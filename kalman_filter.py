"""
KALMAN FILTER FOR PRICE PREDICTION AND VELOCITY TRACKING
═══════════════════════════════════════════════════════════════════════════════

Financial-grade Kalman filter implementation for:
- Price state estimation
- Velocity (rate of change) tracking
- Acceleration detection
- Price prediction (15-minute horizon)

Based on constant velocity model with adaptive noise estimation.

Author: Trading System v4.2.1 (get_state fix)
Date: 2026-01-23
"""

import numpy as np
import logging
import os
import csv
from datetime import datetime
from typing import Dict, Optional, Tuple
from dataclasses import dataclass, field

logger = logging.getLogger('KalmanFilter')


# ═══════════════════════════════════════════════════════════════════════════════
# INNOVATION LOGGER — Phase A of MAP Filter Migration
# Logs prediction errors to build validation dataset for 6-state MAP model
# Zero risk: purely additive, no behavior change to existing filter
# ═══════════════════════════════════════════════════════════════════════════════

class InnovationLogger:
    """Logs Kalman innovations (prediction errors) with context for MAP validation."""

    CSV_HEADERS = [
        'timestamp', 'symbol', 'predicted_price', 'actual_price', 'innovation',
        'innovation_pct', 'velocity', 'uncertainty', 'volume_ratio', 'rsi',
        'observation_count'
    ]

    def __init__(self, output_dir: str = "data/kalman_innovations"):
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)
        self.csv_file = os.path.join(output_dir, "innovations.csv")
        self._ensure_csv_header()
        self._buffer = []
        self._flush_interval = 20  # Flush every 20 records

    def _ensure_csv_header(self):
        """Create CSV with header if it doesn't exist."""
        if not os.path.exists(self.csv_file):
            with open(self.csv_file, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(self.CSV_HEADERS)

    def log(self, symbol: str, predicted_price: float, actual_price: float,
            velocity: float, uncertainty: float, observation_count: int,
            volume_ratio: float = 1.0, rsi: float = 50.0):
        """Log a single innovation record."""
        innovation = actual_price - predicted_price
        innovation_pct = (innovation / actual_price * 100) if actual_price > 0 else 0.0

        self._buffer.append([
            datetime.now().isoformat(),
            symbol,
            round(predicted_price, 2),
            round(actual_price, 2),
            round(innovation, 4),
            round(innovation_pct, 4),
            round(velocity, 6),
            round(uncertainty, 4),
            round(volume_ratio, 4),
            round(rsi, 2),
            observation_count
        ])

        if len(self._buffer) >= self._flush_interval:
            self.flush()

    def flush(self):
        """Write buffered records to CSV."""
        if not self._buffer:
            return
        try:
            with open(self.csv_file, 'a', newline='') as f:
                writer = csv.writer(f)
                writer.writerows(self._buffer)
            self._buffer.clear()
        except Exception as e:
            logger.error(f"Innovation log flush failed: {e}")


# Module-level singleton — shared across all filter instances
_innovation_logger: Optional[InnovationLogger] = None


def get_innovation_logger() -> InnovationLogger:
    """Get or create the module-level innovation logger."""
    global _innovation_logger
    if _innovation_logger is None:
        _innovation_logger = InnovationLogger()
    return _innovation_logger


@dataclass
class KalmanState:
    """Kalman filter state representation"""
    price: float = 0.0
    velocity: float = 0.0
    acceleration: float = 0.0
    prediction_15min: float = 0.0
    uncertainty: float = 1.0
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for API compatibility"""
        return {
            'price': self.price,
            'velocity': self.velocity,
            'acceleration': self.acceleration,
            'prediction_15min': self.prediction_15min,
            'uncertainty': self.uncertainty
        }


class KalmanFilter:
    """
    Kalman Filter for price prediction using constant velocity model.
    
    State vector: [price, velocity]
    - price: Current estimated price
    - velocity: Rate of price change per minute
    
    Prediction horizon: 15 minutes (configurable)
    """
    
    def __init__(
        self,
        dt: float = 1.0,  # Time step in minutes
        process_noise: float = 0.01,  # Process noise (Q)
        measurement_noise: float = 0.5,  # Measurement noise (R)
        prediction_horizon: int = 15  # Prediction horizon in time steps
    ):
        """
        Initialize Kalman filter.
        
        Args:
            dt: Time step in minutes (typically 1.0 for 1-minute data)
            process_noise: Process noise variance (model uncertainty)
            measurement_noise: Measurement noise variance (price noise)
            prediction_horizon: How many time steps ahead to predict
        """
        self.dt = dt
        self.prediction_horizon = prediction_horizon
        
        # State vector: [price, velocity]
        self.x = np.array([[0.0], [0.0]])  # Initial state
        
        # State covariance matrix
        self.P = np.eye(2) * 1000.0  # High initial uncertainty
        
        # State transition matrix (constant velocity model)
        self.F = np.array([
            [1.0, dt],   # price(t+1) = price(t) + velocity*dt
            [0.0, 1.0]   # velocity(t+1) = velocity(t)
        ])
        
        # Measurement matrix (we only measure price)
        self.H = np.array([[1.0, 0.0]])
        
        # Process noise covariance
        self.Q = np.array([
            [0.25 * dt**4, 0.5 * dt**3],
            [0.5 * dt**3, dt**2]
        ]) * process_noise
        
        # Measurement noise covariance
        self.R = np.array([[measurement_noise]])
        
        # Initialize flag
        self.initialized = False

        # Velocity history for acceleration calculation
        self.velocity_history = []
        self.max_history = 5

        # Phase A: Innovation logging
        self.observation_count = 0
        self._symbol = "UNKNOWN"  # Set by caller via set_symbol()
        self._last_rsi = 50.0     # Set by caller before update
        self._last_volume_ratio = 1.0  # Set by caller before update

        logger.debug(f"🔬 Kalman Filter initialized: dt={dt}, Q={process_noise}, R={measurement_noise}")
    
    def set_symbol(self, symbol: str):
        """Set the stock symbol for innovation logging."""
        self._symbol = symbol

    def set_context(self, rsi: float = 50.0, volume_ratio: float = 1.0):
        """Set RSI and volume context for innovation logging (Phase A)."""
        self._last_rsi = rsi
        self._last_volume_ratio = volume_ratio

    def initialize(self, initial_price: float):
        """
        Initialize filter with first price measurement.

        Args:
            initial_price: First observed price
        """
        self.x[0, 0] = initial_price
        self.x[1, 0] = 0.0  # Start with zero velocity
        self.initialized = True
        logger.debug(f"🎯 Kalman initialized at price: ₹{initial_price:.2f}")
    
    def predict(self) -> np.ndarray:
        """
        Prediction step: Project state forward.
        
        Returns:
            Predicted state vector
        """
        # x(k|k-1) = F * x(k-1|k-1)
        self.x = self.F @ self.x
        
        # P(k|k-1) = F * P(k-1|k-1) * F' + Q
        self.P = self.F @ self.P @ self.F.T + self.Q
        
        return self.x
    
    def update(self, measurement: float) -> np.ndarray:
        """
        Update step: Correct prediction with measurement.

        Args:
            measurement: Observed price

        Returns:
            Updated state vector
        """
        # Phase A: Capture predicted price BEFORE update for innovation logging
        predicted_price = float(self.x[0, 0])

        # Innovation (measurement residual)
        z = np.array([[measurement]])
        y = z - self.H @ self.x

        # Innovation covariance
        S = self.H @ self.P @ self.H.T + self.R

        # Kalman gain
        K = self.P @ self.H.T @ np.linalg.inv(S)

        # Update state estimate
        self.x = self.x + K @ y

        # Update covariance estimate
        I = np.eye(2)
        self.P = (I - K @ self.H) @ self.P

        # Track velocity for acceleration
        velocity = self.x[1, 0]
        self.velocity_history.append(velocity)
        if len(self.velocity_history) > self.max_history:
            self.velocity_history.pop(0)

        # Phase A: Log innovation for MAP validation
        self.observation_count += 1
        try:
            inn_logger = get_innovation_logger()
            inn_logger.log(
                symbol=self._symbol,
                predicted_price=predicted_price,
                actual_price=measurement,
                velocity=float(velocity),
                uncertainty=float(np.trace(self.P)),
                observation_count=self.observation_count,
                volume_ratio=self._last_volume_ratio,
                rsi=self._last_rsi
            )
        except Exception:
            pass  # Never let logging break trading

        return self.x
    
    def process_measurement(self, price: float) -> KalmanState:
        """
        Process a price measurement through the Kalman filter.
        
        Args:
            price: Observed price
            
        Returns:
            KalmanState with current estimates and predictions
        """
        if not self.initialized:
            self.initialize(price)
            return self._create_state()
        
        # Predict and update
        self.predict()
        self.update(price)
        
        return self._create_state()
    
    def _create_state(self) -> KalmanState:
        """
        Create KalmanState object from current filter state.
        
        Returns:
            KalmanState with all derived values
        """
        price = self.x[0, 0]
        velocity = self.x[1, 0]
        
        # Calculate acceleration from velocity history
        acceleration = self._calculate_acceleration()
        
        # Predict price N steps ahead
        prediction = self._predict_ahead(self.prediction_horizon)
        
        # Uncertainty from trace of covariance matrix
        uncertainty = np.trace(self.P)
        
        return KalmanState(
            price=float(price),
            velocity=float(velocity),
            acceleration=float(acceleration),
            prediction_15min=float(prediction),
            uncertainty=float(uncertainty)
        )
    
    def _calculate_acceleration(self) -> float:
        """
        Calculate acceleration from velocity history.
        
        Returns:
            Estimated acceleration (change in velocity)
        """
        if len(self.velocity_history) < 2:
            return 0.0
        
        # Linear regression on velocity history
        velocities = np.array(self.velocity_history)
        n = len(velocities)
        
        if n < 2:
            return 0.0
        
        # Simple finite difference
        recent_accel = (velocities[-1] - velocities[0]) / (n - 1)
        
        return recent_accel
    
    def _predict_ahead(self, steps: int) -> float:
        """
        Predict price N steps ahead using current state.
        
        Args:
            steps: Number of time steps to predict ahead
            
        Returns:
            Predicted price
        """
        # Use state transition matrix to project forward
        F_n = np.linalg.matrix_power(self.F, steps)
        x_pred = F_n @ self.x
        
        return x_pred[0, 0]
    
    def get_state_dict(self) -> Dict:
        """
        Get current state as dictionary.
        
        Returns:
            Dictionary with state values
        """
        state = self._create_state()
        return state.to_dict()
    
    def get_state(self) -> Dict:
        """
        Alias for get_state_dict() for backward compatibility.
        
        Returns:
            Dictionary with state values
        """
        return self.get_state_dict()
    
    def reset(self):
        """Reset filter to initial state"""
        self.x = np.array([[0.0], [0.0]])
        self.P = np.eye(2) * 1000.0
        self.velocity_history = []
        self.initialized = False
        self.observation_count = 0
        logger.debug("🔄 Kalman filter reset")


class AdaptiveKalmanFilter(KalmanFilter):
    """
    Adaptive Kalman filter that adjusts noise parameters based on market regime.
    
    Increases measurement noise during high volatility periods,
    reduces it during stable periods.
    """
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.base_R = kwargs.get('measurement_noise', 0.5)
        self.volatility_window = []
        self.max_vol_history = 20
        self._volume_ratio = 1.0  # v4.15.0: Volume ratio for noise adjustment
    
    def process_measurement(self, price: float, atr: Optional[float] = None) -> KalmanState:
        """
        Process measurement with adaptive noise.
        
        Args:
            price: Observed price
            atr: Optional ATR for volatility adjustment
            
        Returns:
            KalmanState with current estimates
        """
        # Adjust measurement noise based on ATR if provided
        if atr is not None and atr > 0:
            # Normalize ATR to percentage of price
            vol_pct = (atr / price) * 100 if price > 0 else 0
            
            # Track volatility
            self.volatility_window.append(vol_pct)
            if len(self.volatility_window) > self.max_vol_history:
                self.volatility_window.pop(0)
            
            # Adjust R based on current vs average volatility
            if len(self.volatility_window) > 5:
                avg_vol = np.mean(self.volatility_window)
                vol_ratio = vol_pct / avg_vol if avg_vol > 0 else 1.0
                
                # Scale R: higher volatility = more measurement noise
                self.R = np.array([[self.base_R * vol_ratio]])
        
        # v4.15.0: Volume-weighted noise adjustment
        # High volume = trust this price MORE (lower noise)
        # Low volume = trust this price LESS (higher noise)
        if hasattr(self, '_volume_ratio') and self._volume_ratio > 0:
            volume_adjustment = 1.0 / np.sqrt(max(self._volume_ratio, 0.1))
            # Clamp: don't let noise go below 0.1 or above 3× base
            volume_adjustment = np.clip(volume_adjustment, 0.33, 3.0)
            self.R = self.R * volume_adjustment
        
        return super().process_measurement(price)
    
    def set_volume_ratio(self, volume_ratio: float):
        """
        v4.15.0: Set volume ratio for next measurement update.
        
        Called by Phase 4 before process_measurement() to adjust
        Kalman's trust in the current price observation.
        
        Args:
            volume_ratio: Current volume / expected volume (1.0 = normal)
                         >1.5 = high volume (trust price more)
                         <0.5 = low volume (trust price less)
        """
        self._volume_ratio = max(volume_ratio, 0.1)  # Floor at 0.1 to prevent division issues


# ═══════════════════════════════════════════════════════════════════════════════
# KALMAN MAP FILTER — 6-State Multi-Observable Price Prediction Engine
# Phase B of MAP Filter Migration
#
# State vector: [price, velocity, acceleration, RSI, dRSI/dt, volume_momentum]
# Observes price, RSI, and volume momentum directly.
# Cross-coupling terms let RSI momentum and volume predict price turns
# before they appear in price itself.
#
# IAE (Innovation-Based Adaptive Estimation) self-tunes Q and R per stock.
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class KalmanMAPState(KalmanState):
    """Extended state from the 6-state MAP filter."""
    # Inherited: price, velocity, acceleration, prediction_15min, uncertainty

    # RSI state
    rsi_filtered: float = 50.0
    rsi_momentum: float = 0.0       # dRSI/dt from state vector

    # Volume state
    volume_momentum: float = 0.0    # Normalized volume rate of change

    # Phase 4 EXIT signals (Inverse-V)
    inverse_v_top: bool = False     # Rising is slowing -> protect profit
    crash_accelerating: bool = False # Falling is accelerating -> emergency exit
    exit_signal_confidence: float = 0.0

    # Phase 2 ENTRY signal (V-Recovery) — passed to Phase 2, NOT used by Phase 4
    v_recovery_bottom: bool = False  # Falling is slowing -> entry opportunity
    v_recovery_confidence: float = 0.0

    # Regime
    regime: str = "UNKNOWN"         # TRENDING / MEAN_REVERTING / VOLATILE

    # Prediction quality
    prediction_1hour: float = 0.0
    prediction_confidence: float = 0.0  # 0-100

    # Cross-coupling insights
    rsi_price_divergence: bool = False    # RSI rising but price falling (bullish)
    volume_price_divergence: bool = False  # Volume spiking but price flat (breakout)

    def to_dict(self) -> Dict:
        """Convert to dictionary — superset of KalmanState.to_dict()."""
        d = super().to_dict()
        d.update({
            'rsi_filtered': self.rsi_filtered,
            'rsi_momentum': self.rsi_momentum,
            'volume_momentum': self.volume_momentum,
            'inverse_v_top': self.inverse_v_top,
            'crash_accelerating': self.crash_accelerating,
            'exit_signal_confidence': self.exit_signal_confidence,
            'v_recovery_bottom': self.v_recovery_bottom,
            'v_recovery_confidence': self.v_recovery_confidence,
            'regime': self.regime,
            'prediction_1hour': self.prediction_1hour,
            'prediction_confidence': self.prediction_confidence,
            'rsi_price_divergence': self.rsi_price_divergence,
            'volume_price_divergence': self.volume_price_divergence,
        })
        return d


class KalmanMAPFilter:
    """
    6-State Multi-Observable Kalman Filter with Innovation-Based Adaptive Estimation.

    State vector: x = [price, velocity, acceleration, RSI, dRSI/dt, volume_momentum]
    Observations: z = [price, RSI, volume_momentum]

    Cross-coupling parameters (β) allow RSI and volume dynamics to influence
    price predictions — detecting V-Recovery bottoms and Inverse-V tops
    2-5 bars before they appear in price.

    IAE adapts Q (process noise) and R (measurement noise) per stock so each
    filter converges to the stock's natural noise profile within ~30 observations.
    """

    # --- Default parameters (from design doc Section 2.2) ---
    DEFAULT_DT = 1.0

    # Damping factors
    DEFAULT_GAMMA = 0.95   # Acceleration damping (mean-reverts to 0)
    DEFAULT_DELTA = 0.90   # RSI momentum damping
    DEFAULT_LAMBDA = 0.85  # Volume momentum decay

    # Cross-coupling (the "MAP" part)
    DEFAULT_BETA1 = 0.001   # Volume momentum -> price
    DEFAULT_BETA2 = 0.0005  # Volume momentum -> velocity
    DEFAULT_BETA3 = 0.01    # RSI momentum -> acceleration
    DEFAULT_BETA4 = 0.005   # Volume momentum -> acceleration

    # IAE forgetting factor
    DEFAULT_ALPHA = 0.97

    # Signal thresholds
    ACCEL_THRESHOLD = 0.005
    DECEL_THRESHOLD = 0.005
    RSI_MOM_THRESHOLD = 0.3
    VOL_THRESHOLD = 0.2
    CRASH_THRESHOLD = 0.01
    VOL_SPIKE_THRESHOLD = 0.5

    # Time-of-day volatility multipliers (IST)
    TIME_VOLATILITY = {
        'opening':   2.0,   # 09:15 - 09:45
        'morning':   1.0,   # 09:45 - 12:00
        'lunch':     0.5,   # 12:00 - 14:00
        'afternoon': 1.3,   # 14:00 - 15:00
        'closing':   1.8,   # 15:00 - 15:30
    }

    def __init__(
        self,
        dt: float = DEFAULT_DT,
        gamma: float = DEFAULT_GAMMA,
        delta: float = DEFAULT_DELTA,
        lam: float = DEFAULT_LAMBDA,
        beta1: float = DEFAULT_BETA1,
        beta2: float = DEFAULT_BETA2,
        beta3: float = DEFAULT_BETA3,
        beta4: float = DEFAULT_BETA4,
        alpha: float = DEFAULT_ALPHA,
        Q_init: Optional[list] = None,
        R_init: Optional[list] = None,
    ):
        self.dt = dt
        self.gamma = gamma
        self.delta = delta
        self.lam = lam
        self.beta1 = beta1
        self.beta2 = beta2
        self.beta3 = beta3
        self.beta4 = beta4
        self.alpha = alpha

        # State vector [price, vel, accel, RSI, dRSI, vol_mom]
        self.x = np.zeros((6, 1))
        self.x[3, 0] = 50.0  # RSI defaults to neutral

        # State transition matrix F (6x6)
        self.F = self._build_F()

        # Measurement matrix H (3x6) — we observe price, RSI, vol_momentum
        self.H = np.zeros((3, 6))
        self.H[0, 0] = 1.0  # z1 = price
        self.H[1, 3] = 1.0  # z2 = RSI
        self.H[2, 5] = 1.0  # z3 = volume_momentum

        # Covariance
        self.P = np.eye(6) * 1000.0

        # Process noise Q (6x6) — initial or restored from calibration
        if Q_init is not None:
            self.Q = np.array(Q_init, dtype=float)
        else:
            self.Q = self._build_default_Q()

        # Measurement noise R (3x3)
        if R_init is not None:
            self.R = np.array(R_init, dtype=float)
        else:
            self.R = np.diag([0.5, 2.0, 0.1])  # price, RSI, vol_mom

        # IAE adaptive estimates
        self.Q_hat = self.Q.copy()
        self.R_hat = self.R.copy()

        # Tracking
        self.initialized = False
        self.observation_count = 0
        self._symbol = "UNKNOWN"

        # Q trace history for regime detection
        self._q_trace_history = []
        self._max_q_history = 30

        # Innovation logger
        self._last_rsi = 50.0
        self._last_volume_ratio = 1.0

        logger.debug(f"KalmanMAPFilter initialized: dt={dt}, gamma={gamma}, delta={delta}")

    def _build_F(self) -> np.ndarray:
        """Build 6x6 state transition matrix with cross-coupling."""
        dt = self.dt
        F = np.eye(6)
        # Row 0: price = price + vel*dt + 0.5*accel*dt^2 + beta1*vol_mom
        F[0, 1] = dt
        F[0, 2] = 0.5 * dt * dt
        F[0, 5] = self.beta1
        # Row 1: vel = vel + accel*dt + beta2*vol_mom
        F[1, 2] = dt
        F[1, 5] = self.beta2
        # Row 2: accel = gamma*accel + beta3*dRSI + beta4*vol_mom
        F[2, 2] = self.gamma
        F[2, 4] = self.beta3
        F[2, 5] = self.beta4
        # Row 3: RSI = RSI + dRSI*dt
        F[3, 4] = dt
        # Row 4: dRSI = delta*dRSI
        F[4, 4] = self.delta
        # Row 5: vol_mom = lambda*vol_mom
        F[5, 5] = self.lam
        return F

    def _build_default_Q(self) -> np.ndarray:
        """Build default process noise covariance."""
        # Diagonal — uncorrelated process noise initially
        # Values tuned for INR stocks on 1-minute bars
        return np.diag([
            0.01,    # price noise (₹²)
            0.001,   # velocity noise
            0.0005,  # acceleration noise
            0.5,     # RSI noise (points²)
            0.1,     # dRSI noise
            0.05,    # volume momentum noise
        ])

    def set_symbol(self, symbol: str):
        """Set stock symbol for logging."""
        self._symbol = symbol

    def initialize(self, price: float, rsi: float = 50.0, volume_momentum: float = 0.0):
        """Initialize filter with first observations."""
        self.x[0, 0] = price
        self.x[1, 0] = 0.0   # zero velocity
        self.x[2, 0] = 0.0   # zero acceleration
        self.x[3, 0] = rsi
        self.x[4, 0] = 0.0   # zero RSI momentum
        self.x[5, 0] = volume_momentum
        self.initialized = True
        logger.debug(f"KalmanMAP initialized: {self._symbol} @ ₹{price:.2f}, RSI={rsi:.1f}")

    def _get_time_volatility_factor(self) -> float:
        """Get time-of-day volatility multiplier for IST market hours."""
        now = datetime.now()
        hour, minute = now.hour, now.minute
        t = hour * 60 + minute  # minutes since midnight

        if t < 9 * 60 + 45:     # Before 09:45
            return self.TIME_VOLATILITY['opening']
        elif t < 12 * 60:        # 09:45 - 12:00
            return self.TIME_VOLATILITY['morning']
        elif t < 14 * 60:        # 12:00 - 14:00
            return self.TIME_VOLATILITY['lunch']
        elif t < 15 * 60:        # 14:00 - 15:00
            return self.TIME_VOLATILITY['afternoon']
        else:                     # 15:00+
            return self.TIME_VOLATILITY['closing']

    def predict(self):
        """Prediction step: project state forward."""
        # Time-of-day Q scaling
        sigma_time = self._get_time_volatility_factor()
        Q_scaled = self.Q_hat.copy()
        Q_scaled[2, 2] *= sigma_time  # Scale acceleration noise

        # x = F * x
        self.x = self.F @ self.x

        # RSI clamping — keep in valid range after prediction
        self.x[3, 0] = np.clip(self.x[3, 0], 1.0, 99.0)

        # P = F * P * F' + Q
        self.P = self.F @ self.P @ self.F.T + Q_scaled

        # Eigenvalue floor to prevent numerical instability
        self._enforce_covariance_floor()

    def update(self, price: float, rsi: float, volume_momentum: float):
        """
        Update step: correct prediction with 3 measurements.

        Args:
            price: Observed price (₹)
            rsi: Computed RSI (0-100)
            volume_momentum: d(Volume)/dt normalized (typically -1 to +3)
        """
        # Measurement vector
        z = np.array([[price], [rsi], [volume_momentum]])

        # Innovation
        nu = z - self.H @ self.x

        # Innovation covariance
        S = self.H @ self.P @ self.H.T + self.R_hat

        # Kalman gain
        try:
            S_inv = np.linalg.inv(S)
        except np.linalg.LinAlgError:
            S_inv = np.linalg.pinv(S)  # Fallback to pseudo-inverse
        K = self.P @ self.H.T @ S_inv

        # State update
        self.x = self.x + K @ nu

        # RSI clamping post-update
        self.x[3, 0] = np.clip(self.x[3, 0], 1.0, 99.0)

        # Joseph form covariance update (numerically stable)
        I_KH = np.eye(6) - K @ self.H
        self.P = I_KH @ self.P @ I_KH.T + K @ self.R_hat @ K.T

        self._enforce_covariance_floor()

        # IAE: Adapt Q and R
        self._iae_update(nu, K)

        # Track observations
        self.observation_count += 1

        # Q trace for regime detection
        q_trace = float(np.trace(self.Q_hat))
        self._q_trace_history.append(q_trace)
        if len(self._q_trace_history) > self._max_q_history:
            self._q_trace_history.pop(0)

        # Innovation logging (Phase A)
        self._last_rsi = rsi
        self._last_volume_ratio = max(volume_momentum, 0.0)
        try:
            inn_logger = get_innovation_logger()
            inn_logger.log(
                symbol=self._symbol,
                predicted_price=float(z[0, 0] - nu[0, 0]),  # predicted = actual - innovation
                actual_price=price,
                velocity=float(self.x[1, 0]),
                uncertainty=float(np.trace(self.P)),
                observation_count=self.observation_count,
                volume_ratio=volume_momentum,
                rsi=rsi,
            )
        except Exception:
            pass

    def _iae_update(self, nu: np.ndarray, K: np.ndarray):
        """Innovation-Based Adaptive Estimation — tune Q and R from innovations."""
        alpha = self.alpha

        # Update R_hat (measurement noise estimate)
        # R̂ₖ = α·R̂ₖ₋₁ + (1-α)·(ν·νᵀ + H·P⁻·Hᵀ)
        nu_outer = nu @ nu.T
        innovation_R = nu_outer + self.H @ self.P @ self.H.T
        self.R_hat = alpha * self.R_hat + (1 - alpha) * innovation_R

        # Update Q_hat (process noise estimate)
        # Q̂ₖ = α·Q̂ₖ₋₁ + (1-α)·(K·ν·νᵀ·Kᵀ)
        innovation_Q = K @ nu_outer @ K.T
        self.Q_hat = alpha * self.Q_hat + (1 - alpha) * innovation_Q

        # Floor: prevent Q or R from collapsing to zero
        for i in range(6):
            self.Q_hat[i, i] = max(self.Q_hat[i, i], 1e-8)
        for i in range(3):
            self.R_hat[i, i] = max(self.R_hat[i, i], 1e-6)

    def _enforce_covariance_floor(self):
        """Prevent P from going negative or exploding via eigenvalue floor."""
        # Symmetrize (numerical drift)
        self.P = 0.5 * (self.P + self.P.T)

        # Eigenvalue floor
        eigvals, eigvecs = np.linalg.eigh(self.P)
        eigvals = np.maximum(eigvals, 1e-8)
        self.P = eigvecs @ np.diag(eigvals) @ eigvecs.T

    def process_measurement(self, price: float, rsi: float = 50.0,
                            volume_momentum: float = 0.0) -> KalmanMAPState:
        """
        Full predict+update cycle. Drop-in replacement for KalmanFilter.process_measurement().

        Args:
            price: Observed price (₹)
            rsi: Current RSI value (0-100)
            volume_momentum: Normalized volume rate of change

        Returns:
            KalmanMAPState with all derived signals
        """
        if not self.initialized:
            self.initialize(price, rsi, volume_momentum)
            return self._create_map_state()

        self.predict()
        self.update(price, rsi, volume_momentum)
        return self._create_map_state()

    def _create_map_state(self) -> KalmanMAPState:
        """Build KalmanMAPState from current filter state."""
        price = float(self.x[0, 0])
        velocity = float(self.x[1, 0])
        acceleration = float(self.x[2, 0])
        rsi_filtered = float(self.x[3, 0])
        rsi_momentum = float(self.x[4, 0])
        volume_momentum = float(self.x[5, 0])
        uncertainty = float(np.trace(self.P))

        # Predictions
        pred_15 = self._predict_ahead(15)
        pred_60 = self._predict_ahead(60)
        pred_confidence = self._calculate_prediction_confidence(15, price)

        # Signal detection
        inv_v = self._detect_inverse_v_top(velocity, acceleration, rsi_momentum, volume_momentum)
        crash = self._detect_crash_acceleration(velocity, acceleration, rsi_momentum, volume_momentum)
        v_rec = self._detect_v_recovery_bottom(velocity, acceleration, rsi_momentum, rsi_filtered)

        # Exit confidence = max of inverse-V and crash signals
        exit_conf = max(inv_v[1], crash[1])

        # Regime
        regime = self._detect_regime()

        # Divergences
        rsi_div = (rsi_momentum > 0.3 and velocity < -0.02)  # RSI rising but price falling
        vol_div = (abs(volume_momentum) > 0.5 and abs(velocity) < 0.01)  # Vol active but price flat

        return KalmanMAPState(
            # Base KalmanState fields
            price=price,
            velocity=velocity,
            acceleration=acceleration,
            prediction_15min=pred_15,
            uncertainty=uncertainty,
            # Extended MAP fields
            rsi_filtered=rsi_filtered,
            rsi_momentum=rsi_momentum,
            volume_momentum=volume_momentum,
            inverse_v_top=inv_v[0],
            crash_accelerating=crash[0],
            exit_signal_confidence=exit_conf,
            v_recovery_bottom=v_rec[0],
            v_recovery_confidence=v_rec[1],
            regime=regime,
            prediction_1hour=pred_60,
            prediction_confidence=pred_confidence,
            rsi_price_divergence=rsi_div,
            volume_price_divergence=vol_div,
        )

    def _predict_ahead(self, steps: int) -> float:
        """Predict price N steps ahead using matrix power."""
        F_n = np.linalg.matrix_power(self.F, steps)
        x_pred = F_n @ self.x
        return float(x_pred[0, 0])

    def _calculate_prediction_confidence(self, steps: int, current_price: float) -> float:
        """Confidence score (0-100) based on projected uncertainty."""
        F_n = np.linalg.matrix_power(self.F, steps)
        P_pred = F_n @ self.P @ F_n.T
        uncertainty = float(np.sqrt(np.trace(P_pred)))
        if current_price <= 0:
            return 0.0
        confidence = max(0.0, min(100.0, 100.0 * (1.0 - uncertainty / (0.02 * current_price))))
        return round(confidence, 1)

    def _detect_inverse_v_top(self, velocity, acceleration, rsi_mom, vol_mom) -> Tuple[bool, float]:
        """
        Detect Inverse-V top: price still rising but deceleration + RSI rolling over.
        Returns (signal_bool, confidence 0-1).
        """
        if velocity <= 0:
            return (False, 0.0)

        decel = acceleration < -self.DECEL_THRESHOLD
        rsi_rolling = rsi_mom < -self.RSI_MOM_THRESHOLD

        if decel and rsi_rolling:
            vol_confirm = vol_mom < -self.VOL_THRESHOLD
            conf = min(1.0, abs(acceleration) / self.DECEL_THRESHOLD * 0.5)
            if vol_confirm:
                conf = min(1.0, conf + 0.3)
            return (True, round(conf, 3))

        return (False, 0.0)

    def _detect_crash_acceleration(self, velocity, acceleration, rsi_mom, vol_mom) -> Tuple[bool, float]:
        """
        Detect crash acceleration: price falling AND falling FASTER with volume.
        Returns (signal_bool, confidence 0-1).
        """
        if velocity >= 0:
            return (False, 0.0)

        accel_bad = acceleration < -self.CRASH_THRESHOLD
        vol_spike = vol_mom > self.VOL_SPIKE_THRESHOLD

        if accel_bad and vol_spike:
            conf = min(1.0, abs(acceleration) / self.CRASH_THRESHOLD * 0.7)
            return (True, round(conf, 3))

        return (False, 0.0)

    def _detect_v_recovery_bottom(self, velocity, acceleration, rsi_mom, rsi) -> Tuple[bool, float]:
        """
        Detect V-Recovery bottom: still falling but deceleration + RSI bottoming.
        Returns (signal_bool, confidence 0-1).
        """
        if velocity >= 0:
            return (False, 0.0)

        decel = acceleration > self.ACCEL_THRESHOLD  # Falling is slowing
        rsi_turning = rsi_mom > 0                     # RSI bottoming
        rsi_oversold = rsi < 40                       # Still oversold

        if decel and rsi_turning and rsi_oversold:
            accel_uncertainty = float(self.P[2, 2])
            conf = 1.0 - min(1.0, accel_uncertainty / 0.01)
            conf = max(0.0, round(conf, 3))
            return (True, conf)

        return (False, 0.0)

    def _detect_regime(self) -> str:
        """Detect market regime from adaptive noise history."""
        if len(self._q_trace_history) < 5:
            return "UNKNOWN"

        q_trace = self._q_trace_history[-1]
        avg_q = float(np.mean(self._q_trace_history[-20:]))

        if avg_q <= 0:
            return "UNKNOWN"

        if q_trace > 2.0 * avg_q:
            return "VOLATILE"

        accel_var = float(self.P[2, 2])
        if accel_var < 0.001:
            return "MEAN_REVERTING"

        return "TRENDING"

    def get_state(self) -> Dict:
        """Get current state as dict — compatible with existing KalmanFilter.get_state()."""
        state = self._create_map_state()
        return state.to_dict()

    def get_state_dict(self) -> Dict:
        """Alias for get_state()."""
        return self.get_state()

    def get_calibration(self) -> Dict:
        """Get converged Q and R for persistence (Phase D)."""
        return {
            'symbol': self._symbol,
            'Q_converged': self.Q_hat.tolist(),
            'R_converged': self.R_hat.tolist(),
            'observations': self.observation_count,
            'last_updated': datetime.now().isoformat(),
        }

    def reset(self):
        """Reset filter to initial state."""
        self.x = np.zeros((6, 1))
        self.x[3, 0] = 50.0
        self.P = np.eye(6) * 1000.0
        self.Q_hat = self.Q.copy()
        self.R_hat = self.R.copy()
        self.initialized = False
        self.observation_count = 0
        self._q_trace_history.clear()
        logger.debug(f"KalmanMAP reset: {self._symbol}")


# ═══════════════════════════════════════════════════════════════════════════════
# DAILY KALMAN FILTER — Phase 8 Tier 3 Intelligence
# Processes daily closing prices to predict multi-day flight path.
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class DailyKalmanState:
    """State representation for the daily Kalman filter."""
    price: float = 0.0
    velocity: float = 0.0           # rupees per day
    acceleration: float = 0.0       # velocity change per day
    tuesday_prediction: float = 0.0
    predicted_pnl_pct: float = 0.0
    confidence: float = 0.0
    uncertainty: float = 1.0

    def to_dict(self) -> Dict:
        return {
            'price': round(self.price, 2),
            'velocity': round(self.velocity, 4),
            'acceleration': round(self.acceleration, 4),
            'tuesday_prediction': round(self.tuesday_prediction, 2),
            'predicted_pnl_pct': round(self.predicted_pnl_pct, 4),
            'confidence': round(self.confidence, 4),
            'uncertainty': round(self.uncertainty, 4),
        }


class DailyKalmanFilter:
    """
    Kalman filter operating on daily closing prices for Tier 3 positions.

    State vector: [price, daily_velocity, daily_acceleration]
    Input:        one daily closing price per trading day
    Output:       Tuesday closing price prediction with confidence

    Differences from tick-level KalmanFilter:
      - dt = 1 trading day (not 1 minute)
      - Process noise higher (daily moves are noisier)
      - Measurement noise lower (daily close is reliable)
      - 3-state model (constant acceleration, not constant velocity)
    """

    def __init__(self, config=None):
        dt = 1.0  # 1 trading day

        process_noise = 0.1
        measurement_noise = 1.0
        if config:
            process_noise = getattr(config, 'PH8_KALMAN_PROCESS_NOISE', 0.1)
            measurement_noise = getattr(config, 'PH8_KALMAN_MEASUREMENT_NOISE', 1.0)

        # State: [price, velocity, acceleration]
        self.x = np.array([[0.0], [0.0], [0.0]])

        # Covariance
        self.P = np.eye(3) * 1000.0

        # State transition: constant acceleration model
        self.F = np.array([
            [1.0, dt, 0.5 * dt ** 2],
            [0.0, 1.0, dt],
            [0.0, 0.0, 1.0],
        ])

        # Observation: we only see price
        self.H = np.array([[1.0, 0.0, 0.0]])

        # Process noise
        self.Q = np.array([
            [dt ** 4 / 4, dt ** 3 / 2, dt ** 2 / 2],
            [dt ** 3 / 2, dt ** 2, dt],
            [dt ** 2 / 2, dt, 1.0],
        ]) * process_noise

        # Measurement noise
        self.R = np.array([[measurement_noise]])

        self.initialized = False
        self.observation_count = 0
        self._entry_price = 0.0
        self._symbol = "UNKNOWN"

    def set_symbol(self, symbol: str):
        self._symbol = symbol

    def set_entry_price(self, entry_price: float):
        self._entry_price = entry_price

    def initialize_with_history(self, daily_closes: list):
        """
        Warm up with historical daily closes (most recent last).

        Args:
            daily_closes: List of floats — last N daily closing prices.
        """
        if not daily_closes:
            return

        self.x[0, 0] = daily_closes[0]
        self.x[1, 0] = 0.0
        self.x[2, 0] = 0.0
        self.P = np.eye(3) * 1000.0
        self.initialized = True
        self.observation_count = 0

        for close in daily_closes:
            self._predict()
            self._update(close)

        logger.info(f"DailyKalman [{self._symbol}]: warmed up with {len(daily_closes)} candles, "
                    f"price={self.x[0, 0]:.2f}, vel={self.x[1, 0]:.2f}/day")

    def process_daily_close(self, close_price: float) -> DailyKalmanState:
        """
        Feed one new daily close. Returns updated state with predictions.
        """
        if not self.initialized:
            self.x[0, 0] = close_price
            self.initialized = True
            self.observation_count = 1
            return self._build_state(days_to_tuesday=0)

        self._predict()
        self._update(close_price)
        return self._build_state(days_to_tuesday=0)

    def get_state(self, days_to_tuesday: int = 0) -> DailyKalmanState:
        """Get current state with Tuesday prediction."""
        return self._build_state(days_to_tuesday)

    def predict_price_at(self, days_ahead: int) -> float:
        """Multi-step extrapolation: price at N trading days ahead."""
        price = self.x[0, 0]
        velocity = self.x[1, 0]
        accel = self.x[2, 0]
        return price + velocity * days_ahead + 0.5 * accel * days_ahead ** 2

    # ── Internal ──────────────────────────────────────────────────────

    def _predict(self):
        self.x = self.F @ self.x
        self.P = self.F @ self.P @ self.F.T + self.Q

    def _update(self, measurement: float):
        y = np.array([[measurement]]) - self.H @ self.x       # innovation
        S = self.H @ self.P @ self.H.T + self.R               # innovation cov
        K = self.P @ self.H.T @ np.linalg.inv(S)              # Kalman gain
        self.x = self.x + K @ y
        I = np.eye(3)
        self.P = (I - K @ self.H) @ self.P
        self.observation_count += 1

    def _build_state(self, days_to_tuesday: int) -> DailyKalmanState:
        price = self.x[0, 0]
        velocity = self.x[1, 0]
        accel = self.x[2, 0]

        tuesday_pred = self.predict_price_at(max(days_to_tuesday, 0))

        pred_pnl = 0.0
        if self._entry_price > 0:
            pred_pnl = (tuesday_pred - self._entry_price) / self._entry_price

        # Confidence: inverse of trace(P) scaled
        trace_p = np.trace(self.P)
        confidence = 1.0 / (1.0 + trace_p / 1000.0)

        return DailyKalmanState(
            price=float(price),
            velocity=float(velocity),
            acceleration=float(accel),
            tuesday_prediction=float(tuesday_pred),
            predicted_pnl_pct=float(pred_pnl),
            confidence=float(confidence),
            uncertainty=float(trace_p),
        )

    def reset(self):
        self.x = np.array([[0.0], [0.0], [0.0]])
        self.P = np.eye(3) * 1000.0
        self.initialized = False
        self.observation_count = 0
        self._entry_price = 0.0


def create_kalman_filter(config) -> KalmanFilter:
    """
    Factory function to create Kalman filter from config.
    
    Args:
        config: Configuration object with Kalman parameters
        
    Returns:
        Configured KalmanFilter instance
    """
    # Extract parameters from config with defaults
    dt = getattr(config, 'KALMAN_DT', 1.0)
    process_noise = getattr(config, 'KALMAN_PROCESS_NOISE', 0.01)
    measurement_noise = getattr(config, 'KALMAN_MEASUREMENT_NOISE', 0.5)
    prediction_horizon = getattr(config, 'KALMAN_PREDICTION_HORIZON', 15)
    use_adaptive = getattr(config, 'KALMAN_ADAPTIVE', True)
    
    if use_adaptive:
        logger.info("🔬 Creating Adaptive Kalman Filter")
        return AdaptiveKalmanFilter(
            dt=dt,
            process_noise=process_noise,
            measurement_noise=measurement_noise,
            prediction_horizon=prediction_horizon
        )
    else:
        logger.info("🔬 Creating Standard Kalman Filter")
        return KalmanFilter(
            dt=dt,
            process_noise=process_noise,
            measurement_noise=measurement_noise,
            prediction_horizon=prediction_horizon
        )


def process_price_series(prices: list, config=None) -> Tuple[list, list, list]:
    """
    Process a series of prices through Kalman filter.
    
    Args:
        prices: List of price observations
        config: Optional configuration object
        
    Returns:
        Tuple of (filtered_prices, velocities, predictions)
    """
    if config is None:
        kf = KalmanFilter()
    else:
        kf = create_kalman_filter(config)
    
    filtered_prices = []
    velocities = []
    predictions = []
    
    for price in prices:
        state = kf.process_measurement(price)
        filtered_prices.append(state.price)
        velocities.append(state.velocity)
        predictions.append(state.prediction_15min)
    
    return filtered_prices, velocities, predictions


# ═══════════════════════════════════════════════════════════════════════════════
# TESTING AND VALIDATION
# ═══════════════════════════════════════════════════════════════════════════════

def test_kalman_filter():
    """Test Kalman filter with synthetic data"""
    logger.info("=" * 80)
    logger.info("KALMAN FILTER TEST")
    logger.info("=" * 80)
    
    # Create synthetic price data with trend and noise
    np.random.seed(42)
    true_prices = 100 + 0.1 * np.arange(100) + np.random.normal(0, 0.5, 100)
    
    # Create filter
    kf = KalmanFilter(dt=1.0, process_noise=0.01, measurement_noise=0.5)
    
    # Process data
    states = []
    for price in true_prices:
        state = kf.process_measurement(price)
        states.append(state)
    
    # Report results
    logger.info(f"\n✅ Processed {len(states)} measurements")
    logger.info(f"Initial price: ₹{true_prices[0]:.2f}")
    logger.info(f"Final price: ₹{true_prices[-1]:.2f}")
    logger.info(f"Final filtered price: ₹{states[-1].price:.2f}")
    logger.info(f"Final velocity: {states[-1].velocity:.4f} ₹/min")
    logger.info(f"Final acceleration: {states[-1].acceleration:.6f} ₹/min²")
    logger.info(f"15-min prediction: ₹{states[-1].prediction_15min:.2f}")
    logger.info(f"Uncertainty: {states[-1].uncertainty:.4f}")
    
    # Calculate tracking error
    tracking_errors = [abs(true_prices[i] - states[i].price) for i in range(len(states))]
    avg_error = np.mean(tracking_errors)
    logger.info(f"\nAverage tracking error: ₹{avg_error:.4f}")
    
    logger.info("=" * 80)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    test_kalman_filter()
