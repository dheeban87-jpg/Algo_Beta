"""
UNIFIED_DATA_MANAGER.PY - SQLite Database Manager for Algo_Beta v1.0.0
═══════════════════════════════════════════════════════════════════════════════

REPLACES: Multiple JSON files scattered across data/ folder
PROVIDES: Single SQLite database for all trading data

BENEFITS:
- Single file backup (algo_beta.db)
- SQL queries for analysis ("Show me all winning trades")
- No file proliferation (was 163 JSON files, now 1 DB)
- Console capture (what you see in CMD window)
- Fast lookups and aggregations

TABLES:
- daily_summary      → One row per trading day
- stock_selections   → Phase 1 stocks (replaces selected_stocks_*.json)
- trades            → Entry/Exit with P&L (replaces trades.json)
- positions         → Current holdings (replaces positions.json)
- decisions         → ChatGPT/AI decisions
- console_log       → CMD window output
- system_events     → Errors, restarts, alerts
- ai_analysis       → ChatGPT consultations
- broker_snapshots  → Broker state (replaces broker_state_*.json)

Author: Dheebanraj
Version: 1.0.0
Date: 2026-02-04
"""

import sqlite3
import json
import logging
import os
import threading
from datetime import datetime, date
from typing import Dict, List, Any, Optional, Tuple
from contextlib import contextmanager
from dataclasses import dataclass, asdict

logger = logging.getLogger('UnifiedDataManager')


# ═══════════════════════════════════════════════════════════════════════════════
# DATABASE SCHEMA
# ═══════════════════════════════════════════════════════════════════════════════

SCHEMA = '''
-- Daily summaries (one row per trading day)
CREATE TABLE IF NOT EXISTS daily_summary (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT UNIQUE NOT NULL,
    day_of_week TEXT,
    market_open INTEGER DEFAULT 1,
    system_start_time TEXT,
    system_end_time TEXT,
    runtime_minutes REAL DEFAULT 0,
    stocks_scanned INTEGER DEFAULT 0,
    stocks_selected INTEGER DEFAULT 0,
    signals_generated INTEGER DEFAULT 0,
    trades_executed INTEGER DEFAULT 0,
    total_pnl REAL DEFAULT 0,
    win_count INTEGER DEFAULT 0,
    loss_count INTEGER DEFAULT 0,
    errors_count INTEGER DEFAULT 0,
    notes TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- Stock selections (Phase 1 results)
CREATE TABLE IF NOT EXISTS stock_selections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    scan_time TEXT NOT NULL,
    scan_label TEXT,
    symbol TEXT NOT NULL,
    price REAL,
    rsi REAL,
    rsi_percentile REAL,
    volume_ratio REAL,
    atr_pct REAL,
    score REAL,
    filter_stage INTEGER,
    selected INTEGER DEFAULT 0,
    metadata TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- Trades (completed trades with P&L)
CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_id TEXT UNIQUE,
    symbol TEXT NOT NULL,
    date TEXT NOT NULL,
    entry_time TEXT,
    exit_time TEXT,
    entry_price REAL,
    exit_price REAL,
    quantity INTEGER DEFAULT 1,
    direction TEXT DEFAULT 'LONG',
    pnl REAL,
    pnl_pct REAL,
    win INTEGER,
    exit_reason TEXT,
    duration_minutes REAL,
    rsi_at_entry REAL,
    volume_ratio REAL,
    atr_pct REAL,
    target_pct REAL,
    stop_pct REAL,
    max_drawdown_pct REAL,
    max_profit_pct REAL,
    ai_confidence REAL,
    source_phase TEXT,
    metadata TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- Positions (current/historical positions)
CREATE TABLE IF NOT EXISTS positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    entry_time TEXT NOT NULL,
    entry_price REAL NOT NULL,
    quantity INTEGER DEFAULT 1,
    direction TEXT DEFAULT 'LONG',
    target_price REAL,
    stop_price REAL,
    current_price REAL,
    unrealized_pnl REAL,
    status TEXT DEFAULT 'OPEN',
    exit_time TEXT,
    exit_price REAL,
    exit_reason TEXT,
    metadata TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- AI/ChatGPT decisions
CREATE TABLE IF NOT EXISTS decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    symbol TEXT NOT NULL,
    decision TEXT NOT NULL,
    reason TEXT,
    confidence REAL,
    current_price REAL,
    entry_price REAL,
    target_price REAL,
    stop_price REAL,
    net_pnl REAL,
    prob_target REAL,
    prob_stop REAL,
    ev_hold REAL,
    ev_exit REAL,
    outcome TEXT,
    outcome_price REAL,
    actual_pnl REAL,
    prediction_correct INTEGER,
    metadata TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- Console log (CMD window capture) - THIS IS WHAT YOU WANTED!
CREATE TABLE IF NOT EXISTS console_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    level TEXT DEFAULT 'INFO',
    source TEXT,
    message TEXT NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- System events (errors, restarts, alerts)
CREATE TABLE IF NOT EXISTS system_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    event_type TEXT NOT NULL,
    category TEXT,
    details TEXT,
    severity TEXT DEFAULT 'INFO',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- AI analysis history (ChatGPT consultations)
CREATE TABLE IF NOT EXISTS ai_analysis (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    analysis_type TEXT,
    stocks_scanned INTEGER,
    stocks_selected INTEGER,
    market_condition TEXT,
    content TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- Broker state snapshots
CREATE TABLE IF NOT EXISTS broker_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    available_cash REAL,
    used_margin REAL,
    total_positions INTEGER,
    positions_data TEXT,
    orders_data TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- Kalman MAP calibration persistence (Phase D)
-- Stores converged Q/R matrices per stock for warm start
CREATE TABLE IF NOT EXISTS kalman_calibration (
    symbol TEXT PRIMARY KEY,
    q_matrix TEXT NOT NULL,
    r_matrix TEXT NOT NULL,
    observation_count INTEGER DEFAULT 0,
    last_updated TEXT NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- Create indexes for fast queries
CREATE INDEX IF NOT EXISTS idx_trades_date ON trades(date);
CREATE INDEX IF NOT EXISTS idx_trades_symbol ON trades(symbol);
CREATE INDEX IF NOT EXISTS idx_decisions_symbol ON decisions(symbol);
CREATE INDEX IF NOT EXISTS idx_decisions_timestamp ON decisions(timestamp);
CREATE INDEX IF NOT EXISTS idx_console_date ON console_log(date);
CREATE INDEX IF NOT EXISTS idx_events_date ON system_events(date);
CREATE INDEX IF NOT EXISTS idx_selections_date ON stock_selections(date);
CREATE INDEX IF NOT EXISTS idx_positions_status ON positions(status);
'''


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN DATABASE MANAGER CLASS
# ═══════════════════════════════════════════════════════════════════════════════

class UnifiedDataManager:
    """
    Centralized data manager using SQLite.
    
    Thread-safe, singleton pattern for use across all modules.
    """
    
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls, db_path: str = "data/algo_beta.db"):
        """Singleton pattern - only one instance"""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self, db_path: str = "data/algo_beta.db"):
        """Initialize database connection"""
        if self._initialized:
            return
            
        self.db_path = db_path
        self._local = threading.local()
        
        # Ensure data directory exists
        os.makedirs(os.path.dirname(db_path) if os.path.dirname(db_path) else "data", exist_ok=True)
        
        # Initialize schema
        self._init_schema()

        # Migrate schema (add columns that didn't exist when DB was first created)
        self._migrate_db()

        # Today's date for daily operations
        self.today = datetime.now().strftime('%Y-%m-%d')

        # Ensure daily summary exists
        self._ensure_daily_summary()

        self._initialized = True
        logger.info(f"✅ UnifiedDataManager initialized: {db_path}")
    
    @property
    def conn(self) -> sqlite3.Connection:
        """Thread-local database connection"""
        if not hasattr(self._local, 'conn') or self._local.conn is None:
            self._local.conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self._local.conn.row_factory = sqlite3.Row
        return self._local.conn
    
    @contextmanager
    def transaction(self):
        """Context manager for transactions"""
        try:
            yield self.conn
            self.conn.commit()
        except Exception as e:
            self.conn.rollback()
            logger.error(f"Transaction failed: {e}")
            raise
    
    def _init_schema(self):
        """Create tables if not exist"""
        try:
            conn = sqlite3.connect(self.db_path)
            conn.executescript(SCHEMA)
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"Schema init failed: {e}")
            raise

    def _migrate_db(self):
        """Run schema migrations for columns added after initial DB creation.

        Each ALTER TABLE is wrapped in try/except so it's a no-op if the column
        already exists (SQLite raises 'duplicate column name' which we ignore).
        """
        migrations = [
            ("stock_selections", "scan_label", "TEXT"),
            ("trades", "source_phase", "TEXT"),
        ]
        try:
            conn = sqlite3.connect(self.db_path)
            for table, column, col_type in migrations:
                try:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
                    conn.commit()
                    logger.info(f"✅ DB migration: added {column} to {table}")
                except sqlite3.OperationalError as e:
                    if "duplicate column" in str(e).lower():
                        pass  # Column already exists — expected after first migration
                    else:
                        logger.warning(f"⚠️ DB migration warning ({table}.{column}): {e}")
            conn.close()
        except Exception as e:
            logger.warning(f"⚠️ DB migration failed: {e}")

    def _ensure_daily_summary(self):
        """Ensure today's summary row exists"""
        today = datetime.now()
        date_str = today.strftime('%Y-%m-%d')
        day_name = today.strftime('%A')
        
        try:
            cursor = self.conn.cursor()
            cursor.execute('''
                INSERT OR IGNORE INTO daily_summary (date, day_of_week, system_start_time)
                VALUES (?, ?, ?)
            ''', (date_str, day_name, datetime.now().isoformat()))
            self.conn.commit()
        except Exception as e:
            logger.error(f"Failed to ensure daily summary: {e}")
    
    # ═══════════════════════════════════════════════════════════════════════════
    # CONSOLE LOG - Capture CMD window output
    # ═══════════════════════════════════════════════════════════════════════════
    
    def log_console(self, message: str, level: str = "INFO", source: str = None):
        """
        Log console output - captures what you see in CMD window.
        
        This replaces the empty console_*.txt files!
        """
        now = datetime.now()
        try:
            cursor = self.conn.cursor()
            cursor.execute('''
                INSERT INTO console_log (date, timestamp, level, source, message)
                VALUES (?, ?, ?, ?, ?)
            ''', (
                now.strftime('%Y-%m-%d'),
                now.isoformat(),
                level,
                source,
                message[:10000]  # Limit message size
            ))
            self.conn.commit()
        except Exception as e:
            # Don't fail on logging errors
            pass
    
    def get_console_log(self, date_str: str = None, limit: int = 1000) -> List[Dict]:
        """Get console logs for a date"""
        date_str = date_str or datetime.now().strftime('%Y-%m-%d')
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT timestamp, level, source, message 
            FROM console_log 
            WHERE date = ?
            ORDER BY timestamp DESC
            LIMIT ?
        ''', (date_str, limit))
        return [dict(row) for row in cursor.fetchall()]
    
    def export_console_to_file(self, date_str: str = None) -> str:
        """Export console log to text file (human readable)"""
        date_str = date_str or datetime.now().strftime('%Y-%m-%d')
        logs = self.get_console_log(date_str, limit=10000)
        
        filepath = f"logs/console_{date_str.replace('-', '')}.txt"
        os.makedirs("logs", exist_ok=True)
        
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(f"CONSOLE LOG - {date_str}\n")
            f.write("=" * 80 + "\n\n")
            for log in reversed(logs):  # Chronological order
                f.write(f"{log['timestamp']} [{log['level']}] {log['source'] or ''}: {log['message']}\n")
        
        return filepath
    
    # ═══════════════════════════════════════════════════════════════════════════
    # SYSTEM EVENTS
    # ═══════════════════════════════════════════════════════════════════════════
    
    def log_event(self, event_type: str, category: str = None, 
                  details: Dict = None, severity: str = "INFO"):
        """Log a system event"""
        now = datetime.now()
        try:
            cursor = self.conn.cursor()
            cursor.execute('''
                INSERT INTO system_events (date, timestamp, event_type, category, details, severity)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (
                now.strftime('%Y-%m-%d'),
                now.isoformat(),
                event_type,
                category,
                json.dumps(details) if details else None,
                severity
            ))
            self.conn.commit()
            
            # Also log to console
            self.log_console(
                f"EVENT: {event_type} - {details}" if details else f"EVENT: {event_type}",
                level=severity,
                source=category
            )
        except Exception as e:
            logger.error(f"Failed to log event: {e}")
    
    # ═══════════════════════════════════════════════════════════════════════════
    # STOCK SELECTIONS (Phase 1)
    # ═══════════════════════════════════════════════════════════════════════════
    
    def save_stock_selection(self, scan_time: str, scan_label: str, stocks: List[Dict]):
        """
        Save Phase 1 stock selection results.
        
        Replaces: data/phase1_outputs/selected_stocks_*.json
        """
        now = datetime.now()
        date_str = now.strftime('%Y-%m-%d')
        
        try:
            cursor = self.conn.cursor()
            for stock in stocks:
                if isinstance(stock, dict):
                    symbol = stock.get('symbol', '')
                    # Phase 1 uses 'ltp' for price, fall back to 'price'
                    price = stock.get('price') or stock.get('ltp')
                    # RSI may be top-level or inside strategy_details
                    rsi = stock.get('rsi')
                    if rsi is None:
                        sd = stock.get('strategy_details') or {}
                        rsi = sd.get('rsi') or sd.get('rsi_value')
                    # Score may be top-level or 'strategy_score'
                    score = stock.get('score') or stock.get('strategy_score')
                else:
                    symbol = stock
                    price = rsi = score = None

                cursor.execute('''
                    INSERT INTO stock_selections
                    (date, scan_time, scan_label, symbol, price, rsi, rsi_percentile,
                     volume_ratio, atr_pct, score, filter_stage, selected, metadata)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    date_str,
                    scan_time,
                    scan_label,
                    symbol,
                    price,
                    rsi,
                    stock.get('rsi_percentile') if isinstance(stock, dict) else None,
                    stock.get('volume_ratio') if isinstance(stock, dict) else None,
                    stock.get('atr_pct') if isinstance(stock, dict) else None,
                    score,
                    stock.get('filter_stage', 0) if isinstance(stock, dict) else 0,
                    1,  # Selected
                    json.dumps(stock, default=str) if isinstance(stock, dict) else None
                ))
            
            self.conn.commit()
            
            # Update daily summary
            cursor.execute('''
                UPDATE daily_summary 
                SET stocks_selected = stocks_selected + ?
                WHERE date = ?
            ''', (len(stocks), date_str))
            self.conn.commit()
            
            # Log event
            self.log_event('PHASE1_SCAN', 'phase1', {
                'scan_time': scan_time,
                'scan_label': scan_label,
                'stocks_count': len(stocks),
                'stocks': [s.get('symbol') if isinstance(s, dict) else s for s in stocks]
            })
            
            logger.info(f"✅ Saved {len(stocks)} stock selections for {scan_label}")
            
        except Exception as e:
            logger.error(f"Failed to save stock selection: {e}")
    
    def get_active_selections(self, date_str: str = None) -> List[Dict]:
        """Get today's selected stocks"""
        date_str = date_str or datetime.now().strftime('%Y-%m-%d')
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT DISTINCT symbol, MAX(scan_time) as latest_scan, 
                   price, rsi, score, metadata
            FROM stock_selections 
            WHERE date = ? AND selected = 1
            GROUP BY symbol
            ORDER BY score DESC
        ''', (date_str,))
        return [dict(row) for row in cursor.fetchall()]
    
    # Also write ACTIVE.json for backward compatibility
    def save_active_json(self, stocks: List[Dict]):
        """Write ACTIVE.json for modules that still read it"""
        os.makedirs("data/phase1_outputs", exist_ok=True)
        filepath = "data/phase1_outputs/ACTIVE.json"
        with open(filepath, 'w') as f:
            json.dump({
                'scan_date': datetime.now().strftime('%Y%m%d'),
                'scan_time': datetime.now().strftime('%H:%M:%S'),
                'stocks': stocks
            }, f, indent=2)
    
    # ═══════════════════════════════════════════════════════════════════════════
    # KALMAN MAP CALIBRATION (Phase D)
    # ═══════════════════════════════════════════════════════════════════════════

    def save_kalman_calibration(self, symbol: str, calibration: Dict):
        """
        Save converged Kalman MAP Q/R matrices for warm start.

        Args:
            symbol: Stock symbol
            calibration: Dict with Q_converged, R_converged, observations, last_updated
        """
        try:
            q_json = json.dumps(calibration.get('Q_converged', []))
            r_json = json.dumps(calibration.get('R_converged', []))
            obs = calibration.get('observations', 0)
            updated = calibration.get('last_updated', datetime.now().isoformat())

            self.conn.execute('''
                INSERT OR REPLACE INTO kalman_calibration
                (symbol, q_matrix, r_matrix, observation_count, last_updated)
                VALUES (?, ?, ?, ?, ?)
            ''', (symbol, q_json, r_json, obs, updated))
            self.conn.commit()
            logger.debug(f"Kalman calibration saved: {symbol} ({obs} obs)")
        except Exception as e:
            logger.error(f"Kalman calibration save failed for {symbol}: {e}")

    def get_kalman_calibration(self, symbol: str, min_observations: int = 30) -> Optional[Dict]:
        """
        Load saved Kalman MAP calibration for warm start.

        Args:
            symbol: Stock symbol
            min_observations: Minimum observations for calibration to be trusted

        Returns:
            Dict with Q_converged, R_converged, observations or None
        """
        try:
            row = self.conn.execute(
                'SELECT * FROM kalman_calibration WHERE symbol = ?', (symbol,)
            ).fetchone()

            if row is None:
                return None

            obs = row['observation_count']
            if obs < min_observations:
                logger.debug(f"Kalman cal for {symbol}: only {obs} obs (need {min_observations})")
                return None

            return {
                'symbol': symbol,
                'Q_converged': json.loads(row['q_matrix']),
                'R_converged': json.loads(row['r_matrix']),
                'observations': obs,
                'last_updated': row['last_updated'],
            }
        except Exception as e:
            logger.error(f"Kalman calibration load failed for {symbol}: {e}")
            return None

    # ═══════════════════════════════════════════════════════════════════════════
    # TRADES
    # ═══════════════════════════════════════════════════════════════════════════

    def save_trade(self, trade: Dict):
        """
        Save a completed trade.
        
        Replaces: data/ml_training/trades_ml.csv rows
        """
        try:
            cursor = self.conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO trades (
                    trade_id, symbol, date, entry_time, exit_time,
                    entry_price, exit_price, quantity, direction,
                    pnl, pnl_pct, win, exit_reason, duration_minutes,
                    rsi_at_entry, volume_ratio, atr_pct, target_pct, stop_pct,
                    max_drawdown_pct, max_profit_pct, ai_confidence, source_phase,
                    metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                trade.get('trade_id'),
                trade.get('symbol'),
                trade.get('date'),
                trade.get('entry_time'),
                trade.get('exit_time'),
                trade.get('entry_price'),
                trade.get('exit_price'),
                trade.get('quantity', 1),
                trade.get('direction', 'LONG'),
                trade.get('pnl'),
                trade.get('pnl_pct'),
                1 if trade.get('pnl', 0) > 0 else 0,
                trade.get('exit_reason'),
                trade.get('duration_minutes'),
                trade.get('rsi'),
                trade.get('volume_ratio'),
                trade.get('atr_pct'),
                trade.get('target_pct'),
                trade.get('stop_pct'),
                trade.get('max_drawdown_pct'),
                trade.get('max_profit_pct'),
                trade.get('ai_confidence'),
                trade.get('source_phase') or trade.get('source'),
                json.dumps(trade)
            ))
            self.conn.commit()
            
            # Update daily summary
            pnl = trade.get('pnl', 0)
            win = 1 if pnl > 0 else 0
            cursor.execute('''
                UPDATE daily_summary 
                SET trades_executed = trades_executed + 1,
                    total_pnl = total_pnl + ?,
                    win_count = win_count + ?,
                    loss_count = loss_count + ?
                WHERE date = ?
            ''', (pnl, win, 1 - win, trade.get('date')))
            self.conn.commit()
            
            # Log event
            self.log_event('TRADE_COMPLETED', 'phase3', {
                'symbol': trade.get('symbol'),
                'pnl': pnl,
                'exit_reason': trade.get('exit_reason')
            })
            
            logger.info(f"✅ Trade saved: {trade.get('symbol')} P&L: ₹{pnl:.2f}")
            
        except Exception as e:
            logger.error(f"Failed to save trade: {e}")
    
    def get_trades(self, date_str: str = None, symbol: str = None, 
                   limit: int = 100) -> List[Dict]:
        """Get trades with optional filters"""
        cursor = self.conn.cursor()
        
        query = "SELECT * FROM trades WHERE 1=1"
        params = []
        
        if date_str:
            query += " AND date = ?"
            params.append(date_str)
        if symbol:
            query += " AND symbol = ?"
            params.append(symbol)
        
        query += " ORDER BY entry_time DESC LIMIT ?"
        params.append(limit)
        
        cursor.execute(query, params)
        return [dict(row) for row in cursor.fetchall()]
    
    def get_trade_stats(self, date_str: str = None) -> Dict:
        """Get trading statistics"""
        cursor = self.conn.cursor()
        
        if date_str:
            cursor.execute('''
                SELECT COUNT(*) as total,
                       SUM(CASE WHEN win = 1 THEN 1 ELSE 0 END) as wins,
                       SUM(CASE WHEN win = 0 THEN 1 ELSE 0 END) as losses,
                       SUM(pnl) as total_pnl,
                       AVG(pnl) as avg_pnl,
                       AVG(pnl_pct) as avg_pnl_pct
                FROM trades WHERE date = ?
            ''', (date_str,))
        else:
            cursor.execute('''
                SELECT COUNT(*) as total,
                       SUM(CASE WHEN win = 1 THEN 1 ELSE 0 END) as wins,
                       SUM(CASE WHEN win = 0 THEN 1 ELSE 0 END) as losses,
                       SUM(pnl) as total_pnl,
                       AVG(pnl) as avg_pnl,
                       AVG(pnl_pct) as avg_pnl_pct
                FROM trades
            ''')
        
        row = cursor.fetchone()
        if row:
            total = row['total'] or 0
            wins = row['wins'] or 0
            return {
                'total': total,
                'wins': wins,
                'losses': row['losses'] or 0,
                'win_rate': (wins / total * 100) if total > 0 else 0,
                'total_pnl': row['total_pnl'] or 0,
                'avg_pnl': row['avg_pnl'] or 0,
                'avg_pnl_pct': row['avg_pnl_pct'] or 0
            }
        return {}
    
    # ═══════════════════════════════════════════════════════════════════════════
    # POSITIONS
    # ═══════════════════════════════════════════════════════════════════════════
    
    def save_position(self, position: Dict):
        """Save/update a position"""
        try:
            cursor = self.conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO positions (
                    symbol, entry_time, entry_price, quantity, direction,
                    target_price, stop_price, current_price, unrealized_pnl,
                    status, metadata, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                position.get('symbol'),
                position.get('entry_time'),
                position.get('entry_price'),
                position.get('quantity', 1),
                position.get('direction', 'LONG'),
                position.get('target_price'),
                position.get('stop_price'),
                position.get('current_price'),
                position.get('unrealized_pnl'),
                position.get('status', 'OPEN'),
                json.dumps(position),
                datetime.now().isoformat()
            ))
            self.conn.commit()
        except Exception as e:
            logger.error(f"Failed to save position: {e}")
    
    def get_open_positions(self) -> List[Dict]:
        """Get all open positions"""
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT * FROM positions WHERE status = 'OPEN'
        ''')
        return [dict(row) for row in cursor.fetchall()]
    
    def close_position(self, symbol: str, exit_price: float, exit_reason: str):
        """Close a position"""
        try:
            cursor = self.conn.cursor()
            cursor.execute('''
                UPDATE positions 
                SET status = 'CLOSED',
                    exit_time = ?,
                    exit_price = ?,
                    exit_reason = ?,
                    updated_at = ?
                WHERE symbol = ? AND status = 'OPEN'
            ''', (
                datetime.now().isoformat(),
                exit_price,
                exit_reason,
                datetime.now().isoformat(),
                symbol
            ))
            self.conn.commit()
        except Exception as e:
            logger.error(f"Failed to close position: {e}")
    
    # ═══════════════════════════════════════════════════════════════════════════
    # DECISIONS (AI/ChatGPT)
    # ═══════════════════════════════════════════════════════════════════════════
    
    def save_decision(self, decision: Dict):
        """
        Save an AI decision.
        
        Replaces: data/decision_history/*.json files
        """
        try:
            cursor = self.conn.cursor()
            cursor.execute('''
                INSERT INTO decisions (
                    timestamp, symbol, decision, reason, confidence,
                    current_price, entry_price, target_price, stop_price,
                    net_pnl, prob_target, prob_stop, ev_hold, ev_exit,
                    outcome, outcome_price, actual_pnl, prediction_correct, metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                decision.get('timestamp') or datetime.now().isoformat(),
                decision.get('symbol'),
                decision.get('decision'),
                decision.get('reason'),
                decision.get('confidence'),
                decision.get('current_price'),
                decision.get('entry_price'),
                decision.get('target_price'),
                decision.get('stop_price'),
                decision.get('net_pnl'),
                decision.get('prob_target'),
                decision.get('prob_stop'),
                decision.get('ev_hold'),
                decision.get('ev_exit'),
                decision.get('outcome'),
                decision.get('outcome_price'),
                decision.get('actual_pnl'),
                decision.get('prediction_correct'),
                json.dumps(decision)
            ))
            self.conn.commit()
            
            self.log_console(
                f"DECISION: {decision.get('symbol')} → {decision.get('decision')} ({decision.get('reason')})",
                level="INFO",
                source="ChatGPT"
            )
            
        except Exception as e:
            logger.error(f"Failed to save decision: {e}")
    
    def get_decisions(self, symbol: str = None, limit: int = 100) -> List[Dict]:
        """Get decisions with optional symbol filter"""
        cursor = self.conn.cursor()
        
        if symbol:
            cursor.execute('''
                SELECT * FROM decisions WHERE symbol = ?
                ORDER BY timestamp DESC LIMIT ?
            ''', (symbol, limit))
        else:
            cursor.execute('''
                SELECT * FROM decisions
                ORDER BY timestamp DESC LIMIT ?
            ''', (limit,))
        
        return [dict(row) for row in cursor.fetchall()]
    
    # ═══════════════════════════════════════════════════════════════════════════
    # AI ANALYSIS
    # ═══════════════════════════════════════════════════════════════════════════
    
    def save_ai_analysis(self, analysis_type: str, content: str, 
                         stocks_scanned: int = 0, stocks_selected: int = 0,
                         market_condition: str = None):
        """
        Save AI/ChatGPT analysis.
        
        Replaces: data/ai_analysis_*.txt files
        """
        now = datetime.now()
        try:
            cursor = self.conn.cursor()
            cursor.execute('''
                INSERT INTO ai_analysis 
                (date, timestamp, analysis_type, stocks_scanned, stocks_selected, 
                 market_condition, content)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (
                now.strftime('%Y-%m-%d'),
                now.isoformat(),
                analysis_type,
                stocks_scanned,
                stocks_selected,
                market_condition,
                content[:50000]  # Limit content size
            ))
            self.conn.commit()
            
            self.log_console(
                f"AI Analysis: {analysis_type} - {stocks_selected} stocks selected",
                level="INFO",
                source="AI"
            )
            
        except Exception as e:
            logger.error(f"Failed to save AI analysis: {e}")
    
    # ═══════════════════════════════════════════════════════════════════════════
    # BROKER SNAPSHOTS
    # ═══════════════════════════════════════════════════════════════════════════
    
    def save_broker_snapshot(self, available_cash: float, used_margin: float,
                             positions: List[Dict], orders: List[Dict] = None):
        """
        Save broker state snapshot.
        
        Replaces: data/broker_state_*.json files
        """
        try:
            cursor = self.conn.cursor()
            cursor.execute('''
                INSERT INTO broker_snapshots 
                (timestamp, available_cash, used_margin, total_positions, 
                 positions_data, orders_data)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (
                datetime.now().isoformat(),
                available_cash,
                used_margin,
                len(positions),
                json.dumps(positions),
                json.dumps(orders) if orders else None
            ))
            self.conn.commit()
            
        except Exception as e:
            logger.error(f"Failed to save broker snapshot: {e}")
    
    # ═══════════════════════════════════════════════════════════════════════════
    # DAILY SUMMARY
    # ═══════════════════════════════════════════════════════════════════════════
    
    def update_daily_summary(self, **kwargs):
        """Update today's daily summary"""
        date_str = datetime.now().strftime('%Y-%m-%d')
        
        if not kwargs:
            return
        
        try:
            set_clause = ", ".join([f"{k} = ?" for k in kwargs.keys()])
            values = list(kwargs.values()) + [date_str]
            
            cursor = self.conn.cursor()
            cursor.execute(f'''
                UPDATE daily_summary SET {set_clause} WHERE date = ?
            ''', values)
            self.conn.commit()
        except Exception as e:
            logger.error(f"Failed to update daily summary: {e}")
    
    def get_daily_summary(self, date_str: str = None) -> Dict:
        """Get daily summary"""
        date_str = date_str or datetime.now().strftime('%Y-%m-%d')
        cursor = self.conn.cursor()
        cursor.execute('SELECT * FROM daily_summary WHERE date = ?', (date_str,))
        row = cursor.fetchone()
        return dict(row) if row else {}
    
    def finalize_day(self):
        """Finalize daily summary at market close"""
        now = datetime.now()
        date_str = now.strftime('%Y-%m-%d')
        
        # Get stats
        stats = self.get_trade_stats(date_str)
        
        self.update_daily_summary(
            system_end_time=now.isoformat(),
            runtime_minutes=(now - datetime.fromisoformat(
                self.get_daily_summary(date_str).get('system_start_time', now.isoformat())
            )).total_seconds() / 60 if self.get_daily_summary(date_str).get('system_start_time') else 0,
            trades_executed=stats.get('total', 0),
            total_pnl=stats.get('total_pnl', 0),
            win_count=stats.get('wins', 0),
            loss_count=stats.get('losses', 0)
        )
        
        # Export console log to file
        self.export_console_to_file(date_str)
        
        logger.info(f"✅ Day finalized: {date_str}")
    
    # ═══════════════════════════════════════════════════════════════════════════
    # QUERY UTILITIES
    # ═══════════════════════════════════════════════════════════════════════════
    
    def query(self, sql: str, params: tuple = None) -> List[Dict]:
        """Run custom SQL query"""
        cursor = self.conn.cursor()
        cursor.execute(sql, params or ())
        return [dict(row) for row in cursor.fetchall()]
    
    def get_win_rate_by_symbol(self) -> List[Dict]:
        """Get win rate by symbol"""
        return self.query('''
            SELECT symbol, 
                   COUNT(*) as total_trades,
                   SUM(CASE WHEN win = 1 THEN 1 ELSE 0 END) as wins,
                   ROUND(AVG(CASE WHEN win = 1 THEN 1.0 ELSE 0.0 END) * 100, 2) as win_rate,
                   ROUND(SUM(pnl), 2) as total_pnl,
                   ROUND(AVG(pnl), 2) as avg_pnl
            FROM trades
            GROUP BY symbol
            ORDER BY total_trades DESC
        ''')
    
    def get_recent_errors(self, limit: int = 20) -> List[Dict]:
        """Get recent errors"""
        return self.query('''
            SELECT timestamp, event_type, category, details
            FROM system_events
            WHERE severity = 'ERROR'
            ORDER BY timestamp DESC
            LIMIT ?
        ''', (limit,))


# ═══════════════════════════════════════════════════════════════════════════════
# CONSOLE LOGGING HANDLER (Captures print statements to database)
# ═══════════════════════════════════════════════════════════════════════════════

class DatabaseLogHandler(logging.Handler):
    """
    Custom logging handler that captures all log messages to database.
    
    This captures what you see in the CMD window!
    """
    
    def __init__(self, db_manager: UnifiedDataManager):
        super().__init__()
        self.db = db_manager
    
    def emit(self, record):
        try:
            msg = self.format(record)
            self.db.log_console(
                message=msg,
                level=record.levelname,
                source=record.name
            )
        except Exception:
            pass  # Don't fail on logging errors


# ═══════════════════════════════════════════════════════════════════════════════
# SINGLETON ACCESSOR
# ═══════════════════════════════════════════════════════════════════════════════

# Global instance for easy access
_db_instance: Optional[UnifiedDataManager] = None

def get_db() -> UnifiedDataManager:
    """Get the global database instance"""
    global _db_instance
    if _db_instance is None:
        _db_instance = UnifiedDataManager()
    return _db_instance


# ═══════════════════════════════════════════════════════════════════════════════
# BACKWARD COMPATIBILITY FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════════

def save_phase1_selection(scan_time: str, scan_label: str, stocks: List[Dict]):
    """Backward compatible function for Phase 1"""
    db = get_db()
    db.save_stock_selection(scan_time, scan_label, stocks)
    db.save_active_json(stocks)  # Keep ACTIVE.json for compatibility

def save_trade_record(trade: Dict):
    """Backward compatible function for trades"""
    get_db().save_trade(trade)

def save_decision_record(decision: Dict):
    """Backward compatible function for decisions"""
    get_db().save_decision(decision)

def save_broker_state(cash: float, margin: float, positions: List[Dict]):
    """Backward compatible function for broker state"""
    get_db().save_broker_snapshot(cash, margin, positions)


if __name__ == "__main__":
    # Test the database manager
    print("Testing UnifiedDataManager...")
    
    db = UnifiedDataManager("test_algo_beta.db")
    
    # Test console logging
    db.log_console("System started", level="INFO", source="TEST")
    db.log_console("Processing stocks...", level="INFO", source="Phase1")
    
    # Test event logging
    db.log_event("TEST_EVENT", "test", {"key": "value"})
    
    # Test stock selection
    db.save_stock_selection("10:00:00", "Morning Scan", [
        {"symbol": "RELIANCE", "price": 2500, "rsi": 35, "score": 85},
        {"symbol": "TCS", "price": 3800, "rsi": 32, "score": 82}
    ])
    
    # Test trade
    db.save_trade({
        "trade_id": "TEST_001",
        "symbol": "RELIANCE",
        "date": "2026-02-05",
        "entry_time": "2026-02-05T10:30:00",
        "exit_time": "2026-02-05T11:45:00",
        "entry_price": 2500,
        "exit_price": 2550,
        "pnl": 50,
        "exit_reason": "TARGET_HIT"
    })
    
    # Test decision
    db.save_decision({
        "symbol": "RELIANCE",
        "decision": "HOLD",
        "reason": "RSI improving",
        "confidence": 0.8,
        "current_price": 2520,
        "entry_price": 2500
    })
    
    # Print stats
    print("\n📊 Trade Stats:")
    print(db.get_trade_stats())
    
    print("\n📊 Win Rate by Symbol:")
    for row in db.get_win_rate_by_symbol():
        print(f"  {row}")
    
    print("\n📊 Console Log:")
    for log in db.get_console_log(limit=5):
        print(f"  {log['timestamp']}: {log['message']}")
    
    # Cleanup test
    import os
    os.remove("test_algo_beta.db")
    print("\n✅ Test completed successfully!")
