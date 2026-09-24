"""
MAIN_ORCHESTRATOR.PY - AUTONOMOUS TRADING SYSTEM ENTRY POINT v5.0.0
====================================================================

v5.0.0: MISSION CONTROL ARCHITECTURE
─────────────────────────────────────
- Spacecraft-style boot sequence (S1-S9)
- SQLite flight recorder (mission_control.db)
- REDUCED_MODE with auto-recovery
- ChatGPT gets yesterday's memory from database
- Structured startup → READY / REDUCED_MODE / ERROR
- End-of-day shutdown with mandatory ChatGPT debrief

v2.5.0: SQLite Database & Console Capture (retained)
v2.4.0: Immediate Broker Sync After Login (now in S3)
v2.3.0: Windows Sleep Prevention (retained)

Author: Dheebanraj
Version: 5.0.0
Date: 2026-02-06
"""

import os
import sys
import time
import logging
from logging.handlers import RotatingFileHandler
import pyotp
import traceback
from datetime import datetime

# ═══════════════════════════════════════════════════════════════════════════════
# WINDOWS UNICODE FIX - MUST BE BEFORE ANY LOGGING / HEAVY IMPORTS!
# ═══════════════════════════════════════════════════════════════════════════════
# Moved ABOVE system-module imports so that orchestrator.py's StreamHandler
# is created with the already-reconfigured stdout (fixes pipe-buffering issue
# when the GUI launches this script as a subprocess).

if sys.platform == 'win32':
    os.environ['PYTHONIOENCODING'] = 'utf-8'
    try:
        if hasattr(sys.stdout, 'reconfigure'):
            sys.stdout.reconfigure(encoding='utf-8', line_buffering=True)
        if hasattr(sys.stderr, 'reconfigure'):
            sys.stderr.reconfigure(encoding='utf-8', line_buffering=True)
    except Exception:
        pass

# ═══════════════════════════════════════════════════════════════════════════════
# LOGGING CONFIGURATION — MUST BE BEFORE ALL SYSTEM MODULE IMPORTS
# Root logger handlers must exist before orchestrator.py is imported,
# otherwise orchestrator.py's basicConfig guard fires first and adds its own
# StreamHandler, resulting in every log line printing twice.
# ═══════════════════════════════════════════════════════════════════════════════

os.makedirs('logs', exist_ok=True)
os.makedirs('data', exist_ok=True)

# Main rotating log
file_handler = RotatingFileHandler(
    'logs/trading.log',
    maxBytes=10 * 1024 * 1024,
    backupCount=10,
    encoding='utf-8'
)

# Daily log
daily_handler = logging.FileHandler(
    f'logs/trading_{datetime.now().strftime("%Y%m%d")}.log',
    encoding='utf-8'
)
daily_handler.setLevel(logging.INFO)
daily_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))

file_handler.setLevel(logging.INFO)
file_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))

# Console handler (uses line-buffered stdout set up above)
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))

# Configure root logger — single source of truth for all handlers.
# Guard against duplicate handler types (not just object identity) so that
# re-imports or future refactors cannot sneak in a second StreamHandler.
root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)
existing_handler_types = [type(h) for h in root_logger.handlers]
for h in [file_handler, daily_handler, console_handler]:
    if h not in root_logger.handlers:
        root_logger.addHandler(h)

logger = logging.getLogger("MainOrchestrator")

# ═══════════════════════════════════════════════════════════════════════════════
# SYSTEM MODULE IMPORTS — logging is fully configured before these run
# ═══════════════════════════════════════════════════════════════════════════════

from kiteconnect import KiteConnect

# Selenium imports
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

# Import system modules
from orchestrator import TradingOrchestrator
from config import Config
from telegram_notifier import TelegramNotifier
from keep_awake import KeepAwake
import json

# ═══════════════════════════════════════════════════════════════════════════════
# v5.0.0: MISSION CONTROL IMPORTS
# ═══════════════════════════════════════════════════════════════════════════════

try:
    from startup_controller import StartupController, SystemState, StartupResult
    STARTUP_CONTROLLER_AVAILABLE = True
except ImportError:
    STARTUP_CONTROLLER_AVAILABLE = False
    StartupController = None
    SystemState = None

try:
    from mission_db import get_mission_db, MissionDB
    MISSION_DB_AVAILABLE = True
except ImportError:
    MISSION_DB_AVAILABLE = False
    get_mission_db = None

# ═══════════════════════════════════════════════════════════════════════════════
# v2.5.0: UNIFIED DATA MANAGER IMPORT (retained for backward compat)
# ═══════════════════════════════════════════════════════════════════════════════

try:
    from unified_data_manager import get_db, UnifiedDataManager, DatabaseLogHandler
    DATABASE_AVAILABLE = True
except ImportError:
    DATABASE_AVAILABLE = False
    get_db = None
    UnifiedDataManager = None
    DatabaseLogHandler = None


# ═══════════════════════════════════════════════════════════════════════════════
# v2.5.0: DATABASE LOG HANDLER (retained)
# ═══════════════════════════════════════════════════════════════════════════════

_db_handler_added = False

def setup_database_logging():
    """Setup database logging to capture console output."""
    global _db_handler_added
    
    if not DATABASE_AVAILABLE or _db_handler_added:
        return
    
    try:
        db = get_db()
        if db and DatabaseLogHandler:
            db_handler = DatabaseLogHandler(db)
            db_handler.setLevel(logging.INFO)
            db_handler.setFormatter(logging.Formatter('%(message)s'))
            
            logging.getLogger().addHandler(db_handler)
            _db_handler_added = True
            
            logger.info("✅ Database logging enabled - Console output captured!")
    except Exception as e:
        logger.warning(f"⚠️ Database logging not available: {e}")


# ═══════════════════════════════════════════════════════════════════════════════
# ZERODHA AUTO-LOGIN CLASS (unchanged from v2.5.0)
# ═══════════════════════════════════════════════════════════════════════════════

class ZerodhaAutoLogin:
    """
    Automated Zerodha Kite login using Selenium.
    
    Handles:
     Selenium browser automation
     TOTP generation (2FA)
     Request token extraction
     Access token generation
     Retry logic (3 attempts)
     Screenshot on failure for debugging
    """
    
    MAX_RETRIES = 3
    RETRY_DELAY = 5
    
    def __init__(self, api_key: str, api_secret: str, user_id: str, 
                 password: str, totp_secret: str):
        self.api_key = api_key
        self.api_secret = api_secret
        self.user_id = user_id
        self.password = password
        self.totp_secret = totp_secret
        self.driver = None
    
    def _save_debug_screenshot(self, stage: str):
        """Save screenshot for debugging login failures"""
        try:
            if self.driver:
                os.makedirs('logs/screenshots', exist_ok=True)
                filename = f"logs/screenshots/login_error_{stage}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
                self.driver.save_screenshot(filename)
                logger.error(f"📸 Screenshot saved: {filename}")
                
                html_file = filename.replace('.png', '.html')
                with open(html_file, 'w', encoding='utf-8') as f:
                    f.write(self.driver.page_source)
                logger.error(f"📄 Page source saved: {html_file}")
        except Exception as e:
            logger.error(f"Failed to save debug info: {e}")
    
    def login_and_get_token(self) -> str:
        """Perform automated login with retry logic."""
        for attempt in range(1, self.MAX_RETRIES + 1):
            logger.info(f"Login attempt {attempt}/{self.MAX_RETRIES}")
            
            token = self._attempt_login()
            
            if token:
                return token
            
            if attempt < self.MAX_RETRIES:
                logger.warning(f"Login failed, retrying in {self.RETRY_DELAY}s...")
                time.sleep(self.RETRY_DELAY)
        
        logger.error("All login attempts failed")
        return None
    
    def _attempt_login(self) -> str:
        """Single login attempt"""
        try:
            # Configure Chrome
            chrome_options = Options()
            chrome_options.add_argument('--headless')
            chrome_options.add_argument('--no-sandbox')
            chrome_options.add_argument('--disable-dev-shm-usage')
            chrome_options.add_argument('--disable-gpu')
            chrome_options.add_argument('--window-size=1920,1080')
            chrome_options.add_argument('--disable-extensions')
            chrome_options.add_argument('--disable-logging')
            chrome_options.add_argument('--log-level=3')
            
            # Initialize driver
            # Prefer the apt-installed driver (matches apt Chromium on the Pi);
            # webdriver-manager can fetch a newer driver than the installed browser.
            _system_driver = next((p for p in ('/usr/bin/chromedriver', '/usr/lib/chromium-browser/chromedriver')
                                   if os.path.exists(p)), None)
            service = Service(_system_driver or ChromeDriverManager().install())
            self.driver = webdriver.Chrome(service=service, options=chrome_options)
            
            # Navigate to login URL
            login_url = f"https://kite.zerodha.com/connect/login?v=3&api_key={self.api_key}"
            self.driver.get(login_url)
            
            # Wait for and fill user ID
            user_input = WebDriverWait(self.driver, 15).until(
                EC.presence_of_element_located((By.ID, "userid"))
            )
            user_input.send_keys(self.user_id)
            
            # Fill password
            pwd_input = self.driver.find_element(By.ID, "password")
            pwd_input.send_keys(self.password)
            
            # Click login
            login_btn = self.driver.find_element(By.XPATH, "//button[@type='submit']")
            login_btn.click()
            
            # Wait for TOTP field
            totp_input = WebDriverWait(self.driver, 15).until(
                EC.presence_of_element_located((By.XPATH, "//input[@type='number' or @type='text'][@inputmode='numeric' or contains(@class,'totp') or @label='External TOTP' or @label='Mobile App Code']"))
            )
            
            # Generate and enter TOTP
            totp = pyotp.TOTP(self.totp_secret)
            totp_code = totp.now()
            totp_input.send_keys(totp_code)
            
            # Wait for redirect with request token
            WebDriverWait(self.driver, 20).until(
                lambda d: "request_token=" in d.current_url
            )
            
            # Extract request token
            current_url = self.driver.current_url
            request_token = current_url.split("request_token=")[1].split("&")[0]
            
            logger.info("✅ Request token obtained")
            
            # Generate access token
            kite = KiteConnect(api_key=self.api_key)
            data = kite.generate_session(request_token, api_secret=self.api_secret)
            access_token = data["access_token"]
            
            logger.info("✅ Access token generated")
            
            return access_token
            
        except Exception as e:
            logger.error(f"Login error: {e}")
            self._save_debug_screenshot("exception")
            return None
            
        finally:
            if self.driver:
                try:
                    self.driver.quit()
                except:
                    pass


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN FUNCTION — v5.0.0 MISSION CONTROL
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    """
    Main entry point for Algo Beta v5.0.0.
    
    Flow:
    ─────
    1. Keep system awake (Windows)
    2. Initialize databases (algo_beta.db + mission_control.db)
    3. Load config, init Telegram
    4. Auto-login to Zerodha (Selenium)
    5. Run StartupController S1-S9 boot sequence
       → READY: Full trading
       → REDUCED_MODE: Monitor only, auto-recovery
       → ERROR: Halt
    6. Initialize orchestrator with startup result
    7. Run main event loop
    8. Shutdown: ChatGPT debrief + SQLite save + backup
    """
    
    telegram = None
    keep_awake = None
    orchestrator = None
    startup_controller = None
    startup_result = None
    
    try:
        # ═══════════════════════════════════════════════════════════════════
        # KEEP SYSTEM AWAKE
        # ═══════════════════════════════════════════════════════════════════
        # v1.0.1: keep_display_on=True — prevents Windows network throttling
        # When display sleeps, Windows may throttle background network traffic,
        # causing DNS resolution failures for api.kite.trade and api.anthropic.com.
        keep_awake = KeepAwake(keep_display_on=True)
        keep_awake.start()
        
        # ═══════════════════════════════════════════════════════════════════
        # INITIALIZE DATABASES
        # ═══════════════════════════════════════════════════════════════════
        
        # Legacy operational DB (algo_beta.db)
        if DATABASE_AVAILABLE:
            try:
                db = get_db()
                logger.info("📦 Operational DB initialized: data/algo_beta.db")
                setup_database_logging()
            except Exception as e:
                logger.warning(f"⚠️ Operational DB failed: {e} — continuing")
        
        # v5.0.0: Mission control DB (mission_control.db)
        if MISSION_DB_AVAILABLE:
            try:
                mission_db = get_mission_db()
                logger.info("📦 Mission DB initialized: data/mission_control.db")
            except Exception as e:
                logger.warning(f"⚠️ Mission DB failed: {e} — continuing")
        
        # ═══════════════════════════════════════════════════════════════════
        # INITIALIZATION BANNER
        # ═══════════════════════════════════════════════════════════════════
        
        logger.info("")
        logger.info("=" * 80)
        logger.info("🚀 ALGO BETA v5.0.0 — MISSION CONTROL ARCHITECTURE")
        logger.info("=" * 80)
        logger.info(f"   Date: {datetime.now().strftime('%Y-%m-%d %A')}")
        logger.info(f"   Time: {datetime.now().strftime('%H:%M:%S')}")
        logger.info("   Boot: Spacecraft-style S1-S9 sequence")
        logger.info("   State: BOOT → STARTUP → READY → RUNNING")
        logger.info("=" * 80)
        logger.info("")
        
        # Create output directories
        os.makedirs('logs', exist_ok=True)
        os.makedirs('data/phase1_outputs', exist_ok=True)
        os.makedirs('data/phase2_outputs', exist_ok=True)
        os.makedirs('data/phase3_outputs', exist_ok=True)
        
        # ═══════════════════════════════════════════════════════════════════
        # 1. LOAD CONFIGURATION
        # ═══════════════════════════════════════════════════════════════════
        
        logger.info("Loading configuration...")
        config = Config()
        logger.info("✅ Configuration loaded")
        logger.info(f"Mode: {'🔴 LIVE TRADING' if config.ENABLE_PHASE3 else '🟡 PAPER TRADING'}")
        
        config.log_config_safe()
        
        if not config.validate_config():
            logger.critical("❌ Configuration validation failed!")
            sys.exit(1)
        
        # ═══════════════════════════════════════════════════════════════════
        # 2. INITIALIZE TELEGRAM NOTIFIER
        # ═══════════════════════════════════════════════════════════════════
        
        logger.info("Initializing Telegram notifier...")
        telegram = TelegramNotifier(
            bot_token=config.TELEGRAM_BOT_TOKEN,
            chat_id=config.TELEGRAM_CHAT_ID
        )
        logger.info("✅ Telegram notifier initialized")
        
        # ═══════════════════════════════════════════════════════════════════
        # 3. AUTOMATED LOGIN TO ZERODHA
        # ═══════════════════════════════════════════════════════════════════
        
        logger.info("")
        logger.info("Initializing automated login...")
        
        login_handler = ZerodhaAutoLogin(
            api_key=config.ZERODHA_API_KEY,
            api_secret=config.ZERODHA_API_SECRET,
            user_id=config.ZERODHA_USER_ID,
            password=config.ZERODHA_PASSWORD,
            totp_secret=config.ZERODHA_TOTP_SECRET
        )
        
        access_token = login_handler.login_and_get_token()
        
        if not access_token:
            logger.error("=" * 80)
            logger.error("❌ CRITICAL: LOGIN FAILED")
            logger.error("=" * 80)
            
            if telegram:
                telegram.send_message(
                    "🚨 CRITICAL ERROR\n\n"
                    "Login failed!\n"
                    "Cannot obtain access token.\n\n"
                    "System halted."
                )
            
            # Log to mission_db
            if MISSION_DB_AVAILABLE:
                try:
                    mdb = get_mission_db()
                    mdb.ensure_today()
                    mdb.log_fault("KITE_LOGIN_FAIL", "CRITICAL",
                                  description="Selenium login failed after 3 attempts")
                    mdb.update_daily_state(
                        shutdown_type="ERROR",
                        system_state="ERROR"
                    )
                except:
                    pass
            
            sys.exit(1)
        
        # Initialize Kite
        logger.info("Initializing KiteConnect...")
        kite = KiteConnect(api_key=config.ZERODHA_API_KEY)
        kite.set_access_token(access_token)
        logger.info("✅ KiteConnect initialized")
        
        if telegram:
            telegram.send_message(
                "✅ LOGIN SUCCESSFUL\n\n"
                "Kite connection established\n"
                "Running boot sequence S1-S9..."
            )
        
        # ═══════════════════════════════════════════════════════════════════
        # 4. v5.0.0: RUN STARTUP CONTROLLER (S1-S9)
        # ═══════════════════════════════════════════════════════════════════
        
        if STARTUP_CONTROLLER_AVAILABLE:
            logger.info("")
            startup_controller = StartupController(config)
            startup_result = startup_controller.run_startup(
                kite=kite,
                telegram=telegram
            )
            
            # Handle startup outcome
            if startup_result.system_state == SystemState.ERROR:
                logger.error("🚨 STARTUP FAILED — System cannot proceed")
                logger.error(f"   Reason: {startup_result.reduced_mode_reason}")
                
                # Mission DB already updated by startup controller
                sys.exit(1)
            
            elif startup_result.system_state == SystemState.REDUCED_MODE:
                logger.warning("⚠️ REDUCED MODE — Monitor only, no new entries")
                logger.warning(f"   Reason: {startup_result.reduced_mode_reason}")
                logger.warning("   Auto-recovery will attempt every 5 minutes")
                # Continue to orchestrator — it will respect REDUCED_MODE
            
            elif startup_result.system_state == SystemState.READY:
                logger.info("✅ ALL SYSTEMS GO — READY for market")
            
            # Extract broker state for orchestrator compatibility
            broker_state = {
                'success': True,
                'check_time': datetime.now().isoformat(),
                'position_count': len(startup_result.broker_positions),
                'positions': startup_result.broker_positions,
                'capital_deployed': sum(
                    abs(p.get('quantity', 0) * p.get('avg_price', 0))
                    for p in startup_result.broker_positions
                ),
                'unrealized_pnl': sum(
                    p.get('pnl', 0) for p in startup_result.broker_positions
                ),
                'available_cash': startup_result.free_capital,
                'used_margin': 0,
                'exposure_warning': len(startup_result.broker_positions) > 0
            }
        
        else:
            # Fallback: run without startup controller (backward compat)
            logger.warning("⚠️ StartupController not available — using legacy startup")
            
            broker_state = _legacy_broker_check(kite, telegram)
            _legacy_pre_market(kite, config, telegram, broker_state)
        
        # ═══════════════════════════════════════════════════════════════════
        # 5. INITIALIZE ORCHESTRATOR
        # ═══════════════════════════════════════════════════════════════════
        
        logger.info("")
        logger.info("Initializing orchestrator...")
        orchestrator = TradingOrchestrator(
            kite=kite,
            config=config,
            telegram=telegram,
            initial_broker_state=broker_state
        )
        
        # v5.0.0: Pass startup result to orchestrator
        if startup_result and STARTUP_CONTROLLER_AVAILABLE:
            orchestrator._startup_result = startup_result
            orchestrator._startup_controller = startup_controller
            
            # Set system state flag
            if startup_result.system_state == SystemState.REDUCED_MODE:
                orchestrator._reduced_mode = True
                orchestrator._reduced_mode_reason = startup_result.reduced_mode_reason
                logger.warning(f"⚠️ Orchestrator starting in REDUCED_MODE")
            else:
                orchestrator._reduced_mode = False
        
        logger.info("✅ Orchestrator initialized")
        logger.info("")
        
        # ═══════════════════════════════════════════════════════════════════
        # 6. RUN MAIN EVENT LOOP
        # ═══════════════════════════════════════════════════════════════════
        
        logger.info("=" * 80)
        logger.info("STARTING MAIN EVENT LOOP")
        logger.info("=" * 80)
        logger.info("")
        
        if broker_state['position_count'] > 0:
            logger.info("📊 CURRENT STATE:")
            logger.info(f"   Open Positions: {broker_state['position_count']}")
            logger.info(f"   Capital Deployed: ₹{broker_state['capital_deployed']:,.0f}")
            logger.info(f"   Unrealized P&L: ₹{broker_state['unrealized_pnl']:,.0f}")
            logger.info("")
        
        if startup_result and STARTUP_CONTROLLER_AVAILABLE:
            state_emoji = "✅" if startup_result.system_state == SystemState.READY else "⚠️"
            logger.info(f"{state_emoji} System State: {startup_result.system_state.value}")
            logger.info(f"💰 Free Capital: ₹{startup_result.free_capital:,.0f}")
            logger.info(f"🎯 Max New Positions: {startup_result.max_new_positions}")
            logger.info(f"📈 Market Regime: {startup_result.market_regime}")
            logger.info("")
        
        logger.info("⏰ v5.0.0 Timeline:")
        logger.info("   09:15-09:22  Phase 5 gap scan (3 loops)")
        logger.info("   09:50+       Phase 1 stock scan")
        logger.info("   10:00+       Phase 2 entry monitoring")
        logger.info("   All day      Phase 4 portfolio management")
        logger.info("   12:00        Phase 5 mandatory exit")
        logger.info("   15:15        MIS cutoff")
        logger.info("   15:25        Market close")
        logger.info("   15:30        ChatGPT EOD debrief + shutdown")
        logger.info("")
        
        logger.info("🛡️ Safety:")
        logger.info(f"   Circuit Breaker: ₹{config.MAX_DAILY_LOSS} max daily loss")
        logger.info(f"   Capital Per Trade: ₹{config.BASE_CAPITAL_PER_TRADE:,}")
        logger.info("")
        
        logger.info("Press Ctrl+C to stop")
        logger.info("=" * 80)
        logger.info("")

        # v5.4.0: Send system startup notification via Telegram
        if telegram and hasattr(telegram, 'notify_system_startup'):
            try:
                mode = "LIVE" if config.ENABLE_PHASE3 else "PAPER"
                architecture = "v5.0.0 (Phase 1→2→3→4→5)"
                telegram.notify_system_startup(mode, architecture)
            except Exception as e:
                logger.debug(f"Startup notification failed: {e}")

        # Update mission_db state to RUNNING
        if MISSION_DB_AVAILABLE:
            try:
                mdb = get_mission_db()
                mdb.update_daily_state(system_state="RUNNING")
            except:
                pass
        
        # Run orchestrator
        orchestrator.run()
        
    except KeyboardInterrupt:
        logger.info("")
        logger.info("=" * 80)
        logger.info("⛔ SYSTEM STOPPED BY USER")
        logger.info("=" * 80)
        
        if telegram:
            telegram.send_message(
                f"⛔ SYSTEM STOPPED\n\n"
                f"User interrupt (Ctrl+C)\n"
                f"Time: {datetime.now().strftime('%H:%M:%S')}"
            )
        
        # v5.0.0: Save shutdown state
        if startup_controller:
            try:
                positions_overnight = _get_overnight_positions(orchestrator)
                ending_capital = _get_ending_capital(orchestrator, startup_result)
                total_pnl = _get_total_pnl(orchestrator)
                
                startup_controller.run_shutdown(
                    shutdown_type="USER_STOP",
                    positions_overnight=positions_overnight,
                    ending_capital=ending_capital,
                    total_pnl_net=total_pnl
                )
            except Exception as e:
                logger.error(f"Shutdown save failed: {e}")
    
    except Exception as e:
        logger.error("")
        logger.error("=" * 80)
        logger.error("❌ CRITICAL ERROR IN MAIN")
        logger.error("=" * 80)
        logger.error(f"Error: {e}")
        logger.error("")
        logger.error(traceback.format_exc())
        
        if telegram:
            telegram.send_message(
                f"🚨 SYSTEM CRASHED\n\n"
                f"Error: {str(e)[:150]}\n\n"
                f"Check logs immediately!"
            )
        
        # v5.0.0: Save crash state
        if startup_controller:
            try:
                positions_overnight = _get_overnight_positions(orchestrator)
                ending_capital = _get_ending_capital(orchestrator, startup_result)
                
                startup_controller.run_shutdown(
                    shutdown_type="CRASH",
                    positions_overnight=positions_overnight,
                    ending_capital=ending_capital,
                    total_pnl_net=0
                )
            except Exception as crash_e:
                logger.error(f"Crash state save failed: {crash_e}")
        
        # Also log to mission_db directly as safety net
        if MISSION_DB_AVAILABLE:
            try:
                mdb = get_mission_db()
                mdb.log_fault("UNKNOWN_CRASH", "CRITICAL",
                              description=str(e)[:200])
                mdb.update_daily_state(
                    shutdown_type="CRASH",
                    shutdown_time=datetime.now().isoformat(),
                    system_state="ERROR"
                )
            except:
                pass
    
    finally:
        # Allow system to sleep again
        if keep_awake:
            keep_awake.stop()
        
        # ═══════════════════════════════════════════════════════════════════
        # FINALIZE BLACKBOX & OPERATIONAL DB (retained from v2.5.0)
        # ═══════════════════════════════════════════════════════════════════
        
        if orchestrator and hasattr(orchestrator, 'blackbox') and orchestrator.blackbox:
            try:
                summary = orchestrator.blackbox.finalize()
                print(summary)
                logger.info("✅ Blackbox recording finalized")
                
                date_str = datetime.now().strftime('%Y-%m-%d')
                summary_file = f'data/blackbox/summary_{date_str}.txt'
                os.makedirs('data/blackbox', exist_ok=True)
                with open(summary_file, 'w', encoding='utf-8') as f:
                    f.write(summary)
                logger.info(f"✅ Daily summary saved: {summary_file}")
                
                if telegram:
                    tg_summary = f"📊 DAILY SUMMARY {date_str}\n\n"
                    tg_summary += f"Scans: {orchestrator.blackbox.stats['phase1_scans_count']}\n"
                    tg_summary += f"Stocks Monitored: {len(orchestrator.blackbox.stocks_monitored)}\n"
                    tg_summary += f"Signals: {orchestrator.blackbox.stats['signals_generated_count']}\n"
                    tg_summary += f"Trades: {orchestrator.blackbox.stats['trades_executed_count']}\n"
                    telegram.send_message(tg_summary)
            except Exception as e:
                logger.error(f"Error finalizing blackbox: {e}")
        
        # Finalize operational DB
        if DATABASE_AVAILABLE:
            try:
                db = get_db()
                db.finalize_day()
                logger.info("✅ Operational DB day finalized")
            except Exception as e:
                logger.error(f"Error finalizing operational DB: {e}")
        
        logger.info("")
        logger.info("=" * 80)
        logger.info("SYSTEM SHUTDOWN COMPLETE — v5.0.0")
        logger.info("=" * 80)


# ═══════════════════════════════════════════════════════════════════════════════
# HELPER FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════════

def _get_overnight_positions(orchestrator) -> list:
    """Extract overnight positions from orchestrator for shutdown save."""
    positions = []
    try:
        if orchestrator and hasattr(orchestrator, 'phase4') and orchestrator.phase4:
            ph4 = orchestrator.phase4
            if hasattr(ph4, 'positions'):
                for sym, pos in ph4.positions.items():
                    if isinstance(pos, dict):
                        positions.append({
                            'symbol': sym,
                            'entry_price': pos.get('entry_price', 0),
                            'qty': pos.get('quantity', pos.get('qty', 1)),
                            'product': pos.get('product', 'CNC'),
                            'unrealized_pnl': pos.get('unrealized_pnl', 0)
                        })
                    elif hasattr(pos, 'entry_price'):
                        positions.append({
                            'symbol': sym,
                            'entry_price': getattr(pos, 'entry_price', 0),
                            'qty': getattr(pos, 'quantity', 1),
                            'product': getattr(pos, 'product', 'CNC'),
                            'unrealized_pnl': getattr(pos, 'unrealized_pnl', 0)
                        })
    except Exception as e:
        logger.warning(f"Could not extract overnight positions: {e}")
    return positions


def _get_ending_capital(orchestrator, startup_result) -> float:
    """Get current capital for shutdown save."""
    try:
        if orchestrator and hasattr(orchestrator, 'capital_manager'):
            cm = orchestrator.capital_manager
            if cm and hasattr(cm, 'available_capital'):
                return cm.available_capital
        if startup_result:
            return startup_result.free_capital
    except:
        pass
    return 0


def _get_total_pnl(orchestrator) -> float:
    """Get total P&L for shutdown save."""
    try:
        if orchestrator and hasattr(orchestrator, 'daily_pnl'):
            return orchestrator.daily_pnl
        if orchestrator and hasattr(orchestrator, 'capital_manager'):
            cm = orchestrator.capital_manager
            if cm and hasattr(cm, 'daily_pnl'):
                return cm.daily_pnl
    except:
        pass
    return 0


# ═══════════════════════════════════════════════════════════════════════════════
# LEGACY FALLBACK FUNCTIONS (used when startup_controller not available)
# ═══════════════════════════════════════════════════════════════════════════════

def _legacy_broker_check(kite, telegram) -> dict:
    """Legacy broker state check (v2.5.0 compatible)."""
    logger.info("")
    logger.info("=" * 80)
    logger.info("🔍 LEGACY BROKER STATE CHECK")
    logger.info("=" * 80)
    
    broker_state = {
        'success': True,
        'check_time': datetime.now().isoformat(),
        'position_count': 0,
        'positions': [],
        'capital_deployed': 0,
        'unrealized_pnl': 0,
        'available_cash': 0,
        'used_margin': 0,
        'exposure_warning': False
    }
    
    try:
        positions = kite.positions()
        net_positions = positions.get('net', [])
        
        active_positions = []
        total_deployed = 0
        total_pnl = 0
        
        for pos in net_positions:
            if pos.get('quantity', 0) != 0:
                symbol = pos.get('tradingsymbol', 'UNKNOWN')
                qty = pos.get('quantity', 0)
                avg_price = pos.get('average_price', 0)
                pnl = pos.get('pnl', 0)
                value = abs(qty * avg_price)
                
                active_positions.append({
                    'symbol': symbol,
                    'quantity': qty,
                    'avg_price': avg_price,
                    'pnl': pnl,
                    'value': value,
                    'product': pos.get('product', 'UNKNOWN'),
                    'exchange': pos.get('exchange', 'NSE')
                })
                
                total_deployed += value
                total_pnl += pnl
        
        broker_state['position_count'] = len(active_positions)
        broker_state['positions'] = active_positions
        broker_state['capital_deployed'] = total_deployed
        broker_state['unrealized_pnl'] = total_pnl
        
        margins = kite.margins()
        equity_margin = margins.get('equity', {})
        broker_state['available_cash'] = equity_margin.get('available', {}).get('cash', 0)
        broker_state['used_margin'] = equity_margin.get('utilised', {}).get('debits', 0)
        
        logger.info(f"   Positions: {len(active_positions)}")
        logger.info(f"   Cash: ₹{broker_state['available_cash']:,.0f}")
        logger.info("✅ Legacy broker check complete")
        
        return broker_state
        
    except Exception as e:
        logger.error(f"❌ Legacy broker check failed: {e}")
        broker_state['success'] = False
        return broker_state


def _legacy_pre_market(kite, config, telegram, broker_state):
    """Legacy pre-market analysis (v2.5.0 compatible)."""
    current_time = datetime.now()
    
    if 8 <= current_time.hour < 9 or (current_time.hour == 9 and current_time.minute < 15):
        analysis_marker = f"data/pre_market_done_{current_time.strftime('%Y%m%d')}.txt"
        
        if not os.path.exists(analysis_marker):
            try:
                from pre_market_analyzer import PreMarketAnalyzer
                
                finbert = None
                try:
                    from finbert_analyzer import FinBERTAnalyzer
                    finbert = FinBERTAnalyzer()
                except:
                    pass
                
                pre_market = PreMarketAnalyzer(
                    kite=kite,
                    config=config,
                    telegram=telegram,
                    finbert=finbert,
                    chatgpt_key=getattr(config, 'CHATGPT_API_KEY', None)
                )
                
                recommendations = pre_market.run_daily_briefing()
                
                os.makedirs('data', exist_ok=True)
                with open(analysis_marker, 'w') as f:
                    f.write(f"Completed: {current_time.isoformat()}\n")
                    f.write(f"Outlook: {recommendations.get('market_outlook', 'UNKNOWN')}\n")
                
                logger.info("✅ Legacy pre-market analysis complete")
                
            except Exception as e:
                logger.error(f"❌ Legacy pre-market failed: {e}")


# ═══════════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    if sys.version_info < (3, 7):
        print("ERROR: Python 3.7 or higher required")
        print(f"Current version: {sys.version}")
        sys.exit(1)
    
    main()
