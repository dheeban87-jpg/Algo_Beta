from connection_health_monitor import ConnectionHealthMonitor
from daily_blackbox import DailyBlackbox
from chatgpt_strategic_advisor import ChatGPTStrategicAdvisor
from trading_utils import CacheManager

# v1.0.0 NEW: Market Intelligence Engine (MIE)
try:
    from market_intelligence_engine import MarketIntelligenceEngine
    MIE_AVAILABLE = True
except ImportError:
    MIE_AVAILABLE = False
    MarketIntelligenceEngine = None

# Phase 4: Autonomous Portfolio Manager (v4.3)
try:
    from phase4_portfolio_manager import Phase4PortfolioManager
    from broker_sync import BrokerSyncManager, create_broker_sync
    PHASE4_AVAILABLE = True
except ImportError:
    PHASE4_AVAILABLE = False
    Phase4PortfolioManager = None
    BrokerSyncManager = None
    create_broker_sync = None

# v4.5.3 NEW: Capital Manager for centralized capital tracking
try:
    from capital_manager import CapitalManager
    CAPITAL_MANAGER_AVAILABLE = True
except ImportError:
    CAPITAL_MANAGER_AVAILABLE = False
    CapitalManager = None
# v5.0.0 SSOT: Broker Sync Handler for MIS vs CNC separation
try:
    from broker_sync_handler import BrokerSyncHandler
    BROKER_SYNC_HANDLER_AVAILABLE = True
except ImportError:
    BROKER_SYNC_HANDLER_AVAILABLE = False
    BrokerSyncHandler = None
    
# v4.9.0 - Phase 5 Init Fix NEW: Phase 5 Gap Strategy (independent daily trading 09:20-09:45)
# v5.0.0 UPDATE: Phase 5 now hands off to Phase 4 for monitoring
try:
    # Try v5.0.0 first (Phase5IntradayEngine with Phase 4 handoff)
    from phase5_intraday_engine import Phase5IntradayEngine as Phase5GapStrategy, GapStrategyConfig
    PHASE5_AVAILABLE = True
    PHASE5_VERSION = "5.0.0"
except ImportError:
    try:
        # Fallback to v4.9.x (self-contained monitoring)
        from phase5_intraday_engine import Phase5GapStrategy, GapStrategyConfig
        PHASE5_AVAILABLE = True
        PHASE5_VERSION = "4.9.x"
    except ImportError:
        PHASE5_AVAILABLE = False
        Phase5GapStrategy = None
        GapStrategyConfig = None
        PHASE5_VERSION = None

# v6.0: Phase 6 Options Advisory System (Paper Trading)
try:
    from phase6_options_advisor import Phase6OptionsAdvisor
    PHASE6_AVAILABLE = True
except ImportError:
    PHASE6_AVAILABLE = False
    Phase6OptionsAdvisor = None

# v1.0.0: Candlestick Pattern Detector (Advisory layer for Phase 4/6)
try:
    from candlestick_pattern_detector import (
        CandlestickPatternDetector, CandleData, KeyLevels, PatternSignal
    )
    PATTERN_DETECTOR_AVAILABLE = True
except ImportError:
    PATTERN_DETECTOR_AVAILABLE = False
    CandlestickPatternDetector = None
    CandleData = None
    KeyLevels = None
    PatternSignal = None

# v5.4.0: Phase 5A PVAT Breakout Scanner (parallel scanner feeding Phase 5 pipeline)
try:
    from phase5a_pvat_scanner import Phase5APVAT
    PHASE5A_AVAILABLE = True
except ImportError:
    PHASE5A_AVAILABLE = False
    Phase5APVAT = None

# v1.0.0: ORB (Open Range Breakout) Advisory (passive scoreboard for Phase 4/6)
try:
    from orb_advisory import ORBAdvisory
    ORB_AVAILABLE = True
except ImportError:
    ORB_AVAILABLE = False
    ORBAdvisory = None

# v1.0.0: Phase 9 AI Fund Manager (Claude as strategic decision layer)
try:
    from phase9_fund_manager import Phase9FundManager
    PHASE9_AVAILABLE = True
except ImportError:
    PHASE9_AVAILABLE = False
    Phase9FundManager = None

# v8.0.0: Phase 8 Weekly Momentum Strategy
try:
    from phase8_momentum import Phase8MomentumScanner
    from screener_data import ScreenerDataFetcher
    PHASE8_AVAILABLE = True
except ImportError:
    PHASE8_AVAILABLE = False
    Phase8MomentumScanner = None
    ScreenerDataFetcher = None

"""
TRADING SYSTEM ORCHESTRATOR v4.9.0 - PHASE 5 v5.0.0 INTEGRATION
═══════════════════════════════════════════════════════════════════════════════

🔄 v4.9.0 NEW: PHASE 5 v5.0.0 ARCHITECTURE INTEGRATION!
   - Phase 5 now ENTRY ONLY (Scan → Analyze → Approve → Enter)
   - Phase 5 hands off positions to Phase 4 for monitoring
   - Phase 4 handles: Kalman, TCAS/ILS, GTT, Exit
   - Supports LONG and SHORT positions from Phase 5
   - MIS mandatory exit by 12:00 PM

🎯 v4.9.0 - Phase 5 Init Fix NEW: PHASE 5 GAP STRATEGY!
   - Independent daily trading system (09:15-09:25 AM entry window)
   - Gap-up/gap-down detection with FinBERT sentiment alignment
   - Quick scalp: 0.3% target, 0.5x ATR stop
   - Telegram commands: /gap, /gap on, /gap off, /gap status, /gap config
   - Runs BEFORE Phase 1 (09:50) - completely independent capital pool

📱 v4.6.0 NEW: ADAPTIVE TELEGRAM + BOT LISTENER + SYSTEM HEALTH!
   - ChatGPT-driven send/skip decisions (reduces ~64 msgs → ~10-15/day)
   - Two-way Telegram bot: /freq, /status, /stocks, /capital, /quiet, /loud, /scan
   - System health monitoring: battery, CPU, RAM, API status every 30min
   - Thread-safe command queue for bot listener → orchestrator communication

💰 v4.5.4 FIX: BROKER SYNC CAPITAL RELEASE!
   - When GTT executes or manual exit happens, capital is now properly released
   - broker_sync_positions() now calls capital_manager.release() for stale positions
   - Prevents capital accounting drift for externally closed positions

💰 v4.5.3 NEW: CAPITAL MANAGER INTEGRATION!
   - Centralized capital tracking across all phases
   - initial_broker_state from main_orchestrator (zero-second risk window)
   - Capital Manager passed to Phase 2, 3, 4
   - Deploy on BUY fill, Release on SELL fill

🚀 v3.4.0 NEW: NON-BLOCKING RECOVERY + ADMISSION CONTROL!
   - Position-scoped recovery (not global blocking)
   - 3 concurrent positions with admission gates
   - Recovery timeout enforcement (1-2 hours)
   - Emergency SL before ChatGPT attempts
   - Optional Task Scheduler with anti-starvation

🔍 v3.2.0: ADAPTIVE SCANNING SYSTEM
   - Automatic scans every 30 min when < 3 stocks
   - Catches opportunities that develop after scheduled scans
   - Ensures portfolio diversification

🚨 v3.1.0: TRADE GUARANTEE SYSTEM
   - Trade Starvation Prevention (Guarantee minimum trades)
   - Adaptive Exit Manager (Trailing stops, momentum exits)
   - Lower thresholds for more trades in mixed markets

🧠 v3.0.0: INTELLIGENT DECISION ENGINE
   - Probabilistic scoring (0-100 instead of binary)
   - Market regime detection (Trending/Range/Volatile)
   - NIFTY correlation for trade filtering
   - Dynamic position sizing by confidence

⭐ PROFESSIONAL EVENT LOOP CONTROLLER
🚗 Automotive-grade reliability with interrupt handling

ARCHITECTURE:
─────────────
Main Event Loop (1-10 second tick)
├─ 🎯 Phase 5 Gap Strategy (09:18-09:45) ⭐ v4.9.0 - Phase 5 Init Fix NEW!
├─ 📱 Telegram Command Handler (polls bot commands) ⭐ v4.6.0!
├─ 📱 Adaptive Telegram (GPT send/skip decisions) ⭐ v4.6.0!
├─ 🖥️ System Health Monitor (battery/CPU/RAM) ⭐ v4.6.0!
├─ Interrupt Handler (Scheduled Phase 1 scans)
├─ 🔍 Adaptive Scanner (Auto-scans when < 3 stocks)
├─ 🧠 Intelligent Engine (Scores and filters signals)
├─ 🚨 Trade Starvation Prevention (Guarantee trades)
├─ 🎯 Adaptive Exit Manager (Smart exits)
├─ 🛡️ Portfolio Recovery (Position-scoped, non-blocking)
├─ 🚪 Admission Control (Capital gates - OPTIONAL)
├─ ⏰ Task Scheduler (Priority-based - OPTIONAL)
├─ Phase 2 Monitor (5-minute periodic task)
├─ Phase 3 Fast Exit Check (10-second high-priority task)
└─ Market Close Handler (15:25 hard stop)

Author: Dheebanraj
Version: 4.7.0
Date: 2026-02-03
"""

import os
import sys
import time
import logging
import traceback
from datetime import datetime, time as dt_time, timedelta
from typing import Optional, List, Dict
from enum import Enum
from threading import Lock
import html as _html


# ═══════════════════════════════════════════════════════════════════════════════
# POSITION STATE MACHINE - Single Source of Truth (v4.5.0)
# ═══════════════════════════════════════════════════════════════════════════════

class PositionState(Enum):
    """Position lifecycle states"""
    PENDING = "PENDING"      # Order placed, awaiting fill
    OPEN = "OPEN"            # Order filled, position active
    CLOSING = "CLOSING"      # Exit initiated
    CLOSED = "CLOSED"        # Exit complete

# Configure logging — STANDALONE USE ONLY.
# When launched via main_orchestrator.py (normal production path), this entire
# block is skipped because main_orchestrator.py sets up the root logger BEFORE
# importing this module. The guard keeps this as a no-op in production,
# preventing duplicate handlers (was the root cause of every line printing twice).
if not logging.getLogger().handlers:
    os.makedirs('logs', exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler('logs/orchestrator.log', encoding='utf-8'),
            logging.StreamHandler(sys.stdout)
        ]
    )

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# TRADING SYSTEM ORCHESTRATOR - MAIN CONTROLLER
# ═══════════════════════════════════════════════════════════════════════════

class TradingOrchestrator:
    """
    Main event loop controller for the trading system.
    
    v3.4 Features:
    ├─ Non-blocking position-scoped recovery
    ├─ Admission control (3 concurrent positions)
    ├─ Recovery timeout enforcement
    └─ Optional task scheduler
    
    v3.1 Features:
    ├─ Trade Starvation Prevention
    ├─ Adaptive Exit Manager
    ├─ Lower score thresholds
    └─ Better mixed market handling
    """
    
    def __init__(self, kite, config, telegram, initial_broker_state=None):
        """
        Initialize orchestrator.
        
        v4.5.3: Added initial_broker_state and Capital Manager integration.
        
        Args:
            kite: Authenticated KiteConnect instance
            config: Configuration object
            telegram: TelegramNotifier instance
            initial_broker_state: Broker state from immediate check (v4.5.1+)
        """
        self.kite = kite
        self.config = config
        self.telegram = telegram
        self.initial_broker_state = initial_broker_state  # v4.5.1+
        
        # ═══════════════════════════════════════════════════════════════════
        # STATE FLAGS
        # ═══════════════════════════════════════════════════════════════════
        
        self.scans_completed = {
            'initial': False,
            'midday': False,
            'final': False,
            'startup_scan': False  # ✅ v3.1.1: For auto-scan on startup
        }
        
        # ═══════════════════════════════════════════════════════════════════
        # 📡 CENTRAL POSITION STATE - Single Source of Truth (v4.5.0)
        # ═══════════════════════════════════════════════════════════════════
        # All phases read/write through this central state
        # Broker sync every 30s ensures consistency
        # No more Phase 3/4 position mismatch!
        
        self._positions_lock = Lock()  # Thread-safe access
        self._central_positions: Dict[str, Dict] = {}  # symbol -> position_data
        self._broker_sync_interval = 30  # seconds
        self._last_broker_sync = datetime.min
        self._position_event_log = []  # Audit trail
        
        # v4.14.0 PERMANENT FIX: Exit tracking to prevent re-adoption loops
        # When Phase 4 exits a position, broker still shows CNC holding (T+1 settlement).
        # Without this, broker_sync re-adopts → Phase 4 re-exits → infinite loop.
        # Tracks: {symbol: {'exit_time': datetime, 'reason': str, 'exit_date': date}}
        # Cleared: automatically when exit_date != today (new trading day)
        self._exited_today: Dict[str, Dict] = {}
        
        # ═══════════════════════════════════════════════════════════════════
        # 💰 v4.5.3 NEW: Capital Manager - Single Source of Truth for Capital
        # ═══════════════════════════════════════════════════════════════════
        self.capital_manager = None
        
        # v4.9.0 - Phase 5 Init Fix TC-04 FIX: Tick interval management to prevent stacking
        self.last_phase3_check_time = 0
        self.MIN_PHASE3_INTERVAL = 10  # seconds between monitoring checks
        
        if CAPITAL_MANAGER_AVAILABLE:
            try:
                self.capital_manager = CapitalManager(
                    kite=kite,
                    config=config,
                    telegram=telegram
                )
                # Sync with broker immediately to get capital state
                self.capital_manager.sync_with_broker()
                logger.info("✅ Capital Manager initialized and synced")
            except Exception as e:
                logger.error(f"❌ Capital Manager init failed: {e}")
                self.capital_manager = None
        else:
            logger.warning("⚠️ Capital Manager module not available")
        
        # ═══════════════════════════════════════════════════════════════════
        # 📊 MIE v1.0.0: Market Intelligence Engine
        # ═══════════════════════════════════════════════════════════════════
        if MIE_AVAILABLE and getattr(self.config, 'ENABLE_MIE', False):
            try:
                self.mie = MarketIntelligenceEngine(
                    config=self.config,
                    kite=self.kite,
                    capital_manager=self.capital_manager,
                    decision_history=None,  # Set later from Phase 4's decision_tracker
                    phase1_data=None        # Set later after Phase 1 loads stocks
                )
                logger.info("✅ Market Intelligence Engine v1.0.0 initialized")
            except Exception as e:
                logger.error(f"❌ MIE init failed: {e}")
                self.mie = None
        else:
            if not MIE_AVAILABLE:
                logger.info("[i]  MIE: Module not available")
            else:
                logger.info("[i]  MIE: DISABLED in config (ENABLE_MIE=False)")

        # ═══════════════════════════════════════════════════════════════════
        # v4.5.1 NEW: Initialize from broker state if provided
        # ═══════════════════════════════════════════════════════════════════
        if initial_broker_state and initial_broker_state.get('success', False):
            # v4.10.0 FIX: Load BOTH positions (MIS/NRML) AND holdings (CNC)
            # Previously only loaded 'positions', missing CNC overnight holdings!
            positions_raw = initial_broker_state.get('positions', {})
            holdings_from_broker = initial_broker_state.get('holdings', {})
            
            # v4.14.0 FIX: Handle both dict {symbol: data} and list [{tradingsymbol: ..., ...}] formats
            # main_orchestrator v2.5.0 may pass either format depending on DB/API source
            if isinstance(positions_raw, list):
                positions_from_broker = {}
                for pos in positions_raw:
                    symbol = pos.get('tradingsymbol', pos.get('symbol', 'UNKNOWN'))
                    qty = pos.get('quantity', 0)
                    if qty != 0 and symbol != 'UNKNOWN':
                        positions_from_broker[symbol] = {
                            'quantity': qty,
                            'average_price': pos.get('average_price', 0),
                            'last_price': pos.get('last_price', pos.get('average_price', 0)),
                            'pnl': pos.get('pnl', 0),
                            'product': pos.get('product', 'CNC'),
                            'source': 'broker_list_conversion'
                        }
                logger.info(f"   📋 Converted {len(positions_from_broker)} positions from list format")
            else:
                positions_from_broker = positions_raw
            
            # Also handle holdings as list
            if isinstance(holdings_from_broker, list):
                holdings_dict = {}
                for h in holdings_from_broker:
                    symbol = h.get('tradingsymbol', h.get('symbol', 'UNKNOWN'))
                    qty = h.get('quantity', 0)
                    if qty > 0 and symbol != 'UNKNOWN':
                        holdings_dict[symbol] = {
                            'quantity': qty,
                            'average_price': h.get('average_price', 0),
                            'last_price': h.get('last_price', h.get('average_price', 0)),
                            'pnl': h.get('pnl', 0),
                        }
                holdings_from_broker = holdings_dict
                logger.info(f"   📦 Converted {len(holdings_from_broker)} holdings from list format")
            
            # Merge holdings into positions (holdings are CNC delivery positions)
            for symbol, holding_data in holdings_from_broker.items():
                if symbol not in positions_from_broker:
                    # Convert holding format to position format
                    positions_from_broker[symbol] = {
                        'quantity': holding_data.get('quantity', 0),
                        'average_price': holding_data.get('average_price', 0),
                        'last_price': holding_data.get('last_price', 0),
                        'pnl': holding_data.get('pnl', 0),
                        'product': 'CNC',  # Holdings are always CNC
                        'source': 'holdings'
                    }
                    logger.info(f"   📦 Merged CNC holding: {symbol} ({holding_data.get('quantity', 0)} shares)")
            
            if positions_from_broker:
                logger.info("=" * 80)
                logger.info("📡 INITIALIZING FROM BROKER STATE (v4.5.1)")
                logger.info("=" * 80)
                
                for symbol, pos_data in positions_from_broker.items():
                    entry_price = pos_data.get('average_price', 0)
                    quantity = pos_data.get('quantity', 0)
                    
                    if entry_price > 0 and quantity > 0:
                        entry_value = entry_price * quantity
                        
                        central_position = {
                            'symbol': symbol,
                            'quantity': quantity,
                            'entry_price': entry_price,
                            'entry_value': entry_value,
                            'entry_time': datetime.now().isoformat(),
                            'product': pos_data.get('product', 'CNC'),
                            'state': 'OPEN',
                            'stop_price': entry_price * (1 - getattr(self.config, 'STOP_LOSS_PCT', 2) / 100),
                            'target_price': entry_price * (1 + getattr(self.config, 'PROFIT_TARGET_PCT', 3) / 100),
                            'recovered_from_broker': True,
                            'gtt_protected': 'PENDING_RECONCILIATION',  # v4.7.1 FIX-02: Phase 4 will reconcile via kite.get_gtts()
                            'last_price': pos_data.get('last_price', entry_price),
                            'unrealized_pnl': pos_data.get('pnl', 0),
                        }
                        
                        with self._positions_lock:
                            self._central_positions[symbol] = central_position
                        
                        # v4.10.0 FIX: Use adopt_deployed_capital for broker-recovered positions
                        # deploy() expects prior reservation, but broker positions have none
                        if self.capital_manager:
                            if hasattr(self.capital_manager, 'adopt_deployed_capital'):
                                self.capital_manager.adopt_deployed_capital(
                                    symbol=symbol,
                                    amount=entry_value,
                                    quantity=quantity,
                                    avg_price=entry_price
                                )
                            else:
                                # Fallback for older capital manager versions
                                self.capital_manager.deploy(
                                    symbol=symbol,
                                    amount=entry_value,
                                    quantity=quantity,
                                    entry_price=entry_price
                                )
                        
                        self._position_event_log.append({
                            'time': datetime.now().isoformat(),
                            'event': 'RECOVERED_FROM_BROKER',
                            'symbol': symbol,
                            'quantity': quantity,
                            'price': entry_price
                        })
                        
                        logger.info(f"   ✅ {symbol}: {quantity} @ ₹{entry_price:.2f}")
                        logger.info(f"      Stop: ₹{central_position['stop_price']:.2f}")
                        logger.info(f"      Target: ₹{central_position['target_price']:.2f}")
                
                logger.info("")
                logger.info(f"📊 Initialized {len(self._central_positions)} positions from broker state")
                if self.capital_manager:
                    logger.info(f"💰 Capital deployed: ₹{self.capital_manager.deployed_capital:,.0f}")
                logger.info("=" * 80)
                logger.info("")
                
                self._last_broker_sync = datetime.now()
        
        self.interrupt_running = False
        self.last_scan_time = None
        self.active_stock_count = 0
        
        # ═══════════════════════════════════════════════════════════════════
        # TIMING CONFIGURATION
        # ═══════════════════════════════════════════════════════════════════
        
        self.interrupt_schedule = [
            {'hour': 10, 'minute': 0, 'label': 'initial', 'description': 'Initial Scan'},
            {'hour': 13, 'minute': 30, 'label': 'midday', 'description': 'Mid-day Scan'},
            {'hour': 14, 'minute': 55, 'label': 'final', 'description': 'Final Scan'}
        ]
        
        self.PHASE2_INTERVAL = 300
        self.last_phase2_update = datetime.min
        self.PHASE3_FAST_CHECK = 10
        self.TIER1_SLEEP_SECONDS = getattr(self.config, 'TIER1_SLEEP_SECONDS', 10)   # MIS/Phase 5 positions
        self.TIER2_SLEEP_SECONDS = getattr(self.config, 'TIER2_SLEEP_SECONDS', 60)   # CNC positions / idle
        self.HUNT_MODE_INTERVAL = 1800
        self.hunt_mode_active = False
        
        # ✅ v3.2.0 NEW: Adaptive scanning (scan every 30 min if < 3 stocks)
        self.ADAPTIVE_SCAN_ENABLED = True
        self.ADAPTIVE_SCAN_INTERVAL = 30 * 60  # 30 minutes when < 3 stocks
        self.ADAPTIVE_SCAN_THRESHOLD = 3  # Trigger when stocks < 3
        self.last_adaptive_scan = datetime.min
        self.adaptive_scan_count = 0
        
        self.MARKET_START = dt_time(9, 15)
        self.MARKET_END = dt_time(15, 30)
        self.ENTRY_CUTOFF = dt_time(14, 0)
        self.HARD_STOP = dt_time(15, 25)
        self.shutdown_initiated = False
        self._user_shutdown = False  # v8.1.0: Telegram /shutdown command flag
        
        self.HEARTBEAT_INTERVAL = 15 * 60
        self.last_heartbeat_time = 0
        
        # ═══════════════════════════════════════════════════════════════════
        # v4.6.0 NEW: ADAPTIVE TELEGRAM + BOT COMMANDS + SYSTEM HEALTH
        # ═══════════════════════════════════════════════════════════════════
        self.phase2_cycle_count = 0
        self._scan_requested_by_user = False  # Set by /scan command
        # v1.4.0: Trade Confirmation Gate — pending manual confirmations keyed by symbol
        self._pending_confirmations: Dict[str, Dict] = {}

        # v2.0.0: Claude dynamic orchestration — action queue from heartbeat
        self._claude_action_queue: list = []

        # v1.4.0: Phase 9 brain directive flags (set after morning briefing + heartbeat)
        self._ph5_brain_skip       = False   # True = PH5 should not fire today (only when VIX>30 or expiry)
        self._ph5a_brain_pause     = False   # True = PH5A scanning paused
        self._ph4_brain_defensive  = False   # True = PH4 in defensive mode (tighter stops)
        self._ph6_brain_hold       = False   # True = PH6 options advisories paused

        # v1.6.0: VIX history for trend direction (rolling last-N values, one per day)
        self._vix_history: list = []   # appended each morning in _collect_morning_briefing_data

        # Live market data cache — refreshed every 60s via _get_live_market_data()
        self._market_data_cache: dict = {}
        self._market_data_cache_time = None

        # ═══════════════════════════════════════════════════════════════════
        # PHASE MODULES
        # ═══════════════════════════════════════════════════════════════════
        
        self.phase1 = None
        self.phase2 = None
        self.phase3 = None
        self.phase4 = None  # 🛫 Phase 4: Autonomous Portfolio Manager (v4.3)
        self.phase5 = None  # 🎯 Phase 5: Gap Strategy (v4.9.0 - Phase 5 Init Fix NEW!)
        self.phase6 = None  # 📊 Phase 6: Options Advisory (v6.0 - Paper Trading)
        self.phase5a = None  # 🔷 Phase 5A: PVAT Breakout Scanner (v5.4.0)
        self.phase8 = None   # 📈 Phase 8: Weekly Momentum Strategy (v8.0.0)
        self.phase9 = None   # 🧠 Phase 9: AI Fund Manager (v1.0.0)
        self._ph9_last_heartbeat: Optional[datetime] = None  # 25-min heartbeat tracker

        # v8.0.0: Phase 8 tracking
        self._ph8_scan_done_today = False
        self._ph8_scan_last_date = None
        self._ph8_entry_done_today = False
        self._ph8_pending_signal = None         # Holds scan result until 10:00 AM VWAP
        self._ph8_tuesday_checks_done = set()   # Track which exit check times have run today
        self._ph8_tuesday_last_date = None
        self._ph8_morning_review_done_today = False  # v8.1.0: Tier 3 intelligence
        self._ph8_morning_review_last_date = None

        # v5.5.0: PMBI — Pre-Market Breadth Intelligence
        self.market_bias = None          # Dict: {direction, priority, confidence, breadth_ratio, timestamp}
        self._pmbi_done_today = False    # Prevents re-running
        self._pmbi_last_run_date = None  # Track date for daily reset

        self.pattern_detector = None  # 🕯️ Candlestick Pattern Detector (v1.0.0)
        self.orb_advisory = None      # 🔄 ORB Advisory (v1.0.0)
        self._ph6_last_check = 0  # Last premium check timestamp

        # v5.4.1: CNC idle detection (IDLE_HUNT mode)
        self._cnc_idle_since = None
        self._cnc_idle_last_log = datetime.min
        self.CNC_IDLE_THRESHOLD_SEC = 30 * 60     # 30 min = idle
        self.CNC_IDLE_LOG_INTERVAL_SEC = 30 * 60  # log once per 30 min
        self.broker_sync = None  # 📡 Centralized broker communication (v4.3.2)
        
        # 🎯 v4.9.0 - Phase 5 Init Fix NEW: Phase 5 Gap Strategy tracking
        self._phase5_run_today = False
        self._phase5_last_run_date = None
        self._phase5_premarket_done = False  # v5.2.0: Pre-market cache flag

        # 🔷 PH5A v2 Sniper tracking (v5.9.0: Independent mode — no ChatGPT gate)
        self.ph5a_scan_complete = False             # True after single sniper scan finds pipeline stocks
        self.ph5a_done = False                      # True when all PH5A activity is done for the day
        self._ph5a_started_today = False            # Daily guard — auto-fires once after Ph5 window ends
        self._ph5a_last_scan_time = None            # Rescan interval tracking (5 min between scans)
        self._ph5a_hunting = False                  # True = scanning for stocks, False = watching/idle

        # 🧠 Intelligent Engine (v3.0)
        self.intelligent_engine = None
        self.intelligent_wrapper = None

        # 📊 Market Intelligence Engine (MIE v1.0.0)
        self.mie = None
        
        # 🚨 Trade Starvation Prevention (v3.1 NEW!)
        self.starvation_prevention = None
        
        # 🎯 Adaptive Exit Manager (v3.1 NEW!)
        self.adaptive_exit_manager = None
        
        # ═══════════════════════════════════════════════════════════════════
        # v3.4.0 NEW: Portfolio Recovery, Admission Control, Task Scheduler
        # ═══════════════════════════════════════════════════════════════════
        
        # 🛡️ Portfolio Recovery Manager (position-scoped, non-blocking)
        self.portfolio_recovery = None
        
        # 🚪 Admission Controller (optional - flag controlled)
        self.admission_controller = None
        
        # ⏰ Task Scheduler (optional - flag controlled)
        self.task_scheduler = None
        
        # ═══════════════════════════════════════════════════════════════════
        # v4.9.0 - Phase 5 Init Fix NEW: Phase 5 Gap Strategy Initialization
        # v4.9.0 UPDATE: Phase 5 v5.0.0 now hands off to Phase 4 for monitoring
        # ═══════════════════════════════════════════════════════════════════
        if PHASE5_AVAILABLE and getattr(self.config, 'GAP_STRATEGY_ENABLED', True):
            try:
                logger.info(f"⏳ Initializing Phase 5 Gap Strategy (v{PHASE5_VERSION})...")

                # Create config from config.py settings
                gap_config = GapStrategyConfig()
                gap_config.ENABLED = getattr(self.config, 'GAP_STRATEGY_ENABLED', True)
                gap_config.TARGET_PCT = getattr(self.config, 'GAP_TARGET_PCT', 0.3)
                gap_config.STOP_ATR_MULTIPLIER = getattr(self.config, 'GAP_STOP_ATR_MULTIPLIER', 0.5)
                gap_config.MAX_POSITION_VALUE = getattr(self.config, 'GAP_MAX_POSITION_VALUE', 10000)
                gap_config.TIER_1_GAP_PCT = getattr(self.config, 'GAP_THRESHOLD_PRIORITY_1', 1.5)
                gap_config.TIER_2_GAP_PCT = getattr(self.config, 'GAP_THRESHOLD_PRIORITY_2', 1.0)
                gap_config.TIER_3_GAP_PCT = getattr(self.config, 'GAP_THRESHOLD_PRIORITY_3', 0.75)
                gap_config.MIN_VOLUME_RATIO = getattr(self.config, 'GAP_MIN_VOLUME_RATIO', 1.0)
                gap_config.MAX_ADX = getattr(self.config, 'GAP_MAX_ADX', 25)

                # v5.3.5: Phase 5 price range (separate from CNC MIN/MAX_PRICE)
                gap_config.MIN_PRICE = getattr(self.config, 'PH5_MIN_PRICE', 800)
                gap_config.MAX_PRICE = getattr(self.config, 'PH5_MAX_PRICE', 3000)

                # P0 FIX #2: ATR-Scaled Target params (wired from config.py)
                gap_config.ATR_TARGET_MULTIPLIER = getattr(self.config, 'GAP_ATR_TARGET_MULTIPLIER', 0.25)
                gap_config.ATR_TARGET_MIN_PCT = getattr(self.config, 'GAP_ATR_TARGET_MIN_PCT', 0.2)
                gap_config.ATR_TARGET_MAX_PCT = getattr(self.config, 'GAP_ATR_TARGET_MAX_PCT', 1.0)

                # Paper trading mode
                gap_config.PH5_PAPER_MODE = getattr(self.config, 'PH5_PAPER_MODE', True)
                gap_config.PH5_PAPER_LOG_FILE = getattr(self.config, 'PH5_PAPER_LOG_FILE', 'data/ph5_paper_trades.json')

                # v5.0.0: Get ChatGPT advisor for entry approval
                chatgpt_for_phase5 = None
                if hasattr(self, 'strategic_advisor') and self.strategic_advisor:
                    chatgpt_for_phase5 = self.strategic_advisor
                elif hasattr(self.config, 'CHATGPT_API_KEY') and self.config.CHATGPT_API_KEY:
                    try:
                        chatgpt_for_phase5 = ChatGPTStrategicAdvisor(
                            api_key=self.config.CHATGPT_API_KEY,
                            model=getattr(self.config, 'GPT_MODEL', 'gpt-4o')
                        )
                    except:
                        pass
                
                # v5.0.0: Initialize with Phase 4 reference for handoff
                self.phase5 = Phase5GapStrategy(
                    kite=kite,
                    config=gap_config,
                    telegram=telegram,  # v5.1.0: Parameter name is 'telegram'
                    capital_manager=self.capital_manager,
                    chatgpt_advisor=chatgpt_for_phase5,
                    phase4_manager=self.phase4  # v5.0.0: Pass Phase 4 for handoff
                )
                
                # v5.0.0: Set orchestrator reference for position management
                if hasattr(self.phase5, 'set_orchestrator'):
                    self.phase5.set_orchestrator(self)
                    logger.info("   ✅ Orchestrator reference set for Phase 5")
                
                logger.info(f"✅ Phase 5 Gap Strategy initialized (v{PHASE5_VERSION})")
                logger.info(f"   Target: ATR-scaled ({gap_config.ATR_TARGET_MULTIPLIER}×ATR, floor {gap_config.ATR_TARGET_MIN_PCT}%, cap {gap_config.ATR_TARGET_MAX_PCT}%)")
                logger.info(f"   Stop: {gap_config.STOP_ATR_MULTIPLIER}x ATR")
                logger.info(f"   Max Position: ₹{gap_config.MAX_POSITION_VALUE:,}")
                
                if PHASE5_VERSION == "5.0.0":
                    logger.info(f"   Architecture: Entry Engine → Phase 4 Handoff")
                    logger.info(f"   Phase 4 handles: TCAS/ILS/Kalman/GTT/Exit")
                else:
                    logger.info(f"   Architecture: Self-contained monitoring")
                    
            except Exception as e:
                logger.error(f"❌ Phase 5 Gap Strategy init failed: {e}")
                import traceback
                logger.error(traceback.format_exc())
                self.phase5 = None
        else:
            logger.info("ℹ️ Phase 5 Gap Strategy disabled or not available")


        # 🤖 ChatGPT Strategic Advisor (v2.0 NEW!)
        if getattr(self.config, 'ENABLE_CHATGPT_STRATEGIC_ADVISOR', False):
            try:
                logger.info("⏳ Initializing ChatGPT Strategic Advisor (Orchestrator)...")
                self.strategic_advisor = ChatGPTStrategicAdvisor(
                    api_key=self.config.CHATGPT_API_KEY,
                    model=getattr(self.config, 'GPT_MODEL', 'gpt-4o')
                )
                logger.info("✅ Strategic Advisor ready for orchestrator decisions")
            except Exception as e:
                logger.error(f"❌ Strategic Advisor init failed: {e}")
                self.strategic_advisor = None
        else:
            self.strategic_advisor = None
        
        # Track adaptive scan history for GPT
        self.adaptive_scan_results_history = []
        
        logger.info("=" * 80)

        # ✅ Connection Health Monitor
        try:
            self.health_monitor = ConnectionHealthMonitor(self.kite, self.telegram, max_failures=3)
            logger.info("✅ Connection health monitoring enabled")
        except Exception as e:
            logger.warning(f"⚠️ Health monitor not available: {e}")
            self.health_monitor = None

        # ✅ Cache Manager
        try:
            self.cache_manager = CacheManager()
            logger.info("✅ Cache management enabled")
        except Exception as e:
            logger.warning(f"⚠️ Cache manager not available: {e}")
            self.cache_manager = None

        # ✅ Daily Blackbox Recorder
        try:
            self.blackbox = DailyBlackbox()
            self.blackbox.log_event('system', 'startup', {'version': 'v4.9.0'})
            logger.info("✅ Daily blackbox recorder enabled")
        except Exception as e:
            logger.warning(f"⚠️ Blackbox recorder not available: {e}")
            self.blackbox = None

        except Exception as e:
            logger.warning(f"⚠️ Cache manager not available: {e}")
            self.cache_manager = None
        logger.info("ORCHESTRATOR v4.9.0 INITIALIZED")
        logger.info("=" * 80)
        logger.info("")
        logger.info("v4.9.0 Features:")
        logger.info(f"  💰 Capital Manager: {'ENABLED' if self.capital_manager else 'DISABLED'}")
        logger.info(f"  📡 Initial Broker State: {'PROVIDED' if self.initial_broker_state else 'NONE'}")
        logger.info("  🔧 FIX: Broker sync now releases capital for GTT/manual exits")
        logger.info("v3.4 Features:")
        logger.info("  🛡️ Portfolio Recovery (position-scoped)")
        logger.info("  🚪 Admission Control (optional)")
        logger.info("  ⏰ Task Scheduler (optional)")
        logger.info("v3.2 Features:")
        logger.info("  🔍 Adaptive Scanning (auto-scans when < 3 stocks)")
        logger.info("v3.1 Features:")
        logger.info("  🚨 Trade Starvation Prevention")
        logger.info("  🎯 Adaptive Exit Manager")
        logger.info("  📉 Lower Score Thresholds")
        logger.info("  📊 Better Mixed Market Handling")
        logger.info("")
    
    
    def _initialize_phases(self):
        """Initialize Phase 1, 2, 3 + v3.1 modules"""
        
        logger.info("Initializing trading phases...")
        logger.info("")
        
        # ─────────────────────────────────────────────────────────────────
        # Phase 1: Stock Selection
        # ─────────────────────────────────────────────────────────────────
        
        try:
            from phase1_stock_selection import Phase1_StockSelector
            self.phase1 = Phase1_StockSelector(self.kite, self.config)
            logger.info("[OK] Phase 1: Stock Selector initialized")
        except ImportError as e:
            logger.error(f"[X] Failed to import Phase 1: {e}")
            raise
        
        # ─────────────────────────────────────────────────────────────────
        # Phase 3: Order Execution (Initialize BEFORE Phase 2!)
        # ─────────────────────────────────────────────────────────────────
        
        if self.config.ENABLE_PHASE3:
            try:
                from phase3_cash_segment import Phase3CashSegmentExecutor
                self.phase3 = Phase3CashSegmentExecutor(
                    kite=self.kite,
                    config=self.config,
                    telegram=self.telegram,
                    capital_manager=self.capital_manager  # v4.5.3 NEW!
                )

                
                # 🤖 Share strategic advisor with Phase 3 (v2.0 CRITICAL!)
                if hasattr(self, 'strategic_advisor') and self.strategic_advisor:
                    self.phase3.strategic_advisor = self.strategic_advisor
                    logger.info("     └─ Strategic Advisor shared with Phase 3")
                logger.info("[OK] Phase 3: Order Executor initialized (LIVE MODE)")

                # v6.0: Initialize Phase 6 Options Advisory and share with Phase 3
                if PHASE6_AVAILABLE and getattr(self.config, 'PH6_OPTIONS_ADVISORY_ENABLED', False):
                    try:
                        chatgpt_for_ph6 = self.strategic_advisor if hasattr(self, 'strategic_advisor') else None
                        self.phase6 = Phase6OptionsAdvisor(
                            kite=self.kite,
                            config=self.config,
                            telegram=self.telegram,
                            chatgpt_advisor=chatgpt_for_ph6,
                        )
                        self.phase3.options_advisor = self.phase6
                        logger.info("     └─ Phase 6 Options Advisory shared with Phase 3")
                    except Exception as e:
                        logger.error(f"Phase 6 Options Advisory init failed: {e}")
                        self.phase6 = None
            except ImportError as e:
                logger.error(f"[X] Failed to import Phase 3: {e}")
                raise
        else:
            logger.info("[i]  Phase 3: DISABLED (Paper Trading)")
            self.phase3 = None
        
        # ─────────────────────────────────────────────────────────────────
        # ─────────────────────────────────────────────────────────────────
        # 📡 Broker Sync Manager (v4.3.2 NEW!) - Centralized broker communication
        # ─────────────────────────────────────────────────────────────────
        
        
        if create_broker_sync:
            try:
                logger.info("[>] Initializing Broker Sync Manager...")
                self.broker_sync = create_broker_sync(self.kite, self.telegram, self.config)
                
                # v5.0.0 SSOT: BrokerSyncHandler for MIS vs CNC separation
                self._broker_sync_handler = None
                if BROKER_SYNC_HANDLER_AVAILABLE and BrokerSyncHandler:
                    self._broker_sync_handler = BrokerSyncHandler(
                        kite=self.kite,
                        capital_manager=self.capital_manager,
                        phase4=self.phase4,
                        phase3=self.phase3,
                        telegram=self.telegram,
                        broker_sync_manager=self.broker_sync
                    )
                    logger.info("v5.0.0: BrokerSyncHandler initialized")
                
                logger.info("[OK] 📡 Broker Sync Manager initialized")
            except Exception as e:
                logger.error(f"[X] Broker Sync init failed: {e}")
                self.broker_sync = None
        else:
            logger.info("[i]  Broker Sync: Module not available")
        
        # 🛫 Phase 4: Autonomous Portfolio Manager (v4.3 NEW!)
        # ─────────────────────────────────────────────────────────────────
        
        # v4.9.0: Phase 4 no longer needs Phase 3 (deprecated parameter)
        if getattr(self.config, 'ENABLE_PHASE4', True) and PHASE4_AVAILABLE:
            try:
                logger.info("[>] Initializing Phase 4 Portfolio Manager...")
                self.phase4 = Phase4PortfolioManager(
                    kite=self.kite,
                    config=self.config,
                    telegram=self.telegram,
                    phase3_executor=self.phase3,
                    chatgpt_advisor=self.strategic_advisor if hasattr(self, 'strategic_advisor') else None,
                    broker_sync=self.broker_sync,
                    capital_manager=self.capital_manager  # v4.5.3 NEW!
                )
                
                # v4.10.0: Set orchestrator reference for position sync
                if hasattr(self.phase4, 'set_orchestrator'):
                    self.phase4.set_orchestrator(self)
                
                # MIE v1.0.0: Pass MIE to Phase 4 and wire decision_history back
                if self.mie and self.phase4:
                    self.phase4.mie = self.mie
                    # Wire decision_tracker from Phase 4 back to MIE
                    if hasattr(self.phase4, 'decision_tracker') and self.phase4.decision_tracker:
                        self.mie.decision_history = self.phase4.decision_tracker

                # v8.1.0: Wire Tier 3 intelligence dependencies to Phase 4
                if self.phase4:
                    if self.intelligent_engine:
                        self.phase4.intelligent_engine = self.intelligent_engine
                    # FinBERT & news_scraper: lazy-init at review time (see _wire_ph8_intelligence)

                # ISSUE-15: Wire Phase 6 into Phase 4 for TCAS pivot handoff
                # Phase 6 is initialized before Phase 4, so self.phase6 exists here
                if self.phase6:
                    self.phase4.phase6 = self.phase6
                    logger.info("     └─ Phase 6 wired for TCAS pivot signal handoff")

                logger.info("[OK] 🛫 Phase 4: Portfolio Manager initialized")
                logger.info("     └─ Aviation safety: TCAS/ILS/Health active")
            except Exception as e:
                logger.error(f"[X] Phase 4 init failed: {e}")
                logger.error(traceback.format_exc())
                self.phase4 = None
        else:
            if not PHASE4_AVAILABLE:
                logger.info("[i]  Phase 4: Module not available")
            else:
                logger.info("[i]  Phase 4: DISABLED in config")

        # ─────────────────────────────────────────────────────────────────
        # 🧠 Phase 9: AI Fund Manager (v1.0.0)
        # ─────────────────────────────────────────────────────────────────

        if PHASE9_AVAILABLE and getattr(self.config, 'ENABLE_PH9', False):
            try:
                logger.info("[>] Initializing Phase 9 AI Fund Manager...")
                self.phase9 = Phase9FundManager(
                    config=self.config,
                    telegram=self.telegram,
                    kite=self.kite,
                    capital_manager=self.capital_manager
                )

                # Wire to Phase 3 (entry gate)
                if self.phase3:
                    self.phase3.fund_manager = self.phase9
                    logger.info("     └─ Fund Manager wired to Phase 3 (entry gate)")

                # Wire to Phase 4 (exit advisor + P&L tracking)
                if self.phase4:
                    self.phase4.fund_manager = self.phase9
                    logger.info("     └─ Fund Manager wired to Phase 4 (exit advisor)")

                # v1.1.0: Wire to Phase 5 (gap trading entry gate)
                if self.phase5:
                    self.phase5.fund_manager = self.phase9
                    logger.info("     └─ Fund Manager wired to Phase 5 (gap entry gate)")

                # v1.4.0: Wire to Phase 5A (PVAT Sniper entry gate)
                if self.phase5a:
                    self.phase5a.fund_manager = self.phase9
                    logger.info("     └─ Fund Manager wired to Phase 5A (sniper entry gate)")

                # v1.4.0: Wire to Phase 8 (weekly momentum entry gate)
                if self.phase8:
                    self.phase8.fund_manager = self.phase9
                    logger.info("     └─ Fund Manager wired to Phase 8 (momentum entry gate)")

                logger.info("[OK] 🧠 Phase 9: AI Fund Manager initialized")
            except Exception as e:
                logger.error(f"[X] Phase 9 init failed: {e}")
                logger.error(traceback.format_exc())
                self.phase9 = None
        else:
            if not PHASE9_AVAILABLE:
                logger.info("[i]  Phase 9: Module not available")
            else:
                logger.info("[i]  Phase 9: DISABLED in config")

        # ─────────────────────────────────────────────────────────────────
        # 🕯️ Candlestick Pattern Detector (v1.0.0)
        # ─────────────────────────────────────────────────────────────────

        if PATTERN_DETECTOR_AVAILABLE and getattr(self.config, 'CANDLESTICK_PATTERN_ENABLED', False):
            try:
                self.pattern_detector = CandlestickPatternDetector(self.config)
                logger.info("[OK] Candlestick Pattern Detector initialized")
            except Exception as e:
                logger.error(f"[X] Candlestick Pattern Detector init failed: {e}")
                self.pattern_detector = None
        else:
            if not PATTERN_DETECTOR_AVAILABLE:
                logger.info("[i]  Candlestick Pattern Detector: Module not available")
            else:
                logger.info("[i]  Candlestick Pattern Detector: DISABLED in config")

        # ─────────────────────────────────────────────────────────────────
        # 🔄 ORB (Open Range Breakout) Advisory (v1.0.0)
        # ─────────────────────────────────────────────────────────────────

        if ORB_AVAILABLE and getattr(self.config, 'ORB_ADVISORY_ENABLED', False):
            try:
                self.orb_advisory = ORBAdvisory(self.config)
                logger.info("[OK] ORB Advisory initialized")
            except Exception as e:
                logger.error(f"[X] ORB Advisory init failed: {e}")
                self.orb_advisory = None
        else:
            if not ORB_AVAILABLE:
                logger.info("[i]  ORB Advisory: Module not available")
            else:
                logger.info("[i]  ORB Advisory: DISABLED in config")

        # Wire ORB reference into Phase 6 and Phase 4 (pull model)
        if self.orb_advisory:
            if self.phase6 and hasattr(self.phase6, 'set_orb_advisory'):
                self.phase6.set_orb_advisory(self.orb_advisory)
                logger.info("     └─ ORB Advisory shared with Phase 6")
            if self.phase4 and hasattr(self.phase4, 'set_orb_advisory'):
                self.phase4.set_orb_advisory(self.orb_advisory)
                logger.info("     └─ ORB Advisory shared with Phase 4")

        # ─────────────────────────────────────────────────────────────────
        # 🔷 Phase 5A: PVAT Breakout Scanner (v5.4.0)
        # ─────────────────────────────────────────────────────────────────

        if PHASE5A_AVAILABLE and getattr(self.config, 'PVAT_ENABLED', False) and self.phase5:
            try:
                self.phase5a = Phase5APVAT(
                    kite=self.kite,
                    config=self.config,
                    telegram=self.telegram,
                    phase4_manager=self.phase4,
                    capital_manager=self.capital_manager,
                    chatgpt_advisor=self.strategic_advisor,
                    phase5_engine=self.phase5,              # kept for data access only
                    candlestick_detector=self.pattern_detector  # may be None
                )
                logger.info("[OK] Phase 5A PVAT Breakout Scanner v5.4.2 initialized (independent)")
                logger.info("     PH5A v2 Sniper: ENABLED" if getattr(self.config, 'PH5A_SNIPER_ENABLED', True) else "     PH5A v2 Sniper: DISABLED (legacy mode)")
            except Exception as e:
                logger.error(f"[X] Phase 5A PVAT Scanner init failed: {e}")
                self.phase5a = None
        else:
            if not PHASE5A_AVAILABLE:
                logger.info("[i]  Phase 5A PVAT Scanner: Module not available")
            elif not self.phase5:
                logger.info("[i]  Phase 5A PVAT Scanner: Requires Phase 5 (not initialized)")
            else:
                logger.info("[i]  Phase 5A PVAT Scanner: DISABLED in config (PVAT_ENABLED=False)")

        # ─────────────────────────────────────────────────────────────────
        # 📈 Phase 8: Weekly Momentum Strategy (v8.0.0)
        # ─────────────────────────────────────────────────────────────────

        if PHASE8_AVAILABLE and getattr(self.config, 'ENABLE_PH8', False):
            try:
                logger.info("[>] Initializing Phase 8 Weekly Momentum Strategy...")

                # Create screener data fetcher
                screener_fetcher = ScreenerDataFetcher(self.config)

                self.phase8 = Phase8MomentumScanner(
                    kite=self.kite,
                    config=self.config,
                    capital_manager=self.capital_manager,
                    telegram=self.telegram,
                    screener_fetcher=screener_fetcher
                )

                # Wire Phase 4 reference for Tier 3 queries
                if self.phase4:
                    self.phase8.phase4 = self.phase4
                    self.phase4.phase8 = self.phase8  # v8.1.0: for instrument token lookup

                # v8.0.0: Wire Tier 3 tracker to BrokerSyncHandler
                # so broker_sync skips re-adopting Ph8 CNC positions as OBSERVE_ONLY
                if self._broker_sync_handler and self.phase4:
                    self._broker_sync_handler.tier3_tracker = self.phase4
                    logger.info("     └─ Tier 3 tracker wired to BrokerSyncHandler")

                logger.info("[OK] 📈 Phase 8: Weekly Momentum Strategy initialized")
                logger.info(f"     └─ Scan day: Wednesday | Max concurrent: {getattr(self.config, 'PH8_MAX_CONCURRENT', 2)}")
                logger.info(f"     └─ Fixed amount: ₹{getattr(self.config, 'PH8_FIXED_AMOUNT', 50000):,}")
                logger.info(f"     └─ Shadow: {'ENABLED' if getattr(self.config, 'PH8_SHADOW_ENABLED', True) else 'DISABLED'}")
            except Exception as e:
                logger.error(f"[X] Phase 8 Momentum init failed: {e}")
                import traceback
                logger.error(traceback.format_exc())
                self.phase8 = None
        else:
            if not PHASE8_AVAILABLE:
                logger.info("[i]  Phase 8 Momentum: Module not available")
            else:
                logger.info("[i]  Phase 8 Momentum: DISABLED in config (ENABLE_PH8=False)")

        # ─────────────────────────────────────────────────────────────────
        # Phase 2: Entry Timing
        # ─────────────────────────────────────────────────────────────────

        try:
            from phase2_entry_timing import Phase2EntryMonitor
            self.phase2 = Phase2EntryMonitor(
                kite=self.kite,
                config=self.config,
                telegram=self.telegram,
                phase3_manager=self.phase3,
                capital_manager=self.capital_manager  # v4.5.3 NEW!
            )
            logger.info("[OK] Phase 2: Entry Monitor initialized")
        except ImportError as e:
            logger.error(f"[X] Failed to import Phase 2: {e}")
            raise
        
        # ═══════════════════════════════════════════════════════════════════
        # v4.7.2 FIX: SYNC RECOVERED POSITIONS TO PHASE 3
        # ═══════════════════════════════════════════════════════════════════
        # Positions were recovered from broker BEFORE Phase 3 was initialized.
        # Now that Phase 3 exists, sync the recovered positions into it.
        # This fixes the "Position not found for exit" bug when Phase 4
        # tries to exit a position that Phase 3 doesn't know about.
        # ═══════════════════════════════════════════════════════════════════
        
        if self.phase3 and self._central_positions:
            logger.info("")
            logger.info("═" * 60)
            logger.info("📡 SYNCING RECOVERED POSITIONS TO PHASE 3")
            logger.info("═" * 60)
            
            synced_count = 0
            for symbol, pos_data in self._central_positions.items():
                if symbol not in self.phase3.positions:
                    try:
                        self.phase3.adopt_position_from_broker(
                            symbol=symbol,
                            quantity=pos_data.get('quantity', 0),
                            avg_price=pos_data.get('entry_price', 0),
                            product=pos_data.get('product', 'CNC'),
                            last_price=pos_data.get('last_price', pos_data.get('entry_price', 0))
                        )
                        synced_count += 1
                        logger.info(f"   ✅ {symbol}: Synced to Phase 3")
                    except Exception as e:
                        logger.error(f"   ❌ {symbol}: Failed to sync - {e}")
            
            if synced_count > 0:
                logger.info(f"📡 Synced {synced_count} positions to Phase 3")
            logger.info("═" * 60)
            logger.info("")
        
        # ─────────────────────────────────────────────────────────────────
        # 🚨 Trade Starvation Prevention (v3.1 NEW!)
        # ─────────────────────────────────────────────────────────────────
        
        if getattr(self.config, 'ENABLE_STARVATION_PREVENTION', True):
            try:
                from phase3_adaptive_exits import TradeStarvationPrevention
                self.starvation_prevention = TradeStarvationPrevention(self.config)
                logger.info("[OK] 🚨 Trade Starvation Prevention: ENABLED")
                logger.info(f"     └─ Min daily trades: {self.starvation_prevention.MIN_DAILY_TRADES}")
            except ImportError as e:
                logger.warning(f"[!] Starvation Prevention not available: {e}")
        
        # ─────────────────────────────────────────────────────────────────
        # 🎯 Adaptive Exit Manager (OBSOLETE - Phase 4 handles exits)
        # ─────────────────────────────────────────────────────────────────
        # NOTE: AdaptiveExitManager from phase3_adaptive_exits.py is OBSOLETE
        # as of v4.3. Phase 4's TCAS/ILS monitoring handles all exit logic:
        # - Trailing stops (ILS-based)
        # - Health monitoring (TCAS)
        # - ChatGPT exit decisions
        # - Partial profit booking
        # - GTT order management
        # ─────────────────────────────────────────────────────────────────
        
        self.adaptive_exit_manager = None  # Obsolete - Phase 4 handles exits
        logger.info("[OK] 🎯 Adaptive Exits: Handled by Phase 4 TCAS/ILS")
        
        # ─────────────────────────────────────────────────────────────────
        # 🧠 Intelligent Decision Engine v1.1
        # ─────────────────────────────────────────────────────────────────
        
        if getattr(self.config, 'USE_INTELLIGENT_ENGINE', True):
            try:
                # ✅ FIX: Try both file naming conventions
                try:
                    from intelligent_engine import IntelligentDecisionEngine
                    logger.info("[OK] 🧠 Intelligent Engine v1.1: LOADED (intelligent_engine.py)")
                except ImportError:
                    try:
                        from intelligent_engine_v1_1 import IntelligentDecisionEngine
                        logger.info("[OK] 🧠 Intelligent Engine v1.1: LOADED (intelligent_engine_v1_1.py)")
                    except ImportError:
                        raise ImportError("Could not import IntelligentDecisionEngine from any file!")
                
                from phase2_intelligent_integration import IntelligentPhase2Wrapper
                
                # Create engine WITH starvation prevention linked
                self.intelligent_engine = IntelligentDecisionEngine(
                    self.kite, self.config, self.telegram,
                    starvation_prevention=self.starvation_prevention
                )
                
                self.intelligent_wrapper = IntelligentPhase2Wrapper(
                    self.phase2, self.kite, self.config, self.telegram
                )
                
                # Replace wrapper's engine with our instance
                self.intelligent_wrapper.intelligent_engine = self.intelligent_engine

                # 🤖 Share strategic advisor with wrapper (v2.0 CRITICAL!)
                if self.strategic_advisor:
                    self.intelligent_wrapper.strategic_advisor = self.strategic_advisor
                    logger.info("     ├─ Strategic Advisor shared with Phase 2 wrapper")

                # 📊 MIE v1.0.0: Share MIE with Phase 2 wrapper
                if self.mie:
                    self.intelligent_wrapper.mie = self.mie
                    logger.info("     ├─ MIE shared with Phase 2 wrapper")
                
                
                logger.info("     ├─ Probabilistic Scoring")
                logger.info("     ├─ Market Regime Detection")
                logger.info("     ├─ NIFTY Correlation")
                logger.info("     ├─ Dynamic Position Sizing")
                if self.starvation_prevention:
                    logger.info("     └─ Starvation Prevention LINKED")
                    
            except ImportError as e:
                logger.warning(f"[!] Intelligent Engine not available: {e}")
                logger.info("     Falling back to standard Phase 2 signals")
        else:
            logger.info("[i]  Intelligent Engine: DISABLED")
        
        # ─────────────────────────────────────────────────────────────────
        # 🛡️ LEGACY: Portfolio Recovery Manager (OBSOLETE - Phase 4 handles this)
        # ─────────────────────────────────────────────────────────────────
        # NOTE: intelligent_portfolio_recovery.py and position_recovery.py are
        # OBSOLETE as of v4.3. Phase 4's _sync_with_broker() now handles:
        # - Fetching positions from kite.positions() (MIS/NRML)
        # - Fetching holdings from kite.holdings() (CNC)
        # - Adding untracked positions to monitoring
        # - Placing GTT orders for manual positions
        #
        # The old recovery modules can be archived/deleted.
        # ─────────────────────────────────────────────────────────────────
        
        self.portfolio_recovery = None  # Obsolete - Phase 4 handles recovery
        logger.info("[OK] 🛡️ Position Recovery: Handled by Phase 4 broker sync")
        
        # ─────────────────────────────────────────────────────────────────
        # 🚪 v3.4.0 NEW: Admission Controller (OPTIONAL)
        # ─────────────────────────────────────────────────────────────────
        
        if getattr(self.config, 'ENABLE_ADMISSION_CONTROL', False):
            try:
                from admission_controller import AdmissionController
                self.admission_controller = AdmissionController(
                    config=self.config,
                    recovery_manager=self.portfolio_recovery if self.portfolio_recovery else None
                )
                logger.info("[OK] 🚪 Admission Controller: ENABLED")
                logger.info(f"     ├─ Max positions: {self.admission_controller.MAX_ACTIVE_POSITIONS}")
                logger.info(f"     ├─ Max capital: ₹{self.admission_controller.MAX_CAPITAL_DEPLOYED:,}")
                logger.info("     └─ 5 admission gates active")
            except ImportError as e:
                logger.warning(f"[!] Admission Controller not available: {e}")
        
        # ─────────────────────────────────────────────────────────────────
        # ⏰ v3.4.0 NEW: Task Scheduler (OPTIONAL)
        # ─────────────────────────────────────────────────────────────────
        
        if getattr(self.config, 'ENABLE_TASK_SCHEDULER', False):
            try:
                from task_scheduler import TaskScheduler
                self.task_scheduler = TaskScheduler(config=self.config)
                logger.info("[OK] ⏰ Task Scheduler: ENABLED")
                logger.info("     ├─ Priority-based execution")
                logger.info("     ├─ Anti-starvation enforcement")
                logger.info("     └─ Frequency guarantees")
            except ImportError as e:
                logger.warning(f"[!] Task Scheduler not available: {e}")
        
        # ─────────────────────────────────────────────────────────────────
        # 📡 v4.5.0: Link Phase 3 to Orchestrator for position state sync
        # ─────────────────────────────────────────────────────────────────
        
        if self.phase3 and hasattr(self.phase3, 'set_orchestrator'):
            self.phase3.set_orchestrator(self)
            logger.info("[OK] 📡 Phase 3 linked to Central Position State")
        
        logger.info("")
        logger.info("[OK] All phases initialized successfully")
        logger.info("")
    
    
    # ═══════════════════════════════════════════════════════════════════════════
    # 📡 CENTRAL POSITION STATE MANAGER (v4.5.0)
    # ═══════════════════════════════════════════════════════════════════════════
    
    @property
    def positions(self) -> Dict[str, Dict]:
        """Get all open positions (thread-safe read)"""
        with self._positions_lock:
            return {s: p.copy() for s, p in self._central_positions.items() 
                    if p.get('state') in [PositionState.OPEN.value, 'OPEN']}
    
    def get_position(self, symbol: str) -> Optional[Dict]:
        """Get single position by symbol"""
        with self._positions_lock:
            return self._central_positions.get(symbol, {}).copy() or None
    
    def has_position(self, symbol: str) -> bool:
        """Check if position exists and is OPEN"""
        with self._positions_lock:
            pos = self._central_positions.get(symbol)
            return pos is not None and pos.get('state') in [PositionState.OPEN.value, 'OPEN']
    
    def get_open_position_count(self) -> int:
        """Get count of open positions"""
        with self._positions_lock:
            return len([p for p in self._central_positions.values() 
                       if p.get('state') in [PositionState.OPEN.value, 'OPEN']])
    
    def on_position_opened(self, symbol: str, position_data: Dict, source: str = "PHASE3"):
        """
        Called when a new position is opened.
        
        Args:
            symbol: Stock symbol
            position_data: Position details (entry_price, quantity, etc.)
            source: Which component opened it (PHASE3, BROKER_SYNC, etc.)
        """
        with self._positions_lock:
            position_data['state'] = PositionState.OPEN.value
            position_data['opened_at'] = datetime.now().isoformat()
            position_data['source'] = source
            self._central_positions[symbol] = position_data
            
            # Audit log
            self._position_event_log.append({
                'event': 'OPENED',
                'symbol': symbol,
                'time': datetime.now().isoformat(),
                'source': source,
                'entry_price': position_data.get('entry_price', 0)
            })
        
        logger.info(f"📡 PSM: Position OPENED - {symbol} (source: {source})")
        
        # Notify Phase 4 to start monitoring
        if self.phase4:
            try:
                if hasattr(self.phase4, 'add_position_from_orchestrator'):
                    self.phase4.add_position_from_orchestrator(symbol, position_data)
                elif symbol not in self.phase4.positions:
                    # Fallback: use existing method
                    self.phase4.positions[symbol] = position_data
                    self.phase4._init_kalman_for_position(symbol, position_data)
            except Exception as e:
                logger.error(f"📡 PSM: Failed to notify Phase 4: {e}")
        
        # Sync Phase 2 entries counter
        if self.phase2 and hasattr(self.phase2, 'sync_entries_taken'):
            self.phase2.sync_entries_taken(self.get_open_position_count())
    
    def on_position_closing(self, symbol: str, reason: str = "UNKNOWN"):
        """
        Called when exit is initiated (order placed, not yet filled).
        
        Args:
            symbol: Stock symbol
            reason: Why closing (TCAS_ALIM, STOP_LOSS, TARGET, etc.)
        """
        with self._positions_lock:
            if symbol in self._central_positions:
                self._central_positions[symbol]['state'] = PositionState.CLOSING.value
                self._central_positions[symbol]['closing_reason'] = reason
                self._central_positions[symbol]['closing_at'] = datetime.now().isoformat()
                
                self._position_event_log.append({
                    'event': 'CLOSING',
                    'symbol': symbol,
                    'time': datetime.now().isoformat(),
                    'reason': reason
                })
        
        logger.info(f"📡 PSM: Position CLOSING - {symbol} (reason: {reason})")
    
    def on_position_closed(self, symbol: str, reason: str = "UNKNOWN", exit_price: float = 0):
        """
        Called when position is fully closed (exit filled).
        
        Args:
            symbol: Stock symbol
            reason: Why closed
            exit_price: Exit price (for P&L calculation)
        """
        _bb_entry_price = 0
        _bb_quantity = 0
        _bb_pnl = 0
        _bb_source = None
        with self._positions_lock:
            if symbol in self._central_positions:
                pos = self._central_positions[symbol]
                entry_price = pos.get('entry_price', 0)
                quantity = pos.get('quantity', 0)
                direction = pos.get('direction', 'LONG')
                _bb_source = pos.get('source')
                # v5.3.6 FIX: Direction-aware P&L (was always exit-entry, wrong for SHORT)
                if exit_price > 0:
                    if direction in ('SHORT', 'SELL'):
                        pnl = (entry_price - exit_price) * quantity
                    else:  # LONG / BUY
                        pnl = (exit_price - entry_price) * quantity
                else:
                    pnl = 0
                _bb_entry_price = entry_price
                _bb_quantity = quantity
                _bb_pnl = pnl

                self._position_event_log.append({
                    'event': 'CLOSED',
                    'symbol': symbol,
                    'time': datetime.now().isoformat(),
                    'reason': reason,
                    'entry_price': entry_price,
                    'exit_price': exit_price,
                    'pnl': pnl
                })

                # Remove from active positions
                del self._central_positions[symbol]

        logger.info(f"📡 PSM: Position CLOSED - {symbol} (reason: {reason})")
        
        # v4.14.0 PERMANENT FIX: Track exit to prevent broker sync re-adoption loop
        self._exited_today[symbol] = {
            'exit_time': datetime.now(),
            'exit_date': datetime.now().date(),
            'reason': reason,
            'exit_price': exit_price
        }
        logger.info(f"📡 PSM: {symbol} added to today's exit list (broker sync will skip)")
        
        # Notify Phase 4 to STOP monitoring
        if self.phase4:
            try:
                if symbol in self.phase4.positions:
                    del self.phase4.positions[symbol]
                    logger.info(f"📡 PSM: Removed {symbol} from Phase 4 monitoring")
                if hasattr(self.phase4, 'kalman_filters') and symbol in self.phase4.kalman_filters:
                    del self.phase4.kalman_filters[symbol]
                if hasattr(self.phase4, 'failed_exit_attempts') and symbol in self.phase4.failed_exit_attempts:
                    del self.phase4.failed_exit_attempts[symbol]
            except Exception as e:
                logger.error(f"📡 PSM: Failed to clean Phase 4: {e}")
        
        # Sync Phase 2 entries counter
        if self.phase2 and hasattr(self.phase2, 'sync_entries_taken'):
            self.phase2.sync_entries_taken(self.get_open_position_count())
        
        # Telegram notification
        if self.telegram:
            self.telegram.send_message(
                f"📤 POSITION CLOSED\n\n"
                f"Stock: {symbol}\n"
                f"Reason: {reason}\n"
                f"Exit: ₹{exit_price:.2f}" if exit_price > 0 else f"📤 POSITION CLOSED\n\nStock: {symbol}\nReason: {reason}"
            )

        # v5.3.5: Log trade exit to blackbox
        try:
            if self.blackbox:
                self.blackbox.log_phase3_trade(
                    symbol=symbol,
                    action='EXIT',
                    details={
                        'exit_price': exit_price,
                        'entry_price': _bb_entry_price,
                        'quantity': _bb_quantity,
                        'pnl': _bb_pnl,
                        'reason': reason,
                        'source': _bb_source,
                    }
                )
        except Exception as e:
            logger.debug(f"Blackbox trade exit log failed: {e}")

    # ═══════════════════════════════════════════════════════════════════════════
    # ENHANCED POSITION API v4.9.0 - SINGLE SOURCE OF TRUTH
    # ═══════════════════════════════════════════════════════════════════════════
    # These methods are used by Phase 3 and Phase 4 for all position operations.
    # All position access should go through these thread-safe methods.
    # ═══════════════════════════════════════════════════════════════════════════
    
    def get_all_positions(self, include_closing: bool = False) -> Dict[str, Dict]:
        """
        Get all positions (thread-safe).
        
        This is the PRIMARY method for Phase 3/4 to access positions.
        Returns copies to prevent external mutation of state.
        
        Args:
            include_closing: If True, include CLOSING/EXIT_IN_PROGRESS positions
            
        Returns:
            Dict of symbol -> position data (copies)
        """
        with self._positions_lock:
            if include_closing:
                return {s: p.copy() for s, p in self._central_positions.items()}
            else:
                return {s: p.copy() for s, p in self._central_positions.items() 
                        if p.get('state') in [PositionState.OPEN.value, 'OPEN']}
    
    def get_position_by_symbol(self, symbol: str) -> Optional[Dict]:
        """
        Get single position by symbol (thread-safe).
        
        Args:
            symbol: Stock symbol
            
        Returns:
            Position dict (copy) or None
        """
        with self._positions_lock:
            pos = self._central_positions.get(symbol)
            return pos.copy() if pos else None
    
    def update_position_field(self, symbol: str, field: str, value) -> bool:
        """
        v5.4.0: Update a single field on a position (thread-safe).

        This is the canonical write path for Phase 4 mutations. Replaces
        direct dict assignments which are silently dropped due to the
        copy-on-read pattern of get_all_positions().

        Args:
            symbol: Stock symbol
            field: Field name to update
            value: New value

        Returns:
            True if updated, False if symbol not found or field is 'state'
            (use transition_position_state for state changes).
        """
        if field == 'state':
            logger.warning(f"⚠️ update_position_field: refusing to mutate 'state' for {symbol} — use transition_position_state")
            return False

        with self._positions_lock:
            if symbol not in self._central_positions:
                return False
            self._central_positions[symbol][field] = value
            return True

    def update_position_fields(self, symbol: str, fields: Dict) -> bool:
        """
        v5.4.0: Update multiple fields on a position atomically (thread-safe).

        Args:
            symbol: Stock symbol
            fields: Dict of field -> value to apply

        Returns:
            True if updated, False if symbol not found.
            'state' field is silently filtered out — use transition_position_state.
        """
        with self._positions_lock:
            if symbol not in self._central_positions:
                return False
            for field, value in fields.items():
                if field == 'state':
                    logger.warning(f"⚠️ update_position_fields: skipping 'state' for {symbol} — use transition_position_state")
                    continue
                self._central_positions[symbol][field] = value
            return True

    def get_positions_for_persistence(self) -> list:
        """
        v5.4.0: Get position snapshots for disk persistence.

        Returns deep-enough copies for JSON serialization. Used by
        Phase 4's _save_positions to avoid the property re-fetch bug.

        Returns:
            List of position dicts (copies, safe to serialize)
        """
        with self._positions_lock:
            return [p.copy() for p in self._central_positions.values()]

    def update_position(self, symbol: str, updates: Dict) -> bool:
        """
        Update position fields (thread-safe).

        Used by Phase 4 for updating current_price, health scores, etc.
        Does NOT allow changing 'state' - use transition_position_state for that.
        
        Args:
            symbol: Stock symbol
            updates: Dict of fields to update
            
        Returns:
            True if updated successfully
        """
        # Prevent state changes via this method
        if 'state' in updates:
            logger.warning(f"⚠️ update_position: Cannot change state via update. Use transition_position_state().")
            updates = {k: v for k, v in updates.items() if k != 'state'}
        
        with self._positions_lock:
            if symbol not in self._central_positions:
                return False
            
            self._central_positions[symbol].update(updates)
            self._central_positions[symbol]['last_updated'] = datetime.now().isoformat()
            return True
    
    def transition_position_state(self, symbol: str, new_state: str, reason: str = "") -> bool:
        """
        Transition position to new state (thread-safe, validates transitions).
        
        Valid transitions:
        - OPEN → CLOSING/EXIT_IN_PROGRESS (exit initiated)
        - CLOSING/EXIT_IN_PROGRESS → CLOSED (exit complete)
        - OPEN → CLOSED (emergency/direct close)
        - CLOSING/EXIT_IN_PROGRESS → OPEN (retry on failed exit)
        
        Args:
            symbol: Stock symbol
            new_state: Target state (CLOSING, EXIT_IN_PROGRESS, CLOSED)
            reason: Reason for transition
            
        Returns:
            True if transition successful
        """
        # v4.10.0 FIX: Added EXIT_IN_PROGRESS (Phase 4 uses this state name)
        valid_transitions = {
            'OPEN': ['CLOSING', 'EXIT_IN_PROGRESS', 'CLOSED'],
            'CLOSING': ['CLOSED', 'OPEN'],
            'EXIT_IN_PROGRESS': ['CLOSED', 'OPEN'],  # Phase 4's equivalent of CLOSING
            'CLOSED': []
        }
        
        with self._positions_lock:
            if symbol not in self._central_positions:
                return False
            
            current_state = self._central_positions[symbol].get('state', 'OPEN')
            
            if new_state not in valid_transitions.get(current_state, []):
                logger.warning(f"⚠️ Invalid transition: {symbol} {current_state} → {new_state}")
                return False
            
            # Apply transition
            self._central_positions[symbol]['state'] = new_state
            self._central_positions[symbol]['state_changed_at'] = datetime.now().isoformat()
            
            if reason:
                self._central_positions[symbol]['state_reason'] = reason
            
            # Log event
            self._position_event_log.append({
                'event': f'STATE_{new_state}',
                'symbol': symbol,
                'time': datetime.now().isoformat(),
                'from_state': current_state,
                'to_state': new_state,
                'reason': reason
            })
            
            logger.info(f"📡 PSM: {symbol} state {current_state} → {new_state} ({reason})")
            return True
    
    def is_position_closing(self, symbol: str) -> bool:
        """
        Check if position is in CLOSING state (exit in progress).
        
        Args:
            symbol: Stock symbol
            
        Returns:
            True if position is CLOSING
        """
        with self._positions_lock:
            pos = self._central_positions.get(symbol)
            if not pos:
                return False
            return pos.get('state') in [PositionState.CLOSING.value, 'CLOSING', 'EXIT_IN_PROGRESS']
    
    def add_position(self, symbol: str, position_data: Dict, source: str = "PHASE3") -> bool:
        """
        Add new position (thread-safe, validates no duplicate).
        
        Args:
            symbol: Stock symbol
            position_data: Position details
            source: Source of position (PHASE3, BROKER_SYNC, etc.)
            
        Returns:
            True if added successfully
        """
        with self._positions_lock:
            if symbol in self._central_positions:
                current_state = self._central_positions[symbol].get('state', 'UNKNOWN')
                logger.warning(f"⚠️ add_position: {symbol} already exists (state={current_state})")
                return False
        
        # Use existing callback which handles all the setup
        self.on_position_opened(symbol, position_data, source)
        return True
    
    def remove_position(self, symbol: str, reason: str = "UNKNOWN", exit_price: float = 0) -> bool:
        """
        Remove position (thread-safe).
        
        Args:
            symbol: Stock symbol
            reason: Exit reason
            exit_price: Exit price for P&L
            
        Returns:
            True if removed successfully
        """
        with self._positions_lock:
            if symbol not in self._central_positions:
                logger.warning(f"⚠️ remove_position: {symbol} not found")
                return False
        
        # Use existing callback which handles cleanup
        self.on_position_closed(symbol, reason, exit_price)
        return True
    
    def position_exists(self, symbol: str) -> bool:
        """
        Check if ANY position exists for symbol (any state).
        
        Args:
            symbol: Stock symbol
            
        Returns:
            True if position exists in any state
        """
        with self._positions_lock:
            return symbol in self._central_positions
    
    def get_position_for_update(self, symbol: str) -> Optional[Dict]:
        """
        Get position reference for in-place updates (USE WITH CAUTION).
        
        This returns the ACTUAL dict, not a copy. Only use when you need
        to update nested structures (like phase4_tracking).
        
        IMPORTANT: Caller should use orchestrator's lock when making updates.
        
        Args:
            symbol: Stock symbol
            
        Returns:
            Position dict (actual reference, not copy) or None
        """
        with self._positions_lock:
            return self._central_positions.get(symbol)
    
    def bulk_update_prices(self, price_updates: Dict[str, float]) -> int:
        """
        Update current prices for multiple positions at once.
        
        Args:
            price_updates: Dict of symbol -> current_price
            
        Returns:
            Number of positions updated
        """
        updated = 0
        with self._positions_lock:
            for symbol, price in price_updates.items():
                if symbol in self._central_positions:
                    self._central_positions[symbol]['current_price'] = price
                    self._central_positions[symbol]['price_updated_at'] = datetime.now().isoformat()
                    updated += 1
        return updated
    
    def broker_sync_positions(self):
        """
        Sync central state with broker positions.
        Called every 30 seconds to catch GTT exits, manual trades, etc.
        
        v4.7.2 FIX: BROKER POSITION ADOPTION!
        - Positions at broker but not in state → ADOPT them (not just warn)
        - This fixes the "unprotected position" emergency exits on restart
        - Capital Manager updated to match broker reality

        v4.5.4 FIX: Now releases capital for externally closed positions!
        """
        # v5.0.0 SSOT: Use handler if available
        if hasattr(self, '_broker_sync_handler') and self._broker_sync_handler:
            self._broker_sync_handler.sync()
            
            # v5.3.2 FIX: SSOT handler cleans capital_manager state but may NOT clean
            # _central_positions for positions adopted via PHASE4_MANUAL_HOLDINGS path
            # (which bypasses capital_manager). Run a safety cleanup here.
            try:
                now = datetime.now()
                broker_positions = {}
                
                # Quick broker state fetch (use broker_sync cache if available)
                if hasattr(self, 'broker_sync') and self.broker_sync:
                    all_pos = self.broker_sync.get_all_positions(use_cache=True, save_snapshot=False)
                    broker_positions = set(all_pos.keys()) if all_pos else set()
                else:
                    # Direct fetch
                    positions_response = self.kite.positions()
                    for pos in positions_response.get('net', []):
                        if pos.get('quantity', 0) != 0:
                            broker_positions.add(pos['tradingsymbol'])
                    holdings = self.kite.holdings()
                    for h in holdings:
                        if h.get('quantity', 0) > 0:
                            broker_positions.add(h['tradingsymbol'])
                
                with self._positions_lock:
                    our_positions = set(self._central_positions.keys())
                    stale = our_positions - broker_positions
                    
                    for symbol in stale:
                        state = self._central_positions[symbol].get('state', '')
                        if state not in ['CLOSING']:
                            logger.warning(f"📡 SSOT CLEANUP: {symbol} in _central_positions but NOT at broker — removing")
                            
                            # Release capital
                            if self.capital_manager:
                                try:
                                    pos_data = self._central_positions[symbol]
                                    entry_value = pos_data.get('entry_value', 0)
                                    if entry_value > 0:
                                        self.capital_manager.release(symbol, entry_value, pnl=0)
                                except Exception as e:
                                    logger.error(f"📡 SSOT CLEANUP: Capital release failed for {symbol}: {e}")
                            
                            del self._central_positions[symbol]
                            
                            # Track as exited today
                            self._exited_today[symbol] = {
                                'exit_time': now,
                                'exit_date': now.date(),
                                'reason': 'SSOT_CLEANUP_EXTERNAL_CLOSE',
                                'exit_price': 0
                            }
                            
                            # Clean Phase 4
                            if self.phase4:
                                if symbol in self.phase4.positions:
                                    del self.phase4.positions[symbol]
                                if hasattr(self.phase4, 'kalman_filters') and symbol in self.phase4.kalman_filters:
                                    del self.phase4.kalman_filters[symbol]
                                if hasattr(self.phase4, '_closed_externally_today'):
                                    self.phase4._closed_externally_today.add(symbol)
                                logger.info(f"📡 SSOT CLEANUP: Cleaned {symbol} from Phase 4")
                            
                            # Clean Phase 3
                            if self.phase3 and symbol in getattr(self.phase3, 'positions', {}):
                                del self.phase3.positions[symbol]
                            
                            if self.telegram:
                                self.telegram.send_message(
                                    f"📡 POSITION CLOSED (External)\n\n"
                                    f"{symbol} removed from monitoring\n"
                                    f"(GTT executed or manual exit)"
                                )
            except Exception as e:
                logger.error(f"📡 SSOT CLEANUP failed: {e}")
            
            return
        
        now = datetime.now()
        if (now - self._last_broker_sync).total_seconds() < self._broker_sync_interval:
            return  # Too soon
        
        self._last_broker_sync = now
        
        try:
            # Get actual positions from broker with full details
            broker_positions = {}  # symbol -> position_data
            
            # MIS/NRML positions
            positions_response = self.kite.positions()
            for pos in positions_response.get('net', []):
                qty = pos.get('quantity', 0)
                if qty != 0:
                    symbol = pos['tradingsymbol']
                    broker_positions[symbol] = {
                        'quantity': abs(qty),
                        'avg_price': pos.get('average_price', 0),
                        'product': pos.get('product', 'MIS'),
                        'pnl': pos.get('pnl', 0),
                        'last_price': pos.get('last_price', 0),
                        'source': 'positions'
                    }
            
            # CNC holdings
            holdings = self.kite.holdings()
            for holding in holdings:
                qty = holding.get('quantity', 0)
                if qty > 0:
                    symbol = holding['tradingsymbol']
                    broker_positions[symbol] = {
                        'quantity': qty,
                        'avg_price': holding.get('average_price', 0),
                        'product': 'CNC',
                        'pnl': holding.get('pnl', 0),
                        'last_price': holding.get('last_price', 0),
                        'source': 'holdings'
                    }
            
            with self._positions_lock:
                our_positions = set(self._central_positions.keys())
                broker_symbols = set(broker_positions.keys())
                
                # ═══════════════════════════════════════════════════════════════════
                # v4.7.2 FIX: ADOPT positions at broker but NOT in our state
                # v4.14.0 PERMANENT FIX: Exit tracking prevents re-adoption loops
                # ═══════════════════════════════════════════════════════════════════
                missing = broker_symbols - our_positions
                for symbol in missing:
                    broker_data = broker_positions[symbol]
                    
                    # v4.14.0: Clean stale entries (from previous trading days)
                    if symbol in self._exited_today:
                        exit_date = self._exited_today[symbol].get('exit_date')
                        if exit_date and exit_date != datetime.now().date():
                            del self._exited_today[symbol]  # Stale, allow fresh adoption
                    
                    # v4.14.0 PERMANENT FIX: Skip if we exited this symbol today
                    # CNC holdings persist at broker after sell (T+1 settlement).
                    # Without this check: exit → broker sync re-adopts → exit → loop
                    if symbol in self._exited_today:
                        exit_info = self._exited_today[symbol]
                        logger.info(
                            f"📡 BROKER SYNC: {symbol} at broker but EXITED TODAY "
                            f"({exit_info['reason']} @ {exit_info['exit_time'].strftime('%H:%M:%S')}) "
                            f"- skipping adoption"
                        )
                        continue
                    
                    # Secondary defense: Phase 4 loop detection (60-min cooldown)
                    if self.phase4 and hasattr(self.phase4, 'is_reentry_allowed'):
                        allowed, reason = self.phase4.is_reentry_allowed(symbol)
                        if not allowed:
                            logger.info(f"📡 BROKER SYNC: {symbol} re-entry blocked by Phase 4: {reason}")
                            continue
                    
                    logger.warning(f"📡 BROKER SYNC: {symbol} at broker but NOT in our state - ADOPTING!")
                    
                    # Adopt into central positions
                    entry_value = broker_data['avg_price'] * broker_data['quantity']
                    adopted_position = {
                        'symbol': symbol,
                        'quantity': broker_data['quantity'],
                        'entry_price': broker_data['avg_price'],
                        'entry_value': entry_value,
                        'entry_time': now.isoformat(),
                        'product': broker_data['product'],
                        'state': PositionState.OPEN.value,
                        'source': 'BROKER_ADOPTION',
                        'adopted_at': now.isoformat(),
                        'gtt_protected': False,  # We don't know - assume unprotected
                    }
                    
                    self._central_positions[symbol] = adopted_position
                    logger.info(f"📡 BROKER SYNC: Adopted {symbol} - {broker_data['quantity']} @ ₹{broker_data['avg_price']:.2f}")
                    
                    # Adopt into Phase 3 if available
                    if self.phase3:
                        try:
                            self.phase3.adopt_position_from_broker(
                                symbol=symbol,
                                quantity=broker_data['quantity'],
                                avg_price=broker_data['avg_price'],
                                product=broker_data['product'],
                                last_price=broker_data['last_price']
                            )
                            logger.info(f"📡 BROKER SYNC: {symbol} added to Phase 3 monitoring")
                        except Exception as e:
                            logger.error(f"📡 BROKER SYNC: Failed to add {symbol} to Phase 3: {e}")
                    
                    # Adopt capital deployment - BUT check if already deployed!
                    if self.capital_manager:
                        try:
                            # v4.7.2 FIX: Check if capital already deployed for this symbol
                            already_deployed = self.capital_manager.get_stock_exposure(symbol)
                            if already_deployed > 0:
                                logger.info(f"📡 BROKER SYNC: Capital ₹{already_deployed:,.0f} already deployed for {symbol} - skipping")
                            else:
                                self.capital_manager.adopt_deployed_capital(
                                    symbol=symbol,
                                    amount=entry_value,
                                    quantity=broker_data['quantity'],
                                    avg_price=broker_data['avg_price']
                                )
                                logger.info(f"📡 BROKER SYNC: Capital ₹{entry_value:,.0f} adopted for {symbol}")
                        except Exception as e:
                            logger.error(f"📡 BROKER SYNC: Capital adoption failed for {symbol}: {e}")
                    
                    # Notify
                    if self.telegram:
                        self.telegram.send_message(
                            f"📡 POSITION ADOPTED\n\n"
                            f"Symbol: {symbol}\n"
                            f"Qty: {broker_data['quantity']}\n"
                            f"Avg Price: ₹{broker_data['avg_price']:.2f}\n"
                            f"Value: ₹{entry_value:,.0f}\n\n"
                            f"Source: {broker_data['source']}\n"
                            f"Now monitoring."
                        )
                    
                    # Log event
                    self._position_event_log.append({
                        'event': 'BROKER_ADOPTION',
                        'symbol': symbol,
                        'time': now.isoformat(),
                        'quantity': broker_data['quantity'],
                        'avg_price': broker_data['avg_price'],
                        'entry_value': entry_value
                    })
                
                # ═══════════════════════════════════════════════════════════════════
                # Positions in our state but NOT at broker (sold without us knowing!)
                # ═══════════════════════════════════════════════════════════════════
                stale = our_positions - broker_symbols
                for symbol in stale:
                    state = self._central_positions[symbol].get('state', '')
                    if state not in [PositionState.CLOSING.value, 'CLOSING']:
                        logger.warning(f"📡 BROKER SYNC: {symbol} in our state but NOT at broker!")
                        logger.info(f"📡 BROKER SYNC: Auto-closing {symbol} (GTT or manual exit detected)")
                        
                        # ═══════════════════════════════════════════════════════════
                        # v4.5.4 FIX: Release capital for externally closed positions
                        # ═══════════════════════════════════════════════════════════
                        if self.capital_manager:
                            try:
                                pos_data = self._central_positions[symbol]
                                entry_value = pos_data.get('entry_value', 0)
                                if entry_value > 0:
                                    # Release capital with pnl=0 (we don't know actual P&L)
                                    # Broker sync will correct total_capital from margins anyway
                                    self.capital_manager.release(symbol, entry_value, pnl=0)
                                    logger.info(f"📡 BROKER SYNC: Released ₹{entry_value:,.0f} capital for {symbol}")
                            except Exception as e:
                                logger.error(f"📡 BROKER SYNC: Capital release failed for {symbol}: {e}")
                        
                        # Auto-close this stale position
                        self._position_event_log.append({
                            'event': 'BROKER_SYNC_CLOSED',
                            'symbol': symbol,
                            'time': now.isoformat(),
                            'reason': 'Position not found at broker'
                        })
                        del self._central_positions[symbol]
                        
                        # Clean Phase 3
                        if self.phase3 and symbol in self.phase3.positions:
                            del self.phase3.positions[symbol]
                            logger.info(f"📡 BROKER SYNC: Cleaned {symbol} from Phase 3")
                        
                        # Clean Phase 4
                        if self.phase4 and symbol in self.phase4.positions:
                            del self.phase4.positions[symbol]
                            if hasattr(self.phase4, 'kalman_filters') and symbol in self.phase4.kalman_filters:
                                del self.phase4.kalman_filters[symbol]
                            logger.info(f"📡 BROKER SYNC: Cleaned {symbol} from Phase 4")
                        
                        # Notify
                        if self.telegram:
                            self.telegram.send_message(
                                f"📡 BROKER SYNC\n\n"
                                f"Position {symbol} was closed externally\n"
                                f"(GTT executed or manual exit)\n\n"
                                f"Removed from monitoring."
                            )
            
            logger.debug(f"📡 Broker sync complete: {len(broker_positions)} positions at broker")
            
        except Exception as e:
            logger.error(f"📡 Broker sync failed: {e}")
    
    def get_position_event_log(self, limit: int = 50) -> List[Dict]:
        """Get recent position events for audit"""
        return self._position_event_log[-limit:]
    
    def _execute_phase1_interrupt(self, label: str, description: str):
        """Execute Phase 1 scan (Interrupt Service Routine)"""
        logger.info("")
        logger.info("=" * 80)
        logger.info(f"INTERRUPT TRIGGERED: {description}")
        logger.info("=" * 80)
        logger.info("")
        
        self.interrupt_running = True
        
        try:
            if self.telegram:
                self.telegram.send_message(f"🔍 SCANNING: {description}")
            
            # Phase 1 returns dict: {'selected_stocks': [...], 'filter1_count': 5, ...}
            result = self.phase1.run_selection()
            
            # Extract the actual stock list from the result dictionary
            selected_stocks = result.get('selected_stocks', []) if isinstance(result, dict) else result
            
            # Filter PH1 output by sector_avoid directive from Phase 9
            if selected_stocks and self.phase9 and self.phase9._morning_briefing_done:
                _avoid = [s.upper() for s in getattr(self.phase9, 'todays_sector_avoid', [])]
                if _avoid:
                    _sector_map = getattr(self.phase1, '_sector_map', {}) if self.phase1 else {}
                    _before = len(selected_stocks)
                    selected_stocks = [
                        s for s in selected_stocks
                        if str(_sector_map.get(
                            s if isinstance(s, str) else s.get('symbol', ''), ''
                        )).upper() not in _avoid
                    ]
                    if len(selected_stocks) < _before:
                        logger.info(f"🧠 PH9 sector filter: removed {_before - len(selected_stocks)} "
                                    f"stocks from avoided sectors {_avoid}")

            if selected_stocks:
                logger.info(f"[OK] Phase 1 selected {len(selected_stocks)} stocks")

                # v5.3.5: Log Phase 1 scan to blackbox
                try:
                    if self.blackbox:
                        self.blackbox.log_phase1_scan(
                            scan_time=datetime.now().strftime('%H:%M:%S'),
                            stocks_found=selected_stocks,  # pass full dicts for DB fields
                            scan_label=description if description else 'Phase1_Scan'
                        )
                except Exception as e:
                    logger.debug(f"Blackbox phase1 log failed: {e}")

                # Load stocks from ACTIVE.json (saved by Phase 1)
                stocks = self.phase2.load_active_stocks()
                
                # Initialize monitors for the loaded stocks
                if stocks and len(stocks) > 0:
                    self.phase2.initialize_monitors(stocks)
                    logger.info(f"[OK] Initialized {len(stocks)} stock monitors")
                else:
                    logger.warning("[!] No stocks to monitor after Phase 1 scan")
                
                self.active_stock_count = len(selected_stocks)
                self.hunt_mode_active = False
                
                if self.telegram:
                    msg = f"✅ SCAN COMPLETE\n\nSelected {len(selected_stocks)} stocks:\n"
                    for i, stock in enumerate(selected_stocks[:10], 1):
                        symbol = stock if isinstance(stock, str) else stock.get('symbol', 'Unknown')
                        msg += f"{i}. {symbol}\n"

                    # Add scan statistics if available
                    if isinstance(result, dict):
                        msg += f"\n📊 Scan Stats:\n"
                        msg += f"Total scanned: {result.get('total_scanned', 0)}\n"
                        msg += f"Filter 1 passed: {result.get('filter1_count', 0)}\n"
                        msg += f"Filter 2 passed: {result.get('filter2_count', 0)}\n"

                    # Show active blocks so user knows if trading is actually possible
                    _blocks = []
                    if self._ph4_brain_defensive: _blocks.append("PH4=DEFENSIVE")
                    if self._ph5_brain_skip:      _blocks.append("PH5=SKIP")
                    if self._ph5a_brain_pause:    _blocks.append("PH5A=PAUSE")
                    if self._ph6_brain_hold:      _blocks.append("PH6=HOLD")
                    _nifty_blocked = self.phase2 and getattr(self.phase2, '_nifty_filter_blocked', False)
                    if _nifty_blocked:            _blocks.append("NIFTY FILTER")
                    if _blocks:
                        msg += f"\n⛔ Active blocks: {' | '.join(_blocks)}\n"
                        msg += "Stocks monitored — entries gated until blocks clear."
                    else:
                        msg += "\n🟢 No active blocks — entries enabled."

                    self.telegram.send_message(msg)
            else:
                logger.info("[i]  No stocks selected")
                self.hunt_mode_active = True
                
                if self.telegram:
                    self.telegram.send_message("⚠️ No stocks selected in scan")
            
            self.last_scan_time = datetime.now()
            self.scans_completed[label] = True
            
            # ═══════════════════════════════════════════════════════════════════
            # START PHASE 4 WITH MARKET CONTEXT (v4.3 NEW!)
            # ═══════════════════════════════════════════════════════════════════
            
            if self.phase4 and not getattr(self, '_phase4_started', False):
                try:
                    import json as json_module
                    market_context_file = getattr(self.config, 'MARKET_CONTEXT_FILE', 
                                                  'data/phase1_outputs/market_context.json')
                    market_context = {}
                    
                    if os.path.exists(market_context_file):
                        with open(market_context_file, 'r') as f:
                            market_context = json_module.load(f)
                    
                    # Start Phase 4 with market context
                    self.phase4.startup_with_market_context(market_context)
                    self._phase4_started = True
                    logger.info("[OK] 🛫 Phase 4 started with market context")
                    
                    # Also share as live sentiment (Phase 1 is the first sentiment)
                    if market_context.get('ai_market_opinion') or market_context.get('chatgpt_market_opinion'):
                        initial_sentiment = {
                            'timestamp': datetime.now().isoformat(),
                            'source': 'phase1_startup',
                            'market_outlook': market_context.get('chatgpt_market_opinion', {}).get('outlook', 'NEUTRAL'),
                            'volatility': market_context.get('chatgpt_market_opinion', {}).get('volatility', 'NORMAL'),
                            'risk_level': market_context.get('chatgpt_market_opinion', {}).get('risk_level', 'MEDIUM'),
                            'notes': market_context.get('ai_market_opinion', '')[:200]
                        }
                        self.phase4.update_market_sentiment(initial_sentiment)
                        logger.info("[OK] 📡 Initial sentiment shared with Phase 4")
                    
                    # v5.6: Share market regime with Phase 3 for entry sizing
                    if (self.phase3 and hasattr(self.phase3, 'update_market_regime')
                            and getattr(self.config, 'MARKET_REGIME_ENABLED', True)):
                        regime_outlook = initial_sentiment.get('market_outlook', 'NEUTRAL') if market_context.get('ai_market_opinion') or market_context.get('chatgpt_market_opinion') else 'NEUTRAL'
                        self.phase3.update_market_regime(regime_outlook)
                        logger.info(f"[OK] 📡 Market regime '{regime_outlook}' shared with Phase 3")

                    # v5.6: Rich market outlook Telegram message (Fix A)
                    if self.telegram:
                        gpt_opinion = market_context.get('chatgpt_market_opinion', {})
                        regime_outlook = gpt_opinion.get('outlook', 'NEUTRAL')
                        regime_vol = gpt_opinion.get('volatility', 'NORMAL')
                        regime_risk = gpt_opinion.get('risk_level', 'MEDIUM')
                        regime_notes = market_context.get('ai_market_opinion', '')[:150]
                        regime_mult = {'BULLISH': '1.0x', 'NEUTRAL': '0.85x', 'MIXED': '0.6x',
                                       'BEARISH': '0.4x', 'DEFENSIVE': 'BLOCKED'}.get(regime_outlook.upper(), '0.85x')
                        self.telegram.send_message(
                            f"📊 MARKET OUTLOOK\n\n"
                            f"🤖 ChatGPT: {regime_outlook}\n"
                            f"⚡ Volatility: {regime_vol}\n"
                            f"🛡️ Risk: {regime_risk}\n"
                            f"📝 {regime_notes}\n\n"
                            f"🛫 Phase 4: ACTIVE\n"
                            f"📊 Entry Mode: {regime_mult} sizing"
                        )
                        
                except Exception as e:
                    logger.error(f"[X] Phase 4 startup failed: {e}")

            # v5.9.0: PH5A ChatGPT gate REMOVED — PH5A now auto-fires independently
            # after Phase 5 exclusive window ends. See main loop PH5A block.

        except Exception as e:
            logger.error(f"[X] Phase 1 scan failed: {e}")
            logger.error(traceback.format_exc())
        finally:
            self.interrupt_running = False
        
        logger.info("")
    
    
    def _run_phase2_cycle(self):
        """
        Run Phase 2 monitoring cycle with v3.1 features.
        
        v4.6.0 ENHANCED:
        - Adaptive Telegram: GPT-driven send/skip decisions
        - Phase 2 cycle counter for tracking
        
        v3.1.1 ENHANCED:
        - Better diagnostic visibility
        - Filter pass/fail counts
        - Signal score breakdown
        
        v3.1 NEW:
        - Records trades for starvation prevention
        - Registers positions for adaptive exit tracking
        - Logs starvation status
        """
        self.phase2_cycle_count += 1

        try:
            monitor_count = len(self.phase2.monitors) if hasattr(self.phase2, 'monitors') else 0

            # v5.8.0: Suppress noisy headers when idle — log every 10th cycle only
            if monitor_count == 0:
                if self.phase2_cycle_count % 10 == 1:
                    logger.info(f"[PH2] Cycle #{self.phase2_cycle_count} | 0 monitors | idle")
                # Lightweight status push every 6th cycle (~30 min) so user isn't blind when idle
                if self.phase2_cycle_count % 6 == 1:
                    self._send_cycle_status(has_monitors=False)
                return

            logger.info("─" * 80)
            logger.info(f"[SCAN] PHASE 2 MONITORING CYCLE #{self.phase2_cycle_count} (v4.6.0)")
            logger.info("─" * 80)
            logger.info(f"📋 Active Monitors: {monitor_count} stocks")
            
            if monitor_count > 0 and hasattr(self.phase2, 'monitors'):
                logger.info("")
                logger.info("Stock Status Summary:")
                rsi_trackers = getattr(self.phase2, 'rsi_trackers', {})
                for monitor in self.phase2.monitors[:10]:  # Show first 10
                    rsi = getattr(monitor, 'current_rsi', None)
                    state = getattr(monitor, 'rsi_state', 'UNKNOWN')
                    rsi_str = f"RSI {rsi:.1f}" if rsi else "RSI ?"
                    # v5.3.3: Show RSIZoneTracker state if available
                    tracker = rsi_trackers.get(monitor.symbol)
                    if tracker:
                        zone_low_str = f"{tracker.zone_low_rsi:.1f}" if tracker.zone_low_rsi < 999 else "—"
                        min_readings = getattr(self.config, 'PH2_MIN_READINGS_BEFORE_TRIGGER', 6)
                        tracker_str = (f"ZT: {tracker.state} | K-RSI {tracker.kalman_rsi:.1f} | "
                                      f"Vel {tracker.kalman_velocity:+.2f} | "
                                      f"ZoneLow {zone_low_str} | {tracker.readings_since_zone}/{min_readings}")
                        logger.info(f"   {monitor.symbol:15} | {state:12} | {rsi_str} | {tracker_str}")
                    else:
                        logger.info(f"   {monitor.symbol:15} | {state:12} | {rsi_str} | ZT: not yet created")
                if monitor_count > 10:
                    logger.info(f"   ... and {monitor_count - 10} more")
                logger.info("")
            
            # 0. v5.3.6: Check monitoring timeouts (2-hour drop rule)
            if hasattr(self.phase2, 'check_monitoring_timeouts'):
                dropped_symbols = self.phase2.check_monitoring_timeouts()
                if dropped_symbols:
                    for sym in dropped_symbols:
                        # Log to blackbox
                        if self.blackbox:
                            self.blackbox.log_event('phase2', 'monitoring_timeout', {
                                'symbol': sym,
                                'reason': 'No signal within 2-hour window'
                            })
                        # Notify via Telegram
                        if self.telegram:
                            self.telegram.send_message(
                                f"⏰ {sym} dropped from monitoring — no signal after 2hrs\n"
                                f"   Phase 1 adaptive scan will pick new candidates"
                            )
                    logger.info(f"⏰ Dropped {len(dropped_symbols)} stock(s) from monitoring: {dropped_symbols}")

            # 1. Refresh live Nifty/VIX cache (60s TTL) so entry gate always has current data
            self._get_live_market_data()

            # 2. Update all stock monitors
            logger.info("Updating stock monitors...")
            self.phase2.update_all_monitors()
            logger.info("[OK] Monitors updated")
            # Lightweight status push every 2nd cycle (~10 min) — zero Claude cost
            if self.phase2_cycle_count % 2 == 0:
                self._send_cycle_status(has_monitors=True)

            # 1b. Candlestick Pattern Detection (v1.0.0)
            if self.pattern_detector and getattr(self.config, 'CANDLESTICK_PATTERN_ENABLED', False):
                self._run_candlestick_pattern_detection()

            # 1c. ORB Advisory — feed / lock / update (v1.0.0)
            if self.orb_advisory and getattr(self.config, 'ORB_ADVISORY_ENABLED', False):
                self._run_orb_advisory_update()

            # 2. Log starvation status (v3.1)
            if self.starvation_prevention:
                status = self.starvation_prevention.get_status()
                logger.info(f"📊 Trade Status: {status['trades_today']} trades today, "
                           f"{status['signals_seen']} signals seen")
                # Only warn if entries are NOT intentionally blocked by brain directive
                _brain_blocked = (self._ph4_brain_defensive or
                                  (self.phase9 and getattr(self.phase9, 'todays_regime', 'NORMAL') in ('HALT', 'DEFENSIVE')))
                if status['starvation_risk'] and not _brain_blocked:
                    logger.warning(f"🚨 STARVATION RISK: 0/{status['min_required']} trades!")
            
            # 3. Check for entry signals
            # Entry window gate: Phase 9 may delay entries on volatile opens
            _entry_window_blocked = False
            if self.phase9 and self.phase9._morning_briefing_done:
                _ew = getattr(self.phase9, 'todays_entry_window', '09:15')
                try:
                    _ew_h, _ew_m = int(_ew.split(':')[0]), int(_ew.split(':')[1])
                    if now.time() < dt_time(_ew_h, _ew_m):
                        _entry_window_blocked = True
                        logger.info(f"⏳ Entry window not open yet (Ph9 says wait until {_ew})")
                except Exception:
                    pass
            # ═══════════════════════════════════════════════════════════════
            # 🧠 INTELLIGENT ENGINE INTEGRATION
            # ═══════════════════════════════════════════════════════════════
            _ph2_skip = getattr(self, '_ph2_brain_skip', False)
            if not _entry_window_blocked and not _ph2_skip and self.intelligent_wrapper:
                logger.info("🧠 Processing through Intelligent Engine v1.1...")
                
                intelligent_signals = self.intelligent_wrapper.get_intelligent_signals()
                tradeable_signals = self.intelligent_wrapper.intelligent_engine.get_tradeable_signals(
                    intelligent_signals
                )
                
                # ═══════════════════════════════════════════════════════════
                # v5.1.0 FIX: Collect raw signals for reservation cleanup
                # Phase 2 reserves capital for each signal it generates.
                # We must unreserve ALL signals at the end of this cycle —
                # deploy() will re-account for any that actually execute.
                # ═══════════════════════════════════════════════════════════
                raw_signals = self.intelligent_wrapper.last_raw_signals or []
                
                # ═══════════════════════════════════════════════════════════
                # DIAGNOSTIC: Signal Score Breakdown
                # ═══════════════════════════════════════════════════════════
                
                if intelligent_signals:
                    logger.info(f"[OK] {len(intelligent_signals)} signal(s) analyzed")
                    logger.info(f"[OK] {len(tradeable_signals)} signal(s) tradeable")
                    
                    logger.info("")
                    logger.info("Signal Score Breakdown:")
                    logger.info("─" * 70)
                    logger.info(f"{'Symbol':<12} {'Score':>6} {'Tech':>5} {'Mom':>5} {'Vol':>5} {'Sup':>5} {'NIFTY':>6} {'Status':<10}")
                    logger.info("─" * 70)
                    
                    for sig in intelligent_signals:
                        status = "✅ TRADE" if sig in tradeable_signals else "⏭️ SKIP"
                        logger.info(
                            f"{sig.symbol:<12} "
                            f"{sig.total_score:>6.0f} "
                            f"{sig.technical_score:>5.0f} "
                            f"{sig.momentum_score:>5.0f} "
                            f"{sig.volume_score:>5.0f} "
                            f"{sig.support_score:>5.0f} "
                            f"{sig.nifty_correlation_score:>6.0f} "
                            f"{status:<10}"
                        )
                        
                        if sig not in tradeable_signals:
                            threshold = getattr(self.config, 'INTELLIGENT_SCORE_SKIP', 45)
                            if self.starvation_prevention:
                                threshold, _ = self.starvation_prevention.get_adjusted_threshold(threshold)
                            logger.info(f"   └─ Reason: Score {sig.total_score:.0f} < {threshold} threshold")
                    
                    logger.info("─" * 70)
                    logger.info("")
                    
                    # Log market regime
                    regime = self.intelligent_wrapper.get_market_regime()
                    logger.info(f"📊 Market Regime: {regime.value}")
                    
                    # ═══════════════════════════════════════════════════════
                    # v5.1.0 FIX: Build set of symbols that will be executed
                    # so we know which reservations to keep vs release
                    # ═══════════════════════════════════════════════════════
                    executed_symbols = set()
                    
                    # v1.4.0: Brain directive gates — DEFENSIVE blocks all new entries
                    _brain_regime = getattr(self.phase9, 'todays_regime', 'NORMAL') if self.phase9 else 'NORMAL'
                    if _brain_regime in ('HALT', 'DEFENSIVE') or self._ph4_brain_defensive:
                        if _brain_regime == 'HALT' or self._ph4_brain_defensive:
                            logger.info(f"🧠 PH9 {_brain_regime}/DEFENSIVE — all new entries blocked")
                            return  # Skip entire cycle

                    _cautious_size_mult = 0.5 if _brain_regime == 'CAUTIOUS' else 1.0

                    # v1.3.0: Phase 9 entry window gate — skip signals before Claude's
                    # recommended start time (e.g. 09:45 on volatile open days).
                    _entry_window_ok = True
                    if self.phase9 and self.phase9._morning_briefing_done:
                        _ew = getattr(self.phase9, 'todays_entry_window', '09:15')
                        try:
                            _ew_h, _ew_m = int(_ew.split(':')[0]), int(_ew.split(':')[1])
                            _ew_time = dt_time(_ew_h, _ew_m)
                            if now.time() < _ew_time:
                                logger.info(f"🧠 PH9 Entry Window: {now.strftime('%H:%M')} < {_ew} — "
                                            f"holding PH2 signals until window opens")
                                _entry_window_ok = False
                        except Exception:
                            pass  # Malformed time string — don't gate

                    # Execute tradeable signals
                    if self.phase3 and tradeable_signals and _entry_window_ok:
                        logger.info("🚀 Executing intelligent signals...")

                        for int_signal in tradeable_signals:
                            try:
                                # ═══════════════════════════════════════════════════════
                                # v5.2.1: Daily duplicate prevention
                                # ═══════════════════════════════════════════════════════
                                if self.phase2 and int_signal.symbol in self.phase2.traded_today:
                                    logger.info(f"🚫 {int_signal.symbol}: Already traded today - skipping")
                                    continue
                                
                                # ═══════════════════════════════════════════════════════
                                # v4.9.0: LOOP DETECTION CHECK
                                # Prevent re-entry to stocks that recently stopped out
                                # ═══════════════════════════════════════════════════════
                                if self.phase4 and hasattr(self.phase4, 'is_reentry_allowed'):
                                    allowed, reason = self.phase4.is_reentry_allowed(int_signal.symbol)
                                    if not allowed:
                                        logger.warning(f"⏳ {int_signal.symbol}: Re-entry BLOCKED - {reason}")
                                        continue  # Skip this signal
                                
                                # Convert to Phase 3 format
                                signal = self.intelligent_wrapper.convert_to_phase3_signal(int_signal)

                                # v1.4.0: Stamp cross-phase portfolio context onto signal
                                signal['_portfolio_context'] = self._build_portfolio_context(int_signal.symbol)

                                # v1.4.0: CAUTIOUS mode halves position size
                                if _cautious_size_mult != 1.0:
                                    signal['quantity'] = max(1, int(signal.get('quantity', 1) * _cautious_size_mult))
                                    logger.info(f"🧠 PH9 CAUTIOUS: size reduced to {_cautious_size_mult:.0%}")

                                logger.info("")
                                logger.info(f"📈 {int_signal.symbol}:")
                                logger.info(f"   Score: {int_signal.total_score:.0f}/100 ({int_signal.signal_strength.value})")
                                logger.info(f"   Position: {int_signal.recommended_position_pct*100:.0f}% (₹{int_signal.recommended_capital:,.0f})")
                                logger.info(f"   Predict: {int_signal.predicted_direction} ({int_signal.prediction_confidence:.0f}%)")
                                logger.info(f"   Reason: {int_signal.trade_reason}")

                                # v1.3.0: Send manual trade card BEFORE order attempt
                                self._send_manual_entry_card(
                                    symbol    = int_signal.symbol,
                                    direction = int_signal.predicted_direction,
                                    signal    = signal,
                                    score     = int_signal.total_score,
                                    source    = 'PH2-INT',
                                    capital   = int_signal.recommended_capital,
                                )

                                # v1.4.0: Confirmation gate — skip auto-execution if enabled
                                _gate_on = getattr(self.config, 'TRADE_CONFIRMATION_GATE_ENABLED', False)
                                if _gate_on:
                                    self._register_pending_confirmation(
                                        symbol    = int_signal.symbol,
                                        signal    = signal,
                                        source    = 'PH2-INT',
                                        score     = int_signal.total_score,
                                        direction = int_signal.predicted_direction,
                                        capital   = int_signal.recommended_capital,
                                    )
                                    continue  # Wait for /done reply

                                # Execute
                                position = self.phase3.execute_signal_realtime(signal)

                                if position:
                                    logger.info(f"   ✅ Position opened!")
                                    executed_symbols.add(int_signal.symbol)

                                    # v5.2.1: Block this stock from re-entry for rest of day
                                    if self.phase2:
                                        self.phase2.traded_today.add(int_signal.symbol)
                                        logger.info(f"   🚫 {int_signal.symbol}: Blocked for rest of day (traded_today)")

                                    # 🚨 Record trade for starvation prevention (v3.1)
                                    if self.starvation_prevention:
                                        self.starvation_prevention.record_trade()
                                        logger.info(f"   📊 Trade recorded for starvation tracking")

                                    # 🛫 Register with Phase 4 Portfolio Manager (v4.3)
                                    # NOTE: AdaptiveExitManager registration removed - Phase 4 handles exits
                                    if self.phase4:
                                        try:
                                            self.phase4.on_position_opened(position, signal)
                                            logger.info(f"   🛫 Registered with Phase 4 monitoring")
                                        except Exception as e:
                                            logger.error(f"   ⚠️ Phase 4 registration failed: {e}")

                                    # v5.3.5: Log trade entry to blackbox
                                    try:
                                        if self.blackbox:
                                            entry_price = position.get('entry_price', 0) if isinstance(position, dict) else getattr(position, 'entry_price', 0)
                                            quantity = position.get('quantity', 0) if isinstance(position, dict) else getattr(position, 'quantity', 0)
                                            self.blackbox.log_phase3_trade(
                                                symbol=int_signal.symbol,
                                                action='BUY',
                                                details={
                                                    'entry_price': entry_price,
                                                    'quantity': quantity,
                                                    'score': int_signal.total_score,
                                                    'signal_strength': int_signal.signal_strength.value,
                                                    'reason': int_signal.trade_reason,
                                                    'source': 'Phase2_Signal'
                                                }
                                            )
                                    except Exception as e:
                                        logger.debug(f"Blackbox trade entry log failed: {e}")

                                else:
                                    logger.warning(f"   ❌ Execution failed")
                                    
                            except Exception as e:
                                logger.error(f"[X] Failed to execute {int_signal.symbol}: {e}")
                    
                    elif not tradeable_signals:
                        # Log why signals were skipped
                        skip_threshold = getattr(self.config, 'INTELLIGENT_SCORE_SKIP', 45)
                        
                        # Get adjusted threshold from starvation prevention
                        if self.starvation_prevention:
                            skip_threshold, _ = self.starvation_prevention.get_adjusted_threshold(skip_threshold)
                        
                        for int_signal in intelligent_signals:
                            if int_signal.total_score < skip_threshold:
                                logger.info(f"   ⏭️  {int_signal.symbol}: Score {int_signal.total_score:.0f} < {skip_threshold} (skipped)")
                                
                                # Track skipped signals
                                if self.starvation_prevention:
                                    self.starvation_prevention.record_signal(
                                        int_signal.total_score, skip_threshold, False
                                    )
                    
                    # ═══════════════════════════════════════════════════════
                    # v5.1.0 FIX: RELEASE ALL RESERVATIONS for non-executed signals
                    # deploy() handles capital for executed signals (reserve→deploy).
                    # All others must be unreserved to prevent capital leak.
                    # ═══════════════════════════════════════════════════════
                    if self.capital_manager and raw_signals:
                        released_count = 0
                        for raw_sig in raw_signals:
                            sig_symbol = raw_sig.get('symbol', '')
                            if raw_sig.get('capital_reserved') and sig_symbol not in executed_symbols:
                                entry_size = raw_sig.get('entry_size', 0)
                                if entry_size > 0:
                                    self.capital_manager.unreserve(sig_symbol, entry_size)
                                    released_count += 1
                        if released_count > 0:
                            logger.info(f"🔓 Released {released_count} capital reservation(s) for non-executed signals")
                    
                else:
                    logger.info("[i]  No signals generated")
                
                # ═══════════════════════════════════════════════════════════
                # v5.1.0 FIX: Safety net — if NO intelligent signals but 
                # raw signals had reservations, release them all
                # ═══════════════════════════════════════════════════════════
                if not intelligent_signals and self.capital_manager and raw_signals:
                    for raw_sig in raw_signals:
                        if raw_sig.get('capital_reserved'):
                            entry_size = raw_sig.get('entry_size', 0)
                            if entry_size > 0:
                                self.capital_manager.unreserve(raw_sig.get('symbol', ''), entry_size)
            
            else:
                # Fallback to standard Phase 2 (no intelligent engine)
                signals = self.phase2.check_entry_signals()

                if signals:
                    logger.info(f"[OK] {len(signals)} signal(s) generated")

                    # v1.3.0: Apply same Phase 9 entry window gate as intelligent path
                    if not _entry_window_ok:
                        logger.info(f"🧠 PH9 Entry Window: holding {len(signals)} PH2 fallback "
                                    f"signal(s) — window not yet open ({self.phase9.todays_entry_window})")
                        signals = []

                    if self.phase3:
                        for signal in signals:
                            try:
                                # v5.2.1: Daily duplicate prevention (defense-in-depth)
                                if self.phase2 and signal['symbol'] in self.phase2.traded_today:
                                    logger.info(f"🚫 {signal['symbol']}: Already traded today - skipping")
                                    continue
                                
                                # v4.9.0: Loop detection check
                                if self.phase4 and hasattr(self.phase4, 'is_reentry_allowed'):
                                    allowed, reason = self.phase4.is_reentry_allowed(signal['symbol'])
                                    if not allowed:
                                        logger.warning(f"⏳ {signal['symbol']}: Re-entry BLOCKED - {reason}")
                                        continue

                                # v1.4.0: Stamp portfolio context
                                signal['_portfolio_context'] = self._build_portfolio_context(signal.get('symbol', ''))

                                # v1.3.0: Send manual trade card BEFORE order attempt
                                self._send_manual_entry_card(
                                    symbol    = signal.get('symbol', ''),
                                    direction = signal.get('direction', 'BUY'),
                                    signal    = signal,
                                    score     = signal.get('composite_score', signal.get('score', 0)),
                                    source    = signal.get('source', signal.get('phase', 'PH2')),
                                    capital   = None,
                                )

                                # v1.4.0: Confirmation gate — skip auto-execution if enabled
                                _gate_on = getattr(self.config, 'TRADE_CONFIRMATION_GATE_ENABLED', False)
                                if _gate_on:
                                    self._register_pending_confirmation(
                                        symbol    = signal.get('symbol', ''),
                                        signal    = signal,
                                        source    = signal.get('source', signal.get('phase', 'PH2')),
                                        score     = signal.get('composite_score', signal.get('score', 0)),
                                        direction = signal.get('direction', 'BUY'),
                                        capital   = None,
                                    )
                                    continue  # Wait for /done reply

                                position = self.phase3.execute_signal_realtime(signal)

                                if position:
                                    logger.info(f"[OK] {signal['symbol']}: Position opened")

                                    # v5.2.1: Block this stock from re-entry for rest of day
                                    if self.phase2:
                                        self.phase2.traded_today.add(signal['symbol'])
                                        logger.info(f"🚫 {signal['symbol']}: Blocked for rest of day (traded_today)")

                                    if self.starvation_prevention:
                                        self.starvation_prevention.record_trade()
                                else:
                                    logger.warning(f"[!]  {signal['symbol']}: Execution failed")
                                    
                            except Exception as e:
                                logger.error(f"[X] Failed to execute {signal['symbol']}: {e}")
                else:
                    logger.info("[i]  No signals generated")
            
            self.last_phase2_update = datetime.now()
            
            # ═══════════════════════════════════════════════════════════════
            # v4.6.0 NEW: ADAPTIVE TELEGRAM DECISION
            # ═══════════════════════════════════════════════════════════════
            try:
                snapshot = self._collect_phase2_snapshot()
                self._run_adaptive_phase2_telegram(snapshot)
            except Exception as e:
                logger.error(f"Adaptive telegram error: {e}")
            
        except Exception as e:
            logger.error(f"[X] Phase 2 cycle failed: {e}")
            logger.error(traceback.format_exc())
        
        logger.info("─" * 80)
        logger.info("")
    
    
    def _run_phase3_fast_check(self):
        """
        Run Phase 3 fast exit check with adaptive exit logic.
        
        v4.3 UPDATE: Phase 4 takes priority if available!
        - Phase 4 handles TCAS/ILS monitoring and exit decisions
        - Falls back to Phase 3/Adaptive if Phase 4 not available
        
        v3.1 NEW:
        - Checks adaptive exits FIRST (trailing, momentum, time)
        - Falls back to standard exits if adaptive not triggered
        
        v4.7.1 FIX-03: ALWAYS check manual stops (TC-06 fallback)
        - Manual stop monitoring is Phase 3's responsibility
        - Must run every cycle regardless of Phase 4 status
        - Removed early 'return' after Phase 4 that was skipping manual stops
        """
        
        # ═══════════════════════════════════════════════════════════════════
        # 🛫 PHASE 4 MONITORING (v4.3 - Priority if available!)
        # ═══════════════════════════════════════════════════════════════════
        
        phase4_handled = False
        if self.phase4 and self.phase4.has_open_positions():
            try:
                self.phase4.run_monitoring_cycle()
                phase4_handled = True

                # v1.0.0: ORB Advisory pull — check ORB status for each open position
                if self.orb_advisory and hasattr(self.phase4, 'check_orb_for_position'):
                    for sym in list(self.phase4.positions.keys()):
                        try:
                            self.phase4.check_orb_for_position(sym)
                        except Exception as orb_e:
                            logger.debug(f"ORB check for {sym}: {orb_e}")

            except Exception as e:
                logger.error(f"[X] Phase 4 monitoring failed, falling back: {e}")
        
        # ═══════════════════════════════════════════════════════════════════
        # v4.9.0: Phase 3 exit methods REMOVED
        # ═══════════════════════════════════════════════════════════════════
        # check_manual_stops() and check_position_exits() have been removed
        # from Phase 3. Phase 4 now handles ALL exit monitoring:
        # - TCAS monitoring (stop loss collision avoidance)
        # - ILS monitoring (target approach with trailing)
        # - Health scoring (position quality)
        # - ChatGPT decisions (intelligent exit timing)
        # - GTT order management (broker-side protection)
        # - Manual stop fallback (moved to Phase 4)
        #
        # If Phase 4 fails, positions remain protected by GTT orders.
        # ═══════════════════════════════════════════════════════════════════
        
        if not phase4_handled:
            # Phase 4 not available - this is a critical error in v4.9.0
            if self.phase3 and self.phase3.has_open_positions():
                logger.warning("⚠️ Phase 4 not available but positions exist!")
                logger.warning("   Positions protected by GTT orders only")
    
    
    # ═══════════════════════════════════════════════════════════════════════════
    # CANDLESTICK PATTERN DETECTION (v1.0.0)
    # ═══════════════════════════════════════════════════════════════════════════

    def _run_candlestick_pattern_detection(self):
        """
        Run candlestick pattern detection on active Phase 2 monitors.

        Fetches the last 6 completed 15-min candles for each monitored symbol
        and runs the pattern detector. Routes results to Phase 6 (bullish boost)
        and Phase 4 TCAS (bearish warning).

        Rate-limited to run at most once every 15 minutes to avoid excessive
        Kite historical_data API calls.
        """
        # Rate limit: only run once per 15-minute candle close
        now = datetime.now()
        if not hasattr(self, '_last_pattern_check'):
            self._last_pattern_check = datetime.min
        elapsed = (now - self._last_pattern_check).total_seconds()
        if elapsed < 900:  # 15 minutes
            return
        self._last_pattern_check = now

        if not self.phase2 or not hasattr(self.phase2, 'monitors'):
            return

        monitors = self.phase2.monitors
        if not monitors:
            return

        detection_count = 0

        for monitor in monitors:
            try:
                symbol = monitor.symbol
                instrument_token = getattr(monitor, 'instrument_token', None)
                if not instrument_token:
                    continue

                # Fetch last 6 completed 15-min candles
                from_date = now - timedelta(hours=2)
                try:
                    candles_raw = self.kite.historical_data(
                        instrument_token=instrument_token,
                        from_date=from_date,
                        to_date=now,
                        interval='15minute'
                    )
                except Exception as e:
                    logger.debug(f"Pattern: {symbol} candle fetch failed: {e}")
                    continue

                if not candles_raw or len(candles_raw) < 2:
                    continue

                # Convert to CandleData objects
                candle_objects = []
                for c in candles_raw:
                    candle_objects.append(CandleData(
                        symbol=symbol,
                        timestamp=c['date'] if isinstance(c['date'], datetime) else datetime.now(),
                        open=float(c['open']),
                        high=float(c['high']),
                        low=float(c['low']),
                        close=float(c['close']),
                        volume=int(c.get('volume', 0))
                    ))

                # Last candle is the current (possibly incomplete) one — use second-to-last
                # as the "just completed" candle, and earlier ones as context
                current_candle = candle_objects[-2] if len(candle_objects) >= 2 else candle_objects[-1]
                recent_candles = candle_objects[:-2] if len(candle_objects) > 2 else []

                # Build key levels from Phase 2 monitor data
                key_levels = KeyLevels(
                    pdh=getattr(monitor, 'prev_day_high', None) or None,
                    pdl=getattr(monitor, 'prev_day_low', None) or None,
                    vwap=getattr(monitor, 'vwap', None) or None,
                )

                # Run pattern detection
                signals = self.pattern_detector.analyze(
                    symbol, current_candle, recent_candles, key_levels
                )

                for signal in signals:
                    detection_count += 1

                    # Route BULLISH to Phase 6
                    if signal.direction == 'BULLISH' and signal.bonus_points > 0:
                        if self.phase6 and hasattr(self.phase6, 'apply_pattern_bonus'):
                            self.phase6.apply_pattern_bonus(symbol, signal)

                        # Telegram notification
                        if self.telegram:
                            msg = CandlestickPatternDetector.format_bullish_telegram(
                                signal, effective_score=signal.bonus_points,
                                original_score=0
                            )
                            try:
                                self.telegram.send_message(msg)
                            except Exception:
                                pass

                    # Route BEARISH to Phase 4 TCAS
                    elif signal.direction == 'BEARISH' and signal.tcas_severity:
                        if self.phase4 and hasattr(self.phase4, 'handle_pattern_warning'):
                            self.phase4.handle_pattern_warning(signal)

                        # Telegram notification
                        if self.telegram:
                            msg = CandlestickPatternDetector.format_bearish_telegram(
                                signal, action_taken=f"Severity: {signal.tcas_severity}"
                            )
                            try:
                                self.telegram.send_message(msg)
                            except Exception:
                                pass

            except Exception as e:
                logger.debug(f"Pattern detection error for {getattr(monitor, 'symbol', '?')}: {e}")

        if detection_count > 0:
            logger.info(f"Pattern Detection: {detection_count} pattern(s) found across {len(monitors)} stocks")

        # Decay stale pattern bonuses in Phase 6 (age by 1 candle per 15-min cycle)
        if self.phase6 and hasattr(self.phase6, 'decrement_pattern_bonus'):
            for monitor in monitors:
                try:
                    self.phase6.decrement_pattern_bonus(monitor.symbol)
                except Exception:
                    pass

    # ═══════════════════════════════════════════════════════════════════════════
    # v1.0.0: ORB (OPEN RANGE BREAKOUT) ADVISORY — MONITORING LOOP INTEGRATION
    # ═══════════════════════════════════════════════════════════════════════════

    def _run_orb_advisory_update(self):
        """
        Drive the ORB advisory through its 3 stages based on current time.

        Stage 1 (09:15–10:15): feed_candle() — silent IB recording
        Stage 2 (10:15 lock):  lock_ib()     — classify IB range
        Stage 3 (10:15+):      update()      — compression + breakout detection

        Rate-limited to once per 15-min candle (same cadence as pattern detection).
        Uses candle data already fetched by Phase 2 monitors — ZERO extra API calls.
        """
        now = datetime.now()

        # Rate limit: only run once per 15-minute interval
        if not hasattr(self, '_last_orb_check'):
            self._last_orb_check = datetime.min
        elapsed = (now - self._last_orb_check).total_seconds()
        if elapsed < 900:  # 15 minutes
            return
        self._last_orb_check = now

        if not self.phase2 or not hasattr(self.phase2, 'monitors'):
            return

        monitors = self.phase2.monitors
        if not monitors:
            return

        current_time = now.time()
        ib_start = dt_time(9, 15)
        ib_end = dt_time(10, 15)
        expiry_hour = getattr(self.config, 'ORB_EXPIRY_HOUR', 13)
        expiry_time = dt_time(expiry_hour, 0)

        # Past expiry — nothing to do
        if current_time >= expiry_time:
            return

        for monitor in monitors:
            try:
                symbol = monitor.symbol
                instrument_token = getattr(monitor, 'instrument_token', None)
                if not instrument_token:
                    continue

                # ── STAGE 1: IB Formation (09:15 – 10:15) ──────────────────
                if ib_start <= current_time < ib_end:
                    # Feed the latest completed candle to build IB range
                    from_date = now - timedelta(minutes=20)
                    try:
                        candles_raw = self.kite.historical_data(
                            instrument_token=instrument_token,
                            from_date=from_date,
                            to_date=now,
                            interval='15minute'
                        )
                    except Exception:
                        continue

                    if candles_raw:
                        # Use last completed candle (second-to-last if current still forming)
                        candle = candles_raw[-2] if len(candles_raw) >= 2 else candles_raw[-1]
                        self.orb_advisory.feed_candle(symbol, candle)

                # ── STAGE 2: Lock IB at 10:15 ──────────────────────────────
                elif current_time >= ib_end:
                    status = self.orb_advisory.get_status(symbol)

                    # Lock IB if still in RECORDING state
                    if status and status.get('status') == 'RECORDING':
                        result = self.orb_advisory.lock_ib(symbol)
                        if result and result.get('potential') in ('VERY_NARROW', 'NARROW'):
                            # Telegram: IB locked with breakout potential
                            if self.telegram:
                                try:
                                    self.telegram.send_message(
                                        f"ORB IB LOCKED -- {symbol}\n"
                                        f"{'=' * 35}\n"
                                        f"IB High: {result['ib_high']:.2f}\n"
                                        f"IB Low:  {result['ib_low']:.2f}\n"
                                        f"Range:   {result.get('ib_range_pct', 0):.2f}%\n"
                                        f"Potential: {result['potential']}\n"
                                        f"Status: Monitoring for compression/breakout"
                                    )
                                except Exception:
                                    pass

                    # ── STAGE 3: Compression + Breakout Detection ──────────
                    elif status and status.get('status') in ('MONITORING', 'COMPRESSION_DETECTED'):
                        # Fetch latest completed 15-min candle
                        from_date = now - timedelta(minutes=20)
                        try:
                            candles_raw = self.kite.historical_data(
                                instrument_token=instrument_token,
                                from_date=from_date,
                                to_date=now,
                                interval='15minute'
                            )
                        except Exception:
                            continue

                        if not candles_raw:
                            continue

                        candle = candles_raw[-2] if len(candles_raw) >= 2 else candles_raw[-1]

                        # Gather BB bandwidth and avg volume from Phase 2 data (ZERO new API calls)
                        # bb_bandwidth: Phase 2 may not compute this — fallback gracefully (None is handled by ORB)
                        bb_bandwidth = getattr(monitor, 'bb_bandwidth', None) or getattr(monitor, 'bollinger_bandwidth', None)
                        # avg_volume: Phase 2 stores this as avg_volume_cached
                        avg_volume = getattr(monitor, 'avg_volume_cached', None) or getattr(monitor, 'avg_volume', None)

                        prev_status = status.get('status')
                        self.orb_advisory.update(symbol, candle, bb_bandwidth, avg_volume)

                        # Check for status transition → send Telegram
                        if self.orb_advisory.has_status_changed(symbol):
                            new_state = self.orb_advisory.get_status(symbol)
                            if not new_state:
                                continue

                            new_status = new_state.get('status')
                            c_close = candle.get('close', 0) if isinstance(candle, dict) else getattr(candle, 'close', 0)

                            if new_status == 'COMPRESSION_DETECTED' and self.telegram:
                                try:
                                    from orb_advisory import ORBAdvisory as _ORB
                                    msg = _ORB.format_compression_telegram(symbol, new_state)
                                    self.telegram.send_message(msg)
                                except Exception:
                                    pass

                            elif new_status in ('UPSIDE_BREAKOUT', 'DOWNSIDE_BREAKDOWN') and self.telegram:
                                try:
                                    from orb_advisory import ORBAdvisory as _ORB
                                    msg = _ORB.format_breakout_telegram(symbol, new_state, c_close)
                                    self.telegram.send_message(msg)
                                except Exception:
                                    pass

            except Exception as e:
                logger.debug(f"ORB update error for {getattr(monitor, 'symbol', '?')}: {e}")

    def _run_periodic_broker_sync(self):
        """
        v4.3.2: Periodic broker sync when Phase 4 has no positions.

        When Phase 4 is monitoring positions, it has its own internal broker sync
        that runs every 5 minutes. However, when there are NO positions, the
        monitoring cycle doesn't run, so we need to periodically check for
        manually-added positions from the broker.

        This runs every 5 minutes and only if:
        1. broker_sync is available
        2. Phase 4 exists but has no positions OR Phase 4 doesn't exist
        """
        if not self.broker_sync:
            return
        
        # Only run if Phase 4 has no positions (or doesn't exist)
        if self.phase4 and self.phase4.has_open_positions():
            return  # Phase 4's internal sync handles this
        
        # Check interval (every 5 minutes)
        PERIODIC_SYNC_INTERVAL = 1800  # 30 minutes
        if not hasattr(self, '_last_periodic_broker_sync'):
            self._last_periodic_broker_sync = datetime.min
        
        elapsed = (datetime.now() - self._last_periodic_broker_sync).total_seconds()
        if elapsed < PERIODIC_SYNC_INTERVAL:
            return
        
        self._last_periodic_broker_sync = datetime.now()
        
        try:
            logger.debug("📡 Running periodic broker sync (no positions)...")
            
            # Get positions from broker
            broker_positions = self.broker_sync.get_all_positions()
            
            if broker_positions:
                logger.info(f"📡 Found {len(broker_positions)} positions at broker")
                
                # Add to Phase 4 if available
                if self.phase4:
                    for symbol, pos in broker_positions.items():
                        if symbol not in self.phase4.positions:
                            logger.info(f"   ➕ Adding {symbol} to Phase 4 monitoring")
                            self.phase4._add_manual_position(symbol, pos.to_dict())
                    
                    if self.phase4.has_open_positions():
                        self._phase4_started = True
                        logger.info(f"📡 Phase 4 now monitoring {len(self.phase4.positions)} positions")
                        
        except Exception as e:
            logger.warning(f"⚠️ Periodic broker sync failed: {e}")

    def _get_live_market_data(self) -> dict:
        """
        Fetch Nifty 50 + India VIX from Kite. Caches for 60 s to avoid flooding the API.
        Also pushes the values into phase9 so entry gate and chat always have current data.
        Returns dict with keys: nifty_change_pct, nifty_close, vix (floats or 'N/A').
        """
        now = datetime.now()
        _age = (
            (now - self._market_data_cache_time).total_seconds()
            if self._market_data_cache_time else 999
        )
        if _age < 60 and self._market_data_cache:
            return self._market_data_cache

        result = dict(self._market_data_cache)  # carry forward previous on failure
        try:
            if self.kite:
                _quotes = self.kite.quote(['NSE:NIFTY 50', 'NSE:INDIA VIX'])
                nq = _quotes.get('NSE:NIFTY 50') or _quotes.get('NSE:Nifty 50', {})
                if nq:
                    _last  = nq.get('last_price', 0) or 0
                    _net   = nq.get('net_change', 0) or 0
                    _prev  = _last - _net
                    if _prev:
                        result['nifty_change_pct'] = round(_net / _prev * 100, 2)
                    result['nifty_close'] = _last
                vq = _quotes.get('NSE:INDIA VIX') or _quotes.get('NSE:India VIX', {})
                if vq:
                    result['vix'] = vq.get('last_price', 'N/A')
                self._market_data_cache = result
                self._market_data_cache_time = now
                # Push into phase9 so entry gate / chat always see current values
                if self.phase9:
                    _nifty_chg = result.get('nifty_change_pct', 'N/A')
                    self.phase9._live_nifty_chg = (
                        f"{_nifty_chg:+.2f}" if isinstance(_nifty_chg, (int, float)) else str(_nifty_chg)
                    )
                    _vix = result.get('vix', 'N/A')
                    self.phase9._live_vix = (
                        f"{_vix:.1f}" if isinstance(_vix, (int, float)) else str(_vix)
                    )
                    # Track intraday Nifty direction for entry gate context
                    _nifty_curr = result.get('nifty_close', None)
                    if _nifty_curr and isinstance(_nifty_curr, (int, float)):
                        _prev = getattr(self.phase9, '_live_nifty_curr', None)
                        if _prev and isinstance(_prev, (int, float)):
                            _delta = _nifty_curr - _prev
                            if _delta > 5:
                                self.phase9._live_nifty_direction = 'rising'
                            elif _delta < -5:
                                self.phase9._live_nifty_direction = 'falling'
                            else:
                                self.phase9._live_nifty_direction = 'flat'
                        self.phase9._live_nifty_curr = _nifty_curr
        except Exception as _e:
            logger.debug(f"_get_live_market_data failed: {_e}")

        return result

    def _send_cycle_status(self, has_monitors: bool = True) -> None:
        """Lightweight no-Claude PH2 cycle status push — shows situation + next action."""
        if not self.telegram:
            return
        try:
            now = datetime.now()
            _md = self._get_live_market_data()
            _nifty_str = (
                f"{_md['nifty_change_pct']:+.2f}%" if isinstance(_md.get('nifty_change_pct'), (int, float))
                else 'N/A'
            )
            _vix_str = (
                f"{_md['vix']:.1f}" if isinstance(_md.get('vix'), (int, float))
                else 'N/A'
            )
            lines = [f"<b>📊 CYCLE STATUS — {now.strftime('%H:%M')}</b>  Nifty {_nifty_str} | VIX {_vix_str}"]

            # Active blocks
            blocks = []
            if getattr(self, '_ph4_brain_defensive', False):
                blocks.append("PH4 DEFENSIVE")
            if getattr(self, '_ph5_brain_skip', False):
                blocks.append("PH5 SKIP")
            if getattr(self, '_ph5a_brain_pause', False):
                blocks.append("PH5A PAUSED")
            if getattr(self, '_ph6_brain_hold', False):
                blocks.append("PH6 HOLD")
            _regime = 'NORMAL'
            if self.phase9:
                _regime = getattr(self.phase9, 'todays_regime', 'NORMAL')
                if _regime in ('HALT', 'DEFENSIVE'):
                    blocks.append(f"REGIME={_html.escape(_regime)}")
            # Check nifty filter (look for any phase that tracks it)
            for _attr in ('_nifty_filter_blocked', '_nifty_blocked', 'nifty_filter_blocked'):
                if getattr(self, _attr, False):
                    blocks.append("NIFTY FILTER")
                    break

            if blocks:
                lines.append("🔴 Blocked: " + " | ".join(blocks))
            else:
                lines.append("🟢 Entries: open")

            # Monitor states
            if has_monitors and hasattr(self.phase2, 'monitors') and self.phase2.monitors:
                mon_parts = []
                for m in self.phase2.monitors[:5]:
                    sym = _html.escape(str(getattr(m, 'symbol', '?')))
                    rsi = getattr(m, 'current_rsi', None)
                    state = _html.escape(str(getattr(m, 'rsi_state', '?')))
                    rsi_str = f"{rsi:.0f}" if rsi is not None else "?"
                    mon_parts.append(f"{sym} {rsi_str}[{state}]")
                lines.append("👁 " + "  ".join(mon_parts))
            else:
                lines.append("👁 Monitors: none")

            # Next brain heartbeat ETA
            if self.phase9:
                _hb_min = getattr(self.config, 'PH9_HEARTBEAT_INTERVAL_MIN', 25)
                _last_hb = getattr(self.phase9, '_last_heartbeat_time', None)
                if _last_hb:
                    _remaining = max(0, _hb_min * 60 - (now - _last_hb).total_seconds())
                    lines.append(f"🧠 Brain check: ~{int(_remaining // 60)}m")
                else:
                    lines.append("🧠 Brain: awaiting heartbeat")

            # Next scheduled scan
            for scan in self.interrupt_schedule:
                _st = now.replace(hour=scan['hour'], minute=scan['minute'], second=0, microsecond=0)
                if _st > now:
                    lines.append(f"🔍 Next scan: {_st.strftime('%H:%M')} ({_html.escape(scan['description'])})")
                    break
            else:
                lines.append("🔍 No more scans today")

            self.telegram.send_message("\n".join(lines))
        except Exception as _e:
            logger.debug(f"_send_cycle_status failed: {_e}")

    def _send_heartbeat(self):
        """Send 15-minute heartbeat with v3.1 status"""
        current_time = time.time()
        
        if (current_time - self.last_heartbeat_time) < self.HEARTBEAT_INTERVAL:
            return
        
        self.last_heartbeat_time = current_time
        now = datetime.now()
        
        try:
            # Count active stocks
            active_count = 0
            stock_list = []
            
            if self.phase2 and hasattr(self.phase2, 'monitors'):
                active_count = len(self.phase2.monitors)
                stock_list = [m.symbol for m in self.phase2.monitors[:5]]
            
            # Count open positions
            open_positions = 0
            if self.phase3 and hasattr(self.phase3, 'positions'):
                open_positions = len(self.phase3.positions)
            
            # Determine status — reflect actual block state, not just window state
            nifty_blocked = (self.phase2 and
                             getattr(self.phase2, '_nifty_filter_blocked', False))
            all_entries_blocked = self._ph4_brain_defensive or nifty_blocked
            if now.time() > self.ENTRY_CUTOFF:
                status = "🟡 ENTRY CUTOFF (Monitoring exits)"
            elif not self._is_entry_window_open():
                status = "⏳ WAITING"
            elif all_entries_blocked:
                status = "🔴 BLOCKED (no new entries)"
            else:
                status = "🟢 ACTIVELY SCANNING"
            
            # Next interrupt
            next_interrupt = "None scheduled"
            for interrupt in self.interrupt_schedule:
                int_time = dt_time(interrupt['hour'], interrupt['minute'])
                if now.time() < int_time:
                    next_interrupt = f"{interrupt['hour']:02d}:{interrupt['minute']:02d} - {interrupt['description']}"
                    break
            
            message = (
                f"💓 SYSTEM HEARTBEAT v4.6.0\n"
                f"─────────────────────\n"
                f"⏰ {now.strftime('%I:%M %p')}\n\n"
                f"Status: {status}\n"
                f"📊 Monitoring: {active_count} stocks\n"
            )
            
            if stock_list:
                message += f"   └─ {', '.join(stock_list)}\n"
            
            if open_positions > 0:
                message += f"💼 Open Positions: {open_positions}\n"

            # 🧠 Brain directive blocks
            blocks = []
            if self._ph4_brain_defensive:
                blocks.append("PH4=DEFENSIVE")
            if self._ph5_brain_skip:
                blocks.append("PH5=SKIP")
            if self._ph5a_brain_pause:
                blocks.append("PH5A=PAUSE")
            if self._ph6_brain_hold:
                blocks.append("PH6=HOLD")
            if nifty_blocked:
                blocks.append("NIFTY FILTER")
            if blocks:
                message += f"⛔ Blocks: {' | '.join(blocks)}\n"

            # 🧠 Market regime
            if self.intelligent_wrapper:
                try:
                    regime = self.intelligent_wrapper.get_market_regime()
                    message += f"🧠 Market: {regime.value}\n"
                except:
                    pass
            
            # 🚨 Starvation status (v3.1) — suppress when brain has deliberately blocked entries
            if self.starvation_prevention:
                status_data = self.starvation_prevention.get_status()
                _brain_blocked = (self._ph4_brain_defensive or
                                  (self.phase9 and getattr(self.phase9, 'todays_regime', 'NORMAL') in ('HALT', 'DEFENSIVE')))
                if status_data['starvation_risk'] and not _brain_blocked:
                    message += f"\n🚨 STARVATION RISK: {status_data['trades_today']}/{status_data['min_required']} trades\n"
                else:
                    message += f"\n✅ Trades: {status_data['trades_today']}/{status_data['min_required']}\n"
            
            # 🛫 Phase 4 status (v4.3)
            if self.phase4 and self.phase4.has_open_positions():
                tracked = len(self.phase4.positions)
                message += f"🛫 Phase 4 monitoring: {tracked} position(s)\n"
            
            message += (
                f"\n⏭️  Next: {next_interrupt}\n"
                f"─────────────────────\n"
                f"✅ System v4.6.0 running"
            )
            
            if self.telegram:
                self.telegram.send_message(message)
            
            logger.info("💓 Heartbeat sent")
            
        except Exception as e:
            logger.error(f"Heartbeat error: {e}")
    
    
    def _is_market_open(self) -> bool:
        """Check if market is currently open"""
        now = datetime.now().time()
        return self.MARKET_START <= now <= self.MARKET_END
    
    
    def _is_entry_window_open(self) -> bool:
        """Check if entry window is still open"""
        now = datetime.now().time()
        return now <= self.ENTRY_CUTOFF
    
    def _is_phase5_window(self) -> bool:
        """
        v5.3.3: Check if Phase 1 scans should be blocked.
        
        Returns True (block Phase 1) when:
        1. Phase 5 has NOT yet completed AND we're in 09:08-09:50 window
        2. OR there are active TIER1 MIS positions (Phase 5 trade being monitored)
        
        Phase 1 scans MUST NOT run during this window to avoid:
        - API rate competition with Phase 5 gap scanning / TIER1 monitoring
        - Stock universe corruption during active gap analysis
        - CPU/memory contention during time-critical execution
        
        Once Phase 5 completes AND no TIER1 positions remain, returns False
        so Phase 1 can proceed normally.
        """
        if not self.phase5:
            return False
        
        # If Phase 5 already ran today, check for active TIER1 positions
        if self._phase5_run_today:
            # v5.3.3: Still block if TIER1 MIS positions are being monitored
            if self.phase4 and hasattr(self.phase4, 'has_tier1_positions'):
                if self.phase4.has_tier1_positions():
                    return True
            # v5.6.1: Time-based safety net — even if PH4 can't confirm TIER1,
            # respect the exclusive window until ph5_end time (default 09:55).
            # Prevents Phase 1 from stomping MIS monitoring if handoff is delayed.
            now_t = datetime.now().time()
            ph5_end_hour = getattr(self.config, 'PH5_EXCLUSIVE_WINDOW_END_HOUR', 9)
            ph5_end_minute = getattr(self.config, 'PH5_EXCLUSIVE_WINDOW_END_MINUTE', 55)
            if now_t <= dt_time(ph5_end_hour, ph5_end_minute):
                return True
            return False
        
        now = datetime.now().time()
        # v5.6.0: Phase 5 MIS exclusive window: 09:08 (pre-market prep) to 09:55
        # Phase 5 enters ~09:18-09:22 but MIS position needs TIER1 monitoring until 09:55.
        # Phase 1 first scan at 10:00 is safely outside this window.
        ph5_end_hour = getattr(self.config, 'PH5_EXCLUSIVE_WINDOW_END_HOUR', 9)
        ph5_end_minute = getattr(self.config, 'PH5_EXCLUSIVE_WINDOW_END_MINUTE', 55)
        return dt_time(9, 8) <= now <= dt_time(ph5_end_hour, ph5_end_minute)

    def _is_mis_active(self) -> bool:
        """v5.4.1: Check if MIS position is active — blocks new CNC work."""
        if self.phase4 and hasattr(self.phase4, 'has_tier1_positions'):
            return self.phase4.has_tier1_positions()
        return False

    def _is_cnc_idle(self) -> bool:
        """v5.4.1: Detect if CNC flow has been idle for 30+ minutes."""
        monitor_count = len(self.phase2.monitors) if hasattr(self.phase2, 'monitors') else 0

        if monitor_count > 0:
            self._cnc_idle_since = None  # Reset — CNC has work
            return False

        now = datetime.now()
        if self._cnc_idle_since is None:
            self._cnc_idle_since = now
            return False  # Just became idle

        return (now - self._cnc_idle_since).total_seconds() >= self.CNC_IDLE_THRESHOLD_SEC

    def _log_idle_compact(self):
        """v5.4.1: One compact line per 30 min instead of death messages."""
        now = datetime.now()
        if (now - self._cnc_idle_last_log).total_seconds() < self.CNC_IDLE_LOG_INTERVAL_SEC:
            return  # Not time yet

        idle_min = int((now - self._cnc_idle_since).total_seconds() / 60)

        # Next Phase 1 scan
        next_scan = "none"
        for interrupt in self.interrupt_schedule:
            int_time = dt_time(interrupt['hour'], interrupt['minute'])
            if now.time() < int_time and not self.scans_completed.get(interrupt['label'], False):
                next_scan = f"{interrupt['hour']:02d}:{interrupt['minute']:02d}"
                break

        # Phase 5A status
        ph5a_status = "SCANNING" if (self.phase5a and self.phase5a.is_active()) else "idle"

        logger.info(f"CNC IDLE {idle_min}m | Ph5A: {ph5a_status} | Next Ph1: {next_scan}")
        self._cnc_idle_last_log = now


    def _get_sleep_time(self) -> int:
        """
        Calculate optimal sleep time based on position urgency.
        
        v5.0.1: Reads from config LIVE so /set tier1_sleep / /set tier2_sleep 
        takes effect immediately via Telegram.
        
        Priority:
          TIER_1 (MIS/Phase 5 scalps) → TIER1_SLEEP_SECONDS (default 10s)
          TIER_2 (CNC) / idle          → TIER2_SLEEP_SECONDS (default 60s)
        """
        # Read live from config (Telegram /set updates config attrs directly)
        tier1_sleep = getattr(self.config, 'TIER1_SLEEP_SECONDS', self.TIER1_SLEEP_SECONDS)
        tier2_sleep = getattr(self.config, 'TIER2_SLEEP_SECONDS', self.TIER2_SLEEP_SECONDS)
        
        # Phase 4 Tier 1 (MIS/Phase 5 scalps) = highest urgency
        if self.phase4 and hasattr(self.phase4, 'has_tier1_positions') and self.phase4.has_tier1_positions():
            return tier1_sleep
        # CNC positions exist but no MIS → longer interval is sufficient
        # (Phase 4 TCAS safety runs every cycle regardless)
        return tier2_sleep
    
    
    def _execute_claude_action(self, action: str) -> None:
        """v2.0.0: Execute a dynamic action requested by Claude via heartbeat next_cycle_actions.
        Claude has full power to orchestrate phases in real time — spawn scans, adjust intervals,
        force rescans, or push status. PH5 09:15-10:00 window is the only fixed constraint.
        """
        action = str(action).strip().upper()
        logger.info(f"🧠 Claude action → {action}")

        if action == 'RUN_PH1':
            # Fresh stock selection scan — Claude wants new names
            try:
                if self.phase1:
                    logger.info("🧠 Claude→PH1: Running fresh stock selection...")
                    _ph1_result = self.phase1.run_selection()
                    # run_selection() returns a dict {'selected_stocks': [...], 'filter1_count': N, ...}
                    # Extract just the stock list — passing the whole dict causes dict keys
                    # (selected_stocks, filter1_count, …) to be treated as phantom stock symbols.
                    selected = (_ph1_result.get('selected_stocks', [])
                                if isinstance(_ph1_result, dict) else _ph1_result) or []
                    if selected and self.phase2:
                        # Apply sector filter if briefing is done
                        if self.phase9 and self.phase9._morning_briefing_done:
                            _avoid = [s.upper() for s in getattr(self.phase9, 'todays_sector_avoid', [])]
                            if _avoid:
                                _sector_map = getattr(self.phase1, '_sector_map', {})
                                selected = [s for s in selected
                                            if str(_sector_map.get(
                                                s if isinstance(s, str) else s.get('symbol', ''), ''
                                            )).upper() not in _avoid]
                        self.phase2.initialize_monitors(selected)
                        logger.info(f"🧠 Claude→PH1: {len(selected)} stocks added to PH2 monitor")
                        if self.telegram:
                            self.telegram.send_message(
                                f"🧠 ALPHA triggered PH1 scan\n"
                                f"→ {len(selected)} stock(s) added to monitor")
            except Exception as e:
                logger.error(f"Claude action RUN_PH1 failed: {e}")

        elif action == 'RUN_PH2_EXTRA':
            # Immediate extra PH2 scan — bypass interval timer
            try:
                logger.info("🧠 Claude→PH2: Extra scan triggered")
                self.last_phase2_update = datetime.min  # Force immediate eligibility
                self._run_phase2_cycle()
            except Exception as e:
                logger.error(f"Claude action RUN_PH2_EXTRA failed: {e}")

        elif action == 'RUN_PH5A_RESCAN':
            # Force PH5A to rescan its IB watchlist immediately
            try:
                if self.phase5a and not self._ph5a_brain_pause:
                    self._ph5a_last_scan_time = None  # Reset so next loop triggers scan
                    logger.info("🧠 Claude→PH5A: Rescan triggered")
                    if self.telegram:
                        self.telegram.send_message("🔷 ALPHA triggered PH5A immediate rescan")
                else:
                    logger.info("🧠 Claude→PH5A: Rescan skipped (paused or unavailable)")
            except Exception as e:
                logger.error(f"Claude action RUN_PH5A_RESCAN failed: {e}")

        elif action.startswith('SET_PH2_INTERVAL:'):
            # Change PH2 scan frequency — Claude controls urgency
            try:
                minutes = int(action.split(':')[1])
                minutes = max(1, min(30, minutes))  # Safety clamp 1–30 min
                self.PHASE2_INTERVAL = minutes * 60
                logger.info(f"🧠 Claude→PH2: Interval changed to {minutes} min ({self.PHASE2_INTERVAL}s)")
                if self.telegram:
                    self.telegram.send_message(f"🧠 ALPHA: PH2 scan interval → every {minutes} min")
            except Exception as e:
                logger.error(f"Claude action {action} failed: {e}")

        elif action == 'RUN_PH6_ADVISORY':
            # Trigger options advisory
            try:
                if self.phase6 and hasattr(self.phase6, 'run_advisory'):
                    self.phase6.run_advisory()
                    logger.info("🧠 Claude→PH6: Advisory triggered")
                else:
                    logger.info("🧠 Claude→PH6: Phase 6 not available or no run_advisory()")
            except Exception as e:
                logger.error(f"Claude action RUN_PH6_ADVISORY failed: {e}")

        elif action == 'SEND_STATUS':
            # Push cycle status to Telegram now
            try:
                _has_mon = bool(
                    self.phase2 and hasattr(self.phase2, 'monitors') and self.phase2.monitors)
                self._send_cycle_status(has_monitors=_has_mon)
            except Exception as e:
                logger.error(f"Claude action SEND_STATUS failed: {e}")

        else:
            logger.warning(f"🧠 Unknown Claude action ignored: {action}")

    def _check_for_interrupts(self):
        """Check if any scheduled interrupt should fire"""
        now = datetime.now()
        current_time = now.time()

        # v5.2.0: Block Phase 1 scans during Phase 5 window
        if self._is_phase5_window():
            return False

        # v5.4.1: Block during MIS active position
        if self._is_mis_active():
            return False
        
        for interrupt in self.interrupt_schedule:
            int_time = dt_time(interrupt['hour'], interrupt['minute'])
            
            # Check if we're within the trigger window (same minute)
            if (current_time.hour == int_time.hour and 
                current_time.minute == int_time.minute and
                not self.scans_completed[interrupt['label']]):
                
                self._execute_phase1_interrupt(interrupt['label'], interrupt['description'])
                return True
        
        # ✅ v3.2.0 NEW: Check for adaptive scan (when < 3 stocks)
        if self._should_run_adaptive_scan():
            self._execute_adaptive_scan()
            return True
        
        return False
    
    
    def _should_run_adaptive_scan(self) -> bool:
        """
        🤖 GPT-ENHANCED: Decide if adaptive scan is worth running.
        """
        now = datetime.now()
        current_time = now.time()

        # Check market hours
        if not (self.MARKET_START <= current_time <= self.HARD_STOP):
            return False

        # v5.2.0: Block during Phase 5 window
        if self._is_phase5_window():
            return False

        # v5.4.1: Block adaptive during MIS takeover
        if self._is_mis_active():
            return False
        
        # Check interval
        elapsed = (now - self.last_adaptive_scan).total_seconds()
        if elapsed < self.ADAPTIVE_SCAN_INTERVAL:
            return False
        
        # Check stock count
        stock_count = len(self.phase2.monitors) if hasattr(self.phase2, 'monitors') else 0
        if stock_count >= self.ADAPTIVE_SCAN_THRESHOLD:
            return False
        
        # 🤖 GPT DECISION POINT
        if self.strategic_advisor and getattr(self.config, 'GPT_ADAPTIVE_SCAN_DECISIONS', True):
            try:
                logger.info("🤖 Consulting GPT: Should we run adaptive scan?")
                
                last_scan_result = self.adaptive_scan_results_history[-1] if self.adaptive_scan_results_history else 0
                market_regime = 'UNKNOWN'
                nifty_change = 0
                
                if hasattr(self, 'intelligent_wrapper') and self.intelligent_wrapper:
                    try:
                        regime = self.intelligent_wrapper.get_market_regime()
                        market_regime = regime.value if hasattr(regime, 'value') else str(regime)
                    except:
                        pass
                
                context = {
                    'current_time': current_time.strftime('%H:%M'),
                    'stocks_monitored': stock_count,
                    'last_scan_time': self.last_adaptive_scan.strftime('%H:%M'),
                    'last_scan_result': last_scan_result,
                    'recent_scan_results': self.adaptive_scan_results_history[-5:],
                    'market_regime': market_regime,
                    'nifty_change': nifty_change,
                    'api_calls_remaining': 'UNLIMITED'
                }
                
                decision = self.strategic_advisor.should_run_adaptive_scan(context)
                
                # ✅ FIX v4.3.2: Update timestamp when GPT is CONSULTED (not just when scan runs)
                # This prevents spam calls when GPT fails or returns low confidence
                self.last_adaptive_scan = now
                
                logger.info(f"🤖 GPT Decision: {'SCAN' if decision['should_scan'] else 'SKIP'}")
                logger.info(f"   Confidence: {decision['confidence']}%")
                
                # ═══ SHARE MARKET SENTIMENT WITH PHASE 4 ═══
                self._share_market_sentiment_with_phase4(decision, source='adaptive_scan')

                # v5.6: Share market regime with Phase 3 for entry sizing
                if (self.phase3 and hasattr(self.phase3, 'update_market_regime')
                        and getattr(self.config, 'MARKET_REGIME_ENABLED', True)):
                    scan_outlook = decision.get('market_outlook', decision.get('outlook', 'NEUTRAL'))
                    self.phase3.update_market_regime(scan_outlook, decision.get('confidence', 0))

                # v5.6: Telegram message for adaptive scan decision (Fix B)
                if self.telegram:
                    scan_outlook = decision.get('market_outlook', decision.get('outlook', 'NEUTRAL'))
                    scan_action = "SCAN ✅" if decision['should_scan'] else "SKIP ❌"
                    scan_reasoning = decision.get('reasoning', '')[:120]
                    scan_mult = {'BULLISH': '1.0x', 'NEUTRAL': '0.85x', 'MIXED': '0.6x',
                                 'BEARISH': '0.4x', 'DEFENSIVE': 'BLOCKED'}.get(
                                     scan_outlook.upper(), '0.85x')
                    self.telegram.send_message(
                        f"🤖 SCAN DECISION\n\n"
                        f"Decision: {scan_action} ({decision.get('confidence', 0)}%)\n"
                        f"Market: {scan_outlook}\n"
                        f"📝 {scan_reasoning}\n\n"
                        f"📊 Entry Mode: {scan_mult} sizing"
                    )

                return decision['should_scan'] and decision['confidence'] >= 60
                
            except Exception as e:
                logger.error(f"❌ GPT scan decision failed: {e}")
                # ✅ FIX v4.3.2: Also update timestamp on failure to prevent spam
                self.last_adaptive_scan = now
                return stock_count < self.ADAPTIVE_SCAN_THRESHOLD
        else:
            return stock_count < self.ADAPTIVE_SCAN_THRESHOLD

    def _execute_adaptive_scan(self):
        """
        ✅ v3.2.0 NEW: Execute adaptive Phase 1 scan
        
        Runs Phase 1 stock selection when we have < 3 stocks.
        This ensures we don't miss opportunities that develop
        after the scheduled scans.
        """
        now = datetime.now()
        self.last_adaptive_scan = now

        # Track result for GPT
        stocks_found = len(self.phase2.monitors) if hasattr(self.phase2, 'monitors') else 0
        self.adaptive_scan_results_history.append(stocks_found)
        if len(self.adaptive_scan_results_history) > 10:
            self.adaptive_scan_results_history = self.adaptive_scan_results_history[-10:]
        self.adaptive_scan_count += 1
        
        current_stocks = len(self.phase2.monitors) if self.phase2 else 0
        
        logger.info("")
        logger.info("=" * 80)
        logger.info(f"🔍 ADAPTIVE SCAN #{self.adaptive_scan_count} TRIGGERED")
        logger.info(f"   Reason: Only {current_stocks}/{self.ADAPTIVE_SCAN_THRESHOLD} stocks monitored")
        logger.info(f"   Time: {now.strftime('%H:%M:%S')}")
        logger.info("=" * 80)
        logger.info("")
        
        # Execute Phase 1 scan
        label = f"adaptive_scan_{self.adaptive_scan_count}"
        description = f"Adaptive Scan #{self.adaptive_scan_count} (&lt; {self.ADAPTIVE_SCAN_THRESHOLD} stocks)"
        
        self._execute_phase1_interrupt(label, description)
    
    
    def _should_run_phase2(self) -> bool:
        """Check if Phase 2 should run"""
        if self.interrupt_running:
            return False

        if not self.phase2:
            return False

        # v5.4.1: Block new CNC monitoring during MIS takeover
        if self._is_mis_active():
            return False

        elapsed = (datetime.now() - self.last_phase2_update).total_seconds()
        return elapsed >= self.PHASE2_INTERVAL
    
    
    def _handle_market_close(self):
        """Handle end-of-day procedures"""
        if self.shutdown_initiated:
            return
        
        logger.info("")
        logger.info("=" * 80)
        logger.info("MARKET CLOSE: Initiating shutdown")
        logger.info("=" * 80)
        
        self.shutdown_initiated = True
        
        # ═══════════════════════════════════════════════════════════════════
        # 🛫 PHASE 4 MARKET CLOSE (v4.3 - Priority if available!)
        # ═══════════════════════════════════════════════════════════════════
        
        if self.phase4:
            try:
                logger.info("🛫 Phase 4 handling market close...")
                self.phase4.handle_market_close()
            except Exception as e:
                logger.error(f"Phase 4 market close failed: {e}")
                # Fallback to Phase 3
                if self.phase3 and self.phase3.has_open_positions():
                    logger.info("Falling back to Phase 3 for position close...")
                    self.phase3.close_all_positions(reason="MARKET_CLOSE")
        elif self.phase3 and self.phase3.has_open_positions():
            # Fallback: Close any open positions
            logger.info("Closing open positions...")
            self.phase3.close_all_positions(reason="MARKET_CLOSE")

        # v6.0: Phase 6 Options Advisory — EOD close + daily summary
        if self.phase6:
            try:
                self.phase6.force_close_all_eod()
                notify_summary = getattr(self.config, 'PH6_NOTIFY_DAILY_SUMMARY', True)
                if notify_summary:
                    summary = self.phase6.generate_daily_summary()
                    if summary and self.telegram:
                        self.telegram.send_message(summary)
                self.phase6.reset_daily()
            except Exception as e:
                logger.error(f"Phase 6 EOD error: {e}")

        # v1.0.0: ORB Advisory — clear IB/compression state for next trading day
        if self.orb_advisory:
            try:
                self.orb_advisory.reset_daily()
                logger.info("[OK] ORB Advisory: Daily state cleared")
            except Exception as e:
                logger.error(f"ORB Advisory reset_daily error: {e}")

        # 🔷 PH5A v2 Sniper — daily reset (v5.9.0: independent mode)
        self.ph5a_scan_complete = False
        self.ph5a_done = False
        self._ph5a_started_today = False
        self._ph5a_last_scan_time = None
        self._ph5a_hunting = False
        self._ph5a_scan_count = 0

        # v5.4.0: Phase 5A PVAT Scanner — clear levels, states, trade flag
        if self.phase5a:
            try:
                self.phase5a.reset_daily()
                logger.info("[OK] Phase 5A PVAT Scanner: Daily state cleared")
            except Exception as e:
                logger.error(f"Phase 5A PVAT reset_daily error: {e}")

        # v5.4.0: Send structured daily trading summary
        if self.telegram:
            try:
                # Gather stats from starvation prevention + blackbox
                trades_today = 0
                total_pnl = 0.0
                winners = 0
                losers = 0
                signals_seen = 0
                stocks_monitored = 0
                phase5_trades = 0

                if self.starvation_prevention:
                    sp_status = self.starvation_prevention.get_status()
                    trades_today = sp_status.get('trades_today', 0)
                    signals_seen = sp_status.get('signals_seen', 0)

                if self.blackbox:
                    bb_stats = getattr(self.blackbox, 'stats', {})
                    trades_today = max(trades_today, bb_stats.get('trades_executed_count', 0))
                    stocks_monitored = len(getattr(self.blackbox, 'stocks_monitored', set()))
                    # Count winners/losers from phase3_trades
                    for t in getattr(self.blackbox, 'phase3_trades', []):
                        pnl = t.get('details', {}).get('pnl', 0)
                        if t.get('action') in ('EXIT', 'SELL', 'CLOSE'):
                            total_pnl += pnl
                            if pnl >= 0:
                                winners += 1
                            else:
                                losers += 1

                open_positions = self.get_open_position_count()

                if hasattr(self.telegram, 'notify_daily_trading_summary'):
                    self.telegram.notify_daily_trading_summary(
                        trades_today=trades_today,
                        total_pnl=total_pnl,
                        winners=winners,
                        losers=losers,
                        open_positions=open_positions,
                        phase5_trades=phase5_trades,
                        signals_seen=signals_seen,
                        stocks_monitored=stocks_monitored
                    )
                else:
                    self.telegram.send_message(
                        f"🔔 MARKET CLOSED\n\nSystem shutting down for the day."
                    )
            except Exception as e:
                logger.debug(f"Daily summary notification failed: {e}")
                self.telegram.send_message(
                    f"🔔 MARKET CLOSED\n\nSystem shutting down for the day."
                )

        # v1.0.0: Phase 9 AI Fund Manager — EOD Review
        if (self.phase9 and not self.phase9._eod_review_done
                and getattr(self.config, 'PH9_EOD_REVIEW_ENABLED', False)):
            try:
                logger.info("🧠 Triggering Phase 9 EOD Review...")
                # v1.4.0: Source EOD data properly instead of relying on scope variables
                _eod_pnl = 0.0
                _eod_trades = 0
                _eod_wins = 0
                _eod_losses = 0
                _trade_list = []

                # Primary: Phase 9's own P&L tracking (updated after every exit via update_daily_pnl)
                if self.phase9:
                    _eod_pnl   = self.phase9.daily_pnl
                    _eod_trades = self.phase9.trades_today

                # Build trade list from blackbox
                if self.blackbox:
                    try:
                        for t in getattr(self.blackbox, 'phase3_trades', []) or []:
                            if t.get('action') in ('EXIT', 'SELL', 'CLOSE'):
                                _pnl_val = float(t.get('details', {}).get('pnl', 0) or 0)
                                _trade_list.append({
                                    'symbol':      t.get('symbol', '?'),
                                    'direction':   t.get('details', {}).get('direction', '?'),
                                    'pnl':         _pnl_val,
                                    'pnl_pct':     float(t.get('details', {}).get('pnl_pct', 0) or 0),
                                    'exit_reason': t.get('details', {}).get('reason', '?'),
                                    'source':      t.get('details', {}).get('source', '?'),
                                })
                                if _pnl_val > 0:
                                    _eod_wins += 1
                                else:
                                    _eod_losses += 1
                    except Exception as _bl_e:
                        logger.debug(f"EOD blackbox parse failed: {_bl_e}")

                _eod_win_rate = (_eod_wins / max(1, _eod_wins + _eod_losses) * 100) if (_eod_wins + _eod_losses) > 0 else 0

                day_summary = {
                    'total_pnl':   round(_eod_pnl, 2),
                    'trade_count': _eod_trades or len(_trade_list),
                    'win_rate':    round(_eod_win_rate, 1),
                    'wins':        _eod_wins,
                    'losses':      _eod_losses,
                    'trades':      _trade_list,
                    'missed_opportunities': [],
                    'portfolio': {
                        'positions': dict(self._central_positions)
                    }
                }
                self.phase9.eod_review(day_summary)
                logger.info("✅ Phase 9 EOD Review complete")

                # v1.4.0: Apply PH8 watchlist additions from EOD review
                _eod_wl = getattr(self.phase9, 'todays_ph8_watchlist_add', [])
                if _eod_wl and self.phase8 and hasattr(self.phase8, 'add_to_watchlist'):
                    for _sym in _eod_wl:
                        try:
                            self.phase8.add_to_watchlist(_sym)
                            logger.info(f"🧠 PH9→PH8 EOD: Added {_sym} to watchlist")
                        except Exception as _we:
                            logger.debug(f"PH8 watchlist EOD add failed for {_sym}: {_we}")

                # v1.1.0: Weekly review — runs after Friday EOD
                # (weekday()==4 is Friday). Uses Sonnet, ~₹2/week.
                if (datetime.now().weekday() == 4
                        and getattr(self.config, 'PH9_WEEKLY_REVIEW_ENABLED', True)):
                    try:
                        logger.info("🧠 Triggering Phase 9 Weekly Review (Friday)...")
                        # Build compact week summary from blackbox
                        # v1.4.0: Aggregate actual week data from Phase 9 rolling history
                        _week_hist = []
                        if self.phase9 and self.phase9.memory_enabled and self.phase9.rolling_history:
                            _week_hist = self.phase9.rolling_history[-5:]  # up to 5 trading days

                        _week_pnl    = sum(float(h.get('pnl', 0) or 0) for h in _week_hist) + day_summary.get('total_pnl', 0)
                        _week_wins   = sum(int(h.get('wins', 0) or 0)   for h in _week_hist) + _eod_wins
                        _week_losses = sum(int(h.get('losses', 0) or 0) for h in _week_hist) + _eod_losses
                        _week_trades = sum(int(h.get('trades', 0) or 0) for h in _week_hist) + len(_trade_list)

                        _all_week_trades = _trade_list  # today's trades (history only has summary)
                        _best  = max(_all_week_trades, key=lambda t: t.get('pnl', 0), default={})
                        _worst = min(_all_week_trades, key=lambda t: t.get('pnl', 0), default={})

                        # Exit reason breakdown from today
                        _exit_reasons: dict = {}
                        for _t in _all_week_trades:
                            _er = _t.get('exit_reason', 'UNKNOWN')
                            _exit_reasons[_er] = _exit_reasons.get(_er, 0) + 1

                        week_summary = {
                            'week_pnl':     round(_week_pnl, 2),
                            'trades_count': _week_trades,
                            'wins':         _week_wins,
                            'losses':       _week_losses,
                            'best_trade':   _best,
                            'worst_trade':  _worst,
                            'exit_reasons': _exit_reasons,
                            'phase_pnl':    {},
                        }
                        self.phase9.weekly_review(week_summary)
                        logger.info("✅ Phase 9 Weekly Review complete")
                    except Exception as e:
                        logger.error(f"❌ Phase 9 Weekly Review failed: {e}")
            except Exception as e:
                logger.error(f"❌ Phase 9 EOD Review failed: {e}")
                import traceback
                logger.error(traceback.format_exc())
            finally:
                # Always reset Phase 9 daily state so morning briefing fires tomorrow
                try:
                    self.phase9.reset_daily_state()
                    logger.info("[OK] Phase 9: Daily state reset")
                except Exception as e:
                    logger.error(f"Phase 9 reset_daily_state error: {e}")

        # v5.3.5: Finalize blackbox recording for the day
        try:
            if self.blackbox:
                summary_path = self.blackbox.finalize()
                logger.info(f"Blackbox finalized: {summary_path}")
        except Exception as e:
            logger.debug(f"Blackbox finalize failed: {e}")

        logger.info("[OK] Shutdown complete")
    
    
    # ═══════════════════════════════════════════════════════════════════════════
    # 🛫 PHASE 4 SPECIAL TIME CHECKS (v4.3 NEW!)
    # ═══════════════════════════════════════════════════════════════════════════
    
    def _check_phase4_special_times(self):
        """
        Check for Phase 4 special time events.
        
        Called in main loop to handle:
        - 14:30: Landing probability analysis
        - 15:15: MIS cutoff handling
        - 15:25: Final market close preparation
        """
        if not self.phase4:
            return
        
        now = datetime.now()
        current_time = now.strftime("%H:%M")
        
        # Track which events have been processed today
        if not hasattr(self, '_phase4_events_today'):
            self._phase4_events_today = {}
        
        today_str = now.strftime("%Y-%m-%d")
        if self._phase4_events_today.get('date') != today_str:
            self._phase4_events_today = {'date': today_str}
        
        try:
            # ═══════════════════════════════════════════════════════════════
            # 14:30 - LANDING PROBABILITY CHECK
            # ═══════════════════════════════════════════════════════════════
            landing_time = getattr(self.config, 'PHASE4_LANDING_CHECK_TIME', '14:30')
            if current_time >= landing_time and not self._phase4_events_today.get('landing_check'):
                if self.phase4.has_open_positions():
                    logger.info("🛬 14:30 - Running landing probability check...")
                    self.phase4.run_landing_probability_check()
                    self._phase4_events_today['landing_check'] = True
                    
                    if self.telegram:
                        self.telegram.send_message("🛬 Phase 4: Landing probability check complete")
            
            # ═══════════════════════════════════════════════════════════════
            # 15:15 - MIS CUTOFF HANDLING
            # ═══════════════════════════════════════════════════════════════
            mis_time = getattr(self.config, 'PHASE4_MIS_CUTOFF_TIME', '15:15')
            if current_time >= mis_time and not self._phase4_events_today.get('mis_cutoff'):
                if self.phase4.has_open_positions():
                    logger.info("⚠️ 15:15 - MIS cutoff handling...")
                    self.phase4.handle_mis_cutoff()
                    self._phase4_events_today['mis_cutoff'] = True
                    
                    if self.telegram:
                        self.telegram.send_message("⚠️ Phase 4: MIS cutoff handled")
                        
        except Exception as e:
            logger.error(f"Phase 4 special time check failed: {e}")
    
    # ═══════════════════════════════════════════════════════════════════════════
    # PHASE 4 MARKET SENTIMENT SHARING (v4.3 NEW!)
    # ═══════════════════════════════════════════════════════════════════════════
    
    def _share_market_sentiment_with_phase4(self, chatgpt_response: Dict, source: str = 'unknown'):
        """
        Share market sentiment from ChatGPT calls with Phase 4.
        
        Called after any ChatGPT consultation to keep Phase 4 informed
        about current market conditions for exit decisions.
        
        Args:
            chatgpt_response: Response from ChatGPT containing market insights
            source: Where the ChatGPT call originated (entry_review, adaptive_scan, etc.)
        """
        if not self.phase4:
            return
            
        try:
            # Extract market sentiment from ChatGPT response
            sentiment = {
                'timestamp': datetime.now().isoformat(),
                'source': source,
                
                # Try to extract market outlook from various response formats
                'market_outlook': (
                    chatgpt_response.get('market_outlook') or
                    chatgpt_response.get('market_view') or
                    chatgpt_response.get('outlook') or
                    'NEUTRAL'
                ),
                
                'volatility': (
                    chatgpt_response.get('volatility') or
                    chatgpt_response.get('market_volatility') or
                    'NORMAL'
                ),
                
                'risk_level': (
                    chatgpt_response.get('risk_level') or
                    chatgpt_response.get('market_risk') or
                    'MEDIUM'
                ),
                
                'trend_strength': (
                    chatgpt_response.get('trend_strength') or
                    chatgpt_response.get('trend') or
                    'MODERATE'
                ),
                
                # Capture any reasoning or notes
                'notes': (
                    chatgpt_response.get('reasoning') or
                    chatgpt_response.get('notes') or
                    chatgpt_response.get('analysis') or
                    ''
                )[:200],  # Limit to 200 chars
                
                # Raw confidence if available
                'confidence': chatgpt_response.get('confidence', 0)
            }
            
            # Share with Phase 4
            self.phase4.update_market_sentiment(sentiment)
            logger.debug(f"📡 Shared market sentiment with Phase 4 (source: {source})")
            
        except Exception as e:
            logger.warning(f"Could not share sentiment with Phase 4: {e}")
    
    def _auto_load_or_scan_stocks(self):
        """
        ✅ FIX v3.1.1: Auto-load stocks on startup
        
        If starting mid-session (after scheduled interrupts), this ensures
        we have stocks to monitor instead of an empty black box.
        
        Priority:
        1. Try to load existing ACTIVE.json (if fresh from today)
        2. If no file or stale, trigger immediate Phase 1 scan
        3. Log clear diagnostic messages
        """
        now = datetime.now()
        
        logger.info("")
        logger.info("=" * 80)
        logger.info("📋 STARTUP STOCK LOADING (v3.1.1)")
        logger.info("=" * 80)
        
        # Check if monitors are already loaded (shouldn't be, but check anyway)
        current_monitors = len(self.phase2.monitors) if hasattr(self.phase2, 'monitors') else 0
        
        if current_monitors > 0:
            logger.info(f"✅ Already have {current_monitors} monitors loaded")
            return
        
        # Try to load from ACTIVE.json
        try:
            active_file = getattr(self.config, 'ACTIVE_STOCKS_FILE', 'data/ACTIVE.json')
            logger.info(f"📂 Checking for existing stock file: {active_file}")
            
            if os.path.exists(active_file):
                import json
                with open(active_file, 'r') as f:
                    data = json.load(f)
                
                # Check if file is from today
                if 'saved_at' in data:
                    saved_at = datetime.fromisoformat(data['saved_at'])
                    is_today = saved_at.date() == now.date()
                    age_hours = (now - saved_at).total_seconds() / 3600
                    
                    logger.info(f"   └─ File date: {saved_at.strftime('%Y-%m-%d %H:%M')}")
                    logger.info(f"   └─ Age: {age_hours:.1f} hours")
                    
                    # ✅ Accept today's stocks OR yesterday's if before first scan (10:15 AM)
                    # This ensures stocks are loaded even if system starts late
                    accept_stocks = is_today or (age_hours < 24 and now.time() < dt_time(10, 15))
                    
                    if accept_stocks:
                        # Load stocks from file
                        stocks = self.phase2.load_active_stocks()
                        
                        if stocks and len(stocks) > 0:
                            try:
                                # Initialize monitors
                                self.phase2.initialize_monitors(stocks)
                                self.active_stock_count = len(stocks)
                                
                                logger.info("")
                                logger.info(f"✅ AUTO-LOADED {len(stocks)} STOCKS FROM EXISTING FILE")
                                logger.info("")
                                logger.info("Stocks loaded:")
                                
                                # Safe iteration - show only symbol
                                for i, stock in enumerate(stocks[:10], 1):
                                    try:
                                        if isinstance(stock, str):
                                            symbol = stock
                                        elif isinstance(stock, dict):
                                            symbol = stock.get('symbol', 'Unknown')
                                        else:
                                            symbol = str(stock)
                                        logger.info(f"   {i}. {symbol}")
                                    except:
                                        logger.info(f"   {i}. [error]")
                                        
                                if len(stocks) > 10:
                                    logger.info(f"   ... and {len(stocks) - 10} more")
                                
                                if self.telegram:
                                    try:
                                        msg = f"📋 AUTO-LOADED {len(stocks)} STOCKS\n\n"
                                        msg += "From yesterday's scan:\n"
                                        for i, stock in enumerate(stocks[:5], 1):
                                            if isinstance(stock, str):
                                                symbol = stock
                                            elif isinstance(stock, dict):
                                                symbol = stock.get('symbol', 'Unknown')
                                            else:
                                                symbol = str(stock)[:20]  # Truncate if weird format
                                            msg += f"{i}. {symbol}\n"
                                        if len(stocks) > 5:
                                            msg += f"... and {len(stocks)-5} more"
                                        self.telegram.send_message(msg)
                                    except Exception as e:
                                        logger.warning(f"Telegram notification failed: {e}")
                                
                                logger.info("")
                                logger.info("=" * 80)
                                return
                                
                            except Exception as e:
                                logger.error(f"Error initializing monitors: {e}")
                                import traceback
                                logger.error(traceback.format_exc())
                                raise
                        else:
                            logger.warning("   └─ File exists but no valid stocks")
                    else:
                        logger.warning(f"   └─ File is from a previous day (stale)")
            else:
                logger.info("   └─ No existing file found")
                
        except Exception as e:
            logger.warning(f"   └─ Error loading ACTIVE.json: {e}")
        
        # No valid stocks loaded - decide what to do
        logger.info("")
        logger.info("⚠️  NO STOCKS AVAILABLE TO MONITOR")
        logger.info("")
        
        # Check if we should trigger immediate scan
        current_time = now.time()
        market_open = self._is_market_open()
        
        if market_open and getattr(self.config, 'AUTO_SCAN_ON_STARTUP', True):
            # v5.2.0: Don't trigger Phase 1 scan during Phase 5 window
            if self._is_phase5_window():
                logger.info("⏳ Phase 5 window active — delaying Phase 1 scan until 09:50")
                return
            
            # Check if any scheduled scan has been missed
            any_missed = False
            for interrupt in self.interrupt_schedule:
                int_time = dt_time(interrupt['hour'], interrupt['minute'])
                if current_time > int_time and not self.scans_completed[interrupt['label']]:
                    any_missed = True
                    break
            
            if any_missed:
                logger.info("🔍 TRIGGERING IMMEDIATE PHASE 1 SCAN")
                logger.info("   (Scheduled scan was missed)")
                logger.info("")
                
                self._execute_phase1_interrupt(
                    "startup_scan",
                    "Startup Scan (Missed scheduled scan)"
                )
            else:
                logger.info("ℹ️  Waiting for next scheduled scan")
                logger.info("   Next interrupts:")
                for interrupt in self.interrupt_schedule:
                    int_time = dt_time(interrupt['hour'], interrupt['minute'])
                    if current_time < int_time:
                        logger.info(f"   └─ {interrupt['hour']:02d}:{interrupt['minute']:02d} - {interrupt['description']}")
        else:
            if not market_open:
                logger.info("ℹ️  Market not yet open - will scan at scheduled time")
            else:
                logger.info("ℹ️  Auto-scan disabled - waiting for scheduled interrupts")
        
        logger.info("")
        logger.info("=" * 80)
    
    
    # ═══════════════════════════════════════════════════════════════════════════
    # v4.6.0 NEW: ADAPTIVE TELEGRAM + BOT COMMANDS + SYSTEM HEALTH
    # ═══════════════════════════════════════════════════════════════════════════
    
    def _collect_phase2_snapshot(self) -> Dict:
        """
        Collect current Phase 2 state into a snapshot dict.
        Used by adaptive telegram to detect changes and format messages.
        """
        snapshot = {
            'stocks': {},
            'positions': self.get_open_position_count(),
            'capital_available': 0,
            'capital_deployed': 0,
            'nifty_filter_blocked': False,
            'cycle_number': self.phase2_cycle_count,
        }
        
        # Capital info
        if self.capital_manager:
            snapshot['capital_available'] = getattr(self.capital_manager, 'capital_available', 0)
            snapshot['capital_deployed'] = getattr(self.capital_manager, 'deployed_capital', 0)
        
        # Stock monitor data
        if self.phase2 and hasattr(self.phase2, 'monitors'):
            for monitor in self.phase2.monitors:
                symbol = getattr(monitor, 'symbol', 'UNKNOWN')
                rsi = getattr(monitor, 'current_rsi', None)
                state = getattr(monitor, 'rsi_state', 'UNKNOWN')
                
                # Check for blocks
                blocked_by = ''
                if hasattr(monitor, '_blocked_signals'):
                    # v4.5.5: blocked signal tracking
                    blocked = getattr(monitor, '_blocked_signals', {})
                    if blocked:
                        # Get most recent block reason
                        for sym_key, block_info in blocked.items():
                            if sym_key == symbol or not blocked_by:
                                blocked_by = block_info.get('reason', '')
                
                # Adaptive RSI threshold
                threshold = None
                if hasattr(monitor, 'adaptive_rsi') and monitor.adaptive_rsi:
                    threshold = getattr(monitor.adaptive_rsi, 'current_threshold', None)
                elif hasattr(monitor, 'rsi_bounce_level'):
                    threshold = getattr(monitor, 'rsi_bounce_level', None)
                
                snapshot['stocks'][symbol] = {
                    'rsi': rsi,
                    'state': state,
                    'blocked_by': blocked_by,
                    'threshold': threshold,
                }
        
        # NIFTY filter state
        if self.phase2 and hasattr(self.phase2, '_nifty_filter_blocked'):
            snapshot['nifty_filter_blocked'] = getattr(self.phase2, '_nifty_filter_blocked', False)
        
        return snapshot
    
    def _collect_health_info(self) -> Dict:
        """
        Collect system health info for the health report.
        Combines system metrics with trading system status.
        """
        info = {}
        
        # WebSocket status
        if self.health_monitor:
            try:
                ws_connected = getattr(self.health_monitor, 'is_connected', True)
                info['websocket_status'] = 'CONNECTED' if ws_connected else 'DISCONNECTED'
            except Exception:
                info['websocket_status'] = 'UNKNOWN'
        
        # Kite API status - try a lightweight call
        try:
            # Check if kite session is valid
            if self.kite:
                info['kite_api_status'] = 'OK'
            else:
                info['kite_api_status'] = 'ERROR'
        except Exception:
            info['kite_api_status'] = 'ERROR'
        
        # GPT API status
        if self.strategic_advisor:
            info['gpt_api_status'] = 'OK'
        else:
            info['gpt_api_status'] = 'DISABLED'
        
        # Trading state
        info['phase2_status'] = 'Active' if self._is_entry_window_open() else 'Monitoring'
        info['phase2_cycle'] = self.phase2_cycle_count
        info['positions_count'] = self.get_open_position_count()
        info['monitored_stocks'] = len(self.phase2.monitors) if self.phase2 and hasattr(self.phase2, 'monitors') else 0
        
        if self.capital_manager:
            info['capital_available'] = getattr(self.capital_manager, 'capital_available', 0)
            info['capital_deployed'] = getattr(self.capital_manager, 'deployed_capital', 0)
        
        return info
    
    def _handle_telegram_commands(self):
        """
        Process any pending commands from the Telegram bot listener.
        Called from the main event loop.
        """
        if not self.telegram or not hasattr(self.telegram, 'get_pending_commands'):
            return
        
        commands = self.telegram.get_pending_commands()
        
        for cmd in commands:
            command = cmd.get('command', '')
            
            try:
                if command == 'freq':
                    new_freq = cmd.get('value', 5)
                    self.PHASE2_INTERVAL = new_freq * 60  # Convert minutes to seconds
                    logger.info(f"📱 CMD: Phase 2 interval changed to {new_freq} min ({self.PHASE2_INTERVAL}s)")
                
                elif command == 'status':
                    # Send system health immediately
                    health_info = self._collect_health_info()
                    self.telegram.send_system_health(extra_info=health_info)
                    logger.info("📱 CMD: System health sent on demand")
                
                elif command == 'stocks':
                    # Send current stock status
                    snapshot = self._collect_phase2_snapshot()
                    self.telegram.send_phase2_adaptive_update(snapshot, self.config)
                    logger.info("📱 CMD: Stock status sent on demand")
                
                elif command == 'capital':
                    # Send capital breakdown
                    if self.capital_manager:
                        avail = getattr(self.capital_manager, 'capital_available', 0)
                        deployed = getattr(self.capital_manager, 'deployed_capital', 0)
                        total = getattr(self.capital_manager, 'total_capital', 0)
                        positions = self.get_open_position_count()
                        
                        msg = f"""💰 <b>Capital Status</b> │ {datetime.now().strftime('%I:%M %p')}
─────────────────────
Total Capital: ₹{total:,.0f}
Available: ₹{avail:,.0f}
Deployed: ₹{deployed:,.0f}
Positions: {positions}"""
                        self.telegram.send_message(msg)
                    else:
                        self.telegram.send_message("💰 Capital Manager not available")
                    logger.info("📱 CMD: Capital status sent on demand")
                
                elif command == 'quiet':
                    logger.info("📱 CMD: Quiet mode enabled")
                
                elif command == 'loud':
                    logger.info("📱 CMD: Loud mode enabled")
                
                elif command == 'scan':
                    # Set flag for Phase 1 scan on next cycle
                    self._scan_requested_by_user = True
                    logger.info("📱 CMD: Phase 1 scan requested by user")
                
                elif command == 'gap':
                    # v4.9.0 - Phase 5 Init Fix NEW: Gap strategy commands
                    sub_cmd = cmd.get('sub_command', 'status')
                    args = cmd.get('args', [])
                    
                    if self.phase5:
                        response = self.phase5.handle_telegram_command(sub_cmd, args)
                        self.telegram.send_message(response)
                        logger.info(f"📱 CMD: Gap command '{sub_cmd}' processed")
                    else:
                        self.telegram.send_message(
                            "❌ Phase 5 Gap Strategy not available.\n\n"
                            "Check if phase5_intraday_engine.py is installed and "
                            "GAP_STRATEGY_ENABLED=True in config.py"
                        )
                        logger.warning("📱 CMD: Gap command received but Phase 5 not available")

                elif command == 'ph5a':
                    # v5.5.0 NEW: PH5A Sniper commands (on/off/status)
                    sub_cmd = cmd.get('sub_command', 'status')

                    if sub_cmd == 'off':
                        self.config.PH5A_SNIPER_ENABLED = False
                        msg = (
                            "🔴 PH5A Sniper DISABLED\n\n"
                            "• No new sniper scans or entries\n"
                            "• Existing positions managed by Phase 4\n"
                            "• Phase 1/2/3/4 running normally\n"
                            "• Send /ph5a on to re-enable"
                        )
                        self.telegram.send_message(msg)
                        logger.info("📱 CMD: PH5A Sniper DISABLED by user")

                    elif sub_cmd == 'on':
                        self.config.PH5A_SNIPER_ENABLED = True
                        # v5.9.0: Reset to fresh state — auto-fires on next loop cycle
                        self._ph5a_started_today = False
                        self._ph5a_hunting = False
                        self.ph5a_scan_complete = False
                        self.ph5a_done = False
                        self._ph5a_scan_count = 0
                        # Initialize PH5A if not already running
                        if not self.phase5a and PHASE5A_AVAILABLE and self.phase5:
                            try:
                                self.phase5a = Phase5APVAT(
                                    kite=self.kite,
                                    config=self.config,
                                    telegram=self.telegram,
                                    phase4_manager=self.phase4,
                                    capital_manager=self.capital_manager,
                                    chatgpt_advisor=self.strategic_advisor,
                                    phase5_engine=self.phase5,
                                    candlestick_detector=self.pattern_detector
                                )
                                logger.info("📱 CMD: PH5A Sniper initialized via /ph5a on")
                            except Exception as e:
                                self.telegram.send_message(f"❌ PH5A init failed: {e}")
                                logger.error(f"📱 CMD: PH5A init via command failed: {e}")

                        scan_done = self.ph5a_scan_complete
                        watch_active = (
                            self.phase5a is not None and
                            not getattr(self.phase5a, 'ph5a_watch_closed', True)
                        )
                        msg = (
                            "🟢 PH5A Sniper ENABLED\n\n"
                            f"• Initialized: {'YES' if self.phase5a else 'NO'}\n"
                            f"• Scan complete: {scan_done}\n"
                            f"• Watch active: {watch_active}\n"
                            "• Will resume on next loop cycle"
                        )
                        self.telegram.send_message(msg)
                        logger.info("📱 CMD: PH5A Sniper ENABLED by user")

                    else:  # status
                        enabled = getattr(self.config, 'PH5A_SNIPER_ENABLED', False)
                        initialized = self.phase5a is not None
                        scan_done = self.ph5a_scan_complete
                        done_today = self.ph5a_done
                        watch_closed = getattr(self.phase5a, 'ph5a_watch_closed', True) if self.phase5a else True
                        pipeline_count = len(getattr(self.phase5a, 'sniper_pipeline', []) or []) if self.phase5a else 0

                        # Build pipeline details
                        pipeline_detail = ""
                        if self.phase5a and hasattr(self.phase5a, 'sniper_pipeline') and self.phase5a.sniper_pipeline:
                            for stock in self.phase5a.sniper_pipeline:
                                sym = getattr(stock, 'symbol', '?')
                                score = getattr(stock, '_elite_score', 0)
                                triggered = getattr(stock, 'triggered', False)
                                direction = getattr(stock, '_sniper_direction', '?')
                                status_icon = "✅" if triggered else "⏳"
                                pipeline_detail += f"\n  {status_icon} {sym}: {score:.0f}pts ({direction})"

                        # PMBI bias info
                        pmbi_info = ""
                        if hasattr(self, 'market_bias') and self.market_bias:
                            mb = self.market_bias
                            pmbi_info = f"\n\n🧠 PMBI: {mb.get('direction', '?')} ({mb.get('confidence', 0)}%)"

                        msg = (
                            f"🔷 PH5A SNIPER STATUS\n\n"
                            f"• Enabled: {'🟢 YES' if enabled else '🔴 NO'}\n"
                            f"• Initialized: {'YES' if initialized else 'NO'}\n"
                            f"• Scan complete: {scan_done}\n"
                            f"• Watch closed: {watch_closed}\n"
                            f"• Done today: {done_today}\n"
                            f"• Pipeline: {pipeline_count} stocks"
                            f"{pipeline_detail}"
                            f"{pmbi_info}\n\n"
                            f"Send /ph5a on or /ph5a off to toggle"
                        )
                        self.telegram.send_message(msg)
                        logger.info("📱 CMD: PH5A status sent")

                elif command == 'shield':  # v5.5.0
                    if self.phase4:
                        self.phase4._handle_shield_status()
                    else:
                        self.telegram.send_message("Phase 4 not available")

                elif command == 'shutdown':
                    if cmd.get('confirmed'):
                        logger.critical("USER-INITIATED SHUTDOWN")

                        # 1. Close MIS positions (same as market close)
                        self._handle_market_close()

                        # 2. Set flag to break main loop
                        self._user_shutdown = True

                        # 3. Final Telegram — CNC holdings summary
                        cnc_summary = ""
                        if self.phase4:
                            tier3 = self.phase4._get_tier3_positions()
                            for sym, pos in tier3.items():
                                entry = pos.get('entry_price', 0)
                                cnc_summary += f"\n  - {sym} (Ph8 Tier 3, entry {entry:.2f})"
                            # Also show other CNC
                            tier2 = self.phase4._get_tier2_positions()
                            for sym, pos in tier2.items():
                                if pos.get('product') == 'CNC':
                                    cnc_summary += f"\n  - {sym} (CNC)"

                        if self.telegram:
                            self.telegram.send_critical(
                                f"<b>SYSTEM OFFLINE</b>\n\n"
                                f"All MIS positions closed.\n"
                                f"CNC holdings preserved:{cnc_summary or ' none'}\n\n"
                                f"To restart: run main_orchestrator.py"
                            )

                elif command == 'chain':
                    sub_cmd = cmd.get('sub_command', 'status')

                    if sub_cmd == 'status':
                        # Build status of all chains
                        chains = [
                            ("Ph1->Ph2->Ph3->Ph4 (V-Recovery)",
                             getattr(self.config, 'ENABLE_PHASE2', True) and getattr(self.config, 'ENABLE_PHASE3', True)),
                            ("Ph5 (Gap Strategy)",
                             getattr(self.config, 'GAP_STRATEGY_ENABLED', False)),
                            ("Ph5A (PVAT Sniper)",
                             getattr(self.config, 'PH5A_SNIPER_ENABLED', False)),
                            ("Ph7 (MCX Commodities)",
                             getattr(self.config, 'MCX_ENABLED', False)),
                            ("Ph8 (Momentum)",
                             getattr(self.config, 'ENABLE_PH8', False)),
                        ]

                        status_lines = ["<b>TRADING CHAIN STATUS</b>\n"]
                        for label, enabled in chains:
                            icon = "ON" if enabled else "OFF"
                            status_lines.append(f"  [{icon}] {label}")

                        # Brain directive blocks
                        _blocks = []
                        if self._ph4_brain_defensive: _blocks.append("PH4=DEFENSIVE")
                        if self._ph5_brain_skip:      _blocks.append("PH5=SKIP")
                        if self._ph5a_brain_pause:    _blocks.append("PH5A=PAUSE")
                        if self._ph6_brain_hold:      _blocks.append("PH6=HOLD")
                        _nifty_bl = self.phase2 and getattr(self.phase2, '_nifty_filter_blocked', False)
                        if _nifty_bl:                 _blocks.append("NIFTY FILTER")
                        status_lines.append("")
                        if _blocks:
                            status_lines.append(f"<b>⛔ Active Blocks:</b> {' | '.join(_blocks)}")
                        else:
                            status_lines.append("<b>🟢 No active blocks</b>")

                        # Add position counts
                        if self.phase4:
                            t1 = len(self.phase4._get_tier1_positions())
                            t2 = len(self.phase4._get_tier2_positions())
                            t3 = len(self.phase4._get_tier3_positions())
                            status_lines.append("")
                            status_lines.append("<b>Open Positions:</b>")
                            status_lines.append(f"  Tier 1 (MIS): {t1}")
                            status_lines.append(f"  Tier 2 (CNC): {t2}")
                            status_lines.append(f"  Tier 3 (Ph8): {t3}")

                        if self.telegram:
                            self.telegram.send_message("\n".join(status_lines))

                    elif sub_cmd == 'toggle':
                        chain = cmd.get('chain', '')
                        action = cmd.get('action', '')
                        enabled = (action == 'on')

                        flag_map = {
                            'ph1': [('ENABLE_PHASE2', enabled), ('ENABLE_PHASE3', enabled)],
                            'ph5': [('GAP_STRATEGY_ENABLED', enabled)],
                            'ph5a': [('PH5A_SNIPER_ENABLED', enabled)],
                            'ph7': [('MCX_ENABLED', enabled)],
                            'ph8': [('ENABLE_PH8', enabled)],
                        }

                        flags = flag_map.get(chain, [])
                        for flag_name, value in flags:
                            setattr(self.config, flag_name, value)
                            logger.info(f"CMD: {flag_name} = {value}")

                        chain_label = {
                            'ph1': 'V-Recovery (Ph1->Ph2->Ph3->Ph4)',
                            'ph5': 'Gap Strategy (Ph5)',
                            'ph5a': 'PVAT Sniper (Ph5A)',
                            'ph7': 'MCX Commodities (Ph7)',
                            'ph8': 'Momentum (Ph8)',
                        }.get(chain, chain)

                        state_label = 'ENABLED' if enabled else 'DISABLED'
                        msg = f"<b>{chain_label}: {state_label}</b>"

                        if not enabled and chain == 'ph8' and self.phase4:
                            t3 = self.phase4.get_tier3_position_count()
                            if t3 > 0:
                                msg += (f"\n\n{t3} Tier 3 position(s) still active!"
                                        "\nThey will continue being monitored until exit."
                                        "\nNew Ph8 scans are disabled.")

                        if self.telegram:
                            self.telegram.send_message(msg)

                    elif sub_cmd in ('all_on', 'all_off'):
                        enabled = (sub_cmd == 'all_on')

                        all_flags = [
                            'ENABLE_PHASE2', 'ENABLE_PHASE3',
                            'GAP_STRATEGY_ENABLED',
                            'PH5A_SNIPER_ENABLED',
                            'ENABLE_PH8',
                        ]

                        for flag in all_flags:
                            setattr(self.config, flag, enabled)
                            logger.info(f"CMD: {flag} = {enabled}")

                        action_word = "ENABLED" if enabled else "DISABLED"
                        msg = f"<b>ALL CHAINS {action_word}</b>\n\n"
                        for flag in all_flags:
                            msg += f"  {flag} = {enabled}\n"

                        if not enabled:
                            msg += ("\nExisting positions continue being monitored."
                                    "\nNo NEW trades will be placed."
                                    "\n\nSend /chain all on to resume.")

                        if self.telegram:
                            self.telegram.send_message(msg)

                    elif sub_cmd == 'detail':
                        chain = cmd.get('chain', '')
                        # Redirect known chains to their specific handler
                        if chain == 'ph8':
                            self.command_queue.put({'command': 'ph8', 'sub_command': 'status'})
                        else:
                            # Generic: show the chain's config flags
                            flag_map = {
                                'ph1': ['ENABLE_PHASE2', 'ENABLE_PHASE3'],
                                'ph5': ['GAP_STRATEGY_ENABLED'],
                                'ph5a': ['PH5A_SNIPER_ENABLED'],
                                'ph7': ['MCX_ENABLED'],
                                'ph8': ['ENABLE_PH8'],
                            }
                            flags = flag_map.get(chain, [])
                            lines = [f"<b>{chain.upper()} Detail</b>\n"]
                            for f in flags:
                                val = getattr(self.config, f, 'N/A')
                                lines.append(f"  {f} = {val}")
                            if self.telegram:
                                self.telegram.send_message("\n".join(lines))

                elif command == 'ph8':
                    sub_cmd = cmd.get('sub_command', 'status')

                    if sub_cmd in ('on', 'off'):
                        enabled = (sub_cmd == 'on')
                        self.config.ENABLE_PH8 = enabled
                        state_label = 'ENABLED' if enabled else 'DISABLED'
                        if self.telegram:
                            self.telegram.send_message(f"Phase 8 Momentum: {state_label}")
                        logger.info(f"CMD: ENABLE_PH8 = {enabled}")

                    else:  # status
                        enabled = getattr(self.config, 'ENABLE_PH8', False)
                        status = "ENABLED" if enabled else "DISABLED"

                        msg = f"<b>PHASE 8 MOMENTUM STATUS</b>\n\n"
                        msg += f"Status: {status}\n"

                        if self.phase4:
                            tier3 = self.phase4._get_tier3_positions()
                            max_c = getattr(self.config, 'PH8_MAX_CONCURRENT', 2)
                            msg += f"Tier 3 Positions: {len(tier3)}/{max_c}\n"

                            if tier3:
                                msg += "\n<b>Active Positions:</b>\n"
                                for sym, pos in tier3.items():
                                    entry = pos.get('entry_price', 0)
                                    peak = pos.get('peak_price', entry)
                                    # Try to get fresh quote
                                    try:
                                        q = self.kite.quote([f"NSE:{sym}"])
                                        current = q.get(f"NSE:{sym}", {}).get('last_price', peak)
                                    except Exception:
                                        current = peak
                                    pnl_pct = ((current - entry) / entry * 100) if entry > 0 else 0
                                    hold = 0
                                    if pos.get('entry_date'):
                                        try:
                                            from datetime import date as dcls
                                            ed = dcls.fromisoformat(pos['entry_date'])
                                            hold = (dcls.today() - ed).days
                                        except Exception:
                                            pass
                                    tcas = "Active" if pos.get('tcas_active') else "Dormant"
                                    shadow = "Yes" if pos.get('shadow_active') else "No"

                                    msg += f"\n  <b>{sym}</b>\n"
                                    msg += f"    Entry: {entry:.2f} | Now: {current:.2f}\n"
                                    msg += f"    P&L: {pnl_pct:+.2f}% | Hold: {hold}d\n"
                                    msg += f"    TCAS: {tcas} | Shadow: {shadow}\n"

                            # Next scheduled action
                            weekday = datetime.now().weekday()
                            if weekday == 2:
                                msg += "\nTODAY: Wednesday — Scan day"
                            elif weekday == 0:
                                msg += "\nTODAY: Monday — TCAS activates at 10:00"
                            elif weekday == 1:
                                msg += "\nTODAY: Tuesday — EXIT benchmark day"
                            elif weekday in (3, 4):
                                msg += f"\nNext action: Monday TCAS"
                            else:
                                msg += f"\nNext action: Wednesday scan"

                        if self.telegram:
                            self.telegram.send_message(msg)

                # ── v1.4.0: Trade Confirmation Gate replies ──────────────────────
                elif command == 'trade_done':
                    # User manually placed the trade — discard pending entry, notify done
                    symbol = cmd.get('symbol', '').upper()
                    if symbol == 'ALL':
                        count = len(self._pending_confirmations)
                        self._pending_confirmations.clear()
                        if self.telegram:
                            self.telegram.send_message(
                                f"✅ <b>All {count} pending trade(s) marked as executed</b>\n"
                                f"Remember to set your own stop-loss and target on Kite."
                            )
                        logger.info(f"📱 CMD: ALL pending confirmations cleared (trade_done)")
                    elif symbol in self._pending_confirmations:
                        entry = self._pending_confirmations.pop(symbol)
                        elapsed = (datetime.now() - entry['registered_at']).total_seconds()
                        logger.info(f"📱 CMD: {symbol} confirmed as manually executed ({elapsed:.0f}s)")
                        if self.telegram:
                            self.telegram.send_message(
                                f"✅ <b>{symbol} — Trade Confirmed</b>\n"
                                f"Position registered. Phase 4 will begin exit monitoring.\n"
                                f"Confirm your stop-loss and target are set on Kite."
                            )
                        # Mark as traded today so duplicate prevention kicks in
                        if self.phase2:
                            self.phase2.traded_today.add(symbol)
                    else:
                        if self.telegram:
                            pending_list = ', '.join(self._pending_confirmations.keys()) or 'none'
                            self.telegram.send_message(
                                f"⚠️ No pending trade for <b>{symbol}</b>\n"
                                f"Pending: {pending_list}"
                            )

                elif command == 'trade_skip':
                    # User chose not to take the trade
                    symbol = cmd.get('symbol', '').upper()
                    if symbol == 'ALL':
                        count = len(self._pending_confirmations)
                        self._pending_confirmations.clear()
                        if self.telegram:
                            self.telegram.send_message(
                                f"⏭️ <b>All {count} pending trade(s) skipped</b>\n"
                                f"No positions opened."
                            )
                        logger.info(f"📱 CMD: ALL pending confirmations skipped")
                    elif symbol in self._pending_confirmations:
                        self._pending_confirmations.pop(symbol)
                        logger.info(f"📱 CMD: {symbol} trade skipped by user")
                        if self.telegram:
                            self.telegram.send_message(
                                f"⏭️ <b>{symbol} — Trade Skipped</b>\n"
                                f"Signal discarded. No position opened."
                            )
                        # Also block from re-entry today
                        if self.phase2:
                            self.phase2.traded_today.add(symbol)
                    else:
                        if self.telegram:
                            pending_list = ', '.join(self._pending_confirmations.keys()) or 'none'
                            self.telegram.send_message(
                                f"⚠️ No pending trade for <b>{symbol}</b>\n"
                                f"Pending: {pending_list}"
                            )

                elif command == 'ask':
                    # Free-text question / instruction routed to Phase 9 brain
                    question = cmd.get('text', '').strip()
                    if not question:
                        if self.telegram:
                            self.telegram.send_message("❓ Empty question — send any message to talk to the brain.")
                    elif not self.phase9 or not self.phase9.client:
                        if self.telegram:
                            self.telegram.send_message("🔴 Brain unavailable — Claude not initialized.")
                    else:
                        if self.telegram:
                            self.telegram.send_message("🧠 Thinking...")
                        context = self._build_chat_context()
                        result  = self.phase9.chat(question, context)
                        import html as _html
                        answer  = _html.escape(result.get('answer', 'No response.'))
                        dirs    = result.get('directives', {})

                        # Re-propagate if directives changed
                        if dirs:
                            self._apply_phase_directives()
                            self._propagate_briefing_to_phases()
                            change_lines = [f"  {k}: {v}" for k, v in dirs.items()]
                            answer += f"\n\n✅ Applied changes:\n" + '\n'.join(change_lines)

                        if self.telegram:
                            self.telegram.send_message(f"🧠 ALPHA:\n\n{answer}")
                        logger.info(f"🧠 PH9 Chat: {len(dirs)} directive changes applied")

            except Exception as e:
                logger.error(f"CMD error handling '{command}': {e}")

    def _build_chat_context(self) -> dict:
        """Build a live snapshot for Phase 9 chat() — aggregates all relevant system state."""
        from datetime import datetime as _dt
        ctx = {'time': _dt.now().strftime('%H:%M:%S')}

        # VIX and Nifty — fetch live (60s cache)
        try:
            _md = self._get_live_market_data()
            ctx['nifty_change_pct'] = _md.get('nifty_change_pct', 'N/A')
            ctx['vix']              = _md.get('vix', 'N/A')
        except Exception:
            pass

        # Regime and directives from Phase 9
        if self.phase9:
            ctx['regime']           = self.phase9.todays_regime
            ctx['trades_today']     = self.phase9.trades_today
            ctx['daily_pnl']        = self.phase9.daily_pnl

        # Active blocks
        blocks = []
        if self._ph4_brain_defensive: blocks.append('PH4=DEFENSIVE')
        if self._ph5_brain_skip:      blocks.append('PH5=SKIP')
        if self._ph5a_brain_pause:    blocks.append('PH5A=PAUSE')
        if self._ph6_brain_hold:      blocks.append('PH6=HOLD')
        if self.phase2 and getattr(self.phase2, '_nifty_filter_blocked', False):
            blocks.append('NIFTY FILTER')
        ctx['active_blocks'] = blocks

        # Monitored stocks with RSI
        monitors = []
        if self.phase2 and hasattr(self.phase2, 'monitors'):
            for m in self.phase2.monitors[:8]:
                monitors.append({
                    'symbol': getattr(m, 'symbol', '?'),
                    'rsi':    round(getattr(m, 'current_rsi', 0) or 0, 1),
                    'state':  getattr(m, 'state', '?'),
                })
        ctx['monitors'] = monitors

        # Open positions
        positions = []
        for sym, pos in dict(self._central_positions).items():
            positions.append({
                'symbol': sym,
                'pnl':    pos.get('unrealized_pnl', pos.get('pnl', 0)),
                'tier':   pos.get('tier', '?'),
            })
        ctx['open_positions'] = positions

        return ctx

    def _handle_user_scan_request(self):
        """
        If user requested a scan via /scan, execute it.
        Called from the main event loop.
        
        v5.3.3: Warns if Phase 5 window or TIER1 active, but still allows
        user-requested scans (user explicitly asked).
        """
        if not self._scan_requested_by_user:
            return
        
        self._scan_requested_by_user = False
        
        now = datetime.now()
        if now.time() < self.MARKET_START or now.time() > self.MARKET_END:
            if self.telegram:
                self.telegram.send_message("⚠️ Market is closed. Scan request ignored.")
            return
        
        # v5.3.3: Warn if Phase 5 window or TIER1 active
        if self._is_phase5_window():
            tier1_active = self.phase4 and hasattr(self.phase4, 'has_tier1_positions') and self.phase4.has_tier1_positions()
            warning = "⚠️ Phase 5 window active" if not self._phase5_run_today else "⚠️ TIER1 MIS position active"
            logger.warning(f"📱 User scan requested during protected window — proceeding with caution")
            if self.telegram:
                self.telegram.send_message(f"{warning} — running scan anyway (user requested). API quota may be affected.")
        
        logger.info("📱 Executing user-requested Phase 1 scan...")
        try:
            self._execute_phase1_interrupt('user_scan', 'User-requested scan via Telegram')
            if self.telegram:
                _blocks = []
                if self._ph4_brain_defensive: _blocks.append("PH4=DEFENSIVE")
                if self._ph5_brain_skip:      _blocks.append("PH5=SKIP")
                if self._ph5a_brain_pause:    _blocks.append("PH5A=PAUSE")
                _nifty_blocked = self.phase2 and getattr(self.phase2, '_nifty_filter_blocked', False)
                if _nifty_blocked:            _blocks.append("NIFTY FILTER")
                _block_note = f"\n⛔ Blocks active: {' | '.join(_blocks)}" if _blocks else "\n🟢 No active blocks."
                self.telegram.send_message(f"✅ User-requested Phase 1 scan completed!{_block_note}")
        except Exception as e:
            logger.error(f"User-requested scan failed: {e}")
            if self.telegram:
                self.telegram.send_message(f"❌ Scan failed: {e}")
    
    def _run_adaptive_phase2_telegram(self, snapshot: Dict):
        """
        After Phase 2 cycle, decide whether to send Telegram update.
        Uses the adaptive frequency system (rule-based + GPT).
        
        Args:
            snapshot: Phase 2 state snapshot from _collect_phase2_snapshot()
        """
        if not self.telegram:
            return
        
        adaptive_enabled = getattr(self.config, 'ADAPTIVE_TELEGRAM_ENABLED', True)
        
        if not adaptive_enabled:
            # Disabled - always send (legacy behavior)
            self.telegram.send_phase2_adaptive_update(snapshot, self.config)
            return
        
        # Ask the adaptive system
        decision = self.telegram.should_send_phase2_update(snapshot, self.config)
        
        if decision['send']:
            if decision['message_type'] == 'quiet_summary':
                self.telegram.send_quiet_summary(snapshot, reason=decision['reason'])
                logger.info(f"📱 Adaptive: Sent quiet summary - {decision['reason']}")
            else:
                self.telegram.send_phase2_adaptive_update(snapshot, self.config)
                logger.info(f"📱 Adaptive: Sent full update - {decision['reason']}")
        else:
            self.telegram.notify_adaptive_skip(decision['reason'])
    
    
    # ═══════════════════════════════════════════════════════════════════════════
    # 🚦 NIFTY HARD GATE — Daily Direction Lock (FIX 1 — PH5A v2 Sniper)
    # ═══════════════════════════════════════════════════════════════════════════

    # ═══════════════════════════════════════════════════════════════════════════
    # v1.3.0: Briefing propagation — push Phase 9 directives to downstream phases
    # ═══════════════════════════════════════════════════════════════════════════

    # ═══════════════════════════════════════════════════════════════════════════
    # v1.4.0: TRADE CONFIRMATION GATE
    # When TRADE_CONFIRMATION_GATE_ENABLED=True, auto-execution is skipped.
    # System registers a pending confirmation and waits for /done or /skip reply.
    # ═══════════════════════════════════════════════════════════════════════════

    def _register_pending_confirmation(self, symbol: str, signal: dict,
                                        source: str = 'SYSTEM', score=None,
                                        direction: str = 'BUY', capital=None):
        """
        Register a signal as awaiting manual confirmation.
        Called instead of execute_signal_realtime() when confirmation gate is on.
        The entry card has already been sent by _send_manual_entry_card().
        """
        timeout_sec = getattr(self.config, 'TRADE_CONFIRMATION_TIMEOUT_SEC', 180)
        deadline    = datetime.now() + timedelta(seconds=timeout_sec)

        self._pending_confirmations[symbol] = {
            'symbol':    symbol,
            'signal':    signal,
            'source':    source,
            'score':     score,
            'direction': direction,
            'capital':   capital,
            'registered_at': datetime.now(),
            'deadline':  deadline,
            'warned':    False,
        }
        deadline_str = deadline.strftime('%H:%M:%S')
        logger.info(f"⏳ Confirmation gate: {symbol} pending manual confirm "
                    f"(deadline {deadline_str} — {timeout_sec}s)")

    def _check_trade_confirmation_timeouts(self):
        """
        Called every main loop cycle.
        Warns and discards pending confirmations that passed their deadline.
        """
        if not self._pending_confirmations:
            return

        now = datetime.now()
        expired = []

        for symbol, entry in list(self._pending_confirmations.items()):
            remaining = (entry['deadline'] - now).total_seconds()

            # 60-second warning (once)
            if not entry.get('warned') and 0 < remaining <= 60:
                entry['warned'] = True
                if self.telegram:
                    try:
                        self.telegram.send_message(
                            f"⚠️ <b>TRADE TIMEOUT WARNING — {symbol}</b>\n"
                            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                            f"You have <b>{int(remaining)}s</b> left to confirm.\n"
                            f"\n"
                            f"Reply /done {symbol} — if you placed the trade\n"
                            f"Reply /skip {symbol} — to discard the trade\n"
                            f"\n"
                            f"No reply → trade DISCARDED at {entry['deadline'].strftime('%H:%M:%S')}"
                        )
                    except Exception as e:
                        logger.debug(f"Timeout warning Telegram failed for {symbol}: {e}")

            # Expired — discard
            if remaining <= 0:
                expired.append(symbol)

        for symbol in expired:
            entry = self._pending_confirmations.pop(symbol, {})
            reg_time = entry.get('registered_at', now)
            elapsed  = (now - reg_time).total_seconds()
            logger.warning(f"⏰ Confirmation gate TIMEOUT: {symbol} — discarded after {elapsed:.0f}s")
            if self.telegram:
                try:
                    self.telegram.send_message(
                        f"⏰ <b>TRADE TIMEOUT — {symbol}</b>\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"No manual confirmation received in time.\n"
                        f"Trade has been <b>DISCARDED</b> — no position opened.\n"
                        f"\n"
                        f"If you already placed the trade on Kite, set your own\n"
                        f"stop-loss and target manually."
                    )
                except Exception as e:
                    logger.debug(f"Timeout discard Telegram failed for {symbol}: {e}")

    # ═══════════════════════════════════════════════════════════════════════════
    # MANUAL TRADE CARDS — proactive Telegram alerts for every signal
    # User can manually execute on Kite if VPN/API fails
    # ═══════════════════════════════════════════════════════════════════════════

    def _send_manual_entry_card(self, symbol: str, direction: str, signal: dict,
                                 score=None, source: str = 'SYSTEM', capital=None):
        """
        Send a proactive Telegram card for every entry signal — BEFORE order attempt.
        Message contains enough detail to manually place the trade on Kite if API fails.

        Called from _run_phase2_cycle() for both intelligent and fallback signals.
        Phase 4's on_position_opened() sends a follow-up GTT card after confirmed fill.
        """
        if not self.telegram:
            return
        try:
            price  = float(signal.get('price',        signal.get('entry_price',   0)) or 0)
            stop   = float(signal.get('stop_price',   signal.get('stop_loss',     0)) or 0)
            target = float(signal.get('target_price', signal.get('target',        0)) or 0)
            qty    = int(  signal.get('quantity',      0) or 0)
            product = str( signal.get('product',      'CNC')).upper()
            now_str = datetime.now().strftime('%H:%M:%S')

            # If qty unknown, estimate from capital
            if qty == 0 and capital and price > 0:
                qty = max(1, int(capital / price))

            # Normalise direction label
            dir_upper = direction.upper() if direction else 'BUY'
            action    = 'BUY'  if dir_upper in ('BUY', 'LONG', 'UP')   else 'SELL'
            exit_act  = 'SELL' if action == 'BUY'                       else 'BUY'

            # Risk / reward context (show only when both stop and target are known)
            risk_block = ''
            if price > 0 and stop > 0 and target > 0 and qty > 0:
                stop_pct   = (stop   - price) / price * 100
                tgt_pct    = (target - price) / price * 100
                risk_amt   = abs(price - stop)   * qty
                reward_amt = abs(target - price) * qty
                rr         = reward_amt / risk_amt if risk_amt > 0 else 0
                risk_block = (
                    f"\nStop    : ₹{stop:,.2f}  ({stop_pct:+.2f}%)"
                    f"\nTarget  : ₹{target:,.2f}  ({tgt_pct:+.2f}%)"
                    f"\nRisk    : ₹{risk_amt:,.0f}  |  R:R 1:{rr:.1f}"
                )

            score_str  = f"  Score: {score:.0f}" if score else ''
            price_str  = f"₹{price:,.2f}" if price > 0 else 'MARKET'
            cap_str    = f"₹{price*qty:,.0f}" if price > 0 and qty > 0 else '—'

            msg = (
                f"📋 SIGNAL FIRED — {symbol}\n"
                f"{'━'*32}\n"
                f"Action  : {action}  |  {product}\n"
                f"Price   : {price_str}  x{qty if qty else '?'}\n"
                f"Capital : {cap_str}\n"
                f"Source  : {source}{score_str}\n"
                f"Time    : {now_str}"
                f"{risk_block}\n"
                f"\n"
                f"{'━'*32}\n"
                f"📌 IF AUTO FAILS — MANUAL STEPS:\n"
                f"1. {action} {symbol} NSE {product}\n"
                f"   {'LIMIT @ ' + price_str if price > 0 else 'MARKET ORDER'}"
                f"{'  x' + str(qty) if qty else ''}\n"
            )
            if stop > 0 and target > 0 and qty > 0:
                # GTT OCO setup hint
                if product == 'CNC':
                    msg += (
                        f"\n"
                        f"2. After fill → GTT OCO on Kite:\n"
                        f"   SL  : Trigger ₹{stop:,.2f} → {exit_act} @ ₹{stop:,.2f}\n"
                        f"   TGT : Trigger ₹{target:,.2f} → {exit_act} @ ₹{target:,.2f}\n"
                        f"   kite.zerodha.com → Orders → GTT"
                    )
                else:
                    msg += (
                        f"\n"
                        f"2. After fill — SL-M order:\n"
                        f"   {exit_act} SL-M Trigger ₹{stop:,.2f}  x{qty}\n"
                        f"3. Target LIMIT order:\n"
                        f"   {exit_act} LIMIT ₹{target:,.2f}  x{qty}"
                    )
            # v1.4.0: Confirmation gate — send with tap buttons when enabled
            gate_enabled = getattr(self.config, 'TRADE_CONFIRMATION_GATE_ENABLED', False)
            if gate_enabled:
                timeout_sec  = getattr(self.config, 'TRADE_CONFIRMATION_TIMEOUT_SEC', 180)
                deadline_str = (datetime.now() + timedelta(seconds=timeout_sec)).strftime('%H:%M:%S')
                msg += (
                    f"\n\n"
                    f"{'━'*32}\n"
                    f"🔔 TAP a button below to confirm:"
                )
                if hasattr(self.telegram, 'send_message_with_buttons'):
                    self.telegram.send_message_with_buttons(
                        msg,
                        [
                            [
                                (f"✅ Done — {symbol}", f"trade_done:{symbol}"),
                                (f"⏭️ Skip — {symbol}", f"trade_skip:{symbol}"),
                            ],
                            [
                                (f"⏰ Deadline: {deadline_str}", f"cmd:status"),
                            ],
                        ]
                    )
                else:
                    # Fallback if buttons not available
                    self.telegram.send_message(msg)
            else:
                self.telegram.send_message(msg)
        except Exception as e:
            logger.debug(f"Manual entry card Telegram failed for {symbol}: {e}")

    # ═══════════════════════════════════════════════════════════════════════════
    # v1.4.0: PHASE DIRECTIVE APPLICATION
    # Reads Phase 9 per-phase directives and gates each phase accordingly.
    # ═══════════════════════════════════════════════════════════════════════════

    @staticmethod
    def _get_vix_tier_params(vix) -> dict:
        """
        v5.6.0: Return VIX-tiered parameters for PH5 gap strategy.
        VIX is intelligence — use it to adjust size and stops, NOT to kill phases.
        Only genuine panic (VIX > 30) justifies a skip.

        Returns dict with keys: size_mult, stop_mult, skip, tier
        """
        try:
            vix = float(vix)
        except (TypeError, ValueError):
            return {'size_mult': 1.0, 'stop_mult': 1.0, 'skip': False, 'tier': 'UNKNOWN'}

        if vix < 15:
            return {'size_mult': 1.00, 'stop_mult': 1.0, 'skip': False, 'tier': 'LOW'}
        elif vix < 20:
            return {'size_mult': 0.75, 'stop_mult': 1.3, 'skip': False, 'tier': 'MODERATE'}
        elif vix < 25:
            return {'size_mult': 0.50, 'stop_mult': 1.5, 'skip': False, 'tier': 'ELEVATED'}
        elif vix < 30:
            return {'size_mult': 0.25, 'stop_mult': 2.0, 'skip': False, 'tier': 'HIGH'}
        else:
            return {'size_mult': 0.00, 'stop_mult': 2.0, 'skip': True,  'tier': 'EXTREME'}

    def _apply_phase_directives(self):
        """
        Read Phase 9's per-phase directives and update local flags that gate
        each phase's execution. Called after morning briefing AND after each heartbeat.
        """
        if not self.phase9 or not self.phase9._morning_briefing_done:
            return

        ph5_dir  = getattr(self.phase9, 'todays_ph5_directive',  'ACTIVE')
        ph5a_dir = getattr(self.phase9, 'todays_ph5a_directive', 'ACTIVE')
        ph4_dir  = getattr(self.phase9, 'todays_ph4_directive',  'NORMAL')
        ph6_dir  = getattr(self.phase9, 'todays_ph6_directive',  'ACTIVE')
        ph8_dir  = getattr(self.phase9, 'todays_ph8_directive',  'HOLD')

        # ── PH5 gate: VIX-tiered override (v5.6.0) ──────────────────────────────
        # VIX is intelligence, not a kill switch.
        # Claude can only enforce SKIP when VIX is genuinely extreme (>30).
        # Below that threshold the system adjusts size + stops and keeps trading.
        prev_ph5_skip = self._ph5_brain_skip

        # Resolve live VIX from Phase 9 cache
        _live_vix_raw = getattr(self.phase9, '_live_vix', 'N/A') if self.phase9 else 'N/A'
        try:
            _live_vix = float(_live_vix_raw)
        except (TypeError, ValueError):
            _live_vix = None

        _vix_tier = self._get_vix_tier_params(_live_vix)
        _vix_label = (
            f"VIX={_live_vix:.1f} ({_vix_tier['tier']})" if _live_vix is not None
            else "VIX=N/A"
        )

        # Override Claude's SKIP unless VIX is truly extreme
        if ph5_dir == 'SKIP' and not _vix_tier['skip']:
            logger.info(
                f"🧠 PH5 SKIP overridden — {_vix_label} is not extreme. "
                f"Running at {_vix_tier['size_mult']:.0%} size, {_vix_tier['stop_mult']:.1f}x stop."
            )
            self._ph5_brain_skip = False
        else:
            self._ph5_brain_skip = _vix_tier['skip'] or (ph5_dir == 'SKIP')

        # Push tier params to PH5 engine so it sizes and widens stops correctly.
        # Priority: PH9 deliberate directives > raw VIX tier.
        # PH9 sets todays_ph5_size_mult/stop_mult in morning briefing + heartbeats.
        # These represent Claude's explicit judgment about today's conditions and
        # override the mechanical VIX tier when Claude has made a conscious decision.
        if self.phase5 and hasattr(self.phase5, 'set_vix_tier_params'):
            if not self._ph5_brain_skip:
                _ph9_size = getattr(self.phase9, 'todays_ph5_size_mult', 1.0) if self.phase9 else 1.0
                _ph9_stop = getattr(self.phase9, 'todays_ph5_stop_mult', 1.0) if self.phase9 else 1.0
                # Use stricter of VIX tier vs PH9 directive (min size = most conservative)
                _final_size = min(_ph9_size, _vix_tier['size_mult'])
                _final_stop = max(_ph9_stop, _vix_tier['stop_mult'])
                _label = f"PH9={_ph9_size:.2f}x/VIX={_vix_tier['size_mult']:.2f}x → {_final_size:.2f}x"
                if _final_size != _vix_tier['size_mult'] or _final_stop != _vix_tier['stop_mult']:
                    logger.info(f"📊 PH5 size override: {_label} stop={_final_stop:.1f}x")
                self.phase5.set_vix_tier_params(_final_size, _final_stop, _vix_tier['tier'])

        if self._ph5_brain_skip and not prev_ph5_skip:
            _reason = 'VIX EXTREME' if _vix_tier['skip'] else 'explicit directive'
            logger.warning(f"🧠 PH9 Directive: PH5 SKIP — gap strategy blocked ({_reason}, {_vix_label})")
            if self.telegram:
                self.telegram.send_message(
                    f"🧠 PH9 → PH5: SKIP\n"
                    f"Gap strategy will not fire today.\n"
                    f"Reason: {_reason} | {_vix_label}\n"
                    f"{getattr(self.phase9, 'todays_notes', '')[:120]}"
                )
        elif not self._ph5_brain_skip and _live_vix is not None and _vix_tier['tier'] != 'LOW':
            logger.info(
                f"📊 PH5 active with VIX adjustment: {_vix_label} → "
                f"size={_vix_tier['size_mult']:.0%}  stop={_vix_tier['stop_mult']:.1f}x"
            )

        # PH5A gate
        prev_ph5a_pause = self._ph5a_brain_pause
        self._ph5a_brain_pause = ph5a_dir in ('PAUSE',)
        if self._ph5a_brain_pause and not prev_ph5a_pause:
            logger.warning(f"🧠 PH9 Directive: PH5A PAUSE — sniper paused by brain")
            if self.telegram:
                self.telegram.send_message(
                    f"🧠 PH9 → PH5A: PAUSE\n"
                    f"PVAT sniper scanning paused today."
                )

        # PH4 defensive mode
        prev_ph4_def = self._ph4_brain_defensive
        self._ph4_brain_defensive = ph4_dir in ('DEFENSIVE',)
        if self._ph4_brain_defensive and not prev_ph4_def and self.phase4:
            logger.warning(f"🧠 PH9 Directive: PH4 DEFENSIVE — tightening all stops")
            if self.telegram:
                self.telegram.send_message(
                    f"🧠 PH9 → PH4: DEFENSIVE\n"
                    f"Tightening all stops to 50% distance to protect profits."
                )
            try:
                if hasattr(self.phase4, 'tighten_all_stops'):
                    self.phase4.tighten_all_stops(factor=0.5)
            except Exception as _te:
                logger.error(f"PH4 tighten_all_stops failed: {_te}")

        # PH6 gate — HOLD means block new advisories
        if not hasattr(self, '_ph6_brain_hold'):
            self._ph6_brain_hold = False
        prev_ph6_hold = self._ph6_brain_hold
        self._ph6_brain_hold = ph6_dir in ('HOLD',)
        if self._ph6_brain_hold and not prev_ph6_hold:
            logger.warning("🧠 PH9 Directive: PH6 HOLD — options advisories paused")
            if self.telegram:
                self.telegram.send_message("🧠 PH9 → PH6: HOLD\nOptions advisories paused today.")
        # Push HOLD state into phase6 so it enforces it at advisory time
        if self.phase6 and hasattr(self.phase6, '_ph9_hold'):
            self.phase6._ph9_hold = self._ph6_brain_hold

        # PH2 gate — brain can SKIP PH2 entirely on choppy/extreme days
        ph2_dir = getattr(self.phase9, 'todays_ph2_directive', 'ACTIVE')
        if not hasattr(self, '_ph2_brain_skip'):
            self._ph2_brain_skip = False
        prev_ph2_skip = self._ph2_brain_skip
        self._ph2_brain_skip = ph2_dir in ('SKIP', 'PAUSE')
        if self._ph2_brain_skip and not prev_ph2_skip:
            logger.warning("🧠 PH9 Directive: PH2 SKIP — RSI monitor entries paused by brain")
            if self.telegram:
                self.telegram.send_message("🧠 PH9 → PH2: SKIP\nRSI swing entries paused today.")

        # PH8 directive — CLOSE_WEAKEST and watchlist additions
        _ph8_wl = getattr(self.phase9, 'todays_ph8_watchlist_add', [])
        if ph8_dir == 'CLOSE_WEAKEST' and self.phase8:
            try:
                if hasattr(self.phase8, 'close_weakest_position'):
                    self.phase8.close_weakest_position()
                    logger.info("🧠 PH9 → PH8: CLOSE_WEAKEST executed")
                    if self.telegram:
                        self.telegram.send_message("🧠 PH9 → PH8: Closing weakest weekly momentum position.")
            except Exception as _ph8e:
                logger.error(f"PH8 close_weakest failed: {_ph8e}")
        if _ph8_wl and self.phase8 and hasattr(self.phase8, 'add_to_watchlist'):
            for _sym in _ph8_wl:
                try:
                    self.phase8.add_to_watchlist(_sym)
                    logger.info(f"🧠 PH9 → PH8: Added {_sym} to watchlist")
                except Exception as _wle:
                    logger.debug(f"PH8 watchlist add failed for {_sym}: {_wle}")

        logger.info(f"🧠 PH9 Directives applied: "
                    f"PH5={'SKIP' if self._ph5_brain_skip else 'ACTIVE'} | "
                    f"PH5A={'PAUSE' if self._ph5a_brain_pause else 'ACTIVE'} | "
                    f"PH4={'DEFENSIVE' if self._ph4_brain_defensive else 'NORMAL'} | "
                    f"PH6={'HOLD' if self._ph6_brain_hold else 'ACTIVE'} | "
                    f"PH2={'SKIP' if self._ph2_brain_skip else 'ACTIVE'} | "
                    f"PH8={ph8_dir}")

    def _apply_position_actions(self, position_actions: list):
        """
        Execute position-level actions from Phase 9 briefing or heartbeat.
        Actions: TIGHTEN_STOP, WATCH_CLOSELY, CLOSE
        """
        if not position_actions or not self.phase4:
            return

        for action_item in position_actions:
            symbol = str(action_item.get('symbol', '')).upper()
            action = str(action_item.get('action', '')).upper()
            reason = action_item.get('reason', '')

            if not symbol or not action:
                continue

            try:
                if action == 'TIGHTEN_STOP':
                    # Move stop halfway to current price (protect profit)
                    pos = self.phase4.positions.get(symbol) if hasattr(self.phase4, 'positions') else None
                    if pos:
                        _entry = float(pos.get('entry_price', 0) or 0)
                        _cur   = float(pos.get('current_price', _entry) or _entry)
                        _stop  = float(pos.get('stop_price', 0) or 0)
                        _is_long = str(pos.get('direction', 'LONG')).upper() in ('LONG', 'BUY')
                        if _entry > 0 and _stop > 0:
                            if _is_long:
                                _new_stop = max(_stop, _stop + (_cur - _stop) * 0.5)
                            else:
                                _new_stop = min(_stop, _stop - (_stop - _cur) * 0.5)
                            _new_stop = round(_new_stop, 2)
                            pos['stop_price'] = _new_stop
                            self.phase4._save_positions()
                            logger.info(f"🧠 PH9 action: TIGHTEN_STOP {symbol} → ₹{_new_stop:.2f} | {reason}")

                elif action == 'WATCH_CLOSELY':
                    logger.warning(f"🧠 PH9 action: WATCH_CLOSELY {symbol} | {reason}")
                    if self.telegram:
                        self.telegram.send_message(
                            f"👁️ PH9 WATCH ALERT — {symbol}\n{reason}"
                        )

                elif action == 'CLOSE':
                    logger.warning(f"🧠 PH9 action: CLOSE {symbol} | {reason}")
                    if self.phase4 and hasattr(self.phase4, '_execute_exit'):
                        pos = self.phase4.positions.get(symbol) if hasattr(self.phase4, 'positions') else None
                        if pos:
                            self.phase4._execute_exit(symbol, pos, f'PH9_BRAIN_CLOSE: {reason}')

            except Exception as _ae:
                logger.error(f"Position action {action} for {symbol} failed: {_ae}")

    def _build_portfolio_context(self, signal_symbol: str = '') -> Dict:
        """
        Build cross-phase portfolio context for entry gate enrichment.
        Passed to Phase 9 approve_entry so Claude sees full portfolio exposure.
        """
        ctx = {
            'capital_deployed_pct':  0,
            'sector_exposure':       {},
            'signal_sector':         '',
            'open_positions_count':  0,
            'today_losses':          0,
            'ph6_active_advisories': 0,
            'brain_directive_mode':  getattr(self.phase9, 'todays_regime', 'NORMAL') if self.phase9 else 'NORMAL',
        }
        try:
            # Capital deployment
            if self.capital_manager:
                _total   = getattr(self.capital_manager, 'total_capital', 1) or 1
                _deployed = getattr(self.capital_manager, 'deployed_capital',
                            getattr(self.capital_manager, 'capital_deployed', 0))
                ctx['capital_deployed_pct'] = round(_deployed / _total * 100, 1)

            # Position count and sector exposure
            _positions = dict(self._central_positions)
            ctx['open_positions_count'] = len(_positions)
            for _sym, _pos in _positions.items():
                _sector = str(_pos.get('sector') or _pos.get('industry') or '').upper()
                if _sector:
                    ctx['sector_exposure'][_sector] = ctx['sector_exposure'].get(_sector, 0) + 1

            # Signal's sector
            if signal_symbol and self.phase1:
                try:
                    _inst = getattr(self.phase1, '_sector_map', {})
                    ctx['signal_sector'] = str(_inst.get(signal_symbol, '')).upper()
                except Exception:
                    pass

            # Today's losses (from Phase 9 P&L tracking)
            if self.phase9:
                ctx['today_losses'] = self.phase9.entries_blocked

            # PH6 active advisories
            if self.phase6 and hasattr(self.phase6, 'active_advisories'):
                ctx['ph6_active_advisories'] = len(getattr(self.phase6, 'active_advisories', {}))

        except Exception as _ce:
            logger.debug(f"Portfolio context build failed: {_ce}")
        return ctx

    def _propagate_briefing_to_phases(self):
        """
        After morning briefing runs, push the extended directive snapshot to
        each downstream phase so they can use it without holding a phase9 ref.

        Called once after morning_briefing() completes successfully.
        Safe to call even if individual phases are None.
        """
        if not self.phase9:
            return

        briefing = self.phase9.get_briefing()
        if not briefing.get('briefing_done'):
            return  # Don't propagate stale/default values

        # ── Phase 5A: PVAT Sniper ─────────────────────────────────────────────
        # PH5A reads `self.daily_briefing` for sector filtering and bias sort.
        if self.phase5a:
            self.phase5a.daily_briefing = briefing
            # Also sync market_bias into the existing PMBI slot so PH5A's
            # built-in direction sort (line ~699) picks it up.
            if not getattr(self.phase5a.config, '_pmbi_market_bias', None):
                # Only set from briefing if PMBI scan didn't already set it
                bias_dir = briefing.get('market_bias', 'NEUTRAL')
                if bias_dir in ('BULLISH', 'BEARISH'):
                    self.phase5a.config._pmbi_market_bias = {
                        'direction': bias_dir,
                        'priority': 'BUY' if bias_dir == 'BULLISH' else 'SELL',
                        'source': 'ph9_briefing',
                    }
            logger.info(f"[PH9→PH5A] Briefing pushed: bias={briefing['market_bias']} "
                        f"focus={briefing['sector_focus']} avoid={briefing['sector_avoid']}")

        # ── Phase 4: Portfolio Manager ────────────────────────────────────────
        # PH4 already holds fund_manager ref; we also stamp daily_briefing
        # so it can be read without calling fund_manager.get_briefing() everywhere.
        if self.phase4:
            self.phase4.daily_briefing = briefing
            logger.info(f"[PH9→PH4] Briefing pushed: stop_mult={briefing['stop_atr_mult']:.2f}x "
                        f"tgt_mult={briefing['target_atr_mult']:.2f}x exit={briefing['exit_aggression']}")

        # ── Phase 6: Options Advisor ──────────────────────────────────────────
        if self.phase6:
            self.phase6.daily_briefing = briefing
            logger.info(f"[PH9→PH6] Briefing pushed: ph6_bias={briefing['ph6_options_bias']} "
                        f"vix={briefing['vix_regime']}")

        # ── Phase 2 via orchestrator attr (PH2 signals executed in _run_phase2_cycle) ──
        # Entry window is read directly from self.phase9 in _run_phase2_cycle.
        # v1.6.0: Also write ph2_min_score to config so intelligent engine picks it up
        _ph2_score = briefing.get('ph2_min_score', 55.0)
        if hasattr(self.config, 'INTELLIGENT_SCORE_SKIP'):
            # Only override if Claude is being more restrictive (safety: never lower the bar below config default)
            _config_min = getattr(self.config, 'INTELLIGENT_SCORE_SKIP', 45)
            _effective = max(float(_config_min), float(_ph2_score))
            if _effective != self.config.INTELLIGENT_SCORE_SKIP:
                self.config.INTELLIGENT_SCORE_SKIP = _effective
                logger.info(f"[PH9→PH2] Score threshold updated: {_effective:.0f}")

        # v1.6.0: Push PH5A sensitivity to phase5a
        _ph5a_sens = briefing.get('ph5a_sensitivity', 'normal')
        if self.phase5a and hasattr(self.phase5a, 'config'):
            self.phase5a.config._ph9_sensitivity = _ph5a_sens
            logger.info(f"[PH9→PH5A] Sensitivity: {_ph5a_sens}")

        # v1.6.0: Push PH8 momentum threshold to phase8
        _ph8_thresh = briefing.get('ph8_momentum_threshold', 3.0)
        if self.phase8 and hasattr(self.phase8, 'config'):
            self.phase8.config._ph9_momentum_threshold = _ph8_thresh
            logger.info(f"[PH9→PH8] Momentum threshold: {_ph8_thresh:.1f}%")

        logger.info(f"[PH9] Briefing propagated to PH4/PH5A/PH6 | "
                    f"entry_window={briefing['entry_window']} | "
                    f"regime={briefing['regime']}")

    # ═══════════════════════════════════════════════════════════════════════════
    # v5.5.0: PMBI — Pre-Market Breadth Intelligence
    # ═══════════════════════════════════════════════════════════════════════════

    def _compute_nifty_trend(self) -> dict:
        """
        v1.6.0: Fetch Nifty 50 historical data from Kite and compute:
        - Current price vs 20DMA, 50DMA
        - Weekly change %, monthly change %
        - Structural trend label (UPTREND / DOWNTREND / SIDEWAYS)
        Fails gracefully — returns {} if Kite unavailable.
        """
        if not self.kite:
            return {}
        try:
            from datetime import timedelta
            _to   = datetime.now().date()
            _from = _to - timedelta(days=80)  # ~55 trading days for 50DMA
            # Nifty 50 NSE instrument token (static for NSE index)
            NIFTY_TOKEN = 256265
            hist = self.kite.historical_data(NIFTY_TOKEN, _from, _to, 'day')
            if not hist or len(hist) < 10:
                return {}
            closes = [float(d['close']) for d in hist]
            cur = closes[-1]
            # Moving averages
            ma20 = sum(closes[-20:]) / min(20, len(closes))
            ma50 = sum(closes[-50:]) / min(50, len(closes))
            # Monthly (~22 trading days) and weekly (~5 trading days) changes
            monthly_chg = round((cur - closes[-22]) / closes[-22] * 100, 2) if len(closes) >= 22 else 0.0
            weekly_chg  = round((cur - closes[-6])  / closes[-6]  * 100, 2) if len(closes) >= 6  else 0.0
            vs_20 = round((cur - ma20) / ma20 * 100, 2)
            vs_50 = round((cur - ma50) / ma50 * 100, 2)
            # Structural trend
            if cur > ma20 and ma20 > ma50:
                trend = 'UPTREND'
            elif cur < ma20 and ma20 < ma50:
                trend = 'DOWNTREND'
            else:
                trend = 'SIDEWAYS'
            return {
                'current':        round(cur, 2),
                'vs_20dma':       vs_20,
                'vs_50dma':       vs_50,
                'weekly_change':  weekly_chg,
                'monthly_change': monthly_chg,
                'trend':          trend,
            }
        except Exception as _e:
            logger.debug(f"Nifty trend fetch failed: {_e}")
            return {}

    def _run_ph9_recovery_check(self):
        """
        v1.3.0: Called after morning briefing. Scans all open positions for
        underwater trades and asks Claude's Recovery Advisor for a plan.
        Phase 4 then executes the plan via execute_recovery_action().

        Trigger: PH9_RECOVERY_ENABLED=True AND position P&L < PH9_RECOVERY_TRIGGER_PCT
        Hard eject: P&L < PH9_RECOVERY_EJECT_PCT — exits immediately, no Claude call.
        """
        if not self.phase9 or not self.phase4:
            return

        positions = dict(getattr(self.phase4, 'positions', {}) or {})
        if not positions:
            return

        trigger_pct = getattr(self.config, 'PH9_RECOVERY_TRIGGER_PCT', -2.0)

        # Get available capital
        available_capital = 0.0
        if self.capital_manager:
            try:
                available_capital = float(self.capital_manager.get_available() or 0)
            except Exception:
                pass

        recovered = 0
        for symbol, position in positions.items():
            try:
                entry  = float(position.get('entry_price', 0) or 0)
                cur    = float(position.get('current_price', entry) or entry)
                is_long = str(position.get('direction', 'LONG')).upper() in ('LONG', 'BUY')
                if entry <= 0:
                    continue
                pnl_pct = ((cur - entry) / entry * 100) if is_long else ((entry - cur) / entry * 100)
                if pnl_pct >= trigger_pct:
                    continue  # Not underwater enough

                logger.info(f"🔄 PH9 Recovery check: {symbol} P&L={pnl_pct:+.2f}% — collecting context")
                market_data = self._collect_position_recovery_context(symbol, position)
                logger.info(f"🔄 PH9 Recovery: consulting advisor for {symbol}")
                recovery_plan = self.phase9.recovery_advisor(
                    symbol=symbol,
                    position=position,
                    available_capital=available_capital,
                    market_data=market_data
                )
                action = str(recovery_plan.get('action', 'HOLD')).upper()
                if action == 'SKIP':
                    continue
                success = self.phase4.execute_recovery_action(symbol, recovery_plan)
                if success:
                    recovered += 1
                    # If position was closed or scaled, clear recovery state
                    if action in ('EXIT',):
                        self.phase9.clear_recovery(symbol)
                    # Reduce available capital after averaging
                    if action == 'AVERAGE':
                        avg_info = recovery_plan.get('average') or {}
                        used = float(avg_info.get('qty', 0) or 0) * float(avg_info.get('limit_price', 0) or cur)
                        available_capital = max(0, available_capital - used)
            except Exception as _e:
                logger.error(f"Recovery check error for {symbol}: {_e}")

        if recovered > 0:
            logger.info(f"🔄 PH9 Recovery: {recovered} position(s) actioned")

    def _collect_position_recovery_context(self, symbol: str, position: dict) -> dict:
        """
        v1.3.1: Collect rich market context for the recovery advisor.
        Fetches 5-day OHLCV, computes RSI/ATR, gets daily Kalman prediction,
        OI walls, live Nifty/VIX, and sector data. All wrapped in try/except
        so a single data-source failure doesn't block the recovery consultation.
        """
        ctx = {
            'ohlcv_5d': [],
            'rsi': None,
            'atr': None,
            'vwap_pos': 'N/A',
            'kalman_daily': {},
            'oi_walls': {},
            'nifty_pct': None,
            'vix': None,
            'sector': 'N/A',
            'sector_perf': 'N/A',
        }
        current_price = float(position.get('current_price', 0) or 0)

        # ── 5-day OHLCV + RSI + ATR ───────────────────────────────────────────
        try:
            if self.kite and self.phase4:
                instrument_token = self.phase4._get_instrument_token(symbol)
                if instrument_token:
                    from datetime import timedelta
                    _from = datetime.now() - timedelta(days=20)  # extra buffer for RSI-14
                    _hist = self.kite.historical_data(
                        instrument_token, _from, datetime.now(), interval='day'
                    )
                    if _hist and len(_hist) >= 5:
                        # Store last 5 candles for prompt
                        ctx['ohlcv_5d'] = [
                            {'date': str(c['date'])[:10],
                             'o': round(c['open'], 2), 'h': round(c['high'], 2),
                             'l': round(c['low'], 2),  'c': round(c['close'], 2),
                             'v': c['volume']}
                            for c in _hist[-5:]
                        ]
                        closes = [c['close'] for c in _hist]
                        highs  = [c['high']  for c in _hist]
                        lows   = [c['low']   for c in _hist]

                        # RSI-14
                        if len(closes) >= 15:
                            deltas = [closes[i] - closes[i-1] for i in range(1, len(closes))]
                            gains  = [max(d, 0) for d in deltas]
                            losses = [max(-d, 0) for d in deltas]
                            avg_gain = sum(gains[-14:]) / 14
                            avg_loss = sum(losses[-14:]) / 14
                            if avg_loss > 0:
                                rs = avg_gain / avg_loss
                                ctx['rsi'] = round(100 - 100 / (1 + rs), 1)
                            else:
                                ctx['rsi'] = 100.0

                        # ATR-5
                        trs = []
                        for i in range(-5, 0):
                            h, l, pc = highs[i], lows[i], closes[i-1]
                            trs.append(max(h - l, abs(h - pc), abs(l - pc)))
                        ctx['atr'] = round(sum(trs) / len(trs), 2) if trs else None

                        # VWAP approximation: if current > avg close of last 5 → above
                        avg_5 = sum(closes[-5:]) / 5
                        if current_price > 0 and avg_5 > 0:
                            diff_pct = (current_price - avg_5) / avg_5 * 100
                            ctx['vwap_pos'] = f"{'ABOVE' if diff_pct >= 0 else 'BELOW'} 5D avg by {abs(diff_pct):.1f}%"
        except Exception as _e:
            logger.debug(f"Recovery ctx OHLCV error for {symbol}: {_e}")

        # ── Daily Kalman prediction ───────────────────────────────────────────
        try:
            if self.phase4 and hasattr(self.phase4, '_fetch_daily_kalman_prediction'):
                ctx['kalman_daily'] = self.phase4._fetch_daily_kalman_prediction(symbol)
        except Exception as _e:
            logger.debug(f"Recovery ctx Kalman error for {symbol}: {_e}")

        # ── OI walls (support / resistance) ──────────────────────────────────
        try:
            if self.phase4 and hasattr(self.phase4, '_fetch_basic_option_oi') and current_price > 0:
                oi_data = self.phase4._fetch_basic_option_oi(symbol, current_price)
                if oi_data:
                    ctx['oi_walls'] = {
                        'max_pain':  oi_data.get('max_pain'),
                        'pcr':       oi_data.get('pcr'),
                        'call_wall': oi_data.get('oi_walls', {}).get('call_resistance'),
                        'put_wall':  oi_data.get('oi_walls', {}).get('put_support'),
                    }
        except Exception as _e:
            logger.debug(f"Recovery ctx OI error for {symbol}: {_e}")

        # ── Live Nifty/VIX ────────────────────────────────────────────────────
        try:
            if self.kite:
                nq = self.kite.quote(['NSE:NIFTY 50'])
                if nq:
                    _nq = list(nq.values())[0]
                    _last = _nq.get('last_price', 0)
                    _chg  = _nq.get('net_change', 0)
                    _prev = _last - _chg
                    if _prev:
                        ctx['nifty_pct'] = round(_chg / _prev * 100, 2)
                vq = self.kite.quote(['NSE:INDIA VIX'])
                if vq:
                    ctx['vix'] = list(vq.values())[0].get('last_price')
        except Exception as _e:
            logger.debug(f"Recovery ctx Nifty/VIX error: {_e}")

        # ── Sector from PMBI ──────────────────────────────────────────────────
        try:
            if self.market_bias:
                _sym_sectors = self.market_bias.get('symbol_sectors', {})
                _sector_perf = (self.market_bias.get('sector_breadth')
                                or self.market_bias.get('sector_ratios')
                                or self.market_bias.get('sectors') or {})
                _sec = _sym_sectors.get(symbol, 'N/A')
                ctx['sector'] = _sec
                if _sec != 'N/A' and _sec in _sector_perf:
                    ctx['sector_perf'] = _sector_perf[_sec]
        except Exception as _e:
            logger.debug(f"Recovery ctx sector error: {_e}")

        return ctx

    def _collect_morning_briefing_data(self) -> dict:
        """
        Collect market data for Phase 9 morning briefing.
        Gathers portfolio state, market indicators, PMBI, and capital info.
        """
        data = {
            'capital_available': 0,
            'open_positions': {},
            'yesterday_pnl': 0,
            'week_pnl': 0,
            'nifty_close': 'N/A',
            'nifty_change_pct': 'N/A',
            'vix': 'N/A',
            'fii_dii': 'N/A',
            'sgx_nifty': 'N/A',
            'pmbi': {},
            'sector_heatmap': {},
            'nifty_trend':   {},   # v1.6.0: 20/50DMA trend context
            'vix_trend':     'N/A',  # v1.6.0: 5-day VIX direction
            'fii_5d_trend':  'N/A',  # v1.6.0: 5-day FII flow direction
        }

        try:
            # Capital
            if self.capital_manager:
                data['capital_available'] = getattr(self.capital_manager, 'available_capital',
                    getattr(self.capital_manager, 'capital_available', 0))
        except Exception:
            pass

        try:
            # Open positions (compact view)
            data['open_positions'] = {
                k: {
                    'entry_price': v.get('entry_price', 0),
                    'direction':   v.get('direction', '?'),
                    'quantity':    v.get('quantity', 0),
                    'product':     v.get('product', '?'),
                }
                for k, v in self._central_positions.items()
            }
        except Exception:
            pass

        try:
            # PMBI — also extract sector heatmap from it
            if self.market_bias:
                data['pmbi'] = self.market_bias
                # sector_heatmap: use sector_breadth sub-dict if available
                _sb = (self.market_bias.get('sector_breadth')
                       or self.market_bias.get('sector_ratios')
                       or self.market_bias.get('sectors')
                       or {})
                if _sb:
                    data['sector_heatmap'] = _sb
        except Exception:
            pass

        try:
            # Yesterday P&L — from Phase 9's own tracking or Phase 4 closed history
            if self.phase9 and self.phase9.daily_pnl != 0:
                # Phase 9 tracks running P&L via update_daily_pnl()
                data['yesterday_pnl'] = round(self.phase9.daily_pnl, 2)
            elif self.phase4 and hasattr(self.phase4, 'get_daily_pnl_summary'):
                try:
                    _pnl_summary = self.phase4.get_daily_pnl_summary()
                    data['yesterday_pnl'] = _pnl_summary.get('total_pnl', 0)
                except Exception:
                    pass
            # Blackbox fallback
            if data['yesterday_pnl'] == 0 and self.blackbox:
                try:
                    _trades = getattr(self.blackbox, 'phase3_trades', []) or []
                    _pnl = sum(
                        float(t.get('details', {}).get('pnl', 0) or 0)
                        for t in _trades
                        if t.get('action') in ('EXIT', 'SELL', 'CLOSE')
                    )
                    if _pnl != 0:
                        data['yesterday_pnl'] = round(_pnl, 2)
                except Exception:
                    pass
        except Exception:
            pass

        try:
            # Week P&L — rolling sum from Phase 9 memory history (last 5 days)
            if self.phase9 and self.phase9.memory_enabled and self.phase9.rolling_history:
                _week_pnl = sum(
                    float(h.get('pnl', 0) or 0)
                    for h in self.phase9.rolling_history[-5:]
                )
                data['week_pnl'] = round(_week_pnl, 2)
        except Exception:
            pass

        try:
            # Nifty/VIX — use shared 60s cache (avoids duplicate Kite calls)
            _lmd = self._get_live_market_data()
            if _lmd.get('nifty_change_pct') is not None:
                data['nifty_change_pct'] = _lmd['nifty_change_pct']
            if _lmd.get('nifty_close') is not None:
                data['nifty_close'] = _lmd['nifty_close']
            if _lmd.get('vix') is not None:
                data['vix'] = _lmd['vix']
        except Exception as e:
            logger.debug(f"Morning briefing Nifty/VIX fetch failed: {e}")

        # v1.6.0: Nifty multi-timeframe trend (20DMA / 50DMA / monthly)
        try:
            data['nifty_trend'] = self._compute_nifty_trend()
        except Exception as _nte:
            logger.debug(f"Nifty trend computation failed: {_nte}")

        # v1.6.0: VIX 5-day trend — roll into in-memory cache, compute direction
        try:
            _vix_val = data.get('vix', 'N/A')
            if isinstance(_vix_val, (int, float)) and _vix_val > 0:
                self._vix_history.append(float(_vix_val))
                self._vix_history = self._vix_history[-10:]  # keep last 10 days
            if len(self._vix_history) >= 3:
                _vix_5d = self._vix_history[-min(5, len(self._vix_history)):]
                data['vix_trend'] = (f"RISING ({_vix_5d[0]:.1f}→{_vix_5d[-1]:.1f})"
                                    if _vix_5d[-1] > _vix_5d[0]
                                    else f"FALLING ({_vix_5d[0]:.1f}→{_vix_5d[-1]:.1f})")
        except Exception as _vte:
            logger.debug(f"VIX trend computation failed: {_vte}")

        # v1.6.0: FII 5-day trend from PMBI if available
        try:
            _pmbi = data.get('pmbi', {})
            _fii_net = _pmbi.get('fii_net_crore') or _pmbi.get('fii_net') or _pmbi.get('fii_dii_net')
            if _fii_net is not None:
                _sign = "NET BUYING" if float(_fii_net) > 0 else "NET SELLING"
                data['fii_5d_trend'] = f"₹{float(_fii_net):+,.0f}Cr ({_sign})"
        except Exception as _fte:
            logger.debug(f"FII trend extraction failed: {_fte}")

        return data

    def _run_pmbi_scan(self):
        """
        Pre-Market Breadth Intelligence (PMBI) v5.4.0

        Runs at 9:11 AM. Scans all F&O stocks using Phase 1's UptrendVerifier
        to count uptrend vs downtrend with sector-wise breakdown.

        v5.4.0 ENHANCEMENTS:
          - Sector rotation detection (per-sector breadth ratio)
          - Momentum quality scoring (strong vs weak uptrends)
          - Claude deep analysis: sector rotation, risk level, sizing advice,
            watch stocks, avoid sectors, and intraday edge assessment
          - Enriched market_bias dict for downstream PH5/PH5A/PH1 consumption

        Sets self.market_bias for downstream phases.
        Does NOT modify Phase 1, ACTIVE.json, or Phase 2 monitors.
        """
        try:
            # ── Guard: already done today ──
            if self._pmbi_done_today:
                return

            # ── Daily reset ──
            today = datetime.now().date()
            if self._pmbi_last_run_date != today:
                self._pmbi_done_today = False

            logger.info("=" * 70)
            logger.info("🧠 PMBI: Pre-Market Breadth Intelligence scan starting...")
            logger.info("=" * 70)

            # ── Import Phase 1 classes (read-only, no modification) ──
            from phase1_stock_selection import UptrendVerifier

            # ── Get master stock list ──
            if self.phase1 and hasattr(self.phase1, 'master_list') and self.phase1.master_list:
                master_list = list(self.phase1.master_list)
            elif hasattr(self.config, 'MASTER_STOCK_LIST') and self.config.MASTER_STOCK_LIST:
                master_list = list(self.config.MASTER_STOCK_LIST)
            else:
                logger.error("🧠 PMBI: No master stock list available — aborting")
                self._pmbi_done_today = True
                self._pmbi_last_run_date = today
                return

            logger.info(f"🧠 PMBI: Scanning {len(master_list)} stocks for breadth...")

            # ── Build token map ──
            instruments = self.kite.instruments("NSE")
            token_map = {inst['tradingsymbol']: inst['instrument_token']
                         for inst in instruments if inst['exchange'] == 'NSE'}

            # ── Create UptrendVerifier instance ──
            if self.phase1 and hasattr(self.phase1, 'uptrend_verifier'):
                uptrend_verifier = self.phase1.uptrend_verifier
            else:
                uptrend_verifier = UptrendVerifier(self.kite, self.config)

            # ── Scan loop (v5.4.0: collect sector-wise breadth + trend details) ──
            uptrend_count = 0
            downtrend_count = 0
            price_skipped = 0
            scan_errors = 0
            uptrend_symbols = []
            downtrend_symbols = []
            sector_map = getattr(self.config, 'STOCK_SECTOR_MAP', {})
            sector_breadth = {}  # {sector: {'up': [...], 'down': [...]}}
            stock_details = []   # [{symbol, ltp, is_uptrend, sector, ema21_slope, ma20_mom, ...}]

            for idx, symbol in enumerate(master_list, 1):
                try:
                    # Get instrument token
                    if symbol not in token_map:
                        continue

                    instrument_token = token_map[symbol]

                    # Get LTP via quote
                    quote = self.kite.quote(f"NSE:{symbol}")
                    ltp = quote.get(f"NSE:{symbol}", {}).get('last_price', 0)

                    # Filter 1: Price range check
                    price_min = getattr(self.config, 'PRICE_MIN', 500)
                    price_max = getattr(self.config, 'PRICE_MAX', 2500)
                    if not (price_min <= ltp <= price_max):
                        price_skipped += 1
                        continue

                    # Filter 2: Uptrend check via Phase 1's UptrendVerifier
                    is_uptrend, trend_details = uptrend_verifier.check_uptrend(
                        symbol, instrument_token
                    )

                    if is_uptrend:
                        uptrend_count += 1
                        uptrend_symbols.append(symbol)
                    else:
                        downtrend_count += 1
                        downtrend_symbols.append(symbol)

                    # v5.4.0: Collect sector-wise breadth
                    sector = sector_map.get(symbol, 'OTHER')
                    if sector not in sector_breadth:
                        sector_breadth[sector] = {'up': [], 'down': []}
                    sector_breadth[sector]['up' if is_uptrend else 'down'].append(symbol)

                    # v5.4.0: Collect stock-level details for Claude analysis
                    stock_details.append({
                        'symbol': symbol,
                        'ltp': round(ltp, 2),
                        'sector': sector,
                        'is_uptrend': is_uptrend,
                        'ema21_slope': trend_details.get('ema21_slope_positive', False),
                        'ma20_momentum': trend_details.get('ma20_momentum_up', False),
                        'price_above_ma20': trend_details.get('price_above_ma20', False),
                        'days_above_ma20': trend_details.get('days_above_ma20', 0),
                    })

                    # Rate limit: Zerodha allows ~3 req/sec for historical_data
                    time.sleep(0.35)

                except Exception as e:
                    scan_errors += 1
                    logger.debug(f"🧠 PMBI: Skip {symbol}: {e}")
                    continue

            # ── Calculate breadth ──
            price_eligible = uptrend_count + downtrend_count
            breadth_ratio = uptrend_count / price_eligible if price_eligible > 0 else 0.5

            logger.info(f"🧠 PMBI: {price_eligible} stocks scanned | "
                        f"{uptrend_count} UPTREND ({breadth_ratio*100:.0f}%) | "
                        f"{downtrend_count} DOWNTREND ({(1-breadth_ratio)*100:.0f}%) | "
                        f"{price_skipped} price-filtered | {scan_errors} errors")

            # ── Programmatic bias ──
            if breadth_ratio >= self.config.PMBI_BULLISH_THRESHOLD:
                prog_bias = 'BULLISH'
                prog_priority = 'BUY'
            elif breadth_ratio <= self.config.PMBI_BEARISH_THRESHOLD:
                prog_bias = 'BEARISH'
                prog_priority = 'SELL'
            else:
                prog_bias = 'MIXED'
                prog_priority = 'NEUTRAL'

            # Defaults (overridden by Claude if successful)
            final_bias = prog_bias
            final_priority = prog_priority
            confidence = int(abs(breadth_ratio - 0.5) * 200)  # 0-100 scale
            source = 'programmatic'

            # v5.4.0: Build sector-wise summary for Claude
            sector_summary = {}
            for sector, data in sector_breadth.items():
                total = len(data['up']) + len(data['down'])
                if total > 0:
                    sector_summary[sector] = {
                        'total': total,
                        'uptrend': len(data['up']),
                        'downtrend': len(data['down']),
                        'ratio': round(len(data['up']) / total, 2),
                        'up_stocks': data['up'][:5],
                        'down_stocks': data['down'][:5],
                    }

            # v5.4.0: Identify strongest/weakest sectors
            sorted_sectors = sorted(sector_summary.items(),
                                     key=lambda x: x[1]['ratio'], reverse=True)
            strong_sectors = [(s, d) for s, d in sorted_sectors if d['ratio'] >= 0.5 and d['total'] >= 2]
            weak_sectors = [(s, d) for s, d in sorted_sectors if d['ratio'] < 0.5 and d['total'] >= 2]

            ai_data = {}  # v5.4.0: populated by Claude if enabled, empty otherwise

            # ── Claude AI Review (v5.4.0: deep analysis with sector rotation) ──
            if (getattr(self.config, 'PMBI_CHATGPT_REVIEW', False) and
                    self.strategic_advisor and
                    hasattr(self.strategic_advisor, 'client')):
                try:
                    import json as json_mod

                    # Build sector breakdown string
                    sector_lines = []
                    for sector, data in sorted(sector_summary.items(),
                                                key=lambda x: x[1]['ratio'], reverse=True):
                        pct = data['ratio'] * 100
                        bar = '█' * int(pct / 10) + '░' * (10 - int(pct / 10))
                        sector_lines.append(
                            f"  {sector:<20} {bar} {data['uptrend']}/{data['total']} "
                            f"({pct:.0f}%) up={','.join(data['up_stocks'][:3])} "
                            f"down={','.join(data['down_stocks'][:3])}"
                        )
                    sector_block = '\n'.join(sector_lines) if sector_lines else '  No sector data available'

                    # Identify momentum quality: how many stocks have BOTH ema21 slope + ma20 momentum?
                    strong_uptrend = [s for s in stock_details
                                      if s['is_uptrend'] and s['ema21_slope'] and s['ma20_momentum']]
                    weak_uptrend = [s for s in stock_details
                                    if s['is_uptrend'] and not (s['ema21_slope'] and s['ma20_momentum'])]

                    user_prompt = f"""NSE PRE-MARKET BREADTH INTELLIGENCE — {datetime.now().strftime('%Y-%m-%d %H:%M')}
═══════════════════════════════════════════════════════

AGGREGATE BREADTH:
  Total F&O stocks scanned: {price_eligible}
  Uptrend: {uptrend_count} ({breadth_ratio*100:.1f}%)
  Downtrend: {downtrend_count} ({(1-breadth_ratio)*100:.1f}%)
  Programmatic bias: {prog_bias} (threshold: bullish≥{self.config.PMBI_BULLISH_THRESHOLD*100:.0f}%, bearish≤{self.config.PMBI_BEARISH_THRESHOLD*100:.0f}%)

MOMENTUM QUALITY:
  Strong uptrends (EMA21↑ + MA20↑ + Price>MA20): {len(strong_uptrend)} stocks
  Weak uptrends (partial criteria only): {len(weak_uptrend)} stocks
  Conviction ratio: {len(strong_uptrend)}/{uptrend_count if uptrend_count > 0 else 1} ({(len(strong_uptrend)/max(uptrend_count,1))*100:.0f}% strong)

SECTOR-WISE BREAKDOWN:
{sector_block}

TOP UPTREND STOCKS: {', '.join(uptrend_symbols[:15])}
TOP DOWNTREND STOCKS: {', '.join(downtrend_symbols[:15])}

CONTEXT FOR YOUR ANALYSIS:
  - This algo trades MIS intraday gap scalps (PH5) and PVAT sniper entries (PH5A)
  - PH5 trades BOTH long and short gaps; your bias determines which direction gets a +10 score bonus
  - PH5A Sniper only enters if bias aligns with NIFTY direction
  - Positions are held 15-60 minutes with 0.5× ATR stops and TCAS trailing
  - If MIXED: both directions get no bonus — algo relies purely on technical score

YOUR TASK — Provide analysis in this exact JSON format (no markdown, no extra text):
{{
  "bias": "BULLISH | BEARISH | MIXED",
  "confidence": 0-100,
  "priority": "BUY | SELL | NEUTRAL",
  "reasoning": "2-3 sentences: WHY this bias, citing breadth + sector data",
  "sector_rotation": "which sectors are leading/lagging and what it signals",
  "strong_sectors": ["SECTOR1", "SECTOR2"],
  "weak_sectors": ["SECTOR3", "SECTOR4"],
  "momentum_quality": "HIGH | MEDIUM | LOW — based on conviction ratio",
  "risk_level": "LOW | MODERATE | ELEVATED | HIGH",
  "preferred_direction": "LONG | SHORT | BOTH",
  "sizing_advice": "FULL | REDUCED | MINIMAL — position sizing recommendation",
  "watch_stocks": ["STOCK1", "STOCK2", "STOCK3"],
  "avoid_sectors": ["SECTOR1"],
  "intraday_edge": "1-2 sentences: specific intraday opportunity you see"
}}

GUIDELINES:
- HIGH confidence (75-100): clear breadth skew (>65% or <35%) + sector alignment + strong momentum quality
- MODERATE confidence (50-74): breadth leans one way but sectors are mixed or momentum quality is weak
- LOW confidence (<50): conflicting signals — set MIXED with NEUTRAL priority
- REDUCED sizing when: breadth is marginal, momentum quality is LOW, or sector rotation unclear
- MINIMAL sizing when: extreme conflict between breadth direction and leading sector direction
- Watch stocks: pick 3-5 from uptrend list that belong to strong sectors (highest probability)
- Avoid sectors: sectors with 0% uptrend or clear technical breakdown"""

                    ai_response = self.strategic_advisor.client.messages.create(
                        model=getattr(self.config, 'GPT_MODEL', 'claude-sonnet-4-6'),
                        system=(
                            "You are an expert NSE intraday market analyst for an algorithmic trading system. "
                            "You analyze pre-market breadth data, sector rotation, and momentum quality to "
                            "produce actionable trading bias for the day's MIS gap scalps and PVAT sniper entries. "
                            "Your output directly controls position sizing and directional preference. "
                            "Be precise, data-driven, and conservative — wrong bias costs real money. "
                            "Respond ONLY with valid JSON. No markdown fences, no explanation outside the JSON."
                        ),
                        messages=[{"role": "user", "content": user_prompt}],
                        temperature=0.2,
                        max_tokens=600
                    )

                    import json
                    raw_text = ai_response.content[0].text.strip()
                    # Handle potential markdown fencing
                    if raw_text.startswith('```'):
                        raw_text = raw_text.split('\n', 1)[-1].rsplit('```', 1)[0].strip()
                    ai_data = json.loads(raw_text)

                    # Validate required keys
                    required_keys = ('bias', 'confidence', 'priority')
                    if all(k in ai_data for k in required_keys):
                        final_bias = ai_data['bias'].upper()
                        confidence = int(ai_data['confidence'])
                        final_priority = ai_data['priority'].upper()
                        source = 'claude'
                        reasoning = ai_data.get('reasoning', '')
                        logger.info(f"🧠 PMBI Claude: {final_bias} ({confidence}%) — {reasoning[:100]}")

                        # v5.4.0: Log enriched analysis
                        sector_rot = ai_data.get('sector_rotation', '')
                        mom_quality = ai_data.get('momentum_quality', 'UNKNOWN')
                        risk_lvl = ai_data.get('risk_level', 'UNKNOWN')
                        sizing = ai_data.get('sizing_advice', 'FULL')
                        pref_dir = ai_data.get('preferred_direction', 'BOTH')
                        watch = ai_data.get('watch_stocks', [])
                        avoid = ai_data.get('avoid_sectors', [])
                        edge = ai_data.get('intraday_edge', '')

                        logger.info(f"🧠 PMBI Claude: Sectors → {sector_rot[:80]}")
                        logger.info(f"🧠 PMBI Claude: Momentum={mom_quality} | Risk={risk_lvl} | "
                                    f"Sizing={sizing} | Direction={pref_dir}")
                        if watch:
                            logger.info(f"🧠 PMBI Claude: Watch → {', '.join(watch[:5])}")
                        if avoid:
                            logger.info(f"🧠 PMBI Claude: Avoid → {', '.join(avoid)}")
                        if edge:
                            logger.info(f"🧠 PMBI Claude: Edge → {edge[:100]}")
                    else:
                        logger.warning("🧠 PMBI: Claude response missing required keys — using programmatic bias")
                        ai_data = {}

                except Exception as e:
                    logger.warning(f"🧠 PMBI: Claude review failed ({e}) — using programmatic bias")
                    ai_data = {}
                    # Fallback already set above

            # ── Store result (v5.4.0: enriched with sector + Claude analysis) ──
            ai_data_safe = ai_data if isinstance(ai_data, dict) else {}
            self.market_bias = {
                'direction': final_bias,
                'priority': final_priority,
                'confidence': confidence,
                'breadth_ratio': breadth_ratio,
                'uptrend_count': uptrend_count,
                'downtrend_count': downtrend_count,
                'total_scanned': price_eligible,
                'source': source,
                'timestamp': datetime.now().isoformat(),
                # v5.4.0: Sector rotation data
                'sector_breadth': {s: {'up': d['uptrend'], 'down': d['downtrend'],
                                        'ratio': d['ratio']}
                                    for s, d in sector_summary.items()},
                'strong_sectors': [s for s, _ in strong_sectors],
                'weak_sectors': [s for s, _ in weak_sectors],
                # v5.4.0: Claude enrichment (empty if Claude disabled/failed)
                'momentum_quality': ai_data_safe.get('momentum_quality', 'UNKNOWN'),
                'risk_level': ai_data_safe.get('risk_level', 'UNKNOWN'),
                'sizing_advice': ai_data_safe.get('sizing_advice', 'FULL'),
                'preferred_direction': ai_data_safe.get('preferred_direction', 'BOTH'),
                'watch_stocks': ai_data_safe.get('watch_stocks', []),
                'avoid_sectors': ai_data_safe.get('avoid_sectors', []),
                'sector_rotation': ai_data_safe.get('sector_rotation', ''),
                'intraday_edge': ai_data_safe.get('intraday_edge', ''),
            }

            # Share via config for PH5A access (no constructor change needed)
            self.config._pmbi_market_bias = self.market_bias

            # ── Save to file ──
            try:
                import json
                pmbi_dir = os.path.join('data', 'pmbi_output')
                os.makedirs(pmbi_dir, exist_ok=True)
                filename = f"pmbi_{datetime.now().strftime('%Y%m%d')}.json"
                filepath = os.path.join(pmbi_dir, filename)
                with open(filepath, 'w') as f:
                    json.dump(self.market_bias, f, indent=2)
                logger.info(f"🧠 PMBI: Saved to {filepath}")
            except Exception as e:
                logger.warning(f"🧠 PMBI: Failed to save output file: {e}")

            # ── Telegram notification (v5.4.0: enriched) ──
            if self.telegram:
                try:
                    # Build sector summary for Telegram
                    sector_tg_lines = []
                    for sector, data in sorted(sector_summary.items(),
                                                key=lambda x: x[1]['ratio'], reverse=True):
                        if data['total'] >= 2:
                            pct = data['ratio'] * 100
                            emoji = '🟢' if pct >= 60 else ('🟡' if pct >= 40 else '🔴')
                            sector_tg_lines.append(f"  {emoji} {sector}: {data['uptrend']}/{data['total']} ({pct:.0f}%)")
                    sector_tg_block = '\n'.join(sector_tg_lines[:8]) if sector_tg_lines else '  No sector data'

                    # Claude insights
                    mom_q = self.market_bias.get('momentum_quality', '')
                    risk = self.market_bias.get('risk_level', '')
                    sizing = self.market_bias.get('sizing_advice', '')
                    pref = self.market_bias.get('preferred_direction', '')
                    watch = self.market_bias.get('watch_stocks', [])
                    edge = self.market_bias.get('intraday_edge', '')
                    reasoning_tg = ai_data_safe.get('reasoning', '') if ai_data_safe else ''

                    msg = (
                        f"🧠 PRE-MARKET BREADTH INTELLIGENCE\n\n"
                        f"📊 {price_eligible} stocks scanned\n"
                        f"✅ {uptrend_count} UPTREND ({breadth_ratio*100:.0f}%)\n"
                        f"❌ {downtrend_count} DOWNTREND ({(1-breadth_ratio)*100:.0f}%)\n\n"
                        f"📈 SECTOR ROTATION:\n{sector_tg_block}\n\n"
                        f"🤖 {source.upper()}: {final_bias} ({confidence}%)\n"
                        f"📌 Priority: {final_priority} | Direction: {pref}\n"
                        f"⚡ Momentum: {mom_q} | Risk: {risk} | Sizing: {sizing}\n"
                    )
                    if reasoning_tg:
                        msg += f"\n💡 {reasoning_tg[:200]}\n"
                    if watch:
                        msg += f"\n👀 Watch: {', '.join(watch[:5])}"
                    if edge:
                        msg += f"\n🎯 Edge: {edge[:150]}"

                    self.telegram.send_message(msg)
                except Exception:
                    pass

            # ── Set flags ──
            self._pmbi_done_today = True
            self._pmbi_last_run_date = today

            logger.info(f"🧠 PMBI: Complete — {final_bias} bias ({source}, {confidence}% confidence) | "
                        f"Sectors: {len(strong_sectors)} strong, {len(weak_sectors)} weak")
            logger.info("=" * 70)

        except Exception as e:
            logger.error(f"❌ PMBI scan failed: {e}")
            import traceback
            logger.error(traceback.format_exc())
            # Ensure flags are set so we don't retry endlessly
            self._pmbi_done_today = True
            self._pmbi_last_run_date = datetime.now().date()

    # ═══════════════════════════════════════════════════════════════════════════
    # v8.0.0: PHASE 8 WEEKLY MOMENTUM STRATEGY SCHEDULER
    # ═══════════════════════════════════════════════════════════════════════════
    #
    # Wednesday: 09:00 → scan + rank → 10:00 → VWAP entry via Ph3 → 10:30 fallback
    # Tuesday:   5 exit check windows via Ph4.check_tier3_tuesday_exit()
    # Daily:     Tier 3 TCAS runs inside Ph4.run_monitoring_cycle() (STEP 4C)
    # ═══════════════════════════════════════════════════════════════════════════

    def _wire_ph8_intelligence(self):
        """v8.1.0: Lazy-wire FinBERT, news_scraper, mission_db to Phase 4."""
        if not self.phase4:
            return

        # FinBERT
        if not getattr(self.phase4, 'finbert', None):
            try:
                from finbert_analyzer import get_finbert_analyzer
                self.phase4.finbert = get_finbert_analyzer()
                logger.info("   PH8: FinBERT wired to Phase 4")
            except Exception as e:
                logger.debug(f"   PH8: FinBERT not available: {e}")

        # News scraper
        if not getattr(self.phase4, 'news_scraper', None):
            try:
                from news_scraper import NewsScraperFree
                self.phase4.news_scraper = NewsScraperFree()
                logger.info("   PH8: NewsScraperFree wired to Phase 4")
            except Exception as e:
                logger.debug(f"   PH8: NewsScraperFree not available: {e}")

        # Mission DB
        if not getattr(self.phase4, 'mission_db', None):
            try:
                from mission_db import get_mission_db
                self.phase4.mission_db = get_mission_db()
                logger.info("   PH8: MissionDB wired to Phase 4")
            except Exception as e:
                logger.debug(f"   PH8: MissionDB not available: {e}")

    def _run_phase8_schedule(self):
        """
        Phase 8 Weekly Momentum — day-of-week gated scheduling.

        Wednesday flow:
            09:00  run_weekly_scan()        → pick top-1 stock
            10:00  calculate_vwap_and_build_signal()  → LIMIT at VWAP
            10:00  Ph3.execute_ph8_momentum_signal()  → place order
            10:05-10:30  Ph3 re-check (PENDING_FILL → fallback to MARKET)

        Tuesday flow:
            5 check windows (config PH8_EXIT_CHECK_TIMES)
            Ph4.check_tier3_tuesday_exit(check_time) at each window
        """
        if not self.phase8:
            return

        now = datetime.now()
        today = now.date()
        current_time = now.time()
        weekday = now.weekday()  # 0=Mon, 1=Tue, 2=Wed

        # ─── Daily reset ─────────────────────────────────────────────────
        if self._ph8_scan_last_date != today:
            self._ph8_scan_done_today = False
            self._ph8_entry_done_today = False
            self._ph8_pending_signal = None
            self._ph8_scan_last_date = today

        if self._ph8_tuesday_last_date != today:
            self._ph8_tuesday_checks_done = set()
            self._ph8_tuesday_last_date = today

        if self._ph8_morning_review_last_date != today:
            self._ph8_morning_review_done_today = False
            self._ph8_morning_review_last_date = today

        # ═════════════════════════════════════════════════════════════════
        # DAILY: Morning Intelligence Review (Thu, Fri, Mon, Tue at 9:00)
        # ═════════════════════════════════════════════════════════════════
        review_days = getattr(self.config, 'PH8_MORNING_REVIEW_DAYS', [0, 1, 3, 4])
        review_time = getattr(self.config, 'PH8_MORNING_REVIEW_TIME', dt_time(9, 0))

        if (weekday in review_days
                and not self._ph8_morning_review_done_today
                and current_time >= review_time
                and getattr(self.config, 'PH8_MORNING_REVIEW_ENABLED', False)):
            try:
                logger.info("")
                logger.info("=" * 70)
                logger.info("PH8 TIER 3 MORNING INTELLIGENCE REVIEW")
                logger.info("=" * 70)

                # Lazy-wire dependencies that may not exist at init time
                self._wire_ph8_intelligence()

                self.phase4.run_tier3_morning_intelligence()
                self._ph8_morning_review_done_today = True
                logger.info("PH8 Morning intelligence review complete")
            except Exception as e:
                logger.error(f"PH8 Morning intelligence review failed: {e}", exc_info=True)
                self._ph8_morning_review_done_today = True  # Don't retry

        # ═════════════════════════════════════════════════════════════════
        # WEDNESDAY: Scan + VWAP Entry
        # ═════════════════════════════════════════════════════════════════
        scan_day = getattr(self.config, 'PH8_SCAN_DAY', 2)  # 2 = Wednesday

        if weekday == scan_day:

            # STEP 1: 09:00+ — Run weekly scan (once)
            if not self._ph8_scan_done_today and current_time >= dt_time(9, 0):
                try:
                    logger.info("")
                    logger.info("=" * 70)
                    logger.info("📈 PHASE 8: WEEKLY MOMENTUM SCAN (Wednesday)")
                    logger.info("=" * 70)

                    scan_result = self.phase8.run_weekly_scan()

                    self._ph8_scan_done_today = True

                    if scan_result:
                        self._ph8_pending_signal = scan_result
                        logger.info(f"📈 PH8 scan picked: {scan_result.get('symbol')} "
                                    f"(return: {scan_result.get('weekly_return_pct', 0):.2f}%)")
                        logger.info("   VWAP entry scheduled at 10:00 AM")
                    else:
                        logger.info("📈 PH8 scan: No eligible stock found (max positions or filter)")

                except Exception as e:
                    logger.error(f"❌ PH8 weekly scan failed: {e}")
                    import traceback
                    logger.error(traceback.format_exc())
                    self._ph8_scan_done_today = True  # Don't retry

            # STEP 2: 10:00+ — Calculate VWAP and build signal, then execute via Ph3
            vwap_time = getattr(self.config, 'PH8_VWAP_WINDOW_END', dt_time(10, 0))
            entry_end = getattr(self.config, 'PH8_ENTRY_WINDOW_END', dt_time(10, 30))

            if (self._ph8_pending_signal and
                    not self._ph8_entry_done_today and
                    current_time >= vwap_time):

                try:
                    signal = self._ph8_pending_signal

                    # Calculate VWAP and build full signal (only once)
                    if not signal.get('_vwap_built'):
                        logger.info(f"📈 PH8: Building VWAP signal for {signal.get('symbol')}...")
                        full_signal = self.phase8.calculate_vwap_and_build_signal(signal)

                        if full_signal:
                            full_signal['_vwap_built'] = True
                            self._ph8_pending_signal = full_signal
                            signal = full_signal
                            logger.info(f"   VWAP: ₹{signal.get('entry_price', 0):.2f} | "
                                        f"Qty: {signal.get('quantity', 0)}")
                        else:
                            logger.warning("📈 PH8: VWAP signal build failed — skipping entry")
                            self._ph8_entry_done_today = True
                            self._ph8_pending_signal = None
                            return

                    # v5.6.1: Paper mode intercept — log signal, skip live execution
                    if getattr(self.config, 'PH8_PAPER_MODE', False):
                        _paper_rec = {
                            'timestamp': datetime.now().isoformat(),
                            'symbol': signal.get('symbol', ''),
                            'direction': signal.get('direction', ''),
                            'entry_price': signal.get('entry_price', 0),
                            'stop_loss': signal.get('stop_loss', 0),
                            'target': signal.get('target', 0),
                            'score': signal.get('score', 0),
                            'mode': 'PAPER',
                        }
                        import json as _json
                        _ph8_log = os.path.join('data', 'ph8_paper_signals.json')
                        try:
                            os.makedirs('data', exist_ok=True)
                            _existing = []
                            if os.path.isfile(_ph8_log):
                                with open(_ph8_log, 'r') as _f:
                                    _existing = _json.load(_f)
                            _existing.append(_paper_rec)
                            with open(_ph8_log, 'w') as _f:
                                _json.dump(_existing, _f, indent=2, default=str)
                        except Exception as _e:
                            logger.warning(f"PH8 paper log write: {_e}")
                        logger.info(f"📝 PH8 PAPER: {_paper_rec['symbol']} {_paper_rec['direction']} "
                                    f"@ {_paper_rec['entry_price']} → logged (no live order)")
                        self._ph8_entry_done_today = True
                        self._ph8_pending_signal = None
                        return

                    # Execute via Phase 3
                    if self.phase3 and hasattr(self.phase3, 'execute_ph8_momentum_signal'):
                        result = self.phase3.execute_ph8_momentum_signal(signal)

                        if result:
                            status = result.get('status', '')
                            if status == 'PENDING_FILL':
                                # Limit order placed, wait for fill or 10:30 fallback
                                logger.info(f"📈 PH8: LIMIT order placed, pending fill "
                                            f"(fallback at {entry_end})")
                                # Don't mark entry_done yet — Ph3 will retry on next loop
                                if current_time >= entry_end:
                                    # Past fallback window, Ph3 should have handled it
                                    self._ph8_entry_done_today = True
                                    self._ph8_pending_signal = None
                            else:
                                # Filled or failed — done for today
                                logger.info(f"📈 PH8: Entry result: {status}")
                                self._ph8_entry_done_today = True
                                self._ph8_pending_signal = None
                        else:
                            logger.warning("📈 PH8: Ph3 returned None — entry skipped")
                            self._ph8_entry_done_today = True
                            self._ph8_pending_signal = None
                    else:
                        logger.error("📈 PH8: Phase 3 not available for order execution")
                        self._ph8_entry_done_today = True
                        self._ph8_pending_signal = None

                except Exception as e:
                    logger.error(f"❌ PH8 entry execution failed: {e}")
                    import traceback
                    logger.error(traceback.format_exc())
                    self._ph8_entry_done_today = True
                    self._ph8_pending_signal = None

        # ═════════════════════════════════════════════════════════════════
        # TUESDAY: 5-Window Profit Exit Checks
        # ═════════════════════════════════════════════════════════════════
        exit_day = getattr(self.config, 'PH8_EXIT_CHECK_DAY', 1)  # 1 = Tuesday
        exit_times = getattr(self.config, 'PH8_EXIT_CHECK_TIMES', [
            dt_time(9, 15), dt_time(10, 0), dt_time(12, 0),
            dt_time(14, 0), dt_time(15, 15)
        ])

        if weekday == exit_day and self.phase4:
            for check_time in exit_times:
                check_key = check_time.strftime("%H:%M")
                if (current_time >= check_time and
                        check_key not in self._ph8_tuesday_checks_done):
                    try:
                        logger.info(f"📈 PH8 Tuesday exit check @ {check_key}")
                        self.phase4.check_tier3_tuesday_exit(check_time)
                        self._ph8_tuesday_checks_done.add(check_key)
                    except Exception as e:
                        logger.error(f"❌ PH8 Tuesday exit check @ {check_key} failed: {e}")
                        self._ph8_tuesday_checks_done.add(check_key)  # Don't retry

        # ═════════════════════════════════════════════════════════════════
        # DAILY: Phase 6 momentum shadow checks (if shadows exist)
        # (Tier 3 TCAS is handled inside Phase 4's run_monitoring_cycle STEP 4C)
        # ═════════════════════════════════════════════════════════════════
        if self.phase6 and hasattr(self.phase6, 'check_momentum_shadows'):
            try:
                self.phase6.check_momentum_shadows()
            except Exception as e:
                logger.error(f"PH8 momentum shadow check failed: {e}")

    # ═══════════════════════════════════════════════════════════════════════════
    # v4.9.0 - Phase 5 Init Fix NEW: PHASE 5 GAP STRATEGY
    # ═══════════════════════════════════════════════════════════════════════════

    def _run_phase5_gap_strategy(self):
        """
        v4.9.0 UPDATE: Run Phase 5 Gap Strategy (09:15-09:25 entry window)
        
        v5.0.0 Architecture:
        - Phase 5: Scan → Analyze → ChatGPT Approval → Enter → HANDOFF
        - Phase 4: Monitor → TCAS/ILS/Kalman → GTT → Exit (by 12:00 PM)
        
        Timeline:
        - 09:15-09:18: FinBERT sentiment check
        - 09:18-09:20: Gap detection scan
        - 09:20: Flight Plan + ChatGPT approval
        - 09:20-09:25: Entry window (MIS order)
        - 09:25: Handoff to Phase 4
        - Until 12:00: Phase 4 monitors with TCAS/ILS
        - 09:50: Phase 1 starts (regular V-Recovery)
        
        This runs BEFORE Phase 1 and is completely independent.
        """
        if not self.phase5:
            return
        
        now = datetime.now()
        current_time = now.time()
        
        # v5.0.0: Updated time window (09:15 - 09:30 for entry attempts)
        GAP_SCAN_START = dt_time(9, 15)
        GAP_ENTRY_END = dt_time(9, 30)
        PHASE1_START = dt_time(9, 50)
        
        # Only run in the gap strategy window
        if current_time < GAP_SCAN_START or current_time >= GAP_ENTRY_END:
            return
        
        # Reset daily flag at new day
        if self._phase5_last_run_date != now.date():
            self._phase5_run_today = False
            self._phase5_last_run_date = now.date()
            self._phase5_premarket_done = False  # v5.2.0: Reset pre-market flag
        
        # Only run once per day
        if self._phase5_run_today:
            return

        # v1.4.0: Brain directive gate — skip only when VIX is extreme (>30) or explicit circuit block
        if self._ph5_brain_skip:
            _vix_display = getattr(self.phase9, '_live_vix', 'N/A') if self.phase9 else 'N/A'
            logger.info(
                f"🧠 PH9 Directive: PH5 SKIP — gap strategy blocked "
                f"(VIX={_vix_display}, reason: extreme VIX or circuit risk)"
            )
            self._phase5_run_today = True  # don't retry
            return

        # Check if enabled
        if hasattr(self.phase5, 'config') and hasattr(self.phase5.config, 'ENABLED'):
            if not self.phase5.config.ENABLED:
                return
        elif hasattr(self.phase5, 'enabled') and not self.phase5.enabled:
            return
        
        # Run gap strategy
        try:
            logger.info("")
            logger.info("=" * 80)
            logger.info(f"🎯 PHASE 5: GAP STRATEGY STARTING (v{PHASE5_VERSION})")
            logger.info("=" * 80)
            logger.info("")
            
            # v4.8.0 FIX: Phase 5 is self-contained - no Phase 1 dependency
            # Stock universe is already initialized in Phase 5.__init__()
            if hasattr(self.phase5, 'stock_universe'):
                logger.info(f"   Phase 5 using self-contained stock universe ({len(self.phase5.stock_universe)} stocks)")
            
            # Initialize FinBERT if not already done
            if hasattr(self.phase5, 'finbert') and not self.phase5.finbert:
                try:
                    from finbert_analyzer import get_finbert_analyzer
                    self.phase5.finbert = get_finbert_analyzer()
                except Exception as e:
                    logger.warning(f"FinBERT not available for Phase 5: {e}")
            
            # Run the gap strategy
            # v6.0.0: Champion-vs-Champion single execution @ 09:16
            if hasattr(self.phase5, 'run_gap_strategy_v6'):
                gap_trade = self.phase5.run_gap_strategy_v6()
            else:
                gap_trade = self.phase5.run_gap_strategy()
            
            # Mark as run for today
            self._phase5_run_today = True
            
            if gap_trade:
                logger.info(f"✅ Phase 5 completed with trade: {gap_trade.symbol}")
                
                # v5.0.0: Check if handed off to Phase 4
                if PHASE5_VERSION == "5.0.0":
                    from phase5_intraday_engine import GapTradeStatus
                    if gap_trade.status == GapTradeStatus.HANDED_OFF:
                        logger.info(f"   ✅ Position handed to Phase 4 for monitoring")
                        logger.info(f"   Phase 4 will monitor with TCAS/ILS until 12:00 PM")
                    else:
                        logger.info(f"   Status: {gap_trade.status.value}")
                else:
                    # Old v4.9.x behavior - shows P&L (self-contained)
                    if hasattr(gap_trade, 'pnl'):
                        logger.info(f"   P&L: ₹{gap_trade.pnl:+.2f} ({gap_trade.pnl_pct:+.2f}%)")
            else:
                logger.info("ℹ️ Phase 5 completed - no trade taken")
            
            logger.info("")
            logger.info("=" * 80)
            logger.info("🎯 PHASE 5 COMPLETE - CNC backbone starts at 10:00 (Phase 1 scan)")
            logger.info("=" * 80)
            logger.info("")
            
        except Exception as e:
            logger.error(f"❌ Phase 5 Gap Strategy error: {e}")
            import traceback
            logger.error(traceback.format_exc())
            self._phase5_run_today = True  # Mark as run to prevent retry spam
    
    
    def _read_gui_phase_controls(self):
        """v5.6.1: Read phase_controls table from mission_control.db.
        Maps 3-state (OFF/PAPER/LIVE) to config flags.
        Called once per main loop iteration — GUI is the control authority.
        """
        try:
            import sqlite3 as _sql
            db_path = os.path.join("data", "mission_control.db")
            if not os.path.isfile(db_path):
                return

            conn = _sql.connect(f"file:{db_path}?mode=ro", uri=True, timeout=2)
            conn.row_factory = _sql.Row

            try:
                rows = conn.execute("SELECT phase_key, state FROM phase_controls").fetchall()
            except _sql.OperationalError:
                conn.close()
                return  # Table doesn't exist yet

            for row in rows:
                key, state = row['phase_key'], row['state']

                if key == 'ENABLE_PH5':
                    # GAP strategy enable + paper mode
                    setattr(self.config, 'GAP_STRATEGY_ENABLED', state != 'OFF')
                    setattr(self.config, 'PH5_PAPER_MODE', state == 'PAPER')
                elif key == 'ENABLE_PH5A':
                    setattr(self.config, 'PH5A_ENABLED', state != 'OFF')
                    setattr(self.config, 'PH5A_SNIPER_ENABLED', state != 'OFF')
                    setattr(self.config, 'PVAT_ENABLED', state != 'OFF')
                    setattr(self.config, 'PH5A_PAPER_MODE', state == 'PAPER')
                elif key == 'ENABLE_PH6':
                    setattr(self.config, 'PH6_OPTIONS_ADVISORY_ENABLED', state != 'OFF')
                    setattr(self.config, 'PH6_LIVE_ORDERS_ENABLED', state == 'LIVE')
                elif key == 'ENABLE_PH7':
                    setattr(self.config, 'MCX_ENABLED', state != 'OFF')
                    setattr(self.config, 'PH7_PAPER_MODE', state == 'PAPER')
                elif key == 'ENABLE_PH8':
                    setattr(self.config, 'ENABLE_PH8', state != 'OFF')
                    setattr(self.config, 'PH8_PAPER_MODE', state == 'PAPER')

            conn.close()
        except Exception as e:
            logger.debug(f"GUI phase controls read: {e}")

    def run(self):
        """Main event loop"""
        logger.info("")
        logger.info("=" * 80)
        logger.info("STARTING TRADING SYSTEM v4.9.0")
        logger.info("=" * 80)
        logger.info("")
        
        # Initialize phases
        self._initialize_phases()
        
        # ═══════════════════════════════════════════════════════════════════
        # ✅ FIX v3.1.1: AUTO-LOAD ACTIVE.json ON STARTUP
        # ═══════════════════════════════════════════════════════════════════
        # If we start mid-session (after 10:00 AM interrupt), load any
        # existing ACTIVE.json file so we have stocks to monitor!
        
        self._auto_load_or_scan_stocks()
        
        # ═══════════════════════════════════════════════════════════════════
        # ✅ FIX v4.3.2: CENTRALIZED BROKER SYNC AT STARTUP
        # ═══════════════════════════════════════════════════════════════════
        # Detect holdings (NESTLEIND, RAMCOCEM, etc.) immediately on startup,
        # not waiting for Phase 1 scan which may be hours away!
        
        if self.broker_sync:
            # v4.5.1: Skip if already initialized from broker state
            if self.initial_broker_state and self.initial_broker_state.get('success', False) and self._central_positions:
                logger.info("✅ Broker state already initialized from main_orchestrator")
                logger.info(f"   Positions: {len(self._central_positions)}")
                if self.capital_manager:
                    logger.info(f"   Capital Deployed: ₹{self.capital_manager.deployed_capital:,.0f}")
            else:
                try:
                    logger.info("🔄 Running startup broker sync...")
                    
                    # Get all positions from broker
                    broker_positions = self.broker_sync.get_all_positions()
                    
                    if broker_positions:
                        logger.info(f"[OK] 📦 Detected {len(broker_positions)} positions at broker")
                        
                        # If Phase 4 is enabled, add positions to monitoring
                        if self.phase4:
                            for symbol, pos in broker_positions.items():
                                if symbol not in self.phase4.positions:
                                    logger.info(f"   ➕ Adding {symbol} to Phase 4 monitoring")
                                    self.phase4._add_manual_position(symbol, pos.to_dict())
                            
                            self._phase4_started = True  # Mark as started since we have positions
                    else:
                        logger.info("[OK] 📭 No existing positions at broker")
                        
                except Exception as e:
                    logger.error(f"[X] Startup broker sync failed: {e}")
                    import traceback
                    logger.error(traceback.format_exc())
        
        
        # Send startup notification
        if self.telegram:
            monitor_count = len(self.phase2.monitors) if hasattr(self.phase2, 'monitors') else 0
            adaptive_status = "ENABLED" if self.ADAPTIVE_SCAN_ENABLED else "DISABLED"
            
            # v4.3 features status
            phase4_status = "ENABLED" if self.phase4 else "DISABLED"
            admission_status = "ENABLED" if self.admission_controller else "DISABLED"
            scheduler_status = "ENABLED" if self.task_scheduler else "DISABLED"
            
            # v4.6.0 features status
            adaptive_tg = "ON" if getattr(self.config, 'ADAPTIVE_TELEGRAM_ENABLED', True) else "OFF"
            bot_listener = "ON" if getattr(self.config, 'BOT_LISTENER_ENABLED', True) else "OFF"
            health_mon = "ON" if getattr(self.config, 'SYSTEM_HEALTH_ENABLED', True) else "OFF"
            
            # v4.9.0 - Phase 5 Init Fix Phase 5 status
            phase5_status = "ENABLED" if self.phase5 else "DISABLED"
            pmbi_status = "ENABLED" if getattr(self.config, 'PMBI_ENABLED', False) else "DISABLED"

            self.telegram.send_message(
                f"🚀 TRADING SYSTEM v4.9.0 - Phase 5 Init Fix STARTED\n\n"
                f"📊 Monitoring: {monitor_count} stocks\n\n"
                "✨ NEW v4.9.0 - Phase 5 Init Fix Features:\n"
                f"🎯 Phase 5 Gap Strategy: {phase5_status}\n"
                "   (09:20-09:45 daily scalp)\n"
                f"🧠 PMBI Breadth Scan: {pmbi_status}\n\n"
                "v4.6.0 Features:\n"
                f"📱 Adaptive Telegram: {adaptive_tg}\n"
                f"📱 Bot Commands: {bot_listener} (send /help)\n"
                f"🖥️ System Health: {health_mon}\n\n"
                f"🛫 Phase 4 Portfolio Manager: {phase4_status}\n"
                f"🚪 Admission Control: {admission_status}\n"
                f"⏰ Task Scheduler: {scheduler_status}\n\n"
                "Active Features:\n"
                f"🔍 Adaptive Scanning: {adaptive_status}\n"
                "🚨 Trade Starvation Prevention\n"
                "✅ Auto-load on startup"
            )
            
            # ═══════════════════════════════════════════════════════════════
            # v4.6.0 NEW: Start Telegram bot command listener
            # ═══════════════════════════════════════════════════════════════
            try:
                self.telegram.start_command_listener(config=self.config)
                
                # v4.10.0 NEW: Set config reference for /config and /set commands
                if hasattr(self.telegram, 'set_config_reference'):
                    self.telegram.set_config_reference(self.config)

                # v3.5.0: Set orchestrator reference for phase-specific /set commands
                if hasattr(self.telegram, 'set_orchestrator_reference'):
                    self.telegram.set_orchestrator_reference(self)

            except Exception as e:
                logger.error(f"❌ Bot command listener start failed: {e}")
            
            # Reset daily adaptive stats
            try:
                self.telegram.reset_adaptive_daily_stats()
            except Exception:
                pass
        
        logger.info("Entering main event loop...")
        logger.info("")
        
        try:
            while True:
                now = datetime.now()

                # ✅ Connection health check
                if hasattr(self, "health_monitor") and self.health_monitor:
                    self.health_monitor.check_connection()

                # ✅ Cache cleanup (hourly)
                if hasattr(self, "cache_manager") and self.cache_manager and now.minute == 0:
                    self.cache_manager.cleanup_all()
                
                # ═══════════════════════════════════════════════════════════
                # NOTE: Portfolio Recovery Timeout - HANDLED BY PHASE 4
                # ═══════════════════════════════════════════════════════════
                # The old intelligent_portfolio_recovery timeout checking has
                # been removed. Phase 4's TCAS system now handles emergency
                # exits through its ALIM (Altitude Limit) threshold.
                # ═══════════════════════════════════════════════════════════
                
                # ═══════════════════════════════════════════════════════════
                # v5.2.0: Phase 5 PRE-MARKET PREP (09:08-09:14)
                # Runs BEFORE market_open gate — caches indicators from
                # CLOSED daily candles for ultrafast gap scanning at 09:18.
                # ═══════════════════════════════════════════════════════════
                if self.phase5 and not self._phase5_premarket_done:
                    current_t = now.time()
                    # Daily reset
                    if self._phase5_last_run_date != now.date():
                        self._phase5_premarket_done = False
                    
                    if dt_time(9, 8) <= current_t < dt_time(9, 15):
                        try:
                            logger.info("🔧 Triggering Phase 5 pre-market prep...")
                            self.phase5.pre_market_prep()
                            self._phase5_premarket_done = True
                            logger.info("✅ Phase 5 pre-market prep complete")
                        except Exception as e:
                            logger.error(f"❌ Phase 5 pre-market prep failed: {e}")
                            import traceback
                            logger.error(traceback.format_exc())
                            # Don't retry — Phase 5 will fall back to inline fetching
                            self._phase5_premarket_done = True

                # ═══════════════════════════════════════════════════════════
                # v5.5.0: PMBI Pre-Market Breadth Scan (09:11)
                # Runs BEFORE market_open gate — uses historical daily candles
                # Sets self.market_bias for PH5/PH5A/Phase2 priority
                # ═══════════════════════════════════════════════════════════
                if (getattr(self.config, 'PMBI_ENABLED', False) and
                        not self._pmbi_done_today):
                    current_t = now.time()
                    # Daily reset
                    if self._pmbi_last_run_date != now.date():
                        self._pmbi_done_today = False
                    # Trigger at 9:11 (or later if system started late)
                    if current_t >= dt_time(
                            getattr(self.config, 'PMBI_SCAN_TIME_HOUR', 9),
                            getattr(self.config, 'PMBI_SCAN_TIME_MINUTE', 11)):
                        try:
                            self._run_pmbi_scan()
                        except Exception as e:
                            logger.error(f"❌ PMBI scan failed: {e}")
                            import traceback
                            logger.error(traceback.format_exc())
                            # Don't retry — downstream phases work without bias
                            self._pmbi_done_today = True
                            self._pmbi_last_run_date = now.date()

                # ═══════════════════════════════════════════════════════════
                # v1.0.0: Phase 9 AI Fund Manager — Morning Briefing
                # Runs ONCE pre-market. Sets regime, size, phase activation.
                # ═══════════════════════════════════════════════════════════
                if (self.phase9 and not self.phase9._morning_briefing_done
                        and getattr(self.config, 'PH9_MORNING_BRIEFING_ENABLED', False)):
                    current_t = now.time()
                    briefing_time = getattr(self.config, 'PH9_MORNING_BRIEFING_TIME', dt_time(9, 5))
                    if current_t >= briefing_time:
                        try:
                            logger.info("🧠 Triggering Phase 9 Morning Briefing...")
                            # v2.1.0: Self-calibration runs first — reads yesterday's
                            # journal + lessons, writes today's rules to phase knowledge
                            # so every heartbeat sees them (~₹0.10 Haiku call)
                            self.phase9.morning_self_calibration()
                            market_data = self._collect_morning_briefing_data()
                            briefing_result = self.phase9.morning_briefing(market_data)
                            logger.info("✅ Phase 9 Morning Briefing complete")
                            self._ph9_last_heartbeat = now   # start 25-min timer from here

                            # v1.6.0: If Claude was unavailable, run rule-based second brain
                            # to override conservative defaults with data-driven rules
                            _used_defaults = (
                                briefing_result.get('notes', '').startswith('Claude unavailable') or
                                briefing_result.get('notes', '').startswith('Default directives')
                            )
                            if _used_defaults:
                                logger.warning("🧠 Claude unavailable — applying rule-based second brain...")
                                self.phase9._apply_rule_based_fallback(market_data)
                                if self.telegram:
                                    self.telegram.send_message(
                                        f"⚠️ PH9: Claude unreachable — rule-based brain active\n"
                                        f"Regime: {self.phase9.todays_regime} | "
                                        f"{self.phase9.todays_notes[:150]}"
                                    )

                            # v1.3.0: Propagate extended briefing to downstream phases
                            self._propagate_briefing_to_phases()
                            # v1.4.0: Apply per-phase directives from briefing
                            self._apply_phase_directives()

                            # v1.3.0: Recovery Advisor — scan open positions
                            # for underwater trades and ask Claude for recovery plan
                            if getattr(self.config, 'PH9_RECOVERY_ENABLED', True):
                                try:
                                    self._run_ph9_recovery_check()
                                except Exception as _rec_e:
                                    logger.error(f"PH9 Recovery check failed: {_rec_e}")
                        except Exception as e:
                            logger.error(f"❌ Phase 9 Morning Briefing failed: {e}")
                            import traceback
                            logger.error(traceback.format_exc())

                # ═══════════════════════════════════════════════════════════
                # v1.4.0: Phase 9 — 25-minute heartbeat (re-enabled)
                # Full portfolio review every 25 min during market hours.
                # Midday check kept as additional downgrade safety.
                # ═══════════════════════════════════════════════════════════
                _heartbeat_interval_min = getattr(self.config, 'PH9_HEARTBEAT_INTERVAL_MIN', 25)
                if (self.phase9 and self.phase9._morning_briefing_done
                        and getattr(self.config, 'PH9_HEARTBEAT_ENABLED', True)
                        and now.time() >= dt_time(9, 30)  # not before market stabilises
                        and now.time() <= dt_time(15, 10)):
                    _last_hb = getattr(self.phase9, '_last_heartbeat_time', None)
                    _hb_due  = (_last_hb is None or
                                (now - _last_hb).total_seconds() >= _heartbeat_interval_min * 60)
                    if _hb_due:
                        try:
                            logger.info("🧠 Triggering Phase 9 Heartbeat...")
                            _hb_state = self._collect_morning_briefing_data()
                            _hb_state['capital_deployed_pct'] = (
                                self._build_portfolio_context().get('capital_deployed_pct', 0))
                            _hb_state['market_breadth'] = (
                                self.market_bias.get('breadth_label', 'N/A') if self.market_bias else 'N/A')
                            _hb_state['ph2_interval_min'] = round(
                                getattr(self, 'PHASE2_INTERVAL', 300) / 60, 1)

                            # v1.5.0: Capture queue snapshot BEFORE heartbeat call
                            # (heartbeat uses self._signal_queue internally; snapshot here
                            #  lets orchestrator match approved symbols back to full signal)
                            _pre_hb_queue = {
                                q['symbol']: q
                                for q in getattr(self.phase9, '_signal_queue', [])
                            }

                            _hb_result = self.phase9.heartbeat_brief(_hb_state)
                            if _hb_result:
                                # Re-apply phase directives (heartbeat may have changed them)
                                self._apply_phase_directives()
                                # Re-propagate briefing so phases see updated directives
                                self._propagate_briefing_to_phases()
                                # v2.0.0: Enqueue dynamic actions Claude requested
                                _next_actions = _hb_result.get('next_cycle_actions', [])
                                if isinstance(_next_actions, list) and _next_actions:
                                    self._claude_action_queue.extend(
                                        [str(a).strip().upper() for a in _next_actions if a])
                                    logger.info(f"🧠 Claude queued {len(_next_actions)} action(s): {_next_actions}")
                                # Apply any position-level actions
                                _pos_actions = _hb_result.get('position_actions', [])
                                if _pos_actions:
                                    self._apply_position_actions(_pos_actions)
                                # PH8 watchlist from heartbeat
                                _hb_wl = getattr(self.phase9, 'todays_ph8_watchlist_add', [])
                                if _hb_wl and self.phase8 and hasattr(self.phase8, 'add_to_watchlist'):
                                    for _sym in _hb_wl:
                                        try:
                                            self.phase8.add_to_watchlist(_sym)
                                            logger.info(f"🧠 PH9→PH8: Added {_sym} to watchlist")
                                        except Exception as _wle:
                                            logger.debug(f"PH8 watchlist add failed for {_sym}: {_wle}")

                                # v1.5.0: Execute heartbeat-approved queued signals
                                _approved_sigs = _hb_result.get('approved_signals', [])
                                _evaluated_syms = set()
                                if _approved_sigs and self.phase3:
                                    for _appr in _approved_sigs:
                                        _sym = _appr.get('symbol', '')
                                        _evaluated_syms.add(_sym)
                                        if not _appr.get('approved') or not _sym:
                                            continue
                                        _qentry = _pre_hb_queue.get(_sym)
                                        if not _qentry:
                                            logger.warning(f"🧠 HB: {_sym} approved but not in queue — skipped")
                                            continue
                                        # Duplicate-trade guard
                                        if self.phase2 and _sym in self.phase2.traded_today:
                                            logger.info(f"🧠 HB: {_sym} already traded today — skipping")
                                            continue
                                        # Re-entry guard
                                        if self.phase4 and hasattr(self.phase4, 'is_reentry_allowed'):
                                            _ok, _why = self.phase4.is_reentry_allowed(_sym)
                                            if not _ok:
                                                logger.warning(f"🧠 HB: {_sym} re-entry blocked — {_why}")
                                                continue
                                        _sig = dict(_qentry.get('_signal_raw', {}))
                                        # Apply heartbeat size adjustment
                                        _sadj = float(_appr.get('size_adjustment', 1.0) or 1.0)
                                        if _sadj != 1.0:
                                            _sig['quantity'] = max(1, int(_qentry['quantity'] * _sadj))
                                        try:
                                            logger.info(f"🧠 HB: Executing approved {_sym} "
                                                       f"{_qentry['direction']} qty={_sig.get('quantity', _qentry['quantity'])}")
                                            _pos = self.phase3.execute_signal_realtime(_sig)
                                            if _pos:
                                                if self.phase2:
                                                    self.phase2.traded_today.add(_sym)
                                                if self.phase4:
                                                    try:
                                                        self.phase4.on_position_opened(_pos, _sig)
                                                    except Exception as _p4e:
                                                        logger.error(f"PH4 register error for {_sym}: {_p4e}")
                                                if self.starvation_prevention:
                                                    self.starvation_prevention.record_trade()
                                                logger.info(f"🧠 HB: ✅ {_sym} position opened")
                                            else:
                                                logger.warning(f"🧠 HB: ❌ {_sym} execution failed")
                                        except Exception as _hexe:
                                            logger.error(f"🧠 HB: signal execution error {_sym}: {_hexe}")

                                # v1.5.0: Remove evaluated entries from queue (approved + rejected)
                                if _evaluated_syms:
                                    self.phase9._signal_queue = [
                                        q for q in self.phase9._signal_queue
                                        if q['symbol'] not in _evaluated_syms
                                    ]
                                    logger.info(f"🧠 HB: Queue cleaned — {len(_evaluated_syms)} evaluated, "
                                               f"{len(self.phase9._signal_queue)} remaining")

                            logger.info("✅ Phase 9 Heartbeat complete")
                        except Exception as e:
                            logger.error(f"❌ Phase 9 Heartbeat failed: {e}")

                if (self.phase9 and self.phase9._morning_briefing_done
                        and not getattr(self.phase9, '_midday_check_done', False)
                        and getattr(self.config, 'PH9_MIDDAY_CHECK_ENABLED', True)):
                    midday_t = getattr(self.config, 'PH9_MIDDAY_CHECK_TIME', dt_time(12, 0))
                    if now.time() >= midday_t:
                        try:
                            logger.info("🧠 Triggering Phase 9 Midday Check...")
                            market_data = self._collect_morning_briefing_data()
                            self.phase9.midday_check(market_data)
                            logger.info("✅ Phase 9 Midday Check complete")
                        except Exception as e:
                            logger.error(f"❌ Phase 9 Midday Check failed: {e}")

                # ═══════════════════════════════════════════════════════════
                # v1.3.2: Phase 9 — Post-ALIM Re-entry Plan Execution
                # phase9.post_exit_reentry_advisor() stores approved plans in
                # _pending_reentry_plans. We pick them up here within seconds
                # of the ALIM exit and execute via phase3.
                # ═══════════════════════════════════════════════════════════
                if (self.phase9 and self.phase3
                        and getattr(self.config, 'PH9_REENTRY_ENABLED', True)):
                    _pending = getattr(self.phase9, '_pending_reentry_plans', {})
                    for _sym, _plan in list(_pending.items()):
                        try:
                            _act = _plan.get('action', 'STAND_DOWN')
                            if _act == 'REENTER':
                                logger.info(f"🔁 PH9 REENTRY: executing {_sym} "
                                            f"{_plan.get('direction','LONG')} "
                                            f"qty={_plan.get('reentry_qty',1)} "
                                            f"@ ₹{_plan.get('reentry_price',0):.2f}")
                                _sig = {
                                    'symbol':       _sym,
                                    'direction':    _plan.get('direction', 'LONG'),
                                    'quantity':     int(_plan.get('reentry_qty', 1)),
                                    'entry_price':  float(_plan.get('reentry_price', 0)),
                                    'stop_price':   float(_plan.get('new_stop', 0)),
                                    'target_price': float(_plan.get('recovery_target', 0)),
                                    'product':      _plan.get('product', 'MIS'),
                                    'source':       'PH9_REENTRY',
                                    '_ph9_source':  'PH9_REENTRY',
                                }
                                _pos = self.phase3.execute_signal_realtime(_sig)
                                if _pos:
                                    logger.info(f"🔁 PH9 REENTRY: ✅ {_sym} re-entered")
                                    if self.phase4:
                                        try:
                                            self.phase4.on_position_opened(_pos, _sig)
                                        except Exception as _p4e:
                                            logger.error(f"PH4 register error for reentry {_sym}: {_p4e}")
                                    if self.phase2:
                                        self.phase2.traded_today.add(_sym)
                                else:
                                    logger.warning(f"🔁 PH9 REENTRY: ❌ {_sym} execution failed")

                            elif _act == 'WATCHLIST':
                                if self.phase8 and hasattr(self.phase8, 'add_to_watchlist'):
                                    self.phase8.add_to_watchlist(_sym)
                                    logger.info(f"🔁 PH9 REENTRY: {_sym} → Phase 8 watchlist")

                        except Exception as _re_exec_e:
                            logger.error(f"PH9 reentry execution error for {_sym}: {_re_exec_e}")
                        finally:
                            # Always remove processed plan — success or failure
                            _pending.pop(_sym, None)

                # Check for hard stop
                if now.time() >= self.HARD_STOP:
                    self._handle_market_close()
                    break

                # v8.1.0: User-initiated shutdown via /shutdown confirm
                if getattr(self, '_user_shutdown', False):
                    logger.critical("User-initiated shutdown — breaking main loop")
                    break

                # v5.6.1: GUI → Orchestrator phase control (3-state)
                self._read_gui_phase_controls()

                # Check for market open
                if not self._is_market_open():
                    time.sleep(60)
                    continue
                
                # ═══════════════════════════════════════════════════════════
                # v4.9.0 - Phase 5 Init Fix NEW: PHASE 5 GAP STRATEGY (09:18-09:45)
                # ═══════════════════════════════════════════════════════════
                # Runs BEFORE Phase 1 (09:50) - completely independent
                # Gap detection, FinBERT sentiment alignment, quick scalp
                self._run_phase5_gap_strategy()

                # ═══════════════════════════════════════════════════════════
                # 🔷 PH5A v2 SNIPER — INDEPENDENT MODE (v5.9.0)
                # Auto-fires after Phase 5 exclusive window ends (09:55).
                # Rescans every 5 min if pipeline is empty (persistent hunter).
                # No ChatGPT gate — GUI toggle is the only control.
                # ═══════════════════════════════════════════════════════════
                _hard_cutoff_str = getattr(self.config, 'PH5A_WATCH_HARD_CUTOFF', '14:00')
                _hard_h, _hard_m = map(int, _hard_cutoff_str.split(':'))
                _hard_cutoff = dt_time(_hard_h, _hard_m)

                if (self.phase5a and
                        getattr(self.config, 'PH5A_SNIPER_ENABLED', True) and
                        not self._is_phase5_window() and
                        not self._ph5a_brain_pause and
                        now.time() < _hard_cutoff):

                    _watch_dur = getattr(self.config, 'PH5A_WATCH_DURATION_MINUTES', 45)
                    _rescan_interval = getattr(self.config, 'PH5A_RESCAN_INTERVAL_MINUTES', 5) * 60

                    # ── AUTO-START: First scan after Phase 5 window ends ──
                    if not self._ph5a_started_today:
                        self._ph5a_started_today = True
                        self._ph5a_hunting = True
                        self._ph5a_last_scan_time = None
                        self._ph5a_scan_count = 0
                        self.ph5a_scan_complete = False
                        self.ph5a_done = False
                        logger.info("")
                        logger.info("=" * 60)
                        logger.info("🔷 PH5A INDEPENDENT MODE — Auto-started")
                        logger.info(f"   Time: {now.strftime('%H:%M:%S')}")
                        logger.info(f"   Rescan interval: {_rescan_interval // 60} min")
                        logger.info(f"   Hard cutoff: {_hard_cutoff_str}")
                        logger.info("=" * 60)
                        logger.info("")

                        if self.telegram:
                            self.telegram.send_message(
                                f"🔷 PH5A SNIPER AUTO-STARTED\n\n"
                                f"Mode: Independent (persistent hunter)\n"
                                f"Rescan: every {_rescan_interval // 60} min if pipeline empty\n"
                                f"Cutoff: {_hard_cutoff_str}"
                            )

                    # ── HUNTING MODE: Scan/rescan for pipeline stocks ──
                    if self._ph5a_hunting:
                        # Check rescan interval
                        _should_scan = False
                        if self._ph5a_last_scan_time is None:
                            _should_scan = True  # First scan
                        else:
                            _elapsed = (now - self._ph5a_last_scan_time).total_seconds()
                            if _elapsed >= _rescan_interval:
                                _should_scan = True

                        if _should_scan:
                            try:
                                self._ph5a_scan_count += 1

                                # v5.9.0: Reset scanner state before rescan (keeps levels warm)
                                if self._ph5a_scan_count > 1:
                                    self.phase5a.reset_for_rescan()

                                logger.info(f"🔷 PH5A Sniper scan #{self._ph5a_scan_count} (hunting mode)")
                                self.phase5a.run_sniper_scan()
                                self._ph5a_last_scan_time = now

                                # Sync state from scanner
                                self.ph5a_scan_complete = self.phase5a.ph5a_scan_complete

                                # Check if pipeline has stocks → switch to watch mode
                                _pipeline = getattr(self.phase5a, 'sniper_pipeline', []) or []
                                if len(_pipeline) > 0:
                                    self._ph5a_hunting = False  # Switch to watch mode
                                    self.ph5a_done = False
                                    logger.info(f"🔷 PH5A Pipeline: {len(_pipeline)} stock(s) → WATCH mode")
                                else:
                                    # Scanner sets ph5a_done=True on empty result — override for persistent hunting
                                    self.ph5a_done = False
                                    logger.info(f"🔷 PH5A Pipeline empty → rescan in {_rescan_interval // 60} min")
                            except Exception as e:
                                logger.error(f"PH5A Sniper scan error: {e}")
                                import traceback
                                logger.error(traceback.format_exc())
                                self._ph5a_last_scan_time = now  # Prevent rapid retry on error

                    # ── WATCH MODE: Monitor pipeline for breakout triggers ──
                    # Watch window = last scan time + watch duration, capped at hard cutoff
                    if self.ph5a_scan_complete and not self._ph5a_hunting:
                        _watch_start = self._ph5a_last_scan_time or now
                        _watch_end_dt = _watch_start + timedelta(minutes=_watch_dur)
                        _watch_end = _watch_end_dt.time()
                        if _watch_end > _hard_cutoff:
                            _watch_end = _hard_cutoff

                        if not self.ph5a_done and now.time() <= _watch_end:
                            # Active watch — monitor breakout triggers
                            try:
                                self.phase5a.run_sniper_watch()
                            except Exception as e:
                                logger.error(f"PH5A Sniper watch error: {e}")

                        elif not self.ph5a_done and not getattr(self.phase5a, 'ph5a_watch_closed', False):
                            # Watch window expired — close watch
                            try:
                                logger.info(f"🔷 PH5A Watch window expired at {_watch_end.strftime('%H:%M')}")
                                self.phase5a.close_watch_window()
                                self.ph5a_done = self.phase5a.ph5a_done

                                # If no entries were triggered, return to hunting
                                _had_triggers = any(s.triggered for s in (getattr(self.phase5a, 'sniper_pipeline', []) or []))
                                if not _had_triggers:
                                    self._ph5a_hunting = True
                                    self.ph5a_done = False
                                    logger.info("🔷 PH5A No triggers → back to HUNTING mode")
                            except Exception as e:
                                logger.error(f"PH5A watch close error: {e}")

                        elif not self.ph5a_done and getattr(self.phase5a, 'ph5a_watch_closed', False):
                            # Watch closed, manage exits for open positions
                            try:
                                self.phase5a.manage_sniper_exits()
                                self.ph5a_done = self.phase5a.ph5a_done

                                # If all positions fully exited → done for today
                                if self.ph5a_done:
                                    logger.info("🔷 PH5A All exits done → DONE for today")
                            except Exception as e:
                                logger.error(f"PH5A exit management error: {e}")

                # Check for scheduled interrupts (Phase 1 scans)
                self._check_for_interrupts()
                
                # ═══════════════════════════════════════════════════════════
                # v4.6.0 NEW: Process Telegram bot commands
                # ═══════════════════════════════════════════════════════════
                self._handle_telegram_commands()

                # v1.4.0: Warn and discard timed-out manual trade confirmations
                self._check_trade_confirmation_timeouts()

                # v4.6.0: Handle user-requested Phase 1 scan (/scan command)
                self._handle_user_scan_request()

                # v2.0.0: Drain Claude's dynamic action queue (one action per loop tick)
                if self._claude_action_queue:
                    _action = self._claude_action_queue.pop(0)
                    try:
                        self._execute_claude_action(_action)
                    except Exception as _ace:
                        logger.error(f"Claude action '{_action}' failed: {_ace}")

                # v5.4.1: CNC window with IDLE_HUNT detection
                if self._should_run_phase2():
                    if self._is_cnc_idle():
                        self._log_idle_compact()
                    else:
                        self._run_phase2_cycle()

                # v4.9.0 - Phase 5 Init Fix TC-04 FIX: Run Phase 3 checks with interval management
                # Prevents monitoring tick stacking during API lag
                current_time = time.time()
                if current_time - self.last_phase3_check_time >= self.MIN_PHASE3_INTERVAL:
                    self._run_phase3_fast_check()
                    self.last_phase3_check_time = current_time
                else:
                    # Skip tick if interval not elapsed (prevents stacking)
                    elapsed = current_time - self.last_phase3_check_time
                    remaining = self.MIN_PHASE3_INTERVAL - elapsed
                    logger.debug(f"⏭️ Skipping Phase 3 check (last {elapsed:.1f}s ago, next in {remaining:.1f}s)")
                
                # 📡 v4.3.2: Periodic broker sync (when Phase 4 has no positions)
                self._run_periodic_broker_sync()
                
                # 📡 v4.5.0: Central position state broker sync
                self.broker_sync_positions()
                
                # 🛫 Check Phase 4 special time events (v4.3 NEW!)
                self._check_phase4_special_times()

                # ═══════════════════════════════════════════════════════════
                # v5.4.1 ENHANCED: Phase 6 Options Advisory
                # EXEMPTION: Runs even during MIS takeover (theta decay)
                # Three-speed: 30 min idle, 2 min TCAS active, 50s MIS active
                # ═══════════════════════════════════════════════════════════
                if self.phase6:
                    # Determine check interval based on context
                    if self._is_mis_active():
                        # v5.4.1: MIS active — still check Phase 6 (theta exemption)
                        # Every ~50s (5 x 10s Tier1 sleep cycles)
                        check_interval = 50
                    elif hasattr(self.phase6, 'has_tcas_active') and self.phase6.has_tcas_active():
                        check_interval = getattr(self.config, 'PH6_TCAS_CHECK_INTERVAL_SEC', 120)
                    else:
                        check_interval = getattr(self.config, 'PH6_PREMIUM_CHECK_INTERVAL_MIN', 30) * 60
                    if (time.time() - self._ph6_last_check) >= check_interval:
                        try:
                            self.phase6.check_open_advisories()
                            self._ph6_last_check = time.time()
                        except Exception as e:
                            logger.error(f"Phase 6 premium check failed: {e}")

                # ═══════════════════════════════════════════════════════════
                # v8.0.0: Phase 8 Weekly Momentum Schedule
                # Wed: scan + VWAP entry | Tue: 5-window exit checks
                # ═══════════════════════════════════════════════════════════
                self._run_phase8_schedule()

                # ═══════════════════════════════════════════════════════════
                # v4.6.0 NEW: Periodic system health check
                # ═══════════════════════════════════════════════════════════
                if self.telegram and getattr(self.config, 'SYSTEM_HEALTH_ENABLED', True):
                    try:
                        if self.telegram.should_send_health(self.config):
                            health_info = self._collect_health_info()
                            self.telegram.send_system_health(extra_info=health_info)
                    except Exception as e:
                        logger.debug(f"Health check error: {e}")
                
                # ═══════════════════════════════════════════════════════════
                # v4.10.0 NEW: Proactive battery monitoring
                # Alerts at 80% (full), 20% (low), and plug/unplug events
                # ═══════════════════════════════════════════════════════════
                if self.telegram and hasattr(self.telegram, 'check_battery_alerts'):
                    try:
                        self.telegram.check_battery_alerts()
                    except Exception as e:
                        logger.debug(f"Battery check error: {e}")
                
                # Send heartbeat
                self._send_heartbeat()
                
                # Sleep
                sleep_time = self._get_sleep_time()
                time.sleep(sleep_time)
                
        except KeyboardInterrupt:
            logger.info("\n[!] Keyboard interrupt received")
            self._handle_market_close()
        except Exception as e:
            logger.error(f"[X] Fatal error in main loop: {e}")
            logger.error(traceback.format_exc())
            raise
        finally:
            # v4.6.0: Stop bot listener
            if self.telegram and hasattr(self.telegram, 'stop_command_listener'):
                try:
                    self.telegram.stop_command_listener()
                except Exception:
                    pass
            
            logger.info("")
            logger.info("=" * 80)
            logger.info("TRADING SYSTEM STOPPED")
