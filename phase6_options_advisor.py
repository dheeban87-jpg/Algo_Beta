"""
Phase 6: ChatGPT Options Advisory System v6.0.0 (Paper Trading Only)

Triggered by Phase 3 after an equity BUY order is placed.
Fetches options chain → feeds to ChatGPT → recommends Bull Call Spread → paper trades.
Tracks paper P&L to measure ChatGPT accuracy over time.

Flow:
  Phase 2 scores stock → ChatGPT says GO → Phase 3 places equity BUY
      ↓
  Phase 6 fetches options chain for THAT stock → ChatGPT recommends spread
      ↓
  Paper trade logged → premiums tracked → P&L calculated at EOD

Author: Algo_Beta v6.0.0
"""

import logging
import json
import time
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum

try:
    from config import Config as _MainConfig
    _MASTER_STOCK_LIST = getattr(_MainConfig, 'MASTER_STOCK_LIST', [])
except ImportError:
    _MASTER_STOCK_LIST = []

try:
    from mission_db import get_mission_db
    DB_AVAILABLE = True
except ImportError:
    DB_AVAILABLE = False
    get_mission_db = None

logger = logging.getLogger('Phase6_OptionsAdvisor')


# ═══════════════════════════════════════════════════════════════════════════════
# ENUMS & DATA CLASSES
# ═══════════════════════════════════════════════════════════════════════════════

class AdvisoryStatus(Enum):
    OPEN = "OPEN"
    TARGET_HIT = "TARGET_HIT"
    STOP_HIT = "STOP_HIT"
    EXPIRED = "EXPIRED"
    EOD_CLOSE = "EOD_CLOSE"
    PROFIT_LOCK_EXIT = "PROFIT_LOCK_EXIT"   # v6.2: TCAS floor breach


@dataclass
class OptionLeg:
    """Single leg of a spread."""
    strike: float
    option_type: str           # "CE" or "PE"
    action: str                # "BUY" or "SELL"
    lot_size: int
    entry_premium: float
    current_premium: float = 0.0
    tradingsymbol: str = ""

    # v6.1: Live order tracking
    order_id: str = ""             # Kite order ID (empty = paper)
    fill_price: float = 0.0        # Actual fill price from Kite
    fill_quantity: int = 0          # Filled quantity
    order_status: str = "PAPER"     # PAPER / COMPLETE / REJECTED / CANCELLED

    def to_dict(self) -> Dict:
        return {
            'strike': self.strike,
            'option_type': self.option_type,
            'action': self.action,
            'lot_size': self.lot_size,
            'entry_premium': self.entry_premium,
            'current_premium': self.current_premium,
            'tradingsymbol': self.tradingsymbol,
            'order_id': self.order_id,
            'fill_price': self.fill_price,
            'fill_quantity': self.fill_quantity,
            'order_status': self.order_status,
        }


@dataclass
class OptionsChainData:
    """Processed options chain for a single stock."""
    symbol: str
    spot_price: float
    expiry: str                           # "YYYY-MM-DD"
    expiry_dt: date = None
    strikes: List[Dict] = field(default_factory=list)
    pcr: float = 0.0
    max_pain: float = 0.0
    total_ce_oi: int = 0
    total_pe_oi: int = 0
    atm_strike: float = 0.0
    lot_size: int = 0
    oi_buildup: Dict = field(default_factory=dict)
    fetched_at: str = ""

    def to_dict(self) -> Dict:
        return {
            'symbol': self.symbol,
            'spot_price': self.spot_price,
            'expiry': self.expiry,
            'strikes': self.strikes,
            'pcr': self.pcr,
            'max_pain': self.max_pain,
            'total_ce_oi': self.total_ce_oi,
            'total_pe_oi': self.total_pe_oi,
            'atm_strike': self.atm_strike,
            'lot_size': self.lot_size,
            'oi_buildup': self.oi_buildup,
        }


@dataclass
class SpreadAdvisory:
    """A complete Bull Call Spread recommendation from ChatGPT."""
    id: int
    timestamp: str
    symbol: str
    spot_price: float
    equity_order_id: str
    equity_entry_price: float
    spread_type: str                      # "BULL_CALL_SPREAD"
    legs: List[OptionLeg] = field(default_factory=list)
    max_profit: float = 0.0
    max_loss: float = 0.0
    breakeven: float = 0.0
    net_debit_per_share: float = 0.0
    confidence: int = 0
    reasoning: str = ""
    risk_reward_ratio: float = 0.0
    expiry: str = ""
    lot_size: int = 0

    # Paper trade tracking
    status: AdvisoryStatus = AdvisoryStatus.OPEN
    entry_net_premium: float = 0.0
    current_net_premium: float = 0.0
    paper_pnl: float = 0.0
    paper_pnl_pct: float = 0.0
    exit_time: str = ""
    exit_reason: str = ""

    # Chain context
    pcr: float = 0.0
    max_pain: float = 0.0
    web_news: str = ""

    # DB row id
    db_id: Optional[int] = None

    # v6.1: Live order tracking
    order_mode: str = "PAPER"      # PAPER / LIVE / PARTIAL
    buy_order_id: str = ""         # Kite order ID for BUY leg
    sell_order_id: str = ""        # Kite order ID for SELL leg

    # v6.2: Options TCAS tracking
    peak_pnl_pct: float = 0.0          # Highest P&L % ever reached
    profit_lock_pct: float = 0.0       # Current locked floor (ratchets up only)
    tcas_active: bool = False           # True once first tier breached

    # v6.3: DTE Timeline Manager
    dte_at_entry: int = -1             # Days to expiry at advisory creation (-1 = not set)
    dte_target_pct: Optional[int] = None  # Override target % for short-DTE entries

    @property
    def is_open(self) -> bool:
        return self.status == AdvisoryStatus.OPEN

    @property
    def is_live(self) -> bool:
        return self.order_mode in ("LIVE", "PARTIAL")


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN ENGINE
# ═══════════════════════════════════════════════════════════════════════════════

class Phase6OptionsAdvisor:
    """
    Phase 6: ChatGPT Options Advisory System (Paper Trading Only)

    Architecture:
    1. NFO Instrument Cache — kite.instruments("NFO"), cached 4 hrs
    2. Options Chain Builder — filter to stock + nearest expiry + ATM±10
    3. Options Calculator   — PCR, Max Pain, OI buildup
    4. ChatGPT Strategist   — recommends Bull Call Spread
    5. Paper Trade Tracker   — log, track premiums, calculate paper P&L
    6. Telegram Dashboard    — notifications + daily summary
    """

    def __init__(
        self,
        kite,
        config=None,
        telegram=None,
        chatgpt_advisor=None,
        stock_universe: List[str] = None,
    ):
        self.kite = kite
        self.config = config    # Will use getattr with defaults
        self.telegram = telegram
        self.chatgpt = chatgpt_advisor
        self.stock_universe = stock_universe or list(_MASTER_STOCK_LIST)

        # NFO instruments cache
        self._nfo_instruments: List[Dict] = []
        self._nfo_cache_time: Optional[datetime] = None
        self._fno_stock_set: set = set()
        self._lot_size_map: Dict[str, int] = {}

        # Advisory tracking
        self.advisories: List[SpreadAdvisory] = []
        self._next_id = 1

        # Daily stats
        self.daily_stats = {
            'advisories_generated': 0,
            'profitable': 0,
            'unprofitable': 0,
            'total_paper_pnl': 0.0,
            'best_trade': 0.0,
            'worst_trade': 0.0,
        }

        # DB
        self._db = None
        if DB_AVAILABLE:
            try:
                self._db = get_mission_db()
            except Exception:
                pass

        # v6.1: Live order mode
        self._live_enabled = getattr(self.config, 'PH6_LIVE_ORDERS_ENABLED', False)

        # v1.0.0: Candlestick pattern bonus tracking
        self._pattern_bonuses: Dict[str, Dict] = {}

        # v1.0.0: ORB Advisory reference (set by orchestrator after init)
        self._orb_advisory = None

        # v1.6.0: PH9 directive gate (set by orchestrator._apply_phase_directives)
        self._ph9_hold = False   # True = PH9 said HOLD, block all new advisories

        logger.info("=" * 70)
        mode_str = "LIVE ORDERS" if self._live_enabled else "Paper Trading"
        logger.info(f"PHASE 6: OPTIONS ADVISORY SYSTEM v6.1.0 ({mode_str})")
        logger.info("=" * 70)
        logger.info(f"   Strategy: BULL CALL SPREAD (always bullish)")
        logger.info(f"   Mode: {'LIVE — real NFO orders via Kite' if self._live_enabled else 'ADVISORY ONLY (no real orders)'}")
        logger.info(f"   Trigger: After Phase 3 equity BUY order")
        if self._live_enabled:
            logger.info(f"   Product: {getattr(self.config, 'PH6_OPTIONS_PRODUCT_TYPE', 'MIS')}")
            logger.info(f"   Max Lots: {getattr(self.config, 'PH6_MAX_LOTS', 1)}")
            logger.info(f"   Entry Buffer: {getattr(self.config, 'PH6_ENTRY_LIMIT_BUFFER_PCT', 0.5)}%")
        logger.info("=" * 70)

    # ───────────────────────────────────────────────────────────────
    # CANDLESTICK PATTERN BONUS (v1.0.0)
    # ───────────────────────────────────────────────────────────────

    def apply_pattern_bonus(self, symbol: str, signal):
        """Apply candlestick pattern bonus to options confidence.

        Called by orchestrator when a bullish pattern is detected at a key level.
        If a Phase 6 entry decision is pending or about to be made for this symbol,
        the bonus points are added to the effective score.

        Args:
            symbol: Stock symbol
            signal: PatternSignal dataclass from candlestick_pattern_detector
        """
        self._pattern_bonuses[symbol] = {
            'bonus_points': signal.bonus_points,
            'pattern_type': signal.pattern_type,
            'nearby_levels': signal.nearby_levels,
            'timestamp': signal.timestamp,
            'expires_after_candles': getattr(self.config, 'PATTERN_BONUS_EXPIRY_CANDLES', 2)
        }

        logger.info(
            f"PH6 BONUS: {symbol} +{signal.bonus_points}pts "
            f"via {signal.pattern_type} at {signal.nearby_levels}"
        )

    def get_pattern_bonus(self, symbol: str) -> int:
        """Get the current pattern bonus for a symbol, if any and not expired.

        Args:
            symbol: Stock symbol

        Returns:
            Bonus points (0 if none or expired)
        """
        bonus = self._pattern_bonuses.get(symbol)
        if not bonus:
            return 0
        if bonus.get('expires_after_candles', 0) <= 0:
            return 0
        return bonus.get('bonus_points', 0)

    def decrement_pattern_bonus(self, symbol: str):
        """Decrement the candle expiry counter for a pattern bonus.

        Called after each 15-min candle to age out stale bonuses.
        """
        bonus = self._pattern_bonuses.get(symbol)
        if bonus and bonus.get('expires_after_candles', 0) > 0:
            bonus['expires_after_candles'] -= 1
            if bonus['expires_after_candles'] <= 0:
                logger.debug(f"PH6: Pattern bonus for {symbol} expired")

    # ───────────────────────────────────────────────────────────────
    # ORB ADVISORY PULL (v1.0.0)
    # ───────────────────────────────────────────────────────────────

    def set_orb_advisory(self, orb_advisory):
        """Set reference to ORB Advisory for pull-model queries.

        Called by orchestrator after both modules are initialized.

        Args:
            orb_advisory: ORBAdvisory instance (or None)
        """
        self._orb_advisory = orb_advisory

    def get_orb_bonus(self, symbol: str) -> int:
        """Pull ORB status and return confidence bonus.

        COMPRESSION_DETECTED → +ORB_COMPRESSION_BONUS (default +8)
        UPSIDE_BREAKOUT      → +ORB_BREAKOUT_BONUS    (default +10)
        All other states     → 0

        Args:
            symbol: Stock symbol

        Returns:
            Bonus points to add to effective confidence
        """
        if not self._orb_advisory:
            return 0

        status = self._orb_advisory.get_status(symbol)
        if not status:
            return 0

        orb_status = status.get('status', '')

        if orb_status == 'COMPRESSION_DETECTED':
            bonus = getattr(self.config, 'ORB_COMPRESSION_BONUS', 8)
            logger.info(f"PH6 ORB: {symbol} COMPRESSION → +{bonus}pts")
            return bonus
        elif orb_status == 'UPSIDE_BREAKOUT':
            bonus = getattr(self.config, 'ORB_BREAKOUT_BONUS', 10)
            logger.info(f"PH6 ORB: {symbol} UPSIDE_BREAKOUT → +{bonus}pts")
            return bonus

        return 0

    # ───────────────────────────────────────────────────────────────
    # NFO INSTRUMENTS CACHE
    # ───────────────────────────────────────────────────────────────

    def _load_nfo_instruments(self):
        """
        Load and cache NFO instruments from Kite.
        Filters to only CE/PE for stocks in MASTER_STOCK_LIST.
        ~80,000 raw records → ~filtered to our universe.
        """
        try:
            start = time.time()
            raw = self.kite.instruments("NFO")
            elapsed = time.time() - start
            logger.info(f"   NFO instruments fetched: {len(raw)} records in {elapsed:.1f}s")

            stock_set = set(self.stock_universe)
            filtered = []
            lot_sizes = {}
            fno_stocks = set()

            for inst in raw:
                name = inst.get('name', '')
                inst_type = inst.get('instrument_type', '')

                if name not in stock_set:
                    continue
                if inst_type not in ('CE', 'PE'):
                    continue

                filtered.append(inst)
                fno_stocks.add(name)
                if name not in lot_sizes:
                    lot_sizes[name] = inst.get('lot_size', 1)

            self._nfo_instruments = filtered
            self._nfo_cache_time = datetime.now()
            self._fno_stock_set = fno_stocks
            self._lot_size_map = lot_sizes

            logger.info(f"   Filtered to {len(filtered)} options for {len(fno_stocks)} F&O stocks")

        except Exception as e:
            logger.error(f"Failed to load NFO instruments: {e}")

    def _is_nfo_cache_stale(self) -> bool:
        if not self._nfo_cache_time:
            return True
        cache_hours = getattr(self.config, 'PH6_INSTRUMENTS_CACHE_HOURS',
                              getattr(self.config, 'INSTRUMENTS_CACHE_HOURS', 4))
        age_hours = (datetime.now() - self._nfo_cache_time).total_seconds() / 3600
        return age_hours >= cache_hours

    # ───────────────────────────────────────────────────────────────
    # OPTIONS CHAIN BUILDER
    # ───────────────────────────────────────────────────────────────

    def _get_nearest_expiry(self, symbol: str) -> Optional[date]:
        """Find nearest MONTHLY expiry for a stock.

        Stock options on NSE expire last Thursday of month.
        Filters out any weekly expiries (if NSE adds them in future)
        by only keeping the latest expiry per calendar month.
        """
        today = date.today()
        expiries = set()

        for inst in self._nfo_instruments:
            if inst.get('name') == symbol:
                exp = inst.get('expiry')
                if exp:
                    if isinstance(exp, datetime):
                        exp = exp.date()
                    if isinstance(exp, date) and exp >= today:
                        expiries.add(exp)

        if not expiries:
            return None

        # Keep only the LAST expiry per month (monthly expiry = last Thursday)
        monthly = {}
        for exp in expiries:
            month_key = (exp.year, exp.month)
            if month_key not in monthly or exp > monthly[month_key]:
                monthly[month_key] = exp

        monthly_expiries = sorted(monthly.values())
        return monthly_expiries[0] if monthly_expiries else None

    # ───────────────────────────────────────────────────────────────
    # DTE TIMELINE MANAGER (v1.0.0) — OPTIONS SAFETY GATE
    # ───────────────────────────────────────────────────────────────

    def _check_dte_eligibility(self, expiry_date) -> dict:
        """Check if an expiry date has enough DTE for safe options trading.

        Called AFTER _get_nearest_expiry() but BEFORE _build_options_chain().
        Acts as a safety gate that either:
          - Allows entry with the given expiry (possibly with adjusted targets)
          - Rolls to next monthly expiry if DTE too low and ROLL enabled
          - Blocks entry entirely if no safe expiry exists

        Args:
            expiry_date: The nearest monthly expiry date (date object)

        Returns:
            dict with keys:
                eligible: bool - True if safe to proceed
                dte: int - days to expiry
                expiry_date: date - original or rolled expiry
                action: str - ALLOW / ALLOW_TIGHT / ROLL / BLOCK
                target_pct: int - adjusted target % of max profit
                reason: str - human-readable explanation
                rolled: bool - True if expiry was changed to next month
        """
        today = date.today()
        if isinstance(expiry_date, datetime):
            expiry_date = expiry_date.date()
        dte = (expiry_date - today).days

        min_dte = getattr(self.config, 'PH6_MIN_DTE', 3)
        sweet_min = getattr(self.config, 'PH6_SWEET_SPOT_MIN_DTE', 8)
        sweet_max = getattr(self.config, 'PH6_SWEET_SPOT_MAX_DTE', 15)
        far_dte = getattr(self.config, 'PH6_FAR_DTE', 25)
        roll_enabled = getattr(self.config, 'PH6_ROLL_TO_NEXT_MONTH', True)

        target_normal = getattr(self.config, 'PH6_TARGET_PCT_OF_MAX',
                                getattr(self.config, 'TARGET_PCT_OF_MAX', 80))
        target_tight = getattr(self.config, 'PH6_DTE_SHORT_TARGET_PCT', 60)

        result = {
            'eligible': False,
            'dte': dte,
            'expiry_date': expiry_date,
            'action': 'BLOCK',
            'target_pct': target_normal,
            'reason': '',
            'rolled': False,
        }

        # --- HARD BLOCK: DTE 0-1 (expiry day or day before) ---
        if dte <= 1:
            result['reason'] = (
                f"DTE={dte}: Theta lethal "
                f"({'~8+' if dte == 0 else '~5-8'}/day on 20 premium). "
                f"Physical delivery risk. HARD BLOCK."
            )
            if roll_enabled:
                next_expiry = self._get_next_monthly_expiry(expiry_date)
                if next_expiry:
                    next_dte = (next_expiry - today).days
                    result['eligible'] = True
                    result['expiry_date'] = next_expiry
                    result['dte'] = next_dte
                    result['action'] = 'ROLL'
                    result['rolled'] = True
                    result['reason'] = (
                        f"Original expiry {expiry_date} has DTE={dte} (BLOCKED). "
                        f"Rolled to next month: {next_expiry} (DTE={next_dte})."
                    )
            return result

        # --- BLOCK or ROLL: DTE 2 to min_dte ---
        if dte <= min_dte:
            result['reason'] = (
                f"DTE={dte}: Below minimum ({min_dte}). "
                f"Theta ~3.50-5.00/day on 20 premium. "
                f"Directionally correct trades still lose to decay."
            )
            if roll_enabled:
                next_expiry = self._get_next_monthly_expiry(expiry_date)
                if next_expiry:
                    next_dte = (next_expiry - today).days
                    result['eligible'] = True
                    result['expiry_date'] = next_expiry
                    result['dte'] = next_dte
                    result['action'] = 'ROLL'
                    result['rolled'] = True
                    result['reason'] = (
                        f"Original expiry {expiry_date} has DTE={dte} (below min {min_dte}). "
                        f"Rolled to next month: {next_expiry} (DTE={next_dte})."
                    )
            return result

        # --- ALLOWED with TIGHT targets: DTE 4 to sweet_min-1 ---
        if dte < sweet_min:
            result['eligible'] = True
            result['action'] = 'ALLOW_TIGHT'
            result['target_pct'] = target_tight
            result['reason'] = (
                f"DTE={dte}: Below sweet spot ({sweet_min}-{sweet_max}). "
                f"Theta noticeable (~1.20-2.00/day). "
                f"Target tightened to {target_tight}% of max profit."
            )
            return result

        # --- SWEET SPOT: DTE 8-15 ---
        if dte <= sweet_max:
            result['eligible'] = True
            result['action'] = 'ALLOW'
            result['reason'] = (
                f"DTE={dte}: Sweet spot ({sweet_min}-{sweet_max}). "
                f"Optimal theta/premium balance. Full operation."
            )
            return result

        # --- ALLOWED: DTE 16-25 ---
        if dte <= far_dte:
            result['eligible'] = True
            result['action'] = 'ALLOW'
            result['reason'] = (
                f"DTE={dte}: Good time value, slightly higher premium cost. "
                f"Standard operation."
            )
            return result

        # --- FAR EXPIRY: DTE 25+ ---
        result['eligible'] = True
        result['action'] = 'ALLOW'
        result['reason'] = (
            f"DTE={dte}: Far expiry. Premium expensive, lower leverage. "
            f"Standard operation but ROI per invested is lower."
        )
        return result

    def _get_next_monthly_expiry(self, current_expiry) -> Optional[date]:
        """Find the next monthly expiry AFTER the given one.

        Used by DTE gate to roll forward when current month's expiry is too close.
        Returns None if no future expiry found in instruments cache.

        Args:
            current_expiry: Current (too close) monthly expiry date

        Returns:
            Next monthly expiry date, or None
        """
        if isinstance(current_expiry, datetime):
            current_expiry = current_expiry.date()

        expiries = set()
        for inst in self._nfo_instruments:
            exp = inst.get('expiry')
            if exp:
                if isinstance(exp, datetime):
                    exp = exp.date()
                if isinstance(exp, date) and exp > current_expiry:
                    expiries.add(exp)

        if not expiries:
            return None

        # Keep only last expiry per month (monthly expiry = last Thursday)
        monthly = {}
        for exp in expiries:
            month_key = (exp.year, exp.month)
            if month_key not in monthly or exp > monthly[month_key]:
                monthly[month_key] = exp

        future_monthlies = sorted(monthly.values())
        return future_monthlies[0] if future_monthlies else None

    def _send_dte_telegram(self, symbol: str, dte_check: dict):
        """Send Telegram notification for DTE gate decisions.

        Args:
            symbol: Stock symbol
            dte_check: Result dict from _check_dte_eligibility()
        """
        if not self.telegram:
            return

        action = dte_check.get('action', 'BLOCK')
        dte = dte_check.get('dte', 0)
        expiry = dte_check.get('expiry_date', '')
        reason = dte_check.get('reason', '')

        if action == 'BLOCK':
            msg = (
                f"OPTIONS BLOCKED -- {symbol}\n"
                f"{'=' * 35}\n"
                f"Nearest expiry: {expiry}\n"
                f"Days to expiry: {dte}\n"
                f"Min required: {getattr(self.config, 'PH6_MIN_DTE', 3)}\n"
                f"\n"
                f"Reason: {reason}\n"
                f"\n"
                f"Action: No options advisory generated"
            )
        elif action == 'ROLL':
            msg = (
                f"EXPIRY ROLL -- {symbol}\n"
                f"{'=' * 35}\n"
                f"Rolled to: {expiry} (DTE={dte})\n"
                f"\n"
                f"Reason: {reason}\n"
                f"\n"
                f"Action: Building options chain on new expiry"
            )
        elif action == 'ALLOW_TIGHT':
            target_pct = dte_check.get('target_pct', 60)
            msg = (
                f"DTE SHORT -- {symbol}\n"
                f"{'=' * 35}\n"
                f"Expiry: {expiry} | DTE: {dte}\n"
                f"\n"
                f"Target tightened: {target_pct}% of max profit\n"
                f"Reason: {reason}\n"
                f"\n"
                f"Advisory generated with adjusted parameters"
            )
        else:
            return  # No notification for normal ALLOW

        try:
            self.telegram.send_message(msg)
        except Exception:
            pass

    def _build_options_chain(self, symbol: str,
                             override_expiry: Optional[date] = None) -> Optional[OptionsChainData]:
        """
        Build complete options chain for a symbol.

        1. Get spot price
        2. Filter instruments to nearest expiry (or use override_expiry from DTE gate)
        3. ATM ±N strikes
        4. Batch kite.quote() for OI + LTP
        5. Calculate PCR, Max Pain, OI buildup
        """
        try:
            # Step 1: Spot price
            nse_quote = self.kite.quote([f"NSE:{symbol}"])
            spot_key = f"NSE:{symbol}"
            if spot_key not in nse_quote:
                logger.warning(f"   No NSE quote for {symbol}")
                return None
            spot_price = nse_quote[spot_key].get('last_price', 0)
            if spot_price <= 0:
                return None

            # Step 2: Nearest expiry (or use DTE-rolled override)
            expiry_date = override_expiry or self._get_nearest_expiry(symbol)
            if not expiry_date:
                logger.warning(f"   No expiry found for {symbol}")
                return None

            expiry_str = expiry_date.strftime('%Y-%m-%d')

            # Step 3: Filter instruments for this symbol + expiry
            symbol_options = [
                inst for inst in self._nfo_instruments
                if inst.get('name') == symbol
                and self._match_expiry(inst.get('expiry'), expiry_date)
            ]

            if not symbol_options:
                logger.warning(f"   No options found for {symbol} expiry {expiry_str}")
                return None

            # Step 4: ATM and strike range
            all_strikes = sorted(set(inst['strike'] for inst in symbol_options))
            if not all_strikes:
                return None

            atm_strike = min(all_strikes, key=lambda s: abs(s - spot_price))
            atm_idx = all_strikes.index(atm_strike)
            n = getattr(self.config, 'PH6_STRIKES_AROUND_ATM',
                        getattr(self.config, 'STRIKES_AROUND_ATM', 10))
            relevant_strikes = set(all_strikes[max(0, atm_idx - n):atm_idx + n + 1])

            # Step 5: Batch quote
            quote_symbols = []
            inst_by_key = {}
            for inst in symbol_options:
                if inst['strike'] in relevant_strikes:
                    ts = inst['tradingsymbol']
                    quote_symbols.append(f"NFO:{ts}")
                    inst_by_key[ts] = inst

            if not quote_symbols:
                return None

            quotes = self.kite.quote(quote_symbols)

            # Step 6: Build strike data
            strike_data = {}
            for ts, inst in inst_by_key.items():
                key = f"NFO:{ts}"
                if key not in quotes:
                    continue
                q = quotes[key]
                strike = inst['strike']
                itype = inst['instrument_type']

                if strike not in strike_data:
                    strike_data[strike] = {
                        'strike': strike,
                        'ce_ltp': 0, 'pe_ltp': 0,
                        'ce_oi': 0, 'pe_oi': 0,
                        'ce_volume': 0, 'pe_volume': 0,
                        'ce_symbol': '', 'pe_symbol': '',
                    }

                sd = strike_data[strike]
                if itype == 'CE':
                    sd['ce_ltp'] = q.get('last_price', 0)
                    sd['ce_oi'] = q.get('oi', 0)
                    sd['ce_volume'] = q.get('volume', 0)
                    sd['ce_symbol'] = ts
                elif itype == 'PE':
                    sd['pe_ltp'] = q.get('last_price', 0)
                    sd['pe_oi'] = q.get('oi', 0)
                    sd['pe_volume'] = q.get('volume', 0)
                    sd['pe_symbol'] = ts

            strikes_list = sorted(strike_data.values(), key=lambda x: x['strike'])

            # Step 6b: Filter out strikes with low OI/volume (unusable for spreads)
            min_oi = getattr(self.config, 'PH6_MIN_OI_THRESHOLD',
                             getattr(self.config, 'MIN_OI_THRESHOLD', 1000))
            min_vol = getattr(self.config, 'PH6_MIN_VOLUME_THRESHOLD',
                              getattr(self.config, 'MIN_VOLUME_THRESHOLD', 50))
            strikes_list = [
                s for s in strikes_list
                if (s['ce_oi'] >= min_oi and s['ce_volume'] >= min_vol)
                or (s['pe_oi'] >= min_oi and s['pe_volume'] >= min_vol)
            ]

            if not strikes_list:
                logger.warning(f"   No strikes with OI >= {min_oi} / Vol >= {min_vol} for {symbol}")
                return None

            # Step 7: Analytics
            total_ce_oi = sum(s['ce_oi'] for s in strikes_list)
            total_pe_oi = sum(s['pe_oi'] for s in strikes_list)
            pcr = round(total_pe_oi / total_ce_oi, 2) if total_ce_oi > 0 else 0
            max_pain = self._calculate_max_pain(strikes_list, spot_price)
            oi_buildup = self._get_oi_buildup(strikes_list)
            lot_size = self._lot_size_map.get(symbol, 1)

            chain = OptionsChainData(
                symbol=symbol,
                spot_price=spot_price,
                expiry=expiry_str,
                expiry_dt=expiry_date,
                strikes=strikes_list,
                pcr=pcr,
                max_pain=max_pain,
                total_ce_oi=total_ce_oi,
                total_pe_oi=total_pe_oi,
                atm_strike=atm_strike,
                lot_size=lot_size,
                oi_buildup=oi_buildup,
                fetched_at=datetime.now().isoformat(),
            )

            logger.info(f"   Options chain built: {len(strikes_list)} strikes, "
                       f"ATM={atm_strike}, PCR={pcr}, MaxPain={max_pain}")
            return chain

        except Exception as e:
            logger.error(f"   Failed to build chain for {symbol}: {e}")
            return None

    def _match_expiry(self, inst_expiry, target_date: date) -> bool:
        """Compare instrument expiry to target date."""
        if inst_expiry is None:
            return False
        if isinstance(inst_expiry, datetime):
            return inst_expiry.date() == target_date
        if isinstance(inst_expiry, date):
            return inst_expiry == target_date
        return False

    # ───────────────────────────────────────────────────────────────
    # OPTIONS ANALYTICS
    # ───────────────────────────────────────────────────────────────

    def _calculate_max_pain(self, strikes: List[Dict], spot: float) -> float:
        """
        Max Pain = strike where total loss for option WRITERS is minimum.

        For each candidate K:
          CE writer loss = Σ max(0, K - S) * ce_oi_at_S  for S < K
          PE writer loss = Σ max(0, S - K) * pe_oi_at_S  for S > K
        """
        if not strikes:
            return spot

        min_loss = float('inf')
        max_pain_strike = spot

        for candidate in strikes:
            k = candidate['strike']
            total_loss = 0

            for s in strikes:
                # CE writers lose when spot above strike
                if s['strike'] < k and s['ce_oi'] > 0:
                    total_loss += (k - s['strike']) * s['ce_oi']
                # PE writers lose when spot below strike
                if s['strike'] > k and s['pe_oi'] > 0:
                    total_loss += (s['strike'] - k) * s['pe_oi']

            if total_loss < min_loss:
                min_loss = total_loss
                max_pain_strike = k

        return max_pain_strike

    def _get_oi_buildup(self, strikes: List[Dict]) -> Dict:
        """Identify key OI buildup levels (support/resistance)."""
        if not strikes:
            return {
                'highest_ce_oi_strike': 0,
                'highest_pe_oi_strike': 0,
                'top_3_ce_oi': [],
                'top_3_pe_oi': [],
            }

        ce_sorted = sorted(strikes, key=lambda x: x['ce_oi'], reverse=True)
        pe_sorted = sorted(strikes, key=lambda x: x['pe_oi'], reverse=True)

        return {
            'highest_ce_oi_strike': ce_sorted[0]['strike'] if ce_sorted else 0,
            'highest_pe_oi_strike': pe_sorted[0]['strike'] if pe_sorted else 0,
            'top_3_ce_oi': [(s['strike'], s['ce_oi']) for s in ce_sorted[:3]],
            'top_3_pe_oi': [(s['strike'], s['pe_oi']) for s in pe_sorted[:3]],
        }

    # ───────────────────────────────────────────────────────────────
    # v6.1: LIVE ORDER PLACEMENT
    # ───────────────────────────────────────────────────────────────

    def _place_nfo_limit_order(
        self,
        tradingsymbol: str,
        lot_size: int,
        transaction_type: str,
        limit_price: float,
    ) -> Optional[str]:
        """
        Place a single LIMIT order on NFO exchange.

        Args:
            tradingsymbol: e.g. "RELIANCE26FEB2800CE"
            lot_size: Full lot qty (e.g. 250)
            transaction_type: "BUY" or "SELL"
            limit_price: LIMIT price after buffer applied

        Returns:
            order_id string, or None on failure
        """
        product = getattr(self.config, 'PH6_OPTIONS_PRODUCT_TYPE', 'MIS')
        max_lots = getattr(self.config, 'PH6_MAX_LOTS', 1)
        quantity = lot_size * max_lots

        if quantity <= 0 or lot_size <= 0:
            logger.error(f"   Invalid quantity/lot_size: qty={quantity}, lot={lot_size}")
            return None

        try:
            order_id = self.kite.place_order(
                variety=self.kite.VARIETY_REGULAR,
                exchange=self.kite.EXCHANGE_NFO,
                tradingsymbol=tradingsymbol,
                transaction_type=transaction_type,
                quantity=quantity,
                product=product,
                order_type=self.kite.ORDER_TYPE_LIMIT,
                price=round(limit_price, 2),
            )
            logger.info(f"   NFO {transaction_type} order placed: {tradingsymbol} "
                       f"qty={quantity} @ ₹{limit_price:.2f} → order_id={order_id}")
            return str(order_id)
        except Exception as e:
            logger.error(f"   NFO order FAILED: {tradingsymbol} {transaction_type} — {e}")
            return None

    def _poll_order_fill(self, order_id: str) -> Tuple[float, int, str]:
        """
        Poll kite.order_history() until order fills, rejects, or times out.

        Returns:
            (fill_price, filled_qty, status)
            status: "COMPLETE" / "REJECTED" / "CANCELLED" / "TIMEOUT"
        """
        timeout = getattr(self.config, 'PH6_ORDER_TIMEOUT_SECONDS', 45)
        poll_interval = getattr(self.config, 'PH6_ORDER_POLL_INTERVAL', 2)
        start = time.time()

        while time.time() - start < timeout:
            try:
                history = self.kite.order_history(order_id)
                if not history:
                    time.sleep(poll_interval)
                    continue

                latest = history[-1]
                status = latest.get('status', '').upper()

                if status == 'COMPLETE':
                    fill_price = float(latest.get('average_price', 0))
                    filled_qty = int(latest.get('filled_quantity', 0))
                    logger.info(f"   Order {order_id} FILLED @ ₹{fill_price:.2f}, qty={filled_qty}")
                    return fill_price, filled_qty, 'COMPLETE'

                if status in ('REJECTED', 'CANCELLED'):
                    reason = latest.get('status_message', status)
                    logger.warning(f"   Order {order_id} {status}: {reason}")
                    return 0.0, 0, status

            except Exception as e:
                logger.warning(f"   Poll error for {order_id}: {e}")

            time.sleep(poll_interval)

        # Timeout — cancel the order
        logger.warning(f"   Order {order_id} TIMEOUT after {timeout}s — cancelling")
        try:
            self.kite.cancel_order(variety=self.kite.VARIETY_REGULAR, order_id=order_id)
        except Exception as e:
            logger.error(f"   Cancel failed for {order_id}: {e}")

        return 0.0, 0, 'TIMEOUT'

    def _place_spread_entry(self, advisory: SpreadAdvisory):
        """
        Place LIVE spread entry: BUY leg first → if filled → SELL leg.

        Safety sequence (aviation-grade):
        - BUY lower CE first (defined risk — max loss = premium paid)
        - Only if BUY fills, then SELL higher CE
        - Never SELL first (naked short CE = unlimited risk)

        Updates advisory with actual fill prices and order_mode.
        """
        buy_leg = advisory.legs[0]   # BUY lower CE
        sell_leg = advisory.legs[1]  # SELL higher CE
        buffer_pct = getattr(self.config, 'PH6_ENTRY_LIMIT_BUFFER_PCT', 0.5)

        # 1. Fetch LIVE premiums (fresh, not ChatGPT estimates)
        try:
            live_quotes = self.kite.quote([
                f"NFO:{buy_leg.tradingsymbol}",
                f"NFO:{sell_leg.tradingsymbol}",
            ])
            buy_ltp = live_quotes.get(f"NFO:{buy_leg.tradingsymbol}", {}).get('last_price', 0)
            sell_ltp = live_quotes.get(f"NFO:{sell_leg.tradingsymbol}", {}).get('last_price', 0)

            if buy_ltp <= 0 or sell_ltp <= 0:
                logger.warning(f"   Live LTP missing: buy={buy_ltp}, sell={sell_ltp} — staying PAPER")
                return
        except Exception as e:
            logger.error(f"   Live quote fetch failed: {e} — staying PAPER")
            return

        # 2. BUY leg: LIMIT @ LTP + buffer (willing to pay slightly more for fill)
        buy_limit = round(buy_ltp * (1 + buffer_pct / 100), 2)
        logger.info(f"   BUY LEG: {buy_leg.tradingsymbol} | LTP=₹{buy_ltp:.2f} | LIMIT=₹{buy_limit:.2f}")

        buy_order_id = self._place_nfo_limit_order(
            tradingsymbol=buy_leg.tradingsymbol,
            lot_size=advisory.lot_size,
            transaction_type='BUY',
            limit_price=buy_limit,
        )

        if not buy_order_id:
            logger.warning(f"   BUY leg order placement failed — staying PAPER")
            return

        buy_fill, buy_qty, buy_status = self._poll_order_fill(buy_order_id)

        if buy_status != 'COMPLETE':
            logger.warning(f"   BUY leg not filled ({buy_status}) — advisory stays PAPER")
            return

        # Update BUY leg with actual fill
        buy_leg.order_id = buy_order_id
        buy_leg.fill_price = buy_fill
        buy_leg.fill_quantity = buy_qty
        buy_leg.order_status = 'COMPLETE'
        advisory.buy_order_id = buy_order_id

        # 3. SELL leg: LIMIT @ LTP - buffer (willing to receive slightly less for fill)
        #    Re-fetch sell LTP (may have moved during buy fill wait)
        try:
            fresh_sell = self.kite.quote([f"NFO:{sell_leg.tradingsymbol}"])
            sell_ltp = fresh_sell.get(f"NFO:{sell_leg.tradingsymbol}", {}).get('last_price', sell_ltp)
        except Exception:
            pass  # Use previous LTP

        sell_limit = round(sell_ltp * (1 - buffer_pct / 100), 2)
        sell_limit = max(sell_limit, 0.05)  # Floor at tick size
        logger.info(f"   SELL LEG: {sell_leg.tradingsymbol} | LTP=₹{sell_ltp:.2f} | LIMIT=₹{sell_limit:.2f}")

        sell_order_id = self._place_nfo_limit_order(
            tradingsymbol=sell_leg.tradingsymbol,
            lot_size=advisory.lot_size,
            transaction_type='SELL',
            limit_price=sell_limit,
        )

        if not sell_order_id:
            # BUY filled but SELL failed to place — PARTIAL (long naked CE, defined risk)
            advisory.order_mode = "PARTIAL"
            logger.warning(f"   ⚠️ SELL leg placement failed — PARTIAL mode (holding naked long CE)")
            self._notify_partial_fill(advisory, "SELL leg order placement failed")
            return

        sell_fill, sell_qty, sell_status = self._poll_order_fill(sell_order_id)

        if sell_status != 'COMPLETE':
            # BUY filled, SELL didn't — PARTIAL
            advisory.order_mode = "PARTIAL"
            sell_leg.order_id = sell_order_id
            sell_leg.order_status = sell_status
            advisory.sell_order_id = sell_order_id
            logger.warning(f"   ⚠️ SELL leg {sell_status} — PARTIAL mode (holding naked long CE)")
            self._notify_partial_fill(advisory, f"SELL leg {sell_status}")
            return

        # Both legs filled — LIVE!
        sell_leg.order_id = sell_order_id
        sell_leg.fill_price = sell_fill
        sell_leg.fill_quantity = sell_qty
        sell_leg.order_status = 'COMPLETE'
        advisory.sell_order_id = sell_order_id
        advisory.order_mode = "LIVE"

        # 4. Recalculate from ACTUAL fill prices (not ChatGPT estimates)
        actual_net_debit = buy_fill - sell_fill
        advisory.entry_net_premium = actual_net_debit
        advisory.current_net_premium = actual_net_debit
        advisory.net_debit_per_share = actual_net_debit
        advisory.max_loss = actual_net_debit * advisory.lot_size
        strike_width = sell_leg.strike - buy_leg.strike
        advisory.max_profit = (strike_width - actual_net_debit) * advisory.lot_size
        advisory.breakeven = buy_leg.strike + actual_net_debit
        if advisory.max_loss > 0:
            advisory.risk_reward_ratio = advisory.max_profit / advisory.max_loss

        # Update entry premiums to actuals
        buy_leg.entry_premium = buy_fill
        sell_leg.entry_premium = sell_fill

        logger.info(f"   ✅ SPREAD LIVE: BUY @ ₹{buy_fill:.2f} / SELL @ ₹{sell_fill:.2f} "
                   f"| Net Debit: ₹{actual_net_debit:.2f} | Max P: ₹{advisory.max_profit:,.0f}")

    def _close_spread_live(self, advisory: SpreadAdvisory, buffer_pct: float = None):
        """
        Close a LIVE spread by reversing both legs.

        BUY leg (we hold long CE) → SELL to close
        SELL leg (we hold short CE) → BUY to close

        Retries failed legs up to PH6_ORDER_MAX_RETRIES times.
        Sends CRITICAL ALERT if still unfilled after retries.
        """
        if buffer_pct is None:
            buffer_pct = getattr(self.config, 'PH6_EXIT_LIMIT_BUFFER_PCT', 0.3)
        max_retries = getattr(self.config, 'PH6_ORDER_MAX_RETRIES', 3)

        buy_leg = advisory.legs[0]   # We hold long CE → SELL to close
        sell_leg = advisory.legs[1]  # We hold short CE → BUY to close

        close_results = {}  # leg_name -> (fill_price, filled_qty, status)

        # Process both legs
        for leg, reverse_txn, leg_name in [
            (buy_leg, 'SELL', 'BUY_LEG_CLOSE'),
            (sell_leg, 'BUY', 'SELL_LEG_CLOSE'),
        ]:
            if leg.order_status != 'COMPLETE':
                logger.info(f"   Skipping {leg_name} — original order was {leg.order_status}")
                close_results[leg_name] = (0.0, 0, 'SKIPPED')
                continue

            # Fetch live LTP for limit price
            try:
                quote = self.kite.quote([f"NFO:{leg.tradingsymbol}"])
                ltp = quote.get(f"NFO:{leg.tradingsymbol}", {}).get('last_price', 0)
            except Exception:
                ltp = leg.current_premium  # Fallback to last known

            if ltp <= 0:
                ltp = leg.current_premium

            # Calculate limit price based on direction
            if reverse_txn == 'SELL':
                limit_price = round(ltp * (1 - buffer_pct / 100), 2)
                limit_price = max(limit_price, 0.05)
            else:  # BUY to close short
                limit_price = round(ltp * (1 + buffer_pct / 100), 2)

            # Retry loop
            filled = False
            for attempt in range(1, max_retries + 1):
                logger.info(f"   {leg_name} attempt {attempt}/{max_retries}: "
                           f"{reverse_txn} {leg.tradingsymbol} LIMIT @ ₹{limit_price:.2f}")

                order_id = self._place_nfo_limit_order(
                    tradingsymbol=leg.tradingsymbol,
                    lot_size=advisory.lot_size,
                    transaction_type=reverse_txn,
                    limit_price=limit_price,
                )

                if not order_id:
                    logger.warning(f"   {leg_name} placement failed, attempt {attempt}")
                    continue

                fill_price, fill_qty, status = self._poll_order_fill(order_id)

                if status == 'COMPLETE':
                    close_results[leg_name] = (fill_price, fill_qty, status)
                    filled = True
                    break
                else:
                    # Widen buffer for next retry
                    buffer_pct = min(buffer_pct * 1.5, 3.0)
                    if reverse_txn == 'SELL':
                        limit_price = round(ltp * (1 - buffer_pct / 100), 2)
                        limit_price = max(limit_price, 0.05)
                    else:
                        limit_price = round(ltp * (1 + buffer_pct / 100), 2)

            if not filled:
                close_results[leg_name] = (0.0, 0, 'FAILED')
                logger.error(f"   🚨 {leg_name} FAILED after {max_retries} retries!")
                # CRITICAL ALERT
                if self.telegram:
                    try:
                        self.telegram.send_message(
                            f"🚨 CRITICAL: OPTIONS LEG UNFILLED\n\n"
                            f"Advisory #{advisory.id} {advisory.symbol}\n"
                            f"Leg: {leg_name}\n"
                            f"Symbol: {leg.tradingsymbol}\n"
                            f"Action needed: {reverse_txn} {advisory.lot_size} qty\n"
                            f"Last LTP: ₹{ltp:.2f}\n\n"
                            f"⚠️ MANUAL INTERVENTION REQUIRED"
                        )
                    except Exception:
                        pass

        # Calculate actual P&L from close fills
        buy_close = close_results.get('BUY_LEG_CLOSE', (0.0, 0, 'SKIPPED'))
        sell_close = close_results.get('SELL_LEG_CLOSE', (0.0, 0, 'SKIPPED'))

        if buy_close[2] == 'COMPLETE' and sell_close[2] == 'COMPLETE':
            # Both legs closed: P&L = (sell_close_fill - buy_entry_fill) + (sell_entry_fill - buy_close_fill)
            # Simplified: spread_exit_value - spread_entry_value
            exit_spread = buy_close[0] - sell_close[0]  # what we got back (sold buy leg, bought back sell leg)
            entry_spread = buy_leg.fill_price - sell_leg.fill_price  # what we paid
            advisory.paper_pnl = (exit_spread - entry_spread) * advisory.lot_size
        elif buy_close[2] == 'COMPLETE':
            # Only buy leg closed (sold our long CE)
            advisory.paper_pnl = (buy_close[0] - buy_leg.fill_price) * advisory.lot_size
        elif sell_close[2] == 'COMPLETE':
            # Only sell leg closed (bought back short CE)
            advisory.paper_pnl = (sell_leg.fill_price - sell_close[0]) * advisory.lot_size

    def _notify_partial_fill(self, advisory: SpreadAdvisory, reason: str):
        """Send Telegram alert for partial fill (BUY filled, SELL failed)."""
        if not self.telegram:
            return
        try:
            buy_leg = advisory.legs[0]
            self.telegram.send_message(
                f"⚠️ OPTIONS PARTIAL FILL\n\n"
                f"Advisory #{advisory.id} {advisory.symbol}\n"
                f"BUY {buy_leg.strike:.0f} CE filled @ ₹{buy_leg.fill_price:.2f}\n"
                f"SELL leg: {reason}\n\n"
                f"Status: Holding naked long CE (defined risk)\n"
                f"Max loss = premium paid = ₹{buy_leg.fill_price * advisory.lot_size:,.0f}"
            )
        except Exception as e:
            logger.warning(f"   Partial fill notification failed: {e}")

    # ───────────────────────────────────────────────────────────────
    # MAIN ENTRY POINT (called from Phase 3)
    # ───────────────────────────────────────────────────────────────

    def generate_advisory(
        self,
        symbol: str,
        equity_order_id: str,
        equity_entry_price: float,
        phase2_score: float = 0,
    ) -> Optional[SpreadAdvisory]:
        """
        Generate a Bull Call Spread advisory for a stock that just got
        an equity BUY order in Phase 3.

        Args:
            symbol: Stock symbol (e.g. 'RELIANCE')
            equity_order_id: Phase 3 order ID
            equity_entry_price: Fill price of equity BUY
            phase2_score: Phase 2 entry score (0-100)

        Returns:
            SpreadAdvisory if recommendation generated, None otherwise
        """
        logger.info(f"")
        logger.info(f"{'='*60}")
        logger.info(f"📊 PHASE 6: OPTIONS ADVISORY for {symbol}")
        logger.info(f"{'='*60}")
        logger.info(f"   Equity BUY @ ₹{equity_entry_price:.2f} | Order: {equity_order_id}")

        # v1.6.0: PH9 HOLD directive — brain has blocked options advisories today
        if getattr(self, '_ph9_hold', False):
            logger.info(f"   ⛔ PH9 directive: PH6 HOLD — options advisory blocked for {symbol}")
            return None

        # Also check daily_briefing ph6_directive (belt-and-suspenders)
        _briefing = getattr(self, 'daily_briefing', {})
        if _briefing.get('ph6_directive', 'ACTIVE').upper() == 'HOLD':
            logger.info(f"   ⛔ PH9 briefing: PH6 HOLD — options advisory blocked for {symbol}")
            return None

        # 1. Refresh NFO cache if stale
        if self._is_nfo_cache_stale():
            logger.info("   Loading NFO instruments...")
            self._load_nfo_instruments()

        # 2. Check if stock has F&O
        if symbol not in self._fno_stock_set:
            logger.info(f"   {symbol} is not in F&O segment, skipping options advisory")
            return None

        # 2b. Duplicate guard — skip if we already have an open advisory for this symbol
        existing_open = [a for a in self.advisories if a.symbol == symbol and a.is_open]
        if existing_open:
            logger.info(f"   {symbol} already has open advisory #{existing_open[0].id}, skipping duplicate")
            return None

        # 2c. DTE Safety Gate — check days to expiry before building chain
        dte_gate_enabled = getattr(self.config, 'PH6_DTE_GATE_ENABLED', True)
        override_expiry = None
        dte_target_pct = None  # will override target if DTE is short
        nearest_expiry = None  # avoid UnboundLocalError if gate disabled

        if dte_gate_enabled:
            nearest_expiry = self._get_nearest_expiry(symbol)
            if nearest_expiry:
                dte_check = self._check_dte_eligibility(nearest_expiry)
                logger.info(f"   DTE Gate: {dte_check['action']} (DTE={dte_check['dte']}) — {dte_check['reason']}")

                if not dte_check['eligible']:
                    # BLOCK — no safe expiry available
                    logger.warning(f"   ⛔ DTE BLOCKED: {symbol} — {dte_check['reason']}")
                    self._send_dte_telegram(symbol, dte_check)
                    return None

                if dte_check['rolled']:
                    # ROLL — use next month's expiry
                    override_expiry = dte_check['expiry_date']
                    logger.info(f"   🔄 DTE ROLL: {symbol} → {override_expiry} (DTE={dte_check['dte']})")
                    self._send_dte_telegram(symbol, dte_check)

                if dte_check['action'] == 'ALLOW_TIGHT':
                    # Tightened target for short-DTE entries
                    dte_target_pct = dte_check['target_pct']
                    logger.info(f"   ⚠️ DTE SHORT: {symbol} target tightened to {dte_target_pct}% of max profit")
                    self._send_dte_telegram(symbol, dte_check)
            else:
                logger.warning(f"   DTE Gate: No expiry found for {symbol}, proceeding without DTE check")

        # 3. Build options chain
        chain = self._build_options_chain(symbol, override_expiry=override_expiry)
        if not chain or not chain.strikes:
            logger.warning(f"   Could not build options chain for {symbol}")
            return None

        # 4. Ask ChatGPT for recommendation
        if not self.chatgpt:
            logger.warning("   ChatGPT advisor not available, skipping options advisory")
            return None

        try:
            recommendation = self.chatgpt.review_options_strategy(
                symbol=symbol,
                spot_price=chain.spot_price,
                chain_data=chain.to_dict(),
                equity_entry_price=equity_entry_price,
                phase2_score=phase2_score,
            )
        except Exception as e:
            logger.error(f"   ChatGPT options strategy failed: {e}")
            return None

        if not recommendation:
            logger.info(f"   ChatGPT returned no recommendation for {symbol}")
            return None

        # 5. Check confidence threshold (with pattern + ORB bonuses)
        confidence = recommendation.get('confidence', 0)
        pattern_bonus = self.get_pattern_bonus(symbol)
        orb_bonus = self.get_orb_bonus(symbol)
        effective_confidence = confidence + pattern_bonus + orb_bonus
        if pattern_bonus > 0 or orb_bonus > 0:
            logger.info(
                f"   Confidence adjusted: {confidence} + {pattern_bonus} (pattern) "
                f"+ {orb_bonus} (ORB) = {effective_confidence}"
            )

        min_confidence = getattr(self.config, 'PH6_CHATGPT_MIN_CONFIDENCE',
                                 getattr(self.config, 'CHATGPT_MIN_CONFIDENCE', 60))
        if effective_confidence < min_confidence:
            logger.info(f"   Confidence {effective_confidence} < {min_confidence} threshold, skipping")
            return None

        # 6. Create SpreadAdvisory
        lot_size = chain.lot_size
        buy_premium = float(recommendation.get('buy_premium', 0))
        sell_premium = float(recommendation.get('sell_premium', 0))
        net_debit = buy_premium - sell_premium

        buy_leg = OptionLeg(
            strike=float(recommendation['buy_strike']),
            option_type='CE',
            action='BUY',
            lot_size=lot_size,
            entry_premium=buy_premium,
            current_premium=buy_premium,
            tradingsymbol=recommendation.get('buy_symbol', ''),
        )

        sell_leg = OptionLeg(
            strike=float(recommendation['sell_strike']),
            option_type='CE',
            action='SELL',
            lot_size=lot_size,
            entry_premium=sell_premium,
            current_premium=sell_premium,
            tradingsymbol=recommendation.get('sell_symbol', ''),
        )

        advisory = SpreadAdvisory(
            id=self._next_id,
            timestamp=datetime.now().isoformat(),
            symbol=symbol,
            spot_price=chain.spot_price,
            equity_order_id=equity_order_id,
            equity_entry_price=equity_entry_price,
            spread_type='BULL_CALL_SPREAD',
            legs=[buy_leg, sell_leg],
            max_profit=float(recommendation.get('max_profit_per_lot', 0)),
            max_loss=float(recommendation.get('max_loss_per_lot', 0)),
            breakeven=float(recommendation.get('breakeven', 0)),
            net_debit_per_share=net_debit,
            confidence=confidence,
            reasoning=recommendation.get('reasoning', ''),
            risk_reward_ratio=float(recommendation.get('risk_reward_ratio', 0)),
            expiry=chain.expiry,
            lot_size=lot_size,
            entry_net_premium=net_debit,
            current_net_premium=net_debit,
            pcr=chain.pcr,
            max_pain=chain.max_pain,
            web_news=recommendation.get('web_news', ''),
        )

        # v6.3: Stamp DTE info on advisory for urgency monitoring
        if dte_gate_enabled and nearest_expiry:
            # Compute DTE from the actual expiry used (possibly rolled)
            actual_expiry = override_expiry or nearest_expiry
            advisory.dte_at_entry = (actual_expiry - date.today()).days
        if dte_target_pct is not None:
            advisory.dte_target_pct = dte_target_pct

        self._next_id += 1

        # 7. Log to DB
        if self._db:
            try:
                db_id = self._db.log_options_spread({
                    'symbol': symbol,
                    'equity_order_id': equity_order_id,
                    'equity_entry_price': equity_entry_price,
                    'spread_type': 'BULL_CALL_SPREAD',
                    'spot_price': chain.spot_price,
                    'expiry': chain.expiry,
                    'lot_size': lot_size,
                    'legs': [buy_leg.to_dict(), sell_leg.to_dict()],
                    'max_profit': advisory.max_profit,
                    'max_loss': advisory.max_loss,
                    'breakeven': [advisory.breakeven],
                    'entry_net_premium': net_debit,
                    'confidence': confidence,
                    'reasoning': advisory.reasoning,
                    'web_news': advisory.web_news,
                    'chatgpt_raw': recommendation,
                    'pcr': chain.pcr,
                    'max_pain': chain.max_pain,
                    'total_ce_oi': chain.total_ce_oi,
                    'total_pe_oi': chain.total_pe_oi,
                })
                advisory.db_id = db_id
                logger.info(f"   DB logged: options_spread_trades id={db_id}")
            except Exception as e:
                logger.error(f"   DB logging failed: {e}")

        # 7b. v6.1: Place LIVE orders if enabled (after DB log, before tracking)
        if self._live_enabled:
            try:
                self._place_spread_entry(advisory)
                # Update DB with live order details
                if self._db and advisory.db_id:
                    self._db.update_options_spread(advisory.db_id, {
                        'order_mode': advisory.order_mode,
                        'buy_order_id': advisory.buy_order_id,
                        'sell_order_id': advisory.sell_order_id,
                        'buy_fill_price': advisory.legs[0].fill_price,
                        'sell_fill_price': advisory.legs[1].fill_price,
                        'actual_net_debit': advisory.entry_net_premium if advisory.order_mode == 'LIVE' else 0,
                        # Update recalculated risk profile from actual fills
                        'entry_net_premium': advisory.entry_net_premium,
                        'legs_json': json.dumps([l.to_dict() for l in advisory.legs]),
                    })
            except Exception as e:
                logger.error(f"   Live order placement error: {e} — advisory stays PAPER")

        # 8. Add to tracking list
        self.advisories.append(advisory)
        self.daily_stats['advisories_generated'] += 1

        # 9. Telegram notification
        self._notify_new_advisory(advisory)

        mode_tag = f" [{advisory.order_mode}]" if advisory.order_mode != "PAPER" else ""
        logger.info(f"   ✅ Advisory #{advisory.id} created: BULL CALL SPREAD on {symbol}{mode_tag}")
        return advisory

    # ───────────────────────────────────────────────────────────────
    # v6.2: OPTIONS TCAS — GRADUATED PROFIT LOCK
    # ───────────────────────────────────────────────────────────────

    def _update_profit_lock(self, advisory: SpreadAdvisory) -> bool:
        """
        Update peak P&L tracking and ratchet profit lock floor.

        Walks PH6_TCAS_TIERS from highest to lowest.
        Floor only moves UP, never down.

        Returns True if advisory should be closed (floor breached).
        """
        tcas_enabled = getattr(self.config, 'PH6_TCAS_ENABLED', True)
        if not tcas_enabled:
            return False

        tiers = getattr(self.config, 'PH6_TCAS_TIERS', [
            (10, 5), (15, 10), (20, 15), (30, 25), (50, 42), (65, 58),
        ])

        # 1. Update peak P&L %
        advisory.peak_pnl_pct = max(advisory.peak_pnl_pct, advisory.paper_pnl_pct)

        # 2. Walk tiers from highest to lowest — find the highest qualifying lock
        new_lock = advisory.profit_lock_pct
        for trigger_pct, lock_floor_pct in sorted(tiers, key=lambda t: t[0], reverse=True):
            if advisory.peak_pnl_pct >= trigger_pct:
                new_lock = max(new_lock, lock_floor_pct)
                break  # Highest qualifying tier wins

        # 3. Ratchet floor UP only
        if new_lock > advisory.profit_lock_pct:
            old_lock = advisory.profit_lock_pct
            advisory.profit_lock_pct = new_lock
            advisory.tcas_active = True
            logger.info(f"   🔒 TCAS #{advisory.id} {advisory.symbol}: "
                       f"Floor raised {old_lock:.0f}% → {new_lock:.0f}% "
                       f"(peak {advisory.peak_pnl_pct:.1f}%)")

            # Update DB with new lock
            if self._db and advisory.db_id:
                try:
                    self._db.update_options_spread(advisory.db_id, {
                        'peak_pnl_pct': advisory.peak_pnl_pct,
                        'profit_lock_pct': advisory.profit_lock_pct,
                        'tcas_active': 1 if advisory.tcas_active else 0,
                    })
                except Exception:
                    pass

        # 4. Check floor breach
        if advisory.tcas_active and advisory.profit_lock_pct > 0:
            if advisory.paper_pnl_pct < advisory.profit_lock_pct:
                logger.info(f"   ⚠️ TCAS BREACH #{advisory.id} {advisory.symbol}: "
                           f"P&L {advisory.paper_pnl_pct:+.1f}% < floor {advisory.profit_lock_pct:.0f}%")
                return True  # Signal close

        return False

    # ───────────────────────────────────────────────────────────────
    # PREMIUM MONITORING
    # ───────────────────────────────────────────────────────────────

    def has_tcas_active(self) -> bool:
        """Check if any open advisory has TCAS active (for adaptive polling)."""
        return any(a.tcas_active and a.is_open for a in self.advisories)

    def check_open_advisories(self):
        """
        Re-check premiums on all open advisories.
        Calculate paper P&L, run TCAS profit lock, DTE urgency, then target/stop/expiry.
        Called periodically by orchestrator.

        v6.3 execution order:
          1. Fetch quotes → update premiums
          2. Calculate P&L
          3. Update TCAS peak & lock floor (ratchet up)
          4. Check TCAS floor breach → PROFIT_LOCK_EXIT
          4b. DTE urgency:
              - DTE 0: Force close at PH6_EXPIRY_EXIT_TIME
              - DTE 1: Close if P&L ≥ 0 (breakeven+)
              - DTE 2-3: Tighten target to PH6_DTE_SHORT_TARGET_PCT (60%)
          5. Check target (80% or DTE-adjusted %) → TARGET_HIT
          6. Check stop (100% max loss) → STOP_HIT
          7. Check expiry → EXPIRED
        """
        open_advisories = [a for a in self.advisories if a.is_open]
        if not open_advisories:
            return

        logger.info(f"📊 Phase 6: Checking {len(open_advisories)} open advisories...")

        for advisory in open_advisories:
            try:
                # 1. Fetch current premiums
                quote_symbols = []
                for leg in advisory.legs:
                    if leg.tradingsymbol:
                        quote_symbols.append(f"NFO:{leg.tradingsymbol}")

                if not quote_symbols:
                    continue

                quotes = self.kite.quote(quote_symbols)

                # Update leg premiums
                for leg in advisory.legs:
                    key = f"NFO:{leg.tradingsymbol}"
                    if key in quotes:
                        leg.current_premium = quotes[key].get('last_price', leg.entry_premium)

                # 2. Calculate current net premium (from trader perspective)
                # BUY leg: we paid premium → current value = current_premium
                # SELL leg: we received premium → current cost to close = current_premium
                # Net spread value = buy_leg.current - sell_leg.current
                # P&L = (current_spread_value - entry_spread_value) × lot_size
                current_spread_value = 0
                entry_spread_value = 0
                for leg in advisory.legs:
                    if leg.action == 'BUY':
                        current_spread_value += leg.current_premium
                        entry_spread_value += leg.entry_premium
                    else:  # SELL
                        current_spread_value -= leg.current_premium
                        entry_spread_value -= leg.entry_premium

                advisory.current_net_premium = current_spread_value
                advisory.paper_pnl = (current_spread_value - entry_spread_value) * advisory.lot_size
                if abs(entry_spread_value * advisory.lot_size) > 0:
                    advisory.paper_pnl_pct = (advisory.paper_pnl / abs(entry_spread_value * advisory.lot_size)) * 100

                # 3-4. TCAS: Update profit lock + check floor breach
                if self._update_profit_lock(advisory):
                    self._close_advisory(advisory, AdvisoryStatus.PROFIT_LOCK_EXIT,
                                        f"TCAS floor {advisory.profit_lock_pct:.0f}% breached "
                                        f"(P&L {advisory.paper_pnl_pct:+.1f}%, "
                                        f"peak {advisory.peak_pnl_pct:.1f}%)")
                    continue

                # 4b. DTE Urgency — escalating exit pressure as expiry approaches
                dte_gate_on = getattr(self.config, 'PH6_DTE_GATE_ENABLED', True)
                current_dte = None
                if dte_gate_on and advisory.expiry:
                    try:
                        expiry_dt = datetime.strptime(advisory.expiry, '%Y-%m-%d').date()
                        current_dte = (expiry_dt - date.today()).days
                    except (ValueError, TypeError):
                        current_dte = None

                if current_dte is not None and current_dte <= 0:
                    # DTE 0 or past expiry: FORCE CLOSE regardless of P&L
                    # Theta is ~₹8+/day, physical delivery risk on expiry day
                    expiry_exit_time = getattr(self.config, 'PH6_EXPIRY_EXIT_TIME', '14:30')
                    now_str = datetime.now().strftime('%H:%M')
                    if now_str >= expiry_exit_time or current_dte < 0:
                        logger.warning(
                            f"   ⏰ DTE URGENCY: #{advisory.id} {advisory.symbol} "
                            f"DTE={current_dte} — FORCE CLOSE "
                            f"(P&L ₹{advisory.paper_pnl:+,.2f})"
                        )
                        self._close_advisory(
                            advisory, AdvisoryStatus.EXPIRED,
                            f"DTE urgency: expiry day force close at {now_str} "
                            f"(P&L {advisory.paper_pnl_pct:+.1f}%)"
                        )
                        continue

                elif current_dte is not None and current_dte == 1:
                    # DTE 1: Close ONLY if at breakeven or above
                    # Theta ~₹5-8/day, overnight decay will eat profits
                    if advisory.paper_pnl >= 0:
                        logger.warning(
                            f"   ⏰ DTE URGENCY: #{advisory.id} {advisory.symbol} "
                            f"DTE=1 — Closing at breakeven+ "
                            f"(P&L ₹{advisory.paper_pnl:+,.2f})"
                        )
                        self._close_advisory(
                            advisory, AdvisoryStatus.TARGET_HIT,
                            f"DTE urgency: DTE=1 close at breakeven+ "
                            f"(P&L {advisory.paper_pnl_pct:+.1f}%)"
                        )
                        continue
                    else:
                        logger.info(
                            f"   ⚠️ DTE WARNING: #{advisory.id} {advisory.symbol} "
                            f"DTE=1, P&L ₹{advisory.paper_pnl:+,.2f} — "
                            f"underwater, holding for recovery"
                        )

                # 5. Check target (80% of max profit, or DTE-adjusted)
                target_pct = getattr(self.config, 'PH6_TARGET_PCT_OF_MAX',
                                     getattr(self.config, 'TARGET_PCT_OF_MAX', 80))
                stop_pct = getattr(self.config, 'PH6_STOP_PCT_OF_MAX_LOSS',
                                   getattr(self.config, 'STOP_PCT_OF_MAX_LOSS', 100))

                # v6.3: DTE urgency overrides target %
                # Priority: advisory-level override > DTE-based override > config default
                if advisory.dte_target_pct is not None:
                    target_pct = advisory.dte_target_pct
                elif current_dte is not None and current_dte <= 3:
                    # DTE 2-3: tighten to short-DTE target even if entered at normal DTE
                    target_pct = getattr(self.config, 'PH6_DTE_SHORT_TARGET_PCT', 60)

                if advisory.max_profit > 0 and advisory.paper_pnl >= advisory.max_profit * (target_pct / 100):
                    self._close_advisory(advisory, AdvisoryStatus.TARGET_HIT,
                                        f"{target_pct}% of max profit reached"
                                        f"{' (DTE-tightened)' if target_pct < 80 else ''}")
                # 6. Check stop (100% max loss)
                elif advisory.max_loss > 0 and advisory.paper_pnl <= -advisory.max_loss * (stop_pct / 100):
                    self._close_advisory(advisory, AdvisoryStatus.STOP_HIT,
                                        f"Max loss reached")
                # 7. Check expiry
                elif advisory.expiry and date.today() >= datetime.strptime(advisory.expiry, '%Y-%m-%d').date():
                    self._close_advisory(advisory, AdvisoryStatus.EXPIRED,
                                        "Option expiry reached")
                else:
                    tcas_info = ""
                    if advisory.tcas_active:
                        tcas_info = f" | 🔒 floor={advisory.profit_lock_pct:.0f}% peak={advisory.peak_pnl_pct:.1f}%"
                    dte_info = ""
                    if current_dte is not None and current_dte <= 7:
                        dte_info = f" | ⏰ DTE={current_dte}"
                        if target_pct < 80:
                            dte_info += f" (target→{target_pct}%)"
                    logger.info(f"   #{advisory.id} {advisory.symbol}: "
                               f"P&L {'+'if advisory.paper_pnl >= 0 else ''}₹{advisory.paper_pnl:,.2f} "
                               f"({advisory.paper_pnl_pct:+.1f}%){tcas_info}{dte_info}")

            except Exception as e:
                logger.error(f"   Error checking advisory #{advisory.id}: {e}")

    def _close_advisory(self, advisory: SpreadAdvisory, status: AdvisoryStatus,
                        reason: str, buffer_pct: float = None):
        """Close an advisory and update stats."""
        # v6.1: Close live spread positions before marking closed
        if advisory.is_live and self._live_enabled:
            try:
                self._close_spread_live(advisory, buffer_pct=buffer_pct)
            except Exception as e:
                logger.error(f"   Live close failed for #{advisory.id}: {e}")

        advisory.status = status
        advisory.exit_time = datetime.now().isoformat()
        advisory.exit_reason = reason

        # Update daily stats
        if advisory.paper_pnl >= 0:
            self.daily_stats['profitable'] += 1
        else:
            self.daily_stats['unprofitable'] += 1
        self.daily_stats['total_paper_pnl'] += advisory.paper_pnl
        self.daily_stats['best_trade'] = max(self.daily_stats['best_trade'], advisory.paper_pnl)
        self.daily_stats['worst_trade'] = min(self.daily_stats['worst_trade'], advisory.paper_pnl)

        # Update DB
        if self._db and advisory.db_id:
            try:
                self._db.update_options_spread(advisory.db_id, {
                    'status': status.value,
                    'current_net_premium': advisory.current_net_premium,
                    'paper_pnl': advisory.paper_pnl,
                    'paper_pnl_pct': advisory.paper_pnl_pct,
                    'exit_time': advisory.exit_time,
                    'exit_reason': reason,
                })
            except Exception as e:
                logger.error(f"   DB update failed for advisory #{advisory.id}: {e}")

        # Telegram
        self._notify_advisory_closed(advisory)

        emoji = "✅" if advisory.paper_pnl >= 0 else "❌"
        logger.info(f"   {emoji} Advisory #{advisory.id} CLOSED: {status.value} | "
                   f"P&L: {'+'if advisory.paper_pnl >= 0 else ''}₹{advisory.paper_pnl:,.2f}")

    # ───────────────────────────────────────────────────────────────
    # EOD & SUMMARY
    # ───────────────────────────────────────────────────────────────

    def force_close_all_eod(self):
        """Close all open advisories at end of day."""
        open_advisories = [a for a in self.advisories if a.is_open]
        if open_advisories:
            logger.info(f"📊 Phase 6 EOD: Closing {len(open_advisories)} open advisories")
            # Fetch final premiums before closing
            self.check_open_advisories()
            # v6.1: Wider LIMIT buffer on EOD for urgency
            eod_buffer = getattr(self.config, 'PH6_EOD_LIMIT_BUFFER_PCT', 1.0)
            # Close any still open
            for advisory in self.advisories:
                if advisory.is_open:
                    self._close_advisory(advisory, AdvisoryStatus.EOD_CLOSE,
                                        "End of day", buffer_pct=eod_buffer)

    def generate_daily_summary(self) -> str:
        """Generate EOD summary for Telegram."""
        today_str = date.today().isoformat()
        today_advisories = [a for a in self.advisories
                           if a.timestamp.startswith(today_str)]

        if not today_advisories:
            return ""

        closed = [a for a in today_advisories if not a.is_open]
        wins = sum(1 for a in closed if a.paper_pnl >= 0)
        losses = sum(1 for a in closed if a.paper_pnl < 0)
        total_pnl = sum(a.paper_pnl for a in closed)
        pnl_sign = "+" if total_pnl >= 0 else ""

        summary = (
            f"📊 OPTIONS ADVISORY DAILY REPORT\n"
            f"{'='*35}\n"
            f"Date: {today_str}\n\n"
            f"Advisories: {len(today_advisories)}\n"
        )

        for a in closed:
            emoji = "✅" if a.paper_pnl >= 0 else "❌"
            pnl = f"{'+'if a.paper_pnl >= 0 else ''}₹{a.paper_pnl:,.0f}"
            summary += f"{emoji} {a.symbol} Bull Call | {pnl}\n"

        summary += f"\nPaper P&L: {pnl_sign}₹{total_pnl:,.0f}\n"
        if wins + losses > 0:
            summary += f"Win Rate: {wins}/{wins+losses} ({wins/(wins+losses)*100:.0f}%)\n"

        # Cumulative stats from DB
        if self._db:
            try:
                stats = self._db.get_options_spread_stats(days=30)
                if stats.get('total_advisories', 0) > 0:
                    summary += (
                        f"\n30-Day Cumulative:\n"
                        f"  Total: {stats.get('total_advisories', 0)} advisories\n"
                        f"  Win Rate: {stats.get('win_rate', 0):.0f}%\n"
                        f"  Paper P&L: ₹{stats.get('total_paper_pnl', 0):,.0f}\n"
                    )
            except Exception:
                pass

        # Show mode based on whether any advisory was live
        live_count = sum(1 for a in today_advisories if a.order_mode in ('LIVE', 'PARTIAL'))
        if live_count > 0:
            summary += f"\nMode: 🟢 LIVE ({live_count} orders placed)"
        else:
            summary += "\nMode: PAPER TRADE (Advisory Only)"
        return summary

    def reset_daily(self):
        """Reset for new trading day."""
        self.advisories.clear()
        self._next_id = 1
        self.daily_stats = {
            'advisories_generated': 0,
            'profitable': 0,
            'unprofitable': 0,
            'total_paper_pnl': 0.0,
            'best_trade': 0.0,
            'worst_trade': 0.0,
        }
        logger.info("   Phase 6: Daily reset complete")

    # ───────────────────────────────────────────────────────────────
    # TELEGRAM NOTIFICATIONS
    # ───────────────────────────────────────────────────────────────

    def _notify_new_advisory(self, advisory: SpreadAdvisory):
        """Send Telegram notification for new advisory."""
        if not self.telegram:
            return
        notify = getattr(self.config, 'PH6_NOTIFY_NEW_ADVISORY',
                         getattr(self.config, 'NOTIFY_NEW_ADVISORY', True))
        if not notify:
            return

        buy_leg = advisory.legs[0]
        sell_leg = advisory.legs[1]

        msg = (
            f"📊 OPTIONS ADVISORY #{advisory.id}\n"
            f"{'='*30}\n"
            f"Stock: {advisory.symbol} (Equity BUY @ ₹{advisory.equity_entry_price:,.2f})\n"
            f"Strategy: BULL CALL SPREAD\n"
            f"Expiry: {advisory.expiry}\n\n"
            f"Legs:\n"
            f"  BUY  {buy_leg.strike:.0f} CE @ ₹{buy_leg.entry_premium:.2f}\n"
            f"  SELL {sell_leg.strike:.0f} CE @ ₹{sell_leg.entry_premium:.2f}\n"
            f"  Net Debit: ₹{advisory.net_debit_per_share:.2f}/share\n\n"
            f"Max Profit: ₹{advisory.max_profit:,.0f} (lot: {advisory.lot_size})\n"
            f"Max Loss: ₹{advisory.max_loss:,.0f}\n"
            f"Breakeven: ₹{advisory.breakeven:,.2f}\n"
            f"R:R = 1:{advisory.risk_reward_ratio:.1f}\n\n"
            f"Confidence: {advisory.confidence}/100\n"
            f"PCR: {advisory.pcr} | Max Pain: ₹{advisory.max_pain:,.0f}\n\n"
        )
        if advisory.order_mode == "LIVE":
            msg += f"Mode: 🟢 LIVE ORDER (filled)"
        elif advisory.order_mode == "PARTIAL":
            msg += f"Mode: 🟡 PARTIAL (BUY filled, SELL failed)"
        else:
            msg += f"Mode: PAPER TRADE (Advisory Only)"

        try:
            self.telegram.send_message(msg)
        except Exception as e:
            logger.warning(f"   Telegram send failed: {e}")

    def _notify_advisory_closed(self, advisory: SpreadAdvisory):
        """Send Telegram notification when advisory closes."""
        if not self.telegram:
            return
        notify = getattr(self.config, 'PH6_NOTIFY_PAPER_CLOSE',
                         getattr(self.config, 'NOTIFY_PAPER_CLOSE', True))
        if not notify:
            return

        emoji = "✅" if advisory.paper_pnl >= 0 else "❌"
        pnl_sign = "+" if advisory.paper_pnl >= 0 else ""

        # v6.2: Special formatting for TCAS exits
        if advisory.status == AdvisoryStatus.PROFIT_LOCK_EXIT:
            msg = (
                f"🔒 TCAS EXIT {emoji}\n\n"
                f"#{advisory.id} {advisory.symbol}\n"
                f"BULL CALL SPREAD\n"
                f"Peak P&L: +{advisory.peak_pnl_pct:.1f}%\n"
                f"Lock Floor: +{advisory.profit_lock_pct:.0f}%\n"
                f"Exit P&L: {pnl_sign}₹{advisory.paper_pnl:,.2f} ({advisory.paper_pnl_pct:+.1f}%)\n"
                f"Reason: {advisory.exit_reason}"
            )
        else:
            msg = (
                f"📊 OPTIONS ADVISORY {emoji} CLOSED\n\n"
                f"#{advisory.id} {advisory.symbol}\n"
                f"BULL CALL SPREAD\n"
                f"Status: {advisory.status.value}\n"
                f"Paper P&L: {pnl_sign}₹{advisory.paper_pnl:,.2f} ({advisory.paper_pnl_pct:+.1f}%)\n"
                f"Reason: {advisory.exit_reason}"
            )
            if advisory.tcas_active:
                msg += f"\n🔒 TCAS: peak={advisory.peak_pnl_pct:.1f}% floor={advisory.profit_lock_pct:.0f}%"

        try:
            self.telegram.send_message(msg)
        except Exception as e:
            logger.warning(f"   Telegram send failed: {e}")

    # ═══════════════════════════════════════════════════════════════════════
    # v8.0.0: PHASE 8 MOMENTUM SHADOW MODE (ChatGPT GATED)
    # ═══════════════════════════════════════════════════════════════════════
    #
    # Unlike intraday shadows (auto-initialize), momentum shadows require
    # ChatGPT approval (score > 70). The cash trade is already executed.
    # ChatGPT only decides whether to paper-shadow with a CE option.
    # ═══════════════════════════════════════════════════════════════════════

    def handle_momentum_fill(self, fill_data: Dict):
        """
        Called when Phase 3 fills a PH8_MOMENTUM CNC order.

        Flow:
          1. Check if momentum shadow is enabled
          2. Collect weekly technical data (simplified)
          3. Enrich with options context (IV, chain)
          4. Send to ChatGPT for approval gate
          5. If score > 70 → initialize paper shadow
          6. If score <= 70 → reject, log, cash-only

        Args:
            fill_data: Dict with symbol, entry_price, quantity, weekly_return_pct, etc.
        """
        symbol = fill_data.get('symbol', '')
        entry_price = fill_data.get('entry_price', 0)

        logger.info(f"")
        logger.info(f"{'='*60}")
        logger.info(f"PH8 MOMENTUM SHADOW: {symbol}")
        logger.info(f"{'='*60}")

        # Check master switch
        if not getattr(self.config, 'PH8_SHADOW_ENABLED', False):
            logger.info(f"   PH8_SHADOW_ENABLED = False — skipping shadow")
            return

        try:
            # 1. Collect weekly technical data (simplified approach)
            weekly_technicals = self._collect_weekly_technicals(symbol, entry_price)

            # 2. Enrich with options context
            options_context = self._get_momentum_options_context(symbol, entry_price)

            # 3. ChatGPT approval gate
            if getattr(self.config, 'PH8_SHADOW_CHATGPT_GATE', True):
                gate_result = self._run_chatgpt_momentum_gate(
                    symbol=symbol,
                    entry_price=entry_price,
                    weekly_return_pct=fill_data.get('weekly_return_pct', 0),
                    weekly_technicals=weekly_technicals,
                    options_context=options_context,
                )
            else:
                # Gate disabled — auto-approve
                gate_result = {
                    'confidence': 100,
                    'decision': 'APPROVE',
                    'reasoning': 'ChatGPT gate disabled',
                    'recommended_strike': options_context.get('atm_strike'),
                    'recommended_expiry': options_context.get('expiry_date'),
                }

            if not gate_result:
                # ChatGPT failed — failsafe = NO_SHADOW
                failsafe = getattr(self.config, 'PH8_SHADOW_FAILSAFE', 'NO_SHADOW')
                logger.warning(f"   ChatGPT gate failed — failsafe: {failsafe}")
                self._ph8_notify(
                    f"PH8 SHADOW GATE FAILED\n"
                    f"ChatGPT API timeout/error — defaulting to NO SHADOW\n"
                    f"{symbol} cash position continues in Tier 3"
                )
                return

            confidence = gate_result.get('confidence', 0)
            decision = gate_result.get('decision', 'REJECT')
            min_confidence = getattr(self.config, 'PH8_SHADOW_MIN_CONFIDENCE', 70)

            if confidence > min_confidence and decision == 'APPROVE':
                # APPROVED — initialize shadow
                logger.info(f"   APPROVED: score={confidence}/100")
                self._initialize_momentum_shadow(fill_data, gate_result, options_context)
                self._ph8_notify(
                    f"PH8 SHADOW APPROVED (score: {confidence}/100)\n"
                    f"{symbol} {gate_result.get('recommended_strike', 'ATM')}CE "
                    f"{gate_result.get('recommended_expiry', 'N/A')} "
                    f"@ Rs{options_context.get('atm_premium', 0):.2f}\n"
                    f"Reason: {gate_result.get('reasoning', 'N/A')}\n"
                    f"Risk: {gate_result.get('risk_flag', 'None')}"
                )
            else:
                # REJECTED — cash-only
                logger.info(f"   REJECTED: score={confidence}/100 (min: {min_confidence})")
                self._ph8_notify(
                    f"PH8 SHADOW REJECTED (score: {confidence}/100)\n"
                    f"{symbol} — cash position continues WITHOUT options shadow\n"
                    f"Reason: {gate_result.get('reasoning', 'N/A')}"
                )

        except Exception as e:
            logger.error(f"   Momentum shadow error: {type(e).__name__}: {e}",
                         exc_info=True)
            self._ph8_notify(f"PH8 SHADOW ERROR: {symbol}: {e}")

    def _collect_weekly_technicals(self, symbol: str, entry_price: float) -> Dict:
        """
        Collect simplified weekly technical data for ChatGPT momentum gate.
        Uses daily candles (20 days) as proxy for weekly indicators.
        """
        technicals = {
            'rsi': 'N/A', 'adx': 'N/A', 'plus_di': 'N/A', 'minus_di': 'N/A',
            'vwap_position': 'N/A', 'vwap_distance_pct': 0,
            'ema_trend': 'N/A', 'current_volume': 0, 'avg_volume': 0,
            'volume_ratio': 0, 'atr': 0, 'atr_pct': 0, 'sector_score': 50,
        }

        try:
            if not hasattr(self, '_nse_instruments') or not self._nse_instruments:
                try:
                    self._nse_instruments = {
                        inst['tradingsymbol']: inst['instrument_token']
                        for inst in self.kite.instruments('NSE')
                        if inst.get('instrument_type') == 'EQ'
                    }
                except Exception:
                    self._nse_instruments = {}

            token = self._nse_instruments.get(symbol)
            if not token:
                return technicals

            from datetime import date as date_cls, timedelta
            to_date = date_cls.today() - timedelta(days=1)
            from_date = to_date - timedelta(days=40)

            candles = self.kite.historical_data(token, from_date, to_date, "day")
            if not candles or len(candles) < 14:
                return technicals

            closes = [c['close'] for c in candles]
            highs = [c['high'] for c in candles]
            lows = [c['low'] for c in candles]
            volumes = [c['volume'] for c in candles]

            # RSI (14-period)
            gains = []
            losses = []
            for i in range(1, min(15, len(closes))):
                change = closes[-i] - closes[-i-1]
                if change > 0:
                    gains.append(change)
                else:
                    losses.append(abs(change))
            avg_gain = sum(gains) / 14 if gains else 0.001
            avg_loss = sum(losses) / 14 if losses else 0.001
            rs = avg_gain / max(avg_loss, 0.001)
            rsi = 100 - (100 / (1 + rs))
            technicals['rsi'] = round(rsi, 1)

            # ATR (14-period)
            trs = []
            for i in range(-14, 0):
                if abs(i) < len(candles):
                    tr = max(
                        highs[i] - lows[i],
                        abs(highs[i] - closes[i-1]) if i > -len(candles) else 0,
                        abs(lows[i] - closes[i-1]) if i > -len(candles) else 0
                    )
                    trs.append(tr)
            atr = sum(trs) / len(trs) if trs else 0
            technicals['atr'] = round(atr, 2)
            technicals['atr_pct'] = round(atr / entry_price * 100, 1) if entry_price > 0 else 0

            # Volume ratio
            recent_vol = volumes[-1] if volumes else 0
            avg_vol = sum(volumes[-20:]) / min(20, len(volumes)) if volumes else 1
            technicals['current_volume'] = recent_vol
            technicals['avg_volume'] = int(avg_vol)
            technicals['volume_ratio'] = round(recent_vol / max(avg_vol, 1), 1)

            # EMA trend (21-period simplified)
            if len(closes) >= 21:
                ema = sum(closes[-21:]) / 21
                if closes[-1] > ema * 1.01:
                    technicals['ema_trend'] = 'rising'
                elif closes[-1] < ema * 0.99:
                    technicals['ema_trend'] = 'falling'
                else:
                    technicals['ema_trend'] = 'flat'

        except Exception as e:
            logger.debug(f"   Weekly technicals error: {e}")

        return technicals

    def _get_momentum_options_context(self, symbol: str, spot_price: float) -> Dict:
        """
        Fetch options context for the momentum shadow gate.
        Targets 2-week out expiry.
        """
        context = {
            'iv_percentile': 'N/A', 'iv_low': 'N/A', 'iv_high': 'N/A',
            'atm_strike': 0, 'atm_premium': 0, 'delta': 'N/A',
            'theta': 0, 'expiry_date': 'N/A', 'dte': 0,
            'chain_summary': 'N/A',
        }

        try:
            if self._is_nfo_cache_stale():
                self._load_nfo_instruments()

            if symbol not in self._fno_stock_set:
                logger.info(f"   {symbol} not in F&O segment")
                return context

            from datetime import date as date_cls, timedelta
            target_expiry_date = date_cls.today() + timedelta(
                weeks=getattr(self.config, 'PH8_SHADOW_EXPIRY_WEEKS', 2)
            )

            stock_expiries = set()
            for inst in self._nfo_cache:
                if (inst.get('name') == symbol and
                        inst.get('instrument_type') == 'CE'):
                    exp = inst.get('expiry')
                    if exp and isinstance(exp, date_cls):
                        if exp >= date_cls.today():
                            stock_expiries.add(exp)
                    elif exp:
                        try:
                            exp_date = date_cls.fromisoformat(str(exp)[:10])
                            if exp_date >= date_cls.today():
                                stock_expiries.add(exp_date)
                        except (ValueError, TypeError):
                            pass

            if not stock_expiries:
                return context

            sorted_expiries = sorted(stock_expiries)
            selected_expiry = None
            for exp in sorted_expiries:
                if exp >= target_expiry_date:
                    selected_expiry = exp
                    break
            if not selected_expiry and sorted_expiries:
                selected_expiry = sorted_expiries[-1]

            if not selected_expiry:
                return context

            dte = (selected_expiry - date_cls.today()).days
            context['expiry_date'] = selected_expiry.isoformat()
            context['dte'] = dte

            atm_strike = round(spot_price / 50) * 50
            available_strikes = set()
            for inst in self._nfo_cache:
                if (inst.get('name') == symbol and
                        inst.get('instrument_type') == 'CE' and
                        inst.get('expiry') == selected_expiry):
                    available_strikes.add(inst.get('strike', 0))

            if available_strikes:
                atm_strike = min(available_strikes, key=lambda s: abs(s - spot_price))

            context['atm_strike'] = atm_strike

            for inst in self._nfo_cache:
                if (inst.get('name') == symbol and
                        inst.get('instrument_type') == 'CE' and
                        inst.get('expiry') == selected_expiry and
                        inst.get('strike') == atm_strike):
                    ts = inst.get('tradingsymbol', '')
                    try:
                        quote = self.kite.quote([f"NFO:{ts}"])
                        quote_data = quote.get(f"NFO:{ts}", {})
                        context['atm_premium'] = quote_data.get('last_price', 0)
                    except Exception:
                        pass
                    break

            context['chain_summary'] = (
                f"{len(available_strikes)} strikes, expiry {selected_expiry}, "
                f"ATM={atm_strike}"
            )

        except Exception as e:
            logger.debug(f"   Options context error: {e}")

        return context

    def _run_chatgpt_momentum_gate(self, symbol: str, entry_price: float,
                                    weekly_return_pct: float,
                                    weekly_technicals: Dict,
                                    options_context: Dict) -> Optional[Dict]:
        """Run ChatGPT approval gate for momentum CE shadow."""
        if not self.chatgpt:
            logger.warning("   ChatGPT advisor not available — gate fails")
            return None

        try:
            quotes = self.kite.quote([f"NSE:{symbol}"])
            spot_price = quotes.get(f"NSE:{symbol}", {}).get('last_price', entry_price)

            return self.chatgpt.review_momentum_options(
                symbol=symbol,
                spot_price=spot_price,
                entry_price=entry_price,
                weekly_return_pct=weekly_return_pct,
                weekly_technicals=weekly_technicals,
                options_context=options_context,
            )
        except Exception as e:
            logger.error(f"   ChatGPT momentum gate error: {e}")
            return None

    def _initialize_momentum_shadow(self, fill_data: Dict, gate_result: Dict,
                                     options_context: Dict):
        """Initialize a paper CE shadow for the momentum position."""
        symbol = fill_data.get('symbol', '')
        entry_price = fill_data.get('entry_price', 0)
        strike = gate_result.get('recommended_strike', options_context.get('atm_strike', 0))
        expiry = gate_result.get('recommended_expiry', options_context.get('expiry_date', ''))
        premium = options_context.get('atm_premium', 0)

        advisory_id = len(self.advisories) + 1

        advisory = SpreadAdvisory(
            id=advisory_id,
            timestamp=datetime.now().isoformat(),
            symbol=symbol,
            spot_price=entry_price,
            equity_order_id=fill_data.get('order_id', ''),
            equity_entry_price=entry_price,
            spread_type='MOMENTUM_CE',
            max_profit=premium * 100,
            max_loss=premium * 100,
            breakeven=strike + premium if strike else 0,
            net_debit_per_share=premium,
            confidence=gate_result.get('confidence', 0),
            reasoning=gate_result.get('reasoning', ''),
            expiry=str(expiry) if expiry else '',
            entry_net_premium=premium,
            current_net_premium=premium,
            order_mode='PAPER',
        )

        advisory.web_news = (
            f"PH8 Gate: confidence={gate_result.get('confidence', 0)}, "
            f"risk={gate_result.get('risk_flag', 'none')}"
        )

        self.advisories.append(advisory)

        try:
            self._save_advisory_to_db(advisory)
        except Exception as e:
            logger.debug(f"   DB save error: {e}")

        logger.info(f"   Momentum shadow initialized: {symbol} {strike}CE {expiry} "
                     f"@ Rs{premium:.2f}")

    def on_momentum_cash_exit(self, symbol: str, exit_price: float, reason: str):
        """Called by Phase 4 when a Tier 3 position exits. Closes momentum shadow."""
        logger.info(f"   PH8 Shadow: cash exit notification for {symbol} ({reason})")

        if not getattr(self.config, 'PH8_SHADOW_EXIT_ON_CASH', True):
            return

        for advisory in self.advisories:
            if (advisory.symbol == symbol and
                    advisory.spread_type == 'MOMENTUM_CE' and
                    advisory.is_open):
                self._close_advisory(
                    advisory,
                    AdvisoryStatus.EXPIRED,
                    f"Cash exit: {reason}"
                )
                logger.info(f"   Momentum shadow closed for {symbol}")
                break

    def on_tcas_direction_signal(self, signal: dict):
        """
        ISSUE-15: Called by Phase 4 with TCAS pivot signals.

        Two signal types (signal['status']):

        'EARLY_WARNING'  — TCAS RA detected on a losing SHORT, equity STILL OPEN.
                           Price is rising, Kalman confirms BULLISH momentum.
                           Phase 6 receives this early so it can analyse and
                           prepare/enter options while the move is happening.
                           This is the actionable signal — equity is live context.

        'EXIT_CONFIRMED' — Equity has just been closed by TCAS ALIM/RA.
                           Phase 6 was already alerted at RA. This update lets it
                           know the equity leg is gone and it can act freely.

        Args:
            signal: dict with keys — symbol, status, signal_time, signal_price,
                    equity_entry, equity_stop, atr, kalman_velocity,
                    kalman_acceleration, tcas_alert, equity_pnl,
                    equity_still_open (EARLY_WARNING only),
                    exit_price / exit_reason (EXIT_CONFIRMED only)
        """
        symbol = signal.get('symbol', '')
        status = signal.get('status', 'EARLY_WARNING')
        signal_price = signal.get('signal_price', 0)
        equity_pnl = signal.get('equity_pnl', 0)
        kal_velocity = signal.get('kalman_velocity', 0)
        tcas_alert = signal.get('tcas_alert', 'RA')

        # ───────────────────────────────────────────────────────────────
        # EXIT_CONFIRMED: equity is now closed — log and notify, no new
        # advisory (generate_advisory was already triggered at EARLY_WARNING)
        # ───────────────────────────────────────────────────────────────
        if status == 'EXIT_CONFIRMED':
            exit_price  = signal.get('exit_price', signal_price)
            exit_reason = signal.get('exit_reason', 'TCAS')
            signal_time = signal.get('signal_time')
            time_str = signal_time.strftime('%H:%M:%S') if signal_time else '--:--:--'
            logger.info(f"")
            logger.info(f"📡 PHASE 6: TCAS PIVOT — {symbol} EQUITY CLOSED")
            logger.info(f"   Exit: ₹{exit_price:.2f} | Reason: {exit_reason} | P&L: {equity_pnl:+.2f}%")
            logger.info(f"   Phase 6 advisory already running — options leg continues independently")
            if self.telegram:
                try:
                    self.telegram.send_message(
                        f"📡 TCAS PIVOT — EQUITY CLOSED\n"
                        f"{'='*32}\n"
                        f"Symbol  : {symbol}\n"
                        f"Time    : {time_str}\n"
                        f"\n"
                        f"EQUITY EXIT:\n"
                        f"  Exit Price : ₹{exit_price:,.2f}\n"
                        f"  Reason     : {exit_reason}\n"
                        f"  Equity P&L : {equity_pnl:+.2f}%\n"
                        f"\n"
                        f"OPTIONS STATUS:\n"
                        f"  Advisory triggered at TCAS RA (early warning)\n"
                        f"  Options leg running independently — no equity dependency\n"
                        f"  Monitor advisory for CALL spread P&L"
                    )
                except Exception as e:
                    logger.warning(f"   Telegram EXIT_CONFIRMED notification failed: {e}")
            return  # Advisory was already triggered at EARLY_WARNING stage

        # ───────────────────────────────────────────────────────────────
        # EARLY_WARNING: equity is STILL OPEN — this is the live signal.
        # Use Claude/ChatGPT inside generate_advisory to decide whether to
        # enter CALL options NOW while the upward move is in progress.
        # ───────────────────────────────────────────────────────────────

        # v1.3.0: Phase 9 options bias gate
        # If morning briefing marked today as BEARISH, a CALL setup from a failed
        # SHORT is fighting the whole market — skip it entirely.
        # PUT bias day also means a BULLISH CALL pivot is low-probability.
        _briefing = getattr(self, 'daily_briefing', {})
        _ph6_bias = _briefing.get('ph6_options_bias', 'NEUTRAL')
        _vix_regime = _briefing.get('vix_regime', 'NORMAL')
        if _ph6_bias == 'PUT':
            logger.info(f"PH6 TCAS PIVOT BLOCKED for {symbol}: "
                        f"morning briefing bias=PUT (BEARISH day) — CALL setup not warranted")
            if self.telegram:
                try:
                    self.telegram.send_message(
                        f"⚠️ PH6 TCAS PIVOT BLOCKED — {symbol}\n"
                        f"Reason: Morning briefing bias = PUT (BEARISH day)\n"
                        f"CALL setup skipped — direction against market."
                    )
                except Exception:
                    pass
            return

        eq_entry   = signal.get('equity_entry', 0)
        eq_stop    = signal.get('equity_stop', 0)
        atr_val    = signal.get('atr', 0)
        kal_accel  = signal.get('kalman_acceleration', 0)
        signal_time = signal.get('signal_time')
        time_str = signal_time.strftime('%H:%M:%S') if signal_time else '--:--:--'

        dist_to_stop = eq_stop - signal_price   # SHORT: stop is above current price
        dist_atr     = (dist_to_stop / atr_val) if atr_val > 0 else 0
        acc_label    = (f"+{kal_accel:.3f} (building)" if kal_accel > 0
                        else f"{kal_accel:.3f} (flat)")

        logger.info(f"")
        logger.info(f"{'='*60}")
        logger.info(f"📡 PHASE 6: TCAS PIVOT EARLY WARNING — {symbol}")
        logger.info(f"{'='*60}")
        logger.info(f"   TCAS {tcas_alert} on SHORT | Equity still OPEN at ₹{signal_price:.2f}")
        logger.info(f"   Entry ₹{eq_entry:.2f} | Stop ₹{eq_stop:.2f} | ATR ₹{atr_val:.2f}")
        logger.info(f"   Equity P&L: {equity_pnl:+.2f}% | Kalman vel: +{kal_velocity:.2f}/min | accel: {acc_label}")
        logger.info(f"   Confirmed direction: BULLISH — Phase 6 analysing CALL options early")

        if self.telegram:
            try:
                self.telegram.send_message(
                    f"📡 PHASE 6 — TCAS PIVOT RECEIVED\n"
                    f"{'='*32}\n"
                    f"Symbol : {symbol}\n"
                    f"Time   : {time_str}\n"
                    f"\n"
                    f"WHY THIS TRADE:\n"
                    f"  • SHORT position hit TCAS {tcas_alert} — price rising against trade\n"
                    f"  • Equity in loss ({equity_pnl:+.2f}%) — direction confirmed wrong\n"
                    f"  • Kalman momentum: +{kal_velocity:.3f}/min rising, accel {acc_label}\n"
                    f"  • Opposite direction = BULLISH → CALL options opportunity\n"
                    f"  • Equity still OPEN — signal sent early for proactive entry\n"
                    f"\n"
                    f"INPUT PARAMETERS:\n"
                    f"  TCAS Alert    : {tcas_alert}  (RA = dangerous zone)\n"
                    f"  Current Price : ₹{signal_price:,.2f}\n"
                    f"  Equity Entry  : ₹{eq_entry:,.2f}\n"
                    f"  Equity Stop   : ₹{eq_stop:,.2f}  ({dist_to_stop:.2f} away, {dist_atr:.2f} ATR)\n"
                    f"  ATR           : ₹{atr_val:.2f}\n"
                    f"  Equity P&L    : {equity_pnl:+.2f}%\n"
                    f"  Kalman Vel    : +{kal_velocity:.3f}/min\n"
                    f"  Kalman Accel  : {acc_label}\n"
                    f"\n"
                    f"PHASE 6 ACTION:\n"
                    f"  Running Bull Call Spread analysis via ChatGPT\n"
                    f"  (options chain, strikes, premium, R:R to follow)"
                )
            except Exception as e:
                logger.warning(f"   Telegram EARLY_WARNING notification failed: {e}")

        # generate_advisory runs F&O check, DTE gate, options chain, ChatGPT
        # (Claude) analysis, and Bull Call Spread — Phase 6 uses its own
        # intelligence to decide entry timing, not Phase 4's exit trigger.
        try:
            advisory = self.generate_advisory(
                symbol=symbol,
                equity_order_id=f"TCAS_PIVOT_{symbol}",
                equity_entry_price=signal_price,
                phase2_score=80,   # TCAS + Kalman direction confirmation = high confidence
            )
            if advisory is None:
                logger.info(f"   Phase 6 skipped {symbol} — F&O/liquidity/DTE gate rejected")
        except Exception as e:
            logger.error(f"   generate_advisory failed for TCAS pivot {symbol}: {e}")

    def check_momentum_shadows(self):
        """Check all open momentum shadows for independent exit triggers."""
        target_pct = getattr(self.config, 'PH8_SHADOW_OPTION_TARGET_PCT', 1.0)
        buffer_days = getattr(self.config, 'PH8_SHADOW_EXPIRY_BUFFER_DAYS', 2)

        for advisory in self.advisories:
            if not (advisory.spread_type == 'MOMENTUM_CE' and advisory.is_open):
                continue

            try:
                if (advisory.entry_net_premium > 0 and
                        advisory.current_net_premium > 0):
                    gain_pct = ((advisory.current_net_premium - advisory.entry_net_premium) /
                                advisory.entry_net_premium)
                    if gain_pct >= target_pct:
                        logger.info(f"   PH8 Shadow target hit: {advisory.symbol} "
                                    f"+{gain_pct:.0%}")
                        self._close_advisory(
                            advisory,
                            AdvisoryStatus.TARGET_HIT,
                            f"Momentum CE target: +{gain_pct:.0%}"
                        )
                        self._ph8_notify(
                            f"PH8 SHADOW TARGET\n"
                            f"{advisory.symbol} CE: Rs{advisory.entry_net_premium:.2f} "
                            f"-> Rs{advisory.current_net_premium:.2f} "
                            f"(+{gain_pct:.0%})\n"
                            f"Cash position still ACTIVE in Tier 3"
                        )
                        continue

                if advisory.expiry:
                    from datetime import date as date_cls
                    try:
                        exp_date = date_cls.fromisoformat(advisory.expiry[:10])
                        dte = (exp_date - date_cls.today()).days
                        if dte <= buffer_days:
                            logger.info(f"   PH8 Shadow expiry approaching: "
                                        f"{advisory.symbol} DTE={dte}")
                            self._close_advisory(
                                advisory,
                                AdvisoryStatus.EXPIRED,
                                f"Expiry buffer: DTE={dte}"
                            )
                            self._ph8_notify(
                                f"PH8 SHADOW EXPIRY\n"
                                f"{advisory.symbol} CE expiring in {dte} days\n"
                                f"Entry: Rs{advisory.entry_net_premium:.2f} | "
                                f"Current: Rs{advisory.current_net_premium:.2f}\n"
                                f"Cash position unaffected"
                            )
                    except (ValueError, TypeError):
                        pass

            except Exception as e:
                logger.error(f"   Momentum shadow check error for {advisory.symbol}: {e}")

    def _ph8_notify(self, message: str):
        """Phase 8 shadow notification — never crashes."""
        try:
            if self.telegram:
                self.telegram.send_message(message)
        except Exception:
            pass
