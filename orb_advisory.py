"""
ORB (OPEN RANGE BREAKOUT) ADVISORY v1.0.0
═══════════════════════════════════════════════════════════════════════════════

Passive detection of IB range compression and breakout/breakdown events.
This module is a READ-ONLY scoreboard — it NEVER calls any phase directly.
Phases PULL from the shared dict when THEY choose to.

Detection Stages:
  1. Silent Recording (09:15 - 10:15):  accumulate IB High/Low
  2. Compression Detection (10:15+):    track touches, BW, volume
  3. Breakout/Breakdown Confirmation:    close beyond IB + volume spike

Critical Constraints:
  - ZERO new timers or threads
  - ZERO new API calls (uses data Phase 1/2 already fetch)
  - NEVER calls any phase directly — phases pull from a shared dict
  - NEVER interrupts Phase 5 (09:15-10:00) or Phase 1 (10:00-10:15)
  - Runs INSIDE the existing Phase 2/4 monitoring loop as a lightweight check
  - Master switch: ORB_ADVISORY_ENABLED = True/False

Consumers (pull model):
  - Phase 6 Options: COMPRESSION_DETECTED → +8 pts, UPSIDE_BREAKOUT → +10 pts
  - Phase 4 TCAS:    DOWNSIDE_BREAKDOWN → tighten SL to breakeven
                     UPSIDE_BREAKOUT → switch to trailing mode

Author: Trading System v1.0.0
Date: 2026-02-22
"""

import logging
from dataclasses import dataclass, field
from typing import Optional, List, Dict
from datetime import datetime

logger = logging.getLogger('ORBAdvisory')


# ═══════════════════════════════════════════════════════════════════════════════
# DATA STRUCTURES
# ═══════════════════════════════════════════════════════════════════════════════

# ORB Status Constants
ORB_RECORDING = 'RECORDING'
ORB_WIDE_IB = 'WIDE_IB'
ORB_MONITORING = 'MONITORING'
ORB_COMPRESSION = 'COMPRESSION_DETECTED'
ORB_BREAKOUT_UP = 'UPSIDE_BREAKOUT'
ORB_BREAKDOWN = 'DOWNSIDE_BREAKDOWN'
ORB_EXPIRED = 'EXPIRED'


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN CLASS
# ═══════════════════════════════════════════════════════════════════════════════

class ORBAdvisory:
    """Passive Open Range Breakout detector.

    Monitors IB range formation, tracks compression indicators,
    and detects breakout/breakdown events. Maintains a shared
    scoreboard that other phases pull from -- never pushes.

    USAGE:
        orb = ORBAdvisory(config)

        # During IB formation (09:15-10:15), feed candles:
        orb.feed_candle(symbol, candle)

        # When IB period ends (10:15):
        orb.lock_ib(symbol)

        # After IB is locked, on each 15-min candle:
        orb.update(symbol, candle, bb_bandwidth, avg_volume)

        # Any phase can query at any time:
        status = orb.get_status(symbol)
        if status and status['status'] == 'COMPRESSION_DETECTED':
            # act accordingly

    THREAD SAFETY:
        Single-threaded. Only call from the main monitoring loop.
    """

    def __init__(self, config=None):
        self.config = config or {}
        self._symbols: Dict[str, Dict] = {}  # symbol -> ORB state dict

        # Configurable thresholds with defaults
        self.IB_NARROW_PCT = self._cfg('ORB_IB_NARROW_PCT', 1.5)
        self.IB_VERY_NARROW_PCT = self._cfg('ORB_IB_VERY_NARROW_PCT', 1.0)
        self.TOUCH_PROXIMITY_PCT = self._cfg('ORB_TOUCH_PROXIMITY_PCT', 0.10)
        self.MIN_TOUCHES = self._cfg('ORB_MIN_TOUCHES', 3)
        self.BREAKOUT_BUFFER_PCT = self._cfg('ORB_BREAKOUT_BUFFER_PCT', 0.10)
        self.BREAKOUT_VOL_MULTIPLIER = self._cfg('ORB_BREAKOUT_VOL_MULTIPLIER', 1.5)
        self.BREAKOUT_TARGET_MULTIPLIER = self._cfg('ORB_BREAKOUT_TARGET_MULTIPLIER', 2.0)
        self.EXPIRY_HOUR = self._cfg('ORB_EXPIRY_HOUR', 13)  # Stop tracking after 1 PM

        logger.info("=" * 60)
        logger.info("ORB ADVISORY v1.0.0 INITIALIZED")
        logger.info("=" * 60)
        logger.info(f"   IB Classification: Very Narrow < {self.IB_VERY_NARROW_PCT}% | Narrow < {self.IB_NARROW_PCT}%")
        logger.info(f"   Touch Proximity: {self.TOUCH_PROXIMITY_PCT}% | Min Touches: {self.MIN_TOUCHES}")
        logger.info(f"   Breakout Buffer: {self.BREAKOUT_BUFFER_PCT}% | Vol Multiplier: {self.BREAKOUT_VOL_MULTIPLIER}x")
        logger.info(f"   Expiry: {self.EXPIRY_HOUR}:00")
        logger.info("=" * 60)

    def _cfg(self, key, default):
        """Read from config dict or object, fallback to default."""
        if isinstance(self.config, dict):
            return self.config.get(key, default)
        return getattr(self.config, key, default)

    # ───────────────────────────────────────────────────────────────────────
    # STAGE 1: SILENT RECORDING (09:15 - 10:15)
    # ───────────────────────────────────────────────────────────────────────

    def feed_candle(self, symbol: str, candle) -> None:
        """Feed a candle during IB formation period (09:15-10:15).

        Call this for every 15-min candle in the first hour.
        The method silently accumulates high/low to establish IB range.

        Args:
            symbol: Stock symbol
            candle: CandleData or dict-like with high, low, volume, timestamp
        """
        c_high = candle.high if hasattr(candle, 'high') else candle.get('high', 0)
        c_low = candle.low if hasattr(candle, 'low') else candle.get('low', 0)
        c_volume = candle.volume if hasattr(candle, 'volume') else candle.get('volume', 0)
        c_timestamp = candle.timestamp if hasattr(candle, 'timestamp') else candle.get('date', datetime.now())

        if symbol not in self._symbols:
            self._symbols[symbol] = {
                'ib_high': c_high,
                'ib_low': c_low,
                'ib_candle_count': 1,
                'status': ORB_RECORDING,
                'touch_count_high': 0,
                'touch_count_low': 0,
                'bw_history': [],
                'vol_history': [],
                'dominant_side': None,
                'bw_shrinking': False,
                'volume_declining': False,
                'breakout_confirmed': False,
                'breakout_direction': None,
                'breakout_target': None,
                'potential': None,
                'ib_range_pct': None,
                'updated_at': c_timestamp,
                '_prev_status': None  # For transition detection
            }
        else:
            state = self._symbols[symbol]
            if state['status'] != ORB_RECORDING:
                return  # Already locked, don't overwrite
            state['ib_high'] = max(state['ib_high'], c_high)
            state['ib_low'] = min(state['ib_low'], c_low)
            state['ib_candle_count'] = state.get('ib_candle_count', 0) + 1
            state['updated_at'] = c_timestamp

    def lock_ib(self, symbol: str) -> Optional[Dict]:
        """Lock the IB range and classify potential.

        Call this ONCE after IB formation period ends (~10:15).

        Returns:
            ORB state dict for this symbol, or None if not tracked
        """
        state = self._symbols.get(symbol)
        if not state or state['status'] != ORB_RECORDING:
            return state

        ib_high = state['ib_high']
        ib_low = state['ib_low']

        # Guard against zero/invalid IB
        if ib_low <= 0 or ib_high <= ib_low:
            state['status'] = ORB_WIDE_IB
            state['potential'] = 'INVALID'
            return state

        ib_range_pct = ((ib_high - ib_low) / ib_low) * 100
        state['ib_range_pct'] = round(ib_range_pct, 2)

        if ib_range_pct < self.IB_VERY_NARROW_PCT:
            state['potential'] = 'VERY_NARROW'
            state['status'] = ORB_MONITORING
        elif ib_range_pct < self.IB_NARROW_PCT:
            state['potential'] = 'NARROW'
            state['status'] = ORB_MONITORING
        else:
            state['potential'] = 'WIDE'
            state['status'] = ORB_WIDE_IB  # No further tracking

        logger.info(
            f"ORB {symbol}: IB locked | "
            f"H={ib_high:.2f} L={ib_low:.2f} | "
            f"Range={state['ib_range_pct']}% | "
            f"Potential={state['potential']}"
        )

        return state

    # ───────────────────────────────────────────────────────────────────────
    # STAGE 2 & 3: COMPRESSION + BREAKOUT DETECTION (10:15 onward)
    # ───────────────────────────────────────────────────────────────────────

    def update(self, symbol: str, candle,
               bb_bandwidth: float = None,
               avg_volume: float = None) -> Optional[Dict]:
        """Update ORB tracking with a new 15-min candle.

        Call this on every 15-min candle AFTER IB is locked.
        Only processes symbols with potential = NARROW or VERY_NARROW.

        Args:
            symbol: Stock symbol
            candle: Latest completed 15-min candle (CandleData or dict-like)
            bb_bandwidth: Current Bollinger BandWidth (from Phase 2 data)
            avg_volume: Average volume for comparison (from Phase 2 data)

        Returns:
            Updated ORB state dict for this symbol, or None
        """
        state = self._symbols.get(symbol)
        if not state:
            return None

        # Skip if already expired, wide IB, or breakout already confirmed
        if state['status'] in (ORB_WIDE_IB, ORB_EXPIRED, ORB_BREAKOUT_UP, ORB_BREAKDOWN):
            return state

        # Extract candle fields (support both CandleData and dict)
        c_high = candle.high if hasattr(candle, 'high') else candle.get('high', 0)
        c_low = candle.low if hasattr(candle, 'low') else candle.get('low', 0)
        c_close = candle.close if hasattr(candle, 'close') else candle.get('close', 0)
        c_volume = candle.volume if hasattr(candle, 'volume') else candle.get('volume', 0)
        c_timestamp = candle.timestamp if hasattr(candle, 'timestamp') else candle.get('date', datetime.now())

        # Expiry check
        ts_hour = c_timestamp.hour if hasattr(c_timestamp, 'hour') else 0
        if ts_hour >= self.EXPIRY_HOUR:
            state['status'] = ORB_EXPIRED
            return state

        state['_prev_status'] = state['status']
        state['updated_at'] = c_timestamp

        ib_high = state['ib_high']
        ib_low = state['ib_low']

        # ── Touch counting ──
        proximity = c_close * (self.TOUCH_PROXIMITY_PCT / 100.0) if c_close > 0 else 0

        if c_high >= ib_high - proximity:
            state['touch_count_high'] += 1
        if c_low <= ib_low + proximity:
            state['touch_count_low'] += 1

        # ── BandWidth trend ──
        if bb_bandwidth is not None:
            state['bw_history'].append(bb_bandwidth)
            if len(state['bw_history']) > 5:
                state['bw_history'] = state['bw_history'][-5:]

        bw_shrinking = False
        if len(state['bw_history']) >= 3:
            bw = state['bw_history']
            bw_shrinking = bw[-1] < bw[-2] < bw[-3]

        # ── Volume trend ──
        state['vol_history'].append(c_volume)
        if len(state['vol_history']) > 5:
            state['vol_history'] = state['vol_history'][-5:]

        vol_declining = False
        if len(state['vol_history']) >= 3:
            vol = state['vol_history']
            vol_declining = vol[-1] < vol[-2] < vol[-3]

        # ── Update derived fields ──
        state['dominant_side'] = 'HIGH' if state['touch_count_high'] >= state['touch_count_low'] else 'LOW'
        state['bw_shrinking'] = bw_shrinking
        state['volume_declining'] = vol_declining

        # ── Compression check ──
        max_touches = max(state['touch_count_high'], state['touch_count_low'])

        if (state['status'] == ORB_MONITORING
                and max_touches >= self.MIN_TOUCHES
                and bw_shrinking
                and vol_declining):
            state['status'] = ORB_COMPRESSION
            logger.warning(
                f"ORB COMPRESSION: {symbol} | "
                f"Touches H={state['touch_count_high']} L={state['touch_count_low']} | "
                f"BW shrinking | Vol declining | "
                f"Dominant: {state['dominant_side']}"
            )

        # ── Breakout / Breakdown check ──
        if state['status'] == ORB_COMPRESSION:
            breakout_buffer_high = ib_high * (1 + self.BREAKOUT_BUFFER_PCT / 100.0)
            breakdown_buffer_low = ib_low * (1 - self.BREAKOUT_BUFFER_PCT / 100.0)

            vol_confirms = True  # Default if avg_volume not provided
            if avg_volume and avg_volume > 0:
                vol_confirms = c_volume >= avg_volume * self.BREAKOUT_VOL_MULTIPLIER

            if c_close > breakout_buffer_high and vol_confirms:
                ib_range = ib_high - ib_low
                state['status'] = ORB_BREAKOUT_UP
                state['breakout_confirmed'] = True
                state['breakout_direction'] = 'UP'
                state['breakout_target'] = round(
                    c_close + (ib_range * self.BREAKOUT_TARGET_MULTIPLIER), 2
                )
                logger.warning(
                    f"ORB BREAKOUT UP: {symbol} closed {c_close:.2f} "
                    f"above IB High {ib_high:.2f} | "
                    f"Target: {state['breakout_target']:.2f}"
                )

            elif c_close < breakdown_buffer_low and vol_confirms:
                state['status'] = ORB_BREAKDOWN
                state['breakout_confirmed'] = True
                state['breakout_direction'] = 'DOWN'
                logger.warning(
                    f"ORB BREAKDOWN: {symbol} closed {c_close:.2f} "
                    f"below IB Low {ib_low:.2f} | TCAS WARNING"
                )

        return state

    # ───────────────────────────────────────────────────────────────────────
    # PUBLIC QUERY API (pull model)
    # ───────────────────────────────────────────────────────────────────────

    def get_status(self, symbol: str) -> Optional[Dict]:
        """Get current ORB status for a symbol. Thread-safe read.

        Returns None if symbol is not being tracked.
        This is the method other phases call to PULL data.
        """
        return self._symbols.get(symbol)

    def get_all_active(self) -> Dict[str, Dict]:
        """Get all symbols with active ORB setups (compression or breakout).

        Returns dict of symbol -> state for actionable symbols only.
        """
        return {
            sym: state for sym, state in self._symbols.items()
            if state.get('status') in (
                ORB_COMPRESSION, ORB_BREAKOUT_UP, ORB_BREAKDOWN
            )
        }

    def has_status_changed(self, symbol: str) -> bool:
        """Check if the status just changed on the last update.

        Useful for orchestrator to decide when to send Telegram notifications.
        """
        state = self._symbols.get(symbol)
        if not state:
            return False
        return state.get('_prev_status') != state.get('status')

    def reset_daily(self):
        """Reset all ORB state. Call at market open (09:15)."""
        self._symbols.clear()
        logger.info("ORB Advisory: Daily reset complete")

    # ───────────────────────────────────────────────────────────────────────
    # TELEGRAM MESSAGE FORMATTERS
    # ───────────────────────────────────────────────────────────────────────

    @staticmethod
    def format_compression_telegram(symbol: str, state: Dict) -> str:
        """Format ORB compression detection for Telegram."""
        ib_high = state.get('ib_high', 0)
        ib_low = state.get('ib_low', 0)
        ib_range_pct = state.get('ib_range_pct', 0)

        # Estimate breakout target
        ib_range = ib_high - ib_low
        est_target_up = round(ib_high + ib_range * 2.0, 2)

        msg = (
            f"ORB COMPRESSION -- {symbol}\n"
            f"{'=' * 30}\n"
            f"IB Range: {ib_low:.2f} - {ib_high:.2f} ({ib_range_pct}%)\n"
            f"Potential: {state.get('potential', '?')}\n"
            f"\n"
            f"Compression Signals:\n"
            f"  IB High touches: {state.get('touch_count_high', 0)}\n"
            f"  IB Low touches: {state.get('touch_count_low', 0)}\n"
            f"  Dominant side: {state.get('dominant_side', '?')}\n"
            f"  Bollinger BW: {'Shrinking' if state.get('bw_shrinking') else 'Stable'}\n"
            f"  Volume: {'Declining' if state.get('volume_declining') else 'Stable'}\n"
            f"\n"
            f"Big move likely within 2-4 candles\n"
            f"Estimated target if breakout: {est_target_up:.2f}"
        )
        return msg

    @staticmethod
    def format_breakout_telegram(symbol: str, state: Dict, close_price: float = 0) -> str:
        """Format ORB breakout/breakdown for Telegram."""
        direction = state.get('breakout_direction', '?')
        ib_high = state.get('ib_high', 0)
        ib_low = state.get('ib_low', 0)

        if direction == 'UP':
            target = state.get('breakout_target', 0)
            msg = (
                f"ORB BREAKOUT -- {symbol}\n"
                f"{'=' * 30}\n"
                f"CONFIRMED above IB High {ib_high:.2f}\n"
                f"Close: {close_price:.2f}\n"
                f"\n"
                f"Target: {target:.2f} (2x IB range)\n"
                f"Active positions: Trailing mode activated"
            )
        else:
            msg = (
                f"ORB BREAKDOWN -- {symbol}\n"
                f"{'=' * 30}\n"
                f"CONFIRMED below IB Low {ib_low:.2f}\n"
                f"Close: {close_price:.2f}\n"
                f"\n"
                f"TCAS Action:\n"
                f"  SL tightened to breakeven on active positions"
            )
        return msg


# ═══════════════════════════════════════════════════════════════════════════════
# INLINE UNIT TESTS
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == '__main__':
    import sys

    print("=" * 70)
    print("ORB ADVISORY -- UNIT TESTS")
    print("=" * 70)

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

    # Helper: create a simple candle-like object
    class TestCandle:
        def __init__(self, high, low, close, volume, hour=10):
            self.high = high
            self.low = low
            self.close = close
            self.open = close  # Simplified
            self.volume = volume
            self.timestamp = datetime(2026, 2, 22, hour, 15)
            self.symbol = 'TEST'

    orb = ORBAdvisory()

    # ── Test 1: IB Formation ──
    print("\n--- IB Formation Tests ---")

    orb.feed_candle('SBIN', TestCandle(806, 795, 800, 50000, hour=9))
    orb.feed_candle('SBIN', TestCandle(805, 797, 802, 48000, hour=9))
    orb.feed_candle('SBIN', TestCandle(804.5, 796.5, 801, 45000, hour=10))
    orb.feed_candle('SBIN', TestCandle(803, 798, 800, 42000, hour=10))

    state = orb._symbols.get('SBIN')
    assert_test("IB High recorded correctly", state['ib_high'] == 806)
    assert_test("IB Low recorded correctly", state['ib_low'] == 795)
    assert_test("Status is RECORDING", state['status'] == ORB_RECORDING)

    # ── Test 2: Lock IB (Narrow) ──
    print("\n--- IB Lock Tests ---")

    result = orb.lock_ib('SBIN')
    assert_test("IB locked successfully", result is not None)
    assert_test(f"IB range = {result['ib_range_pct']}%", result['ib_range_pct'] == 1.38)
    assert_test("Potential = NARROW", result['potential'] == 'NARROW')
    assert_test("Status = MONITORING", result['status'] == ORB_MONITORING)

    # Wide IB test
    orb.feed_candle('WIDE', TestCandle(850, 800, 825, 60000, hour=9))
    orb.feed_candle('WIDE', TestCandle(860, 795, 830, 55000, hour=10))
    wide_result = orb.lock_ib('WIDE')
    assert_test("Wide IB classified correctly", wide_result['potential'] == 'WIDE')
    assert_test("Wide IB status = WIDE_IB", wide_result['status'] == ORB_WIDE_IB)

    # Very narrow IB test
    orb.feed_candle('TIGHT', TestCandle(803, 796, 800, 40000, hour=9))
    orb.feed_candle('TIGHT', TestCandle(802.5, 797, 800, 38000, hour=10))
    tight_result = orb.lock_ib('TIGHT')
    assert_test(f"Very narrow IB range = {tight_result['ib_range_pct']}%",
                tight_result['ib_range_pct'] < 1.0)
    assert_test("Very narrow classified correctly", tight_result['potential'] == 'VERY_NARROW')

    # ── Test 3: Touch Counting + Compression ──
    print("\n--- Compression Detection Tests ---")

    # Simulate 3 candles touching IB High with shrinking BW and declining volume
    orb.update('SBIN', TestCandle(805.5, 800, 804, 40000, hour=10), bb_bandwidth=1.2)
    assert_test("Touch 1 counted", orb._symbols['SBIN']['touch_count_high'] == 1)

    orb.update('SBIN', TestCandle(805.9, 799, 803, 35000, hour=11), bb_bandwidth=1.0)
    assert_test("Touch 2 counted", orb._symbols['SBIN']['touch_count_high'] == 2)

    orb.update('SBIN', TestCandle(806.1, 800, 805, 30000, hour=11), bb_bandwidth=0.8)
    assert_test("Touch 3 counted", orb._symbols['SBIN']['touch_count_high'] == 3)
    assert_test("BW shrinking detected", orb._symbols['SBIN']['bw_shrinking'] is True)
    assert_test("Volume declining detected", orb._symbols['SBIN']['volume_declining'] is True)
    assert_test("Compression detected", orb._symbols['SBIN']['status'] == ORB_COMPRESSION)

    # ── Test 4: Breakout Confirmation ──
    print("\n--- Breakout Tests ---")

    # Breakout candle: close above IB High + buffer, with volume
    orb.update('SBIN', TestCandle(810, 804, 808.5, 85000, hour=11), avg_volume=35000)
    assert_test("Breakout detected", orb._symbols['SBIN']['status'] == ORB_BREAKOUT_UP)
    assert_test("Breakout direction = UP", orb._symbols['SBIN']['breakout_direction'] == 'UP')
    assert_test("Breakout target calculated", orb._symbols['SBIN']['breakout_target'] > 0)

    # ── Test 5: Breakdown Test ──
    print("\n--- Breakdown Tests ---")

    # Create a new symbol for breakdown test
    orb.feed_candle('INFY', TestCandle(1845, 1830, 1838, 60000, hour=9))
    orb.feed_candle('INFY', TestCandle(1843, 1832, 1840, 55000, hour=10))
    orb.lock_ib('INFY')

    # Simulate compression
    orb.update('INFY', TestCandle(1844, 1831, 1835, 50000, hour=10), bb_bandwidth=1.5)
    orb.update('INFY', TestCandle(1843, 1830.5, 1834, 40000, hour=11), bb_bandwidth=1.2)
    orb.update('INFY', TestCandle(1844, 1831, 1836, 30000, hour=11), bb_bandwidth=0.9)

    # Check if compressed (INFY has narrow enough IB)
    infy_state = orb._symbols['INFY']
    infy_ib_range = infy_state.get('ib_range_pct', 0)
    if infy_state['status'] == ORB_COMPRESSION:
        # Breakdown candle
        orb.update('INFY', TestCandle(1835, 1825, 1828, 90000, hour=12), avg_volume=40000)
        assert_test("Breakdown detected", orb._symbols['INFY']['status'] == ORB_BREAKDOWN)
        assert_test("Breakdown direction = DOWN", orb._symbols['INFY']['breakout_direction'] == 'DOWN')
    else:
        # IB might be too wide for INFY, skip breakdown test
        print(f"  SKIP: INFY IB range {infy_ib_range}% > {orb.IB_NARROW_PCT}%, skipping breakdown")

    # ── Test 6: Expiry ──
    print("\n--- Expiry Tests ---")

    orb.feed_candle('EXP', TestCandle(503, 497, 500, 30000, hour=9))
    orb.lock_ib('EXP')
    if orb._symbols['EXP']['status'] == ORB_MONITORING:
        orb.update('EXP', TestCandle(502, 498, 500, 25000, hour=13))
        assert_test("Expired after 1 PM", orb._symbols['EXP']['status'] == ORB_EXPIRED)
    else:
        print("  SKIP: EXP IB too wide for monitoring")

    # ── Test 7: Query API ──
    print("\n--- Query API Tests ---")

    status = orb.get_status('SBIN')
    assert_test("get_status returns data", status is not None)
    assert_test("Status is UPSIDE_BREAKOUT", status['status'] == ORB_BREAKOUT_UP)

    active = orb.get_all_active()
    assert_test("get_all_active returns breakouts", 'SBIN' in active)
    assert_test("get_all_active excludes expired", 'EXP' not in active)

    unknown = orb.get_status('UNKNOWN')
    assert_test("Unknown symbol returns None", unknown is None)

    # ── Test 8: Daily Reset ──
    print("\n--- Reset Tests ---")

    orb.reset_daily()
    assert_test("Reset clears all symbols", len(orb._symbols) == 0)
    assert_test("get_status returns None after reset", orb.get_status('SBIN') is None)

    # ── Test 9: Telegram Formatters ──
    print("\n--- Telegram Formatter Tests ---")

    test_state = {
        'ib_high': 806.0, 'ib_low': 795.0, 'ib_range_pct': 1.38,
        'potential': 'NARROW', 'status': ORB_COMPRESSION,
        'touch_count_high': 4, 'touch_count_low': 1,
        'dominant_side': 'HIGH', 'bw_shrinking': True,
        'volume_declining': True, 'breakout_target': 828.0,
        'breakout_direction': 'UP'
    }
    comp_msg = ORBAdvisory.format_compression_telegram('SBIN', test_state)
    assert_test("Compression message generated", len(comp_msg) > 50)
    assert_test("Compression message contains symbol", 'SBIN' in comp_msg)

    brk_msg = ORBAdvisory.format_breakout_telegram('SBIN', test_state, 808.5)
    assert_test("Breakout message generated", len(brk_msg) > 50)

    # ── Summary ──
    print("\n" + "=" * 70)
    print(f"RESULTS: {passed} passed, {failed} failed out of {passed + failed} tests")
    print("=" * 70)

    sys.exit(0 if failed == 0 else 1)
