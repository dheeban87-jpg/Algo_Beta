"""
PHASE 5: GAP STRATEGY v4.10.0 - FALLING KNIFE PROTECTION + BUG FIXES
═══════════════════════════════════════════════════════════════════════════════

🎯 PURPOSE:
   Capture gap-up/gap-down reversions in the first 25 minutes of market open.
   This is a SEPARATE strategy from V-Recovery, running 09:20-09:45 AM.

📊 STRATEGY LOGIC:
   Gap Down detected → BUY (expecting bounce/fill)
   Gap Up detected   → SELL (expecting fade/fill)
   
   Target: 0.3% profit (quick scalp)
   Stop: 0.5x ATR (dynamic per stock)
   
🔧 v4.10.0 UPDATES (2026-02-06): POLICYBZR POST-MORTEM FIXES
   ═══════════════════════════════════════════════════════════════════════════
   
   🔴 BUG FIX 1: RECOVERY CALCULATION (CRITICAL)
      - OLD: Used range_from_open = (open - low), giving 100% when current >= open
      - NEW: Uses full_range = (high - low), true recovery from low to high
      - Impact: POLICYBZR showed 100% recovery but was actually ~45%
   
   🔴 BUG FIX 2: CAPITAL MANAGER DEPLOY CALL
      - OLD: deploy(symbol, amount, trade_type='GAP_STRATEGY') → CRASH
      - NEW: deploy(symbol, amount, quantity, avg_price) → WORKS
      - Impact: Position was created but not tracked, causing state drift
   
   🟡 NEW FILTER 1: DAILY TREND CHECK
      - Before entering, check if price is in daily downtrend
      - If price < EMA5 daily AND RSI < 35 daily → SKIP (falling knife)
   
   🟡 NEW FILTER 2: NIFTY REGIME CHECK
      - If NIFTY is also gapping down >1%, broad market weakness
      - Skip gap-down BUY entries during market-wide selloffs
   
   🟡 NEW FILTER 3: ADX THRESHOLD TIGHTENED
      - OLD: ADX <= 25 (borderline trending allowed)
      - NEW: ADX <= 20 (only low-trend stocks for mean reversion)
   
   🟢 NEW: PHASE 4 PRE-VALIDATION
      - Before entry, ask Phase 4's TruthPredictor opinion
      - If Phase 4 says BEARISH (confidence > 60%), SKIP entry

Author: Dheebanraj
Version: 4.10.0
Date: 2026-02-06
"""

import logging
import time
import math
import pandas as pd
import numpy as np
from datetime import datetime, time as dt_time, timedelta
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass
from enum import Enum

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

logger = logging.getLogger('Phase5_GapStrategy')


# ═══════════════════════════════════════════════════════════════════════════════
# ENUMS AND DATA CLASSES
# ═══════════════════════════════════════════════════════════════════════════════

class GapType(Enum):
    GAP_DOWN = "GAP_DOWN"
    GAP_UP = "GAP_UP"
    NO_GAP = "NO_GAP"

class GapTradeDirection(Enum):
    BUY = "BUY"
    SELL = "SELL"

class GapTradeStatus(Enum):
    ENTERED = "ENTERED"
    TARGET_HIT = "TARGET_HIT"
    STOP_HIT = "STOP_HIT"
    TIME_EXIT = "TIME_EXIT"
    HANDED_OFF = "HANDED_OFF"


@dataclass
class VolumeBurstScore:
    todays_volume: int
    daily_avg_volume: int
    expected_volume: int
    volume_ratio: float
    volume_score: int
    todays_range: float
    atr: float
    range_atr_ratio: float
    range_score: int
    open_price: float
    low_price: float
    high_price: float
    current_price: float
    recovery_pct: float
    recovery_score: int
    total_score: int
    passed: bool


@dataclass 
class DailyTrendAnalysis:
    daily_rsi: float
    daily_ema5: float
    daily_ema20: float
    current_price: float
    price_vs_ema5_pct: float
    is_downtrend: bool
    is_oversold_falling: bool
    trend_score: int
    warning: str


@dataclass
class GapCandidate:
    symbol: str
    gap_pct: float
    gap_type: GapType
    prev_close: float
    open_price: float
    high_price: float
    low_price: float
    current_price: float
    volume: int
    avg_volume: int
    atr: float
    adx: float
    volume_burst_score: Optional[VolumeBurstScore] = None
    daily_trend: Optional[DailyTrendAnalysis] = None
    score: float = 0.0
    finbert_sentiment: str = "NEUTRAL"
    finbert_aligned: bool = False
    filters_passed: bool = False
    filter_reason: str = ""


@dataclass
class GapTrade:
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
    status: GapTradeStatus = GapTradeStatus.ENTERED
    exit_price: float = 0.0
    exit_time: Optional[datetime] = None
    pnl: float = 0.0
    pnl_pct: float = 0.0
    breakeven_trailed: bool = False
    order_id: str = ""
    exit_order_id: str = ""
    gtt_id: Optional[str] = None
    margin_used: float = 0.0
    effective_leverage: float = 1.0
    position_value: float = 0.0
    paper_logger_id: Optional[str] = None   # paper_trade_logger.py trade ID (paper mode only)


@dataclass
class GapStrategyConfig:
    SCAN_START_TIME: dt_time = dt_time(9, 18)
    ENTRY_START_TIME: dt_time = dt_time(9, 20)
    BREAKEVEN_TRAIL_TIME: dt_time = dt_time(9, 40)
    MANDATORY_EXIT_TIME: dt_time = dt_time(9, 45)
    PHASE1_START_TIME: dt_time = dt_time(9, 50)
    
    GAP_THRESHOLD_PRIORITY_1: float = 1.5
    GAP_THRESHOLD_PRIORITY_2: float = 1.0
    GAP_THRESHOLD_PRIORITY_3: float = 0.75
    
    TARGET_PCT: float = 0.3
    STOP_ATR_MULTIPLIER: float = 0.5
    MIN_STOP_PCT: float = 0.5  # Was 0.3 — 0.5% minimum stop distance
    MAX_STOP_PCT: float = 1.0
    
    PHASE5_MAX_CAPITAL: float = 7000
    PHASE5_MIN_CAPITAL: float = 1000
    USE_LEVERAGE: bool = True
    LEVERAGE_SAFETY_BUFFER: float = 0.80
    DEFAULT_LEVERAGE: float = 5.0
    MARGIN_API_TIMEOUT: float = 2.0
    
    VOLUME_BURST_MIN_SCORE: int = 60
    OPENING_VOLUME_TIME_FRACTION: float = 0.03
    
    # v4.10.0: IMPROVED FILTERS
    MAX_ADX: float = 20  # Tightened from 25
    MIN_RECOVERY_PCT: float = 50.0
    
    DAILY_TREND_FILTER_ENABLED: bool = True
    DAILY_RSI_OVERSOLD_THRESHOLD: float = 35
    DAILY_RSI_FALLING_KNIFE_THRESHOLD: float = 30
    
    NIFTY_REGIME_FILTER_ENABLED: bool = True
    NIFTY_GAP_THRESHOLD: float = 1.0
    
    PHASE4_PREVALIDATION_ENABLED: bool = True
    PHASE4_REJECT_IF_BEARISH_CONFIDENCE: float = 60
    
    MAX_TRADES_PER_DAY: int = 1
    MONITOR_INTERVAL_SECONDS: int = 5
    ENABLED: bool = True

    # Paper Trading Mode
    PH5_PAPER_MODE: bool = True               # True = paper (no real orders)
    PH5_PAPER_LOG_FILE: str = "data/ph5_paper_trades.json"


class Phase5GapStrategy:
    """Phase 5: Gap Strategy v4.10.0 - Falling Knife Protection"""
    
    MASTER_STOCK_LIST = [
        'RELIANCE', 'TCS', 'HDFCBANK', 'INFY', 'ICICIBANK',
        'HINDUNILVR', 'SBIN', 'BHARTIARTL', 'ITC', 'KOTAKBANK',
        'LT', 'AXISBANK', 'ASIANPAINT', 'MARUTI', 'HCLTECH',
        'BAJFINANCE', 'TITAN', 'SUNPHARMA', 'ULTRACEMCO', 'NESTLEIND',
        'WIPRO', 'ADANIENT', 'ONGC', 'NTPC', 'JSWSTEEL',
        'POWERGRID', 'M&M', 'TATASTEEL', 'BAJAJFINSV', 'TECHM',
        'HINDALCO', 'TATAMOTORS', 'INDUSINDBK', 'COALINDIA', 'HDFCLIFE',
        'SBILIFE', 'BRITANNIA', 'DIVISLAB', 'BAJAJ-AUTO', 'EICHERMOT',
        'DRREDDY', 'GRASIM', 'BPCL', 'CIPLA', 'TATACONSUM',
        'APOLLOHOSP', 'ADANIPORTS', 'HEROMOTOCO', 'SHRIRAMFIN', 'LTIM',
        'HAVELLS', 'SIEMENS', 'DLF', 'GODREJCP', 'BOSCHLTD',
        'AMBUJACEM', 'PIDILITIND', 'INDUSTOWER', 'ICICIPRULI', 'VEDL',
        'CANBK', 'PNB', 'BANKBARODA', 'IDFCFIRSTB', 'FEDERALBNK',
        'JINDALSTEL', 'SAIL', 'NMDC', 'HINDZINC', 'ADANIGREEN',
        'TATAPOWER', 'TORNTPOWER', 'IOC', 'GAIL', 'PETRONET',
        'MCDOWELL-N', 'DABUR', 'MARICO', 'COLPAL', 'PGHH',
        'BERGEPAINT', 'INDIGO', 'IRCTC', 'PVR', 'ZOMATO',
        'NYKAA', 'ZEEL', 'SUNTV', 'DIXON', 'VOLTAS',
        'WHIRLPOOL', 'CROMPTON', 'BATAINDIA', 'AFFLE', 'MPHASIS',
        'COFORGE', 'PERSISTENT', 'L&TFH', 'CHOLAFIN', 'MUTHOOTFIN',
        'PFC', 'RECLTD', 'LICHSGFIN', 'BAJAJHLDNG', 'UNIONBANK',
        'PAYTM', 'POLICYBZR', 'TATATECH', 'JIOFINANC', 'IREDA',
        'COCHINSHIP', 'MAZAGON', 'BEL', 'HAL', 'BHEL',
        'RVNL', 'IRCON', 'NBCC', 'CONCOR', 'APOLLOTYRE',
        'MRF', 'BALKRISIND', 'CEAT', 'JKTYRE', 'EXIDEIND',
        'AMARAJABAT', 'SCHAEFFLER', 'MOTHERSON', 'MINDACORP', 'RAMCOCEM',
        'JKCEMENT', 'DALBHARAT', 'SHREECEM', 'ACC', 'GUJAMBCEM',
        'STAR', 'NATCOPHARM', 'GLAXO', 'PFIZER', 'BIOCON',
        'TORNTPHARM', 'ALKEM', 'LUPIN', 'CADILAHC', 'GRANULES',
        'AUBANK', 'BANDHANBNK', 'RBLBANK', 'CREDITACC', 'MANAPPURAM',
        'ICICIGI', 'SBICARD', 'HDFCAMC', 'AARTIIND', 'SYMPHONY'
    ]
    
    def __init__(
        self,
        kite: Optional[KiteConnect] = None,
        config: Optional[GapStrategyConfig] = None,
        finbert: Optional[FinBERTAnalyzer] = None,
        news_scraper: Optional[NewsScraper] = None,
        stock_universe: Optional[List[str]] = None,
        telegram_notifier: Optional[Any] = None,
        capital_manager: Optional[Any] = None,
        chatgpt_advisor: Optional[Any] = None,
        phase4_manager: Optional[Any] = None
    ):
        self.kite = kite
        self.config = config or GapStrategyConfig()
        self.finbert = finbert
        self.news_scraper = news_scraper
        self.stock_universe = stock_universe or self.MASTER_STOCK_LIST.copy()
        self.telegram = telegram_notifier
        self.capital_manager = capital_manager
        self.chatgpt_advisor = chatgpt_advisor
        self.phase4_manager = phase4_manager
        self.orchestrator = None
        
        self.today_date = None
        self.gap_candidates: List[GapCandidate] = []
        self.selected_candidate: Optional[GapCandidate] = None
        self.radar_candidates: List[GapCandidate] = []
        self.active_trade: Optional[GapTrade] = None
        self.today_trades: List[GapTrade] = []
        self.market_sentiment: str = "NEUTRAL"
        
        self.nifty_gap_pct: float = 0.0
        self.nifty_regime: str = "NEUTRAL"
        
        self._margin_cache: Dict[str, Dict] = {}
        self._margin_cache_time: Optional[datetime] = None
        self._MARGIN_CACHE_TTL_SECONDS: int = 300
        self._instrument_cache: Dict[str, int] = {}

        # Paper trading mode
        self._paper_mode = getattr(self.config, 'PH5_PAPER_MODE', False)
        self._paper_trades: List[Dict] = []        # in-memory paper trade log
        self._active_paper_trades: List[Dict] = []  # currently open paper positions

        logger.info("=" * 70)
        logger.info("PHASE 5: GAP STRATEGY v4.10.0 INITIALIZED")
        if self._paper_mode:
            logger.info("   📝 PAPER TRADING MODE — no real orders will be placed")
        logger.info(f"   Stock Universe: {len(self.stock_universe)} stocks")
        logger.info(f"   ADX Threshold: {self.config.MAX_ADX} (tightened)")
        logger.info(f"   Min Recovery: {self.config.MIN_RECOVERY_PCT}%")
        logger.info(f"   Daily Trend Filter: {'ON' if self.config.DAILY_TREND_FILTER_ENABLED else 'OFF'}")
        logger.info(f"   NIFTY Regime Filter: {'ON' if self.config.NIFTY_REGIME_FILTER_ENABLED else 'OFF'}")
        logger.info("=" * 70)

    def set_orchestrator(self, orchestrator):
        self.orchestrator = orchestrator
        logger.info("   ✅ Orchestrator reference set for Phase 5")

    def run_gap_strategy(self) -> Optional[GapTrade]:
        """Main entry point - Run complete gap strategy cycle."""
        logger.info("")
        logger.info("═" * 70)
        logger.info("🎯 PHASE 5: GAP STRATEGY v4.10.0 - STARTING")
        logger.info("═" * 70)
        
        if not self.config.ENABLED:
            logger.info("⏸️ Gap Strategy is DISABLED")
            return None
        
        now = datetime.now()
        current_time = now.time()
        
        if current_time < self.config.SCAN_START_TIME:
            logger.info(f"⏰ Too early. Wait until {self.config.SCAN_START_TIME}")
            return None
        
        if current_time > self.config.MANDATORY_EXIT_TIME:
            logger.info(f"⏰ Gap window closed")
            return None
        
        if self.today_date != now.date():
            self._reset_daily_state()
        
        if len(self.today_trades) >= self.config.MAX_TRADES_PER_DAY:
            logger.info(f"📊 Max trades reached: {len(self.today_trades)}")
            return None
        
        try:
            # Step 1: Market sentiment
            logger.info("\n─ STEP 1: FINBERT SENTIMENT ─")
            self.market_sentiment = self._get_market_sentiment()
            logger.info(f"📊 Sentiment: {self.market_sentiment}")
            
            # Step 1.5: NIFTY Regime
            if self.config.NIFTY_REGIME_FILTER_ENABLED:
                logger.info("\n─ STEP 1.5: NIFTY REGIME ─")
                self._check_nifty_regime()
                logger.info(f"📊 NIFTY: {self.nifty_gap_pct:+.2f}% ({self.nifty_regime})")
            
            # Step 2: Scan for gaps
            logger.info("\n─ STEP 2: GAP SCAN ─")
            self.gap_candidates = self._scan_for_gaps()
            
            if not self.gap_candidates:
                logger.info("❌ No gap candidates")
                return None
            
            # Step 3: Apply filters
            logger.info("\n─ STEP 3: FILTERS (v4.10.0) ─")
            filtered = self._apply_filters_with_detailed_logging(self.gap_candidates)
            
            if not filtered:
                logger.info("❌ No candidates passed filters")
                return None
            
            # Step 4: Select best
            logger.info("\n─ STEP 4: SELECT BEST ─")
            self.selected_candidate = self._select_best_candidate(filtered)
            
            if not self.selected_candidate:
                logger.info("❌ Could not select candidate")
                return None
            
            # Step 4.5: Phase 4 pre-validation
            if self.config.PHASE4_PREVALIDATION_ENABLED and self.phase4_manager:
                logger.info("\n─ STEP 4.5: PHASE 4 PRE-VALIDATION ─")
                if not self._prevalidate_with_phase4(self.selected_candidate):
                    logger.info(f"❌ {self.selected_candidate.symbol} rejected by Phase 4")
                    for backup in self.radar_candidates:
                        if self._prevalidate_with_phase4(backup):
                            logger.info(f"✅ Using backup: {backup.symbol}")
                            self.selected_candidate = backup
                            break
                    else:
                        logger.info("❌ All candidates rejected by Phase 4")
                        return None
            
            # Step 5: Execute
            if current_time >= self.config.ENTRY_START_TIME:
                logger.info("\n─ STEP 5: EXECUTE ENTRY ─")
                trade = self._execute_entry(self.selected_candidate)
                if trade:
                    self.active_trade = trade
                    self.today_trades.append(trade)
                    logger.info(f"✅ Trade opened: {trade.symbol}")
                    return trade
            
            return None
            
        except Exception as e:
            logger.error(f"❌ Gap strategy error: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return None

    def _check_nifty_regime(self):
        """Check NIFTY gap and determine market regime."""
        try:
            if not self.kite:
                return
            nifty_quote = self.kite.quote(["NSE:NIFTY 50"])
            if "NSE:NIFTY 50" in nifty_quote:
                q = nifty_quote["NSE:NIFTY 50"]
                prev_close = q['ohlc']['close']
                open_price = q['ohlc']['open']
                self.nifty_gap_pct = ((open_price - prev_close) / prev_close) * 100
                if self.nifty_gap_pct > self.config.NIFTY_GAP_THRESHOLD:
                    self.nifty_regime = "BULLISH"
                elif self.nifty_gap_pct < -self.config.NIFTY_GAP_THRESHOLD:
                    self.nifty_regime = "BEARISH"
                else:
                    self.nifty_regime = "NEUTRAL"
        except Exception as e:
            logger.warning(f"NIFTY regime check failed: {e}")
            self.nifty_regime = "NEUTRAL"

    def _analyze_daily_trend(self, symbol: str, current_price: float) -> Optional[DailyTrendAnalysis]:
        """Analyze daily timeframe for falling knife detection."""
        try:
            if not self.kite or ta is None:
                return None
            token = self._get_instrument_token(symbol)
            if not token:
                return None
            to_date = datetime.now()
            from_date = to_date - timedelta(days=60)
            hist = self.kite.historical_data(
                instrument_token=token,
                from_date=from_date.strftime("%Y-%m-%d"),
                to_date=to_date.strftime("%Y-%m-%d"),
                interval="day"
            )
            if not hist or len(hist) < 20:
                return None
            df = pd.DataFrame(hist)
            close = df['close'].values
            ema5 = ta.EMA(close, timeperiod=5)
            ema20 = ta.EMA(close, timeperiod=20)
            rsi = ta.RSI(close, timeperiod=14)
            daily_ema5 = ema5[-1] if not np.isnan(ema5[-1]) else current_price
            daily_ema20 = ema20[-1] if not np.isnan(ema20[-1]) else current_price
            daily_rsi = rsi[-1] if not np.isnan(rsi[-1]) else 50
            price_vs_ema5_pct = ((current_price - daily_ema5) / daily_ema5) * 100
            is_downtrend = current_price < daily_ema5 and daily_ema5 < daily_ema20
            is_oversold_falling = daily_rsi < self.config.DAILY_RSI_FALLING_KNIFE_THRESHOLD and is_downtrend
            if current_price > daily_ema5:
                trend_score = 30
            elif current_price > daily_ema20:
                trend_score = 20
            elif daily_rsi > self.config.DAILY_RSI_OVERSOLD_THRESHOLD:
                trend_score = 10
            else:
                trend_score = 0
            warning = ""
            if is_oversold_falling:
                warning = f"⚠️ FALLING KNIFE: RSI={daily_rsi:.1f}"
            elif is_downtrend:
                warning = f"⚠️ Downtrend"
            return DailyTrendAnalysis(
                daily_rsi=daily_rsi, daily_ema5=daily_ema5, daily_ema20=daily_ema20,
                current_price=current_price, price_vs_ema5_pct=price_vs_ema5_pct,
                is_downtrend=is_downtrend, is_oversold_falling=is_oversold_falling,
                trend_score=trend_score, warning=warning
            )
        except Exception as e:
            logger.debug(f"Daily trend analysis failed for {symbol}: {e}")
            return None

    def _prevalidate_with_phase4(self, candidate: GapCandidate) -> bool:
        """Ask Phase 4 if this entry makes sense."""
        try:
            if not self.phase4_manager:
                return True
            if not hasattr(self.phase4_manager, 'truth_predictor'):
                return True
            truth_predictor = self.phase4_manager.truth_predictor
            if not truth_predictor:
                return True
            direction = "LONG" if candidate.gap_type == GapType.GAP_DOWN else "SHORT"
            if hasattr(truth_predictor, 'get_quick_confluence_score'):
                score = truth_predictor.get_quick_confluence_score(
                    symbol=candidate.symbol, kite=self.kite, entry_price=candidate.current_price
                )
                if score is not None:
                    if direction == "LONG" and score < (100 - self.config.PHASE4_REJECT_IF_BEARISH_CONFIDENCE):
                        logger.info(f"   ❌ Phase 4: {score}% (BEARISH)")
                        return False
                    elif direction == "SHORT" and score > self.config.PHASE4_REJECT_IF_BEARISH_CONFIDENCE:
                        logger.info(f"   ❌ Phase 4: {score}% (BULLISH)")
                        return False
                    logger.info(f"   ✅ Phase 4: {score}% - OK for {direction}")
            return True
        except Exception as e:
            logger.debug(f"Phase 4 pre-validation error: {e}")
            return True

    def _get_market_sentiment(self) -> str:
        """Get market sentiment from FinBERT."""
        if not self.finbert:
            try:
                from finbert_analyzer import get_finbert_analyzer
                self.finbert = get_finbert_analyzer()
            except:
                return "NEUTRAL"
        try:
            if self.news_scraper:
                headlines = self.news_scraper.get_market_headlines()
            else:
                headlines = ["NIFTY", "market", "trading"]
            result = self.finbert.analyze_sentiment(" ".join(headlines[:5]))
            return result.get('sentiment', 'NEUTRAL').upper()
        except:
            return "NEUTRAL"

    def _scan_for_gaps(self) -> List[GapCandidate]:
        """Scan stock universe for significant gaps."""
        candidates = []
        thresholds = [
            (self.config.GAP_THRESHOLD_PRIORITY_1, "P1"),
            (self.config.GAP_THRESHOLD_PRIORITY_2, "P2"),
            (self.config.GAP_THRESHOLD_PRIORITY_3, "P3")
        ]
        for threshold, label in thresholds:
            logger.info(f"Scanning {len(self.stock_universe)} stocks at {label} ({threshold}%)")
            for symbol in self.stock_universe:
                candidate = self._analyze_gap(symbol, threshold)
                if candidate:
                    candidates.append(candidate)
            if candidates:
                logger.info(f"   ✅ Found {len(candidates)} at {label}")
                break
        return candidates

    def _analyze_gap(self, symbol: str, min_gap_pct: float) -> Optional[GapCandidate]:
        """Analyze a single stock for gap."""
        try:
            if not self.kite:
                return None
            token = self._get_instrument_token(symbol)
            if not token:
                return None
            to_date = datetime.now()
            from_date = to_date - timedelta(days=30)
            hist = self.kite.historical_data(
                instrument_token=token,
                from_date=from_date.strftime("%Y-%m-%d"),
                to_date=to_date.strftime("%Y-%m-%d"),
                interval="day"
            )
            if not hist or len(hist) < 15:
                return None
            df = pd.DataFrame(hist)
            prev_close = df['close'].iloc[-1]
            quote = self.kite.quote([f"NSE:{symbol}"])
            q = quote.get(f"NSE:{symbol}")
            if not q:
                return None
            open_price = q['ohlc']['open']
            high_price = q['ohlc']['high']
            low_price = q['ohlc']['low']
            current_price = q['last_price']
            volume = q['volume']
            avg_volume = df['volume'].iloc[-20:].mean() if len(df) >= 20 else df['volume'].mean()
            gap_pct = ((open_price - prev_close) / prev_close) * 100
            if abs(gap_pct) < min_gap_pct:
                return None
            if gap_pct < -min_gap_pct:
                gap_type = GapType.GAP_DOWN
            elif gap_pct > min_gap_pct:
                gap_type = GapType.GAP_UP
            else:
                return None
            high = df['high'].values
            low = df['low'].values
            close = df['close'].values
            atr_values = ta.ATR(high, low, close, timeperiod=14)
            atr = atr_values[-1] if not np.isnan(atr_values[-1]) else 0
            adx_values = ta.ADX(high, low, close, timeperiod=14)
            adx = adx_values[-1] if not np.isnan(adx_values[-1]) else 25
            return GapCandidate(
                symbol=symbol, gap_pct=gap_pct, gap_type=gap_type,
                prev_close=prev_close, open_price=open_price,
                high_price=high_price, low_price=low_price,
                current_price=current_price, volume=volume,
                avg_volume=int(avg_volume), atr=atr, adx=adx
            )
        except Exception as e:
            logger.debug(f"Gap analysis error for {symbol}: {e}")
            return None

    def _calculate_volume_burst_score(self, candidate: GapCandidate) -> VolumeBurstScore:
        """
        Calculate Volume Burst Score - v4.10.0 FIXED recovery calculation.
        
        OLD (BUGGY): range_from_open = (open - low), gave 100% when current >= open
        NEW (FIXED): full_range = (high - low), true recovery measurement
        """
        # Factor A: Volume Ratio (0-40 pts)
        expected_volume = int(candidate.avg_volume * self.config.OPENING_VOLUME_TIME_FRACTION)
        if expected_volume <= 0:
            expected_volume = 1
        volume_ratio = candidate.volume / expected_volume
        if volume_ratio >= 2.0:
            volume_score = 40
        elif volume_ratio >= 1.5:
            volume_score = 30
        elif volume_ratio >= 1.0:
            volume_score = 20
        elif volume_ratio >= 0.5:
            volume_score = 10
        else:
            volume_score = 0
        
        # Factor B: Range Intensity (0-30 pts)
        todays_range = candidate.high_price - candidate.low_price
        if candidate.atr > 0:
            range_atr_ratio = todays_range / candidate.atr
        else:
            range_atr_ratio = 0
        if range_atr_ratio >= 0.5:
            range_score = 30
        elif range_atr_ratio >= 0.3:
            range_score = 20
        elif range_atr_ratio >= 0.15:
            range_score = 10
        else:
            range_score = 0
        
        # Factor C: Recovery (0-30 pts) - v4.10.0 FIXED
        full_range = candidate.high_price - candidate.low_price
        if candidate.gap_type == GapType.GAP_DOWN:
            # BUY - recovery from low toward high
            if full_range > 0:
                recovery_pct = ((candidate.current_price - candidate.low_price) / full_range) * 100
            else:
                recovery_pct = 50.0
        else:
            # SELL - fade from high toward low
            if full_range > 0:
                recovery_pct = ((candidate.high_price - candidate.current_price) / full_range) * 100
            else:
                recovery_pct = 50.0
        recovery_pct = min(max(recovery_pct, 0.0), 100.0)
        
        if recovery_pct >= self.config.MIN_RECOVERY_PCT:
            recovery_score = 30
        elif recovery_pct >= 40:
            recovery_score = 20
        elif recovery_pct >= 25:
            recovery_score = 10
        else:
            recovery_score = 0
        
        total_score = volume_score + range_score + recovery_score
        passed = total_score >= self.config.VOLUME_BURST_MIN_SCORE
        
        return VolumeBurstScore(
            todays_volume=candidate.volume, daily_avg_volume=candidate.avg_volume,
            expected_volume=expected_volume, volume_ratio=volume_ratio, volume_score=volume_score,
            todays_range=todays_range, atr=candidate.atr, range_atr_ratio=range_atr_ratio,
            range_score=range_score, open_price=candidate.open_price, low_price=candidate.low_price,
            high_price=candidate.high_price, current_price=candidate.current_price,
            recovery_pct=recovery_pct, recovery_score=recovery_score,
            total_score=total_score, passed=passed
        )

    def _apply_filters_with_detailed_logging(self, candidates: List[GapCandidate]) -> List[GapCandidate]:
        """Apply filters with detailed logging."""
        filtered = []
        for candidate in candidates:
            self._log_candidate_analysis(candidate)
            passed, reason = self._check_filters_v3(candidate)
            candidate.filters_passed = passed
            candidate.filter_reason = reason
            if passed:
                filtered.append(candidate)
        logger.info(f"\nFILTER SUMMARY: {len(filtered)}/{len(candidates)} passed")
        return filtered

    def _log_candidate_analysis(self, candidate: GapCandidate):
        """Log detailed analysis for a candidate."""
        vb = self._calculate_volume_burst_score(candidate)
        candidate.volume_burst_score = vb
        if self.config.DAILY_TREND_FILTER_ENABLED:
            candidate.daily_trend = self._analyze_daily_trend(candidate.symbol, candidate.current_price)
        
        gap_emoji = "⬇️" if candidate.gap_type == GapType.GAP_DOWN else "⬆️"
        trade_dir = "BUY" if candidate.gap_type == GapType.GAP_DOWN else "SELL"
        
        logger.info("")
        logger.info("╔" + "═" * 60 + "╗")
        logger.info(f"║ {candidate.symbol:<15} {gap_emoji} {candidate.gap_pct:+.2f}% → {trade_dir}")
        logger.info("╠" + "═" * 60 + "╣")
        logger.info(f"║ Price: ₹{candidate.current_price:.2f} | ATR: ₹{candidate.atr:.2f} | ADX: {candidate.adx:.1f}")
        logger.info("╠" + "─" * 60 + "╣")
        logger.info(f"║ Volume Burst: {vb.total_score}/100 (Vol:{vb.volume_score} Range:{vb.range_score} Rec:{vb.recovery_score})")
        logger.info(f"║ Recovery: {vb.recovery_pct:.1f}% (need ≥{self.config.MIN_RECOVERY_PCT}%) {'✓' if vb.recovery_pct >= self.config.MIN_RECOVERY_PCT else '✗'}")
        logger.info(f"║ ADX: {candidate.adx:.1f} (need ≤{self.config.MAX_ADX}) {'✓' if candidate.adx <= self.config.MAX_ADX else '✗'}")
        
        if candidate.daily_trend:
            dt = candidate.daily_trend
            logger.info(f"║ Daily: RSI={dt.daily_rsi:.1f} Trend={dt.trend_score}/30 {dt.warning}")
        
        if self.config.NIFTY_REGIME_FILTER_ENABLED:
            logger.info(f"║ NIFTY: {self.nifty_gap_pct:+.2f}% ({self.nifty_regime})")
        
        logger.info("╚" + "═" * 60 + "╝")

    def _check_filters_v3(self, candidate: GapCandidate) -> Tuple[bool, str]:
        """Check all filters v4.10.0."""
        fail_reasons = []
        
        # Filter 1: Sentiment
        if candidate.gap_type == GapType.GAP_DOWN and self.market_sentiment == "BEARISH":
            fail_reasons.append("Sentiment BEARISH vs BUY")
        elif candidate.gap_type == GapType.GAP_UP and self.market_sentiment == "BULLISH":
            fail_reasons.append("Sentiment BULLISH vs SELL")
        else:
            candidate.finbert_aligned = True
        
        # Filter 2: Volume Burst
        vb = candidate.volume_burst_score
        if vb and not vb.passed:
            fail_reasons.append(f"VB {vb.total_score}/100 < {self.config.VOLUME_BURST_MIN_SCORE}")
        
        # Filter 3: ADX (tightened)
        if candidate.adx > self.config.MAX_ADX:
            fail_reasons.append(f"ADX {candidate.adx:.1f} > {self.config.MAX_ADX}")
        
        # Filter 4: Min Recovery
        if vb and vb.recovery_pct < self.config.MIN_RECOVERY_PCT:
            fail_reasons.append(f"Recovery {vb.recovery_pct:.1f}% < {self.config.MIN_RECOVERY_PCT}%")
        
        # Filter 5: NIFTY Regime
        if self.config.NIFTY_REGIME_FILTER_ENABLED:
            if candidate.gap_type == GapType.GAP_DOWN and self.nifty_regime == "BEARISH":
                fail_reasons.append(f"NIFTY BEARISH - broad weakness")
            elif candidate.gap_type == GapType.GAP_UP and self.nifty_regime == "BULLISH":
                fail_reasons.append(f"NIFTY BULLISH - strong momentum")
        
        # Filter 6: Daily Trend (falling knife)
        if self.config.DAILY_TREND_FILTER_ENABLED and candidate.daily_trend:
            dt = candidate.daily_trend
            if dt.is_oversold_falling and candidate.gap_type == GapType.GAP_DOWN:
                fail_reasons.append(f"FALLING KNIFE: RSI={dt.daily_rsi:.1f}")
        
        if fail_reasons:
            return False, "; ".join(fail_reasons)
        
        vb_score = vb.total_score if vb else 0
        return True, f"Gap:{candidate.gap_pct:+.2f}%, VB:{vb_score}/100"

    def _select_best_candidate(self, candidates: List[GapCandidate]) -> Optional[GapCandidate]:
        """Select best candidate with v4.10.0 scoring."""
        if not candidates:
            return None
        for candidate in candidates:
            gap_factor = abs(candidate.gap_pct)
            vb_factor = candidate.volume_burst_score.total_score / 100 if candidate.volume_burst_score else 0.5
            adx_factor = max(0, 30 - candidate.adx) / 30
            trend_factor = 1.0
            if candidate.daily_trend:
                trend_factor = candidate.daily_trend.trend_score / 30
            candidate.score = gap_factor * vb_factor * (1 + adx_factor) * (0.5 + trend_factor * 0.5)
        
        candidates.sort(key=lambda x: x.score, reverse=True)
        logger.info("📊 Top Candidates:")
        for i, c in enumerate(candidates[:5]):
            vb = c.volume_burst_score.total_score if c.volume_burst_score else 0
            tag = " ← SELECTED" if i == 0 else ""
            logger.info(f"   {i+1}. {c.symbol}: Score={c.score:.2f}, Gap={c.gap_pct:+.2f}%, VB={vb}{tag}")
        
        self.radar_candidates = candidates[1:5]
        return candidates[0]

    def _calculate_position_size_with_leverage(self, symbol: str, price: float, direction: GapTradeDirection) -> Optional[Dict]:
        """Calculate position size with leverage."""
        try:
            if self.capital_manager:
                available_capital = self.capital_manager.get_available()
            else:
                available_capital = self.config.PHASE5_MAX_CAPITAL
            
            phase5_allocation = min(available_capital, self.config.PHASE5_MAX_CAPITAL)
            
            if phase5_allocation < self.config.PHASE5_MIN_CAPITAL:
                return {'quantity': 0, 'margin_per_share': price, 'reason': 'Insufficient capital'}
            
            margin_per_share = price
            effective_leverage = 1.0
            
            if self.config.USE_LEVERAGE and self.kite:
                try:
                    transaction_type = "BUY" if direction == GapTradeDirection.BUY else "SELL"
                    margins = self.kite.order_margins([{
                        "exchange": "NSE", "tradingsymbol": symbol,
                        "transaction_type": transaction_type, "variety": "regular",
                        "product": "MIS", "order_type": "MARKET", "quantity": 1
                    }])
                    if margins and len(margins) > 0:
                        margin_per_share = float(margins[0].get('total', price))
                        effective_leverage = price / margin_per_share if margin_per_share > 0 else 1.0
                except:
                    margin_per_share = price / self.config.DEFAULT_LEVERAGE
                    effective_leverage = self.config.DEFAULT_LEVERAGE
            
            max_quantity = int((phase5_allocation / margin_per_share) * self.config.LEVERAGE_SAFETY_BUFFER)
            
            if max_quantity <= 0:
                return {'quantity': 0, 'margin_per_share': margin_per_share, 'reason': 'Cannot afford'}
            
            return {
                'quantity': max_quantity, 'margin_per_share': margin_per_share,
                'margin_used': max_quantity * margin_per_share,
                'effective_leverage': effective_leverage, 'available_capital': phase5_allocation
            }
        except Exception as e:
            logger.error(f"Position sizing error: {e}")
            return None

    def _execute_entry(self, candidate: GapCandidate) -> Optional[GapTrade]:
        """Execute entry order - v4.10.0 fixed deploy() call."""
        try:
            if not self.kite:
                return None
            
            if candidate.gap_type == GapType.GAP_DOWN:
                direction = GapTradeDirection.BUY
                transaction_type = "BUY"
            else:
                direction = GapTradeDirection.SELL
                transaction_type = "SELL"
            
            entry_price = candidate.current_price
            sizing = self._calculate_position_size_with_leverage(candidate.symbol, entry_price, direction)
            
            if not sizing or sizing['quantity'] <= 0:
                logger.warning(f"❌ Cannot afford {candidate.symbol}")
                return None
            
            quantity = sizing['quantity']
            
            # Calculate target/stop
            if direction == GapTradeDirection.BUY:
                target_price = entry_price * (1 + self.config.TARGET_PCT / 100)
                stop_distance = max(candidate.atr * self.config.STOP_ATR_MULTIPLIER, entry_price * self.config.MIN_STOP_PCT / 100)
                stop_distance = min(stop_distance, entry_price * self.config.MAX_STOP_PCT / 100)
                stop_price = entry_price - stop_distance
            else:
                target_price = entry_price * (1 - self.config.TARGET_PCT / 100)
                stop_distance = max(candidate.atr * self.config.STOP_ATR_MULTIPLIER, entry_price * self.config.MIN_STOP_PCT / 100)
                stop_distance = min(stop_distance, entry_price * self.config.MAX_STOP_PCT / 100)
                stop_price = entry_price + stop_distance
            
            target_price = round(target_price * 10) / 10
            stop_price = round(stop_price * 10) / 10
            
            logger.info(f"📤 Placing {transaction_type}: {candidate.symbol} x {quantity}")

            order_id = self._place_order(
                tradingsymbol=candidate.symbol, exchange="NSE",
                transaction_type=transaction_type, quantity=quantity,
                product="MIS", order_type="MARKET", variety="regular"
            )
            logger.info(f"✅ Order placed: {order_id}")

            if self._paper_mode:
                # Paper mode: simulate immediate fill at current price
                try:
                    quote = self.kite.quote([f"NSE:{candidate.symbol}"])
                    sim_price = quote.get(f"NSE:{candidate.symbol}", {}).get('last_price', entry_price)
                except Exception:
                    sim_price = entry_price
                fill_info = {'filled': True, 'status': 'COMPLETE', 'average_price': sim_price}
            else:
                fill_info = self._verify_order_fill(order_id, candidate.symbol, quantity)
            if not fill_info['filled']:
                logger.error(f"❌ Order not filled: {fill_info['status']}")
                return None
            
            actual_fill_price = fill_info['average_price']
            logger.info(f"✅ Filled @ ₹{actual_fill_price:.2f}")
            
            # Recalculate targets based on actual fill
            if direction == GapTradeDirection.BUY:
                target_price = actual_fill_price * (1 + self.config.TARGET_PCT / 100)
                stop_price = actual_fill_price - stop_distance
            else:
                target_price = actual_fill_price * (1 - self.config.TARGET_PCT / 100)
                stop_price = actual_fill_price + stop_distance
            target_price = round(target_price * 10) / 10
            stop_price = round(stop_price * 10) / 10
            
            gtt_id = self._place_gtt_stoploss(candidate.symbol, quantity, stop_price, direction)
            
            actual_margin_used = sizing['margin_per_share'] * quantity
            
            self._notify_entry(candidate, direction, actual_fill_price, quantity, target_price, stop_price, actual_margin_used, sizing['effective_leverage'])
            
            trade = GapTrade(
                symbol=candidate.symbol, direction=direction, entry_price=actual_fill_price,
                entry_time=datetime.now(), quantity=quantity, target_price=target_price,
                stop_price=stop_price, target_pct=self.config.TARGET_PCT,
                stop_pct=-(stop_distance / actual_fill_price) * 100, gap_pct=candidate.gap_pct,
                status=GapTradeStatus.ENTERED, order_id=str(order_id),
                gtt_id=str(gtt_id) if gtt_id else None, margin_used=actual_margin_used,
                effective_leverage=sizing['effective_leverage'], position_value=actual_fill_price * quantity
            )
            
            # v4.10.0 FIX: Correct deploy() call
            if self.capital_manager:
                self.capital_manager.deploy(
                    symbol=candidate.symbol,
                    amount=actual_margin_used,
                    quantity=quantity,
                    avg_price=actual_fill_price
                )
                logger.info(f"   💰 Capital deployed: ₹{actual_margin_used:,.0f}")

            # PAPER MODE: Log entry to paper_trade_logger → Excel
            if self._paper_mode:
                try:
                    from paper_trade_logger import log_paper_entry
                    _phase_tag = "PH5_GAP"
                    _logger_id = log_paper_entry(
                        phase=_phase_tag,
                        symbol=candidate.symbol,
                        direction=transaction_type,
                        entry_price=actual_fill_price,
                        quantity=quantity,
                        stop_loss=stop_price,
                        target=target_price,
                        strategy="Gap Strategy",
                        score=getattr(candidate, 'total_score', 0),
                        regime=self.nifty_regime,
                        notes=f"Gap: {candidate.gap_pct:+.2f}%  GTT(paper): {gtt_id}"
                    )
                    trade.paper_logger_id = _logger_id
                    logger.info(f"   📊 PAPER LOG: entry recorded → {_logger_id}")
                except Exception as _le:
                    logger.warning(f"   ⚠️ paper_trade_logger entry failed: {_le}")

            return trade
            
        except Exception as e:
            logger.error(f"Entry execution error: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return None

    def _get_instrument_token(self, symbol: str) -> Optional[int]:
        if symbol in self._instrument_cache:
            return self._instrument_cache[symbol]
        try:
            if not self.kite:
                return None
            instruments = self.kite.ltp([f"NSE:{symbol}"])
            if f"NSE:{symbol}" in instruments:
                token = instruments[f"NSE:{symbol}"].get('instrument_token')
                if token:
                    self._instrument_cache[symbol] = token
                    return token
        except:
            pass
        return None

    def _verify_order_fill(self, order_id: str, symbol: str, expected_qty: int) -> Dict:
        try:
            for _ in range(5):
                orders = self.kite.orders()
                for order in orders:
                    if str(order['order_id']) == str(order_id):
                        status = order['status']
                        if status == 'COMPLETE':
                            return {'filled': True, 'status': status, 'average_price': order['average_price']}
                        elif status in ['REJECTED', 'CANCELLED']:
                            return {'filled': False, 'status': status}
                time.sleep(0.5)
            return {'filled': False, 'status': 'TIMEOUT'}
        except Exception as e:
            return {'filled': False, 'status': 'ERROR', 'reason': str(e)}

    def _place_gtt_stoploss(self, symbol: str, quantity: int, stop_price: float, direction: GapTradeDirection) -> Optional[int]:
        try:
            if not self.kite:
                return None
            if self._paper_mode:
                import uuid
                paper_gtt_id = f"PGTT_{uuid.uuid4().hex[:6].upper()}"
                logger.info(f"   📝 PAPER GTT: {symbol} trigger={stop_price:.2f} "
                            f"(paper GTT ID: {paper_gtt_id})")
                return paper_gtt_id
            transaction_type = "SELL" if direction == GapTradeDirection.BUY else "BUY"
            gtt = self.kite.place_gtt(
                trigger_type=self.kite.GTT_TYPE_SINGLE, tradingsymbol=symbol, exchange="NSE",
                trigger_values=[stop_price], last_price=stop_price,
                orders=[{"exchange": "NSE", "tradingsymbol": symbol, "transaction_type": transaction_type,
                         "quantity": quantity, "order_type": "MARKET", "product": "MIS"}]
            )
            logger.info(f"🛡️ GTT placed: {gtt}")
            return gtt.get('trigger_id')
        except Exception as e:
            logger.warning(f"GTT placement failed: {e}")
            return None

    # ------------------------------------------------------------------
    #  PAPER TRADING HELPERS
    # ------------------------------------------------------------------

    def _place_order(self, **order_params) -> str:
        """Wrapper for order placement.
        In paper mode: logs the order, returns a fake order ID.
        In live mode: calls self.kite.place_order() as before.
        """
        if self._paper_mode:
            return self._place_paper_order(order_params)
        # v5.4.0 SEBI FIX: inject market_protection for MARKET/SL-M orders
        order_type = str(order_params.get('order_type', '')).upper()
        if order_type in ('MARKET', 'SL-M'):
            order_params['market_protection'] = -1
        return self.kite.place_order(
            tradingsymbol=order_params.get('tradingsymbol'),
            exchange=order_params.get('exchange', 'NSE'),
            transaction_type=order_params.get('transaction_type', 'BUY'),
            quantity=order_params.get('quantity'),
            product=order_params.get('product', 'MIS'),
            order_type=order_params.get('order_type', 'MARKET'),
            variety=order_params.get('variety', 'regular'),
            price=order_params.get('price'),
            trigger_price=order_params.get('trigger_price'),
            market_protection=order_params.get('market_protection'),
        )

    def _place_paper_order(self, params: dict) -> str:
        """Simulate order placement in paper mode."""
        import uuid
        import json as _json

        paper_id = f"PAPER_{uuid.uuid4().hex[:8].upper()}"

        symbol = params.get('tradingsymbol', '')
        try:
            quote = self.kite.quote([f"NSE:{symbol}"])
            fill_price = quote.get(f"NSE:{symbol}", {}).get('last_price', 0)
        except Exception:
            fill_price = params.get('price', 0)

        paper_trade = {
            "paper_order_id": paper_id,
            "symbol": symbol,
            "exchange": params.get('exchange', 'NSE'),
            "transaction_type": params.get('transaction_type', 'BUY'),
            "quantity": params.get('quantity', 0),
            "product": params.get('product', 'MIS'),
            "order_type": params.get('order_type', 'MARKET'),
            "intended_price": params.get('price', 0),
            "simulated_fill_price": fill_price,
            "timestamp": datetime.now().isoformat(),
            "status": "COMPLETE",
        }

        self._paper_trades.append(paper_trade)

        # Track open position for paper exit monitoring
        if params.get('transaction_type', 'BUY') == 'BUY':
            self._active_paper_trades.append(paper_trade)

        logger.info(f"   📝 PAPER ORDER: {params.get('transaction_type', 'BUY')} "
                     f"{params.get('quantity', 0)} {symbol} @ ₹{fill_price:.2f} "
                     f"(paper ID: {paper_id})")

        # Telegram notification
        try:
            if self.telegram:
                self.telegram.send_message(
                    f"📝 PH5 PAPER TRADE\n"
                    f"{params.get('transaction_type', 'BUY')} "
                    f"{params.get('quantity', 0)} {symbol}\n"
                    f"Fill: ₹{fill_price:.2f}\n"
                    f"Paper ID: {paper_id}"
                )
        except Exception:
            pass

        self._save_paper_log()
        return paper_id

    def _save_paper_log(self):
        """Save paper trades to JSON file."""
        import json as _json
        log_file = getattr(self.config, 'PH5_PAPER_LOG_FILE', 'data/ph5_paper_trades.json')
        try:
            os.makedirs(os.path.dirname(log_file), exist_ok=True)
            with open(log_file, 'w') as f:
                _json.dump(self._paper_trades, f, indent=2)
        except Exception as e:
            logger.debug(f"Paper log save failed: {e}")

    def _check_paper_exits(self):
        """In paper mode, check if any paper trades should be exited.
        Call this from monitor_position() path."""
        if not self._paper_mode or not self.active_trade:
            return
        # Paper exits are handled through the normal monitor_position() →
        # execute_exit() flow, which already uses _place_order wrapper.
        # No additional logic needed — the monitor checks price vs target/stop.

    # ------------------------------------------------------------------

    def _reset_daily_state(self):
        logger.info("🔄 Resetting daily state...")
        self.today_date = datetime.now().date()
        self.gap_candidates = []
        self.selected_candidate = None
        self.radar_candidates = []
        self.active_trade = None
        self.today_trades = []
        self.market_sentiment = "NEUTRAL"
        self.nifty_gap_pct = 0.0
        self.nifty_regime = "NEUTRAL"

    def _notify_entry(self, candidate, direction, fill_price, quantity, target, stop, margin_used, leverage):
        if not self.telegram:
            return
        try:
            emoji = "🟢" if direction == GapTradeDirection.BUY else "🔴"
            vb = candidate.volume_burst_score.total_score if candidate.volume_burst_score else 0
            trend = candidate.daily_trend.trend_score if candidate.daily_trend else "N/A"
            msg = (f"{emoji} GAP TRADE v4.10.0\n\n"
                   f"Symbol: {candidate.symbol}\n"
                   f"Direction: {direction.value}\n"
                   f"Gap: {candidate.gap_pct:+.2f}%\n"
                   f"Entry: ₹{fill_price:.2f}\n"
                   f"Qty: {quantity}\n"
                   f"Target: ₹{target:.2f}\n"
                   f"Stop: ₹{stop:.2f}\n"
                   f"VB: {vb}/100, Trend: {trend}/30\n"
                   f"NIFTY: {self.nifty_gap_pct:+.2f}% ({self.nifty_regime})")
            self.telegram.send_message(msg)
        except:
            pass

    def monitor_position(self) -> Optional[Dict]:
        """Monitor active trade for exit signals."""
        if not self.active_trade:
            return None
        try:
            trade = self.active_trade
            quote = self.kite.quote([f"NSE:{trade.symbol}"])
            if f"NSE:{trade.symbol}" not in quote:
                return None
            current_price = quote[f"NSE:{trade.symbol}"]['last_price']
            now = datetime.now()
            current_time = now.time()
            
            if trade.direction == GapTradeDirection.BUY:
                pnl = (current_price - trade.entry_price) * trade.quantity
                pnl_pct = ((current_price - trade.entry_price) / trade.entry_price) * 100
                target_hit = current_price >= trade.target_price
                stop_hit = current_price <= trade.stop_price
            else:
                pnl = (trade.entry_price - current_price) * trade.quantity
                pnl_pct = ((trade.entry_price - current_price) / trade.entry_price) * 100
                target_hit = current_price <= trade.target_price
                stop_hit = current_price >= trade.stop_price
            
            time_exit = current_time >= self.config.MANDATORY_EXIT_TIME
            
            if not trade.breakeven_trailed and current_time >= self.config.BREAKEVEN_TRAIL_TIME:
                if pnl > 0:
                    trade.stop_price = trade.entry_price
                    trade.breakeven_trailed = True
                    logger.info(f"🔄 {trade.symbol}: Stop trailed to breakeven")
            
            if target_hit:
                return {'action': 'EXIT', 'reason': 'TARGET_HIT', 'symbol': trade.symbol, 'pnl': pnl}
            elif stop_hit:
                return {'action': 'EXIT', 'reason': 'STOP_HIT', 'symbol': trade.symbol, 'pnl': pnl}
            elif time_exit:
                return {'action': 'EXIT', 'reason': 'TIME_EXIT', 'symbol': trade.symbol, 'pnl': pnl}
            
            return {'action': 'HOLD', 'symbol': trade.symbol, 'current_price': current_price, 'pnl': pnl}
        except Exception as e:
            logger.error(f"Monitor error: {e}")
            return None

    def execute_exit(self, reason: str = "MANUAL") -> Optional[Dict]:
        """Execute exit for active trade."""
        if not self.active_trade:
            return None
        try:
            trade = self.active_trade
            transaction_type = "SELL" if trade.direction == GapTradeDirection.BUY else "BUY"
            order_id = self._place_order(
                tradingsymbol=trade.symbol, exchange="NSE",
                transaction_type=transaction_type, quantity=trade.quantity,
                product="MIS", order_type="MARKET", variety="regular"
            )
            if self._paper_mode:
                try:
                    quote = self.kite.quote([f"NSE:{trade.symbol}"])
                    sim_price = quote.get(f"NSE:{trade.symbol}", {}).get('last_price', trade.entry_price)
                except Exception:
                    sim_price = trade.entry_price
                fill_info = {'filled': True, 'status': 'COMPLETE', 'average_price': sim_price}
            else:
                fill_info = self._verify_order_fill(order_id, trade.symbol, trade.quantity)
            
            if fill_info['filled']:
                exit_price = fill_info['average_price']
                trade.exit_price = exit_price
                trade.exit_time = datetime.now()
                if trade.direction == GapTradeDirection.BUY:
                    trade.pnl = (exit_price - trade.entry_price) * trade.quantity
                    trade.pnl_pct = ((exit_price - trade.entry_price) / trade.entry_price) * 100
                else:
                    trade.pnl = (trade.entry_price - exit_price) * trade.quantity
                    trade.pnl_pct = ((trade.entry_price - exit_price) / trade.entry_price) * 100
                
                if trade.gtt_id and not self._paper_mode:
                    try:
                        self.kite.delete_gtt(int(trade.gtt_id))
                    except:
                        pass

                # PAPER MODE: Log exit to paper_trade_logger → Excel
                if self._paper_mode:
                    try:
                        from paper_trade_logger import log_paper_exit
                        _logger_id = getattr(trade, 'paper_logger_id', None)
                        if _logger_id:
                            log_paper_exit(
                                trade_id=_logger_id,
                                exit_price=exit_price,
                                exit_reason=reason
                            )
                            logger.info(f"   📊 PAPER LOG: exit recorded → {_logger_id}  P&L=₹{trade.pnl:+.2f}")
                        else:
                            logger.warning("   ⚠️ PAPER LOG: no paper_logger_id on trade — exit not logged to Excel")
                    except Exception as _le:
                        logger.warning(f"   ⚠️ paper_trade_logger exit failed: {_le}")

                if self.capital_manager:
                    self.capital_manager.release(symbol=trade.symbol, amount=trade.margin_used, pnl=trade.pnl)

                self._notify_exit(trade, reason)
                self.active_trade = None
                return {'success': True, 'exit_price': exit_price, 'pnl': trade.pnl, 'reason': reason}
            
            return {'success': False, 'reason': 'Order not filled'}
        except Exception as e:
            logger.error(f"Exit error: {e}")
            return {'success': False, 'reason': str(e)}

    def _notify_exit(self, trade: GapTrade, reason: str):
        if not self.telegram:
            return
        try:
            emoji = "✅" if trade.pnl > 0 else "❌"
            self.telegram.send_message(
                f"{emoji} GAP TRADE CLOSED\n\n"
                f"Symbol: {trade.symbol}\n"
                f"Reason: {reason}\n"
                f"Entry: ₹{trade.entry_price:.2f}\n"
                f"Exit: ₹{trade.exit_price:.2f}\n"
                f"P&L: ₹{trade.pnl:+,.0f} ({trade.pnl_pct:+.2f}%)"
            )
        except:
            pass

    def get_active_trade(self) -> Optional[GapTrade]:
        return self.active_trade

    def has_active_trade(self) -> bool:
        return self.active_trade is not None

    def handoff_to_phase4(self) -> Optional[Dict]:
        """Hand off trade to Phase 4."""
        if not self.active_trade:
            return None
        trade = self.active_trade
        handoff_data = {
            'symbol': trade.symbol,
            'direction': 'LONG' if trade.direction == GapTradeDirection.BUY else 'SHORT',
            'entry_price': trade.entry_price, 'quantity': trade.quantity,
            'entry_time': trade.entry_time, 'margin_used': trade.margin_used,
            'source': 'PHASE5_GAP', 'gap_pct': trade.gap_pct,
            'is_paper_trade': self._paper_mode,             # tells Phase4 to skip real GTTs/orders
            'paper_logger_id': trade.paper_logger_id,       # carries logger ID for Phase4 exit logging
        }
        trade.status = GapTradeStatus.HANDED_OFF
        self.active_trade = None
        logger.info(f"🤝 Handed off {trade.symbol} to Phase 4")
        return handoff_data

    def handle_telegram_command(self, command: str, args: list = None) -> str:
        """Process /gap telegram commands."""
        args = args or []
        cmd = command.lower().strip()
        
        if cmd == 'status':
            return (f"📊 Phase 5 v4.10.0\n\n"
                    f"Enabled: {'✅' if self.config.ENABLED else '❌'}\n"
                    f"Trade: {'ACTIVE' if self.active_trade else 'NONE'}\n"
                    f"ADX Max: {self.config.MAX_ADX}\n"
                    f"Min Recovery: {self.config.MIN_RECOVERY_PCT}%\n"
                    f"NIFTY: {self.nifty_gap_pct:+.2f}% ({self.nifty_regime})")
        elif cmd == 'enable':
            self.config.ENABLED = True
            return "✅ Gap Strategy ENABLED"
        elif cmd == 'disable':
            self.config.ENABLED = False
            return "⏸️ Gap Strategy DISABLED"
        elif cmd == 'run':
            return self._force_run_scan()
        elif cmd == 'trade':
            if self.active_trade:
                t = self.active_trade
                return f"📊 Active Trade\n\n{t.symbol} {t.direction.value}\nEntry: ₹{t.entry_price:.2f}\nQty: {t.quantity}"
            return "No active trade"
        elif cmd == 'help':
            return ("📋 Gap Commands v4.10.0\n\n"
                    "/gap status - Status\n"
                    "/gap enable - Enable\n"
                    "/gap disable - Disable\n"
                    "/gap run - Force run NOW\n"
                    "/gap trade - Active trade\n"
                    "/gap help - This help")
        else:
            return f"Unknown: {cmd}. Try /gap help"

    def _force_run_scan(self) -> str:
        """Force run gap scan immediately."""
        try:
            now = datetime.now()
            current_time = now.time()
            if current_time < dt_time(9, 15):
                return "❌ Market not open yet"
            if current_time > dt_time(9, 50):
                return "❌ Gap window closed"
            if self.active_trade:
                return f"❌ Already have trade: {self.active_trade.symbol}"
            trade = self.run_gap_strategy()
            if trade:
                return f"✅ Trade opened: {trade.symbol} {trade.direction.value} @ ₹{trade.entry_price:.2f}"
            return "❌ No suitable gap found"
        except Exception as e:
            return f"❌ Error: {e}"


__all__ = [
    'Phase5GapStrategy', 'GapStrategyConfig', 'GapCandidate', 'GapTrade',
    'GapType', 'GapTradeDirection', 'GapTradeStatus', 'VolumeBurstScore', 'DailyTrendAnalysis'
]
