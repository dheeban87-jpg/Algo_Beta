"""
MCX_PAPER_TRADER.PY - Phase 7.3: Virtual Execution Engine
===========================================================

Tracks paper trades from signal engine. No real orders.
Logs all trades to CSV, sends Telegram notifications,
generates daily P&L summaries.

Author: Dheebanraj + Claude
Version: 7.0.0
Date: 2026-02-16
"""

import os
import csv
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from dataclasses import dataclass, field
from collections import defaultdict

import mcx_config as cfg
from mcx_signals import Signal

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# DATA STRUCTURES
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class PaperPosition:
    """A virtual paper trade position."""
    id: int
    signal: Signal
    entry_time: datetime
    entry_price: float
    stop_loss: float
    target: float
    direction: str            # 'BUY' or 'SELL'
    symbol: str
    strategy: str
    trailing_stop: float = 0  # Updated trailing stop
    highest_price: float = 0  # For trailing (longs)
    lowest_price: float = 0   # For trailing (shorts)
    exit_time: Optional[datetime] = None
    exit_price: Optional[float] = None
    exit_reason: Optional[str] = None
    pnl: float = 0
    
    @property
    def is_open(self) -> bool:
        return self.exit_time is None


# ═══════════════════════════════════════════════════════════════════════════════
# PAPER TRADER
# ═══════════════════════════════════════════════════════════════════════════════

class MCXPaperTrader:
    """
    Virtual trade execution and tracking engine.
    
    Takes signals from MCXSignalEngine, creates paper positions,
    monitors them against live ticks, and tracks P&L.
    """
    
    def __init__(self, telegram=None):
        """
        Args:
            telegram: Optional TelegramNotifier instance
        """
        self.telegram = telegram
        self.positions: List[PaperPosition] = []
        self.closed_trades: List[PaperPosition] = []
        self.next_id = 1
        
        # Daily stats
        self.daily_pnl = 0
        self.daily_trades = 0
        self.daily_wins = 0
        self.daily_losses = 0
        self.daily_stopped = False  # Stops trading after max daily loss
        
        # Per-strategy stats
        self.strategy_stats: Dict[str, dict] = defaultdict(
            lambda: {'trades': 0, 'wins': 0, 'losses': 0, 'pnl': 0}
        )
        
        # Ensure data directories exist
        os.makedirs(os.path.dirname(cfg.MCX_PAPER_TRADES_CSV), exist_ok=True)
        os.makedirs(cfg.MCX_CANDLE_CACHE_DIR, exist_ok=True)
        
        # Initialize CSV if not exists
        self._init_csv()
    
    def _init_csv(self):
        """Create CSV with headers if it doesn't exist."""
        if not os.path.exists(cfg.MCX_PAPER_TRADES_CSV):
            with open(cfg.MCX_PAPER_TRADES_CSV, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow([
                    'date', 'id', 'symbol', 'strategy', 'direction',
                    'entry_price', 'exit_price', 'stop_loss', 'target',
                    'entry_time', 'exit_time', 'exit_reason',
                    'pnl', 'hold_duration_min', 'confidence', 'reason'
                ])
    
    def reset_daily(self):
        """Reset daily counters for new session."""
        self.daily_pnl = 0
        self.daily_trades = 0
        self.daily_wins = 0
        self.daily_losses = 0
        self.daily_stopped = False
        self.strategy_stats.clear()
        logger.info("  Paper trader: daily stats reset")
    
    def open_positions_count(self) -> int:
        """Number of currently open paper positions."""
        return sum(1 for p in self.positions if p.is_open)
    
    def execute_signal(self, signal: Signal) -> Optional[PaperPosition]:
        """
        Create a paper position from a signal.
        
        Args:
            signal: Signal from the signal engine
            
        Returns:
            PaperPosition if opened, None if rejected
        """
        # Pre-checks
        if self.daily_stopped:
            logger.info(f"  ⛔ PAPER REJECTED {signal.symbol}: Daily loss limit reached")
            return None
        
        if self.open_positions_count() >= cfg.MCX_MAX_PAPER_POSITIONS:
            logger.info(f"  ⛔ PAPER REJECTED {signal.symbol}: Max positions ({cfg.MCX_MAX_PAPER_POSITIONS}) reached")
            return None
        
        # Check for duplicate — no same symbol + same strategy already open
        for p in self.positions:
            if p.is_open and p.symbol == signal.symbol and p.strategy == signal.strategy:
                logger.info(f"  ⛔ PAPER REJECTED {signal.symbol}: Already have open {signal.strategy} position")
                return None
        
        # Create paper position
        pos = PaperPosition(
            id=self.next_id,
            signal=signal,
            entry_time=signal.timestamp,
            entry_price=signal.entry_price,
            stop_loss=signal.stop_loss,
            target=signal.target,
            direction=signal.direction,
            symbol=signal.symbol,
            strategy=signal.strategy,
            trailing_stop=signal.stop_loss,
            highest_price=signal.entry_price,
            lowest_price=signal.entry_price,
        )
        self.next_id += 1
        self.positions.append(pos)
        
        # Notify
        dir_emoji = "🟢" if signal.direction == 'BUY' else "🔴"
        msg = (f"{cfg.MCX_TELEGRAM_PREFIX} PAPER {dir_emoji} {signal.direction}\n\n"
               f"Symbol: {signal.symbol}\n"
               f"Strategy: {signal.strategy}\n"
               f"Entry: ₹{signal.entry_price:,.2f}\n"
               f"Stop: ₹{signal.stop_loss:,.2f}\n"
               f"Target: ₹{signal.target:,.2f}\n"
               f"Confidence: {signal.confidence}/100\n\n"
               f"Reason: {signal.reason}")
        
        logger.info(f"  📝 PAPER OPENED #{pos.id}: {signal.direction} {signal.symbol} "
                    f"@ {signal.entry_price:.2f} | {signal.strategy}")
        
        if self.telegram and cfg.MCX_NOTIFY_PAPER_TRADES:
            try:
                self.telegram.send_message(msg)
            except Exception as e:
                logger.warning(f"  Telegram send failed: {e}")
        
        return pos
    
    def on_tick(self, symbol: str, ltp: float, tick_time: datetime):
        """
        Check all open positions against current price.
        
        Args:
            symbol: Trading symbol
            ltp: Last traded price
            tick_time: Current time
        """
        for pos in self.positions:
            if not pos.is_open or pos.symbol != symbol:
                continue
            
            # Update price tracking
            if pos.direction == 'BUY':
                pos.highest_price = max(pos.highest_price, ltp)
                
                # Trailing stop — move to breakeven after 1x range
                if cfg.ORB_TRAIL_AT_1X and pos.strategy == 'ORB':
                    range_width = pos.signal.metadata.get('range_width', 0)
                    if range_width > 0 and ltp >= pos.entry_price + range_width:
                        new_trail = max(pos.trailing_stop, pos.entry_price)
                        if new_trail > pos.trailing_stop:
                            pos.trailing_stop = new_trail
                            logger.info(f"  📈 TRAIL #{pos.id}: Stop moved to breakeven {new_trail:.2f}")
                
                effective_stop = max(pos.stop_loss, pos.trailing_stop)
                
                # Check stop
                if ltp <= effective_stop:
                    self._close_position(pos, ltp, tick_time, 'STOP_LOSS')
                # Check target
                elif ltp >= pos.target:
                    self._close_position(pos, ltp, tick_time, 'TARGET_HIT')
            
            else:  # SELL
                pos.lowest_price = min(pos.lowest_price, ltp)
                
                effective_stop = pos.stop_loss  # No trailing for shorts yet
                
                if ltp >= effective_stop:
                    self._close_position(pos, ltp, tick_time, 'STOP_LOSS')
                elif ltp <= pos.target:
                    self._close_position(pos, ltp, tick_time, 'TARGET_HIT')
            
            # Timeout check
            if pos.is_open:
                hold_minutes = (tick_time - pos.entry_time).total_seconds() / 60
                if hold_minutes >= cfg.MCX_POSITION_TIMEOUT_MINUTES:
                    self._close_position(pos, ltp, tick_time, 'TIMEOUT')
    
    def _close_position(self, pos: PaperPosition, exit_price: float, 
                         exit_time: datetime, reason: str):
        """Close a paper position and record results."""
        pos.exit_time = exit_time
        pos.exit_price = exit_price
        pos.exit_reason = reason
        
        # Calculate P&L
        if pos.direction == 'BUY':
            pos.pnl = exit_price - pos.entry_price
        else:
            pos.pnl = pos.entry_price - exit_price
        
        # Update daily stats
        self.daily_trades += 1
        self.daily_pnl += pos.pnl
        
        is_win = pos.pnl > 0
        if is_win:
            self.daily_wins += 1
        else:
            self.daily_losses += 1
        
        # Strategy stats
        stats = self.strategy_stats[pos.strategy]
        stats['trades'] += 1
        stats['pnl'] += pos.pnl
        if is_win:
            stats['wins'] += 1
        else:
            stats['losses'] += 1
        
        self.closed_trades.append(pos)
        
        # Check daily loss limit
        if self.daily_pnl <= -cfg.MCX_MAX_DAILY_LOSS:
            self.daily_stopped = True
            logger.warning(f"  ⛔ DAILY LOSS LIMIT: ₹{self.daily_pnl:,.2f} — stopping paper trading")
        
        # Log
        hold_minutes = (exit_time - pos.entry_time).total_seconds() / 60
        result_emoji = "✅" if is_win else "❌"
        pnl_sign = "+" if pos.pnl >= 0 else ""
        
        logger.info(f"  {result_emoji} PAPER CLOSED #{pos.id}: {pos.symbol} | "
                    f"{pos.strategy} | {reason} | P&L: {pnl_sign}₹{pos.pnl:,.2f} | "
                    f"Hold: {hold_minutes:.0f}min")
        
        # Telegram
        msg = (f"{cfg.MCX_TELEGRAM_PREFIX} PAPER {result_emoji} {'WIN' if is_win else 'LOSS'}\n\n"
               f"Symbol: {pos.symbol}\n"
               f"Strategy: {pos.strategy}\n"
               f"Direction: {pos.direction}\n"
               f"Entry: ₹{pos.entry_price:,.2f}\n"
               f"Exit: ₹{exit_price:,.2f}\n"
               f"P&L: {pnl_sign}₹{pos.pnl:,.2f}\n"
               f"Reason: {reason}\n"
               f"Hold: {hold_minutes:.0f} min\n\n"
               f"Daily: {self.daily_wins}W/{self.daily_losses}L "
               f"| Net: {'+' if self.daily_pnl >= 0 else ''}₹{self.daily_pnl:,.2f}")
        
        if self.telegram and cfg.MCX_NOTIFY_PAPER_TRADES:
            try:
                self.telegram.send_message(msg)
            except Exception as e:
                logger.warning(f"  Telegram send failed: {e}")
        
        # Write to CSV
        self._write_trade_csv(pos)
    
    def _write_trade_csv(self, pos: PaperPosition):
        """Append closed trade to CSV."""
        try:
            hold_min = (pos.exit_time - pos.entry_time).total_seconds() / 60 if pos.exit_time else 0
            
            with open(cfg.MCX_PAPER_TRADES_CSV, 'a', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow([
                    pos.entry_time.strftime('%Y-%m-%d'),
                    pos.id,
                    pos.symbol,
                    pos.strategy,
                    pos.direction,
                    f"{pos.entry_price:.2f}",
                    f"{pos.exit_price:.2f}" if pos.exit_price else '',
                    f"{pos.stop_loss:.2f}",
                    f"{pos.target:.2f}",
                    pos.entry_time.strftime('%H:%M:%S'),
                    pos.exit_time.strftime('%H:%M:%S') if pos.exit_time else '',
                    pos.exit_reason or '',
                    f"{pos.pnl:.2f}",
                    f"{hold_min:.1f}",
                    pos.signal.confidence,
                    pos.signal.reason,
                ])
        except Exception as e:
            logger.error(f"  CSV write failed: {e}")
    
    def force_close_all(self, current_prices: Dict[str, float], close_time: datetime):
        """Force close all open positions (EOD)."""
        open_count = self.open_positions_count()
        if open_count == 0:
            return
        
        logger.info(f"\n  ⏰ FORCE CLOSING {open_count} open paper positions")
        
        for pos in self.positions:
            if pos.is_open:
                price = current_prices.get(pos.symbol, pos.entry_price)
                self._close_position(pos, price, close_time, 'EOD_FORCE_CLOSE')
    
    def get_daily_summary(self) -> str:
        """Generate daily summary string."""
        lines = []
        lines.append(f"{cfg.MCX_TELEGRAM_PREFIX} MCX PAPER TRADING SUMMARY")
        lines.append(f"Date: {datetime.now().strftime('%Y-%m-%d')}")
        lines.append("")
        
        # Overall
        pnl_sign = "+" if self.daily_pnl >= 0 else ""
        lines.append(f"Total: {self.daily_trades} trades | "
                     f"{self.daily_wins}W/{self.daily_losses}L | "
                     f"P&L: {pnl_sign}₹{self.daily_pnl:,.2f}")
        
        if self.daily_trades > 0:
            win_rate = (self.daily_wins / self.daily_trades) * 100
            lines.append(f"Win Rate: {win_rate:.0f}%")
        
        lines.append("")
        
        # Per strategy
        for strategy, stats in sorted(self.strategy_stats.items()):
            pnl_sign = "+" if stats['pnl'] >= 0 else ""
            lines.append(f"  {strategy:10s}: {stats['trades']}T | "
                        f"{stats['wins']}W/{stats['losses']}L | "
                        f"P&L: {pnl_sign}₹{stats['pnl']:,.2f}")
        
        if not self.strategy_stats:
            lines.append("  No trades today")
        
        # Open positions warning
        open_count = self.open_positions_count()
        if open_count > 0:
            lines.append(f"\n⚠️ {open_count} positions still open!")
        
        return "\n".join(lines)
    
    def send_daily_summary(self):
        """Send daily summary via Telegram and log."""
        summary = self.get_daily_summary()
        logger.info("")
        logger.info("=" * 70)
        for line in summary.split('\n'):
            logger.info(f"  {line}")
        logger.info("=" * 70)
        
        if self.telegram and cfg.MCX_NOTIFY_DAILY_SUMMARY:
            try:
                self.telegram.send_message(summary)
            except Exception as e:
                logger.warning(f"  Telegram summary send failed: {e}")
        
        # Append to daily summary CSV
        self._write_daily_summary_csv()
    
    def _write_daily_summary_csv(self):
        """Append daily summary to CSV."""
        try:
            file_exists = os.path.exists(cfg.MCX_DAILY_SUMMARY_CSV)
            
            with open(cfg.MCX_DAILY_SUMMARY_CSV, 'a', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                if not file_exists:
                    writer.writerow([
                        'date', 'total_trades', 'wins', 'losses', 'daily_pnl',
                        'win_rate', 'orb_trades', 'orb_pnl', 'vwap_trades', 'vwap_pnl',
                        'rsi_trades', 'rsi_pnl'
                    ])
                
                orb = self.strategy_stats.get('ORB', {'trades': 0, 'pnl': 0})
                vwap = self.strategy_stats.get('VWAP_MR', {'trades': 0, 'pnl': 0})
                rsi = self.strategy_stats.get('RSI_ZONE', {'trades': 0, 'pnl': 0})
                win_rate = (self.daily_wins / max(self.daily_trades, 1)) * 100
                
                writer.writerow([
                    datetime.now().strftime('%Y-%m-%d'),
                    self.daily_trades, self.daily_wins, self.daily_losses,
                    f"{self.daily_pnl:.2f}", f"{win_rate:.1f}",
                    orb['trades'], f"{orb['pnl']:.2f}",
                    vwap['trades'], f"{vwap['pnl']:.2f}",
                    rsi['trades'], f"{rsi['pnl']:.2f}",
                ])
        except Exception as e:
            logger.error(f"  Daily summary CSV write failed: {e}")
