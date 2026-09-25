"""
PHASE 5: INTRADAY ENTRY ENGINE v5.4.0 (Score Rebalance + Gap-First Philosophy)
═══════════════════════════════════════════════════════════════════════════════

🎯 PURPOSE:
   Capture gap-up/gap-down reversions in the first minutes of market open.
   This is a SEPARATE strategy from V-Recovery, completely independent.

🔄 v5.4.0 ARCHITECTURE: PRE-MARKET CACHE + BATCH QUOTE + 3-LOOP EXECUTE-FIRST
   ──────────────────────────────────────────────────────────────────────────────
   Phase 5 is a HARD REAL-TIME engine. Speed = money.
   
   KEY INSIGHT (v5.2.0):
   Daily indicators (ATR, RSI, ADX, avg_volume) use DAILY candles only.
   Fetching them DURING market hours includes today's partial candle → corrupted data.
   Pre-computing at 09:08-09:14 (pre-market) gives CLEANER indicators from 
   CLOSED candles only — the standard used by professional trading desks.
   
   PERFORMANCE:
   OLD (v5.1.0): 147 individual quote calls + 5-10 historical calls = ~25 seconds/loop
   NEW (v5.2.0): 1 batch quote call + cached indicators = ~1.5 seconds/loop
   
   DATA INTEGRITY:
   OLD: Today's partial candle corrupts ATR (shrinks), RSI (fake close), ADX (noise)
   NEW: Only closed daily candles used → statistically correct indicators

🔄 TIMELINE (v5.2.0):
   09:08-09:14 - PRE-MARKET PREP (called by orchestrator, runs ONCE):
                 1. Build instrument token map (kite.instruments, cached)
                 2. Batch kite.quote(147 stocks) → cache prev_close
                 3. Sequential kite.historical_data per stock → cache ATR, RSI, ADX, avg_vol
                 4. FinBERT sentiment check
                 5. Set cache validity stamp (date, time, stock_count)
   
   09:15       - Market opens
   09:18       - LOOP 1: Batch quote (0.5s) → gap calc → filter → score → EXECUTE
   ~09:20      - LOOP 2: Same ultrafast pipeline (if Loop 1 didn't fire)
   ~09:22      - LOOP 3: Same ultrafast pipeline (if Loop 2 didn't fire)
   09:22-09:50 - Phase 5 DONE
   
   FALLBACK: If pre-market prep missed (late boot), loops fall back to 
   inline fetching (v5.1.0 behavior) — slower but functional.

📊 STRATEGY LOGIC:
   Gap Down detected → BUY (expecting bounce/fill)
   Gap Up detected   → SELL (expecting fade/fill)
   
   Each loop: Scan → Filter → Score → EXECUTE → Handoff → async ChatGPT
   MAX 1 TRADE PER DAY — once ANY loop fires, Phase 5 is done.

📦 POSITION DATA PASSED TO PHASE 4:
   {
       'symbol': 'STOCK',
       'entry_price': 100.0,
       'quantity': 10,
       'direction': 'LONG' or 'SHORT',
       'product': 'MIS',
       'mandatory_exit_time': time(12, 0),
       'source': 'PHASE5_GAP',
       'gap_pct': 2.5,
       'volume_burst_score': 75,
       'sentiment': 'BULLISH',
       'chatgpt_approval': {...},
       'flight_plan': {...}
   }

🔧 PREVIOUS VERSIONS:
   - v5.1.0: 3-Loop Execute-First, async ChatGPT log
   - v5.0.0: Entry Engine + Phase 4 Handoff (single scan, ChatGPT blocks entry)
   - v4.9.1: Volume Burst Scoring, Detailed Logging
   - v4.9.0: Leverage-aware position sizing via Zerodha Margin API

Author: Dheebanraj
Version: 5.4.0
Date: 2026-03-06
"""

import logging
import time
import math
import json
import os
import threading
import pandas as pd
import numpy as np
from datetime import datetime, time as dt_time, timedelta
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass
from enum import Enum

# Import existing modules
try:
    from finbert_analyzer import FinBERTAnalyzer
except ImportError:
    FinBERTAnalyzer = None

try:
    from news_scraper import NewsScraper
except ImportError:
    NewsScraper = None

try:
    from kiteconnect import KiteConnect
except ImportError:
    KiteConnect = None

try:
    import talib as ta
except ImportError:
    ta = None

# v5.2.1: Import config for MASTER_STOCK_LIST (single source of truth)
try:
    from config import Config as _MainConfig
    _MASTER_STOCK_LIST = getattr(_MainConfig, 'MASTER_STOCK_LIST', [])
except ImportError:
    _MASTER_STOCK_LIST = []

logger = logging.getLogger('Phase5_IntradayEngine')


# ═══════════════════════════════════════════════════════════════════════════════
# ENUMS AND DATA CLASSES
# ═══════════════════════════════════════════════════════════════════════════════

class GapType(Enum):
    """Gap classification."""
    GAP_UP = "GAP_UP"
    GAP_DOWN = "GAP_DOWN"
    NO_GAP = "NO_GAP"


class GapTradeDirection(Enum):
    """Trade direction based on gap type."""
    BUY = "BUY"    # For gap down (expecting bounce)
    SELL = "SELL"  # For gap up (expecting fade)


class GapTradeStatus(Enum):
    """Trade lifecycle status."""
    PENDING = "PENDING"
    ENTERED = "ENTERED"
    HANDED_OFF = "HANDED_OFF"  # v5.0.0: New status after Phase 4 handoff
    REJECTED = "REJECTED"      # v5.0.0: ChatGPT rejected entry


@dataclass
class VolumeBurstScore:
    """
    Volume Burst Scoring System (v5.4.0)

    Two-factor scoring — gap-first philosophy:
    - Factor A: Opening Volume Ratio (0-20 points)  — halved from 40, volume unreliable at 09:17-09:20
    - Factor B: Price Range Intensity (0-30 points)  — unchanged

    Recovery REMOVED (v5.4.0): By the time recovery confirms, the move is done.
    Entry on gap quality, TCAS monitors position afterward.
    """
    volume_ratio_score: float = 0     # Factor A: 0-20 (was 0-40)
    range_intensity_score: float = 0   # Factor B: 0-30
    recovery_score: float = 0          # Factor C: DEPRECATED (always 0, kept for compatibility)
    total_score: float = 0             # 0-50 (was 0-100)

    # Raw values for logging
    volume_ratio: float = 0
    range_vs_atr: float = 0
    recovery_pct: float = 0            # Still calculated for logging, not scored

    def is_valid(self, min_score: float = 15) -> bool:
        """Check if volume burst is significant enough. Threshold halved from 50 to 15 for v5.4.0."""
        return self.total_score >= min_score


@dataclass
class GapCandidate:
    """Candidate stock for gap strategy."""
    symbol: str
    gap_type: GapType
    gap_pct: float
    prev_close: float
    open_price: float
    current_price: float
    atr: float
    volume_ratio: float  # Kept for compatibility
    rsi: float = 50.0
    adx: float = 25.0
    
    # v4.9.1: Volume Burst fields
    volume_burst: Optional[VolumeBurstScore] = None
    range_high: float = 0
    range_low: float = 0
    avg_volume_20d: float = 0

    # v6.0.0: Champion-vs-Champion fields
    excess_gap_pct: float = 0.0   # gap_pct − nifty_gap_pct  (stock-specific gap quality)
    iev: float = 0.0              # Indicative Equilibrium Volume from pre-open auction

    def get_direction(self) -> GapTradeDirection:
        """Get trade direction based on gap type."""
        if self.gap_type == GapType.GAP_DOWN:
            return GapTradeDirection.BUY
        else:
            return GapTradeDirection.SELL


@dataclass
class GapTrade:
    """Executed gap trade."""
    symbol: str
    direction: GapTradeDirection
    entry_price: float
    entry_time: datetime
    quantity: int
    target_price: float
    stop_price: float
    target_pct: float
    stop_pct: float
    gap_pct: float
    status: GapTradeStatus
    order_id: str = ""
    margin_used: float = 0
    effective_leverage: float = 1.0
    position_value: float = 0
    
    # v4.9.1: Volume Burst data
    volume_burst_score: float = 0
    
    # v5.0.0: Flight Plan and ChatGPT approval
    flight_plan: Dict = None
    chatgpt_approval: Dict = None
    
    # v5.1.0: Loop metadata
    loop_number: int = 0
    tier_used: str = ""
    
    # P0 FIX: ATR for Phase 4 handoff (TCAS/ILS calculations)
    atr: float = 0

    # PAPER MODE: logger ID from paper_trade_logger.py (carried through to Phase4)
    paper_logger_id: str = ""


class GapStrategyConfig:
    """Configuration for gap strategy."""
    # Gap thresholds (tiered approach)
    TIER_1_GAP_PCT = 1.5    # Loop 1: large gaps
    TIER_2_GAP_PCT = 1.0    # Loop 2: medium gaps
    TIER_3_GAP_PCT = 0.75   # Loop 3: small gaps
    
    # Target and Stop — v5.3.3: Smart TCAS Scalp Design
    # No hard target cap. TCAS activates at +0.3%, rides momentum,
    # Kalman detects deceleration → exit. Minimum profit ≈ 0.3% guaranteed.
    TCAS_ACTIVATION_PCT = 0.3     # TCAS engages after +0.3% profit
    STOP_ATR_MULTIPLIER = 1.2     # v5.7.0: Stop = 1.2× ATR — restored breathing room (was 0.5× which equalled proximity zone)
    
    # v5.3.3: Time-based safety layers
    HARD_EXIT_TIME = dt_time(9, 45)          # Absolute exit deadline
    MAX_HOLD_MINUTES = 25                     # 25 min max (09:20 → 09:45)
    
    # DEPRECATED — kept for backward compatibility / fallback only
    TARGET_PCT = 0.3        # Legacy: used only if ATR unavailable
    ATR_TARGET_MULTIPLIER = 0.25  # DEPRECATED — not called in v5.3.3+
    ATR_TARGET_MIN_PCT = 0.2      # DEPRECATED
    ATR_TARGET_MAX_PCT = 1.0      # DEPRECATED
    MIN_STOP_PCT = 0.3            # DEPRECATED
    MAX_STOP_PCT = 1.0            # DEPRECATED
    
    # Volume requirements (v4.9.1 - now handled by Volume Burst Score)
    MIN_VOLUME_RATIO = 1.2  # Fallback if Volume Burst unavailable
    MIN_VOLUME_BURST_SCORE = 15  # v5.4.0: Halved from 50 (VB now 0-50 scale)
    
    # Filters
    MIN_ADX = 20
    MAX_ADX = 50
    MIN_PRICE = 800     # v5.3.5: ₹800+ for meaningful gap movement
    MAX_PRICE = 3000    # v5.3.5: Expanded to include large-caps (ADANIENT, HINDUNILVR etc.)
    
    # v5.0.0: Config
    CHATGPT_MIN_CONFIDENCE = 0.6  # Minimum confidence for ChatGPT approval
    MAX_EXIT_TIME = dt_time(12, 0)  # Maximum hold until 12:00 PM
    
    # Position sizing
    MAX_POSITION_VALUE = 20000
    MAX_CAPITAL_PCT = 0.5  # Use max 50% of available capital
    
    # v5.1.0: 3-Loop config
    LOOP_WAIT_SECONDS = 90   # Wait between loops (gap momentum develops)
    FULL_SIZE_SCORE = 50     # v5.4.0: Score ≥50 → full position (was 75)
    HALF_SIZE_SCORE = 50     # v5.4.0: Unified minimum (was 75)
    # v5.5.1: Tier-adaptive thresholds — relax for smaller gaps (Tier 2/3)
    FULL_SIZE_SCORE_TIER1 = 50   # ≥1.5% gaps: strong setups, keep high bar
    FULL_SIZE_SCORE_TIER2 = 45   # ≥1.0% gaps: slightly relaxed
    FULL_SIZE_SCORE_TIER3 = 45   # ≥0.75% gaps: same as tier 2
    MAX_TRADES_PER_DAY = 1   # Max 1 trade per day for Phase 5

    # v6.0.0: Champion-vs-Champion thresholds
    V6_MIN_GAP_PCT         = 0.75   # Absolute minimum gap% to even enter the pool
    V6_MIN_EXCESS_GAP_PCT  = 0.0    # Min stock-vs-nifty excess (0 = stock must at least match nifty)
    V6_MIN_LIQUIDITY_VOL   = 50_000 # Min IEV (pre-open volume) for liquidity check

    # v5.8.0: Gap quality filters (fake-gap removal + absorption scoring)
    V6_MAX_GAP_PCT          = 3.0   # Reject extreme/news gaps > 3% (unpredictable, may continue)
    V6_REQUIRE_TRUE_GAP     = True  # open_price must be OUTSIDE prev day high/low (true structural gap)
    V6_ABSORPTION_IEV_RATIO = 3.0   # IEV > 3× avg_vol on moderate gap = absorption signal (+15 score)
    V6_LOW_CONVICTION_RATIO = 0.5   # IEV < 0.5× avg_vol = thin gap, no smart money (-10 score)

    # v5.8.0: 9:20 confirmation candle (failure verification before entry)
    V6_CONFIRM_AT_920       = True  # Wait for first 5-min candle; verify rejection + no new extreme
    V6_WICK_MIN_RATIO       = 0.35  # Wick must be ≥ 35% of candle range to confirm rejection

    # v5.9.0: Refinement parameters
    V6_INSIDE_RANGE_PENALTY    = 12    # Score penalty for inside-PDH/PDL opens (when V6_REQUIRE_TRUE_GAP=False)
    V6_ABSORPTION_RANGE_PCT    = 0.003 # 0.3%: first-candle range < this + IEV>=2x = true absorption signal
    V6_CANDLE_ABSORPTION_BONUS = 10    # Score bonus for true candle absorption detection

    # Paper Trading Mode
    PH5_PAPER_MODE = True               # True = paper (no real orders)
    PH5_PAPER_LOG_FILE = "data/ph5_paper_trades.json"


class Phase5IntradayEngine:
    """
    Phase 5: Intraday Entry Engine v5.4.0
    
    Pre-Market Cache + Batch Quote + 3-Loop Execute-First Architecture:
    
    PRE-MARKET (09:08-09:14, called by orchestrator):
    - Cache instrument tokens, prev_close, ATR, RSI, ADX, avg_volume for all stocks
    - Uses CLOSED daily candles only (no partial today candle contamination)
    
    MARKET OPEN (09:18-09:22):
    - LOOP 1 @ 09:18: 1 batch quote → gap calc → filter → score → EXECUTE (~1.5s)
    - LOOP 2 @ ~09:20: Same ultrafast pipeline (if Loop 1 didn't fire)
    - LOOP 3 @ ~09:22: Same ultrafast pipeline (if Loop 2 didn't fire)
    
    Max 1 trade per day. Once fired, Phase 5 is done.
    Fallback: If cache missed, loops use inline fetching (v5.1.0 behavior).
    """
    
    def __init__(
        self,
        kite: 'KiteConnect',
        config: GapStrategyConfig = None,
        finbert: 'FinBERTAnalyzer' = None,
        news_scraper: 'NewsScraper' = None,
        capital_manager = None,
        telegram = None,
        chatgpt_advisor = None,
        phase4_manager = None,
        stock_universe: List[str] = None
    ):
        """
        Initialize Phase 5 Intraday Engine.
        
        Args:
            kite: Zerodha KiteConnect instance
            config: Strategy configuration
            finbert: FinBERT analyzer for sentiment
            news_scraper: News scraper for FinBERT
            capital_manager: Capital Manager for position sizing
            telegram: Telegram notifier
            chatgpt_advisor: ChatGPT advisor for post-entry logging (v5.1.0)
            phase4_manager: Phase 4 Portfolio Manager for handoff (v5.0.0)
            stock_universe: List of stocks to scan
        """
        self.kite = kite
        self.config = config or GapStrategyConfig()
        self.finbert = finbert
        self.news_scraper = news_scraper
        self.capital_manager = capital_manager
        self.telegram = telegram
        self.chatgpt = chatgpt_advisor
        self.phase4 = phase4_manager
        self.stock_universe = stock_universe or list(_MASTER_STOCK_LIST)  # v5.2.1: from config.py
        
        # State
        self.enabled = True
        self.current_trade: Optional[GapTrade] = None
        self.market_sentiment = "NEUTRAL"
        self.daily_trade_count = 0
        self.last_scan_time = None
        
        # v5.1.0: Loop tracking
        self._trade_fired = False      # Once True, no more loops
        self._loops_completed = 0      # How many loops ran
        self._radar_candidates = []    # Runners-up from last scan
        
        # v5.4.0: PVAT trade tracking (separate from gap's _trade_fired)
        self._pvat_trade_fired = False  # Phase 5A gets its own trade slot

        # v5.2.0: Pre-market cache (populated by pre_market_prep())
        self._indicator_cache = {}     # {symbol: {atr, rsi, adx, avg_volume_20d, prev_close}}
        self._indicator_cache_meta = { # Cache validity stamp (avionics-grade)
            'as_of_date': None,        # Date cache was built
            'generated_at': None,      # Timestamp of generation
            'stock_count': 0,          # Number of stocks cached
            'complete': False          # True only if ALL stocks processed
        }
        self._instrument_map = {}      # {symbol: instrument_token} — cached ONCE
        self._instrument_map_loaded = False
        
        # v5.0.0: Orchestrator reference (set by orchestrator)
        self.orchestrator = None

        # v5.6.0: VIX-tiered parameters (set by orchestrator before each gap scan)
        self._vix_size_mult = 1.0   # 0.25–1.0 based on India VIX tier
        self._vix_stop_mult = 1.0   # 1.0–2.0 — wider stops in elevated VIX
        self._vix_tier_label = 'UNKNOWN'  # LOW / MODERATE / ELEVATED / HIGH / EXTREME
        
        logger.info("=" * 80)
        logger.info("PHASE 5: INTRADAY ENTRY ENGINE v5.4.0")
        logger.info("=" * 80)
        logger.info(f"Architecture: Pre-Market Cache + Batch Quote + 3-Loop Execute-First")
        logger.info(f"Pre-Market: 09:08-09:14 (cache ATR/RSI/ADX/avg_vol from closed candles)")
        logger.info(f"Gap Thresholds: {self.config.TIER_1_GAP_PCT}% / {self.config.TIER_2_GAP_PCT}% / {self.config.TIER_3_GAP_PCT}%")
        logger.info(f"Loop Wait: {self.config.LOOP_WAIT_SECONDS}s between loops")
        logger.info(f"Score Thresholds: Full ≥{self.config.FULL_SIZE_SCORE}, Half ≥{self.config.HALF_SIZE_SCORE}")
        logger.info(f"Target: Smart TCAS (activate at +{self.config.TCAS_ACTIVATION_PCT}%, ride momentum) | Stop: {self.config.STOP_ATR_MULTIPLIER}x ATR (raw)")
        logger.info(f"Max Exit Time: {self.config.MAX_EXIT_TIME}")
        logger.info(f"Max Trades/Day: {self.config.MAX_TRADES_PER_DAY}")

        # Paper trading mode
        self._paper_mode = bool(getattr(self.config, 'PH5_PAPER_MODE', False) or getattr(self.config, 'MASTER_PAPER_MODE', False))
        self._paper_trades: list = []
        if self._paper_mode:
            logger.info("📝 PAPER TRADING MODE — no real orders will be placed")

        logger.info("=" * 80)
    
    def set_orchestrator(self, orchestrator):
        """v5.0.0: Set orchestrator reference for Phase 4 handoff."""
        self.orchestrator = orchestrator
        logger.info("✅ Phase 5: Orchestrator reference set")

    def set_vix_tier_params(self, size_mult: float, stop_mult: float, tier_label: str = ''):
        """v5.6.0: Apply VIX-tiered position sizing and stop width before gap scan."""
        self._vix_size_mult = max(0.0, min(1.0, size_mult))
        self._vix_stop_mult = max(1.0, min(2.5, stop_mult))
        self._vix_tier_label = tier_label or ''
        logger.info(
            f"📊 PH5 VIX tier applied: {self._vix_tier_label} → "
            f"size={self._vix_size_mult:.2f}x  stop={self._vix_stop_mult:.2f}x"
        )

    def _reset_daily_state(self):
        """Reset all per-day trading state. Called once at start of each trading day."""
        self._trade_fired       = False
        self._pvat_trade_fired  = False
        self.daily_trade_count  = 0
        self.current_trade      = None
        self._paper_trades      = []
        logger.info("🔄 Phase 5 daily state reset")

    # ═══════════════════════════════════════════════════════════════════════════
    # v5.2.0: PRE-MARKET PREP — Called by orchestrator at 09:08-09:14
    # ═══════════════════════════════════════════════════════════════════════════

    def pre_market_prep(self):
        """
        v6.0.0: Pre-market cache — builds full indicator cache + IEV before market open.

        Timeline:
          09:00-09:08  orchestrator calls this method
          Step 1       Instrument token map (once per session)
          Step 2       Batch quote → prev_close for all stocks (1 API call)
          Step 3       Historical data → ATR, RSI, ADX, avg_volume_20d
                       (~3 req/sec rate limit, ~50s for 150 stocks)
          Step 4       Wait until 09:10, then batch quote for IEV
                       (indicative equilibrium volume from pre-open auction)
          Step 5       Pre-calculate vb_iev_score (Factor A proxy) per stock
                       Stored in cache → used by v6 champion scoring at 09:16

        Cache written to: self._indicator_cache[symbol] with keys:
          atr, rsi, adx, avg_volume_20d, prev_close, iev, vb_iev_score
        """
        start_time = time.time()

        logger.info("")
        logger.info("=" * 80)
        logger.info("🔧 PHASE 5 PRE-MARKET PREP v6.0.0")
        logger.info("=" * 80)
        logger.info(f"Time: {datetime.now().strftime('%H:%M:%S')}")
        logger.info(f"Stocks: {len(self.stock_universe)}")
        logger.info(f"Purpose: Cache ATR/RSI/ADX/IEV + pre-calc vb_iev_score")
        logger.info("")

        today = datetime.now().date()

        # Reset cache for new day
        self._indicator_cache = {}
        self._indicator_cache_meta = {
            'as_of_date': today,
            'generated_at': datetime.now(),
            'stock_count': 0,
            'complete': False
        }

        try:
            # ─────────────────────────────────────────────────────
            # STEP 1: Build instrument token map (once per session)
            # ─────────────────────────────────────────────────────
            if not self._instrument_map_loaded:
                logger.info("📋 Step 1: Building instrument token map...")
                try:
                    instruments = self.kite.instruments("NSE")
                    self._instrument_map = {
                        inst['tradingsymbol']: inst['instrument_token']
                        for inst in instruments
                        if inst['tradingsymbol'] in self.stock_universe
                    }
                    self._instrument_map_loaded = True
                    logger.info(f"   ✅ Mapped {len(self._instrument_map)}/{len(self.stock_universe)} stocks")
                except Exception as e:
                    logger.error(f"   ❌ Instrument map failed: {e}")
            else:
                logger.info("📋 Step 1: Instrument token map already loaded ✅")

            # ─────────────────────────────────────────────────────
            # STEP 2: Batch quote for prev_close (1 API call)
            # ─────────────────────────────────────────────────────
            logger.info("📊 Step 2: Batch quote for prev_close...")
            prev_close_map = {}
            try:
                symbols_nse = [f"NSE:{s}" for s in self.stock_universe]
                all_quotes = self.kite.quote(symbols_nse)
                for sym_key, qd in all_quotes.items():
                    symbol = sym_key.replace("NSE:", "")
                    pc = qd.get('ohlc', {}).get('close', 0)
                    if pc > 0:
                        prev_close_map[symbol] = pc
                logger.info(f"   ✅ Got prev_close for {len(prev_close_map)} stocks (1 batch call)")
            except Exception as e:
                logger.error(f"   ❌ Batch prev_close failed: {e}")

            # ─────────────────────────────────────────────────────
            # STEP 3: Historical data → ATR, RSI, ADX, avg_volume
            # Rate limit: ~3 req/sec → ~50s for 150 stocks
            # ─────────────────────────────────────────────────────
            logger.info(f"📈 Step 3: Historical data for {len(self.stock_universe)} stocks...")
            logger.info(f"   Rate limit: ~3 req/sec → est. {len(self.stock_universe) / 3:.0f}s")

            cached_count = 0
            errors = 0
            rate_limit_delay = 0.35  # ~3 req/sec with margin

            for i, symbol in enumerate(self.stock_universe):
                try:
                    token = self._instrument_map.get(symbol)
                    if not token:
                        errors += 1
                        continue

                    to_date = datetime.now()
                    from_date = to_date - timedelta(days=40)

                    data = self.kite.historical_data(
                        instrument_token=token,
                        from_date=from_date,
                        to_date=to_date,
                        interval="day"
                    )

                    if not data or len(data) < 20:
                        errors += 1
                        continue

                    df = pd.DataFrame(data)
                    atr          = self._calculate_atr(df)
                    rsi          = self._calculate_rsi(df)
                    adx          = self._calculate_adx(df)
                    avg_volume   = df['volume'].rolling(20).mean().iloc[-1]
                    prev_close   = prev_close_map.get(symbol, df['close'].iloc[-1])
                    # v5.8.0: prev day high/low for fake-gap detection
                    prev_high    = float(df['high'].iloc[-1])
                    prev_low     = float(df['low'].iloc[-1])

                    self._indicator_cache[symbol] = {
                        'atr':            atr,
                        'rsi':            rsi,
                        'adx':            adx,
                        'avg_volume_20d': avg_volume,
                        'prev_close':     prev_close,
                        'prev_high':      prev_high,   # v5.8.0: PDH for fake-gap filter
                        'prev_low':       prev_low,    # v5.8.0: PDL for fake-gap filter
                        'iev':            0.0,    # filled in Step 4
                        'vb_iev_score':   0.0,    # filled in Step 5
                    }
                    cached_count += 1

                    if (i + 1) % 25 == 0:
                        logger.info(f"   ... {i+1}/{len(self.stock_universe)} processed "
                                    f"({cached_count} cached, {errors} errors)")

                    time.sleep(rate_limit_delay)

                except Exception as e:
                    errors += 1
                    logger.debug(f"   Error caching {symbol}: {e}")

            logger.info(f"   ✅ Historical cache: {cached_count} stocks, {errors} errors")

            # ─────────────────────────────────────────────────────────
            # STEP 4: Wait until 09:10, then batch IEV quote
            # IEV = indicative equilibrium volume from NSE pre-open auction
            # Available via kite.quote() 'volume' field during 09:00-09:15
            # ─────────────────────────────────────────────────────────
            now = datetime.now()
            iev_target = now.replace(hour=9, minute=10, second=0, microsecond=0)
            wait_secs = (iev_target - now).total_seconds()
            if wait_secs > 0:
                logger.info(f"⏳ Step 4: Waiting {wait_secs:.0f}s until 09:10 for IEV batch quote...")
                time.sleep(wait_secs)
            else:
                logger.info("📡 Step 4: IEV batch quote (already past 09:10)...")

            iev_map = {}
            try:
                symbols_nse = [f"NSE:{s}" for s in self.stock_universe]
                # Include Nifty 50 index for nifty_iev (used in v6 scoring context)
                symbols_nse_with_nifty = symbols_nse + ["NSE:NIFTY 50"]
                iev_quotes = self.kite.quote(symbols_nse_with_nifty)
                for sym_key, qd in iev_quotes.items():
                    symbol = sym_key.replace("NSE:", "")
                    iev = qd.get('volume', 0)   # pre-open auction indicative volume
                    if iev and iev > 0:
                        iev_map[symbol] = float(iev)
                logger.info(f"   ✅ Got IEV for {len(iev_map)} symbols (1 batch call)")
            except Exception as e:
                logger.error(f"   ❌ IEV batch quote failed: {e}")

            # Write IEV into cache
            for symbol, cache in self._indicator_cache.items():
                cache['iev'] = iev_map.get(symbol, 0.0)

            # ─────────────────────────────────────────────────────────
            # STEP 5: Pre-calculate vb_iev_score (Factor A proxy from IEV)
            # Formula mirrors _calculate_volume_burst_score Factor A,
            # but uses iev / avg_volume_20d as the ratio
            # (IEV is a ~15-min pre-open session, not a full day —
            #  multiply by 26 to normalise to a full 6.5-hr session)
            # ─────────────────────────────────────────────────────────
            logger.info("🔢 Step 5: Pre-calculating vb_iev_score per stock...")
            scored = 0
            IEV_DAY_NORMALISER = 26.0  # 6.5hr / 15min ≈ 26 equivalent periods

            for symbol, cache in self._indicator_cache.items():
                iev       = cache.get('iev', 0.0)
                avg_vol   = cache.get('avg_volume_20d', 0.0)
                if avg_vol > 0 and iev > 0:
                    # Normalised ratio: how much of a full day's avg volume
                    # is implied by this pre-open IEV reading
                    iev_ratio = (iev * IEV_DAY_NORMALISER) / avg_vol
                    # Factor A scoring table (mirrors _calculate_volume_burst_score)
                    if iev_ratio >= 3.0:
                        score = 20
                    elif iev_ratio >= 2.5:
                        score = 18
                    elif iev_ratio >= 2.0:
                        score = 15
                    elif iev_ratio >= 1.5:
                        score = 10
                    elif iev_ratio >= 1.2:
                        score = 5
                    else:
                        score = 0
                    cache['vb_iev_score'] = float(score)
                    scored += 1

            logger.info(f"   ✅ vb_iev_score pre-calculated for {scored} stocks")

            # ─────────────────────────────────────────────────────────
            # FINALIZE
            # ─────────────────────────────────────────────────────────
            self._indicator_cache_meta = {
                'as_of_date':    today,
                'generated_at':  datetime.now(),
                'stock_count':   cached_count,
                'complete':      cached_count > 0,
            }

            elapsed = time.time() - start_time

            logger.info("")
            logger.info("┌" + "─" * 58 + "┐")
            logger.info(f"│{'PRE-MARKET PREP v6.0.0 COMPLETE':^58}│")
            logger.info("├" + "─" * 58 + "┤")
            logger.info(f"│ Cached:    {cached_count:>4}/{len(self.stock_universe)} stocks{'':17}│")
            logger.info(f"│ Errors:    {errors:>4}{'':37}│")
            logger.info(f"│ IEV:       {len(iev_map):>4} symbols{'':33}│")
            logger.info(f"│ IEV scored:{scored:>4} stocks{'':33}│")
            logger.info(f"│ Time:      {elapsed:.1f}s{'':39}│")
            logger.info(f"│ Cache:     {'✅ VALID' if self._indicator_cache_meta['complete'] else '❌ INCOMPLETE'}{'':32}│")
            logger.info("└" + "─" * 58 + "┘")
            logger.info("")
            logger.info("✅ Ready for 09:15:30 open-price quote + v6 champion scoring at 09:16")
            logger.info("")

            if self.telegram:
                self.telegram.send_message(
                    f"🔧 PHASE 5 PRE-MARKET PREP v6.0.0\n\n"
                    f"Cached: {cached_count}/{len(self.stock_universe)} stocks\n"
                    f"IEV: {len(iev_map)} symbols\n"
                    f"IEV scored: {scored} stocks\n"
                    f"Time: {elapsed:.1f}s\n"
                    f"Cache: {'OK' if self._indicator_cache_meta['complete'] else 'INCOMPLETE'}\n\n"
                    f"Ready for 09:16 v6 champion scan"
                )

        except Exception as e:
            logger.error(f"❌ Pre-market prep v6 failed: {e}")
            logger.exception(e)
            self._indicator_cache_meta['complete'] = False

    def _is_cache_valid(self) -> bool:
        """v5.3.3: Always returns True — batch quote mode is always available.
        Cache for prev_close/indicators is optional enhancement, not a gate.
        """
        return True

    # ═══════════════════════════════════════════════════════════════════════════
    # MAIN ENTRY POINT — 3-LOOP EXECUTE-FIRST (v5.1.0)
    # ═══════════════════════════════════════════════════════════════════════════
    
    def run_gap_strategy(self) -> Optional[GapTrade]:
        """
        v5.1.0: Execute 3-loop progressive gap scan with execute-first architecture.
        
        This method is BLOCKING — orchestrator waits until Phase 5 returns.
        
        Flow:
        ─────
        1. Sentiment check (once, cached)
        2. Loop 1 @ 09:18: Tier 1 (≥1.5%) → if score ≥ threshold → EXECUTE → done
        3. Wait 90s
        4. Loop 2 @ ~09:20: Tier 2 (≥1.0%) → if score ≥ threshold → EXECUTE → done
        5. Wait 90s
        6. Loop 3 @ ~09:22: Tier 3 (≥0.75%) → if score ≥ threshold → EXECUTE → done
        7. No trade → Phase 5 done for today
        
        Returns:
            GapTrade if position entered and handed off, None otherwise
        """
        if not self.enabled:
            logger.info("Phase 5 is disabled")
            return None
        
        now = datetime.now()
        current_time = now.time()
        
        # v5.1.0: Reset daily state at start of new day
        if not hasattr(self, '_last_reset_date') or self._last_reset_date != now.date():
            self._reset_daily_state()
            self._last_reset_date = now.date()
        
        # Already traded today — Phase 5 done
        if self._trade_fired or self.daily_trade_count >= self.config.MAX_TRADES_PER_DAY:
            logger.info("✅ Phase 5 already fired today — done")
            return self.current_trade
        
        # Time window check: 09:15 - 09:50 (widened from 09:25 in v5.0.0)
        if not (dt_time(9, 15) <= current_time <= dt_time(9, 50)):
            logger.info(f"⏰ Outside Phase 5 window (09:15-09:50). Current: {current_time}")
            return None
        
        logger.info("")
        logger.info("=" * 80)
        logger.info("🚀 PHASE 5: 3-LOOP EXECUTE-FIRST GAP STRATEGY v5.4.0")
        logger.info("=" * 80)
        logger.info(f"Time: {now.strftime('%H:%M:%S')}")
        logger.info(f"Stocks: {len(self.stock_universe)}")
        logger.info(f"Loops: 3 (Tier 1 → Tier 2 → Tier 3)")
        logger.info(f"Wait: {self.config.LOOP_WAIT_SECONDS}s between loops")
        logger.info(f"Execute-First: YES (ChatGPT post-entry async)")
        
        # v5.2.0: Cache status
        # v5.3.3: Always uses batch quote mode (1 API call for all stocks)
        logger.info(f"📦 Mode: ⚡ BATCH QUOTE (1 API call for {len(self.stock_universe)} stocks)")
        logger.info("")
        
        try:
            # ═══════════════════════════════════════════════════════════════
            # STEP 0: SENTIMENT CHECK (skip if already done in pre-market prep)
            # ═══════════════════════════════════════════════════════════════
            if self.market_sentiment == "NEUTRAL" and not self.last_scan_time:
                logger.info("📰 Running FinBERT sentiment check...")
                self.market_sentiment = self._get_market_sentiment()
                logger.info(f"📰 Market Sentiment: {self.market_sentiment}")
                logger.info("")
            
            # ═══════════════════════════════════════════════════════════════
            # WAIT UNTIL 09:17:00 (opening auction settled, first tick available)
            # v5.3.5: Moved from 09:15:30 → 09:17:00 (105s for auction settlement)
            # At 09:15:30 many stocks still have open=0, losing ~40 stocks silently
            # ═══════════════════════════════════════════════════════════════
            now = datetime.now()
            target_start = now.replace(hour=9, minute=17, second=0, microsecond=0)
            
            if now < target_start:
                wait_secs = (target_start - now).total_seconds()
                if wait_secs > 0:
                    logger.info(f"⏳ Waiting {wait_secs:.0f}s until 09:17:00 (opening auction settled)...")
                    time.sleep(wait_secs)
            
            # ═══════════════════════════════════════════════════════════════
            # 3-LOOP PROGRESSIVE SCAN
            # ═══════════════════════════════════════════════════════════════
            
            loop_config = [
                {
                    'loop_num': 1,
                    'tier': 'TIER_1',
                    'min_gap_pct': self.config.TIER_1_GAP_PCT,
                    'label': f'Tier 1 (≥{self.config.TIER_1_GAP_PCT}%)'
                },
                {
                    'loop_num': 2,
                    'tier': 'TIER_2',
                    'min_gap_pct': self.config.TIER_2_GAP_PCT,
                    'label': f'Tier 2 (≥{self.config.TIER_2_GAP_PCT}%)'
                },
                {
                    'loop_num': 3,
                    'tier': 'TIER_3',
                    'min_gap_pct': self.config.TIER_3_GAP_PCT,
                    'label': f'Tier 3 (≥{self.config.TIER_3_GAP_PCT}%)'
                },
            ]
            
            for loop in loop_config:
                loop_num = loop['loop_num']
                
                # Check if we already fired
                if self._trade_fired:
                    break
                
                # Check time — don't start a new loop after 09:50
                if datetime.now().time() > dt_time(9, 50):
                    logger.info("⏰ Past 09:50 — stopping loops")
                    break
                
                logger.info("")
                logger.info("─" * 80)
                logger.info(f"🔄 LOOP {loop_num}/3: {loop['label']}")
                logger.info(f"   Time: {datetime.now().strftime('%H:%M:%S')}")
                logger.info("─" * 80)
                
                # Run the scan-filter-score-execute pipeline for this tier
                trade = self._run_scan_loop(
                    loop_num=loop_num,
                    tier=loop['tier'],
                    min_gap_pct=loop['min_gap_pct']
                )
                
                if trade:
                    # TRADE FIRED — Phase 5 done!
                    self._trade_fired = True
                    self.current_trade = trade
                    self.daily_trade_count += 1
                    self._loops_completed = loop_num
                    
                    logger.info("")
                    logger.info("=" * 80)
                    logger.info(f"✅ PHASE 5 COMPLETE — Trade fired on Loop {loop_num}")
                    logger.info(f"   {trade.symbol} {trade.direction.value} @ ₹{trade.entry_price:.2f}")
                    logger.info(f"   Status: {trade.status.value}")
                    logger.info("=" * 80)
                    
                    return trade
                
                # No trade this loop — wait before next loop
                if loop_num < 3:
                    logger.info(f"   ℹ️ Loop {loop_num} — no trade. Waiting {self.config.LOOP_WAIT_SECONDS}s...")
                    time.sleep(self.config.LOOP_WAIT_SECONDS)
            
            # ═══════════════════════════════════════════════════════════════
            # ALL 3 LOOPS DONE — NO TRADE TODAY
            # ═══════════════════════════════════════════════════════════════
            logger.info("")
            logger.info("=" * 80)
            logger.info("ℹ️ PHASE 5 COMPLETE — No trade today after 3 loops")
            logger.info("=" * 80)
            
            if self.telegram:
                radar_text = ""
                if self._radar_candidates:
                    radar_text = "\n\n📡 RADAR (near-miss):\n"
                    for rc in self._radar_candidates[:3]:
                        radar_text += f"  • {rc.symbol}: gap {rc.gap_pct:+.2f}%, VB {rc.volume_burst.total_score:.0f}/50\n" if rc.volume_burst else f"  • {rc.symbol}: gap {rc.gap_pct:+.2f}%\n"
                
                self.telegram.send_message(
                    f"ℹ️ PHASE 5 SCAN COMPLETE\n\n"
                    f"3 loops completed — no trade.\n"
                    f"Thresholds: {self.config.TIER_1_GAP_PCT}%/{self.config.TIER_2_GAP_PCT}%/{self.config.TIER_3_GAP_PCT}%\n"
                    f"Sentiment: {self.market_sentiment}"
                    f"{radar_text}"
                )
            
            return None
            
        except Exception as e:
            logger.error(f"Gap strategy error: {e}")
            logger.exception(e)
            self._notify_error(str(e))
            return None

    # ═══════════════════════════════════════════════════════════════════════════
    # v6.0.0: CHAMPION-VS-CHAMPION GAP STRATEGY (single execution @ 09:16)
    # ═══════════════════════════════════════════════════════════════════════════

    def run_gap_strategy_v6(self) -> Optional[GapTrade]:
        """
        v6.0.0: Champion-vs-Champion single execution at 09:16.

        Architecture:
          Pre-market  IEV cached at 09:10 in pre_market_prep()
          09:15:30    Batch quote → confirmed open prices for ALL stocks + Nifty
          09:16:00    Score both pools, pick winning champion, EXECUTE ONCE

        Champion selection:
          1. Build gap-up pool (gap_pct > 0) and gap-down pool (gap_pct < 0)
          2. Each pool sorted by |excess_gap_pct| DESC   (excess = stock_gap - nifty_gap)
          3. Gap-up champion vs gap-down champion
          4. Side with higher |excess_gap_pct| wins (tiebreak: higher |gap_pct|)
          5. Single execute — Phase 5 done for today

        Returns:
            GapTrade if position entered and handed off, None otherwise
        """
        if not self.enabled:
            logger.info("Phase 5 is disabled")
            return None

        now = datetime.now()

        # Reset daily state once per day
        if not hasattr(self, '_last_reset_date') or self._last_reset_date != now.date():
            self._reset_daily_state()
            self._last_reset_date = now.date()

        if self._trade_fired or self.daily_trade_count >= self.config.MAX_TRADES_PER_DAY:
            logger.info("Phase 5 v6: already fired today")
            return self.current_trade

        # Time gate: 09:15 – 09:25 (v6 must finish well before 09:30)
        current_time = now.time()
        if not (dt_time(9, 15) <= current_time <= dt_time(9, 25)):
            logger.info(f"Outside Phase 5 v6 window (09:15-09:25). Current: {current_time}")
            return None

        logger.info("")
        logger.info("=" * 80)
        logger.info("🏆 PHASE 5 v6.0.0: CHAMPION-VS-CHAMPION GAP STRATEGY")
        logger.info("=" * 80)
        logger.info(f"Time: {now.strftime('%H:%M:%S')}")
        logger.info(f"Stocks: {len(self.stock_universe)}")
        logger.info(f"Logic: Gap-up champion vs Gap-down champion → single execute @ 09:16")
        logger.info("")

        try:
            # ─────────────────────────────────────────────────────────────
            # STEP 1: Wait until 09:15:30 for confirmed open prices
            # ─────────────────────────────────────────────────────────────
            now = datetime.now()
            open_target = now.replace(hour=9, minute=15, second=30, microsecond=0)
            wait_secs = (open_target - now).total_seconds()
            if wait_secs > 0:
                logger.info(f"⏳ Waiting {wait_secs:.1f}s until 09:15:30 for confirmed open prices...")
                time.sleep(wait_secs)
            logger.info(f"📡 09:15:30 reached — fetching open prices")

            # ─────────────────────────────────────────────────────────────
            # STEP 2: Single batch quote — all stocks + Nifty 50
            # ─────────────────────────────────────────────────────────────
            symbols_nse = [f"NSE:{s}" for s in self.stock_universe]
            symbols_nse_with_nifty = symbols_nse + ["NSE:NIFTY 50"]

            try:
                batch_quotes = self.kite.quote(symbols_nse_with_nifty)
                logger.info(f"✅ Batch quote: {len(batch_quotes)} symbols received")
            except Exception as e:
                logger.error(f"❌ Batch quote failed: {e}")
                return None

            # ─────────────────────────────────────────────────────────────
            # STEP 3: Nifty gap % (benchmark for excess calculation)
            # ─────────────────────────────────────────────────────────────
            nifty_gap_pct = self._get_nifty_gap_pct(batch_quotes)
            logger.info(f"📊 Nifty gap: {nifty_gap_pct:+.3f}%")

            # ─────────────────────────────────────────────────────────────
            # STEP 4: Build candidates from batch quote + indicator cache
            # ─────────────────────────────────────────────────────────────
            gap_up_pool:   list = []
            gap_down_pool: list = []
            skipped = 0

            for symbol in self.stock_universe:
                key = f"NSE:{symbol}"
                qd  = batch_quotes.get(key)
                if not qd:
                    skipped += 1
                    continue

                candidate = self._build_v6_candidate(symbol, qd, nifty_gap_pct)
                if candidate is None:
                    skipped += 1
                    continue

                if candidate.gap_type == GapType.GAP_UP:
                    gap_up_pool.append(candidate)
                else:
                    gap_down_pool.append(candidate)

            logger.info(f"   Gap-up pool:   {len(gap_up_pool)} stocks")
            logger.info(f"   Gap-down pool: {len(gap_down_pool)} stocks")
            logger.info(f"   Skipped:       {skipped} (no quote / no cache / filtered)")

            if not gap_up_pool and not gap_down_pool:
                logger.info("❌ Both pools empty — no trade today")
                return None

            # ─────────────────────────────────────────────────────────────
            # STEP 5: Find champion of each pool
            # Sort by |excess_gap_pct| DESC, tiebreak by |gap_pct| DESC
            # ─────────────────────────────────────────────────────────────
            def pool_champion(pool):
                if not pool:
                    return None
                return sorted(
                    pool,
                    key=lambda c: (abs(c.excess_gap_pct), abs(c.gap_pct)),
                    reverse=True
                )[0]

            up_champ   = pool_champion(gap_up_pool)
            down_champ = pool_champion(gap_down_pool)

            self._log_v6_champion_comparison(up_champ, down_champ, nifty_gap_pct)

            # ─────────────────────────────────────────────────────────────
            # STEP 6: Pick the winning champion (higher |excess_gap_pct|)
            # ─────────────────────────────────────────────────────────────
            winner = None
            if up_champ and down_champ:
                if abs(up_champ.excess_gap_pct) >= abs(down_champ.excess_gap_pct):
                    winner = up_champ
                    logger.info(f"🏆 Gap-UP wins: {up_champ.symbol} "
                                f"excess={up_champ.excess_gap_pct:+.3f}% vs "
                                f"gap-down {down_champ.symbol} excess={down_champ.excess_gap_pct:+.3f}%")
                else:
                    winner = down_champ
                    logger.info(f"🏆 Gap-DOWN wins: {down_champ.symbol} "
                                f"excess={down_champ.excess_gap_pct:+.3f}% vs "
                                f"gap-up {up_champ.symbol} excess={up_champ.excess_gap_pct:+.3f}%")
            elif up_champ:
                winner = up_champ
                logger.info(f"🏆 Gap-UP only: {up_champ.symbol} (no gap-down pool)")
            elif down_champ:
                winner = down_champ
                logger.info(f"🏆 Gap-DOWN only: {down_champ.symbol} (no gap-up pool)")

            if winner is None:
                logger.info("❌ No champion — no trade today")
                return None

            # ─────────────────────────────────────────────────────────────
            # STEP 7: v5.8.0 — Confirmation candle (09:15–09:20)
            #
            # If V6_CONFIRM_AT_920 is enabled:
            #   - Wait until 09:20:00 (first 5-min candle completes)
            #   - Fetch 1-min candles 09:15–09:20 and build composite candle
            #   - Check 1: Wick rejection ratio ≥ V6_WICK_MIN_RATIO (0.35)
            #       GAP_DOWN (LONG): lower_wick / total_range ≥ 0.35 → buyers pushed back up
            #       GAP_UP  (SHORT): upper_wick / total_range ≥ 0.35 → sellers pushed back down
            #   - Check 2: No new extreme — gap must not be continuing
            #       GAP_DOWN (LONG): 5-min LOW must be ≥ open_price (no new lows formed)
            #       GAP_UP  (SHORT): 5-min HIGH must be ≤ open_price (no new highs formed)
            #   - If either check fails → skip trade (gap may be continuing, not fading)
            #
            # If disabled → fall through to immediate execute at 09:16 (legacy behaviour)
            # ─────────────────────────────────────────────────────────────
            confirm_enabled = getattr(self.config, 'V6_CONFIRM_AT_920', True)
            wick_min_ratio  = getattr(self.config, 'V6_WICK_MIN_RATIO', 0.35)

            if confirm_enabled:
                # v5.9.0: Wait until 09:20:02.
                # +2s buffer: Zerodha historical_data can lag 1-2s after candle close.
                # Firing at exactly 09:20:00 frequently returns only 4 bars or an
                # incomplete 5th bar, making wick logic calculate on stale data.
                now = datetime.now()
                gate_time = now.replace(hour=9, minute=20, second=2, microsecond=0)
                wait_confirm = (gate_time - now).total_seconds()
                if wait_confirm > 0:
                    logger.info(f"⏳ v6 hard gate: {wait_confirm:.1f}s until 09:20:02 "
                                f"({winner.symbol} {winner.gap_type.value})...")
                    time.sleep(wait_confirm)

                # Hard cutoff — if we're already past 09:22, window too late
                if datetime.now().time() > dt_time(9, 22, 0):
                    logger.warning("⏰ Past 09:22:00 — confirmation window closed, aborting v6")
                    return None

                # Fetch 1-min candles for the confirmation window
                confirmed = False
                skip_reason = "no 1-min data"
                try:
                    token = self._instrument_map.get(winner.symbol)
                    if token:
                        today = datetime.now().date()
                        candle_from = datetime.combine(today, dt_time(9, 14, 0))
                        candle_to   = datetime.combine(today, dt_time(9, 20, 0))
                        candles_1m  = self.kite.historical_data(
                            instrument_token=token,
                            from_date=candle_from,
                            to_date=candle_to,
                            interval="minute"
                        )
                        if candles_1m and len(candles_1m) >= 3:
                            # Build composite 5-min candle from available 1-min bars
                            highs  = [c['high']  for c in candles_1m]
                            lows   = [c['low']   for c in candles_1m]
                            c_open = candles_1m[0]['open']
                            c_high = max(highs)
                            c_low  = min(lows)
                            c_close= candles_1m[-1]['close']
                            total_range = c_high - c_low

                            if total_range > 0:
                                open_price = winner.open_price

                                # v5.9.0: "failed acceptance" logic — price CAN make a new extreme,
                                # but must CLOSE on the rejection side of the candle midpoint.
                                # Replaces binary "no new extreme" check (which wrongly rejected
                                # the strongest reversal setups: spike → hard rejection → fill).
                                midpoint = (c_high + c_low) / 2.0

                                # v5.9.0 CHANGE 3: First-candle absorption
                                # True absorption = high volume + SMALL price range.
                                # range_pct < V6_ABSORPTION_RANGE_PCT (0.3%) AND iev_ratio >= 2x
                                # = institutions absorbing without letting price move.
                                range_pct   = total_range / c_open if c_open else 0
                                abs_rng_thr = getattr(self.config, 'V6_ABSORPTION_RANGE_PCT', 0.003)
                                _vb_ratio   = winner.volume_burst.volume_ratio if winner.volume_burst else 0
                                _candle_abs_bonus = 0
                                if _vb_ratio >= 2.0 and range_pct < abs_rng_thr:
                                    _candle_abs_bonus = getattr(self.config, 'V6_CANDLE_ABSORPTION_BONUS', 10)
                                    logger.info(
                                        f"🟢 CANDLE ABSORPTION {winner.symbol}: "
                                        f"range_pct={range_pct*100:.3f}% < {abs_rng_thr*100:.2f}% "
                                        f"IEV={_vb_ratio:.1f}× → +{_candle_abs_bonus} score"
                                    )
                                    if winner.volume_burst:
                                        winner.volume_burst.total_score = min(
                                            50, winner.volume_burst.total_score + _candle_abs_bonus)

                                if winner.gap_type == GapType.GAP_DOWN:
                                    # LONG: sellers drove to new low BUT buyers took over
                                    # Signal: candle closes above midpoint
                                    lower_wick      = min(c_open, c_close) - c_low
                                    wick_ratio      = lower_wick / total_range
                                    close_above_mid = c_close > midpoint
                                    confirmed       = wick_ratio >= wick_min_ratio and close_above_mid
                                else:
                                    # SHORT: buyers drove to new high BUT sellers took over
                                    # Signal: candle closes below midpoint
                                    upper_wick      = c_high - max(c_open, c_close)
                                    wick_ratio      = upper_wick / total_range
                                    close_below_mid = c_close < midpoint
                                    confirmed       = wick_ratio >= wick_min_ratio and close_below_mid

                                # v5.9.0 CHANGE 4: Graded wick-strength bonus
                                # Strong rejection (>= 0.50) = large institutional rejection wick
                                # Moderate (>= wick_min_ratio) = minimum acceptable rejection
                                if confirmed:
                                    if wick_ratio >= 0.50:
                                        _wick_bonus = 20
                                        _wick_tier  = 'STRONG'
                                    else:
                                        _wick_bonus = 10
                                        _wick_tier  = 'MODERATE'
                                    if winner.volume_burst:
                                        winner.volume_burst.total_score = min(
                                            50, winner.volume_burst.total_score + _wick_bonus)
                                else:
                                    _wick_tier  = 'WEAK'
                                    _wick_bonus = 0

                                skip_reason = (
                                    f"wick={wick_ratio:.2f} [{_wick_tier}] (need≥{wick_min_ratio}) "
                                    f"mid_test={'✅' if confirmed else '❌'} "
                                    f"range={range_pct*100:.3f}% abs_bonus={_candle_abs_bonus}"
                                )

                                logger.info(
                                    f"📊 CONFIRM CANDLE {winner.symbol} ({winner.gap_type.value}): "
                                    f"O={c_open:.2f} H={c_high:.2f} L={c_low:.2f} C={c_close:.2f} "
                                    f"| {skip_reason} → {'✅ CONFIRMED' if confirmed else '❌ REJECTED'}"
                                )
                            else:
                                skip_reason = "zero-range candle (no trading yet)"
                                logger.warning(f"⚠️ {winner.symbol}: {skip_reason}")
                        else:
                            skip_reason = f"insufficient 1-min bars ({len(candles_1m) if candles_1m else 0})"
                            logger.warning(f"⚠️ {winner.symbol}: {skip_reason}")
                    else:
                        skip_reason = "instrument token not found"
                        logger.warning(f"⚠️ {winner.symbol}: {skip_reason}")

                except Exception as e:
                    skip_reason = f"candle fetch error: {e}"
                    logger.warning(f"⚠️ {winner.symbol}: confirmation candle failed — {e}")

                if not confirmed:
                    logger.info(f"🚫 v6 TRADE SKIPPED — confirmation not met: {skip_reason}")
                    if self.telegram:
                        try:
                            self.telegram.send_message(
                                f"🚫 v6 GAP TRADE SKIPPED\n\n"
                                f"Stock: {winner.symbol}\n"
                                f"Gap: {winner.gap_pct:+.2f}%  Excess: {winner.excess_gap_pct:+.2f}%\n"
                                f"Reason: 09:20 candle did not confirm failure\n"
                                f"{skip_reason}"
                            )
                        except Exception:
                            pass
                    return None

            else:
                # Legacy behaviour: wait until 09:16:00 and execute immediately
                now = datetime.now()
                execute_target = now.replace(hour=9, minute=16, second=0, microsecond=0)
                wait_exec = (execute_target - now).total_seconds()
                if wait_exec > 0:
                    logger.info(f"⏳ Waiting {wait_exec:.1f}s until 09:16:00 to execute...")
                    time.sleep(wait_exec)

                if datetime.now().time() > dt_time(9, 17, 0):
                    logger.warning("⏰ Past 09:17:00 — v6 execution window closed, aborting")
                    return None

            logger.info("")
            logger.info(f"🔥 EXECUTING: {winner.symbol} {winner.get_direction().value}")
            logger.info(f"   Gap: {winner.gap_pct:+.3f}%  Excess: {winner.excess_gap_pct:+.3f}%  IEV: {winner.iev:,.0f}")
            logger.info("")

            # Composite score for sizing + approval dict
            candidate_score = self._calculate_composite_score(winner)
            size_factor = 1.0 if candidate_score >= self.config.FULL_SIZE_SCORE else 0.5

            flight_plan  = self._generate_entry_flight_plan(winner)
            sizing_result = self._calculate_position_size_with_leverage(winner)

            if sizing_result['quantity'] <= 0:
                logger.warning("❌ Position sizing failed — insufficient capital")
                return None

            if size_factor < 1.0:
                original_qty = sizing_result['quantity']
                sizing_result['quantity'] = max(1, int(sizing_result['quantity'] * size_factor))
                logger.info(f"   📐 Half-size: {original_qty} → {sizing_result['quantity']}")

            if self._vix_size_mult < 1.0:
                pre_vix = sizing_result['quantity']
                sizing_result['quantity'] = max(1, int(sizing_result['quantity'] * self._vix_size_mult))
                logger.info(f"   📊 VIX mult: {pre_vix} → {sizing_result['quantity']} ({self._vix_size_mult:.2f}x)")

            auto_approval = {
                'approved':        True,
                'confidence':      candidate_score / 100.0,
                'reasoning':       (f"v6 champion: excess={winner.excess_gap_pct:+.3f}% "
                                    f"gap={winner.gap_pct:+.3f}% score={candidate_score:.0f}"),
                'risk_assessment': 'LOW' if candidate_score >= 80 else 'MEDIUM',
            }

            trade = self._execute_entry(winner, sizing_result, flight_plan, auto_approval)
            if not trade:
                logger.error("❌ v6 entry execution failed")
                return None

            trade.loop_number = 0   # v6 has no loops — single shot
            trade.tier_used   = 'V6_CHAMPION'

            handoff_success = self._handoff_to_phase4(trade)
            if handoff_success:
                trade.status = GapTradeStatus.HANDED_OFF
                logger.info("✅ Handed to Phase 4")
            else:
                logger.warning("⚠️ Phase 4 handoff failed — position unmonitored!")

            self._trade_fired       = True
            self.current_trade      = trade
            self.daily_trade_count += 1

            self._send_async_chatgpt_log(winner, trade, flight_plan, 0, 'V6_CHAMPION')

            logger.info("")
            logger.info("=" * 80)
            logger.info(f"✅ PHASE 5 v6.0.0 COMPLETE — {trade.symbol} {trade.direction.value} @ {trade.entry_price:.2f}")
            logger.info("=" * 80)

            return trade

        except Exception as e:
            logger.error(f"v6 gap strategy error: {e}")
            logger.exception(e)
            self._notify_error(str(e))
            return None

    # ───────────────────────────────────────────────────────────────────────────

    def _get_nifty_gap_pct(self, batch_quotes: dict) -> float:
        """Extract Nifty 50 gap% from the batch quote response.

        Returns 0.0 if Nifty quote is unavailable (safe fallback — excess_gap_pct
        will equal gap_pct, meaning no index-level adjustment).
        """
        try:
            nifty_qd  = batch_quotes.get("NSE:NIFTY 50", {})
            ohlc      = nifty_qd.get('ohlc', {})
            prev_close = ohlc.get('close', 0)
            open_price = ohlc.get('open', 0)
            if prev_close > 0 and open_price > 0:
                return ((open_price - prev_close) / prev_close) * 100.0
        except Exception as e:
            logger.debug(f"Nifty gap calc error: {e}")
        return 0.0

    def _build_v6_candidate(self, symbol: str, qd: dict,
                             nifty_gap_pct: float) -> Optional[GapCandidate]:
        """Build a GapCandidate for v6 scoring from a live quote + indicator cache.

        Applies entry filters inline so the caller only receives valid candidates:
          - open_price confirmed (> 0)
          - prev_close from cache (or quote ohlc.close)
          - abs gap >= V6_MIN_GAP_PCT
          - price within MIN_PRICE..MAX_PRICE range
          - ATR > 0 in cache
          - IEV >= V6_MIN_LIQUIDITY_VOL

        Returns None if any filter fails.
        """
        try:
            cache = self._indicator_cache.get(symbol, {})

            # Open price from live quote
            ohlc       = qd.get('ohlc', {})
            open_price = ohlc.get('open', 0.0)
            if open_price <= 0:
                return None   # Auction not confirmed yet

            # prev_close: prefer cache (from daily OHLC), fall back to quote
            prev_close = cache.get('prev_close') or ohlc.get('close', 0.0)
            if prev_close <= 0:
                return None

            # Current price (last traded)
            current_price = qd.get('last_price', open_price)
            if current_price <= 0:
                current_price = open_price

            # Price range filter
            if not (self.config.MIN_PRICE <= open_price <= self.config.MAX_PRICE):
                return None

            # Gap calculation
            gap_pct = ((open_price - prev_close) / prev_close) * 100.0
            if abs(gap_pct) < self.config.V6_MIN_GAP_PCT:
                return None

            gap_type = GapType.GAP_UP if gap_pct > 0 else GapType.GAP_DOWN

            # ── v5.8.0 FILTER 1: Gap cap — reject extreme/news gaps ──────────
            # Gaps > 3% are typically earnings/event-driven; unpredictable direction.
            if abs(gap_pct) > self.config.V6_MAX_GAP_PCT:
                logger.debug(f"_build_v6_candidate({symbol}): GAP_CAP rejected "
                             f"({gap_pct:+.2f}% > {self.config.V6_MAX_GAP_PCT}%)")
                return None

            # ── v5.9.0 FILTER 2: True gap vs inside-range gap ────────────────────────────
            # V6_REQUIRE_TRUE_GAP=True  (default): hard-reject inside-range opens.
            # V6_REQUIRE_TRUE_GAP=False           : apply V6_INSIDE_RANGE_PENALTY
            #   instead — keeps exhaustion-reversal setups but scores them lower.
            _inside_range_penalty = 0.0
            prev_high = cache.get('prev_high', 0.0)
            prev_low  = cache.get('prev_low',  0.0)
            if prev_high > 0 and prev_low > 0:
                _is_inside = (
                    (gap_type == GapType.GAP_UP   and open_price <= prev_high) or
                    (gap_type == GapType.GAP_DOWN  and open_price >= prev_low)
                )
                if _is_inside:
                    if self.config.V6_REQUIRE_TRUE_GAP:
                        logger.debug(f"_build_v6_candidate({symbol}): FAKE_GAP rejected "
                                     f"(open {open_price:.2f} inside PDH {prev_high:.2f}/PDL {prev_low:.2f})")
                        return None
                    else:
                        _pen = getattr(self.config, 'V6_INSIDE_RANGE_PENALTY', 12)
                        _inside_range_penalty = float(_pen)
                        logger.debug(f"_build_v6_candidate({symbol}): INSIDE_RANGE "
                                     f"penalty -{_pen} (open {open_price:.2f} inside PDH/PDL)")

            # Excess gap (stock-specific gap above/below the Nifty move)
            # For gap-up:   excess = stock_gap - nifty_gap  (positive = outperforming)
            # For gap-down: excess = stock_gap - nifty_gap  (negative = underperforming)
            excess_gap_pct = gap_pct - nifty_gap_pct

            # Excess direction sanity: gap-up stock must still beat nifty (or nifty going down)
            if gap_type == GapType.GAP_UP and excess_gap_pct < self.config.V6_MIN_EXCESS_GAP_PCT:
                return None
            if gap_type == GapType.GAP_DOWN and excess_gap_pct > -self.config.V6_MIN_EXCESS_GAP_PCT:
                return None

            # Indicator cache
            atr          = cache.get('atr', 0.0)
            rsi          = cache.get('rsi', 50.0)
            adx          = cache.get('adx', 25.0)
            avg_volume   = cache.get('avg_volume_20d', 0.0)
            iev          = cache.get('iev', 0.0)
            vb_iev_score = cache.get('vb_iev_score', 0.0)

            if atr <= 0:
                return None   # ATR unavailable — cannot size position

            # IEV liquidity check
            if iev < self.config.V6_MIN_LIQUIDITY_VOL:
                return None

            # ── v5.9.0 FILTER 3: Absorption scoring adjustment ───────────────
            # True absorption = HIGH volume + LOW price displacement.
            # v5.8 used abs(gap_pct) < 1.5% as proxy — too loose: a 3× volume spike on
            # a 1.4% gap is momentum, not absorption. Fix: tighten gap cap to 1.0% AND
            # require displacement_efficiency (iev_ratio / gap_pct) ≥ 3.0 (more volume
            # per unit of price movement = heavier institutional hand).
            absorption_bonus = 0.0
            if avg_volume > 0:
                iev_ratio = (iev / avg_volume) if avg_volume > 0 else 0.0
                gap_abs   = abs(gap_pct)
                # displacement_efficiency: high = lots of volume moved price very little = absorption
                displacement_efficiency = (iev_ratio / gap_abs) if gap_abs > 0 else 0.0
                if (iev_ratio >= self.config.V6_ABSORPTION_IEV_RATIO
                        and gap_abs < 1.0
                        and displacement_efficiency >= 3.0):
                    # Heavy pre-open volume + tight gap + low displacement = institutional absorption
                    absorption_bonus = 15.0
                    logger.debug(f"_build_v6_candidate({symbol}): ABSORPTION signal "
                                 f"(IEV {iev_ratio:.1f}× avg, gap {gap_pct:+.2f}%, "
                                 f"disp_eff={displacement_efficiency:.1f}) +15")
                elif iev_ratio < self.config.V6_LOW_CONVICTION_RATIO:
                    # Gap with almost no pre-open volume = no institutional conviction
                    absorption_bonus = -10.0
                    logger.debug(f"_build_v6_candidate({symbol}): LOW_CONVICTION "
                                 f"(IEV {iev_ratio:.2f}× avg_vol) -10")

            # Build a VolumeBurstScore using pre-cached IEV factor
            # Factor B (range intensity) is unavailable at 09:15:30 — leave at 0
            # v5.8.0: Apply absorption_bonus to total_score
            vb = VolumeBurstScore()
            vb.volume_ratio_score    = int(vb_iev_score)
            vb.range_intensity_score = 0
            vb.total_score           = max(0, int(vb_iev_score + absorption_bonus - _inside_range_penalty))
            vb.volume_ratio          = (iev / avg_volume) if avg_volume > 0 else 0.0

            candidate = GapCandidate(
                symbol        = symbol,
                gap_type      = gap_type,
                gap_pct       = round(gap_pct, 4),
                prev_close    = prev_close,
                open_price    = open_price,
                current_price = current_price,
                atr           = atr,
                volume_ratio  = vb.volume_ratio,
                rsi           = rsi,
                adx           = adx,
                volume_burst  = vb,
                avg_volume_20d= avg_volume,
                excess_gap_pct= round(excess_gap_pct, 4),
                iev           = iev,
            )
            return candidate

        except Exception as e:
            logger.debug(f"_build_v6_candidate({symbol}): {e}")
            return None

    def _log_v6_champion_comparison(self, up_champ: Optional[GapCandidate],
                                     down_champ: Optional[GapCandidate],
                                     nifty_gap_pct: float):
        """Log champion comparison table for both sides."""
        logger.info("")
        logger.info("┌" + "─" * 82 + "┐")
        logger.info(f"│{'CHAMPION-VS-CHAMPION COMPARISON  (Nifty gap: ' + f'{nifty_gap_pct:+.3f}%' + ')':^82}│")
        logger.info("├" + "─" * 16 + "┬" + "─" * 10 + "┬" + "─" * 12 + "┬" + "─" * 12 + "┬" + "─" * 10 + "┬" + "─" * 18 + "┤")
        logger.info(f"│ {'SIDE':<14} │ {'GAP %':>8} │ {'EXCESS %':>10} │ {'IEV':>10} │ {'IEV Sc':>8} │ {'SYMBOL':>16} │")
        logger.info("├" + "─" * 16 + "┼" + "─" * 10 + "┼" + "─" * 12 + "┼" + "─" * 12 + "┼" + "─" * 10 + "┼" + "─" * 18 + "┤")

        def row(label, c):
            if c is None:
                return f"│ {label:<14} │ {'—':>8} │ {'—':>10} │ {'—':>10} │ {'—':>8} │ {'—':>16} │"
            vb_sc = c.volume_burst.total_score if c.volume_burst else 0
            return (f"│ {label:<14} │ {c.gap_pct:>+8.3f} │ {c.excess_gap_pct:>+10.3f} │ "
                    f"{c.iev:>10,.0f} │ {vb_sc:>8.0f} │ {c.symbol:>16} │")

        logger.info(row("GAP-UP  CHAMP", up_champ))
        logger.info(row("GAP-DOWN CHAMP", down_champ))
        logger.info("└" + "─" * 16 + "┴" + "─" * 10 + "┴" + "─" * 12 + "┴" + "─" * 12 + "┴" + "─" * 10 + "┴" + "─" * 18 + "┘")
        logger.info("")


    # ═══════════════════════════════════════════════════════════════════════════
    # v5.1.0: SINGLE LOOP PIPELINE (Scan → Filter → Score → Execute → Handoff)
    # ═══════════════════════════════════════════════════════════════════════════
    
    def _run_scan_loop(self, loop_num: int, tier: str,
                       min_gap_pct: float) -> Optional[GapTrade]:
        """
        Run a single scan-filter-score-execute pipeline for one tier.
        
        v5.1.0 Execute-First: No ChatGPT gate. Score passes → execute immediately.
        ChatGPT is notified AFTER entry (async, non-blocking).
        
        Args:
            loop_num: Which loop (1, 2, 3)
            tier: Tier label (TIER_1, TIER_2, TIER_3)
            min_gap_pct: Minimum gap percentage for this tier
            
        Returns:
            GapTrade if executed, None if no qualifying candidate
        """
        
        # ───────────────────────────────────────────────────────
        # SCAN: Find gaps at this tier's threshold
        # ───────────────────────────────────────────────────────
        logger.info(f"   🔍 Scanning {len(self.stock_universe)} stocks for ≥{min_gap_pct}% gaps...")
        
        candidates = self._scan_tier(min_gap_pct)
        self.last_scan_time = datetime.now()
        
        if not candidates:
            logger.info(f"   ❌ No gaps ≥{min_gap_pct}% found")
            self._log_loop_funnel(loop_num, len(self.stock_universe), 0, 0, 0, "NO_GAPS")
            return None
        
        logger.info(f"   ✅ Found {len(candidates)} candidates")
        
        # ───────────────────────────────────────────────────────
        # FILTER: Apply volume burst, ADX, sentiment filters
        # ───────────────────────────────────────────────────────
        filtered = self._apply_filters_with_detailed_logging(candidates)
        
        if not filtered:
            logger.info(f"   ❌ All candidates filtered out")
            self._log_loop_funnel(loop_num, len(self.stock_universe), len(candidates), 0, 0, "ALL_FILTERED")
            # Save as radar for reporting
            self._radar_candidates = candidates[:4]
            return None
        
        # ───────────────────────────────────────────────────────
        # SELECT: Pick best candidate by composite score
        # ───────────────────────────────────────────────────────
        best = self._select_best_candidate(filtered)
        
        if not best:
            logger.info(f"   ❌ No suitable candidate after ranking")
            self._log_loop_funnel(loop_num, len(self.stock_universe), len(candidates), len(filtered), 0, "NO_BEST")
            return None
        
        logger.info(f"   🎯 BEST: {best.symbol}")
        self._log_candidate_analysis(best)
        
        # Save runners-up as radar
        self._radar_candidates = [c for c in filtered if c.symbol != best.symbol][:4]
        
        # ───────────────────────────────────────────────────────
        # SCORE CHECK: Must meet threshold to proceed
        # ───────────────────────────────────────────────────────
        candidate_score = self._calculate_composite_score(best)

        # v5.5.1: Tier-adaptive threshold — relax for smaller gaps (Tier 2/3)
        tier_thresholds = {
            1: self.config.FULL_SIZE_SCORE_TIER1,
            2: self.config.FULL_SIZE_SCORE_TIER2,
            3: self.config.FULL_SIZE_SCORE_TIER3,
        }
        min_score = tier_thresholds.get(loop_num, self.config.FULL_SIZE_SCORE)

        logger.info(f"   📊 Composite Score: {candidate_score:.0f}/100 (threshold: {min_score} for Loop {loop_num})")

        if candidate_score < min_score:
            logger.info(f"   ❌ Score {candidate_score:.0f} < {min_score} — SKIP")
            self._log_loop_funnel(loop_num, len(self.stock_universe), len(candidates), len(filtered), candidate_score, "LOW_SCORE")
            return None

        # Determine position size factor based on score
        if candidate_score >= self.config.FULL_SIZE_SCORE:
            size_factor = 1.0
            logger.info(f"   ✅ Score ≥{self.config.FULL_SIZE_SCORE} → FULL SIZE")
        else:
            size_factor = 0.5
            logger.info(f"   ⚠️ Score {candidate_score:.0f} ({min_score}-{self.config.FULL_SIZE_SCORE}) → HALF SIZE")
        
        # ───────────────────────────────────────────────────────
        # FLIGHT PLAN: Generate for reference & Phase 4
        # ───────────────────────────────────────────────────────
        flight_plan = self._generate_entry_flight_plan(best)
        
        # ───────────────────────────────────────────────────────
        # POSITION SIZING (applies size_factor)
        # ───────────────────────────────────────────────────────
        sizing_result = self._calculate_position_size_with_leverage(best)
        
        if sizing_result['quantity'] <= 0:
            logger.warning("   ❌ Position sizing failed — insufficient capital")
            self._notify_skip_insufficient_capital(best, sizing_result)
            return None
        
        # Apply size factor for half-size entries
        if size_factor < 1.0:
            original_qty = sizing_result['quantity']
            sizing_result['quantity'] = max(1, int(sizing_result['quantity'] * size_factor))
            logger.info(f"   📐 Qty adjusted: {original_qty} → {sizing_result['quantity']} (half size)")

        # v5.6.0: Apply VIX-tiered size multiplier on top of score-based factor
        if self._vix_size_mult < 1.0:
            pre_vix_qty = sizing_result['quantity']
            sizing_result['quantity'] = max(1, int(sizing_result['quantity'] * self._vix_size_mult))
            logger.info(
                f"   📊 VIX tier ({self._vix_tier_label}): "
                f"qty {pre_vix_qty} → {sizing_result['quantity']} ({self._vix_size_mult:.2f}x)"
            )
        
        # ───────────────────────────────────────────────────────
        # 🔥 EXECUTE IMMEDIATELY — NO CHATGPT GATE 🔥
        # ───────────────────────────────────────────────────────
        # v5.1.0: This is the core change. Speed is everything.
        # ChatGPT latency = 2-5s = missed gap momentum.
        
        logger.info("")
        logger.info("   🔥 EXECUTE-FIRST: Placing order NOW")
        
        # Create a placeholder approval (ChatGPT will be notified async)
        auto_approval = {
            'approved': True,
            'confidence': candidate_score / 100.0,
            'reasoning': f'Execute-first: score {candidate_score:.0f}/100 (Loop {loop_num}, {tier})',
            'risk_assessment': 'LOW' if candidate_score >= 80 else 'MEDIUM'
        }
        
        trade = self._execute_entry(best, sizing_result, flight_plan, auto_approval)
        
        if not trade:
            logger.error("   ❌ Entry execution failed")
            return None
        
        # Tag with loop metadata
        trade.loop_number = loop_num
        trade.tier_used = tier
        
        # ───────────────────────────────────────────────────────
        # HANDOFF TO PHASE 4 (critical — must happen immediately)
        # ───────────────────────────────────────────────────────
        handoff_success = self._handoff_to_phase4(trade)
        
        if handoff_success:
            trade.status = GapTradeStatus.HANDED_OFF
            logger.info("   ✅ Handed to Phase 4 (Tier 1 monitoring)")
        else:
            logger.warning("   ⚠️ Phase 4 handoff failed — position unmonitored!")
        
        # ───────────────────────────────────────────────────────
        # ASYNC CHATGPT LOG (non-blocking, fire-and-forget)
        # ───────────────────────────────────────────────────────
        # ChatGPT receives entry details for learning/logging, NOT for approval.
        self._send_async_chatgpt_log(best, trade, flight_plan, loop_num, tier)
        
        return trade

    # ═══════════════════════════════════════════════════════════════════════════
    # v5.4.0: PVAT BREAKOUT ENTRY (called by Phase 5A scanner)
    # ═══════════════════════════════════════════════════════════════════════════

    def execute_pvat_candidate(self, candidate: GapCandidate,
                               pvat_metadata: Dict = None) -> Optional[GapTrade]:
        """
        DEPRECATED v5.4.2: Phase 5A now executes independently via _execute_pvat_pipeline().
        Kept as fallback safety net only. Phase 5A bypasses this entirely.

        Previously: Phase 5A → Phase 5 pipeline (gap-centric scoring penalized PVAT).
        Now: Phase 5A scores, sizes, places orders, and hands off to Phase 4 directly.
        """
        logger.warning("⚠️ execute_pvat_candidate DEPRECATED v5.4.2 — Phase 5A should execute independently")
        logger.info("")
        logger.info("=" * 80)
        logger.info("   🔷 PHASE 5A → PHASE 5: PVAT BREAKOUT CANDIDATE")
        logger.info("=" * 80)
        logger.info(f"   Symbol: {candidate.symbol}")
        logger.info(f"   Direction: {candidate.gap_type.value}")
        logger.info(f"   Current Price: ₹{candidate.current_price:.2f}")
        logger.info(f"   Volume Ratio: {candidate.volume_ratio:.2f}x")

        if pvat_metadata:
            logger.info(f"   PVAT Level: {pvat_metadata.get('level_type', '?')} @ ₹{pvat_metadata.get('level_price', 0):.2f}")
            logger.info(f"   Acceptance: {pvat_metadata.get('acceptance_candles', 0)} candles | Vol Declining: {pvat_metadata.get('volume_declining', False)}")

        # ── Guard 1: Already fired PVAT trade today ──
        if self._pvat_trade_fired:
            logger.info("   ❌ PVAT trade already fired today — SKIP")
            return None

        # ── Guard 2: Don't stack with existing MIS ──
        if self.phase4 and hasattr(self.phase4, 'has_tier1_positions'):
            if self.phase4.has_tier1_positions():
                logger.info("   ❌ Phase 4 already has Tier 1 MIS position — SKIP")
                return None

        # ── Step 1: Log candidate details ──
        self._log_candidate_analysis(candidate)

        # ── Step 2: Apply filters ──
        passed, reason = self._check_filters_v2(candidate)
        if not passed:
            logger.info(f"   ❌ Filter failed: {reason}")
            return None

        # ── Step 3: Score candidate ──
        candidate_score = self._calculate_composite_score(candidate)
        logger.info(f"   📊 Composite Score: {candidate_score:.0f}/100")

        if candidate_score < self.config.HALF_SIZE_SCORE:
            logger.info(f"   ❌ Score {candidate_score:.0f} < {self.config.HALF_SIZE_SCORE} — SKIP")
            return None

        # ── Step 4: Determine size factor ──
        if candidate_score >= self.config.FULL_SIZE_SCORE:
            size_factor = 1.0
            logger.info(f"   ✅ Score {candidate_score:.0f} ≥ {self.config.FULL_SIZE_SCORE} → FULL SIZE")
        else:
            size_factor = 0.5
            logger.info(f"   ⚠️ Score {candidate_score:.0f} ({self.config.HALF_SIZE_SCORE}-{self.config.FULL_SIZE_SCORE}) → HALF SIZE")

        # ── Step 5: Generate flight plan ──
        flight_plan = self._generate_entry_flight_plan(candidate)

        # ── Step 6: Calculate position size ──
        sizing_result = self._calculate_position_size_with_leverage(candidate)

        if not sizing_result or sizing_result.get('quantity', 0) <= 0:
            logger.info("   ❌ Position sizing returned zero quantity")
            return None

        # Apply size factor for half-size entries
        if size_factor < 1.0:
            original_qty = sizing_result['quantity']
            sizing_result['quantity'] = max(1, int(sizing_result['quantity'] * size_factor))
            logger.info(f"   📐 Half-size: {original_qty} → {sizing_result['quantity']} shares")

        # ── Step 7: ChatGPT PVAT Approval Gate ──
        # Unlike gap entries (Execute-First, 5s window), PVAT builds over 45+ min
        # acceptance — 3-5s ChatGPT latency is negligible, so we gate BEFORE entry
        approval = self._get_pvat_chatgpt_approval(
            candidate, flight_plan, pvat_metadata or {},
            candidate_score, size_factor
        )

        if not approval.get('approved', False):
            logger.info(f"   ❌ ChatGPT REJECTED PVAT entry: {approval.get('reasoning', 'N/A')}")
            return None

        # ── Step 8: Execute entry ──
        trade = self._execute_entry(candidate, sizing_result, flight_plan, approval)

        if not trade:
            logger.error("   ❌ PVAT entry execution failed")
            return None

        # Tag as PVAT trade
        trade.loop_number = 0
        trade.tier_used = 'PVAT_BREAKOUT'

        # ── Step 9: Handoff to Phase 4 with PVAT timing overrides ──
        handoff_success = self._handoff_to_phase4(trade)

        if handoff_success:
            trade.status = GapTradeStatus.HANDED_OFF
            logger.info("   ✅ PVAT trade handed to Phase 4 (Tier 1 monitoring)")
        else:
            logger.warning("   ⚠️ Phase 4 handoff failed — PVAT position unmonitored!")

        # Mark PVAT as fired for today
        self._pvat_trade_fired = True

        # ── Step 10: Async ChatGPT log ──
        self._send_async_chatgpt_log(candidate, trade, flight_plan, 0, 'PVAT')

        logger.info("   🎯 PVAT BREAKOUT TRADE ACTIVE")
        return trade

    # ═══════════════════════════════════════════════════════════════════════════
    # v5.1.0: COMPOSITE SCORE CALCULATOR
    # ═══════════════════════════════════════════════════════════════════════════

    def _calculate_composite_score(self, candidate: GapCandidate) -> float:
        """
        Calculate composite entry score (0-100) for go/no-go decision.

        v5.5.1 — Continuous gap scoring (no cliff edges), tier-adaptive thresholds.

        Factors:
        - Gap Quality        (0-35): Continuous linear interpolation (0.75% → 15, 3.0% → 35)
        - Session Timing     (0-15): Earlier in window = more momentum remaining
        - Target Probability (0-20): Gap/target ratio — probability of mean reversion
        - Trend Alignment    (0-10): RSI context (override at ≥1.5% gap)
        - Volume Burst       (0-10): Institutional interest (reduced — unreliable early)
        - PMBI Alignment     (0-10): Pre-market breadth bias alignment

        Threshold: Tier1=50, Tier2/3=45 (adaptive)
        """
        score = 0.0

        # ── Gap Quality (0-35) ── v5.5.1: Continuous scoring (no cliff edges)
        gap_abs = abs(candidate.gap_pct)
        if gap_abs >= 3.0:
            score += 35
        elif gap_abs >= 0.75:
            # Linear interpolation: 0.75% → 15pts, 3.0% → 35pts
            score += 15 + (gap_abs - 0.75) / (3.0 - 0.75) * 20
        else:
            score += 8

        # ── Volume Burst (0-10) ── v5.4.0: Reduced — volume unreliable at 09:17-09:20
        if candidate.volume_burst:
            vb = candidate.volume_burst.total_score  # Now 0-50
            score += min(10, vb * 0.2)

        # ── Trend Alignment (0-10) ── v5.4.0: Reduced from 15 — RSI lags at open
        rsi_override_threshold = getattr(self.config, 'GAP_LARGE_RSI_OVERRIDE_PCT', 1.5)
        if gap_abs >= rsi_override_threshold:
            score += 8  # Large gap = strong momentum regardless of lagging RSI
            logger.debug(f"      📊 RSI override: gap {gap_abs:.1f}% ≥ {rsi_override_threshold}% → 8/10")
        elif candidate.gap_type == GapType.GAP_DOWN:
            # For BUY: lower RSI = more oversold = better
            if candidate.rsi < 30:
                score += 10
            elif candidate.rsi < 35:
                score += 8
            elif candidate.rsi < 40:
                score += 6
            elif candidate.rsi < 45:
                score += 4
            else:
                score += 2
        else:
            # For SELL: higher RSI = more overbought = better
            if candidate.rsi > 70:
                score += 10
            elif candidate.rsi > 65:
                score += 8
            elif candidate.rsi > 60:
                score += 6
            elif candidate.rsi > 55:
                score += 4
            else:
                score += 2
        
        # ── Session Timing (0-15) ──
        # Earlier in window = better (gap momentum is strongest)
        now = datetime.now().time()
        if now <= dt_time(9, 19):
            score += 15  # Very early — maximum momentum
        elif now <= dt_time(9, 21):
            score += 12
        elif now <= dt_time(9, 25):
            score += 9
        elif now <= dt_time(9, 35):
            score += 6
        else:
            score += 3  # Late in window

        # ── Target Probability Bonus (0-20) ── v5.5.0
        # Larger gap ÷ target = higher mean-reversion probability
        # A 2.89% gap reverting 0.3% is near-certain (ratio 9.6x)
        target_pct = getattr(self.config, 'GAP_TARGET_PCT', 0.3)
        if target_pct > 0:
            gap_target_ratio = gap_abs / target_pct
        else:
            gap_target_ratio = 0

        if gap_target_ratio >= 8:        # 2.4%+ gap vs 0.3% target → near-certain  # v5.5.0
            score += 20
        elif gap_target_ratio >= 5:      # 1.5%+ gap → very high probability
            score += 15
        elif gap_target_ratio >= 3:      # 0.9%+ gap → high probability
            score += 10
        elif gap_target_ratio >= 2:      # 0.6%+ gap → moderate probability
            score += 5

        # ── PMBI Bias Alignment Bonus (0-10) ── v5.5.0
        # If pre-market breadth scan detected a directional bias,
        # give bonus to trades aligned with market direction
        pmbi_bonus = 0
        try:
            orch = getattr(self, 'orchestrator', None)
            market_bias = getattr(orch, 'market_bias', None) if orch else None
            if market_bias and market_bias.get('direction') != 'MIXED':
                bias_priority = market_bias.get('priority', 'NEUTRAL')  # BUY or SELL
                trade_direction = candidate.get_direction()  # GapTradeDirection.BUY or .SELL
                bonus_pts = getattr(self.config, 'PMBI_PH5_SCORE_BONUS', 10)

                if bias_priority == trade_direction.value:
                    # Trade aligns with market bias → bonus
                    pmbi_bonus = bonus_pts
                    logger.info(f"      🧠 PMBI +{bonus_pts}: {trade_direction.value} aligns with {bias_priority} bias")
                # No penalty for misaligned — just no bonus
        except Exception:
            pass  # PMBI is advisory, never blocks

        score += pmbi_bonus

        # ── Gap Fill Velocity Penalty (0 to −20) ── v5.7.0
        # Measures how fast the gap is actually closing at scan time.
        # Formula: recovery_pct (already computed in VB score) ÷ minutes since open.
        # A gap stuck below 3%/min after 2.5 min means no institutional counter-flow —
        # the market has accepted the gap; it will go sideways or continue in gap direction.
        # This is the "best stock selected, no fill happens, sideways bleed" problem.
        if candidate.volume_burst is not None and candidate.volume_burst.recovery_pct is not None:
            rec = candidate.volume_burst.recovery_pct   # % of gap already closed
            _now = datetime.now()
            _open_dt = _now.replace(hour=9, minute=15, second=0, microsecond=0)
            _elapsed_min = max(1.0, (_now - _open_dt).total_seconds() / 60)
            rec_velocity = rec / _elapsed_min            # gap-fill rate: %/min

            if _elapsed_min >= 2.5:                      # Only apply after opening noise settles
                if rec_velocity < 3.0:
                    # Gap has barely moved: strong stall signal → heavy penalty
                    score -= 20
                    logger.info(
                        f"      ⚠️ Fill-velocity −20: {rec:.1f}% filled in "
                        f"{_elapsed_min:.1f}min ({rec_velocity:.1f}%/min) — gap stalling"
                    )
                elif rec_velocity < 6.0:
                    # Slow fill: marginal candidate, mild penalty
                    score -= 8
                    logger.debug(
                        f"      ⚠️ Fill-velocity −8: {rec:.1f}% filled in "
                        f"{_elapsed_min:.1f}min ({rec_velocity:.1f}%/min) — fill slow"
                    )
                elif rec_velocity > 15.0:
                    # Fast fill: gap has real momentum → small bonus
                    score += 5
                    logger.debug(
                        f"      ✅ Fill-velocity +5: {rec:.1f}% filled in "
                        f"{_elapsed_min:.1f}min ({rec_velocity:.1f}%/min) — strong fill"
                    )

        return score  # v5.5.0: uncapped — PMBI + Target Probability can push above 100

    # ═══════════════════════════════════════════════════════════════════════════
    # v5.1.0: ASYNC CHATGPT POST-ENTRY LOG
    # ═══════════════════════════════════════════════════════════════════════════
    
    def _send_async_chatgpt_log(self, candidate: GapCandidate, trade: GapTrade,
                                flight_plan: Dict, loop_num: int, tier: str):
        """
        v5.1.0: Send entry details to ChatGPT AFTER execution (non-blocking).
        
        This is for LOGGING and LEARNING, not approval.
        ChatGPT can flag concerns for the next trade but cannot block this one.
        Runs in a background thread so it doesn't delay Phase 4 handoff.
        """
        if not self.chatgpt:
            logger.info("   ℹ️ ChatGPT not available — skipping post-entry log")
            return
        
        def _async_chatgpt_call():
            try:
                vb = candidate.volume_burst
                direction = candidate.get_direction()
                
                prompt = f"""📋 PHASE 5 POST-ENTRY LOG (for your records — trade already executed)

TRADE EXECUTED:
• {trade.symbol} {direction.value} @ ₹{trade.entry_price:.2f}
• Qty: {trade.quantity} (MIS)
• Loop: {loop_num}/3 ({tier})
• Composite Score: {trade.chatgpt_approval.get('confidence', 0) * 100:.0f}/100

GAP DATA:
• Gap: {candidate.gap_pct:+.2f}% ({candidate.gap_type.value})
• Volume Burst: {vb.total_score:.0f}/50 (Vol {vb.volume_ratio:.1f}x, Range/ATR {vb.range_vs_atr:.2f}, Recovery {vb.recovery_pct:.1f}%)
• RSI: {candidate.rsi:.1f} | ADX: {candidate.adx:.1f}

FLIGHT PLAN:
• Truth Score: {flight_plan.get('overall_truth_score', 'N/A')}
• Direction: {flight_plan.get('overall_direction', 'N/A')}

SENTIMENT: {self.market_sentiment}

MONITORING: Phase 4 Tier 1 (10-15s checks, TCAS/ILS, max exit 12:00 PM)

NOTE: This trade was already executed. Please log any concerns for future reference.
Respond briefly with: assessment of entry quality and any flags for monitoring."""

                response = self.chatgpt.get_decision(prompt)
                
                if response:
                    # Store response in trade record
                    if trade.chatgpt_approval:
                        trade.chatgpt_approval['post_entry_assessment'] = response[:500]
                    logger.info(f"   🤖 ChatGPT post-entry logged: {response[:100]}...")
                
            except Exception as e:
                logger.warning(f"   ⚠️ ChatGPT async log failed: {e}")
        
        # Fire and forget — don't block the main thread
        thread = threading.Thread(target=_async_chatgpt_call, daemon=True)
        thread.start()
        logger.info("   🤖 ChatGPT post-entry log sent (async)")

    def _get_pvat_chatgpt_approval(self, candidate: GapCandidate,
                                    flight_plan: Dict,
                                    pvat_metadata: Dict,
                                    candidate_score: float,
                                    size_factor: float) -> Dict:
        """
        v5.4.0: Get ChatGPT pre-entry approval for PVAT breakout trades.

        Unlike gap entries (Execute-First due to 5s momentum window),
        PVAT breakouts build over 45+ min acceptance — 3-5s ChatGPT
        latency is negligible. This enables a real approval gate.

        Returns:
            {
                'approved': bool,
                'confidence': float (0-1),
                'reasoning': str,
                'risk_assessment': str,
                'source': 'PHASE5A_PVAT'
            }
        """
        logger.info("")
        logger.info("   🤖 REQUESTING CHATGPT PVAT ENTRY APPROVAL...")

        min_confidence = getattr(self.config, 'PVAT_CHATGPT_MIN_CONFIDENCE', 0.60)

        # If ChatGPT not available, auto-approve with medium confidence
        if not self.chatgpt:
            logger.info("   ℹ️ ChatGPT not available — auto-approving with 70% confidence")
            return {
                'approved': True,
                'confidence': 0.70,
                'reasoning': 'Auto-approved (ChatGPT not available)',
                'risk_assessment': 'MEDIUM',
                'source': 'PHASE5A_PVAT'
            }

        # If toggle disabled, auto-approve
        if not getattr(self.config, 'PVAT_CHATGPT_ENABLED', True):
            logger.info("   ℹ️ PVAT ChatGPT approval disabled — auto-approving")
            return {
                'approved': True,
                'confidence': 0.75,
                'reasoning': 'Auto-approved (PVAT ChatGPT gate disabled)',
                'risk_assessment': 'MEDIUM',
                'source': 'PHASE5A_PVAT'
            }

        try:
            # Extract PVAT-specific context (raw 4-act pattern data from Phase 5A)
            direction = candidate.get_direction()
            vb = candidate.volume_burst
            level_type = pvat_metadata.get('level_type', '?')
            level_price = pvat_metadata.get('level_price', 0)
            acceptance_candles = pvat_metadata.get('acceptance_candles', 0)
            vol_declining = pvat_metadata.get('volume_declining', False)
            breakout_vol_ratio = pvat_metadata.get('breakout_volume_ratio',
                                                    candidate.volume_ratio)

            # Breakout distance from level
            breakout_pct = 0.0
            if level_price > 0:
                breakout_pct = abs(candidate.current_price - level_price) / level_price * 100

            prompt = f"""🔷 PHASE 5A PVAT BREAKOUT — ENTRY DECISION

CANDIDATE: {candidate.symbol}
Direction: {direction.value}
Entry Price: ₹{candidate.current_price:.2f}

═══ PHASE 5A: 4-ACT BREAKOUT PATTERN ═══

ACT 1 — LEVEL EXISTS:
  Level Type: {level_type}
  Level Price: ₹{level_price:.2f}
  Significance: {"STRONG (Previous Day High/Low — proven institutional level)" if level_type in ('PDH', 'PDL') else "MODERATE (Multi-day or IB level)" if level_type in ('MULTI_DAY_HIGH', 'MULTI_DAY_LOW', 'IB_HIGH', 'IB_LOW') else "WEAK (POC or other)"}

ACT 2 — REJECTION (level proved real):
  Price tested this level and bounced away before today's acceptance phase.

ACT 3 — ACCEPTANCE (sellers exhausted):
  Duration: {acceptance_candles} candles ({acceptance_candles * 15} minutes at level)
  Volume Declining: {'YES ✅ — sellers running out of inventory' if vol_declining else 'NO ⚠️ — active trading still at level'}
  Quality: {"HIGH — 5+ candles with volume decline = textbook exhaustion" if acceptance_candles >= 5 and vol_declining else "GOOD — 3+ candles meeting minimum threshold" if acceptance_candles >= 3 else "LOW — insufficient acceptance"}

ACT 4 — BREAKOUT:
  Breakout Distance: {breakout_pct:.2f}% beyond level
  Breakout Volume: {breakout_vol_ratio:.1f}x average {"✅ STRONG" if breakout_vol_ratio >= 2.0 else "⚠️ MODERATE" if breakout_vol_ratio >= 1.5 else "❌ WEAK"}

═══ MARKET CONTEXT ═══
  RSI: {candidate.rsi:.1f} | ADX: {candidate.adx:.1f}
  Market Sentiment: {self.market_sentiment}

═══ PHASE 5 SCORING ═══
  Composite Score: {candidate_score:.0f}/100
  Size: {'FULL' if size_factor >= 1.0 else 'HALF'}
  Product: MIS (intraday, exit by 15:00)
  Exit: Phase 4 TCAS dynamic trailing stop

═══ FLIGHT PLAN ═══
  Truth Score: {flight_plan.get('overall_truth_score', 'N/A')}%
  Direction: {flight_plan.get('overall_direction', 'N/A')}

QUESTION: Based on the 4-ACT pattern quality above, should we ENTER this {direction.value} breakout?
Key factors: Is the acceptance duration sufficient? Is the breakout volume convincing? Does market context support this direction?

Respond ONLY with valid JSON:
{{"decision": "APPROVE" or "REJECT", "confidence": 0.0-1.0, "reasoning": "brief reason", "risk_assessment": "LOW/MEDIUM/HIGH"}}"""

            # Call ChatGPT
            response = self.chatgpt.get_decision(prompt)

            if response:
                try:
                    import re
                    json_match = re.search(r'\{[^{}]+\}', response)
                    if json_match:
                        result = json.loads(json_match.group())

                        approved = result.get('decision', '').upper() == 'APPROVE'
                        confidence = float(result.get('confidence', 0.5))
                        reasoning = result.get('reasoning', '')
                        risk = result.get('risk_assessment', 'MEDIUM')

                        # Check minimum confidence
                        if approved and confidence < min_confidence:
                            approved = False
                            reasoning = (f"Confidence {confidence:.0%} below "
                                        f"threshold {min_confidence:.0%}")

                        logger.info(f"   🤖 Decision: {'APPROVED ✅' if approved else 'REJECTED ❌'}")
                        logger.info(f"   🤖 Confidence: {confidence:.0%}")
                        logger.info(f"   🤖 Reasoning: {reasoning}")
                        logger.info(f"   🤖 Risk: {risk}")

                        # Telegram notification on REJECT
                        if not approved and self.telegram:
                            self.telegram.send_message(
                                f"🔷 PVAT BREAKOUT REJECTED BY ChatGPT\n\n"
                                f"Stock: {candidate.symbol}\n"
                                f"Level: {level_type} @ ₹{level_price:.2f}\n"
                                f"Acceptance: {acceptance_candles} candles "
                                f"({'vol declining' if vol_declining else 'vol active'})\n"
                                f"Composite: {candidate_score:.0f}/100\n\n"
                                f"ChatGPT: REJECT ({confidence:.0%} confidence)\n"
                                f"Reason: \"{reasoning}\"\n\n"
                                f"Phase 5A continues scanning other stocks."
                            )

                        return {
                            'approved': approved,
                            'confidence': confidence,
                            'reasoning': reasoning,
                            'risk_assessment': risk,
                            'source': 'PHASE5A_PVAT',
                            'score': candidate_score,
                            'pvat_metadata': pvat_metadata,
                            'size_factor': size_factor
                        }

                except json.JSONDecodeError:
                    logger.warning(f"   ⚠️ Failed to parse ChatGPT PVAT response: {response[:100]}")

            # Fallback: ChatGPT responded but unparseable — auto-approve
            logger.warning("   ⚠️ ChatGPT response unclear — auto-approving with 65% confidence")
            return {
                'approved': True,
                'confidence': 0.65,
                'reasoning': 'Auto-approved (ChatGPT response unclear)',
                'risk_assessment': 'MEDIUM',
                'source': 'PHASE5A_PVAT',
                'score': candidate_score,
                'pvat_metadata': pvat_metadata,
                'size_factor': size_factor
            }

        except Exception as e:
            logger.error(f"   ❌ ChatGPT PVAT approval error: {e}")
            return {
                'approved': True,
                'confidence': 0.60,
                'reasoning': f'Auto-approved (error: {str(e)[:50]})',
                'risk_assessment': 'MEDIUM',
                'source': 'PHASE5A_PVAT',
                'score': candidate_score,
                'pvat_metadata': pvat_metadata,
                'size_factor': size_factor
            }

    # ═══════════════════════════════════════════════════════════════════════════
    # SENTIMENT ANALYSIS
    # ═══════════════════════════════════════════════════════════════════════════
    
    def _get_market_sentiment(self) -> str:
        """Get market sentiment using FinBERT."""
        if not self.finbert or not self.news_scraper:
            logger.info("FinBERT/NewsScraper not available, using NEUTRAL")
            return "NEUTRAL"
        
        try:
            # Get recent market news
            headlines = self.news_scraper.scrape_general_headlines(limit=10)
            
            if not headlines:
                return "NEUTRAL"
            
            # Analyze sentiment
            sentiment_scores = []
            for headline in headlines:
                result = self.finbert.analyze(headline)
                if result:
                    sentiment_scores.append(result.get('sentiment_score', 0))
            
            if not sentiment_scores:
                return "NEUTRAL"
            
            avg_score = sum(sentiment_scores) / len(sentiment_scores)
            
            if avg_score > 0.2:
                return "BULLISH"
            elif avg_score < -0.2:
                return "BEARISH"
            else:
                return "NEUTRAL"
                
        except Exception as e:
            logger.warning(f"Sentiment analysis error: {e}")
            return "NEUTRAL"

    # ═══════════════════════════════════════════════════════════════════════════
    # GAP SCANNING
    # ═══════════════════════════════════════════════════════════════════════════
    
    def _scan_for_gaps(self) -> List[GapCandidate]:
        """
        Scan stock universe for gaps using tiered approach.
        
        v5.1.0: This method is kept for backward compatibility.
        The 3-loop architecture calls _scan_tier() directly per loop.
        
        Tier 1: Large gaps (≥1.5%)
        Tier 2: Medium gaps (≥1.0%) if Tier 1 empty
        Tier 3: Small gaps (≥0.75%) if Tier 2 empty
        """
        candidates = []
        
        # Tier 1: Large gaps
        logger.info(f"   Tier 1 scan (≥{self.config.TIER_1_GAP_PCT}% gap)...")
        tier1 = self._scan_tier(self.config.TIER_1_GAP_PCT)
        if tier1:
            logger.info(f"   ✅ Tier 1: {len(tier1)} candidates")
            return tier1
        
        # Tier 2: Medium gaps
        logger.info(f"   Tier 2 scan (≥{self.config.TIER_2_GAP_PCT}% gap)...")
        tier2 = self._scan_tier(self.config.TIER_2_GAP_PCT)
        if tier2:
            logger.info(f"   ✅ Tier 2: {len(tier2)} candidates")
            return tier2
        
        # Tier 3: Small gaps
        logger.info(f"   Tier 3 scan (≥{self.config.TIER_3_GAP_PCT}% gap)...")
        tier3 = self._scan_tier(self.config.TIER_3_GAP_PCT)
        if tier3:
            logger.info(f"   ✅ Tier 3: {len(tier3)} candidates")
            return tier3
        
        return candidates
    
    def _scan_tier(self, min_gap_pct: float) -> List[GapCandidate]:
        """
        Scan for gaps at specific threshold with detailed logging.
        
        v5.2.0: Two modes:
        - BATCH MODE (cache valid): 1 batch kite.quote() → gap calc from cache → ~0.5s
        - FALLBACK MODE (no cache): Individual kite.quote() per stock → ~22s (v5.1.0 behavior)
        """
        candidates = []
        all_gaps = []  # Track ALL stocks for summary table
        scan_errors = 0
        
        cache_valid = self._is_cache_valid()
        
        if cache_valid:
            # ═══════════════════════════════════════════════════════════
            # v5.2.0 BATCH MODE: 1 API call for all 147 stocks
            # ═══════════════════════════════════════════════════════════
            scan_start = time.time()
            
            try:
                symbols_nse = [f"NSE:{s}" for s in self.stock_universe]
                all_quotes = self.kite.quote(symbols_nse)
            except Exception as e:
                logger.error(f"   ❌ Batch quote failed: {e} — falling back to individual calls")
                return self._scan_tier_fallback(min_gap_pct)
            
            scan_elapsed = time.time() - scan_start
            logger.info(f"   ⚡ Batch quote: {len(all_quotes)} stocks in {scan_elapsed:.2f}s")
            
            for symbol in self.stock_universe:
                try:
                    quote_data = all_quotes.get(f"NSE:{symbol}", {})
                    if not quote_data:
                        scan_errors += 1
                        continue
                    
                    ohlc = quote_data.get('ohlc', {})
                    open_price = ohlc.get('open', 0)
                    current_price = quote_data.get('last_price', 0)
                    
                    # v5.2.1: Price filter — skip stocks outside range
                    if current_price < self.config.MIN_PRICE or current_price > self.config.MAX_PRICE:
                        continue
                    
                    # Use CACHED prev_close (from pre-market, closed candles only)
                    cached = self._indicator_cache.get(symbol)
                    if cached:
                        prev_close = cached['prev_close']
                    else:
                        # Cache miss — use quote's prev_close as fallback
                        prev_close = ohlc.get('close', 0)
                    
                    if prev_close > 0 and open_price > 0:
                        gap_pct = ((open_price - prev_close) / prev_close) * 100
                        all_gaps.append((symbol, gap_pct, prev_close, open_price))
                        
                        # Full analysis only if gap meets threshold
                        if abs(gap_pct) >= min_gap_pct:
                            candidate = self._analyze_stock_gap_with_quote(
                                symbol, min_gap_pct, quote_data
                            )
                            if candidate:
                                candidates.append(candidate)
                    
                except Exception as e:
                    scan_errors += 1
                    logger.debug(f"Error analyzing {symbol}: {e}")
        else:
            # ═══════════════════════════════════════════════════════════
            # FALLBACK MODE: Individual calls (v5.1.0 behavior)
            # ═══════════════════════════════════════════════════════════
            logger.info(f"   ⚠️ No pre-market cache — using individual quote calls")
            return self._scan_tier_fallback(min_gap_pct)
        
        # ═══════════════════════════════════════════════════════════════
        # DETAILED SCAN SUMMARY TABLE (Phase 1 style)
        # ═══════════════════════════════════════════════════════════════
        if all_gaps:
            self._log_gap_scan_table(all_gaps, candidates, min_gap_pct, scan_errors)
        
        return candidates
    
    def _scan_tier_fallback(self, min_gap_pct: float) -> List[GapCandidate]:
        """
        v5.2.0 FALLBACK: Individual quote calls (v5.1.0 behavior).
        Used when pre-market cache is not available (late boot, cache failure).
        """
        candidates = []
        all_gaps = []
        scan_errors = 0
        
        for symbol in self.stock_universe:
            try:
                # Get quote ONCE per stock — used for both gap table and analysis
                quote = self.kite.quote(f"NSE:{symbol}")
                quote_data = quote.get(f"NSE:{symbol}", {})
                
                if not quote_data:
                    scan_errors += 1
                    continue
                
                ohlc = quote_data.get('ohlc', {})
                prev_close = ohlc.get('close', 0)
                open_price = ohlc.get('open', 0)
                current_price = quote_data.get('last_price', 0)
                
                # v5.2.1: Price filter — skip stocks outside range
                if current_price < self.config.MIN_PRICE or current_price > self.config.MAX_PRICE:
                    continue
                
                if prev_close > 0 and open_price > 0:
                    gap_pct = ((open_price - prev_close) / prev_close) * 100
                    all_gaps.append((symbol, gap_pct, prev_close, open_price))
                    
                    # Full analysis only if gap meets threshold
                    if abs(gap_pct) >= min_gap_pct:
                        candidate = self._analyze_stock_gap_with_quote(
                            symbol, min_gap_pct, quote_data
                        )
                        if candidate:
                            candidates.append(candidate)
                    
            except Exception as e:
                scan_errors += 1
                logger.debug(f"Error analyzing {symbol}: {e}")
        
        # Log scan table
        if all_gaps:
            self._log_gap_scan_table(all_gaps, candidates, min_gap_pct, scan_errors)
        
        return candidates
    
    def _log_gap_scan_table(self, all_gaps: List[Tuple], candidates: list, 
                            min_gap_pct: float, scan_errors: int):
        """Log formatted gap scan summary table."""
        # Sort by absolute gap% descending
        all_gaps.sort(key=lambda x: abs(x[1]), reverse=True)
        
        logger.info("")
        logger.info("┌" + "─" * 78 + "┐")
        logger.info(f"│{'GAP SCAN RESULTS (threshold: ≥' + f'{min_gap_pct}%)':^78}│")
        logger.info("├" + "─" * 18 + "┬" + "─" * 12 + "┬" + "─" * 14 + "┬" + "─" * 14 + "┬" + "─" * 16 + "┤")
        logger.info(f"│ {'SYMBOL':<16} │ {'GAP %':>10} │ {'PREV CLOSE':>12} │ {'OPEN':>12} │ {'STATUS':>14} │")
        logger.info("├" + "─" * 18 + "┼" + "─" * 12 + "┼" + "─" * 14 + "┼" + "─" * 14 + "┼" + "─" * 16 + "┤")
        
        # Show top gaps (qualifying + near-miss)
        shown = 0
        for symbol, gap_pct, prev_close, open_price in all_gaps:
            if shown >= 15:
                remaining = len(all_gaps) - shown
                if remaining > 0:
                    logger.info(f"│ {'... ' + str(remaining) + ' more':<16} │ {'':>10} │ {'':>12} │ {'':>12} │ {'below threshold':>14} │")
                break
            
            if abs(gap_pct) >= min_gap_pct:
                # Check if it made it to candidates
                is_candidate = any(c.symbol == symbol for c in candidates)
                status = "✅ CANDIDATE" if is_candidate else "⚠️ NO DATA"
                gap_emoji = "🔴" if gap_pct < 0 else "🟢"
            else:
                status = "— below"
                gap_emoji = "⚪"
            
            logger.info(f"│ {gap_emoji} {symbol:<14} │ {gap_pct:>+9.2f}% │ ₹{prev_close:>10.2f} │ ₹{open_price:>10.2f} │ {status:>14} │")
            shown += 1
        
        logger.info("└" + "─" * 18 + "┴" + "─" * 12 + "┴" + "─" * 14 + "┴" + "─" * 14 + "┴" + "─" * 16 + "┘")
        
        # Count summary
        qualifying = sum(1 for _, g, _, _ in all_gaps if abs(g) >= min_gap_pct)
        gap_downs = sum(1 for _, g, _, _ in all_gaps if g <= -min_gap_pct)
        gap_ups = sum(1 for _, g, _, _ in all_gaps if g >= min_gap_pct)
        
        logger.info(f"   📊 Scanned: {len(all_gaps)} stocks (BATCH mode) | "
                    f"Gaps ≥{min_gap_pct}%: {qualifying} "
                    f"(↓{gap_downs} down, ↑{gap_ups} up) | "
                    f"Errors: {scan_errors}")
        logger.info("")
    
    def _analyze_stock_gap_with_quote(self, symbol: str, min_gap_pct: float, 
                                      quote_data: Dict) -> Optional[GapCandidate]:
        """
        Analyze single stock for gap using pre-fetched quote data.
        
        v5.2.0: Uses pre-market cached indicators (ATR, RSI, ADX, avg_volume).
        Fallback: If cache miss, fetches historical_data inline (v5.1.0 behavior).
        """
        try:
            if not quote_data:
                return None
            
            ohlc = quote_data.get('ohlc', {})
            open_price = ohlc.get('open', 0)
            current_price = quote_data.get('last_price', 0)
            volume = quote_data.get('volume', 0)
            
            # v5.2.0: Use cached prev_close if available
            cached = self._indicator_cache.get(symbol)
            if cached:
                prev_close = cached['prev_close']
            else:
                prev_close = ohlc.get('close', 0)
            
            if prev_close <= 0 or open_price <= 0:
                return None
            
            # Calculate gap
            gap_pct = ((open_price - prev_close) / prev_close) * 100
            
            # Check if gap meets threshold
            if abs(gap_pct) < min_gap_pct:
                return None
            
            # Determine gap type
            if gap_pct < 0:
                gap_type = GapType.GAP_DOWN
            else:
                gap_type = GapType.GAP_UP
            
            # ─────────────────────────────────────────────────────────
            # v5.2.1: Always fetch indicators inline (cache removed)
            # ─────────────────────────────────────────────────────────
            hist_data = self._get_historical_data(symbol, days=30)
            
            if hist_data is None or len(hist_data) < 20:
                return None
            
            atr = self._calculate_atr(hist_data)
            if not atr or atr <= 0:
                logger.warning(f"   ⚠️ {symbol}: ATR unavailable — skipping gap candidate")
                return None
            avg_volume = hist_data['volume'].rolling(20).mean().iloc[-1]
            rsi = self._calculate_rsi(hist_data)
            adx = self._calculate_adx(hist_data)

            # v5.2.1 FIX: Time-normalized volume ratio
            # At 09:18 (~3 mins), expected volume ≈ 3% of daily average
            # Compare actual volume against this expected amount, not full-day average
            expected_opening_volume = avg_volume * 0.03 if avg_volume > 0 else 1
            volume_ratio = volume / expected_opening_volume if expected_opening_volume > 0 else 0

            # Create candidate
            candidate = GapCandidate(
                symbol=symbol,
                gap_type=gap_type,
                gap_pct=gap_pct,
                prev_close=prev_close,
                open_price=open_price,
                current_price=current_price,
                atr=atr,
                volume_ratio=volume_ratio,
                rsi=rsi,
                adx=adx,
                range_high=quote_data.get('ohlc', {}).get('high', current_price),
                range_low=quote_data.get('ohlc', {}).get('low', current_price),
                avg_volume_20d=avg_volume
            )
            
            # Calculate Volume Burst Score
            candidate.volume_burst = self._calculate_volume_burst_score(candidate)
            
            return candidate
            
        except Exception as e:
            logger.debug(f"Error in _analyze_stock_gap_with_quote for {symbol}: {e}")
            return None

    def _analyze_stock_gap(self, symbol: str, min_gap_pct: float) -> Optional[GapCandidate]:
        """Analyze single stock for gap."""
        try:
            # Get quote
            quote = self.kite.quote(f"NSE:{symbol}")
            quote_data = quote.get(f"NSE:{symbol}", {})
            
            if not quote_data:
                return None
            
            ohlc = quote_data.get('ohlc', {})
            prev_close = ohlc.get('close', 0)
            open_price = ohlc.get('open', 0)
            current_price = quote_data.get('last_price', 0)
            volume = quote_data.get('volume', 0)
            
            if prev_close <= 0 or open_price <= 0:
                return None
            
            # Calculate gap
            gap_pct = ((open_price - prev_close) / prev_close) * 100
            
            # Check if gap meets threshold
            if abs(gap_pct) < min_gap_pct:
                return None
            
            # Determine gap type
            if gap_pct < 0:
                gap_type = GapType.GAP_DOWN
            else:
                gap_type = GapType.GAP_UP
            
            # Get historical data for indicators
            hist_data = self._get_historical_data(symbol, days=30)
            
            if hist_data is None or len(hist_data) < 20:
                return None
            
            # Calculate ATR
            atr = self._calculate_atr(hist_data)
            if not atr or atr <= 0:
                logger.warning(f"   ⚠️ {symbol}: ATR unavailable — skipping gap candidate")
                return None

            # v5.2.1 FIX: Time-normalized volume ratio
            avg_volume = hist_data['volume'].rolling(20).mean().iloc[-1]
            expected_opening_volume = avg_volume * 0.03 if avg_volume > 0 else 1
            volume_ratio = volume / expected_opening_volume if expected_opening_volume > 0 else 0

            # Calculate RSI
            rsi = self._calculate_rsi(hist_data)

            # Calculate ADX
            adx = self._calculate_adx(hist_data)

            # Create candidate
            candidate = GapCandidate(
                symbol=symbol,
                gap_type=gap_type,
                gap_pct=gap_pct,
                prev_close=prev_close,
                open_price=open_price,
                current_price=current_price,
                atr=atr,
                volume_ratio=volume_ratio,
                rsi=rsi,
                adx=adx,
                range_high=quote_data.get('ohlc', {}).get('high', current_price),
                range_low=quote_data.get('ohlc', {}).get('low', current_price),
                avg_volume_20d=avg_volume
            )
            
            # Calculate Volume Burst Score
            candidate.volume_burst = self._calculate_volume_burst_score(candidate)
            
            return candidate
            
        except Exception as e:
            logger.debug(f"Error in _analyze_stock_gap for {symbol}: {e}")
            return None
    
    def _get_historical_data(self, symbol: str, days: int = 30) -> Optional[pd.DataFrame]:
        """Get historical OHLCV data."""
        try:
            to_date = datetime.now()
            from_date = to_date - timedelta(days=days + 10)
            
            data = self.kite.historical_data(
                instrument_token=self._get_instrument_token(symbol),
                from_date=from_date,
                to_date=to_date,
                interval="day"
            )
            
            if not data:
                return None
            
            df = pd.DataFrame(data)
            return df
            
        except Exception as e:
            logger.debug(f"Historical data error for {symbol}: {e}")
            return None
    
    def _calculate_atr(self, df: pd.DataFrame, period: int = 14) -> float:
        """Calculate Average True Range."""
        try:
            high = df['high']
            low = df['low']
            close = df['close']
            
            tr1 = high - low
            tr2 = abs(high - close.shift())
            tr3 = abs(low - close.shift())
            
            tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
            atr = tr.rolling(period).mean().iloc[-1]
            
            return atr
        except Exception as e:
            logger.error(f"❌ ATR calculation failed: {e}")
            # Return last close * 1.5% as a conservative fallback so callers don't crash.
            # PH4's add_phase5_position validates ATR at adoption and will recalculate via
            # _fetch_real_atr if this value falls outside the 0.5%-8% sanity band.
            try:
                fallback = float(df['close'].iloc[-1]) * 0.015
            except Exception:
                fallback = 0.0
            logger.warning(f"   Using ATR fallback: ₹{fallback:.2f} (1.5% of last close)")
            return fallback
    
    def _calculate_rsi(self, df: pd.DataFrame, period: int = 14) -> float:
        """Calculate RSI."""
        try:
            if ta:
                rsi = ta.RSI(df['close'], timeperiod=period)
                return rsi.iloc[-1]
            else:
                # Manual calculation
                delta = df['close'].diff()
                gain = delta.where(delta > 0, 0).rolling(period).mean()
                loss = (-delta.where(delta < 0, 0)).rolling(period).mean()
                rs = gain / loss
                rsi = 100 - (100 / (1 + rs))
                return rsi.iloc[-1]
        except:
            return 50
    
    def _calculate_adx(self, df: pd.DataFrame, period: int = 14) -> float:
        """Calculate ADX."""
        try:
            if ta:
                adx = ta.ADX(df['high'], df['low'], df['close'], timeperiod=period)
                return adx.iloc[-1]
            else:
                return 25  # Default
        except:
            return 25

    # ═══════════════════════════════════════════════════════════════════════════
    # VOLUME BURST SCORING (v4.9.1)
    # ═══════════════════════════════════════════════════════════════════════════
    
    def _calculate_volume_burst_score(self, candidate: GapCandidate) -> VolumeBurstScore:
        """
        Calculate Volume Burst Score using 2-factor system (v5.4.0).

        Factor A: Opening Volume Ratio (0-20 points) — halved, volume unreliable at 09:17-09:20
        Factor B: Price Range Intensity (0-30 points) — unchanged
        Factor C: Recovery — LOGGED ONLY, not scored (v5.4.0)
        """
        score = VolumeBurstScore()

        # ═══════════════════════════════════════════════════════════════
        # FACTOR A: Opening Volume Ratio (0-20 points) — v5.4.0: halved from 40
        # ═══════════════════════════════════════════════════════════════
        volume_ratio = candidate.volume_ratio
        score.volume_ratio = volume_ratio

        if volume_ratio >= 3.0:
            score.volume_ratio_score = 20
        elif volume_ratio >= 2.5:
            score.volume_ratio_score = 18
        elif volume_ratio >= 2.0:
            score.volume_ratio_score = 15
        elif volume_ratio >= 1.5:
            score.volume_ratio_score = 10
        elif volume_ratio >= 1.2:
            score.volume_ratio_score = 5
        else:
            score.volume_ratio_score = 0
        
        # ═══════════════════════════════════════════════════════════════
        # FACTOR B: Price Range Intensity (0-30 points)
        # ═══════════════════════════════════════════════════════════════
        if candidate.atr > 0:
            range_size = abs(candidate.range_high - candidate.range_low)
            range_vs_atr = range_size / candidate.atr
            score.range_vs_atr = range_vs_atr
            
            if range_vs_atr >= 1.5:
                score.range_intensity_score = 30
            elif range_vs_atr >= 1.2:
                score.range_intensity_score = 25
            elif range_vs_atr >= 1.0:
                score.range_intensity_score = 20
            elif range_vs_atr >= 0.8:
                score.range_intensity_score = 15
            elif range_vs_atr >= 0.5:
                score.range_intensity_score = 10
            else:
                score.range_intensity_score = 0
        
        # ═══════════════════════════════════════════════════════════════
        # FACTOR C: Opening Range Recovery — v5.4.0: LOGGED ONLY, NOT SCORED
        # Recovery removed from scoring: by the time it confirms, the move is done.
        # TCAS monitors position after entry. Value still calculated for logging.
        # ═══════════════════════════════════════════════════════════════
        gap_distance = abs(candidate.open_price - candidate.prev_close)

        if candidate.gap_type == GapType.GAP_DOWN:
            recovery = candidate.current_price - candidate.open_price
        else:
            recovery = candidate.open_price - candidate.current_price

        recovery = max(0, recovery)

        if gap_distance > 0:
            recovery_pct = (recovery / gap_distance) * 100
            score.recovery_pct = recovery_pct
        # score.recovery_score stays 0 — not added to total

        # v5.4.0: 2-factor total (Volume + Range). Recovery removed.
        score.total_score = (
            score.volume_ratio_score +
            score.range_intensity_score
        )
        
        return score

    # ═══════════════════════════════════════════════════════════════════════════
    # FILTERING
    # ═══════════════════════════════════════════════════════════════════════════
    
    def _apply_filters_with_detailed_logging(self, candidates: List[GapCandidate]) -> List[GapCandidate]:
        """Apply filters with Phase 1 style detailed logging."""
        logger.info("")
        logger.info("┌" + "─" * 98 + "┐")
        logger.info(f"│{'FILTER ANALYSIS — ' + str(len(candidates)) + ' CANDIDATES':^98}│")
        logger.info("├" + "─" * 16 + "┬" + "─" * 10 + "┬" + "─" * 12 + "┬" + "─" * 8 + "┬" + "─" * 8 + "┬" + "─" * 10 + "┬" + "─" * 12 + "┬" + "─" * 16 + "┤")
        logger.info(f"│ {'SYMBOL':<14} │ {'GAP %':>8} │ {'VOL BURST':>10} │ {'ADX':>6} │ {'RSI':>6} │ {'VOL RAT':>8} │ {'SENTIMENT':>10} │ {'RESULT':>14} │")
        logger.info("├" + "─" * 16 + "┼" + "─" * 10 + "┼" + "─" * 12 + "┼" + "─" * 8 + "┼" + "─" * 8 + "┼" + "─" * 10 + "┼" + "─" * 12 + "┼" + "─" * 16 + "┤")
        
        passed = []
        
        for candidate in candidates:
            passed_filter, reason = self._check_filters_v2(candidate)
            
            vb_score = candidate.volume_burst.total_score if candidate.volume_burst else 0
            sentiment_str = self.market_sentiment[:8] if self.market_sentiment else "N/A"
            
            if passed_filter:
                passed.append(candidate)
                status = "✅ PASS"
            else:
                status = "❌ FAIL"
            
            logger.info(
                f"│ {candidate.symbol:<14} "
                f"│ {candidate.gap_pct:>+7.2f}% "
                f"│ {vb_score:>9.0f}/50 "
                f"│ {candidate.adx:>5.1f} "
                f"│ {candidate.rsi:>5.1f} "
                f"│ {candidate.volume_ratio:>7.2f}x "
                f"│ {sentiment_str:>10} "
                f"│ {status:>14} │"
            )
            if not passed_filter:
                logger.info(f"│ {'':>14} │ {'Reason: ' + reason:<79} │")
        
        logger.info("└" + "─" * 16 + "┴" + "─" * 10 + "┴" + "─" * 12 + "┴" + "─" * 8 + "┴" + "─" * 8 + "┴" + "─" * 10 + "┴" + "─" * 12 + "┴" + "─" * 16 + "┘")
        logger.info(f"   📊 FILTER SUMMARY: {len(passed)}/{len(candidates)} passed | Sentiment: {self.market_sentiment}")
        logger.info("")
        
        return passed
    
    def _log_candidate_analysis(self, candidate: GapCandidate):
        """Log detailed candidate analysis in Phase 1 box style."""
        logger.info("")
        logger.info("┌" + "─" * 78 + "┐")
        logger.info(f"│{'CANDIDATE ANALYSIS: ' + candidate.symbol:^78}│")
        logger.info("├" + "─" * 78 + "┤")
        
        # Gap info
        gap_emoji = "📉" if candidate.gap_type == GapType.GAP_DOWN else "📈"
        logger.info(f"│ {gap_emoji} Gap: {candidate.gap_pct:+.2f}% ({candidate.gap_type.value})".ljust(79) + "│")
        logger.info(f"│    Prev Close: ₹{candidate.prev_close:.2f} → Open: ₹{candidate.open_price:.2f}".ljust(79) + "│")
        logger.info(f"│    Current: ₹{candidate.current_price:.2f}".ljust(79) + "│")
        
        logger.info("├" + "─" * 78 + "┤")
        
        # Volume Burst
        if candidate.volume_burst:
            vb = candidate.volume_burst
            logger.info(f"│ 📊 VOLUME BURST SCORE: {vb.total_score:.0f}/50".ljust(79) + "│")
            logger.info(f"│    A) Volume Ratio: {vb.volume_ratio:.2f}x → {vb.volume_ratio_score:.0f}/20 pts".ljust(79) + "│")
            logger.info(f"│    B) Range/ATR: {vb.range_vs_atr:.2f}x → {vb.range_intensity_score:.0f}/30 pts".ljust(79) + "│")
            logger.info(f"│    C) Recovery: {vb.recovery_pct:.1f}% (logged only, not scored v5.4.0)".ljust(79) + "│")
        
        logger.info("├" + "─" * 78 + "┤")
        
        # Indicators
        logger.info(f"│ 📈 INDICATORS".ljust(79) + "│")
        logger.info(f"│    RSI: {candidate.rsi:.1f} | ADX: {candidate.adx:.1f} | ATR: ₹{candidate.atr:.2f}".ljust(79) + "│")
        
        logger.info("├" + "─" * 78 + "┤")
        
        # Direction
        direction = candidate.get_direction()
        dir_emoji = "🟢" if direction == GapTradeDirection.BUY else "🔴"
        logger.info(f"│ {dir_emoji} DIRECTION: {direction.value}".ljust(79) + "│")
        
        logger.info("└" + "─" * 78 + "┘")
    
    def _calculate_atr_target_pct(self, candidate: GapCandidate) -> float:
        """
        DEPRECATED (v5.3.3): No longer called from _execute_entry().
        Smart TCAS design uses fixed TCAS_ACTIVATION_PCT (0.3%) instead.
        Kept for backward compatibility — do not delete.
        
        Original: Calculate ATR-scaled target percentage.
        """
        if candidate.atr <= 0 or candidate.current_price <= 0:
            logger.warning(f"{candidate.symbol}: ATR or price invalid, using fallback TARGET_PCT={self.config.TARGET_PCT}%")
            return self.config.TARGET_PCT
        
        atr_pct = (candidate.atr / candidate.current_price) * 100
        raw_target = atr_pct * self.config.ATR_TARGET_MULTIPLIER
        
        # Clamp to floor/ceiling
        target_pct = max(self.config.ATR_TARGET_MIN_PCT, min(raw_target, self.config.ATR_TARGET_MAX_PCT))
        
        logger.info(
            f"   📐 ATR Target: ATR ₹{candidate.atr:.2f} / ₹{candidate.current_price:.2f} = "
            f"{atr_pct:.2f}% × {self.config.ATR_TARGET_MULTIPLIER} = {raw_target:.2f}% → "
            f"clamped to {target_pct:.2f}%"
        )
        
        return target_pct

    def _classify_regime(self, candidate: GapCandidate) -> Tuple[str, str]:
        """
        P0 FIX #1: Regime Classifier — Detect momentum continuation vs mean reversion.
        
        Logic:
          GAP_DOWN + current_price < open → CONTINUATION (still falling, don't BUY)
          GAP_DOWN + current_price >= open → REVERSION (recovering, safe to BUY)
          GAP_UP + current_price > open → CONTINUATION (still rising, don't SHORT)
          GAP_UP + current_price <= open → REVERSION (fading, safe to SHORT)
        
        Returns:
            (regime, reason) — regime is 'CONTINUATION' or 'REVERSION'
        """
        price = candidate.current_price
        open_price = candidate.open_price
        
        if candidate.gap_type == GapType.GAP_DOWN:
            if price < open_price:
                pct_below = ((open_price - price) / open_price) * 100
                return "CONTINUATION", (
                    f"GAP_DOWN continuation: price ₹{price:.2f} < open ₹{open_price:.2f} "
                    f"({pct_below:.2f}% below open, still falling)"
                )
            else:
                pct_above = ((price - open_price) / open_price) * 100
                return "REVERSION", (
                    f"GAP_DOWN reverting: price ₹{price:.2f} >= open ₹{open_price:.2f} "
                    f"(+{pct_above:.2f}% above open, recovering)"
                )
        else:  # GAP_UP
            if price > open_price:
                pct_above = ((price - open_price) / open_price) * 100
                return "CONTINUATION", (
                    f"GAP_UP continuation: price ₹{price:.2f} > open ₹{open_price:.2f} "
                    f"(+{pct_above:.2f}% above open, still rising)"
                )
            else:
                pct_below = ((open_price - price) / open_price) * 100
                return "REVERSION", (
                    f"GAP_UP reverting: price ₹{price:.2f} <= open ₹{open_price:.2f} "
                    f"({pct_below:.2f}% below open, fading)"
                )

    def _check_filters_v2(self, candidate: GapCandidate) -> Tuple[bool, str]:
        """Check all filters for a candidate."""
        # ═══════════════════════════════════════════════════════════════
        # P0 FIX #1: REGIME CLASSIFIER — Must be FIRST filter
        # Blocks trading INTO momentum continuation
        # ═══════════════════════════════════════════════════════════════
        regime, regime_reason = self._classify_regime(candidate)
        if regime == "CONTINUATION":
            direction = "BUY" if candidate.gap_type == GapType.GAP_DOWN else "SHORT"
            return False, f"Regime CONTINUATION — blocked {direction}: {regime_reason}"
        
        # Volume Burst Score — INFO ONLY (v5.3.5: no longer blocks entry)
        if candidate.volume_burst:
            if not candidate.volume_burst.is_valid(self.config.MIN_VOLUME_BURST_SCORE):
                logger.info(f"  ℹ️  {candidate.symbol}: Volume Burst {candidate.volume_burst.total_score:.0f} < {self.config.MIN_VOLUME_BURST_SCORE} (info only, not blocking)")
        else:
            if candidate.volume_ratio < self.config.MIN_VOLUME_RATIO:
                logger.info(f"  ℹ️  {candidate.symbol}: Volume ratio {candidate.volume_ratio:.2f} < {self.config.MIN_VOLUME_RATIO} (info only, not blocking)")

        # ADX — skip filter if NaN (data fetch issue, not stock quality issue)
        if np.isnan(candidate.adx):
            logger.warning(f"  ⚠️  {candidate.symbol}: ADX is NaN — skipping ADX filter (pre-market data incomplete)")
        elif candidate.adx > self.config.MAX_ADX:
            # ADX too high — INFO ONLY (v5.3.5: no longer blocks entry)
            logger.info(f"  ℹ️  {candidate.symbol}: ADX {candidate.adx:.1f} > {self.config.MAX_ADX} (info only, not blocking)")
        
        # Sentiment filter
        if self.market_sentiment == "BEARISH" and candidate.gap_type == GapType.GAP_DOWN:
            # Bearish sentiment + gap down = risky to buy
            if candidate.gap_pct < -2.0:
                return False, "Bearish sentiment + large gap down (panic selling)"
        
        if self.market_sentiment == "BULLISH" and candidate.gap_type == GapType.GAP_UP:
            # Bullish sentiment + gap up = may continue higher
            if candidate.gap_pct > 2.0:
                return False, "Bullish sentiment + large gap up (momentum continuation)"
        
        return True, "PASSED"
    
    def _log_loop_funnel(self, loop_num: int, scanned: int, gaps: int, 
                         filtered: int, score: float, outcome: str):
        """Log a compact funnel summary for each loop iteration."""
        logger.info("")
        logger.info(f"   ┌─────────────────────────────────────────────────┐")
        logger.info(f"   │ LOOP {loop_num} FUNNEL SUMMARY                          │")
        logger.info(f"   ├─────────────────────────────────────────────────┤")
        logger.info(f"   │ Scanned:  {scanned:>4} stocks                          │")
        logger.info(f"   │ Gaps:     {gaps:>4} passed gap threshold     {'✅' if gaps > 0 else '❌'}       │")
        logger.info(f"   │ Filtered: {filtered:>4} passed all filters      {'✅' if filtered > 0 else '❌'}       │")
        if score > 0:
            logger.info(f"   │ Score:    {score:>4.0f}/100                       {'✅' if score >= 50 else '❌'}       │")
        logger.info(f"   │ Outcome:  {outcome:<37} │")
        logger.info(f"   └─────────────────────────────────────────────────┘")
        logger.info("")
    
    def _select_best_candidate(self, candidates: List[GapCandidate]) -> Optional[GapCandidate]:
        """Select best candidate based on composite score."""
        if not candidates:
            return None
        
        def score_candidate(c: GapCandidate) -> float:
            score = 0
            
            # Gap size (larger = better, up to a point)
            gap_score = min(abs(c.gap_pct) * 10, 30)
            score += gap_score
            
            # Volume Burst Score
            if c.volume_burst:
                score += c.volume_burst.total_score * 0.5
            
            # RSI extremity (more extreme = better)
            if c.gap_type == GapType.GAP_DOWN:
                # For gap down (BUY), lower RSI is better
                rsi_score = max(0, (40 - c.rsi))
            else:
                # For gap up (SELL), higher RSI is better
                rsi_score = max(0, (c.rsi - 60))
            score += rsi_score
            
            return score
        
        # Sort by score descending
        candidates.sort(key=score_candidate, reverse=True)
        
        return candidates[0]

    # ═══════════════════════════════════════════════════════════════════════════
    # v5.0.0: FLIGHT PLAN GENERATION
    # ═══════════════════════════════════════════════════════════════════════════
    
    def _generate_entry_flight_plan(self, candidate: GapCandidate) -> Dict:
        """
        v5.0.0: Generate entry flight plan using Phase 4's FlightPlanGenerator.
        
        For intraday, we focus on shorter timeframes (15min, 1H).
        """
        logger.info("")
        logger.info("✈️ GENERATING ENTRY FLIGHT PLAN...")
        
        try:
            # Try to use Phase 4's FlightPlanGenerator
            if self.phase4 and hasattr(self.phase4, 'flight_plan_generator'):
                generator = self.phase4.flight_plan_generator
                
                # Generate short-term flight plan
                flight_plan = generator.generate(
                    symbol=candidate.symbol,
                    entry_price=candidate.current_price,
                    stop_price=candidate.current_price * (0.985 if candidate.gap_type == GapType.GAP_DOWN else 1.015),
                    target_price=candidate.current_price * (1.003 if candidate.gap_type == GapType.GAP_DOWN else 0.997)
                )
                
                if flight_plan:
                    logger.info(f"   ✅ Flight Plan generated")
                    logger.info(f"   Truth Score: {flight_plan.overall_truth_score:.0f}%")
                    logger.info(f"   Direction: {flight_plan.overall_direction}")
                    return flight_plan.to_dict() if hasattr(flight_plan, 'to_dict') else {}
            
            # Fallback: Create simple flight plan
            logger.info("   ℹ️ Using simplified flight plan (Phase 4 not available)")
            
            direction = "BULLISH" if candidate.gap_type == GapType.GAP_DOWN else "BEARISH"
            
            simple_plan = {
                'symbol': candidate.symbol,
                'overall_truth_score': 60,
                'overall_direction': direction,
                'timeframes': {
                    '15min': {'score': 65, 'direction': direction},
                    '1H': {'score': 55, 'direction': direction}
                },
                'indicators': {
                    'rsi': candidate.rsi,
                    'adx': candidate.adx,
                    'gap_pct': candidate.gap_pct,
                    'volume_burst': candidate.volume_burst.total_score if candidate.volume_burst else 0
                },
                'recommendation': 'ENTRY_APPROVED' if candidate.volume_burst and candidate.volume_burst.total_score >= 30 else 'CAUTIOUS_ENTRY'
            }
            
            return simple_plan
            
        except Exception as e:
            logger.error(f"Flight plan generation error: {e}")
            return {'error': str(e)}

    # ═══════════════════════════════════════════════════════════════════════════
    # v5.0.0: CHATGPT ENTRY APPROVAL (kept for backward compat, NOT used in v5.1.0 loop)
    # ═══════════════════════════════════════════════════════════════════════════
    
    def _get_chatgpt_entry_approval(self, candidate: GapCandidate, flight_plan: Dict) -> Dict:
        """
        v5.0.0: Get ChatGPT approval for entry decision.
        
        NOTE (v5.1.0): This method is NO LONGER called in the main loop.
        The 3-loop architecture uses execute-first with _send_async_chatgpt_log().
        Kept for backward compatibility and potential direct-call use.
        
        Returns:
            {
                'approved': bool,
                'confidence': float (0-1),
                'reasoning': str,
                'risk_assessment': str
            }
        """
        logger.info("")
        logger.info("🤖 REQUESTING CHATGPT ENTRY APPROVAL...")
        
        # If no ChatGPT available, auto-approve with medium confidence
        if not self.chatgpt:
            logger.info("   ℹ️ ChatGPT not available - auto-approving with 70% confidence")
            return {
                'approved': True,
                'confidence': 0.70,
                'reasoning': 'Auto-approved (ChatGPT not available)',
                'risk_assessment': 'MEDIUM'
            }
        
        try:
            # Build prompt
            direction = candidate.get_direction()
            vb = candidate.volume_burst
            
            prompt = f"""🎯 PHASE 5 GAP ENTRY DECISION

CANDIDATE: {candidate.symbol}
Gap: {candidate.gap_pct:+.2f}% ({candidate.gap_type.value})
Direction: {direction.value}
Entry Price: ₹{candidate.current_price:.2f}

FLIGHT PLAN SUMMARY:
• Truth Score: {flight_plan.get('overall_truth_score', 'N/A')}% 
• Direction: {flight_plan.get('overall_direction', 'N/A')}
• Recommendation: {flight_plan.get('recommendation', 'N/A')}

VOLUME BURST ANALYSIS:
• Total Score: {vb.total_score:.0f}/50
• Volume Ratio: {vb.volume_ratio:.2f}x avg
• Range/ATR: {vb.range_vs_atr:.2f}x
• Recovery: {vb.recovery_pct:.1f}%

INDICATORS:
• RSI: {candidate.rsi:.1f}
• ADX: {candidate.adx:.1f}

MARKET SENTIMENT: {self.market_sentiment}

RISK CONTEXT:
• Position: MIS (max hold until 12:00 PM)
• Stop: Phase 4 TCAS will manage dynamically
• Target: Phase 4 ILS will manage dynamically

QUESTION: Should we ENTER this {direction.value} trade?

Respond ONLY with valid JSON:
{{"decision": "APPROVE" or "REJECT", "confidence": 0.0-1.0, "reasoning": "brief reason", "risk_assessment": "LOW/MEDIUM/HIGH"}}"""

            # Call ChatGPT
            response = self.chatgpt.get_decision(prompt)
            
            if response:
                # Parse response
                try:
                    # Try to extract JSON from response
                    import re
                    json_match = re.search(r'\{[^{}]+\}', response)
                    if json_match:
                        result = json.loads(json_match.group())
                        
                        approved = result.get('decision', '').upper() == 'APPROVE'
                        confidence = float(result.get('confidence', 0.5))
                        
                        # Check minimum confidence
                        if approved and confidence < self.config.CHATGPT_MIN_CONFIDENCE:
                            approved = False
                            result['reasoning'] = f"Confidence {confidence:.0%} below threshold {self.config.CHATGPT_MIN_CONFIDENCE:.0%}"
                        
                        logger.info(f"   Decision: {'APPROVED' if approved else 'REJECTED'}")
                        logger.info(f"   Confidence: {confidence:.0%}")
                        logger.info(f"   Reasoning: {result.get('reasoning', 'N/A')}")
                        
                        return {
                            'approved': approved,
                            'confidence': confidence,
                            'reasoning': result.get('reasoning', ''),
                            'risk_assessment': result.get('risk_assessment', 'MEDIUM')
                        }
                except json.JSONDecodeError:
                    logger.warning(f"   Failed to parse ChatGPT response: {response[:100]}")
            
            # Fallback: auto-approve with medium confidence
            logger.warning("   ChatGPT response unclear - auto-approving with 65% confidence")
            return {
                'approved': True,
                'confidence': 0.65,
                'reasoning': 'Auto-approved (ChatGPT response unclear)',
                'risk_assessment': 'MEDIUM'
            }
            
        except Exception as e:
            logger.error(f"ChatGPT approval error: {e}")
            return {
                'approved': True,
                'confidence': 0.60,
                'reasoning': f'Auto-approved (error: {str(e)[:50]})',
                'risk_assessment': 'MEDIUM'
            }

    # ═══════════════════════════════════════════════════════════════════════════
    # POSITION SIZING
    # ═══════════════════════════════════════════════════════════════════════════
    
    def _calculate_position_size_with_leverage(self, candidate: GapCandidate) -> Dict:
        """Calculate position size using leverage-aware sizing."""
        try:
            # Get available capital
            if self.capital_manager:
                available_capital = self.capital_manager.get_available()
            else:
                available_capital = self.config.MAX_POSITION_VALUE
            
            # Apply capital percentage limit
            max_position = min(
                available_capital * self.config.MAX_CAPITAL_PCT,
                self.config.MAX_POSITION_VALUE
            )
            
            # Get margin per share
            margin_info = self._get_margin_per_share(candidate.symbol, candidate.current_price)
            margin_per_share = margin_info.get('margin_per_share', candidate.current_price)
            effective_leverage = margin_info.get('effective_leverage', 1.0)
            
            # Calculate quantity
            quantity = int(max_position / margin_per_share)
            
            # Ensure at least 1 share
            quantity = max(1, quantity)
            
            return {
                'quantity': quantity,
                'margin_per_share': margin_per_share,
                'effective_leverage': effective_leverage,
                'total_margin': margin_per_share * quantity,
                'position_value': candidate.current_price * quantity
            }
            
        except Exception as e:
            logger.error(f"Position sizing error: {e}")
            return {'quantity': 0, 'error': str(e)}
    
    def _get_margin_per_share(self, symbol: str, price: float) -> Dict:
        """Get margin required per share from Zerodha API."""
        try:
            # Try Zerodha Margin API
            direction = "BUY"  # Default
            
            margins = self.kite.order_margins([{
                "exchange": "NSE",
                "tradingsymbol": symbol,
                "transaction_type": direction,
                "variety": "regular",
                "product": "MIS",
                "order_type": "MARKET",
                "quantity": 1,
                "price": price
            }])
            
            if margins and len(margins) > 0:
                margin_info = margins[0]
                total_margin = margin_info.get('total', price)
                
                # Apply 80% safety buffer
                margin_with_buffer = total_margin * 1.25
                
                effective_leverage = price / margin_with_buffer if margin_with_buffer > 0 else 1.0
                
                return {
                    'margin_per_share': margin_with_buffer,
                    'effective_leverage': effective_leverage,
                    'raw_margin': total_margin
                }
            
        except Exception as e:
            logger.debug(f"Margin API error for {symbol}: {e}")
        
        # Fallback: assume 20% margin (5x leverage)
        return {
            'margin_per_share': price * 0.20,
            'effective_leverage': 5.0,
            'raw_margin': price * 0.20
        }

    # ═══════════════════════════════════════════════════════════════════════════
    # ENTRY EXECUTION
    # ═══════════════════════════════════════════════════════════════════════════
    
    def _execute_entry(self, candidate: GapCandidate, sizing_result: Dict,
                       flight_plan: Dict, approval: Dict) -> Optional[GapTrade]:
        """
        Execute entry order.
        
        v5.0.0: No GTT placement - Phase 4 will handle stops/targets.
        """
        try:
            direction = candidate.get_direction()
            transaction_type = "BUY" if direction == GapTradeDirection.BUY else "SELL"
            quantity = sizing_result['quantity']
            entry_price = candidate.current_price

            # ═══════════════════════════════════════════════════════════════
            # 🧠 Phase 9 Fund Manager Gate (v1.1.0) — gap trading entry gate
            # Uses gray-zone filter; applies size_adjustment and operation_mode
            # ═══════════════════════════════════════════════════════════════
            fm = getattr(self, 'fund_manager', None)
            if fm and getattr(self.config, 'PH9_ENTRY_GATE_ENABLED', False):
                try:
                    # HALT check — operation_mode override
                    op_mode = getattr(fm, 'todays_regime', 'NORMAL') or 'NORMAL'
                    if op_mode == 'HALT':
                        logger.warning(f"⛔ PH9 HALT mode — rejecting {candidate.symbol}")
                        return None

                    signal_dict = {
                        'symbol': candidate.symbol,
                        'direction': transaction_type,
                        'source': 'PHASE5_GAP',
                        'composite_score': getattr(candidate, 'composite_score', None),
                        'gap_pct': getattr(candidate, 'gap_pct', None),
                        'rsi': getattr(candidate, 'rsi', None),
                        'atr': getattr(candidate, 'atr', None),
                    }
                    portfolio_state = {'positions': {}}
                    if self.orchestrator:
                        portfolio_state['positions'] = dict(
                            getattr(self.orchestrator, '_central_positions', {}))

                    fm_result = fm.approve_entry(
                        signal=signal_dict,
                        current_price=entry_price,
                        quantity=quantity,
                        portfolio_state=portfolio_state,
                    )
                    logger.info(f"🧠 PH9 GATE: {candidate.symbol} "
                                f"{'APPROVED' if fm_result['approved'] else 'BLOCKED'} "
                                f"({fm_result.get('gate', '?')}) — "
                                f"{fm_result.get('reasoning', '')[:120]}")
                    if not fm_result['approved']:
                        return None

                    # Apply size_adjustment (respects CAUTIOUS mode throttling)
                    size_adj = float(fm_result.get('size_adjustment', 1.0) or 1.0)
                    if op_mode == 'CAUTIOUS':
                        size_adj = min(size_adj, 0.5)
                    if size_adj != 1.0:
                        old_qty = quantity
                        quantity = max(1, int(quantity * size_adj))
                        sizing_result['quantity'] = quantity
                        logger.info(f"   📐 PH9 size: {old_qty} → {quantity} ({size_adj:.2f}x)")
                except Exception as _fm_e:
                    logger.error(f"PH9 gate error (Phase 5): {_fm_e} — proceeding")

            
            # v5.3.3: Smart TCAS Scalp Design
            # - No hard target cap (set aspirational 5% so Phase 4 display works)
            # - Stop: raw 0.5× ATR (no clamping) as safety net
            # - TCAS activation at +0.3% handled by Phase 4 TIER1
            tcas_pct = self.config.TCAS_ACTIVATION_PCT  # 0.3%
            # v5.6.0: widen stop in elevated VIX; base is 0.5× ATR
            stop_distance = candidate.atr * self.config.STOP_ATR_MULTIPLIER * self._vix_stop_mult
            
            if direction == GapTradeDirection.BUY:
                target_price = entry_price * 1.05   # Aspirational (Phase 4 TCAS manages real exit)
                tcas_activation_price = entry_price * (1 + tcas_pct / 100)
                stop_price = entry_price - stop_distance
            else:
                target_price = entry_price * 0.95   # Aspirational
                tcas_activation_price = entry_price * (1 - tcas_pct / 100)
                stop_price = entry_price + stop_distance
            
            target_price = round(target_price * 10) / 10
            stop_price = round(stop_price * 10) / 10
            
            logger.info(f"📤 Placing {transaction_type}: {candidate.symbol} x {quantity}")

            # Place order (paper mode wrapper)
            order_id = self._place_order(
                tradingsymbol=candidate.symbol,
                exchange="NSE",
                transaction_type=transaction_type,
                quantity=quantity,
                product="MIS",
                order_type="MARKET",
                variety="regular"
            )

            logger.info(f"✅ Order placed. ID: {order_id}")

            # Verify fill
            if self._paper_mode:
                try:
                    quote = self.kite.quote([f"NSE:{candidate.symbol}"])
                    sim_price = quote.get(f"NSE:{candidate.symbol}", {}).get('last_price', entry_price)
                except Exception:
                    sim_price = entry_price
                fill_info = {'filled': True, 'status': 'COMPLETE', 'average_price': sim_price, 'filled_qty': quantity}
            else:
                fill_info = self._verify_order_fill(order_id, candidate.symbol, quantity)
            
            if not fill_info['filled']:
                logger.error(f"❌ Order not filled! Status: {fill_info['status']}")
                return None
            
            actual_fill_price = fill_info['average_price']
            logger.info(f"✅ Filled @ ₹{actual_fill_price:.2f}")
            
            # v5.3.3: Recalculate with actual fill price (Smart TCAS design)
            if direction == GapTradeDirection.BUY:
                target_price = actual_fill_price * 1.05   # Aspirational
                tcas_activation_price = actual_fill_price * (1 + tcas_pct / 100)
                stop_price = actual_fill_price - stop_distance
            else:
                target_price = actual_fill_price * 0.95   # Aspirational
                tcas_activation_price = actual_fill_price * (1 - tcas_pct / 100)
                stop_price = actual_fill_price + stop_distance
            
            target_price = round(target_price * 10) / 10
            stop_price = round(stop_price * 10) / 10
            
            # v5.0.0: NO GTT PLACEMENT - Phase 4 handles this
            logger.info("   ℹ️ No GTT placed - Phase 4 will manage stops/targets")
            
            # Notify Capital Manager
            actual_margin_used = sizing_result['margin_per_share'] * quantity
            
            if self.capital_manager:
                self.capital_manager.deploy(
                    symbol=candidate.symbol,
                    amount=actual_margin_used,
                    quantity=quantity,
                    avg_price=actual_fill_price,
                    source='PHASE5_GAP',
                    product='MIS'
                )
            
            # Create trade record
            trade = GapTrade(
                symbol=candidate.symbol,
                direction=direction,
                entry_price=actual_fill_price,
                entry_time=datetime.now(),
                quantity=quantity,
                target_price=target_price,
                stop_price=stop_price,
                target_pct=tcas_pct if direction == GapTradeDirection.BUY else -tcas_pct,
                stop_pct=-(stop_distance / actual_fill_price) * 100 if direction == GapTradeDirection.BUY else (stop_distance / actual_fill_price) * 100,
                gap_pct=candidate.gap_pct,
                status=GapTradeStatus.ENTERED,
                order_id=str(order_id),
                margin_used=actual_margin_used,
                effective_leverage=sizing_result['effective_leverage'],
                position_value=actual_fill_price * quantity,
                volume_burst_score=candidate.volume_burst.total_score if candidate.volume_burst else 0,
                flight_plan=flight_plan,
                chatgpt_approval=approval,
                atr=candidate.atr  # P0 FIX: Pass ATR for Phase 4 TCAS/ILS
            )
            
            # Send entry notification
            self._notify_entry(candidate, direction, actual_fill_price, quantity,
                              target_price, stop_price, actual_margin_used,
                              sizing_result['effective_leverage'])

            # PAPER MODE: log entry to paper_trade_logger → Excel
            # Dual-check config directly — _place_order syncs self._paper_mode but runs before this
            if self._paper_mode or getattr(self.config, 'PH5_PAPER_MODE', False):
                try:
                    from paper_trade_logger import log_paper_entry
                    _txn = "BUY" if direction == GapTradeDirection.BUY else "SELL"
                    _logger_id = log_paper_entry(
                        phase="PH5_INTRA",
                        symbol=candidate.symbol,
                        direction=_txn,
                        entry_price=actual_fill_price,
                        quantity=quantity,
                        stop_loss=stop_price,
                        target=target_price,
                        strategy="Gap Intraday",
                        score=getattr(candidate, 'volume_burst', None) and candidate.volume_burst.total_score or 0,
                        regime=getattr(self, 'market_sentiment', ''),
                        notes=f"Gap: {candidate.gap_pct:+.2f}%"
                    )
                    trade.paper_logger_id = _logger_id
                    logger.info(f"   📊 PAPER LOG: entry recorded → {_logger_id}")
                except Exception as _le:
                    logger.warning(f"   ⚠️ paper_trade_logger entry failed: {_le}")

            return trade
            
        except Exception as e:
            logger.error(f"Entry execution error: {e}")
            logger.exception(e)
            return None
    
    def _verify_order_fill(self, order_id: str, symbol: str, expected_qty: int,
                          max_wait: int = 10) -> Dict:
        """Verify order fill with broker."""
        logger.info(f"🔍 Verifying order fill...")
        start_time = time.time()
        
        while time.time() - start_time < max_wait:
            try:
                order_history = self.kite.order_history(order_id)
                if order_history:
                    latest = order_history[-1]
                    status = latest.get('status', '')
                    
                    if status == 'COMPLETE':
                        return {
                            'filled': True,
                            'status': status,
                            'average_price': latest.get('average_price', 0),
                            'filled_qty': latest.get('filled_quantity', 0)
                        }
                    elif status in ['REJECTED', 'CANCELLED']:
                        return {'filled': False, 'status': status, 'average_price': 0, 'filled_qty': 0}
                time.sleep(0.5)
            except Exception as e:
                logger.warning(f"Order verification error: {e}")
                time.sleep(0.5)
        
        return {'filled': False, 'status': 'TIMEOUT', 'average_price': 0, 'filled_qty': 0}

    # ═══════════════════════════════════════════════════════════════════════════

    # ───────────────────────────────────────────────────────────────────────────
    # NOTIFICATION HELPERS
    # ───────────────────────────────────────────────────────────────────────────

    def _get_instrument_token(self, symbol: str) -> Optional[int]:
        """Return KiteConnect instrument token for symbol from cached map."""
        token = self._instrument_map.get(symbol)
        if token is None:
            logger.warning(f"_get_instrument_token: '{symbol}' not in instrument map")
        return token

    def _notify_error(self, msg: str) -> None:
        """Send strategy-level error alert via Telegram + log."""
        logger.error(f"[Phase5] Strategy error: {msg}")
        try:
            if self.telegram:
                self.telegram.send_message(
                    f"🚨 PHASE 5 ERROR\n\n{msg}\n\nCheck logs immediately."
                )
        except Exception as te:
            logger.warning(f"_notify_error telegram failed: {te}")

    def _notify_skip_insufficient_capital(self, best, sizing_result: dict) -> None:
        """Log and optionally telegram when position sizing returns qty=0."""
        symbol = getattr(best, 'symbol', '?')
        gap    = getattr(best, 'gap_pct', 0.0)
        reason = sizing_result.get('reason', 'qty=0')
        logger.warning(
            f"   ⏭ SKIP {symbol} — insufficient capital: {reason} "
            f"(gap {gap:+.2f}%, available ₹{sizing_result.get('available_capital', 0):,.0f})"
        )
        try:
            if self.telegram:
                self.telegram.send_message(
                    f"⏭ PHASE 5 SKIP — {symbol}\n"
                    f"Gap: {gap:+.2f}%\n"
                    f"Reason: insufficient capital ({reason})\n"
                    f"Available: ₹{sizing_result.get('available_capital', 0):,.0f}"
                )
        except Exception as te:
            logger.warning(f"_notify_skip_insufficient_capital telegram failed: {te}")

    def _notify_entry(self, candidate, direction, fill_price: float, qty: int,
                      target: float, stop: float, margin: float, leverage: float) -> None:
        """Send Telegram entry notification card."""
        symbol    = getattr(candidate, 'symbol', '?')
        gap_pct   = getattr(candidate, 'gap_pct', 0.0)
        score     = candidate.volume_burst.total_score if getattr(candidate, 'volume_burst', None) else 0
        dir_str   = direction.value if hasattr(direction, 'value') else str(direction)
        dir_emoji = "🟢" if dir_str == "BUY" else "🔴"
        rr        = round(abs(target - fill_price) / abs(fill_price - stop), 2) if abs(fill_price - stop) > 0 else 0

        logger.info(
            f"✅ ENTRY {symbol} {dir_str} {qty}x @ ₹{fill_price:.2f} | "
            f"T ₹{target:.2f} | SL ₹{stop:.2f} | R:R {rr:.1f} | "
            f"Margin ₹{margin:,.0f} | Lev {leverage:.1f}x"
        )
        try:
            if self.telegram:
                self.telegram.send_message(
                    f"{dir_emoji} PHASE 5 ENTRY\n\n"
                    f"Symbol : {symbol}\n"
                    f"Dir    : {dir_str}\n"
                    f"Gap    : {gap_pct:+.2f}%\n"
                    f"Fill   : ₹{fill_price:.2f}\n"
                    f"Qty    : {qty}\n"
                    f"Target : ₹{target:.2f}\n"
                    f"Stop   : ₹{stop:.2f}\n"
                    f"R:R    : {rr:.1f}\n"
                    f"Margin : ₹{margin:,.0f}\n"
                    f"Lev    : {leverage:.1f}x\n"
                    f"VB Score: {score:.0f}/50"
                )
        except Exception as te:
            logger.warning(f"_notify_entry telegram failed: {te}")

    # ═══════════════════════════════════════════════════════════════════════════════
    # PHASE 4 HANDOFF
    # ═══════════════════════════════════════════════════════════════════════════════

    def _handoff_to_phase4(self, trade) -> bool:
        """Hand off executed GapTrade to Phase 4 via add_phase5_position().

        Uses the purpose-built add_phase5_position() entry point which correctly
        initialises all Smart TCAS fields, monitoring tier, exit mode, and GTT
        paper-mode gates.  Calling on_position_opened() directly bypasses that
        setup and leaves smart_tcas_enabled=False, breaking CHECK 3.7 (stale gap),
        CHECK 1.5 (hard exit time), and the 0.3 % TCAS activation threshold.
        """
        if not self.phase4:
            logger.warning("Phase 4 manager not attached — position unmonitored")
            return False
        try:
            is_paper = bool(
                self._paper_mode
                or getattr(self.config, 'PH5_PAPER_MODE', False)
                or getattr(self.config, 'MASTER_PAPER_MODE', False)
            )
            # Phase 4 TCAS uses 'LONG'/'SHORT'
            direction_ph4 = 'LONG' if trade.direction.value == 'BUY' else 'SHORT'

            # hard_exit_time from config — passed as HH:MM:SS string so Phase 4
            # can parse it back to a time object via strptime (CHECK 1.5)
            hard_exit_str = None
            _het = getattr(self.config, 'HARD_EXIT_TIME', None)
            if _het:
                try:
                    hard_exit_str = _het.strftime('%H:%M:%S')
                except Exception:
                    hard_exit_str = str(_het)

            position_data = {
                # ── Core identity ──────────────────────────────────────────
                'symbol':             trade.symbol,
                'direction':          direction_ph4,
                'entry_price':        trade.entry_price,
                'stop_price':         trade.stop_price,
                'target_price':       trade.target_price,
                'quantity':           trade.quantity,
                'order_id':           trade.order_id,
                'entry_time':         trade.entry_time.isoformat(),
                'product':            'MIS',
                'exchange':           'NSE',
                'source':             'PHASE5_GAP',
                'monitoring_tier':    'TIER_1',
                'exit_mode':          'FAST_TECHNICAL',
                'max_hold_minutes':   getattr(self.config, 'MAX_HOLD_MINUTES', 25),

                # ── Risk data ──────────────────────────────────────────────
                'atr':                trade.atr,
                'gap_pct':            trade.gap_pct,
                'target_pct':         trade.target_pct,
                'stop_pct':           trade.stop_pct,
                'margin_used':        trade.margin_used,
                'effective_leverage': trade.effective_leverage,
                'volume_burst_score': trade.volume_burst_score,

                # ── Smart TCAS scalp flags (v5.9.0 FIX) ───────────────────
                # Without these Phase 4 defaults smart_tcas_enabled=False and:
                #   • TCAS activates at 0.5% instead of configured 0.3%
                #   • CHECK 3.7 STALE_GAP never fires
                #   • CHECK 1.5 hard exit time is ignored
                'smart_tcas_enabled':  True,
                'tcas_activation_pct': getattr(self.config, 'TCAS_ACTIVATION_PCT', 0.3),
                'hard_exit_time':      hard_exit_str,

                # ── Phase 5 metadata ──────────────────────────
                'tier_used':          trade.tier_used,
                'loop_number':        trade.loop_number,
                'flight_plan':        trade.flight_plan or {},
                'chatgpt_approval':   trade.chatgpt_approval or {},

                # ── Paper mode ──────────────────────────
                'is_paper_trade':     is_paper,
                'paper_logger_id':    trade.paper_logger_id,
                'phase':              'PH5_INTRA',
            }

            # Use the dedicated Phase 5 handoff entry point — not on_position_opened()
            if hasattr(self.phase4, 'add_phase5_position'):
                success = self.phase4.add_phase5_position(position_data)
            else:
                # Fallback for older Phase 4 builds
                self.phase4.on_position_opened(position_data,
                    {'source': 'PH5_INTRA', 'gap_pct': trade.gap_pct})
                success = True

            if success:
                tag = "PAPER" if is_paper else "LIVE"
                logger.info(
                    f"✅ Handoff → Phase 4 [{tag}] via add_phase5_position: "
                    f"{trade.symbol} {direction_ph4} @ ₹{trade.entry_price:.2f} | "
                    f"smart_tcas=ON tcas_act={getattr(self.config, 'TCAS_ACTIVATION_PCT', 0.3)}% "
                    f"hard_exit={hard_exit_str}"
                )
            return bool(success)

        except Exception as e:
            logger.error(f"❌ Phase 4 handoff error {trade.symbol}: {e}")
            logger.exception(e)
            return False

    # ═════════════════════════════════════════════════════════════════════════════════
    # PAPER TRADING MODE
    # ═════════════════════════════════════════════════════════════════════════════════

    def _place_order(self, **order_params) -> str:
        """Wrapper: routes to paper or live order placement."""
        self._paper_mode = bool(getattr(self.config, 'PH5_PAPER_MODE', self._paper_mode) or getattr(self.config, 'MASTER_PAPER_MODE', False))
        if self._paper_mode:
            return self._place_paper_order(order_params)
        return self.kite.place_order(
            variety=order_params.get('variety', 'regular'),
            exchange=order_params.get('exchange', 'NSE'),
            tradingsymbol=order_params.get('tradingsymbol'),
            transaction_type=order_params.get('transaction_type'),
            quantity=order_params.get('quantity'),
            product=order_params.get('product', 'MIS'),
            order_type=order_params.get('order_type', 'MARKET'),
            market_protection=-1,
        )

    def _place_paper_order(self, params: dict) -> str:
        """Simulate order placement. Returns paper order ID."""
        import uuid
        paper_id = f"PAPER_{uuid.uuid4().hex[:8].upper()}"
        symbol = params.get('tradingsymbol', '???')
        txn    = params.get('transaction_type', '???')
        qty    = params.get('quantity', 0)
        try:
            quote     = self.kite.quote([f"NSE:{symbol}"])
            sim_price = quote.get(f"NSE:{symbol}", {}).get('last_price', 0)
        except Exception:
            sim_price = 0
        price_str = f"₹{sim_price:.2f}" if sim_price else "MARKET"
        logger.info(f"📝 PAPER ORDER: {txn} {symbol} x{qty} @ {price_str} → {paper_id}")
        self._paper_trades.append({
            'order_id': paper_id, 'symbol': symbol, 'txn': txn,
            'qty': qty, 'sim_price': sim_price, 'mode': 'PAPER'
        })
        return paper_id
