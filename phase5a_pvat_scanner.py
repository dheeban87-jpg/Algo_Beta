"""
Phase 5A: PVAT (Price-Volume-Acceptance-Trading) Breakout Scanner v5.4.2
═══════════════════════════════════════════════════════════════════════════════

INDEPENDENT 4-ACT PATTERN DETECTOR + EXECUTOR (v5.4.2)

Architecture (v5.4.2):
  Phase 5A = eyes + brain + hands (detect, score, size, execute, handoff)
  Phase 5  = data provider only (stock universe, indicator cache)
  Phase 4  = position monitoring (TCAS/ILS/Kalman exit management)

  Phase 5A detects PVAT breakout → scores independently → sizes → ChatGPT gate
  → places MIS order → deploys capital → hands off to Phase 4 TIER_1

The PVAT Sequence (from charts):
  ACT 1 — LEVEL EXISTS    (PDH/PDL/multi-day S/R from 15-min candles)
  ACT 2 — REJECTION PHASE (price approaches, bounces away — proves level is real)
  ACT 3 — ACCEPTANCE      (price sits AT level for 3+ candles, volume declines)
  ACT 4 — BREAKOUT        (price breaks beyond level + buffer → pass to Phase 5)

Timing (v2.0: candle-aligned 3-loop burst):
  10:15    IB locked → levels computed → monitoring starts
  Every 15-min boundary (10:15, 10:30, ... 14:00):
    Loop 1 (0 sec)  — catch instant breakouts at candle close
    Loop 2 (+30 sec) — breakout candle body forming
    Loop 3 (+90 sec) — candle confirmed, stragglers caught
  14:00    PVAT scanner expires (no new entries)

v5.4.2 changes (INDEPENDENCE):
  - Phase 5A no longer calls Phase 5.execute_pvat_candidate()
  - Own scorer (_calculate_pvat_score), sizer, ChatGPT gate, order placement
  - Direct handoff to Phase 4 TIER_1 monitoring
  - FIX 1: Volume gate at breakout (1.5x avg required)
  - FIX 2: Candle body quality (>=40% body, no dojis)
  - FIX 3: PVAT-specific 5-component scorer (no gap penalty)
  - FIX 4: Coil-to-spike volume bonus
  - FIX 5: ATR-relative breakout buffer (replaces fixed 0.2%)

Author: Algo_Beta v5.4.2
"""

import logging
import time
import json
import os
import numpy as np
from collections import deque
from datetime import datetime, date, time as dt_time, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum

try:
    from phase5_intraday_engine import (
        GapCandidate, GapType, VolumeBurstScore,
        GapTradeDirection, Phase5IntradayEngine
    )
    _PH5_IMPORTS_OK = True
except ImportError:
    _PH5_IMPORTS_OK = False

try:
    from candlestick_pattern_detector import CandlestickPatternDetector, CandleData
    _CANDLE_IMPORTS_OK = True
except ImportError:
    _CANDLE_IMPORTS_OK = False

try:
    from config import Config as _MainConfig
    _MASTER_STOCK_LIST = getattr(_MainConfig, 'MASTER_STOCK_LIST', [])
except ImportError:
    _MASTER_STOCK_LIST = []

try:
    from regret_tracker import log_regret_trade
except ImportError:
    def log_regret_trade(*args, **kwargs):
        pass

logger = logging.getLogger('Phase5A_PVAT')


# ═══════════════════════════════════════════════════════════════════════════════
# ENUMS & DATA CLASSES
# ═══════════════════════════════════════════════════════════════════════════════

class PVATState(Enum):
    IDLE = "IDLE"
    APPROACH = "APPROACH"
    ACCEPTANCE = "ACCEPTANCE"
    BREAKOUT_CONFIRMED = "BREAKOUT_CONFIRMED"
    TRADED = "TRADED"
    REJECTED = "REJECTED"


@dataclass
class PVATStockData:
    """Per-stock PVAT tracking state."""
    symbol: str
    state: PVATState = PVATState.IDLE
    tracked_level_price: float = 0.0
    tracked_level_type: str = ""           # PDH, PDL, MULTI_DAY_HIGH, etc.
    tracked_level_side: str = ""           # RESISTANCE or SUPPORT
    tracked_level_score: int = 0           # v2.1: Level score (0-100) at approach time
    acceptance_start_time: Optional[datetime] = None
    acceptance_candle_count: int = 0
    acceptance_candle_boundary: Optional[datetime] = None  # Track which candle boundary started acceptance
    acceptance_zone_high: float = 0.0
    acceptance_zone_low: float = 0.0
    volume_at_acceptance_start: float = 0.0  # per-candle volume at acceptance start
    volume_declining: bool = False
    last_volume: float = 0.0               # cumulative day volume from kite.quote()
    prev_cumulative_volume: float = 0.0    # previous scan's cumulative volume
    candle_volume: float = 0.0             # computed per-candle delta volume
    prev_state: PVATState = PVATState.IDLE
    last_price: float = 0.0
    approach_time: Optional[datetime] = None
    approach_candle_boundary: Optional[datetime] = None  # v2.1: candle boundary when approach started
    approach_candle_count: int = 0                        # v2.1: candle boundaries spent in approach
    tracked_level_rejections: int = 0                      # v5.4.3: Confirmed rejection count at tracked level
    tracked_level_confluence_days: int = 0                 # v5.4.3: Multi-day confluence count


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN CLASS
# ═══════════════════════════════════════════════════════════════════════════════

class Phase5APVAT:
    """
    Phase 5A: PVAT (Price-Volume-Acceptance-Trading) Breakout Scanner v5.4.3

    INDEPENDENT 4-act pattern detector + executor.
    Detects level acceptance + breakout patterns, then scores, sizes,
    places orders, and hands off to Phase 4 directly.

    v5.4.2: Independent execution (bypass Phase 5 pipeline).
    v5.4.3: Intelligent Level Discovery — rejection-verified scoring,
            multi-day confluence, duplicate merging, proven level filtering.
    Phase 5 kept only for data access (stock universe, indicator cache).

    Dependencies:
      - Kite API (data fetching + order placement)
      - Phase 4 (direct handoff for TIER_1 monitoring)
      - Capital Manager (position sizing + capital deployment)
      - ChatGPT Advisor (pre-entry approval gate)
      - Phase 5 (DATA ONLY — stock universe, instrument tokens)
    """

    def __init__(self, kite, config, telegram, phase4_manager,
                 capital_manager, chatgpt_advisor, phase5_engine,
                 candlestick_detector=None):
        self.kite = kite
        self.config = config
        self.telegram = telegram
        self.phase4 = phase4_manager
        self.capital_manager = capital_manager
        self.chatgpt = chatgpt_advisor
        self.phase5 = phase5_engine  # DATA ONLY — stock universe, indicators
        self.candle_detector = candlestick_detector
        self.orchestrator = None  # Set by orchestrator after init

        # State
        self._trade_fired = False
        self._levels_computed = False
        self._scan_active = False

        # PH5A v2 Sniper state
        self.sniper_pipeline = []
        self.ph5a_scan_complete = False
        self.ph5a_done = False
        self.ph5a_watch_closed = False
        self.sniper_watch_start = None

        # Per-stock tracking
        self._stock_states: Dict[str, PVATStockData] = {}
        self._key_levels: Dict[str, Dict] = {}
        self._candle_cache_15m: Dict[str, List[Dict]] = {}

        # Timing — v5.4.1: Phase 5A is main MIS flow, not time-windowed
        # Runs during market hours. Entry cutoff prevents late trades.
        cutoff_raw = getattr(config, 'PVAT_MIS_ENTRY_CUTOFF', '15:10')
        if isinstance(cutoff_raw, str):
            h, m = map(int, cutoff_raw.split(':'))
            self.MIS_ENTRY_CUTOFF = dt_time(h, m)
        else:
            self.MIS_ENTRY_CUTOFF = cutoff_raw

        self._last_boundary_scanned: Optional[datetime] = None  # Last 15-min boundary we scanned

        # v5.6.1: Paper trading mode — GUI-controlled via orchestrator setattr
        self._paper_mode = bool(getattr(config, 'PH5A_PAPER_MODE', False) or getattr(config, 'MASTER_PAPER_MODE', False))
        self._paper_log_path = os.path.join('data', 'ph5a_paper_trades.json')
        self._paper_counter = 0
        self._last_candle_time = None   # Track 15-min candle boundaries for acceptance counting
        self._scan_count = 0            # Running scan counter for LOG 4

        # v5.4.4: Adaptive scan frequency — WARM/HOT zones near breakout
        self._last_scan_time: Optional[datetime] = None   # Last time any scan ran
        self._current_scan_mode = 'NORMAL'                # NORMAL / WARM / HOT

        # v5.8.0: GUI activity log — recent events for radar state
        self._recent_events: deque = deque(maxlen=30)

        logger.info("Phase 5A PVAT Scanner v5.4.4 initialized (adaptive frequency, independent executor)")

    def _log_event(self, text: str, level: str = 'info'):
        """v5.8.0: Append a timestamped event for GUI activity log."""
        ts = datetime.now().strftime('%H:%M:%S')
        self._recent_events.append({'time': ts, 'text': text, 'level': level})

    # ─────────────────────────────────────────────────────────────────
    # PUBLIC API
    # ─────────────────────────────────────────────────────────────────

    def is_active(self) -> bool:
        """Can Phase 5A run right now? Main MIS flow — not time-gated."""
        if self._trade_fired:
            return False
        if not getattr(self.config, 'PVAT_ENABLED', False):
            return False
        now = datetime.now().time()
        # v5.4.1: Market hours only (not a fixed scan window)
        market_open = dt_time(9, 15)
        hard_stop = dt_time(15, 25)
        if not (market_open <= now <= hard_stop):
            return False
        # Don't stack MIS — check if Phase 4 already managing a tier1 position
        if (self.phase4 and hasattr(self.phase4, 'has_tier1_positions') and
                self.phase4.has_tier1_positions()):
            return False
        return True

    def _get_closest_breakout_distance(self) -> Tuple[float, Optional[str]]:
        """
        v5.4.4: Find the minimum distance (%) from current price to breakout trigger
        across all APPROACH and ACCEPTANCE stocks.

        Uses ATR-based breakout buffer (matching _check_breakout_gates) for accurate
        distance calculation.

        Returns:
            (min_distance_pct, symbol) — closest stock to breakout, or (999, None)
        """
        min_dist = 999.0
        closest_sym = None

        for symbol, data in self._stock_states.items():
            if data.state not in (PVATState.APPROACH, PVATState.ACCEPTANCE):
                continue
            if data.last_price <= 0 or data.tracked_level_price <= 0:
                continue

            # Compute actual breakout trigger price (ATR-based, same as _check_breakout_gates)
            atr = self._key_levels.get(symbol, {}).get('atr_15m', 0)
            atr_factor = getattr(self.config, 'PVAT_BREAKOUT_ATR_FACTOR', 0.3)
            if atr > 0:
                buffer = atr * atr_factor
            else:
                buffer_pct = getattr(self.config, 'PVAT_BREAKOUT_BUFFER_PCT', 0.2)
                buffer = data.tracked_level_price * (buffer_pct / 100)

            if data.tracked_level_side == 'RESISTANCE':
                breakout_price = data.tracked_level_price + buffer
                # Distance: how far below breakout price
                dist_pct = (breakout_price - data.last_price) / data.last_price * 100
            else:
                breakout_price = data.tracked_level_price - buffer
                # Distance: how far above breakout price (for support breakdown)
                dist_pct = (data.last_price - breakout_price) / data.last_price * 100

            # Clamp negative (already past breakout) to 0
            dist_pct = max(0.0, dist_pct)

            if dist_pct < min_dist:
                min_dist = dist_pct
                closest_sym = symbol

        return min_dist, closest_sym

    def _determine_scan_mode(self) -> Tuple[str, float, Optional[str]]:
        """
        v5.4.4: Determine scan mode based on closest breakout distance.

        Returns:
            (mode, distance, symbol)
            mode: 'HOT' / 'WARM' / 'NORMAL'
        """
        warm_pct = getattr(self.config, 'PVAT_WARM_ZONE_PCT', 1.0)
        hot_pct = getattr(self.config, 'PVAT_HOT_ZONE_PCT', 0.3)

        dist, sym = self._get_closest_breakout_distance()

        if dist <= hot_pct:
            return 'HOT', dist, sym
        elif dist <= warm_pct:
            return 'WARM', dist, sym
        else:
            return 'NORMAL', dist, sym

    def run_scan_cycle(self) -> Optional[Dict]:
        """
        Called by orchestrator every main loop (10-60 sec).

        v5.4.4: ADAPTIVE SCAN FREQUENCY based on proximity to breakout.

        Scan modes:
            NORMAL (>1.0% from BO):  Every 15-min candle boundary, 3-loop burst
            WARM   (0.3%-1.0%):      Every 5-min boundary, 3-loop burst
            HOT    (<0.3%):          Every 2-min, single scan (no burst delay)

        If breakout found → execute independently, return result.
        If trade already fired today → skip.
        """
        if not self.is_active():
            return None

        now = datetime.now()

        # v5.4.1: Entry cutoff — scanner keeps evaluating but won't commit capital
        if now.time() > self.MIS_ENTRY_CUTOFF:
            logger.debug(f"PVAT: Past {self.MIS_ENTRY_CUTOFF.strftime('%H:%M')} entry cutoff — scanning only, no new trades")
            return None

        # Step 1: Compute levels (one-time at first scan)
        if not self._levels_computed:
            self._fetch_historical_and_compute_levels()
            self._levels_computed = True

        # Step 2: Determine scan mode from closest breakout distance
        mode, bo_dist, bo_sym = self._determine_scan_mode()
        prev_mode = self._current_scan_mode
        self._current_scan_mode = mode

        # Log mode transitions
        if mode != prev_mode:
            mode_emoji = {'HOT': '🔴', 'WARM': '🟡', 'NORMAL': '🟢'}
            logger.info(
                f"{mode_emoji.get(mode, '⚪')} PVAT Scan Mode: {prev_mode} → {mode}"
                f"{f' — {bo_sym} {bo_dist:.2f}% from breakout' if bo_sym else ''}"
            )

        # Step 3: Determine boundary interval based on mode
        if mode == 'HOT':
            boundary_minutes = 2
        elif mode == 'WARM':
            boundary_minutes = 5
        else:
            boundary_minutes = 15

        # Compute current boundary for this mode's interval
        current_boundary = now.replace(
            minute=(now.minute // boundary_minutes) * boundary_minutes,
            second=0, microsecond=0
        )

        # Already scanned this boundary?
        if self._last_boundary_scanned and self._last_boundary_scanned >= current_boundary:
            return None  # Wait for next boundary

        # Step 4: Configure loop behavior per mode
        if mode == 'HOT':
            # HOT: single immediate scan, no sleep delays (speed is critical)
            loop_config = [(1, 0)]  # 1 loop, 0 delay
            burst_label = "HOT-single"
        elif mode == 'WARM':
            # WARM: 2-loop mini-burst (0s, 30s)
            loop_config = [(1, 0), (2, 30)]
            burst_label = "WARM-2loop"
        else:
            # NORMAL: full 3-loop burst (0s, 30s, 90s)
            loop_config = [(1, 0), (2, 30), (3, 90)]
            burst_label = "NORM-3loop"

        total_loops = len(loop_config)

        # Step 5: Log burst start
        mode_emoji = {'HOT': '🔴', 'WARM': '🟡', 'NORMAL': '🟢'}
        bo_info = f" | {bo_sym} {bo_dist:.2f}% from BO" if bo_sym and bo_dist < 999 else ""
        logger.info(
            f"📡 PVAT: {mode_emoji.get(mode, '⚪')} {mode} {boundary_minutes}-min boundary "
            f"{current_boundary.strftime('%H:%M')} — {burst_label}{bo_info}"
        )

        # Step 6: Run scan loops
        for loop_num, delay in loop_config:
            if delay > 0:
                time.sleep(delay)

            # Refresh quotes for all tracked stocks
            self._update_current_candles()

            # Update state machine for each stock
            breakout_signals = []
            for symbol in list(self._stock_states.keys()):
                signal = self._update_pvat_state(symbol)
                if signal and signal.get('state') == 'BREAKOUT_CONFIRMED':
                    breakout_signals.append(signal)

            # Log scan summary
            self._scan_count += 1
            state_counts = self._count_states()
            logger.info(
                f"📡 PVAT #{self._scan_count} ({mode_emoji.get(mode, '⚪')}{mode} "
                f"Loop {loop_num}/{total_loops} @ +{delay}s): "
                f"{len(self._stock_states)} tracked | "
                f"✈️ {state_counts.get('APPROACH', 0)} approach | "
                f"➡️ {state_counts.get('ACCEPTANCE', 0)} accept | "
                f"🎯 {len(breakout_signals)} breakout"
            )
            self._log_event(
                f"Scan #{self._scan_count} ({mode}): "
                f"{len(self._stock_states)} tracked, "
                f"{state_counts.get('APPROACH', 0)} approach, "
                f"{state_counts.get('ACCEPTANCE', 0)} accept, "
                f"{len(breakout_signals)} breakout"
            )

            # v5.7.0: Write radar state for GUI
            self._write_radar_state()

            # Telegram: ONE consolidated status on last loop of each burst
            if loop_num == total_loops and len(self._stock_states) > 0:
                self._notify_pvat_scan_summary(state_counts)

            # Breakout found → execute independently
            if breakout_signals:
                breakout_signals.sort(
                    key=lambda s: s.get('acceptance_candle_count', 0), reverse=True
                )
                best = breakout_signals[0]

                logger.warning(
                    f"🎯 PVAT BREAKOUT: {best['symbol']} | "
                    f"Level: {best['level_type']} @ ₹{best['level_price']:.2f} | "
                    f"Acceptance: {best['acceptance_candle_count']} candles"
                )

                # Print visual flight path
                self._print_pvat_flight_path(best)

                # v5.4.2: INDEPENDENT EXECUTION — bypass Phase 5 entirely
                sym = best['symbol']
                stock_data = self._stock_states.get(sym)
                if stock_data:
                    result = self._execute_pvat_pipeline(sym, stock_data)
                    if result.get('traded'):
                        self._stock_states[sym].state = PVATState.TRADED
                        self._log_pvat_mission_complete_v2(sym, best, result)
                        self._last_boundary_scanned = current_boundary
                        return {'symbol': sym, 'result': result}
                    else:
                        # Pipeline rejected (score/ChatGPT/order/fill)
                        self._stock_states[sym].state = PVATState.REJECTED
                        self._stock_states[sym].prev_state = PVATState.BREAKOUT_CONFIRMED
                        self._log_pvat_mission_failed(sym, best, result.get('reason', 'Unknown rejection'))

                # Breakout handled (success or reject) — stop burst
                self._last_boundary_scanned = current_boundary
                return None

            # No breakout in this loop — continue to next loop

        # All loops done, no breakout
        self._last_boundary_scanned = current_boundary
        return None

    def reset_daily(self):
        """Reset state for new trading day."""
        self._trade_fired = False
        self._levels_computed = False
        self._scan_active = False
        self._stock_states.clear()
        self._key_levels.clear()
        self._candle_cache_15m.clear()
        self._last_boundary_scanned = None
        self._last_candle_time = None
        self._scan_count = 0
        self._last_scan_time = None
        self._current_scan_mode = 'NORMAL'

        # PH5A v2 Sniper state reset
        self.sniper_pipeline = []
        self.ph5a_scan_complete = False
        self.ph5a_done = False
        self.ph5a_watch_closed = False
        self.sniper_watch_start = None

        logger.info("Phase 5A PVAT: Daily state reset (including Sniper)")

    def reset_for_rescan(self):
        """
        v5.9.0: Reset sniper state for a new hunting scan cycle.
        Keeps computed levels (PDH/PDL/POC/IB) warm — only clears
        pipeline and scan/watch flags. Called by orchestrator before
        each HUNTING mode rescan.
        """
        self.sniper_pipeline = []
        self.ph5a_scan_complete = False
        self.ph5a_done = False
        self.ph5a_watch_closed = False
        self.sniper_watch_start = None
        logger.info("PH5A: Reset for rescan (levels preserved)")

    # ─────────────────────────────────────────────────────────────────
    # PH5A v2 SNIPER MODEL (FIX 2-6)
    # ─────────────────────────────────────────────────────────────────

    def _calculate_sniper_score(self, stock_data: PVATStockData) -> float:
        """
        Sniper-specific scoring using data available at APPROACH state.
        Replaces _calculate_pvat_score for elite filter because the original
        PVAT composite score requires ACCEPTANCE candles (always 0 in single scan).

        Components (max 100+):
          1. Level historical strength (0-35): from rejection-verified level_score
          2. Rejection density       (0-25): more rejections = stronger level
          3. Multi-day confluence     (0-20): more days = more proven
          4. Proximity to level       (0-10): closer = more imminent trigger
          5. Candle body quality      (0-10): strong body = institutional intent
        """
        score = 0.0
        symbol = stock_data.symbol

        # 1. Level historical strength (0-35)
        level_score = stock_data.tracked_level_score or 0  # 0-100 from _score_level
        score += (level_score / 100) * 35

        # 2. Rejection density (0-25): 10 rejections = full 25
        rejections = stock_data.tracked_level_rejections or 0
        rej_pts = min(25, rejections * 2.5)
        score += rej_pts

        # 3. Multi-day confluence (0-20): 4 days = full 20
        confluence = stock_data.tracked_level_confluence_days or 0
        conf_pts = min(20, confluence * 5)
        score += conf_pts

        # 4. Proximity to level (0-10): 0% = 10pts, 0.3% = 0pts
        if stock_data.tracked_level_price > 0 and stock_data.last_price > 0:
            dist = abs(stock_data.last_price - stock_data.tracked_level_price) / stock_data.tracked_level_price * 100
            prox_pts = max(0, 10 - dist * 33.33)
        else:
            prox_pts = 0
        score += prox_pts

        # 5. Candle body quality (0-10): strong body = institutional intent
        if hasattr(stock_data, 'candle_open') and hasattr(stock_data, 'candle_close'):
            candle_open = stock_data.candle_open or 0
            candle_close = stock_data.candle_close or 0
            candle_high = getattr(stock_data, 'candle_high', 0) or 0
            candle_low = getattr(stock_data, 'candle_low', 0) or 0
            candle_range = candle_high - candle_low
            if candle_range > 0:
                body_ratio = abs(candle_close - candle_open) / candle_range
                body_pts = min(10, body_ratio * 10)
            else:
                body_pts = 5  # neutral
        else:
            body_pts = 5  # neutral
        score += body_pts

        # ── PMBI Bias Alignment Bonus ── v5.5.0
        pmbi_bonus = 0
        try:
            market_bias = getattr(self.config, '_pmbi_market_bias', None)
            if market_bias and market_bias.get('direction') != 'MIXED':
                bias_priority = market_bias.get('priority', 'NEUTRAL')
                trade_direction = getattr(stock_data, '_sniper_direction', 'BUY')
                bonus_pts = getattr(self.config, 'PMBI_BIAS_SCORE_BONUS', 5)

                if bias_priority == trade_direction:
                    pmbi_bonus = bonus_pts
                    logger.info(f"      🧠 PMBI +{bonus_pts}: {trade_direction} aligns with {bias_priority} bias")
        except Exception:
            pass

        score += pmbi_bonus

        return round(score, 1)  # v5.5.0: uncapped — PMBI bonus can push above 100

    def passes_elite_filter(self, stock_data: PVATStockData) -> bool:
        """
        FIX 2: 5-criteria elite filter. Only battle-tested levels pass.
        ALL 5 must be True.

        Uses sniper-specific scoring (not PVAT composite) because the original
        PVAT score requires ACCEPTANCE candles which are always 0 in single-scan.

        Criterion 6 (volume ratio) removed: unreliable at 09:30 open candle
        (pre-open auction inflation + opening rush makes ratio non-filtering).

        Returns:
            True if stock passes all elite criteria.
        """
        symbol = stock_data.symbol
        levels = self._key_levels.get(symbol, {})

        level_type_upper = stock_data.tracked_level_type.upper() if stock_data.tracked_level_type else ''
        is_ib_level = level_type_upper in ('IB_HIGH', 'IBH', 'IB_LOW', 'IBL')

        # IB levels (IB_HIGH / IB_LOW) are intraday — formed today, so they
        # naturally have fewer rejections and 0 confluence days.
        # Use relaxed thresholds for IB; standard thresholds for PDH/PDL/POC.
        if is_ib_level:
            min_score      = getattr(self.config, 'PH5A_ELITE_IB_MIN_SCORE',      60)
            min_rejections = getattr(self.config, 'PH5A_ELITE_IB_MIN_REJECTIONS',  2)
            min_confluence = getattr(self.config, 'PH5A_ELITE_IB_MIN_CONFLUENCE',  0)
            max_distance   = getattr(self.config, 'PH5A_ELITE_IB_MAX_DISTANCE',   0.3)
        else:
            min_score      = getattr(self.config, 'PH5A_ELITE_MIN_SCORE',         75)
            min_rejections = getattr(self.config, 'PH5A_ELITE_MIN_REJECTIONS',     5)
            min_confluence = getattr(self.config, 'PH5A_ELITE_MIN_CONFLUENCE',     3)
            max_distance   = getattr(self.config, 'PH5A_ELITE_MAX_DISTANCE',      0.3)

        # Criterion 1: Sniper score
        score = self._calculate_sniper_score(stock_data)
        c1 = score >= min_score

        # Criterion 2: Rejection count
        rejections = stock_data.tracked_level_rejections
        c2 = rejections >= min_rejections

        # Criterion 3: Confluence days
        confluence = stock_data.tracked_level_confluence_days
        c3 = confluence >= min_confluence

        # Criterion 4: Distance to level
        if stock_data.tracked_level_price > 0 and stock_data.last_price > 0:
            dist_pct = abs(stock_data.last_price - stock_data.tracked_level_price) / stock_data.tracked_level_price * 100
        else:
            dist_pct = 999
        c4 = dist_pct <= max_distance

        # Criterion 5: Level type — PDH/PDL/POC/MDH/MDL + IB levels allowed
        allowed_types = getattr(self.config, 'PH5A_ELITE_LEVEL_TYPES',
                                ['PDH', 'PDL', 'POC', 'MDH', 'MDL',
                                 'IB_HIGH', 'IBH', 'IB_LOW', 'IBL',
                                 'MULTI_DAY_HIGH', 'MULTI_DAY_LOW'])
        c5 = level_type_upper in [t.upper() for t in allowed_types]

        # Criterion 6: Trend alignment
        # A BUY breakout (approaching resistance from below) must have price ABOVE its
        # 20-period MA on the 15-min chart — trading WITH the short-term trend.
        # A SELL breakdown must have price BELOW its 20-period MA.
        # POC is bidirectional — skip this check.
        # Lesson learned (2026-04-16 CIPLA): CIPLA was approaching PDH from below while
        # trading below MA20 AND EMA21. That is a stock approaching resistance against the
        # trend — a fade candidate, not a breakout. Score 81 + 6 rejections looked strong
        # but the underlying trend was bearish. The trade had no wind at its back.
        direction = getattr(stock_data, '_sniper_direction', 'BUY')
        is_poc = 'POC' in level_type_upper
        c6 = True        # default pass for POC
        trend_note = 'N/A (POC)'
        trend_aligned = None   # None = unknown, True = aligned, False = against
        price_vs_ma20 = 'N/A'
        ma20_val = None
        if not is_poc:
            candles_15m = self._candle_cache_15m.get(symbol, [])
            if len(candles_15m) >= 20:
                closes = [c['close'] for c in candles_15m[-20:]]
                ma20_val = sum(closes) / len(closes)
                current = stock_data.last_price
                if direction == 'BUY':
                    c6 = current >= ma20_val
                    price_vs_ma20 = 'ABOVE' if c6 else 'BELOW'
                    trend_aligned = c6
                    trend_note = f"price ₹{current:.1f} vs MA20 ₹{ma20_val:.1f} ({price_vs_ma20})"
                else:  # SELL
                    c6 = current <= ma20_val
                    price_vs_ma20 = 'BELOW' if c6 else 'ABOVE'
                    trend_aligned = c6
                    trend_note = f"price ₹{current:.1f} vs MA20 ₹{ma20_val:.1f} ({price_vs_ma20})"
            else:
                # Cache not ready — BLOCK rather than silently pass.
                # This prevents a race condition where Criterion 6 defaults to True
                # because _candle_cache_15m hasn't been populated yet for this symbol.
                # The stock will be re-evaluated on the next scan when cache is ready.
                c6 = False
                trend_note = f'cache not ready ({len(candles_15m)} candles) — blocked until next scan'
                trend_aligned = False
                logger.warning(f"  {symbol}: Criterion 6 BLOCKED — candle cache not ready, will retry next scan")

        # Store trend data on stock_data so the entry signal builder can pass it to Claude
        stock_data._trend_aligned = trend_aligned
        stock_data._price_vs_ma20 = price_vs_ma20
        stock_data._trend_note = trend_note
        stock_data._ma20_val = ma20_val

        passed = c1 and c2 and c3 and c4 and c5 and c6

        # Log criteria for debugging
        logger.info(f"  Elite Filter {symbol}: "
                    f"SniperScore={score:.0f}({'PASS' if c1 else 'FAIL'}) | "
                    f"Rej={rejections}({'PASS' if c2 else 'FAIL'}) | "
                    f"Conf={confluence}d({'PASS' if c3 else 'FAIL'}) | "
                    f"Dist={dist_pct:.2f}%({'PASS' if c4 else 'FAIL'}) | "
                    f"Type={level_type_upper}({'PASS' if c5 else 'FAIL'}) | "
                    f"Trend={'PASS' if c6 else 'FAIL'}({trend_note}) | "
                    f"{'ELITE' if passed else 'FILTERED'}")

        # Store score for pipeline sorting
        stock_data._elite_score = score if passed else 0

        return passed

    def run_sniper_scan(self):
        """
        FIX 3: Single scan gate. Called ONCE by orchestrator after:
          - PH5 Gap is complete (or disabled)
          - Time >= 09:30
        """
        logger.info("")
        logger.info("=" * 80)
        logger.info("  PH5A v2 SNIPER: Single Scan Starting")
        logger.info("=" * 80)

        # SINGLE SCAN: Compute levels using existing PVAT logic
        if not self._levels_computed:
            self._fetch_historical_and_compute_levels()
            self._levels_computed = True

        # Refresh quotes for all stocks
        self._update_current_candles()

        # Update state machine for each stock to get APPROACH/ACCEPTANCE states
        for symbol in list(self._stock_states.keys()):
            self._update_pvat_state(symbol)

        # ELITE FILTER
        elite_stocks = []
        for symbol, data in self._stock_states.items():
            # Only consider stocks in APPROACH or ACCEPTANCE state
            if data.state not in (PVATState.APPROACH, PVATState.ACCEPTANCE):
                continue

            direction = 'BUY' if data.tracked_level_side == 'RESISTANCE' else 'SELL'
            data._sniper_direction = direction

            if self.passes_elite_filter(data):
                elite_stocks.append(data)

        # v1.3.0: Phase 9 briefing — sector avoid filter
        # Orchestrator stamps self.daily_briefing after morning_briefing() runs.
        # sector_avoid removes stocks whose symbol is tagged with an avoided sector.
        # sector_focus is used for score-boosting below (not hard exclusion).
        _briefing = getattr(self, 'daily_briefing', {})
        _sector_avoid = [s.upper() for s in _briefing.get('sector_avoid', [])]
        _sector_focus = [s.upper() for s in _briefing.get('sector_focus', [])]

        if _sector_avoid:
            pre_filter_count = len(elite_stocks)
            elite_stocks = [
                s for s in elite_stocks
                if not any(
                    av in (getattr(s, 'sector', '') or '').upper()
                    for av in _sector_avoid
                )
            ]
            removed = pre_filter_count - len(elite_stocks)
            if removed:
                logger.info(f"PH5A Briefing: {removed} stock(s) removed — sector in avoid list {_sector_avoid}")

        # v1.3.0: Boost score for stocks in sector_focus (soft preference, not hard gate)
        if _sector_focus:
            for s in elite_stocks:
                sym_sector = (getattr(s, 'sector', '') or '').upper()
                if any(f in sym_sector for f in _sector_focus):
                    s._elite_score = getattr(s, '_elite_score', 0) + 10  # +10 boost
                    logger.info(f"PH5A Briefing: {s.symbol} score +10 — sector '{sym_sector}' in focus list")

        # PIPELINE CAP: Sort by PVAT score (descending), take top 3
        max_pipeline = getattr(self.config, 'PH5A_MAX_PIPELINE', 3)
        elite_stocks.sort(key=lambda x: getattr(x, '_elite_score', 0), reverse=True)

        # v5.5.0: PMBI bias-aligned sorting — bias-aligned trades come first
        # v1.3.0: Also uses Phase 9 market_bias via _pmbi_market_bias (set by propagation)
        market_bias = getattr(self.config, '_pmbi_market_bias', None)
        if market_bias and market_bias.get('direction') != 'MIXED':
            bias_priority = market_bias.get('priority', 'NEUTRAL')
            elite_stocks.sort(key=lambda s: (
                1 if getattr(s, '_sniper_direction', '') == bias_priority else 0,
                getattr(s, '_elite_score', 0)
            ), reverse=True)

        pipeline = elite_stocks[:max_pipeline]

        # RESULT
        if len(pipeline) == 0:
            logger.info("PH5A Sniper: 0 stocks passed Elite Filter. NO TRADE TODAY.")
            if self.telegram:
                try:
                    self.telegram.send_message(
                        "PH5A Sniper: 0 elite setups found. Walking away. Capital preserved"
                    )
                except Exception:
                    pass
            self.ph5a_done = True
            self.ph5a_scan_complete = True
            self._write_radar_state()
            return

        # Store pipeline
        self.sniper_pipeline = pipeline
        self.sniper_watch_start = datetime.now()
        self.ph5a_scan_complete = True
        self._write_radar_state()

        # Initialize sniper-specific fields on pipeline stocks
        for stock in self.sniper_pipeline:
            stock.triggered = False
            stock.exited = False
            stock.entry_price = 0.0
            stock.entry_time = None
            stock.filled_qty = 0           # Actual filled quantity (Flaw 3 fix)
            stock.stop_price = 0.0
            stock.target_price = 0.0
            stock.stop_order_id = None
            stock.target_order_id = None
            stock.exit_reason = None
            stock.exit_price = 0.0
            stock.stall_start = None
            stock.stall_price = 0.0
            stock.direction = getattr(stock, '_sniper_direction', 'BUY')

        logger.info(f"PH5A Sniper: {len(pipeline)} elite stocks in pipeline: "
                    f"{[s.symbol for s in pipeline]}")
        logger.info("=" * 80)

        if self.telegram:
            try:
                stock_details = "\n".join([
                    f"  {s.symbol} | {s.tracked_level_type} @ {s.tracked_level_price:.2f} | "
                    f"Score: {getattr(s, '_elite_score', 0):.0f} | Rej: {s.tracked_level_rejections} | "
                    f"Dir: {s.direction}"
                    for s in pipeline
                ])
                self.telegram.send_message(
                    f"PH5A Sniper: {len(pipeline)} elite stocks in pipeline\n\n"
                    f"{stock_details}\n\n"
                    f"Watch window: 09:30-10:30"
                )
            except Exception:
                pass

    def _check_oco_fills(self, stock):
        """
        OCO check for triggered positions during watch window.
        If stop fills -> cancel target (and vice versa).
        Prevents double-exit race condition (Flaw 2 fix).
        """
        # Check stop order
        if stock.stop_order_id:
            try:
                history = self.kite.order_history(stock.stop_order_id)
                if history and history[-1].get('status') == 'COMPLETE':
                    # Stop hit — cancel target immediately
                    if stock.target_order_id:
                        try:
                            self.kite.cancel_order(
                                variety=self.kite.VARIETY_REGULAR,
                                order_id=stock.target_order_id
                            )
                            logger.info(f"  OCO: {stock.symbol} stop filled, target cancelled")
                        except Exception:
                            pass
                    stock.exited = True
                    stock.exit_reason = 'STOP_HIT'
                    stock.exit_price = history[-1].get('average_price', stock.stop_price)
                    self._log_sniper_exit(stock)
                    self._release_sniper_capital(stock)
                    return
            except Exception:
                pass

        # Check target order
        if stock.target_order_id:
            try:
                history = self.kite.order_history(stock.target_order_id)
                if history and history[-1].get('status') == 'COMPLETE':
                    # Target hit — cancel stop immediately
                    if stock.stop_order_id:
                        try:
                            self.kite.cancel_order(
                                variety=self.kite.VARIETY_REGULAR,
                                order_id=stock.stop_order_id
                            )
                            logger.info(f"  OCO: {stock.symbol} target filled, stop cancelled")
                        except Exception:
                            pass
                    stock.exited = True
                    stock.exit_reason = 'TARGET_HIT'
                    stock.exit_price = history[-1].get('average_price', stock.target_price)
                    self._log_sniper_exit(stock)
                    self._release_sniper_capital(stock)
                    return
            except Exception:
                pass

    def run_sniper_watch(self):
        """
        FIX 4: Monitor pipeline stocks. Called every ~30 seconds during watch window.
        Price crosses level -> IMMEDIATE entry (no candle counting).
        Also checks OCO fills for already-triggered positions (Flaw 2 fix).
        """
        if not self.sniper_pipeline:
            return

        for stock in self.sniper_pipeline:
            if stock.exited:
                continue  # Already exited, nothing to do

            if stock.triggered:
                # OCO check: did stop or target fill while we were watching?
                self._check_oco_fills(stock)
                continue

            # Get current price
            try:
                q = self.kite.quote([f"NSE:{stock.symbol}"])
                quote_data = q.get(f"NSE:{stock.symbol}", {})
                current_price = quote_data.get('last_price', 0)
                if current_price <= 0:
                    continue
            except Exception as e:
                logger.debug(f"PH5A Sniper quote error for {stock.symbol}: {e}")
                continue

            # Update distance
            if stock.tracked_level_price > 0:
                stock.distance_pct = abs(current_price - stock.tracked_level_price) / stock.tracked_level_price * 100
            stock.last_price = current_price

            # CHECK TRIGGER: Has price crossed the level?
            triggered = False
            if stock.direction == 'SELL':  # SHORT: Price drops BELOW level
                if current_price <= stock.tracked_level_price:
                    triggered = True
            elif stock.direction == 'BUY':  # LONG: Price rises ABOVE level
                if current_price >= stock.tracked_level_price:
                    triggered = True

            if triggered:
                self._trigger_sniper_entry(stock, current_price)
            else:
                logger.info(f"  {stock.symbol} {stock.tracked_level_type} "
                           f"{stock.tracked_level_price:.2f} -> "
                           f"{stock.distance_pct:.2f}% away | LTP {current_price:.2f}")

    def calculate_level_stop(self, stock) -> float:
        """
        FIX 5: Level-based stop = other side of level + ATR x 0.3 buffer.
        Replaces flat 1.95 stop.
        """
        atr = self._key_levels.get(stock.symbol, {}).get('atr_15m', 0)
        atr_mult = getattr(self.config, 'PH5A_ATR_STOP_MULTIPLIER', 0.3)

        if atr > 0:
            buffer = atr * atr_mult
        else:
            # Fallback: use min stop percentage
            buffer = stock.tracked_level_price * getattr(self.config, 'PH5A_MIN_STOP_PCT', 0.3) / 100

        if stock.direction == 'SELL':
            # Short entry at level: stop ABOVE level
            stop = stock.tracked_level_price + buffer
        else:  # BUY
            # Long entry at level: stop BELOW level
            stop = stock.tracked_level_price - buffer

        # SANITY CHECK: Minimum stop distance
        min_stop_abs = stock.tracked_level_price * getattr(self.config, 'PH5A_MIN_STOP_PCT', 0.3) / 100
        actual_distance = abs(stop - stock.tracked_level_price)
        if actual_distance < min_stop_abs:
            if stock.direction == 'SELL':
                stop = stock.tracked_level_price + min_stop_abs
            else:
                stop = stock.tracked_level_price - min_stop_abs
            logger.warning(f"{stock.symbol}: ATR stop too tight ({actual_distance:.2f}), "
                         f"expanded to min {min_stop_abs:.2f}")

        # SANITY CHECK: Maximum stop distance
        max_stop_abs = stock.tracked_level_price * getattr(self.config, 'PH5A_MAX_STOP_PCT', 1.5) / 100
        actual_distance = abs(stop - stock.tracked_level_price)
        if actual_distance > max_stop_abs:
            if stock.direction == 'SELL':
                stop = stock.tracked_level_price + max_stop_abs
            else:
                stop = stock.tracked_level_price - max_stop_abs
            logger.warning(f"{stock.symbol}: ATR stop too wide ({actual_distance:.2f}), "
                         f"clamped to max {max_stop_abs:.2f}")

        # Round to tick size (0.10 covers all NSE instruments; 0.05-tick stocks are also 0.10-valid)
        stop = round(stop / 0.10) * 0.10
        return stop

    def calculate_sniper_target(self, stock, stop_price: float) -> float:
        """
        FIX 5: Target based on R:R ratio from level-based stop.
        """
        rr_ratio = getattr(self.config, 'PH5A_MIN_RR_RATIO', 2.0)
        risk = abs(stock.tracked_level_price - stop_price)
        reward = risk * rr_ratio

        if stock.direction == 'SELL':
            target = stock.tracked_level_price - reward
        else:  # BUY
            target = stock.tracked_level_price + reward

        # Round to tick size (0.10 covers all NSE instruments)
        target = round(target / 0.10) * 0.10
        return target

    def _trigger_sniper_entry(self, stock, trigger_price: float):
        """
        FIX 4: Immediate entry when price crosses level.
        Places limit order at level price + SL-M stop + limit target.
        """
        logger.info("")
        logger.info("=" * 60)
        logger.info(f"  PH5A SNIPER TRIGGER: {stock.symbol}")
        logger.info("=" * 60)

        # 1. CALCULATE STOP
        stop_price = self.calculate_level_stop(stock)

        # 2. CALCULATE TARGET
        target_price = self.calculate_sniper_target(stock, stop_price)

        # 3. POSITION SIZING — dynamic: Claude controls final size via size_adjustment
        if not self.capital_manager:
            logger.error(f"PH5A Sniper {stock.symbol}: No capital manager")
            return

        # Derive max_value from live capital so position size auto-scales with account
        _config_max = getattr(self.config, 'PVAT_MAX_POSITION_VALUE', 10000)
        _available  = self.capital_manager.get_available()
        _max_conc   = getattr(self.capital_manager, 'max_concentration_pct', 0.70)
        _total      = getattr(self.capital_manager, 'total_capital', _available)
        _conc_limit = _total * _max_conc
        max_value   = min(_config_max, _conc_limit, _available)
        max_value   = max(max_value, 0)

        if max_value <= 0 or (stock.tracked_level_price and max_value < stock.tracked_level_price):
            logger.info(f"PH5A Sniper {stock.symbol}: Insufficient capital (available ₹{_available:,.0f})")
            return

        can_enter = self.capital_manager.can_enter(stock.symbol, max_value)
        if not can_enter.get('can_enter', False):
            logger.info(f"PH5A Sniper {stock.symbol}: Capital check failed — {can_enter.get('reason', '?')}")
            return

        risk_per_share = abs(stock.tracked_level_price - stop_price)
        if risk_per_share <= 0:
            logger.warning(f"PH5A Sniper {stock.symbol}: Zero risk per share")
            return
        quantity = int(max_value / stock.tracked_level_price)
        quantity = max(1, quantity)
        logger.info(f"   💰 PH5A dynamic sizing: ₹{max_value:,.0f} of ₹{_available:,.0f} available → {quantity} qty")

        transaction_type = 'SELL' if stock.direction == 'SELL' else 'BUY'
        product = 'MIS'

        # 4. Send manual trade card BEFORE order — user can act manually if VPN fails
        self._send_manual_mis_card(stock, quantity, stop_price, target_price)

        # 4b. Fund Manager entry gate (Phase 9) — approve/reject/resize before placing
        if (hasattr(self, 'fund_manager') and self.fund_manager
                and getattr(self.config, 'PH9_ENTRY_GATE_ENABLED', False)):
            try:
                _regime = getattr(self.fund_manager, 'todays_regime', 'NORMAL')
                if _regime == 'HALT':
                    logger.warning(f"⛔ PH5A Sniper {stock.symbol}: BLOCKED — PH9 HALT mode")
                    return

                _sniper_signal = {
                    'symbol':          stock.symbol,
                    'direction':       transaction_type,
                    'source':          'PH5A',
                    'composite_score': getattr(stock, '_elite_score', 50),
                    'stop_price':      stop_price,
                    'target_price':    target_price,
                    'sector':          getattr(stock, 'sector', ''),
                    # Trend alignment data — required for Claude's Criterion 6 check
                    'trend_aligned':   getattr(stock, '_trend_aligned', None),
                    'price_vs_ma20':   getattr(stock, '_price_vs_ma20', 'N/A'),
                    'trend_label':     getattr(stock, '_trend_note', 'N/A'),
                    # ATR metadata so Claude can spot wrong-timeframe ATR
                    'atr':             self._key_levels.get(stock.symbol, {}).get('atr_15m', 0),
                    'atr_source':      'daily',   # _handoff_to_phase4 replaces with daily ATR
                    # Level context
                    'level_type':      getattr(stock, 'tracked_level_type', 'N/A'),
                    'level_price':     getattr(stock, 'tracked_level_price', 0),
                    'rejections':      getattr(stock, 'tracked_level_rejections', 0),
                    'confluence_days': getattr(stock, 'tracked_level_confluence_days', 0),
                }
                # Real portfolio state — not empty dict.
                # Claude must see actual open positions to assess concentration risk.
                _portfolio_state = {'positions': {}}
                if hasattr(self, 'phase4') and self.phase4:
                    try:
                        _open = getattr(self.phase4, 'positions', {}) or {}
                        _portfolio_state = {'positions': {
                            sym: {
                                'entry_price': p.get('entry_price', 0),
                                'direction': p.get('direction', 'LONG'),
                                'product': p.get('product', 'MIS'),
                            }
                            for sym, p in _open.items()
                        }}
                    except Exception:
                        pass
                elif hasattr(self, 'orchestrator') and self.orchestrator:
                    try:
                        _open = getattr(self.orchestrator, '_positions', {}) or {}
                        _portfolio_state = {'positions': {
                            sym: {
                                'entry_price': p.get('entry_price', 0),
                                'direction': p.get('direction', 'LONG'),
                                'product': p.get('product', 'MIS'),
                            }
                            for sym, p in _open.items()
                        }}
                    except Exception:
                        pass

                _fm = self.fund_manager.approve_entry(
                    signal=_sniper_signal,
                    current_price=trigger_price,
                    quantity=quantity,
                    portfolio_state=_portfolio_state
                )
                # v1.5.0: Queue mode — signal deferred to heartbeat, skip immediate execution
                if _fm.get('queued'):
                    logger.info(f"🧠 PH5A Sniper {stock.symbol}: queued for heartbeat batch evaluation")
                    return
                if not _fm.get('approved', True):
                    logger.warning(f"⛔ PH5A Sniper {stock.symbol}: BLOCKED by Fund Manager — "
                                   f"{_fm.get('reasoning', '')[:150]}")
                    return
                # Apply size adjustment
                _size_adj = float(_fm.get('size_adjustment', 1.0) or 1.0)
                if _regime == 'CAUTIOUS':
                    _size_adj = min(_size_adj, 0.7)
                if _size_adj != 1.0:
                    _old_qty = quantity
                    quantity = max(1, int(quantity * _size_adj))
                    logger.info(f"   📐 PH5A Fund Manager size: {_old_qty} → {quantity} ({_size_adj:.1f}x)")
                # Apply stop_adjustment — Claude may want a tighter or wider stop
                _stop_adj = _fm.get('stop_adjustment', None)
                if _stop_adj and isinstance(_stop_adj, (int, float)) and _stop_adj > 0:
                    _old_stop = stop_price
                    stop_price = float(_stop_adj)
                    logger.info(f"   📐 PH5A Fund Manager stop: ₹{_old_stop:.2f} → ₹{stop_price:.2f} (Claude adjusted)")
            except Exception as _fm_e:
                logger.error(f"PH5A Fund Manager gate error: {_fm_e} — blocking entry (fail-closed)")
                return  # Fail-closed: gate error = do not trade

        # 5. PLACE ENTRY ORDER (LIMIT at level price)
        try:
            entry_order_id = self._place_order(
                variety=self.kite.VARIETY_REGULAR,
                exchange=self.kite.EXCHANGE_NSE,
                tradingsymbol=stock.symbol,
                transaction_type=transaction_type,
                quantity=quantity,
                product=self.kite.PRODUCT_MIS,
                order_type=self.kite.ORDER_TYPE_LIMIT,
                price=round(stock.tracked_level_price / 0.10) * 0.10,
            )
            logger.info(f"  Entry order placed: {stock.symbol} {transaction_type} "
                       f"qty={quantity} @ {stock.tracked_level_price:.2f} "
                       f"order_id={entry_order_id}")
        except Exception as e:
            logger.error(f"  PH5A Sniper entry order failed: {e}")
            return

        # 6. VERIFY FILL (wait up to 10 seconds)
        fill_result = self._verify_pvat_order_fill(entry_order_id)
        if not fill_result.get('filled', False):
            logger.warning(f"  PH5A Sniper {stock.symbol}: Entry not filled — {fill_result.get('status', '?')}")
            # Cancel unfilled order
            try:
                self.kite.cancel_order(variety=self.kite.VARIETY_REGULAR, order_id=entry_order_id)
            except Exception:
                pass
            return

        actual_price = fill_result.get('average_price', stock.tracked_level_price)
        filled_qty = fill_result.get('filled_qty', quantity)

        logger.info(f"  FILL CONFIRMED: {stock.symbol} @ {actual_price:.2f} x {filled_qty}")

        # 7. PLACE STOP-LOSS ORDER (SL-M)
        stop_order_id = None
        opposite_type = 'BUY' if transaction_type == 'SELL' else 'SELL'
        try:
            stop_order_id = self._place_order(
                variety=self.kite.VARIETY_REGULAR,
                exchange=self.kite.EXCHANGE_NSE,
                tradingsymbol=stock.symbol,
                transaction_type=opposite_type,
                quantity=filled_qty,
                product=self.kite.PRODUCT_MIS,
                order_type=self.kite.ORDER_TYPE_SLM,
                trigger_price=round(stop_price / 0.10) * 0.10,
            )
            logger.info(f"  SL-M stop placed: {stock.symbol} trigger={stop_price:.2f} "
                       f"order_id={stop_order_id}")
        except Exception as e:
            logger.error(f"  PH5A Sniper SL-M order failed: {e}")

        # 8. PLACE TARGET ORDER (LIMIT)
        target_order_id = None
        try:
            target_order_id = self._place_order(
                variety=self.kite.VARIETY_REGULAR,
                exchange=self.kite.EXCHANGE_NSE,
                tradingsymbol=stock.symbol,
                transaction_type=opposite_type,
                quantity=filled_qty,
                product=self.kite.PRODUCT_MIS,
                order_type=self.kite.ORDER_TYPE_LIMIT,
                price=round(target_price / 0.10) * 0.10,
            )
            logger.info(f"  Target placed: {stock.symbol} @ {target_price:.2f} "
                       f"order_id={target_order_id}")
        except Exception as e:
            logger.error(f"  PH5A Sniper target order failed: {e}")

        # 9. DEPLOY CAPITAL
        if self.capital_manager:
            try:
                margin_used = actual_price * filled_qty
                self.capital_manager.deploy(
                    symbol=stock.symbol,
                    amount=margin_used,
                    quantity=filled_qty,
                    avg_price=actual_price,
                    source='PHASE5A_PVAT',
                    product='MIS'
                )
            except Exception as e:
                logger.error(f"  Capital deploy error: {e}")

        # 9. MARK TRIGGERED
        stock.triggered = True
        stock.entry_price = actual_price
        stock.filled_qty = filled_qty     # Store actual filled qty (Flaw 3 fix)
        stock.entry_time = datetime.now()
        stock.stop_price = stop_price
        stock.target_price = target_price
        stock.stop_order_id = stop_order_id
        stock.target_order_id = target_order_id
        stock.stall_start = None
        stock.stall_price = 0.0
        stock.paper_logger_id = ""        # PAPER MODE: set below if paper trade

        risk = abs(actual_price - stop_price)
        reward = abs(target_price - actual_price)
        rr = reward / risk if risk > 0 else 0

        logger.info(f"  SNIPER ENTRY COMPLETE: {stock.symbol}")
        logger.info(f"  Entry: {actual_price:.2f} | Stop: {stop_price:.2f} | Target: {target_price:.2f}")
        logger.info(f"  Risk: {risk:.2f} | Reward: {reward:.2f} | R:R = 1:{rr:.1f}")
        logger.info("=" * 60)

        # PAPER MODE: log entry to paper_trade_logger → Excel
        # Dual-check: _place_order syncs self._paper_mode but runs AFTER this block
        if self._paper_mode or getattr(self.config, 'PH5A_PAPER_MODE', False):
            try:
                from paper_trade_logger import log_paper_entry
                _logger_id = log_paper_entry(
                    phase="PH5A_PVAT",
                    symbol=stock.symbol,
                    direction=transaction_type,
                    entry_price=actual_price,
                    quantity=filled_qty,
                    stop_loss=stop_price,
                    target=target_price,
                    strategy="PVAT Sniper",
                    score=getattr(stock, '_elite_score', 0),
                    notes=f"Level: {getattr(stock, 'tracked_level_type', '')} @ {getattr(stock, 'tracked_level_price', 0):.2f}  R:R=1:{rr:.1f}"
                )
                stock.paper_logger_id = _logger_id
                logger.info(f"   📊 PAPER LOG: entry recorded → {_logger_id}")
            except Exception as _le:
                logger.warning(f"   ⚠️ paper_trade_logger entry failed: {_le}")

        # 10. HANDOFF TO PHASE 4
        if self.phase4:
            position_data = {
                'symbol': stock.symbol,
                'direction': 'LONG' if stock.direction == 'BUY' else 'SHORT',
                'entry_price': actual_price,
                'entry_time': datetime.now().isoformat(),
                'quantity': filled_qty,
                'product': 'MIS',
                'source': 'PHASE5A_PVAT',
                'monitoring_tier': 'TIER_1',
                'stop_price': stop_price,
                'target_price': target_price,
                'atr': self._key_levels.get(stock.symbol, {}).get('atr_15m', 0),
                'pvat_score': getattr(stock, '_elite_score', 0),
                'mandatory_exit_time': dt_time(12, 30),
                'is_paper_trade': self._paper_mode,
                'paper_logger_id': getattr(stock, 'paper_logger_id', ''),
            }
            try:
                self.phase4.add_phase5_position(position_data)
                logger.info(f"  Phase 4 handoff OK: {stock.symbol} TIER_1")
            except Exception as e:
                logger.error(f"  Phase 4 handoff failed: {e}")

        # 11. TELEGRAM
        if self.telegram:
            try:
                self.telegram.send_message(
                    f"PH5A SNIPER ENTRY\n\n"
                    f"Stock: {stock.symbol}\n"
                    f"Direction: {stock.direction}\n"
                    f"Level: {stock.tracked_level_type} @ {stock.tracked_level_price:.2f}\n"
                    f"Entry: {actual_price:.2f} | Qty: {filled_qty}\n"
                    f"Stop: {stop_price:.2f} | Target: {target_price:.2f}\n"
                    f"R:R = 1:{rr:.1f}"
                )
            except Exception:
                pass

    def manage_sniper_exits(self):
        """
        FIX 6: Priority-based exit management for sniper positions.
        Called every ~30 seconds while PH5A positions are open.
        """
        if not self.sniper_pipeline:
            return

        for stock in self.sniper_pipeline:
            if not stock.triggered:
                continue
            if stock.exited:
                continue

            now = datetime.now()

            # Get current price
            try:
                q = self.kite.quote([f"NSE:{stock.symbol}"])
                current_price = q.get(f"NSE:{stock.symbol}", {}).get('last_price', 0)
            except Exception:
                continue

            # PRIORITY 1: Stop hit (SL-M order filled)
            if stock.stop_order_id:
                try:
                    history = self.kite.order_history(stock.stop_order_id)
                    if history:
                        last = history[-1]
                        if last.get('status') == 'COMPLETE':
                            # Cancel target order (OCO)
                            if stock.target_order_id:
                                try:
                                    self.kite.cancel_order(
                                        variety=self.kite.VARIETY_REGULAR,
                                        order_id=stock.target_order_id
                                    )
                                except Exception:
                                    pass
                            stock.exited = True
                            stock.exit_reason = 'STOP_HIT'
                            stock.exit_price = last.get('average_price', stock.stop_price)
                            self._log_sniper_exit(stock)
                            self._release_sniper_capital(stock)
                            continue
                except Exception:
                    pass

            # PRIORITY 2: Target hit (limit order filled)
            if stock.target_order_id:
                try:
                    history = self.kite.order_history(stock.target_order_id)
                    if history:
                        last = history[-1]
                        if last.get('status') == 'COMPLETE':
                            # Cancel stop order (OCO)
                            if stock.stop_order_id:
                                try:
                                    self.kite.cancel_order(
                                        variety=self.kite.VARIETY_REGULAR,
                                        order_id=stock.stop_order_id
                                    )
                                except Exception:
                                    pass
                            stock.exited = True
                            stock.exit_reason = 'TARGET_HIT'
                            stock.exit_price = last.get('average_price', stock.target_price)
                            self._log_sniper_exit(stock)
                            self._release_sniper_capital(stock)
                            continue
                except Exception:
                    pass

            # PRIORITY 3: 12:30 PM timeout
            timeout_str = getattr(self.config, 'PH5A_POSITION_TIMEOUT', '12:30')
            if isinstance(timeout_str, str):
                th, tm = map(int, timeout_str.split(':'))
                timeout_time = dt_time(th, tm)
            else:
                timeout_time = timeout_str
            if now.time() >= timeout_time:
                self._exit_sniper_at_market(stock, 'TIMEOUT_1230', current_price)
                continue

            # PRIORITY 4: Price stalls 30 min at level
            # v5.8.0: Skip STALL_TIMEOUT if price is within 15% of total target distance.
            # Rationale: SRF exited ₹0.20 from target (₹2495.70 vs ₹2495.90) because the
            # stall timer fired while price was essentially at target. If we're in the last
            # 15% of the journey, the target order will fill shortly — don't abandon it.
            stall_timeout = getattr(self.config, 'PH5A_STALL_TIMEOUT_MINUTES', 30) * 60
            near_target = False
            if stock.entry_price > 0 and stock.target_price > 0:
                total_target_dist = abs(stock.target_price - stock.entry_price)
                if total_target_dist > 0:
                    if stock.direction == 'BUY':
                        dist_to_target = stock.target_price - current_price
                    else:  # SELL / SHORT
                        dist_to_target = current_price - stock.target_price
                    # Within last 15% of target distance → suppress stall exit
                    near_target = 0 <= dist_to_target <= total_target_dist * 0.15

            if stock.stall_start is None:
                stock.stall_start = now
                stock.stall_price = current_price
            else:
                price_moved = abs(current_price - stock.stall_price) / stock.stall_price * 100 if stock.stall_price > 0 else 0
                if price_moved > 0.1:
                    # Price moved, reset stall timer
                    stock.stall_start = now
                    stock.stall_price = current_price
                elif (now - stock.stall_start).total_seconds() >= stall_timeout:
                    if near_target:
                        # Within 15% of target — hold, reset timer, let target order fill
                        logger.info(
                            f"PH5A {stock.symbol}: STALL_TIMEOUT suppressed — "
                            f"near target (dist={dist_to_target:.2f} ≤ 15% of {total_target_dist:.2f}). "
                            f"Holding for target hit."
                        )
                        stock.stall_start = now   # reset so we don't spam this log
                    else:
                        self._exit_sniper_at_market(stock, 'STALL_TIMEOUT', current_price)
                        continue

        # CHECK: All positions exited?
        triggered_stocks = [s for s in self.sniper_pipeline if s.triggered]
        if triggered_stocks and all(s.exited for s in triggered_stocks):
            self.ph5a_done = True
            logger.info("PH5A Sniper: All positions closed. Done for today.")

    # ==================================================================
    #  v5.6.1: PAPER TRADING MODE
    # ==================================================================

    def _place_order(self, **order_params) -> str:
        """Wrapper: routes to paper or live order placement.
        Re-reads config each call so GUI toggles take effect immediately.
        v5.7.0: Hard guard — if config says PAPER, NEVER reach kite.place_order."""
        # Re-read every call so a GUI toggle takes effect without restart
        _cfg_paper = bool(getattr(self.config, 'PH5A_PAPER_MODE', False) or getattr(self.config, 'MASTER_PAPER_MODE', False))
        if _cfg_paper:
            self._paper_mode = True          # lock instance flag in sync with config
        if self._paper_mode or _cfg_paper:   # either source is enough
            return self._place_paper_order(order_params)
        order_type = str(order_params.get('order_type', '')).upper()
        if order_type in ('MARKET', 'SL-M'):
            order_params['market_protection'] = -1
        return self.kite.place_order(**order_params)

    def _place_paper_order(self, params: dict) -> str:
        """Simulate order placement — returns paper order ID, logs to JSON."""
        self._paper_counter += 1
        paper_id = f"PH5A_PAPER_{datetime.now().strftime('%Y%m%d')}_{self._paper_counter:04d}"

        record = {
            'order_id': paper_id,
            'timestamp': datetime.now().isoformat(),
            'symbol': params.get('tradingsymbol', ''),
            'transaction_type': params.get('transaction_type', ''),
            'quantity': params.get('quantity', 0),
            'order_type': str(params.get('order_type', '')),
            'price': params.get('price', 0),
            'trigger_price': params.get('trigger_price', 0),
            'product': str(params.get('product', 'MIS')),
            'mode': 'PAPER',
        }

        logger.info(f"  📝 PAPER ORDER: {record['symbol']} {record['transaction_type']} "
                     f"qty={record['quantity']} @ {record.get('price', 'MKT')} "
                     f"id={paper_id}")

        self._save_paper_log(record)
        return paper_id

    def _save_paper_log(self, record: dict):
        """Append paper trade record to JSON log file."""
        try:
            os.makedirs(os.path.dirname(self._paper_log_path), exist_ok=True)
            trades = []
            if os.path.isfile(self._paper_log_path):
                with open(self._paper_log_path, 'r') as f:
                    trades = json.load(f)
            trades.append(record)
            with open(self._paper_log_path, 'w') as f:
                json.dump(trades, f, indent=2, default=str)
        except Exception as e:
            logger.warning(f"Paper trade log write failed: {e}")

    def _exit_sniper_at_market(self, stock, reason: str, current_price: float):
        """Exit a sniper position at market price."""
        # Cancel existing stop and target orders
        for order_id in [stock.stop_order_id, stock.target_order_id]:
            if order_id:
                try:
                    self.kite.cancel_order(variety=self.kite.VARIETY_REGULAR, order_id=order_id)
                except Exception:
                    pass

        # Place market exit — use actual filled qty (Flaw 3 fix)
        opposite_type = 'BUY' if stock.direction == 'SELL' else 'SELL'
        qty = getattr(stock, 'filled_qty', 0)
        if qty <= 0:
            # Fallback only if filled_qty was never stored
            qty = max(1, int(getattr(self.config, 'PVAT_MAX_POSITION_VALUE', 10000) / stock.entry_price)) if stock.entry_price > 0 else 1

        try:
            self._place_order(
                variety=self.kite.VARIETY_REGULAR,
                exchange=self.kite.EXCHANGE_NSE,
                tradingsymbol=stock.symbol,
                transaction_type=opposite_type,
                quantity=qty,
                product=self.kite.PRODUCT_MIS,
                order_type=self.kite.ORDER_TYPE_MARKET,
            )
        except Exception as e:
            logger.error(f"PH5A Sniper market exit failed for {stock.symbol}: {e}")

        stock.exited = True
        stock.exit_reason = reason
        stock.exit_price = current_price
        self._log_sniper_exit(stock)
        self._release_sniper_capital(stock)

    def _release_sniper_capital(self, stock):
        """Release capital for a closed sniper position."""
        if self.capital_manager and stock.entry_price > 0:
            try:
                qty = getattr(stock, 'filled_qty', 0) or max(1, int(
                    getattr(self.config, 'PVAT_MAX_POSITION_VALUE', 10000) / stock.entry_price))
                if stock.direction == 'SELL':
                    pnl = (stock.entry_price - stock.exit_price) * qty
                else:
                    pnl = (stock.exit_price - stock.entry_price) * qty
                self.capital_manager.release(stock.symbol, pnl)
            except Exception as e:
                logger.error(f"PH5A capital release error for {stock.symbol}: {e}")

    def _send_manual_mis_card(self, stock, quantity: int, stop_price: float, target_price: float):
        """
        Send a Telegram card with manual MIS trade instructions.
        Called in _trigger_sniper_entry() BEFORE placing any orders.
        MIS product — uses SL-M for stop, LIMIT for target (not GTT).
        """
        if not self.telegram:
            return
        try:
            symbol     = stock.symbol
            entry      = stock.tracked_level_price
            direction  = stock.direction          # 'BUY' or 'SELL'
            level_type = stock.tracked_level_type
            score      = getattr(stock, '_elite_score', 0)
            now_str    = datetime.now().strftime('%H:%M:%S')

            exit_action = 'SELL' if direction == 'BUY' else 'BUY'

            stop_pct  = ((stop_price  - entry) / entry * 100) if entry > 0 else 0
            tgt_pct   = ((target_price - entry) / entry * 100) if entry > 0 else 0
            risk_amt  = abs(entry - stop_price)  * quantity
            reward_amt = abs(target_price - entry) * quantity
            rr        = (reward_amt / risk_amt) if risk_amt > 0 else 0

            stop_trigger  = round(stop_price  / 0.10) * 0.10
            target_limit  = round(target_price / 0.10) * 0.10

            msg = (
                f"📋 PH5A SIGNAL — {symbol}\n"
                f"{'━'*32}\n"
                f"Action  : {direction} (MIS INTRADAY)\n"
                f"Level   : {level_type} @ ₹{entry:,.2f}\n"
                f"Qty     : {quantity}  |  Score: {score:.0f}\n"
                f"Capital : ₹{entry*quantity:,.0f}\n"
                f"\n"
                f"Stop    : ₹{stop_price:,.2f}  ({stop_pct:+.2f}%)\n"
                f"Target  : ₹{target_price:,.2f}  ({tgt_pct:+.2f}%)\n"
                f"Risk    : ₹{risk_amt:,.0f}  |  R:R 1:{rr:.1f}\n"
                f"Time    : {now_str}\n"
                f"\n"
                f"{'━'*32}\n"
                f"📌 IF AUTO FAILS — MANUAL STEPS:\n"
                f"1. {direction} {symbol} NSE MIS\n"
                f"   LIMIT @ ₹{entry:,.2f}  x{quantity}\n"
                f"\n"
                f"2. After fill — place SL-M order:\n"
                f"   {exit_action} {symbol} MIS SL-M\n"
                f"   Trigger : ₹{stop_trigger:,.2f}  x{quantity}\n"
                f"\n"
                f"3. Place target LIMIT order:\n"
                f"   {exit_action} {symbol} MIS LIMIT\n"
                f"   Price   : ₹{target_limit:,.2f}  x{quantity}\n"
                f"\n"
                f"⚠️ MIS — must exit before 3:20 PM"
            )
            self.telegram.send_message(msg)
        except Exception as e:
            logger.debug(f"PH5A manual MIS card send failed: {e}")

    def _log_sniper_exit(self, stock):
        """Log and notify sniper exit."""
        pnl = 0
        if stock.entry_price > 0 and stock.exit_price > 0:
            if stock.direction == 'SELL':
                pnl_per_share = stock.entry_price - stock.exit_price
            else:
                pnl_per_share = stock.exit_price - stock.entry_price
            qty = getattr(stock, 'filled_qty', 0) or max(1, int(
                getattr(self.config, 'PVAT_MAX_POSITION_VALUE', 10000) / stock.entry_price))
            pnl = pnl_per_share * qty

        logger.info(f"PH5A Sniper EXIT: {stock.symbol} | Reason: {stock.exit_reason} | "
                   f"Entry: {stock.entry_price:.2f} | Exit: {stock.exit_price:.2f} | "
                   f"P&L: {pnl:+.2f}")

        # PAPER MODE: log exit to paper_trade_logger → Excel
        # Dual-check: same pattern as entry — config is authoritative
        if self._paper_mode or getattr(self.config, 'PH5A_PAPER_MODE', False):
            try:
                from paper_trade_logger import log_paper_exit
                _logger_id = getattr(stock, 'paper_logger_id', '')
                if _logger_id:
                    log_paper_exit(
                        trade_id=_logger_id,
                        exit_price=stock.exit_price,
                        exit_reason=getattr(stock, 'exit_reason', 'UNKNOWN')
                    )
                    logger.info(f"   📊 PAPER LOG: exit recorded → {_logger_id}  P&L=₹{pnl:+.2f}")
                else:
                    logger.warning(f"   ⚠️ PAPER LOG: no paper_logger_id on stock — exit not logged to Excel")
            except Exception as _le:
                logger.warning(f"   ⚠️ paper_trade_logger exit failed: {_le}")

        if self.telegram:
            try:
                self.telegram.send_message(
                    f"PH5A Sniper EXIT\n\n"
                    f"Stock: {stock.symbol}\n"
                    f"Reason: {stock.exit_reason}\n"
                    f"Entry: {stock.entry_price:.2f}\n"
                    f"Exit: {stock.exit_price:.2f}\n"
                    f"P&L: {pnl:+.2f}"
                )
            except Exception:
                pass

    def close_watch_window(self):
        """
        FIX 3: Called by orchestrator at 10:30 if watch window expires.
        No more entries allowed.
        """
        for stock in self.sniper_pipeline:
            if not stock.triggered:
                logger.info(f"PH5A: {stock.symbol} --- watch expired, never triggered. Removing.")

        self.ph5a_watch_closed = True

        # If no positions were triggered at all
        if not any(s.triggered for s in self.sniper_pipeline):
            self.ph5a_done = True
            logger.info("PH5A Sniper: Watch window closed. 0 triggers. Done.")
            if self.telegram:
                try:
                    self.telegram.send_message(
                        "PH5A Sniper: Watch window expired. No triggers. Capital preserved"
                    )
                except Exception:
                    pass

    # ─────────────────────────────────────────────────────────────────
    # LEVEL DETECTION
    # ─────────────────────────────────────────────────────────────────

    def _fetch_historical_and_compute_levels(self):
        """Fetch 5-day 15-min candles and compute key levels for all stocks."""
        logger.info("")
        logger.info("=" * 70)
        logger.info("PHASE 5A: COMPUTING KEY LEVELS FOR PVAT SCANNER")
        logger.info("=" * 70)

        # Use Phase 5's stock universe
        if self.phase5 and hasattr(self.phase5, 'stock_universe'):
            symbols = self.phase5.stock_universe
        else:
            symbols = list(_MASTER_STOCK_LIST)

        if not symbols:
            logger.warning("PVAT: No stocks in universe — cannot compute levels")
            return

        today = date.today()
        from_date = today - timedelta(days=7)  # Extra buffer for weekends
        to_date = datetime.now()

        computed = 0
        near_levels = 0
        price_filtered = 0
        score_filtered = 0
        errors = 0

        # Price filter — reuse Phase 5 config (same tradeable universe)
        min_price = getattr(self.config, 'PH5_MIN_PRICE', 800)
        max_price = getattr(self.config, 'PH5_MAX_PRICE', 3000)
        min_level_score = getattr(self.config, 'PVAT_MIN_LEVEL_SCORE', 25)

        for symbol in symbols:
            try:
                # Get instrument token
                token = None
                if self.phase5 and hasattr(self.phase5, '_get_instrument_token'):
                    token = self.phase5._get_instrument_token(symbol)
                if not token:
                    continue

                # Fetch 15-min candles
                candles = self.kite.historical_data(
                    token, from_date, to_date, '15minute'
                )
                if not candles or len(candles) < 10:
                    continue

                # Compute levels
                levels = self._compute_key_levels(symbol, candles)
                if not levels:
                    continue

                self._key_levels[symbol] = levels
                self._candle_cache_15m[symbol] = candles

                # Check proximity — only actively track stocks near a level
                current_price = candles[-1].get('close', 0)
                if current_price <= 0:
                    continue

                # ── Price filter: skip stocks outside tradeable range ──
                if current_price < min_price or current_price > max_price:
                    price_filtered += 1
                    logger.debug(
                        f"  PVAT: {symbol} @ ₹{current_price:.0f} "
                        f"SKIPPED (outside ₹{min_price}-₹{max_price} range)"
                    )
                    continue

                nearest, nearest_dist = self._find_nearest_level(current_price, levels)
                if nearest_dist <= 2.0:  # Within 2% of any proven level
                    nearest_price = levels.get(nearest, 0)

                    # v5.4.3: Use pre-computed score from level_evidence
                    evidence = levels.get('level_evidence', {}).get(nearest, {})
                    if evidence:
                        level_score = evidence.get('score', 0)
                    else:
                        level_score = self._score_level(nearest_price, nearest, candles) if nearest_price > 0 else 0

                    self._stock_states[symbol] = PVATStockData(
                        symbol=symbol,
                        state=PVATState.IDLE,
                        last_price=current_price,
                    )
                    near_levels += 1

                    if level_score >= 30:
                        n_rej = len(evidence.get('rejections', [])) if evidence else 0
                        conf = evidence.get('confluence_days', 0) if evidence else 0
                        logger.debug(
                            f"  PVAT: {symbol} near {nearest} @ ₹{nearest_price:.0f} "
                            f"(dist={nearest_dist:.1f}%, score={level_score}, "
                            f"rejections={n_rej}, confluence={conf}d)"
                        )

                computed += 1
                time.sleep(0.05)  # Rate limit

            except Exception as e:
                errors += 1
                logger.debug(f"PVAT levels error for {symbol}: {e}")

        logger.info(
            f"PVAT: Computed levels for {computed} stocks, "
            f"{near_levels} near key levels, "
            f"{price_filtered} price-filtered (₹{min_price}-₹{max_price}), "
            f"{errors} errors"
        )

        # Telegram: Startup summary
        try:
            if self.telegram and near_levels > 0:
                # Collect stocks near levels for the message
                near_stocks = []
                for sym, data in sorted(self._stock_states.items()):
                    if data.tracked_level_price > 0:
                        near_stocks.append(f"  {sym} @ ₹{data.last_price:.0f}")
                near_list = '\n'.join(near_stocks[:10])  # Cap at 10
                extra = f"\n  ...+{near_levels - 10} more" if near_levels > 10 else ""
                self.telegram.send_message(
                    f"📡 <b>PVAT Scanner Started</b>\n\n"
                    f"Levels: {computed} stocks\n"
                    f"Near key levels: {near_levels}\n"
                    f"Price-filtered: {price_filtered}\n\n"
                    f"<b>Tracking:</b>\n{near_list}{extra}"
                )
        except Exception as e:
            logger.debug(f"PVAT startup Telegram error: {e}")

    def _compute_key_levels(self, symbol: str, candles: List[Dict]) -> Optional[Dict]:
        """
        From 5-day 15-min historical data, extract actionable S/R levels.
        """
        today = date.today()
        today_candles = []
        prev_day_candles = []
        older_candles = []
        prev_date = None

        # Separate candles by day
        for c in candles:
            c_date = c['date'].date() if hasattr(c['date'], 'date') else c['date']
            if isinstance(c_date, datetime):
                c_date = c_date.date()
            if c_date == today:
                today_candles.append(c)
            else:
                if prev_date is None or c_date > prev_date:
                    if prev_date is not None:
                        older_candles.extend(prev_day_candles)
                    prev_day_candles = [c]
                    prev_date = c_date
                elif c_date == prev_date:
                    prev_day_candles.append(c)
                else:
                    older_candles.append(c)

        if not prev_day_candles:
            return None

        # PDH / PDL / PDC
        pdh = max(c['high'] for c in prev_day_candles)
        pdl = min(c['low'] for c in prev_day_candles)
        pdc = prev_day_candles[-1]['close']

        # Multi-day high/low (exclude today)
        all_prior = prev_day_candles + older_candles
        multi_day_high = max(c['high'] for c in all_prior) if all_prior else pdh
        multi_day_low = min(c['low'] for c in all_prior) if all_prior else pdl

        # IB (Initial Balance) from today's first 4 candles (09:15-10:15)
        ib_high = 0
        ib_low = float('inf')
        if today_candles and len(today_candles) >= 4:
            ib_candles = today_candles[:4]
            ib_high = max(c['high'] for c in ib_candles)
            ib_low = min(c['low'] for c in ib_candles)
        elif today_candles:
            ib_high = max(c['high'] for c in today_candles)
            ib_low = min(c['low'] for c in today_candles)

        # POC (Point of Control) — price with highest volume
        poc = self._calculate_poc(all_prior)

        # Average volume and ATR
        volumes = [c['volume'] for c in candles if c['volume'] > 0]
        avg_volume_15m = float(np.mean(volumes)) if volumes else 0

        atr_15m = self._calculate_atr_15m(candles)

        # ── v5.4.3: Enhanced Level Discovery — rejection analysis ──
        ib_low_val = ib_low if ib_low != float('inf') else 0
        level_type_map = {
            'pdh': ('RESISTANCE', pdh),
            'pdl': ('SUPPORT', pdl),
            'multi_day_high': ('RESISTANCE', multi_day_high),
            'multi_day_low': ('SUPPORT', multi_day_low),
            'ib_high': ('RESISTANCE', ib_high),
            'ib_low': ('SUPPORT', ib_low_val),
            'poc': ('BOTH', poc),
        }

        candidate_levels = []
        for level_key, (side, price) in level_type_map.items():
            if price <= 0:
                continue
            rejections = self._analyze_rejections(price, side, candles, avg_volume_15m)
            confluence = self._compute_confluence(rejections)
            lv_score = self._score_level(price, level_key, candles, rejections, confluence)
            candidate_levels.append({
                'key': level_key,
                'price': price,
                'side': side,
                'rejections': rejections,
                'confluence_days': confluence,
                'score': lv_score,
                'merged_types': [level_key],
            })

        # Merge duplicate levels (PDH ≈ multi_day_high → single stronger level)
        merged = self._merge_duplicate_levels(candidate_levels)

        # Filter to top N proven levels (discard 0-rejection levels)
        max_levels = getattr(self.config, 'PVAT_MAX_PROVEN_LEVELS', 4)
        proven = self._filter_top_levels(merged, max_levels)

        # Return with all original keys preserved + new enhanced data
        return {
            'pdh': pdh,
            'pdl': pdl,
            'pdc': pdc,
            'multi_day_high': multi_day_high,
            'multi_day_low': multi_day_low,
            'ib_high': ib_high,
            'ib_low': ib_low_val,
            'poc': poc,
            'avg_volume_15m': avg_volume_15m,
            'atr_15m': atr_15m,
            # v5.4.3: Enhanced level data
            'proven_levels': proven,
            'level_evidence': {lv['key']: lv for lv in proven},
        }

    def _calculate_poc(self, candles: List[Dict]) -> float:
        """Point of Control — price level with highest cumulative volume."""
        if not candles:
            return 0
        price_volume = {}
        for c in candles:
            # Round to nearest 0.5 for bucketing
            typical = round((c['high'] + c['low'] + c['close']) / 3 * 2) / 2
            price_volume[typical] = price_volume.get(typical, 0) + c.get('volume', 0)
        if not price_volume:
            return 0
        return max(price_volume, key=price_volume.get)

    def _fetch_daily_atr(self, symbol: str, entry_price: float, period: int = 14) -> float:
        """
        Fetch ATR from daily candles for stop/risk sizing.

        15-min ATR is 10-15× smaller than daily ATR and dominated by intraday noise.
        Using it for stop placement produces stops that get hit on routine tick fluctuations.
        Daily ATR must be used for anything that scales with 'how much can this stock move'.
        """
        fallback = entry_price * 0.015  # 1.5% conservative fallback
        if not self.kite:
            return fallback
        try:
            token = None
            if self.phase5 and hasattr(self.phase5, '_get_instrument_token'):
                token = self.phase5._get_instrument_token(symbol)
            if not token:
                instruments = self.kite.instruments('NSE')
                for inst in instruments:
                    if inst['tradingsymbol'] == symbol:
                        token = inst['instrument_token']
                        break
            if not token:
                logger.warning(f"PVAT {symbol}: instrument token not found — daily ATR fallback ₹{fallback:.2f}")
                return fallback

            from_date = datetime.now() - timedelta(days=45)
            candles = self.kite.historical_data(token, from_date, datetime.now(), 'day')
            if not candles or len(candles) < period + 1:
                logger.warning(f"PVAT {symbol}: only {len(candles) if candles else 0} daily candles — ATR fallback ₹{fallback:.2f}")
                return fallback

            trs = []
            for i in range(1, len(candles)):
                h, l, pc = candles[i]['high'], candles[i]['low'], candles[i - 1]['close']
                trs.append(max(h - l, abs(h - pc), abs(l - pc)))

            atr = sum(trs[-period:]) / period
            atr_pct = (atr / entry_price) * 100
            if atr_pct < 0.5 or atr_pct > 8.0:
                logger.warning(f"PVAT {symbol}: daily ATR ₹{atr:.2f} ({atr_pct:.1f}%) outside sane range — clamping")
                atr = max(entry_price * 0.005, min(entry_price * 0.08, atr))

            logger.info(f"PVAT {symbol}: daily ATR = ₹{atr:.2f} ({atr_pct:.1f}% of ₹{entry_price:.2f})")
            return round(atr, 2)
        except Exception as e:
            logger.warning(f"PVAT {symbol}: daily ATR fetch failed ({e}) — fallback ₹{fallback:.2f}")
            return fallback

    def _calculate_atr_15m(self, candles: List[Dict], period: int = 14) -> float:
        """ATR on 15-min candles (used for level discovery only, NOT for stop sizing)."""
        if len(candles) < period + 1:
            return 0
        trs = []
        for i in range(1, len(candles)):
            h = candles[i]['high']
            l = candles[i]['low']
            pc = candles[i - 1]['close']
            tr = max(h - l, abs(h - pc), abs(l - pc))
            trs.append(tr)
        if len(trs) < period:
            return float(np.mean(trs)) if trs else 0
        # Wilder's smoothing
        atr = float(np.mean(trs[:period]))
        for tr in trs[period:]:
            atr = (atr * (period - 1) + tr) / period
        return atr

    def _calculate_vwap(self, candles: List[Dict]) -> float:
        """VWAP: sum(typical_price * volume) / sum(volume)."""
        cum_pv = 0
        cum_v = 0
        for c in candles:
            tp = (c['high'] + c['low'] + c['close']) / 3
            v = c.get('volume', 0)
            cum_pv += tp * v
            cum_v += v
        return cum_pv / cum_v if cum_v > 0 else 0

    # ─────────────────────────────────────────────────────────────────
    # ENHANCED LEVEL DISCOVERY v5.4.3 — Rejection Analysis
    # ─────────────────────────────────────────────────────────────────

    def _analyze_rejections(self, level_price: float, level_side: str,
                            candles: List[Dict], avg_volume: float) -> List[Dict]:
        """
        v5.4.3: Find confirmed rejections (touch + bounce + volume) at a level.

        A rejection requires ALL 3:
          1. Touch: wick within 0.3% of level price
          2. Bounce: close ≥ PVAT_REJECTION_MIN_BOUNCE_PCT away in rejection direction
          3. Volume: candle volume ≥ PVAT_REJECTION_MIN_VOL_RATIO × avg_volume

        Args:
            level_price: The price level to analyze
            level_side: 'RESISTANCE', 'SUPPORT', or 'BOTH' (for POC)
            candles: Historical 15-min candle data
            avg_volume: Average 15-min volume for volume ratio calculation

        Returns:
            List of confirmed rejection dicts with date, prices, bounce%, volume_ratio
        """
        rejections = []
        min_bounce = getattr(self.config, 'PVAT_REJECTION_MIN_BOUNCE_PCT', 0.3) / 100
        min_vol_ratio = getattr(self.config, 'PVAT_REJECTION_MIN_VOL_RATIO', 0.8)
        touch_zone = 0.003  # 0.3% proximity for touch detection

        for idx, c in enumerate(candles):
            c_date = c['date'].date() if hasattr(c['date'], 'date') else c['date']
            if isinstance(c_date, datetime):
                c_date = c_date.date()

            vol = c.get('volume', 0)
            vol_ratio = vol / avg_volume if avg_volume > 0 else 1.0

            # Volume gate — skip thin candles
            if vol_ratio < min_vol_ratio:
                continue

            touched = False
            bounce_pct = 0.0
            touch_price = 0.0

            # RESISTANCE: high wick touches level → close bounces below
            if level_side in ('RESISTANCE', 'BOTH'):
                if level_price > 0 and abs(c['high'] - level_price) / level_price < touch_zone:
                    bounce = (level_price - c['close']) / level_price
                    if bounce >= min_bounce:
                        touched = True
                        bounce_pct = bounce * 100
                        touch_price = c['high']

            # SUPPORT: low wick touches level → close bounces above
            if not touched and level_side in ('SUPPORT', 'BOTH'):
                if level_price > 0 and abs(c['low'] - level_price) / level_price < touch_zone:
                    bounce = (c['close'] - level_price) / level_price
                    if bounce >= min_bounce:
                        touched = True
                        bounce_pct = bounce * 100
                        touch_price = c['low']

            if touched:
                rejections.append({
                    'date': c_date,
                    'datetime': c['date'],
                    'touch_price': touch_price,
                    'close_price': c['close'],
                    'bounce_pct': bounce_pct,
                    'volume_ratio': vol_ratio,
                    'candle_index': idx,
                })

        return rejections

    def _compute_confluence(self, rejections: List[Dict]) -> int:
        """v5.4.3: Count distinct trading days with confirmed rejections."""
        if not rejections:
            return 0
        return len(set(r['date'] for r in rejections))

    def _merge_duplicate_levels(self, candidates: List[Dict]) -> List[Dict]:
        """
        v5.4.3: Merge levels within PVAT_CONFLUENCE_PROXIMITY_PCT of each other.

        When PDH ≈ multi_day_high (within 0.3%), they become a single stronger level
        with combined rejection evidence. The higher-priority type name is kept.
        """
        if not candidates:
            return []

        merge_pct = getattr(self.config, 'PVAT_CONFLUENCE_PROXIMITY_PCT', 0.3) / 100
        sorted_lvls = sorted(candidates, key=lambda x: x['price'])

        type_priority = {
            'pdh': 1, 'pdl': 1,
            'multi_day_high': 2, 'multi_day_low': 2,
            'ib_high': 3, 'ib_low': 3,
            'poc': 4,
        }

        merged = []
        current = sorted_lvls[0].copy()
        current['rejections'] = list(current.get('rejections', []))
        current['merged_types'] = list(current.get('merged_types', [current['key']]))

        for nxt in sorted_lvls[1:]:
            if current['price'] > 0 and \
               abs(nxt['price'] - current['price']) / current['price'] < merge_pct:
                # MERGE: combine rejection evidence (deduplicate by candle_index)
                seen_indices = {r['candle_index'] for r in current['rejections']}
                for r in nxt.get('rejections', []):
                    if r['candle_index'] not in seen_indices:
                        current['rejections'].append(r)
                        seen_indices.add(r['candle_index'])

                current['merged_types'].append(nxt['key'])

                # Keep higher-priority type name
                if type_priority.get(nxt['key'], 99) < type_priority.get(current['key'], 99):
                    current['key'] = nxt['key']

                # Recompute confluence with merged rejections
                current['confluence_days'] = self._compute_confluence(current['rejections'])

                logger.debug(
                    f"PVAT Level Merge: {current['merged_types']} → "
                    f"₹{current['price']:.2f} (combined {len(current['rejections'])} rejections)"
                )
            else:
                merged.append(current)
                current = nxt.copy()
                current['rejections'] = list(current.get('rejections', []))
                current['merged_types'] = list(current.get('merged_types', [current['key']]))

        merged.append(current)
        return merged

    def _filter_top_levels(self, candidates: List[Dict], max_levels: int) -> List[Dict]:
        """
        v5.4.3: Keep only top N levels by score. Discard levels with 0 rejections.

        IB levels with rejections get a floor score (since they lack multi-day data).
        Levels with 0 confirmed rejections are ALWAYS discarded (no market evidence).
        """
        ib_floor = getattr(self.config, 'PVAT_IB_LEVEL_SCORE_FLOOR', 25)

        # Apply IB floor: IB levels with >0 rejections get minimum score
        for lv in candidates:
            if lv['key'] in ('ib_high', 'ib_low') and len(lv.get('rejections', [])) > 0:
                lv['score'] = max(lv['score'], ib_floor)

        # Discard levels with 0 confirmed rejections — no market evidence
        proven = [lv for lv in candidates if len(lv.get('rejections', [])) > 0]

        # Sort by score descending, take top N
        proven.sort(key=lambda x: x['score'], reverse=True)

        if proven:
            logger.debug(
                f"PVAT Level Filter: {len(candidates)} candidates → "
                f"{len(proven)} proven → top {min(max_levels, len(proven))}"
            )

        return proven[:max_levels]

    # ─────────────────────────────────────────────────────────────────
    # NEAREST LEVEL FINDER
    # ─────────────────────────────────────────────────────────────────

    def _find_nearest_level(self, price: float, levels: Dict) -> Tuple[str, float]:
        """Find closest key level. v5.4.3: Prefers proven (rejection-verified) levels."""
        proven = levels.get('proven_levels', [])

        if proven:
            # Use filtered proven levels — only levels with confirmed rejections
            nearest_type = ""
            nearest_dist = float('inf')
            for lv in proven:
                if lv['price'] <= 0:
                    continue
                dist = abs(price - lv['price']) / lv['price'] * 100
                if dist < nearest_dist:
                    nearest_dist = dist
                    nearest_type = lv['key']
            return nearest_type, nearest_dist

        # Fallback: original 7-type iteration (backward compat)
        nearest_type = ""
        nearest_dist = float('inf')
        for level_type in ['pdh', 'pdl', 'multi_day_high', 'multi_day_low',
                           'ib_high', 'ib_low', 'poc']:
            lv = levels.get(level_type, 0)
            if lv <= 0:
                continue
            dist = abs(price - lv) / lv * 100
            if dist < nearest_dist:
                nearest_dist = dist
                nearest_type = level_type
        return nearest_type, nearest_dist

    def _get_level_side(self, level_type: str, price: float, level_price: float) -> str:
        """Determine if level acts as RESISTANCE or SUPPORT relative to price."""
        if level_type in ('pdh', 'multi_day_high', 'ib_high'):
            return 'RESISTANCE'
        elif level_type in ('pdl', 'multi_day_low', 'ib_low'):
            return 'SUPPORT'
        else:
            # POC — depends on price position
            return 'RESISTANCE' if price < level_price else 'SUPPORT'

    # ─────────────────────────────────────────────────────────────────
    # CANDLE UPDATES
    # ─────────────────────────────────────────────────────────────────

    def _update_current_candles(self):
        """Fetch latest quotes for tracked stocks (APPROACH/ACCEPTANCE/IDLE)."""
        tracked = [
            sym for sym, data in self._stock_states.items()
            if data.state in (PVATState.APPROACH, PVATState.ACCEPTANCE, PVATState.IDLE)
        ]
        if not tracked:
            return

        try:
            quote_symbols = [f"NSE:{s}" for s in tracked]
            quotes = self.kite.quote(quote_symbols)

            for sym in tracked:
                key = f"NSE:{sym}"
                if key in quotes:
                    q = quotes[key]
                    ltp = q.get('last_price', 0)
                    cum_vol = q.get('volume', 0)  # kite returns cumulative day volume
                    if ltp > 0 and sym in self._stock_states:
                        data = self._stock_states[sym]
                        data.last_price = ltp

                        # Compute per-candle volume delta from cumulative
                        if data.prev_cumulative_volume > 0:
                            data.candle_volume = max(0, cum_vol - data.prev_cumulative_volume)
                        else:
                            data.candle_volume = 0  # First scan — no delta yet
                        data.prev_cumulative_volume = cum_vol
                        data.last_volume = cum_vol  # Keep cumulative for other uses

            # Track candle boundaries for acceptance counting
            now = datetime.now()
            minute_slot = now.minute // 15 * 15
            candle_boundary = now.replace(
                minute=minute_slot, second=0, microsecond=0
            )
            if (self._last_candle_time is None or
                    candle_boundary > self._last_candle_time):
                self._last_candle_time = candle_boundary
                # New 15-min candle — increment acceptance AND approach counts
                for s, data in self._stock_states.items():
                    # v2.1: Track approach dwell time
                    if data.state == PVATState.APPROACH:
                        if (data.approach_candle_boundary is None or
                                candle_boundary > data.approach_candle_boundary):
                            data.approach_candle_count += 1
                            data.approach_candle_boundary = candle_boundary

                    if data.state == PVATState.ACCEPTANCE:
                        # Only count if this is a NEW boundary after acceptance started
                        if (data.acceptance_candle_boundary is None or
                                candle_boundary > data.acceptance_candle_boundary):
                            data.acceptance_candle_count += 1
                            data.acceptance_candle_boundary = candle_boundary

                        # Check volume decline using per-candle delta
                        if data.candle_volume > 0 and data.volume_at_acceptance_start <= 0:
                            data.volume_at_acceptance_start = data.candle_volume
                        elif (data.candle_volume > 0 and
                                data.volume_at_acceptance_start > 0 and
                                data.candle_volume < data.volume_at_acceptance_start * 0.8):
                            data.volume_declining = True

                        # Refresh 15-min candle cache for acceptance stocks
                        self._refresh_candle_cache(s)

                # LOG 2: Compact acceptance table (replaces per-stock verbose blocks)
                self._log_pvat_acceptance_table()

        except Exception as e:
            logger.debug(f"PVAT quote update error: {e}")

    def _refresh_candle_cache(self, symbol: str):
        """
        Refresh 15-min candle cache for a single stock.
        Called on candle boundaries for ACCEPTANCE stocks only.
        """
        try:
            token = None
            if self.phase5 and hasattr(self.phase5, '_get_instrument_token'):
                token = self.phase5._get_instrument_token(symbol)
            if not token:
                return

            today = date.today()
            from_date = today - timedelta(days=2)  # Just 2 days — enough for today + prev
            to_date = datetime.now()

            candles = self.kite.historical_data(
                token, from_date, to_date, '15minute'
            )
            if candles and len(candles) >= 2:
                self._candle_cache_15m[symbol] = candles
        except Exception as e:
            logger.debug(f"PVAT cache refresh error for {symbol}: {e}")

    # ─────────────────────────────────────────────────────────────────
    # PVAT STATE MACHINE
    # ─────────────────────────────────────────────────────────────────

    def _update_pvat_state(self, symbol: str) -> Optional[Dict]:
        """
        Core state machine logic for one stock.
        Returns signal dict if BREAKOUT_CONFIRMED, else None.

        v2.1 changes:
          - IDLE→APPROACH: uses config PVAT_APPROACH_PROXIMITY_PCT (was hardcoded 1.0%)
          - IDLE→APPROACH: level score gate (PVAT_MIN_LEVEL_SCORE)
          - APPROACH→ACCEPTANCE: min approach dwell time (PVAT_MIN_APPROACH_CANDLES)
          - APPROACH→ACCEPTANCE: logs detail block (_log_pvat_acceptance_detail)
          - REJECTED→APPROACH: uses config PVAT_APPROACH_PROXIMITY_PCT (was hardcoded 1.0%)
        """
        data = self._stock_states.get(symbol)
        if not data:
            return None

        levels = self._key_levels.get(symbol, {})
        if not levels:
            return None

        price = data.last_price
        if price <= 0:
            return None

        proximity_pct = getattr(self.config, 'PVAT_LEVEL_PROXIMITY_PCT', 0.3)
        buffer_pct = getattr(self.config, 'PVAT_BREAKOUT_BUFFER_PCT', 0.2)
        approach_pct = getattr(self.config, 'PVAT_APPROACH_PROXIMITY_PCT', 0.5)
        min_level_score = getattr(self.config, 'PVAT_MIN_LEVEL_SCORE', 25)
        min_approach_candles = getattr(self.config, 'PVAT_MIN_APPROACH_CANDLES', 1)

        # Find nearest level
        nearest_type, nearest_dist = self._find_nearest_level(price, levels)
        nearest_price = levels.get(nearest_type, 0)
        if nearest_price <= 0:
            return None

        level_side = self._get_level_side(nearest_type, price, nearest_price)
        old_state = data.state

        # ─── IDLE → APPROACH ───
        if data.state == PVATState.IDLE:
            # v2.1 Fix A: configurable approach threshold (was hardcoded 1.0%)
            if nearest_dist <= approach_pct:
                # v5.4.3: Use pre-computed score from level_evidence (rejection-verified)
                evidence = levels.get('level_evidence', {}).get(nearest_type, {})
                if evidence:
                    level_score = evidence.get('score', 0)
                else:
                    candles = self._candle_cache_15m.get(symbol, [])
                    level_score = self._score_level(nearest_price, nearest_type, candles) if candles else 0

                if level_score < min_level_score:
                    logger.debug(
                        f"PVAT {symbol}: IDLE — near {nearest_type.upper()} "
                        f"₹{nearest_price:.0f} ({nearest_dist:.2f}%) but "
                        f"level_score={level_score} < {min_level_score} — skipped"
                    )
                    return None

                data.state = PVATState.APPROACH
                data.tracked_level_price = nearest_price
                data.tracked_level_type = nearest_type.upper()
                data.tracked_level_side = level_side
                data.tracked_level_score = level_score
                # v5.4.3: Store rejection metadata for downstream use
                data.tracked_level_rejections = len(evidence.get('rejections', [])) if evidence else 0
                data.tracked_level_confluence_days = evidence.get('confluence_days', 0) if evidence else 0
                data.approach_time = datetime.now()
                # v2.1 Fix B: record approach candle boundary for dwell time check
                now_t = datetime.now()
                ms = now_t.minute // 15 * 15
                data.approach_candle_boundary = now_t.replace(
                    minute=ms, second=0, microsecond=0
                )
                data.approach_candle_count = 0  # Will increment on next candle boundary
                logger.info(
                    f"📊 PVAT {symbol}: IDLE → APPROACH "
                    f"(within {nearest_dist:.2f}% of {nearest_type.upper()} "
                    f"₹{nearest_price:.2f} | score={level_score} | "
                    f"rejections={data.tracked_level_rejections} | "
                    f"confluence={data.tracked_level_confluence_days}d)"
                )
                self._log_event(
                    f"{symbol}: IDLE->APPROACH | {nearest_type.upper()} "
                    f"Rs.{nearest_price:.0f} | dist={nearest_dist:.2f}% | "
                    f"score={level_score} | rej={data.tracked_level_rejections}",
                    'phase'
                )
                self._log_pvat_approach(symbol, data, nearest_dist,
                                        nearest_type, nearest_price)

        # ─── APPROACH → ACCEPTANCE or back to IDLE ───
        elif data.state == PVATState.APPROACH:
            # Recalculate distance to tracked level
            tracked_dist = abs(price - data.tracked_level_price) / data.tracked_level_price * 100

            if tracked_dist <= proximity_pct:
                # v2.1 Fix B: must dwell in APPROACH for min candle boundaries
                if data.approach_candle_count < min_approach_candles:
                    logger.debug(
                        f"PVAT {symbol}: within acceptance zone ({tracked_dist:.2f}%) "
                        f"but approach_candles={data.approach_candle_count} "
                        f"< min={min_approach_candles} — waiting"
                    )
                    return None

                data.state = PVATState.ACCEPTANCE
                data.acceptance_start_time = datetime.now()
                data.acceptance_candle_count = 1
                # Record candle boundary at acceptance start
                now_t = datetime.now()
                ms = now_t.minute // 15 * 15
                data.acceptance_candle_boundary = now_t.replace(
                    minute=ms, second=0, microsecond=0
                )
                data.acceptance_zone_high = max(price, data.tracked_level_price) * 1.003
                data.acceptance_zone_low = min(price, data.tracked_level_price) * 0.997
                data.volume_at_acceptance_start = data.candle_volume
                data.volume_declining = False
                logger.info(
                    f"🎯 PVAT {symbol}: APPROACH → ACCEPTANCE "
                    f"(within {tracked_dist:.2f}% of {data.tracked_level_type} "
                    f"₹{data.tracked_level_price:.2f})"
                )
                self._log_event(
                    f"{symbol}: APPROACH->ACCEPTANCE | "
                    f"{data.tracked_level_type} Rs.{data.tracked_level_price:.0f} | "
                    f"dist={tracked_dist:.2f}%",
                    'success'
                )
                # v2.1 Fix C: detailed acceptance log block at transition
                self._log_pvat_acceptance_detail(symbol, data, tracked_dist)
            elif tracked_dist > 2.0:
                # Drifted too far — back to IDLE
                data.state = PVATState.IDLE
                data.tracked_level_price = 0
                data.tracked_level_type = ""
                data.approach_candle_count = 0

        # ─── ACCEPTANCE → counting / REJECTED / BREAKOUT ───
        elif data.state == PVATState.ACCEPTANCE:
            tracked_dist = abs(price - data.tracked_level_price) / data.tracked_level_price * 100

            if tracked_dist > 0.5:
                # Check if this is a breakout (beyond level + buffer) or rejection (bounced away)
                beyond_level = False
                if data.tracked_level_side == 'RESISTANCE':
                    beyond_level = price > data.tracked_level_price * (1 + buffer_pct / 100)
                else:
                    beyond_level = price < data.tracked_level_price * (1 - buffer_pct / 100)

                if beyond_level:
                    # ACT 4: Check breakout gates (only 2: price beyond level + acceptance duration)
                    if self._check_breakout_gates(symbol, data):
                        data.state = PVATState.BREAKOUT_CONFIRMED
                        logger.warning(
                            f"🎯 PVAT {symbol}: ACCEPTANCE → BREAKOUT_CONFIRMED "
                            f"({data.acceptance_candle_count} candles at "
                            f"{data.tracked_level_type})"
                        )
                        self._log_event(
                            f"{symbol}: BREAKOUT CONFIRMED! "
                            f"{data.acceptance_candle_count} candles at "
                            f"{data.tracked_level_type} Rs.{data.tracked_level_price:.0f}",
                            'warning'
                        )
                        return self._build_signal_dict(symbol, data)
                    # Not enough acceptance candles yet — still watching
                else:
                    # Bounced away from level — rejected
                    data.state = PVATState.REJECTED
                    data.prev_state = PVATState.ACCEPTANCE
                    logger.info(
                        f"🔴 PVAT {symbol}: ACCEPTANCE → REJECTED "
                        f"(bounced {tracked_dist:.2f}% from "
                        f"{data.tracked_level_type})"
                    )

        # ─── REJECTED → can re-approach ───
        elif data.state == PVATState.REJECTED:
            tracked_dist = abs(price - data.tracked_level_price) / data.tracked_level_price * 100
            # v2.1 Fix A: use config approach threshold (was hardcoded 1.0%)
            if tracked_dist <= approach_pct and data.tracked_level_price > 0:
                data.state = PVATState.APPROACH
                data.acceptance_candle_count = 0
                # v2.1 Fix B: reset approach dwell tracking for re-approach
                now_t = datetime.now()
                ms = now_t.minute // 15 * 15
                data.approach_candle_boundary = now_t.replace(
                    minute=ms, second=0, microsecond=0
                )
                data.approach_candle_count = 0
                logger.info(
                    f"✈️ PVAT {symbol}: REJECTED → APPROACH (re-approaching "
                    f"{data.tracked_level_type})"
                )

        return None

    # ─────────────────────────────────────────────────────────────────
    # BREAKOUT CONFIRMATION (ACT 4 — 4 gates v5.4.2)
    # ─────────────────────────────────────────────────────────────────

    def _check_breakout_gates(self, symbol: str, data: PVATStockData) -> bool:
        """
        ACT 4 confirmation: 4 gates for breakout quality (v5.4.2).
        Gate 1: Price beyond level + ATR-relative buffer (FIX 5)
        Gate 2: Minimum acceptance candles
        Gate 3: Volume confirmation at breakout (FIX 1)
        Gate 4: Candle body quality — no dojis (FIX 2)
        """
        price = data.last_price

        # Gate 1 (FIX 5): Price beyond level + ATR-relative buffer
        atr = self._key_levels.get(symbol, {}).get('atr_15m', 0)
        atr_factor = getattr(self.config, 'PVAT_BREAKOUT_ATR_FACTOR', 0.3)
        if atr > 0:
            buffer = atr * atr_factor
        else:
            # Fallback to percentage-based buffer if no ATR data
            buffer_pct = getattr(self.config, 'PVAT_BREAKOUT_BUFFER_PCT', 0.2)
            buffer = data.tracked_level_price * (buffer_pct / 100)

        if data.tracked_level_side == 'RESISTANCE':
            if price <= (data.tracked_level_price + buffer):
                return False
        else:  # SUPPORT breakdown
            if price >= (data.tracked_level_price - buffer):
                return False

        # Gate 2: Minimum acceptance candles (ACT 3 must be complete)
        min_candles = getattr(self.config, 'PVAT_ACCEPTANCE_MIN_CANDLES', 3)
        if data.acceptance_candle_count < min_candles:
            return False

        # Gate 3 (FIX 1): Volume confirmation — breakout candle must have above-avg volume
        avg_vol = self._key_levels.get(symbol, {}).get('avg_volume_15m', 0)
        min_vol_ratio = getattr(self.config, 'PVAT_MIN_BREAKOUT_VOLUME_RATIO', 1.5)
        if avg_vol > 0 and data.candle_volume > 0:
            vol_ratio = data.candle_volume / avg_vol
            if vol_ratio < min_vol_ratio:
                logger.debug(f"PVAT {symbol}: Volume gate FAIL — ratio {vol_ratio:.2f} < {min_vol_ratio}")
                return False

        # Gate 4 (FIX 2): Candle body must be substantial (no dojis/wicks)
        candles = self._candle_cache_15m.get(symbol, [])
        if candles:
            latest = candles[-1]
            body = abs(latest['close'] - latest['open'])
            total_range = latest['high'] - latest['low']
            min_body_pct = getattr(self.config, 'PVAT_MIN_CANDLE_BODY_PCT', 0.40)
            if total_range > 0 and (body / total_range) < min_body_pct:
                logger.debug(f"PVAT {symbol}: Candle body gate FAIL — {body/total_range:.1%} < {min_body_pct:.0%}")
                return False

        return True

    # ─────────────────────────────────────────────────────────────────
    # SIGNAL & CANDIDATE BUILDERS
    # ─────────────────────────────────────────────────────────────────

    def _estimate_breakout_volume_ratio(self, data: 'PVATStockData',
                                         avg_volume_15m: float) -> float:
        """
        Compute normalized volume ratio for breakout quality assessment.
        Informational metadata for Phase 5 — NOT used as a blocking gate.

        candle_volume = delta between consecutive scans
        avg_volume_15m = historical average per 15-min candle

        Normalizes scan-interval delta to 15-min equivalent.
        With 3-loop burst at candle boundaries, Loop 1 delta ≈ full 15-min candle.
        Loop 2/3 deltas are shorter intervals, scale up accordingly.
        """
        if avg_volume_15m <= 0 or data.candle_volume <= 0:
            return 0.0
        # Conservative: use raw delta vs avg, no scale factor needed for Loop 1
        # For Loop 2/3 (30-60s deltas), the volume ratio will naturally be lower
        # Phase 5 composite score handles the interpretation
        return data.candle_volume / avg_volume_15m

    def _build_signal_dict(self, symbol: str, data: PVATStockData) -> Dict:
        """Build signal with raw pattern metadata for Phase 5 handoff."""
        levels = self._key_levels.get(symbol, {})
        avg_vol = levels.get('avg_volume_15m', 1)
        atr = levels.get('atr_15m', 0)
        vol_ratio = self._estimate_breakout_volume_ratio(data, avg_vol)
        direction = 'LONG' if data.tracked_level_side == 'RESISTANCE' else 'SHORT'

        # Today's open from cache
        candles = self._candle_cache_15m.get(symbol, [])
        today_candles = [c for c in candles
                         if (c['date'].date() if hasattr(c['date'], 'date') else c['date']) == date.today()]
        today_open = today_candles[0]['open'] if today_candles else data.last_price

        return {
            'state': 'BREAKOUT_CONFIRMED',
            'symbol': symbol,
            'direction': direction,
            'level_type': data.tracked_level_type,
            'level_price': data.tracked_level_price,
            'level_side': data.tracked_level_side,
            'breakout_price': data.last_price,
            'acceptance_candle_count': data.acceptance_candle_count,
            'volume_declining': data.volume_declining,
            'breakout_volume_ratio': vol_ratio,  # informational for Phase 5
            'today_open': today_open,
            'atr': atr,
            'avg_volume': avg_vol,
        }

    # ─────────────────────────────────────────────────────────────────
    # v5.4.2: INDEPENDENT EXECUTION PIPELINE (replaces Phase 5 handoff)
    # ─────────────────────────────────────────────────────────────────

    def _calculate_pvat_score(self, symbol: str, stock_data: PVATStockData) -> float:
        """
        v5.4.2: PVAT-specific composite score (0-100).
        Replaces Phase 5's gap-centric scorer which penalized PVAT by ~22 points.

        5 components:
          1. Level Quality (0-25): How strong is the level being tested?
          2. Acceptance Quality (0-25): How clean was the acceptance phase?
          3. Breakout Volume (0-20): Volume confirmation at breakout
          4. Candle Quality (0-15): Body strength + wick rejection
          5. Coil-to-Spike Bonus (0-15): Volume expanding from declining base
        """
        score = 0.0

        # 1. Level Quality (0-25): How strong is the level being tested?
        level_score = stock_data.tracked_level_score  # 0-100 from level engine
        score += (level_score / 100) * 25

        # 2. Acceptance Quality (0-25): How clean was the acceptance phase?
        acceptance_candles = stock_data.acceptance_candle_count
        # 3 candles = baseline (15/25), 5+ candles = full (25/25)
        acceptance_pts = min(25, max(0, 10 + (acceptance_candles - 3) * 5))
        # Bonus: volume declining during acceptance = healthy coil
        if stock_data.volume_declining:
            acceptance_pts = min(25, acceptance_pts + 5)
        score += acceptance_pts

        # 3. Breakout Volume (0-20): Volume confirmation at breakout
        avg_vol = self._key_levels.get(symbol, {}).get('avg_volume_15m', 0)
        if avg_vol > 0 and stock_data.candle_volume > 0:
            vol_ratio = stock_data.candle_volume / avg_vol
            vol_pts = min(20, max(0, (vol_ratio - 1.0) * 20))  # 1x=0pts, 2x=20pts
        else:
            vol_pts = 10  # neutral if no data
        score += vol_pts

        # 4. Candle Quality (0-15): Body strength + wick rejection
        candles = self._candle_cache_15m.get(symbol, [])
        if candles:
            latest = candles[-1]
            body = abs(latest['close'] - latest['open'])
            total_range = latest['high'] - latest['low']
            if total_range > 0:
                body_pct = body / total_range
                candle_pts = min(15, body_pct * 20)  # 75% body = 15pts
            else:
                candle_pts = 7
        else:
            candle_pts = 7
        score += candle_pts

        # 5. Coil-to-Spike Bonus (0-15): Volume expanding from declining base
        if stock_data.volume_declining and avg_vol > 0 and stock_data.candle_volume > 0:
            spike_ratio = stock_data.candle_volume / avg_vol
            if spike_ratio >= 2.0:
                score += 15  # Strong coil-to-spike
            elif spike_ratio >= 1.5:
                score += 10
            elif spike_ratio >= 1.2:
                score += 5

        final_score = min(100, round(score, 1))

        logger.info(f"   📊 PVAT Score Breakdown for {symbol}:")
        logger.info(f"      Level Quality: {(level_score / 100) * 25:.1f}/25")
        logger.info(f"      Acceptance:    {acceptance_pts:.1f}/25 ({acceptance_candles} candles, vol_declining={stock_data.volume_declining})")
        logger.info(f"      Breakout Vol:  {vol_pts:.1f}/20")
        logger.info(f"      Candle Body:   {candle_pts:.1f}/15")
        logger.info(f"      TOTAL:         {final_score}/100")

        return final_score

    def _calculate_pvat_position_size(self, symbol: str, entry_price: float, score: float) -> int:
        """v5.4.2: Score-based position sizing. Returns quantity (0 = no trade)."""
        if not self.capital_manager:
            logger.warning(f"PVAT {symbol}: No capital manager — using fallback size")
            return max(1, int(10000 / entry_price)) if entry_price > 0 else 0

        available = self.capital_manager.get_available()
        max_value = getattr(self.config, 'PVAT_MAX_POSITION_VALUE', 10000)
        max_pct = getattr(self.config, 'PVAT_MAX_CAPITAL_PCT', 0.5)
        capital_limit = min(max_value, available * max_pct)

        min_score = getattr(self.config, 'PVAT_FULL_SIZE_SCORE', 75)

        if score >= min_score:
            position_value = capital_limit
            size_label = 'FULL'
        else:
            # Score below 75 = NO ENTRY, observation only
            logger.info(f"PVAT {symbol}: Score {score} < {min_score} — NO TRADE (below 75 threshold)")
            log_regret_trade(symbol, score, "PVAT", "SCORE_BELOW_75",
                            entry_price=entry_price, phase="Phase5A")
            return 0

        quantity = int(position_value / entry_price) if entry_price > 0 else 0
        quantity = max(1, quantity) if quantity > 0 else 0

        logger.info(f"   💰 PVAT Sizing: {size_label} | Capital ₹{position_value:.0f} | "
                     f"Qty {quantity} @ ₹{entry_price:.2f} | Available ₹{available:.0f}")

        return quantity

    def _get_pvat_chatgpt_approval(self, symbol: str, stock_data: PVATStockData,
                                     score: float) -> dict:
        """v5.4.2: ChatGPT pre-entry gate for PVAT trades."""
        if not getattr(self.config, 'PVAT_CHATGPT_ENABLED', True):
            return {'approved': True, 'confidence': 1.0, 'reason': 'ChatGPT disabled'}

        if not self.chatgpt:
            logger.warning("PVAT: ChatGPT advisor not available — auto-approving")
            return {'approved': True, 'confidence': 0.5, 'reason': 'Advisor unavailable'}

        try:
            prompt = self._build_pvat_chatgpt_prompt(symbol, stock_data, score)
            response = self.chatgpt.get_decision(prompt)

            if response:
                import re
                import json as _json
                json_match = re.search(r'\{[^{}]+\}', response)
                if json_match:
                    result = _json.loads(json_match.group())
                    approved_raw = result.get('decision', '').upper() == 'APPROVE'
                    confidence = float(result.get('confidence', 0.5))
                    reasoning = result.get('reasoning', '')
                    min_conf = getattr(self.config, 'PVAT_CHATGPT_MIN_CONFIDENCE', 0.60)

                    approved = approved_raw and confidence >= min_conf
                    if approved_raw and not approved:
                        reasoning = f"Confidence {confidence:.0%} below threshold {min_conf:.0%}"

                    logger.info(f"   🤖 ChatGPT: {'APPROVED ✅' if approved else 'REJECTED ❌'} "
                                 f"| Confidence: {confidence:.0%} | {reasoning}")

                    return {
                        'approved': approved,
                        'confidence': confidence,
                        'reason': reasoning,
                        'raw_response': response
                    }

            # No parseable response — auto-approve with low confidence
            logger.warning("PVAT ChatGPT: Unparseable response — auto-approving")
            return {'approved': True, 'confidence': 0.5, 'reason': 'Unparseable response'}

        except Exception as e:
            logger.error(f"PVAT ChatGPT gate error: {e} — auto-approving")
            return {'approved': True, 'confidence': 0.5, 'reason': f'Error: {e}'}

    def _build_pvat_chatgpt_prompt(self, symbol: str, stock_data: PVATStockData,
                                     score: float) -> str:
        """Build PVAT-specific ChatGPT prompt with 4-act pattern context."""
        direction = 'LONG' if stock_data.tracked_level_side == 'RESISTANCE' else 'SHORT'
        level_type = stock_data.tracked_level_type
        level_price = stock_data.tracked_level_price
        breakout_price = stock_data.last_price
        acc_candles = stock_data.acceptance_candle_count
        vol_declining = stock_data.volume_declining

        # Volume ratio
        avg_vol = self._key_levels.get(symbol, {}).get('avg_volume_15m', 0)
        vol_ratio = (stock_data.candle_volume / avg_vol) if avg_vol > 0 else 0

        # Breakout distance
        breakout_pct = abs(breakout_price - level_price) / max(level_price, 1) * 100

        prompt = f"""🔷 PHASE 5A PVAT BREAKOUT — INDEPENDENT ENTRY DECISION

CANDIDATE: {symbol}
Direction: {direction}
Entry Price: ₹{breakout_price:.2f}

═══ 4-ACT BREAKOUT PATTERN ═══

ACT 1 — LEVEL EXISTS:
  Level Type: {level_type}
  Level Price: ₹{level_price:.2f}
  Level Score: {stock_data.tracked_level_score}/100
  Confirmed Rejections: {stock_data.tracked_level_rejections} across {stock_data.tracked_level_confluence_days} days

ACT 3 — ACCEPTANCE (sellers exhausted):
  Duration: {acc_candles} candles ({acc_candles * 15} minutes at level)
  Volume Declining: {'YES ✅ — sellers running out' if vol_declining else 'NO ⚠️ — active trading'}

ACT 4 — BREAKOUT:
  Breakout Distance: {breakout_pct:.2f}% beyond level
  Breakout Volume: {vol_ratio:.1f}x average {'✅ STRONG' if vol_ratio >= 2.0 else '⚠️ MODERATE' if vol_ratio >= 1.5 else '❌ WEAK'}

═══ PVAT SCORE ═══
  Composite Score: {score:.0f}/100
  Size: FULL (score >= {getattr(self.config, 'PVAT_FULL_SIZE_SCORE', 75)})
  Product: MIS (intraday, exit by 15:00)

QUESTION: Based on the 4-ACT pattern quality, should we ENTER this {direction} breakout?

Respond ONLY with valid JSON:
{{"decision": "APPROVE" or "REJECT", "confidence": 0.0-1.0, "reasoning": "brief reason", "risk_assessment": "LOW/MEDIUM/HIGH"}}"""

        return prompt

    def _execute_pvat_entry(self, symbol: str, direction: str,
                             entry_price: float, quantity: int) -> dict:
        """v5.4.2: Place MIS order directly via Kite (or paper)."""
        transaction_type = 'BUY' if direction == 'LONG' else 'SELL'

        try:
            order_id = self._place_order(
                variety=self.kite.VARIETY_REGULAR,
                exchange=self.kite.EXCHANGE_NSE,
                tradingsymbol=symbol,
                transaction_type=transaction_type,
                quantity=quantity,
                product=self.kite.PRODUCT_MIS,
                order_type=self.kite.ORDER_TYPE_MARKET,
            )
            logger.info(f"   ✈️ PVAT ORDER PLACED: {symbol} {transaction_type} qty={quantity} order_id={order_id}")
            return {'success': True, 'order_id': order_id}
        except Exception as e:
            logger.error(f"   ❌ PVAT order failed for {symbol}: {e}")
            return {'success': False, 'error': str(e)}

    def _verify_pvat_order_fill(self, order_id: str) -> dict:
        """v5.4.2: Poll broker for fill confirmation (10s timeout).
        v5.7.0: Paper IDs (PH5A_PAPER_*) return simulated fill immediately —
        never reach kite.order_history, which would REJECT or error on fake IDs."""
        if str(order_id).startswith('PH5A_PAPER_'):
            # Simulate immediate fill at the level price stored in the paper log
            _sim_price = 0.0
            try:
                if os.path.isfile(self._paper_log_path):
                    with open(self._paper_log_path) as _f:
                        _trades = json.load(_f)
                    for _t in reversed(_trades):
                        if _t.get('order_id') == order_id:
                            _sim_price = float(_t.get('price', 0))
                            break
            except Exception:
                pass
            logger.info(f"  📝 Paper fill confirmed: {order_id} @ ₹{_sim_price:.2f}")
            return {
                'filled': True,
                'average_price': _sim_price,
                'filled_qty': 0,   # caller uses requested quantity
                'status': 'PAPER_COMPLETE'
            }

        for attempt in range(10):
            try:
                history = self.kite.order_history(order_id)
                if history:
                    last = history[-1]
                    status = last.get('status', '')
                    if status == 'COMPLETE':
                        return {
                            'filled': True,
                            'average_price': last.get('average_price', 0),
                            'filled_qty': last.get('filled_quantity', 0),
                            'status': status
                        }
                    elif status in ('REJECTED', 'CANCELLED'):
                        return {
                            'filled': False,
                            'status': status,
                            'reason': last.get('status_message', '')
                        }
            except Exception:
                pass
            time.sleep(1)
        return {'filled': False, 'status': 'TIMEOUT'}

    def _handoff_to_phase4(self, symbol: str, direction: str, entry_price: float,
                            quantity: int, atr: float, score: float,
                            chatgpt_result: dict) -> bool:
        """v5.4.2: Register position with Phase 4 for TIER_1 monitoring."""
        if not self.phase4:
            logger.error(f"PVAT {symbol}: No Phase 4 manager — cannot handoff!")
            return False

        stop_mult = getattr(self.config, 'PVAT_STOP_ATR_MULTIPLIER', 0.5)
        tcas_pct = getattr(self.config, 'PVAT_TCAS_ACTIVATION_PCT', 0.3)

        # Use daily ATR for stop sizing — the 15-min ATR passed in is for level discovery
        # only and is 10-15× too small to represent real daily move risk.
        daily_atr = self._fetch_daily_atr(symbol, entry_price)
        atr_for_stop = daily_atr  # replace 15-min atr with daily for all risk sizing

        # Calculate ATR-based stop
        atr_stop = atr_for_stop * stop_mult if atr_for_stop > 0 else entry_price * 0.015

        # Minimum 0.5% of entry price — NEVER go below this
        min_stop = entry_price * 0.005

        # Use acceptance zone boundary if available
        acceptance_zone_stop = 0
        if hasattr(self, '_pvat_stocks') and symbol in self._pvat_stocks:
            sd = self._pvat_stocks[symbol]
            if direction == 'LONG' and sd.acceptance_zone_low > 0:
                acceptance_zone_stop = entry_price - sd.acceptance_zone_low
            elif direction == 'SHORT' and sd.acceptance_zone_high > 0:
                acceptance_zone_stop = sd.acceptance_zone_high - entry_price

        # Use the MAXIMUM of all three (widest stop wins)
        stop_distance = max(atr_stop, min_stop, acceptance_zone_stop)

        if direction == 'LONG':
            stop_price = entry_price - stop_distance
        else:
            stop_price = entry_price + stop_distance

        position_data = {
            'symbol': symbol,
            'direction': direction,
            'entry_price': entry_price,
            'entry_time': datetime.now().isoformat(),
            'quantity': quantity,
            'product': 'MIS',
            'source': 'PHASE5A_PVAT',
            'monitoring_tier': 'TIER_1',
            'stop_price': stop_price,
            'tcas_activation_pct': tcas_pct,
            'atr': daily_atr,       # daily ATR — safe for PH4 TIER1 proximity threshold
            'atr_15m': atr,         # preserved for reference/logging only
            'pvat_score': score,
            'chatgpt_approval': chatgpt_result,
            # PVAT timing overrides
            'max_hold_minutes': getattr(self.config, 'PVAT_MAX_HOLD_MINUTES', 240),
            'breakeven_trail_time': dt_time(14, 30),
            'hard_exit_time': dt_time(14, 50),
            'mandatory_exit_time': dt_time(15, 0),
        }

        try:
            self.phase4.add_phase5_position(position_data)
            logger.info(f"   📡 PVAT → Phase 4 handoff OK: {symbol} TIER_1 | "
                         f"Stop ₹{stop_price:.2f} | TCAS {tcas_pct:.1%}")
            return True
        except Exception as e:
            logger.error(f"   ❌ PVAT → Phase 4 handoff FAILED: {e}")
            return False

    def _execute_pvat_pipeline(self, symbol: str, stock_data: PVATStockData) -> dict:
        """
        v5.4.2: Independent PVAT execution pipeline. No Phase 5 dependency.

        Steps:
          1. Score (PVAT-specific 5-component scorer)
          2. Entry price + ATR
          3. Position sizing (score-based)
          4. ChatGPT approval gate
          5. Place MIS order
          6. Verify fill
          7. Deploy capital
          8. Handoff to Phase 4 TIER_1
          9. Notify + mark trade fired
        """
        logger.info("")
        logger.info("=" * 80)
        logger.info(f"   🔷 PVAT INDEPENDENT EXECUTION: {symbol}")
        logger.info("=" * 80)

        # Step 1: Score
        score = self._calculate_pvat_score(symbol, stock_data)

        min_threshold = getattr(self.config, 'PVAT_FULL_SIZE_SCORE', 75)
        if score < min_threshold:
            logger.info(f"   ❌ PVAT {symbol}: Score {score} < {min_threshold} — NO TRADE")
            self._log_event(f"{symbol}: Score {score} < {min_threshold} -- REJECTED", 'error')
            log_regret_trade(symbol, score, "PVAT", "SCORE_BELOW_75",
                            entry_price=stock_data.last_price, phase="Phase5A")
            return {'traded': False, 'reason': f'Score {score} below threshold {min_threshold}'}

        # Step 2: Get entry price + ATR
        entry_price = stock_data.last_price
        atr = self._key_levels.get(symbol, {}).get('atr_15m', 0)
        direction = 'LONG' if stock_data.tracked_level_side == 'RESISTANCE' else 'SHORT'

        logger.info(f"   📋 Direction: {direction} | Entry: ₹{entry_price:.2f} | ATR: {atr:.2f}")

        # Step 3: Position sizing
        quantity = self._calculate_pvat_position_size(symbol, entry_price, score)
        if quantity <= 0:
            return {'traded': False, 'reason': 'Insufficient capital or below size threshold'}

        # Step 4: ChatGPT approval
        chatgpt_result = self._get_pvat_chatgpt_approval(symbol, stock_data, score)
        if not chatgpt_result['approved']:
            logger.info(f"   🚫 PVAT {symbol}: ChatGPT REJECTED (conf={chatgpt_result['confidence']:.2f})")
            self._log_event(
                f"{symbol}: ChatGPT REJECT conf={chatgpt_result['confidence']:.2f} -- {chatgpt_result.get('reason', '')}",
                'error'
            )
            if self.telegram:
                try:
                    self.telegram.send_message(
                        f"🚫 PVAT {symbol}: ChatGPT rejected — {chatgpt_result['reason']}"
                    )
                except Exception:
                    pass
            return {'traded': False, 'reason': f'ChatGPT rejected: {chatgpt_result["reason"]}'}

        self._log_event(
            f"{symbol}: ChatGPT APPROVE conf={chatgpt_result['confidence']:.2f} | Score={score}",
            'success'
        )

        # Step 5: Place order
        order_result = self._execute_pvat_entry(symbol, direction, entry_price, quantity)
        if not order_result['success']:
            return {'traded': False, 'reason': f'Order failed: {order_result.get("error", "unknown")}'}

        # Step 6: Verify fill
        fill = self._verify_pvat_order_fill(order_result['order_id'])
        if not fill['filled']:
            logger.warning(f"   ⚠️ PVAT {symbol}: Order not filled — {fill['status']}")
            return {'traded': False, 'reason': f'Fill failed: {fill["status"]}'}

        actual_price = fill.get('average_price') or entry_price
        filled_qty = fill.get('filled_qty', quantity)

        logger.info(f"   ✅ FILL CONFIRMED: ₹{actual_price:.2f} x {filled_qty}")
        self._log_event(
            f"{symbol}: TRADE EXECUTED {direction} Rs.{actual_price:.2f} x {filled_qty}",
            'success'
        )

        # Step 7: Deploy capital
        if self.capital_manager:
            try:
                margin_used = actual_price * filled_qty
                self.capital_manager.deploy(
                    symbol=symbol,
                    amount=margin_used,
                    quantity=filled_qty,
                    avg_price=actual_price,
                    source='PHASE5A_PVAT',
                    product='MIS'
                )
                logger.info(f"   💰 Capital deployed: ₹{margin_used:.0f}")
            except Exception as e:
                logger.error(f"   ⚠️ PVAT capital deploy error: {e}")

        # Step 8: Handoff to Phase 4
        self._handoff_to_phase4(symbol, direction, actual_price, filled_qty,
                                 atr, score, chatgpt_result)

        # Step 9: Mark trade fired + notify
        self._trade_fired = True

        if self.telegram:
            try:
                dir_emoji = '✈️ LONG' if direction == 'LONG' else '↘️ SHORT'
                self.telegram.send_message(
                    f"🔷 PVAT TRADE EXECUTED\n\n"
                    f"Stock: {symbol}\n"
                    f"Direction: {dir_emoji}\n"
                    f"Entry: ₹{actual_price:.2f} | Qty: {filled_qty}\n"
                    f"Score: {score}/100 | ChatGPT: {chatgpt_result['confidence']:.0%}\n"
                    f"ATR: {atr:.2f}\n\n"
                    f"✈️ Phase 5A → Phase 4 TIER_1 (independent)"
                )
            except Exception:
                pass

        logger.info("")
        logger.info(f"   🎯 PVAT TRADE COMPLETE: {symbol} {direction} | "
                     f"₹{actual_price:.2f} x {filled_qty} | Score {score}")
        logger.info("=" * 80)

        return {
            'traded': True,
            'symbol': symbol,
            'direction': direction,
            'price': actual_price,
            'quantity': filled_qty,
            'score': score,
            'chatgpt_confidence': chatgpt_result.get('confidence', 0),
            'order_id': order_result.get('order_id')
        }

    def _log_pvat_mission_complete_v2(self, symbol: str, signal: Dict, result: dict):
        """LOG 6 (v5.4.2): Mission complete — PVAT trade independently executed."""
        level_type = signal.get('level_type', '?')
        level_price = signal.get('level_price', 0)
        entry_price = result.get('price', 0)
        acc_candles = signal.get('acceptance_candle_count', 0)
        score = result.get('score', 0)

        logger.info("")
        logger.info(f"✅ PVAT DONE: {symbol} | {level_type} @ ₹{level_price:.2f} | "
                     f"Entry ₹{entry_price:.2f} | {acc_candles} candles | Score {score} | "
                     f"✈️ Phase 5A → Phase 4 TIER_1 (independent)")
        logger.info("")

    # ─────────────────────────────────────────────────────────────────
    # PVAT FLIGHT PATH VISUALIZATION
    # ─────────────────────────────────────────────────────────────────

    def _print_pvat_flight_path(self, signal: Dict):
        """
        Kalman-style PVAT flight path visualization.
        Matches Phase 4's Kalman Flight Path format with diagonal arrows.
        Shows breakout trajectory from level through target.
        """
        symbol = signal['symbol']
        level = signal['level_price']
        price = signal['breakout_price']
        direction = signal['direction']
        atr = signal.get('atr', 0)
        acc_candles = signal.get('acceptance_candle_count', 3)
        level_type = signal.get('level_type', '???')
        vol_ratio = signal.get('breakout_volume_ratio', 0)
        vol_declining = signal.get('volume_declining', False)
        target_mult = getattr(self.config, 'PVAT_TARGET_MULTIPLIER', 2.0)

        # Use candle cache for breakout candle range
        candles = self._candle_cache_15m.get(symbol, [])
        if candles:
            bc_high = candles[-1]['high']
            bc_low = candles[-1]['low']
        else:
            bc_high = price
            bc_low = price
        acc_range = abs(bc_high - bc_low)
        target_dist = acc_range * target_mult if acc_range > 0 else atr

        if direction == 'LONG':
            stop = level - 0.3 * atr if atr > 0 else level * 0.997
            target = price + target_dist
            arrow = "↗️"
            target_pct = (target - price) / price * 100 if price > 0 else 0
            stop_pct = (price - stop) / price * 100 if price > 0 else 0
        else:
            stop = level + 0.3 * atr if atr > 0 else level * 1.003
            target = price - target_dist
            arrow = "↘️"
            target_pct = (price - target) / price * 100 if price > 0 else 0
            stop_pct = (stop - price) / price * 100 if price > 0 else 0

        # Projected prices
        move_per_step = (price - level) * 0.5 if direction == 'LONG' else (level - price) * 0.5
        p_15m = price + move_per_step if direction == 'LONG' else price - move_per_step
        p_30m = price + move_per_step * 1.5 if direction == 'LONG' else price - move_per_step * 1.5
        p_60m = price + move_per_step * 2.0 if direction == 'LONG' else price - move_per_step * 2.0

        # Clamp projections to target
        if direction == 'LONG':
            p_15m = min(p_15m, target)
            p_30m = min(p_30m, target)
            p_60m = min(p_60m, target)
        else:
            p_15m = max(p_15m, target)
            p_30m = max(p_30m, target)
            p_60m = max(p_60m, target)

        # ═══════════════════════════════════════════════════════════════
        # LOG 3: BREAKOUT FLIGHT PATH (Kalman-style diagonal arrows)
        # ═══════════════════════════════════════════════════════════════
        logger.info("")
        logger.info(f"✈️ PVAT BREAKOUT FLIGHT PATH                                       {symbol}")
        logger.info("━" * 85)
        logger.info(f"    Level: {level_type} @ ₹{level:.2f} | "
                     f"Acceptance: {acc_candles} candles | Vol: {vol_ratio:.1f}x | "
                     f"Vol Declining: {'YES' if vol_declining else 'NO'}")
        logger.info("")

        if direction == 'LONG':
            logger.info(f"                                              🎯 ₹{target:.2f} TARGET [+{target_pct:.1f}%]")
            logger.info(f"                                           {arrow}")
            logger.info(f"                                      {arrow} ₹{p_60m:.2f} (+60m)")
            logger.info(f"                                 {arrow}")
            logger.info(f"                            {arrow} ₹{p_30m:.2f} (+30m)")
            logger.info(f"                       {arrow}")
            logger.info(f"                  {arrow} ₹{p_15m:.2f} (+15m)")
            logger.info(f"             {arrow}")
            logger.info(f"    ✈️ ₹{price:.2f} BREAKOUT")
            logger.info(f"    ═══════════════════════════════════════════════ {level_type} @ ₹{level:.2f}")
            logger.info(f"    ➡️➡️➡️ ACCEPTANCE ({acc_candles} candles)")
            logger.info("")
            logger.info(f"    ⛔ ₹{stop:.2f} TERRAIN ·············································· [-{stop_pct:.1f}%]")
        else:
            logger.info(f"    ⛔ ₹{stop:.2f} TERRAIN ·············································· [-{stop_pct:.1f}%]")
            logger.info("")
            logger.info(f"    ➡️➡️➡️ ACCEPTANCE ({acc_candles} candles)")
            logger.info(f"    ═══════════════════════════════════════════════ {level_type} @ ₹{level:.2f}")
            logger.info(f"    ✈️ ₹{price:.2f} BREAKDOWN")
            logger.info(f"             {arrow}")
            logger.info(f"                  {arrow} ₹{p_15m:.2f} (+15m)")
            logger.info(f"                       {arrow}")
            logger.info(f"                            {arrow} ₹{p_30m:.2f} (+30m)")
            logger.info(f"                                 {arrow}")
            logger.info(f"                                      {arrow} ₹{p_60m:.2f} (+60m)")
            logger.info(f"                                           {arrow}")
            logger.info(f"                                              🎯 ₹{target:.2f} TARGET [+{target_pct:.1f}%]")

        logger.info("")
        logger.info("━" * 85)
        logger.info(f"📊 PVAT FLIGHT DATA:")
        logger.info(f"    ✈️ Direction: {direction} | ATR: ₹{atr:.2f}")
        logger.info(f"    📈 Volume Burst: {vol_ratio:.1f}x average")
        logger.info(f"    🎯 Target: ₹{target:.2f} [+{target_pct:.1f}%] | ⛔ Stop: ₹{stop:.2f} [-{stop_pct:.1f}%]")
        logger.info(f"    🔷 Acceptance: {acc_candles} candles at {level_type} | Vol Declining: {'YES' if vol_declining else 'NO'}")
        logger.info("═" * 85)

    # ─────────────────────────────────────────────────────────────────
    # TOUCH HISTORY ASCII CHART (shared by approach + acceptance logs)
    # ─────────────────────────────────────────────────────────────────

    def _build_touch_chart(self, symbol: str, level_price: float,
                            level_type: str, level_side: str,
                            current_price: float) -> List[str]:
        """
        Build ASCII price chart showing touch history arrows plotted on a
        grid with level line, breakout zone, and current price.

        Y-axis: price rows, auto-scaled from touch range + breakout + NOW
        X-axis: 15-min candle timestamps (up to 12 most recent touches)

        Returns list of log-ready strings (caller logs each line).
        """
        candles = self._candle_cache_15m.get(symbol, [])
        if not candles:
            return ["    (no candle data for chart)"]

        # ── Compute breakout trigger price (v5.4.3: ATR-based, matches _check_breakout_gates) ──
        atr = self._key_levels.get(symbol, {}).get('atr_15m', 0)
        atr_factor = getattr(self.config, 'PVAT_BREAKOUT_ATR_FACTOR', 0.3)
        if atr > 0:
            buffer = atr * atr_factor
        else:
            buffer_pct = getattr(self.config, 'PVAT_BREAKOUT_BUFFER_PCT', 0.2)
            buffer = level_price * (buffer_pct / 100)

        if level_side == 'RESISTANCE':
            breakout_price = level_price + buffer
        else:
            breakout_price = level_price - buffer

        # ── Collect touching candles (last 20, within 0.3% of level) ──
        touch_candles = []
        for c in candles[-20:]:
            c_high = c.get('high', 0)
            c_low = c.get('low', 0)
            c_close = c.get('close', 0)
            if c_close <= 0 or level_price <= 0:
                continue
            if abs(c_high - level_price) / level_price < 0.003 or \
               abs(c_low - level_price) / level_price < 0.003:
                # Classify arrow
                pct_from_level = (c_close - level_price) / level_price * 100
                if abs(pct_from_level) < 0.2:
                    arrow = "➡️"
                elif c_close > level_price:
                    arrow = "↗️"
                else:
                    arrow = "↘️"

                # Extract time
                c_dt = c['date']
                if hasattr(c_dt, 'strftime'):
                    c_time = c_dt.strftime('%H:%M')
                else:
                    c_time = str(c_dt)[-5:]

                touch_candles.append({
                    'close': c_close,
                    'time': c_time,
                    'arrow': arrow,
                })

        if not touch_candles:
            return ["    (no touches near level for chart)"]

        # Keep last 12 touches max
        touch_candles = touch_candles[-12:]
        touch_count = len(touch_candles)

        # ── Compute Y-axis range (auto-scale) ──
        all_prices = [tc['close'] for tc in touch_candles] + [current_price, breakout_price, level_price]
        price_min = min(all_prices)
        price_max = max(all_prices)

        # Add padding (0.15% each side, minimum ₹1)
        padding = max(level_price * 0.0015, 1.0)
        price_min = price_min - padding
        price_max = price_max + padding

        num_rows = 7  # 7 price rows
        row_step = (price_max - price_min) / (num_rows - 1)
        if row_step <= 0:
            row_step = 1.0

        # Build row prices (top = highest)
        row_prices = [price_max - i * row_step for i in range(num_rows)]

        # ── Helper: find closest row index for a price ──
        def price_to_row(p):
            if row_step <= 0:
                return 0
            idx = round((price_max - p) / row_step)
            return max(0, min(num_rows - 1, idx))

        # ── Column width per touch candle ──
        col_w = 6  # chars per column

        # ── Build grid (rows × columns) — empty strings ──
        grid = [["      "] * touch_count for _ in range(num_rows)]

        # Place touch arrows on grid
        for col_idx, tc in enumerate(touch_candles):
            row_idx = price_to_row(tc['close'])
            # Center the arrow in the column (arrow emoji takes ~2 chars display)
            grid[row_idx][col_idx] = f"  {tc['arrow']}  "

        # ── Determine special row markers ──
        level_row = price_to_row(level_price)
        now_row = price_to_row(current_price)
        breakout_row = price_to_row(breakout_price)

        # ── Build output lines ──
        lines = []
        lines.append(f"    📈 Touch History ({touch_count} touches at {level_type} ₹{level_price:.2f}):")

        # Y-axis label width
        price_fmt_w = 8  # "₹1234.5" fits in 8

        for r in range(num_rows):
            rp = row_prices[r]
            price_label = f"₹{rp:<7.1f}"

            # Row content from grid
            if r == level_row:
                # Level line — draw ═══ across, overlaying arrows
                row_content = ""
                for col_idx in range(touch_count):
                    cell = grid[r][col_idx].strip()
                    if cell:
                        row_content += f"══{cell}═"
                    else:
                        row_content += "══════"
                # Trim to consistent width and add label
                suffix = f" {level_type} ₹{level_price:.0f}"
                row_line = f"    {price_label}┤{row_content}{suffix}"
            else:
                row_content = ""
                for col_idx in range(touch_count):
                    cell = grid[r][col_idx].strip()
                    if cell:
                        row_content += f"  {cell}  "
                    else:
                        row_content += "      "

                # Add special markers on the right
                suffix = ""
                if r == now_row:
                    suffix = f"  ✈️ ₹{current_price:.2f} NOW"
                if r == breakout_row:
                    suffix = f"  🟢 ₹{breakout_price:.2f} BREAKOUT → Phase 5"

                row_line = f"    {price_label}┤{row_content}{suffix}"

            lines.append(row_line)

        # ── Time axis ──
        time_ticks = ""
        for tc in touch_candles:
            time_ticks += f"{tc['time']:^6}"
        axis_line = "    " + " " * price_fmt_w + "└" + "──┬───" * touch_count
        time_line = "    " + " " * (price_fmt_w + 1) + time_ticks

        lines.append(axis_line)
        lines.append(time_line)

        # ── Gap to Phase 5 ──
        gap = abs(current_price - breakout_price)
        gap_pct = gap / current_price * 100 if current_price > 0 else 0
        if level_side == 'RESISTANCE':
            gap_dir = "↑" if current_price < breakout_price else "✅ ABOVE"
        else:
            gap_dir = "↓" if current_price > breakout_price else "✅ BELOW"

        lines.append("")
        lines.append(f"    Gap to Phase 5: ₹{gap:.2f} ({gap_pct:.2f}%) {gap_dir}")

        return lines

    # ─────────────────────────────────────────────────────────────────
    # LOG 1: APPROACH HISTORY
    # ─────────────────────────────────────────────────────────────────

    def _log_pvat_approach(self, symbol: str, data: 'PVATStockData',
                           nearest_dist: float, nearest_type: str,
                           nearest_price: float):
        """
        LOG 1: Approach history with ASCII touch chart.
        v5.4.3: Uses rejection evidence for confirmed touch/bounce counts.
        """
        candles = self._candle_cache_15m.get(symbol, [])

        # v5.4.3: Use rejection evidence from proven_levels when available
        level_ev = None
        for lv in self._key_levels.get(symbol, {}).get('proven_levels', []):
            if abs(lv['price'] - nearest_price) / max(nearest_price, 1) < 0.003:
                level_ev = lv
                break

        if level_ev:
            rejections = level_ev.get('rejections', [])
            touch_count = len(rejections)
            bounces = [r['bounce_pct'] for r in rejections]
            confluence_days = level_ev.get('confluence_days', 0)
            merged_types = level_ev.get('merged_types', [])
        else:
            # Fallback: old counting logic
            touch_count = 0
            bounces = []
            for c in candles[-20:]:
                if abs(c.get('high', 0) - nearest_price) / max(nearest_price, 1) < 0.003 or \
                   abs(c.get('low', 0) - nearest_price) / max(nearest_price, 1) < 0.003:
                    touch_count += 1
                    bounce = abs(c.get('close', 0) - nearest_price) / max(nearest_price, 1) * 100
                    bounces.append(bounce)
            confluence_days = 0
            merged_types = []

        avg_bounce = sum(bounces) / len(bounces) if bounces else 0

        vol_declining = '📉' if data.volume_declining else '📈'

        logger.info("")
        logger.info(f"🛬 PVAT APPROACH: {symbol} → {nearest_type.upper()} @ ₹{nearest_price:.2f}")
        logger.info("─" * 75)
        logger.info(f"    ✈️ Current: ₹{data.last_price:.2f} | Distance: {nearest_dist:.2f}%")
        logger.info(f"    📊 Confirmed rejections: {touch_count} | Avg bounce: {avg_bounce:.2f}% | Confluence: {confluence_days}d")
        if merged_types and len(merged_types) > 1:
            logger.info(f"    🔗 Merged level types: {', '.join(t.upper() for t in merged_types)}")
        logger.info(f"    {vol_declining} Volume trend: {'Declining (good for acceptance)' if data.volume_declining else 'Rising (watching)'}")
        logger.info(f"    🏅 Level score: {data.tracked_level_score}/100")
        logger.info("")

        # ASCII touch chart
        chart_lines = self._build_touch_chart(
            symbol, nearest_price, nearest_type.upper(),
            data.tracked_level_side, data.last_price
        )
        for line in chart_lines:
            logger.info(line)

        logger.info("")

    # ─────────────────────────────────────────────────────────────────
    # LOG 1B: ACCEPTANCE DETAIL (v2.1 — Fix C)
    # ─────────────────────────────────────────────────────────────────

    def _log_pvat_acceptance_detail(self, symbol: str, data: 'PVATStockData',
                                     tracked_dist: float):
        """
        LOG 1B: Acceptance detail block with ASCII touch chart.
        v5.4.3: Uses rejection evidence for confirmed touch/bounce counts.
        """
        candles = self._candle_cache_15m.get(symbol, [])

        # v5.4.3: Use rejection evidence from proven_levels when available
        level_ev = None
        for lv in self._key_levels.get(symbol, {}).get('proven_levels', []):
            if abs(lv['price'] - data.tracked_level_price) / max(data.tracked_level_price, 1) < 0.003:
                level_ev = lv
                break

        if level_ev:
            rejections = level_ev.get('rejections', [])
            touch_count = len(rejections)
            bounces = [r['bounce_pct'] for r in rejections]
            confluence_days = level_ev.get('confluence_days', 0)
        else:
            # Fallback: old counting logic
            touch_count = 0
            bounces = []
            for c in candles[-20:]:
                if abs(c.get('high', 0) - data.tracked_level_price) / max(data.tracked_level_price, 1) < 0.003 or \
                   abs(c.get('low', 0) - data.tracked_level_price) / max(data.tracked_level_price, 1) < 0.003:
                    touch_count += 1
                    bounce = abs(c.get('close', 0) - data.tracked_level_price) / max(data.tracked_level_price, 1) * 100
                    bounces.append(bounce)
            confluence_days = 0

        avg_bounce = sum(bounces) / len(bounces) if bounces else 0

        # Time in approach
        approach_duration = ""
        if data.approach_time:
            elapsed = datetime.now() - data.approach_time
            mins = int(elapsed.total_seconds() / 60)
            approach_duration = f"{mins}m"
        else:
            approach_duration = "?"

        # Volume info
        vol_str = "init"
        if data.candle_volume > 0:
            vol_str = f"₹{data.candle_volume:,.0f}/candle"

        # Min candles needed
        min_candles = getattr(self.config, 'PVAT_ACCEPTANCE_MIN_CANDLES', 3)
        orbits = '⚪' * min_candles
        candles_eta = min_candles * 15  # minutes

        logger.info("")
        logger.info(f"🎯 PVAT ACCEPTANCE: {symbol} → {data.tracked_level_type} @ ₹{data.tracked_level_price:.2f}")
        logger.info("─" * 75)
        logger.info(f"    ✈️ Price: ₹{data.last_price:.2f} | Distance: {tracked_dist:.2f}%")
        logger.info(f"    📐 Zone: ₹{data.acceptance_zone_low:.2f} — ₹{data.acceptance_zone_high:.2f}")
        logger.info(f"    ⏱️  Approach dwell: {approach_duration} ({data.approach_candle_count} candle{'s' if data.approach_candle_count != 1 else ''})")
        logger.info(f"    📊 Confirmed rejections: {touch_count} | Avg bounce: {avg_bounce:.2f}% | Confluence: {confluence_days}d")
        logger.info(f"    📈 Volume at acceptance: {vol_str}")
        logger.info(f"    🏅 Level score: {data.tracked_level_score}/100")
        logger.info(f"    🔄 Orbits needed: {orbits} ({min_candles} candles ≈ {candles_eta}m)")
        logger.info("")

        # ASCII touch chart
        chart_lines = self._build_touch_chart(
            symbol, data.tracked_level_price, data.tracked_level_type,
            data.tracked_level_side, data.last_price
        )
        for line in chart_lines:
            logger.info(line)

        logger.info("")

    # ─────────────────────────────────────────────────────────────────
    # LOG 2: ACCEPTANCE STATUS TABLE (compact batch view)
    # ─────────────────────────────────────────────────────────────────

    # Level type abbreviations for compact table display
    _LEVEL_ABBREV = {
        'MULTI_DAY_HIGH': 'MDH', 'MULTI_DAY_LOW': 'MDL',
        'IB_HIGH': 'IBH', 'IB_LOW': 'IBL',
        'PDH': 'PDH', 'PDL': 'PDL', 'POC': 'POC',
    }

    def _log_pvat_acceptance_table(self):
        """
        LOG 2: Compact acceptance table — replaces per-stock verbose blocks.
        Shows all ACCEPTANCE stocks in one table, sorted by distance (closest first).
        """
        min_candles = getattr(self.config, 'PVAT_ACCEPTANCE_MIN_CANDLES', 3)

        # Collect acceptance stocks
        rows = []
        for sym, data in self._stock_states.items():
            if data.state != PVATState.ACCEPTANCE:
                continue
            dist = abs(data.last_price - data.tracked_level_price) / max(data.tracked_level_price, 1) * 100
            candles_done = data.acceptance_candle_count
            candles_left = max(0, min_candles - candles_done)
            orbits = '🟢' * min(candles_done, min_candles) + '⚪' * candles_left
            if candles_done >= min_candles:
                status = '✅ READY'
            else:
                status = f'Need {candles_left}'

            # Volume emoji
            if data.candle_volume > 0 and data.volume_at_acceptance_start > 0:
                vol_ratio = data.candle_volume / data.volume_at_acceptance_start
                vol_str = f"{'📉' if vol_ratio < 0.8 else '📊'}{vol_ratio:.0%}"
            else:
                vol_str = '⚪ init'

            level_abbrev = self._LEVEL_ABBREV.get(
                data.tracked_level_type, data.tracked_level_type[:6]
            )

            rows.append((dist, sym, level_abbrev, data.last_price,
                         data.tracked_level_price, dist, orbits, vol_str, status))

        if not rows:
            return  # No acceptance stocks — nothing to log

        # Sort by distance (closest to breakout first)
        rows.sort(key=lambda r: r[0])

        logger.info("")
        logger.info(f"✈️ PVAT ACCEPTANCE STATUS ({len(rows)} stock{'s' if len(rows) != 1 else ''})")
        logger.info("─" * 78)
        logger.info(f" {'Stock':<12}| {'Level':<6}| {'Price':>10} | {'Dist':>5} | {'Orbits':<10}| {'Vol':<8}| Status")
        logger.info("─" * 78)
        for _, sym, level, price, level_price, dist, orbits, vol, status in rows:
            logger.info(
                f" {sym:<12}| {level:<6}| ₹{price:>8.2f} | {dist:>4.2f}% | {orbits:<10}| {vol:<8}| {status}"
            )
        logger.info("─" * 78)

    # ─────────────────────────────────────────────────────────────────
    # LOG 6: MISSION COMPLETE / FAILED
    # ─────────────────────────────────────────────────────────────────

    def _log_pvat_mission_complete(self, symbol: str, signal: Dict, trade):
        """DEPRECATED v5.4.2: Use _log_pvat_mission_complete_v2 instead."""
        level_type = signal.get('level_type', '?')
        level_price = signal.get('level_price', 0)
        entry_price = getattr(trade, 'entry_price', 0)
        acc_candles = signal.get('acceptance_candle_count', 0)

        logger.info("")
        logger.info(f"✅ PVAT DONE: {symbol} | {level_type} @ ₹{level_price:.2f} | "
                     f"Entry ₹{entry_price:.2f} | {acc_candles} candles | "
                     f"✈️ Phase 5A → Phase 4 TIER_1")
        logger.info("")

    def _log_pvat_mission_failed(self, symbol: str, signal: Dict, reason: str):
        """LOG 6: Mission failed — PVAT breakout rejected by pipeline."""
        level_type = signal.get('level_type', '?')
        acc_candles = signal.get('acceptance_candle_count', 0)

        logger.info("")
        logger.info(f"🔴 PVAT CLOSED: {symbol} | {level_type} | "
                     f"{acc_candles} candles | Reason: {reason}")
        logger.info("")

    # ─────────────────────────────────────────────────────────────────
    # SCAN STATUS VISUALIZATION
    # ─────────────────────────────────────────────────────────────────

    def get_scan_status_visual(self) -> str:
        """
        Generate scan status dashboard for Telegram or logs.
        Shows all tracked stocks and their PVAT state.
        """
        lines = []
        lines.append("PVAT SCANNER STATUS")
        lines.append("=" * 40)

        state_emoji = {
            PVATState.IDLE: '⚪',
            PVATState.APPROACH: '✈️',
            PVATState.ACCEPTANCE: '➡️',
            PVATState.BREAKOUT_CONFIRMED: '🎯',
            PVATState.TRADED: '✅',
            PVATState.REJECTED: '↘️',
        }

        for sym, data in sorted(self._stock_states.items(),
                                key=lambda x: x[1].state.value):
            emoji = state_emoji.get(data.state, '?')
            level_info = ""
            if data.tracked_level_price > 0:
                dist = abs(data.last_price - data.tracked_level_price) / data.tracked_level_price * 100
                level_info = (
                    f" {data.tracked_level_type} "
                    f"{data.tracked_level_price:.0f} "
                    f"({dist:.1f}%)"
                )
                if data.state == PVATState.ACCEPTANCE:
                    level_info += f" [{data.acceptance_candle_count} candles]"

            lines.append(f"  [{emoji}] {sym:12s} @ {data.last_price:>8.2f}{level_info}")

        counts = self._count_states()
        lines.append("")
        lines.append(
            f"  Total: {len(self._stock_states)} | "
            f"Approach: {counts.get('APPROACH', 0)} | "
            f"Accept: {counts.get('ACCEPTANCE', 0)} | "
            f"Fired: {'YES' if self._trade_fired else 'NO'}"
        )

        return '\n'.join(lines)

    # ─────────────────────────────────────────────────────────────────
    # HELPERS
    # ─────────────────────────────────────────────────────────────────

    def _count_states(self) -> Dict[str, int]:
        """Count stocks in each PVAT state."""
        counts = {}
        for data in self._stock_states.values():
            name = data.state.name
            counts[name] = counts.get(name, 0) + 1
        return counts

    def _write_radar_state(self):
        """v5.7.0: Write live scanner state to JSON for GUI data bridge."""
        try:
            state_counts = self._count_states()
            mode, closest_dist, closest_sym = self._determine_scan_mode()
            now = datetime.now()

            # Build approaching stocks list (APPROACH + ACCEPTANCE)
            approaching = []
            for symbol, data in self._stock_states.items():
                if data.state not in (PVATState.APPROACH, PVATState.ACCEPTANCE):
                    continue
                if data.last_price <= 0 or data.tracked_level_price <= 0:
                    continue

                dist_pct = abs(data.last_price - data.tracked_level_price) / data.tracked_level_price * 100
                direction = 'LONG' if data.tracked_level_side == 'RESISTANCE' else 'SHORT'

                # Gate number: APPROACH=2, ACCEPTANCE=3
                gate = 2 if data.state == PVATState.APPROACH else 3

                # ETA estimate based on distance and scan interval
                scan_sec = getattr(self.config, 'PVAT_SCAN_INTERVAL_NORMAL', 30)
                eta_scans = max(1, int(dist_pct / 0.1)) if dist_pct > 0 else 1
                eta_min = max(1, (eta_scans * scan_sec) // 60)

                approaching.append({
                    'symbol': symbol,
                    'level': round(data.tracked_level_price, 1),
                    'level_type': data.tracked_level_type,
                    'side': data.tracked_level_side,
                    'direction': direction,
                    'price': round(data.last_price, 1),
                    'distance_pct': round(dist_pct, 2),
                    'gate': gate,
                    'eta': f"~{eta_min} min",
                    'score': data.tracked_level_score,
                    'rejections': data.tracked_level_rejections,
                    'confluence': data.tracked_level_confluence_days,
                    'acceptance_candles': data.acceptance_candle_count,
                    'state': data.state.name,
                })

            # Sort by distance (closest first)
            approaching.sort(key=lambda x: x['distance_pct'])

            # Build gate counts: levels → approach → acceptance → breakout
            total_levels = sum(len(v.get('proven_levels', [])) for v in self._key_levels.values())
            gate_data = {
                'Gate 1': total_levels,
                'Gate 2': state_counts.get('APPROACH', 0) + state_counts.get('ACCEPTANCE', 0),
                'Gate 3': state_counts.get('ACCEPTANCE', 0),
                'Gate 4': state_counts.get('BREAKOUT_CONFIRMED', 0) + state_counts.get('TRADED', 0),
            }

            # Sniper pipeline status
            pipeline_stocks = []
            for stock in self.sniper_pipeline:
                pipeline_stocks.append({
                    'symbol': stock.symbol,
                    'direction': 'LONG' if stock.tracked_level_side == 'RESISTANCE' else 'SHORT',
                    'level': round(stock.tracked_level_price, 1),
                    'level_type': stock.tracked_level_type,
                    'score': getattr(stock, '_elite_score', 0),
                    'triggered': getattr(stock, 'triggered', False),
                    'entry_price': getattr(stock, 'entry_price', 0),
                    'stop_price': getattr(stock, 'stop_price', 0),
                    'target_price': getattr(stock, 'target_price', 0),
                    'exited': getattr(stock, 'exited', False),
                    'exit_reason': getattr(stock, 'exit_reason', ''),
                })

            # Traded/rejected summary
            traded = [s for s, d in self._stock_states.items() if d.state == PVATState.TRADED]
            rejected = [s for s, d in self._stock_states.items() if d.state == PVATState.REJECTED]

            radar_state = {
                'timestamp': now.isoformat(),
                'scan_mode': mode,
                'scan_interval_sec': getattr(self.config, f'PVAT_SCAN_INTERVAL_{mode}',
                                             getattr(self.config, 'PVAT_SCAN_INTERVAL_NORMAL', 30)),
                'scan_count': self._scan_count,
                'levels_found': total_levels,
                'closest_distance_pct': round(closest_dist, 2) if closest_dist < 999 else None,
                'closest_symbol': closest_sym,
                'gates': gate_data,
                'gate_max': max(total_levels, 10),
                'approaching': approaching[:8],  # Top 8 closest
                'state_counts': state_counts,
                'pipeline': pipeline_stocks,
                'traded': traded,
                'rejected': rejected,
                'trade_fired': self._trade_fired,
                'ph5a_done': self.ph5a_done,
                'recent_events': list(self._recent_events),
                'total_tracked': len(self._stock_states),
            }

            os.makedirs('data', exist_ok=True)
            state_path = os.path.join('data', 'ph5a_radar_state.json')
            tmp_path = state_path + '.tmp'
            with open(tmp_path, 'w') as f:
                json.dump(radar_state, f, indent=2, default=str)
            os.replace(tmp_path, state_path)

        except Exception as e:
            logger.debug(f"PVAT radar state write error: {e}")

    def _notify_pvat_entry(self, signal: Dict, trade):
        """DEPRECATED v5.4.2: Telegram notification now in _execute_pvat_pipeline."""
        try:
            if self.telegram:
                direction = signal.get('direction', '?')
                dir_emoji = '✈️ LONG' if direction == 'LONG' else '↘️ SHORT'
                vol_declining = signal.get('volume_declining', False)
                msg = (
                    f"🔷 PVAT BREAKOUT ENTRY\n\n"
                    f"Stock: {signal['symbol']}\n"
                    f"Direction: {dir_emoji}\n"
                    f"Level: {signal['level_type']} @ "
                    f"₹{signal['level_price']:.2f}\n"
                    f"Entry: ₹{signal['breakout_price']:.2f}\n"
                    f"Acceptance: {signal['acceptance_candle_count']} candles "
                    f"({'vol declining' if vol_declining else 'vol active'})\n"
                    f"Vol Ratio: {signal['breakout_volume_ratio']:.1f}x\n\n"
                    f"✈️ Phase 5A → Phase 4 TIER_1 (independent)"
                )
                self.telegram.send_message(msg)
        except Exception as e:
            logger.debug(f"PVAT Telegram notification error: {e}")

    def _notify_pvat_scan_summary(self, state_counts: Dict[str, int]):
        """Telegram: ONE consolidated status message per 15-min scan burst."""
        try:
            if not self.telegram:
                return
            min_candles = getattr(self.config, 'PVAT_ACCEPTANCE_MIN_CANDLES', 3)

            # ── Acceptance rows (sorted by distance) ──
            acc_rows = []
            for sym, data in self._stock_states.items():
                if data.state != PVATState.ACCEPTANCE:
                    continue
                dist = abs(data.last_price - data.tracked_level_price) / max(data.tracked_level_price, 1) * 100
                candles_done = data.acceptance_candle_count
                candles_left = max(0, min_candles - candles_done)
                orbits = '🟢' * min(candles_done, min_candles) + '⚪' * candles_left
                if candles_done >= min_candles:
                    orbits += '✅'
                level_abbrev = self._LEVEL_ABBREV.get(
                    data.tracked_level_type, data.tracked_level_type[:6]
                )
                acc_rows.append((dist, f"{sym} {level_abbrev} ₹{data.last_price:.0f} {orbits}"))
            acc_rows.sort(key=lambda r: r[0])

            # ── Approach rows (top 5 closest) ──
            app_rows = []
            for sym, data in self._stock_states.items():
                if data.state != PVATState.APPROACH:
                    continue
                if data.tracked_level_price <= 0:
                    continue
                dist = abs(data.last_price - data.tracked_level_price) / max(data.tracked_level_price, 1) * 100
                level_abbrev = self._LEVEL_ABBREV.get(
                    data.tracked_level_type, data.tracked_level_type[:6]
                )
                app_rows.append((dist, f"{sym} {level_abbrev} ₹{data.last_price:.0f} ({dist:.1f}%)"))
            app_rows.sort(key=lambda r: r[0])

            # ── Build message ──
            now_str = datetime.now().strftime('%H:%M')
            n_accept = state_counts.get('ACCEPTANCE', 0)
            n_approach = state_counts.get('APPROACH', 0)

            msg_parts = [
                f"📡 <b>PVAT @ {now_str}</b>",
                f"Tracked: {len(self._stock_states)} | "
                f"Accept: {n_accept} | Approach: {n_approach}",
            ]

            if acc_rows:
                header = ["Symbol","Direction","Entry","Target","Stop","Score","Status"]
                rows   = [header] + acc_rows
                self._send_telegram_table("PVAT Scan Summary", rows)
        except Exception as e:
            logger.error(f"_notify_pvat_scan_summary error: {e}")
