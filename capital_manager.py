"""
CAPITAL MANAGER v5.0.0 - Single Source of Truth (SSOT) Architecture
═══════════════════════════════════════════════════════════════════════════════

THE AUTHORITATIVE STATE TRACKER FOR ALL POSITIONS AND HOLDINGS.

v5.0.1 (2026-02-15): CRITICAL FIX - entry_size=0 guard clause
─────────────────────────────────────────────────────────────
BUG: calculate_max_entries() returned 0 when entry_size=0, blocking ALL entries.
     Phase 2 calls can_enter(symbol, 0) as a capacity pre-check, passing 0 because
     the actual trade size isn't known yet. The guard clause treated this as
     "zero-sized trade = no entries" instead of "just check if we have room."
FIX: Fall back to BASE_CAPITAL_PER_TRADE from config when entry_size <= 0.
IMPACT: Fixes both live trading and backtest — without this, zero trades execute.

v5.0.0 (2026-02-06): SSOT ARCHITECTURE - CRITICAL REDESIGN
─────────────────────────────────────────────────────────────
PROBLEM SOLVED: State drift between CapitalManager, Phase 4, and BrokerSync
caused false "position not at broker" alarms and illegal release attempts
when CNC holdings were treated as MIS positions.

KEY CHANGES:
1. ✅ SEMANTIC SEPARATION: deployed_positions{} (MIS/NRML) vs cnc_holdings{} (CNC)
2. ✅ SINGLE WRITER: Only CapitalManager mutates position/holding state
3. ✅ SOURCE TAGGING: Every entry tagged with origin (PHASE3/PHASE5/BROKER_ADOPTED/MANUAL)
4. ✅ AUTHORITY FLOW: Phase 4 READS from CapitalManager, never writes directly
5. ✅ PHASE 4 MODE: ACTIVE_CONTROL for MIS, OBSERVE_ONLY for CNC
6. ✅ ILLEGAL RELEASE GUARD: Enhanced to check deployed_positions only (not cnc_holdings)

ARCHITECTURAL PRINCIPLES (Safety-Certified System Design):
─────────────────────────────────────────────────────────────
- Single Writer, Multiple Readers: CapitalManager is the ONLY writer
- Semantic Separation: Holdings (inventory) ≠ Positions (controlled actuators)
- Authority Flows Downward: Phases request, CapitalManager authorizes
- BrokerSync is OBSERVER ONLY: Reports deltas, never modifies state

DATA STRUCTURES:
─────────────────────────────────────────────────────────────
deployed_positions = {
    'POLICYBZR': PositionRecord(
        symbol='POLICYBZR',
        quantity=18,
        avg_price=1516.00,
        deployed_amount=5454.00,  # margin used
        product='MIS',
        source='PHASE5_GAP',
        gtt_id='305747696',
        phase4_mode='ACTIVE_CONTROL',
        created_at='2026-02-06T09:26:14',
        last_updated='2026-02-06T09:26:14'
    )
}

cnc_holdings = {
    'ADANIPORTS': HoldingRecord(
        symbol='ADANIPORTS',
        quantity=1,
        quantity_settled=0,
        quantity_t1=1,
        avg_price=1564.80,
        source='MANUAL',
        phase4_mode='OBSERVE_ONLY',  # NO control authority!
        created_at='2026-02-05T15:30:00',
        last_updated='2026-02-06T09:26:14'
    )
}

SOURCE TAGS (Metadata Only - No Logic Branching in Phase 1):
─────────────────────────────────────────────────────────────
- PHASE3_ENTRY: Normal V-Recovery entry via Phase 3
- PHASE5_GAP: Gap Strategy entry via Phase 5
- BROKER_ADOPTED: Discovered at broker on startup/sync
- MANUAL: User traded directly in Kite
- RECOVERY: Position recovered after crash

PHASE 4 MODES:
─────────────────────────────────────────────────────────────
- ACTIVE_CONTROL: Full authority (TCAS, ILS, predictive stop, exits)
- OBSERVE_ONLY: P&L monitoring only (no control actions)

INVARIANT (Must ALWAYS hold):
  deployed + reserved + available = total
  (CNC holdings are NOT counted in deployed - they're inventory)

Previous versions:
- v4.8.1: Emergency flag, send_alert() fix
- v4.8.0: Illegal release guard, event logging
- v4.7.2: Broker position adoption
- v4.5.6: Capital invariant checking

Author: Trading System v5.0.0
Date: 2026-02-06
"""

import time
import logging
from datetime import datetime
from typing import Dict, Optional, Tuple, List, Any
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger('CapitalManager')


# ═══════════════════════════════════════════════════════════════════════════════
# v5.0.0: ENUMS AND DATA STRUCTURES
# ═══════════════════════════════════════════════════════════════════════════════

class CapitalEvent(Enum):
    """Types of capital state changes for audit logging"""
    SYNC = "SYNC"                        # Broker sync
    RESERVE = "RESERVE"                  # Capital reserved for pending order
    UNRESERVE = "UNRESERVE"              # Reservation cancelled
    DEPLOY = "DEPLOY"                    # Order filled, capital deployed
    RELEASE = "RELEASE"                  # Position closed, capital released
    ADOPT_POSITION = "ADOPT_POSITION"    # v5.0.0: MIS/NRML position discovered at broker
    ADOPT_HOLDING = "ADOPT_HOLDING"      # v5.0.0: CNC holding discovered at broker
    ILLEGAL_RELEASE = "ILLEGAL_RELEASE"  # Blocked release attempt
    HOLDING_UPDATE = "HOLDING_UPDATE"    # v5.0.0: CNC holding state changed


class PositionSource(Enum):
    """Source of position/holding entry - for audit trail"""
    PHASE3_ENTRY = "PHASE3_ENTRY"        # Normal V-Recovery entry
    PHASE5_GAP = "PHASE5_GAP"            # Gap Strategy entry
    BROKER_ADOPTED = "BROKER_ADOPTED"    # Discovered at broker
    MANUAL = "MANUAL"                    # User traded directly in Kite
    RECOVERY = "RECOVERY"                # Position recovered after crash
    UNKNOWN = "UNKNOWN"                  # Legacy/migration
    PHASE5A_PVAT = "PHASE5A_PVAT"        # v5.4.2: Independent PVAT breakout entry
    PH8_MOMENTUM = "PH8_MOMENTUM"        # v8.0.0: Phase 8 Weekly Momentum Strategy


class Phase4Mode(Enum):
    """Phase 4 control authority mode"""
    ACTIVE_CONTROL = "ACTIVE_CONTROL"    # Full authority (TCAS, ILS, exits)
    OBSERVE_ONLY = "OBSERVE_ONLY"        # P&L monitoring only


@dataclass
class CapitalEventLog:
    """Audit log entry for capital state change"""
    timestamp: str
    event_type: CapitalEvent
    symbol: str
    amount: float
    pnl: float
    before_state: Dict
    after_state: Dict
    source: str  # Which component triggered this
    details: str


@dataclass
class PositionRecord:
    """
    v5.0.0: MIS/NRML Position Record (Phase 4 ACTIVE_CONTROL)
    
    These are actively controlled positions that Phase 4 manages:
    - TCAS alerts
    - ILS guidance
    - Predictive stops
    - Exit execution
    """
    symbol: str
    quantity: int
    avg_price: float
    deployed_amount: float          # Margin used (qty × price × margin_pct)
    product: str                    # MIS or NRML
    source: PositionSource          # Where this position came from
    phase4_mode: Phase4Mode = Phase4Mode.ACTIVE_CONTROL
    gtt_id: Optional[str] = None    # GTT order ID if placed
    entry_count: int = 1            # Number of entries (for averaging)
    created_at: str = ""
    last_updated: str = ""
    
    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now().isoformat()
        if not self.last_updated:
            self.last_updated = datetime.now().isoformat()
    
    def to_dict(self) -> Dict:
        return {
            'symbol': self.symbol,
            'quantity': self.quantity,
            'avg_price': self.avg_price,
            'deployed_amount': self.deployed_amount,
            'product': self.product,
            'source': self.source.value if isinstance(self.source, PositionSource) else self.source,
            'phase4_mode': self.phase4_mode.value if isinstance(self.phase4_mode, Phase4Mode) else self.phase4_mode,
            'gtt_id': self.gtt_id,
            'entry_count': self.entry_count,
            'created_at': self.created_at,
            'last_updated': self.last_updated
        }


@dataclass
class HoldingRecord:
    """
    v5.0.0: CNC Holding Record (Phase 4 OBSERVE_ONLY)
    
    These are delivery holdings - inventory, not controlled positions:
    - P&L monitoring allowed
    - NO TCAS/ILS/predictive stop
    - NO exit execution
    - NO capital release logic
    """
    symbol: str
    quantity: int                   # Total quantity (settled + T1)
    quantity_settled: int           # Can sell immediately
    quantity_t1: int                # T+1 pending (can't sell yet)
    avg_price: float
    source: PositionSource          # Where this holding came from
    phase4_mode: Phase4Mode = Phase4Mode.OBSERVE_ONLY  # ALWAYS observe-only
    isin: str = ""
    collateral_quantity: int = 0
    created_at: str = ""
    last_updated: str = ""
    
    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now().isoformat()
        if not self.last_updated:
            self.last_updated = datetime.now().isoformat()
    
    def to_dict(self) -> Dict:
        return {
            'symbol': self.symbol,
            'quantity': self.quantity,
            'quantity_settled': self.quantity_settled,
            'quantity_t1': self.quantity_t1,
            'avg_price': self.avg_price,
            'source': self.source.value if isinstance(self.source, PositionSource) else self.source,
            'phase4_mode': self.phase4_mode.value if isinstance(self.phase4_mode, Phase4Mode) else self.phase4_mode,
            'isin': self.isin,
            'collateral_quantity': self.collateral_quantity,
            'created_at': self.created_at,
            'last_updated': self.last_updated
        }


# Legacy compatibility - kept for backward compatibility with existing code
@dataclass
class StockExposure:
    """
    Legacy exposure tracking - DEPRECATED in v5.0.0
    Use PositionRecord for MIS/NRML, HoldingRecord for CNC
    """
    symbol: str
    deployed_amount: float = 0.0
    entry_count: int = 0
    avg_entry_price: float = 0.0
    last_updated: str = ""
    
    def to_dict(self) -> Dict:
        return {
            'symbol': self.symbol,
            'deployed_amount': self.deployed_amount,
            'entry_count': self.entry_count,
            'avg_entry_price': self.avg_entry_price,
            'last_updated': self.last_updated
        }


class CapitalManager:
    """
    v5.0.0: Single Source of Truth (SSOT) Capital Manager
    
    THE ONLY COMPONENT THAT MAY MUTATE POSITION/HOLDING STATE.
    
    Key architectural changes:
    1. deployed_positions{} - MIS/NRML only (Phase 4 ACTIVE_CONTROL)
    2. cnc_holdings{} - CNC only (Phase 4 OBSERVE_ONLY)
    3. Source tagging on all entries
    4. Explicit Phase 4 mode assignment
    
    Features:
    - Staleness guard (auto-refresh if data > 5 seconds old)
    - Reserve/Deploy/Release lifecycle with guards
    - Concentration limits per stock
    - Illegal release protection (checks deployed_positions only)
    - Event logging for audit trail
    - CNC holding tracking (separate from MIS positions)
    """
    
    # ═══════════════════════════════════════════════════════════════════════════
    # CONFIGURATION
    # ═══════════════════════════════════════════════════════════════════════════
    
    DEFAULT_CONFIG = {
        'MAX_CONCENTRATION_PCT': 0.25,      # Max 25% of capital in single stock
        'ABSOLUTE_MAX_ENTRIES': 3,          # Hard cap per stock (safety)
        'MIN_CAPITAL_BUFFER': 1000,         # Keep ₹1,000 reserve
        'MAX_SYNC_AGE': 5,                  # Seconds before auto-refresh
        'ENABLE_ADAPTIVE_LIMITS': True,     # Feature flag
        'MIS_MARGIN_PCT': 0.20,             # MIS requires ~20% margin
        'CNC_MARGIN_PCT': 1.00,             # CNC requires 100% (full value)
    }
    
    # ═══════════════════════════════════════════════════════════════════════════
    # INITIALIZATION
    # ═══════════════════════════════════════════════════════════════════════════
    
    def __init__(self, kite, config, telegram=None):
        """
        Initialize Capital Manager v5.0.0 SSOT.
        
        Args:
            kite: Kite Connect instance
            config: System configuration object
            telegram: Optional Telegram notifier
        """
        self.kite = kite
        self.config = config
        self.telegram = telegram
        
        # Load capital management config
        self._load_config()
        
        # ═══════════════════════════════════════════════════════════════════
        # v5.0.0: CAPITAL STATE
        # ═══════════════════════════════════════════════════════════════════
        self.total_capital: float = 0.0
        self.available_capital: float = 0.0
        self.deployed_capital: float = 0.0      # MIS/NRML positions only
        self.reserved_capital: float = 0.0      # Pending orders
        
        # ═══════════════════════════════════════════════════════════════════
        # v5.0.0: SSOT - SEPARATE TRACKING FOR POSITIONS VS HOLDINGS
        # ═══════════════════════════════════════════════════════════════════
        # MIS/NRML positions (Phase 4 ACTIVE_CONTROL)
        self.deployed_positions: Dict[str, PositionRecord] = {}
        
        # CNC holdings (Phase 4 OBSERVE_ONLY) - NOT in deployed_capital!
        self.cnc_holdings: Dict[str, HoldingRecord] = {}
        
        # Legacy compatibility - mirrors deployed_positions for old code
        self.stock_exposures: Dict[str, StockExposure] = {}
        
        # ═══════════════════════════════════════════════════════════════════
        # SYNC TRACKING
        # ═══════════════════════════════════════════════════════════════════
        self.last_sync_ts: float = 0
        self.last_sync_time: str = ""
        self.sync_count: int = 0
        
        # ═══════════════════════════════════════════════════════════════════
        # STATE FLAGS
        # ═══════════════════════════════════════════════════════════════════
        self.initialized: bool = False
        self.last_error: Optional[str] = None
        self.capital_broken: bool = False  # Emergency flag when invariant violated
        
        # ═══════════════════════════════════════════════════════════════════
        # EVENT LOG FOR AUDIT TRAIL
        # ═══════════════════════════════════════════════════════════════════
        self.event_log: List[CapitalEventLog] = []
        self.max_event_log_size: int = 100
        
        logger.info("═" * 70)
        logger.info("💰 CAPITAL MANAGER v5.0.0 - SSOT ARCHITECTURE")
        logger.info("═" * 70)
        logger.info("   ✅ SSOT: Single Source of Truth for all position state")
        logger.info("   ✅ SEMANTIC SEPARATION: deployed_positions{} vs cnc_holdings{}")
        logger.info("   ✅ SOURCE TAGGING: All entries tagged with origin")
        logger.info("   ✅ PHASE 4 MODES: ACTIVE_CONTROL vs OBSERVE_ONLY")
        logger.info("   ✅ SINGLE WRITER: Only CapitalManager mutates state")
        logger.info("   ✅ Illegal Release Guard: ENABLED")
        logger.info("   ✅ Event Logging: ENABLED")
        logger.info("   ✅ State Drift Detection: ENABLED")
        self._log_config()
    
    def _load_config(self):
        """Load configuration from config object or use defaults"""
        cap_config = getattr(self.config, 'CAPITAL_MANAGEMENT', {})
        
        self.max_concentration_pct = cap_config.get(
            'MAX_CONCENTRATION_PCT', 
            self.DEFAULT_CONFIG['MAX_CONCENTRATION_PCT']
        )
        self.absolute_max_entries = cap_config.get(
            'ABSOLUTE_MAX_ENTRIES',
            self.DEFAULT_CONFIG['ABSOLUTE_MAX_ENTRIES']
        )
        self.min_capital_buffer = cap_config.get(
            'MIN_CAPITAL_BUFFER',
            self.DEFAULT_CONFIG['MIN_CAPITAL_BUFFER']
        )
        self.max_sync_age = cap_config.get(
            'MAX_SYNC_AGE',
            self.DEFAULT_CONFIG['MAX_SYNC_AGE']
        )
        self.enable_adaptive = cap_config.get(
            'ENABLE_ADAPTIVE_LIMITS',
            self.DEFAULT_CONFIG['ENABLE_ADAPTIVE_LIMITS']
        )
        self.mis_margin_pct = cap_config.get(
            'MIS_MARGIN_PCT',
            self.DEFAULT_CONFIG['MIS_MARGIN_PCT']
        )
        self.cnc_margin_pct = cap_config.get(
            'CNC_MARGIN_PCT',
            self.DEFAULT_CONFIG['CNC_MARGIN_PCT']
        )
    
    def _log_config(self):
        """Log current configuration"""
        logger.info(f"   Max Concentration: {self.max_concentration_pct * 100:.0f}% per stock")
        logger.info(f"   Absolute Max Entries: {self.absolute_max_entries} per stock")
        logger.info(f"   Min Capital Buffer: ₹{self.min_capital_buffer:,.0f}")
        logger.info(f"   Staleness Guard: {self.max_sync_age}s")
        logger.info(f"   Adaptive Limits: {'ENABLED' if self.enable_adaptive else 'DISABLED'}")
        logger.info("")
    
    # ═══════════════════════════════════════════════════════════════════════════════
    # v5.0.0: EVENT LOGGING FOR AUDIT TRAIL
    # ═══════════════════════════════════════════════════════════════════════════════
    
    def _log_event(self, event_type: CapitalEvent, symbol: str, amount: float, 
                   pnl: float, source: str, details: str) -> CapitalEventLog:
        """Log a capital state change event for audit trail."""
        before_state = self._get_state_snapshot()
        
        event = CapitalEventLog(
            timestamp=datetime.now().isoformat(),
            event_type=event_type,
            symbol=symbol,
            amount=amount,
            pnl=pnl,
            before_state=before_state,
            after_state={},  # Will be filled after state change
            source=source,
            details=details
        )
        
        # Keep log bounded
        if len(self.event_log) >= self.max_event_log_size:
            self.event_log.pop(0)
        
        self.event_log.append(event)
        return event
    
    def _complete_event(self, event: CapitalEventLog):
        """Complete an event by capturing the after-state"""
        event.after_state = self._get_state_snapshot()
    
    def _get_state_snapshot(self) -> Dict:
        """Get current capital state as a dictionary"""
        return {
            'total': self.total_capital,
            'deployed': self.deployed_capital,
            'reserved': self.reserved_capital,
            'available': self.available_capital,
            'mis_positions': list(self.deployed_positions.keys()),
            'cnc_holdings': list(self.cnc_holdings.keys())
        }
    
    def get_recent_events(self, count: int = 10) -> List[Dict]:
        """Get recent capital events for debugging"""
        events = self.event_log[-count:] if self.event_log else []
        return [
            {
                'timestamp': e.timestamp,
                'type': e.event_type.value,
                'symbol': e.symbol,
                'amount': e.amount,
                'pnl': e.pnl,
                'source': e.source,
                'details': e.details
            }
            for e in events
        ]
    
    # ═══════════════════════════════════════════════════════════════════════════════
    # CAPITAL INVARIANT CHECKING
    # ═══════════════════════════════════════════════════════════════════════════════
    
    def check_invariant(self) -> tuple:
        """
        Check capital conservation invariant.
        
        INVARIANT: total_capital == deployed + reserved + available
        NOTE: CNC holdings are NOT in deployed_capital (they're inventory)
        
        Returns:
            (bool, str): (is_valid, message)
        """
        calculated_total = self.deployed_capital + self.reserved_capital + self.available_capital
        diff = abs(calculated_total - self.total_capital)
        
        # Allow tiny float errors (< ₹1)
        if diff > 1.0:
            msg = (f"INVARIANT VIOLATION: deployed(₹{self.deployed_capital:,.0f}) + "
                   f"reserved(₹{self.reserved_capital:,.0f}) + "
                   f"available(₹{self.available_capital:,.0f}) = "
                   f"₹{calculated_total:,.0f} != total(₹{self.total_capital:,.0f})")
            logger.error(f"   ⚠️ {msg}")
            return False, msg
        
        return True, "OK"
    
    def _verify_and_log_invariant(self, operation: str):
        """Verify invariant after operation and log if violated"""
        ok, msg = self.check_invariant()
        if not ok:
            # Set emergency flag - blocks new entries
            self.capital_broken = True
            
            logger.error(f"   ⚠️ INVARIANT VIOLATED after {operation}: {msg}")
            logger.error(f"   🚨 CAPITAL BROKEN FLAG SET - NEW ENTRIES BLOCKED")
            logger.error(f"   State snapshot: {self._get_state_snapshot()}")
            logger.error(f"   Recent events: {self.get_recent_events(5)}")
            
            if self.telegram:
                try:
                    self.telegram.send_critical(
                        f"🚨 CAPITAL INTEGRITY FAILURE\n\n"
                        f"After: {operation}\n"
                        f"{msg}\n\n"
                        f"NEW ENTRIES BLOCKED\n"
                        f"Existing positions will continue normally.\n"
                        f"Restart system after fixing root cause."
                    )
                except Exception as e:
                    logger.error(f"   Failed to send Telegram alert: {e}")
    
    def _check_buffer_sanity(self):
        """Warn if buffer consumes excessive capital."""
        if self.total_capital > 0:
            buffer_pct = (self.min_capital_buffer / self.total_capital) * 100
            
            if buffer_pct > 50:
                msg = (
                    f"⚠️ BUFFER CONFIGURATION WARNING\n\n"
                    f"💰 Total Capital: ₹{self.total_capital:,.0f}\n"
                    f"🛡️ Capital Buffer: ₹{self.min_capital_buffer:,.0f}\n"
                    f"📊 Buffer Percentage: {buffer_pct:.0f}%\n\n"
                    f"⚠️ Buffer consumes {buffer_pct:.0f}% of total capital!\n"
                    f"This severely constrains trading capacity.\n\n"
                    f"💡 Recommendation:\n"
                    f"Reduce MIN_CAPITAL_BUFFER to ~₹{int(self.total_capital * 0.1):,} (10% of capital)"
                )
                logger.warning("═" * 70)
                logger.warning("⚠️ CAPITAL BUFFER WARNING")
                logger.warning(msg.replace("\n", " | "))
                logger.warning("═" * 70)
                
                if self.telegram:
                    self.telegram.send_critical(msg)
            elif buffer_pct > 20:
                logger.info(f"   ℹ️ Buffer uses {buffer_pct:.0f}% of capital (acceptable but high)")
            else:
                logger.debug(f"   ✅ Buffer at {buffer_pct:.0f}% of capital (healthy)")
    
    # ═══════════════════════════════════════════════════════════════════════════════
    # v5.0.0: SSOT POSITION/HOLDING QUERIES
    # ═══════════════════════════════════════════════════════════════════════════════
    
    def is_deployed(self, symbol: str) -> bool:
        """
        v5.0.0: Check if symbol is in deployed_positions (MIS/NRML only).
        
        This is the PRIMARY check for Phase 4 ACTIVE_CONTROL eligibility.
        """
        return symbol in self.deployed_positions
    
    def is_holding(self, symbol: str) -> bool:
        """
        v5.0.0: Check if symbol is a CNC holding.
        
        CNC holdings get Phase 4 OBSERVE_ONLY mode.
        """
        return symbol in self.cnc_holdings
    
    def is_known(self, symbol: str) -> bool:
        """
        v5.0.0: Check if symbol is tracked anywhere (position OR holding).
        
        Used by BrokerSync to determine if position needs adoption.
        """
        return symbol in self.deployed_positions or symbol in self.cnc_holdings
    
    def get_phase4_mode(self, symbol: str) -> Optional[Phase4Mode]:
        """
        v5.0.0: Get Phase 4 control mode for a symbol.
        
        Returns:
            Phase4Mode.ACTIVE_CONTROL for MIS/NRML positions
            Phase4Mode.OBSERVE_ONLY for CNC holdings
            None if symbol not tracked
        """
        if symbol in self.deployed_positions:
            return self.deployed_positions[symbol].phase4_mode
        elif symbol in self.cnc_holdings:
            return self.cnc_holdings[symbol].phase4_mode
        return None
    
    def get_position_record(self, symbol: str) -> Optional[PositionRecord]:
        """v5.0.0: Get MIS/NRML position record"""
        return self.deployed_positions.get(symbol)
    
    def get_holding_record(self, symbol: str) -> Optional[HoldingRecord]:
        """v5.0.0: Get CNC holding record"""
        return self.cnc_holdings.get(symbol)
    
    def get_all_deployed_symbols(self) -> List[str]:
        """v5.0.0: Get list of all MIS/NRML position symbols"""
        return list(self.deployed_positions.keys())
    
    def get_all_holding_symbols(self) -> List[str]:
        """v5.0.0: Get list of all CNC holding symbols"""
        return list(self.cnc_holdings.keys())
    
    def get_all_tracked_symbols(self) -> List[str]:
        """v5.0.0: Get list of all tracked symbols (positions + holdings)"""
        return list(self.deployed_positions.keys()) + list(self.cnc_holdings.keys())
    
    # Legacy compatibility
    def is_position_known(self, symbol: str) -> bool:
        """Legacy: Check if position is tracked (now checks deployed_positions only)"""
        return self.is_deployed(symbol)
    
    def get_all_positions(self) -> List[str]:
        """Legacy: Get all positions (now returns deployed_positions only)"""
        return self.get_all_deployed_symbols()
    
    def get_position_details(self, symbol: str) -> Optional[Dict]:
        """Legacy: Get position details"""
        pos = self.deployed_positions.get(symbol)
        if pos:
            return pos.to_dict()
        return None
    
    # ═══════════════════════════════════════════════════════════════════════════════
    # BROKER SYNC
    # ═══════════════════════════════════════════════════════════════════════════════
    
    def sync_with_broker(self) -> bool:
        """
        v5.0.0: Sync capital state with broker.
        
        IMPORTANT: This syncs CAPITAL AMOUNTS only.
        Position/Holding adoption should be done via adopt_position() / add_holding()
        called by orchestrator after BrokerSync.reconcile().
        
        Returns:
            True if sync successful
        """
        logger.info("🔄 Syncing capital state with broker...")
        
        from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
        
        def _fetch_broker_data():
            """Fetch margins, positions, holdings from broker"""
            m = self.kite.margins()
            p = self.kite.positions()
            h = self.kite.holdings() or []
            return m, p, h
        
        try:
            event = self._log_event(
                CapitalEvent.SYNC, "", 0, 0, "BROKER_SYNC", "Starting broker sync"
            )
            
            # Run broker API calls with 15-second timeout
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(_fetch_broker_data)
                try:
                    margins, positions, holdings = future.result(timeout=15)
                except FuturesTimeoutError:
                    raise TimeoutError("Broker sync timeout after 15 seconds")
            
            if not margins:
                logger.error("   Failed to fetch margins")
                self.last_error = "Margin fetch failed"
                return False
            
            # Extract available cash
            equity_margins = margins.get('equity', {}).get('available', {})
            self.total_capital = equity_margins.get('live_balance', 0)

            if self.total_capital == 0:
                self.total_capital = equity_margins.get('cash', 0)
                logger.warning("   ⚠️ live_balance unavailable, using cash as fallback")

            # v5.7.0: Paper-mode fallback — broker returns ₹0 when running paper trades
            # against a Zerodha account with no live margin deployed.
            # Use config.TOTAL_CAPITAL so paper positions aren't blocked by ₹0 capital.
            if self.total_capital == 0 and hasattr(self.config, 'TOTAL_CAPITAL') and self.config.TOTAL_CAPITAL > 0:
                self.total_capital = float(self.config.TOTAL_CAPITAL)
                logger.warning(
                    f"   ⚠️ Broker returned ₹0 balance — paper mode detected. "
                    f"Using config TOTAL_CAPITAL = ₹{self.total_capital:,.0f}"
                )
            
            # ═══════════════════════════════════════════════════════════════
            # v5.0.0: Calculate deployed from our tracked positions only
            # (NOT from broker - that could include manual trades)
            # ═══════════════════════════════════════════════════════════════
            deployed_from_tracked = sum(
                pos.deployed_amount for pos in self.deployed_positions.values()
            )
            
            # v5.0.0: Note - we DON'T add CNC holdings to deployed_capital
            # They're inventory, not margin-deployed positions
            
            # Update state
            self.deployed_capital = deployed_from_tracked
            self.available_capital = self.total_capital - self.deployed_capital - self.reserved_capital
            
            # ═══════════════════════════════════════════════════════════════
            # v5.0.0: Update legacy stock_exposures for backward compatibility
            # ═══════════════════════════════════════════════════════════════
            self.stock_exposures.clear()
            for symbol, pos in self.deployed_positions.items():
                self.stock_exposures[symbol] = StockExposure(
                    symbol=symbol,
                    deployed_amount=pos.deployed_amount,
                    entry_count=pos.entry_count,
                    avg_entry_price=pos.avg_price,
                    last_updated=pos.last_updated
                )
            
            # Update sync tracking
            self.last_sync_ts = time.time()
            self.last_sync_time = datetime.now().strftime("%H:%M:%S")
            self.sync_count += 1
            self.initialized = True
            self.last_error = None
            
            self._complete_event(event)
            self._check_buffer_sanity()
            
            # Log summary
            logger.info(f"   ✅ Sync #{self.sync_count} complete @ {self.last_sync_time}")
            logger.info(f"   💰 Total Capital: ₹{self.total_capital:,.0f}")
            logger.info(f"   📊 Deployed (MIS): ₹{self.deployed_capital:,.0f}")
            logger.info(f"   🔓 Available: ₹{self.available_capital:,.0f}")
            logger.info(f"   📈 MIS Positions: {len(self.deployed_positions)}")
            logger.info(f"   📦 CNC Holdings: {len(self.cnc_holdings)}")
            
            return True
            
        except TimeoutError as e:
            logger.error("⚠️ BROKER SYNC TIMEOUT (15 seconds)")
            logger.warning("   Using fallback capital - will retry in 5 minutes")
            
            if hasattr(self.config, 'TOTAL_CAPITAL'):
                self.total_capital = self.config.TOTAL_CAPITAL
                self.available_capital = self.total_capital - self.deployed_capital - self.reserved_capital
                self.initialized = True
                self.last_sync_ts = time.time()
                self.last_sync_time = datetime.now().strftime("%H:%M:%S")
                self.sync_count += 1
                
                logger.warning(f"   📊 Fallback Capital: ₹{self.total_capital:,.0f}")
                
                if self.telegram:
                    self.telegram.send_critical(
                        "⚠️ BROKER SYNC TIMEOUT\n\n"
                        f"Kite API took >15 seconds.\n"
                        f"Using config fallback: ₹{self.total_capital:,}\n\n"
                        "System starting - will retry in 5 min."
                    )
                
                self.last_error = "Broker timeout - using fallback"
                return True
            
            logger.critical("   ❌ No fallback capital - cannot continue")
            self.last_error = str(e)
            return False
            
        except Exception as e:
            logger.error(f"   ❌ Broker sync failed: {e}")
            self.last_error = str(e)
            return False
    
    def _ensure_fresh_data(self):
        """Refresh data if stale (older than max_sync_age seconds)"""
        age = time.time() - self.last_sync_ts
        if age > self.max_sync_age and self.initialized:
            logger.debug(f"   🔄 Data stale ({age:.1f}s > {self.max_sync_age}s), refreshing...")
            self.sync_with_broker()
    
    # ═══════════════════════════════════════════════════════════════════════════════
    # CAPITAL CALCULATIONS
    # ═══════════════════════════════════════════════════════════════════════════════
    
    def get_available(self) -> float:
        """Get available capital after minimum buffer"""
        self._ensure_fresh_data()
        return max(0, self.available_capital - self.min_capital_buffer)
    
    def get_total_exposure_pct(self) -> float:
        """Get total exposure as percentage of total capital"""
        if self.total_capital <= 0:
            return 0.0
        return (self.deployed_capital / self.total_capital) * 100
    
    def get_stock_exposure(self, symbol: str) -> float:
        """Get current exposure in a stock (MIS/NRML positions only)"""
        pos = self.deployed_positions.get(symbol)
        return pos.deployed_amount if pos else 0.0
    
    def get_stock_exposure_pct(self, symbol: str) -> float:
        """Get stock exposure as percentage of total capital"""
        if self.total_capital <= 0:
            return 0.0
        return (self.get_stock_exposure(symbol) / self.total_capital) * 100
    
    def get_stock_entry_count(self, symbol: str) -> int:
        """Get number of entries in a stock"""
        pos = self.deployed_positions.get(symbol)
        return pos.entry_count if pos else 0
    
    def calculate_entry_size(self, price: float, quantity: int, product: str = 'MIS') -> float:
        """Calculate entry size (capital required) for a trade"""
        if product == 'MIS':
            return price * quantity * self.mis_margin_pct
        else:
            return price * quantity * self.cnc_margin_pct
    
    def calculate_max_entries(self, symbol: str, entry_size: float) -> int:
        """Calculate maximum additional entries allowed for a stock"""
        if entry_size <= 0:
            # v4.8.2 FIX: entry_size=0 means "capacity check" (Phase 2 pre-check)
            # Fall back to BASE_CAPITAL_PER_TRADE instead of blocking all entries
            entry_size = getattr(self.config, 'BASE_CAPITAL_PER_TRADE', 10000)
            if entry_size <= 0:
                entry_size = 10000  # Ultimate fallback
        
        current_exposure = self.get_stock_exposure(symbol)
        current_entries = self.get_stock_entry_count(symbol)
        
        # Exposure limit
        max_exposure = self.total_capital * self.max_concentration_pct
        remaining_exposure = max_exposure - current_exposure
        exposure_based_entries = int(remaining_exposure / entry_size) if entry_size > 0 else 0
        
        # Capital limit
        available = self.get_available()
        capital_based_entries = int(available / entry_size) if entry_size > 0 else 0
        
        # Absolute limit
        absolute_remaining = max(0, self.absolute_max_entries - current_entries)
        
        max_entries = min(exposure_based_entries, capital_based_entries, absolute_remaining)
        
        logger.debug(f"   Max entries for {symbol}:")
        logger.debug(f"      Current: {current_entries} entries, ₹{current_exposure:,.0f} exposure")
        logger.debug(f"      Exposure limit: {exposure_based_entries}")
        logger.debug(f"      Capital limit: {capital_based_entries}")
        logger.debug(f"      Absolute limit: {absolute_remaining}")
        logger.debug(f"      → Result: {max_entries} entries allowed")
        
        return max(0, max_entries)
    
    def can_afford(self, amount: float) -> bool:
        """Check if capital is available for trade"""
        return self.get_available() >= amount
    
    # ═══════════════════════════════════════════════════════════════════════════════
    # PHASE 2 COMPATIBILITY API
    # ═══════════════════════════════════════════════════════════════════════════════
    
    def can_enter(self, symbol: str, entry_size: float) -> dict:
        """
        Check if entry is allowed (Phase 2 compatibility wrapper).
        """
        self._ensure_fresh_data()
        
        # Emergency block if capital integrity violated
        if self.capital_broken:
            logger.error(f"   🚨 ENTRY BLOCKED: Capital integrity violated")
            return {
                'can_enter': False,
                'max_entries': 0,
                'current_entries': self.get_stock_entry_count(symbol),
                'available_capital': 0,
                'stock_exposure': self.get_stock_exposure(symbol),
                'stock_exposure_pct': self.get_stock_exposure_pct(symbol),
                'reasons': ['Capital integrity violated - system in safe mode. Restart required.']
            }
        
        max_entries = self.calculate_max_entries(symbol, entry_size)
        current_entries = self.get_stock_entry_count(symbol)
        can_enter = max_entries > 0
        
        reasons = []
        if not can_enter:
            if self.get_available() < entry_size:
                reasons.append(f"Insufficient capital (need ₹{entry_size:,.0f}, have ₹{self.get_available():,.0f})")
            if current_entries >= self.absolute_max_entries:
                reasons.append(f"Max entries reached ({self.absolute_max_entries})")
            if self.get_stock_exposure_pct(symbol) >= self.max_concentration_pct * 100:
                reasons.append(f"Concentration limit ({self.max_concentration_pct * 100:.0f}%)")
        
        logger.info("─" * 50)
        logger.info(f"💰 CAPITAL CHECK for {symbol}")
        logger.info("─" * 50)
        logger.info(f"   Entry Size: ₹{entry_size:,.0f}")
        logger.info(f"   Total Capital: ₹{self.total_capital:,.0f}")
        logger.info(f"   Deployed: ₹{self.deployed_capital:,.0f}")
        logger.info(f"   Reserved: ₹{self.reserved_capital:,.0f}")
        logger.info(f"   Available: ₹{self.available_capital:,.0f}")
        logger.info(f"   Usable (after buffer): ₹{self.get_available():,.0f}")
        logger.info(f"   Current {symbol} exposure: ₹{self.get_stock_exposure(symbol):,.0f}")
        logger.info(f"   Current {symbol} entries: {current_entries}")
        logger.info(f"   Max entries allowed: {max_entries}")
        logger.info(f"   Can Enter: {'✅ YES' if can_enter else '❌ NO'}")
        if reasons:
            logger.info(f"   Reasons: {', '.join(reasons)}")
        logger.info("─" * 50)
        
        return {
            'can_enter': can_enter,
            'max_entries': max_entries,
            'current_entries': current_entries,
            'available_capital': self.get_available(),
            'stock_exposure': self.get_stock_exposure(symbol),
            'stock_exposure_pct': self.get_stock_exposure_pct(symbol),
            'reasons': reasons
        }
    
    # ═══════════════════════════════════════════════════════════════════════════════
    # CAPITAL LIFECYCLE: RESERVE → DEPLOY → RELEASE
    # ═══════════════════════════════════════════════════════════════════════════════
    
    def reserve(self, symbol: str, amount: float) -> bool:
        """
        Reserve capital for pending order.
        Called by Phase 3/5 before placing BUY order.
        """
        if amount <= 0:
            return True
        
        if amount > self.available_capital:
            logger.warning(f"   ⚠️ Cannot reserve ₹{amount:,.0f} for {symbol} "
                          f"(available: ₹{self.available_capital:,.0f})")
            return False
        
        event = self._log_event(
            CapitalEvent.RESERVE, symbol, amount, 0, "PHASE3/5", 
            f"Reserving capital for pending order"
        )
        
        self.available_capital -= amount
        self.reserved_capital += amount
        
        self._complete_event(event)
        
        logger.info(f"   🔒 Reserved ₹{amount:,.0f} for {symbol} "
                   f"(available: ₹{self.available_capital:,.0f})")
        
        self._verify_and_log_invariant(f"reserve({symbol}, ₹{amount:,.0f})")
        
        return True
    
    def unreserve(self, symbol: str, amount: float):
        """Unreserve capital (order cancelled/rejected)."""
        if amount <= 0:
            return
        
        event = self._log_event(
            CapitalEvent.UNRESERVE, symbol, amount, 0, "PHASE3/5",
            f"Unreserving capital - order cancelled/rejected"
        )
        
        actual_unreserve = min(amount, self.reserved_capital)
        self.reserved_capital -= actual_unreserve
        self.available_capital += actual_unreserve
        
        self._complete_event(event)
        
        logger.info(f"   🔓 Unreserved ₹{actual_unreserve:,.0f} for {symbol} "
                   f"(available: ₹{self.available_capital:,.0f})")
        
        self._verify_and_log_invariant(f"unreserve({symbol}, ₹{actual_unreserve:,.0f})")
    
    def release_reservation(self, symbol: str, amount: float = 0, reservation_id: str = None):
        """Release a pending reservation (Phase 2 compatibility)."""
        self.unreserve(symbol, amount)
    
    def reserve_capital(self, symbol: str, amount: float) -> dict:
        """Reserve capital (Phase 2 compatibility wrapper).
        
        v5.1.0 FIX: Returns 'reserved' key (Phase 2 checks this), 
        plus 'success' for backward compat.
        """
        success = self.reserve(symbol, amount)
        return {
            'success': success,
            'reserved': success,  # v5.1.0 FIX: Phase 2 checks this key, not 'success'
            'reserved_amount': amount if success else 0,
            'available_after': self.available_capital
        }
    
    def deploy(self, symbol: str, amount: float, quantity: int = 0, 
               avg_price: float = 0, entry_price: float = None,
               source: PositionSource = PositionSource.PHASE3_ENTRY,
               product: str = 'MIS', gtt_id: str = None) -> bool:
        """
        v5.0.0: Deploy capital (BUY order filled).
        
        Called by Phase 3/5 when BUY order fills.
        Creates a PositionRecord in deployed_positions{}.
        
        Args:
            symbol: Stock symbol
            amount: Amount deployed (₹)
            quantity: Shares bought
            avg_price: Average entry price
            entry_price: Alias for avg_price
            source: Where this entry came from (PHASE3_ENTRY, PHASE5_GAP, etc.)
            product: MIS or NRML (NOT CNC - CNC goes to add_holding)
            gtt_id: GTT order ID if placed
            
        Returns:
            True if deployment recorded
        """
        if entry_price is not None:
            avg_price = entry_price
        if amount <= 0:
            return True
        
        # v5.1.0 FIX: Allow CNC for system-placed orders (Phase 3/5),
        # only reject CNC from external adoption (use add_holding() for those)
        system_sources = {
            PositionSource.PHASE3_ENTRY, PositionSource.PHASE5_GAP, PositionSource.PHASE5A_PVAT,
            PositionSource.PH8_MOMENTUM,
            'PHASE3_ENTRY', 'PHASE5_GAP', 'PHASE5A_PVAT', 'PH8_MOMENTUM'
        }
        source_val = source.value if isinstance(source, PositionSource) else source
        if product == 'CNC' and source_val not in {'PHASE3_ENTRY', 'PHASE5_GAP', 'PHASE5A_PVAT', 'PH8_MOMENTUM'}:
            if isinstance(source, PositionSource) and source not in {PositionSource.PHASE3_ENTRY, PositionSource.PHASE5_GAP, PositionSource.PHASE5A_PVAT, PositionSource.PH8_MOMENTUM}:
                logger.error(f"   ❌ deploy() called with product=CNC for {symbol} from {source_val}")
                logger.error(f"   External CNC holdings should use add_holding() instead")
                return False
        
        if product == 'CNC':
            logger.info(f"   📦 {symbol}: CNC deploy accepted (system order from {source_val})")
        
        event = self._log_event(
            CapitalEvent.DEPLOY, symbol, amount, 0, source.value if isinstance(source, PositionSource) else source,
            f"Order filled: {quantity} shares @ ₹{avg_price:.2f}"
        )
        
        # Move from reserved to deployed
        # v5.0.1 FIX: Handle case where reserve() was NOT called before deploy()
        # If reserved >= amount, normal flow (move reserved → deployed)
        # If reserved < amount, the shortfall must come from available
        actual_from_reserved = min(self.reserved_capital, amount)
        shortfall_from_available = amount - actual_from_reserved
        
        self.reserved_capital -= actual_from_reserved
        self.deployed_capital += amount
        
        if shortfall_from_available > 0:
            self.available_capital = max(0, self.available_capital - shortfall_from_available)
            logger.debug(f"   📝 deploy() direct: ₹{shortfall_from_available:,.0f} from available "
                        f"(reserve() was not called first)")
        
        # v5.0.0: Create or update PositionRecord
        if symbol in self.deployed_positions:
            pos = self.deployed_positions[symbol]
            # Update existing position (adding to position)
            old_qty = pos.quantity
            old_avg = pos.avg_price
            new_qty = old_qty + quantity
            # Weighted average price
            if new_qty > 0:
                pos.avg_price = ((old_qty * old_avg) + (quantity * avg_price)) / new_qty
            pos.quantity = new_qty
            pos.deployed_amount += amount
            pos.entry_count += 1
            pos.last_updated = datetime.now().isoformat()
            if gtt_id:
                pos.gtt_id = gtt_id
        else:
            # Create new position record
            self.deployed_positions[symbol] = PositionRecord(
                symbol=symbol,
                quantity=quantity,
                avg_price=avg_price,
                deployed_amount=amount,
                product=product,
                source=source if isinstance(source, PositionSource) else PositionSource(source),
                phase4_mode=Phase4Mode.ACTIVE_CONTROL,
                gtt_id=gtt_id,
                entry_count=1
            )
        
        # v5.0.0: Update legacy stock_exposures for backward compatibility
        if symbol in self.stock_exposures:
            exp = self.stock_exposures[symbol]
            exp.deployed_amount += amount
            exp.entry_count += 1
            exp.avg_entry_price = avg_price
            exp.last_updated = datetime.now().isoformat()
        else:
            self.stock_exposures[symbol] = StockExposure(
                symbol=symbol,
                deployed_amount=amount,
                entry_count=1,
                avg_entry_price=avg_price,
                last_updated=datetime.now().isoformat()
            )
        
        self._complete_event(event)
        
        logger.info(f"   💰 Deployed ₹{amount:,.0f} in {symbol} "
                   f"(source: {source.value if isinstance(source, PositionSource) else source}) "
                   f"(total deployed: ₹{self.deployed_capital:,.0f})")
        
        self._verify_and_log_invariant(f"deploy({symbol}, ₹{amount:,.0f})")
        
        return True
    
    def release(self, symbol: str, amount: float, pnl: float = 0) -> bool:
        """
        v5.0.0: Release capital (SELL order filled / position closed).
        
        CRITICAL: Only releases from deployed_positions{} (MIS/NRML).
        CNC holdings are NOT released via this method.
        
        Args:
            symbol: Stock symbol
            amount: Original deployed amount (₹)
            pnl: Profit/Loss realized (₹)
            
        Returns:
            True if release recorded, False if illegal release blocked
        """
        if amount <= 0:
            return True
        
        # ═══════════════════════════════════════════════════════════════
        # v5.0.0: ILLEGAL RELEASE GUARD - Now checks deployed_positions
        # ═══════════════════════════════════════════════════════════════
        if symbol not in self.deployed_positions:
            # Check if it's a CNC holding (different error message)
            if symbol in self.cnc_holdings:
                self._log_event(
                    CapitalEvent.ILLEGAL_RELEASE, symbol, amount, pnl, "PHASE3/4",
                    f"BLOCKED: Cannot release CNC holding via release(). Use remove_holding() if needed."
                )
                logger.warning(f"   ⚠️ release() called for CNC holding {symbol}")
                logger.warning(f"   CNC holdings are not in deployed_capital - no release needed")
                return True  # Not an error, just a no-op
            
            # Truly illegal release
            self._log_event(
                CapitalEvent.ILLEGAL_RELEASE, symbol, amount, pnl, "PHASE3/4",
                f"BLOCKED: Symbol not in deployed_positions"
            )
            
            logger.critical("═" * 70)
            logger.critical(f"🚨 ILLEGAL RELEASE BLOCKED: {symbol}")
            logger.critical("═" * 70)
            logger.critical(f"   Attempted release: ₹{amount:,.0f} (P&L: ₹{pnl:,.0f})")
            logger.critical(f"   Problem: {symbol} not in deployed_positions (MIS/NRML)")
            logger.critical(f"   Known MIS positions: {list(self.deployed_positions.keys())}")
            logger.critical(f"   Known CNC holdings: {list(self.cnc_holdings.keys())}")
            logger.critical(f"   This indicates STATE DRIFT")
            logger.critical(f"   Action: Release BLOCKED to prevent invariant violation")
            logger.critical("═" * 70)
            
            if self.telegram:
                try:
                    self.telegram.send_message(
                        f"🚨 ILLEGAL RELEASE BLOCKED\n\n"
                        f"Symbol: {symbol}\n"
                        f"Amount: ₹{amount:,.0f}\n"
                        f"P&L: ₹{pnl:,.0f}\n\n"
                        f"Reason: Not in deployed_positions\n\n"
                        f"MIS positions: {list(self.deployed_positions.keys())}\n"
                        f"CNC holdings: {list(self.cnc_holdings.keys())}\n\n"
                        f"⚠️ STATE DRIFT DETECTED"
                    )
                except:
                    pass
            
            return False
        
        # ═══════════════════════════════════════════════════════════════
        # RELEASE OVERFLOW PROTECTION
        # ═══════════════════════════════════════════════════════════════
        pos = self.deployed_positions[symbol]
        actual_deployed = pos.deployed_amount
        if amount > actual_deployed + 1:  # Allow ₹1 tolerance
            logger.warning(f"⚠️ RELEASE OVERFLOW DETECTED: {symbol}")
            logger.warning(f"   Deployed: ₹{actual_deployed:,.0f}")
            logger.warning(f"   Requested: ₹{amount:,.0f}")
            logger.warning(f"   Capping to deployed amount")
            amount = actual_deployed
        
        event = self._log_event(
            CapitalEvent.RELEASE, symbol, amount, pnl, "PHASE3/4",
            f"Position closed, releasing capital"
        )
        
        # Move from deployed to available (with P&L)
        self.deployed_capital = max(0, self.deployed_capital - amount)
        self.available_capital += (amount + pnl)
        self.total_capital += pnl  # P&L affects total
        
        # Update position record
        pos.deployed_amount = max(0, pos.deployed_amount - amount)
        pos.entry_count = max(0, pos.entry_count - 1)
        pos.last_updated = datetime.now().isoformat()
        
        # Remove if fully exited
        if pos.deployed_amount <= 0 and pos.entry_count <= 0:
            del self.deployed_positions[symbol]
            logger.info(f"   ✅ {symbol} fully exited - removed from deployed_positions")
        
        # Update legacy stock_exposures
        if symbol in self.stock_exposures:
            exp = self.stock_exposures[symbol]
            exp.deployed_amount = max(0, exp.deployed_amount - amount)
            exp.entry_count = max(0, exp.entry_count - 1)
            exp.last_updated = datetime.now().isoformat()
            if exp.deployed_amount <= 0:
                del self.stock_exposures[symbol]
        
        self._complete_event(event)
        
        pnl_str = f"+₹{pnl:,.0f}" if pnl >= 0 else f"-₹{abs(pnl):,.0f}"
        logger.info(f"   🔓 Released ₹{amount:,.0f} from {symbol} (P&L: {pnl_str}) "
                   f"(available: ₹{self.available_capital:,.0f})")
        
        self._verify_and_log_invariant(f"release({symbol}, ₹{amount:,.0f}, pnl={pnl_str})")
        
        return True
    
    # ═══════════════════════════════════════════════════════════════════════════════
    # v5.0.0: POSITION ADOPTION (MIS/NRML discovered at broker)
    # ═══════════════════════════════════════════════════════════════════════════════
    
    def adopt_position(self, symbol: str, amount: float, quantity: int = 0, 
                       avg_price: float = 0, product: str = 'MIS',
                       source: PositionSource = PositionSource.BROKER_ADOPTED,
                       gtt_id: str = None) -> bool:
        """
        v5.0.0: Adopt MIS/NRML position discovered at broker.
        
        Called by orchestrator when BrokerSync finds positions not in our state.
        Unlike deploy(), this does NOT require prior reservation.
        
        Args:
            symbol: Stock symbol
            amount: Capital value (qty × avg_price × margin_pct)
            quantity: Number of shares
            avg_price: Average entry price
            product: MIS or NRML (NOT CNC - use add_holding for CNC)
            source: Usually BROKER_ADOPTED or MANUAL
            gtt_id: GTT order ID if exists
            
        Returns:
            True if adoption successful
        """
        if amount <= 0:
            return True
        
        # v5.0.0: Route CNC to add_holding
        if product == 'CNC':
            logger.info(f"   📦 Routing {symbol} to add_holding() (CNC product)")
            return self.add_holding(
                symbol=symbol,
                quantity=quantity,
                avg_price=avg_price,
                source=source
            )
        
        event = self._log_event(
            CapitalEvent.ADOPT_POSITION, symbol, amount, 0, "BROKER_SYNC",
            f"Adopting broker position: {quantity} shares @ ₹{avg_price:.2f} ({product})"
        )
        
        # Check available (defensive)
        if self.available_capital < amount:
            logger.warning(f"   ⚠️ Adopting {symbol}: available ₹{self.available_capital:,.0f} < "
                          f"amount ₹{amount:,.0f}")
            logger.warning(f"   Proceeding anyway - broker is source of truth")
        
        # Adjust capital state (no reservation - direct adoption)
        self.deployed_capital += amount
        self.available_capital = max(0, self.available_capital - amount)
        
        # Create PositionRecord
        if symbol in self.deployed_positions:
            pos = self.deployed_positions[symbol]
            pos.quantity = quantity  # Broker is truth
            pos.avg_price = avg_price
            pos.deployed_amount = amount
            pos.last_updated = datetime.now().isoformat()
            pos.source = source
            if gtt_id:
                pos.gtt_id = gtt_id
        else:
            self.deployed_positions[symbol] = PositionRecord(
                symbol=symbol,
                quantity=quantity,
                avg_price=avg_price,
                deployed_amount=amount,
                product=product,
                source=source,
                phase4_mode=Phase4Mode.ACTIVE_CONTROL,
                gtt_id=gtt_id,
                entry_count=1
            )
        
        # Update legacy stock_exposures
        self.stock_exposures[symbol] = StockExposure(
            symbol=symbol,
            deployed_amount=amount,
            entry_count=1,
            avg_entry_price=avg_price,
            last_updated=datetime.now().isoformat()
        )
        
        self._complete_event(event)
        
        logger.info(f"   📡 ADOPTED Position: {symbol} - {quantity} @ ₹{avg_price:.2f} "
                   f"(₹{amount:,.0f}, {product}, source={source.value if isinstance(source, PositionSource) else source})")
        
        self._verify_and_log_invariant(f"adopt_position({symbol}, ₹{amount:,.0f})")
        
        return True
    
    # Legacy compatibility
    def adopt_deployed_capital(self, symbol: str, amount: float, quantity: int = 0, 
                                avg_price: float = 0):
        """Legacy: Adopt position (now routes to adopt_position with product detection)"""
        # Default to MIS for legacy calls
        return self.adopt_position(
            symbol=symbol,
            amount=amount,
            quantity=quantity,
            avg_price=avg_price,
            product='MIS',
            source=PositionSource.BROKER_ADOPTED
        )
    
    # ═══════════════════════════════════════════════════════════════════════════════
    # v5.0.0: CNC HOLDING MANAGEMENT (Phase 4 OBSERVE_ONLY)
    # ═══════════════════════════════════════════════════════════════════════════════
    
    def add_holding(self, symbol: str, quantity: int, avg_price: float,
                    quantity_settled: int = None, quantity_t1: int = None,
                    source: PositionSource = PositionSource.BROKER_ADOPTED,
                    isin: str = "", collateral_quantity: int = 0) -> bool:
        """
        v5.0.0: Add or update CNC holding.
        
        CNC holdings are INVENTORY - they do NOT consume deployed_capital.
        Phase 4 monitors them in OBSERVE_ONLY mode (P&L display only).
        
        Args:
            symbol: Stock symbol
            quantity: Total quantity (settled + T1)
            avg_price: Average price
            quantity_settled: Settled shares (can sell)
            quantity_t1: T+1 pending (can't sell yet)
            source: Where this holding came from
            isin: ISIN code
            collateral_quantity: Collateral shares
            
        Returns:
            True if holding added/updated
        """
        if quantity <= 0:
            logger.debug(f"   Skipping {symbol} holding with qty={quantity}")
            return True
        
        # Default settlement split
        if quantity_settled is None:
            quantity_settled = quantity
        if quantity_t1 is None:
            quantity_t1 = 0
        
        event = self._log_event(
            CapitalEvent.ADOPT_HOLDING, symbol, 0, 0, "BROKER_SYNC",
            f"Adding CNC holding: {quantity} shares ({quantity_settled} settled, {quantity_t1} T+1)"
        )
        
        # Create or update HoldingRecord
        if symbol in self.cnc_holdings:
            hold = self.cnc_holdings[symbol]
            hold.quantity = quantity
            hold.quantity_settled = quantity_settled
            hold.quantity_t1 = quantity_t1
            hold.avg_price = avg_price
            hold.last_updated = datetime.now().isoformat()
            hold.source = source
        else:
            self.cnc_holdings[symbol] = HoldingRecord(
                symbol=symbol,
                quantity=quantity,
                quantity_settled=quantity_settled,
                quantity_t1=quantity_t1,
                avg_price=avg_price,
                source=source,
                phase4_mode=Phase4Mode.OBSERVE_ONLY,
                isin=isin,
                collateral_quantity=collateral_quantity
            )
        
        self._complete_event(event)
        
        t1_note = f" ({quantity_t1} T+1 pending)" if quantity_t1 > 0 else ""
        logger.info(f"   📦 CNC Holding: {symbol} - {quantity} @ ₹{avg_price:.2f}{t1_note} "
                   f"(OBSERVE_ONLY mode)")
        
        return True
    
    def update_holding(self, symbol: str, quantity: int = None, 
                       quantity_settled: int = None, quantity_t1: int = None) -> bool:
        """
        v5.0.0: Update CNC holding quantities.
        
        Called when T+1 settles or partial quantities change.
        """
        if symbol not in self.cnc_holdings:
            logger.warning(f"   ⚠️ Cannot update unknown holding: {symbol}")
            return False
        
        hold = self.cnc_holdings[symbol]
        
        event = self._log_event(
            CapitalEvent.HOLDING_UPDATE, symbol, 0, 0, "BROKER_SYNC",
            f"Updating holding: qty={quantity}, settled={quantity_settled}, t1={quantity_t1}"
        )
        
        if quantity is not None:
            hold.quantity = quantity
        if quantity_settled is not None:
            hold.quantity_settled = quantity_settled
        if quantity_t1 is not None:
            hold.quantity_t1 = quantity_t1
        
        hold.last_updated = datetime.now().isoformat()
        
        self._complete_event(event)
        
        logger.info(f"   📦 Updated holding: {symbol} - {hold.quantity} "
                   f"({hold.quantity_settled} settled, {hold.quantity_t1} T+1)")
        
        return True
    
    def remove_holding(self, symbol: str) -> bool:
        """
        v5.0.0: Remove CNC holding (sold externally or transferred).
        
        NOTE: This does NOT affect capital state (CNC holdings aren't in deployed_capital).
        """
        if symbol not in self.cnc_holdings:
            logger.debug(f"   {symbol} not in cnc_holdings - nothing to remove")
            return True
        
        event = self._log_event(
            CapitalEvent.HOLDING_UPDATE, symbol, 0, 0, "BROKER_SYNC",
            f"Removing CNC holding (sold/transferred)"
        )
        
        del self.cnc_holdings[symbol]
        
        self._complete_event(event)
        
        logger.info(f"   📦 Removed CNC holding: {symbol}")
        
        return True
    
    # ═══════════════════════════════════════════════════════════════════════════════
    # v5.0.0: GTT MANAGEMENT
    # ═══════════════════════════════════════════════════════════════════════════════
    
    def set_gtt_id(self, symbol: str, gtt_id: str) -> bool:
        """v5.0.0: Set GTT order ID for a position"""
        if symbol not in self.deployed_positions:
            logger.warning(f"   ⚠️ Cannot set GTT for unknown position: {symbol}")
            return False
        
        self.deployed_positions[symbol].gtt_id = gtt_id
        self.deployed_positions[symbol].last_updated = datetime.now().isoformat()
        
        logger.info(f"   🎯 GTT set for {symbol}: {gtt_id}")
        return True
    
    def get_gtt_id(self, symbol: str) -> Optional[str]:
        """v5.0.0: Get GTT order ID for a position"""
        pos = self.deployed_positions.get(symbol)
        return pos.gtt_id if pos else None
    
    def clear_gtt_id(self, symbol: str) -> bool:
        """v5.0.0: Clear GTT order ID (GTT executed or cancelled)"""
        if symbol not in self.deployed_positions:
            return True
        
        self.deployed_positions[symbol].gtt_id = None
        self.deployed_positions[symbol].last_updated = datetime.now().isoformat()
        
        logger.info(f"   🎯 GTT cleared for {symbol}")
        return True
    
    # ═══════════════════════════════════════════════════════════════════════════════
    # UTILITY METHODS
    # ═══════════════════════════════════════════════════════════════════════════════
    
    def log_status(self):
        """Log current capital status"""
        logger.info("─" * 60)
        logger.info("💰 CAPITAL STATUS (v5.0.0 SSOT)")
        logger.info("─" * 60)
        logger.info(f"   Total:     ₹{self.total_capital:>12,.0f}")
        logger.info(f"   Deployed:  ₹{self.deployed_capital:>12,.0f} (MIS/NRML only)")
        logger.info(f"   Reserved:  ₹{self.reserved_capital:>12,.0f}")
        logger.info(f"   Available: ₹{self.available_capital:>12,.0f}")
        logger.info(f"   Usable:    ₹{self.get_available():>12,.0f} (after buffer)")
        logger.info(f"   Exposure:  {self.get_total_exposure_pct():>11.1f}%")
        
        if self.deployed_positions:
            logger.info(f"   ─ MIS/NRML Positions ({len(self.deployed_positions)}):")
            for symbol, pos in self.deployed_positions.items():
                pct = self.get_stock_exposure_pct(symbol)
                src = pos.source.value if isinstance(pos.source, PositionSource) else pos.source
                logger.info(f"      • {symbol}: {pos.quantity} @ ₹{pos.avg_price:.2f} "
                           f"(₹{pos.deployed_amount:,.0f}, {pct:.1f}%, {src})")
        
        if self.cnc_holdings:
            logger.info(f"   ─ CNC Holdings ({len(self.cnc_holdings)}) [OBSERVE_ONLY]:")
            for symbol, hold in self.cnc_holdings.items():
                t1_note = f" ({hold.quantity_t1} T+1)" if hold.quantity_t1 > 0 else ""
                src = hold.source.value if isinstance(hold.source, PositionSource) else hold.source
                logger.info(f"      • {symbol}: {hold.quantity} @ ₹{hold.avg_price:.2f}{t1_note} ({src})")
        
        # Show invariant status
        ok, msg = self.check_invariant()
        logger.info(f"   Invariant: {'✅ OK' if ok else f'❌ {msg}'}")
        
        logger.info("─" * 60)
    
    def get_summary_for_phase4(self) -> Dict[str, Any]:
        """
        v5.0.0: Get summary for Phase 4 initialization.
        
        Returns positions with their control modes.
        """
        return {
            'mis_positions': {
                symbol: {
                    **pos.to_dict(),
                    'phase4_mode': 'ACTIVE_CONTROL'
                }
                for symbol, pos in self.deployed_positions.items()
            },
            'cnc_holdings': {
                symbol: {
                    **hold.to_dict(),
                    'phase4_mode': 'OBSERVE_ONLY'
                }
                for symbol, hold in self.cnc_holdings.items()
            },
            'capital': {
                'total': self.total_capital,
                'deployed': self.deployed_capital,
                'available': self.available_capital,
                'reserved': self.reserved_capital
            }
        }
    
    def reset(self):
        """Reset capital manager state (for testing)"""
        self.total_capital = 0.0
        self.available_capital = 0.0
        self.deployed_capital = 0.0
        self.reserved_capital = 0.0
        self.deployed_positions.clear()
        self.cnc_holdings.clear()
        self.stock_exposures.clear()
        self.event_log.clear()
        self.last_sync_ts = 0
        self.initialized = False
        self.capital_broken = False
        logger.info("   ⚠️ Capital Manager reset")


# ═══════════════════════════════════════════════════════════════════════════════
# STANDALONE TESTING
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    print("=" * 70)
    print("CAPITAL MANAGER v5.0.0 - SSOT Architecture Test")
    print("=" * 70)
    
    # Mock config
    class MockConfig:
        CAPITAL_MANAGEMENT = {
            'MAX_CONCENTRATION_PCT': 0.25,
            'ABSOLUTE_MAX_ENTRIES': 3,
            'MIN_CAPITAL_BUFFER': 10000,
            'ENABLE_ADAPTIVE_LIMITS': True,
        }
        MAX_LOTS_PER_STOCK = 2
        TOTAL_CAPITAL = 200000
    
    # Mock kite
    class MockKite:
        def margins(self, segment='equity'):
            return {'equity': {'available': {'live_balance': 200000, 'cash': 200000}}}
        
        def positions(self):
            return {'net': []}
        
        def holdings(self):
            return []
    
    # Initialize
    cm = CapitalManager(MockKite(), MockConfig())
    cm.sync_with_broker()
    
    print(f"\n✅ Initial State:")
    print(f"   Available: ₹{cm.get_available():,.0f}")
    
    # Test MIS position deployment
    print("\n" + "=" * 70)
    print("Test 1: Deploy MIS Position (POLICYBZR)")
    print("=" * 70)
    
    cm.reserve('POLICYBZR', 5454)
    cm.deploy(
        symbol='POLICYBZR',
        amount=5454,
        quantity=18,
        avg_price=1516.00,
        source=PositionSource.PHASE5_GAP,
        product='MIS',
        gtt_id='305747696'
    )
    
    print(f"   is_deployed('POLICYBZR'): {cm.is_deployed('POLICYBZR')}")
    print(f"   is_holding('POLICYBZR'): {cm.is_holding('POLICYBZR')}")
    print(f"   get_phase4_mode('POLICYBZR'): {cm.get_phase4_mode('POLICYBZR')}")
    
    # Test CNC holding
    print("\n" + "=" * 70)
    print("Test 2: Add CNC Holding (ADANIPORTS)")
    print("=" * 70)
    
    cm.add_holding(
        symbol='ADANIPORTS',
        quantity=1,
        avg_price=1564.80,
        quantity_settled=0,
        quantity_t1=1,
        source=PositionSource.MANUAL
    )
    
    print(f"   is_deployed('ADANIPORTS'): {cm.is_deployed('ADANIPORTS')}")
    print(f"   is_holding('ADANIPORTS'): {cm.is_holding('ADANIPORTS')}")
    print(f"   get_phase4_mode('ADANIPORTS'): {cm.get_phase4_mode('ADANIPORTS')}")
    
    # Log status
    print("\n" + "=" * 70)
    print("Full Status:")
    print("=" * 70)
    cm.log_status()
    
    # Test illegal release on CNC
    print("\n" + "=" * 70)
    print("Test 3: Release on CNC holding (should be no-op)")
    print("=" * 70)
    result = cm.release('ADANIPORTS', 1564.80, pnl=50)
    print(f"   release() result: {result} (True = no-op for CNC)")
    
    # Test illegal release on unknown symbol
    print("\n" + "=" * 70)
    print("Test 4: Illegal release on unknown symbol (should be blocked)")
    print("=" * 70)
    result = cm.release('UNKNOWN', 10000, pnl=500)
    print(f"   release() result: {result} (False = blocked)")
    
    # Test proper release
    print("\n" + "=" * 70)
    print("Test 5: Proper release of MIS position")
    print("=" * 70)
    result = cm.release('POLICYBZR', 5454, pnl=-34)
    print(f"   release() result: {result}")
    print(f"   is_deployed('POLICYBZR'): {cm.is_deployed('POLICYBZR')}")
    
    # Show Phase 4 summary
    print("\n" + "=" * 70)
    print("Phase 4 Summary:")
    print("=" * 70)
    summary = cm.get_summary_for_phase4()
    print(f"   MIS positions: {list(summary['mis_positions'].keys())}")
    print(f"   CNC holdings: {list(summary['cnc_holdings'].keys())}")
    print(f"   Capital: {summary['capital']}")
    
    # Show event log
    print("\n" + "=" * 70)
    print("Recent Events:")
    print("=" * 70)
    for event in cm.get_recent_events(10):
        print(f"   {event['timestamp'][:19]} | {event['type']:15} | {event['symbol']:12} | {event['details'][:40]}")
    
    print("\n✅ Capital Manager v5.0.0 SSOT test complete")
