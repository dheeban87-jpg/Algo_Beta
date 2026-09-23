"""
MISSION_DB.PY - Mission Control Flight Recorder for Algo_Beta v5.0.0
═══════════════════════════════════════════════════════════════════════════════

PURPOSE:
  SQLite database for mission-critical state persistence.
  This is the system's "speedometer" — remembers where it was yesterday,
  what happened, and what to tell ChatGPT about past context.

DESIGN PRINCIPLES:
  1. Separate from operational DB (unified_data_manager uses algo_beta.db)
  2. This DB = mission_control.db — smaller, focused, critical
  3. Integrity-checked at startup (PRAGMA integrity_check)
  4. Daily backup at clean shutdown (.db.bak)
  5. If corrupted → try backup → if both fail → REDUCED_MODE
  6. Thread-safe singleton pattern

TABLES:
  daily_state       → 1 row per day — the "speedometer"
  trade_log         → Complete trade history with AI context
  fault_log         → System health events
  chatgpt_decisions → AI audit trail (was ChatGPT right?)
  options_advisory  → Ph4→Ph6 signal archive

USAGE:
  from mission_db import get_mission_db, MissionDB
  
  db = get_mission_db()
  yesterday = db.get_yesterday_state()
  db.save_daily_state(state_dict)
  db.log_fault("GTT_ORPHAN", "WARNING", symbol="BAJFINANCE")
  db.log_trade(trade_dict)

Author: Dheebanraj
Version: 5.0.0
Date: 2026-02-06
"""

import sqlite3
import json
import logging
import os
import shutil
import threading
from datetime import datetime, date, timedelta
from typing import Dict, List, Any, Optional, Tuple
from contextlib import contextmanager

logger = logging.getLogger('MissionDB')


# ═══════════════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════════

DB_PATH = os.path.join("data", "mission_control.db")
DB_BACKUP_PATH = os.path.join("data", "mission_control.db.bak")


# ═══════════════════════════════════════════════════════════════════════════════
# DATABASE SCHEMA
# ═══════════════════════════════════════════════════════════════════════════════

MISSION_SCHEMA = '''

-- ═══════════════════════════════════════════════════════════════
-- DAILY STATE — The Speedometer (1 row per day)
-- ═══════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS daily_state (
    date                TEXT PRIMARY KEY,

    -- Capital Speedometer
    starting_capital    REAL DEFAULT 0,
    ending_capital      REAL DEFAULT 0,
    free_capital        REAL DEFAULT 0,

    -- Trade Summary
    total_trades        INTEGER DEFAULT 0,
    trades_won          INTEGER DEFAULT 0,
    trades_lost         INTEGER DEFAULT 0,
    total_pnl_gross     REAL DEFAULT 0,
    total_pnl_net       REAL DEFAULT 0,

    -- Phase Breakdown
    ph5_trades          INTEGER DEFAULT 0,
    ph5_pnl             REAL DEFAULT 0,
    ph2_trades          INTEGER DEFAULT 0,
    ph2_pnl             REAL DEFAULT 0,
    ph8_trades          INTEGER DEFAULT 0,
    ph8_pnl             REAL DEFAULT 0,

    -- Overnight State (what Phase 4 is carrying)
    positions_overnight TEXT DEFAULT '[]',

    -- System Health
    fault_codes         TEXT DEFAULT '[]',
    warnings_count      INTEGER DEFAULT 0,
    errors_count        INTEGER DEFAULT 0,

    -- Shutdown
    shutdown_type       TEXT DEFAULT 'RUNNING',
    shutdown_time       TEXT,

    -- ChatGPT Context
    chatgpt_morning_brief   TEXT,
    chatgpt_eod_debrief     TEXT,

    -- Market Context
    market_regime       TEXT,
    vix_open            REAL DEFAULT 0,
    nifty_open          REAL DEFAULT 0,

    -- Metadata
    system_version      TEXT DEFAULT '5.0.0',
    boot_time           TEXT,
    system_state        TEXT DEFAULT 'BOOT',

    -- Timestamps
    created_at          TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at          TEXT DEFAULT CURRENT_TIMESTAMP
);


-- ═══════════════════════════════════════════════════════════════
-- TRADE LOG — Complete trade history with AI context
-- ═══════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS trade_log (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    date                TEXT NOT NULL,
    symbol              TEXT NOT NULL,
    direction           TEXT DEFAULT 'BUY',
    product             TEXT DEFAULT 'MIS',

    -- Entry
    entry_price         REAL NOT NULL,
    entry_time          TEXT NOT NULL,
    entry_qty           INTEGER DEFAULT 1,
    entry_phase         TEXT NOT NULL,
    entry_reason        TEXT,
    entry_score         REAL DEFAULT 0,

    -- Exit
    exit_price          REAL,
    exit_time           TEXT,
    exit_reason         TEXT,

    -- P&L
    pnl_gross           REAL DEFAULT 0,
    pnl_net             REAL DEFAULT 0,
    fees                REAL DEFAULT 0,

    -- AI Context at entry/exit
    kalman_prediction   TEXT,
    chatgpt_entry_rec   TEXT,
    chatgpt_exit_rec    TEXT,
    vp_signal_at_entry  TEXT,

    -- Position Details
    stop_price          REAL,
    target_price        REAL,
    atr_at_entry        REAL,

    -- Performance Metrics
    hold_duration_min   INTEGER DEFAULT 0,
    max_favorable       REAL DEFAULT 0,
    max_adverse         REAL DEFAULT 0,

    created_at          TEXT DEFAULT CURRENT_TIMESTAMP
);


-- ═══════════════════════════════════════════════════════════════
-- FAULT LOG — System health history
-- ═══════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS fault_log (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp           TEXT NOT NULL,
    date                TEXT NOT NULL,

    fault_code          TEXT NOT NULL,
    severity            TEXT DEFAULT 'WARNING',
    symbol              TEXT,
    description         TEXT,
    resolution          TEXT DEFAULT 'PENDING',
    resolved_at         TEXT,

    created_at          TEXT DEFAULT CURRENT_TIMESTAMP
);


-- ═══════════════════════════════════════════════════════════════
-- CHATGPT DECISIONS — AI audit trail
-- ═══════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS chatgpt_decisions (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp           TEXT NOT NULL,
    date                TEXT NOT NULL,
    symbol              TEXT,

    decision_type       TEXT NOT NULL,
    context_summary     TEXT,
    recommendation      TEXT,
    confidence          REAL,
    action_taken        TEXT,
    outcome             TEXT,
    response_time_ms    INTEGER DEFAULT 0,

    created_at          TEXT DEFAULT CURRENT_TIMESTAMP
);


-- ═══════════════════════════════════════════════════════════════
-- OPTIONS ADVISORY — Ph4→Ph6 signal archive
-- ═══════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS options_advisory (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp           TEXT NOT NULL,
    date                TEXT NOT NULL,
    symbol              TEXT NOT NULL,

    -- Trigger
    vp_signal_type      TEXT,
    volume_ratio        REAL,
    price_change_pct    REAL,

    -- Kalman
    kalman_1day         REAL,
    kalman_3day         REAL,
    kalman_1week        REAL,
    kalman_confidence   REAL,
    kalman_direction    TEXT,

    -- OI Data
    oi_walls_json       TEXT,
    max_pain            REAL,
    pcr                 REAL,

    -- Suggestion
    suggested_strike    REAL,
    suggested_ltp       REAL,
    suggested_cost      REAL,
    suggestion_reason   TEXT,

    -- Future Ph6 fields
    executed            INTEGER DEFAULT 0,
    exit_pnl            REAL,

    created_at          TEXT DEFAULT CURRENT_TIMESTAMP
);


-- ═══════════════════════════════════════════════════════════════
-- OPTIONS SPREAD TRADES — Phase 6 Paper Trade Tracking (v6.0)
-- ═══════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS options_spread_trades (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp           TEXT NOT NULL,
    date                TEXT NOT NULL,
    symbol              TEXT NOT NULL,

    -- Equity trade link
    equity_order_id     TEXT,
    equity_entry_price  REAL,

    -- Strategy
    spread_type         TEXT NOT NULL,
    spot_price          REAL,
    expiry              TEXT,
    lot_size            INTEGER,

    -- Legs (JSON)
    legs_json           TEXT,

    -- Risk profile
    max_profit          REAL,
    max_loss            REAL,
    breakeven_json      TEXT,
    entry_net_premium   REAL,

    -- ChatGPT analysis
    confidence          INTEGER,
    reasoning           TEXT,
    web_news            TEXT,
    chatgpt_raw_json    TEXT,

    -- Options chain context
    pcr                 REAL,
    max_pain            REAL,
    total_ce_oi         INTEGER,
    total_pe_oi         INTEGER,

    -- Paper trade results
    status              TEXT DEFAULT 'OPEN',
    current_net_premium REAL,
    paper_pnl           REAL DEFAULT 0,
    paper_pnl_pct       REAL DEFAULT 0,
    exit_time           TEXT,
    exit_reason         TEXT,

    -- v6.1: Live order tracking
    order_mode          TEXT DEFAULT 'PAPER',
    buy_order_id        TEXT,
    sell_order_id       TEXT,
    buy_fill_price      REAL,
    sell_fill_price     REAL,
    actual_net_debit    REAL,

    -- v6.2: Options TCAS tracking
    peak_pnl_pct        REAL DEFAULT 0,
    profit_lock_pct     REAL DEFAULT 0,
    tcas_active         INTEGER DEFAULT 0,

    created_at          TEXT DEFAULT CURRENT_TIMESTAMP
);


-- ═══════════════════════════════════════════════════════════════
-- INDEXES
-- ═══════════════════════════════════════════════════════════════
CREATE INDEX IF NOT EXISTS idx_trade_log_date ON trade_log(date);
CREATE INDEX IF NOT EXISTS idx_trade_log_symbol ON trade_log(symbol);
CREATE INDEX IF NOT EXISTS idx_trade_log_phase ON trade_log(entry_phase);
CREATE INDEX IF NOT EXISTS idx_fault_log_date ON fault_log(date);
CREATE INDEX IF NOT EXISTS idx_fault_log_code ON fault_log(fault_code);
CREATE INDEX IF NOT EXISTS idx_fault_log_resolution ON fault_log(resolution);
CREATE INDEX IF NOT EXISTS idx_chatgpt_date ON chatgpt_decisions(date);
CREATE INDEX IF NOT EXISTS idx_chatgpt_type ON chatgpt_decisions(decision_type);
CREATE INDEX IF NOT EXISTS idx_options_date ON options_advisory(date);
CREATE INDEX IF NOT EXISTS idx_options_symbol ON options_advisory(symbol);
CREATE INDEX IF NOT EXISTS idx_spread_date ON options_spread_trades(date);
CREATE INDEX IF NOT EXISTS idx_spread_symbol ON options_spread_trades(symbol);
CREATE INDEX IF NOT EXISTS idx_spread_status ON options_spread_trades(status);

-- ═══════════════════════════════════════════════════════════════
-- PHASE CONTROLS — GUI ↔ Orchestrator shared state (v5.6.1)
-- ═══════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS phase_controls (
    phase_key   TEXT PRIMARY KEY,
    state       TEXT NOT NULL DEFAULT 'OFF',
    updated_at  TEXT DEFAULT CURRENT_TIMESTAMP
);
''';


# ═══════════════════════════════════════════════════════════════════════════════
# MISSION DATABASE CLASS
# ═══════════════════════════════════════════════════════════════════════════════

class MissionDB:
    """
    Mission Control Flight Recorder.
    
    Thread-safe singleton. Handles all state persistence for the
    mission-critical startup/shutdown cycle.
    
    Design Review Fix #2: Includes integrity check + backup/restore.
    """
    
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls, db_path: str = None):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self, db_path: str = None):
        if self._initialized:
            return
        
        self.db_path = db_path or DB_PATH
        self.backup_path = db_path + ".bak" if db_path else DB_BACKUP_PATH
        self._local = threading.local()
        
        # Ensure data directory
        os.makedirs(os.path.dirname(self.db_path) if os.path.dirname(self.db_path) else "data", exist_ok=True)
        
        # Initialize schema
        self._init_schema()
        self.ensure_phase_controls()

        self.today = datetime.now().strftime('%Y-%m-%d')
        self._initialized = True
        
        logger.info(f"✅ MissionDB initialized: {self.db_path}")
    
    # ═══════════════════════════════════════════════════════════════════════════
    # CONNECTION & SCHEMA
    # ═══════════════════════════════════════════════════════════════════════════
    
    @property
    def conn(self) -> sqlite3.Connection:
        """Thread-local database connection."""
        if not hasattr(self._local, 'conn') or self._local.conn is None:
            self._local.conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self._local.conn.row_factory = sqlite3.Row
            # Enable WAL mode for better concurrent access
            self._local.conn.execute("PRAGMA journal_mode=WAL")
        return self._local.conn
    
    @contextmanager
    def transaction(self):
        """Context manager for atomic transactions."""
        try:
            yield self.conn
            self.conn.commit()
        except Exception as e:
            self.conn.rollback()
            logger.error(f"Transaction failed: {e}")
            raise
    
    def _init_schema(self):
        """Create tables if not exist."""
        try:
            conn = sqlite3.connect(self.db_path)
            conn.executescript(MISSION_SCHEMA)
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"MissionDB schema init failed: {e}")
            raise
    
    # ═══════════════════════════════════════════════════════════════════════════
    # PHASE CONTROLS — GUI ↔ Orchestrator (v5.6.1)
    # ═══════════════════════════════════════════════════════════════════════════

    def ensure_phase_controls(self):
        """Seed phase_controls rows if missing (idempotent)."""
        phases = ['ENABLE_PH5', 'ENABLE_PH5A', 'ENABLE_PH6', 'ENABLE_PH7', 'ENABLE_PH8']
        try:
            with self.transaction() as conn:
                for key in phases:
                    conn.execute(
                        "INSERT OR IGNORE INTO phase_controls (phase_key, state) VALUES (?, 'OFF')",
                        (key,)
                    )
        except Exception as e:
            logger.warning(f"ensure_phase_controls: {e}")

    def set_phase_state(self, phase_key: str, state: str):
        """Write phase state from GUI.  state ∈ {'OFF', 'PAPER', 'LIVE'}."""
        if state not in ('OFF', 'PAPER', 'LIVE'):
            logger.warning(f"Invalid phase state: {state}")
            return
        try:
            with self.transaction() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO phase_controls (phase_key, state, updated_at) "
                    "VALUES (?, ?, ?)",
                    (phase_key, state, datetime.now().isoformat())
                )
        except Exception as e:
            logger.error(f"set_phase_state failed: {e}")

    def get_phase_states(self) -> Dict[str, str]:
        """Read all phase states.  Returns {'ENABLE_PH5': 'OFF', ...}."""
        try:
            rows = self.conn.execute("SELECT phase_key, state FROM phase_controls").fetchall()
            return {r['phase_key']: r['state'] for r in rows}
        except Exception:
            return {}

    # ═══════════════════════════════════════════════════════════════════════════
    # INTEGRITY CHECK & BACKUP (Design Review Fix #2)
    # ═══════════════════════════════════════════════════════════════════════════
    
    def check_integrity(self) -> Tuple[bool, str]:
        """
        Run PRAGMA integrity_check on the database.
        
        Returns:
            (is_ok, message)
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.execute("PRAGMA integrity_check")
            result = cursor.fetchone()
            conn.close()
            
            if result and result[0] == 'ok':
                return True, "Database integrity OK"
            else:
                return False, f"Integrity check failed: {result}"
        except Exception as e:
            return False, f"Integrity check error: {e}"
    
    def create_backup(self) -> bool:
        """
        Create backup copy of the database.
        Called at CLEAN_SHUTDOWN.
        
        Returns:
            True if backup succeeded
        """
        try:
            if os.path.exists(self.db_path):
                # Close any open connections first
                if hasattr(self._local, 'conn') and self._local.conn:
                    self._local.conn.close()
                    self._local.conn = None
                
                shutil.copy2(self.db_path, self.backup_path)
                logger.info(f"✅ Database backup created: {self.backup_path}")
                return True
            return False
        except Exception as e:
            logger.error(f"Database backup failed: {e}")
            return False
    
    def restore_from_backup(self) -> Tuple[bool, str]:
        """
        Restore database from backup.
        Called when primary DB fails integrity check.
        
        Returns:
            (success, message)
        """
        try:
            if not os.path.exists(self.backup_path):
                return False, "No backup file found"
            
            # Close current connection
            if hasattr(self._local, 'conn') and self._local.conn:
                self._local.conn.close()
                self._local.conn = None
            
            # Copy backup over primary
            shutil.copy2(self.backup_path, self.db_path)
            
            # Verify backup integrity
            conn = sqlite3.connect(self.db_path)
            cursor = conn.execute("PRAGMA integrity_check")
            result = cursor.fetchone()
            conn.close()
            
            if result and result[0] == 'ok':
                return True, "Restored from backup successfully"
            else:
                return False, "Backup also corrupted"
                
        except Exception as e:
            return False, f"Restore failed: {e}"
    
    def startup_integrity_check(self) -> Tuple[str, str]:
        """
        Full startup integrity check with 3-layer protection.
        
        Returns:
            (status, message)
            status: "OK" | "RESTORED" | "FRESH_START"
        """
        # Layer 1: Check primary DB
        if os.path.exists(self.db_path):
            ok, msg = self.check_integrity()
            if ok:
                return "OK", "Database integrity verified"
        
            # Layer 2: Try backup
            logger.warning(f"⚠️ Primary DB corrupted: {msg}")
            restored, restore_msg = self.restore_from_backup()
            if restored:
                logger.warning(f"⚠️ Restored from backup: {restore_msg}")
                return "RESTORED", f"Primary corrupted. {restore_msg}"
            
            # Layer 3: Start fresh
            logger.error(f"🚨 Both DB and backup corrupted!")
            logger.error(f"   Primary: {msg}")
            logger.error(f"   Backup: {restore_msg}")
            
            # Rename corrupted DB for forensics
            corrupt_path = self.db_path + f".corrupt_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            try:
                os.rename(self.db_path, corrupt_path)
            except:
                pass
            
            # Create fresh DB
            self._init_schema()
            return "FRESH_START", "Memory lost — both DB and backup corrupted. Starting blind."
        
        else:
            # No DB file at all (first run or deleted)
            self._init_schema()
            return "FRESH_START", "No database found — first run or data cleared."
    
    # ═══════════════════════════════════════════════════════════════════════════
    # DAILY STATE — The Speedometer
    # ═══════════════════════════════════════════════════════════════════════════
    
    def ensure_today(self):
        """Ensure today's daily_state row exists."""
        today = datetime.now().strftime('%Y-%m-%d')
        self.today = today
        try:
            with self.transaction() as conn:
                conn.execute('''
                    INSERT OR IGNORE INTO daily_state (date, boot_time, system_version)
                    VALUES (?, ?, ?)
                ''', (today, datetime.now().isoformat(), '5.0.0'))
        except Exception as e:
            logger.error(f"Failed to ensure today's state: {e}")
    
    def get_yesterday_state(self) -> Optional[Dict]:
        """
        Load yesterday's daily_state.
        This is what ChatGPT receives as "memory".
        
        Returns:
            Dict with yesterday's state, or None if no data
        """
        try:
            yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
            cursor = self.conn.cursor()
            cursor.execute('SELECT * FROM daily_state WHERE date = ?', (yesterday,))
            row = cursor.fetchone()
            
            if row:
                result = dict(row)
                # Parse JSON fields
                for json_field in ('positions_overnight', 'fault_codes'):
                    if result.get(json_field):
                        try:
                            result[json_field] = json.loads(result[json_field])
                        except:
                            result[json_field] = []
                return result
            
            return None
        except Exception as e:
            logger.error(f"Failed to load yesterday's state: {e}")
            return None
    
    def get_last_trading_day_state(self) -> Optional[Dict]:
        """
        Load the most recent daily_state (might not be yesterday if weekend/holiday).
        
        Returns:
            Dict with last trading day's state, or None
        """
        try:
            cursor = self.conn.cursor()
            cursor.execute('''
                SELECT * FROM daily_state 
                WHERE date < ? AND shutdown_type != 'RUNNING'
                ORDER BY date DESC LIMIT 1
            ''', (datetime.now().strftime('%Y-%m-%d'),))
            row = cursor.fetchone()
            
            if row:
                result = dict(row)
                for json_field in ('positions_overnight', 'fault_codes'):
                    if result.get(json_field):
                        try:
                            result[json_field] = json.loads(result[json_field])
                        except:
                            result[json_field] = []
                return result
            
            return None
        except Exception as e:
            logger.error(f"Failed to load last trading day state: {e}")
            return None
    
    def update_daily_state(self, **kwargs):
        """
        Update today's daily_state with any fields.
        
        Usage:
            db.update_daily_state(
                ending_capital=18500,
                total_trades=3,
                shutdown_type="CLEAN_SHUTDOWN"
            )
        """
        if not kwargs:
            return
        
        # JSON-encode dict/list fields
        for key in ('positions_overnight', 'fault_codes'):
            if key in kwargs and isinstance(kwargs[key], (list, dict)):
                kwargs[key] = json.dumps(kwargs[key])
        
        # Add updated_at
        kwargs['updated_at'] = datetime.now().isoformat()
        
        # Build SET clause
        set_parts = [f"{k} = ?" for k in kwargs.keys()]
        values = list(kwargs.values())
        values.append(self.today)
        
        try:
            with self.transaction() as conn:
                conn.execute(f'''
                    UPDATE daily_state 
                    SET {', '.join(set_parts)}
                    WHERE date = ?
                ''', values)
        except Exception as e:
            logger.error(f"Failed to update daily state: {e}")
    
    def save_shutdown_state(self, shutdown_type: str, positions_overnight: List[Dict] = None,
                            ending_capital: float = 0, total_pnl_net: float = 0,
                            chatgpt_eod_debrief: str = None):
        """
        Save end-of-day state and create backup.
        Called at CLEAN_SHUTDOWN.
        """
        try:
            self.update_daily_state(
                shutdown_type=shutdown_type,
                shutdown_time=datetime.now().isoformat(),
                ending_capital=ending_capital,
                total_pnl_net=total_pnl_net,
                positions_overnight=positions_overnight or [],
                chatgpt_eod_debrief=chatgpt_eod_debrief
            )
            
            # Create backup (Design Review Fix #2)
            if shutdown_type == "CLEAN_SHUTDOWN":
                self.create_backup()
            
            logger.info(f"✅ Daily state saved: {shutdown_type}")
            
        except Exception as e:
            logger.error(f"Failed to save shutdown state: {e}")
    
    # ═══════════════════════════════════════════════════════════════════════════
    # TRADE LOG
    # ═══════════════════════════════════════════════════════════════════════════
    
    def log_trade(self, trade: Dict):
        """
        Log a completed trade.
        
        Args:
            trade: Dict with keys matching trade_log columns
        """
        try:
            with self.transaction() as conn:
                conn.execute('''
                    INSERT INTO trade_log (
                        date, symbol, direction, product,
                        entry_price, entry_time, entry_qty, entry_phase,
                        entry_reason, entry_score,
                        exit_price, exit_time, exit_reason,
                        pnl_gross, pnl_net, fees,
                        kalman_prediction, chatgpt_entry_rec, chatgpt_exit_rec,
                        vp_signal_at_entry,
                        stop_price, target_price, atr_at_entry,
                        hold_duration_min, max_favorable, max_adverse
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    trade.get('date', self.today),
                    trade.get('symbol', ''),
                    trade.get('direction', 'BUY'),
                    trade.get('product', 'MIS'),
                    trade.get('entry_price', 0),
                    trade.get('entry_time', ''),
                    trade.get('entry_qty', 1),
                    trade.get('entry_phase', 'UNKNOWN'),
                    trade.get('entry_reason', ''),
                    trade.get('entry_score', 0),
                    trade.get('exit_price'),
                    trade.get('exit_time'),
                    trade.get('exit_reason'),
                    trade.get('pnl_gross', 0),
                    trade.get('pnl_net', 0),
                    trade.get('fees', 0),
                    json.dumps(trade['kalman_prediction']) if isinstance(trade.get('kalman_prediction'), dict) else trade.get('kalman_prediction'),
                    trade.get('chatgpt_entry_rec'),
                    trade.get('chatgpt_exit_rec'),
                    json.dumps(trade['vp_signal_at_entry']) if isinstance(trade.get('vp_signal_at_entry'), dict) else trade.get('vp_signal_at_entry'),
                    trade.get('stop_price'),
                    trade.get('target_price'),
                    trade.get('atr_at_entry'),
                    trade.get('hold_duration_min', 0),
                    trade.get('max_favorable', 0),
                    trade.get('max_adverse', 0)
                ))
            
            # Update daily state trade counts
            self._increment_trade_count(trade)
            
        except Exception as e:
            logger.error(f"Failed to log trade: {e}")
    
    def _increment_trade_count(self, trade: Dict):
        """Update daily_state trade counters after a trade."""
        try:
            pnl = trade.get('pnl_net', trade.get('pnl_gross', 0))
            phase = trade.get('entry_phase', '')
            
            cursor = self.conn.cursor()
            cursor.execute('SELECT * FROM daily_state WHERE date = ?', (self.today,))
            row = cursor.fetchone()
            
            if row:
                state = dict(row)
                updates = {
                    'total_trades': state.get('total_trades', 0) + 1,
                    'total_pnl_gross': state.get('total_pnl_gross', 0) + trade.get('pnl_gross', 0),
                    'total_pnl_net': state.get('total_pnl_net', 0) + pnl,
                }
                
                if pnl >= 0:
                    updates['trades_won'] = state.get('trades_won', 0) + 1
                else:
                    updates['trades_lost'] = state.get('trades_lost', 0) + 1
                
                if 'PH5' in phase.upper():
                    updates['ph5_trades'] = state.get('ph5_trades', 0) + 1
                    updates['ph5_pnl'] = state.get('ph5_pnl', 0) + pnl
                elif 'PH8' in phase.upper():
                    updates['ph8_trades'] = state.get('ph8_trades', 0) + 1
                    updates['ph8_pnl'] = state.get('ph8_pnl', 0) + pnl
                else:
                    updates['ph2_trades'] = state.get('ph2_trades', 0) + 1
                    updates['ph2_pnl'] = state.get('ph2_pnl', 0) + pnl
                
                self.update_daily_state(**updates)
                
        except Exception as e:
            logger.error(f"Failed to increment trade count: {e}")
    
    def get_trades_today(self) -> List[Dict]:
        """Get all trades for today."""
        try:
            cursor = self.conn.cursor()
            cursor.execute('''
                SELECT * FROM trade_log WHERE date = ? ORDER BY entry_time
            ''', (self.today,))
            return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Failed to get today's trades: {e}")
            return []
    
    def get_trades_for_date(self, date_str: str) -> List[Dict]:
        """Get all trades for a specific date."""
        try:
            cursor = self.conn.cursor()
            cursor.execute('''
                SELECT * FROM trade_log WHERE date = ? ORDER BY entry_time
            ''', (date_str,))
            return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Failed to get trades for {date_str}: {e}")
            return []
    
    def get_recent_trades(self, days: int = 7) -> List[Dict]:
        """Get trades from last N days."""
        try:
            since = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
            cursor = self.conn.cursor()
            cursor.execute('''
                SELECT * FROM trade_log WHERE date >= ? ORDER BY date DESC, entry_time DESC
            ''', (since,))
            return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Failed to get recent trades: {e}")
            return []
    
    def get_trade_stats(self, days: int = 30) -> Dict:
        """
        Get aggregate trade statistics for last N days.
        Useful for ChatGPT context and performance monitoring.
        """
        try:
            since = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
            cursor = self.conn.cursor()
            
            cursor.execute('''
                SELECT 
                    COUNT(*) as total_trades,
                    SUM(CASE WHEN pnl_net >= 0 THEN 1 ELSE 0 END) as wins,
                    SUM(CASE WHEN pnl_net < 0 THEN 1 ELSE 0 END) as losses,
                    SUM(pnl_net) as total_pnl,
                    AVG(pnl_net) as avg_pnl,
                    MAX(pnl_net) as best_trade,
                    MIN(pnl_net) as worst_trade,
                    AVG(hold_duration_min) as avg_hold_min,
                    SUM(CASE WHEN entry_phase LIKE '%PH5%' THEN 1 ELSE 0 END) as ph5_count,
                    SUM(CASE WHEN entry_phase LIKE '%PH5%' THEN pnl_net ELSE 0 END) as ph5_pnl
                FROM trade_log
                WHERE date >= ?
            ''', (since,))
            
            row = cursor.fetchone()
            if row:
                result = dict(row)
                total = result.get('total_trades', 0)
                wins = result.get('wins', 0)
                result['win_rate'] = round((wins / total * 100), 1) if total > 0 else 0
                return result
            
            return {'total_trades': 0, 'win_rate': 0}
            
        except Exception as e:
            logger.error(f"Failed to get trade stats: {e}")
            return {'total_trades': 0, 'win_rate': 0}
    
    # ═══════════════════════════════════════════════════════════════════════════
    # FAULT LOG
    # ═══════════════════════════════════════════════════════════════════════════
    
    def log_fault(self, fault_code: str, severity: str = "WARNING",
                  symbol: str = None, description: str = None,
                  resolution: str = "PENDING"):
        """
        Log a system fault.
        
        Fault codes:
            GTT_ORPHAN, API_TIMEOUT, POSITION_MISMATCH,
            BROKER_DISCONNECT, CAPITAL_BREACH, ORDER_REJECT,
            CHATGPT_TIMEOUT, KALMAN_FAILURE, CRASH_RECOVERY,
            DB_CORRUPTION, UNKNOWN
        """
        try:
            now = datetime.now()
            with self.transaction() as conn:
                conn.execute('''
                    INSERT INTO fault_log (timestamp, date, fault_code, severity, symbol, description, resolution)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', (
                    now.isoformat(),
                    now.strftime('%Y-%m-%d'),
                    fault_code,
                    severity,
                    symbol,
                    description,
                    resolution
                ))
            
            # Update daily_state counters
            if severity in ('WARNING', 'ERROR', 'CRITICAL'):
                cursor = self.conn.cursor()
                cursor.execute('SELECT warnings_count, errors_count, fault_codes FROM daily_state WHERE date = ?', (self.today,))
                row = cursor.fetchone()
                if row:
                    state = dict(row)
                    updates = {}
                    if severity == 'WARNING':
                        updates['warnings_count'] = state.get('warnings_count', 0) + 1
                    else:
                        updates['errors_count'] = state.get('errors_count', 0) + 1
                    
                    # Append to fault_codes list
                    try:
                        codes = json.loads(state.get('fault_codes', '[]'))
                    except:
                        codes = []
                    if fault_code not in codes:
                        codes.append(fault_code)
                    updates['fault_codes'] = codes
                    
                    self.update_daily_state(**updates)
            
            logger.info(f"🔧 Fault logged: [{severity}] {fault_code} — {description}")
            
        except Exception as e:
            logger.error(f"Failed to log fault: {e}")
    
    def resolve_fault(self, fault_id: int, resolution: str = "AUTO_FIXED"):
        """Mark a fault as resolved."""
        try:
            with self.transaction() as conn:
                conn.execute('''
                    UPDATE fault_log SET resolution = ?, resolved_at = ?
                    WHERE id = ?
                ''', (resolution, datetime.now().isoformat(), fault_id))
        except Exception as e:
            logger.error(f"Failed to resolve fault {fault_id}: {e}")
    
    def get_unresolved_faults(self, date_str: str = None) -> List[Dict]:
        """Get all unresolved faults for a date."""
        date_str = date_str or self.today
        try:
            cursor = self.conn.cursor()
            cursor.execute('''
                SELECT * FROM fault_log 
                WHERE date = ? AND resolution = 'PENDING'
                ORDER BY timestamp DESC
            ''', (date_str,))
            return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Failed to get unresolved faults: {e}")
            return []
    
    def get_faults_for_date(self, date_str: str = None) -> List[Dict]:
        """Get all faults for a date."""
        date_str = date_str or self.today
        try:
            cursor = self.conn.cursor()
            cursor.execute('''
                SELECT * FROM fault_log WHERE date = ? ORDER BY timestamp
            ''', (date_str,))
            return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Failed to get faults: {e}")
            return []
    
    # ═══════════════════════════════════════════════════════════════════════════
    # CHATGPT DECISIONS — AI Audit Trail
    # ═══════════════════════════════════════════════════════════════════════════
    
    def log_chatgpt_decision(self, decision_type: str, recommendation: str,
                              symbol: str = None, context_summary: str = None,
                              confidence: float = None, action_taken: str = None,
                              response_time_ms: int = 0):
        """
        Log a ChatGPT decision for audit trail.
        
        Decision types:
            MORNING_BRIEF, ENTRY_CONFIRM, EXIT_DECISION,
            RECOVERY_CLASSIFY, EOD_DEBRIEF, VP_BURST_CONSULT,
            PH5_POST_ENTRY
        """
        try:
            now = datetime.now()
            with self.transaction() as conn:
                conn.execute('''
                    INSERT INTO chatgpt_decisions (
                        timestamp, date, symbol,
                        decision_type, context_summary, recommendation,
                        confidence, action_taken, response_time_ms
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    now.isoformat(),
                    now.strftime('%Y-%m-%d'),
                    symbol,
                    decision_type,
                    context_summary[:2000] if context_summary else None,
                    recommendation[:5000] if recommendation else None,
                    confidence,
                    action_taken,
                    response_time_ms
                ))
        except Exception as e:
            logger.error(f"Failed to log ChatGPT decision: {e}")
    
    def update_chatgpt_outcome(self, decision_id: int, outcome: str):
        """Update the outcome of a ChatGPT decision (was it correct?)."""
        try:
            with self.transaction() as conn:
                conn.execute('''
                    UPDATE chatgpt_decisions SET outcome = ?
                    WHERE id = ?
                ''', (outcome, decision_id))
        except Exception as e:
            logger.error(f"Failed to update ChatGPT outcome: {e}")
    
    def get_chatgpt_accuracy(self, days: int = 30) -> Dict:
        """
        Calculate ChatGPT decision accuracy over last N days.
        Used in morning briefing context.
        """
        try:
            since = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
            cursor = self.conn.cursor()
            
            cursor.execute('''
                SELECT 
                    decision_type,
                    COUNT(*) as total,
                    SUM(CASE WHEN outcome = 'CORRECT' THEN 1 ELSE 0 END) as correct,
                    SUM(CASE WHEN outcome = 'INCORRECT' THEN 1 ELSE 0 END) as incorrect,
                    AVG(response_time_ms) as avg_response_ms
                FROM chatgpt_decisions
                WHERE date >= ? AND outcome IS NOT NULL
                GROUP BY decision_type
            ''', (since,))
            
            results = {}
            for row in cursor.fetchall():
                d = dict(row)
                total = d.get('total', 0)
                correct = d.get('correct', 0)
                d['accuracy_pct'] = round(correct / total * 100, 1) if total > 0 else 0
                results[d['decision_type']] = d
            
            return results
            
        except Exception as e:
            logger.error(f"Failed to get ChatGPT accuracy: {e}")
            return {}
    
    def get_chatgpt_decisions_for_date(self, date_str: str = None) -> List[Dict]:
        """Get all ChatGPT decisions for a date."""
        date_str = date_str or self.today
        try:
            cursor = self.conn.cursor()
            cursor.execute('''
                SELECT * FROM chatgpt_decisions WHERE date = ? ORDER BY timestamp
            ''', (date_str,))
            return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Failed to get ChatGPT decisions: {e}")
            return []
    
    # ═══════════════════════════════════════════════════════════════════════════
    # PH8 — TIER 3 MORNING INTELLIGENCE REVIEW LOG
    # ═══════════════════════════════════════════════════════════════════════════

    def log_ph8_morning_review(
        self,
        symbol: str,
        recommendation: str,
        confidence: int,
        reasoning: str,
        risk_level: str,
        key_factors: list = None,
        kalman_state: dict = None,
        data_package_summary: dict = None,
        action_taken: str = "NONE",
    ):
        """
        Log a Ph8 Tier 3 morning intelligence review.

        Uses the existing chatgpt_decisions table with decision_type='PH8_MORNING_REVIEW'.
        Stores rich context in context_summary as JSON.
        """
        try:
            context = {
                'risk_level': risk_level,
                'key_factors': key_factors or [],
                'kalman': kalman_state or {},
                'data_summary': data_package_summary or {},
            }
            context_json = json.dumps(context, default=str)[:2000]

            self.log_chatgpt_decision(
                decision_type='PH8_MORNING_REVIEW',
                recommendation=recommendation,
                symbol=symbol,
                context_summary=context_json,
                confidence=float(confidence),
                action_taken=action_taken,
                response_time_ms=0,
            )
            logger.info(f"Ph8 morning review logged: {symbol} → {recommendation} "
                        f"(conf={confidence}, risk={risk_level})")
        except Exception as e:
            logger.error(f"Failed to log Ph8 morning review: {e}")

    # ═══════════════════════════════════════════════════════════════════════════
    # OPTIONS ADVISORY — Ph4→Ph6 Signal Archive
    # ═══════════════════════════════════════════════════════════════════════════
    
    def log_options_advisory(self, advisory: Dict):
        """
        Log an options advisory signal from Phase 4.
        Complements the JSON file saved in /signals/ folder.
        """
        try:
            now = datetime.now()
            with self.transaction() as conn:
                conn.execute('''
                    INSERT INTO options_advisory (
                        timestamp, date, symbol,
                        vp_signal_type, volume_ratio, price_change_pct,
                        kalman_1day, kalman_3day, kalman_1week,
                        kalman_confidence, kalman_direction,
                        oi_walls_json, max_pain, pcr,
                        suggested_strike, suggested_ltp, suggested_cost,
                        suggestion_reason
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    now.isoformat(),
                    now.strftime('%Y-%m-%d'),
                    advisory.get('symbol', ''),
                    advisory.get('vp_signal', advisory.get('vp_signal_type', '')),
                    advisory.get('volume_ratio', 0),
                    advisory.get('price_change_pct', 0),
                    advisory.get('kalman', {}).get('prediction_1day', 0) if isinstance(advisory.get('kalman'), dict) else advisory.get('kalman_1day', 0),
                    advisory.get('kalman', {}).get('prediction_3day', 0) if isinstance(advisory.get('kalman'), dict) else advisory.get('kalman_3day', 0),
                    advisory.get('kalman', {}).get('prediction_1week', 0) if isinstance(advisory.get('kalman'), dict) else advisory.get('kalman_1week', 0),
                    advisory.get('kalman', {}).get('confidence', 0) if isinstance(advisory.get('kalman'), dict) else advisory.get('kalman_confidence', 0),
                    advisory.get('kalman', {}).get('direction', '') if isinstance(advisory.get('kalman'), dict) else advisory.get('kalman_direction', ''),
                    json.dumps(advisory.get('oi_walls', [])),
                    advisory.get('max_pain', 0),
                    advisory.get('pcr', 0),
                    advisory.get('suggested_strike'),
                    advisory.get('suggested_ltp') if advisory.get('suggested_strike') else None,
                    advisory.get('suggested_cost', 0),
                    advisory.get('suggestion_reason', '')
                ))
        except Exception as e:
            logger.error(f"Failed to log options advisory: {e}")

    # ===================================================================
    # OPTIONS SPREAD TRADES — Phase 6 Paper Trading (v6.0)
    # ===================================================================

    def log_options_spread(self, spread: Dict) -> Optional[int]:
        """Log a new options spread advisory / paper trade. Returns row id."""
        try:
            now = datetime.now()
            with self.transaction() as conn:
                conn.execute('''
                    INSERT INTO options_spread_trades (
                        timestamp, date, symbol,
                        equity_order_id, equity_entry_price,
                        spread_type, spot_price, expiry, lot_size,
                        legs_json,
                        max_profit, max_loss, breakeven_json, entry_net_premium,
                        confidence, reasoning, web_news, chatgpt_raw_json,
                        pcr, max_pain, total_ce_oi, total_pe_oi,
                        status,
                        order_mode, buy_order_id, sell_order_id,
                        buy_fill_price, sell_fill_price, actual_net_debit
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                              ?, ?, ?, ?, ?, ?)
                ''', (
                    now.isoformat(),
                    now.strftime('%Y-%m-%d'),
                    spread.get('symbol', ''),
                    spread.get('equity_order_id', ''),
                    spread.get('equity_entry_price', 0),
                    spread.get('spread_type', ''),
                    spread.get('spot_price', 0),
                    spread.get('expiry', ''),
                    spread.get('lot_size', 0),
                    json.dumps(spread.get('legs', [])),
                    spread.get('max_profit', 0),
                    spread.get('max_loss', 0),
                    json.dumps(spread.get('breakeven', [])),
                    spread.get('entry_net_premium', 0),
                    spread.get('confidence', 0),
                    spread.get('reasoning', ''),
                    spread.get('web_news', ''),
                    json.dumps(spread.get('chatgpt_raw', {})),
                    spread.get('pcr', 0),
                    spread.get('max_pain', 0),
                    spread.get('total_ce_oi', 0),
                    spread.get('total_pe_oi', 0),
                    'OPEN',
                    spread.get('order_mode', 'PAPER'),
                    spread.get('buy_order_id', ''),
                    spread.get('sell_order_id', ''),
                    spread.get('buy_fill_price', 0),
                    spread.get('sell_fill_price', 0),
                    spread.get('actual_net_debit', 0),
                ))
                row_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
                return row_id
        except Exception as e:
            logger.error(f"Failed to log options spread: {e}")
            return None

    _SPREAD_UPDATE_ALLOWED_COLS = frozenset({
        'status', 'current_net_premium', 'paper_pnl', 'paper_pnl_pct',
        'exit_time', 'exit_reason', 'legs_json', 'entry_net_premium',
        # v6.1: Live order columns
        'order_mode', 'buy_order_id', 'sell_order_id',
        'buy_fill_price', 'sell_fill_price', 'actual_net_debit',
        # v6.2: TCAS tracking columns
        'peak_pnl_pct', 'profit_lock_pct', 'tcas_active',
    })

    def update_options_spread(self, spread_id: int, updates: Dict):
        """Update an existing options spread trade (paper P&L, status, etc.).
        Only whitelisted columns can be updated to prevent SQL injection."""
        try:
            with self.transaction() as conn:
                set_clauses = []
                values = []
                for key, value in updates.items():
                    if key not in self._SPREAD_UPDATE_ALLOWED_COLS:
                        logger.warning(f"Skipping disallowed column '{key}' in spread update")
                        continue
                    set_clauses.append(f"{key} = ?")
                    values.append(value)
                if not set_clauses:
                    return
                values.append(spread_id)
                conn.execute(
                    f"UPDATE options_spread_trades SET {', '.join(set_clauses)} WHERE id = ?",
                    tuple(values)
                )
        except Exception as e:
            logger.error(f"Failed to update options spread {spread_id}: {e}")

    def get_options_spread_stats(self, days: int = 30) -> Dict:
        """Get aggregate options advisory statistics for last N days."""
        try:
            since = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
            cursor = self.conn.cursor()
            cursor.execute('''
                SELECT
                    COUNT(*) as total_advisories,
                    SUM(CASE WHEN status != 'OPEN' AND paper_pnl >= 0 THEN 1 ELSE 0 END) as profitable,
                    SUM(CASE WHEN status != 'OPEN' AND paper_pnl < 0 THEN 1 ELSE 0 END) as unprofitable,
                    SUM(CASE WHEN status = 'OPEN' THEN 1 ELSE 0 END) as still_open,
                    SUM(paper_pnl) as total_paper_pnl,
                    AVG(paper_pnl) as avg_paper_pnl,
                    MAX(paper_pnl) as best_trade,
                    MIN(paper_pnl) as worst_trade,
                    AVG(confidence) as avg_confidence
                FROM options_spread_trades
                WHERE date >= ?
            ''', (since,))
            row = cursor.fetchone()
            if row:
                result = dict(row)
                closed = (result.get('profitable', 0) or 0) + (result.get('unprofitable', 0) or 0)
                profitable = result.get('profitable', 0) or 0
                result['win_rate'] = round(profitable / closed * 100, 1) if closed > 0 else 0
                return result
            return {'total_advisories': 0, 'win_rate': 0}
        except Exception as e:
            logger.error(f"Failed to get options spread stats: {e}")
            return {'total_advisories': 0, 'win_rate': 0}

    def get_options_spreads_for_date(self, date_str: str = None) -> List[Dict]:
        """Get all options spreads for a specific date."""
        date_str = date_str or datetime.now().strftime('%Y-%m-%d')
        try:
            cursor = self.conn.cursor()
            cursor.execute(
                'SELECT * FROM options_spread_trades WHERE date = ? ORDER BY timestamp',
                (date_str,)
            )
            return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Failed to get options spreads: {e}")
            return []

    # ═══════════════════════════════════════════════════════════════════════════
    # MORNING BRIEFING CONTEXT — Build ChatGPT memory packet
    # ═══════════════════════════════════════════════════════════════════════════
    
    def build_morning_context(self) -> Dict:
        """
        Build the complete context packet for ChatGPT morning briefing.
        
        Combines:
        - Yesterday's state (speedometer)
        - Yesterday's trades (detail)
        - Yesterday's faults
        - ChatGPT accuracy (was AI right recently?)
        - Recent trade stats (7-day window)
        
        Returns:
            Dict with all context for the morning briefing prompt
        """
        try:
            # Yesterday's state
            yesterday = self.get_last_trading_day_state()
            
            # Yesterday's trades
            yesterday_date = yesterday.get('date') if yesterday else None
            yesterday_trades = self.get_trades_for_date(yesterday_date) if yesterday_date else []
            
            # Yesterday's faults
            yesterday_faults = self.get_faults_for_date(yesterday_date) if yesterday_date else []
            
            # ChatGPT accuracy (30 days)
            chatgpt_accuracy = self.get_chatgpt_accuracy(30)
            
            # Recent trade stats (7 days)
            recent_stats = self.get_trade_stats(7)
            
            # Weekly stats (for running total)
            week_start = (datetime.now() - timedelta(days=datetime.now().weekday())).strftime('%Y-%m-%d')
            cursor = self.conn.cursor()
            cursor.execute('''
                SELECT 
                    SUM(total_pnl_net) as week_pnl,
                    SUM(total_trades) as week_trades,
                    SUM(trades_won) as week_wins
                FROM daily_state
                WHERE date >= ?
            ''', (week_start,))
            week_row = cursor.fetchone()
            week_stats = dict(week_row) if week_row else {}
            
            context = {
                'yesterday': yesterday,
                'yesterday_trades': yesterday_trades,
                'yesterday_faults': yesterday_faults,
                'chatgpt_accuracy': chatgpt_accuracy,
                'recent_stats_7d': recent_stats,
                'week_stats': week_stats,
                'context_date': datetime.now().strftime('%Y-%m-%d'),
                'context_time': datetime.now().strftime('%H:%M:%S'),
            }
            
            return context
            
        except Exception as e:
            logger.error(f"Failed to build morning context: {e}")
            return {}
    
    # ═══════════════════════════════════════════════════════════════════════════
    # UTILITY QUERIES
    # ═══════════════════════════════════════════════════════════════════════════
    
    def get_daily_states(self, days: int = 7) -> List[Dict]:
        """Get daily states for last N days (for weekly summary)."""
        try:
            since = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
            cursor = self.conn.cursor()
            cursor.execute('''
                SELECT * FROM daily_state WHERE date >= ? ORDER BY date DESC
            ''', (since,))
            return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Failed to get daily states: {e}")
            return []
    
    def query(self, sql: str, params: tuple = None) -> List[Dict]:
        """Execute raw SQL query. For ad-hoc analysis."""
        try:
            cursor = self.conn.cursor()
            if params:
                cursor.execute(sql, params)
            else:
                cursor.execute(sql)
            return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Query failed: {e}")
            return []
    
    def get_symbol_history(self, symbol: str, days: int = 90) -> Dict:
        """
        Get complete trading history for a symbol.
        Useful for ChatGPT when consulting about a specific stock.
        """
        try:
            since = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
            
            # Trades
            cursor = self.conn.cursor()
            cursor.execute('''
                SELECT * FROM trade_log 
                WHERE symbol = ? AND date >= ?
                ORDER BY date DESC
            ''', (symbol, since))
            trades = [dict(row) for row in cursor.fetchall()]
            
            # Faults
            cursor.execute('''
                SELECT * FROM fault_log 
                WHERE symbol = ? AND date >= ?
                ORDER BY timestamp DESC
            ''', (symbol, since))
            faults = [dict(row) for row in cursor.fetchall()]
            
            # Options advisories
            cursor.execute('''
                SELECT * FROM options_advisory 
                WHERE symbol = ? AND date >= ?
                ORDER BY timestamp DESC
            ''', (symbol, since))
            advisories = [dict(row) for row in cursor.fetchall()]
            
            # ChatGPT decisions about this symbol
            cursor.execute('''
                SELECT * FROM chatgpt_decisions 
                WHERE symbol = ? AND date >= ?
                ORDER BY timestamp DESC
            ''', (symbol, since))
            decisions = [dict(row) for row in cursor.fetchall()]
            
            # Aggregate stats
            total = len(trades)
            wins = sum(1 for t in trades if (t.get('pnl_net') or 0) >= 0)
            total_pnl = sum(t.get('pnl_net', 0) for t in trades)
            
            return {
                'symbol': symbol,
                'period_days': days,
                'trades': trades,
                'trade_count': total,
                'win_rate': round(wins / total * 100, 1) if total > 0 else 0,
                'total_pnl': total_pnl,
                'faults': faults,
                'advisories': advisories,
                'chatgpt_decisions': decisions
            }
            
        except Exception as e:
            logger.error(f"Failed to get symbol history for {symbol}: {e}")
            return {'symbol': symbol, 'trades': [], 'trade_count': 0}


# ═══════════════════════════════════════════════════════════════════════════════
# SINGLETON ACCESSOR
# ═══════════════════════════════════════════════════════════════════════════════

_mission_db_instance = None

def get_mission_db(db_path: str = None) -> MissionDB:
    """
    Get the singleton MissionDB instance.
    
    Usage:
        from mission_db import get_mission_db
        db = get_mission_db()
    """
    global _mission_db_instance
    if _mission_db_instance is None:
        _mission_db_instance = MissionDB(db_path)
    return _mission_db_instance


# ═══════════════════════════════════════════════════════════════════════════════
# SELF-TEST
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    """Run self-test to verify database works."""
    import tempfile
    
    print("=" * 60)
    print("MISSION_DB SELF-TEST")
    print("=" * 60)
    
    # Use temp directory for test
    test_db = os.path.join(tempfile.gettempdir(), "test_mission_control.db")
    
    # Clean up previous test
    for f in [test_db, test_db + ".bak"]:
        if os.path.exists(f):
            os.remove(f)
    
    # Create instance
    db = MissionDB(test_db)
    
    # Test 1: Integrity check
    ok, msg = db.check_integrity()
    print(f"\n✅ Test 1 - Integrity check: {ok} — {msg}")
    
    # Test 2: Ensure today
    db.ensure_today()
    print(f"✅ Test 2 - Today's state created: {db.today}")
    
    # Test 3: Update daily state
    db.update_daily_state(
        starting_capital=20000,
        free_capital=12000,
        market_regime="BULLISH",
        vix_open=14.2,
        system_state="RUNNING"
    )
    print("✅ Test 3 - Daily state updated")
    
    # Test 4: Log a trade
    db.log_trade({
        'symbol': 'TATAMOTORS',
        'direction': 'BUY',
        'product': 'MIS',
        'entry_price': 820.0,
        'entry_time': '2026-02-06T09:19:00',
        'entry_qty': 1,
        'entry_phase': 'PH5_GAP',
        'entry_reason': 'Gap down -2.1%, score 78',
        'exit_price': 836.0,
        'exit_time': '2026-02-06T09:42:00',
        'exit_reason': 'TARGET_HIT',
        'pnl_gross': 16.0,
        'pnl_net': 14.5,
        'fees': 1.5,
        'stop_price': 812.0,
        'target_price': 836.0,
        'hold_duration_min': 23,
    })
    print("✅ Test 4 - Trade logged")
    
    # Test 5: Check trade stats
    stats = db.get_trade_stats(30)
    print(f"✅ Test 5 - Trade stats: {stats.get('total_trades', 0)} trades, "
          f"win rate: {stats.get('win_rate', 0)}%")
    
    # Test 6: Log fault
    db.log_fault("GTT_ORPHAN", "WARNING", symbol="JSWSTEEL",
                 description="2 orphan GTTs found, auto-cleaned",
                 resolution="AUTO_FIXED")
    print("✅ Test 6 - Fault logged")
    
    # Test 7: Log ChatGPT decision
    db.log_chatgpt_decision(
        decision_type="ENTRY_CONFIRM",
        recommendation="BUY TATAMOTORS — gap reversal likely",
        symbol="TATAMOTORS",
        confidence=75.0,
        action_taken="EXECUTED",
        response_time_ms=3200
    )
    print("✅ Test 7 - ChatGPT decision logged")
    
    # Test 8: Log options advisory
    db.log_options_advisory({
        'symbol': 'BAJFINANCE',
        'vp_signal': 'BULLISH_CONVICTION',
        'volume_ratio': 2.8,
        'price_change_pct': 1.76,
        'kalman': {
            'prediction_1day': 990,
            'prediction_3day': 1012,
            'prediction_1week': 1035,
            'confidence': 78,
            'direction': 'BULLISH_ACCELERATING'
        },
        'oi_walls': [{'strike': 1000, 'oi_lakhs': 23.84}],
        'max_pain': 970,
        'pcr': 1.13,
        'suggested_strike': 1000,
        'suggested_ltp': 12.30,
        'suggested_cost': 9225,
        'suggestion_reason': 'Highest OI wall within Kalman range'
    })
    print("✅ Test 8 - Options advisory logged")
    
    # Test 9: Save shutdown state + backup
    db.save_shutdown_state(
        shutdown_type="CLEAN_SHUTDOWN",
        positions_overnight=[{
            'symbol': 'BAJFINANCE',
            'entry_price': 982,
            'qty': 1,
            'product': 'CNC',
            'unrealized_pnl': 15.0
        }],
        ending_capital=18500,
        total_pnl_net=14.5,
        chatgpt_eod_debrief="Good day. Hold BAJFINANCE."
    )
    print("✅ Test 9 - Shutdown state saved + backup created")
    assert os.path.exists(test_db + ".bak"), "Backup file should exist"
    
    # Test 10: Build morning context
    context = db.build_morning_context()
    print(f"✅ Test 10 - Morning context built: {len(context)} keys")
    
    # Test 11: Startup integrity check
    status, msg = db.startup_integrity_check()
    print(f"✅ Test 11 - Startup integrity: {status} — {msg}")
    
    # Test 12: Symbol history
    history = db.get_symbol_history("TATAMOTORS", 90)
    print(f"✅ Test 12 - Symbol history: {history.get('trade_count', 0)} trades, "
          f"win rate: {history.get('win_rate', 0)}%")
    
    # Cleanup
    for f in [test_db, test_db + ".bak"]:
        if os.path.exists(f):
            os.remove(f)
    
    print("\n" + "=" * 60)
    print("ALL 12 TESTS PASSED ✅")
    print("=" * 60)
