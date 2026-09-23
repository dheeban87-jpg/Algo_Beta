"""
DataBridge — Read-Only SQLite Poller for GUI
=============================================
Background thread polls algo_beta.db + mission_control.db every 5 seconds.
Delivers LiveData snapshots to registered GUI widgets via widget.after().
Thread-safe: never modifies databases.
Graceful: missing/locked DBs → empty LiveData, GUI falls back to mock.
"""

import os
import json
import math
import sqlite3
import logging
import threading
from datetime import datetime, date
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Callable

logger = logging.getLogger("DataBridge")


# ═══════════════════════════════════════════════════════════════════════════════
# DATA CLASSES
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class PositionData:
    """Single active position from DB."""
    symbol: str = ""
    entry_time: str = ""
    entry_price: float = 0.0
    quantity: int = 0
    direction: str = "BUY"
    target_price: float = 0.0
    stop_price: float = 0.0
    current_price: float = 0.0
    unrealized_pnl: float = 0.0
    status: str = "ACTIVE"
    metadata: dict = field(default_factory=dict)


@dataclass
class TradeData:
    """Single completed trade from DB."""
    trade_id: str = ""
    symbol: str = ""
    date: str = ""
    entry_price: float = 0.0
    exit_price: float = 0.0
    quantity: int = 0
    direction: str = "BUY"
    pnl: float = 0.0
    pnl_pct: float = 0.0
    win: bool = False
    exit_reason: str = ""
    duration_minutes: float = 0.0


@dataclass
class FaultData:
    """System fault entry."""
    timestamp: str = ""
    fault_code: str = ""
    severity: str = "INFO"
    symbol: str = ""
    description: str = ""
    resolution: str = ""


@dataclass
class DecisionData:
    """AI/ChatGPT decision entry."""
    timestamp: str = ""
    symbol: str = ""
    decision: str = ""
    reason: str = ""
    confidence: float = 0.0
    current_price: float = 0.0


@dataclass
class LiveData:
    """Complete snapshot of live system state.
    All fields default to empty — GUI renders safely with no data."""

    # From algo_beta.db
    positions: List[PositionData] = field(default_factory=list)
    trades_today: List[TradeData] = field(default_factory=list)
    decisions_recent: List[DecisionData] = field(default_factory=list)

    # P&L / Capital
    total_pnl_today: float = 0.0
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    win_count: int = 0
    loss_count: int = 0
    trades_count: int = 0

    # Capital (from mission_control.db daily_state)
    starting_capital: float = 0.0
    free_capital: float = 0.0
    deployed_capital: float = 0.0

    # Broker state (from broker_snapshots)
    broker_connected: bool = False
    available_cash: float = 0.0
    used_margin: float = 0.0
    broker_positions_count: int = 0

    # System health (from mission_control.db)
    faults: List[FaultData] = field(default_factory=list)
    chatgpt_decisions: List[DecisionData] = field(default_factory=list)
    market_regime: str = ""
    system_state: str = ""
    system_version: str = ""

    # Kalman states (from kalman_calibration)
    kalman_states: Dict[str, Any] = field(default_factory=dict)

    # Metadata
    last_updated: str = ""
    db_available: bool = False


# ═══════════════════════════════════════════════════════════════════════════════
# BROKER CHARGE CALCULATOR (Indian Equity CNC / Delivery — Zerodha-style)
# ═══════════════════════════════════════════════════════════════════════════════

def _calc_broker_charges(entry_price: float, exit_price: float,
                         quantity: int, direction: str = "LONG") -> dict:
    """Calculate Indian equity delivery (CNC) broker charges.

    For LONG: buy at entry_price, sell at exit_price.
    For SHORT: sell at entry_price, buy at exit_price.
    Returns dict with individual charge components + total (all rounded ₹).
    """
    buy_value = entry_price * quantity
    sell_value = exit_price * quantity

    if direction.upper() in ("SHORT", "SELL"):
        buy_value, sell_value = sell_value, buy_value

    turnover = buy_value + sell_value

    # Brokerage: ₹20/order OR 0.03% whichever is lower, per side
    brokerage_buy = min(20.0, buy_value * 0.0003)
    brokerage_sell = min(20.0, sell_value * 0.0003)
    brokerage = brokerage_buy + brokerage_sell

    # STT: 0.025% on sell side (CNC delivery)
    stt = sell_value * 0.00025

    # Exchange transaction charges: 0.00345% of turnover (NSE)
    exchange = turnover * 0.0000345

    # SEBI fees: 0.0001% of turnover
    sebi = turnover * 0.000001

    # GST: 18% on (brokerage + exchange + SEBI)
    gst = (brokerage + exchange + sebi) * 0.18

    # Stamp duty: 0.015% on buy side
    stamp = buy_value * 0.00015

    total = brokerage + stt + exchange + sebi + gst + stamp

    return {
        "brokerage": round(brokerage, 2),
        "stt": round(stt, 2),
        "exchange": round(exchange, 2),
        "sebi": round(sebi, 2),
        "gst": round(gst, 2),
        "stamp": round(stamp, 2),
        "total": round(total, 2),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# DATA BRIDGE
# ═══════════════════════════════════════════════════════════════════════════════

class DataBridge:
    """Read-only SQLite poller — feeds live data to GUI views.

    Usage:
        bridge = DataBridge(algo_db_path, mc_db_path)
        bridge.start()
        bridge.register_callback(my_widget, my_callback)
        # ... later ...
        bridge.stop()
    """

    POLL_INTERVAL = 5  # seconds

    def __init__(self, algo_db_path: str, mc_db_path: str):
        self._algo_db = algo_db_path
        self._mc_db = mc_db_path
        self._latest: LiveData = LiveData()
        self._callbacks: List[tuple] = []  # [(widget, callback), ...]
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

        # Log DB availability
        algo_ok = os.path.isfile(self._algo_db)
        mc_ok = os.path.isfile(self._mc_db)
        logger.info(f"DataBridge init: algo_beta.db={'OK' if algo_ok else 'MISSING'}, "
                     f"mission_control.db={'OK' if mc_ok else 'MISSING'}")

    # ──────────────────────────────────────────────────────────────────────
    #  PUBLIC API
    # ──────────────────────────────────────────────────────────────────────

    def start(self):
        """Start background polling thread."""
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._poll_loop, daemon=True,
                                         name="DataBridge-Poller")
        self._thread.start()
        logger.info("DataBridge started (polling every %ds)", self.POLL_INTERVAL)

    def stop(self):
        """Stop background polling thread."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=3)
        logger.info("DataBridge stopped")

    def register_callback(self, widget, callback: Callable[[LiveData], None]):
        """Register a GUI widget to receive LiveData updates.

        callback is invoked on the main thread via widget.after().
        If widget is destroyed, the callback is silently skipped.
        """
        with self._lock:
            self._callbacks.append((widget, callback))

    def get_latest(self) -> LiveData:
        """Get the most recent LiveData snapshot (thread-safe)."""
        with self._lock:
            return self._latest

    # ──────────────────────────────────────────────────────────────────────
    #  POLLING LOOP (runs in background thread)
    # ──────────────────────────────────────────────────────────────────────

    def _poll_loop(self):
        """Main polling loop — runs until stop() is called."""
        while not self._stop_event.is_set():
            try:
                data = self._read_all()
                with self._lock:
                    self._latest = data
                self._notify_callbacks(data)
            except Exception as e:
                logger.debug(f"DataBridge poll error: {e}")
            self._stop_event.wait(self.POLL_INTERVAL)

    def _notify_callbacks(self, data: LiveData):
        """Dispatch LiveData to registered widgets on main thread."""
        with self._lock:
            callbacks = list(self._callbacks)

        alive = []
        for widget, callback in callbacks:
            try:
                # widget.after() schedules on Tk main thread (thread-safe)
                widget.after(0, callback, data)
                alive.append((widget, callback))
            except Exception:
                # Widget destroyed — skip silently
                pass

        # Prune dead callbacks
        if len(alive) != len(callbacks):
            with self._lock:
                self._callbacks = alive

    # ──────────────────────────────────────────────────────────────────────
    #  DATABASE READERS
    # ──────────────────────────────────────────────────────────────────────

    def _read_all(self) -> LiveData:
        """Read both databases, return combined LiveData snapshot."""
        data = LiveData(last_updated=datetime.now().isoformat())

        # Read algo_beta.db
        if os.path.isfile(self._algo_db):
            try:
                self._read_algo_db(data)
                data.db_available = True
            except Exception as e:
                logger.debug(f"algo_beta.db read error: {e}")

        # Read mission_control.db
        if os.path.isfile(self._mc_db):
            try:
                self._read_mc_db(data)
                data.db_available = True
            except Exception as e:
                logger.debug(f"mission_control.db read error: {e}")

        return data

    def _connect(self, db_path: str) -> sqlite3.Connection:
        """Open a read-only SQLite connection with short timeout."""
        conn = sqlite3.connect(
            f"file:{db_path}?mode=ro",
            uri=True,
            timeout=2,
        )
        conn.row_factory = sqlite3.Row
        # Note: do NOT set journal_mode=WAL on read-only connections —
        # it tries to create/write the WAL file and fails with mode=ro.
        # Reading a WAL-mode DB works automatically without this PRAGMA.
        return conn

    # ── Phase Controls (GUI → Orchestrator) ────────────────────────────

    def set_phase_state(self, phase_key: str, state: str):
        """Write phase state to mission_control.db.  state ∈ {'OFF','PAPER','LIVE'}."""
        if not self._mc_db:
            return
        try:
            conn = sqlite3.connect(self._mc_db, timeout=5)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                "CREATE TABLE IF NOT EXISTS phase_controls "
                "(phase_key TEXT PRIMARY KEY, state TEXT NOT NULL DEFAULT 'OFF', "
                "updated_at TEXT DEFAULT CURRENT_TIMESTAMP)"
            )
            conn.execute(
                "INSERT OR REPLACE INTO phase_controls (phase_key, state, updated_at) "
                "VALUES (?, ?, ?)",
                (phase_key, state, datetime.now().isoformat())
            )
            conn.commit()
            conn.close()
            logger.info(f"Phase control: {phase_key} → {state}")
        except Exception as e:
            logger.error(f"set_phase_state failed: {e}")

    def get_phase_states(self) -> Dict[str, str]:
        """Read all phase states from mission_control.db."""
        result: Dict[str, str] = {}
        if not self._mc_db or not os.path.isfile(self._mc_db):
            return result
        try:
            conn = self._connect(self._mc_db)
            rows = conn.execute(
                "SELECT phase_key, state FROM phase_controls"
            ).fetchall()
            conn.close()
            result = {r['phase_key']: r['state'] for r in rows}
        except Exception:
            pass
        return result

    # ── algo_beta.db ─────────────────────────────────────────────────────

    def _read_algo_db(self, data: LiveData):
        """Read positions, trades, decisions, broker state from algo_beta.db."""
        conn = self._connect(self._algo_db)
        try:
            self._read_positions(conn, data)
            self._read_trades_today(conn, data)
            self._read_decisions(conn, data)
            self._read_broker_state(conn, data)
            self._read_daily_summary(conn, data)
            self._read_kalman(conn, data)
        finally:
            conn.close()

    def _read_positions(self, conn: sqlite3.Connection, data: LiveData):
        """Read active positions."""
        try:
            rows = conn.execute(
                "SELECT * FROM positions WHERE status IN ('ACTIVE', 'MONITORING', 'OPEN') "
                "ORDER BY entry_time DESC"
            ).fetchall()
            for r in rows:
                meta = {}
                try:
                    meta = json.loads(r["metadata"] or "{}")
                except (json.JSONDecodeError, TypeError):
                    pass
                data.positions.append(PositionData(
                    symbol=r["symbol"] or "",
                    entry_time=r["entry_time"] or "",
                    entry_price=r["entry_price"] or 0.0,
                    quantity=r["quantity"] or 0,
                    direction=r["direction"] or "BUY",
                    target_price=r["target_price"] or 0.0,
                    stop_price=r["stop_price"] or 0.0,
                    current_price=r["current_price"] or 0.0,
                    unrealized_pnl=r["unrealized_pnl"] or 0.0,
                    status=r["status"] or "ACTIVE",
                    metadata=meta,
                ))
            # Compute unrealized total
            data.unrealized_pnl = sum(p.unrealized_pnl for p in data.positions)
        except Exception as e:
            logger.debug(f"  positions read: {e}")

    def _read_trades_today(self, conn: sqlite3.Connection, data: LiveData):
        """Read today's completed trades."""
        today = date.today().isoformat()
        try:
            rows = conn.execute(
                "SELECT * FROM trades WHERE date = ? ORDER BY exit_time DESC",
                (today,)
            ).fetchall()
            for r in rows:
                data.trades_today.append(TradeData(
                    trade_id=r["trade_id"] or "",
                    symbol=r["symbol"] or "",
                    date=r["date"] or "",
                    entry_price=r["entry_price"] or 0.0,
                    exit_price=r["exit_price"] or 0.0,
                    quantity=r["quantity"] or 0,
                    direction=r["direction"] or "BUY",
                    pnl=r["pnl"] or 0.0,
                    pnl_pct=r["pnl_pct"] or 0.0,
                    win=bool(r["win"]),
                    exit_reason=r["exit_reason"] or "",
                    duration_minutes=r["duration_minutes"] or 0.0,
                ))
            data.trades_count = len(data.trades_today)
            data.realized_pnl = sum(t.pnl for t in data.trades_today)
            data.win_count = sum(1 for t in data.trades_today if t.win)
            data.loss_count = sum(1 for t in data.trades_today if not t.win and t.pnl != 0)
            data.total_pnl_today = data.realized_pnl + data.unrealized_pnl
        except Exception as e:
            logger.debug(f"  trades read: {e}")

    def _read_decisions(self, conn: sqlite3.Connection, data: LiveData):
        """Read recent decisions (last 20)."""
        try:
            rows = conn.execute(
                "SELECT * FROM decisions ORDER BY timestamp DESC LIMIT 20"
            ).fetchall()
            for r in rows:
                data.decisions_recent.append(DecisionData(
                    timestamp=r["timestamp"] or "",
                    symbol=r["symbol"] or "",
                    decision=r["decision"] or "",
                    reason=r["reason"] or "",
                    confidence=r["confidence"] or 0.0,
                    current_price=r["current_price"] or 0.0,
                ))
        except Exception as e:
            logger.debug(f"  decisions read: {e}")

    def _read_broker_state(self, conn: sqlite3.Connection, data: LiveData):
        """Read latest broker snapshot for connection status."""
        try:
            row = conn.execute(
                "SELECT * FROM broker_snapshots ORDER BY timestamp DESC LIMIT 1"
            ).fetchone()
            if row:
                data.available_cash = row["available_cash"] or 0.0
                data.used_margin = row["used_margin"] or 0.0
                data.broker_positions_count = row["total_positions"] or 0
                # If snapshot < 60s old, consider broker connected
                try:
                    ts = datetime.fromisoformat(row["timestamp"])
                    data.broker_connected = (datetime.now() - ts).total_seconds() < 60
                except (ValueError, TypeError):
                    data.broker_connected = False
        except Exception as e:
            logger.debug(f"  broker state read: {e}")

    def _read_daily_summary(self, conn: sqlite3.Connection, data: LiveData):
        """Read today's daily summary for P&L overview."""
        today = date.today().isoformat()
        try:
            row = conn.execute(
                "SELECT * FROM daily_summary WHERE date = ? LIMIT 1",
                (today,)
            ).fetchone()
            if row:
                data.total_pnl_today = row["total_pnl"] or data.total_pnl_today
                data.win_count = max(data.win_count, row["win_count"] or 0)
                data.loss_count = max(data.loss_count, row["loss_count"] or 0)
        except Exception as e:
            logger.debug(f"  daily_summary read: {e}")

    def _read_kalman(self, conn: sqlite3.Connection, data: LiveData):
        """Read Kalman calibration states."""
        try:
            rows = conn.execute("SELECT * FROM kalman_calibration").fetchall()
            for r in rows:
                data.kalman_states[r["symbol"]] = {
                    "q_matrix": r["q_matrix"],
                    "r_matrix": r["r_matrix"],
                    "observation_count": r["observation_count"],
                    "last_updated": r["last_updated"],
                }
        except Exception as e:
            logger.debug(f"  kalman read: {e}")

    # ── mission_control.db ───────────────────────────────────────────────

    def _read_mc_db(self, data: LiveData):
        """Read capital, faults, ChatGPT decisions from mission_control.db."""
        conn = self._connect(self._mc_db)
        try:
            self._read_daily_state(conn, data)
            self._read_faults(conn, data)
            self._read_chatgpt(conn, data)
        finally:
            conn.close()

    def _read_daily_state(self, conn: sqlite3.Connection, data: LiveData):
        """Read today's capital state."""
        today = date.today().isoformat()
        try:
            row = conn.execute(
                "SELECT * FROM daily_state WHERE date = ? LIMIT 1",
                (today,)
            ).fetchone()
            if row:
                data.starting_capital = row["starting_capital"] or 0.0
                data.free_capital = row["free_capital"] or 0.0
                data.deployed_capital = (
                    (row["starting_capital"] or 0.0) - (row["free_capital"] or 0.0)
                )
                data.market_regime = row["market_regime"] or ""
                data.system_state = row["system_state"] or ""
                data.system_version = row["system_version"] or ""
        except Exception as e:
            logger.debug(f"  daily_state read: {e}")

    def _read_faults(self, conn: sqlite3.Connection, data: LiveData):
        """Read recent unresolved faults."""
        today = date.today().isoformat()
        try:
            rows = conn.execute(
                "SELECT * FROM fault_log WHERE date = ? "
                "ORDER BY timestamp DESC LIMIT 20",
                (today,)
            ).fetchall()
            for r in rows:
                data.faults.append(FaultData(
                    timestamp=r["timestamp"] or "",
                    fault_code=r["fault_code"] or "",
                    severity=r["severity"] or "INFO",
                    symbol=r["symbol"] or "",
                    description=r["description"] or "",
                    resolution=r["resolution"] or "",
                ))
        except Exception as e:
            logger.debug(f"  faults read: {e}")

    # ------------------------------------------------------------------
    #  PHASE-SPECIFIC DATA ACCESSORS
    # ------------------------------------------------------------------

    def get_ph5_gap_data(self) -> dict:
        """Get PH5 gap strategy live data from DB."""
        data = self.get_latest()
        if not data or not data.db_available:
            return {}
        ph5_trades = [t for t in data.trades_today
                      if 'PH5' in (t.exit_reason or '') or 'gap' in (t.exit_reason or '').lower()
                      or 'GAP' in (t.exit_reason or '')]
        ph5_positions = [p for p in data.positions
                         if 'PH5' in (p.metadata.get('source', '') if p.metadata else '')]
        return {
            "window_status": "CLOSED" if not ph5_positions else "ACTIVE",
            "candidates_today": len(ph5_trades) + len(ph5_positions),
            "trades_today": len(ph5_trades),
            "pnl_today": sum(t.pnl for t in ph5_trades),
            "active_positions": ph5_positions,
            "recent_trades": ph5_trades,
        }

    def get_ph5_data_v2(self) -> dict:
        """Comprehensive PH5 gap strategy data from mission_control.db + config.

        Aggregates: trade_log (today + historical), daily_state (P&L series),
        config params, and live window status.  Returns empty dict on failure
        so the GUI falls back to PH5_MOCK.
        """
        result = {
            "source": "ph5_v2",
            "status": "CLOSED",
            "window_start": "09:15", "window_end": "09:50",
            "scan_window": "09:18 -- 09:20",
            "entry_window": "09:20 -- 09:25",
            "universe_size": 147,
            "candidates_today": 0,
            "trades_today_count": 0,
            "pnl_today": 0.0,
            "next_run": "Tomorrow 09:15 AM",
            "today_trades": [],
            "historical_trades": [],
            "daily_pnl_series": [],
            "config": {},
            "performance": {
                "total_trades": 0, "wins": 0, "losses": 0,
                "win_rate": 0, "avg_pnl": 0, "avg_duration_min": 0,
                "profit_factor": 0, "avg_win": 0, "avg_loss": 0,
                "total_pnl": 0,
            },
            "mission_log": [],
        }

        # ── Supplement from live data bridge ──────────────────────────
        try:
            live = self.get_ph5_gap_data()
            if live:
                if live.get("window_status") == "ACTIVE":
                    result["status"] = "ACTIVE"
                result["candidates_today"] = live.get("candidates_today", 0)
                result["pnl_today"] = live.get("pnl_today", 0.0)
        except Exception:
            pass

        # ── Config params ─────────────────────────────────────────────
        cfg_defaults = {
            "gap_p1": 1.5, "gap_p2": 1.0, "gap_p3": 0.75,
            "min_volume_ratio": 1.0, "max_adx": 25,
            "min_price": 800, "max_price": 3000,
            "max_trades_day": 1, "pos_size_pct": 5.0,
            "min_pos_value": 5000, "max_pos_value": 10000,
        }
        try:
            import importlib.util
            project_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            cfg_path = os.path.join(project_dir, "config.py")
            if os.path.isfile(cfg_path):
                spec = importlib.util.spec_from_file_location("_cfg", cfg_path)
                cfg = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(cfg)
                cfg_defaults = {
                    "gap_p1": getattr(cfg, "GAP_THRESHOLD_PRIORITY_1", 1.5),
                    "gap_p2": getattr(cfg, "GAP_THRESHOLD_PRIORITY_2", 1.0),
                    "gap_p3": getattr(cfg, "GAP_THRESHOLD_PRIORITY_3", 0.75),
                    "min_volume_ratio": getattr(cfg, "GAP_MIN_VOLUME_RATIO", 1.0),
                    "max_adx": getattr(cfg, "GAP_MAX_ADX", 25),
                    "min_price": getattr(cfg, "PH5_MIN_PRICE", 800),
                    "max_price": getattr(cfg, "PH5_MAX_PRICE", 3000),
                    "max_trades_day": getattr(cfg, "GAP_MAX_TRADES_PER_DAY", 1),
                    "pos_size_pct": getattr(cfg, "GAP_POSITION_SIZE_PCT", 5.0),
                    "min_pos_value": getattr(cfg, "GAP_MIN_POSITION_VALUE", 5000),
                    "max_pos_value": getattr(cfg, "GAP_MAX_POSITION_VALUE", 10000),
                }
        except Exception:
            pass
        result["config"] = cfg_defaults

        # ── mission_control.db queries ────────────────────────────────
        if not self._mc_db or not os.path.isfile(self._mc_db):
            return result

        try:
            conn = self._connect(self._mc_db)
        except Exception:
            return result

        today = date.today().isoformat()
        ph5_filter = (
            "entry_phase LIKE '%PH5%' OR entry_phase LIKE '%ph5%' "
            "OR exit_reason LIKE '%gap%' OR exit_reason LIKE '%GAP%' "
            "OR exit_reason LIKE '%PH5%'"
        )

        try:
            # 1. Today's PH5 trades
            rows = conn.execute(
                f"SELECT symbol, direction, entry_price, entry_time, entry_qty, "
                f"exit_price, exit_time, pnl_net, hold_duration_min, exit_reason "
                f"FROM trade_log WHERE date = ? AND ({ph5_filter}) "
                f"ORDER BY entry_time",
                (today,)
            ).fetchall()
            for r in rows:
                result["today_trades"].append({
                    "symbol": r["symbol"] or "",
                    "direction": r["direction"] or "",
                    "entry_price": r["entry_price"] or 0,
                    "entry_time": r["entry_time"] or "",
                    "entry_qty": r["entry_qty"] or 0,
                    "exit_price": r["exit_price"] or 0,
                    "exit_time": r["exit_time"] or "",
                    "pnl_net": r["pnl_net"] or 0,
                    "hold_duration_min": r["hold_duration_min"] or 0,
                    "exit_reason": r["exit_reason"] or "",
                })
            result["trades_today_count"] = len(result["today_trades"])
            if result["today_trades"]:
                result["pnl_today"] = sum(
                    t["pnl_net"] for t in result["today_trades"]
                )
        except Exception as e:
            logger.debug(f"PH5 today trades: {e}")

        try:
            # 2. Historical PH5 trades (last 30)
            rows = conn.execute(
                f"SELECT date, symbol, direction, entry_price, exit_price, "
                f"pnl_net, hold_duration_min, max_favorable, max_adverse, "
                f"exit_reason FROM trade_log "
                f"WHERE ({ph5_filter}) ORDER BY date DESC LIMIT 30"
            ).fetchall()
            for r in rows:
                result["historical_trades"].append({
                    "date": r["date"] or "",
                    "symbol": r["symbol"] or "",
                    "direction": r["direction"] or "",
                    "entry_price": r["entry_price"] or 0,
                    "exit_price": r["exit_price"] or 0,
                    "pnl_net": r["pnl_net"] or 0,
                    "hold_duration_min": r["hold_duration_min"] or 0,
                    "max_favorable": r["max_favorable"] or 0,
                    "max_adverse": r["max_adverse"] or 0,
                    "exit_reason": r["exit_reason"] or "",
                })
        except Exception as e:
            logger.debug(f"PH5 historical trades: {e}")

        try:
            # 3. Historical aggregates
            row = conn.execute(
                f"SELECT COUNT(*) as total, "
                f"SUM(CASE WHEN pnl_net > 0 THEN 1 ELSE 0 END) as wins, "
                f"AVG(pnl_net) as avg_pnl, "
                f"AVG(hold_duration_min) as avg_dur, "
                f"SUM(CASE WHEN pnl_net > 0 THEN pnl_net ELSE 0 END) as gross_profit, "
                f"SUM(CASE WHEN pnl_net < 0 THEN ABS(pnl_net) ELSE 0 END) as gross_loss, "
                f"SUM(pnl_net) as total_pnl "
                f"FROM trade_log WHERE ({ph5_filter})"
            ).fetchone()
            if row and row["total"] and row["total"] > 0:
                total = row["total"]
                wins = row["wins"] or 0
                losses = total - wins
                wr = (wins / total * 100) if total > 0 else 0
                gross_profit = row["gross_profit"] or 0
                gross_loss = row["gross_loss"] or 0
                pf = (gross_profit / gross_loss) if gross_loss > 0 else 0
                avg_win = (gross_profit / wins) if wins > 0 else 0
                avg_loss = (gross_loss / losses) if losses > 0 else 0
                result["performance"] = {
                    "total_trades": total,
                    "wins": wins,
                    "losses": losses,
                    "win_rate": round(wr, 1),
                    "avg_pnl": round(row["avg_pnl"] or 0, 1),
                    "avg_duration_min": round(row["avg_dur"] or 0, 0),
                    "profit_factor": round(pf, 2),
                    "avg_win": round(avg_win, 1),
                    "avg_loss": round(avg_loss, 1),
                    "total_pnl": round(row["total_pnl"] or 0, 1),
                }
        except Exception as e:
            logger.debug(f"PH5 aggregates: {e}")

        try:
            # 4. Daily PH5 P&L series (last 30 days with activity)
            rows = conn.execute(
                "SELECT date, ph5_pnl FROM daily_state "
                "WHERE ph5_trades > 0 OR ph5_pnl != 0 "
                "ORDER BY date DESC LIMIT 30"
            ).fetchall()
            result["daily_pnl_series"] = [
                {"date": r["date"], "ph5_pnl": r["ph5_pnl"] or 0}
                for r in reversed(rows)  # chronological order
            ]
        except Exception as e:
            logger.debug(f"PH5 daily series: {e}")

        try:
            conn.close()
        except Exception:
            pass

        return result

    def get_ph5a_data(self) -> dict:
        """v5.7.0: Get PH5A PVAT scanner live data from radar state JSON."""
        # Try live radar state file first
        radar_path = os.path.join("data", "ph5a_radar_state.json")
        if os.path.isfile(radar_path) and self._is_recent_file(radar_path, 1):
            try:
                with open(radar_path, "r") as f:
                    radar = json.load(f)
                # Enrich with trade PnL from DB
                data = self.get_latest()
                if data and data.db_available:
                    ph5a_trades = [t for t in data.trades_today
                                   if 'PH5A' in (t.exit_reason or '') or 'PVAT' in (t.exit_reason or '')]
                    radar["triggers_today"] = len(ph5a_trades)
                    radar["pnl_today"] = sum(t.pnl for t in ph5a_trades)
                return radar
            except (json.JSONDecodeError, IOError, KeyError):
                pass

        # Fallback: basic data from DB
        data = self.get_latest()
        if not data or not data.db_available:
            return {}
        ph5a_trades = [t for t in data.trades_today
                       if 'PH5A' in (t.exit_reason or '') or 'PVAT' in (t.exit_reason or '')]
        return {
            "scan_mode": "NORMAL",
            "scan_count": 0,
            "triggers_today": len(ph5a_trades),
            "pnl_today": sum(t.pnl for t in ph5a_trades),
        }

    def get_ph6_data(self) -> dict:
        """Get PH6 options shadow data from DB."""
        data = self.get_latest()
        if not data or not data.db_available:
            return {}
        return {
            "open_shadows": 0,
            "shadow_pnl": 0,
        }

    def get_ph7_data(self) -> dict:
        """Get PH7 MCX data from DB."""
        data = self.get_latest()
        if not data or not data.db_available:
            return {}
        ph7_positions = [p for p in data.positions
                         if 'PH7' in (p.metadata.get('source', '') if p.metadata else '')
                         or 'MCX' in (p.metadata.get('source', '') if p.metadata else '')]
        return {
            "active_positions": len(ph7_positions),
            "symbols": [p.symbol for p in ph7_positions],
        }

    def get_ph8_data(self) -> dict:
        """Get PH8 momentum data from DB."""
        data = self.get_latest()
        if not data or not data.db_available:
            return {}
        ph8_positions = [p for p in data.positions
                         if 'PH8' in (p.metadata.get('source', '') if p.metadata else '')]
        return {
            "active_positions": len(ph8_positions),
            "symbols": [p.symbol for p in ph8_positions],
        }

    # ------------------------------------------------------------------
    #  PH1 / PH2 / PH3 DATA READERS  (v5.6.2)
    # ------------------------------------------------------------------

    def get_ph1_data(self) -> dict:
        """Read today's stock selection results from algo_beta.db."""
        result: dict = {}
        if not self._algo_db or not os.path.isfile(self._algo_db):
            return result
        today = date.today().isoformat()
        try:
            conn = self._connect(self._algo_db)
            rows = conn.execute(
                "SELECT * FROM stock_selections WHERE date = ? ORDER BY score DESC",
                (today,)
            ).fetchall()
            conn.close()

            stocks = []
            filter_counts: dict = {}
            scan_time = ""
            for r in rows:
                fs = r["filter_stage"] or ""
                if r["selected"]:
                    stocks.append({
                        "symbol": r["symbol"] or "",
                        "price": r["price"] or 0.0,
                        "rsi": round(r["rsi"] or 0, 1),
                        "score": round(r["score"] or 0, 1),
                        "filter_stage": fs,
                    })
                filter_counts[fs] = filter_counts.get(fs, 0) + 1
                if not scan_time and r["scan_time"]:
                    scan_time = r["scan_time"]

            total_scanned = len(rows)
            result = {
                "scan_time": scan_time or "--",
                "total_scanned": total_scanned,
                "selected_count": len(stocks),
                "next_scan": "Tomorrow 09:15 AM",
                "stocks": stocks[:20],  # cap display
                "filter_funnel": filter_counts,
            }
        except Exception as e:
            logger.debug(f"get_ph1_data: {e}")
        return result

    # ------------------------------------------------------------------
    #  PH1 v2: Read from ACTIVE.json + market_context.json (primary)
    # ------------------------------------------------------------------

    def get_ph1_data_v2(self) -> dict:
        """Read PH1 data from Phase 1 JSON output files.

        Primary:  data/phase1_outputs/ACTIVE.json  (final selected stocks)
                  data/phase1_outputs/market_context.json  (funnel numbers)
        Fallback: get_ph1_data() (DB query)
        """
        gui_dir = os.path.dirname(os.path.abspath(__file__))
        ph1_dir = os.path.join(os.path.dirname(gui_dir), "data", "phase1_outputs")
        active_path = os.path.join(ph1_dir, "ACTIVE.json")
        context_path = os.path.join(ph1_dir, "market_context.json")

        # --- Try ACTIVE.json ---
        active = None
        if os.path.isfile(active_path):
            try:
                with open(active_path, "r") as f:
                    active = json.load(f)
            except (json.JSONDecodeError, IOError):
                active = None

        if not active or not active.get("stocks"):
            return self.get_ph1_data()  # fallback to DB

        # Check freshness: scan_date is YYYYMMDD
        today_compact = date.today().strftime("%Y%m%d")
        scan_date = str(active.get("scan_date", ""))
        if scan_date != today_compact and not self._is_recent_file(active_path, 24):
            return self.get_ph1_data()

        # --- Try market_context.json for funnel numbers ---
        ctx = None
        if os.path.isfile(context_path):
            try:
                with open(context_path, "r") as f:
                    ctx = json.load(f)
            except (json.JSONDecodeError, IOError):
                ctx = None

        ss = (ctx or {}).get("scan_summary", {})
        total_scanned = ss.get("total_scanned", 0)
        filter_funnel = {}
        if ss.get("filter1_passed"):
            filter_funnel["Filter 1 (Price)"] = ss["filter1_passed"]
        if ss.get("filter2_passed"):
            filter_funnel["Filter 2 (Uptrend)"] = ss["filter2_passed"]

        # --- Build stock list with rich metadata ---
        stocks = []
        for stk in active["stocks"]:
            stocks.append({
                "symbol": stk.get("symbol", ""),
                "ltp": stk.get("ltp", 0),
                "open": stk.get("open", 0),
                "high": stk.get("high", 0),
                "low": stk.get("low", 0),
                "strategy": stk.get("strategy", ""),
                "strategy_score": stk.get("strategy_score", 0),
                "trend": stk.get("trend", {}),
                "sector_check": stk.get("sector_check", {}),
                "weekly_check": stk.get("weekly_check", {}),
                "strategy_details": stk.get("strategy_details", {}),
                "v_recovery": stk.get("v_recovery", {}),
                "selected_at": stk.get("selected_at", ""),
            })

        scan_time = active.get("scan_time", "--")
        if isinstance(scan_time, str) and len(scan_time) > 19:
            scan_time = scan_time[11:19]  # trim ISO timestamp

        return {
            "source": "active_json",
            "scan_time": scan_time,
            "total_scanned": total_scanned,
            "selected_count": len(stocks),
            "next_scan": "Tomorrow 09:15 AM",
            "stocks": stocks,
            "filter_funnel": filter_funnel,
            "phase1_complete": active.get("phase1_complete", False),
            "phase2_started": active.get("phase2_started", False),
        }

    @staticmethod
    def _is_recent_file(filepath: str, max_hours: int = 24) -> bool:
        """Check if file was modified within max_hours."""
        try:
            mtime = os.path.getmtime(filepath)
            age_hours = (datetime.now().timestamp() - mtime) / 3600
            return age_hours <= max_hours
        except OSError:
            return False

    def get_ph2_data(self) -> dict:
        """Read recent PH2 entry decisions from algo_beta.db."""
        result: dict = {}
        if not self._algo_db or not os.path.isfile(self._algo_db):
            return result
        today = date.today().isoformat()
        try:
            conn = self._connect(self._algo_db)
            rows = conn.execute(
                "SELECT * FROM decisions WHERE date(timestamp) = ? "
                "ORDER BY timestamp DESC LIMIT 30",
                (today,)
            ).fetchall()
            conn.close()

            recent = []
            entries = skips = blocks = 0
            for r in rows:
                dec = (r["decision"] or "").upper()
                if "ENTER" in dec or "BUY" in dec:
                    entries += 1
                elif "BLOCK" in dec:
                    blocks += 1
                else:
                    skips += 1

                ts = r["timestamp"] or ""
                short_time = ts[11:16] if len(ts) >= 16 else ts
                conf = r["confidence"] or 0.0

                # Derive grade from confidence
                if conf >= 80:
                    grade = "STRONG_BUY"
                elif conf >= 65:
                    grade = "BUY"
                elif conf >= 50:
                    grade = "MODERATE"
                else:
                    grade = "SKIP"

                if "BLOCK" in dec:
                    grade = "BLOCKED"

                recent.append({
                    "time": short_time,
                    "symbol": r["symbol"] or "",
                    "decision": dec if dec else "SKIP",
                    "confidence": round(conf, 1),
                    "grade": grade,
                })

            total = entries + skips + blocks
            result = {
                "decisions_today": total,
                "monitoring": len(recent),
                "entries": entries,
                "skips": skips,
                "blocks": blocks,
                "recent": recent,
            }
        except Exception as e:
            logger.debug(f"get_ph2_data: {e}")
        return result

    # ------------------------------------------------------------------
    #  PH2 v2: Aggregate ACTIVE.json + decisions + trades + orders
    # ------------------------------------------------------------------

    def get_ph2_data_v2(self) -> dict:
        """Read PH2 data from multiple sources for a rich monitoring view.

        Primary:  data/phase1_outputs/ACTIVE.json  (active monitors)
                  algo_beta.db decisions table       (today's decisions)
                  algo_beta.db trades table          (all-time executions)
                  data/phase3_outputs/orders.json    (PH3 buy orders)
        Fallback: get_ph2_data() (decisions-only)
        """
        result: dict = {}

        # ── 1. Existing decisions data (today) ─────────────────────
        today = date.today().isoformat()
        recent = []
        entries = skips = blocks = 0

        if self._algo_db and os.path.isfile(self._algo_db):
            try:
                conn = self._connect(self._algo_db)
                rows = conn.execute(
                    "SELECT * FROM decisions WHERE date(timestamp) = ? "
                    "ORDER BY timestamp DESC LIMIT 10",
                    (today,)
                ).fetchall()

                for r in rows:
                    dec = (r["decision"] or "").upper()
                    if "ENTER" in dec or "BUY" in dec:
                        entries += 1
                    elif "BLOCK" in dec:
                        blocks += 1
                    else:
                        skips += 1

                    ts = r["timestamp"] or ""
                    short_time = ts[11:16] if len(ts) >= 16 else ts
                    conf = r["confidence"] or 0.0
                    reason = r["reason"] or "" if "reason" in r.keys() else ""
                    cur_price = r["current_price"] or 0 if "current_price" in r.keys() else 0

                    if conf >= 80:
                        grade = "STRONG_BUY"
                    elif conf >= 65:
                        grade = "BUY"
                    elif conf >= 50:
                        grade = "MODERATE"
                    else:
                        grade = "SKIP"
                    if "BLOCK" in dec:
                        grade = "BLOCKED"

                    recent.append({
                        "time": short_time,
                        "symbol": r["symbol"] or "",
                        "decision": dec if dec else "SKIP",
                        "reason": reason[:40] if reason else "",
                        "confidence": round(conf, 1),
                        "current_price": round(cur_price, 2),
                        "grade": grade,
                    })

                # ── 2. Historical aggregates from trades table ─────────
                hist = {"total_trades": 0, "wins": 0, "win_rate": 0.0,
                        "avg_pnl_pct": 0.0, "avg_duration_min": 0.0,
                        "total_entry_decisions": 0, "decision_accuracy": 0.0}
                try:
                    agg = conn.execute(
                        "SELECT COUNT(*) as total, "
                        "SUM(CASE WHEN win = 1 THEN 1 ELSE 0 END) as wins, "
                        "AVG(pnl_pct) as avg_pnl, "
                        "AVG(duration_minutes) as avg_dur "
                        "FROM trades"
                    ).fetchone()
                    if agg and agg["total"]:
                        total_t = agg["total"]
                        wins_t = agg["wins"] or 0
                        hist["total_trades"] = total_t
                        hist["wins"] = wins_t
                        hist["win_rate"] = round(wins_t / total_t * 100, 1) if total_t else 0
                        hist["avg_pnl_pct"] = round(agg["avg_pnl"] or 0, 2)
                        hist["avg_duration_min"] = round(agg["avg_dur"] or 0, 0)

                    # Entry decision count for accuracy
                    entry_cnt = conn.execute(
                        "SELECT COUNT(*) as cnt FROM decisions "
                        "WHERE UPPER(decision) LIKE '%ENTER%' "
                        "OR UPPER(decision) LIKE '%BUY%'"
                    ).fetchone()
                    if entry_cnt and entry_cnt["cnt"]:
                        hist["total_entry_decisions"] = entry_cnt["cnt"]
                        hist["decision_accuracy"] = round(
                            wins_t / entry_cnt["cnt"] * 100, 1
                        ) if entry_cnt["cnt"] > 0 else 0
                except Exception:
                    pass

                # ── 3. PH3 executions from trades table ───────────────
                ph3_execs = []
                try:
                    trade_rows = conn.execute(
                        "SELECT * FROM trades ORDER BY date DESC, entry_time DESC LIMIT 8"
                    ).fetchall()
                    for tr in trade_rows:
                        ph3_execs.append({
                            "date": tr["date"] or "",
                            "symbol": tr["symbol"] or "",
                            "entry_price": round(tr["entry_price"] or 0, 2),
                            "exit_price": round(tr["exit_price"] or 0, 2),
                            "pnl_pct": round(tr["pnl_pct"] or 0, 2),
                            "win": bool(tr["win"]) if tr["win"] is not None else None,
                            "exit_reason": tr["exit_reason"] or "",
                            "source": "trade",
                        })
                except Exception:
                    pass

                conn.close()

            except Exception as e:
                logger.debug(f"get_ph2_data_v2 DB: {e}")

        # ── 4. Active monitors from ACTIVE.json ───────────────────
        gui_dir = os.path.dirname(os.path.abspath(__file__))
        ph1_dir = os.path.join(os.path.dirname(gui_dir), "data", "phase1_outputs")
        active_path = os.path.join(ph1_dir, "ACTIVE.json")

        active_monitors = []
        phase2_started = False

        if os.path.isfile(active_path):
            try:
                with open(active_path, "r") as f:
                    active = json.load(f)

                phase2_started = active.get("phase2_started", False)

                # Build per-symbol decision lookup for today
                dec_by_sym = {}
                for r in recent:
                    sym = r.get("symbol", "")
                    if sym and sym not in dec_by_sym:
                        dec_by_sym[sym] = r.get("decision", "")

                for stk in active.get("stocks", []):
                    sym = stk.get("symbol", "")
                    dec = dec_by_sym.get(sym, "")
                    if "ENTER" in dec or "BUY" in dec:
                        status = "ENTERED"
                    elif "BLOCK" in dec:
                        status = "BLOCKED"
                    else:
                        status = "MONITORING"

                    trend = stk.get("trend", {})
                    active_monitors.append({
                        "symbol": sym,
                        "ltp": stk.get("ltp", 0),
                        "strategy": stk.get("strategy", ""),
                        "strategy_score": stk.get("strategy_score", 0),
                        "trend": trend,
                        "sector_check": stk.get("sector_check", {}),
                        "status": status,
                    })
            except (json.JSONDecodeError, IOError):
                pass

        # ── 5. Merge orders.json (if trades list is short) ────────
        if len(ph3_execs) < 8:
            orders_path = os.path.join(
                os.path.dirname(gui_dir), "data", "phase3_outputs", "orders.json"
            )
            if os.path.isfile(orders_path):
                try:
                    with open(orders_path, "r") as f:
                        orders = json.load(f)
                    # Only add orders not already covered by trades
                    trade_syms_dates = {
                        (e["symbol"], e["date"]) for e in ph3_execs
                    }
                    for o in sorted(orders, key=lambda x: x.get("timestamp", ""),
                                    reverse=True):
                        od = (o.get("timestamp", ""))[:10]
                        if (o.get("symbol", ""), od) not in trade_syms_dates:
                            ph3_execs.append({
                                "date": od,
                                "symbol": o.get("symbol", ""),
                                "entry_price": round(o.get("price", 0), 2),
                                "exit_price": 0,
                                "pnl_pct": 0,
                                "win": None,
                                "exit_reason": o.get("status", ""),
                                "source": "order",
                            })
                        if len(ph3_execs) >= 8:
                            break
                except (json.JSONDecodeError, IOError):
                    pass

        # ── Assemble result ────────────────────────────────────────
        total_dec = entries + skips + blocks
        result = {
            "source": "ph2_v2",
            "decisions_today": total_dec,
            "monitoring": len(active_monitors),
            "entries": entries,
            "skips": skips,
            "blocks": blocks,
            "recent": recent,
            "active_monitors": active_monitors,
            "phase2_started": phase2_started,
            "ph3_executions": ph3_execs[:8],
            "historical": hist if 'hist' in dir() else {
                "total_trades": 0, "wins": 0, "win_rate": 0.0,
                "avg_pnl_pct": 0.0, "avg_duration_min": 0.0,
                "total_entry_decisions": 0, "decision_accuracy": 0.0,
            },
        }
        return result

    def get_ph3_data(self) -> dict:
        """Read PH3 execution state — active positions + today's trades."""
        result: dict = {}
        data = self.get_latest()
        if not data or not data.db_available:
            return result

        positions = []
        for p in data.positions:
            pnl_pct = 0.0
            if p.entry_price > 0:
                pnl_pct = ((p.current_price - p.entry_price) / p.entry_price) * 100
                if p.direction.upper() in ("SELL", "SHORT"):
                    pnl_pct = -pnl_pct
            positions.append({
                "symbol": p.symbol,
                "direction": p.direction,
                "entry": p.entry_price,
                "current": p.current_price,
                "pnl": f"{pnl_pct:+.1f}%",
                "status": p.status,
            })

        trades = []
        for t in data.trades_today:
            trades.append({
                "symbol": t.symbol,
                "direction": t.direction,
                "entry": t.entry_price,
                "exit": t.exit_price,
                "pnl": f"{t.pnl_pct:+.1f}%",
                "reason": t.exit_reason,
            })

        wins = data.win_count
        total_trades = data.trades_count
        win_rate = (wins / total_trades * 100) if total_trades > 0 else 0.0

        result = {
            "active_positions": len(positions),
            "max_positions": 3,
            "positions": positions,
            "trades_today": total_trades,
            "trades": trades,
            "win_rate": round(win_rate, 1),
            "total_pnl": round(data.total_pnl_today, 2),
        }
        return result

    def get_ph5_paper_trades(self) -> list:
        """Read PH5 paper trade log from JSON file."""
        log_file = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "data", "ph5_paper_trades.json"
        )
        try:
            if os.path.isfile(log_file):
                with open(log_file, 'r') as f:
                    return json.load(f)
        except Exception:
            pass
        return []

    # ------------------------------------------------------------------
    #  TRADES HISTORY (all-time, paginated, with broker charges)
    # ------------------------------------------------------------------

    def get_trades_history(self, page: int = 1, per_page: int = 25) -> dict:
        """Fetch all-time trades with calculated broker charges + aggregates.

        Returns paginated trade list, per-trade fee breakdown, and
        consolidated performance summary.
        """
        result = {
            "source": "trades_history",
            "page": page, "per_page": per_page,
            "total_trades": 0, "total_pages": 0,
            "aggregates": {
                "total_gross_pnl": 0.0, "total_charges": 0.0,
                "total_net_pnl": 0.0,
                "win_count": 0, "loss_count": 0, "win_rate": 0.0,
                "profit_factor": 0.0, "avg_pnl_per_trade": 0.0,
                "avg_duration_min": 0.0,
                "best_trade": {"symbol": "--", "date": "--", "net_pnl": 0.0},
                "worst_trade": {"symbol": "--", "date": "--", "net_pnl": 0.0},
            },
            "trades": [],
        }

        if not self._algo_db or not os.path.isfile(self._algo_db):
            return result

        try:
            conn = self._connect(self._algo_db)
            if conn is None:
                return result

            with conn:
                # ── 1. Aggregate stats ────────────────────────────────
                agg_row = conn.execute(
                    "SELECT COUNT(*) as total_trades, "
                    "  SUM(pnl) as total_gross_pnl, "
                    "  SUM(CASE WHEN win=1 THEN 1 ELSE 0 END) as win_count, "
                    "  SUM(CASE WHEN win=1 THEN pnl ELSE 0 END) as gross_profit, "
                    "  SUM(CASE WHEN win=0 AND pnl<0 THEN ABS(pnl) ELSE 0 END) as gross_loss, "
                    "  AVG(duration_minutes) as avg_duration "
                    "FROM trades"
                ).fetchone()

                total_trades = agg_row["total_trades"] or 0
                if total_trades == 0:
                    return result

                total_gross_pnl = agg_row["total_gross_pnl"] or 0.0
                win_count = agg_row["win_count"] or 0
                loss_count = total_trades - win_count
                gross_profit = agg_row["gross_profit"] or 0.0
                gross_loss = agg_row["gross_loss"] or 0.0
                avg_duration = agg_row["avg_duration"] or 0.0

                # ── 2. Compute total charges from ALL trades ──────────
                all_rows = conn.execute(
                    "SELECT entry_price, exit_price, quantity, direction, "
                    "       pnl, symbol, date "
                    "FROM trades"
                ).fetchall()

                total_charges = 0.0
                best_net = None
                worst_net = None

                for r in all_rows:
                    ep = r["entry_price"] or 0.0
                    xp = r["exit_price"] or 0.0
                    qty = r["quantity"] or 0
                    dr = r["direction"] or "LONG"
                    pnl_val = r["pnl"] or 0.0

                    charges = _calc_broker_charges(ep, xp, qty, dr)
                    net = pnl_val - charges["total"]
                    total_charges += charges["total"]

                    if best_net is None or net > best_net["net_pnl"]:
                        best_net = {"symbol": r["symbol"], "date": r["date"],
                                    "net_pnl": round(net, 2)}
                    if worst_net is None or net < worst_net["net_pnl"]:
                        worst_net = {"symbol": r["symbol"], "date": r["date"],
                                     "net_pnl": round(net, 2)}

                total_charges = round(total_charges, 2)
                total_net_pnl = round(total_gross_pnl - total_charges, 2)
                win_rate = round((win_count / total_trades) * 100, 1) if total_trades > 0 else 0.0
                profit_factor = round(gross_profit / gross_loss, 2) if gross_loss > 0 else 0.0
                avg_pnl = round(total_net_pnl / total_trades, 2) if total_trades > 0 else 0.0

                total_pages = max(1, math.ceil(total_trades / per_page))
                page = max(1, min(page, total_pages))
                offset = (page - 1) * per_page

                result["total_trades"] = total_trades
                result["total_pages"] = total_pages
                result["page"] = page
                result["aggregates"] = {
                    "total_gross_pnl": round(total_gross_pnl, 2),
                    "total_charges": total_charges,
                    "total_net_pnl": total_net_pnl,
                    "win_count": win_count,
                    "loss_count": loss_count,
                    "win_rate": win_rate,
                    "profit_factor": profit_factor,
                    "avg_pnl_per_trade": avg_pnl,
                    "avg_duration_min": round(avg_duration, 1),
                    "best_trade": best_net or {"symbol": "--", "date": "--", "net_pnl": 0.0},
                    "worst_trade": worst_net or {"symbol": "--", "date": "--", "net_pnl": 0.0},
                }

                # ── 3. Page data ──────────────────────────────────────
                page_rows = conn.execute(
                    "SELECT * FROM trades "
                    "ORDER BY date DESC, exit_time DESC "
                    "LIMIT ? OFFSET ?",
                    (per_page, offset)
                ).fetchall()

                # Check if source_phase column exists
                _has_source_phase = "source_phase" in (
                    page_rows[0].keys() if page_rows else []
                )

                # ── 3b. TCAS cross-reference helper ──────────────────
                _TCAS_LEVELS = {"TCAS_ALIM": 3, "TCAS_RA": 2, "TCAS_TA": 1}

                def _get_tcas_info(sym, entry_t, exit_t, trade_date=""):
                    """Cross-reference decisions table for TCAS alerts."""
                    if not entry_t and not exit_t and not trade_date:
                        return {"max_level": "", "count": 0}
                    # Build time window: use entry/exit if available,
                    # fall back to full trade date
                    t_start = entry_t or (trade_date + "T00:00:00" if trade_date else exit_t)
                    t_end = exit_t or (trade_date + "T23:59:59" if trade_date else entry_t)
                    try:
                        tcas_rows = conn.execute(
                            "SELECT reason, COUNT(*) as cnt "
                            "FROM decisions "
                            "WHERE symbol = ? AND reason LIKE 'TCAS%' "
                            "  AND timestamp BETWEEN ? AND ? "
                            "GROUP BY reason",
                            (sym, t_start, t_end)
                        ).fetchall()
                    except Exception:
                        return {"max_level": "", "count": 0}
                    if not tcas_rows:
                        return {"max_level": "", "count": 0}
                    total = 0
                    max_rank = 0
                    max_label = ""
                    for tr in tcas_rows:
                        reason = tr["reason"] or ""
                        cnt = tr["cnt"]
                        total += cnt
                        for prefix, rank in _TCAS_LEVELS.items():
                            if reason.startswith(prefix) and rank > max_rank:
                                max_rank = rank
                                max_label = prefix.replace("TCAS_", "")
                    return {"max_level": max_label, "count": total}

                for r in page_rows:
                    ep = r["entry_price"] or 0.0
                    xp = r["exit_price"] or 0.0
                    qty = r["quantity"] or 0
                    dr = r["direction"] or "LONG"
                    pnl_val = r["pnl"] or 0.0
                    pnl_pct = r["pnl_pct"]

                    charges = _calc_broker_charges(ep, xp, qty, dr)
                    net_pnl = round(pnl_val - charges["total"], 2)

                    # Calculate pnl_pct if missing
                    if pnl_pct is None and ep > 0 and qty > 0:
                        pnl_pct = round((pnl_val / (ep * qty)) * 100, 2)
                    elif pnl_pct is None:
                        pnl_pct = 0.0

                    # Source phase
                    src = ""
                    if _has_source_phase:
                        src = r["source_phase"] or ""

                    # TCAS info
                    tcas = _get_tcas_info(
                        r["symbol"],
                        r["entry_time"],
                        r["exit_time"],
                        r["date"] or "",
                    )

                    result["trades"].append({
                        "date": r["date"] or "",
                        "symbol": r["symbol"] or "",
                        "direction": dr,
                        "quantity": qty,
                        "entry_price": ep,
                        "exit_price": xp,
                        "gross_pnl": round(pnl_val, 2),
                        "charges": charges,
                        "net_pnl": net_pnl,
                        "pnl_pct": pnl_pct,
                        "win": bool(r["win"]),
                        "exit_reason": r["exit_reason"] or "",
                        "duration_minutes": r["duration_minutes"],
                        "source_phase": src,
                        "tcas_max_level": tcas["max_level"],
                        "tcas_count": tcas["count"],
                        "entry_time": r["entry_time"] or "",
                    })

        except Exception as e:
            logger.debug(f"get_trades_history error: {e}")

        return result

    # ------------------------------------------------------------------
    #  PRIVATE DB READERS (continued)
    # ------------------------------------------------------------------

    def _read_chatgpt(self, conn: sqlite3.Connection, data: LiveData):
        """Read recent ChatGPT decisions."""
        today = date.today().isoformat()
        try:
            rows = conn.execute(
                "SELECT * FROM chatgpt_decisions WHERE date = ? "
                "ORDER BY timestamp DESC LIMIT 10",
                (today,)
            ).fetchall()
            for r in rows:
                data.chatgpt_decisions.append(DecisionData(
                    timestamp=r["timestamp"] or "",
                    symbol=r["symbol"] or "",
                    decision=r["recommendation"] or "",
                    reason=r["context_summary"] or "",
                    confidence=r["confidence"] or 0.0,
                ))
        except Exception as e:
            logger.debug(f"  chatgpt read: {e}")
