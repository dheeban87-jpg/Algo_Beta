"""
CANDLESTICK PATTERN DETECTOR v1.0.0
═══════════════════════════════════════════════════════════════════════════════

Advisory layer that detects high-probability candlestick patterns on
15-minute OHLCV candle data and checks proximity to institutional key levels.

Patterns Detected:
  1. Bullish Hammer      — long lower wick, body at top (reversal signal)
  2. Bullish Engulfing   — bearish candle engulfed by bullish candle
  3. Bearish Pin Bar     — long upper wick, body at bottom (rejection signal)

Consumers:
  - Phase 6 Options Advisory: bullish patterns at key levels add +5/+8/+10
    bonus confidence points
  - Phase 4 TCAS Safety System: bearish patterns at resistance trigger
    CAUTION or ALERT warnings

This module does NOT generate entry signals. It only enhances or warns
after the core scoring system has made its decision.

Author: Trading System v1.0.0
Date: 2026-02-22
"""

import logging
from dataclasses import dataclass, field
from typing import Optional, List, Dict
from datetime import datetime
from collections import deque

logger = logging.getLogger('CandlestickPatternDetector')


# ═══════════════════════════════════════════════════════════════════════════════
# DATA STRUCTURES
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class CandleData:
    """Single 15-minute OHLCV candle."""
    symbol: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int


@dataclass
class KeyLevels:
    """Institutional reference levels for the current trading session.

    These are computed ONCE at market open (09:15-09:45) and remain fixed
    for the rest of the session. The orchestrator or Phase 2 already
    calculates most of these — the detector just receives them.
    """
    ib_high: Optional[float] = None       # Initial Balance High
    ib_low: Optional[float] = None        # Initial Balance Low
    pdh: Optional[float] = None           # Previous Day High
    pdl: Optional[float] = None           # Previous Day Low
    swing_high: Optional[float] = None    # Recent multi-day swing high
    swing_low: Optional[float] = None     # Recent multi-day swing low
    vwap: Optional[float] = None          # Current session VWAP
    vwap_upper_1sd: Optional[float] = None  # VWAP + 1 standard deviation
    vwap_lower_1sd: Optional[float] = None  # VWAP - 1 standard deviation


@dataclass
class PatternSignal:
    """Result from pattern detection on a single candle/pair."""
    symbol: str
    timestamp: datetime
    pattern_type: str          # 'BULLISH_HAMMER', 'BULLISH_ENGULFING', 'BEARISH_PIN_BAR'
    direction: str             # 'BULLISH' or 'BEARISH'
    confidence: str            # 'HIGH', 'MEDIUM', 'LOW'

    # Pattern anatomy details (for logging/Telegram)
    body_pct: float            # Body as % of total candle range
    wick_ratio: float          # Dominant wick / body ratio

    # Key level proximity
    nearby_levels: List[str] = field(default_factory=list)
    level_count: int = 0
    nearest_level: Optional[str] = None
    nearest_level_distance_pct: Optional[float] = None

    # Scoring impact
    bonus_points: int = 0
    tcas_severity: Optional[str] = None  # None, 'CAUTION', 'ALERT'

    # Raw data for debugging
    candle_open: float = 0.0
    candle_high: float = 0.0
    candle_low: float = 0.0
    candle_close: float = 0.0
    candle_volume: int = 0


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN DETECTOR CLASS
# ═══════════════════════════════════════════════════════════════════════════════

class CandlestickPatternDetector:
    """Detects candlestick patterns on 15-min candles and checks key level proximity.

    USAGE:
        detector = CandlestickPatternDetector(config)

        # On every new 15-min candle:
        signals = detector.analyze(
            symbol='SBIN',
            current_candle=candle,
            recent_candles=last_5_candles,
            key_levels=session_levels
        )

        for signal in signals:
            if signal.direction == 'BULLISH' and signal.bonus_points > 0:
                phase6.apply_pattern_bonus(signal)
            elif signal.direction == 'BEARISH' and signal.tcas_severity:
                phase4.handle_pattern_warning(signal)

    CANDLE BUFFER:
        The detector maintains a per-symbol rolling buffer of the last 5 candles.
        Caller can either:
        a) Pass recent_candles explicitly on each call (stateless)
        b) Use detector.feed_candle(symbol, candle) to let the detector manage buffers

    THREAD SAFETY:
        The detector is stateless per call when recent_candles is provided.
        The internal buffer uses a simple dict — only call from the
        monitoring loop thread (same as Phase 2/4), not from multiple threads.
    """

    def __init__(self, config=None):
        self.config = config or {}
        self._candle_buffers: Dict[str, deque] = {}  # symbol -> deque(maxlen=5)

        # Load configurable thresholds with defaults
        self.HAMMER_WICK_RATIO = self._cfg('HAMMER_WICK_RATIO', 2.0)
        self.HAMMER_UPPER_WICK_MAX_PCT = self._cfg('HAMMER_UPPER_WICK_MAX_PCT', 10.0)
        self.HAMMER_BODY_POSITION_MIN = self._cfg('HAMMER_BODY_POSITION_MIN', 0.65)
        self.HAMMER_BODY_PCT_MAX = self._cfg('HAMMER_BODY_PCT_MAX', 33.0)

        self.ENGULF_RATIO_MIN = self._cfg('ENGULF_RATIO_MIN', 1.2)

        self.PINBAR_WICK_RATIO = self._cfg('PINBAR_WICK_RATIO', 2.0)
        self.PINBAR_LOWER_WICK_MAX_PCT = self._cfg('PINBAR_LOWER_WICK_MAX_PCT', 10.0)
        self.PINBAR_BODY_POSITION_MAX = self._cfg('PINBAR_BODY_POSITION_MAX', 0.35)
        self.PINBAR_BODY_PCT_MAX = self._cfg('PINBAR_BODY_PCT_MAX', 33.0)

        self.LEVEL_PROXIMITY_PCT = self._cfg('PATTERN_LEVEL_PROXIMITY_PCT', 0.20)

        self.BONUS_1_LEVEL = self._cfg('PATTERN_BONUS_1_LEVEL', 5)
        self.BONUS_2_LEVELS = self._cfg('PATTERN_BONUS_2_LEVELS', 8)
        self.BONUS_3_LEVELS = self._cfg('PATTERN_BONUS_3_LEVELS', 10)

        logger.info("=" * 60)
        logger.info("CANDLESTICK PATTERN DETECTOR v1.0.0 INITIALIZED")
        logger.info("=" * 60)
        logger.info(f"   Patterns: Bullish Hammer, Bullish Engulfing, Bearish Pin Bar")
        logger.info(f"   Level Proximity: {self.LEVEL_PROXIMITY_PCT}%")
        logger.info(f"   Bonus Points: +{self.BONUS_1_LEVEL}/+{self.BONUS_2_LEVELS}/+{self.BONUS_3_LEVELS}")
        logger.info("=" * 60)

    def _cfg(self, key, default):
        """Read from config dict or object, fallback to default."""
        if isinstance(self.config, dict):
            return self.config.get(key, default)
        return getattr(self.config, key, default)

    # ───────────────────────────────────────────────────────────────────────
    # CANDLE BUFFER MANAGEMENT
    # ───────────────────────────────────────────────────────────────────────

    def feed_candle(self, symbol: str, candle: CandleData):
        """Add a candle to the internal buffer for a symbol.

        Use this if you want the detector to manage its own rolling buffer
        instead of passing recent_candles explicitly.
        """
        if symbol not in self._candle_buffers:
            self._candle_buffers[symbol] = deque(maxlen=5)
        self._candle_buffers[symbol].append(candle)

    def get_recent_candles(self, symbol: str) -> List[CandleData]:
        """Get the internal candle buffer for a symbol."""
        buf = self._candle_buffers.get(symbol)
        return list(buf) if buf else []

    # ───────────────────────────────────────────────────────────────────────
    # CANDLE ANATOMY
    # ───────────────────────────────────────────────────────────────────────

    def _parse_candle(self, candle: CandleData) -> Optional[dict]:
        """Decompose a candle into body, wicks, and ratios.

        Returns dict with body_size, upper_wick, lower_wick, total_range,
        is_bullish, body_pct, upper_wick_pct, lower_wick_pct, body_position.
        Returns None if candle has near-zero range (doji / no movement).
        """
        total_range = candle.high - candle.low

        # Guard against doji / zero-range candles
        if total_range < 0.01:
            return None

        body_top = max(candle.open, candle.close)
        body_bottom = min(candle.open, candle.close)
        body_size = body_top - body_bottom
        upper_wick = candle.high - body_top
        lower_wick = body_bottom - candle.low

        return {
            'body_size': body_size,
            'body_top': body_top,
            'body_bottom': body_bottom,
            'upper_wick': upper_wick,
            'lower_wick': lower_wick,
            'total_range': total_range,
            'is_bullish': candle.close > candle.open,
            'body_pct': (body_size / total_range) * 100,
            'upper_wick_pct': (upper_wick / total_range) * 100,
            'lower_wick_pct': (lower_wick / total_range) * 100,
            'body_position': (body_bottom - candle.low) / total_range  # 0=bottom, 1=top
        }

    # ───────────────────────────────────────────────────────────────────────
    # PATTERN DETECTION: BULLISH HAMMER
    # ───────────────────────────────────────────────────────────────────────

    def _detect_bullish_hammer(self, candle: CandleData,
                                recent_candles: List[CandleData]) -> Optional[dict]:
        """Detect Bullish Hammer pattern.

        Small body at the TOP of the candle range with a long LOWER wick.
        Indicates buyers rejected lower prices.

        Rules:
          1. lower_wick >= 2.0x body_size
          2. upper_wick <= 10% of total range
          3. body_position >= 0.65
          4. body_pct <= 33%
          Context: At least 2 of previous 3 candles bearish (downswing)
        """
        anatomy = self._parse_candle(candle)
        if anatomy is None:
            return None

        # Guard: need minimum body size to avoid noise
        min_body = candle.close * 0.0005
        if anatomy['body_size'] < min_body:
            return None

        # Rule 1: Long lower wick (>= 2x body)
        if anatomy['body_size'] <= 0:
            return None
        wick_ratio = anatomy['lower_wick'] / anatomy['body_size']
        if wick_ratio < self.HAMMER_WICK_RATIO:
            return None

        # Rule 2: Small upper wick (<= 10% of total range)
        if anatomy['upper_wick_pct'] > self.HAMMER_UPPER_WICK_MAX_PCT:
            return None

        # Rule 3: Body in upper third (position >= 0.65)
        if anatomy['body_position'] < self.HAMMER_BODY_POSITION_MIN:
            return None

        # Rule 4: Small body (<= 33% of range)
        if anatomy['body_pct'] > self.HAMMER_BODY_PCT_MAX:
            return None

        # Context: Downswing check — at least 2 of last 3 candles bearish
        if len(recent_candles) >= 3:
            bearish_count = sum(1 for c in recent_candles[-3:] if c.close < c.open)
            if bearish_count < 2:
                return None
        elif len(recent_candles) >= 1:
            bearish_count = sum(1 for c in recent_candles if c.close < c.open)
            if bearish_count < 1:
                return None
        # If no recent candles available (first candle of session), skip context check

        return {
            'pattern_type': 'BULLISH_HAMMER',
            'direction': 'BULLISH',
            'wick_ratio': round(wick_ratio, 2),
            'body_pct': round(anatomy['body_pct'], 1),
            'body_position': round(anatomy['body_position'], 2),
            'confidence': 'HIGH' if wick_ratio >= 3.0 else 'MEDIUM'
        }

    # ───────────────────────────────────────────────────────────────────────
    # PATTERN DETECTION: BULLISH ENGULFING
    # ───────────────────────────────────────────────────────────────────────

    def _detect_bullish_engulfing(self, current: CandleData,
                                   previous: CandleData) -> Optional[dict]:
        """Detect Bullish Engulfing pattern.

        Two-candle pattern. First candle is a small BEARISH candle.
        Second candle is a large BULLISH candle whose body completely
        covers (engulfs) the first candle's body.

        Rules:
          1. prev_candle is bearish
          2. current_candle is bullish
          3. curr.close > prev.open  (covers top)
          4. curr.open < prev.close  (covers bottom)
          5. current body_size > prev body_size x 1.2
        """
        curr_anatomy = self._parse_candle(current)
        prev_anatomy = self._parse_candle(previous)

        if curr_anatomy is None or prev_anatomy is None:
            return None

        # Rule 1: Previous candle must be bearish
        if prev_anatomy['is_bullish']:
            return None

        # Rule 2: Current candle must be bullish
        if not curr_anatomy['is_bullish']:
            return None

        # Rule 3 & 4: Current body engulfs previous body
        if current.close <= previous.open:
            return None
        if current.open >= previous.close:
            return None

        # Rule 5: Current body meaningfully larger (1.2x previous body)
        if prev_anatomy['body_size'] > 0:
            engulf_ratio = curr_anatomy['body_size'] / prev_anatomy['body_size']
        else:
            engulf_ratio = 999  # Previous is doji-like, any body engulfs it

        if engulf_ratio < self.ENGULF_RATIO_MIN:
            return None

        # Volume confirmation (optional but boosts confidence)
        volume_confirms = current.volume > previous.volume

        if engulf_ratio >= 2.0 and volume_confirms:
            confidence = 'HIGH'
        elif engulf_ratio >= 1.5 or volume_confirms:
            confidence = 'MEDIUM'
        else:
            confidence = 'LOW'

        return {
            'pattern_type': 'BULLISH_ENGULFING',
            'direction': 'BULLISH',
            'wick_ratio': round(engulf_ratio, 2),  # Using engulf ratio here
            'body_pct': round(curr_anatomy['body_pct'], 1),
            'volume_confirms': volume_confirms,
            'confidence': confidence
        }

    # ───────────────────────────────────────────────────────────────────────
    # PATTERN DETECTION: BEARISH PIN BAR
    # ───────────────────────────────────────────────────────────────────────

    def _detect_bearish_pin_bar(self, candle: CandleData,
                                 recent_candles: List[CandleData],
                                 key_levels: Optional[KeyLevels] = None) -> Optional[dict]:
        """Detect Bearish Pin Bar pattern.

        Small body at the BOTTOM of the candle range with a long UPPER wick.
        Indicates sellers rejected higher prices.

        Rules:
          1. upper_wick >= 2.0x body_size
          2. lower_wick <= 10% of total range
          3. body_position <= 0.35
          4. body_pct <= 33%
          Context: At least 2 of previous 3 candles bullish (upswing)
                   OR candle high near a resistance key level
        """
        anatomy = self._parse_candle(candle)
        if anatomy is None:
            return None

        min_body = candle.close * 0.0005
        if anatomy['body_size'] < min_body:
            return None

        # Rule 1: Long upper wick (>= 2x body)
        if anatomy['body_size'] <= 0:
            return None
        wick_ratio = anatomy['upper_wick'] / anatomy['body_size']
        if wick_ratio < self.PINBAR_WICK_RATIO:
            return None

        # Rule 2: Small lower wick (<= 10% of total range)
        if anatomy['lower_wick_pct'] > self.PINBAR_LOWER_WICK_MAX_PCT:
            return None

        # Rule 3: Body in lower third (position <= 0.35)
        if anatomy['body_position'] > self.PINBAR_BODY_POSITION_MAX:
            return None

        # Rule 4: Small body (<= 33% of range)
        if anatomy['body_pct'] > self.PINBAR_BODY_PCT_MAX:
            return None

        # Context: Upswing check OR near resistance level
        upswing_confirmed = False
        near_resistance = False

        if len(recent_candles) >= 3:
            bullish_count = sum(1 for c in recent_candles[-3:] if c.close > c.open)
            upswing_confirmed = bullish_count >= 2

        # Check if candle high is near a resistance level
        if key_levels:
            resistance_levels = []
            if key_levels.ib_high is not None:
                resistance_levels.append(key_levels.ib_high)
            if key_levels.pdh is not None:
                resistance_levels.append(key_levels.pdh)
            if key_levels.swing_high is not None:
                resistance_levels.append(key_levels.swing_high)
            if key_levels.vwap_upper_1sd is not None:
                resistance_levels.append(key_levels.vwap_upper_1sd)

            proximity_threshold = candle.close * 0.002  # 0.2% of price
            for level in resistance_levels:
                if abs(candle.high - level) <= proximity_threshold:
                    near_resistance = True
                    break

        if not upswing_confirmed and not near_resistance:
            return None

        return {
            'pattern_type': 'BEARISH_PIN_BAR',
            'direction': 'BEARISH',
            'wick_ratio': round(wick_ratio, 2),
            'body_pct': round(anatomy['body_pct'], 1),
            'body_position': round(anatomy['body_position'], 2),
            'near_resistance': near_resistance,
            'upswing_confirmed': upswing_confirmed,
            'confidence': 'HIGH' if (wick_ratio >= 3.0 and near_resistance) else 'MEDIUM'
        }

    # ───────────────────────────────────────────────────────────────────────
    # KEY LEVEL PROXIMITY CHECK
    # ───────────────────────────────────────────────────────────────────────

    def _check_key_level_proximity(self, candle: CandleData,
                                    pattern_direction: str,
                                    key_levels: KeyLevels) -> dict:
        """Check if the pattern occurred near institutional key levels.

        For BULLISH patterns: check proximity to SUPPORT levels
          (IB Low, PDL, Swing Low, VWAP lower band)
        For BEARISH patterns: check proximity to RESISTANCE levels
          (IB High, PDH, Swing High, VWAP upper band)

        Returns dict with nearby_levels, level_count, nearest_level,
        nearest_level_distance_pct, bonus_points, and tcas_severity.
        """
        proximity_threshold = candle.close * (self.LEVEL_PROXIMITY_PCT / 100.0)

        # Select appropriate levels based on direction
        if pattern_direction == 'BULLISH':
            reference_price = candle.low
            levels_to_check = {
                'IB_LOW': key_levels.ib_low,
                'PDL': key_levels.pdl,
                'SWING_LOW': key_levels.swing_low,
                'VWAP_LOWER': key_levels.vwap_lower_1sd,
            }
        else:  # BEARISH
            reference_price = candle.high
            levels_to_check = {
                'IB_HIGH': key_levels.ib_high,
                'PDH': key_levels.pdh,
                'SWING_HIGH': key_levels.swing_high,
                'VWAP_UPPER': key_levels.vwap_upper_1sd,
            }

        nearby_levels = []
        nearest_name = None
        nearest_distance = float('inf')

        for level_name, level_price in levels_to_check.items():
            if level_price is None:
                continue

            distance = abs(reference_price - level_price)

            if distance <= proximity_threshold:
                nearby_levels.append(level_name)
                if distance < nearest_distance:
                    nearest_distance = distance
                    nearest_name = level_name

        level_count = len(nearby_levels)

        # Bonus points based on confluence
        if level_count >= 3:
            bonus_points = self.BONUS_3_LEVELS
        elif level_count == 2:
            bonus_points = self.BONUS_2_LEVELS
        elif level_count == 1:
            bonus_points = self.BONUS_1_LEVEL
        else:
            bonus_points = 0

        # TCAS severity for bearish patterns
        tcas_severity = None
        if pattern_direction == 'BEARISH':
            if level_count >= 2:
                tcas_severity = 'ALERT'
            elif level_count == 1:
                tcas_severity = 'CAUTION'

        return {
            'nearby_levels': nearby_levels,
            'level_count': level_count,
            'nearest_level': nearest_name,
            'nearest_level_distance_pct': round((nearest_distance / candle.close) * 100, 3) if nearest_name else None,
            'bonus_points': bonus_points,
            'tcas_severity': tcas_severity
        }

    # ───────────────────────────────────────────────────────────────────────
    # PUBLIC API
    # ───────────────────────────────────────────────────────────────────────

    def analyze(self, symbol: str, current_candle: CandleData,
                recent_candles: List[CandleData],
                key_levels: Optional[KeyLevels] = None) -> List[PatternSignal]:
        """Main entry point — analyze a candle for all patterns.

        Args:
            symbol: Stock symbol (e.g. 'SBIN')
            current_candle: The latest completed 15-min candle
            recent_candles: Previous 3-5 candles for context
            key_levels: Session reference levels (IB, PDH/PDL, etc.)

        Returns:
            List of PatternSignal objects (usually 0 or 1, rarely 2)
        """
        signals = []

        # 1. Try Bullish Hammer
        hammer = self._detect_bullish_hammer(current_candle, recent_candles)
        if hammer:
            signals.append(self._build_signal(
                symbol, current_candle, hammer, key_levels
            ))

        # 2. Try Bullish Engulfing (needs previous candle)
        if len(recent_candles) >= 1:
            previous_candle = recent_candles[-1]
            engulfing = self._detect_bullish_engulfing(current_candle, previous_candle)
            if engulfing:
                signals.append(self._build_signal(
                    symbol, current_candle, engulfing, key_levels
                ))

        # 3. Try Bearish Pin Bar
        pin_bar = self._detect_bearish_pin_bar(
            current_candle, recent_candles, key_levels
        )
        if pin_bar:
            signals.append(self._build_signal(
                symbol, current_candle, pin_bar, key_levels
            ))

        # Log detections
        for sig in signals:
            logger.info(
                f"PATTERN: {sig.pattern_type} on {sig.symbol} | "
                f"Levels: {sig.nearby_levels} | Bonus: +{sig.bonus_points}pts | "
                f"TCAS: {sig.tcas_severity or 'N/A'}"
            )

        return signals

    def _build_signal(self, symbol: str, candle: CandleData,
                      pattern_result: dict,
                      key_levels: Optional[KeyLevels]) -> PatternSignal:
        """Build PatternSignal from detection result + level check."""

        # Key level proximity check
        if key_levels:
            level_result = self._check_key_level_proximity(
                candle, pattern_result['direction'], key_levels
            )
        else:
            level_result = {
                'nearby_levels': [], 'level_count': 0,
                'nearest_level': None, 'nearest_level_distance_pct': None,
                'bonus_points': 0, 'tcas_severity': None
            }

        return PatternSignal(
            symbol=symbol,
            timestamp=candle.timestamp,
            pattern_type=pattern_result['pattern_type'],
            direction=pattern_result['direction'],
            confidence=pattern_result['confidence'],
            body_pct=pattern_result['body_pct'],
            wick_ratio=pattern_result['wick_ratio'],
            nearby_levels=level_result['nearby_levels'],
            level_count=level_result['level_count'],
            nearest_level=level_result['nearest_level'],
            nearest_level_distance_pct=level_result['nearest_level_distance_pct'],
            bonus_points=level_result['bonus_points'],
            tcas_severity=level_result['tcas_severity'],
            candle_open=candle.open,
            candle_high=candle.high,
            candle_low=candle.low,
            candle_close=candle.close,
            candle_volume=candle.volume
        )

    # ───────────────────────────────────────────────────────────────────────
    # TELEGRAM MESSAGE FORMATTERS
    # ───────────────────────────────────────────────────────────────────────

    @staticmethod
    def format_bullish_telegram(signal: PatternSignal, effective_score: int = 0,
                                 original_score: int = 0) -> str:
        """Format a bullish pattern detection for Telegram."""
        pattern_names = {
            'BULLISH_HAMMER': 'Bullish Hammer',
            'BULLISH_ENGULFING': 'Bullish Engulfing',
        }
        pattern_display = pattern_names.get(signal.pattern_type, signal.pattern_type)

        levels_str = ""
        if signal.nearby_levels:
            for lvl in signal.nearby_levels:
                levels_str += f"\n  - {lvl}"
        else:
            levels_str = "\n  (none within proximity)"

        msg = (
            f"PATTERN BOOST -- {signal.symbol}\n"
            f"{'=' * 30}\n"
            f"Pattern: {pattern_display}\n"
            f"Wick Ratio: {signal.wick_ratio}x body\n"
            f"Confidence: {signal.confidence}\n"
            f"\n"
            f"Key Levels:{levels_str}\n"
            f"\n"
            f"Phase 6 Impact:\n"
            f"  Score: {original_score} + {signal.bonus_points} (pattern) = {effective_score}\n"
            f"\n"
            f"{signal.timestamp.strftime('%I:%M %p')} | {signal.timestamp.strftime('%d-%b-%Y')}"
        )
        return msg

    @staticmethod
    def format_bearish_telegram(signal: PatternSignal, position: dict = None,
                                 action_taken: str = '') -> str:
        """Format a bearish pattern TCAS warning for Telegram."""
        severity_prefix = "TCAS PATTERN ALERT" if signal.tcas_severity == 'ALERT' else "TCAS PATTERN CAUTION"
        severity_icon = "!" if signal.tcas_severity == 'ALERT' else "?"

        levels_str = ""
        if signal.nearby_levels:
            for lvl in signal.nearby_levels:
                levels_str += f"\n  - {lvl}"
        else:
            levels_str = "\n  (none)"

        msg = (
            f"{severity_icon} {severity_prefix} -- {signal.symbol}\n"
            f"{'=' * 35}\n"
            f"Pattern: Bearish Pin Bar\n"
            f"Wick Ratio: {signal.wick_ratio}x body\n"
            f"Confidence: {signal.confidence}\n"
            f"\n"
            f"Key Levels:{levels_str}\n"
            f"\n"
            f"TCAS Action:\n"
            f"  {action_taken}\n"
            f"\n"
            f"{signal.timestamp.strftime('%I:%M %p')} | {signal.timestamp.strftime('%d-%b-%Y')}"
        )
        return msg


# ═══════════════════════════════════════════════════════════════════════════════
# INLINE UNIT TESTS
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == '__main__':
    import sys

    print("=" * 70)
    print("CANDLESTICK PATTERN DETECTOR — UNIT TESTS")
    print("=" * 70)

    detector = CandlestickPatternDetector()
    passed = 0
    failed = 0

    def assert_test(name, condition):
        global passed, failed
        if condition:
            print(f"  PASS: {name}")
            passed += 1
        else:
            print(f"  FAIL: {name}")
            failed += 1

    # ── Test 1: Bullish Hammer Detection ──
    print("\n--- Bullish Hammer Tests ---")

    # Downswing context candles
    bearish_candles = [
        CandleData('TEST', datetime.now(), 105, 105, 100, 100, 1000),
        CandleData('TEST', datetime.now(), 103, 103, 98, 98, 1000),
        CandleData('TEST', datetime.now(), 101, 101, 96, 96, 1000),
    ]

    # Perfect hammer: body at top, long lower wick
    hammer_candle = CandleData('TEST', datetime.now(), 100, 101, 95, 100.5, 1000)
    result = detector._detect_bullish_hammer(hammer_candle, bearish_candles)
    assert_test("Perfect hammer detected", result is not None)
    if result:
        assert_test("Hammer pattern type correct", result['pattern_type'] == 'BULLISH_HAMMER')

    # Inverted hammer (long upper wick) — should NOT detect
    inverted = CandleData('TEST', datetime.now(), 100, 106, 99, 100.5, 1000)
    result = detector._detect_bullish_hammer(inverted, bearish_candles)
    assert_test("Inverted hammer rejected", result is None)

    # Full-body candle (no wick) — should NOT detect
    full_body = CandleData('TEST', datetime.now(), 100, 105, 100, 105, 1000)
    result = detector._detect_bullish_hammer(full_body, bearish_candles)
    assert_test("Full-body candle rejected", result is None)

    # Hammer without downswing context — should NOT detect
    bullish_candles = [
        CandleData('TEST', datetime.now(), 100, 105, 100, 105, 1000),
        CandleData('TEST', datetime.now(), 105, 110, 105, 110, 1000),
        CandleData('TEST', datetime.now(), 110, 115, 110, 115, 1000),
    ]
    result = detector._detect_bullish_hammer(hammer_candle, bullish_candles)
    assert_test("Hammer without downswing rejected", result is None)

    # ── Test 2: Bullish Engulfing Detection ──
    print("\n--- Bullish Engulfing Tests ---")

    # Perfect engulfing
    prev = CandleData('TEST', datetime.now(), 102, 102.5, 99.5, 100, 800)
    curr = CandleData('TEST', datetime.now(), 99, 104, 98.5, 103, 1200)
    result = detector._detect_bullish_engulfing(curr, prev)
    assert_test("Perfect engulfing detected", result is not None)
    if result:
        assert_test("Engulfing pattern type correct", result['pattern_type'] == 'BULLISH_ENGULFING')
        assert_test("Volume confirms", result.get('volume_confirms') is True)

    # Partial engulfing (doesn't fully cover) — should NOT detect
    prev2 = CandleData('TEST', datetime.now(), 102, 102.5, 99.5, 100, 800)
    curr2 = CandleData('TEST', datetime.now(), 100.5, 103, 100, 101.8, 1200)
    result = detector._detect_bullish_engulfing(curr2, prev2)
    assert_test("Partial engulfing rejected", result is None)

    # Both bullish — should NOT detect
    prev3 = CandleData('TEST', datetime.now(), 100, 103, 99.5, 102, 800)
    curr3 = CandleData('TEST', datetime.now(), 102, 106, 101.5, 105, 1200)
    result = detector._detect_bullish_engulfing(curr3, prev3)
    assert_test("Both bullish rejected", result is None)

    # ── Test 3: Bearish Pin Bar Detection ──
    print("\n--- Bearish Pin Bar Tests ---")

    # Upswing context
    upswing_candles = [
        CandleData('TEST', datetime.now(), 95, 100, 95, 100, 1000),
        CandleData('TEST', datetime.now(), 100, 105, 100, 105, 1000),
        CandleData('TEST', datetime.now(), 105, 110, 105, 110, 1000),
    ]

    # Perfect pin bar: body at bottom, long upper wick
    pin_bar = CandleData('TEST', datetime.now(), 100, 106, 99.5, 99.8, 1000)
    result = detector._detect_bearish_pin_bar(pin_bar, upswing_candles)
    assert_test("Perfect pin bar detected", result is not None)
    if result:
        assert_test("Pin bar pattern type correct", result['pattern_type'] == 'BEARISH_PIN_BAR')

    # Pin bar at PDH — should detect even without upswing
    levels = KeyLevels(pdh=106.1)
    pin_bar_at_level = CandleData('TEST', datetime.now(), 100, 106, 99.5, 99.8, 1000)
    result = detector._detect_bearish_pin_bar(pin_bar_at_level, [], levels)
    assert_test("Pin bar at PDH detected", result is not None)
    if result:
        assert_test("Near resistance flag set", result.get('near_resistance') is True)

    # Pin bar without upswing and not at resistance — should NOT detect
    result = detector._detect_bearish_pin_bar(pin_bar, [])
    assert_test("Pin bar without context rejected", result is None)

    # ── Test 4: Key Level Proximity ──
    print("\n--- Key Level Proximity Tests ---")

    levels = KeyLevels(
        ib_low=1000.0,
        pdl=999.5,
        swing_low=998.0,
        vwap_lower_1sd=1001.0
    )

    # Candle near IB Low and PDL (within 0.2%)
    near_candle = CandleData('TEST', datetime.now(), 1001, 1003, 1000.5, 1002, 1000)
    result = detector._check_key_level_proximity(near_candle, 'BULLISH', levels)
    assert_test(f"Found {result['level_count']} nearby support levels", result['level_count'] >= 1)
    assert_test(f"Bonus points = {result['bonus_points']}", result['bonus_points'] > 0)

    # Candle far from all levels
    far_candle = CandleData('TEST', datetime.now(), 1050, 1055, 1045, 1052, 1000)
    result = detector._check_key_level_proximity(far_candle, 'BULLISH', levels)
    assert_test(f"No nearby levels when far ({result['level_count']})", result['level_count'] == 0)
    assert_test("Zero bonus when no levels", result['bonus_points'] == 0)

    # ── Test 5: Full Analyze Pipeline ──
    print("\n--- Full Analyze Pipeline Tests ---")

    levels = KeyLevels(ib_low=95.2, pdl=94.8)
    signals = detector.analyze('SBIN', hammer_candle, bearish_candles, levels)
    assert_test(f"Analyze returned {len(signals)} signal(s)", len(signals) >= 1)
    if signals:
        sig = signals[0]
        assert_test("Signal has correct symbol", sig.symbol == 'SBIN')
        assert_test("Signal direction is BULLISH", sig.direction == 'BULLISH')
        assert_test(f"Signal bonus_points = {sig.bonus_points}", sig.bonus_points >= 0)

    # ── Summary ──
    print("\n" + "=" * 70)
    print(f"RESULTS: {passed} passed, {failed} failed out of {passed + failed} tests")
    print("=" * 70)

    sys.exit(0 if failed == 0 else 1)
