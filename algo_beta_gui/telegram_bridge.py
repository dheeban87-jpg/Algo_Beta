"""
Algo_Beta GUI — Telegram Command Bridge
=========================================
Formats GUI actions into the same /set command format your Telegram bot uses.
In mock mode: logs commands to console + command_log list.
In live mode: wire send_command() to your Telegram bot's command handler.

Usage:
    from telegram_bridge import TelegramBridge
    bridge = TelegramBridge()
    bridge.send_command("/set min_score 75")
    bridge.get_log()  # Returns list of sent commands
"""

import datetime


class TelegramBridge:
    """
    Routes GUI config changes through the same command pathway as Telegram /set.
    
    WIRING TO LIVE SYSTEM:
    ──────────────────────
    Option A — Direct function call:
        Replace send_command() body with a call to the same handler
        your Telegram bot's /set dispatcher calls, e.g.:
            from telegram_command_handler import handle_set_command
            handle_set_command(command_text)
    
    Option B — Telegram Bot API:
        Post directly to your bot using python-telegram-bot:
            bot.send_message(chat_id=YOUR_CHAT_ID, text=command_text)
    
    Option C — Shared SQLite command queue:
        Write to a 'pending_commands' table that the trading loop polls.
    """

    def __init__(self):
        self._log = []
        self._callbacks = []  # Optional: register listeners for UI updates

    def send_command(self, command_text):
        """
        Send a Telegram-style command.
        
        Args:
            command_text: Full command string, e.g. "/set min_score 75"
        
        Returns:
            dict with status and timestamp
        """
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        entry = {
            "timestamp": timestamp,
            "command": command_text,
            "status": "SENT (mock)",
        }
        self._log.append(entry)
        
        # ── MOCK MODE: Print to console ──
        print(f"[TG-BRIDGE] {timestamp} → {command_text}")
        
        # ── Notify registered callbacks ──
        for callback in self._callbacks:
            try:
                callback(entry)
            except Exception as e:
                print(f"[TG-BRIDGE] Callback error: {e}")

        return entry

    # ── Convenience methods matching your Telegram /set patterns ──

    def set_config(self, key, value):
        """Send /set key value command."""
        return self.send_command(f"/set {key} {value}")

    def enable_phase(self, phase_key, enabled):
        """Toggle a phase enable flag."""
        val = "true" if enabled else "false"
        return self.send_command(f"/set {phase_key} {val}")

    def set_capital(self, field, amount):
        """Update capital configuration."""
        return self.send_command(f"/set {field} {amount}")

    def set_rsi_override(self, symbol, rsi_value):
        """Set stock-specific RSI threshold."""
        return self.send_command(f"/set rsi_override {symbol} {rsi_value}")

    def remove_rsi_override(self, symbol):
        """Remove stock-specific RSI override."""
        return self.send_command(f"/remove rsi_override {symbol}")

    def system_start(self):
        """Send system start command."""
        return self.send_command("/start")

    def system_stop(self):
        """Send system stop command."""
        return self.send_command("/stop")

    def request_status(self):
        """Request current system status."""
        return self.send_command("/status")

    def toggle_mis(self, enabled):
        """Toggle MIS (intraday) mode."""
        val = "on" if enabled else "off"
        return self.send_command(f"/mis {val}")

    # ── Log & Callback Management ──

    def get_log(self, last_n=50):
        """Return last N command log entries."""
        return self._log[-last_n:]

    def clear_log(self):
        """Clear command log."""
        self._log.clear()

    def register_callback(self, callback_fn):
        """Register a function to be called on every command sent."""
        self._callbacks.append(callback_fn)

    def unregister_callback(self, callback_fn):
        """Remove a registered callback."""
        self._callbacks = [cb for cb in self._callbacks if cb != callback_fn]
