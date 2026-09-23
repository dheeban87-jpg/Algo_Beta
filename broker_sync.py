"""
BROKER_SYNC.PY v3.0.0 - OBSERVER-ONLY Broker Communication
═══════════════════════════════════════════════════════════════════════════════

v3.0.0 (2026-02-06): OBSERVER-ONLY PATTERN (SSOT Architecture)
─────────────────────────────────────────────────────────────────
CRITICAL CHANGE: BrokerSync now OBSERVES ONLY, never modifies state.

OLD BEHAVIOR (v2.x):
- reconcile() returned new/closed positions
- Caller added positions directly to Phase 4
- Led to STATE DRIFT when CNC holdings treated as MIS positions

NEW BEHAVIOR (v3.0.0):
- reconcile_with_capital_manager() returns CATEGORIZED deltas
- ORCHESTRATOR decides what to do with deltas
- BrokerSync NEVER modifies Phase 4 or CapitalManager directly

Author: Trading System v3.0.0
Date: 2026-02-06
"""

import logging
import json
from typing import Dict, List, Optional, TYPE_CHECKING, Any
from datetime import datetime
from dataclasses import dataclass, field

if TYPE_CHECKING:
    from capital_manager_v5_0_0 import CapitalManager

try:
    from unified_data_manager import get_db
    DATABASE_AVAILABLE = True
except ImportError:
    DATABASE_AVAILABLE = False
    get_db = None

logger = logging.getLogger('BrokerSync')


# ═══════════════════════════════════════════════════════════════════════════════
# DATA STRUCTURES
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class BrokerPosition:
    """Standardized position format from broker"""
    symbol: str
    exchange: str
    quantity: int
    quantity_settled: int
    quantity_t1: int
    average_price: float
    last_price: float
    pnl: float
    pnl_pct: float
    product: str                   # CNC / MIS / NRML
    source: str                    # HOLDINGS / POSITIONS
    direction: str                 # LONG / SHORT
    instrument_token: int
    tradingsymbol: str
    isin: str = ""
    collateral_quantity: int = 0
    
    def to_dict(self) -> Dict:
        return {
            'symbol': self.symbol, 'exchange': self.exchange,
            'quantity': self.quantity, 'quantity_settled': self.quantity_settled,
            'quantity_t1': self.quantity_t1, 'average_price': self.average_price,
            'last_price': self.last_price, 'pnl': self.pnl, 'pnl_pct': self.pnl_pct,
            'product': self.product, 'source': self.source, 'direction': self.direction,
            'instrument_token': self.instrument_token, 'tradingsymbol': self.tradingsymbol,
            'isin': self.isin, 'collateral_quantity': self.collateral_quantity
        }
    
    def is_mis_or_nrml(self) -> bool:
        return self.product in ('MIS', 'NRML')
    
    def is_cnc(self) -> bool:
        return self.product == 'CNC'


@dataclass
class ReconcileResult:
    """Legacy result - use SSOTReconcileResult for v3.0.0"""
    new_positions: Dict[str, BrokerPosition] = field(default_factory=dict)
    closed_positions: List[str] = field(default_factory=list)
    matched_positions: Dict[str, BrokerPosition] = field(default_factory=dict)
    broker_positions: Dict[str, BrokerPosition] = field(default_factory=dict)
    sync_time: datetime = field(default_factory=datetime.now)


@dataclass
class SSOTReconcileResult:
    """
    v3.0.0: SSOT-aware reconciliation result.
    Separates MIS/NRML positions from CNC holdings.
    """
    # MIS/NRML - Phase 4 ACTIVE_CONTROL eligible
    new_mis_positions: Dict[str, BrokerPosition] = field(default_factory=dict)
    closed_mis_positions: List[str] = field(default_factory=list)
    matched_mis_positions: Dict[str, BrokerPosition] = field(default_factory=dict)
    
    # CNC - Phase 4 OBSERVE_ONLY mode
    new_cnc_holdings: Dict[str, BrokerPosition] = field(default_factory=dict)
    closed_cnc_holdings: List[str] = field(default_factory=list)
    matched_cnc_holdings: Dict[str, BrokerPosition] = field(default_factory=dict)
    
    # Combined broker data
    all_broker_mis: Dict[str, BrokerPosition] = field(default_factory=dict)
    all_broker_cnc: Dict[str, BrokerPosition] = field(default_factory=dict)
    
    sync_time: datetime = field(default_factory=datetime.now)
    
    def has_changes(self) -> bool:
        return (len(self.new_mis_positions) > 0 or len(self.closed_mis_positions) > 0 or
                len(self.new_cnc_holdings) > 0 or len(self.closed_cnc_holdings) > 0)
    
    def summary(self) -> str:
        return (f"MIS: +{len(self.new_mis_positions)} -{len(self.closed_mis_positions)} "
                f"={len(self.matched_mis_positions)} | "
                f"CNC: +{len(self.new_cnc_holdings)} -{len(self.closed_cnc_holdings)} "
                f"={len(self.matched_cnc_holdings)}")


# ═══════════════════════════════════════════════════════════════════════════════
# BROKER SYNC MANAGER
# ═══════════════════════════════════════════════════════════════════════════════

class BrokerSyncManager:
    """
    v3.0.0: OBSERVER-ONLY Broker Communication Manager
    
    This class OBSERVES and REPORTS - never modifies state.
    Orchestrator decides what to do with reported deltas.
    """
    
    def __init__(self, kite, telegram=None, config=None):
        self.kite = kite
        self.telegram = telegram
        self.config = config
        
        self._db = None
        self._init_database()
        
        self._last_sync_time = None
        self._cached_positions = {}
        self._cache_ttl_seconds = 5
        self._last_fetch_ok = True   # v5.3.5: Track API fetch reliability
        
        logger.info("=" * 60)
        logger.info("📡 BROKER SYNC MANAGER v3.0.0 - OBSERVER-ONLY")
        logger.info("=" * 60)
        logger.info("   ✅ OBSERVER-ONLY: Reports deltas, never modifies state")
        logger.info("   ✅ SSOT Support: Separates MIS/NRML from CNC holdings")
        if self._db:
            logger.info("   ✅ Database: SQLite snapshots enabled")
        logger.info("=" * 60)
    
    def _init_database(self):
        if DATABASE_AVAILABLE:
            try:
                self._db = get_db()
            except Exception as e:
                logger.warning(f"⚠️ Database not available: {e}")
                self._db = None
    
    def _save_snapshot_to_db(self, positions: Dict[str, BrokerPosition]):
        if not self._db:
            return
        try:
            total_value = sum(p.last_price * p.quantity for p in positions.values())
            total_pnl = sum(p.pnl for p in positions.values())
            try:
                margins = self.kite.margins()
                equity_margin = margins.get('equity', {})
                available_cash = equity_margin.get('available', {}).get('cash', 0)
                used_margin = equity_margin.get('utilised', {}).get('debits', 0)
            except:
                available_cash = 0
                used_margin = 0
            positions_list = [p.to_dict() for p in positions.values()]
            self._db.save_broker_snapshot(
                available_cash=available_cash,
                used_margin=used_margin,
                positions=positions_list
            )
        except Exception as e:
            logger.debug(f"   ⚠️ Snapshot save failed: {e}")
    
    # ═══════════════════════════════════════════════════════════════════════════
    # POSITION FETCHING
    # ═══════════════════════════════════════════════════════════════════════════
    
    def get_all_positions(self, use_cache: bool = False, save_snapshot: bool = True) -> Dict[str, BrokerPosition]:
        """Get ALL positions from broker (MIS + NRML + CNC).

        Also sets self._last_fetch_ok to indicate if ALL API calls succeeded.
        If any fetch failed (timeout/error), _last_fetch_ok = False and
        reconciliation should be SKIPPED to prevent false closes.
        """
        if use_cache and self._is_cache_valid():
            return self._cached_positions

        logger.debug("🔄 Fetching all positions from broker...")  # v5.8.0: debug level

        all_positions = {}

        # Fetch intraday (MIS/NRML)
        intraday, intraday_ok = self._fetch_intraday_positions()
        all_positions.update(intraday)

        # Fetch CNC holdings
        holdings, holdings_ok = self._fetch_holdings()
        for symbol, pos in holdings.items():
            if symbol not in all_positions:
                all_positions[symbol] = pos

        # Track whether ALL fetches succeeded
        self._last_fetch_ok = intraday_ok and holdings_ok
        if not self._last_fetch_ok:
            logger.warning("   ⚠️ FETCH INCOMPLETE — one or more API calls failed/timed out")

        self._cached_positions = all_positions
        self._last_sync_time = datetime.now()

        if save_snapshot and all_positions:
            self._save_snapshot_to_db(all_positions)

        self._log_positions_summary(all_positions)

        return all_positions
    
    def get_mis_positions_only(self) -> Dict[str, BrokerPosition]:
        """v3.0.0: Get only MIS/NRML positions"""
        all_pos = self.get_all_positions(use_cache=True, save_snapshot=False)
        return {s: p for s, p in all_pos.items() if p.is_mis_or_nrml()}
    
    def get_cnc_holdings_only(self) -> Dict[str, BrokerPosition]:
        """v3.0.0: Get only CNC holdings"""
        all_pos = self.get_all_positions(use_cache=True, save_snapshot=False)
        return {s: p for s, p in all_pos.items() if p.is_cnc()}
    
    def get_holdings_only(self) -> Dict[str, BrokerPosition]:
        """Legacy: Get CNC holdings"""
        holdings, _ = self._fetch_holdings()
        return holdings

    def get_intraday_only(self) -> Dict[str, BrokerPosition]:
        """Legacy: Get intraday positions"""
        positions, _ = self._fetch_intraday_positions()
        return positions
    
    # ═══════════════════════════════════════════════════════════════════════════
    # INTERNAL FETCH METHODS
    # ═══════════════════════════════════════════════════════════════════════════
    
    def _fetch_intraday_positions(self) -> tuple:
        """
        Fetch MIS/NRML positions from kite.positions().

        Returns:
            tuple: (positions_dict, fetch_ok_bool)
            - positions_dict: Dict of BrokerPosition objects
            - fetch_ok: True if API call succeeded, False if it failed/timed out
        """
        positions = {}
        try:
            broker_positions = self.kite.positions()
            net_positions = broker_positions.get('net', [])

            for pos in net_positions:
                qty = pos.get('quantity', 0)
                product = pos.get('product', 'MIS')

                # Skip zero-qty and CNC negative (completed sells)
                if qty != 0 and not (product == 'CNC' and qty < 0):
                    symbol = pos.get('tradingsymbol')
                    avg_price = pos.get('average_price', 0)
                    last_price = pos.get('last_price', 0)
                    pnl = pos.get('pnl', 0)
                    pnl_pct = ((last_price - avg_price) / avg_price * 100) if avg_price > 0 else 0

                    positions[symbol] = BrokerPosition(
                        symbol=symbol,
                        exchange=pos.get('exchange', 'NSE'),
                        quantity=abs(qty),
                        quantity_settled=abs(qty),
                        quantity_t1=0,
                        average_price=avg_price,
                        last_price=last_price,
                        pnl=pnl,
                        pnl_pct=pnl_pct,
                        product=product,
                        source='POSITIONS',
                        direction='LONG' if qty > 0 else 'SHORT',
                        instrument_token=pos.get('instrument_token', 0),
                        tradingsymbol=symbol
                    )

            if positions:
                logger.info(f"   📊 Positions (MIS/NRML): {len(positions)} found")

            return positions, True

        except Exception as e:
            logger.warning(f"   ⚠️ Could not fetch positions: {e}")
            return positions, False
    
    def _fetch_holdings(self) -> tuple:
        """
        Fetch CNC holdings from kite.holdings().

        Returns:
            tuple: (holdings_dict, fetch_ok_bool)
            - holdings_dict: Dict of BrokerPosition objects
            - fetch_ok: True if API call succeeded, False if it failed/timed out
        """
        holdings = {}
        try:
            broker_holdings = self.kite.holdings()
            zero_qty_symbols = []

            for holding in broker_holdings:
                qty = holding.get('quantity', 0)
                t1_qty = holding.get('t1_quantity', 0)
                total_qty = qty + t1_qty

                if total_qty > 0:
                    symbol = holding.get('tradingsymbol')
                    avg_price = holding.get('average_price', 0)
                    last_price = holding.get('last_price', 0)
                    pnl = holding.get('pnl', 0)
                    pnl_pct = ((last_price - avg_price) / avg_price * 100) if avg_price > 0 else 0

                    holdings[symbol] = BrokerPosition(
                        symbol=symbol,
                        exchange=holding.get('exchange', 'NSE'),
                        quantity=total_qty,
                        quantity_settled=qty,
                        quantity_t1=t1_qty,
                        average_price=avg_price,
                        last_price=last_price,
                        pnl=pnl,
                        pnl_pct=pnl_pct,
                        product='CNC',
                        source='HOLDINGS',
                        direction='LONG',
                        instrument_token=holding.get('instrument_token', 0),
                        tradingsymbol=symbol,
                        isin=holding.get('isin', ''),
                        collateral_quantity=holding.get('collateral_quantity', 0)
                    )

                    if t1_qty > 0:
                        logger.info(f"   📦 {symbol}: {qty} settled + {t1_qty} T+1 pending")
                else:
                    symbol = holding.get('tradingsymbol')
                    if symbol:
                        zero_qty_symbols.append(symbol)

            if holdings:
                logger.info(f"   📦 Holdings (CNC): {len(holdings)} found")
            if zero_qty_symbols:
                logger.debug(f"   ℹ️ Skipped {len(zero_qty_symbols)} zero-qty holdings")

            return holdings, True

        except Exception as e:
            logger.warning(f"   ⚠️ Could not fetch holdings: {e}")
            return holdings, False
    
    # ═══════════════════════════════════════════════════════════════════════════
    # v3.0.0: SSOT-AWARE RECONCILIATION (Observer Only)
    # ═══════════════════════════════════════════════════════════════════════════
    
    def reconcile_with_capital_manager(self, capital_manager: Any) -> SSOTReconcileResult:
        """
        v3.0.0: SSOT-aware reconciliation - OBSERVER ONLY.
        
        Compares broker state with CapitalManager and returns CATEGORIZED deltas.
        DOES NOT modify any state - orchestrator decides what to do.
        
        Args:
            capital_manager: CapitalManager v5.0.0 instance
            
        Returns:
            SSOTReconcileResult with categorized deltas
        """
        # v5.8.0: Fetch first, then log only if there's something to report
        all_broker = self.get_all_positions(use_cache=False, save_snapshot=True)

        # v5.3.5 CRITICAL FIX: If ANY API call failed/timed out, do NOT reconcile.
        if not self._last_fetch_ok:
            logger.warning("   🛑 RECONCILIATION SKIPPED — API fetch was incomplete/timed out")
            return SSOTReconcileResult()

        # v5.8.0: If both broker and system are empty, skip silently
        cm_has_positions = bool(capital_manager.get_all_deployed_symbols()) or \
                           bool(capital_manager.get_all_holding_symbols())
        if not all_broker and not cm_has_positions:
            return SSOTReconcileResult()

        result = SSOTReconcileResult()
        result.sync_time = datetime.now()
        
        # Separate broker data by product type
        broker_mis = {s: p for s, p in all_broker.items() if p.is_mis_or_nrml()}
        broker_cnc = {s: p for s, p in all_broker.items() if p.is_cnc()}
        
        result.all_broker_mis = broker_mis
        result.all_broker_cnc = broker_cnc
        
        # Get current CapitalManager state
        # v5.2.1 FIX: Split deployed_positions by ACTUAL product type
        # Phase 3 places CNC orders into deployed_positions{} with product='CNC'
        # These must be matched against broker_cnc, NOT broker_mis
        cm_deployed_mis_symbols = set()
        cm_deployed_cnc_symbols = set()
        for sym in capital_manager.get_all_deployed_symbols():
            pos_record = capital_manager.get_position_record(sym)
            if pos_record and pos_record.product == 'CNC':
                cm_deployed_cnc_symbols.add(sym)
            else:
                cm_deployed_mis_symbols.add(sym)
        
        cm_holding_cnc_symbols = set(capital_manager.get_all_holding_symbols())
        
        # Combine: CNC symbols from deployed_positions + cnc_holdings
        cm_all_cnc_symbols = cm_deployed_cnc_symbols | cm_holding_cnc_symbols
        
        broker_mis_symbols = set(broker_mis.keys())
        broker_cnc_symbols = set(broker_cnc.keys())
        
        if cm_deployed_cnc_symbols:
            logger.info(f"   📦 System CNC in deployed_positions: {cm_deployed_cnc_symbols}")
        
        # ═══════════════════════════════════════════════════════════════
        # MIS/NRML RECONCILIATION (only MIS-product deployed positions)
        # ═══════════════════════════════════════════════════════════════
        
        # NEW MIS: At broker but not in CapitalManager.deployed_positions
        new_mis = broker_mis_symbols - cm_deployed_mis_symbols
        for symbol in new_mis:
            result.new_mis_positions[symbol] = broker_mis[symbol]
            logger.info(f"   ➕ NEW MIS: {symbol} (at broker, not in deployed_positions)")
        
        # CLOSED MIS: In CapitalManager but not at broker
        closed_mis = cm_deployed_mis_symbols - broker_mis_symbols
        for symbol in closed_mis:
            result.closed_mis_positions.append(symbol)
            logger.warning(f"   ➖ CLOSED MIS: {symbol} (tracked, not at broker)")
        
        # MATCHED MIS: In both
        matched_mis = cm_deployed_mis_symbols & broker_mis_symbols
        for symbol in matched_mis:
            result.matched_mis_positions[symbol] = broker_mis[symbol]
        
        # ═══════════════════════════════════════════════════════════════
        # CNC HOLDINGS RECONCILIATION (cnc_holdings + CNC-product deployed)
        # ═══════════════════════════════════════════════════════════════
        
        # NEW CNC: At broker but not tracked anywhere
        new_cnc = broker_cnc_symbols - cm_all_cnc_symbols
        for symbol in new_cnc:
            result.new_cnc_holdings[symbol] = broker_cnc[symbol]
            t1 = broker_cnc[symbol].quantity_t1
            t1_note = f" ({t1} T+1 pending)" if t1 > 0 else ""
            logger.info(f"   ➕ NEW CNC: {symbol}{t1_note} (at broker, not in cnc_holdings)")
        
        # CLOSED CNC: In cnc_holdings but not at broker
        closed_cnc = cm_holding_cnc_symbols - broker_cnc_symbols
        for symbol in closed_cnc:
            result.closed_cnc_holdings.append(symbol)
            logger.warning(f"   ➖ CLOSED CNC: {symbol} (tracked, not at broker)")
        
        # v5.2.1: System CNC positions (in deployed_positions with product=CNC)
        # These are MATCHED if broker confirms them — do NOT flag as new or closed
        matched_system_cnc = cm_deployed_cnc_symbols & broker_cnc_symbols
        for symbol in matched_system_cnc:
            result.matched_cnc_holdings[symbol] = broker_cnc[symbol]
            logger.info(f"   ✅ MATCHED SYSTEM CNC: {symbol} (deployed + confirmed at broker)")
        
        # CLOSED SYSTEM CNC: In deployed_positions as CNC but not at broker
        closed_system_cnc = cm_deployed_cnc_symbols - broker_cnc_symbols
        for symbol in closed_system_cnc:
            result.closed_mis_positions.append(symbol)  # Route through MIS close path to release capital
            logger.warning(f"   ➖ CLOSED SYSTEM CNC: {symbol} (deployed CNC, not at broker)")
        
        # MATCHED CNC holdings: In both cnc_holdings and broker
        matched_cnc = cm_holding_cnc_symbols & broker_cnc_symbols
        for symbol in matched_cnc:
            result.matched_cnc_holdings[symbol] = broker_cnc[symbol]
        
        # Summary
        logger.info(f"   📊 SSOT Reconcile: {result.summary()}")
        
        # Log to database
        if self._db and result.has_changes():
            try:
                self._db.log_event(
                    event_type='SSOT_RECONCILE',
                    category='broker_sync',
                    details={
                        'new_mis': list(result.new_mis_positions.keys()),
                        'closed_mis': result.closed_mis_positions,
                        'new_cnc': list(result.new_cnc_holdings.keys()),
                        'closed_cnc': result.closed_cnc_holdings
                    },
                    severity='INFO' if not result.closed_mis_positions else 'WARNING'
                )
            except:
                pass
        
        return result
    
    # Legacy reconcile for backward compatibility
    def reconcile(self, tracked_positions: Dict[str, Dict]) -> ReconcileResult:
        """
        Legacy reconcile method - use reconcile_with_capital_manager() for v3.0.0
        """
        logger.info("🔄 Legacy Reconciling with broker...")

        broker_positions = self.get_all_positions(use_cache=False)

        # v5.3.5 CRITICAL FIX: Skip reconciliation if API fetch failed
        if not self._last_fetch_ok:
            logger.warning("   🛑 LEGACY RECONCILIATION SKIPPED — API fetch was incomplete/timed out")
            return ReconcileResult()

        result = ReconcileResult()
        result.broker_positions = broker_positions
        result.sync_time = datetime.now()
        
        tracked_symbols = set(tracked_positions.keys())
        broker_symbols = set(broker_positions.keys())
        
        # NEW: At broker but not tracked
        for symbol in (broker_symbols - tracked_symbols):
            result.new_positions[symbol] = broker_positions[symbol]
            logger.info(f"   ➕ NEW: {symbol} (at broker, not tracked)")
            if self._db:
                try:
                    self._db.log_event(
                        event_type='POSITION_DISCOVERED',
                        category='broker_sync',
                        details={'symbol': symbol, 'action': 'new_position'},
                        severity='WARNING'
                    )
                except:
                    pass
        
        # CLOSED: Tracked but not at broker
        for symbol in (tracked_symbols - broker_symbols):
            result.closed_positions.append(symbol)
            logger.warning(f"   ➖ CLOSED: {symbol} (tracked, not at broker)")
            if self._db:
                try:
                    self._db.log_event(
                        event_type='POSITION_CLOSED_EXTERNALLY',
                        category='broker_sync',
                        details={'symbol': symbol, 'action': 'external_close'},
                        severity='WARNING'
                    )
                except:
                    pass
        
        # MATCHED: In both
        for symbol in (tracked_symbols & broker_symbols):
            result.matched_positions[symbol] = broker_positions[symbol]
        
        logger.info(f"   📊 Reconcile: +{len(result.new_positions)} -{len(result.closed_positions)} ={len(result.matched_positions)}")
        
        return result
    
    # ═══════════════════════════════════════════════════════════════════════════
    # HELPER METHODS
    # ═══════════════════════════════════════════════════════════════════════════
    
    def _is_cache_valid(self) -> bool:
        if not self._last_sync_time or not self._cached_positions:
            return False
        age = (datetime.now() - self._last_sync_time).total_seconds()
        return age < self._cache_ttl_seconds
    
    def _log_positions_summary(self, positions: Dict[str, BrokerPosition]):
        if not positions:
            logger.debug("   📭 No positions at broker")  # v5.8.0: debug when empty
            return
        
        logger.info(f"   📊 Total broker positions: {len(positions)}")
        
        for symbol, pos in positions.items():
            source_emoji = "📊" if pos.source == 'POSITIONS' else "📦"
            pnl_emoji = "🟢" if pos.pnl > 0 else "🔴" if pos.pnl < 0 else "⚪"
            t1_note = f" (T+1: {pos.quantity_t1})" if pos.quantity_t1 > 0 else ""
            
            logger.info(
                f"      {source_emoji} {pnl_emoji} {symbol}: "
                f"{pos.quantity} @ ₹{pos.average_price:.2f} "
                f"→ ₹{pos.last_price:.2f} ({pos.pnl_pct:+.2f}%) "
                f"[{pos.product}]{t1_note}"
            )
    
    def get_position(self, symbol: str) -> Optional[BrokerPosition]:
        positions = self.get_all_positions(use_cache=True, save_snapshot=False)
        return positions.get(symbol)
    
    def get_total_exposure(self) -> float:
        positions = self.get_all_positions(use_cache=True, save_snapshot=False)
        return sum(p.last_price * p.quantity for p in positions.values())
    
    def get_total_pnl(self) -> float:
        positions = self.get_all_positions(use_cache=True, save_snapshot=False)
        return sum(p.pnl for p in positions.values())
    
    def refresh(self):
        """Force refresh positions from broker"""
        self._cached_positions = {}
        self._last_sync_time = None
        return self.get_all_positions(use_cache=False)
    
    def send_sync_summary(self, result: SSOTReconcileResult):
        """v3.0.0: Send SSOT reconciliation summary via Telegram"""
        if not self.telegram or not result.has_changes():
            return
        
        msg_parts = ["📡 SSOT BROKER SYNC\n"]
        
        if result.new_mis_positions:
            msg_parts.append(f"\n➕ New MIS ({len(result.new_mis_positions)}):")
            for s, p in result.new_mis_positions.items():
                msg_parts.append(f"\n   {s}: {p.quantity} @ ₹{p.average_price:.2f}")
        
        if result.closed_mis_positions:
            msg_parts.append(f"\n\n➖ Closed MIS ({len(result.closed_mis_positions)}):")
            for s in result.closed_mis_positions:
                msg_parts.append(f"\n   {s}")
        
        if result.new_cnc_holdings:
            msg_parts.append(f"\n\n📦 New CNC ({len(result.new_cnc_holdings)}):")
            for s, p in result.new_cnc_holdings.items():
                t1 = f" ({p.quantity_t1} T+1)" if p.quantity_t1 > 0 else ""
                msg_parts.append(f"\n   {s}: {p.quantity}{t1}")
        
        if result.closed_cnc_holdings:
            msg_parts.append(f"\n\n📦 Closed CNC ({len(result.closed_cnc_holdings)}):")
            for s in result.closed_cnc_holdings:
                msg_parts.append(f"\n   {s}")
        
        msg_parts.append(f"\n\n⏰ {result.sync_time.strftime('%H:%M:%S')}")
        
        try:
            self.telegram.send_message("".join(msg_parts))
        except:
            pass


def create_broker_sync(kite, telegram=None, config=None) -> BrokerSyncManager:
    """Factory function"""
    return BrokerSyncManager(kite, telegram, config)
