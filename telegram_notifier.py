"""
TELEGRAM_NOTIFIER v5.4.0 - ADAPTIVE FREQUENCY + TWO-WAY BOT + SYSTEM HEALTH
═══════════════════════════════════════════════════════════════════════════════

🆕 v5.4.0 UPDATES (2026-02-24):
   1. 📊 notify_daily_trading_summary() — End-of-day recap with P&L, trades, capital
   2. 📤 notify_partial_exit() — Partial profit booking notification
   3. ✅ Wired: notify_system_startup() now called at boot
   4. ✅ Wired: notify_phase4_tcas_alert() now called on TCAS ALIM exits
   5. ✅ Wired: notify_partial_exit() now called on Phase 4 partial exits

✅ v4.6.0 FEATURES:
   1. 🤖 ADAPTIVE TELEGRAM FREQUENCY (ChatGPT-driven)
      - GPT rates importance of each Phase 2 update (1-10)
      - Score ≥ 6 → SEND, < 6 → SKIP
      - Quiet summaries after 15 min silence
      - Reduces ~64 messages/day → ~10-15 meaningful ones

   2. 🖥️ SYSTEM HEALTH MONITORING
      - Battery, CPU, RAM via psutil
      - WebSocket, Kite API, GPT API status
      - Every 30 min or on-demand via /status

   3. 📱 TWO-WAY BOT COMMAND LISTENER
      - Background thread polls for user replies
      - /freq, /status, /stocks, /capital, /quiet, /loud, /scan, /help
      - Security: only authorized chat_ids
      - Thread-safe command queue

✅ v4.4.0 PHASE 2 ENHANCEMENTS (2026-01-28):
   - notify_entry_signal_v4() with ADX, volume spike, GPT reasoning
   - notify_gpt_approved_entry() / notify_gpt_rejected_entry()
   - notify_adx_blocked() for ADX filter notifications
   - notify_entry_score_summary() for 100-point breakdown
   - notify_volume_spike_detected() for volume confirmation

Every message shows:
├─ What's happening NOW
├─ What action system is taking
├─ What you should expect next
└─ Clear timestamps

Author: Dheebanraj
Version: 5.4.0
Date: 2026-02-24
"""

import requests
import logging
import time
import html
import os
import json
import threading
import queue
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Callable

# System health monitoring
try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False

logger = logging.getLogger('TelegramNotifier')


class TelegramNotifier:

    def send_message_with_retry(self, message: str, max_retries: int = 3):
        """v3.1.0: Send message with retry + file fallback"""
        for attempt in range(max_retries):
            try:
                result = self.send_message(message)
                if result:
                    return True
            except Exception as e:
                logger.warning(f"Telegram attempt {attempt+1} failed: {e}")
                if attempt < max_retries - 1:
                    time.sleep(2)
        
        # All retries failed - write to file
        logger.error("All Telegram retries failed - writing to CRITICAL_ALERTS.txt")
        try:
            with open('CRITICAL_ALERTS.txt', 'a', encoding='utf-8') as f:
                f.write(f"\n{'='*80}\n")
                f.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"{message}\n")
            logger.info("✅ Alert written to CRITICAL_ALERTS.txt")
            return False
        except Exception as e:
            logger.error(f"Failed to write alert file: {e}")
            return False

    """
    Enhanced Telegram notifier with crystal-clear status messages.
    
    v4.6.0 NEW:
    ├─ Adaptive frequency (GPT-driven send/skip decisions)
    ├─ Two-way bot command listener (user commands via Telegram)
    ├─ System health monitoring (battery, CPU, RAM, APIs)
    
    v4.4.0:
    ├─ Clear system state indicators (WAITING, SCANNING, MONITORING, etc.)
    ├─ Action-oriented messages (what system is doing)
    ├─ Next-step guidance (what to expect)
    ├─ Consistent emoji system (🟢 active, 🟡 waiting, ⚪ idle)
    ├─ Retry logic (3 attempts with exponential backoff)
    └─ Fallback to local file logging on failure
    """
    
    MAX_RETRIES = 3
    RETRY_DELAYS = [1, 3, 5]  # Exponential backoff seconds
    
    def __init__(self, bot_token: str, chat_id: str):
        """
        Initialize Telegram notifier.
        
        Args:
            bot_token: Telegram bot token
            chat_id: Chat ID or comma-separated list of chat IDs
        """
        self.bot_token = bot_token
        
        # Handle multiple chat IDs
        if isinstance(chat_id, str):
            self.chat_ids = [cid.strip() for cid in chat_id.split(',')]
        else:
            self.chat_ids = [str(chat_id)]
        
        self.enabled = bool(bot_token and chat_id)
        
        # Fallback log file for critical messages
        self.fallback_log = 'logs/telegram_fallback.log'
        
        # ═══════════════════════════════════════════════════════════════
        # v4.6.0 NEW: ADAPTIVE TELEGRAM STATE
        # ═══════════════════════════════════════════════════════════════
        self._adaptive_state = {
            'last_sent_snapshot': {},        # Last Phase 2 data that was actually sent
            'last_sent_time': datetime.min,  # When last Phase 2 update was sent
            'quiet_since': None,             # When quiet period started (for quiet summary)
            'force_send': False,             # Override: force next update
            'quiet_mode': False,             # User requested /quiet
            'update_freq_minutes': 5,        # Default freq, changeable via /freq
            'total_sent_today': 0,           # Counter for daily stats
            'total_skipped_today': 0,        # Counter for daily stats
            'last_gpt_reason': '',           # Why GPT decided to send/skip
        }
        
        # ═══════════════════════════════════════════════════════════════
        # v4.6.0 NEW: COMMAND QUEUE (thread-safe)
        # ═══════════════════════════════════════════════════════════════
        self.command_queue = queue.Queue()  # Orchestrator polls this
        self._listener_thread = None
        self._listener_running = False
        
        # ═══════════════════════════════════════════════════════════════
        # v4.6.0 NEW: SYSTEM HEALTH STATE
        # ═══════════════════════════════════════════════════════════════
        self._last_health_time = datetime.min
        self._system_start_time = datetime.now()
        
        # ═══════════════════════════════════════════════════════════════
        # v4.10.0 NEW: PROACTIVE BATTERY MONITORING
        # Alerts at 80% (full) and 20% (low) - only once per threshold crossing
        # ═══════════════════════════════════════════════════════════════
        self._battery_state = {
            'last_level': None,           # Last known battery %
            'last_plugged': None,         # Last known plug status
            'alerted_80': False,          # Already alerted at 80%?
            'alerted_20': False,          # Already alerted at 20%?
            'last_check': datetime.min,   # When we last checked
            'check_interval': 60,         # Check every 60 seconds
        }
        
        self._orchestrator_ref = None  # v3.5.0: For phase-specific config routing

        if self.enabled:
            logger.info(f"✅ Telegram notifications enabled for {len(self.chat_ids)} recipient(s)")
        else:
            logger.warning("⚠️ Telegram notifications disabled (no token/chat_id)")
    
    def _log_fallback(self, message: str, is_critical: bool = False):
        """Log message to fallback file when Telegram fails"""
        try:
            os.makedirs('logs', exist_ok=True)
            with open(self.fallback_log, 'a', encoding='utf-8') as f:
                timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                priority = "CRITICAL" if is_critical else "INFO"
                f.write(f"[{timestamp}] [{priority}] {message}\n")
                f.write("-" * 60 + "\n")
            
            if is_critical:
                logger.critical(f"📝 FALLBACK LOG: {self.fallback_log}")
        except Exception as e:
            logger.error(f"Fallback logging failed: {e}")
    
    def send_message(self, message: str, parse_mode: str = 'HTML', is_critical: bool = False) -> int:
        """
        Send message to all configured chat IDs with retry logic.
        
        Args:
            message: Message text
            parse_mode: Parse mode (HTML or Markdown)
            is_critical: If True, will retry more aggressively and log to fallback
            
        Returns:
            Number of successful sends
        """
        if not self.enabled:
            return 0
        
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        success_count = 0
        
        for chat_id in self.chat_ids:
            sent = False
            
            # Retry loop
            for attempt in range(self.MAX_RETRIES):
                try:
                    payload = {
                        'chat_id': chat_id,
                        'text': message,
                        'parse_mode': parse_mode
                    }
                    
                    response = requests.post(url, json=payload, timeout=10)
                    
                    if response.status_code == 200:
                        success_count += 1
                        sent = True
                        break  # Success, exit retry loop
                        
                    elif response.status_code == 400:
                        error_data = response.json()
                        error_desc = error_data.get('description', '')
                        
                        if 'chat not found' in error_desc.lower() or 'bot was blocked' in error_desc.lower():
                            logger.warning(f"⚠️ Telegram user {chat_id} hasn't started the bot yet!")
                            break  # No point retrying
                        else:
                            logger.warning(f"⚠️ Telegram error 400 for {chat_id}: {error_desc}")
                    
                    elif response.status_code == 429:  # Rate limited
                        retry_after = response.json().get('parameters', {}).get('retry_after', 5)
                        logger.warning(f"⚠️ Telegram rate limited, waiting {retry_after}s")
                        time.sleep(retry_after)
                        continue
                    
                    else:
                        logger.warning(f"⚠️ Telegram send failed to {chat_id}: {response.status_code}")
                        
                except requests.exceptions.Timeout:
                    logger.warning(f"⚠️ Telegram timeout for {chat_id} (attempt {attempt + 1})")
                except requests.exceptions.ConnectionError:
                    logger.warning(f"⚠️ Telegram connection error for {chat_id} (attempt {attempt + 1})")
                except Exception as e:
                    logger.warning(f"⚠️ Telegram error for {chat_id}: {e}")
                
                # Wait before retry
                if attempt < self.MAX_RETRIES - 1:
                    time.sleep(self.RETRY_DELAYS[attempt])
            
            # If all retries failed and this is critical, log to fallback
            if not sent and is_critical:
                self._log_fallback(message, is_critical=True)
        
        if success_count > 0:
            logger.info(f"✅ Telegram notification sent to {success_count}/{len(self.chat_ids)} recipient(s)")
        elif is_critical:
            logger.critical("❌ CRITICAL: All Telegram sends failed! Check fallback log.")
        
        return success_count
    
    def send_critical(self, message: str) -> int:
        """Send critical message with aggressive retry and fallback logging"""
        return self.send_message(message, is_critical=True)
    
    
    # ═══════════════════════════════════════════════════════════════════════════
    # SYSTEM STATUS MESSAGES - CRYSTAL CLEAR
    # ═══════════════════════════════════════════════════════════════════════════
    
    def notify_system_startup(self, mode: str, architecture: str):
        """
        System startup notification.
        
        Shows:
        ├─ System is starting
        ├─ Mode (LIVE or PAPER)
        ├─ What will happen next
        └─ Clear timeline
        """
        now = datetime.now()
        mode_emoji = "🔴" if mode == "LIVE" else "🟢"
        
        message = f"""
╔════════════════════════════════════════╗
║  {mode_emoji} <b>SYSTEM STARTING</b>
╚════════════════════════════════════════╝

<b>📅 {now.strftime('%A, %B %d, %Y')}</b>
<b>🕐 {now.strftime('%I:%M:%S %p')}</b>

<b>⚙️ CONFIGURATION:</b>
• Mode: <b>{mode}</b>
• Architecture: {architecture}
• Entry Window: 10:00 AM - 2:00 PM

<b>📋 WHAT HAPPENS NEXT:</b>

<b>09:15 AM</b> → Market Opens
               System becomes active

<b>10:00 AM</b> → 🎯 First Scan (Interrupt #1)
               • V-Recovery detection
               • Momentum breakout detection
               • Pullback to value detection
               • Expected: 15-25 stocks

<b>01:30 PM</b> → 🎯 Second Scan (Interrupt #2)
               • Fresh opportunities
               • More stocks added

<b>02:55 PM</b> → 🎯 Final Scan (Interrupt #3)
               • Last chance entries

<b>🟡 CURRENT STATUS: WAITING FOR MARKET OPEN</b>

Next action at 09:15 AM (market open)
"""
        
        self.send_message(message)
    
    
    def notify_market_open(self):
        """Market opened - system activating."""
        message = f"""
╔════════════════════════════════════════╗
║  🟢 <b>MARKET OPEN</b>
╚════════════════════════════════════════╝

<b>🕐 {datetime.now().strftime('%I:%M:%S %p')}</b>

<b>🟢 SYSTEM STATUS: ACTIVE</b>

Market has opened. System is now active.

<b>⏱️ NEXT ACTION:</b>
• Waiting for 10:00 AM scan
• First scan in ~45 minutes
• System will automatically scan when ready

<b>💡 TIP:</b>
Market needs 45 min to stabilize after opening.
V-Recovery patterns appear clearest after 10 AM.
"""
        
        self.send_message(message)
    
    
    def notify_interrupt_starting(self, interrupt_name: str, interrupt_time: str):
        """
        Interrupt is starting (scan about to run).
        
        Shows:
        ├─ Which interrupt is firing
        ├─ What scan will do
        ├─ Expected outcome
        └─ Timeline
        """
        interrupt_map = {
            'initial': {
                'number': '1',
                'purpose': 'Market has stabilized, finding V-Recovery patterns',
                'expected': '15-25 stocks (highest quality patterns)'
            },
            'midday': {
                'number': '2',
                'purpose': 'Momentum shifts detected, finding breakout patterns',
                'expected': '8-15 additional stocks'
            },
            'final': {
                'number': '3',
                'purpose': 'Last chance entries, late-day reversals',
                'expected': '5-10 additional stocks'
            }
        }
        
        info = interrupt_map.get(interrupt_name, {
            'number': '?',
            'purpose': 'Scanning for trading opportunities',
            'expected': 'Variable'
        })
        
        message = f"""
╔════════════════════════════════════════╗
║  🎯 <b>SCAN #{info['number']} STARTING</b>
╚════════════════════════════════════════╝

<b>🕐 {datetime.now().strftime('%I:%M:%S %p')}</b>

<b>🟢 SYSTEM STATUS: SCANNING</b>

<b>📊 SCAN DETAILS:</b>
• Name: {interrupt_time} Scan
• Purpose: {info['purpose']}
• Expected: {info['expected']}

<b>🔍 WHAT SYSTEM IS DOING:</b>
1. Pausing Phase 2 monitoring
2. Running Phase 1 stock selection
3. Checking 3 strategies:
   • V-Recovery (your proven pattern)
   • Momentum Breakout (squeeze + volume)
   • Pullback to Value (uptrend + RSI)

<b>⏱️ ESTIMATED TIME: 1-2 minutes</b>

Stand by for scan results...
"""
        
        self.send_message(message)
    
    
    def notify_scan_complete(
        self, 
        interrupt_name: str,
        total_stocks: int,
        strategy_breakdown: Dict[str, int],
        ai_analysis: str = ""
    ):
        """
        Scan complete notification with strategy breakdown.
        
        Shows:
        ├─ How many stocks found
        ├─ Strategy breakdown (V-Recovery, Momentum, Pullback)
        ├─ What system will do next
        └─ Clear action items
        """
        now = datetime.now()
        
        # Strategy breakdown
        v_recovery = strategy_breakdown.get('V-Recovery', 0)
        momentum = strategy_breakdown.get('Momentum Breakout', 0)
        pullback = strategy_breakdown.get('Pullback to Value', 0)
        
        if total_stocks > 0:
            status_emoji = "✅"
            status_text = "STOCKS FOUND"
            next_status = "🟢 MONITORING ACTIVE"
        else:
            status_emoji = "⚠️"
            status_text = "NO STOCKS FOUND"
            next_status = "🟡 HUNT MODE ACTIVE"
        
        message = f"""
╔════════════════════════════════════════╗
║  {status_emoji} <b>{status_text}</b>
╚════════════════════════════════════════╝

<b>🕐 {now.strftime('%I:%M:%S %p')}</b>

<b>📊 SCAN RESULTS:</b>
Total Stocks Selected: <b>{total_stocks}</b>

<b>📈 STRATEGY BREAKDOWN:</b>
• V-Recovery: {v_recovery} stocks
• Momentum Breakout: {momentum} stocks
• Pullback to Value: {pullback} stocks

<b>🟢 SYSTEM STATUS: {next_status}</b>
"""
        
        if total_stocks > 0:
            message += f"""
<b>⏭️ NEXT ACTIONS:</b>
1. Phase 2 monitoring starts immediately
2. Watching for RSI 20-35 entry zones
3. Checking 9 filters for entry confirmation
4. Calculating 10-point entry scores

<b>💡 ENTRY CRITERIA:</b>
• Score 7.0+: STRONG BUY (immediate entry)
• Score 5.0-6.9: WEAK BUY (check ChatGPT)
• Score <5.0: Skip (too weak)

<b>⏰ MONITORING INTERVAL:</b>
Every 5 minutes until 2:00 PM (entry cutoff)
"""
        else:
            message += f"""
<b>⏭️ NEXT ACTIONS:</b>
1. Hunt Mode activated (searching for stocks)
2. Will re-scan every 30 minutes
3. System continues automatically

<b>💡 WHY NO STOCKS?</b>
• Market may be choppy/sideways
• No clear patterns yet
• System is being selective (good!)

<b>⏰ NEXT HUNT SCAN:</b>
In 30 minutes ({(now + timedelta(minutes=30)).strftime('%I:%M %p')})
"""
        
        self.send_message(message)
        
        # Send AI analysis if available
        if ai_analysis and total_stocks > 0:
            self._send_ai_analysis_chunked(ai_analysis)
    
    
    def notify_hunt_mode_activated(self):
        """Hunt mode activated (no stocks found)."""
        message = f"""
╔════════════════════════════════════════╗
║  🏹 <b>HUNT MODE ACTIVATED</b>
╚════════════════════════════════════════╝

<b>🕐 {datetime.now().strftime('%I:%M:%S %p')}</b>

<b>🟡 SYSTEM STATUS: HUNTING</b>

No stocks currently match entry criteria.

<b>🔄 WHAT SYSTEM IS DOING:</b>
• Automatically re-scanning every 30 min
• Searching for V-Recovery patterns
• Monitoring momentum breakouts
• Watching for pullback setups

<b>💡 THIS IS NORMAL:</b>
• Quality over quantity
• Better to wait than force trades
• System is being selective (good!)

<b>⏰ NEXT SCAN:</b>
In 30 minutes

System continues automatically...
"""
        
        self.send_message(message)
    
    
    def notify_hunt_mode_success(self, num_stocks: int):
        """Hunt mode found stocks!"""
        message = f"""
╔════════════════════════════════════════╗
║  ✅ <b>HUNT SUCCESSFUL!</b>
╚════════════════════════════════════════╝

<b>🕐 {datetime.now().strftime('%I:%M:%S %p')}</b>

<b>🟢 SYSTEM STATUS: MONITORING ACTIVE</b>

Found <b>{num_stocks}</b> stocks!

<b>⏭️ NEXT ACTIONS:</b>
1. Exiting hunt mode
2. Phase 2 monitoring starts now
3. Watching for entry signals

Hunt mode complete ✅
"""
        
        self.send_message(message)
    
    
    def notify_phase2_monitoring_start(self, num_stocks: int):
        """Phase 2 monitoring started."""
        message = f"""
╔════════════════════════════════════════╗
║  🔍 <b>MONITORING STARTED</b>
╚════════════════════════════════════════╝

<b>🕐 {datetime.now().strftime('%I:%M:%S %p')}</b>

<b>🟢 SYSTEM STATUS: MONITORING</b>

Monitoring <b>{num_stocks}</b> stocks for entry signals.

<b>🎯 WHAT SYSTEM IS WATCHING:</b>
• RSI crossing above 35
• VWAP alignment
• MACD momentum
• Volume confirmation

<b>📊 ENTRY SCORING:</b>
System calculates 10-point scores:
• 7.0+: STRONG BUY (enter immediately)
• 5.0-6.9: WEAK BUY (check ChatGPT)
• <5.0: Skip (too weak)

<b>⏰ UPDATE INTERVAL:</b>
Every 5 minutes until 2:00 PM

You'll receive alerts for HIGH confidence entries only.
"""
        
        self.send_message(message)
    
    
    # ═══════════════════════════════════════════════════════════════════════════
    # ENTRY SIGNAL MESSAGES - SCORE-BASED
    # ═══════════════════════════════════════════════════════════════════════════
    
    def notify_entry_signal(
        self,
        symbol: str,
        entry_price: float,
        entry_score: Dict,
        technical_data: Dict,
        chatgpt_sentiment: str = "",
        mode: str = "PAPER"
    ):
        """
        Entry signal notification with complete scoring breakdown.
        
        Shows:
        ├─ Stock details
        ├─ Entry score (10-point system)
        ├─ Score breakdown (RSI, VWAP, MACD, Volume)
        ├─ Technical details
        ├─ Action taken (PAPER or LIVE)
        └─ What to expect next
        """
        now = datetime.now()
        
        # Extract scoring data
        total_score = entry_score.get('total_score', 0)
        confidence = entry_score.get('confidence_level', 'UNKNOWN')
        breakdown = entry_score.get('breakdown', {})
        entry_reason = entry_score.get('entry_reason', 'Entry approved')
        
        # Extract technical data
        rsi = technical_data.get('rsi', 0)
        vwap = technical_data.get('vwap', 0)
        volume_ratio = technical_data.get('volume_ratio', 0)
        
        # Confidence emoji
        confidence_emoji = {
            'VERY HIGH': '🟢',
            'HIGH': '🟢',
            'MEDIUM': '🟡',
            'LOW': '🟠',
            'VERY LOW': '🔴'
        }.get(confidence, '⚪')
        
        # Mode tag
        mode_tag = f"[{mode} MODE]" if mode == "PAPER" else ""
        
        message = f"""
╔════════════════════════════════════════╗
║  {confidence_emoji} <b>ENTRY SIGNAL! {mode_tag}</b>
╚════════════════════════════════════════╝

<b>🕐 {now.strftime('%I:%M:%S %p')}</b>

<b>📊 STOCK: {symbol}</b>
<b>💰 Entry Price: ₹{entry_price:.2f}</b>

<b>🎯 ENTRY SCORE: {total_score:.1f}/10.0</b>
<b>📈 Confidence: {confidence}</b>

<b>📊 SCORE BREAKDOWN:</b>
• RSI Position: {breakdown.get('rsi', 0):.1f}/3.0
  └─ RSI: {rsi:.1f} (oversold zone ✅)

• VWAP Alignment: {breakdown.get('vwap', 0):.1f}/3.0
  └─ Price vs VWAP: ₹{vwap:.2f}

• MACD Momentum: {breakdown.get('macd', 0):.1f}/2.0
  └─ Bullish crossover detected ✅

• Volume: {breakdown.get('volume', 0):.1f}/2.0
  └─ {volume_ratio:.1f}x avg volume
"""
        
        # Add ChatGPT sentiment if available
        if chatgpt_sentiment:
            message += f"""
<b>🤖 CHATGPT SENTIMENT: {chatgpt_sentiment}</b>
"""
        
        # Add action taken
        if mode == "PAPER":
            message += f"""
<b>✅ DECISION: {entry_reason}</b>

<b>📝 PAPER MODE:</b>
• No real order placed
• Signal logged for analysis
• Track performance in signals file

<b>⏭️ IF THIS WERE LIVE:</b>
• Order would be placed now
• Stop-loss set automatically
• Profit target calculated
• Position monitored until exit
"""
        else:
            message += f"""
<b>✅ DECISION: {entry_reason}</b>

<b>🔴 LIVE MODE - ORDER PLACED!</b>
• Real order submitted to Zerodha
• Position monitoring active
• Stop-loss and target set
• Exit signals will be sent

<b>⏰ HOLDING PERIOD:</b>
• Target: 1-3 days (40-50% profit)
• Exit window: Thursday 11 AM - 2 PM
• Updates every 5 minutes
"""
        
        self.send_message(message)
    
    
    def notify_entry_rejected(
        self,
        symbol: str,
        entry_score: Dict,
        rejection_reason: str
    ):
        """Entry rejected (score too low or ChatGPT bearish)."""
        total_score = entry_score.get('total_score', 0)
        
        message = f"""
╔════════════════════════════════════════╗
║  ⚪ <b>ENTRY REJECTED</b>
╚════════════════════════════════════════╝

<b>📊 {symbol}</b>
<b>🎯 Score: {total_score:.1f}/10.0</b>

<b>❌ REJECTED: {rejection_reason}</b>

<b>💡 WHY:</b>
• Score below threshold
• Quality filter working correctly
• Better opportunities ahead

Continuing to monitor other stocks...
"""
        
        self.send_message(message)
    
    
    # ═══════════════════════════════════════════════════════════════════════════
    # EXIT & POSITION MESSAGES
    # ═══════════════════════════════════════════════════════════════════════════
    
    def notify_exit_signal(
        self,
        symbol: str,
        exit_price: float,
        entry_price: float,
        pnl: float,
        pnl_pct: float,
        exit_reason: str,
        mode: str = "PAPER"
    ):
        """Exit signal notification."""
        pnl_emoji = "🟢" if pnl > 0 else "🔴"
        mode_tag = f"[{mode} MODE]" if mode == "PAPER" else ""
        
        message = f"""
╔════════════════════════════════════════╗
║  {pnl_emoji} <b>EXIT SIGNAL! {mode_tag}</b>
╚════════════════════════════════════════╝

<b>📊 {symbol}</b>

<b>💰 TRADE SUMMARY:</b>
• Entry: ₹{entry_price:.2f}
• Exit: ₹{exit_price:.2f}
• P&L: {pnl_emoji} ₹{pnl:.2f} ({pnl_pct:+.2f}%)

<b>📋 EXIT REASON:</b>
{exit_reason}

<b>⏰ {datetime.now().strftime('%I:%M:%S %p')}</b>
"""
        
        if mode == "PAPER":
            message += """
<b>📝 PAPER MODE:</b>
Trade logged for performance tracking.
"""
        else:
            message += """
<b>🔴 LIVE MODE:</b>
Real exit order placed!
Position closed.
"""
        
        self.send_message(message)
    
    
    # ═══════════════════════════════════════════════════════════════════════════
    # SYSTEM STATUS UPDATES
    # ═══════════════════════════════════════════════════════════════════════════
    
    def notify_entry_window_closed(self):
        """Entry window closed (2:00 PM)."""
        message = f"""
╔════════════════════════════════════════╗
║  ⏸️ <b>ENTRY WINDOW CLOSED</b>
╚════════════════════════════════════════╝

<b>🕐 02:00 PM</b>

<b>🟡 SYSTEM STATUS: MONITORING EXITS ONLY</b>

<b>🔒 WHAT CHANGED:</b>
• No new entries accepted after 2:00 PM
• Existing positions monitored
• Exit signals still active

<b>⏰ REMAINING SCHEDULE:</b>
• 02:55 PM: Final scan (informational only)
• 03:30 PM: Market closes (system shutdown)

<b>💡 TIP:</b>
No new entries to avoid late-day volatility.
Focus on managing existing positions.
"""
        
        self.send_message(message)
    
    
    def notify_market_close(self):
        """Market closed - system shutting down."""
        message = f"""
╔════════════════════════════════════════╗
║  🔴 <b>MARKET CLOSED</b>
╚════════════════════════════════════════╝

<b>🕐 {datetime.now().strftime('%I:%M:%S %p')}</b>

<b>⚪ SYSTEM STATUS: SHUTTING DOWN</b>

<b>📊 TODAY'S SESSION COMPLETE</b>

<b>📁 REVIEW FILES:</b>
• Phase 1: data/phase1_outputs/ACTIVE.json
• Phase 2: data/phase2_outputs/entry_signals_*.json
• Phase 3: data/phase3_outputs/trades_*.json

<b>⏰ NEXT SESSION:</b>
Tomorrow at 09:15 AM

<b>💤 System will sleep until next market open.</b>

Good trading! 📈
"""
        
        self.send_message(message)
    
    
    def notify_error(self, error_type: str, error_message: str):
        """Critical error notification."""
        message = f"""
╔════════════════════════════════════════╗
║  🚨 <b>SYSTEM ERROR</b>
╚════════════════════════════════════════╝

<b>🕐 {datetime.now().strftime('%I:%M:%S %p')}</b>

<b>❌ ERROR TYPE: {error_type}</b>

<b>📝 DETAILS:</b>
{error_message[:200]}

<b>⚠️ ACTION REQUIRED:</b>
Check logs immediately!

<b>📁 LOG FILE:</b>
logs/trading_{datetime.now().strftime('%Y%m%d')}.log

System may continue or may need restart.
"""
        
        self.send_message(message)
    
    
    # ═══════════════════════════════════════════════════════════════════════════
    # HELPER METHODS
    # ═══════════════════════════════════════════════════════════════════════════
    
    def _send_ai_analysis_chunked(self, ai_analysis: str):
        """Send AI analysis in chunks to avoid Telegram limits."""
        if not self.enabled or not ai_analysis:
            return
        
        sections = []
        current_section = ""
        
        lines = ai_analysis.split('\n')
        
        for line in lines:
            if len(current_section) + len(line) + 1 > 3500:
                if current_section:
                    sections.append(current_section.strip())
                current_section = line + '\n'
            else:
                current_section += line + '\n'
        
        if current_section.strip():
            sections.append(current_section.strip())
        
        if not sections:
            sections = [ai_analysis]
        
        total_parts = len(sections)
        
        for idx, section in enumerate(sections, 1):
            section_safe = html.escape(section)
            
            if total_parts > 1:
                header = f"""
╔════════════════════════════════════════╗
║  🤖 <b>AI ANALYSIS (Part {idx}/{total_parts})</b>
╚════════════════════════════════════════╝

"""
            else:
                header = f"""
╔════════════════════════════════════════╗
║  🤖 <b>AI MARKET ANALYSIS</b>
╚════════════════════════════════════════╝

"""
            
            message = header + section_safe
            self.send_message(message)
            
            if idx < total_parts:
                time.sleep(0.5)
    
    # ═══════════════════════════════════════════════════════════════════════════════
    # PHASE 4 NOTIFICATIONS (v4.3 NEW!)
    # ═══════════════════════════════════════════════════════════════════════════════
    
    def notify_phase4_startup(self, positions_count: int = 0):
        """Notify Phase 4 Portfolio Manager startup"""
        message = f"""
╔════════════════════════════════════════╗
║  🛫 <b>PHASE 4 PORTFOLIO MANAGER</b>
╚════════════════════════════════════════╝

Status: <b>ACTIVE</b>
Open Positions: {positions_count}
Monitoring: TCAS/ILS/Health

🔒 Aviation safety systems initialized
"""
        return self.send_message(message)
    
    def notify_phase4_tcas_alert(
        self,
        symbol: str,
        alert_level: str,
        distance_to_stop_atr: float,
        current_price: float,
        stop_price: float,
        action_taken: str = None
    ):
        """
        Notify TCAS alert - collision avoidance warning
        
        Alert levels: CLEAR, TA (Traffic Advisory), RA (Resolution Advisory), ALIM (Immediate)
        """
        emoji_map = {
            'CLEAR': '🟢',
            'TA': '🟡',
            'RA': '🟠',
            'ALIM': '🔴'
        }
        emoji = emoji_map.get(alert_level, '⚪')
        
        action_text = f"\nAction: <b>{action_taken}</b>" if action_taken else ""
        
        message = f"""
{emoji} <b>TCAS {alert_level}: {symbol}</b>

Distance to Stop: {distance_to_stop_atr:.2f} ATR
Current: ₹{current_price:.2f}
Stop: ₹{stop_price:.2f}{action_text}
"""
        
        # RA and ALIM are critical
        if alert_level in ['RA', 'ALIM']:
            return self.send_critical(message)
        return self.send_message(message)
    
    def notify_phase4_ils_phase(
        self,
        symbol: str,
        phase: str,
        progress_pct: float,
        current_price: float,
        target_price: float
    ):
        """
        Notify ILS landing phase change
        
        Phases: CRUISE, OUTER_MARKER, MIDDLE_MARKER, INNER_MARKER, DECISION_HEIGHT, LANDING
        """
        phase_emoji = {
            'CRUISE': '✈️',
            'OUTER_MARKER': '🔵',
            'MIDDLE_MARKER': '🟡',
            'INNER_MARKER': '🟠',
            'DECISION_HEIGHT': '🎯',
            'LANDING': '🛬'
        }
        emoji = phase_emoji.get(phase, '📍')
        
        message = f"""
{emoji} <b>ILS {phase}: {symbol}</b>

Progress: {progress_pct:.1f}%
Current: ₹{current_price:.2f}
Target: ₹{target_price:.2f}
"""
        return self.send_message(message)
    
    def notify_phase4_chatgpt_decision(
        self,
        symbol: str,
        decision: str,
        confidence: float,
        reasoning: str
    ):
        """Notify ChatGPT Portfolio Manager decision"""
        decision_emoji = {
            'HOLD': '⏸️',
            'TIGHTEN_STOP': '🔒',
            'WIDEN_STOP': '🔓',
            'PARTIAL_25': '📉',
            'PARTIAL_50': '📉📉',
            'EXIT': '🚪',
            'EXTEND_TARGET': '🎯⬆️'
        }
        emoji = decision_emoji.get(decision, '🤖')
        
        # Truncate reasoning
        short_reason = reasoning[:100] + '...' if len(reasoning) > 100 else reasoning
        
        message = f"""
{emoji} <b>GPT Decision: {symbol}</b>

Decision: <b>{decision}</b>
Confidence: {confidence:.0%}
Reason: {short_reason}
"""
        return self.send_message(message)
    
    def notify_phase4_landing_analysis(
        self,
        symbol: str,
        decision: str,
        prob_today: float,
        prob_tomorrow: float,
        prob_stop_overnight: float
    ):
        """Notify landing probability analysis result"""
        decision_emoji = {
            'LAND_TODAY': '🛬',
            'HOLD_FOR_TOMORROW': '🌙',
            'PARTIAL_PROFIT_NOW': '💰',
            'EXIT_NOW': '🚪'
        }
        emoji = decision_emoji.get(decision, '📊')
        
        message = f"""
{emoji} <b>Landing Analysis: {symbol}</b>

Decision: <b>{decision}</b>

Probabilities:
├─ Target Today: {prob_today:.0%}
├─ Target Tomorrow: {prob_tomorrow:.0%}
└─ Stop Overnight: {prob_stop_overnight:.0%}
"""
        return self.send_message(message)
    
    def notify_phase4_gtt_modified(
        self,
        symbol: str,
        modification_type: str,
        old_price: float,
        new_price: float
    ):
        """Notify GTT order modification"""
        message = f"""
🔧 <b>GTT Modified: {symbol}</b>

Type: {modification_type}
Old: ₹{old_price:.2f}
New: ₹{new_price:.2f}
"""
        return self.send_message(message)
    
    def notify_phase4_emergency_exit(
        self,
        symbol: str,
        reason: str,
        exit_price: float,
        pnl_pct: float
    ):
        """Notify emergency exit triggered by Phase 4"""
        emoji = '🟢' if pnl_pct >= 0 else '🔴'
        
        message = f"""
🚨 <b>EMERGENCY EXIT: {symbol}</b>

Reason: {reason}
Exit Price: ₹{exit_price:.2f}
P&L: {emoji} {pnl_pct:+.2f}%
"""
        return self.send_critical(message)
    
    def notify_phase4_market_close(
        self,
        positions_closed: int,
        total_pnl: float,
        total_pnl_pct: float
    ):
        """Notify Phase 4 market close summary"""
        emoji = '🟢' if total_pnl >= 0 else '🔴'
        
        message = f"""
🌅 <b>PHASE 4 MARKET CLOSE</b>

Positions Closed: {positions_closed}
Total P&L: {emoji} ₹{total_pnl:,.2f} ({total_pnl_pct:+.2f}%)

🛫 Phase 4 shutdown complete
"""
        return self.send_message(message)

    # ═══════════════════════════════════════════════════════════════════════════════
    # v5.4.0 NEW NOTIFICATION METHODS
    # ═══════════════════════════════════════════════════════════════════════════════

    def notify_partial_exit(
        self,
        symbol: str,
        percent: int,
        exit_qty: int,
        exit_price: float,
        pnl: float,
        remaining_qty: int,
        reason: str = ""
    ):
        """
        v5.4.0: Notify partial profit booking.
        Called when Phase 4 sells a portion of a position.
        """
        emoji = '🟢' if pnl >= 0 else '🔴'
        message = (
            f"📤 PARTIAL EXIT ({percent}%)\n\n"
            f"Stock: {symbol}\n"
            f"Sold: {exit_qty} shares @ ₹{exit_price:.2f}\n"
            f"P&L: {emoji} ₹{pnl:+,.0f}\n"
            f"Remaining: {remaining_qty} shares\n"
            f"Reason: {reason}"
        )
        return self.send_message(message)

    def notify_daily_trading_summary(
        self,
        trades_today: int = 0,
        total_pnl: float = 0,
        winners: int = 0,
        losers: int = 0,
        open_positions: int = 0,
        phase5_trades: int = 0,
        signals_seen: int = 0,
        stocks_monitored: int = 0
    ):
        """
        v5.4.0: End-of-day trading summary with full P&L recap.
        Called at market close by orchestrator.
        """
        emoji = '🟢' if total_pnl >= 0 else '🔴'
        win_rate = (winners / trades_today * 100) if trades_today > 0 else 0

        lines = [
            f"🌅 DAILY TRADING SUMMARY",
            f"{'═' * 30}",
            f"",
            f"Trades: {trades_today} ({winners}W / {losers}L)",
        ]
        if trades_today > 0:
            lines.append(f"Win Rate: {win_rate:.0f}%")
        lines.extend([
            f"P&L: {emoji} ₹{total_pnl:+,.0f}",
            f"",
            f"Signals Seen: {signals_seen}",
            f"Stocks Monitored: {stocks_monitored}",
        ])
        if phase5_trades > 0:
            lines.append(f"Gap/PVAT Trades: {phase5_trades}")
        if open_positions > 0:
            lines.append(f"Carrying Forward: {open_positions} positions")
        lines.extend([
            f"",
            f"System shutting down for the day."
        ])

        message = "\n".join(lines)
        return self.send_message(message)

    # ═══════════════════════════════════════════════════════════════════════════════
    # PHASE 8 — TIER 3 INTELLIGENCE NOTIFICATIONS
    # ═══════════════════════════════════════════════════════════════════════════════

    def notify_ph8_morning_review(
        self,
        symbol: str,
        hold_days: int,
        pnl_pct: float,
        pnl_rupees: float,
        recommendation: str,
        confidence: int,
        reasoning: str,
        key_factors: list = None,
        risk_level: str = "MEDIUM",
        kalman_velocity: float = 0.0,
        kalman_tuesday_pred: float = 0.0,
        kalman_predicted_pnl: float = 0.0,
    ):
        """Ph8 Tier 3 morning intelligence review summary."""
        rec_emoji = {"HOLD": "OK", "CONCERN": "!!", "EXIT": "XX"}.get(recommendation, "??")
        risk_emoji = {"LOW": "OK", "MEDIUM": "!!", "HIGH": "XX", "CRITICAL": "XX"}.get(risk_level, "??")
        pnl_emoji = "+" if pnl_pct >= 0 else "-"

        factors_str = ""
        if key_factors:
            factors_str = "\n".join(f"  - {f}" for f in key_factors[:4])

        lines = [
            f"PH8 MORNING REVIEW ({datetime.now().strftime('%a %d %b')})",
            f"{'=' * 30}",
            f"",
            f"[{rec_emoji}] {recommendation} (confidence: {confidence}/100)",
            f"Risk: [{risk_emoji}] {risk_level}",
            f"",
            f"{symbol} | Day {hold_days} | P&L: [{pnl_emoji}] Rs{pnl_rupees:+,.0f} ({pnl_pct:+.2%})",
            f"",
            f"Kalman: vel={kalman_velocity:+.1f}/day | Tue pred: {kalman_tuesday_pred:.2f} ({kalman_predicted_pnl:+.2%})",
        ]

        if factors_str:
            lines.extend([f"", f"Key factors:", factors_str])

        if reasoning:
            lines.extend([f"", f"GPT: {reasoning[:200]}"])

        message = "\n".join(lines)
        is_critical = (recommendation == "EXIT" and confidence >= 80)
        if is_critical:
            return self.send_critical(message)
        return self.send_message(message)

    def notify_ph8_chatgpt_early_exit(
        self,
        symbol: str,
        exit_price: float,
        entry_price: float,
        pnl_pct: float,
        pnl_rupees: float,
        confidence: int,
        reasoning: str,
        hold_days: int,
    ):
        """Ph8 Tier 3 ChatGPT-triggered early exit alert."""
        lines = [
            f"PH8 EARLY EXIT — ChatGPT TRIGGERED",
            f"{'=' * 30}",
            f"",
            f"{symbol} SOLD at {exit_price:.2f}",
            f"Entry: {entry_price:.2f} | Hold: {hold_days} days",
            f"P&L: Rs{pnl_rupees:+,.0f} ({pnl_pct:+.2%})",
            f"",
            f"GPT confidence: {confidence}/100",
            f"Reason: {reasoning[:200]}",
        ]
        message = "\n".join(lines)
        return self.send_critical(message)

    def notify_ph8_kalman_reversal(
        self,
        symbol: str,
        velocity: float,
        acceleration: float,
        current_price: float,
        entry_price: float,
        tuesday_prediction: float,
    ):
        """Ph8 Tier 3 Kalman momentum reversal alert."""
        pnl_pct = (current_price - entry_price) / entry_price if entry_price > 0 else 0
        pred_pnl = (tuesday_prediction - entry_price) / entry_price if entry_price > 0 else 0

        lines = [
            f"PH8 KALMAN REVERSAL ALERT",
            f"{'=' * 30}",
            f"",
            f"{symbol} — momentum turned NEGATIVE",
            f"Velocity: {velocity:+.2f}/day | Accel: {acceleration:+.2f}",
            f"",
            f"Current: {current_price:.2f} (P&L: {pnl_pct:+.2%})",
            f"Tue prediction: {tuesday_prediction:.2f} (pred P&L: {pred_pnl:+.2%})",
            f"",
            f"ChatGPT consultation triggered.",
        ]
        message = "\n".join(lines)
        return self.send_message(message, is_critical=True)

    # ═══════════════════════════════════════════════════════════════════════════════
    # v4.4.0 PHASE 2 ENTRY NOTIFICATIONS
    # ═══════════════════════════════════════════════════════════════════════════════

    def notify_entry_signal_v4(
        self,
        symbol: str,
        entry_price: float,
        rsi: float,
        rsi_history: list,
        adx_value: float,
        volume_spike: float,
        entry_score: float,
        entry_grade: str,
        finbert_label: str,
        finbert_contribution: int,
        kalman_prediction: dict,
        target_price: float,
        stop_price: float,
        gpt_decision: str = None,
        gpt_confidence: float = None,
        gpt_reasoning: str = None
    ):
        """
        v4.4.0: Enhanced entry signal notification with all indicators.
        """
        # RSI history formatting
        rsi_history_str = " → ".join([f"{r:.1f}" for r in rsi_history[-4:]]) if rsi_history else "N/A"
        
        # ADX assessment
        if adx_value is None:
            adx_text = "N/A"
            adx_emoji = "⚪"
        elif adx_value < 20:
            adx_text = f"{adx_value:.1f} (RANGING ✅)"
            adx_emoji = "🟢"
        elif adx_value < 25:
            adx_text = f"{adx_value:.1f} (CONSOLIDATING ✅)"
            adx_emoji = "🟢"
        elif adx_value < 30:
            adx_text = f"{adx_value:.1f} (MODERATE TREND ⚠️)"
            adx_emoji = "🟡"
        else:
            adx_text = f"{adx_value:.1f} (STRONG TREND ⚠️)"
            adx_emoji = "🟠"
        
        # Volume spike formatting
        if volume_spike is None:
            vol_text = "N/A"
            vol_emoji = "⚪"
        elif volume_spike >= 2.0:
            vol_text = f"{volume_spike:.1f}x (STRONG SPIKE ✅)"
            vol_emoji = "🟢"
        elif volume_spike >= 1.5:
            vol_text = f"{volume_spike:.1f}x (MODERATE ⚠️)"
            vol_emoji = "🟡"
        else:
            vol_text = f"{volume_spike:.1f}x (WEAK ❌)"
            vol_emoji = "🔴"
        
        # Entry score grade emoji
        grade_emoji = {
            'STRONG_BUY': '🟢',
            'MODERATE_BUY': '🟡',
            'WEAK_BUY': '🟠',
            'SKIP': '🔴'
        }.get(entry_grade, '⚪')
        
        # FinBERT formatting
        finbert_emoji = "🟢" if finbert_label == "BULLISH" else ("🔴" if finbert_label == "BEARISH" else "⚪")
        finbert_sign = "+" if finbert_contribution >= 0 else ""
        
        # Kalman prediction
        kalman_text = ""
        if kalman_prediction:
            pred_price = kalman_prediction.get('price_predicted_15min', 0)
            velocity = kalman_prediction.get('velocity', 0)
            if pred_price > 0:
                kalman_pct = ((pred_price - entry_price) / entry_price * 100)
                vel_emoji = "📈" if velocity > 0 else "📉"
                kalman_text = f"\n<b>🔮 Kalman 15min:</b> ₹{pred_price:.2f} ({kalman_pct:+.2f}%) {vel_emoji}"
        
        # GPT section
        gpt_section = ""
        if gpt_decision:
            gpt_emoji = "✅" if gpt_decision in ['ENTER', 'GO'] else "❌"
            gpt_section = f"""
<b>🤖 ChatGPT:</b> {gpt_emoji} {gpt_decision} ({gpt_confidence:.0f}%)"""
            if gpt_reasoning:
                short_reason = gpt_reasoning[:150] + "..." if len(gpt_reasoning) > 150 else gpt_reasoning
                gpt_section += f"\n<i>{short_reason}</i>"
        
        # Calculate R:R
        risk = entry_price - stop_price
        reward = target_price - entry_price
        rr_ratio = reward / risk if risk > 0 else 0
        
        message = f"""
╔════════════════════════════════════════╗
║  🎯 <b>ENTRY SIGNAL v4.4.0</b>
╚════════════════════════════════════════╝

<b>📊 {symbol}</b>
💰 Entry: <b>₹{entry_price:.2f}</b>
🎯 Target: ₹{target_price:.2f} (+{((target_price/entry_price)-1)*100:.1f}%)
🛑 Stop: ₹{stop_price:.2f} ({((stop_price/entry_price)-1)*100:.1f}%)
⚖️ R:R = 1:{rr_ratio:.1f}

<b>📈 RSI Analysis:</b>
├─ Current: {rsi:.1f}
└─ Sequence: {rsi_history_str}

<b>{adx_emoji} ADX:</b> {adx_text}
<b>{vol_emoji} Volume Spike:</b> {vol_text}

<b>📊 Entry Score:</b> {grade_emoji} <b>{entry_score:.0f}/100</b> ({entry_grade})
<b>{finbert_emoji} FinBERT:</b> {finbert_label} ({finbert_sign}{finbert_contribution}pts){kalman_text}{gpt_section}

<b>⏰ {datetime.now().strftime('%H:%M:%S')}</b>
"""
        return self.send_message(message)
    
    
    def notify_gpt_approved_entry(
        self,
        symbol: str,
        confidence: float,
        reasoning: str,
        suggested_position_pct: float = None
    ):
        """v4.4.0: ChatGPT approved entry notification"""
        
        position_text = f"\nSuggested Position: {suggested_position_pct:.0f}%" if suggested_position_pct else ""
        short_reason = reasoning[:200] + "..." if len(reasoning) > 200 else reasoning
        
        message = f"""
╔════════════════════════════════════════╗
║  ✅ <b>GPT APPROVED: {symbol}</b>
╚════════════════════════════════════════╝

<b>Decision:</b> ENTER ✅
<b>Confidence:</b> {confidence:.0f}%{position_text}

<b>Reasoning:</b>
<i>{short_reason}</i>

🚀 Proceeding with entry!
"""
        return self.send_message(message)
    
    
    def notify_gpt_rejected_entry(
        self,
        symbol: str,
        confidence: float,
        reasoning: str,
        risk_notes: str = None
    ):
        """v4.4.0: ChatGPT rejected entry notification"""
        
        short_reason = reasoning[:200] + "..." if len(reasoning) > 200 else reasoning
        risk_text = f"\n\n<b>⚠️ Risk Notes:</b>\n<i>{risk_notes[:150]}</i>" if risk_notes else ""
        
        message = f"""
╔════════════════════════════════════════╗
║  ❌ <b>GPT REJECTED: {symbol}</b>
╚════════════════════════════════════════╝

<b>Decision:</b> SKIP ❌
<b>Confidence:</b> {confidence:.0f}%

<b>Reasoning:</b>
<i>{short_reason}</i>{risk_text}

⏸️ Entry skipped by ChatGPT Trade Advisor
"""
        return self.send_message(message)
    
    
    def notify_adx_blocked(
        self,
        symbol: str,
        adx_value: float,
        threshold: float
    ):
        """v4.4.0: ADX filter blocked entry notification"""
        
        message = f"""
╔════════════════════════════════════════╗
║  🚫 <b>ADX FILTER BLOCKED: {symbol}</b>
╚════════════════════════════════════════╝

<b>ADX Value:</b> {adx_value:.1f}
<b>Threshold:</b> {threshold:.0f}

⚠️ Market is TRENDING (ADX > {threshold:.0f})
V-Recovery strategy NOT recommended!

<b>Explanation:</b>
V-Recovery is a mean reversion strategy.
It works best in RANGING markets (ADX < {threshold:.0f}).
When market is trending, prices may not revert.

🔄 Will re-check when ADX drops below {threshold:.0f}
"""
        return self.send_message(message)
    
    
    def notify_entry_score_summary(
        self,
        symbol: str,
        total_score: float,
        breakdown: dict,
        grade: str
    ):
        """v4.4.0: Detailed entry score breakdown notification"""
        
        grade_emoji = {
            'STRONG_BUY': '🟢',
            'MODERATE_BUY': '🟡', 
            'WEAK_BUY': '🟠',
            'SKIP': '🔴'
        }.get(grade, '⚪')
        
        message = f"""
📊 <b>Entry Score: {symbol}</b>

{grade_emoji} <b>Total: {total_score:.0f}/100 ({grade})</b>

<b>Breakdown:</b>
├─ RSI Quality: {breakdown.get('rsi_quality', {}).get('score', 0) if isinstance(breakdown.get('rsi_quality'), dict) else breakdown.get('rsi_quality', 0)}/20
├─ Recovery: {breakdown.get('recovery_quality', {}).get('score', 0) if isinstance(breakdown.get('recovery_quality'), dict) else breakdown.get('recovery_quality', 0)}/25
├─ Volume: {breakdown.get('volume_ratio', {}).get('score', 0) if isinstance(breakdown.get('volume_ratio'), dict) else breakdown.get('volume_ratio', 0)}/20
├─ Trend: {breakdown.get('trend_context', {}).get('score', 0) if isinstance(breakdown.get('trend_context'), dict) else breakdown.get('trend_context', 0)}/20
└─ Timing: {breakdown.get('session_timing', {}).get('score', 0) if isinstance(breakdown.get('session_timing'), dict) else breakdown.get('session_timing', 0)}/15
"""
        return self.send_message(message)
    
    
    def notify_volume_spike_detected(
        self,
        symbol: str,
        spike_ratio: float,
        assessment: str
    ):
        """v4.4.0: Volume spike detection notification"""
        
        if spike_ratio >= 2.0:
            emoji = "🟢"
        elif spike_ratio >= 1.5:
            emoji = "🟡"
        else:
            emoji = "🔴"
        
        message = f"""
{emoji} <b>Volume Spike: {symbol}</b>

Spike Ratio: <b>{spike_ratio:.1f}x</b>
{assessment}
"""
        return self.send_message(message)
    
    
    # ═══════════════════════════════════════════════════════════════════════════
    # ═══════════════════════════════════════════════════════════════════════════
    #
    #  v4.6.0 FEATURE 1: ADAPTIVE TELEGRAM FREQUENCY (GPT-driven)
    #
    # ═══════════════════════════════════════════════════════════════════════════
    # ═══════════════════════════════════════════════════════════════════════════
    
    def detect_significant_changes(self, current_snapshot: Dict, config=None) -> Dict:
        """
        Compare current Phase 2 state with last sent snapshot.
        Returns dict with 'has_changes' bool and 'changes' list of descriptions.
        
        This is the RULE-BASED pre-filter before GPT. If no changes detected,
        we skip GPT entirely to save API calls.
        
        Args:
            current_snapshot: Current Phase 2 state dict with keys like:
                - stocks: {symbol: {rsi, state, blocked_by, ...}}
                - capital: {available, deployed, ...}
                - positions: count
                - nifty_filter: blocked/unblocked
            config: Config object for thresholds
        
        Returns:
            {'has_changes': bool, 'changes': [str], 'priority': str}
        """
        rsi_threshold = 3.0
        if config:
            rsi_threshold = getattr(config, 'ADAPTIVE_TELEGRAM_RSI_CHANGE_THRESHOLD', 3.0)
        
        last = self._adaptive_state.get('last_sent_snapshot', {})
        changes = []
        
        # === Check 1: New blocks or unblocks (FinBERT, capital, NIFTY) ===
        curr_stocks = current_snapshot.get('stocks', {})
        last_stocks = last.get('stocks', {})
        
        for symbol, data in curr_stocks.items():
            last_data = last_stocks.get(symbol, {})
            
            # State transition (e.g., WAITING → LOWER_ZONE, LOWER_ZONE → BOUNCE_DETECTED)
            curr_state = data.get('state', '')
            last_state = last_data.get('state', '')
            if curr_state != last_state and last_state:
                changes.append(f"{symbol}: State {last_state} → {curr_state}")
            
            # RSI significant movement
            curr_rsi = data.get('rsi')
            last_rsi = last_data.get('rsi')
            if curr_rsi is not None and last_rsi is not None:
                if abs(curr_rsi - last_rsi) >= rsi_threshold:
                    direction = "↑" if curr_rsi > last_rsi else "↓"
                    changes.append(f"{symbol}: RSI {last_rsi:.1f} → {curr_rsi:.1f} {direction}")
            
            # New block detected
            curr_block = data.get('blocked_by', '')
            last_block = last_data.get('blocked_by', '')
            if curr_block and not last_block:
                changes.append(f"🚫 {symbol}: Blocked by {curr_block}")
            elif not curr_block and last_block:
                changes.append(f"✅ {symbol}: Unblocked (was {last_block})")
        
        # === Check 2: Position count changed ===
        curr_positions = current_snapshot.get('positions', 0)
        last_positions = last.get('positions', 0)
        if curr_positions != last_positions:
            if curr_positions > last_positions:
                changes.append(f"📈 New position opened ({last_positions} → {curr_positions})")
            else:
                changes.append(f"📉 Position closed ({last_positions} → {curr_positions})")
        
        # === Check 3: NIFTY filter state changed ===
        curr_nifty = current_snapshot.get('nifty_filter_blocked', False)
        last_nifty = last.get('nifty_filter_blocked', False)
        if curr_nifty != last_nifty:
            if curr_nifty:
                changes.append("🔴 NIFTY market filter ACTIVATED")
            else:
                changes.append("🟢 NIFTY market filter CLEARED")
        
        # === Check 4: Capital significant change ===
        curr_capital = current_snapshot.get('capital_available', 0)
        last_capital = last.get('capital_available', 0)
        if last_capital > 0 and abs(curr_capital - last_capital) > 500:
            changes.append(f"💰 Capital: ₹{last_capital:,.0f} → ₹{curr_capital:,.0f}")
        
        # === Check 5: New stock added/removed from monitoring ===
        curr_symbols = set(curr_stocks.keys())
        last_symbols = set(last_stocks.keys())
        new_stocks = curr_symbols - last_symbols
        removed_stocks = last_symbols - curr_symbols
        if new_stocks:
            changes.append(f"➕ New stocks: {', '.join(new_stocks)}")
        if removed_stocks:
            changes.append(f"➖ Removed stocks: {', '.join(removed_stocks)}")
        
        # Determine priority
        priority = 'LOW'
        if any('position' in c.lower() for c in changes):
            priority = 'HIGH'
        elif any('blocked' in c.lower() or 'nifty' in c.lower() for c in changes):
            priority = 'MEDIUM'
        elif len(changes) >= 3:
            priority = 'MEDIUM'
        
        return {
            'has_changes': len(changes) > 0,
            'changes': changes,
            'priority': priority
        }
    
    def evaluate_with_gpt(self, changes: List[str], current_snapshot: Dict, config=None) -> Dict:
        """
        Ask lightweight GPT to rate the importance of detected changes.
        
        Returns: {'score': int (1-10), 'reason': str, 'next_check_minutes': int}
        """
        try:
            import anthropic as _anthropic

            api_key = None
            if config:
                api_key = getattr(config, 'ANTHROPIC_API_KEY', None) or getattr(config, 'CHATGPT_API_KEY', None)

            if not api_key:
                logger.debug("No API key for adaptive telegram call, using rule-based fallback")
                score = 7 if len(changes) >= 2 else 5
                return {'score': score, 'reason': 'Rule-based (no API key)', 'next_check_minutes': 5}

            model = "claude-haiku-4-5"
            if config:
                model = getattr(config, 'ADAPTIVE_TELEGRAM_MODEL', 'claude-haiku-4-5')

            client = _anthropic.Anthropic(api_key=api_key, timeout=10.0, max_retries=0)
            
            # Build compact context
            stocks_summary = []
            for sym, data in current_snapshot.get('stocks', {}).items():
                rsi = data.get('rsi', '?')
                state = data.get('state', '?')
                block = data.get('blocked_by', '')
                rsi_str = f"{rsi:.1f}" if isinstance(rsi, (int, float)) else str(rsi)
                line = f"{sym}: RSI={rsi_str} State={state}"
                if block:
                    line += f" BLOCKED({block})"
                stocks_summary.append(line)
            
            prompt = f"""You are a trading system notification filter. Rate the importance of these market changes for the trader (1-10 scale).

CHANGES DETECTED:
{chr(10).join(f'- {c}' for c in changes)}

CURRENT STATE:
{chr(10).join(stocks_summary)}
Positions: {current_snapshot.get('positions', 0)}
Capital Available: ₹{current_snapshot.get('capital_available', 0):,.0f}

RATING GUIDE:
1-3: Routine, no action needed (skip notification)
4-5: Minor changes, informational only (skip)
6-7: Meaningful changes, trader should know (SEND)
8-10: Critical - position change, signal, block (SEND immediately)

Respond ONLY with JSON: {{"score": N, "reason": "brief reason", "next_check_minutes": N}}"""

            response = client.messages.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=100,
                temperature=0.3
            )

            text = response.content[0].text.strip()

            # v5.7.0: Robust JSON extraction — strip fences then grab outermost { … }
            # The old fence regex (non-greedy .*?) could yield empty group(1) when the
            # model omits the closing ``` or uses \r\n line endings. The flat-brace
            # fallback \{[^{}]*\} never matched nested JSON (score/reason/next_check).
            import re
            # Step 1: strip any leading/trailing markdown fence lines
            _clean = re.sub(r'^```(?:json)?\s*\n?', '', text)
            _clean = re.sub(r'\n?```\s*$', '', _clean).strip()
            # Step 2: extract the outermost JSON object (handles nested braces)
            _brace_match = re.search(r'\{.*\}', _clean, re.DOTALL)
            if _brace_match:
                text = _brace_match.group(0).strip()
            else:
                text = _clean  # last resort — let json.loads raise a clear error

            result = json.loads(text)
            score = int(result.get('score', 5))
            reason = result.get('reason', 'No reason given')
            next_check = int(result.get('next_check_minutes', 5))

            logger.info(f"🤖 Adaptive Telegram GPT: score={score}/10, reason='{reason}', next={next_check}min")

            return {'score': score, 'reason': reason, 'next_check_minutes': next_check}

        except json.JSONDecodeError as e:
            logger.warning(f"GPT adaptive telegram response parse error: {e} | raw: {text[:200] if 'text' in dir() else 'N/A'}")
            # Score 4 = below default threshold (6), so parse failures → skip, not send
            return {'score': 4, 'reason': 'Parse error fallback', 'next_check_minutes': 5}
        except Exception as e:
            logger.warning(f"GPT adaptive telegram call failed: {e}")
            # Fallback: send if 2+ changes, skip if fewer
            score = 7 if len(changes) >= 2 else 4
            return {'score': score, 'reason': f'GPT fallback ({e})', 'next_check_minutes': 5}
    
    def should_send_phase2_update(self, current_snapshot: Dict, config=None) -> Dict:
        """
        Master decision: Should this Phase 2 cycle result in a Telegram message?
        
        Logic flow:
        1. If force_send=True (user /loud or critical event) → SEND
        2. If quiet_mode=True (/quiet) → SKIP (unless force or max silence)
        3. Detect rule-based changes vs last sent snapshot
        4. If no changes → SKIP
        5. If changes found → ask GPT to rate importance
        6. If GPT score >= threshold → SEND
        7. If score < threshold → SKIP
        8. If max_silence exceeded → force quiet summary
        
        Returns: {'send': bool, 'reason': str, 'message_type': 'full'|'quiet_summary'|'skip'}
        """
        now = datetime.now()
        threshold = 6
        max_silence_minutes = 20
        quiet_summary_minutes = 15
        
        if config:
            threshold = getattr(config, 'ADAPTIVE_TELEGRAM_SIGNIFICANCE_THRESHOLD', 6)
            max_silence_minutes = getattr(config, 'ADAPTIVE_TELEGRAM_MAX_SILENCE_MINUTES', 20)
            quiet_summary_minutes = getattr(config, 'ADAPTIVE_TELEGRAM_QUIET_SUMMARY_MINUTES', 15)
        
        # 1. Force send override
        if self._adaptive_state['force_send']:
            self._adaptive_state['force_send'] = False
            return {'send': True, 'reason': 'Force send (user command or critical event)', 'message_type': 'full'}
        
        # 2. Quiet mode
        if self._adaptive_state['quiet_mode']:
            # Still check max silence
            elapsed = (now - self._adaptive_state['last_sent_time']).total_seconds() / 60
            if elapsed >= max_silence_minutes:
                return {'send': True, 'reason': f'Max silence {max_silence_minutes}min exceeded in quiet mode', 'message_type': 'quiet_summary'}
            return {'send': False, 'reason': 'Quiet mode active', 'message_type': 'skip'}
        
        # 3. Rule-based change detection
        change_result = self.detect_significant_changes(current_snapshot, config)
        
        if not change_result['has_changes']:
            # No changes at all - check silence duration
            elapsed = (now - self._adaptive_state['last_sent_time']).total_seconds() / 60
            
            if elapsed >= max_silence_minutes:
                return {'send': True, 'reason': f'Max silence {max_silence_minutes}min exceeded', 'message_type': 'quiet_summary'}
            elif elapsed >= quiet_summary_minutes:
                return {'send': True, 'reason': f'Quiet period {quiet_summary_minutes}min - sending summary', 'message_type': 'quiet_summary'}
            
            self._adaptive_state['total_skipped_today'] += 1
            return {'send': False, 'reason': 'No significant changes', 'message_type': 'skip'}
        
        # 4. HIGH priority changes always send immediately
        if change_result['priority'] == 'HIGH':
            return {'send': True, 'reason': f"High priority: {', '.join(change_result['changes'][:2])}", 'message_type': 'full'}
        
        # 5. Ask GPT for MEDIUM/LOW priority changes
        gpt_result = self.evaluate_with_gpt(change_result['changes'], current_snapshot, config)
        
        self._adaptive_state['last_gpt_reason'] = gpt_result['reason']
        
        if gpt_result['score'] >= threshold:
            return {
                'send': True, 
                'reason': f"GPT score {gpt_result['score']}/10: {gpt_result['reason']}", 
                'message_type': 'full'
            }
        else:
            self._adaptive_state['total_skipped_today'] += 1
            # Track quiet period start
            if self._adaptive_state['quiet_since'] is None:
                self._adaptive_state['quiet_since'] = now
            
            return {
                'send': False, 
                'reason': f"GPT score {gpt_result['score']}/10: {gpt_result['reason']} (below {threshold})", 
                'message_type': 'skip'
            }
    
    def send_phase2_adaptive_update(self, stocks_data: Dict, config=None):
        """
        Send a Phase 2 cycle update formatted for adaptive display.
        
        Args:
            stocks_data: Dict with keys:
                - stocks: {symbol: {rsi, state, blocked_by, threshold, ...}}
                - positions: int
                - capital_available: float
                - capital_deployed: float
                - nifty_filter_blocked: bool
                - cycle_number: int
        """
        now = datetime.now()
        
        # Build stock lines
        stock_lines = []
        for symbol, data in stocks_data.get('stocks', {}).items():
            rsi = data.get('rsi')
            state = data.get('state', '?')
            blocked_by = data.get('blocked_by', '')
            threshold = data.get('threshold')
            
            # State emoji
            state_emoji = {
                'WAITING': '⏳',
                'LOWER_ZONE': '🔽',
                'BOUNCE_DETECTED': '📈',
                'CONFIRMATION': '✅',
                'ENTRY_READY': '🎯',
            }.get(state, '❓')
            
            rsi_str = f"{rsi:.1f}" if isinstance(rsi, (int, float)) else "?"
            thresh_str = f"/{threshold:.0f}" if isinstance(threshold, (int, float)) else ""
            
            line = f"{state_emoji} {symbol}: RSI {rsi_str}{thresh_str} [{state}]"
            
            if blocked_by:
                line += f" 🚫{blocked_by}"
            
            stock_lines.append(line)
        
        positions = stocks_data.get('positions', 0)
        capital_avail = stocks_data.get('capital_available', 0)
        capital_deployed = stocks_data.get('capital_deployed', 0)
        nifty_blocked = stocks_data.get('nifty_filter_blocked', False)
        cycle = stocks_data.get('cycle_number', '?')
        
        nifty_line = "🔴 NIFTY Filter: BLOCKED" if nifty_blocked else "🟢 NIFTY Filter: Clear"
        
        # Stats
        sent = self._adaptive_state['total_sent_today']
        skipped = self._adaptive_state['total_skipped_today']
        
        message = f"""📊 <b>Phase 2 Update</b> │ {now.strftime('%I:%M %p')}
─────────────────────
{chr(10).join(stock_lines) if stock_lines else '(No stocks monitored)'}

{nifty_line}
💼 Positions: {positions} │ 💰 ₹{capital_avail:,.0f} avail
📊 Cycle #{cycle} │ Sent {sent}/Skipped {skipped}"""
        
        self.send_message(message)
        
        # Update adaptive state
        self._adaptive_state['last_sent_time'] = now
        self._adaptive_state['last_sent_snapshot'] = stocks_data.copy()
        self._adaptive_state['quiet_since'] = None
        self._adaptive_state['total_sent_today'] += 1
    
    def send_quiet_summary(self, stocks_data: Dict, reason: str = ""):
        """
        Send a compact quiet period summary.
        Used when nothing significant happened for 15+ minutes.
        """
        now = datetime.now()
        
        # Collect RSI range
        rsi_values = []
        for sym, data in stocks_data.get('stocks', {}).items():
            rsi = data.get('rsi')
            if isinstance(rsi, (int, float)):
                rsi_values.append(rsi)
        
        rsi_range = ""
        if rsi_values:
            rsi_range = f"RSI range: {min(rsi_values):.0f}-{max(rsi_values):.0f}"
        
        # How long silent
        last_sent = self._adaptive_state['last_sent_time']
        if last_sent != datetime.min:
            silent_mins = (now - last_sent).total_seconds() / 60
            silent_str = f"{silent_mins:.0f}min"
        else:
            silent_str = "session start"
        
        stocks_count = len(stocks_data.get('stocks', {}))
        positions = stocks_data.get('positions', 0)
        
        # Estimate next update
        freq = self._adaptive_state['update_freq_minutes']
        next_est = now + timedelta(minutes=freq)
        
        message = f"""🔇 <b>Quiet Period</b> │ {now.strftime('%I:%M %p')}
─────────────────────
No significant changes for {silent_str}

📊 {stocks_count} stocks │ {rsi_range}
💼 Positions: {positions}
All stocks in normal monitoring.

⏭️ Next check: ~{next_est.strftime('%I:%M %p')}
{f'ℹ️ {reason}' if reason else ''}"""
        
        self.send_message(message)
        
        # Update state
        self._adaptive_state['last_sent_time'] = now
        self._adaptive_state['last_sent_snapshot'] = stocks_data.copy()
        self._adaptive_state['quiet_since'] = None
        self._adaptive_state['total_sent_today'] += 1
    
    def notify_adaptive_skip(self, reason: str):
        """Log (not send) when adaptive filter decides to skip a message."""
        logger.info(f"📱 Adaptive Telegram: SKIP - {reason}")
    
    def reset_adaptive_daily_stats(self):
        """Reset daily counters. Call at market open."""
        self._adaptive_state['total_sent_today'] = 0
        self._adaptive_state['total_skipped_today'] = 0
        self._adaptive_state['quiet_since'] = None
        self._adaptive_state['last_sent_snapshot'] = {}
        self._adaptive_state['last_sent_time'] = datetime.min
        logger.info("📱 Adaptive Telegram: Daily stats reset")
    
    
    # ═══════════════════════════════════════════════════════════════════════════
    # ═══════════════════════════════════════════════════════════════════════════
    #
    #  v4.6.0 FEATURE 2: SYSTEM HEALTH MONITORING
    #
    # ═══════════════════════════════════════════════════════════════════════════
    # ═══════════════════════════════════════════════════════════════════════════
    
    def send_system_health(self, extra_info: Dict = None):
        """
        Send comprehensive system health report via Telegram.
        
        Collects:
        - Battery level & charging status (psutil)
        - CPU usage (psutil)
        - RAM usage (psutil)
        - Uptime
        - Extra info passed by orchestrator (WebSocket, Kite API, GPT status, etc.)
        
        Args:
            extra_info: Optional dict with additional health data:
                - websocket_status: str ('CONNECTED' / 'DISCONNECTED')
                - websocket_uptime: str ('2h 15m')
                - kite_api_status: str ('OK' / 'ERROR')
                - kite_last_call: str ('3s ago')
                - gpt_api_status: str ('OK' / 'ERROR')
                - gpt_tokens_today: int
                - phase2_status: str ('Active' / 'Idle')
                - phase2_cycle: int
                - capital_available: float
                - capital_deployed: float
                - positions_count: int
                - monitored_stocks: int
        """
        now = datetime.now()
        extra = extra_info or {}
        
        # ── Battery ──
        battery_line = "🔋 Battery: N/A (no sensor)"
        if PSUTIL_AVAILABLE:
            try:
                battery = psutil.sensors_battery()
                if battery:
                    pct = battery.percent
                    plugged = battery.power_plugged
                    
                    if pct >= 80:
                        batt_emoji = "🟢"
                    elif pct >= 40:
                        batt_emoji = "🟡"
                    elif pct >= 20:
                        batt_emoji = "🟠"
                    else:
                        batt_emoji = "🔴"
                    
                    plug_str = "⚡ Plugged In" if plugged else "🔌 On Battery"
                    battery_line = f"{batt_emoji} Battery: {pct:.0f}% ({plug_str})"
                    
                    # Warning if low and unplugged
                    if pct < 20 and not plugged:
                        battery_line += "\n⚠️ LOW BATTERY - PLUG IN!"
                else:
                    battery_line = "🔋 Battery: Desktop (no battery)"
            except Exception:
                battery_line = "🔋 Battery: Error reading"
        
        # ── CPU ──
        cpu_line = "💻 CPU: N/A"
        if PSUTIL_AVAILABLE:
            try:
                cpu_pct = psutil.cpu_percent(interval=0.5)
                cpu_emoji = "🟢" if cpu_pct < 50 else ("🟡" if cpu_pct < 80 else "🔴")
                cpu_line = f"{cpu_emoji} CPU: {cpu_pct:.0f}%"
            except Exception:
                cpu_line = "💻 CPU: Error reading"
        
        # ── RAM ──
        ram_line = "🧠 RAM: N/A"
        if PSUTIL_AVAILABLE:
            try:
                mem = psutil.virtual_memory()
                used_gb = mem.used / (1024 ** 3)
                total_gb = mem.total / (1024 ** 3)
                pct = mem.percent
                ram_emoji = "🟢" if pct < 60 else ("🟡" if pct < 85 else "🔴")
                ram_line = f"{ram_emoji} RAM: {used_gb:.1f}GB / {total_gb:.1f}GB ({pct:.0f}%)"
            except Exception:
                ram_line = "🧠 RAM: Error reading"
        
        # ── Uptime ──
        uptime_delta = now - self._system_start_time
        hours = int(uptime_delta.total_seconds() // 3600)
        minutes = int((uptime_delta.total_seconds() % 3600) // 60)
        uptime_str = f"{hours}h {minutes}m"
        
        # ── WebSocket ──
        ws_status = extra.get('websocket_status', 'UNKNOWN')
        ws_uptime = extra.get('websocket_uptime', '')
        ws_emoji = "🟢" if ws_status == 'CONNECTED' else "🔴"
        ws_line = f"{ws_emoji} WebSocket: {ws_status}"
        if ws_uptime:
            ws_line += f" ({ws_uptime})"
        
        # ── Kite API ──
        kite_status = extra.get('kite_api_status', 'UNKNOWN')
        kite_last = extra.get('kite_last_call', '')
        kite_emoji = "🟢" if kite_status == 'OK' else "🔴"
        kite_line = f"{kite_emoji} Kite API: {kite_status}"
        if kite_last:
            kite_line += f" (last: {kite_last})"
        
        # ── GPT API ──
        gpt_status = extra.get('gpt_api_status', 'UNKNOWN')
        gpt_tokens = extra.get('gpt_tokens_today', 0)
        gpt_emoji = "🟢" if gpt_status == 'OK' else ("🟡" if gpt_status == 'UNKNOWN' else "🔴")
        gpt_line = f"{gpt_emoji} GPT API: {gpt_status}"
        if gpt_tokens:
            gpt_line += f" (tokens today: {gpt_tokens:,})"
        
        # ── Trading State ──
        phase2_status = extra.get('phase2_status', 'Unknown')
        phase2_cycle = extra.get('phase2_cycle', '?')
        positions = extra.get('positions_count', 0)
        monitored = extra.get('monitored_stocks', 0)
        capital_avail = extra.get('capital_available', 0)
        capital_deployed = extra.get('capital_deployed', 0)
        
        # ── Adaptive Telegram Stats ──
        sent = self._adaptive_state['total_sent_today']
        skipped = self._adaptive_state['total_skipped_today']
        freq = self._adaptive_state['update_freq_minutes']
        quiet = "ON" if self._adaptive_state['quiet_mode'] else "OFF"
        
        message = f"""🖥️ <b>SYSTEM HEALTH</b> │ {now.strftime('%I:%M %p')}
═════════════════════════
{battery_line}
{cpu_line}
{ram_line}
⏱️ Uptime: {uptime_str}
─────────────────────
{ws_line}
{kite_line}
{gpt_line}
─────────────────────
📊 Phase 2: {phase2_status} │ Cycle #{phase2_cycle}
📋 Monitoring: {monitored} stocks
💼 Positions: {positions}
💰 Capital: ₹{capital_avail:,.0f} avail │ ₹{capital_deployed:,.0f} deployed
─────────────────────
📱 Telegram: {sent} sent / {skipped} skipped
⏰ Frequency: {freq}min │ Quiet: {quiet}
═════════════════════════
✅ System v4.6.0 operational"""
        
        self.send_message(message)
        self._last_health_time = now
        logger.info("🖥️ System health report sent")
    
    def should_send_health(self, config=None) -> bool:
        """Check if it's time to send a health report."""
        interval = 30
        if config:
            interval = getattr(config, 'SYSTEM_HEALTH_INTERVAL_MINUTES', 30)
        
        elapsed = (datetime.now() - self._last_health_time).total_seconds() / 60
        return elapsed >= interval
    
    def check_battery_alerts(self) -> None:
        """
        v4.10.0 NEW: Proactive battery monitoring.
        
        Sends alerts when:
        - Battery reaches 80% while charging (fully charged alert)
        - Battery drops to 20% while unplugged (low battery alert)
        - Power plugged/unplugged status changes
        
        Called from orchestrator main loop.
        Only alerts ONCE per threshold crossing to avoid spam.
        """
        if not PSUTIL_AVAILABLE:
            return
        
        # Rate limit checks
        now = datetime.now()
        if (now - self._battery_state['last_check']).total_seconds() < self._battery_state['check_interval']:
            return
        
        self._battery_state['last_check'] = now
        
        try:
            battery = psutil.sensors_battery()
            if not battery:
                return  # Desktop or no battery sensor
            
            level = battery.percent
            plugged = battery.power_plugged
            
            last_level = self._battery_state['last_level']
            last_plugged = self._battery_state['last_plugged']
            
            # ═══════════════════════════════════════════════════════════════
            # Alert 1: Power plug status changed
            # ═══════════════════════════════════════════════════════════════
            if last_plugged is not None and plugged != last_plugged:
                if plugged:
                    self.send_message(
                        f"⚡ <b>POWER CONNECTED</b>\n\n"
                        f"🔋 Battery: {level:.0f}%\n"
                        f"✅ Laptop is now charging",
                        is_critical=False
                    )
                    logger.info(f"⚡ Power connected - Battery at {level:.0f}%")
                else:
                    self.send_message(
                        f"🔌 <b>POWER DISCONNECTED</b>\n\n"
                        f"🔋 Battery: {level:.0f}%\n"
                        f"⚠️ Running on battery power",
                        is_critical=True
                    )
                    logger.warning(f"🔌 Power disconnected - Battery at {level:.0f}%")
                
                # Reset threshold alerts on plug change
                self._battery_state['alerted_80'] = False
                self._battery_state['alerted_20'] = False
            
            # ═══════════════════════════════════════════════════════════════
            # Alert 2: Battery at 80% (fully charged notification)
            # ═══════════════════════════════════════════════════════════════
            if level >= 80 and plugged and not self._battery_state['alerted_80']:
                self.send_message(
                    f"🟢 <b>BATTERY FULL</b>\n\n"
                    f"🔋 Battery: {level:.0f}%\n"
                    f"✅ Fully charged - can unplug if needed\n"
                    f"💡 Tip: For battery health, avoid keeping at 100% always",
                    is_critical=False
                )
                logger.info(f"🟢 Battery full notification sent ({level:.0f}%)")
                self._battery_state['alerted_80'] = True
                self._battery_state['alerted_20'] = False  # Reset low alert
            
            # ═══════════════════════════════════════════════════════════════
            # Alert 3: Battery at 20% (low battery warning)
            # ═══════════════════════════════════════════════════════════════
            if level <= 20 and not plugged and not self._battery_state['alerted_20']:
                self.send_message(
                    f"🔴 <b>LOW BATTERY WARNING</b>\n\n"
                    f"🔋 Battery: {level:.0f}%\n"
                    f"⚠️ PLUG IN CHARGER NOW!\n\n"
                    f"⏰ Estimated time remaining: ~{battery.secsleft // 60} min" if battery.secsleft > 0 else "",
                    is_critical=True
                )
                logger.warning(f"🔴 Low battery warning sent ({level:.0f}%)")
                self._battery_state['alerted_20'] = True
                self._battery_state['alerted_80'] = False  # Reset high alert
            
            # ═══════════════════════════════════════════════════════════════
            # Alert 4: Critical battery (< 10%) - urgent!
            # ═══════════════════════════════════════════════════════════════
            if level <= 10 and not plugged:
                self.send_message(
                    f"🚨 <b>CRITICAL BATTERY - {level:.0f}%</b>\n\n"
                    f"⚠️ SYSTEM MAY SHUTDOWN SOON!\n"
                    f"🔌 PLUG IN IMMEDIATELY!\n\n"
                    f"💾 Positions are GTT-protected",
                    is_critical=True
                )
                logger.critical(f"🚨 CRITICAL BATTERY: {level:.0f}%")
            
            # Update state
            self._battery_state['last_level'] = level
            self._battery_state['last_plugged'] = plugged
            
            # Reset alerts when crossing back through thresholds
            if level < 75:
                self._battery_state['alerted_80'] = False
            if level > 25:
                self._battery_state['alerted_20'] = False
                
        except Exception as e:
            logger.debug(f"Battery check error: {e}")
    
    def _handle_battery_command(self):
        """
        v4.10.0 NEW: Handle /battery command - show detailed battery status.
        """
        if not PSUTIL_AVAILABLE:
            self.send_message("⚠️ Battery monitoring unavailable (psutil not installed)")
            return
        
        try:
            battery = psutil.sensors_battery()
            if not battery:
                self.send_message("🖥️ <b>Desktop Mode</b>\n\nNo battery detected - running on AC power.")
                return
            
            level = battery.percent
            plugged = battery.power_plugged
            secs_left = battery.secsleft
            
            # Status emoji
            if level >= 80:
                level_emoji = "🟢"
                status = "Excellent"
            elif level >= 50:
                level_emoji = "🟡"
                status = "Good"
            elif level >= 20:
                level_emoji = "🟠"
                status = "Low"
            else:
                level_emoji = "🔴"
                status = "Critical"
            
            # Power status
            if plugged:
                power_status = "⚡ Plugged In (Charging)"
            else:
                power_status = "🔌 On Battery"
            
            # Time remaining
            if secs_left > 0 and not plugged:
                hours = secs_left // 3600
                mins = (secs_left % 3600) // 60
                time_str = f"⏱️ Time remaining: {hours}h {mins}m"
            elif plugged:
                time_str = "⏱️ Charging..."
            else:
                time_str = "⏱️ Time remaining: Calculating..."
            
            message = f"""🔋 <b>BATTERY STATUS</b>
═══════════════════════

{level_emoji} Level: <b>{level:.0f}%</b> ({status})
{power_status}
{time_str}

───────────────────────
<i>Auto-alerts at 80% (full) and 20% (low)</i>
<i>Power plug/unplug events also notified</i>"""
            
            self.send_message(message)
            logger.info(f"📱 Battery status sent: {level:.0f}%")
            
        except Exception as e:
            self.send_message(f"❌ Error reading battery: {e}")
            logger.error(f"Battery command error: {e}")
    
    
    # ═══════════════════════════════════════════════════════════════════════════
    # ═══════════════════════════════════════════════════════════════════════════
    #
    #  v4.6.0 FEATURE 3: TWO-WAY BOT COMMAND LISTENER
    #
    # ═══════════════════════════════════════════════════════════════════════════
    # ═══════════════════════════════════════════════════════════════════════════
    
    def start_command_listener(self, config=None):
        """
        Start the background thread that polls Telegram for user commands.
        
        Uses Telegram Bot API's getUpdates endpoint (long polling).
        Thread-safe: commands placed into self.command_queue for orchestrator.
        
        Security: Only processes messages from authorized chat_ids.
        """
        if not self.enabled:
            logger.warning("⚠️ Cannot start command listener: Telegram disabled")
            return
        
        enabled = True
        if config:
            enabled = getattr(config, 'BOT_LISTENER_ENABLED', True)
        
        if not enabled:
            logger.info("📱 Bot command listener: DISABLED by config")
            return
        
        # Get authorized chat IDs
        self._authorized_ids = set(self.chat_ids)
        if config:
            extra_ids = getattr(config, 'BOT_LISTENER_AUTHORIZED_CHAT_IDS', [])
            if extra_ids:
                self._authorized_ids.update(str(cid) for cid in extra_ids)
        
        self._poll_interval = 3
        if config:
            self._poll_interval = getattr(config, 'BOT_LISTENER_POLL_INTERVAL', 3)
        
        self._listener_running = True
        self._listener_thread = threading.Thread(
            target=self._listener_loop,
            name="TelegramCommandListener",
            daemon=True  # Dies when main thread dies
        )
        self._listener_thread.start()
        logger.info(f"📱 Bot command listener started (poll every {self._poll_interval}s, auth: {self._authorized_ids})")
    
    def stop_command_listener(self):
        """Stop the command listener thread."""
        self._listener_running = False
        if self._listener_thread and self._listener_thread.is_alive():
            self._listener_thread.join(timeout=10)
            logger.info("📱 Bot command listener stopped")
    
    def _listener_loop(self):
        """
        Background loop: polls Telegram getUpdates API for new messages.
        Parses commands and places them in self.command_queue.
        """
        offset = None  # Track last processed update
        url = f"https://api.telegram.org/bot{self.bot_token}/getUpdates"
        
        logger.info("📱 Command listener: polling started")
        
        # On first run, flush any old messages + callback_queries to avoid stale events
        _allowed = ['message', 'callback_query']
        try:
            flush_resp = requests.get(url, params={'timeout': 1, 'allowed_updates': _allowed}, timeout=5)
            if flush_resp.status_code == 200:
                flush_data = flush_resp.json()
                results = flush_data.get('result', [])
                if results:
                    offset = results[-1].get('update_id', 0) + 1
                    logger.info(f"📱 Flushed {len(results)} old update(s)")
        except Exception as e:
            logger.debug(f"📱 Initial flush failed (ok): {e}")

        while self._listener_running:
            try:
                params = {
                    'timeout': 10,
                    'allowed_updates': _allowed,  # messages + button taps
                }
                if offset is not None:
                    params['offset'] = offset

                response = requests.get(url, params=params, timeout=15)

                if response.status_code != 200:
                    logger.warning(f"📱 Listener: API error {response.status_code}")
                    time.sleep(self._poll_interval)
                    continue

                data = response.json()

                if not data.get('ok', False):
                    logger.warning(f"📱 Listener: API returned ok=false")
                    time.sleep(self._poll_interval)
                    continue

                results = data.get('result', [])

                for update in results:
                    update_id = update.get('update_id', 0)
                    offset = update_id + 1  # Mark as processed

                    # ── Inline keyboard button tap ────────────────────────────
                    if 'callback_query' in update:
                        self._process_callback_query(update['callback_query'])
                        continue

                    # ── Regular text message ──────────────────────────────────
                    message = update.get('message', {})
                    chat_id = str(message.get('chat', {}).get('id', ''))
                    text = message.get('text', '').strip()

                    if chat_id not in self._authorized_ids:
                        logger.debug(f"📱 Listener: Ignoring message from unauthorized {chat_id}")
                        continue

                    if text.startswith('/'):
                        self._process_command(text, chat_id)

            except requests.exceptions.Timeout:
                pass  # Normal for long polling
            except requests.exceptions.ConnectionError:
                logger.warning("📱 Listener: Connection error, retrying...")
                time.sleep(5)
            except Exception as e:
                logger.error(f"📱 Listener error: {e}")
                time.sleep(self._poll_interval)

            time.sleep(0.5)

        logger.info("📱 Command listener: polling stopped")
    
    # ═══════════════════════════════════════════════════════════════════════════
    # v1.4.0: INLINE KEYBOARD (BUTTON) SUPPORT
    # Telegram Bot API inline keyboards — user taps buttons instead of typing.
    # ═══════════════════════════════════════════════════════════════════════════

    def send_message_with_buttons(self, text: str, buttons: list,
                                   parse_mode: str = 'HTML',
                                   edit_message_id: int = None) -> dict:
        """
        Send (or edit) a Telegram message with inline keyboard buttons.

        Args:
            text:            Message body (HTML by default).
            buttons:         List of rows. Each row is a list of (label, callback_data) tuples.
                             Example:
                               [
                                 [("✅ Done RELIANCE", "trade_done:RELIANCE"),
                                  ("⏭️ Skip",          "trade_skip:RELIANCE")],
                                 [("📊 Status",         "cmd:status"),
                                  ("💰 Capital",        "cmd:capital")],
                               ]
            parse_mode:      'HTML' or 'Markdown'
            edit_message_id: If provided, edits that existing message instead of sending new.

        Returns:
            Telegram API response dict (may be empty on error).
        """
        if not self.enabled or not self.bot_token:
            return {}
        try:
            keyboard = {
                'inline_keyboard': [
                    [{'text': label, 'callback_data': cb_data} for label, cb_data in row]
                    for row in buttons
                ]
            }
            import json as _json
            if edit_message_id:
                url = f"https://api.telegram.org/bot{self.bot_token}/editMessageText"
                payload = {
                    'chat_id':              self.chat_ids[0] if self.chat_ids else '',
                    'message_id':           edit_message_id,
                    'text':                 text,
                    'parse_mode':           parse_mode,
                    'reply_markup':         _json.dumps(keyboard),
                }
            else:
                url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
                payload = {
                    'chat_id':              self.chat_ids[0] if self.chat_ids else '',
                    'text':                 text,
                    'parse_mode':           parse_mode,
                    'reply_markup':         _json.dumps(keyboard),
                }
            resp = requests.post(url, data=payload, timeout=10)
            result = resp.json() if resp.status_code == 200 else {}
            return result.get('result', {})
        except Exception as e:
            logger.debug(f"send_message_with_buttons failed: {e}")
            return {}

    def answer_callback_query(self, callback_query_id: str, text: str = '', show_alert: bool = False):
        """
        Dismiss the 'loading' spinner on a tapped inline button.
        Must be called within 10 seconds of receiving the callback_query.
        """
        if not self.enabled or not self.bot_token:
            return
        try:
            url = f"https://api.telegram.org/bot{self.bot_token}/answerCallbackQuery"
            requests.post(url, data={
                'callback_query_id': callback_query_id,
                'text':              text,
                'show_alert':        show_alert,
            }, timeout=5)
        except Exception as e:
            logger.debug(f"answerCallbackQuery failed: {e}")

    def _process_callback_query(self, callback_query: dict):
        """
        Handle an inline keyboard button tap.

        callback_data format:  "<action>:<payload>"
        Examples:
            trade_done:RELIANCE
            trade_skip:RELIANCE
            cmd:status
            cmd:stocks
            cmd:capital
            cmd:scan
            cmd:quiet
            cmd:loud
            cmd:shield
            cmd:ph5a_status
            cmd:ph8_status
            cmd:chain_status
        """
        cb_id   = callback_query.get('id', '')
        chat_id = str(callback_query.get('from', {}).get('id', ''))
        data    = callback_query.get('data', '')

        # Security: only authorised users
        if chat_id not in self._authorized_ids:
            logger.debug(f"📱 Button tap from unauthorized {chat_id} — ignored")
            self.answer_callback_query(cb_id, "⛔ Not authorised")
            return

        logger.info(f"📱 Button tap: '{data}' from {chat_id}")

        if not data:
            self.answer_callback_query(cb_id)
            return

        # Parse  action:payload
        parts   = data.split(':', 1)
        action  = parts[0]
        payload = parts[1] if len(parts) > 1 else ''

        # ── Trade confirmation gate ────────────────────────────────────────────
        if action == 'trade_done':
            symbol = payload.upper() or 'ALL'
            self.command_queue.put({'command': 'trade_done', 'symbol': symbol})
            self.answer_callback_query(cb_id, f"✅ {symbol} marked as executed")
            logger.info(f"📱 Button: trade_done {symbol}")

        elif action == 'trade_skip':
            symbol = payload.upper() or 'ALL'
            self.command_queue.put({'command': 'trade_skip', 'symbol': symbol})
            self.answer_callback_query(cb_id, f"⏭️ {symbol} skipped")
            logger.info(f"📱 Button: trade_skip {symbol}")

        # ── Quick-action commands ──────────────────────────────────────────────
        elif action == 'cmd':
            cmd_text = f"/{payload.replace('_', ' ', 1)}"  # e.g. ph5a_status → /ph5a status
            self._process_command(cmd_text, chat_id)
            self.answer_callback_query(cb_id)

        else:
            self.answer_callback_query(cb_id, "❓ Unknown action")

    def _process_command(self, text: str, chat_id: str):
        """
        Parse a Telegram command and place it in the command queue.
        Also sends immediate acknowledgment to user.

        Supported commands:
        /freq N     - Set update frequency to N minutes (1-60)
        /status     - Trigger immediate system health report
        /stocks     - Show current monitored stocks + RSI
        /capital    - Show capital breakdown
        /quiet      - Suppress non-critical Phase 2 updates
        /loud       - Resume all updates (cancel quiet mode)
        /scan       - Request Phase 1 scan
        /gap        - Gap strategy status (also: /gap on, /gap off, /gap config)
        /help       - Show available commands
        """
        parts = text.split()
        command = parts[0].lower().replace('@', ' ').split()[0]  # Handle /command@botname
        args = parts[1:] if len(parts) > 1 else []
        
        logger.info(f"📱 Command received: '{text}' from {chat_id}")
        
        if command == '/freq':
            if args:
                try:
                    minutes = int(args[0])
                    if 1 <= minutes <= 60:
                        self._adaptive_state['update_freq_minutes'] = minutes
                        self.command_queue.put({'command': 'freq', 'value': minutes})
                        self.send_message(f"✅ Update frequency set to <b>{minutes} min</b>\n\nYou'll receive Phase 2 updates every {minutes} minutes (adaptive filter still applies).")
                        logger.info(f"📱 Frequency changed to {minutes}min by user command")
                    else:
                        self.send_message("⚠️ Frequency must be 1-60 minutes.\nUsage: /freq 15")
                except ValueError:
                    self.send_message("⚠️ Invalid number.\nUsage: /freq 15")
            else:
                current = self._adaptive_state['update_freq_minutes']
                self.send_message(f"Current frequency: <b>{current} min</b>\nUsage: /freq 15")
        
        elif command == '/status':
            self.command_queue.put({'command': 'status'})
            self.send_message("⏳ System health report coming...")
        
        elif command == '/battery':
            # v4.10.0 NEW: Manual battery check command
            self._handle_battery_command()
        
        elif command == '/stocks':
            self.command_queue.put({'command': 'stocks'})
            self.send_message("⏳ Fetching stock status...")
        
        elif command == '/capital':
            self.command_queue.put({'command': 'capital'})
            self.send_message("⏳ Fetching capital status...")
        
        elif command == '/quiet':
            self._adaptive_state['quiet_mode'] = True
            self.command_queue.put({'command': 'quiet'})
            self.send_message("🔇 <b>Quiet mode ON</b>\n\nNon-critical Phase 2 updates suppressed.\nYou'll still receive:\n• Entry signals\n• Position changes\n• Critical alerts\n• Periodic health checks\n\nSend /loud to resume.")
            logger.info("📱 Quiet mode enabled by user command")
        
        elif command == '/loud':
            self._adaptive_state['quiet_mode'] = False
            self._adaptive_state['force_send'] = True
            self.command_queue.put({'command': 'loud'})
            self.send_message("🔊 <b>Loud mode ON</b>\n\nAll updates resumed. Next Phase 2 cycle will be sent.")
            logger.info("📱 Loud mode enabled by user command")
        
        elif command == '/scan':
            self.command_queue.put({'command': 'scan'})
            self.send_message("🔍 <b>Scan requested</b>\n\nPhase 1 scan will run on next cycle.")
            logger.info("📱 Phase 1 scan requested by user command")
        
        elif command == '/gap':
            # v4.7.0 NEW: Gap strategy commands
            # /gap, /gap status, /gap on, /gap off, /gap config
            sub_command = args[0].lower() if args else 'status'
            self.command_queue.put({
                'command': 'gap',
                'sub_command': sub_command,
                'args': args[1:] if len(args) > 1 else []
            })
            
            if sub_command == 'on':
                self.send_message("⏳ Enabling gap strategy...")
            elif sub_command == 'off':
                self.send_message("⏳ Disabling gap strategy...")
            elif sub_command == 'config':
                self.send_message("⏳ Fetching gap strategy config...")
            else:
                self.send_message("⏳ Fetching gap strategy status...")
            logger.info(f"📱 Gap command received: /gap {sub_command}")

        elif command == '/ph5a':
            # v5.5.0 NEW: PH5A Sniper commands
            # /ph5a, /ph5a status, /ph5a on, /ph5a off
            sub_command = args[0].lower() if args else 'status'
            self.command_queue.put({
                'command': 'ph5a',
                'sub_command': sub_command,
                'args': args[1:] if len(args) > 1 else []
            })

            if sub_command == 'on':
                self.send_message("⏳ Enabling PH5A Sniper...")
            elif sub_command == 'off':
                self.send_message("⏳ Disabling PH5A Sniper...")
            else:
                self.send_message("⏳ Fetching PH5A status...")
            logger.info(f"📱 PH5A command received: /ph5a {sub_command}")

        elif command == '/shield':  # v5.5.0
            self.command_queue.put({'command': 'shield'})
            self.send_message("⏳ Fetching CNC Shield status...")
            logger.info("📱 Shield status command received")

        elif command == '/shutdown':
            if args and args[0].lower() == 'confirm':
                # Check if shutdown was requested within 60 seconds
                if (hasattr(self, '_shutdown_requested_at') and
                        self._shutdown_requested_at and
                        (datetime.now() - self._shutdown_requested_at).total_seconds() <= 60):
                    self.send_critical(
                        "SHUTTING DOWN...\n\n"
                        "Closing MIS positions and saving state.\n"
                        "System will stop in ~10 seconds."
                    )
                    self.command_queue.put({'command': 'shutdown', 'confirmed': True})
                    self._shutdown_requested_at = None
                    logger.critical("SHUTDOWN CONFIRMED by user")
                else:
                    self.send_message(
                        "No pending shutdown request.\n"
                        "Send /shutdown first, then /shutdown confirm within 60 seconds."
                    )
            else:
                # First step — request confirmation
                self._shutdown_requested_at = datetime.now()
                self.send_message(
                    "<b>SYSTEM SHUTDOWN REQUESTED</b>\n\n"
                    "This will:\n"
                    "  - Close all MIS positions (market orders)\n"
                    "  - Preserve CNC holdings (including Ph8 Tier 3)\n"
                    "  - Close Phase 6 paper shadows\n"
                    "  - Save all state to database\n"
                    "  - Stop the trading loop\n\n"
                    "CNC positions will NOT be sold.\n"
                    "System will NOT auto-restart.\n\n"
                    "Send <b>/shutdown confirm</b> within 60 seconds to proceed."
                )
                logger.warning("SHUTDOWN REQUESTED — waiting for confirmation")

        elif command == '/chain':
            if not args:
                # Show all chain statuses
                self.command_queue.put({'command': 'chain', 'sub_command': 'status'})
                self.send_message("Fetching chain status...")
            elif len(args) >= 2:
                chain_name = args[0].lower()
                action = args[1].lower()

                if chain_name == 'all':
                    if action in ('on', 'off'):
                        self.command_queue.put({
                            'command': 'chain',
                            'sub_command': f'all_{action}',
                        })
                        self.send_message(f"Setting ALL chains to {action.upper()}...")
                    else:
                        self.send_message("Usage: /chain all on|off")
                elif chain_name in ('ph1', 'ph5', 'ph5a', 'ph7', 'ph8'):
                    if action in ('on', 'off'):
                        self.command_queue.put({
                            'command': 'chain',
                            'sub_command': 'toggle',
                            'chain': chain_name,
                            'action': action,
                        })
                        self.send_message(f"Setting {chain_name.upper()} to {action.upper()}...")
                    else:
                        self.send_message(f"Usage: /chain {chain_name} on|off")
                else:
                    self.send_message(
                        f"Unknown chain: {chain_name}\n"
                        f"Available: ph1, ph5, ph5a, ph7, ph8, all"
                    )
            elif len(args) == 1:
                chain_name = args[0].lower()
                self.command_queue.put({
                    'command': 'chain',
                    'sub_command': 'detail',
                    'chain': chain_name,
                })
                self.send_message(f"Fetching {chain_name.upper()} status...")
            logger.info(f"Chain command received: /chain {' '.join(args)}")

        elif command == '/opt':
            self.command_queue.put({'command': 'opt', 'args': args})

        elif command == '/ph8':
            sub_command = args[0].lower() if args else 'status'
            self.command_queue.put({
                'command': 'ph8',
                'sub_command': sub_command,
                'args': args[1:] if len(args) > 1 else []
            })
            self.send_message("Fetching Phase 8 status...")
            logger.info(f"Ph8 command received: /ph8 {sub_command}")

        elif command == '/help':
            freq = self._adaptive_state['update_freq_minutes']
            mode = "🔇 Quiet" if self._adaptive_state['quiet_mode'] else "🔊 Loud"
            adaptive = "ON"
            
            help_msg = f"""<b>Algo_Beta Bot Commands</b>
═════════════════════════

<b>Monitoring:</b>
/status - System health report
/stocks - Current monitored stocks + RSI
/capital - Capital breakdown
/chain - All chain statuses

<b>Chain Control:</b>
/chain ph1 on|off - V-Recovery chain
/chain ph5 on|off - Gap strategy
/chain ph5a on|off - PVAT Sniper
/chain ph7 on|off - MCX Commodities
/chain ph8 on|off - Momentum strategy
/chain all on|off - ALL chains at once

<b>Phase 8:</b>
/ph8 - Momentum status + positions
/ph8 on|off - Enable/disable

<b>Settings:</b>
/freq N - Update frequency (1-60 min)
/quiet - Suppress Phase 2 updates
/loud - Resume all updates
/scan - Request Phase 1 scan
/gap - Gap strategy control
/ph5a - PH5A Sniper control
/shield - CNC Shield status
/config - View configuration
/set &lt;param&gt; &lt;value&gt; - Change setting
  e.g. /set ph5_score 55
  e.g. /set ph5_enabled off
  e.g. /set ph8_confidence 75

<b>Manual Trade Gate:</b>
/done SYMBOL - Confirm you placed the trade manually
/skip SYMBOL - Skip this trade (do not open position)

<b>Quick Access:</b>
/menu - Button panel (tap instead of typing)

<b>Brain (Claude):</b>
/ask &lt;question&gt; - Ask the AI anything about current state
  Or just type any message — it goes straight to the brain
  e.g. "why no trades?" / "resume ph5a" / "go defensive"
  The brain can answer questions AND change strategy live.

<b>System:</b>
/shutdown - Graceful system shutdown (2-step confirm)

Current: {freq}min | {mode}"""
            
            self.send_message(help_msg)
        
        elif command == '/config':
            # v4.10.0 NEW: Configuration viewing
            self._handle_config_command(args)
        
        elif command == '/set':
            # v4.10.0 NEW: Configuration setting
            self._handle_set_command(args)
        
        elif command == '/confirm':
            # v4.10.0 NEW: Confirm risky changes
            self._handle_confirm_command()

        elif command == '/menu':
            # v1.4.0: Quick-action button panel — tap instead of typing
            self.send_message_with_buttons(
                "<b>Algo_Beta — Quick Actions</b>\nTap a button:",
                [
                    [("📊 Status",    "cmd:status"),
                     ("📈 Stocks",    "cmd:stocks"),
                     ("💰 Capital",   "cmd:capital")],
                    [("🔍 Scan",      "cmd:scan"),
                     ("🔇 Quiet",     "cmd:quiet"),
                     ("🔊 Loud",      "cmd:loud")],
                    [("🛡️ Shield",    "cmd:shield"),
                     ("🎯 PH5A",      "cmd:ph5a_status"),
                     ("📉 PH8",       "cmd:ph8_status")],
                    [("⛓️ Chains",    "cmd:chain_status"),
                     ("⚙️ Config",    "cmd:config"),
                     ("❓ Help",      "cmd:help")],
                ]
            )

        elif command == '/done':
            # v1.4.0: Trade Confirmation Gate — user manually executed the trade
            symbol = args[0].upper() if args else 'ALL'
            self.command_queue.put({'command': 'trade_done', 'symbol': symbol})
            self.send_message(
                f"✅ <b>Received — {symbol}</b>\n"
                f"Marked as manually executed.\n"
                f"System will now register the position and set up exit management."
            )
            logger.info(f"📱 Trade DONE received for {symbol}")

        elif command == '/skip':
            # v1.4.0: Trade Confirmation Gate — user chose not to take the trade
            symbol = args[0].upper() if args else 'ALL'
            self.command_queue.put({'command': 'trade_skip', 'symbol': symbol})
            self.send_message(
                f"⏭️ <b>{symbol} skipped</b>\n"
                f"Trade discarded — no position will be opened."
            )
            logger.info(f"📱 Trade SKIP received for {symbol}")

        elif command == '/ask':
            # /ask <question> — explicit slash-command form
            question = ' '.join(args).strip()
            if question:
                self.command_queue.put({'command': 'ask', 'text': question})
            else:
                self.send_message("Usage: /ask <question>\nExample: /ask why no trades today?")

        else:
            # Any free-text message (not a /command) → route to brain
            if not text.startswith('/'):
                self.command_queue.put({'command': 'ask', 'text': text})
            else:
                self.send_message(f"❓ Unknown command: {command}\nSend /help for available commands.")
    
    # ═══════════════════════════════════════════════════════════════════════════
    # v4.10.0 NEW: TELEGRAM CONFIGURATION SYSTEM
    # ═══════════════════════════════════════════════════════════════════════════
    
    # Configurable parameters with validation rules
    CONFIG_PARAMS = {
        # Position Sizing
        'lot_size': {
            'attr': 'LOT_SIZE_CASH',
            'type': int,
            'min': 1000,
            'max': 50000,
            'unit': '₹',
            'category': 'position',
            'risky': False,
            'config_source': 'main',
            'description': 'Capital per lot'
        },
        'max_lots': {
            'attr': 'MAX_LOTS_PER_STOCK',
            'type': int,
            'min': 1,
            'max': 5,
            'unit': '',
            'category': 'position',
            'risky': True,
            'config_source': 'main',
            'description': 'Max lots per stock'
        },
        'max_positions': {
            'attr': 'MAX_TOTAL_POSITIONS',
            'type': int,
            'min': 1,
            'max': 10,
            'unit': '',
            'category': 'position',
            'risky': True,
            'config_source': 'main',
            'description': 'Max open positions'
        },
        'buffer': {
            'attr': 'EMERGENCY_BUFFER',
            'type': int,
            'min': 500,
            'max': 20000,
            'unit': '₹',
            'category': 'position',
            'risky': False,
            'config_source': 'main',
            'description': 'Emergency capital buffer'
        },

        # Exit Parameters
        'stop_loss': {
            'attr': 'STOP_LOSS_PCT',
            'type': float,
            'min': 0.5,
            'max': 10.0,
            'unit': '%',
            'category': 'exit',
            'risky': False,
            'config_source': 'main',
            'description': 'Stop loss percentage'
        },
        'target': {
            'attr': 'PROFIT_TARGET_PCT',
            'type': float,
            'min': 0.5,
            'max': 15.0,
            'unit': '%',
            'category': 'exit',
            'risky': False,
            'config_source': 'main',
            'description': 'Profit target percentage'
        },
        'trailing_trigger': {
            'attr': 'TRAILING_STOP_TRIGGER',
            'type': float,
            'min': 0.3,
            'max': 5.0,
            'unit': '%',
            'category': 'exit',
            'risky': False,
            'config_source': 'main',
            'description': 'Trailing stop activation'
        },
        'trailing_dist': {
            'attr': 'TRAILING_STOP_DISTANCE',
            'type': float,
            'min': 0.2,
            'max': 3.0,
            'unit': '%',
            'category': 'exit',
            'risky': False,
            'config_source': 'main',
            'description': 'Trailing stop distance'
        },

        # Entry Parameters
        'rsi_entry': {
            'attr': 'RSI_ENTRY_MAX',
            'type': int,
            'min': 20,
            'max': 50,
            'unit': '',
            'category': 'entry',
            'risky': False,
            'config_source': 'main',
            'description': 'RSI entry threshold'
        },
        'rsi_confirm': {
            'attr': 'RSI_CONFIRMATION',
            'type': int,
            'min': 25,
            'max': 55,
            'unit': '',
            'category': 'entry',
            'risky': False,
            'config_source': 'main',
            'description': 'RSI confirmation level'
        },
        'min_score': {
            'attr': 'MIN_ENTRY_SCORE',
            'type': int,
            'min': 40,
            'max': 90,
            'unit': '',
            'category': 'entry',
            'risky': False,
            'config_source': 'main',
            'description': 'Minimum entry score'
        },

        # AI Settings
        'chatgpt': {
            'attr': 'PHASE2_CHATGPT_ENABLED',
            'type': bool,
            'min': None,
            'max': None,
            'unit': '',
            'category': 'ai',
            'risky': False,
            'config_source': 'main',
            'description': 'ChatGPT for entries'
        },
        'fib_exit': {
            'attr': 'USE_ADVISOR_FOR_EXIT_STRATEGY',
            'type': bool,
            'min': None,
            'max': None,
            'unit': '',
            'category': 'ai',
            'risky': False,
            'config_source': 'main',
            'description': 'Fibonacci exit strategy'
        },

        # Monitoring Intervals
        'tier1_sleep': {
            'attr': 'TIER1_SLEEP_SECONDS',
            'type': int,
            'min': 5,
            'max': 30,
            'unit': 's',
            'category': 'monitoring',
            'risky': False,
            'config_source': 'main',
            'description': 'MIS/Phase5 monitoring interval'
        },
        'tier2_sleep': {
            'attr': 'TIER2_SLEEP_SECONDS',
            'type': int,
            'min': 15,
            'max': 300,
            'unit': 's',
            'category': 'monitoring',
            'risky': False,
            'config_source': 'main',
            'description': 'CNC/idle monitoring interval'
        },

        # ═══════════════════════════════════════════════════════════════
        # v3.5.0: Phase 5 — Gap Strategy Thresholds
        # These route to phase5.config (GapStrategyConfig), NOT main config
        # ═══════════════════════════════════════════════════════════════
        'ph5_score': {
            'attr': 'HALF_SIZE_SCORE',
            'type': int,
            'min': 30,
            'max': 90,
            'unit': '',
            'category': 'phase5',
            'risky': False,
            'config_source': 'ph5',
            'description': 'PH5 composite score threshold (also sets FULL_SIZE_SCORE)'
        },
        'ph5_enabled': {
            'attr': 'ENABLED',
            'type': bool,
            'min': None,
            'max': None,
            'unit': '',
            'category': 'phase5',
            'risky': True,
            'config_source': 'ph5',
            'description': 'PH5 gap strategy on/off'
        },
        'ph5_gap_target': {
            'attr': 'TCAS_ACTIVATION_PCT',
            'type': float,
            'min': 0.1,
            'max': 2.0,
            'unit': '%',
            'category': 'phase5',
            'risky': False,
            'config_source': 'ph5',
            'description': 'PH5 TCAS activation / target %'
        },
        'ph5_stop_atr': {
            'attr': 'STOP_ATR_MULTIPLIER',
            'type': float,
            'min': 0.2,
            'max': 3.0,
            'unit': 'x ATR',
            'category': 'phase5',
            'risky': False,
            'config_source': 'ph5',
            'description': 'PH5 stop loss ATR multiplier'
        },
        'ph5_vb_min': {
            'attr': 'MIN_VOLUME_BURST_SCORE',
            'type': int,
            'min': 5,
            'max': 40,
            'unit': '',
            'category': 'phase5',
            'risky': False,
            'config_source': 'ph5',
            'description': 'PH5 minimum Volume Burst score (0-50 scale)'
        },
        'ph5_max_adx': {
            'attr': 'MAX_ADX',
            'type': int,
            'min': 20,
            'max': 80,
            'unit': '',
            'category': 'phase5',
            'risky': False,
            'config_source': 'ph5',
            'description': 'PH5 maximum ADX filter'
        },
        'ph5_max_trades': {
            'attr': 'MAX_TRADES_PER_DAY',
            'type': int,
            'min': 1,
            'max': 5,
            'unit': '',
            'category': 'phase5',
            'risky': True,
            'config_source': 'ph5',
            'description': 'PH5 max trades per day'
        },

        # ═══════════════════════════════════════════════════════════════
        # v3.5.0: Phase 5A — PVAT Sniper Thresholds
        # These are on main config
        # ═══════════════════════════════════════════════════════════════
        'ph5a_enabled': {
            'attr': 'PH5A_SNIPER_ENABLED',
            'type': bool,
            'min': None,
            'max': None,
            'unit': '',
            'category': 'phase5a',
            'risky': True,
            'config_source': 'ph5a',
            'description': 'PH5A sniper on/off'
        },
        'ph5a_score': {
            'attr': 'PVAT_HALF_SIZE_SCORE',
            'type': int,
            'min': 40,
            'max': 95,
            'unit': '',
            'category': 'phase5a',
            'risky': False,
            'config_source': 'ph5a',
            'description': 'PH5A minimum score threshold (also sets PVAT_FULL_SIZE_SCORE)'
        },
        'ph5a_elite_score': {
            'attr': 'PH5A_ELITE_MIN_SCORE',
            'type': int,
            'min': 50,
            'max': 95,
            'unit': '',
            'category': 'phase5a',
            'risky': False,
            'config_source': 'ph5a',
            'description': 'PH5A elite sniper minimum score'
        },

        # ═══════════════════════════════════════════════════════════════
        # v3.5.0: Phase 1 — Stock Selection
        # ═══════════════════════════════════════════════════════════════
        'ph1_max_stocks': {
            'attr': 'MAX_STOCKS_TO_SELECT',
            'type': int,
            'min': 3,
            'max': 25,
            'unit': '',
            'category': 'phase1',
            'risky': False,
            'config_source': 'main',
            'description': 'Phase 1 max stocks to select'
        },

        # ═══════════════════════════════════════════════════════════════
        # v3.5.0: Phase 8 — Momentum Thresholds
        # These are on main config
        # ═══════════════════════════════════════════════════════════════
        'ph8_enabled': {
            'attr': 'PH8_SHADOW_ENABLED',
            'type': bool,
            'min': None,
            'max': None,
            'unit': '',
            'category': 'phase8',
            'risky': True,
            'config_source': 'ph8',
            'description': 'Phase 8 shadow options on/off'
        },
        'ph8_confidence': {
            'attr': 'PH8_SHADOW_MIN_CONFIDENCE',
            'type': int,
            'min': 40,
            'max': 95,
            'unit': '',
            'category': 'phase8',
            'risky': False,
            'config_source': 'ph8',
            'description': 'PH8 shadow minimum confidence score'
        },
        'ph8_exit_confidence': {
            'attr': 'PH8_CHATGPT_EXIT_MIN_CONFIDENCE',
            'type': int,
            'min': 50,
            'max': 95,
            'unit': '',
            'category': 'phase8',
            'risky': False,
            'config_source': 'ph8',
            'description': 'PH8 ChatGPT exit minimum confidence'
        },
        'ph8_target_min': {
            'attr': 'PH8_DYNAMIC_TARGET_MIN',
            'type': float,
            'min': 0.002,
            'max': 0.02,
            'unit': '%',
            'category': 'phase8',
            'risky': False,
            'config_source': 'ph8',
            'description': 'PH8 dynamic target minimum (decimal, e.g. 0.005 = 0.5%)'
        },
        'ph8_target_max': {
            'attr': 'PH8_DYNAMIC_TARGET_MAX',
            'type': float,
            'min': 0.01,
            'max': 0.05,
            'unit': '%',
            'category': 'phase8',
            'risky': False,
            'config_source': 'ph8',
            'description': 'PH8 dynamic target maximum (decimal, e.g. 0.03 = 3%)'
        },

        # ═══════════════════════════════════════════════════════════════
        # v3.5.0: Phase 7 — MCX
        # ═══════════════════════════════════════════════════════════════
        'mcx_enabled': {
            'attr': 'MCX_ENABLED',
            'type': bool,
            'min': None,
            'max': None,
            'unit': '',
            'category': 'mcx',
            'risky': True,
            'config_source': 'mcx',
            'description': 'MCX evening session on/off'
        },

        # ═══════════════════════════════════════════════════════════════
        # v3.5.0: PMBI (Pre-Market Breadth Intelligence)
        # ═══════════════════════════════════════════════════════════════
        'pmbi_enabled': {
            'attr': 'PMBI_ENABLED',
            'type': bool,
            'min': None,
            'max': None,
            'unit': '',
            'category': 'pmbi',
            'risky': False,
            'config_source': 'main',
            'description': 'Pre-market breadth scan on/off'
        },
        'pmbi_ph5_bonus': {
            'attr': 'PMBI_PH5_SCORE_BONUS',
            'type': int,
            'min': 0,
            'max': 20,
            'unit': 'pts',
            'category': 'pmbi',
            'risky': False,
            'config_source': 'main',
            'description': 'PMBI score bonus for aligned PH5 trades'
        },
    }
    
    # Pending confirmation for risky changes
    _pending_config_change = None
    
    def _handle_config_command(self, args: List[str]):
        """
        Handle /config command - show current configuration.
        
        Usage:
            /config          - Show all settings
            /config trading  - Show position/exit settings
            /config entry    - Show entry settings
            /config ai       - Show AI settings
            /config reset    - Reset to defaults (requires confirm)
        """
        try:
            # Get config reference
            if not hasattr(self, '_config_ref') or self._config_ref is None:
                self.send_message("⚠️ Configuration not available.\nConfig reference not set.")
                return
            
            config = self._config_ref
            
            # Handle sub-commands
            sub_cmd = args[0].lower() if args else 'all'
            
            if sub_cmd == 'reset':
                self._pending_config_change = {
                    'action': 'reset',
                    'timestamp': datetime.now()
                }
                self.send_message(
                    "⚠️ <b>RESET CONFIRMATION REQUIRED</b>\n\n"
                    "This will reset ALL parameters to defaults.\n"
                    "Changes made this session will be lost.\n\n"
                    "Send /confirm to proceed, or ignore to cancel."
                )
                return
            
            # Build configuration display
            msg_parts = ["📊 <b>CURRENT CONFIGURATION</b>\n═══════════════════════════"]
            
            # Position Sizing
            if sub_cmd in ['all', 'trading', 'position']:
                msg_parts.append("\n\n💰 <b>POSITION SIZING</b>")
                msg_parts.append(f"• Lot Size: ₹{getattr(config, 'LOT_SIZE_CASH', 6000):,}")
                msg_parts.append(f"• Max Lots/Stock: {getattr(config, 'MAX_LOTS_PER_STOCK', 2)}")
                msg_parts.append(f"• Max Positions: {getattr(config, 'MAX_TOTAL_POSITIONS', 2)}")
                msg_parts.append(f"• Emergency Buffer: ₹{getattr(config, 'EMERGENCY_BUFFER', 2000):,}")
            
            # Exit Parameters
            if sub_cmd in ['all', 'trading', 'exit']:
                msg_parts.append("\n\n🎯 <b>EXIT PARAMETERS</b>")
                msg_parts.append(f"• Stop Loss: {getattr(config, 'STOP_LOSS_PCT', 3.0)}%")
                msg_parts.append(f"• Target: {getattr(config, 'PROFIT_TARGET_PCT', 3.0)}%")
                msg_parts.append(f"• Trailing Trigger: {getattr(config, 'TRAILING_STOP_TRIGGER', 1.5)}%")
                msg_parts.append(f"• Trailing Distance: {getattr(config, 'TRAILING_STOP_DISTANCE', 0.8)}%")
            
            # Entry Parameters
            if sub_cmd in ['all', 'entry']:
                msg_parts.append("\n\n📈 <b>ENTRY PARAMETERS</b>")
                msg_parts.append(f"• RSI Entry Max: {getattr(config, 'RSI_ENTRY_MAX', 35)}")
                msg_parts.append(f"• RSI Confirmation: {getattr(config, 'RSI_CONFIRMATION', 35)}")
                msg_parts.append(f"• Min Entry Score: {getattr(config, 'MIN_ENTRY_SCORE', 70)}")
            
            # AI Settings
            if sub_cmd in ['all', 'ai']:
                msg_parts.append("\n\n🤖 <b>AI SETTINGS</b>")
                chatgpt_status = "ON ✅" if getattr(config, 'PHASE2_CHATGPT_ENABLED', True) else "OFF ❌"
                fib_status = "ON ✅" if getattr(config, 'USE_ADVISOR_FOR_EXIT_STRATEGY', True) else "OFF ❌"
                msg_parts.append(f"• ChatGPT: {chatgpt_status}")
                msg_parts.append(f"• Fibonacci Exit: {fib_status}")
            
            # Monitoring Intervals
            if sub_cmd in ['all', 'monitoring']:
                msg_parts.append("\n\n⏱️ <b>MONITORING INTERVALS</b>")
                msg_parts.append(f"• Tier 1 (MIS): {getattr(config, 'TIER1_SLEEP_SECONDS', 10)}s")
                msg_parts.append(f"• Tier 2 (CNC): {getattr(config, 'TIER2_SLEEP_SECONDS', 60)}s")
            
            # Help text
            msg_parts.append("\n\n<i>Use /set &lt;param&gt; &lt;value&gt; to change</i>")
            msg_parts.append("<i>Example: /set lot_size 8000</i>")
            
            self.send_message("\n".join(msg_parts))
            
        except Exception as e:
            logger.error(f"Config command error: {e}")
            self.send_message(f"❌ Error reading config: {e}")
    
    def _handle_set_command(self, args: List[str]):
        """
        Handle /set command - change configuration parameter.
        
        Usage:
            /set lot_size 8000
            /set stop_loss 3.5
            /set chatgpt on
        """
        try:
            if not args or len(args) < 2:
                # Show available parameters
                params_list = ", ".join(sorted(self.CONFIG_PARAMS.keys()))
                self.send_message(
                    "⚙️ <b>SET CONFIGURATION</b>\n\n"
                    f"Usage: /set &lt;param&gt; &lt;value&gt;\n\n"
                    f"<b>Available parameters:</b>\n{params_list}\n\n"
                    "<b>Examples:</b>\n"
                    "• /set lot_size 8000\n"
                    "• /set stop_loss 3.5\n"
                    "• /set chatgpt off"
                )
                return
            
            param_name = args[0].lower()
            value_str = args[1].lower()
            
            # Check if parameter exists
            if param_name not in self.CONFIG_PARAMS:
                similar = [p for p in self.CONFIG_PARAMS if param_name in p or p in param_name]
                hint = f"\nDid you mean: {', '.join(similar)}?" if similar else ""
                self.send_message(f"❌ Unknown parameter: {param_name}{hint}\n\nSend /set for list of parameters.")
                return
            
            param_info = self.CONFIG_PARAMS[param_name]
            
            # v3.5.0: Resolve correct config object based on parameter source
            config = self._resolve_config_target(param_info)
            if config is None:
                source = param_info.get('config_source', 'main')
                self.send_message(f"⚠️ Configuration not available for {source}. Phase may not be initialized yet.")
                return

            # Parse value based on type
            try:
                if param_info['type'] == bool:
                    if value_str in ['on', 'true', '1', 'yes', 'enable']:
                        new_value = True
                    elif value_str in ['off', 'false', '0', 'no', 'disable']:
                        new_value = False
                    else:
                        self.send_message(f"❌ Invalid value for {param_name}.\nUse: on/off, true/false, yes/no")
                        return
                elif param_info['type'] == int:
                    new_value = int(args[1])
                elif param_info['type'] == float:
                    new_value = float(args[1])
                else:
                    new_value = args[1]
            except ValueError:
                self.send_message(f"❌ Invalid value: {args[1]}\nExpected: {param_info['type'].__name__}")
                return
            
            # Validate range
            if param_info['min'] is not None and new_value < param_info['min']:
                self.send_message(f"❌ Value too low.\nMinimum: {param_info['min']}{param_info['unit']}")
                return
            if param_info['max'] is not None and new_value > param_info['max']:
                self.send_message(f"❌ Value too high.\nMaximum: {param_info['max']}{param_info['unit']}")
                return
            
            # Get current value
            attr_name = param_info['attr']
            old_value = getattr(config, attr_name, None)
            
            # Check if risky change needs confirmation
            if param_info['risky']:
                self._pending_config_change = {
                    'action': 'set',
                    'param': param_name,
                    'attr': attr_name,
                    'old_value': old_value,
                    'new_value': new_value,
                    'timestamp': datetime.now()
                }
                
                # Calculate risk warning
                warning = ""
                if param_name == 'max_positions':
                    lot_size = getattr(config, 'LOT_SIZE_CASH', 6000)
                    max_lots = getattr(config, 'MAX_LOTS_PER_STOCK', 2)
                    max_exposure = lot_size * max_lots * new_value
                    warning = f"\n\n⚠️ Max exposure: ₹{max_exposure:,}"
                elif param_name == 'max_lots':
                    lot_size = getattr(config, 'LOT_SIZE_CASH', 6000)
                    max_positions = getattr(config, 'MAX_TOTAL_POSITIONS', 2)
                    max_exposure = lot_size * new_value * max_positions
                    warning = f"\n\n⚠️ Max exposure: ₹{max_exposure:,}"
                
                self.send_message(
                    f"⚠️ <b>CONFIRMATION REQUIRED</b>\n\n"
                    f"Parameter: {param_name}\n"
                    f"Current: {old_value}\n"
                    f"New: {new_value}\n"
                    f"{warning}\n\n"
                    f"Send /confirm to apply, or ignore to cancel."
                )
                return
            
            # Apply change immediately for non-risky params
            self._apply_config_change(config, attr_name, old_value, new_value, param_name, param_info)
            
        except Exception as e:
            logger.error(f"Set command error: {e}")
            self.send_message(f"❌ Error: {e}")
    
    def _handle_confirm_command(self):
        """Handle /confirm command for risky changes."""
        if self._pending_config_change is None:
            self.send_message("❓ Nothing to confirm.\nNo pending configuration change.")
            return
        
        # Check if pending change is still valid (within 60 seconds)
        elapsed = (datetime.now() - self._pending_config_change['timestamp']).total_seconds()
        if elapsed > 60:
            self._pending_config_change = None
            self.send_message("⏰ Confirmation expired.\nPlease make the change again.")
            return
        
        try:
            # v3.5.0: Resolve correct config for confirmed changes
            pending = self._pending_config_change
            param_info = self.CONFIG_PARAMS.get(pending.get('param', ''), {})
            config = self._resolve_config_target(param_info)
            if config is None:
                self.send_message("⚠️ Configuration not available.")
                return

            if pending['action'] == 'reset':
                # Reset all to defaults - just notify user, actual reset needs restart
                self._pending_config_change = None
                self.send_message(
                    "✅ <b>RESET ACKNOWLEDGED</b>\n\n"
                    "Configuration will reset on next system restart.\n"
                    "Current session changes remain active."
                )
                logger.info("📱 Config reset requested by user")
                return
            
            # Apply the pending set change
            attr_name = pending['attr']
            old_value = pending['old_value']
            new_value = pending['new_value']
            param_name = pending['param']
            param_info = self.CONFIG_PARAMS[param_name]
            
            self._apply_config_change(config, attr_name, old_value, new_value, param_name, param_info)
            self._pending_config_change = None
            
        except Exception as e:
            logger.error(f"Confirm command error: {e}")
            self.send_message(f"❌ Error applying change: {e}")
            self._pending_config_change = None
    
    def _resolve_config_target(self, param_info: dict):
        """
        v3.5.0: Resolve which config object a parameter belongs to.

        Returns the config object to setattr on, or None if unavailable.
        """
        config_source = param_info.get('config_source', 'main')

        if config_source == 'main':
            return self._config_ref

        if not hasattr(self, '_orchestrator_ref') or self._orchestrator_ref is None:
            return None

        orch = self._orchestrator_ref

        if config_source == 'ph5':
            if hasattr(orch, 'phase5') and orch.phase5 and hasattr(orch.phase5, 'config'):
                return orch.phase5.config
            return None

        if config_source == 'ph5a':
            # PH5A thresholds are on main config
            return self._config_ref

        if config_source == 'ph8':
            # PH8 thresholds are on main config
            return self._config_ref

        if config_source == 'mcx':
            # MCX thresholds are on main config
            return self._config_ref

        return self._config_ref

    def _apply_config_change(self, config, attr_name: str, old_value, new_value, param_name: str, param_info: dict):
        """Apply configuration change and notify user."""
        try:
            # Apply the change
            setattr(config, attr_name, new_value)

            # v3.5.0: Paired thresholds — some params should update both HALF and FULL
            paired_attrs = {
                'HALF_SIZE_SCORE': 'FULL_SIZE_SCORE',      # PH5: keep both in sync
                'PVAT_HALF_SIZE_SCORE': 'PVAT_FULL_SIZE_SCORE',  # PH5A: keep both in sync
            }
            if attr_name in paired_attrs:
                paired_attr = paired_attrs[attr_name]
                setattr(config, paired_attr, new_value)
                logger.info(f"📱 PAIRED UPDATE: {paired_attr} = {new_value} (synced with {attr_name})")

            # Format values for display
            unit = param_info['unit']
            if param_info['type'] == bool:
                old_display = "ON ✅" if old_value else "OFF ❌"
                new_display = "ON ✅" if new_value else "OFF ❌"
            elif unit == '₹':
                old_display = f"₹{old_value:,}" if old_value else "N/A"
                new_display = f"₹{new_value:,}"
            else:
                old_display = f"{old_value}{unit}" if old_value is not None else "N/A"
                new_display = f"{new_value}{unit}"
            
            # Log the change
            logger.info(f"📱 CONFIG CHANGE: {attr_name} = {new_value} (was {old_value})")
            
            # Notify user
            self.send_message(
                f"✅ <b>{param_info['description'].upper()}</b> updated\n\n"
                f"Old: {old_display}\n"
                f"New: {new_display}\n\n"
                f"<i>⚠️ Affects new positions only.\n"
                f"Change is session-only (resets on restart).</i>"
            )
            
            # Queue for orchestrator awareness
            self.command_queue.put({
                'command': 'config_change',
                'param': param_name,
                'attr': attr_name,
                'old_value': old_value,
                'new_value': new_value
            })
            
        except Exception as e:
            logger.error(f"Error applying config change: {e}")
            self.send_message(f"❌ Failed to apply change: {e}")
    
    def set_config_reference(self, config):
        """
        Set reference to config object for runtime modification.

        Called by orchestrator during initialization.
        """
        self._config_ref = config
        logger.info("📱 Telegram config reference set - /config and /set commands enabled")

    def set_orchestrator_reference(self, orchestrator):
        """v3.5.0: Store orchestrator reference for phase-specific config access."""
        self._orchestrator_ref = orchestrator
        logger.info("📱 Telegram orchestrator reference set - phase config commands enabled")
    
    def get_pending_commands(self) -> List[Dict]:
        """
        Get all pending commands from the queue (non-blocking).
        Called by orchestrator in the main loop.
        
        Returns list of command dicts like:
            [{'command': 'freq', 'value': 15}, {'command': 'status'}, ...]
        """
        commands = []
        while not self.command_queue.empty():
            try:
                cmd = self.command_queue.get_nowait()
                commands.append(cmd)
            except queue.Empty:
                break
        return commands
