"""
MARKET INTELLIGENCE ENGINE v1.0.0
═══════════════════════════════════════════════════════════════════════════════

Data enrichment layer for ChatGPT prompts. Computes 10 intelligence layers
and packages them into structured context dictionaries.

Does NOT make decisions. Does NOT place orders. Does NOT modify positions.
Only computes and returns data.

Author: Algo_Beta MIE v1.0.0
Date: 2026-03-03
"""

import logging
import numpy as np
from datetime import datetime, time as dt_time, timedelta
from typing import Dict, Optional, List, Any, Tuple
from dataclasses import dataclass, asdict

logger = logging.getLogger('MarketIntelligenceEngine')


# ═══════════════════════════════════════════════════════════════════════════════
# DATACLASSES — One per intelligence layer
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class VWAPContext:
    """Layer 1: VWAP position analysis"""
    vwap_price: float
    current_price: float
    distance_from_vwap_pct: float          # +above, -below
    sigma_1_upper: float
    sigma_1_lower: float
    sigma_2_upper: float
    sigma_2_lower: float
    band_position: str                      # "ABOVE_2σ", "ABOVE_1σ", "WITHIN_1σ", "BELOW_1σ", "BELOW_2σ"
    prev_day_poc: float                     # Point of Control
    prev_day_value_area_high: float
    prev_day_value_area_low: float
    price_vs_value_area: str               # "ABOVE", "INSIDE", "BELOW"
    signal: str                             # "OVEREXTENDED_HIGH", "OVEREXTENDED_LOW", "NEUTRAL", "APPROACHING_POC"


@dataclass
class MomentumContext:
    """Layer 2: Optimized momentum indicators"""
    macd_histogram: float
    macd_signal_cross: str                  # "BULLISH_CROSS", "BEARISH_CROSS", "NONE"
    macd_trend: str                         # "STRENGTHENING", "WEAKENING", "FLAT"
    stochastic_k: float
    stochastic_d: float
    stochastic_zone: str                    # "OVERSOLD", "OVERBOUGHT", "NEUTRAL"
    stochastic_cross: str                   # "BULLISH_CROSS", "BEARISH_CROSS", "NONE"
    adx_value: float
    adx_trend_strength: str                 # "NO_TREND" (<20), "WEAK" (20-25), "STRONG" (25-40), "VERY_STRONG" (>40)
    adx_implication: str                    # "RANGING_MARKET_DIP_IS_NOISE", "TRENDING_RESPECT_THE_MOVE"
    momentum_verdict: str                   # "OVERSOLD_IN_RANGE", "TRENDING_DOWN", "TRENDING_UP", "NEUTRAL"


@dataclass
class VRecoveryQuality:
    """Layer 3: Fibonacci-aligned V-Recovery grading"""
    recovery_pct: float
    fibonacci_level: str                    # "38.2%", "50.0%", "61.8%", "78.6%", "OTHER"
    fibonacci_score: int                    # 0-20 base score
    volume_at_bounce_ratio: float           # vs 20-day average
    volume_confirmed: bool                  # >= 1.5x average
    candle_pattern: str                     # "HAMMER", "ENGULFING", "DOJI", "NONE"
    candle_bonus: int                       # 0 or 3
    quality_score: float                    # Final score (fibonacci_score * volume_multiplier + candle_bonus)
    quality_grade: str                      # "EXCEPTIONAL" (>20), "STRONG" (15-20), "MODERATE" (8-14), "WEAK" (<8)
    interpretation: str                     # Human-readable summary


@dataclass
class ATRContext:
    """Layer 4: ATR-based volatility analysis"""
    atr_value: float
    atr_pct_of_price: float                 # ATR as % of current price
    current_drop_from_entry: float          # In rupees
    drop_as_atr_multiple: float             # drop / ATR
    drop_interpretation: str                # "WITHIN_NORMAL" (<1.5x), "AT_EDGE" (1.5-2x), "BEYOND_NORMAL" (>2x)
    suggested_stop_conservative: float      # entry - 1.5*ATR
    suggested_stop_normal: float            # entry - 2.0*ATR
    suggested_target_2x: float              # entry + 2.0*ATR
    suggested_target_3x: float              # entry + 3.0*ATR
    risk_reward_from_current: float         # if held from current price
    risk_reward_interpretation: str         # "EXCELLENT" (>1:2.5), "GOOD" (>1:2), "MARGINAL" (>1:1.5), "POOR"


@dataclass
class CompositeScore:
    """Layer 5: 100-point multi-factor scoring"""
    total_score: float
    risk_reward_score: float                # 0-25
    v_recovery_score: float                 # 0-20
    trend_alignment_score: float            # 0-15
    volume_confirmation_score: float        # 0-15
    session_timing_score: float             # 0-10
    indicator_confluence_score: float       # 0-10
    liquidity_score: float                  # 0-5
    position_size_recommendation: str       # "FULL", "75%", "50%", "SKIP"
    rank_among_candidates: int              # 1, 2, 3... (0 if only stock)
    total_candidates: int


@dataclass
class ExpiryCycleContext:
    """Layer 6: Day-of-week relative to Tuesday expiry"""
    today_weekday: str                      # "Monday", "Tuesday", etc.
    expiry_day: str                         # "Tuesday" (NSE)
    days_to_expiry: int                     # 0 = expiry day
    cycle_position: str                     # "EXPIRY_EVE", "EXPIRY_DAY", "POST_EXPIRY_DAY_1", ...
    expected_pressure: str                  # "SELLING_PRESSURE", "BUYING_PRESSURE_BEGINS", ...
    trading_implication: str                # Human-readable
    is_good_entry_day: bool                 # True for Wed/Thu (post-expiry)
    is_dangerous_day: bool                  # True for Mon/Tue (expiry pressure)


@dataclass
class DecisionHistoryContext:
    """Layer 7: ChatGPT's own track record"""
    total_decisions: int
    exit_accuracy_pct: float                # % of EXIT calls that were correct
    hold_accuracy_pct: float                # % of HOLD calls that were correct
    accuracy_by_adx_low: float              # accuracy when ADX < 20
    accuracy_by_adx_high: float             # accuracy when ADX > 25
    similar_past_cases: List[Dict]          # [{date, symbol, setup, decision, outcome}]
    learning_insight: str                   # "Your EXIT accuracy drops to 35% when ADX < 20"


@dataclass
class PerformanceMetrics:
    """Layer 8: Real vs simulated performance"""
    phase3_real_trades: int
    phase3_real_win_rate: float
    phase3_real_avg_profit_pct: float
    phase3_real_avg_loss_pct: float
    phase5_real_trades: int
    phase5_real_win_rate: float
    backtest_win_rate: float
    backtest_vs_real_gap: float             # backtest - real (positive = overoptimistic)
    confidence_note: str                    # "50+ trades: reliable" or "< 10 trades: treat with caution"


@dataclass
class CapitalState:
    """Layer 9: Live capital from CapitalManager"""
    total_capital: float
    deployed_amount: float
    available_amount: float
    deployed_positions: List[Dict]          # [{symbol, amount, pnl_pct}]
    concentration_limit_pct: float
    max_per_stock: float
    can_fit_new_entry: bool
    entry_budget: float                     # How much can be allocated to new entry
    buffer_remaining: float


@dataclass
class CrashMatrix:
    """Layer 10: Context-dependent crash interpretation"""
    phase_source: str                       # "PHASE_2", "PHASE_3_CNC", "PHASE_5_MIS", "PHASE_6_OPTIONS"
    product_type: str                       # "CNC", "MIS", "NRML"
    crash_meaning: str                      # "BUYING_OPPORTUNITY", "DANGER_TO_CAPITAL", "OPTIONS_DANGER"
    patience_level: str                     # "HIGH_PATIENCE" (CNC), "LOW_PATIENCE" (MIS), "MEDIUM" (NRML)
    exit_trigger_philosophy: str            # How exits should be evaluated for this context
    crash_response_instruction: str         # Direct instruction for ChatGPT


@dataclass
class IntelligencePackage:
    """Complete output from MIE - all 10 layers"""
    vwap: Optional[VWAPContext]
    momentum: Optional[MomentumContext]
    v_recovery: Optional[VRecoveryQuality]
    atr: Optional[ATRContext]
    composite: Optional[CompositeScore]
    expiry_cycle: Optional[ExpiryCycleContext]
    decision_history: Optional[DecisionHistoryContext]
    performance: Optional[PerformanceMetrics]
    capital: Optional[CapitalState]
    crash_matrix: Optional[CrashMatrix]
    generated_at: str                       # ISO timestamp

    def to_dict(self) -> Dict:
        """Convert all layers to dict for prompt building"""
        result = {}
        for field_name in self.__dataclass_fields__:
            val = getattr(self, field_name)
            if val is not None and hasattr(val, '__dataclass_fields__'):
                result[field_name] = asdict(val)
            elif val is not None:
                result[field_name] = val
        return result


# ═══════════════════════════════════════════════════════════════════════════════
# HELPER — EMA calculation
# ═══════════════════════════════════════════════════════════════════════════════

def _ema(data: List[float], period: int) -> List[float]:
    """Compute Exponential Moving Average. Returns list same length as input (None-padded)."""
    if len(data) < period:
        return []

    multiplier = 2 / (period + 1)
    ema_values = [None] * (period - 1)
    ema_values.append(sum(data[:period]) / period)  # SMA seed

    for i in range(period, len(data)):
        ema_values.append(data[i] * multiplier + ema_values[-1] * (1 - multiplier))

    return ema_values


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN ENGINE CLASS
# ═══════════════════════════════════════════════════════════════════════════════

class MarketIntelligenceEngine:
    """
    Computes 10 intelligence layers for ChatGPT prompt enrichment.

    Does NOT make decisions. Does NOT place orders.
    Only computes and returns structured context data.
    """

    def __init__(self, config, kite=None, capital_manager=None,
                 decision_history=None, phase1_data=None):
        self.config = config
        self.kite = kite
        self.capital_manager = capital_manager
        self.decision_history = decision_history
        self.phase1_data = phase1_data or {}

        # Cache for prev-day data (refreshed daily)
        self._prev_day_cache: Dict[str, Dict] = {}
        self._cache_date = None

        logger.info("=" * 80)
        logger.info("MARKET INTELLIGENCE ENGINE v1.0.0")
        logger.info("=" * 80)

    # ═══════════════════════════════════════════════════════════════════
    # PUBLIC API
    # ═══════════════════════════════════════════════════════════════════

    def get_entry_context(
        self,
        symbol: str,
        stock_monitor,
        phase_source: str = "PHASE_2",
        product_type: str = "CNC",
        all_candidates: List[Dict] = None,
        v_recovery_data: Dict = None
    ) -> IntelligencePackage:
        """Build complete intelligence package for ENTRY decisions."""
        if not getattr(self.config, 'ENABLE_MIE', False):
            return self._empty_package()

        current_price = self._safe_price(stock_monitor)
        entry_price = current_price  # For entry, current IS entry

        return IntelligencePackage(
            vwap=self._safe_compute(self._compute_vwap_context, symbol, stock_monitor, current_price),
            momentum=self._safe_compute(self._compute_momentum_context, symbol, stock_monitor),
            v_recovery=self._safe_compute(self._compute_v_recovery_quality, v_recovery_data, stock_monitor),
            atr=self._safe_compute(self._compute_atr_context, symbol, stock_monitor, entry_price, current_price),
            composite=self._safe_compute(self._compute_composite_score, symbol, stock_monitor, v_recovery_data, all_candidates),
            expiry_cycle=self._safe_compute(self._compute_expiry_cycle),
            decision_history=self._safe_compute(self._compute_decision_history, symbol, {'product': product_type}),
            performance=self._safe_compute(self._compute_performance_metrics),
            capital=self._safe_compute(self._compute_capital_state, entry_price),
            crash_matrix=self._safe_compute(self._compute_crash_matrix, phase_source, product_type),
            generated_at=datetime.now().isoformat()
        )

    def get_exit_context(
        self,
        symbol: str,
        position: Dict,
        stock_monitor=None,
        phase_source: str = "PHASE_3_CNC",
        product_type: str = "CNC"
    ) -> IntelligencePackage:
        """Build complete intelligence package for EXIT decisions."""
        if not getattr(self.config, 'ENABLE_MIE', False):
            return self._empty_package()

        entry_price = position.get('entry_price', 0)
        current_price = position.get('current_price', entry_price)

        return IntelligencePackage(
            vwap=self._safe_compute(self._compute_vwap_context, symbol, stock_monitor, current_price) if stock_monitor else None,
            momentum=self._safe_compute(self._compute_momentum_context, symbol, stock_monitor) if stock_monitor else None,
            v_recovery=None,  # Not relevant for exits
            atr=self._safe_compute(self._compute_atr_context, symbol, stock_monitor, entry_price, current_price) if stock_monitor else None,
            composite=None,  # Not relevant for exits
            expiry_cycle=self._safe_compute(self._compute_expiry_cycle),
            decision_history=self._safe_compute(self._compute_decision_history, symbol, {
                'pnl_pct': position.get('pnl_pct', 0),
                'product': product_type
            }),
            performance=self._safe_compute(self._compute_performance_metrics),
            capital=self._safe_compute(self._compute_capital_state, 0),
            crash_matrix=self._safe_compute(self._compute_crash_matrix, phase_source, product_type),
            generated_at=datetime.now().isoformat()
        )

    def get_sizing_context(
        self,
        symbol: str,
        entry_price: float,
        score: float,
        all_candidates: List[Dict] = None
    ) -> IntelligencePackage:
        """Build intelligence for POSITION SIZING decisions. Subset: L5, L6, L9."""
        if not getattr(self.config, 'ENABLE_MIE', False):
            return self._empty_package()

        return IntelligencePackage(
            vwap=None, momentum=None, v_recovery=None, atr=None,
            composite=None,  # Would need stock_monitor; caller can add
            expiry_cycle=self._safe_compute(self._compute_expiry_cycle),
            decision_history=None, performance=None,
            capital=self._safe_compute(self._compute_capital_state, entry_price),
            crash_matrix=None,
            generated_at=datetime.now().isoformat()
        )

    def get_premarket_context(self) -> IntelligencePackage:
        """Build intelligence for PRE-MARKET decisions. Subset: L6, L8, L9."""
        if not getattr(self.config, 'ENABLE_MIE', False):
            return self._empty_package()

        return IntelligencePackage(
            vwap=None, momentum=None, v_recovery=None, atr=None,
            composite=None,
            expiry_cycle=self._safe_compute(self._compute_expiry_cycle),
            decision_history=None,
            performance=self._safe_compute(self._compute_performance_metrics),
            capital=self._safe_compute(self._compute_capital_state, 0),
            crash_matrix=None,
            generated_at=datetime.now().isoformat()
        )

    # ═══════════════════════════════════════════════════════════════════
    # LAYER 1: VWAP CONTEXT
    # ═══════════════════════════════════════════════════════════════════

    def _compute_vwap_context(self, symbol: str, stock_monitor, current_price: float) -> Optional[VWAPContext]:
        if not getattr(self.config, 'ENABLE_MIE_VWAP', True):
            return None

        vwap = getattr(stock_monitor, 'vwap', None) or 0
        if vwap == 0:
            return None

        # Standard Deviation Bands from intraday candle history
        candles = getattr(stock_monitor, 'intraday_candles', None)
        if candles and len(candles) > 5:
            typical_prices = [(c.get('high', 0) + c.get('low', 0) + c.get('close', 0)) / 3 for c in candles]
            volumes = [c.get('volume', 0) for c in candles]
            total_vol = sum(volumes)

            if total_vol > 0:
                variance = sum(v * (tp - vwap) ** 2 for tp, v in zip(typical_prices, volumes)) / total_vol
                std_dev = max(variance ** 0.5, 0.01)
            else:
                fallback_pct = getattr(self.config, 'MIE_VWAP_FALLBACK_STD_PCT', 1.0)
                std_dev = current_price * fallback_pct / 100
        else:
            atr = getattr(stock_monitor, 'atr', None)
            if atr and atr > 0:
                std_dev = atr * 0.5
            else:
                fallback_pct = getattr(self.config, 'MIE_VWAP_FALLBACK_STD_PCT', 1.0)
                std_dev = current_price * fallback_pct / 100

        sigma_1_upper = vwap + std_dev
        sigma_1_lower = vwap - std_dev
        sigma_2_upper = vwap + 2 * std_dev
        sigma_2_lower = vwap - 2 * std_dev

        # Band Position (σ labels match prompt rules referencing "VWAP 1σ", "VWAP 2σ")
        if current_price > sigma_2_upper:
            band_position = "ABOVE_2σ"
        elif current_price > sigma_1_upper:
            band_position = "ABOVE_1σ"
        elif current_price >= sigma_1_lower:
            band_position = "WITHIN_1σ"
        elif current_price >= sigma_2_lower:
            band_position = "BELOW_1σ"
        else:
            band_position = "BELOW_2σ"

        distance_pct = ((current_price - vwap) / vwap * 100) if vwap > 0 else 0

        # Previous Day POC and Value Area
        prev_data = self._get_prev_day_data(symbol)
        prev_poc = prev_data.get('poc', 0)
        prev_va_high = prev_data.get('value_area_high', 0)
        prev_va_low = prev_data.get('value_area_low', 0)

        if prev_va_high > 0 and prev_va_low > 0:
            if current_price > prev_va_high:
                price_vs_va = "ABOVE"
            elif current_price >= prev_va_low:
                price_vs_va = "INSIDE"
            else:
                price_vs_va = "BELOW"
        else:
            price_vs_va = "UNKNOWN"

        # Signal
        if band_position == "ABOVE_2s":
            signal = "OVEREXTENDED_HIGH"
        elif band_position == "BELOW_2s":
            signal = "OVEREXTENDED_LOW"
        elif prev_poc > 0 and abs(current_price - prev_poc) / prev_poc < 0.005:
            signal = "APPROACHING_POC"
        else:
            signal = "NEUTRAL"

        return VWAPContext(
            vwap_price=round(vwap, 2),
            current_price=round(current_price, 2),
            distance_from_vwap_pct=round(distance_pct, 2),
            sigma_1_upper=round(sigma_1_upper, 2),
            sigma_1_lower=round(sigma_1_lower, 2),
            sigma_2_upper=round(sigma_2_upper, 2),
            sigma_2_lower=round(sigma_2_lower, 2),
            band_position=band_position,
            prev_day_poc=round(prev_poc, 2),
            prev_day_value_area_high=round(prev_va_high, 2),
            prev_day_value_area_low=round(prev_va_low, 2),
            price_vs_value_area=price_vs_va,
            signal=signal
        )

    # ═══════════════════════════════════════════════════════════════════
    # LAYER 2: MOMENTUM STACK
    # ═══════════════════════════════════════════════════════════════════

    def _compute_momentum_context(self, symbol: str, stock_monitor) -> Optional[MomentumContext]:
        if not getattr(self.config, 'ENABLE_MIE_MOMENTUM', True):
            return None

        # ADX (Primary)
        adx_value = getattr(stock_monitor, 'adx_value', None) or getattr(stock_monitor, 'adx', None) or 0

        if adx_value < 20:
            adx_strength = "NO_TREND"
            adx_implication = "RANGING_MARKET_DIP_IS_NOISE"
        elif adx_value < 25:
            adx_strength = "WEAK"
            adx_implication = "RANGING_MARKET_DIP_IS_NOISE"
        elif adx_value < 40:
            adx_strength = "STRONG"
            adx_implication = "TRENDING_RESPECT_THE_MOVE"
        else:
            adx_strength = "VERY_STRONG"
            adx_implication = "TRENDING_RESPECT_THE_MOVE"

        # MACD (5, 13, 8) optimized for intraday
        macd_hist = 0.0
        macd_cross = "NONE"
        macd_trend = "FLAT"

        candles = getattr(stock_monitor, 'intraday_candles', None)
        if candles and len(candles) >= 15:
            closes = [c.get('close', 0) for c in candles if c.get('close', 0) > 0]

            fast_period = getattr(self.config, 'MIE_MACD_FAST', 5)
            slow_period = getattr(self.config, 'MIE_MACD_SLOW', 13)
            signal_period = getattr(self.config, 'MIE_MACD_SIGNAL', 8)

            if len(closes) >= slow_period + signal_period:
                ema_fast = _ema(closes, fast_period)
                ema_slow = _ema(closes, slow_period)

                macd_line_values = []
                for ef, es in zip(ema_fast, ema_slow):
                    if ef is not None and es is not None:
                        macd_line_values.append(ef - es)

                if len(macd_line_values) >= signal_period:
                    signal_line = _ema(macd_line_values, signal_period)
                    if signal_line and len(signal_line) >= 2:
                        sl_curr = signal_line[-1]
                        sl_prev = signal_line[-2]
                        if sl_curr is not None and sl_prev is not None:
                            macd_hist = macd_line_values[-1] - sl_curr

                            prev_diff = macd_line_values[-2] - sl_prev
                            curr_diff = macd_line_values[-1] - sl_curr
                            if prev_diff <= 0 < curr_diff:
                                macd_cross = "BULLISH_CROSS"
                            elif prev_diff >= 0 > curr_diff:
                                macd_cross = "BEARISH_CROSS"

                            hist_prev = macd_line_values[-2] - sl_prev
                            if abs(macd_hist) > abs(hist_prev):
                                macd_trend = "STRENGTHENING"
                            elif abs(macd_hist) < abs(hist_prev):
                                macd_trend = "WEAKENING"

        # Stochastic (8, 3, 3) — Proper %K and %D with crossover detection
        stoch_k = 50.0
        stoch_d = 50.0
        stoch_zone = "NEUTRAL"
        stoch_cross = "NONE"

        if candles and len(candles) >= 10:
            closes = [c.get('close', 0) for c in candles]
            highs = [c.get('high', 0) for c in candles]
            lows = [c.get('low', 0) for c in candles]

            period = getattr(self.config, 'MIE_STOCHASTIC_K', 8)
            d_period = getattr(self.config, 'MIE_STOCHASTIC_D', 3)

            if len(closes) >= period + d_period:
                # Compute raw %K for recent candles (enough for %D SMA)
                k_values = []
                for i in range(max(0, len(closes) - d_period - 1), len(closes)):
                    start_idx = max(0, i - period + 1)
                    window_highs = highs[start_idx:i + 1]
                    window_lows = lows[start_idx:i + 1]
                    hh = max(window_highs) if window_highs else 0
                    ll = min(window_lows) if window_lows else 0
                    if hh != ll:
                        k_values.append((closes[i] - ll) / (hh - ll) * 100)
                    else:
                        k_values.append(50.0)

                stoch_k = k_values[-1] if k_values else 50.0

                # %D = SMA of last d_period %K values
                if len(k_values) >= d_period:
                    stoch_d = sum(k_values[-d_period:]) / d_period

                    # Crossover detection: compare previous vs current K-D relationship
                    if len(k_values) >= d_period + 1:
                        prev_d = sum(k_values[-(d_period + 1):-1]) / d_period
                        prev_k = k_values[-2]
                        if prev_k <= prev_d and stoch_k > stoch_d:
                            stoch_cross = "BULLISH_CROSS"
                        elif prev_k >= prev_d and stoch_k < stoch_d:
                            stoch_cross = "BEARISH_CROSS"
                else:
                    stoch_d = stoch_k

                if stoch_k < 20:
                    stoch_zone = "OVERSOLD"
                elif stoch_k > 80:
                    stoch_zone = "OVERBOUGHT"

        # Momentum Verdict
        adx_threshold = getattr(self.config, 'MIE_ADX_TREND_THRESHOLD', 25)
        if adx_value < adx_threshold and stoch_zone == "OVERSOLD":
            verdict = "OVERSOLD_IN_RANGE"
        elif adx_value >= adx_threshold and macd_hist < 0:
            verdict = "TRENDING_DOWN"
        elif adx_value >= adx_threshold and macd_hist > 0:
            verdict = "TRENDING_UP"
        else:
            verdict = "NEUTRAL"

        return MomentumContext(
            macd_histogram=round(macd_hist, 3),
            macd_signal_cross=macd_cross,
            macd_trend=macd_trend,
            stochastic_k=round(stoch_k, 1),
            stochastic_d=round(stoch_d, 1),
            stochastic_zone=stoch_zone,
            stochastic_cross=stoch_cross,
            adx_value=round(adx_value, 1),
            adx_trend_strength=adx_strength,
            adx_implication=adx_implication,
            momentum_verdict=verdict
        )

    # ═══════════════════════════════════════════════════════════════════
    # LAYER 3: V-RECOVERY QUALITY SCORER
    # ═══════════════════════════════════════════════════════════════════

    def _compute_v_recovery_quality(self, v_recovery_data: Dict,
                                      stock_monitor) -> Optional[VRecoveryQuality]:
        if not getattr(self.config, 'ENABLE_MIE_V_RECOVERY', True):
            return None
        if not v_recovery_data:
            return None

        recovery_pct = v_recovery_data.get('recovery_pct', 0)

        # Fibonacci Level Mapping
        fib_levels = [
            (78.6, 12, "78.6%"),
            (61.8, 20, "61.8%"),
            (50.0, 14, "50.0%"),
            (38.2, 8, "38.2%"),
        ]

        tolerance = getattr(self.config, 'MIE_FIBONACCI_TOLERANCE', 5.0)
        fib_score = 5
        fib_level = "OTHER"

        for level, score, label in fib_levels:
            if abs(recovery_pct - level) <= tolerance:
                fib_score = score
                fib_level = label
                break

        if fib_level == "OTHER":
            if recovery_pct > 61.8:
                fib_score = int(20 - (recovery_pct - 61.8) * 0.47)
            elif recovery_pct > 50:
                fib_score = int(14 + (recovery_pct - 50) * 0.5)
            elif recovery_pct > 38.2:
                fib_score = int(8 + (recovery_pct - 38.2) * 0.5)
            else:
                fib_score = max(3, int(recovery_pct / 5))

        # Volume Confirmation
        vol_ratio = v_recovery_data.get('volume_ratio', None)
        if vol_ratio is None or vol_ratio == 0:
            vol_ratio = getattr(stock_monitor, 'volume_ratio', 1.0) or 1.0

        vol_threshold = getattr(self.config, 'MIE_VOLUME_CONFIRMATION_THRESHOLD', 1.5)
        volume_confirmed = vol_ratio >= vol_threshold
        volume_multiplier = 1.0 if volume_confirmed else 0.7

        # Candle Pattern Detection
        candle_pattern = v_recovery_data.get('candle_pattern', 'NONE')
        candle_bonus = 3 if candle_pattern in ('HAMMER', 'ENGULFING', 'BULLISH_ENGULFING') else 0

        # Quality Score
        quality_score = round(fib_score * volume_multiplier + candle_bonus, 1)

        if quality_score > 20:
            grade = "EXCEPTIONAL"
        elif quality_score >= 15:
            grade = "STRONG"
        elif quality_score >= 8:
            grade = "MODERATE"
        else:
            grade = "WEAK"

        # Interpretation
        interpretation = f"Recovery at {recovery_pct:.1f}% ({fib_level} Fibonacci)"
        if volume_confirmed:
            interpretation += f" with {vol_ratio:.1f}x volume CONFIRMED"
        else:
            interpretation += f" with {vol_ratio:.1f}x volume (UNCONFIRMED)"
        if candle_pattern != "NONE":
            interpretation += f". {candle_pattern} candle pattern detected"

        return VRecoveryQuality(
            recovery_pct=round(recovery_pct, 1),
            fibonacci_level=fib_level,
            fibonacci_score=fib_score,
            volume_at_bounce_ratio=round(vol_ratio, 2),
            volume_confirmed=volume_confirmed,
            candle_pattern=candle_pattern,
            candle_bonus=candle_bonus,
            quality_score=quality_score,
            quality_grade=grade,
            interpretation=interpretation
        )

    # ═══════════════════════════════════════════════════════════════════
    # LAYER 4: ATR VOLATILITY CONTEXT
    # ═══════════════════════════════════════════════════════════════════

    def _compute_atr_context(self, symbol: str, stock_monitor,
                               entry_price: float, current_price: float) -> Optional[ATRContext]:
        if not getattr(self.config, 'ENABLE_MIE_ATR', True):
            return None

        atr = getattr(stock_monitor, 'atr', None) or 0
        if atr == 0:
            atr = current_price * 0.015  # Fallback: 1.5% of price

        atr_pct = (atr / current_price * 100) if current_price > 0 else 0

        drop = entry_price - current_price  # Positive = loss, Negative = gain
        drop_atr_mult = abs(drop) / atr if atr > 0 else 0

        normal_thresh = getattr(self.config, 'MIE_ATR_NORMAL_THRESHOLD', 1.5)
        abnormal_thresh = getattr(self.config, 'MIE_ATR_ABNORMAL_THRESHOLD', 2.0)

        if drop >= 0:
            # Price below entry (loss)
            if drop_atr_mult < normal_thresh:
                drop_interp = "LOSS_WITHIN_NORMAL"
            elif drop_atr_mult < abnormal_thresh:
                drop_interp = "LOSS_AT_EDGE"
            else:
                drop_interp = "LOSS_BEYOND_NORMAL"
        else:
            # Price above entry (gain)
            if drop_atr_mult < normal_thresh:
                drop_interp = "GAIN_WITHIN_NORMAL"
            elif drop_atr_mult < abnormal_thresh:
                drop_interp = "GAIN_EXTENDED"
            else:
                drop_interp = "GAIN_OVEREXTENDED"

        stop_mult = getattr(self.config, 'MIE_ATR_STOP_MULTIPLIER', 2.0)
        target_mult = getattr(self.config, 'MIE_ATR_TARGET_MULTIPLIER', 3.0)

        stop_conservative = round(entry_price - 1.5 * atr, 2)
        stop_normal = round(entry_price - stop_mult * atr, 2)
        target_2x = round(entry_price + 2.0 * atr, 2)
        target_3x = round(entry_price + target_mult * atr, 2)

        risk_from_current = max(current_price - stop_normal, 0.01)
        reward_from_current = target_3x - current_price
        rr_ratio = reward_from_current / risk_from_current if risk_from_current > 0 else 0

        if rr_ratio > 2.5:
            rr_interp = "EXCELLENT"
        elif rr_ratio > 2.0:
            rr_interp = "GOOD"
        elif rr_ratio > 1.5:
            rr_interp = "MARGINAL"
        else:
            rr_interp = "POOR"

        return ATRContext(
            atr_value=round(atr, 2),
            atr_pct_of_price=round(atr_pct, 2),
            current_drop_from_entry=round(drop, 2),
            drop_as_atr_multiple=round(drop_atr_mult, 2),
            drop_interpretation=drop_interp,
            suggested_stop_conservative=stop_conservative,
            suggested_stop_normal=stop_normal,
            suggested_target_2x=target_2x,
            suggested_target_3x=target_3x,
            risk_reward_from_current=round(rr_ratio, 2),
            risk_reward_interpretation=rr_interp
        )

    # ═══════════════════════════════════════════════════════════════════
    # LAYER 5: COMPOSITE SCORER
    # ═══════════════════════════════════════════════════════════════════

    def _compute_composite_score(self, symbol: str, stock_monitor,
                                   v_recovery_data: Dict,
                                   all_candidates: List[Dict] = None) -> Optional[CompositeScore]:
        if not getattr(self.config, 'ENABLE_MIE_COMPOSITE', True):
            return None

        entry_price = self._safe_price(stock_monitor)
        atr = getattr(stock_monitor, 'atr', None) or (entry_price * 0.015)

        # 1. Risk-Reward (25 pts) — Use actual target/stop from stock data if available
        target = getattr(stock_monitor, 'target_price', 0) or getattr(stock_monitor, 'target', 0)
        stop = getattr(stock_monitor, 'stop_price', 0) or getattr(stock_monitor, 'stop_loss', 0)

        # Fallback to ATR-based estimates if stock doesn't have real targets
        if target <= 0:
            target_pct = getattr(self.config, 'PROFIT_TARGET_PCT', 3.0)
            target = entry_price * (1 + target_pct / 100)
        if stop <= 0:
            stop_pct = getattr(self.config, 'STOP_LOSS_PCT', 2.0)
            stop = entry_price * (1 - stop_pct / 100)

        reward = target - entry_price
        risk = entry_price - stop
        rr = reward / max(risk, 0.01) if risk > 0 else 0

        if rr >= 3.0:
            rr_score = 25
        elif rr >= 2.5:
            rr_score = 22
        elif rr >= 2.0:
            rr_score = 18
        elif rr >= 1.5:
            rr_score = 12
        elif rr >= 1.0:
            rr_score = 6
        else:
            rr_score = 0

        # 2. V-Recovery Quality (20 pts)
        vr_score = 0.0
        if v_recovery_data:
            v_rec = self._compute_v_recovery_quality(v_recovery_data, stock_monitor)
            if v_rec:
                vr_score = min(20, v_rec.quality_score)

        # 3. Trend Alignment (15 pts)
        ema21 = getattr(stock_monitor, 'ema21', 0) or 0
        ema50 = getattr(stock_monitor, 'ema50', 0) or 0

        if entry_price > ema21 > ema50 > 0:
            trend_score = 15
        elif (entry_price > ema21 > 0) or (entry_price > ema50 > 0):
            trend_score = 10
        else:
            trend_score = 0

        # 4. Volume Confirmation (15 pts)
        vol_ratio = getattr(stock_monitor, 'volume_ratio', 1.0) or 1.0

        if vol_ratio >= 1.5:
            vol_score = 15
        elif vol_ratio >= 1.2:
            vol_score = 10
        else:
            vol_score = 5

        # 5. Session Timing (10 pts)
        now = datetime.now().time()
        if dt_time(9, 15) <= now <= dt_time(10, 15):
            timing_score = 10
        elif dt_time(10, 15) < now <= dt_time(12, 0):
            timing_score = 6
        elif dt_time(12, 0) < now <= dt_time(13, 30):
            timing_score = 3
        elif dt_time(13, 30) < now <= dt_time(15, 0):
            timing_score = 6
        else:
            timing_score = 3

        # 6. Indicator Confluence (10 pts)
        aligned_count = 0
        rsi = getattr(stock_monitor, 'rsi', 50) or 50
        adx = getattr(stock_monitor, 'adx_value', None) or getattr(stock_monitor, 'adx', 0) or 0

        if rsi < 40:
            aligned_count += 1
        if adx < 25:
            aligned_count += 1
        if vol_ratio >= 1.2:
            aligned_count += 1
        if v_recovery_data:
            aligned_count += 1

        if aligned_count >= 3:
            confluence_score = 10
        elif aligned_count >= 2:
            confluence_score = 7
        else:
            confluence_score = 4

        # 7. Liquidity (5 pts)
        stock_meta = self.phase1_data.get(symbol, {})
        is_fno = stock_meta.get('is_fno', False)
        liquidity_score = 5 if is_fno else 0

        # Total
        total = rr_score + vr_score + trend_score + vol_score + timing_score + confluence_score + liquidity_score

        full_thresh = getattr(self.config, 'MIE_COMPOSITE_FULL_THRESHOLD', 85)
        t75_thresh = getattr(self.config, 'MIE_COMPOSITE_75_THRESHOLD', 70)
        t50_thresh = getattr(self.config, 'MIE_COMPOSITE_50_THRESHOLD', 60)

        if total >= full_thresh:
            size_rec = "FULL"
        elif total >= t75_thresh:
            size_rec = "75%"
        elif total >= t50_thresh:
            size_rec = "50%"
        else:
            size_rec = "SKIP"

        # Ranking Among Candidates
        rank = 0
        total_candidates = 0
        if all_candidates:
            total_candidates = len(all_candidates)
            sorted_candidates = sorted(all_candidates, key=lambda x: x.get('composite_score', 0), reverse=True)
            for i, c in enumerate(sorted_candidates):
                if c.get('symbol') == symbol:
                    rank = i + 1
                    break

        return CompositeScore(
            total_score=round(total, 1),
            risk_reward_score=rr_score,
            v_recovery_score=round(vr_score, 1),
            trend_alignment_score=trend_score,
            volume_confirmation_score=vol_score,
            session_timing_score=timing_score,
            indicator_confluence_score=confluence_score,
            liquidity_score=liquidity_score,
            position_size_recommendation=size_rec,
            rank_among_candidates=rank,
            total_candidates=total_candidates
        )

    # ═══════════════════════════════════════════════════════════════════
    # LAYER 6: EXPIRY CYCLE
    # ═══════════════════════════════════════════════════════════════════

    def _compute_expiry_cycle(self) -> Optional[ExpiryCycleContext]:
        if not getattr(self.config, 'ENABLE_MIE_EXPIRY_CYCLE', True):
            return None

        now = datetime.now()
        weekday = now.weekday()  # 0=Mon, 1=Tue, ..., 4=Fri
        weekday_name = now.strftime("%A")

        expiry_weekday = getattr(self.config, 'MIE_NSE_EXPIRY_WEEKDAY', 1)  # Tuesday
        expiry_day_name = "Tuesday"

        days_to_expiry = (expiry_weekday - weekday) % 7
        if days_to_expiry == 0 and now.time() > dt_time(15, 30):
            days_to_expiry = 7

        cycle_map = {
            0: ("EXPIRY_EVE", "SELLING_PRESSURE",
                "Monday: Expiry eve. Extreme volatility expected. Avoid fresh entries unless strong conviction.",
                False, True),
            1: ("EXPIRY_DAY", "SELLING_PRESSURE",
                "Tuesday: EXPIRY DAY. Maximum artificial selling pressure from gamma hedging. Oversold conditions created today reverse tomorrow.",
                False, True),
            2: ("POST_EXPIRY_DAY_1", "BUYING_PRESSURE_BEGINS",
                "Wednesday: Post-expiry Day 1. Short covering begins. Oversold bounce initiates. Best entry day for V-Recovery.",
                True, False),
            3: ("POST_EXPIRY_DAY_2", "BUYING_CONTINUES",
                "Thursday: Post-expiry Day 2. If Wednesday showed recovery, Thursday confirms. Second-best entry day.",
                True, False),
            4: ("NORMAL", "NEUTRAL",
                "Friday: Normal trading. Next week positioning starts. Avoid late entries - weekend gap risk.",
                False, False),
        }

        position, pressure, implication, good_entry, dangerous = cycle_map.get(
            weekday, ("NORMAL", "NEUTRAL", "Weekend", False, False)
        )

        return ExpiryCycleContext(
            today_weekday=weekday_name,
            expiry_day=expiry_day_name,
            days_to_expiry=days_to_expiry,
            cycle_position=position,
            expected_pressure=pressure,
            trading_implication=implication,
            is_good_entry_day=good_entry,
            is_dangerous_day=dangerous
        )

    # ═══════════════════════════════════════════════════════════════════
    # LAYER 7: DECISION HISTORY
    # ═══════════════════════════════════════════════════════════════════

    def _compute_decision_history(self, symbol: str = None,
                                    current_setup: Dict = None) -> Optional[DecisionHistoryContext]:
        if not getattr(self.config, 'ENABLE_MIE_DECISION_HISTORY', True):
            return None
        if not self.decision_history:
            return None

        try:
            accuracy = self.decision_history.get_decision_accuracy(symbol, days=30)
            similar = self.decision_history.get_similar_historical_cases(
                symbol=symbol,
                current_setup=current_setup or {}
            ) if symbol else []

            total = accuracy.get('total_decisions', 0)
            # The decision_history.get_decision_accuracy returns different keys
            # depending on version; handle both formats
            by_type = accuracy.get('by_decision_type', {})
            exit_acc = by_type.get('EXIT', accuracy.get('exit_accuracy_pct', 0))
            hold_acc = by_type.get('HOLD', accuracy.get('hold_accuracy_pct', 0))

            adx_low_acc = accuracy.get('accuracy_adx_below_20', 0)
            adx_high_acc = accuracy.get('accuracy_adx_above_25', 0)

            # Generate learning insight
            min_decisions = getattr(self.config, 'MIE_MIN_DECISIONS_FOR_INSIGHT', 10)
            insight = ""
            if total >= min_decisions:
                if isinstance(exit_acc, (int, float)) and exit_acc < 50:
                    insight = f"WARNING: Your EXIT accuracy is only {exit_acc:.0f}%. Consider HOLD more often."
                if isinstance(adx_low_acc, (int, float)) and adx_low_acc > 0 and adx_low_acc < 40:
                    insight += f" EXIT accuracy drops to {adx_low_acc:.0f}% when ADX < 20 (ranging)."
            else:
                insight = f"Only {total} decisions tracked. Need {min_decisions}+ for reliable patterns."

            return DecisionHistoryContext(
                total_decisions=total,
                exit_accuracy_pct=exit_acc if isinstance(exit_acc, (int, float)) else 0,
                hold_accuracy_pct=hold_acc if isinstance(hold_acc, (int, float)) else 0,
                accuracy_by_adx_low=adx_low_acc if isinstance(adx_low_acc, (int, float)) else 0,
                accuracy_by_adx_high=adx_high_acc if isinstance(adx_high_acc, (int, float)) else 0,
                similar_past_cases=similar[:5] if isinstance(similar, list) else [],
                learning_insight=insight
            )
        except Exception as e:
            logger.warning(f"MIE: Decision history failed: {e}")
            return None

    # ═══════════════════════════════════════════════════════════════════
    # LAYER 8: PERFORMANCE METRICS
    # ═══════════════════════════════════════════════════════════════════

    def _compute_performance_metrics(self) -> Optional[PerformanceMetrics]:
        if not getattr(self.config, 'ENABLE_MIE_PERFORMANCE', True):
            return None

        p3_stats = {'trades': 0, 'wins': 0, 'total_profit': 0, 'total_loss': 0}
        p5_stats = {'trades': 0, 'wins': 0, 'total_profit': 0, 'total_loss': 0}

        if self.decision_history:
            try:
                # Try get_all_outcomes if available; else use accuracy stats
                if hasattr(self.decision_history, 'get_all_outcomes'):
                    all_outcomes = self.decision_history.get_all_outcomes()
                    for outcome in (all_outcomes or []):
                        source = outcome.get('phase_source', 'PHASE_3')
                        pnl = outcome.get('pnl_pct', 0) or outcome.get('actual_pnl', 0)
                        stats = p5_stats if 'PHASE5' in str(source).upper() else p3_stats
                        stats['trades'] += 1
                        if pnl > 0:
                            stats['wins'] += 1
                            stats['total_profit'] += pnl
                        else:
                            stats['total_loss'] += abs(pnl)
            except Exception:
                pass

        p3_wr = (p3_stats['wins'] / p3_stats['trades'] * 100) if p3_stats['trades'] > 0 else 0
        p5_wr = (p5_stats['wins'] / p5_stats['trades'] * 100) if p5_stats['trades'] > 0 else 0
        p3_avg_profit = (p3_stats['total_profit'] / max(1, p3_stats['wins']))
        p3_avg_loss = (p3_stats['total_loss'] / max(1, p3_stats['trades'] - p3_stats['wins']))

        bt_wr = getattr(self.config, 'LAST_BACKTEST_WIN_RATE', 0)
        gap = bt_wr - p3_wr

        total_real = p3_stats['trades'] + p5_stats['trades']
        if total_real >= 50:
            note = f"{total_real} real trades: RELIABLE performance data"
        elif total_real >= 20:
            note = f"{total_real} real trades: Moderate confidence, patterns emerging"
        else:
            note = f"{total_real} real trades: LOW confidence, treat metrics with caution"

        return PerformanceMetrics(
            phase3_real_trades=p3_stats['trades'],
            phase3_real_win_rate=round(p3_wr, 1),
            phase3_real_avg_profit_pct=round(p3_avg_profit, 2),
            phase3_real_avg_loss_pct=round(p3_avg_loss, 2),
            phase5_real_trades=p5_stats['trades'],
            phase5_real_win_rate=round(p5_wr, 1),
            backtest_win_rate=bt_wr,
            backtest_vs_real_gap=round(gap, 1),
            confidence_note=note
        )

    # ═══════════════════════════════════════════════════════════════════
    # LAYER 9: CAPITAL STATE
    # ═══════════════════════════════════════════════════════════════════

    def _compute_capital_state(self, entry_price: float = 0) -> Optional[CapitalState]:
        if not getattr(self.config, 'ENABLE_MIE_CAPITAL', True):
            return None

        if not self.capital_manager:
            total = getattr(self.config, 'TOTAL_CAPITAL', 20000)
            return CapitalState(
                total_capital=total,
                deployed_amount=0, available_amount=total,
                deployed_positions=[], concentration_limit_pct=0.25,
                max_per_stock=total * 0.25, can_fit_new_entry=entry_price <= total * 0.25,
                entry_budget=total * 0.25, buffer_remaining=total
            )

        cm = self.capital_manager

        total = getattr(cm, 'total_capital', 0) or getattr(self.config, 'TOTAL_CAPITAL', 20000)
        deployed = getattr(cm, 'deployed_capital', 0) or 0
        available = total - deployed

        cap_mgmt = getattr(self.config, 'CAPITAL_MANAGEMENT', {})
        conc_pct = cap_mgmt.get('MAX_CONCENTRATION_PCT', 0.40)
        max_per = total * conc_pct

        can_fit = entry_price > 0 and entry_price <= available and entry_price <= max_per
        entry_budget = min(available, max_per)
        buffer = available - entry_price if entry_price > 0 else available

        positions_summary = []
        deployed_positions = getattr(cm, 'deployed_positions', {})
        if isinstance(deployed_positions, dict):
            for sym, pos in deployed_positions.items():
                if isinstance(pos, dict):
                    positions_summary.append({
                        'symbol': sym,
                        'amount': pos.get('deployed_amount', pos.get('amount', 0)),
                        'pnl_pct': pos.get('pnl_pct', 0)
                    })

        return CapitalState(
            total_capital=round(total, 2),
            deployed_amount=round(deployed, 2),
            available_amount=round(max(0, available), 2),
            deployed_positions=positions_summary,
            concentration_limit_pct=conc_pct,
            max_per_stock=round(max_per, 2),
            can_fit_new_entry=can_fit,
            entry_budget=round(max(0, entry_budget), 2),
            buffer_remaining=round(max(0, buffer), 2)
        )

    # ═══════════════════════════════════════════════════════════════════
    # LAYER 10: CRASH MATRIX
    # ═══════════════════════════════════════════════════════════════════

    def _compute_crash_matrix(self, phase_source: str, product_type: str) -> Optional[CrashMatrix]:
        if not getattr(self.config, 'ENABLE_MIE_CRASH_MATRIX', True):
            return None

        matrix = {
            "PHASE_2": {
                "CNC": {
                    "meaning": "POTENTIAL_ENTRY",
                    "patience": "HIGH_PATIENCE",
                    "philosophy": "This phase LOOKS FOR drops. Price decline = potential V-Recovery entry. Verify with VWAP, ADX, volume before entering. Don't fear red - evaluate quality.",
                    "instruction": "Evaluate this as a BUYING OPPORTUNITY. The drop is why we're looking at this stock. Score the bounce quality, don't just react to the decline."
                },
                "MIS": {
                    "meaning": "POTENTIAL_ENTRY",
                    "patience": "LOW_PATIENCE",
                    "philosophy": "Intraday entry. Must recover within session.",
                    "instruction": "Quick entry evaluation. If bounce quality is high, enter. MIS = must close today."
                }
            },
            "PHASE_3_CNC": {
                "CNC": {
                    "meaning": "DANGER_TO_CAPITAL",
                    "patience": "HIGH_PATIENCE",
                    "philosophy": "CNC holding experiencing drawdown. Do NOT panic exit on intraday noise. Only exit if: (1) ADX > 25 confirms real trend breakdown, (2) Price breaks below VWAP 2s, (3) Weekly trend reverses. Normal dips within 1.5x ATR are noise - HOLD.",
                    "instruction": "This is a CNC HOLDING under stress. Apply PATIENCE. Check ADX (trending or ranging?), ATR (normal noise or real breakdown?), VWAP (institutional zone or abandoned?). Bias toward HOLD unless multiple breakdown signals align."
                }
            },
            "PHASE_5_MIS": {
                "MIS": {
                    "meaning": "BUYING_OPPORTUNITY",
                    "patience": "LOW_PATIENCE",
                    "philosophy": "Phase 5 gap strategy SEEKS crashes. Gap down at market open = mean reversion opportunity. The bigger the gap, the bigger the potential bounce.",
                    "instruction": "This is Phase 5 MIS gap trading. The crash IS the thesis. DO NOT advise caution about the decline - evaluate BOUNCE QUALITY. Speed matters - this is a 15-minute window."
                }
            },
            "PHASE_6_OPTIONS": {
                "MIS": {
                    "meaning": "OPTIONS_DANGER",
                    "patience": "MEDIUM",
                    "philosophy": "Options shadow tracking CNC stock. If CNC TCAS fires RA, the options position must evaluate protective action.",
                    "instruction": "Phase 6 options shadow. The underlying CNC stock is showing deceleration (TCAS RA). Evaluate whether to: tighten options stop, partial exit, or hold."
                }
            }
        }

        phase_data = matrix.get(phase_source, {}).get(product_type, {})

        if not phase_data:
            phase_data = {
                "meaning": "UNKNOWN_CONTEXT",
                "patience": "MEDIUM",
                "philosophy": "Unknown phase/product combination. Apply standard risk management.",
                "instruction": "Apply balanced analysis. Check all technical indicators before deciding."
            }

        return CrashMatrix(
            phase_source=phase_source,
            product_type=product_type,
            crash_meaning=phase_data["meaning"],
            patience_level=phase_data["patience"],
            exit_trigger_philosophy=phase_data["philosophy"],
            crash_response_instruction=phase_data["instruction"]
        )

    # ═══════════════════════════════════════════════════════════════════
    # PRIVATE HELPERS
    # ═══════════════════════════════════════════════════════════════════

    def _empty_package(self) -> IntelligencePackage:
        """Return an empty package when MIE is disabled."""
        return IntelligencePackage(
            vwap=None, momentum=None, v_recovery=None, atr=None,
            composite=None, expiry_cycle=None, decision_history=None,
            performance=None, capital=None, crash_matrix=None,
            generated_at=datetime.now().isoformat()
        )

    def _safe_compute(self, func, *args, **kwargs):
        """Call a layer computation function, returning None on any error."""
        try:
            return func(*args, **kwargs)
        except Exception as e:
            logger.warning(f"MIE: {func.__name__} failed: {e}")
            return None

    def _safe_price(self, stock_monitor) -> float:
        """Extract current price from stock monitor safely."""
        for attr in ('current_price', 'ltp', 'last_price', 'close'):
            val = getattr(stock_monitor, attr, None)
            if val and val > 0:
                return float(val)
        return 0.0

    def _get_instrument_token(self, symbol: str) -> Optional[int]:
        """Get instrument token for Kite API calls."""
        meta = self.phase1_data.get(symbol, {})
        token = meta.get('instrument_token', None)
        if token:
            return int(token)
        return None

    def _get_prev_day_data(self, symbol: str) -> Dict:
        """Get previous day's POC and Value Area. Cached daily."""
        today = datetime.now().date()
        cache_key = f"{symbol}_{today}"

        if cache_key in self._prev_day_cache:
            return self._prev_day_cache[cache_key]

        try:
            yesterday = today - timedelta(days=1)
            while yesterday.weekday() >= 5:
                yesterday -= timedelta(days=1)

            if self.kite:
                token = self._get_instrument_token(symbol)
                if token:
                    candles = self.kite.historical_data(
                        token, yesterday, yesterday, "15minute"
                    )
                    if candles:
                        result = self._calculate_poc_value_area(candles)
                        self._prev_day_cache[cache_key] = result
                        return result
        except Exception as e:
            logger.debug(f"MIE: Failed to get prev day data for {symbol}: {e}")

        return {'poc': 0, 'value_area_high': 0, 'value_area_low': 0}

    def _calculate_poc_value_area(self, candles: list) -> Dict:
        """Calculate Point of Control and Value Area from candle data."""
        if not candles:
            return {'poc': 0, 'value_area_high': 0, 'value_area_low': 0}

        volume_profile: Dict[int, float] = {}
        total_volume = 0

        for candle in candles:
            high = candle.get('high', 0)
            low = candle.get('low', 0)
            close = candle.get('close', 0)
            vol = candle.get('volume', 0)
            typical_price = (high + low + close) / 3 if (high + low + close) > 0 else 0

            price_level = round(typical_price)
            if price_level > 0:
                volume_profile[price_level] = volume_profile.get(price_level, 0) + vol
                total_volume += vol

        if total_volume == 0 or not volume_profile:
            return {'poc': 0, 'value_area_high': 0, 'value_area_low': 0}

        poc = max(volume_profile, key=volume_profile.get)

        target_volume = total_volume * 0.70
        accumulated = volume_profile[poc]
        va_low = poc
        va_high = poc

        sorted_levels = sorted(volume_profile.keys())
        poc_idx = sorted_levels.index(poc) if poc in sorted_levels else len(sorted_levels) // 2

        low_idx = poc_idx - 1
        high_idx = poc_idx + 1

        while accumulated < target_volume:
            vol_below = volume_profile.get(sorted_levels[low_idx], 0) if 0 <= low_idx < len(sorted_levels) else 0
            vol_above = volume_profile.get(sorted_levels[high_idx], 0) if 0 <= high_idx < len(sorted_levels) else 0

            if vol_below == 0 and vol_above == 0:
                break

            if vol_above >= vol_below and high_idx < len(sorted_levels):
                accumulated += vol_above
                va_high = sorted_levels[high_idx]
                high_idx += 1
            elif low_idx >= 0:
                accumulated += vol_below
                va_low = sorted_levels[low_idx]
                low_idx -= 1
            else:
                break

        return {
            'poc': poc,
            'value_area_high': va_high,
            'value_area_low': va_low
        }
