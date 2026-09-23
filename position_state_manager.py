"""
POSITION STATE MANAGER v5.0.0
═══════════════════════════════════════════════════════════════════════════════

Extracted from orchestrator.py for modularity.
Centralized position state management with thread-safe operations.

This module handles:
- Position lifecycle (PENDING → OPEN → CLOSING → CLOSED)
- Thread-safe position state access
- Position event logging
- Price updates propagation

USAGE:
    from position_state_manager import PositionStateManager, PositionState
    
    psm = PositionStateManager(positions_lock=threading.Lock())
    
    # Add position
    psm.on_position_opened('RELIANCE', {...}, source='PHASE3')
    
    # Update price
    psm.bulk_update_prices({'RELIANCE': 2450.50})
    
    # Close position
    psm.on_position_closed('RELIANCE', reason='TARGET_HIT', exit_price=2475.0)

Author: Trading System v5.0.0
Date: 2026-02-06
"""

import logging
from datetime import datetime
from typing import Dict, List, Optional, Any, Callable
from enum import Enum
import threading

logger = logging.getLogger('PositionStateManager')


class PositionState(Enum):
    """Position lifecycle states"""
    PENDING = "PENDING"       # Order placed, not yet filled
    OPEN = "OPEN"            # Position active
    CLOSING = "CLOSING"      # Exit order placed
    CLOSED = "CLOSED"        # Fully closed


class PositionStateManager:
    """
    Centralized Position State Manager
    
    Single source of truth for position state within the orchestrator.
    All position state changes go through this manager.
    """
    
    def __init__(
        self,
        positions_lock: threading.Lock = None,
        capital_manager=None,
        phase4=None,
        phase3=None,
        phase2=None,
        telegram=None
    ):
        """
        Initialize position state manager.
        
        Args:
            positions_lock: Threading lock for thread-safe access
            capital_manager: CapitalManager instance for capital tracking
            phase4: Phase4PortfolioManager instance
            phase3: Phase3 instance
            phase2: Phase2 instance
            telegram: TelegramNotifier instance
        """
        self._positions_lock = positions_lock or threading.Lock()
        self._central_positions: Dict[str, Dict] = {}
        self._position_event_log: List[Dict] = []
        self._exited_today: Dict[str, Dict] = {}
        
        # Component references
        self.capital_manager = capital_manager
        self.phase4 = phase4
        self.phase3 = phase3
        self.phase2 = phase2
        self.telegram = telegram
        
        # Callbacks for position events
        self._on_opened_callbacks: List[Callable] = []
        self._on_closed_callbacks: List[Callable] = []
        
        logger.info("=" * 60)
        logger.info("📊 POSITION STATE MANAGER v5.0.0")
        logger.info("=" * 60)
    
    # ═══════════════════════════════════════════════════════════════════════════
    # PROPERTIES
    # ═══════════════════════════════════════════════════════════════════════════
    
    @property
    def positions(self) -> Dict[str, Dict]:
        """Get all open positions (thread-safe read)"""
        with self._positions_lock:
            return {s: p.copy() for s, p in self._central_positions.items() 
                    if p.get('state') in [PositionState.OPEN.value, 'OPEN']}
    
    @property
    def all_positions(self) -> Dict[str, Dict]:
        """Get all positions including closing (thread-safe)"""
        with self._positions_lock:
            return {s: p.copy() for s, p in self._central_positions.items()}
    
    @property
    def exited_today(self) -> Dict[str, Dict]:
        """Get symbols exited today"""
        return self._exited_today.copy()
    
    # ═══════════════════════════════════════════════════════════════════════════
    # POSITION QUERIES
    # ═══════════════════════════════════════════════════════════════════════════
    
    def get_position(self, symbol: str) -> Optional[Dict]:
        """Get single position by symbol"""
        with self._positions_lock:
            pos = self._central_positions.get(symbol)
            return pos.copy() if pos else None
    
    def has_position(self, symbol: str) -> bool:
        """Check if position exists and is OPEN"""
        with self._positions_lock:
            pos = self._central_positions.get(symbol)
            return pos is not None and pos.get('state') in [PositionState.OPEN.value, 'OPEN']
    
    def position_exists(self, symbol: str) -> bool:
        """Check if symbol has any position (including CLOSING)"""
        with self._positions_lock:
            return symbol in self._central_positions
    
    def get_open_position_count(self) -> int:
        """Get count of open positions"""
        with self._positions_lock:
            return len([p for p in self._central_positions.values() 
                       if p.get('state') in [PositionState.OPEN.value, 'OPEN']])
    
    def get_all_positions(self, include_closing: bool = False) -> Dict[str, Dict]:
        """Get positions with optional closing filter"""
        with self._positions_lock:
            if include_closing:
                return {s: p.copy() for s, p in self._central_positions.items()}
            return {s: p.copy() for s, p in self._central_positions.items() 
                    if p.get('state') in [PositionState.OPEN.value, 'OPEN']}
    
    def get_position_for_update(self, symbol: str) -> Optional[Dict]:
        """Get position reference for in-place updates (with lock held externally)"""
        return self._central_positions.get(symbol)
    
    def is_position_closing(self, symbol: str) -> bool:
        """Check if position is in CLOSING state"""
        with self._positions_lock:
            pos = self._central_positions.get(symbol)
            return pos is not None and pos.get('state') in [PositionState.CLOSING.value, 'CLOSING']
    
    def was_exited_today(self, symbol: str) -> bool:
        """Check if symbol was exited today"""
        if symbol not in self._exited_today:
            return False
        exit_date = self._exited_today[symbol].get('exit_date')
        return exit_date == datetime.now().date()
    
    # ═══════════════════════════════════════════════════════════════════════════
    # POSITION LIFECYCLE
    # ═══════════════════════════════════════════════════════════════════════════
    
    def on_position_opened(self, symbol: str, position_data: Dict, source: str = "PHASE3"):
        """
        Called when a new position is opened.
        
        Args:
            symbol: Stock symbol
            position_data: Position details (entry_price, quantity, etc.)
            source: Which component opened it (PHASE3, PHASE5, BROKER_ADOPTION)
        """
        with self._positions_lock:
            position_data['state'] = PositionState.OPEN.value
            position_data['opened_at'] = datetime.now().isoformat()
            position_data['source'] = source
            self._central_positions[symbol] = position_data
            
            # Audit log
            self._position_event_log.append({
                'event': 'OPENED',
                'symbol': symbol,
                'time': datetime.now().isoformat(),
                'source': source,
                'entry_price': position_data.get('entry_price', 0)
            })
        
        logger.info(f"📊 PSM: Position OPENED - {symbol} (source: {source})")
        
        # Notify Phase 4 to start monitoring
        if self.phase4:
            try:
                if hasattr(self.phase4, 'add_position_from_orchestrator'):
                    self.phase4.add_position_from_orchestrator(symbol, position_data)
                elif symbol not in getattr(self.phase4, 'positions', {}):
                    self.phase4.positions[symbol] = position_data
                    if hasattr(self.phase4, '_init_kalman_for_position'):
                        self.phase4._init_kalman_for_position(symbol, position_data)
            except Exception as e:
                logger.error(f"📊 PSM: Failed to notify Phase 4: {e}")
        
        # Sync Phase 2 entries counter
        if self.phase2 and hasattr(self.phase2, 'sync_entries_taken'):
            self.phase2.sync_entries_taken(self.get_open_position_count())
        
        # Fire callbacks
        for callback in self._on_opened_callbacks:
            try:
                callback(symbol, position_data, source)
            except Exception as e:
                logger.error(f"📊 PSM: Callback error on open: {e}")
    
    def on_position_closing(self, symbol: str, reason: str = "UNKNOWN"):
        """
        Called when exit is initiated (order placed, not yet filled).
        
        Args:
            symbol: Stock symbol
            reason: Why closing (TCAS_ALIM, STOP_LOSS, TARGET, etc.)
        """
        with self._positions_lock:
            if symbol in self._central_positions:
                self._central_positions[symbol]['state'] = PositionState.CLOSING.value
                self._central_positions[symbol]['closing_reason'] = reason
                self._central_positions[symbol]['closing_at'] = datetime.now().isoformat()
                
                self._position_event_log.append({
                    'event': 'CLOSING',
                    'symbol': symbol,
                    'time': datetime.now().isoformat(),
                    'reason': reason
                })
        
        logger.info(f"📊 PSM: Position CLOSING - {symbol} (reason: {reason})")
    
    def on_position_closed(self, symbol: str, reason: str = "UNKNOWN", exit_price: float = 0):
        """
        Called when position is fully closed (exit filled).
        
        Args:
            symbol: Stock symbol
            reason: Why closed
            exit_price: Exit price (for P&L calculation)
        """
        now = datetime.now()
        
        with self._positions_lock:
            if symbol in self._central_positions:
                position = self._central_positions[symbol]
                entry_price = position.get('entry_price', 0)
                quantity = position.get('quantity', 0)
                entry_value = position.get('entry_value', entry_price * quantity)
                
                # Calculate P&L
                if exit_price > 0 and entry_price > 0:
                    direction = position.get('direction', 'LONG')
                    if direction == 'LONG':
                        pnl = (exit_price - entry_price) * quantity
                    else:
                        pnl = (entry_price - exit_price) * quantity
                    pnl_pct = ((exit_price - entry_price) / entry_price * 100) if entry_price > 0 else 0
                else:
                    pnl = 0
                    pnl_pct = 0
                
                # Audit log
                self._position_event_log.append({
                    'event': 'CLOSED',
                    'symbol': symbol,
                    'time': now.isoformat(),
                    'reason': reason,
                    'exit_price': exit_price,
                    'entry_price': entry_price,
                    'pnl': pnl,
                    'pnl_pct': pnl_pct
                })
                
                # Track exit to prevent re-adoption
                self._exited_today[symbol] = {
                    'exit_time': now,
                    'exit_date': now.date(),
                    'reason': reason,
                    'exit_price': exit_price,
                    'pnl': pnl
                }
                
                # Remove from central positions
                del self._central_positions[symbol]
                
                logger.info(f"📊 PSM: Position CLOSED - {symbol} (reason: {reason}, P&L: ₹{pnl:.2f})")
                
                # Release capital
                if self.capital_manager and entry_value > 0:
                    try:
                        self.capital_manager.release(symbol, entry_value, pnl=pnl)
                    except Exception as e:
                        logger.error(f"📊 PSM: Capital release failed for {symbol}: {e}")
        
        # Clean up Phase 4
        if self.phase4 and hasattr(self.phase4, 'positions'):
            if symbol in self.phase4.positions:
                del self.phase4.positions[symbol]
            if hasattr(self.phase4, 'kalman_filters') and symbol in self.phase4.kalman_filters:
                del self.phase4.kalman_filters[symbol]
        
        # Clean up Phase 3
        if self.phase3 and hasattr(self.phase3, 'positions'):
            if symbol in self.phase3.positions:
                del self.phase3.positions[symbol]
        
        # Fire callbacks
        for callback in self._on_closed_callbacks:
            try:
                callback(symbol, reason, exit_price)
            except Exception as e:
                logger.error(f"📊 PSM: Callback error on close: {e}")
    
    # ═══════════════════════════════════════════════════════════════════════════
    # POSITION MODIFICATIONS
    # ═══════════════════════════════════════════════════════════════════════════
    
    def add_position(self, symbol: str, position_data: Dict, source: str = "PHASE3") -> bool:
        """
        Add a new position.
        
        Args:
            symbol: Stock symbol
            position_data: Position details
            source: Origin of position
            
        Returns:
            True if added successfully
        """
        with self._positions_lock:
            if symbol in self._central_positions:
                logger.warning(f"📊 PSM: Position {symbol} already exists - not adding")
                return False
            
            self._central_positions[symbol] = position_data
        
        self.on_position_opened(symbol, position_data, source)
        return True
    
    def remove_position(self, symbol: str, reason: str = "UNKNOWN", exit_price: float = 0) -> bool:
        """
        Remove a position.
        
        Args:
            symbol: Stock symbol
            reason: Why removing
            exit_price: Exit price for P&L
            
        Returns:
            True if removed
        """
        if not self.position_exists(symbol):
            logger.debug(f"📊 PSM: Cannot remove {symbol} - not found")
            return False
        
        self.on_position_closed(symbol, reason, exit_price)
        return True
    
    def update_position(self, symbol: str, updates: Dict) -> bool:
        """
        Update position fields.
        
        Args:
            symbol: Stock symbol
            updates: Dict of fields to update
            
        Returns:
            True if updated
        """
        with self._positions_lock:
            if symbol not in self._central_positions:
                return False
            
            self._central_positions[symbol].update(updates)
            self._central_positions[symbol]['last_updated'] = datetime.now().isoformat()
            return True
    
    def transition_position_state(self, symbol: str, new_state: str, reason: str = "") -> bool:
        """
        Transition position to new state.
        
        Args:
            symbol: Stock symbol
            new_state: Target state
            reason: Reason for transition
            
        Returns:
            True if transitioned
        """
        with self._positions_lock:
            if symbol not in self._central_positions:
                logger.warning(f"📊 PSM: Cannot transition {symbol} - not found")
                return False
            
            old_state = self._central_positions[symbol].get('state', 'UNKNOWN')
            self._central_positions[symbol]['state'] = new_state
            self._central_positions[symbol]['state_changed_at'] = datetime.now().isoformat()
            
            if reason:
                self._central_positions[symbol]['state_change_reason'] = reason
            
            self._position_event_log.append({
                'event': 'STATE_TRANSITION',
                'symbol': symbol,
                'time': datetime.now().isoformat(),
                'old_state': old_state,
                'new_state': new_state,
                'reason': reason
            })
            
            logger.info(f"📊 PSM: {symbol} state: {old_state} → {new_state}")
            return True
    
    def bulk_update_prices(self, price_updates: Dict[str, float]) -> int:
        """
        Update prices for multiple positions.
        
        Args:
            price_updates: Dict mapping symbol to last price
            
        Returns:
            Number of positions updated
        """
        updated = 0
        with self._positions_lock:
            for symbol, price in price_updates.items():
                if symbol in self._central_positions:
                    pos = self._central_positions[symbol]
                    pos['last_price'] = price
                    pos['price_updated_at'] = datetime.now().isoformat()
                    
                    # Calculate unrealized P&L
                    entry_price = pos.get('entry_price', 0)
                    quantity = pos.get('quantity', 0)
                    direction = pos.get('direction', 'LONG')
                    
                    if entry_price > 0:
                        if direction == 'LONG':
                            pos['unrealized_pnl'] = (price - entry_price) * quantity
                        else:
                            pos['unrealized_pnl'] = (entry_price - price) * quantity
                        pos['unrealized_pnl_pct'] = ((price - entry_price) / entry_price * 100)
                    
                    updated += 1
        
        return updated
    
    # ═══════════════════════════════════════════════════════════════════════════
    # EVENT LOG
    # ═══════════════════════════════════════════════════════════════════════════
    
    def get_position_event_log(self, limit: int = 50) -> List[Dict]:
        """Get recent position events for audit"""
        return self._position_event_log[-limit:]
    
    def clear_stale_exit_tracking(self):
        """Clear exit tracking for previous trading days"""
        today = datetime.now().date()
        stale = [s for s, info in self._exited_today.items() 
                if info.get('exit_date') != today]
        for symbol in stale:
            del self._exited_today[symbol]
        if stale:
            logger.info(f"📊 PSM: Cleared {len(stale)} stale exit entries")
    
    # ═══════════════════════════════════════════════════════════════════════════
    # CALLBACKS
    # ═══════════════════════════════════════════════════════════════════════════
    
    def register_on_opened(self, callback: Callable):
        """Register callback for position opened events"""
        self._on_opened_callbacks.append(callback)
    
    def register_on_closed(self, callback: Callable):
        """Register callback for position closed events"""
        self._on_closed_callbacks.append(callback)
    
    # ═══════════════════════════════════════════════════════════════════════════
    # COMPONENT SETTERS
    # ═══════════════════════════════════════════════════════════════════════════
    
    def set_capital_manager(self, capital_manager):
        """Set capital manager reference"""
        self.capital_manager = capital_manager
    
    def set_phase4(self, phase4):
        """Set Phase 4 reference"""
        self.phase4 = phase4
    
    def set_phase3(self, phase3):
        """Set Phase 3 reference"""
        self.phase3 = phase3
    
    def set_phase2(self, phase2):
        """Set Phase 2 reference"""
        self.phase2 = phase2
    
    def set_telegram(self, telegram):
        """Set Telegram reference"""
        self.telegram = telegram
    
    # ═══════════════════════════════════════════════════════════════════════════
    # STATUS
    # ═══════════════════════════════════════════════════════════════════════════
    
    def get_status_summary(self) -> Dict:
        """Get summary status for monitoring"""
        with self._positions_lock:
            open_count = len([p for p in self._central_positions.values() 
                            if p.get('state') in [PositionState.OPEN.value, 'OPEN']])
            closing_count = len([p for p in self._central_positions.values() 
                               if p.get('state') in [PositionState.CLOSING.value, 'CLOSING']])
            
            total_pnl = sum(p.get('unrealized_pnl', 0) for p in self._central_positions.values())
            
            return {
                'open_positions': open_count,
                'closing_positions': closing_count,
                'total_unrealized_pnl': total_pnl,
                'exited_today_count': len(self._exited_today),
                'event_log_size': len(self._position_event_log)
            }
