"""
Position Recovery Module for Trading System (ENHANCED v2.0)
============================================================

CRITICAL SAFETY FEATURE: Recovers open positions on system startup.

NEW v2.0 FEATURES:
- Auto-creates missing files (positions.json, recovery_reports/)
- Initializes empty structures if needed
- Safe startup even with no prior data

Without this, positions from crashed/restarted systems would be UNMONITORED,
leading to unlimited loss risk!

Author: Trading System v4.2.0
Date: 2026-01-23
"""

import os
import json
import logging
from datetime import datetime
from typing import List, Dict, Optional, Tuple

logger = logging.getLogger(__name__)


class PositionRecovery:
    """
    Position Recovery System with Auto-Initialization
    
    Features:
    - Auto-creates data/ directory
    - Auto-creates positions.json if missing
    - Auto-creates recovery_reports/ directory
    - Graceful handling of missing files
    - Recovers positions from broker + local file
    """
    
    def __init__(self, kite, config, telegram=None):
        """
        Initialize position recovery with auto-setup
        
        Args:
            kite: Authenticated Kite Connect instance
            config: System configuration
            telegram: Optional Telegram notifier
        """
        self.kite = kite
        self.config = config
        self.telegram = telegram
        
        # File paths
        self.data_dir = 'data'
        self.positions_file = getattr(config, 'POSITIONS_FILE', 'data/positions.json')
        self.recovery_reports_dir = 'data/recovery_reports'
        
        # Statistics
        self.broker_count = 0
        self.local_count = 0
        self.reconciled_count = 0
        self.orphaned_count = 0
        
        # ═══════════════════════════════════════════════════════════════
        # AUTO-INITIALIZE FILE STRUCTURE
        # ═══════════════════════════════════════════════════════════════
        self._ensure_file_structure()
    
    
    def _ensure_file_structure(self):
        """
        Auto-create required directories and files if missing
        
        Creates:
        - data/ directory
        - data/positions.json (empty array)
        - data/recovery_reports/ directory
        """
        logger.info("Checking file structure...")
        
        # Create data/ directory
        if not os.path.exists(self.data_dir):
            os.makedirs(self.data_dir)
            logger.info(f"✅ Created directory: {self.data_dir}/")
        
        # Create recovery_reports/ directory
        if not os.path.exists(self.recovery_reports_dir):
            os.makedirs(self.recovery_reports_dir)
            logger.info(f"✅ Created directory: {self.recovery_reports_dir}/")
        
        # Create positions.json if missing
        if not os.path.exists(self.positions_file):
            with open(self.positions_file, 'w') as f:
                json.dump([], f, indent=2)
            logger.info(f"✅ Created file: {self.positions_file} (empty)")
        
        logger.info("File structure ready ✓")
    
    
    def recover_positions(self) -> List[Dict]:
        """
        Main entry point: Recover all open positions
        
        Returns:
            List of reconciled positions ready for monitoring
        """
        logger.info("")
        logger.info("=" * 80)
        logger.info("🔍 POSITION RECOVERY (Startup Check)")
        logger.info("=" * 80)
        logger.info("")
        
        # Ensure file structure exists
        self._ensure_file_structure()
        
        # Step 1: Fetch from broker API
        logger.info("📡 Checking Kite API for live positions...")
        broker_positions = self._fetch_broker_positions()
        self.broker_count = len(broker_positions)
        
        # Step 2: Load from local file
        logger.info("💾 Checking local positions.json...")
        local_positions = self._load_local_positions()
        self.local_count = len(local_positions)
        
        # Step 3: Reconcile both sources
        logger.info("")
        logger.info("🔄 Reconciling position sources...")
        logger.info("")
        reconciled = self._reconcile_positions(broker_positions, local_positions)
        self.reconciled_count = len(reconciled)
        self.orphaned_count = len([p for p in reconciled if p.get('source') == 'ORPHANED'])
        
        # Step 4: Check health of each position
        for pos in reconciled:
            health = self._check_position_health(pos)
            pos['health'] = health
        
        # Step 5: Generate report
        self._save_reconciliation_report(reconciled)
        
        # Step 6: Send alerts
        if reconciled:
            self._send_recovery_alert(reconciled)
        else:
            logger.info("✅ No open positions to recover")
        
        logger.info("")
        logger.info("=" * 80)
        logger.info("")
        
        return reconciled
    
    
    def _fetch_broker_positions(self) -> List[Dict]:
        """
        Fetch live positions from Kite API
        
        Returns:
            List of open positions from broker
        """
        try:
            positions = self.kite.positions()
            
            # Extract net positions (combined day + carried forward)
            net_positions = positions.get('net', [])
            
            # Filter for open positions only
            open_positions = []
            for pos in net_positions:
                # Check if actually open (has non-zero quantity)
                qty = pos.get('quantity', 0)
                if qty != 0:
                    # Calculate current P&L
                    buy_value = pos.get('buy_value', 0)
                    pnl = pos.get('pnl', 0)
                    pnl_pct = (pnl / buy_value * 100) if buy_value > 0 else 0
                    
                    open_positions.append({
                        'symbol': pos['tradingsymbol'],
                        'exchange': pos['exchange'],
                        'quantity': qty,
                        'entry_price': pos.get('average_price', 0),
                        'buy_value': buy_value,
                        'current_price': pos.get('last_price', 0),
                        'current_pnl': pnl,
                        'pnl_pct': pnl_pct,
                        'product': pos.get('product', 'MIS'),
                        'source': 'BROKER_API',
                        'broker_data': pos  # Keep full broker data
                    })
            
            if open_positions:
                logger.info(f"   └─ ✅ Found {len(open_positions)} live position(s) at broker:")
                for pos in open_positions:
                    pnl_emoji = "🟢" if pos['current_pnl'] > 0 else "🔴" if pos['current_pnl'] < 0 else "⚪"
                    logger.info(f"      {pnl_emoji} {pos['symbol']}: ₹{pos['entry_price']:.2f} → ₹{pos['current_price']:.2f} ({pos['pnl_pct']:+.1f}%)")
            else:
                logger.info(f"   └─ No live positions at broker")
            
            return open_positions
            
        except Exception as e:
            logger.error(f"   └─ ❌ Error fetching broker positions: {e}")
            logger.error(f"   └─ Will check local file only")
            return []
    
    
    def _load_local_positions(self) -> List[Dict]:
        """
        Load positions from local positions.json
        
        Auto-creates file if missing.
        
        Returns:
            List of positions from our records
        """
        try:
            # Ensure file exists
            if not os.path.exists(self.positions_file):
                logger.info(f"   └─ Creating new positions file: {self.positions_file}")
                with open(self.positions_file, 'w') as f:
                    json.dump([], f, indent=2)
                return []
            
            with open(self.positions_file, 'r') as f:
                data = json.load(f)
            
            if not isinstance(data, list):
                data = [data]
            
            # Filter for OPEN status only
            open_positions = [p for p in data if p.get('status') == 'OPEN']
            
            if open_positions:
                logger.info(f"   └─ ✅ Found {len(open_positions)} position(s) in local file:")
                for pos in open_positions:
                    logger.info(f"      📄 {pos['symbol']}: Entry ₹{pos.get('entry_price', 0):.2f}")
            else:
                logger.info(f"   └─ No open positions in local file")
            
            return open_positions
            
        except json.JSONDecodeError as e:
            logger.error(f"   └─ ❌ Invalid JSON in {self.positions_file}: {e}")
            logger.error(f"   └─ Creating backup and starting fresh")
            
            # Backup corrupted file
            backup_file = f"{self.positions_file}.backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            if os.path.exists(self.positions_file):
                os.rename(self.positions_file, backup_file)
                logger.info(f"   └─ Corrupted file backed up to: {backup_file}")
            
            # Create fresh file
            with open(self.positions_file, 'w') as f:
                json.dump([], f, indent=2)
            
            return []
            
        except Exception as e:
            logger.error(f"   └─ ❌ Error loading local positions: {e}")
            return []
    
    
    def _reconcile_positions(
        self, 
        broker_positions: List[Dict], 
        local_positions: List[Dict]
    ) -> List[Dict]:
        """
        Reconcile broker positions with local records
        
        Logic:
        - Position in both? → Use broker live data + local metadata
        - Position in broker only? → Orphaned! Warn and use default stops
        - Position in local only? → Already closed, skip
        
        Args:
            broker_positions: Positions from Kite API
            local_positions: Positions from our file
            
        Returns:
            Reconciled positions ready for monitoring
        """
        reconciled = []
        
        # Create lookup dicts
        broker_by_symbol = {p['symbol']: p for p in broker_positions}
        local_by_symbol = {p['symbol']: p for p in local_positions}
        
        all_symbols = set(broker_by_symbol.keys()) | set(local_by_symbol.keys())
        
        for symbol in sorted(all_symbols):
            broker_pos = broker_by_symbol.get(symbol)
            local_pos = local_by_symbol.get(symbol)
            
            if broker_pos and local_pos:
                # ✅ IDEAL: Position in both sources
                logger.info(f"   ✅ {symbol}: Found in both sources (reconciling...)")
                
                # Merge: Use broker for live data, local for metadata
                merged = {
                    # Our metadata (strategy, stops, targets)
                    'symbol': symbol,
                    'status': 'OPEN',
                    'entry_time': local_pos.get('entry_time'),
                    'order_id': local_pos.get('order_id'),
                    'stop_loss': local_pos.get('stop_loss'),
                    'target': local_pos.get('target'),
                    'strategy': local_pos.get('strategy', 'Unknown'),
                    'signal': local_pos.get('signal'),
                    
                    # Broker live data (current truth)
                    'entry_price': broker_pos['entry_price'],
                    'quantity': broker_pos['quantity'],
                    'current_price': broker_pos['current_price'],
                    'current_pnl': broker_pos['current_pnl'],
                    'pnl_pct': broker_pos['pnl_pct'],
                    'product': broker_pos['product'],
                    'entry_value': broker_pos['buy_value'],
                    
                    # Metadata
                    'source': 'RECONCILED',
                    'recovery_time': datetime.now().isoformat()
                }
                reconciled.append(merged)
                
            elif broker_pos and not local_pos:
                # ⚠️ WARNING: Position at broker but no local record (ORPHANED)
                logger.warning(f"   ⚠️  {symbol}: At broker but NO local record → ORPHANED TRADE!")
                logger.warning(f"      This position was likely placed outside the system")
                
                # Get default stops from config or use hardcoded
                default_stop_pct = getattr(self.config, 'DEFAULT_STOP_LOSS_PCT', 2.0)
                default_target_pct = getattr(self.config, 'DEFAULT_PROFIT_TARGET_PCT', 3.0)
                
                logger.warning(f"      Using default stops: -{default_stop_pct}%, +{default_target_pct}%")
                
                # Use broker data, create minimal metadata with default stops
                orphaned = {
                    'symbol': symbol,
                    'status': 'OPEN',
                    'entry_price': broker_pos['entry_price'],
                    'current_price': broker_pos['current_price'],
                    'quantity': broker_pos['quantity'],
                    'current_pnl': broker_pos['current_pnl'],
                    'pnl_pct': broker_pos['pnl_pct'],
                    'entry_value': broker_pos['buy_value'],
                    'product': broker_pos['product'],
                    
                    # Default stops
                    'stop_loss': broker_pos['entry_price'] * (1 - default_stop_pct/100),
                    'target': broker_pos['entry_price'] * (1 + default_target_pct/100),
                    'strategy': 'ORPHANED',
                    
                    # Metadata
                    'source': 'ORPHANED',
                    'warning': f'No local record - using default stops ({default_stop_pct}%/{default_target_pct}%)',
                    'recovery_time': datetime.now().isoformat()
                }
                reconciled.append(orphaned)
                
            elif local_pos and not broker_pos:
                # ℹ️ INFO: Position in file but not at broker (already closed)
                logger.info(f"   ℹ️  {symbol}: In local file but NOT at broker (already closed)")
                logger.info(f"      Skipping recovery (will clean up file)")
                # Don't add to reconciled
        
        logger.info("")
        logger.info(f"📊 Reconciliation Summary:")
        logger.info(f"   Broker positions: {len(broker_positions)}")
        logger.info(f"   Local positions: {len(local_positions)}")
        logger.info(f"   Reconciled: {len(reconciled)}")
        logger.info(f"   Orphaned: {len([p for p in reconciled if p.get('source') == 'ORPHANED'])}")
        logger.info("")
        
        return reconciled
    
    
    def _check_position_health(self, position: Dict) -> Dict:
        """
        Check health of recovered position
        
        Determines if immediate action needed (stop hit, target hit, etc.)
        
        Args:
            position: Recovered position dict
            
        Returns:
            Health status dict with warnings and actions
        """
        health = {
            'status': 'HEALTHY',
            'warnings': [],
            'actions': [],
            'severity': 'LOW'
        }
        
        current_price = position['current_price']
        entry_price = position['entry_price']
        stop_loss = position.get('stop_loss', 0)
        target = position.get('target', 0)
        pnl_pct = position.get('pnl_pct', 0)
        
        # Check 1: Is stop loss hit?
        if stop_loss > 0 and current_price <= stop_loss:
            health['status'] = 'CRITICAL'
            health['severity'] = 'CRITICAL'
            health['warnings'].append(f'STOP LOSS HIT: {current_price:.2f} <= {stop_loss:.2f}')
            health['actions'].append('EXIT IMMEDIATELY AT MARKET')
        
        # Check 2: Is target hit?
        elif target > 0 and current_price >= target:
            health['status'] = 'TARGET_HIT'
            health['severity'] = 'HIGH'
            health['warnings'].append(f'TARGET REACHED: {current_price:.2f} >= {target:.2f}')
            health['actions'].append('EXIT AT MARKET')
        
        # Check 3: Large drawdown?
        elif pnl_pct < -3:
            health['status'] = 'WARNING'
            health['severity'] = 'MEDIUM'
            health['warnings'].append(f'Drawdown: {pnl_pct:.1f}%')
            health['actions'].append('MONITOR CLOSELY')
        
        # Check 4: Near market close?
        now = datetime.now()
        if now.hour >= 15 and now.minute >= 20:
            health['warnings'].append('NEAR MARKET CLOSE (15:20+)')
            health['actions'].append('PREPARE TO EXIT')
            if health['severity'] == 'LOW':
                health['severity'] = 'MEDIUM'
        
        # Check 5: Orphaned position?
        if position.get('source') == 'ORPHANED':
            health['warnings'].append('ORPHANED TRADE (no local record)')
            health['actions'].append('VERIFY STOPS MANUALLY')
            if health['severity'] == 'LOW':
                health['severity'] = 'MEDIUM'
        
        return health
    
    
    def _send_recovery_alert(self, positions: List[Dict]):
        """
        Send Telegram alert about recovered positions
        
        Args:
            positions: List of recovered positions
        """
        if not self.telegram:
            return
        
        try:
            msg = "⚠️ POSITION RECOVERY ALERT\n"
            msg += "=" * 40 + "\n\n"
            msg += f"System startup detected {len(positions)} open position(s) from previous session:\n\n"
            
            for pos in positions:
                symbol = pos['symbol']
                entry = pos['entry_price']
                current = pos['current_price']
                pnl = pos.get('current_pnl', 0)
                pnl_pct = pos.get('pnl_pct', 0)
                
                # Emoji based on P&L
                if pnl > 0:
                    emoji = "🟢"
                elif pnl < 0:
                    emoji = "🔴"
                else:
                    emoji = "⚪"
                
                # Warning emoji for orphaned
                if pos.get('source') == 'ORPHANED':
                    emoji = "⚠️ " + emoji
                
                msg += f"{emoji} {symbol}\n"
                msg += f"   Entry: ₹{entry:.2f}\n"
                msg += f"   Current: ₹{current:.2f}\n"
                msg += f"   P&L: ₹{pnl:+.2f} ({pnl_pct:+.1f}%)\n"
                
                # Add stop/target info
                if pos.get('stop_loss'):
                    msg += f"   Stop: ₹{pos['stop_loss']:.2f}\n"
                if pos.get('target'):
                    msg += f"   Target: ₹{pos['target']:.2f}\n"
                
                # Add health warnings
                health = pos.get('health', {})
                if health.get('warnings'):
                    msg += f"   ⚠️ {', '.join(health['warnings'])}\n"
                
                msg += "\n"
            
            msg += "System will continue monitoring and manage exits automatically.\n"
            
            self.telegram.send_message(msg)
            logger.info("📱 Recovery alert sent to Telegram")
            
        except Exception as e:
            logger.error(f"❌ Failed to send Telegram alert: {e}")
    
    
    def _save_reconciliation_report(self, positions: List[Dict]):
        """
        Save reconciliation report for audit trail
        
        Auto-creates directory if needed.
        
        Args:
            positions: Reconciled positions
        """
        try:
            # Ensure directory exists
            os.makedirs(self.recovery_reports_dir, exist_ok=True)
            
            report = {
                'timestamp': datetime.now().isoformat(),
                'recovery_stats': {
                    'broker_positions': self.broker_count,
                    'local_positions': self.local_count,
                    'reconciled': self.reconciled_count,
                    'orphaned': self.orphaned_count
                },
                'positions': positions
            }
            
            # Save report
            filename = f"{self.recovery_reports_dir}/recovery_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            with open(filename, 'w') as f:
                json.dump(report, f, indent=2)
            
            logger.info(f"📄 Reconciliation report saved: {filename}")
            
        except Exception as e:
            logger.error(f"❌ Failed to save reconciliation report: {e}")
