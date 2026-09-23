"""
PHASE 8 — WEEKLY MOMENTUM STRATEGY
═══════════════════════════════════════════════════════════════════════════════

Cross-sectional momentum: buy the single strongest large-cap stock each week
based on past 1-week return. Hold CNC delivery position from Wednesday to
Tuesday. Shadow with 2-week CE option via Phase 6 (ChatGPT gated).

Pipeline:
  1. Wednesday 9:00 AM → Load universe, fetch 1-week returns, rank
  2. Wednesday 10:00 AM → Calculate VWAP (9:15-10:00), build signal, send to Ph3
  3. Wednesday 10:00-10:30 → Ph3 places LIMIT order at VWAP, fallback to MARKET
  4. On fill → Ph4 Tier 3 tracking + Ph6 momentum shadow (ChatGPT gated)
  5. Tuesday → 5 exit checks (9:15, 10:00, 12:00, 14:00, 15:15)
  6. TCAS trailing stop: 0.5% activation, 1.5% trail

v1.0.0 (2026-03-04): Initial implementation
"""

import logging
import time as time_module
from datetime import datetime, date, time as dt_time, timedelta
from typing import List, Dict, Optional, Tuple

logger = logging.getLogger('Phase8Momentum')


class Phase8MomentumScanner:
    """
    Weekly momentum scanner, ranker, VWAP calculator, and signal generator.

    Called by orchestrator on Wednesday 9:00 AM.
    Outputs a signal dict to Phase 3 for execution at 10:00 AM.
    """

    def __init__(self, kite, config, capital_manager, telegram, screener_fetcher):
        """
        Args:
            kite: Authenticated KiteConnect instance
            config: Configuration object (with PH8_* params)
            capital_manager: CapitalManager for deployment checks
            telegram: TelegramNotifier for alerts
            screener_fetcher: ScreenerDataFetcher instance
        """
        self.kite = kite
        self.config = config
        self.capital_manager = capital_manager
        self.telegram = telegram
        self.screener = screener_fetcher

        # Instrument token cache: {symbol: instrument_token}
        self._instrument_map = {}
        self._instrument_map_loaded = False

        # Weekly state
        self._last_scan_date = None
        self._last_signal = None

        # Reference to Phase 4 for Tier 3 position queries
        # Set by orchestrator after init: phase8.phase4 = self.phase4
        self.phase4 = None

        logger.info("Phase 8 Momentum Scanner initialized")

    # ═══════════════════════════════════════════════════════════════════════
    # MAIN ENTRY POINT
    # ═══════════════════════════════════════════════════════════════════════

    def run_weekly_scan(self) -> Optional[Dict]:
        """
        Main entry point — called by orchestrator on Wednesday ~9:00 AM.

        Returns:
            Signal dict for Phase 3 if a valid pick is found, None otherwise.
        """
        logger.info("")
        logger.info("=" * 60)
        logger.info("PHASE 8: WEEKLY MOMENTUM SCAN")
        logger.info("=" * 60)

        try:
            # ── Pre-checks ──────────────────────────────────────────
            if not self._pre_scan_checks():
                return None

            # ── Step 1: Load Ph1's master stock list + market cap filter ─
            master_list = self._get_master_stock_list()
            if not master_list:
                logger.error("   No stocks in MASTER_STOCK_LIST — aborting scan")
                self._notify("PH8 SCAN FAILED: Empty MASTER_STOCK_LIST in config")
                return None

            logger.info(f"   Ph1 master list: {len(master_list)} stocks")

            # Filter by market cap using screener lookup
            universe = self._filter_by_market_cap(master_list)
            logger.info(f"   Universe after mcap filter: {len(universe)} stocks (mcap >= "
                        f"{getattr(self.config, 'PH8_MIN_MCAP_CRORE', 25000):,} cr)")

            # ── Step 2: Ensure instrument map loaded ─────────────────
            self._ensure_instrument_map()

            # ── Step 3: Fetch 1-week returns ─────────────────────────
            returns_data = self._calculate_weekly_returns(universe)
            if not returns_data:
                logger.error("   No valid weekly returns calculated — aborting")
                self._notify("PH8 SCAN FAILED: Could not calculate weekly returns (Kite API issue)")
                return None

            # ── Step 4: Filter and rank ──────────────────────────────
            min_return = getattr(self.config, 'PH8_MIN_WEEKLY_RETURN', 0.0)
            positive_returns = [r for r in returns_data if r['weekly_return'] > min_return]

            if not positive_returns:
                logger.info(f"   No stocks with positive weekly return — skipping this week")
                self._notify(f"PH8: No stocks with positive weekly return. Skipping this week.\n"
                             f"Universe: {len(universe)} | Returns calculated: {len(returns_data)}")
                return None

            # Sort descending by weekly return
            ranked = sorted(positive_returns, key=lambda x: x['weekly_return'], reverse=True)
            logger.info(f"   Ranked: {len(ranked)} stocks with positive returns")

            # Log top 5 for visibility
            for i, stock in enumerate(ranked[:5], 1):
                logger.info(f"   #{i}: {stock['symbol']:15s} {stock['weekly_return']:+.2%} "
                            f"(mcap: {stock.get('market_cap_crore', 0):,.0f} cr)")

            # ── Step 5: Select top pick (avoid duplicates) ───────────
            held_symbols = self._get_current_tier3_symbols()
            selected = None
            selected_rank = 0

            for i, stock in enumerate(ranked):
                if stock['symbol'] not in held_symbols:
                    selected = stock
                    selected_rank = i + 1
                    break

            if not selected:
                logger.info(f"   All top stocks already held in Tier 3 — skipping")
                self._notify(f"PH8: Top ranked stocks already held. Skipping this week.\n"
                             f"Held: {', '.join(held_symbols)}")
                return None

            logger.info(f"   SELECTED: {selected['symbol']} (rank #{selected_rank}, "
                        f"{selected['weekly_return']:+.2%})")

            # ── Step 6: Send pick notification (before VWAP) ─────────
            self._notify(
                f"PH8 MOMENTUM PICK\n"
                f"Stock: {selected['symbol']} (#{selected_rank} of {len(ranked)} eligible)\n"
                f"1-Week Return: {selected['weekly_return']:+.2%}\n"
                f"Market Cap: {selected.get('market_cap_crore', 0):,.0f} crore\n"
                f"Waiting for 10:00 AM VWAP entry window..."
            )

            # ── Store for VWAP calculation at 10:00 AM ───────────────
            self._last_scan_date = date.today()
            self._last_signal = selected  # Will be completed with VWAP at 10:00
            return selected  # Orchestrator will call calculate_vwap_and_build_signal at 10:00

        except Exception as e:
            logger.error(f"Phase 8 scan error: {type(e).__name__}: {e}", exc_info=True)
            self._notify(f"PH8 SCAN ERROR: {type(e).__name__}: {e}")
            return None

    def calculate_vwap_and_build_signal(self, scan_result: Dict) -> Optional[Dict]:
        """
        Called at 10:00 AM after the 9:15-10:00 VWAP window closes.
        Calculates VWAP and builds the final signal for Phase 3.

        Args:
            scan_result: Dict from run_weekly_scan()

        Returns:
            Complete signal dict for Phase 3, or None on failure.
        """
        symbol = scan_result.get('symbol', scan_result.get('kite_symbol', ''))
        kite_symbol = scan_result.get('kite_symbol', symbol)

        logger.info(f"   Calculating VWAP for {symbol} (9:15-10:00 window)...")

        try:
            token = self._get_instrument_token(kite_symbol)
            if not token:
                logger.error(f"   No instrument token for {kite_symbol} — using MARKET order")
                return self._build_signal_market_fallback(scan_result)

            vwap = self._calculate_vwap(token)
            if vwap is None or vwap <= 0:
                logger.warning(f"   VWAP calculation failed — using MARKET order fallback")
                return self._build_signal_market_fallback(scan_result)

            logger.info(f"   VWAP (9:15-10:00): {vwap:.2f}")

            # Calculate quantity
            fixed_amount = getattr(self.config, 'PH8_FIXED_AMOUNT', 50000)
            quantity = int(fixed_amount // vwap)
            if quantity <= 0:
                logger.error(f"   Quantity = 0 (stock price {vwap:.2f} > allocation {fixed_amount})")
                self._notify(f"PH8: Cannot buy {symbol} — price {vwap:.2f} exceeds allocation {fixed_amount}")
                return None

            # Check capital availability
            if self.capital_manager:
                cap_check = self.capital_manager.can_enter(symbol, vwap * quantity)
                if not cap_check.get('can_enter', False):
                    reasons = cap_check.get('reasons', ['Unknown'])
                    logger.warning(f"   Capital check failed: {reasons}")
                    self._notify(f"PH8: Capital insufficient for {symbol}. {'; '.join(reasons)}")
                    return None

            return self._build_signal(
                symbol=kite_symbol,
                weekly_return=scan_result.get('weekly_return', 0),
                vwap=vwap,
                quantity=quantity,
                market_cap=scan_result.get('market_cap_crore', 0),
                sector=scan_result.get('sector', ''),
                rank=scan_result.get('rank', 1),
            )

        except Exception as e:
            logger.error(f"   VWAP/signal build error: {type(e).__name__}: {e}", exc_info=True)
            return self._build_signal_market_fallback(scan_result)

    # ═══════════════════════════════════════════════════════════════════════
    # PRE-SCAN CHECKS
    # ═══════════════════════════════════════════════════════════════════════

    def _pre_scan_checks(self) -> bool:
        """Run all pre-scan validations. Returns True if scan should proceed."""

        # 1. Master switch
        if not getattr(self.config, 'ENABLE_PH8', False):
            logger.info("   ENABLE_PH8 = False — Phase 8 disabled")
            return False

        # 2. Day check
        today = date.today()
        scan_day = getattr(self.config, 'PH8_SCAN_DAY', 2)  # 2 = Wednesday
        if today.weekday() != scan_day:
            logger.info(f"   Today is {today.strftime('%A')} — not scan day "
                        f"(day {scan_day}). Skipping.")
            return False

        # 3. Already scanned today?
        if self._last_scan_date == today:
            logger.info("   Already scanned today — skipping duplicate")
            return False

        # 4. Max concurrent positions
        tier3_count = self._get_tier3_position_count()
        max_concurrent = getattr(self.config, 'PH8_MAX_CONCURRENT', 2)
        if tier3_count >= max_concurrent:
            held_info = ', '.join(self._get_current_tier3_symbols()) or 'N/A'
            logger.info(f"   Max concurrent ({max_concurrent}) reached "
                        f"(current: {tier3_count}). Held: {held_info}")
            self._notify(
                f"PH8: MAX CONCURRENT REACHED ({tier3_count}/{max_concurrent})\n"
                f"Skipping this Wednesday's pick\n"
                f"Held: {held_info}"
            )
            return False

        logger.info("   Pre-checks passed")
        return True

    # ═══════════════════════════════════════════════════════════════════════
    # STOCK UNIVERSE (from Ph1's config + market cap filter)
    # ═══════════════════════════════════════════════════════════════════════

    def _get_master_stock_list(self) -> List[str]:
        """
        Read Ph1's F&O master stock list from config.MASTER_STOCK_LIST.
        This is the SAME list Phase 1 uses — no separate universe.
        """
        master = getattr(self.config, 'MASTER_STOCK_LIST', None)
        if master and len(master) > 0:
            return list(master)

        logger.warning("   MASTER_STOCK_LIST not found in config — trying fallback")
        # Fallback: try to read from any known config attr
        for attr in ['FNO_STOCK_LIST', 'STOCK_LIST', 'NSE_STOCKS']:
            alt = getattr(self.config, attr, None)
            if alt and len(alt) > 0:
                logger.info(f"   Using fallback config.{attr}: {len(alt)} stocks")
                return list(alt)
        return []

    def _filter_by_market_cap(self, symbols: List[str]) -> List[Dict]:
        """
        Apply market cap > PH8_MIN_MCAP_CRORE filter using screener lookup.
        If screener lookup is empty, return ALL symbols unfiltered (with WARNING).

        Returns:
            List of dicts: [{"symbol": "RELIANCE", "kite_symbol": "RELIANCE",
                             "market_cap_crore": 1850000, "sector": "..."}, ...]
        """
        min_mcap = getattr(self.config, 'PH8_MIN_MCAP_CRORE', 25000)
        mcap_lookup = {}
        try:
            mcap_lookup = self.screener.get_mcap_lookup()
        except Exception as e:
            logger.warning(f"   Screener mcap lookup failed: {e}")

        if not mcap_lookup:
            # No market cap data — use all symbols unfiltered
            logger.warning(f"   No market cap data available — using all {len(symbols)} stocks unfiltered")
            return [{'symbol': s, 'kite_symbol': s, 'market_cap_crore': 0, 'sector': 'Unknown'}
                    for s in symbols]

        filtered = []
        for sym in symbols:
            mcap_info = mcap_lookup.get(sym, {})
            mcap = mcap_info.get('market_cap_crore', 0)
            if mcap >= min_mcap:
                filtered.append({
                    'symbol': sym,
                    'kite_symbol': sym,
                    'market_cap_crore': mcap,
                    'sector': mcap_info.get('sector', 'Unknown'),
                })

        if not filtered:
            # Market cap filter eliminated everything — fall back to all symbols
            logger.warning(f"   Market cap filter ({min_mcap:,} cr) eliminated all stocks — "
                           f"using top {len(symbols)} unfiltered")
            return [{'symbol': s, 'kite_symbol': s, 'market_cap_crore': 0, 'sector': 'Unknown'}
                    for s in symbols]

        return filtered

    # ═══════════════════════════════════════════════════════════════════════
    # WEEKLY RETURN CALCULATION
    # ═══════════════════════════════════════════════════════════════════════

    def _calculate_weekly_returns(self, universe: List[Dict]) -> List[Dict]:
        """
        Fetch 1-week returns for all symbols via Kite historical API.

        For each symbol: (close[-1] - close[-6]) / close[-6]
        Uses last 10 trading days with holiday buffer.

        Returns:
            List of dicts with weekly_return added to each stock.
        """
        results = []
        api_calls = 0
        errors = 0
        skipped = 0

        today = date.today()
        # Buffer for holidays: fetch 15 calendar days to get at least 6 trading sessions
        from_date = today - timedelta(days=15)
        to_date = today - timedelta(days=1)  # Yesterday's close

        for stock in universe:
            symbol = stock.get('kite_symbol', stock.get('symbol', ''))
            if not symbol:
                skipped += 1
                continue

            token = self._get_instrument_token(symbol)
            if not token:
                skipped += 1
                continue

            try:
                # Rate limit: ~3 req/sec for Kite historical
                if api_calls > 0 and api_calls % 3 == 0:
                    time_module.sleep(0.4)

                candles = self.kite.historical_data(
                    token, from_date, to_date, "day"
                )
                api_calls += 1

                if not candles or len(candles) < 6:
                    skipped += 1
                    continue

                # Most recent close = candles[-1], 5 sessions ago = candles[-6]
                close_today = candles[-1]['close']
                close_5_ago = candles[-6]['close']

                if close_5_ago <= 0:
                    skipped += 1
                    continue

                weekly_return = (close_today - close_5_ago) / close_5_ago

                result = stock.copy()
                result['weekly_return'] = weekly_return
                result['close_latest'] = close_today
                result['close_5_ago'] = close_5_ago
                result['instrument_token'] = token
                results.append(result)

            except Exception as e:
                errors += 1
                if errors <= 5:
                    logger.debug(f"   {symbol}: historical data error: {e}")

        logger.info(f"   Returns calculated: {len(results)} | "
                    f"Skipped: {skipped} | Errors: {errors} | "
                    f"API calls: {api_calls}")

        return results

    # ═══════════════════════════════════════════════════════════════════════
    # VWAP CALCULATION
    # ═══════════════════════════════════════════════════════════════════════

    def _calculate_vwap(self, instrument_token: int) -> Optional[float]:
        """
        Calculate VWAP of 9:15-10:00 AM window using 1-minute candles.

        VWAP = Sum(Typical_Price x Volume) / Sum(Volume)
        Typical Price = (High + Low + Close) / 3

        Returns:
            VWAP price, or None if insufficient data.
        """
        try:
            today = date.today()
            vwap_start = getattr(self.config, 'PH8_VWAP_WINDOW_START', dt_time(9, 15))
            vwap_end = getattr(self.config, 'PH8_VWAP_WINDOW_END', dt_time(10, 0))

            from_dt = datetime.combine(today, vwap_start)
            to_dt = datetime.combine(today, vwap_end)

            candles = self.kite.historical_data(
                instrument_token, from_dt, to_dt, "minute"
            )

            if not candles or len(candles) < 5:
                logger.warning(f"   VWAP: Only {len(candles) if candles else 0} candles "
                               f"in window — insufficient")
                return None

            numerator = 0.0
            denominator = 0.0

            for c in candles:
                high = c.get('high', 0)
                low = c.get('low', 0)
                close = c.get('close', 0)
                volume = c.get('volume', 0)

                if volume <= 0:
                    continue

                typical_price = (high + low + close) / 3.0
                numerator += typical_price * volume
                denominator += volume

            if denominator <= 0:
                logger.warning("   VWAP: Zero total volume in window")
                return None

            vwap = numerator / denominator
            logger.info(f"   VWAP = {vwap:.2f} ({len(candles)} candles, "
                        f"volume: {int(denominator):,})")
            return round(vwap, 2)

        except Exception as e:
            logger.error(f"   VWAP calculation error: {type(e).__name__}: {e}")
            return None

    # ═══════════════════════════════════════════════════════════════════════
    # SIGNAL BUILDING
    # ═══════════════════════════════════════════════════════════════════════

    def _build_signal(self, symbol: str, weekly_return: float, vwap: float,
                      quantity: int, market_cap: float, sector: str,
                      rank: int = 1) -> Dict:
        """
        Build signal dict matching the format Phase 3 expects.

        The "source": "PH8_MOMENTUM" tag is how Ph3, Ph4, Ph6
        distinguish momentum orders from V-Recovery orders.
        """
        return {
            "source": "PH8_MOMENTUM",
            "symbol": symbol,
            "exchange": "NSE",
            "direction": "BUY",
            "product": getattr(self.config, 'PH8_PRODUCT', 'CNC'),
            "quantity": quantity,
            "limit_price": vwap,
            "order_type": "LIMIT",
            "validity": "DAY",
            "weekly_return_pct": round(weekly_return * 100, 2),
            "market_cap_crore": market_cap,
            "sector": sector,
            "rank": rank,
            "entry_window_start": getattr(self.config, 'PH8_ENTRY_WINDOW_START',
                                          dt_time(10, 0)).strftime('%H:%M'),
            "entry_window_end": getattr(self.config, 'PH8_ENTRY_WINDOW_END',
                                        dt_time(10, 30)).strftime('%H:%M'),
            "fallback_to_market": getattr(self.config, 'PH8_FALLBACK_TO_MARKET', True),
            "no_gtt": True,  # Phase 8 uses TCAS, not GTT
        }

    def _build_signal_market_fallback(self, scan_result: Dict) -> Optional[Dict]:
        """Build a MARKET order signal when VWAP cannot be calculated."""
        symbol = scan_result.get('kite_symbol', scan_result.get('symbol', ''))
        close = scan_result.get('close_latest', 0)
        if close <= 0:
            # Try to get current quote
            try:
                quotes = self.kite.quote([f"NSE:{symbol}"])
                close = quotes.get(f"NSE:{symbol}", {}).get('last_price', 0)
            except Exception:
                pass

        if close <= 0:
            logger.error(f"   Cannot determine price for {symbol} — aborting")
            return None

        fixed_amount = getattr(self.config, 'PH8_FIXED_AMOUNT', 50000)
        quantity = int(fixed_amount // close)
        if quantity <= 0:
            return None

        signal = self._build_signal(
            symbol=symbol,
            weekly_return=scan_result.get('weekly_return', 0),
            vwap=0,
            quantity=quantity,
            market_cap=scan_result.get('market_cap_crore', 0),
            sector=scan_result.get('sector', ''),
            rank=scan_result.get('rank', 1),
        )
        # Override to MARKET since VWAP is unavailable
        signal['order_type'] = 'MARKET'
        signal['limit_price'] = 0
        logger.info(f"   Using MARKET order fallback for {symbol}")
        return signal

    # ═══════════════════════════════════════════════════════════════════════
    # TIER 3 POSITION QUERIES
    # ═══════════════════════════════════════════════════════════════════════

    def _get_tier3_position_count(self) -> int:
        """Get count of active Tier 3 (PH8_MOMENTUM) positions."""
        if self.phase4 and hasattr(self.phase4, 'get_tier3_position_count'):
            return self.phase4.get_tier3_position_count()
        return 0

    def _get_current_tier3_symbols(self) -> List[str]:
        """Get list of symbols currently held in Tier 3."""
        if self.phase4 and hasattr(self.phase4, 'get_tier3_held_symbols'):
            return self.phase4.get_tier3_held_symbols()
        return []

    # ═══════════════════════════════════════════════════════════════════════
    # INSTRUMENT TOKEN HANDLING
    # ═══════════════════════════════════════════════════════════════════════

    def _ensure_instrument_map(self):
        """Load NSE instrument token map (cached once per session)."""
        if self._instrument_map_loaded:
            return

        try:
            instruments = self.kite.instruments("NSE")
            self._instrument_map = {
                inst['tradingsymbol']: inst['instrument_token']
                for inst in instruments
                if inst.get('instrument_type') == 'EQ'
            }
            self._instrument_map_loaded = True
            logger.info(f"   Instrument map loaded: {len(self._instrument_map)} NSE equities")
        except Exception as e:
            logger.error(f"   Failed to load instrument map: {e}")

    def _get_instrument_token(self, symbol: str) -> Optional[int]:
        """Get instrument token for a symbol."""
        token = self._instrument_map.get(symbol)
        if token:
            return int(token)
        return None

    # ═══════════════════════════════════════════════════════════════════════
    # NOTIFICATIONS
    # ═══════════════════════════════════════════════════════════════════════

    def _notify(self, message: str):
        """Telegram notification — wrapped in try/except, never crashes."""
        prefix = getattr(self.config, 'PH8_TELEGRAM_PREFIX', 'PH8')
        full_msg = f"{prefix}: {message}" if not message.startswith(prefix) else message
        try:
            if self.telegram:
                self.telegram.send_message(full_msg)
        except Exception as e:
            logger.error(f"   Telegram notification failed: {e}")


# ═══════════════════════════════════════════════════════════════════════════════
# STANDALONE TEST
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(name)s] %(message)s')
    print("Phase 8 Momentum Scanner — module loaded OK")
    print("Run via orchestrator for live operation.")
