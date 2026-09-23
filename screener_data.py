"""
SCREENER DATA FETCHER — Phase 8 Universe Provider
═══════════════════════════════════════════════════════════════════════════════

Fetches and caches large-cap stock universe from screener.in.
Used by Phase 8 Momentum Strategy to identify eligible stocks (market cap > ₹25,000 crore).

FALLBACK CHAIN:
  1. Live fetch from screener.in
  2. Cached data (even if stale, up to 30 days)
  3. MASTER_STOCK_LIST hardcoded fallback (NIFTY 100 proxy)
  4. CRITICAL error — skip Phase 8 this week

v1.0.0 (2026-03-04): Initial implementation for Phase 8 Momentum Strategy
"""

import json
import os
import time
import logging
import requests
from datetime import datetime, timedelta
from typing import List, Dict, Optional

logger = logging.getLogger('ScreenerData')


# ═══════════════════════════════════════════════════════════════════════════════
# HARDCODED FALLBACK — NIFTY 100 Large-Cap Proxy
# Used ONLY when screener.in is down AND cache is missing/corrupt
# ═══════════════════════════════════════════════════════════════════════════════
_FALLBACK_LARGE_CAPS = [
    "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK", "HINDUNILVR", "SBIN",
    "BHARTIARTL", "ITC", "KOTAKBANK", "LT", "HCLTECH", "AXISBANK", "ASIANPAINT",
    "MARUTI", "SUNPHARMA", "TITAN", "BAJFINANCE", "DMART", "NTPC", "ULTRACEMCO",
    "WIPRO", "ADANIENT", "ADANIPORTS", "ONGC", "JSWSTEEL", "POWERGRID", "M&M",
    "TATAMOTORS", "TATASTEEL", "TECHM", "HDFCLIFE", "BAJAJFINSV", "NESTLEIND",
    "DIVISLAB", "GRASIM", "CIPLA", "DRREDDY", "APOLLOHOSP", "HEROMOTOCO",
    "EICHERMOT", "SBILIFE", "COALINDIA", "BPCL", "TATACONSUM", "BRITANNIA",
    "HINDALCO", "INDUSINDBK", "ADANIGREEN", "BAJAJ-AUTO", "DABUR", "PIDILITIND",
    "GODREJCP", "SIEMENS", "HAVELLS", "AMBUJACEM", "DLF", "BANKBARODA",
    "TRENT", "ABB", "JINDALSTEL", "VEDL", "IOC", "ICICIPRULI", "SHREECEM",
    "TORNTPHARM", "INDIGO", "SRF", "MUTHOOTFIN", "PNB", "NAUKRI",
    "LUPIN", "BERGEPAINT", "MARICO", "COLPAL", "AUROPHARMA", "VOLTAS",
    "CANBK", "PAGEIND", "IRCTC", "SAIL", "TVSMOTOR", "GAIL", "BOSCHLTD",
    "PERSISTENT", "LTIM", "LTTS", "ZOMATO", "POLICYBZR", "PAYTM",
    "HAL", "BEL", "BHEL", "RECLTD", "PFC", "NHPC", "IRFC",
    "JIOFIN", "JIOFINANCE",
]


class ScreenerDataFetcher:
    """
    Fetches and caches market cap data for Phase 8 momentum universe.

    Usage:
        fetcher = ScreenerDataFetcher(config)
        universe = fetcher.get_mcap_universe()
        # Returns: [{"symbol": "RELIANCE", "kite_symbol": "RELIANCE",
        #            "market_cap_crore": 1850000, "sector": "Oil & Gas", ...}, ...]
    """

    # Known symbol mapping exceptions: screener.in name → Kite NSE symbol
    _SYMBOL_MAP_OVERRIDES = {
        "M&MFIN": "M&MFIN",
        "M&M": "M&M",
        "L&TFH": "L&TFH",
        "NAM-INDIA": "NAM-INDIA",
    }

    def __init__(self, config):
        self.config = config
        self.cache_file = getattr(config, 'PH8_SCREENER_CACHE_FILE', 'data/screener_mcap_cache.json')
        self.cache_ttl_days = getattr(config, 'PH8_SCREENER_CACHE_TTL_DAYS', 7)
        self.min_mcap_crore = getattr(config, 'PH8_MIN_MCAP_CRORE', 25000)
        self._last_fetch_time = 0  # Rate limiting

    # ───────────────────────────────────────────────────────────────────────
    # PUBLIC API
    # ───────────────────────────────────────────────────────────────────────

    def get_mcap_universe(self) -> List[Dict]:
        """
        Returns list of stocks with market cap > PH8_MIN_MCAP_CRORE.
        Uses cache if fresh (< TTL days). Refreshes from screener.in if stale.

        Returns:
            List of dicts: [
                {"symbol": "RELIANCE", "kite_symbol": "RELIANCE",
                 "market_cap_crore": 1850000, "sector": "Oil & Gas",
                 "company_name": "Reliance Industries"},
                ...
            ]
            Empty list on total failure (never raises).
        """
        # 1. Try cache first
        cached = self._load_cache()
        if cached and not self._is_cache_stale():
            logger.info(f"📦 Screener cache: {len(cached)} stocks (fresh, TTL={self.cache_ttl_days}d)")
            return cached

        # 2. Cache stale or missing — try live fetch
        logger.info("🔄 Screener cache stale/missing — fetching from screener.in...")
        live_data = self._fetch_from_screener()

        if live_data and len(live_data) >= 20:
            # Sanity check: screener should return at least 20 large-caps
            self._save_cache(live_data)
            logger.info(f"✅ Screener live fetch: {len(live_data)} stocks cached")
            return live_data

        # 3. Live fetch failed — use stale cache if available
        if cached:
            cache_age = self._get_cache_age_days()
            if cache_age <= 30:
                logger.warning(f"⚠️ Screener.in fetch failed — using stale cache "
                               f"({cache_age:.0f} days old, {len(cached)} stocks)")
                return cached
            else:
                logger.warning(f"⚠️ Cache too old ({cache_age:.0f} days) — falling back to hardcoded list")

        # 4. No cache, no live data — use hardcoded fallback
        logger.error("🚨 SCREENER FALLBACK: Using hardcoded NIFTY 100 proxy list")
        return self._build_fallback_universe()

    def refresh_cache(self) -> bool:
        """
        Force-refresh the cache from screener.in.
        Called by orchestrator on Sunday night or Wednesday pre-market if stale.

        Returns:
            True if refresh succeeded
        """
        live_data = self._fetch_from_screener()
        if live_data and len(live_data) >= 20:
            self._save_cache(live_data)
            logger.info(f"✅ Cache force-refreshed: {len(live_data)} stocks")
            return True
        logger.warning("⚠️ Cache refresh failed — keeping existing cache")
        return False

    def get_mcap_lookup(self) -> Dict[str, Dict]:
        """
        Returns market cap lookup dict keyed by Kite trading symbol.

        Used by Phase 8 to FILTER Ph1's MASTER_STOCK_LIST by market cap.
        This is NOT the stock universe source — Ph1's list is.

        Returns:
            {
                "RELIANCE": {"market_cap_crore": 1850000, "sector": "Oil & Gas"},
                "HDFCBANK": {"market_cap_crore": 1120000, "sector": "Banking"},
                ...
            }
            Empty dict on total failure (never raises).
        """
        universe = self.get_mcap_universe()
        lookup = {}
        for stock in universe:
            sym = stock.get('kite_symbol') or stock.get('symbol', '')
            if sym:
                lookup[sym] = {
                    'market_cap_crore': stock.get('market_cap_crore', 0),
                    'sector': stock.get('sector', 'Unknown'),
                }
        return lookup

    # ───────────────────────────────────────────────────────────────────────
    # SCREENER.IN FETCHING
    # ───────────────────────────────────────────────────────────────────────

    def _fetch_from_screener(self) -> List[Dict]:
        """
        Scrape screener.in for stocks with market cap > threshold.

        Uses screener.in's screen results page.
        Polite scraping: User-Agent header, 2s rate limit between requests.

        Returns:
            List of stock dicts, or empty list on failure.
        """
        try:
            # Rate limiting: max 1 request per 2 seconds
            elapsed = time.time() - self._last_fetch_time
            if elapsed < 2.0:
                time.sleep(2.0 - elapsed)

            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                              '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.9',
            }

            # Strategy: Use screener.in's company search/export API
            # The screen URL for large caps: https://www.screener.in/screens/71/large-cap-stocks/
            # But the reliable approach is the company search API
            all_stocks = []
            page = 1
            max_pages = 15  # Safety limit

            while page <= max_pages:
                url = (f"https://www.screener.in/api/company/search/"
                       f"?q=&limit=50&offset={(page - 1) * 50}")

                # Alternative approach: Use the screen results page
                # screener.in doesn't have a clean public API for market cap filtering
                # So we'll use their company listing with pagination
                url = f"https://www.screener.in/screens/71/large-cap-stocks/?page={page}"

                response = requests.get(url, headers=headers, timeout=15)
                self._last_fetch_time = time.time()

                if response.status_code == 403:
                    logger.warning("⚠️ Screener.in blocked request (403) — possible rate limit or captcha")
                    break
                elif response.status_code == 404:
                    logger.info(f"   Page {page}: 404 — no more pages")
                    break
                elif response.status_code != 200:
                    logger.warning(f"⚠️ Screener.in HTTP {response.status_code} on page {page}")
                    break

                # Parse HTML response for stock data
                stocks_on_page = self._parse_screener_html(response.text)

                if not stocks_on_page:
                    break

                all_stocks.extend(stocks_on_page)
                logger.info(f"   Page {page}: {len(stocks_on_page)} stocks parsed "
                            f"(total: {len(all_stocks)})")

                page += 1
                time.sleep(2)  # Polite delay between pages

            # Filter by market cap threshold
            filtered = [s for s in all_stocks
                        if s.get('market_cap_crore', 0) >= self.min_mcap_crore]

            logger.info(f"   Screener.in total: {len(all_stocks)} stocks, "
                        f"filtered (≥₹{self.min_mcap_crore} cr): {len(filtered)}")

            return filtered

        except requests.Timeout:
            logger.error("🚨 Screener.in request timed out (15s)")
            return []
        except requests.ConnectionError:
            logger.error("🚨 Screener.in connection failed — network issue or site down")
            return []
        except Exception as e:
            logger.error(f"🚨 Screener.in fetch error: {type(e).__name__}: {e}")
            return []

    def _parse_screener_html(self, html: str) -> List[Dict]:
        """
        Parse screener.in HTML response to extract stock data.

        Screener.in's large-cap screen page contains a table with columns:
        S.No. | Name | CMP | P/E | Mar Cap (Cr.)  | ...

        Returns:
            List of stock dicts parsed from HTML table
        """
        stocks = []
        try:
            # Simple HTML table parsing without BeautifulSoup dependency
            # Look for table rows containing stock data
            import re

            # Find all table rows with stock links
            # Pattern: <a href="/company/SYMBOL/">Company Name</a>
            company_pattern = re.compile(
                r'<a\s+class="ink-600"\s+href="/company/([^/]+)/"[^>]*>([^<]+)</a>',
                re.IGNORECASE
            )

            # Find market cap values — they appear in table cells
            # The page structure has rows with multiple <td> elements
            row_pattern = re.compile(
                r'<tr[^>]*data-row-company-id[^>]*>(.*?)</tr>',
                re.DOTALL | re.IGNORECASE
            )

            # Alternative: find rows by looking for company links and nearby numbers
            rows = row_pattern.findall(html)

            for row_html in rows:
                company_match = company_pattern.search(row_html)
                if not company_match:
                    continue

                screener_symbol = company_match.group(1).strip()
                company_name = company_match.group(2).strip()

                # Extract numeric values from <td> elements
                td_values = re.findall(r'<td[^>]*>\s*([\d,]+\.?\d*)\s*</td>', row_html)

                # Market cap is typically the 4th or 5th numeric column
                market_cap = 0
                if len(td_values) >= 4:
                    try:
                        # Try to find the largest number (market cap is usually largest)
                        numeric_vals = []
                        for v in td_values:
                            try:
                                numeric_vals.append(float(v.replace(',', '')))
                            except ValueError:
                                continue
                        # Market cap should be > 1000 (in crores)
                        large_vals = [v for v in numeric_vals if v > 1000]
                        if large_vals:
                            market_cap = max(large_vals)  # Market cap is the largest number
                    except (ValueError, IndexError):
                        pass

                if market_cap <= 0:
                    continue

                kite_symbol = self._map_symbol_to_kite(screener_symbol)

                stocks.append({
                    'symbol': screener_symbol,
                    'kite_symbol': kite_symbol,
                    'company_name': company_name,
                    'market_cap_crore': market_cap,
                    'sector': '',  # Screener doesn't always show sector in list view
                })

        except Exception as e:
            logger.error(f"   HTML parse error: {type(e).__name__}: {e}")

        return stocks

    # ───────────────────────────────────────────────────────────────────────
    # SYMBOL MAPPING
    # ───────────────────────────────────────────────────────────────────────

    def _map_symbol_to_kite(self, screener_symbol: str) -> str:
        """
        Map screener.in symbol → Kite NSE trading symbol.
        Most are 1:1. Handle known exceptions via override dict.
        """
        # Check override table first
        if screener_symbol in self._SYMBOL_MAP_OVERRIDES:
            return self._SYMBOL_MAP_OVERRIDES[screener_symbol]

        # Default: screener.in and Kite NSE symbols match
        return screener_symbol

    # ───────────────────────────────────────────────────────────────────────
    # CACHE MANAGEMENT
    # ───────────────────────────────────────────────────────────────────────

    def _load_cache(self) -> Optional[List[Dict]]:
        """Load from cache JSON file if exists."""
        try:
            if not os.path.exists(self.cache_file):
                return None

            with open(self.cache_file, 'r') as f:
                data = json.load(f)

            if not isinstance(data, dict) or 'stocks' not in data:
                logger.warning("⚠️ Cache file format invalid — ignoring")
                return None

            stocks = data.get('stocks', [])
            timestamp = data.get('timestamp', '')
            logger.debug(f"   Cache loaded: {len(stocks)} stocks, saved {timestamp}")
            return stocks

        except (json.JSONDecodeError, IOError) as e:
            logger.error(f"⚠️ Cache load error: {e}")
            return None

    def _save_cache(self, stocks: List[Dict]):
        """Save to cache JSON file with timestamp."""
        try:
            os.makedirs(os.path.dirname(self.cache_file), exist_ok=True)

            cache_data = {
                'timestamp': datetime.now().isoformat(),
                'min_mcap_crore': self.min_mcap_crore,
                'stock_count': len(stocks),
                'stocks': stocks,
            }

            with open(self.cache_file, 'w') as f:
                json.dump(cache_data, f, indent=2)

            logger.info(f"   Cache saved: {len(stocks)} stocks → {self.cache_file}")

        except IOError as e:
            logger.error(f"⚠️ Cache save error: {e}")

    def _is_cache_stale(self) -> bool:
        """Check if cache is older than TTL days."""
        try:
            if not os.path.exists(self.cache_file):
                return True

            with open(self.cache_file, 'r') as f:
                data = json.load(f)

            timestamp_str = data.get('timestamp', '')
            if not timestamp_str:
                return True

            cache_time = datetime.fromisoformat(timestamp_str)
            age = datetime.now() - cache_time
            return age.total_seconds() > self.cache_ttl_days * 86400

        except Exception:
            return True

    def _get_cache_age_days(self) -> float:
        """Get cache age in days."""
        try:
            if not os.path.exists(self.cache_file):
                return 999

            with open(self.cache_file, 'r') as f:
                data = json.load(f)

            timestamp_str = data.get('timestamp', '')
            if not timestamp_str:
                return 999

            cache_time = datetime.fromisoformat(timestamp_str)
            age = datetime.now() - cache_time
            return age.total_seconds() / 86400

        except Exception:
            return 999

    # ───────────────────────────────────────────────────────────────────────
    # FALLBACK UNIVERSE
    # ───────────────────────────────────────────────────────────────────────

    def _build_fallback_universe(self) -> List[Dict]:
        """
        Build a minimal universe from the hardcoded NIFTY 100 proxy list.
        Used only when screener.in AND cache both fail.
        Market cap values are approximate (not real-time).
        """
        fallback = []
        for symbol in _FALLBACK_LARGE_CAPS:
            fallback.append({
                'symbol': symbol,
                'kite_symbol': symbol,
                'company_name': symbol,
                'market_cap_crore': 50000,  # Approximate — all > 25K threshold
                'sector': '',
                'is_fallback': True,  # Flag so downstream knows this is approximate
            })
        logger.warning(f"   Fallback universe: {len(fallback)} stocks (approximate market caps)")
        return fallback


# ═══════════════════════════════════════════════════════════════════════════════
# STANDALONE TEST
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(name)s] %(message)s')

    # Minimal config mock for testing
    class MockConfig:
        PH8_SCREENER_CACHE_FILE = 'data/screener_mcap_cache.json'
        PH8_SCREENER_CACHE_TTL_DAYS = 7
        PH8_MIN_MCAP_CRORE = 25000

    fetcher = ScreenerDataFetcher(MockConfig())
    universe = fetcher.get_mcap_universe()

    print(f"\n{'='*60}")
    print(f"Universe: {len(universe)} stocks with mcap ≥ ₹25,000 crore")
    print(f"{'='*60}")

    # Show top 10 by market cap
    sorted_by_mcap = sorted(universe, key=lambda x: x.get('market_cap_crore', 0), reverse=True)
    for i, stock in enumerate(sorted_by_mcap[:10], 1):
        mcap = stock.get('market_cap_crore', 0)
        print(f"  #{i:2d}  {stock['kite_symbol']:15s}  ₹{mcap:>12,.0f} cr  {stock.get('sector', '')}")
