"""
PREDICTIVE STOP-LOSS v4.1.0 - EXIT BEFORE STOP HIT
════════════════════════════════════════════════════════════════════════════════

🔴 CRITICAL FIXES (v4.1.0):
─────────────────────────
1. ✅ PROFIT FLOOR - Won't exit on noise-level moves
2. ✅ MINIMUM R REQUIREMENT - Must be at least 0.3R in profit
3. ✅ CONFIG-DRIVEN THRESHOLDS - All parameters from config

Purpose: Detect momentum decay and exit positions BEFORE stop-loss is hit
Method: Kalman velocity + RSI divergence + acceleration analysis

Exits when (AND profit floor met):
1. Velocity decaying rapidly (>50% drop)
2. Acceleration turning negative
3. RSI divergence (price up, RSI down)
4. Predicted to hit stop-loss in 2-3 ticks

Author: Dheebanraj
Date: 2026-01-22
Version: 4.1.0
"""

import logging
from typing import Dict, Optional
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class ExitReason(Enum):
    """Reasons for predictive exit"""
    VELOCITY_DECAY = "Velocity decaying rapidly"
    NEGATIVE_ACCELERATION = "Acceleration turning negative"
    MOMENTUM_EXHAUSTION = "Momentum exhausted"
    PREDICTED_STOP_HIT = "Predicted to hit stop-loss"
    RSI_DIVERGENCE = "RSI divergence detected"
    NO_EXIT = "No exit signal"
    PROFIT_FLOOR_NOT_MET = "Profit floor not met"  # 🔴 NEW


@dataclass
class PredictiveExitSignal:
    """Signal for predictive exit"""
    should_exit: bool
    reason: ExitReason
    confidence: float  # 0.0 to 1.0
    velocity: float
    acceleration: float
    predicted_price: float
    details: str
    profit_pct: float = 0.0  # 🔴 NEW: Include profit info
    r_multiple: float = 0.0  # 🔴 NEW: Include R multiple


class PredictiveStop:
    """
    Predictive stop-loss system using Kalman filter data.
    
    🔴 CRITICAL FIX: Now includes PROFIT FLOOR check!
    
    Won't exit on noise-level moves. Must be:
    - At least MIN_PROFIT_PCT_FOR_EXIT in profit (default 0.5%)
    - At least MIN_R_FOR_PREDICTIVE_EXIT R-multiple (default 0.3R)
    
    Detects momentum decay and exits BEFORE traditional stop-loss hits.
    """
    
    def __init__(self, config):
        """
        Initialize predictive stop system.
        
        Args:
            config: Configuration module
        """
        self.config = config
        
        # Get config from PREDICTIVE_STOP_CONFIG dict
        predictive_config = getattr(config, 'PREDICTIVE_STOP_CONFIG', {})
        
        # Thresholds (from config)
        self.VELOCITY_DECAY_THRESHOLD = predictive_config.get('VELOCITY_DECAY_THRESHOLD', 0.50)
        self.MIN_VELOCITY_FOR_DECAY_CHECK = predictive_config.get('MIN_VELOCITY_FOR_DECAY_CHECK', 0.1)
        self.ACCELERATION_NEGATIVE_THRESHOLD = predictive_config.get('ACCELERATION_NEGATIVE_THRESHOLD', -0.05)
        self.STOP_LOSS_BUFFER = predictive_config.get('STOP_LOSS_BUFFER', 0.3)
        
        # 🔴 CRITICAL FIX: Profit floor parameters
        self.MIN_PROFIT_PCT = predictive_config.get('MIN_PROFIT_PCT_FOR_EXIT', 0.5)
        self.MIN_R_MULTIPLE = predictive_config.get('MIN_R_FOR_PREDICTIVE_EXIT', 0.3)
        
        # History tracking
        self.velocity_history = {}  # symbol -> [velocities]
        self.rsi_history = {}  # symbol -> [rsi values]
        
        logger.info("=" * 70)
        logger.info("✅ Predictive Stop v4.1 initialized (WITH PROFIT FLOOR)")
        logger.info("=" * 70)
        logger.info(f"   Velocity decay threshold: {self.VELOCITY_DECAY_THRESHOLD*100:.0f}%")
        logger.info(f"   Min velocity for decay check: {self.MIN_VELOCITY_FOR_DECAY_CHECK}")
        logger.info(f"   Acceleration threshold: {self.ACCELERATION_NEGATIVE_THRESHOLD}")
        logger.info(f"   🔴 PROFIT FLOOR: {self.MIN_PROFIT_PCT}% profit required")
        logger.info(f"   🔴 R FLOOR: {self.MIN_R_MULTIPLE}R required")
        logger.info("")
    
    def _calculate_r_multiple(self, current_price: float, entry_price: float, 
                               stop_loss_price: float) -> float:
        """Calculate current R multiple (risk units)"""
        risk = entry_price - stop_loss_price
        if risk <= 0:
            return 0
        return (current_price - entry_price) / risk
    
    def _calculate_profit_pct(self, current_price: float, entry_price: float) -> float:
        """Calculate current profit percentage"""
        return (current_price - entry_price) / entry_price * 100
    
    def should_exit(
        self,
        symbol: str,
        kalman_state: Dict,
        current_price: float,
        entry_price: float,
        stop_loss_price: float,
        current_rsi: Optional[float] = None,
        min_profit_override: Optional[float] = None
    ) -> PredictiveExitSignal:
        """
        Check if position should exit based on predictive indicators.
        
        🔴 CRITICAL: Now checks PROFIT FLOOR before allowing exit!
        
        Args:
            symbol: Stock symbol
            kalman_state: State from Kalman filter
            current_price: Current LTP
            entry_price: Entry price
            stop_loss_price: Stop-loss price
            current_rsi: Optional current RSI value
            min_profit_override: Optional override for MIN_PROFIT_PCT (v5.3.3 Smart TCAS)
            
        Returns:
            PredictiveExitSignal with exit decision
        """
        try:
            # Calculate profit metrics
            profit_pct = self._calculate_profit_pct(current_price, entry_price)
            r_multiple = self._calculate_r_multiple(current_price, entry_price, stop_loss_price)
            
            # Extract Kalman data
            velocity = kalman_state.get('velocity', 0.0)
            acceleration = kalman_state.get('acceleration', 0.0)
            prediction_15min = kalman_state.get('prediction_15min', current_price)
            
            # Initialize history for symbol
            if symbol not in self.velocity_history:
                self.velocity_history[symbol] = []
                self.rsi_history[symbol] = []
            
            # Store current velocity
            self.velocity_history[symbol].append(velocity)
            if len(self.velocity_history[symbol]) > 10:
                self.velocity_history[symbol].pop(0)
            
            # Store current RSI
            if current_rsi is not None:
                self.rsi_history[symbol].append(current_rsi)
                if len(self.rsi_history[symbol]) > 5:
                    self.rsi_history[symbol].pop(0)
            
            # ═══════════════════════════════════════════════════════════════
            # 🔴 CRITICAL: PROFIT FLOOR CHECK (BEFORE any exit logic)
            # v5.3.3: Smart TCAS positions can override with lower threshold
            # ═══════════════════════════════════════════════════════════════
            
            effective_min_profit = min_profit_override if min_profit_override is not None else self.MIN_PROFIT_PCT
            
            profit_floor_met = (profit_pct >= effective_min_profit and 
                               r_multiple >= self.MIN_R_MULTIPLE)
            
            if not profit_floor_met:
                # Log why we're not checking for exits
                if profit_pct < effective_min_profit:
                    floor_reason = f"profit {profit_pct:.2f}% < {effective_min_profit}%"
                else:
                    floor_reason = f"R={r_multiple:.2f} < {self.MIN_R_MULTIPLE}R"
                
                logger.debug(f"{symbol}: Predictive exit BLOCKED - {floor_reason}")
                
                return PredictiveExitSignal(
                    should_exit=False,
                    reason=ExitReason.PROFIT_FLOOR_NOT_MET,
                    confidence=0.0,
                    velocity=velocity,
                    acceleration=acceleration,
                    predicted_price=prediction_15min,
                    details=f"Profit floor not met: {floor_reason}",
                    profit_pct=profit_pct,
                    r_multiple=r_multiple
                )
            
            # ═══════════════════════════════════════════════════════════════
            # CHECK 1: VELOCITY DECAY
            # ═══════════════════════════════════════════════════════════════
            
            if len(self.velocity_history[symbol]) >= 3:
                recent_velocities = self.velocity_history[symbol][-3:]
                
                # Check if velocity was strong but now weak
                max_velocity = max(abs(v) for v in recent_velocities)
                current_velocity_abs = abs(velocity)
                
                if max_velocity > self.MIN_VELOCITY_FOR_DECAY_CHECK:
                    decay_pct = (max_velocity - current_velocity_abs) / max_velocity
                    
                    if decay_pct > self.VELOCITY_DECAY_THRESHOLD:
                        return PredictiveExitSignal(
                            should_exit=True,
                            reason=ExitReason.VELOCITY_DECAY,
                            confidence=min(decay_pct, 1.0),
                            velocity=velocity,
                            acceleration=acceleration,
                            predicted_price=prediction_15min,
                            details=f"Velocity decayed {decay_pct*100:.1f}% from peak (profit: +{profit_pct:.1f}%)",
                            profit_pct=profit_pct,
                            r_multiple=r_multiple
                        )
            
            # ═══════════════════════════════════════════════════════════════
            # CHECK 2: NEGATIVE ACCELERATION (Momentum Dying)
            # ═══════════════════════════════════════════════════════════════
            
            # For long positions, negative acceleration is bad
            if current_price > entry_price:  # In profit
                if acceleration < self.ACCELERATION_NEGATIVE_THRESHOLD:
                    if velocity < 0.1:  # And velocity also weak
                        return PredictiveExitSignal(
                            should_exit=True,
                            reason=ExitReason.NEGATIVE_ACCELERATION,
                            confidence=min(abs(acceleration) / 0.1, 1.0),
                            velocity=velocity,
                            acceleration=acceleration,
                            predicted_price=prediction_15min,
                            details=f"Acceleration negative: {acceleration:.4f} (locking +{profit_pct:.1f}%)",
                            profit_pct=profit_pct,
                            r_multiple=r_multiple
                        )
            
            # ═══════════════════════════════════════════════════════════════
            # CHECK 3: MOMENTUM EXHAUSTION
            # ═══════════════════════════════════════════════════════════════
            
            # If velocity near zero and acceleration negative = exhaustion
            # 🔴 FIX: Require higher profit for exhaustion exit (at least 1%)
            if abs(velocity) < 0.05 and acceleration < 0:
                if profit_pct >= 1.0:  # At least 1% profit for exhaustion exit
                    return PredictiveExitSignal(
                        should_exit=True,
                        reason=ExitReason.MOMENTUM_EXHAUSTION,
                        confidence=0.7,
                        velocity=velocity,
                        acceleration=acceleration,
                        predicted_price=prediction_15min,
                        details=f"Momentum exhausted, locking +{profit_pct:.1f}% profit",
                        profit_pct=profit_pct,
                        r_multiple=r_multiple
                    )
            
            # ═══════════════════════════════════════════════════════════════
            # CHECK 4: PREDICTED STOP-LOSS HIT
            # ═══════════════════════════════════════════════════════════════
            
            # Calculate distance to stop-loss
            if current_price > entry_price:  # Long position
                distance_to_stop = current_price - stop_loss_price
                
                # If prediction says we'll hit stop soon
                predicted_distance = prediction_15min - stop_loss_price
                
                if predicted_distance < distance_to_stop * self.STOP_LOSS_BUFFER:
                    # 🔴 FIX: Only exit if we have meaningful profit to protect
                    if profit_pct >= 0.8:  # At least 0.8% profit
                        return PredictiveExitSignal(
                            should_exit=True,
                            reason=ExitReason.PREDICTED_STOP_HIT,
                            confidence=0.8,
                            velocity=velocity,
                            acceleration=acceleration,
                            predicted_price=prediction_15min,
                            details=f"Predicted price ₹{prediction_15min:.2f} near stop ₹{stop_loss_price:.2f} (protecting +{profit_pct:.1f}%)",
                            profit_pct=profit_pct,
                            r_multiple=r_multiple
                        )
            
            # ═══════════════════════════════════════════════════════════════
            # CHECK 5: RSI DIVERGENCE (Advanced)
            # ═══════════════════════════════════════════════════════════════
            
            if current_rsi is not None and len(self.rsi_history[symbol]) >= 3:
                # Price making higher high but RSI making lower high = divergence
                if current_price > entry_price:  # In profit
                    recent_rsi = self.rsi_history[symbol][-3:]
                    
                    # RSI declining while price rising = bearish divergence
                    rsi_trend = recent_rsi[-1] - recent_rsi[0]
                    
                    if rsi_trend < -5:  # RSI dropped by 5+ points
                        if velocity < 0.1:  # And momentum weak
                            # 🔴 FIX: Require at least 0.8% profit for divergence exit
                            if profit_pct >= 0.8:
                                return PredictiveExitSignal(
                                    should_exit=True,
                                    reason=ExitReason.RSI_DIVERGENCE,
                                    confidence=0.75,
                                    velocity=velocity,
                                    acceleration=acceleration,
                                    predicted_price=prediction_15min,
                                    details=f"RSI divergence: RSI dropped {-rsi_trend:.1f} points (protecting +{profit_pct:.1f}%)",
                                    profit_pct=profit_pct,
                                    r_multiple=r_multiple
                                )
            
            # ═══════════════════════════════════════════════════════════════
            # NO EXIT SIGNAL
            # ═══════════════════════════════════════════════════════════════
            
            return PredictiveExitSignal(
                should_exit=False,
                reason=ExitReason.NO_EXIT,
                confidence=0.0,
                velocity=velocity,
                acceleration=acceleration,
                predicted_price=prediction_15min,
                details=f"All checks passed, hold position (+{profit_pct:.1f}%, {r_multiple:.2f}R)",
                profit_pct=profit_pct,
                r_multiple=r_multiple
            )
            
        except Exception as e:
            logger.error(f"Predictive stop error for {symbol}: {e}")
            
            # Return safe no-exit on error
            return PredictiveExitSignal(
                should_exit=False,
                reason=ExitReason.NO_EXIT,
                confidence=0.0,
                velocity=0.0,
                acceleration=0.0,
                predicted_price=current_price,
                details=f"Error: {e}",
                profit_pct=0.0,
                r_multiple=0.0
            )
    
    def reset_history(self, symbol: str):
        """Clear history for symbol"""
        if symbol in self.velocity_history:
            del self.velocity_history[symbol]
        if symbol in self.rsi_history:
            del self.rsi_history[symbol]
        logger.info(f"Reset predictive stop history for {symbol}")
    
    def get_status(self, symbol: str) -> dict:
        """Get current tracking status for a symbol"""
        return {
            'symbol': symbol,
            'velocity_history_len': len(self.velocity_history.get(symbol, [])),
            'rsi_history_len': len(self.rsi_history.get(symbol, [])),
            'min_profit_pct': self.MIN_PROFIT_PCT,
            'min_r_multiple': self.MIN_R_MULTIPLE
        }


# ════════════════════════════════════════════════════════════════════════════
# STANDALONE TEST
# ════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("Testing Predictive Stop v4.1 (with profit floor)...")
    
    class MockConfig:
        PREDICTIVE_STOP_CONFIG = {
            'VELOCITY_DECAY_THRESHOLD': 0.50,
            'MIN_VELOCITY_FOR_DECAY_CHECK': 0.1,
            'ACCELERATION_NEGATIVE_THRESHOLD': -0.05,
            'STOP_LOSS_BUFFER': 0.3,
            'MIN_PROFIT_PCT_FOR_EXIT': 0.5,
            'MIN_R_FOR_PREDICTIVE_EXIT': 0.3,
        }
    
    config = MockConfig()
    ps = PredictiveStop(config)
    
    # Simulate positions
    test_cases = [
        # Case 1: Good profit, velocity decay - SHOULD EXIT
        {
            'name': 'Good profit + velocity decay → EXIT',
            'kalman_state': {'velocity': 0.1, 'acceleration': -0.02, 'prediction_15min': 101.5},
            'current_price': 101.5,
            'entry_price': 100.0,
            'stop_loss_price': 98.0,
            'current_rsi': 62,
            'expected_exit': True
        },
        # Case 2: Poor profit, velocity decay - SHOULD NOT EXIT (floor)
        {
            'name': 'Poor profit + velocity decay → HOLD (floor)',
            'kalman_state': {'velocity': 0.1, 'acceleration': -0.02, 'prediction_15min': 100.3},
            'current_price': 100.3,  # Only +0.3% profit
            'entry_price': 100.0,
            'stop_loss_price': 98.0,
            'current_rsi': 55,
            'expected_exit': False
        },
        # Case 3: Strong momentum - SHOULD NOT EXIT
        {
            'name': 'Strong momentum → HOLD',
            'kalman_state': {'velocity': 0.5, 'acceleration': 0.1, 'prediction_15min': 102.0},
            'current_price': 101.0,
            'entry_price': 100.0,
            'stop_loss_price': 98.0,
            'current_rsi': 65,
            'expected_exit': False
        },
        # Case 4: Good profit, predicted stop hit - SHOULD EXIT
        {
            'name': 'Good profit + predicted stop → EXIT',
            'kalman_state': {'velocity': -0.3, 'acceleration': -0.1, 'prediction_15min': 98.5},
            'current_price': 101.0,  # Still +1% profit
            'entry_price': 100.0,
            'stop_loss_price': 98.0,
            'current_rsi': 45,
            'expected_exit': True
        }
    ]
    
    for test in test_cases:
        # Simulate history buildup
        ps.velocity_history['TEST'] = [0.5, 0.4, 0.3]
        ps.rsi_history['TEST'] = [65, 63, 60]
        
        signal = ps.should_exit(
            symbol='TEST',
            kalman_state=test['kalman_state'],
            current_price=test['current_price'],
            entry_price=test['entry_price'],
            stop_loss_price=test['stop_loss_price'],
            current_rsi=test['current_rsi']
        )
        
        status = "✅ PASS" if signal.should_exit == test['expected_exit'] else "❌ FAIL"
        
        print(f"\n{test['name']}:")
        print(f"  Should Exit: {signal.should_exit} (expected: {test['expected_exit']}) {status}")
        print(f"  Reason: {signal.reason.value}")
        print(f"  Profit: +{signal.profit_pct:.2f}%, R={signal.r_multiple:.2f}")
        print(f"  Details: {signal.details}")
        
        # Reset for next test
        ps.reset_history('TEST')
    
    print("\n" + "=" * 60)
    print("✅ Predictive Stop v4.1 test complete!")
