"""
MCX_MAIN.PY - Phase 7 Standalone Launcher
===========================================

Independent entry point for MCX commodity paper trading.
Runs separately from Algo_Beta (Option B architecture).

USAGE:
  python mcx_main.py                    # Manual start
  python mcx_main.py --wait-for-close   # Wait until 15:30 then start

AUTO-LAUNCH (Windows Task Scheduler):
  Trigger: Daily at 15:25 (Mon-Fri)
  Action:  python mcx_main.py --wait-for-close
  This ensures NSE system has stopped before MCX login.

LIFECYCLE:
  15:25 → Script starts, waits for 15:30
  15:30 → Kite login, instrument scan, WebSocket connect
  15:30-17:00 → Data accumulation (build candle history)
  17:00-22:45 → Active paper trading (ORB + VWAP MR + RSI Zone)
  22:45 → Entry cutoff
  23:00 → Force close all, daily summary
  23:10 → System exits

Author: Dheebanraj + Claude
Version: 7.0.0
Date: 2026-02-16
"""

import os
import sys
import time
import logging
from logging.handlers import RotatingFileHandler
import pyotp
import argparse
import traceback
from datetime import datetime, time as dt_time

# ─── Path Setup ───────────────────────────────────────────────────────────────

# Add current directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ─── Logging Setup ────────────────────────────────────────────────────────────

os.makedirs('logs', exist_ok=True)
os.makedirs('data/mcx', exist_ok=True)
os.makedirs('data/mcx/candles', exist_ok=True)

log_file = f"logs/mcx_phase7_{datetime.now().strftime('%Y%m%d')}.log"

# Console handler
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(logging.Formatter(
    '%(asctime)s | %(levelname)-7s | %(message)s', datefmt='%H:%M:%S'
))

# File handler with rotation
file_handler = RotatingFileHandler(
    log_file, maxBytes=10*1024*1024, backupCount=5, encoding='utf-8'
)
file_handler.setLevel(logging.DEBUG)
file_handler.setFormatter(logging.Formatter(
    '%(asctime)s | %(levelname)-7s | %(name)s | %(message)s', datefmt='%H:%M:%S'
))

logging.basicConfig(level=logging.DEBUG, handlers=[console_handler, file_handler])
logger = logging.getLogger(__name__)

# ─── Imports ──────────────────────────────────────────────────────────────────

try:
    from kiteconnect import KiteConnect, KiteTicker
except ImportError:
    logger.error("❌ kiteconnect not installed. Run: pip install kiteconnect")
    sys.exit(1)

try:
    from selenium import webdriver
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service
    from webdriver_manager.chrome import ChromeDriverManager
except ImportError:
    logger.error("❌ selenium not installed. Run: pip install selenium webdriver-manager")
    sys.exit(1)

from config import Config
from telegram_notifier import TelegramNotifier

# Import Keep Awake to prevent Windows sleep
try:
    from keep_awake import KeepAwake
    KEEP_AWAKE_AVAILABLE = True
except ImportError:
    KEEP_AWAKE_AVAILABLE = False

import mcx_config as cfg
from mcx_orchestrator import MCXOrchestrator


# ═══════════════════════════════════════════════════════════════════════════════
# KITE LOGIN (same as main_orchestrator.py)
# ═══════════════════════════════════════════════════════════════════════════════

def kite_login() -> KiteConnect:
    """Automated Kite login using Selenium."""
    
    logger.info("=" * 70)
    logger.info("KITE LOGIN")
    logger.info("=" * 70)
    
    max_retries = 3
    
    for attempt in range(1, max_retries + 1):
        logger.info(f"Login attempt {attempt}/{max_retries}")
        driver = None
        
        try:
            chrome_options = Options()
            chrome_options.add_argument('--headless')
            chrome_options.add_argument('--no-sandbox')
            chrome_options.add_argument('--disable-dev-shm-usage')
            chrome_options.add_argument('--disable-gpu')
            chrome_options.add_argument('--window-size=1920,1080')
            chrome_options.add_argument('--disable-extensions')
            chrome_options.add_argument('--disable-logging')
            chrome_options.add_argument('--log-level=3')
            
            service = Service(ChromeDriverManager().install())
            driver = webdriver.Chrome(service=service, options=chrome_options)
            
            login_url = f"https://kite.zerodha.com/connect/login?v=3&api_key={Config.ZERODHA_API_KEY}"
            driver.get(login_url)
            
            # User ID
            user_input = WebDriverWait(driver, 15).until(
                EC.presence_of_element_located((By.ID, "userid"))
            )
            user_input.send_keys(Config.ZERODHA_USER_ID)
            
            # Password
            pwd_input = driver.find_element(By.ID, "password")
            pwd_input.send_keys(Config.ZERODHA_PASSWORD)
            
            # Submit
            login_btn = driver.find_element(By.XPATH, "//button[@type='submit']")
            login_btn.click()
            
            # TOTP
            totp_input = WebDriverWait(driver, 15).until(
                EC.presence_of_element_located((By.XPATH, 
                    "//input[@type='number' or @type='text']"
                    "[@inputmode='numeric' or contains(@class,'totp') or @label='External TOTP']"))
            )
            totp = pyotp.TOTP(Config.ZERODHA_TOTP_SECRET)
            totp_input.send_keys(totp.now())
            
            # Wait for redirect
            WebDriverWait(driver, 20).until(
                lambda d: "request_token=" in d.current_url
            )
            
            request_token = driver.current_url.split("request_token=")[1].split("&")[0]
            logger.info("✅ Request token obtained")
            
            kite = KiteConnect(api_key=Config.ZERODHA_API_KEY)
            data = kite.generate_session(request_token, api_secret=Config.ZERODHA_API_SECRET)
            kite.set_access_token(data["access_token"])
            
            logger.info("✅ Access token generated — Kite Connect ready")
            return kite
            
        except Exception as e:
            logger.error(f"Login attempt {attempt} failed: {e}")
            if driver:
                try:
                    os.makedirs('logs/screenshots', exist_ok=True)
                    driver.save_screenshot(
                        f"logs/screenshots/mcx_login_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
                    )
                except:
                    pass
            
            if attempt < max_retries:
                logger.info(f"Retrying in 5 seconds...")
                time.sleep(5)
        finally:
            if driver:
                try:
                    driver.quit()
                except:
                    pass
    
    return None


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    """Main entry point for MCX Phase 7."""
    
    parser = argparse.ArgumentParser(description='MCX Phase 7 Paper Trading')
    parser.add_argument('--wait-for-close', action='store_true',
                        help='Wait until 15:30 before starting (for Task Scheduler)')
    args = parser.parse_args()
    
    # ─── Banner ───────────────────────────────────────────────────────────
    
    logger.info("")
    logger.info("╔══════════════════════════════════════════════════════════════════════╗")
    logger.info(f"║   MCX PHASE 7 - COMMODITY PAPER TRADING v{cfg.MCX_VERSION:15s}              ║")
    logger.info(f"║   {cfg.MCX_CODENAME:30s}                                       ║")
    logger.info(f"║   {datetime.now().strftime('%Y-%m-%d %H:%M:%S'):30s}                                       ║")
    logger.info("╚══════════════════════════════════════════════════════════════════════╝")
    logger.info("")
    
    # ─── Weekend check ────────────────────────────────────────────────────
    
    today = datetime.now()
    if today.weekday() >= 5:  # Saturday=5, Sunday=6
        logger.info("📅 Weekend — MCX market closed. Exiting.")
        return
    
    # ─── Wait for NSE close if requested ──────────────────────────────────
    
    if args.wait_for_close:
        target_time = today.replace(hour=15, minute=30, second=0, microsecond=0)
        now = datetime.now()
        
        if now < target_time:
            wait_seconds = (target_time - now).total_seconds()
            logger.info(f"⏰ --wait-for-close: Waiting {wait_seconds:.0f}s until 15:30...")
            logger.info(f"   NSE Algo_Beta should shutdown by then.")
            
            while datetime.now() < target_time:
                remaining = (target_time - datetime.now()).total_seconds()
                if int(remaining) % 60 == 0 and remaining > 0:
                    logger.info(f"   Waiting... {remaining/60:.0f} minutes remaining")
                time.sleep(10)
            
            logger.info("⏰ 15:30 reached — starting Phase 7")
        else:
            logger.info(f"Already past 15:30 ({now.strftime('%H:%M')}) — starting immediately")
    
    # ─── Late start check ─────────────────────────────────────────────────
    
    if datetime.now().time() >= cfg.MCX_HARD_STOP:
        logger.info(f"⏰ Past hard stop time ({cfg.MCX_HARD_STOP.strftime('%H:%M')}) — too late to start")
        return
    
    # ─── Keep Awake ───────────────────────────────────────────────────────
    
    keep_awake = None
    if KEEP_AWAKE_AVAILABLE:
        keep_awake = KeepAwake(keep_display_on=False, heartbeat_interval=120)
        if keep_awake.start():
            logger.info("✅ KeepAwake: Windows sleep prevention active")
        else:
            logger.warning("⚠️  KeepAwake failed to start")
    
    # ─── Telegram ─────────────────────────────────────────────────────────
    
    telegram = None
    if Config.ENABLE_TELEGRAM:
        telegram = TelegramNotifier(Config.TELEGRAM_BOT_TOKEN, Config.TELEGRAM_CHAT_ID)
        logger.info("✅ Telegram notifier initialized")
    
    # ─── Kite Login ───────────────────────────────────────────────────────
    
    kite = kite_login()
    if not kite:
        logger.error("❌ Login failed — cannot start Phase 7")
        if telegram:
            telegram.send_message("🚨 MCX Phase 7: Login FAILED — not starting")
        return
    
    # Verify profile
    try:
        profile = kite.profile()
        logger.info(f"✅ Logged in as: {profile.get('user_name')} ({profile.get('user_id')})")
        
        margins = kite.margins()
        eq_balance = margins.get('equity', {}).get('available', {}).get('live_balance', 0)
        cm_balance = margins.get('commodity', {}).get('available', {}).get('live_balance', 0)
        logger.info(f"   Equity: ₹{eq_balance:,.2f} | Commodity: ₹{cm_balance:,.2f}")
    except Exception as e:
        logger.warning(f"Profile check: {e}")
    
    # ─── WebSocket ────────────────────────────────────────────────────────
    
    logger.info("")
    logger.info("Initializing MCX WebSocket...")
    kws = KiteTicker(Config.ZERODHA_API_KEY, kite.access_token)
    
    # ─── Start Orchestrator ───────────────────────────────────────────────
    
    orchestrator = MCXOrchestrator(kite=kite, kws=kws, telegram=telegram)
    
    # Run orchestrator (blocks until shutdown)
    # WebSocket started inside orchestrator.run() via kws.connect(threaded=True)
    try:
        orchestrator.run()
    except KeyboardInterrupt:
        logger.info("\n⛔ Stopped by user (Ctrl+C)")
    except Exception as e:
        logger.error(f"❌ Phase 7 crashed: {e}")
        logger.error(traceback.format_exc())
        if telegram:
            telegram.send_message(f"🚨 MCX Phase 7 CRASHED: {str(e)[:150]}")
    finally:
        # Cleanup
        try:
            kws.close()
        except:
            pass
        
        if keep_awake:
            keep_awake.stop()
            logger.info("✅ KeepAwake stopped — Windows can sleep again")
        
        logger.info("")
        logger.info("=" * 70)
        logger.info("MCX PHASE 7 — SESSION COMPLETE")
        logger.info("=" * 70)
        logger.info(f"Log file: {log_file}")


# ═══════════════════════════════════════════════════════════════════════════════
# TASK SCHEDULER SETUP INSTRUCTIONS
# ═══════════════════════════════════════════════════════════════════════════════

TASK_SCHEDULER_HELP = """
╔══════════════════════════════════════════════════════════════════════╗
║   WINDOWS TASK SCHEDULER SETUP FOR AUTO-LAUNCH                      ║
╚══════════════════════════════════════════════════════════════════════╝

1. Open Task Scheduler (taskschd.msc)
2. Click "Create Task" (not Basic Task)

GENERAL TAB:
  Name: MCX Phase 7 Paper Trading
  Run whether user is logged on or not: NO (keep "only when logged on")
  Run with highest privileges: YES

TRIGGERS TAB:
  New Trigger:
    Begin: On a schedule
    Daily, recur every 1 day
    Start: 15:25:00
    Enabled: YES
  
  Advanced:
    Stop task if it runs longer than: 8 hours
    Enabled: YES

CONDITIONS TAB:
  Power:
    Start only if AC power: YES (prevents running on battery)
    Stop if switching to battery: NO
  
  Network:
    Start only if network available: YES

ACTIONS TAB:
  New Action:
    Program: C:\\Users\\dheeb\\AppData\\Local\\Programs\\Python\\Python310\\python.exe
    Arguments: mcx_main.py --wait-for-close
    Start in: C:\\Users\\dheeb\\Working\\Algo_Beta

SETTINGS TAB:
  Allow task to be run on demand: YES
  If task fails, restart every: 5 minutes, up to 3 times
  Stop if runs longer than: 8 hours
  If running task doesn't end: Stop the task

This launches at 15:25, waits until 15:30 (ensuring Algo_Beta has 
stopped), then runs Phase 7 until ~23:10.
"""


if __name__ == '__main__':
    if '--help-scheduler' in sys.argv:
        print(TASK_SCHEDULER_HELP)
    else:
        try:
            main()
        except Exception as e:
            logger.error(f"Unexpected error: {e}")
            logger.error(traceback.format_exc())
