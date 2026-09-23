"""
DAILY_BLACKBOX.PY - Flight Data Recorder for Trading System v2.0.0
═══════════════════════════════════════════════════════════════════════════════

v2.0.0 UPGRADE: SQLite Database Integration
────────────────────────────────────────────
- All events stored in unified SQLite database
- Real-time queryable data (no more scattered JSON files)
- Console output capture (what you see in CMD window!)
- Backward compatible API - same methods, new storage

REPLACES:
- data/blackbox/blackbox_YYYY-MM-DD.json → database table: system_events
- data/blackbox/summary_YYYY-MM-DD.txt → auto-generated from database

Author: Dheebanraj
Version: 2.0.0
Date: 2026-02-04
"""

import json
import os
import logging
from datetime import datetime
from typing import Dict, List, Any, Optional

# Import unified data manager
try:
    from unified_data_manager import get_db, UnifiedDataManager
except ImportError:
    # Fallback if module not found yet
    get_db = None
    UnifiedDataManager = None

logger = logging.getLogger('DailyBlackbox')


class DailyBlackbox:
    """
    Records all trading events for daily analysis.
    
    v2.0.0: Now uses SQLite database for storage instead of JSON files.
    
    Like an aircraft's flight data recorder:
    - All system events
    - All decisions made
    - All stocks monitored
    - All signals generated
    - All trades executed
    - Performance metrics
    - Console output (NEW in v2.0.0!)
    """
    
    def __init__(self):
        """Initialize blackbox recorder"""
        self.date = datetime.now().strftime('%Y-%m-%d')
        self.start_time = datetime.now()
        
        # Event categories (in-memory for quick access)
        self.events = []
        self.stocks_monitored = set()  # Unique stocks seen today
        self.phase1_scans = []
        self.phase2_signals = []
        self.phase3_trades = []
        self.errors = []
        
        # Summary stats
        self.stats = {
            'system_start': self.start_time.isoformat(),
            'system_end': None,
            'total_runtime_minutes': 0,
            'phase1_scans_count': 0,
            'stocks_identified_count': 0,
            'stocks_monitored_count': 0,
            'signals_generated_count': 0,
            'trades_executed_count': 0,
            'errors_count': 0
        }
        
        # Database connection
        self._db = None
        self._init_database()
        
        # Legacy file path (for backward compatibility summary export)
        os.makedirs('data/blackbox', exist_ok=True)
        self.filepath = f'data/blackbox/blackbox_{self.date}.json'
        
        # Log initialization to database
        self._log_to_db('SYSTEM_START', 'system', {
            'date': self.date,
            'start_time': self.start_time.isoformat()
        })
        
        logger.info("=" * 80)
        logger.info("📦 DAILY BLACKBOX v2.0.0 - SQLite Database Storage")
        logger.info("=" * 80)
        logger.info(f"   Date: {self.date}")
        logger.info(f"   Database: data/algo_beta.db")
        logger.info("=" * 80)
    
    def _init_database(self):
        """Initialize database connection"""
        try:
            if get_db is not None:
                self._db = get_db()
                logger.info("✅ Blackbox connected to SQLite database")
            else:
                logger.warning("⚠️ UnifiedDataManager not available, using legacy JSON storage")
        except Exception as e:
            logger.error(f"Failed to connect to database: {e}")
            self._db = None
    
    def _log_to_db(self, event_type: str, category: str, details: Dict[str, Any], 
                   severity: str = "INFO"):
        """Log event to database"""
        if self._db:
            try:
                self._db.log_event(
                    event_type=event_type,
                    category=category,
                    details=details,
                    severity=severity
                )
            except Exception as e:
                logger.debug(f"DB log failed: {e}")
    
    def _log_console(self, message: str, level: str = "INFO", source: str = None):
        """Log to console capture (CMD window output)"""
        if self._db:
            try:
                self._db.log_console(
                    message=message,
                    level=level,
                    source=source or "Blackbox"
                )
            except Exception:
                pass
    
    def log_event(self, category: str, event_type: str, details: Dict[str, Any]):
        """
        Log a system event.
        
        Args:
            category: 'system', 'phase1', 'phase2', 'phase3', 'error'
            event_type: Specific event (e.g., 'scan_completed', 'signal_generated')
            details: Event-specific data
        """
        event = {
            'timestamp': datetime.now().isoformat(),
            'category': category,
            'type': event_type,
            'details': details
        }
        self.events.append(event)
        
        # Log to database
        self._log_to_db(event_type, category, details)
        
        # Log to console capture
        self._log_console(
            f"[{category.upper()}] {event_type}: {json.dumps(details)[:200]}",
            level="INFO",
            source=f"Phase{category[-1]}" if category.startswith('phase') else category.capitalize()
        )
        
        # Auto-save every 10 events (legacy compatibility)
        if len(self.events) % 10 == 0:
            self.save()
    
    def log_phase1_scan(self, scan_time: str, stocks_found: List[str], scan_label: str):
        """Record Phase 1 scan results"""
        scan_record = {
            'timestamp': datetime.now().isoformat(),
            'scan_time': scan_time,
            'label': scan_label,
            'stocks_found': stocks_found,
            'count': len(stocks_found)
        }
        self.phase1_scans.append(scan_record)
        self.stats['phase1_scans_count'] += 1
        self.stats['stocks_identified_count'] += len(stocks_found)
        
        # Add to unique stocks
        for stock in stocks_found:
            symbol = stock if isinstance(stock, str) else stock.get('symbol', '')
            if symbol:
                self.stocks_monitored.add(symbol)
        
        # Log to database
        self._log_to_db('PHASE1_SCAN', 'phase1', {
            'scan_time': scan_time,
            'label': scan_label,
            'count': len(stocks_found),
            'stocks': [s if isinstance(s, str) else s.get('symbol', '') for s in stocks_found[:10]]
        })
        
        # Save stock selections to database
        if self._db and stocks_found:
            try:
                self._db.save_stock_selection(scan_time, scan_label, stocks_found)
            except Exception as e:
                logger.debug(f"Failed to save selection: {e}")
        
        self.log_event('phase1', 'scan_completed', scan_record)
        
        # Console log
        self._log_console(
            f"Phase 1 Scan [{scan_label}]: {len(stocks_found)} stocks found",
            source="Phase1"
        )
    
    def log_phase2_monitor_start(self, stocks: List[str]):
        """Record when Phase 2 monitoring starts"""
        for stock in stocks:
            symbol = stock if isinstance(stock, str) else stock.get('symbol', '')
            if symbol:
                self.stocks_monitored.add(symbol)
        
        self.stats['stocks_monitored_count'] = len(self.stocks_monitored)
        
        self._log_to_db('PHASE2_MONITOR_START', 'phase2', {
            'stocks': list(self.stocks_monitored),
            'count': len(self.stocks_monitored)
        })
        
        self.log_event('phase2', 'monitoring_started', {
            'stocks': list(self.stocks_monitored),
            'count': len(self.stocks_monitored)
        })
        
        self._log_console(
            f"Phase 2 Monitoring: {len(self.stocks_monitored)} stocks",
            source="Phase2"
        )
    
    def log_phase2_signal(self, symbol: str, signal_type: str, details: Dict[str, Any]):
        """Record Phase 2 entry signal"""
        signal_record = {
            'timestamp': datetime.now().isoformat(),
            'symbol': symbol,
            'signal_type': signal_type,
            'details': details
        }
        self.phase2_signals.append(signal_record)
        self.stats['signals_generated_count'] += 1
        
        self._log_to_db('PHASE2_SIGNAL', 'phase2', {
            'symbol': symbol,
            'signal_type': signal_type,
            'details': details
        })
        
        self.log_event('phase2', 'signal_generated', signal_record)
        
        self._log_console(
            f"🎯 Entry Signal: {symbol} - {signal_type}",
            level="INFO",
            source="Phase2"
        )
    
    def log_phase3_trade(self, symbol: str, action: str, details: Dict[str, Any]):
        """Record Phase 3 trade execution"""
        trade_record = {
            'timestamp': datetime.now().isoformat(),
            'symbol': symbol,
            'action': action,
            'details': details
        }
        self.phase3_trades.append(trade_record)
        self.stats['trades_executed_count'] += 1
        
        self._log_to_db('PHASE3_TRADE', 'phase3', {
            'symbol': symbol,
            'action': action,
            'details': details
        }, severity="INFO")
        
        # If this is a completed trade, save to trades table
        if self._db and action in ['EXIT', 'SELL', 'CLOSE']:
            try:
                trade_data = {
                    'symbol': symbol,
                    'date': self.date,
                    'exit_time': datetime.now().isoformat(),
                    'exit_reason': details.get('reason', action),
                    'pnl': details.get('pnl', 0),
                    'entry_price': details.get('entry_price'),
                    'exit_price': details.get('exit_price'),
                }
                # Merge any additional details
                trade_data.update({k: v for k, v in details.items() if k not in trade_data})
                self._db.save_trade(trade_data)
            except Exception as e:
                logger.debug(f"Failed to save trade: {e}")
        
        self.log_event('phase3', 'trade_executed', trade_record)
        
        pnl = details.get('pnl', 0)
        pnl_str = f"₹{pnl:+.2f}" if pnl else ""
        self._log_console(
            f"💰 Trade: {symbol} {action} {pnl_str}",
            level="INFO",
            source="Phase3"
        )
    
    def log_error(self, error_type: str, details: Dict[str, Any]):
        """Record system errors"""
        error_record = {
            'timestamp': datetime.now().isoformat(),
            'error_type': error_type,
            'details': details
        }
        self.errors.append(error_record)
        self.stats['errors_count'] += 1
        
        self._log_to_db(error_type, 'error', details, severity="ERROR")
        
        self.log_event('error', error_type, error_record)
        
        self._log_console(
            f"❌ Error: {error_type} - {str(details)[:100]}",
            level="ERROR",
            source="System"
        )
    
    def log_console_output(self, message: str, source: str = "System"):
        """
        v2.0.0 NEW: Directly log console output.
        
        Call this to capture important CMD window output.
        """
        self._log_console(message, level="INFO", source=source)
    
    def finalize(self) -> str:
        """Finalize recording at end of day"""
        self.stats['system_end'] = datetime.now().isoformat()
        runtime = datetime.now() - self.start_time
        self.stats['total_runtime_minutes'] = int(runtime.total_seconds() / 60)
        
        # Log finalization to database
        self._log_to_db('SYSTEM_END', 'system', {
            'date': self.date,
            'runtime_minutes': self.stats['total_runtime_minutes'],
            'stats': self.stats
        })
        
        # Update daily summary in database
        if self._db:
            try:
                self._db.update_daily_summary(
                    system_end_time=self.stats['system_end'],
                    runtime_minutes=self.stats['total_runtime_minutes'],
                    stocks_scanned=self.stats['stocks_identified_count'],
                    stocks_selected=len(self.stocks_monitored),
                    signals_generated=self.stats['signals_generated_count'],
                    trades_executed=self.stats['trades_executed_count'],
                    errors_count=self.stats['errors_count']
                )
                
                # Export console log to file
                self._db.export_console_to_file(self.date)
                
                logger.info("✅ Daily summary saved to database")
            except Exception as e:
                logger.error(f"Failed to update daily summary: {e}")
        
        # Save legacy JSON file
        self.save()
        
        # Generate summary
        summary = self.generate_summary()
        
        # Save summary to file
        summary_path = f'data/blackbox/summary_{self.date}.txt'
        try:
            with open(summary_path, 'w', encoding='utf-8') as f:
                f.write(summary)
        except Exception as e:
            logger.error(f"Failed to save summary: {e}")
        
        return summary
    
    def save(self):
        """Save blackbox data to file (legacy compatibility)"""
        data = {
            'date': self.date,
            'stats': self.stats,
            'stocks_monitored': list(self.stocks_monitored),
            'phase1_scans': self.phase1_scans,
            'phase2_signals': self.phase2_signals,
            'phase3_trades': self.phase3_trades,
            'errors': self.errors,
            'events': self.events[-100:]  # Only last 100 events in JSON
        }
        
        try:
            with open(self.filepath, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.debug(f"⚠️ Error saving blackbox JSON: {e}")
    
    def generate_summary(self) -> str:
        """Generate end-of-day summary report"""
        
        # Get trade stats from database if available
        db_stats = {}
        if self._db:
            try:
                db_stats = self._db.get_trade_stats(self.date)
            except:
                pass
        
        win_rate = db_stats.get('win_rate', 0)
        total_pnl = db_stats.get('total_pnl', 0)
        
        summary = f"""
╔═══════════════════════════════════════════════════════════════════════════════╗
║                                                                               ║
║  📊 DAILY TRADING SUMMARY - {self.date}                                       ║
║  Blackbox Recording v2.0.0 (SQLite Database)                                 ║
║                                                                               ║
╚═══════════════════════════════════════════════════════════════════════════════╝

SYSTEM OPERATION
════════════════════════════════════════════════════════════════════════════════
Start Time:       {self.stats['system_start']}
End Time:         {self.stats['system_end']}
Total Runtime:    {self.stats['total_runtime_minutes']} minutes

PERFORMANCE SUMMARY
════════════════════════════════════════════════════════════════════════════════
Trades Executed:  {self.stats['trades_executed_count']}
Win Rate:         {win_rate:.1f}%
Total P&L:        ₹{total_pnl:.2f}

PHASE 1 - STOCK SELECTION
════════════════════════════════════════════════════════════════════════════════
Scans Executed:   {self.stats['phase1_scans_count']}
Stocks Found:     {self.stats['stocks_identified_count']}

Scan Timeline:
"""
        for i, scan in enumerate(self.phase1_scans, 1):
            summary += f"  {i}. {scan['scan_time']} - {scan['label']}: {scan['count']} stocks\n"
            for stock in scan['stocks_found'][:5]:
                symbol = stock if isinstance(stock, str) else stock.get('symbol', '')
                summary += f"     • {symbol}\n"
            if len(scan['stocks_found']) > 5:
                summary += f"     ... and {len(scan['stocks_found']) - 5} more\n"
        
        summary += f"""
PHASE 2 - ENTRY MONITORING
════════════════════════════════════════════════════════════════════════════════
Unique Stocks Monitored: {len(self.stocks_monitored)}
Entry Signals Generated: {self.stats['signals_generated_count']}

Stocks Monitored Today:
"""
        for i, symbol in enumerate(sorted(self.stocks_monitored), 1):
            summary += f"  {i:2d}. {symbol}\n"
        
        if self.phase2_signals:
            summary += "\nEntry Signals:\n"
            for i, signal in enumerate(self.phase2_signals, 1):
                summary += f"  {i}. {signal['timestamp'][:16]} - {signal['symbol']}: {signal['signal_type']}\n"
        else:
            summary += "\nNo entry signals generated today.\n"
        
        summary += f"""
PHASE 3 - TRADE EXECUTION
════════════════════════════════════════════════════════════════════════════════
Trades Executed:  {self.stats['trades_executed_count']}

"""
        if self.phase3_trades:
            for i, trade in enumerate(self.phase3_trades, 1):
                pnl = trade['details'].get('pnl', 0)
                pnl_str = f"₹{pnl:+.2f}" if pnl else ""
                summary += f"  {i}. {trade['timestamp'][:16]} - {trade['symbol']}: {trade['action']} {pnl_str}\n"
        else:
            summary += "No trades executed today.\n"
        
        summary += f"""
SYSTEM HEALTH
════════════════════════════════════════════════════════════════════════════════
Errors/Warnings:  {self.stats['errors_count']}

"""
        if self.errors:
            for i, error in enumerate(self.errors[:10], 1):
                summary += f"  {i}. {error['timestamp'][:16]} - {error['error_type']}\n"
            if len(self.errors) > 10:
                summary += f"  ... and {len(self.errors) - 10} more (see database)\n"
        else:
            summary += "No errors recorded.\n"
        
        summary += f"""
════════════════════════════════════════════════════════════════════════════════
📊 Data stored in: data/algo_beta.db (SQLite)
📋 Console log: logs/console_{self.date.replace('-', '')}.txt
📁 Legacy JSON: {self.filepath}
════════════════════════════════════════════════════════════════════════════════
"""
        
        return summary
    
    def get_database_stats(self) -> Dict:
        """Get statistics from database"""
        if not self._db:
            return {}
        
        try:
            return {
                'trade_stats': self._db.get_trade_stats(self.date),
                'daily_summary': self._db.get_daily_summary(self.date),
                'selections': len(self._db.get_active_selections(self.date)),
                'console_entries': len(self._db.get_console_log(self.date, limit=10000))
            }
        except Exception as e:
            logger.error(f"Failed to get database stats: {e}")
            return {}


# ═══════════════════════════════════════════════════════════════════════════════
# SINGLETON PATTERN
# ═══════════════════════════════════════════════════════════════════════════════

_blackbox_instance: Optional[DailyBlackbox] = None

def get_blackbox() -> DailyBlackbox:
    """Get or create the daily blackbox instance"""
    global _blackbox_instance
    
    # Check if we need a new instance (new day)
    today = datetime.now().strftime('%Y-%m-%d')
    if _blackbox_instance is None or _blackbox_instance.date != today:
        _blackbox_instance = DailyBlackbox()
    
    return _blackbox_instance


# ═══════════════════════════════════════════════════════════════════════════════
# CONVENIENCE FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════════

def log_event(category: str, event_type: str, details: Dict[str, Any]):
    """Quick access to log_event"""
    get_blackbox().log_event(category, event_type, details)

def log_phase1_scan(scan_time: str, stocks_found: List[str], scan_label: str):
    """Quick access to log_phase1_scan"""
    get_blackbox().log_phase1_scan(scan_time, stocks_found, scan_label)

def log_phase2_signal(symbol: str, signal_type: str, details: Dict[str, Any]):
    """Quick access to log_phase2_signal"""
    get_blackbox().log_phase2_signal(symbol, signal_type, details)

def log_phase3_trade(symbol: str, action: str, details: Dict[str, Any]):
    """Quick access to log_phase3_trade"""
    get_blackbox().log_phase3_trade(symbol, action, details)

def log_error(error_type: str, details: Dict[str, Any]):
    """Quick access to log_error"""
    get_blackbox().log_error(error_type, details)

def log_console(message: str, source: str = "System"):
    """Quick access to log console output"""
    get_blackbox().log_console_output(message, source)


if __name__ == "__main__":
    # Test the blackbox
    print("Testing DailyBlackbox v2.0.0...")
    
    blackbox = DailyBlackbox()
    
    # Test logging
    blackbox.log_phase1_scan("09:30:00", ["RELIANCE", "TCS", "INFY"], "Morning Scan")
    blackbox.log_phase2_monitor_start(["RELIANCE", "TCS"])
    blackbox.log_phase2_signal("RELIANCE", "RSI_BOUNCE", {"rsi": 32, "price": 2500})
    blackbox.log_phase3_trade("RELIANCE", "BUY", {"price": 2500, "quantity": 1})
    blackbox.log_phase3_trade("RELIANCE", "EXIT", {
        "entry_price": 2500, 
        "exit_price": 2550, 
        "pnl": 50,
        "reason": "TARGET_HIT"
    })
    blackbox.log_error("API_TIMEOUT", {"endpoint": "/quote", "timeout": 30})
    
    # Finalize
    summary = blackbox.finalize()
    print(summary)
    
    # Show database stats
    stats = blackbox.get_database_stats()
    print("\nDatabase Stats:")
    print(json.dumps(stats, indent=2, default=str))
    
    print("\n✅ Test completed!")
