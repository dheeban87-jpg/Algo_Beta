"""
BROKER SYNC HANDLER v5.0.0 - SSOT Broker Synchronization
═══════════════════════════════════════════════════════════════════════════════

Extracted from orchestrator.py for modularity.
Handles all broker position synchronization with SSOT architecture.

v5.0.0 FEATURES:
- Semantic separation: MIS/NRML positions vs CNC holdings
- CNC holdings get OBSERVE_ONLY mode (no exits, no capital tracking)
- MIS/NRML positions get ACTIVE_CONTROL mode (full management)
- Uses CapitalManager as Single Source of Truth

USAGE:
    from broker_sync_handler import BrokerSyncHandler
    
    handler = BrokerSyncHandler(kite, capital_manager, position_manager)
    handler.sync()  # Call every 30 seconds

Author: Trading System v5.0.0
Date: 2026-02-06
"""

import logging
from datetime import datetime
from typing import Dict, List, Optional, Any
from enum import Enum

logger = logging.getLogger('BrokerSyncHandler')


class ProductType(Enum):
    """Trading product types"""
    MIS = "MIS"
    NRML = "NRML"
    CNC = "CNC"


class Phase4Mode(Enum):
    """Phase 4 monitoring modes"""
    ACTIVE_CONTROL = "ACTIVE_CONTROL"
    OBSERVE_ONLY = "OBSERVE_ONLY"


class BrokerSyncHandler:
    """
    v5.0.0: SSOT-aware Broker Synchronization Handler
    
    Key Principle: SEMANTIC SEPARATION
    - MIS/NRML -> deployed_positions -> ACTIVE_CONTROL
    - CNC -> cnc_holdings -> OBSERVE_ONLY
    """
    
    def __init__(
        self,
        kite,
        capital_manager,
        position_manager=None,
        phase4=None,
        phase3=None,
        telegram=None,
        broker_sync_manager=None,
        tier3_tracker=None  # v8.0.0: Phase 8 Tier 3 reference (for CNC skip guards)
    ):
        self.kite = kite
        self.capital_manager = capital_manager
        self.position_manager = position_manager
        self.phase4 = phase4
        self.phase3 = phase3
        self.telegram = telegram
        self.broker_sync = broker_sync_manager
        self.tier3_tracker = tier3_tracker  # v8.0.0: Phase 8
        
        self.last_sync_time = datetime.min
        self.sync_interval_seconds = 30
        self.sync_count = 0
        
        self.ssot_available = self._check_ssot_support()
        
        logger.info("=" * 60)
        logger.info("BROKER SYNC HANDLER v5.0.0 - SSOT")
        logger.info("=" * 60)
        logger.info(f"   SSOT Mode: {'ENABLED' if self.ssot_available else 'LEGACY'}")
        logger.info("=" * 60)
    
    def _check_ssot_support(self) -> bool:
        if not self.capital_manager:
            return False
        return (hasattr(self.capital_manager, 'add_holding') and
                hasattr(self.capital_manager, 'adopt_position') and
                hasattr(self.capital_manager, 'is_deployed'))
    
    def should_sync(self) -> bool:
        elapsed = (datetime.now() - self.last_sync_time).total_seconds()
        return elapsed >= self.sync_interval_seconds
    
    def sync(self) -> Dict:
        if not self.should_sync():
            return {'skipped': True}
        
        self.last_sync_time = datetime.now()
        self.sync_count += 1
        
        try:
            if self.ssot_available and self.broker_sync:
                if hasattr(self.broker_sync, 'reconcile_with_capital_manager'):
                    result = self.broker_sync.reconcile_with_capital_manager(self.capital_manager)
                    return self._handle_ssot_result(result)
            
            return self._sync_legacy()
            
        except Exception as e:
            logger.error(f"Broker sync failed: {e}")
            return {'error': str(e)}
    
    def _handle_ssot_result(self, result) -> Dict:
        now = datetime.now()
        stats = {'new_mis': 0, 'closed_mis': 0, 'new_cnc': 0, 'closed_cnc': 0}
        
        exited_today = {}
        if self.position_manager:
            exited_today = self.position_manager.exited_today
        
        # NEW MIS -> ACTIVE_CONTROL
        for symbol, pos in result.new_mis_positions.items():
            if self._should_skip_adoption(symbol, now, exited_today):
                continue
            
            logger.warning(f"SSOT: NEW MIS {symbol} - ADOPTING")
            self._adopt_mis_position(symbol, pos, now)
            stats['new_mis'] += 1
        
        # NEW CNC -> OBSERVE_ONLY
        for symbol, hold in result.new_cnc_holdings.items():
            if self._should_skip_adoption(symbol, now, exited_today):
                continue
            
            logger.info(f"SSOT: NEW CNC {symbol} - OBSERVE_ONLY")
            self._adopt_cnc_holding(symbol, hold)
            stats['new_cnc'] += 1
        
        # CLOSED MIS
        for symbol in result.closed_mis_positions:
            logger.warning(f"SSOT: MIS {symbol} CLOSED externally")
            self._handle_closed_mis(symbol, now)
            stats['closed_mis'] += 1
        
        # CLOSED CNC
        for symbol in result.closed_cnc_holdings:
            logger.info(f"SSOT: CNC {symbol} removed")
            self._handle_closed_cnc(symbol, now)
            stats['closed_cnc'] += 1
        
        if result.has_changes():
            logger.info(f"SSOT Sync #{self.sync_count}: {result.summary()}")
        
        return stats
    
    def _should_skip_adoption(self, symbol: str, now: datetime, exited_today: Dict) -> bool:
        if symbol in exited_today:
            exit_info = exited_today[symbol]
            if exit_info.get('exit_date') == now.date():
                logger.info(f"{symbol} at broker but EXITED TODAY - skipping")
                return True
        
        if self.phase4 and hasattr(self.phase4, 'is_reentry_allowed'):
            allowed, reason = self.phase4.is_reentry_allowed(symbol)
            if not allowed:
                logger.info(f"{symbol} re-entry blocked: {reason}")
                return True
        
        return False
    
    def _adopt_mis_position(self, symbol: str, pos, now: datetime):
        margin_rate = 0.20 if pos.product == 'MIS' else 1.0
        margin_amount = pos.quantity * pos.average_price * margin_rate
        entry_value = pos.quantity * pos.average_price
        
        if hasattr(self.capital_manager, 'adopt_position'):
            self.capital_manager.adopt_position(
                symbol=symbol,
                amount=margin_amount,
                quantity=pos.quantity,
                avg_price=pos.average_price,
                product=pos.product
            )
        
        position_data = {
            'symbol': symbol,
            'quantity': pos.quantity,
            'entry_price': pos.average_price,
            'entry_value': entry_value,
            'product': pos.product,
            'source': 'BROKER_ADOPTION',
            'phase4_mode': Phase4Mode.ACTIVE_CONTROL.value
        }
        
        if self.position_manager:
            self.position_manager.on_position_opened(symbol, position_data, 'BROKER_ADOPTION')
        
        # Add to Phase 4 for monitoring (use _add_manual_position which exists)
        if self.phase4:
            try:
                broker_pos = {
                    'average_price': pos.average_price,
                    'quantity': pos.quantity,
                    'product': pos.product,
                    'last_price': pos.average_price,
                    'pnl': 0,
                    'source': 'BROKER_ADOPTED',
                    'direction': 'LONG' if pos.quantity > 0 else 'SHORT'
                }
                if hasattr(self.phase4, '_add_manual_position'):
                    self.phase4._add_manual_position(symbol, broker_pos)
                    logger.info(f"Phase 4: Added {symbol} via _add_manual_position")
            except Exception as e:
                logger.error(f"Phase 4 add failed for {symbol}: {e}")
        
        if self.telegram:
            self.telegram.send_message(f"MIS ADOPTED: {symbol} (ACTIVE_CONTROL)")
    
    def _adopt_cnc_holding(self, symbol: str, hold):
        # v8.0.0: Skip CNC positions managed by Phase 8 Tier 3
        if self.tier3_tracker and hasattr(self.tier3_tracker, 'get_tier3_held_symbols'):
            try:
                if symbol in self.tier3_tracker.get_tier3_held_symbols():
                    logger.info(f"SSOT: CNC {symbol} managed by PH8 Tier 3 — skipping OBSERVE_ONLY adoption")
                    return
            except Exception:
                pass  # If tier3 query fails, proceed with normal adoption

        if hasattr(self.capital_manager, 'add_holding'):
            self.capital_manager.add_holding(
                symbol=symbol,
                quantity=hold.quantity,
                avg_price=hold.average_price,
                quantity_settled=getattr(hold, 'quantity_settled', hold.quantity),
                quantity_t1=getattr(hold, 'quantity_t1', 0)
            )
        
        if self.phase4 and hasattr(self.phase4, 'add_holding_monitor'):
            self.phase4.add_holding_monitor(
                symbol=symbol,
                quantity=hold.quantity,
                avg_price=hold.average_price,
                phase4_mode='OBSERVE_ONLY'
            )
        
        t1 = getattr(hold, 'quantity_t1', 0)
        t1_note = f" ({t1} T+1)" if t1 > 0 else ""
        if self.telegram:
            self.telegram.send_message(f"CNC HOLDING: {symbol}{t1_note} (OBSERVE_ONLY)")
    
    def _handle_closed_mis(self, symbol: str, now: datetime):
        if self.position_manager and self.position_manager.position_exists(symbol):
            self.position_manager.on_position_closed(symbol, reason='EXTERNAL_CLOSE', exit_price=0)
        else:
            if hasattr(self.capital_manager, 'is_deployed'):
                if self.capital_manager.is_deployed(symbol):
                    pos_record = self.capital_manager.get_position_record(symbol)
                    if pos_record:
                        self.capital_manager.release(symbol, pos_record.deployed_amount, pnl=0)
        
        # v5.3.2 FIX: Also clean Phase 4 directly (position_manager.on_position_closed
        # should do this, but belt-and-suspenders for when position_manager doesn't have it)
        if self.phase4:
            if symbol in self.phase4.positions:
                del self.phase4.positions[symbol]
                logger.info(f"   ✅ Cleaned {symbol} from Phase 4 positions")
            if hasattr(self.phase4, 'kalman_filters') and symbol in self.phase4.kalman_filters:
                del self.phase4.kalman_filters[symbol]
            if hasattr(self.phase4, '_closed_externally_today'):
                self.phase4._closed_externally_today.add(symbol)
        
        if self.telegram:
            self.telegram.send_message(f"MIS CLOSED: {symbol}")
    
    def _handle_closed_cnc(self, symbol: str, now: datetime):
        # v8.0.0: Notify Tier 3 if Ph8 position closed externally at broker
        if self.tier3_tracker and hasattr(self.tier3_tracker, 'get_tier3_held_symbols'):
            try:
                if symbol in self.tier3_tracker.get_tier3_held_symbols():
                    logger.warning(f"SSOT: PH8 Tier 3 position {symbol} closed externally at broker!")
                    # Tier 3 exit is handled by Phase 4 monitoring — just log the external close
                    return
            except Exception:
                pass  # If tier3 query fails, proceed with normal close handling

        if hasattr(self.capital_manager, 'remove_holding'):
            self.capital_manager.remove_holding(symbol)
        
        if self.phase4 and hasattr(self.phase4, 'holding_monitors'):
            if symbol in self.phase4.holding_monitors:
                del self.phase4.holding_monitors[symbol]
        
        # v5.3.2 FIX: Also clean Phase 4 positions (CNC positions adopted at startup
        # go into phase4.positions, not holding_monitors)
        if self.phase4:
            if symbol in self.phase4.positions:
                del self.phase4.positions[symbol]
                logger.info(f"   ✅ Cleaned {symbol} from Phase 4 positions (CNC)")
            if hasattr(self.phase4, 'kalman_filters') and symbol in self.phase4.kalman_filters:
                del self.phase4.kalman_filters[symbol]
            if hasattr(self.phase4, '_closed_externally_today'):
                self.phase4._closed_externally_today.add(symbol)
    
    def _sync_legacy(self) -> Dict:
        """Legacy sync for non-SSOT systems"""
        now = datetime.now()
        broker_positions = {}
        stats = {'adopted': 0, 'closed': 0}
        
        try:
            positions_response = self.kite.positions()
            for pos in positions_response.get('net', []):
                qty = pos.get('quantity', 0)
                if qty != 0:
                    symbol = pos['tradingsymbol']
                    broker_positions[symbol] = {
                        'quantity': abs(qty),
                        'avg_price': pos.get('average_price', 0),
                        'product': pos.get('product', 'MIS'),
                        'source': 'positions'
                    }
            
            holdings = self.kite.holdings()
            for holding in holdings:
                qty = holding.get('quantity', 0)
                t1_qty = holding.get('t1_quantity', 0)
                total_qty = qty + t1_qty
                if total_qty > 0:
                    symbol = holding['tradingsymbol']
                    broker_positions[symbol] = {
                        'quantity': total_qty,
                        'avg_price': holding.get('average_price', 0),
                        'product': 'CNC',
                        'source': 'holdings'
                    }
            
            our_positions = set()
            exited_today = {}
            if self.position_manager:
                our_positions = set(self.position_manager.all_positions.keys())
                exited_today = self.position_manager.exited_today
            
            broker_symbols = set(broker_positions.keys())
            
            for symbol in (broker_symbols - our_positions):
                broker_data = broker_positions[symbol]
                
                if self._should_skip_adoption(symbol, now, exited_today):
                    continue
                
                product = broker_data.get('product', 'MIS')
                
                if product == 'CNC' and self.ssot_available:
                    logger.info(f"BROKER SYNC: {symbol} CNC - OBSERVE_ONLY")
                    if hasattr(self.capital_manager, 'add_holding'):
                        self.capital_manager.add_holding(
                            symbol=symbol,
                            quantity=broker_data['quantity'],
                            avg_price=broker_data['avg_price']
                        )
                    if self.phase4 and hasattr(self.phase4, 'add_holding_monitor'):
                        self.phase4.add_holding_monitor(
                            symbol=symbol,
                            quantity=broker_data['quantity'],
                            avg_price=broker_data['avg_price'],
                            phase4_mode='OBSERVE_ONLY'
                        )
                else:
                    logger.warning(f"BROKER SYNC: {symbol} - ADOPTING")
                    
                    entry_value = broker_data['avg_price'] * broker_data['quantity']
                    
                    if self.capital_manager:
                        if hasattr(self.capital_manager, 'adopt_position'):
                            self.capital_manager.adopt_position(
                                symbol=symbol,
                                amount=entry_value * 0.20,
                                quantity=broker_data['quantity'],
                                avg_price=broker_data['avg_price'],
                                product=product
                            )
                        elif hasattr(self.capital_manager, 'adopt_deployed_capital'):
                            self.capital_manager.adopt_deployed_capital(
                                symbol=symbol,
                                amount=entry_value,
                                quantity=broker_data['quantity'],
                                avg_price=broker_data['avg_price']
                            )
                    
                    position_data = {
                        'symbol': symbol,
                        'quantity': broker_data['quantity'],
                        'entry_price': broker_data['avg_price'],
                        'entry_value': entry_value,
                        'product': product,
                        'source': 'BROKER_ADOPTION'
                    }
                    
                    if self.position_manager:
                        self.position_manager.on_position_opened(symbol, position_data, 'BROKER_ADOPTION')
                    
                    stats['adopted'] += 1
                
                if self.telegram:
                    mode = "OBSERVE_ONLY" if product == 'CNC' else "ACTIVE_CONTROL"
                    self.telegram.send_message(f"ADOPTED: {symbol} ({mode})")
            
            for symbol in (our_positions - broker_symbols):
                if self.position_manager:
                    if not self.position_manager.is_position_closing(symbol):
                        logger.warning(f"BROKER SYNC: {symbol} CLOSED externally")
                        self.position_manager.on_position_closed(symbol, 'EXTERNAL_CLOSE', 0)
                        stats['closed'] += 1
            
            logger.debug(f"Legacy sync complete: {len(broker_positions)} positions")
            
        except Exception as e:
            logger.error(f"Legacy sync failed: {e}")
            stats['error'] = str(e)
        
        return stats
    
    def get_sync_stats(self) -> Dict:
        return {
            'last_sync_time': self.last_sync_time.isoformat() if self.last_sync_time != datetime.min else None,
            'sync_count': self.sync_count,
            'ssot_available': self.ssot_available,
            'sync_interval': self.sync_interval_seconds
        }
