"""
SSOT SIMPLE INTEGRATOR v5.0.0
═══════════════════════════════════════════════════════════════════════════════

This script integrates SSOT support into existing files with MINIMAL changes.
Uses new modular files instead of massive inline patches.

NEW FILES REQUIRED (download these first):
1. capital_manager.py (v5.0.0 - already replaced)
2. broker_sync.py (v3.0.0 - already replaced)
3. broker_sync_handler.py (NEW - handles sync logic)
4. phase4_holding_monitor.py (NEW - CNC holding monitoring)

WHAT THIS SCRIPT DOES:
1. Adds import for BrokerSyncHandler to orchestrator.py
2. Adds import for HoldingMonitor to phase4_portfolio_manager.py
3. Adds minimal integration code (5-10 lines each file)

USAGE:
    python ssot_simple_integrator.py

Author: Trading System v5.0.0
Date: 2026-02-06
"""

import os
import sys
import shutil
from datetime import datetime

ORCHESTRATOR_FILE = "orchestrator.py"
PHASE4_FILE = "phase4_portfolio_manager.py"


def backup_file(filepath):
    """Create timestamped backup"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = filepath.replace('.py', f'_backup_{timestamp}.py')
    shutil.copy2(filepath, backup_path)
    print(f"   Backup: {backup_path}")
    return backup_path


def patch_orchestrator(filepath):
    """
    Minimal patch to orchestrator.py:
    1. Add import for BrokerSyncHandler
    2. Initialize BrokerSyncHandler in __init__
    3. Replace broker_sync_positions() call with handler.sync()
    """
    print(f"\nPatching {filepath}...")
    
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Check if already patched
    if 'BrokerSyncHandler' in content:
        print("   Already has BrokerSyncHandler - skipping")
        return True
    
    # 1. Add import after capital_manager import
    import_marker = "from capital_manager import CapitalManager"
    import_addition = """from capital_manager import CapitalManager
    
# v5.0.0 SSOT: Modular broker sync handler
try:
    from broker_sync_handler import BrokerSyncHandler
    BROKER_SYNC_HANDLER_AVAILABLE = True
except ImportError:
    BROKER_SYNC_HANDLER_AVAILABLE = False
    BrokerSyncHandler = None"""
    
    if import_marker in content:
        content = content.replace(import_marker, import_addition)
        print("   Added BrokerSyncHandler import")
    else:
        print("   WARNING: Could not find import marker")
    
    # 2. Find __init__ and add handler initialization
    # Look for "self.broker_sync = " and add after it
    broker_sync_init = "self.broker_sync = create_broker_sync(self.kite, self.telegram)"
    handler_init = """self.broker_sync = create_broker_sync(self.kite, self.telegram)
        
        # v5.0.0 SSOT: Initialize modular broker sync handler
        self.broker_sync_handler = None
        if BROKER_SYNC_HANDLER_AVAILABLE and BrokerSyncHandler:
            self.broker_sync_handler = BrokerSyncHandler(
                kite=self.kite,
                capital_manager=self.capital_manager,
                phase4=self.phase4,
                phase3=self.phase3,
                telegram=self.telegram,
                positions_lock=self._positions_lock,
                central_positions=self._central_positions,
                exited_today=self._exited_today,
                broker_sync_manager=self.broker_sync
            )
            logger.info("v5.0.0: BrokerSyncHandler initialized (SSOT enabled)")"""
    
    if broker_sync_init in content:
        content = content.replace(broker_sync_init, handler_init)
        print("   Added BrokerSyncHandler initialization")
    else:
        print("   WARNING: Could not find broker_sync initialization")
    
    # 3. Modify broker_sync_positions to use handler
    # Find the method and add a quick check at the start
    old_sync_start = '''    def broker_sync_positions(self):
        """
        Sync central state with broker positions.
        Called every 30 seconds to catch GTT exits, manual trades, etc.'''
    
    new_sync_start = '''    def broker_sync_positions(self):
        """
        v5.0.0: Sync using BrokerSyncHandler if available.
        Falls back to legacy sync if handler not available.
        """
        # v5.0.0: Use modular handler if available
        if self.broker_sync_handler:
            self.broker_sync_handler.sync()
            return
        
        # Legacy sync below (fallback)
        """
        Sync central state with broker positions.
        Called every 30 seconds to catch GTT exits, manual trades, etc.'''
    
    if old_sync_start in content:
        content = content.replace(old_sync_start, new_sync_start)
        print("   Modified broker_sync_positions to use handler")
    else:
        # Try alternate pattern
        alt_pattern = "    def broker_sync_positions(self):"
        if alt_pattern in content and "broker_sync_handler" not in content:
            # Insert handler check after method definition
            new_method_start = '''    def broker_sync_positions(self):
        """v5.0.0: Sync using modular handler or legacy fallback."""
        # v5.0.0: Use BrokerSyncHandler if available
        if hasattr(self, 'broker_sync_handler') and self.broker_sync_handler:
            self.broker_sync_handler.sync()
            return
        
        # Legacy sync (original code below)'''
            
            # Find the full method signature with docstring
            import re
            pattern = r'(    def broker_sync_positions\(self\):)\s*\n\s*"""[^"]*"""'
            match = re.search(pattern, content)
            if match:
                content = content[:match.start()] + new_method_start + "\n        " + content[match.end():]
                print("   Modified broker_sync_positions (alternate pattern)")
            else:
                print("   WARNING: Could not find broker_sync_positions method")
    
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)
    
    return True


def patch_phase4(filepath):
    """
    Minimal patch to phase4_portfolio_manager.py:
    1. Add import for HoldingMonitor
    2. Initialize HoldingMonitor in __init__
    3. Add delegate methods
    """
    print(f"\nPatching {filepath}...")
    
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Check if already patched
    if 'HoldingMonitor' in content or 'holding_monitors' in content:
        print("   Already has HoldingMonitor - skipping")
        return True
    
    # 1. Add import at top (after other imports)
    import_marker = "logger = logging.getLogger('Phase4_PortfolioManager')"
    import_addition = """logger = logging.getLogger('Phase4_PortfolioManager')

# v5.0.0 SSOT: CNC Holding Monitor (OBSERVE_ONLY mode)
try:
    from phase4_holding_monitor import HoldingMonitor
    HOLDING_MONITOR_AVAILABLE = True
except ImportError:
    HOLDING_MONITOR_AVAILABLE = False
    HoldingMonitor = None"""
    
    if import_marker in content:
        content = content.replace(import_marker, import_addition)
        print("   Added HoldingMonitor import")
    else:
        print("   WARNING: Could not find logger definition")
    
    # 2. Add holding_monitors initialization in __init__
    # Look for "self.positions = {}" and add after it
    positions_init = "self.positions: Dict[str, Dict] = {}"
    if positions_init not in content:
        positions_init = "self.positions = {}"
    
    holding_init = positions_init + """
        
        # v5.0.0 SSOT: CNC Holding Monitor (OBSERVE_ONLY mode)
        self.holding_monitors = {}
        self._holding_monitor = None
        if HOLDING_MONITOR_AVAILABLE and HoldingMonitor:
            self._holding_monitor = HoldingMonitor(telegram=self.telegram)
            logger.info("v5.0.0: HoldingMonitor initialized (CNC OBSERVE_ONLY)")"""
    
    if positions_init in content:
        content = content.replace(positions_init, holding_init)
        print("   Added HoldingMonitor initialization")
    else:
        print("   WARNING: Could not find positions initialization")
    
    # 3. Add delegate methods at end of class
    # Find a good spot - look for the last method before if __name__
    delegate_methods = '''
    # ═══════════════════════════════════════════════════════════════════════════════
    # v5.0.0 SSOT: CNC HOLDING MONITOR DELEGATES
    # ═══════════════════════════════════════════════════════════════════════════════
    
    def add_holding_monitor(self, symbol: str, quantity: int, avg_price: float,
                            phase4_mode: str = 'OBSERVE_ONLY'):
        """v5.0.0: Add CNC holding for OBSERVE_ONLY monitoring."""
        if self._holding_monitor:
            return self._holding_monitor.add_holding(symbol, quantity, avg_price)
        
        # Fallback: store in dict
        self.holding_monitors[symbol] = {
            'symbol': symbol,
            'quantity': quantity,
            'avg_price': avg_price,
            'phase4_mode': phase4_mode,
            'added_at': datetime.now().isoformat(),
            'last_price': 0,
            'pnl': 0,
            'pnl_pct': 0
        }
        logger.info(f"Phase 4: Added {symbol} as CNC OBSERVE_ONLY")
        return True

    def update_holding_prices(self, prices: Dict[str, float]):
        """v5.0.0: Update prices for CNC holdings."""
        if self._holding_monitor:
            self._holding_monitor.update_prices(prices)
            return
        
        # Fallback
        for symbol, hold in self.holding_monitors.items():
            if symbol in prices:
                ltp = prices[symbol]
                hold['last_price'] = ltp
                hold['pnl'] = (ltp - hold['avg_price']) * hold['quantity']
                if hold['avg_price'] > 0:
                    hold['pnl_pct'] = ((ltp - hold['avg_price']) / hold['avg_price'] * 100)

    def get_holding_status(self) -> Dict[str, Dict]:
        """v5.0.0: Get status of all CNC holdings."""
        if self._holding_monitor:
            return self._holding_monitor.get_all_status()
        return self.holding_monitors.copy()

    def remove_holding_monitor(self, symbol: str):
        """v5.0.0: Remove CNC holding from monitoring."""
        if self._holding_monitor:
            return self._holding_monitor.remove_holding(symbol)
        if symbol in self.holding_monitors:
            del self.holding_monitors[symbol]
            logger.info(f"Phase 4: Removed {symbol} from CNC monitoring")

'''
    
    # Find end of class (before if __name__)
    if "if __name__ ==" in content:
        insert_point = content.rfind("\nif __name__ ==")
        content = content[:insert_point] + delegate_methods + content[insert_point:]
        print("   Added delegate methods")
    else:
        # Just append at end
        content += delegate_methods
        print("   Added delegate methods at end")
    
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)
    
    return True


def validate_syntax(filepath):
    """Validate Python syntax"""
    import py_compile
    try:
        py_compile.compile(filepath, doraise=True)
        print(f"   Syntax OK: {filepath}")
        return True
    except py_compile.PyCompileError as e:
        print(f"   Syntax ERROR in {filepath}: {e}")
        return False


def check_required_files():
    """Check that required new files exist"""
    required = [
        'capital_manager.py',
        'broker_sync.py', 
        'broker_sync_handler.py',
        'phase4_holding_monitor.py'
    ]
    
    missing = []
    for f in required:
        if not os.path.exists(f):
            missing.append(f)
    
    return missing


def main():
    print("=" * 70)
    print("SSOT SIMPLE INTEGRATOR v5.0.0")
    print("=" * 70)
    print()
    print("This adds SSOT support with MINIMAL changes to existing files.")
    print()
    
    # Check we're in the right directory
    if not os.path.exists(ORCHESTRATOR_FILE):
        print(f"ERROR: {ORCHESTRATOR_FILE} not found!")
        print("Please run from your Algo_Beta directory.")
        sys.exit(1)
    
    if not os.path.exists(PHASE4_FILE):
        print(f"ERROR: {PHASE4_FILE} not found!")
        sys.exit(1)
    
    # Check required files
    missing = check_required_files()
    if missing:
        print("ERROR: Missing required files:")
        for f in missing:
            print(f"   - {f}")
        print()
        print("Please download these files first.")
        sys.exit(1)
    
    print("Required files found:")
    print("   - capital_manager.py (v5.0.0)")
    print("   - broker_sync.py (v3.0.0)")
    print("   - broker_sync_handler.py (NEW)")
    print("   - phase4_holding_monitor.py (NEW)")
    print()
    
    response = input("Continue with integration? (y/n): ").strip().lower()
    if response != 'y':
        print("Aborted.")
        sys.exit(0)
    
    # Create backups
    print("\nCreating backups...")
    backup_file(ORCHESTRATOR_FILE)
    backup_file(PHASE4_FILE)
    
    # Patch files
    success = True
    
    if not patch_orchestrator(ORCHESTRATOR_FILE):
        success = False
    
    if not patch_phase4(PHASE4_FILE):
        success = False
    
    # Validate syntax
    print("\nValidating syntax...")
    if not validate_syntax(ORCHESTRATOR_FILE):
        success = False
    if not validate_syntax(PHASE4_FILE):
        success = False
    
    # Summary
    print()
    print("=" * 70)
    if success:
        print("INTEGRATION COMPLETE!")
        print()
        print("Changes made:")
        print("  1. orchestrator.py: Uses BrokerSyncHandler for sync")
        print("  2. phase4_portfolio_manager.py: Has HoldingMonitor for CNC")
        print()
        print("Next steps:")
        print("  1. Restart your trading system")
        print("  2. Look for these log messages:")
        print("     - 'v5.0.0: BrokerSyncHandler initialized'")
        print("     - 'v5.0.0: HoldingMonitor initialized'")
        print("  3. CNC holdings will show as OBSERVE_ONLY")
    else:
        print("INTEGRATION HAD ISSUES - Check errors above")
        print("Backups were created, you can restore if needed.")
    print("=" * 70)


if __name__ == "__main__":
    main()
