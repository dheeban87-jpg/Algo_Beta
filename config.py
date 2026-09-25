"""
[BOT] AUTONOMOUS TRADING SYSTEM - v4.8.1 - ORDER EXECUTION FIX
====================================================================================

✅ v4.8.1 (2026-02-05): ORDER FILL TIMEOUT FIX
────────────────────────────────────────────────
- Added ORDER_FILL_WAIT_SECONDS = 90 (was hardcoded 10s)
- Prevents premature order cancellation
- Gives Zerodha adequate time to fill orders

✅ v2.2.0 MEDIUM PRIORITY FIXES:
────────────────────────────────────────────────
FIX #13: Secrets masking in logs
   - Added mask_secret() utility function
   - All API keys/passwords masked when logged
   - Shows only first 4 and last 4 characters

✅ v5.0.1 FIXES APPLIED (January 2026):
────────────────────────────────────────────────
1. ✅ FIX #1: Added CHATGPT_API_KEY alias (line ~245)
   - chatgpt_strategic_advisor.py uses config.CHATGPT_API_KEY
   - But only OPENAI_API_KEY was defined
   - Now: CHATGPT_API_KEY = OPENAI_API_KEY

2. ✅ FIX #2: Capital sized for ₹8,500 account (line ~1053)
   - BASE_CAPITAL_PER_TRADE = ₹3,500
   - MAX_TOTAL_POSITIONS = 2
   - 2 × ₹3,500 = ₹7,000 (82%), preserves ₹1,500 buffer

3. ✅ FIX #3: Removed conflicting deprecated settings
   - Commented out STOP_LOSS_PERCENT (was 5.0%)
   - Commented out TARGET_PERCENT (was 40.0%)
   - These were from options trading, caused confusion
   - ACTUAL settings: PROFIT_TARGET_PCT=3.0%, STOP_LOSS_PCT=2.0%

4. ✅ FIX #4: Commented out QUANTITY_PER_TRADE
   - Deprecated, now using BASE_CAPITAL_PER_TRADE + AI

====================================================================================
"""
"""
INTELLIGENT ENGINE CONFIG ADDITIONS
════════════════════════════════════════════════════════════════════════════════

Add these settings to your existing config.py file.

These enable the 5 intelligent trading features:
1. Probabilistic Scoring
2. Market Regime Detection  
3. Short-Term Price Prediction
4. NIFTY Correlation Filter
5. Dynamic Position Sizing
"""


import logging
import time
import json
import os
from datetime import datetime, time as dt_time
from typing import Tuple, Any, Dict

logger = logging.getLogger('Config')
"""
CONFIG ADDITIONS v3.1 - MORE TRADES + ADAPTIVE EXITS
═══════════════════════════════════════════════════════════════════════════════

ADD THESE TO YOUR config.py FILE!

New Settings for:
1. Lower score thresholds
2. Trade starvation prevention
3. Adaptive exit parameters
4. More generous position sizing

Author: Trading System v5.1
Date: 2026-01-16
"""

# ═══════════════════════════════════════════════════════════════════════════════
# INTELLIGENT ENGINE v1.1 - LOWER THRESHOLDS FOR MORE TRADES
# ═══════════════════════════════════════════════════════════════════════════════

USE_INTELLIGENT_ENGINE = True

# Score thresholds (OPTIMIZED for better win rate!)
#INTELLIGENT_SCORE_STRONG = 90     # Keep at 75 - Full position (best quality)
#INTELLIGENT_SCORE_MODERATE = 80   # Was 60 → Now 65 (raise quality bar)
#INTELLIGENT_SCORE_WEAK = 70       # Was 45 → Now 60 (minimum acceptable)
#INTELLIGENT_SCORE_SKIP = 70       # Was 45 → Now 60 (reject scores <60)
                                   # Expected: Filter out 30% of weak signals
                                   # Expected: Win rate improvement 37% → 55%+

# Enable mixed market trading
ENABLE_MIXED_MARKET_TRADING = True

# Minimum score to trade (base, will be adjusted by starvation prevention)
MIXED_MARKET_MIN_SCORE = 70  # Was 45 → Now 60 (reject weak signals)

# ═══════════════════════════════════════════════════════════════════════════════
# TRADE STARVATION PREVENTION - GUARANTEE MINIMUM TRADES!
# ═══════════════════════════════════════════════════════════════════════════════

# Enable starvation prevention
ENABLE_STARVATION_PREVENTION = False

# Minimum trades per day target
MIN_DAILY_TRADES = 1

# When to start reducing threshold (if no trades yet)
STARVATION_REDUCTION_START = "11:30"  # After 11:30 AM

# How much to reduce threshold
STARVATION_REDUCTION_STEP = 5   # Reduce by 5 points
STARVATION_REDUCTION_INTERVAL = 30  # Every 30 minutes

# Maximum reduction
STARVATION_MAX_REDUCTION = 15   # Don't reduce more than 15 points

# Emergency mode (after this time with 0 trades, use minimum threshold)
STARVATION_EMERGENCY_TIME = "14:00"  # 2:00 PM

# Absolute minimum threshold (HARD FLOOR - starvation prevention can NEVER go below this)
# v5.1.1 FIX: Raised from 35→45 to match skip threshold. Starvation was lowering
# quality standards when trades were blocked by position limits (2/2), not by scores.
STARVATION_MINIMUM_THRESHOLD = 45  # Never go below skip threshold

# ═══════════════════════════════════════════════════════════════════════════════
# DEPRECATED (v5.6): These thresholds are NOT used by any active code path.
# Active scoring thresholds are in PH2_SCORE_* (Phase 2) and
# INTELLIGENT_SCORE_SKIP (orchestrator intelligent integration).
# Kept for reference only — safe to remove in future cleanup.
# ═══════════════════════════════════════════════════════════════════════════════
SCORE_THRESHOLD_STRONG = 80    # DEPRECATED — not consumed
SCORE_THRESHOLD_MODERATE = 70  # DEPRECATED — not consumed
SCORE_THRESHOLD_WEAK = 60      # DEPRECATED — not consumed
SCORE_THRESHOLD_SKIP = 60      # DEPRECATED — not consumed

# ═══════════════════════════════════════════════════════════════════════════════
# AUTO-LOAD / AUTO-SCAN ON STARTUP (v3.1.1)
# ═══════════════════════════════════════════════════════════════════════════════

# If True: Automatically load stocks from ACTIVE.json on startup
# If file is stale/missing, trigger immediate Phase 1 scan
AUTO_SCAN_ON_STARTUP = True

# Maximum age (in hours) for ACTIVE.json to be considered valid
MAX_ACTIVE_FILE_AGE_HOURS = 24

# ═══════════════════════════════════════════════════════════════════════════════
# ADAPTIVE EXIT PARAMETERS
# ═══════════════════════════════════════════════════════════════════════════════

ENABLE_ADAPTIVE_EXITS = True

# Trailing Stop Settings
TRAILING_ATR_MULTIPLIER = 1.0     # Was 1.5 → Now 1.0 (tighter trail = lock profits)
TRAILING_ACTIVATION_PCT = 0.5     # Was 0.8 → Now 0.5 (activate earlier at +0.5% profit)
MIN_TRAILING_DISTANCE_PCT = 0.3   # Was 0.5 → Now 0.3 (tighter minimum trail)

# Momentum Exit Settings (RSI)
MOMENTUM_RSI_PEAK = 55            # RSI was above this
MOMENTUM_RSI_EXIT = 48            # RSI dropped below this = exit
RSI_OVERBOUGHT_EXIT = 80          # Was 72 → Now 80 (let winners run longer before RSI exit)

# Momentum Exit Settings (MACD)
MACD_NEGATIVE_BARS_EXIT = 3       # Exit after 3 consecutive negative bars

# Time Decay Settings
TIME_STAGNATION_MINUTES = 45      # Exit if no new high for 45 min
MAX_HOLD_MINUTES = 120             # Was 1440 → Now 120 (2 hours max for intraday)
MIN_PROGRESS_PCT = 0.3            # Need at least 0.3% progress
STAGNATION_DROP_PCT = 0.5         # Exit if price dropped this % from session high while profitable

# Partial Exit Settings
ENABLE_PARTIAL_EXITS = True
PARTIAL_EXIT_PCT = 0.5            # Exit 50% at first target
PARTIAL_TARGET_R_MULTIPLE = 1.0   # First target at 1R

# Move stop to breakeven after partial
BREAKEVEN_AFTER_PARTIAL = True

# ═══════════════════════════════════════════════════════════════════════════════
# REGIME-SPECIFIC SETTINGS (Override defaults based on market condition)
# ═══════════════════════════════════════════════════════════════════════════════

REGIME_SETTINGS = {
    'TRENDING_UP': {
        'position_mult': 1.0,
        'target_mult': 1.3,
        'use_partial': False,    # Hold for full target
        'use_time_exit': False,  # Don't time-exit in trend
        'trailing_mult': 2.0     # Wide trail
    },
    'TRENDING_DOWN': {
        'position_mult': 0.6,
        'target_mult': 0.7,
        'use_partial': True,
        'use_time_exit': True,
        'trailing_mult': 1.0     # Tight trail
    },
    'RANGE_BOUND': {
        'position_mult': 0.8,
        'target_mult': 0.8,
        'use_partial': True,
        'use_time_exit': True,
        'trailing_mult': 1.2
    },
    'HIGH_VOLATILITY': {
        'position_mult': 0.6,
        'target_mult': 1.0,
        'use_partial': True,
        'use_time_exit': True,
        'trailing_mult': 2.5     # Very wide trail
    },
    'MIXED': {
        'position_mult': 0.7,    # Was 0.6 - increased!
        'target_mult': 0.9,
        'use_partial': True,
        'use_time_exit': True,
        'trailing_mult': 1.5
    }
}

# ═══════════════════════════════════════════════════════════════════════════════
# LOGGING & NOTIFICATIONS
# ═══════════════════════════════════════════════════════════════════════════════

# Detailed scoring logs
LOG_DETAILED_SCORES = True

# Send intelligent analysis via Telegram
SEND_INTELLIGENT_ANALYSIS = True

# Send exit notifications
SEND_EXIT_NOTIFICATIONS = True

# Alert on starvation prevention activation
ALERT_ON_STARVATION = True
# ═══════════════════════════════════════════════════════════════════════════════
# INTELLIGENT ENGINE SETTINGS
# ═══════════════════════════════════════════════════════════════════════════════

# Enable/Disable Intelligent Engine
USE_INTELLIGENT_ENGINE = True

# Score thresholds (0-100)
INTELLIGENT_SCORE_STRONG = 85     # Full position
INTELLIGENT_SCORE_MODERATE = 80   # 75% position
INTELLIGENT_SCORE_WEAK = 70       # 50% position (mixed market trades!)
INTELLIGENT_SCORE_SKIP = 70       # Below this = no trade

# Enable trading in mixed markets (key feature!)
ENABLE_MIXED_MARKET_TRADING = True

# Minimum score to trade in mixed market
MIXED_MARKET_MIN_SCORE = 70

# ═══════════════════════════════════════════════════════════════════════════════
# MARKET REGIME SETTINGS
# ═══════════════════════════════════════════════════════════════════════════════

# ADX threshold for trend detection
ADX_TRENDING_THRESHOLD = 25
ADX_RANGING_THRESHOLD = 20

# ATR ratio thresholds for volatility
ATR_HIGH_VOLATILITY = 1.5
ATR_LOW_VOLATILITY = 0.7

# Regime-specific targets (override defaults when detected)
REGIME_TARGETS = {
    'TRENDING_UP': {'target': 3.0, 'stop': 2.0},
    'TRENDING_DOWN': {'target': 2.0, 'stop': 1.5},
    'RANGE_BOUND': {'target': 1.5, 'stop': 1.0},
    'HIGH_VOLATILITY': {'target': 2.5, 'stop': 2.0},
    'MIXED': {'target': 2.0, 'stop': 1.5}
}

# ═══════════════════════════════════════════════════════════════════════════════
# NIFTY CORRELATION SETTINGS
# ═══════════════════════════════════════════════════════════════════════════════

# Use NIFTY as trade filter
USE_NIFTY_CORRELATION = True

# NIFTY change threshold for trend classification
NIFTY_BULLISH_THRESHOLD = 0.3    # +0.3% = bullish
NIFTY_BEARISH_THRESHOLD = -0.3   # -0.3% = bearish

# Boost score when stock oversold + NIFTY bullish
NIFTY_ALIGNMENT_BONUS = 5

# ═══════════════════════════════════════════════════════════════════════════════
# PRICE PREDICTION SETTINGS
# ═══════════════════════════════════════════════════════════════════════════════

# Enable short-term price prediction
USE_PRICE_PREDICTION = True

# Minimum confidence to boost score
PREDICTION_MIN_CONFIDENCE = 60

# Score boost/reduction based on prediction
PREDICTION_BOOST_FACTOR = 1.1    # +10% score if predict UP with confidence
PREDICTION_REDUCE_FACTOR = 0.85  # -15% score if predict DOWN

# ═══════════════════════════════════════════════════════════════════════════════
# DYNAMIC POSITION SIZING
# ═══════════════════════════════════════════════════════════════════════════════

# Enable confidence-based position sizing
USE_DYNAMIC_POSITION_SIZING = True

# Position size multipliers by signal strength
POSITION_SIZE_STRONG = 1.0       # 100% of base capital
POSITION_SIZE_MODERATE = 0.75    # 75% of base capital
POSITION_SIZE_WEAK = 0.5         # 50% of base capital (mixed market)

# Regime position multipliers
REGIME_POSITION_MULT = {
    'TRENDING_UP': 1.0,
    'TRENDING_DOWN': 0.5,
    'RANGE_BOUND': 0.75,
    'HIGH_VOLATILITY': 0.5,
    'MIXED': 0.6
}

# ═══════════════════════════════════════════════════════════════════════════════
# SCORING WEIGHTS (must sum to 100)
# ═══════════════════════════════════════════════════════════════════════════════

SCORING_WEIGHTS = {
    'technical': 25,      # EMA, MA, trend alignment
    'momentum': 20,       # RSI, MACD, rate of change
    'volume': 15,         # Volume confirmation
    'support': 15,        # Support proximity, V-recovery
    'sentiment': 10,      # News sentiment
    'nifty_correlation': 15  # Market alignment
}

# ═══════════════════════════════════════════════════════════════════════════════
# LOGGING & NOTIFICATIONS
# ═══════════════════════════════════════════════════════════════════════════════

# Send intelligent analysis via Telegram
SEND_INTELLIGENT_ANALYSIS = True

# Log detailed scoring breakdown
LOG_DETAILED_SCORES = True
# ════════════════════════════════════════════════════════════════════════════
# ✅ FIX #13: SECRETS MASKING UTILITY
# ════════════════════════════════════════════════════════════════════════════

def mask_secret(secret: str, show_chars: int = 4) -> str:
    """
    Mask a secret string for safe logging.
    Shows first N and last N characters only.
    
    Example: "sk-proj-abc123xyz789" -> "sk-p****789"
    """
    if not secret or len(secret) <= show_chars * 2:
        return "****"
    return f"{secret[:show_chars]}****{secret[-show_chars:]}"


def safe_json_load(filepath: str, default: Any = None) -> Any:
    """
    ✅ FIX #11: Safe JSON loading with schema validation.
    Returns default value if file missing or invalid.
    """
    try:
        if not os.path.exists(filepath):
            logger.warning(f"JSON file not found: {filepath}")
            return default if default is not None else {}
        
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in {filepath}: {e}")
        return default if default is not None else {}
    except Exception as e:
        logger.error(f"Error loading {filepath}: {e}")
        return default if default is not None else {}


def safe_json_get(data: dict, key: str, default: Any = None) -> Any:
    """
    ✅ FIX #11: Safe dictionary access with default.
    Prevents KeyError on missing fields.
    """
    try:
        return data.get(key, default)
    except (AttributeError, TypeError):
        return default


# ============================================================================
# CONFIGURATION CLASS - ALL SETTINGS IN ONE PLACE
# ============================================================================

class Config:
    """
    Master configuration for the autonomous trading system.
    Version: 5.0.1 (Fixed)
    """

    # ╔══════════════════════════════════════════════════════════════════════════╗
    # ║  MASTER PAPER MODE — 1-MONTH VERIFICATION PERIOD (2026-04-20 onwards)  ║
    # ║  Set to True = all phases run paper-only, no real orders placed.        ║
    # ║  Set to False = re-enables live execution per phase flags below.        ║
    # ╚══════════════════════════════════════════════════════════════════════════╝
    MASTER_PAPER_MODE = True   # ← PAPER MODE ENABLED (flip to False for live)

    # Paper trade log — all phases write here for 1-month review
    PAPER_TRADE_LOG_XLSX = "data/Paper_Trade_Log.xlsx"

    # ============================================================
    # V-RECOVERY SCAN PARAMETERS
    # ============================================================
    
    MIN_PRICE = 900   # aligned with Phase 1 (strategy range 900-3500)
    MAX_PRICE = 3500
    V_RECOVERY_MIN_DROP_PCT = 1.0     # Was 0.75 → Now 1.0 (stronger patterns)
                                       # Require minimum 1% drop for quality signals
                                       # Expected: Better entry quality, higher win rate
    V_RECOVERY_MIN_RECOVERY_PCT = 30   # Minimum recovery % to qualify as V-pattern
    V_RECOVERY_MAX_RECOVERY_PCT = 80   # Reject over-extended recoveries (already ran)
    V_RECOVERY_TOLERANCE_PCT = 0.20
    TREND_DAYS = 50
    MIN_BOUNCE_QUALITY = 7
    MIN_RISK_REWARD_RATIO = 2.0
    MAX_STOCKS_TO_SCAN = 150
    
    OUTPUT_FILE = "data/selected_stocks_{timestamp}.json"
    ACTIVE_STOCKS_FILE = "data/phase1_outputs/ACTIVE.json"
    ENTRY_SIGNALS_FILE = "data/phase2_outputs/entry_signals.json"
    
    # ============================================================
    # SECTOR HEALTH FILTER (Filter 2B)
    # ============================================================
    
    ENABLE_SECTOR_FILTER = True
    
    SECTOR_INDEX_MAP = {
        'IT': 'NIFTY IT',
        'BANKING': 'NIFTY BANK',
        'FINANCE': 'NIFTY FIN SERVICE',
        'PHARMA': 'NIFTY PHARMA',
        'AUTO': 'NIFTY AUTO',
        'FMCG': 'NIFTY FMCG',
        'METAL': 'NIFTY METAL',
        'REALTY': 'NIFTY REALTY',
        'ENERGY': 'NIFTY ENERGY',
        'INFRASTRUCTURE': 'NIFTY INFRA',
        'MEDIA': 'NIFTY MEDIA',
        'PSU BANK': 'NIFTY PSU BANK',
        'PRIVATE BANK': 'NIFTY PRIVATE BANK',
        'CONSUMER DURABLES': 'NIFTY CONSUMER DURABLES',
        'OIL & GAS': 'NIFTY OIL & GAS',
        'HEALTHCARE': 'NIFTY HEALTHCARE INDEX',
        'DIVERSIFIED': 'NIFTY 50',
    }
    
    STOCK_SECTOR_MAP = {
        'INFY': 'IT', 'TCS': 'IT', 'WIPRO': 'IT', 'HCLTECH': 'IT', 'TECHM': 'IT', 'LTIM': 'IT',
        'HDFCBANK': 'BANKING', 'ICICIBANK': 'BANKING', 'KOTAKBANK': 'BANKING', 'AXISBANK': 'BANKING',
        'SBIN': 'PSU BANK', 'BANKBARODA': 'PSU BANK', 'PNB': 'PSU BANK', 'CANBK': 'PSU BANK',
        'BAJFINANCE': 'FINANCE', 'BAJAJFINSV': 'FINANCE', 'HDFC': 'FINANCE',
        'SUNPHARMA': 'PHARMA', 'DRREDDY': 'PHARMA', 'CIPLA': 'PHARMA', 'DIVISLAB': 'PHARMA',
        'MARUTI': 'AUTO', 'TATAMOTORS': 'AUTO', 'M&M': 'AUTO', 'HEROMOTOCO': 'AUTO', 'BAJAJ-AUTO': 'AUTO',
        'HINDUNILVR': 'FMCG', 'ITC': 'FMCG', 'NESTLEIND': 'FMCG', 'BRITANNIA': 'FMCG', 'DABUR': 'FMCG',
        'TATASTEEL': 'METAL', 'JSWSTEEL': 'METAL', 'HINDALCO': 'METAL', 'VEDL': 'METAL',
        'RELIANCE': 'ENERGY', 'ONGC': 'ENERGY', 'IOC': 'ENERGY', 'BPCL': 'ENERGY', 'GAIL': 'ENERGY',
        'NTPC': 'ENERGY', 'POWERGRID': 'ENERGY', 'ADANIGREEN': 'ENERGY', 'ADANIPOWER': 'ENERGY',
        'DLF': 'REALTY', 'GODREJPROP': 'REALTY', 'OBEROIRLTY': 'REALTY',
        'LT': 'INFRASTRUCTURE', 'ADANIENT': 'INFRASTRUCTURE', 'ADANIPORTS': 'INFRASTRUCTURE',
        'TITAN': 'CONSUMER DURABLES', 'HAVELLS': 'CONSUMER DURABLES', 'VOLTAS': 'CONSUMER DURABLES',
        'APOLLOHOSP': 'HEALTHCARE', 'FORTIS': 'HEALTHCARE', 'MAXHEALTH': 'HEALTHCARE',
        'ASIANPAINT': 'DIVERSIFIED', 'ULTRACEMCO': 'DIVERSIFIED', 'GRASIM': 'DIVERSIFIED',
    }
    
    SECTOR_THRESHOLDS = {
        'IT': -1.0, 'BANKING': -0.8, 'FINANCE': -0.8, 'PHARMA': -0.7,
        'AUTO': -1.0, 'FMCG': -0.5, 'METAL': -1.2, 'REALTY': -1.0,
        'ENERGY': -1.0, 'INFRASTRUCTURE': -1.0, 'MEDIA': -1.0,
        'PSU BANK': -1.2, 'PRIVATE BANK': -0.8, 'CONSUMER DURABLES': -0.8,
        'OIL & GAS': -1.0, 'HEALTHCARE': -0.7, 'DIVERSIFIED': -1.0,
    }
    
    # ============================================================
    # WEEKLY ANCHOR FILTER (Filter 2C)
    # ============================================================
    
    ENABLE_WEEKLY_ANCHOR = True
    WEEKLY_MA_PERIOD = 20
    WEEKLY_DATA_WEEKS = 52
    
    # ============================================================
    # DEBUG / EXPORT SETTINGS
    # ============================================================
    EXPORT_HISTORICAL_DATA = False  # Export CSV files for debugging
    EXPORT_DIRECTORY = "historical_data"  # Directory to save CSV files
    DETAILED_FILTER_OUTPUT = True  # Detailed filter logging
    
    # ============================================================
    # PHASE 1 STOCK SELECTION
    # ============================================================
    PRICE_MIN = 900   # Minimum stock price (aligned with Phase 1)
    PRICE_MAX = 3500  # Maximum stock price (aligned with Phase 1)
    MASTER_LIST_SIZE = 150  # Scan top N liquid NSE stocks
    MIN_VOLUME_ABSOLUTE = 50000  # Absolute volume floor for stock filtering
    MIN_ATR_PERCENT = 0.5        # Minimum ATR as % of price (need volatility)
    MAX_ATR_PERCENT = 8.0        # Maximum ATR % (avoid chaotic stocks)
    
    # ============================================================
    # v5.3.0 QUALITY FILTERS (Phase 2 — replaces dead EntryFilters)
    # ============================================================
    VOLUME_BURST_MIN_RATIO = 1.3     # Min volume spike ratio for entry
    QUALITY_ADX_MIN = 15.0           # ADX below this = choppy, no trend
    QUALITY_ADX_MAX = 45.0           # ADX above this = extreme trend, risky for V-recovery
    QUALITY_MAX_BELOW_MA20_PCT = -5.0  # Max % below MA20 allowed
    MAX_CANDIDATES_PER_CYCLE = 5     # Max signals to score per cycle (rank first, score top N)
    FINBERT_MARKET_CONFIDENCE = 80   # Market-level FinBERT block confidence threshold
    
    # ============================================================
    # v5.3.0 RAMP DETECTOR (Kalman + MA + Rising Lows)
    # ============================================================
    RAMP_RSI_ZONE_LOW = 10.0         # RSI below this = capitulation, not ramp
    RAMP_RSI_ZONE_HIGH = 35.0        # RSI above this = already recovered (climb phase)
    # v5.3.1 RSI CALIBRATION (from real 15min charts):
    #   RSI 10-35: Ramp detection zone (accumulation/bottoming)
    #   RSI 35-40: Transition zone (ramp completing)
    #   RSI 40-60: CLIMB phase (real price momentum starts)
    #   RSI 60-80: STRONG CLIMB (best price gains happen here!)
    #   RSI 80-85: Caution zone (momentum may slow)
    #   RSI > 85:  Exhaustion (true overbought on 15min candles)
    RSI_UPPER_BOUND_HARD = 85.0      # Only block above this (was 70 — killed profitable trades)
    RAMP_MA_PERIOD = 5               # MA period for RSI smoothing
    RAMP_MA_SLOPE_RISING = 0.3       # Slope threshold for RISING
    RAMP_MA_SLOPE_FALLING = -0.3     # Slope threshold for FALLING
    RAMP_RISING_LOW_TOLERANCE = 1.5  # Tolerance for "rising" lows (Kalman-smoothed)
    RAMP_MIN_READINGS_LOWS = 8       # Min readings before checking lows
    RAMP_KALMAN_PROCESS_NOISE = 0.5  # Kalman process noise (RSI is noisy)
    RAMP_KALMAN_MEASUREMENT_NOISE = 4.0  # Kalman measurement noise
    RAMP_KALMAN_VEL_STRONG = 0.5     # Velocity > this = strong positive
    RAMP_KALMAN_VEL_MILD = 0.2       # Velocity > this = mild positive
    RAMP_MIN_READINGS = 10           # Min RSI history length for detection

    # ═══════════════════════════════════════════════════════════
    # PHASE 2 v5.3.2 SCORING ENGINE
    # ═══════════════════════════════════════════════════════════

    # Hard gates
    PH2_ADX_FLOOR = 15.0                      # ADX < this = block (choppy)
    # v5.3.4: PH2_ADX_CEILING REMOVED — trending stocks (ADX 30-50) are ideal
    #         for V-Recovery. Scoring F4 handles graduated penalty instead.
    PH2_RSI_CEILING = 85.0                    # RSI >= this = block (exhausted)

    # RSI Zone Tracker
    PH2_RSI_ZONE_LOW = 40.0                   # Bears active below 40 (short entry zone)
    PH2_RSI_ZONE_HIGH = 60.0                  # Bulls active above 60 (long entry zone)
    PH2_RSI_TRIGGER_LOW = 35.0                # Trigger fires when RSI rises above this
    PH2_RSI_TRIGGER_HIGH = 45.0               # Optimal trigger ceiling
    PH2_RSI_CAPITULATION = 10.0               # Below this = capitulation block
    PH2_MIN_READINGS_BEFORE_TRIGGER = 6       # ~30 min on 5-min candles

    # Scoring thresholds
    PH2_SCORE_ENTRY_MIN = 45                  # 1-share marker entry: low risk, so loose gate (was 65)
    PH2_SCORE_FULL_POSITION = 70              # Score for full position (v5.4: was 80)
    PH2_SCORE_STRONG_BUY = 80                 # Score for STRONG_BUY (v5.4: was 90)

    # Position sizing multipliers
    PH2_MULTIPLIER_FULL = 1.0                 # Score >= 80
    PH2_MULTIPLIER_MODERATE = 0.75            # Score 70-79

    # Volume burst scoring thresholds
    PH2_VOL_EXCELLENT = 2.0                   # 15 points
    PH2_VOL_GOOD = 1.5                        # 12 points
    PH2_VOL_MIN = 1.3                         # 8 points

    # VWAP
    PH2_VWAP_ACTIVE_AFTER_HOUR = 10           # VWAP scoring starts at 10 AM

    # Trend
    PH2_TREND_MAX_BELOW_MA20 = -5.0           # Below this = 0 points (falling knife)

    # ============================================================
    # v5.4: LIMIT ORDER ENTRY + ChatGPT S/R-BASED STOPS
    # ============================================================

    # Master switches
    USE_CHATGPT_ENTRY_PRICE = True            # Use ChatGPT's suggested_entry_price for LIMIT orders
    USE_CHATGPT_STOP_TARGET = True            # Use ChatGPT's S/R-aligned stop/target (absolute prices)

    # LIMIT order settings
    LIMIT_ORDER_TIMEOUT = 60                  # Seconds to wait for LIMIT fill before MARKET fallback
    LIMIT_ORDER_MAX_SLIP_PCT = 0.5            # Max % below LTP that LIMIT price can be set
    LIMIT_ORDER_POLL_INTERVAL = 2             # Seconds between fill status polls

    # Sanity bounds for ChatGPT S/R-based stops/targets
    CHATGPT_STOP_MIN_PCT = 0.5               # Min stop distance % (don't be too tight)
    CHATGPT_STOP_MAX_PCT = 5.0               # Max stop distance % (don't be too wide)
    CHATGPT_TARGET_MIN_PCT = 1.0             # Min target distance %
    CHATGPT_TARGET_MAX_PCT = 10.0            # Max target distance %

    # ═══════════════════════════════════════════════════════════════
    # v5.5: ChatGPT Role Separation
    # ═══════════════════════════════════════════════════════════════
    CHATGPT_MODE = 'LANDMINE_ONLY'          # 'LANDMINE_ONLY' (v5.5) or 'FULL_ANALYSIS' (v5.4 rollback)

    # v5.5: Price Level Anchoring (replaces ChatGPT S/R)
    USE_PRICE_LEVEL_STOPS = True             # Use PDH/PDL for stop/target instead of ChatGPT S/R
    PRICE_LEVEL_STOP_BUFFER_PCT = 0.3        # Place stop 0.3% below PDL (not exactly at it)
    PRICE_LEVEL_TARGET_BUFFER_PCT = 0.3      # Place target 0.3% below PDH (sellers sit at exact level)
    PRICE_LEVEL_PROXIMITY_PCT = 2.0          # PDH/PDL only used if within 2% of entry price
                                             # (if PDL is 5% below entry, ATR stop is better)

    # ============================================================
    # v5.6: MARKET REGIME SIZING
    # ChatGPT outlook adjusts Phase 3 entry quantity
    # BULLISH=1.0x, NEUTRAL=0.85x, MIXED=0.6x, BEARISH=0.4x, DEFENSIVE=block
    # ============================================================
    MARKET_REGIME_ENABLED = True              # Use ChatGPT outlook for entry sizing
    MARKET_REGIME_DEFAULT = 'NEUTRAL'         # Default when no GPT data available

    # ============================================================
    # MASTER STOCK LIST - SINGLE SOURCE OF TRUTH
    # Used by: Phase 1 (stock selection scan), Phase 5 (gap strategy scan)
    # Add/remove stocks HERE only — all phases read from this list
    # ============================================================
    # ⚠️  UPDATED 2026-09-24: Only stocks with active NSE F&O options are kept.
    # Strategy: V-Recovery on equity → options play on 2nd dip.
    # 34 stocks removed (no options): LALPATHLAB, MRF, TATAMOTORS, IRCTC, ZOMATO,
    #   ACC, IGL, LTIM, LTTS, BERGEPAINT, ABFRL, BATAINDIA, CADILAHC, CERA, GLAND,
    #   GLAXO, HONAUT, IPCA, KAJARIACER, MCDOWELL-N, METROPOLIS, MINDTREE, NATCOPHARM,
    #   PEL, PFIZER, PGHH, RAMCOCEM, SANOFI, STAR, SYMPHONY, SYNGENE, TORNTPOWER, WHIRLPOOL
    # 10 liquid F&O stocks added: TVSMOTOR, FEDERALBNK, SHRIRAMFIN, MUTHOOTFIN,
    #   POLYCAB, OFSS, JIOFIN, LICI, MAXHEALTH, OBEROIRLTY
    MASTER_STOCK_LIST = [
        # NIFTY 50 Core — all have options
        'RELIANCE', 'TCS', 'HDFCBANK', 'INFY', 'ICICIBANK',
        'HINDUNILVR', 'SBIN', 'BHARTIARTL', 'ITC', 'KOTAKBANK',
        'LT', 'AXISBANK', 'BAJFINANCE', 'ASIANPAINT', 'MARUTI',
        'TITAN', 'SUNPHARMA', 'ULTRACEMCO', 'NESTLEIND', 'WIPRO',
        'HCLTECH', 'BAJAJFINSV', 'TECHM', 'POWERGRID', 'NTPC',
        'ONGC', 'M&M', 'TATASTEEL', 'ADANIPORTS',
        'COALINDIA', 'DIVISLAB', 'HINDALCO', 'JSWSTEEL', 'GRASIM',
        'DRREDDY', 'INDUSINDBK', 'BRITANNIA', 'SHREECEM', 'APOLLOHOSP',
        'CIPLA', 'EICHERMOT', 'BPCL', 'HEROMOTOCO', 'BAJAJ-AUTO',
        'TATACONSUM', 'SBILIFE', 'PIDILITIND', 'HAVELLS', 'DABUR',
        # NIFTY Next 50 + Liquid Mid-Caps — options verified
        'GODREJCP', 'ADANIENT', 'HDFCLIFE', 'ICICIGI', 'AMBUJACEM',
        'BOSCHLTD', 'BANDHANBNK', 'SIEMENS', 'INDIGO',
        'MARICO', 'COLPAL', 'DLF', 'LUPIN', 'TORNTPHARM',
        'CHOLAFIN', 'GAIL', 'VEDL',
        'ADANIGREEN', 'SRF', 'NAUKRI', 'MOTHERSON',
        'CONCOR', 'MPHASIS',
        'BIOCON', 'PERSISTENT', 'COFORGE',
        'HINDZINC', 'LICHSGFIN', 'IDFCFIRSTB', 'AUBANK', 'BANKBARODA',
        'PFC', 'RECLTD', 'NMDC', 'SAIL', 'JINDALSTEL',
        'TATAPOWER', 'ADANIPOWER', 'PNB', 'CANBK', 'IOC',
        # Defence / PSU / New-Age — options verified
        'BHEL', 'HAL', 'BEL', 'PAGEIND',
        'ABCAPITAL', 'DMART', 'PAYTM',
        'NYKAA', 'TATAELXSI', 'VOLTAS',
        # High Beta / Specialty — options verified
        'GODREJPROP', 'ASHOKLEY', 'MANAPPURAM',
        'PETRONET', 'UPL', 'LAURUSLABS',
        'ALKEM', 'AUROPHARMA', 'JUBLFOOD', 'TRENT',
        'CROMPTON', 'DIXON', 'AMBER',
        # New additions — liquid F&O stocks not previously in list
        'TVSMOTOR', 'FEDERALBNK', 'SHRIRAMFIN', 'MUTHOOTFIN',
        'POLYCAB', 'OFSS', 'JIOFIN', 'LICI', 'MAXHEALTH', 'OBEROIRLTY',
    ]
    
    # ============================================================
    # ZERODHA API CREDENTIALS 
    # ============================================================
    # ✅ FIX #13: Support environment variables (more secure)
    # Falls back to hardcoded values if env vars not set
    
    ZERODHA_API_KEY = os.environ.get('ZERODHA_API_KEY', "v5jxo2jrno6fsp9g")
    ZERODHA_API_SECRET = os.environ.get('ZERODHA_API_SECRET', "8zqyhfkaxtor582pdprt4g3ix1bvokxe")
    ZERODHA_USER_ID = os.environ.get('ZERODHA_USER_ID', "YV4062")
    ZERODHA_PASSWORD = os.environ.get('ZERODHA_PASSWORD', "Sandheba@98")
    ZERODHA_TOTP_SECRET = os.environ.get('ZERODHA_TOTP_SECRET', "BRO74SETKV2PZVWTWEX7MCZZLWVI7KE6")

    # ═══════════════════════════════════════════════════════════════════
    # ✅ KITE ALIASES - main_orchestrator.py expects these names
    # ═══════════════════════════════════════════════════════════════════
    KITE_API_KEY = ZERODHA_API_KEY
    KITE_API_SECRET = ZERODHA_API_SECRET
    KITE_USER_ID = ZERODHA_USER_ID
    KITE_PASSWORD = ZERODHA_PASSWORD
    KITE_TOTP_SECRET = ZERODHA_TOTP_SECRET
    # ═══════════════════════════════════════════════════════════════════

    
    # ============================================================
    # CHATGPT AI ANALYSIS CONFIGURATION
    # ============================================================
    
    ENABLE_AI_ANALYSIS = True

    # Anthropic API Key
    ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY', "")

    # Kept for backward compatibility
    CHATGPT_API_KEY = ANTHROPIC_API_KEY
    OPENAI_API_KEY = ANTHROPIC_API_KEY

    # One switch for the most capable model (strategy, options, briefings). Cheap tactical gates stay on Haiku.
    AI_MODEL_TOP = "claude-fable-5-1"
    MARKER_AI_ENABLED = True           # AI expert review of 2nd-dip options setups (falls back to rules)
    AI_MODEL = AI_MODEL_TOP
    AI_MAX_TOKENS = 3000
    AI_TEMPERATURE = 0.2
    
    # ============================================================
    # WEEK 3-4 TRADING RULES
    # ============================================================
    
    ENABLE_WEEK_FILTERING = True
    TRADING_WEEKS = [1, 2]
    
    # ============================================================
    # CONTINUOUS SCANNING CONFIGURATION
    # ============================================================
    
    SCAN_INTERVAL_MINUTES = 30
    MARKET_OPEN_HOUR = 9
    MARKET_OPEN_MINUTE = 15
    MARKET_CLOSE_HOUR = 15
    MARKET_CLOSE_MINUTE = 30
    
    # ============================================================
    # TELEGRAM BOT CONFIGURATION
    # ============================================================
    
    ENABLE_TELEGRAM = True
    TELEGRAM_BOT_TOKEN = "7461127617:AAHBsM3ljSrU369AbloySczjABVJDTmnipA"
    TELEGRAM_CHAT_ID = "8331900078"
    
    # ─────────────────────────────────────────────────────────────
    # v4.6.0 NEW: ADAPTIVE TELEGRAM + BOT LISTENER + SYSTEM HEALTH
    # ─────────────────────────────────────────────────────────────
    
    # Feature 1: Adaptive Telegram Frequency (GPT-driven)
    ADAPTIVE_TELEGRAM_ENABLED = True       # Enable GPT-based send/skip decision
    ADAPTIVE_TELEGRAM_MODEL = "claude-haiku-4-5"  # Fast model for frequency decisions
    ADAPTIVE_TELEGRAM_SIGNIFICANCE_THRESHOLD = 6  # GPT score >= this → SEND
    ADAPTIVE_TELEGRAM_QUIET_SUMMARY_MINUTES = 15  # After N min silence, send quiet summary
    ADAPTIVE_TELEGRAM_RSI_CHANGE_THRESHOLD = 3.0  # RSI change > this = significant
    ADAPTIVE_TELEGRAM_MAX_SILENCE_MINUTES = 20  # Force update after N minutes no matter what
    
    # Feature 2: System Health Monitoring
    SYSTEM_HEALTH_ENABLED = True           # Enable periodic health telegrams
    SYSTEM_HEALTH_INTERVAL_MINUTES = 30    # Send health every N minutes
    
    # Feature 3: Two-Way Bot Command Listener
    BOT_LISTENER_ENABLED = True            # Enable listening for user commands
    BOT_LISTENER_POLL_INTERVAL = 3         # Poll every N seconds for new commands
    BOT_LISTENER_AUTHORIZED_CHAT_IDS = ["8331900078"]  # Only respond to these chat IDs
    
    # ============================================================
    # PHASE 2: ENTRY TIMING CONFIGURATION
    # ============================================================
    
    ENABLE_PHASE2 = True
    MAX_STOCK_AGE_DAYS = 2
    
    PHASE2_UPDATE_INTERVAL = 300

    # Phase 2: Monitoring timeout — drop stock if no signal after 2 hours
    PHASE2_MONITORING_TIMEOUT_MINUTES = 120
    RSI_PERIOD = 14
    RSI_CANDLE_INTERVAL = "5minute"
    
    RSI_OVERSOLD_SEVERE = 20
    RSI_OVERSOLD = 30
    RSI_ENTRY_MAX = 35
    RSI_CONFIRMATION = 35
    RSI_MAX_CONFIRMATION = 65  # v5.1.0 FIX: Soft ceiling for exhaustion warning (was 40, should be 65)
    
    # ✅ UPDATED: Entry window timing
    # Start: 09:15 - Entry allowed at market open (filters protect against bad signals)
    # End: 15:05 - Allow entries until 5 minutes before market close
    PHASE2_ENTRY_WINDOW_START = "09:15"
    PHASE2_ENTRY_WINDOW_END = "15:05"
    PHASE2_ABSOLUTE_CUTOFF = "15:05"
    
    MAX_LOTS_PER_STOCK = 5
    MAX_TOTAL_POSITIONS = 2  # ₹8,500 supports max 2 positions safely
    LOT_SIZE_CASH = 8000
    EMERGENCY_BUFFER = 1000
    
    TRADING_SEGMENT = "CASH"
    EXCHANGE = "NSE"
    PRODUCT_TYPE = "CNC"
    ORDER_TYPE = "MARKET"

    # MARKER STRATEGY: buy 1 share as a radar; options are suggested on the 2nd dip
    MARKER_MODE_ENABLED = True
    MARKER_QUANTITY = 1
    MARKER_BUY_ON_CONFIRMATION = True  # buy the marker once Phase 1 confirms V-Recovery and score >= entry min (skip RSI trigger)
    MARKER_DISASTER_STOP_PCT = 8.0     # only automatic exit
    MARKER_TARGET_PCT = 25.0           # GTT target kept far so it never fires in a 5-6 day hold
    MARKER_MAX_HOLD_DAYS = 6
    # 2nd-dip sensor (5-min bars, Kalman values normalised as % of price)
    MARKER_DIP_MIN_PCT = 3.0           # dip from post-entry peak (sim-tuned 2026-09-24)
    MARKER_CONFIRM_BOUNCE_PCT = 0.4    # close must be this far above the dip low
    MARKER_BOTTOM_FRESH_BARS = 12      # low must be within the last hour
    MARKER_USE_KALMAN = True
    MARKER_KALMAN_ACCEL_MIN = 0.001    # %/bar² — fall decelerating
    MARKER_KALMAN_VEL_MIN = -0.02      # %/bar — fall nearly stopped
    MANUAL_OPT_CHECK_INTERVAL_SEC = 120
    
    # ═══════════════════════════════════════════════════════════════════
    # ✅ FIX #3: DEPRECATED SETTINGS REMOVED
    # ═══════════════════════════════════════════════════════════════════
    # These settings were from options trading and caused confusion.
    # The ACTUAL settings used are PROFIT_TARGET_PCT and STOP_LOSS_PCT.
    # Commented out to prevent confusion:
    #
    # STOP_LOSS_PERCENT = 5.0      # DEPRECATED - Was for options
    # TARGET_PERCENT = 40.0        # DEPRECATED - Was for options  
    # MIN_RISK_REWARD = 5.0        # DEPRECATED - Not used
    # ═══════════════════════════════════════════════════════════════════
    
    NIFTY_THRESHOLD = -1.0
    
    VWAP_ENABLED = True
    MACD_FAST = 5
    MACD_SLOW = 13
    MACD_SIGNAL = 8
    ATR_PERIOD = 14
    
    MIN_VOLUME_RATIO = 1.5
    STRONG_VOLUME_RATIO = 1.5
    
    PHASE2_CHATGPT_ENABLED = True
    PHASE2_CHATGPT_CALL_SCHEDULE = ["09:15", "09:45", "10:15"]
    PHASE2_MIN_CONFIDENCE = 50
    
    RECONFIRM_TREND = True
    RECONFIRM_VOLUME = True
    RECONFIRM_MOMENTUM = True
    RECONFIRM_PATTERN = True
    
    # ============================================================
    # KALMAN FILTER CONFIGURATION (v4.2.0)
    # ============================================================
    # For price prediction, velocity tracking, and acceleration detection
    # Part of "Aircraft Architecture" enhancement
    
    ENABLE_KALMAN_FILTER = True  # Set to True when ready for production
    
    # Kalman Filter Parameters
    KALMAN_DT = 1.0                      # Time step in minutes (for 1-min candles)
    KALMAN_PROCESS_NOISE = 0.01          # Process noise (Q) - model uncertainty
    KALMAN_MEASUREMENT_NOISE = 0.5       # Measurement noise (R) - price noise
    KALMAN_PREDICTION_HORIZON = 15       # Predict 15 minutes ahead
    KALMAN_ADAPTIVE = True               # Use adaptive noise based on ATR
    
    # Predictive Stop-Loss Integration
    ENABLE_PREDICTIVE_STOP = True       # Requires Kalman filter
    PREDICTIVE_MIN_PROFIT_PCT = 0.3      # Minimum profit before predictive exit
    PREDICTIVE_VELOCITY_DECAY_THRESHOLD = -0.8  # Velocity decay trigger
    
    # ============================================================
    # AI INTELLIGENCE MODULE (v5.0.0)
    # ============================================================
    
    ENABLE_AI_INTELLIGENCE = True
    
    # FinBERT Settings
    # Pi-lite branch: off by default — needs torch/transformers (~2GB, slow on
    # ARM). Flip to True only if those are installed. See PI_SETUP.md.
    ENABLE_FINBERT = os.environ.get('ENABLE_FINBERT', 'false').lower() == 'true'
    FINBERT_CONFIDENCE_THRESHOLD = 70
    FINBERT_SENTIMENT_WEIGHT = 0.3
    FINBERT_USE_TEMPORAL_DECAY = True
    FINBERT_HALF_LIFE_HOURS = 4
    FINBERT_ENTITY_FILTER = True
    
    # ATR-Based Dynamic Targets
    ENABLE_ATR_DYNAMIC_TARGETS = True
    ATR_PERIOD_AI = 14
    ATR_TARGET_MULTIPLIER = 2.0      # Was 3.5 → Now 2.0 (reachable targets!)
    ATR_STOP_MULTIPLIER = 1.8        # Was 2.0 → Now 1.8 (balanced stop width)
                                      # RR = 2.0/1.8 = 1.11 but hit rate >> 60%
    ATR_MIN_TARGET_PCT = 1.0
    ATR_MAX_TARGET_PCT = 5.0
    ATR_MIN_STOP_PCT = 1.5
    ATR_MAX_STOP_PCT = 3.0
    ATR_FALLBACK_TARGET_PCT = 3.0
    ATR_FALLBACK_STOP_PCT = 2.0
    
    # Adaptive RSI
    ENABLE_ADAPTIVE_RSI = True
    ADAPTIVE_RSI_LOOKBACK_DAYS = 30
    ADAPTIVE_RSI_OVERSOLD_PERCENTILE = 30
    ADAPTIVE_RSI_OVERBOUGHT_PERCENTILE = 70
    ADAPTIVE_RSI_MIN_THRESHOLD = 25
    ADAPTIVE_RSI_MAX_THRESHOLD = 40
    ADAPTIVE_RSI_FALLBACK = 35
    
    # ═══════════════════════════════════════════════════════════════════════════
    # ✅ STOCK-SPECIFIC RSI THRESHOLDS (v2.3.0 - Adaptive RSI Bridge)
    # ═══════════════════════════════════════════════════════════════════════════
    #
    # Each stock has unique RSI bounce characteristics!
    # - RAMCOCEM bounces at RSI 42 (higher floor)
    # - NIFTY bounces at RSI 32 (lower floor)
    # - BAJFINANCE bounces at RSI 30 (standard)
    #
    # Format: {symbol: (lower_bound, bounce_level, upper_bound, confidence)}
    # - lower_bound: Minimum RSI for entry consideration
    # - bounce_level: Historical bounce point (crossover confirmation)
    # - upper_bound: Maximum RSI for entry zone
    # - confidence: 0.0-1.0 (higher = more reliable threshold)
    #
    # ═══════════════════════════════════════════════════════════════════════════
    
    ENABLE_STOCK_SPECIFIC_RSI = True  # Use stock-specific thresholds if available
    
    # Stock-specific RSI thresholds (update based on your historical analysis)
    STOCK_RSI_THRESHOLDS = {
        # Format: 'SYMBOL': (lower, bounce, upper, confidence)
        
        # High-floor stocks (bounce earlier)
        'RAMCOCEM': (38, 42, 48, 0.85),
        'ULTRACEMCO': (35, 40, 48, 0.80),
        'AMBUJACEM': (36, 41, 47, 0.78),
        
        # Index/ETF (lower floor)
        'NIFTY': (28, 32, 38, 0.90),
        'NIFTY 50': (28, 32, 38, 0.90),
        'BANKNIFTY': (26, 30, 36, 0.88),
        
        # Banking stocks
        'HDFCBANK': (28, 33, 40, 0.82),
        'ICICIBANK': (27, 32, 39, 0.80),
        'SBIN': (25, 30, 38, 0.78),
        'KOTAKBANK': (28, 33, 40, 0.80),
        'AXISBANK': (26, 31, 38, 0.78),
        'BAJFINANCE': (25, 30, 38, 0.75),
        'BAJAJFINSV': (24, 29, 37, 0.72),
        
        # IT stocks (typically lower RSI floor)
        'TCS': (24, 28, 36, 0.82),
        'INFY': (23, 27, 35, 0.80),
        'WIPRO': (22, 26, 34, 0.75),
        'HCLTECH': (24, 28, 36, 0.78),
        'TECHM': (23, 27, 35, 0.76),
        
        # Auto stocks
        'TATAMOTORS': (26, 31, 39, 0.80),
        'MARUTI': (28, 33, 41, 0.78),
        'M&M': (27, 32, 40, 0.76),
        'HEROMOTOCO': (29, 34, 42, 0.74),
        'BAJAJ-AUTO': (30, 35, 43, 0.76),
        
        # Pharma stocks
        'SUNPHARMA': (26, 31, 39, 0.78),
        'DRREDDY': (27, 32, 40, 0.76),
        'CIPLA': (25, 30, 38, 0.74),
        'DIVISLAB': (28, 33, 41, 0.72),
        
        # Energy/Oil
        'RELIANCE': (27, 32, 40, 0.85),
        'ONGC': (24, 29, 37, 0.72),
        'BPCL': (23, 28, 36, 0.70),
        'IOC': (22, 27, 35, 0.68),
        
        # Metal/Mining
        'TATASTEEL': (24, 29, 37, 0.76),
        'JSWSTEEL': (25, 30, 38, 0.74),
        'HINDALCO': (24, 29, 37, 0.72),
        'COALINDIA': (26, 31, 39, 0.70),
        
        # FMCG (typically higher floor)
        'HINDUNILVR': (32, 37, 45, 0.80),
        'ITC': (30, 35, 43, 0.82),
        'NESTLEIND': (33, 38, 46, 0.78),
        'BRITANNIA': (31, 36, 44, 0.76),
        
        # Infra/Capital goods
        'LTIM': (26, 31, 39, 0.74),
        'LT': (28, 33, 41, 0.78),
        'ADANIENT': (22, 27, 35, 0.68),
        'ADANIPORTS': (24, 29, 37, 0.70),
        
        # Telecom
        'BHARTIARTL': (28, 33, 41, 0.80),
        
        # Others
        'TITAN': (30, 35, 43, 0.78),
        'ASIANPAINT': (32, 37, 45, 0.76),
        'POWERGRID': (28, 33, 41, 0.74),
        'NTPC': (27, 32, 40, 0.72),
    }
    
    # Default threshold for stocks not in the list
    STOCK_RSI_DEFAULT = (25, 30, 38, 0.60)
    
    # Market regime adjustments
    STOCK_RSI_HIGH_VOL_EXPAND = 0.20   # Expand range by 20% in high volatility
    STOCK_RSI_LOW_VOL_CONTRACT = 0.15  # Contract range by 15% in low volatility
    
    # Volatility Clustering
    ENABLE_VOLATILITY_CLUSTERING = True
    VOL_LOOKBACK_DAYS = 90
    VOL_N_CLUSTERS = 3
    VOL_ATR_PERIOD = 10
    VOL_LOW_MULTIPLIER = 1.0
    VOL_MEDIUM_MULTIPLIER = 0.75
    VOL_HIGH_MULTIPLIER = 0.5
    
    # AI Cache & Logging
    AI_CACHE_ENABLED = True
    AI_CACHE_FILE = "data/ai_intelligence_cache.json"
    AI_DETAILED_LOGGING = True
    AI_LOG_FILE = "logs/ai_intelligence.log"
    
    # ============================================================
    # CHATGPT STRATEGIC ADVISOR
    # ============================================================
    
    ENABLE_CHATGPT_STRATEGIC_ADVISOR = True
    STRATEGIC_ADVISOR_MODEL = AI_MODEL_TOP
    
    USE_ADVISOR_FOR_POSITION_SIZING = True
    USE_ADVISOR_FOR_EXIT_STRATEGY = True
    USE_ADVISOR_FOR_ORDER_PARAMS = True
    USE_ADVISOR_FOR_PORTFOLIO_RISK = True
    

    # ═══════════════════════════════════════════════════════════════════
    # 🤖 AUTONOMOUS SYSTEM - GPT DECISION POINTS (v2.0 NEW!)
    # ═══════════════════════════════════════════════════════════════════
    
    # GPT Model Selection
    GPT_MODEL = AI_MODEL_TOP
    
    # Decision #1: Entry Signal Approval (Most Critical)
    GPT_APPROVE_ENTRIES = True
    GPT_ENTRY_MIN_CONFIDENCE = 60  # Reject if GPT confidence < this
    
    # Decision #2: Position Sizing
    GPT_POSITION_SIZING = True
    GPT_POSITION_MULTIPLIER_MIN = 0.5   # Minimum 50%
    GPT_POSITION_MULTIPLIER_MAX = 2.0   # Maximum 200%
    # Monitoring sleep intervals (seconds)
    TIER1_SLEEP_SECONDS = 10   # MIS/Phase 5 scalps — fast monitoring
    TIER2_SLEEP_SECONDS = 60   # CNC positions / idle — slower cycle
    # Decision #3: Adaptive Scan Decisions
    GPT_ADAPTIVE_SCAN_DECISIONS = True
    GPT_SCAN_MIN_CONFIDENCE = 60  # Skip scan if GPT confidence < this
    
    # Decision #4: End-of-Day Shutdown
    GPT_SHUTDOWN_DECISIONS = True
    GPT_SHUTDOWN_MIN_CONFIDENCE = 70  # Don't shutdown unless GPT > this
    GPT_SHUTDOWN_MIN_TIME_REMAINING = 10  # Only consult GPT if >X min to close
    
    # Fallback Behavior (When GPT Fails)
    GPT_FALLBACK_APPROVE_ENTRIES = True  # Allow trades on GPT failure?
    GPT_FALLBACK_POSITION_MULTIPLIER = 0.75  # Conservative sizing on failure
    GPT_FALLBACK_ALLOW_SCANS = True  # Allow scans on GPT failure?
    GPT_FALLBACK_CONTINUE_TRADING = True  # Don't shutdown on GPT failure
    
    # Kalman Filter Integration
    KALMAN_PREDICTION_HORIZON = 3  # Predict N steps ahead (5-min × 3 = 15 min)
    KALMAN_VELOCITY_GATE = False  # Reject if velocity < 0?
    KALMAN_MIN_CONFIDENCE = 50  # Reject if Kalman confidence < this
    
    # ═══════════════════════════════════════════════════════════════════

    ADVISOR_CACHE_PORTFOLIO_RISK = True
    ADVISOR_MIN_PNL_FOR_EXIT_CALC = 2.0
    
    # ============================================================
    # PHASE 3: ORDER EXECUTION CONFIGURATION
    # ============================================================
    
    ENABLE_PHASE3 = True   # Phase 3 runs behind PaperKiteProxy while MASTER_PAPER_MODE=True (no real orders)
    # ═══════════════════════════════════════════════════════════════════════════
    # V3.4.0 ADDITIONS - NON-BLOCKING ARCHITECTURE
    # ═══════════════════════════════════════════════════════════════════════════
    
    # Admission Control
    MAX_ACTIVE_POSITIONS = 3
    MAX_CAPITAL_DEPLOYED = 50000
    MAX_CAPITAL_PCT = 0.9
    
    # Recovery System
    EMERGENCY_SL_OFFSET_PCT = -2.0
    EMERGENCY_SL_ATR_MULTIPLIER = 1.5
    USE_ATR_BASED_SL = True
    RECOVERY_PRIORITY_TIMEOUT_HOURS = 1.0
    RECOVERY_MAX_TIMEOUT_HOURS = 2.0
    FORCE_EXIT_ON_RECOVERY_TIMEOUT = True
    
    # ChatGPT Integration
    CHATGPT_TIMEOUT_SECONDS = 5
    CHATGPT_MAX_RETRIES = 3
    CHATGPT_DEGRADED_MODE_DURATION = 300
    
    # v4.8.1: Order Fill Wait Configuration
    ORDER_FILL_WAIT_SECONDS = 90  # Wait up to 90s for order fill (prevents premature cancellation)

    # v1.4.0: Trade Confirmation Gate
    # When True, system does NOT auto-execute orders.
    # Instead it sends a Telegram card and waits for the user to reply /done SYMBOL
    # (trade was manually placed) or /skip SYMBOL (skip this trade).
    # Useful for users without VPN/static IP who trade manually via Kite.
    TRADE_CONFIRMATION_GATE_ENABLED = False   # Set True for manual-only users
    TRADE_CONFIRMATION_TIMEOUT_SEC  = 180     # 3 minutes — warn and discard if no reply
    
    # Task Scheduling
    INTERRUPT_PRIORITY_ENABLED = True
    POSITION_STATE_TRACKING = True
    MIN_PHASE2_FREQUENCY = 60
    MIN_PHASE3_FREQUENCY = 10
    MIN_RECOVERY_FREQUENCY = 30
    
    TOTAL_CAPITAL = 15000  # Actual Zerodha balance as of 2026-03-30

    # v2.1.0: CNC overnight max-loss cap per trade.
    # GTT stop fires with loss ≤ this amount. CHOLAFIN (-₹559) + PAYTM (-₹643)
    # were both GTT disasters — this cap would have capped each to ≤₹150.
    CNC_MAX_LOSS_CAP = 150  # ₹ maximum loss allowed on a single CNC GTT stop

    # ═══════════════════════════════════════════════════════════════════
    # CAPITAL SIZING FOR ₹8,500 ACCOUNT
    # ═══════════════════════════════════════════════════════════════════
    # ₹3,500 × 2 positions = ₹7,000 (82% of capital)
    # Preserves ₹1,500 buffer for fees + emergency
    #
    BASE_CAPITAL_PER_TRADE = 6000  # 2 × ₹6,000 = ₹12,000 (80% of ₹15,000 + ₹3,000 buffer)
    
    # ═══════════════════════════════════════════════════════════════════
    # v5.3.3: CAPITAL MANAGEMENT — CapitalManager SSOT settings
    # ═══════════════════════════════════════════════════════════════════
    CAPITAL_MANAGEMENT = {
        'MAX_CONCENTRATION_PCT': 0.40,      # Max 40% of capital in single stock
                                             # 40% of ₹9,411 = ₹3,764 → fits 1× ₹1,800 stock
        'ABSOLUTE_MAX_ENTRIES': 1,           # 1 stock only — the BEST pick wins
                                             # CNC is conviction validator, not profit engine
        'MIN_CAPITAL_BUFFER': 1500,          # Keep ₹1,500 reserve
        'MAX_SYNC_AGE': 300,                 # 5 min staleness guard
        'ENABLE_ADAPTIVE_LIMITS': True,      # AI-adjusted limits
        'MIS_MARGIN_PCT': 0.20,              # 20% MIS margin
        'CNC_MARGIN_PCT': 1.00,              # 100% CNC (full delivery)
    }
    # ═══════════════════════════════════════════════════════════════════
    
    # ═══════════════════════════════════════════════════════════════════
    # ✅ FIX #4: DEPRECATED SETTING REMOVED
    # ═══════════════════════════════════════════════════════════════════
    # QUANTITY_PER_TRADE = 1  # DEPRECATED - Now using BASE_CAPITAL + AI
    # ═══════════════════════════════════════════════════════════════════
    
    MAX_POSITIONS_PER_STOCK = 2
    
    ENTRY_START_HOUR = 9
    ENTRY_START_MIN = 15
    ENTRY_END_HOUR = 14
    ENTRY_END_MIN = 0
    
    EXIT_START_HOUR = 11
    EXIT_START_MIN = 0
    EXIT_END_HOUR = 14
    EXIT_END_MIN = 0
    
    # ═══════════════════════════════════════════════════════════════════
    # ACTUAL PROFIT/LOSS TARGETS (THESE ARE USED!)
    # ═══════════════════════════════════════════════════════════════════
    # v5.3.3: Smart TCAS for CNC — same philosophy as Phase 5 MIS
    # Target is ASPIRATIONAL (ILS ceiling), not exit trigger
    # Real exit comes from Smart TCAS trailing + Kalman deceleration
    PROFIT_TARGET_PCT = 5.0     # Aspirational ceiling for ILS (was 2.0%)
    STOP_LOSS_PCT = 2.0         # Fallback % stop (used when ATR unavailable)
    
    # CNC Smart TCAS parameters
    CNC_TCAS_ACTIVATION_PCT = 0.7   # Lock breakeven at +0.7% profit
    CNC_TCAS_TRAIL_PCT = 0.5        # Trail: peak - 0.5%
    CNC_STOP_ATR_MULTIPLIER = 2.0   # Stop = entry - 2× ATR (stock-specific)
    # ═══════════════════════════════════════════════════════════════════
    
    POSITION_CHECK_INTERVAL = 300
    
    POSITIONS_FILE = "data/phase3_outputs/positions.json"
    ORDERS_FILE = "data/phase3_outputs/orders.json"
    TRADES_FILE = "data/phase3_outputs/trades.json"
    
    # Circuit Breaker
    MAX_DAILY_LOSS = 750  # ~5% of ₹15,000
    
    # Technical Scoring
    SCORE_RECOVERY_PCT = 30
    SCORE_RSI = 20
    SCORE_VWAP = 20
    SCORE_VOLUME = 15
    SCORE_TREND = 15
    
    # Phase 2 Output Files
    PHASE2_MONITORING_LOG = "data/phase2_outputs/monitoring_state_{date}.json"
    PHASE2_ENTRY_SIGNALS = "data/phase2_outputs/entry_signals_{date}.json"
    PHASE2_CHATGPT_CACHE = "data/phase2_outputs/chatgpt_analysis_cache.json"
    
    # Monitoring Heartbeat
    ENABLE_MONITORING_HEARTBEAT = True
    HEARTBEAT_INTERVAL_MINUTES = 15
    HEARTBEAT_SHOW_AI_STATUS = True
    HEARTBEAT_SHOW_RSI_DETAILS = True
    HEARTBEAT_SHOW_PRICE_CHANGE = True
    HEARTBEAT_TELEGRAM = True
    
    # ════════════════════════════════════════════════════════════════════════
    # ✅ FIX #13: SAFE CONFIG LOGGING (Masks Secrets)
    # ════════════════════════════════════════════════════════════════════════
    
    @classmethod
    def log_config_safe(cls):
        """Log configuration with masked secrets for debugging"""
        logger.info("=" * 60)
        logger.info("CONFIGURATION (Secrets Masked)")
        logger.info("=" * 60)
        logger.info(f"  Zerodha API Key: {mask_secret(cls.ZERODHA_API_KEY)}")
        logger.info(f"  Zerodha Secret: {mask_secret(cls.ZERODHA_API_SECRET)}")
        logger.info(f"  Zerodha User: {cls.ZERODHA_USER_ID}")
        logger.info(f"  Zerodha Password: {mask_secret(cls.ZERODHA_PASSWORD)}")
        logger.info(f"  TOTP Secret: {mask_secret(cls.ZERODHA_TOTP_SECRET)}")
        logger.info(f"  Anthropic Key: {mask_secret(cls.ANTHROPIC_API_KEY)}")
        logger.info(f"  Telegram Token: {mask_secret(cls.TELEGRAM_BOT_TOKEN)}")
        logger.info("-" * 60)
        logger.info(f"  Capital: ₹{cls.TOTAL_CAPITAL:,}")
        logger.info(f"  Per Trade: ₹{cls.BASE_CAPITAL_PER_TRADE:,}")
        logger.info(f"  Max Daily Loss: ₹{cls.MAX_DAILY_LOSS}")
        logger.info(f"  Phase 3 Enabled: {cls.ENABLE_PHASE3}")
        logger.info("=" * 60)
    
    @classmethod
    def validate_config(cls) -> bool:
        """Validate critical configuration values"""
        errors = []
        
        if not cls.ZERODHA_API_KEY or len(cls.ZERODHA_API_KEY) < 10:
            errors.append("ZERODHA_API_KEY missing or invalid")
        
        if not cls.ZERODHA_API_SECRET or len(cls.ZERODHA_API_SECRET) < 10:
            errors.append("ZERODHA_API_SECRET missing or invalid")
        
        if cls.TOTAL_CAPITAL < 5000:
            errors.append(f"TOTAL_CAPITAL too low: ₹{cls.TOTAL_CAPITAL}")
        
        if cls.BASE_CAPITAL_PER_TRADE > cls.TOTAL_CAPITAL:
            errors.append("BASE_CAPITAL_PER_TRADE exceeds TOTAL_CAPITAL")
        
        if errors:
            for err in errors:
                logger.error(f"❌ Config Error: {err}")
            return False
        
        logger.info("✅ Configuration validated successfully")
        return True

    # ═══════════════════════════════════════════════════════════════════
    # MARKET INTELLIGENCE ENGINE (MIE) v1.0.0
    # ═══════════════════════════════════════════════════════════════════

    ENABLE_MIE = True                          # Master switch

    # Individual layer switches
    ENABLE_MIE_VWAP = True                     # Layer 1: VWAP Context
    ENABLE_MIE_MOMENTUM = True                 # Layer 2: Optimized Momentum Stack
    ENABLE_MIE_V_RECOVERY = True               # Layer 3: V-Recovery Quality Scorer
    ENABLE_MIE_ATR = True                      # Layer 4: ATR Volatility Context
    ENABLE_MIE_COMPOSITE = True                # Layer 5: 100-Point Composite Scorer
    ENABLE_MIE_EXPIRY_CYCLE = True             # Layer 6: Expiry Cycle Awareness
    ENABLE_MIE_DECISION_HISTORY = True         # Layer 7: Decision History Feed
    ENABLE_MIE_PERFORMANCE = True              # Layer 8: Real vs Simulated Performance
    ENABLE_MIE_CAPITAL = True                  # Layer 9: Live Capital State
    ENABLE_MIE_CRASH_MATRIX = True             # Layer 10: Crash Interpretation Matrix

    # Layer-specific parameters
    MIE_VWAP_FALLBACK_STD_PCT = 1.0
    MIE_MACD_FAST = 5
    MIE_MACD_SLOW = 13
    MIE_MACD_SIGNAL = 8
    MIE_STOCHASTIC_K = 8
    MIE_STOCHASTIC_D = 3
    MIE_ADX_TREND_THRESHOLD = 25
    MIE_FIBONACCI_TOLERANCE = 5.0
    MIE_VOLUME_CONFIRMATION_THRESHOLD = 1.5
    MIE_ATR_NORMAL_THRESHOLD = 1.5
    MIE_ATR_ABNORMAL_THRESHOLD = 2.0
    MIE_ATR_STOP_MULTIPLIER = 2.0
    MIE_ATR_TARGET_MULTIPLIER = 3.0
    MIE_COMPOSITE_FULL_THRESHOLD = 85
    MIE_COMPOSITE_75_THRESHOLD = 70
    MIE_COMPOSITE_50_THRESHOLD = 60
    MIE_NSE_EXPIRY_WEEKDAY = 1               # Tuesday
    MIE_MIN_DECISIONS_FOR_INSIGHT = 10
    LAST_BACKTEST_WIN_RATE = 72.0

    # ══════════════════════════════════════════════════════════════════
    # PHASE 4 / PHASE 2 / PHASE 5 / PHASE 6 SETTINGS
    # (Restored to Config class — were orphaned at module level)
    # ══════════════════════════════════════════════════════════════════


    # ═══════════════════════════════════════════════════════════════════════════════
    # PHASE 4: AUTONOMOUS PORTFOLIO MANAGER CONFIGURATION
    # ═══════════════════════════════════════════════════════════════════════════════
    # Version: 4.3.0
    # Date: 2026-01-26
    # Description: Aviation-inspired position monitoring with TCAS/ILS/GTT
    # ═══════════════════════════════════════════════════════════════════════════════

    # ─────────────────────────────────────────────────────────────────────────────
    # PHASE 4: MASTER SWITCH
    # ─────────────────────────────────────────────────────────────────────────────

    ENABLE_PHASE4 = True  # Master switch for Phase 4 Portfolio Manager

    # ─────────────────────────────────────────────────────────────────────────────
    # PHASE 4: MONITORING INTERVALS
    # ─────────────────────────────────────────────────────────────────────────────

    PHASE4_MONITORING_INTERVAL_SEC = 30      # Main monitoring cycle (30 seconds)
    PHASE4_BROKER_SYNC_INTERVAL_SEC = 1800   # Broker sync (30 minutes) - Heavy API call
    PHASE4_CHATGPT_PERIODIC_MIN = 30         # ChatGPT review interval (30 minutes)
    PHASE4_GTT_CHECK_INTERVAL_SEC = 300      # GTT status check (5 minutes)

    # ─────────────────────────────────────────────────────────────────────────────
    # PHASE 4: DANGER ZONE THRESHOLDS
    # ─────────────────────────────────────────────────────────────────────────────

    PHASE4_DANGER_ZONE_PCT = -1.0            # Trigger ChatGPT when loss >= 1%
    PHASE4_CRITICAL_ZONE_PCT = -2.0          # Urgent action needed at 2% loss

    # ─────────────────────────────────────────────────────────────────────────────
    # PHASE 4: TCAS THRESHOLDS (ATR units)
    # ─────────────────────────────────────────────────────────────────────────────
    # TCAS = Traffic Collision Avoidance System (Stop-Loss Protection)
    # Alert Levels:
    #   CLEAR: > 2.0 ATR from stop (safe)
    #   TA (Traffic Advisory): 1.5-2.0 ATR (monitor closely)  
    #   RA (Resolution Advisory): 0.75-1.5 ATR (ChatGPT consultation)
    #   ALIM: < 0.75 ATR (IMMEDIATE EXIT - no ChatGPT)

    TCAS_TA_THRESHOLD_ATR = 2.0              # Traffic Advisory threshold
    TCAS_RA_THRESHOLD_ATR = 1.5              # Resolution Advisory threshold  
    TCAS_ALIM_THRESHOLD_ATR = 0.75           # Mandatory exit threshold

    # ─────────────────────────────────────────────────────────────────────────────
    # PHASE 4: ILS LANDING PHASES (% of target achieved)
    # ─────────────────────────────────────────────────────────────────────────────
    # ILS = Instrument Landing System (Profit Target Approach)
    # Phases:
    #   CRUISE: < 25% (no trailing)
    #   OUTER_MARKER: 25-50% (monitor)
    #   MIDDLE_MARKER: 50-75% (activate trailing)
    #   INNER_MARKER: 75-90% (tighten trailing)
    #   DECISION_HEIGHT: 90-95% (final approach)
    #   LANDING: > 95% (let GTT trigger)

    ILS_OUTER_MARKER_PCT = 25
    ILS_MIDDLE_MARKER_PCT = 50
    ILS_INNER_MARKER_PCT = 75
    ILS_DECISION_HEIGHT_PCT = 90

    # ─────────────────────────────────────────────────────────────────────────────
    # PHASE 4: HEALTH SCORE THRESHOLDS
    # ─────────────────────────────────────────────────────────────────────────────
    # Health Score = Composite (0-100) based on P&L, Momentum, TCAS, Time

    HEALTH_CRITICAL_THRESHOLD = 30           # Below = ChatGPT EXIT signal
    HEALTH_UNSTABLE_THRESHOLD = 50           # 30-50 = Unstable
    HEALTH_MARGINAL_THRESHOLD = 70           # 50-70 = Marginal

    # ─────────────────────────────────────────────────────────────────────────────
    # PHASE 4: GTT ORDER CONFIGURATION
    # ─────────────────────────────────────────────────────────────────────────────

    ENABLE_GTT_ORDERS = True                 # Place GTT stop/target after entry
    GTT_OVERNIGHT_STOP_BUFFER_PCT = 1.5      # Widen stop by 1.5% for overnight

    # v4.7.1 FIX-01: Configurable BUY order fill timeout
    # NSE LIMIT orders can take 30-90s in low-liquidity stocks
    # Previous hardcoded 10s (5 polls × 2s) caused premature cancellation
    BUY_FILL_MAX_POLL_ATTEMPTS = 15          # Number of polls (15 × 2s = 30s total)
    BUY_FILL_POLL_INTERVAL = 2              # Seconds between polls
    BUY_FILL_ALERT_AT_PCT = 50             # Send "still waiting" alert at 50% timeout

    # v4.7.1 FIX-04: GTT placement retry before manual stop fallback
    # Transient failures (network blip, rate limit) usually resolve in 2-3 seconds
    GTT_PLACEMENT_RETRIES = 2               # Max retries before falling to manual stop
    GTT_RETRY_DELAY_SECONDS = 3             # Delay between GTT retry attempts

    # ─────────────────────────────────────────────────────────────────────────────
    # PHASE 4: FILE PATHS
    # ─────────────────────────────────────────────────────────────────────────────

    MARKET_CONTEXT_FILE = "data/phase1_outputs/market_context.json"

    # ─────────────────────────────────────────────────────────────────────────────
    # PHASE 4: REGIME-SPECIFIC PARAMETERS  
    # ─────────────────────────────────────────────────────────────────────────────

    REGIME_PARAMS = {
        'SQUEEZE': {'stop_mult': 1.5, 'target_mult': 2.0, 'trail_pct': 1.0},
        'STRONG_TREND': {'stop_mult': 3.0, 'target_mult': 4.0, 'trail_pct': 2.0},
        'VOLATILE_TREND': {'stop_mult': 3.5, 'target_mult': 3.0, 'trail_pct': 1.5},
        'CHOPPY_VOLATILE': {'stop_mult': 2.0, 'target_mult': 1.5, 'trail_pct': 0.5},
        'RANGING_QUIET': {'stop_mult': 1.5, 'target_mult': 1.5, 'trail_pct': 1.0},
        'CRISIS': {'stop_mult': 4.0, 'target_mult': 2.0, 'trail_pct': 0.5},
        'NORMAL': {'stop_mult': 2.5, 'target_mult': 2.5, 'trail_pct': 1.5}
    }

    # ─────────────────────────────────────────────────────────────────────────────
    # PHASE 4: TIME-BASED SETTINGS
    # ─────────────────────────────────────────────────────────────────────────────

    PHASE4_LANDING_CHECK_TIME = "14:30"      # Landing probability analysis
    PHASE4_MIS_CUTOFF_TIME = "15:15"         # MIS positions must convert/exit
    PHASE4_MARKET_CLOSE_TIME = "15:25"       # Force close all MIS positions

    # ─────────────────────────────────────────────────────────────────────────────
    # PHASE 4: CHATGPT SETTINGS
    # ─────────────────────────────────────────────────────────────────────────────

    PHASE4_CHATGPT_COOLDOWN_SEC = 300        # Min 5 min between calls per position
    PHASE4_CHATGPT_EMERGENCY_BYPASS = True   # Bypass cooldown for TCAS RA alerts

    # ─────────────────────────────────────────────────────────────────────────────
    # PHASE 4: LOGGING
    # ─────────────────────────────────────────────────────────────────────────────

    PHASE4_LOG_DETAILED_CYCLES = False       # Log every monitoring cycle detail
    PHASE4_LOG_CHATGPT_RESPONSES = True      # Log full ChatGPT responses


    # ═══════════════════════════════════════════════════════════════════════════════
    # v4.4.0 PHASE 2 ENHANCEMENTS (2026-01-28) + v3.3.0 UPDATES (2026-02-03)
    # ═══════════════════════════════════════════════════════════════════════════════
    #
    # NEW: ADX Filter (v4.4.0) → CHANGED to advisory-only (v3.3.0, ChatGPT decides)
    # NEW: Volume Spike Detection at RSI reversal
    # NEW: Enhanced 100-point Entry Scoring System
    # REMOVED: RSI momentum sequence as HARD BLOCK (v3.3.0 "Symphony Killer" fix)
    # ENHANCED: FinBERT scoring contributes to entry score
    # ENHANCED: ChatGPT Trade Advisor receives ALL data (v3.3.0 wiring fix)
    # ENHANCED: Per-stock ADX calculated every monitoring cycle (v3.3.0)
    #
    # ═══════════════════════════════════════════════════════════════════════════════

    # ─────────────────────────────────────────────────────────────────────────────
    # ADX FILTER CONFIGURATION (v4.4.0 → v3.3.0 CHANGED TO ADVISORY)
    # ─────────────────────────────────────────────────────────────────────────────
    # ADX (Average Directional Index) measures trend strength.
    # V-Recovery is a MEAN REVERSION strategy - it FAILS in trending markets!
    #
    # ADX < 20:  WEAK/NO TREND   → V-Recovery WORKS! ✅
    # ADX 20-25: CONSOLIDATION   → V-Recovery WORKS! ✅
    # ADX 25-40: TRENDING        → V-Recovery may FAIL ⚠️
    # ADX > 40:  STRONG TREND    → V-Recovery will FAIL ❌
    #
    # v3.3.0: ADX is NO LONGER a hard block. Value passed to ChatGPT for
    # nuanced evaluation. GPT considers ADX alongside volume, Kalman, etc.
    # Per-stock ADX calculated every monitoring cycle in update_all_monitors().

    ENABLE_ADX_FILTER = True              # Master switch for ADX calculation
    ADX_PERIOD = 14                       # ADX calculation period (standard: 14)
    ADX_MAX_FOR_ENTRY = 25                # Advisory threshold (ChatGPT reference, not hard block)

    # ─────────────────────────────────────────────────────────────────────────────
    # VOLUME SPIKE DETECTION (v4.4.0 NEW!)
    # ─────────────────────────────────────────────────────────────────────────────
    # Volume spike at RSI reversal = Institutional buying confirmed!
    # This confirms the reversal is real, not just noise.

    ENABLE_VOLUME_SPIKE_FILTER = True     # Master switch for volume spike filter
    VOLUME_SPIKE_THRESHOLD = 2.0          # Strong spike: 2x average volume
    VOLUME_SPIKE_MIN_THRESHOLD = 1.5      # Minimum spike: 1.5x average
    VOLUME_SPIKE_LOOKBACK_CANDLES = 5     # Candles to analyze for spike

    # ─────────────────────────────────────────────────────────────────────────────
    # RSI MOMENTUM SEQUENCE (v4.4.0 → v3.3.0 REMOVED AS GATE)
    # ─────────────────────────────────────────────────────────────────────────────
    # v3.3.0: Momentum sequence is NO LONGER a hard block ("Symphony Killer" fix).
    # RSI above adaptive threshold = IMMEDIATE entry signal.
    # These values kept for scoring utilities and diagnostics only.

    RSI_MIN_SEQUENCE_LENGTH = 4           # Reference for scoring (not a gate)
    RSI_MIN_TOTAL_RISE = 5.0              # Reference for scoring (not a gate)

    # ─────────────────────────────────────────────────────────────────────────────
    # FINBERT ENHANCED SCORING (v4.4.0)
    # ─────────────────────────────────────────────────────────────────────────────
    # Old: FinBERT only blocked BEARISH trades (BULLISH ignored!)
    # New: FinBERT contributes points to entry score

    FINBERT_SCORING_ENABLED = True        # Enable FinBERT score contribution
    FINBERT_BULLISH_BONUS = 15            # BULLISH sentiment adds +15 points
    FINBERT_NEUTRAL_BONUS = 5             # NEUTRAL sentiment adds +5 points
    FINBERT_BEARISH_PENALTY = -20         # BEARISH sentiment subtracts -20 points

    # ─────────────────────────────────────────────────────────────────────────────
    # CHATGPT TRADE ADVISOR (v4.4.0 ENHANCED!)
    # ─────────────────────────────────────────────────────────────────────────────
    # Old: ChatGPTNewsAnalyzer asked "Should we trade today?" (useless!)
    # New: ChatGPT Trade Advisor asks "Should we enter THIS trade?" with ALL data

    ENABLE_CHATGPT_TRADE_ADVISOR = True   # Master switch
    GPT_APPROVE_ENTRIES = True            # Require GPT approval for entries
    GPT_MIN_CONFIDENCE_FOR_ENTRY = 60     # Minimum GPT confidence to enter

    # ─────────────────────────────────────────────────────────────────────────────
    # DEPRECATED (v5.6): Legacy v4.4.0 entry score thresholds.
    # NOT used by any active code path. Active thresholds are PH2_SCORE_*.
    # Kept for reference only — safe to remove in future cleanup.
    # ─────────────────────────────────────────────────────────────────────────────
    ENTRY_SCORE_STRONG_BUY = 75           # DEPRECATED — not consumed
    ENTRY_SCORE_MODERATE_BUY = 60         # DEPRECATED — not consumed
    ENTRY_SCORE_WEAK_BUY = 50             # DEPRECATED — not consumed
    ENTRY_SCORE_SKIP = 50                 # DEPRECATED — not consumed

    # ─────────────────────────────────────────────────────────────────────────────
    # TELEGRAM NOTIFICATION ENHANCEMENTS (v4.4.0)
    # ─────────────────────────────────────────────────────────────────────────────

    TELEGRAM_INCLUDE_ADX = True           # Include ADX in entry signals
    TELEGRAM_INCLUDE_VOLUME_SPIKE = True  # Include volume spike info
    TELEGRAM_INCLUDE_GPT_REASONING = True # Include ChatGPT reasoning (truncated)
    TELEGRAM_GPT_REASONING_LENGTH = 150   # Max characters for GPT reasoning


    # ═══════════════════════════════════════════════════════════════════════════════
    # PHASE 5: GAP STRATEGY CONFIGURATION (v4.7.0 NEW!)
    # ═══════════════════════════════════════════════════════════════════════════════
    # Independent daily trading system running 09:20-09:45 AM
    # Captures gap-up/gap-down reversions before Phase 1 starts
    #
    # Timeline:
    #   09:15 - Market opens
    #   09:15-09:18 - FinBERT sentiment check
    #   09:18-09:20 - Gap detection scan
    #   09:20-09:25 - Entry window
    #   09:40 - Trail stop to breakeven
    #   09:45 - Mandatory exit
    #   09:50 - Phase 1 starts (regular V-Recovery)

    # Master enable switch (can be toggled via Telegram /gap on/off)
    GAP_STRATEGY_ENABLED = True

    # ─────────────────────────────────────────────────────────────────────────────
    # GAP DETECTION THRESHOLDS (Tiered - tries P1 first, then P2, then P3)
    # ─────────────────────────────────────────────────────────────────────────────
    GAP_THRESHOLD_PRIORITY_1 = 1.5          # Strong gaps (searched first)
    GAP_THRESHOLD_PRIORITY_2 = 1.0          # Moderate gaps (if P1 empty)
    GAP_THRESHOLD_PRIORITY_3 = 0.75         # Weak gaps (last resort)

    # ─────────────────────────────────────────────────────────────────────────────
    # PROFIT/LOSS TARGETS — v5.3.3: Smart TCAS Scalp Design
    # ─────────────────────────────────────────────────────────────────────────────
    # No hard target cap. TCAS activates at +0.3%, rides momentum.
    # Kalman detects deceleration → exit. Minimum profit ≈ 0.3% guaranteed.
    # Config below is for reference — actual params are in GapStrategyConfig class.
    GAP_TCAS_ACTIVATION_PCT = 0.3           # TCAS engages after +0.3% profit
    GAP_STOP_ATR_MULTIPLIER = 1.2           # v5.7.0: Stop = 1.2x ATR (restored breathing room, was 0.5)

    # Phase 5 Gap Scoring (v5.5.0 additions)
    GAP_LARGE_RSI_OVERRIDE_PCT = 1.5        # v5.5.1: Gap >= this bypasses daily RSI lag (was 2.0)

    # DEPRECATED — kept for backward compatibility
    GAP_TARGET_PCT = 0.3                    # Legacy: TCAS activation level
    GAP_ATR_TARGET_MULTIPLIER = 0.25        # DEPRECATED (v5.3.3: no ATR-scaled target)
    GAP_ATR_TARGET_MIN_PCT = 0.2            # DEPRECATED
    GAP_ATR_TARGET_MAX_PCT = 1.0            # DEPRECATED
    GAP_MIN_STOP_PCT = 0.3                  # DEPRECATED (v5.3.3: no stop clamping)
    GAP_MAX_STOP_PCT = 1.0                  # DEPRECATED

    # ─────────────────────────────────────────────────────────────────────────────
    # POSITION SIZING
    # ─────────────────────────────────────────────────────────────────────────────
    GAP_MAX_POSITION_VALUE = 10000          # Max ₹10,000 per gap trade
    GAP_MIN_POSITION_VALUE = 5000           # Min ₹5,000 per gap trade
    GAP_POSITION_SIZE_PCT = 5.0             # 5% of total capital (adaptive)

    # ─────────────────────────────────────────────────────────────────────────────
    # FILTERS (All must pass for trade)
    # ─────────────────────────────────────────────────────────────────────────────
    GAP_MIN_VOLUME_RATIO = 1.0              # Volume must be > average
    GAP_MAX_ADX = 25                        # ADX must be < 25 (range-bound)

    # v5.3.5: Phase 5 price range (separate from CNC MIN/MAX_PRICE)
    # ₹800+ → meaningful absolute gap movement for MIS scalps
    # ₹3000 cap → keeps position within ₹10K MIS limit (3+ shares)
    PH5_MIN_PRICE = 800
    PH5_MAX_PRICE = 3000

    # FinBERT Sentiment Alignment:
    #   Gap Down (BUY)  → Requires BULLISH or NEUTRAL sentiment
    #   Gap Up (SELL)   → Requires BEARISH or NEUTRAL sentiment
    #   Misaligned sentiment → SKIP trade

    # ─────────────────────────────────────────────────────────────────────────────
    # TRADE LIMITS
    # ─────────────────────────────────────────────────────────────────────────────
    GAP_MAX_TRADES_PER_DAY = 1              # Only 1 gap trade per day (best setup)

    # ─────────────────────────────────────────────────────────────────────────────
    # PH5 LIVE/PAPER MODE — READ BY ORCHESTRATOR via getattr(self.config, ...)
    # NOTE: Must live in Config class, NOT BACKTEST_CONFIG.
    # Orchestrator: gap_config.PH5_PAPER_MODE = getattr(self.config, "PH5_PAPER_MODE", True)
    # If missing here → falls back to True → paper mode even when you want live.
    # ─────────────────────────────────────────────────────────────────────────────
    PH5_PAPER_MODE = True                   # PAPER — 1-month verification (was LIVE)

    # ─────────────────────────────────────────────────────────────────────────────
    # MONITORING
    # ─────────────────────────────────────────────────────────────────────────────
    GAP_MONITOR_INTERVAL_SECONDS = 5        # Check position every 5 seconds

    # ─────────────────────────────────────────────────────────────────────────────
    # TELEGRAM NOTIFICATIONS
    # ─────────────────────────────────────────────────────────────────────────────
    GAP_NOTIFY_ENTRY = True                 # Notify on entry
    GAP_NOTIFY_EXIT = True                  # Notify on exit
    GAP_NOTIFY_NO_GAPS = True               # Notify when no gaps found
    GAP_NOTIFY_FILTERS_FAILED = True        # Notify when filters fail

    # ─────────────────────────────────────────────────────────────────────────────
    # DECISION MATRIX (Reference - Logic in phase5_gap_strategy.py)
    # ─────────────────────────────────────────────────────────────────────────────
    # ┌─────────────────┬─────────────────┬─────────────────┬─────────────────┐
    # │    GAP TYPE     │ FINBERT BULLISH │ FINBERT NEUTRAL │ FINBERT BEARISH │
    # ├─────────────────┼─────────────────┼─────────────────┼─────────────────┤
    # │   GAP DOWN      │   ✅ BUY        │   ✅ BUY        │   ❌ SKIP       │
    # │   (< -0.75%)    │   (aligned)     │   (acceptable)  │   (conflict)    │
    # ├─────────────────┼─────────────────┼─────────────────┼─────────────────┤
    # │   GAP UP        │   ❌ SKIP       │   ✅ SELL       │   ✅ SELL       │
    # │   (> +0.75%)    │   (conflict)    │   (acceptable)  │   (aligned)     │
    # └─────────────────┴─────────────────┴─────────────────┴─────────────────┘


    # =============================================================================
    # v6.0: PHASE 6 OPTIONS ADVISORY (Paper Trading Only)
    # =============================================================================
    # ChatGPT-powered Bull Call Spread recommendations for stocks entering Phase 3.
    # Advisory only — no real options orders placed.
    # Tracks paper P&L to measure ChatGPT accuracy over time.

    PH6_OPTIONS_ADVISORY_ENABLED = True

    # Options chain parameters
    PH6_STRIKES_AROUND_ATM = 10          # ATM ±10 strikes to fetch
    PH6_MIN_OI_THRESHOLD = 1000          # Min OI for a strike to be usable
    PH6_MIN_VOLUME_THRESHOLD = 50        # Min volume for liquidity

    # ChatGPT
    PH6_CHATGPT_MIN_CONFIDENCE = 60      # Min confidence to log advisory

    # Paper trade monitoring
    PH6_PREMIUM_CHECK_INTERVAL_MIN = 30  # Re-check premiums every 30 min
    PH6_INSTRUMENTS_CACHE_HOURS = 4      # Refresh NFO instruments cache

    # Auto-close rules
    PH6_TARGET_PCT_OF_MAX = 80           # Close at 80% of max profit
    PH6_STOP_PCT_OF_MAX_LOSS = 100       # Close at 100% of max loss

    # Notifications
    PH6_NOTIFY_NEW_ADVISORY = True
    PH6_NOTIFY_PAPER_CLOSE = True
    PH6_NOTIFY_DAILY_SUMMARY = True

    # v6.1: Live Options Order Placement (gated behind master switch)
    PH6_LIVE_ORDERS_ENABLED = False          # PAPER — 1-month verification (was LIVE)
    PH6_OPTIONS_PRODUCT_TYPE = "MIS"         # MIS for intraday, NRML for carry-forward
    PH6_MAX_LOTS = 1                         # Safety cap — max lots per spread
    PH6_ENTRY_LIMIT_BUFFER_PCT = 0.5         # BUY at LTP+0.5%, SELL at LTP-0.5%
    PH6_EXIT_LIMIT_BUFFER_PCT = 0.3          # Tighter on exit for faster fill
    PH6_EOD_LIMIT_BUFFER_PCT = 1.0           # Wider on EOD for urgency
    PH6_ORDER_TIMEOUT_SECONDS = 45           # Max wait per leg before cancelling
    PH6_ORDER_POLL_INTERVAL = 2              # Poll kite.order_history every 2 sec
    PH6_ORDER_MAX_RETRIES = 3                # Retry failed exit legs

    # v6.2: Options TCAS — Graduated Profit Lock (ratcheting floor)
    PH6_TCAS_ENABLED = True
    PH6_TCAS_CHECK_INTERVAL_SEC = 120       # 2-min polling when TCAS active (vs 30-min idle)
    PH6_TCAS_TIERS = [
        # (trigger_pct, lock_floor_pct) — floor only ratchets UP, never down
        (10, 5),       # P&L reaches +10% → guarantee +5%
        (15, 10),      # P&L reaches +15% → guarantee +10%
        (20, 15),      # P&L reaches +20% → guarantee +15%
        (30, 25),      # P&L reaches +30% → guarantee +25%
        (50, 42),      # P&L reaches +50% → guarantee +42%
        (65, 58),      # P&L reaches +65% → tighten near target
    ]

    # ═══════════════════════════════════════════════════════════════════════════════
    # CANDLESTICK PATTERN DETECTOR v1.0.0
    # ═══════════════════════════════════════════════════════════════════════════════
    # Advisory layer — detects patterns and provides bonus confidence for Phase 6
    # and reversal warnings for Phase 4 TCAS. Does NOT generate entry signals.

    CANDLESTICK_PATTERN_ENABLED = True   # Master switch

    # --- Bullish Hammer thresholds ---
    HAMMER_WICK_RATIO = 2.0              # Lower wick must be >= Nx body size
    HAMMER_UPPER_WICK_MAX_PCT = 10.0     # Max upper wick as % of total range
    HAMMER_BODY_POSITION_MIN = 0.65      # Body must be in upper portion (0=bottom, 1=top)
    HAMMER_BODY_PCT_MAX = 33.0           # Max body size as % of total range

    # --- Bullish Engulfing thresholds ---
    ENGULF_RATIO_MIN = 1.2               # Current body must be >= 1.2x previous body

    # --- Bearish Pin Bar thresholds ---
    PINBAR_WICK_RATIO = 2.0              # Upper wick must be >= Nx body size
    PINBAR_LOWER_WICK_MAX_PCT = 10.0     # Max lower wick as % of total range
    PINBAR_BODY_POSITION_MAX = 0.35      # Body must be in lower portion
    PINBAR_BODY_PCT_MAX = 33.0           # Max body size as % of total range

    # --- Key Level Proximity ---
    PATTERN_LEVEL_PROXIMITY_PCT = 0.20   # How close to a level counts as "near" (% of price)
                                          # 0.20% of Rs.1000 = Rs.2.00 proximity zone

    # --- Bonus Points (applied to Phase 6 options confidence) ---
    PATTERN_BONUS_1_LEVEL = 5            # Pattern at 1 key level = +5 pts
    PATTERN_BONUS_2_LEVELS = 8           # Pattern at 2 key levels = +8 pts
    PATTERN_BONUS_3_LEVELS = 10          # Pattern at 3+ key levels = +10 pts

    # --- TCAS Pattern Warning ---
    PATTERN_TCAS_CAUTION_ACTION = 'MONITOR'     # Single resistance: monitor next 2 candles
    PATTERN_TCAS_ALERT_ACTION = 'TIGHTEN_SL'    # Multiple resistance: move SL to breakeven
    PATTERN_TCAS_ALERT_TRAIL_PCT = 50            # Trail 50% of unrealized profit on ALERT

    # ═══════════════════════════════════════════════════════════════════════════════
    # ORB (OPEN RANGE BREAKOUT) ADVISORY v1.0.0
    # ═══════════════════════════════════════════════════════════════════════════════
    # Passive detection of IB range compression and breakout/breakdown events.
    # Does NOT generate entry signals. Provides advisory data for Phase 4/6.

    ORB_ADVISORY_ENABLED = True              # Master switch

    # --- IB Range Classification ---
    ORB_IB_VERY_NARROW_PCT = 1.0            # Below 1.0% = highest breakout probability
    ORB_IB_NARROW_PCT = 1.5                 # Below 1.5% = good breakout probability
                                             # Above 1.5% = wide IB, ORB unlikely

    # --- Compression Detection ---
    ORB_TOUCH_PROXIMITY_PCT = 0.10          # How close to IB boundary counts as "touch"
                                             # 0.10% of Rs.800 = Rs.0.80 proximity zone
    ORB_MIN_TOUCHES = 3                      # Minimum boundary touches to detect compression
                                             # Must also have BW shrinking + volume declining

    # --- Breakout Confirmation ---
    ORB_BREAKOUT_BUFFER_PCT = 0.10          # Close must be 0.1% beyond IB boundary
    ORB_BREAKOUT_VOL_MULTIPLIER = 1.5       # Volume must be 1.5x average at breakout
    ORB_BREAKOUT_TARGET_MULTIPLIER = 2.0    # Target = breakout point + 2x IB range

    # --- Timing ---
    ORB_EXPIRY_HOUR = 13                    # Stop tracking after 1:00 PM (late breakouts unreliable)

    # --- Bonus Points (when Phase 6 pulls ORB data) ---
    ORB_COMPRESSION_BONUS = 8               # Compression detected = +8 to options confidence
    ORB_BREAKOUT_BONUS = 10                 # Confirmed breakout = +10 to options confidence
    ORB_BREAKOUT_TRAIL_PCT = 50             # Phase 4: Trail this % of profit on ORB breakout (50 = 50%)

    # --- Pattern Bonus Lifecycle ---
    PATTERN_BONUS_EXPIRY_CANDLES = 2        # Pattern bonus valid for this many 15-min candles

    # ─────────────────────────────────────────────────────────────────────────────
    # PHASE 6: DTE TIMELINE MANAGER
    # ─────────────────────────────────────────────────────────────────────────────
    # Safety gate that prevents options entries when expiry is too close.
    # Theta decay accelerates exponentially near expiry — even directionally
    # correct trades lose money when DTE is too low.

    PH6_DTE_GATE_ENABLED = True           # Master switch for DTE checks

    # --- Entry Gate Thresholds ---
    PH6_MIN_DTE = 3                       # HARD BLOCK below this DTE
                                           # DTE 0-1: always blocked
                                           # DTE 2-3: blocked unless rolled

    PH6_SWEET_SPOT_MIN_DTE = 8            # Ideal minimum DTE for entries
    PH6_SWEET_SPOT_MAX_DTE = 15           # Ideal maximum DTE for entries
    PH6_FAR_DTE = 25                      # Above this: premium expensive warning

    # --- Roll to Next Month ---
    PH6_ROLL_TO_NEXT_MONTH = True         # If current month DTE too low,
                                           # automatically use next month's expiry
                                           # False = just block, don't roll

    # --- DTE-Based Target Adjustment ---
    PH6_DTE_SHORT_TARGET_PCT = 60         # Target % when DTE is 4-7
                                           # (vs normal PH6_TARGET_PCT_OF_MAX = 80)
                                           # Take profits faster near expiry

    # --- Existing Position DTE Rules ---
    PH6_EXPIRY_EXIT_TIME = "14:30"        # Force-exit all positions on expiry day
                                           # by this time (before 3:00 PM close)
                                           # Avoids physical delivery / pin risk

    # ═══════════════════════════════════════════════════════════════════════════════
    # PH5A MASTER SWITCH (v5.5.0) — Telegram /ph5a on|off toggles PH5A_SNIPER_ENABLED
    # ═══════════════════════════════════════════════════════════════════════════════
    PH5A_ENABLED = True                              # MASTER switch for PH5A subsystem

    # ═══════════════════════════════════════════════════════════════════════════════
    # PH5A v2 SNIPER — Elite Filter (FIX 2)
    # ═══════════════════════════════════════════════════════════════════════════════
    PH5A_SNIPER_ENABLED = PH5A_ENABLED               # Runtime toggle (Telegram updates this)
    PH5A_PAPER_MODE = True                             # PAPER — 1-month verification (was LIVE)

    # ═══════════════════════════════════════════════════════════════
    # v5.9.0: PH5A INDEPENDENT MODE — Auto-fire after Phase 5 window
    # PH5A fires automatically when Phase 5 exclusive window ends
    # (09:55 by default). Rescans every N minutes if pipeline empty.
    # No ChatGPT gate — GUI toggle (OFF/PAPER/LIVE) is sole control.
    # ═══════════════════════════════════════════════════════════════
    PH5A_RESCAN_INTERVAL_MINUTES = 5        # Retry scan interval when pipeline empty (persistent hunter)

    # v5.6.0: Phase 5 MIS Exclusive Window
    # Phase 5 Gap Strategy has exclusive TIER1 monitoring until this time.
    # Phase 1 scans are BLOCKED until this time passes.
    # Phase 5 entry happens ~09:18-09:22, but MIS position needs
    # TIER1 (10s) monitoring attention until handoff.
    PH5_EXCLUSIVE_WINDOW_END_HOUR = 9
    PH5_EXCLUSIVE_WINDOW_END_MINUTE = 55

    PH5A_ELITE_MIN_SCORE = 75                    # Minimum sniper score (scaled for single-scan)
    PH5A_ELITE_MIN_REJECTIONS = 5                # Minimum rejection count at level (non-IB)
    PH5A_ELITE_IB_MIN_REJECTIONS = 2             # Minimum rejection count for IB levels
    PH5A_ELITE_MIN_CONFLUENCE = 3                # Minimum days level has been active
    PH5A_ELITE_MAX_DISTANCE = 0.3                # Maximum distance to level (%)
    PH5A_ELITE_LEVEL_TYPES = ['PDH', 'PDL', 'POC', 'MDH', 'MDL',
                               'IB_HIGH', 'IBH', 'IB_LOW', 'IBL',
                               'MULTI_DAY_HIGH', 'MULTI_DAY_LOW']
    PH5A_MAX_PIPELINE = 2                          # Max 2 hunts → max 2 trades per day

    # ═══════════════════════════════════════════════════════════════════════════════
    # PH5A v2 SNIPER — Timing (FIX 3)
    # ═══════════════════════════════════════════════════════════════════════════════
    PH5A_WATCH_END_TIME = "10:30"                # Default watch end (used only for early triggers)
    PH5A_WATCH_DURATION_MINUTES = 45             # v5.7.1: Dynamic watch window duration from gate trigger
    PH5A_WATCH_HARD_CUTOFF = "14:00"             # v5.7.1: Absolute latest watch can run (no entries after this)
    PH5A_POSITION_TIMEOUT = "14:30"              # Force exit open positions
    PH5A_STALL_TIMEOUT_MINUTES = 30              # Exit if price stalls at level

    # ═══════════════════════════════════════════════════════════════════════════════
    # PH5A v2 SNIPER — Stop/Target (FIX 5)
    # ═══════════════════════════════════════════════════════════════════════════════
    PH5A_ATR_STOP_MULTIPLIER = 0.8               # v5.7.0: ATR × 0.8 (was 0.3 — floor kept firing, stop too tight)
    PH5A_MIN_STOP_PCT = 0.3                      # Minimum stop distance (% of price)
    PH5A_MAX_STOP_PCT = 1.5                      # Maximum stop distance (% of price)
    PH5A_MIN_RR_RATIO = 2.0                      # Minimum risk:reward ratio
    PH5A_ATR_PERIOD = 14                         # ATR calculation period

    # ═══════════════════════════════════════════════════════════════════
    # PMBI — Pre-Market Breadth Intelligence (v5.5.0)
    # Scans market breadth at 9:11 AM → sets directional bias for the day
    # Downstream: PH5 gap score bonus, PH5A pipeline priority, Phase 2 filter
    # ═══════════════════════════════════════════════════════════════════
    PMBI_ENABLED = True
    PMBI_SCAN_TIME_HOUR = 9
    PMBI_SCAN_TIME_MINUTE = 11
    PMBI_BULLISH_THRESHOLD = 0.55       # Breadth ratio >= this → BULLISH
    PMBI_BEARISH_THRESHOLD = 0.35       # Breadth ratio <= this → BEARISH
    PMBI_CHATGPT_REVIEW = True          # v5.4.0: Send breadth + sector data to Claude for deep analysis
    PMBI_BIAS_SCORE_BONUS = 5           # PH5A sniper score bonus for aligned trades
    PMBI_PH5_SCORE_BONUS = 10           # PH5 gap composite score bonus for aligned trades

    # ══════════════════════════════════════════════════════════════════════════════
    # PHASE 5A — PVAT (Price-Volume-Acceptance-Trading) BREAKOUT SCANNER
    # ══════════════════════════════════════════════════════════════════════════════
    # Scans for breakouts at key price levels using the PVAT 4-act sequence:
    #   Act 1: Level Exists (PDH/PDL/S&R/IB/POC)
    #   Act 2: Rejection Phase (price tests level, pulls back)
    #   Act 3: Acceptance (price lingers within 0.3% for 3+ candles)
    #   Act 4: Breakout (volume spike confirms, Phase 5 executes MIS)

    PVAT_ENABLED = PH5A_ENABLED                # Legacy alias — startup init uses this
    PVAT_ACCEPTANCE_MIN_CANDLES = 3            # Minimum 15-min candles in acceptance zone
    PVAT_BREAKOUT_BUFFER_PCT = 0.2             # Price must exceed level by this % to confirm
    PVAT_LEVEL_PROXIMITY_PCT = 0.3            # Within 0.3% of level = acceptance zone
    PVAT_APPROACH_PROXIMITY_PCT = 0.5          # Within 0.5% of level = approach zone (was hardcoded 1.0%)
    PVAT_MIN_APPROACH_CANDLES = 1              # Must be in APPROACH for 1+ candle boundaries before ACCEPTANCE
    PVAT_MIN_LEVEL_SCORE = 40                  # v5.4.3: RAISED from 25 — requires rejection evidence to enter APPROACH
    PVAT_TARGET_MULTIPLIER = 2.0              # Target = 2x the ATR from breakout price
    # v5.4.1: Phase 5A is main MIS flow — no time-window (PVAT_SCAN_START/END removed)
    # Scanner runs market hours (09:15-15:25), entry cutoff prevents late trades
    PVAT_MIS_ENTRY_CUTOFF = '15:10'            # 5 min before MIS forced exit at 15:15
    PVAT_MAX_HOLD_MINUTES = 240               # 4 hours max hold (vs gap's 25 min)

    # Phase 5A PVAT ChatGPT Approval Settings
    PVAT_CHATGPT_ENABLED = True               # Master toggle for pre-entry ChatGPT approval
    PVAT_CHATGPT_MIN_CONFIDENCE = 0.60        # Minimum confidence (0-1) to proceed with entry
    PVAT_CHATGPT_TIMEOUT = 8                  # Seconds before auto-approve fallback

    # --- PVAT Breakout Quality (v5.4.2) ---
    PVAT_MIN_BREAKOUT_VOLUME_RATIO = 1.5      # FIX 1: Breakout candle volume must be 1.5x avg
    PVAT_MIN_CANDLE_BODY_PCT = 0.40            # FIX 2: Body must be >=40% of total range (no dojis)
    PVAT_BREAKOUT_ATR_FACTOR = 0.3             # FIX 5: Buffer = 0.3 * ATR (replaces fixed 0.2%)
    PVAT_HALF_SIZE_SCORE = 75                  # Was 70 — no more half-size weak trades
    PVAT_FULL_SIZE_SCORE = 75                  # Was 80 — unified minimum, no tiered sizing below 75
    PVAT_MAX_POSITION_VALUE = 10000            # Max position value in INR
    PVAT_MAX_CAPITAL_PCT = 0.5                 # Max % of available capital per trade
    PVAT_STOP_ATR_MULTIPLIER = 1.2             # v5.7.0: Stop = entry - 1.2*ATR (was 0.5, matched proximity zone)
    PVAT_TCAS_ACTIVATION_PCT = 0.3             # TCAS kicks in after 0.3% profit

    # --- Adaptive Scan Frequency v5.4.4 ---
    PVAT_WARM_ZONE_PCT = 1.0                   # Within 1.0% of breakout → 5-min scan intervals
    PVAT_HOT_ZONE_PCT = 0.3                    # Within 0.3% of breakout → 2-min continuous polling

    # --- Enhanced Level Discovery v5.4.3 (Layer 1) ---
    PVAT_REJECTION_MIN_BOUNCE_PCT = 0.3        # Min bounce % away from level to count as rejection
    PVAT_REJECTION_MIN_VOL_RATIO = 0.8         # Min volume ratio (vs avg) for touch to count
    PVAT_CONFLUENCE_PROXIMITY_PCT = 0.3        # Two levels within 0.3% → merge as one
    PVAT_MAX_PROVEN_LEVELS = 4                 # Max proven levels to track per stock
    PVAT_IB_LEVEL_SCORE_FLOOR = 25             # IB levels (today only) get floor score if they have rejections

    # ═══════════════════════════════════════════════════════════════════
    # CNC LONG SHIELD — Upgraded TCAS (v5.5.0)
    # "Land the Plane in Green Zone — Never Exit in Red"
    # Same Phase 4 loop, smarter responses for CNC LONG held 1+ days
    # ═══════════════════════════════════════════════════════════════════

    # Master Switch
    CNC_SHIELD_ENABLED = True
    CNC_SHIELD_MIN_HOLD_DAYS = 1           # Activates after Day 0 (next day onwards)

    # GREEN-ONLY EXIT (Hard Block — No Exceptions)
    CNC_SHIELD_GREEN_ONLY = True           # NEVER exit CNC LONG in red. Period.

    # SL Management (WIDEN on danger for CNC, not tighten)
    CNC_SHIELD_WIDEN_ATR_RA = 1.0          # Widen stop by 1.0× ATR on RA
    CNC_SHIELD_WIDEN_ATR_ALIM = 1.5        # Widen stop by 1.5× ATR on ALIM
    CNC_SHIELD_MAX_DRAWDOWN_PCT = 15       # Stop floor: entry × (1 - 15%)

    # Smart Averaging — Bounce Confidence
    CNC_BOUNCE_MIN_CONFIDENCE = 65         # Min confidence (0-100) to trigger averaging
    CNC_BOUNCE_FIB_WEIGHT = 20             # Fibonacci zone proximity (0-20)
    CNC_BOUNCE_SR_WEIGHT = 20              # S/R + VWAP level proximity (0-20)
    CNC_BOUNCE_BB_WEIGHT = 15              # Bollinger lower band proximity (0-15)
    CNC_BOUNCE_KALMAN_WEIGHT = 15          # Kalman deceleration signal (0-15)
    CNC_BOUNCE_RSI_WEIGHT = 15             # RSI upturn from oversold (0-15)
    CNC_BOUNCE_VOLUME_WEIGHT = 15          # Volume spike at support (0-15)

    # Smart Averaging — Execution
    CNC_AVG_DROP_TRIGGER_PCT = 3.0         # Min drop % from entry before considering
    CNC_AVG_COOLDOWN_DAYS = 1              # Min days between averaging events
    CNC_AVG_MAX_POSITION_MULTIPLIER = 3    # Max 3× original investment
    CNC_AVG_TARGET_PCT = 3.0               # Target % for new average projection
    CNC_AVG_MAX_DISTANCE_PCT = 10          # Don't average if target still >10% away after

    # ═══════════════════════════════════════════════════════════════════
    # PHASE 8 — WEEKLY MOMENTUM STRATEGY
    # ═══════════════════════════════════════════════════════════════════

    # Master switch
    ENABLE_PH8 = True                          # Kill switch
    PH8_PAPER_MODE = True                      # PAPER — 1-month verification (was LIVE)

    # Universe filters
    PH8_MIN_MCAP_CRORE = 25000                  # Market cap floor (crore)
    PH8_MIN_WEEKLY_RETURN = 0.0                 # 1-week return must be > 0%

    # Selection
    PH8_TOP_N = 1                               # Pick top 1 stock per week

    # Timing — Entry
    PH8_SCAN_DAY = 2                            # Wednesday (0=Mon, 1=Tue, 2=Wed, ...)
    PH8_VWAP_WINDOW_START = dt_time(9, 15)      # VWAP calculation start
    PH8_VWAP_WINDOW_END = dt_time(10, 0)        # VWAP calculation end
    PH8_ENTRY_WINDOW_START = dt_time(10, 0)     # Limit order placed
    PH8_ENTRY_WINDOW_END = dt_time(10, 30)      # Fallback to market order
    PH8_FALLBACK_TO_MARKET = True               # Auto-convert at 10:30

    # Timing — Exit
    PH8_EXIT_CHECK_DAY = 1                      # Tuesday (0=Mon, 1=Tue)
    PH8_EXIT_CHECK_TIMES = [                    # Specific check times on Tuesday
        dt_time(9, 15),
        dt_time(10, 0),
        dt_time(12, 0),
        dt_time(14, 0),
        dt_time(15, 15),
    ]
    PH8_PROFIT_EXIT_THRESHOLD = 0.005           # 0.5% minimum profit to exit on Tuesday

    # Position management
    PH8_MAX_CONCURRENT = 2                      # Max simultaneous momentum holds
    PH8_PRODUCT = "CNC"                         # Always delivery
    PH8_FIXED_AMOUNT = 3000                    # Rupees per trade (adjust to your capital)

    # TCAS — Tier 3 trailing stop
    PH8_TCAS_ACTIVATION_PCT = 0.005             # Activates at 0.5% profit
    PH8_TCAS_TRAIL_PCT = 0.015                  # 1.5% trailing stop below peak
    PH8_TCAS_START_DAY = 0                      # Monday (0=Mon) — TCAS becomes active
    PH8_TCAS_START_TIME = dt_time(10, 0)        # 10:00 AM — earliest TCAS activation on Monday

    # Screener.in data
    PH8_SCREENER_CACHE_FILE = "data/screener_mcap_cache.json"
    PH8_SCREENER_CACHE_TTL_DAYS = 7

    # Phase 6 shadow — momentum mode (ChatGPT gated)
    PH8_SHADOW_ENABLED = True                   # Shadow options follow momentum trades
    PH8_SHADOW_CHATGPT_GATE = True              # ChatGPT must approve shadow
    PH8_SHADOW_MIN_CONFIDENCE = 70              # Score threshold (0-100)
    PH8_SHADOW_EXPIRY_WEEKS = 2                 # 2-week out CE
    PH8_SHADOW_EXIT_ON_CASH = True              # Exit shadow when cash exits
    PH8_SHADOW_INDEPENDENT_TARGET = True        # Shadow can exit on its own target
    PH8_SHADOW_OPTION_TARGET_PCT = 1.0          # 100% gain = shadow exits
    PH8_SHADOW_EXPIRY_BUFFER_DAYS = 2           # Close shadow 2 days before expiry
    PH8_SHADOW_FAILSAFE = "NO_SHADOW"           # If ChatGPT fails: NO_SHADOW

    # Telegram prefix
    PH8_TELEGRAM_PREFIX = "PH8"

    # ═══════════════════════════════════════════════════════════════════
    # PHASE 7 — MCX COMMODITIES (chain control flag)
    # ═══════════════════════════════════════════════════════════════════
    MCX_ENABLED = False                              # MCX evening session paper trading

    # ═══════════════════════════════════════════════════════════════════
    # PHASE 8 — TIER 3 INTELLIGENCE UPGRADE
    # ═══════════════════════════════════════════════════════════════════

    # Morning intelligence review
    PH8_MORNING_REVIEW_ENABLED = True
    PH8_MORNING_REVIEW_TIME = dt_time(9, 0)
    PH8_MORNING_REVIEW_DAYS = [0, 1, 3, 4]        # Mon, Tue, Thu, Fri

    # ChatGPT early exit authority
    PH8_CHATGPT_EARLY_EXIT = True
    PH8_CHATGPT_EXIT_MIN_CONFIDENCE = 80
    PH8_CHATGPT_FAILSAFE = "HOLD"

    # Kalman — daily candle mode
    PH8_KALMAN_ENABLED = True
    PH8_KALMAN_WARMUP_DAYS = 30
    PH8_KALMAN_PROCESS_NOISE = 0.1                 # Higher than tick (daily is noisier)
    PH8_KALMAN_MEASUREMENT_NOISE = 1.0             # Lower than tick (daily close is reliable)

    # Dynamic target from Kalman
    PH8_DYNAMIC_TARGET_ENABLED = True
    PH8_DYNAMIC_TARGET_MIN = 0.005                 # 0.5%
    PH8_DYNAMIC_TARGET_MAX = 0.03                  # 3%

    # FinBERT for Ph8
    PH8_FINBERT_ENABLED = True

    # ═══════════════════════════════════════════════════════════════════
    # PHASE 9 — AI FUND MANAGER (Claude as Strategic Decision Layer)
    # ═══════════════════════════════════════════════════════════════════

    # Master switch
    ENABLE_PH9 = True                              # Kill switch for Fund Manager

    # Claude Configuration — v1.1.0 DUAL-MODEL (cost-optimized)
    # Sonnet is used for rare strategic calls (2/day: morning briefing + EOD review)
    # Haiku is used for frequent tactical gates (entry/exit approvals, ~10-20/day)
    # This delivers ~10x cost reduction vs all-Sonnet.
    PH9_MODEL_SONNET = AI_MODEL_TOP                # Strategic reasoning (morning/EOD) — now the top model
    PH9_MODEL_HAIKU  = "claude-haiku-4-5-20251001" # Tactical gates (entry/exit)
    PH9_MODEL = PH9_MODEL_SONNET                   # Back-compat alias
    PH9_API_KEY_ENV_VAR = "ANTHROPIC_API_KEY"      # Env var for API key
    PH9_CLAUDE_TIMEOUT = 30.0                      # Seconds — fallback to rules on timeout

    # Level 1: Strategic Overseer
    PH9_MORNING_BRIEFING_ENABLED = True            # Pre-market regime decision
    PH9_EOD_REVIEW_ENABLED = True                  # Post-market performance review
    PH9_MORNING_BRIEFING_TIME = dt_time(9, 5)      # Run briefing at 9:05 AM
    PH9_EOD_REVIEW_TIME = dt_time(15, 35)          # Run EOD review at 3:35 PM

    # v1.1.0: Midday sanity check (1 Haiku call/day ~₹0.20)
    PH9_MIDDAY_CHECK_ENABLED = True
    PH9_MIDDAY_CHECK_TIME = dt_time(12, 0)         # Reassess regime at noon

    # v1.4.0: 25-minute heartbeat
    PH9_HEARTBEAT_ENABLED       = True
    PH9_HEARTBEAT_INTERVAL_MIN  = 25               # Minutes between heartbeats

    # v1.5.0: Signal queue mode — gray-zone signals batched at heartbeat instead of
    # individual Claude calls. Saves ~60% of entry gate API cost on busy days.
    # When True, approve_entry() queues signals; heartbeat evaluates them in batch.
    # When False, signals are evaluated immediately (legacy behaviour).
    PH9_QUEUE_MODE_ENABLED = False

    # v1.1.0: Weekly strategic review (1 Sonnet call/week on Friday ~₹2/month)
    PH9_WEEKLY_REVIEW_ENABLED = True

    # v1.1.0: Sector concentration cap — max concurrent positions per sector
    PH9_MAX_POSITIONS_PER_SECTOR = 2

    # v1.2.0: Persistent memory (Option A: rolling history + Option C: lessons DB)
    PH9_MEMORY_ENABLED = True
    PH9_MEMORY_HISTORY_FILE = "ph9_memory.json"     # Rolling last-N-days summary
    PH9_MEMORY_HISTORY_DAYS = 3                      # How many days to retain
    PH9_LESSONS_FILE = "ph9_lessons.txt"             # Learned lessons (pruned weekly)
    PH9_LESSONS_MAX_COUNT = 15                       # Hard cap on number of lessons
    PH9_LESSONS_MAX_TOKENS_APPROX = 500              # Rough char budget (~2000 chars)
    PH9_INJECT_LESSONS_INTO_GATES = True             # Include compact lessons in entry/exit gate prompts

    # Level 2A: Entry Approval Gate
    PH9_ENTRY_GATE_ENABLED = True                  # Claude approves/rejects every entry
    PH9_ENTRY_MIN_CONFIDENCE = 65                  # Min Claude confidence to approve (0-100)

    # Gray-zone gating — skip Claude for obvious trades (~60% call reduction)
    # Score >= upper: auto-approve (no Claude call)
    # Score <  lower: auto-reject (no Claude call)
    # Score in [lower, upper): Claude is consulted (gray zone)
    PH9_ENTRY_GATE_SCORE_LOWER = 50                # Below = auto-reject
    PH9_ENTRY_GATE_SCORE_UPPER = 75                # Above = auto-approve

    # Level 2B: Exit Advisor
    PH9_EXIT_ADVISOR_ENABLED = True                # Claude advises on discretionary exits
    # Note: Hard exits (stop loss, MIS cutoff, ALIM) are NEVER overridden

    # Level 2C: Recovery Advisor (v1.3.0)
    # Claude actively manages underwater positions to bring them back to profit.
    # Called once per morning for each position that meets the trigger threshold.
    # Claude can: HOLD, AVERAGE, SCALE_OUT_PARTIAL, CONVERT_CNC, WIDEN_STOP, EXIT
    # ─────────────────────────────────────────────────────────────────────────────
    PH9_RECOVERY_ENABLED          = True           # Master switch for recovery advisor
    PH9_RECOVERY_TRIGGER_PCT      = -2.0           # Activate when P&L < -2%
    PH9_RECOVERY_EJECT_PCT        = -15.0          # Hard eject: force EXIT below -15% (no Claude)
    PH9_RECOVERY_MAX_DAYS         = 5              # Max calendar days in recovery mode before force-exit
    PH9_RECOVERY_MAX_AVERAGES     = 1              # Max times Claude can authorize averaging per position
    PH9_RECOVERY_AVG_MAX_QTY_PCT  = 100            # Avg qty ≤ N% of original qty (100 = can double max)
    PH9_RECOVERY_AVG_CAPITAL_PCT  = 20             # Avg capital ≤ N% of free available capital
    PH9_RECOVERY_ALLOW_CNC_CONV   = True           # Allow MIS→CNC conversion to hold overnight
    PH9_RECOVERY_CNC_CONV_TIME    = dt_time(14, 30)  # Must convert before 2:30 PM (before cutoff)

    # v1.3.2: Post-ALIM re-entry advisor
    # After TCAS ALIM forces an exit at a loss, Claude assesses whether to re-enter
    # at a better price if the stock shows genuine recovery potential.
    PH9_REENTRY_ENABLED          = True            # Master switch
    PH9_REENTRY_CUTOFF_TIME      = dt_time(13, 30) # No new re-entries after 1:30 PM
    PH9_REENTRY_MAX_PER_SYMBOL   = 1               # Max re-entries per symbol per day
    PH9_REENTRY_MIN_LOSS_INR     = 300             # Only consult Claude if realized loss > ₹300

    # Daily API budget (hard-stop circuit breaker to cap Claude spend)
    PH9_MAX_DAILY_API_COST_INR = 15.0              # ₹ — hard stop at this daily spend
    PH9_DAILY_CALL_COUNT_MAX = 30                  # Hard stop at this many Claude calls/day

    # Token limits (keep responses compact → lower output cost)
    PH9_GATE_MAX_PROMPT_TOKENS = 500               # Ceiling for entry/exit prompt tokens
    PH9_GATE_MAX_RESPONSE_TOKENS = 200             # Ceiling for Haiku gate response
    PH9_STRATEGIC_MAX_PROMPT_TOKENS = 1500         # Ceiling for morning/EOD prompt tokens
    PH9_STRATEGIC_MAX_RESPONSE_TOKENS = 950        # Ceiling for Sonnet strategic response (20+ field JSON needs room)

    # Safety Rails (non-negotiable, override Claude)
    PH9_MAX_DAILY_LOSS = -5000                     # ₹ — circuit breaker, HALT all new entries
    PH9_MAX_POSITION_SIZE = 100000                 # ₹ — max single position value
    PH9_MAX_POSITIONS = 5                          # Max concurrent open positions

    # Telegram
    PH9_TELEGRAM_PREFIX = "PH9"
    PH9_NOTIFY_BLOCKS = True                       # Telegram on entry blocks
    PH9_NOTIFY_BRIEFING = True                     # Telegram on morning/EOD

    # End of Config class



# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def get_week_of_month(date: datetime = None) -> int:
    """Get the week number within the month (1-5)."""
    if date is None:
        date = datetime.now()
    day_of_month = date.day
    week = ((day_of_month - 1) // 7) + 1
    return min(week, 5)


def is_trading_week(date: datetime = None) -> bool:
    """Check if current date is in a trading week."""
    if not Config.ENABLE_WEEK_FILTERING:
        return True
    week = get_week_of_month(date)
    return week in Config.TRADING_WEEKS


def should_run_scanner() -> Tuple[bool, str]:
    """Determine if scanner should run based on week restrictions."""
    current_date = datetime.now()
    week = get_week_of_month(current_date)
    
    if not Config.ENABLE_WEEK_FILTERING:
        return (True, "Week filtering disabled - scanner active")
    
    if week in Config.TRADING_WEEKS:
        return (True, f"Week {week} - Trading week - Scanner active")
    else:
        return (False, f"Week {week} - NOT a trading week")


def log_week_status():
    """Log current week status."""
    current_date = datetime.now()
    week = get_week_of_month(current_date)
    should_run, reason = should_run_scanner()
    
    logger.info("=" * 80)
    logger.info("WEEK STATUS CHECK")
    logger.info("=" * 80)
    logger.info(f"Current date: {current_date.strftime('%Y-%m-%d %A')}")
    logger.info(f"Week of month: Week {week}")
    logger.info(reason)
    logger.info("=" * 80)
    
    return should_run


def is_market_open() -> Tuple[bool, str]:
    """Check if market is currently open."""
    now = datetime.now()
    current_time = now.time()
    
    market_open = datetime.strptime(f"{Config.MARKET_OPEN_HOUR}:{Config.MARKET_OPEN_MINUTE}", "%H:%M").time()
    market_close = datetime.strptime(f"{Config.MARKET_CLOSE_HOUR}:{Config.MARKET_CLOSE_MINUTE}", "%H:%M").time()
    
    if now.weekday() >= 5:
        return (False, "Weekend - Market closed")
    
    if market_open <= current_time <= market_close:
        return (True, "Market is open")
    else:
        return (False, f"Market closed")


def check_market_hours(telegram=None) -> tuple:
    """Market hours gatekeeper."""
    now = datetime.now()
    
    if now.weekday() in [5, 6]:
        logger.error("WEEKEND - MARKET IS CLOSED")
        if telegram:
            telegram.send_message("Weekend - Market closed")
        return False, "Weekend"
    
    market_open = now.replace(hour=9, minute=15, second=0, microsecond=0)
    market_close = now.replace(hour=15, minute=30, second=0, microsecond=0)
    
    if now < market_open:
        logger.info("PRE-MARKET - Waiting...")
        if telegram:
            telegram.send_message(f"Pre-market - Waiting until 09:15")
        
        while datetime.now() < market_open:
            time.sleep(60)
        
        return True, "Market opened"
    
    elif now > market_close:
        logger.error("POST-MARKET - CLOSED")
        if telegram:
            telegram.send_message("Post-market - Closed")
        return False, "Post-market"
    
    else:
        logger.info("MARKET IS OPEN")
        return True, "Market open"
# Note: Before first TCAS tier, full max loss is allowed (profit_lock_pct = 0).
# Exit on floor breach is immediate (no cooldown) by design.


# ═══════════════════════════════════════════════════════════════════════════════
# v4.8.0: STOCK PROFILES - Stock-Specific Behavior Patterns
# ═══════════════════════════════════════════════════════════════════════════════
"""
Stock profiles provide intelligence about each stock's typical behavior.
This helps ChatGPT understand what's "normal" vs "unusual" for each stock.

Used by: Phase 4 ChatGPT for intelligent position management decisions
"""

STOCK_PROFILES = {
    'SYMPHONY': {
        'typical_atr_pct': 2.8,
        'typical_daily_range_pct': 3.2,
        'correlation_nifty': 0.45,
        'beta': 0.85,
        'sector': 'TECHNOLOGY',
        'avg_recovery_time_min': 120,
        'volatility_profile': 'MODERATE',
        'liquidity': 'HIGH',
        'typical_rsi_bounce': 42,
        'notes': 'Strong independent movement, low NIFTY correlation'
    },
    
    'JSWSTEEL': {
        'typical_atr_pct': 2.5,
        'typical_daily_range_pct': 2.8,
        'correlation_nifty': 0.72,
        'beta': 1.15,
        'sector': 'METALS',
        'avg_recovery_time_min': 180,
        'volatility_profile': 'HIGH',
        'liquidity': 'HIGH',
        'typical_rsi_bounce': 38,
        'notes': 'High NIFTY correlation, sector-driven moves'
    },
    
    'RAMCOCEM': {
        'typical_atr_pct': 3.2,
        'typical_daily_range_pct': 3.8,
        'correlation_nifty': 0.55,
        'beta': 1.05,
        'sector': 'CEMENT',
        'avg_recovery_time_min': 150,
        'volatility_profile': 'HIGH',
        'liquidity': 'MEDIUM',
        'typical_rsi_bounce': 42,
        'notes': 'Infrastructure-driven, responds to policy news'
    },
    
    'INFY': {
        'typical_atr_pct': 2.0,
        'typical_daily_range_pct': 2.2,
        'correlation_nifty': 0.68,
        'beta': 0.95,
        'sector': 'IT',
        'avg_recovery_time_min': 90,
        'volatility_profile': 'LOW',
        'liquidity': 'VERY_HIGH',
        'typical_rsi_bounce': 45,
        'notes': 'Large cap, stable, USD-sensitive'
    },
    
    'TECHM': {
        'typical_atr_pct': 2.3,
        'typical_daily_range_pct': 2.6,
        'correlation_nifty': 0.65,
        'beta': 1.0,
        'sector': 'IT',
        'avg_recovery_time_min': 100,
        'volatility_profile': 'MODERATE',
        'liquidity': 'HIGH',
        'typical_rsi_bounce': 43,
        'notes': 'IT sector, USD correlation'
    },
    
    # Add more stocks as needed - these are examples for the 45+ pre-configured stocks
}

# Sector groupings for correlation analysis
SECTOR_GROUPS = {
    'METALS': ['JSWSTEEL', 'HINDALCO', 'TATASTEEL', 'JINDALSTEL', 'SAIL'],
    'IT': ['INFY', 'TCS', 'TECHM', 'WIPRO', 'HCLTECH', 'LTIM'],
    'TECHNOLOGY': ['SYMPHONY', 'TATAELXSI', 'PERSISTENT', 'COFORGE'],
    'CEMENT': ['RAMCOCEM', 'ULTRACEMCO', 'SHREECEM', 'DALMIACM'],
    'AUTO': ['MARUTI', 'TVSMOTOR', 'BAJAJ-AUTO', 'M&M', 'TATAMOTORS'],
    'PHARMA': ['SUNPHARMA', 'DRREDDY', 'DIVISLAB', 'CIPLA', 'AUROPHARMA'],
    'BANKS': ['HDFCBANK', 'ICICIBANK', 'AXISBANK', 'KOTAKBANK', 'SBIN'],
    'FINANCE': ['BAJFINANCE', 'CHOLAFIN', 'MUTHOOTFIN', 'ICICIGI'],
    'FMCG': ['HINDUNILVR', 'ITC', 'NESTLEIND', 'BRITANNIA'],
    'ENERGY': ['RELIANCE', 'ONGC', 'BPCL', 'IOC', 'POWERGRID'],
}

def get_stock_profile(symbol: str) -> Dict:
    """
    Get stock profile with defaults if not found.
    
    Returns:
        Dict with stock-specific behavioral characteristics
    """
    return STOCK_PROFILES.get(symbol, {
        'typical_atr_pct': 2.5,
        'typical_daily_range_pct': 3.0,
        'correlation_nifty': 0.65,
        'beta': 1.0,
        'sector': 'UNKNOWN',
        'avg_recovery_time_min': 150,
        'volatility_profile': 'MODERATE',
        'liquidity': 'MEDIUM',
        'typical_rsi_bounce': 40,
        'notes': 'Default profile - no specific data available'
    })

def get_sector_stocks(sector: str) -> list:
    """Get all stocks in a sector"""
    return SECTOR_GROUPS.get(sector, [])

def get_stock_sector(symbol: str) -> str:
    """Get sector for a symbol"""
    profile = get_stock_profile(symbol)
    return profile.get('sector', 'UNKNOWN')

# ═══════════════════════════════════════════════════════════════════════════════
# BACKTEST CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════════

class BACKTEST_CONFIG:
    """
    Backtest reporting & analytics settings ONLY.

    v4.0.0 (2026-02-15):
    ─────────────────────────────────────────────────────────
    All trading parameters now come from Config class directly.
    This class only controls WHAT to track/report during backtest,
    not HOW the system trades. Same config = same behavior as live.
    ─────────────────────────────────────────────────────────
    """

    # Reporting
    GENERATE_HTML_REPORT = True
    REPORT_OUTPUT_DIR = "data/backtest_reports/"

    # Phase 1 Analytics
    TRACK_FILTER_FUNNEL = True
    LOG_REJECTED_STOCKS = False  # Set True for debugging

    # Phase 2 Analytics
    TRACK_SCORE_COMPONENTS = True
    TRACK_KALMAN_PREDICTIONS = True
    TRACK_ADAPTIVE_RSI = True

    # Phase 3 Analytics
    SIMULATE_SLIPPAGE = True
    SLIPPAGE_PERCENT = 0.05  # 0.05% typical slippage for simulation

    # Phase 4 Analytics
    TRACK_TCAS_ILS_STATES = True
    CALCULATE_HEALTH_SCORES = True

    # Multi-month Settings
    ALLOW_MULTI_MONTH = True
    RESET_CAPITAL_MONTHLY = False  # Use continuous capital

    # Output Settings
    PRINT_MONTHLY_SUMMARY = True
    PRINT_PHASE_ANALYTICS = True
    EXPORT_TRADES_CSV = True
    CSV_OUTPUT_PATH = "data/backtest_reports/trades.csv"

    # ── Phase 5 Paper Trading ──
    PH5_PAPER_MODE = True                              # PAPER — 1-month verification (was LIVE)
    PH5_PAPER_LOG_FILE = "data/ph5_paper_trades.json"  # Paper trade log

    # End of BACKTEST_CONFIG
