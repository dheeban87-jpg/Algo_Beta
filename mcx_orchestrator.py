"""
MCX_ORCHESTRATOR.PY - Phase 7 Lifecycle Coordinator
=====================================================

Manages the complete MCX paper trading lifecycle:
  15:30 → Activate, scan instruments, subscribe WebSocket
  17:00 → Evening session starts, enable strategies
  22:45 → Entry cutoff
  23:00 → Force close, daily summary, shutdown

Author: Dheebanraj + Claude
Version: 7.0.0
Date: 2026-02-16
"""

import time
import logging
import traceback
from datetime import datetime, time as dt_time, timedelta
from typing import Dict, List, Optional

import mcx_config as cfg
from mcx_scanner import MCXScanner
from mcx_signals import MCXSignalEngine, CandleBuilder, Indicators
from mcx_paper_trader import MCXPaperTrader

logger = logging.getLogger(__name__)


class MCXOrchestrator:
    """
    Phase 7 main coordinator.
    
    Lifecycle:
        1. Scan instruments
        2. Subscribe WebSocket for MCX ticks
        3. Build candles from ticks
        4. Run signal engine on completed candles
        5. Execute paper trades from signals
        6. Force close at EOD
        7. Generate daily summary
    """
    
    def __init__(self, kite, kws, telegram=None):
        """
        Args:
            kite: Authenticated KiteConnect instance
            kws: KiteTicker WebSocket instance
            telegram: Optional TelegramNotifier instance
        """
        self.kite = kite
        self.kws = kws
        self.telegram = telegram
        
        # Components
        self.scanner = MCXScanner(kite)
        self.signal_engine = MCXSignalEngine()
        self.candle_builder = CandleBuilder(
            interval_minutes=cfg.MCX_CANDLE_INTERVAL,
            max_candles=200
        )
        self.paper_trader = MCXPaperTrader(telegram)
        
        # State
        self.running = False
        self.token_map = {}           # instrument_token → symbol
        self.current_prices = {}      # symbol → latest LTP
        self.session_date = None
        self.evening_session_started = False
        self.orb_locked = False
        self.last_heartbeat = None
        self.tick_count = 0
        self.candles_completed = 0
    
    def run(self):
        """
        Main Phase 7 event loop.
        Runs from activation until MCX_HARD_STOP.
        """
        logger.info("")
        logger.info("╔══════════════════════════════════════════════════════════════════════╗")
        logger.info(f"║   PHASE 7: MCX COMMODITY PAPER TRADING v{cfg.MCX_VERSION:15s}              ║")
        logger.info(f"║   Codename: {cfg.MCX_CODENAME:30s}                         ║")
        logger.info("╚══════════════════════════════════════════════════════════════════════╝")
        logger.info("")
        logger.info(f"  Evening session:  {cfg.MCX_EVENING_SESSION_START.strftime('%H:%M')} - "
                    f"{cfg.MCX_FORCE_CLOSE.strftime('%H:%M')}")
        logger.info(f"  ORB window:       {cfg.ORB_WINDOW_START.strftime('%H:%M')} - "
                    f"{cfg.ORB_WINDOW_END.strftime('%H:%M')}")
        logger.info(f"  Entry cutoff:     {cfg.MCX_ENTRY_CUTOFF.strftime('%H:%M')}")
        logger.info(f"  Force close:      {cfg.MCX_FORCE_CLOSE.strftime('%H:%M')}")
        logger.info(f"  System shutdown:  {cfg.MCX_HARD_STOP.strftime('%H:%M')}")
        logger.info("")
        
        self.running = True
        self.session_date = datetime.now().date()
        
        # ─── Step 1: Scan instruments ─────────────────────────────────────
        
        scan_result = self.scanner.scan()
        self.token_map = {}
        
        for token, info in scan_result['token_map'].items():
            self.token_map[token] = info['symbol']
        
        if not self.token_map:
            logger.error("❌ No MCX instruments found — aborting Phase 7")
            self._notify("❌ Phase 7 ABORTED: No MCX instruments found")
            return
        
        # ─── Step 2: Reset strategies and paper trader ────────────────────
        
        self.signal_engine.reset_session()
        self.paper_trader.reset_daily()
        
        # ─── Step 3: Setup WebSocket callbacks ────────────────────────────
        
        tokens = list(self.token_map.keys())
        logger.info(f"  Subscribing to {len(tokens)} MCX tokens via WebSocket...")
        
        self._setup_websocket(tokens)
        
        # Start WebSocket connection in background thread (threaded=True)
        # This avoids the "signal only works in main thread" error
        logger.info("  Starting MCX WebSocket connection (threaded=True)...")
        self.kws.connect(threaded=True)
        
        # Wait for connection to establish
        time.sleep(3)
        logger.info("  ✅ WebSocket connection initiated")
        
        # ─── Step 4: Notify start ─────────────────────────────────────────
        
        instruments_str = ", ".join(sorted(set(self.token_map.values())))
        self._notify(
            f"{cfg.MCX_TELEGRAM_PREFIX} Phase 7 ACTIVATED\n\n"
            f"Mode: Paper Trading\n"
            f"Instruments: {len(self.token_map)}\n"
            f"Strategies: ORB + VWAP MR + RSI Zone\n"
            f"Session: {cfg.MCX_EVENING_SESSION_START.strftime('%H:%M')} - "
            f"{cfg.MCX_FORCE_CLOSE.strftime('%H:%M')}\n\n"
            f"Watching: {instruments_str}"
        )
        
        # ─── Step 5: Main event loop ──────────────────────────────────────
        
        logger.info("")
        logger.info("=" * 70)
        logger.info("PHASE 7 MAIN LOOP — Waiting for ticks...")
        logger.info("=" * 70)
        
        try:
            while self.running:
                now = datetime.now()
                current_time = now.time()
                
                # Hard stop check
                if current_time >= cfg.MCX_HARD_STOP:
                    logger.info("⏰ HARD STOP reached — shutting down Phase 7")
                    break
                
                # Force close check
                if current_time >= cfg.MCX_FORCE_CLOSE:
                    if self.paper_trader.open_positions_count() > 0:
                        logger.info("⏰ FORCE CLOSE time — closing all paper positions")
                        self.paper_trader.force_close_all(self.current_prices, now)
                
                # Evening session start detection
                if (current_time >= cfg.MCX_EVENING_SESSION_START and 
                        not self.evening_session_started):
                    self.evening_session_started = True
                    logger.info("")
                    logger.info("🌆 EVENING SESSION STARTED — All strategies active")
                    logger.info("=" * 70)
                
                # Heartbeat
                if (self.last_heartbeat is None or 
                        (now - self.last_heartbeat).total_seconds() >= 
                        cfg.MCX_HEARTBEAT_INTERVAL_MINUTES * 60):
                    self._send_heartbeat()
                    self.last_heartbeat = now
                
                # Sleep — ticks are processed via WebSocket callbacks
                time.sleep(cfg.MCX_SCAN_INTERVAL_SECONDS)
                
        except KeyboardInterrupt:
            logger.info("\n⛔ Phase 7 stopped by user (Ctrl+C)")
        except Exception as e:
            logger.error(f"❌ Phase 7 fatal error: {e}")
            logger.error(traceback.format_exc())
            self._notify(f"🚨 Phase 7 CRASH: {str(e)[:150]}")
        
        # ─── Step 6: Shutdown ─────────────────────────────────────────────
        
        self._shutdown()
    
    def _setup_websocket(self, tokens: List[int]):
        """
        Configure WebSocket callbacks for MCX tick processing.
        
        The KiteTicker instance is created in mcx_main.py.
        We assign our callbacks and subscribe to MCX tokens.
        """
        def on_ticks(ws, ticks):
            """Process incoming MCX ticks."""
            for tick in ticks:
                try:
                    self._process_tick(tick)
                except Exception as e:
                    logger.error(f"Tick processing error: {e}")
        
        def on_connect(ws, response):
            """Subscribe to MCX tokens on connect."""
            logger.info(f"  ✅ MCX WebSocket connected — subscribing {len(tokens)} tokens")
            ws.subscribe(tokens)
            ws.set_mode(ws.MODE_FULL, tokens)
            logger.info(f"  ✅ Subscribed in FULL mode")
        
        def on_close(ws, code, reason):
            """Handle disconnect."""
            logger.warning(f"  ⚠️  MCX WebSocket closed: code={code}, reason={reason}")
            if self.running:
                logger.info("  Attempting reconnect...")
        
        def on_error(ws, code, reason):
            """Handle errors."""
            logger.error(f"  ❌ MCX WebSocket error: code={code}, reason={reason}")
        
        self.kws.on_ticks = on_ticks
        self.kws.on_connect = on_connect
        self.kws.on_close = on_close
        self.kws.on_error = on_error
    
    def _process_tick(self, tick: dict):
        """
        Process a single MCX tick through the full pipeline.
        
        Flow: tick → candle builder → signal engine → paper trader
        """
        token = tick.get('instrument_token')
        symbol = self.token_map.get(token)
        if not symbol:
            return
        
        ltp = tick.get('last_price', 0)
        volume = tick.get('volume_traded', tick.get('volume', 0))
        oi = tick.get('oi', 0)
        tick_time = datetime.now()
        
        if ltp <= 0:
            return
        
        self.tick_count += 1
        self.current_prices[symbol] = ltp
        
        # ─── Paper trader: check open positions against live price ────────
        self.paper_trader.on_tick(symbol, ltp, tick_time)
        
        # ─── Candle builder: aggregate tick into 5-min candle ─────────────
        completed = self.candle_builder.on_tick(symbol, ltp, volume, oi, tick_time)
        
        if completed:
            self.candles_completed += 1
            all_candles = self.candle_builder.get_candles(symbol)
            candle_count = len(all_candles)
            
            # Log candle
            if self.candles_completed % 20 == 0 or candle_count <= 3:
                logger.info(f"  🕯️  {symbol:25s} | C={completed.close:.2f} "
                           f"| H={completed.high:.2f} L={completed.low:.2f} "
                           f"| Vol={completed.volume:,} | #{candle_count}")
            
            # ─── Time-based checks ────────────────────────────────────────
            now_time = tick_time.time()
            
            # ORB range: update during window, lock after
            if cfg.ORB_WINDOW_START <= now_time < cfg.ORB_WINDOW_END:
                self.signal_engine.orb.update_orb_range(symbol, completed)
            
            # ─── Signal engine: check all strategies ──────────────────────
            if candle_count >= cfg.RSI_PERIOD + 1:  # Need enough candles
                signals = self.signal_engine.on_candle(symbol, completed, all_candles)
                
                # Execute paper trades from signals
                for signal in signals:
                    self.paper_trader.execute_signal(signal)
    
    def _send_heartbeat(self):
        """Send periodic status update."""
        now = datetime.now()
        open_pos = self.paper_trader.open_positions_count()
        
        status = (f"Phase 7 Heartbeat | {now.strftime('%H:%M')} | "
                 f"Ticks: {self.tick_count:,} | "
                 f"Candles: {self.candles_completed} | "
                 f"Signals: {self.signal_engine.signals_generated} | "
                 f"Paper Trades: {self.paper_trader.daily_trades} | "
                 f"Open: {open_pos} | "
                 f"P&L: ₹{self.paper_trader.daily_pnl:+,.2f}")
        
        logger.info(f"  💓 {status}")
        
        # Cycle summary for all symbols
        if self.evening_session_started:
            self._log_cycle_summary()
    
    def _log_cycle_summary(self):
        """Log current state of all monitored symbols."""
        logger.info(f"\n  {'Symbol':25s} | {'Price':>10s} | {'RSI':>6s} | {'VWAP':>10s} | "
                    f"{'ORB State':20s} | {'RSI Zone':20s}")
        logger.info(f"  {'-'*100}")
        
        for token, symbol in sorted(self.token_map.items(), key=lambda x: x[1]):
            price = self.current_prices.get(symbol, 0)
            all_candles = self.candle_builder.get_candles(symbol)
            
            # RSI
            rsi_val = Indicators.rsi(all_candles, cfg.RSI_PERIOD) if len(all_candles) > cfg.RSI_PERIOD else None
            rsi_str = f"{rsi_val:5.1f}" if rsi_val else "  N/A"
            
            # VWAP
            session_candles = [c for c in all_candles if c.timestamp.time() >= cfg.VWAP_RESET_TIME]
            vwap_val, _ = Indicators.vwap(session_candles) if session_candles else (None, None)
            vwap_str = f"{vwap_val:>10.2f}" if vwap_val else "       N/A"
            
            # ORB state
            orb = self.signal_engine.orb.orb_ranges.get(symbol, {})
            if orb.get('locked'):
                orb_str = f"H={orb['high']:.1f} L={orb['low']:.1f}"
            elif orb:
                orb_str = f"Building..."
            else:
                orb_str = "Not started"
            
            # RSI Zone state
            rsi_state = self.signal_engine.rsi_zone.get_state_display(symbol)
            
            logger.info(f"  {symbol:25s} | {price:>10.2f} | {rsi_str} | {vwap_str} | "
                       f"{orb_str:20s} | {rsi_state}")
    
    def _shutdown(self):
        """Clean shutdown of Phase 7."""
        self.running = False
        
        logger.info("")
        logger.info("=" * 70)
        logger.info("PHASE 7 SHUTDOWN")
        logger.info("=" * 70)
        
        # Force close remaining positions
        if self.paper_trader.open_positions_count() > 0:
            self.paper_trader.force_close_all(self.current_prices, datetime.now())
        
        # Daily summary
        self.paper_trader.send_daily_summary()
        
        # System stats
        logger.info(f"\n  Session stats:")
        logger.info(f"    Total ticks processed: {self.tick_count:,}")
        logger.info(f"    Candles completed:     {self.candles_completed}")
        logger.info(f"    Signals generated:     {self.signal_engine.signals_generated}")
        logger.info(f"    Paper trades:          {self.paper_trader.daily_trades}")
        
        # Disconnect WebSocket
        try:
            self.kws.close()
            logger.info("  ✅ WebSocket closed")
        except:
            pass
        
        self._notify(
            f"{cfg.MCX_TELEGRAM_PREFIX} Phase 7 SHUTDOWN\n\n"
            f"Ticks: {self.tick_count:,}\n"
            f"Candles: {self.candles_completed}\n"
            f"Signals: {self.signal_engine.signals_generated}\n"
            f"Trades: {self.paper_trader.daily_trades}"
        )
        
        logger.info("")
        logger.info("Phase 7 shutdown complete.")
    
    def _notify(self, message: str):
        """Send Telegram notification."""
        if self.telegram:
            try:
                self.telegram.send_message(message)
            except Exception as e:
                logger.warning(f"  Telegram notify failed: {e}")
