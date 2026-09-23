"""
Algo_Beta — Ensemble Prediction Engine
========================================
Combines 4 prediction methods with dynamic weighting:
  1. Kalman Filter (state-based, real-time)
  2. Linear Regression (trend baseline)
  3. Polynomial Regression (curved trajectory)
  4. Hurst Exponent (regime detection → weight adjuster)

Usage:
    from prediction_engine import EnsemblePrediction

    engine = EnsemblePrediction()

    result = engine.predict(
        prices=[882, 884, 885, 888, 890, 893, 895, 897, 900, 905.3],
        timestamps=[0, 5, 10, 15, 20, 25, 30, 35, 40, 45],  # minutes
        current_price=905.3,
        kalman_state={"velocity": 1.8, "acceleration": 0.12},
        prediction_horizon=20,  # predict 20 minutes ahead
        prediction_step=2,      # one point every 2 minutes
        atr=8.5,                # for uncertainty calculation
        accuracy_history=None,  # optional: past accuracy from prediction_store
    )

    # result contains:
    # result.ensemble_path     → [{t:0, p:905.3}, ...]  (final weighted prediction)
    # result.kalman_path       → individual Kalman prediction
    # result.linear_path       → individual linear regression prediction
    # result.polynomial_path   → individual polynomial prediction
    # result.weights           → {"kalman": 0.45, "linear": 0.25, "polynomial": 0.30}
    # result.hurst             → 0.72 (Hurst exponent value)
    # result.regime            → "TRENDING" / "MEAN_REVERTING" / "RANDOM_WALK"
    # result.confidence        → 0.78 (0-1 scale)
    # result.uncertainty_cone  → [{t:2, upper:907.5, lower:906.1}, ...]
"""

import numpy as np
import math
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple


# ═══════════════════════════════════════════════════════════
#  DATA CLASSES
# ═══════════════════════════════════════════════════════════

@dataclass
class PredictionPoint:
    """Single point on a prediction path."""
    t: float          # time offset from now (in same units as input timestamps)
    p: float          # predicted price

@dataclass
class UncertaintyBound:
    """Upper and lower bounds at a time point."""
    t: float
    upper: float
    lower: float

@dataclass
class PredictionResult:
    """Complete prediction output from the ensemble engine."""

    # The final weighted prediction (THIS is what you plot)
    ensemble_path: List[PredictionPoint] = field(default_factory=list)

    # Individual model predictions (for overlay/debugging)
    kalman_path: List[PredictionPoint] = field(default_factory=list)
    linear_path: List[PredictionPoint] = field(default_factory=list)
    polynomial_path: List[PredictionPoint] = field(default_factory=list)

    # Model weights (sum to 1.0)
    weights: Dict[str, float] = field(default_factory=dict)

    # Hurst analysis
    hurst: float = 0.5              # Hurst exponent (0-1)
    regime: str = "RANDOM_WALK"     # TRENDING / MEAN_REVERTING / RANDOM_WALK

    # Overall confidence (0-1)
    confidence: float = 0.5

    # Uncertainty cone
    uncertainty_cone: List[UncertaintyBound] = field(default_factory=list)

    # Metadata
    models_used: List[str] = field(default_factory=list)
    lookback_bars: int = 0


# ═══════════════════════════════════════════════════════════
#  MODEL 1: KALMAN PREDICTION
# ═══════════════════════════════════════════════════════════

def predict_kalman(current_price: float, velocity: float, acceleration: float,
                   horizon: float, step: float) -> List[PredictionPoint]:
    """
    Kalman state-based prediction.
    Uses current estimated state (price, velocity, acceleration) to extrapolate.

    Formula: price(t) = current + velocity * t + 0.5 * acceleration * t^2

    This is NOT running the Kalman filter — it's using the Kalman filter's
    CURRENT state estimate to project forward. The actual Kalman update
    happens in the trading code (phase4_portfolio_manager.py).

    Args:
        current_price: Current estimated price (Kalman state)
        velocity: Estimated price velocity (units/time)
        acceleration: Estimated price acceleration (units/time^2)
        horizon: How far ahead to predict (same time units)
        step: Time step between prediction points

    Returns:
        List of PredictionPoints
    """
    points = []
    t = 0
    while t <= horizon:
        p = current_price + velocity * t + 0.5 * acceleration * t * t
        points.append(PredictionPoint(t=t, p=p))
        t += step
    return points


# ═══════════════════════════════════════════════════════════
#  MODEL 2: LINEAR REGRESSION PREDICTION
# ═══════════════════════════════════════════════════════════

def predict_linear(timestamps: np.ndarray, prices: np.ndarray,
                   horizon: float, step: float) -> Tuple[List[PredictionPoint], float, float, float]:
    """
    Linear regression prediction using Ordinary Least Squares (OLS).
    Fits y = mx + b to historical data, then extrapolates.

    OLS formulas:
        m = (n*Sxy - Sx*Sy) / (n*Sx2 - (Sx)^2)
        b = (Sy - m*Sx) / n

    Args:
        timestamps: Array of time values (x)
        prices: Array of price values (y)
        horizon: Prediction horizon
        step: Time step

    Returns:
        (prediction_points, slope_m, intercept_b, r_squared)
    """
    n = len(timestamps)
    x = np.array(timestamps, dtype=float)
    y = np.array(prices, dtype=float)

    # OLS calculation
    sum_x = np.sum(x)
    sum_y = np.sum(y)
    sum_xy = np.sum(x * y)
    sum_x2 = np.sum(x * x)

    denominator = n * sum_x2 - sum_x * sum_x
    if abs(denominator) < 1e-10:
        # Degenerate case — all x values are the same
        m = 0.0
        b = np.mean(y)
    else:
        m = (n * sum_xy - sum_x * sum_y) / denominator
        b = (sum_y - m * sum_x) / n

    # R^2 (coefficient of determination) — how well the line fits
    y_pred_hist = m * x + b
    ss_res = np.sum((y - y_pred_hist) ** 2)
    ss_tot = np.sum((y - np.mean(y)) ** 2)
    r_squared = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0

    # Generate prediction points
    last_t = timestamps[-1]
    points = []
    t = 0
    while t <= horizon:
        future_t = last_t + t
        p = m * future_t + b
        points.append(PredictionPoint(t=t, p=p))
        t += step

    return points, m, b, r_squared


# ═══════════════════════════════════════════════════════════
#  MODEL 3: POLYNOMIAL REGRESSION PREDICTION
# ═══════════════════════════════════════════════════════════

def predict_polynomial(timestamps: np.ndarray, prices: np.ndarray,
                       horizon: float, step: float,
                       degree: int = 2) -> Tuple[List[PredictionPoint], np.ndarray, float]:
    """
    Polynomial regression prediction.
    Fits y = b0 + b1*x + b2*x^2 (2nd degree by default — captures acceleration).

    Uses matrix algebra: beta_hat = (X'X)^-1 X'Y

    Args:
        timestamps: Array of time values
        prices: Array of price values
        horizon: Prediction horizon
        step: Time step
        degree: Polynomial degree (2 = quadratic, 3 = cubic)

    Returns:
        (prediction_points, coefficients, r_squared)
    """
    x = np.array(timestamps, dtype=float)
    y = np.array(prices, dtype=float)

    # Normalize x to prevent numerical instability with large values
    x_mean = np.mean(x)
    x_std = np.std(x) if np.std(x) > 0 else 1.0
    x_norm = (x - x_mean) / x_std

    # Build Vandermonde matrix: [1, x, x^2, x^3, ...]
    X = np.column_stack([x_norm ** i for i in range(degree + 1)])

    # Solve using least squares: beta_hat = (X'X)^-1 X'Y
    try:
        # Use numpy's lstsq for numerical stability (better than direct inverse)
        coeffs, residuals, rank, sv = np.linalg.lstsq(X, y, rcond=None)
    except np.linalg.LinAlgError:
        # Fallback to pseudo-inverse
        coeffs = np.linalg.pinv(X) @ y

    # R^2 calculation
    y_pred_hist = X @ coeffs
    ss_res = np.sum((y - y_pred_hist) ** 2)
    ss_tot = np.sum((y - np.mean(y)) ** 2)
    r_squared = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0

    # Generate prediction points
    last_t = timestamps[-1]
    points = []
    t = 0
    while t <= horizon:
        future_t = last_t + t
        future_t_norm = (future_t - x_mean) / x_std
        p = sum(coeffs[i] * (future_t_norm ** i) for i in range(len(coeffs)))
        points.append(PredictionPoint(t=t, p=p))
        t += step

    # Detect if polynomial is diverging unreasonably
    # (polynomial regression can go wild beyond the data range)
    if len(points) > 2:
        max_change = abs(points[-1].p - points[0].p)
        data_range = max(prices) - min(prices)
        if data_range > 0 and max_change > data_range * 5:
            # Polynomial is diverging — cap it
            _cap_diverging_predictions(points, prices[-1], data_range * 3)

    return points, coeffs, r_squared


def _cap_diverging_predictions(points: List[PredictionPoint],
                                current_price: float, max_deviation: float):
    """Prevent polynomial predictions from going to infinity."""
    for pt in points:
        if pt.p > current_price + max_deviation:
            pt.p = current_price + max_deviation
        elif pt.p < current_price - max_deviation:
            pt.p = current_price - max_deviation


# ═══════════════════════════════════════════════════════════
#  MODEL 4: HURST EXPONENT (Regime Detection)
# ═══════════════════════════════════════════════════════════

def calculate_hurst(prices: np.ndarray, min_window: int = 4) -> float:
    """
    Calculate the Hurst exponent using Rescaled Range (R/S) analysis.

    The Hurst exponent H determines the nature of the time series:
        H = 0.5  -> Random walk (unpredictable)
        H > 0.5  -> Trending (persistent — current direction will continue)
        H < 0.5  -> Mean-reverting (anti-persistent — will reverse)

    Formula:
        E[R(n)/S(n)] = C * n^H

    Where:
        R(n) = range of cumulative deviations from mean over window n
        S(n) = standard deviation over window n

    We calculate R/S for multiple window sizes, then fit log(R/S) vs log(n)
    to get H as the slope.

    Args:
        prices: Array of prices (minimum 20 points recommended)
        min_window: Minimum sub-series length

    Returns:
        Hurst exponent (float, typically 0.3 to 0.8)
    """
    ts = np.array(prices, dtype=float)
    n = len(ts)

    if n < min_window * 2:
        return 0.5  # Not enough data — assume random walk

    # Calculate returns (log returns for better statistical properties)
    returns = np.diff(np.log(ts))
    returns = returns[np.isfinite(returns)]  # Remove any inf/nan

    if len(returns) < min_window * 2:
        return 0.5

    # Generate window sizes (powers of 2, plus some intermediate values)
    max_window = len(returns) // 2
    window_sizes = []
    w = min_window
    while w <= max_window:
        window_sizes.append(w)
        w = max(w + 1, int(w * 1.5))

    if len(window_sizes) < 3:
        return 0.5  # Not enough window sizes for reliable fit

    rs_values = []

    for window in window_sizes:
        # Split returns into non-overlapping sub-series of length 'window'
        n_subseries = len(returns) // window
        if n_subseries < 1:
            continue

        rs_for_this_window = []

        for i in range(n_subseries):
            subseries = returns[i * window : (i + 1) * window]

            # Mean of subseries
            mean_val = np.mean(subseries)

            # Cumulative deviation from mean
            cumulative_dev = np.cumsum(subseries - mean_val)

            # Range
            R = np.max(cumulative_dev) - np.min(cumulative_dev)

            # Standard deviation
            S = np.std(subseries, ddof=1)

            if S > 0 and R > 0:
                rs_for_this_window.append(R / S)

        if rs_for_this_window:
            rs_values.append((window, np.mean(rs_for_this_window)))

    if len(rs_values) < 3:
        return 0.5

    # Fit log(R/S) vs log(n) — slope = Hurst exponent
    log_n = np.log([rs[0] for rs in rs_values])
    log_rs = np.log([rs[1] for rs in rs_values])

    # Simple linear regression for the slope
    n_pts = len(log_n)
    sum_x = np.sum(log_n)
    sum_y = np.sum(log_rs)
    sum_xy = np.sum(log_n * log_rs)
    sum_x2 = np.sum(log_n * log_n)

    denom = n_pts * sum_x2 - sum_x * sum_x
    if abs(denom) < 1e-10:
        return 0.5

    H = (n_pts * sum_xy - sum_x * sum_y) / denom

    # Clamp to valid range
    H = max(0.01, min(0.99, H))

    return H


def classify_regime(hurst: float) -> str:
    """Classify market regime from Hurst exponent."""
    if hurst > 0.6:
        return "TRENDING"
    elif hurst < 0.4:
        return "MEAN_REVERTING"
    else:
        return "RANDOM_WALK"


# ═══════════════════════════════════════════════════════════
#  ENSEMBLE WEIGHTING
# ═══════════════════════════════════════════════════════════

def calculate_weights(hurst: float, r2_linear: float, r2_poly: float,
                      accuracy_history: Optional[Dict] = None) -> Dict[str, float]:
    """
    Calculate dynamic weights for each prediction model.

    Two factors determine weights:
    1. Hurst exponent (regime) — trending favors Kalman, mean-reverting favors regression
    2. Historical accuracy — models that were recently accurate get more weight

    Args:
        hurst: Hurst exponent value
        r2_linear: R^2 of linear regression fit
        r2_poly: R^2 of polynomial regression fit
        accuracy_history: Optional dict from prediction_store with past accuracy:
            {"kalman_error": float, "linear_error": float, "poly_error": float}

    Returns:
        Dict of weights summing to 1.0
    """
    # -- Step 1: Base weights from regime --
    regime = classify_regime(hurst)

    if regime == "TRENDING":
        # Trending market: trust Kalman (captures momentum) and polynomial (captures curve)
        base = {"kalman": 0.50, "linear": 0.15, "polynomial": 0.35}
    elif regime == "MEAN_REVERTING":
        # Mean-reverting: trust linear regression (regression to mean)
        # Kalman may overshoot because it follows momentum
        base = {"kalman": 0.20, "linear": 0.45, "polynomial": 0.35}
    else:
        # Random walk: equal-ish weights, slight Kalman preference (most reactive)
        base = {"kalman": 0.35, "linear": 0.30, "polynomial": 0.35}

    # -- Step 2: Adjust by R^2 (regression quality) --
    # If linear R^2 is high, boost linear weight
    # If polynomial R^2 is high, boost polynomial weight
    r2_boost = 0.15  # Maximum boost from R^2

    if r2_linear > 0.8:
        base["linear"] += r2_boost * (r2_linear - 0.8) / 0.2
    if r2_poly > 0.8:
        base["polynomial"] += r2_boost * (r2_poly - 0.8) / 0.2

    # If R^2 is very low, penalize that model
    if r2_linear < 0.3:
        base["linear"] *= 0.5
    if r2_poly < 0.3:
        base["polynomial"] *= 0.5

    # -- Step 3: Adjust by historical accuracy (if available) --
    if accuracy_history:
        # Models with lower recent error get higher weight
        errors = {
            "kalman": accuracy_history.get("kalman_error", 1.0),
            "linear": accuracy_history.get("linear_error", 1.0),
            "polynomial": accuracy_history.get("poly_error", 1.0),
        }

        # Convert errors to scores (lower error = higher score)
        total_err = sum(errors.values())
        if total_err > 0:
            accuracy_weights = {
                k: (1 - e / total_err) for k, e in errors.items()
            }

            # Blend: 60% regime-based, 40% accuracy-based
            for model in base:
                if model in accuracy_weights:
                    base[model] = 0.6 * base[model] + 0.4 * accuracy_weights[model]

    # -- Step 4: Normalize to sum = 1.0 --
    total = sum(base.values())
    if total > 0:
        base = {k: v / total for k, v in base.items()}

    return base


# ═══════════════════════════════════════════════════════════
#  UNCERTAINTY CONE
# ═══════════════════════════════════════════════════════════

def calculate_uncertainty(ensemble_path: List[PredictionPoint],
                          kalman_path: List[PredictionPoint],
                          linear_path: List[PredictionPoint],
                          poly_path: List[PredictionPoint],
                          atr: float, hurst: float) -> List[UncertaintyBound]:
    """
    Calculate uncertainty cone using two factors:
    1. Disagreement between models (wider disagreement = more uncertainty)
    2. ATR-based natural volatility (scaled by time and Hurst)

    The cone represents "where the price could reasonably be" at each time step.
    """
    bounds = []

    for i in range(len(ensemble_path)):
        t = ensemble_path[i].t
        ep = ensemble_path[i].p

        # Model disagreement at this time step
        model_prices = [ep]  # Start with ensemble
        if i < len(kalman_path): model_prices.append(kalman_path[i].p)
        if i < len(linear_path): model_prices.append(linear_path[i].p)
        if i < len(poly_path): model_prices.append(poly_path[i].p)

        model_spread = max(model_prices) - min(model_prices)

        # ATR-based volatility spread (widens with sqrt of time)
        # Hurst adjustment: trending markets -> narrower cone; random -> wider
        hurst_factor = 1.0 + (0.5 - hurst)  # H=0.5 -> 1.0; H=0.7 -> 0.8; H=0.3 -> 1.2
        atr_spread = atr * 0.15 * math.sqrt(max(1, t)) * hurst_factor

        # Total uncertainty = max of model disagreement and ATR spread
        total_spread = max(model_spread * 0.5, atr_spread)

        bounds.append(UncertaintyBound(
            t=t,
            upper=ep + total_spread,
            lower=ep - total_spread,
        ))

    return bounds


# ═══════════════════════════════════════════════════════════
#  CONFIDENCE CALCULATION
# ═══════════════════════════════════════════════════════════

def calculate_confidence(hurst: float, r2_linear: float, r2_poly: float,
                         model_agreement: float,
                         accuracy_history: Optional[Dict] = None) -> float:
    """
    Calculate overall prediction confidence (0 to 1).

    Factors:
    1. Hurst strength: further from 0.5 = more predictable = higher confidence
    2. Regression fit quality (R^2)
    3. Model agreement: if all models agree, higher confidence
    4. Historical accuracy: if predictions have been accurate recently
    """
    # Hurst contribution (0-0.3): further from 0.5 = more confident
    hurst_conf = abs(hurst - 0.5) * 0.6  # Max 0.3

    # Regression R^2 contribution (0-0.25)
    avg_r2 = (r2_linear + r2_poly) / 2
    r2_conf = avg_r2 * 0.25

    # Model agreement contribution (0-0.25)
    # model_agreement = 1 - (spread between models / average predicted price)
    agreement_conf = model_agreement * 0.25

    # Historical accuracy contribution (0-0.20)
    hist_conf = 0.10  # Default if no history
    if accuracy_history:
        dir_accuracy = accuracy_history.get("direction_accuracy_pct", 50) / 100
        hist_conf = dir_accuracy * 0.20

    confidence = hurst_conf + r2_conf + agreement_conf + hist_conf
    return max(0.05, min(0.98, confidence))


# ═══════════════════════════════════════════════════════════
#  MAIN ENSEMBLE ENGINE
# ═══════════════════════════════════════════════════════════

class EnsemblePrediction:
    """
    Main ensemble prediction engine.
    Combines Kalman, Linear Regression, Polynomial Regression,
    weighted by Hurst exponent and historical accuracy.
    """

    def __init__(self, polynomial_degree: int = 2, min_data_points: int = 10):
        """
        Args:
            polynomial_degree: Degree for polynomial regression (2=quadratic, 3=cubic)
            min_data_points: Minimum historical data points needed
        """
        self.poly_degree = polynomial_degree
        self.min_points = min_data_points

    def predict(self,
                prices: List[float],
                timestamps: List[float],
                current_price: float,
                kalman_state: Dict[str, float],
                prediction_horizon: float,
                prediction_step: float = 2,
                atr: float = 1.0,
                accuracy_history: Optional[Dict] = None,
                ) -> PredictionResult:
        """
        Generate ensemble prediction.

        Args:
            prices: Historical prices (at least min_data_points)
            timestamps: Corresponding time values (same units as horizon)
            current_price: Current price
            kalman_state: {"velocity": float, "acceleration": float}
            prediction_horizon: How far ahead to predict
            prediction_step: Time step between prediction points
            atr: Average True Range (for uncertainty calculation)
            accuracy_history: Optional dict with past model accuracy from prediction_store:
                {
                    "kalman_error": avg % error of Kalman predictions,
                    "linear_error": avg % error of linear predictions,
                    "poly_error": avg % error of polynomial predictions,
                    "direction_accuracy_pct": % of correct direction predictions,
                }

        Returns:
            PredictionResult with ensemble path, individual paths, weights, etc.
        """
        result = PredictionResult()
        result.lookback_bars = len(prices)

        ts = np.array(timestamps, dtype=float)
        px = np.array(prices, dtype=float)

        # -- Step 1: Calculate Hurst Exponent --
        result.hurst = calculate_hurst(px)
        result.regime = classify_regime(result.hurst)

        # -- Step 2: Run individual models --

        # Model 1: Kalman
        vel = kalman_state.get("velocity", 0)
        acc = kalman_state.get("acceleration", 0)
        result.kalman_path = predict_kalman(
            current_price, vel, acc, prediction_horizon, prediction_step
        )
        result.models_used.append("kalman")

        # Model 2: Linear Regression
        r2_linear = 0
        if len(prices) >= self.min_points:
            result.linear_path, slope, intercept, r2_linear = predict_linear(
                ts, px, prediction_horizon, prediction_step
            )
            result.models_used.append("linear")
        else:
            # Not enough data — use Kalman as fallback
            result.linear_path = result.kalman_path.copy()

        # Model 3: Polynomial Regression
        r2_poly = 0
        if len(prices) >= self.min_points:
            result.polynomial_path, coeffs, r2_poly = predict_polynomial(
                ts, px, prediction_horizon, prediction_step, self.poly_degree
            )
            result.models_used.append("polynomial")
        else:
            result.polynomial_path = result.kalman_path.copy()

        # -- Anchor correction: shift regression paths to start at current_price --
        # Regression lines extrapolate from fitted curve, so t=0 may not equal
        # current_price. Shift so all models agree at t=0 (= now).
        for path in (result.linear_path, result.polynomial_path):
            if path:
                offset = current_price - path[0].p
                if abs(offset) > 1e-6:
                    for pt in path:
                        pt.p += offset

        # -- Step 3: Calculate weights --
        result.weights = calculate_weights(
            result.hurst, r2_linear, r2_poly, accuracy_history
        )

        # -- Step 4: Generate ensemble (weighted average) --
        n_points = min(len(result.kalman_path),
                       len(result.linear_path),
                       len(result.polynomial_path))

        for i in range(n_points):
            t = result.kalman_path[i].t

            weighted_price = (
                result.weights["kalman"] * result.kalman_path[i].p +
                result.weights["linear"] * result.linear_path[i].p +
                result.weights["polynomial"] * result.polynomial_path[i].p
            )

            result.ensemble_path.append(PredictionPoint(t=t, p=weighted_price))

        # -- Step 5: Calculate uncertainty cone --
        result.uncertainty_cone = calculate_uncertainty(
            result.ensemble_path, result.kalman_path,
            result.linear_path, result.polynomial_path,
            atr, result.hurst
        )

        # -- Step 6: Calculate confidence --
        # Model agreement: how close are the models at the endpoint?
        if n_points > 0:
            end_prices = [
                result.kalman_path[-1].p,
                result.linear_path[-1].p,
                result.polynomial_path[-1].p,
            ]
            spread = max(end_prices) - min(end_prices)
            avg_price = np.mean(end_prices)
            model_agreement = max(0, 1 - (spread / avg_price * 10)) if avg_price > 0 else 0
        else:
            model_agreement = 0

        result.confidence = calculate_confidence(
            result.hurst, r2_linear, r2_poly,
            model_agreement, accuracy_history
        )

        return result

    def predict_multi_scale(self,
                            intraday_prices: List[float],
                            intraday_timestamps: List[float],
                            daily_closes: List[float],
                            current_price: float,
                            kalman_intraday: Dict[str, float],
                            kalman_daily: Dict[str, float],
                            timeframe: str,
                            atr_intraday: float,
                            atr_daily: float,
                            prediction_horizon: float,
                            prediction_step: float,
                            accuracy_history: Optional[Dict] = None,
                            ) -> PredictionResult:
        """
        Multi-scale prediction that uses appropriate data for the timeframe.

        For intraday timeframes (15m-Day): uses intraday tick data + intraday Kalman
        For extended timeframes (Tmrw-1W): uses daily close data + daily Kalman

        Args:
            intraday_prices: Today's price data
            intraday_timestamps: Today's time data (minutes)
            daily_closes: Last N daily closing prices
            current_price: Current price
            kalman_intraday: {"velocity": /min, "acceleration": /min^2}
            kalman_daily: {"velocity": /day, "acceleration": /day^2}
            timeframe: "15m", "30m", "1hr", "2hr", "Day", "Tmrw", "3D", "1W"
            atr_intraday: Intraday ATR
            atr_daily: Daily ATR
            prediction_horizon: In appropriate units for timeframe
            prediction_step: Time step
            accuracy_history: Past accuracy data

        Returns:
            PredictionResult (same format — caller doesn't need to know the scale)
        """
        EXTENDED_TIMEFRAMES = {"Tmrw", "3D", "1W"}

        if timeframe in EXTENDED_TIMEFRAMES:
            # Use daily data
            if len(daily_closes) < 3:
                # Not enough daily data — fall back to intraday
                return self.predict(
                    intraday_prices, intraday_timestamps, current_price,
                    kalman_intraday, prediction_horizon, prediction_step,
                    atr_intraday, accuracy_history
                )

            # Create daily timestamps (0, 1, 2, ... days)
            daily_ts = list(range(len(daily_closes)))

            return self.predict(
                prices=daily_closes,
                timestamps=daily_ts,
                current_price=current_price,
                kalman_state=kalman_daily,
                prediction_horizon=prediction_horizon,
                prediction_step=prediction_step,
                atr=atr_daily,
                accuracy_history=accuracy_history,
            )
        else:
            # Use intraday data
            return self.predict(
                prices=intraday_prices,
                timestamps=intraday_timestamps,
                current_price=current_price,
                kalman_state=kalman_intraday,
                prediction_horizon=prediction_horizon,
                prediction_step=prediction_step,
                atr=atr_intraday,
                accuracy_history=accuracy_history,
            )


# ═══════════════════════════════════════════════════════════
#  CONVENIENCE FUNCTIONS
# ═══════════════════════════════════════════════════════════

def quick_predict(prices: List[float], velocity: float, acceleration: float,
                  horizon: float = 20, atr: float = 1.0) -> PredictionResult:
    """
    Quick prediction with minimal inputs.
    Auto-generates timestamps, uses defaults for everything else.

    Usage:
        result = quick_predict([882, 885, 890, 895, 905], velocity=1.8, acceleration=0.12)
        for pt in result.ensemble_path:
            print(f"  t={pt.t:.0f}  price={pt.p:.2f}")
    """
    timestamps = list(range(len(prices)))
    engine = EnsemblePrediction()
    return engine.predict(
        prices=prices,
        timestamps=timestamps,
        current_price=prices[-1],
        kalman_state={"velocity": velocity, "acceleration": acceleration},
        prediction_horizon=horizon,
        prediction_step=max(1, horizon / 20),
        atr=atr,
    )


# ═══════════════════════════════════════════════════════════
#  SELF-TEST
# ═══════════════════════════════════════════════════════════

if __name__ == "__main__":
    """Run a self-test with RAMCOCEM mock data."""
    print("=" * 60)
    print("  Ensemble Prediction Engine -- Self Test")
    print("=" * 60)

    prices = [882, 884, 885.5, 888, 890, 893, 895, 897, 900, 905.3]
    timestamps = [0, 5, 10, 15, 20, 25, 30, 35, 40, 45]

    engine = EnsemblePrediction()
    result = engine.predict(
        prices=prices,
        timestamps=timestamps,
        current_price=905.3,
        kalman_state={"velocity": 1.8, "acceleration": 0.12},
        prediction_horizon=20,
        prediction_step=2,
        atr=8.5,
    )

    print(f"\nHurst Exponent: {result.hurst:.3f}")
    print(f"Regime: {result.regime}")
    print(f"Confidence: {result.confidence:.2f}")
    print(f"Models: {result.models_used}")
    print(f"Weights: { {k: f'{v:.2f}' for k, v in result.weights.items()} }")

    print(f"\nEnsemble Prediction Path:")
    for pt in result.ensemble_path:
        print(f"  t={pt.t:5.1f}  ->  {pt.p:.2f}")

    print(f"\nUncertainty Cone (last point):")
    last = result.uncertainty_cone[-1]
    print(f"  t={last.t:.0f}  ->  {last.lower:.2f} -- {last.upper:.2f}")

    print(f"\nIndividual Model Endpoints:")
    print(f"  Kalman:     {result.kalman_path[-1].p:.2f}")
    print(f"  Linear:     {result.linear_path[-1].p:.2f}")
    print(f"  Polynomial: {result.polynomial_path[-1].p:.2f}")
    print(f"  Ensemble:   {result.ensemble_path[-1].p:.2f}")

    print("\n>> Self-test complete")
