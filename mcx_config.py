"""
MCX_CONFIG.PY - Phase 7 MCX Commodity Configuration
=====================================================

All MCX-specific constants, session times, strategy parameters,
and instrument configuration in one place.

Author: Dheebanraj + Claude
Version: 7.0.0
Date: 2026-02-16
"""

from datetime import time as dt_time
from typing import Dict, List


# ═══════════════════════════════════════════════════════════════════════════════
# SESSION TIMES
# ═══════════════════════════════════════════════════════════════════════════════

# Phase 7 lifecycle
MCX_PHASE7_START = dt_time(15, 30)       # Activate after NSE close
MCX_EVENING_SESSION_START = dt_time(17, 0)  # Primary trading window opens
MCX_ENTRY_CUTOFF = dt_time(22, 45)       # No new entries after this
MCX_FORCE_CLOSE = dt_time(23, 0)         # Force close all paper positions
MCX_HARD_STOP = dt_time(23, 10)          # System shutdown
MCX_EXCHANGE_CLOSE = dt_time(23, 30)     # Actual MCX close

# Pre-market data accumulation
MCX_DATA_WARMUP_MINUTES = 30  # Accumulate candles before generating signals
MCX_CANDLE_INTERVAL = 5       # 5-minute candles (matches equity system)

# ═══════════════════════════════════════════════════════════════════════════════
# INSTRUMENT CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════════

# All commodities to paper trade (monitor all, trade only what fits capital)
MCX_PAPER_UNIVERSE = [
    'GOLDPETAL',     # Gold micro — ₹3,782 margin (ONLY tradeable with ₹9,400)
    'GOLDGUINEA',    # Gold guinea — ₹29,763
    'GOLDM',         # Gold mini — ₹377,294
    'CRUDEOILM',     # Crude mini — ₹25,308
    'CRUDEOIL',      # Crude main — ₹253,138
    'SILVERM',       # Silver mini — ₹787,372
    'SILVERMIC',     # Silver micro — ₹158,913
    'NATURALGAS',    # Natural gas — ₹194,255
    'NATGASMINI',    # Natural gas mini — ₹38,601
    'LEADMINI',      # Lead mini — ₹15,361
    'ZINC',          # Zinc — ₹180,159
    'COPPER',        # Copper — ₹497,639
    'NICKEL',        # Nickel — ₹206,049
    'ALUMINIUM',     # Aluminium — ₹179,312
]

# Capital-constrained live trading ladder
MCX_CAPITAL = 9400  # Current capital for MCX

# Capital ladder — unlock as profits grow
MCX_CAPITAL_LADDER = {
    'TIER_1': {  # Start here
        'symbols': ['GOLDPETAL'],
        'min_capital': 4000,
    },
    'TIER_2': {  # Unlock with ₹15K+
        'symbols': ['GOLDPETAL', 'LEADMINI'],
        'min_capital': 15000,
    },
    'TIER_3': {  # Unlock with ₹25K+
        'symbols': ['GOLDPETAL', 'LEADMINI', 'CRUDEOILM'],
        'min_capital': 25000,
    },
}

# Minimum liquidity thresholds for paper trading
MCX_MIN_VOLUME = 50       # Minimum daily volume to consider
MCX_MIN_OI = 200          # Minimum open interest

# ═══════════════════════════════════════════════════════════════════════════════
# STRATEGY S1: OPENING RANGE BREAKOUT (ORB)
# ═══════════════════════════════════════════════════════════════════════════════

ORB_WINDOW_START = dt_time(17, 0)     # Evening session open
ORB_WINDOW_END = dt_time(17, 15)      # 15-minute ORB range
ORB_MIN_RANGE_PCT = 0.3               # Min range width as % of price (skip if too narrow)
ORB_MAX_RANGE_PCT = 2.0               # Max range width as % of price (skip if too wide)
ORB_VOLUME_MULTIPLIER = 1.5           # Breakout candle volume must be > 1.5x avg
ORB_TARGET_MULTIPLIER = 1.5           # Target = 1.5x range width from entry
ORB_TRAIL_AT_1X = True                # Move stop to breakeven after 1x range width profit
ORB_MAX_TRADES_PER_SESSION = 2        # Max ORB trades per commodity per session

# ═══════════════════════════════════════════════════════════════════════════════
# STRATEGY S2: VWAP MEAN REVERSION
# ═══════════════════════════════════════════════════════════════════════════════

VWAP_RESET_TIME = dt_time(17, 0)      # Reset VWAP at evening session start
VWAP_DEVIATION_ENTRY = 1.5            # Enter when price > 1.5σ from VWAP
VWAP_DEVIATION_STOP = 2.0             # Stop at 2σ from VWAP
VWAP_RSI_OVERSOLD = 35                # RSI below this for long mean reversion
VWAP_RSI_OVERBOUGHT = 65              # RSI above this for short mean reversion
VWAP_MIN_CANDLES_FOR_SIGNAL = 12      # Need 12 candles (1 hour) before signals
VWAP_MAX_TRADES_PER_SESSION = 3       # Max VWAP MR trades per commodity

# ═══════════════════════════════════════════════════════════════════════════════
# STRATEGY S3: RSI ZONE TRACKER (Kalman-smoothed, adapted from equity)
# ═══════════════════════════════════════════════════════════════════════════════

RSI_PERIOD = 14                       # Standard RSI period
RSI_DIP_ZONE_LOW = 20                 # Zone entry: K-RSI enters this range
RSI_DIP_ZONE_HIGH = 35                # Zone entry: K-RSI enters this range
RSI_TRIGGER_READINGS = 6              # Need 6 readings in zone with positive velocity
RSI_MIN_VELOCITY = 0.3                # Minimum positive velocity to trigger
RSI_SCORE_THRESHOLD = 65              # Minimum score to generate signal (lower than equity 70)

# Kalman filter parameters (same as equity system)
KALMAN_Q = 0.01                       # Process noise
KALMAN_R = 0.1                        # Measurement noise

# ═══════════════════════════════════════════════════════════════════════════════
# RISK MANAGEMENT
# ═══════════════════════════════════════════════════════════════════════════════

MCX_MAX_PAPER_POSITIONS = 5           # Max simultaneous paper positions
MCX_MAX_LOSS_PER_TRADE_PCT = 2.0      # Max 2% loss per trade (of margin)
MCX_MAX_DAILY_LOSS = 500              # Max daily paper loss before stopping (₹)
MCX_POSITION_TIMEOUT_MINUTES = 180    # Force close after 3 hours if no target/stop

# ═══════════════════════════════════════════════════════════════════════════════
# LOGGING & OUTPUT
# ═══════════════════════════════════════════════════════════════════════════════

MCX_LOG_DIR = 'logs'
MCX_DATA_DIR = 'data/mcx'
MCX_PAPER_TRADES_CSV = 'data/mcx/paper_trades.csv'
MCX_DAILY_SUMMARY_CSV = 'data/mcx/daily_summary.csv'
MCX_CANDLE_CACHE_DIR = 'data/mcx/candles'

# Telegram notification settings
MCX_TELEGRAM_PREFIX = "🏭"             # Commodity emoji prefix for all MCX messages
MCX_NOTIFY_SIGNALS = True              # Send signal notifications
MCX_NOTIFY_PAPER_TRADES = True         # Send paper trade open/close
MCX_NOTIFY_DAILY_SUMMARY = True        # Send EOD summary

# ═══════════════════════════════════════════════════════════════════════════════
# CYCLE TIMING
# ═══════════════════════════════════════════════════════════════════════════════

MCX_SCAN_INTERVAL_SECONDS = 15        # Check signals every 15 seconds
MCX_HEARTBEAT_INTERVAL_MINUTES = 30   # Send heartbeat every 30 minutes

# ═══════════════════════════════════════════════════════════════════════════════
# VERSION
# ═══════════════════════════════════════════════════════════════════════════════

MCX_VERSION = "7.0.0"
MCX_VERSION_DATE = "2026-02-16"
MCX_CODENAME = "Commodity Explorer"
