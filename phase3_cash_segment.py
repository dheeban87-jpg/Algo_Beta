"""
PHASE 3: CASH SEGMENT ORDER EXECUTION v4.9.0 (Entry-Only Separation)
============================================================================

🔄 CASH SEGMENT TRADING (NOT OPTIONS!)
⚡ COMPLETELY AUTONOMOUS (NO MANUAL INTERVENTION!)

🔧 v4.9.0 - ENTRY-ONLY SEPARATION (2026-02-04)
─────────────────────────────────────────────────────
✅ ARCHITECTURE: Phase 3 now handles ENTRY ONLY, Phase 4 handles EXIT
   - REMOVED: check_position_exits() (~218 lines) → Phase 4
   - REMOVED: check_manual_stops() (~113 lines) → Phase 4  
   - REMOVED: _close_position() (~275 lines) → Phase 4._place_sell_order()
   - REMOVED: _exit_position_by_symbol() → Phase 4._execute_exit()
   - REMOVED: _partial_exit() → Phase 4._execute_partial_exit()
   - REMOVED: _check_position_exit() → Phase 4 TCAS/ILS monitoring
   
✅ KEPT: close_all_positions() - Now delegates to Phase 4
✅ KEPT: has_open_positions() - Simple utility method
✅ KEPT: All entry logic (BUY orders, GTT placement)
   
Total lines removed: ~792 lines of exit logic

PHASE RESPONSIBILITIES (v4.9.0):
─────────────────────────────────────
PHASE 3 (Entry-Only):
   - execute_signal_realtime() - BUY order execution
   - _place_order() - Order placement
   - _wait_for_fill() - Fill confirmation
   - _place_gtt_orders() - Initial GTT protection
   - capital_manager.deploy() - Capital deployment
   
PHASE 4 (Monitor + Exit):
   - run_monitoring_cycle() - Position monitoring
   - TCAS/ILS - Stop/target detection
   - ChatGPT decisions - Intelligent exits
   - _place_sell_order() - SELL order execution
   - capital_manager.release() - Capital release

🔧 v4.7.2 - MINIMUM VIABLE TRADE FIX (2026-02-03)
─────────────────────────────────────────────────────
✅ FIX: MINIMUM CAPITAL FLOOR FOR 1-SHARE TRADES
   - Problem: Score-based sizing (e.g., 0.35x for WEAK scores) could reduce
     capital below minimum needed for even 1 share
   - Example: ₹2000 × 0.35 = ₹700, but stock costs ₹1140
   - Fix: Apply minimum floor = stock_ltp × 1.05 (5% buffer)
   - Ensures every valid signal can buy at least 1 share
   - Preserves intelligent sizing when capital is sufficient

🔧 v4.7.1 - RETEST FIXES (2026-02-01)
─────────────────────────────────────────────────────
✅ FIX-01: BUY Order Fill Timeout Configurable (RETEST-03)
   - Poll constants now read from config.py (BUY_FILL_MAX_POLL_ATTEMPTS, BUY_FILL_POLL_INTERVAL)
   - Default: 15 polls × 2s = 30s (was hardcoded 5×2s = 10s)
   - "Still waiting" Telegram alert at 50% timeout
   - Prevents premature cancellation of valid pending orders

✅ FIX-04: GTT Retry Before Manual Stop Fallback (RETEST-06)
   - Retry loop: up to GTT_PLACEMENT_RETRIES (default 2) retries, 3s delay
   - Catches transient failures (network blip, rate limit)
   - Only falls to manual stop after ALL retries exhausted
   - Recovery Telegram alert if GTT succeeds on retry

🔧 v4.7.0 - CRITICAL RESILIENCE FIXES (2026-02-01)
─────────────────────────────────────────────────────
✅ FIX TC-05: Partial Fill Handling
   - Polls order_history() for filled_quantity vs planned quantity
   - Detects partial fills → cancels unfilled qty → uses actual filled qty
   - Capital deployed and GTT placed for actual filled quantity only
   - Telegram alert on partial fills

✅ FIX TC-06: GTT Fallback Manual Stop Protection (MOVED TO PHASE 4)
   - Manual stop monitoring now handled by Phase 4

✅ FIX TC-10: SELL Order Retry with Market Order Fallback (MOVED TO PHASE 4)
   - SELL retry logic now in Phase 4._place_sell_order()

🔧 v4.5.3 - CAPITAL MANAGER INTEGRATION (2026-01-29)
─────────────────────────────────────────────────────
✅ FIX #1: Capital Manager integration for deploy/release lifecycle
   - deploy() called after successful BUY order fill
   - release() NOW CALLED BY PHASE 4 after successful SELL order fill

CAPITAL FLOW (v4.9.0):
─────────────
Phase 2: can_add_position() → signal approved
Phase 3: execute_signal() → order filled → capital_manager.deploy()
Phase 4: _place_sell_order() → SELL filled → capital_manager.release(pnl)

🔧 v4.5.2 - SAFETY ENHANCEMENTS (2026-01-28)
─────────────────────────────────────────────
✅ FIX #1: EXIT_IN_PROGRESS state prevents duplicate SELL orders
   - Status transitions: OPEN → EXIT_IN_PROGRESS → CLOSED
   - Now managed by Phase 4 via _place_sell_order()

✅ FIX #2: Broker reconciliation on startup
   - _reconcile_with_broker() compares JSON vs kite.positions()
   - Detects orphan positions (at broker but not in JSON)
   - Detects ghost positions (in JSON but not at broker)
   - Sends CRITICAL alerts for mismatches

✅ FIX #3: gtt_protected flag for unprotected positions
   - Tracks whether GTT stop-loss is active
   - CRITICAL Telegram alert if position has no GTT protection
   - Visible in position dict for cockpit monitoring

POSITION STATES (v4.5.2):
─────────────────────────────
✅ OPEN              - Active position, being monitored
✅ EXIT_IN_PROGRESS  - SELL order placed, waiting for fill
✅ CLOSED            - Position fully exited

✅ v3.4.0 - PORTFOLIO RECOVERY INTEGRATION!
   - Compatible with position-scoped recovery system
   - Dict-based position tracking (symbol -> position data)
   - Coordinates with admission controller
   - Supports emergency exits from orchestrator

🧠 v3.0.0 - INTELLIGENT ENGINE INTEGRATION!
   - Uses intelligent signal recommendations for position sizing
   - Adaptive stop loss/target based on market regime
   - Reads intelligent_score, recommended_capital from signals
   - Supports mixed market trading with reduced positions

✅ v2.4.0 - SMART CAPITAL CHECK!
   - Checks ACTUAL Zerodha balance BEFORE calculating quantity
   - Uses MIN(config_capital, actual_usable) for position sizing
✅ v2.3.0 - CORRECTED LOG MESSAGE!
   - Position sizing: CAPITAL-BASED (not hardcoded 1 share)
✅ v2.2.0 - KITE INSTANCE FIX!
   - Now accepts kite instance from orchestrator (already authenticated)
✅ v2.1.0 - CRITICAL FIXES APPLIED!

CRITICAL: This places REAL orders with REAL money in CASH SEGMENT.
Only enable when ready to trade live.

v2.1.0 CRITICAL FIXES:
─────────────────────────────
✅ FIX #1: TRAILING STOP LOGIC CORRECTED!
   - OLD BUG: Compared to entry_price → converted winners to losers
   - NEW: Tracks max_price, trails from highest point
   - Result: +2% winners stay profitable, not -2% losers!

✅ FIX #2: EMERGENCY BUFFER ENFORCED!
   - Emergency buffer (₹4,000) now checked before every trade
   - System will NEVER deploy 100% capital

✅ FIX #3: DAILY LOSS CIRCUIT BREAKER!
   - Tracks daily realized P&L
   - Halts trading when MAX_DAILY_LOSS exceeded

MAJOR CHANGES IN v2.0.0 (CASH SEGMENT):
─────────────────────────────────────────
✅ Exchange: NSE (Cash segment, not NFO)
✅ Product: CNC (delivery) or MIS (intraday)
✅ Quantity: CAPITAL-BASED (₹8,000/trade + AI multiplier)
✅ Profit target: +3% (realistic for cash)
✅ Stop loss: -2% (realistic for cash)
✅ Direct stock trading (HDFCBANK, not HDFCBANK26JAN1650CE)
✅ Autonomous execution (no manual steps)

PHASE 4 INTEGRATION (v4.0.0):
─────────────────────────────────
✅ GTT order placement after entry
✅ GTT modification methods for trailing/widening
✅ GTT cancellation before manual exit
✅ GTT status checking for Phase 4 monitoring
⚠️  Exit decisions now made by Phase 4 Portfolio Manager

SAFETY FEATURES:
─────────────────
✅ Position sizing = BASE_CAPITAL / LTP * AI_multiplier
✅ Maximum 2 positions per stock
✅ Capital availability checks
✅ Entry window: Wednesday 9:15-11:00 AM
✅ Exit window: Thursday 11:00 AM - 2:00 PM
✅ 7-point pre-trade validation
✅ Real-time position monitoring
✅ Automatic exits (profit/stop/time)

WORKFLOW:
─────────
1. Load entry_signals.json from Phase 2
2. Validate each signal (7 checks)
3. Place BUY order: 1 share at market price (NSE)
4. Monitor position every 5 minutes
5. Exit when +3% profit, -2% stop, or time reached
6. Save trade to trades.json + Excel

Default: PAPER TRADING (ENABLE_PHASE3 = False)
Live trading: ENABLE_PHASE3 = True
"""

import os
import sys
import json
import time
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import traceback

# Kite Connect API
from kiteconnect import KiteConnect
from chatgpt_strategic_advisor import ChatGPTStrategicAdvisor

# Excel export (optional)
try:
    import pandas as pd
    EXCEL_AVAILABLE = True
except ImportError:
    EXCEL_AVAILABLE = False

# ✅ BUG FIX: Configure logging BEFORE it's used!
logger = logging.getLogger('Phase3_CashSegment')

# ═══════════════════════════════════════════════════════════════════════════
# ML DATA LOGGER (Week 1+ Integration - Collect from Day 1!)
# ═══════════════════════════════════════════════════════════════════════════
try:
    from ml_data_logger import MLDataLogger
    ML_LOGGER_AVAILABLE = True
except ImportError:
    ML_LOGGER_AVAILABLE = False
    logger.warning("⚠️ ml_data_logger not found - ML features will not be logged")


# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def load_json(filepath: str) -> Optional[dict]:
    """Load JSON file"""
    try:
        if not os.path.exists(filepath):
            logger.warning(f"File not found: {filepath}")
            return None
        
        with open(filepath, 'r') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Error loading {filepath}: {e}")
        return None


def save_json(filepath: str, data: dict):
    """Save JSON file"""
    try:
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(filepath, 'w') as f:
            json.dump(data, f, indent=2)
        logger.debug(f"Saved: {filepath}")
    except Exception as e:
        logger.error(f"Error saving {filepath}: {e}")


def append_to_json(filepath: str, data: dict):
    """Append to JSON array file"""
    try:
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        
        # Load existing data
        if os.path.exists(filepath):
            with open(filepath, 'r') as f:
                existing = json.load(f)
            if not isinstance(existing, list):
                existing = [existing]
        else:
            existing = []
        
        # Append new data
        existing.append(data)
        
        # Save
        with open(filepath, 'w') as f:
            json.dump(existing, f, indent=2)
        
        logger.debug(f"Appended to: {filepath}")
    except Exception as e:
        logger.error(f"Error appending to {filepath}: {e}")


# ═══════════════════════════════════════════════════════════════════════════════
# POSITION STATES (v4.5.2)
# ═══════════════════════════════════════════════════════════════════════════════

class PositionState:
    """
    Position state constants for v4.5.2 state machine.
    
    State Transitions:
    - OPEN → EXIT_IN_PROGRESS (when SELL order placed)
    - EXIT_IN_PROGRESS → CLOSED (when SELL order filled)
    - EXIT_IN_PROGRESS → OPEN (if SELL fails, position kept for retry)
    
    This prevents duplicate SELL orders during shutdown overlap.
    """
    OPEN = 'OPEN'                          # Active position, being monitored
    EXIT_IN_PROGRESS = 'EXIT_IN_PROGRESS'  # SELL order placed, waiting fill
    CLOSED = 'CLOSED'                      # Position fully exited


# ============================================================================
# PHASE 3 CASH SEGMENT EXECUTOR
# ============================================================================

class Phase3CashSegmentExecutor:
    """
    Cash segment order executor for autonomous trading.
    
    v4.7.0: Critical Resilience Fixes
    - TC-05: Partial fill detection and handling
    - TC-06: GTT fallback manual stop protection
    - TC-10: SELL retry with market order fallback
    
    v4.5.3: Capital Manager Integration
    - deploy() called after successful BUY fill
    - release() called after successful SELL fill with P&L
    - Centralized capital tracking across all phases
    
    Key differences from options:
    - Exchange: NSE (not NFO)
    - Symbol: Direct stock symbol (e.g., HDFCBANK)
    - Quantity: Capital-based (not hard-coded)
    - Product: CNC or MIS
    - Profit target: +3% (configurable)
    - Stop loss: -2% (configurable)
    """
    
    def __init__(self, kite, config, telegram, capital_manager=None):
        """
        Initialize cash segment executor.
        
        v4.5.3: Added capital_manager parameter for centralized capital tracking.
        
        Args:
            kite: Authenticated Kite Connect instance
            config: System configuration
            telegram: Telegram notifier instance
            capital_manager: Optional CapitalManager instance (v4.5.3+)
        """
        self.config = config
        self.telegram = telegram
        
        self.strategic_advisor = None  # Will be set by orchestrator
        self.options_advisor = None    # v6.0: Phase 6 Options Advisory (set by orchestrator)
        # Use passed Kite instance (already authenticated)
        if getattr(config, 'MASTER_PAPER_MODE', False):
            from paper_kite_proxy import PaperKiteProxy
            if not isinstance(kite, PaperKiteProxy):
                kite = PaperKiteProxy(kite, tag='PH3')
            logger.info("📝 Phase 3: PAPER MODE — all order/GTT writes are blocked from the broker")
        self.kite = kite
        
        # ═══════════════════════════════════════════════════════════════════
        # v4.5.3 NEW: Capital Manager Integration
        # ═══════════════════════════════════════════════════════════════════
        self.capital_manager = capital_manager
        if self.capital_manager:
            logger.info("✅ Capital Manager integrated - centralized capital tracking")
        else:
            logger.info("ℹ️  Capital Manager not provided - using internal tracking")
        
        # Capital tracking (fallback if no Capital Manager)
        # Capital tracking - read from Capital Manager if available
        if self.capital_manager:
            self.total_capital = self.capital_manager.total_capital
            logger.info(f"   💰 Using Capital Manager total: ₹{self.total_capital:,.0f}")
        else:
            self.total_capital = config.TOTAL_CAPITAL
            logger.info(f"   💰 Using config fallback: ₹{self.total_capital:,.0f}")
        self.capital_used = 0
        
        # ═══════════════════════════════════════════════════════════════════
        # v4.9.0: POSITION DELEGATION TO ORCHESTRATOR (Single Source of Truth)
        # ═══════════════════════════════════════════════════════════════════
        # Positions are now managed by orchestrator._central_positions
        # Phase 3 accesses positions via @property that delegates to orchestrator
        # This prevents divergence between Phase 3 and Phase 4 position dicts
        #
        # _local_positions is used as fallback when orchestrator not set (standalone mode)
        self._local_positions = {}  # Fallback for standalone operation
        
        # v4.7.0 FIX TC-06: Manual stop tracking for GTT fallback
        self.manual_stop_positions = {}  # symbol -> {stop_price, entry_time, last_check, emergency_timeout}
        
        # ═══════════════════════════════════════════════════════════════════
        # v4.7.2 NEW: STOCK COOLDOWN TRACKING (Prevents re-entry loop!)
        # ═══════════════════════════════════════════════════════════════════
        # Problem: Stock closes with profit → immediately re-enters → loses money
        # Solution: Track recently closed stocks and block re-entry for cooldown period
        self.recently_closed_stocks = {}  # symbol -> {'closed_at': datetime, 'pnl': float, 'reason': str}
        self.COOLDOWN_MINUTES = getattr(config, 'STOCK_COOLDOWN_MINUTES', 30)  # Default 30 min cooldown
        self.DAILY_STOCK_LIMIT = getattr(config, 'DAILY_STOCK_TRADE_LIMIT', 2)  # Max 2 trades per stock per day
        self.daily_stock_trades = {}  # symbol -> count (resets daily)
        self._last_daily_reset = datetime.now().date()
        logger.info(f"   🛡️ Stock cooldown: {self.COOLDOWN_MINUTES} minutes after close")
        logger.info(f"   🛡️ Daily stock limit: {self.DAILY_STOCK_LIMIT} trades per stock")
        
        # 📡 v4.5.0 NEW: Orchestrator reference for central position state
        self.orchestrator = None  # Set by orchestrator after init
        
        # 🛡️ v3.4.0 NEW: Portfolio Recovery Integration
        # This will be set by orchestrator if portfolio recovery is enabled
        self.portfolio_recovery = None
        
        # 🧠 Adaptive stop/target (set by Intelligent Engine per signal)
        self.adaptive_stop_loss = None  # Will be set per signal if intelligent
        self.adaptive_target = None     # Will be set per signal if intelligent
        
        # ✅ STEP 2: Initialize ML Data Logger
        if ML_LOGGER_AVAILABLE:
            self.ml_logger = MLDataLogger()
            logger.info("✅ ML Data Logger initialized - Features will be logged!")
        else:
            self.ml_logger = None
            logger.warning("⚠️ ML Data Logger not available")
        
        # ═══════════════════════════════════════════════════════════════════
        # 🧠 STRATEGIC ADVISOR MODULE - AI ORDER PARAMS & EXIT STRATEGY
        # ═══════════════════════════════════════════════════════════════════
        
        if config.ENABLE_CHATGPT_STRATEGIC_ADVISOR:
            try:
                logger.info("⏳ Initializing ChatGPT Strategic Advisor...")
                self.strategic_advisor = ChatGPTStrategicAdvisor(
                    api_key=config.CHATGPT_API_KEY,
                    model=config.STRATEGIC_ADVISOR_MODEL
                )
                logger.info("✅ Strategic Advisor initialized")
                logger.info("   ├─ AI Order Parameters")
                logger.info("   ├─ Dynamic Stops/Targets")
                logger.info("   └─ Fibonacci Exit Strategy")
            except Exception as e:
                logger.error(f"❌ Strategic Advisor initialization failed: {e}")
                logger.warning("⚠️  Falling back to fixed parameters")
                self.strategic_advisor = None
        else:
            self.strategic_advisor = None
            logger.info("ℹ️  Strategic Advisor disabled (using fixed parameters)")
        
        logger.info("Phase 3 Cash Segment Executor initialized")
        logger.info(f"Mode: CASH SEGMENT (NSE)")
        logger.info(f"Position Sizing: MIN(₹{config.BASE_CAPITAL_PER_TRADE:,}, actual_available) + AI multiplier")
        logger.info(f"Product type: {config.PRODUCT_TYPE}")
        logger.info(f"Profit target: +{config.PROFIT_TARGET_PCT}%")
        logger.info(f"Stop loss: -{config.STOP_LOSS_PCT}%")
    
    # ═══════════════════════════════════════════════════════════════════════════
    # 📡 ORCHESTRATOR INTEGRATION (v4.5.0) - Central Position State
    # ═══════════════════════════════════════════════════════════════════════════
    
    def set_orchestrator(self, orchestrator):
        """Set orchestrator reference for central position state management (v4.5.0)"""
        self.orchestrator = orchestrator
        logger.info("📡 Phase 3: Orchestrator reference set for position state sync")

    # ═══════════════════════════════════════════════════════════════════════════
    # v5.6: MARKET REGIME SIZING (ChatGPT outlook → entry quantity adjustment)
    # ═══════════════════════════════════════════════════════════════════════════

    def update_market_regime(self, outlook: str, confidence: int = 0):
        """Called by orchestrator when ChatGPT provides market assessment.

        Adjusts position sizing multiplier based on market regime:
          BULLISH=1.0x, NEUTRAL=0.85x, MIXED=0.6x, BEARISH=0.4x, DEFENSIVE=0.0x
        """
        self._market_regime = outlook.upper() if outlook else 'NEUTRAL'
        self._market_regime_confidence = confidence
        self._market_regime_multiplier = {
            'BULLISH': 1.0,
            'NEUTRAL': 0.85,
            'MIXED': 0.6,
            'BEARISH': 0.4,
            'DEFENSIVE': 0.0,
        }.get(self._market_regime, 0.85)
        logger.info(f"📊 Market regime updated: {self._market_regime} "
                    f"({self._market_regime_multiplier:.0%} sizing, confidence={confidence}%)")

    # ═══════════════════════════════════════════════════════════════════════════
    # v4.7.2 NEW: STOCK COOLDOWN SYSTEM
    # ═══════════════════════════════════════════════════════════════════════════
    
    def _check_stock_cooldown(self, symbol: str) -> tuple:
        """
        Check if stock is in cooldown period after recent close.
        
        v4.7.2: Prevents the re-entry loop where:
        1. Stock closes with small profit
        2. Immediately re-enters
        3. GTT fails / emergency exit
        4. Loses all profit + more
        
        Returns:
            (allowed: bool, reason: str)
        """
        # Reset daily counters if new day
        today = datetime.now().date()
        if today != self._last_daily_reset:
            self.daily_stock_trades = {}
            self.recently_closed_stocks = {}  # Also clear cooldowns on new day
            self._last_daily_reset = today
            logger.info("🔄 Daily stock trade counters reset")
        
        # Check 1: Daily trade limit per stock
        trades_today = self.daily_stock_trades.get(symbol, 0)
        if trades_today >= self.DAILY_STOCK_LIMIT:
            return False, f"Daily limit reached ({trades_today}/{self.DAILY_STOCK_LIMIT} trades today)"
        
        # Check 2: Cooldown period
        if symbol in self.recently_closed_stocks:
            close_info = self.recently_closed_stocks[symbol]
            closed_at = close_info['closed_at']
            minutes_since_close = (datetime.now() - closed_at).total_seconds() / 60
            
            if minutes_since_close < self.COOLDOWN_MINUTES:
                remaining = self.COOLDOWN_MINUTES - minutes_since_close
                pnl = close_info.get('pnl', 0)
                pnl_str = f"+₹{pnl:.0f}" if pnl >= 0 else f"-₹{abs(pnl):.0f}"
                return False, f"Cooldown active ({remaining:.0f} min left, last trade: {pnl_str})"
            else:
                # Cooldown expired, remove from tracking
                del self.recently_closed_stocks[symbol]
        
        return True, "OK"
    
    def _record_stock_closed(self, symbol: str, pnl: float, reason: str):
        """
        Record that a stock position was closed.
        Called after successful exit to start cooldown timer.
        
        v4.7.2: Enables cooldown tracking.
        """
        self.recently_closed_stocks[symbol] = {
            'closed_at': datetime.now(),
            'pnl': pnl,
            'reason': reason
        }
        
        # Increment daily trade counter
        self.daily_stock_trades[symbol] = self.daily_stock_trades.get(symbol, 0) + 1
        
        logger.info(f"🛡️ {symbol}: Cooldown started ({self.COOLDOWN_MINUTES} min)")
        logger.info(f"   Daily trades for {symbol}: {self.daily_stock_trades[symbol]}/{self.DAILY_STOCK_LIMIT}")
    
    def _notify_position_opened(self, symbol: str, position: dict):
        """Notify orchestrator that position was opened (v4.5.0)"""
        if self.orchestrator and hasattr(self.orchestrator, 'on_position_opened'):
            try:
                self.orchestrator.on_position_opened(symbol, position.copy(), source="PHASE3")
                logger.debug(f"📡 Notified orchestrator: {symbol} OPENED")
            except Exception as e:
                logger.error(f"📡 Failed to notify orchestrator of position open: {e}")
    
    def _notify_position_closed(self, symbol: str, reason: str, exit_price: float = 0):
        """Notify orchestrator that position was closed (v4.5.0)"""
        if self.orchestrator and hasattr(self.orchestrator, 'on_position_closed'):
            try:
                self.orchestrator.on_position_closed(symbol, reason, exit_price)
                logger.debug(f"📡 Notified orchestrator: {symbol} CLOSED ({reason})")
            except Exception as e:
                logger.error(f"📡 Failed to notify orchestrator of position close: {e}")
    
    # ═══════════════════════════════════════════════════════════════════════════
    # v4.9.0: POSITION PROPERTY - DELEGATES TO ORCHESTRATOR (Single Source of Truth)
    # ═══════════════════════════════════════════════════════════════════════════
    
    @property
    def positions(self) -> Dict[str, Dict]:
        """
        Get positions dict - delegates to orchestrator if available.
        
        v4.9.0: Single Source of Truth implementation.
        
        This property delegates ALL position access to orchestrator._central_positions
        when orchestrator is set. Falls back to _local_positions for standalone use.
        
        Returns:
            Dict of symbol -> position data
        """
        if self.orchestrator and hasattr(self.orchestrator, 'get_all_positions'):
            # Delegate to orchestrator - include_closing=True to see EXIT_IN_PROGRESS
            return self.orchestrator.get_all_positions(include_closing=True)
        else:
            return self._local_positions
    
    @positions.setter
    def positions(self, value: Dict[str, Dict]):
        """
        Set positions dict - for backward compatibility.
        
        This setter is rarely used. Prefer using orchestrator's position API.
        """
        if self.orchestrator and hasattr(self.orchestrator, 'add_position'):
            logger.warning("⚠️ Direct positions assignment deprecated. Use orchestrator.add_position()")
            # Sync to orchestrator
            for symbol, pos_data in value.items():
                if not self.orchestrator.position_exists(symbol):
                    self.orchestrator.add_position(symbol, pos_data, source="PHASE3_DIRECT")
        else:
            self._local_positions = value
    
    def _get_position_direct(self, symbol: str) -> Optional[Dict]:
        """
        Get single position by symbol - for direct access.
        
        v4.9.0: Helper for consistent position access.
        
        Args:
            symbol: Stock symbol
            
        Returns:
            Position dict or None
        """
        if self.orchestrator and hasattr(self.orchestrator, 'get_position_by_symbol'):
            return self.orchestrator.get_position_by_symbol(symbol)
        else:
            return self._local_positions.get(symbol)
    
    def _set_position(self, symbol: str, position_data: Dict):
        """
        Set/update a position - for consistent writes.
        
        v4.9.0: Helper that notifies orchestrator of changes.
        
        Args:
            symbol: Stock symbol
            position_data: Position data dict
        """
        if self.orchestrator and hasattr(self.orchestrator, 'add_position'):
            if self.orchestrator.position_exists(symbol):
                # Update existing
                self.orchestrator.update_position(symbol, position_data)
            else:
                # Add new
                self.orchestrator.add_position(symbol, position_data, source="PHASE3")
        else:
            self._local_positions[symbol] = position_data
    
    def _delete_position(self, symbol: str, reason: str = "UNKNOWN", exit_price: float = 0):
        """
        Delete a position - for consistent deletion.
        
        v4.9.0: Helper that notifies orchestrator.
        
        Args:
            symbol: Stock symbol
            reason: Exit reason
            exit_price: Exit price for P&L
        """
        if self.orchestrator and hasattr(self.orchestrator, 'remove_position'):
            self.orchestrator.remove_position(symbol, reason, exit_price)
        else:
            if symbol in self._local_positions:
                del self._local_positions[symbol]
    
    def _position_exists(self, symbol: str) -> bool:
        """
        Check if position exists.
        
        v4.9.0: Helper for consistent existence check.
        
        Args:
            symbol: Stock symbol
            
        Returns:
            True if position exists
        """
        if self.orchestrator and hasattr(self.orchestrator, 'position_exists'):
            return self.orchestrator.position_exists(symbol)
        else:
            return symbol in self._local_positions
    
    def _is_position_closing(self, symbol: str) -> bool:
        """
        Check if position is in EXIT_IN_PROGRESS/CLOSING state.
        
        v4.9.0: Helper for state checks.
        
        Args:
            symbol: Stock symbol
            
        Returns:
            True if position is in closing state
        """
        if self.orchestrator and hasattr(self.orchestrator, 'is_position_closing'):
            return self.orchestrator.is_position_closing(symbol)
        else:
            pos = self._local_positions.get(symbol)
            return pos is not None and pos.get('status') in ['EXIT_IN_PROGRESS', 'CLOSING']
    
    def _transition_to_closing(self, symbol: str, reason: str = ""):
        """
        Transition position to CLOSING/EXIT_IN_PROGRESS state.
        
        v4.9.0: Uses orchestrator's state machine if available.
        
        Args:
            symbol: Stock symbol
            reason: Reason for closing
        """
        if self.orchestrator and hasattr(self.orchestrator, 'transition_position_state'):
            self.orchestrator.transition_position_state(symbol, 'CLOSING', reason)
        else:
            pos = self._local_positions.get(symbol)
            if pos:
                pos['status'] = PositionState.EXIT_IN_PROGRESS

    
    def check_portfolio_risk(self, new_signal: dict) -> dict:
        """
        Check if adding new position would exceed portfolio risk limits.
        
        ✅ NEW METHOD (v2.0.0 - 2026-01-15)
        
        Portfolio Risk Rules:
        - Max positions from config.MAX_TOTAL_POSITIONS (default 5)
        - Max 70% of capital deployed
        - Max 40% in single sector
        
        Args:
            new_signal: Proposed new trade signal
            
        Returns:
            {
                'approved': bool,
                'reason': str,
                'current_exposure': float (% of capital),
                'current_positions': int,
                'risk_score': int (0-100, higher = more risky)
            }
        """
        try:
            # Count current open positions
            open_positions = [p for p in self.positions.values() if p.get('status') == 'OPEN']
            num_positions = len(open_positions)
            
            # Calculate current capital deployed
            total_deployed = sum(
                p.get('entry_price', 0) * p.get('quantity', 0)
                for p in open_positions
            )
            
            # v4.6.0: Read from Capital Manager for real-time capital tracking
            if self.capital_manager:
                max_capital = self.capital_manager.total_capital
            else:
                max_capital = self.config.TOTAL_CAPITAL
            capital_pct = (total_deployed / max_capital) * 100 if max_capital > 0 else 0
            
            # Check max positions (v5.2.1: Read from config instead of hardcoded 2)
            max_positions = getattr(self.config, 'MAX_TOTAL_POSITIONS', 5)
            if num_positions >= max_positions:
                return {
                    'approved': False,
                    'reason': f'Max {max_positions} positions reached (current: {num_positions})',
                    'current_exposure': capital_pct,
                    'current_positions': num_positions,
                    'risk_score': 100
                }
            
            # Calculate new position value
            new_price = new_signal.get('entry_price', 0)
            new_quantity = new_signal.get('quantity', 1)
            new_position_value = new_price * new_quantity
            
            # Calculate total after adding new position
            new_total_deployed = total_deployed + new_position_value
            new_capital_pct = (new_total_deployed / max_capital) * 100
            
            # Check capital deployment
            if new_capital_pct > 70:
                return {
                    'approved': False,
                    'reason': f'Would exceed 70% capital deployment (would be {new_capital_pct:.0f}%)',
                    'current_exposure': capital_pct,
                    'current_positions': num_positions,
                    'risk_score': 90
                }
            
            # Calculate risk score (0-100)
            risk_score = int(
                (num_positions / max_positions) * 40 +  # Position count contributes 40%
                (new_capital_pct / 70) * 60  # Capital usage contributes 60%
            )
            
            # Approved
            return {
                'approved': True,
                'reason': 'Portfolio risk acceptable',
                'current_exposure': capital_pct,
                'current_positions': num_positions,
                'risk_score': risk_score
            }
            
        except Exception as e:
            logger.error(f"❌ Error checking portfolio risk: {e}")
            # Fail-safe: Allow trade if check fails
            return {
                'approved': True,
                'reason': 'Risk check failed, allowing trade',
                'current_exposure': 0,
                'current_positions': 0,
                'risk_score': 50
            }
    
    
    def execute_entry_signals(self) -> List[dict]:
        """
        Execute all entry signals from Phase 2.
        
        v4.5.1 FIX: Now notifies orchestrator for each position opened
        
        Returns:
            List of executed trades
        """
        logger.info("=" * 80)
        logger.info("PHASE 3: CASH SEGMENT ORDER EXECUTION")
        logger.info("=" * 80)
        logger.info("")
        
        # Load entry signals
        signals = self._load_entry_signals()
        if not signals:
            logger.warning("⚠️  No entry signals found")
            return []
        
        logger.info(f"📋 Loaded {len(signals)} entry signal(s)")
        logger.info("")
        
        # Execute each signal
        executed_trades = []
        
        for idx, signal in enumerate(signals, 1):
            symbol = signal.get('symbol', 'UNKNOWN')
            logger.info(f"Processing signal {idx}/{len(signals)}: {symbol}")
            
            try:
                # Execute single signal
                trade = self._execute_single_signal(signal)
                
                if trade:
                    executed_trades.append(trade)
                    
                    # ═══════════════════════════════════════════════════════════
                    # v4.5.1 FIX: Notify orchestrator of new position
                    # ═══════════════════════════════════════════════════════════
                    self._notify_position_opened(symbol, trade)
                    logger.info(f"✅ Signal {idx} executed, orchestrator notified")
                else:
                    logger.warning(f"⚠️  Signal {idx} not executed")
                
            except Exception as e:
                logger.error(f"❌ Error executing signal {idx}: {e}")
                logger.error(traceback.format_exc())
            
            logger.info("")
        
        # Summary
        logger.info("=" * 80)
        logger.info(f"EXECUTION SUMMARY: {len(executed_trades)}/{len(signals)} orders placed")
        logger.info("=" * 80)
        
        if executed_trades and self.telegram:
            self.telegram.send_message(
                f"✅ PHASE 3 EXECUTION COMPLETE\n\n"
                f"Orders placed: {len(executed_trades)}/{len(signals)}\n"
                f"Capital used: ₹{self.capital_used:,.0f}\n"
                f"Positions: {len(executed_trades)}"
            )
        
        return executed_trades
    
    
    def execute_signal_realtime(self, signal: dict) -> Optional[dict]:
        """
        Execute a SINGLE signal immediately (real-time execution).
        
        Called by Phase 2 when signal is generated during monitoring.
        This enables immediate order placement instead of batch execution.
        
        v4.5.1: Removed duplicate position add (already done in _execute_single_signal)
        
        Args:
            signal: Signal dict from Phase 2
            
        Returns:
            Position dict if successful, None otherwise
        """
        symbol = signal.get('symbol', 'UNKNOWN')
        
        logger.info(f"🚀 REAL-TIME EXECUTION: {symbol}")
        
        try:
            # Check circuit breaker first
            if not self._check_daily_loss_limit():
                logger.warning(f"⛔ {symbol}: Daily loss limit exceeded - skipping")
                return None
            
            # Execute single signal (adds to self.positions internally)
            position = self._execute_single_signal(signal)
            
            if position:
                logger.info(f"✅ {symbol}: Real-time order placed successfully")
                
                # 📡 v4.5.0: Notify orchestrator (central position state)
                # Note: Position already added to self.positions by _execute_single_signal
                self._notify_position_opened(symbol, position)
                
                # Send Telegram notification
                if self.telegram:
                    actual_target_pct = ((position['target_price'] - position['entry_price']) / position['entry_price']) * 100 if position['entry_price'] > 0 else 0
                    actual_stop_pct = ((position['entry_price'] - position['stop_price']) / position['entry_price']) * 100 if position['entry_price'] > 0 else 0
                    pdl_tag = " [PDL]" if position.get('price_level_stop_used') else ""
                    pdh_tag = " [PDH]" if position.get('price_level_target_used') else ""
                    self.telegram.send_message(
                        f"🚀 REAL-TIME ENTRY\n\n"
                        f"Stock: {symbol}\n"
                        f"Quantity: {position['quantity']}\n"
                        f"Entry: ₹{position['entry_price']:.2f}\n"
                        f"Target: ₹{position['target_price']:.2f} (+{actual_target_pct:.1f}%){pdh_tag}\n"
                        f"Stop: ₹{position['stop_price']:.2f} (-{actual_stop_pct:.1f}%){pdl_tag}"
                    )
                
            return position
            
        except Exception as e:
            logger.error(f"❌ Real-time execution failed for {symbol}: {e}")
            logger.error(traceback.format_exc())
            
            if self.telegram:
                self.telegram.send_message(
                    f"❌ REAL-TIME EXECUTION FAILED\n\n"
                    f"Stock: {symbol}\n"
                    f"Error: {str(e)[:150]}"
                )
            
            return None

    # ═══════════════════════════════════════════════════════════════════════
    # v8.0.0: PHASE 8 MOMENTUM SIGNAL EXECUTION
    # ═══════════════════════════════════════════════════════════════════════

    def execute_ph8_momentum_signal(self, signal: dict) -> Optional[dict]:
        """
        Execute a Phase 8 Weekly Momentum signal.

        Differences from standard execute_signal_realtime:
          - Places CNC LIMIT order at VWAP price (not MARKET)
          - No GTT placement (TCAS handles exits in Tier 3)
          - 10:30 AM fallback: cancel limit → place MARKET
          - Notifies Ph4 with source="PH8_MOMENTUM" for Tier 3 tracking
          - Triggers Ph6 momentum shadow (ChatGPT gated)

        Args:
            signal: Signal dict from Phase 8 scanner:
                source: "PH8_MOMENTUM"
                symbol, exchange, direction, product, quantity,
                limit_price, order_type, validity, weekly_return_pct,
                market_cap_crore, sector, rank, entry_window_start,
                entry_window_end, fallback_to_market, no_gtt

        Returns:
            Position dict if successful, None otherwise.
        """
        symbol = signal.get('symbol', 'UNKNOWN')
        logger.info(f"")
        logger.info(f"{'='*60}")
        logger.info(f"PH8 MOMENTUM ENTRY: {symbol}")
        logger.info(f"{'='*60}")
        logger.info(f"   Weekly Return: {signal.get('weekly_return_pct', 0):+.2f}%")
        logger.info(f"   Order Type: {signal.get('order_type', 'LIMIT')}")
        logger.info(f"   Limit Price: {signal.get('limit_price', 0):.2f}")
        logger.info(f"   Quantity: {signal.get('quantity', 0)}")

        try:
            quantity = signal.get('quantity', 0)
            limit_price = signal.get('limit_price', 0)
            product = signal.get('product', 'CNC')
            order_type = signal.get('order_type', 'LIMIT')

            if quantity <= 0:
                logger.error(f"   Invalid quantity: {quantity}")
                return None

            # ── Place order ──────────────────────────────────────────
            order_id = None
            fill_price = None

            if order_type == 'LIMIT' and limit_price > 0:
                # Place CNC LIMIT BUY at VWAP price
                order_id = self._place_limit_order(
                    symbol=symbol,
                    quantity=quantity,
                    price=limit_price,
                    product=product
                )
                logger.info(f"   LIMIT order placed: {order_id} @ {limit_price:.2f}")
            else:
                # Direct MARKET order (VWAP unavailable)
                order_id = self._place_order(
                    symbol=symbol,
                    quantity=quantity,
                    transaction_type='BUY',
                    product=product
                )
                logger.info(f"   MARKET order placed: {order_id}")

            if not order_id:
                logger.error(f"   Order placement failed for {symbol}")
                self._ph8_notify(f"PH8 ORDER FAILED\n{symbol} — order placement returned None")
                return None

            # ── Wait for fill ────────────────────────────────────────
            fill_price = self._wait_for_fill(order_id)

            # ── 10:30 AM Fallback: Cancel limit → Market ────────────
            if fill_price is None and order_type == 'LIMIT' and signal.get('fallback_to_market', True):
                logger.info(f"   LIMIT not filled — checking fallback window...")

                # Check if we're past the entry window end
                from datetime import datetime as dt_cls
                now = dt_cls.now().time()
                entry_end_str = signal.get('entry_window_end', '10:30')
                try:
                    parts = entry_end_str.split(':')
                    entry_end = dt_time(int(parts[0]), int(parts[1]))
                except (ValueError, IndexError):
                    entry_end = dt_time(10, 30)

                if now >= entry_end:
                    # Cancel the limit order
                    try:
                        self.kite.cancel_order(
                            variety=self.kite.VARIETY_REGULAR,
                            order_id=order_id
                        )
                        logger.info(f"   LIMIT order {order_id} cancelled")
                    except Exception as e:
                        logger.warning(f"   Cancel order error: {e}")

                    # Place MARKET order
                    market_order_id = self._place_order(
                        symbol=symbol,
                        quantity=quantity,
                        transaction_type='BUY',
                        product=product
                    )
                    if market_order_id:
                        logger.info(f"   MARKET fallback order placed: {market_order_id}")
                        order_id = market_order_id
                        fill_price = self._wait_for_fill(order_id)

                        if fill_price:
                            self._ph8_notify(
                                f"PH8 VWAP LIMIT MISSED\n"
                                f"{symbol} — limit {limit_price:.2f} not filled by "
                                f"{entry_end_str}\n"
                                f"MARKET order filled @ {fill_price:.2f} "
                                f"({((fill_price - limit_price) / limit_price * 100):+.1f}% slip)"
                            )
                else:
                    # Not yet at fallback time — wait more
                    # Orchestrator will call us again or handle the timeout
                    logger.info(f"   Still within entry window (now: {now.strftime('%H:%M')}, "
                                f"end: {entry_end_str}). Order remains active.")
                    # Return a pending-state dict so orchestrator can track
                    return {
                        'symbol': symbol,
                        'status': 'PENDING_FILL',
                        'order_id': order_id,
                        'order_type': 'LIMIT',
                        'limit_price': limit_price,
                        'quantity': quantity,
                        'source': 'PH8_MOMENTUM',
                    }

            if fill_price is None or fill_price <= 0:
                logger.error(f"   {symbol}: Order not filled")
                self._ph8_notify(f"PH8 ORDER NOT FILLED\n{symbol} — no fill received")
                return None

            logger.info(f"   FILLED: {symbol} @ {fill_price:.2f}")

            # ── Build position dict ──────────────────────────────────
            entry_value = fill_price * quantity
            position = {
                'symbol': symbol,
                'entry_price': fill_price,
                'quantity': quantity,
                'order_id': str(order_id),
                'product': product,
                'source': 'PH8_MOMENTUM',
                'monitoring_tier': 'TIER_3',
                'entry_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'entry_date': date.today().isoformat(),
                'weekly_return_pct': signal.get('weekly_return_pct', 0),
                'market_cap_crore': signal.get('market_cap_crore', 0),
                'sector': signal.get('sector', ''),
                'rank': signal.get('rank', 1),
                'vwap_price': limit_price,
                'status': 'ACTIVE',
                # No target/stop — TCAS handles exits
                'target_price': 0,
                'stop_price': 0,
                # TCAS tracking (initialized by Ph4 Tier 3)
                'peak_price': fill_price,
                'tcas_active': False,
                'tcas_trail_price': 0,
            }

            # ── Deploy capital ───────────────────────────────────────
            if self.capital_manager:
                try:
                    from capital_manager import PositionSource
                    deploy_success = self.capital_manager.deploy(
                        symbol=symbol,
                        amount=entry_value,
                        quantity=quantity,
                        avg_price=fill_price,
                        source=PositionSource.PH8_MOMENTUM,
                        product=product
                    )
                    if deploy_success:
                        logger.info(f"   Capital deployed: {entry_value:,.0f}")
                    else:
                        logger.warning(f"   Capital deploy returned False")
                except Exception as e:
                    logger.error(f"   Capital deploy error: {e}")

            # ── NO GTT for Phase 8 (TCAS is sole stop mechanism) ────
            logger.info(f"   GTT SKIPPED: Phase 8 uses TCAS trailing stop (no GTT)")
            position['gtt_active'] = False
            position['gtt_protected'] = False
            position['no_gtt'] = True

            # ── Notify orchestrator / Phase 4 (Tier 3) ──────────────
            self._notify_position_opened(symbol, position)

            # ── Phase 6: Momentum Shadow (ChatGPT gated) ────────────
            if self.options_advisor and getattr(self.config, 'PH8_SHADOW_ENABLED', False):
                try:
                    if hasattr(self.options_advisor, 'handle_momentum_fill'):
                        self.options_advisor.handle_momentum_fill(
                            fill_data={
                                'symbol': symbol,
                                'entry_price': fill_price,
                                'quantity': quantity,
                                'order_id': str(order_id),
                                'source': 'PH8_MOMENTUM',
                                'weekly_return_pct': signal.get('weekly_return_pct', 0),
                                'market_cap_crore': signal.get('market_cap_crore', 0),
                                'sector': signal.get('sector', ''),
                            }
                        )
                        logger.info(f"   Ph6 momentum shadow triggered for {symbol}")
                    else:
                        logger.info(f"   Ph6: handle_momentum_fill not available — skipping shadow")
                except Exception as e:
                    logger.error(f"   Ph6 momentum shadow error: {e}")

            # ── Save position ────────────────────────────────────────
            self.positions[symbol] = position
            self._save_position(position)

            # ── Telegram notification ────────────────────────────────
            self._ph8_notify(
                f"PH8 BUY EXECUTED\n"
                f"{symbol} @ {fill_price:.2f} (CNC)\n"
                f"Qty: {quantity} | Value: {entry_value:,.0f}\n"
                f"{'VWAP Limit Fill' if limit_price > 0 else 'Market Fill'}\n"
                f"Tier 3 tracking: ACTIVE\n"
                f"Momentum: {signal.get('weekly_return_pct', 0):+.2f}% last week"
            )

            return position

        except Exception as e:
            logger.error(f"   PH8 execution error: {type(e).__name__}: {e}",
                         exc_info=True)
            self._ph8_notify(f"PH8 EXECUTION ERROR\n{symbol}: {e}")
            return None

    def _ph8_notify(self, message: str):
        """Phase 8 Telegram notification — never crashes."""
        try:
            if self.telegram:
                self.telegram.send_message(message)
        except Exception as e:
            logger.error(f"   PH8 Telegram error: {e}")

    def _load_entry_signals(self) -> List[dict]:
        """Load entry signals from Phase 2"""
        filepath = self.config.ENTRY_SIGNALS_FILE
        
        if not os.path.exists(filepath):
            logger.error(f"Entry signals file not found: {filepath}")
            return []
        
        data = load_json(filepath)
        
        if not data:
            return []
        
        # Extract signals array
        if isinstance(data, list):
            return data
        elif 'signals' in data:
            return data['signals']
        else:
            return [data]
    
    
    def _execute_single_signal(self, signal: dict) -> Optional[dict]:
        """
        Execute a single entry signal.
        
        Cash segment flow:
        1. Validate signal (7 checks)
        2. Get stock LTP
        3. Calculate cost (LTP × 1 share)
        4. Place BUY order (NSE, quantity=1)
        5. Confirm fill
        6. Save position
        
        Args:
            signal: Entry signal from Phase 2
        
        Returns:
            Trade data if successful, None otherwise
        """
        symbol = signal.get('symbol', signal.get('stock', 'UNKNOWN'))
        
        logger.info(f"Executing: {symbol}")
        logger.info("─" * 60)
        
        # Step 1: Validate signal
        is_valid, reason = self._validate_signal(signal)
        
        if not is_valid:
            logger.warning(f"❌ Validation failed: {reason}")
            return None
        
        logger.info(f"✅ Validation passed")
        
        # Step 1.5: Circuit breaker check (daily loss limit)
        if not self._check_daily_loss_limit():
            logger.warning(f"⛔ Circuit breaker: Daily loss limit exceeded - skipping {symbol}")
            return None
        
        # Step 2: Get stock LTP (current price)
        try:
            quote = self.kite.quote([f"NSE:{symbol}"])
            instrument_key = f"NSE:{symbol}"
            if instrument_key not in quote or 'last_price' not in quote[instrument_key]:
                raise KeyError(f"last_price missing in quote response for {instrument_key}")
            stock_ltp = quote[instrument_key]['last_price']
            logger.info(f"📊 Stock LTP: ₹{stock_ltp:.2f}")
        except Exception as e:
            logger.error(f"❌ Failed to get stock price: {e}")
            return None
        
        # ═══════════════════════════════════════════════════════════════
        # Step 3: Calculate Dynamic Quantity (🧠 Intelligent Engine!) 
        # ═══════════════════════════════════════════════════════════════
        # ✅ v3.0.0: Uses intelligent signal recommendations if available
        
        # Step 3.1: Get ACTUAL available capital from Zerodha
        try:
            margins = self.kite.margins()
            zerodha_available = margins.get('equity', {}).get('available', {}).get('live_balance', 0)
            emergency_buffer = getattr(self.config, 'EMERGENCY_BUFFER', 4000)
            actual_usable = zerodha_available - emergency_buffer
            
            logger.info(f"💰 CAPITAL CHECK (Before Sizing):")
            logger.info(f"   Zerodha Available: ₹{zerodha_available:,.0f}")
            logger.info(f"   Emergency Buffer: ₹{emergency_buffer:,.0f}")
            logger.info(f"   Actual Usable: ₹{actual_usable:,.0f}")
            
            if actual_usable <= 0:
                logger.warning(f"❌ No usable capital after buffer! Available: ₹{zerodha_available:.0f}, Buffer: ₹{emergency_buffer:.0f}")
                return None
                
        except Exception as e:
            logger.error(f"❌ Failed to get margins: {e}")
            return None
        
        # Step 3.2: Check if this is an intelligent signal (v3.0.0)
        is_intelligent_signal = 'intelligent_score' in signal or 'recommended_capital' in signal
        
        if is_intelligent_signal:
            # 🧠 Use intelligent engine recommendations
            logger.info("🧠 INTELLIGENT POSITION SIZING:")
            
            # v4.7.2 FIX: Ensure numeric types (values might come as strings)
            intelligent_score = float(signal.get('intelligent_score', 50) or 50)
            signal_strength = str(signal.get('signal_strength', 'UNKNOWN') or 'UNKNOWN')
            recommended_capital = float(signal.get('recommended_capital', self.config.BASE_CAPITAL_PER_TRADE) or self.config.BASE_CAPITAL_PER_TRADE)
            position_multiplier = float(signal.get('position_multiplier', 1.0) or 1.0)
            market_regime = str(signal.get('market_regime', 'MIXED') or 'MIXED')
            
            logger.info(f"   Score: {intelligent_score:.0f}/100 ({signal_strength})")
            logger.info(f"   Market Regime: {market_regime}")
            logger.info(f"   Recommended Capital: ₹{recommended_capital:,.0f}")
            logger.info(f"   Position Multiplier: {position_multiplier:.2f}x")
            
            # Use recommended capital but cap at actual usable
            effective_capital = min(recommended_capital, actual_usable)
            
            # Get adaptive stop/target from intelligent engine
            if 'suggested_stop_loss_pct' in signal:
                self.adaptive_stop_loss = signal['suggested_stop_loss_pct']
                logger.info(f"   Adaptive Stop Loss: {self.adaptive_stop_loss}%")
            
            if 'suggested_target_pct' in signal:
                self.adaptive_target = signal['suggested_target_pct']
                logger.info(f"   Adaptive Target: {self.adaptive_target}%")
            
            # Log prediction if available
            if 'predicted_direction' in signal:
                pred_dir = str(signal.get('predicted_direction', 'NEUTRAL') or 'NEUTRAL')
                pred_conf = float(signal.get('prediction_confidence', 0) or 0)
                logger.info(f"   🔮 Prediction: {pred_dir} ({pred_conf:.0f}% confidence)")
            
        else:
            # Fallback to standard sizing
            logger.info("📊 STANDARD POSITION SIZING:")
            config_capital = float(self.config.BASE_CAPITAL_PER_TRADE)
            effective_capital = min(config_capital, actual_usable)
            position_multiplier = float(signal.get('position_size_multiplier', 1.0) or 1.0)
            logger.info(f"   Config Capital: ₹{config_capital:,.0f}")
            logger.info(f"   Position Multiplier: {position_multiplier:.2f}x")
        
        logger.info(f"   → Effective Capital: ₹{effective_capital:,.0f}")
        
        # ═══════════════════════════════════════════════════════════════════════════
        # v4.7.2 FIX: MINIMUM VIABLE TRADE INVARIANT
        # ═══════════════════════════════════════════════════════════════════════════
        # Ensures we can always buy at least 1 share, regardless of score multiplier.
        # Without this, intelligent sizing (e.g., 0.35x for WEAK scores) can reduce
        # capital below the minimum needed for even 1 share of high-priced stocks.
        # ═══════════════════════════════════════════════════════════════════════════
        min_for_one_share = stock_ltp * 1.05  # 5% buffer for price movement/fees
        
        if effective_capital < min_for_one_share:
            # Check if we can actually afford the minimum from usable capital
            if actual_usable >= min_for_one_share:
                logger.info(f"   📈 Capital floor applied: ₹{effective_capital:,.0f} → ₹{min_for_one_share:,.0f} (1-share minimum)")
                effective_capital = min_for_one_share
            else:
                # Truly insufficient capital - let it fail naturally below
                logger.warning(f"   ⚠️ Cannot afford 1 share: need ₹{min_for_one_share:,.0f}, usable ₹{actual_usable:,.0f}")
        
        # Step 3.3: Calculate quantity from EFFECTIVE capital
        base_qty = int(effective_capital / stock_ltp)
        
        if base_qty < 1:
            logger.warning(f"❌ Insufficient capital for even 1 share! Need ₹{stock_ltp:.0f}, Have ₹{effective_capital:.0f}")
            return None
        
        # Apply multiplier (from intelligent engine or volatility)
        quantity = max(1, int(base_qty * position_multiplier))

        # v5.6: Market regime sizing adjustment
        market_mult = getattr(self, '_market_regime_multiplier', 1.0)
        market_regime = getattr(self, '_market_regime', 'NEUTRAL')
        if market_mult <= 0:
            # DEFENSIVE regime — block new entries entirely
            logger.warning(f"   🛡️ DEFENSIVE market regime — blocking new entry for {symbol}")
            if self.telegram:
                self.telegram.send_message(
                    f"🛡️ Entry BLOCKED: {symbol}\n"
                    f"Market regime: DEFENSIVE\n"
                    f"No new entries until regime improves"
                )
            return None
        elif market_mult < 1.0:
            pre_regime_qty = quantity
            quantity = max(1, int(quantity * market_mult))
            logger.info(f"   📊 Market regime {market_regime}: "
                        f"{market_mult:.0%} → qty {pre_regime_qty} → {quantity}")

        cost = stock_ltp * quantity
        
        # Final check: ensure cost doesn't exceed actual usable
        if cost > actual_usable:
            # Reduce quantity to fit
            quantity = max(1, int(actual_usable / stock_ltp))
            cost = stock_ltp * quantity
            logger.info(f"   ⚠️ Reduced quantity to fit available capital")

        # v2.1.0: CNC MAX-LOSS CAP (Stage 1 — buy-time pre-check)
        # Caps quantity so estimated GTT loss ≤ CNC_MAX_LOSS_CAP.
        # Uses signal's stop_pct as estimate (ATR/PDL overrides applied later may differ
        # slightly, but Stage 2 at GTT time will warn if actual loss still exceeds cap).
        _cnc_loss_cap = getattr(self.config, 'CNC_MAX_LOSS_CAP', 150)
        _est_stop_pct = float(signal.get('stop_pct', getattr(self.config, 'STOP_LOSS_PCT', 2.0)) or 2.0)
        _est_stop_dist = stock_ltp * (_est_stop_pct / 100)
        if _est_stop_dist > 0:
            _max_qty_loss = max(1, int(_cnc_loss_cap / _est_stop_dist))
            if quantity > _max_qty_loss:
                logger.warning(
                    f"   🛡️ CNC MAX-LOSS CAP: qty {quantity} → {_max_qty_loss} "
                    f"(est stop ₹{_est_stop_dist:.2f}/share × {quantity} = "
                    f"₹{_est_stop_dist * quantity:.0f} > ₹{_cnc_loss_cap} cap)"
                )
                quantity = _max_qty_loss
                cost = stock_ltp * quantity

        # v4.5.3 FIX: Get volatility_regime early (was undefined bug)
        volatility_regime = signal.get('volatility_regime', 'MEDIUM')
        
        logger.info(f"🤖 AI POSITION SIZING:")
        logger.info(f"   Effective Capital: ₹{effective_capital:,.0f}")
        logger.info(f"   Base Quantity: {base_qty} shares")
        logger.info(f"   Volatility: {volatility_regime}")
        logger.info(f"   AI Multiplier: {position_multiplier:.2f}x")
        logger.info(f"   ✅ Final Quantity: {quantity} shares")
        logger.info(f"   💰 Order Cost: ₹{cost:,.2f}")
        
        # Update internal tracking
        available = self.total_capital - self.capital_used
        if cost > available:
            logger.warning(f"❌ Internal capital limit: Need ₹{cost:.0f}, Tracked Available ₹{available:.0f}")
            return None
        
        # ═══════════════════════════════════════════════════════════════
        # ✅ Step 3.5: Portfolio Risk Check (v2.0.0)
        # ═══════════════════════════════════════════════════════════════
        
        if (self.strategic_advisor and 
            self.config.USE_ADVISOR_FOR_PORTFOLIO_RISK):
            
            # Prepare signal with calculated values
            signal_with_values = signal.copy()
            signal_with_values['entry_price'] = stock_ltp
            signal_with_values['quantity'] = quantity
            
            risk_check = self.check_portfolio_risk(signal_with_values)
            
            logger.info(f"🛡️  PORTFOLIO RISK CHECK:")
            max_pos_display = getattr(self.config, 'MAX_TOTAL_POSITIONS', 5)
            logger.info(f"   Current positions: {risk_check['current_positions']}/{max_pos_display}")
            logger.info(f"   Current exposure: {risk_check['current_exposure']:.1f}%")
            logger.info(f"   Risk score: {risk_check['risk_score']}/100")
            logger.info(f"   Verdict: {risk_check['reason']}")
            
            if not risk_check['approved']:
                logger.warning(f"⛔ TRADE BLOCKED BY PORTFOLIO RISK: {risk_check['reason']}")
                
                if self.telegram:
                    self.telegram.send_message(
                        f"⛔ TRADE BLOCKED - PORTFOLIO RISK\n\n"
                        f"Stock: {symbol}\n"
                        f"Reason: {risk_check['reason']}\n\n"
                        f"Current positions: {risk_check['current_positions']}/{max_pos_display}\n"
                        f"Current exposure: {risk_check['current_exposure']:.1f}%\n"
                        f"Risk score: {risk_check['risk_score']}/100\n\n"
                        f"Wait for existing positions to close before entering new trades."
                    )
                
                return None  # Don't place order
            
            logger.info(f"✅ Portfolio risk check PASSED")

        # ═══════════════════════════════════════════════════════════════
        # ✅ Step 3.7: Fund Manager Approval Gate (Phase 9 v1.0.0)
        # ═══════════════════════════════════════════════════════════════

        _marker_gate_bypass = (getattr(self.config, 'MARKER_MODE_ENABLED', False)
                               and getattr(self.config, 'MARKER_BUY_ON_CONFIRMATION', False))
        if _marker_gate_bypass and hasattr(self, 'fund_manager') and self.fund_manager:
            if (getattr(self.fund_manager, 'todays_regime', 'NORMAL') or 'NORMAL') == 'HALT':
                logger.warning(f"⛔ PH9 HALT mode — rejecting marker {symbol}")
                return None
            logger.info(f"   📍 MARKER mode: Phase 9 entry approval skipped for {symbol}")

        if (hasattr(self, 'fund_manager') and self.fund_manager
                and getattr(self.config, 'PH9_ENTRY_GATE_ENABLED', False)
                and not _marker_gate_bypass):

            try:
                # v1.1.0: Respect operation_mode (HALT blocks, CAUTIOUS throttles)
                _op_mode = getattr(self.fund_manager, 'todays_regime', 'NORMAL') or 'NORMAL'
                if _op_mode == 'HALT':
                    logger.warning(f"⛔ PH9 HALT mode — rejecting {symbol}")
                    return None

                # Collect portfolio state for context
                portfolio_state = {'positions': {}}
                if hasattr(self, '_orchestrator') and self._orchestrator:
                    portfolio_state['positions'] = dict(
                        getattr(self._orchestrator, '_central_positions', {}))
                elif hasattr(self, 'phase4_manager') and self.phase4_manager:
                    portfolio_state['positions'] = dict(
                        getattr(self.phase4_manager, 'positions', {}))

                # v1.1.0: Sector correlation check — block if too many
                # positions already open in the same sector.
                try:
                    max_per_sector = getattr(self.config, 'PH9_MAX_POSITIONS_PER_SECTOR', 2)
                    sig_sector = (signal.get('sector') or signal.get('industry') or '').strip().upper()
                    if sig_sector and portfolio_state['positions']:
                        same = 0
                        for _s, _p in portfolio_state['positions'].items():
                            _ps = ''
                            if isinstance(_p, dict):
                                _ps = (_p.get('sector') or _p.get('industry') or '').strip().upper()
                            if _ps and _ps == sig_sector:
                                same += 1
                        if same >= max_per_sector:
                            logger.warning(f"⛔ Sector cap: {sig_sector} already has "
                                         f"{same}/{max_per_sector} positions — rejecting {symbol}")
                            return None
                except Exception as _sec_e:
                    logger.debug(f"Sector check skipped: {_sec_e}")

                fm_result = self.fund_manager.approve_entry(
                    signal=signal,
                    current_price=stock_ltp,
                    quantity=quantity,
                    portfolio_state=portfolio_state
                )

                # v1.5.0: Queue mode — signal deferred to heartbeat, skip immediate execution
                if fm_result.get('queued'):
                    logger.info(f"🧠 FUND MANAGER: {symbol} queued for heartbeat batch evaluation")
                    return None

                logger.info(f"🧠 FUND MANAGER GATE:")
                logger.info(f"   Verdict: {'APPROVED' if fm_result['approved'] else 'BLOCKED'}")
                logger.info(f"   Confidence: {fm_result.get('confidence', 0)}%")
                logger.info(f"   Size Adj: {fm_result.get('size_adjustment', 1.0):.1f}x")
                logger.info(f"   Gate: {fm_result.get('gate', '?')}")
                logger.info(f"   Reason: {fm_result.get('reasoning', '')[:200]}")

                if not fm_result['approved']:
                    logger.warning(f"⛔ TRADE BLOCKED BY FUND MANAGER: {fm_result['reasoning'][:200]}")
                    return None

                # Apply size adjustment if Claude modified it
                size_adj = float(fm_result.get('size_adjustment', 1.0) or 1.0)
                # v1.1.0: CAUTIOUS mode caps size at 0.5x
                if _op_mode == 'CAUTIOUS':
                    size_adj = min(size_adj, 0.5)
                if size_adj != 1.0:
                    old_qty = quantity
                    quantity = max(1, int(quantity * size_adj))
                    cost = stock_ltp * quantity
                    logger.info(f"   📐 Fund Manager size adjustment: {old_qty} → {quantity} shares "
                               f"({size_adj:.1f}x)")

                logger.info(f"✅ Fund Manager gate PASSED")

            except Exception as e:
                logger.error(f"Fund Manager gate error: {e} — auto-approving at 0.5x size (cautious fallback)")
                # On error: allow trade (safety rails already passed) but halve size as precaution
                old_qty = quantity
                quantity = max(1, quantity // 2)
                if quantity != old_qty:
                    logger.info(f"   ⚠️ Gate error fallback: size reduced {old_qty} → {quantity} (0.5x)")
                cost = stock_ltp * quantity

        _marker_mode = getattr(self.config, 'MARKER_MODE_ENABLED', False)
        if _marker_mode:
            quantity = int(getattr(self.config, 'MARKER_QUANTITY', 1))
            cost = stock_ltp * quantity
            logger.info(f"   📍 MARKER MODE: quantity forced to {quantity} share(s) (₹{cost:,.2f})")

        # Step 4: Place BUY order (v5.4: LIMIT if ChatGPT suggests entry price)
        logger.info(f"📤 Placing BUY order...")

        # v5.4: Check for ChatGPT suggested LIMIT entry price
        use_limit = getattr(self.config, 'USE_CHATGPT_ENTRY_PRICE', False)
        suggested_entry = signal.get('chatgpt_suggested_entry_price')
        limit_filled_directly = False
        fill_price = 0
        filled_quantity = 0

        try:
            if use_limit and suggested_entry is not None:
                # Validate: entry must be within LIMIT_ORDER_MAX_SLIP_PCT of LTP
                max_slip_pct = getattr(self.config, 'LIMIT_ORDER_MAX_SLIP_PCT', 0.5)
                min_limit = stock_ltp * (1 - max_slip_pct / 100)

                if min_limit <= suggested_entry <= stock_ltp:
                    logger.info(f"   ChatGPT LIMIT entry: Rs{suggested_entry:.2f} "
                               f"(LTP: Rs{stock_ltp:.2f}, diff: "
                               f"{((stock_ltp - suggested_entry)/stock_ltp)*100:.2f}%)")

                    order_id, limit_fill, limit_qty = self._execute_limit_with_fallback(
                        symbol=symbol,
                        quantity=quantity,
                        limit_price=suggested_entry
                    )

                    if order_id is None:
                        logger.error(f"❌ Both LIMIT and MARKET orders failed")
                        return None

                    # If LIMIT filled directly, skip standard fill polling
                    if limit_fill is not None and limit_fill > 0:
                        fill_price = limit_fill
                        filled_quantity = limit_qty
                        limit_filled_directly = True
                        logger.info(f"✅ LIMIT filled: {filled_quantity} @ Rs{fill_price:.2f}")
                    else:
                        logger.info(f"✅ Fallback MARKET order placed: {order_id}")
                else:
                    logger.warning(f"   ChatGPT entry Rs{suggested_entry:.2f} out of range "
                                 f"(LTP: Rs{stock_ltp:.2f}, min: Rs{min_limit:.2f})")
                    order_id = self._place_order(
                        symbol=symbol, quantity=quantity, transaction_type='BUY'
                    )
            else:
                # Standard MARKET order (existing behavior)
                order_id = self._place_order(
                    symbol=symbol, quantity=quantity, transaction_type='BUY'
                )

            if not order_id:
                logger.error(f"❌ Order placement failed")
                return None

            logger.info(f"✅ Order placed: {order_id}")

        except Exception as e:
            logger.error(f"❌ Order placement error: {e}")
            return None

        # Step 5: Wait for fill with partial fill detection (skip if LIMIT already filled)
        if limit_filled_directly:
            # LIMIT already filled — skip polling, jump to Step 6
            quantity = filled_quantity  # Use actual filled qty
            logger.info(f"   Skipping fill polling (LIMIT already filled)")
        else:
            # Standard fill polling (MARKET order or LIMIT fallback to MARKET)
            # v4.7.0 FIX TC-05: Poll for fill with partial fill detection
            # v4.7.1 FIX-01: Configurable timeout (was hardcoded 5×2s=10s, now default 15×2s=30s)
            logger.info(f"⏳ Waiting for order fill...")

            MAX_POLL_ATTEMPTS = getattr(self.config, 'BUY_FILL_MAX_POLL_ATTEMPTS', 15)
            POLL_INTERVAL = getattr(self.config, 'BUY_FILL_POLL_INTERVAL', 2)
            ALERT_AT_PCT = getattr(self.config, 'BUY_FILL_ALERT_AT_PCT', 50)
            alert_threshold = int(MAX_POLL_ATTEMPTS * ALERT_AT_PCT / 100)
            alert_sent = False

            filled_quantity = 0
            fill_price = 0
            order_status = None

            for attempt in range(MAX_POLL_ATTEMPTS):
                time.sleep(POLL_INTERVAL)

                # v4.7.1 FIX-01: "Still waiting" alert at configured threshold
                if not alert_sent and attempt >= alert_threshold and filled_quantity == 0:
                    alert_sent = True
                    elapsed = (attempt + 1) * POLL_INTERVAL
                    remaining = (MAX_POLL_ATTEMPTS - attempt - 1) * POLL_INTERVAL
                    logger.warning(f"⏳ {symbol}: Order still pending after {elapsed}s "
                                 f"({remaining}s remaining before cancel)")
                    if self.telegram:
                        self.telegram.send_message(
                            f"⏳ ORDER STILL PENDING\n\n"
                            f"Symbol: {symbol}\n"
                            f"Waiting: {elapsed}s of {MAX_POLL_ATTEMPTS * POLL_INTERVAL}s\n"
                            f"Status: {order_status or 'UNKNOWN'}\n\n"
                            f"Will cancel unfilled qty after timeout."
                        )

                try:
                    order_history = self.kite.order_history(order_id)
                    order_info = order_history[-1]  # Latest status

                    filled_quantity = order_info.get('filled_quantity', 0)
                    planned_quantity = order_info.get('quantity', quantity)
                    fill_price = order_info.get('average_price', 0)
                    order_status = order_info.get('status', '')

                    logger.debug(f"   Poll {attempt+1}/{MAX_POLL_ATTEMPTS}: "
                                f"{filled_quantity}/{planned_quantity} filled, "
                                f"status: {order_status}")

                    # Break if order reached terminal state
                    if order_status in ['COMPLETE', 'REJECTED', 'CANCELLED']:
                        break

                except Exception as e:
                    logger.warning(f"   Error polling order {order_id}: {e}")
                    continue

            # v4.7.0 TC-05: Handle zero fill
            if filled_quantity == 0:
                logger.error(f"❌ {symbol}: Order {order_id} not filled at all "
                            f"(status: {order_status})")
                try:
                    self.kite.cancel_order(variety='regular', order_id=order_id)
                    logger.info(f"   Cancelled unfilled order {order_id}")
                except Exception as cancel_err:
                    logger.debug(f"   Cancel attempt: {cancel_err}")
                return None

            # v4.7.0 TC-05: Handle partial fill
            if filled_quantity < quantity:
                logger.warning(f"⚠️ {symbol}: PARTIAL FILL - "
                              f"{filled_quantity}/{quantity} shares filled")

                try:
                    if order_status not in ['COMPLETE', 'REJECTED', 'CANCELLED']:
                        self.kite.cancel_order(variety='regular', order_id=order_id)
                        logger.info(f"   ✅ Cancelled remaining "
                                   f"{quantity - filled_quantity} unfilled shares")
                except Exception as cancel_err:
                    logger.warning(f"   ⚠️ Could not cancel remaining: {cancel_err}")

                if self.telegram:
                    self.telegram.send_message(
                        f"⚠️ PARTIAL FILL ALERT\n\n"
                        f"Symbol: {symbol}\n"
                        f"Ordered: {quantity} shares\n"
                        f"Filled: {filled_quantity} shares\n"
                        f"Unfilled: {quantity - filled_quantity} shares\n\n"
                        f"Position will be created for filled quantity only."
                    )

                # USE FILLED QUANTITY going forward
                quantity = filled_quantity
            else:
                logger.info(f"✅ {symbol}: Full fill - "
                           f"{filled_quantity} shares @ ₹{fill_price:.2f}")
        
        # Validate fill price
        if fill_price == 0:
            logger.error(f"❌ {symbol}: Invalid fill price (0)")
            return None
        
        logger.info(f"✅ Order filled @ ₹{fill_price:.2f} "
                    f"({filled_quantity} shares)")
        
        # ═══════════════════════════════════════════════════════════════
        # 🧠 AI ORDER PARAMETERS (Strategic Advisor)
        # ═══════════════════════════════════════════════════════════════
        
        # v5.3.3: Smart TCAS for CNC — ATR-based stop, aspirational target
        target_pct = signal.get('target_pct', self.config.PROFIT_TARGET_PCT)
        stop_pct = signal.get('stop_pct', self.config.STOP_LOSS_PCT)
        
        # Use ATR-based stop if ATR available from Phase 2
        signal_atr = signal.get('atr', 0)
        cnc_stop_atr_mult = getattr(self.config, 'CNC_STOP_ATR_MULTIPLIER', 2.0)
        if signal_atr > 0 and fill_price > 0:
            atr_stop_pct = (signal_atr * cnc_stop_atr_mult / fill_price) * 100
            stop_pct = round(atr_stop_pct, 2)
            logger.info(f"   📐 ATR-based stop: ATR=₹{signal_atr:.2f} × {cnc_stop_atr_mult} = "
                       f"₹{signal_atr * cnc_stop_atr_mult:.2f} ({stop_pct:.2f}%)")
        
        # Aspirational target (ILS ceiling, not exit trigger)
        target_pct = getattr(self.config, 'PROFIT_TARGET_PCT', 5.0)
        
        # Get AI-optimized parameters if enabled
        # v5.5: Skip optimize_order_parameters in LANDMINE_ONLY mode (ChatGPT no longer sets stops/targets)
        if (self.strategic_advisor and
            self.config.USE_ADVISOR_FOR_ORDER_PARAMS and
            getattr(self.config, 'CHATGPT_MODE', 'LANDMINE_ONLY') != 'LANDMINE_ONLY'):
            try:
                # Get current time of day
                hour = datetime.now().hour
                if hour < 11:
                    time_of_day = 'MORNING'
                elif hour < 14:
                    time_of_day = 'MIDDAY'
                else:
                    time_of_day = 'AFTERNOON'
                
                # Get AI-optimized order parameters
                order_params = self.strategic_advisor.optimize_order_parameters(
                    symbol=symbol,
                    entry_price=fill_price,
                    atr=0.0,  # TODO: Get from AI intelligence
                    volatility_regime=signal.get('volatility_regime', 'NORMAL'),
                    time_of_day=time_of_day,
                    current_positions=len(self.positions)
                )
                
                # Use AI-optimized parameters
                target_pct = order_params['profit_target_pct']
                stop_pct = abs(order_params['stop_loss_pct'])  # Make positive
                
                logger.info(f"🧠 AI Order Parameters:")
                logger.info(f"   Stop Loss: -{stop_pct:.1f}%")
                logger.info(f"   Target: +{target_pct:.1f}%")
                logger.info(f"   Risk:Reward: 1:{order_params['risk_reward_ratio']:.1f}")
                logger.info(f"   Reasoning: {order_params['reasoning'][:80]}...")
                
            except Exception as e:
                logger.error(f"⚠️ AI order params failed: {e}")
                # Use defaults already set above
        
        # ═══════════════════════════════════════════════════════════════
        # 🤖 AI-POWERED DYNAMIC TARGETS (v5.0.0)
        # ═══════════════════════════════════════════════════════════════
        
        # Use AI-calculated targets if available, otherwise use optimized above
        # (Already set above from signal or AI optimization)
        
        # Calculate target and stop prices
        target_price = fill_price * (1 + target_pct / 100)
        stop_price = fill_price * (1 - stop_pct / 100)

        # ═══════════════════════════════════════════════════════════════
        # v5.4: ChatGPT S/R-ALIGNED STOP & TARGET OVERRIDE
        # (v5.5: Only active in FULL_ANALYSIS mode)
        # ═══════════════════════════════════════════════════════════════
        chatgpt_stop_used = False
        chatgpt_target_used = False

        if (getattr(self.config, 'USE_CHATGPT_STOP_TARGET', False) and fill_price > 0
                and getattr(self.config, 'CHATGPT_MODE', 'LANDMINE_ONLY') != 'LANDMINE_ONLY'):
            # --- Override STOP with ChatGPT's S/R-aligned stop ---
            gpt_stop = signal.get('chatgpt_adjusted_stop_price')
            if gpt_stop is not None:
                try:
                    gpt_stop = float(gpt_stop)
                    if gpt_stop > 0 and gpt_stop < fill_price:
                        stop_dist_pct = ((fill_price - gpt_stop) / fill_price) * 100
                        min_stop = getattr(self.config, 'CHATGPT_STOP_MIN_PCT', 0.5)
                        max_stop = getattr(self.config, 'CHATGPT_STOP_MAX_PCT', 5.0)

                        if min_stop <= stop_dist_pct <= max_stop:
                            old_stop = stop_price
                            stop_price = round(gpt_stop, 2)
                            stop_pct = round(stop_dist_pct, 2)
                            chatgpt_stop_used = True
                            logger.info(f"   🎯 S/R STOP OVERRIDE: ₹{old_stop:.2f} → ₹{stop_price:.2f} "
                                       f"({stop_pct:.2f}%, below nearest support)")
                        else:
                            logger.info(f"   ⚠️ ChatGPT stop ₹{gpt_stop:.2f} ({stop_dist_pct:.1f}%) "
                                       f"outside bounds [{min_stop}-{max_stop}%], keeping ₹{stop_price:.2f}")
                    else:
                        logger.info(f"   ⚠️ ChatGPT stop ₹{gpt_stop:.2f} invalid (must be >0 and <fill), "
                                   f"keeping ₹{stop_price:.2f}")
                except (ValueError, TypeError):
                    logger.warning(f"   ⚠️ ChatGPT stop price not a valid number, keeping ₹{stop_price:.2f}")

            # --- Override TARGET with ChatGPT's S/R-aligned target ---
            gpt_target = signal.get('chatgpt_adjusted_target_price')
            if gpt_target is not None:
                try:
                    gpt_target = float(gpt_target)
                    if gpt_target > 0 and gpt_target > fill_price:
                        target_dist_pct = ((gpt_target - fill_price) / fill_price) * 100
                        min_target = getattr(self.config, 'CHATGPT_TARGET_MIN_PCT', 1.0)
                        max_target = getattr(self.config, 'CHATGPT_TARGET_MAX_PCT', 10.0)

                        if min_target <= target_dist_pct <= max_target:
                            old_target = target_price
                            target_price = round(gpt_target, 2)
                            target_pct = round(target_dist_pct, 2)
                            chatgpt_target_used = True
                            logger.info(f"   🎯 S/R TARGET OVERRIDE: ₹{old_target:.2f} → ₹{target_price:.2f} "
                                       f"(+{target_pct:.2f}%, at nearest resistance)")
                        else:
                            logger.info(f"   ⚠️ ChatGPT target ₹{gpt_target:.2f} ({target_dist_pct:.1f}%) "
                                       f"outside bounds [{min_target}-{max_target}%], keeping ₹{target_price:.2f}")
                    else:
                        logger.info(f"   ⚠️ ChatGPT target ₹{gpt_target:.2f} invalid (must be >0 and >fill), "
                                   f"keeping ₹{target_price:.2f}")
                except (ValueError, TypeError):
                    logger.warning(f"   ⚠️ ChatGPT target price not a valid number, keeping ₹{target_price:.2f}")

        # ═══════════════════════════════════════════════════════════════
        # v5.5: PRICE LEVEL ANCHORED STOP & TARGET
        # ═══════════════════════════════════════════════════════════════
        price_level_stop_used = False
        price_level_target_used = False

        if (getattr(self.config, 'USE_PRICE_LEVEL_STOPS', False) and fill_price > 0
                and getattr(self.config, 'CHATGPT_MODE', 'LANDMINE_ONLY') == 'LANDMINE_ONLY'):
            pdl = signal.get('prev_day_low', 0)
            pdh = signal.get('prev_day_high', 0)
            proximity_pct = getattr(self.config, 'PRICE_LEVEL_PROXIMITY_PCT', 2.0)
            stop_buffer = getattr(self.config, 'PRICE_LEVEL_STOP_BUFFER_PCT', 0.3)
            target_buffer = getattr(self.config, 'PRICE_LEVEL_TARGET_BUFFER_PCT', 0.3)

            # --- STOP: Anchor to PDL if it's a useful level ---
            if pdl > 0 and pdl < fill_price:
                pdl_distance_pct = ((fill_price - pdl) / fill_price) * 100

                if pdl_distance_pct <= proximity_pct:
                    # PDL is close enough to be useful — anchor stop below it
                    new_stop = pdl * (1 - stop_buffer / 100)
                    new_stop_pct = ((fill_price - new_stop) / fill_price) * 100

                    # Safety bounds: stop must be between 0.5% and 5% from entry
                    min_stop = getattr(self.config, 'CHATGPT_STOP_MIN_PCT', 0.5)
                    max_stop = getattr(self.config, 'CHATGPT_STOP_MAX_PCT', 5.0)

                    if min_stop <= new_stop_pct <= max_stop:
                        old_stop = stop_price
                        stop_price = round(new_stop, 2)
                        stop_pct = round(new_stop_pct, 2)
                        price_level_stop_used = True
                        logger.info(f"   📊 PDL STOP ANCHOR: ₹{old_stop:.2f} → ₹{stop_price:.2f} "
                                   f"({stop_pct:.2f}%, below PDL ₹{pdl:.2f})")
                    else:
                        logger.info(f"   ⚠️ PDL stop ₹{new_stop:.2f} ({new_stop_pct:.1f}%) "
                                   f"outside bounds [{min_stop}-{max_stop}%], keeping ATR stop ₹{stop_price:.2f}")
                else:
                    logger.info(f"   📊 PDL ₹{pdl:.2f} too far ({pdl_distance_pct:.1f}% > {proximity_pct}%), "
                               f"keeping ATR stop ₹{stop_price:.2f}")

            # --- TARGET: Anchor to PDH if it's a useful level ---
            if pdh > 0 and pdh > fill_price:
                pdh_distance_pct = ((pdh - fill_price) / fill_price) * 100

                if pdh_distance_pct >= 0.5:  # At least 0.5% room to PDH
                    new_target = pdh * (1 - target_buffer / 100)
                    new_target_pct = ((new_target - fill_price) / fill_price) * 100

                    # Safety bounds
                    min_target = getattr(self.config, 'CHATGPT_TARGET_MIN_PCT', 1.0)
                    max_target = getattr(self.config, 'CHATGPT_TARGET_MAX_PCT', 10.0)

                    if min_target <= new_target_pct <= max_target:
                        # Only use PDH target if it's BELOW the ATR target (more conservative)
                        if new_target < target_price:
                            old_target = target_price
                            target_price = round(new_target, 2)
                            target_pct = round(new_target_pct, 2)
                            price_level_target_used = True
                            logger.info(f"   📊 PDH TARGET ANCHOR: ₹{old_target:.2f} → ₹{target_price:.2f} "
                                       f"(+{target_pct:.2f}%, below PDH ₹{pdh:.2f})")
                        else:
                            logger.info(f"   📊 PDH target ₹{new_target:.2f} > ATR target ₹{target_price:.2f}, "
                                       f"keeping ATR target (PDH too far)")
                    else:
                        logger.info(f"   ⚠️ PDH target ₹{new_target:.2f} ({new_target_pct:.1f}%) "
                                   f"outside bounds [{min_target}-{max_target}%], keeping ATR target")
                else:
                    logger.info(f"   ⚠️ PDH ₹{pdh:.2f} only {pdh_distance_pct:.1f}% above entry — "
                               f"resistance overhead warning (not blocking trade)")

            # --- ROUND NUMBER awareness (log only, not stop/target override) ---
            round_below = signal.get('nearest_round_below', 0)
            round_above = signal.get('nearest_round_above', 0)
            if round_below > 0 and round_above > 0:
                logger.info(f"   📊 Round numbers: ₹{round_below:.0f} (below) ₹{round_above:.0f} (above)")

        if _marker_mode:
            stop_pct = float(getattr(self.config, 'MARKER_DISASTER_STOP_PCT', 8.0))
            target_pct = float(getattr(self.config, 'MARKER_TARGET_PCT', 25.0))
            stop_price = round(fill_price * (1 - stop_pct / 100), 2)
            target_price = round(fill_price * (1 + target_pct / 100), 2)
            price_level_stop_used = False
            price_level_target_used = False
            logger.info(f"   📍 MARKER MODE: disaster stop ₹{stop_price:.2f} (-{stop_pct:.1f}%), "
                        f"far target ₹{target_price:.2f} (+{target_pct:.1f}%)")

        # Volatility-adjusted position size (from AI)
        position_multiplier = signal.get('position_size_multiplier', 1.0)
        volatility_regime = signal.get('volatility_regime', 'MEDIUM')
        
        # Log AI-powered targets
        if signal.get('ai_powered', False):
            logger.info(f"═══════════════════════════════════════════")
            logger.info(f"🤖 AI-POWERED POSITION OPENED")
            logger.info(f"═══════════════════════════════════════════")
            logger.info(f"Symbol: {symbol}")
            logger.info(f"Entry: ₹{fill_price:.2f}")
            logger.info(f"Target: ₹{target_price:.2f} (+{target_pct:.1f}%)")
            logger.info(f"Stop: ₹{stop_price:.2f} (-{stop_pct:.1f}%)")
            logger.info(f"Volatility: {volatility_regime}")
            logger.info(f"Position Size: {position_multiplier*100:.0f}%")
            
            if 'finbert_sentiment' in signal and signal['finbert_sentiment']:
                sent = signal['finbert_sentiment']
                logger.info(f"Sentiment: {sent['label']} ({sent['sentiment_score']:+.2f})")
        else:
            logger.info(f"🎯 Target: ₹{target_price:.2f} (+{target_pct:.1f}%)")
            logger.info(f"🛑 Stop: ₹{stop_price:.2f} (-{stop_pct:.1f}%)")
        
        # Step 7: Save position
        position = {
            'symbol': symbol,
            'quantity': quantity,
            'entry_price': fill_price,
            'entry_value': fill_price * quantity,
            'entry_time': datetime.now().isoformat(),
            
            # ✅ AI-CALCULATED TARGETS (stock-specific!)
            'target_price': target_price,
            'stop_price': stop_price,
            'target_pct': target_pct,
            'stop_pct': stop_pct,
            
            # ✅ AI METADATA
            'position_size_multiplier': position_multiplier,
            'volatility_regime': volatility_regime,
            'ai_powered': signal.get('ai_powered', False),
            
            # ✅ STEP 3: Store original signal for ML logging
            'signal_data': signal,  # Store complete signal for ML features!
            
            # Position tracking
            'max_profit_pct': 0.0,  # Track max profit reached
            'max_drawdown_pct': 0.0,  # Track max drawdown
            
            # v4.5.2: Use PositionState constants
            'status': PositionState.OPEN,
            'order_id': order_id,
            'exchange': 'NSE',
            'product': self.config.PRODUCT_TYPE,
            
            # v4.5.2: GTT protection tracking (set after GTT placement)
            'gtt_protected': False,  # Will be set True if GTT stop placed successfully
            
            # MARKER positions are routed to Phase 4's marker pipeline (sensor-only, no quick exits)
            'strategy_mode': 'MARKER' if _marker_mode else 'STANDARD',
            'marker_low_since_entry': fill_price,
            'second_dip_signaled': False,

            # v5.3.3: Smart TCAS for CNC (same design philosophy as Phase 5 MIS)
            'smart_tcas_enabled': not _marker_mode,
            'tcas_activation_pct': getattr(self.config, 'CNC_TCAS_ACTIVATION_PCT', 0.7),
            'tcas_activation_price': fill_price * (1 + getattr(self.config, 'CNC_TCAS_ACTIVATION_PCT', 0.7) / 100),
            'tcas_trail_pct': getattr(self.config, 'CNC_TCAS_TRAIL_PCT', 0.5),
            'tcas_activated': False,
            'tcas_peak_price': fill_price,
            'atr': signal.get('atr', 0),

            # v5.4: ChatGPT S/R + LIMIT entry metadata (kept for FULL_ANALYSIS rollback)
            'chatgpt_entry_used': signal.get('chatgpt_limit_entry_used', False),
            'chatgpt_support': signal.get('chatgpt_nearest_support'),
            'chatgpt_resistance': signal.get('chatgpt_nearest_resistance'),
            'chatgpt_stop_used': chatgpt_stop_used,
            'chatgpt_target_used': chatgpt_target_used,
            'chatgpt_delivery_signal': signal.get('chatgpt_delivery_signal', 'UNKNOWN'),
            'chatgpt_oi_signal': signal.get('chatgpt_oi_signal', 'UNKNOWN'),

            # v5.5: Price level metadata (replaces ChatGPT S/R in LANDMINE_ONLY mode)
            'price_level_stop_used': price_level_stop_used,
            'price_level_target_used': price_level_target_used,
            'prev_day_high': signal.get('prev_day_high', 0),
            'prev_day_low': signal.get('prev_day_low', 0),
            'prev_week_high': signal.get('prev_week_high', 0),
            'prev_week_low': signal.get('prev_week_low', 0),

            # PAPER MODE flag — Phase4 uses this to skip real GTT/order ops
            'is_paper_trade': getattr(self.config, 'MASTER_PAPER_MODE', False),
            'paper_logger_id': '',   # filled below in paper mode
        }

        # PAPER MODE: log entry to paper_trade_logger → Excel
        if getattr(self.config, 'MASTER_PAPER_MODE', False):
            try:
                from paper_trade_logger import log_paper_entry
                _logger_id = log_paper_entry(
                    phase="PH3",
                    symbol=symbol,
                    direction="BUY",
                    entry_price=fill_price,
                    quantity=quantity,
                    stop_loss=stop_price,
                    target=target_price,
                    strategy=signal.get('strategy', 'CNC'),
                    score=signal.get('entry_score', 0),
                    regime=signal.get('volatility_regime', ''),
                    notes=f"product={self.config.PRODUCT_TYPE}"
                )
                position['paper_logger_id'] = _logger_id
                logger.info(f"   📊 PAPER LOG: PH3 entry recorded → {_logger_id}")
            except Exception as _le:
                logger.warning(f"   ⚠️ paper_trade_logger PH3 entry failed: {_le}")

        # v4.9.0: Use helper method for consistent position tracking
        self._set_position(symbol, position)
        self.capital_used += fill_price * quantity
        
        # ═══════════════════════════════════════════════════════════════════
        # v4.5.3 NEW: Deploy capital via Capital Manager
        # ═══════════════════════════════════════════════════════════════════
        entry_value = fill_price * quantity
        if self.capital_manager:
            try:
                deploy_success = self.capital_manager.deploy(
                    symbol=symbol,
                    amount=entry_value,
                    quantity=quantity,
                    entry_price=fill_price,
                    product=self.config.PRODUCT_TYPE  # v5.1.0 FIX: Pass actual product type (CNC/MIS)
                )
                if deploy_success:
                    logger.info(f"💰 Capital Manager: Deployed ₹{entry_value:,.0f} for {symbol}")
                else:
                    logger.warning(f"⚠️ Capital Manager: Deploy returned False for {symbol}")
            except Exception as e:
                logger.error(f"❌ Capital Manager deploy failed: {e}")

        # ═══════════════════════════════════════════════════════════════════
        # v6.0: Phase 6 Options Advisory (Paper Trade)
        # Generate Bull Call Spread recommendation for this stock
        # ═══════════════════════════════════════════════════════════════════
        if _marker_mode:
            logger.info(f"   📍 MARKER MODE: options advisory deferred to 2nd-dip signal from Phase 4")
        elif self.options_advisor and getattr(self.config, 'PH6_OPTIONS_ADVISORY_ENABLED', False):
            try:
                options_advisory = self.options_advisor.generate_advisory(
                    symbol=symbol,
                    equity_order_id=str(order_id),
                    equity_entry_price=fill_price,
                    phase2_score=signal.get('entry_score', 0),
                )
                if options_advisory:
                    logger.info(f"   📊 Options Advisory: {options_advisory.spread_type} "
                               f"| Max Profit: ₹{options_advisory.max_profit:,.0f} "
                               f"| Confidence: {options_advisory.confidence}/100")
                    position['options_advisory_id'] = options_advisory.id
                else:
                    logger.info(f"   📊 Options Advisory: No spread recommended for {symbol}")
            except Exception as e:
                logger.error(f"   ⚠️ Options advisory failed for {symbol}: {e}")
        elif getattr(self.config, 'PH6_OPTIONS_ADVISORY_ENABLED', False) and not self.options_advisor:
            logger.warning(f"   📊 Phase 6: options_advisor not wired — skipping advisory for {symbol}")

        # Save to positions file
        self._save_position(position)
        
        # ═══════════════════════════════════════════════════════════════
        # PLACE GTT ORDERS FOR SAFETY (Phase 4 Integration)
        # v4.5.2: Added gtt_protected flag for visibility
        # v4.7.1 FIX-04: Retry GTT placement before manual stop fallback
        # ═══════════════════════════════════════════════════════════
        # v2.1.0: CNC MAX-LOSS CAP (Stage 2 — GTT safety check)
        # The actual stop may be wider than the estimated stop used at buy-time
        # (ATR-based, PDL-anchored overrides can change stop_pct after fill).
        # If actual loss still exceeds cap, we CANNOT reduce qty (shares already bought),
        # so we alert loudly for manual intervention.
        _cnc_loss_cap = getattr(self.config, 'CNC_MAX_LOSS_CAP', 150)
        _actual_stop_dist = fill_price - stop_price
        if _actual_stop_dist > 0:
            _actual_max_loss = _actual_stop_dist * quantity
            if _actual_max_loss > _cnc_loss_cap:
                logger.warning(
                    f"   ⚠️ CNC LOSS CAP BREACH: {symbol} actual stop dist "
                    f"₹{_actual_stop_dist:.2f} × {quantity} qty = ₹{_actual_max_loss:.0f} "
                    f"(cap ₹{_cnc_loss_cap}). Stage 1 estimate was too narrow. "
                    f"MANUAL REVIEW RECOMMENDED."
                )
                if self.telegram:
                    self.telegram.send_message(
                        f"⚠️ CNC LOSS CAP BREACH: {symbol}\n"
                        f"Stop dist ₹{_actual_stop_dist:.2f} × {quantity} shares "
                        f"= ₹{_actual_max_loss:.0f} max loss\n"
                        f"Cap is ₹{_cnc_loss_cap} — consider closing {quantity} → "
                        f"{max(1, int(_cnc_loss_cap / _actual_stop_dist))} shares manually"
                    )

        if getattr(self.config, 'MASTER_PAPER_MODE', False):
            logger.info("   📝 PAPER MODE: no broker GTT — Phase 4 monitors the stop")
        elif getattr(self.config, 'ENABLE_GTT_ORDERS', True):
            MAX_GTT_RETRIES = getattr(self.config, 'GTT_PLACEMENT_RETRIES', 2)
            GTT_RETRY_DELAY = getattr(self.config, 'GTT_RETRY_DELAY_SECONDS', 3)
            gtt_ids = None
            gtt_last_error = None
            
            # v4.7.1 FIX-04: Retry loop for transient failures
            for gtt_attempt in range(MAX_GTT_RETRIES + 1):
                try:
                    gtt_ids = self._place_gtt_orders(
                        symbol=symbol,
                        quantity=quantity,
                        stop_price=stop_price,
                        target_price=target_price,
                        pdl_tag=" [PDL]" if price_level_stop_used else "",
                        pdh_tag=" [PDH]" if price_level_target_used else "",
                        current_price=fill_price
                    )
                    
                    if gtt_ids and gtt_ids.get('stop_id'):
                        # GTT stop placed successfully
                        position['gtt_stop_id'] = gtt_ids.get('stop_id')
                        position['gtt_target_id'] = gtt_ids.get('target_id')
                        position['gtt_active'] = True
                        position['gtt_protected'] = True
                        self._save_position(position)
                        
                        if gtt_attempt > 0:
                            logger.info(f"\u2705 {symbol}: GTT placed on retry {gtt_attempt} "
                                      f"(Stop ID: {gtt_ids['stop_id']})")
                            if self.telegram:
                                self.telegram.send_message(
                                    f"\u2705 GTT RECOVERED\n\n"
                                    f"Symbol: {symbol}\n"
                                    f"Attempt: {gtt_attempt+1}/{MAX_GTT_RETRIES+1}\n"
                                    f"GTT Stop ID: {gtt_ids['stop_id']}"
                                )
                        else:
                            logger.info(f"\u2705 {symbol}: Position PROTECTED "
                                      f"(GTT Stop ID: {gtt_ids['stop_id']})")
                        
                        logger.info(f"\u2705 GTT orders placed for {symbol}")
                        break  # Success - exit retry loop
                    
                    elif gtt_ids:
                        # GTT returned IDs but stop_id is None (target may have worked)
                        position['gtt_target_id'] = gtt_ids.get('target_id')
                        position['gtt_active'] = bool(gtt_ids.get('target_id'))
                        gtt_last_error = "GTT stop returned None"
                        logger.warning(f"\u26a0\ufe0f {symbol}: GTT attempt {gtt_attempt+1}/{MAX_GTT_RETRIES+1} - "
                                     f"stop_id is None")
                    else:
                        gtt_last_error = "GTT placement returned empty"
                        logger.warning(f"\u26a0\ufe0f {symbol}: GTT attempt {gtt_attempt+1}/{MAX_GTT_RETRIES+1} - "
                                     f"returned empty")
                    
                except Exception as e:
                    gtt_last_error = str(e)
                    logger.warning(f"\u26a0\ufe0f {symbol}: GTT attempt {gtt_attempt+1}/{MAX_GTT_RETRIES+1} "
                                 f"failed: {e}")
                
                # If not last attempt, wait before retry
                if gtt_attempt < MAX_GTT_RETRIES:
                    logger.info(f"   Retrying GTT in {GTT_RETRY_DELAY}s...")
                    time.sleep(GTT_RETRY_DELAY)
            
            # After all attempts: check if GTT stop was successfully placed
            if not position.get('gtt_protected'):
                # ALL RETRIES EXHAUSTED - activate manual stop fallback (TC-06)
                position['gtt_protected'] = False
                position['gtt_active'] = False
                self._save_position(position)
                
                logger.critical(f"\U0001f6a8 {symbol}: Position UNPROTECTED - "
                              f"GTT failed after {MAX_GTT_RETRIES+1} attempts! "
                              f"Last error: {gtt_last_error}")
                
                # v4.7.0 FIX TC-06: Activate manual stop monitoring
                stop_p = position.get('stop_price')
                if stop_p:
                    self.manual_stop_positions[symbol] = {
                        'stop_price': stop_p,
                        'target_price': position.get('target_price'),
                        'entry_price': position.get('entry_price'),
                        'entry_time': datetime.now(),
                        'last_check': datetime.now(),
                        'emergency_timeout': 300  # 5 minutes
                    }
                    logger.warning(f"\u26a0\ufe0f {symbol}: Activated MANUAL STOP monitoring @ \u20b9{stop_p:.2f}")
                
                # CRITICAL Telegram alert
                if self.telegram:
                    self.telegram.send_message(
                        f"\U0001f6a8 CRITICAL: GTT PLACEMENT FAILED!\n\n"
                        f"Symbol: {symbol}\n"
                        f"Attempts: {MAX_GTT_RETRIES+1}\n"
                        f"Error: {str(gtt_last_error)[:100]}\n\n"
                        f"\u26a0\ufe0f MANUAL STOP MONITORING ACTIVATED\n"
                        f"Stop Price: \u20b9{(f'{stop_p:.2f}' if stop_p else 'N/A')}\n\n"
                        f"System will monitor and exit if stop hit.\n"
                        f"Emergency exit in 5 min if stop not working."
                    )
        else:
            # GTT disabled by config
            position['gtt_protected'] = False
            position['gtt_active'] = False
        
        # Save order to orders file
        self._log_order({
            'order_id': order_id,
            'symbol': symbol,
            'exchange': 'NSE',
            'transaction': 'BUY',
            'quantity': quantity,
            'price': fill_price,
            'value': fill_price * quantity,
            'timestamp': datetime.now().isoformat(),
            'status': 'COMPLETE'
        })
        
        # Telegram notification
        ai_info = ""
        if signal.get('ai_powered', False):
            ai_info = f"\n\n🤖 AI-POWERED ENTRY:\n" \
                     f"├─ Volatility: {volatility_regime}\n" \
                     f"├─ Position Size: {position_multiplier*100:.0f}% of base\n" \
                     f"├─ Dynamic Target: {target_pct:+.1f}%\n" \
                     f"└─ Dynamic Stop: {stop_pct:+.1f}%"
        
        if self.telegram:
            pdl_tag = " [PDL]" if price_level_stop_used else ""
            pdh_tag = " [PDH]" if price_level_target_used else ""
            self.telegram.send_message(
                f"✅ ORDER FILLED\n\n"
                f"Stock: {symbol}\n"
                f"Qty: {quantity} shares (AI-adjusted)\n"
                f"Price: ₹{fill_price:.2f}\n"
                f"Value: ₹{fill_price * quantity:,.0f}\n\n"
                f"🎯 Target: ₹{target_price:.2f} (+{target_pct:.1f}%){pdh_tag}\n"
                f"🛑 Stop: ₹{stop_price:.2f} (-{stop_pct:.1f}%){pdl_tag}"
                f"{ai_info}"
            )
        
        return position
    
    
    def _validate_signal(self, signal: dict) -> Tuple[bool, str]:
        """
        8-point pre-trade validation WITH EMERGENCY BUFFER PROTECTION.
        
        ✅ v2.1.0 FIX: Now enforces emergency buffer before every trade!
        
        Checks:
        1. Symbol validity
        2. Signal freshness (< 15 min)
        3. Market hours (entry window)
        4. Position limit (< 2 per stock)
        5. ✅ NEW: Capital availability WITH EMERGENCY BUFFER!
        6. Signal confidence (>= 70%)
        7. Signal approved flag
        8. Daily loss limit (circuit breaker)
        """
        symbol = signal.get('symbol', signal.get('stock'))
        
        # ════════════════════════════════════════════════════════════════════
        # CHECK 1: Symbol validity
        # ════════════════════════════════════════════════════════════════════
        if not symbol:
            return False, "Invalid symbol"
        
        logger.info(f"🔍 Validating signal for {symbol}...")
        
        # ════════════════════════════════════════════════════════════════════
        # CHECK 1.5: v4.7.2 NEW - STOCK COOLDOWN CHECK (Prevents re-entry loop!)
        # ════════════════════════════════════════════════════════════════════
        cooldown_ok, cooldown_reason = self._check_stock_cooldown(symbol)
        if not cooldown_ok:
            logger.warning(f"  ❌ {symbol}: COOLDOWN BLOCKED - {cooldown_reason}")
            return False, f"Cooldown: {cooldown_reason}"
        
        logger.info(f"  ✅ Cooldown check OK")
        
        # ════════════════════════════════════════════════════════════════════
        # CHECK 2: Signal freshness
        # ════════════════════════════════════════════════════════════════════
        if 'timestamp' in signal:
            signal_time = datetime.fromisoformat(signal['timestamp'])
            age = (datetime.now() - signal_time).total_seconds() / 60
            
            if age > 15:
                logger.warning(f"  ❌ Signal too old ({age:.1f} min)")
                return False, f"Signal too old ({age:.1f} min)"
        
        logger.info(f"  ✅ Signal freshness OK")
        
        # ════════════════════════════════════════════════════════════════════
        # CHECK 3: Market hours (Entry Window)
        # ════════════════════════════════════════════════════════════════════
        now = datetime.now()
        hour, minute = now.hour, now.minute
        
        entry_start = (self.config.ENTRY_START_HOUR, self.config.ENTRY_START_MIN)
        entry_end = (self.config.ENTRY_END_HOUR, self.config.ENTRY_END_MIN)
        
        current_time = (hour, minute)
        
        if not (entry_start <= current_time <= entry_end):
            reason = f"Outside entry window ({entry_start[0]}:{entry_start[1]:02d} - {entry_end[0]}:{entry_end[1]:02d})"
            logger.warning(f"  ❌ {reason}")
            return False, reason
        
        logger.info(f"  ✅ Entry window OK ({now.strftime('%H:%M')})")
        
        # ════════════════════════════════════════════════════════════════════
        # CHECK 4: Position limit per stock (v5.2.1: Read from config)
        # ════════════════════════════════════════════════════════════════════
        max_per_stock = getattr(self.config, 'MAX_POSITIONS_PER_STOCK', 2)
        current_positions = sum(1 for s, p in self.positions.items() 
                               if s == symbol and p['status'] == 'OPEN')
        
        if current_positions >= max_per_stock:
            logger.warning(f"  ❌ Position limit reached ({current_positions}/{max_per_stock}) for {symbol}")
            return False, f"Position limit reached ({current_positions}/{max_per_stock})"
        
        logger.info(f"  ✅ Position limit OK ({current_positions}/{max_per_stock})")
        
        # ════════════════════════════════════════════════════════════════════
        # CHECK 5: CAPITAL AVAILABILITY WITH EMERGENCY BUFFER! ✅ FIX v2.3.0
        # ════════════════════════════════════════════════════════════════════
        try:
            # Get available capital from Zerodha
            margins = self.kite.margins()
            available_capital = margins.get('equity', {}).get('available', {}).get('live_balance', 0)
            
            # ✅ FIX: Calculate USABLE capital (total - emergency buffer)
            emergency_buffer = getattr(self.config, 'EMERGENCY_BUFFER', 4000)
            usable_capital = available_capital - emergency_buffer
            
            # Get entry price
            entry_price = signal.get('entry_price', signal.get('ltp', 0))
            
            # ✅ FIX v2.3.0: Use MIN(config_capital, usable_capital) for quantity
            config_capital = self.config.BASE_CAPITAL_PER_TRADE
            effective_capital = min(config_capital, usable_capital) if usable_capital > 0 else 0
            
            # Calculate quantity based on EFFECTIVE capital
            quantity = max(1, int(effective_capital / entry_price)) if entry_price > 0 and effective_capital > 0 else 0
            required_capital = entry_price * quantity if quantity > 0 else entry_price
            
            # Add buffer for price movement (5%)
            required_with_buffer = required_capital * 1.05
            
            logger.info(f"  💰 Capital Check (Validation):")
            logger.info(f"     Zerodha Available: ₹{available_capital:,.0f}")
            logger.info(f"     Emergency Buffer: ₹{emergency_buffer:,.0f} (PROTECTED)")
            logger.info(f"     Usable Capital: ₹{usable_capital:,.0f}")
            logger.info(f"     Config Capital: ₹{config_capital:,.0f}")
            logger.info(f"     Effective Capital: ₹{effective_capital:,.0f}")
            logger.info(f"     Estimated Qty: {quantity} shares @ ₹{entry_price:.0f}")
            logger.info(f"     Required (with 5% buffer): ₹{required_with_buffer:,.0f}")
            
            if usable_capital <= 0:
                reason = (
                    f"NO USABLE CAPITAL (Buffer Protected!)\n"
                    f"   Available: ₹{available_capital:,.0f}\n"
                    f"   Buffer: ₹{emergency_buffer:,.0f}\n"
                    f"   Usable: ₹{usable_capital:,.0f}"
                )
                logger.warning(f"  ❌ {reason}")
                return False, reason
            
            if quantity < 1:
                reason = (
                    f"CANNOT AFFORD EVEN 1 SHARE\n"
                    f"   Usable: ₹{usable_capital:,.0f}\n"
                    f"   Stock Price: ₹{entry_price:,.0f}"
                )
                logger.warning(f"  ❌ {reason}")
                return False, reason
            
            if usable_capital < required_with_buffer:
                reason = (
                    f"INSUFFICIENT CAPITAL (Buffer Protected!)\n"
                    f"   Available: ₹{available_capital:,.0f}\n"
                    f"   Buffer: ₹{emergency_buffer:,.0f}\n"
                    f"   Usable: ₹{usable_capital:,.0f}\n"
                    f"   Required: ₹{required_with_buffer:,.0f}"
                )
                logger.warning(f"  ❌ {reason}")
                
                # Send Telegram alert
                if self.telegram:
                    self.telegram.send_message(
                        f"⚠️ TRADE BLOCKED - CAPITAL PROTECTION\n\n"
                        f"Stock: {symbol}\n"
                        f"Entry Price: ₹{entry_price:,.2f}\n\n"
                        f"💰 Capital Status:\n"
                        f"  Available: ₹{available_capital:,.0f}\n"
                        f"  Buffer: ₹{emergency_buffer:,.0f} (protected)\n"
                        f"  Usable: ₹{usable_capital:,.0f}\n"
                        f"  Required: ₹{required_with_buffer:,.0f}\n\n"
                        f"❌ Trade rejected to preserve emergency buffer"
                    )
                
                return False, reason
            
            logger.info(f"  ✅ Capital OK (₹{usable_capital:,.0f} usable after buffer)")
            
        except Exception as e:
            logger.error(f"  ⚠️ Capital check failed: {e}")
            # Fail-safe: Allow trade if capital check fails (previous behavior)
            logger.warning(f"  ⚠️ Proceeding with trade (capital check error)")
        
        # ════════════════════════════════════════════════════════════════════
        # CHECK 6: Signal confidence
        # ════════════════════════════════════════════════════════════════════
        confidence = signal.get('confidence', 100)
        if confidence < 70:
            logger.warning(f"  ❌ Low confidence ({confidence}%)")
            return False, f"Low confidence ({confidence}%)"
        
        logger.info(f"  ✅ Confidence OK ({confidence}%)")
        
        # ════════════════════════════════════════════════════════════════════
        # CHECK 7: Approved flag
        # ════════════════════════════════════════════════════════════════════
        if not signal.get('approved', False):
            logger.warning(f"  ❌ Signal not approved")
            return False, "Signal not approved"
        
        logger.info(f"  ✅ Signal approved")
        
        # ════════════════════════════════════════════════════════════════════
        # CHECK 8: Daily loss limit (Circuit Breaker)
        # ════════════════════════════════════════════════════════════════════
        try:
            daily_pnl = self._get_daily_pnl()
            max_daily_loss = getattr(self.config, 'MAX_DAILY_LOSS', 500)
            
            if daily_pnl < -max_daily_loss:
                reason = f"CIRCUIT BREAKER: Daily loss ₹{abs(daily_pnl):,.0f} exceeds limit ₹{max_daily_loss}"
                logger.error(f"  🚨 {reason}")
                
                if self.telegram:
                    self.telegram.send_message(
                        f"🚨 CIRCUIT BREAKER TRIGGERED!\n\n"
                        f"Daily Loss: ₹{abs(daily_pnl):,.0f}\n"
                        f"Limit: ₹{max_daily_loss}\n\n"
                        f"❌ All trading halted for today"
                    )
                
                return False, reason
            
            logger.info(f"  ✅ Daily P&L OK (₹{daily_pnl:+,.0f})")
            
        except Exception as e:
            logger.warning(f"  ⚠️ Could not check daily P&L: {e}")
        
        # ════════════════════════════════════════════════════════════════════
        # ALL CHECKS PASSED!
        # ════════════════════════════════════════════════════════════════════
        logger.info(f"✅ ALL VALIDATIONS PASSED for {symbol}")
        
        return True, "OK"
    
    
    def _get_daily_pnl(self) -> float:
        """
        Get today's realized P&L from closed positions.
        
        Returns:
            Today's P&L in rupees
        """
        try:
            today = datetime.now().date()
            daily_pnl = 0.0
            
            for pos_id, pos in self.positions.items():
                if pos.get('status') == 'CLOSED':
                    exit_time = pos.get('exit_time')
                    if exit_time:
                        exit_date = datetime.fromisoformat(exit_time).date()
                        if exit_date == today:
                            daily_pnl += pos.get('profit_loss', 0)
            
            return daily_pnl
            
        except Exception as e:
            logger.error(f"Error calculating daily P&L: {e}")
            return 0.0
    
    
    def get_capital_status(self) -> Dict:
        """
        Get current capital status with emergency buffer.
        
        ✅ NEW HELPER METHOD (v2.1.0)
        
        Returns:
            Dict with capital breakdown
        """
        try:
            margins = self.kite.margins()
            available = margins.get('equity', {}).get('available', {}).get('live_balance', 0)
            
            emergency_buffer = getattr(self.config, 'EMERGENCY_BUFFER', 4000)
            usable = available - emergency_buffer
            
            # Count open positions
            open_positions = [p for p in self.positions.values() if p.get('status') == 'OPEN']
            deployed = sum(p.get('entry_price', 0) * p.get('quantity', 0) for p in open_positions)
            
            return {
                'available': available,
                'emergency_buffer': emergency_buffer,
                'usable': usable,
                'deployed': deployed,
                'open_positions': len(open_positions),
                'can_trade': usable > 0,
                'buffer_protected': True
            }
            
        except Exception as e:
            logger.error(f"Capital status error: {e}")
            return {
                'error': str(e),
                'buffer_protected': True
            }
    
    
    def _place_order(self, symbol: str, quantity: int, transaction_type: str, product: str = None) -> Optional[str]:
        """
        Place order via Kite API.
        
        Args:
            symbol: Stock symbol (e.g., 'HDFCBANK')
            quantity: Number of shares
            transaction_type: 'BUY' or 'SELL'
            product: Product type ('MIS' or 'CNC'). If None, uses config.PRODUCT_TYPE
        
        Returns:
            Order ID if successful, None otherwise
        """
        # Use provided product or fallback to config
        if product is None:
            product = self.config.PRODUCT_TYPE

        # PAPER MODE FIX: never hit real broker in paper mode
        if getattr(self.config, 'MASTER_PAPER_MODE', False):
            from paper_kite_proxy import PaperKiteProxy
            if isinstance(self.kite, PaperKiteProxy):
                # The proxy records qty/price so the fill check that follows can answer COMPLETE
                return self.kite.place_order(tradingsymbol=symbol, exchange='NSE',
                                             transaction_type=transaction_type, quantity=quantity,
                                             order_type='MARKET', product=product)
            import uuid
            paper_id = f"PH3_PAPER_{uuid.uuid4().hex[:8].upper()}"
            try:
                quote = self.kite.quote([f"NSE:{symbol}"])
                sim_price = quote.get(f"NSE:{symbol}", {}).get('last_price', 0)
            except Exception:
                sim_price = 0
            logger.info(f"   📝 PAPER ORDER: {transaction_type} {quantity} {symbol} @ ₹{sim_price:.2f}  id={paper_id}")
            return paper_id

        try:
            # v5.4.0 SEBI FIX: Raw API call to inject market_protection=-1
            import requests
            url = "https://api.kite.trade/orders/regular"
            headers = {
                "X-Kite-Version": "3",
                "Authorization": f"token {self.kite.api_key}:{self.kite.access_token}"
            }
            payload = {
                "tradingsymbol": symbol,
                "exchange": "NSE",
                "transaction_type": transaction_type,
                "quantity": str(quantity),
                "product": product,
                "order_type": "MARKET",
                "validity": "DAY",
                "market_protection": "-1"
            }
            response = requests.post(url, headers=headers, data=payload, timeout=10)
            response_json = response.json()
            if response.status_code == 200 and response_json.get('status') == 'success':
                order_id = response_json.get('data', {}).get('order_id')
            else:
                logger.error(f"PH3 order raw API failed: {response_json}")
                order_id = None

            return order_id

        except Exception as e:
            logger.error(f"Order placement error: {e}")
            return None

    def _place_limit_order(self, symbol: str, quantity: int,
                            price: float, product: str = None) -> Optional[str]:
        """
        v5.4: Place LIMIT BUY order at specified price.

        Args:
            symbol: Stock symbol
            quantity: Number of shares
            price: Limit price (must be > 0)
            product: Product type. If None, uses config.PRODUCT_TYPE

        Returns:
            Order ID if placed successfully, None otherwise
        """
        if product is None:
            product = self.config.PRODUCT_TYPE

        try:
            order_id = self.kite.place_order(
                variety=self.kite.VARIETY_REGULAR,
                exchange=self.kite.EXCHANGE_NSE,
                tradingsymbol=symbol,
                transaction_type='BUY',
                quantity=quantity,
                product=product,
                order_type=self.kite.ORDER_TYPE_LIMIT,
                price=price,
                validity=self.kite.VALIDITY_DAY
            )

            logger.info(f"   LIMIT order placed: {order_id} @ Rs{price:.2f}")
            return order_id

        except Exception as e:
            logger.error(f"   LIMIT order placement error: {e}")
            return None

    def _execute_limit_with_fallback(self, symbol: str, quantity: int,
                                      limit_price: float, product: str = None):
        """
        v5.4: Place LIMIT order, wait for fill, fallback to MARKET if not filled.

        Returns:
            Tuple of (order_id, fill_price, filled_quantity)
            fill_price=None means caller should use standard fill polling
        """
        timeout = getattr(self.config, 'LIMIT_ORDER_TIMEOUT', 60)
        poll_interval = getattr(self.config, 'LIMIT_ORDER_POLL_INTERVAL', 2)

        # Step 1: Place LIMIT order
        logger.info(f"📤 LIMIT BUY @ Rs{limit_price:.2f} (timeout: {timeout}s)")
        order_id = self._place_limit_order(symbol, quantity, limit_price, product)

        if not order_id:
            logger.warning(f"   LIMIT failed, falling back to MARKET immediately")
            market_id = self._place_order(symbol, quantity, 'BUY', product)
            return (market_id, None, 0)

        # Step 2: Poll for LIMIT fill
        start_time = time.time()
        filled_quantity = 0
        fill_price = 0
        order_status = None
        max_polls = int(timeout / poll_interval)

        for attempt in range(max_polls):
            time.sleep(poll_interval)

            try:
                order_history = self.kite.order_history(order_id)
                order_info = order_history[-1]

                filled_quantity = order_info.get('filled_quantity', 0)
                fill_price = order_info.get('average_price', 0)
                order_status = order_info.get('status', '')

                elapsed = int(time.time() - start_time)
                logger.debug(f"   LIMIT poll {attempt+1}/{max_polls}: "
                            f"{filled_quantity}/{quantity} filled, "
                            f"status={order_status}, {elapsed}s")

                if order_status == 'COMPLETE':
                    logger.info(f"   ✅ LIMIT filled @ Rs{fill_price:.2f} "
                              f"({filled_quantity} shares, {elapsed}s)")
                    return (order_id, fill_price, filled_quantity)

                if order_status in ['REJECTED', 'CANCELLED']:
                    logger.warning(f"   LIMIT {order_status}: "
                                 f"{order_info.get('status_message', '')}")
                    break

            except Exception as e:
                logger.warning(f"   Error polling LIMIT order: {e}")
                continue

        # Step 3: LIMIT not filled — cancel and go MARKET
        elapsed = int(time.time() - start_time)
        logger.warning(f"   LIMIT not filled after {elapsed}s "
                      f"(filled: {filled_quantity}/{quantity})")

        # Cancel unfilled LIMIT order
        try:
            if order_status not in ['COMPLETE', 'REJECTED', 'CANCELLED']:
                self.kite.cancel_order(variety='regular', order_id=order_id)
                logger.info(f"   Cancelled LIMIT order {order_id}")
        except Exception as e:
            logger.warning(f"   Cancel LIMIT error (may already be filled): {e}")

        # If partially filled, use what we got
        if filled_quantity > 0 and fill_price > 0:
            logger.info(f"   LIMIT partial fill: {filled_quantity} shares @ Rs{fill_price:.2f}")
            return (order_id, fill_price, filled_quantity)

        # Full MARKET fallback
        logger.info(f"   Falling back to MARKET order for {quantity} shares")

        if self.telegram:
            try:
                self.telegram.send_message(
                    f"⚡ LIMIT→MARKET FALLBACK\n\n"
                    f"Symbol: {symbol}\n"
                    f"LIMIT @ Rs{limit_price:.2f} not filled in {elapsed}s\n"
                    f"Switching to MARKET order"
                )
            except Exception:
                pass

        market_id = self._place_order(symbol, quantity, 'BUY', product)
        return (market_id, None, 0)


    def _wait_for_fill(self, order_id: str, timeout: int = 60) -> Optional[float]:
        """
        Wait for order to fill.
        
        Args:
            order_id: Order ID
            timeout: Timeout in seconds
        
        Returns:
            Fill price if successful, None otherwise
        """
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            try:
                orders = self.kite.orders()
                
                for order in orders:
                    if order['order_id'] == order_id:
                        if order['status'] == 'COMPLETE':
                            return order['average_price']
                        elif order['status'] in ['REJECTED', 'CANCELLED']:
                            logger.error(f"Order {order['status']}: {order.get('status_message', 'Unknown')}")
                            return None
                
                time.sleep(2)
                
            except Exception as e:
                logger.error(f"Error checking order status: {e}")
                time.sleep(2)
        
        logger.error(f"Order fill timeout after {timeout}s")
        return None
    
    
    def _place_market_order(self, symbol: str, quantity: int, 
                            transaction_type: str, product: str) -> Optional[str]:
        """
        v4.7.0 FIX TC-10: Place MARKET order as fallback for failed LIMIT orders.
        
        Market orders execute at best available price, guaranteeing fill.
        Used after multiple LIMIT order failures during position exit.
        
        Args:
            symbol: Stock symbol (e.g., 'HDFCBANK')
            quantity: Number of shares
            transaction_type: 'BUY' or 'SELL'
            product: Product type ('MIS' or 'CNC')
        
        Returns:
            Order ID if successful, None otherwise
        """
        try:
            # v5.4.0 SEBI FIX: Raw API call to inject market_protection=-1
            import requests
            url = "https://api.kite.trade/orders/regular"
            headers = {
                "X-Kite-Version": "3",
                "Authorization": f"token {self.kite.api_key}:{self.kite.access_token}"
            }
            payload = {
                "tradingsymbol": symbol,
                "exchange": "NSE",
                "transaction_type": transaction_type,
                "quantity": str(quantity),
                "product": product,
                "order_type": "MARKET",
                "validity": "DAY",
                "market_protection": "-1"
            }
            response = requests.post(url, headers=headers, data=payload, timeout=10)
            response_json = response.json()
            if response.status_code == 200 and response_json.get('status') == 'success':
                order_id = response_json.get('data', {}).get('order_id')
            else:
                logger.error(f"   PH3 MARKET fallback raw API failed: {response_json}")
                order_id = None

            logger.info(f"   MARKET order placed: {order_id}")
            return order_id

        except Exception as e:
            logger.error(f"   MARKET order failed: {e}")
            return None
    
    
    # ═══════════════════════════════════════════════════════════════════════════
    # v4.9.0: monitor_positions() REMOVED
    # ═══════════════════════════════════════════════════════════════════════════
    # This loop-based monitoring method was never called by orchestrator.
    # Phase 4 now handles all position monitoring via run_monitoring_cycle().
    # ═══════════════════════════════════════════════════════════════════════════
    
    
    
    # ═══════════════════════════════════════════════════════════════════════
    # ORCHESTRATOR COMPATIBILITY METHODS (Added for interrupt-based system)
    # ═══════════════════════════════════════════════════════════════════════
    
    def has_open_positions(self) -> bool:
        """
        Check if any positions are currently open.
        
        Called by orchestrator to determine sleep time.
        If positions open, orchestrator checks exits every 10 seconds.
        
        Returns:
            True if any positions open, False otherwise
        """
        return len(self.positions) > 0
    
    # ═══════════════════════════════════════════════════════════════════════════
    # v4.9.0: EXIT MONITORING LOGIC REMOVED - PHASE 4 NOW HANDLES ALL EXITS
    # ═══════════════════════════════════════════════════════════════════════════
    #
    # The following methods have been REMOVED (~517 lines):
    #
    # REMOVED - Exit Decision Methods (Phase 4 handles these now):
    # - check_position_exits()     - 218 lines - Stop/target/time monitoring
    # - check_manual_stops()       - 113 lines - GTT fallback protection  
    # - _exit_position_by_symbol() -  40 lines - Single symbol exit
    # - _partial_exit()            -  77 lines - Partial position exit
    # - _check_position_exit()     -  44 lines - Single position check
    # - _close_all_positions()     -  25 lines - Duplicate of close_all_positions
    #
    # KEPT - SELL Order Execution (Phase 4 calls these):
    # - close_all_positions()      - Emergency/market close
    # - _close_position()          - Actual SELL order placement
    #
    # Phase 3 is now ENTRY-ONLY:
    # - execute_signal_realtime()  - Execute BUY signals
    # - _place_gtt_orders()        - Place initial GTT protection
    # - _close_position()          - SELL order (called by Phase 4)
    #
    # Phase 4 handles all exit decisions via:
    # - TCAS: Stop loss collision avoidance
    # - ILS: Target approach monitoring
    # - ChatGPT: Intelligent exit decisions
    # - Health scoring: Position quality tracking
    # ═══════════════════════════════════════════════════════════════════════════
    
    
    def close_all_positions(self, reason: str = "Manual Close"):
        """
        Close all open positions immediately.
        
        v4.9.0: Now delegates to Phase 4 for SELL order execution.
        Phase 3 is ENTRY-ONLY. Phase 4 handles all exits.
        
        Called by orchestrator during shutdown or emergency.
        
        Args:
            reason: Reason for closing (for logging)
        """
        if not self.positions:
            logger.info("No open positions to close")
            return
        
        # v4.9.0: Delegate to Phase 4 if available
        if self.orchestrator and hasattr(self.orchestrator, 'phase4'):
            phase4 = self.orchestrator.phase4
            if phase4 and hasattr(phase4, '_execute_exit'):
                logger.info(f"🔄 Delegating close_all_positions to Phase 4 (reason: {reason})")
                
                closed_count = 0
                failed_count = 0
                
                for symbol in list(self.positions.keys()):
                    try:
                        success = phase4._execute_exit(symbol, reason)
                        if success:
                            closed_count += 1
                        else:
                            failed_count += 1
                    except Exception as e:
                        failed_count += 1
                        logger.error(f"❌ Failed to close {symbol}: {e}")
                
                logger.info(f"✅ Close complete via Phase 4: {closed_count} closed, {failed_count} failed")
                
                if failed_count > 0 and self.telegram:
                    self.telegram.send_message(
                        f"⚠️ CLOSE ALL INCOMPLETE\n\n"
                        f"Closed: {closed_count}\n"
                        f"Failed: {failed_count}\n\n"
                        f"Check broker for stuck positions!"
                    )
                return
        
        # Fallback: Log error if Phase 4 not available
        logger.error("❌ Phase 4 not available for close_all_positions!")
        logger.error("   SELL order execution has moved to Phase 4 in v4.9.0")
        logger.error("   Manual intervention may be required!")
        
        if self.telegram:
            self.telegram.send_message(
                f"🚨 CRITICAL: Cannot close positions!\n\n"
                f"Phase 4 not available.\n"
                f"MANUAL INTERVENTION REQUIRED!\n"
                f"Positions: {list(self.positions.keys())}"
            )
    
    # ═══════════════════════════════════════════════════════════════════════════
    # v4.9.0: _close_position() REMOVED - Moved to Phase 4
    # ═══════════════════════════════════════════════════════════════════════════
    # The SELL order execution logic has been moved to Phase 4's _place_sell_order().
    # Phase 3 is now ENTRY-ONLY (BUY orders and GTT placement).
    # Phase 4 handles all exit decisions and SELL order execution.
    #
    # Removed methods:
    # - _close_position() (~275 lines) → Phase 4._place_sell_order()
    # - _exit_position_by_symbol() → Phase 4._execute_exit()
    # - _partial_exit() → Phase 4._execute_partial_exit()
    # - check_position_exits() → Phase 4.run_monitoring_cycle()
    # - check_manual_stops() → Phase 4 monitoring
    # ═══════════════════════════════════════════════════════════════════════════
    
    
    def _save_position(self, position: dict):
        """Save position to positions.json"""
        all_positions = load_json(self.config.POSITIONS_FILE) or []
        
        if not isinstance(all_positions, list):
            all_positions = [all_positions]
        
        # Update or append
        found = False
        for i, p in enumerate(all_positions):
            if p['symbol'] == position['symbol'] and p.get('entry_time') == position.get('entry_time'):
                all_positions[i] = position
                found = True
                break
        
        if not found:
            all_positions.append(position)
        
        save_json(self.config.POSITIONS_FILE, all_positions)
    
    
    def _load_positions(self):
        """
        Load open positions from file and reconcile with broker.
        
        v4.5.2: Added broker reconciliation to detect orphan/ghost positions.
        """
        data = load_json(self.config.POSITIONS_FILE)
        
        if not data:
            # No saved positions - still need to check broker
            logger.info("No saved positions found in JSON")
        else:
            if not isinstance(data, list):
                data = [data]
            
            for position in data:
                # v4.5.2: Accept OPEN and EXIT_IN_PROGRESS
                if position.get('status') in [PositionState.OPEN, PositionState.EXIT_IN_PROGRESS]:
                    self.positions[position['symbol']] = position
                    self.capital_used += position.get('entry_value', 0)
                    logger.info(f"📂 Loaded position: {position['symbol']} ({position.get('status')})")
        
        # ═══════════════════════════════════════════════════════════════
        # v4.5.2 FIX: Reconcile with broker to catch orphan positions
        # ═══════════════════════════════════════════════════════════════
        self._reconcile_with_broker()
    
    
    def _reconcile_with_broker(self):
        """
        v4.5.2: Compare JSON positions with broker positions to detect mismatches.
        
        Detects:
        - ORPHAN positions: At broker but NOT in JSON (crash after fill, before save)
        - GHOST positions: In JSON but NOT at broker (position closed externally)
        
        This is a CRITICAL safety measure for recovery after crashes!
        """
        try:
            logger.info("🔄 Reconciling positions with broker...")
            
            # Get actual positions from Zerodha
            broker_positions = self.kite.positions()
            day_positions = broker_positions.get('day', [])
            net_positions = broker_positions.get('net', [])
            
            # Build set of symbols with open positions at broker
            broker_symbols = set()
            for pos in day_positions + net_positions:
                if pos.get('quantity', 0) > 0 and pos.get('exchange') == 'NSE':
                    symbol = pos.get('tradingsymbol')
                    if symbol:
                        broker_symbols.add(symbol)
            
            # Build set of symbols in our JSON tracking
            json_symbols = set(self.positions.keys())
            
            logger.info(f"   Broker positions: {broker_symbols or 'None'}")
            logger.info(f"   JSON positions: {json_symbols or 'None'}")
            
            # ═══════════════════════════════════════════════════════════════
            # DETECT ORPHAN POSITIONS (at broker, not in JSON)
            # ═══════════════════════════════════════════════════════════════
            orphan_symbols = broker_symbols - json_symbols
            
            if orphan_symbols:
                logger.critical(f"🚨 ORPHAN POSITIONS DETECTED: {orphan_symbols}")
                logger.critical("   These positions exist at broker but NOT in JSON!")
                logger.critical("   Possible cause: Crash after fill, before JSON save")
                
                # Send CRITICAL alert
                if self.telegram:
                    self.telegram.send_message(
                        f"🚨 CRITICAL: ORPHAN POSITIONS DETECTED!\n\n"
                        f"Symbols: {list(orphan_symbols)}\n\n"
                        f"These positions exist at Zerodha but are NOT tracked.\n"
                        f"⚠️ MANUAL ACTION REQUIRED!\n\n"
                        f"Options:\n"
                        f"1. Add to positions.json manually\n"
                        f"2. Close at broker manually\n"
                        f"3. System will NOT manage these until resolved"
                    )
                
                # Add orphan positions to tracking with WARNING status
                for symbol in orphan_symbols:
                    # Find position data from broker
                    for pos in day_positions + net_positions:
                        if pos.get('tradingsymbol') == symbol and pos.get('quantity', 0) > 0:
                            orphan_position = {
                                'symbol': symbol,
                                'quantity': pos.get('quantity'),
                                'entry_price': pos.get('average_price', 0),
                                'entry_value': pos.get('average_price', 0) * pos.get('quantity', 0),
                                'entry_time': datetime.now().isoformat(),
                                'target_price': pos.get('average_price', 0) * 1.03,  # Default +3%
                                'stop_price': pos.get('average_price', 0) * 0.98,    # Default -2%
                                'status': PositionState.OPEN,
                                'gtt_protected': False,  # No GTT for orphan
                                'orphan_recovered': True,  # Mark as recovered orphan
                                'product': pos.get('product', self.config.PRODUCT_TYPE)
                            }
                            # v4.9.0: Use helper method for consistent position tracking
                            self._set_position(symbol, orphan_position)
                            self.capital_used += orphan_position['entry_value']
                            self._save_position(orphan_position)
                            logger.warning(f"⚠️ Added orphan position to tracking: {symbol}")
                            break
            
            # ═══════════════════════════════════════════════════════════════
            # DETECT GHOST POSITIONS (in JSON, not at broker)
            # ═══════════════════════════════════════════════════════════════
            ghost_symbols = json_symbols - broker_symbols
            
            if ghost_symbols:
                logger.warning(f"👻 GHOST POSITIONS DETECTED: {ghost_symbols}")
                logger.warning("   These positions are in JSON but NOT at broker!")
                logger.warning("   Possible cause: Position closed externally (GTT triggered, manual)")
                
                # Send warning alert
                if self.telegram:
                    self.telegram.send_message(
                        f"👻 WARNING: GHOST POSITIONS DETECTED!\n\n"
                        f"Symbols: {list(ghost_symbols)}\n\n"
                        f"These are tracked in JSON but don't exist at Zerodha.\n"
                        f"Likely closed by GTT trigger or manually.\n\n"
                        f"Removing from tracking..."
                    )
                
                # Remove ghost positions from tracking
                for symbol in ghost_symbols:
                    if self._position_exists(symbol):
                        position = self.positions.get(symbol, {})
                        self.capital_used -= position.get('entry_value', 0)
                        # v4.9.0: Use helper method for consistent deletion
                        self._delete_position(symbol, "GHOST_REMOVED", 0)
                        logger.warning(f"🗑️ Removed ghost position: {symbol}")
            
            # Summary
            if not orphan_symbols and not ghost_symbols:
                logger.info("✅ Reconciliation complete: JSON matches broker")
            else:
                logger.warning(f"⚠️ Reconciliation complete: {len(orphan_symbols)} orphans, {len(ghost_symbols)} ghosts")
                
        except Exception as e:
            logger.error(f"❌ Broker reconciliation failed: {e}")
            logger.error("   Continuing with JSON-only positions (may be stale)")
            logger.error(traceback.format_exc())
    
    
    def _check_daily_loss_limit(self) -> bool:
        """
        Circuit breaker: Check if daily loss limit exceeded.
        
        Prevents runaway losses by stopping trading when daily loss hits limit.
        This is a CRITICAL safety measure!
        
        Returns:
            True if safe to trade, False if limit exceeded
        """
        # Check if MAX_DAILY_LOSS is configured
        if not hasattr(self.config, 'MAX_DAILY_LOSS'):
            # No limit configured - allow trading
            return True
        
        max_loss = self.config.MAX_DAILY_LOSS
        
        try:
            # Load today's trades
            trades_data = load_json(self.config.TRADES_FILE)
            
            if not trades_data:
                # No trades yet - safe to trade
                return True
            
            if not isinstance(trades_data, list):
                trades_data = [trades_data]
            
            # Filter today's trades
            today = datetime.now().date()
            today_trades = []
            
            for trade in trades_data:
                try:
                    entry_time = datetime.fromisoformat(trade.get('entry_time', ''))
                    if entry_time.date() == today:
                        today_trades.append(trade)
                except:
                    logger.warning(f"⚠️ Circuit breaker: Unparseable trade date, skipping: {trade.get('symbol', '?')} entry_time={trade.get('entry_time', 'MISSING')}")
                    continue
            
            if not today_trades:
                # No trades today - safe to trade
                return True
            
            # Calculate total P&L for today
            total_pnl = sum(t.get('pnl', 0) for t in today_trades)
            
            # Check if loss exceeds limit
            if total_pnl < -max_loss:
                logger.error("=" * 80)
                logger.error("⛔ CIRCUIT BREAKER TRIGGERED")
                logger.error("=" * 80)
                logger.error(f"Daily loss limit exceeded: ₹{abs(total_pnl):.2f}")
                logger.error(f"Maximum allowed loss: ₹{max_loss:.2f}")
                logger.error(f"Number of trades today: {len(today_trades)}")
                logger.error("")
                logger.error("🛑 TRADING HALTED FOR TODAY")
                logger.error("=" * 80)
                
                # Send Telegram alert
                if self.telegram:
                    self.telegram.send_message(
                        f"⛔ CIRCUIT BREAKER TRIGGERED\n\n"
                        f"Daily loss limit exceeded!\n\n"
                        f"Current loss: ₹{abs(total_pnl):.2f}\n"
                        f"Limit: ₹{max_loss:.2f}\n"
                        f"Trades today: {len(today_trades)}\n\n"
                        f"🛑 Trading halted for today\n"
                        f"System will reset tomorrow"
                    )
                
                return False
            
            # Within limit - log status
            remaining = max_loss + total_pnl  # How much more can we lose
            logger.info(f"💰 Daily P&L: ₹{total_pnl:.2f} (Limit: ₹{max_loss:.2f}, Remaining: ₹{remaining:.2f})")
            
            return True
            
        except Exception as e:
            logger.error(f"Error checking daily loss limit: {e}")
            # On error, allow trading (fail-safe)
            return True
    
    
    def _log_order(self, order: dict):

        """Log order to orders.json"""
        append_to_json(self.config.ORDERS_FILE, order)
    
    
    def _log_trade(self, trade: dict):
        """Log completed trade to trades.json"""
        append_to_json(self.config.TRADES_FILE, trade)
    
    

    # ═══════════════════════════════════════════════════════════════════════════
    # GTT ORDER METHODS (Added for Phase 4 Integration)
    # ═══════════════════════════════════════════════════════════════════════════
    
    def _place_gtt_orders(self, symbol: str, quantity: int,
                          stop_price: float, target_price: float,
                          current_price: float,
                          pdl_tag: str = "", pdh_tag: str = "") -> Dict:
        """
        Place GTT stop loss and target orders after entry.
        
        Called immediately after BUY order is filled.
        These GTT orders act as safety net while Phase 4 monitors.
        
        Args:
            symbol: Stock symbol
            quantity: Number of shares
            stop_price: Stop loss trigger price
            target_price: Target profit trigger price
            current_price: Current/entry price
            
        Returns:
            {'stop_id': int or None, 'target_id': int or None}
        """
        gtt_ids = {'stop_id': None, 'target_id': None}
        
        # Check if GTT is enabled
        if not getattr(self.config, 'ENABLE_GTT_ORDERS', True):
            logger.info(f"GTT orders disabled - skipping for {symbol}")
            return gtt_ids
        
        try:
            # GTT STOP LOSS ORDER
            try:
                gtt_stop = self.kite.place_gtt(
                    trigger_type=self.kite.GTT_TYPE_SINGLE,
                    tradingsymbol=symbol,
                    exchange="NSE",
                    trigger_values=[stop_price],
                    last_price=current_price,
                    orders=[{
                        "transaction_type": self.kite.TRANSACTION_TYPE_SELL,
                        "quantity": quantity,
                        "price": stop_price,
                        "order_type": self.kite.ORDER_TYPE_MARKET,
                        "product": self.config.PRODUCT_TYPE  # v4.7.2 FIX: Required by Kite API!
                    }]
                )
                gtt_ids['stop_id'] = gtt_stop.get('trigger_id')
                logger.info(f"✅ GTT Stop placed: {symbol} @ ₹{stop_price:.2f} (ID: {gtt_ids['stop_id']})")
                
            except Exception as e:
                logger.error(f"❌ GTT Stop failed for {symbol}: {e}")
            
            # GTT TARGET ORDER
            try:
                gtt_target = self.kite.place_gtt(
                    trigger_type=self.kite.GTT_TYPE_SINGLE,
                    tradingsymbol=symbol,
                    exchange="NSE",
                    trigger_values=[target_price],
                    last_price=current_price,
                    orders=[{
                        "transaction_type": self.kite.TRANSACTION_TYPE_SELL,
                        "quantity": quantity,
                        "price": target_price,
                        "order_type": self.kite.ORDER_TYPE_LIMIT,
                        "product": self.config.PRODUCT_TYPE  # v4.7.2 FIX: Required by Kite API!
                    }]
                )
                gtt_ids['target_id'] = gtt_target.get('trigger_id')
                logger.info(f"✅ GTT Target placed: {symbol} @ ₹{target_price:.2f} (ID: {gtt_ids['target_id']})")
                
            except Exception as e:
                logger.error(f"❌ GTT Target failed for {symbol}: {e}")
            
            # Notify via Telegram
            if self.telegram and (gtt_ids['stop_id'] or gtt_ids['target_id']):
                self.telegram.send_message(
                    f"🎯 GTT ORDERS PLACED: {symbol}\n\n"
                    f"Stop: ₹{stop_price:.2f}{pdl_tag}\n"
                    f"Target: ₹{target_price:.2f}{pdh_tag}\n"
                    f"Qty: {quantity}"
                )
            
            return gtt_ids
            
        except Exception as e:
            logger.error(f"GTT placement failed for {symbol}: {e}")
            return gtt_ids

    def modify_gtt_stop(self, trigger_id: int, symbol: str, 
                        new_stop_price: float, quantity: int,
                        current_price: float = None) -> bool:
        """
        Modify GTT stop loss price.
        
        Called by Phase 4 when trailing stop moves up or widening for overnight.
        """
        try:
            if not current_price:
                try:
                    quote = self.kite.quote([f"NSE:{symbol}"])
                    current_price = quote[f"NSE:{symbol}"]['last_price']
                except:
                    current_price = new_stop_price * 1.02
                    logger.warning(f"⚠️ {symbol}: Quote fetch failed for GTT stop modify, using fallback price ₹{current_price:.2f} (stop×1.02)")
            
            self.kite.modify_gtt(
                trigger_id=trigger_id,
                trigger_type=self.kite.GTT_TYPE_SINGLE,
                tradingsymbol=symbol,
                exchange="NSE",
                trigger_values=[new_stop_price],
                last_price=current_price,
                orders=[{
                    "transaction_type": self.kite.TRANSACTION_TYPE_SELL,
                    "quantity": quantity,
                    "price": new_stop_price,
                    "order_type": self.kite.ORDER_TYPE_MARKET
                }]
            )
            
            logger.info(f"✅ GTT Stop modified: {symbol} → ₹{new_stop_price:.2f}")
            return True
            
        except Exception as e:
            logger.error(f"❌ GTT Stop modify failed for {symbol}: {e}")
            return False
    
    def modify_gtt_target(self, trigger_id: int, symbol: str,
                          new_target_price: float, quantity: int,
                          current_price: float = None) -> bool:
        """
        Modify GTT target price. May need cancel and replace if modify fails.
        """
        try:
            if not current_price:
                try:
                    quote = self.kite.quote([f"NSE:{symbol}"])
                    current_price = quote[f"NSE:{symbol}"]['last_price']
                except:
                    current_price = new_target_price * 0.98
                    logger.warning(f"⚠️ {symbol}: Quote fetch failed for GTT target modify, using fallback price ₹{current_price:.2f} (target×0.98)")
            
            self.kite.modify_gtt(
                trigger_id=trigger_id,
                trigger_type=self.kite.GTT_TYPE_SINGLE,
                tradingsymbol=symbol,
                exchange="NSE",
                trigger_values=[new_target_price],
                last_price=current_price,
                orders=[{
                    "transaction_type": self.kite.TRANSACTION_TYPE_SELL,
                    "quantity": quantity,
                    "price": new_target_price,
                    "order_type": self.kite.ORDER_TYPE_LIMIT
                }]
            )
            
            logger.info(f"✅ GTT Target modified: {symbol} → ₹{new_target_price:.2f}")
            return True
            
        except Exception as e:
            logger.error(f"❌ GTT Target modify failed: {e}")
            
            # Try cancel and replace
            try:
                logger.info(f"   Attempting cancel and replace...")
                self.kite.delete_gtt(trigger_id)
                
                gtt_new = self.kite.place_gtt(
                    trigger_type=self.kite.GTT_TYPE_SINGLE,
                    tradingsymbol=symbol,
                    exchange="NSE",
                    trigger_values=[new_target_price],
                    last_price=current_price,
                    orders=[{
                        "transaction_type": self.kite.TRANSACTION_TYPE_SELL,
                        "quantity": quantity,
                        "price": new_target_price,
                        "order_type": self.kite.ORDER_TYPE_LIMIT
                    }]
                )
                
                logger.info(f"✅ GTT Target replaced: {symbol} → ₹{new_target_price:.2f}")
                return True
                
            except Exception as e2:
                logger.error(f"❌ GTT Target replace also failed: {e2}")
                return False

    def cancel_gtt(self, trigger_id: int) -> bool:
        """Cancel a single GTT order."""
        try:
            self.kite.delete_gtt(trigger_id)
            logger.info(f"✅ GTT {trigger_id} cancelled")
            return True
        except Exception as e:
            logger.error(f"❌ GTT cancel failed ({trigger_id}): {e}")
            return False
    
    def cancel_all_gtt_for_position(self, position: Dict) -> bool:
        """Cancel all GTT orders for a position before manual exit."""
        success = True
        
        if position.get('gtt_stop_id'):
            if not self.cancel_gtt(position['gtt_stop_id']):
                success = False
            position['gtt_stop_id'] = None
        
        if position.get('gtt_target_id'):
            if not self.cancel_gtt(position['gtt_target_id']):
                success = False
            position['gtt_target_id'] = None
        
        position['gtt_active'] = False
        return success

    def check_gtt_status(self, trigger_id: int) -> str:
        """Check GTT order status: 'active', 'triggered', 'cancelled', etc."""
        try:
            gtts = self.kite.get_gtts()
            for gtt in gtts:
                if gtt['id'] == trigger_id:
                    return gtt['status']
            return 'not_found'
        except Exception as e:
            logger.error(f"GTT status check failed: {e}")
            return 'error'
    
    def check_all_gtt_triggered(self) -> List[Dict]:
        """Check if any GTT orders have triggered (called by Phase 4)."""
        triggered = []
        
        try:
            gtts = self.kite.get_gtts()
            for gtt in gtts:
                if gtt['status'] == 'triggered':
                    triggered.append({
                        'trigger_id': gtt['id'],
                        'symbol': gtt['tradingsymbol'],
                        'trigger_price': gtt['trigger_values'][0] if gtt.get('trigger_values') else 0,
                        'triggered_at': gtt.get('updated_at')
                    })
            
            if triggered:
                logger.info(f"🎯 Found {len(triggered)} triggered GTT orders")
                
        except Exception as e:
            logger.error(f"GTT triggered check failed: {e}")
        
        return triggered


    def export_to_excel(self, output_file: str = None):
        """Export trades to Excel (same as before)"""
        if not EXCEL_AVAILABLE:
            logger.warning("pandas not installed - Excel export skipped")
            return False
        
        if output_file is None:
            output_file = "data/phase3_outputs/trades_analysis.xlsx"
        
        try:
            trades_data = load_json(self.config.TRADES_FILE)
            
            if not trades_data:
                logger.warning("No trades found")
                return False
            
            if not isinstance(trades_data, list):
                trades_data = [trades_data]
            
            # Create DataFrame
            df = pd.DataFrame(trades_data)
            
            if len(df) > 0:
                df['entry_time'] = pd.to_datetime(df['entry_time'])
                df['exit_time'] = pd.to_datetime(df['exit_time'])
                df['date'] = df['entry_time'].dt.date
                df['result'] = df['pnl'].apply(lambda x: 'WIN' if x > 0 else 'LOSS')
            
            # Create Excel with 4 sheets
            with pd.ExcelWriter(output_file, engine='openpyxl') as writer:
                # Sheet 1: Trades
                df_export = df[['date', 'symbol', 'quantity', 'entry_price', 
                               'exit_price', 'pnl', 'pnl_pct', 'result', 
                               'exit_reason', 'duration']]
                df_export.to_excel(writer, sheet_name='Trades', index=False)
                
                # Sheet 2: Summary
                if len(df) > 0:
                    wins = df[df['pnl'] > 0]
                    losses = df[df['pnl'] < 0]
                    
                    summary = {
                        'Metric': ['Total Trades', 'Wins', 'Losses', 'Win Rate %', '', 
                                  'Total P&L', 'Avg Win', 'Avg Loss', 'Profit Factor'],
                        'Value': [len(df), len(wins), len(losses), 
                                 round(len(wins)/len(df)*100, 2) if len(df) > 0 else 0, '',
                                 round(df['pnl'].sum(), 2),
                                 round(wins['pnl'].mean(), 2) if len(wins) > 0 else 0,
                                 round(losses['pnl'].mean(), 2) if len(losses) > 0 else 0,
                                 round(wins['pnl'].sum() / abs(losses['pnl'].sum()), 2) 
                                 if len(losses) > 0 and losses['pnl'].sum() != 0 else 0]
                    }
                    
                    pd.DataFrame(summary).to_excel(writer, sheet_name='Summary', index=False)
                
                # Sheet 3: By Stock
                if len(df) > 0:
                    by_stock = df.groupby('symbol').agg({
                        'pnl': ['sum', 'count', 'mean']
                    }).round(2)
                    by_stock.columns = ['Total P&L', 'Trades', 'Avg P&L']
                    by_stock.reset_index().to_excel(writer, sheet_name='By Stock', index=False)
                
                # Sheet 4: By Exit Reason
                if len(df) > 0:
                    by_reason = df.groupby('exit_reason').agg({
                        'pnl': ['sum', 'count', 'mean']
                    }).round(2)
                    by_reason.columns = ['Total P&L', 'Trades', 'Avg P&L']
                    by_reason.reset_index().to_excel(writer, sheet_name='By Exit Reason', index=False)
            
            logger.info(f"✅ Excel export complete: {output_file}")
            
            self.telegram.send_message(
                f"📊 EXCEL EXPORT COMPLETE\n\n"
                f"Trades: {len(df)}\n"
                f"Win Rate: {len(wins)/len(df)*100:.1f}%\n"
                f"Total P&L: ₹{df['pnl'].sum():,.0f}"
            )
            
            return True
            
        except Exception as e:
            logger.error(f"Excel export failed: {e}")
            return False
    
    # ═══════════════════════════════════════════════════════════════════════════
    # v4.7.2 NEW: BROKER POSITION ADOPTION
    # ═══════════════════════════════════════════════════════════════════════════
    
    def adopt_position_from_broker(self, symbol: str, quantity: int, avg_price: float,
                                    product: str = None, last_price: float = None):
        """
        Adopt a position discovered at broker into Phase 3 monitoring.
        
        Called by orchestrator.broker_sync_positions() when positions exist
        at broker but not in our state (e.g., after restart, crash recovery).
        
        v4.7.2: Enables "cold start reconciliation" - system can restart
        while positions are open and automatically resume monitoring.
        
        Args:
            symbol: Stock symbol
            quantity: Number of shares
            avg_price: Average entry price from broker
            product: Product type (MIS/CNC) - defaults to config
            last_price: Current market price (for initial P&L calc)
        """
        if symbol in self.positions:
            logger.warning(f"   {symbol} already in positions - skipping adoption")
            return
        
        product = product or self.config.PRODUCT_TYPE
        last_price = last_price or avg_price
        entry_value = avg_price * quantity
        
        # Calculate default targets (conservative since we don't know original intent)
        target_pct = getattr(self.config, 'PROFIT_TARGET_PCT', 3.0)
        stop_pct = getattr(self.config, 'STOP_LOSS_PCT', 2.0)
        
        adopted_position = {
            'symbol': symbol,
            'quantity': quantity,
            'entry_price': avg_price,
            'entry_value': entry_value,
            'entry_time': datetime.now().isoformat(),
            'target_price': avg_price * (1 + target_pct / 100),
            'stop_price': avg_price * (1 - stop_pct / 100),
            'target_pct': target_pct,
            'stop_pct': stop_pct,
            'max_price': last_price,  # Initialize max tracking
            'status': PositionState.OPEN,
            'product': product,
            'exchange': 'NSE',
            
            # Mark as adopted for audit trail
            'adopted': True,
            'adopted_at': datetime.now().isoformat(),
            'adoption_source': 'BROKER_SYNC',
            
            # Safety flags
            'gtt_protected': False,  # No GTT - need to place
            'gtt_stop_id': None,
            'gtt_target_id': None,
            
            # Position tracking
            'max_profit_pct': 0.0,
            'max_drawdown_pct': 0.0,
            
            # P&L tracking
            'current_price': last_price,
            'unrealized_pnl': (last_price - avg_price) * quantity,
        }
        
        # v4.9.0: Use helper method for consistent position tracking
        self._set_position(symbol, adopted_position)
        self.capital_used += entry_value
        
        # Save to file
        self._save_position(adopted_position)
        
        logger.info(f"📡 ADOPTED: {symbol} - {quantity} shares @ ₹{avg_price:.2f}")
        logger.info(f"   Target: ₹{adopted_position['target_price']:.2f} (+{target_pct}%)")
        logger.info(f"   Stop: ₹{adopted_position['stop_price']:.2f} (-{stop_pct}%)")
        logger.info(f"   ⚠️ GTT NOT placed - position unprotected until next cycle")
        
        # Try to place GTT stop for safety
        try:
            self._place_gtt_stop_for_adopted(symbol, adopted_position)
        except Exception as e:
            logger.warning(f"   ⚠️ Failed to place GTT for adopted position: {e}")
            # Add to manual stop tracking
            if hasattr(self, 'manual_stop_positions'):
                self.manual_stop_positions[symbol] = {
                    'position': adopted_position,
                    'unprotected_since': datetime.now()
                }
    
    def _place_gtt_stop_for_adopted(self, symbol: str, position: dict):
        """Place GTT stop-loss for an adopted position."""
        try:
            stop_price = position['stop_price']
            quantity = position['quantity']
            current_price = position.get('current_price', position['entry_price'])
            
            gtt_response = self.kite.place_gtt(
                trigger_type=self.kite.GTT_TYPE_SINGLE,
                tradingsymbol=symbol,
                exchange="NSE",
                trigger_values=[stop_price],
                last_price=current_price,
                orders=[{
                    "transaction_type": self.kite.TRANSACTION_TYPE_SELL,
                    "quantity": quantity,
                    "price": stop_price,
                    "order_type": self.kite.ORDER_TYPE_LIMIT,
                    "product": self.config.PRODUCT_TYPE  # v4.7.2 FIX: Required by Kite API!
                }]
            )
            
            trigger_id = gtt_response.get('trigger_id')
            if trigger_id:
                position['gtt_stop_id'] = trigger_id
                position['gtt_protected'] = True
                self._save_position(position)
                logger.info(f"   ✅ GTT Stop placed for adopted {symbol}: ID={trigger_id}")
                
                if self.telegram:
                    self.telegram.send_message(
                        f"🛡️ GTT PROTECTION ADDED\n\n"
                        f"Symbol: {symbol} (adopted)\n"
                        f"Stop: ₹{stop_price:.2f}\n"
                        f"GTT ID: {trigger_id}"
                    )
            
        except Exception as e:
            logger.error(f"   ❌ GTT placement failed for {symbol}: {e}")


# ============================================================================
# STANDALONE EXECUTION (NOT RECOMMENDED)
# ============================================================================

if __name__ == "__main__":
    print("=" * 80)
    print("⚠️  WARNING: Standalone execution not recommended")
    print("   Run via main file for proper integration")
    print("=" * 80)