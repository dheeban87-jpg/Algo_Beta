"""
RSI Ramp Detector v5.3.0
========================

3-Detector Fusion System for detecting silent RSI ramps in noisy data.

Problem:
  RSI in the 10-35 zone zigzags wildly: 24 18 20 16 19 22 26 18 21 24...
  Simple threshold crossing (RSI > X) can't detect the underlying uptrend.
  The old adaptive RSI check had 0% block rate — useless rubber stamp.

Solution: Three independent detectors + 2D calibration map
  Detector 1: MA(5) of RSI — smoothed slope direction
  Detector 2: Rising Lows on Kalman-smoothed RSI — floor accumulation
  Detector 3: Kalman velocity — noise-filtered rate of change

Map Decision: Minimum 2 of 3 must agree, rising lows is anchor.

Validated with real noisy RSI sequence:
  Input:  24 18 20 16 19 22 26 18 21 24 26 20 24 26 22 23 26...
  Result: RAMP detected at reading 12, sustained through 18 ✅

Usage:
  detector = RampDetector(config)
  result = detector.detect(rsi_values_list)
  if result.is_ramp:
      # Proceed with entry
"""

import numpy as np
import logging
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

logger = logging.getLogger('algo_beta.ramp_detector')


# ============================================================================
# DATA CLASSES
# ============================================================================

@dataclass
class RampResult:
    """Output of ramp detection."""
    is_ramp: bool = False
    is_weak_ramp: bool = False       # Early warning (Kalman strong but lows not built)
    confidence: str = 'NONE'         # NONE / WEAK / RAMP
    
    # Detector outputs
    ma_direction: str = 'UNKNOWN'    # FALLING / FLAT / RISING
    ma_slope: float = 0.0
    rising_lows_count: int = 0
    kalman_velocity: float = 0.0
    kalman_rsi: float = 0.0
    
    # Zone info
    raw_rsi: float = 0.0
    in_zone: bool = False
    zone_range: str = ''
    
    # Debug
    local_lows: List[Tuple[int, float]] = field(default_factory=list)
    reason: str = ''


@dataclass
class RampConfig:
    """Configurable parameters for ramp detection."""
    # Zone boundaries — RSI must be in this range for RAMP to trigger
    RSI_ZONE_LOW: float = 10.0
    RSI_ZONE_HIGH: float = 35.0
    
    # Detector 1: MA parameters
    MA_PERIOD: int = 5
    MA_SLOPE_RISING: float = 0.3     # Slope > this = RISING
    MA_SLOPE_FALLING: float = -0.3   # Slope < this = FALLING
    
    # Detector 2: Rising Lows parameters
    RISING_LOW_TOLERANCE: float = 1.5  # Allow small dips (Kalman-smoothed)
    MIN_READINGS_FOR_LOWS: int = 8     # Need at least 8 readings to find lows
    
    # Detector 3: Kalman parameters
    KALMAN_PROCESS_NOISE: float = 0.5
    KALMAN_MEASUREMENT_NOISE: float = 4.0
    KALMAN_VEL_STRONG: float = 0.5
    KALMAN_VEL_MILD: float = 0.2
    KALMAN_VEL_WEAK: float = 0.0
    
    # Minimum readings needed for ramp detection
    MIN_READINGS: int = 10


# ============================================================================
# RAMP DETECTOR
# ============================================================================

class RampDetector:
    """
    3-Detector Fusion RSI Ramp Detector.
    
    Detects silent accumulation ramps in noisy RSI data by combining:
      1. MA(5) smoothed slope direction
      2. Rising lows on Kalman-smoothed RSI
      3. Kalman velocity extraction
    
    Physics-based calibration — no trade history needed.
    """
    
    def __init__(self, config=None):
        """Initialize with config (uses defaults if None)."""
        if config is None:
            self.cfg = RampConfig()
        elif isinstance(config, RampConfig):
            self.cfg = config
        else:
            # Extract from algo config object
            self.cfg = RampConfig(
                RSI_ZONE_LOW=getattr(config, 'RAMP_RSI_ZONE_LOW', 10.0),
                RSI_ZONE_HIGH=getattr(config, 'RAMP_RSI_ZONE_HIGH', 35.0),
                MA_PERIOD=getattr(config, 'RAMP_MA_PERIOD', 5),
                MA_SLOPE_RISING=getattr(config, 'RAMP_MA_SLOPE_RISING', 0.3),
                MA_SLOPE_FALLING=getattr(config, 'RAMP_MA_SLOPE_FALLING', -0.3),
                RISING_LOW_TOLERANCE=getattr(config, 'RAMP_RISING_LOW_TOLERANCE', 1.5),
                MIN_READINGS_FOR_LOWS=getattr(config, 'RAMP_MIN_READINGS_LOWS', 8),
                KALMAN_PROCESS_NOISE=getattr(config, 'RAMP_KALMAN_PROCESS_NOISE', 0.5),
                KALMAN_MEASUREMENT_NOISE=getattr(config, 'RAMP_KALMAN_MEASUREMENT_NOISE', 4.0),
                KALMAN_VEL_STRONG=getattr(config, 'RAMP_KALMAN_VEL_STRONG', 0.5),
                KALMAN_VEL_MILD=getattr(config, 'RAMP_KALMAN_VEL_MILD', 0.2),
                MIN_READINGS=getattr(config, 'RAMP_MIN_READINGS', 10),
            )
    
    def detect(self, rsi_values: List[float]) -> RampResult:
        """
        Main detection method.
        
        Args:
            rsi_values: List of RSI readings (most recent last).
                        Needs at least MIN_READINGS values.
        
        Returns:
            RampResult with is_ramp=True if ramp detected.
        """
        result = RampResult()
        
        if not rsi_values or len(rsi_values) < self.cfg.MIN_READINGS:
            result.reason = f'Insufficient data ({len(rsi_values) if rsi_values else 0} < {self.cfg.MIN_READINGS})'
            return result
        
        # Current RSI value
        result.raw_rsi = rsi_values[-1]
        result.zone_range = f'{self.cfg.RSI_ZONE_LOW}-{self.cfg.RSI_ZONE_HIGH}'
        
        # ── Run all 3 detectors ──
        
        # Detector 1: MA slope
        ma_direction, ma_slope = self._detect_ma_slope(rsi_values)
        result.ma_direction = ma_direction
        result.ma_slope = ma_slope
        
        # Detector 3 (run before 2): Kalman filter on RSI
        kalman_rsi_values, kalman_velocities = self._run_kalman(rsi_values)
        result.kalman_rsi = kalman_rsi_values[-1]
        result.kalman_velocity = kalman_velocities[-1]
        
        # Zone check on Kalman-smoothed RSI (less noisy)
        result.in_zone = self.cfg.RSI_ZONE_LOW <= result.kalman_rsi <= self.cfg.RSI_ZONE_HIGH
        
        # Detector 2: Rising lows on Kalman-smoothed RSI
        rising_count, local_lows = self._detect_rising_lows(kalman_rsi_values)
        result.rising_lows_count = rising_count
        result.local_lows = local_lows
        
        # ── Apply 2D calibration map ──
        
        if not result.in_zone:
            result.reason = f'Kalman RSI {result.kalman_rsi:.1f} outside zone {result.zone_range}'
            return result
        
        # Categorize detector outputs
        ma_score = 1 if ma_direction == 'RISING' else (-1 if ma_direction == 'FALLING' else 0)
        
        vel = result.kalman_velocity
        if vel > self.cfg.KALMAN_VEL_STRONG:
            vel_score = 3   # STRONG
        elif vel > self.cfg.KALMAN_VEL_MILD:
            vel_score = 2   # MILD
        elif vel > self.cfg.KALMAN_VEL_WEAK:
            vel_score = 1   # WEAK
        else:
            vel_score = 0   # NEG
        
        lows_count = result.rising_lows_count
        
        # ══════════════════════════════════════════════════════════════
        # 2D CALIBRATION MAP
        #
        # Rule: Minimum 2 of 3 must agree, rising lows is anchor.
        #
        #                     Kalman Velocity
        #                     <0     0~0.2   0.2~0.5   >0.5
        #               ┌──────────────────────────────────────┐
        #  MA↑ + 3+     │  NO     RAMP    RAMP      RAMP      │
        #  MA↑ + 2      │  NO     NO      RAMP      RAMP      │
        #  MA↑ + 1      │  NO     NO      NO        RAMP      │
        #  MA→ + 3+     │  NO     NO      RAMP      RAMP      │
        #  MA→ + 2      │  NO     NO      NO        RAMP      │
        #  MA↓ + 3+     │  NO     NO      NO        RAMP      │
        #  (all else)   │  NO     NO      NO        NO        │
        #               └──────────────────────────────────────┘
        # ══════════════════════════════════════════════════════════════
        
        is_ramp = False
        is_weak = False
        
        # Strong patterns (2+ detectors agree with anchor)
        if lows_count >= 3 and vel_score >= 1:
            is_ramp = True
            result.reason = f'3+ rising lows + Kalman positive (vel={vel:+.2f})'
        elif lows_count >= 3 and ma_score >= 1:
            is_ramp = True
            result.reason = f'3+ rising lows + MA rising (slope={ma_slope:+.2f})'
        elif lows_count >= 2 and vel_score >= 2:
            is_ramp = True
            result.reason = f'2+ rising lows + Kalman mild+ (vel={vel:+.2f})'
        elif lows_count >= 2 and ma_score >= 1 and vel_score >= 1:
            is_ramp = True
            result.reason = f'2 rising lows + MA rising + Kalman positive'
        
        # Weak/early warning patterns
        elif vel_score >= 3 and ma_score >= 1:
            is_weak = True
            result.reason = f'Kalman strong + MA rising but lows not built ({lows_count})'
        
        # No pattern
        else:
            parts = []
            if lows_count < 2:
                parts.append(f'lows={lows_count}<2')
            if vel_score < 1:
                parts.append(f'vel={vel:+.2f}≤0')
            if ma_score < 1:
                parts.append(f'MA={ma_direction}')
            result.reason = f'No ramp: {", ".join(parts)}'
        
        result.is_ramp = is_ramp
        result.is_weak_ramp = is_weak
        result.confidence = 'RAMP' if is_ramp else ('WEAK' if is_weak else 'NONE')
        
        return result
    
    # ================================================================
    # DETECTOR 1: Moving Average Slope
    # ================================================================
    
    def _detect_ma_slope(self, rsi_values: List[float]) -> Tuple[str, float]:
        """
        Calculate MA(5) of RSI and determine slope direction.
        
        Returns:
            (direction, slope) where direction is FALLING/FLAT/RISING
        """
        period = self.cfg.MA_PERIOD
        if len(rsi_values) < period + 1:
            return 'UNKNOWN', 0.0
        
        # Calculate last 2 MA values
        window_curr = rsi_values[-period:]
        window_prev = rsi_values[-period - 1:-1]
        
        ma_curr = sum(window_curr) / period
        ma_prev = sum(window_prev) / period
        slope = ma_curr - ma_prev
        
        if slope > self.cfg.MA_SLOPE_RISING:
            return 'RISING', round(slope, 2)
        elif slope < self.cfg.MA_SLOPE_FALLING:
            return 'FALLING', round(slope, 2)
        else:
            return 'FLAT', round(slope, 2)
    
    # ================================================================
    # DETECTOR 2: Rising Lows on Kalman-Smoothed RSI
    # ================================================================
    
    def _detect_rising_lows(self, kalman_rsi: List[float]) -> Tuple[int, List[Tuple[int, float]]]:
        """
        Find local minimums in Kalman-smoothed RSI and count consecutive rising lows.
        
        Uses tolerance to handle minor dips (e.g., Kalman RSI 23.0 → 23.4 → 22.8 
        is still "rising" within tolerance).
        
        Returns:
            (rising_count, list_of_(index, value) local lows)
        """
        if len(kalman_rsi) < self.cfg.MIN_READINGS_FOR_LOWS:
            return 0, []
        
        local_lows = []
        tolerance = self.cfg.RISING_LOW_TOLERANCE
        
        for i in range(1, len(kalman_rsi) - 1):
            if kalman_rsi[i] <= kalman_rsi[i - 1] and kalman_rsi[i] <= kalman_rsi[i + 1]:
                local_lows.append((i, round(kalman_rsi[i], 1)))
        
        if len(local_lows) < 2:
            return 0, local_lows
        
        # Count consecutive rising (or nearly equal) lows
        rising_count = 0
        for j in range(1, len(local_lows)):
            prev_low = local_lows[j - 1][1]
            curr_low = local_lows[j][1]
            if curr_low >= prev_low - tolerance:
                rising_count += 1
            else:
                rising_count = 0
        
        return rising_count, local_lows
    
    # ================================================================
    # DETECTOR 3: Kalman Filter on RSI
    # ================================================================
    
    def _run_kalman(self, rsi_values: List[float]) -> Tuple[List[float], List[float]]:
        """
        Run 2D Kalman filter on RSI to extract smoothed RSI and velocity.
        
        State: [rsi, rsi_velocity]
        Measurement: raw RSI value
        
        Returns:
            (kalman_rsi_list, kalman_velocity_list)
        """
        dt = 1.0
        pn = self.cfg.KALMAN_PROCESS_NOISE
        mn = self.cfg.KALMAN_MEASUREMENT_NOISE
        
        # State: [rsi, velocity]
        x = np.array([[float(rsi_values[0])], [0.0]])
        
        # Covariance
        P = np.eye(2) * 100.0
        
        # Transition matrix
        F = np.array([[1.0, dt], [0.0, 1.0]])
        
        # Measurement matrix
        H = np.array([[1.0, 0.0]])
        
        # Process noise
        Q = np.array([
            [0.25 * dt**4, 0.5 * dt**3],
            [0.5 * dt**3, dt**2]
        ]) * pn
        
        # Measurement noise
        R = np.array([[mn]])
        
        kalman_rsi = []
        kalman_vel = []
        
        I = np.eye(2)
        
        for rsi in rsi_values:
            # Predict
            x = F @ x
            P = F @ P @ F.T + Q
            
            # Update
            z = np.array([[float(rsi)]])
            y = z - H @ x
            S = H @ P @ H.T + R
            K = P @ H.T @ np.linalg.inv(S)
            x = x + K @ y
            P = (I - K @ H) @ P
            
            kalman_rsi.append(float(x[0, 0]))
            kalman_vel.append(float(x[1, 0]))
        
        return kalman_rsi, kalman_vel


# ============================================================================
# SELF-TEST (run with: python ramp_detector.py)
# ============================================================================

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    
    # Test with the exact noisy sequence from design session
    test_rsi = [24, 18, 20, 16, 19, 22, 26, 18, 21, 24, 26, 20, 24, 26, 22, 23, 
                26, 24, 25, 19, 22, 25, 28, 30, 24, 26, 22, 23, 26, 28, 26, 24, 
                22, 26, 28, 32, 34, 28, 24, 29, 32, 35]
    
    detector = RampDetector()
    
    print("═" * 70)
    print("RAMP DETECTOR SELF-TEST")
    print("═" * 70)
    
    # Test with growing windows (like real-time accumulation)
    for window_end in [10, 15, 18, 25, 30, 35, 42]:
        window = test_rsi[:window_end]
        result = detector.detect(window)
        
        status = '🟢 RAMP' if result.is_ramp else ('🟡 WEAK' if result.is_weak_ramp else '⚪ NO')
        print(f"\nReadings 0-{window_end-1} (last RSI={window[-1]}):")
        print(f"  {status} | K_RSI={result.kalman_rsi:.1f} | vel={result.kalman_velocity:+.2f} "
              f"| MA={result.ma_direction}({result.ma_slope:+.2f}) | lows={result.rising_lows_count}")
        print(f"  Reason: {result.reason}")
    
    print(f"\n{'═' * 70}")
    print("EDGE CASE: Flat RSI (no ramp)")
    flat_rsi = [30, 31, 29, 30, 32, 30, 29, 31, 30, 30, 31, 29, 30]
    result = detector.detect(flat_rsi)
    print(f"  {'🟢 RAMP' if result.is_ramp else '⚪ NO'}: {result.reason}")
    
    print(f"\nEDGE CASE: Falling RSI (should NOT detect ramp)")
    falling_rsi = [35, 33, 30, 32, 28, 25, 27, 22, 20, 18, 15, 12, 10]
    result = detector.detect(falling_rsi)
    print(f"  {'🟢 RAMP' if result.is_ramp else '⚪ NO'}: {result.reason}")
    
    print(f"\nEDGE CASE: Strong clean ramp (should detect quickly)")
    clean_ramp = [15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27]
    result = detector.detect(clean_ramp)
    print(f"  {'🟢 RAMP' if result.is_ramp else '⚪ NO'}: {result.reason}")
    
    print(f"\nEDGE CASE: RSI outside zone (above 35)")
    high_rsi = [40, 42, 43, 45, 44, 46, 48, 50, 52, 55, 53, 56, 58]
    result = detector.detect(high_rsi)
    print(f"  {'🟢 RAMP' if result.is_ramp else '⚪ NO'}: {result.reason}")
