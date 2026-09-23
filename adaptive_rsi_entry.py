"""
ADAPTIVE_RSI_ENTRY.PY - Smart RSI Entry Logic v3.0.0
=====================================================

Adapts RSI entry thresholds based on pattern strength.
Strong recoveries = Higher RSI threshold (enter on momentum)
Weak recoveries = Lower RSI threshold (wait for pullback)

v3.0.0 CHANGES (2026-02-03):
────────────────────────────
🔴 REMOVED: Momentum Sequence HARD BLOCK (the "Symphony Killer")
   - RSI above adaptive threshold now triggers IMMEDIATELY
   - No more waiting 4 consecutive rising readings over ~20 minutes
   - V-Recoveries are fast; the old gate punished the exact pattern we target
   - Per-stock ADX + ChatGPT now handle trend viability (smarter decision)
✅ KEPT: check_momentum_sequence() as UTILITY (for scoring/logging only)
✅ KEPT: check_sustained_momentum() as UTILITY
✅ KEPT: check_rsi_sequence() as UTILITY
✅ KEPT: All RSI upper bound protections (65 soft, 70 hard)
✅ KEPT: Adaptive threshold logic per stock

v2.0.0 CHANGES (2026-01-28):
────────────────────────────
✅ RSI_MIN_SEQUENCE_LENGTH = 4 (was 3) - Now scoring reference only
✅ RSI_MIN_TOTAL_RISE = 5.0 - Now scoring reference only
✅ Enhanced check_momentum_sequence() with total rise validation

Author: Dheebanraj
Date: 2026-02-03
Version: 3.0.0
"""

from typing import Tuple, Optional
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class AdaptiveRSIEntry:
    """
    Adaptive RSI entry logic based on V-Recovery strength.
    
    Key Insight:
    - Strong momentum stocks (241%, 341% recovery) rarely dip to RSI < 30
    - They often stay > RSI 50 during entire uptrend
    - Fixed RSI < 30 causes you to MISS the trade entirely!
    
    Solution:
    - Adapt RSI threshold based on recovery strength
    - For EXTREME recoveries (>200%): Enter when RSI crosses > 50
    - For STRONG recoveries (150-200%): Enter when RSI crosses > 45
    - For MODERATE recoveries (100-150%): Enter when RSI crosses > 40
    - For WEAK recoveries (60-100%): Enter when RSI crosses > 35
    
    🔴 v4.1.0 CRITICAL FIX: RSI UPPER BOUND
    - Blocks entries when RSI > 70 (exhausted momentum)
    - Warns when RSI > 65 (approaching exhaustion)
    
    🔴 v3.0.0 CHANGE: MOMENTUM SEQUENCE REMOVED AS GATE
    - RSI above adaptive threshold = IMMEDIATE entry signal
    - Momentum sequence methods kept as utilities for scoring/logging
    - Per-stock ADX + ChatGPT now evaluate trend viability
    """
    
    # Recovery strength categories
    EXTREME_RECOVERY = 200.0   # >200% recovery
    STRONG_RECOVERY = 150.0    # 150-200% recovery
    MODERATE_RECOVERY = 100.0  # 100-150% recovery
    WEAK_RECOVERY = 60.0       # 60-100% recovery
    
    # Corresponding RSI thresholds
    RSI_EXTREME = 50.0   # Enter on strength confirmation
    RSI_STRONG = 45.0    # Enter on minor pullback
    RSI_MODERATE = 40.0  # Enter on moderate pullback
    RSI_WEAK = 35.0      # Enter on deeper pullback
    RSI_DEFAULT = 30.0   # Original conservative threshold
    
    # 🔴 v4.1.0: RSI Upper Bounds (CRITICAL FIX)
    RSI_UPPER_BOUND_SOFT = 65.0   # Warning threshold
    RSI_UPPER_BOUND_HARD = 70.0   # Absolute blocking threshold
    
    # 🔴 v2.0.0: Stricter Momentum Sequence
    RSI_MIN_SEQUENCE_LENGTH = 4   # Need 4 consecutive rising readings (was 3)
    RSI_MIN_TOTAL_RISE = 5.0      # Must rise by at least 5 RSI points
    
    def __init__(self, config=None):
        """Initialize adaptive RSI entry system with optional config"""
        self.stock_profiles = {}  # Store learned RSI profiles per stock
        self._rsi_history_cache = {}  # Cache RSI history per stock
        
        # Load settings from config if provided
        if config:
            self.RSI_UPPER_BOUND_SOFT = getattr(config, 'RSI_MAX_CONFIRMATION', 65.0)
            self.RSI_UPPER_BOUND_HARD = getattr(config, 'RSI_UPPER_BOUND_HARD', 70.0)
            self.RSI_MIN_SEQUENCE_LENGTH = getattr(config, 'RSI_MIN_SEQUENCE_LENGTH', 4)
            self.RSI_MIN_TOTAL_RISE = getattr(config, 'RSI_MIN_TOTAL_RISE', 5.0)
            
            logger.info(f"✅ Adaptive RSI Entry v2.0.0 initialized:")
            logger.info(f"   Upper bounds: soft={self.RSI_UPPER_BOUND_SOFT}, hard={self.RSI_UPPER_BOUND_HARD}")
            logger.info(f"   Sequence: {self.RSI_MIN_SEQUENCE_LENGTH} readings, min rise +{self.RSI_MIN_TOTAL_RISE}")
        else:
            logger.info("✅ Adaptive RSI Entry v2.0.0 initialized (default settings)")
    
    def get_entry_threshold(self, symbol: str, recovery_percent: float) -> Tuple[float, str]:
        """
        Get adaptive RSI threshold based on recovery strength.
        
        Args:
            symbol: Stock symbol
            recovery_percent: V-Recovery percentage (e.g., 241.0 for 241%)
            
        Returns:
            (rsi_threshold, reasoning)
        """
        # Check if we have a learned profile for this stock
        if symbol in self.stock_profiles:
            learned_threshold = self.stock_profiles[symbol]['threshold']
            learned_reason = f"Learned profile for {symbol}"
            logger.debug(f"{symbol}: Using learned threshold {learned_threshold:.1f}")
            return learned_threshold, learned_reason
        
        # Adaptive threshold based on recovery strength
        if recovery_percent >= self.EXTREME_RECOVERY:
            threshold = self.RSI_EXTREME
            reason = f"EXTREME recovery ({recovery_percent:.0f}%) - Enter on momentum (RSI > {threshold})"
            
        elif recovery_percent >= self.STRONG_RECOVERY:
            threshold = self.RSI_STRONG
            reason = f"STRONG recovery ({recovery_percent:.0f}%) - Enter on strength (RSI > {threshold})"
            
        elif recovery_percent >= self.MODERATE_RECOVERY:
            threshold = self.RSI_MODERATE
            reason = f"MODERATE recovery ({recovery_percent:.0f}%) - Enter on pullback (RSI > {threshold})"
            
        elif recovery_percent >= self.WEAK_RECOVERY:
            threshold = self.RSI_WEAK
            reason = f"WEAK recovery ({recovery_percent:.0f}%) - Wait for dip (RSI > {threshold})"
            
        else:
            threshold = self.RSI_DEFAULT
            reason = f"Conservative entry (recovery {recovery_percent:.0f}% < 60%) - Deep pullback (RSI > {threshold})"
        
        logger.info(f"{symbol}: Adaptive threshold = {threshold:.1f} | {reason}")
        return threshold, reason


    def check_momentum_sequence(
        self,
        rsi_history: list,
        min_sequence_length: int = None
    ) -> Tuple[bool, str]:
        """
        Check if RSI shows continuous upward momentum.
        
        🔴 v2.0.0 ENHANCED:
        - Default sequence length = 4 (was 3)
        - Requires minimum total rise of 5 RSI points
        
        User's Insight: "RSI1 > RSI2 > RSI3 > RSI4... continuously rising"
        
        This is MORE sophisticated than just checking 2 points!
        It confirms SUSTAINED momentum, not just a spike.
        
        Args:
            rsi_history: List of RSI values in chronological order
                        [oldest, ..., newest]
            min_sequence_length: Minimum consecutive rising values needed
                                (default 4 = need 4 readings in a row)
        
        Returns:
            (is_rising, reason)
        
        Example:
            RSI: [48, 47, 51, 52] → False (dipped at 47)
            RSI: [28, 30, 33, 36] → True (continuous rise, +8 points!)
            RSI: [48, 49, 50, 51] → False (only +3 points, need +5)
        """
        # Use default if not specified
        if min_sequence_length is None:
            min_sequence_length = self.RSI_MIN_SEQUENCE_LENGTH
        
        if not rsi_history or len(rsi_history) < min_sequence_length:
            return False, f"Need {min_sequence_length} RSI readings, have {len(rsi_history) if rsi_history else 0}"
        
        # Take last N readings
        recent = rsi_history[-min_sequence_length:]
        
        # Check if continuously rising
        is_rising = all(recent[i] < recent[i+1] for i in range(len(recent)-1))
        
        if not is_rising:
            # Find where it dipped
            dips = []
            for i in range(len(recent)-1):
                if recent[i] >= recent[i+1]:
                    dips.append(f"{recent[i]:.1f}→{recent[i+1]:.1f}")
            
            reason = f"RSI not continuously rising (dips: {', '.join(dips)})"
            return False, reason
        
        # 🔴 v2.0.0: Check minimum total rise
        total_rise = recent[-1] - recent[0]
        
        if total_rise < self.RSI_MIN_TOTAL_RISE:
            reason = (
                f"RSI rising (+{total_rise:.1f}) but below "
                f"required momentum (+{self.RSI_MIN_TOTAL_RISE:.1f}): "
                f"{recent[0]:.1f} → {recent[-1]:.1f}"
            )
            return False, reason
        
        # SUCCESS: Continuous rise with sufficient magnitude
        reason = (
            f"✅ Momentum confirmed! "
            f"RSI: {recent[0]:.1f} → {recent[-1]:.1f} "
            f"(+{total_rise:.1f} over {len(recent)} readings)"
        )
        return True, reason


    def check_sustained_momentum(
        self,
        symbol: str,
        rsi_history: list,
        min_samples: int = None
    ) -> Tuple[bool, str]:
        """
        Check for SUSTAINED RSI momentum (User's brilliant insight!).
        
        Instead of just checking current > previous (2 points),
        verify RSI is CONSISTENTLY RISING over multiple samples.
        
        User's insight: "RSI1 > RSI2 > RSI3 > RSI4 ... > RSIn"
        
        This filters noise and confirms genuine momentum building!
        
        Args:
            symbol: Stock symbol
            rsi_history: List of RSI values [newest, ..., oldest]
                        e.g., [52.1, 51.3, 50.2, 48.9, 47.8]
            min_samples: Minimum samples required (default from config)
            
        Returns:
            (momentum_confirmed, reason)
        """
        if min_samples is None:
            min_samples = self.RSI_MIN_SEQUENCE_LENGTH
        
        # Need at least min_samples
        if len(rsi_history) < min_samples:
            return False, f"Only {len(rsi_history)} samples, need {min_samples}"
        
        # Check if RSI is monotonically increasing
        # rsi_history is [newest, ..., oldest], so we check newest > older
        is_rising = True
        for i in range(len(rsi_history) - 1):
            if rsi_history[i] <= rsi_history[i + 1]:
                # Current sample NOT greater than previous - momentum broken!
                is_rising = False
                break
        
        if is_rising:
            # Calculate momentum strength
            total_rise = rsi_history[0] - rsi_history[-1]
            samples = len(rsi_history)
            avg_rise_per_sample = total_rise / (samples - 1)
            
            # 🔴 v2.0.0: Check minimum total rise
            if total_rise < self.RSI_MIN_TOTAL_RISE:
                reason = (
                    f"RSI rising (+{total_rise:.1f}) but below "
                    f"required momentum (+{self.RSI_MIN_TOTAL_RISE:.1f})"
                )
                return False, reason
            
            reason = (
                f"SUSTAINED MOMENTUM! RSI rising for {samples} samples "
                f"({rsi_history[-1]:.1f} → {rsi_history[0]:.1f}, "
                f"+{total_rise:.1f} total, +{avg_rise_per_sample:.1f} avg/sample)"
            )
            logger.info(f"{symbol}: ✅ {reason}")
            return True, reason
        else:
            # Find where momentum broke
            for i in range(len(rsi_history) - 1):
                if rsi_history[i] <= rsi_history[i + 1]:
                    reason = (
                        f"Momentum broken at sample {i+1}: "
                        f"{rsi_history[i]:.1f} ≤ {rsi_history[i+1]:.1f}"
                    )
                    return False, reason
            
            return False, "No sustained momentum"


    def check_rsi_sequence(
        self, 
        symbol: str,
        rsi_history: list,
        min_sequence_length: int = None
    ) -> Tuple[bool, str]:
        """
        Check if RSI shows SUSTAINED upward momentum (sequence check).
        
        User Insight: "Not just RSI > 50, but RSI1 > RSI2 > RSI3 > RSI4..."
        This filters out noise and confirms real momentum!
        
        Args:
            symbol: Stock symbol
            rsi_history: List of recent RSI values [oldest, ..., newest]
            min_sequence_length: Minimum consecutive increases needed (default from config)
            
        Returns:
            (is_sustained_uptrend, reason)
            
        Examples:
            ✅ [28, 31, 34, 38] → Sustained uptrend! (+10 points)
            ❌ [45, 51, 49, 52] → Choppy, no sustained trend
            ❌ [48, 49, 50, 51] → Rising but only +3 (need +5)
        """
        if min_sequence_length is None:
            min_sequence_length = self.RSI_MIN_SEQUENCE_LENGTH
        
        if not rsi_history or len(rsi_history) < 2:
            return False, "Insufficient RSI history"
        
        # Need at least min_sequence_length points
        if len(rsi_history) < min_sequence_length:
            return False, f"Need {min_sequence_length} samples, have {len(rsi_history)}"
        
        # Check for monotonic increase (each value > previous)
        increases = 0
        for i in range(1, len(rsi_history)):
            if rsi_history[i] > rsi_history[i-1]:
                increases += 1
            else:
                # Sequence broken
                break
        
        # Need consecutive increases
        is_sustained = increases >= (min_sequence_length - 1)
        
        if is_sustained:
            # Calculate total rise
            recent = rsi_history[-min_sequence_length:]
            total_rise = recent[-1] - recent[0]
            
            # 🔴 v2.0.0: Check minimum total rise
            if total_rise < self.RSI_MIN_TOTAL_RISE:
                reason = (
                    f"RSI sequence OK but only +{total_rise:.1f} "
                    f"(need +{self.RSI_MIN_TOTAL_RISE:.1f})"
                )
                return False, reason
            
            sequence_str = " → ".join([f"{r:.1f}" for r in recent])
            reason = (
                f"✅ SUSTAINED momentum! "
                f"RSI: {sequence_str} "
                f"(+{total_rise:.1f}, {increases} consecutive)"
            )
            logger.info(f"{symbol}: {reason}")
            return True, reason
        else:
            if len(rsi_history) >= 2:
                latest = rsi_history[-1]
                previous = rsi_history[-2]
                if latest > previous:
                    reason = (
                        f"RSI rising ({previous:.1f} → {latest:.1f}) "
                        f"but only {increases} consecutive - need {min_sequence_length-1}"
                    )
                else:
                    reason = f"RSI not rising ({previous:.1f} → {latest:.1f})"
            else:
                reason = "Insufficient data for sequence check"
        
        return False, reason


    def check_entry_signal(
        self, 
        symbol: str, 
        current_rsi: float, 
        rsi_history: Optional[list],
        recovery_percent: float,
        min_sequence_length: int = None
    ) -> Tuple[bool, str]:
        """
        Check if RSI conditions are met for entry.
        
        🔴 v3.0.0 SIMPLIFIED: Momentum sequence REMOVED as hard block.
        RSI above adaptive threshold = IMMEDIATE entry signal.
        Per-stock ADX + ChatGPT now handle trend viability.
        
        Key Logic:
        1. CHECK RSI UPPER BOUND FIRST (blocks exhausted entries)
        2. Get adaptive threshold based on recovery strength
        3. Check RSI is ABOVE threshold → ENTRY SIGNAL ✅
        4. Log momentum info for diagnostics (NOT a gate)
        
        Args:
            symbol: Stock symbol
            current_rsi: Current RSI value (float or tuple)
            rsi_history: List of RSI values (floats) for diagnostics
            recovery_percent: V-Recovery percentage
            min_sequence_length: Unused (kept for API compatibility)
            
        Returns:
            (signal_triggered, reason)
        """
        # ✅ DEFENSIVE: Handle tuple format (timestamp, value) if passed
        if isinstance(current_rsi, tuple):
            current_rsi = current_rsi[1]
        
        # ✅ DEFENSIVE: Clean rsi_history if it contains tuples
        if rsi_history and len(rsi_history) > 0 and isinstance(rsi_history[0], tuple):
            rsi_history = [val for ts, val in rsi_history]
        
        # 🔴 RSI UPPER BOUND CHECK FIRST
        # This blocks entries when momentum is exhausted (RSI > 70)
        if current_rsi >= self.RSI_UPPER_BOUND_HARD:
            reason = (
                f"🔴 RSI {current_rsi:.1f} >= {self.RSI_UPPER_BOUND_HARD} (EXHAUSTED) | "
                f"Entry BLOCKED - momentum exhausted, high reversal risk"
            )
            logger.warning(f"{symbol}: {reason}")
            return False, reason
        
        if current_rsi >= self.RSI_UPPER_BOUND_SOFT:
            # Warning but don't block yet
            logger.warning(
                f"{symbol}: ⚠️ RSI {current_rsi:.1f} approaching exhaustion "
                f"(soft ceiling {self.RSI_UPPER_BOUND_SOFT})"
            )
        
        # Get adaptive threshold
        threshold, threshold_reason = self.get_entry_threshold(symbol, recovery_percent)
        
        # ONLY GATE: RSI must be above adaptive threshold
        if current_rsi < threshold:
            reason = f"RSI {current_rsi:.1f} below threshold {threshold:.1f}"
            return False, reason
        
        # ═══════════════════════════════════════════════════════════════
        # v3.0.0: RSI ABOVE THRESHOLD = IMMEDIATE ENTRY SIGNAL
        # Momentum sequence removed as gate. ADX + ChatGPT decide.
        # Log momentum info for diagnostics only.
        # ═══════════════════════════════════════════════════════════════
        
        # Log momentum diagnostics (informational, NOT blocking)
        momentum_info = ""
        if rsi_history and len(rsi_history) >= 2:
            seq_len = min(len(rsi_history), self.RSI_MIN_SEQUENCE_LENGTH)
            is_rising, momentum_reason = self.check_momentum_sequence(
                rsi_history, seq_len
            )
            momentum_info = f" | Momentum: {'✅ ' if is_rising else '⚠️ '}{momentum_reason}"
            logger.info(f"{symbol}:   RSI History: {[f'{x:.1f}' for x in rsi_history[-6:]]}")
        
        reason = (
            f"RSI {current_rsi:.1f} > {threshold:.1f} ✅ | "
            f"{threshold_reason}{momentum_info}"
        )
        logger.info(f"{symbol}: ✅ ENTRY SIGNAL | {reason}")
        return True, reason

    
    def learn_stock_profile(self, symbol: str, successful_entry_rsi: float):
        """
        Learn stock-specific RSI profile from successful trades.
        
        Over time, this builds a database of optimal entry RSI levels
        for each stock based on actual trading results.
        
        Args:
            symbol: Stock symbol
            successful_entry_rsi: RSI level at which successful entry happened
        """
        if symbol not in self.stock_profiles:
            self.stock_profiles[symbol] = {
                'entries': [],
                'threshold': successful_entry_rsi
            }
        else:
            self.stock_profiles[symbol]['entries'].append(successful_entry_rsi)
            
            # Recalculate threshold as average of successful entries
            entries = self.stock_profiles[symbol]['entries']
            avg_rsi = sum(entries) / len(entries)
            self.stock_profiles[symbol]['threshold'] = avg_rsi
        
        logger.info(
            f"{symbol}: Learned RSI profile updated - "
            f"Optimal entry ≈ {self.stock_profiles[symbol]['threshold']:.1f}"
        )
    

    def update_rsi_history(self, symbol: str, rsi_value: float, max_history: int = 6):
        """
        Update RSI history for sequence checking.
        
        🔴 v2.0.0: Increased default max_history to 6 (from 5)
        This allows checking 4+ reading sequences with buffer
        
        Stores RSI values in chronological order: [oldest, ..., newest]
        This allows easy sequence checking: RSI[i] > RSI[i-1]
        
        Args:
            symbol: Stock symbol
            rsi_value: New RSI value
            max_history: Maximum samples to keep (default 6)
        """
        if symbol not in self._rsi_history_cache:
            self._rsi_history_cache[symbol] = []
        
        # Add new value at the END (chronological order)
        # Order: [oldest, ..., newest]
        self._rsi_history_cache[symbol].append(rsi_value)
        
        # Keep only last N samples (remove oldest if too many)
        if len(self._rsi_history_cache[symbol]) > max_history:
            self._rsi_history_cache[symbol].pop(0)  # Remove oldest


    def get_rsi_history(self, symbol: str) -> list:
        """
        Get RSI history for a symbol.
        
        Args:
            symbol: Stock symbol
            
        Returns:
            List of RSI values [oldest, ..., newest]
        """
        return self._rsi_history_cache.get(symbol, [])


    def get_stock_profile_summary(self) -> str:
        """
        Get summary of learned stock profiles.
        
        Returns:
            Human-readable summary
        """
        if not self.stock_profiles:
            return "No stock profiles learned yet."
        
        summary = "📊 LEARNED STOCK RSI PROFILES:\n"
        summary += "=" * 60 + "\n"
        
        for symbol, profile in sorted(self.stock_profiles.items()):
            num_entries = len(profile['entries'])
            threshold = profile['threshold']
            summary += f"{symbol:12s} | RSI ≈ {threshold:5.1f} | {num_entries} trades\n"
        
        return summary


# Global instance (singleton)
_adaptive_rsi = None

def get_adaptive_rsi_entry(config=None) -> AdaptiveRSIEntry:
    """
    Get global adaptive RSI entry instance.
    
    🔴 v2.0.0: Now loads RSI_MIN_SEQUENCE_LENGTH and RSI_MIN_TOTAL_RISE from config
    
    Args:
        config: Optional config object with RSI settings
        
    Returns:
        AdaptiveRSIEntry instance
    """
    global _adaptive_rsi
    if _adaptive_rsi is None:
        _adaptive_rsi = AdaptiveRSIEntry(config)
    return _adaptive_rsi
