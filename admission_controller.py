"""
ADMISSION CONTROLLER v1.0 - CAPITAL & POSITION GATES
═══════════════════════════════════════════════════════════════════════════════

PURPOSE:
Prevents over-trading and capital over-deployment through hard gates.
All gates must pass before Phase 2 can enter a new position.

IMPLEMENTS:
✅ CONDITION 2: Recovery positions counted as ACTIVE for capital limits
✅ INVARIANT 2: Capital accounting includes recovery positions

Author: Trading System v3.4.0
Date: 2026-01-25
"""

import logging
from datetime import datetime, time as dt_time
from typing import Dict, Optional, Tuple

logger = logging.getLogger('AdmissionController')


class AdmissionController:
    """
    Hard gates for new position entries.
    
    All gates must pass. If any gate fails, entry is REJECTED.
    
    Gates:
    1. Position count limit
    2. Capital availability (INCLUDES recovery positions - CONDITION 2)
    3. Symbol not in recovery
    4. No duplicate position
    5. Market hours check
    """
    
    def __init__(self, config, phase3_manager=None, recovery_manager=None):
        """
        Initialize admission controller.
        
        Args:
            config: System configuration
            phase3_manager: Phase 3 position manager (optional, can be set later)
            recovery_manager: Recovery manager (optional, can be set later)
        """
        self.config = config
        self.phase3 = phase3_manager
        self.recovery = recovery_manager
        
        # Configuration
        self.max_positions = getattr(config, 'MAX_ACTIVE_POSITIONS', 3)
        self.max_capital = getattr(config, 'MAX_CAPITAL_DEPLOYED', 50000)
        self.max_capital_pct = getattr(config, 'MAX_CAPITAL_PCT', 0.9)
        
        # Market hours
        self.market_open = dt_time(9, 15)
        self.market_close = dt_time(15, 30)
        
        logger.info("=" * 80)
        logger.info("🔒 ADMISSION CONTROLLER v1.0")
        logger.info("=" * 80)
        logger.info("")
        logger.info("Configuration:")
        logger.info(f"  Max Positions: {self.max_positions}")
        logger.info(f"  Max Capital: ₹{self.max_capital:,.0f}")
        logger.info(f"  Max Capital %: {self.max_capital_pct * 100:.0f}%")
        logger.info("")
        logger.info("✅ CONDITION 2: Recovery positions count in capital limits")
        logger.info("")
    
    
    def set_phase3_manager(self, phase3_manager):
        """Set Phase 3 manager reference (if not provided at init)"""
        self.phase3 = phase3_manager
    
    
    def set_recovery_manager(self, recovery_manager):
        """Set recovery manager reference (if not provided at init)"""
        self.recovery = recovery_manager
    
    
    def check_admission(self, symbol: str, capital_required: float, 
                       reason: str = "") -> Tuple[bool, str]:
        """
        Check if new position entry is allowed.
        
        ALL gates must pass. If any fails, entry is rejected.
        
        Args:
            symbol: Stock symbol
            capital_required: Capital needed for this trade
            reason: Optional reason for entry (for logging)
            
        Returns:
            (approved: bool, rejection_reason: str)
            If approved=True, rejection_reason is empty
            If approved=False, rejection_reason explains which gate failed
        """
        logger.info("=" * 80)
        logger.info(f"🔒 ADMISSION CHECK: {symbol}")
        logger.info("=" * 80)
        logger.info(f"   Capital Required: ₹{capital_required:,.2f}")
        if reason:
            logger.info(f"   Reason: {reason}")
        logger.info("")
        
        # ═══════════════════════════════════════════════════════════════════
        # GATE 1: Position Count Limit
        # ═══════════════════════════════════════════════════════════════════
        
        position_count = self._count_positions()
        logger.info(f"   Gate 1: Position Count ({position_count}/{self.max_positions})")
        
        if position_count >= self.max_positions:
            reason = f"Max positions reached ({position_count}/{self.max_positions})"
            logger.warning(f"   ❌ GATE 1 FAILED: {reason}")
            logger.info("=" * 80)
            logger.info("")
            return False, reason
        
        logger.info(f"   ✅ GATE 1 PASSED")
        
        # ═══════════════════════════════════════════════════════════════════
        # GATE 2: Capital Availability (CONDITION 2 - includes recovery!)
        # ═══════════════════════════════════════════════════════════════════
        
        deployed_capital = self._get_deployed_capital()
        available_capital = self.max_capital - deployed_capital
        
        logger.info(f"   Gate 2: Capital Availability")
        logger.info(f"      Deployed: ₹{deployed_capital:,.2f}")
        logger.info(f"      Available: ₹{available_capital:,.2f}")
        logger.info(f"      Required: ₹{capital_required:,.2f}")
        
        if deployed_capital + capital_required > self.max_capital:
            reason = f"Capital limit exceeded (need ₹{capital_required:,.2f}, available ₹{available_capital:,.2f})"
            logger.warning(f"   ❌ GATE 2 FAILED: {reason}")
            logger.info("=" * 80)
            logger.info("")
            return False, reason
        
        logger.info(f"   ✅ GATE 2 PASSED")
        
        # ═══════════════════════════════════════════════════════════════════
        # GATE 3: Symbol Not In Recovery
        # ═══════════════════════════════════════════════════════════════════
        
        logger.info(f"   Gate 3: Recovery Check")
        
        if self._is_symbol_in_recovery(symbol):
            reason = f"{symbol} currently in recovery state"
            logger.warning(f"   ❌ GATE 3 FAILED: {reason}")
            logger.info("=" * 80)
            logger.info("")
            return False, reason
        
        logger.info(f"   ✅ GATE 3 PASSED")
        
        # ═══════════════════════════════════════════════════════════════════
        # GATE 4: No Duplicate Position
        # ═══════════════════════════════════════════════════════════════════
        
        logger.info(f"   Gate 4: Duplicate Check")
        
        if self._has_active_position(symbol):
            reason = f"{symbol} already has active position"
            logger.warning(f"   ❌ GATE 4 FAILED: {reason}")
            logger.info("=" * 80)
            logger.info("")
            return False, reason
        
        logger.info(f"   ✅ GATE 4 PASSED")
        
        # ═══════════════════════════════════════════════════════════════════
        # GATE 5: Market Hours
        # ═══════════════════════════════════════════════════════════════════
        
        logger.info(f"   Gate 5: Market Hours")
        
        if not self._is_market_hours():
            current_time = datetime.now().time()
            reason = f"Outside market hours (current: {current_time}, market: {self.market_open}-{self.market_close})"
            logger.warning(f"   ❌ GATE 5 FAILED: {reason}")
            logger.info("=" * 80)
            logger.info("")
            return False, reason
        
        logger.info(f"   ✅ GATE 5 PASSED")
        
        # ═══════════════════════════════════════════════════════════════════
        # ALL GATES PASSED
        # ═══════════════════════════════════════════════════════════════════
        
        logger.info("")
        logger.info(f"✅ ADMISSION APPROVED: {symbol}")
        logger.info(f"   Capital: ₹{capital_required:,.2f}")
        logger.info(f"   New Position Count: {position_count + 1}/{self.max_positions}")
        logger.info(f"   New Deployed Capital: ₹{deployed_capital + capital_required:,.2f}/{self.max_capital:,.2f}")
        logger.info("=" * 80)
        logger.info("")
        
        return True, ""
    
    
    def _count_positions(self) -> int:
        """
        Count total active positions.
        
        Includes:
        - Phase 3 active positions
        - Recovery positions
        
        Returns:
            Total position count
        """
        count = 0
        
        # Count Phase 3 active positions
        if self.phase3 and hasattr(self.phase3, 'active_positions'):
            if isinstance(self.phase3.active_positions, dict):
                count += len(self.phase3.active_positions)
            elif isinstance(self.phase3.active_positions, list):
                count += len(self.phase3.active_positions)
        
        # Count recovery positions
        if self.recovery and hasattr(self.recovery, 'recovery_positions'):
            if isinstance(self.recovery.recovery_positions, dict):
                count += len(self.recovery.recovery_positions)
        
        return count
    
    
    def _get_deployed_capital(self) -> float:
        """
        Calculate total deployed capital.
        
        CRITICAL - IMPLEMENTS CONDITION 2:
        Recovery positions MUST be counted in capital limits.
        
        Returns:
            Total capital deployed (active + recovery)
        """
        total = 0.0
        
        # ═══════════════════════════════════════════════════════════════════
        # Active Positions (Phase 3)
        # ═══════════════════════════════════════════════════════════════════
        
        if self.phase3 and hasattr(self.phase3, 'active_positions'):
            positions = self.phase3.active_positions
            
            if isinstance(positions, dict):
                for symbol, pos in positions.items():
                    # Try different field names for capital
                    capital = (pos.get('capital_deployed', 0) or 
                             pos.get('capital', 0) or 
                             pos.get('buy_value', 0) or
                             (pos.get('quantity', 0) * pos.get('entry_price', 0)))
                    total += capital
            
            elif isinstance(positions, list):
                for pos in positions:
                    capital = (pos.get('capital_deployed', 0) or 
                             pos.get('capital', 0) or 
                             pos.get('buy_value', 0) or
                             (pos.get('quantity', 0) * pos.get('entry_price', 0)))
                    total += capital
        
        # ═══════════════════════════════════════════════════════════════════
        # Recovery Positions (CRITICAL - CONDITION 2)
        # ═══════════════════════════════════════════════════════════════════
        # Recovery positions MUST count as active for capital limits.
        # Even if priority is reduced or timeout exceeded, capital is locked.
        # ═══════════════════════════════════════════════════════════════════
        
        if self.recovery and hasattr(self.recovery, 'recovery_positions'):
            positions = self.recovery.recovery_positions
            
            if isinstance(positions, dict):
                for symbol, pos in positions.items():
                    # Recovery position structure
                    capital = (pos.get('capital_deployed', 0) or
                             pos.get('capital', 0) or
                             self._calculate_capital_from_position(pos.get('position_data', {})))
                    total += capital
        
        return total
    
    
    def _calculate_capital_from_position(self, position_data: dict) -> float:
        """Calculate capital from raw position data"""
        if not position_data:
            return 0.0
        
        # Try multiple methods
        capital = (position_data.get('buy_value', 0) or
                  (abs(position_data.get('quantity', 0)) * 
                   position_data.get('average_price', 0)))
        
        return capital
    
    
    def _is_symbol_in_recovery(self, symbol: str) -> bool:
        """
        Check if symbol is currently in recovery.
        
        FAULT #1 FIX: Also checks pending SL placements.
        """
        if not self.recovery or not hasattr(self.recovery, 'recovery_positions'):
            return False
        
        # Check recovery positions
        positions = self.recovery.recovery_positions
        
        if isinstance(positions, dict):
            if symbol in positions:
                return True
        
        # FAULT #1 FIX: Check pending SL placements
        if hasattr(self.recovery, 'pending_sl_symbols'):
            if symbol in self.recovery.pending_sl_symbols:
                return True
        
        return False
    
    
    def _has_active_position(self, symbol: str) -> bool:
        """Check if symbol has active position in Phase 3"""
        if not self.phase3 or not hasattr(self.phase3, 'active_positions'):
            return False
        
        positions = self.phase3.active_positions
        
        if isinstance(positions, dict):
            return symbol in positions
        
        elif isinstance(positions, list):
            return any(pos.get('symbol') == symbol for pos in positions)
        
        return False
    
    
    def _is_market_hours(self) -> bool:
        """Check if current time is within market hours"""
        current_time = datetime.now().time()
        return self.market_open <= current_time <= self.market_close
    
    
    def get_admission_status(self) -> Dict:
        """
        Get current admission control status (for monitoring/debugging).
        
        Returns:
            Dictionary with current limits and usage
        """
        position_count = self._count_positions()
        deployed_capital = self._get_deployed_capital()
        available_capital = self.max_capital - deployed_capital
        
        return {
            'positions': {
                'current': position_count,
                'max': self.max_positions,
                'available': self.max_positions - position_count
            },
            'capital': {
                'deployed': deployed_capital,
                'max': self.max_capital,
                'available': available_capital,
                'utilization_pct': (deployed_capital / self.max_capital * 100) if self.max_capital > 0 else 0
            },
            'market_hours': self._is_market_hours(),
            'timestamp': datetime.now()
        }
