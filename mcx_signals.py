"""
MCX_SIGNALS.PY - Phase 7.2: MCX Signal Generation Engine
==========================================================

Three strategies running in parallel on 5-minute MCX candles:
  S1: Opening Range Breakout (ORB)
  S2: VWAP Mean Reversion
  S3: RSI Zone Tracker (Kalman-smoothed)

Each strategy independently generates signals. The paper trader
tracks all of them to determine which works best per commodity.

Author: Dheebanraj + Claude
Version: 7.0.0
Date: 2026-02-16
"""

import math
import logging
from datetime import datetime, time as dt_time, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from collections import defaultdict

import mcx_config as cfg

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# DATA STRUCTURES
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class Candle:
    """5-minute OHLCV candle."""
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int
    oi: int = 0


@dataclass
class Signal:
    """Trading signal output."""
    strategy: str         # 'ORB', 'VWAP_MR', 'RSI_ZONE'
    symbol: str           # e.g., 'GOLDPETAL26FEBFUT'
    direction: str        # 'BUY' or 'SELL'
    entry_price: float
    stop_loss: float
    target: float
    confidence: int       # 0-100
    timestamp: datetime
    reason: str
    metadata: dict = field(default_factory=dict)


# ═══════════════════════════════════════════════════════════════════════════════
# CANDLE BUILDER — Converts WebSocket ticks into 5-minute candles
# ═══════════════════════════════════════════════════════════════════════════════

class CandleBuilder:
    """
    Aggregates WebSocket ticks into 5-minute OHLCV candles.
    Maintains rolling candle history per symbol.
    """
    
    def __init__(self, interval_minutes: int = 5, max_candles: int = 200):
        self.interval = interval_minutes
        self.max_candles = max_candles
        
        # Per-symbol state
        self.current_candle: Dict[str, dict] = {}   # Building candle
        self.candles: Dict[str, List[Candle]] = defaultdict(list)  # Completed candles
    
    def on_tick(self, symbol: str, ltp: float, volume: int, oi: int, tick_time: datetime) -> Optional[Candle]:
        """
        Process a tick. Returns completed Candle when interval boundary crossed.
        
        Args:
            symbol: Trading symbol
            ltp: Last traded price
            volume: Cumulative volume
            oi: Open interest
            tick_time: Tick timestamp
            
        Returns:
            Completed Candle if interval boundary crossed, else None
        """
        # Calculate candle bucket
        minute = tick_time.minute
        bucket_minute = (minute // self.interval) * self.interval
        bucket_time = tick_time.replace(minute=bucket_minute, second=0, microsecond=0)
        
        current = self.current_candle.get(symbol)
        completed = None
        
        # Check if we've crossed into a new candle
        if current and current['bucket'] != bucket_time:
            # Finalize previous candle
            completed = Candle(
                timestamp=current['bucket'],
                open=current['open'],
                high=current['high'],
                low=current['low'],
                close=current['close'],
                volume=current['volume_end'] - current['volume_start'],
                oi=current['oi'],
            )
            self.candles[symbol].append(completed)
            
            # Trim history
            if len(self.candles[symbol]) > self.max_candles:
                self.candles[symbol] = self.candles[symbol][-self.max_candles:]
            
            # Start new candle
            self.current_candle[symbol] = {
                'bucket': bucket_time,
                'open': ltp,
                'high': ltp,
                'low': ltp,
                'close': ltp,
                'volume_start': volume,
                'volume_end': volume,
                'oi': oi,
            }
        elif current:
            # Update existing candle
            current['high'] = max(current['high'], ltp)
            current['low'] = min(current['low'], ltp)
            current['close'] = ltp
            current['volume_end'] = volume
            current['oi'] = oi
        else:
            # First tick for this symbol
            self.current_candle[symbol] = {
                'bucket': bucket_time,
                'open': ltp,
                'high': ltp,
                'low': ltp,
                'close': ltp,
                'volume_start': volume,
                'volume_end': volume,
                'oi': oi,
            }
        
        return completed
    
    def get_candles(self, symbol: str, count: int = 0) -> List[Candle]:
        """Get completed candles for a symbol."""
        candles = self.candles.get(symbol, [])
        if count > 0:
            return candles[-count:]
        return candles
    
    def get_current_price(self, symbol: str) -> Optional[float]:
        """Get the latest tick price for a symbol."""
        current = self.current_candle.get(symbol)
        return current['close'] if current else None
    
    def candle_count(self, symbol: str) -> int:
        """Number of completed candles for a symbol."""
        return len(self.candles.get(symbol, []))


# ═══════════════════════════════════════════════════════════════════════════════
# TECHNICAL INDICATORS
# ═══════════════════════════════════════════════════════════════════════════════

class Indicators:
    """Technical indicator calculations on candle data."""
    
    @staticmethod
    def rsi(candles: List[Candle], period: int = 14) -> Optional[float]:
        """Calculate RSI using Wilder's smoothing."""
        if len(candles) < period + 1:
            return None
        
        closes = [c.close for c in candles]
        deltas = [closes[i] - closes[i-1] for i in range(1, len(closes))]
        
        gains = [d if d > 0 else 0 for d in deltas[:period]]
        losses = [-d if d < 0 else 0 for d in deltas[:period]]
        
        avg_gain = sum(gains) / period
        avg_loss = sum(losses) / period
        
        # Wilder's smoothing for remaining
        for d in deltas[period:]:
            gain = d if d > 0 else 0
            loss = -d if d < 0 else 0
            avg_gain = (avg_gain * (period - 1) + gain) / period
            avg_loss = (avg_loss * (period - 1) + loss) / period
        
        if avg_loss == 0:
            return 100.0
        
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))
    
    @staticmethod
    def vwap(candles: List[Candle]) -> Tuple[Optional[float], Optional[float]]:
        """
        Calculate VWAP and standard deviation.
        
        Returns:
            (vwap_value, std_dev) or (None, None)
        """
        if not candles:
            return None, None
        
        cum_tp_vol = 0
        cum_vol = 0
        tp_values = []
        
        for c in candles:
            tp = (c.high + c.low + c.close) / 3
            vol = max(c.volume, 1)  # Avoid zero division
            cum_tp_vol += tp * vol
            cum_vol += vol
            tp_values.append(tp)
        
        if cum_vol == 0:
            return None, None
        
        vwap_val = cum_tp_vol / cum_vol
        
        # Standard deviation of typical price from VWAP
        if len(tp_values) > 1:
            variance = sum((tp - vwap_val) ** 2 for tp in tp_values) / len(tp_values)
            std = math.sqrt(variance) if variance > 0 else 0
        else:
            std = 0
        
        return vwap_val, std
    
    @staticmethod
    def avg_volume(candles: List[Candle], period: int = 20) -> float:
        """Average volume over last N candles."""
        recent = candles[-period:] if len(candles) >= period else candles
        if not recent:
            return 0
        return sum(c.volume for c in recent) / len(recent)
    
    @staticmethod
    def kalman_smooth(value: float, state: dict) -> Tuple[float, float]:
        """
        Simple Kalman filter for RSI smoothing.
        
        Args:
            value: Raw RSI value
            state: Dict with 'estimate', 'error' (modified in-place)
            
        Returns:
            (smoothed_value, velocity)
        """
        Q = cfg.KALMAN_Q  # Process noise
        R = cfg.KALMAN_R  # Measurement noise
        
        if 'estimate' not in state:
            state['estimate'] = value
            state['error'] = 1.0
            state['prev_estimate'] = value
            return value, 0.0
        
        # Predict
        pred_estimate = state['estimate']
        pred_error = state['error'] + Q
        
        # Update
        kalman_gain = pred_error / (pred_error + R)
        new_estimate = pred_estimate + kalman_gain * (value - pred_estimate)
        new_error = (1 - kalman_gain) * pred_error
        
        # Velocity
        velocity = new_estimate - state['estimate']
        
        state['prev_estimate'] = state['estimate']
        state['estimate'] = new_estimate
        state['error'] = new_error
        
        return new_estimate, velocity


# ═══════════════════════════════════════════════════════════════════════════════
# STRATEGY S1: OPENING RANGE BREAKOUT
# ═══════════════════════════════════════════════════════════════════════════════

class ORBStrategy:
    """
    Opening Range Breakout for MCX evening session.
    
    Logic:
        17:00-17:15 → Record high/low of opening range
        17:15+      → Signal on breakout above/below range with volume
    """
    
    def __init__(self):
        self.name = 'ORB'
        # Per-symbol ORB state
        self.orb_ranges: Dict[str, dict] = {}  # symbol → {high, low, locked, trades}
    
    def reset_session(self):
        """Reset for new evening session."""
        self.orb_ranges.clear()
    
    def update_orb_range(self, symbol: str, candle: Candle):
        """Update ORB range during the opening window."""
        now = candle.timestamp.time()
        
        if now < cfg.ORB_WINDOW_START or now >= cfg.ORB_WINDOW_END:
            return
        
        if symbol not in self.orb_ranges:
            self.orb_ranges[symbol] = {
                'high': candle.high,
                'low': candle.low,
                'locked': False,
                'trades': 0,
            }
        else:
            orb = self.orb_ranges[symbol]
            if not orb['locked']:
                orb['high'] = max(orb['high'], candle.high)
                orb['low'] = min(orb['low'], candle.low)
    
    def lock_range(self, symbol: str):
        """Lock the ORB range after window closes."""
        if symbol in self.orb_ranges:
            orb = self.orb_ranges[symbol]
            orb['locked'] = True
            range_width = orb['high'] - orb['low']
            range_pct = (range_width / orb['low']) * 100 if orb['low'] > 0 else 0
            logger.info(f"  🔒 ORB LOCKED {symbol}: High={orb['high']:.2f} "
                       f"Low={orb['low']:.2f} Range={range_width:.2f} ({range_pct:.2f}%)")
    
    def check_signal(self, symbol: str, candle: Candle, avg_vol: float) -> Optional[Signal]:
        """
        Check for ORB breakout signal.
        
        Args:
            symbol: Trading symbol
            candle: Latest completed 5-min candle
            avg_vol: Average volume for volume confirmation
        """
        orb = self.orb_ranges.get(symbol)
        if not orb or not orb['locked']:
            return None
        
        # Max trades check
        if orb['trades'] >= cfg.ORB_MAX_TRADES_PER_SESSION:
            return None
        
        # Range validation
        range_width = orb['high'] - orb['low']
        mid_price = (orb['high'] + orb['low']) / 2
        range_pct = (range_width / mid_price) * 100 if mid_price > 0 else 0
        
        if range_pct < cfg.ORB_MIN_RANGE_PCT:
            return None  # Too narrow
        if range_pct > cfg.ORB_MAX_RANGE_PCT:
            return None  # Too wide
        
        # Volume confirmation
        vol_ratio = candle.volume / max(avg_vol, 1)
        has_volume = vol_ratio >= cfg.ORB_VOLUME_MULTIPLIER
        
        # Breakout detection — candle CLOSES beyond range
        if candle.close > orb['high'] and has_volume:
            # Bullish breakout
            entry = candle.close
            stop = orb['low']
            target = entry + (range_width * cfg.ORB_TARGET_MULTIPLIER)
            confidence = min(90, int(50 + vol_ratio * 15 + range_pct * 5))
            
            orb['trades'] += 1
            return Signal(
                strategy=self.name,
                symbol=symbol,
                direction='BUY',
                entry_price=entry,
                stop_loss=stop,
                target=target,
                confidence=confidence,
                timestamp=candle.timestamp,
                reason=f"ORB breakout above {orb['high']:.2f} | Vol {vol_ratio:.1f}x | Range {range_pct:.1f}%",
                metadata={'range_width': range_width, 'vol_ratio': vol_ratio},
            )
        
        elif candle.close < orb['low'] and has_volume:
            # Bearish breakout
            entry = candle.close
            stop = orb['high']
            target = entry - (range_width * cfg.ORB_TARGET_MULTIPLIER)
            confidence = min(90, int(50 + vol_ratio * 15 + range_pct * 5))
            
            orb['trades'] += 1
            return Signal(
                strategy=self.name,
                symbol=symbol,
                direction='SELL',
                entry_price=entry,
                stop_loss=stop,
                target=target,
                confidence=confidence,
                timestamp=candle.timestamp,
                reason=f"ORB breakdown below {orb['low']:.2f} | Vol {vol_ratio:.1f}x | Range {range_pct:.1f}%",
                metadata={'range_width': range_width, 'vol_ratio': vol_ratio},
            )
        
        return None


# ═══════════════════════════════════════════════════════════════════════════════
# STRATEGY S2: VWAP MEAN REVERSION
# ═══════════════════════════════════════════════════════════════════════════════

class VWAPMeanReversionStrategy:
    """
    VWAP Mean Reversion for MCX evening session.
    
    Logic:
        Track VWAP from evening session start (17:00)
        When price deviates > 1.5σ from VWAP + RSI confirms → enter reversion
        Target: VWAP, Stop: 2σ beyond entry deviation
    """
    
    def __init__(self):
        self.name = 'VWAP_MR'
        self.session_candles: Dict[str, List[Candle]] = defaultdict(list)
        self.trade_counts: Dict[str, int] = defaultdict(int)
    
    def reset_session(self):
        """Reset for new evening session."""
        self.session_candles.clear()
        self.trade_counts.clear()
    
    def add_candle(self, symbol: str, candle: Candle):
        """Add candle to session tracking (only evening session candles)."""
        if candle.timestamp.time() >= cfg.VWAP_RESET_TIME:
            self.session_candles[symbol].append(candle)
    
    def check_signal(self, symbol: str, candle: Candle, rsi: Optional[float]) -> Optional[Signal]:
        """
        Check for VWAP mean reversion signal.
        
        Args:
            symbol: Trading symbol
            candle: Latest completed 5-min candle
            rsi: Current RSI value (14-period)
        """
        session = self.session_candles.get(symbol, [])
        
        # Need minimum candles
        if len(session) < cfg.VWAP_MIN_CANDLES_FOR_SIGNAL:
            return None
        
        # Max trades check
        if self.trade_counts[symbol] >= cfg.VWAP_MAX_TRADES_PER_SESSION:
            return None
        
        # Calculate VWAP and deviation
        vwap_val, std = Indicators.vwap(session)
        if vwap_val is None or std is None or std == 0:
            return None
        
        price = candle.close
        deviation = (price - vwap_val) / std  # In standard deviations
        
        # Long setup: price below VWAP - 1.5σ + RSI oversold
        if (deviation < -cfg.VWAP_DEVIATION_ENTRY and 
                rsi is not None and rsi < cfg.VWAP_RSI_OVERSOLD):
            
            entry = price
            target = vwap_val  # Mean reversion to VWAP
            stop = vwap_val - (std * cfg.VWAP_DEVIATION_STOP)
            confidence = min(85, int(50 + abs(deviation) * 10 + (cfg.VWAP_RSI_OVERSOLD - rsi)))
            
            self.trade_counts[symbol] += 1
            return Signal(
                strategy=self.name,
                symbol=symbol,
                direction='BUY',
                entry_price=entry,
                stop_loss=stop,
                target=target,
                confidence=confidence,
                timestamp=candle.timestamp,
                reason=f"VWAP MR Long | Dev {deviation:.1f}σ | RSI {rsi:.1f} | VWAP {vwap_val:.2f}",
                metadata={'vwap': vwap_val, 'std': std, 'deviation': deviation, 'rsi': rsi},
            )
        
        # Short setup: price above VWAP + 1.5σ + RSI overbought
        elif (deviation > cfg.VWAP_DEVIATION_ENTRY and 
                  rsi is not None and rsi > cfg.VWAP_RSI_OVERBOUGHT):
            
            entry = price
            target = vwap_val
            stop = vwap_val + (std * cfg.VWAP_DEVIATION_STOP)
            confidence = min(85, int(50 + abs(deviation) * 10 + (rsi - cfg.VWAP_RSI_OVERBOUGHT)))
            
            self.trade_counts[symbol] += 1
            return Signal(
                strategy=self.name,
                symbol=symbol,
                direction='SELL',
                entry_price=entry,
                stop_loss=stop,
                target=target,
                confidence=confidence,
                timestamp=candle.timestamp,
                reason=f"VWAP MR Short | Dev +{deviation:.1f}σ | RSI {rsi:.1f} | VWAP {vwap_val:.2f}",
                metadata={'vwap': vwap_val, 'std': std, 'deviation': deviation, 'rsi': rsi},
            )
        
        return None


# ═══════════════════════════════════════════════════════════════════════════════
# STRATEGY S3: RSI ZONE TRACKER (Kalman-smoothed)
# ═══════════════════════════════════════════════════════════════════════════════

class RSIZoneStrategy:
    """
    RSI Zone Tracker adapted from Algo_Beta equity system.
    
    Logic:
        Kalman-smooth the 14-period RSI on 5-min candles
        Track velocity (rising/falling)
        Zone: K-RSI enters 20-35 → ZONE_ENTERED
        After 6+ readings with positive velocity → TRIGGERED → signal
    """
    
    # States
    WATCHING = 'WATCHING'
    ZONE_ENTERED = 'ZONE_ENTERED'
    TRIGGERED = 'TRIGGERED'
    COOLDOWN = 'COOLDOWN'
    
    def __init__(self):
        self.name = 'RSI_ZONE'
        self.states: Dict[str, dict] = {}  # Per-symbol state
    
    def reset_session(self):
        """Reset for new evening session."""
        self.states.clear()
    
    def _get_state(self, symbol: str) -> dict:
        """Get or create state for a symbol."""
        if symbol not in self.states:
            self.states[symbol] = {
                'state': self.WATCHING,
                'kalman': {},
                'readings_in_zone': 0,
                'zone_low': None,
                'last_velocity': 0,
                'trigger_count': 0,
            }
        return self.states[symbol]
    
    def check_signal(self, symbol: str, candle: Candle, raw_rsi: Optional[float]) -> Optional[Signal]:
        """
        Check RSI zone for signal.
        
        Args:
            symbol: Trading symbol
            candle: Latest completed 5-min candle
            raw_rsi: Raw 14-period RSI value
        """
        if raw_rsi is None:
            return None
        
        st = self._get_state(symbol)
        
        # Kalman smooth
        k_rsi, velocity = Indicators.kalman_smooth(raw_rsi, st['kalman'])
        st['last_velocity'] = velocity
        
        price = candle.close
        
        # State machine
        if st['state'] == self.WATCHING:
            # Check if RSI enters dip zone
            if cfg.RSI_DIP_ZONE_LOW <= k_rsi <= cfg.RSI_DIP_ZONE_HIGH:
                st['state'] = self.ZONE_ENTERED
                st['readings_in_zone'] = 1
                st['zone_low'] = k_rsi
                logger.debug(f"  RSI_ZONE {symbol}: WATCHING → ZONE_ENTERED | K-RSI {k_rsi:.1f}")
        
        elif st['state'] == self.ZONE_ENTERED:
            if cfg.RSI_DIP_ZONE_LOW <= k_rsi <= cfg.RSI_DIP_ZONE_HIGH:
                st['readings_in_zone'] += 1
                if k_rsi < st['zone_low']:
                    st['zone_low'] = k_rsi
                
                # Check trigger conditions
                if (st['readings_in_zone'] >= cfg.RSI_TRIGGER_READINGS and 
                        velocity >= cfg.RSI_MIN_VELOCITY):
                    st['state'] = self.TRIGGERED
                    st['trigger_count'] += 1
                    logger.info(f"  ✅ RSI_ZONE TRIGGERED {symbol} | K-RSI {k_rsi:.1f} "
                               f"| Vel +{velocity:.2f} | ZoneLow {st['zone_low']:.1f} "
                               f"| Readings {st['readings_in_zone']}")
            
            elif k_rsi > cfg.RSI_DIP_ZONE_HIGH:
                # Exited zone upward without enough readings — could still be valid
                if st['readings_in_zone'] >= 3 and velocity > 0:
                    st['state'] = self.TRIGGERED
                    st['trigger_count'] += 1
                else:
                    st['state'] = self.WATCHING
                    st['readings_in_zone'] = 0
            
            elif k_rsi < cfg.RSI_DIP_ZONE_LOW:
                # Dropped below zone — keep tracking
                st['readings_in_zone'] += 1
                st['zone_low'] = min(st['zone_low'], k_rsi)
        
        elif st['state'] == self.TRIGGERED:
            # Generate signal
            entry = price
            # Stop below the zone low price (approximate using RSI zone low)
            atr_estimate = abs(candle.high - candle.low) * 2  # Rough ATR proxy
            stop = entry - atr_estimate
            target = entry + (atr_estimate * 1.5)
            
            dip_depth = cfg.RSI_DIP_ZONE_HIGH - st['zone_low']
            confidence = min(85, int(50 + dip_depth * 2 + velocity * 20 + st['readings_in_zone'] * 2))
            
            # Move to cooldown
            st['state'] = self.COOLDOWN
            
            return Signal(
                strategy=self.name,
                symbol=symbol,
                direction='BUY',
                entry_price=entry,
                stop_loss=stop,
                target=target,
                confidence=confidence,
                timestamp=candle.timestamp,
                reason=(f"RSI Zone BUY | K-RSI {k_rsi:.1f} | Vel +{velocity:.2f} "
                       f"| ZoneLow {st['zone_low']:.1f} | Readings {st['readings_in_zone']}"),
                metadata={
                    'k_rsi': k_rsi, 'velocity': velocity,
                    'zone_low': st['zone_low'], 'readings': st['readings_in_zone'],
                },
            )
        
        elif st['state'] == self.COOLDOWN:
            # Wait for RSI to reset above zone before allowing re-entry
            if k_rsi > cfg.RSI_DIP_ZONE_HIGH + 10:  # Well above zone
                st['state'] = self.WATCHING
                st['readings_in_zone'] = 0
                st['zone_low'] = None
        
        return None
    
    def get_state_display(self, symbol: str) -> str:
        """Get human-readable state for logging."""
        st = self._get_state(symbol)
        k_rsi = st['kalman'].get('estimate', 0)
        return (f"{st['state']:14s} | K-RSI {k_rsi:5.1f} | Vel {st['last_velocity']:+.2f} "
                f"| Readings {st['readings_in_zone']}")


# ═══════════════════════════════════════════════════════════════════════════════
# SIGNAL ENGINE — Coordinates all strategies
# ═══════════════════════════════════════════════════════════════════════════════

class MCXSignalEngine:
    """
    Coordinates all three strategies and dispatches signals.
    
    Usage:
        engine = MCXSignalEngine()
        engine.reset_session()
        
        # On each tick:
        completed_candle = candle_builder.on_tick(...)
        if completed_candle:
            signals = engine.on_candle(symbol, completed_candle, all_candles)
    """
    
    def __init__(self):
        self.orb = ORBStrategy()
        self.vwap_mr = VWAPMeanReversionStrategy()
        self.rsi_zone = RSIZoneStrategy()
        self.orb_locked = set()  # Symbols whose ORB ranges are locked
        self.signals_generated = 0
    
    def reset_session(self):
        """Reset all strategies for new evening session."""
        self.orb.reset_session()
        self.vwap_mr.reset_session()
        self.rsi_zone.reset_session()
        self.orb_locked.clear()
        self.signals_generated = 0
        logger.info("  Signal engine: all strategies reset for new session")
    
    def on_candle(self, symbol: str, candle: Candle, all_candles: List[Candle]) -> List[Signal]:
        """
        Process a completed candle through all strategies.
        
        Args:
            symbol: Trading symbol
            candle: Newly completed 5-min candle
            all_candles: Full candle history for this symbol
            
        Returns:
            List of signals (may be empty)
        """
        signals = []
        now = candle.timestamp.time()
        
        # ─── Time checks ─────────────────────────────────────────────────
        
        after_entry_cutoff = now >= cfg.MCX_ENTRY_CUTOFF
        if after_entry_cutoff:
            return signals  # No new signals after cutoff
        
        in_orb_window = cfg.ORB_WINDOW_START <= now < cfg.ORB_WINDOW_END
        after_orb_window = now >= cfg.ORB_WINDOW_END
        in_evening_session = now >= cfg.MCX_EVENING_SESSION_START
        
        # ─── S1: ORB ─────────────────────────────────────────────────────
        
        if in_orb_window:
            self.orb.update_orb_range(symbol, candle)
        
        if after_orb_window and symbol not in self.orb_locked:
            self.orb.lock_range(symbol)
            self.orb_locked.add(symbol)
        
        if after_orb_window:
            avg_vol = Indicators.avg_volume(all_candles)
            orb_signal = self.orb.check_signal(symbol, candle, avg_vol)
            if orb_signal:
                signals.append(orb_signal)
        
        # ─── S2: VWAP Mean Reversion ─────────────────────────────────────
        
        if in_evening_session:
            self.vwap_mr.add_candle(symbol, candle)
            rsi_val = Indicators.rsi(all_candles, cfg.RSI_PERIOD)
            vwap_signal = self.vwap_mr.check_signal(symbol, candle, rsi_val)
            if vwap_signal:
                signals.append(vwap_signal)
        
        # ─── S3: RSI Zone Tracker ────────────────────────────────────────
        
        if in_evening_session and len(all_candles) >= cfg.RSI_PERIOD + 1:
            rsi_val = Indicators.rsi(all_candles, cfg.RSI_PERIOD)
            rsi_signal = self.rsi_zone.check_signal(symbol, candle, rsi_val)
            if rsi_signal:
                signals.append(rsi_signal)
        
        # ─── Log signals ─────────────────────────────────────────────────
        
        for sig in signals:
            self.signals_generated += 1
            logger.info(f"  📡 SIGNAL #{self.signals_generated}: {sig.strategy} {sig.direction} "
                       f"{sig.symbol} @ {sig.entry_price:.2f} | SL {sig.stop_loss:.2f} "
                       f"| TGT {sig.target:.2f} | Conf {sig.confidence}")
            logger.info(f"     Reason: {sig.reason}")
        
        return signals
