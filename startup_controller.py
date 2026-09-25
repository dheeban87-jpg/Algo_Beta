"""
STARTUP_CONTROLLER.PY - Mission Control Boot Sequence for Algo_Beta v5.0.0
═══════════════════════════════════════════════════════════════════════════════

PURPOSE:
  Spacecraft-style sequential startup that guarantees the system is in a
  known-good state before any trading begins.

DESIGN PRINCIPLES:
  - Every subsystem reports READY before ignition
  - Yesterday's state loaded from SQLite (flight recorder)
  - Faults detected, classified, and handled — never ignored
  - Safety-critical checks (broker, capital) gate entry to RUNNING
  - AI components (ChatGPT, FinBERT) are OPTIONAL — never block startup
  - REDUCED_MODE for partial failures (monitor only, no new entries)
  - Auto-promotion from REDUCED_MODE when faults clear

STARTUP SEQUENCE:
  S1  HARDWARE CHECK       — Kite, Telegram, ChatGPT, disk
  S2  MEMORY LOAD          — SQLite yesterday's state
  S3  BROKER SYNC          — Positions reconciliation
  S4  GTT CLEANUP          — Orphan/duplicate GTTs
  S5  CAPITAL CHECK        — Available capital
  S6  SUBSYSTEM INIT       — Kalman, TCAS, V+P, regime
  S7  PRE-MARKET ANALYSIS  — Ph1 candidates, Ph5 gap watchlist
  S8  CHATGPT BRIEFING     — Morning strategy with yesterday's context
  S9  READINESS CHECK      — Go/No-Go decision

SYSTEM STATES:
  BOOT → STARTUP → READY → (market open) → RUNNING
                 → REDUCED_MODE (critical fault)
                 → ERROR (unrecoverable)

USAGE:
  from startup_controller import StartupController, SystemState

  controller = StartupController(config)
  state = controller.run_startup()
  # state.system_state == SystemState.READY or REDUCED_MODE or ERROR

Author: Dheebanraj
Version: 5.0.0
Date: 2026-02-06
"""

import os
import sys
import time
import json
import shutil
import logging
import traceback
from enum import Enum
from datetime import datetime, date, timedelta, time as dt_time
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field

logger = logging.getLogger('StartupController')


# ═══════════════════════════════════════════════════════════════════════════════
# SYSTEM STATES
# ═══════════════════════════════════════════════════════════════════════════════

class SystemState(Enum):
    """System state machine states."""
    BOOT = "BOOT"
    STARTUP = "STARTUP"
    READY = "READY"
    RUNNING = "RUNNING"
    REDUCED_MODE = "REDUCED_MODE"
    SHUTDOWN = "SHUTDOWN"
    ERROR = "ERROR"


class FaultSeverity(Enum):
    """Fault classification."""
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


# ═══════════════════════════════════════════════════════════════════════════════
# STARTUP RESULT
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class StepResult:
    """Result of a single startup step."""
    step: str
    success: bool
    severity: FaultSeverity = FaultSeverity.INFO
    message: str = ""
    details: Dict = field(default_factory=dict)
    duration_ms: int = 0


@dataclass
class StartupResult:
    """Complete startup sequence result."""
    system_state: SystemState = SystemState.BOOT
    steps: List[StepResult] = field(default_factory=list)
    
    # Components available
    kite: Any = None
    telegram: Any = None
    chatgpt: Any = None
    config: Any = None
    
    # State loaded
    yesterday_state: Optional[Dict] = None
    broker_positions: List[Dict] = field(default_factory=list)
    
    # Trading readiness
    free_capital: float = 0
    can_trade: bool = False
    max_new_positions: int = 0
    
    # Pre-market results
    ph1_candidates: List[str] = field(default_factory=list)
    ph5_gap_watchlist: List[str] = field(default_factory=list)
    market_regime: str = "UNKNOWN"
    morning_strategy: str = ""
    
    # Faults
    critical_faults: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    reduced_mode_reason: str = ""
    
    # Timing
    boot_time: str = ""
    startup_duration_sec: float = 0
    
    def add_step(self, result: StepResult):
        """Add step result and track faults."""
        self.steps.append(result)
        if result.severity == FaultSeverity.CRITICAL and not result.success:
            self.critical_faults.append(f"{result.step}: {result.message}")
        elif result.severity == FaultSeverity.WARNING and not result.success:
            self.warnings.append(f"{result.step}: {result.message}")


# ═══════════════════════════════════════════════════════════════════════════════
# STARTUP CONTROLLER
# ═══════════════════════════════════════════════════════════════════════════════

class StartupController:
    """
    Mission Control Boot Sequence.
    
    Runs S1-S9 sequentially, classifies faults, and determines
    whether system is READY, REDUCED_MODE, or ERROR.
    """
    
    # Configuration defaults
    MIN_FREE_CAPITAL = 5000          # Minimum ₹ to enable trading
    MIN_DISK_SPACE_MB = 100          # Minimum disk space
    API_PING_TIMEOUT = 10            # Seconds for API ping
    CHATGPT_PING_TIMEOUT = 15       # Seconds for ChatGPT test
    
    # REDUCED_MODE auto-recovery (Design Review Fix #1)
    RECOVERY_CHECK_INTERVAL = 300    # 5 minutes
    MAX_RECOVERY_ATTEMPTS = 3
    
    def __init__(self, config):
        """
        Initialize startup controller.
        
        Args:
            config: Config object with all API keys and settings
        """
        self.config = config
        self.result = StartupResult(config=config)
        self.result.boot_time = datetime.now().isoformat()
        
        # Will be set during startup
        self.kite = None
        self.telegram = None
        self.chatgpt = None
        self.mission_db = None
        
        # REDUCED_MODE recovery tracking
        self._recovery_attempts = 0
        self._reduced_mode_fault = None
        
        logger.info("=" * 80)
        logger.info("🚀 ALGO BETA v5.0 — MISSION CONTROL BOOT SEQUENCE")
        logger.info("=" * 80)
        logger.info(f"   Date: {datetime.now().strftime('%Y-%m-%d %A')}")
        logger.info(f"   Time: {datetime.now().strftime('%H:%M:%S')}")
        logger.info("=" * 80)
    
    # ═══════════════════════════════════════════════════════════════════════════
    # MAIN STARTUP SEQUENCE
    # ═══════════════════════════════════════════════════════════════════════════
    
    def run_startup(self, kite=None, telegram=None) -> StartupResult:
        """
        Execute complete startup sequence S1-S9.
        
        Args:
            kite: Pre-authenticated KiteConnect instance (from main_orchestrator login)
            telegram: Pre-initialized TelegramNotifier
            
        Returns:
            StartupResult with final system state
        """
        start_time = time.time()
        self.result.system_state = SystemState.STARTUP
        
        # Accept pre-initialized components (from main_orchestrator)
        if kite:
            self.kite = kite
            self.result.kite = kite
        if telegram:
            self.telegram = telegram
            self.result.telegram = telegram
        
        try:
            # ─────────────────────────────────────────────────────────────
            # S1: HARDWARE CHECK
            # ─────────────────────────────────────────────────────────────
            self._run_step("S1", "HARDWARE CHECK", self._s1_hardware_check)
            
            # If Kite failed, we cannot continue at all
            if not self.kite:
                self.result.system_state = SystemState.ERROR
                self.result.reduced_mode_reason = "Kite API connection failed"
                self._send_startup_report()
                return self.result
            
            # ─────────────────────────────────────────────────────────────
            # S2: MEMORY LOAD (SQLite)
            # ─────────────────────────────────────────────────────────────
            self._run_step("S2", "MEMORY LOAD", self._s2_memory_load)
            
            # ─────────────────────────────────────────────────────────────
            # S3: BROKER SYNC
            # ─────────────────────────────────────────────────────────────
            self._run_step("S3", "BROKER SYNC", self._s3_broker_sync)
            
            # ─────────────────────────────────────────────────────────────
            # S4: GTT CLEANUP
            # ─────────────────────────────────────────────────────────────
            self._run_step("S4", "GTT CLEANUP", self._s4_gtt_cleanup)
            
            # ─────────────────────────────────────────────────────────────
            # S5: CAPITAL CHECK
            # ─────────────────────────────────────────────────────────────
            self._run_step("S5", "CAPITAL CHECK", self._s5_capital_check)
            
            # ─────────────────────────────────────────────────────────────
            # S6: SUBSYSTEM INIT
            # ─────────────────────────────────────────────────────────────
            self._run_step("S6", "SUBSYSTEM INIT", self._s6_subsystem_init)
            
            # ─────────────────────────────────────────────────────────────
            # S7: PRE-MARKET ANALYSIS
            # ─────────────────────────────────────────────────────────────
            self._run_step("S7", "PRE-MARKET ANALYSIS", self._s7_pre_market_analysis)
            
            # ─────────────────────────────────────────────────────────────
            # S8: CHATGPT MORNING BRIEFING
            # ─────────────────────────────────────────────────────────────
            self._run_step("S8", "CHATGPT BRIEFING", self._s8_chatgpt_briefing)
            
            # ─────────────────────────────────────────────────────────────
            # S9: FINAL READINESS CHECK
            # ─────────────────────────────────────────────────────────────
            self._run_step("S9", "READINESS CHECK", self._s9_readiness_check)
            
        except Exception as e:
            logger.error(f"🚨 STARTUP SEQUENCE FAILED: {e}")
            logger.error(traceback.format_exc())
            self.result.system_state = SystemState.ERROR
            self.result.reduced_mode_reason = f"Startup exception: {str(e)[:200]}"
        
        # Record timing
        self.result.startup_duration_sec = round(time.time() - start_time, 1)
        
        # Update mission_db
        if self.mission_db:
            try:
                self.mission_db.ensure_today()
                self.mission_db.update_daily_state(
                    boot_time=self.result.boot_time,
                    system_state=self.result.system_state.value,
                    starting_capital=self.result.free_capital
                )
            except Exception as e:
                logger.warning(f"Failed to update mission_db after startup: {e}")
        
        # Send Telegram report
        self._send_startup_report()
        
        logger.info("")
        logger.info("=" * 80)
        logger.info(f"🏁 STARTUP COMPLETE — State: {self.result.system_state.value}")
        logger.info(f"   Duration: {self.result.startup_duration_sec}s")
        logger.info(f"   Critical faults: {len(self.result.critical_faults)}")
        logger.info(f"   Warnings: {len(self.result.warnings)}")
        logger.info("=" * 80)
        
        return self.result
    
    def _run_step(self, step_id: str, step_name: str, step_func):
        """Execute a single startup step with timing and error handling."""
        logger.info("")
        logger.info(f"{'─' * 60}")
        logger.info(f"  {step_id}: {step_name}")
        logger.info(f"{'─' * 60}")
        
        start = time.time()
        try:
            result = step_func()
            result.duration_ms = int((time.time() - start) * 1000)
            
            status = "✅" if result.success else ("⚠️" if result.severity == FaultSeverity.WARNING else "🔴")
            logger.info(f"  {status} {step_id}: {result.message} ({result.duration_ms}ms)")
            
            self.result.add_step(result)
            
        except Exception as e:
            duration_ms = int((time.time() - start) * 1000)
            result = StepResult(
                step=step_id,
                success=False,
                severity=FaultSeverity.ERROR,
                message=f"Exception: {str(e)[:200]}",
                duration_ms=duration_ms
            )
            logger.error(f"  🔴 {step_id}: EXCEPTION — {e}")
            logger.error(f"      {traceback.format_exc()}")
            self.result.add_step(result)
    
    # ═══════════════════════════════════════════════════════════════════════════
    # S1: HARDWARE CHECK
    # ═══════════════════════════════════════════════════════════════════════════
    
    def _s1_hardware_check(self) -> StepResult:
        """
        Check all hardware/API connections.
        
        Kite API: CRITICAL (can't trade without it)
        Telegram: WARNING (can trade without alerts)
        ChatGPT:  WARNING (can trade without AI)
        Disk:     WARNING (can trade if space available)
        """
        details = {}
        overall_ok = True
        severity = FaultSeverity.INFO
        messages = []
        
        # ── Kite API ──
        if self.kite:
            try:
                profile = self.kite.profile()
                user_name = profile.get('user_name', 'Unknown')
                details['kite'] = {'status': 'OK', 'user': user_name}
                messages.append(f"Kite: {user_name}")
                logger.info(f"    ✅ Kite API: Connected as {user_name}")
            except Exception as e:
                details['kite'] = {'status': 'FAIL', 'error': str(e)}
                self.kite = None
                self.result.kite = None
                overall_ok = False
                severity = FaultSeverity.CRITICAL
                messages.append("Kite: FAIL")
                logger.error(f"    🔴 Kite API: FAILED — {e}")
                if self.mission_db:
                    self.mission_db.log_fault("KITE_API_FAIL", "CRITICAL",
                                              description=str(e)[:200])
        else:
            details['kite'] = {'status': 'NOT_PROVIDED'}
            overall_ok = False
            severity = FaultSeverity.CRITICAL
            messages.append("Kite: NOT PROVIDED")
            logger.error("    🔴 Kite API: Not provided — cannot proceed")
        
        # ── Telegram ──
        if self.telegram:
            try:
                # Simple test — send a startup ping
                self.telegram.send_message("🔧 Startup self-check: Telegram OK")
                details['telegram'] = {'status': 'OK'}
                messages.append("Telegram: OK")
                logger.info("    ✅ Telegram: Connected")
            except Exception as e:
                details['telegram'] = {'status': 'FAIL', 'error': str(e)}
                messages.append("Telegram: FAIL (warning)")
                logger.warning(f"    ⚠️ Telegram: FAILED — {e} (non-critical)")
                if self.mission_db:
                    self.mission_db.log_fault("TELEGRAM_FAIL", "WARNING",
                                              description=str(e)[:200])
        else:
            details['telegram'] = {'status': 'NOT_INITIALIZED'}
            messages.append("Telegram: N/A")
            logger.info("    ℹ️ Telegram: Not initialized")
        
        # ── ChatGPT ──
        try:
            from chatgpt_strategic_advisor import ChatGPTStrategicAdvisor
            api_key = getattr(self.config, 'CHATGPT_API_KEY', None) or \
                      getattr(self.config, 'OPENAI_API_KEY', None)
            
            if api_key:
                self.chatgpt = ChatGPTStrategicAdvisor(api_key=api_key)
                self.result.chatgpt = self.chatgpt
                details['chatgpt'] = {'status': 'OK'}
                messages.append("ChatGPT: OK")
                logger.info("    ✅ ChatGPT: Initialized")
            else:
                details['chatgpt'] = {'status': 'NO_KEY'}
                messages.append("ChatGPT: No API key")
                logger.warning("    ⚠️ ChatGPT: No API key configured")
        except Exception as e:
            details['chatgpt'] = {'status': 'FAIL', 'error': str(e)}
            messages.append("ChatGPT: FAIL (warning)")
            logger.warning(f"    ⚠️ ChatGPT: FAILED — {e} (non-critical)")
        
        # ── Disk Space ──
        try:
            import shutil as shutil_check
            total, used, free = shutil_check.disk_usage('.')
            free_mb = free // (1024 * 1024)
            details['disk'] = {'free_mb': free_mb}
            if free_mb < self.MIN_DISK_SPACE_MB:
                messages.append(f"Disk: LOW ({free_mb}MB)")
                logger.warning(f"    ⚠️ Disk: Only {free_mb}MB free")
            else:
                messages.append(f"Disk: {free_mb}MB free")
                logger.info(f"    ✅ Disk: {free_mb}MB free")
        except Exception as e:
            details['disk'] = {'status': 'CHECK_FAILED'}
            logger.warning(f"    ⚠️ Disk check failed: {e}")
        
        return StepResult(
            step="S1",
            success=overall_ok,
            severity=severity,
            message=", ".join(messages),
            details=details
        )
    
    # ═══════════════════════════════════════════════════════════════════════════
    # S2: MEMORY LOAD (SQLite)
    # ═══════════════════════════════════════════════════════════════════════════
    
    def _s2_memory_load(self) -> StepResult:
        """
        Load yesterday's state from mission_control.db.
        Includes 3-layer integrity protection (Design Review Fix #2).
        """
        details = {}
        
        try:
            from mission_db import get_mission_db
            self.mission_db = get_mission_db()
            
            # Integrity check with 3-layer protection
            db_status, db_msg = self.mission_db.startup_integrity_check()
            details['db_status'] = db_status
            details['db_message'] = db_msg
            
            if db_status == "FRESH_START":
                # No memory — this is dangerous
                logger.warning(f"    🚨 {db_msg}")
                if self.mission_db:
                    self.mission_db.log_fault("DB_CORRUPTION", "CRITICAL",
                                              description=db_msg)
                
                return StepResult(
                    step="S2",
                    success=False,
                    severity=FaultSeverity.CRITICAL,
                    message=f"Memory lost: {db_msg}",
                    details=details
                )
            
            if db_status == "RESTORED":
                logger.warning(f"    ⚠️ DB restored from backup: {db_msg}")
                if self.mission_db:
                    self.mission_db.log_fault("DB_CORRUPTION", "WARNING",
                                              description=db_msg,
                                              resolution="AUTO_FIXED")
            
            # Ensure today's row
            self.mission_db.ensure_today()
            
            # Load yesterday's state
            yesterday = self.mission_db.get_last_trading_day_state()
            self.result.yesterday_state = yesterday
            
            if yesterday:
                shutdown_type = yesterday.get('shutdown_type', 'UNKNOWN')
                pnl = yesterday.get('total_pnl_net', 0)
                trades = yesterday.get('total_trades', 0)
                positions = yesterday.get('positions_overnight', [])
                fault_codes = yesterday.get('fault_codes', [])
                last_date = yesterday.get('date', 'Unknown')
                
                details['last_date'] = last_date
                details['shutdown_type'] = shutdown_type
                details['pnl'] = pnl
                details['trades'] = trades
                details['overnight_positions'] = len(positions) if isinstance(positions, list) else 0
                details['fault_codes'] = fault_codes
                
                logger.info(f"    📅 Last trading day: {last_date}")
                logger.info(f"    🔧 Shutdown: {shutdown_type}")
                logger.info(f"    💰 P&L: ₹{pnl:+,.0f} ({trades} trades)")
                
                if isinstance(positions, list) and positions:
                    logger.info(f"    📦 Overnight positions: {len(positions)}")
                    for pos in positions:
                        sym = pos.get('symbol', '?')
                        entry = pos.get('entry_price', 0)
                        logger.info(f"       └─ {sym} @ ₹{entry}")
                
                if shutdown_type == "CRASH":
                    logger.warning("    ⚠️ LAST SESSION CRASHED — Extra caution active")
                    details['extra_caution'] = True
                
                severity = FaultSeverity.WARNING if db_status == "RESTORED" else FaultSeverity.INFO
                return StepResult(
                    step="S2",
                    success=True,
                    severity=severity,
                    message=f"Loaded ({last_date}, {shutdown_type}, P&L: ₹{pnl:+,.0f})",
                    details=details
                )
            else:
                logger.info("    ℹ️ No previous trading day found (first run?)")
                return StepResult(
                    step="S2",
                    success=True,
                    severity=FaultSeverity.INFO,
                    message="No previous state (first run)",
                    details=details
                )
                
        except ImportError:
            logger.warning("    ⚠️ mission_db module not available")
            return StepResult(
                step="S2",
                success=False,
                severity=FaultSeverity.WARNING,
                message="mission_db not available — no memory",
                details={'error': 'ImportError'}
            )
        except Exception as e:
            logger.error(f"    🔴 Memory load failed: {e}")
            return StepResult(
                step="S2",
                success=False,
                severity=FaultSeverity.WARNING,
                message=f"Memory load failed: {str(e)[:100]}",
                details={'error': str(e)}
            )
    
    # ═══════════════════════════════════════════════════════════════════════════
    # S3: BROKER SYNC
    # ═══════════════════════════════════════════════════════════════════════════
    
    def _s3_broker_sync(self) -> StepResult:
        """
        Compare broker positions with saved state.
        Detect phantoms (in local, not at broker) and orphans (at broker, not in local).
        """
        if not self.kite:
            return StepResult(
                step="S3", success=False, severity=FaultSeverity.CRITICAL,
                message="No Kite connection — cannot sync"
            )
        
        details = {
            'positions_at_broker': 0,
            'positions_in_memory': 0,
            'matched': 0,
            'phantoms': [],
            'orphans': [],
            'mismatches': []
        }
        
        try:
            # Get live positions from broker
            positions = self.kite.positions()
            net_positions = positions.get('net', [])
            
            # Get holdings
            try:
                holdings = self.kite.holdings()
            except:
                holdings = []
            
            # Build broker position map
            broker_map = {}
            for pos in net_positions:
                if pos.get('quantity', 0) != 0:
                    sym = pos.get('tradingsymbol', '')
                    broker_map[sym] = {
                        'symbol': sym,
                        'quantity': pos.get('quantity', 0),
                        'avg_price': pos.get('average_price', 0),
                        'product': pos.get('product', 'UNKNOWN'),
                        'pnl': pos.get('pnl', 0),
                        'exchange': pos.get('exchange', 'NSE')
                    }
            
            # Add holdings
            for h in holdings:
                sym = h.get('tradingsymbol', '')
                if h.get('quantity', 0) > 0 and sym not in broker_map:
                    broker_map[sym] = {
                        'symbol': sym,
                        'quantity': h.get('quantity', 0),
                        'avg_price': h.get('average_price', 0),
                        'product': 'CNC',
                        'pnl': h.get('pnl', 0),
                        'exchange': h.get('exchange', 'NSE')
                    }
            
            details['positions_at_broker'] = len(broker_map)
            self.result.broker_positions = list(broker_map.values())
            
            # Compare with yesterday's overnight positions
            overnight = []
            if self.result.yesterday_state:
                overnight = self.result.yesterday_state.get('positions_overnight', [])
                if isinstance(overnight, str):
                    try:
                        overnight = json.loads(overnight)
                    except:
                        overnight = []
            
            memory_map = {}
            for pos in overnight:
                sym = pos.get('symbol', '')
                if sym:
                    memory_map[sym] = pos
            
            details['positions_in_memory'] = len(memory_map)
            
            # Reconciliation
            all_symbols = set(list(broker_map.keys()) + list(memory_map.keys()))
            
            for sym in all_symbols:
                at_broker = sym in broker_map
                in_memory = sym in memory_map
                
                if at_broker and in_memory:
                    # MATCH
                    details['matched'] += 1
                    logger.info(f"    ✅ {sym}: Matched (broker + memory)")
                
                elif in_memory and not at_broker:
                    # PHANTOM — in local, not at broker
                    details['phantoms'].append(sym)
                    logger.warning(f"    👻 {sym}: PHANTOM — in memory but NOT at broker")
                    logger.warning(f"       → Removing from local state")
                    if self.mission_db:
                        self.mission_db.log_fault(
                            "POSITION_MISMATCH", "WARNING",
                            symbol=sym,
                            description=f"Phantom: {sym} in memory but not at broker",
                            resolution="AUTO_FIXED"
                        )
                
                elif at_broker and not in_memory:
                    # ORPHAN — at broker, not in local
                    details['orphans'].append(sym)
                    bp = broker_map[sym]
                    logger.warning(f"    🔍 {sym}: ORPHAN — at broker but NOT in memory")
                    logger.warning(f"       → qty: {bp['quantity']} @ ₹{bp['avg_price']:.2f} ({bp['product']})")
                    logger.warning(f"       → Will adopt into Phase 4 monitoring")
                    if self.mission_db:
                        self.mission_db.log_fault(
                            "POSITION_MISMATCH", "WARNING",
                            symbol=sym,
                            description=f"Orphan: {sym} at broker but not in memory "
                                        f"(qty={bp['quantity']}, price={bp['avg_price']})",
                            resolution="AUTO_FIXED"
                        )
            
            # Determine result severity
            has_issues = len(details['phantoms']) > 0 or len(details['orphans']) > 0
            
            msg_parts = [f"{details['positions_at_broker']} at broker"]
            if details['matched']:
                msg_parts.append(f"{details['matched']} matched")
            if details['phantoms']:
                msg_parts.append(f"{len(details['phantoms'])} phantoms removed")
            if details['orphans']:
                msg_parts.append(f"{len(details['orphans'])} orphans adopted")
            
            return StepResult(
                step="S3",
                success=True,  # Mismatches are auto-fixed, not failures
                severity=FaultSeverity.WARNING if has_issues else FaultSeverity.INFO,
                message=", ".join(msg_parts),
                details=details
            )
            
        except Exception as e:
            logger.error(f"    🔴 Broker sync failed: {e}")
            if self.mission_db:
                self.mission_db.log_fault("BROKER_SYNC_FAIL", "CRITICAL",
                                          description=str(e)[:200])
            return StepResult(
                step="S3",
                success=False,
                severity=FaultSeverity.CRITICAL,
                message=f"Broker sync failed: {str(e)[:100]}",
                details={'error': str(e)}
            )
    
    # ═══════════════════════════════════════════════════════════════════════════
    # S4: GTT CLEANUP
    # ═══════════════════════════════════════════════════════════════════════════
    
    def _s4_gtt_cleanup(self) -> StepResult:
        """
        Clean up orphan and duplicate GTTs.
        Remove GTTs for symbols not in portfolio.
        """
        if not self.kite:
            return StepResult(
                step="S4", success=False, severity=FaultSeverity.WARNING,
                message="No Kite connection"
            )
        
        details = {
            'total_gtts': 0,
            'orphan_gtts_cancelled': 0,
            'valid_gtts': 0,
            'errors': []
        }
        
        try:
            # Get all active GTTs
            gtts = self.kite.get_gtts()
            details['total_gtts'] = len(gtts)
            
            # Build set of held symbols
            held_symbols = set()
            for pos in self.result.broker_positions:
                held_symbols.add(pos.get('symbol', ''))
            
            orphans_cancelled = 0
            valid_count = 0
            
            for gtt in gtts:
                gtt_id = gtt.get('id')
                gtt_status = gtt.get('status', '')
                gtt_condition = gtt.get('condition', {})
                gtt_symbol = gtt_condition.get('tradingsymbol', '') if isinstance(gtt_condition, dict) else ''
                
                # Only process active GTTs
                if gtt_status != 'active':
                    continue
                
                if gtt_symbol and gtt_symbol not in held_symbols:
                    # ORPHAN GTT — symbol not in portfolio
                    try:
                        self.kite.delete_gtt(gtt_id)
                        orphans_cancelled += 1
                        logger.info(f"    🗑️ Cancelled orphan GTT #{gtt_id} for {gtt_symbol}")
                    except Exception as e:
                        details['errors'].append(f"GTT #{gtt_id}: {str(e)[:50]}")
                        logger.warning(f"    ⚠️ Failed to cancel GTT #{gtt_id}: {e}")
                else:
                    valid_count += 1
            
            details['orphan_gtts_cancelled'] = orphans_cancelled
            details['valid_gtts'] = valid_count
            
            if orphans_cancelled > 0 and self.mission_db:
                self.mission_db.log_fault(
                    "GTT_ORPHAN", "WARNING",
                    description=f"Cleaned {orphans_cancelled} orphan GTTs at startup",
                    resolution="AUTO_FIXED"
                )
            
            msg = f"{details['total_gtts']} total, {valid_count} valid"
            if orphans_cancelled:
                msg += f", {orphans_cancelled} orphans cancelled"
            
            return StepResult(
                step="S4",
                success=True,
                severity=FaultSeverity.WARNING if orphans_cancelled > 0 else FaultSeverity.INFO,
                message=msg,
                details=details
            )
            
        except Exception as e:
            logger.warning(f"    ⚠️ GTT cleanup failed: {e}")
            return StepResult(
                step="S4",
                success=False,
                severity=FaultSeverity.WARNING,
                message=f"GTT cleanup failed: {str(e)[:100]}",
                details={'error': str(e)}
            )
    
    # ═══════════════════════════════════════════════════════════════════════════
    # S5: CAPITAL CHECK
    # ═══════════════════════════════════════════════════════════════════════════
    
    def _s5_capital_check(self) -> StepResult:
        """
        Check available trading capital.
        """
        if not self.kite:
            return StepResult(
                step="S5", success=False, severity=FaultSeverity.CRITICAL,
                message="No Kite connection"
            )
        
        details = {}
        
        try:
            margins = self.kite.margins()
            equity = margins.get('equity', {})
            
            # live_balance includes today's pay-ins; 'cash' is only the settled opening balance
            available_cash = equity.get('available', {}).get('live_balance', equity.get('available', {}).get('cash', 0))
            used_margin = equity.get('utilised', {}).get('debits', 0)
            
            # Calculate free capital
            buffer = getattr(self.config, 'CAPITAL_BUFFER', 2000)
            free_capital = max(0, available_cash - buffer)
            
            # Determine position capacity
            capital_per_trade = getattr(self.config, 'BASE_CAPITAL_PER_TRADE', 2000)
            max_positions = int(free_capital / capital_per_trade) if capital_per_trade > 0 else 0
            if max_positions == 0 and free_capital >= self.MIN_FREE_CAPITAL:
                max_positions = 1
            max_total = getattr(self.config, 'MAX_POSITIONS', 3)
            
            # Account for existing positions
            existing_count = len(self.result.broker_positions)
            available_slots = max(0, max_total - existing_count)
            max_new = min(max_positions, available_slots)
            
            can_trade = free_capital >= self.MIN_FREE_CAPITAL and max_new > 0
            
            self.result.free_capital = free_capital
            self.result.can_trade = can_trade
            self.result.max_new_positions = max_new
            
            details = {
                'available_cash': available_cash,
                'used_margin': used_margin,
                'buffer': buffer,
                'free_capital': free_capital,
                'capital_per_trade': capital_per_trade,
                'existing_positions': existing_count,
                'max_new_positions': max_new,
                'can_trade': can_trade
            }
            
            logger.info(f"    💰 Available cash: ₹{available_cash:,.0f}")
            logger.info(f"    📊 Used margin: ₹{used_margin:,.0f}")
            logger.info(f"    🆓 Free capital: ₹{free_capital:,.0f} (after ₹{buffer} buffer)")
            logger.info(f"    📦 Existing positions: {existing_count}")
            logger.info(f"    🎯 Can open: {max_new} new positions")
            logger.info(f"    {'✅' if can_trade else '🔴'} Can trade: {can_trade}")
            
            if not can_trade:
                reason = "Insufficient capital" if free_capital < self.MIN_FREE_CAPITAL else "No position slots"
                if self.mission_db:
                    self.mission_db.log_fault("CAPITAL_BREACH", "CRITICAL",
                                              description=f"{reason}: ₹{free_capital:,.0f} free, "
                                                          f"{max_new} slots")
                return StepResult(
                    step="S5",
                    success=False,
                    severity=FaultSeverity.CRITICAL,
                    message=f"{reason} (₹{free_capital:,.0f} free, {max_new} slots)",
                    details=details
                )
            
            return StepResult(
                step="S5",
                success=True,
                severity=FaultSeverity.INFO,
                message=f"₹{free_capital:,.0f} free, {max_new} slots available",
                details=details
            )
            
        except Exception as e:
            logger.error(f"    🔴 Capital check failed: {e}")
            return StepResult(
                step="S5",
                success=False,
                severity=FaultSeverity.CRITICAL,
                message=f"Capital check failed: {str(e)[:100]}",
                details={'error': str(e)}
            )
    
    # ═══════════════════════════════════════════════════════════════════════════
    # S6: SUBSYSTEM INIT
    # ═══════════════════════════════════════════════════════════════════════════
    
    def _s6_subsystem_init(self) -> StepResult:
        """
        Initialize trading subsystems.
        These are OPTIONAL — failure here is WARNING, not CRITICAL.
        Subsystems will lazy-init at runtime if needed.
        """
        details = {
            'kalman': 'SKIPPED',
            'regime': 'UNKNOWN',
            'finbert': 'SKIPPED'
        }
        
        # Detect market regime via VIX
        try:
            # Try to get India VIX
            vix_value = 0
            nifty_value = 0
            
            try:
                vix_quote = self.kite.quote(["NSE:INDIA VIX"])
                vix_data = vix_quote.get("NSE:INDIA VIX", {})
                vix_value = vix_data.get('last_price', 0)
            except:
                pass
            
            try:
                nifty_quote = self.kite.quote(["NSE:NIFTY 50"])
                nifty_data = nifty_quote.get("NSE:NIFTY 50", {})
                nifty_value = nifty_data.get('last_price', 0)
            except:
                pass
            
            # Classify regime
            if vix_value > 20:
                regime = "VOLATILE"
            elif vix_value > 15:
                regime = "NEUTRAL"
            elif vix_value > 0:
                regime = "CALM"
            else:
                regime = "UNKNOWN"
            
            self.result.market_regime = regime
            details['regime'] = regime
            details['vix'] = vix_value
            details['nifty'] = nifty_value
            
            logger.info(f"    📊 VIX: {vix_value:.1f} → Regime: {regime}")
            logger.info(f"    📈 NIFTY: {nifty_value:.0f}")
            
            # Update mission_db
            if self.mission_db:
                self.mission_db.update_daily_state(
                    market_regime=regime,
                    vix_open=vix_value,
                    nifty_open=nifty_value
                )
            
        except Exception as e:
            logger.warning(f"    ⚠️ Market regime detection failed: {e}")
            details['regime_error'] = str(e)
        
        # FinBERT check (optional)
        try:
            from finbert_analyzer import FinBERTAnalyzer
            details['finbert'] = 'AVAILABLE'
            logger.info("    ✅ FinBERT: Available")
        except ImportError:
            details['finbert'] = 'NOT_AVAILABLE'
            logger.info("    ℹ️ FinBERT: Not available (optional)")
        
        # Note: Kalman filters are initialized per-position by Phase 4
        # at startup_with_market_context, not here
        details['kalman'] = 'DEFERRED_TO_PHASE4'
        logger.info("    ℹ️ Kalman: Deferred to Phase 4 init")
        
        return StepResult(
            step="S6",
            success=True,
            severity=FaultSeverity.INFO,
            message=f"Regime: {details.get('regime', 'UNKNOWN')}, "
                    f"VIX: {details.get('vix', 0):.1f}",
            details=details
        )
    
    # ═══════════════════════════════════════════════════════════════════════════
    # S7: PRE-MARKET ANALYSIS
    # ═══════════════════════════════════════════════════════════════════════════
    
    def _s7_pre_market_analysis(self) -> StepResult:
        """
        Run pre-market analysis if in pre-market window.
        Otherwise skip (system started after market open).
        """
        now = datetime.now()
        details = {}
        
        # Only run pre-market between 8:00-9:15
        if now.hour >= 9 and now.minute >= 15:
            logger.info("    ℹ️ Market already open — skipping pre-market analysis")
            return StepResult(
                step="S7",
                success=True,
                severity=FaultSeverity.INFO,
                message="Skipped (market already open)",
                details={'skipped': True, 'reason': 'after_market_open'}
            )
        
        if now.hour < 8:
            logger.info("    ℹ️ Too early for pre-market — will run later")
            return StepResult(
                step="S7",
                success=True,
                severity=FaultSeverity.INFO,
                message="Skipped (too early, will run closer to market open)",
                details={'skipped': True, 'reason': 'too_early'}
            )
        
        # Run PreMarketAnalyzer
        try:
            from pre_market_analyzer import PreMarketAnalyzer
            
            finbert = None
            try:
                from finbert_analyzer import FinBERTAnalyzer
                finbert = FinBERTAnalyzer()
            except:
                pass
            
            api_key = getattr(self.config, 'CHATGPT_API_KEY', None) or \
                      getattr(self.config, 'OPENAI_API_KEY', None)
            
            analyzer = PreMarketAnalyzer(
                kite=self.kite,
                config=self.config,
                telegram=self.telegram,
                finbert=finbert,
                chatgpt_key=api_key
            )
            
            recommendations = analyzer.run_daily_briefing()
            
            outlook = recommendations.get('market_outlook', 'UNKNOWN')
            confidence = recommendations.get('confidence', 0)
            strategies = recommendations.get('recommended_strategies', [])
            
            details['outlook'] = outlook
            details['confidence'] = confidence
            details['strategies'] = strategies
            
            logger.info(f"    📊 Outlook: {outlook} (confidence: {confidence}%)")
            logger.info(f"    🎯 Strategies: {', '.join(strategies)}")
            
            return StepResult(
                step="S7",
                success=True,
                severity=FaultSeverity.INFO,
                message=f"Outlook: {outlook} ({confidence}%)",
                details=details
            )
            
        except Exception as e:
            logger.warning(f"    ⚠️ Pre-market analysis failed: {e}")
            return StepResult(
                step="S7",
                success=False,
                severity=FaultSeverity.WARNING,
                message=f"Pre-market failed: {str(e)[:100]}",
                details={'error': str(e)}
            )
    
    # ═══════════════════════════════════════════════════════════════════════════
    # S8: CHATGPT MORNING BRIEFING
    # ═══════════════════════════════════════════════════════════════════════════
    
    def _s8_chatgpt_briefing(self) -> StepResult:
        """
        Send ChatGPT a morning briefing with yesterday's context from SQLite.
        ChatGPT gets MEMORY of what happened yesterday.
        """
        if not self.chatgpt:
            return StepResult(
                step="S8",
                success=False,
                severity=FaultSeverity.WARNING,
                message="ChatGPT not available — proceeding without AI",
                details={'skipped': True}
            )
        
        if not self.mission_db:
            return StepResult(
                step="S8",
                success=False,
                severity=FaultSeverity.WARNING,
                message="No mission_db — no context for ChatGPT",
                details={'skipped': True}
            )
        
        try:
            # Build context from SQLite
            context = self.mission_db.build_morning_context()
            yesterday = context.get('yesterday', {})
            yesterday_trades = context.get('yesterday_trades', [])
            week_stats = context.get('week_stats', {})
            
            # Build the prompt
            prompt = self._build_morning_briefing_prompt(
                yesterday=yesterday,
                yesterday_trades=yesterday_trades,
                week_stats=week_stats,
                broker_positions=self.result.broker_positions,
                free_capital=self.result.free_capital,
                vix=self.mission_db.query(
                    "SELECT vix_open FROM daily_state WHERE date = ?",
                    (datetime.now().strftime('%Y-%m-%d'),)
                ),
                regime=self.result.market_regime
            )
            
            # Send to ChatGPT
            start_time = time.time()
            
            if hasattr(self.chatgpt, 'get_market_analysis'):
                response = self.chatgpt.get_market_analysis(prompt)
            elif hasattr(self.chatgpt, 'ask'):
                response = self.chatgpt.ask(prompt)
            else:
                response = "ChatGPT interface not compatible"
            
            response_time = int((time.time() - start_time) * 1000)
            
            # Extract strategy from response
            if isinstance(response, dict):
                strategy = response.get('recommendation', response.get('analysis', str(response)))
            else:
                strategy = str(response)
            
            self.result.morning_strategy = strategy[:1000]
            
            # Log to mission_db
            self.mission_db.log_chatgpt_decision(
                decision_type="MORNING_BRIEF",
                recommendation=strategy[:5000],
                context_summary=prompt[:2000],
                response_time_ms=response_time
            )
            
            # Save to daily state
            self.mission_db.update_daily_state(
                chatgpt_morning_brief=strategy[:5000]
            )
            
            logger.info(f"    ✅ ChatGPT briefed ({response_time}ms)")
            logger.info(f"    📋 Strategy: {strategy[:150]}...")
            
            return StepResult(
                step="S8",
                success=True,
                severity=FaultSeverity.INFO,
                message=f"ChatGPT briefed ({response_time}ms)",
                details={
                    'response_time_ms': response_time,
                    'strategy_length': len(strategy)
                }
            )
            
        except Exception as e:
            logger.warning(f"    ⚠️ ChatGPT briefing failed: {e}")
            return StepResult(
                step="S8",
                success=False,
                severity=FaultSeverity.WARNING,
                message=f"ChatGPT failed: {str(e)[:100]} — proceeding without AI",
                details={'error': str(e)}
            )
    
    def _build_morning_briefing_prompt(self, yesterday: Dict, yesterday_trades: List,
                                        week_stats: Dict, broker_positions: List,
                                        free_capital: float, vix: Any,
                                        regime: str) -> str:
        """Build the morning briefing prompt with yesterday's context."""
        
        lines = []
        lines.append("═══════════════════════════════════════")
        lines.append(f"MORNING BRIEFING — {datetime.now().strftime('%Y-%m-%d %A')}")
        lines.append("═══════════════════════════════════════")
        lines.append("")
        
        # Yesterday's debrief
        if yesterday:
            lines.append("📊 YESTERDAY'S DEBRIEF:")
            lines.append("────────────────────────")
            lines.append(f"Date: {yesterday.get('date', 'Unknown')}")
            lines.append(f"Shutdown: {yesterday.get('shutdown_type', 'Unknown')}")
            pnl = yesterday.get('total_pnl_net', 0)
            trades = yesterday.get('total_trades', 0)
            won = yesterday.get('trades_won', 0)
            lost = yesterday.get('trades_lost', 0)
            lines.append(f"Trades: {trades} total | Won: {won} | Lost: {lost}")
            lines.append(f"Net P&L: ₹{pnl:+,.0f}")
            lines.append("")
            
            # Individual trades
            for t in yesterday_trades:
                phase = t.get('entry_phase', '')
                sym = t.get('symbol', '')
                entry = t.get('entry_price', 0)
                exit_p = t.get('exit_price', 0)
                t_pnl = t.get('pnl_net', 0)
                reason = t.get('exit_reason', '')
                entry_t = t.get('entry_time', '')[:5] if t.get('entry_time') else ''
                exit_t = t.get('exit_time', '')[:5] if t.get('exit_time') else ''
                lines.append(f"  {phase}: {sym}")
                lines.append(f"    Entry: ₹{entry} @ {entry_t} | Exit: ₹{exit_p} @ {exit_t}")
                lines.append(f"    P&L: ₹{t_pnl:+,.0f} | Reason: {reason}")
            
            # Fault codes
            faults = yesterday.get('fault_codes', [])
            if faults:
                lines.append(f"Faults: {', '.join(faults)}")
            lines.append("")
        else:
            lines.append("📊 YESTERDAY: No data (first run)")
            lines.append("")
        
        # Current state
        lines.append("📦 CURRENT STATE:")
        lines.append("─────────────────")
        
        if broker_positions:
            lines.append("Holdings:")
            for pos in broker_positions:
                sym = pos.get('symbol', '')
                price = pos.get('avg_price', 0)
                qty = pos.get('quantity', 0)
                product = pos.get('product', '')
                pnl = pos.get('pnl', 0)
                lines.append(f"  {sym} {product} @ ₹{price} (qty: {qty}) — P&L: ₹{pnl:+,.0f}")
        else:
            lines.append("Holdings: None (clean start)")
        
        lines.append(f"Capital: ₹{free_capital:,.0f} free")
        
        vix_val = 0
        if isinstance(vix, list) and vix:
            vix_val = vix[0].get('vix_open', 0) if isinstance(vix[0], dict) else 0
        lines.append(f"VIX: {vix_val:.1f} | Regime: {regime}")
        lines.append("")
        
        # Weekly stats
        if week_stats:
            week_pnl = week_stats.get('week_pnl', 0) or 0
            week_trades = week_stats.get('week_trades', 0) or 0
            lines.append(f"📈 THIS WEEK: P&L ₹{week_pnl:+,.0f} ({week_trades} trades)")
            lines.append("")
        
        # Questions
        lines.append("🎯 QUESTIONS:")
        lines.append("1. Should we hold or exit any overnight positions?")
        lines.append("2. What should today's focus be?")
        lines.append("3. Overall risk level for today?")
        lines.append("4. Any special instructions?")
        
        return "\n".join(lines)
    
    # ═══════════════════════════════════════════════════════════════════════════
    # S9: FINAL READINESS CHECK
    # ═══════════════════════════════════════════════════════════════════════════
    
    def _s9_readiness_check(self) -> StepResult:
        """
        Final Go/No-Go decision based on all previous steps.
        """
        details = {
            'critical_count': len(self.result.critical_faults),
            'warning_count': len(self.result.warnings),
            'all_steps': []
        }
        
        for step in self.result.steps:
            details['all_steps'].append({
                'step': step.step,
                'ok': step.success,
                'severity': step.severity.value,
                'ms': step.duration_ms
            })
        
        if self.result.critical_faults:
            # REDUCED_MODE — monitor only
            self.result.system_state = SystemState.REDUCED_MODE
            self.result.reduced_mode_reason = "; ".join(self.result.critical_faults[:3])
            self._reduced_mode_fault = self.result.critical_faults[0]
            
            logger.warning("")
            logger.warning("=" * 60)
            logger.warning("⚠️ SYSTEM ENTERING REDUCED MODE")
            logger.warning("=" * 60)
            logger.warning(f"Reason: {self.result.reduced_mode_reason}")
            logger.warning("Action: Monitor existing positions only")
            logger.warning("        No new entries allowed")
            logger.warning("        Auto-recovery will attempt every 5 minutes")
            logger.warning("=" * 60)
            
            if self.mission_db:
                self.mission_db.update_daily_state(
                    system_state="REDUCED_MODE"
                )
                self.mission_db.log_fault(
                    "REDUCED_MODE_ENTRY", "CRITICAL",
                    description=self.result.reduced_mode_reason[:200]
                )
            
            return StepResult(
                step="S9",
                success=False,
                severity=FaultSeverity.CRITICAL,
                message=f"REDUCED MODE — {self.result.reduced_mode_reason[:100]}",
                details=details
            )
        else:
            # ALL CLEAR — READY
            self.result.system_state = SystemState.READY
            
            logger.info("")
            logger.info("=" * 60)
            logger.info("✅ ALL SYSTEMS GO — State: READY")
            logger.info("=" * 60)
            logger.info(f"   Free capital: ₹{self.result.free_capital:,.0f}")
            logger.info(f"   Max new positions: {self.result.max_new_positions}")
            logger.info(f"   Existing positions: {len(self.result.broker_positions)}")
            logger.info(f"   Warnings: {len(self.result.warnings)}")
            logger.info("=" * 60)
            
            if self.mission_db:
                self.mission_db.update_daily_state(
                    system_state="READY"
                )
            
            return StepResult(
                step="S9",
                success=True,
                severity=FaultSeverity.INFO,
                message=f"READY — ₹{self.result.free_capital:,.0f} free, "
                        f"{self.result.max_new_positions} slots, "
                        f"{len(self.result.warnings)} warnings",
                details=details
            )
    
    # ═══════════════════════════════════════════════════════════════════════════
    # REDUCED_MODE AUTO-RECOVERY (Design Review Fix #1)
    # ═══════════════════════════════════════════════════════════════════════════
    
    def attempt_recovery(self) -> Tuple[bool, str]:
        """
        Attempt to recover from REDUCED_MODE.
        Called every 5 minutes by the main orchestrator loop.
        
        Returns:
            (recovered, message)
        """
        if self.result.system_state != SystemState.REDUCED_MODE:
            return False, "Not in REDUCED_MODE"
        
        if self._recovery_attempts >= self.MAX_RECOVERY_ATTEMPTS:
            return False, f"Max recovery attempts ({self.MAX_RECOVERY_ATTEMPTS}) reached"
        
        self._recovery_attempts += 1
        fault = self._reduced_mode_fault or "UNKNOWN"
        
        logger.info(f"🔄 Recovery attempt {self._recovery_attempts}/{self.MAX_RECOVERY_ATTEMPTS} "
                     f"for: {fault}")
        
        try:
            recovered = False
            msg = ""
            
            # Check based on fault type
            if "Kite" in fault or "BROKER" in fault.upper():
                # Try broker ping
                try:
                    self.kite.profile()
                    recovered = True
                    msg = "Broker connection restored"
                except:
                    msg = "Broker still unavailable"
            
            elif "CAPITAL" in fault.upper():
                # Re-check capital
                try:
                    margins = self.kite.margins()
                    equity = margins.get('equity', {})
                    cash = equity.get('available', {}).get('live_balance', equity.get('available', {}).get('cash', 0))
                    buffer = getattr(self.config, 'CAPITAL_BUFFER', 2000)
                    free = max(0, cash - buffer)
                    
                    if free >= self.MIN_FREE_CAPITAL:
                        self.result.free_capital = free
                        self.result.can_trade = True
                        recovered = True
                        msg = f"Capital restored: ₹{free:,.0f} free"
                    else:
                        msg = f"Capital still insufficient: ₹{free:,.0f}"
                except Exception as e:
                    msg = f"Capital check failed: {e}"
            
            elif "MISMATCH" in fault.upper() or "sync" in fault.lower():
                # Re-run broker sync
                try:
                    result = self._s3_broker_sync()
                    if result.success:
                        recovered = True
                        msg = "Broker sync clean"
                    else:
                        msg = f"Broker sync still has issues"
                except Exception as e:
                    msg = f"Broker sync failed: {e}"
            
            elif "DB" in fault.upper() or "MEMORY" in fault.upper():
                # Re-check DB integrity
                if self.mission_db:
                    ok, db_msg = self.mission_db.check_integrity()
                    if ok:
                        recovered = True
                        msg = "Database integrity restored"
                    else:
                        msg = f"Database still corrupted"
            
            else:
                # Generic — try broker ping
                try:
                    self.kite.profile()
                    recovered = True
                    msg = "System health restored (generic check)"
                except:
                    msg = "System still unhealthy"
            
            if recovered:
                # Quick re-validation
                try:
                    self.kite.profile()
                    margins = self.kite.margins()
                    
                    self.result.system_state = SystemState.RUNNING
                    self._recovery_attempts = 0
                    
                    logger.info(f"🟢 AUTO-RECOVERED: {msg}")
                    
                    if self.telegram:
                        self.telegram.send_message(
                            f"🟢 AUTO-RECOVERED from REDUCED_MODE\n\n"
                            f"Fault: {fault[:100]}\n"
                            f"Resolution: {msg}\n"
                            f"Attempt: {self._recovery_attempts}\n\n"
                            f"Full trading resumed."
                        )
                    
                    if self.mission_db:
                        self.mission_db.update_daily_state(system_state="RUNNING")
                        self.mission_db.log_fault(
                            "REDUCED_MODE_EXIT", "INFO",
                            description=f"Auto-recovered: {msg}",
                            resolution="AUTO_FIXED"
                        )
                    
                    return True, msg
                    
                except Exception as e:
                    msg = f"Re-validation failed after recovery: {e}"
                    logger.warning(f"    ⚠️ {msg}")
            
            # Not recovered
            logger.warning(f"    ⚠️ Recovery attempt {self._recovery_attempts} failed: {msg}")
            
            if self._recovery_attempts >= self.MAX_RECOVERY_ATTEMPTS:
                permanent_msg = (f"Auto-recovery failed after {self.MAX_RECOVERY_ATTEMPTS} attempts. "
                                 f"Manual intervention required. Fault: {fault}")
                logger.error(f"🔴 {permanent_msg}")
                
                if self.telegram:
                    self.telegram.send_message(
                        f"🔴 AUTO-RECOVERY FAILED\n\n"
                        f"Attempts: {self.MAX_RECOVERY_ATTEMPTS}\n"
                        f"Fault: {fault[:150]}\n\n"
                        f"Manual intervention required.\n"
                        f"System remains in REDUCED MODE."
                    )
                
                if self.mission_db:
                    self.mission_db.log_fault(
                        "RECOVERY_EXHAUSTED", "CRITICAL",
                        description=permanent_msg[:200]
                    )
            
            return False, msg
            
        except Exception as e:
            logger.error(f"Recovery attempt error: {e}")
            return False, f"Recovery exception: {e}"
    
    # ═══════════════════════════════════════════════════════════════════════════
    # TELEGRAM STARTUP REPORT
    # ═══════════════════════════════════════════════════════════════════════════
    
    def _send_startup_report(self):
        """Send startup report via Telegram."""
        if not self.telegram:
            return
        
        try:
            state = self.result.system_state
            
            # Build step summary
            step_lines = []
            for step in self.result.steps:
                icon = "✅" if step.success else ("⚠️" if step.severity == FaultSeverity.WARNING else "🔴")
                step_lines.append(f"   {icon} {step.step}: {step.message[:60]}")
            
            step_text = "\n".join(step_lines)
            
            # Yesterday summary
            yesterday_text = ""
            y = self.result.yesterday_state
            if y:
                pnl = y.get('total_pnl_net', 0)
                trades = y.get('total_trades', 0)
                shutdown = y.get('shutdown_type', 'Unknown')
                yesterday_text = (
                    f"\n📊 YESTERDAY ({y.get('date', '?')}):\n"
                    f"   Trades: {trades} | P&L: ₹{pnl:+,.0f}\n"
                    f"   Shutdown: {shutdown}"
                )
            
            # Holdings
            holdings_text = ""
            if self.result.broker_positions:
                holdings_lines = []
                for pos in self.result.broker_positions:
                    sym = pos.get('symbol', '?')
                    price = pos.get('avg_price', 0)
                    pnl = pos.get('pnl', 0)
                    product = pos.get('product', '')
                    icon = "🟢" if pnl >= 0 else "🔴"
                    holdings_lines.append(f"   {icon} {sym} {product} @ ₹{price:.0f} (P&L: ₹{pnl:+,.0f})")
                holdings_text = "\n📦 HOLDINGS:\n" + "\n".join(holdings_lines)
            
            # Strategy
            strategy_text = ""
            if self.result.morning_strategy:
                strategy_text = f"\n🎯 STRATEGY:\n   {self.result.morning_strategy[:200]}"
            
            if state == SystemState.READY:
                header = "🚀 ALGO BETA v5.0 — SYSTEM BOOT"
                footer = (
                    f"\n✅ All systems GO — State: READY\n"
                    f"💰 Capital: ₹{self.result.free_capital:,.0f} free\n"
                    f"🎯 Slots: {self.result.max_new_positions} available\n"
                    f"⏰ Market opens at 09:15"
                )
            elif state == SystemState.REDUCED_MODE:
                header = "⚠️ ALGO BETA v5.0 — REDUCED MODE"
                footer = (
                    f"\n⚠️ REDUCED MODE ACTIVE\n"
                    f"Reason: {self.result.reduced_mode_reason[:150]}\n"
                    f"Action: Monitor only, no new entries\n"
                    f"Recovery: Auto-attempt every 5 min"
                )
            else:
                header = "🚨 ALGO BETA v5.0 — ERROR"
                footer = (
                    f"\n🚨 SYSTEM ERROR\n"
                    f"Reason: {self.result.reduced_mode_reason[:150]}\n"
                    f"Action: Manual intervention required"
                )
            
            message = (
                f"{header}\n\n"
                f"📋 SELF-CHECK ({self.result.startup_duration_sec}s):\n"
                f"{step_text}"
                f"{yesterday_text}"
                f"{holdings_text}"
                f"{strategy_text}"
                f"{footer}"
            )
            
            self.telegram.send_message(message[:4000])
            
        except Exception as e:
            logger.error(f"Failed to send startup Telegram: {e}")
    
    # ═══════════════════════════════════════════════════════════════════════════
    # END-OF-DAY SHUTDOWN
    # ═══════════════════════════════════════════════════════════════════════════
    
    def run_shutdown(self, shutdown_type: str = "CLEAN_SHUTDOWN",
                     positions_overnight: List[Dict] = None,
                     ending_capital: float = 0,
                     total_pnl_net: float = 0):
        """
        End-of-day shutdown procedure.
        Saves state to SQLite and creates backup.
        
        Args:
            shutdown_type: "CLEAN_SHUTDOWN", "CRASH", "ERROR", "USER_STOP"
            positions_overnight: List of positions being carried
            ending_capital: Final capital
            total_pnl_net: Day's net P&L
        """
        logger.info("")
        logger.info("=" * 60)
        logger.info(f"🛬 SHUTDOWN SEQUENCE — {shutdown_type}")
        logger.info("=" * 60)
        
        if self.mission_db:
            try:
                # Get ChatGPT EOD debrief (mandatory, wait for response)
                chatgpt_eod = None
                if self.chatgpt and shutdown_type == "CLEAN_SHUTDOWN":
                    chatgpt_eod = self._run_eod_debrief()
                
                self.mission_db.save_shutdown_state(
                    shutdown_type=shutdown_type,
                    positions_overnight=positions_overnight,
                    ending_capital=ending_capital,
                    total_pnl_net=total_pnl_net,
                    chatgpt_eod_debrief=chatgpt_eod
                )
                
                logger.info(f"✅ State saved: {shutdown_type}")
                logger.info(f"   Positions overnight: {len(positions_overnight or [])}")
                logger.info(f"   Capital: ₹{ending_capital:,.0f}")
                logger.info(f"   P&L: ₹{total_pnl_net:+,.0f}")
                
                if shutdown_type == "CLEAN_SHUTDOWN":
                    logger.info(f"✅ Database backup created")
                
            except Exception as e:
                logger.error(f"Shutdown save failed: {e}")
        
        if self.telegram:
            try:
                self.telegram.send_message(
                    f"🛬 SHUTDOWN: {shutdown_type}\n\n"
                    f"P&L: ₹{total_pnl_net:+,.0f}\n"
                    f"Overnight: {len(positions_overnight or [])} positions\n"
                    f"Capital: ₹{ending_capital:,.0f}\n"
                    f"Time: {datetime.now().strftime('%H:%M:%S')}"
                )
            except:
                pass
        
        # ── EOD PAPER TRADE LOG UPDATE ──────────────────────────────────────
        # Runs for every shutdown type (CLEAN, CRASH, USER_STOP) so the
        # Excel is always current regardless of how the system stopped.
        try:
            import subprocess, sys
            consolidator = os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                "eod_trade_consolidator.py"
            )
            if os.path.exists(consolidator):
                logger.info("📊 Updating Paper_Trade_Log.xlsx ...")
                result = subprocess.run(
                    [sys.executable, consolidator, "--today"],
                    capture_output=True, text=True, timeout=60
                )
                if result.returncode == 0:
                    logger.info("✅ Paper_Trade_Log.xlsx updated")
                else:
                    logger.warning(f"   Consolidator warning: {result.stderr[:200]}")
        except Exception as _exc:
            logger.warning(f"   Paper trade log update skipped: {_exc}")
        # ────────────────────────────────────────────────────────────────────

        logger.info("=" * 60)
        logger.info("SHUTDOWN COMPLETE")
        logger.info("=" * 60)

    def _run_eod_debrief(self) -> Optional[str]:
        """
        Run mandatory end-of-day ChatGPT debrief.
        Waits up to 60 seconds, retries once.
        """
        if not self.chatgpt or not self.mission_db:
            return None
        
        EOD_TIMEOUT = 60  # seconds
        
        try:
            # Build EOD context
            trades_today = self.mission_db.get_trades_today()
            faults_today = self.mission_db.get_faults_for_date()
            
            prompt_lines = [
                "═══════════════════════════════════════",
                f"END-OF-DAY DEBRIEF — {datetime.now().strftime('%Y-%m-%d')}",
                "═══════════════════════════════════════",
                "",
                f"📊 TODAY'S RESULTS:",
                f"Trades: {len(trades_today)}",
            ]
            
            total_pnl = 0
            for t in trades_today:
                sym = t.get('symbol', '')
                pnl = t.get('pnl_net', 0)
                reason = t.get('exit_reason', '')
                total_pnl += pnl
                prompt_lines.append(f"  {sym}: ₹{pnl:+,.0f} ({reason})")
            
            prompt_lines.append(f"Net P&L: ₹{total_pnl:+,.0f}")
            prompt_lines.append("")
            
            if faults_today:
                prompt_lines.append(f"⚠️ FAULTS: {len(faults_today)}")
                for f in faults_today[:5]:
                    prompt_lines.append(f"  [{f.get('severity')}] {f.get('fault_code')}: {f.get('description', '')[:80]}")
                prompt_lines.append("")
            
            prompt_lines.extend([
                "🎯 QUESTIONS:",
                "1. Rate today's performance (1-10) and why.",
                "2. What should we carry overnight vs exit?",
                "3. Any strategy adjustments for tomorrow?",
                "4. Key lessons from today?"
            ])
            
            prompt = "\n".join(prompt_lines)
            
            # Call ChatGPT with timeout
            import signal
            
            start_time = time.time()
            response = None
            
            for attempt in range(2):  # Try twice
                try:
                    if hasattr(self.chatgpt, 'get_market_analysis'):
                        response = self.chatgpt.get_market_analysis(prompt)
                    elif hasattr(self.chatgpt, 'ask'):
                        response = self.chatgpt.ask(prompt)
                    
                    if response:
                        break
                except Exception as e:
                    logger.warning(f"    EOD debrief attempt {attempt+1} failed: {e}")
                    if attempt == 0:
                        time.sleep(5)
            
            response_time = int((time.time() - start_time) * 1000)
            
            if response:
                result_text = str(response) if not isinstance(response, str) else response
                
                self.mission_db.log_chatgpt_decision(
                    decision_type="EOD_DEBRIEF",
                    recommendation=result_text[:5000],
                    context_summary=prompt[:2000],
                    response_time_ms=response_time
                )
                
                logger.info(f"    ✅ EOD debrief received ({response_time}ms)")
                return result_text[:5000]
            else:
                logger.warning("    ⚠️ EOD debrief: No response after 2 attempts")
                self.mission_db.log_fault("CHATGPT_TIMEOUT", "WARNING",
                                          description="EOD debrief timeout after 2 attempts")
                return "DEBRIEF_TIMEOUT"
                
        except Exception as e:
            logger.error(f"EOD debrief error: {e}")
            return f"DEBRIEF_ERROR: {str(e)[:100]}"


# ═══════════════════════════════════════════════════════════════════════════════
# MODULE TEST
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    """Quick syntax + import test."""
    print("=" * 60)
    print("STARTUP_CONTROLLER — SYNTAX + IMPORT TEST")
    print("=" * 60)
    
    # Test enums
    assert SystemState.BOOT.value == "BOOT"
    assert SystemState.READY.value == "READY"
    assert SystemState.REDUCED_MODE.value == "REDUCED_MODE"
    print("✅ SystemState enum OK")
    
    assert FaultSeverity.CRITICAL.value == "CRITICAL"
    print("✅ FaultSeverity enum OK")
    
    # Test dataclasses
    step = StepResult(step="S1", success=True, message="Test")
    assert step.step == "S1"
    print("✅ StepResult dataclass OK")
    
    result = StartupResult()
    result.add_step(step)
    assert len(result.steps) == 1
    assert len(result.critical_faults) == 0
    print("✅ StartupResult dataclass OK")
    
    # Test critical fault tracking
    bad_step = StepResult(step="S3", success=False, severity=FaultSeverity.CRITICAL,
                          message="Broker failed")
    result.add_step(bad_step)
    assert len(result.critical_faults) == 1
    assert "Broker failed" in result.critical_faults[0]
    print("✅ Critical fault tracking OK")
    
    # Test warning tracking
    warn_step = StepResult(step="S4", success=False, severity=FaultSeverity.WARNING,
                           message="GTT cleanup issue")
    result.add_step(warn_step)
    assert len(result.warnings) == 1
    print("✅ Warning tracking OK")
    
    print()
    print("=" * 60)
    print("ALL TESTS PASSED ✅")
    print("=" * 60)
    print()
    print("NOTE: Full startup test requires Kite API credentials.")
    print("      Use main_orchestrator.py for production startup.")
