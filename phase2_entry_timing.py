"""
PHASE 2: AI-ENHANCED ENTRY TIMING MODULE v5.3.5
===============================================================================

v5.3.5 - ADAPTIVE RSI ZONE + VOLUME REMOVAL (2026-02-19):
────────────────────────────
FIX: RSI zone was hardcoded [20-35] — impossible for V-recovery stocks that
     arrive at Phase 2 with RSI 45-70 (already bounced). System starved.
NEW: 2D Calibration Map (automotive-style bilinear interpolation)
     - X-axis: Recovery % (from Phase 1), Y-axis: Kalman RSI velocity
     - Output: adaptive zone_center → zone = [center ± 10]
     - Base zone [40-60] — the healthy momentum zone (not oversold/overbought)
     - Higher recovery + positive velocity = wider acceptance zone
     - Lower recovery + negative velocity = conservative zone
NEW: CalibrationMap2D class — generic reusable bilinear interpolation engine
FIX: Volume Burst (F3, 25 points) REMOVED from scoring — Phase 1 F&O filter
     guarantees institutional liquidity. 5-min volume vs 20-day avg at 2 PM is
     time-of-day noise, not signal. CHOLAFIN scored 0/25 on 15 consecutive cycles.
NEW: 25 volume points redistributed:
     - F1 RSI: 30 → 40 (+10, zone-relative position scoring)
     - F4 ADX: 20 → 25 (+5, directional movement matters more)
     - F5 VWAP: 10 → 20 (+10, primary institutional flow proxy)
     Total max: 110 (100 base + 5 MACD bonus + 5 EMA bonus)
NEW: ZoneTracker logs show adaptive zone per stock per cycle
NEW: Cycle summary shows adaptive zone in "Need" message

v5.3.4 - SCORING REBALANCE (2026-02-17):
────────────────────────────
FIX: ADX ceiling gate removed from HardGates (was blocking trending stocks
     ideal for V-Recovery dip-buying; ADX 30-50 = healthy trend, not a risk)
     ADX floor (< 15) retained — no direction = dips don't bounce
FIX: RAMP Confidence (F2) removed from ScoringEngine — timing mismatch:
     RAMP zone (10-35) expires before HG-6 fires, so every scored stock
     got a fixed 8/20. Dead weight — differentiated nothing.
NEW: 20 RAMP points redistributed to filters that actually vary:
     - F1 RSI Entry: rise_score 0-5 → 0-10 (velocity matters more)
     - F3 Volume Burst: 0-15 → 0-25 (core V-Recovery thesis = institutional flow)
     - F4 ADX Regime: 0-15 → 0-20 (new curve aligned to V-Recovery:
       ADX 20-35 = sweet spot, 35-50 = strong, >50 = parabolic risk)
     Total max: 110 (100 base + 5 MACD bonus + 5 EMA bonus)
NOTE: RAMP detector still runs for ChatGPT context — just removed from scoring

v5.3.3 - LOGGING + CAPITAL FIX (2026-02-16):
────────────────────────────
FIX: can_enter() passed ₹0 price → concentration = 0 → all entries blocked
FIX: MAX_CONCENTRATION_PCT 0.25 → 0.40, ABSOLUTE_MAX_ENTRIES = 1
NEW: RSIZoneTracker per-update diagnostic logging (Raw/Kalman RSI, velocity, state)
NEW: HardGates always logs gate result (removed 'trigger not fired' suppression)
NEW: Phase2 Cycle Summary (stocks | gates passed | signals — single-glance)
NEW: Orchestrator dual-state display (StockMonitor + ZoneTracker side-by-side)

v5.3.2 - SCORING ENGINE REWRITE (2026-02-15):
────────────────────────────
NEW: RSIZoneTracker state machine (replaces ScoreDebouncer)
   - Kalman-smoothed RSI with dip-and-ramp cycle detection
   - 5 states: WATCHING -> ZONE_ENTERED -> TRIGGERED -> CLIMB -> BLOCKED
   - Minimum 6 readings (~30 min) before trigger fires
NEW: HardGates class (6 binary pass/fail checks)
   - ADX floor gate (blocks choppy/directionless ADX < 15)
   - RSI ceiling 85 (exhaustion block)
   - Capital + already-traded + RSI trigger gates
NEW: ScoringEngine (6-filter 105-point system)
   - RSI Entry Quality /30, Volume Burst /25
   - ADX Regime /20, VWAP Position /10, Trend MA20 /15
   - FinBERT Sentiment -5 to +5 (scoring only, NO veto)
NEW: Telegram score notifications at scoring step
NEW: ChatGPT Trading Manager web search (Responses API)
REMOVED: ScoreDebouncer, DebounceState, QualityFilters (dead code)

v4.5.7 - FinBERT threshold + volume normalization CAPITAL FIX (2026-02-03):
────────────────────────────
CRITICAL FIX: can_enter.get('approved') -> can_enter.get('can_enter')

v4.5.5 AUDIT FIX (2026-02-03):
────────────────────────────
FIX: volume_ratio now defaults to 1.0 (was None - caused crashes)
FIX: Added missing technical indicators (ma20, ema21, ema50, atr)

v4.5.0 CHANGES (2026-01-29):
────────────────────────────
NEW: Capital Manager Integration

Author: Claude + Dheebanraj
Date: February 2026
Version: 5.3.5
"""

import os
import sys
import json
import time
import logging
from datetime import datetime, timedelta, time as dt_time
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, field
from pathlib import Path
import tempfile
import gc

# Data processing
import pandas as pd
import numpy as np

# Zerodha API
from kiteconnect import KiteConnect

# OpenAI for ChatGPT
import openai

# Technical indicators - Using TA-Lib (Professional Grade!)
import talib

# Local imports
from kalman_filter import KalmanFilter, create_kalman_filter
from ramp_detector import RampDetector
# v5.5.0 (Pi-lite): FinBERT (torch/transformers) is imported lazily below,
# only when ENABLE_FINBERT is True — keeps this module importable on
# hosts without torch installed (e.g. Raspberry Pi lite branch).
from ai_intelligence import AIIntelligence
from chatgpt_strategic_advisor import ChatGPTStrategicAdvisor
from news_scraper import NewsScraperFree

try:
    from regret_tracker import log_regret_trade
except ImportError:
    def log_regret_trade(*args, **kwargs):
        pass

# ============================================================================
# LOGGING SETUP
# ============================================================================

logger = logging.getLogger('Phase2_EntryTiming')

# ============================================================================
# ATOMIC FILE OPERATIONS (Crash-Safe!)
# ============================================================================

def atomic_write(filepath: str, data: dict):
    """Write JSON file atomically - prevents partial writes!"""
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    temp_file = filepath + '.tmp'
    with open(temp_file, 'w') as f:
        json.dump(data, f, indent=2)
    os.replace(temp_file, filepath)
    logger.debug(f"Atomically wrote: {filepath}")


def safe_read(filepath: str, max_retries: int = 3, retry_delay: float = 0.5) -> Optional[dict]:
    """Read JSON file with retry logic."""
    for attempt in range(max_retries):
        try:
            with open(filepath, 'r') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
            else:
                return None
    return None


# ═══════════════════════════════════════════════════════════════════════════════
# STARVATION POSITION SIZING
# ═══════════════════════════════════════════════════════════════════════════════

def get_starvation_position_multiplier(
    trades_today: int,
    min_daily_trades: int,
    current_time: datetime,
    reduction_start_hour: int = 11,
    reduction_start_minute: int = 30,
    starvation_multiplier: float = 0.5
) -> Tuple[float, bool, str]:
    """Get position size multiplier based on starvation mode."""
    if trades_today >= min_daily_trades:
        return (1.0, False, "Normal position size (min trades met)")
    
    starvation_start = current_time.replace(
        hour=reduction_start_hour, 
        minute=reduction_start_minute, 
        second=0
    )
    
    if current_time < starvation_start:
        return (1.0, False, "Normal position size (before starvation window)")
    
    return (
        starvation_multiplier, 
        True, 
        f"Starvation mode - {starvation_multiplier*100:.0f}% position size"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# v5.3.2: MARKET DATA + RESULT DATACLASSES
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class MarketData:
    """All data needed to evaluate one stock at one moment.
    Built from StockMonitor cached data. No API calls."""
    symbol: str
    timestamp: datetime
    price: float                    # Current LTP
    open: float                     # Day open
    high: float                     # Day high
    low: float                      # Day low
    volume: float                   # Current session volume
    avg_volume_20: float            # 20-period average volume
    rsi: float                      # RSI(14) on 5-min candles
    rsi_history: List[float]        # Last 20+ RSI readings for Kalman/RAMP
    atr: float                      # ATR(14)
    adx: float                      # ADX(14), 0 if unavailable
    vwap: float                     # Session VWAP, 0 if unavailable
    ma20: float                     # 20-period SMA (daily), 0 if unavailable
    macd_hist: float                # MACD histogram
    recovery_percent: float         # V-Recovery % from Phase 1
    ema21: float = 0.0              # 21-period EMA (v5.6: for stacked trend scoring)
    ema50: float = 0.0              # 50-period EMA (v5.6: for stacked trend scoring)
    volume_ratio: float = 1.0      # Time-adjusted volume ratio (from StockMonitor)
    already_traded_today: bool = False
    capital_available: float = 0.0


@dataclass
class Phase2Result:
    """Complete output of Phase 2 evaluation."""
    action: str                         # 'ENTER' / 'SKIP' / 'BLOCKED'
    block_reason: str = ''              # Which gate failed (if BLOCKED)
    score: float = 0.0                  # 0-100+
    grade: str = ''                     # STRONG_BUY / BUY / MODERATE_BUY / SKIP
    position_multiplier: float = 0.0    # 1.0 / 0.75 / 0
    breakdown: Dict = field(default_factory=dict)   # Per-filter scores
    # RSI trigger data
    zone_entered: bool = False
    zone_low_rsi: float = 0.0
    kalman_velocity: float = 0.0
    kalman_rsi: float = 0.0
    # RAMP data
    ramp_confidence: str = ''           # RAMP / WEAK / NONE
    ramp_rising_lows: int = 0
    # ChatGPT package
    chatgpt_package: str = ''


# ═══════════════════════════════════════════════════════════════════════════════
# v5.3.5: 2D CALIBRATION MAP (Automotive-style bilinear interpolation)
# ═══════════════════════════════════════════════════════════════════════════════

class CalibrationMap2D:
    """2D bilinear interpolation map — like ECU calibration tables.

    X-axis: Recovery % (from Phase 1 V-Recovery detection)
    Y-axis: Kalman RSI Velocity (rate of change from Kalman filter)
    Output: zone_center value (zone = center ± half_width)

    Usage:
        cal_map = CalibrationMap2D(x_axis, y_axis, grid)
        center = cal_map.lookup(recovery_pct, kalman_velocity)
    """

    def __init__(self, x_breakpoints: List[float], y_breakpoints: List[float],
                 grid: List[List[float]]):
        """
        Args:
            x_breakpoints: Recovery % axis values (ascending), e.g. [60, 80, 100, ...]
            y_breakpoints: Velocity axis values (ascending), e.g. [-3, 0, 2, 5, 8]
            grid: 2D list [y][x] of output values. grid[row=velocity][col=recovery]
        """
        self.x_bp = x_breakpoints
        self.y_bp = y_breakpoints
        self.grid = grid

        # Validate dimensions
        assert len(grid) == len(y_breakpoints), \
            f"Grid rows ({len(grid)}) must match y_breakpoints ({len(y_breakpoints)})"
        for row_idx, row in enumerate(grid):
            assert len(row) == len(x_breakpoints), \
                f"Grid row {row_idx} cols ({len(row)}) must match x_breakpoints ({len(x_breakpoints)})"

    def lookup(self, x: float, y: float) -> float:
        """Bilinear interpolation lookup.

        Clamps inputs to grid boundaries (no extrapolation beyond edges).
        Returns smoothly interpolated zone_center value.
        """
        # Clamp to grid boundaries
        x = max(self.x_bp[0], min(x, self.x_bp[-1]))
        y = max(self.y_bp[0], min(y, self.y_bp[-1]))

        # Find bounding indices on X axis
        xi = 0
        for i in range(len(self.x_bp) - 1):
            if x >= self.x_bp[i]:
                xi = i
        xi2 = min(xi + 1, len(self.x_bp) - 1)

        # Find bounding indices on Y axis
        yi = 0
        for i in range(len(self.y_bp) - 1):
            if y >= self.y_bp[i]:
                yi = i
        yi2 = min(yi + 1, len(self.y_bp) - 1)

        # Calculate interpolation fractions
        if self.x_bp[xi2] != self.x_bp[xi]:
            xf = (x - self.x_bp[xi]) / (self.x_bp[xi2] - self.x_bp[xi])
        else:
            xf = 0.0

        if self.y_bp[yi2] != self.y_bp[yi]:
            yf = (y - self.y_bp[yi]) / (self.y_bp[yi2] - self.y_bp[yi])
        else:
            yf = 0.0

        # Bilinear interpolation: 4-corner weighted average
        v00 = self.grid[yi][xi]      # bottom-left
        v10 = self.grid[yi][xi2]     # bottom-right
        v01 = self.grid[yi2][xi]     # top-left
        v11 = self.grid[yi2][xi2]    # top-right

        result = (v00 * (1 - xf) * (1 - yf) +
                  v10 * xf * (1 - yf) +
                  v01 * (1 - xf) * yf +
                  v11 * xf * yf)

        return round(result, 1)


# ═══════════════════════════════════════════════════════════════════════════════
# v5.3.5: RSI ZONE TRACKER (Adaptive 2D Map — replaces fixed [20-35] zone)
# ═══════════════════════════════════════════════════════════════════════════════

class RSIZoneTracker:
    """Per-symbol state machine tracking RSI within adaptive zone.

    v5.3.5: Zone boundaries come from 2D calibration map (recovery% × velocity)
    instead of fixed [20-35]. Base zone is [40-60] — the healthy momentum zone.

    States: WATCHING → ZONE_ENTERED → TRIGGERED (or CLIMB)
        WATCHING:      RSI outside adaptive zone
        ZONE_ENTERED:  RSI entered adaptive zone (healthy momentum confirmed)
        TRIGGERED:     RSI in zone with positive Kalman velocity + min readings
        CLIMB:         RSI passed zone ceiling (late entry, still valid)
        BLOCKED:       RSI < 10 (capitulation) or RSI >= 85 (exhausted)
    """

    def __init__(self, symbol: str, config, recovery_percent: float = 0.0):
        self.symbol = symbol
        self.config = config
        self.recovery_percent = recovery_percent
        self.state = 'WATCHING'
        self.zone_entered = False
        self.zone_entered_time = None
        self.zone_low_rsi = 999.0
        self.kalman_rsi = 0.0
        self.kalman_velocity = 0.0
        self.triggered = False
        self.trigger_time = None
        self.trigger_rsi = 0.0
        self.readings_since_zone = 0
        self.kalman_filter = None       # Initialized on first update

        # v5.3.5: Adaptive zone from 2D calibration map
        self.adaptive_zone_low = 40.0   # Will be updated each cycle
        self.adaptive_zone_high = 60.0  # Will be updated each cycle
        self.adaptive_center = 50.0     # Will be updated each cycle

        # Build 2D calibration map from config
        x_bp = getattr(config, 'ADAPTIVE_RSI_MAP_X_RECOVERY', [60, 80, 100, 120, 150, 200, 250])
        y_bp = getattr(config, 'ADAPTIVE_RSI_MAP_Y_VELOCITY', [-3, 0, 2, 5, 8])
        grid = getattr(config, 'ADAPTIVE_RSI_MAP_GRID', [
            # Recovery:  60    80   100   120   150   200   250     ← Velocity:
            [47,  48,  49,  49,  50,  50,  50],    # -3 (RSI falling)
            [48,  49,  50,  51,  52,  53,  53],    #  0 (RSI flat)
            [49,  50,  52,  53,  55,  56,  57],    # +2 (RSI rising)
            [50,  52,  54,  56,  58,  60,  61],    # +5 (RSI surging)
            [52,  54,  56,  58,  61,  63,  65],    # +8 (strong momentum)
        ])
        self.cal_map = CalibrationMap2D(x_bp, y_bp, grid)
        self.zone_half_width = getattr(config, 'ADAPTIVE_RSI_ZONE_HALF_WIDTH', 10.0)
        self.eviction_reason = None       # v5.4.2: Why stock was evicted
        self.eviction_time = None         # v5.4.2: When stock was evicted
        self.consecutive_neg_vel = 0      # v5.4.2: Track sustained negative velocity

    def update(self, rsi: float, rsi_history: List[float], config,
               recovery_percent: float = None):
        """Feed new RSI reading. Updates Kalman filter, 2D map zone, and state machine."""

        prev_state = self.state

        # Update recovery_percent if provided (may change intraday as recovery evolves)
        if recovery_percent is not None:
            self.recovery_percent = recovery_percent

        # 1. Initialize Kalman on first call with enough history
        if self.kalman_filter is None and len(rsi_history) >= 2:
            self.kalman_filter = KalmanFilter(
                process_noise=0.5,
                measurement_noise=4.0
            )
            # Process historical readings to warm up filter
            for hist_rsi in rsi_history[:-1]:
                self.kalman_filter.process_measurement(hist_rsi)

        # 2. Run Kalman filter on latest RSI
        if self.kalman_filter is not None:
            state = self.kalman_filter.process_measurement(rsi)
            self.kalman_rsi = state.price       # Smoothed RSI
            self.kalman_velocity = state.velocity  # Rate of change
        else:
            self.kalman_rsi = rsi
            self.kalman_velocity = 0.0

        smoothed_rsi = self.kalman_rsi

        # v5.4.2: Track consecutive negative velocity readings
        if self.kalman_velocity < 0:
            self.consecutive_neg_vel += 1
        else:
            self.consecutive_neg_vel = 0

        # 3. BLOCK checks (unchanged — hard safety limits)
        if smoothed_rsi < getattr(config, 'PH2_RSI_CAPITULATION', 10.0):
            self.state = 'BLOCKED'
            if prev_state != 'BLOCKED':
                logger.warning(f"ZoneTracker: {self.symbol} | {prev_state} → BLOCKED | "
                             f"K-RSI {smoothed_rsi:.1f} < capitulation | Raw RSI {rsi:.1f}")
            return
        if smoothed_rsi >= getattr(config, 'PH2_RSI_CEILING', 85.0):
            self.state = 'BLOCKED'
            if prev_state != 'BLOCKED':
                logger.warning(f"ZoneTracker: {self.symbol} | {prev_state} → BLOCKED | "
                             f"K-RSI {smoothed_rsi:.1f} >= ceiling | Raw RSI {rsi:.1f}")
            return

        # 4. v5.3.5: ADAPTIVE ZONE from 2D calibration map
        #    Inputs: recovery% (from Phase 1) × Kalman velocity (live)
        #    Output: zone_center → zone = [center - half_width, center + half_width]
        self.adaptive_center = self.cal_map.lookup(
            self.recovery_percent or 100.0,   # Default 100% if unknown
            self.kalman_velocity
        )
        self.adaptive_zone_low = self.adaptive_center - self.zone_half_width
        self.adaptive_zone_high = self.adaptive_center + self.zone_half_width

        zone_low = self.adaptive_zone_low
        zone_high = self.adaptive_zone_high

        # 5. Zone tracking: RSI in adaptive zone
        if zone_low <= smoothed_rsi <= zone_high:
            if not self.zone_entered:
                # v5.4.2: Cooldown after eviction — prevent immediate re-entry
                cooldown_minutes = getattr(config, 'PH2_EVICTION_COOLDOWN_MINUTES', 15)
                if self.eviction_time:
                    elapsed_since_eviction = (datetime.now() - self.eviction_time).total_seconds() / 60
                    if elapsed_since_eviction < cooldown_minutes:
                        logger.info(f"ZoneTracker: {self.symbol} | ⏳ COOLDOWN — {elapsed_since_eviction:.0f}/{cooldown_minutes} min "
                                   f"since eviction ({self.eviction_reason})")
                        return  # Skip this update entirely
                    else:
                        # Cooldown expired, clear eviction state
                        self.eviction_reason = None
                        self.eviction_time = None

                self.zone_entered = True
                self.zone_entered_time = datetime.now()
                logger.info(f"ZoneTracker: {self.symbol} | {prev_state} → ZONE_ENTERED | "
                           f"K-RSI {smoothed_rsi:.1f} entered [{zone_low:.0f}-{zone_high:.0f}] "
                           f"(center={self.adaptive_center:.0f}, rec={self.recovery_percent:.0f}%) | Raw RSI {rsi:.1f}")
            self.zone_low_rsi = min(self.zone_low_rsi, smoothed_rsi)
            self.state = 'ZONE_ENTERED'
            self.readings_since_zone = min(self.readings_since_zone + 1, 99)  # cap prevents overflow

            # v5.4.3: Zone timeout check inside zone — evict if RSI lingers in zone
            # without triggering (Rule 3 in else-block only fires when RSI exits zone,
            # so stocks that stay in zone 120+ min would never be evicted — fixed here).
            if self.zone_entered and self.zone_entered_time:
                elapsed_min = (datetime.now() - self.zone_entered_time).total_seconds() / 60
                max_zone_minutes = getattr(config, 'PH2_MAX_ZONE_MINUTES', 30)
                if elapsed_min > max_zone_minutes:
                    logger.info(f"ZoneTracker: {self.symbol} | ❌ EVICTED (in-zone timeout) — "
                               f"in zone {elapsed_min:.0f} min without trigger (max {max_zone_minutes} min) | "
                               f"K-RSI {smoothed_rsi:.1f} | Vel {self.kalman_velocity:+.2f}")
                    self._evict("ZONE_TIMEOUT")
                    return

        else:
            # v5.4.2: Smart eviction — RSI dropped out of zone
            if self.zone_entered:
                below_zone_by = zone_low - smoothed_rsi  # Positive = below zone
                above_zone_by = smoothed_rsi - zone_high  # Positive = above zone

                # Rule 1: RSI dropped MORE than 5 pts below zone low → evict
                # Stock is falling away from entry zone, not recovering
                zone_drop_threshold = getattr(config, 'PH2_ZONE_DROP_THRESHOLD', 5)
                if below_zone_by > zone_drop_threshold:
                    logger.info(f"ZoneTracker: {self.symbol} | ❌ EVICTED — K-RSI {smoothed_rsi:.1f} "
                               f"dropped {below_zone_by:.1f} pts below zone low {zone_low:.0f}")
                    self._evict("RSI_BELOW_ZONE")

                # Rule 2: RSI above zone + negative velocity → momentum exhausted
                elif above_zone_by > zone_drop_threshold and self.kalman_velocity < -2.0:
                    logger.info(f"ZoneTracker: {self.symbol} | ❌ EVICTED — K-RSI {smoothed_rsi:.1f} "
                               f"above zone but falling (vel {self.kalman_velocity:+.2f})")
                    self._evict("RSI_ABOVE_FALLING")

                # Rule 3: In zone too long without trigger (30 min = ~6 readings on 5-min candles)
                elif self.zone_entered_time:
                    elapsed_min = (datetime.now() - self.zone_entered_time).total_seconds() / 60
                    max_zone_minutes = getattr(config, 'PH2_MAX_ZONE_MINUTES', 30)
                    if elapsed_min > max_zone_minutes:
                        logger.info(f"ZoneTracker: {self.symbol} | ❌ EVICTED — in zone {elapsed_min:.0f} min "
                                   f"without trigger (max {max_zone_minutes} min)")
                        self._evict("ZONE_TIMEOUT")

                # Rule 4: Sustained negative velocity while in zone → momentum dead
                elif self.consecutive_neg_vel >= getattr(config, 'PH2_MAX_CONSECUTIVE_NEG_VEL', 4):
                    logger.info(f"ZoneTracker: {self.symbol} | ❌ EVICTED — {self.consecutive_neg_vel} consecutive "
                               f"negative velocity readings (vel {self.kalman_velocity:+.2f})")
                    self._evict("SUSTAINED_NEG_VELOCITY")

        # 6. Trigger detection (only if zone was entered)
        if self.zone_entered:
            # v5.3.5: Trigger zone = upper half of adaptive zone + 5 above
            #   If zone is [40-60], trigger zone is [50-65]
            trigger_low = self.adaptive_center
            trigger_high = self.adaptive_zone_high + 5.0
            min_readings = getattr(config, 'PH2_MIN_READINGS_BEFORE_TRIGGER', 6)

            if trigger_low <= smoothed_rsi <= trigger_high:
                if self.kalman_velocity > 0:
                    if self.readings_since_zone >= min_readings:
                        self.state = 'TRIGGERED'
                        self.triggered = True
                        self.trigger_time = datetime.now()
                        self.trigger_rsi = smoothed_rsi
                        logger.info(f"ZoneTracker: {self.symbol} | ✅ TRIGGERED! | "
                                   f"K-RSI {smoothed_rsi:.1f} | Vel {self.kalman_velocity:+.2f} | "
                                   f"Zone [{zone_low:.0f}-{zone_high:.0f}] | "
                                   f"Readings {self.readings_since_zone}/{min_readings}")
                    else:
                        logger.info(f"ZoneTracker: {self.symbol} | TRIGGER ZONE but readings {self.readings_since_zone}/{min_readings} | "
                                   f"K-RSI {smoothed_rsi:.1f} | Vel {self.kalman_velocity:+.2f}")
                else:
                    logger.info(f"ZoneTracker: {self.symbol} | TRIGGER ZONE but Vel {self.kalman_velocity:+.2f} <= 0 | "
                               f"K-RSI {smoothed_rsi:.1f} | Readings {self.readings_since_zone}/{min_readings}")
            elif smoothed_rsi > trigger_high:
                # Late entry — RSI climbed past trigger zone
                self.state = 'CLIMB'
                self.triggered = True   # Late but valid
                self.trigger_rsi = smoothed_rsi
                if prev_state != 'CLIMB':
                    logger.info(f"ZoneTracker: {self.symbol} | {prev_state} → CLIMB (late entry) | "
                               f"K-RSI {smoothed_rsi:.1f} > {trigger_high:.0f} | Raw RSI {rsi:.1f}")

        # v5.3.5: Compact per-update diagnostic with adaptive zone info
        zone_low_str = f"{self.zone_low_rsi:.1f}" if self.zone_low_rsi < 999 else "—"
        min_readings = getattr(config, 'PH2_MIN_READINGS_BEFORE_TRIGGER', 6)
        logger.info(f"ZoneTracker: {self.symbol} | {self.state:13} | "
                   f"Raw {rsi:.1f} | K-RSI {smoothed_rsi:.1f} | Vel {self.kalman_velocity:+.2f} | "
                   f"Zone [{zone_low:.0f}-{zone_high:.0f}] (ctr={self.adaptive_center:.0f}) | "
                   f"Rec {self.recovery_percent:.0f}% | Readings {self.readings_since_zone}/{min_readings}")

    def reset_daily(self):
        """Reset at market open (9:15 AM). Called by Phase2EntryMonitor."""
        self.state = 'WATCHING'
        self.zone_entered = False
        self.zone_entered_time = None
        self.zone_low_rsi = 999.0
        self.kalman_rsi = 0.0
        self.kalman_velocity = 0.0
        self.triggered = False
        self.trigger_time = None
        self.trigger_rsi = 0.0
        self.readings_since_zone = 0
        self.kalman_filter = None
        # v5.3.5: Reset adaptive zone to defaults (will recalculate on first update)
        self.adaptive_zone_low = 40.0
        self.adaptive_zone_high = 60.0
        self.adaptive_center = 50.0
        # v5.4.2: Clear eviction state
        self.eviction_reason = None
        self.eviction_time = None
        self.consecutive_neg_vel = 0
        # NOTE: recovery_percent is NOT reset — it comes from Phase 1 and stays valid

    def _evict(self, reason: str):
        """
        v5.4.2: Reset zone tracking state when stock should no longer be monitored.
        Similar to reset_daily but preserves Kalman state for potential re-entry.
        """
        self.state = 'WATCHING'
        self.zone_entered = False
        self.zone_entered_time = None
        self.zone_low_rsi = 999.0
        self.triggered = False
        self.trigger_time = None
        self.trigger_rsi = 0.0
        self.readings_since_zone = 0
        self.eviction_reason = reason
        self.eviction_time = datetime.now()
        # NOTE: Kalman filter state (kalman_rsi, kalman_velocity) preserved
        # so if RSI recovers back into zone, tracker can re-enter cleanly


# ═══════════════════════════════════════════════════════════════════════════════
# v5.3.2: HARD GATES (binary pass/fail)
# ═══════════════════════════════════════════════════════════════════════════════

class HardGates:
    """Binary pass/fail checks. Any fail = skip stock, no scoring."""

    @staticmethod
    def check_all(data: MarketData, tracker: RSIZoneTracker, config) -> Tuple[bool, str]:
        """
        Check all hard gates in order (cheapest first).
        Returns (all_passed, failed_gate_reason).
        If all_passed=True, failed_gate_reason is empty string.
        """

        # HG-1: Already traded today
        if data.already_traded_today:
            return (False, "Already traded today")

        # HG-2: Price range
        price_min = getattr(config, 'PRICE_MIN', 900)
        price_max = getattr(config, 'PRICE_MAX', 1800)
        if not (price_min <= data.price <= price_max):
            return (False, f"Price {data.price:.0f} outside range {price_min}-{price_max}")

        # HG-3: RSI ceiling (exhausted)
        rsi_ceiling = getattr(config, 'PH2_RSI_CEILING', 85.0)
        if data.rsi is not None and data.rsi >= rsi_ceiling:
            return (False, f"RSI {data.rsi:.1f} >= {rsi_ceiling} (exhausted)")

        # HG-4: ADX floor (no direction = dips don't bounce), None passes
        # v5.3.4: ADX ceiling REMOVED — trending stocks (ADX 30-50) are ideal
        #         for V-Recovery dip-buying. Scoring (F4) handles graduated penalty.
        adx_floor = getattr(config, 'PH2_ADX_FLOOR', 15.0)
        if data.adx is not None and data.adx > 0:
            if data.adx < adx_floor:
                return (False, f"ADX {data.adx:.1f} < {adx_floor} (choppy/no direction)")

        # HG-5: Capital (at least 1 share)
        min_position = data.price * 1
        if data.capital_available < min_position:
            return (False, f"Capital {data.capital_available:.0f} insufficient")

        # HG-6: RSI trigger fired
        if not tracker.triggered:
            return (False, f"RSI trigger not fired (state={tracker.state})")

        # ALL PASSED
        return (True, "")


# ═══════════════════════════════════════════════════════════════════════════════
# v5.3.2: SCORING ENGINE (replaces QualityFilters)
# ═══════════════════════════════════════════════════════════════════════════════

class ScoringEngine:
    """6-filter scoring system. Called only after all hard gates pass.

    v5.3.5: Volume (F3) REMOVED — Phase 1 F&O filter guarantees liquidity.
    Afternoon 5-min volume vs 20-day avg is time-of-day noise, not signal.
    25 points redistributed: F1 +10 (RSI 30→40), F4 +5 (ADX 20→25), F5 +10 (VWAP 10→20).
    v5.6: Added MACD momentum bonus (0-5) and EMA21>EMA50 stacked trend bonus (0-5).
    Total max: 110 (100 base + 5 MACD bonus + 5 EMA bonus).
    """

    @staticmethod
    def score_all(data: MarketData, tracker: RSIZoneTracker,
                  finbert_result: Optional[dict],
                  config) -> Dict:
        """
        v5.4: Score all 5 filters. Max total = 100.
        F1 RSI(20) + F2 Recovery(25) + F3 Volume(20) + F4 Trend(20) + F5 Timing(15).
        Returns dict with total, grade, position_multiplier, breakdown.
        """
        breakdown = {}

        # ─── F1: RSI Quality (0-20) ───  [v5.4: halved from 0-40]
        # RSI alone can't carry a trade — one of five pillars now
        # A) Recovery depth (0-6): How deep RSI went before zone
        if tracker.zone_low_rsi < 999:
            lowest = tracker.zone_low_rsi
        else:
            lowest = max(20, 60 - (tracker.recovery_percent or 100) * 0.2)

        if lowest <= 25:
            dip_score = 6    # Deep V
        elif lowest <= 30:
            dip_score = 5
        elif lowest <= 35:
            dip_score = 4
        elif lowest <= 40:
            dip_score = 3
        elif lowest <= 45:
            dip_score = 2
        else:
            dip_score = 0

        # B) Position relative to adaptive zone center (0-8)
        zone_center = tracker.adaptive_center
        zone_hw = tracker.zone_half_width
        if zone_hw > 0:
            distance_from_center = abs(tracker.kalman_rsi - zone_center)
            if distance_from_center <= zone_hw * 0.3:
                pos_score = 8    # Sweet spot
            elif distance_from_center <= zone_hw * 0.6:
                pos_score = 6
            elif distance_from_center <= zone_hw:
                pos_score = 4
            elif distance_from_center <= zone_hw * 1.5:
                pos_score = 2
            else:
                pos_score = 0
        else:
            pos_score = 4   # Fallback

        # C) Rise strength (0-6) — Kalman velocity
        if tracker.kalman_velocity > 0.5:
            rise_score = 6
        elif tracker.kalman_velocity > 0.3:
            rise_score = 5
        elif tracker.kalman_velocity > 0.2:
            rise_score = 3
        elif tracker.kalman_velocity > 0:
            rise_score = 2
        else:
            rise_score = 0

        f1_total = dip_score + pos_score + rise_score
        breakdown['rsi_quality'] = {
            'score': f1_total, 'max': 20,
            'detail': f"dip={dip_score} pos={pos_score} rise={rise_score} "
                      f"(low={tracker.zone_low_rsi:.1f} now={tracker.kalman_rsi:.1f} "
                      f"vel={tracker.kalman_velocity:+.2f} zone=[{tracker.adaptive_zone_low:.0f}-{tracker.adaptive_zone_high:.0f}])"
        }

        # ─── F2: Recovery Quality (0-25) ───  [v5.4: NEW — highest weight, core thesis]
        # Scores today's live recovery % against Fibonacci levels
        # Uses open as anchor (not high) — V-Recovery is drop-from-open, recover-toward-open
        today_drop = data.open - data.low
        if today_drop > 0 and data.low < data.open:
            today_recovery_pct = ((data.price - data.low) / (data.open - data.low)) * 100
        else:
            today_recovery_pct = 0  # No drop today = no V-Recovery pattern

        # v5.4.1 FIX: Recovery >100% = price overshot open = STRONGEST V-recovery
        # Save raw value for logging, then map to golden ratio zone for scoring
        today_recovery_pct_raw = today_recovery_pct
        if today_recovery_pct > 100:
            today_recovery_pct = 65.0  # Maps to 58-68% bracket → 25 pts (golden ratio)

        if 58 <= today_recovery_pct <= 68:
            f2_score = 25    # 61.8% golden ratio zone
        elif 48 <= today_recovery_pct < 58:
            f2_score = 20    # 50% midpoint
        elif 68 < today_recovery_pct <= 80:
            f2_score = 18    # Above golden, still good
        elif 36 <= today_recovery_pct < 48:
            f2_score = 12    # 38.2% shallow retracement
        elif 80 < today_recovery_pct <= 100:
            f2_score = 8     # Deep recovery, possible overextension
        elif 25 <= today_recovery_pct < 36:
            f2_score = 5     # Very early recovery
        else:
            f2_score = 0     # <25% or >100% or no drop

        breakdown['recovery_quality'] = {
            'score': f2_score, 'max': 25,
            'detail': f"recovery={today_recovery_pct_raw:.1f}% (open={data.open:.1f} low={data.low:.1f} price={data.price:.1f})"
        }

        # ─── F3: Volume Ratio (0-20) ───  [v5.4: REINSTATED — institutional confirmation]
        # Time-adjusted volume ratio already computed on StockMonitor
        vr = data.volume_ratio
        if vr >= 2.0:
            f3_score = 20    # 2x expected = strong institutional footprint
        elif vr >= 1.5:
            f3_score = 15    # Above average institutional activity
        elif vr >= 1.0:
            f3_score = 8     # Normal volume — no red flag, no confirmation
        elif vr >= 0.7:
            f3_score = 3     # Below average — weak conviction
        else:
            f3_score = 0     # Dead volume — no institutional interest

        breakdown['volume_ratio'] = {
            'score': f3_score, 'max': 20,
            'detail': f"vol_ratio={vr:.2f}x"
        }

        # ─── F4: Trend Context (0-20) ───  [v5.4: MERGED ADX+VWAP+MA20]
        # Single composite: "is the backdrop supportive for a bounce?"

        # Sub-A: ADX regime (0-8)
        if data.adx is None or data.adx == 0:
            adx_sub = 4                    # Unknown, neutral
        elif 20 <= data.adx <= 35:
            adx_sub = 8                    # Sweet spot for V-Recovery
        elif 15 <= data.adx < 20:
            adx_sub = 5                    # Mild trend
        elif 35 < data.adx <= 50:
            adx_sub = 6                    # Strong trend, still ok
        else:
            adx_sub = 2                    # Too low (<15) or parabolic (>50)

        # Sub-B: VWAP position (0-7) — only active after 10 AM
        vwap_after_hour = getattr(config, 'PH2_VWAP_ACTIVE_AFTER_HOUR', 10)
        if data.timestamp.hour < vwap_after_hour:
            vwap_sub = 4                   # Neutral before 10 AM
        elif data.vwap is None or data.vwap == 0:
            vwap_sub = 4                   # Unavailable, neutral
        else:
            vwap_pct = (data.price - data.vwap) / data.vwap * 100
            if vwap_pct > 0.3:
                vwap_sub = 7               # Above VWAP = institutional bullish
            elif vwap_pct > -0.2:
                vwap_sub = 4               # Near VWAP = neutral
            else:
                vwap_sub = 0               # Below VWAP = institutional bearish

        # Sub-C: MA20 position (0-5)
        if data.ma20 is None or data.ma20 == 0:
            ma20_sub = 3                   # Unknown, neutral
        else:
            ma20_pct = (data.price - data.ma20) / data.ma20 * 100
            if ma20_pct > 1.0:
                ma20_sub = 5               # Clearly above daily support
            elif ma20_pct > 0:
                ma20_sub = 4               # Just above
            elif ma20_pct > -2.0:
                ma20_sub = 2               # Slightly below, still ok
            else:
                ma20_sub = 0               # Falling knife

        f4_score = adx_sub + vwap_sub + ma20_sub  # Max = 8 + 7 + 5 = 20
        breakdown['trend_context'] = {
            'score': f4_score, 'max': 20,
            'detail': f"adx={adx_sub}({data.adx:.1f}) vwap={vwap_sub} ma20={ma20_sub}"
        }

        # ─── F5: Session Timing (0-15) ───  [v5.4: NEW — institutional activity windows]
        hour = data.timestamp.hour
        minute = data.timestamp.minute
        t = hour * 60 + minute  # Minutes since midnight

        if 585 <= t < 630:       # 09:45 - 10:30 (peak morning)
            f5_score = 15
            f5_detail = "Peak morning window"
        elif 870 <= t < 910:     # 14:30 - 15:10 (closing rebalance)
            f5_score = 13
            f5_detail = "Closing rebalance window"
        elif 780 <= t < 870:     # 13:00 - 14:30 (European overlap + pre-close buildup)
            f5_score = 10
            f5_detail = "European overlap window"
        elif 630 <= t < 690:     # 10:30 - 11:30 (morning continuation)
            f5_score = 6
            f5_detail = "Morning continuation"
        elif 555 <= t < 585:     # 09:15 - 09:45 (opening volatility)
            f5_score = 4
            f5_detail = "Opening volatility"
        elif 910 <= t < 930:     # 15:10 - 15:30 (closing auction, risky)
            f5_score = 3
            f5_detail = "Closing auction (risky)"
        elif 690 <= t < 780:     # 11:30 - 13:00 (LUNCH DEAD ZONE)
            f5_score = 0
            f5_detail = "Lunch dead zone"
        else:
            f5_score = 0
            f5_detail = "Outside market hours"

        breakdown['session_timing'] = {
            'score': f5_score, 'max': 15,
            'detail': f"{f5_detail} ({hour:02d}:{minute:02d})"
        }

        # ─── BONUS B1: MACD Momentum Confirmation (0-5) ───
        # v5.6: MACD histogram > 0 = upward momentum confirming V-Recovery bounce
        b1_macd_score = 0
        b1_macd_detail = "N/A"
        if data.macd_hist != 0:
            if data.macd_hist > 0:
                b1_macd_score = 5
                b1_macd_detail = f"Positive momentum ({data.macd_hist:.3f})"
            elif data.macd_hist > -0.5:
                b1_macd_score = 2
                b1_macd_detail = f"Near zero, turning ({data.macd_hist:.3f})"
            else:
                b1_macd_score = 0
                b1_macd_detail = f"Bearish momentum ({data.macd_hist:.3f})"

        breakdown['macd_bonus'] = {
            'score': b1_macd_score, 'max': 5,
            'detail': b1_macd_detail
        }

        # ─── BONUS B2: EMA21 > EMA50 Stacked Trend (0-5) ───
        # v5.6: Book's F3 — price > EMA21 > EMA50 = strongest bullish alignment
        b2_ema_score = 0
        b2_ema_detail = "EMAs unavailable"
        if data.ema21 > 0 and data.ema50 > 0:
            if data.price > data.ema21 and data.ema21 > data.ema50:
                b2_ema_score = 5
                b2_ema_detail = f"Full bullish stack (P>{data.ema21:.0f}>{data.ema50:.0f})"
            elif data.price > data.ema21 and data.ema21 <= data.ema50:
                b2_ema_score = 2
                b2_ema_detail = f"Above short EMA, long bearish ({data.ema21:.0f}<{data.ema50:.0f})"
            elif data.price < data.ema21 and data.ema21 > data.ema50:
                b2_ema_score = 1
                b2_ema_detail = f"Dip in uptrend ({data.ema21:.0f}>{data.ema50:.0f})"
            else:
                b2_ema_score = 0
                b2_ema_detail = f"Full bearish stack (P<{data.ema21:.0f}<{data.ema50:.0f})"

        breakdown['ema_stack_bonus'] = {
            'score': b2_ema_score, 'max': 5,
            'detail': b2_ema_detail
        }

        # ─── Total + Grade ───
        # v5.6: 5 base filters + 2 bonuses. F1(20)+F2(25)+F3(20)+F4(20)+F5(15)=100 + B1(5)+B2(5)=110
        total = f1_total + f2_score + f3_score + f4_score + f5_score + b1_macd_score + b2_ema_score

        score_strong = getattr(config, 'PH2_SCORE_STRONG_BUY', 85)
        score_full = getattr(config, 'PH2_SCORE_FULL_POSITION', 75)
        score_min = getattr(config, 'PH2_SCORE_ENTRY_MIN', 75)
        mult_full = getattr(config, 'PH2_MULTIPLIER_FULL', 1.0)

        if total >= score_strong:
            grade = 'STRONG_BUY'
            position_multiplier = mult_full
        elif total >= score_min:
            grade = 'BUY'
            position_multiplier = mult_full
        else:
            grade = 'SKIP'
            position_multiplier = 0.0

        bonus = b1_macd_score + b2_ema_score
        base_total = f1_total + f2_score + f3_score + f4_score + f5_score
        return {
            'total': total,
            'base_total': base_total,
            'bonus': bonus,
            'grade': grade,
            'position_multiplier': position_multiplier,
            'breakdown': breakdown,
        }


# ============================================================================
# STOCK MONITOR CLASS
# ============================================================================

class StockMonitor:
    """Monitors a single stock for entry opportunities."""

    def __init__(self, stock_data: dict, config):
        self.symbol = stock_data['symbol']
        self.instrument_token = stock_data.get('instrument_token')
        self.phase1_ltp = stock_data.get('ltp', 0)
        self.phase1_open = stock_data.get('open', 0)

        # v5.3.6: Monitoring timeout tracking (2-hour drop rule)
        self.monitoring_start_time = datetime.now()
        
        v_recovery_data = stock_data.get('v_recovery', {})
        self.recovery_percent = v_recovery_data.get('recovery_percent', 0) if isinstance(v_recovery_data, dict) else 0
        self.priority_rank = 0
        
        # Real-time data
        self.current_ltp = None
        self.current_open = None
        self.current_high = None
        self.current_low = None
        self.current_volume = None
        self.last_update = None
        self.avg_volume_cached = 0
        
        # RSI tracking
        self.current_rsi = None
        self.previous_rsi = None
        self.rsi_history = []
        self.rsi_lowest = None
        self.rsi_lowest_time = None
        self.rsi_values_only = []
        
        # AI attributes
        self.historical_data = None
        self.recent_news = []
        
        # State tracking
        self.rsi_state = "WATCHING"
        self.in_entry_zone = False
        self.stage1_alerted = False
        self.stage1_alert_time = None
        self.stage1_rsi = None
        self.stage2_triggered = False
        self.stage2_trigger_time = None
        self.stage2_rsi = None
        
        # Position tracking
        self.position_status = "NOT_ENTERED"
        self.lots_taken = 0
        
        # Filter status
        self.filter_results = {}
        self.all_filters_passed = False
        
        # Technical indicators
        self.vwap = None
        self.macd_hist = None
        self.volume_ratio = 1.0  # v4.5.5 FIX: Default to 1.0 not None
        self.adx_value = None
        self.volume_spike_at_reversal = None
        
        # v4.5.5 FIX: New attributes for IntelligentEngine scoring
        self.ma20 = 0.0           # 20-period moving average
        self.ema21 = 0.0          # 21-period EMA
        self.ema21_prev = 0.0     # Previous EMA21 for slope calculation
        self.ema50 = 0.0          # 50-period EMA
        self.atr = 0.0            # Average True Range (14-period)
        self.support_level = 0.0  # Recent support (20-day low)
        self.prev_close = 0.0     # Previous day close

        # v5.5: Price level data (extracted from historical API, not new API calls)
        self.prev_day_high = 0.0       # PDH — previous trading day's high
        self.prev_day_low = 0.0        # PDL — previous trading day's low
        self.prev_week_high = 0.0      # PWH — previous week's high
        self.prev_week_low = 0.0       # PWL — previous week's low
        self.nearest_round_below = 0.0 # Nearest round number below LTP
        self.nearest_round_above = 0.0 # Nearest round number above LTP

        # Monitoring stats
        self.update_count = 0
        self.monitoring_start = datetime.now()
        self.config = config
        self.kalman_enabled = getattr(config, "ENABLE_KALMAN_FILTER", False)

        # Phase E: MAP filter for V-Recovery detection
        self.kalman_map = None  # Initialized on first price update
        self.map_v_recovery = False
        self.map_v_recovery_confidence = 0.0

    def update_live_data(self, quote_data: dict):
        self.current_ltp = quote_data.get('last_price', 0)
        self.current_open = quote_data.get('ohlc', {}).get('open', 0)
        self.current_high = quote_data.get('ohlc', {}).get('high', 0)
        self.current_low = quote_data.get('ohlc', {}).get('low', 0)
        self.current_volume = quote_data.get('volume', 0)
        self.last_update = datetime.now()
        self.update_count += 1
    
    def update_rsi(self, rsi_value: float):
        self.previous_rsi = self.current_rsi
        self.current_rsi = rsi_value
        self.rsi_history.append((datetime.now().isoformat(), rsi_value))
        self.rsi_values_only.append(rsi_value)
        
        if len(self.rsi_history) > 50:
            self.rsi_history = self.rsi_history[-50:]
        if len(self.rsi_values_only) > 50:
            self.rsi_values_only = self.rsi_values_only[-50:]
        
        if self.rsi_lowest is None or rsi_value < self.rsi_lowest:
            self.rsi_lowest = rsi_value
            self.rsi_lowest_time = datetime.now()
        
        if rsi_value > 45:
            self.rsi_state = "WATCHING"
            self.in_entry_zone = False
        elif 35 <= rsi_value <= 45:
            self.rsi_state = "APPROACHING"
            self.in_entry_zone = False
        elif 20 <= rsi_value < 35:
            self.rsi_state = "STAGE_1"
            self.in_entry_zone = True
            if not self.stage1_alerted:
                self.stage1_alerted = True
                self.stage1_alert_time = datetime.now()
                self.stage1_rsi = rsi_value
        else:
            self.rsi_state = "STAGE_1"
            self.in_entry_zone = True
    
    def update_kalman_map(self, price: float, rsi: float, volume_ratio: float):
        """Update MAP filter for V-Recovery detection (Phase E)."""
        try:
            if self.kalman_map is None:
                from kalman_filter import KalmanMAPFilter
                self.kalman_map = KalmanMAPFilter()
                self.kalman_map.set_symbol(self.symbol)
                self.kalman_map.initialize(price, rsi=rsi, volume_momentum=volume_ratio - 1.0)
                return

            vol_momentum = volume_ratio - 1.0
            map_state = self.kalman_map.process_measurement(price, rsi=rsi,
                                                            volume_momentum=vol_momentum)
            self.map_v_recovery = map_state.v_recovery_bottom
            self.map_v_recovery_confidence = map_state.v_recovery_confidence
        except Exception:
            pass  # Never let MAP filter break entry flow

    def check_rsi_cross_above_threshold(self) -> bool:
        if self.previous_rsi is None or self.current_rsi is None:
            return False
        threshold = getattr(self, 'rsi_threshold', 35.0)
        return self.previous_rsi < threshold and self.current_rsi >= threshold

    def to_dict(self) -> dict:
        return {
            'symbol': self.symbol,
            'priority_rank': self.priority_rank,
            'recovery_percent': self.recovery_percent,
            'current_ltp': self.current_ltp,
            'current_rsi': self.current_rsi,
            'rsi_state': self.rsi_state,
            'vwap': self.vwap,
            'stage1_alerted': self.stage1_alerted,
            'stage2_triggered': self.stage2_triggered,
            'position_status': self.position_status,
            'lots_taken': self.lots_taken,
            'update_count': self.update_count,
            'last_update': self.last_update.isoformat() if self.last_update else None
        }


# ============================================================================
# TECHNICAL INDICATORS
# ============================================================================

class TechnicalIndicators:
    """Calculate technical indicators for entry validation"""
    
    @staticmethod
    def calculate_rsi(kite: KiteConnect, instrument_token: int, period: int = 14, 
                     interval: str = "5minute") -> Optional[float]:
        try:
            from_date = datetime.now() - timedelta(days=5)
            to_date = datetime.now()
            
            historical = kite.historical_data(
                instrument_token=instrument_token,
                from_date=from_date,
                to_date=to_date,
                interval=interval
            )
            
            if historical is None or len(historical) < period + 1:
                return None
            
            closes = np.array([candle['close'] for candle in historical], dtype=float)
            rsi_values = talib.RSI(closes, timeperiod=period)
            current_rsi = rsi_values[-1]
            
            return float(current_rsi) if not np.isnan(current_rsi) else None
        except Exception as e:
            logger.error(f"Token {instrument_token}: RSI calculation failed: {e}")
            return None
    
    @staticmethod
    def calculate_vwap(historical_data: list) -> Optional[float]:
        try:
            if not historical_data:
                return None
            
            total_pv = 0
            total_v = 0
            
            for candle in historical_data:
                typical_price = (candle['high'] + candle['low'] + candle['close']) / 3
                volume = candle['volume']
                total_pv += typical_price * volume
                total_v += volume
            
            return float(total_pv / total_v) if total_v > 0 else None
        except Exception as e:
            logger.error(f"VWAP calculation failed: {e}")
            return None
    
    @staticmethod
    def calculate_macd(kite: KiteConnect, instrument_token: int, 
                      fast: int = 5, slow: int = 13, signal: int = 8) -> Optional[float]:
        try:
            from_date = datetime.now() - timedelta(days=5)
            to_date = datetime.now()
            
            historical = kite.historical_data(
                instrument_token=instrument_token,
                from_date=from_date,
                to_date=to_date,
                interval="5minute"
            )
            
            if len(historical) < slow + signal:
                return None
            
            closes = np.array([candle['close'] for candle in historical], dtype=float)
            macd, signal_line, hist = talib.MACD(closes, fastperiod=fast, slowperiod=slow, signalperiod=signal)
            current_hist = hist[-1]
            
            return float(current_hist) if not np.isnan(current_hist) else None
        except Exception as e:
            logger.error(f"Token {instrument_token}: MACD calculation failed: {e}")
            return None
    
    @staticmethod
    def check_market_regime(kite: KiteConnect, threshold: float = -1.0) -> dict:
        try:
            nifty_quote = kite.quote("NSE:NIFTY 50")
            
            if not nifty_quote or "NSE:NIFTY 50" not in nifty_quote:
                return {'allow_entries': True, 'nifty_change': 0.0, 'nifty_current': 0.0, 
                        'nifty_open': 0.0, 'reason': 'NIFTY data unavailable - entries allowed (fail-safe)'}
            
            nifty_data = nifty_quote["NSE:NIFTY 50"]
            nifty_open = nifty_data['ohlc']['open']
            nifty_current = nifty_data['last_price']
            nifty_change_pct = ((nifty_current - nifty_open) / nifty_open) * 100
            allow_entries = nifty_change_pct >= threshold
            
            if allow_entries:
                reason = f"Market {'UP' if nifty_change_pct > 0 else 'down'} {nifty_change_pct:+.2f}% - Allowed ✅"
            else:
                reason = f"Market CRASH! NIFTY {nifty_change_pct:.2f}% < {threshold}% - BLOCKED! ⛔"
            
            return {
                'allow_entries': allow_entries,
                'nifty_change': round(nifty_change_pct, 2),
                'nifty_current': nifty_current,
                'nifty_open': nifty_open,
                'reason': reason
            }
        except Exception as e:
            return {'allow_entries': True, 'nifty_change': 0.0, 'nifty_current': 0.0, 
                    'nifty_open': 0.0, 'reason': f'NIFTY check error - entries allowed (fail-safe): {str(e)}'}
    
    @staticmethod
    def check_nifty_market_filter(kite: KiteConnect, threshold: float = -1.0) -> dict:
        return TechnicalIndicators.check_market_regime(kite, threshold)


# ============================================================================
# UTILITY: ADX CALCULATION (extracted from dead EntryFilters class v5.3.0)
# ============================================================================

def calculate_adx(kite, instrument_token: int, config, period: int = None) -> float:
    """Calculate ADX for a given instrument. Standalone utility function."""
    if period is None:
        period = getattr(config, 'ADX_PERIOD', 14)
    
    try:
        days_needed = max(3, (period + 20) // 75 + 1)
        from_date = datetime.now() - timedelta(days=days_needed)
        to_date = datetime.now()
        
        candles = kite.historical_data(
            instrument_token=instrument_token,
            from_date=from_date,
            to_date=to_date,
            interval='15minute'
        )
        
        if not candles or len(candles) < period + 14:
            return None
        
        high = np.array([c['high'] for c in candles], dtype=float)
        low = np.array([c['low'] for c in candles], dtype=float)
        close = np.array([c['close'] for c in candles], dtype=float)
        
        adx = talib.ADX(high, low, close, timeperiod=period)
        valid_adx = adx[~np.isnan(adx)]
        return float(valid_adx[-1]) if len(valid_adx) > 0 else None
    except Exception as e:
        logger.error(f"ADX calculation error: {e}")
        return None


# ============================================================================
# PHASE 2 ENTRY MONITOR (Main Class)
# ============================================================================

class Phase2EntryMonitor:
    """
    Main Phase 2 monitoring class with Capital Manager integration.
    
    v4.5.0: Now accepts capital_manager parameter for real-time capital checks.
    """
    
    def __init__(self, kite: KiteConnect, config, telegram=None, phase3_manager=None, 
                 capital_manager=None, phase4_manager=None):
        """
        Initialize Phase 2 monitor.
        
        v4.8.1: Added phase4_manager for C2 loop detection.
        
        Args:
            kite: KiteConnect instance
            config: Configuration object
            telegram: TelegramNotifier (optional)
            phase3_manager: Phase3CashSegmentExecutor for real-time execution (optional)
            capital_manager: CapitalManager for capital-aware entries (v4.5.0 NEW!)
            phase4_manager: Phase4PortfolioManager for loop detection (v4.8.1 NEW!)
        """
        self.kite = kite
        self.config = config
        self.telegram = telegram
        self.phase3_manager = phase3_manager
        
        # v4.5.0: Capital Manager Integration
        self.capital_manager = capital_manager
        if capital_manager:
            logger.info("✅ CapitalManager integrated - adaptive position limits enabled")
        else:
            logger.warning("⚠️ No CapitalManager provided - using legacy position limits")
        
        # v4.8.1 C2: Phase4 integration for loop detection
        self.phase4_manager = phase4_manager

        if phase4_manager:
            logger.info("✅ Phase4Manager integrated - loop detection enabled")
        else:
            logger.info("ℹ️  Phase4Manager not provided - loop detection disabled")
        
        # Create directories
        os.makedirs('data/phase2_outputs', exist_ok=True)
        os.makedirs('logs', exist_ok=True)
        
        # v4.5.5: NIFTY filter state tracking (transition notifications)
        self._nifty_filter_blocked = False
        
        # Stock monitors
        self.monitors: List[StockMonitor] = []
        
        # v4.5.5: Blocked signal tracking for Telegram visibility
        self.last_cycle_blocked = []  # [{symbol, reason, details}, ...]
        
        # Entry tracking
        self.entries_taken = 0
        self.max_entries = config.MAX_TOTAL_POSITIONS
        
        # v5.2.1: Daily duplicate entry prevention - once a stock gets Phase 3 entry, block it for the day
        self.traded_today: set = set()
        
        # Kalman filters
        self.kalman_filters = {}
        self.kalman_enabled = getattr(config, "ENABLE_KALMAN_FILTER", False)
        
        # Market regime
        self.market_regime = None
        
        # Initialize AI modules
        self._init_ai_modules(config)
        
        # Initialize adaptive RSI
        self._init_adaptive_rsi(config)
        
        # v5.3.2: RSI Zone Trackers (replace ScoreDebouncer)
        self.rsi_trackers = {}    # symbol -> RSIZoneTracker

        # v5.3.2: Ensure ramp_detector exists (backup — already created in _init_adaptive_rsi)
        if not hasattr(self, 'ramp_detector'):
            self.ramp_detector = RampDetector(config)

        # Technical indicators
        self.tech = TechnicalIndicators()
        
        # Heartbeat
        self.enable_heartbeat = getattr(config, 'ENABLE_MONITORING_HEARTBEAT', False)
        self.heartbeat_interval = getattr(config, 'HEARTBEAT_INTERVAL_MINUTES', 15) * 60
        self.last_heartbeat_time = {}
        
        logger.info("Phase 2 Entry Monitor v5.3.5 initialized")
    
    def _init_ai_modules(self, config):
        """Initialize AI modules"""
        self.finbert = None
        self.news_scraper = None
        self.ai_intelligence = None
        self.strategic_advisor = None
        self.chatgpt_advisor = None
        
        if getattr(config, 'ENABLE_AI_INTELLIGENCE', False):
            try:
                if getattr(config, 'ENABLE_FINBERT', False):
                    from finbert_analyzer import FinBERTAnalyzer  # lazy: needs torch/transformers
                    self.finbert = FinBERTAnalyzer()
                    self.news_scraper = NewsScraperFree()
                    logger.info("✅ FinBERT + News Scraper initialized")
                
                self.ai_intelligence = AIIntelligence()
                logger.info("✅ AI Intelligence module initialized")
            except Exception as e:
                logger.error(f"AI module init failed: {e}")
        
        if getattr(config, 'ENABLE_CHATGPT_STRATEGIC_ADVISOR', False):
            try:
                api_key = getattr(config, 'CHATGPT_API_KEY', None)
                if api_key:
                    self.strategic_advisor = ChatGPTStrategicAdvisor(
                        api_key=api_key,
                        model=getattr(config, 'STRATEGIC_ADVISOR_MODEL', 'gpt-4o')
                    )
                    logger.info("✅ Strategic Advisor initialized")
            except Exception as e:
                logger.error(f"Strategic Advisor init failed: {e}")
    
    def _init_adaptive_rsi(self, config):
        """Initialize adaptive RSI system and Ramp Detector."""
        self.use_adaptive_rsi = getattr(config, 'ENABLE_ADAPTIVE_RSI', False)
        self.use_atr_targets = getattr(config, 'ENABLE_ATR_DYNAMIC_TARGETS', False)
        self.use_volatility_sizing = getattr(config, 'ENABLE_VOLATILITY_CLUSTERING', False)

        # v5.3.2: AdaptiveRSIEntry replaced by RSIZoneTracker (no import needed)

        # v5.3.0: Ramp Detector (Kalman + MA + Rising Lows)
        self.ramp_detector = RampDetector(config)
        logger.info("Ramp Detector initialized (3-detector fusion)")

    # ═══════════════════════════════════════════════════════════════════════
    # v5.3.2: HELPER METHODS
    # ═══════════════════════════════════════════════════════════════════════

    def _build_market_data(self, monitor: StockMonitor) -> MarketData:
        """Build MarketData from StockMonitor cached data. No API calls."""
        return MarketData(
            symbol=monitor.symbol,
            timestamp=datetime.now(),
            price=monitor.current_ltp or 0,
            open=monitor.current_open or 0,
            high=monitor.current_high or 0,
            low=monitor.current_low or 0,
            volume=monitor.current_volume or 0,
            avg_volume_20=monitor.avg_volume_cached or 0,
            rsi=monitor.current_rsi or 50,
            rsi_history=monitor.rsi_values_only or [],
            atr=getattr(monitor, 'atr', 0) or 0,
            adx=getattr(monitor, 'adx_value', None) or 0,
            vwap=getattr(monitor, 'vwap', 0) or 0,
            ma20=getattr(monitor, 'ma20', 0) or 0,
            macd_hist=getattr(monitor, 'macd_hist', 0) or 0,
            ema21=getattr(monitor, 'ema21', 0) or 0,
            ema50=getattr(monitor, 'ema50', 0) or 0,
            recovery_percent=monitor.recovery_percent or 0,
            volume_ratio=getattr(monitor, 'volume_ratio', 1.0) or 1.0,
            already_traded_today=monitor.symbol in self.traded_today,
            capital_available=self._get_available_capital(monitor.symbol),
        )

    def _get_available_capital(self, symbol: str) -> float:
        """Get available capital from CapitalManager or fallback."""
        if self.capital_manager:
            try:
                # v5.3.3: Use get_available() directly — don't call can_enter(0)
                # which triggers verbose logging and wrong concentration math
                return self.capital_manager.get_available()
            except Exception:
                pass
        return getattr(self.config, 'BASE_CAPITAL_PER_TRADE', 10000)

    def _get_stock_sentiment(self, monitor: StockMonitor) -> Optional[dict]:
        """Get FinBERT sentiment for a stock. Returns None on failure."""
        if not self.finbert or not self.news_scraper:
            return None
        try:
            headlines = self.news_scraper.get_stock_news(
                symbol=monitor.symbol, max_results=5
            )
            if headlines and len(headlines) >= 1:
                return self.finbert.analyze_sentiment(
                    text_list=headlines,
                    symbol=monitor.symbol,
                    use_temporal_decay=getattr(self.config, 'FINBERT_USE_TEMPORAL_DECAY', False)
                )
        except Exception as e:
            logger.debug(f"{monitor.symbol}: FinBERT failed: {e}")
        return None

    def _log_score_breakdown(self, symbol: str, score_result: dict):
        """Log detailed score breakdown."""
        breakdown = score_result['breakdown']
        bonus = score_result.get('bonus', 0)
        bonus_tag = f" (+{bonus} bonus)" if bonus > 0 else ""
        logger.info(f"📊 {symbol}: SCORE {score_result['total']:.0f}/110 ({score_result['grade']}){bonus_tag}")
        for name, detail in breakdown.items():
            status = '✅' if detail['score'] > 0 else '⚪' if detail['score'] == 0 else '🔴'
            logger.info(f"   {status} {name}: {detail['score']}/{detail['max']} -- {detail['detail']}")

    def _send_score_telegram(self, data: MarketData, score_result: dict,
                              tracker: RSIZoneTracker):
        """Send Telegram notification with score results."""
        if not self.telegram:
            return

        breakdown = score_result['breakdown']
        bonus = score_result.get('bonus', 0)
        bonus_tag = f" (+{bonus})" if bonus > 0 else ""
        lines = [
            f"{'✅' if score_result['grade'] != 'SKIP' else '⏭️'} "
            f"{data.symbol} | Score: {score_result['total']:.0f}/110 ({score_result['grade']}){bonus_tag}",
            "",
            f"RSI Quality:     {breakdown['rsi_quality']['score']}/{breakdown['rsi_quality']['max']}",
            f"Recovery:        {breakdown['recovery_quality']['score']}/{breakdown['recovery_quality']['max']}",
            f"Volume:          {breakdown['volume_ratio']['score']}/{breakdown['volume_ratio']['max']}",
            f"Trend:           {breakdown['trend_context']['score']}/{breakdown['trend_context']['max']}",
            f"Timing:          {breakdown['session_timing']['score']}/{breakdown['session_timing']['max']}",
            f"MACD Bonus:      {breakdown.get('macd_bonus', {}).get('score', 0)}/{breakdown.get('macd_bonus', {}).get('max', 5)}",
            f"EMA Stack:       {breakdown.get('ema_stack_bonus', {}).get('score', 0)}/{breakdown.get('ema_stack_bonus', {}).get('max', 5)}",
            "",
            f"RSI: dip={tracker.zone_low_rsi:.1f} now={tracker.kalman_rsi:.1f} vel={tracker.kalman_velocity:+.2f}",
            f"Zone: [{tracker.adaptive_zone_low:.0f}-{tracker.adaptive_zone_high:.0f}] (ctr={tracker.adaptive_center:.0f})",
            f"Price: {data.price:.2f} | Vol Ratio: {data.volume_ratio:.2f}x",
        ]

        if score_result['grade'] != 'SKIP':
            lines.append(f"\nPosition: {score_result['position_multiplier']*100:.0f}%")
            lines.append("Sending to ChatGPT Trading Manager...")

        try:
            self.telegram.send_message("\n".join(lines))
        except Exception as e:
            logger.debug(f"Telegram score notification failed: {e}")

    def _format_chatgpt_package(self, data: MarketData, tracker: RSIZoneTracker,
                                 score_result: dict, ramp_result, finbert_result,
                                 monitor=None) -> str:
        """Build clean text package for ChatGPT Trading Manager."""
        bd = score_result['breakdown']

        pkg = (
            f"{'=' * 47}\n"
            f"TRADE SIGNAL: {data.symbol} | Score: {score_result['total']:.0f}/110 ({score_result['grade']})\n"
            f"{'=' * 47}\n"
            f"\n"
            f"HARD GATES: ALL PASSED\n"
            f"\n"
            f"PRICE CONTEXT:\n"
            f"  Entry Price: ₹{data.price:.2f}\n"
            f"  Today Open: ₹{getattr(data, 'open', 0):.2f}\n"
            f"  PDH (Prev Day High): ₹{getattr(monitor, 'prev_day_high', 0):.2f}\n"
            f"  PDL (Prev Day Low): ₹{getattr(monitor, 'prev_day_low', 0):.2f}\n"
            + (f"  VWAP: ₹{data.vwap:.2f}\n" if getattr(data, 'vwap', 0) else "")
            + (f"  ATR: ₹{data.atr:.2f}\n" if getattr(data, 'atr', 0) else "")
            + f"\n"
            f"RSI TRIGGER:\n"
            f"  Zone entered: RSI dipped to {tracker.zone_low_rsi:.1f}\n"
            f"  Current: RSI {data.rsi:.1f} (Kalman: {tracker.kalman_rsi:.1f})\n"
            f"  Velocity: {tracker.kalman_velocity:+.2f}\n"
            f"  Adaptive Zone: [{tracker.adaptive_zone_low:.0f}-{tracker.adaptive_zone_high:.0f}] (ctr={tracker.adaptive_center:.0f})\n"
            f"  Recovery: {tracker.recovery_percent:.0f}%\n"
            f"  Readings since zone: {tracker.readings_since_zone}\n"
            f"\n"
            f"SCORED FILTERS:\n"
            f"  RSI Quality:        {bd['rsi_quality']['score']}/{bd['rsi_quality']['max']}  {bd['rsi_quality']['detail']}\n"
            f"  Recovery Quality:   {bd['recovery_quality']['score']}/{bd['recovery_quality']['max']}  {bd['recovery_quality']['detail']}\n"
            f"  Volume Ratio:       {bd['volume_ratio']['score']}/{bd['volume_ratio']['max']}  {bd['volume_ratio']['detail']}\n"
            f"  Trend Context:      {bd['trend_context']['score']}/{bd['trend_context']['max']}  {bd['trend_context']['detail']}\n"
            f"  Session Timing:     {bd['session_timing']['score']}/{bd['session_timing']['max']}  {bd['session_timing']['detail']}\n"
            f"\n"
            f"CAPITAL: {data.capital_available:,.0f} available\n"
            f"POSITION SIZE: {score_result['position_multiplier']*100:.0f}%\n"
            f"\n"
            f"DECISION REQUIRED: GO / NOGO\n"
            f"{'=' * 47}"
        )
        return pkg

    def sync_entries_taken(self, actual_positions: int):
        """Sync entries_taken with actual broker positions."""
        if self.entries_taken != actual_positions:
            logger.info(f"📊 Syncing entries_taken: {self.entries_taken} → {actual_positions}")
            self.entries_taken = actual_positions
    
    def reset_entries_taken(self):
        """Reset entries counter"""
        logger.info(f"🔄 Resetting entries_taken: {self.entries_taken} → 0")
        self.entries_taken = 0
    
    def load_active_stocks(self) -> Optional[List[dict]]:
        """Load stocks from ACTIVE.json file."""
        filepath = self.config.ACTIVE_STOCKS_FILE
        data = safe_read(filepath)
        
        if data is None or 'stocks' not in data:
            logger.error("Failed to load ACTIVE stocks file")
            return None
        
        stocks = data['stocks']
        saved_at = datetime.fromisoformat(data['saved_at'])
        age_days = (datetime.now() - saved_at).days
        
        if age_days > self.config.MAX_STOCK_AGE_DAYS:
            logger.error(f"Stocks too old ({age_days} days)")
            return None
        
        logger.info(f"Loaded {len(stocks)} stocks (age: {age_days} days)")
        return stocks
    
    def reload_active_stocks(self) -> bool:
        """Reload active stocks from ACTIVE.json."""
        try:
            stocks = self.load_active_stocks()
            if not stocks:
                return False
            
            self.monitors.clear()
            for stock_data in stocks:
                monitor = StockMonitor(stock_data, self.config)
                self.monitors.append(monitor)
                
                if self.kalman_enabled:
                    self.kalman_filters[stock_data.get('symbol', '')] = create_kalman_filter(self.config)
            
            logger.info(f"✅ Reloaded {len(self.monitors)} stock monitors")
            return True
        except Exception as e:
            logger.error(f"Failed to reload stocks: {e}")
            return False
    
    def initialize_monitors(self, stocks: List[dict]):
        """Create StockMonitor for each stock."""
        existing_symbols = {m.symbol for m in self.monitors} if self.monitors else set()
        
        if not hasattr(self, 'monitors') or self.monitors is None:
            self.monitors = []
        
        new_count = 0
        for i, stock in enumerate(stocks, 1):
            if isinstance(stock, str):
                stock_data = {'symbol': stock, 'ltp': 0, 'open': 0, 'v_recovery': {'recovery_percent': 0}}
                priority_rank = i
            else:
                stock_data = stock
                priority_rank = stock.get('priority_rank', i)
            
            symbol = stock_data['symbol']
            if symbol in existing_symbols:
                continue
            
            monitor = StockMonitor(stock_data, self.config)
            monitor.priority_rank = priority_rank
            
            # Cache volume
            try:
                end_date = datetime.now()
                start_date = end_date - timedelta(days=30)
                
                hist = self.kite.historical_data(
                    instrument_token=monitor.instrument_token,
                    from_date=start_date,
                    to_date=end_date,
                    interval="day"
                )
                
                if hist and len(hist) > 0:
                    recent_hist = hist[-20:] if len(hist) >= 20 else hist
                    volumes = [candle['volume'] for candle in recent_hist]
                    monitor.avg_volume_cached = sum(volumes) / len(volumes)

                    # v5.5: Extract price levels from SAME hist[] data (zero new API calls)
                    # PDH/PDL = previous completed trading day
                    # Use hist[-2] for safety — guaranteed to be a completed day
                    if len(hist) >= 2:
                        prev_day = hist[-2]
                        monitor.prev_day_high = prev_day['high']
                        monitor.prev_day_low = prev_day['low']
                        monitor.prev_close = prev_day['close']
                        logger.info(f"   📊 {symbol}: PDH=₹{prev_day['high']:.2f} PDL=₹{prev_day['low']:.2f}")

                    # PWH/PWL = highest high and lowest low from last 5 trading days
                    if len(hist) >= 7:
                        prev_week = hist[-7:-2]
                        monitor.prev_week_high = max(c['high'] for c in prev_week)
                        monitor.prev_week_low = min(c['low'] for c in prev_week)

                    # Nearest round number
                    if monitor.phase1_ltp > 0:
                        price = monitor.phase1_ltp
                        if price >= 1000:
                            step = 100
                        elif price >= 500:
                            step = 50
                        elif price >= 100:
                            step = 25
                        else:
                            step = 10
                        monitor.nearest_round_below = (price // step) * step
                        monitor.nearest_round_above = monitor.nearest_round_below + step
            except Exception as e:
                logger.error(f"{symbol}: Failed to cache volume: {e}")
                monitor.avg_volume_cached = 0
            
            self.monitors.append(monitor)
            new_count += 1
        
        logger.info(f"✅ Monitoring: {len(self.monitors)} stocks total ({new_count} new)")

    def check_monitoring_timeouts(self) -> List[str]:
        """
        v5.3.6: Drop stocks that have been monitored for > PHASE2_MONITORING_TIMEOUT_MINUTES
        without generating a trade signal. Returns list of dropped symbols.
        """
        timeout_minutes = getattr(self.config, 'PHASE2_MONITORING_TIMEOUT_MINUTES', 120)
        now = datetime.now()
        dropped = []

        for monitor in list(self.monitors):
            elapsed_min = (now - monitor.monitoring_start_time).total_seconds() / 60

            # v5.4.2: Smart eviction — check if ZoneTracker evicted the stock
            if hasattr(self, 'rsi_trackers') and monitor.symbol in self.rsi_trackers:
                tracker = self.rsi_trackers[monitor.symbol]
                if getattr(tracker, 'eviction_reason', None):
                    logger.info(f"📤 {monitor.symbol}: Evicted by ZoneTracker — {tracker.eviction_reason} "
                               f"(monitored {elapsed_min:.0f} min)")
                    dropped.append(monitor.symbol)
                    self.monitors.remove(monitor)
                    del self.rsi_trackers[monitor.symbol]
                    continue  # Skip to next monitor (already removed)

            if elapsed_min >= timeout_minutes:
                logger.info(f"⏰ {monitor.symbol}: Dropped from Phase 2 monitoring (no signal after {elapsed_min:.0f} min)")
                logger.info(f"   Phase 1 adaptive scan will pick new candidates")
                dropped.append(monitor.symbol)
                self.monitors.remove(monitor)
                # Clean RSI tracker if exists
                if hasattr(self, 'rsi_trackers') and monitor.symbol in self.rsi_trackers:
                    del self.rsi_trackers[monitor.symbol]

        return dropped

    def prioritize_stocks(self, stocks: List[dict], chatgpt_rankings: List[dict]) -> List[dict]:
        """Prioritize stocks by recovery %, sentiment, and MAP V-Recovery signal."""
        sentiment_scores = {r['symbol']: r.get('sentiment_score', 50) for r in chatgpt_rankings}

        # Build MAP V-Recovery lookup from monitors
        map_v_recovery_scores = {}
        for monitor in self.monitors:
            if getattr(monitor, 'map_v_recovery', False):
                map_v_recovery_scores[monitor.symbol] = monitor.map_v_recovery_confidence

        for stock in stocks:
            symbol = stock['symbol']
            recovery = stock.get('v_recovery', {}).get('recovery_percent', 0)
            sentiment = sentiment_scores.get(symbol, 50)
            base_score = (recovery * 0.7) + (sentiment * 0.3)

            # Phase E: MAP V-Recovery boost (up to +15 points)
            map_boost = map_v_recovery_scores.get(symbol, 0.0) * 15.0
            stock['priority_score'] = base_score + map_boost
            stock['map_v_recovery_boost'] = round(map_boost, 1)

        stocks_sorted = sorted(stocks, key=lambda x: x['priority_score'], reverse=True)

        for i, stock in enumerate(stocks_sorted):
            stock['priority_rank'] = i + 1

        return stocks_sorted
    
    def update_all_monitors(self):
        """Update data for all stock monitors.
        
        v3.3.0: Added per-stock ADX calculation every monitoring cycle.
        ADX value stored in monitor.adx_value for ChatGPT decision context.
        """
        if not self.monitors:
            return
        
        for monitor in self.monitors:
            try:
                quote = self.kite.quote(f"NSE:{monitor.symbol}")
                monitor.update_live_data(quote[f"NSE:{monitor.symbol}"])
                
                if monitor.instrument_token is None:
                    monitor.instrument_token = quote[f"NSE:{monitor.symbol}"].get('instrument_token')
                
                if monitor.instrument_token:
                    rsi = self.tech.calculate_rsi(self.kite, monitor.instrument_token)
                    if rsi is not None:
                        monitor.update_rsi(rsi)
                    
                    if self.config.VWAP_ENABLED:
                        from_date = datetime.now().replace(hour=9, minute=15, second=0)
                        historical = self.kite.historical_data(
                            instrument_token=monitor.instrument_token,
                            from_date=from_date,
                            to_date=datetime.now(),
                            interval="5minute"
                        )
                        monitor.vwap = self.tech.calculate_vwap(historical)
                    
                    monitor.macd_hist = self.tech.calculate_macd(self.kite, monitor.instrument_token)
                    
                    # v3.3.0: Per-stock ADX calculation for ChatGPT decision context
                    if getattr(self.config, 'ENABLE_ADX_FILTER', True):
                        try:
                            adx_val = calculate_adx(
                                self.kite, monitor.instrument_token, self.config
                            )
                            if adx_val is not None:
                                monitor.adx_value = adx_val
                        except Exception as e:
                            logger.debug(f"{monitor.symbol}: ADX calc failed: {e}")
                

                    # ═══════════════════════════════════════════════════════════════
                    # v4.5.5 FIX: Calculate missing technical indicators
                    # These were initialized but never calculated - causing crashes!
                    # ═══════════════════════════════════════════════════════════════
                    try:
                        # Get historical data for calculations (30 days for EMAs)
                        from_date_hist = datetime.now().replace(hour=9, minute=15, second=0) - timedelta(days=60)
                        historical_daily = self.kite.historical_data(
                            instrument_token=monitor.instrument_token,
                            from_date=from_date_hist,
                            to_date=datetime.now(),
                            interval="day"
                        )
                        
                        if historical_daily and len(historical_daily) >= 5:
                            closes = [c['close'] for c in historical_daily]
                            highs = [c['high'] for c in historical_daily]
                            lows = [c['low'] for c in historical_daily]
                            
                            # MA20 - 20-period Simple Moving Average
                            if len(closes) >= 20:
                                monitor.ma20 = float(np.mean(closes[-20:]))
                            else:
                                monitor.ma20 = float(np.mean(closes))
                            
                            # EMA21 and EMA50 using TA-Lib
                            closes_arr = np.array(closes, dtype=float)
                            
                            # Store previous EMA21 for slope calculation
                            monitor.ema21_prev = monitor.ema21
                            
                            if len(closes_arr) >= 21:
                                ema21_arr = talib.EMA(closes_arr, timeperiod=21)
                                monitor.ema21 = float(ema21_arr[-1]) if not np.isnan(ema21_arr[-1]) else monitor.ma20
                            else:
                                monitor.ema21 = monitor.ma20
                            
                            if len(closes_arr) >= 50:
                                ema50_arr = talib.EMA(closes_arr, timeperiod=50)
                                monitor.ema50 = float(ema50_arr[-1]) if not np.isnan(ema50_arr[-1]) else monitor.ma20
                            else:
                                monitor.ema50 = monitor.ma20
                            
                            # ATR - Average True Range (14-period) using TA-Lib
                            if len(closes) >= 15:
                                highs_arr = np.array(highs, dtype=float)
                                lows_arr = np.array(lows, dtype=float)
                                atr_arr = talib.ATR(highs_arr, lows_arr, closes_arr, timeperiod=14)
                                monitor.atr = float(atr_arr[-1]) if not np.isnan(atr_arr[-1]) else 0.0
                            
                            # Support Level - 20-day low
                            if len(lows) >= 20:
                                monitor.support_level = float(min(lows[-20:]))
                            else:
                                monitor.support_level = float(min(lows))
                            
                            # Previous Close
                            if len(closes) >= 2:
                                monitor.prev_close = float(closes[-2])
                            
                            # Volume Ratio - Time-adjusted
                            if monitor.avg_volume_cached > 0 and monitor.current_volume:
                                now = datetime.now()
                                minutes_since_open = (now.hour - 9) * 60 + (now.minute - 15)
                                minutes_since_open = max(1, min(375, minutes_since_open))
                                expected_volume = monitor.avg_volume_cached * (minutes_since_open / 375)
                                if expected_volume > 0:
                                    monitor.volume_ratio = float(monitor.current_volume / expected_volume)
                                else:
                                    monitor.volume_ratio = 1.0
                            
                            logger.debug(f"{monitor.symbol}: ma20={monitor.ma20:.2f}, ema21={monitor.ema21:.2f}, "
                                       f"ema50={monitor.ema50:.2f}, atr={monitor.atr:.2f}, vol_ratio={monitor.volume_ratio:.2f}")
                            
                    except Exception as e:
                        logger.debug(f"{monitor.symbol}: Technical indicator calc failed: {e}")
                        # Keep default values - won't crash
                
                # Update Kalman filter
                if self.kalman_enabled and monitor.symbol in self.kalman_filters:
                    if monitor.current_ltp and monitor.current_ltp > 0:
                        self.kalman_filters[monitor.symbol].update(monitor.current_ltp)

                # Phase E: Update MAP filter for V-Recovery detection
                if monitor.current_ltp and monitor.current_ltp > 0 and monitor.current_rsi:
                    monitor.update_kalman_map(
                        price=monitor.current_ltp,
                        rsi=monitor.current_rsi,
                        volume_ratio=monitor.volume_ratio or 1.0
                    )

                # Fetch news
                if self.news_scraper:
                    try:
                        headlines = self.news_scraper.scrape_latest_headlines(monitor.symbol, max_results=5)
                        monitor.recent_news = headlines
                    except:
                        pass
                        
            except Exception as e:
                logger.error(f"Failed to update {monitor.symbol}: {e}")
    
    def check_entry_signals(self) -> List[dict]:
        """
        v5.3.2: Hard Gates -> RSI Zone Tracker -> Scoring Engine -> ChatGPT Package.

        PRE-FLIGHT (once per cycle):
          PF-1: Time window
          PF-2: NIFTY filter
          PF-3: FinBERT market sentiment (strongly BEARISH -> return)
          PF-4: Daily tracker reset (new day -> clear rsi_trackers)

        PER-STOCK:
          STEP 1: Build MarketData from StockMonitor
          STEP 2: Get/create RSIZoneTracker -> update
          STEP 3: HardGates.check_all() -> blocked? continue
          STEP 4: RAMP + FinBERT + ScoringEngine (5 filters, no volume) -> score < 70? SKIP
          STEP 5: _generate_entry_signal() (unchanged)
          STEP 6: Attach phase2_* data to signal
          STEP 7: Capital reservation = False -> append signal
        """
        signals = []
        self.last_cycle_blocked = []

        if not self.monitors:
            return signals

        # ═══════════════════════════════════════════════════════════════
        # PRE-FLIGHT (market level, run once per cycle)
        # ═══════════════════════════════════════════════════════════════

        # PF-1: Time Window
        now = datetime.now()
        current_time = now.time()
        entry_start = datetime.strptime(
            getattr(self.config, 'PHASE2_ENTRY_WINDOW_START', '09:55'), '%H:%M').time()
        entry_end = datetime.strptime(
            getattr(self.config, 'PHASE2_ABSOLUTE_CUTOFF', '14:55'), '%H:%M').time()

        if current_time < entry_start or current_time > entry_end:
            return signals  # Silent -- runs every cycle

        # PF-2: NIFTY Market Filter
        if not self._check_nifty_filter():
            return signals

        # PF-3: FinBERT Market Sentiment (run once per cycle, not per-stock)
        market_bearish = False
        if self.finbert and self.news_scraper:
            try:
                market_news = self.news_scraper.get_market_news(max_results=5) if hasattr(self.news_scraper, 'get_market_news') else []
                if market_news and len(market_news) >= 2:
                    market_sentiment = self.finbert.analyze_sentiment(
                        text_list=market_news, symbol='MARKET',
                        use_temporal_decay=getattr(self.config, 'FINBERT_USE_TEMPORAL_DECAY', False)
                    )
                    if (market_sentiment.get('label') == 'BEARISH' and
                        market_sentiment.get('confidence', 0) > getattr(self.config, 'FINBERT_MARKET_CONFIDENCE', 80) and
                        market_sentiment.get('sentiment_score', 0) < -0.4):
                        logger.warning(f"Pre-flight: Market BEARISH sentiment -- blocking all entries")
                        market_bearish = True
            except Exception as e:
                logger.debug(f"Market sentiment check failed: {e}")

        if market_bearish:
            return signals

        # PF-4: Daily RSI tracker reset (new day -> clear all trackers)
        today_str = now.strftime('%Y-%m-%d')
        if not hasattr(self, '_last_tracker_reset_day') or self._last_tracker_reset_day != today_str:
            if self.rsi_trackers:
                logger.info(f"New day ({today_str}) -- resetting {len(self.rsi_trackers)} RSI trackers")
                for tracker in self.rsi_trackers.values():
                    tracker.reset_daily()
            self._last_tracker_reset_day = today_str

        # ═══════════════════════════════════════════════════════════════
        # PER-STOCK LOOP
        # ═══════════════════════════════════════════════════════════════

        for monitor in self.monitors:
            try:
                # ─── Pre-check: Max positions ───
                # v5.3.3: Pass real stock price (not 0) so concentration math works
                if self.capital_manager:
                    entry_price = getattr(monitor, 'current_ltp', 0) or 0
                    if not self.capital_manager.can_enter(monitor.symbol, entry_price).get('can_enter', True):
                        logger.info(f"Capital check failed for {monitor.symbol} (₹{entry_price:.0f}) — trying next stock")
                        continue  # v5.3.3: try next stock, don't break entire loop
                elif self.entries_taken >= self.max_entries:
                    logger.info(f"Max positions reached ({self.max_entries})")
                    break

                # ─── Pre-check: Loop detection via Phase 4 ───
                if self.phase4_manager:
                    reentry_allowed, reentry_reason = self.phase4_manager._check_reentry_allowed(monitor.symbol)
                    if not reentry_allowed:
                        logger.info(f"Loop: {monitor.symbol}: Re-entry blocked - {reentry_reason}")
                        self.last_cycle_blocked.append({
                            'symbol': monitor.symbol,
                            'reason': f"Loop Detection: {reentry_reason}",
                            'rsi': monitor.current_rsi,
                            'ltp': monitor.current_ltp,
                        })
                        continue

                # ─── STEP 1: Build MarketData ───
                data = self._build_market_data(monitor)

                # ─── STEP 2: Get/create RSI tracker + update ───
                if data.symbol not in self.rsi_trackers:
                    self.rsi_trackers[data.symbol] = RSIZoneTracker(
                        data.symbol, self.config,
                        recovery_percent=data.recovery_percent
                    )
                tracker = self.rsi_trackers[data.symbol]
                tracker.update(data.rsi, data.rsi_history, self.config,
                             recovery_percent=data.recovery_percent)

                # ─── STEP 3: HARD GATES ───
                gates_passed, gate_reason = HardGates.check_all(data, tracker, self.config)

                if not gates_passed:
                    # v5.3.3: Always log gate result (removed 'trigger not fired' suppression)
                    tracker_info = (f"state={tracker.state}, K-RSI={tracker.kalman_rsi:.1f}, "
                                   f"vel={tracker.kalman_velocity:+.2f}")
                    logger.info(f"HardGate: {data.symbol} ❌ {gate_reason} ({tracker_info})")
                    self.last_cycle_blocked.append({
                        'symbol': data.symbol,
                        'reason': f"Gate: {gate_reason}",
                        'rsi': data.rsi,
                        'ltp': data.price,
                        'tracker_state': tracker.state,
                        'kalman_rsi': tracker.kalman_rsi,
                    })
                    continue   # BLOCKED, next stock

                # ─── STEP 4: SCORING (only reached if ALL gates passed) ───

                # v5.3.3: Log gate passage clearly
                logger.info(f"HardGate: {data.symbol} ✅ ALL GATES PASSED | "
                           f"State={tracker.state} | K-RSI={tracker.kalman_rsi:.1f} | "
                           f"Vel={tracker.kalman_velocity:+.2f} → entering scoring")

                # Run RAMP detector (scoring only, not a gate)
                ramp_result = None
                rsi_history = data.rsi_history
                if rsi_history and len(rsi_history) >= 10:
                    ramp_result = self.ramp_detector.detect(rsi_history)
                    monitor.ramp_result = ramp_result

                # Get FinBERT per-stock sentiment (scoring only, not a veto)
                finbert_result = self._get_stock_sentiment(monitor)

                # Score all 5 filters (v5.3.5: volume removed, RSI/ADX/VWAP rebalanced)
                score_result = ScoringEngine.score_all(
                    data, tracker, finbert_result, self.config
                )

                # Log score breakdown
                self._log_score_breakdown(data.symbol, score_result)

                # Build ChatGPT package (always, for logging even on SKIP)
                chatgpt_pkg = self._format_chatgpt_package(
                    data, tracker, score_result, ramp_result, finbert_result,
                    monitor=monitor
                )

                # Send Telegram score notification
                self._send_score_telegram(data, score_result, tracker)

                if score_result['grade'] == 'SKIP':
                    score_min = getattr(self.config, 'PH2_SCORE_ENTRY_MIN', 75)
                    logger.info(f"SKIP {data.symbol}: Score {score_result['total']:.0f}/110 < {score_min}")
                    self.last_cycle_blocked.append({
                        'symbol': data.symbol,
                        'reason': f"Score {score_result['total']:.0f}/110 < {score_min}",
                        'rsi': data.rsi,
                        'ltp': data.price,
                        'score_breakdown': score_result['breakdown'],
                    })
                    log_regret_trade(
                        data.symbol, score_result['total'], "Phase2_SKIP",
                        f"PH2_SCORE_BELOW_{score_min}",
                        entry_price=data.price, phase="Phase2",
                        rsi_value=data.rsi
                    )
                    continue   # LOW SCORE, next stock

                logger.info(f"PASS {data.symbol}: Score {score_result['total']:.0f}/110 "
                           f"({score_result['grade']}) -- proceeding to signal generation")

                # ─── STEP 5: Generate Signal (AI analysis for targets/stops) ───
                signal = self._generate_entry_signal(monitor)
                if not signal:
                    continue

                # ─── STEP 6: Attach Phase 2 scoring data to signal ───
                signal['phase2_score'] = score_result['total']
                signal['phase2_grade'] = score_result['grade']
                signal['phase2_breakdown'] = score_result['breakdown']
                signal['phase2_position_multiplier'] = score_result['position_multiplier']
                signal['phase2_chatgpt_package'] = chatgpt_pkg
                signal['phase2_zone_low_rsi'] = tracker.zone_low_rsi
                signal['phase2_kalman_velocity'] = tracker.kalman_velocity
                signal['phase2_ramp_confidence'] = ramp_result.confidence if ramp_result else 'NONE'

                # ─── STEP 7: Capital reservation → append signal ───
                # Capital reservation done in wrapper AFTER GPT approval
                signal['capital_reserved'] = False
                signal['reservation_id'] = None
                signals.append(signal)

            except Exception as e:
                logger.error(f"Error checking {monitor.symbol}: {e}")

        # v5.7.1: Cycle summary as ASCII table — easy-to-read in CMD and log files
        total_stocks = len(self.monitors)
        passed_gates = total_stocks - len(self.last_cycle_blocked)

        # ── Collect rows first so we can size columns dynamically ──
        _rows = []  # list of (sym, state, k_rsi_str, requirement, score_line)
        if self.last_cycle_blocked:
            for blocked in self.last_cycle_blocked:
                sym = blocked['symbol']
                score_bd = blocked.get('score_breakdown')
                if score_bd:
                    scores = []
                    for fname, fdata in score_bd.items():
                        short_name = fname[:3].upper()
                        scores.append(f"{short_name}={fdata['score']}/{fdata['max']}")
                    _rows.append((sym, 'SCORED', '-', blocked['reason'], " | ".join(scores)))
                else:
                    tracker_state = blocked.get('tracker_state', '?')
                    k_rsi = blocked.get('kalman_rsi', 0)
                    k_rsi_str = f"{k_rsi:.1f}" if k_rsi else "?"
                    sym_tracker = self.rsi_trackers.get(sym)
                    if sym_tracker:
                        zone_low = sym_tracker.adaptive_zone_low
                        zone_high = sym_tracker.adaptive_zone_high
                        zone_ctr = sym_tracker.adaptive_center
                    else:
                        zone_low, zone_high, zone_ctr = 40.0, 60.0, 50.0
                    if tracker_state == 'WATCHING':
                        need = f"K-RSI needs [{zone_low:.0f}-{zone_high:.0f}] (ctr={zone_ctr:.0f})"
                    elif tracker_state == 'ZONE_ENTERED':
                        need = f"In zone -- needs K-RSI > {zone_ctr:.0f} with +vel"
                    elif tracker_state == 'BLOCKED':
                        need = "BLOCKED (capitulation/exhaustion)"
                    else:
                        need = f"state={tracker_state}"
                    _rows.append((sym, tracker_state, k_rsi_str, need, ''))

        # ── Column widths ──
        C1 = max(10, max((len(r[0]) for r in _rows), default=0) + 2)   # Stock
        C2 = max(14, max((len(r[1]) for r in _rows), default=0) + 2)   # State
        C3 = 7                                                           # K-RSI
        C4 = max(38, max((len(r[3]) for r in _rows), default=0) + 2)   # Requirement

        _sep   = f"+{'-'*C1}+{'-'*C2}+{'-'*C3}+{'-'*C4}+"
        _hdr   = f"| {'Stock':<{C1-1}}| {'State':<{C2-1}}| {'K-RSI':<{C3-1}}| {'Requirement':<{C4-1}}|"
        _title = (f"  Phase 2 Cycle Summary  |  {total_stocks} stocks  |  "
                  f"{passed_gates} passed gates  |  {len(signals)} signals")

        logger.info(_title)
        logger.info(_sep)
        logger.info(_hdr)
        logger.info(_sep)
        if _rows:
            for sym, state, k_rsi_str, need, score_line in _rows:
                _state_display = f"{state} (*)" if state == 'ZONE_ENTERED' else state
                logger.info(f"| {sym:<{C1-1}}| {_state_display:<{C2-1}}| {k_rsi_str:>{C3-1}}| {need:<{C4-1}}|")
                if score_line:
                    logger.info(f"| {'  Scores:':<{C1-1}}| {'':<{C2-1}}| {'':<{C3-1}}| {score_line:<{C4-1}}|")
        else:
            _no_data = "All stocks passed gates"
            logger.info(f"| {_no_data:<{C1+C2+C3+C4+2}} |")
        logger.info(_sep)

        return signals
    
    def _check_nifty_filter(self) -> bool:
        """
        Check NIFTY 50 market filter.
        
        v4.5.5: State-aware notifications
          - First block  → log + Telegram once
          - Ongoing block → silent
          - Recovery      → log + Telegram once
        """
        try:
            nifty_data = self.kite.quote(["NSE:NIFTY 50"])
            nifty_quote = nifty_data["NSE:NIFTY 50"]
            
            current_price = nifty_quote['last_price']
            prev_close = nifty_quote['ohlc']['close']
            change_pct = ((current_price - prev_close) / prev_close) * 100
            
            # v5.2.1: Read from config instead of hardcoded -1.0%
            nifty_threshold = getattr(self.config, 'NIFTY_THRESHOLD', -1.0)
            passed = change_pct >= nifty_threshold
            
            # ── State transition: MONITORING → BLOCKED (first block) ──
            if not passed and not self._nifty_filter_blocked:
                self._nifty_filter_blocked = True
                logger.warning(
                    f"❌ NIFTY FILTER BLOCKED | NIFTY: {current_price:,.1f} "
                    f"({change_pct:+.2f}%) | Threshold: {nifty_threshold}%"
                )
                logger.warning("   All stock entry checks suspended until NIFTY recovers")
                if self.telegram:
                    self.telegram.send_message(
                        f"❌ NIFTY FILTER ACTIVE\n\n"
                        f"NIFTY 50: ₹{current_price:,.1f} ({change_pct:+.2f}%)\n"
                        f"Threshold: {nifty_threshold}%\n\n"
                        f"⛔ All entry checks suspended\n"
                        f"Resumes when NIFTY ≥ {nifty_threshold}%"
                    )
            
            # ── State transition: BLOCKED → MONITORING (recovered) ──
            elif passed and self._nifty_filter_blocked:
                self._nifty_filter_blocked = False
                logger.info(
                    f"✅ NIFTY FILTER CLEARED | NIFTY: {current_price:,.1f} "
                    f"({change_pct:+.2f}%) | Monitoring resumed"
                )
                if self.telegram:
                    self.telegram.send_message(
                        f"✅ NIFTY FILTER CLEARED\n\n"
                        f"NIFTY 50: ₹{current_price:,.1f} ({change_pct:+.2f}%)\n\n"
                        f"📊 Entry checks resumed"
                    )
            
            return passed
            
        except Exception as e:
            logger.error(f"NIFTY filter error: {e}")
            return True
    
    # v5.3.0: _check_rsi_cross() REMOVED — was rubber stamp (84/84 passed, 0 blocked)
    # RSI upper bound (>=70) moved to check_entry_signals() PS-5
    # RSI overbought zone (>62) moved to check_entry_signals() RAMP placeholder
    # TODO: Full RAMP detector (Kalman+MA+RisingLows) replaces this
    
    def _generate_entry_signal(self, monitor: StockMonitor) -> Optional[dict]:
        """Generate entry signal with Capital Manager entry_size."""
        try:
            ltp = monitor.current_ltp
            rsi = monitor.current_rsi or 50
            
            # Calculate targets
            target_price = ltp * 1.03
            stop_price = ltp * 0.98
            target_pct = 3.0
            stop_pct = 2.0
            position_multiplier = 1.0
            volatility_regime = 'MEDIUM'
            
            # AI analysis
            if self.ai_intelligence:
                try:
                    from_date = (datetime.now() - timedelta(days=100)).date()
                    to_date = datetime.now().date()
                    
                    historical_data = self.kite.historical_data(
                        instrument_token=monitor.instrument_token,
                        from_date=from_date,
                        to_date=to_date,
                        interval='day'
                    )
                    
                    if historical_data and len(historical_data) >= 30:
                        df = pd.DataFrame(historical_data)
                        ai_results = self.ai_intelligence.analyze(
                            ohlc_data=df,
                            current_price=ltp,
                            rsi_history=monitor.rsi_values_only if monitor.rsi_values_only else [rsi]
                        )
                        
                        target_price = ai_results['atr']['target_price']
                        stop_price = ai_results['atr']['stop_price']
                        target_pct = ai_results['atr']['target_pct']
                        stop_pct = ai_results['atr']['stop_pct']
                        position_multiplier = ai_results['volatility']['position_size_multiplier']
                        volatility_regime = ai_results['volatility']['regime']
                except Exception as e:
                    logger.error(f"AI analysis failed: {e}")
            
            # Calculate entry size for Capital Manager
            base_capital = getattr(self.config, 'BASE_CAPITAL_PER_TRADE', 10000)
            quantity = max(1, int(base_capital / ltp))
            quantity = max(1, int(quantity * position_multiplier))
            
            product_type = getattr(self.config, 'PRODUCT_TYPE', 'CNC')
            if product_type == 'MIS':
                entry_size = ltp * quantity * 0.20
            else:
                entry_size = ltp * quantity
            
            actual_investment = ltp * quantity
            
            # FinBERT sentiment
            sentiment_result = None
            if self.finbert and self.news_scraper:
                try:
                    news_headlines = self.news_scraper.get_stock_news(symbol=monitor.symbol, max_results=5)
                    if news_headlines:
                        monitor.recent_news = news_headlines
                        sentiment_result = self.finbert.analyze_sentiment(
                            text_list=monitor.recent_news,
                            symbol=monitor.symbol,
                            use_temporal_decay=getattr(self.config, 'FINBERT_USE_TEMPORAL_DECAY', False)
                        )
                        
                        # Block on strong bearish
                        if (sentiment_result['label'] == 'BEARISH' and 
                            sentiment_result['confidence'] > getattr(self.config, 'FINBERT_CONFIDENCE_THRESHOLD', 70) and
                            len(news_headlines) >= 2 and
                            sentiment_result['sentiment_score'] < -0.3):
                            logger.warning(f"⛔ Blocking {monitor.symbol}: Strong BEARISH sentiment!")
                            # v4.5.5: Track blocked signal for Telegram
                            self.last_cycle_blocked.append({
                                'symbol': monitor.symbol,
                                'reason': 'FinBERT BEARISH',
                                'rsi': rsi,
                                'ltp': ltp,
                                'details': f"Score: {sentiment_result['sentiment_score']:.2f}, "
                                          f"Conf: {sentiment_result['confidence']}%, "
                                          f"Headlines: {len(news_headlines)}",
                                'rsi_passed': True,
                                'momentum_passed': True,
                                'sentiment_passed': False
                            })
                            return None
                except Exception as e:
                    logger.error(f"FinBERT failed: {e}")
            
            signal = {
                'symbol': monitor.symbol,
                'instrument_token': monitor.instrument_token,
                'entry_price': ltp,
                'target_price': target_price,
                'stop_price': stop_price,
                'target_pct': target_pct,
                'stop_pct': stop_pct,
                'position_size_multiplier': position_multiplier,
                'volatility_regime': volatility_regime,
                'entry_size': entry_size,
                'quantity': quantity,
                'actual_investment': actual_investment,
                'product_type': product_type,
                'rsi': rsi,
                'rsi_threshold': getattr(monitor, 'adaptive_rsi_threshold', 35),
                'entry_signal_type': getattr(monitor, 'entry_signal_type', 'CONFIRMATION'),
                'timestamp': datetime.now().isoformat(),
                'confidence': getattr(monitor, 'confidence_score', 80),
                'approved': True,
                'finbert_sentiment': sentiment_result,
                'capital_reserved': False,
                'reservation_id': None,
                # v3.3.0: New fields for ChatGPT decision context
                'adx_value': getattr(monitor, 'adx_value', None),
                'rsi_history': monitor.rsi_values_only if hasattr(monitor, 'rsi_values_only') else None,
                'volume_spike_at_reversal': getattr(monitor, 'volume_spike_at_reversal', None),
                'v_recovery_data': getattr(monitor, 'v_recovery_data', None),
                'vwap': getattr(monitor, 'vwap', None),
                'finbert_contribution': self._get_finbert_contribution(sentiment_result),
                # v5.3.0: Ramp detector results for ChatGPT context
                'ramp_detected': getattr(getattr(monitor, 'ramp_result', None), 'is_ramp', False),
                'ramp_confidence': getattr(getattr(monitor, 'ramp_result', None), 'confidence', 'NONE'),
                'ramp_kalman_velocity': getattr(getattr(monitor, 'ramp_result', None), 'kalman_velocity', 0),
                'ramp_rising_lows': getattr(getattr(monitor, 'ramp_result', None), 'rising_lows_count', 0),
                # Phase E: MAP V-Recovery signal for entry confirmation
                'map_v_recovery': getattr(monitor, 'map_v_recovery', False),
                'map_v_recovery_confidence': getattr(monitor, 'map_v_recovery_confidence', 0.0),
                # v5.3.3: ATR for Phase 3/4 Smart TCAS stop calculation
                'atr': getattr(monitor, 'atr', 0) or 0,
                # v5.5: Price level data for Phase 3 stop/target anchoring
                'prev_day_high': getattr(monitor, 'prev_day_high', 0.0),
                'prev_day_low': getattr(monitor, 'prev_day_low', 0.0),
                'prev_week_high': getattr(monitor, 'prev_week_high', 0.0),
                'prev_week_low': getattr(monitor, 'prev_week_low', 0.0),
                'nearest_round_below': getattr(monitor, 'nearest_round_below', 0.0),
                'nearest_round_above': getattr(monitor, 'nearest_round_above', 0.0),
                'vwap': getattr(monitor, 'vwap', 0.0),
                'today_high': getattr(monitor, 'current_high', 0.0),
                'today_low': getattr(monitor, 'current_low', 0.0),
                'today_open': getattr(monitor, 'current_open', 0.0),
            }
            
            logger.info(f"✅ SIGNAL: {monitor.symbol} | ₹{ltp:.2f} | Qty: {quantity} | Size: ₹{entry_size:,.0f}")
            
            return signal
            
        except Exception as e:
            logger.error(f"Failed to generate signal for {monitor.symbol}: {e}")
            return None
    
    def save_entry_signals(self, signals: List[dict]):
        """Save entry signals to file."""
        if not signals:
            return
        
        filepath = self.config.PHASE2_ENTRY_SIGNALS.format(date=datetime.now().strftime('%Y%m%d'))
        data = {
            'generated_at': datetime.now().isoformat(),
            'count': len(signals),
            'signals': signals
        }
        atomic_write(filepath, data)
        logger.info(f"Saved {len(signals)} entry signals")
    
    def _get_finbert_contribution(self, sentiment_result: dict) -> int:
        """
        Calculate FinBERT's point contribution for entry scoring.
        
        v3.3.0: Helper for signal dict construction.
        Maps FinBERT label to point contribution for ChatGPT context.
        
        Returns:
            int: Points contribution (+15 bullish, +5 neutral, -20 bearish, 0 if N/A)
        """
        if not sentiment_result:
            return 0
        
        contribution = sentiment_result.get('entry_score_contribution', None)
        if contribution is not None:
            return int(contribution)
        
        label = sentiment_result.get('label', 'NEUTRAL')
        if label == 'BULLISH':
            return getattr(self.config, 'FINBERT_BULLISH_BONUS', 15)
        elif label == 'BEARISH':
            return getattr(self.config, 'FINBERT_BEARISH_PENALTY', -20)
        else:
            return getattr(self.config, 'FINBERT_NEUTRAL_BONUS', 5)
    
    def save_monitoring_state(self):
        """Save current monitoring state."""
        filepath = self.config.PHASE2_MONITORING_LOG.format(date=datetime.now().strftime('%Y%m%d'))
        # v5.3.1: entries_taken sourced from CapitalManager when available
        active_entries = self.entries_taken
        if self.capital_manager:
            try:
                active_entries = self.capital_manager.get_active_position_count() if hasattr(self.capital_manager, 'get_active_position_count') else self.entries_taken
            except Exception:
                pass
        data = {
            'updated_at': datetime.now().isoformat(),
            'entries_taken': active_entries,
            'max_entries': self.max_entries,
            'monitors': [m.to_dict() for m in self.monitors]
        }
        atomic_write(filepath, data)
    
    def run_monitoring(self) -> List[dict]:
        """Main monitoring loop."""
        logger.info("=" * 80)
        logger.info("PHASE 2: ENTRY TIMING v4.5.0 - MONITORING START")
        logger.info("=" * 80)
        
        # Wait for market open
        while datetime.now() < datetime.now().replace(hour=9, minute=15, second=0, microsecond=0):
            wait_seconds = (datetime.now().replace(hour=9, minute=15, second=0) - datetime.now()).total_seconds()
            logger.info(f"Waiting for market open... ({int(wait_seconds/60)} min)")
            time.sleep(60)
        
        logger.info("🚀 Market is OPEN - Starting monitoring...")
        
        # Load stocks
        stocks = self.load_active_stocks()
        if not stocks:
            return []
        
        # Sync with Capital Manager
        if self.capital_manager:
            logger.info("💰 Syncing with Capital Manager...")
            self.capital_manager.sync_with_broker()
        
        # Check market regime
        self.market_regime = self.tech.check_market_regime(self.kite, self.config.NIFTY_THRESHOLD)
        if not self.market_regime['allow_entries']:
            logger.warning(f"⛔ MARKET BLOCKED - NIFTY {self.market_regime['nifty_change']:.2f}%")
            return []
        
        # Initialize monitors
        stocks_prioritized = self.prioritize_stocks(stocks, [])
        self.initialize_monitors(stocks_prioritized)
        
        logger.info(f"Monitoring {len(self.monitors)} stocks")
        
        all_signals = []
        update_count = 0
        
        while True:
            update_count += 1
            now = datetime.now().time()
            cutoff = datetime.strptime(self.config.PHASE2_ABSOLUTE_CUTOFF, "%H:%M").time()
            
            if now > cutoff:
                logger.info("Time window closed")
                break
            
            # v5.3.3: Simple capacity check — is there any usable capital left?
            if self.capital_manager:
                available = self.capital_manager.get_available()
                buffer = getattr(self.capital_manager, 'min_capital_buffer', 1000)
                if available <= buffer:
                    logger.info(f"No usable capital remaining (₹{available:,.0f} ≤ ₹{buffer:,.0f} buffer)")
                    break
            elif not self.capital_manager and self.entries_taken >= self.max_entries:
                logger.info("Max entries reached (fallback counter)")
                break
            
            logger.info(f"Update #{update_count} - {datetime.now().strftime('%H:%M:%S')}")
            self.update_all_monitors()
            
            signals = self.check_entry_signals()
            
            if signals:
                all_signals.extend(signals)
                
                # Execute signals if Phase 3 enabled
                if self.phase3_manager:
                    for signal in signals:
                        try:
                            position = self.phase3_manager.execute_signal_realtime(signal)
                            
                            if position:
                                # Deploy capital after successful execution
                                if self.capital_manager and signal.get('capital_reserved'):
                                    self.capital_manager.deploy(
                                        symbol=signal['symbol'],
                                        amount=signal.get('entry_size', 0),
                                        entry_price=signal.get('entry_price', 0),
                                        quantity=signal.get('quantity', 0)
                                    )
                            else:
                                # Release reservation on failure
                                if self.capital_manager and signal.get('capital_reserved'):
                                    self.capital_manager.release_reservation(
                                        symbol=signal['symbol'],
                                        reservation_id=signal.get('reservation_id')
                                    )
                        except Exception as e:
                            logger.error(f"Execution failed for {signal.get('symbol')}: {e}")
            
            self.save_monitoring_state()
            
            logger.info(f"Next update in {self.config.PHASE2_UPDATE_INTERVAL // 60} minutes...")
            time.sleep(self.config.PHASE2_UPDATE_INTERVAL)
        
        self.save_entry_signals(all_signals)
        
        logger.info("=" * 80)
        logger.info(f"PHASE 2 COMPLETE - {len(all_signals)} signal(s) generated")
        logger.info("=" * 80)
        
        return all_signals


# ============================================================================
# STANDALONE EXECUTION
# ============================================================================

if __name__ == "__main__":
    print("Phase 2 Entry Timing Module v4.5.0")
    print("=" * 50)
    print("This module requires capital_manager parameter for v4.5.0 features.")
    print("Import and use from orchestrator.")
