"""
PHASE 4: AUTONOMOUS PORTFOLIO MANAGER v4.8.2 (GTT Cancel-Before-Place Fix)
═══════════════════════════════════════════════════════════════════════════════

✅ v4.8.2 (2026-02-07): GTT CANCEL-BEFORE-PLACE FIX
   - Fixed _check_existing_gtt_for_symbol: was using gtt['tradingsymbol'] (wrong path)
     Now uses gtt['condition']['tradingsymbol'] (matching Zerodha API response) with fallback
   - Changed GTT strategy from "reuse existing" to "cancel-then-place-fresh"
   - Every restart now: cancel old GTTs → place exactly 1 stop + 1 target
   - Prevents duplicate GTTs accumulating across restarts
   - Applied to all 3 callers: _add_manual_position, add_phase5_position, on_position_opened
   - Returns 'all_ids' list for complete cleanup

✅ v4.8.1 (2026-02-05): CRITICAL GTT FIX
   - Added 'product' field to ALL GTT orders (place, modify_stop, modify_target)
   - Prevents Zerodha API rejection "product type mismatch"
   - Product type now stored in position and used in all GTT calls
   - Fixes: MIS positions can now modify GTT, CNC positions work correctly

🛫 AVIATION-INSPIRED POSITION MANAGEMENT
   - TCAS: Traffic Collision Avoidance System (Stop-Loss Protection)
   - ILS: Instrument Landing System (Profit Target Approach)
   - Go-Around: Health-Based Exit Gates
   - Kalman Filter: Price Velocity & Prediction

🏎️ v4.14.0: PRIORITY TIER MONITORING
   - TIER_1 (MIS/Phase 5): Fast 200ms check — target/stop/timeout only
   - TIER_2 (CNC/Swing): Full pipeline — Kalman/TCAS/ILS/ChatGPT
   - Tier 1 checked FIRST every cycle, no exceptions
   - exit_mode: FAST_TECHNICAL (skip ChatGPT/TruthMatrix for scalps)
   - Radar candidates logged for post-trade analysis
   - has_tier1_positions() for orchestrator sleep time awareness

🔄 v4.13.0: DIRECTION + MIS SUPPORT
   - SHORT Position Handling: Inverted TCAS/ILS logic for bearish trades
   - MIS Mandatory Exit: Auto-exit before mandatory_exit_time
   - Direction-aware P&L: Correct calculations for LONG/SHORT
   - Direction-aware GTT: SELL for LONG exit, BUY for SHORT exit
   - Phase 5 Integration: Accepts positions from Phase 5 Gap Strategy
   - Source Tracking: position['source'] = PHASE5_GAP, MANUAL, PHASE3

✈️ v4.12.0: MULTI-TIMEFRAME FLIGHT PLAN
   - FlightPlanGenerator: 5 timeframes × 8 indicators
   - Truth Confluence Score, Decision Matrix

🔮 v4.11.0: TRUTH PREDICTOR SYSTEM
   - BollingerBandAnalyzer, FibonacciLevelCalculator, VWAPAnalyzer
   - TruthPredictor: Multi-indicator truth matrix

🔧 Previous Versions:
   - v4.8.0: Predictive Stop, Kalman predictions
   - v1.1.1: GTT reconciliation on restart

🤖 FULLY AUTONOMOUS - LONG + SHORT, CNC + MIS

Author: Trading System v4.14.0
Date: 2026-02-05
"""

import os
import sys
import json
import time
import logging
import traceback
from datetime import datetime, timedelta, time as dt_time
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field, asdict
from enum import Enum, auto
import numpy as np

# v4.8.0: Enable Predictive Stop (WAS DEAD CODE - NOW ACTIVE!)
from predictive_stop import PredictiveStop, PredictiveExitSignal, ExitReason as PredictiveExitReason

# v4.8.1: C1 - Decision History Tracking
from decision_history import DecisionHistoryTracker

# Ensemble Prediction Engine (advisory only — does not override exits)
try:
    from prediction_engine import EnsemblePrediction, PredictionResult
    ENSEMBLE_AVAILABLE = True
except ImportError:
    ENSEMBLE_AVAILABLE = False

logger = logging.getLogger('Phase4_PortfolioManager')
if not ENSEMBLE_AVAILABLE:
    logger.info("prediction_engine not available — ensemble predictions disabled")


# ═══════════════════════════════════════════════════════════════════════════════
# ENUMS & DATA CLASSES
# ═══════════════════════════════════════════════════════════════════════════════

class MarketRegime(Enum):
    """Market regime classification"""
    SQUEEZE = "SQUEEZE"           # Low volatility, compression
    STRONG_TREND = "STRONG_TREND" # ADX > 30, clear direction
    VOLATILE_TREND = "VOLATILE_TREND"  # Trending but choppy
    CHOPPY_VOLATILE = "CHOPPY_VOLATILE"  # High volatility, no direction
    RANGING_QUIET = "RANGING_QUIET"  # Low volatility, sideways
    CRISIS = "CRISIS"             # Extreme volatility (VIX > 25)
    NORMAL = "NORMAL"             # Default


class TCASAlert(Enum):
    """TCAS alert levels"""
    CLEAR = "CLEAR"       # > 2.0 ATR from stop
    TA = "TA"             # Traffic Advisory: 1.5-2.0 ATR
    RA = "RA"             # Resolution Advisory: 0.75-1.5 ATR
    ALIM = "ALIM"         # ALIM Breach: < 0.75 ATR - IMMEDIATE EXIT


class LandingPhase(Enum):
    """ILS landing phases"""
    CRUISE = "CRUISE"           # < 25% to target
    OUTER_MARKER = "OUTER_MARKER"  # 25-50% to target
    MIDDLE_MARKER = "MIDDLE_MARKER"  # 50-75% to target
    INNER_MARKER = "INNER_MARKER"  # 75-90% to target
    DECISION_HEIGHT = "DECISION_HEIGHT"  # 90-95% to target
    LANDING = "LANDING"         # > 95% to target


class GateType(Enum):
    """Health check gates"""
    GATE_1 = "GATE_1"  # After 15 min: Score >= 60
    GATE_2 = "GATE_2"  # After 30 min: Score >= 50
    GATE_3 = "GATE_3"  # After 60 min: Score >= 40
    GATE_4 = "GATE_4"  # After 90 min: Score >= 30


class ExitReason(Enum):
    """Exit reasons for tracking"""
    TARGET_HIT = "TARGET_HIT"
    STOP_LOSS = "STOP_LOSS"
    TRAILING_STOP = "TRAILING_STOP"
    TCAS_ALIM = "TCAS_ALIM"
    TCAS_RA_EXIT = "TCAS_RA_EXIT"
    HEALTH_CRITICAL = "HEALTH_CRITICAL"
    GO_AROUND = "GO_AROUND"
    CHATGPT_EXIT = "CHATGPT_EXIT"
    TIME_EXIT = "TIME_EXIT"
    MIS_CUTOFF = "MIS_CUTOFF"
    MARKET_CLOSE = "MARKET_CLOSE"
    GTT_TRIGGERED = "GTT_TRIGGERED"
    MANUAL = "MANUAL"


class ChatGPTDecision(Enum):
    """ChatGPT decision types"""
    HOLD = "HOLD"
    TIGHTEN_STOP = "TIGHTEN_STOP"
    WIDEN_STOP = "WIDEN_STOP"
    PARTIAL_25 = "PARTIAL_25"
    PARTIAL_50 = "PARTIAL_50"
    EXIT = "EXIT"
    EXTEND_TARGET = "EXTEND_TARGET"
    LAND_TODAY = "LAND_TODAY"
    HOLD_FOR_TOMORROW = "HOLD_FOR_TOMORROW"


@dataclass
class TCASStatus:
    """TCAS system status"""
    alert_level: TCASAlert = TCASAlert.CLEAR
    distance_to_stop_atr: float = 999.0
    tau_estimate: float = 999.0  # Time to collision estimate
    recommended_action: str = "MONITOR"
    
    def to_dict(self) -> Dict:
        return {
            'alert_level': self.alert_level.value,
            'distance_to_stop_atr': round(self.distance_to_stop_atr, 2),
            'tau_estimate': round(self.tau_estimate, 1),
            'recommended_action': self.recommended_action
        }


@dataclass
class ILSStatus:
    """ILS landing system status"""
    landing_phase: LandingPhase = LandingPhase.CRUISE
    progress_pct: float = 0.0
    glideslope_deviation: float = 0.0  # Positive = above glideslope
    trailing_stop: float = 0.0
    trailing_active: bool = False
    
    def to_dict(self) -> Dict:
        return {
            'landing_phase': self.landing_phase.value,
            'progress_pct': round(self.progress_pct, 1),
            'glideslope_deviation': round(self.glideslope_deviation, 2),
            'trailing_stop': round(self.trailing_stop, 2),
            'trailing_active': self.trailing_active
        }


@dataclass
class HealthScore:
    """Position health score"""
    total_score: float = 100.0
    interpretation: str = "HEALTHY"
    component_scores: Dict = field(default_factory=dict)
    gate_status: Dict = field(default_factory=dict)
    
    def to_dict(self) -> Dict:
        return {
            'total_score': round(self.total_score, 1),
            'interpretation': self.interpretation,
            'component_scores': self.component_scores,
            'gate_status': self.gate_status
        }


@dataclass
class KalmanState:
    """Kalman filter state — extended with MAP fields for 6-state filter"""
    # Base fields (backward compatible)
    price: float = 0.0
    velocity: float = 0.0
    acceleration: float = 0.0
    prediction_15min: float = 0.0
    uncertainty: float = 1.0
    interpretation: str = "UNKNOWN"

    # MAP extended fields (Phase B)
    rsi_filtered: float = 50.0
    rsi_momentum: float = 0.0
    volume_momentum: float = 0.0
    inverse_v_top: bool = False
    crash_accelerating: bool = False
    exit_signal_confidence: float = 0.0
    v_recovery_bottom: bool = False
    v_recovery_confidence: float = 0.0
    regime: str = "UNKNOWN"
    prediction_1hour: float = 0.0
    prediction_confidence: float = 0.0
    rsi_price_divergence: bool = False
    volume_price_divergence: bool = False

    def to_dict(self) -> Dict:
        return {
            'price': round(self.price, 2),
            'velocity': round(self.velocity, 4),
            'acceleration': round(self.acceleration, 6),
            'prediction_15min': round(self.prediction_15min, 2),
            'uncertainty': round(self.uncertainty, 2),
            'interpretation': self.interpretation,
            'rsi_filtered': round(self.rsi_filtered, 2),
            'rsi_momentum': round(self.rsi_momentum, 4),
            'volume_momentum': round(self.volume_momentum, 4),
            'inverse_v_top': self.inverse_v_top,
            'crash_accelerating': self.crash_accelerating,
            'exit_signal_confidence': round(self.exit_signal_confidence, 3),
            'v_recovery_bottom': self.v_recovery_bottom,
            'v_recovery_confidence': round(self.v_recovery_confidence, 3),
            'regime': self.regime,
            'prediction_1hour': round(self.prediction_1hour, 2),
            'prediction_confidence': round(self.prediction_confidence, 1),
            'rsi_price_divergence': self.rsi_price_divergence,
            'volume_price_divergence': self.volume_price_divergence,
        }


# ═══════════════════════════════════════════════════════════════════════════════
# v4.11.0 TRUTH PREDICTOR DATA CLASSES
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class BollingerBandResult:
    """Bollinger Band analysis result"""
    upper_band: float = 0.0
    middle_band: float = 0.0
    lower_band: float = 0.0
    bandwidth_pct: float = 0.0
    squeeze_active: bool = False
    price_position: float = 0.5  # 0=lower, 1=upper
    mean_reversion_signal: str = 'NEUTRAL'  # BUY_OVERSOLD, SELL_OVERBOUGHT, NEUTRAL
    
    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class FibonacciResult:
    """Fibonacci level analysis result"""
    swing_high: float = 0.0
    swing_low: float = 0.0
    swing_range: float = 0.0
    retracement_levels: Dict[str, float] = field(default_factory=dict)
    extension_levels: Dict[str, float] = field(default_factory=dict)
    current_retracement_pct: float = 0.0
    nearest_level: str = ''
    
    def to_dict(self) -> Dict:
        return {
            'swing_high': self.swing_high,
            'swing_low': self.swing_low,
            'swing_range': self.swing_range,
            'retracement_levels': self.retracement_levels,
            'extension_levels': self.extension_levels,
            'current_retracement_pct': self.current_retracement_pct,
            'nearest_level': self.nearest_level
        }


@dataclass
class VWAPResult:
    """VWAP analysis result"""
    vwap: float = 0.0
    price_vs_vwap: str = 'AT'  # ABOVE, BELOW, AT
    deviation_pct: float = 0.0
    vwap_1sigma_upper: float = 0.0
    vwap_1sigma_lower: float = 0.0
    vwap_2sigma_upper: float = 0.0
    vwap_2sigma_lower: float = 0.0
    institutional_flow: str = 'NEUTRAL'  # BULLISH, BEARISH, NEUTRAL
    
    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class TruthMatrix:
    """Complete truth prediction matrix"""
    symbol: str = ''
    timestamp: str = ''
    entry_price: float = 0.0
    predictions: Dict[str, Dict] = field(default_factory=dict)
    targets: Dict[str, float] = field(default_factory=dict)
    supports: Dict[str, float] = field(default_factory=dict)
    indicators: Dict[str, Dict] = field(default_factory=dict)
    overall_confidence: float = 0.0
    direction: str = 'NEUTRAL'
    recommended_target: float = 0.0
    recommended_stop: float = 0.0
    
    def to_dict(self) -> Dict:
        return {
            'symbol': self.symbol,
            'timestamp': self.timestamp,
            'entry_price': self.entry_price,
            'predictions': self.predictions,
            'targets': self.targets,
            'supports': self.supports,
            'indicators': self.indicators,
            'overall_confidence': self.overall_confidence,
            'direction': self.direction,
            'recommended_target': self.recommended_target,
            'recommended_stop': self.recommended_stop
        }


# ═══════════════════════════════════════════════════════════════════════════════
# v4.11.0 TRUTH PREDICTOR ANALYZER CLASSES
# ═══════════════════════════════════════════════════════════════════════════════

class BollingerBandAnalyzer:
    """
    Bollinger Band analyzer for squeeze detection and mean reversion signals.
    
    From project spec:
    - Middle Band = SMA(20)
    - Upper/Lower = Middle ± 2σ
    - Squeeze = BandWidth < 4%
    """
    
    def __init__(self, period: int = 20, std_dev: float = 2.0, squeeze_threshold: float = 4.0):
        self.period = period
        self.std_dev = std_dev
        self.squeeze_threshold = squeeze_threshold
    
    def analyze(self, prices: List[float], current_price: float = None) -> BollingerBandResult:
        """Calculate Bollinger Bands and analyze current position."""
        if len(prices) < self.period:
            return BollingerBandResult()
        
        prices_arr = np.array(prices[-self.period:])
        middle_band = float(np.mean(prices_arr))
        std = float(np.std(prices_arr, ddof=1))
        
        upper_band = middle_band + (self.std_dev * std)
        lower_band = middle_band - (self.std_dev * std)
        bandwidth_pct = ((upper_band - lower_band) / middle_band) * 100 if middle_band > 0 else 0
        squeeze_active = bandwidth_pct < self.squeeze_threshold
        
        price = current_price if current_price else prices[-1]
        band_range = upper_band - lower_band
        price_position = (price - lower_band) / band_range if band_range > 0 else 0.5
        price_position = max(0.0, min(1.0, price_position))
        
        if price_position < 0.15:
            mean_reversion_signal = 'BUY_OVERSOLD'
        elif price_position > 0.85:
            mean_reversion_signal = 'SELL_OVERBOUGHT'
        else:
            mean_reversion_signal = 'NEUTRAL'
        
        return BollingerBandResult(
            upper_band=round(upper_band, 2),
            middle_band=round(middle_band, 2),
            lower_band=round(lower_band, 2),
            bandwidth_pct=round(bandwidth_pct, 2),
            squeeze_active=squeeze_active,
            price_position=round(price_position, 2),
            mean_reversion_signal=mean_reversion_signal
        )


class FibonacciLevelCalculator:
    """
    Fibonacci retracement and extension level calculator.
    
    Key levels: 23.6%, 38.2%, 50%, 61.8% (golden ratio), 78.6%
    """
    
    RETRACEMENT_LEVELS = {
        '0.0': 0.0, '23.6': 0.236, '38.2': 0.382,
        '50.0': 0.500, '61.8': 0.618, '78.6': 0.786, '100.0': 1.0
    }
    EXTENSION_LEVELS = {'127.2': 1.272, '161.8': 1.618, '200.0': 2.0}
    
    def __init__(self, lookback_periods: int = 20):
        self.lookback_periods = lookback_periods
    
    def calculate(self, highs: List[float], lows: List[float], current_price: float) -> FibonacciResult:
        """Calculate Fibonacci levels from swing high/low."""
        if len(highs) < 2 or len(lows) < 2:
            return FibonacciResult()
        
        lookback_highs = highs[-self.lookback_periods:] if len(highs) >= self.lookback_periods else highs
        lookback_lows = lows[-self.lookback_periods:] if len(lows) >= self.lookback_periods else lows
        
        swing_high = max(lookback_highs)
        swing_low = min(lookback_lows)
        swing_range = swing_high - swing_low
        
        if swing_range <= 0:
            return FibonacciResult()
        
        retracement_levels = {name: round(swing_high - (swing_range * ratio), 2) 
                             for name, ratio in self.RETRACEMENT_LEVELS.items()}
        extension_levels = {name: round(swing_low + (swing_range * ratio), 2) 
                           for name, ratio in self.EXTENSION_LEVELS.items()}
        
        current_retracement_pct = round(((current_price - swing_low) / swing_range) * 100, 1)
        nearest_level = min(retracement_levels.keys(), 
                           key=lambda k: abs(current_price - retracement_levels[k]))
        
        return FibonacciResult(
            swing_high=round(swing_high, 2),
            swing_low=round(swing_low, 2),
            swing_range=round(swing_range, 2),
            retracement_levels=retracement_levels,
            extension_levels=extension_levels,
            current_retracement_pct=current_retracement_pct,
            nearest_level=nearest_level
        )


class VWAPAnalyzer:
    """
    VWAP (Volume Weighted Average Price) analyzer.
    
    VWAP = Σ(Typical Price × Volume) / Σ(Volume)
    Above VWAP = Bullish institutional flow
    """
    
    def __init__(self, std_periods: int = 20):
        self.std_periods = std_periods
    
    def calculate(self, highs: List[float], lows: List[float], closes: List[float],
                  volumes: List[float], current_price: float) -> VWAPResult:
        """Calculate VWAP and deviation bands."""
        if len(highs) < 2 or len(volumes) < 2:
            return VWAPResult()
        
        min_len = min(len(highs), len(lows), len(closes), len(volumes))
        highs, lows, closes, volumes = highs[-min_len:], lows[-min_len:], closes[-min_len:], volumes[-min_len:]
        
        typical_prices = [(h + l + c) / 3 for h, l, c in zip(highs, lows, closes)]
        total_tp_volume = sum(tp * v for tp, v in zip(typical_prices, volumes))
        total_volume = sum(volumes)
        
        if total_volume <= 0:
            return VWAPResult()
        
        vwap = total_tp_volume / total_volume
        squared_diffs = [(tp - vwap) ** 2 * v for tp, v in zip(typical_prices, volumes)]
        std_dev = (sum(squared_diffs) / total_volume) ** 0.5
        
        if current_price > vwap * 1.001:
            price_vs_vwap, institutional_flow = 'ABOVE', 'BULLISH'
        elif current_price < vwap * 0.999:
            price_vs_vwap, institutional_flow = 'BELOW', 'BEARISH'
        else:
            price_vs_vwap, institutional_flow = 'AT', 'NEUTRAL'
        
        deviation_pct = ((current_price - vwap) / vwap) * 100 if vwap > 0 else 0
        
        return VWAPResult(
            vwap=round(vwap, 2),
            price_vs_vwap=price_vs_vwap,
            deviation_pct=round(deviation_pct, 2),
            vwap_1sigma_upper=round(vwap + std_dev, 2),
            vwap_1sigma_lower=round(vwap - std_dev, 2),
            vwap_2sigma_upper=round(vwap + (2 * std_dev), 2),
            vwap_2sigma_lower=round(vwap - (2 * std_dev), 2),
            institutional_flow=institutional_flow
        )


class TruthPredictor:
    """
    v4.11.0: Multi-indicator truth prediction system.
    
    Combines Kalman, Bollinger, Fibonacci, VWAP for price predictions.
    Integrates with decision_history.py v4.9.0 for accuracy tracking.
    """
    
    def __init__(self, config=None):
        self.config = config
        self.bb_analyzer = BollingerBandAnalyzer(
            period=getattr(config, 'BB_PERIOD', 20),
            std_dev=getattr(config, 'BB_STD_DEV', 2.0),
            squeeze_threshold=getattr(config, 'BB_SQUEEZE_THRESHOLD', 4.0)
        )
        self.fib_calculator = FibonacciLevelCalculator(
            lookback_periods=getattr(config, 'FIB_LOOKBACK', 20)
        )
        self.vwap_analyzer = VWAPAnalyzer(
            std_periods=getattr(config, 'VWAP_STD_PERIODS', 20)
        )
        self.horizons = {'15min': 15, '30min': 30, '60min': 60, 'eod': 390}
        logger.info("✅ TruthPredictor v4.11.0 initialized (Kalman, BB, Fib, VWAP)")
    
    def generate_truth_matrix(self, symbol: str, entry_price: float, 
                              kalman_state: Dict, ohlcv_data: Dict[str, List[float]]) -> TruthMatrix:
        """Generate complete truth prediction matrix at entry."""
        timestamp = datetime.now().isoformat()
        closes = ohlcv_data.get('close', [])
        highs = ohlcv_data.get('high', [])
        lows = ohlcv_data.get('low', [])
        volumes = ohlcv_data.get('volume', [])
        
        bb_result = self.bb_analyzer.analyze(closes, entry_price)
        fib_result = self.fib_calculator.calculate(highs, lows, entry_price)
        vwap_result = self.vwap_analyzer.calculate(highs, lows, closes, volumes, entry_price)
        predictions = self._generate_predictions(kalman_state, entry_price)
        
        targets = {
            'fib_382': fib_result.retracement_levels.get('38.2', 0),
            'fib_500': fib_result.retracement_levels.get('50.0', 0),
            'fib_618': fib_result.retracement_levels.get('61.8', 0),
            'fib_ext_127': fib_result.extension_levels.get('127.2', 0),
            'bb_upper': bb_result.upper_band,
            'vwap_1sigma_upper': vwap_result.vwap_1sigma_upper
        }
        supports = {
            'fib_236': fib_result.retracement_levels.get('23.6', 0),
            'bb_lower': bb_result.lower_band,
            'vwap_1sigma_lower': vwap_result.vwap_1sigma_lower
        }
        indicators = {
            'kalman': {
                'velocity': kalman_state.get('velocity', 0),
                'acceleration': kalman_state.get('acceleration', 0),
                'prediction_15min': kalman_state.get('prediction_15min', entry_price),
                'trend': 'UP' if kalman_state.get('velocity', 0) > 0 else 'DOWN'
            },
            'bollinger': bb_result.to_dict(),
            'fibonacci': fib_result.to_dict(),
            'vwap': vwap_result.to_dict()
        }
        
        confidence, direction = self._calculate_confidence(kalman_state, bb_result, fib_result, vwap_result)
        recommended_target = self._select_target(targets, direction, entry_price)
        recommended_stop = self._select_stop(supports, entry_price)
        
        return TruthMatrix(
            symbol=symbol, timestamp=timestamp, entry_price=entry_price,
            predictions=predictions, targets=targets, supports=supports,
            indicators=indicators, overall_confidence=round(confidence, 2),
            direction=direction, recommended_target=recommended_target,
            recommended_stop=recommended_stop
        )
    
    def _generate_predictions(self, kalman_state: Dict, entry_price: float) -> Dict:
        """Generate Kalman-based price predictions for each horizon."""
        velocity = kalman_state.get('velocity', 0)
        acceleration = kalman_state.get('acceleration', 0)
        predictions = {}
        confidence_map = {'15min': 0.80, '30min': 0.72, '60min': 0.65, 'eod': 0.55}
        
        for horizon_name, minutes in self.horizons.items():
            predicted_price = entry_price + (velocity * minutes) + (0.5 * acceleration * minutes * minutes)

            # v4.13.2: Clamp to realistic bounds (2-5% based on horizon)
            max_move_pct = 0.02 if minutes <= 15 else 0.03 if minutes <= 30 else 0.05
            max_move = entry_price * max_move_pct
            predicted_price = min(predicted_price, entry_price + max_move)
            confidence = confidence_map.get(horizon_name, 0.5)
            if abs(velocity) < 0.01:
                confidence *= 0.8
            predictions[horizon_name] = {
                'value': round(predicted_price, 2),
                'confidence': round(confidence, 2),
                'source': 'kalman'
            }
        return predictions
    
    def _calculate_confidence(self, kalman_state, bb_result, fib_result, vwap_result) -> Tuple[float, str]:
        """Calculate overall confidence and direction from all indicators."""
        bullish_score, bearish_score = 0, 0
        
        velocity = kalman_state.get('velocity', 0)
        if velocity > 0.05: bullish_score += 30
        elif velocity < -0.05: bearish_score += 30
        
        if bb_result.mean_reversion_signal == 'BUY_OVERSOLD': bullish_score += 25
        elif bb_result.mean_reversion_signal == 'SELL_OVERBOUGHT': bearish_score += 25
        
        if vwap_result.institutional_flow == 'BULLISH': bullish_score += 25
        elif vwap_result.institutional_flow == 'BEARISH': bearish_score += 25
        
        retracement_pct = fib_result.current_retracement_pct
        if 50 <= retracement_pct <= 70: bullish_score += 20
        elif retracement_pct < 30: bearish_score += 15
        
        if bullish_score > bearish_score + 15: direction = 'BULLISH'
        elif bearish_score > bullish_score + 15: direction = 'BEARISH'
        else: direction = 'NEUTRAL'
        
        confidence = max(bullish_score, bearish_score) / 100
        return confidence, direction
    
    def _select_target(self, targets: Dict, direction: str, entry_price: float) -> float:
        """Select target based on direction and Fib/BB levels."""
        if direction == 'BULLISH':
            candidates = [v for v in targets.values() if v > entry_price * 1.005]
            if candidates: return min(candidates)
        return round(entry_price * 1.02, 2)
    
    def _select_stop(self, supports: Dict, entry_price: float) -> float:
        """Select stop based on support levels."""
        candidates = [v for v in supports.values() if 0 < v < entry_price * 0.995]
        if candidates: return max(candidates)
        return round(entry_price * 0.98, 2)
    
    def get_checkpoint_data(self, kalman_state: Dict, current_price: float) -> Dict:
        """Get simplified data for hourly checkpoint tracking."""
        velocity = kalman_state.get('velocity', 0)
        return {
            'timestamp': datetime.now().isoformat(),
            'current_price': current_price,
            'kalman_velocity': velocity,
            'kalman_15min_prediction': kalman_state.get('prediction_15min', current_price),
            'trend': 'UP' if velocity > 0 else 'DOWN' if velocity < 0 else 'FLAT'
        }
    
    def calculate_prediction_accuracy(self, predictions: Dict, actual_prices: Dict) -> Dict:
        """Calculate accuracy of predictions vs actual prices at exit."""
        accuracy_results = {}
        entry_price = actual_prices.get('entry', 0)
        
        for horizon, pred_data in predictions.items():
            predicted = pred_data.get('value', 0)
            actual = actual_prices.get(horizon)
            if actual and predicted:
                error_pct = abs((actual - predicted) / predicted) * 100
                direction_correct = (
                    (predicted > entry_price and actual > entry_price) or
                    (predicted < entry_price and actual < entry_price)
                )
                accuracy_results[horizon] = {
                    'predicted': predicted, 'actual': actual,
                    'error_pct': round(error_pct, 2), 'direction_correct': direction_correct
                }
        
        if accuracy_results:
            direction_scores = [1 if r.get('direction_correct') else 0 for r in accuracy_results.values()]
            overall_accuracy = sum(direction_scores) / len(direction_scores) * 100
        else:
            overall_accuracy = 0
        
        return {'horizon_results': accuracy_results, 'overall_direction_accuracy_pct': round(overall_accuracy, 1)}


# ═══════════════════════════════════════════════════════════════════════════════
# v4.12.0 MULTI-TIMEFRAME FLIGHT PLAN SYSTEM
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class TimeframeSignals:
    """Indicator signals for a single timeframe"""
    timeframe: str = ''
    kalman_trend: str = 'FLAT'  # RISING, FALLING, FLAT
    rsi_value: float = 50.0
    rsi_signal: str = 'NEUTRAL'  # OVERBOUGHT, OVERSOLD, NEUTRAL
    macd_signal: str = 'NEUTRAL'  # BULLISH, BEARISH, NEUTRAL
    vwap_position: str = 'AT'  # ABOVE, BELOW, AT
    bb_position: str = 'MID'  # UPPER, MID, LOWER
    adx_value: float = 20.0
    adx_trend: str = 'WEAK'  # STRONG, TREND, WEAK
    ema_signal: str = 'NEUTRAL'  # ABOVE, BELOW
    volume_signal: str = 'AVG'  # HIGH, AVG, LOW
    bullish_count: int = 0
    bearish_count: int = 0
    neutral_count: int = 0
    verdict: str = 'MIXED'  # BULLISH, BEARISH, MIXED
    confidence_pct: float = 50.0
    
    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class FlightPlan:
    """Complete multi-timeframe flight plan for a position"""
    symbol: str = ''
    timestamp: str = ''
    current_price: float = 0.0
    entry_price: float = 0.0
    stop_price: float = 0.0
    target_price: float = 0.0
    
    # Signals by timeframe
    signals_15min: TimeframeSignals = field(default_factory=TimeframeSignals)
    signals_1hour: TimeframeSignals = field(default_factory=TimeframeSignals)
    signals_4hour: TimeframeSignals = field(default_factory=TimeframeSignals)
    signals_daily: TimeframeSignals = field(default_factory=TimeframeSignals)
    signals_weekly: TimeframeSignals = field(default_factory=TimeframeSignals)
    
    # Price predictions (consensus ranges)
    predictions: Dict[str, Dict] = field(default_factory=dict)
    
    # Truth confluence scores
    truth_scores: Dict[str, float] = field(default_factory=dict)
    overall_truth_score: float = 50.0
    overall_direction: str = 'MIXED'
    
    # Decision matrix
    decision_matrix: Dict[str, Dict] = field(default_factory=dict)
    
    # Key levels and alerts
    bullish_triggers: List[str] = field(default_factory=list)
    bearish_triggers: List[str] = field(default_factory=list)
    emergency_exits: List[str] = field(default_factory=list)
    
    # Recommended action
    recommended_action: str = 'HOLD'
    action_confidence: float = 50.0
    strategy_note: str = ''
    
    def to_dict(self) -> Dict:
        return {
            'symbol': self.symbol,
            'timestamp': self.timestamp,
            'current_price': self.current_price,
            'entry_price': self.entry_price,
            'stop_price': self.stop_price,
            'target_price': self.target_price,
            'signals': {
                '15min': self.signals_15min.to_dict(),
                '1hour': self.signals_1hour.to_dict(),
                '4hour': self.signals_4hour.to_dict(),
                'daily': self.signals_daily.to_dict(),
                'weekly': self.signals_weekly.to_dict()
            },
            'predictions': self.predictions,
            'truth_scores': self.truth_scores,
            'overall_truth_score': self.overall_truth_score,
            'overall_direction': self.overall_direction,
            'decision_matrix': self.decision_matrix,
            'bullish_triggers': self.bullish_triggers,
            'bearish_triggers': self.bearish_triggers,
            'emergency_exits': self.emergency_exits,
            'recommended_action': self.recommended_action,
            'action_confidence': self.action_confidence,
            'strategy_note': self.strategy_note
        }
    
    def format_for_log(self) -> str:
        """Format flight plan for logging"""
        lines = []
        lines.append("═" * 90)
        lines.append(f"🔮 MULTI-INDICATOR TRUTH MATRIX                                              {self.symbol}")
        lines.append("═" * 90)
        lines.append(f"📊 Current: ₹{self.current_price:.2f} | Entry: ₹{self.entry_price:.2f} | Stop: ₹{self.stop_price:.2f} | Target: ₹{self.target_price:.2f}")
        lines.append("═" * 90)
        lines.append("")
        
        # Indicator signals table
        lines.append("┌" + "─" * 88 + "┐")
        lines.append("│" + "INDICATOR SIGNALS BY TIMEFRAME".center(88) + "│")
        lines.append("├" + "──────────────┬" * 5 + "─────────────┤")
        lines.append("│  INDICATOR   │   15-MIN     │    1-HOUR    │    4-HOUR    │    DAILY     │   WEEKLY    │")
        lines.append("├" + "──────────────┼" * 5 + "─────────────┤")
        
        # Build signal rows
        sigs = [self.signals_15min, self.signals_1hour, self.signals_4hour, self.signals_daily, self.signals_weekly]
        
        # Kalman row
        kalman_cells = [self._format_trend(s.kalman_trend) for s in sigs]
        lines.append(f"│ Kalman       │{kalman_cells[0]:^14}│{kalman_cells[1]:^14}│{kalman_cells[2]:^14}│{kalman_cells[3]:^14}│{kalman_cells[4]:^13}│")
        
        # RSI row
        rsi_cells = [self._format_rsi(s.rsi_value) for s in sigs]
        lines.append(f"│ RSI (value)  │{rsi_cells[0]:^14}│{rsi_cells[1]:^14}│{rsi_cells[2]:^14}│{rsi_cells[3]:^14}│{rsi_cells[4]:^13}│")
        
        # MACD row
        macd_cells = [self._format_signal(s.macd_signal) for s in sigs]
        lines.append(f"│ MACD         │{macd_cells[0]:^14}│{macd_cells[1]:^14}│{macd_cells[2]:^14}│{macd_cells[3]:^14}│{macd_cells[4]:^13}│")
        
        # VWAP row
        vwap_cells = [self._format_vwap(s.vwap_position) for s in sigs]
        lines.append(f"│ VWAP         │{vwap_cells[0]:^14}│{vwap_cells[1]:^14}│{vwap_cells[2]:^14}│{vwap_cells[3]:^14}│{vwap_cells[4]:^13}│")
        
        # Bollinger row
        bb_cells = [self._format_bb(s.bb_position) for s in sigs]
        lines.append(f"│ Bollinger    │{bb_cells[0]:^14}│{bb_cells[1]:^14}│{bb_cells[2]:^14}│{bb_cells[3]:^14}│{bb_cells[4]:^13}│")
        
        # ADX row
        adx_cells = [self._format_adx(s.adx_value, s.adx_trend) for s in sigs]
        lines.append(f"│ ADX (trend)  │{adx_cells[0]:^14}│{adx_cells[1]:^14}│{adx_cells[2]:^14}│{adx_cells[3]:^14}│{adx_cells[4]:^13}│")
        
        # EMA row
        ema_cells = [self._format_signal(s.ema_signal) for s in sigs]
        lines.append(f"│ EMA 9/21     │{ema_cells[0]:^14}│{ema_cells[1]:^14}│{ema_cells[2]:^14}│{ema_cells[3]:^14}│{ema_cells[4]:^13}│")
        
        # Volume row
        vol_cells = [self._format_volume(s.volume_signal) for s in sigs]
        lines.append(f"│ Volume       │{vol_cells[0]:^14}│{vol_cells[1]:^14}│{vol_cells[2]:^14}│{vol_cells[3]:^14}│{vol_cells[4]:^13}│")
        
        lines.append("├" + "──────────────┼" * 5 + "─────────────┤")
        
        # Counts
        bull_cells = [f"{s.bullish_count}/8" for s in sigs]
        bear_cells = [f"{s.bearish_count}/8" for s in sigs]
        neut_cells = [f"{s.neutral_count}/8" for s in sigs]
        lines.append(f"│ BULLISH      │{bull_cells[0]:^14}│{bull_cells[1]:^14}│{bull_cells[2]:^14}│{bull_cells[3]:^14}│{bull_cells[4]:^13}│")
        lines.append(f"│ BEARISH      │{bear_cells[0]:^14}│{bear_cells[1]:^14}│{bear_cells[2]:^14}│{bear_cells[3]:^14}│{bear_cells[4]:^13}│")
        lines.append(f"│ NEUTRAL      │{neut_cells[0]:^14}│{neut_cells[1]:^14}│{neut_cells[2]:^14}│{neut_cells[3]:^14}│{neut_cells[4]:^13}│")
        
        lines.append("├" + "──────────────┼" * 5 + "─────────────┤")
        
        # Verdict
        verdict_cells = [self._format_verdict(s.verdict) for s in sigs]
        lines.append(f"│ VERDICT      │{verdict_cells[0]:^14}│{verdict_cells[1]:^14}│{verdict_cells[2]:^14}│{verdict_cells[3]:^14}│{verdict_cells[4]:^13}│")
        lines.append("└" + "──────────────┴" * 5 + "─────────────┘")
        
        # Truth confluence score
        lines.append("")
        lines.append("┌" + "─" * 88 + "┐")
        lines.append("│" + "🎯 TRUTH CONFLUENCE SCORE".center(88) + "│")
        lines.append("├" + "─" * 88 + "┤")
        
        for tf, score in self.truth_scores.items():
            bar_len = int(score / 5)
            bar = "█" * bar_len + "░" * (20 - bar_len)
            direction = "BULLISH" if score >= 50 else "BEARISH"
            note = ""
            if tf == '15min' and score < 40:
                note = " ← Short-term weakness"
            elif tf == '4hour' and score > 80:
                note = " ← STRONGEST"
            lines.append(f"│   {tf.upper():8}: {bar}  {score:.0f}% {direction:8}{note:20} │")
        
        lines.append("│" + " " * 88 + "│")
        bar_len = int(self.overall_truth_score / 5)
        bar = "█" * bar_len + "░" * (20 - bar_len)
        lines.append(f"│   {'OVERALL':8}: {bar}  {self.overall_truth_score:.0f}% {self.overall_direction:8}                    │")
        lines.append("└" + "─" * 88 + "┘")
        
        # Flight path consensus
        lines.append("")
        lines.append("┌" + "─" * 88 + "┐")
        lines.append("│" + "🛫 FLIGHT PATH CONSENSUS".center(88) + "│")
        lines.append("├" + "─" * 88 + "┤")
        
        target_pct = ((self.target_price - self.current_price) / self.current_price * 100) if self.current_price > 0 else 0
        stop_pct = ((self.current_price - self.stop_price) / self.current_price * 100) if self.current_price > 0 else 0
        
        lines.append(f"│    🎯 ₹{self.target_price:.2f} TARGET {'·' * 50} [+{target_pct:.1f}%]".ljust(89) + "│")
        lines.append("│" + " " * 88 + "│")
        
        # Flight path arrows based on scores
        tfs = [('weekly', self.signals_weekly), ('daily', self.signals_daily), 
               ('4hour', self.signals_4hour), ('1hour', self.signals_1hour), ('15min', self.signals_15min)]
        
        for i, (tf_name, sig) in enumerate(tfs):
            arrow = "↗️" if sig.confidence_pct >= 50 else "↘️"
            conf = sig.confidence_pct
            note = ""
            if tf_name == '4hour' and conf > 80:
                note = " ← STRONGEST"
            elif tf_name == '15min' and conf < 40:
                note = " ← Short-term dip"
            indent = " " * (8 + i * 4)
            lines.append(f"│{indent}{arrow} {tf_name.upper()} ({conf:.0f}% conf){note}".ljust(89) + "│")
        
        lines.append(f"│    ✈️ ₹{self.current_price:.2f} NOW".ljust(89) + "│")
        lines.append("│" + " " * 88 + "│")
        lines.append(f"│    ⛔ ₹{self.stop_price:.2f} TERRAIN {'·' * 50} [-{stop_pct:.1f}%]".ljust(89) + "│")
        lines.append("│" + " " * 88 + "│")
        lines.append(f"│    📊 INTERPRETATION: {self.strategy_note[:60]}".ljust(89) + "│")
        lines.append("└" + "─" * 88 + "┘")
        
        # Decision matrix
        lines.append("")
        lines.append("┌" + "─" * 88 + "┐")
        lines.append("│" + "🎯 DECISION MATRIX".center(88) + "│")
        lines.append("├" + "─" * 88 + "┤")
        
        for question, answer_data in self.decision_matrix.items():
            answer = answer_data.get('answer', 'UNKNOWN')
            conf = answer_data.get('confidence', 50)
            reason = answer_data.get('reason', '')[:25]
            stars = "⭐" * int(conf / 20)
            emoji = "✅" if answer == 'YES' else ("❌" if answer == 'NO' else "🟡")
            lines.append(f"│  {question[:25]:25} │ {emoji} {answer:8} │ {stars:10} {conf:.0f}%  │ {reason:20} │")
        
        lines.append("└" + "─" * 88 + "┘")
        
        # Summary
        lines.append("")
        lines.append("═" * 90)
        lines.append(f"📊 SUMMARY: {self.overall_truth_score:.0f}% {self.overall_direction} | {self.strategy_note}")
        lines.append(f"💡 ACTION: {self.recommended_action} (Confidence: {self.action_confidence:.0f}%)")
        lines.append("═" * 90)
        
        return "\n".join(lines)
    
    def _format_trend(self, trend: str) -> str:
        if trend == 'RISING': return "↗️ RISING"
        elif trend == 'FALLING': return "↘️ FALLING"
        else: return "➡️ FLAT"
    
    def _format_rsi(self, value: float) -> str:
        if value > 70: return f"🔴 {value:.0f}"
        elif value < 30: return f"🟢 {value:.0f}"
        elif value > 50: return f"🟢 {value:.0f}"
        else: return f"🟡 {value:.0f}"
    
    def _format_signal(self, signal: str) -> str:
        if signal == 'BULLISH' or signal == 'ABOVE': return "🟢 BULLISH"
        elif signal == 'BEARISH' or signal == 'BELOW': return "🔴 BEARISH"
        else: return "🟡 NEUTRAL"
    
    def _format_vwap(self, position: str) -> str:
        if position == 'ABOVE': return "🟢 ABOVE"
        elif position == 'BELOW': return "🔴 BELOW"
        else: return "━━━"
    
    def _format_bb(self, position: str) -> str:
        if position == 'UPPER': return "🟢 UPPER"
        elif position == 'LOWER': return "🔴 LOWER"
        else: return "🟡 MID"
    
    def _format_adx(self, value: float, trend: str) -> str:
        if trend == 'STRONG': return f"🟢 {value:.0f} STRONG"
        elif trend == 'TREND': return f"🟢 {value:.0f} TREND"
        else: return f"🟡 {value:.0f} WEAK"
    
    def _format_volume(self, signal: str) -> str:
        if signal == 'HIGH': return "🟢 HIGH"
        elif signal == 'LOW': return "🔴 LOW"
        else: return "🟡 AVG"
    
    def _format_verdict(self, verdict: str) -> str:
        if verdict == 'BULLISH': return "🟢 BULLISH"
        elif verdict == 'BEARISH': return "🔴 BEARISH"
        else: return "🟡 MIXED"


class FlightPlanGenerator:
    """
    v4.12.0: Generates comprehensive multi-timeframe flight plan at entry.
    
    Analyzes 5 timeframes (15min, 1H, 4H, Daily, Weekly) with 8 indicators each.
    Creates truth confluence score, decision matrix, and price predictions.
    """
    
    TIMEFRAMES = {
        '15minute': '15min',
        '60minute': '1hour',
        '4hour': '4hour',  # Note: Kite uses 'day' for 4H, we'll aggregate
        'day': 'daily',
        'week': 'weekly'
    }
    
    def __init__(self, kite, config=None):
        """Initialize flight plan generator with Kite API access."""
        self.kite = kite
        self.config = config
        self.bb_analyzer = BollingerBandAnalyzer()
        self.fib_calculator = FibonacciLevelCalculator()
        self.vwap_analyzer = VWAPAnalyzer()
        logger.info("✅ FlightPlanGenerator v4.12.0 initialized")
    
    def generate(self, symbol: str, current_price: float, entry_price: float,
                 stop_price: float, target_price: float, 
                 instrument_token: int = None) -> FlightPlan:
        """
        Generate comprehensive flight plan for a position.
        
        Args:
            symbol: Stock symbol
            current_price: Current market price
            entry_price: Entry price
            stop_price: Stop loss price
            target_price: Target price
            instrument_token: Optional instrument token (for API calls)
            
        Returns:
            FlightPlan with all analysis
        """
        flight_plan = FlightPlan(
            symbol=symbol,
            timestamp=datetime.now().isoformat(),
            current_price=current_price,
            entry_price=entry_price,
            stop_price=stop_price,
            target_price=target_price
        )
        
        try:
            # Fetch data for each timeframe
            tf_data = self._fetch_all_timeframes(symbol, instrument_token)
            
            # Analyze each timeframe
            flight_plan.signals_15min = self._analyze_timeframe(tf_data.get('15minute', []), '15min', current_price)
            flight_plan.signals_1hour = self._analyze_timeframe(tf_data.get('60minute', []), '1hour', current_price)
            flight_plan.signals_4hour = self._analyze_timeframe(tf_data.get('day', []), '4hour', current_price)  # Approximate
            flight_plan.signals_daily = self._analyze_timeframe(tf_data.get('day', []), 'daily', current_price)
            flight_plan.signals_weekly = self._analyze_timeframe(tf_data.get('week', []), 'weekly', current_price)
            
            # Calculate truth scores
            flight_plan.truth_scores = {
                '15min': flight_plan.signals_15min.confidence_pct,
                '1hour': flight_plan.signals_1hour.confidence_pct,
                '4hour': flight_plan.signals_4hour.confidence_pct,
                'daily': flight_plan.signals_daily.confidence_pct,
                'weekly': flight_plan.signals_weekly.confidence_pct
            }
            
            # Overall truth score (weighted average - higher timeframes weighted more)
            weights = {'15min': 0.10, '1hour': 0.15, '4hour': 0.25, 'daily': 0.25, 'weekly': 0.25}
            flight_plan.overall_truth_score = sum(
                flight_plan.truth_scores[tf] * w for tf, w in weights.items()
            )
            
            if flight_plan.overall_truth_score >= 65:
                flight_plan.overall_direction = 'BULLISH'
            elif flight_plan.overall_truth_score <= 35:
                flight_plan.overall_direction = 'BEARISH'
            else:
                flight_plan.overall_direction = 'MIXED'
            
            # Generate price predictions
            flight_plan.predictions = self._generate_predictions(
                tf_data, current_price, stop_price, target_price
            )
            
            # Generate decision matrix
            flight_plan.decision_matrix = self._generate_decision_matrix(flight_plan)
            
            # Generate triggers and alerts
            flight_plan.bullish_triggers, flight_plan.bearish_triggers, flight_plan.emergency_exits = \
                self._generate_triggers(flight_plan, current_price, stop_price, target_price)
            
            # Determine recommended action
            flight_plan.recommended_action, flight_plan.action_confidence, flight_plan.strategy_note = \
                self._determine_action(flight_plan)
            
        except Exception as e:
            logger.error(f"FlightPlan generation error for {symbol}: {e}")
            flight_plan.strategy_note = f"Error generating full analysis: {e}"
        
        return flight_plan
    
    def _fetch_all_timeframes(self, symbol: str, instrument_token: int = None) -> Dict[str, List]:
        """Fetch OHLCV data for all timeframes."""
        data = {}
        
        if not instrument_token:
            # Try to get instrument token
            try:
                instruments = self.kite.instruments('NSE')
                for inst in instruments:
                    if inst['tradingsymbol'] == symbol:
                        instrument_token = inst['instrument_token']
                        break
            except:
                pass
        
        if not instrument_token:
            return data
        
        now = datetime.now()
        
        # Fetch each timeframe
        timeframe_configs = {
            '15minute': (timedelta(days=5), '15minute'),
            '60minute': (timedelta(days=30), '60minute'),
            'day': (timedelta(days=365), 'day'),
            'week': (timedelta(days=365*2), 'week')
        }
        
        for tf_name, (lookback, interval) in timeframe_configs.items():
            try:
                from_date = now - lookback
                candles = self.kite.historical_data(
                    instrument_token=instrument_token,
                    from_date=from_date,
                    to_date=now,
                    interval=interval
                )
                data[tf_name] = candles if candles else []
            except Exception as e:
                logger.debug(f"Failed to fetch {tf_name} data: {e}")
                data[tf_name] = []
        
        return data
    
    def _analyze_timeframe(self, candles: List[Dict], timeframe: str, current_price: float) -> TimeframeSignals:
        """Analyze indicators for a single timeframe."""
        signals = TimeframeSignals(timeframe=timeframe)
        
        if not candles or len(candles) < 20:
            return signals
        
        # Extract OHLCV
        closes = [c['close'] for c in candles[-50:]]
        highs = [c['high'] for c in candles[-50:]]
        lows = [c['low'] for c in candles[-50:]]
        volumes = [c['volume'] for c in candles[-50:]]
        
        bullish = 0
        bearish = 0
        neutral = 0
        
        # 1. Kalman trend (velocity direction)
        if len(closes) >= 3:
            recent_vel = closes[-1] - closes[-3]
            if recent_vel > closes[-1] * 0.002:  # > 0.2% up
                signals.kalman_trend = 'RISING'
                bullish += 1
            elif recent_vel < -closes[-1] * 0.002:
                signals.kalman_trend = 'FALLING'
                bearish += 1
            else:
                signals.kalman_trend = 'FLAT'
                neutral += 1
        
        # 2. RSI
        signals.rsi_value = self._calculate_rsi(closes)
        if signals.rsi_value > 70:
            signals.rsi_signal = 'OVERBOUGHT'
            bearish += 1
        elif signals.rsi_value < 30:
            signals.rsi_signal = 'OVERSOLD'
            bullish += 1  # Oversold is bullish for mean reversion
        elif signals.rsi_value > 50:
            signals.rsi_signal = 'BULLISH'
            bullish += 1
        else:
            signals.rsi_signal = 'NEUTRAL'
            neutral += 1
        
        # 3. MACD
        macd_signal = self._calculate_macd_signal(closes)
        signals.macd_signal = macd_signal
        if macd_signal == 'BULLISH':
            bullish += 1
        elif macd_signal == 'BEARISH':
            bearish += 1
        else:
            neutral += 1
        
        # 4. VWAP (only for intraday)
        if timeframe in ['15min', '1hour']:
            vwap_result = self.vwap_analyzer.calculate(highs, lows, closes, volumes, current_price)
            signals.vwap_position = vwap_result.price_vs_vwap
            if signals.vwap_position == 'ABOVE':
                bullish += 1
            elif signals.vwap_position == 'BELOW':
                bearish += 1
            else:
                neutral += 1
        else:
            signals.vwap_position = 'N/A'
            neutral += 1
        
        # 5. Bollinger Bands
        bb_result = self.bb_analyzer.analyze(closes, current_price)
        if bb_result.price_position > 0.7:
            signals.bb_position = 'UPPER'
            bullish += 1
        elif bb_result.price_position < 0.3:
            signals.bb_position = 'LOWER'
            bearish += 1  # Lower BB could be oversold
        else:
            signals.bb_position = 'MID'
            neutral += 1
        
        # 6. ADX
        signals.adx_value = self._calculate_adx(highs, lows, closes)
        if signals.adx_value > 30:
            signals.adx_trend = 'STRONG'
            bullish += 1  # Strong trend (assuming bullish context)
        elif signals.adx_value > 20:
            signals.adx_trend = 'TREND'
            bullish += 1
        else:
            signals.adx_trend = 'WEAK'
            neutral += 1
        
        # 7. EMA 9/21
        ema9 = self._calculate_ema(closes, 9)
        ema21 = self._calculate_ema(closes, 21)
        if ema9 > ema21 and current_price > ema9:
            signals.ema_signal = 'ABOVE'
            bullish += 1
        elif ema9 < ema21 or current_price < ema21:
            signals.ema_signal = 'BELOW'
            bearish += 1
        else:
            signals.ema_signal = 'NEUTRAL'
            neutral += 1
        
        # 8. Volume
        avg_vol = sum(volumes[-20:]) / 20 if len(volumes) >= 20 else sum(volumes) / len(volumes)
        current_vol = volumes[-1] if volumes else 0
        if current_vol > avg_vol * 1.5:
            signals.volume_signal = 'HIGH'
            bullish += 1
        elif current_vol < avg_vol * 0.5:
            signals.volume_signal = 'LOW'
            bearish += 1
        else:
            signals.volume_signal = 'AVG'
            neutral += 1
        
        # Set counts
        signals.bullish_count = bullish
        signals.bearish_count = bearish
        signals.neutral_count = neutral
        
        # Determine verdict
        if bullish >= 5:
            signals.verdict = 'BULLISH'
        elif bearish >= 5:
            signals.verdict = 'BEARISH'
        else:
            signals.verdict = 'MIXED'
        
        # Confidence percentage
        signals.confidence_pct = (bullish / 8) * 100
        
        return signals
    
    def _calculate_rsi(self, prices: List[float], period: int = 14) -> float:
        """Calculate RSI."""
        if len(prices) < period + 1:
            return 50.0
        
        deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
        gains = [d if d > 0 else 0 for d in deltas[-period:]]
        losses = [-d if d < 0 else 0 for d in deltas[-period:]]
        
        avg_gain = sum(gains) / period
        avg_loss = sum(losses) / period
        
        if avg_loss == 0:
            return 100.0
        
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        return round(rsi, 1)
    
    def _calculate_macd_signal(self, prices: List[float]) -> str:
        """Calculate MACD signal."""
        if len(prices) < 26:
            return 'NEUTRAL'
        
        ema12 = self._calculate_ema(prices, 12)
        ema26 = self._calculate_ema(prices, 26)
        macd_line = ema12 - ema26
        
        # Simple signal: MACD > 0 is bullish
        if macd_line > 0:
            return 'BULLISH'
        elif macd_line < 0:
            return 'BEARISH'
        return 'NEUTRAL'
    
    def _calculate_ema(self, prices: List[float], period: int) -> float:
        """Calculate EMA."""
        if len(prices) < period:
            return prices[-1] if prices else 0
        
        multiplier = 2 / (period + 1)
        ema = sum(prices[:period]) / period  # SMA for first value
        
        for price in prices[period:]:
            ema = (price * multiplier) + (ema * (1 - multiplier))
        
        return ema
    
    def _calculate_adx(self, highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> float:
        """Calculate ADX (simplified)."""
        if len(highs) < period + 1:
            return 20.0
        
        # Simplified: Use ATR-based volatility as proxy
        trs = []
        for i in range(1, min(len(highs), period + 1)):
            tr = max(
                highs[i] - lows[i],
                abs(highs[i] - closes[i-1]),
                abs(lows[i] - closes[i-1])
            )
            trs.append(tr)
        
        atr = sum(trs) / len(trs) if trs else 0
        avg_price = sum(closes[-period:]) / period
        
        # ADX proxy: Higher ATR relative to price = stronger trend
        volatility_pct = (atr / avg_price) * 100 if avg_price > 0 else 0
        adx_proxy = min(50, volatility_pct * 10)  # Scale to 0-50 range
        
        return round(adx_proxy, 1)
    
    def _generate_predictions(self, tf_data: Dict, current_price: float,
                              stop_price: float, target_price: float) -> Dict:
        """Generate price predictions for different horizons."""
        predictions = {}
        
        # Calculate ATR for range estimation
        day_data = tf_data.get('day', [])
        if day_data and len(day_data) >= 14:
            atrs = []
            for i in range(1, min(15, len(day_data))):
                tr = max(
                    day_data[i]['high'] - day_data[i]['low'],
                    abs(day_data[i]['high'] - day_data[i-1]['close']),
                    abs(day_data[i]['low'] - day_data[i-1]['close'])
                )
                atrs.append(tr)
            atr = sum(atrs) / len(atrs)
        else:
            atr = current_price * 0.02  # Default 2%
        
        # 1 Hour prediction
        predictions['1_hour'] = {
            'low': round(current_price - atr * 0.3, 2),
            'high': round(current_price + atr * 0.3, 2),
            'consensus': round(current_price + atr * 0.1, 2)
        }
        
        # 4 Hours prediction
        predictions['4_hours'] = {
            'low': round(current_price - atr * 0.6, 2),
            'high': round(current_price + atr * 0.6, 2),
            'consensus': round(current_price + atr * 0.2, 2)
        }
        
        # Tomorrow prediction
        predictions['tomorrow'] = {
            'low': round(current_price - atr * 1.0, 2),
            'high': round(current_price + atr * 1.0, 2),
            'consensus': round(current_price + atr * 0.3, 2)
        }
        
        # Next week prediction
        predictions['next_week'] = {
            'low': round(current_price - atr * 2.5, 2),
            'high': round(current_price + atr * 2.5, 2),
            'consensus': round(current_price + atr * 0.8, 2)
        }
        
        return predictions
    
    def _generate_decision_matrix(self, flight_plan: FlightPlan) -> Dict:
        """Generate decision matrix with yes/no answers."""
        matrix = {}
        
        overall = flight_plan.overall_truth_score
        tf_15 = flight_plan.signals_15min.confidence_pct
        tf_1h = flight_plan.signals_1hour.confidence_pct
        tf_4h = flight_plan.signals_4hour.confidence_pct
        tf_d = flight_plan.signals_daily.confidence_pct
        tf_w = flight_plan.signals_weekly.confidence_pct
        
        # Exit now?
        exit_conf = 100 - overall  # Higher confidence to NOT exit if bullish
        matrix['Exit now?'] = {
            'answer': 'NO' if overall >= 50 else 'YES',
            'confidence': exit_conf if overall >= 50 else overall,
            'reason': 'Higher TFs bullish' if overall >= 50 else 'Multiple TFs bearish'
        }
        
        # Hold through today?
        hold_today = (tf_1h + tf_4h) / 2
        matrix['Hold through today?'] = {
            'answer': 'YES' if hold_today >= 50 else 'NO',
            'confidence': hold_today,
            'reason': '1H/4H positive' if hold_today >= 50 else '1H/4H negative'
        }
        
        # Hold overnight?
        hold_overnight = tf_d
        matrix['Hold overnight?'] = {
            'answer': 'YES' if hold_overnight >= 50 else 'NO',
            'confidence': hold_overnight,
            'reason': 'Daily bullish' if hold_overnight >= 50 else 'Daily bearish'
        }
        
        # Hold for week?
        hold_week = tf_w
        matrix['Hold for week?'] = {
            'answer': 'MAYBE' if 40 <= hold_week <= 70 else ('YES' if hold_week > 70 else 'NO'),
            'confidence': hold_week,
            'reason': 'Weekly positive' if hold_week >= 50 else 'Weekly uncertain'
        }
        
        # Add to position?
        add_conf = tf_15
        matrix['Add to position?'] = {
            'answer': 'NO' if tf_15 < 60 else 'YES',
            'confidence': 100 - tf_15 if tf_15 < 60 else tf_15,
            'reason': 'Wait for 15m confirm' if tf_15 < 60 else '15m confirms'
        }
        
        # Move stop tighter?
        matrix['Move stop tighter?'] = {
            'answer': 'NO' if overall >= 60 else 'YES',
            'confidence': 80 if overall >= 60 else 60,
            'reason': 'Give room for dip' if overall >= 60 else 'Protect gains'
        }
        
        # Will hit target today?
        target_conf = min(tf_1h, tf_4h)
        matrix['Will hit target today?'] = {
            'answer': 'MAYBE' if 40 <= target_conf <= 70 else ('YES' if target_conf > 70 else 'UNLIKELY'),
            'confidence': target_conf,
            'reason': 'Needs 1H breakout' if target_conf < 70 else 'Momentum strong'
        }
        
        # Will hit stop today?
        stop_risk = 100 - overall
        matrix['Will hit stop today?'] = {
            'answer': 'UNLIKELY' if overall >= 60 else ('MAYBE' if overall >= 40 else 'LIKELY'),
            'confidence': overall,
            'reason': 'Strong support' if overall >= 60 else 'Watch closely'
        }
        
        return matrix
    
    def _generate_triggers(self, flight_plan: FlightPlan, current_price: float,
                           stop_price: float, target_price: float) -> Tuple[List, List, List]:
        """Generate bullish/bearish triggers and emergency exits."""
        bullish = []
        bearish = []
        emergency = []
        
        # Calculate key levels
        range_size = target_price - stop_price
        
        # Bullish triggers
        vwap_reclaim = current_price * 1.005  # 0.5% above current
        bullish.append(f"Price > ₹{vwap_reclaim:.2f} (VWAP reclaim) → 15-min turns bullish")
        bullish.append(f"Price > ₹{current_price * 1.01:.2f} (Bollinger upper) → Breakout confirmed")
        bullish.append(f"RSI 15-min > 50 → Short-term momentum shift")
        
        # Bearish triggers
        support_1h = current_price * 0.99  # 1% below
        support_daily = current_price * 0.98  # 2% below
        bearish.append(f"Price < ₹{support_1h:.2f} (1H support) → 1-hour turns bearish")
        bearish.append(f"Price < ₹{support_daily:.2f} (Daily support) → Trend in danger")
        bearish.append(f"RSI Daily < 45 → Momentum fading")
        
        # Emergency exits
        emergency.append(f"Price < ₹{stop_price:.2f} (Stop hit)")
        emergency.append(f"Truth score drops below 40%")
        emergency.append(f"3+ timeframes turn bearish")
        
        return bullish, bearish, emergency
    
    def _determine_action(self, flight_plan: FlightPlan) -> Tuple[str, float, str]:
        """Determine recommended action and strategy note."""
        overall = flight_plan.overall_truth_score
        tf_15 = flight_plan.signals_15min.confidence_pct
        
        if overall >= 70:
            action = 'HOLD'
            confidence = overall
            note = f"Strong bullish consensus across timeframes"
        elif overall >= 50:
            if tf_15 < 40:
                action = 'HOLD'
                confidence = 75
                note = f"Short-term weakness, hold for higher timeframe trend"
            else:
                action = 'HOLD'
                confidence = overall
                note = f"Moderate bullish, watch for breakout"
        elif overall >= 35:
            action = 'TIGHTEN_STOP'
            confidence = 60
            note = f"Mixed signals, tighten stop for protection"
        else:
            action = 'EXIT'
            confidence = 100 - overall
            note = f"Multiple timeframes bearish, exit recommended"
        
        return action, confidence, note


# ═══════════════════════════════════════════════════════════════════════════════
# PHASE 4 PORTFOLIO MANAGER
# ═══════════════════════════════════════════════════════════════════════════════

class Phase4PortfolioManager:
    """
    Autonomous Portfolio Manager with Aviation-Inspired Systems.
    
    Features:
    - TCAS: Stop-loss collision avoidance
    - ILS: Profit target landing system
    - Go-Around: Health-based exit gates
    - Kalman: Price prediction
    - GTT: Automatic order management
    - ChatGPT: Intelligent decision making
    """
    
    def __init__(
        self,
        kite,
        config,
        telegram,
        phase3_executor=None,  # v4.9.0: Deprecated - kept for backward compatibility
        chatgpt_advisor=None,
        broker_sync=None,
        capital_manager=None
    ):
        """
        Initialize Phase 4 Portfolio Manager.
        
        v4.9.0: Phase 4 now handles all SELL orders internally.
                phase3_executor parameter deprecated (kept for backward compatibility).
        v1.1.0: Added capital_manager for centralized capital tracking.
        
        Args:
            kite: Authenticated KiteConnect instance
            config: Configuration object
            telegram: Telegram notifier
            phase3_executor: DEPRECATED - No longer used (v4.9.0)
            chatgpt_advisor: ChatGPT strategic advisor
            broker_sync: Centralized broker sync manager (v4.3.1)
            capital_manager: Capital Manager for centralized tracking (v1.1.0)
        """
        self.kite = kite
        self.config = config
        self.telegram = telegram
        # v4.9.0: phase3 no longer used - Phase 4 handles SELL orders internally
        # self.phase3 = phase3_executor  # REMOVED
        self.chatgpt = chatgpt_advisor
        self.broker_sync = broker_sync  # 📡 v4.3.1: Centralized broker communication
        
        # ═══════════════════════════════════════════════════════════════════
        # v4.10.0 FIX: Orchestrator reference for position management
        # Set via set_orchestrator() after orchestrator initialization
        # ═══════════════════════════════════════════════════════════════════
        self.orchestrator = None

        # ISSUE-15: Phase 6 reference for TCAS pivot signal handoff
        # Wired post-init by orchestrator (self.phase4.phase6 = self.phase6)
        self.phase6 = None
        self.tcas_pivot_early_signaled: set = set()  # ISSUE-15: symbols that got early Phase 6 warning

        # ═══════════════════════════════════════════════════════════════════
        # v1.1.0 NEW: Capital Manager Integration
        # ═══════════════════════════════════════════════════════════════════
        self.capital_manager = capital_manager
        if self.capital_manager:
            logger.info("✅ Capital Manager integrated - centralized capital tracking")
        else:
            logger.warning("⚠️  Capital Manager not provided - capital release may not work!")
        
        # ═══════════════════════════════════════════════════════════════════
        # v4.8.1: C1 - Decision History Tracker
        # ═══════════════════════════════════════════════════════════════════
        try:
            self.decision_tracker = DecisionHistoryTracker()
            logger.info("✅ Decision History Tracker initialized")
            logger.info(self.decision_tracker.get_summary())
        except Exception as e:
            logger.warning(f"⚠️ Decision History Tracker not available: {e}")
            self.decision_tracker = None
        
        # ═══════════════════════════════════════════════════════════════════
        # MIE v1.0.0: Market Intelligence Engine (set by Orchestrator)
        # ═══════════════════════════════════════════════════════════════════
        self.mie = None

        # ═══════════════════════════════════════════════════════════════════
        # v4.8.0: PREDICTIVE STOP (Was dead code - NOW ENABLED!)
        # ═══════════════════════════════════════════════════════════════════
        try:
            self.predictive_stop = PredictiveStop(config)
            logger.info("   ✅ Predictive Stop ENABLED (exit before stop hit)")
        except Exception as e:
            logger.warning(f"   ⚠️ Predictive Stop not available: {e}")
            self.predictive_stop = None
        
        # ═══════════════════════════════════════════════════════════════════
        # v4.11.0: TRUTH PREDICTOR (Multi-indicator predictions)
        # ═══════════════════════════════════════════════════════════════════
        try:
            self.truth_predictor = TruthPredictor(config)
            logger.info("   ✅ TruthPredictor v4.11.0 ENABLED (BB, Fib, VWAP)")
        except Exception as e:
            logger.warning(f"   ⚠️ TruthPredictor not available: {e}")
            self.truth_predictor = None
        
        # v4.11.0: Prediction checkpoint tracking
        self.last_checkpoint_time: Dict[str, datetime] = {}  # symbol -> last checkpoint
        self.checkpoint_interval_minutes = 60  # Track predictions every hour
        
        # ═══════════════════════════════════════════════════════════════════
        # v4.12.0: MULTI-TIMEFRAME FLIGHT PLAN GENERATOR
        # ═══════════════════════════════════════════════════════════════════
        try:
            self.flight_plan_generator = FlightPlanGenerator(kite, config)
            logger.info("   ✅ FlightPlanGenerator v4.12.0 ENABLED (5-timeframe analysis)")
        except Exception as e:
            logger.warning(f"   ⚠️ FlightPlanGenerator not available: {e}")
            self.flight_plan_generator = None

        # ═══════════════════════════════════════════════════════════════════
        # v4.14.1: ML DATA LOGGER (feed all exits into ML pipeline)
        # ═══════════════════════════════════════════════════════════════════
        try:
            from ml_data_logger import MLDataLogger
            self.ml_logger = MLDataLogger()
            logger.info("   ✅ MLDataLogger integrated — all exits feed ML pipeline")
        except ImportError:
            self.ml_logger = None
            logger.info("   ℹ️  MLDataLogger not available — ML logging disabled")
        except Exception as e:
            self.ml_logger = None
            logger.warning(f"   ⚠️ MLDataLogger init failed: {e}")

        # ═══════════════════════════════════════════════════════════════════
        # ENSEMBLE PREDICTION ENGINE (advisory only — does not trigger exits)
        # ═══════════════════════════════════════════════════════════════════
        self._ensemble_engine = EnsemblePrediction() if ENSEMBLE_AVAILABLE else None
        self._ensemble_cache: Dict[str, Any] = {}          # {symbol: PredictionResult}
        self._ensemble_last_update: Dict[str, datetime] = {}  # {symbol: datetime}
        self._ensemble_update_interval = 300                # Update every 5 minutes
        self._price_history: Dict[str, list] = {}           # {symbol: [{"price", "timestamp"}]}
        if self._ensemble_engine:
            logger.info("   ✅ Ensemble Prediction Engine ENABLED (advisory only)")

        # ═══════════════════════════════════════════════════════════════════
        # POSITIONS & STATE
        # ═══════════════════════════════════════════════════════════════════

        # v4.9.0: Position delegation to orchestrator (Single Source of Truth)
        # Phase 4 accesses positions via @property that delegates to orchestrator
        # _local_positions is fallback for standalone operation
        self._local_positions: Dict[str, Dict] = {}  # Fallback for standalone
        self.tcas_ra_last_warning: Dict[str, datetime] = {}  # v4.13.2: TCAS RA cooldown
        self.kalman_filters: Dict[str, Any] = {}  # symbol -> KalmanFilter
        self.failed_exit_attempts: Dict[str, int] = {}  # symbol -> count (prevent exit spam)
        self.max_exit_attempts = 3  # Max attempts before manual intervention needed
        self.market_context: Dict = {}  # From Phase 1 (startup)
        self.live_market_sentiment: Dict = {}  # From Orchestrator ChatGPT calls (live updates)
        self.current_regime: MarketRegime = MarketRegime.NORMAL
        
        # ═══════════════════════════════════════════════════════════════════
        # TIMING & INTERVALS
        # ═══════════════════════════════════════════════════════════════════
        
        self.MONITORING_INTERVAL = getattr(config, 'PHASE4_MONITORING_INTERVAL_SEC', 30)
        self.BROKER_SYNC_INTERVAL = getattr(config, 'PHASE4_BROKER_SYNC_INTERVAL_SEC', 1800)  # 30 minutes
        self.CHATGPT_PERIODIC_INTERVAL = getattr(config, 'PHASE4_CHATGPT_PERIODIC_MIN', 30) * 60
        
        # v4.15.0: CNC positions get longer cycle (60 min) vs MIS (5 min cooldown)
        self.CNC_CONSULTATION_INTERVAL = getattr(config, 'PHASE4_CNC_CONSULTATION_MIN', 60) * 60  # 60 min for CNC
        self.GTT_CHECK_INTERVAL = 300  # 5 minutes
        
        self.last_broker_sync = datetime.min
        self.last_chatgpt_call: Dict[str, datetime] = {}  # symbol -> last call time
        self.last_gtt_check = datetime.min
        self.chatgpt_cooldown = 300  # 5 minutes cooldown per position
        
        # v5.3.2 FIX: Track positions closed externally (GTT triggered, manual exit)
        # Prevents ghost position monitoring loop
        self._closed_externally_today: set = set()
        
        # ═══════════════════════════════════════════════════════════════════
        # v4.8.1 C1: DECISION HISTORY TRACKING
        # ═══════════════════════════════════════════════════════════════════
        self.decision_history: List[Dict] = []  # All ChatGPT decisions with outcomes
        self.max_history_size = 1000  # Keep last 1000 decisions
        
        # ═══════════════════════════════════════════════════════════════════
        # v4.8.1 C2: LOOP DETECTION (Prevent re-entry mistakes)
        # ═══════════════════════════════════════════════════════════════════
        self.exit_history: Dict[str, Dict] = {}  # symbol -> {exit_time, exit_price, reason}
        self.reentry_cooldown_minutes = 60  # 60 min cooldown after exit
        self._exit_history_file = 'data/exit_history.json'  # v4.10.0: Persist across restarts
        self._load_exit_history()  # Load persisted state
        
        # ═══════════════════════════════════════════════════════════════════
        # v4.8.1 C3: OVER-TRADING PREVENTION
        # ═══════════════════════════════════════════════════════════════════
        self.chatgpt_consultation_count: Dict[str, int] = {}  # symbol -> count today
        self.max_consultations_per_position = 5  # Max ChatGPT calls per position per day
        self.consultation_reset_time = dt_time(9, 15)  # Reset at market open
        
        # ═══════════════════════════════════════════════════════════════════
        # TCAS THRESHOLDS (in ATR units)
        # ═══════════════════════════════════════════════════════════════════
        
        self.TCAS_TA_THRESHOLD = getattr(config, 'TCAS_TA_THRESHOLD_ATR', 2.0)
        self.TCAS_RA_THRESHOLD = getattr(config, 'TCAS_RA_THRESHOLD_ATR', 1.5)
        self.TCAS_ALIM_THRESHOLD = getattr(config, 'TCAS_ALIM_THRESHOLD_ATR', 0.75)
        
        # ═══════════════════════════════════════════════════════════════════
        # ILS PHASES (% of target)
        # ═══════════════════════════════════════════════════════════════════
        
        self.ILS_OUTER_MARKER = getattr(config, 'ILS_OUTER_MARKER_PCT', 25)
        self.ILS_MIDDLE_MARKER = getattr(config, 'ILS_MIDDLE_MARKER_PCT', 50)
        self.ILS_INNER_MARKER = getattr(config, 'ILS_INNER_MARKER_PCT', 75)
        self.ILS_DECISION_HEIGHT = getattr(config, 'ILS_DECISION_HEIGHT_PCT', 90)
        
        # ═══════════════════════════════════════════════════════════════════
        # HEALTH THRESHOLDS
        # ═══════════════════════════════════════════════════════════════════
        
        self.HEALTH_CRITICAL = getattr(config, 'HEALTH_CRITICAL_THRESHOLD', 30)
        self.HEALTH_UNSTABLE = getattr(config, 'HEALTH_UNSTABLE_THRESHOLD', 50)
        self.HEALTH_MARGINAL = getattr(config, 'HEALTH_MARGINAL_THRESHOLD', 70)
        
        # ═══════════════════════════════════════════════════════════════════
        # DANGER ZONE THRESHOLDS
        # ═══════════════════════════════════════════════════════════════════
        
        self.DANGER_ZONE_PCT = getattr(config, 'PHASE4_DANGER_ZONE_PCT', -1.0)
        self.CRITICAL_ZONE_PCT = getattr(config, 'PHASE4_CRITICAL_ZONE_PCT', -2.0)
        
        # ═══════════════════════════════════════════════════════════════════
        # GTT CONFIGURATION
        # ═══════════════════════════════════════════════════════════════════
        
        self.ENABLE_GTT = getattr(config, 'ENABLE_GTT_ORDERS', True)
        self.GTT_OVERNIGHT_BUFFER = getattr(config, 'GTT_OVERNIGHT_STOP_BUFFER_PCT', 1.5)
        
        # ═══════════════════════════════════════════════════════════════════
        # REGIME PARAMETERS
        # ═══════════════════════════════════════════════════════════════════
        
        self.REGIME_PARAMS = getattr(config, 'REGIME_PARAMS', {
            'SQUEEZE': {'stop_mult': 1.5, 'target_mult': 2.0, 'trail_pct': 1.0},
            'STRONG_TREND': {'stop_mult': 3.0, 'target_mult': 4.0, 'trail_pct': 2.0},
            'VOLATILE_TREND': {'stop_mult': 3.5, 'target_mult': 3.0, 'trail_pct': 1.5},
            'CHOPPY_VOLATILE': {'stop_mult': 2.0, 'target_mult': 1.5, 'trail_pct': 0.5},
            'RANGING_QUIET': {'stop_mult': 1.5, 'target_mult': 1.5, 'trail_pct': 1.0},
            'CRISIS': {'stop_mult': 4.0, 'target_mult': 2.0, 'trail_pct': 0.5},
            'NORMAL': {'stop_mult': 2.5, 'target_mult': 2.5, 'trail_pct': 1.5}
        })
        
        # ═══════════════════════════════════════════════════════════════════
        # FILE PATHS
        # ═══════════════════════════════════════════════════════════════════
        
        self.POSITIONS_FILE = getattr(config, 'POSITIONS_FILE', 'data/phase3_outputs/positions.json')
        self.MARKET_CONTEXT_FILE = getattr(config, 'MARKET_CONTEXT_FILE', 'data/phase1_outputs/market_context.json')
        
        # ═══════════════════════════════════════════════════════════════════
        # INTERRUPT FLAGS
        # ═══════════════════════════════════════════════════════════════════
        
        self.tcas_alim_flag = False
        self.emergency_exit_queue: List[str] = []
        self.pending_chatgpt_decisions: Dict[str, Dict] = {}

        # ═══════════════════════════════════════════════════════════════════
        # v1.0.0: CANDLESTICK PATTERN WATCH (for TCAS warnings)
        # ═══════════════════════════════════════════════════════════════════
        self._pattern_watch: Dict[str, Dict] = {}

        # ═══════════════════════════════════════════════════════════════════
        # v1.0.0: ORB ADVISORY REFERENCE (pull model — set by orchestrator)
        # ═══════════════════════════════════════════════════════════════════
        self._orb_advisory = None

        # ═══════════════════════════════════════════════════════════════════
        # INITIALIZATION
        # ═══════════════════════════════════════════════════════════════════
        
        self._log_initialization()
    
    def _log_initialization(self):
        """Log initialization info"""
        logger.info("=" * 80)
        logger.info("🛫 PHASE 4 PORTFOLIO MANAGER v4.11.0 INITIALIZED")
        logger.info("=" * 80)
        logger.info("")
        logger.info("🤖 FULLY AUTONOMOUS - NO HUMAN MONITORING REQUIRED")
        logger.info("")
        logger.info("v4.11.0 NEW: TRUTH PREDICTOR SYSTEM")
        logger.info("  🔮 BollingerBandAnalyzer: Squeeze detection, mean reversion")
        logger.info("  🔮 FibonacciCalculator: Retracement/extension levels")
        logger.info("  🔮 VWAPAnalyzer: Institutional flow direction")
        logger.info("  🔮 TruthPredictor: Multi-indicator predictions (15/30/60min/EOD)")
        logger.info("  🔮 Accuracy tracking: Integrates with decision_history.py v4.9.0")
        logger.info("")
        logger.info("Previous Features:")
        logger.info("  ✅ Predictive Stop ENABLED (exit before stop hit)")
        logger.info("  ✅ Kalman Predictions in Health Score")
        logger.info("  ✅ Multi-Timeframe Analysis (weekly/daily trends)")
        logger.info("")
        logger.info("Aviation Systems:")
        logger.info(f"  ✈️ TCAS: TA={self.TCAS_TA_THRESHOLD} ATR, RA={self.TCAS_RA_THRESHOLD} ATR, ALIM={self.TCAS_ALIM_THRESHOLD} ATR")
        logger.info(f"  🛬 ILS: Phases at {self.ILS_OUTER_MARKER}/{self.ILS_MIDDLE_MARKER}/{self.ILS_INNER_MARKER}/{self.ILS_DECISION_HEIGHT}%")
        logger.info(f"  ❤️ Health: Critical={self.HEALTH_CRITICAL}, Unstable={self.HEALTH_UNSTABLE}")
        logger.info("")
        logger.info("Timing:")
        logger.info(f"  📊 Monitoring: Every {self.MONITORING_INTERVAL} seconds")
        logger.info(f"  🔄 Broker Sync: Every {self.BROKER_SYNC_INTERVAL // 60} minutes")
        logger.info(f"  🤖 ChatGPT: Every {self.CHATGPT_PERIODIC_INTERVAL // 60} minutes")
        logger.info("")
        logger.info(f"GTT Orders: {'ENABLED' if self.ENABLE_GTT else 'DISABLED'}")
        logger.info(f"Capital Manager: {'INTEGRATED' if self.capital_manager else 'Via Phase 3'}")
        logger.info(f"Predictive Stop: {'ENABLED' if self.predictive_stop else 'DISABLED'}")
        logger.info(f"TruthPredictor: {'ENABLED' if self.truth_predictor else 'DISABLED'}")
        logger.info("=" * 80)
    
    def set_orchestrator(self, orchestrator):
        """
        v4.10.0: Set orchestrator reference for position management.
        
        Called by orchestrator after both are initialized.
        Enables Phase 4 to access central positions dictionary.
        
        Args:
            orchestrator: TradingOrchestrator instance
        """
        self.orchestrator = orchestrator
        logger.info("✅ Phase 4: Orchestrator reference set - position sync enabled")

    # ═══════════════════════════════════════════════════════════════════════════
    # v4.13.0: DIRECTION-AWARE UTILITIES (LONG + SHORT Support)
    # ═══════════════════════════════════════════════════════════════════════════
    
    def _get_position_direction(self, position: Dict) -> str:
        """
        v4.13.0: Get position direction (LONG or SHORT).
        
        Returns:
            'LONG' (default) or 'SHORT'
        """
        return position.get('direction', 'LONG')
    
    def _calculate_pnl_pct(self, position: Dict, current_price: float) -> float:
        """
        v4.13.0: Calculate P&L percentage based on direction.
        
        LONG:  (current - entry) / entry * 100
        SHORT: (entry - current) / entry * 100
        """
        entry_price = position.get('entry_price', 0)
        if entry_price <= 0:
            return 0.0
        
        direction = self._get_position_direction(position)
        
        if direction == 'SHORT':
            return ((entry_price - current_price) / entry_price) * 100
        else:  # LONG
            return ((current_price - entry_price) / entry_price) * 100
    
    def _calculate_distance_to_stop(self, position: Dict, current_price: float) -> float:
        """
        v4.13.0: Calculate distance to stop (positive = safe, negative = breached).
        
        LONG:  current - stop (higher = safer)
        SHORT: stop - current (higher = safer)
        """
        stop_price = position.get('stop_price', 0)
        direction = self._get_position_direction(position)
        
        if direction == 'SHORT':
            return stop_price - current_price  # For SHORT, stop is above current
        else:  # LONG
            return current_price - stop_price  # For LONG, stop is below current
    
    def _calculate_distance_to_target(self, position: Dict, current_price: float) -> float:
        """
        v4.13.0: Calculate distance to target (positive = not yet reached).
        
        LONG:  target - current (positive = upside remaining)
        SHORT: current - target (positive = downside remaining)
        """
        target_price = position.get('target_price', 0)
        direction = self._get_position_direction(position)
        
        if direction == 'SHORT':
            return current_price - target_price  # For SHORT, target is below current
        else:  # LONG
            return target_price - current_price  # For LONG, target is above current
    
    def _calculate_progress_to_target(self, position: Dict, current_price: float) -> float:
        """
        v4.13.0: Calculate progress towards target as percentage (0-100+).
        
        LONG:  (current - entry) / (target - entry) * 100
        SHORT: (entry - current) / (entry - target) * 100
        """
        entry_price = position.get('entry_price', 0)
        target_price = position.get('target_price', 0)
        direction = self._get_position_direction(position)
        
        if direction == 'SHORT':
            total_distance = entry_price - target_price
            current_distance = entry_price - current_price
        else:  # LONG
            total_distance = target_price - entry_price
            current_distance = current_price - entry_price
        
        if total_distance <= 0:
            return 0.0
        
        return (current_distance / total_distance) * 100
    
    def _is_stop_hit(self, position: Dict, current_price: float) -> bool:
        """
        v4.13.0: Check if stop is hit based on direction.
        
        LONG:  current <= stop
        SHORT: current >= stop
        """
        stop_price = position.get('stop_price', 0)
        direction = self._get_position_direction(position)
        
        if direction == 'SHORT':
            return current_price >= stop_price
        else:  # LONG
            return current_price <= stop_price
    
    def _is_target_hit(self, position: Dict, current_price: float) -> bool:
        """
        v4.13.0: Check if target is hit based on direction.
        
        LONG:  current >= target
        SHORT: current <= target
        """
        target_price = position.get('target_price', 0)
        direction = self._get_position_direction(position)
        
        if direction == 'SHORT':
            return current_price <= target_price
        else:  # LONG
            return current_price >= target_price
    
    def _is_velocity_favorable(self, velocity: float, direction: str) -> bool:
        """
        v4.13.0: Check if Kalman velocity is favorable for position.
        
        LONG:  velocity > 0 (rising) is favorable
        SHORT: velocity < 0 (falling) is favorable
        """
        if direction == 'SHORT':
            return velocity < -0.01  # Falling is good for SHORT
        else:  # LONG
            return velocity > 0.01   # Rising is good for LONG
    
    def _is_approaching_stop(self, velocity: float, direction: str) -> bool:
        """
        v4.13.0: Check if price is moving towards stop.
        
        LONG:  velocity < 0 (falling towards stop below)
        SHORT: velocity > 0 (rising towards stop above)
        """
        if direction == 'SHORT':
            return velocity > 0.01   # Rising towards stop
        else:  # LONG
            return velocity < -0.01  # Falling towards stop
    
    def _get_exit_transaction_type(self, direction: str) -> str:
        """
        v4.13.0: Get exit transaction type.
        
        LONG:  SELL to exit
        SHORT: BUY to exit
        """
        return "BUY" if direction == 'SHORT' else "SELL"
    
    def _check_mis_mandatory_exit(self, position: Dict) -> Tuple[bool, str]:
        """
        v4.13.0: Check if MIS position needs mandatory exit.
        
        Returns:
            (should_exit, reason)
        """
        product = position.get('product', 'CNC')
        if product != 'MIS':
            return False, ""
        
        mandatory_exit_time = position.get('mandatory_exit_time')
        if not mandatory_exit_time:
            # Default MIS exit: 12:00 PM for Phase 5, 3:15 PM for others
            source = position.get('source', 'MANUAL')
            if source == 'PHASE5_GAP':
                mandatory_exit_time = dt_time(12, 0)
            else:
                mandatory_exit_time = dt_time(15, 15)
        
        # Convert if stored as string
        if isinstance(mandatory_exit_time, str):
            try:
                mandatory_exit_time = datetime.strptime(mandatory_exit_time, '%H:%M:%S').time()
            except:
                mandatory_exit_time = dt_time(12, 0)
        
        now = datetime.now()
        current_time = now.time()
        
        # Exit 5 minutes before mandatory time
        buffer_minutes = 5
        warning_time = datetime.combine(now.date(), mandatory_exit_time) - timedelta(minutes=buffer_minutes)
        
        if current_time >= warning_time.time():
            return True, f"MIS_MANDATORY_EXIT ({mandatory_exit_time.strftime('%H:%M')})"
        
        return False, ""

    # ═══════════════════════════════════════════════════════════════════════════
    # STARTUP & INITIALIZATION
    # ═══════════════════════════════════════════════════════════════════════════
    
    def startup_with_market_context(self, market_context: Dict = None):
        """
        Initialize Phase 4 with market context from Phase 1.
        
        Called by orchestrator after Phase 1 completes.
        
        Args:
            market_context: Market analysis from Phase 1
        """
        logger.info("🚀 Phase 4 Startup Beginning...")
        
        # Load market context
        if market_context:
            self.market_context = market_context
        else:
            self.market_context = self._load_market_context()
        
        logger.info(f"   Market Context: {self.market_context.get('chatgpt_market_opinion', {}).get('outlook', 'UNKNOWN')}")
        
        # Load existing positions
        self._load_positions()
        logger.info(f"   Loaded {len(self.positions)} existing positions")
        
        # Sync with broker
        self._sync_with_broker()
        
        # v4.15.0: Clean up orphan/duplicate GTTs at startup
        logger.info("   🧹 Running GTT orphan cleanup...")
        self._cleanup_all_orphan_gtts()
        
        # v4.15.0: Initialize volume baselines for V+P alerts
        logger.info("   📊 Initializing volume baselines for CNC positions...")
        self._init_volume_baselines()
        
        # Detect current regime
        self.current_regime = self._detect_market_regime()
        logger.info(f"   Market Regime: {self.current_regime.value}")
        
        # Initialize Kalman filters for open positions
        for symbol, position in self.positions.items():
            self._init_kalman_for_position(symbol, position)
        
        # Morning briefing with ChatGPT (if positions exist)
        if self.positions and self.chatgpt:
            self._run_morning_briefing()
        
        logger.info("✅ Phase 4 Startup Complete")
    
    def _load_market_context(self) -> Dict:
        """Load market context from Phase 1"""
        try:
            if os.path.exists(self.MARKET_CONTEXT_FILE):
                with open(self.MARKET_CONTEXT_FILE, 'r') as f:
                    return json.load(f)
        except Exception as e:
            logger.warning(f"Could not load market context: {e}")
        return {}
    
    # ═══════════════════════════════════════════════════════════════════════════
    # LIVE MARKET SENTIMENT (From Orchestrator ChatGPT Calls)
    # ═══════════════════════════════════════════════════════════════════════════
    
    def update_market_sentiment(self, sentiment: Dict):
        """
        Update live market sentiment from Orchestrator/Phase 2 ChatGPT calls.
        
        Called by Orchestrator whenever ChatGPT is consulted for:
        - Entry reviews
        - Adaptive scan decisions
        - Periodic market assessments
        
        This ensures Phase 4 has FRESH market context for exit decisions.
        
        Args:
            sentiment: Dict containing:
                - timestamp: When sentiment was generated
                - market_outlook: BULLISH/NEUTRAL/BEARISH
                - volatility: LOW/NORMAL/HIGH/EXTREME
                - trend_strength: WEAK/MODERATE/STRONG
                - risk_level: LOW/MEDIUM/HIGH/CRITICAL
                - nifty_trend: UP/DOWN/SIDEWAYS (optional)
                - sector_rotation: Dict of sector strengths (optional)
                - notes: Additional context
        """
        if not sentiment:
            return
            
        self.live_market_sentiment = {
            **sentiment,
            'received_at': datetime.now().isoformat()
        }
        
        logger.info(f"📡 Phase 4 received live market sentiment:")
        logger.info(f"   Outlook: {sentiment.get('market_outlook', 'UNKNOWN')}")
        logger.info(f"   Volatility: {sentiment.get('volatility', 'UNKNOWN')}")
        logger.info(f"   Risk Level: {sentiment.get('risk_level', 'UNKNOWN')}")
        
        # Adjust regime based on sentiment if volatility is extreme
        if sentiment.get('volatility') == 'EXTREME':
            self.current_regime = MarketRegime.HIGH_VOLATILITY
            logger.warning(f"⚠️ Regime adjusted to HIGH_VOLATILITY based on sentiment")
        elif sentiment.get('market_outlook') == 'BEARISH' and sentiment.get('risk_level') == 'HIGH':
            self.current_regime = MarketRegime.BEARISH
            logger.warning(f"⚠️ Regime adjusted to BEARISH based on sentiment")
    
    def get_combined_market_context(self) -> Dict:
        """
        Get combined market context (startup + live) for ChatGPT decisions.
        
        Returns merged context with live sentiment taking priority.
        """
        combined = {
            # Base context from Phase 1 (startup)
            'phase1_context': self.market_context,
            
            # Live sentiment from Orchestrator (fresher)
            'live_sentiment': self.live_market_sentiment,
            
            # Current regime
            'current_regime': self.current_regime.value if self.current_regime else 'UNKNOWN',
            
            # Derived fields (live takes priority)
            'market_outlook': self.live_market_sentiment.get('market_outlook') or 
                             self.market_context.get('chatgpt_market_opinion', {}).get('outlook', 'NEUTRAL'),
            'volatility': self.live_market_sentiment.get('volatility', 'NORMAL'),
            'risk_level': self.live_market_sentiment.get('risk_level', 'MEDIUM'),
            'trend_strength': self.live_market_sentiment.get('trend_strength', 'MODERATE'),
            
            # Freshness indicator
            'sentiment_age_seconds': self._get_sentiment_age_seconds()
        }
        return combined
    
    def _get_sentiment_age_seconds(self) -> int:
        """Get age of live sentiment in seconds"""
        if not self.live_market_sentiment.get('timestamp'):
            return 9999  # Very old / not available
        try:
            sentiment_time = datetime.fromisoformat(self.live_market_sentiment['timestamp'])
            return int((datetime.now() - sentiment_time).total_seconds())
        except:
            return 9999
    
    # ═══════════════════════════════════════════════════════════════════════════
    # v4.9.0: POSITION PROPERTY - DELEGATES TO ORCHESTRATOR (Single Source of Truth)
    # ═══════════════════════════════════════════════════════════════════════════
    
    @property
    def positions(self) -> Dict[str, Dict]:
        """
        Get positions dict - delegates to orchestrator if available.
        
        v4.9.0: Single Source of Truth implementation.
        
        This property delegates ALL position access to orchestrator._central_positions
        when orchestrator is set. Falls back to _local_positions for standalone use.
        
        Returns:
            Dict of symbol -> position data
        """
        if self.orchestrator and hasattr(self.orchestrator, 'get_all_positions'):
            # Delegate to orchestrator - include_closing=True to see EXIT_IN_PROGRESS
            return self.orchestrator.get_all_positions(include_closing=True)
        else:
            return self._local_positions
    
    @positions.setter
    def positions(self, value: Dict[str, Dict]):
        """
        Set positions dict - for backward compatibility.
        
        This setter is rarely used. Prefer using orchestrator's position API.
        """
        if self.orchestrator and hasattr(self.orchestrator, 'add_position'):
            logger.warning("⚠️ Direct positions assignment deprecated. Use orchestrator.add_position()")
            # Sync to orchestrator
            for symbol, pos_data in value.items():
                if not self.orchestrator.position_exists(symbol):
                    self.orchestrator.add_position(symbol, pos_data, source="PHASE4_DIRECT")
        else:
            self._local_positions = value
    
    def _get_position_direct(self, symbol: str) -> Optional[Dict]:
        """
        Get single position by symbol - for direct access.
        
        v4.9.0: Helper for consistent position access.
        
        Args:
            symbol: Stock symbol
            
        Returns:
            Position dict or None
        """
        if self.orchestrator and hasattr(self.orchestrator, 'get_position_by_symbol'):
            return self.orchestrator.get_position_by_symbol(symbol)
        else:
            return self._local_positions.get(symbol)
    
    def _set_position(self, symbol: str, position_data: Dict):
        """
        Set/update a position - for consistent writes.
        
        v4.9.0: Helper that notifies orchestrator of changes.
        
        Args:
            symbol: Stock symbol
            position_data: Position data dict
        """
        if self.orchestrator and hasattr(self.orchestrator, 'add_position'):
            if self.orchestrator.position_exists(symbol):
                # Update existing
                self.orchestrator.update_position(symbol, position_data)
            else:
                # Add new
                self.orchestrator.add_position(symbol, position_data, source="PHASE4")
        else:
            self._local_positions[symbol] = position_data
    
    def _delete_position(self, symbol: str, reason: str = "UNKNOWN", exit_price: float = 0):
        """
        Delete a position - for consistent deletion.
        
        v4.9.0: Helper that notifies orchestrator.
        
        Args:
            symbol: Stock symbol
            reason: Exit reason
            exit_price: Exit price for P&L
        """
        if self.orchestrator and hasattr(self.orchestrator, 'remove_position'):
            self.orchestrator.remove_position(symbol, reason, exit_price)
        else:
            if symbol in self._local_positions:
                del self._local_positions[symbol]
    
    def _position_exists(self, symbol: str) -> bool:
        """
        Check if position exists.
        
        v4.9.0: Helper for consistent existence check.
        
        Args:
            symbol: Stock symbol
            
        Returns:
            True if position exists
        """
        if self.orchestrator and hasattr(self.orchestrator, 'position_exists'):
            return self.orchestrator.position_exists(symbol)
        else:
            return symbol in self._local_positions
    
    def _load_positions(self):
        """
        Load positions from file (standalone mode only).
        
        v4.9.0: In normal operation, positions come from orchestrator.
        This method is only used for standalone Phase 4 testing.
        """
        # Skip file loading if orchestrator is managing positions
        if self.orchestrator and hasattr(self.orchestrator, 'get_all_positions'):
            logger.debug("📡 Phase 4: Positions managed by orchestrator, skipping file load")
            return
        
        try:
            if os.path.exists(self.POSITIONS_FILE):
                with open(self.POSITIONS_FILE, 'r') as f:
                    data = json.load(f)
                
                if isinstance(data, list):
                    # Convert list to dict by symbol
                    for pos in data:
                        if pos.get('status') == 'OPEN':
                            symbol = pos.get('symbol')
                            if symbol:
                                self._local_positions[symbol] = pos
                elif isinstance(data, dict):
                    self._local_positions = {k: v for k, v in data.items() if v.get('status') == 'OPEN'}
                    
        except Exception as e:
            logger.error(f"Error loading positions: {e}")
    
    def _save_positions(self):
        """
        Save positions to file.

        v5.4.0 FIX: Reads directly from orchestrator central store via
        get_positions_for_persistence() instead of self.positions property
        (which returns copies and was dropping all in-flight mutations).
        """
        try:
            os.makedirs(os.path.dirname(self.POSITIONS_FILE), exist_ok=True)

            # v5.4.0: Pull from orchestrator central store directly
            if self.orchestrator and hasattr(self.orchestrator, 'get_positions_for_persistence'):
                positions_list = self.orchestrator.get_positions_for_persistence()
            else:
                # Fallback for tests / standalone
                positions_list = list(self._local_positions.values()) if hasattr(self, '_local_positions') else []

            with open(self.POSITIONS_FILE, 'w') as f:
                json.dump(positions_list, f, indent=2, default=str)

        except Exception as e:
            logger.error(f"Error saving positions: {e}")

    def _update_position(self, symbol: str, position: Dict, **fields) -> None:
        """
        v5.4.0: Persist position field updates through orchestrator.

        This is the ONLY correct way to mutate position fields in Phase 4.
        Direct dict mutations (position['x'] = y) are silently dropped because
        self.positions returns fresh copies from orchestrator central store.

        This helper:
          1. Updates the local copy for in-method read consistency
          2. Persists to orchestrator central store for cross-cycle durability

        Usage:
            self._update_position(symbol, position,
                                  stop_price=new_stop,
                                  tier1_trailing_active=True)

        Args:
            symbol: Stock symbol (required for orchestrator lookup)
            position: Local position dict reference (updated in place)
            **fields: Field name -> value pairs to persist
        """
        # 1. Update local copy for in-method consistency
        for key, value in fields.items():
            position[key] = value

        # 2. Persist to orchestrator central store
        if self.orchestrator and hasattr(self.orchestrator, 'update_position_fields'):
            self.orchestrator.update_position_fields(symbol, fields)

    # ═══════════════════════════════════════════════════════════════════════════
    # BROKER SYNC (v4.3.1: Uses centralized BrokerSyncManager)
    # ═══════════════════════════════════════════════════════════════════════════
    
    def _sync_with_broker(self) -> int:
        """
        Synchronize positions with broker using centralized BrokerSyncManager.

        v4.3.1 REFACTOR: Now uses broker_sync utility instead of direct kite calls.
        This ensures consistent position fetching across all system components.

        Returns:
            int: Number of positions at broker
        """
        # PAPER MODE FIX: skip broker sync entirely — paper positions don't exist at the real
        # broker, so reconcile() would always mark them as 'closed_positions' and ghost-kill them.
        if getattr(self.config, 'MASTER_PAPER_MODE', False):
            logger.debug("🔄 Phase 4: broker sync SKIPPED (MASTER_PAPER_MODE=True)")
            return len(self.positions)

        logger.info("🔄 Phase 4: Syncing with broker...")
        
        try:
            # ═══════════════════════════════════════════════════════════════
            # Use centralized broker_sync if available
            # ═══════════════════════════════════════════════════════════════
            
            if self.broker_sync:
                # Use centralized reconcile method
                result = self.broker_sync.reconcile(self.positions)
                
                # Handle positions closed outside system (GTT triggered?)
                for symbol in result.closed_positions:
                    logger.warning(f"   ⚠️ {symbol}: Not at broker - marking as CLOSED")
                    self._handle_external_close(symbol)
                
                # Add new/untracked positions
                for symbol, broker_pos in result.new_positions.items():
                    logger.info(f"   ➕ {symbol}: Found untracked position - adding to monitoring")
                    self._add_manual_position(symbol, broker_pos.to_dict())
                
                # Update current prices for matched positions
                # v5.4.0 FIX: Persist through orchestrator (was writing to throwaway copies)
                for symbol, broker_pos in result.matched_positions.items():
                    if symbol in self.positions:
                        if self.orchestrator and hasattr(self.orchestrator, 'update_position_fields'):
                            self.orchestrator.update_position_fields(symbol, {
                                'current_price': broker_pos.last_price,
                                'broker_pnl': broker_pos.pnl
                            })
                
                self.last_broker_sync = datetime.now()
                total_at_broker = len(result.broker_positions)
                logger.info(f"   ✅ Sync complete: {len(self.positions)} positions tracked")
                
                # v4.7.1 FIX-02: Reconcile GTT orders for recovered/new positions
                # Check if any positions need GTT reconciliation (PENDING_RECONCILIATION or just added)
                needs_reconciliation = any(
                    pos.get('gtt_protected') == 'PENDING_RECONCILIATION' or pos.get('recovered_from_broker')
                    for pos in self.positions.values()
                )
                if needs_reconciliation:
                    logger.info("   🔄 Running GTT reconciliation for recovered positions...")
                    self._reconcile_gtts_on_startup()
                
                return total_at_broker
            
            else:
                # ═══════════════════════════════════════════════════════════
                # Fallback: Direct kite API calls (if broker_sync not available)
                # ═══════════════════════════════════════════════════════════
                
                logger.warning("   ⚠️ broker_sync not available, using fallback")
                return self._sync_with_broker_fallback()
                
        except Exception as e:
            logger.error(f"❌ Broker sync failed: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return 0
    
    def _sync_with_broker_fallback(self) -> int:
        """
        Fallback broker sync using direct kite API calls.
        Used when centralized broker_sync is not available.
        
        Returns:
            int: Number of positions at broker
        """
        broker_holdings = {}
        
        # STEP 1: Fetch INTRADAY/F&O positions (MIS, NRML)
        try:
            broker_positions = self.kite.positions()
            net_positions = broker_positions.get('net', [])
            
            for pos in net_positions:
                qty = pos.get('quantity', 0)
                if qty != 0:
                    symbol = pos.get('tradingsymbol')
                    broker_holdings[symbol] = {
                        'quantity': abs(qty),
                        'average_price': pos.get('average_price', 0),
                        'last_price': pos.get('last_price', 0),
                        'pnl': pos.get('pnl', 0),
                        'product': pos.get('product', 'MIS'),
                        'source': 'POSITIONS',
                        'direction': 'LONG' if qty > 0 else 'SHORT'
                    }
                    
        except Exception as e:
            logger.warning(f"   ⚠️ Could not fetch positions: {e}")
        
        # STEP 2: Fetch DELIVERY holdings (CNC)
        try:
            holdings = self.kite.holdings()
            
            for holding in holdings:
                qty = holding.get('quantity', 0)
                t1_qty = holding.get('t1_quantity', 0)
                total_qty = qty + t1_qty
                
                if total_qty > 0:
                    symbol = holding.get('tradingsymbol')
                    
                    if symbol in broker_holdings:
                        continue
                    
                    broker_holdings[symbol] = {
                        'quantity': total_qty,
                        'quantity_settled': qty,
                        'quantity_t1': t1_qty,
                        'average_price': holding.get('average_price', 0),
                        'last_price': holding.get('last_price', 0),
                        'pnl': holding.get('pnl', 0),
                        'product': 'CNC',
                        'source': 'HOLDINGS',
                        'direction': 'LONG',
                        'isin': holding.get('isin', ''),
                        'collateral_quantity': holding.get('collateral_quantity', 0)
                    }
                    
        except Exception as e:
            logger.warning(f"   ⚠️ Could not fetch holdings: {e}")
        
        # STEP 3: Reconcile
        for symbol in list(self.positions.keys()):
            if symbol not in broker_holdings:
                logger.warning(f"   ⚠️ {symbol}: Not at broker - marking as CLOSED")
                self._handle_external_close(symbol)
        
        for symbol, broker_pos in broker_holdings.items():
            if symbol not in self.positions:
                logger.info(f"   ➕ {symbol}: Found untracked position - adding to monitoring")
                self._add_manual_position(symbol, broker_pos)
            else:
                # v5.4.0 FIX: Persist through orchestrator
                if self.orchestrator and hasattr(self.orchestrator, 'update_position_fields'):
                    self.orchestrator.update_position_fields(symbol, {
                        'current_price': broker_pos['last_price'],
                        'broker_pnl': broker_pos['pnl']
                    })
        
        self.last_broker_sync = datetime.now()
        logger.info(f"   ✅ Sync complete: {len(self.positions)} positions tracked")
        
        return len(broker_holdings)
    
    def _handle_external_close(self, symbol: str):
        """
        Handle position closed outside system (e.g., GTT triggered).
        
        v5.3.2 FIX: Now notifies orchestrator to clean _central_positions
        and prevents ghost position re-monitoring via _closed_externally_today.
        """
        position = self.positions.get(symbol)
        if not position:
            return
        
        entry_price = position.get('entry_price', 0)
        stop_price = position.get('stop_price', 0)
        
        # Mark as closed
        self._update_position(symbol, position,
                              status='CLOSED',
                              exit_time=datetime.now().isoformat(),
                              exit_reason=ExitReason.GTT_TRIGGERED.value)

        logger.warning(f"   🎯 {symbol}: EXTERNALLY CLOSED — removing from ALL tracking")
        
        # v5.3.2 FIX-A: Track in closed set to prevent ghost re-monitoring
        if not hasattr(self, '_closed_externally_today'):
            self._closed_externally_today = set()
        self._closed_externally_today.add(symbol)
        
        # v5.3.2 FIX-B: Notify orchestrator to clean _central_positions + _exited_today
        # This is the KEY fix — without this, the orchestrator never knows the position is gone
        if self.orchestrator and hasattr(self.orchestrator, 'on_position_closed'):
            try:
                exit_price = stop_price if stop_price > 0 else entry_price
                self.orchestrator.on_position_closed(
                    symbol, 
                    reason='GTT_TRIGGERED_EXTERNAL', 
                    exit_price=exit_price
                )
                logger.info(f"   ✅ {symbol}: Orchestrator notified — cleaned from _central_positions + _exited_today")
            except Exception as e:
                logger.error(f"   ❌ {symbol}: Orchestrator notification failed: {e}")
                # Fallback: try remove_position
                if hasattr(self.orchestrator, 'remove_position'):
                    try:
                        self.orchestrator.remove_position(symbol, 'GTT_TRIGGERED_EXTERNAL', stop_price)
                    except:
                        pass
        
        # v5.3.2 FIX-C: Clean Kalman filters for this symbol
        if hasattr(self, 'kalman_filters') and symbol in self.kalman_filters:
            del self.kalman_filters[symbol]
        if hasattr(self, 'failed_exit_attempts') and symbol in self.failed_exit_attempts:
            del self.failed_exit_attempts[symbol]
        
        # Notify user
        if self.telegram:
            self.telegram.send_message(
                f"🎯 POSITION CLOSED (External)\n\n"
                f"Stock: {symbol}\n"
                f"Likely: GTT Order Triggered\n"
                f"Check broker for details\n\n"
                f"✅ Removed from ALL monitoring"
            )
        
        # Remove from active tracking (LAST — after all notifications)
        del self.positions[symbol]
    
    def _add_manual_position(self, symbol: str, broker_pos: Dict):
        """
        Add manually opened / untracked position to monitoring.
        
        Handles both:
        - MIS/NRML positions (from kite.positions())
        - CNC holdings (from kite.holdings())
        
        Applies conservative default stop/target and starts TCAS/ILS monitoring.
        """
        entry_price = broker_pos['average_price']
        quantity = broker_pos['quantity']
        product = broker_pos.get('product', 'CNC')
        source = broker_pos.get('source', 'UNKNOWN')
        current_price = broker_pos.get('last_price', entry_price)
        current_pnl = broker_pos.get('pnl', 0)
        direction = broker_pos.get('direction', 'LONG')
        
        # v4.13.0 FIX: Direction-aware P&L calculation
        if entry_price > 0:
            if direction == 'SHORT':
                pnl_pct = ((entry_price - current_price) / entry_price) * 100
            else:
                pnl_pct = ((current_price - entry_price) / entry_price) * 100
        else:
            pnl_pct = 0
        
        # T+1 handling for holdings
        t1_qty = broker_pos.get('quantity_t1', 0)
        settled_qty = broker_pos.get('quantity_settled', quantity)
        
        # Create position record
        position = {
            'symbol': symbol,
            'quantity': quantity,
            'quantity_settled': settled_qty,
            'quantity_t1': t1_qty,
            'entry_price': entry_price,
            'current_price': current_price,
            'entry_time': datetime.now().isoformat(),
            'entry_value': entry_price * quantity,
            
            # v4.14.0 FIX-A: Direction-aware stop/target
            # LONG:  stop below entry, target above
            # SHORT: stop above entry, target below
            'target_price': entry_price * 0.97 if direction == 'SHORT' else entry_price * 1.03,
            'stop_price': entry_price * 1.02 if direction == 'SHORT' else entry_price * 0.98,
            'target_pct': 3.0,
            'stop_pct': 2.0,
            
            'status': 'OPEN',
            'state': 'OPEN',  # v4.10.0: Add state for orchestrator
            'product': product,
            'direction': direction,  # v4.13.0: Use extracted direction
            'manual_entry': True,
            'broker_source': source,  # POSITIONS or HOLDINGS
            
            # Phase 4 tracking
            'phase4_tracking': {
                'tcas_status': TCASStatus().to_dict(),
                'ils_status': ILSStatus().to_dict(),
                'health_score': HealthScore().to_dict(),
                'kalman_state': KalmanState().to_dict(),
                'chatgpt_consultations': []
            }
        }
        
        # v4.10.0 FIX: Properly add to orchestrator's central positions
        if self.orchestrator and hasattr(self.orchestrator, 'add_position'):
            self.orchestrator.add_position(symbol, position, source=f"PHASE4_MANUAL_{source}")
            logger.debug(f"   📡 {symbol}: Added to orchestrator central positions")
        else:
            # Fallback to local positions
            self._local_positions[symbol] = position
            logger.debug(f"   📦 {symbol}: Added to local positions (no orchestrator)")
        
        # Initialize Kalman
        self._init_kalman_for_position(symbol, position)
        
        # ═══════════════════════════════════════════════════════════════════
        # v4.14.0 PERMANENT FIX: Fetch REAL ATR from historical data
        # Replaces the blind 2% estimate that caused false TCAS ALIMs
        # ═══════════════════════════════════════════════════════════════════
        real_atr = self._fetch_real_atr(symbol, current_price)
        position['atr'] = real_atr
        logger.info(f"   📊 {symbol}: ATR = ₹{real_atr:.2f} ({real_atr/current_price*100:.1f}% of price)")
        
        # ═══════════════════════════════════════════════════════════════════
        # v4.11.0: Generate and record truth predictions at entry
        # ═══════════════════════════════════════════════════════════════════
        self._record_entry_predictions(symbol, position)
        
        # ═══════════════════════════════════════════════════════════════════
        # v4.12.0: Generate comprehensive flight plan at entry
        # ═══════════════════════════════════════════════════════════════════
        self._generate_and_log_flight_plan(symbol, position)
        
        # Place GTT if enabled (only for sellable quantity, not T+1)
        # v4.8.2 FIX: Cancel-before-place — always place fresh GTTs with current stop/target levels
        # Old bug: _check_existing_gtt_for_symbol used wrong field path, never found existing GTTs,
        #          so new GTTs were placed on every restart → duplicates accumulated
        # PAPER MODE FIX: skip real GTT ops for paper positions
        _is_paper = position.get('is_paper_trade', False) or getattr(self.config, 'MASTER_PAPER_MODE', False)
        if self.ENABLE_GTT and settled_qty > 0 and not _is_paper:
            existing_gtt = self._check_existing_gtt_for_symbol(symbol)
            
            # v4.8.2: Cancel ALL existing GTTs for this symbol before placing new ones
            # This ensures clean state: exactly 1 stop + 1 target per position
            if existing_gtt and existing_gtt.get('all_ids'):
                cancelled = 0
                for old_gtt_id in existing_gtt['all_ids']:
                    try:
                        self._cancel_gtt(old_gtt_id)
                        cancelled += 1
                    except Exception as e:
                        logger.warning(f"   ⚠️ {symbol}: Failed to cancel old GTT #{old_gtt_id}: {e}")
                if cancelled > 0:
                    logger.info(f"   🧹 {symbol}: Cancelled {cancelled} old GTT(s) — placing fresh pair")
            
            # Place fresh GTT pair with current stop/target levels
            gtt_position = position.copy()
            gtt_position['quantity'] = settled_qty
            gtt_result = self._place_gtt_orders(symbol, gtt_position)
            
            if gtt_result and gtt_result.get('stop_id'):
                position['gtt_stop_id'] = gtt_result['stop_id']
                position['gtt_target_id'] = gtt_result.get('target_id')
                position['gtt_protected'] = True
                position['gtt_active'] = True
            else:
                position['gtt_protected'] = False
                position['gtt_active'] = False
                logger.warning(f"   ⚠️ {symbol}: GTT placement failed — position UNPROTECTED")
            
            if t1_qty > 0:
                logger.info(f"   ⚠️ {symbol}: GTT covers {settled_qty} settled shares only (T+1: {t1_qty} pending)")
        
        # Log and notify
        source_emoji = "📊" if source == 'POSITIONS' else "📦"
        pnl_emoji = "🟢" if pnl_pct > 0 else "🔴" if pnl_pct < 0 else "⚪"
        
        logger.info(f"   {source_emoji} {pnl_emoji} Added {symbol} to Phase 4 monitoring:")
        logger.info(f"      Entry: ₹{entry_price:.2f} | Current: ₹{current_price:.2f} | P&L: {pnl_pct:+.2f}%")
        logger.info(f"      Qty: {quantity} ({product}) | Stop: ₹{position['stop_price']:.2f} | Target: ₹{position['target_price']:.2f}")
        
        if self.telegram:
            t1_note = f"\nT+1 Pending: {t1_qty} shares" if t1_qty > 0 else ""
            self.telegram.send_message(
                f"📡 POSITION DETECTED & MONITORING\n\n"
                f"Stock: {symbol}\n"
                f"Source: {source} ({product})\n"
                f"Qty: {quantity}{t1_note}\n"
                f"Entry: ₹{entry_price:.2f}\n"
                f"Current: ₹{current_price:.2f}\n"
                f"P&L: {pnl_pct:+.2f}%\n\n"
                f"🎯 Target: ₹{position['target_price']:.2f} (+3%)\n"
                f"🛑 Stop: ₹{position['stop_price']:.2f} (-2%)\n\n"
                f"Phase 4 TCAS/ILS monitoring ACTIVE"
            )

    # ═══════════════════════════════════════════════════════════════════════════
    # v4.14.0: REAL ATR CALCULATION
    # ═══════════════════════════════════════════════════════════════════════════
    
    def _fetch_real_atr(self, symbol: str, current_price: float, period: int = 14) -> float:
        """
        Fetch real ATR from historical daily candles.
        
        v4.14.0 PERMANENT FIX: Replaces the blind `current_price * 0.02` estimate
        that caused false TCAS ALIMs on adopted positions.
        
        Returns:
            float: Actual ATR value, or conservative fallback (2% of price)
        """
        fallback_atr = current_price * 0.02
        
        if not self.kite:
            logger.debug(f"   {symbol}: No kite API - using ATR fallback ₹{fallback_atr:.2f}")
            return fallback_atr
        
        try:
            # Get instrument token
            instrument_token = None
            try:
                instruments = self.kite.instruments('NSE')
                for inst in instruments:
                    if inst['tradingsymbol'] == symbol:
                        instrument_token = inst['instrument_token']
                        break
            except Exception:
                pass
            
            if not instrument_token:
                logger.debug(f"   {symbol}: Instrument token not found - using ATR fallback")
                return fallback_atr
            
            # Fetch 20 daily candles (need period+1 for TR calculation)
            from_date = datetime.now() - timedelta(days=45)  # Extra buffer for weekends/holidays
            to_date = datetime.now()
            
            candles = self.kite.historical_data(
                instrument_token=instrument_token,
                from_date=from_date,
                to_date=to_date,
                interval='day'
            )
            
            if not candles or len(candles) < period + 1:
                logger.debug(f"   {symbol}: Only {len(candles) if candles else 0} candles - using ATR fallback")
                return fallback_atr
            
            # Calculate True Range for last `period` candles
            true_ranges = []
            for i in range(1, min(period + 1, len(candles))):
                high = candles[i]['high']
                low = candles[i]['low']
                prev_close = candles[i - 1]['close']
                
                tr = max(
                    high - low,
                    abs(high - prev_close),
                    abs(low - prev_close)
                )
                true_ranges.append(tr)
            
            if not true_ranges:
                return fallback_atr
            
            atr = sum(true_ranges) / len(true_ranges)
            
            # Sanity check: ATR should be 0.5% - 8% of price
            # If outside this range, something is wrong with the data
            atr_pct = atr / current_price * 100
            if atr_pct < 0.5 or atr_pct > 8.0:
                logger.warning(f"   {symbol}: ATR ₹{atr:.2f} ({atr_pct:.1f}%) outside sane range - clamping")
                atr = max(current_price * 0.005, min(current_price * 0.08, atr))
            
            return round(atr, 2)
            
        except Exception as e:
            logger.warning(f"   {symbol}: ATR fetch failed ({e}) - using fallback ₹{fallback_atr:.2f}")
            return fallback_atr

    # ═══════════════════════════════════════════════════════════════════════════
    # v4.13.0: PHASE 5 POSITION HANDOFF
    # ═══════════════════════════════════════════════════════════════════════════
    
    def add_phase5_position(self, position_data: Dict) -> bool:
        """
        v4.13.0: Add position from Phase 5 Gap Strategy for monitoring.
        
        Phase 5 handles entry (scan → analyze → approve → enter).
        Phase 4 handles monitoring (TCAS/ILS/Kalman → exit).
        
        Required fields in position_data:
            symbol: Stock symbol
            entry_price: Entry fill price
            quantity: Number of shares
            direction: 'LONG' or 'SHORT'
            product: 'MIS' (always for Phase 5)
            
        Optional fields:
            stop_price: Phase 4 will calculate if not provided
            target_price: Phase 4 will calculate if not provided
            mandatory_exit_time: Default 12:00 PM for Phase 5
            gap_pct: Gap percentage (for logging)
            volume_burst_score: Volume Burst Score (for logging)
            flight_plan: Flight plan data from Phase 5
            
        Returns:
            True if position added successfully
        """
        symbol = position_data.get('symbol')
        if not symbol:
            logger.error("Phase 5 handoff: Missing symbol!")
            return False
        
        entry_price = position_data.get('entry_price', 0)
        quantity = position_data.get('quantity', 0)
        direction = position_data.get('direction', 'LONG')
        product = position_data.get('product', 'MIS')
        
        if entry_price <= 0 or quantity <= 0:
            logger.error(f"Phase 5 handoff: Invalid entry_price={entry_price} or quantity={quantity}")
            return False
        
        logger.info(f"📥 PHASE 5 HANDOFF: {symbol}")
        logger.info(f"   Direction: {direction} | Entry: ₹{entry_price:.2f} | Qty: {quantity}")
        logger.info(f"   🏎️ Monitoring: TIER_1 | Exit Mode: FAST_TECHNICAL | Max Hold: {position_data.get('max_hold_minutes', 60)}min")
        
        # Calculate stop/target if not provided
        # v5.4.0: Warn if Phase 5 didn't supply ATR-based stop — fallback diverges from PH5 formula
        if 'stop_price' not in position_data:
            logger.warning(
                f"⚠️ {symbol}: PH5 handoff missing 'stop_price' — using 1.5% flat fallback. "
                f"This diverges from PH5's ATR-based stop and may produce inconsistent risk."
            )
        if 'target_price' not in position_data:
            logger.warning(
                f"⚠️ {symbol}: PH5 handoff missing 'target_price' — using 3% flat fallback."
            )
        if direction == 'SHORT':
            # SHORT: stop above entry, target below entry
            stop_price = position_data.get('stop_price', entry_price * 1.015)   # 1.5% above
            target_price = position_data.get('target_price', entry_price * 0.97)  # 3% below
        else:
            # LONG: stop below entry, target above entry
            stop_price = position_data.get('stop_price', entry_price * 0.985)   # 1.5% below
            target_price = position_data.get('target_price', entry_price * 1.03)  # 3% above
        
        # Round to tick size (0.10 covers all NSE instruments)
        stop_price = round(stop_price * 10) / 10
        target_price = round(target_price * 10) / 10
        
        # Create position record
        position = {
            'symbol': symbol,
            'entry_price': entry_price,
            'current_price': entry_price,
            'quantity': quantity,
            'product': product,
            'direction': direction,
            'source': position_data.get('source', 'PHASE5_GAP'),
            'stop_price': stop_price,
            'target_price': target_price,
            'mandatory_exit_time': position_data.get('mandatory_exit_time', dt_time(12, 0)),
            'entry_time': position_data.get('entry_time', datetime.now().isoformat()),
            'status': 'OPEN',
            
            # v4.14.0: Tier 1 monitoring instructions
            'monitoring_tier': position_data.get('monitoring_tier', 'TIER_1'),
            'exit_mode': position_data.get('exit_mode', 'FAST_TECHNICAL'),
            'max_hold_minutes': position_data.get('max_hold_minutes', 60),
            'atr': position_data.get('atr', 0),  # ATR from Phase 5 for predictive stop
            
            # v5.3.3: Smart TCAS Scalp Design fields
            'smart_tcas_enabled': position_data.get('smart_tcas_enabled', False),
            'tcas_activation_pct': position_data.get('tcas_activation_pct', 0.3),
            'tcas_activation_price': position_data.get('tcas_activation_price', 0),
            'breakeven_trail_time': position_data.get('breakeven_trail_time', None),
            'hard_exit_time': position_data.get('hard_exit_time', None),
            
            # Phase 5 metadata
            'gap_pct': position_data.get('gap_pct', 0),
            'volume_burst_score': position_data.get('volume_burst_score', 0),
            'sentiment': position_data.get('sentiment', 'NEUTRAL'),
            'chatgpt_approval': position_data.get('chatgpt_approval', {}),
            
            # Phase 4 tracking
            'phase4_tracking': {
                'tcas_status': TCASStatus().to_dict(),
                'ils_status': ILSStatus().to_dict(),
                'health_score': HealthScore(total_score=100.0, interpretation="HEALTHY").to_dict(),
                'kalman_state': KalmanState().to_dict(),
                'last_update': datetime.now().isoformat(),
                'chatgpt_consultations': [],
                'alerts_history': [],
                'phase5_flight_plan': position_data.get('flight_plan', {})
            }
        }
        
        # Add to orchestrator's central positions
        if self.orchestrator and hasattr(self.orchestrator, 'add_position'):
            self.orchestrator.add_position(symbol, position, source=position_data.get('source', 'PHASE5_GAP'))
            logger.info(f"   📡 Added to orchestrator central positions")
        else:
            # Fallback to local positions
            self.positions[symbol] = position
            logger.info(f"   📦 Added to local positions (no orchestrator)")
        
        # Initialize Kalman filter
        self._init_kalman_for_position(symbol, position)

        # ── ATR SANITY OVERRIDE ──────────────────────────────────────────────
        # PH5A sends daily ATR now, but guard against any upstream sending
        # an intraday ATR again (15-min, 1-min). If the ATR is outside the
        # realistic 0.5%–8% band for this stock's price, recalculate from
        # daily candles using our own validated fetcher.
        inherited_atr = position.get('atr', 0)
        if inherited_atr > 0:
            atr_pct = (inherited_atr / entry_price) * 100
            if atr_pct < 0.5 or atr_pct > 8.0:
                logger.warning(
                    f"   ⚠️ {symbol}: Inherited ATR ₹{inherited_atr:.2f} ({atr_pct:.1f}%) "
                    f"outside sane range — recalculating from daily candles"
                )
                position['atr'] = self._fetch_real_atr(symbol, entry_price)
                logger.info(f"   📊 {symbol}: ATR corrected to ₹{position['atr']:.2f} "
                            f"({position['atr']/entry_price*100:.1f}% of price)")
        else:
            position['atr'] = self._fetch_real_atr(symbol, entry_price)
            logger.info(f"   📊 {symbol}: ATR set to ₹{position['atr']:.2f} "
                        f"({position['atr']/entry_price*100:.1f}% of price)")

        # Place GTT orders (direction-aware)
        # v4.8.2 FIX: Cancel-before-place (prevents duplicates across restarts)
        # PAPER MODE FIX: skip real GTT ops for paper positions
        _is_paper = position.get('is_paper_trade', False) or getattr(self.config, 'MASTER_PAPER_MODE', False)
        if self.ENABLE_GTT and not _is_paper:
            existing_gtt = self._check_existing_gtt_for_symbol(symbol)

            # Cancel existing GTTs before placing fresh ones
            if existing_gtt and existing_gtt.get('all_ids'):
                cancelled = 0
                for old_gtt_id in existing_gtt['all_ids']:
                    try:
                        self._cancel_gtt(old_gtt_id)
                        cancelled += 1
                    except Exception as e:
                        logger.warning(f"   ⚠️ {symbol}: Failed to cancel old GTT #{old_gtt_id}: {e}")
                if cancelled > 0:
                    logger.info(f"   🧹 {symbol}: Cancelled {cancelled} old GTT(s) — placing fresh pair")
            
            gtt_result = self._place_gtt_orders(symbol, position)
            if gtt_result and gtt_result.get('stop_id'):
                position['gtt_stop_id'] = gtt_result['stop_id']
                position['gtt_target_id'] = gtt_result.get('target_id')
                position['gtt_protected'] = True
                position['gtt_active'] = True
            else:
                position['gtt_protected'] = False
                position['gtt_active'] = False
                logger.warning(f"   ⚠️ GTT placement failed — position UNPROTECTED")
        
        # Save positions
        self._save_positions()
        
        # Log summary
        exit_time = position.get('mandatory_exit_time', dt_time(12, 0))
        if isinstance(exit_time, dt_time):
            exit_time_str = exit_time.strftime('%H:%M')
        else:
            exit_time_str = str(exit_time)
        
        logger.info(f"   ✅ PHASE 5 HANDOFF COMPLETE")
        logger.info(f"      Direction: {direction}")
        logger.info(f"      Stop: ₹{stop_price:.2f} | Target: ₹{target_price:.2f}")
        logger.info(f"      Mandatory Exit: {exit_time_str}")
        logger.info(f"      TCAS/ILS monitoring ACTIVE")
        
        # Telegram notification
        if self.telegram:
            self.telegram.send_message(
                f"📥 PHASE 5 → PHASE 4 HANDOFF\n\n"
                f"Stock: {symbol}\n"
                f"Direction: {direction}\n"
                f"Entry: ₹{entry_price:.2f}\n"
                f"Qty: {quantity} ({product})\n\n"
                f"🎯 Target: ₹{target_price:.2f}\n"
                f"🛑 Stop: ₹{stop_price:.2f}\n"
                f"⏰ Max Exit: {exit_time_str}\n\n"
                f"Gap: {position_data.get('gap_pct', 0):.2f}%\n"
                f"Volume Score: {position_data.get('volume_burst_score', 0)}/100\n\n"
                f"Phase 4 TCAS/ILS monitoring ACTIVE"
            )
        
        return True

    # ═══════════════════════════════════════════════════════════════════════════
    # MARKET REGIME DETECTION
    # ═══════════════════════════════════════════════════════════════════════════
    
    # ═══════════════════════════════════════════════════════════════════════════
    # v4.15.0: NSE MARKET CONTEXT FOR CNC SWING DECISIONS
    # ═══════════════════════════════════════════════════════════════════════════
    
    def _fetch_nse_market_context(self) -> Dict:
        """
        v4.15.0: Fetch comprehensive NSE market data for ChatGPT CNC decisions.
        
        Returns NIFTY trend, India VIX, FII/DII flows, market breadth.
        Called once per TIER_2 cycle (every 60 min for CNC positions).
        """
        result = {
            'nifty': {},
            'vix': {},
            'breadth': {},
            'fii_dii': {},
            'market_mood': 'UNKNOWN'
        }
        
        try:
            # ─── NIFTY 50 ───
            nifty_quote = self.kite.quote(['NSE:NIFTY 50'])
            nifty_data = nifty_quote.get('NSE:NIFTY 50', {})
            nifty_price = nifty_data.get('last_price', 0)
            nifty_close = nifty_data.get('ohlc', {}).get('close', nifty_price)
            nifty_open = nifty_data.get('ohlc', {}).get('open', nifty_price)
            nifty_change = nifty_data.get('change', 0)
            nifty_change_pct = (nifty_change / nifty_close * 100) if nifty_close > 0 else 0
            
            # Intraday trend from open
            if nifty_price > nifty_open * 1.003:
                nifty_intraday_trend = "BULLISH"
            elif nifty_price < nifty_open * 0.997:
                nifty_intraday_trend = "BEARISH"
            else:
                nifty_intraday_trend = "FLAT"
            
            result['nifty'] = {
                'level': round(nifty_price, 2),
                'change_pct': round(nifty_change_pct, 2),
                'intraday_trend': nifty_intraday_trend,
                'day_high': nifty_data.get('ohlc', {}).get('high', 0),
                'day_low': nifty_data.get('ohlc', {}).get('low', 0)
            }
            
            # ─── INDIA VIX ───
            vix_quote = self.kite.quote(['NSE:INDIA VIX'])
            vix_data = vix_quote.get('NSE:INDIA VIX', {})
            vix_value = vix_data.get('last_price', 15)
            vix_prev_close = vix_data.get('ohlc', {}).get('close', vix_value)
            vix_change_pct = ((vix_value - vix_prev_close) / vix_prev_close * 100) if vix_prev_close > 0 else 0
            
            if vix_value < 13:
                vix_interpretation = "LOW (Calm market, complacency)"
            elif vix_value < 17:
                vix_interpretation = "NORMAL (Healthy volatility)"
            elif vix_value < 22:
                vix_interpretation = "ELEVATED (Caution warranted)"
            else:
                vix_interpretation = "HIGH (Fear/panic in market)"
            
            result['vix'] = {
                'value': round(vix_value, 2),
                'change_pct': round(vix_change_pct, 2),
                'interpretation': vix_interpretation
            }
            
            # ─── MARKET BREADTH (Advance/Decline from NIFTY 50 components) ───
            try:
                # Quick breadth: check NIFTY 50 stocks advancing vs declining
                nifty_instruments = [
                    'RELIANCE', 'TCS', 'HDFCBANK', 'INFY', 'ICICIBANK',
                    'HINDUNILVR', 'ITC', 'SBIN', 'BHARTIARTL', 'KOTAKBANK',
                    'LT', 'AXISBANK', 'BAJFINANCE', 'MARUTI', 'TITAN',
                    'SUNPHARMA', 'NTPC', 'TATAMOTORS', 'POWERGRID', 'ULTRACEMCO'
                ]
                breadth_quotes = self.kite.quote([f"NSE:{s}" for s in nifty_instruments])
                
                advancing = 0
                declining = 0
                for sym in nifty_instruments:
                    q = breadth_quotes.get(f"NSE:{sym}", {})
                    change = q.get('change', 0)
                    if change > 0:
                        advancing += 1
                    elif change < 0:
                        declining += 1
                
                total = advancing + declining
                breadth_ratio = advancing / total if total > 0 else 0.5
                
                if breadth_ratio > 0.65:
                    breadth_interpretation = "BROAD RALLY (most stocks up)"
                elif breadth_ratio > 0.5:
                    breadth_interpretation = "MILD POSITIVE (slight majority up)"
                elif breadth_ratio > 0.35:
                    breadth_interpretation = "MILD NEGATIVE (slight majority down)"
                else:
                    breadth_interpretation = "BROAD SELLOFF (most stocks down)"
                
                result['breadth'] = {
                    'advancing': advancing,
                    'declining': declining,
                    'ratio': round(breadth_ratio, 2),
                    'interpretation': breadth_interpretation
                }
            except Exception as e:
                logger.debug(f"Breadth calculation failed: {e}")
                result['breadth'] = {'advancing': 0, 'declining': 0, 'ratio': 0.5, 'interpretation': 'UNAVAILABLE'}
            
            # ─── FII/DII (from market context if available, else placeholder) ───
            # Note: Real-time FII/DII requires NSE website scraping or delayed data
            # For now, use previous day's data if available from market_context
            fii_dii_data = self.market_context.get('fii_dii', {})
            if fii_dii_data:
                result['fii_dii'] = fii_dii_data
            else:
                result['fii_dii'] = {
                    'available': False,
                    'note': 'FII/DII data updated after market hours. Use NIFTY trend + VIX as proxy.'
                }
            
            # ─── OVERALL MARKET MOOD ───
            bullish_signals = 0
            bearish_signals = 0
            
            if nifty_change_pct > 0.5: bullish_signals += 2
            elif nifty_change_pct > 0: bullish_signals += 1
            elif nifty_change_pct < -0.5: bearish_signals += 2
            elif nifty_change_pct < 0: bearish_signals += 1
            
            if vix_value < 15: bullish_signals += 1
            elif vix_value > 20: bearish_signals += 2
            
            breadth_ratio = result['breadth'].get('ratio', 0.5)
            if breadth_ratio > 0.6: bullish_signals += 1
            elif breadth_ratio < 0.4: bearish_signals += 1
            
            if bullish_signals >= 3:
                result['market_mood'] = 'BULLISH'
            elif bearish_signals >= 3:
                result['market_mood'] = 'BEARISH'
            elif bullish_signals > bearish_signals:
                result['market_mood'] = 'MILDLY_BULLISH'
            elif bearish_signals > bullish_signals:
                result['market_mood'] = 'MILDLY_BEARISH'
            else:
                result['market_mood'] = 'NEUTRAL'
            
            logger.info(f"   🌍 NSE Market: NIFTY {nifty_price:.0f} ({nifty_change_pct:+.2f}%) | "
                       f"VIX {vix_value:.1f} | Breadth {result['breadth'].get('advancing', 0)}A/"
                       f"{result['breadth'].get('declining', 0)}D | Mood: {result['market_mood']}")
            
        except Exception as e:
            logger.warning(f"NSE market context fetch failed: {e}")
            result['market_mood'] = 'UNKNOWN'
        
        return result
    
    def _fetch_daily_kalman_prediction(self, symbol: str) -> Dict:
        """
        v4.15.0: Run Kalman filter on DAILY candles for 1-3 day predictions.
        
        Separate from the intraday 15min Kalman — this gives swing-level direction.
        Called once per TIER_2 cycle (every 60 min for CNC positions).
        """
        try:
            instrument_token = self._get_instrument_token(symbol)
            if not instrument_token:
                return {'available': False, 'reason': 'No instrument token'}
            
            # Fetch 60 days of daily candles
            from_date = datetime.now() - timedelta(days=60)
            to_date = datetime.now()
            
            daily_data = self.kite.historical_data(
                instrument_token, from_date, to_date, interval="day"
            )
            
            if not daily_data or len(daily_data) < 10:
                return {'available': False, 'reason': 'Insufficient daily data'}
            
            closes = [c['close'] for c in daily_data]
            current_price = closes[-1]
            
            # Simple Kalman-like velocity/acceleration on daily closes
            # Velocity = average daily change over last 5 days
            recent_changes = [closes[i] - closes[i-1] for i in range(-5, 0)]
            daily_velocity = sum(recent_changes) / len(recent_changes)
            
            # Acceleration = change in velocity
            older_changes = [closes[i] - closes[i-1] for i in range(-10, -5)]
            older_velocity = sum(older_changes) / len(older_changes)
            daily_acceleration = daily_velocity - older_velocity
            
            # Predictions with damping (mean reversion for longer horizons)
            pred_1day = current_price + daily_velocity
            pred_3day = current_price + (daily_velocity * 3) + (0.5 * daily_acceleration * 9)
            pred_1week = current_price + (daily_velocity * 5 * 0.7)  # 0.7 damping for uncertainty
            
            # Clamp predictions to realistic bounds
            max_1day = current_price * 1.03  # Max 3% daily move
            min_1day = current_price * 0.97
            pred_1day = max(min_1day, min(max_1day, pred_1day))
            
            max_3day = current_price * 1.06
            min_3day = current_price * 0.94
            pred_3day = max(min_3day, min(max_3day, pred_3day))
            
            max_1week = current_price * 1.08
            min_1week = current_price * 0.92
            pred_1week = max(min_1week, min(max_1week, pred_1week))
            
            # Direction assessment
            if daily_velocity > 0 and daily_acceleration >= 0:
                daily_direction = "BULLISH_ACCELERATING"
            elif daily_velocity > 0:
                daily_direction = "BULLISH_DECELERATING"
            elif daily_velocity < 0 and daily_acceleration <= 0:
                daily_direction = "BEARISH_ACCELERATING"
            elif daily_velocity < 0:
                daily_direction = "BEARISH_DECELERATING"
            else:
                daily_direction = "FLAT"
            
            # Confidence based on consistency of recent moves
            consistent_moves = sum(1 for c in recent_changes if (c > 0) == (daily_velocity > 0))
            consistency = consistent_moves / len(recent_changes)
            confidence = round(consistency * 100, 0)
            
            result = {
                'available': True,
                'daily_velocity': round(daily_velocity, 2),
                'daily_acceleration': round(daily_acceleration, 2),
                'direction': daily_direction,
                'confidence': confidence,
                'predictions': {
                    '1_day': round(pred_1day, 2),
                    '3_day': round(pred_3day, 2),
                    '1_week': round(pred_1week, 2)
                },
                'prediction_change_pct': {
                    '1_day': round((pred_1day - current_price) / current_price * 100, 2),
                    '3_day': round((pred_3day - current_price) / current_price * 100, 2),
                    '1_week': round((pred_1week - current_price) / current_price * 100, 2)
                }
            }
            
            logger.info(f"   📈 {symbol} Daily Kalman: {daily_direction} (Conf={confidence:.0f}%) | "
                       f"1D=₹{pred_1day:.2f} ({result['prediction_change_pct']['1_day']:+.2f}%) | "
                       f"3D=₹{pred_3day:.2f} ({result['prediction_change_pct']['3_day']:+.2f}%)")
            
            return result
            
        except Exception as e:
            logger.debug(f"Daily Kalman failed for {symbol}: {e}")
            return {'available': False, 'reason': str(e)}
    
    def _calculate_position_age(self, position: Dict) -> Dict:
        """
        v4.15.0: Calculate position age in days/hours for CNC context.
        """
        try:
            entry_time_str = position.get('entry_time', '')
            if not entry_time_str:
                return {'days': 0, 'hours': 0, 'description': 'Unknown'}
            
            if isinstance(entry_time_str, str):
                entry_time = datetime.fromisoformat(entry_time_str)
            else:
                entry_time = entry_time_str
            
            elapsed = datetime.now() - entry_time
            days = elapsed.days
            hours = elapsed.seconds // 3600
            
            if days == 0:
                description = f"Entered today ({hours}h ago)"
            elif days == 1:
                description = f"Day 2 of hold (entered yesterday)"
            else:
                description = f"Day {days + 1} of hold ({days} days)"
            
            return {
                'days': days,
                'hours': hours,
                'total_hours': days * 24 + hours,
                'description': description
            }
        except Exception as e:
            return {'days': 0, 'hours': 0, 'total_hours': 0, 'description': f'Error: {e}'}
    
    # ═══════════════════════════════════════════════════════════════════════════
    # v4.15.0: VOLUME + PRICE (V+P) ALERT SYSTEM
    # ═══════════════════════════════════════════════════════════════════════════
    
    def _fetch_yesterday_volume(self, symbol: str) -> int:
        """
        v4.15.0: Fetch yesterday's total traded volume for a symbol.
        
        Called once at startup per CNC position. Used as baseline to
        detect abnormal volume throughout the day.
        
        Returns:
            Yesterday's total volume, or 0 if unavailable
        """
        try:
            instrument_token = self._get_instrument_token(symbol)
            if not instrument_token:
                logger.debug(f"No instrument token for {symbol}")
                return 0
            
            # Get yesterday's daily candle
            today = datetime.now().date()
            from_date = today - timedelta(days=5)  # Go back 5 days to handle weekends
            
            daily_data = self.kite.historical_data(
                instrument_token, from_date, today, interval="day"
            )
            
            if not daily_data or len(daily_data) < 2:
                return 0
            
            # Last complete day (not today)
            yesterday_candle = daily_data[-2]  # -1 is today's partial, -2 is yesterday
            yesterday_vol = yesterday_candle.get('volume', 0)
            
            logger.info(f"   📊 {symbol}: Yesterday's volume = {yesterday_vol:,.0f}")
            return yesterday_vol
            
        except Exception as e:
            logger.debug(f"Yesterday volume fetch failed for {symbol}: {e}")
            return 0
    
    def _init_volume_baselines(self):
        """
        v4.15.0: Initialize yesterday's volume for all CNC positions at startup.
        Called from startup_with_market_context().
        """
        for symbol, position in self.positions.items():
            if position.get('product', 'CNC') == 'CNC':
                if not position.get('yesterday_volume'):
                    vol = self._fetch_yesterday_volume(symbol)
                    position['yesterday_volume'] = vol
                    
        logger.info(f"   📊 Volume baselines initialized for {len(self.positions)} positions")
    
    def _calculate_volume_ratio(self, symbol: str, current_volume: int) -> float:
        """
        v4.15.0: Calculate volume ratio = current cumulative volume / expected volume at this time.
        
        Args:
            symbol: Stock symbol
            current_volume: Today's cumulative volume so far (from quote)
            
        Returns:
            Volume ratio (1.0 = normal, 2.0 = 2× expected, etc.)
        """
        position = self.positions.get(symbol)
        if not position:
            return 1.0
        
        yesterday_volume = position.get('yesterday_volume', 0)
        if yesterday_volume <= 0:
            return 1.0
        
        # Market hours: 9:15 AM to 3:30 PM = 375 minutes
        now = datetime.now()
        market_open = now.replace(hour=9, minute=15, second=0)
        
        if now < market_open:
            return 1.0
        
        minutes_elapsed = max(1, (now - market_open).total_seconds() / 60)
        total_market_minutes = 375.0
        
        # Expected volume = yesterday's total × fraction of day elapsed
        expected_volume = yesterday_volume * (minutes_elapsed / total_market_minutes)
        
        if expected_volume <= 0:
            return 1.0
        
        return current_volume / expected_volume
    
    def _check_volume_price_signal(self, symbol: str, position: Dict, 
                                    current_price: float, quote_data: Dict) -> Optional[Dict]:
        """
        v4.15.0: Volume + Price combined signal detection for CNC positions.
        
        Runs every cycle in TIER_2 loop. Uses already-fetched quote data.
        Returns signal dict if burst detected, None otherwise.
        
        Signal Matrix:
            Volume >3× + Price DOWN >1% → EXTREME_BEARISH → Force ChatGPT + Telegram
            Volume >3× + Price UP >1%   → EXTREME_BULLISH → Telegram alert
            Volume >3× + Price FLAT     → EXTREME_CHURN   → Telegram alert
            Volume >2× + Price DOWN >1% → BEARISH_CONVICTION → Force ChatGPT + Telegram
            Volume >2× + Price UP >1%   → BULLISH_CONVICTION → Telegram alert
            Volume >2× + Price FLAT     → CHURNING → Log only
            Volume <2×                  → NORMAL → No action
        """
        # Only for CNC positions
        if position.get('product', 'CNC') != 'CNC':
            return None
        
        # Cooldown check: 15 minutes between V+P alerts per symbol
        vp_cooldown_key = f"vp_alert_{symbol}"
        last_alert = getattr(self, '_vp_alert_times', {}).get(symbol)
        if last_alert and (datetime.now() - last_alert).total_seconds() < 900:  # 15 min
            return None
        
        # Get volume data from quote
        current_volume = quote_data.get('volume', 0)
        if current_volume <= 0:
            return None
        
        # Calculate volume ratio
        volume_ratio = self._calculate_volume_ratio(symbol, current_volume)
        
        # Calculate price change from today's open (needed for log regardless)
        day_open = quote_data.get('ohlc', {}).get('open', 0)
        if day_open <= 0:
            day_open = position.get('entry_price', current_price)
        price_change_pct = ((current_price - day_open) / day_open * 100) if day_open > 0 else 0
        
        # v5.0.1: Always log V+P status for visibility
        if volume_ratio >= 2.0:
            vp_label = "🔴 HIGH" if volume_ratio >= 3.0 else "🟡 ELEVATED"
        elif volume_ratio >= 1.5:
            vp_label = "⚡ MODERATE"
        else:
            vp_label = "✅ Normal"
        
        logger.info(f"   📶 V+P: {volume_ratio:.1f}× vol ({vp_label}) | "
                    f"Price: {price_change_pct:+.2f}% from open | "
                    f"Vol: {current_volume:,.0f}")
        
        # Below threshold — no signal (but we already logged status above)
        if volume_ratio < 2.0:
            return None
        
        # Determine signal
        is_extreme = volume_ratio >= 3.0
        is_price_up = price_change_pct > 1.0
        is_price_down = price_change_pct < -1.0
        is_flat = not is_price_up and not is_price_down
        
        if is_extreme:
            if is_price_down:
                signal_type = "EXTREME_BEARISH"
                emoji = "🔴"
                interpretation = "Institutional SELLING with extreme volume"
                action = "FORCE_CHATGPT"
            elif is_price_up:
                signal_type = "EXTREME_BULLISH"
                emoji = "🟢"
                interpretation = "Institutional BUYING with extreme volume"
                action = "TELEGRAM_ALERT"
            else:
                signal_type = "EXTREME_CHURN"
                emoji = "🟡"
                interpretation = "Extreme volume with no direction — big players exchanging"
                action = "TELEGRAM_ALERT"
        else:  # volume_ratio >= 2.0
            if is_price_down:
                signal_type = "BEARISH_CONVICTION"
                emoji = "🔴"
                interpretation = "Institutional SELLING with high volume"
                action = "FORCE_CHATGPT"
            elif is_price_up:
                signal_type = "BULLISH_CONVICTION"
                emoji = "🟢"
                interpretation = "Institutional BUYING detected"
                action = "TELEGRAM_ALERT"
            else:
                signal_type = "CHURNING"
                emoji = "🟡"
                interpretation = "High volume, flat price — accumulation or distribution"
                action = "LOG_ONLY"
        
        signal = {
            'symbol': symbol,
            'signal_type': signal_type,
            'emoji': emoji,
            'volume_ratio': round(volume_ratio, 1),
            'current_volume': current_volume,
            'expected_volume': round(current_volume / volume_ratio) if volume_ratio > 0 else 0,
            'price_change_pct': round(price_change_pct, 2),
            'current_price': current_price,
            'interpretation': interpretation,
            'action': action,
            'timestamp': datetime.now().isoformat()
        }
        
        # Record alert time for cooldown
        if not hasattr(self, '_vp_alert_times'):
            self._vp_alert_times = {}
        self._vp_alert_times[symbol] = datetime.now()
        
        # Store in position for ChatGPT
        position.setdefault('phase4_tracking', {})['last_vp_signal'] = signal
        
        # Log
        logger.warning(f"{emoji} V+P SIGNAL: {symbol} — {signal_type}")
        logger.warning(f"   Volume: {volume_ratio:.1f}× normal ({current_volume:,.0f} vs "
                      f"{signal['expected_volume']:,.0f} expected)")
        logger.warning(f"   Price: ₹{current_price:.2f} ({price_change_pct:+.2f}% from open)")
        logger.warning(f"   → {interpretation}")
        
        # Telegram alert for non-LOG_ONLY signals
        if action != "LOG_ONLY" and self.telegram:
            yesterday_vol = position.get('yesterday_volume', 0)
            
            alert_msg = (
                f"{emoji} V+P ALERT: {symbol}\n\n"
                f"Volume: {volume_ratio:.1f}× normal "
                f"({'EXTREME' if is_extreme else 'HIGH'})\n"
                f"Price: ₹{current_price:.2f} ({price_change_pct:+.2f}% from open)\n"
                f"Signal: {signal_type.replace('_', ' ')}\n\n"
                f"📊 {interpretation}\n"
                f"   Today's Volume: {current_volume:,.0f}\n"
                f"   Expected by now: {signal['expected_volume']:,.0f}\n"
                f"   Yesterday Total: {yesterday_vol:,.0f}\n"
            )
            
            if action == "FORCE_CHATGPT":
                alert_msg += "\n🤖 Forcing ChatGPT consultation..."
            elif signal_type.startswith("EXTREME_BULLISH") or signal_type == "BULLISH_CONVICTION":
                alert_msg += "\n✅ Hold position confirmed by volume strength"
            elif signal_type == "EXTREME_CHURN":
                alert_msg += "\n⚠️ Watch next 15-30 min for breakout direction"
            
            self.telegram.send_message(alert_msg)
        
        # v4.15.0: Generate OPTIONS ADVISORY for BULLISH bursts only
        if signal_type in ('EXTREME_BULLISH', 'BULLISH_CONVICTION'):
            try:
                logger.info(f"   ⚡ BULLISH V+P burst — generating options advisory...")
                self._generate_options_advisory(symbol, signal, position, current_price)
            except Exception as e:
                logger.error(f"   Options advisory failed: {e}")
        
        return signal

    # ═══════════════════════════════════════════════════════════════════════════
    # v4.15.0: OPTIONS ADVISORY SIGNAL GENERATOR
    # Ph4 generates signal + basic OI + Kalman-guided strike suggestion
    # Ph6 (future) will consume this signal for execution
    # ═══════════════════════════════════════════════════════════════════════════
    
    def _fetch_basic_option_oi(self, symbol: str, current_price: float) -> Optional[Dict]:
        """
        v4.15.0: Fetch basic option chain OI data for a symbol.
        
        Gets top 5 OTM Call OI walls + max pain + PCR from NFO instruments.
        Cached for 30 minutes to avoid excessive API calls.
        
        Returns:
            Dict with oi_walls, max_pain, pcr, atm_iv, expiry info, lot_size
            or None if fetch fails
        """
        try:
            # Cache check (30-minute cache per symbol)
            cache_key = f"oi_cache_{symbol}"
            cached = getattr(self, '_oi_cache', {}).get(cache_key)
            if cached:
                cache_time = cached.get('_cache_time')
                if cache_time and (datetime.now() - cache_time).total_seconds() < 1800:
                    return cached
            
            if not hasattr(self, '_oi_cache'):
                self._oi_cache = {}
            
            # Step 1: Get NFO instruments for this symbol
            nfo_instruments = self.kite.instruments('NFO')
            
            # Filter: same underlying, CE options, nearest monthly expiry
            today = datetime.now().date()
            ce_options = []
            pe_options = []
            
            for inst in nfo_instruments:
                if inst.get('name') != symbol:
                    continue
                
                expiry = inst.get('expiry')
                if not expiry:
                    continue
                
                # Convert expiry to date if needed
                if hasattr(expiry, 'date'):
                    expiry_date = expiry.date() if callable(getattr(expiry, 'date', None)) else expiry
                elif isinstance(expiry, str):
                    expiry_date = datetime.strptime(expiry, '%Y-%m-%d').date()
                else:
                    expiry_date = expiry
                
                # Only future expiries
                if expiry_date < today:
                    continue
                
                if inst.get('instrument_type') == 'CE':
                    ce_options.append({
                        'tradingsymbol': inst['tradingsymbol'],
                        'instrument_token': inst['instrument_token'],
                        'strike': float(inst.get('strike', 0)),
                        'expiry': expiry_date,
                        'lot_size': int(inst.get('lot_size', 1))
                    })
                elif inst.get('instrument_type') == 'PE':
                    pe_options.append({
                        'tradingsymbol': inst['tradingsymbol'],
                        'instrument_token': inst['instrument_token'],
                        'strike': float(inst.get('strike', 0)),
                        'expiry': expiry_date,
                        'lot_size': int(inst.get('lot_size', 1))
                    })
            
            if not ce_options:
                logger.warning(f"   No CE options found for {symbol}")
                return None
            
            # Find nearest expiry
            nearest_expiry = min(set(o['expiry'] for o in ce_options))
            days_to_expiry = (nearest_expiry - today).days
            
            # Filter to nearest expiry only
            ce_nearest = [o for o in ce_options if o['expiry'] == nearest_expiry]
            pe_nearest = [o for o in pe_options if o['expiry'] == nearest_expiry]
            
            # Get lot size
            lot_size = ce_nearest[0]['lot_size'] if ce_nearest else 1
            
            # Filter OTM calls (strike > current price) + some ITM for PCR calc
            # Get strikes around current price (±15%)
            price_low = current_price * 0.85
            price_high = current_price * 1.15
            
            ce_filtered = [o for o in ce_nearest if price_low <= o['strike'] <= price_high]
            pe_filtered = [o for o in pe_nearest if price_low <= o['strike'] <= price_high]
            
            if not ce_filtered:
                logger.warning(f"   No CE options in range for {symbol}")
                return None
            
            # Step 2: Batch quote for OI data
            # Kite quote gives: last_price, oi, volume, ohlc
            ce_symbols = [f"NFO:{o['tradingsymbol']}" for o in ce_filtered]
            pe_symbols = [f"NFO:{o['tradingsymbol']}" for o in pe_filtered]
            
            # Batch in groups of 50 (Kite API limit)
            all_symbols = ce_symbols + pe_symbols
            quotes = {}
            for i in range(0, len(all_symbols), 50):
                batch = all_symbols[i:i+50]
                batch_quotes = self.kite.quote(batch)
                quotes.update(batch_quotes)
            
            # Step 3: Build OI data for CE (OTM only)
            otm_ce_data = []
            total_ce_oi = 0
            total_pe_oi = 0
            
            for opt in ce_filtered:
                key = f"NFO:{opt['tradingsymbol']}"
                q = quotes.get(key, {})
                oi = q.get('oi', 0)
                total_ce_oi += oi
                
                if opt['strike'] > current_price:  # OTM calls only for walls
                    otm_ce_data.append({
                        'strike': opt['strike'],
                        'oi': oi,
                        'oi_lakhs': round(oi / 100000, 2),
                        'oi_change_pct': round(((q.get('oi', 0) - q.get('ohlc', {}).get('open', oi)) / max(oi, 1)) * 100, 2) if oi > 0 else 0,
                        'ltp': q.get('last_price', 0),
                        'volume': q.get('volume', 0),
                        'tradingsymbol': opt['tradingsymbol']
                    })
            
            for opt in pe_filtered:
                key = f"NFO:{opt['tradingsymbol']}"
                q = quotes.get(key, {})
                total_pe_oi += q.get('oi', 0)
            
            # Sort by OI descending, take top 5
            otm_ce_data.sort(key=lambda x: x['oi'], reverse=True)
            top_5_walls = otm_ce_data[:5]
            
            # Step 4: Calculate PCR
            pcr = round(total_pe_oi / max(total_ce_oi, 1), 2)
            
            # Step 5: Max Pain calculation (simplified)
            # Max pain = strike where total premium loss for option BUYERS is maximum
            # Simplified: weighted average of high-OI strikes
            all_strikes_oi = []
            for opt in ce_filtered + pe_filtered:
                key = f"NFO:{opt['tradingsymbol']}"
                q = quotes.get(key, {})
                oi = q.get('oi', 0)
                if oi > 0:
                    all_strikes_oi.append((opt['strike'], oi))
            
            if all_strikes_oi:
                total_oi_weight = sum(oi for _, oi in all_strikes_oi)
                if total_oi_weight > 0:
                    max_pain = round(sum(s * oi for s, oi in all_strikes_oi) / total_oi_weight, 0)
                else:
                    max_pain = current_price
            else:
                max_pain = current_price
            
            # Step 6: ATM IV (from nearest ATM CE quote)
            atm_strike_options = sorted(ce_filtered, key=lambda x: abs(x['strike'] - current_price))
            atm_iv = 0
            if atm_strike_options:
                atm_key = f"NFO:{atm_strike_options[0]['tradingsymbol']}"
                atm_quote = quotes.get(atm_key, {})
                # Kite doesn't give IV directly in quote — estimate from price if needed
                # For now use 0 and Ph6 can calculate with Greeks
                atm_iv = 0  # Ph6 will calculate using Black-Scholes
            
            result = {
                'oi_walls': top_5_walls,
                'max_pain': max_pain,
                'pcr': pcr,
                'atm_iv': atm_iv,
                'nearest_expiry': nearest_expiry.isoformat(),
                'days_to_expiry': days_to_expiry,
                'lot_size': lot_size,
                'total_ce_oi': total_ce_oi,
                'total_pe_oi': total_pe_oi,
                '_cache_time': datetime.now()
            }
            
            # Cache it
            self._oi_cache[cache_key] = result
            
            logger.info(f"   📋 {symbol} OI: Top wall={top_5_walls[0]['strike']} ({top_5_walls[0]['oi_lakhs']}L), "
                        f"PCR={pcr}, MaxPain={max_pain}, Expiry={nearest_expiry} ({days_to_expiry}d)")
            
            return result
            
        except Exception as e:
            logger.error(f"Option OI fetch failed for {symbol}: {e}")
            return None
    
    def _select_strike_kalman_guided(self, oi_data: Dict, kalman_predictions: Dict, 
                                      current_price: float) -> Optional[Dict]:
        """
        v4.15.0: Select strike using Kalman prediction vs OI walls.
        
        Logic: Pick the highest OI wall that Kalman's 1-week prediction can REACH.
        If Kalman can't reach ANY wall, return None (skip trade).
        
        Returns:
            Dict with strike, reason, cost, kalman_reaches_walls
            or None if no suitable strike
        """
        try:
            oi_walls = oi_data.get('oi_walls', [])
            if not oi_walls:
                return None
            
            lot_size = oi_data.get('lot_size', 1)
            days_to_expiry = oi_data.get('days_to_expiry', 0)
            
            # Minimum 5 days to expiry for this to make sense
            if days_to_expiry < 5:
                logger.info(f"   ⏰ Only {days_to_expiry} days to expiry — too risky for advisory")
                return None
            
            # Get Kalman predictions
            k_1day = kalman_predictions.get('prediction_1day', current_price)
            k_3day = kalman_predictions.get('prediction_3day', current_price)
            k_1week = kalman_predictions.get('prediction_1week', current_price)
            k_confidence = kalman_predictions.get('confidence', 50)
            k_direction = kalman_predictions.get('direction', 'UNKNOWN')
            
            # Must be bullish direction
            if 'BEARISH' in k_direction.upper():
                logger.info(f"   📉 Kalman direction is {k_direction} — skipping CE advisory")
                return None
            
            # Minimum confidence
            if k_confidence < 55:
                logger.info(f"   🤷 Kalman confidence {k_confidence}% too low — skipping advisory")
                return None
            
            # Check which walls Kalman can reach
            kalman_reaches = {}
            reachable_walls = []
            
            for wall in oi_walls:
                strike = wall['strike']
                can_reach = k_1week >= strike  # Kalman 1-week prediction reaches this strike
                kalman_reaches[str(int(strike))] = can_reach
                
                if can_reach:
                    reachable_walls.append(wall)
            
            if not reachable_walls:
                # Kalman can't reach any OI wall
                logger.info(f"   🚫 Kalman 1-week (₹{k_1week:.0f}) can't reach any OI wall — no advisory")
                return None
            
            # Pick the highest OI wall among reachable ones
            # (highest OI = most significant resistance/target)
            selected = max(reachable_walls, key=lambda w: w['oi'])
            
            # Determine reason
            if k_3day >= selected['strike']:
                time_frame = "3-day"
            elif k_1week >= selected['strike']:
                time_frame = "1-week"
            else:
                time_frame = "1-week"
            
            cost = round(selected['ltp'] * lot_size, 2)
            
            result = {
                'strike': selected['strike'],
                'ltp': selected['ltp'],
                'oi_lakhs': selected['oi_lakhs'],
                'lot_size': lot_size,
                'cost': cost,
                'reason': f"Highest OI wall ({selected['oi_lakhs']}L) within Kalman {time_frame} range (₹{k_1week:.0f})",
                'kalman_reaches_walls': kalman_reaches,
                'reachable_count': len(reachable_walls),
                'total_walls': len(oi_walls),
                'tradingsymbol': selected.get('tradingsymbol', '')
            }
            
            logger.info(f"   🎯 Strike selected: {int(selected['strike'])} CE "
                        f"(OI: {selected['oi_lakhs']}L, LTP: ₹{selected['ltp']}, "
                        f"Cost: ₹{cost:,.0f})")
            
            return result
            
        except Exception as e:
            logger.error(f"Strike selection failed: {e}")
            return None
    
    def _generate_options_advisory(self, symbol: str, vp_signal: Dict, 
                                    position: Dict, current_price: float):
        """
        v4.15.0: Generate complete options advisory signal.
        
        Called when V+P BULLISH burst detected.
        Fetches OI, selects strike via Kalman, sends Telegram, saves signal JSON.
        
        This signal is the CONTRACT between Ph4 and future Ph6.
        """
        try:
            logger.info(f"\n{'='*60}")
            logger.info(f"⚡ OPTIONS ADVISORY: {symbol}")
            logger.info(f"{'='*60}")
            
            # Step 1: Get Kalman predictions
            daily_kalman = self._fetch_daily_kalman_prediction(symbol)
            if not daily_kalman or daily_kalman.get('direction', 'UNKNOWN') == 'UNKNOWN':
                logger.warning(f"   ❌ Daily Kalman unavailable — skipping advisory")
                return
            
            # Step 2: Fetch basic OI (top 5 walls)
            oi_data = self._fetch_basic_option_oi(symbol, current_price)
            if not oi_data or not oi_data.get('oi_walls'):
                logger.warning(f"   ❌ Option chain OI unavailable — skipping advisory")
                return
            
            # Step 3: Kalman-guided strike selection
            strike_selection = self._select_strike_kalman_guided(oi_data, daily_kalman, current_price)
            
            # Step 4: Build signal packet
            signal_packet = {
                'source': 'PH4_VP_BURST',
                'timestamp': datetime.now().isoformat(),
                'version': '4.15.0',
                
                # Equity Context
                'symbol': symbol,
                'current_price': current_price,
                'day_open': vp_signal.get('current_price', current_price) - (vp_signal.get('price_change_pct', 0) / 100 * current_price),
                'price_change_pct': vp_signal.get('price_change_pct', 0),
                
                # V+P Signal
                'vp_signal': vp_signal.get('signal_type', ''),
                'volume_ratio': vp_signal.get('volume_ratio', 1.0),
                'current_volume': vp_signal.get('current_volume', 0),
                'expected_volume': vp_signal.get('expected_volume', 0),
                
                # Kalman Predictions
                'kalman': daily_kalman,
                
                # Basic OI (Top 5 walls)
                'oi_walls': oi_data.get('oi_walls', []),
                'max_pain': oi_data.get('max_pain', 0),
                'pcr': oi_data.get('pcr', 0),
                'atm_iv': oi_data.get('atm_iv', 0),
                'nearest_expiry': oi_data.get('nearest_expiry', ''),
                'days_to_expiry': oi_data.get('days_to_expiry', 0),
                'lot_size': oi_data.get('lot_size', 1),
                
                # Strike Suggestion
                'suggested_strike': strike_selection.get('strike') if strike_selection else None,
                'suggestion_reason': strike_selection.get('reason', 'No suitable strike found') if strike_selection else 'Kalman cannot reach any OI wall',
                'suggested_cost': strike_selection.get('cost', 0) if strike_selection else 0,
                'suggested_tradingsymbol': strike_selection.get('tradingsymbol', '') if strike_selection else '',
                'kalman_reaches_walls': strike_selection.get('kalman_reaches_walls', {}) if strike_selection else {},
            }
            
            # Step 5: Save signal JSON (for Ph6 future consumption)
            signal_dir = os.path.join(os.path.dirname(__file__), 'signals')
            os.makedirs(signal_dir, exist_ok=True)
            
            signal_file = os.path.join(signal_dir, 
                f"options_advisory_{symbol}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
            
            with open(signal_file, 'w') as f:
                json.dump(signal_packet, f, indent=2, default=str)
            
            logger.info(f"   💾 Signal saved: {signal_file}")
            
            # Step 6: Send Telegram advisory
            if self.telegram:
                walls_text = ""
                for i, wall in enumerate(oi_data.get('oi_walls', [])[:5], 1):
                    reach_emoji = "✅" if strike_selection and strike_selection.get('kalman_reaches_walls', {}).get(str(int(wall['strike'])), False) else "❌"
                    walls_text += f"   {i}. {int(wall['strike'])} CE — {wall['oi_lakhs']}L OI ({wall.get('oi_change_pct', 0):+.1f}%) — LTP ₹{wall['ltp']:.2f} {reach_emoji}\n"
                
                # Kalman reaches summary
                if strike_selection:
                    reaches = strike_selection.get('kalman_reaches_walls', {})
                    reaches_text = " ".join(f"{k}{'✅' if v else '❌'}" for k, v in sorted(reaches.items(), key=lambda x: float(x[0])))
                else:
                    reaches_text = "N/A"
                
                # Build message
                k = daily_kalman
                msg = (
                    f"⚡ OPTIONS ADVISORY: {symbol}\n\n"
                    f"🔥 V+P BURST: {vp_signal.get('signal_type', '').replace('_', ' ')}\n"
                    f"   Volume: {vp_signal.get('volume_ratio', 0):.1f}× | "
                    f"Price: ₹{current_price:.2f} ({vp_signal.get('price_change_pct', 0):+.2f}%)\n\n"
                    f"🔮 KALMAN PREDICTIONS:\n"
                    f"   1-Day:  ₹{k.get('prediction_1day', 0):.0f} "
                    f"({((k.get('prediction_1day', current_price) - current_price) / current_price * 100):+.1f}%)\n"
                    f"   3-Day:  ₹{k.get('prediction_3day', 0):.0f} "
                    f"({((k.get('prediction_3day', current_price) - current_price) / current_price * 100):+.1f}%)\n"
                    f"   1-Week: ₹{k.get('prediction_1week', 0):.0f} "
                    f"({((k.get('prediction_1week', current_price) - current_price) / current_price * 100):+.1f}%)\n"
                    f"   Direction: {k.get('direction', 'N/A')} ({k.get('confidence', 0)}%)\n\n"
                    f"📋 TOP OI WALLS (OTM CE):\n"
                    f"{walls_text}\n"
                )
                
                if strike_selection:
                    msg += (
                        f"🎯 SUGGESTED: {int(strike_selection['strike'])} CE @ ₹{strike_selection['ltp']:.2f}\n"
                        f"   {strike_selection['reason']}\n"
                        f"   Cost: ₹{strike_selection['cost']:,.0f} (1 lot × {oi_data.get('lot_size', 0)})\n"
                        f"   Kalman reaches: {reaches_text}\n\n"
                    )
                else:
                    msg += (
                        f"🚫 NO STRIKE SUGGESTED\n"
                        f"   Reason: {signal_packet.get('suggestion_reason', 'Unknown')}\n\n"
                    )
                
                msg += (
                    f"📊 Max Pain: {oi_data.get('max_pain', 0):.0f} | "
                    f"PCR: {oi_data.get('pcr', 0):.2f}\n"
                    f"⏰ Expiry: {oi_data.get('nearest_expiry', 'N/A')} "
                    f"({oi_data.get('days_to_expiry', 0)} days)\n\n"
                    f"⚠️ ADVISORY ONLY — No auto-execution"
                )
                
                self.telegram.send_message(msg)
                logger.info(f"   📱 Telegram advisory sent for {symbol}")
            
            logger.info(f"{'='*60}\n")
            
        except Exception as e:
            logger.error(f"Options advisory generation failed for {symbol}: {e}")

    # ═══════════════════════════════════════════════════════════════════════════
    # MARKET REGIME DETECTION
    # ═══════════════════════════════════════════════════════════════════════════
    
    def _detect_market_regime(self) -> MarketRegime:
        """Detect current market regime"""
        try:
            # Get NIFTY data
            nifty_quote = self.kite.quote(['NSE:NIFTY 50'])
            nifty_data = nifty_quote.get('NSE:NIFTY 50', {})
            
            # Get VIX
            vix_quote = self.kite.quote(['NSE:INDIA VIX'])
            vix_value = vix_quote.get('NSE:INDIA VIX', {}).get('last_price', 15)
            
            # Calculate change
            nifty_change = nifty_data.get('change', 0)
            nifty_change_pct = (nifty_change / nifty_data.get('last_price', 1)) * 100 if nifty_data.get('last_price') else 0
            
            # Simple regime detection
            if vix_value > 25:
                return MarketRegime.CRISIS
            elif vix_value > 18:
                if abs(nifty_change_pct) > 1.0:
                    return MarketRegime.VOLATILE_TREND
                else:
                    return MarketRegime.CHOPPY_VOLATILE
            elif vix_value < 12:
                if abs(nifty_change_pct) < 0.3:
                    return MarketRegime.SQUEEZE
                else:
                    return MarketRegime.RANGING_QUIET
            else:
                if abs(nifty_change_pct) > 0.8:
                    return MarketRegime.STRONG_TREND
                else:
                    return MarketRegime.NORMAL
                    
        except Exception as e:
            logger.warning(f"Regime detection failed: {e}")
            return MarketRegime.NORMAL
    
    def _get_regime_params(self) -> Dict:
        """Get parameters for current regime"""
        return self.REGIME_PARAMS.get(self.current_regime.value, self.REGIME_PARAMS['NORMAL'])

    # ═══════════════════════════════════════════════════════════════════════════
    # POSITION EVENT HANDLERS
    # ═══════════════════════════════════════════════════════════════════════════
    
    def on_position_opened(self, position: Dict, signal: Dict = None):
        """
        Called when Phase 3 opens a new position.
        
        Args:
            position: Position data from Phase 3
            signal: Original signal data
        """
        symbol = position.get('symbol')
        if not symbol:
            logger.error("Position has no symbol!")
            return
        
        logger.info(f"📥 Phase 4 received new position: {symbol}")
        
        # Add Phase 4 tracking data
        position['phase4_tracking'] = {
            'tcas_status': TCASStatus().to_dict(),
            'ils_status': ILSStatus().to_dict(),
            'health_score': HealthScore(total_score=100.0, interpretation="HEALTHY").to_dict(),
            'kalman_state': KalmanState().to_dict(),
            'last_update': datetime.now().isoformat(),
            'chatgpt_consultations': [],
            'alerts_history': []
        }
        
        # v1.6.0: Store originating phase for P&L attribution
        if signal:
            position['_ph9_source'] = signal.get('source', signal.get('phase', 'UNKNOWN'))

        # Store position
        self.positions[symbol] = position

        # v1.4.0: Apply Phase 9 morning briefing stop/target/exit multipliers
        _briefing = getattr(self, 'daily_briefing', {})
        if _briefing and _briefing.get('briefing_done'):
            try:
                _entry  = float(position.get('entry_price', 0) or 0)
                _stop   = float(position.get('stop_price', 0) or 0)
                _target = float(position.get('target_price', 0) or 0)
                _dir    = str(position.get('direction', 'LONG')).upper()
                _is_long = _dir in ('LONG', 'BUY')

                if _entry > 0 and _stop > 0 and _target > 0:
                    _stop_mult   = float(_briefing.get('stop_atr_mult', 1.0) or 1.0)
                    _target_mult = float(_briefing.get('target_atr_mult', 1.0) or 1.0)
                    _exit_agg    = str(_briefing.get('exit_aggression', 'NORMAL')).upper()

                    # Scale stop distance
                    if _stop_mult != 1.0:
                        _stop_dist = abs(_entry - _stop)
                        _new_stop_dist = _stop_dist * _stop_mult
                        _new_stop = (_entry - _new_stop_dist) if _is_long else (_entry + _new_stop_dist)
                        position['stop_price'] = round(_new_stop, 2)
                        logger.info(f"   🧠 PH9 stop adjusted: ₹{_stop:.2f} → ₹{_new_stop:.2f} "
                                    f"({_stop_mult:.2f}x ATR mult)")

                    # Scale target distance
                    if _target_mult != 1.0:
                        _target_dist = abs(_target - _entry)
                        _new_target_dist = _target_dist * _target_mult
                        _new_target = (_entry + _new_target_dist) if _is_long else (_entry - _new_target_dist)
                        position['target_price'] = round(_new_target, 2)
                        logger.info(f"   🧠 PH9 target adjusted: ₹{_target:.2f} → ₹{_new_target:.2f} "
                                    f"({_target_mult:.2f}x ATR mult)")

                    # Exit aggression: EARLY = take profit at 80% of target distance
                    if _exit_agg == 'EARLY':
                        _t_now  = float(position.get('target_price', _target))
                        _t_dist = abs(_t_now - _entry)
                        _early_target = (_entry + _t_dist * 0.80) if _is_long else (_entry - _t_dist * 0.80)
                        position['target_price'] = round(_early_target, 2)
                        logger.info(f"   🧠 PH9 EARLY exit: target clipped to ₹{_early_target:.2f} "
                                    f"(80% of distance)")
                    elif _exit_agg == 'HOLD':
                        # HOLD = let TCAS/Kalman trailing handle exit; extend target by 20%
                        _t_now  = float(position.get('target_price', _target))
                        _t_dist = abs(_t_now - _entry)
                        _hold_target = (_entry + _t_dist * 1.20) if _is_long else (_entry - _t_dist * 1.20)
                        position['target_price'] = round(_hold_target, 2)
                        logger.info(f"   🧠 PH9 HOLD exit: target extended to ₹{_hold_target:.2f} "
                                    f"(120%, trailing stop active)")

            except Exception as _brf_e:
                logger.debug(f"PH9 briefing multiplier apply failed for {symbol}: {_brf_e}")

        # Initialize Kalman filter
        self._init_kalman_for_position(symbol, position)
        
        # Send manual trade card BEFORE GTT placement — user can act manually if API fails
        self._send_manual_gtt_card(symbol, position)

        # Place GTT orders
        # v4.8.2 FIX: Cancel-before-place (prevents duplicates across restarts)
        # PAPER MODE FIX: skip all real GTT operations for paper positions
        _is_paper = position.get('is_paper_trade', False) or getattr(self.config, 'MASTER_PAPER_MODE', False)
        if self.ENABLE_GTT and not _is_paper:
            existing_gtt = self._check_existing_gtt_for_symbol(symbol)

            # Cancel existing GTTs before placing fresh ones
            if existing_gtt and existing_gtt.get('all_ids'):
                cancelled = 0
                for old_gtt_id in existing_gtt['all_ids']:
                    try:
                        self._cancel_gtt(old_gtt_id)
                        cancelled += 1
                    except Exception as e:
                        logger.warning(f"   ⚠️ {symbol}: Failed to cancel old GTT #{old_gtt_id}: {e}")
                if cancelled > 0:
                    logger.info(f"   🧹 {symbol}: Cancelled {cancelled} old GTT(s) — placing fresh pair")
            
            gtt_ids = self._place_gtt_orders(symbol, position)
            if gtt_ids:
                position['gtt_stop_id'] = gtt_ids.get('stop_id')
                position['gtt_target_id'] = gtt_ids.get('target_id')
                position['gtt_active'] = True
            else:
                position['gtt_protected'] = False
                position['gtt_active'] = False
        
        # Save
        self._save_positions()
        
        logger.info(f"   ✅ Position registered with Phase 4 monitoring")

    def tighten_all_stops(self, factor: float = 0.5):
        """
        v1.4.0: PH9 DEFENSIVE mode — move all stops halfway towards current price.
        Protects unrealised profit while keeping positions open.
        factor=0.5 means: new_stop = old_stop + (current - old_stop) * 0.5
        """
        if not self.positions:
            return
        adjusted = 0
        for symbol, pos in self.positions.items():
            try:
                _entry  = float(pos.get('entry_price', 0) or 0)
                _cur    = float(pos.get('current_price', _entry) or _entry)
                _stop   = float(pos.get('stop_price', 0) or 0)
                _is_long = str(pos.get('direction', 'LONG')).upper() in ('LONG', 'BUY')

                if _entry <= 0 or _stop <= 0:
                    continue

                if _is_long:
                    # Only tighten if position is profitable (cur > entry)
                    if _cur > _entry and _cur > _stop:
                        _new_stop = round(_stop + (_cur - _stop) * factor, 2)
                        if _new_stop > _stop:
                            pos['stop_price'] = _new_stop
                            adjusted += 1
                            logger.info(f"   🛡️ DEFENSIVE tighten {symbol}: "
                                        f"₹{_stop:.2f} → ₹{_new_stop:.2f}")
                else:
                    if _cur < _entry and _cur < _stop:
                        _new_stop = round(_stop - (_stop - _cur) * factor, 2)
                        if _new_stop < _stop:
                            pos['stop_price'] = _new_stop
                            adjusted += 1
                            logger.info(f"   🛡️ DEFENSIVE tighten {symbol} (SHORT): "
                                        f"₹{_stop:.2f} → ₹{_new_stop:.2f}")
            except Exception as _te:
                logger.debug(f"tighten_all_stops error for {symbol}: {_te}")

        if adjusted:
            self._save_positions()
            logger.info(f"   🛡️ DEFENSIVE mode: tightened stops on {adjusted} position(s)")

    # ═══════════════════════════════════════════════════════════════════════════
    # v1.3.0: POSITION RECOVERY EXECUTOR
    # Executes the action plan returned by Phase9.recovery_advisor()
    # ═══════════════════════════════════════════════════════════════════════════

    def execute_recovery_action(self, symbol: str, recovery_plan: Dict) -> bool:
        """
        Execute Claude's recovery plan for an underwater position.

        Actions handled:
          HOLD         — Update stop/target if Claude suggested new values
          AVERAGE      — Place additional BUY/SELL order to lower avg entry
          SCALE_OUT    — Partial exit (25/50/75%)
          CONVERT_CNC  — Convert MIS product to CNC for overnight holding
          WIDEN_STOP   — Move stop further away to give position room
          EXIT         — Full position exit (delegates to _execute_exit)

        Safety validation is done in recovery_advisor() before this is called.
        Phase 4 adds one final check: does the position still exist?

        Returns True if action was executed successfully.
        """
        action = str(recovery_plan.get('action', 'HOLD')).upper()
        if action in ('SKIP', 'NONE'):
            return True

        position = self.positions.get(symbol)
        if not position:
            logger.warning(f"Recovery executor: {symbol} not in positions — skipped")
            return False

        direction = str(position.get('direction', 'LONG')).upper()
        is_long   = direction in ('LONG', 'BUY')
        product   = str(position.get('product', 'CNC')).upper()
        quantity  = int(position.get('quantity', 0) or 0)

        logger.info(f"🔄 PH9 RECOVERY EXECUTE: {symbol} → {action}")

        # ── HOLD — optionally update stop and target ──────────────────────────
        if action == 'HOLD':
            new_stop = recovery_plan.get('new_stop')
            if new_stop and float(new_stop or 0) > 0:
                old_stop = float(position.get('stop_price', 0) or 0)
                if float(new_stop) != old_stop:
                    position['stop_price'] = float(new_stop)
                    if self.orchestrator:
                        try:
                            self.orchestrator.update_position_field(symbol, 'stop_price', float(new_stop))
                        except Exception:
                            pass
                    logger.info(f"   HOLD: stop updated ₹{old_stop:.2f} → ₹{float(new_stop):.2f}")
            rec_target = recovery_plan.get('recovery_target')
            if rec_target and float(rec_target or 0) > 0:
                position['recovery_target'] = float(rec_target)
            position['_recovery_action'] = 'HOLD'
            position['_recovery_days_more'] = recovery_plan.get('hold_days_more', 1)
            return True

        # ── WIDEN_STOP — move stop further to give position breathing room ────
        if action == 'WIDEN_STOP':
            new_stop = recovery_plan.get('new_stop')
            if not new_stop or float(new_stop or 0) <= 0:
                logger.warning(f"   WIDEN_STOP: no new_stop provided — defaulting to HOLD")
                return True
            old_stop = float(position.get('stop_price', 0) or 0)
            new_stop_f = float(new_stop)
            # Safety: widen only if new stop is indeed further away from entry
            entry_price = float(position.get('entry_price', 0) or 0)
            if is_long and new_stop_f >= entry_price:
                logger.warning(f"   WIDEN_STOP: rejected — new stop ₹{new_stop_f:.2f} above entry for LONG")
                return False
            if not is_long and new_stop_f <= entry_price:
                logger.warning(f"   WIDEN_STOP: rejected — new stop ₹{new_stop_f:.2f} below entry for SHORT")
                return False
            position['stop_price'] = new_stop_f
            if self.orchestrator:
                try:
                    self.orchestrator.update_position_field(symbol, 'stop_price', new_stop_f)
                except Exception:
                    pass
            logger.info(f"   WIDEN_STOP: ₹{old_stop:.2f} → ₹{new_stop_f:.2f}")
            position['_recovery_action'] = 'WIDEN_STOP'
            return True

        # ── CONVERT_CNC — convert MIS product to CNC for overnight ───────────
        if action == 'CONVERT_CNC':
            if product == 'CNC':
                logger.info(f"   CONVERT_CNC: already CNC — no action needed")
                return True
            try:
                tx_type = (self.kite.TRANSACTION_TYPE_BUY if is_long
                           else self.kite.TRANSACTION_TYPE_SELL)
                self.kite.convert_position(
                    exchange="NSE",
                    tradingsymbol=symbol,
                    transaction_type=tx_type,
                    position_type="day",
                    quantity=quantity,
                    old_product=self.kite.PRODUCT_MIS,
                    new_product=self.kite.PRODUCT_CNC
                )
                position['product'] = 'CNC'
                if self.orchestrator:
                    try:
                        self.orchestrator.update_position_field(symbol, 'product', 'CNC')
                    except Exception:
                        pass
                logger.info(f"   ✅ CONVERT_CNC: {symbol} MIS → CNC (holding overnight)")
                if self.telegram:
                    try:
                        self.telegram.send_message(
                            f"🔄 RECOVERY: {symbol} converted MIS→CNC\n"
                            f"Will hold overnight for recovery.")
                    except Exception:
                        pass
                position['_recovery_action'] = 'CONVERT_CNC'
                return True
            except Exception as e:
                logger.error(f"   CONVERT_CNC failed: {e} — position stays MIS")
                return False

        # ── SCALE_OUT — partial exit ──────────────────────────────────────────
        if action == 'SCALE_OUT':
            scale_info  = recovery_plan.get('scale_out') or {}
            exit_pct    = int(scale_info.get('exit_pct', 50) or 50)
            exit_pct    = max(25, min(75, exit_pct))   # clamp 25-75%
            exit_qty    = max(1, int(quantity * exit_pct / 100))
            order_type  = str(scale_info.get('order_type', 'MARKET')).upper()
            limit_price = scale_info.get('limit_price')

            try:
                tx_type = (self.kite.TRANSACTION_TYPE_SELL if is_long
                           else self.kite.TRANSACTION_TYPE_BUY)
                _use_limit = (order_type == 'LIMIT' and limit_price)
                order_id = self.kite.place_order(
                    variety=self.kite.VARIETY_REGULAR,
                    exchange=self.kite.EXCHANGE_NSE,
                    tradingsymbol=symbol,
                    transaction_type=tx_type,
                    quantity=exit_qty,
                    product=getattr(self.kite, f'PRODUCT_{product}', self.kite.PRODUCT_MIS),
                    order_type=(self.kite.ORDER_TYPE_LIMIT if _use_limit
                                else self.kite.ORDER_TYPE_MARKET),
                    price=round(float(limit_price), 2) if _use_limit else None,
                    validity=self.kite.VALIDITY_DAY,
                )
                # Update position quantity
                new_qty = quantity - exit_qty
                if new_qty <= 0:
                    self._execute_exit(symbol, 'PH9_RECOVERY_SCALE_OUT')
                else:
                    position['quantity'] = new_qty
                    if self.orchestrator:
                        try:
                            self.orchestrator.update_position_field(symbol, 'quantity', new_qty)
                        except Exception:
                            pass
                logger.info(f"   ✅ SCALE_OUT {exit_pct}%: {exit_qty} shares exited, {new_qty} remain"
                            f" (order {order_id})")
                position['_recovery_action'] = 'SCALE_OUT'
                return True
            except Exception as e:
                logger.error(f"   SCALE_OUT failed: {e}")
                return False

        # ── AVERAGE — add to position to lower average entry price ────────────
        if action == 'AVERAGE':
            avg_info    = recovery_plan.get('average') or {}
            avg_qty     = int(avg_info.get('qty', 0) or 0)
            avg_price   = float(avg_info.get('limit_price', 0) or 0)

            if avg_qty <= 0:
                logger.warning(f"   AVERAGE: qty=0 — skipping")
                return False
            if avg_price <= 0:
                logger.warning(f"   AVERAGE: no limit_price — using MARKET")

            try:
                tx_type = (self.kite.TRANSACTION_TYPE_BUY if is_long
                           else self.kite.TRANSACTION_TYPE_SELL)
                order_id = self.kite.place_order(
                    variety=self.kite.VARIETY_REGULAR,
                    exchange=self.kite.EXCHANGE_NSE,
                    tradingsymbol=symbol,
                    transaction_type=tx_type,
                    quantity=avg_qty,
                    product=getattr(self.kite, f'PRODUCT_{product}', self.kite.PRODUCT_MIS),
                    order_type=(self.kite.ORDER_TYPE_LIMIT if avg_price > 0
                                else self.kite.ORDER_TYPE_MARKET),
                    price=round(avg_price, 2) if avg_price > 0 else None,
                    validity=self.kite.VALIDITY_DAY,
                )
                # Recalculate average entry price
                new_qty = quantity + avg_qty
                fill_price = avg_info.get('new_avg_entry') or avg_price or float(
                    position.get('current_price', avg_price))
                old_avg_val = entry_price * quantity
                new_avg_val = old_avg_val + (fill_price * avg_qty)
                new_avg_entry = new_avg_val / new_qty if new_qty > 0 else entry_price
                position['quantity']    = new_qty
                position['entry_price'] = round(new_avg_entry, 2)
                position['_recovery_averaged'] = True
                if self.orchestrator:
                    try:
                        self.orchestrator.update_position_field(symbol, 'quantity', new_qty)
                        self.orchestrator.update_position_field(symbol, 'entry_price', round(new_avg_entry, 2))
                    except Exception:
                        pass
                # Notify Phase 9 recovery state
                fm = getattr(self, 'fund_manager', None)
                if fm and hasattr(fm, 'mark_averaged'):
                    fm.mark_averaged(symbol)
                logger.info(f"   ✅ AVERAGE: {avg_qty} @ ₹{fill_price:.2f} (order {order_id})")
                logger.info(f"      New: qty={new_qty} avg_entry=₹{new_avg_entry:.2f}")
                position['_recovery_action'] = 'AVERAGE'
                return True
            except Exception as e:
                logger.error(f"   AVERAGE failed: {e}")
                return False

        # ── EXIT — full position exit ─────────────────────────────────────────
        if action == 'EXIT':
            return self._execute_exit(symbol, 'PH9_RECOVERY_EXIT')

        logger.warning(f"   Unknown recovery action: {action}")
        return False

    def close_weakest_position(self, reason: str = 'PH9_CLOSE_WEAKEST') -> bool:
        """
        v1.4.0: PH9 directive — find the position with the worst P&L% and exit it.
        Returns True if a position was closed.
        """
        if not self.positions:
            logger.info("close_weakest_position: no open positions")
            return False
        try:
            worst_sym  = None
            worst_pnl  = float('inf')

            for sym, pos in self.positions.items():
                _entry = float(pos.get('entry_price', 0) or 0)
                _cur   = float(pos.get('current_price', _entry) or _entry)
                _is_long = str(pos.get('direction', 'LONG')).upper() in ('LONG', 'BUY')
                if _entry <= 0:
                    continue
                _pnl_pct = ((_cur - _entry) / _entry * 100) if _is_long else ((_entry - _cur) / _entry * 100)
                if _pnl_pct < worst_pnl:
                    worst_pnl = _pnl_pct
                    worst_sym = sym

            if worst_sym:
                logger.warning(f"🧠 PH9 CLOSE_WEAKEST: {worst_sym} ({worst_pnl:+.2f}%) — {reason}")
                _pos = self.positions[worst_sym]
                return self._execute_exit(worst_sym, _pos, reason)
        except Exception as _e:
            logger.error(f"close_weakest_position error: {_e}")
        return False

    def on_position_closed(self, symbol: str, reason: str = "UNKNOWN"):
        """
        Called when a position is closed.
        
        Args:
            symbol: Stock symbol
            reason: Exit reason
        """
        if symbol in self.positions:
            position = self.positions[symbol]
            self._update_position(symbol, position,
                                  status='CLOSED',
                                  exit_time=datetime.now().isoformat(),
                                  exit_reason=reason)

            # v4.15.0 FIX: Cancel ALL GTTs for this symbol BEFORE removing position
            logger.info(f"   🧹 {symbol}: Cancelling GTTs on position close...")
            self._cancel_all_gtt_for_symbol(symbol)
            
            # Cleanup Kalman
            if symbol in self.kalman_filters:
                del self.kalman_filters[symbol]

            # ISSUE-15: Clear early-warning tracker for this symbol
            self.tcas_pivot_early_signaled.discard(symbol)

            # Remove from active tracking
            del self.positions[symbol]
            
            self._save_positions()
            
            logger.info(f"📤 Position closed: {symbol} - {reason}")

    # ═══════════════════════════════════════════════════════════════════════════
    # CANDLESTICK PATTERN WARNING HANDLER (v1.0.0)
    # ═══════════════════════════════════════════════════════════════════════════

    def handle_pattern_warning(self, signal):
        """Handle bearish candlestick pattern warning from detector.

        Only acts if the symbol has an active LONG position.

        CAUTION: Log + Telegram, monitor next 2 candles
        ALERT: Tighten SL to breakeven, trail 50% of unrealized profit

        Args:
            signal: PatternSignal dataclass from candlestick_pattern_detector
        """
        symbol = signal.symbol

        # Check if we have an active position for this symbol
        position = self.positions.get(symbol)
        if not position:
            return  # No position to protect

        # Only warn on OPEN positions
        if position.get('status') not in ('OPEN', None):
            return

        entry_price = position.get('entry_price', 0)
        current_price = position.get('current_price', position.get('ltp', 0))
        if not entry_price or not current_price:
            return

        unrealized_pnl = current_price - entry_price

        # Only warn if position is in profit (nothing to protect if already losing)
        if unrealized_pnl <= 0:
            logger.info(
                f"TCAS: {symbol} Pin Bar detected but position is in loss "
                f"({unrealized_pnl:.2f}), existing SL handles this"
            )
            return

        if signal.tcas_severity == 'CAUTION':
            # Monitor mode — just notify, don't change stops
            logger.warning(
                f"TCAS CAUTION: {symbol} Bearish Pin Bar at {signal.nearby_levels} | "
                f"Monitoring next 2 candles | Current profit: {unrealized_pnl:.2f}"
            )

            if self.telegram:
                try:
                    self.telegram.send_message(
                        f"TCAS PATTERN CAUTION -- {symbol}\n"
                        f"{'=' * 35}\n"
                        f"Pattern: Bearish Pin Bar\n"
                        f"Wick Ratio: {signal.wick_ratio}x body\n"
                        f"Confidence: {signal.confidence}\n"
                        f"\n"
                        f"Key Level: {', '.join(signal.nearby_levels)}\n"
                        f"\n"
                        f"TCAS Action:\n"
                        f"  Monitoring next 2 candles\n"
                        f"  SL unchanged: {position.get('stop_price', 0):.2f}\n"
                        f"\n"
                        f"{signal.timestamp.strftime('%I:%M %p')} | {signal.timestamp.strftime('%d-%b-%Y')}"
                    )
                except Exception:
                    pass

            self._pattern_watch[symbol] = {
                'severity': 'CAUTION',
                'candles_remaining': 2,
                'detected_at': signal.timestamp
            }

        elif signal.tcas_severity == 'ALERT':
            # Tighten stop-loss to breakeven + trail 50% of profit
            trail_pct = getattr(self.config, 'PATTERN_TCAS_ALERT_TRAIL_PCT', 50) / 100.0
            new_sl = entry_price + (unrealized_pnl * trail_pct)

            old_sl = position.get('stop_price', 0)

            logger.warning(
                f"TCAS ALERT: {symbol} Bearish Pin Bar at {signal.nearby_levels} | "
                f"TIGHTENING SL: {old_sl:.2f} -> {new_sl:.2f} | "
                f"Locking {trail_pct * 100:.0f}% of {unrealized_pnl:.2f} profit"
            )

            # Update the stop-loss via GTT modification
            sl_updated = self._modify_gtt_stop(symbol, new_sl)
            if not sl_updated:
                # GTT modify failed — persist through orchestrator for tracking
                self._update_position(symbol, position, stop_price=new_sl)
                logger.warning(f"   GTT modify failed for {symbol}, stop_price updated in memory only")

            if self.telegram:
                try:
                    self.telegram.send_message(
                        f"TCAS PATTERN ALERT -- {symbol}\n"
                        f"{'=' * 35}\n"
                        f"Pattern: Bearish Pin Bar\n"
                        f"Wick Ratio: {signal.wick_ratio}x body\n"
                        f"Confidence: {signal.confidence}\n"
                        f"\n"
                        f"Key Levels: {', '.join(signal.nearby_levels)}\n"
                        f"\n"
                        f"TCAS Action:\n"
                        f"  Stop Loss: {old_sl:.2f} -> {new_sl:.2f}\n"
                        f"  Locking: {trail_pct * 100:.0f}% of {unrealized_pnl:.2f} profit\n"
                        f"\n"
                        f"{signal.timestamp.strftime('%I:%M %p')} | {signal.timestamp.strftime('%d-%b-%Y')}"
                    )
                except Exception:
                    pass

            self._pattern_watch[symbol] = {
                'severity': 'ALERT',
                'candles_remaining': 0,
                'detected_at': signal.timestamp,
                'sl_tightened_to': new_sl
            }

    # ═══════════════════════════════════════════════════════════════════════════
    # v1.0.0: ORB ADVISORY PULL (passive scoreboard queries)
    # ═══════════════════════════════════════════════════════════════════════════

    def set_orb_advisory(self, orb_advisory):
        """Set reference to ORB Advisory for pull-model queries.

        Called by orchestrator after both modules are initialized.

        Args:
            orb_advisory: ORBAdvisory instance (or None)
        """
        self._orb_advisory = orb_advisory

    def check_orb_for_position(self, symbol: str) -> None:
        """Pull ORB status for an open position and act accordingly.

        DOWNSIDE_BREAKDOWN → tighten SL to breakeven (protect capital)
        UPSIDE_BREAKOUT    → switch to trailing mode (ride the move)

        Called from the TCAS monitoring loop for each open position.
        This is a PULL model — Phase 4 decides when to query.

        Args:
            symbol: Stock symbol with an open position
        """
        if not self._orb_advisory:
            return

        status = self._orb_advisory.get_status(symbol)
        if not status:
            return

        orb_status = status.get('status', '')

        position = self.positions.get(symbol)
        if not position or position.get('status') not in ('OPEN', None):
            return

        entry_price = position.get('entry_price', 0)
        current_price = position.get('current_price', position.get('ltp', 0))
        if not entry_price or not current_price:
            return

        if orb_status == 'DOWNSIDE_BREAKDOWN':
            # Tighten SL to breakeven to protect capital
            old_sl = position.get('stop_price', 0)
            if entry_price > old_sl:
                logger.warning(
                    f"ORB TCAS: {symbol} DOWNSIDE BREAKDOWN → "
                    f"Tightening SL to breakeven: {old_sl:.2f} → {entry_price:.2f}"
                )
                sl_updated = self._modify_gtt_stop(symbol, entry_price)
                if not sl_updated:
                    self._update_position(symbol, position, stop_price=entry_price)
                    logger.warning(f"   GTT modify failed for {symbol}, stop_price updated in memory only")

                if self.telegram:
                    try:
                        self.telegram.send_message(
                            f"ORB TCAS -- {symbol}\n"
                            f"{'=' * 35}\n"
                            f"Event: DOWNSIDE BREAKDOWN\n"
                            f"IB High: {status.get('ib_high', 0):.2f}\n"
                            f"IB Low:  {status.get('ib_low', 0):.2f}\n"
                            f"\n"
                            f"Action: SL → Breakeven\n"
                            f"  Old SL: {old_sl:.2f}\n"
                            f"  New SL: {entry_price:.2f}\n"
                            f"\n"
                            f"Reason: Protect capital on breakdown"
                        )
                    except Exception:
                        pass

        elif orb_status == 'UPSIDE_BREAKOUT':
            # Switch to trailing mode — ride the breakout move
            unrealized_pnl = current_price - entry_price
            if unrealized_pnl > 0:
                # Trail % of unrealized profit (from config, default 50%)
                trail_pct = getattr(self.config, 'ORB_BREAKOUT_TRAIL_PCT', 50) / 100.0
                trail_sl = entry_price + (unrealized_pnl * trail_pct)
                old_sl = position.get('stop_price', 0)

                if trail_sl > old_sl:
                    logger.info(
                        f"ORB TRAIL: {symbol} UPSIDE BREAKOUT → "
                        f"Trailing SL: {old_sl:.2f} → {trail_sl:.2f} "
                        f"(locking {trail_pct * 100:.0f}% of {unrealized_pnl:.2f} profit)"
                    )
                    sl_updated = self._modify_gtt_stop(symbol, trail_sl)
                    if not sl_updated:
                        self._update_position(symbol, position, stop_price=trail_sl)

                    if self.telegram:
                        try:
                            self.telegram.send_message(
                                f"ORB TRAIL -- {symbol}\n"
                                f"{'=' * 35}\n"
                                f"Event: UPSIDE BREAKOUT\n"
                                f"IB High: {status.get('ib_high', 0):.2f}\n"
                                f"Target:  {status.get('breakout_target', 0):.2f}\n"
                                f"\n"
                                f"Action: Trailing Mode\n"
                                f"  Old SL: {old_sl:.2f}\n"
                                f"  New SL: {trail_sl:.2f}\n"
                                f"  Locked: {trail_pct * 100:.0f}% of +{unrealized_pnl:.2f}\n"
                                f"\n"
                                f"Reason: Ride the breakout move"
                            )
                        except Exception:
                            pass

    # ═══════════════════════════════════════════════════════════════════════════
    # KALMAN FILTER INTEGRATION
    # ═══════════════════════════════════════════════════════════════════════════

    def _init_kalman_for_position(self, symbol: str, position: Dict):
        """Initialize Kalman MAP filter for a position (6-state multi-observable)"""
        try:
            from kalman_filter import KalmanMAPFilter

            entry_price = position.get('entry_price', 0)
            if entry_price > 0:
                # Check for saved calibration (Phase D warm start)
                Q_init, R_init = self._load_kalman_calibration(symbol)
                kf = KalmanMAPFilter(Q_init=Q_init, R_init=R_init)
                kf.set_symbol(symbol)
                entry_rsi = position.get('entry_rsi', 50.0) or 50.0
                kf.initialize(entry_price, rsi=entry_rsi)
                self.kalman_filters[symbol] = kf
                cal_tag = " (warm)" if Q_init else ""
                logger.debug(f"   KalmanMAP initialized{cal_tag} for {symbol} @ {entry_price:.2f}")
        except ImportError:
            logger.warning("Kalman MAP filter module not available")
        except Exception as e:
            logger.error(f"Kalman MAP init failed for {symbol}: {e}")

    def _load_kalman_calibration(self, symbol: str):
        """Load saved Q/R calibration for warm start (Phase D)."""
        try:
            from unified_data_manager import get_db
            db = get_db()
            cal = db.get_kalman_calibration(symbol, min_observations=30)
            if cal:
                logger.debug(f"   Kalman warm start for {symbol}: {cal['observations']} obs")
                return cal['Q_converged'], cal['R_converged']
        except Exception as e:
            logger.debug(f"   Kalman calibration load skipped for {symbol}: {e}")
        return None, None

    def _save_kalman_calibration(self, symbol: str):
        """Save converged Q/R calibration to DB (Phase D)."""
        try:
            if symbol not in self.kalman_filters:
                return
            kf = self.kalman_filters[symbol]
            if not hasattr(kf, 'get_calibration'):
                return
            if kf.observation_count < 10:
                return  # Not enough data to save

            from unified_data_manager import get_db
            cal = kf.get_calibration()
            get_db().save_kalman_calibration(symbol, cal)
            logger.debug(f"   Kalman calibration saved: {symbol} ({cal['observations']} obs)")
        except Exception as e:
            logger.debug(f"   Kalman calibration save skipped for {symbol}: {e}")

    def _update_kalman(self, symbol: str, current_price: float, atr: float = 0,
                       rsi: float = None, volume_ratio: float = None) -> KalmanState:
        """Update Kalman MAP filter with price + RSI + volume.

        Args:
            symbol: Stock symbol
            current_price: Current observed price
            atr: Average True Range (for reference, not directly used by MAP)
            rsi: Current RSI value (0-100). If None, uses position tracking data.
            volume_ratio: Current volume / expected volume. If None, defaults to 1.0.
        """
        state = KalmanState(price=current_price)

        if symbol not in self.kalman_filters:
            return state

        try:
            kf = self.kalman_filters[symbol]

            # Resolve RSI and volume if not passed directly
            if rsi is None:
                position = self.positions.get(symbol, {})
                rsi = position.get('phase4_tracking', {}).get('current_rsi', 50.0) or 50.0
            if volume_ratio is None:
                volume_ratio = 1.0

            # Normalize volume_ratio to momentum-like value for MAP state vector
            # volume_ratio > 1 means above-average volume -> positive momentum
            vol_momentum = volume_ratio - 1.0  # Center at 0

            # MAP filter: process_measurement does predict + update
            map_state = kf.process_measurement(current_price, rsi=rsi,
                                               volume_momentum=vol_momentum)

            # Populate KalmanState from MAP output
            state.price = map_state.price
            state.velocity = map_state.velocity
            state.acceleration = map_state.acceleration
            state.prediction_15min = map_state.prediction_15min
            state.uncertainty = map_state.uncertainty

            # MAP extended fields
            state.rsi_filtered = map_state.rsi_filtered
            state.rsi_momentum = map_state.rsi_momentum
            state.volume_momentum = map_state.volume_momentum
            state.inverse_v_top = map_state.inverse_v_top
            state.crash_accelerating = map_state.crash_accelerating
            state.exit_signal_confidence = map_state.exit_signal_confidence
            state.v_recovery_bottom = map_state.v_recovery_bottom
            state.v_recovery_confidence = map_state.v_recovery_confidence
            state.regime = map_state.regime
            state.prediction_1hour = map_state.prediction_1hour
            state.prediction_confidence = map_state.prediction_confidence
            state.rsi_price_divergence = map_state.rsi_price_divergence
            state.volume_price_divergence = map_state.volume_price_divergence

            # Interpret velocity (backward compatible)
            if state.velocity > 0.1:
                state.interpretation = "STRONG_UP"
            elif state.velocity > 0.02:
                state.interpretation = "DRIFTING_UP"
            elif state.velocity < -0.1:
                state.interpretation = "STRONG_DOWN"
            elif state.velocity < -0.02:
                state.interpretation = "DRIFTING_DOWN"
            else:
                state.interpretation = "NEUTRAL"

        except Exception as e:
            logger.error(f"Kalman MAP update failed for {symbol}: {e}")

        return state

    # ═══════════════════════════════════════════════════════════════════════════
    # TCAS SYSTEM (Stop-Loss Collision Avoidance)
    # ═══════════════════════════════════════════════════════════════════════════
    
    def _calculate_tcas_status(self, position: Dict, current_price: float, atr: float) -> TCASStatus:
        """
        Calculate TCAS status for a position.
        
        v4.13.0: Direction-aware for LONG and SHORT positions.
        
        TCAS Alert Levels:
        - CLEAR: > 2.0 ATR from stop (safe)
        - TA: 1.5-2.0 ATR (Traffic Advisory - monitor closely)
        - RA: 0.75-1.5 ATR (Resolution Advisory - ChatGPT consultation)
        - ALIM: < 0.75 ATR (IMMEDIATE EXIT - no consultation)
        """
        status = TCASStatus()
        
        stop_price = position.get('stop_price', 0)
        entry_price = position.get('entry_price', 0)
        direction = self._get_position_direction(position)
        
        if atr <= 0 or stop_price <= 0:
            return status
        
        # v4.13.0: Direction-aware distance calculation
        distance_to_stop = self._calculate_distance_to_stop(position, current_price)
        distance_atr = distance_to_stop / atr if atr > 0 else 999
        
        status.distance_to_stop_atr = distance_atr
        
        # Get Kalman velocity for tau estimate
        kalman_state = self._get_kalman_state(position.get('symbol', ''))
        velocity = kalman_state.velocity if kalman_state else 0
        
        # v4.13.0: Direction-aware tau calculation
        approaching_stop = self._is_approaching_stop(velocity, direction)
        if approaching_stop:
            status.tau_estimate = abs(distance_to_stop / velocity) if velocity != 0 else 999
        else:
            status.tau_estimate = 999  # Not approaching stop
        
        # Determine alert level (same thresholds, direction already handled)
        if distance_atr < self.TCAS_ALIM_THRESHOLD:
            status.alert_level = TCASAlert.ALIM
            status.recommended_action = "IMMEDIATE_EXIT"
        elif distance_atr < self.TCAS_RA_THRESHOLD:
            status.alert_level = TCASAlert.RA
            status.recommended_action = "CONSULT_CHATGPT"
        elif distance_atr < self.TCAS_TA_THRESHOLD:
            status.alert_level = TCASAlert.TA
            status.recommended_action = "MONITOR_CLOSELY"
        else:
            status.alert_level = TCASAlert.CLEAR
            status.recommended_action = "NORMAL_MONITORING"
        
        return status
    
    def _get_kalman_state(self, symbol: str) -> Optional[KalmanState]:
        """Get current Kalman state for symbol (includes MAP fields if available)"""
        position = self.positions.get(symbol)
        if position and 'phase4_tracking' in position:
            tracking = position['phase4_tracking']
            if 'kalman_state' in tracking:
                ks = tracking['kalman_state']
                return KalmanState(
                    price=ks.get('price', 0),
                    velocity=ks.get('velocity', 0),
                    acceleration=ks.get('acceleration', 0),
                    prediction_15min=ks.get('prediction_15min', 0),
                    uncertainty=ks.get('uncertainty', 1.0),
                    interpretation=ks.get('interpretation', 'UNKNOWN'),
                    # MAP fields (graceful defaults for backward compatibility)
                    rsi_filtered=ks.get('rsi_filtered', 50.0),
                    rsi_momentum=ks.get('rsi_momentum', 0.0),
                    volume_momentum=ks.get('volume_momentum', 0.0),
                    inverse_v_top=ks.get('inverse_v_top', False),
                    crash_accelerating=ks.get('crash_accelerating', False),
                    exit_signal_confidence=ks.get('exit_signal_confidence', 0.0),
                    v_recovery_bottom=ks.get('v_recovery_bottom', False),
                    v_recovery_confidence=ks.get('v_recovery_confidence', 0.0),
                    regime=ks.get('regime', 'UNKNOWN'),
                    prediction_1hour=ks.get('prediction_1hour', 0.0),
                    prediction_confidence=ks.get('prediction_confidence', 0.0),
                    rsi_price_divergence=ks.get('rsi_price_divergence', False),
                    volume_price_divergence=ks.get('volume_price_divergence', False),
                )
        return None

    # ═══════════════════════════════════════════════════════════════════════════
    # ENSEMBLE PREDICTION (Advisory Only — does NOT trigger exits)
    # ═══════════════════════════════════════════════════════════════════════════

    def _update_ensemble_prediction(self, symbol: str, position: Dict,
                                     current_price: float, kalman_state) -> None:
        """
        Generate ensemble prediction for a position.
        Called during each monitoring cycle, throttled to every 5 minutes.
        Results cached in self._ensemble_cache[symbol].

        This is ADVISORY ONLY — does not trigger any trades.
        """
        if not self._ensemble_engine:
            return

        now = datetime.now()
        last_update = self._ensemble_last_update.get(symbol)
        if last_update and (now - last_update).total_seconds() < self._ensemble_update_interval:
            return  # Use cached result

        try:
            # Gather price history for this symbol
            price_history = self._get_recent_prices(symbol, n_bars=20)
            if not price_history or len(price_history) < 10:
                return

            prices = [p['price'] for p in price_history]
            timestamps = [p['minutes_from_entry'] for p in price_history]

            velocity = getattr(kalman_state, 'velocity', 0) if kalman_state else 0
            acceleration = getattr(kalman_state, 'acceleration', 0) if kalman_state else 0
            tracking = position.get('phase4_tracking', {})
            atr = tracking.get('atr', position.get('atr', 1.0))

            result = self._ensemble_engine.predict(
                prices=prices,
                timestamps=timestamps,
                current_price=current_price,
                kalman_state={"velocity": velocity, "acceleration": acceleration},
                prediction_horizon=30,   # 30 minutes ahead
                prediction_step=2,
                atr=atr,
            )

            # Cache the result
            self._ensemble_cache[symbol] = result
            self._ensemble_last_update[symbol] = now

            # Log ensemble summary (debug level)
            logger.debug(
                f"   Ensemble {symbol}: "
                f"Hurst={result.hurst:.2f} ({result.regime}) "
                f"Conf={result.confidence:.0%} "
                f"Weights=[K:{result.weights.get('kalman', 0):.0%} "
                f"L:{result.weights.get('linear', 0):.0%} "
                f"P:{result.weights.get('polynomial', 0):.0%}] "
                f"Pred@30m={result.ensemble_path[-1].p:.2f}"
            )

            # Store in position dict so it's accessible everywhere
            if 'phase4_tracking' not in position:
                position['phase4_tracking'] = {}
            position['phase4_tracking']['ensemble_prediction'] = {
                'hurst': result.hurst,
                'regime': result.regime,
                'confidence': result.confidence,
                'weights': result.weights,
                'predicted_30m': result.ensemble_path[-1].p if result.ensemble_path else None,
                'models_used': result.models_used,
                'updated_at': now.isoformat(),
            }

        except Exception as e:
            logger.debug(f"   Ensemble prediction failed for {symbol}: {e}")

    def _get_recent_prices(self, symbol: str, n_bars: int = 20) -> list:
        """
        Get recent price snapshots for ensemble prediction.
        Uses accumulated price_history buffer, falls back to entry+current.

        Returns:
            List of {"price": float, "minutes_from_entry": float}
        """
        # Option A: Use price_history buffer (built each monitoring cycle)
        if symbol in self._price_history and len(self._price_history[symbol]) >= 2:
            buf = self._price_history[symbol][-n_bars:]
            if buf:
                entry_ts = buf[0]['timestamp']
                return [
                    {
                        "price": p['price'],
                        "minutes_from_entry": (p['timestamp'] - entry_ts).total_seconds() / 60,
                    }
                    for p in buf
                ]

        # Option B: Minimal — use just entry and current from position
        position = self.positions.get(symbol, {})
        tracking = position.get('phase4_tracking', {})
        entry_price = position.get('entry_price', tracking.get('entry_price', 0))
        current_price = tracking.get('current_price', position.get('current_price', 0))
        entry_time = position.get('entry_time')
        if isinstance(entry_time, str):
            try:
                entry_time = datetime.fromisoformat(entry_time)
            except (ValueError, TypeError):
                entry_time = datetime.now() - timedelta(minutes=30)
        if not entry_time:
            entry_time = datetime.now() - timedelta(minutes=30)
        elapsed = (datetime.now() - entry_time).total_seconds() / 60

        if entry_price > 0 and current_price > 0:
            return [
                {"price": entry_price, "minutes_from_entry": 0},
                {"price": current_price, "minutes_from_entry": elapsed},
            ]

        return []

    def _record_price_snapshot(self, symbol: str, current_price: float):
        """Record a price snapshot for ensemble prediction history."""
        if symbol not in self._price_history:
            self._price_history[symbol] = []
        self._price_history[symbol].append({
            'price': current_price,
            'timestamp': datetime.now(),
        })
        # Keep last 100 snapshots (avoid unbounded growth)
        if len(self._price_history[symbol]) > 100:
            self._price_history[symbol] = self._price_history[symbol][-100:]

    # ═══════════════════════════════════════════════════════════════════════════
    # ILS SYSTEM (Profit Target Landing)
    # ═══════════════════════════════════════════════════════════════════════════
    
    def _calculate_ils_status(self, position: Dict, current_price: float) -> ILSStatus:
        """
        Calculate ILS landing status for a position.
        
        v4.13.0: Direction-aware for LONG and SHORT positions.
        
        ILS Phases:
        - CRUISE: < 25% to target
        - OUTER_MARKER: 25-50%
        - MIDDLE_MARKER: 50-75% (activate trailing)
        - INNER_MARKER: 75-90% (tighten trailing)
        - DECISION_HEIGHT: 90-95%
        - LANDING: > 95%
        """
        status = ILSStatus()
        
        entry_price = position.get('entry_price', 0)
        target_price = position.get('target_price', 0)
        direction = self._get_position_direction(position)
        
        # v4.13.0: Direction-aware validation
        if entry_price <= 0:
            return status
        
        # For LONG: target > entry; For SHORT: target < entry
        if direction == 'LONG' and target_price <= entry_price:
            return status
        if direction == 'SHORT' and target_price >= entry_price:
            return status
        
        # v4.13.0: Direction-aware progress calculation
        progress_pct = self._calculate_progress_to_target(position, current_price)
        status.progress_pct = max(0, progress_pct)
        
        # Determine landing phase
        if progress_pct >= 95:
            status.landing_phase = LandingPhase.LANDING
            status.trailing_active = True
        elif progress_pct >= 90:
            status.landing_phase = LandingPhase.DECISION_HEIGHT
            status.trailing_active = True
        elif progress_pct >= 75:
            status.landing_phase = LandingPhase.INNER_MARKER
            status.trailing_active = True
        elif progress_pct >= 50:
            status.landing_phase = LandingPhase.MIDDLE_MARKER
            status.trailing_active = True
        elif progress_pct >= 25:
            status.landing_phase = LandingPhase.OUTER_MARKER
            status.trailing_active = False
        else:
            status.landing_phase = LandingPhase.CRUISE
            status.trailing_active = False
        
        # Calculate glideslope (expected progress based on time)
        entry_time = datetime.fromisoformat(position.get('entry_time', datetime.now().isoformat()))
        time_elapsed = (datetime.now() - entry_time).total_seconds() / 60  # minutes
        expected_progress = min(100, time_elapsed * 0.5)  # Expect ~0.5% progress per minute
        status.glideslope_deviation = progress_pct - expected_progress
        
        # v4.13.0: Direction-aware trailing stop
        if status.trailing_active:
            regime_params = self._get_regime_params()
            trail_pct = regime_params.get('trail_pct', 1.5)
            
            # Tighter trail at higher phases
            if status.landing_phase == LandingPhase.LANDING:
                trail_pct *= 0.5
            elif status.landing_phase == LandingPhase.DECISION_HEIGHT:
                trail_pct *= 0.7
            elif status.landing_phase == LandingPhase.INNER_MARKER:
                trail_pct *= 0.85
            
            # Direction-aware trailing stop
            if direction == 'SHORT':
                # v4.13.1: Use max_price (LONG) or min_price (SHORT) for trailing
                if direction == "SHORT":
                    # Trail from MIN price reached (protect short profit)
                    min_price = position.get("min_price", entry_price)
                    status.trailing_stop = min_price * (1 + trail_pct / 100)
                else:
                    # Trail from MAX price reached (lock long profit)
                    max_price = position.get("max_price", entry_price)
                    status.trailing_stop = max_price * (1 - trail_pct / 100)
        
        return status

    # ═══════════════════════════════════════════════════════════════════════════
    # HEALTH SCORE SYSTEM (Go-Around Gates)
    # ═══════════════════════════════════════════════════════════════════════════
    
    def _calculate_health_score(self, position: Dict, current_price: float, 
                                 tcas: TCASStatus, ils: ILSStatus, 
                                 kalman: KalmanState) -> HealthScore:
        """
        Calculate health score for a position.
        
        v4.13.0: Direction-aware for LONG and SHORT positions.
        v4.8.0: Includes Kalman prediction component (15pts).
        
        Components (100 total):
        - P&L Score: 30 points
        - Momentum Score: 20 points (Kalman velocity)
        - TCAS Score: 25 points
        - Time Score: 10 points
        - Prediction Score: 15 points (Kalman 15-min forecast)
        """
        health = HealthScore()
        components = {}
        
        entry_price = position.get('entry_price', current_price)
        direction = self._get_position_direction(position)
        
        # 1. P&L Score (30 points) - v4.13.0: Direction-aware
        pnl_pct = self._calculate_pnl_pct(position, current_price)
        if pnl_pct >= 2.0:
            components['pnl'] = 30
        elif pnl_pct >= 1.0:
            components['pnl'] = 25
        elif pnl_pct >= 0:
            components['pnl'] = 20
        elif pnl_pct >= -1.0:
            components['pnl'] = 10
        else:
            components['pnl'] = max(0, 10 + pnl_pct * 5)  # Degrade further for big losses
        
        # 2. Momentum Score (20 points) - v4.13.0: Direction-aware velocity
        if kalman:
            velocity = kalman.velocity
            
            # v4.13.0: For SHORT positions, invert velocity interpretation
            effective_velocity = velocity if direction == 'LONG' else -velocity
            
            if effective_velocity > 0.1:
                components['momentum'] = 20
            elif effective_velocity > 0.02:
                components['momentum'] = 16
            elif effective_velocity > -0.02:
                components['momentum'] = 12
            elif effective_velocity > -0.1:
                components['momentum'] = 6
            else:
                components['momentum'] = 0
            
            # v4.10.0: Add acceleration modifier (±5 points)
            if hasattr(kalman, 'acceleration') and kalman.acceleration:
                # v4.13.0: Direction-aware acceleration
                effective_accel = kalman.acceleration if direction == 'LONG' else -kalman.acceleration
                
                if effective_accel > 0.01:  # Accelerating favorably
                    components['momentum'] = min(25, components['momentum'] + 5)
                    logger.debug(f"   📈 Acceleration bonus: +5 (accel={kalman.acceleration:.4f})")
                elif effective_accel < -0.01:  # Accelerating unfavorably
                    components['momentum'] = max(0, components['momentum'] - 5)
                    logger.debug(f"   📉 Acceleration penalty: -5 (accel={kalman.acceleration:.4f})")
        else:
            components['momentum'] = 12  # Neutral if no Kalman
        
        # 3. TCAS Score (25 points) - Already direction-aware via _calculate_tcas_status
        if tcas.alert_level == TCASAlert.CLEAR:
            components['tcas'] = 25
        elif tcas.alert_level == TCASAlert.TA:
            components['tcas'] = 15
        elif tcas.alert_level == TCASAlert.RA:
            components['tcas'] = 5
        else:  # ALIM
            components['tcas'] = 0
        
        # 4. Time Score (10 points)
        entry_time = datetime.fromisoformat(position.get('entry_time', datetime.now().isoformat()))
        hold_minutes = (datetime.now() - entry_time).total_seconds() / 60
        
        if hold_minutes < 30:
            components['time'] = 10
        elif hold_minutes < 60:
            components['time'] = 8
        elif hold_minutes < 120:
            components['time'] = 5
        else:
            components['time'] = 3
        
        # 5. Prediction Score (15 points) - v4.13.0: Direction-aware
        if kalman and hasattr(kalman, 'prediction_15min') and kalman.prediction_15min:
            # Compare prediction to current price
            predicted_change_pct = ((kalman.prediction_15min - current_price) / current_price) * 100
            
            # v4.13.0: For SHORT, price falling is favorable
            effective_change = predicted_change_pct if direction == 'LONG' else -predicted_change_pct
            
            if effective_change > 0.5:
                # Strong improvement predicted - HOLD!
                components['prediction'] = 15
            elif effective_change > 0.2:
                # Moderate improvement
                components['prediction'] = 12
            elif effective_change > -0.2:
                # Stable
                components['prediction'] = 8
            elif effective_change > -0.5:
                # Slight deterioration
                components['prediction'] = 4
            else:
                # Significant deterioration predicted
                components['prediction'] = 0
        else:
            components['prediction'] = 8  # Neutral if no prediction
        
        # Calculate total
        health.total_score = sum(components.values())
        health.component_scores = components
        
        # Interpretation
        if health.total_score >= self.HEALTH_MARGINAL:
            health.interpretation = "HEALTHY"
        elif health.total_score >= self.HEALTH_UNSTABLE:
            health.interpretation = "MARGINAL"
        elif health.total_score >= self.HEALTH_CRITICAL:
            health.interpretation = "UNSTABLE"
        else:
            health.interpretation = "CRITICAL"
        
        # Check gates
        health.gate_status = self._check_gates(position, health.total_score)
        
        return health
    
    def _check_gates(self, position: Dict, score: float) -> Dict:
        """Check health gates based on hold time"""
        entry_time = datetime.fromisoformat(position.get('entry_time', datetime.now().isoformat()))
        hold_minutes = (datetime.now() - entry_time).total_seconds() / 60
        
        gates = {}
        
        # Gate 1: After 15 min, score >= 60
        if hold_minutes >= 15:
            gates['GATE_1'] = {'required': 60, 'actual': score, 'passed': score >= 60}
        
        # Gate 2: After 30 min, score >= 50
        if hold_minutes >= 30:
            gates['GATE_2'] = {'required': 50, 'actual': score, 'passed': score >= 50}
        
        # Gate 3: After 60 min, score >= 40
        if hold_minutes >= 60:
            gates['GATE_3'] = {'required': 40, 'actual': score, 'passed': score >= 40}
        
        # Gate 4: After 90 min, score >= 30
        if hold_minutes >= 90:
            gates['GATE_4'] = {'required': 30, 'actual': score, 'passed': score >= 30}
        
        return gates

    # ═══════════════════════════════════════════════════════════════════════════
    # v4.8.0 NEW: MULTI-TIMEFRAME ANALYSIS
    # ═══════════════════════════════════════════════════════════════════════════
    
    def _get_multi_timeframe_context(self, symbol: str) -> Dict:
        """
        Fetch weekly and daily trend for swing trading context.
        
        This provides the "PhD-level" context ChatGPT needs to make intelligent
        decisions about whether short-term dips are noise or real danger.
        
        Returns:
            {
                'weekly_trend': 'UPTREND' | 'DOWNTREND' | 'NEUTRAL',
                'weekly_strength': 0-100,
                'daily_trend': 'UPTREND' | 'DOWNTREND' | 'NEUTRAL',
                'daily_strength': 0-100,
                'weekly_support': price,
                'weekly_resistance': price,
                'trend_alignment': 'ALIGNED' | 'MIXED' | 'CONFLICTING'
            }
        """
        try:
            # Get instrument token for symbol
            instrument_token = None
            try:
                instruments = self.kite.instruments("NSE")
                for inst in instruments:
                    if inst['tradingsymbol'] == symbol:
                        instrument_token = inst['instrument_token']
                        break
            except:
                pass
            
            if not instrument_token:
                logger.debug(f"{symbol}: Instrument token not found for multi-timeframe")
                return self._default_timeframe_context()
            
            # Fetch weekly data (last 20 weeks)
            from_date = datetime.now() - timedelta(days=140)
            to_date = datetime.now()
            
            try:
                weekly_data = self.kite.historical_data(
                    instrument_token, from_date, to_date, interval="week"
                )
            except Exception as e:
                logger.debug(f"{symbol}: Weekly data fetch failed: {e}")
                weekly_data = []
            
            # Fetch daily data (last 30 days)
            from_date = datetime.now() - timedelta(days=30)
            try:
                daily_data = self.kite.historical_data(
                    instrument_token, from_date, to_date, interval="day"
                )
            except Exception as e:
                logger.debug(f"{symbol}: Daily data fetch failed: {e}")
                daily_data = []
            
            # Analyze trends
            weekly_trend, weekly_strength, weekly_support, weekly_resistance = self._analyze_trend(weekly_data)
            daily_trend, daily_strength, _, _ = self._analyze_trend(daily_data)
            
            # Determine alignment
            if weekly_trend == daily_trend:
                trend_alignment = "ALIGNED"
            elif weekly_trend == "NEUTRAL" or daily_trend == "NEUTRAL":
                trend_alignment = "MIXED"
            else:
                trend_alignment = "CONFLICTING"
            
            result = {
                'weekly_trend': weekly_trend,
                'weekly_strength': weekly_strength,
                'daily_trend': daily_trend,
                'daily_strength': daily_strength,
                'weekly_support': weekly_support,
                'weekly_resistance': weekly_resistance,
                'trend_alignment': trend_alignment
            }
            
            # Log for visibility
            logger.info(f"   📊 {symbol} Multi-TF: Weekly={weekly_trend}({weekly_strength}%), "
                       f"Daily={daily_trend}({daily_strength}%), Alignment={trend_alignment}")
            
            return result
            
        except Exception as e:
            logger.error(f"Multi-timeframe analysis error for {symbol}: {e}")
            return self._default_timeframe_context()
    
    def _analyze_trend(self, ohlc_data: list) -> tuple:
        """Analyze trend from OHLC data. Returns (trend, strength, support, resistance)"""
        if not ohlc_data or len(ohlc_data) < 5:
            return "NEUTRAL", 50, 0, 0
        
        try:
            closes = [candle['close'] for candle in ohlc_data]
            highs = [candle['high'] for candle in ohlc_data]
            lows = [candle['low'] for candle in ohlc_data]
            
            short_ma = sum(closes[-5:]) / 5
            long_ma = sum(closes[-20:]) / min(20, len(closes))
            current = closes[-1]
            
            support = min(lows[-10:]) if len(lows) >= 10 else min(lows)
            resistance = max(highs[-10:]) if len(highs) >= 10 else max(highs)
            
            if current > short_ma > long_ma:
                trend = "UPTREND"
                strength = min(100, int(((current - long_ma) / long_ma) * 1000))
            elif current < short_ma < long_ma:
                trend = "DOWNTREND"
                strength = min(100, int(((long_ma - current) / long_ma) * 1000))
            else:
                trend = "NEUTRAL"
                strength = 50
            
            return trend, strength, support, resistance
        except:
            return "NEUTRAL", 50, 0, 0
    
    def _default_timeframe_context(self) -> Dict:
        """Return default timeframe context when analysis fails"""
        return {
            'weekly_trend': 'NEUTRAL', 'weekly_strength': 50,
            'daily_trend': 'NEUTRAL', 'daily_strength': 50,
            'weekly_support': 0, 'weekly_resistance': 0,
            'trend_alignment': 'NEUTRAL'
        }
    
    # ═══════════════════════════════════════════════════════════════════════════
    # v4.8.0 NEW: TRADING COST CALCULATOR
    # ═══════════════════════════════════════════════════════════════════════════
    
    def _calculate_trading_costs(self, symbol: str, quantity: int, 
                                  entry_price: float, exit_price: float,
                                  direction: str = 'LONG') -> Dict:
        """
        Calculate net P&L after all trading costs.
        
        v4.13.0: Direction-aware P&L calculation.
        
        This prevents the "exit with ₹1 profit that's actually a net loss" problem.
        """
        try:
            # v4.13.0: Direction-aware Gross P&L
            if direction == 'SHORT':
                gross_pnl = (entry_price - exit_price) * quantity
            else:  # LONG
                gross_pnl = (exit_price - entry_price) * quantity
            
            trade_value = entry_price * quantity
            gross_pnl_pct = (gross_pnl / trade_value) * 100 if trade_value > 0 else 0
            
            # Fee calculation (NSE equity)
            brokerage = 40.0  # ₹20 × 2 orders
            stt = exit_price * quantity * 0.001  # 0.1% on sell
            gst_on_brokerage = brokerage * 0.18
            exchange_charges = trade_value * 0.0000345 * 2
            stamp_duty = trade_value * 0.00015
            sebi_charges = trade_value * 0.000001 * 2
            
            other = gst_on_brokerage + exchange_charges + stamp_duty + sebi_charges
            total_fees = brokerage + stt + other
            
            # Net P&L
            net_pnl = gross_pnl - total_fees
            net_pnl_pct = (net_pnl / trade_value) * 100 if trade_value > 0 else 0
            
            # Breakeven
            breakeven_price = entry_price + (total_fees / quantity) if quantity > 0 else entry_price
            min_exit_for_profit = breakeven_price + 0.05
            
            # Warning
            warning = None
            if gross_pnl > 0 and net_pnl < 0:
                warning = f"ℹ️ Gross profit ₹{gross_pnl:.0f} < fees ₹{total_fees:.0f}. Net if exit: -₹{abs(net_pnl):.0f}. (Fees are sunk cost — evaluate on price direction, not fee impact)"
            elif net_pnl < -50:
                warning = f"⚠️ Position in significant loss: Net ₹{net_pnl:.0f}"
            
            result = {
                'gross_pnl': round(gross_pnl, 2),
                'gross_pnl_pct': round(gross_pnl_pct, 2),
                'fees': {
                    'brokerage': round(brokerage, 2),
                    'stt': round(stt, 2),
                    'other': round(other, 2),
                    'total': round(total_fees, 2)
                },
                'net_pnl': round(net_pnl, 2),
                'net_pnl_pct': round(net_pnl_pct, 2),
                'breakeven_price': round(breakeven_price, 2),
                'min_exit_for_profit': round(min_exit_for_profit, 2),
                'warning': warning
            }
            
            # Log for visibility
            if warning:
                logger.warning(f"   💰 {symbol} Cost: {warning}")
            else:
                logger.info(f"   💰 {symbol} Cost: Gross ₹{gross_pnl:.0f} - Fees ₹{total_fees:.0f} = Net ₹{net_pnl:.0f}")
            
            return result
            
        except Exception as e:
            logger.error(f"Cost calculation error for {symbol}: {e}")
            return {
                'gross_pnl': 0, 'gross_pnl_pct': 0,
                'fees': {'brokerage': 0, 'stt': 0, 'other': 0, 'total': 0},
                'net_pnl': 0, 'net_pnl_pct': 0,
                'breakeven_price': entry_price, 'min_exit_for_profit': entry_price,
                'warning': None
            }

    # ═══════════════════════════════════════════════════════════════════════════
    # GTT ORDER MANAGEMENT
    # ═══════════════════════════════════════════════════════════════════════════
    
    def _reconcile_gtts_on_startup(self):
        """
        v4.7.1 FIX-02: Reconcile GTT orders after system restart.
        
        Queries kite.get_gtts() and matches active GTT orders to recovered
        positions. This prevents:
        - Duplicate GTTs (old + new placed blindly)
        - False 'unprotected' status when GTT actually exists
        - Manual stops not activated for truly unprotected positions
        
        Called once during broker sync after positions are loaded.
        """
        try:
            broker_gtts = self.kite.get_gtts()
            if not broker_gtts:
                logger.info("   📋 No active GTT orders found at broker")
                return
            
            # Build lookup: symbol → list of active GTTs
            active_gtts_by_symbol = {}
            for gtt in broker_gtts:
                if gtt.get('status') == 'active':
                    sym = gtt.get('tradingsymbol', '')
                    if sym not in active_gtts_by_symbol:
                        active_gtts_by_symbol[sym] = []
                    active_gtts_by_symbol[sym].append(gtt)
            
            logger.info(f"   📋 Found {sum(len(v) for v in active_gtts_by_symbol.values())} "
                       f"active GTTs across {len(active_gtts_by_symbol)} symbols")
            
            reconciled_count = 0
            unprotected_count = 0
            
            for symbol, position in self.positions.items():
                gtt_status = position.get('gtt_protected')
                
                # Only reconcile positions that need it
                if gtt_status == 'PENDING_RECONCILIATION' or gtt_status is False:
                    symbol_gtts = active_gtts_by_symbol.get(symbol, [])
                    
                    if symbol_gtts:
                        # Found existing GTT(s) for this symbol
                        stop_gtt = None
                        target_gtt = None
                        
                        for gtt in symbol_gtts:
                            orders = gtt.get('orders', [])
                            for order in orders:
                                if order.get('transaction_type') == 'SELL':
                                    trigger_val = gtt.get('trigger_values', [0])[0]
                                    entry_price = position.get('entry_price', 0)
                                    
                                    # Classify: stop (below entry) or target (above entry)
                                    if entry_price > 0 and trigger_val < entry_price:
                                        stop_gtt = gtt
                                    elif entry_price > 0 and trigger_val >= entry_price:
                                        target_gtt = gtt
                        
                        if stop_gtt:
                            # GTT stop exists — position IS protected
                            position['gtt_protected'] = True
                            position['gtt_active'] = True
                            position['gtt_stop_id'] = stop_gtt['id']
                            if target_gtt:
                                position['gtt_target_id'] = target_gtt['id']
                            
                            stop_price = stop_gtt.get('trigger_values', [0])[0]
                            logger.info(f"   ✅ {symbol}: GTT RECONCILED - "
                                      f"Stop @ ₹{stop_price:.2f} (ID: {stop_gtt['id']})")
                            reconciled_count += 1
                        else:
                            # No stop GTT — position is truly unprotected
                            position['gtt_protected'] = False
                            position['gtt_active'] = bool(target_gtt)
                            if target_gtt:
                                position['gtt_target_id'] = target_gtt['id']
                            
                            logger.warning(f"   ⚠️ {symbol}: No stop GTT found - UNPROTECTED")
                            unprotected_count += 1
                    else:
                        # No GTTs at all for this symbol
                        position['gtt_protected'] = False
                        position['gtt_active'] = False
                        logger.warning(f"   ⚠️ {symbol}: No GTTs found at broker - UNPROTECTED")
                        unprotected_count += 1
            
            logger.info(f"   📊 GTT Reconciliation: {reconciled_count} protected, "
                       f"{unprotected_count} unprotected")
            
            # Send summary alert
            if self.telegram and (reconciled_count > 0 or unprotected_count > 0):
                self.telegram.send_message(
                    f"🔄 GTT RECONCILIATION (Restart)\n\n"
                    f"✅ Protected: {reconciled_count} positions\n"
                    f"⚠️ Unprotected: {unprotected_count} positions\n\n"
                    f"{'Manual stop monitoring activated for unprotected positions.' if unprotected_count > 0 else 'All positions have GTT protection.'}"
                )
            
            return {
                'reconciled': reconciled_count,
                'unprotected': unprotected_count
            }
                
        except Exception as e:
            logger.error(f"❌ GTT reconciliation failed: {e}")
            import traceback
            logger.error(traceback.format_exc())
            
            # On failure, mark all PENDING as unprotected (safe default)
            for symbol, position in self.positions.items():
                if position.get('gtt_protected') == 'PENDING_RECONCILIATION':
                    position['gtt_protected'] = False
                    logger.warning(f"   ⚠️ {symbol}: GTT reconciliation failed - marking UNPROTECTED")
            
            return None
    
    def _check_existing_gtt_for_symbol(self, symbol: str) -> Optional[Dict]:
        """
        v4.8.2 FIX: Check if active GTT already exists for a symbol.
        
        v4.8.2 CHANGES:
          - Fixed field path: uses condition.tradingsymbol (matching Zerodha API response)
          - Also checks top-level tradingsymbol as fallback
          - Returns 'all_ids' list for cancel-before-place cleanup
        
        Used by _add_manual_position, add_phase5_position, on_position_opened.
        
        Returns:
            Dict with 'stop_id', 'target_id', 'all_ids' if found, None otherwise
        """
        try:
            broker_gtts = self.kite.get_gtts()
            if not broker_gtts:
                return None
            
            existing = {'stop_id': None, 'target_id': None, 'all_ids': []}
            found = False
            
            for gtt in broker_gtts:
                if gtt.get('status') != 'active':
                    continue
                
                # v4.8.2 FIX: Check BOTH field paths (Zerodha API uses condition.tradingsymbol)
                gtt_symbol = ''
                condition = gtt.get('condition', {})
                if isinstance(condition, dict):
                    gtt_symbol = condition.get('tradingsymbol', '')
                if not gtt_symbol:
                    gtt_symbol = gtt.get('tradingsymbol', '')
                
                if gtt_symbol == symbol:
                    found = True
                    existing['all_ids'].append(gtt['id'])
                    
                    # Try to classify as stop or target
                    if existing['stop_id'] is None:
                        existing['stop_id'] = gtt['id']
                    elif existing['target_id'] is None:
                        existing['target_id'] = gtt['id']
                    # Any beyond 2 are duplicates (still tracked in all_ids)
            
            if found:
                logger.debug(f"   🔍 {symbol}: Found {len(existing['all_ids'])} active GTT(s) at broker: {existing['all_ids']}")
            
            return existing if found else None
            
        except Exception as e:
            logger.debug(f"GTT check for {symbol} failed: {e}")
            return None
    
    # ═══════════════════════════════════════════════════════════════════════════
    # MANUAL TRADE CARDS — Telegram alerts for manual execution
    # Sent proactively on every signal so user can act if VPN/API fails
    # ═══════════════════════════════════════════════════════════════════════════

    def _send_manual_gtt_card(self, symbol: str, position: Dict):
        """
        Send a Telegram card with exact GTT OCO setup instructions.
        Called in on_position_opened() BEFORE _place_gtt_orders().
        Contains confirmed fill price, stop, target, quantity.
        """
        if not self.telegram:
            return
        try:
            entry  = position.get('entry_price', 0)
            stop   = position.get('stop_price',  0)
            target = position.get('target_price', 0)
            qty    = position.get('quantity', 0)
            direction = self._get_position_direction(position)
            product   = position.get('product', 'CNC').upper()
            source    = position.get('source', position.get('phase', 'SYSTEM'))
            now_str   = datetime.now().strftime('%H:%M:%S')

            # Direction labels
            exit_action = 'SELL' if direction == 'LONG' else 'BUY'

            # P&L context
            risk_amt   = abs(entry - stop)   * qty
            reward_amt = abs(target - entry) * qty
            stop_pct   = ((stop - entry)   / entry * 100) if entry > 0 else 0
            tgt_pct    = ((target - entry) / entry * 100) if entry > 0 else 0
            rr         = (reward_amt / risk_amt) if risk_amt > 0 else 0

            # GTT trigger prices: 0.10 tick inside the limit to ensure fill
            if direction == 'LONG':
                stop_trigger   = round((stop   + 0.10) / 0.10) * 0.10
                target_trigger = round((target - 0.10) / 0.10) * 0.10
            else:
                stop_trigger   = round((stop   - 0.10) / 0.10) * 0.10
                target_trigger = round((target + 0.10) / 0.10) * 0.10

            msg = (
                f"✅ TRADE ENTERED — {symbol}\n"
                f"{'━'*32}\n"
                f"Fill    : ₹{entry:,.2f}  x{qty}  {product}\n"
                f"Capital : ₹{entry*qty:,.0f}\n"
                f"Source  : {source}  {now_str}\n"
                f"\n"
                f"Stop    : ₹{stop:,.2f}  ({stop_pct:+.2f}%)\n"
                f"Target  : ₹{target:,.2f}  ({tgt_pct:+.2f}%)\n"
                f"Risk    : ₹{risk_amt:,.0f}  |  R:R 1:{rr:.1f}\n"
                f"\n"
                f"{'━'*32}\n"
                f"📌 CREATE GTT OCO ON KITE:\n"
                f"kite.zerodha.com → Orders → GTT\n"
                f"\n"
                f"Symbol  : {symbol} NSE {product}\n"
                f"Qty     : {qty}\n"
                f"\n"
                f"Leg 1 — STOP LOSS\n"
                f"  Trigger : ₹{stop_trigger:,.2f}\n"
                f"  Order   : {exit_action} {qty} @ ₹{stop:,.2f} LIMIT\n"
                f"\n"
                f"Leg 2 — TARGET\n"
                f"  Trigger : ₹{target_trigger:,.2f}\n"
                f"  Order   : {exit_action} {qty} @ ₹{target:,.2f} LIMIT"
            )
            self.telegram.send_message(msg)
        except Exception as e:
            logger.debug(f"Manual GTT card send failed: {e}")

    def _enrich_exit_context(self, symbol: str, position: dict) -> dict:
        """
        v1.3.2: Fetch rich market context for TCAS RA exit advisor and post-ALIM
        re-entry advisor. Uses phase4's own kite, Kalman, and OI helpers.
        Returns a dict compatible with the recovery_advisor market_data schema.
        All failures are silent (debug log only) — never blocks the exit path.
        """
        ctx = {'ohlcv_5d': [], 'rsi': None, 'atr': None, 'vwap_pos': 'N/A',
               'kalman_daily': {}, 'oi_walls': {}}
        current_price = float(position.get('current_price', 0) or 0)

        # ── 5-day OHLCV + RSI-14 + ATR-5 ─────────────────────────────────────
        try:
            instrument_token = self._get_instrument_token(symbol)
            if instrument_token and self.kite:
                _from = datetime.now() - timedelta(days=22)   # buffer for RSI-14
                _hist = self.kite.historical_data(
                    instrument_token, _from, datetime.now(), interval='day')
                if _hist and len(_hist) >= 5:
                    closes = [c['close'] for c in _hist]
                    highs  = [c['high']  for c in _hist]
                    lows   = [c['low']   for c in _hist]
                    ctx['ohlcv_5d'] = [
                        {'date': str(c['date'])[:10],
                         'o': round(c['open'], 2), 'h': round(c['high'], 2),
                         'l': round(c['low'], 2),  'c': round(c['close'], 2)}
                        for c in _hist[-5:]
                    ]
                    # RSI-14
                    if len(closes) >= 15:
                        deltas = [closes[i] - closes[i-1] for i in range(1, len(closes))]
                        gains  = [max(d, 0) for d in deltas]
                        losses = [max(-d, 0) for d in deltas]
                        avg_g = sum(gains[-14:]) / 14
                        avg_l = sum(losses[-14:]) / 14
                        ctx['rsi'] = round(100 - 100 / (1 + avg_g / avg_l), 1) if avg_l > 0 else 100.0
                    # ATR-5
                    trs = [max(highs[i]-lows[i],
                               abs(highs[i]-closes[i-1]),
                               abs(lows[i]-closes[i-1]))
                           for i in range(-5, 0)]
                    ctx['atr'] = round(sum(trs) / len(trs), 2) if trs else None
                    # VWAP approx vs 5D avg close
                    avg_5 = sum(closes[-5:]) / 5
                    if current_price > 0 and avg_5 > 0:
                        dp = (current_price - avg_5) / avg_5 * 100
                        ctx['vwap_pos'] = f"{'ABOVE' if dp >= 0 else 'BELOW'} 5D-avg by {abs(dp):.1f}%"
        except Exception as _e:
            logger.debug(f"_enrich_exit_context OHLCV error for {symbol}: {_e}")

        # ── Daily Kalman prediction ───────────────────────────────────────────
        try:
            if hasattr(self, '_fetch_daily_kalman_prediction'):
                ctx['kalman_daily'] = self._fetch_daily_kalman_prediction(symbol)
        except Exception as _e:
            logger.debug(f"_enrich_exit_context Kalman error for {symbol}: {_e}")

        # ── OI walls (support / resistance) ──────────────────────────────────
        try:
            if current_price > 0 and hasattr(self, '_fetch_basic_option_oi'):
                oi = self._fetch_basic_option_oi(symbol, current_price)
                if oi:
                    ctx['oi_walls'] = {
                        'max_pain':  oi.get('max_pain'),
                        'pcr':       oi.get('pcr'),
                        'call_wall': oi.get('oi_walls', {}).get('call_resistance'),
                        'put_wall':  oi.get('oi_walls', {}).get('put_support'),
                    }
        except Exception as _e:
            logger.debug(f"_enrich_exit_context OI error for {symbol}: {_e}")

        return ctx

    def _send_manual_exit_card(self, symbol: str, position: Dict, reason: str):
        """
        Send a Telegram card with manual exit instructions.
        Called in _execute_exit() BEFORE _place_exit_order().
        """
        if not self.telegram:
            return
        try:
            entry     = position.get('entry_price', 0)
            stop      = position.get('stop_price',  0)
            target    = position.get('target_price', 0)
            qty       = position.get('quantity', 0)
            direction = self._get_position_direction(position)
            product   = position.get('product', 'CNC').upper()
            now_str   = datetime.now().strftime('%H:%M:%S')

            exit_action = 'SELL' if direction == 'LONG' else 'BUY'

            # Estimate likely exit price based on reason
            reason_u = reason.upper()
            if 'STOP' in reason_u or 'ALIM' in reason_u:
                likely_price = stop
                emoji = '🛑'
            elif 'TARGET' in reason_u:
                likely_price = target
                emoji = '🎯'
            else:
                likely_price = position.get('last_price', entry)
                emoji = '🚨'

            pnl_pct = self._calculate_pnl_pct(position, likely_price)
            pnl_amt = abs(likely_price - entry) * qty
            pnl_sign = '+' if pnl_pct >= 0 else '-'

            msg = (
                f"{emoji} EXIT SIGNAL — {symbol}\n"
                f"{'━'*32}\n"
                f"Action  : {exit_action} (CLOSE)\n"
                f"Reason  : {reason}\n"
                f"Est.Price: ₹{likely_price:,.2f}  x{qty}\n"
                f"\n"
                f"Entry   : ₹{entry:,.2f}\n"
                f"P&L     : {pnl_sign}₹{pnl_amt:,.0f}  ({pnl_pct:+.2f}%)\n"
                f"Time    : {now_str}\n"
                f"\n"
                f"{'━'*32}\n"
                f"📌 IF AUTO FAILS — MANUAL EXIT:\n"
                f"{exit_action} {symbol} NSE {product}\n"
                f"MARKET ORDER  x{qty}\n"
                f"(or LIMIT @ ₹{likely_price:,.2f})\n"
                f"\n"
                f"After exit: cancel pending GTT on Kite"
            )
            self.telegram.send_message(msg)
        except Exception as e:
            logger.debug(f"Manual exit card send failed: {e}")

    def _place_gtt_orders(self, symbol: str, position: Dict) -> Optional[Dict]:
        """
        Place GTT stop loss and target orders.
        
        v4.13.0: Direction-aware for LONG and SHORT positions.
        - LONG: SELL to exit (stop below, target above)
        - SHORT: BUY to exit (stop above, target below)
        
        Returns:
            Dict with stop_id and target_id if successful
        """
        if not self.ENABLE_GTT:
            return None
        
        try:
            quantity = position.get('quantity', 0)
            stop_price = position.get('stop_price', 0)
            target_price = position.get('target_price', 0)
            current_price = position.get('entry_price', 0)
            direction = self._get_position_direction(position)
            
            if quantity <= 0 or stop_price <= 0 or target_price <= 0:
                logger.warning(f"Invalid params for GTT: {symbol}")
                return None
            
            # v4.13.0: Direction-aware exit transaction type
            exit_transaction = self._get_exit_transaction_type(direction)
            
            # v4.8.1: CRITICAL - Product type must be stored and used in GTT
            product_type = position.get('product', 'CNC')
            
            gtt_ids = {}
            
            # GTT Stop Loss
            try:
                gtt_stop = self.kite.place_gtt(
                    trigger_type=self.kite.GTT_TYPE_SINGLE,
                    tradingsymbol=symbol,
                    exchange="NSE",
                    trigger_values=[stop_price],
                    last_price=current_price,
                    orders=[{
                        "transaction_type": exit_transaction,
                        "quantity": quantity,
                        "price": stop_price,
                        "order_type": self.kite.ORDER_TYPE_MARKET,
                        "product": product_type  # v4.8.1: REQUIRED - must match original order
                    }]
                )
                gtt_ids['stop_id'] = gtt_stop.get('trigger_id')
                logger.info(f"   ✅ GTT Stop placed: {symbol} @ ₹{stop_price:.2f} ({direction} → {exit_transaction})")
            except Exception as e:
                logger.error(f"   ❌ GTT Stop failed: {e}")
            
            # GTT Target
            try:
                gtt_target = self.kite.place_gtt(
                    trigger_type=self.kite.GTT_TYPE_SINGLE,
                    tradingsymbol=symbol,
                    exchange="NSE",
                    trigger_values=[target_price],
                    last_price=current_price,
                    orders=[{
                        "transaction_type": exit_transaction,
                        "quantity": quantity,
                        "price": target_price,
                        "order_type": self.kite.ORDER_TYPE_LIMIT,
                        "product": product_type  # v4.8.1: REQUIRED - must match original order
                    }]
                )
                gtt_ids['target_id'] = gtt_target.get('trigger_id')
                logger.info(f"   ✅ GTT Target placed: {symbol} @ ₹{target_price:.2f} ({direction} → {exit_transaction})")
            except Exception as e:
                logger.error(f"   ❌ GTT Target failed: {e}")
            
            return gtt_ids if gtt_ids else None
            
        except Exception as e:
            logger.error(f"GTT placement failed for {symbol}: {e}")
            return None
    
    def _modify_gtt_stop(self, symbol: str, new_stop_price: float) -> bool:
        """
        Modify GTT stop loss price.
        
        v4.13.0: Direction-aware (BUY to close SHORT, SELL to close LONG).
        """
        position = self.positions.get(symbol)
        if not position:
            return False
        
        trigger_id = position.get('gtt_stop_id')
        if not trigger_id:
            logger.warning(f"No GTT stop ID for {symbol}")
            return False
        
        try:
            quantity = position.get('quantity', 0)
            current_price = position.get('current_price', position.get('entry_price', 0))
            
            # v4.13.0: Direction-aware exit transaction
            direction = self._get_position_direction(position)
            exit_transaction = self._get_exit_transaction_type(direction)
            kite_transaction = (self.kite.TRANSACTION_TYPE_BUY 
                               if exit_transaction == 'BUY' 
                               else self.kite.TRANSACTION_TYPE_SELL)
            
            # v4.8.1: CRITICAL - Must include product field matching original order
            product_type = position.get('product', 'CNC')
            
            self.kite.modify_gtt(
                trigger_id=trigger_id,
                trigger_type=self.kite.GTT_TYPE_SINGLE,
                tradingsymbol=symbol,
                exchange="NSE",
                trigger_values=[new_stop_price],
                last_price=current_price,
                orders=[{
                    "transaction_type": kite_transaction,
                    "quantity": quantity,
                    "price": new_stop_price,
                    "order_type": self.kite.ORDER_TYPE_MARKET,
                    "product": product_type  # v4.8.1: REQUIRED - must match original order
                }]
            )
            
            # Update position
            old_stop = position.get('stop_price', 0)
            position['stop_price'] = new_stop_price
            
            logger.info(f"✅ GTT Stop modified: {symbol} ₹{old_stop:.2f} → ₹{new_stop_price:.2f} ({direction} → {exit_transaction})")
            
            # Telegram notification
            if self.telegram:
                self.telegram.send_message(
                    f"📝 GTT STOP MODIFIED: {symbol}\n\n"
                    f"Old: ₹{old_stop:.2f}\n"
                    f"New: ₹{new_stop_price:.2f}"
                )
            
            return True
            
        except Exception as e:
            logger.error(f"GTT stop modify failed for {symbol}: {e}")
            return False
    
    def _modify_gtt_target(self, symbol: str, new_target_price: float) -> bool:
        """
        Modify GTT target price - requires cancel and replace.
        
        v4.13.0: Direction-aware (BUY to close SHORT, SELL to close LONG).
        """
        position = self.positions.get(symbol)
        if not position:
            return False
        
        trigger_id = position.get('gtt_target_id')
        if not trigger_id:
            logger.warning(f"No GTT target ID for {symbol}")
            return False
        
        try:
            # Cancel existing
            self.kite.delete_gtt(trigger_id)
            
            # Place new
            quantity = position.get('quantity', 0)
            current_price = position.get('current_price', position.get('entry_price', 0))
            
            # v4.13.0: Direction-aware exit transaction
            direction = self._get_position_direction(position)
            exit_transaction = self._get_exit_transaction_type(direction)
            kite_transaction = (self.kite.TRANSACTION_TYPE_BUY 
                               if exit_transaction == 'BUY' 
                               else self.kite.TRANSACTION_TYPE_SELL)
            
            # v4.8.1: CRITICAL - Must include product field matching original order
            product_type = position.get('product', 'CNC')
            
            gtt_target = self.kite.place_gtt(
                trigger_type=self.kite.GTT_TYPE_SINGLE,
                tradingsymbol=symbol,
                exchange="NSE",
                trigger_values=[new_target_price],
                last_price=current_price,
                orders=[{
                    "transaction_type": kite_transaction,
                    "quantity": quantity,
                    "price": new_target_price,
                    "order_type": self.kite.ORDER_TYPE_LIMIT,
                    "product": product_type  # v4.8.1: REQUIRED - must match original order
                }]
            )
            
            # Update position
            old_target = position.get('target_price', 0)
            position['target_price'] = new_target_price
            position['gtt_target_id'] = gtt_target.get('trigger_id')
            
            logger.info(f"✅ GTT Target modified: {symbol} ₹{old_target:.2f} → ₹{new_target_price:.2f} ({direction} → {exit_transaction})")
            
            return True
            
        except Exception as e:
            logger.error(f"GTT target modify failed for {symbol}: {e}")
            return False
    
    def _cancel_gtt(self, trigger_id: int) -> bool:
        """
        Cancel a GTT order.
        
        v5.2.1: Enhanced error handling
        - Logs trigger_id in all messages (was missing, made debugging impossible)
        - Gracefully handles "already cancelled/triggered" (not a real error)
        - Still logs genuine failures as ERROR
        """
        if not trigger_id:
            logger.warning("_cancel_gtt called with empty trigger_id — skipping")
            return False
        
        try:
            self.kite.delete_gtt(trigger_id)
            logger.info(f"✅ GTT #{trigger_id} cancelled")
            return True
        except Exception as e:
            error_msg = str(e).lower()
            # These are "already gone" conditions — not real errors
            # v5.3.5: Added 'error while deleting' — Kite returns this when
            # GTT was already triggered/cancelled/expired
            if any(phrase in error_msg for phrase in [
                'does not exist', 'not found', 'already',
                'invalid trigger', 'no trigger', 'expired',
                'error while deleting'
            ]):
                logger.info(f"ℹ️ GTT #{trigger_id} already gone: {e}")
                return True  # Not an error — trigger is already cancelled/triggered
            else:
                logger.error(f"❌ GTT #{trigger_id} cancel FAILED: {e}")
                return False
    
    def _cancel_all_gtt_for_symbol(self, symbol: str):
        """
        Cancel all GTT orders for a symbol.
        
        v4.15.0 FIX: Two-phase cleanup:
          Phase A: Cancel known GTT IDs from position dict (fast path)
          Phase B: Scan broker for ANY active GTTs matching symbol (catches orphans)
        """
        # Phase A: Cancel known IDs from position dict
        position = self.positions.get(symbol)
        cancelled_ids = set()
        
        if position:
            for key in ['gtt_stop_id', 'gtt_target_id']:
                trigger_id = position.get(key)
                if trigger_id:
                    self._cancel_gtt(trigger_id)
                    cancelled_ids.add(trigger_id)
                    position[key] = None
            position['gtt_active'] = False
        
        # Phase B: Scan broker for orphan GTTs (catches restart-lost IDs)
        try:
            broker_gtts = self.kite.get_gtts()
            if not broker_gtts:
                return
            
            orphan_count = 0
            for gtt in broker_gtts:
                if (gtt.get('tradingsymbol') == symbol and 
                    gtt.get('status') == 'active' and 
                    gtt['id'] not in cancelled_ids):
                    logger.warning(f"   🧹 Found orphan GTT {gtt['id']} for {symbol} — cancelling")
                    self._cancel_gtt(gtt['id'])
                    orphan_count += 1
            
            if orphan_count > 0:
                logger.info(f"   🧹 Cleaned up {orphan_count} orphan GTT(s) for {symbol}")
                
        except Exception as e:
            logger.warning(f"Broker GTT scan failed for {symbol}: {e}")

    def _cleanup_all_orphan_gtts(self):
        """
        v4.15.0: Startup cleanup — cancel GTTs for symbols we DON'T hold.
        
        Called once at startup to clean up GTTs from positions that were
        closed but whose GTTs were never cancelled (crash/restart/bug).
        """
        try:
            broker_gtts = self.kite.get_gtts()
            if not broker_gtts:
                logger.info("   🧹 No GTTs at broker — clean slate")
                return
            
            active_symbols = set(self.positions.keys())
            orphan_count = 0
            
            for gtt in broker_gtts:
                if gtt.get('status') != 'active':
                    continue
                    
                symbol = gtt.get('tradingsymbol', '')
                
                if symbol not in active_symbols:
                    logger.warning(f"   🧹 ORPHAN GTT: {gtt['id']} for {symbol} "
                                 f"(no active position) — cancelling")
                    self._cancel_gtt(gtt['id'])
                    orphan_count += 1
            
            # Also check for duplicate GTTs within active positions
            gtt_count_by_symbol = {}
            for gtt in broker_gtts:
                if gtt.get('status') != 'active':
                    continue
                sym = gtt.get('tradingsymbol', '')
                if sym in active_symbols:
                    if sym not in gtt_count_by_symbol:
                        gtt_count_by_symbol[sym] = []
                    gtt_count_by_symbol[sym].append(gtt)
            
            for sym, gtts in gtt_count_by_symbol.items():
                if len(gtts) > 2:  # More than 1 stop + 1 target = duplicates
                    logger.warning(f"   🧹 {sym}: {len(gtts)} GTTs found (expected max 2) — cleaning duplicates")
                    
                    # Keep the 2 most recent, cancel the rest
                    sorted_gtts = sorted(gtts, key=lambda g: g.get('id', 0), reverse=True)
                    keep_ids = set()
                    
                    # Keep latest stop and latest target
                    for gtt in sorted_gtts:
                        orders = gtt.get('orders', [])
                        for order in orders:
                            tx_type = order.get('transaction_type', '')
                            if tx_type == 'SELL' and 'stop' not in keep_ids:
                                keep_ids.add(gtt['id'])
                                break
                            elif tx_type == 'BUY' and 'target' not in keep_ids:
                                keep_ids.add(gtt['id'])
                                break
                    
                    # If we couldn't classify, just keep the 2 newest
                    if len(keep_ids) < 2:
                        keep_ids = {g['id'] for g in sorted_gtts[:2]}
                    
                    for gtt in sorted_gtts:
                        if gtt['id'] not in keep_ids:
                            logger.warning(f"   🧹 Cancelling duplicate GTT {gtt['id']} for {sym}")
                            self._cancel_gtt(gtt['id'])
                            orphan_count += 1
                    
                    # Update position with kept IDs
                    position = self.positions.get(sym)
                    if position and keep_ids:
                        kept_list = list(keep_ids)
                        position['gtt_stop_id'] = kept_list[0]
                        position['gtt_target_id'] = kept_list[1] if len(kept_list) > 1 else None
                        position['gtt_active'] = True
            
            if orphan_count > 0:
                logger.info(f"   🧹 GTT Cleanup: Cancelled {orphan_count} orphan/duplicate GTT(s)")
                if self.telegram:
                    self.telegram.send_message(
                        f"🧹 GTT CLEANUP AT STARTUP\n\n"
                        f"Cancelled {orphan_count} orphan/duplicate GTT(s)\n"
                        f"Active positions: {', '.join(active_symbols) if active_symbols else 'None'}"
                    )
            else:
                active_gtt_count = sum(1 for g in broker_gtts if g.get('status') == 'active')
                logger.info(f"   🧹 GTT Check: {active_gtt_count} active GTTs, all accounted for ✅")
                
        except Exception as e:
            logger.error(f"GTT orphan cleanup failed: {e}")

    # ═══════════════════════════════════════════════════════════════════════════
    # v4.8.1 C1: DECISION HISTORY TRACKING
    # ═══════════════════════════════════════════════════════════════════════════
    
    def _log_decision(self, symbol: str, decision: Dict, position_state: Dict):
        """
        Log ChatGPT decision for later outcome tracking.
        
        C1: Decision History - Learn from past decisions
        """
        decision_record = {
            'timestamp': datetime.now().isoformat(),
            'symbol': symbol,
            'decision': decision.get('decision'),
            'confidence': decision.get('confidence'),
            'probabilistic_analysis': decision.get('probabilistic_analysis', {}),
            'position_snapshot': {
                'entry_price': position_state.get('entry_price'),
                'current_price': position_state.get('current_price'),
                'target_price': position_state.get('target_price'),
                'stop_price': position_state.get('stop_price'),
                'pnl_pct': ((position_state.get('current_price', 0) - position_state.get('entry_price', 0)) 
                           / position_state.get('entry_price', 1)) * 100 if position_state.get('entry_price') else 0
            },
            'outcome': None,  # Will be filled when position closes
            'outcome_time': None,
            'outcome_pnl': None
        }
        
        self.decision_history.append(decision_record)
        
        # Keep only last N decisions
        if len(self.decision_history) > self.max_history_size:
            self.decision_history = self.decision_history[-self.max_history_size:]
        
        logger.info(f"   📝 Decision logged (History size: {len(self.decision_history)})")
    
    # ═══════════════════════════════════════════════════════════════════════════
    # v4.8.1 C2: LOOP DETECTION (Prevent Re-Entry Mistakes)
    # ═══════════════════════════════════════════════════════════════════════════
    
    def _record_exit(self, symbol: str, exit_price: float, reason: str):
        """
        Record exit for loop detection + ML pipeline logging.

        C2: Prevents immediate re-entry after stop-loss.
        v4.10.0: Persists to file for restart stability.
        v4.14.1: Logs trade features to ML pipeline (trades_ml.csv).
        """
        self.exit_history[symbol] = {
            'exit_time': datetime.now(),
            'exit_price': exit_price,
            'reason': reason
        }

        logger.info(f"   🔄 Exit recorded for loop detection: {symbol} @ ₹{exit_price:.2f} ({reason})")
        self._save_exit_history()  # v4.10.0: Persist immediately

        # v4.14.1: Log to ML pipeline (all sources: Phase 2/3 CNC, Phase 5 MIS, manual)
        if self.ml_logger:
            try:
                position = self.positions.get(symbol, {})
                entry_price = position.get('entry_price', 0)
                quantity = position.get('quantity', 1)
                pnl = (exit_price - entry_price) * quantity if entry_price else 0
                direction = position.get('direction', 'LONG')
                if direction == 'SHORT':
                    pnl = -pnl
                pnl_pct = ((exit_price - entry_price) / entry_price * 100) if entry_price else 0
                if direction == 'SHORT':
                    pnl_pct = -pnl_pct

                trade = {
                    'symbol': symbol,
                    'entry_price': entry_price,
                    'exit_price': exit_price,
                    'quantity': quantity,
                    'pnl': pnl,
                    'pnl_pct': pnl_pct,
                    'entry_time': position.get('entry_time', ''),
                    'exit_time': datetime.now().isoformat(),
                    'exit_reason': reason,
                }

                # Extract entry features from position dict (populated at entry by Phase 2/5)
                signal = {
                    'rsi': position.get('entry_rsi', 0),
                    'volume_ratio': position.get('volume_burst_score', position.get('volume_ratio', 0)),
                    'atr_pct': position.get('atr_pct', 0),
                    'target_pct': position.get('target_pct', 0),
                    'stop_pct': position.get('stop_pct', 0),
                    'v_recovery_pct': position.get('recovery_percent', 0),
                    'score': position.get('intelligent_score', position.get('phase2_score', 0)),
                    'sector': position.get('sector', ''),
                    'volatility_regime': position.get('volatility_regime', 'NORMAL'),
                }

                # Trade performance metrics from TCAS tracking
                max_drawdown = position.get('max_drawdown_pct', 0)
                max_profit = position.get('peak_pnl_pct', position.get('max_profit_pct', 0))

                self.ml_logger.log_trade_with_features(
                    trade=trade,
                    signal=signal,
                    max_drawdown=max_drawdown,
                    max_profit=max_profit,
                )
                logger.debug(f"   📊 ML logged: {symbol} ({reason})")
            except Exception as e:
                logger.debug(f"   ML logging failed for {symbol}: {e}")
    
    def _save_exit_history(self):
        """
        v4.10.0 NEW: Save exit history to file for restart persistence.
        """
        try:
            os.makedirs('data', exist_ok=True)
            
            # Convert datetime to string for JSON serialization
            serializable = {}
            for symbol, data in self.exit_history.items():
                serializable[symbol] = {
                    'exit_time': data['exit_time'].isoformat() if isinstance(data['exit_time'], datetime) else data['exit_time'],
                    'exit_price': data['exit_price'],
                    'reason': data['reason']
                }
            
            with open(self._exit_history_file, 'w') as f:
                json.dump(serializable, f, indent=2)
            
            logger.debug(f"   💾 Exit history saved ({len(serializable)} entries)")
            
        except Exception as e:
            logger.warning(f"   ⚠️ Failed to save exit history: {e}")
    
    def _load_exit_history(self):
        """
        v4.10.0 NEW: Load exit history from file on startup.
        Cleans up expired entries (older than cooldown period).
        """
        try:
            if os.path.exists(self._exit_history_file):
                with open(self._exit_history_file, 'r') as f:
                    data = json.load(f)
                
                now = datetime.now()
                loaded_count = 0
                expired_count = 0
                
                for symbol, entry in data.items():
                    exit_time = datetime.fromisoformat(entry['exit_time'])
                    age_minutes = (now - exit_time).total_seconds() / 60
                    
                    # Only load entries that are still within cooldown period
                    if age_minutes < self.reentry_cooldown_minutes:
                        self.exit_history[symbol] = {
                            'exit_time': exit_time,
                            'exit_price': entry['exit_price'],
                            'reason': entry['reason']
                        }
                        loaded_count += 1
                        logger.info(f"   📥 Restored exit block: {symbol} ({age_minutes:.0f} min ago)")
                    else:
                        expired_count += 1
                
                if loaded_count > 0:
                    logger.info(f"   ✅ Loaded {loaded_count} active exit blocks (expired: {expired_count})")
                else:
                    logger.debug(f"   ℹ️ No active exit blocks to load (expired: {expired_count})")
                    
        except FileNotFoundError:
            logger.debug("   ℹ️ No exit history file found (fresh start)")
        except Exception as e:
            logger.warning(f"   ⚠️ Failed to load exit history: {e}")
    
    def _check_reentry_allowed(self, symbol: str) -> Tuple[bool, str]:
        """
        Check if re-entry is allowed for this symbol.
        
        C2: Loop Detection - Prevent re-entering same stock that just stopped out.
        
        Returns:
            (allowed, reason)
        """
        if symbol not in self.exit_history:
            return True, "NO_PRIOR_EXIT"
        
        exit_record = self.exit_history[symbol]
        time_since_exit = (datetime.now() - exit_record['exit_time']).total_seconds() / 60
        
        if time_since_exit < self.reentry_cooldown_minutes:
            remaining = self.reentry_cooldown_minutes - time_since_exit
            return False, f"COOLDOWN: {remaining:.0f} min remaining (exited {time_since_exit:.0f} min ago)"
        
        # Cooldown passed - allow re-entry
        return True, f"COOLDOWN_PASSED: {time_since_exit:.0f} min since exit"
    
    def is_reentry_allowed(self, symbol: str) -> Tuple[bool, str]:
        """
        v4.9.0: PUBLIC API for loop detection.
        
        Called by Orchestrator/Phase 2 BEFORE generating entry signal.
        Prevents re-entering a stock that recently stopped out.
        
        Args:
            symbol: Stock symbol to check
            
        Returns:
            (allowed, reason) - True if entry allowed, False with cooldown info if blocked
            
        Example usage in Orchestrator:
            if phase4 and hasattr(phase4, 'is_reentry_allowed'):
                allowed, reason = phase4.is_reentry_allowed(symbol)
                if not allowed:
                    logger.info(f"⏳ {symbol}: Re-entry blocked - {reason}")
                    continue
        """
        return self._check_reentry_allowed(symbol)
    
    def _clear_exit_history_for_symbol(self, symbol: str):
        """Clear exit history when position successfully completes (target hit)"""
        if symbol in self.exit_history:
            del self.exit_history[symbol]
            logger.info(f"   ✅ Exit history cleared for {symbol} (successful trade)")
    
    # ═══════════════════════════════════════════════════════════════════════════
    # v4.10.0 NEW: PHASE 4 STATUS BANNER (Every 5 minutes)
    # ═══════════════════════════════════════════════════════════════════════════
    
    def _log_phase4_status_if_needed(self):
        """
        v4.10.0 NEW: Log Phase 4 status banner every 5 minutes.
        
        Features KALMAN FLIGHT PATH visualization:
        - Horizontal flight path showing price trajectory
        - Target and Stop as visual reference points
        - Predicted prices at 15m, 30m, 60m
        - Flight data: velocity, acceleration, ETAs
        """
        # Check if 5 minutes have passed since last status log
        if not hasattr(self, '_last_status_log_time'):
            self._last_status_log_time = datetime.min
        
        now = datetime.now()
        elapsed = (now - self._last_status_log_time).total_seconds() / 60
        
        if elapsed < 5:  # Only log every 5 minutes
            return
        
        self._last_status_log_time = now
        
        # Get positions
        positions = self.positions
        if not positions:
            return
        
        # Log main banner
        logger.info("")
        logger.info("═" * 85)
        logger.info("🛫 PHASE 4 PORTFOLIO MONITORING STATUS")
        logger.info("═" * 85)
        logger.info(f"📊 Active Positions: {len(positions)} | ⏰ Time: {now.strftime('%H:%M:%S')}")
        logger.info("─" * 85)
        
        total_pnl = 0
        total_value = 0
        
        for symbol, position in positions.items():
            entry_price = position.get('entry_price', 0)
            current_price = position.get('current_price', entry_price)
            quantity = position.get('quantity', 0)
            stop_price = position.get('stop_price', 0)
            target_price = position.get('target_price', 0)
            direction = self._get_position_direction(position)
            
            # v4.13.0: Direction-aware P&L calculation
            if entry_price > 0:
                pnl_pct = self._calculate_pnl_pct(position, current_price)
                if direction == 'SHORT':
                    pnl_value = (entry_price - current_price) * quantity
                else:
                    pnl_value = (current_price - entry_price) * quantity
            else:
                pnl_pct = 0
                pnl_value = 0
            
            total_pnl += pnl_value
            total_value += current_price * quantity
            
            # Get tracking data
            tracking = position.get('phase4_tracking', {})
            
            # Health Score
            health_data = tracking.get('health_score', {})
            health_score = health_data.get('total', 50)
            health_emoji = "🟢" if health_score >= 60 else ("🟡" if health_score >= 40 else "🔴")
            
            # TCAS Status
            tcas_data = tracking.get('tcas_status', {})
            tcas_alert = tcas_data.get('alert_level', 'CLEAR')
            tcas_emoji = {"CLEAR": "🟢", "TA": "🟡", "RA": "🟠", "ALIM": "🔴"}.get(tcas_alert, "⚪")
            
            # ILS Status
            ils_data = tracking.get('ils_status', {})
            ils_phase = ils_data.get('phase', 'CRUISE')
            ils_emoji = {"CRUISE": "✈️", "APPROACH": "📍", "FINAL": "🎯"}.get(ils_phase, "⚪")
            
            # Kalman State - Get velocity and acceleration
            kalman_data = tracking.get('kalman_state', {})
            velocity = kalman_data.get('velocity', 0)  # Price change per minute
            acceleration = kalman_data.get('acceleration', 0)
            
            # If velocity is very small, estimate from recent price changes
            if abs(velocity) < 0.0001 and current_price > 0:
                velocity = current_price * 0.0001  # Default small movement
            
            # Calculate predicted prices (velocity is per-tick, convert to per-minute estimate)
            # Assuming ~2 ticks per minute for 30-sec monitoring
            vel_per_min = velocity * current_price * 2 if abs(velocity) < 1 else velocity
            
            # v4.14.0 FIX-D: Clamp predictions to ±10% of current price per hour
            # Prevents insane Kalman extrapolations on newly adopted positions
            max_move_per_min = current_price * 0.10 / 60  # 10% per hour = ~0.17% per min
            vel_per_min = max(-max_move_per_min, min(max_move_per_min, vel_per_min))
            
            price_15m = current_price + (vel_per_min * 15)
            price_30m = current_price + (vel_per_min * 30) + (acceleration * current_price * 450)
            price_60m = current_price + (vel_per_min * 60) + (acceleration * current_price * 1800)
            
            # v4.14.0 FIX-D: Also clamp final predictions
            max_15m = current_price * 1.03   # ±3% for 15min
            min_15m = current_price * 0.97
            max_60m = current_price * 1.10   # ±10% for 60min
            min_60m = current_price * 0.90
            price_15m = max(min_15m, min(max_15m, price_15m))
            price_30m = max(min_60m, min(max_60m, price_30m))
            price_60m = max(min_60m, min(max_60m, price_60m))
            
            # Direction-aware distance to stop/target (always positive %)
            # LONG: stop is below current, target is above
            # SHORT: stop is above current, target is below
            if direction == 'SHORT':
                stop_dist_pct  = ((stop_price  - current_price) / current_price * 100) if current_price > 0 else 0
                target_dist_pct = ((current_price - target_price) / current_price * 100) if current_price > 0 else 0
            else:
                stop_dist_pct  = ((current_price - stop_price)  / current_price * 100) if current_price > 0 else 0
                target_dist_pct = ((target_price - current_price) / current_price * 100) if current_price > 0 else 0

            # profit_vel > 0  → moving toward target (good)
            # profit_vel < 0  → moving toward stop   (bad)
            profit_vel = vel_per_min if direction != 'SHORT' else -vel_per_min

            # Calculate ETAs (direction-aware)
            if profit_vel > 0.01:   # Moving toward target
                time_to_target = abs((target_price - current_price) / vel_per_min) if vel_per_min != 0 else 999
                target_eta = f"~{time_to_target:.0f} min" if time_to_target < 999 else "N/A"
                stop_eta = "SAFE (profit direction)"
            elif profit_vel < -0.01:  # Moving toward stop
                time_to_stop = abs((current_price - stop_price) / vel_per_min) if vel_per_min != 0 else 999
                stop_eta = f"~{time_to_stop:.0f} min" if time_to_stop < 999 else "N/A"
                target_eta = "N/A (wrong direction)"
            else:  # Cruising
                stop_eta = "SAFE (stable)"
                target_eta = "Slow progress"
            
            # Determine flight status and arrows (kinematic — describes price direction)
            if vel_per_min < -0.5:  # Strong descent
                flight_status = "DIVING"
                arrow = "⬇️"
                status_emoji = "🔴" if direction != 'SHORT' else "🟢"
            elif vel_per_min < -0.1:  # Moderate descent
                flight_status = "DESCENDING"
                arrow = "↘️"
                status_emoji = "🟠" if direction != 'SHORT' else "🟢"
            elif vel_per_min > 0.5:  # Strong climb
                flight_status = "CLIMBING FAST"
                arrow = "⬆️"
                status_emoji = "🟢" if direction != 'SHORT' else "🔴"
            elif vel_per_min > 0.1:  # Moderate climb
                flight_status = "CLIMBING"
                arrow = "↗️"
                status_emoji = "🟢" if direction != 'SHORT' else "🔴"
            else:  # Cruising
                flight_status = "CRUISING"
                arrow = "➡️"
                status_emoji = "🟡"

            # For SHORT: append direction context so the narrative is unambiguous
            # CRUISING range (|vel| < 0.1) — neither profit nor loss direction dominates
            if direction == 'SHORT':
                if abs(vel_per_min) < 0.1:
                    flight_status = f"{flight_status} (SHORT: neutral)"
                else:
                    flight_status = f"{flight_status} (SHORT: {'profit' if vel_per_min < 0 else 'loss'} dir)"

            # Check for critical situations
            # v5.1.0 FIX: Only critical if moving toward stop
            # For LONG: stop is below — vel negative = moving toward stop
            # For SHORT: stop is above — vel positive = moving toward stop
            if direction == 'SHORT':
                is_critical = price_30m >= stop_price or (
                    tcas_alert in ['RA', 'ALIM'] and vel_per_min > 0
                )
            else:
                is_critical = price_30m <= stop_price or (
                    tcas_alert in ['RA', 'ALIM'] and vel_per_min < 0
                )
            
            # P&L emoji
            pnl_emoji = "🟢" if pnl_pct >= 0 else "🔴"
            
            # ═══════════════════════════════════════════════════════════════
            # LOG FLIGHT PATH VISUALIZATION
            # ═══════════════════════════════════════════════════════════════
            
            logger.info("")
            logger.info(f"🔮 KALMAN FLIGHT PATH                                              {symbol}")
            logger.info("━" * 85)
            
            if direction == 'SHORT':
                # SHORT: stop is ABOVE (danger), target is BELOW (profit)
                # profit_vel < 0 means vel_per_min < 0 = price falling = good for SHORT
                if profit_vel >= 0:
                    # SHORT + rising = approaching STOP (danger — stop on top)
                    logger.info("")
                    if profit_vel > 0.1:  # Rising fast toward stop
                        if is_critical:
                            logger.info(f"    ⛔ ₹{stop_price:.2f} ══════════════════════════════════════════════ TERRAIN [{stop_dist_pct:.1f}%]")
                            logger.info(f"                                              💥 IMPACT!")
                            logger.info(f"                                           {arrow}")
                        else:
                            logger.info(f"    ⛔ ₹{stop_price:.2f} TERRAIN ·············································· [{stop_dist_pct:.1f}%]")
                            logger.info(f"                                           {arrow}")
                        logger.info(f"                                      {arrow} ₹{price_60m:.2f} (+60m)")
                        logger.info(f"                                 {arrow}")
                        logger.info(f"                            {arrow} ₹{price_30m:.2f} (+30m)")
                        logger.info(f"                       {arrow}")
                        logger.info(f"                  {arrow} ₹{price_15m:.2f} (+15m)")
                        logger.info(f"             {arrow}")
                        logger.info(f"    ✈️ ₹{current_price:.2f} NOW")
                    else:  # Cruising
                        logger.info(f"    ⛔ ₹{stop_price:.2f} TERRAIN ·············································· [{stop_dist_pct:.1f}%]")
                        logger.info("")
                        logger.info(f"    ✈️ ₹{current_price:.2f} {arrow}{arrow}{arrow} ₹{price_15m:.2f} {arrow}{arrow}{arrow} ₹{price_30m:.2f} {arrow}{arrow}{arrow} ₹{price_60m:.2f}")
                        logger.info(f"       NOW              (+15m)              (+30m)              (+60m)")
                    logger.info("")
                    logger.info(f"    🎯 ₹{target_price:.2f} TARGET ·············································· [{target_dist_pct:.1f}%]")
                else:
                    # SHORT + falling = approaching TARGET (profit — target on bottom)
                    logger.info("")
                    logger.info(f"    ⛔ ₹{stop_price:.2f} TERRAIN ·············································· [{stop_dist_pct:.1f}%]")
                    logger.info("")
                    logger.info(f"    ✈️ ₹{current_price:.2f} NOW")
                    logger.info(f"                   {arrow}")
                    logger.info(f"                      {arrow} ₹{price_15m:.2f} (+15m)")
                    logger.info(f"                           {arrow}")
                    logger.info(f"                              {arrow} ₹{price_30m:.2f} (+30m)")
                    logger.info(f"                                   {arrow}")
                    logger.info(f"                                      {arrow} ₹{price_60m:.2f} (+60m)")
                    logger.info(f"                                           {arrow}")
                    logger.info(f"    🎯 ₹{target_price:.2f} TARGET ·············································· [{target_dist_pct:.1f}%]")

            else:
                # LONG: stop is BELOW (danger), target is ABOVE (profit)
                if vel_per_min >= 0:  # LONG + climbing/cruising → target on top
                    logger.info("")
                    if vel_per_min > 0.1:  # Climbing
                        logger.info(f"                                              🎯 ₹{target_price:.2f} TARGET [+{target_dist_pct:.1f}%]")
                        logger.info(f"                                           {arrow}")
                        logger.info(f"                                      {arrow} ₹{price_60m:.2f} (+60m)")
                        logger.info(f"                                 {arrow}")
                        logger.info(f"                            {arrow} ₹{price_30m:.2f} (+30m)")
                        logger.info(f"                       {arrow}")
                        logger.info(f"                  {arrow} ₹{price_15m:.2f} (+15m)")
                        logger.info(f"             {arrow}")
                        logger.info(f"    ✈️ ₹{current_price:.2f} NOW")
                    else:  # Cruising
                        logger.info(f"    🎯 ₹{target_price:.2f} TARGET ·············································· [+{target_dist_pct:.1f}%]")
                        logger.info("")
                        logger.info(f"    ✈️ ₹{current_price:.2f} {arrow}{arrow}{arrow} ₹{price_15m:.2f} {arrow}{arrow}{arrow} ₹{price_30m:.2f} {arrow}{arrow}{arrow} ₹{price_60m:.2f}")
                        logger.info(f"       NOW              (+15m)              (+30m)              (+60m)")
                    logger.info("")
                    logger.info(f"    ⛔ ₹{stop_price:.2f} TERRAIN ·············································· [-{stop_dist_pct:.1f}%]")
                else:  # LONG + descending → stop danger on bottom
                    logger.info("")
                    logger.info(f"    🎯 ₹{target_price:.2f} TARGET ·············································· [+{target_dist_pct:.1f}%]")
                    logger.info("")
                    logger.info(f"    ✈️ ₹{current_price:.2f} NOW")
                    logger.info(f"                   {arrow}")
                    logger.info(f"                      {arrow} ₹{price_15m:.2f} (+15m)")
                    logger.info(f"                           {arrow}")
                    logger.info(f"                              {arrow} ₹{price_30m:.2f} (+30m)")
                    logger.info(f"                                   {arrow}")
                    logger.info(f"                                      {arrow} ₹{price_60m:.2f} (+60m)")
                    if is_critical:
                        logger.info(f"                                           {arrow}")
                        logger.info(f"                                              💥 IMPACT!")
                        logger.info(f"    ⛔ ₹{stop_price:.2f} ══════════════════════════════════════════════ TERRAIN [-{stop_dist_pct:.1f}%]")
                    else:
                        logger.info(f"                                           {arrow}")
                        logger.info(f"                                              ⛔ ₹{stop_price:.2f} TERRAIN [-{stop_dist_pct:.1f}%]")
            
            logger.info("")
            logger.info("━" * 85)
            logger.info(f"📊 FLIGHT DATA:")
            
            # Velocity display
            if vel_per_min > 0:
                logger.info(f"    📈 Climb Rate: +₹{abs(vel_per_min):.2f}/min ({flight_status})")
            elif vel_per_min < 0:
                logger.info(f"    📉 Descent Rate: -₹{abs(vel_per_min):.2f}/min ({flight_status})")
            else:
                logger.info(f"    ➡️ Cruise Speed: ₹{abs(vel_per_min):.2f}/min ({flight_status})")
            
            # Acceleration display
            if acceleration > 0.0001:
                logger.info(f"    📈 Acceleration: +₹{abs(acceleration * current_price):.4f}/min² (speeding up)")
            elif acceleration < -0.0001:
                logger.info(f"    📉 Acceleration: -₹{abs(acceleration * current_price):.4f}/min² (slowing down)")
            else:
                logger.info(f"    ➡️ Acceleration: Stable")
            
            # ETAs and alerts
            if is_critical:
                logger.info(f"    🚨 TERRAIN ALERT: {stop_eta}")
                logger.info(f"    🚨 PULL UP! PULL UP! PULL UP!")
            else:
                logger.info(f"    ⚠️ Terrain: {stop_eta}")
                logger.info(f"    🎯 Target ETA: {target_eta}")
            
            # Additional indicators
            logger.info("")
            logger.info(f"📋 POSITION STATUS:")
            logger.info(f"    {pnl_emoji} P&L: ₹{pnl_value:+.2f} ({pnl_pct:+.2f}%)")
            logger.info(f"    {health_emoji} Health: {health_score}/100 | {tcas_emoji} TCAS: {tcas_alert} | {ils_emoji} ILS: {ils_phase}")
            logger.info("═" * 85)
        
        # Portfolio summary
        logger.info("")
        total_pnl_emoji = "🟢" if total_pnl >= 0 else "🔴"
        logger.info(f"📊 PORTFOLIO SUMMARY: {total_pnl_emoji} P&L: ₹{total_pnl:+.2f} | 💼 Value: ₹{total_value:,.2f} | 📋 Positions: {len(positions)}")
        logger.info("═" * 85)
        logger.info("")
    
    # ═══════════════════════════════════════════════════════════════════════════
    # v4.8.1 C3: OVER-TRADING PREVENTION
    # ═══════════════════════════════════════════════════════════════════════════
    
    def _reset_consultation_counts_if_needed(self):
        """Reset consultation counts at market open"""
        now = datetime.now().time()
        if now < self.consultation_reset_time:
            # It's a new day and before market open - reset if we haven't already
            if self.chatgpt_consultation_count:
                logger.info(f"   🔄 Resetting consultation counts (new trading day)")
                self.chatgpt_consultation_count = {}
    
    def _check_consultation_allowed(self, symbol: str) -> Tuple[bool, str]:
        """
        Check if ChatGPT consultation is allowed for this position.
        
        C3: Over-Trading Prevention - Limit consultations per position per day.
        
        Returns:
            (allowed, reason)
        """
        count = self.chatgpt_consultation_count.get(symbol, 0)
        
        if count >= self.max_consultations_per_position:
            return False, f"MAX_CONSULTATIONS: {count}/{self.max_consultations_per_position} today"
        
        return True, f"ALLOWED: {count}/{self.max_consultations_per_position} today"
    
    def _increment_consultation_count(self, symbol: str):
        """Increment consultation counter for this symbol"""
        self.chatgpt_consultation_count[symbol] = self.chatgpt_consultation_count.get(symbol, 0) + 1
        count = self.chatgpt_consultation_count[symbol]
        logger.info(f"   📊 Consultation count: {count}/{self.max_consultations_per_position} today")

    # ═══════════════════════════════════════════════════════════════════════════
    # CHATGPT INTEGRATION
    # ═══════════════════════════════════════════════════════════════════════════
    
    def _should_consult_chatgpt(self, symbol: str, position: Dict, 
                                 tcas: TCASStatus, health: HealthScore) -> Tuple[bool, str]:
        """
        v4.10.0 HYBRID INTELLIGENCE: Smart ChatGPT consultation decision.
        
        Consult ChatGPT ONLY for ambiguous situations.
        Handle clear cases locally to reduce API calls.
        
        LOCAL DECISIONS (No ChatGPT):
        - Profitable positions with good exit score
        - TCAS RA with profit (just tighten stop)
        - Clear hold signals (healthy + uptrend)
        - TCAS ALIM (immediate exit, no time for consultation)
        
        CHATGPT NEEDED:
        - Ambiguous exit score (40-60)
        - TCAS RA with significant loss
        - Low health with unclear direction
        
        Returns:
            (should_call, reason)
        """
        if not self.chatgpt:
            return False, "ChatGPT not available"

        # ═══════════════════════════════════════════════════════════════════
        # FIX 3: HARD COUNT CHECK — runs BEFORE any critical rules
        # Prevents 728-call runaway (Feb 13 incident)
        # ═══════════════════════════════════════════════════════════════════
        daily_count = self.chatgpt_consultation_count.get(symbol, 0)
        if daily_count >= self.max_consultations_per_position:
            logger.info(f"   🚫 HARD LIMIT: {symbol} already at {daily_count}/{self.max_consultations_per_position} consultations today — BLOCKED")
            return False, f"HARD_LIMIT: {daily_count}/{self.max_consultations_per_position} today"

        # v4.13.0: Direction-aware P&L calculation
        entry_price = position.get('entry_price', 0)
        current_price = position.get('current_price', entry_price)
        pnl_pct = self._calculate_pnl_pct(position, current_price)
        
        # Get Kalman state for momentum
        kalman = self._get_kalman_state(symbol)
        kalman_velocity = kalman.velocity if kalman else 0
        
        # Check cooldown
        last_call = self.last_chatgpt_call.get(symbol, datetime.min)
        seconds_since_call = (datetime.now() - last_call).total_seconds()
        cooldown_passed = seconds_since_call > self.chatgpt_cooldown
        
        # ═══════════════════════════════════════════════════════════════════
        # RULE 1: TCAS ALIM - Immediate exit, NO ChatGPT
        # ═══════════════════════════════════════════════════════════════════
        if tcas.alert_level == TCASAlert.ALIM:
            return False, "TCAS_ALIM - Immediate exit (no consultation)"
        
        # ═══════════════════════════════════════════════════════════════════
        # RULE 2: PROFITABLE POSITIONS - Usually skip ChatGPT
        # ═══════════════════════════════════════════════════════════════════
        if pnl_pct >= 1.5:  # Good profit
            if tcas.alert_level == TCASAlert.RA:
                # RA with profit = tighten stop locally, don't panic
                logger.info(f"   🧠 HYBRID: {symbol} RA+Profit({pnl_pct:.1f}%) → Local tighten stop")
                return False, "RA_PROFITABLE - Tighten stop locally"
            
            if health.total_score >= 50:
                # Healthy + profitable = hold or auto-exit based on exit score
                logger.info(f"   🧠 HYBRID: {symbol} Profit({pnl_pct:.1f}%)+Health({health.total_score}) → Local decision")
                return False, "PROFITABLE_HEALTHY - Local decision"
        
        # ═══════════════════════════════════════════════════════════════════
        # RULE 3: HEALTHY POSITIONS - Skip ChatGPT
        # ═══════════════════════════════════════════════════════════════════
        if health.total_score >= 60:
            if tcas.alert_level != TCASAlert.RA:
                logger.info(f"   🧠 HYBRID: {symbol} Healthy({health.total_score}) → No consultation")
                return False, "HEALTHY - No consultation needed"
        
        # ═══════════════════════════════════════════════════════════════════
        # RULE 4: TCAS RA - Check severity before consulting
        # ═══════════════════════════════════════════════════════════════════
        if tcas.alert_level == TCASAlert.RA:
            if pnl_pct >= 0.5:
                # Small profit with RA = local tighten stop
                logger.info(f"   🧠 HYBRID: {symbol} RA+SmallProfit({pnl_pct:.1f}%) → Local tighten")
                return False, "RA_SMALL_PROFIT - Tighten locally"
            
            if pnl_pct > -1.5 and kalman_velocity > 0:
                # Small loss but recovering = hold locally
                logger.info(f"   🧠 HYBRID: {symbol} RA+Recovering(vel={kalman_velocity:.2f}) → Local hold")
                return False, "RA_RECOVERING - Hold locally"
            
            if pnl_pct < -2.0:
                # Significant loss with RA = need ChatGPT advice
                if cooldown_passed:
                    logger.info(f"   🧠 HYBRID: {symbol} RA+BigLoss({pnl_pct:.1f}%) → Need ChatGPT")
                    return True, "RA_CRITICAL_LOSS - Need advice"
                else:
                    return False, f"RA_COOLDOWN - Wait {self.chatgpt_cooldown - seconds_since_call:.0f}s"
        
        # ═══════════════════════════════════════════════════════════════════
        # RULE 5: LOW HEALTH - Consult only for ambiguous cases
        # ═══════════════════════════════════════════════════════════════════
        if health.total_score < self.HEALTH_CRITICAL:  # < 40
            if pnl_pct >= 0:
                # Low health but profitable = local tighten stop
                logger.info(f"   🧠 HYBRID: {symbol} LowHealth+Profit → Local tighten")
                return False, "LOW_HEALTH_PROFIT - Tighten locally"
            
            if pnl_pct < -1.5 and cooldown_passed:
                # Low health + loss = need advice
                logger.info(f"   🧠 HYBRID: {symbol} LowHealth+Loss → Need ChatGPT")
                return True, "HEALTH_CRITICAL_LOSS"
        
        # ═══════════════════════════════════════════════════════════════════
        # RULE 6: Gate failures - Consult only if not profitable
        # ═══════════════════════════════════════════════════════════════════
        for gate, status in health.gate_status.items():
            if not status.get('passed', True):
                if pnl_pct >= 1.0:
                    logger.info(f"   🧠 HYBRID: {symbol} GateFail+Profit → Local decision")
                    return False, f"GATE_FAIL_PROFIT - Local decision"
                elif cooldown_passed:
                    return True, f"GATE_FAILED: {gate}"
        
        # ═══════════════════════════════════════════════════════════════════
        # RULE 7: Danger zone - Consult only if deeply negative
        # ═══════════════════════════════════════════════════════════════════
        if pnl_pct < self.DANGER_ZONE_PCT and pnl_pct < -2.0:
            if cooldown_passed:
                return True, "DANGER_ZONE_DEEP"
        
        # ═══════════════════════════════════════════════════════════════════
        # RULE 7B (v4.15.0): V+P Volume Burst — bypass cooldown for bearish
        # ═══════════════════════════════════════════════════════════════════
        vp_signal = position.get('phase4_tracking', {}).get('last_vp_signal')
        if vp_signal:
            signal_age = 0
            try:
                signal_time = datetime.fromisoformat(vp_signal.get('timestamp', ''))
                signal_age = (datetime.now() - signal_time).total_seconds()
            except:
                signal_age = 9999
            
            # Only act on recent V+P signals (within last 2 minutes)
            if signal_age < 120 and vp_signal.get('action') == 'FORCE_CHATGPT':
                logger.info(f"   🧠 HYBRID: {symbol} V+P {vp_signal['signal_type']} → Forcing ChatGPT")
                return True, f"VP_BURST_{vp_signal['signal_type']}"
        
        # ═══════════════════════════════════════════════════════════════════
        # RULE 8: Periodic review - Much less frequent
        # ═══════════════════════════════════════════════════════════════════
        # v4.15.0: CNC positions use longer interval (60 min) vs MIS
        product = position.get('product', 'CNC')
        periodic_interval = self.CNC_CONSULTATION_INTERVAL if product == 'CNC' else self.CHATGPT_PERIODIC_INTERVAL
        if seconds_since_call > periodic_interval:
            if pnl_pct < -1.0:
                return True, "PERIODIC_REVIEW"
        
        # ═══════════════════════════════════════════════════════════════════
        # v4.8.1 C3: Check over-trading prevention for any remaining cases
        # ═══════════════════════════════════════════════════════════════════
        allowed, reason = self._check_consultation_allowed(symbol)
        if not allowed:
            logger.info(f"   🧠 HYBRID: Blocked by over-trading prevention: {reason}")
            return False, reason
        
        return False, "NO_CONSULTATION_NEEDED"
    
    # ═══════════════════════════════════════════════════════════════════════════
    # v4.9.0 NEW: FIBONACCI EXIT STRATEGY (Moved from Phase 3)
    # ═══════════════════════════════════════════════════════════════════════════
    
    def _should_calculate_fibonacci_exit(self, symbol: str, position: Dict, 
                                          ils: ILSStatus) -> Tuple[bool, str]:
        """
        v4.9.0: Determine if Fibonacci exit calculation is needed.
        
        Triggers:
        - Position in profit >= MIN_PNL_FOR_FIBONACCI (default 1.5%)
        - ILS phase is APPROACH, FINAL, or TOUCHDOWN (near target)
        - Cooldown passed (avoid too frequent calls)
        
        Returns:
            (should_calculate, reason)
        """
        # Check if ChatGPT advisor available
        if not self.chatgpt:
            return False, "ChatGPT advisor not available"
        
        # Check config flag
        if not getattr(self.config, 'USE_ADVISOR_FOR_EXIT_STRATEGY', True):
            return False, "Fibonacci exit disabled in config"
        
        # v4.13.0: Direction-aware P&L calculation
        entry_price = position.get('entry_price', 0)
        current_price = position.get('current_price', entry_price)
        pnl_pct = self._calculate_pnl_pct(position, current_price)
        
        # Minimum P&L threshold
        min_pnl = getattr(self.config, 'ADVISOR_MIN_PNL_FOR_EXIT_CALC', 1.5)
        if pnl_pct < min_pnl:
            return False, f"P&L {pnl_pct:.2f}% < minimum {min_pnl}%"
        
        # ILS phase check - only when approaching target
        if ils.landing_phase not in [ILSPhase.APPROACH, ILSPhase.FINAL, ILSPhase.TOUCHDOWN]:
            return False, f"ILS phase {ils.landing_phase.value} - not approaching target"
        
        # Cooldown check (separate from ChatGPT cooldown)
        last_fib_calc = position.get('phase4_tracking', {}).get('last_fibonacci_calc')
        if last_fib_calc:
            try:
                last_calc_time = datetime.fromisoformat(last_fib_calc)
                fib_cooldown = getattr(self.config, 'FIBONACCI_CALC_COOLDOWN', 300)  # 5 min default
                if (datetime.now() - last_calc_time).total_seconds() < fib_cooldown:
                    return False, "Fibonacci cooldown not passed"
            except:
                pass
        
        return True, f"ILS_{ils.landing_phase.value}_PNL_{pnl_pct:.1f}%"
    
    def _calculate_fibonacci_exit_levels(self, symbol: str, position: Dict) -> Optional[Dict]:
        """
        v4.9.0: Calculate Fibonacci-based exit levels using ChatGPT advisor.
        
        Moved from Phase 3's check_position_exits() for clean separation.
        
        Args:
            symbol: Stock symbol
            position: Position dict
            
        Returns:
            Dict with exit_strategy, fibonacci_resistance, trailing_stop, reasoning
            or None if calculation fails
        """
        if not self.chatgpt:
            return None
        
        entry_price = position.get('entry_price', 0)
        current_price = position.get('current_price', entry_price)
        stop_price = position.get('stop_price', entry_price * 0.98)
        target_price = position.get('target_price', entry_price * 1.03)
        
        # Calculate time held
        now = datetime.now()
        try:
            entry_time = datetime.fromisoformat(position.get('entry_time', now.isoformat()))
            time_held = (now - entry_time).total_seconds() / 60  # minutes
        except:
            time_held = 0
        
        # Calculate max profit achieved
        max_profit_pct = position.get('phase4_tracking', {}).get('max_profit_pct', 0)
        if max_profit_pct == 0:
            max_profit_pct = position.get('max_profit_pct', 0)
        
        recent_high = entry_price + (max_profit_pct / 100 * entry_price) if max_profit_pct > 0 else current_price
        
        # Calculate ATR (use stored or estimate)
        atr = position.get('atr', current_price * 0.02)
        
        # Calculate Fibonacci levels from recent swing
        swing_low = entry_price
        swing_high = max(recent_high, current_price, target_price)
        swing_range = swing_high - swing_low
        
        fibonacci_levels = {
            '23.6': swing_high - (swing_range * 0.236),
            '38.2': swing_high - (swing_range * 0.382),
            '50.0': swing_high - (swing_range * 0.500),
            '61.8': swing_high - (swing_range * 0.618),
            '78.6': swing_high - (swing_range * 0.786)
        }
        
        # Build support/resistance levels
        support_levels = [stop_price, entry_price, fibonacci_levels['61.8']]
        resistance_levels = [target_price, swing_high, fibonacci_levels['23.6']]
        
        logger.info(f"📐 Calculating Fibonacci exit levels for {symbol}...")
        logger.info(f"   Entry: ₹{entry_price:.2f}, Current: ₹{current_price:.2f}")
        logger.info(f"   Swing: ₹{swing_low:.2f} - ₹{swing_high:.2f}")
        logger.info(f"   Fib 38.2%: ₹{fibonacci_levels['38.2']:.2f}, 61.8%: ₹{fibonacci_levels['61.8']:.2f}")
        
        try:
            # Call ChatGPT advisor for exit levels
            exit_analysis = self.chatgpt.calculate_exit_levels(
                symbol=symbol,
                entry_price=entry_price,
                atr=atr,
                support_levels=support_levels,
                resistance_levels=resistance_levels,
                fibonacci_levels=fibonacci_levels
            )
            
            # Add metadata
            exit_analysis['fibonacci_levels'] = fibonacci_levels
            exit_analysis['time_held_minutes'] = int(time_held)
            exit_analysis['pnl_at_calc'] = self._calculate_pnl_pct(position, current_price)  # v4.13.0: Direction-aware
            
            logger.info(f"🧠 AI Fibonacci Exit Analysis for {symbol}:")
            logger.info(f"   Stop Loss: ₹{exit_analysis.get('stop_loss', 0):.2f}")
            logger.info(f"   Target 1: ₹{exit_analysis.get('target_1', 0):.2f}")
            logger.info(f"   Target 2: ₹{exit_analysis.get('target_2', 0):.2f}")
            logger.info(f"   Trailing Trigger: ₹{exit_analysis.get('trailing_stop_trigger', 0):.2f}")
            logger.info(f"   Reasoning: {exit_analysis.get('reasoning', 'N/A')[:80]}...")
            
            # Update position tracking
            if 'phase4_tracking' not in position:
                position['phase4_tracking'] = {}
            position['phase4_tracking']['last_fibonacci_calc'] = now.isoformat()
            position['phase4_tracking']['fibonacci_analysis'] = exit_analysis
            
            return exit_analysis
            
        except Exception as e:
            logger.error(f"❌ Fibonacci exit calculation failed for {symbol}: {e}")
            return None
    
    def _execute_fibonacci_recommendation(self, symbol: str, position: Dict, 
                                           exit_analysis: Dict) -> bool:
        """
        v4.9.0: Execute Fibonacci exit recommendations.
        
        Actions:
        - Update stop loss if AI recommends tighter stop
        - Update target if AI recommends extension
        - Activate trailing stop if trigger reached
        - Execute partial/full exit if recommended
        
        Returns:
            True if any action was taken
        """
        if not exit_analysis:
            return False
        
        action_taken = False
        entry_price = position.get('entry_price', 0)
        current_price = position.get('current_price', entry_price)
        current_stop = position.get('stop_price', entry_price * 0.98)
        current_target = position.get('target_price', entry_price * 1.03)
        
        # ═══════════════════════════════════════════════════════════════════
        # ACTION 1: Update Stop Loss (only if tighter/higher)
        # ═══════════════════════════════════════════════════════════════════
        ai_stop = exit_analysis.get('stop_loss', 0)
        if ai_stop > current_stop:
            logger.info(f"🧠 AI recommends tightening stop: ₹{current_stop:.2f} → ₹{ai_stop:.2f}")
            
            success = self._modify_gtt_stop(symbol, ai_stop)
            if success:
                self._update_position(symbol, position, stop_price=ai_stop)
                position['phase4_tracking']['ai_stop_update'] = datetime.now().isoformat()
                action_taken = True
                logger.info(f"   ✅ Stop updated to ₹{ai_stop:.2f}")
            else:
                logger.warning(f"   ⚠️ Failed to update stop")
        
        # ═══════════════════════════════════════════════════════════════════
        # ACTION 2: Update Target (extend if AI recommends)
        # ═══════════════════════════════════════════════════════════════════
        ai_target_2 = exit_analysis.get('target_2', 0)
        if ai_target_2 > current_target:
            logger.info(f"🧠 AI recommends extending target: ₹{current_target:.2f} → ₹{ai_target_2:.2f}")
            
            success = self._modify_gtt_target(symbol, ai_target_2)
            if success:
                self._update_position(symbol, position, target_price=ai_target_2)
                position['phase4_tracking']['ai_target_update'] = datetime.now().isoformat()
                action_taken = True
                logger.info(f"   ✅ Target extended to ₹{ai_target_2:.2f}")
            else:
                logger.warning(f"   ⚠️ Failed to update target")
        
        # ═══════════════════════════════════════════════════════════════════
        # ACTION 3: Activate Trailing Stop
        # ═══════════════════════════════════════════════════════════════════
        trailing_trigger = exit_analysis.get('trailing_stop_trigger', 0)
        if trailing_trigger > 0 and current_price >= trailing_trigger:
            if not position.get('phase4_tracking', {}).get('trailing_active'):
                logger.info(f"🧠 AI trailing stop activated at ₹{current_price:.2f} (trigger: ₹{trailing_trigger:.2f})")
                
                # Calculate trailing stop (1 ATR below current)
                atr = position.get('atr', current_price * 0.02)
                trailing_stop = current_price - atr
                
                if trailing_stop > current_stop:
                    success = self._modify_gtt_stop(symbol, trailing_stop)
                    if success:
                        self._update_position(symbol, position, stop_price=trailing_stop)
                        position['phase4_tracking']['trailing_active'] = True
                        position['phase4_tracking']['trailing_activated_at'] = datetime.now().isoformat()
                        position['phase4_tracking']['trailing_trigger_price'] = trailing_trigger
                        action_taken = True
                        logger.info(f"   ✅ Trailing stop set at ₹{trailing_stop:.2f}")
        
        # ═══════════════════════════════════════════════════════════════════
        # ACTION 4: Check for Partial Exit at Target 1
        # ═══════════════════════════════════════════════════════════════════
        target_1 = exit_analysis.get('target_1', 0)
        if target_1 > 0 and current_price >= target_1:
            # Check if we already did partial exit
            if not position.get('phase4_tracking', {}).get('partial_exit_done'):
                logger.info(f"🧠 AI Target 1 reached (₹{target_1:.2f}), considering partial exit")
                
                # Only do partial if quantity > 1 and config allows
                quantity = position.get('quantity', 0)
                if quantity > 1 and getattr(self.config, 'ENABLE_PARTIAL_EXIT', True):
                    success = self._execute_partial_exit(symbol, 50, "AI_TARGET_1_REACHED")
                    if success:
                        position['phase4_tracking']['partial_exit_done'] = True
                        position['phase4_tracking']['partial_exit_price'] = current_price
                        action_taken = True
                        logger.info(f"   ✅ 50% partial exit executed at ₹{current_price:.2f}")
        
        # Log summary
        if action_taken:
            if self.telegram:
                self.telegram.send_message(
                    f"🧠 FIBONACCI EXIT UPDATE\n\n"
                    f"Symbol: {symbol}\n"
                    f"Price: ₹{current_price:.2f}\n"
                    f"Stop: ₹{position.get('stop_price', 0):.2f}\n"
                    f"Target: ₹{position.get('target_price', 0):.2f}\n"
                    f"Reasoning: {exit_analysis.get('reasoning', 'AI optimization')[:100]}"
                )
        
        return action_taken
    
    def _calculate_exit_score(self, data: Dict) -> 'ExitScoreResult':
        """
        v4.10.0: Calculate exit quality score (0-100).
        
        Determines how good the current moment is for exiting.
        Higher score = better exit opportunity.
        
        Factors:
        - Net P&L (after costs) - most important
        - Hold time vs typical recovery
        - Kalman momentum direction
        - Multi-timeframe alignment
        - RSI position
        
        Args:
            data: Dict with position, trading_costs, kalman, multi_timeframe, stock_profile
            
        Returns:
            ExitScoreResult with total_score, interpretation, components, recommendation, confidence
        """
        
        # Simple result class
        class ExitScoreResult:
            def __init__(self, total_score, interpretation, components, recommendation, confidence):
                self.total_score = total_score
                self.interpretation = interpretation
                self.components = components
                self.recommendation = recommendation
                self.confidence = confidence
        
        components = {}
        
        # 1. Net P&L Score (0-40 points)
        # Positive P&L = good exit, negative = bad exit
        trading_costs = data.get('trading_costs', {})
        net_pnl_pct = trading_costs.get('net_pnl_pct', 0)
        
        if net_pnl_pct >= 2.0:
            pnl_score = 40  # Great profit
        elif net_pnl_pct >= 1.0:
            pnl_score = 30  # Good profit
        elif net_pnl_pct >= 0:
            pnl_score = 20  # Breakeven or small profit
        elif net_pnl_pct >= -1.0:
            pnl_score = 10  # Small loss
        else:
            pnl_score = 0   # Significant loss
        components['pnl'] = pnl_score
        
        # 2. Hold Time Score (0-20 points)
        # Exiting too early is bad, reasonable hold time is good
        hold_minutes = data.get('position', {}).get('hold_minutes', 0)
        stock_profile = data.get('stock_profile', {})
        typical_recovery = stock_profile.get('avg_recovery_time_min', 120)
        
        hold_ratio = hold_minutes / typical_recovery if typical_recovery > 0 else 1.0
        
        if hold_ratio >= 1.0:
            time_score = 20  # Held past typical recovery
        elif hold_ratio >= 0.5:
            time_score = 15  # Reasonable hold
        elif hold_ratio >= 0.25:
            time_score = 10  # Short hold
        else:
            time_score = 5   # Very early exit
        components['time'] = time_score
        
        # 3. Momentum Score (0-20 points)
        # Positive momentum = wait, negative = exit now
        kalman = data.get('kalman', {})
        velocity = kalman.get('velocity', 0)
        
        if velocity > 0.1:
            momentum_score = 5   # Rising - bad time to exit
        elif velocity > 0:
            momentum_score = 10  # Slightly rising
        elif velocity > -0.1:
            momentum_score = 15  # Flat/slightly falling
        else:
            momentum_score = 20  # Falling - good time to exit if profitable
        components['momentum'] = momentum_score
        
        # 4. Trend Alignment Score (0-10 points)
        multi_tf = data.get('multi_timeframe', {})
        weekly_trend = multi_tf.get('weekly_trend', 'NEUTRAL')
        daily_trend = multi_tf.get('daily_trend', 'NEUTRAL')
        
        if weekly_trend == 'UPTREND' and daily_trend in ['UPTREND', 'PULLBACK']:
            trend_score = 5   # Strong trend - hold longer
        elif weekly_trend == 'DOWNTREND':
            trend_score = 10  # Weak trend - exit ok
        else:
            trend_score = 7   # Neutral
        components['trend'] = trend_score
        
        # 5. RSI Score (0-10 points)
        current_rsi = data.get('current_rsi', 50)
        
        if current_rsi >= 70:
            rsi_score = 10  # Overbought - good exit
        elif current_rsi >= 60:
            rsi_score = 8   # Getting overbought
        elif current_rsi <= 30:
            rsi_score = 3   # Oversold - bad exit
        else:
            rsi_score = 5   # Neutral
        components['rsi'] = rsi_score
        
        # Total Score
        total_score = sum(components.values())
        
        # Interpretation
        if total_score >= 80:
            interpretation = "EXCELLENT_EXIT"
            recommendation = "Strong exit opportunity - consider taking profits"
        elif total_score >= 60:
            interpretation = "GOOD_EXIT"
            recommendation = "Reasonable exit point - acceptable to close"
        elif total_score >= 40:
            interpretation = "NEUTRAL_EXIT"
            recommendation = "Neither good nor bad - wait for better opportunity"
        elif total_score >= 20:
            interpretation = "POOR_EXIT"
            recommendation = "Suboptimal exit - likely to improve if held"
        else:
            interpretation = "BAD_EXIT"
            recommendation = "Very poor exit - strong hold signal"
        
        # Confidence based on data availability
        confidence = 0.7  # Base confidence
        if kalman:
            confidence += 0.1
        if trading_costs.get('net_pnl') is not None:
            confidence += 0.1
        if multi_tf.get('weekly_trend'):
            confidence += 0.1
        confidence = min(confidence, 1.0)
        
        return ExitScoreResult(
            total_score=total_score,
            interpretation=interpretation,
            components=components,
            recommendation=recommendation,
            confidence=confidence
        )
    
    def _build_chatgpt_data_package(self, symbol: str, position: Dict,
                                     tcas: TCASStatus, ils: ILSStatus,
                                     health: HealthScore, kalman: KalmanState) -> Dict:
        """Build comprehensive data package for ChatGPT"""
        
        entry_price = position.get('entry_price', 0)
        current_price = position.get('current_price', entry_price)
        target_price = position.get('target_price', 0)
        stop_price = position.get('stop_price', 0)
        quantity = position.get('quantity', 0)
        direction = self._get_position_direction(position)
        
        # v4.13.0: Direction-aware calculations
        pnl_pct = self._calculate_pnl_pct(position, current_price)
        distance_to_target = self._calculate_distance_to_target(position, current_price) / current_price * 100 if current_price > 0 else 0
        distance_to_stop = self._calculate_distance_to_stop(position, current_price) / current_price * 100 if current_price > 0 else 0
        
        # Time analysis
        now = datetime.now()
        entry_time = datetime.fromisoformat(position.get('entry_time', now.isoformat()))
        hold_minutes = (now - entry_time).total_seconds() / 60
        market_close = now.replace(hour=15, minute=30)
        minutes_to_close = max(0, (market_close - now).total_seconds() / 60)
        
        # ═══════════════════════════════════════════════════════════════════
        # v4.8.0 NEW: Get Multi-Timeframe Context (B1)
        # ═══════════════════════════════════════════════════════════════════
        multi_timeframe = self._get_multi_timeframe_context(symbol)
        
        # ═══════════════════════════════════════════════════════════════════
        # v4.8.0 NEW: Calculate Trading Costs (B3)
        # v4.13.0: Pass direction for correct P&L calculation
        # ═══════════════════════════════════════════════════════════════════
        direction = self._get_position_direction(position)
        trading_costs = self._calculate_trading_costs(
            symbol, quantity, entry_price, current_price, direction
        )
        
        # ═══════════════════════════════════════════════════════════════════
        # v4.8.0 NEW: Get Stock Profile (B2)
        # ═══════════════════════════════════════════════════════════════════
        from config import get_stock_profile, get_stock_sector
        stock_profile = get_stock_profile(symbol)
        
        # Calculate current vs typical metrics
        current_atr_pct = (position.get('atr', current_price * 0.02) / current_price) * 100
        atr_vs_typical = (current_atr_pct / stock_profile['typical_atr_pct']) if stock_profile['typical_atr_pct'] > 0 else 1.0
        volatility_status = 'HIGH' if atr_vs_typical > 1.3 else 'LOW' if atr_vs_typical < 0.7 else 'NORMAL'
        
        # Log stock profile context
        logger.info(f"   📋 {symbol} Profile: Sector={stock_profile['sector']}, "
                   f"Typical ATR={stock_profile['typical_atr_pct']:.1f}%, "
                   f"Current={current_atr_pct:.1f}% ({volatility_status}), "
                   f"Avg Recovery={stock_profile['avg_recovery_time_min']}min")
        
        # ═══════════════════════════════════════════════════════════════════
        # v4.8.0 NEW: Calculate Exit Score (A4)
        # v4.10.0 FIX: Inline implementation (was missing from intelligent_engine)
        # ═══════════════════════════════════════════════════════════════════
        
        # Build data package first (for exit score calculation)
        data_for_exit_score = {
            'position': {
                'hold_minutes': round(hold_minutes, 0)
            },
            'trading_costs': trading_costs,
            'kalman': kalman.to_dict() if kalman else {},
            'multi_timeframe': multi_timeframe,
            'stock_profile': stock_profile,
            'current_rsi': position.get('current_rsi', 50)  # May not exist, use default
        }
        
        exit_score = self._calculate_exit_score(data_for_exit_score)
        
        # ═══════════════════════════════════════════════════════════════════
        # v4.10.0 NEW: Decision History for Learning Loop
        # Enables ChatGPT to learn from past decisions
        # ═══════════════════════════════════════════════════════════════════
        decision_history_context = {
            'accuracy_stats': {},
            'similar_past_cases': [],
            'available': False
        }
        
        if self.decision_tracker:
            try:
                # Get accuracy stats for this symbol
                accuracy = self.decision_tracker.get_decision_accuracy(symbol, days=30)
                
                # Get similar historical cases
                similar_cases = self.decision_tracker.get_similar_historical_cases(
                    symbol=symbol,
                    current_setup={
                        'pnl_pct': pnl_pct, 
                        'health': health.total_score if health else 50,
                        'tcas': tcas.alert_level.value if tcas else 'UNKNOWN'
                    },
                    max_results=3
                )
                
                decision_history_context = {
                    'available': True,
                    'accuracy_stats': {
                        'total_decisions': accuracy.get('total', 0),
                        'hold_decisions': accuracy.get('hold_count', 0),
                        'exit_decisions': accuracy.get('exit_count', 0),
                        'hold_accuracy_pct': accuracy.get('hold_accuracy', 0),
                        'exit_accuracy_pct': accuracy.get('exit_accuracy', 0),
                        'overall_win_rate_pct': accuracy.get('win_rate', 0)
                    },
                    'similar_past_cases': similar_cases,
                    'learning_insight': self._generate_learning_insight(accuracy)
                }
                
                if similar_cases:
                    logger.info(f"   📚 Decision History: {len(similar_cases)} similar cases found")
                    
            except Exception as e:
                logger.warning(f"   ⚠️ Decision history unavailable: {e}")
        
        # ═══════════════════════════════════════════════════════════════════
        # v4.10.0 NEW: Stock-Specific Sentiment (FinBERT)
        # Provides news awareness for individual stocks
        # ═══════════════════════════════════════════════════════════════════
        stock_sentiment = {
            'label': 'NEUTRAL',
            'score': 0.5,
            'confidence': 0,
            'headlines': [],
            'available': False,
            'warning': None
        }
        
        try:
            from finbert_analyzer import FinBERTAnalyzer
            from news_scraper import NewsScraper
            
            # Use singleton or create instances
            if not hasattr(self, '_finbert_analyzer'):
                self._finbert_analyzer = FinBERTAnalyzer()
            if not hasattr(self, '_news_scraper'):
                self._news_scraper = NewsScraper()
            
            # Step 1: Fetch recent news headlines for this stock
            headlines = self._news_scraper.get_stock_news(symbol, max_results=5)
            
            if headlines:
                # Step 2: Analyze sentiment using FinBERT
                sentiment_result = self._finbert_analyzer.analyze_sentiment(
                    text_list=headlines,
                    symbol=symbol,
                    use_temporal_decay=True
                )
                
                if sentiment_result:
                    # Map FinBERT label to standard format
                    label = sentiment_result.get('label', 'NEUTRAL')
                    if label == 'BULLISH':
                        label = 'POSITIVE'
                    elif label == 'BEARISH':
                        label = 'NEGATIVE'
                    
                    score = sentiment_result.get('sentiment_score', 0)
                    # Convert -1 to +1 range to 0 to 1 range
                    normalized_score = (score + 1) / 2
                    
                    stock_sentiment = {
                        'available': True,
                        'label': label,
                        'score': round(normalized_score, 2),
                        'confidence': round(sentiment_result.get('confidence', 0), 0),
                        'headlines': headlines[:3],
                        'num_articles': sentiment_result.get('num_articles', len(headlines)),
                        'entity_matched': sentiment_result.get('entity_matched', False),
                        'analysis_time': datetime.now().isoformat(),
                        'warning': None
                    }
                    
                    # Add warning for negative sentiment
                    if label == 'NEGATIVE' and normalized_score < 0.35:
                        stock_sentiment['warning'] = f"⚠️ NEGATIVE news sentiment detected (score: {normalized_score:.0%})"
                        logger.warning(f"   📰 {symbol}: {stock_sentiment['warning']}")
                    elif label == 'POSITIVE' and normalized_score > 0.65:
                        logger.info(f"   📰 {symbol}: POSITIVE news sentiment (score: {normalized_score:.0%})")
            else:
                logger.debug(f"   📰 No recent news found for {symbol}")
                    
        except ImportError as e:
            logger.debug(f"   FinBERT/News modules not available: {e}")
        except Exception as e:
            logger.warning(f"   ⚠️ FinBERT sentiment unavailable: {e}")
        
        return {
            # Combined market context (startup + live sentiment)
            'market_context': self.get_combined_market_context(),
            'market_strategist_opinion': self.market_context.get('chatgpt_market_opinion', {}),
            'live_sentiment': self.live_market_sentiment,  # Fresh from Orchestrator
            
            'position': {
                'symbol': symbol,
                'entry_price': entry_price,
                'current_price': current_price,
                'target_price': target_price,
                'stop_price': stop_price,
                'quantity': quantity,
                'product_type': position.get('product', 'CNC'),
                
                'pnl_pct': round(pnl_pct, 2),
                'distance_to_target_pct': round(distance_to_target, 2),
                'distance_to_stop_pct': round(distance_to_stop, 2),
                'hold_minutes': round(hold_minutes, 0)
            },
            
            'time_analysis': {
                'current_time': now.strftime('%H:%M'),
                'minutes_to_market_close': round(minutes_to_close, 0),
                'can_hold_overnight': position.get('product', 'CNC') == 'CNC',
                'mis_cutoff_approaching': minutes_to_close < 30 and position.get('product') == 'MIS'
            },
            
            'tcas': tcas.to_dict(),
            'ils': ils.to_dict(),
            'health': health.to_dict(),
            'kalman': kalman.to_dict() if kalman else {},
            
            # v4.8.0 NEW: Multi-Timeframe Context (B1)
            'multi_timeframe': multi_timeframe,
            
            # v4.8.0 NEW: Trading Costs (B3)
            'trading_costs': trading_costs,
            
            # v4.8.0 NEW: Stock Profile (B2)
            'stock_profile': {
                **stock_profile,  # All profile data
                'current_atr_pct': round(current_atr_pct, 2),
                'atr_vs_typical': round(atr_vs_typical, 2),
                'volatility_status': 'HIGH' if atr_vs_typical > 1.3 else 'LOW' if atr_vs_typical < 0.7 else 'NORMAL'
            },
            
            # v4.8.0 NEW: Exit Score (A4)
            'exit_score': {
                'total_score': exit_score.total_score,
                'interpretation': exit_score.interpretation,
                'components': exit_score.components,
                'recommendation': exit_score.recommendation,
                'confidence': exit_score.confidence
            },
            
            # v4.10.0 NEW: Decision History (Learning Loop)
            'decision_history': decision_history_context,
            
            # v4.10.0 NEW: Stock-Specific Sentiment (FinBERT)
            'stock_sentiment': stock_sentiment,
            
            # v4.12.0 NEW: Multi-Timeframe Flight Plan
            'flight_plan': self._get_flight_plan_for_chatgpt(symbol),
            
            # v4.15.0 NEW: CNC Swing Context
            'position_age': self._calculate_position_age(position),
            'product_type_context': {
                'product': position.get('product', 'CNC'),
                'can_hold_indefinitely': position.get('product', 'CNC') == 'CNC',
                'monitoring_tier': position.get('monitoring_tier', 'TIER_2'),
                'is_swing_position': position.get('product', 'CNC') == 'CNC'
            },
            'daily_kalman': self._fetch_daily_kalman_prediction(symbol),
            'nse_market_context': self._fetch_nse_market_context(),
            
            # v4.15.0: V+P signal (if active)
            'phase4_tracking': position.get('phase4_tracking', {}),
            
            'regime': {
                'current_regime': self.current_regime.value,
                'parameters': self._get_regime_params()
            }
        }
    
    def _generate_learning_insight(self, accuracy: Dict) -> str:
        """
        v4.10.0: Generate a human-readable learning insight from accuracy stats.
        
        This helps ChatGPT understand its own past performance.
        """
        if not accuracy or accuracy.get('total', 0) < 3:
            return "Insufficient history for learning insights"
        
        total = accuracy.get('total', 0)
        hold_acc = accuracy.get('hold_accuracy', 0)
        exit_acc = accuracy.get('exit_accuracy', 0)
        win_rate = accuracy.get('win_rate', 0)
        
        insights = []
        
        # Overall performance
        if win_rate >= 70:
            insights.append(f"Strong performance: {win_rate:.0f}% win rate over {total} decisions")
        elif win_rate >= 50:
            insights.append(f"Moderate performance: {win_rate:.0f}% win rate over {total} decisions")
        else:
            insights.append(f"Below average: {win_rate:.0f}% win rate - review decision logic")
        
        # HOLD vs EXIT accuracy comparison
        if hold_acc > exit_acc + 15:
            insights.append(f"HOLD decisions more accurate ({hold_acc:.0f}% vs EXIT {exit_acc:.0f}%) - bias toward holding")
        elif exit_acc > hold_acc + 15:
            insights.append(f"EXIT decisions more accurate ({exit_acc:.0f}% vs HOLD {hold_acc:.0f}%) - bias toward exiting")
        
        # Specific recommendations
        if hold_acc < 50 and accuracy.get('hold_count', 0) >= 3:
            insights.append("⚠️ HOLD decisions often wrong - consider earlier exits")
        if exit_acc < 50 and accuracy.get('exit_count', 0) >= 3:
            insights.append("⚠️ EXIT decisions often wrong - consider holding longer")
        
        return " | ".join(insights) if insights else "No significant patterns detected"
    
    def _consult_chatgpt(self, symbol: str, data_package: Dict, reason: str) -> Optional[Dict]:
        """
        Consult ChatGPT for exit decision.
        
        v4.8.1: Now logs decisions (C1) and increments consultation count (C3)
        v5.3.2: HARD consultation limit check + ghost position guard
        
        Returns:
            Decision dict with action, confidence, reasoning
        """
        if not self.chatgpt:
            return None
        
        # v5.3.2 FIX-A: Ghost position guard — never consult for externally closed positions
        if hasattr(self, '_closed_externally_today') and symbol in self._closed_externally_today:
            logger.info(f"   🚫 {symbol}: Ghost position — skipping ChatGPT consultation")
            return None
        
        # v5.3.2 FIX-B: HARD consultation count limit (was only checked in _should_consult)
        # Critical rules (RA+BigLoss, LowHealth+Loss) used to bypass this check
        allowed, limit_reason = self._check_consultation_allowed(symbol)
        if not allowed:
            logger.info(f"   🚫 {symbol}: {limit_reason} — skipping API call")
            return None
        
        try:
            # ═══════════════════════════════════════════════════════════════
            # v4.8.1 C3: Increment consultation count
            # ═══════════════════════════════════════════════════════════════
            self._increment_consultation_count(symbol)
            
            logger.info(f"🤖 Consulting ChatGPT for {symbol} (Reason: {reason})")

            # ═══════════════════════════════════════════════════════════════
            # MIE v1.0.0: Build exit intelligence context
            # ═══════════════════════════════════════════════════════════════
            mie_intelligence = None
            if self.mie:
                try:
                    position = self.positions.get(symbol, {})
                    source = position.get('source', 'PHASE_3_CNC')
                    product = position.get('product', 'CNC')

                    # Map source to MIE phase_source
                    if 'PHASE5' in source or 'GAP' in source:
                        phase_source = "PHASE_5_MIS"
                    elif 'PHASE6' in source or 'OPTION' in source:
                        phase_source = "PHASE_6_OPTIONS"
                    else:
                        phase_source = "PHASE_3_CNC"

                    intelligence = self.mie.get_exit_context(
                        symbol=symbol,
                        position=position,
                        stock_monitor=self._get_monitor(symbol) if hasattr(self, '_get_monitor') else None,
                        phase_source=phase_source,
                        product_type=product
                    )
                    mie_intelligence = intelligence.to_dict() if intelligence else None
                    if mie_intelligence:
                        logger.info(f"   📊 MIE exit context built for {symbol}")
                except Exception as e:
                    logger.warning(f"   ⚠️ MIE exit context failed: {e}")
                    mie_intelligence = None

            # Call ChatGPT
            decision = self.chatgpt.evaluate_position_for_phase4(
                position_data=data_package,
                market_strategist_opinion=data_package.get('market_strategist_opinion', {}),
                live_market_sentiment=self.live_market_sentiment,
                intelligence_package=mie_intelligence
            )
            
            # Record consultation time
            self.last_chatgpt_call[symbol] = datetime.now()
            
            # Track in position
            position = self.positions.get(symbol)
            if position and 'phase4_tracking' in position:
                position['phase4_tracking']['chatgpt_consultations'].append({
                    'time': datetime.now().isoformat(),
                    'reason': reason,
                    'decision': decision.get('decision', 'UNKNOWN'),
                    'confidence': decision.get('confidence', 0)
                })
            
            # ═══════════════════════════════════════════════════════════════
            # v4.8.1 C1: Log decision for outcome tracking
            # ═══════════════════════════════════════════════════════════════
            if self.decision_tracker and position:
                self.decision_tracker.record_decision(
                    symbol=symbol,
                    decision=decision.get('decision', 'UNKNOWN'),
                    reason=reason,
                    confidence=decision.get('confidence', 0.5),
                    position_data={
                        'current_price': position.get('current_price', 0),
                        'entry_price': position.get('entry_price', 0),
                        'target_price': position.get('target_price', 0),
                        'stop_price': position.get('stop_price', 0),
                        'net_pnl': data_package.get('trading_costs', {}).get('net_pnl', 0)
                    },
                    probabilistic_analysis=decision.get('probabilistic_analysis')
                )
            
            logger.info(f"   Decision: {decision.get('decision', 'UNKNOWN')}")
            logger.info(f"   Confidence: {decision.get('confidence', 0):.0%}")
            
            return decision
            
        except Exception as e:
            logger.error(f"ChatGPT consultation failed: {e}")
            return None
    
    def _execute_chatgpt_decision(self, symbol: str, decision: Dict):
        """Execute ChatGPT decision"""
        if not decision:
            return
        
        action = decision.get('decision', 'HOLD')
        position = self.positions.get(symbol)
        
        if not position:
            return
        
        logger.info(f"📋 Executing ChatGPT decision for {symbol}: {action}")
        
        if action == 'HOLD':
            # No action needed
            pass
        
        elif action == 'TIGHTEN_STOP':
            new_stop = decision.get('gtt_modifications', {}).get('new_stop_price')
            
            # FALLBACK: Calculate new stop if ChatGPT didn't provide specific price
            if not new_stop:
                current_price = position.get('current_price', position.get('entry_price', 0))
                entry_price = position.get('entry_price', 0)
                current_stop = position.get('stop_price', 0)
                
                # Tighten to halfway between current stop and current price
                if current_price > current_stop:
                    new_stop = current_stop + (current_price - current_stop) * 0.5
                    logger.info(f"   📐 Calculated tightened stop: ₹{new_stop:.2f} (midpoint)")
            
            if new_stop and new_stop > position.get('stop_price', 0):
                self._modify_gtt_stop(symbol, new_stop)
            else:
                logger.info(f"   ⏸️ Stop not modified (no valid new price)")
        
        elif action == 'WIDEN_STOP':
            new_stop = decision.get('gtt_modifications', {}).get('new_stop_price')
            
            # FALLBACK: Calculate wider stop for overnight
            if not new_stop:
                entry_price = position.get('entry_price', 0)
                current_stop = position.get('stop_price', 0)
                # Widen by additional 1% for overnight gap protection
                new_stop = entry_price * 0.97  # 3% below entry
                logger.info(f"   📐 Calculated widened stop: ₹{new_stop:.2f} (overnight protection)")
            
            if new_stop and new_stop < position.get('stop_price', 0):
                self._modify_gtt_stop(symbol, new_stop)
            else:
                logger.info(f"   ⏸️ Stop not modified (would be tighter, not wider)")
        
        elif action == 'EXTEND_TARGET':
            new_target = decision.get('gtt_modifications', {}).get('new_target_price')
            
            # FALLBACK: Extend target by 1.5%
            if not new_target:
                current_target = position.get('target_price', 0)
                if current_target:
                    new_target = current_target * 1.015  # Extend by 1.5%
                    logger.info(f"   📐 Calculated extended target: ₹{new_target:.2f} (+1.5%)")
            
            if new_target and new_target > position.get('target_price', 0):
                self._modify_gtt_target(symbol, new_target)
            else:
                logger.info(f"   ⏸️ Target not modified (no valid new price)")
        
        elif action in ['PARTIAL_25', 'PARTIAL_50']:
            pct = 25 if action == 'PARTIAL_25' else 50
            self._execute_partial_exit(symbol, pct, f"ChatGPT: {action}")
        
        elif action == 'EXIT':
            # ═══════════════════════════════════════════════════════════════
            # v5.2.1 SAFETY GUARDS: Prevent premature ChatGPT exits
            # ChatGPT tends to exit too early on low health scores.
            # These guards downgrade EXIT → TIGHTEN_STOP when conditions
            # indicate the position should be given more time.
            # ═══════════════════════════════════════════════════════════════
            
            entry_price = position.get('entry_price', 0)
            current_price = position.get('current_price', entry_price)
            pnl_pct = self._calculate_pnl_pct(position, current_price) if entry_price else 0
            gross_pnl = (current_price - entry_price) * position.get('quantity', 1)

            # v5.3.2 FIX: Ghost position bypass — if position not at broker, skip ALL guards
            # MUST run BEFORE CNC Shield — shield would block cleanup + averaging could buy ghost
            if hasattr(self, '_closed_externally_today') and symbol in self._closed_externally_today:
                logger.warning(f"   🛡️ {symbol}: Ghost position detected — skipping guards, forcing cleanup")
                self._handle_external_close(symbol)
                return

            # ═══════════════════════════════════════════════════════════
            # v5.5.0: CNC SHIELD — Green-Only Exit Block
            # CNC LONG held 1+ days NEVER exits in red. No exceptions.
            # ═══════════════════════════════════════════════════════════
            if self._is_cnc_shield_active(position) and getattr(self.config, 'CNC_SHIELD_GREEN_ONLY', True):  # v5.5.0
                if pnl_pct < 0:
                    logger.warning(f"   🛡️ CNC SHIELD: EXIT BLOCKED for {symbol} (P&L {pnl_pct:.1f}% < 0)")
                    logger.info(f"   🛡️ CNC LONG never exits in red → WIDEN + check averaging")

                    # Widen stop instead of exiting
                    self._cnc_shield_widen_stop(symbol, position, current_price, 'EXIT_BLOCKED')

                    # Check averaging opportunity
                    self._cnc_shield_check_averaging(symbol, position, current_price)

                    if self.telegram:
                        self.telegram.send_message(
                            f"🛡️ CNC SHIELD: EXIT BLOCKED\n\n"
                            f"Stock: {symbol}\n"
                            f"P&L: {pnl_pct:.1f}% (IN RED)\n"
                            f"ChatGPT wanted EXIT → BLOCKED\n"
                            f"Stop widened, checking averaging\n"
                            f"Rule: CNC LONG never exits in red"
                        )
                    return  # EXIT completely blocked  # v5.5.0
            
            # Calculate hold time
            entry_time_str = position.get('entry_time', '')
            hold_minutes = 0
            if entry_time_str:
                try:
                    entry_time = datetime.fromisoformat(entry_time_str)
                    hold_minutes = (datetime.now() - entry_time).total_seconds() / 60
                except:
                    pass
            
            # Get TCAS status (ALIM always overrides guards)
            tcas_data = position.get('phase4_tracking', {}).get('tcas_status', {})
            is_alim = tcas_data.get('alert_level') == 'ALIM'
            
            exit_blocked = False
            block_reason = ""
            
            # GUARD 1: Minimum hold time (30 min) — too early to judge
            if not is_alim and hold_minutes < 30:
                exit_blocked = True
                block_reason = f"HOLD_TIME_GUARD: {hold_minutes:.0f}min < 30min minimum"
            
            # GUARD 2: Net P&L floor — exiting with tiny PROFIT = net loss after fees
            # v5.3.2 FIX: Only block POSITIVE tiny P&L (thin profits eaten by fees)
            # NEVER block negative P&L (loss-cutting exits must always be allowed)
            if not is_alim and not exit_blocked and 0 < gross_pnl < 50:
                exit_blocked = True
                block_reason = f"NET_PNL_GUARD: Gross P&L ₹{gross_pnl:.0f} too small (fees would eat profit)"
            
            # GUARD 3: Weekly uptrend override — dip is noise, not danger
            if not is_alim and not exit_blocked and pnl_pct > -2.0:
                mtf = position.get('phase4_tracking', {}).get('multi_timeframe', {})
                weekly_trend = mtf.get('weekly_trend', '')
                if weekly_trend == 'UPTREND':
                    exit_blocked = True
                    block_reason = f"WEEKLY_UPTREND_GUARD: Loss {pnl_pct:.1f}% < 2% in weekly uptrend"
            
            if exit_blocked:
                # Downgrade to TIGHTEN_STOP instead of exiting
                logger.warning(f"   🛡️ EXIT BLOCKED for {symbol}: {block_reason}")
                logger.info(f"   🛡️ Downgrading EXIT → TIGHTEN_STOP")
                
                # Tighten stop defensively
                current_stop = position.get('stop_price', 0)
                if current_price > current_stop and current_stop > 0:
                    new_stop = current_stop + (current_price - current_stop) * 0.4
                    if new_stop > current_stop:
                        self._modify_gtt_stop(symbol, new_stop)
                        logger.info(f"   🛡️ Stop tightened: ₹{current_stop:.2f} → ₹{new_stop:.2f}")
                
                if self.telegram:
                    self.telegram.send_message(
                        f"🛡️ EXIT BLOCKED: {symbol}\n"
                        f"Reason: {block_reason}\n"
                        f"Action: Tightened stop instead"
                    )
            else:
                self._execute_exit(symbol, ExitReason.CHATGPT_EXIT.value)
        
        elif action == 'HOLD_FOR_TOMORROW':
            # Widen stop for overnight
            entry_price = position.get('entry_price', 0)
            current_stop = position.get('stop_price', 0)
            new_stop = entry_price * (1 - (self.GTT_OVERNIGHT_BUFFER + 1) / 100)
            
            if new_stop < current_stop:
                self._modify_gtt_stop(symbol, new_stop)
            
            position['overnight_hold'] = True
            
            if self.telegram:
                self.telegram.send_message(
                    f"🌙 HOLDING OVERNIGHT: {symbol}\n\n"
                    f"Stop widened for gap protection\n"
                    f"Target expected: Tomorrow"
                )
    
    def _run_morning_briefing(self):
        """Morning briefing with ChatGPT"""
        if not self.chatgpt or not self.positions:
            return
        
        logger.info("☀️ Running Morning Briefing...")
        
        try:
            # Build portfolio summary
            portfolio_data = {
                'positions': [],
                'market_context': self.market_context,
                'date': datetime.now().strftime('%Y-%m-%d')
            }
            
            for symbol, position in self.positions.items():
                portfolio_data['positions'].append({
                    'symbol': symbol,
                    'entry_price': position.get('entry_price', 0),
                    'quantity': position.get('quantity', 0),
                    'product': position.get('product', 'CNC'),
                    'overnight_hold': position.get('overnight_hold', False)
                })
            
            # Get briefing from ChatGPT
            if hasattr(self.chatgpt, 'portfolio_morning_briefing'):
                briefing = self.chatgpt.portfolio_morning_briefing(
                    yesterday_data={},
                    current_positions=portfolio_data['positions'],
                    market_strategist_opinion=self.market_context.get('chatgpt_market_opinion', {}),
                    live_market_sentiment=self.live_market_sentiment  # Fresh sentiment
                )
                
                logger.info(f"   Operation Mode: {briefing.get('operation_mode', 'NORMAL')}")
                
                # Execute any position decisions
                for pos_decision in briefing.get('position_decisions', []):
                    symbol = pos_decision.get('symbol')
                    action = pos_decision.get('action')
                    if action and action != 'HOLD':
                        self._execute_chatgpt_decision(symbol, {'decision': action})
            
        except Exception as e:
            logger.error(f"Morning briefing failed: {e}")

    # ═══════════════════════════════════════════════════════════════════════════
    # EXIT EXECUTION (v4.9.0: Now handles SELL orders directly, not via Phase 3)
    # ═══════════════════════════════════════════════════════════════════════════
    
    def _execute_exit(self, symbol: str, reason: str) -> bool:
        """
        Execute full position exit with appropriate order.
        
        v4.13.0: Direction-aware for LONG and SHORT positions.
        - LONG: Exit via SELL order
        - SHORT: Exit via BUY order
        
        v4.9.0: Handles order placement directly (moved from Phase 3).
        v4.8.1: Records outcomes (C1) and exits (C2) for tracking
        
        Args:
            symbol: Stock to exit
            reason: Exit reason
            
        Returns:
            True if successful
        """
        logger.info(f"🚨 EXECUTING EXIT: {symbol} - {reason}")
        
        position = self.positions.get(symbol)
        if not position:
            logger.warning(f"Position not found: {symbol}")
            return False
        
        # v4.13.0: Get direction for logging and P&L calculation
        direction = self._get_position_direction(position)
        exit_type = self._get_exit_transaction_type(direction)
        logger.info(f"   Direction: {direction} → Exit via {exit_type}")

        # ═══════════════════════════════════════════════════════════════════
        # v1.0.0: Phase 9 Fund Manager — Exit Advisor
        # Soft exits (TCAS_RA, TRAILING, BREAKEVEN) can be overridden.
        # Hard exits (STOP_LOSS, MIS_CUTOFF, ALIM) are never blocked.
        # ═══════════════════════════════════════════════════════════════════
        # v1.1.0: Skip Claude for hard exits (non-negotiable) — cost saving
        # v1.2.0: 'TIER1' covers ALL PH5 scalp exits (9:15-10:00am window).
        #         These are sub-second mechanical decisions — Claude latency
        #         (2-8s) would miss the exit window entirely.
        #         TIER1_ATR_PROXIMITY, TIER1_HARD_EXIT_TIME, TIER1_BREAKEVEN_EXIT
        #         are all non-negotiable mechanical exits for PH5 scalps.
        # v1.2.1: Added TARGET (profit confirmed, don't second-guess),
        #         GTT (broker order already triggered),
        #         CHATGPT (ChatGPT already decided, no dual-review needed)
        _hard_exit_tokens = ('STOP_LOSS', 'STOP', 'ALIM', 'MIS_CUTOFF',
                             'MIS_MANDATORY', 'HARD_STOP', 'CIRCUIT',
                             'EMERGENCY', 'MANUAL', 'TIER1', 'HEALTH',
                             'TARGET', 'GTT', 'CHATGPT_EXIT')
        _reason_u = str(reason or '').upper()
        _is_hard_exit = any(tok in _reason_u for tok in _hard_exit_tokens)

        if (not _is_hard_exit
                and hasattr(self, 'fund_manager') and self.fund_manager
                and getattr(self.config, 'PH9_EXIT_ADVISOR_ENABLED', False)):
            try:
                # v1.4.0: Pass rich market context so Claude can make better exit decisions
                _ph4_tracking = position.get('phase4_tracking', {})
                _kal_state    = _ph4_tracking.get('kalman_state', {})
                _tcas_status  = _ph4_tracking.get('tcas_status', {})
                _now_dt       = datetime.now()
                _mis_remaining = max(0, int((
                    datetime.combine(_now_dt.date(), dt_time(15, 15)) - _now_dt
                ).total_seconds() / 60))

                _entry  = float(position.get('entry_price', 0) or 0)
                _cur    = float(position.get('current_price', _entry) or _entry)
                _pnl_pct = ((_cur - _entry) / _entry * 100) if _entry > 0 else 0
                if str(position.get('direction', 'LONG')).upper() in ('SHORT', 'SELL'):
                    _pnl_pct = -_pnl_pct

                _market_ctx = {
                    'kalman_velocity':    _kal_state.get('velocity', 'N/A'),
                    'kalman_acceleration':_kal_state.get('acceleration', 'N/A'),
                    'tcas_level':         _tcas_status.get('level', 'N/A'),
                    'pnl_pct':            round(_pnl_pct, 2),
                    'time_now':           _now_dt.strftime('%H:%M'),
                    'mis_minutes_remaining': _mis_remaining,
                    'regime':             getattr(self.fund_manager, 'todays_regime', 'NORMAL'),
                    'exit_aggression':    getattr(self, 'daily_briefing', {}).get('exit_aggression', 'NORMAL'),
                }

                # v1.3.2: Enrich soft exits (TCAS_RA etc.) with OHLCV/RSI/ATR/Kalman/OI
                # Hard exits never reach this block so enrichment cost is justified
                try:
                    _rich = self._enrich_exit_context(symbol, position)
                    _market_ctx.update(_rich)
                except Exception as _ece:
                    logger.debug(f"Exit context enrichment failed for {symbol}: {_ece}")

                exit_advice = self.fund_manager.advise_exit(
                    symbol=symbol,
                    position=position,
                    exit_reason=reason,
                    market_context=_market_ctx
                )

                action = exit_advice.get('action', 'EXIT')
                logger.info(f"   🧠 Fund Manager exit advice: {action} "
                           f"(confidence: {exit_advice.get('confidence', 0)}%)")
                logger.info(f"      Reason: {exit_advice.get('reasoning', '')[:200]}")

                if action == 'HOLD':
                    logger.info(f"   ⏸️ Fund Manager says HOLD — exit cancelled for {symbol}")
                    return False

                if action == 'TRAIL' and exit_advice.get('new_stop'):
                    new_stop = exit_advice['new_stop']
                    logger.info(f"   📐 Fund Manager says TRAIL — new stop: ₹{new_stop:.2f}")
                    # Update stop in position (best-effort via orchestrator)
                    try:
                        if hasattr(self, '_orchestrator') and self._orchestrator:
                            self._orchestrator.update_position_field(
                                symbol, 'stop_price', new_stop)
                        position['stop_price'] = new_stop
                    except Exception:
                        pass
                    return False  # Don't exit yet, trail instead

            except Exception as e:
                logger.error(f"Fund Manager exit advice error: {e} — proceeding with exit")

        # Send manual exit card BEFORE order attempt — user can act manually if API fails
        self._send_manual_exit_card(symbol, position, reason)

        # Execute the exit order
        exit_price = self._place_exit_order(symbol, position, reason)
        
        if exit_price is not None:
            # v4.13.0: Direction-aware P&L calculation
            entry_price = position.get('entry_price', 0)
            pnl_pct = self._calculate_pnl_pct(position, exit_price)
            
            # ═══════════════════════════════════════════════════════════
            # v4.8.1 C1: Record outcome for decision history
            # ═══════════════════════════════════════════════════════════
            if self.decision_tracker:
                # Determine outcome type
                if 'TARGET' in reason.upper():
                    outcome = 'TARGET_HIT'
                elif 'STOP' in reason.upper() or 'ALIM' in reason.upper():
                    outcome = 'STOP_HIT'
                elif 'CHATGPT' in reason.upper():
                    outcome = 'CHATGPT_EXIT'
                elif 'MIS' in reason.upper():
                    outcome = 'MIS_MANDATORY_EXIT'
                else:
                    outcome = 'MANUAL_EXIT'
                
                self.decision_tracker.record_outcome(
                    symbol=symbol,
                    outcome=outcome,
                    outcome_price=exit_price,
                    actual_pnl=pnl_pct
                )
                
                # ═══════════════════════════════════════════════════════════
                # v4.11.0: Track prediction accuracy at exit
                # ═══════════════════════════════════════════════════════════
                self._track_prediction_accuracy(symbol, exit_price, position)
            
            # ═══════════════════════════════════════════════════════════
            # v4.8.1 C2: Record exit for loop detection
            # ═══════════════════════════════════════════════════════════
            self._record_exit(symbol, exit_price, reason)
            
            # If target hit, clear exit history (successful trade, allow re-entry)
            if 'TARGET' in reason.upper():
                self._clear_exit_history_for_symbol(symbol)
            
            # Update position via orchestrator
            self.on_position_closed(symbol, reason)

            # ═══════════════════════════════════════════════════════════
            # v1.0.0: Phase 9 Fund Manager — P&L tracking
            # ═══════════════════════════════════════════════════════════
            if hasattr(self, 'fund_manager') and self.fund_manager:
                try:
                    quantity = position.get('quantity', 0)
                    if direction == 'SHORT':
                        pnl_rupees = (entry_price - exit_price) * quantity
                    else:
                        pnl_rupees = (exit_price - entry_price) * quantity
                    self.fund_manager.update_daily_pnl(pnl_rupees, symbol)
                    # v1.6.0: Per-phase attribution
                    if hasattr(self.fund_manager, 'record_trade_pnl'):
                        _src = position.get('_ph9_source', 'UNKNOWN')
                        self.fund_manager.record_trade_pnl(_src, pnl_rupees, symbol)
                    # v1.3.0: Clear recovery state when position closes
                    if hasattr(self.fund_manager, 'clear_recovery'):
                        self.fund_manager.clear_recovery(symbol)

                    # v1.3.2: Post-ALIM re-entry advisor
                    # Only for ALIM-forced exits at a realized loss — give Claude one
                    # chance to assess whether a re-entry at a better price makes sense.
                    _is_alim = 'ALIM' in str(reason or '').upper()
                    _loss_ok = pnl_rupees < -getattr(
                        self.config, 'PH9_REENTRY_MIN_LOSS_INR', 300)
                    if (_is_alim and _loss_ok
                            and getattr(self.config, 'PH9_REENTRY_ENABLED', True)
                            and hasattr(self.fund_manager, 'post_exit_reentry_advisor')):
                        try:
                            _exit_ctx = self._enrich_exit_context(symbol, dict(position))
                            self.fund_manager.post_exit_reentry_advisor(
                                symbol=symbol,
                                closed_position=dict(position),
                                realized_pnl_inr=pnl_rupees,
                                exit_price=float(exit_price or 0),
                                market_data=_exit_ctx,
                            )
                        except Exception as _re_e:
                            logger.error(f"Post-ALIM reentry advisor failed for {symbol}: {_re_e}")
                except Exception as e:
                    logger.debug(f"Fund Manager P&L update failed: {e}")

            # ═══════════════════════════════════════════════════════════
            # ISSUE-15: TCAS Pivot → Phase 6 exit confirmation
            # Early warning was already sent at TCAS RA (equity still open).
            # Now equity is closed — notify Phase 6 so it knows the position
            # is gone and can time its options entry without waiting for equity.
            # ═══════════════════════════════════════════════════════════
            tcas_reasons = {ExitReason.TCAS_ALIM.value, ExitReason.TCAS_RA_EXIT.value}
            if (
                self.phase6 is not None
                and reason in tcas_reasons
                and direction == 'SHORT'
                and symbol in self.tcas_pivot_early_signaled
            ):
                try:
                    exit_signal = {
                        'symbol': symbol,
                        'status': 'EXIT_CONFIRMED',  # equity closed — Phase 6 free to act
                        'exit_price': exit_price,
                        'exit_reason': reason,
                        'equity_pnl': pnl_pct,
                        'signal_time': datetime.now(),
                    }
                    logger.info(
                        f"📡 TCAS PIVOT EXIT: {symbol} equity closed ({reason}, "
                        f"pnl={pnl_pct:.1f}%) → Phase 6 notified"
                    )
                    self.phase6.on_tcas_direction_signal(exit_signal)
                except Exception as e:
                    logger.error(f"TCAS pivot exit confirmation failed for {symbol}: {e}")

            # v4.9.0: Position removal handled by _place_exit_order via _delete_position

            return True
        else:
            logger.warning(f"⚠️ {symbol}: Exit failed, will retry next cycle")
            return False
    
    def _place_exit_order(self, symbol: str, position: Dict, reason: str) -> Optional[float]:
        """
        v4.13.0: Place exit order with retry logic and market order fallback.
        
        Direction-aware: SELL for LONG, BUY for SHORT.
        Renamed from _place_sell_order for clarity.
        
        Features:
        - Sets EXIT_IN_PROGRESS state to prevent duplicate exits
        - Cancels GTT orders before manual exit
        - Retry logic with exponential backoff
        - Market order fallback after 3 failures
        - Capital release via Capital Manager
        - Trade logging and Telegram notifications
        
        Args:
            symbol: Stock symbol
            position: Position dict with entry_price, quantity, etc.
            reason: Exit reason for logging
            
        Returns:
            float: Exit price if successful, None if failed
        """
        # v4.10.0 FIX: Use local PositionState enum instead of missing module
        class PositionState:
            OPEN = 'OPEN'
            EXIT_IN_PROGRESS = 'EXIT_IN_PROGRESS'
            CLOSED = 'CLOSED'
        
        # v4.13.0: Get direction-aware exit transaction type
        direction = self._get_position_direction(position)
        exit_transaction = self._get_exit_transaction_type(direction)
        
        # ═══════════════════════════════════════════════════════════════
        # Set EXIT_IN_PROGRESS state to prevent duplicate exit attempts
        # ═══════════════════════════════════════════════════════════════
        # v5.4.0 FIX: Honor transition guard. Abort if state transition is
        # rejected (e.g. position is already EXIT_IN_PROGRESS from a prior cycle).
        if self.orchestrator and hasattr(self.orchestrator, 'transition_position_state'):
            transition_ok = self.orchestrator.transition_position_state(
                symbol, PositionState.EXIT_IN_PROGRESS, reason
            )
            if not transition_ok:
                logger.warning(
                    f"🚫 {symbol}: Exit aborted — state transition rejected by guard "
                    f"(likely already EXIT_IN_PROGRESS). Skipping duplicate attempt."
                )
                return None

        # v5.4.0: 'status' field migrated to 'state' via orchestrator. No local mutation.
        self._save_positions()
        logger.info(f"🔄 {symbol}: State → EXIT_IN_PROGRESS ({direction} → {exit_transaction})")

        # ═══════════════════════════════════════════════════════════════
        # PAPER MODE: skip real broker ops — simulate exit from live price
        # ═══════════════════════════════════════════════════════════════
        _is_paper = position.get('is_paper_trade', False) or getattr(self.config, 'MASTER_PAPER_MODE', False)
        if _is_paper:
            try:
                quote = self.kite.quote([f"NSE:{symbol}"])
                sim_exit_price = quote.get(f"NSE:{symbol}", {}).get('last_price', position.get('entry_price', 0))
            except Exception:
                sim_exit_price = position.get('current_price', position.get('entry_price', 0))
            logger.info(f"   📝 PAPER EXIT: {symbol} simulated @ ₹{sim_exit_price:.2f}  reason={reason}")
            try:
                from paper_trade_logger import log_paper_exit
                _logger_id = position.get('paper_logger_id')
                if _logger_id:
                    log_paper_exit(trade_id=_logger_id, exit_price=sim_exit_price, exit_reason=reason)
                    logger.info(f"   📊 PAPER LOG: exit recorded → {_logger_id}  ₹{sim_exit_price:.2f}")
                else:
                    logger.warning(f"   ⚠️ PAPER LOG: no paper_logger_id on position — exit not logged to Excel")
            except Exception as _le:
                logger.warning(f"   ⚠️ paper_trade_logger exit failed: {_le}")
            return sim_exit_price

        # ═══════════════════════════════════════════════════════════════
        # Cancel GTT orders before manual exit
        # v5.3.5 FIX: Always run orphan scan (Phase B) regardless of
        # known-ID cancel results, to catch GTTs whose IDs were lost
        # (e.g. after false-close/re-adoption from BrokerSync timeout)
        # ═══════════════════════════════════════════════════════════════
        logger.info(f"   Cancelling GTT orders before exit...")
        try:
            self._cancel_all_gtt_for_symbol(symbol)
        except Exception as e:
            logger.error(f"   GTT cancellation failed: {e}")

        # v5.3.5: Post-cancel verification — scan broker for any surviving GTTs
        try:
            import time
            time.sleep(1)  # Brief pause for Kite API to process cancellations
            broker_gtts = self.kite.get_gtts()
            surviving = [g for g in (broker_gtts or [])
                         if g.get('tradingsymbol') == symbol and g.get('status') == 'active']
            if surviving:
                logger.warning(f"   ⚠️ {symbol}: {len(surviving)} GTT(s) still active after cancel — retrying")
                for gtt in surviving:
                    self._cancel_gtt(gtt['id'])
                # Final check
                time.sleep(1)
                broker_gtts2 = self.kite.get_gtts()
                still_alive = [g for g in (broker_gtts2 or [])
                               if g.get('tradingsymbol') == symbol and g.get('status') == 'active']
                if still_alive:
                    logger.error(f"   🚨 {symbol}: {len(still_alive)} GTT(s) STILL ACTIVE after retry!")
                    logger.error(f"   🚨 MANUAL CANCELLATION REQUIRED: GTT IDs {[g['id'] for g in still_alive]}")
                else:
                    logger.info(f"   ✅ {symbol}: All GTTs confirmed cancelled after retry")
            else:
                logger.info(f"   ✅ {symbol}: No active GTTs remaining (clean exit)")
        except Exception as e:
            logger.warning(f"   ⚠️ {symbol}: Post-cancel GTT verification failed: {e}")
        
        # ═══════════════════════════════════════════════════════════════
        # EXIT with retry logic and market order fallback
        # ═══════════════════════════════════════════════════════════════
        retry_count = position.get('exit_retries', 0)
        max_retries = 3
        retry_delays = [2, 5, 10]  # Exponential backoff
        
        try:
            # Determine order type based on retry count
            if retry_count >= max_retries:
                # Final attempt: Use MARKET order for guaranteed fill
                logger.warning(f"⚠️ {symbol}: {max_retries} previous {exit_transaction} failures, using MARKET order")
                
                order_id = self._place_market_order_internal(
                    symbol=symbol,
                    quantity=position['quantity'],
                    transaction_type=exit_transaction,
                    product=position.get('product', 'CNC')
                )
                
                if self.telegram:
                    self.telegram.send_message(
                        f"⚠️ EXIT ESCALATION\n\n"
                        f"Symbol: {symbol}\n"
                        f"Direction: {direction}\n"
                        f"Exit Type: {exit_transaction}\n"
                        f"Reason: {reason}\n\n"
                        f"{max_retries} LIMIT order failures.\n"
                        f"Using MARKET order for exit."
                    )
            else:
                # Normal exit order attempt
                order_id = self._place_exit_order_internal(
                    symbol=symbol,
                    quantity=position['quantity'],
                    transaction_type=exit_transaction,
                    product=position.get('product', 'CNC')
                )
            
            if not order_id:
                logger.error(f"Failed to place {exit_transaction} order for {symbol}")

                # v5.4.0 FIX: Persist retry tracking through orchestrator
                # Status restore now handled via state machine in PHASE 3
                retry_count += 1
                self._update_position(symbol, position,
                                      exit_retries=retry_count,
                                      last_exit_attempt=datetime.now().isoformat())
                # Restore central state to OPEN so next cycle can legitimately retry
                if self.orchestrator and hasattr(self.orchestrator, 'transition_position_state'):
                    self.orchestrator.transition_position_state(
                        symbol, PositionState.OPEN, "exit_retry_after_placement_failure"
                    )
                self._save_positions()
                
                logger.warning(f"⚠️ {symbol}: {exit_transaction} order placement failed (retry {retry_count}/{max_retries})")
                
                if retry_count >= max_retries:
                    if self.telegram:
                        self.telegram.send_message(
                            f"🚨 EXIT FAILURE\n\n"
                            f"Symbol: {symbol}\n"
                            f"Direction: {direction}\n"
                            f"Retries: {retry_count}\n\n"
                            f"Cannot place {exit_transaction} order.\n"
                            f"Next attempt will use MARKET order.\n"
                            f"If MARKET also fails: MANUAL INTERVENTION REQUIRED!"
                        )
                
                return None
            
            logger.info(f"{exit_transaction} order placed: {order_id} (attempt {retry_count + 1})")
            
            # Wait for fill with retry-specific delay
            delay = retry_delays[min(retry_count, len(retry_delays) - 1)]
            time.sleep(delay)
            
            # Wait for fill
            exit_price = self._wait_for_order_fill(order_id)
            
            if not exit_price:
                logger.error(f"SELL order {order_id} not filled for {symbol}")

                # v5.4.0 FIX: Persist retry tracking through orchestrator
                retry_count += 1
                self._update_position(symbol, position,
                                      exit_retries=retry_count,
                                      last_exit_attempt=datetime.now().isoformat())
                # Restore central state to OPEN so next cycle can legitimately retry
                if self.orchestrator and hasattr(self.orchestrator, 'transition_position_state'):
                    self.orchestrator.transition_position_state(
                        symbol, PositionState.OPEN, "exit_retry_after_fill_failure"
                    )
                self._save_positions()
                
                logger.warning(f"⚠️ {symbol}: SELL not filled (retry {retry_count}/{max_retries})")
                
                if retry_count == 2:
                    if self.telegram:
                        self.telegram.send_message(
                            f"⚠️ EXIT RETRY WARNING\n\n"
                            f"Symbol: {symbol}\n"
                            f"Retries: {retry_count}/{max_retries}\n\n"
                            f"SELL orders not filling.\n"
                            f"Next attempt will use MARKET order."
                        )
                
                return None
            
            # Success! Log recovery if retries were needed
            if retry_count > 0:
                logger.info(f"✅ {symbol}: Exit successful after {retry_count} retries")
                if self.telegram and retry_count > 1:
                    self.telegram.send_message(
                        f"✅ EXIT RECOVERED\n\n"
                        f"Symbol: {symbol}\n"
                        f"Retries: {retry_count}\n"
                        f"Exit Price: ₹{exit_price:.2f}\n\n"
                        f"Position closed successfully."
                    )
            
            # ═══════════════════════════════════════════════════════════
            # Calculate final P&L
            # v4.13.0: Direction-aware P&L calculation
            # ═══════════════════════════════════════════════════════════
            entry_price = position['entry_price']
            quantity = position['quantity']
            direction = self._get_position_direction(position)
            
            if direction == 'SHORT':
                pnl = (entry_price - exit_price) * quantity
                pnl_pct = ((entry_price - exit_price) / entry_price) * 100
            else:  # LONG
                pnl = (exit_price - entry_price) * quantity
                pnl_pct = ((exit_price - entry_price) / entry_price) * 100
            
            # ═══════════════════════════════════════════════════════════
            # Update position status
            # ═══════════════════════════════════════════════════════════
            self._update_position(symbol, position,
                                  status='CLOSED',
                                  exit_price=exit_price,
                                  exit_time=datetime.now().isoformat(),
                                  pnl=pnl,
                                  pnl_pct=pnl_pct,
                                  exit_reason=reason)

            self._save_positions()
            
            # ═══════════════════════════════════════════════════════════
            # Release capital via Capital Manager
            # ═══════════════════════════════════════════════════════════
            if self.capital_manager:
                try:
                    release_success = self.capital_manager.release(
                        symbol=symbol,
                        amount=position.get('entry_value', 0),
                        pnl=pnl
                    )
                    if release_success:
                        logger.info(f"💰 Capital Manager: Released ₹{position.get('entry_value', 0):,.0f} "
                                   f"for {symbol} (P&L: ₹{pnl:+,.0f})")
                    else:
                        logger.warning(f"⚠️ Capital Manager: Release returned False for {symbol}")
                except Exception as e:
                    logger.error(f"❌ Capital Manager release failed: {e}")
            
            # ═══════════════════════════════════════════════════════════
            # Telegram notification
            # ═══════════════════════════════════════════════════════════
            result_emoji = "✅" if pnl > 0 else "❌"
            
            if self.telegram:
                self.telegram.send_message(
                    f"{result_emoji} POSITION CLOSED\n\n"
                    f"Stock: {symbol}\n"
                    f"Entry: ₹{entry_price:.2f}\n"
                    f"Exit: ₹{exit_price:.2f}\n"
                    f"P&L: ₹{pnl:+.0f} ({pnl_pct:+.2f}%)\n"
                    f"Reason: {reason}"
                )
            
            logger.info(f"✅ {symbol} closed: P&L ₹{pnl:+.0f} ({pnl_pct:+.2f}%)")
            
            # ═══════════════════════════════════════════════════════════
            # Remove position from tracking
            # ═══════════════════════════════════════════════════════════
            self._delete_position(symbol, reason, exit_price)
            
            return exit_price
            
        except Exception as e:
            logger.error(f"Error closing {symbol}: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return None
    
    def _place_sell_order_internal(self, symbol: str, quantity: int, product: str) -> Optional[str]:
        """
        DEPRECATED: Use _place_exit_order_internal() instead for direction-aware exits.
        
        v4.9.0: Place SELL order via Kite API.
        v4.13.0: DEPRECATED - Only works for LONG positions.
        
        Args:
            symbol: Stock symbol
            quantity: Number of shares
            product: Product type ('MIS' or 'CNC')
            
        Returns:
            Order ID if successful, None otherwise
        """
        logger.warning(f"DEPRECATED: _place_sell_order_internal called for {symbol}. Use _place_exit_order_internal instead.")
        try:
            # v5.4.0 SEBI FIX: Raw API call to inject market_protection=-1
            import requests
            url = "https://api.kite.trade/orders/regular"
            headers = {
                "X-Kite-Version": "3",
                "Authorization": f"token {self.kite.api_key}:{self.kite.access_token}"
            }
            payload = {
                "tradingsymbol": symbol,
                "exchange": "NSE",
                "transaction_type": "SELL",
                "quantity": str(quantity),
                "product": "CNC" if product == 'CNC' else "MIS",
                "order_type": "MARKET",
                "validity": "DAY",
                "market_protection": "-1"
            }
            response = requests.post(url, headers=headers, data=payload, timeout=10)
            response_json = response.json()
            if response.status_code == 200 and response_json.get('status') == 'success':
                order_id = response_json.get('data', {}).get('order_id')
            else:
                logger.error(f"   SELL raw API failed: {response_json}")
                order_id = None
            return order_id
        except Exception as e:
            logger.error(f"SELL order placement error: {e}")
            return None
    
    def _place_exit_order_internal(self, symbol: str, quantity: int, 
                                    transaction_type: str, product: str) -> Optional[str]:
        """
        v4.13.0: Place exit order via Kite API (direction-aware).
        
        For LONG positions: transaction_type = 'SELL'
        For SHORT positions: transaction_type = 'BUY'
        
        Args:
            symbol: Stock symbol
            quantity: Number of shares
            transaction_type: 'BUY' or 'SELL' (based on position direction)
            product: Product type ('MIS' or 'CNC')
            
        Returns:
            Order ID if successful, None otherwise
        """
        try:
            kite_transaction = (self.kite.TRANSACTION_TYPE_BUY 
                               if transaction_type == 'BUY' 
                               else self.kite.TRANSACTION_TYPE_SELL)
            
            # v5.4.0 SEBI FIX: Raw API call to inject market_protection=-1
            # SDK v5.0.1 does not support this parameter; SEBI mandates non-zero.
            import requests
            url = "https://api.kite.trade/orders/regular"
            headers = {
                "X-Kite-Version": "3",
                "Authorization": f"token {self.kite.api_key}:{self.kite.access_token}"
            }
            payload = {
                "tradingsymbol": symbol,
                "exchange": "NSE",
                "transaction_type": kite_transaction,
                "quantity": str(quantity),
                "product": "CNC" if product == 'CNC' else "MIS",
                "order_type": "MARKET",
                "validity": "DAY",
                "market_protection": "-1"
            }
            response = requests.post(url, headers=headers, data=payload, timeout=10)
            response_json = response.json()
            if response.status_code == 200 and response_json.get('status') == 'success':
                order_id = response_json.get('data', {}).get('order_id')
                logger.info(f"   {transaction_type} order placed (raw API): {order_id}")
                return order_id
            else:
                logger.error(f"   {transaction_type} raw API failed: {response_json}")
                return None
        except Exception as e:
            logger.error(f"{transaction_type} order placement error: {e}")
            return None

    def _place_market_order_internal(self, symbol: str, quantity: int,
                                      transaction_type: str, product: str) -> Optional[str]:
        """
        v4.9.0: Place MARKET order as fallback for failed orders.
        
        Args:
            symbol: Stock symbol
            quantity: Number of shares
            transaction_type: 'BUY' or 'SELL'
            product: Product type ('MIS' or 'CNC')
            
        Returns:
            Order ID if successful, None otherwise
        """
        try:
            # v5.4.0 SEBI FIX: Raw API call to inject market_protection=-1
            import requests
            url = "https://api.kite.trade/orders/regular"
            headers = {
                "X-Kite-Version": "3",
                "Authorization": f"token {self.kite.api_key}:{self.kite.access_token}"
            }
            payload = {
                "tradingsymbol": symbol,
                "exchange": "NSE",
                "transaction_type": transaction_type,
                "quantity": str(quantity),
                "product": "CNC" if product == 'CNC' else "MIS",
                "order_type": "MARKET",
                "validity": "DAY",
                "market_protection": "-1"
            }
            response = requests.post(url, headers=headers, data=payload, timeout=10)
            response_json = response.json()
            if response.status_code == 200 and response_json.get('status') == 'success':
                order_id = response_json.get('data', {}).get('order_id')
            else:
                logger.error(f"   MARKET fallback raw API failed: {response_json}")
                order_id = None
            logger.info(f"   MARKET order placed: {order_id}")
            return order_id
        except Exception as e:
            logger.error(f"   MARKET order failed: {e}")
            return None
    
    def _wait_for_order_fill(self, order_id: str, timeout: int = 60) -> Optional[float]:
        """
        v4.9.0: Wait for order to fill.
        
        Args:
            order_id: Order ID
            timeout: Timeout in seconds
            
        Returns:
            Fill price if successful, None otherwise
        """
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            try:
                orders = self.kite.orders()
                
                for order in orders:
                    if order['order_id'] == order_id:
                        if order['status'] == 'COMPLETE':
                            return order['average_price']
                        elif order['status'] in ['REJECTED', 'CANCELLED']:
                            logger.error(f"Order {order['status']}: {order.get('status_message', 'Unknown')}")
                            return None
                
                time.sleep(2)
                
            except Exception as e:
                logger.error(f"Error checking order status: {e}")
                time.sleep(2)
        
        logger.error(f"Order fill timeout after {timeout}s")
        return None
    
    def _execute_partial_exit(self, symbol: str, percent: int, reason: str) -> bool:
        """
        Execute partial exit.
        
        v4.9.0: Now uses internal sell methods instead of Phase 3.
        
        Args:
            symbol: Stock symbol
            percent: Percentage to exit (25 or 50)
            reason: Exit reason
        """
        position = self.positions.get(symbol)
        if not position:
            return False
        
        total_qty = position.get('quantity', 0)
        exit_qty = int(total_qty * percent / 100)
        
        if exit_qty < 1:
            logger.info(f"Partial exit qty too small, executing full exit")
            return self._execute_exit(symbol, reason)
        
        remaining_qty = total_qty - exit_qty
        
        direction = self._get_position_direction(position)
        exit_transaction = self._get_exit_transaction_type(direction)
        
        logger.info(f"📊 Partial Exit: {symbol} - {exit_qty} of {total_qty} shares ({direction} → {exit_transaction})")
        
        try:
            # Cancel existing GTT orders
            self._cancel_all_gtt_for_symbol(symbol)
            
            # v4.13.0: Direction-aware partial exit
            order_id = self._place_exit_order_internal(
                symbol=symbol,
                quantity=exit_qty,
                transaction_type=exit_transaction,
                product=position.get('product', 'CNC')
            )
            
            if order_id:
                # Wait for fill
                exit_price = self._wait_for_order_fill(order_id)
                success = exit_price is not None
                
                if success:
                    # v4.13.0: Direction-aware partial P&L calculation
                    entry_price = position.get('entry_price', 0)
                    direction = self._get_position_direction(position)
                    if direction == 'SHORT':
                        partial_pnl = (entry_price - exit_price) * exit_qty
                    else:  # LONG
                        partial_pnl = (exit_price - entry_price) * exit_qty
                    
                    # Release partial capital
                    if self.capital_manager:
                        partial_value = entry_price * exit_qty
                        self.capital_manager.release(
                            symbol=f"{symbol}_PARTIAL",
                            amount=partial_value,
                            pnl=partial_pnl
                        )
                    
                    logger.info(f"✅ Partial exit: {exit_qty} shares @ ₹{exit_price:.2f} "
                               f"(P&L: ₹{partial_pnl:+,.0f})")

                    # v5.4.0: Structured partial exit notification
                    if self.telegram and hasattr(self.telegram, 'notify_partial_exit'):
                        try:
                            self.telegram.notify_partial_exit(
                                symbol=symbol,
                                percent=percent,
                                exit_qty=exit_qty,
                                exit_price=exit_price,
                                pnl=partial_pnl,
                                remaining_qty=remaining_qty,
                                reason=reason
                            )
                        except Exception:
                            pass
            else:
                success = False

            if success:
                # Update position
                position['quantity'] = remaining_qty
                
                # Place new GTT for remaining
                if self.ENABLE_GTT and remaining_qty > 0:
                    # Tighter stop after partial profit
                    current_price = position.get('current_price', position.get('entry_price', 0))
                    new_stop = current_price * 0.985  # Tighter 1.5% stop
                    position['stop_price'] = new_stop
                    
                    gtt_ids = self._place_gtt_orders(symbol, position)
                    if gtt_ids:
                        position['gtt_stop_id'] = gtt_ids.get('stop_id')
                        position['gtt_target_id'] = gtt_ids.get('target_id')
                        position['gtt_active'] = True
                
                self._save_positions()
            
            return success
            
        except Exception as e:
            logger.error(f"Partial exit failed for {symbol}: {e}")
            return False
    
    # ═══════════════════════════════════════════════════════════════════════════
    # v4.9.0: _direct_sell and _direct_partial_sell REMOVED
    # Replaced by: _place_sell_order(), _place_sell_order_internal(), 
    #              _place_market_order_internal(), _wait_for_order_fill()
    # ═══════════════════════════════════════════════════════════════════════════

    # ═══════════════════════════════════════════════════════════════════════════
    # MAIN MONITORING CYCLE
    # ═══════════════════════════════════════════════════════════════════════════
    
    # ═══════════════════════════════════════════════════════════════════════════
    # v4.14.0: PRIORITY TIER MONITORING SYSTEM
    # ═══════════════════════════════════════════════════════════════════════════

    def has_tier1_positions(self) -> bool:
        """
        v4.14.0: Check if any Tier 1 (MIS/Phase 5) positions exist.
        Used by orchestrator to determine sleep interval (10s vs 60s).
        """
        for symbol, position in self.positions.items():
            if position.get('monitoring_tier') == 'TIER_1':
                return True
            # Fallback: any MIS position from Phase 5 or Phase 5A is Tier 1
            if position.get('product') == 'MIS' and position.get('source') in ('PHASE5_GAP', 'PHASE5A_PVAT'):
                return True
        return False

    def _get_tier1_positions(self) -> dict:
        """v4.14.0: Get all Tier 1 positions (MIS/Phase 5/5A scalps)."""
        tier1 = {}
        for symbol, position in self.positions.items():
            if position.get('monitoring_tier') == 'TIER_1':
                tier1[symbol] = position
            elif position.get('product') == 'MIS' and position.get('source') in ('PHASE5_GAP', 'PHASE5A_PVAT'):
                tier1[symbol] = position
        return tier1

    def _get_tier2_positions(self) -> dict:
        """v4.14.0: Get all Tier 2 positions (CNC/swing - everything not Tier 1, not Tier 3)."""
        tier1_symbols = set(self._get_tier1_positions().keys())
        tier3_symbols = set(self._get_tier3_positions().keys())
        return {s: p for s, p in self.positions.items()
                if s not in tier1_symbols and s not in tier3_symbols}

    # ═══════════════════════════════════════════════════════════════════════
    # v8.0.0: TIER 3 — PHASE 8 WEEKLY MOMENTUM POSITIONS
    # ═══════════════════════════════════════════════════════════════════════
    #
    # Tier 3 tracks CNC positions from Phase 8 Momentum Strategy.
    #
    # Differences from Tier 1/2:
    #   - Multi-day hold (Wed→Tue+), not intraday
    #   - TCAS trail: 0.5% activation, 1.5% trail (wider than Tier 1)
    #   - Tuesday-only scheduled exit checks (5 times)
    #   - No ILS landing, no intraday target locks
    #   - Max 2 concurrent positions
    #   - No GTT — TCAS is the only stop mechanism
    # ═══════════════════════════════════════════════════════════════════════

    def _get_tier3_positions(self) -> dict:
        """v8.0.0: Get all Tier 3 positions (Phase 8 Momentum)."""
        tier3 = {}
        for symbol, position in self.positions.items():
            if position.get('monitoring_tier') == 'TIER_3':
                tier3[symbol] = position
            elif position.get('source') == 'PH8_MOMENTUM':
                tier3[symbol] = position
        return tier3

    def get_tier3_position_count(self) -> int:
        """Used by Phase 8 scanner to check max concurrent before new pick."""
        return len(self._get_tier3_positions())

    def get_tier3_held_symbols(self) -> list:
        """Used by Phase 8 scanner to avoid duplicate picks."""
        return list(self._get_tier3_positions().keys())

    def _run_tier3_momentum_check(self, symbol: str, position: dict,
                                  current_price: float) -> bool:
        """
        v8.0.0: TIER 3 MOMENTUM CHECK — TCAS trailing stop.

        Called during each monitoring cycle for Tier 3 positions.
        Implements the Phase 8 TCAS logic:
          - Activation: 0.5% profit above entry
          - Trail: 1.5% below peak (only moves up, never down)
          - Exit: price <= trail price

        Args:
            symbol: Stock symbol
            position: Position dict
            current_price: Latest price from quote

        Returns:
            True if position was exited, False if still active.
        """
        entry_price = position.get('entry_price', 0)
        if entry_price <= 0 or current_price <= 0:
            return False

        # ── Day-of-week gate: DORMANT on Wed/Thu/Fri ──────────────
        # TCAS only active Monday 10:00 AM+ and Tuesday (all day)
        now = datetime.now()
        weekday = now.weekday()  # 0=Mon, 1=Tue, 2=Wed, ...
        tcas_start_day = getattr(self.config, 'PH8_TCAS_START_DAY', 0)  # Monday
        tcas_start_time = getattr(self.config, 'PH8_TCAS_START_TIME', dt_time(10, 0))

        if weekday == tcas_start_day:
            # Monday — only active after start time
            if now.time() < tcas_start_time:
                return False  # Monday before 10:00 AM — dormant
        elif weekday == 1:
            pass  # Tuesday — always active
        else:
            return False  # Wed/Thu/Fri/Sat/Sun — DORMANT

        activation_pct = getattr(self.config, 'PH8_TCAS_ACTIVATION_PCT', 0.005)
        trail_pct = getattr(self.config, 'PH8_TCAS_TRAIL_PCT', 0.015)

        # Update peak price
        peak = position.get('peak_price', entry_price)
        if current_price > peak:
            position['peak_price'] = current_price
            peak = current_price

        # Calculate current profit
        profit_pct = (current_price - entry_price) / entry_price

        # Check TCAS activation
        tcas_active = position.get('tcas_active', False)
        if not tcas_active and profit_pct >= activation_pct:
            position['tcas_active'] = True
            position['tcas_trail_price'] = peak * (1 - trail_pct)
            tcas_active = True
            logger.info(f"   PH8 TCAS ACTIVATED: {symbol} at {profit_pct:+.2%} "
                        f"(trail: {position['tcas_trail_price']:.2f})")
            try:
                if self.telegram:
                    self.telegram.send_message(
                        f"PH8 TCAS ACTIVATED\n"
                        f"{symbol} at {profit_pct:+.2%} ({current_price:.2f})\n"
                        f"Trailing stop set: {position['tcas_trail_price']:.2f} "
                        f"(1.5% below peak)"
                    )
            except Exception:
                pass

        # Update trail (only moves UP, never down)
        if tcas_active:
            new_trail = peak * (1 - trail_pct)
            old_trail = position.get('tcas_trail_price', 0)
            if new_trail > old_trail:
                position['tcas_trail_price'] = new_trail

            # Check trail hit
            trail_price = position.get('tcas_trail_price', 0)
            if current_price <= trail_price:
                logger.info(f"   PH8 TCAS EXIT TRIGGERED: {symbol} "
                            f"({current_price:.2f} <= trail {trail_price:.2f})")
                self._execute_tier3_exit(symbol, position, current_price, "TCAS_TRAIL")
                return True

        return False

    def check_tier3_tuesday_exit(self, check_time=None):
        """
        v8.0.0: Tuesday profit check for all Tier 3 positions.

        Called by orchestrator at each of the 5 Tuesday check times:
          9:15, 10:00, 12:00, 14:00, 15:15

        For each Tier 3 position:
          - If profit >= PH8_PROFIT_EXIT_THRESHOLD (0.5%) → EXIT
          - If last check (15:15) and still holding → send HOLD Telegram

        Args:
            check_time: The scheduled check time (for logging)
        """
        tier3 = self._get_tier3_positions()
        if not tier3:
            return

        check_str = check_time.strftime('%H:%M') if check_time else 'unknown'
        logger.info(f"   PH8 Tuesday exit check ({check_str}): {len(tier3)} Tier 3 positions")

        threshold = getattr(self.config, 'PH8_PROFIT_EXIT_THRESHOLD', 0.005)
        exit_times = getattr(self.config, 'PH8_EXIT_CHECK_TIMES', [])
        is_last_check = False
        if exit_times and check_time:
            is_last_check = (check_time >= exit_times[-1])

        # Batch fetch quotes
        try:
            symbols = list(tier3.keys())
            quotes = self.kite.quote([f"NSE:{s}" for s in symbols])
        except Exception as e:
            logger.error(f"   Quote fetch failed for Tuesday check: {e}")
            return

        for symbol, position in tier3.items():
            try:
                quote_key = f"NSE:{symbol}"
                quote_data = quotes.get(quote_key, {})
                current_price = quote_data.get('last_price', 0)

                if current_price <= 0:
                    continue

                entry_price = position.get('entry_price', 0)
                if entry_price <= 0:
                    continue

                profit_pct = (current_price - entry_price) / entry_price
                pnl_rupees = (current_price - entry_price) * position.get('quantity', 0)

                # Also update TCAS peak/trail while we have the price
                peak = position.get('peak_price', entry_price)
                if current_price > peak:
                    position['peak_price'] = current_price

                if profit_pct >= threshold:
                    # EXIT — profit threshold met (rule a)
                    logger.info(f"   PH8 TUESDAY EXIT: {symbol} at {profit_pct:+.2%} "
                                f"(>= {threshold:.1%})")
                    self._execute_tier3_exit(symbol, position, current_price,
                                            "TUESDAY_PROFIT")

                elif profit_pct > 0:
                    # Rule c: Kalman predicts EOD lower than current AND profit > 0
                    kalman_exit = False
                    try:
                        kf = position.get('_daily_kalman')
                        if kf and getattr(self.config, 'PH8_KALMAN_ENABLED', True):
                            eod_pred = kf.predict_price_at(0)  # today = 0 days ahead
                            if eod_pred < current_price:
                                logger.info(f"   PH8 KALMAN EOD EXIT: {symbol} — "
                                            f"Kalman EOD={eod_pred:.2f} < current={current_price:.2f}")
                                self._execute_tier3_exit(symbol, position, current_price,
                                                        "KALMAN_EOD_EXIT")
                                kalman_exit = True
                    except Exception as e:
                        logger.debug(f"   Kalman EOD check error for {symbol}: {e}")

                    if kalman_exit:
                        continue  # Already exited

                    # HOLD — profit > 0 but below threshold and Kalman is ok
                    logger.info(f"   PH8 Tuesday {check_str}: {symbol} at "
                                f"{profit_pct:+.2%} — small profit, HOLD")

                else:
                    # HOLD
                    hold_days = 0
                    if position.get('entry_date'):
                        try:
                            from datetime import date as date_cls
                            entry_dt = date_cls.fromisoformat(position['entry_date'])
                            hold_days = (date_cls.today() - entry_dt).days
                        except Exception:
                            pass

                    logger.info(f"   PH8 Tuesday {check_str}: {symbol} at "
                                f"{profit_pct:+.2%} — HOLD (threshold: {threshold:.1%})")

                    # Last check of the day (15:15) — enhanced HOLD notification
                    if is_last_check:
                        try:
                            kalman_info = ""
                            kf = position.get('_daily_kalman')
                            if kf:
                                try:
                                    state = kf.get_state(5)  # ~5 days to next Tuesday
                                    kalman_info = (
                                        f"\nKalman: vel={state.velocity:+.1f}/day | "
                                        f"Next Tue pred: {state.tuesday_prediction:.2f} "
                                        f"({state.predicted_pnl_pct:+.2%})"
                                    )
                                except Exception:
                                    pass

                            if self.telegram:
                                self.telegram.send_message(
                                    f"PH8 HOLD DECISION ({check_str} check)\n"
                                    f"{symbol} at {current_price:.2f} | "
                                    f"Entry: {entry_price:.2f}\n"
                                    f"P&L: {pnl_rupees:+,.0f} ({profit_pct:+.2%})\n"
                                    f"Carrying to next week (hold: {hold_days} days)"
                                    f"{kalman_info}\n"
                                    f"Next review: Thursday 9:00 AM"
                                )
                        except Exception:
                            pass

            except Exception as e:
                logger.error(f"   PH8 Tuesday check error for {symbol}: {e}")

    def _execute_tier3_exit(self, symbol: str, position: dict,
                            exit_price: float, reason: str):
        """
        v8.0.0: Execute exit for a Tier 3 (Phase 8 Momentum) position.

        Steps:
          1. Place CNC SELL MARKET order
          2. Update position status
          3. Notify Phase 6 to close shadow (if active)
          4. Release capital
          5. Send Telegram
          6. Log to exit history
        """
        logger.info(f"   PH8 EXIT: {symbol} | Reason: {reason} | Price: {exit_price:.2f}")

        quantity = position.get('quantity', 0)
        entry_price = position.get('entry_price', 0)

        # 1. Place CNC SELL MARKET order
        sell_order_id = None
        try:
            # v5.4.0 SEBI FIX: Raw API call to inject market_protection=-1
            import requests
            url = "https://api.kite.trade/orders/regular"
            headers = {
                "X-Kite-Version": "3",
                "Authorization": f"token {self.kite.api_key}:{self.kite.access_token}"
            }
            payload = {
                "tradingsymbol": symbol,
                "exchange": "NSE",
                "transaction_type": "SELL",
                "quantity": str(quantity),
                "product": "CNC",
                "order_type": "MARKET",
                "validity": "DAY",
                "market_protection": "-1"
            }
            response = requests.post(url, headers=headers, data=payload, timeout=10)
            response_json = response.json()
            if response.status_code == 200 and response_json.get('status') == 'success':
                sell_order_id = response_json.get('data', {}).get('order_id')
            else:
                logger.error(f"   PH8 CNC SELL raw API failed: {response_json}")
            logger.info(f"   CNC SELL order placed: {sell_order_id}")
        except Exception as e:
            logger.error(f"   SELL order failed for {symbol}: {e}")
            try:
                if self.telegram:
                    self.telegram.send_message(
                        f"PH8 EXIT SELL FAILED\n"
                        f"{symbol}: {e}\n"
                        f"MANUAL SELL REQUIRED: {quantity} shares"
                    )
            except Exception:
                pass
            return

        # 2. Update position
        pnl = (exit_price - entry_price) * quantity
        pnl_pct = (exit_price - entry_price) / entry_price if entry_price > 0 else 0

        hold_days = 0
        if position.get('entry_date'):
            try:
                from datetime import date as date_cls
                entry_dt = date_cls.fromisoformat(position['entry_date'])
                hold_days = (date_cls.today() - entry_dt).days
            except Exception:
                pass

        self._update_position(symbol, position,
                              status='EXITED',
                              exit_price=exit_price,
                              exit_date=date.today().isoformat(),
                              exit_time=datetime.now().strftime('%H:%M:%S'),
                              exit_reason=reason,
                              pnl=pnl,
                              pnl_pct=pnl_pct,
                              hold_days=hold_days,
                              sell_order_id=str(sell_order_id))

        # 3. Notify Phase 6 to close shadow (if active)
        if position.get('shadow_active', False):
            try:
                if hasattr(self, 'phase6') and self.phase6:
                    if hasattr(self.phase6, 'on_momentum_cash_exit'):
                        self.phase6.on_momentum_cash_exit(symbol, exit_price, reason)
                        logger.info(f"   Ph6 notified: momentum shadow close for {symbol}")
            except Exception as e:
                logger.error(f"   Ph6 shadow close notification failed: {e}")

        # 4. Release capital
        if self.capital_manager:
            try:
                self.capital_manager.release(symbol)
                logger.info(f"   Capital released for {symbol}")
            except Exception as e:
                logger.error(f"   Capital release error: {e}")

        # 5. Remove from active positions
        if symbol in self.positions:
            del self.positions[symbol]
        self._save_positions()

        # 6. Log to exit history
        try:
            import json as json_mod
            history_file = 'data/ph8_exit_history.json'
            import os
            os.makedirs(os.path.dirname(history_file), exist_ok=True)

            history = []
            if os.path.exists(history_file):
                with open(history_file, 'r') as f:
                    history = json_mod.load(f)

            history.append({
                'symbol': symbol,
                'entry_date': position.get('entry_date', ''),
                'exit_date': position.get('exit_date', ''),
                'entry_price': entry_price,
                'exit_price': exit_price,
                'quantity': quantity,
                'pnl': pnl,
                'pnl_pct': round(pnl_pct * 100, 2),
                'hold_days': hold_days,
                'exit_reason': reason,
                'weekly_return_at_entry': position.get('weekly_return_pct', 0),
                'exit_time': datetime.now().isoformat(),
            })

            with open(history_file, 'w') as f:
                json_mod.dump(history, f, indent=2, default=str)
        except Exception as e:
            logger.error(f"   Exit history log error: {e}")

        # 7. Telegram
        exit_label = {
            'TUESDAY_PROFIT': 'PH8 TUESDAY EXIT',
            'TCAS_TRAIL': 'PH8 TCAS EXIT',
        }.get(reason, f'PH8 EXIT ({reason})')

        try:
            if self.telegram:
                self.telegram.send_message(
                    f"{exit_label}\n"
                    f"{symbol} @ {exit_price:.2f} | Entry: {entry_price:.2f}\n"
                    f"P&L: {pnl:+,.0f} ({pnl_pct:+.2%})\n"
                    f"Hold: {hold_days} days | Reason: {reason}"
                )
        except Exception:
            pass

    # ═══════════════════════════════════════════════════════════════════════
    # v8.1.0: TIER 3 INTELLIGENCE — MORNING REVIEW & KALMAN DAILY
    # ═══════════════════════════════════════════════════════════════════════
    #
    # Daily morning intelligence for Tier 3 (Phase 8 Momentum) positions.
    # Runs Thu/Fri/Mon/Tue at ~9:00 AM, BEFORE Phase 1 scans.
    #
    # Components:
    #   1. _build_tier3_data_package() — collects all available data
    #   2. _init_tier3_daily_kalman() — Kalman on daily candles
    #   3. _update_tier3_daily_kalman() — feed new daily close
    #   4. _chatgpt_tier3_review() — send data package to ChatGPT
    #   5. run_tier3_morning_intelligence() — orchestrator entry point
    #
    # Isolation: all try/except. Failure = HOLD, never crash.
    # ═══════════════════════════════════════════════════════════════════════

    def run_tier3_morning_intelligence(self):
        """
        Main entry point — called by orchestrator at 9:00 AM on review days.

        For each Tier 3 position:
          1. Update daily Kalman with yesterday's close
          2. Build full data package
          3. Send to ChatGPT for review
          4. If EXIT with confidence > 80 → execute early exit
          5. Send Telegram summary
          6. Log to mission DB
        """
        if not getattr(self.config, 'PH8_MORNING_REVIEW_ENABLED', False):
            return

        tier3 = self._get_tier3_positions()
        if not tier3:
            logger.info("   PH8 Morning Intelligence: no Tier 3 positions — skipping")
            return

        logger.info(f"   PH8 MORNING INTELLIGENCE: reviewing {len(tier3)} position(s)")

        for symbol, position in tier3.items():
            try:
                self._run_single_tier3_morning_review(symbol, position)
            except Exception as e:
                logger.error(f"   PH8 morning review error for {symbol}: "
                             f"{type(e).__name__}: {e}", exc_info=True)
                # Fail-safe: HOLD
                try:
                    if self.telegram:
                        self.telegram.send_message(
                            f"PH8 Morning review failed for {symbol}: {e}\n"
                            f"Fail-safe: HOLD — position unchanged"
                        )
                except Exception:
                    pass

    def _run_single_tier3_morning_review(self, symbol: str, position: dict):
        """Run morning intelligence for a single Tier 3 position."""
        from datetime import date as date_cls

        entry_price = position.get('entry_price', 0)
        if entry_price <= 0:
            return

        # ── 1. Get current quote ────────────────────────────────────
        current_price = 0
        try:
            quotes = self.kite.quote([f"NSE:{symbol}"])
            current_price = quotes.get(f"NSE:{symbol}", {}).get('last_price', 0)
        except Exception as e:
            logger.warning(f"   Quote failed for {symbol}: {e}")

        if current_price <= 0:
            current_price = position.get('peak_price', entry_price)

        # ── 2. Update daily Kalman ──────────────────────────────────
        kalman_state_dict = {}
        try:
            kalman_state_dict = self._update_tier3_daily_kalman(symbol, position)
        except Exception as e:
            logger.warning(f"   Kalman update failed for {symbol}: {e}")

        # ── 3. Build data package ───────────────────────────────────
        data_package = self._build_tier3_data_package(symbol, position, current_price, kalman_state_dict)

        # ── 4. ChatGPT review ───────────────────────────────────────
        review = self._chatgpt_tier3_review(data_package)

        recommendation = review.get('recommendation', 'HOLD')
        confidence = review.get('confidence', 0)
        reasoning = review.get('reasoning', '')
        key_factors = review.get('key_factors', [])
        risk_level = review.get('risk_level', 'MEDIUM')

        pnl_pct = (current_price - entry_price) / entry_price
        pnl_rupees = (current_price - entry_price) * position.get('quantity', 0)
        hold_days = 0
        if position.get('entry_date'):
            try:
                entry_dt = date_cls.fromisoformat(position['entry_date'])
                hold_days = (date_cls.today() - entry_dt).days
            except Exception:
                pass

        days_to_tuesday = self._days_to_next_tuesday()

        # ── 5. Log to mission DB ────────────────────────────────────
        action_taken = "NONE"
        try:
            if hasattr(self, 'mission_db') and self.mission_db:
                self.mission_db.log_ph8_morning_review(
                    symbol=symbol,
                    recommendation=recommendation,
                    confidence=confidence,
                    reasoning=reasoning,
                    risk_level=risk_level,
                    key_factors=key_factors,
                    kalman_state=kalman_state_dict,
                    data_package_summary={
                        'pnl_pct': round(pnl_pct, 4),
                        'hold_days': hold_days,
                        'days_to_tuesday': days_to_tuesday,
                    },
                )
        except Exception as e:
            logger.warning(f"   Mission DB log failed: {e}")

        # ── 6. Act on recommendation ────────────────────────────────
        exit_enabled = getattr(self.config, 'PH8_CHATGPT_EARLY_EXIT', True)
        min_conf = getattr(self.config, 'PH8_CHATGPT_EXIT_MIN_CONFIDENCE', 80)

        if recommendation == 'EXIT' and confidence >= min_conf and exit_enabled:
            action_taken = "EARLY_EXIT"
            logger.info(f"   PH8 ChatGPT EXIT: {symbol} (confidence={confidence})")
            self._execute_tier3_exit(symbol, position, current_price, "CHATGPT_EARLY_EXIT")
            try:
                if self.telegram:
                    self.telegram.notify_ph8_chatgpt_early_exit(
                        symbol=symbol,
                        exit_price=current_price,
                        entry_price=entry_price,
                        pnl_pct=pnl_pct,
                        pnl_rupees=pnl_rupees,
                        confidence=confidence,
                        reasoning=reasoning,
                        hold_days=hold_days,
                    )
            except Exception:
                pass
            return

        if recommendation == 'EXIT' and confidence < min_conf:
            action_taken = "EXIT_LOW_CONF_HOLD"
            logger.info(f"   PH8 EXIT suggested but confidence only {confidence}/{min_conf} — HOLDING")

        # ── 7. Telegram morning summary ─────────────────────────────
        try:
            if self.telegram:
                self.telegram.notify_ph8_morning_review(
                    symbol=symbol,
                    hold_days=hold_days,
                    pnl_pct=pnl_pct,
                    pnl_rupees=pnl_rupees,
                    recommendation=recommendation,
                    confidence=confidence,
                    reasoning=reasoning,
                    key_factors=key_factors,
                    risk_level=risk_level,
                    kalman_velocity=kalman_state_dict.get('velocity', 0),
                    kalman_tuesday_pred=kalman_state_dict.get('tuesday_prediction', 0),
                    kalman_predicted_pnl=kalman_state_dict.get('predicted_pnl_pct', 0),
                )
        except Exception:
            pass

    # ── Daily Kalman Management ───────────────────────────────────────

    def _init_tier3_daily_kalman(self, symbol: str, position: dict):
        """Initialize daily Kalman for a new Tier 3 position (called once at entry)."""
        try:
            from kalman_filter import DailyKalmanFilter

            warmup_days = getattr(self.config, 'PH8_KALMAN_WARMUP_DAYS', 30)
            token = self._get_instrument_token_for_symbol(symbol)
            if not token:
                logger.warning(f"   No instrument token for {symbol} — Kalman skipped")
                return

            from datetime import date as date_cls, timedelta as td
            from_date = date_cls.today() - td(days=warmup_days + 10)
            to_date = date_cls.today() - td(days=1)

            candles = self.kite.historical_data(token, from_date, to_date, "day")
            if not candles or len(candles) < 10:
                logger.warning(f"   Insufficient candles for {symbol} Kalman warmup: {len(candles) if candles else 0}")
                return

            daily_closes = [c['close'] for c in candles[-warmup_days:]]

            kf = DailyKalmanFilter(config=self.config)
            kf.set_symbol(symbol)
            kf.set_entry_price(position.get('entry_price', 0))
            kf.initialize_with_history(daily_closes)

            # Store on position
            position['_daily_kalman'] = kf
            logger.info(f"   PH8 Daily Kalman initialized for {symbol} ({len(daily_closes)} candles)")

        except Exception as e:
            logger.error(f"   Daily Kalman init error for {symbol}: {e}")

    def _update_tier3_daily_kalman(self, symbol: str, position: dict) -> dict:
        """Feed yesterday's close into the daily Kalman. Returns state dict."""
        kf = position.get('_daily_kalman')

        if kf is None:
            # First time — initialize
            if getattr(self.config, 'PH8_KALMAN_ENABLED', True):
                self._init_tier3_daily_kalman(symbol, position)
                kf = position.get('_daily_kalman')

        if kf is None:
            return {}

        # Get yesterday's close
        try:
            from datetime import date as date_cls, timedelta as td
            token = self._get_instrument_token_for_symbol(symbol)
            if not token:
                return kf.get_state(self._days_to_next_tuesday()).to_dict()

            yesterday = date_cls.today() - td(days=1)
            from_date = yesterday - td(days=5)  # buffer for weekends
            candles = self.kite.historical_data(token, from_date, yesterday, "day")

            if candles:
                last_close = candles[-1]['close']
                days_to_tue = self._days_to_next_tuesday()
                state = kf.process_daily_close(last_close)

                state_dict = state.to_dict()
                state_dict['days_to_tuesday'] = days_to_tue

                # Check for momentum reversal
                if state.velocity < 0 and position.get('_kalman_prev_velocity', 0) >= 0:
                    logger.info(f"   PH8 KALMAN REVERSAL: {symbol} velocity turned negative "
                                f"({state.velocity:.2f}/day)")
                    try:
                        if self.telegram:
                            self.telegram.notify_ph8_kalman_reversal(
                                symbol=symbol,
                                velocity=state.velocity,
                                acceleration=state.acceleration,
                                current_price=last_close,
                                entry_price=position.get('entry_price', 0),
                                tuesday_prediction=state.tuesday_prediction,
                            )
                    except Exception:
                        pass

                position['_kalman_prev_velocity'] = state.velocity
                return state_dict

        except Exception as e:
            logger.warning(f"   Kalman daily update error for {symbol}: {e}")

        return kf.get_state(self._days_to_next_tuesday()).to_dict()

    def _get_instrument_token_for_symbol(self, symbol: str) -> Optional[int]:
        """Get instrument token for a symbol (use phase8 scanner's map if available)."""
        # Try phase8 scanner's cached map first
        if hasattr(self, 'phase8') and self.phase8:
            if hasattr(self.phase8, '_instrument_map'):
                token = self.phase8._instrument_map.get(symbol)
                if token:
                    return int(token)
        # Fallback: direct lookup
        try:
            instruments = self.kite.instruments("NSE")
            for inst in instruments:
                if inst['tradingsymbol'] == symbol and inst.get('instrument_type') == 'EQ':
                    return int(inst['instrument_token'])
        except Exception:
            pass
        return None

    # ── Data Package Builder ──────────────────────────────────────────

    def _build_tier3_data_package(self, symbol: str, position: dict,
                                  current_price: float, kalman_state: dict) -> dict:
        """
        Build the complete intelligence data package for ChatGPT review.

        Uses ONLY existing infrastructure. No new indicator code.
        Gracefully skips any component that fails.
        """
        from datetime import date as date_cls

        entry_price = position.get('entry_price', 0)
        pnl_pct = (current_price - entry_price) / entry_price if entry_price > 0 else 0
        pnl_rupees = (current_price - entry_price) * position.get('quantity', 0)
        peak = position.get('peak_price', entry_price)
        drawdown = (current_price - peak) / peak if peak > 0 else 0

        hold_days = 0
        entry_date_str = position.get('entry_date', '')
        if entry_date_str:
            try:
                entry_dt = date_cls.fromisoformat(entry_date_str)
                hold_days = (date_cls.today() - entry_dt).days
            except Exception:
                pass

        days_to_tuesday = self._days_to_next_tuesday()

        package = {
            # ── Position Status ─────────────────────────────────────
            'symbol': symbol,
            'entry_date': entry_date_str,
            'entry_price': entry_price,
            'current_price': current_price,
            'pnl_pct': round(pnl_pct, 4),
            'pnl_rupees': round(pnl_rupees, 2),
            'hold_days': hold_days,
            'days_to_tuesday': days_to_tuesday,
            'peak_price': peak,
            'drawdown_from_peak_pct': round(drawdown, 4),
            'quantity': position.get('quantity', 0),
            'sector': position.get('sector', 'Unknown'),
        }

        # ── Previous Day Data (PDH/PDL) ────────────────────────────
        try:
            token = self._get_instrument_token_for_symbol(symbol)
            if token:
                from datetime import timedelta as td
                yesterday = date_cls.today() - td(days=1)
                from_date = yesterday - td(days=5)
                candles = self.kite.historical_data(token, from_date, yesterday, "day")
                if candles and len(candles) >= 1:
                    pd_candle = candles[-1]
                    pdh = pd_candle['high']
                    pdl = pd_candle['low']
                    pdc = pd_candle['close']
                    pdo = pd_candle['open']
                    package.update({
                        'pdh': pdh, 'pdl': pdl, 'pdc': pdc, 'pdo': pdo,
                        'pd_range': round(pdh - pdl, 2),
                        'pd_candle_type': 'BULLISH' if pdc > pdo else 'BEARISH',
                    })
                    # Volume
                    package['yesterday_volume'] = pd_candle.get('volume', 0)

                    # Week high/low since entry
                    if len(candles) >= 2:
                        highs = [c['high'] for c in candles]
                        lows = [c['low'] for c in candles]
                        package['week_high'] = max(highs)
                        package['week_low'] = min(lows)
                        package['week_range'] = round(max(highs) - min(lows), 2)

                    # 20-day avg volume
                    if len(candles) >= 5:
                        vols = [c.get('volume', 0) for c in candles[-20:] if c.get('volume', 0) > 0]
                        if vols:
                            avg_vol = sum(vols) / len(vols)
                            package['avg_20d_volume'] = int(avg_vol)
                            yd_vol = pd_candle.get('volume', 0)
                            package['volume_ratio'] = round(yd_vol / avg_vol, 2) if avg_vol > 0 else 1.0
                            package['volume_trend'] = 'ABOVE_AVERAGE' if yd_vol > avg_vol else 'BELOW_AVERAGE'

                    # ── Daily Technicals from candle history ────────────
                    if len(candles) >= 14:
                        closes = [c['close'] for c in candles]

                        # RSI-14
                        rsi = self._calc_rsi(closes, 14)
                        if rsi is not None:
                            package['rsi_14d'] = round(rsi, 1)
                            if len(closes) >= 15:
                                prev_rsi = self._calc_rsi(closes[:-1], 14)
                                if prev_rsi is not None:
                                    package['rsi_trend'] = 'RISING' if rsi > prev_rsi else 'FALLING'

                        # EMA-21
                        if len(closes) >= 21:
                            ema21 = self._calc_ema(closes, 21)
                            if ema21:
                                package['ema_21d'] = round(ema21[-1], 2)
                                if len(ema21) >= 2:
                                    package['ema_21d_slope'] = 'RISING' if ema21[-1] > ema21[-2] else 'FALLING'

                        # ATR-14
                        if len(candles) >= 15:
                            atr = self._calc_atr(candles, 14)
                            if atr is not None:
                                package['atr_14d'] = round(atr, 2)
                                package['atr_pct'] = round(atr / current_price * 100, 2) if current_price > 0 else 0

                        # Support/Resistance (PDH/PDL as anchors)
                        if 'pdh' in package and 'pdl' in package:
                            package['nearest_support'] = package['pdl']
                            package['nearest_resistance'] = package['pdh']
                            if current_price > 0:
                                package['distance_to_support_pct'] = round(
                                    (package['pdl'] - current_price) / current_price * 100, 2)
                                package['distance_to_resistance_pct'] = round(
                                    (package['pdh'] - current_price) / current_price * 100, 2)
        except Exception as e:
            logger.debug(f"   Data package — PDH/technical error: {e}")

        # ── Kalman Filter Predictions ───────────────────────────────
        if kalman_state:
            package.update({
                'kalman_price_prediction': kalman_state.get('price', 0),
                'kalman_tuesday_prediction': kalman_state.get('tuesday_prediction', 0),
                'kalman_velocity': kalman_state.get('velocity', 0),
                'kalman_acceleration': kalman_state.get('acceleration', 0),
                'kalman_confidence': kalman_state.get('confidence', 0),
                'kalman_predicted_pnl_tuesday': kalman_state.get('predicted_pnl_pct', 0),
            })

        # ── FinBERT Sentiment ───────────────────────────────────────
        if getattr(self.config, 'PH8_FINBERT_ENABLED', True):
            try:
                finbert_data = self._get_tier3_sentiment(symbol)
                if finbert_data:
                    package.update(finbert_data)
            except Exception as e:
                logger.debug(f"   FinBERT for {symbol} failed: {e}")

        # ── Nifty Change Since Entry ────────────────────────────────
        try:
            nifty_change = self._get_nifty_change_since(entry_date_str)
            if nifty_change is not None:
                package['nifty_change_since_entry'] = round(nifty_change, 4)
        except Exception as e:
            logger.debug(f"   Nifty change calc failed: {e}")

        # ── Market Regime ───────────────────────────────────────────
        try:
            if hasattr(self, 'intelligent_engine') and self.intelligent_engine:
                regime = self.intelligent_engine.detect_market_regime()
                if regime:
                    package['market_regime'] = str(regime.name if hasattr(regime, 'name') else regime)
        except Exception as e:
            logger.debug(f"   Market regime detection failed: {e}")

        # ── NSE Expiry Context ──────────────────────────────────────
        try:
            expiry_info = self._get_nse_expiry_context()
            if expiry_info:
                package.update(expiry_info)
        except Exception as e:
            logger.debug(f"   Expiry context failed: {e}")

        return package

    # ── Helpers for data package ──────────────────────────────────────

    def _get_tier3_sentiment(self, symbol: str) -> Optional[dict]:
        """Get FinBERT sentiment for a Tier 3 stock."""
        if not hasattr(self, 'finbert') or not self.finbert:
            return None
        if not hasattr(self, 'news_scraper') or not self.news_scraper:
            return None

        try:
            news_data = self.news_scraper.get_stock_news(symbol, max_results=5)
            if not news_data:
                return None

            # news_data is list of headline strings
            combined_text = '. '.join(news_data[:5]) if isinstance(news_data, list) else str(news_data)
            result = self.finbert.analyze_sentiment(combined_text)

            if result:
                label = result.get('label', 'NEUTRAL')
                score = result.get('score', 0.5)
                return {
                    'finbert_sentiment': label.upper(),
                    'finbert_score': round(score, 2),
                    'recent_news_count': len(news_data) if isinstance(news_data, list) else 0,
                    'news_summary': combined_text[:200],
                }
        except Exception as e:
            logger.debug(f"   Sentiment analysis error for {symbol}: {e}")
        return None

    def _get_nifty_change_since(self, entry_date_str: str) -> Optional[float]:
        """Calculate Nifty change % since entry date."""
        if not entry_date_str:
            return None
        try:
            from datetime import date as date_cls, timedelta as td
            entry_dt = date_cls.fromisoformat(entry_date_str)
            from_date = entry_dt - td(days=2)
            to_date = date_cls.today() - td(days=1)

            # Nifty 50 token: 256265
            candles = self.kite.historical_data(256265, from_date, to_date, "day")
            if candles and len(candles) >= 2:
                entry_close = candles[0]['close']
                latest_close = candles[-1]['close']
                return (latest_close - entry_close) / entry_close
        except Exception:
            pass
        return None

    def _get_nse_expiry_context(self) -> dict:
        """Calculate NSE weekly expiry context (Tuesday expiry)."""
        from datetime import date as date_cls
        today = date_cls.today()
        weekday = today.weekday()  # 0=Mon

        # Next Tuesday
        days_to_tue = (1 - weekday) % 7
        if days_to_tue == 0 and weekday == 1:
            days_to_tue = 0  # Today is Tuesday
        elif days_to_tue == 0:
            days_to_tue = 7

        is_expiry_week = days_to_tue <= 6  # Always true for weekly options
        impact = 'NORMAL'
        if days_to_tue <= 1:
            impact = 'HIGH'
        elif days_to_tue <= 3:
            impact = 'CAUTION'

        return {
            'is_expiry_week': is_expiry_week,
            'days_to_expiry': days_to_tue,
            'expiry_impact': impact,
        }

    def _days_to_next_tuesday(self) -> int:
        """Calculate trading days to next Tuesday."""
        from datetime import date as date_cls
        weekday = date_cls.today().weekday()
        days = (1 - weekday) % 7
        if days == 0 and weekday != 1:
            days = 7
        return days

    @staticmethod
    def _calc_rsi(closes: list, period: int = 14) -> Optional[float]:
        """Calculate RSI from a list of closing prices."""
        if len(closes) < period + 1:
            return None
        deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
        gains = [d if d > 0 else 0 for d in deltas]
        losses = [-d if d < 0 else 0 for d in deltas]

        avg_gain = sum(gains[:period]) / period
        avg_loss = sum(losses[:period]) / period

        for i in range(period, len(deltas)):
            avg_gain = (avg_gain * (period - 1) + gains[i]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i]) / period

        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))

    @staticmethod
    def _calc_ema(values: list, period: int) -> Optional[list]:
        """Calculate EMA series from a list of values."""
        if len(values) < period:
            return None
        multiplier = 2.0 / (period + 1)
        ema = [sum(values[:period]) / period]
        for v in values[period:]:
            ema.append((v - ema[-1]) * multiplier + ema[-1])
        return ema

    @staticmethod
    def _calc_atr(candles: list, period: int = 14) -> Optional[float]:
        """Calculate ATR from candle data."""
        if len(candles) < period + 1:
            return None
        trs = []
        for i in range(1, len(candles)):
            h = candles[i]['high']
            l = candles[i]['low']
            pc = candles[i - 1]['close']
            tr = max(h - l, abs(h - pc), abs(l - pc))
            trs.append(tr)

        if len(trs) < period:
            return None
        atr = sum(trs[:period]) / period
        for tr in trs[period:]:
            atr = (atr * (period - 1) + tr) / period
        return atr

    # ── ChatGPT Tier 3 Review ─────────────────────────────────────────

    def _chatgpt_tier3_review(self, data_package: dict) -> dict:
        """
        Send the complete data package to ChatGPT for strategic review.

        Returns:
            Dict with: recommendation, confidence, reasoning, key_factors,
                       risk_level, kalman_assessment, tuesday_outlook, suggested_action
        """
        failsafe = getattr(self.config, 'PH8_CHATGPT_FAILSAFE', 'HOLD')
        default_response = {
            'recommendation': failsafe,
            'confidence': 0,
            'reasoning': 'ChatGPT unavailable — fail-safe applied',
            'key_factors': [],
            'risk_level': 'MEDIUM',
            'kalman_assessment': 'N/A',
            'tuesday_outlook': 'N/A',
            'suggested_action': 'NONE',
        }

        if not hasattr(self, 'chatgpt') or not self.chatgpt:
            logger.warning("   ChatGPT advisor not available — using fail-safe")
            return default_response

        try:
            import json as json_mod
            prompt = self._build_tier3_chatgpt_prompt(data_package)

            # Use ChatGPT Responses API
            import time as time_mod
            start = time_mod.time()

            response = self.chatgpt.client.responses.create(
                model=self.chatgpt.model,
                instructions=(
                    "You are a swing trading position analyst for Indian equities. "
                    "Analyze the position data and provide your recommendation in STRICT JSON format. "
                    "Your response must be ONLY valid JSON, no other text."
                ),
                input=prompt,
                temperature=0.3,
            )

            elapsed_ms = int((time_mod.time() - start) * 1000)
            raw_text = response.output_text.strip()

            # Parse JSON response
            # Strip markdown code fences if present
            if raw_text.startswith('```'):
                raw_text = raw_text.split('\n', 1)[-1].rsplit('```', 1)[0].strip()

            result = json_mod.loads(raw_text)

            # Validate required fields
            rec = result.get('recommendation', failsafe).upper()
            if rec not in ('HOLD', 'CONCERN', 'EXIT'):
                rec = failsafe

            return {
                'recommendation': rec,
                'confidence': min(max(int(result.get('confidence', 0)), 0), 100),
                'reasoning': str(result.get('reasoning', ''))[:500],
                'key_factors': result.get('key_factors', [])[:5],
                'risk_level': result.get('risk_level', 'MEDIUM').upper(),
                'kalman_assessment': str(result.get('kalman_assessment', ''))[:200],
                'tuesday_outlook': str(result.get('tuesday_outlook', ''))[:200],
                'suggested_action': str(result.get('suggested_action', ''))[:200],
                'response_time_ms': elapsed_ms,
            }

        except Exception as e:
            logger.error(f"   ChatGPT Tier 3 review failed: {type(e).__name__}: {e}")
            try:
                if self.telegram:
                    self.telegram.send_message(
                        f"PH8 Morning review: ChatGPT unavailable — HOLD\n{e}")
            except Exception:
                pass
            return default_response

    def _build_tier3_chatgpt_prompt(self, data_package: dict) -> str:
        """Build the ChatGPT prompt from the data package."""
        import json as json_mod

        symbol = data_package.get('symbol', 'UNKNOWN')
        pnl_pct = data_package.get('pnl_pct', 0)
        hold_days = data_package.get('hold_days', 0)
        days_to_tue = data_package.get('days_to_tuesday', 0)

        prompt = f"""PHASE 8 TIER 3 POSITION REVIEW — {symbol}
═══════════════════════════════════════════

POSITION DATA:
{json_mod.dumps(data_package, indent=2, default=str)}

TASK:
Analyze this CNC swing position held for {hold_days} days with {days_to_tue} trading days until next Tuesday exit window.

Current P&L: {pnl_pct:+.2%}

Provide your assessment in this EXACT JSON format:
{{
  "recommendation": "HOLD | CONCERN | EXIT",
  "confidence": 0-100,
  "reasoning": "2-3 sentences explaining your assessment",
  "key_factors": ["factor1", "factor2", "factor3"],
  "risk_level": "LOW | MEDIUM | HIGH | CRITICAL",
  "kalman_assessment": "interpretation of Kalman predictions",
  "tuesday_outlook": "expected outcome by Tuesday",
  "suggested_action": "specific suggestion if any"
}}

GUIDELINES:
- EXIT only if high-confidence negative signal (reversal, breakdown, or loss likely to worsen)
- CONCERN for degrading but not yet critical conditions
- HOLD for neutral or positive trajectory
- Consider: momentum (Kalman velocity), technicals (RSI, EMA), sentiment, volume
- Factor in days remaining — more patience with 4 days vs 1 day to go
"""
        return prompt

    def _run_tier1_fast_check(self, symbol: str, position: dict, current_price: float) -> bool:
        """
        v5.1.0: TIER 1 FAST CHECK — ~250ms per position.
        
        For MIS/Phase 5 gap scalps that need instant exit decisions.
        Skips: Truth Matrix, ChatGPT, ILS approach phases, Fibonacci exits.
        Uses: Existing direction-aware target/stop/predictive functions.
        
        v5.1.0 ENHANCEMENTS:
          - CHECK 3.5: Trailing Stop (locks profits after +0.5% excursion)
          - CHECK 3.6: Kalman Momentum Reversal (exits on confirmed trend flip)

        v5.5.1 ENHANCEMENTS:
          - TCAS PIVOT: After Kalman update, if SHORT + RA/ALIM + losing +
            Kalman BULLISH → fire Phase 6 early warning for CALL options

        EXIT DECISION ORDER (safety hierarchy):
          1. Hard target/stop
          2. Predictive stop (Kalman → stop trajectory)
          [TCAS Pivot signal — non-blocking, fires Phase 6 in parallel]
          3.5. Trailing stop (profit ratchet)
          3.6. Kalman momentum reversal (trend decay)
          4. Max hold timeout
          5. MIS mandatory cutoff
        
        Returns:
            True if position was exited (skip further processing)
            False if position should continue being held
        """
        direction = self._get_position_direction(position)
        pnl_pct = self._calculate_pnl_pct(position, current_price)
        entry_price = position.get('entry_price', current_price)
        stop_price = position.get('stop_price', entry_price * 0.985)
        atr = position.get('atr', 0)
        # Validate ATR is realistic before using it for exit thresholds.
        # An intraday ATR (15-min/1-min) would be 10-15× too small, making the
        # proximity threshold fire on single-tick noise.
        if atr > 0:
            atr_pct = (atr / current_price) * 100
            if atr_pct < 0.5 or atr_pct > 8.0:
                logger.warning(
                    f"🏎️ TIER1 {symbol}: ATR ₹{atr:.2f} ({atr_pct:.1f}%) outside sane range "
                    f"— recalculating before proximity check"
                )
                atr = self._fetch_real_atr(symbol, current_price)
                # v5.9.0: persist through orchestrator — direct dict mutation is silently
                # dropped because position is a copy from the central store. Without this,
                # the same bad ATR triggers another _fetch_real_atr on every 10s tick.
                self._update_position(symbol, position, atr=atr)

        # ─── CHECK 1: HARD STOP HIT → EXIT IMMEDIATELY ───
        # v5.3.3: Stop is now raw 0.5× ATR (no clamping) — wide safety net
        if self._is_stop_hit(position, current_price):
            logger.warning(f"🏎️ TIER1 {symbol}: 🛑 STOP HIT! ₹{current_price:.2f} (P&L: {pnl_pct:+.2f}%)")
            exit_success = self._execute_exit(symbol, "TIER1_STOP_HIT")
            if exit_success:
                logger.info("   ✅ Tier 1 stop exit successful")
                if self.telegram:
                    self.telegram.send_message(
                        "🛑 TIER 1 STOP HIT\n\n"
                        f"Stock: {symbol}\n"
                        f"Direction: {direction}\n"
                        f"Entry: ₹{entry_price:.2f}\n"
                        f"Exit: ₹{current_price:.2f}\n"
                        f"P&L: {pnl_pct:+.2f}%"
                    )
            else:
                logger.error("   ❌ Tier 1 stop exit FAILED!")
            return True
        
        # ─── CHECK 1.5: HARD EXIT TIME → EXIT (09:45 deadline) ───
        # v5.3.3: Absolute time boundary for gap scalps
        hard_exit_time = position.get('hard_exit_time')
        if hard_exit_time:
            now_time = datetime.now().time()
            if isinstance(hard_exit_time, str):
                try:
                    hard_exit_time = datetime.strptime(hard_exit_time, '%H:%M:%S').time()
                except (ValueError, TypeError):
                    hard_exit_time = None
            if hard_exit_time and now_time >= hard_exit_time:
                logger.warning(f"🏎️ TIER1 {symbol}: ⏰ HARD EXIT TIME {hard_exit_time.strftime('%H:%M')}! "
                             f"₹{current_price:.2f} (P&L: {pnl_pct:+.2f}%)")
                exit_success = self._execute_exit(symbol, "TIER1_HARD_EXIT_TIME")
                if exit_success and self.telegram:
                    self.telegram.send_message(
                        "⏰ TIER 1 HARD EXIT TIME\n\n"
                        f"Stock: {symbol}\n"
                        f"Deadline: {hard_exit_time.strftime('%H:%M')}\n"
                        f"Exit: ₹{current_price:.2f}\n"
                        f"P&L: {pnl_pct:+.2f}%"
                    )
                return True
        
        # ─── CHECK 1.7: BREAKEVEN TRAIL TIME → TIGHTEN STOP (09:40 safety) ───
        # v5.3.3: If target not hit by 09:40, move stop to entry (breakeven)
        breakeven_trail_time = position.get('breakeven_trail_time')
        if breakeven_trail_time and not position.get('breakeven_trail_applied', False):
            now_time = datetime.now().time()
            if isinstance(breakeven_trail_time, str):
                try:
                    breakeven_trail_time = datetime.strptime(breakeven_trail_time, '%H:%M:%S').time()
                except (ValueError, TypeError):
                    breakeven_trail_time = None
            if breakeven_trail_time and now_time >= breakeven_trail_time:
                # v5.4.0 FIX: Persist through orchestrator
                self._update_position(symbol, position, breakeven_trail_applied=True)
                if direction == 'LONG' and stop_price < entry_price:
                    old_stop = stop_price
                    self._update_position(symbol, position, stop_price=entry_price)
                    logger.warning(f"🏎️ TIER1 {symbol}: ⏰ BREAKEVEN TRAIL @ {breakeven_trail_time.strftime('%H:%M')} "
                                 f"| Stop: ₹{old_stop:.2f} → ₹{entry_price:.2f}")
                    # If already below entry, exit immediately
                    if current_price < entry_price:
                        logger.warning(f"🏎️ TIER1 {symbol}: 🛑 BELOW BREAKEVEN → EXIT! ₹{current_price:.2f}")
                        exit_success = self._execute_exit(symbol, "TIER1_BREAKEVEN_EXIT")
                        if exit_success and self.telegram:
                            self.telegram.send_message(
                                "⏰ TIER 1 BREAKEVEN EXIT\n\n"
                                f"Stock: {symbol}\n"
                                f"Time: {breakeven_trail_time.strftime('%H:%M')} breakeven\n"
                                f"Exit: ₹{current_price:.2f}\n"
                                f"P&L: {pnl_pct:+.2f}%"
                            )
                        return True
                elif direction == 'SHORT' and stop_price > entry_price:
                    old_stop = stop_price
                    # v5.4.0 FIX: Persist through orchestrator
                    self._update_position(symbol, position, stop_price=entry_price)
                    logger.warning(f"🏎️ TIER1 {symbol}: ⏰ BREAKEVEN TRAIL @ {breakeven_trail_time.strftime('%H:%M')} "
                                 f"| Stop: ₹{old_stop:.2f} → ₹{entry_price:.2f}")
                    if current_price > entry_price:
                        logger.warning(f"🏎️ TIER1 {symbol}: 🛑 ABOVE BREAKEVEN → EXIT! ₹{current_price:.2f}")
                        exit_success = self._execute_exit(symbol, "TIER1_BREAKEVEN_EXIT")
                        if exit_success and self.telegram:
                            self.telegram.send_message(
                                "⏰ TIER 1 BREAKEVEN EXIT\n\n"
                                f"Stock: {symbol}\n"
                                f"Time: {breakeven_trail_time.strftime('%H:%M')} breakeven\n"
                                f"Exit: ₹{current_price:.2f}\n"
                                f"P&L: {pnl_pct:+.2f}%"
                            )
                        return True
        
        # ─── CHECK 2: TARGET HIT → EXIT (only for non-Smart-TCAS positions) ───
        # v5.3.3: Smart TCAS positions have aspirational target (5%) that won't trigger.
        # For legacy/CNC positions, hard target still applies.
        if self._is_target_hit(position, current_price):
            logger.info(f"🏎️ TIER1 {symbol}: 🎯 TARGET HIT! ₹{current_price:.2f} (P&L: {pnl_pct:+.2f}%)")
            exit_success = self._execute_exit(symbol, "TIER1_TARGET_HIT")
            if exit_success:
                logger.info("   ✅ Tier 1 target exit successful")
                if self.telegram:
                    self.telegram.send_message(
                        "🎯 TIER 1 TARGET HIT\n\n"
                        f"Stock: {symbol}\n"
                        f"Direction: {direction}\n"
                        f"Entry: ₹{entry_price:.2f}\n"
                        f"Exit: ₹{current_price:.2f}\n"
                        f"P&L: {pnl_pct:+.2f}%"
                    )
            else:
                logger.error("   ❌ Tier 1 target exit FAILED!")
            return True
        
        # ─── CHECK 3: PREDICTIVE STOP → EXIT BEFORE STOP IS HIT ───
        kalman_state = None  # Will be populated here, reused in CHECK 3.6
        if self.predictive_stop:
            atr = position.get('atr', current_price * 0.02)  # Use Phase 5 ATR or estimate
            kalman_state = self._update_kalman(symbol, current_price, atr)
            current_rsi = position.get('phase4_tracking', {}).get('current_rsi')
            
            # v5.3.3: Smart TCAS positions use lower profit floor (0.3% instead of 0.5%)
            profit_override = position.get('tcas_activation_pct', None) if position.get('smart_tcas_enabled') else None
            
            predictive_signal = self.predictive_stop.should_exit(
                symbol=symbol,
                kalman_state=kalman_state.to_dict() if kalman_state else {},
                current_price=current_price,
                entry_price=entry_price,
                stop_loss_price=stop_price,
                current_rsi=current_rsi,
                min_profit_override=profit_override
            )
            
            if predictive_signal.should_exit:
                logger.warning(f"🏎️ TIER1 {symbol}: 🔮 PREDICTIVE EXIT! {predictive_signal.reason.value} "
                             f"(Conf={predictive_signal.confidence:.0%}, P&L: {pnl_pct:+.2f}%)")
                exit_success = self._execute_exit(symbol, f"TIER1_PREDICTIVE_{predictive_signal.reason.value}")
                if exit_success and self.telegram:
                    self.telegram.send_message(
                        "🔮 TIER 1 PREDICTIVE EXIT\n\n"
                        f"Stock: {symbol}\n"
                        f"Reason: {predictive_signal.reason.value}\n"
                        f"Confidence: {predictive_signal.confidence:.0%}\n"
                        f"P&L: {pnl_pct:+.2f}%"
                    )
                return True
        
        # ═══════════════════════════════════════════════════════════════
        # v5.3.3 FIX: Write live Kalman state back to tracking dict
        # Without this, the flight path display shows frozen init values.
        # Also updates TCAS/Health so display reflects reality.
        # ═══════════════════════════════════════════════════════════════
        if kalman_state:
            tracking = position.setdefault('phase4_tracking', {})
            tracking['kalman_state'] = kalman_state.to_dict() if hasattr(kalman_state, 'to_dict') else {}
            
            # Update TCAS status based on live data
            velocity = kalman_state.velocity if hasattr(kalman_state, 'velocity') else 0
            acceleration = kalman_state.acceleration if hasattr(kalman_state, 'acceleration') else 0
            
            # Simple TCAS level from Kalman velocity
            if direction == 'LONG':
                approaching_stop = velocity < -0.01
                fast_approach = velocity < -0.05
            else:
                approaching_stop = velocity > 0.01
                fast_approach = velocity > 0.05
            
            if fast_approach and pnl_pct < -0.3:
                tcas_level = 'ALIM'
            elif approaching_stop and pnl_pct < 0:
                tcas_level = 'RA'
            elif approaching_stop:
                tcas_level = 'TA'
            else:
                tcas_level = 'CLEAR'
            tracking.setdefault('tcas_status', {})['alert_level'] = tcas_level
            
            # Update health score (simple: based on pnl + velocity direction)
            health = 50
            if pnl_pct > 0.3:
                health += 20
            elif pnl_pct < -0.3:
                health -= 20
            if (direction == 'LONG' and velocity > 0) or (direction == 'SHORT' and velocity < 0):
                health += 15
            elif (direction == 'LONG' and velocity < -0.02) or (direction == 'SHORT' and velocity > 0.02):
                health -= 15
            health = max(10, min(95, health))
            tracking.setdefault('health_score', {})['total'] = health

            # ═══════════════════════════════════════════════════════════
            # v5.5.1: TCAS PIVOT EARLY SIGNAL (Tier 1)
            # SHORT + RA/ALIM + losing + Kalman confirms BULLISH →
            # Fire Phase 6 early signal while equity is still open.
            # Same logic as Tier 2 (ISSUE-15) but inside Tier 1 fast loop.
            # ═══════════════════════════════════════════════════════════
            if (
                self.phase6 is not None
                and direction == 'SHORT'
                and symbol not in self.tcas_pivot_early_signaled
                and tcas_level in ('RA', 'ALIM')
            ):
                try:
                    now_time = datetime.now().time()
                    if (
                        pnl_pct < 0
                        and velocity > 0.3
                        and acceleration >= 0
                        and now_time < dt_time(13, 30)
                    ):
                        eq_entry = position.get('entry_price', 0)
                        eq_stop  = position.get('stop_price', 0)
                        atr_val  = position.get('atr', current_price * 0.02)
                        dist_to_stop = eq_stop - current_price  # SHORT: stop above current
                        dist_atr = dist_to_stop / atr_val if atr_val > 0 else 0

                        early_signal = {
                            'symbol': symbol,
                            'confirmed_direction': 'BULLISH',
                            'status': 'EARLY_WARNING',
                            'signal_time': datetime.now(),
                            'signal_price': current_price,
                            'equity_entry': eq_entry,
                            'equity_stop': eq_stop,
                            'atr': atr_val,
                            'kalman_velocity': velocity,
                            'kalman_acceleration': acceleration,
                            'tcas_alert': tcas_level,
                            'equity_pnl': pnl_pct,
                            'equity_still_open': True,
                        }
                        self.tcas_pivot_early_signaled.add(symbol)
                        logger.info(
                            f"📡 TIER1 TCAS PIVOT EARLY: {symbol} SHORT {tcas_level}+loss "
                            f"(pnl={pnl_pct:.1f}%, vel={velocity:.2f}, acc={acceleration:.3f}) → "
                            f"BULLISH early warning → Phase 6"
                        )

                        if self.telegram:
                            try:
                                acc_label = (f"+{acceleration:.3f} (building)"
                                             if acceleration > 0 else f"{acceleration:.3f} (flat)")
                                self.telegram.send_message(
                                    f"📡 TCAS PIVOT — TIER 1 EARLY WARNING\n"
                                    f"{'='*32}\n"
                                    f"Symbol : {symbol}  (SHORT — LOSING)\n"
                                    f"Source : Tier 1 Fast Check\n"
                                    f"Time   : {now_time.strftime('%H:%M:%S')}\n"
                                    f"\n"
                                    f"WHY TRIGGERED:\n"
                                    f"  • TCAS {tcas_level} — price rising toward stop\n"
                                    f"  • Position in loss ({pnl_pct:+.2f}%)\n"
                                    f"  • Kalman confirms BULLISH momentum\n"
                                    f"\n"
                                    f"POSITION:\n"
                                    f"  Entry  : ₹{eq_entry:,.2f}\n"
                                    f"  Current: ₹{current_price:,.2f}\n"
                                    f"  Stop   : ₹{eq_stop:,.2f}  ({dist_to_stop:.2f} away, {dist_atr:.2f} ATR)\n"
                                    f"\n"
                                    f"KALMAN MOMENTUM:\n"
                                    f"  Velocity    : +{velocity:.3f}/min\n"
                                    f"  Acceleration: {acc_label}\n"
                                    f"\n"
                                    f"ACTION:\n"
                                    f"  Passing to Phase 6 for CALL options analysis"
                                )
                            except Exception as _te:
                                logger.warning(f"   TCAS pivot Tier1 Telegram failed: {_te}")

                        self.phase6.on_tcas_direction_signal(early_signal)
                except Exception as e:
                    logger.error(f"   TCAS pivot Tier1 early signal failed for {symbol}: {e}")

        # ═══════════════════════════════════════════════════════════════
        # CHECK 3.5: SMART TCAS TRAILING STOP (v5.3.3)
        # ═══════════════════════════════════════════════════════════════
        # v5.3.3: TCAS activates at +0.3% (configurable per position).
        # On activation:
        #   a) Lock breakeven (stop → entry price)
        #   b) Start trailing: stop = peak - activation_pct
        # After activation: ratchet stop upward only (peak - 0.3%).
        #
        # For non-Smart-TCAS positions: falls back to old 0.5% activation.
        # ═══════════════════════════════════════════════════════════════
        
        smart_tcas = position.get('smart_tcas_enabled', False)
        TCAS_ACT_PCT = position.get('tcas_activation_pct', 0.3) if smart_tcas else 0.5
        TRAIL_OFFSET_PCT = position.get('tcas_activation_pct', 0.3) if smart_tcas else 0.5  # Trail at activation% below peak
        
        trailing_active = position.get('tier1_trailing_active', False)
        
        if direction == 'LONG':
            max_price = position.get('max_price', current_price)
            excursion_pct = ((max_price - entry_price) / entry_price) * 100 if entry_price > 0 else 0
            
            if not trailing_active:
                # Check activation: has price excursion reached TCAS threshold?
                if excursion_pct >= TCAS_ACT_PCT:
                    # v5.4.0 FIX: Persist through orchestrator
                    self._update_position(symbol, position, tier1_trailing_active=True)
                    trailing_active = True

                    # v5.3.3: Lock breakeven first
                    if smart_tcas and position.get('stop_price', 0) < entry_price:
                        self._update_position(symbol, position, stop_price=entry_price)
                        logger.info(f"🏎️ TIER1 {symbol}: 🔒 BREAKEVEN LOCKED (TCAS at +{excursion_pct:.1f}%)")

                    # Calculate trailing stop: peak - TRAIL_OFFSET_PCT
                    trail_stop = max_price * (1 - TRAIL_OFFSET_PCT / 100)
                    trail_stop = round(trail_stop * 10) / 10  # Round to tick

                    # Only set if better than current stop
                    if trail_stop > position.get('stop_price', 0):
                        self._update_position(symbol, position,
                                              stop_price=trail_stop,
                                              tier1_trail_stop=trail_stop)

                    tcas_label = "TCAS" if smart_tcas else "TRAILING"
                    logger.info(f"🏎️ TIER1 {symbol}: 📈 {tcas_label} ACTIVATED at +{excursion_pct:.1f}% "
                               f"| Trail stop: ₹{position['stop_price']:.2f} (entry: ₹{entry_price:.2f})")
            else:
                # Already active — ratchet stop upward only
                trail_stop = max_price * (1 - TRAIL_OFFSET_PCT / 100)
                trail_stop = round(trail_stop * 10) / 10
                current_stop = position.get('stop_price', 0)

                if trail_stop > current_stop:
                    old_stop = current_stop
                    # v5.4.0 FIX: Persist through orchestrator
                    self._update_position(symbol, position,
                                          stop_price=trail_stop,
                                          tier1_trail_stop=trail_stop)
                    logger.info(f"🏎️ TIER1 {symbol}: 📈 TRAIL RATCHET ₹{old_stop:.2f} → ₹{trail_stop:.2f} "
                               f"(peak: ₹{max_price:.2f}, +{excursion_pct:.1f}%)")
        
        elif direction == 'SHORT':
            min_price = position.get('min_price', current_price)
            excursion_pct = ((entry_price - min_price) / entry_price) * 100 if entry_price > 0 else 0
            
            if not trailing_active:
                if excursion_pct >= TCAS_ACT_PCT:
                    # v5.4.0 FIX: Persist through orchestrator
                    self._update_position(symbol, position, tier1_trailing_active=True)
                    trailing_active = True

                    # v5.3.3: Lock breakeven
                    if smart_tcas and position.get('stop_price', 999999) > entry_price:
                        self._update_position(symbol, position, stop_price=entry_price)
                        logger.info(f"🏎️ TIER1 {symbol}: 🔒 BREAKEVEN LOCKED (TCAS at +{excursion_pct:.1f}%)")

                    trail_stop = min_price * (1 + TRAIL_OFFSET_PCT / 100)
                    trail_stop = round(trail_stop * 10) / 10

                    if trail_stop < position.get('stop_price', 999999):
                        self._update_position(symbol, position,
                                              stop_price=trail_stop,
                                              tier1_trail_stop=trail_stop)

                    tcas_label = "TCAS" if smart_tcas else "TRAILING"
                    logger.info(f"🏎️ TIER1 {symbol}: 📉 {tcas_label} ACTIVATED at +{excursion_pct:.1f}% "
                               f"| Trail stop: ₹{position['stop_price']:.2f} (entry: ₹{entry_price:.2f})")
            else:
                trail_stop = min_price * (1 + TRAIL_OFFSET_PCT / 100)
                trail_stop = round(trail_stop * 10) / 10
                current_stop = position.get('stop_price', 999999)

                if trail_stop < current_stop:
                    old_stop = current_stop
                    # v5.4.0 FIX: Persist through orchestrator
                    self._update_position(symbol, position,
                                          stop_price=trail_stop,
                                          tier1_trail_stop=trail_stop)
                    logger.info(f"🏎️ TIER1 {symbol}: 📉 TRAIL RATCHET ₹{old_stop:.2f} → ₹{trail_stop:.2f} "
                               f"(trough: ₹{min_price:.2f}, +{excursion_pct:.1f}%)")
        
        # Re-check stop after trailing adjustment (stop may have moved up)
        stop_price = position.get('stop_price', stop_price)
        if self._is_stop_hit(position, current_price):
            logger.warning(f"🏎️ TIER1 {symbol}: 📈🛑 TRAILING STOP HIT! ₹{current_price:.2f} (P&L: {pnl_pct:+.2f}%)")
            exit_success = self._execute_exit(symbol, "TIER1_TRAILING_STOP")
            if exit_success and self.telegram:
                self.telegram.send_message(
                    "📈🛑 TIER 1 TRAILING STOP\n\n"
                    f"Stock: {symbol}\n"
                    f"Direction: {direction}\n"
                    f"Entry: ₹{entry_price:.2f}\n"
                    f"Exit: ₹{current_price:.2f}\n"
                    f"Trail Stop: ₹{stop_price:.2f}\n"
                    f"P&L: {pnl_pct:+.2f}%"
                )
            return True
        
        # ═══════════════════════════════════════════════════════════════
        # CHECK 3.6: KALMAN MOMENTUM REVERSAL EXIT (v5.3.3)
        # ═══════════════════════════════════════════════════════════════
        # v5.3.3: Only fires AFTER TCAS trailing is active (profit locked).
        # Detects momentum decay: velocity + acceleration both bearish.
        # Gate: trailing must be active (ensures minimum profit locked)
        # Sustained for 2 consecutive checks to avoid noise.
        # ═══════════════════════════════════════════════════════════════
        
        KALMAN_MIN_PROFIT_PCT = position.get('tcas_activation_pct', 0.3) if smart_tcas else 0.3
        KALMAN_MIN_EXCURSION_PCT = KALMAN_MIN_PROFIT_PCT * 2   # 0.6% for 0.3% activation
        TIER1_KALMAN_SUSTAIN_COUNT = 2        # Consecutive bearish checks needed
        
        # Get or update Kalman state (reuse from CHECK 3 if available)
        if kalman_state is None:
            atr = position.get('atr', current_price * 0.02)
            kalman_state = self._update_kalman(symbol, current_price, atr)
        
        if kalman_state:
            velocity = kalman_state.velocity if hasattr(kalman_state, 'velocity') else 0
            acceleration = kalman_state.acceleration if hasattr(kalman_state, 'acceleration') else 0
            
            # Calculate excursion from entry
            if direction == 'LONG':
                max_price = position.get('max_price', current_price)
                excursion_from_entry = ((max_price - entry_price) / entry_price) * 100 if entry_price > 0 else 0
                is_reversal = velocity < 0 and acceleration < 0
                made_new_extreme = current_price >= max_price  # New high resets counter
            else:
                min_price = position.get('min_price', current_price)
                excursion_from_entry = ((entry_price - min_price) / entry_price) * 100 if entry_price > 0 else 0
                is_reversal = velocity > 0 and acceleration > 0
                made_new_extreme = current_price <= min_price  # New low resets counter
            
            # Gate 1: Must be in profit (TCAS activation level)
            # Gate 2: Must have had meaningful excursion
            # v5.3.3: For Smart TCAS, also require trailing to be active
            kalman_gate_open = (pnl_pct >= KALMAN_MIN_PROFIT_PCT and 
                excursion_from_entry >= KALMAN_MIN_EXCURSION_PCT)
            if smart_tcas:
                kalman_gate_open = kalman_gate_open and trailing_active
            
            if kalman_gate_open:

                reversal_counter = position.get('tier1_kalman_reversal_count', 0)

                if made_new_extreme:
                    # Momentum resumed — reset counter
                    if reversal_counter > 0:
                        logger.debug(f"🏎️ TIER1 {symbol}: Kalman reversal counter reset (new extreme)")
                    # v5.4.0 FIX: Persist through orchestrator
                    self._update_position(symbol, position, tier1_kalman_reversal_count=0)
                elif is_reversal:
                    # Velocity + acceleration both confirm reversal
                    reversal_counter += 1
                    # v5.4.0 FIX: Persist through orchestrator
                    self._update_position(symbol, position, tier1_kalman_reversal_count=reversal_counter)
                    
                    if reversal_counter >= TIER1_KALMAN_SUSTAIN_COUNT:
                        logger.warning(
                            f"🏎️ TIER1 {symbol}: 🔄 KALMAN REVERSAL EXIT! "
                            f"vel={velocity:.4f} acc={acceleration:.6f} "
                            f"sustained={reversal_counter}x (P&L: {pnl_pct:+.2f}%)"
                        )
                        exit_success = self._execute_exit(symbol, "TIER1_KALMAN_REVERSAL")
                        if exit_success and self.telegram:
                            self.telegram.send_message(
                                "🔄 TIER 1 KALMAN REVERSAL EXIT\n\n"
                                f"Stock: {symbol}\n"
                                f"Direction: {direction}\n"
                                f"Entry: ₹{entry_price:.2f}\n"
                                f"Exit: ₹{current_price:.2f}\n"
                                f"Kalman vel: {velocity:.4f}\n"
                                f"Peak excursion: +{excursion_from_entry:.1f}%\n"
                                f"P&L locked: {pnl_pct:+.2f}%"
                            )
                        return True
                    else:
                        logger.info(
                            f"🏎️ TIER1 {symbol}: 🔄 Kalman reversal signal {reversal_counter}/{TIER1_KALMAN_SUSTAIN_COUNT} "
                            f"(vel={velocity:.4f}, acc={acceleration:.6f})"
                        )
                else:
                    # Not a clean reversal — decay counter gradually
                    if reversal_counter > 0:
                        # v5.4.0 FIX: Persist through orchestrator
                        self._update_position(symbol, position, tier1_kalman_reversal_count=max(0, reversal_counter - 1))
        
        # ─── CHECK 3.7: STALE GAP ABANDONMENT EXIT (v5.7.0) ───
        # For PH5 gap scalps: after 4 minutes if there is STILL no gap fill progress
        # (price hasn't moved meaningfully and Kalman velocity is flat), the gap has
        # been absorbed by the market and will NOT fill. Holding until 09:45 just risks
        # a late adverse move on a trade that was never working.
        # Exit near-flat now; free capital for the next opportunity.
        #
        # Fires ONLY when ALL are true:
        #   a) smart_tcas position (PH5 gap scalp — not a CNC or manual trade)
        #   b) TCAS has NOT activated (no profit momentum at all)
        #   c) ≥ 4 min elapsed since entry (past opening noise)
        #   d) P&L between −0.4% and +0.1% (genuinely sideways, not trending to stop)
        #   e) |Kalman velocity| < 0.025 (confirmed flat — not just a slow trend)
        if position.get('smart_tcas_enabled', False) and not position.get('tier1_trailing_active', False):
            _sg_entry_str = position.get('entry_time', '')
            if _sg_entry_str:
                try:
                    _sg_entry = (datetime.fromisoformat(_sg_entry_str)
                                 if isinstance(_sg_entry_str, str) else _sg_entry_str)
                    _sg_elapsed = (datetime.now() - _sg_entry).total_seconds() / 60

                    if _sg_elapsed >= 4.0:
                        # Reuse kalman_state from CHECK 3/3.6 if available
                        _sg_vel = 0.0
                        if kalman_state is not None:
                            _sg_vel = (kalman_state.velocity
                                       if hasattr(kalman_state, 'velocity') else 0.0)
                        else:
                            _sg_vel = (position.get('phase4_tracking', {})
                                       .get('kalman_state', {}).get('velocity', 0.0))

                        _gap_stale = (
                            pnl_pct < 0.1 and           # no profit — fill hasn't happened
                            pnl_pct > -0.4 and          # not near stop — genuinely sideways
                            abs(_sg_vel) < 0.025         # Kalman confirms: no directional momentum
                        )

                        if _gap_stale:
                            logger.warning(
                                f"🏎️ TIER1 {symbol}: 🕳️ STALE GAP EXIT! "
                                f"No fill progress after {_sg_elapsed:.1f}min "
                                f"| P&L: {pnl_pct:+.2f}% | Velocity: {_sg_vel:.4f} (flat)"
                            )
                            _sg_success = self._execute_exit(symbol, "TIER1_STALE_GAP")
                            if _sg_success:
                                if self.telegram:
                                    self.telegram.send_message(
                                        "🕳️ TIER 1 STALE GAP EXIT\n\n"
                                        f"Stock: {symbol}\n"
                                        f"Direction: {direction}\n"
                                        f"Held: {_sg_elapsed:.1f} min (no gap fill)\n"
                                        f"P&L: {pnl_pct:+.2f}%\n"
                                        f"Velocity: {_sg_vel:.4f}"
                                    )
                                return True
                except (ValueError, TypeError) as _sg_e:
                    logger.debug(f"   Stale gap check error: {_sg_e}")

        # ─── CHECK 4: MAX HOLD TIME EXCEEDED → EXIT AT MARKET ───
        # v4.14.1: Skip max hold timer if TCAS trailing is active (stop already protected)
        max_hold_minutes = position.get('max_hold_minutes', 60)
        entry_time_str = position.get('entry_time', '')
        if entry_time_str:
            try:
                if isinstance(entry_time_str, str):
                    entry_time = datetime.fromisoformat(entry_time_str)
                else:
                    entry_time = entry_time_str
                elapsed_minutes = (datetime.now() - entry_time).total_seconds() / 60
                if elapsed_minutes > max_hold_minutes:
                    if position.get('tier1_trailing_active', False):
                        # TCAS trailing is managing exit — skip the rigid timer
                        logger.info(
                            f"🏎️ TIER1 {symbol}: ⏰ Max hold {elapsed_minutes:.0f}min > {max_hold_minutes}min "
                            f"BYPASSED — TCAS trailing active (stop protected at ₹{position.get('tier1_trail_stop', 0):.2f})"
                        )
                    else:
                        logger.warning(f"🏎️ TIER1 {symbol}: ⏰ MAX HOLD EXCEEDED ({elapsed_minutes:.0f}min > {max_hold_minutes}min)")
                        exit_success = self._execute_exit(symbol, f"TIER1_MAX_HOLD_{max_hold_minutes}min")
                        if exit_success and self.telegram:
                            self.telegram.send_message(
                                "⏰ TIER 1 MAX HOLD EXIT\n\n"
                                f"Stock: {symbol}\n"
                                f"Held: {elapsed_minutes:.0f} min (max: {max_hold_minutes})\n"
                                f"P&L: {pnl_pct:+.2f}%"
                            )
                        return True
            except (ValueError, TypeError) as e:
                logger.debug(f"   Entry time parse error: {e}")
        
        # ─── CHECK 5: MIS MANDATORY EXIT (auto_exit_by or default) ───
        should_mis_exit, mis_reason = self._check_mis_mandatory_exit(position)
        if should_mis_exit:
            logger.warning(f"🏎️ TIER1 {symbol}: ⏰ {mis_reason}")
            exit_success = self._execute_exit(symbol, mis_reason)
            if exit_success:
                logger.info("   ✅ MIS mandatory exit successful")
            else:
                logger.error("   ❌ MIS mandatory exit FAILED!")
                if self.telegram:
                    self.telegram.send_message(
                        "⚠️ URGENT: MIS EXIT FAILED\n\n"
                        f"Stock: {symbol}\n"
                        f"Reason: {mis_reason}\n"
                        f"P&L: {pnl_pct:+.2f}%\n\n"
                        "⚠️ Manual exit required immediately!"
                    )
            return True
        
        # ─── STILL HOLDING: Log fast check status ───
        progress = self._calculate_progress_to_target(position, current_price)
        dist_to_target = self._calculate_distance_to_target(position, current_price)
        dist_to_stop = self._calculate_distance_to_stop(position, current_price)
        
        # v5.1.0: Enhanced status with trailing info
        trail_info = ""
        if position.get('tier1_trailing_active'):
            trail_info = f" | 📈 Trail: ₹{position.get('tier1_trail_stop', 0):.2f}"
        
        kalman_info = ""
        rev_count = position.get('tier1_kalman_reversal_count', 0)
        if rev_count > 0:
            kalman_info = f" | 🔄 Rev: {rev_count}/{TIER1_KALMAN_SUSTAIN_COUNT}"
        
        logger.info(
            f"🏎️ TIER1 {symbol}: ₹{current_price:.2f} | {direction} | P&L: {pnl_pct:+.2f}% | "
            f"Target: ₹{dist_to_target:.2f} away ({progress:.0f}%) | "
            f"Stop: ₹{dist_to_stop:.2f} safe{trail_info}{kalman_info}"
        )
        
        return False  # Not exited, continue holding


    def run_monitoring_cycle(self):
        """
        Main monitoring cycle.
        
        v4.14.0: PRIORITY TIER SYSTEM
           - Tier 1 (MIS/Phase 5): Fast check FIRST, every cycle
           - Tier 2 (CNC/Swing): Full pipeline, only if timer elapsed
        v4.8.1: Now resets consultation counts daily (C3)
        v4.10.0: Added clear status logging like Phase 2
        
        Steps:
        1. Check interrupt flags
        2. Batch fetch ALL prices
        3. TIER 1: Fast check all MIS positions (target/stop/timeout)
        4. TIER 2: Full pipeline for CNC positions (Kalman/TCAS/ILS/ChatGPT)
        5. Save state
        """
        if not self.positions:
            return
        
        cycle_start = datetime.now()
        
        # ═══════════════════════════════════════════════════════════════════
        # v4.10.0 NEW: Phase 4 Status Banner (every 5 minutes)
        # ═══════════════════════════════════════════════════════════════════
        self._log_phase4_status_if_needed()
        
        # ═══════════════════════════════════════════════════════════════════
        # v4.8.1 C3: Reset consultation counts at market open
        # ═══════════════════════════════════════════════════════════════════
        self._reset_consultation_counts_if_needed()
        
        # ═══════════════════════════════════════════════════════════════════
        # STEP 1: Check interrupt flags
        # ═══════════════════════════════════════════════════════════════════
        
        if self.tcas_alim_flag or self.emergency_exit_queue:
            self._process_emergency_exits()
            return
        
        # ═══════════════════════════════════════════════════════════════════
        # STEP 2: Broker sync (every 5 min)
        # ═══════════════════════════════════════════════════════════════════
        
        if (datetime.now() - self.last_broker_sync).total_seconds() > self.BROKER_SYNC_INTERVAL:
            self._sync_with_broker()
        
        # ═══════════════════════════════════════════════════════════════════
        # STEP 3: Batch price fetch (ALL positions - Tier 1 + Tier 2)
        # ═══════════════════════════════════════════════════════════════════
        
        symbols = list(self.positions.keys())
        if not symbols:
            return
        
        try:
            quotes = self.kite.quote([f"NSE:{s}" for s in symbols])
        except Exception as e:
            logger.error(f"Price fetch failed: {e}")
            return
        
        # ═══════════════════════════════════════════════════════════════════
        # STEP 4A: TIER 1 — Fast check MIS/Phase 5 positions FIRST
        # ~200ms per position. Target/stop/timeout only. No ChatGPT.
        # ═══════════════════════════════════════════════════════════════════
        
        tier1_positions = self._get_tier1_positions()
        tier2_positions = self._get_tier2_positions()
        
        if tier1_positions:
            logger.debug(f"🏎️ TIER 1: Processing {len(tier1_positions)} MIS position(s)")
        
        for symbol, position in tier1_positions.items():
            quote_key = f"NSE:{symbol}"
            quote_data = quotes.get(quote_key, {})
            current_price = quote_data.get('last_price', 0)

            if current_price <= 0:
                continue

            # v5.4.0 FIX: Persist live price through orchestrator
            direction = self._get_position_direction(position)
            extreme_updates = {'current_price': current_price}
            if direction == "SHORT":
                new_min = min(position.get("min_price", current_price), current_price)
                extreme_updates['min_price'] = new_min
            else:
                new_max = max(position.get("max_price", current_price), current_price)
                extreme_updates['max_price'] = new_max
            self._update_position(symbol, position, **extreme_updates)

            # Run fast 5-check exit system
            exited = self._run_tier1_fast_check(symbol, position, current_price)
            if exited:
                # Position was closed — remove from tier tracking
                continue
        
        # ═══════════════════════════════════════════════════════════════════
        # STEP 4B: TIER 2 — Full pipeline for CNC/swing positions
        # Kalman → TCAS → ILS → Health → ChatGPT → Trailing Stop
        # ═══════════════════════════════════════════════════════════════════
        
        chatgpt_queue = []  # Queue positions needing ChatGPT
        
        for symbol in list(tier2_positions.keys()):
            position = self.positions.get(symbol)
            if not position:
                continue
            
            # v5.3.2 FIX: Ghost position guard — skip positions closed externally
            if hasattr(self, '_closed_externally_today') and symbol in self._closed_externally_today:
                logger.info(f"   👻 {symbol}: Ghost position — skipping monitoring (closed externally)")
                # Clean up if still in self.positions somehow
                if symbol in self.positions:
                    del self.positions[symbol]
                continue
            
            # Get current price
            quote_key = f"NSE:{symbol}"
            quote_data = quotes.get(quote_key, {})
            current_price = quote_data.get('last_price', 0)

            if current_price <= 0:
                continue

            # v5.4.0 FIX: Persist live price through orchestrator
            direction = self._get_position_direction(position)
            extreme_updates = {'current_price': current_price}
            if direction == "SHORT":
                new_min = min(position.get("min_price", current_price), current_price)
                extreme_updates['min_price'] = new_min
            else:
                new_max = max(position.get("max_price", current_price), current_price)
                extreme_updates['max_price'] = new_max
            self._update_position(symbol, position, **extreme_updates)
            
            # ═══════════════════════════════════════════════════════════════
            # v4.13.0: MIS MANDATORY EXIT CHECK (for non-Phase5 MIS)
            # ═══════════════════════════════════════════════════════════════
            should_mis_exit, mis_reason = self._check_mis_mandatory_exit(position)
            if should_mis_exit:
                logger.warning(f"⏰ {symbol}: {mis_reason}")
                direction = self._get_position_direction(position)
                pnl_pct = self._calculate_pnl_pct(position, current_price)
                logger.info(f"   Direction: {direction} | P&L: {pnl_pct:+.2f}%")
                
                exit_success = self._execute_exit(symbol, mis_reason)
                if exit_success:
                    logger.info("   ✅ MIS mandatory exit successful")
                else:
                    logger.error("   ❌ MIS mandatory exit FAILED - manual intervention needed!")
                    if self.telegram:
                        self.telegram.send_message(
                            "⚠️ URGENT: MIS EXIT FAILED\n\n"
                            f"Stock: {symbol}\n"
                            f"Reason: {mis_reason}\n"
                            f"P&L: {pnl_pct:+.2f}%\n\n"
                            "⚠️ Manual exit required immediately!"
                        )
                continue
            
            # v4.14.0 FIX: Use real ATR stored at adoption, fallback to 2% estimate
            atr = position.get('atr', current_price * 0.02)
            
            # ═══════════════════════════════════════════════════════════════
            # v5.1.0 FIX: T+1 SETTLEMENT GTT RETRY
            # If position has no GTT and had T+1 pending shares, check if
            # shares have now settled and place GTT if so.
            # ═══════════════════════════════════════════════════════════════
            if not position.get('gtt_stop_id') and self.ENABLE_GTT:
                t1_qty = position.get('quantity_t1', 0)
                total_qty = position.get('quantity', 0)
                
                if t1_qty > 0 and total_qty > 0:
                    # Check broker for current settlement status
                    try:
                        holdings = self.kite.holdings() or []
                        for h in holdings:
                            if h.get('tradingsymbol') == symbol:
                                broker_t1 = h.get('t1_quantity', 0)
                                broker_settled = h.get('quantity', 0) - broker_t1
                                
                                if broker_settled > 0 and broker_t1 < t1_qty:
                                    # Shares have settled! Place GTT now
                                    logger.info(f"   🔄 {symbol}: T+1 shares settled ({broker_settled} settled, {broker_t1} T+1)")
                                    position['quantity_t1'] = broker_t1
                                    position['quantity_settled'] = broker_settled
                                    
                                    gtt_position = position.copy()
                                    gtt_position['quantity'] = broker_settled
                                    gtt_result = self._place_gtt_orders(symbol, gtt_position)
                                    
                                    if gtt_result and gtt_result.get('stop_id'):
                                        position['gtt_stop_id'] = gtt_result['stop_id']
                                        position['gtt_target_id'] = gtt_result.get('target_id')
                                        position['gtt_protected'] = True
                                        position['gtt_active'] = True
                                        logger.info(f"   ✅ {symbol}: GTT placed after T+1 settlement!")
                                        if self.telegram:
                                            self.telegram.send_message(
                                                f"🛡️ GTT PLACED: {symbol}\n\n"
                                                f"Shares settled: {broker_settled}\n"
                                                f"Stop: ₹{position.get('stop_price', 0):.2f}\n"
                                                f"Target: ₹{position.get('target_price', 0):.2f}"
                                            )
                                break
                    except Exception as e:
                        logger.debug(f"   {symbol}: Settlement check failed: {e}")
            
            # ═══════════════════════════════════════════════════════════════
            # v5.4.0: MAP Kalman update (6-state: price + RSI + volume)
            # Cross-coupled filter predicts price turns from RSI/volume dynamics
            # ═══════════════════════════════════════════════════════════════
            current_volume = quote_data.get('volume', 0)
            volume_ratio = self._calculate_volume_ratio(symbol, current_volume) if current_volume > 0 else 1.0
            current_rsi = position.get('phase4_tracking', {}).get('current_rsi', 50.0) or 50.0

            # Update Kalman MAP (price + RSI + volume)
            kalman_state = self._update_kalman(symbol, current_price, atr,
                                               rsi=current_rsi,
                                               volume_ratio=volume_ratio)

            # Log MAP signals when detected
            if kalman_state.inverse_v_top:
                logger.warning(f"   MAP INVERSE-V TOP: {symbol} "
                              f"(conf={kalman_state.exit_signal_confidence:.0%}, regime={kalman_state.regime})")
            if kalman_state.crash_accelerating:
                logger.warning(f"   MAP CRASH ACCEL: {symbol} "
                              f"(conf={kalman_state.exit_signal_confidence:.0%}, regime={kalman_state.regime})")
            if kalman_state.rsi_price_divergence:
                logger.info(f"   MAP DIVERGENCE: {symbol} RSI rising but price falling (bullish)")
            if kalman_state.volume_price_divergence:
                logger.info(f"   MAP DIVERGENCE: {symbol} volume active but price flat (breakout pending)")

            # ═══════════════════════════════════════════════════════════════
            # ENSEMBLE PREDICTION (advisory — does NOT trigger exits)
            # Record price snapshot + generate ensemble prediction
            # ═══════════════════════════════════════════════════════════════
            self._record_price_snapshot(symbol, current_price)
            self._update_ensemble_prediction(symbol, position, current_price, kalman_state)

            # ═══════════════════════════════════════════════════════════════
            # v4.15.0: Volume + Price (V+P) Signal Check
            # Runs every cycle — detects institutional buying/selling
            # ═══════════════════════════════════════════════════════════════
            vp_signal = self._check_volume_price_signal(symbol, position, current_price, quote_data)
            
            if vp_signal and vp_signal.get('action') == 'FORCE_CHATGPT':
                # Bearish conviction with volume — bypass 60-min cooldown
                # Force ChatGPT consultation by resetting last call time
                self.last_chatgpt_call[symbol] = datetime.min
                logger.warning(f"   🤖 V+P BEARISH: Forcing ChatGPT consultation for {symbol}")
            
            # ═══════════════════════════════════════════════════════════════
            # v4.11.0: Track prediction checkpoints every hour
            # ═══════════════════════════════════════════════════════════════
            self._check_prediction_checkpoint(symbol, kalman_state, current_price)
            
            # Calculate TCAS
            tcas_status = self._calculate_tcas_status(position, current_price, atr)
            
            # ═══════════════════════════════════════════════════════════════
            # v4.14.0 PERMANENT FIX: Product-aware TCAS for CNC holdings
            # CNC = delivery holdings meant for multi-day hold.
            # ALIM (panic exit) is inappropriate for CNC — they can survive
            # overnight. Downgrade to RA (consult ChatGPT) so the Truth
            # Matrix and multi-timeframe analysis get a say before exiting.
            # MIS positions keep instant ALIM (must close same day).
            # ═══════════════════════════════════════════════════════════════
            product = position.get('product', 'MIS')
            if product == 'CNC' and tcas_status.alert_level == TCASAlert.ALIM:
                # v5.5.0: CNC Shield enhanced — widen stop + check averaging
                if self._is_cnc_shield_active(position):  # v5.5.0
                    pnl_pct = self._calculate_pnl_pct(position, current_price)
                    if pnl_pct < 0:
                        logger.info(f"   🛡️ {symbol}: CNC SHIELD ALIM → WIDEN (not exit)")
                        self._cnc_shield_widen_stop(symbol, position, current_price, 'ALIM')
                        self._cnc_shield_check_averaging(symbol, position, current_price)
                        continue  # Skip ALIM entirely — shield handles it  # v5.5.0

                # Existing behavior: downgrade ALIM → RA for non-shielded CNC
                tcas_status.alert_level = TCASAlert.RA
                tcas_status.recommended_action = "CONSULT_CHATGPT"
                logger.info(f"   🛡️ {symbol}: CNC ALIM → RA (delivery holding, consulting ChatGPT)")
            
            # Check for TCAS ALIM - IMMEDIATE EXIT
            if tcas_status.alert_level == TCASAlert.ALIM:
                # Check if we've already tried to exit this position and failed
                attempts = self.failed_exit_attempts.get(symbol, 0)
                if attempts >= self.max_exit_attempts:
                    if attempts == self.max_exit_attempts:  # Log only once
                        logger.error(f"⚠️ {symbol}: TCAS ALIM triggered but exit failed {attempts} times!")
                        logger.error("   Manual intervention required - position may not be in Phase 3")
                        if self.telegram:
                            self.telegram.send_message(
                                "⚠️ MANUAL ACTION NEEDED\n\n"
                                f"Stock: {symbol}\n"
                                f"Issue: TCAS ALIM exit failed {attempts} times\n"
                                "Reason: Position not synced with Phase 3\n\n"
                                "Please exit manually or restart system"
                            )
                        self.failed_exit_attempts[symbol] = attempts + 1  # Increment to stop future logs
                    continue
                
                logger.warning(f"🔴 TCAS ALIM: {symbol} - IMMEDIATE EXIT (attempt {attempts + 1})")

                # v5.4.0: Structured TCAS ALIM notification
                if self.telegram and hasattr(self.telegram, 'notify_phase4_tcas_alert'):
                    try:
                        self.telegram.notify_phase4_tcas_alert(
                            symbol=symbol,
                            alert_level='ALIM',
                            distance_to_stop_atr=tcas_status.distance_to_stop_atr if hasattr(tcas_status, 'distance_to_stop_atr') else 0,
                            current_price=current_price,
                            stop_price=position.get('stop_price', 0),
                            action_taken='IMMEDIATE EXIT'
                        )
                    except Exception:
                        pass

                exit_success = self._execute_exit(symbol, ExitReason.TCAS_ALIM.value)
                if not exit_success:
                    self.failed_exit_attempts[symbol] = attempts + 1
                continue
            
            # ═══════════════════════════════════════════════════════════════
            # v4.8.1 NEW: TCAS RA SAFETY REFLEX
            # DANGEROUS ZONE (0.75-1.5 ATR from stop) - Auto-tighten stop immediately
            # Don't wait for ChatGPT (3-7 sec latency) - price could hit stop!
            # ═══════════════════════════════════════════════════════════════
            if tcas_status.alert_level == TCASAlert.RA:
                # v4.13.2: Cooldown to prevent spam (60 seconds)
                now = datetime.now()
                last_warning = self.tcas_ra_last_warning.get(symbol)
                if last_warning and (now - last_warning).seconds < 60:
                    continue  # Skip this warning, too soon
                self.tcas_ra_last_warning[symbol] = now

                # v5.5.0: CNC SHIELD — Widen stop instead of tighten for shielded positions
                if self._is_cnc_shield_active(position):  # v5.5.0
                    pnl_pct = self._calculate_pnl_pct(position, current_price)
                    if pnl_pct < 0:
                        logger.info(f"   🛡️ {symbol}: CNC SHIELD RA → WIDEN (not tighten)")
                        self._cnc_shield_widen_stop(symbol, position, current_price, 'RA')
                        self._cnc_shield_check_averaging(symbol, position, current_price)
                        continue  # Skip normal RA reflex which tightens  # v5.5.0
                    # If pnl >= 0, fall through to normal RA reflex (smart TCAS trails)

                logger.warning(f"⚠️ {symbol}: TCAS RA - SAFETY REFLEX TRIGGERED")
                
                entry_price = position.get('entry_price', current_price)
                current_stop = position.get('stop_price', entry_price * 0.98)
                
                # Only tighten if we're in profit or small loss
                if current_price > current_stop:
                    # Tighten stop to 50% between current stop and current price
                    # This locks in some profit/reduces loss while allowing recovery room
                    new_stop = current_stop + (current_price - current_stop) * 0.5
                    
                    logger.warning("   🔧 REFLEX: Auto-tightening stop")
                    logger.warning(f"      Old: ₹{current_stop:.2f}")
                    logger.warning(f"      New: ₹{new_stop:.2f}")
                    logger.warning(f"      Locked: ₹{new_stop - current_stop:.2f} gain")
                    
                    # Execute stop tightening (mechanical reflex - no ChatGPT wait)
                    try:
                        success = self._modify_gtt_stop(symbol, new_stop)
                        if success:
                            self._update_position(symbol, position, stop_price=new_stop)
                            # v5.1.0 FIX: Use setdefault to avoid KeyError for fresh positions
                            position.setdefault('phase4_tracking', {})['ra_reflex_triggered'] = True
                            position.setdefault('phase4_tracking', {})['ra_reflex_time'] = datetime.now().isoformat()
                            position.setdefault('phase4_tracking', {})['ra_old_stop'] = current_stop
                            position.setdefault('phase4_tracking', {})['ra_new_stop'] = new_stop
                            logger.info("   ✅ RA Reflex: Stop tightened successfully")
                        else:
                            # v5.1.0 FIX: Only warn once per session for T+1 positions without GTT
                            t1_qty = position.get('quantity_t1', 0)
                            if t1_qty > 0:
                                if not position.get('_t1_gtt_warned'):
                                    logger.warning(f"   ⏳ RA Reflex: {symbol} T+1 pending — GTT tighten deferred until settlement")
                                    position['_t1_gtt_warned'] = True
                            else:
                                logger.error("   ❌ RA Reflex: Failed to tighten stop")
                    except Exception as e:
                        logger.error(f"   ❌ RA Reflex error: {e}")
                
                # ChatGPT will still be consulted (added to queue below)
                # This reflex is IMMEDIATE safety, ChatGPT consultation is PARALLEL

                # ═══════════════════════════════════════════════════════════
                # ISSUE-15: EARLY Phase 6 pivot signal
                # SHORT + RA + losing + Kalman confirms price rising →
                # Send to Phase 6 NOW, while equity is still open.
                # Phase 6 can monitor and build its strategy proactively.
                # One signal per position (dedup via tcas_pivot_early_signaled).
                # ═══════════════════════════════════════════════════════════
                if (
                    self.phase6 is not None
                    and direction == 'SHORT'
                    and symbol not in self.tcas_pivot_early_signaled
                ):
                    try:
                        pnl_now = self._calculate_pnl_pct(position, current_price)
                        kalman_data = position.get('phase4_tracking', {}).get('kalman_state', {})
                        kal_vel = kalman_data.get('velocity', 0)
                        kal_acc = kalman_data.get('acceleration', 0)
                        now_time = datetime.now().time()

                        if (
                            pnl_now < 0
                            and kal_vel > 0.3
                            and kal_acc >= 0
                            and now_time < dt_time(13, 30)
                        ):
                            eq_entry = position.get('entry_price', 0)
                            eq_stop  = position.get('stop_price', 0)
                            atr_val  = position.get('atr', current_price * 0.02)
                            dist_to_stop = eq_stop - current_price   # SHORT: stop above current
                            dist_atr = dist_to_stop / atr_val if atr_val > 0 else 0

                            early_signal = {
                                'symbol': symbol,
                                'confirmed_direction': 'BULLISH',
                                'status': 'EARLY_WARNING',       # equity still OPEN
                                'signal_time': datetime.now(),
                                'signal_price': current_price,
                                'equity_entry': eq_entry,
                                'equity_stop': eq_stop,
                                'atr': atr_val,
                                'kalman_velocity': kal_vel,
                                'kalman_acceleration': kal_acc,
                                'tcas_alert': 'RA',
                                'equity_pnl': pnl_now,
                                'equity_still_open': True,
                            }
                            self.tcas_pivot_early_signaled.add(symbol)
                            logger.info(
                                f"📡 TCAS PIVOT EARLY: {symbol} SHORT RA+loss "
                                f"(pnl={pnl_now:.1f}%, vel={kal_vel:.2f}) → "
                                f"BULLISH early warning → Phase 6 (equity still open)"
                            )

                            # ── Phase 4 Telegram: full alert with all trigger values ──
                            if self.telegram:
                                try:
                                    acc_label = (f"+{kal_acc:.3f} (building)"
                                                 if kal_acc > 0 else f"{kal_acc:.3f} (flat)")
                                    self.telegram.send_message(
                                        f"📡 TCAS PIVOT — EARLY WARNING\n"
                                        f"{'='*32}\n"
                                        f"Symbol : {symbol}  (SHORT — LOSING)\n"
                                        f"Time   : {now_time.strftime('%H:%M:%S')}\n"
                                        f"\n"
                                        f"WHY TRIGGERED:\n"
                                        f"  • TCAS RA — price within 1.5 ATR of stop\n"
                                        f"  • Position in loss — direction wrong\n"
                                        f"  • Kalman confirms price rising (BULLISH)\n"
                                        f"\n"
                                        f"POSITION:\n"
                                        f"  Entry  : ₹{eq_entry:,.2f}\n"
                                        f"  Current: ₹{current_price:,.2f}  ({pnl_now:+.2f}%)\n"
                                        f"  Stop   : ₹{eq_stop:,.2f}  ({dist_to_stop:.2f} away)\n"
                                        f"  ATR    : ₹{atr_val:.2f}  ({dist_atr:.2f} ATR to stop)\n"
                                        f"\n"
                                        f"KALMAN MOMENTUM:\n"
                                        f"  Velocity    : +{kal_vel:.3f}/min  (price rising)\n"
                                        f"  Acceleration: {acc_label}\n"
                                        f"  Confirms    : BULLISH momentum\n"
                                        f"\n"
                                        f"ACTION:\n"
                                        f"  Equity still OPEN — passing to Phase 6 early\n"
                                        f"  Phase 6 will analyse CALL options now\n"
                                        f"  (advisory plan to follow in next message)"
                                    )
                                except Exception as _te:
                                    logger.warning(f"   TCAS pivot Telegram failed: {_te}")

                            self.phase6.on_tcas_direction_signal(early_signal)
                    except Exception as e:
                        logger.error(f"   TCAS pivot early signal failed for {symbol}: {e}")

            # ═══════════════════════════════════════════════════════════════
            # v5.3.3: SMART TCAS for CNC — Lock profit at activation %
            # Same philosophy as Phase 5 MIS Smart TCAS:
            #   1. Price hits +0.7% → TCAS activates, lock breakeven
            #   2. Trail: peak - 0.5% (ratchets up, never down)
            #   3. Kalman decel → predictive exit catches the rest
            # ═══════════════════════════════════════════════════════════════
            if position.get('smart_tcas_enabled', False):
                entry_price = position.get('entry_price', 0)
                if entry_price > 0:
                    pnl_pct = ((current_price - entry_price) / entry_price) * 100
                    activation_pct = position.get('tcas_activation_pct', 0.7)
                    trail_pct = position.get('tcas_trail_pct', 0.5)
                    
                    if not position.get('tcas_activated', False):
                        # CHECK: Has price crossed activation threshold?
                        if pnl_pct >= activation_pct:
                            self._update_position(symbol, position,
                                                  tcas_activated=True,
                                                  tcas_peak_price=current_price,
                                                  stop_price=entry_price)
                            # Lock breakeven: move stop to entry price
                            old_stop = position.get('stop_price', 0)
                            logger.info(f"   ✈️ {symbol}: CNC SMART TCAS ACTIVATED at +{pnl_pct:.2f}%")
                            logger.info(f"      Breakeven locked: stop ₹{old_stop:.2f} → ₹{entry_price:.2f}")
                            logger.info(f"      Now trailing: peak - {trail_pct}%")
                            
                            # Update GTT to breakeven
                            try:
                                self._modify_gtt_stop(symbol, entry_price)
                            except Exception as e:
                                logger.error(f"      GTT update failed: {e}")
                            
                            if self.telegram:
                                self.telegram.send_message(
                                    f"✈️ CNC SMART TCAS ACTIVATED\n\n"
                                    f"Stock: {symbol}\n"
                                    f"P&L: +{pnl_pct:.2f}%\n"
                                    f"Breakeven LOCKED at ₹{entry_price:.2f}\n"
                                    f"Trailing: peak - {trail_pct}%"
                                )
                    else:
                        # TCAS already activated — trail the peak
                        peak = position.get('tcas_peak_price', current_price)
                        if current_price > peak:
                            self._update_position(symbol, position, tcas_peak_price=current_price)
                            peak = current_price
                        
                        # Calculate trailing stop
                        trail_stop = peak * (1 - trail_pct / 100)
                        
                        # Only ratchet UP, never down
                        current_stop = position.get('stop_price', entry_price)
                        if trail_stop > current_stop:
                            self._update_position(symbol, position, stop_price=trail_stop)
                            logger.info(f"   ✈️ {symbol}: CNC trail ratchet: "
                                       f"peak ₹{peak:.2f} → stop ₹{trail_stop:.2f} "
                                       f"(was ₹{current_stop:.2f})")
                            try:
                                self._modify_gtt_stop(symbol, trail_stop)
                            except Exception as e:
                                logger.error(f"      GTT trail update failed: {e}")
                        
                        # Check if trailing stop hit
                        if current_price <= current_stop and current_stop > entry_price:
                            profit_locked = ((current_stop - entry_price) / entry_price) * 100
                            logger.warning(f"   ✈️ {symbol}: CNC SMART TCAS TRAIL EXIT at ₹{current_price:.2f}")
                            logger.warning(f"      Profit locked: +{profit_locked:.2f}%")
                            exit_success = self._execute_exit(symbol, "CNC_SMART_TCAS_TRAIL")
                            if exit_success and self.telegram:
                                self.telegram.send_message(
                                    f"✈️ CNC SMART TCAS EXIT\n\n"
                                    f"Stock: {symbol}\n"
                                    f"Peak: ₹{peak:.2f}\n"
                                    f"Exit: ₹{current_price:.2f}\n"
                                    f"Profit: +{profit_locked:.2f}%"
                                )
                            continue
            
            # ═══════════════════════════════════════════════════════════════
            # v4.8.0 NEW: PREDICTIVE STOP CHECK
            # Uses Kalman velocity/acceleration to exit BEFORE stop is hit
            # ═══════════════════════════════════════════════════════════════
            if self.predictive_stop and tcas_status.alert_level != TCASAlert.ALIM:
                entry_price = position.get('entry_price', current_price)
                stop_price = position.get('stop_price', entry_price * 0.98)
                current_rsi = position.get('phase4_tracking', {}).get('current_rsi')
                
                predictive_signal = self.predictive_stop.should_exit(
                    symbol=symbol,
                    kalman_state=kalman_state.to_dict() if kalman_state else {},
                    current_price=current_price,
                    entry_price=entry_price,
                    stop_loss_price=stop_price,
                    current_rsi=current_rsi
                )
                
                # Log predictive stop analysis (ALWAYS - for visibility)
                logger.info(f"   🔮 {symbol} Predictive Stop: {predictive_signal.reason.value} "
                           f"(Exit={predictive_signal.should_exit}, "
                           f"Conf={predictive_signal.confidence:.0%}, "
                           f"Profit={predictive_signal.profit_pct:.1f}%)")
                
                if predictive_signal.should_exit:
                    logger.warning(f"🔮 PREDICTIVE EXIT TRIGGERED: {symbol}")
                    logger.warning(f"   Reason: {predictive_signal.reason.value}")
                    logger.warning(f"   Details: {predictive_signal.details}")
                    
                    # Execute predictive exit
                    exit_success = self._execute_exit(
                        symbol, 
                        f"PREDICTIVE_STOP: {predictive_signal.reason.value}"
                    )
                    
                    if exit_success and self.telegram:
                        self.telegram.send_message(
                            f"🔮 PREDICTIVE EXIT\\n\\n"
                            f"Symbol: {symbol}\\n"
                            f"Reason: {predictive_signal.reason.value}\\n"
                            f"Details: {predictive_signal.details}\\n"
                            f"Confidence: {predictive_signal.confidence:.0%}\\n"
                            f"Profit Locked: {predictive_signal.profit_pct:.1f}%"
                        )
                    continue  # Skip to next position
            
            # Calculate ILS
            ils_status = self._calculate_ils_status(position, current_price)
            
            # ═══════════════════════════════════════════════════════════════
            # v4.9.0 NEW: Fibonacci Exit Strategy Check
            # When position is profitable and approaching target, calculate
            # AI-optimized exit levels using Fibonacci retracements
            # ═══════════════════════════════════════════════════════════════
            should_calc_fib, fib_reason = self._should_calculate_fibonacci_exit(
                symbol, position, ils_status
            )
            
            if should_calc_fib:
                logger.info(f"📐 {symbol}: Fibonacci exit check triggered ({fib_reason})")
                fib_analysis = self._calculate_fibonacci_exit_levels(symbol, position)
                if fib_analysis:
                    self._execute_fibonacci_recommendation(symbol, position, fib_analysis)
            
            # Calculate Health
            health_score = self._calculate_health_score(
                position, current_price, tcas_status, ils_status, kalman_state
            )
            
            # Update tracking data
            if 'phase4_tracking' not in position:
                position['phase4_tracking'] = {}
            
            position['phase4_tracking'].update({
                'tcas_status': tcas_status.to_dict(),
                'ils_status': ils_status.to_dict(),
                'health_score': health_score.to_dict(),
                'kalman_state': kalman_state.to_dict() if kalman_state else {},
                'last_update': datetime.now().isoformat()
            })
            
            # Check if ChatGPT consultation needed
            should_call, reason = self._should_consult_chatgpt(
                symbol, position, tcas_status, health_score
            )
            
            if should_call:
                chatgpt_queue.append((symbol, reason, position, tcas_status, ils_status, health_score, kalman_state))
            
            # Update trailing stop if ILS active
            if ils_status.trailing_active:
                self._update_trailing_stop(symbol, position, ils_status)
            
            # v4.13.0: Direction-aware P&L for logging
            entry_price = position.get('entry_price', current_price)
            pnl_pct = self._calculate_pnl_pct(position, current_price)
            
            # v4.8.0: Enhanced logging to show ALL new intelligence components
            logger.info(
                f"📊 {symbol}: ₹{current_price:.2f} | P&L: {pnl_pct:+.2f}% | "
                f"TCAS: {tcas_status.alert_level.value} | "
                f"ILS: {ils_status.landing_phase.value} | "
                f"Health: {health_score.total_score:.0f}/100"
            )
            
            # Show health score breakdown (v4.8.0: includes prediction)
            components = health_score.component_scores
            logger.info(
                f"   💚 Health Components: P&L={components.get('pnl', 0):.0f} | "
                f"Mom={components.get('momentum', 0):.0f} | "
                f"TCAS={components.get('tcas', 0):.0f} | "
                f"Time={components.get('time', 0):.0f} | "
                f"Pred={components.get('prediction', 0):.0f}"
            )
            
            # Show Kalman prediction if available (v4.8.0)
            if kalman_state and hasattr(kalman_state, 'prediction_15min') and kalman_state.prediction_15min:
                pred_change = ((kalman_state.prediction_15min - current_price) / current_price) * 100
                logger.info(
                    f"   🔮 Kalman: Vel={kalman_state.velocity:.3f} | "
                    f"Accel={kalman_state.acceleration:.3f} | "
                    f"15min Pred=₹{kalman_state.prediction_15min:.2f} ({pred_change:+.2f}%)"
                )
        
        # ═══════════════════════════════════════════════════════════════════
        # STEP 4C: TIER 3 — Phase 8 Momentum positions (TCAS only)
        # v8.0.0: Wider TCAS params, no ILS/ChatGPT, multi-day hold
        # ═══════════════════════════════════════════════════════════════════

        tier3_positions = self._get_tier3_positions()
        if tier3_positions:
            logger.debug(f"   PH8 TIER 3: Processing {len(tier3_positions)} momentum position(s)")

            for symbol, position in tier3_positions.items():
                quote_key = f"NSE:{symbol}"
                quote_data = quotes.get(quote_key, {})
                current_price = quote_data.get('last_price', 0)

                if current_price <= 0:
                    continue

                self._update_position(symbol, position, current_price=current_price)

                # Run Tier 3 TCAS check
                exited = self._run_tier3_momentum_check(symbol, position, current_price)
                if exited:
                    continue

        # ═══════════════════════════════════════════════════════════════════
        # STEP 5: Process ChatGPT queue
        # ═══════════════════════════════════════════════════════════════════

        for symbol, reason, position, tcas, ils, health, kalman in chatgpt_queue:
            data_package = self._build_chatgpt_data_package(
                symbol, position, tcas, ils, health, kalman
            )
            
            decision = self._consult_chatgpt(symbol, data_package, reason)
            
            if decision:
                self._execute_chatgpt_decision(symbol, decision)
        
        # ═══════════════════════════════════════════════════════════════════
        # STEP 6: Save state
        # ═══════════════════════════════════════════════════════════════════
        
        self._save_positions()
        
        cycle_time = (datetime.now() - cycle_start).total_seconds()
        t1_count = len(tier1_positions)
        t2_count = len(tier2_positions)
        t3_count = len(tier3_positions) if tier3_positions else 0
        logger.debug(f"Monitoring cycle completed in {cycle_time:.2f}s "
                     f"(T1:{t1_count} + T2:{t2_count} + T3:{t3_count})")
    
    def _process_emergency_exits(self):
        """Process emergency exit queue"""
        while self.emergency_exit_queue:
            symbol = self.emergency_exit_queue.pop(0)
            self._execute_exit(symbol, ExitReason.TCAS_ALIM.value)
        
        self.tcas_alim_flag = False
    
    def _update_trailing_stop(self, symbol: str, position: Dict, ils: ILSStatus):
        """Update trailing stop based on ILS status"""
        if not ils.trailing_active or ils.trailing_stop <= 0:
            return
        
        current_stop = position.get('stop_price', 0)
        
        # Only move stop UP (for longs)
        if ils.trailing_stop > current_stop:
            # Update GTT if enabled
            if self.ENABLE_GTT and position.get('gtt_active'):
                self._modify_gtt_stop(symbol, ils.trailing_stop)
            
            self._update_position(symbol, position,
                                  stop_price=ils.trailing_stop,
                                  trailing_stop=ils.trailing_stop)

    # ═══════════════════════════════════════════════════════════════════════════
    # SPECIAL TIME CHECKS
    # ═══════════════════════════════════════════════════════════════════════════
    
    def run_landing_probability_check(self):
        """
        Run at 14:30 - analyze if positions can reach target today.
        """
        logger.info("🛬 Running Landing Probability Analysis...")
        
        for symbol, position in list(self.positions.items()):
            # Build analysis data
            current_price = position.get('current_price', 0)
            target_price = position.get('target_price', 0)
            
            if current_price <= 0 or target_price <= 0:
                continue
            
            distance_to_target_pct = ((target_price - current_price) / current_price) * 100
            
            # Get Kalman prediction
            kalman = self._get_kalman_state(symbol)
            velocity = kalman.velocity if kalman else 0
            
            # Calculate estimated time to target
            if velocity > 0:
                price_needed = target_price - current_price
                est_minutes = abs(price_needed / velocity) if velocity != 0 else 999
            else:
                est_minutes = 999
            
            # Time remaining
            now = datetime.now()
            market_close = now.replace(hour=15, minute=30)
            minutes_remaining = (market_close - now).total_seconds() / 60
            
            can_reach_today = est_minutes < minutes_remaining * 0.8  # 80% buffer
            
            logger.info(f"   {symbol}: {distance_to_target_pct:.1f}% to target, "
                       f"Est. {est_minutes:.0f} min, {minutes_remaining:.0f} min remaining, "
                       f"Can reach: {can_reach_today}")
            
            # Consult ChatGPT for landing decision
            if self.chatgpt:
                data_package = self._build_chatgpt_data_package(
                    symbol, position,
                    TCASStatus(), 
                    self._calculate_ils_status(position, current_price),
                    HealthScore(),
                    kalman
                )
                
                decision = self._consult_chatgpt(symbol, data_package, "LANDING_PROBABILITY")
                if decision:
                    self._execute_chatgpt_decision(symbol, decision)
    
    def handle_mis_cutoff(self):
        """Handle MIS positions before cutoff (15:15)"""
        logger.info("⏰ Checking MIS positions for cutoff...")
        
        for symbol, position in list(self.positions.items()):
            if position.get('product') == 'MIS':
                logger.warning(f"   {symbol}: MIS position - must exit or convert")
                
                # Try to convert to CNC if holding overnight
                if position.get('overnight_hold'):
                    try:
                        # Convert to CNC
                        self.kite.convert_position(
                            exchange="NSE",
                            tradingsymbol=symbol,
                            transaction_type=self.kite.TRANSACTION_TYPE_BUY,
                            position_type="day",
                            quantity=position.get('quantity', 0),
                            old_product=self.kite.PRODUCT_MIS,
                            new_product=self.kite.PRODUCT_CNC
                        )
                        position['product'] = 'CNC'
                        logger.info(f"   ✅ {symbol}: Converted MIS → CNC")
                    except Exception as e:
                        logger.error(f"   ❌ Conversion failed: {e}")
                        # Must exit
                        self._execute_exit(symbol, ExitReason.MIS_CUTOFF.value)
                else:
                    # Exit MIS position
                    self._execute_exit(symbol, ExitReason.MIS_CUTOFF.value)
    
    def handle_market_close(self):
        """Handle end of day - close all MIS positions"""
        logger.info("🔔 Market Close Handler")
        
        for symbol, position in list(self.positions.items()):
            if position.get('product') == 'MIS':
                logger.warning(f"   Force closing MIS: {symbol}")
                self._execute_exit(symbol, ExitReason.MARKET_CLOSE.value)

        # Flush innovation log + save Kalman calibrations at market close
        try:
            from kalman_filter import get_innovation_logger
            get_innovation_logger().flush()
        except Exception:
            pass

        # Save converged Q/R for warm start next session (Phase D)
        for sym in list(self.kalman_filters.keys()):
            self._save_kalman_calibration(sym)

        # Save final state
        self._save_positions()
        
        # Send EOD summary
        self._send_eod_summary()
    
    def _send_eod_summary(self):
        """Send end of day summary via Telegram"""
        if not self.telegram:
            return
        
        # Calculate daily stats
        total_pnl = 0
        positions_closed = 0
        positions_held = len(self.positions)
        
        summary = (
            f"📊 END OF DAY SUMMARY\n"
            f"{'=' * 30}\n\n"
            f"Positions Closed: {positions_closed}\n"
            f"Positions Held Overnight: {positions_held}\n"
            f"Daily P&L: {total_pnl:+.2f}%\n\n"
            f"System Status: ✅ Autonomous"
        )
        
        self.telegram.send_message(summary)

    # ═══════════════════════════════════════════════════════════════════════════
    # UTILITY METHODS
    # ═══════════════════════════════════════════════════════════════════════════
    
    def has_open_positions(self) -> bool:
        """Check if there are open positions"""
        return len(self.positions) > 0
    
    # ═══════════════════════════════════════════════════════════════════════════
    # v4.11.0 TRUTH PREDICTOR HELPER METHODS
    # ═══════════════════════════════════════════════════════════════════════════
    
    def _record_entry_predictions(self, symbol: str, position: Dict):
        """
        v4.11.0: Generate and record truth predictions at position entry.
        
        Called from _add_manual_position after Kalman initialization.
        Records predictions to decision_history for accuracy tracking.
        """
        if not self.truth_predictor or not self.decision_tracker:
            return
        
        try:
            entry_price = position.get('entry_price', 0)
            if entry_price <= 0:
                return
            
            # Get Kalman state
            kalman_state = {}
            if symbol in self.kalman_filters:
                kalman_state = self.kalman_filters[symbol].get_state()
            
            # Fetch OHLCV data for analysis
            ohlcv_data = self._fetch_ohlcv_for_truth_predictor(symbol)
            if not ohlcv_data or len(ohlcv_data.get('close', [])) < 20:
                logger.warning(f"   ⚠️ {symbol}: Insufficient OHLCV data for TruthPredictor")
                return
            
            # Generate truth matrix
            truth_matrix = self.truth_predictor.generate_truth_matrix(
                symbol=symbol,
                entry_price=entry_price,
                kalman_state=kalman_state,
                ohlcv_data=ohlcv_data
            )
            
            # Record to decision_history
            self.decision_tracker.record_prediction(
                symbol=symbol,
                entry_price=entry_price,
                predictions=truth_matrix.predictions,
                indicators=truth_matrix.indicators,
                targets=truth_matrix.targets,
                confidence=truth_matrix.overall_confidence
            )
            
            # Store in position for later accuracy tracking
            position['truth_matrix'] = truth_matrix.to_dict()
            
            # Initialize checkpoint tracking
            self.last_checkpoint_time[symbol] = datetime.now()
            
            logger.info(f"   🔮 {symbol}: TruthPredictor predictions recorded")
            logger.info(f"      Direction: {truth_matrix.direction} | Confidence: {truth_matrix.overall_confidence:.0%}")
            logger.info(f"      15min: ₹{truth_matrix.predictions.get('15min', {}).get('value', 0):.2f}")
            
        except Exception as e:
            logger.error(f"   ⚠️ {symbol}: TruthPredictor error: {e}")
    
    def _fetch_ohlcv_for_truth_predictor(self, symbol: str, periods: int = 50) -> Dict[str, List[float]]:
        """
        Fetch OHLCV data for TruthPredictor analysis.
        
        Returns:
            Dictionary with 'open', 'high', 'low', 'close', 'volume' lists
        """
        try:
            # Fetch 15-minute candles for last N periods
            from datetime import datetime, timedelta
            
            instrument_token = self._get_instrument_token(symbol)
            if not instrument_token:
                return {}
            
            to_date = datetime.now()
            from_date = to_date - timedelta(days=5)  # 5 days of data
            
            data = self.kite.historical_data(
                instrument_token=instrument_token,
                from_date=from_date,
                to_date=to_date,
                interval='15minute'
            )
            
            if not data:
                return {}
            
            # Extract OHLCV into separate lists
            return {
                'open': [d['open'] for d in data[-periods:]],
                'high': [d['high'] for d in data[-periods:]],
                'low': [d['low'] for d in data[-periods:]],
                'close': [d['close'] for d in data[-periods:]],
                'volume': [d['volume'] for d in data[-periods:]]
            }
            
        except Exception as e:
            logger.debug(f"OHLCV fetch error for {symbol}: {e}")
            return {}
    
    def _get_instrument_token(self, symbol: str) -> Optional[int]:
        """Get instrument token for a symbol."""
        try:
            # Try to get from config's instrument list
            instruments = getattr(self.config, 'INSTRUMENTS', {})
            if symbol in instruments:
                return instruments[symbol]
            
            # Fallback: query from Kite
            instruments = self.kite.instruments('NSE')
            for inst in instruments:
                if inst['tradingsymbol'] == symbol:
                    return inst['instrument_token']
            
            return None
        except Exception as e:
            logger.debug(f"Instrument token error for {symbol}: {e}")
            return None
    
    def _check_prediction_checkpoint(self, symbol: str, kalman_state: Dict, current_price: float):
        """
        v4.11.0: Check if it's time to add a prediction checkpoint.
        
        Called every monitoring cycle, adds checkpoint every hour.
        """
        if not self.decision_tracker or not self.truth_predictor:
            return
        
        try:
            last_checkpoint = self.last_checkpoint_time.get(symbol)
            
            # First checkpoint or interval elapsed?
            if last_checkpoint is None:
                return  # No initial prediction recorded
            
            minutes_elapsed = (datetime.now() - last_checkpoint).total_seconds() / 60
            
            if minutes_elapsed >= self.checkpoint_interval_minutes:
                # Determine checkpoint type
                if minutes_elapsed < 120:
                    checkpoint_type = '1H'
                elif minutes_elapsed < 180:
                    checkpoint_type = '2H'
                else:
                    checkpoint_type = 'EOD'
                
                # Get checkpoint data from TruthPredictor
                checkpoint_data = self.truth_predictor.get_checkpoint_data(kalman_state, current_price)
                
                # Record to decision_history
                self.decision_tracker.add_prediction_checkpoint(
                    symbol=symbol,
                    checkpoint_type=checkpoint_type,
                    actual_price=current_price
                )
                
                # Update last checkpoint time
                self.last_checkpoint_time[symbol] = datetime.now()
                
                logger.debug(f"   📊 {symbol}: Prediction checkpoint recorded ({checkpoint_type})")
                
        except Exception as e:
            logger.debug(f"Checkpoint error for {symbol}: {e}")
    
    def _track_prediction_accuracy(self, symbol: str, exit_price: float, position: Dict):
        """
        v4.11.0: Track prediction accuracy at position exit.
        
        Called from _execute_exit after recording outcome.
        """
        if not self.decision_tracker or not self.truth_predictor:
            return
        
        try:
            # Get original truth matrix from position
            truth_matrix = position.get('truth_matrix', {})
            predictions = truth_matrix.get('predictions', {})
            entry_price = position.get('entry_price', 0)
            
            if not predictions or entry_price <= 0:
                return
            
            # Build actual prices dict
            actual_prices = {
                'entry': entry_price,
                'exit': exit_price
                # Note: We don't have actual 15min/30min prices stored
                # This will be enhanced in future versions
            }
            
            # Calculate accuracy
            accuracy = self.truth_predictor.calculate_prediction_accuracy(predictions, actual_prices)
            
            # Track with decision_history
            self.decision_tracker.track_prediction_accuracy(
                symbol=symbol,
                exit_price=exit_price,
                exit_time=datetime.now()
            )
            
            # Clean up
            if symbol in self.last_checkpoint_time:
                del self.last_checkpoint_time[symbol]
            
            logger.info(f"   📊 {symbol}: Prediction accuracy tracked")
            
        except Exception as e:
            logger.debug(f"Accuracy tracking error for {symbol}: {e}")
    
    def _generate_and_log_flight_plan(self, symbol: str, position: Dict):
        """
        v4.12.0: Generate comprehensive multi-timeframe flight plan at entry.
        
        Creates detailed analysis across 5 timeframes with 8 indicators each.
        Logs the visual flight plan and stores it in position for ChatGPT context.
        """
        if not self.flight_plan_generator:
            logger.debug(f"   ⚠️ FlightPlanGenerator not available for {symbol}")
            return
        
        try:
            current_price = position.get('current_price', position.get('entry_price', 0))
            entry_price = position.get('entry_price', 0)
            stop_price = position.get('stop_price', entry_price * 0.98)
            target_price = position.get('target_price', entry_price * 1.03)
            
            # Get instrument token
            instrument_token = self._get_instrument_token(symbol)
            
            logger.info(f"   🔮 Generating multi-timeframe flight plan for {symbol}...")
            
            # Generate flight plan
            flight_plan = self.flight_plan_generator.generate(
                symbol=symbol,
                current_price=current_price,
                entry_price=entry_price,
                stop_price=stop_price,
                target_price=target_price,
                instrument_token=instrument_token
            )
            
            # Store in position for ChatGPT context
            position['flight_plan'] = flight_plan.to_dict()
            
            # Update position in orchestrator if available
            if self.orchestrator and hasattr(self.orchestrator, 'positions'):
                if symbol in self.orchestrator.positions:
                    self.orchestrator.positions[symbol]['flight_plan'] = flight_plan.to_dict()
            
            # Log the visual flight plan
            flight_plan_log = flight_plan.format_for_log()
            for line in flight_plan_log.split('\n'):
                logger.info(line)
            
            logger.info(f"   ✅ Flight plan generated: {flight_plan.overall_truth_score:.0f}% {flight_plan.overall_direction}")
            logger.info(f"   💡 Recommended action: {flight_plan.recommended_action} (Confidence: {flight_plan.action_confidence:.0f}%)")
            
            # Send summary to Telegram
            if self.telegram:
                tf_summary = []
                for tf, score in flight_plan.truth_scores.items():
                    emoji = "🟢" if score >= 65 else ("🟡" if score >= 40 else "🔴")
                    tf_summary.append(f"{emoji} {tf}: {score:.0f}%")
                
                self.telegram.send_message(
                    f"🔮 <b>FLIGHT PLAN: {symbol}</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                    f"📊 <b>Truth Score: {flight_plan.overall_truth_score:.0f}% {flight_plan.overall_direction}</b>\n\n"
                    f"<b>By Timeframe:</b>\n" + "\n".join(tf_summary) + "\n\n"
                    f"<b>Decision Matrix:</b>\n"
                    f"• Exit now? {flight_plan.decision_matrix.get('Exit now?', {}).get('answer', 'UNKNOWN')}\n"
                    f"• Hold overnight? {flight_plan.decision_matrix.get('Hold overnight?', {}).get('answer', 'UNKNOWN')}\n"
                    f"• Add position? {flight_plan.decision_matrix.get('Add to position?', {}).get('answer', 'UNKNOWN')}\n\n"
                    f"💡 <b>{flight_plan.recommended_action}</b>: {flight_plan.strategy_note}"
                )
            
        except Exception as e:
            logger.warning(f"   ⚠️ Flight plan generation failed for {symbol}: {e}")
            import traceback
            logger.debug(traceback.format_exc())
    
    def _get_flight_plan_for_chatgpt(self, symbol: str) -> Optional[Dict]:
        """
        v4.12.0: Get flight plan summary for ChatGPT consultation.
        
        Returns condensed flight plan data that helps ChatGPT make decisions.
        """
        position = self.positions.get(symbol)
        if not position:
            return None
        
        flight_plan_data = position.get('flight_plan')
        if not flight_plan_data:
            return None
        
        # Condense for ChatGPT context
        return {
            'overall_truth_score': flight_plan_data.get('overall_truth_score', 50),
            'overall_direction': flight_plan_data.get('overall_direction', 'MIXED'),
            'timeframe_scores': flight_plan_data.get('truth_scores', {}),
            'recommended_action': flight_plan_data.get('recommended_action', 'HOLD'),
            'action_confidence': flight_plan_data.get('action_confidence', 50),
            'strategy_note': flight_plan_data.get('strategy_note', ''),
            'decision_matrix': flight_plan_data.get('decision_matrix', {}),
            'predictions': flight_plan_data.get('predictions', {}),
            'bullish_triggers': flight_plan_data.get('bullish_triggers', []),
            'bearish_triggers': flight_plan_data.get('bearish_triggers', [])
        }

    # ═══════════════════════════════════════════════════════════════════════════
    # v5.5.0: CNC LONG SHIELD — Upgraded TCAS for CNC LONG Positions
    # "Land the Plane in Green Zone — Never Exit in Red"
    # Same Phase 4 loop, smarter responses for CNC LONG held 1+ days
    # ═══════════════════════════════════════════════════════════════════════════

    def _is_cnc_shield_active(self, position: Dict) -> bool:  # v5.5.0
        """Check if CNC Long Shield is active for this position."""
        if not getattr(self.config, 'CNC_SHIELD_ENABLED', False):
            return False
        if position.get('product', 'CNC') != 'CNC':
            return False
        # Direction check: only LONG positions
        direction = self._get_position_direction(position)
        if direction != 'LONG':
            return False
        # Hold days check
        entry_time_str = position.get('entry_time', '')
        if entry_time_str:
            try:
                entry_date = datetime.fromisoformat(entry_time_str).date()
                hold_days = (datetime.now().date() - entry_date).days
                return hold_days >= getattr(self.config, 'CNC_SHIELD_MIN_HOLD_DAYS', 1)
            except:
                return False
        return False

    def _cnc_shield_widen_stop(self, symbol: str, position: Dict,  # v5.5.0
                                current_price: float, trigger: str):
        """CNC Shield: WIDEN (lower) stop to give recovery room."""
        entry_price = position.get('entry_price', current_price)
        current_stop = position.get('stop_price', entry_price * 0.98)
        atr = position.get('atr', current_price * 0.02)

        if trigger in ('ALIM', 'EXIT_BLOCKED'):
            widen_factor = getattr(self.config, 'CNC_SHIELD_WIDEN_ATR_ALIM', 1.5)
        else:
            widen_factor = getattr(self.config, 'CNC_SHIELD_WIDEN_ATR_RA', 1.0)

        new_stop = current_stop - (atr * widen_factor)

        # Floor: never below entry × (1 - max_drawdown%)
        max_dd = getattr(self.config, 'CNC_SHIELD_MAX_DRAWDOWN_PCT', 15)
        stop_floor = entry_price * (1 - max_dd / 100)
        new_stop = max(new_stop, stop_floor)

        # Only widen (lower), never tighten
        if new_stop < current_stop:
            try:
                success = self._modify_gtt_stop(symbol, new_stop)
                if success:
                    position['stop_price'] = new_stop
                    logger.info(f"   🛡️ SHIELD WIDEN: {symbol} stop ₹{current_stop:.2f} → ₹{new_stop:.2f} (trigger: {trigger})")
            except Exception as e:
                logger.error(f"   ❌ Shield widen failed: {e}")
        else:
            logger.info(f"   🛡️ SHIELD: {symbol} stop already widened to ₹{current_stop:.2f}")

    def _cnc_shield_check_averaging(self, symbol: str, position: Dict,  # v5.5.0
                                     current_price: float):
        """
        CNC Shield: Check if smart averaging should execute.

        Uses EXISTING TruthMatrix supports (Fib, BB, VWAP) already
        calculated by Phase 4 every cycle. No new indicator calculations.

        Loop behavior: This method is called every TCAS cycle while
        the position is in red. It checks conditions each time and
        only averages when ALL criteria are met.
        """
        entry_price = position.get('entry_price', current_price)

        # 1. Minimum drop check
        drop_pct = ((entry_price - current_price) / entry_price) * 100
        min_drop = getattr(self.config, 'CNC_AVG_DROP_TRIGGER_PCT', 3.0)
        if drop_pct < min_drop:
            return  # Not enough drop to warrant averaging

        # 2. Cooldown check
        last_avg_date_str = position.get('_shield_last_avg_date', '')
        if last_avg_date_str:
            try:
                last_avg_date = datetime.fromisoformat(last_avg_date_str).date()
                days_since = (datetime.now().date() - last_avg_date).days
                cooldown = getattr(self.config, 'CNC_AVG_COOLDOWN_DAYS', 1)
                if days_since < cooldown:
                    return  # In cooldown
            except:
                pass

        # 3. Position multiplier cap
        current_qty = position.get('quantity', 1)
        current_avg = position.get('entry_price', current_price)  # weighted avg
        total_invested = current_qty * current_avg
        original_invested = position.get('_shield_original_invested', total_invested)
        if '_shield_original_invested' not in position:
            position['_shield_original_invested'] = total_invested

        max_mult = getattr(self.config, 'CNC_AVG_MAX_POSITION_MULTIPLIER', 3)
        if total_invested >= original_invested * max_mult:
            logger.info(f"   🛡️ {symbol}: Position at {max_mult}x cap, no more averaging")
            return

        # 4. Weekly uptrend check (don't average into confirmed downtrend)
        mtf = position.get('phase4_tracking', {}).get('multi_timeframe', {})
        weekly_trend = mtf.get('weekly_trend', 'UNKNOWN')
        if weekly_trend == 'DOWNTREND':
            logger.info(f"   🛡️ {symbol}: Weekly DOWNTREND — averaging blocked")
            return

        # 5. Calculate bounce confidence using EXISTING TruthMatrix
        confidence = self._calc_bounce_confidence(symbol, position, current_price)
        min_conf = getattr(self.config, 'CNC_BOUNCE_MIN_CONFIDENCE', 65)

        if confidence < min_conf:
            logger.info(f"   🛡️ {symbol}: Bounce confidence {confidence}/100 < {min_conf} — waiting")
            return

        # 6. Calculate what averaging achieves
        # Use same qty as current position (buy same amount)
        add_qty = current_qty  # Mirror original quantity
        new_total_qty = current_qty + add_qty
        new_avg = (current_qty * current_avg + add_qty * current_price) / new_total_qty
        target_pct = getattr(self.config, 'CNC_AVG_TARGET_PCT', 3.0)
        new_target = new_avg * (1 + target_pct / 100)
        target_distance = ((new_target - current_price) / current_price) * 100

        # Check if target is reachable
        max_distance = getattr(self.config, 'CNC_AVG_MAX_DISTANCE_PCT', 10)
        if target_distance > max_distance:
            logger.info(f"   🛡️ {symbol}: Target still {target_distance:.1f}% away after avg — too far")
            return

        # 7. Check capital availability
        # Use capital_manager if available, otherwise allow
        can_afford = True
        if hasattr(self, 'capital_manager') and self.capital_manager:
            try:
                available = self.capital_manager.get_available()
                needed = add_qty * current_price
                can_afford = available >= needed
            except:
                pass

        if not can_afford:
            logger.info(f"   🛡️ {symbol}: Insufficient capital for averaging")
            return

        # ═══ ALL CHECKS PASSED — EXECUTE AVERAGING ═══
        self._execute_cnc_averaging(symbol, position, current_price,
                                     add_qty, new_avg, new_target, confidence)

    def _calc_bounce_confidence(self, symbol: str, position: Dict,  # v5.5.0
                                 current_price: float) -> int:
        """
        5-Layer Bounce Confidence using EXISTING Phase 4 TruthMatrix data.
        Returns 0-100 score.
        """
        score = 0
        entry_price = position.get('entry_price', current_price)
        atr = position.get('atr', current_price * 0.02)

        # Get stored TruthMatrix (updated every Phase 4 cycle)
        tm = position.get('truth_matrix', {})
        supports = tm.get('supports', {})
        indicators = tm.get('indicators', {})
        fib_data = indicators.get('fibonacci', {})
        bb_data = indicators.get('bollinger', {})
        kalman_data = indicators.get('kalman', {})

        # Build support levels list from TruthMatrix
        support_levels = []

        # Fibonacci retracements (from TruthMatrix)
        fib_retrace = fib_data.get('retracement_levels', {})
        for name, price in fib_retrace.items():
            if price and 0 < price < entry_price:
                support_levels.append(('Fib_' + str(name), price))

        # BB lower and VWAP lower
        bb_lower = supports.get('bb_lower', 0)
        if bb_lower > 0:
            support_levels.append(('BB_Lower', bb_lower))
        vwap_lower = supports.get('vwap_1sigma_lower', 0)
        if vwap_lower > 0:
            support_levels.append(('VWAP_-1σ', vwap_lower))

        # Sort by price descending (nearest support first)
        support_levels.sort(key=lambda x: x[1], reverse=True)

        # LAYER 1: Fibonacci zone proximity (0-20)
        fib_382 = fib_retrace.get('38.2', 0) or fib_retrace.get('38.2%', 0) or 0
        fib_500 = fib_retrace.get('50.0', 0) or fib_retrace.get('50.0%', 0) or 0
        fib_618 = fib_retrace.get('61.8', 0) or fib_retrace.get('61.8%', 0) or 0

        fib_score = 0
        for fib_level, fib_pts in [(fib_618, 20), (fib_500, 16), (fib_382, 12)]:
            if fib_level > 0:
                dist = abs(current_price - fib_level) / current_price * 100
                if dist <= 1.0:  # Within 1% of Fib level
                    fib_score = max(fib_score, fib_pts)
                elif dist <= 2.0:
                    fib_score = max(fib_score, int(fib_pts * 0.6))
        score += fib_score

        # LAYER 2: S/R + VWAP proximity (0-20)
        sr_score = 0
        for name, level in support_levels:
            if level > 0:
                dist = abs(current_price - level) / current_price * 100
                if dist <= 0.5:
                    sr_score = max(sr_score, 20)
                elif dist <= 1.0:
                    sr_score = max(sr_score, 15)
                elif dist <= 2.0:
                    sr_score = max(sr_score, 10)
        score += sr_score

        # LAYER 3: Bollinger band proximity (0-15)
        if bb_lower > 0:
            bb_dist = (current_price - bb_lower) / current_price * 100
            if bb_dist <= 0.5:
                score += 15  # At or below BB lower
            elif bb_dist <= 1.0:
                score += 12
            elif bb_dist <= 2.0:
                score += 8

        # LAYER 4: Kalman deceleration (0-15)
        kalman_vel = kalman_data.get('velocity', 0)
        kalman_accel = kalman_data.get('acceleration', 0)
        if kalman_vel < 0 and kalman_accel > 0:
            # Falling but decelerating = bottom forming
            score += 15
        elif kalman_vel < 0 and kalman_accel > -0.5:
            # Falling, deceleration starting
            score += 10
        elif kalman_vel > 0:
            # Already turning up
            score += 12

        # LAYER 5: RSI recovery (0-15) — using stored tracking data
        rsi = position.get('phase4_tracking', {}).get('rsi_14', 0)
        prev_rsi = position.get('phase4_tracking', {}).get('prev_rsi_14', 0)
        if rsi > 0:
            if rsi < 30:
                score += 10  # Deeply oversold
                if prev_rsi > 0 and rsi > prev_rsi:
                    score += 5  # RSI upturn bonus
            elif rsi < 35:
                score += 7
                if prev_rsi > 0 and rsi > prev_rsi:
                    score += 4
            elif rsi < 40:
                score += 4

        # Cap at 100
        confidence = min(100, score)

        logger.info(f"   🛡️ {symbol}: Bounce confidence {confidence}/100 "
                    f"(Fib:{fib_score} SR:{sr_score} BB:{score - fib_score - sr_score}...)")

        return confidence

    def _execute_cnc_averaging(self, symbol: str, position: Dict,  # v5.5.0
                                current_price: float, add_qty: int,
                                new_avg: float, new_target: float,
                                confidence: int):
        """Execute CNC averaging order and update position tracking."""

        avg_count = position.get('_shield_avg_count', 0) + 1

        logger.info(f"   🛡️ CNC SHIELD: AVERAGING #{avg_count} for {symbol}")
        logger.info(f"      Buy {add_qty} @ ₹{current_price:.2f}")
        logger.info(f"      New avg: ₹{new_avg:.2f} → Target: ₹{new_target:.2f}")

        try:
            # v5.4.0 SEBI FIX: Raw API call to inject market_protection=-1
            import requests
            url = "https://api.kite.trade/orders/regular"
            headers = {
                "X-Kite-Version": "3",
                "Authorization": f"token {self.kite.api_key}:{self.kite.access_token}"
            }
            payload = {
                "tradingsymbol": symbol,
                "exchange": "NSE",
                "transaction_type": "BUY",
                "quantity": str(add_qty),
                "product": "CNC",
                "order_type": "MARKET",
                "market_protection": "-1"
            }
            response = requests.post(url, headers=headers, data=payload, timeout=10)
            response_json = response.json()
            if response.status_code == 200 and response_json.get('status') == 'success':
                order_id = response_json.get('data', {}).get('order_id')
            else:
                logger.error(f"   CNC Shield averaging raw API failed: {response_json}")
                order_id = None

            logger.info(f"   Averaging order placed: {order_id}")

            # Update position tracking
            old_qty = position.get('quantity', 1)
            old_avg = position.get('entry_price', current_price)
            position['quantity'] = old_qty + add_qty
            position['entry_price'] = new_avg
            position['target_price'] = new_target
            position['_shield_avg_count'] = avg_count
            position['_shield_last_avg_date'] = datetime.now().isoformat()

            # Track averaging history
            avg_history = position.setdefault('_shield_avg_history', [])
            avg_history.append({
                'date': datetime.now().isoformat(),
                'qty': add_qty,
                'price': current_price,
                'old_avg': old_avg,
                'new_avg': new_avg,
                'new_target': new_target,
                'confidence': confidence,
                'order_id': order_id
            })

            # Update GTT with new target
            try:
                if position.get('gtt_target_id'):
                    self._modify_gtt_target(symbol, new_target)
            except Exception as e:
                logger.error(f"_execute_cnc_averaging GTT update error {symbol}: {e}")

        except Exception as e:
            logger.error(f"_execute_cnc_averaging error {symbol}: {e}")
