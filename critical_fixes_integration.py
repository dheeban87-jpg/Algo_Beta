"""
CRITICAL FIXES INTEGRATION MODULE v4.1.0
═══════════════════════════════════════════════════════════════════════════════

This module provides integration helpers for the critical fixes.
Import this module and use its utilities in your existing code.

🔴 CRITICAL FIXES:
─────────────────────────
1. ✅ ATR Clamping - clamp_atr()
2. ✅ RSI Upper Bound - check_rsi_upper_bound()
3. ✅ Profit Floor Check - check_profit_floor()
4. ✅ Starvation Position Sizing - get_starvation_position_multiplier()
5. ✅ Score Debouncing - ScoreDebouncer class

USAGE:
─────────────────────────
from critical_fixes_integration import (
    clamp_atr,
    check_rsi_upper_bound,
    check_profit_floor,
    ScoreDebouncer,
    get_starvation_position_multiplier
)

Author: Trading System v4.1
Date: 2026-01-22
"""

import logging
from datetime import datetime, timedelta
from typing import Tuple, Optional, Dict
from dataclasses import dataclass

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# 1. ATR CLAMPING
# ═══════════════════════════════════════════════════════════════════════════════

def clamp_atr(
    atr_value: float, 
    price: float, 
    min_pct: float = 0.3, 
    max_pct: float = 3.0
) -> float:
    """
    🔴 CRITICAL FIX #1: Clamp ATR to prevent explosion on news candles.
    
    Problem: During news events, ATR can spike 5-10x normal, causing:
    - Stops set 10% away from entry
    - Targets set 15% away
    - Instant stop-outs on normal retracements
    
    Solution: Clamp ATR between min and max % of price
    
    Args:
        atr_value: Raw ATR value
        price: Current stock price
        min_pct: Minimum ATR as % of price (default 0.3%)
        max_pct: Maximum ATR as % of price (default 3.0%)
        
    Returns:
        Clamped ATR value
        
    Example:
        >>> clamp_atr(50.0, 1000.0)  # 5% ATR on ₹1000 stock
        30.0  # Clamped to 3%
        >>> clamp_atr(1.0, 1000.0)  # 0.1% ATR
        3.0  # Clamped to 0.3%
    """
    min_atr = price * (min_pct / 100)
    max_atr = price * (max_pct / 100)
    
    clamped = max(min_atr, min(atr_value, max_atr))
    
    if clamped != atr_value:
        direction = "↓" if clamped < atr_value else "↑"
        logger.warning(f"🔴 ATR CLAMPED: {atr_value:.2f} {direction} {clamped:.2f} "
                      f"(bounds: {min_atr:.2f}-{max_atr:.2f})")
    
    return clamped


def get_atr_based_levels(
    entry_price: float,
    atr: float,
    target_mult: float = 1.2,
    stop_mult: float = 1.5,
    clamp: bool = True
) -> dict:
    """
    Calculate stop and target levels using ATR with optional clamping.
    
    Args:
        entry_price: Entry price
        atr: ATR value (will be clamped if clamp=True)
        target_mult: ATR multiplier for target
        stop_mult: ATR multiplier for stop
        clamp: Whether to clamp ATR (default True)
        
    Returns:
        dict with target_price, stop_price, target_pct, stop_pct, atr_clamped
    """
    # Clamp ATR if requested
    atr_used = clamp_atr(atr, entry_price) if clamp else atr
    
    # Calculate levels
    target_distance = atr_used * target_mult
    stop_distance = atr_used * stop_mult
    
    target_price = entry_price + target_distance
    stop_price = entry_price - stop_distance
    
    target_pct = (target_distance / entry_price) * 100
    stop_pct = (stop_distance / entry_price) * 100
    
    return {
        'target_price': target_price,
        'stop_price': stop_price,
        'target_pct': target_pct,
        'stop_pct': stop_pct,
        'atr_original': atr,
        'atr_clamped': atr_used,
        'was_clamped': atr != atr_used
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 2. RSI UPPER BOUND CHECK
# ═══════════════════════════════════════════════════════════════════════════════

def check_rsi_upper_bound(
    current_rsi: float,
    soft_ceiling: float = 65.0,
    hard_ceiling: float = 70.0
) -> Tuple[bool, str, str]:
    """
    🔴 CRITICAL FIX #2: Check if RSI is within acceptable upper bounds.
    
    Prevents late, exhausted entries that are likely to reverse.
    
    Args:
        current_rsi: Current RSI value
        soft_ceiling: RSI level to warn about (default 65)
        hard_ceiling: RSI level to BLOCK entry (default 70)
        
    Returns:
        (is_allowed, warning_level, reason)
        - is_allowed: True if entry is permitted
        - warning_level: "NONE", "CAUTION", "BLOCKED"
        - reason: Explanation string
        
    Example:
        >>> check_rsi_upper_bound(52.0)
        (True, "NONE", "RSI 52.0 within safe range")
        >>> check_rsi_upper_bound(67.0)
        (True, "CAUTION", "RSI 67.0 near ceiling...")
        >>> check_rsi_upper_bound(72.0)
        (False, "BLOCKED", "RSI 72.0 above hard ceiling...")
    """
    if current_rsi >= hard_ceiling:
        return (
            False, 
            "BLOCKED",
            f"🔴 RSI {current_rsi:.1f} >= {hard_ceiling} HARD CEILING - "
            f"Entry BLOCKED (exhausted momentum, high reversal risk)"
        )
    
    if current_rsi >= soft_ceiling:
        return (
            True,
            "CAUTION",
            f"⚠️ RSI {current_rsi:.1f} >= {soft_ceiling} - "
            f"Entry allowed but CAUTION (momentum may be exhausted)"
        )
    
    return (
        True,
        "NONE",
        f"RSI {current_rsi:.1f} within safe range (< {soft_ceiling})"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# 3. PROFIT FLOOR CHECK
# ═══════════════════════════════════════════════════════════════════════════════

def check_profit_floor(
    current_price: float,
    entry_price: float,
    stop_price: float,
    min_profit_pct: float = 0.5,
    min_r_multiple: float = 0.3
) -> Tuple[bool, float, float, str]:
    """
    🔴 CRITICAL FIX #3: Check if profit floor is met for predictive exits.
    
    Prevents exiting on noise-level moves.
    
    Args:
        current_price: Current price
        entry_price: Entry price
        stop_price: Stop loss price
        min_profit_pct: Minimum profit % required (default 0.5%)
        min_r_multiple: Minimum R-multiple required (default 0.3R)
        
    Returns:
        (floor_met, profit_pct, r_multiple, reason)
        
    Example:
        >>> check_profit_floor(101.0, 100.0, 98.0)
        (True, 1.0, 0.5, "Profit floor met: +1.00%, 0.50R")
        >>> check_profit_floor(100.3, 100.0, 98.0)
        (False, 0.3, 0.15, "Profit floor NOT met: +0.30% < 0.50%")
    """
    profit_pct = (current_price - entry_price) / entry_price * 100
    
    risk = entry_price - stop_price
    r_multiple = (current_price - entry_price) / risk if risk > 0 else 0
    
    pct_ok = profit_pct >= min_profit_pct
    r_ok = r_multiple >= min_r_multiple
    floor_met = pct_ok and r_ok
    
    if floor_met:
        reason = f"Profit floor met: +{profit_pct:.2f}%, {r_multiple:.2f}R"
    elif not pct_ok:
        reason = f"Profit floor NOT met: +{profit_pct:.2f}% < {min_profit_pct}%"
    else:
        reason = f"Profit floor NOT met: {r_multiple:.2f}R < {min_r_multiple}R"
    
    return (floor_met, profit_pct, r_multiple, reason)


# ═══════════════════════════════════════════════════════════════════════════════
# 4. STARVATION POSITION SIZING
# ═══════════════════════════════════════════════════════════════════════════════

def get_starvation_position_multiplier(
    trades_today: int,
    min_daily_trades: int,
    current_time: datetime,
    reduction_start_hour: int = 11,
    reduction_start_minute: int = 30,
    starvation_multiplier: float = 0.5
) -> Tuple[float, bool, str]:
    """
    🔴 CRITICAL FIX #4: Get position size multiplier based on starvation mode.
    
    Lower-quality trades (from reduced thresholds) should risk less capital.
    
    Args:
        trades_today: Number of trades executed today
        min_daily_trades: Minimum daily trades target
        current_time: Current datetime
        reduction_start_hour: Hour when starvation mode starts
        reduction_start_minute: Minute when starvation mode starts
        starvation_multiplier: Position size multiplier in starvation mode
        
    Returns:
        (multiplier, is_starvation_mode, reason)
        
    Example:
        >>> get_starvation_position_multiplier(0, 1, datetime(2026, 1, 22, 12, 0))
        (0.5, True, "Starvation mode - reduced position")
        >>> get_starvation_position_multiplier(1, 1, datetime(2026, 1, 22, 12, 0))
        (1.0, False, "Normal position size (min trades met)")
    """
    # If min trades already met, normal sizing
    if trades_today >= min_daily_trades:
        return (1.0, False, "Normal position size (min trades met)")
    
    # Before starvation window, normal sizing
    starvation_start = current_time.replace(
        hour=reduction_start_hour, 
        minute=reduction_start_minute, 
        second=0
    )
    
    if current_time < starvation_start:
        return (1.0, False, "Normal position size (before starvation window)")
    
    # In starvation mode - reduced sizing
    return (
        starvation_multiplier, 
        True, 
        f"Starvation mode - {starvation_multiplier*100:.0f}% position size"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# 5. SCORE DEBOUNCING
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class DebounceState:
    """State for a single symbol's score debouncing"""
    symbol: str
    last_score: float = 0.0
    last_check_time: Optional[datetime] = None
    consecutive_above: int = 0
    consecutive_below: int = 0
    last_entry_attempt: Optional[datetime] = None
    entry_blocked_until: Optional[datetime] = None


class ScoreDebouncer:
    """
    🔴 CRITICAL FIX #5: Debounce score oscillation near thresholds.
    
    Problem: Score oscillates around threshold (49, 51, 48, 52...) causing
    repeated entry attempts and API spam.
    
    Solution:
    1. Require score to exceed threshold by hysteresis margin
    2. Require multiple consecutive readings above threshold
    3. Cooldown period after failed attempts
    """
    
    def __init__(
        self,
        hysteresis_points: float = 3.0,
        min_consecutive: int = 2,
        cooldown_minutes: int = 5
    ):
        """
        Initialize score debouncer.
        
        Args:
            hysteresis_points: Score must exceed threshold by this much
            min_consecutive: Minimum consecutive readings above threshold
            cooldown_minutes: Cooldown after failed entry attempt
        """
        self.hysteresis_points = hysteresis_points
        self.min_consecutive = min_consecutive
        self.cooldown_minutes = cooldown_minutes
        
        self.states: Dict[str, DebounceState] = {}
        
        logger.info(f"✅ Score Debouncer initialized")
        logger.info(f"   Hysteresis: {hysteresis_points} points")
        logger.info(f"   Min consecutive: {min_consecutive}")
        logger.info(f"   Cooldown: {cooldown_minutes} min")
    
    def _get_state(self, symbol: str) -> DebounceState:
        """Get or create state for symbol"""
        if symbol not in self.states:
            self.states[symbol] = DebounceState(symbol=symbol)
        return self.states[symbol]
    
    def check_entry_allowed(
        self,
        symbol: str,
        current_score: float,
        threshold: float
    ) -> Tuple[bool, str]:
        """
        Check if entry is allowed after debouncing.
        
        Args:
            symbol: Stock symbol
            current_score: Current entry score
            threshold: Score threshold for entry
            
        Returns:
            (entry_allowed, reason)
        """
        state = self._get_state(symbol)
        now = datetime.now()
        
        # Check cooldown
        if state.entry_blocked_until and now < state.entry_blocked_until:
            remaining = (state.entry_blocked_until - now).total_seconds() / 60
            return (False, f"Cooldown active ({remaining:.1f} min remaining)")
        
        # Calculate effective threshold with hysteresis
        effective_threshold = threshold + self.hysteresis_points
        
        # Update consecutive counters
        if current_score >= effective_threshold:
            state.consecutive_above += 1
            state.consecutive_below = 0
        else:
            state.consecutive_above = 0
            state.consecutive_below += 1
        
        state.last_score = current_score
        state.last_check_time = now
        
        # Check if entry allowed
        if current_score < threshold:
            return (False, f"Score {current_score:.1f} below threshold {threshold}")
        
        if current_score < effective_threshold:
            return (
                False, 
                f"Score {current_score:.1f} in hysteresis zone "
                f"({threshold} to {effective_threshold})"
            )
        
        if state.consecutive_above < self.min_consecutive:
            return (
                False, 
                f"Need {self.min_consecutive} consecutive readings, "
                f"have {state.consecutive_above}"
            )
        
        # Entry allowed!
        return (
            True, 
            f"Score {current_score:.1f} > {effective_threshold} "
            f"for {state.consecutive_above} readings"
        )
    
    def record_entry_attempt(self, symbol: str, success: bool):
        """
        Record an entry attempt for cooldown management.
        
        Args:
            symbol: Stock symbol
            success: Whether entry was successful
        """
        state = self._get_state(symbol)
        state.last_entry_attempt = datetime.now()
        
        if not success:
            # Apply cooldown
            state.entry_blocked_until = (
                datetime.now() + timedelta(minutes=self.cooldown_minutes)
            )
            state.consecutive_above = 0
            logger.info(f"{symbol}: Entry failed, cooldown until {state.entry_blocked_until}")
        else:
            # Clear cooldown on success
            state.entry_blocked_until = None
            state.consecutive_above = 0
    
    def reset(self, symbol: str):
        """Reset state for symbol"""
        if symbol in self.states:
            del self.states[symbol]
    
    def get_status(self, symbol: str) -> dict:
        """Get current debounce status for symbol"""
        state = self._get_state(symbol)
        now = datetime.now()
        
        return {
            'symbol': symbol,
            'last_score': state.last_score,
            'consecutive_above': state.consecutive_above,
            'consecutive_below': state.consecutive_below,
            'in_cooldown': (
                state.entry_blocked_until is not None and 
                now < state.entry_blocked_until
            ),
            'cooldown_remaining': (
                (state.entry_blocked_until - now).total_seconds() / 60
                if state.entry_blocked_until and now < state.entry_blocked_until
                else 0
            )
        }


# ═══════════════════════════════════════════════════════════════════════════════
# INTEGRATION HELPER: Apply all critical fixes to a trade decision
# ═══════════════════════════════════════════════════════════════════════════════

def apply_critical_fixes_to_entry(
    symbol: str,
    entry_score: float,
    score_threshold: float,
    current_rsi: float,
    current_price: float,
    atr: float,
    trades_today: int,
    min_daily_trades: int = 1,
    debouncer: Optional[ScoreDebouncer] = None
) -> dict:
    """
    Apply all critical fixes to an entry decision.
    
    This is a convenience function that runs all checks and returns
    a comprehensive result.
    
    Args:
        symbol: Stock symbol
        entry_score: Current entry score
        score_threshold: Score threshold for entry
        current_rsi: Current RSI value
        current_price: Current stock price
        atr: ATR value
        trades_today: Trades executed today
        min_daily_trades: Minimum daily trades target
        debouncer: Optional ScoreDebouncer instance
        
    Returns:
        dict with all check results and final decision
    """
    result = {
        'symbol': symbol,
        'entry_allowed': True,
        'warnings': [],
        'blocks': [],
        'adjustments': {}
    }
    
    # 1. ATR Clamping
    atr_clamped = clamp_atr(atr, current_price)
    result['adjustments']['atr'] = {
        'original': atr,
        'clamped': atr_clamped,
        'was_clamped': atr != atr_clamped
    }
    
    # 2. RSI Upper Bound
    rsi_allowed, rsi_level, rsi_reason = check_rsi_upper_bound(current_rsi)
    if not rsi_allowed:
        result['entry_allowed'] = False
        result['blocks'].append(rsi_reason)
    elif rsi_level == "CAUTION":
        result['warnings'].append(rsi_reason)
    result['rsi_check'] = {
        'allowed': rsi_allowed,
        'level': rsi_level,
        'reason': rsi_reason
    }
    
    # 3. Score Debouncing
    if debouncer:
        score_allowed, score_reason = debouncer.check_entry_allowed(
            symbol, entry_score, score_threshold
        )
        if not score_allowed:
            result['entry_allowed'] = False
            result['blocks'].append(score_reason)
        result['score_check'] = {
            'allowed': score_allowed,
            'reason': score_reason
        }
    
    # 4. Starvation Position Sizing
    pos_mult, is_starvation, starvation_reason = get_starvation_position_multiplier(
        trades_today, min_daily_trades, datetime.now()
    )
    result['adjustments']['position_multiplier'] = {
        'value': pos_mult,
        'is_starvation_mode': is_starvation,
        'reason': starvation_reason
    }
    
    # Summary
    result['summary'] = {
        'can_enter': result['entry_allowed'],
        'block_count': len(result['blocks']),
        'warning_count': len(result['warnings']),
        'position_multiplier': pos_mult,
        'atr_used': atr_clamped
    }
    
    return result


# ═══════════════════════════════════════════════════════════════════════════════
# STANDALONE TEST
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("Testing Critical Fixes Integration Module v4.1...")
    print("=" * 60)
    
    # Test 1: ATR Clamping
    print("\n1. ATR Clamping:")
    for atr, price in [(50.0, 1000.0), (1.0, 1000.0), (20.0, 1000.0)]:
        clamped = clamp_atr(atr, price)
        print(f"   ATR {atr:.1f} on ₹{price:.0f} → {clamped:.2f}")
    
    # Test 2: RSI Upper Bound
    print("\n2. RSI Upper Bound:")
    for rsi in [50, 60, 66, 72]:
        allowed, level, reason = check_rsi_upper_bound(rsi)
        print(f"   RSI {rsi}: {level} - {'✅' if allowed else '❌'}")
    
    # Test 3: Profit Floor
    print("\n3. Profit Floor:")
    for curr in [100.3, 100.6, 101.0]:
        met, pct, r, reason = check_profit_floor(curr, 100.0, 98.0)
        print(f"   Price {curr}: {'✅' if met else '❌'} ({pct:.1f}%, {r:.2f}R)")
    
    # Test 4: Starvation Position Sizing
    print("\n4. Starvation Position Sizing:")
    from datetime import datetime
    times = [
        (0, datetime(2026, 1, 22, 10, 0)),  # Before window
        (0, datetime(2026, 1, 22, 12, 0)),  # In window
        (1, datetime(2026, 1, 22, 12, 0)),  # Trades met
    ]
    for trades, time in times:
        mult, is_starv, reason = get_starvation_position_multiplier(trades, 1, time)
        print(f"   Trades={trades}, {time.strftime('%H:%M')}: {mult}x {'⚠️' if is_starv else '✅'}")
    
    # Test 5: Score Debouncing
    print("\n5. Score Debouncing:")
    debouncer = ScoreDebouncer(hysteresis_points=3, min_consecutive=2)
    scores = [48, 51, 52, 54, 55]  # Gradually rising
    for score in scores:
        allowed, reason = debouncer.check_entry_allowed('TEST', score, 50)
        print(f"   Score {score}: {'✅' if allowed else '❌'} - {reason}")
    
    # Test 6: Full Integration
    print("\n6. Full Integration Test:")
    debouncer.reset('TEST')
    result = apply_critical_fixes_to_entry(
        symbol='TEST',
        entry_score=55,
        score_threshold=50,
        current_rsi=58,
        current_price=1000,
        atr=25,
        trades_today=0,
        min_daily_trades=1,
        debouncer=debouncer
    )
    print(f"   Entry allowed: {'✅' if result['entry_allowed'] else '❌'}")
    print(f"   Blocks: {result['blocks']}")
    print(f"   Warnings: {result['warnings']}")
    print(f"   Position multiplier: {result['summary']['position_multiplier']}")
    
    print("\n" + "=" * 60)
    print("✅ Critical Fixes Integration tests complete!")
