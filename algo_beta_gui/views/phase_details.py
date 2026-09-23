"""
Algo_Beta GUI -- Phase Detail Views (Aviation Themed)
=====================================================
Sub-views inside Dashboard tab for detailed phase information.
Aviation theme: gauges, instrument panels, flight data recorder styling.
ALL DATA IS MOCK -- wired to real data later.
"""

import customtkinter as ctk
import tkinter as tk
import math
import os
import json
import datetime
import sys

import matplotlib
matplotlib.use("TkAgg")
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import numpy as np

import pygame
import pygame.gfxdraw
from PIL import Image as PILImage

try:
    # prediction_store.py lives in algo_beta_gui/ (parent of views/)
    _parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if _parent_dir not in sys.path:
        sys.path.insert(0, _parent_dir)
    from prediction_store import PredictionStore
except ImportError:
    PredictionStore = None

# Ensemble prediction engine (lives in Algo_Beta/ project root)
try:
    _project_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if _project_dir not in sys.path:
        sys.path.insert(0, _project_dir)
    from prediction_engine import EnsemblePrediction, PredictionResult
    ENSEMBLE_AVAILABLE = True
except ImportError:
    ENSEMBLE_AVAILABLE = False


import sys as _sys
_sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from theme import (  # noqa: E402
    BG_APP, BG_PANEL, BG_HEADER, BG_INPUT,
    BORDER, BORDER_DIM,
    TEXT_PRIMARY, TEXT_LABEL, TEXT_MUTED, TEXT_DIM,
    GREEN, AMBER, RED, CYAN, WHITE, ACCENT_CYAN,
    ZONE_COLORS,
    SKY_BLUE, SKY_BLUE_LT, GROUND_BROWN, GROUND_DARK,
    HORIZON_LINE, AIRCRAFT_REF, BB_UPPER, BB_LOWER, BB_MIDDLE,
    FONT_FAMILY, FONT_TITLE, FONT_HEADING, FONT_BODY_BOLD, FONT_BODY,
    FONT_SMALL_BOLD, FONT_SMALL, FONT_TINY_BOLD, FONT_TINY,
)


# ==========================================================================
#  MOCK DATA
# ==========================================================================

PH5_MOCK = {
    "source": "mock",
    "status": "WINDOW CLOSED",
    "window_start": "09:15",
    "window_end": "09:50",
    "scan_window": "09:18 -- 09:20",
    "entry_window": "09:20 -- 09:25",
    "next_run": "Tomorrow 09:15 AM",
    "candidates_today": 3,
    "universe_size": 147,
    "trades_today_count": 1,
    "pnl_today": 14.2,
    "mission_log": [
        ("09:15", "Scan started -- 147 stocks", "info"),
        ("09:17", "Gap detected: SBIN -2.3%", "phase"),
        ("09:19", "ATR target: Rs.782 -> Rs.798", "info"),
        ("09:22", "Entry: SBIN @ Rs.784", "success"),
        ("09:35", "Target hit: +1.8%", "success"),
        ("09:50", "Window closed", "warning"),
    ],
    "today_trades": [
        {"symbol": "SBIN", "direction": "BUY", "entry_price": 784, "entry_time": "09:22",
         "entry_qty": 12, "exit_price": 798, "exit_time": "09:35",
         "pnl_net": 14.2, "hold_duration_min": 13, "exit_reason": "Target hit"},
    ],
    "config": {
        "gap_p1": 1.5, "gap_p2": 1.0, "gap_p3": 0.75,
        "min_volume_ratio": 1.0, "max_adx": 25,
        "min_price": 800, "max_price": 3000,
        "max_trades_day": 1, "pos_size_pct": 5.0,
        "min_pos_value": 5000, "max_pos_value": 10000,
    },
    "historical_trades": [
        {"date": "2026-03-07", "symbol": "SBIN", "direction": "BUY",
         "entry_price": 784, "exit_price": 798, "pnl_net": 14.2,
         "hold_duration_min": 13, "max_favorable": 16.8, "max_adverse": -3.1,
         "exit_reason": "Target hit"},
        {"date": "2026-03-06", "symbol": "TATAMOTORS", "direction": "BUY",
         "entry_price": 652, "exit_price": 645, "pnl_net": -8.4,
         "hold_duration_min": 23, "max_favorable": 4.2, "max_adverse": -9.8,
         "exit_reason": "Stop hit"},
        {"date": "2026-03-05", "symbol": "RELIANCE", "direction": "SELL",
         "entry_price": 2410, "exit_price": 2385, "pnl_net": 12.5,
         "hold_duration_min": 18, "max_favorable": 28.0, "max_adverse": -5.0,
         "exit_reason": "Target hit"},
        {"date": "2026-03-04", "symbol": "HDFCBANK", "direction": "BUY",
         "entry_price": 1680, "exit_price": 1695, "pnl_net": 9.0,
         "hold_duration_min": 15, "max_favorable": 18.0, "max_adverse": -2.5,
         "exit_reason": "Target hit"},
        {"date": "2026-03-03", "symbol": "ICICIBANK", "direction": "BUY",
         "entry_price": 1120, "exit_price": 1108, "pnl_net": -10.8,
         "hold_duration_min": 25, "max_favorable": 3.5, "max_adverse": -14.0,
         "exit_reason": "Mandatory exit"},
        {"date": "2026-02-28", "symbol": "INFY", "direction": "SELL",
         "entry_price": 1545, "exit_price": 1528, "pnl_net": 11.0,
         "hold_duration_min": 12, "max_favorable": 19.0, "max_adverse": -1.8,
         "exit_reason": "Target hit"},
    ],
    "performance": {
        "total_trades": 23, "wins": 16, "losses": 7,
        "win_rate": 69.6, "avg_pnl": 6.8, "avg_duration_min": 17,
        "profit_factor": 2.3, "avg_win": 12.4, "avg_loss": 8.7,
        "total_pnl": 156.4,
    },
    "daily_pnl_series": [
        {"date": "2026-02-24", "ph5_pnl": 14.2},
        {"date": "2026-02-25", "ph5_pnl": -8.4},
        {"date": "2026-02-26", "ph5_pnl": 12.5},
        {"date": "2026-02-27", "ph5_pnl": 9.0},
        {"date": "2026-02-28", "ph5_pnl": -10.8},
        {"date": "2026-03-03", "ph5_pnl": 11.0},
        {"date": "2026-03-04", "ph5_pnl": 15.3},
        {"date": "2026-03-05", "ph5_pnl": -6.2},
        {"date": "2026-03-06", "ph5_pnl": 18.1},
        {"date": "2026-03-07", "ph5_pnl": 14.2},
    ],
}

PH5A_MOCK = {
    "scan_mode": "WARM",
    "scan_interval_sec": 30,
    "next_scan_sec": 14,
    "scan_count": 47,
    "levels_found": 7,
    "total_tracked": 147,
    "gates": {"Gate 1": 7, "Gate 2": 3, "Gate 3": 1, "Gate 4": 0},
    "gate_max": 10,
    "state_counts": {"IDLE": 140, "APPROACH": 3, "ACCEPTANCE": 1,
                     "BREAKOUT": 0, "TRADED": 0, "REJECTED": 3},
    "approaching": [{"symbol": "SBIN", "level": 782, "gate": 3, "eta": "~2 min",
                     "direction": "LONG", "level_type": "PDH", "distance_pct": 0.19,
                     "score": 82, "rejections": 12, "confluence": 5, "state": "APPROACH"}],
    "closest_distance_pct": 0.19,
    "closest_symbol": "SBIN",
    "recent_events": [
        {"time": "09:31:15", "text": "SBIN: IDLE → APPROACH (PDH Rs.782, dist 0.19%)", "level": "info"},
        {"time": "09:30:45", "text": "HDFCBANK: rejected — sniper score 62 < 75", "level": "warn"},
        {"time": "09:30:12", "text": "ChatGPT: APPROVE SBIN (confidence 0.78)", "level": "success"},
        {"time": "09:29:30", "text": "Scan #47 complete — 147 tracked, 7 levels, 3 approaching", "level": "info"},
        {"time": "09:29:00", "text": "WARM mode: 3 stocks near levels, interval 30s", "level": "info"},
        {"time": "09:28:15", "text": "RELIANCE: APPROACH → ACCEPTANCE (3 candles)", "level": "info"},
        {"time": "09:27:30", "text": "ICICIBANK: rejected — ChatGPT REJECT (conf 0.42)", "level": "warn"},
    ],
}

EMPTY_COCKPIT = {
    "positions": [],
    "tcas_advisory": "STANDBY",
    "ils_on_track": 0,
    "ils_total": 0,
}

GLASS_COCKPIT_MOCK = {
    "positions": [
        {
            "symbol": "RAMCOCEM", "status": "ON TRACK", "trade_type": "CNC",
            "current": 905.30, "entry": 882.00,
            "velocity": 1.8, "acceleration": 0.12,
            "ils_target": 915.00, "tcas_floor": 878.20,
            "eta_minutes": 22, "pitch": 12, "bank": 8,
            "ema_20": 895, "ema_50": 880,
            "rsi": 58, "atr_14": 8.5, "adx": 28,
            "volume_ratio": 1.8, "vol_expected": 1.5, "vol_burst": "BUY",
            "macd_hist": 1.2, "stoch_k": 65,
            "pnl_pct": 2.64, "pnl_abs": 1165,
            "plan": {
                "target": 915, "stop_loss": 870, "rr": 2.5, "pnl_target": 3.8,
                "entry_rsi": 42, "entry_atr": 8.2, "entry_vol": 1.5,
            },
            "pdh": 912, "pdl": 875,
            "levels_intraday": {
                "sup": 890, "res": 920,
                "fib236": 889.8, "fib382": 894.6, "fib50": 898.5, "fib618": 902.4, "fib786": 907.6,
                "ma20": 896, "ma50": 882, "bbU": 928, "bbM": 895, "bbL": 862,
            },
            "levels_daily": {
                "sup": 875, "res": 935,
                "fib236": 882.5, "fib382": 891, "fib50": 898, "fib618": 905, "fib786": 915,
                "ma20": 890, "ma50": 870, "bbU": 940, "bbM": 892, "bbL": 845,
            },
            "bb_upper": 928, "bb_lower": 862, "bb_middle": 895,
            "support": 890, "resistance": 920,
            "entry_time": "09:22", "current_time": "10:22",
            "history": [
                {"t": 0, "p": 882}, {"t": 5, "p": 884}, {"t": 8, "p": 883.5}, {"t": 10, "p": 885.5},
                {"t": 15, "p": 888}, {"t": 18, "p": 887}, {"t": 20, "p": 890}, {"t": 25, "p": 893},
                {"t": 28, "p": 891.5}, {"t": 30, "p": 895}, {"t": 35, "p": 897}, {"t": 38, "p": 896},
                {"t": 40, "p": 898}, {"t": 45, "p": 900}, {"t": 48, "p": 899}, {"t": 50, "p": 902},
                {"t": 55, "p": 903.5}, {"t": 58, "p": 904}, {"t": 60, "p": 905.3},
            ],
            "hourly_candles": [
                {"time": "09:15", "p": 882}, {"time": "10:00", "p": 890.5},
                {"time": "11:00", "p": 896.2}, {"time": "12:00", "p": 898.8},
                {"time": "13:00", "p": 901.4}, {"time": "14:00", "p": 905.3},
            ],
            "daily_closes": [
                {"date": "Mon 03", "p": 865}, {"date": "Tue 04", "p": 872.5},
                {"date": "Wed 05", "p": 878}, {"date": "Thu 06", "p": 876.5},
                {"date": "Fri 07", "p": 882}, {"date": "Mon 10", "p": 905.3},
            ],
            "kalman_hourly": {"velocity": 3.8, "acceleration": 0.2},
            "kalman_daily": {"velocity": 5.5, "acceleration": -0.3},
            "ai": {"action": "HOLD", "conf": 74, "msg": "V-Recovery intact. Kalman +1.8/m. ILS Rs.915 valid.", "review": 15},
        },
        {
            "symbol": "HDFCBANK", "status": "MONITOR", "trade_type": "CNC",
            "current": 1432.50, "entry": 1445.00,
            "velocity": -0.4, "acceleration": -0.08,
            "ils_target": 1480.00, "tcas_floor": 1420.00,
            "eta_minutes": None, "pitch": -5, "bank": -3,
            "ema_20": 1442, "ema_50": 1450,
            "rsi": 42, "atr_14": 12, "adx": 18,
            "volume_ratio": 0.9, "vol_expected": 1.3, "vol_burst": "SELL",
            "macd_hist": -0.8, "stoch_k": 32,
            "pnl_pct": -0.87, "pnl_abs": -312,
            "plan": {
                "target": 1480, "stop_loss": 1430, "rr": 2.3, "pnl_target": 2.4,
                "entry_rsi": 38, "entry_atr": 11, "entry_vol": 1.3,
            },
            "pdh": 1458, "pdl": 1428,
            "levels_intraday": {
                "sup": 1425, "res": 1460,
                "fib236": 1437.3, "fib382": 1441.4, "fib50": 1445, "fib618": 1448.6, "fib786": 1453.5,
                "ma20": 1440, "ma50": 1448, "bbU": 1475, "bbM": 1442, "bbL": 1410,
            },
            "levels_daily": {
                "sup": 1405, "res": 1470,
                "fib236": 1430, "fib382": 1438, "fib50": 1445, "fib618": 1452, "fib786": 1462,
                "ma20": 1435, "ma50": 1455, "bbU": 1490, "bbM": 1440, "bbL": 1390,
            },
            "bb_upper": 1475, "bb_lower": 1410, "bb_middle": 1442,
            "support": 1425, "resistance": 1460,
            "entry_time": "09:30", "current_time": "10:20",
            "history": [
                {"t": 0, "p": 1445}, {"t": 5, "p": 1444}, {"t": 10, "p": 1443}, {"t": 12, "p": 1444},
                {"t": 15, "p": 1441}, {"t": 20, "p": 1440}, {"t": 25, "p": 1438}, {"t": 28, "p": 1439},
                {"t": 30, "p": 1436}, {"t": 35, "p": 1435}, {"t": 40, "p": 1434}, {"t": 45, "p": 1433},
                {"t": 50, "p": 1432.5},
            ],
            "hourly_candles": [
                {"time": "09:30", "p": 1445}, {"time": "10:00", "p": 1442},
                {"time": "11:00", "p": 1438.5}, {"time": "12:00", "p": 1436},
                {"time": "13:00", "p": 1434.2}, {"time": "14:00", "p": 1432.5},
            ],
            "daily_closes": [
                {"date": "Mon 03", "p": 1462}, {"date": "Tue 04", "p": 1458.5},
                {"date": "Wed 05", "p": 1455}, {"date": "Thu 06", "p": 1450},
                {"date": "Fri 07", "p": 1445}, {"date": "Mon 10", "p": 1432.5},
            ],
            "kalman_hourly": {"velocity": -2.5, "acceleration": -0.1},
            "kalman_daily": {"velocity": -4.2, "acceleration": -0.5},
            "ai": {"action": "CAUTION", "conf": 52, "msg": "Below EMA-20. Vel -0.4/m. TCAS Rs.1420 0.9% away.", "review": 5},
        },
        {
            "symbol": "RELIANCE", "status": "ON TRACK", "trade_type": "CNC",
            "current": 2417.00, "entry": 2380.00,
            "velocity": 1.2, "acceleration": 0.05,
            "ils_target": 2450.00, "tcas_floor": 2360.00,
            "eta_minutes": 35, "pitch": 8, "bank": 5,
            "ema_20": 2410, "ema_50": 2395,
            "rsi": 55, "atr_14": 18, "adx": 24,
            "volume_ratio": 1.4, "vol_expected": 1.2, "vol_burst": "BUY",
            "macd_hist": 0.6, "stoch_k": 58,
            "pnl_pct": 1.55, "pnl_abs": 555,
            "plan": {
                "target": 2450, "stop_loss": 2355, "rr": 2.8, "pnl_target": 2.94,
                "entry_rsi": 45, "entry_atr": 16, "entry_vol": 1.2,
            },
            "pdh": 2445, "pdl": 2388,
            "levels_intraday": {
                "sup": 2400, "res": 2460,
                "fib236": 2396.5, "fib382": 2406.7, "fib50": 2415, "fib618": 2423.3, "fib786": 2435,
                "ma20": 2412, "ma50": 2398, "bbU": 2465, "bbM": 2420, "bbL": 2375,
            },
            "levels_daily": {
                "sup": 2370, "res": 2480,
                "fib236": 2388, "fib382": 2400, "fib50": 2410, "fib618": 2420, "fib786": 2438,
                "ma20": 2405, "ma50": 2380, "bbU": 2490, "bbM": 2415, "bbL": 2340,
            },
            "bb_upper": 2465, "bb_lower": 2375, "bb_middle": 2420,
            "support": 2400, "resistance": 2460,
            "entry_time": "09:25", "current_time": "10:10",
            "history": [
                {"t": 0, "p": 2380}, {"t": 5, "p": 2383}, {"t": 10, "p": 2387}, {"t": 12, "p": 2385},
                {"t": 15, "p": 2392}, {"t": 20, "p": 2396}, {"t": 25, "p": 2400}, {"t": 28, "p": 2398},
                {"t": 30, "p": 2404}, {"t": 35, "p": 2408}, {"t": 40, "p": 2412}, {"t": 45, "p": 2417},
            ],
            "hourly_candles": [
                {"time": "09:25", "p": 2380}, {"time": "10:00", "p": 2396},
                {"time": "11:00", "p": 2408}, {"time": "12:00", "p": 2412},
            ],
            "daily_closes": [
                {"date": "Mon 03", "p": 2365}, {"date": "Tue 04", "p": 2372},
                {"date": "Wed 05", "p": 2380}, {"date": "Thu 06", "p": 2385},
                {"date": "Fri 07", "p": 2380}, {"date": "Mon 10", "p": 2417},
            ],
            "kalman_hourly": {"velocity": 4.2, "acceleration": 0.1},
            "kalman_daily": {"velocity": 7.4, "acceleration": 0.8},
            "ai": {"action": "HOLD", "conf": 81, "msg": "Trend intact. Approaching ILS Rs.2450. Partial exit at Rs.2440.", "review": 20},
        },
    ],
    "tcas_advisory": "ALL CLEAR",
    "ils_on_track": 2,
    "ils_total": 3,
}

# -- Timeframe configuration --
TIMEFRAME_CONFIG = {
    "15m":  {"x_range": 15,   "prediction": 5,   "grid_step": 1,   "x_label": "minutes", "cone_factor": 0.10, "kalman_scale": "intraday", "min_pred_pct": 0.25},
    "30m":  {"x_range": 30,   "prediction": 10,  "grid_step": 5,   "x_label": "minutes", "cone_factor": 0.12, "kalman_scale": "intraday", "min_pred_pct": 0.25},
    "1hr":  {"x_range": 60,   "prediction": 20,  "grid_step": 10,  "x_label": "clock",   "cone_factor": 0.15, "kalman_scale": "intraday", "min_pred_pct": 0.25},
    "2hr":  {"x_range": 120,  "prediction": 30,  "grid_step": 15,  "x_label": "clock",   "cone_factor": 0.18, "kalman_scale": "intraday", "min_pred_pct": 0.20},
    "Day":  {"x_range": 375,  "prediction": 45,  "grid_step": 60,  "x_label": "clock",   "cone_factor": 0.20, "kalman_scale": "intraday", "min_pred_pct": 0.15},
    "Tmrw": {"x_range": 750,  "prediction": 375, "grid_step": 375, "x_label": "days",    "cone_factor": 0.25, "kalman_scale": "hourly",   "min_pred_pct": 0.15},
    "3D":   {"x_range": 1125, "prediction": 1125, "grid_step": 375, "x_label": "days",    "cone_factor": 0.30, "kalman_scale": "daily",    "min_pred_pct": 0.25},
    "1W":   {"x_range": 1875, "prediction": 1875,"grid_step": 375, "x_label": "days",    "cone_factor": 0.35, "kalman_scale": "daily",    "min_pred_pct": 0.20},
}
MINS_PER_TDAY = 375   # minutes in one trading day (9:15–15:30)
MINS_PER_HOUR = 60
TIMEFRAME_LIST = ["15m", "30m", "1hr", "2hr", "Day", "Tmrw", "3D", "1W"]
TRADE_TYPE_DEFAULTS = {"CNC": "1hr", "PH5_GAP": "15m", "PH5A_MIS": "15m", "PH7_MCX": "30m", "PH8_MOMENTUM": "30m"}
PURPLE = "#a855f7"
PINK = "#f472b6"
PREDICTED = "#4ade80"
HISTORY_PRED = "#f59e0b"   # amber for old prediction overlay

# -- Dynamic Y-axis grid helpers ------------------------------------------
_Y_IDEAL_LINES = {
    "15m": 12, "30m": 12, "1hr": 10, "2hr": 10,
    "Day": 8,  "Tmrw": 8, "3D": 6,   "1W": 6,
}
_NICE_STEPS = [1, 2, 5, 10, 20, 25, 50, 100, 200, 250, 500, 1000, 2000]

def _get_price_step(timeframe, price_range):
    """Return a 'nice' Y-axis grid interval for the given timeframe & range."""
    target_lines = _Y_IDEAL_LINES.get(timeframe, 10)
    if price_range <= 0:
        return 10
    raw_step = price_range / target_lines
    best = _NICE_STEPS[-1]
    for s in _NICE_STEPS:
        if s >= raw_step:
            best = s
            break
    return best

# -- Dynamic Y-axis padding per timeframe ---------------------------------
_Y_PAD_PCT = {
    "15m": 0.05, "30m": 0.05, "1hr": 0.08, "2hr": 0.08,
    "Day": 0.12, "Tmrw": 0.18, "3D": 0.30,  "1W": 0.35,
}

# -- Prediction label intervals per timeframe ------------------------------
_PRED_LABEL_INTERVAL = {
    "15m": 2, "30m": 3, "1hr": 4, "2hr": 5,
    "Day": 5, "Tmrw": 4, "3D": 3, "1W": 3,
}

# -- Barrier strength weights for prediction damping -------------------------
# Each known price level acts as a friction zone that decelerates the
# Kalman prediction.  Strengths are 0–1; stronger → more deceleration.
_BARRIER_STRENGTH = {
    "fib618": 0.70,  "fib786": 0.55,  "res": 0.60,  "sup": 0.60,
    "fib382": 0.45,  "fib50":  0.40,  "pdh": 0.50,  "pdl": 0.50,
    "bbU":    0.30,  "bbL":    0.30,  "fib236": 0.15,
    "ma20":   0.15,  "ma50":   0.15,
}


def _sigmoid_damping(price, vel, barriers, atr):
    """Return velocity damping factor (0.05–1.0) from barrier proximity.

    Only damps when price is APPROACHING a barrier (not moving away).
    Influence zone = 1.5 × ATR around each barrier.
    Multiple barriers compound multiplicatively.
    Floor at 0.05 so prediction always creeps through.
    """
    if not barriers or atr <= 0:
        return 1.0
    influence = atr * 1.5
    damping = 1.0
    for level, strength in barriers:
        if level <= 0:
            continue
        dist = abs(price - level)
        if dist > influence:
            continue
        # Only damp if approaching the barrier
        approaching = (vel > 0 and price < level) or (vel < 0 and price > level)
        if not approaching:
            continue
        # proximity: 1.0 at barrier, 0.0 at edge of influence zone
        proximity = 1.0 - (dist / influence)
        # Sigmoid: sharp ramp in inner 40 % of zone
        sigmoid = 1.0 / (1.0 + math.exp(-10 * (proximity - 0.5)))
        damping *= (1.0 - strength * sigmoid)
    return max(0.05, damping)


PH6_MOCK = {
    "mode": "PAPER TRADE",
    "shadow_pnl": 2800,
    "trades_today": 2,
    "net_delta": 0.72,
    "net_theta": -5.30,
    "positions": [
        {"symbol": "RAMCOCEM", "strike": "900CE", "expiry": "Mar",
         "premium": 12.50, "delta": 0.45, "theta": -2.1, "shadow_pnl": 1800},
        {"symbol": "RELIANCE", "strike": "2420CE", "expiry": "Mar",
         "premium": 18.30, "delta": 0.52, "theta": -3.2, "shadow_pnl": 1000},
    ],
}

PH7_MOCK = {
    "session": "CLOSED",
    "opens": "17:00 IST",
    "countdown": "2h 14m",
    "mode": "Paper Trade",
    "evening_trades": 0,
    "instruments": [
        {"name": "GOLD",   "price": 72450, "spread": 12},
        {"name": "SILVER", "price": 86200, "spread": 28},
        {"name": "CRUDE",  "price": 6340,  "spread": 8},
        {"name": "NATGAS", "price": 228,   "spread": 4},
    ],
    "strategy": "15m--3hr intraday",
}

PH8_MOCK = {
    "score_threshold": 75,
    "scanning": 147,
    "above_threshold": 3,
    "signals_today": 5,
    "candidates": [
        {"symbol": "TATASTEEL", "score": 82, "adx": 32},
        {"symbol": "BAJFIN",    "score": 78, "adx": 28},
        {"symbol": "ITC",       "score": 74, "adx": 26},
    ],
    "entry_signals": 1,
    "approaching": "TATASTEEL approaching Rs.142 level",
}

# ---------- PH1 / PH2 / PH3 mock data (v5.6.2) ----------

PH1_MOCK = {
    "scan_time": "09:17",
    "total_scanned": 147,
    "selected_count": 5,
    "next_scan": "Tomorrow 09:15 AM",
    "stocks": [
        {"symbol": "HDFCBANK",  "price": 1642.0, "rsi": 42.3, "score": 88.2, "filter_stage": "F2A"},
        {"symbol": "SBIN",      "price": 784.0,  "rsi": 38.1, "score": 82.5, "filter_stage": "F2A"},
        {"symbol": "ICICIBANK", "price": 1245.0, "rsi": 44.7, "score": 78.0, "filter_stage": "F2B"},
        {"symbol": "RELIANCE",  "price": 1380.0, "rsi": 41.0, "score": 75.4, "filter_stage": "F2A"},
        {"symbol": "TATAMOTORS","price": 952.0,  "rsi": 39.5, "score": 71.8, "filter_stage": "F2C"},
    ],
    "filter_funnel": {"total": 147, "F1": 92, "F2A": 34, "F2B": 18, "selected": 5},
}

PH2_MOCK = {
    "decisions_today": 5,
    "monitoring": 5,
    "entries": 1,
    "skips": 3,
    "blocks": 1,
    "recent": [
        {"time": "10:15", "symbol": "HDFCBANK",  "decision": "ENTER",   "confidence": 82.0, "grade": "STRONG_BUY"},
        {"time": "10:32", "symbol": "SBIN",       "decision": "SKIP",    "confidence": 45.0, "grade": "SKIP"},
        {"time": "10:48", "symbol": "ICICIBANK",  "decision": "SKIP",    "confidence": 52.0, "grade": "MODERATE"},
        {"time": "11:05", "symbol": "RELIANCE",   "decision": "BLOCKED", "confidence": 0.0,  "grade": "BLOCKED"},
        {"time": "11:20", "symbol": "TATAMOTORS", "decision": "SKIP",    "confidence": 58.0, "grade": "MODERATE"},
    ],
}

PH3_MOCK = {
    "active_positions": 1,
    "max_positions": 3,
    "trades_today": 2,
    "win_rate": 50.0,
    "total_pnl": 1250.0,
    "positions": [
        {"symbol": "HDFCBANK", "direction": "BUY", "entry": 1642.0, "current": 1668.0, "pnl": "+1.6%", "status": "ACTIVE"},
    ],
    "trades": [
        {"symbol": "SBIN", "direction": "BUY", "entry": 784.0, "exit": 798.0, "pnl": "+1.8%", "reason": "TARGET"},
        {"symbol": "ITC",  "direction": "BUY", "entry": 445.0, "exit": 440.0, "pnl": "-1.1%", "reason": "STOP"},
    ],
}


# ==========================================================================
#  AVIATION GAUGE WIDGET
# ==========================================================================

class AviationGauge(ctk.CTkFrame):
    """
    Semicircular gauge with colored arc zones and animated needle.
    Zones define color bands: [(start_pct, end_pct, color_name), ...]
    """

    def __init__(self, parent, label, value, min_val=0, max_val=100,
                 unit="", zones=None, width=130, height=100, canvas_bg=None):
        super().__init__(parent, fg_color="transparent", width=width, height=height)
        self.pack_propagate(False)

        if canvas_bg is None:
            canvas_bg = BG_PANEL
        if zones is None:
            zones = [(0, 100, "green")]

        self._target = value
        self._min = min_val
        self._max = max_val
        self._zones = zones

        # Canvas for the arc and needle
        canvas_h = height - 38
        self._canvas = tk.Canvas(self, width=width, height=canvas_h,
                                 bg=canvas_bg, highlightthickness=0)
        self._canvas.pack(pady=(2, 0))

        # Arc geometry
        self._cx = width // 2
        self._cy = canvas_h - 3
        self._r = min(width // 2 - 8, canvas_h - 6)

        # Background arc
        bbox = (self._cx - self._r, self._cy - self._r,
                self._cx + self._r, self._cy + self._r)
        self._canvas.create_arc(*bbox, start=0, extent=180,
                                outline="#27272a", width=10, style="arc")

        # Colored zone arcs
        for s_pct, e_pct, cname in zones:
            color = ZONE_COLORS.get(cname, cname)
            sa = 180 * (1 - e_pct / 100)
            ext = 180 * (e_pct - s_pct) / 100
            self._canvas.create_arc(*bbox, start=sa, extent=ext,
                                    outline=color, width=8, style="arc")

        # Determine value color from zones
        val_color = TEXT_PRIMARY
        rng = max_val - min_val
        if rng > 0:
            pct = (value - min_val) / rng * 100
            for s, e, cn in zones:
                if s <= pct <= e:
                    val_color = ZONE_COLORS.get(cn, TEXT_PRIMARY)
                    break

        # Readout + label
        self._readout = ctk.CTkLabel(
            self, text=f"{value}{unit}",
            font=FONT_HEADING, text_color=val_color,
        )
        self._readout.pack()
        ctk.CTkLabel(self, text=label, font=FONT_TINY,
                     text_color=TEXT_MUTED).pack()

        # Animate needle
        self._needle_ids = []
        self._step = 0
        self._steps = 20
        self.after(50, self._tick)

    def _val_to_angle(self, v):
        rng = self._max - self._min
        if rng <= 0:
            return 90
        pct = max(0, min(1, (v - self._min) / rng))
        return 180 - pct * 180

    def _draw_needle(self, angle_deg):
        for i in self._needle_ids:
            self._canvas.delete(i)
        self._needle_ids.clear()

        rad = math.radians(angle_deg)
        r = self._r - 12
        cx, cy = self._cx, self._cy
        ex = cx + r * math.cos(rad)
        ey = cy - r * math.sin(rad)

        self._needle_ids.append(
            self._canvas.create_line(cx, cy, ex, ey, fill=WHITE, width=2))
        dr = 3
        self._needle_ids.append(
            self._canvas.create_oval(cx - dr, cy - dr, cx + dr, cy + dr,
                                     fill="#d4d4d8", outline="#d4d4d8"))

    def _tick(self):
        if self._step <= self._steps:
            t = self._step / self._steps
            t = 1 - (1 - t) ** 2  # ease-out
            val = self._min + (self._target - self._min) * t
            self._draw_needle(self._val_to_angle(val))
            self._step += 1
            self.after(25, self._tick)



# ==========================================================================
#  PYGAME EICAS GAUGE — offscreen rendered, embedded as CTkImage
# ==========================================================================

# Pygame initialized once at module level (offscreen only)
pygame.init()

# Font loading
_GAUGE_FONT_PATH = None
for _fp in ["C:/Windows/Fonts/JetBrainsMono-Bold.ttf",
            "C:/Windows/Fonts/consola.ttf"]:
    if os.path.exists(_fp):
        _GAUGE_FONT_PATH = _fp
        break

_ZONE_RGB = {
    "green": (34, 197, 94),
    "amber": (245, 158, 11),
    "red": (239, 68, 68),
}
GAUGE_SCALE = 2  # Render at 2x for HiDPI, downscale with LANCZOS


class PygameGauge:
    """Renders a single EICAS gauge to a PIL Image using Pygame offscreen at 2x for HiDPI."""

    def __init__(self, width=200, height=160):
        self.width = width
        self.height = height
        S = GAUGE_SCALE
        self.surface = pygame.Surface((width * S, height * S), pygame.SRCALPHA)

    def render(self, value, min_val, max_val, label, unit,
               plan_text="", zones=None):
        S = GAUGE_SCALE
        s = self.surface
        s.fill((25, 25, 32, 255))

        rw, rh = self.width * S, self.height * S
        cx = rw // 2
        cy = rh // 2 + 10 * S
        radius = min(rw // 2 - 16 * S, rh // 2 - 8 * S)

        # -- Step 1: Bezel ring --
        pygame.draw.circle(s, (40, 40, 50), (cx, cy), radius + 6 * S, 4 * S)
        for i in range(6):
            color = (55 + i * 10, 55 + i * 10, 65 + i * 10)
            pygame.draw.circle(s, color, (cx, cy), radius + 3 * S - i * S, max(1, S))
        # Glass reflection
        try:
            for dr in range(2):
                r = radius - 2 * S - dr * S
                for deg in range(120, 170):
                    rad = math.radians(deg)
                    px = int(cx + r * math.cos(rad))
                    py = int(cy - r * math.sin(rad))
                    if 0 <= px < rw and 0 <= py < rh:
                        s.set_at((px, py), (255, 255, 255, 20 - dr * 8))
        except Exception:
            pass

        # -- Step 2: Background arc track --
        arc_rect = pygame.Rect(cx - radius, cy - radius, radius * 2, radius * 2)
        pygame.draw.arc(s, (35, 35, 42), arc_rect,
                        math.radians(0), math.radians(180), 3 * S)

        # -- Step 3: Colored zone arcs (thick) --
        if zones is None:
            zones = [(0, 100, "green")]

        for s_pct, e_pct, cname in zones:
            zcolor = _ZONE_RGB.get(cname, (34, 197, 94))
            sa_deg = 180 - (e_pct / 100) * 180
            ea_deg = 180 - (s_pct / 100) * 180
            sa_rad = math.radians(sa_deg)
            ea_rad = math.radians(ea_deg)
            for thickness in range(-4 * S, 5 * S):
                r = radius + thickness
                if r < 5:
                    continue
                rect = pygame.Rect(cx - r, cy - r, r * 2, r * 2)
                try:
                    pygame.draw.arc(s, zcolor, rect, sa_rad, ea_rad, 1)
                except Exception:
                    pass

        # -- Step 4: Needle --
        rng = max_val - min_val
        val_norm = max(0, min(1, (value - min_val) / rng)) if rng > 0 else 0.5

        needle_angle = math.radians(180 - val_norm * 180)
        needle_len = radius - 10 * S
        end_x = cx + needle_len * math.cos(needle_angle)
        end_y = cy - needle_len * math.sin(needle_angle)

        base_r = 6 * S
        base_offset = 0.08
        p1 = (cx + base_r * math.cos(needle_angle - base_offset),
              cy - base_r * math.sin(needle_angle - base_offset))
        p2 = (cx + base_r * math.cos(needle_angle + base_offset),
              cy - base_r * math.sin(needle_angle + base_offset))
        p3 = (int(end_x), int(end_y))
        pts = [(int(p1[0]), int(p1[1])), (int(p2[0]), int(p2[1])), p3]
        pygame.draw.polygon(s, (220, 220, 230), pts)
        try:
            pygame.gfxdraw.aapolygon(s, pts, (220, 220, 230))
        except Exception:
            pass

        # -- Step 5: Center cap --
        cap_r = 7 * S
        cap_inner = 3 * S
        try:
            pygame.gfxdraw.filled_circle(s, cx, cy, cap_r, (160, 160, 170))
            pygame.gfxdraw.aacircle(s, cx, cy, cap_r, (190, 190, 200))
            pygame.gfxdraw.filled_circle(s, cx, cy, cap_inner, (220, 220, 230))
        except Exception:
            pygame.draw.circle(s, (180, 180, 190), (cx, cy), cap_r)
            pygame.draw.circle(s, (220, 220, 230), (cx, cy), cap_inner)

        # -- Step 6: Glow at needle tip --
        val_pct = val_norm * 100
        glow_color = (34, 197, 94)
        for sp, ep, cn in zones:
            if sp <= val_pct <= ep:
                glow_color = _ZONE_RGB.get(cn, (34, 197, 94))
                break

        glow_sz = 30 * S
        glow_surf = pygame.Surface((glow_sz, glow_sz), pygame.SRCALPHA)
        half = glow_sz // 2
        for r in range(half, 0, -1):
            alpha = int(50 * (1 - r / half))
            try:
                pygame.gfxdraw.filled_circle(glow_surf, half, half, r,
                                             (*glow_color, alpha))
            except Exception:
                pass
        s.blit(glow_surf, (int(end_x) - half, int(end_y) - half))

        # -- Step 7: Scale markings --
        try:
            if _GAUGE_FONT_PATH:
                tick_font = pygame.font.Font(_GAUGE_FONT_PATH, 10 * S)
            else:
                tick_font = pygame.font.SysFont("consolas", 10 * S)
        except Exception:
            tick_font = pygame.font.SysFont("monospace", 10 * S)

        for i in range(11):
            pct = i / 10
            angle = math.radians(180 - pct * 180)
            inner_r = radius - 14 * S
            outer_r = radius - 7 * S

            x1 = cx + inner_r * math.cos(angle)
            y1 = cy - inner_r * math.sin(angle)
            x2 = cx + outer_r * math.cos(angle)
            y2 = cy - outer_r * math.sin(angle)

            lw = 2 * S if i % 5 == 0 else max(1, S)
            pygame.draw.line(s, (110, 110, 120),
                             (int(x1), int(y1)), (int(x2), int(y2)), lw)

            if i % 2 == 0 or i == 10:
                val_at = min_val + (max_val - min_val) * pct
                txt = tick_font.render(f"{val_at:.0f}", True, (90, 90, 100))
                lx = cx + (inner_r - 12 * S) * math.cos(angle) - txt.get_width() // 2
                ly = cy - (inner_r - 12 * S) * math.sin(angle) - txt.get_height() // 2
                s.blit(txt, (int(lx), int(ly)))

        # -- Step 8: Value text --
        try:
            if _GAUGE_FONT_PATH:
                value_font = pygame.font.Font(_GAUGE_FONT_PATH, 28 * S)
                label_font = pygame.font.Font(_GAUGE_FONT_PATH, 14 * S)
                plan_font = pygame.font.Font(_GAUGE_FONT_PATH, 11 * S)
            else:
                value_font = pygame.font.SysFont("consolas", 28 * S, bold=True)
                label_font = pygame.font.SysFont("consolas", 14 * S)
                plan_font = pygame.font.SysFont("consolas", 11 * S)
        except Exception:
            value_font = pygame.font.SysFont("monospace", 28 * S, bold=True)
            label_font = pygame.font.SysFont("monospace", 14 * S)
            plan_font = pygame.font.SysFont("monospace", 11 * S)

        if isinstance(value, float):
            vtxt = f"{value:.1f}{unit}" if abs(value) < 100 else f"{value:.0f}{unit}"
        else:
            vtxt = f"{value}{unit}"
        val_surf = value_font.render(vtxt, True, glow_color)
        s.blit(val_surf, (cx - val_surf.get_width() // 2, cy + 10 * S))

        lbl_surf = label_font.render(label, True, (176, 176, 186))
        s.blit(lbl_surf, (cx - lbl_surf.get_width() // 2, cy + 34 * S))

        if plan_text:
            pln_surf = plan_font.render(plan_text, True, (85, 85, 95))
            s.blit(pln_surf, (cx - pln_surf.get_width() // 2, cy + 48 * S))

        # Convert to PIL Image and downscale with LANCZOS for crisp HiDPI
        raw = pygame.image.tostring(s, "RGBA")
        pil_img = PILImage.frombytes("RGBA", (rw, rh), raw)
        pil_img = pil_img.resize((self.width, self.height), PILImage.LANCZOS)
        return pil_img

class EicasGaugeWidget(ctk.CTkFrame):
    """CTk widget displaying a Pygame-rendered EICAS gauge + detail rows."""

    def __init__(self, parent, title, value, min_val, max_val, unit,
                 zones=None, plan_text="", details=None,
                 gauge_w=200, gauge_h=160):
        super().__init__(parent, fg_color=BG_INPUT, corner_radius=6,
                         border_width=1, border_color=BORDER_DIM)

        self._renderer = PygameGauge(width=gauge_w, height=gauge_h)
        self._title = title
        self._min = min_val
        self._max = max_val
        self._unit = unit
        self._zones = zones or [(0, 100, "green")]
        self._plan_text = plan_text
        self._gw = gauge_w
        self._gh = gauge_h
        self._current_value = min_val
        self._target_value = value
        self._anim_step = 0
        self._anim_steps = 20
        self._anim_after_id = None

        # Render gauge
        pil_img = self._renderer.render(
            value, min_val, max_val, title, unit,
            plan_text=plan_text, zones=self._zones)
        self._ctk_image = ctk.CTkImage(
            light_image=pil_img, dark_image=pil_img,
            size=(gauge_w, gauge_h))
        self._gauge_label = ctk.CTkLabel(self, image=self._ctk_image, text="")
        self._gauge_label.pack(padx=2, pady=(2, 0))

        # Separator
        ctk.CTkFrame(self, fg_color=BORDER_DIM, height=1).pack(
            fill="x", padx=6, pady=2)

        # Detail rows
        if details:
            for lbl, val in details:
                row = ctk.CTkFrame(self, fg_color="transparent", height=18)
                row.pack(fill="x", padx=6)
                row.pack_propagate(False)
                ctk.CTkLabel(row, text=lbl,
                             font=FONT_SMALL,
                             text_color=TEXT_DIM,
                             anchor="w").pack(side="left")
                ctk.CTkLabel(row, text=val,
                             font=FONT_SMALL_BOLD,
                             text_color=TEXT_LABEL,
                             anchor="e").pack(side="right")

        # Start needle animation
        self._animate_start(value)

    def _animate_start(self, target):
        self._current_value = self._min
        self._target_value = target
        self._anim_step = 0
        self._anim_tick()

    def _anim_tick(self):
        if self._anim_step > self._anim_steps:
            return
        t = self._anim_step / self._anim_steps
        t = 1 - (1 - t) ** 2  # ease-out
        val = self._min + (self._target_value - self._min) * t
        pil_img = self._renderer.render(
            val, self._min, self._max, self._title, self._unit,
            plan_text=self._plan_text, zones=self._zones)
        self._ctk_image.configure(light_image=pil_img, dark_image=pil_img)
        self._anim_step += 1
        self._anim_after_id = self.after(25, self._anim_tick)

    def update_value(self, new_value):
        if self._anim_after_id:
            self.after_cancel(self._anim_after_id)
        self._current_value = self._target_value
        self._target_value = new_value
        self._anim_step = 0
        self._anim_steps = 20
        self._anim_tick_smooth()

    def _anim_tick_smooth(self):
        if self._anim_step > self._anim_steps:
            return
        t = self._anim_step / self._anim_steps
        t = 1 - (1 - t) ** 2
        val = self._current_value + (self._target_value - self._current_value) * t
        pil_img = self._renderer.render(
            val, self._min, self._max, self._title, self._unit,
            plan_text=self._plan_text, zones=self._zones)
        self._ctk_image.configure(light_image=pil_img, dark_image=pil_img)
        self._anim_step += 1
        self._anim_after_id = self.after(25, self._anim_tick_smooth)

    def destroy(self):
        if self._anim_after_id:
            self.after_cancel(self._anim_after_id)
            self._anim_after_id = None
        super().destroy()

# ==========================================================================
#  HELPER WIDGETS
# ==========================================================================

def _instrument_panel(parent, title):
    """Aviation-styled instrument panel section (pack-based)."""
    f = ctk.CTkFrame(parent, fg_color=BG_PANEL, corner_radius=8,
                     border_width=1, border_color=BORDER)
    tb = ctk.CTkFrame(f, fg_color=BG_HEADER, corner_radius=0, height=30)
    tb.pack(fill="x")
    tb.pack_propagate(False)
    ctk.CTkLabel(tb, text=title, font=FONT_SMALL_BOLD,
                 text_color=TEXT_MUTED, anchor="w").pack(side="left", padx=12, pady=5)
    return f


def _back_button(parent, on_back):
    """Aviation 'return to base' button."""
    return ctk.CTkButton(
        parent, text="<  RETURN TO OVERVIEW",
        font=FONT_BODY_BOLD,
        fg_color=BG_HEADER, hover_color=BORDER,
        text_color=TEXT_LABEL, height=32, width=220,
        anchor="w", command=on_back,
    )


def _title_bar(parent, text):
    """Phase title bar with aviation styling."""
    bar = ctk.CTkFrame(parent, fg_color=BG_PANEL, corner_radius=8,
                       border_width=1, border_color=BORDER, height=38)
    bar.pack_propagate(False)
    ctk.CTkLabel(bar, text=text, font=FONT_HEADING,
                 text_color=CYAN, anchor="w").pack(side="left", padx=14, pady=6)
    return bar


def _stat_row(parent, label, value, value_color=TEXT_PRIMARY):
    """Compact stat row: label left, value right."""
    r = ctk.CTkFrame(parent, fg_color="transparent")
    r.pack(fill="x", padx=12, pady=2)
    ctk.CTkLabel(r, text=label, font=FONT_SMALL,
                 text_color=TEXT_MUTED, anchor="w").pack(side="left")
    ctk.CTkLabel(r, text=str(value), font=FONT_BODY_BOLD,
                 text_color=value_color, anchor="e").pack(side="right")


def _log_entry(parent, time_str, message, tag="info"):
    """Flight data recorder entry with colored message."""
    colors = {"info": TEXT_LABEL, "phase": CYAN, "success": GREEN,
              "warning": AMBER, "error": RED}
    color = colors.get(tag, TEXT_LABEL)

    r = ctk.CTkFrame(parent, fg_color="transparent")
    r.pack(fill="x", padx=8, pady=1)
    ctk.CTkLabel(r, text=time_str, font=FONT_SMALL_BOLD,
                 text_color=TEXT_DIM, width=50, anchor="w").pack(side="left")
    ctk.CTkLabel(r, text=message, font=FONT_SMALL,
                 text_color=color, anchor="w").pack(side="left", fill="x", expand=True)


def _status_bar(parent, items):
    """Bottom status bar with key-value pairs."""
    bar = ctk.CTkFrame(parent, fg_color=BG_PANEL, corner_radius=8,
                       border_width=1, border_color=BORDER, height=36)
    bar.pack_propagate(False)
    inner = ctk.CTkFrame(bar, fg_color="transparent")
    inner.pack(expand=True)
    for i, (text, color) in enumerate(items):
        ctk.CTkLabel(inner, text=text, font=FONT_SMALL_BOLD,
                     text_color=color).pack(side="left", padx=8)
        if i < len(items) - 1:
            ctk.CTkLabel(inner, text="|", font=("", 10),
                         text_color=BORDER_DIM).pack(side="left")
    return bar


def _nice_interval(range_span, target_ticks=6):
    """Return a 'nice' tick interval for axis labels."""
    if range_span <= 0:
        return 1
    rough = range_span / max(target_ticks, 1)
    mag = 10 ** math.floor(math.log10(rough)) if rough > 0 else 1
    for nice in (1, 2, 2.5, 5, 10):
        if mag * nice >= rough:
            return mag * nice
    return mag * 10


# ==========================================================================
#  SPEED TAPE  (vertical Kalman velocity strip, left of attitude indicator)
# ==========================================================================

class SpeedTape(ctk.CTkFrame):
    """Vertical scrolling tape showing Kalman velocity (-3 to +3 Rs/min)."""

    def __init__(self, parent, width=60):
        super().__init__(parent, fg_color=BG_PANEL, corner_radius=0,
                         border_width=1, border_color=BORDER, width=width)
        self.pack_propagate(False)
        self._canvas = tk.Canvas(self, bg=BG_PANEL, highlightthickness=0)
        self._canvas.pack(fill="both", expand=True)
        self._value = 0.0
        self._target = 0.0
        self._volume_ratio = 0.0
        self._anim_id = None
        self._anim_step = 0
        self._start_val = 0.0
        self._cw = 1
        self._ch = 1
        self._ready = False
        self._pending = False
        self._canvas.bind("<Configure>", self._on_cfg)

    def _on_cfg(self, event):
        if event.width < 20 or event.height < 40:
            return
        self._cw, self._ch = event.width, event.height
        self._ready = True
        if self._pending:
            self._pending = False
            self._start_anim()
        else:
            self._render()

    def _render(self):
        cv = self._canvas
        cv.delete("all")
        cw, ch = self._cw, self._ch
        cy = ch // 2
        val = self._value
        px_per_unit = ch * 0.13

        # -- Header: two-line "SPD" + "VOL (REL)" --
        cv.create_text(cw // 2, 7, text="SPD",
                       fill=TEXT_DIM, font=FONT_TINY_BOLD)
        cv.create_text(cw // 2, 18, text="VOL (REL)",
                       fill=TEXT_MUTED, font=FONT_TINY)

        # -- Tick marks and numbers --
        for tick10 in range(-30, 31):
            tv = tick10 / 10.0
            dy = (val - tv) * px_per_unit
            y = cy + dy
            if y < 25 or y > ch - 30:
                continue
            is_major = tick10 % 10 == 0
            is_half = tick10 % 5 == 0
            tc = GREEN if tv > 0.01 else RED if tv < -0.01 else TEXT_PRIMARY
            if is_major:
                cv.create_line(cw - 2, y, cw - 18, y, fill=tc, width=1)
                cv.create_text(cw - 22, y, text=f"{tv:+.0f}",
                               fill=tc, font=FONT_TINY,
                               anchor="e")
            elif is_half:
                cv.create_line(cw - 2, y, cw - 12, y, fill=BORDER, width=1)

        # -- STALL markers at ±2.5 velocity --
        for stall_v in (2.5, -2.5):
            sy = cy + (val - stall_v) * px_per_unit
            if 20 < sy < ch - 25:
                cv.create_rectangle(2, sy - 8, cw - 4, sy + 8,
                                    fill="", outline=RED, width=2)
                cv.create_text(cw // 2, sy, text="STALL",
                               fill=RED, font=FONT_TINY_BOLD)

        # -- Thin color strip on right edge --
        zero_y = cy + val * px_per_unit
        if zero_y < ch:
            cv.create_line(cw - 1, 0, cw - 1, max(0, zero_y),
                           fill=GREEN, width=2)
        if zero_y > 0:
            cv.create_line(cw - 1, min(ch, zero_y), cw - 1, ch,
                           fill=RED, width=2)

        # -- Current value bug (pointer + digital readout) --
        bh = 13
        cv.create_rectangle(1, cy - bh, cw - 4, cy + bh,
                            fill="#0a0a10", outline=AIRCRAFT_REF, width=2)
        vc = GREEN if val > 0.01 else RED if val < -0.01 else TEXT_PRIMARY
        cv.create_text(cw // 2 - 1, cy, text=f"{val:+.1f}",
                       fill=vc, font=FONT_BODY_BOLD)

        # -- Pointer arrow on right --
        cv.create_polygon(cw - 3, cy, cw - 3 - 8, cy - 5,
                          cw - 3 - 8, cy + 5,
                          fill=AIRCRAFT_REF, outline="")

        # -- Volume % box at bottom --
        vol_pct = self._volume_ratio * 100
        if vol_pct >= 100:
            vol_col = GREEN
        elif vol_pct >= 50:
            vol_col = AMBER
        else:
            vol_col = RED
        bx1, by1, bx2, by2 = 2, ch - 24, cw - 2, ch - 4
        cv.create_rectangle(bx1, by1, bx2, by2,
                            fill="#0a0a10", outline=vol_col, width=2)
        cv.create_text((bx1 + bx2) // 2, (by1 + by2) // 2,
                       text=f"{vol_pct:.0f}%",
                       fill=vol_col, font=FONT_TINY_BOLD)

    def update_data(self, pos):
        self._target = pos.get("velocity", 0.0)
        self._volume_ratio = pos.get("volume_ratio", 0.0)
        self._start_anim()

    def _start_anim(self):
        if self._anim_id:
            self.after_cancel(self._anim_id)
            self._anim_id = None
        if not self._ready:
            self._pending = True
            return
        self._anim_step = 0
        self._start_val = self._value
        self._tick()

    def _tick(self):
        N = 20
        if self._anim_step <= N:
            t = self._anim_step / N
            t = 1 - (1 - t) ** 3
            self._value = self._start_val + (self._target - self._start_val) * t
            self._render()
            self._anim_step += 1
            self._anim_id = self.after(22, self._tick)
        else:
            self._anim_id = None


# ==========================================================================
#  ALTITUDE TAPE  (vertical price strip with markers, right of attitude)
# ==========================================================================

class AltitudeTape(ctk.CTkFrame):
    """Vertical scrolling tape showing price levels with reference markers."""

    # (name, key, color, label, sublabel, boxed)
    _MARKER_DEFS = [
        ("TGT",   "ils_target",  GREEN,    "\u25b6TGT",  "(MPT-TP-1)",   True),
        ("TCAS",  "tcas_floor",  RED,      "\u25b6SL",   "GND/TERRAIN",  True),
        ("BB\u25b2",  "bb_upper",    RED,      "BB\u25b2",    "",             False),
        ("BB\u25bc",  "bb_lower",    RED,      "BB\u25bc",    "",             False),
        ("EMA",   "bb_middle",   CYAN,     "EMA",     "",             False),
        ("ENTRY", "entry",       AMBER,    "ENTR",    "",             False),
        ("S",     "support",     TEXT_DIM,  "S",      "",             False),
        ("R",     "resistance",  TEXT_DIM,  "R",      "",             False),
    ]

    def __init__(self, parent, width=70):
        super().__init__(parent, fg_color=BG_PANEL, corner_radius=0,
                         border_width=1, border_color=BORDER, width=width)
        self.pack_propagate(False)
        self._canvas = tk.Canvas(self, bg=BG_PANEL, highlightthickness=0)
        self._canvas.pack(fill="both", expand=True)
        self._price = 0.0
        self._target_price = 0.0
        self._velocity = 0.0
        self._markers = {}
        self._range_min = 0
        self._range_max = 1
        self._anim_id = None
        self._anim_step = 0
        self._start_price = 0.0
        self._cw = 1
        self._ch = 1
        self._ready = False
        self._pending = False
        self._canvas.bind("<Configure>", self._on_cfg)

    def _on_cfg(self, event):
        if event.width < 20 or event.height < 40:
            return
        self._cw, self._ch = event.width, event.height
        self._ready = True
        if self._pending:
            self._pending = False
            self._start_anim()
        else:
            self._render()

    def _price_to_y(self, price):
        total = (self._range_max - self._range_min)
        if total <= 0:
            return self._ch // 2
        px_per_unit = (self._ch - 40) / total
        return self._ch // 2 - (price - self._price) * px_per_unit

    def _render(self):
        cv = self._canvas
        cv.delete("all")
        cw, ch = self._cw, self._ch
        cy = ch // 2

        total_range = self._range_max - self._range_min
        if total_range <= 0:
            return
        px_per_unit = (ch - 40) / total_range
        interval = _nice_interval(total_range, 8)

        # -- Split header: "ALT/PRICE" left + "VSI" right --
        cv.create_text(4, 7, text="ALT/PRICE",
                       fill=TEXT_DIM, font=FONT_TINY_BOLD,
                       anchor="w")
        cv.create_text(cw - 4, 7, text="VSI",
                       fill=TEXT_MUTED, font=FONT_TINY_BOLD,
                       anchor="e")

        # -- Grid ticks --
        p = math.ceil((self._price - total_range * 0.7) / interval) * interval
        p_end = self._price + total_range * 0.7
        while p <= p_end:
            y = self._price_to_y(p)
            if 18 <= y <= ch - 20:
                cv.create_line(0, y, 8, y, fill=BORDER, width=1)
                cv.create_text(10, y, text=f"{p:.0f}",
                               fill=TEXT_DIM, font=FONT_TINY,
                               anchor="w")
            p += interval

        # -- Reference markers (with optional boxes + sublabels) --
        for _name, _key, color, label, sublabel, boxed in self._MARKER_DEFS:
            mprice = self._markers.get(_key)
            if mprice is None:
                continue
            y = self._price_to_y(mprice)
            if y < 15 or y > ch - 15:
                continue
            # Dashed line
            for xs in range(0, cw, 8):
                cv.create_line(xs, y, min(xs + 4, cw), y,
                               fill=color, width=1)
            if boxed:
                # Boxed marker: colored outline rectangle with label + sublabel
                bx1, by1 = 2, y - 10
                bx2, by2 = cw - 4, y + (10 if not sublabel else 16)
                cv.create_rectangle(bx1, by1, bx2, by2,
                                    fill="#0a0a10", outline=color, width=2)
                cv.create_text(bx1 + 4, y - 2, text=label, fill=color,
                               font=FONT_TINY_BOLD, anchor="w")
                if sublabel:
                    cv.create_text(bx1 + 4, y + 8, text=sublabel,
                                   fill=TEXT_MUTED,
                                   font=FONT_TINY, anchor="w")
            else:
                # Simple label
                cv.create_text(3, y - 9, text=label, fill=color,
                               font=FONT_TINY_BOLD, anchor="w")

        # -- Current price bug (larger box, P&L-colored border) --
        bh = 16
        pc = GREEN if self._price >= self._markers.get("entry", 0) else RED
        cv.create_rectangle(0, cy - bh, cw - 2, cy + bh,
                            fill="#0a0a10", outline=pc, width=2)
        cv.create_text(cw // 2, cy, text=f"{self._price:.1f}",
                       fill=pc, font=FONT_SMALL_BOLD)

        # -- Pointer arrow on left --
        cv.create_polygon(2, cy, 10, cy - 5, 10, cy + 5,
                          fill=AIRCRAFT_REF, outline="")

        # -- VSI readout at bottom-right --
        vsi = self._velocity
        vsi_sign = "+" if vsi >= 0 else ""
        vsi_col = GREEN if vsi > 0.01 else RED if vsi < -0.01 else TEXT_MUTED
        cv.create_text(cw - 4, ch - 10,
                       text=f"{vsi_sign}{vsi:.1f} pts/m",
                       fill=vsi_col, font=FONT_TINY_BOLD,
                       anchor="e")

    def update_data(self, pos):
        self._target_price = pos.get("current", 0)
        self._velocity = pos.get("velocity", 0.0)
        self._markers = {}
        for _name, key, _c, _l, _sl, _bx in self._MARKER_DEFS:
            v = pos.get(key)
            if v is not None:
                self._markers[key] = v
        all_p = list(self._markers.values()) + [pos.get("current", 0)]
        self._range_min = min(all_p) - (max(all_p) - min(all_p)) * 0.15
        self._range_max = max(all_p) + (max(all_p) - min(all_p)) * 0.15
        self._start_anim()

    def _start_anim(self):
        if self._anim_id:
            self.after_cancel(self._anim_id)
            self._anim_id = None
        if not self._ready:
            self._pending = True
            return
        self._anim_step = 0
        self._start_price = self._price
        self._tick()

    def _tick(self):
        N = 20
        if self._anim_step <= N:
            t = self._anim_step / N
            t = 1 - (1 - t) ** 3
            self._price = self._start_price + (self._target_price - self._start_price) * t
            self._render()
            self._anim_step += 1
            self._anim_id = self.after(22, self._tick)
        else:
            self._anim_id = None


# ==========================================================================
#  HEADING STRIP  (horizontal trend compass below attitude indicator)
# ==========================================================================

class HeadingStrip(ctk.CTkFrame):
    """Horizontal compass strip mapping velocity→heading (BEAR→NEUT→BULL)."""

    _LABELS = {
        0: "BEAR", 60: "060", 90: "WEAK", 120: "120",
        180: "NEUT", 240: "240", 270: "STRG", 300: "300", 360: "BULL",
    }

    def __init__(self, parent, height=35):
        super().__init__(parent, fg_color=BG_PANEL, corner_radius=0,
                         border_width=1, border_color=BORDER, height=height)
        self.pack_propagate(False)
        self._canvas = tk.Canvas(self, bg=BG_PANEL, highlightthickness=0)
        self._canvas.pack(fill="both", expand=True)
        self._heading = 180.0
        self._target_heading = 180.0
        self._trend_label = "NEUTRAL"
        self._trend_color = TEXT_MUTED
        self._anim_id = None
        self._anim_step = 0
        self._start_hdg = 180.0
        self._cw = 1
        self._ch = 1
        self._ready = False
        self._pending = False
        self._canvas.bind("<Configure>", self._on_cfg)

    def _on_cfg(self, event):
        if event.width < 40 or event.height < 15:
            return
        self._cw, self._ch = event.width, event.height
        self._ready = True
        if self._pending:
            self._pending = False
            self._start_anim()
        else:
            self._render()

    def _render(self):
        cv = self._canvas
        cv.delete("all")
        cw, ch = self._cw, self._ch
        cx = cw // 2
        hdg = self._heading
        visible = 140  # degrees visible in strip
        px_per_deg = cw / visible

        # -- Subtle background coloring --
        mid_x = cx + (180 - hdg) * px_per_deg
        # Green tint right of neutral, red tint left
        cv.create_rectangle(max(0, mid_x), 0, cw, ch,
                            fill="#0a1a0e", outline="")
        cv.create_rectangle(0, 0, max(0, mid_x), ch,
                            fill="#1a0a0a", outline="")

        # -- Tick marks --
        for deg in range(0, 361, 10):
            x = cx + (deg - hdg) * px_per_deg
            if x < -20 or x > cw + 20:
                continue
            is_major = deg % 30 == 0
            th = ch * 0.4 if is_major else ch * 0.2
            cv.create_line(x, 0, x, th, fill=BORDER if not is_major else TEXT_DIM,
                           width=1)
            label = self._LABELS.get(deg)
            if label:
                lc = GREEN if deg > 200 else RED if deg < 160 else TEXT_LABEL
                cv.create_text(x, ch * 0.55, text=label, fill=lc,
                               font=FONT_TINY_BOLD)

        # -- Center pointer (amber triangle at top) --
        cv.create_polygon(cx, 0, cx - 6, 10, cx + 6, 10,
                          fill=AIRCRAFT_REF, outline="")

        # -- Trend label --
        cv.create_text(cx, ch - 5, text=self._trend_label,
                       fill=self._trend_color,
                       font=FONT_TINY_BOLD)

    def update_data(self, pos):
        vel = pos.get("velocity", 0.0)
        acc = pos.get("acceleration", 0.0)
        clamped = max(-3.0, min(3.0, vel))
        heading = 180.0 + (clamped / 3.0) * 180.0
        heading += max(-20, min(20, acc * 50))
        self._target_heading = max(0, min(360, heading))
        if vel > 0.5:
            self._trend_label, self._trend_color = "STATUS: CLIMBING FAST", GREEN
        elif vel > 0.1:
            self._trend_label, self._trend_color = "STATUS: CLIMBING", GREEN
        elif vel < -0.5:
            self._trend_label, self._trend_color = "STATUS: DESCENDING FAST", RED
        elif vel < -0.1:
            self._trend_label, self._trend_color = "STATUS: DESCENDING", RED
        else:
            self._trend_label, self._trend_color = "STATUS: LEVEL", TEXT_MUTED
        self._start_anim()

    def _start_anim(self):
        if self._anim_id:
            self.after_cancel(self._anim_id)
            self._anim_id = None
        if not self._ready:
            self._pending = True
            return
        self._anim_step = 0
        self._start_hdg = self._heading
        self._tick()

    def _tick(self):
        N = 20
        if self._anim_step <= N:
            t = self._anim_step / N
            t = 1 - (1 - t) ** 3
            self._heading = self._start_hdg + (self._target_heading - self._start_hdg) * t
            self._render()
            self._anim_step += 1
            self._anim_id = self.after(22, self._tick)
        else:
            self._anim_id = None


# ==========================================================================
#  NAV DISPLAY v3 — 3 flight paths + prediction cone + timeframe-aware levels
# ==========================================================================
#  NAV DISPLAY v3 — matplotlib FigureCanvasTkAgg
# ==========================================================================

class NavDisplayV3(ctk.CTkFrame):
    """Hero NAV display using matplotlib for reliable rendering."""

    def __init__(self, parent):
        super().__init__(parent, fg_color=BG_PANEL, corner_radius=4,
                         border_width=1, border_color=BORDER)

        self.fig = Figure(facecolor='#08080d', dpi=100)
        self.ax = self.fig.add_axes([0.06, 0.07, 0.88, 0.86])
        self.ax.set_facecolor('#08080d')

        self._mpl_canvas = FigureCanvasTkAgg(self.fig, master=self)
        self._mpl_canvas.get_tk_widget().pack(fill="both", expand=True)

        self._pos = None
        self._all_pos = []
        self._timeframe = "1hr"
        self._show_history = False
        self._history_predictions = []
        self._last_pred = []

        # Ensemble prediction engine (advisory display)
        self._ensemble_engine = EnsemblePrediction() if ENSEMBLE_AVAILABLE else None
        self._ensemble_result = None  # Cache last PredictionResult

    # -- Kalman prediction -------------------------------------------------
    def _kalman_predict(self, current, vel, acc, duration, step,
                        clamp_range=None, barriers=None, atr=1):
        """Predict future price using Kalman state with barrier damping.

        Uses step-by-step integration so that velocity is smoothly
        reduced (via _sigmoid_damping) as the predicted price
        approaches known S/R, Fibonacci, PDH/PDL, BB, or MA levels.
        """
        pts = []
        p = current
        v = vel
        t = 0
        while t <= duration:
            pts.append({"t": t, "p": p})
            # Damping: slow down near price barriers
            damp = _sigmoid_damping(p, v, barriers, atr) if barriers else 1.0
            # Advance position with damped velocity
            dp = v * damp * step + 0.5 * acc * step * step
            p += dp
            # Velocity evolves from original Kalman state
            v = vel + acc * t
            t += step
            # Safety clamp
            if clamp_range:
                p = max(clamp_range[0], min(clamp_range[1], p))
        return pts

    @staticmethod
    def _declutter_labels(labels, ax, min_gap_px=14):
        """Adjust y-positions so labels don't overlap.
        labels: list of {'y': float, 'fontsize': int}
        Returns: list of adjusted y data-coordinates (same order).
        """
        if not labels:
            return []
        transform = ax.transData
        inv_transform = ax.transData.inverted()
        indexed = []
        for i, lbl in enumerate(labels):
            _, py = transform.transform((0, lbl['y']))
            indexed.append({'idx': i, 'py': py, 'dy': lbl['y']})
        indexed.sort(key=lambda item: item['py'])
        for j in range(1, len(indexed)):
            gap = indexed[j]['py'] - indexed[j-1]['py']
            if gap < min_gap_px:
                indexed[j]['py'] = indexed[j-1]['py'] + min_gap_px
        result = [0.0] * len(labels)
        for item in indexed:
            _, dy = inv_transform.transform((0, item['py']))
            result[item['idx']] = dy
        return result

    # -- Main render -------------------------------------------------------
    def _render(self):
        ax = self.ax
        ax.clear()
        ax.set_facecolor('#08080d')

        pos = self._pos
        if not pos:
            self._mpl_canvas.draw_idle()
            return

        tf_key = self._timeframe
        tf = TIMEFRAME_CONFIG.get(tf_key, TIMEFRAME_CONFIG["1hr"])
        is_ext = tf["kalman_scale"] in ("hourly", "daily")

        # Level set
        levels = pos.get("levels_daily") if is_ext else pos.get("levels_intraday")
        if not levels:
            levels = pos.get("levels_intraday", {})

        sup = levels.get("sup", pos.get("support", 0))
        res = levels.get("res", pos.get("resistance", 0))
        ma20 = levels.get("ma20", pos.get("ema_20", 0))
        ma50 = levels.get("ma50", pos.get("ema_50", 0))
        bbU = levels.get("bbU", pos.get("bb_upper", 0))
        bbM = levels.get("bbM", pos.get("bb_middle", 0))
        bbL = levels.get("bbL", pos.get("bb_lower", 0))
        pdh = pos.get("pdh", 0)
        pdl = pos.get("pdl", 0)

        fibs = {}
        for fk in ("fib236", "fib382", "fib50", "fib618", "fib786"):
            fibs[fk] = levels.get(fk, 0)

        # Kalman vel/acc per scale (in native units: ₹/day, ₹/hr, ₹/min)
        if tf["kalman_scale"] == "daily":
            kd = pos.get("kalman_daily", {})
            vel_raw = kd.get("velocity", pos.get("velocity", 0))
            acc_raw = kd.get("acceleration", pos.get("acceleration", 0))
        elif tf["kalman_scale"] == "hourly":
            kh = pos.get("kalman_hourly", {})
            vel_raw = kh.get("velocity", pos.get("velocity", 0))
            acc_raw = kh.get("acceleration", pos.get("acceleration", 0))
        else:
            vel_raw = pos.get("velocity", 0)
            acc_raw = pos.get("acceleration", 0)

        # ── UNIT CONVERSION ─────────────────────────────────────────
        # vel_raw is ₹/day or ₹/hr or ₹/min depending on kalman_scale.
        # _kalman_predict uses t in MINUTES, so convert vel/acc to per-minute.
        if tf["kalman_scale"] == "daily":
            vel = vel_raw / MINS_PER_TDAY              # ₹/day  → ₹/min
            acc = acc_raw / (MINS_PER_TDAY ** 2)       # ₹/day² → ₹/min²
        elif tf["kalman_scale"] == "hourly":
            vel = vel_raw / MINS_PER_HOUR              # ₹/hr   → ₹/min
            acc = acc_raw / (MINS_PER_HOUR ** 2)       # ₹/hr²  → ₹/min²
        else:
            vel = vel_raw                              # already ₹/min
            acc = acc_raw

        history = pos.get("history", [])
        last_t = history[-1]["t"] if history else 0
        pred_step = max(1, round(tf["prediction"] / 25))

        entry = pos["entry"]
        current = pos["current"]
        target = pos["ils_target"]
        tcas = pos["tcas_floor"]
        plan_tgt = pos.get("plan", {}).get("target", target)
        plan_sl = pos.get("plan", {}).get("stop_loss", tcas)
        atr = pos.get("atr_14", 1)

        # -- Clamp range for Kalman predictions (safety net) --
        # Scale clamp width with timeframe so multi-day preds aren't artificially flattened
        _clamp_atr_mult = {
            "15m": 3, "30m": 4, "1hr": 5, "2hr": 5,
            "Day": 6, "Tmrw": 8, "3D": 12, "1W": 16,
        }
        atr_mult = _clamp_atr_mult.get(tf_key, 5)
        atr_band = max(atr * atr_mult, abs(current) * 0.03 * (atr_mult / 5))
        clamp_lo = current - atr_band
        clamp_hi = current + atr_band

        # -- Build barrier list for sigmoid velocity damping ---------------
        _barriers = []
        for name, lvl in [("sup", sup), ("res", res), ("pdh", pdh), ("pdl", pdl),
                          ("bbU", bbU), ("bbL", bbL), ("ma20", ma20), ("ma50", ma50)]:
            if lvl and lvl > 0:
                _barriers.append((lvl, _BARRIER_STRENGTH.get(name, 0.2)))
        for fk, fv in fibs.items():
            if fv and fv > 0:
                _barriers.append((fv, _BARRIER_STRENGTH.get(fk, 0.2)))

        pred = self._kalman_predict(current, vel, acc,
                                    tf["prediction"], pred_step,
                                    clamp_range=(clamp_lo, clamp_hi),
                                    barriers=_barriers, atr=atr)
        self._last_pred = pred  # expose for external access (history store)

        # ── ENSEMBLE PREDICTION (replaces raw Kalman as primary display) ────
        # Barrier-aware Kalman `pred` stays as fallback; ensemble overrides when available.
        _ens_kalman_path = []
        _ens_linear_path = []
        _ens_poly_path = []
        _ens_cone = None
        if self._ensemble_engine and history and len(history) >= 3:
            try:
                _ens_prices = [h["p"] for h in history]
                _ens_timestamps = [h["t"] for h in history]
                _ens_k_state = {"velocity": vel_raw, "acceleration": acc_raw}
                _ens_atr = atr
                _ens_result = self._ensemble_engine.predict(
                    prices=_ens_prices,
                    timestamps=_ens_timestamps,
                    current_price=current,
                    kalman_state=_ens_k_state,
                    prediction_horizon=tf["prediction"],
                    prediction_step=pred_step,
                    atr=_ens_atr,
                )
                self._ensemble_result = _ens_result
                # Use ensemble path as primary prediction
                pred = [{"t": pt.t, "p": pt.p} for pt in _ens_result.ensemble_path]
                self._last_pred = pred
                # Store individual model paths for overlay
                _ens_kalman_path = [(pt.t, pt.p) for pt in _ens_result.kalman_path]
                _ens_linear_path = [(pt.t, pt.p) for pt in _ens_result.linear_path]
                _ens_poly_path = [(pt.t, pt.p) for pt in _ens_result.polynomial_path]
                _ens_cone = _ens_result.uncertainty_cone
            except Exception:
                self._ensemble_result = None
                # fallback: keep barrier-aware Kalman pred already computed
        else:
            self._ensemble_result = None

        # -- Dynamic x_range: prediction zone gets >= min_pred_pct of chart --
        pred_width = tf["prediction"]
        min_pct = tf.get("min_pred_pct", 0.20)
        x_range_from_pct = pred_width / min_pct          # max x_range for min visibility
        x_range_from_data = last_t + pred_width + 5       # must fit all data
        x_range_baseline = tf["x_range"]                  # config default
        # Use baseline unless it's too wide (compresses prediction below min_pct),
        # but never shrink below what data needs
        x_range = max(x_range_from_data, min(x_range_baseline, x_range_from_pct))

        # -- Compute Y-axis from DATA only (not prediction) -----------
        # Y-axis shows meaningful price levels; prediction clips if extreme
        key_prices = [current, entry, target, tcas]
        if plan_tgt:  key_prices.append(plan_tgt)
        if plan_sl:   key_prices.append(plan_sl)
        if bbU:       key_prices.append(bbU)
        if bbL:       key_prices.append(bbL)
        if pdh:       key_prices.append(pdh)
        if pdl:       key_prices.append(pdl)
        if sup:       key_prices.append(sup)
        if res:       key_prices.append(res)
        for h in history:
            key_prices.append(h["p"])
        key_prices = [p for p in key_prices if p > 0]
        if key_prices:
            y_lo = min(key_prices)
            y_hi = max(key_prices)
        else:
            y_lo, y_hi = current * 0.97, current * 1.03
        # Padding: dynamic per timeframe (min 0.5×ATR)
        y_span = y_hi - y_lo
        pad_pct = _Y_PAD_PCT.get(tf_key, 0.10)
        pad = max(y_span * pad_pct, atr * 0.5)
        y_lo -= pad
        y_hi += pad

        # -- AXIS STYLING --
        ax.tick_params(colors='#55555f', labelsize=7)
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        ax.spines['bottom'].set_color('#252530')
        ax.spines['left'].set_color('#252530')
        ax.margins(x=0.02, y=0.03)
        ax.yaxis.set_major_formatter(lambda x, p: f'\u20b9{x:.0f}')

        # -- Dynamic Y-axis grid (Fix 1) --
        y_range = y_hi - y_lo
        price_step = _get_price_step(tf_key, y_range)
        y_tick_lo = int(y_lo // price_step) * price_step
        y_ticks = []
        v = y_tick_lo
        while v <= y_hi + price_step:
            if y_lo <= v <= y_hi:
                y_ticks.append(v)
            v += price_step
        if y_ticks:
            ax.set_yticks(y_ticks)
        ax.grid(True, alpha=0.04, color='white', linewidth=0.5)

        ax.set_xlim(0, x_range)
        ax.set_ylim(y_lo, y_hi)

        # -- BB band shading --
        if bbU and bbL:
            ax.axhspan(bbL, bbU, color='#06b6d4', alpha=0.04)

        # -- Support / Resistance zones --
        if sup:
            ax.axhspan(sup - 5, sup + 3, color='#0a1a0e', alpha=0.5)
        if res:
            ax.axhspan(res - 3, res + 5, color='#1a0a0a', alpha=0.5)

        # -- Fibonacci levels (very subtle gold dotted) --
        fib_labels = {"fib236": "F23.6", "fib382": "F38.2", "fib50": "F50",
                      "fib618": "F61.8", "fib786": "F78.6"}
        for fk, fl in fib_labels.items():
            fv = fibs.get(fk, 0)
            if fv:
                ax.axhline(fv, color='#c8a032', alpha=0.12, linewidth=0.5,
                           linestyle=(0, (1, 4)))
                ax.text(2, fv, fl, fontsize=8, color='#c8a03233', va='bottom')

        # -- Level lines (draw all horizontal lines first) --
        rx = x_range * 0.99   # primary label x-pos (TGT / TCAS)
        sx = x_range * 0.70   # secondary label x-pos (SL / PDH / PDL)

        ax.axhline(target, color=GREEN, linewidth=1.2, alpha=0.9)
        ax.axhline(tcas, color=RED, linewidth=1.2, alpha=0.9)
        ax.axhline(plan_sl, color=RED, linewidth=0.6, linestyle='--', alpha=0.5)
        ax.axhline(entry, color='#777777', linewidth=0.6, linestyle='--', alpha=0.5)
        ax.axhline(ma20, color=CYAN, linewidth=0.6, linestyle=':', alpha=0.4)
        ax.axhline(ma50, color=PINK, linewidth=0.6, linestyle=':', alpha=0.4)
        if pdh:
            ax.axhline(pdh, color=PURPLE, linewidth=0.5, linestyle='--', alpha=0.5)
        if pdl:
            ax.axhline(pdl, color=PURPLE, linewidth=0.5, linestyle='--', alpha=0.5)
        if sup:
            ax.axhline(sup, color='#22c55e55', linewidth=0.4, linestyle='--')
        if res:
            ax.axhline(res, color='#ef444455', linewidth=0.4, linestyle='--')

        # -- Right-side labels (decluttered) --
        right_labels = []
        right_props = []

        right_labels.append({'y': target, 'fontsize': 10})
        right_props.append({'x': rx, 'text': f'\u25b6 TGT \u20b9{target:.0f}',
                            'fontsize': 10, 'fontweight': 'bold', 'color': GREEN,
                            'va': 'bottom', 'ha': 'right'})

        right_labels.append({'y': tcas, 'fontsize': 10})
        right_props.append({'x': rx, 'text': f'\u25b6 TCAS \u20b9{tcas:.0f}',
                            'fontsize': 10, 'fontweight': 'bold', 'color': RED,
                            'va': 'top', 'ha': 'right'})

        right_labels.append({'y': plan_sl, 'fontsize': 9})
        right_props.append({'x': sx, 'text': f'SL \u20b9{plan_sl:.0f}',
                            'fontsize': 9, 'color': '#ef444488',
                            'va': 'top', 'ha': 'right'})

        if pdh:
            right_labels.append({'y': pdh, 'fontsize': 9})
            right_props.append({'x': sx, 'text': f'PDH \u20b9{pdh}',
                                'fontsize': 9, 'color': PURPLE,
                                'va': 'bottom', 'ha': 'right', 'alpha': 0.7})
        if pdl:
            right_labels.append({'y': pdl, 'fontsize': 9})
            right_props.append({'x': sx, 'text': f'PDL \u20b9{pdl}',
                                'fontsize': 9, 'color': PURPLE,
                                'va': 'top', 'ha': 'right', 'alpha': 0.7})

        adj_right = self._declutter_labels(right_labels, ax, min_gap_px=14)
        for i, props in enumerate(right_props):
            kw = {k: v for k, v in props.items() if k not in ('x', 'text')}
            ax.text(props['x'], adj_right[i], props['text'], **kw)

        # -- Left-side labels (decluttered) --
        left_labels = []
        left_props = []

        left_labels.append({'y': entry, 'fontsize': 9})
        left_props.append({'x': 3, 'text': f'ENTRY \u20b9{entry:.0f}',
                           'fontsize': 9, 'color': '#777777', 'va': 'top'})

        left_labels.append({'y': ma20, 'fontsize': 8})
        left_props.append({'x': 3, 'text': 'MA20',
                           'fontsize': 8, 'color': CYAN, 'va': 'bottom', 'alpha': 0.5})

        left_labels.append({'y': ma50, 'fontsize': 8})
        left_props.append({'x': 3, 'text': 'MA50',
                           'fontsize': 8, 'color': PINK, 'va': 'bottom', 'alpha': 0.5})

        if sup:
            left_labels.append({'y': sup, 'fontsize': 8})
            left_props.append({'x': 3, 'text': 'S',
                               'fontsize': 8, 'color': '#22c55e33', 'va': 'bottom'})
        if res:
            left_labels.append({'y': res, 'fontsize': 8})
            left_props.append({'x': 3, 'text': 'R',
                               'fontsize': 8, 'color': '#ef444433', 'va': 'bottom'})

        adj_left = self._declutter_labels(left_labels, ax, min_gap_px=14)
        for i, props in enumerate(left_props):
            kw = {k: v for k, v in props.items() if k not in ('x', 'text')}
            ax.text(props['x'], adj_left[i], props['text'], **kw)

        # -- NOW vertical line --
        ax.axvline(last_t, color='#ffffff', linewidth=0.5, linestyle='--', alpha=0.07)
        ax.text(last_t, ax.get_ylim()[0], '\u25bc NOW', fontsize=11,
                fontweight='bold', color=AMBER, ha='center', va='bottom')

        # Prediction zone tint
        ax.axvspan(last_t, x_range, color='#0a1a0a', alpha=0.08)

        # -- PATH 1: Planned path (dashed white) --
        ax.plot([0, x_range], [entry, plan_tgt],
                color='white', linewidth=0.8, linestyle='--', alpha=0.2)

        # -- PATH 2: Actual path (solid cyan with glow) --
        if len(history) >= 2:
            ht = [h["t"] for h in history]
            hp = [h["p"] for h in history]
            ax.plot(ht, hp, color='#06b6d4', linewidth=5, alpha=0.15)  # glow
            ax.plot(ht, hp, color=CYAN, linewidth=2.5, alpha=0.95)     # main

        # -- PATH 3: Kalman predicted (green dotted + cone) --
        if pred:
            pred_t = [last_t + pt["t"] for pt in pred]
            pred_p = [pt["p"] for pt in pred]

            # Prediction cone — prefer ensemble uncertainty_cone if available
            cone_upper = []
            cone_lower = []
            if _ens_cone:
                # Ensemble cone (based on model disagreement + ATR — smarter)
                for b in _ens_cone:
                    cone_upper.append(b.upper)
                    cone_lower.append(b.lower)
                cone_t = [last_t + b.t for b in _ens_cone]
            else:
                # Fallback: ATR-based cone (unit-aware)
                cone_t = pred_t
                for pt in pred:
                    if tf["kalman_scale"] == "daily":
                        t_units = pt["t"] / MINS_PER_TDAY
                    elif tf["kalman_scale"] == "hourly":
                        t_units = pt["t"] / MINS_PER_HOUR
                    else:
                        t_units = pt["t"]
                    spread = atr * tf["cone_factor"] * math.sqrt(t_units + 1)
                    cone_upper.append(pt["p"] + spread)
                    cone_lower.append(pt["p"] - spread)
            if cone_upper and cone_lower:
                ax.fill_between(cone_t, cone_lower, cone_upper,
                                color=PREDICTED, alpha=0.02)
                ax.plot(cone_t, cone_upper, color=PREDICTED, linewidth=0.7,
                        linestyle='--', alpha=0.25)
                ax.plot(cone_t, cone_lower, color=PREDICTED, linewidth=0.7,
                        linestyle='--', alpha=0.25)

            # Predicted line (solid + glow) — ensemble when available, else Kalman
            ax.plot(pred_t, pred_p, color=PREDICTED, linewidth=4, alpha=0.12)  # glow
            ax.plot(pred_t, pred_p, color=PREDICTED, linewidth=2, alpha=0.75)  # main

            # ── Individual model overlays (faint dotted, for comparison) ─────
            if _ens_kalman_path:
                _ek_t = [last_t + pt[0] for pt in _ens_kalman_path]
                _ek_p = [pt[1] for pt in _ens_kalman_path]
                ax.plot(_ek_t, _ek_p, color='#06b6d4', linewidth=0.8,
                        linestyle=':', alpha=0.4, zorder=4)
            if _ens_linear_path:
                _el_t = [last_t + pt[0] for pt in _ens_linear_path]
                _el_p = [pt[1] for pt in _ens_linear_path]
                ax.plot(_el_t, _el_p, color='#ffffff', linewidth=0.8,
                        linestyle=':', alpha=0.3, zorder=4)
            if _ens_poly_path:
                _ep_t = [last_t + pt[0] for pt in _ens_poly_path]
                _ep_p = [pt[1] for pt in _ens_poly_path]
                ax.plot(_ep_t, _ep_p, color='#f59e0b', linewidth=0.8,
                        linestyle=':', alpha=0.3, zorder=4)

            # -- Historical predictions overlay (faded amber dotted) --
            if self._show_history and self._history_predictions:
                for hist_idx, hist_pred in enumerate(self._history_predictions):
                    if not hist_pred:
                        continue
                    h_pred_t = [last_t + pt["t"] for pt in hist_pred]
                    h_pred_p = [pt["p"] for pt in hist_pred]
                    h_alpha = max(0.08, 0.30 - hist_idx * 0.04)
                    ax.plot(h_pred_t, h_pred_p, color=HISTORY_PRED,
                            linewidth=1.2, linestyle=':', alpha=h_alpha,
                            zorder=3)
                    if h_pred_t:
                        ax.text(h_pred_t[-1], h_pred_p[-1],
                                f' #{hist_idx+1}', fontsize=6,
                                color=HISTORY_PRED, alpha=h_alpha + 0.1,
                                ha='left', va='center')

            # -- Predicted price annotations (along the green line) --
            label_interval = _PRED_LABEL_INTERVAL.get(tf_key, 4)
            prev_label_y = None
            # min pixel gap in price units (prevent overlap)
            y_range_now = y_hi - y_lo
            min_price_gap = y_range_now * 0.025  # ~2.5% of visible range

            for i_ann in range(label_interval, len(pred), label_interval):
                pt_ann = pred[i_ann]
                ann_x = last_t + pt_ann["t"]
                ann_y = pt_ann["p"]

                # skip if too close to previous label
                if prev_label_y is not None:
                    if abs(ann_y - prev_label_y) < min_price_gap:
                        continue

                fade_alpha = max(0.4, 1.0 - i_ann / len(pred) * 0.6)
                ax.annotate(
                    f'\u20b9{ann_y:.0f}',
                    xy=(ann_x, ann_y),
                    xytext=(0, 8), textcoords='offset points',
                    fontsize=8, color=PREDICTED, fontweight='bold',
                    ha='center', va='bottom', alpha=fade_alpha,
                    bbox=dict(boxstyle='round,pad=0.15',
                              facecolor='#08080d', edgecolor=PREDICTED,
                              alpha=0.7, linewidth=0.5))
                # small dot on the prediction line
                ax.plot(ann_x, ann_y, 'o', color=PREDICTED,
                        markersize=3, alpha=0.6, zorder=6)
                prev_label_y = ann_y

            # -- Final predicted price (endpoint) --
            if pred:
                final_t = pred_t[-1]
                final_p = pred_p[-1]
                ax.annotate(
                    f'\u20b9{final_p:.0f}',
                    xy=(final_t, final_p),
                    xytext=(8, 0), textcoords='offset points',
                    fontsize=10, color=PREDICTED, fontweight='bold',
                    ha='left', va='center',
                    bbox=dict(boxstyle='round,pad=0.2',
                              facecolor='#08080d', edgecolor=PREDICTED,
                              alpha=0.85, linewidth=1))
                ax.plot(final_t, final_p, 'D', color=PREDICTED,
                        markersize=6, zorder=7)

            # -- Prediction time labels along X-axis --
            x_mode = tf.get("x_label", "minutes")
            if x_mode == "days" and pred:
                day_step = MINS_PER_TDAY
                t_val = day_step
                d_count = 1
                while t_val < pred[-1]["t"]:
                    # find closest prediction point for Y position
                    cl = min(pred, key=lambda pt: abs(pt["t"] - t_val))
                    tx = last_t + cl["t"]
                    ax.annotate(f'+{d_count}D',
                                xy=(tx, y_lo),
                                xytext=(0, 6), textcoords='offset points',
                                fontsize=7, color='#55555f',
                                ha='center', va='bottom', alpha=0.7)
                    t_val += day_step
                    d_count += 1
            elif x_mode != "days" and pred and len(pred) > 4:
                # intraday: label midpoint and endpoint
                for idx_lbl in [len(pred) // 2, len(pred) - 1]:
                    t_min = pred[idx_lbl]["t"]
                    if t_min >= 60:
                        t_label = f'+{t_min / 60:.0f}h'
                    else:
                        t_label = f'+{t_min:.0f}m'
                    tx = last_t + t_min
                    ax.annotate(t_label,
                                xy=(tx, y_lo),
                                xytext=(0, 6), textcoords='offset points',
                                fontsize=7, color='#55555f',
                                ha='center', va='bottom', alpha=0.7)

        # -- ETA marker (with linear interpolation) --
        eta_t = None
        for i_pt, pt in enumerate(pred):
            if pt["p"] >= target:
                if i_pt == 0:
                    eta_t = pt["t"]
                else:
                    p0, p1 = pred[i_pt - 1]["p"], pt["p"]
                    t0, t1 = pred[i_pt - 1]["t"], pt["t"]
                    frac = (target - p0) / (p1 - p0) if p1 != p0 else 0
                    eta_t = t0 + frac * (t1 - t0)
                break
        if eta_t is not None:
            mx = last_t + eta_t
            ax.plot(mx, target, marker='*', markersize=12, color=GREEN, zorder=5)
            ax.annotate(f'\u2726 ETA ~{eta_t:.0f}m',
                        xy=(mx, target), xytext=(0, 10),
                        textcoords='offset points',
                        fontsize=10, fontweight='bold',
                        color=GREEN, ha='center', va='bottom')
            ax.axvline(mx, color=GREEN, linewidth=0.5, linestyle=':', alpha=0.2)
        else:
            ax.text(x_range * 0.70, target,
                    'ETA: beyond \u2192', fontsize=9, color=AMBER,
                    ha='right', va='top')

        # -- TCAS warning for declining stocks (with linear interpolation) --
        if vel < 0:
            tcas_hit_t = None
            for i_pt, pt in enumerate(pred):
                if pt["p"] <= tcas:
                    if i_pt == 0:
                        tcas_hit_t = pt["t"]
                    else:
                        p0, p1 = pred[i_pt - 1]["p"], pt["p"]
                        t0, t1 = pred[i_pt - 1]["t"], pt["t"]
                        frac = (tcas - p0) / (p1 - p0) if p1 != p0 else 0
                        tcas_hit_t = t0 + frac * (t1 - t0)
                    break
            if tcas_hit_t is not None:
                mx = last_t + tcas_hit_t
                ax.plot(mx, tcas, marker='v', markersize=10, color=RED, zorder=5)
                ax.annotate(f'\u26a0 TCAS ~{tcas_hit_t:.0f}m',
                            xy=(mx, tcas), xytext=(0, -10),
                            textcoords='offset points',
                            fontsize=10, fontweight='bold',
                            color=RED, ha='center', va='top')

        # -- Entry marker --
        ax.plot(0, entry, marker='*', markersize=14, color='white', zorder=5)
        ax.annotate(f'ENTRY \u20b9{entry}\n{pos.get("entry_time", "")}',
                    xy=(0, entry), xytext=(6, -6),
                    textcoords='offset points',
                    fontsize=10, color='#888888', va='top', ha='left')

        # -- Target diamond --
        ax.plot(x_range * 0.96, target, marker='D', markersize=8,
                color=GREEN, zorder=5)

        # -- Current position aircraft + price box --
        ax.plot(last_t, current, marker='$\u2708$', markersize=16,
                color='white', zorder=6)
        pnl = pos.get("pnl_pct", 0)
        pc = GREEN if pnl >= 0 else RED
        ax.annotate(f'\u20b9{current:.1f}',
                    xy=(last_t, current), xytext=(0, 12),
                    textcoords='offset points',
                    fontsize=11, fontweight='bold', color=pc,
                    ha='center', va='bottom',
                    bbox=dict(boxstyle='round,pad=0.3', facecolor='#08080d',
                              edgecolor=pc, alpha=0.9))

        # TCAS circle
        ax.plot(x_range * 0.96, tcas, marker='o', markersize=6,
                color=RED, zorder=5)

        # -- Traffic (other stocks) --
        others = [s for s in self._all_pos if s["symbol"] != pos["symbol"]]
        for i, st in enumerate(others):
            ylim = ax.get_ylim()
            if ylim[0] < st["current"] < ylim[1]:
                ax.plot(5 + i * 8, st["current"], marker='$\u2708$',
                        markersize=8, color=TEXT_DIM, zorder=4)
                sp = st.get("pnl_pct", 0)
                ax.text(14 + i * 8, st["current"],
                        f'{st["symbol"][:6]} ({sp:+.1f}%)',
                        fontsize=11, color=TEXT_DIM, va='center')

        # -- Title + status --
        et = pos.get('entry_time', '')
        ct = pos.get('current_time', '')
        tt = pos.get('trade_type', '')
        ax.text(0.01, 0.98, f'NAV \u2014 {pos["symbol"]} ({et}\u2192{ct}) {tt}',
                transform=ax.transAxes, fontsize=11, fontweight='bold',
                color=TEXT_MUTED, va='top', ha='left')
        sc = GREEN if pos.get("status") == "ON TRACK" else AMBER
        ax.text(0.99, 0.98, pos.get("status", ""),
                transform=ax.transAxes, fontsize=11, fontweight='bold',
                color=sc, va='top', ha='right')

        # -- Bottom annotations --
        plan = pos.get("plan", {})
        pnl_abs = pos.get("pnl_abs", 0)
        pnl_pct = pos.get("pnl_pct", 0)
        plan_pnl = plan.get("pnl_target", 0)
        plan_rr = plan.get("rr", 0)
        plc = GREEN if pnl_pct >= 0 else RED
        ax.text(0.01, 0.02,
                f'P&L: {pnl_pct:+.2f}% (\u20b9{pnl_abs:+d})',
                transform=ax.transAxes, fontsize=10, fontweight='bold',
                color=plc, va='bottom', ha='left')
        ax.text(0.5, 0.02,
                f'Plan: +{plan_pnl}% R:R {plan_rr}',
                transform=ax.transAxes, fontsize=10, fontweight='bold',
                color=TEXT_LABEL, va='bottom', ha='center')
        eta_m = pos.get("eta_minutes")
        if self._ensemble_result:
            _er = self._ensemble_result
            _regime_c = GREEN if _er.regime == 'TRENDING' else AMBER if _er.regime == 'RANDOM_WALK' else RED
            ax.text(0.99, 0.02,
                    f'H:{_er.hurst:.2f} ({_er.regime})  Conf:{_er.confidence:.0%}',
                    transform=ax.transAxes, fontsize=9, fontweight='bold',
                    color=_regime_c, va='bottom', ha='right')
            # Show weights on second line
            _wk = _er.weights.get('kalman', 0)
            _wl = _er.weights.get('linear', 0)
            _wp = _er.weights.get('polynomial', 0)
            ax.text(0.99, 0.06,
                    f'W: K{_wk:.0%} L{_wl:.0%} P{_wp:.0%}',
                    transform=ax.transAxes, fontsize=8,
                    color=TEXT_DIM, va='bottom', ha='right')
        else:
            ax.text(0.99, 0.02,
                    f'Kalman ETA ~{eta_m}m' if eta_m else 'ETA: calc...',
                    transform=ax.transAxes, fontsize=10, fontweight='bold',
                    color=AMBER, va='bottom', ha='right')

        # Extended timeframe disclaimer
        if is_ext:
            scale_label = tf["kalman_scale"]
            unit = "day" if scale_label == "daily" else "hr"
            ax.text(0.01, 0.06,
                    f'\u26a0 Extended: {scale_label} Kalman (\u20b9{abs(vel_raw):.1f}/{unit})',
                    transform=ax.transAxes, fontsize=10, color=TEXT_DIM,
                    va='bottom', ha='left')

        # -- Legend (horizontal row at top) --
        legend_items = [
            ('\u2501 Actual', CYAN),
        ]
        if self._ensemble_result:
            legend_items.append(('\u2501 Ensemble', PREDICTED))
            legend_items.append(('\u00b7\u00b7 Kalman', '#06b6d4'))
            legend_items.append(('\u00b7\u00b7 LinReg', '#ffffff55'))
            legend_items.append(('\u00b7\u00b7 Poly', '#f59e0b'))
        else:
            legend_items.append(('\u2505 Pred', PREDICTED))
        legend_items += [
            ('-- Plan', '#ffffff55'),
            ('TGT', GREEN),
            ('TCAS', RED),
        ]
        if self._show_history:
            legend_items.append(('\u2505 Hist', HISTORY_PRED))
        _leg_step = min(0.155, 0.95 / max(len(legend_items), 1))
        for i, (txt, cl) in enumerate(legend_items):
            ax.text(0.01 + i * _leg_step, 0.97, txt,
                    transform=ax.transAxes, fontsize=7, color=cl,
                    va='top', ha='left', alpha=0.7)

        # -- X-axis time labels --
        t_step = tf["grid_step"] if tf["grid_step"] > 0 else 10
        x_mode = tf.get("x_label", "minutes")
        xticks = []
        xlabels = []
        t = 0
        while t <= x_range:
            xticks.append(t)
            if x_mode == "days":
                # Multi-day: show "D1", "D2", … (trading day boundaries)
                day_num = int(t / MINS_PER_TDAY) + 1
                xlabels.append(f"D{day_num}")
            elif x_mode == "clock":
                # Intraday clock: 09:22 + t minutes
                tm = 9 * 60 + 22 + t
                xlabels.append(f"{tm // 60 % 24:02d}:{tm % 60:02d}")
            else:
                # Short timeframes: raw minutes
                xlabels.append(f"{t}m")
            t += t_step
        ax.set_xticks(xticks)
        ax.set_xticklabels(xlabels, fontsize=10, color='#55555f')

        self._mpl_canvas.draw_idle()

    # -- Public API --------------------------------------------------------
    def update_data(self, pos, all_positions=None, timeframe="1hr",
                    show_history=False, history_predictions=None):
        self._pos = pos
        self._all_pos = all_positions or []
        self._timeframe = timeframe
        self._show_history = show_history
        self._history_predictions = history_predictions or []
        self._render()

# ==========================================================================
#  PH5 DETAIL -- GAP STRATEGY
# ==========================================================================

class PH5Detail(ctk.CTkFrame):

    def __init__(self, parent, on_back, data_bridge=None):
        super().__init__(parent, fg_color="transparent")
        self._on_back = on_back
        self._data_bridge = data_bridge
        self._data = PH5_MOCK.copy()
        self._data_fingerprint = ""
        self._chart_canvas = None          # matplotlib FigureCanvasTkAgg ref
        self._build()

        if self._data_bridge:
            self._data_bridge.register_callback(self, self._on_live_data)
            self.after(500, self._try_live)

    # ── fingerprint — skip rebuild when data is unchanged ─────────
    @staticmethod
    def _fingerprint(d: dict) -> str:
        trades = tuple(t.get("symbol", "") for t in d.get("today_trades", []))
        perf = d.get("performance", {})
        return (f"{d.get('status')}|{d.get('trades_today_count')}|"
                f"{d.get('pnl_today')}|{trades}|{perf.get('total_trades')}")

    def _try_live(self):
        if self._data_bridge:
            try:
                ph5 = self._data_bridge.get_ph5_data_v2()
                if ph5 and ph5.get("source") == "ph5_v2":
                    fp = self._fingerprint(ph5)
                    if fp != self._data_fingerprint:
                        self._data = ph5
                        self._data_fingerprint = fp
                        self._refresh_display()
            except Exception:
                pass

    def _on_live_data(self, live):
        try:
            ph5 = self._data_bridge.get_ph5_data_v2()
            if ph5 and ph5.get("source") == "ph5_v2":
                fp = self._fingerprint(ph5)
                if fp != self._data_fingerprint:
                    self._data = ph5
                    self._data_fingerprint = fp
                    self._refresh_display()
        except Exception:
            pass

    def _refresh_display(self):
        if self._chart_canvas:
            try:
                self._chart_canvas.get_tk_widget().destroy()
            except Exception:
                pass
            self._chart_canvas = None
        for w in self.winfo_children():
            w.destroy()
        self._build()

    # ══════════════════════════════════════════════════════════════
    #  BUILD — 3-row × 2-column grid + status bar
    # ══════════════════════════════════════════════════════════════
    def _build(self):
        d = self._data

        _back_button(self, self._on_back).pack(anchor="w", padx=8, pady=(4, 4))
        _title_bar(self, "PH5 . GAP STRATEGY -- FLIGHT STATUS").pack(
            fill="x", padx=8, pady=(0, 4))

        content = ctk.CTkFrame(self, fg_color="transparent")
        content.pack(fill="both", expand=True, padx=8, pady=(0, 4))
        content.columnconfigure(0, weight=2)
        content.columnconfigure(1, weight=3)
        content.rowconfigure(0, weight=1)
        content.rowconfigure(1, weight=1)
        content.rowconfigure(2, weight=1)

        self._build_scanner_status(content, d)
        self._build_today_trades(content, d)
        self._build_config_panel(content, d)
        self._build_historical_table(content, d)
        self._build_performance_gauges(content, d)
        self._build_pnl_chart(content, d)
        self._build_status_bar(d)

    # ── Row 0, Col 0 : GAP SCANNER STATUS ─────────────────────────
    def _build_scanner_status(self, parent, d):
        panel = _instrument_panel(parent, "GAP SCANNER STATUS")
        panel.grid(row=0, column=0, sticky="nsew", padx=(0, 4), pady=(0, 2))

        gauge_row = ctk.CTkFrame(panel, fg_color="transparent")
        gauge_row.pack(fill="x", padx=4, pady=(6, 2))

        window_val = 0 if d.get("status") in ("CLOSED", "WINDOW CLOSED") else 80
        AviationGauge(gauge_row, "Window", window_val, 0, 100, "%",
                      zones=[(0, 30, "red"), (30, 70, "amber"), (70, 100, "green")],
                      canvas_bg=BG_PANEL, width=110, height=85).pack(side="left", padx=2)

        AviationGauge(gauge_row, "Candidates", d.get("candidates_today", 0), 0, 10, "",
                      zones=[(0, 100, "green")],
                      canvas_bg=BG_PANEL, width=110, height=85).pack(side="left", padx=2)

        pnl = d.get("pnl_today", 0)
        pnl_gv = max(0, min(100, int((pnl + 500) / 1000 * 100)))
        AviationGauge(gauge_row, "P&L Today", pnl_gv, 0, 100, "",
                      zones=[(0, 40, "red"), (40, 55, "amber"), (55, 100, "green")],
                      canvas_bg=BG_PANEL, width=110, height=85).pack(side="left", padx=2)

        info = ctk.CTkFrame(panel, fg_color=BG_INPUT, corner_radius=6)
        info.pack(fill="x", padx=10, pady=(2, 6))

        sc = GREEN if d.get("status") == "ACTIVE" else AMBER
        _stat_row(info, "Status", d.get("status", "CLOSED"), sc)
        _stat_row(info, "Window", f"{d.get('window_start', '09:15')} -- {d.get('window_end', '09:50')}")
        _stat_row(info, "Scan Window", d.get("scan_window", "09:18 -- 09:20"))
        _stat_row(info, "Entry Window", d.get("entry_window", "09:20 -- 09:25"))
        _stat_row(info, "Universe", f"{d.get('universe_size', 0)} stocks")
        _stat_row(info, "Trades Today", str(d.get("trades_today_count", 0)), CYAN)
        pc = GREEN if pnl > 0 else RED if pnl < 0 else TEXT_LABEL
        _stat_row(info, "P&L Today", f"Rs.{pnl:+.2f}", pc)
        _stat_row(info, "Next Run", d.get("next_run", "--"), TEXT_LABEL)

    # ── Row 0, Col 1 : TODAY'S GAP TRADES / MISSION LOG ───────────
    def _build_today_trades(self, parent, d):
        trades = d.get("today_trades", [])
        if trades:
            panel = _instrument_panel(parent, "TODAY'S GAP TRADES")
        else:
            panel = _instrument_panel(parent, "MISSION LOG")
        panel.grid(row=0, column=1, sticky="nsew", padx=(4, 0), pady=(0, 2))

        if not trades:
            log_frame = ctk.CTkScrollableFrame(panel, fg_color=BG_INPUT,
                                               scrollbar_button_color=BORDER_DIM)
            log_frame.pack(fill="both", expand=True, padx=6, pady=(4, 6))
            for ts, msg, tag in d.get("mission_log", []):
                _log_entry(log_frame, ts, msg, tag)
            return

        cols = [("SYMBOL", 80), ("DIR", 40), ("ENTRY", 60), ("EXIT", 60),
                ("QTY", 40), ("P&L", 65), ("DUR", 40), ("REASON", 90)]
        hdr = ctk.CTkFrame(panel, fg_color=BG_HEADER, corner_radius=0, height=26)
        hdr.pack(fill="x", padx=6, pady=(6, 0))
        hdr.pack_propagate(False)
        for txt, w in cols:
            ctk.CTkLabel(hdr, text=txt, font=FONT_TINY_BOLD,
                         text_color=TEXT_MUTED, width=w, anchor="w").pack(
                             side="left", padx=2)

        for t in trades:
            row = ctk.CTkFrame(panel, fg_color=BG_INPUT, corner_radius=4, height=28)
            row.pack(fill="x", padx=6, pady=1)
            row.pack_propagate(False)
            ctk.CTkLabel(row, text=t.get("symbol", ""),
                         font=FONT_TINY_BOLD,
                         text_color=TEXT_PRIMARY, width=80, anchor="w").pack(side="left", padx=2)
            dc = GREEN if t.get("direction") == "BUY" else RED
            ctk.CTkLabel(row, text=t.get("direction", "")[:3],
                         font=FONT_TINY_BOLD,
                         text_color=dc, width=40, anchor="w").pack(side="left", padx=2)
            ctk.CTkLabel(row, text=f"{t.get('entry_price', 0):.0f}",
                         font=FONT_TINY,
                         text_color=TEXT_LABEL, width=60, anchor="w").pack(side="left", padx=2)
            ep = t.get("exit_price")
            ctk.CTkLabel(row, text=f"{ep:.0f}" if ep else "--",
                         font=FONT_TINY,
                         text_color=TEXT_LABEL, width=60, anchor="w").pack(side="left", padx=2)
            ctk.CTkLabel(row, text=str(t.get("entry_qty", 0)),
                         font=FONT_TINY,
                         text_color=TEXT_DIM, width=40, anchor="w").pack(side="left", padx=2)
            pv = t.get("pnl_net", 0)
            pvc = GREEN if pv > 0 else RED if pv < 0 else TEXT_DIM
            ctk.CTkLabel(row, text=f"{pv:+.1f}" if pv else "--",
                         font=FONT_TINY_BOLD,
                         text_color=pvc, width=65, anchor="w").pack(side="left", padx=2)
            ctk.CTkLabel(row, text=f"{t.get('hold_duration_min', 0)}m",
                         font=FONT_TINY,
                         text_color=TEXT_DIM, width=40, anchor="w").pack(side="left", padx=2)
            ctk.CTkLabel(row, text=(t.get("exit_reason", "")[:14]),
                         font=FONT_TINY,
                         text_color=TEXT_DIM, width=90, anchor="w").pack(side="left", padx=2)

    # ── Row 1, Col 0 : GAP STRATEGY CONFIG ────────────────────────
    def _build_config_panel(self, parent, d):
        panel = _instrument_panel(parent, "GAP STRATEGY CONFIG")
        panel.grid(row=1, column=0, sticky="nsew", padx=(0, 4), pady=(2, 2))

        cfg = d.get("config", {})
        info = ctk.CTkFrame(panel, fg_color=BG_INPUT, corner_radius=6)
        info.pack(fill="x", padx=10, pady=(6, 4))

        _stat_row(info, "Gap P1 (Strong)", f"{cfg.get('gap_p1', 1.5)}%", CYAN)
        _stat_row(info, "Gap P2 (Moderate)", f"{cfg.get('gap_p2', 1.0)}%", CYAN)
        _stat_row(info, "Gap P3 (Weak)", f"{cfg.get('gap_p3', 0.75)}%", CYAN)

        ctk.CTkFrame(info, fg_color=BORDER_DIM, height=1).pack(fill="x", padx=6, pady=3)

        _stat_row(info, "Min Volume Ratio", f"{cfg.get('min_volume_ratio', 1.0)}x")
        _stat_row(info, "Max ADX", str(cfg.get("max_adx", 25)))
        _stat_row(info, "Price Range",
                  f"Rs.{cfg.get('min_price', 800)} - Rs.{cfg.get('max_price', 3000)}")

        ctk.CTkFrame(info, fg_color=BORDER_DIM, height=1).pack(fill="x", padx=6, pady=3)

        _stat_row(info, "Max Trades/Day", str(cfg.get("max_trades_day", 1)))
        _stat_row(info, "Position Size", f"{cfg.get('pos_size_pct', 5.0)}% of capital")
        _stat_row(info, "Value Range",
                  f"Rs.{cfg.get('min_pos_value', 5000)} - Rs.{cfg.get('max_pos_value', 10000)}")

        ctk.CTkFrame(info, fg_color=BORDER_DIM, height=1).pack(fill="x", padx=6, pady=3)

        _stat_row(info, "Gap Down + Bullish", "BUY", GREEN)
        _stat_row(info, "Gap Up + Bearish", "SELL", RED)
        _stat_row(info, "Misaligned", "SKIP", AMBER)

    # ── Row 1, Col 1 : HISTORICAL TRADES ──────────────────────────
    def _build_historical_table(self, parent, d):
        panel = _instrument_panel(parent, "HISTORICAL TRADES (LAST 30)")
        panel.grid(row=1, column=1, sticky="nsew", padx=(4, 0), pady=(2, 2))

        trades = d.get("historical_trades", [])
        if not trades:
            ctk.CTkLabel(panel, text="No historical PH5 trades found",
                         font=FONT_SMALL,
                         text_color=TEXT_DIM).pack(pady=20)
            return

        cols = [("DATE", 65), ("SYM", 75), ("DIR", 35), ("ENTRY", 55),
                ("EXIT", 55), ("P&L", 55), ("DUR", 35), ("MFE", 45),
                ("MAE", 45), ("REASON", 75)]
        hdr = ctk.CTkFrame(panel, fg_color=BG_HEADER, corner_radius=0, height=26)
        hdr.pack(fill="x", padx=6, pady=(6, 0))
        hdr.pack_propagate(False)
        for txt, w in cols:
            ctk.CTkLabel(hdr, text=txt, font=FONT_TINY_BOLD,
                         text_color=TEXT_MUTED, width=w, anchor="w").pack(
                             side="left", padx=1)

        scroll = ctk.CTkScrollableFrame(panel, fg_color="transparent",
                                        scrollbar_button_color=BORDER_DIM, height=120)
        scroll.pack(fill="both", expand=True, padx=6, pady=(0, 4))

        for t in trades:
            row = ctk.CTkFrame(scroll, fg_color="transparent", height=24)
            row.pack(fill="x", pady=1)
            row.pack_propagate(False)

            dt = t.get("date", "")
            ctk.CTkLabel(row, text=dt[5:] if len(dt) >= 10 else dt,
                         font=FONT_TINY,
                         text_color=TEXT_DIM, width=65, anchor="w").pack(side="left", padx=1)
            ctk.CTkLabel(row, text=t.get("symbol", "")[:8],
                         font=FONT_TINY_BOLD,
                         text_color=TEXT_PRIMARY, width=75, anchor="w").pack(side="left", padx=1)
            dc = GREEN if t.get("direction") == "BUY" else RED
            ctk.CTkLabel(row, text=(t.get("direction", ""))[:3],
                         font=FONT_TINY_BOLD,
                         text_color=dc, width=35, anchor="w").pack(side="left", padx=1)
            ctk.CTkLabel(row, text=f"{t.get('entry_price', 0):.0f}",
                         font=FONT_TINY,
                         text_color=TEXT_LABEL, width=55, anchor="w").pack(side="left", padx=1)
            ep = t.get("exit_price")
            ctk.CTkLabel(row, text=f"{ep:.0f}" if ep else "--",
                         font=FONT_TINY,
                         text_color=TEXT_LABEL, width=55, anchor="w").pack(side="left", padx=1)
            pv = t.get("pnl_net", 0)
            pvc = GREEN if pv > 0 else RED if pv < 0 else TEXT_DIM
            ctk.CTkLabel(row, text=f"{pv:+.0f}" if pv else "--",
                         font=FONT_TINY_BOLD,
                         text_color=pvc, width=55, anchor="w").pack(side="left", padx=1)
            ctk.CTkLabel(row, text=f"{t.get('hold_duration_min', 0)}m",
                         font=FONT_TINY,
                         text_color=TEXT_DIM, width=35, anchor="w").pack(side="left", padx=1)
            mfe = t.get("max_favorable", 0)
            ctk.CTkLabel(row, text=f"+{mfe:.0f}" if mfe else "--",
                         font=FONT_TINY,
                         text_color=GREEN, width=45, anchor="w").pack(side="left", padx=1)
            mae = t.get("max_adverse", 0)
            ctk.CTkLabel(row, text=f"-{abs(mae):.0f}" if mae else "--",
                         font=FONT_TINY,
                         text_color=RED, width=45, anchor="w").pack(side="left", padx=1)
            ctk.CTkLabel(row, text=(t.get("exit_reason", "") or "")[:12],
                         font=FONT_TINY,
                         text_color=TEXT_DIM, width=75, anchor="w").pack(side="left", padx=1)

    # ── Row 2, Col 0 : PERFORMANCE METRICS ────────────────────────
    def _build_performance_gauges(self, parent, d):
        panel = _instrument_panel(parent, "PERFORMANCE METRICS")
        panel.grid(row=2, column=0, sticky="nsew", padx=(0, 4), pady=(2, 0))

        perf = d.get("performance", {})
        wr = perf.get("win_rate", 0)
        avg_pnl = perf.get("avg_pnl", 0)
        avg_dur = perf.get("avg_duration_min", 0)
        pf = perf.get("profit_factor", 0)

        pnl_gv = max(0, min(100, int((avg_pnl + 50) / 100 * 100)))
        dur_gv = max(0, min(100, int(avg_dur / 60 * 100)))
        pf_gv = max(0, min(100, int(pf / 5 * 100)))

        gauges = [
            ("WIN RATE", int(wr),
             f"{perf.get('wins', 0)}/{perf.get('total_trades', 0)}",
             [(0, 30, "red"), (30, 50, "amber"), (50, 100, "green")]),
            ("AVG P&L", pnl_gv,
             f"Rs.{avg_pnl:+.1f}",
             [(0, 40, "red"), (40, 55, "amber"), (55, 100, "green")]),
            ("AVG HOLD", dur_gv,
             f"{avg_dur:.0f} min",
             [(0, 100, "green")]),
            ("PROFIT F.", pf_gv,
             f"{pf:.1f}x",
             [(0, 30, "red"), (30, 50, "amber"), (50, 100, "green")]),
        ]

        gf = ctk.CTkFrame(panel, fg_color="transparent")
        gf.pack(fill="both", expand=True, padx=4, pady=(4, 4))
        gf.columnconfigure(0, weight=1)
        gf.columnconfigure(1, weight=1)

        for idx, (name, pct, sub, zones) in enumerate(gauges):
            r, c = divmod(idx, 2)
            cell = ctk.CTkFrame(gf, fg_color="transparent")
            cell.grid(row=r, column=c, sticky="nsew", padx=2, pady=2)
            AviationGauge(cell, name, pct, 0, 100, "%",
                          zones=zones, canvas_bg=BG_PANEL,
                          width=110, height=80).pack(pady=(2, 0))
            clr = GREEN if pct >= 50 else AMBER if pct >= 30 else RED
            ctk.CTkLabel(cell, text=sub,
                         font=FONT_TINY_BOLD,
                         text_color=clr).pack()

    # ── Row 2, Col 1 : P&L TREND CHART ───────────────────────────
    def _build_pnl_chart(self, parent, d):
        panel = _instrument_panel(parent, "PH5 DAILY P&L TREND")
        panel.grid(row=2, column=1, sticky="nsew", padx=(4, 0), pady=(2, 0))

        series = d.get("daily_pnl_series", [])

        fig = Figure(facecolor='#191920', dpi=90)
        fig.subplots_adjust(left=0.12, right=0.88, top=0.92, bottom=0.22)
        ax = fig.add_subplot(111)
        ax.set_facecolor('#0d0d14')

        if not series:
            ax.text(0.5, 0.5, "No PH5 P&L data available",
                    ha='center', va='center', fontsize=10,
                    color='#55555f', transform=ax.transAxes)
            canvas = FigureCanvasTkAgg(fig, master=panel)
            canvas.get_tk_widget().pack(fill="both", expand=True, padx=6, pady=(4, 6))
            canvas.draw_idle()
            self._chart_canvas = canvas
            return

        dates = [s["date"][5:] for s in series]
        pnls = [s["ph5_pnl"] for s in series]
        colors = [GREEN if p >= 0 else RED for p in pnls]
        x = range(len(dates))

        ax.bar(x, pnls, color=colors, alpha=0.8, width=0.6)

        cumulative = []
        running = 0.0
        for p in pnls:
            running += p
            cumulative.append(running)
        ax2 = ax.twinx()
        ax2.plot(list(x), cumulative, color=CYAN, linewidth=1.5,
                 alpha=0.9, marker='o', markersize=3)
        ax2.set_ylabel("Cumulative", fontsize=8, color=CYAN)
        ax2.tick_params(axis='y', labelsize=7, colors=CYAN)
        ax2.spines['right'].set_color(CYAN)
        ax2.spines['right'].set_alpha(0.3)

        ax.set_xticks(list(x))
        ax.set_xticklabels(dates, rotation=45, fontsize=7, color='#72727e')
        ax.tick_params(axis='y', labelsize=7, colors='#b0b0ba')
        ax.set_ylabel("Daily P&L (Rs.)", fontsize=8, color='#b0b0ba')
        ax.axhline(y=0, color='#2e2e3a', linewidth=0.5)

        for spine in ax.spines.values():
            spine.set_color('#2e2e3a')
        for sp in ['top', 'right']:
            ax.spines[sp].set_visible(False)
        ax2.spines['top'].set_visible(False)
        ax2.spines['left'].set_visible(False)
        ax.grid(axis='y', color='#1f1f28', linewidth=0.5, alpha=0.5)

        canvas = FigureCanvasTkAgg(fig, master=panel)
        canvas.get_tk_widget().pack(fill="both", expand=True, padx=6, pady=(4, 6))
        canvas.draw_idle()
        self._chart_canvas = canvas

    # ── Bottom : SEASON STATS BAR ─────────────────────────────────
    def _build_status_bar(self, d):
        perf = d.get("performance", {})
        total = perf.get("total_trades", 0)
        wins = perf.get("wins", 0)
        losses = perf.get("losses", 0)
        wr = perf.get("win_rate", 0)
        aw = perf.get("avg_win", 0)
        al = perf.get("avg_loss", 0)
        pf = perf.get("profit_factor", 0)
        net = perf.get("total_pnl", 0)

        _status_bar(self, [
            (f"Total: {total}", TEXT_LABEL),
            (f"W: {wins}", GREEN),
            (f"L: {losses}", RED),
            (f"WR: {wr:.0f}%", GREEN if wr >= 50 else RED),
            (f"Avg W: +Rs.{aw:.0f}", GREEN),
            (f"Avg L: -Rs.{al:.0f}", RED),
            (f"PF: {pf:.1f}x", GREEN if pf >= 1.5 else AMBER if pf >= 1.0 else RED),
            (f"Net: Rs.{net:+.0f}", GREEN if net > 0 else RED),
        ]).pack(fill="x", padx=8, pady=(0, 4))


# ==========================================================================
#  PH5A DETAIL -- PVAT SCANNER
# ==========================================================================

class PH5ADetail(ctk.CTkFrame):

    def __init__(self, parent, on_back, data_bridge=None):
        super().__init__(parent, fg_color="transparent")
        self._on_back = on_back
        self._data_bridge = data_bridge
        self._data = PH5A_MOCK.copy()
        self._build()

        if self._data_bridge:
            self._data_bridge.register_callback(self, self._on_live_data)
            self.after(500, self._try_live)

    def _try_live(self):
        if self._data_bridge:
            live = self._data_bridge.get_latest()
            if live and live.db_available:
                self._on_live_data(live)

    def _on_live_data(self, live):
        if not live or not live.db_available:
            return
        try:
            ph5a = self._data_bridge.get_ph5a_data()
            if ph5a:
                # Merge live data into display dict
                for key in ('scan_mode', 'scan_interval_sec', 'scan_count',
                            'levels_found', 'gates', 'gate_max', 'approaching',
                            'state_counts', 'pipeline', 'traded', 'rejected',
                            'trade_fired', 'ph5a_done', 'triggers_today', 'pnl_today',
                            'closest_distance_pct', 'closest_symbol',
                            'recent_events', 'total_tracked'):
                    if key in ph5a:
                        self._data[key] = ph5a[key]
                self._refresh_display()
        except Exception:
            pass

    def _refresh_display(self):
        for w in self.winfo_children():
            w.destroy()
        self._build()

    def _build(self):
        d = self._data

        _back_button(self, self._on_back).pack(anchor="w", padx=8, pady=(4, 4))

        # === TITLE BAR with RUNNING/STOPPED indicator ===
        scan_count = d.get("scan_count", 0)
        is_running = scan_count > 0
        if is_running:
            status_dot = "●"
            status_text = f"RUNNING ({scan_count})"
            status_color = GREEN
        else:
            status_dot = "●"
            status_text = "STOPPED"
            status_color = RED

        title_frame = ctk.CTkFrame(self, fg_color=BG_HEADER, corner_radius=8,
                                   border_width=1, border_color=BORDER, height=36)
        title_frame.pack(fill="x", padx=8, pady=(0, 4))
        title_frame.pack_propagate(False)

        ctk.CTkLabel(title_frame, text="PH5A . PVAT SCANNER -- RADAR SWEEP",
                     font=FONT_TITLE, text_color=TEXT_PRIMARY,
                     ).pack(side="left", padx=10)

        ctk.CTkLabel(title_frame,
                     text=f"{status_dot} {status_text}",
                     font=FONT_BODY_BOLD, text_color=status_color,
                     ).pack(side="right", padx=10)

        # === TOP ROW: Filter Funnel + Activity Log ===
        top = ctk.CTkFrame(self, fg_color="transparent")
        top.pack(fill="x", padx=8, pady=(0, 4))
        top.columnconfigure(0, weight=2)
        top.columnconfigure(1, weight=3)

        scan_mode = d.get("scan_mode", "NORMAL")
        scan_interval = d.get("scan_interval_sec", 30)

        # -- Left: FILTER FUNNEL + STATUS --
        left = _instrument_panel(top, "FILTER FUNNEL")
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 4))

        funnel = ctk.CTkFrame(left, fg_color=BG_INPUT, corner_radius=6)
        funnel.pack(fill="x", padx=10, pady=(8, 4))

        # Pipeline funnel — how stocks flow through gates
        total_tracked = d.get("total_tracked", 0)
        levels_found = d.get("levels_found", 0)
        sc = d.get("state_counts", {})
        n_approach = sc.get("APPROACH", 0)
        n_acceptance = sc.get("ACCEPTANCE", 0)
        n_breakout = sc.get("BREAKOUT", 0)
        n_traded = sc.get("TRADED", 0)
        n_rejected = sc.get("REJECTED", 0)

        funnel_stages = [
            (f"{total_tracked} scanned", TEXT_PRIMARY, ""),
            (f" ├─ {levels_found} with levels (PDH/PDL/POC)", GREEN, ""),
            (f" ├─ {n_approach} approaching", AMBER, ""),
            (f" ├─ {n_acceptance} acceptance", CYAN, ""),
            (f" └─ {n_breakout} breakout / {n_traded} traded", RED if n_traded == 0 else GREEN, ""),
        ]
        for text, color, _ in funnel_stages:
            ctk.CTkLabel(funnel, text=text,
                         font=FONT_SMALL_BOLD, text_color=color,
                         anchor="w").pack(padx=8, pady=1, anchor="w")

        # State breakdown — compact row
        state_row = ctk.CTkFrame(left, fg_color=BG_INPUT, corner_radius=6)
        state_row.pack(fill="x", padx=10, pady=(4, 4))

        state_items = [
            ("IDLE", sc.get("IDLE", 0), TEXT_MUTED),
            ("APPR", n_approach, AMBER),
            ("ACC", n_acceptance, CYAN),
            ("BRK", n_breakout, RED),
            ("TRADED", n_traded, GREEN),
            ("REJ", n_rejected, TEXT_DIM),
        ]
        state_text = "  |  ".join(f"{name} {count}" for name, count, _ in state_items)
        ctk.CTkLabel(state_row, text=state_text,
                     font=FONT_TINY_BOLD, text_color=TEXT_PRIMARY,
                     ).pack(padx=8, pady=4)

        # Key stats
        info = ctk.CTkFrame(left, fg_color=BG_INPUT, corner_radius=6)
        info.pack(fill="x", padx=10, pady=(4, 8))

        mc = {"NORMAL": GREEN, "WARM": AMBER, "HOT": RED}.get(scan_mode, TEXT_PRIMARY)
        _stat_row(info, "Mode", scan_mode, mc)
        _stat_row(info, "Interval", f"{scan_interval}s")
        _stat_row(info, "Scans Today", str(scan_count))

        closest_dist = d.get("closest_distance_pct")
        closest_sym = d.get("closest_symbol")
        if closest_dist is not None and closest_sym:
            dist_color = RED if closest_dist < 0.3 else AMBER if closest_dist < 1.0 else TEXT_MUTED
            _stat_row(info, "Nearest", f"{closest_sym} {closest_dist:.2f}%", dist_color)

        # -- Right: ACTIVITY LOG --
        right = _instrument_panel(top, "ACTIVITY LOG")
        right.grid(row=0, column=1, sticky="nsew", padx=(4, 0))

        log_box = ctk.CTkTextbox(right, font=FONT_SMALL,
                                 fg_color=BG_INPUT, text_color=TEXT_PRIMARY,
                                 corner_radius=6, height=180,
                                 activate_scrollbars=True, wrap="word")
        log_box.pack(fill="both", expand=True, padx=10, pady=(8, 8))

        # Color tags for different event levels
        log_box.tag_config("info", foreground=TEXT_PRIMARY)
        log_box.tag_config("success", foreground=GREEN)
        log_box.tag_config("warn", foreground=AMBER)
        log_box.tag_config("error", foreground=RED)
        log_box.tag_config("time", foreground=TEXT_DIM)

        events = d.get("recent_events", [])
        if events:
            for evt in events:
                ts = evt.get("time", "")
                text = evt.get("text", "")
                level = evt.get("level", "info")
                log_box.insert("end", f"{ts}  ", "time")
                log_box.insert("end", f"{text}\n", level)
        else:
            log_box.insert("end", "  No scanner events yet\n", "info")

        log_box.configure(state="disabled")

        # === MIDDLE ROW: Approaching + Pipeline ===
        mid = ctk.CTkFrame(self, fg_color="transparent")
        mid.pack(fill="both", expand=True, padx=8, pady=(0, 4))
        mid.columnconfigure(0, weight=1)
        mid.columnconfigure(1, weight=1)
        mid.rowconfigure(0, weight=1)

        # -- Left: APPROACHING LEVELS --
        app_panel = _instrument_panel(mid, "APPROACHING LEVELS")
        app_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 4))

        approaching = d.get("approaching", [])
        if approaching:
            for item in approaching:
                row = ctk.CTkFrame(app_panel, fg_color=BG_INPUT, corner_radius=6)
                row.pack(fill="x", padx=10, pady=3)

                direction = item.get('direction', '?')
                dir_color = GREEN if direction == 'LONG' else RED
                dir_arrow = "▲" if direction == 'LONG' else "▼"
                state = item.get('state', '')
                state_color = AMBER if state == 'ACCEPTANCE' else TEXT_LABEL

                # Line 1: Symbol + direction + level
                ctk.CTkLabel(
                    row,
                    text=f"{dir_arrow} {item.get('symbol', '?')}  Rs.{item.get('level', 0)}  "
                         f"{item.get('level_type', '')}",
                    font=FONT_BODY_BOLD,
                    text_color=dir_color,
                ).pack(padx=8, pady=(4, 0), anchor="w")

                # Line 2: Details
                dist = item.get('distance_pct', 0)
                score = item.get('score', 0)
                rej = item.get('rejections', 0)
                conf = item.get('confluence', 0)
                ctk.CTkLabel(
                    row,
                    text=f"Dist: {dist:.2f}%  |  Score: {score}  |  "
                         f"Rej: {rej}  |  Conf: {conf}d  |  {state}",
                    font=FONT_TINY,
                    text_color=state_color,
                ).pack(padx=8, pady=(0, 4), anchor="w")
        else:
            ctk.CTkLabel(
                app_panel, text="No stocks near levels",
                font=FONT_SMALL,
                text_color=TEXT_DIM,
            ).pack(padx=10, pady=20)

        # -- Right: SNIPER PIPELINE --
        pipe_panel = _instrument_panel(mid, "SNIPER PIPELINE")
        pipe_panel.grid(row=0, column=1, sticky="nsew", padx=(4, 0))

        pipeline = d.get("pipeline", [])
        if pipeline:
            for stock in pipeline:
                row = ctk.CTkFrame(pipe_panel, fg_color=BG_INPUT, corner_radius=6)
                row.pack(fill="x", padx=10, pady=3)

                direction = stock.get('direction', '?')
                dir_color = GREEN if direction == 'LONG' else RED
                dir_arrow = "▲ LONG" if direction == 'LONG' else "▼ SHORT"
                triggered = stock.get('triggered', False)
                exited = stock.get('exited', False)

                if exited:
                    status = f"EXIT: {stock.get('exit_reason', '?')}"
                    status_color = TEXT_MUTED
                elif triggered:
                    entry = stock.get('entry_price', 0)
                    stop = stock.get('stop_price', 0)
                    target = stock.get('target_price', 0)
                    status = f"LIVE  E:{entry:.0f}  SL:{stop:.0f}  TGT:{target:.0f}"
                    status_color = GREEN
                else:
                    status = "WATCHING -- awaiting level break"
                    status_color = AMBER

                # Line 1: Symbol + direction
                ctk.CTkLabel(
                    row,
                    text=f"{stock.get('symbol', '?')}  {dir_arrow}  "
                         f"{stock.get('level_type', '')} @ Rs.{stock.get('level', 0)}",
                    font=FONT_BODY_BOLD,
                    text_color=dir_color,
                ).pack(padx=8, pady=(4, 0), anchor="w")

                # Line 2: Status
                ctk.CTkLabel(
                    row,
                    text=f"Score: {stock.get('score', 0)}  |  {status}",
                    font=FONT_TINY,
                    text_color=status_color,
                ).pack(padx=8, pady=(0, 4), anchor="w")
        else:
            done = d.get("ph5a_done", False)
            fired = d.get("trade_fired", False)
            if done and not fired:
                msg = "No elite setups today -- standing down"
                msg_color = TEXT_DIM
            elif fired:
                msg = "Trade executed -- mission complete"
                msg_color = GREEN
            else:
                msg = "Scanning -- pipeline not yet built"
                msg_color = AMBER
            ctk.CTkLabel(
                pipe_panel, text=msg,
                font=FONT_SMALL,
                text_color=msg_color,
            ).pack(padx=10, pady=20)

        # === BOTTOM BAR: Scan Zones + PnL ===
        bottom = ctk.CTkFrame(self, fg_color=BG_PANEL, corner_radius=8,
                              border_width=1, border_color=BORDER, height=36)
        bottom.pack(fill="x", padx=8, pady=(0, 4))
        bottom.pack_propagate(False)

        zones_inner = ctk.CTkFrame(bottom, fg_color="transparent")
        zones_inner.pack(expand=True)

        ctk.CTkLabel(zones_inner, text="SCAN ZONES:",
                     font=FONT_SMALL_BOLD,
                     text_color=TEXT_MUTED).pack(side="left", padx=(10, 10))

        for mn, mc_z in [("NORMAL", GREEN), ("WARM", AMBER), ("HOT", RED)]:
            active = scan_mode == mn
            dot = "●" if active else "○"
            ctk.CTkLabel(zones_inner, text=f"{dot} {mn}",
                         font=FONT_SMALL_BOLD,
                         text_color=mc_z if active else TEXT_DIM,
                         ).pack(side="left", padx=8)

        # PnL summary on right side of bottom bar
        triggers = d.get("triggers_today", 0)
        pnl = d.get("pnl_today", 0)
        if triggers > 0 or pnl != 0:
            pnl_color = GREEN if pnl >= 0 else RED
            pnl_sign = "+" if pnl >= 0 else ""
            ctk.CTkLabel(zones_inner, text=f"Trades: {triggers}  |  PnL: {pnl_sign}{pnl:.0f}",
                         font=FONT_SMALL_BOLD,
                         text_color=pnl_color,
                         ).pack(side="right", padx=10)


# ==========================================================================
#  ATTITUDE INDICATOR (Canvas-based artificial horizon -- hero element)
# ==========================================================================

class AttitudeIndicator(ctk.CTkFrame):
    """
    Canvas-based artificial horizon instrument.
    Renders gradient sky/ground with pitch and bank rotation,
    pitch ladder, bank indicator, Bollinger Band markers,
    and a fixed aircraft reference symbol.
    Scales dynamically to fill available space.
    """

    # Sky gradient: horizon (lightest) -> zenith (darkest)
    _SKY = [
        "#4aa8ff", "#42a0f8", "#3a98f0", "#3290e8", "#2a88e0",
        "#2280d8", "#1a78d0", "#1270c8", "#0a68c0", "#0560b8",
        "#0058b0", "#004ca0",
    ]
    # Ground gradient: horizon (lightest) -> nadir (darkest)
    _GND = [
        "#b88860", "#aa7c55", "#9c704a", "#8e6440", "#805836",
        "#724c2c", "#644022", "#563418", "#48280e", "#3a1c04",
        "#2c1000", "#200800",
    ]

    def __init__(self, parent):
        super().__init__(parent, fg_color="transparent")
        self._canvas = tk.Canvas(self, bg=BG_PANEL, highlightthickness=0)
        self._canvas.pack(fill="both", expand=True)

        self._pitch = 0.0
        self._bank = 0.0
        self._target_pitch = 0.0
        self._target_bank = 0.0
        self._bb_data = {}
        self._anim_id = None
        self._anim_step = 0
        self._ready = False
        self._pending = False
        self._cw = 1
        self._ch = 1

        self._canvas.bind("<Configure>", self._on_cfg)

    # -- geometry ----------------------------------------------------------

    def _on_cfg(self, event):
        cw, ch = event.width, event.height
        if cw < 60 or ch < 60:
            return
        self._cw = cw
        self._ch = ch
        self._ready = True
        if self._pending:
            self._pending = False
            self._start_anim()
        else:
            self._render()

    @staticmethod
    def _rot(x, y, a):
        """Rotate (x, y) around origin by *a* radians."""
        c, s = math.cos(a), math.sin(a)
        return x * c - y * s, x * s + y * c

    # -- full render -------------------------------------------------------

    def _render(self):
        cv = self._canvas
        cv.delete("all")

        cw, ch = self._cw, self._ch
        cx = cw // 2
        cy = ch // 2 - 14
        r = min(cx - 12, cy - 24)
        if r < 30:
            return

        pitch, bank = self._pitch, self._bank
        b_rad = math.radians(-bank)
        p_px = (pitch / 45.0) * r * 0.7

        # -- 1. Sky gradient bands --
        bh = r * 0.28
        for i, col in enumerate(self._SKY):
            y0 = p_px + i * bh
            y1 = p_px + (i + 1) * bh
            pts = []
            for px, py in [(-r * 3, y0), (r * 3, y0),
                           (r * 3, y1), (-r * 3, y1)]:
                rx, ry = self._rot(px, py, b_rad)
                pts.extend([cx + rx, cy - ry])
            cv.create_polygon(pts, fill=col, outline="")

        # -- 2. Ground gradient bands --
        for i, col in enumerate(self._GND):
            y0 = p_px - i * bh
            y1 = p_px - (i + 1) * bh
            pts = []
            for px, py in [(-r * 3, y0), (r * 3, y0),
                           (r * 3, y1), (-r * 3, y1)]:
                rx, ry = self._rot(px, py, b_rad)
                pts.extend([cx + rx, cy - ry])
            cv.create_polygon(pts, fill=col, outline="")

        # -- 3. Horizon line --
        hx1, hy1 = self._rot(-r * 1.5, p_px, b_rad)
        hx2, hy2 = self._rot(r * 1.5, p_px, b_rad)
        cv.create_line(cx + hx1, cy - hy1, cx + hx2, cy - hy2,
                       fill="#ffffff", width=2)

        # -- 4. Pitch ladder --
        for deg in [-30, -20, -10, 10, 20, 30]:
            y = (deg / 45.0) * r * 0.7 + p_px
            hw = r * (0.22 - abs(deg) * 0.003)
            x1, y1 = self._rot(-hw, y, b_rad)
            x2, y2 = self._rot(hw, y, b_rad)
            cv.create_line(cx + x1, cy - y1, cx + x2, cy - y2,
                           fill="#b0b0b8", width=1)
            for side in (-1, 1):
                lx, ly = self._rot(side * (hw + 6), y, b_rad)
                cv.create_text(cx + lx, cy - ly, text=str(abs(deg)),
                               fill="#80808a",
                               font=FONT_TINY,
                               anchor="e" if side < 0 else "w")

        # +/-5 deg short sub-lines
        for deg in (-5, 5):
            y = (deg / 45.0) * r * 0.7 + p_px
            hw = r * 0.10
            x1, y1 = self._rot(-hw, y, b_rad)
            x2, y2 = self._rot(hw, y, b_rad)
            cv.create_line(cx + x1, cy - y1, cx + x2, cy - y2,
                           fill="#b0b0b8", width=1)

        # -- 5. Circular mask (covers everything outside instrument) --
        mw = int(max(cw, ch) * 2 + 200)
        mr = r + mw / 2
        cv.create_oval(cx - mr, cy - mr, cx + mr, cy + mr,
                       outline=BG_PANEL, width=mw, fill="")

        # -- 6. Bezel (layered rings for metallic look) --
        for br, col, w in [
            (r + 16, "#0d0d12", 10),
            (r + 9,  "#18181e", 7),
            (r + 4,  "#222228", 5),
            (r + 1,  "#2e2e36", 3),
            (r - 1,  "#3a3a44", 2),
            (r - 2,  "#48485a", 1),
        ]:
            cv.create_oval(cx - br, cy - br, cx + br, cy + br,
                           outline=col, width=w, fill="")

        # -- 7. Bank indicator (arc at top of circle) --
        for bdeg in [-30, -20, -10, 0, 10, 20, 30]:
            a = math.radians(90 + bdeg)
            r_out = r - 3
            r_in = r - (18 if bdeg == 0 else 14 if bdeg % 20 == 0 else 9)
            cv.create_line(
                cx + r_in * math.cos(a), cy - r_in * math.sin(a),
                cx + r_out * math.cos(a), cy - r_out * math.sin(a),
                fill="#e0e0e0" if bdeg == 0 else "#909090",
                width=2 if bdeg == 0 else 1,
            )

        # Fixed zenith triangle (amber -- aircraft nose reference)
        zt = r - 4
        cv.create_polygon(
            cx, cy - zt,
            cx - 8, cy - zt + 16,
            cx + 8, cy - zt + 16,
            fill=AIRCRAFT_REF, outline="",
        )

        # Moving bank pointer (white triangle -- rotates with bank)
        pa = math.radians(90 - bank)
        pr_base = r - 20
        tip_x = cx + (pr_base + 12) * math.cos(pa)
        tip_y = cy - (pr_base + 12) * math.sin(pa)
        b1x = cx + pr_base * math.cos(pa + 0.08)
        b1y = cy - pr_base * math.sin(pa + 0.08)
        b2x = cx + pr_base * math.cos(pa - 0.08)
        b2y = cy - pr_base * math.sin(pa - 0.08)
        cv.create_polygon(tip_x, tip_y, b1x, b1y, b2x, b2y,
                          fill="#ffffff", outline="")

        # -- 8. Bollinger-band markers (right edge of circle) --
        if self._bb_data:
            ema = self._bb_data.get("ema_20", 0)
            atr = self._bb_data.get("atr_14", 1)
            if atr > 0:
                for key, label, col in [
                    ("bb_upper", "STALL", BB_UPPER),
                    ("bb_lower", "TERRAIN", BB_LOWER),
                ]:
                    val = self._bb_data.get(key)
                    if val is not None:
                        bp = ((val - ema) / atr) * 15
                        by = (bp / 45.0) * r * 0.7
                        if abs(by) < r * 0.85:
                            tx = cx + r - 10
                            ty = cy - by
                            cv.create_polygon(
                                tx, ty, tx - 14, ty - 7, tx - 14, ty + 7,
                                fill=col, outline="",
                            )
                            cv.create_text(
                                tx - 18, ty, text=label, fill=col,
                                font=FONT_TINY_BOLD,
                                anchor="e",
                            )
                # BB middle (SMA) marker
                bb_m = self._bb_data.get("bb_middle")
                if bb_m is not None:
                    mp = ((bb_m - ema) / atr) * 15
                    my = (mp / 45.0) * r * 0.7
                    if abs(my) < r * 0.85:
                        cv.create_line(
                            cx + r - 22, cy - my,
                            cx + r - 6, cy - my,
                            fill=BB_MIDDLE, width=2,
                        )

        # -- 9. Aircraft reference symbol (fixed amber crosshair) --
        ww = r * 0.18
        gap = r * 0.04
        droop = r * 0.04
        cv.create_line(cx - ww, cy, cx - gap, cy,
                       fill=AIRCRAFT_REF, width=4, capstyle="round")
        cv.create_line(cx + gap, cy, cx + ww, cy,
                       fill=AIRCRAFT_REF, width=4, capstyle="round")
        cv.create_line(cx - ww, cy, cx - ww, cy + droop,
                       fill=AIRCRAFT_REF, width=3, capstyle="round")
        cv.create_line(cx + ww, cy, cx + ww, cy + droop,
                       fill=AIRCRAFT_REF, width=3, capstyle="round")
        dot = 5
        cv.create_oval(cx - dot, cy - dot, cx + dot, cy + dot,
                       fill=AIRCRAFT_REF, outline="")

        # -- 10. Readouts below instrument --
        ry = cy + r + 22
        cv.create_text(
            cx, ry,
            text=f"PITCH {pitch:+.0f}\u00b0    BANK {bank:+.0f}\u00b0",
            fill=TEXT_LABEL, font=FONT_SMALL_BOLD,
        )
        bbu = self._bb_data.get("bb_upper")
        bbl = self._bb_data.get("bb_lower")
        bbm = self._bb_data.get("bb_middle")
        if bbu and bbl and bbm:
            cv.create_text(
                cx, ry + 18,
                text=f"BB  {bbl:.0f}  |  {bbm:.0f}  |  {bbu:.0f}",
                fill=TEXT_DIM, font=FONT_TINY,
            )

    # -- public API --------------------------------------------------------

    def update_data(self, data):
        """Set target pitch/bank and BB data, then animate."""
        self._target_pitch = data.get("pitch", 0)
        self._target_bank = data.get("bank", 0)
        self._bb_data = {
            "bb_upper": data.get("bb_upper"),
            "bb_lower": data.get("bb_lower"),
            "bb_middle": data.get("bb_middle"),
            "ema_20": data.get("ema_20", 0),
            "atr_14": data.get("atr_14", 1),
        }
        self._start_anim()

    def _start_anim(self):
        if self._anim_id:
            self.after_cancel(self._anim_id)
            self._anim_id = None
        if not self._ready:
            self._pending = True
            return
        self._anim_step = 0
        self._anim_sp = self._pitch
        self._anim_sb = self._bank
        self._tick()

    def _tick(self):
        N = 20
        if self._anim_step <= N:
            t = self._anim_step / N
            t = 1 - (1 - t) ** 3  # ease-out cubic
            self._pitch = self._anim_sp + (self._target_pitch - self._anim_sp) * t
            self._bank = self._anim_sb + (self._target_bank - self._anim_sb) * t
            self._render()
            self._anim_step += 1
            self._anim_id = self.after(22, self._tick)
        else:
            self._anim_id = None


# ==========================================================================
#  FLIGHT DATA PANEL (right side vertical data strip)
# ==========================================================================

class FlightDataPanel(ctk.CTkFrame):
    """Vertical flight data strip -- aviation-style data readout."""

    def __init__(self, parent, width=220):
        super().__init__(parent, fg_color=BG_PANEL, corner_radius=8,
                         border_width=1, border_color=BORDER, width=width)
        self.pack_propagate(False)
        self._labels = {}
        self._build()

    def _build(self):
        inner = ctk.CTkFrame(self, fg_color="transparent")
        inner.pack(fill="both", expand=True, padx=6, pady=6)

        fields = [
            ("ALTITUDE", "alt_val", 18, True),
            ("CLIMB RATE", "vel_val", 13, True),
            ("ACCELERATION", "acc_val", 12, False),
            ("HEADING", "heading_val", 13, True),
            None,  # separator
            ("\u25b2 ILS TARGET", "ils_val", 13, False),
            ("ils_dist", "ils_dist", 11, False),
            ("\u25bc TCAS FLOOR", "tcas_val", 13, False),
            ("tcas_dist", "tcas_dist", 11, False),
            None,
            ("ETA TARGET", "eta_val", 13, False),
            ("SUPPORT", "sup_val", 12, False),
            ("RESISTANCE", "res_val", 12, False),
        ]

        for item in fields:
            if item is None:
                ctk.CTkFrame(inner, fg_color=BORDER_DIM, height=1
                             ).pack(fill="x", padx=4, pady=4)
                continue
            lbl_text, key, fsize, is_hero = item
            # Label (skip for sub-value rows)
            if not key.endswith("_dist"):
                lbl_color = TEXT_DIM
                if "ILS" in lbl_text:
                    lbl_color = GREEN
                elif "TCAS" in lbl_text:
                    lbl_color = RED
                ctk.CTkLabel(inner, text=lbl_text,
                             font=FONT_TINY,
                             text_color=lbl_color, anchor="w"
                             ).pack(fill="x", padx=6, pady=(4, 0))
            # Value
            val_lbl = ctk.CTkLabel(inner, text="--",
                                   font=(FONT_FAMILY, fsize, "bold"),
                                   text_color=TEXT_PRIMARY, anchor="w")
            val_lbl.pack(fill="x", padx=6, pady=(0, 2))
            self._labels[key] = val_lbl

    def update_data(self, pos):
        """Update all fields from position data dict."""
        price = pos["current"]
        entry = pos["entry"]

        # Altitude
        self._labels["alt_val"].configure(
            text=f"Rs.{price:,.2f}",
            text_color=GREEN if price >= entry else RED)

        # Climb rate
        vel = pos["velocity"]
        self._labels["vel_val"].configure(
            text=f"{vel:+.1f} Rs/min",
            text_color=GREEN if vel > 0 else RED if vel < 0 else TEXT_MUTED)

        # Acceleration
        acc = pos["acceleration"]
        self._labels["acc_val"].configure(
            text=f"{acc:+.2f} Rs/min\u00b2",
            text_color=GREEN if acc > 0 else RED if acc < 0 else TEXT_MUTED)

        # Heading
        if vel > 0.3:
            hdg, hc = "BULLISH  \u25b2", GREEN
        elif vel < -0.3:
            hdg, hc = "BEARISH  \u25bc", RED
        else:
            hdg, hc = "NEUTRAL  \u2501", TEXT_MUTED
        self._labels["heading_val"].configure(text=hdg, text_color=hc)

        # ILS
        ils = pos["ils_target"]
        ils_pct = (ils - price) / price * 100
        self._labels["ils_val"].configure(
            text=f"Rs.{ils:,.2f}", text_color=GREEN)
        self._labels["ils_dist"].configure(
            text=f"{ils_pct:+.1f}% away", text_color=TEXT_DIM)

        # TCAS
        tcas = pos["tcas_floor"]
        tcas_pct = (tcas - price) / price * 100
        self._labels["tcas_val"].configure(
            text=f"Rs.{tcas:,.2f}", text_color=RED)
        self._labels["tcas_dist"].configure(
            text=f"{tcas_pct:+.1f}% away", text_color=TEXT_DIM)

        # ETA
        eta = pos.get("eta_minutes")
        if eta:
            ec = GREEN if eta < 30 else AMBER
            self._labels["eta_val"].configure(text=f"~{eta} min", text_color=ec)
        else:
            self._labels["eta_val"].configure(text="--", text_color=TEXT_MUTED)

        # Support / Resistance
        self._labels["sup_val"].configure(
            text=f"Rs.{pos['support']:,}", text_color=TEXT_LABEL)
        self._labels["res_val"].configure(
            text=f"Rs.{pos['resistance']:,}", text_color=TEXT_LABEL)


# ==========================================================================
#  STOCK SELECTOR TABS
# ==========================================================================

class StockSelectorTabs(ctk.CTkFrame):
    """Horizontal tabs with colored status dots for stock switching."""

    def __init__(self, parent, stocks, on_select):
        super().__init__(parent, fg_color=BG_PANEL, corner_radius=8,
                         border_width=1, border_color=BORDER, height=42)
        self.pack_propagate(False)
        self._on_select = on_select
        self._tabs = {}
        self._active = None

        inner = ctk.CTkFrame(self, fg_color="transparent")
        inner.pack(fill="both", expand=True, padx=6, pady=4)

        for stock in stocks:
            sym = stock["symbol"]
            status = stock["status"]
            sc = {"ON TRACK": GREEN, "MONITOR": AMBER,
                  "WARNING": RED}.get(status, TEXT_MUTED)

            cell = ctk.CTkFrame(inner, fg_color="transparent",
                                corner_radius=6, cursor="hand2")
            cell.pack(side="left", padx=3)

            dot = ctk.CTkLabel(cell, text="\u25cf", font=("", 10),
                               text_color=sc, width=14, cursor="hand2")
            dot.pack(side="left", padx=(6, 0))

            name = ctk.CTkLabel(cell, text=sym,
                                font=FONT_SMALL_BOLD,
                                text_color=TEXT_MUTED, cursor="hand2")
            name.pack(side="left", padx=(3, 8))

            for w in (cell, dot, name):
                w.bind("<Button-1>", lambda e, s=sym: self._select(s))

            self._tabs[sym] = (cell, name, sc)

    def _select(self, symbol):
        if self._active == symbol:
            return
        self._active = symbol
        for sym, (cell, name, sc) in self._tabs.items():
            if sym == symbol:
                cell.configure(fg_color=BG_HEADER)
                name.configure(text_color=TEXT_PRIMARY)
            else:
                cell.configure(fg_color="transparent")
                name.configure(text_color=TEXT_MUTED)
        self._on_select(symbol)

    def set_active(self, symbol):
        """Highlight tab without triggering callback."""
        for sym, (cell, name, sc) in self._tabs.items():
            if sym == symbol:
                cell.configure(fg_color=BG_HEADER)
                name.configure(text_color=TEXT_PRIMARY)
            else:
                cell.configure(fg_color="transparent")
                name.configure(text_color=TEXT_MUTED)
        self._active = symbol


# ==========================================================================
#  KALMAN STRIP (compact bottom row)
# ==========================================================================

class KalmanStrip(ctk.CTkFrame):
    """Compact single-row strip showing all positions."""

    def __init__(self, parent, positions, on_select, height=72):
        super().__init__(parent, fg_color=BG_PANEL, corner_radius=8,
                         border_width=1, border_color=BORDER, height=height)
        self.pack_propagate(False)
        self._on_select = on_select

        py = 2 if height < 60 else 4
        inner = ctk.CTkFrame(self, fg_color="transparent")
        inner.pack(fill="both", expand=True, padx=4, pady=py)

        for i, pos in enumerate(positions):
            cell = ctk.CTkFrame(inner, fg_color=BG_INPUT, corner_radius=6,
                                cursor="hand2")
            cell.pack(side="left", fill="both", expand=True, padx=2)

            sym = pos["symbol"]
            sc = {"ON TRACK": GREEN, "MONITOR": AMBER,
                  "WARNING": RED}.get(pos["status"], TEXT_MUTED)
            vel = pos["velocity"]
            arrow = "\u25b2" if vel > 0 else "\u25bc"
            vc = GREEN if vel > 0 else RED

            # Row 1: symbol + price + velocity
            r1 = ctk.CTkFrame(cell, fg_color="transparent")
            r1.pack(fill="x", padx=6, pady=(4, 0))
            ctk.CTkLabel(r1, text=f"\u25cf {sym}",
                         font=FONT_SMALL_BOLD,
                         text_color=sc, cursor="hand2").pack(side="left")
            ctk.CTkLabel(r1, text=f"Rs.{pos['current']:.0f} {arrow}{vel:+.1f}",
                         font=FONT_TINY,
                         text_color=vc, cursor="hand2").pack(side="right")

            # Row 2: ILS + TCAS + status
            r2 = ctk.CTkFrame(cell, fg_color="transparent")
            r2.pack(fill="x", padx=6, pady=(0, 4))
            ctk.CTkLabel(r2, text=f"ILS:{pos['ils_target']:.0f}  TCAS:{pos['tcas_floor']:.0f}",
                         font=FONT_TINY,
                         text_color=TEXT_DIM, cursor="hand2").pack(side="left")
            ctk.CTkLabel(r2, text=pos["status"],
                         font=FONT_TINY_BOLD,
                         text_color=sc, cursor="hand2").pack(side="right")

            # Click binding
            for widget in [cell, r1, r2] + list(r1.winfo_children()) + list(r2.winfo_children()):
                widget.bind("<Button-1>", lambda e, s=sym: self._on_select(s))


# ==========================================================================
#  PH4 GLASS COCKPIT VIEW
# ==========================================================================

class PH4Detail(ctk.CTkFrame):
    """Glass Cockpit PFD v3 -- full flight deck with timeframe selector,
    AI advisory, blinking status lights, and 5-row EICAS detail."""

    INTRADAY_TFS = {"15m", "30m", "1hr", "2hr", "Day"}

    def __init__(self, parent, on_back, data_bridge=None):
        super().__init__(parent, fg_color="transparent")
        self._on_back = on_back
        self._data_bridge = data_bridge
        self._data = EMPTY_COCKPIT
        self._using_live = False
        self._positions = {}                  # no positions at startup
        self._selected = None                 # no stock selected
        self._timeframe = "1hr"               # sensible default
        self._status_widget = None
        self._source_label = None             # LIVE/MOCK/STANDBY indicator
        self._blink_after_id = None
        self._blink_state = True
        self._active_lights = set()
        self._tf_btns = {}
        self._light_labels = {}
        self._idle_overlay = None             # idle state overlay
        # Prediction history
        self._pred_store = None
        if PredictionStore is not None:
            try:
                self._pred_store = PredictionStore()
            except Exception as e:
                print(f"[PH4Detail] PredictionStore init failed: {e}",
                      file=sys.stderr)
        self._last_save_time = {}
        self._show_history = False
        self._actual_after_id = None
        self._deviation_panel = None
        self._history_btn = None
        self._bot_pane = None
        self._build()
        # Only init instruments if positions exist (empty start = idle)
        if self._positions:
            self._select_stock(self._selected)
            self._seed_mock_history()
        self._start_actual_recording()

        # Register for live data updates
        if self._data_bridge:
            self._data_bridge.register_callback(self, self._on_live_data)
            self.after(500, self._try_live_data)

    # ------------------------------------------------------------------
    #  BUILD
    # ------------------------------------------------------------------
    def _build(self):
        d = self._data

        # ROW 0 — Top bar: back + title + stock tabs + timeframe buttons
        self._top_bar = ctk.CTkFrame(self, fg_color=BG_PANEL, corner_radius=8,
                           border_width=1, border_color=BORDER, height=38)
        self._top_bar.pack(fill="x", padx=8, pady=(4, 3))
        self._top_bar.pack_propagate(False)

        # Back button
        ctk.CTkButton(self._top_bar, text="\u25c0 OVERVIEW", width=90, height=26,
                       font=FONT_SMALL, fg_color=BG_INPUT,
                       hover_color=BORDER, text_color=TEXT_MUTED,
                       corner_radius=6,
                       command=self._on_back).pack(side="left", padx=(6, 4))

        # Title
        ctk.CTkLabel(self._top_bar, text="PH4 \u00b7 GLASS COCKPIT",
                     font=FONT_HEADING,
                     text_color=CYAN).pack(side="left", padx=(4, 4))

        # Standby/Live/Mock indicator
        self._source_label = ctk.CTkLabel(
            self._top_bar, text="\u25cf STANDBY", font=FONT_TINY_BOLD,
            text_color="#94a3b8", width=75)
        self._source_label.pack(side="left", padx=(0, 6))

        # Container for stock tabs (allows clean rebuild)
        self._tab_container = ctk.CTkFrame(self._top_bar, fg_color="transparent")
        self._tab_container.pack(side="left", fill="x", expand=False)

        # Inline stock tabs (empty on first build)
        self._tab_btns = {}
        for pos in d["positions"]:
            sym = pos["symbol"]
            sc = GREEN if pos["status"] == "ON TRACK" else (
                AMBER if pos["status"] == "MONITOR" else RED)
            btn = ctk.CTkButton(
                self._tab_container, text=f"{sym[:6]}\u25cf", width=75, height=24,
                font=FONT_SMALL, fg_color=BG_INPUT,
                hover_color=BORDER, text_color=sc, corner_radius=4,
                command=lambda s=sym: self._select_stock(s))
            btn.pack(side="left", padx=2)
            self._tab_btns[sym] = btn

        # Timeframe buttons (right-aligned)
        tf_frame = ctk.CTkFrame(self._top_bar, fg_color="transparent")
        tf_frame.pack(side="right", padx=(4, 6))

        for i, tf in enumerate(TIMEFRAME_LIST):
            pad_l = 6 if tf == "Tmrw" else 1  # gap between Day and Tmrw
            btn = ctk.CTkButton(
                tf_frame, text=tf, width=36, height=22,
                font=FONT_TINY, fg_color=BG_INPUT,
                hover_color=BORDER, text_color=TEXT_DIM, corner_radius=4,
                command=lambda t=tf: self._set_timeframe(t))
            btn.pack(side="left", padx=(pad_l, 1))
            self._tf_btns[tf] = btn

        # History toggle button
        self._history_btn = ctk.CTkButton(
            tf_frame, text="HIST", width=40, height=22,
            font=FONT_TINY, fg_color=BG_INPUT,
            hover_color=BORDER, text_color=TEXT_DIM, corner_radius=4,
            command=self._toggle_history)
        self._history_btn.pack(side="left", padx=(6, 1))

        # ── Vertical PanedWindow: top (instruments+NAV+mid) | bottom (EICAS+status) ──
        self._vsplit = tk.PanedWindow(
            self, orient=tk.VERTICAL,
            sashwidth=4, sashrelief=tk.FLAT,
            bg='#252530', borderwidth=0,
        )
        self._vsplit.pack(fill="both", expand=True, padx=8, pady=(0, 3))

        # ── Top pane ──
        top_pane = tk.Frame(self._vsplit, bg=BG_APP)

        # Horizontal PanedWindow: instruments | NAV display
        self._hsplit = tk.PanedWindow(
            top_pane, orient=tk.HORIZONTAL,
            sashwidth=4, sashrelief=tk.FLAT,
            bg='#252530', borderwidth=0,
        )
        self._hsplit.pack(fill="both", expand=True)

        # LEFT — instruments column
        left = ctk.CTkFrame(self._hsplit, fg_color="transparent", width=250)
        left.grid_propagate(False)
        left.columnconfigure(0, weight=0, minsize=42)    # Speed tape
        left.columnconfigure(1, weight=1)                 # Attitude
        left.columnconfigure(2, weight=0, minsize=52)     # Altitude tape
        left.rowconfigure(0, weight=1)
        left.rowconfigure(1, weight=0, minsize=35)

        self._speed_tape = SpeedTape(left, width=42)
        self._speed_tape.grid(row=0, column=0, sticky="ns")

        ai_frame = ctk.CTkFrame(left, fg_color=BG_PANEL, corner_radius=8,
                                border_width=1, border_color=BORDER)
        ai_frame.grid(row=0, column=1, sticky="nsew", padx=2)
        self._attitude = AttitudeIndicator(ai_frame)
        self._attitude.pack(fill="both", expand=True, padx=2, pady=2)

        self._alt_tape = AltitudeTape(left, width=52)
        self._alt_tape.grid(row=0, column=2, sticky="ns")

        self._heading_strip = HeadingStrip(left, height=35)
        self._heading_strip.grid(row=1, column=0, columnspan=3,
                                 sticky="ew", pady=(2, 0))

        # RIGHT — NAV Display
        nav_frame = tk.Frame(self._hsplit, bg=BG_APP)
        self._nav_display = NavDisplayV3(nav_frame)
        self._nav_display.pack(fill="both", expand=True)

        # Add to horizontal paned window
        self._hsplit.add(left, minsize=200, width=280)
        self._hsplit.add(nav_frame, minsize=400)

        # Mid bar — status lights + ACARS (in top pane, below graph)
        mid = ctk.CTkFrame(top_pane, fg_color=BG_PANEL, corner_radius=8,
                           border_width=1, border_color=BORDER, height=48)
        mid.pack(fill="x", pady=(3, 0))
        mid.pack_propagate(False)

        # Status lights
        light_frame = ctk.CTkFrame(mid, fg_color="transparent")
        light_frame.pack(side="left", padx=(10, 6))
        light_defs = [
            ("HOLD", GREEN), ("CAUTION", AMBER),
            ("TGT ACH", CYAN), ("LAND", GREEN),
        ]
        for name, color in light_defs:
            lbl = ctk.CTkLabel(light_frame, text=f"\u25cf {name}",
                               font=FONT_TINY_BOLD,
                               text_color=TEXT_DIM)
            lbl.pack(side="left", padx=4)
            self._light_labels[name] = (lbl, color)

        # Separator
        ctk.CTkFrame(mid, fg_color=BORDER, width=1).pack(
            side="left", fill="y", padx=4, pady=6)

        # ACARS panel (AI Advisory)
        acars = ctk.CTkFrame(mid, fg_color="transparent",
                             border_width=0)
        acars.pack(side="left", fill="both", expand=True, padx=(2, 8))

        # ACARS left border accent
        ctk.CTkFrame(acars, fg_color=CYAN, width=3).pack(
            side="left", fill="y", padx=(0, 6))

        acars_content = ctk.CTkFrame(acars, fg_color="transparent")
        acars_content.pack(side="left", fill="both", expand=True)

        self._acars_action = ctk.CTkLabel(
            acars_content, text="HOLD",
            font=FONT_BODY_BOLD, text_color=GREEN,
            anchor="w")
        self._acars_action.pack(side="left", padx=(0, 8))

        self._acars_msg = ctk.CTkLabel(
            acars_content, text="--",
            font=FONT_SMALL, text_color=TEXT_LABEL,
            anchor="w")
        self._acars_msg.pack(side="left", fill="x", expand=True)

        self._acars_conf = ctk.CTkLabel(
            acars_content, text="Conf:--",
            font=FONT_SMALL_BOLD, text_color=CYAN,
            anchor="e")
        self._acars_conf.pack(side="right", padx=(4, 0))

        self._acars_review = ctk.CTkLabel(
            acars_content, text="Rev:--",
            font=FONT_SMALL, text_color=TEXT_DIM,
            anchor="e")
        self._acars_review.pack(side="right", padx=(4, 4))

        self._acars_mie = ctk.CTkLabel(
            acars_content, text="",
            font=FONT_SMALL_BOLD, text_color=AMBER,
            anchor="e")
        self._acars_mie.pack(side="right", padx=(4, 4))

        # ── Bottom pane ──
        bot_pane = tk.Frame(self._vsplit, bg=BG_APP)
        self._bot_pane = bot_pane

        # EICAS
        eicas_outer = ctk.CTkFrame(bot_pane, fg_color=BG_PANEL, corner_radius=8,
                                   border_width=1, border_color=BORDER)
        eicas_outer.pack(fill="x", pady=(0, 3))

        eicas_hdr = ctk.CTkLabel(eicas_outer, text="EICAS",
                                 font=FONT_SMALL_BOLD,
                                 text_color=TEXT_DIM)
        eicas_hdr.pack(anchor="w", padx=10, pady=(4, 0))

        self._eicas_inner = ctk.CTkFrame(eicas_outer, fg_color="transparent")
        self._eicas_inner.pack(fill="x", padx=6, pady=(0, 6))
        for i in range(4):
            self._eicas_inner.columnconfigure(i, weight=1)

        # Kalman Strip
        self._strip = KalmanStrip(bot_pane, d["positions"],
                                  self._select_stock, height=52)
        self._strip.pack(fill="x", pady=(0, 3))

        # Status Bar
        self._status_frame = ctk.CTkFrame(bot_pane, fg_color="transparent")
        self._status_frame.pack(fill="x", pady=(0, 3))

        # Add panes to vertical split
        self._vsplit.add(top_pane, minsize=250)
        self._vsplit.add(bot_pane, minsize=150, height=260)

        # Show idle overlay if no positions at startup
        if not self._data.get("positions"):
            self._show_idle_overlay()

    # ------------------------------------------------------------------
    #  IDLE OVERLAY
    # ------------------------------------------------------------------

    def _show_idle_overlay(self):
        """Show aviation-themed idle state overlay when no positions exist."""
        if self._idle_overlay is not None:
            return  # already showing

        self._idle_overlay = ctk.CTkFrame(self, fg_color=BG_APP)
        # Place over the _vsplit area (below top bar)
        self._idle_overlay.place(relx=0, rely=0, relwidth=1, relheight=1, y=42)

        # Center content
        center = ctk.CTkFrame(self._idle_overlay, fg_color="transparent")
        center.place(relx=0.5, rely=0.45, anchor="center")

        # Airplane icon
        ctk.CTkLabel(
            center, text="\u2708", font=(FONT_FAMILY, 48),
            text_color="#334155",
        ).pack(pady=(0, 12))

        # Primary message
        ctk.CTkLabel(
            center, text="NO ACTIVE POSITIONS",
            font=(FONT_FAMILY, 18, "bold"), text_color="#64748b",
        ).pack(pady=(0, 4))

        # Sub-message
        ctk.CTkLabel(
            center, text="Awaiting PH3 / PH5 orders",
            font=FONT_HEADING, text_color="#475569",
        ).pack(pady=(0, 16))

        # Status indicator row
        status_row = ctk.CTkFrame(center, fg_color="transparent")
        status_row.pack()
        ctk.CTkLabel(
            status_row, text="\u25cf", font=FONT_BODY,
            text_color="#94a3b8",
        ).pack(side="left", padx=(0, 4))
        ctk.CTkLabel(
            status_row,
            text="SYSTEMS NOMINAL \u2014 DATA BRIDGE CONNECTED"
                if self._data_bridge else "SYSTEMS NOMINAL \u2014 OFFLINE",
            font=FONT_TINY, text_color="#475569",
        ).pack(side="left")

    def _hide_idle_overlay(self):
        """Remove the idle overlay when positions become available."""
        if self._idle_overlay is not None:
            self._idle_overlay.destroy()
            self._idle_overlay = None

    # ------------------------------------------------------------------
    #  TIMEFRAME
    # ------------------------------------------------------------------
    def _set_timeframe(self, tf):
        self._timeframe = tf
        self._update_tf_buttons()
        pos = self._positions[self._selected]
        history_preds = self._get_history_predictions(self._selected, tf)
        self._nav_display.update_data(
            pos, list(self._positions.values()), tf,
            show_history=self._show_history,
            history_predictions=history_preds)
        if self._nav_display._last_pred:
            self._maybe_save_prediction(
                self._selected, tf, pos, self._nav_display._last_pred)
        # Refresh deviation panel if showing
        if self._show_history:
            self._destroy_deviation_panel()
            self._build_deviation_panel()

    def _update_tf_buttons(self):
        for tf, btn in self._tf_btns.items():
            if tf == self._timeframe:
                accent = CYAN if tf in self.INTRADAY_TFS else PURPLE
                btn.configure(fg_color=accent, text_color="#000000")
            else:
                btn.configure(fg_color=BG_INPUT, text_color=TEXT_DIM)

    def _update_stock_tabs(self, symbol):
        for sym, btn in self._tab_btns.items():
            pos = self._positions[sym]
            sc = GREEN if pos["status"] == "ON TRACK" else (
                AMBER if pos["status"] == "MONITOR" else RED)
            if sym == symbol:
                btn.configure(fg_color=BORDER, text_color=sc,
                              border_width=1, border_color=sc)
            else:
                btn.configure(fg_color=BG_INPUT, text_color=sc,
                              border_width=0)

    def _rebuild_stock_tabs(self):
        """Destroy and recreate stock tab buttons from current positions."""
        if hasattr(self, '_tab_btns'):
            for btn in self._tab_btns.values():
                btn.destroy()
            self._tab_btns.clear()

        if not hasattr(self, '_tab_container'):
            return

        for pos in self._data.get("positions", []):
            sym = pos["symbol"]
            sc = GREEN if pos["status"] == "ON TRACK" else (
                AMBER if pos["status"] == "MONITOR" else RED)
            btn = ctk.CTkButton(
                self._tab_container, text=f"{sym[:6]}\u25cf", width=75, height=24,
                font=FONT_SMALL, fg_color=BG_INPUT,
                hover_color=BORDER, text_color=sc, corner_radius=4,
                command=lambda s=sym: self._select_stock(s))
            btn.pack(side="left", padx=2)
            self._tab_btns[sym] = btn

    # ------------------------------------------------------------------
    #  EICAS with 5 detail rows
    # ------------------------------------------------------------------
    def _update_eicas(self, pos):
        """Destroy and recreate EICAS gauges with Pygame-rendered widgets."""
        for w in self._eicas_inner.winfo_children():
            w.destroy()

        vol = round(pos.get("volume_ratio", 0.0), 1)
        pnl_pct = round(pos.get("pnl_pct", 0.0), 2)
        plan = pos.get("plan", {})

        gauge_specs = [
            {
                "title": "FUEL (Vol)", "value": vol, "lo": 0, "hi": 3, "unit": "x",
                "zones": [(0, 27, "red"), (27, 50, "amber"), (50, 100, "green")],
                "plan_text": f"Plan: {plan.get('entry_vol', '--')}x",
                "details": [
                    ("Cur Vol", f"{vol}x"),
                    ("Exp Vol", f"{pos.get('vol_expected', '--')}x"),
                    ("Burst", str(pos.get("vol_burst", "--"))),
                    ("ADX", f"{pos.get('adx', '--')}"),
                    ("MACD-H", f"{pos.get('macd_hist', '--')}"),
                ],
            },
            {
                "title": "N1 (RSI)", "value": pos["rsi"], "lo": 0, "hi": 100, "unit": "",
                "zones": [(0, 30, "red"), (30, 70, "green"), (70, 100, "red")],
                "plan_text": "Plan: RSI<70",
                "details": [
                    ("Zone", "OB" if pos["rsi"] > 70 else ("OS" if pos["rsi"] < 30 else "Neutral")),
                    ("Stoch%K", f"{pos.get('stoch_k', '--')}"),
                    ("EMA cross", "Bull" if pos.get("ema_20", 0) > pos.get("bb_middle", 0) else "Bear"),
                    ("MA20", f"{pos.get('ema_20', '--')}"),
                    ("MA50", f"{pos.get('bb_lower', '--')}"),
                ],
            },
            {
                "title": "TEMP (ATR)", "value": round(pos.get("atr_14", 0), 1),
                "lo": 0, "hi": 40, "unit": "",
                "zones": [(0, 25, "green"), (25, 60, "amber"), (60, 100, "red")],
                "plan_text": f"Plan: ATR<{plan.get('entry_atr', '--')}",
                "details": [
                    ("Vol lvl", "High" if pos.get("atr_14", 0) > 20 else "Normal"),
                    ("BB wid", f"{round(pos.get('bb_upper', 0) - pos.get('bb_lower', 0), 1)}"),
                    ("Squeeze", "No"),
                    ("Risk/t", f"\u20b9{round(pos.get('atr_14', 0) * 1.5, 0):.0f}"),
                    ("PDH-PDL", f"{pos.get('pdh', 0) - pos.get('pdl', 0)}"),
                ],
            },
            {
                "title": "EGT (P&L)", "value": pnl_pct, "lo": -5, "hi": 5, "unit": "%",
                "zones": [(0, 40, "red"), (40, 55, "amber"), (55, 100, "green")],
                "plan_text": f"Plan: +{plan.get('pnl_target', '--')}%",
                "details": [
                    ("P&L abs", f"\u20b9{pos.get('pnl_abs', '--')}"),
                    ("Tgt %", f"+{plan.get('pnl_target', '--')}%"),
                    ("Plan RR", f"{plan.get('rr', '--')}"),
                    ("Act RR", f"{round(abs(pnl_pct / plan.get('pnl_target', 1)) * plan.get('rr', 1), 1) if plan.get('pnl_target') else '--'}"),
                    ("% done", f"{round(pnl_pct / plan.get('pnl_target', 1) * 100, 0):.0f}%" if plan.get('pnl_target') else "--"),
                ],
            },
        ]

        for col, spec in enumerate(gauge_specs):
            gw = EicasGaugeWidget(
                self._eicas_inner,
                title=spec["title"],
                value=spec["value"],
                min_val=spec["lo"],
                max_val=spec["hi"],
                unit=spec["unit"],
                zones=spec["zones"],
                plan_text=spec["plan_text"],
                details=spec["details"],
                gauge_w=200, gauge_h=160,
            )
            gw.grid(row=0, column=col, sticky="nsew", padx=3, pady=2)

    def _update_acars(self, pos):
        ai = pos.get("ai", {})
        action = ai.get("action", "HOLD")
        ac = GREEN if action == "HOLD" else (AMBER if action == "CAUTION" else RED)
        self._acars_action.configure(text=action, text_color=ac)

        # Enhance message with ensemble regime info if available
        base_msg = ai.get("msg", "--")
        er = self._nav_display._ensemble_result if hasattr(self, '_nav_display') and self._nav_display else None
        if er:
            regime_c = GREEN if er.regime == 'TRENDING' else AMBER if er.regime == 'RANDOM_WALK' else RED
            regime_txt = f"  |  {er.regime} H:{er.hurst:.2f} Conf:{er.confidence:.0%}"
            self._acars_msg.configure(text=base_msg + regime_txt)
        else:
            self._acars_msg.configure(text=base_msg)

        self._acars_conf.configure(text=f"Conf:{ai.get('conf', '--')}%")
        rev = ai.get("review")
        self._acars_review.configure(
            text=f"Rev:{rev}m" if rev else "Rev:--")
        # MIE status
        mie = "MIE" if pos.get("status") == "MONITOR" else ""
        self._acars_mie.configure(text=mie)

    # ------------------------------------------------------------------
    #  STATUS LIGHTS (blink at 600ms)
    # ------------------------------------------------------------------
    def _update_status_lights(self, pos):
        ai = pos.get("ai", {})
        action = ai.get("action", "HOLD")
        self._active_lights = set()

        if action == "HOLD":
            self._active_lights.add("HOLD")
        if action == "CAUTION" or pos.get("status") == "MONITOR":
            self._active_lights.add("CAUTION")
        if pos.get("status") == "TARGET ACHIEVED":
            self._active_lights.add("TGT ACH")
        if pos.get("status") == "LANDED":
            self._active_lights.add("LAND")

        # Set initial colors
        for name, (lbl, color) in self._light_labels.items():
            if name in self._active_lights:
                lbl.configure(text_color=color)
            else:
                lbl.configure(text_color=TEXT_DIM)

        # Start blink cycle
        self._blink_state = True
        self._start_blink()

    def _start_blink(self):
        if self._blink_after_id:
            self.after_cancel(self._blink_after_id)
        self._blink_lights()

    def _blink_lights(self):
        self._blink_state = not self._blink_state
        for name, (lbl, color) in self._light_labels.items():
            if name in self._active_lights:
                lbl.configure(text_color=color if self._blink_state else TEXT_DIM)
        self._blink_after_id = self.after(600, self._blink_lights)

    # ------------------------------------------------------------------
    #  STATUS BAR
    # ------------------------------------------------------------------
    def _update_status_bar(self, pos):
        if not pos:
            return
        if self._status_widget:
            self._status_widget.destroy()

        d = self._data
        tc = GREEN if d["tcas_advisory"] == "ALL CLEAR" else RED
        ils_color = GREEN if d["ils_on_track"] == d["ils_total"] else AMBER

        vel = pos["velocity"]
        if vel > 0.3:
            fm, fc = "▲ CLIMB", GREEN
        elif vel < -0.3:
            fm, fc = "▼ DESCENT", RED
        else:
            fm, fc = "━ CRUISE", TEXT_MUTED

        eta = pos.get("eta_minutes")
        eta_t = f"ETA ~{eta}m" if eta else "ETA --"
        eta_c = GREEN if eta and eta < 30 else AMBER if eta else TEXT_MUTED

        items = [
            (f"TCAS: {d['tcas_advisory']}", tc),
            (f"ILS {d['ils_on_track']}/{d['ils_total']}", ils_color),
            (fm, fc),
            (f"BB: {pos['bb_lower']}|{pos['bb_middle']}|{pos['bb_upper']}", TEXT_LABEL),
            (f"RSI: {pos['rsi']}", TEXT_LABEL),
            (f"ADX: {pos.get('adx', '--')}", TEXT_LABEL),
            (eta_t, eta_c),
            (f"TF: {self._timeframe}", CYAN if self._timeframe in self.INTRADAY_TFS else PURPLE),
        ]
        self._status_widget = _status_bar(self._status_frame, items)
        self._status_widget.pack(fill="x")

    # ------------------------------------------------------------------
    #  PREDICTION HISTORY
    # ------------------------------------------------------------------
    def _toggle_history(self):
        """Toggle history prediction overlay on/off."""
        self._show_history = not self._show_history
        if self._history_btn:
            if self._show_history:
                self._history_btn.configure(
                    fg_color=AMBER, text_color="#000000")
            else:
                self._history_btn.configure(
                    fg_color=BG_INPUT, text_color=TEXT_DIM)

        # Toggle deviation panel
        if self._show_history:
            self._build_deviation_panel()
        else:
            self._destroy_deviation_panel()

        # Re-render chart with/without history
        if self._selected in self._positions:
            pos = self._positions[self._selected]
            history_preds = self._get_history_predictions(
                self._selected, self._timeframe)
            self._nav_display.update_data(
                pos, list(self._positions.values()), self._timeframe,
                show_history=self._show_history,
                history_predictions=history_preds)

    def _get_history_predictions(self, symbol, timeframe):
        """Retrieve past predictions from the store."""
        if self._pred_store is None or not self._show_history:
            return []
        try:
            rows = self._pred_store.get_predictions_for_symbol(
                symbol, timeframe=timeframe, limit=10)
            return [r["prediction_points"] for r in rows
                    if r.get("prediction_points")]
        except Exception:
            return []

    def _maybe_save_prediction(self, symbol, timeframe, pos, pred_points):
        """Save prediction with 5-minute throttle per (symbol, tf)."""
        if self._pred_store is None:
            return
        key = (symbol, timeframe)
        now = datetime.datetime.now()
        last = self._last_save_time.get(key)
        if last and (now - last).total_seconds() < 300:
            return
        try:
            tf_cfg = TIMEFRAME_CONFIG.get(timeframe, {})
            self._pred_store.save_prediction(
                symbol=symbol,
                timeframe=timeframe,
                current_price=pos.get("current", 0),
                velocity=pos.get("velocity", 0),
                acceleration=pos.get("acceleration", 0),
                prediction_points=pred_points,
                ils_target=pos.get("ils_target"),
                tcas_floor=pos.get("tcas_floor"),
                kalman_scale=tf_cfg.get("kalman_scale"),
                entry=pos.get("entry"),
                atr=pos.get("atr_14", 1),
                confidence=pos.get("ai", {}).get("conf") if isinstance(
                    pos.get("ai"), dict) else None,
                trade_type=pos.get("trade_type"),
            )
            self._last_save_time[key] = now
        except Exception as e:
            print(f"[PH4Detail] Prediction save error: {e}",
                  file=sys.stderr)

    def _start_actual_recording(self):
        """Record current prices for all positions every 60 seconds."""
        if self._pred_store is not None:
            try:
                for sym, pos in self._positions.items():
                    self._pred_store.save_actual_price(
                        sym, pos.get("current", 0))
            except Exception as e:
                print(f"[PH4Detail] Actual recording error: {e}",
                      file=sys.stderr)
        self._actual_after_id = self.after(
            60_000, self._start_actual_recording)

    def _seed_mock_history(self):
        """Seed DB with mock historical predictions (once)."""
        if self._pred_store is None:
            return
        flag_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "..", ".pred_seeded")
        if os.path.exists(flag_path):
            return
        try:
            import random
            for pos in self._data.get("positions", []):
                sym = pos["symbol"]
                cur = pos.get("current", 900)
                vel_base = pos.get("velocity", 1.0)
                acc_base = pos.get("acceleration", 0.05)
                for tf_key in ["15m", "30m", "1hr"]:
                    tf_cfg = TIMEFRAME_CONFIG.get(tf_key)
                    if not tf_cfg:
                        continue
                    for age in range(5):
                        offset = random.uniform(-0.5, 0.5)
                        mock_pred = []
                        step = max(1, round(tf_cfg["prediction"] / 10))
                        t = 0
                        while t <= tf_cfg["prediction"]:
                            p = cur + (vel_base + offset) * t + (
                                0.5 * acc_base * t * t)
                            mock_pred.append(
                                {"t": t, "p": round(p, 2)})
                            t += step
                        self._pred_store.save_prediction(
                            symbol=sym,
                            timeframe=tf_key,
                            current_price=cur + offset * 2,
                            velocity=vel_base + offset,
                            acceleration=acc_base,
                            prediction_points=mock_pred,
                            ils_target=pos.get("ils_target"),
                            tcas_floor=pos.get("tcas_floor"),
                            kalman_scale=tf_cfg.get("kalman_scale"),
                            entry=pos.get("entry"),
                            atr=pos.get("atr_14", 1),
                            trade_type=pos.get("trade_type"),
                        )
                        # Save mock actuals too
                        for mt in range(0, tf_cfg["prediction"], 5):
                            ap = cur + (vel_base + 0.3) * mt + (
                                0.5 * (acc_base + 0.02) * mt * mt)
                            ap += random.uniform(-2, 2)
                            self._pred_store.save_actual_price(
                                sym, round(ap, 2))
            # Write flag
            with open(flag_path, "w") as f:
                f.write("seeded")
        except Exception as e:
            print(f"[PH4Detail] Mock seed error: {e}", file=sys.stderr)

    def _build_deviation_panel(self):
        """Show deviation analysis panel below EICAS."""
        if self._deviation_panel is not None:
            return
        if self._pred_store is None or self._bot_pane is None:
            return

        self._deviation_panel = ctk.CTkFrame(
            self._bot_pane, fg_color=BG_PANEL, corner_radius=8,
            border_width=1, border_color=BORDER, height=60)
        self._deviation_panel.pack(fill="x", pady=(0, 3),
                                   before=self._strip)
        self._deviation_panel.pack_propagate(False)

        row = ctk.CTkFrame(self._deviation_panel, fg_color="transparent")
        row.pack(fill="x", padx=8, pady=6)

        # Header
        ctk.CTkLabel(row, text="\u2505 PREDICTION ACCURACY",
                     font=FONT_TINY_BOLD,
                     text_color=HISTORY_PRED).pack(side="left", padx=(0, 10))

        try:
            summary = self._pred_store.get_calibration_summary(
                symbol=self._selected, timeframe=self._timeframe,
                last_n=20)
        except Exception:
            summary = None

        if summary and summary.get("count", 0) > 0:
            avg_err = summary.get("avg_error_pct", 0)
            max_err = summary.get("max_error_pct", 0)
            dir_acc = summary.get("direction_accuracy", 0)
            suggestion = summary.get("suggestion", "")

            err_color = GREEN if avg_err < 1.0 else (
                AMBER if avg_err < 2.0 else RED)
            dir_color = GREEN if dir_acc >= 70 else (
                AMBER if dir_acc >= 50 else RED)

            for text, color in [
                (f"Avg: {avg_err:.1f}%", err_color),
                (f"Max: {max_err:.1f}%", TEXT_DIM),
                (f"Dir: {dir_acc:.0f}%", dir_color),
                (suggestion[:60], TEXT_DIM),
            ]:
                ctk.CTkLabel(row, text=text,
                             font=FONT_TINY,
                             text_color=color).pack(
                    side="left", padx=6)
        else:
            ctk.CTkLabel(row,
                         text="Recording predictions\u2026 need more data.",
                         font=FONT_TINY,
                         text_color=TEXT_DIM).pack(side="left", padx=6)

    def _destroy_deviation_panel(self):
        """Hide and destroy deviation panel."""
        if self._deviation_panel is not None:
            self._deviation_panel.pack_forget()
            self._deviation_panel.destroy()
            self._deviation_panel = None

    # ------------------------------------------------------------------
    #  SELECT STOCK
    # ------------------------------------------------------------------
    def _select_stock(self, symbol):
        if symbol not in self._positions:
            return
        self._selected = symbol
        pos = self._positions[symbol]

        # Reset timeframe to trade type default
        tt = pos.get("trade_type", "CNC")
        self._timeframe = TRADE_TYPE_DEFAULTS.get(tt, "1hr")

        # Update UI
        self._update_stock_tabs(symbol)
        self._update_tf_buttons()

        # Update flight instruments
        self._attitude.update_data(pos)
        self._speed_tape.update_data(pos)
        self._alt_tape.update_data(pos)
        self._heading_strip.update_data(pos)
        history_preds = self._get_history_predictions(
            symbol, self._timeframe)
        self._nav_display.update_data(
            pos, list(self._positions.values()), self._timeframe,
            show_history=self._show_history,
            history_predictions=history_preds)
        # Save prediction to history store
        if self._nav_display._last_pred:
            self._maybe_save_prediction(
                symbol, self._timeframe, pos,
                self._nav_display._last_pred)

        # EICAS, ACARS, lights, status bar
        self._update_eicas(pos)
        self._update_acars(pos)
        self._update_status_lights(pos)
        self._update_status_bar(pos)

        # Refresh deviation panel if showing
        if self._show_history:
            self._destroy_deviation_panel()
            self._build_deviation_panel()

    # ------------------------------------------------------------------
    #  LIVE DATA WIRING
    # ------------------------------------------------------------------

    def _try_live_data(self):
        """Try to get live data immediately on init."""
        if self._data_bridge:
            data = self._data_bridge.get_latest()
            if data and data.db_available:
                self._on_live_data(data)   # handles both empty and populated

    def _on_live_data(self, data):
        """Callback from DataBridge — convert LiveData to cockpit format."""
        if not data or not data.db_available:
            return

        if not data.positions:
            # No open positions — revert to idle state
            if self._positions:  # only if we were previously active
                self._data = {
                    "positions": [], "tcas_advisory": "STANDBY",
                    "ils_on_track": 0, "ils_total": 0,
                }
                self._using_live = True    # still live, just empty
                self._refresh_all_instruments()
            return

        try:
            cockpit_data = self._convert_live_to_cockpit(data)
            if cockpit_data and cockpit_data.get("positions"):
                self._data = cockpit_data
                self._using_live = True
                self._refresh_all_instruments()
        except Exception as e:
            import logging
            logging.getLogger("GlassCockpit").debug(f"Live data conversion: {e}")

    def _convert_live_to_cockpit(self, data):
        """Convert LiveData positions to GLASS_COCKPIT_MOCK format."""
        positions = []

        for pos in data.positions:
            meta = pos.metadata or {}
            symbol = pos.symbol

            # Find AI decision for this symbol
            ai_decision = None
            for dec in data.decisions_recent:
                if dec.symbol == symbol:
                    ai_decision = dec
                    break
            if not ai_decision:
                for dec in data.chatgpt_decisions:
                    if dec.symbol == symbol:
                        ai_decision = dec
                        break

            entry = pos.entry_price or 0
            current = pos.current_price or entry

            pnl_pct = ((current - entry) / entry * 100) if entry > 0 else 0
            pnl_abs = pos.unrealized_pnl or (current - entry) * (pos.quantity or 1)

            vel = meta.get('kalman_velocity', meta.get('velocity', 0))
            acc = meta.get('kalman_acceleration', meta.get('acceleration', 0))
            atr = meta.get('atr', meta.get('atr_at_entry', 1))

            rsi = meta.get('rsi', meta.get('rsi_14', 50))
            adx = meta.get('adx', 20)
            vol_ratio = meta.get('volume_ratio', meta.get('vol_ratio', 1.0))

            ema20 = meta.get('ema20', meta.get('ema_20', current))
            ma20 = meta.get('ma20', meta.get('sma_20', ema20))
            ma50 = meta.get('ma50', meta.get('sma_50', current * 0.98))

            bbU = meta.get('bb_upper', meta.get('bbU', current * 1.02))
            bbM = meta.get('bb_middle', meta.get('bbM', current))
            bbL = meta.get('bb_lower', meta.get('bbL', current * 0.98))

            pdh = meta.get('pdh', meta.get('prev_day_high', current * 1.01))
            pdl = meta.get('pdl', meta.get('prev_day_low', current * 0.99))

            ils_target = pos.target_price or meta.get('target_price', current * 1.03)
            tcas_floor = pos.stop_price or meta.get('stop_price', current * 0.97)

            session_high = meta.get('session_high', max(current, entry))
            session_low = meta.get('session_low', min(current, entry))
            fib_range = session_high - session_low if session_high != session_low else 1

            ema_dist = (current - ema20) / atr if atr > 0 else 0
            pitch = max(-45, min(45, ema_dist * 15))
            bank = max(-30, min(30, (vel / atr * 30) if atr > 0 else 0))

            status = "ON TRACK" if pnl_pct >= 0 else "MONITOR"
            if pnl_pct < -2:
                status = "WARNING"

            source = meta.get('source', meta.get('entry_phase', 'CNC'))
            trade_type = "CNC"
            if "PH5" in str(source) and "GAP" in str(source).upper():
                trade_type = "PH5_GAP"
            elif "PH5A" in str(source):
                trade_type = "PH5A_MIS"
            elif "PH8" in str(source):
                trade_type = "PH8_MOMENTUM"
            elif "MCX" in str(source) or "PH7" in str(source):
                trade_type = "PH7_MCX"

            history = meta.get('price_history', [])
            if not history:
                elapsed = meta.get('hold_duration_min', 30)
                history = [
                    {"t": 0, "p": entry},
                    {"t": max(1, elapsed), "p": current},
                ]

            ai_action, ai_conf, ai_msg, ai_rev = "N/A", 0, "No AI data available", 0
            if ai_decision:
                ai_action = ai_decision.decision or "HOLD"
                ai_conf = ai_decision.confidence or 0
                ai_msg = ai_decision.reason or ""

            ensemble = meta.get('ensemble_prediction', {})
            kD = meta.get('kalman_daily', {"vel": 0, "acc": 0})
            kH = meta.get('kalman_hourly', {"vel": vel * 60, "acc": acc * 3600})

            entry_time_str = ""
            if pos.entry_time:
                entry_time_str = str(pos.entry_time)

            stock = {
                "symbol": symbol, "status": status, "trade_type": trade_type,
                "current": current, "entry": entry, "vel": vel, "acc": acc,
                "ils": ils_target, "tcas": tcas_floor,
                "eta": meta.get('eta_minutes', None),
                "pitch": pitch, "bank": bank,
                "ema20": ema20, "ma20": ma20, "ma50": ma50,
                "bbU": bbU, "bbM": bbM, "bbL": bbL,
                "rsi": rsi, "atr": atr, "adx": adx,
                "volRatio": vol_ratio,
                "volExp": meta.get('expected_volume', 1.0),
                "volBurst": "BUY" if vel > 0 else "SELL",
                "macdH": meta.get('macd_histogram', 0),
                "stochK": meta.get('stoch_k', 50),
                "pnl": round(pnl_pct, 2), "pnlAbs": round(pnl_abs, 0),
                "planTgt": ils_target, "planSL": tcas_floor,
                "planRR": meta.get('planned_rr', 2.0),
                "planPnl": meta.get('target_pnl_pct', 3.0),
                "pdh": pdh, "pdl": pdl,
                "entryTime": entry_time_str, "currentTime": "",
                "fib": {
                    "236": round(session_low + fib_range * 0.236, 2),
                    "382": round(session_low + fib_range * 0.382, 2),
                    "500": round(session_low + fib_range * 0.500, 2),
                    "618": round(session_low + fib_range * 0.618, 2),
                    "786": round(session_low + fib_range * 0.786, 2),
                },
                "fibD": meta.get('fib_daily', {}),
                "lvlD": meta.get('levels_daily', {}),
                "kD": kD, "kH": kH,
                "history": history,
                "daily": meta.get('daily_closes', []),
                "ai": {"action": ai_action, "conf": ai_conf, "msg": ai_msg, "rev": ai_rev},
                "ensemble": ensemble,
            }
            positions.append(stock)

        return {
            "positions": positions,
            "tcas_advisory": "ALL CLEAR",
            "ils_on_track": sum(1 for p in positions if p["pnl"] >= 0),
            "ils_total": len(positions),
        }

    def _refresh_all_instruments(self):
        """Redraw all cockpit instruments with current data."""
        positions = self._data.get("positions", [])
        self._positions = {p["symbol"]: p for p in positions}

        # --- EMPTY STATE: show overlay, reset to standby ---
        if not positions:
            self._selected = None
            self._show_idle_overlay()
            if self._source_label:
                self._source_label.configure(
                    text="\u25cf STANDBY", text_color="#94a3b8")
            self._rebuild_stock_tabs()     # clears all tabs
            # Reset ACARS to idle
            if hasattr(self, '_acars_action') and self._acars_action:
                try:
                    self._acars_action.configure(text="STBY", text_color="#94a3b8")
                    self._acars_msg.configure(text="No active positions")
                    self._acars_conf.configure(text="Conf:--")
                    self._acars_review.configure(text="Rev:--")
                except Exception:
                    pass
            # Dim all status lights
            for name, (lbl, color) in self._light_labels.items():
                lbl.configure(text_color=TEXT_DIM)
            self._active_lights.clear()
            return

        # --- ACTIVE STATE: hide overlay, update instruments ---
        self._hide_idle_overlay()

        # Ensure selected stock is valid
        if self._selected not in self._positions:
            self._selected = positions[0]["symbol"]

        # Update source indicator
        if self._source_label:
            if self._using_live:
                self._source_label.configure(text="\u25cf LIVE", text_color="#22c55e")
            else:
                self._source_label.configure(text="\u25cf MOCK", text_color="#f59e0b")

        # Rebuild stock tabs
        self._rebuild_stock_tabs()

        # Rebuild KalmanStrip with new positions
        if hasattr(self, '_strip') and self._strip:
            self._strip.destroy()
        if self._bot_pane:
            self._strip = KalmanStrip(
                self._bot_pane, positions,
                self._select_stock, height=52)
            self._strip.pack(fill="x", pady=(0, 3),
                             before=self._status_frame)

        # Re-select current stock to refresh all flight instruments
        if self._selected in self._positions:
            self._select_stock(self._selected)

    # ------------------------------------------------------------------
    #  CLEANUP
    # ------------------------------------------------------------------
    def destroy(self):
        if self._blink_after_id:
            self.after_cancel(self._blink_after_id)
            self._blink_after_id = None
        if self._actual_after_id:
            self.after_cancel(self._actual_after_id)
            self._actual_after_id = None
        if self._pred_store:
            try:
                self._pred_store.close()
            except Exception:
                pass
        super().destroy()



# ==========================================================================
#  PH6 DETAIL -- OPTIONS SHADOW
# ==========================================================================

class PH6Detail(ctk.CTkFrame):

    def __init__(self, parent, on_back, data_bridge=None):
        super().__init__(parent, fg_color="transparent")
        self._on_back = on_back
        self._data_bridge = data_bridge
        self._data = PH6_MOCK.copy()
        self._build()

        if self._data_bridge:
            self._data_bridge.register_callback(self, self._on_live_data)
            self.after(500, self._try_live)

    def _try_live(self):
        if self._data_bridge:
            live = self._data_bridge.get_latest()
            if live and live.db_available:
                self._on_live_data(live)

    def _on_live_data(self, live):
        if not live or not live.db_available:
            return
        try:
            ph6 = self._data_bridge.get_ph6_data()
            if ph6:
                if "shadow_pnl" in ph6:
                    self._data["shadow_pnl"] = ph6["shadow_pnl"]
                self._refresh_display()
        except Exception:
            pass

    def _refresh_display(self):
        for w in self.winfo_children():
            w.destroy()
        self._build()

    def _build(self):
        d = self._data

        _back_button(self, self._on_back).pack(anchor="w", padx=8, pady=(4, 4))
        _title_bar(self, "PH6 . OPTIONS SHADOW -- PAPER FLIGHT").pack(
            fill="x", padx=8, pady=(0, 4))

        content = ctk.CTkFrame(self, fg_color="transparent")
        content.pack(fill="both", expand=True, padx=8, pady=(0, 4))
        content.columnconfigure(0, weight=2)
        content.columnconfigure(1, weight=3)
        content.rowconfigure(0, weight=1)

        # -- Left: SHADOW STATUS --
        left = _instrument_panel(content, "SHADOW STATUS")
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 4))

        info = ctk.CTkFrame(left, fg_color=BG_INPUT, corner_radius=6)
        info.pack(fill="x", padx=10, pady=(8, 4))

        _stat_row(info, "Mode", d["mode"], AMBER)
        pnl_color = GREEN if d["shadow_pnl"] >= 0 else RED
        _stat_row(info, "Shadow P&L", f"+Rs.{d['shadow_pnl']:,}", pnl_color)
        _stat_row(info, "Trades Today", str(d["trades_today"]))

        # Greeks gauge
        gauge_frame = ctk.CTkFrame(left, fg_color="transparent")
        gauge_frame.pack(pady=(8, 4))
        AviationGauge(
            gauge_frame, "Net Delta", int(d["net_delta"] * 100),
            0, 100, "",
            zones=[(0, 30, "green"), (30, 70, "amber"), (70, 100, "red")],
            canvas_bg=BG_PANEL,
        ).pack()

        greeks_frame = ctk.CTkFrame(left, fg_color=BG_INPUT, corner_radius=6)
        greeks_frame.pack(fill="x", padx=10, pady=(4, 8))
        _stat_row(greeks_frame, "Net Delta", f"{d['net_delta']:.2f}", AMBER)
        _stat_row(greeks_frame, "Net Theta", f"{d['net_theta']:.2f}", RED)

        # -- Right: MIRRORED POSITIONS --
        right = _instrument_panel(content, "MIRRORED POSITIONS")
        right.grid(row=0, column=1, sticky="nsew", padx=(4, 0))

        for pos in d["positions"]:
            self._build_option_card(right, pos)

    def _build_option_card(self, parent, pos):
        card = ctk.CTkFrame(parent, fg_color=BG_INPUT, corner_radius=6)
        card.pack(fill="x", padx=10, pady=(6, 2))

        # Header
        hdr = ctk.CTkFrame(card, fg_color="transparent")
        hdr.pack(fill="x", padx=10, pady=(6, 2))
        ctk.CTkLabel(hdr, text=f"{pos['symbol']} {pos['strike']} {pos['expiry']}",
                     font=FONT_BODY_BOLD,
                     text_color=TEXT_PRIMARY).pack(side="left")
        ctk.CTkLabel(hdr, text=f"Rs.{pos['premium']:.2f}",
                     font=FONT_BODY_BOLD,
                     text_color=CYAN).pack(side="right")

        # Greeks
        greeks = ctk.CTkFrame(card, fg_color="transparent")
        greeks.pack(fill="x", padx=10, pady=2)
        ctk.CTkLabel(greeks, text=f"Delta: {pos['delta']:.2f}",
                     font=FONT_SMALL,
                     text_color=TEXT_MUTED).pack(side="left", padx=(0, 16))
        ctk.CTkLabel(greeks, text=f"Theta: {pos['theta']:.1f}",
                     font=FONT_SMALL,
                     text_color=TEXT_MUTED).pack(side="left")

        # Shadow P&L
        pnl_c = GREEN if pos["shadow_pnl"] >= 0 else RED
        ctk.CTkLabel(card, text=f"Shadow P&L: +Rs.{pos['shadow_pnl']:,}",
                     font=FONT_SMALL_BOLD,
                     text_color=pnl_c).pack(padx=10, pady=(2, 6), anchor="w")


# ==========================================================================
#  PH7 DETAIL -- MCX COMMODITIES
# ==========================================================================

class PH7Detail(ctk.CTkFrame):

    def __init__(self, parent, on_back, data_bridge=None):
        super().__init__(parent, fg_color="transparent")
        self._on_back = on_back
        self._data_bridge = data_bridge
        self._data = PH7_MOCK.copy()
        self._build()

        if self._data_bridge:
            self._data_bridge.register_callback(self, self._on_live_data)
            self.after(500, self._try_live)

    def _try_live(self):
        if self._data_bridge:
            live = self._data_bridge.get_latest()
            if live and live.db_available:
                self._on_live_data(live)

    def _on_live_data(self, live):
        if not live or not live.db_available:
            return
        try:
            ph7 = self._data_bridge.get_ph7_data()
            if ph7:
                if "active_positions" in ph7:
                    self._data["evening_trades"] = ph7["active_positions"]
                self._refresh_display()
        except Exception:
            pass

    def _refresh_display(self):
        for w in self.winfo_children():
            w.destroy()
        self._build()

    def _build(self):
        d = self._data

        _back_button(self, self._on_back).pack(anchor="w", padx=8, pady=(4, 4))
        _title_bar(self, "PH7 . MCX -- EVENING SORTIE").pack(
            fill="x", padx=8, pady=(0, 4))

        content = ctk.CTkFrame(self, fg_color="transparent")
        content.pack(fill="both", expand=True, padx=8, pady=(0, 4))
        content.columnconfigure(0, weight=2)
        content.columnconfigure(1, weight=3)
        content.rowconfigure(0, weight=1)

        # -- Left: SESSION STATUS --
        left = _instrument_panel(content, "SESSION STATUS")
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 4))

        info = ctk.CTkFrame(left, fg_color=BG_INPUT, corner_radius=6)
        info.pack(fill="x", padx=10, pady=(8, 4))

        sess_color = RED if d["session"] == "CLOSED" else GREEN
        _stat_row(info, "Session", d["session"], sess_color)
        _stat_row(info, "Opens", d["opens"], AMBER)
        _stat_row(info, "Countdown", d["countdown"], AMBER)
        _stat_row(info, "Mode", d["mode"], TEXT_LABEL)
        _stat_row(info, "Evening Trades", str(d["evening_trades"]))

        # Countdown gauge
        gauge_frame = ctk.CTkFrame(left, fg_color="transparent")
        gauge_frame.pack(pady=(8, 8))
        AviationGauge(
            gauge_frame, "Session", 0, 0, 100, "%",
            zones=[(0, 30, "red"), (30, 70, "amber"), (70, 100, "green")],
            canvas_bg=BG_PANEL,
        ).pack()

        # -- Right: INSTRUMENTS SCANNING --
        right = _instrument_panel(content, "INSTRUMENTS SCANNING")
        right.grid(row=0, column=1, sticky="nsew", padx=(4, 0))

        # Table header
        hdr = ctk.CTkFrame(right, fg_color=BG_HEADER, corner_radius=0, height=28)
        hdr.pack(fill="x", padx=8, pady=(6, 0))
        hdr.pack_propagate(False)
        for text, w in [("INSTRUMENT", 100), ("PRICE", 100), ("SPREAD", 70)]:
            ctk.CTkLabel(hdr, text=text, font=FONT_TINY_BOLD,
                         text_color=TEXT_MUTED, width=w, anchor="w").pack(side="left", padx=6)

        # Table rows
        for inst in d["instruments"]:
            row = ctk.CTkFrame(right, fg_color="transparent", height=28)
            row.pack(fill="x", padx=8, pady=1)
            row.pack_propagate(False)

            ctk.CTkLabel(row, text=inst["name"],
                         font=FONT_BODY_BOLD,
                         text_color=TEXT_PRIMARY, width=100, anchor="w").pack(side="left", padx=6)
            ctk.CTkLabel(row, text=f"Rs.{inst['price']:,}",
                         font=FONT_BODY,
                         text_color=TEXT_LABEL, width=100, anchor="w").pack(side="left", padx=6)
            ctk.CTkLabel(row, text=f"{inst['spread']}",
                         font=FONT_BODY,
                         text_color=TEXT_MUTED, width=70, anchor="w").pack(side="left", padx=6)

        # Strategy footer
        ctk.CTkFrame(right, fg_color=BORDER_DIM, height=1).pack(fill="x", padx=8, pady=(8, 4))
        ctk.CTkLabel(right, text=f"Strategy: {d['strategy']}",
                     font=FONT_SMALL,
                     text_color=TEXT_DIM).pack(padx=12, pady=(0, 8), anchor="w")


# ==========================================================================
#  PH8 DETAIL -- MOMENTUM TRADE
# ==========================================================================

class PH8Detail(ctk.CTkFrame):

    def __init__(self, parent, on_back, data_bridge=None):
        super().__init__(parent, fg_color="transparent")
        self._on_back = on_back
        self._data_bridge = data_bridge
        self._data = PH8_MOCK.copy()
        self._build()

        if self._data_bridge:
            self._data_bridge.register_callback(self, self._on_live_data)
            self.after(500, self._try_live)

    def _try_live(self):
        if self._data_bridge:
            live = self._data_bridge.get_latest()
            if live and live.db_available:
                self._on_live_data(live)

    def _on_live_data(self, live):
        if not live or not live.db_available:
            return
        try:
            ph8 = self._data_bridge.get_ph8_data()
            if ph8:
                if "active_positions" in ph8:
                    self._data["above_threshold"] = ph8["active_positions"]
                self._refresh_display()
        except Exception:
            pass

    def _refresh_display(self):
        for w in self.winfo_children():
            w.destroy()
        self._build()

    def _build(self):
        d = self._data

        _back_button(self, self._on_back).pack(anchor="w", padx=8, pady=(4, 4))
        _title_bar(self, "PH8 . MOMENTUM -- AFTERBURNER").pack(
            fill="x", padx=8, pady=(0, 4))

        content = ctk.CTkFrame(self, fg_color="transparent")
        content.pack(fill="both", expand=True, padx=8, pady=(0, 4))
        content.columnconfigure(0, weight=2)
        content.columnconfigure(1, weight=3)
        content.rowconfigure(0, weight=1)

        # -- Left: MOMENTUM RADAR --
        left = _instrument_panel(content, "MOMENTUM RADAR")
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 4))

        gauge_frame = ctk.CTkFrame(left, fg_color="transparent")
        gauge_frame.pack(pady=(8, 4))
        AviationGauge(
            gauge_frame, "Score Threshold", d["score_threshold"], 0, 100, "",
            zones=[(0, 50, "red"), (50, 75, "amber"), (75, 100, "green")],
            canvas_bg=BG_PANEL,
        ).pack()

        info = ctk.CTkFrame(left, fg_color=BG_INPUT, corner_radius=6)
        info.pack(fill="x", padx=10, pady=(4, 8))

        _stat_row(info, "Scanning", f"{d['scanning']} stocks")
        _stat_row(info, "Above Threshold", str(d["above_threshold"]), GREEN)
        _stat_row(info, "Signals Today", str(d["signals_today"]), CYAN)
        _stat_row(info, "Entry Signals", f"{d['entry_signals']} pending", AMBER)

        # -- Right: BREAKOUT CANDIDATES --
        right = _instrument_panel(content, "BREAKOUT CANDIDATES")
        right.grid(row=0, column=1, sticky="nsew", padx=(4, 0))

        # Table header
        hdr = ctk.CTkFrame(right, fg_color=BG_HEADER, corner_radius=0, height=28)
        hdr.pack(fill="x", padx=8, pady=(6, 0))
        hdr.pack_propagate(False)
        for text, w in [("SYMBOL", 110), ("SCORE", 70), ("ADX", 70)]:
            ctk.CTkLabel(hdr, text=text, font=FONT_TINY_BOLD,
                         text_color=TEXT_MUTED, width=w, anchor="w").pack(side="left", padx=6)

        # Table rows
        for cand in d["candidates"]:
            row = ctk.CTkFrame(right, fg_color="transparent", height=28)
            row.pack(fill="x", padx=8, pady=1)
            row.pack_propagate(False)

            ctk.CTkLabel(row, text=cand["symbol"],
                         font=FONT_BODY_BOLD,
                         text_color=TEXT_PRIMARY, width=110, anchor="w").pack(side="left", padx=6)

            sc = GREEN if cand["score"] >= d["score_threshold"] else AMBER
            ctk.CTkLabel(row, text=str(cand["score"]),
                         font=FONT_BODY_BOLD,
                         text_color=sc, width=70, anchor="w").pack(side="left", padx=6)

            ctk.CTkLabel(row, text=str(cand["adx"]),
                         font=FONT_BODY,
                         text_color=TEXT_LABEL, width=70, anchor="w").pack(side="left", padx=6)

        # Approaching info
        ctk.CTkFrame(right, fg_color=BORDER_DIM, height=1).pack(fill="x", padx=8, pady=(8, 4))
        app_frame = ctk.CTkFrame(right, fg_color=BG_INPUT, corner_radius=6)
        app_frame.pack(fill="x", padx=10, pady=(0, 8))
        ctk.CTkLabel(app_frame, text=d["approaching"],
                     font=FONT_SMALL_BOLD,
                     text_color=AMBER).pack(padx=10, pady=6, anchor="w")


# ==========================================================================
#  PH1 DETAIL — STOCK SELECTION RADAR  (v5.6.2)
# ==========================================================================

class PH1Detail(ctk.CTkFrame):

    def __init__(self, parent, on_back, data_bridge=None):
        super().__init__(parent, fg_color="transparent")
        self._on_back = on_back
        self._data_bridge = data_bridge
        self._data = {}  # empty init — real data arrives via DataBridge
        self._data_fingerprint = ""  # skip refresh when data unchanged
        self._build()

        if self._data_bridge:
            self._data_bridge.register_callback(self, self._on_live_data)
            self.after(500, self._try_live)

    @staticmethod
    def _fingerprint(d: dict) -> str:
        """Quick hash of key fields — skip rebuild if unchanged."""
        syms = tuple(s.get("symbol", "") for s in d.get("stocks", []))
        return f"{d.get('scan_time')}|{d.get('selected_count')}|{syms}"

    def _try_live(self):
        if self._data_bridge:
            try:
                ph1 = self._data_bridge.get_ph1_data_v2()
                if ph1:
                    fp = self._fingerprint(ph1)
                    if fp != self._data_fingerprint:
                        self._data = ph1
                        self._data_fingerprint = fp
                        self._refresh_display()
            except Exception:
                pass

    def _on_live_data(self, live):
        try:
            ph1 = self._data_bridge.get_ph1_data_v2()
            if ph1:
                fp = self._fingerprint(ph1)
                if fp != self._data_fingerprint:
                    self._data = ph1
                    self._data_fingerprint = fp
                    self._refresh_display()
        except Exception:
            pass

    def _refresh_display(self):
        for w in self.winfo_children():
            w.destroy()
        self._build()

    def _build(self):
        d = self._data

        _back_button(self, self._on_back).pack(anchor="w", padx=8, pady=(4, 4))
        _title_bar(self, "PH1 . STOCK SELECTION -- RADAR").pack(
            fill="x", padx=8, pady=(0, 4))

        content = ctk.CTkFrame(self, fg_color="transparent")
        content.pack(fill="both", expand=True, padx=8, pady=(0, 4))
        content.columnconfigure(0, weight=2)
        content.columnconfigure(1, weight=3)
        content.rowconfigure(0, weight=1)   # top row: funnel + table
        content.rowconfigure(1, weight=0)   # bottom row: filter gauges

        # -- Row 0, Col 0: SELECTION FUNNEL --
        left_top = _instrument_panel(content, "SELECTION FUNNEL")
        left_top.grid(row=0, column=0, sticky="nsew", padx=(0, 4), pady=(0, 2))
        self._build_funnel(left_top, d)

        # -- Row 0, Col 1: SELECTED STOCKS (full detail table) --
        right_top = _instrument_panel(content, "SELECTED STOCKS")
        right_top.grid(row=0, column=1, sticky="nsew", padx=(4, 0), pady=(0, 2))
        self._build_stocks_table(right_top, d)

        # -- Row 1, Col 0-1: FILTER PIPELINE gauges (full width) --
        bot = _instrument_panel(content, "FILTER PIPELINE")
        bot.grid(row=1, column=0, columnspan=2, sticky="nsew", pady=(2, 0))
        self._build_filter_gauges(bot, d)

    # ── PH1 sub-panels ─────────────────────────────────────────────

    def _build_funnel(self, panel, d):
        """Selection funnel gauge + stats."""
        total = d.get("total_scanned", 0) or 1
        selected = d.get("selected_count", 0)
        rate = int(selected / total * 100) if total > 0 else 0

        gauge_frame = ctk.CTkFrame(panel, fg_color="transparent")
        gauge_frame.pack(pady=(8, 4))
        AviationGauge(
            gauge_frame, "Selection Rate", rate, 0, 100, "%",
            zones=[(0, 3, "red"), (3, 8, "amber"), (8, 100, "green")],
            canvas_bg=BG_PANEL,
        ).pack()

        info = ctk.CTkFrame(panel, fg_color=BG_INPUT, corner_radius=6)
        info.pack(fill="x", padx=10, pady=(4, 8))

        _stat_row(info, "Total Scanned", str(d.get("total_scanned", 0)))
        funnel = d.get("filter_funnel", {})
        for stage, count in funnel.items():
            if stage != "total":
                _stat_row(info, f"  {stage}", str(count), AMBER)
        _stat_row(info, "Final Selected", str(selected), GREEN)
        _stat_row(info, "Scan Time", d.get("scan_time", "--"))
        _stat_row(info, "Next Scan", d.get("next_scan", "--"))

        if d.get("phase1_complete"):
            _stat_row(info, "PH1 Status", "COMPLETE", GREEN)
        if d.get("phase2_started"):
            _stat_row(info, "PH2 Status", "MONITORING", CYAN)

    def _build_stocks_table(self, panel, d):
        """Full detail table — one row per stock, all key info at a glance."""
        stocks = d.get("stocks", [])
        if not stocks:
            ctk.CTkLabel(panel, text="No selections yet today",
                         font=FONT_SMALL, text_color=TEXT_DIM).pack(
                             pady=20)
            return

        # -- Header row --
        cols = [("SYMBOL", 90), ("LTP", 60), ("STRATEGY", 80), ("SCORE", 45),
                ("TREND", 80), ("SECTOR", 100), ("WEEKLY", 65), ("V-RECOVERY", 95)]
        hdr = ctk.CTkFrame(panel, fg_color=BG_HEADER, corner_radius=0, height=26)
        hdr.pack(fill="x", padx=6, pady=(6, 0))
        hdr.pack_propagate(False)
        for text, w in cols:
            ctk.CTkLabel(hdr, text=text, font=FONT_TINY_BOLD,
                         text_color=TEXT_MUTED, width=w, anchor="w").pack(
                             side="left", padx=3)

        # -- Data rows --
        for stk in stocks:
            row = ctk.CTkFrame(panel, fg_color=BG_INPUT, corner_radius=4, height=32)
            row.pack(fill="x", padx=6, pady=2)
            row.pack_propagate(False)

            # Symbol
            ctk.CTkLabel(row, text=stk.get("symbol", ""),
                         font=FONT_TINY_BOLD,
                         text_color=TEXT_PRIMARY, width=90, anchor="w").pack(
                             side="left", padx=3)

            # LTP
            ltp = stk.get("ltp", stk.get("price", 0))
            ctk.CTkLabel(row, text=f"{ltp:.1f}",
                         font=FONT_TINY,
                         text_color=TEXT_LABEL, width=60, anchor="w").pack(
                             side="left", padx=3)

            # Strategy
            strat = stk.get("strategy", "")
            sc = CYAN if "V-Recovery" in strat else AMBER
            ctk.CTkLabel(row, text=strat,
                         font=FONT_TINY,
                         text_color=sc, width=80, anchor="w").pack(
                             side="left", padx=3)

            # Score
            score = stk.get("strategy_score", stk.get("score", 0))
            sc2 = GREEN if score >= 8 else AMBER if score >= 5 else RED
            ctk.CTkLabel(row, text=str(score),
                         font=FONT_TINY_BOLD,
                         text_color=sc2, width=45, anchor="center").pack(
                             side="left", padx=3)

            # Trend (compact: "UP 4d" or "DOWN")
            trend = stk.get("trend", {})
            if isinstance(trend, dict) and trend:
                up = trend.get("is_uptrend", False)
                days = trend.get("days_above_ma20", 0)
                txt = f"{'UP' if up else 'DN'} {days}d"
            else:
                up = False
                txt = "--"
            ctk.CTkLabel(row, text=txt,
                         font=FONT_TINY_BOLD,
                         text_color=GREEN if up else RED,
                         width=80, anchor="w").pack(side="left", padx=3)

            # Sector
            sec = stk.get("sector_check", {})
            if isinstance(sec, dict) and sec:
                chg = sec.get("sector_change", 0)
                sec_txt = f"{sec.get('sector', '')[:10]} {chg:+.1f}%"
                sec_ok = sec.get("allow_entry", False)
            else:
                sec_txt = "--"
                sec_ok = False
            ctk.CTkLabel(row, text=sec_txt,
                         font=FONT_TINY,
                         text_color=GREEN if sec_ok else TEXT_MUTED,
                         width=100, anchor="w").pack(side="left", padx=3)

            # Weekly
            wk = stk.get("weekly_check", {})
            if isinstance(wk, dict) and wk:
                dist = wk.get("distance_pct", 0)
                wk_aligned = wk.get("aligned", False)
                wk_txt = f"{dist:+.1f}%"
            else:
                wk_txt = "--"
                wk_aligned = False
            ctk.CTkLabel(row, text=wk_txt,
                         font=FONT_TINY_BOLD,
                         text_color=GREEN if wk_aligned else TEXT_MUTED,
                         width=65, anchor="w").pack(side="left", padx=3)

            # V-Recovery
            vr = stk.get("v_recovery", {})
            if isinstance(vr, dict) and vr:
                drop = vr.get("drop_percent", 0)
                recv = vr.get("recovery_percent", 0)
                vr_ok = vr.get("is_v_recovery", False)
                vr_txt = f"D:{drop:.1f}% R:{recv:.0f}%"
            else:
                vr_txt = "--"
                vr_ok = False
            ctk.CTkLabel(row, text=vr_txt,
                         font=FONT_TINY,
                         text_color=GREEN if vr_ok else AMBER,
                         width=95, anchor="w").pack(side="left", padx=3)

    def _build_filter_gauges(self, panel, d):
        """Filter pipeline as 3 aviation gauges side by side."""
        funnel = d.get("filter_funnel", {})
        total = d.get("total_scanned", 0)
        f1 = funnel.get("Filter 1 (Price)", 0)
        f2 = funnel.get("Filter 2 (Uptrend)", 0)
        final = d.get("selected_count", 0)

        filters = [
            ("PRICE FILTER", "F&O Rs.100-5K",
             f1, total),
            ("UPTREND FILTER", "EMA21 slope+ > MA20",
             f2, f1 or total),
            ("STRATEGY FILTER", "V-Rec / Mom / PB",
             final, f2 or f1 or total),
        ]

        row = ctk.CTkFrame(panel, fg_color="transparent")
        row.pack(fill="x", padx=4, pady=(4, 2))
        for i in range(len(filters)):
            row.columnconfigure(i, weight=1)

        for col, (name, desc, passed, of_total) in enumerate(filters):
            cell = ctk.CTkFrame(row, fg_color="transparent")
            cell.grid(row=0, column=col, sticky="nsew", padx=4)

            pct = int(passed / of_total * 100) if of_total > 0 else 0
            AviationGauge(
                cell, name, pct, 0, 100, "%",
                zones=[(0, 10, "red"), (10, 30, "amber"), (30, 100, "green")],
                canvas_bg=BG_PANEL, width=130, height=95,
            ).pack(pady=(2, 0))

            # Pass count label
            if of_total > 0:
                clr = GREEN if pct > 10 else AMBER if pct > 3 else RED
                ctk.CTkLabel(cell,
                             text=f"{passed}/{of_total} ({pct}%)",
                             font=FONT_TINY_BOLD,
                             text_color=clr).pack()
            # Description
            ctk.CTkLabel(cell, text=desc,
                         font=FONT_TINY,
                         text_color=TEXT_DIM).pack(pady=(0, 4))

        if not d:
            ctk.CTkLabel(panel, text="Awaiting scan data...",
                         font=FONT_SMALL,
                         text_color=TEXT_DIM).pack(pady=20)


# ==========================================================================
#  PH2 DETAIL — MONITOR CYCLE  (v5.6.2)
# ==========================================================================

class PH2Detail(ctk.CTkFrame):

    def __init__(self, parent, on_back, data_bridge=None):
        super().__init__(parent, fg_color="transparent")
        self._on_back = on_back
        self._data_bridge = data_bridge
        self._data = {}  # empty init — real data arrives via DataBridge
        self._data_fingerprint = ""
        self._build()

        if self._data_bridge:
            self._data_bridge.register_callback(self, self._on_live_data)
            self.after(500, self._try_live)

    @staticmethod
    def _fingerprint(d: dict) -> str:
        """Quick hash of key fields — skip rebuild if unchanged."""
        monitors = tuple(m.get("symbol", "") for m in d.get("active_monitors", []))
        return (f"{d.get('decisions_today')}|{d.get('entries')}|"
                f"{monitors}|{len(d.get('ph3_executions', []))}")

    def _try_live(self):
        if self._data_bridge:
            try:
                ph2 = self._data_bridge.get_ph2_data_v2()
                if ph2:
                    fp = self._fingerprint(ph2)
                    if fp != self._data_fingerprint:
                        self._data = ph2
                        self._data_fingerprint = fp
                        self._refresh_display()
            except Exception:
                pass

    def _on_live_data(self, live):
        try:
            ph2 = self._data_bridge.get_ph2_data_v2()
            if ph2:
                fp = self._fingerprint(ph2)
                if fp != self._data_fingerprint:
                    self._data = ph2
                    self._data_fingerprint = fp
                    self._refresh_display()
        except Exception:
            pass

    def _refresh_display(self):
        for w in self.winfo_children():
            w.destroy()
        self._build()

    # ── PH2 main layout ──────────────────────────────────────────

    def _build(self):
        d = self._data

        _back_button(self, self._on_back).pack(anchor="w", padx=8, pady=(4, 4))
        _title_bar(self, "PH2 . MONITOR CYCLE -- SIGNAL QUALITY").pack(
            fill="x", padx=8, pady=(0, 4))

        content = ctk.CTkFrame(self, fg_color="transparent")
        content.pack(fill="both", expand=True, padx=8, pady=(0, 4))
        content.columnconfigure(0, weight=2)
        content.columnconfigure(1, weight=3)
        content.rowconfigure(0, weight=1)   # top: gauge + monitors
        content.rowconfigure(1, weight=1)   # mid: decisions + ph3
        content.rowconfigure(2, weight=0)   # bot: historical gauges

        # Row 0, Col 0: SIGNAL QUALITY
        self._build_signal_quality(content, d)
        # Row 0, Col 1: ACTIVE MONITORS
        self._build_active_monitors(content, d)
        # Row 1, Col 0: RECENT DECISIONS
        self._build_decisions_table(content, d)
        # Row 1, Col 1: PH3 EXECUTIONS
        self._build_ph3_executions(content, d)
        # Row 2, full width: HISTORICAL PERFORMANCE
        self._build_historical_gauges(content, d)

    # ── PH2 sub-panels ───────────────────────────────────────────

    def _build_signal_quality(self, parent, d):
        """Signal Quality gauge + enriched stat rows."""
        panel = _instrument_panel(parent, "SIGNAL QUALITY")
        panel.grid(row=0, column=0, sticky="nsew", padx=(0, 4), pady=(0, 2))

        total = d.get("decisions_today", 0) or 1
        entries_val = d.get("entries", 0)
        rate = int(entries_val / total * 100) if total > 0 else 0

        gauge_frame = ctk.CTkFrame(panel, fg_color="transparent")
        gauge_frame.pack(pady=(6, 2))
        AviationGauge(
            gauge_frame, "Entry Rate", rate, 0, 100, "%",
            zones=[(0, 20, "red"), (20, 50, "amber"), (50, 100, "green")],
            canvas_bg=BG_PANEL,
        ).pack()

        info = ctk.CTkFrame(panel, fg_color=BG_INPUT, corner_radius=6)
        info.pack(fill="x", padx=10, pady=(2, 4))

        _stat_row(info, "Monitoring", str(d.get("monitoring", 0)))
        _stat_row(info, "Decisions Today", str(d.get("decisions_today", 0)), CYAN)
        _stat_row(info, "Entries", str(entries_val), GREEN)
        _stat_row(info, "Skips", str(d.get("skips", 0)), AMBER)
        _stat_row(info, "Blocks", str(d.get("blocks", 0)), RED)

        # Historical stats
        hist = d.get("historical", {})
        if hist.get("total_trades"):
            ctk.CTkFrame(info, fg_color=BORDER_DIM, height=1).pack(
                fill="x", padx=6, pady=2)
            _stat_row(info, "Total Trades", str(hist.get("total_trades", 0)))
            wr = hist.get("win_rate", 0)
            _stat_row(info, "Win Rate",
                      f"{wr:.0f}%", GREEN if wr >= 50 else RED)
            _stat_row(info, "Avg Duration",
                      f"{hist.get('avg_duration_min', 0):.0f}m", TEXT_LABEL)

        # PH2 status
        if d.get("phase2_started"):
            _stat_row(info, "PH2 Status", "ACTIVE", GREEN)
        elif d.get("monitoring", 0) > 0:
            _stat_row(info, "PH2 Status", "WAITING", AMBER)

    def _build_active_monitors(self, parent, d):
        """Active monitors from ACTIVE.json — compact stock table."""
        panel = _instrument_panel(parent, "ACTIVE MONITORS")
        panel.grid(row=0, column=1, sticky="nsew", padx=(4, 0), pady=(0, 2))

        monitors = d.get("active_monitors", [])
        if not monitors:
            ctk.CTkLabel(panel, text="No monitors active -- awaiting PH1",
                         font=FONT_SMALL,
                         text_color=TEXT_DIM).pack(pady=20)
            return

        # Header
        cols = [("SYMBOL", 85), ("LTP", 60), ("STRATEGY", 80),
                ("SCORE", 45), ("TREND", 70), ("SECTOR", 100), ("STATUS", 80)]
        hdr = ctk.CTkFrame(panel, fg_color=BG_HEADER, corner_radius=0, height=26)
        hdr.pack(fill="x", padx=6, pady=(6, 0))
        hdr.pack_propagate(False)
        for text, w in cols:
            ctk.CTkLabel(hdr, text=text, font=FONT_TINY_BOLD,
                         text_color=TEXT_MUTED, width=w, anchor="w").pack(
                             side="left", padx=3)

        _STATUS_COLORS = {"ENTERED": GREEN, "BLOCKED": RED, "MONITORING": CYAN}

        for stk in monitors:
            row = ctk.CTkFrame(panel, fg_color=BG_INPUT, corner_radius=4, height=30)
            row.pack(fill="x", padx=6, pady=2)
            row.pack_propagate(False)

            ctk.CTkLabel(row, text=stk.get("symbol", ""),
                         font=FONT_TINY_BOLD,
                         text_color=TEXT_PRIMARY, width=85, anchor="w").pack(
                             side="left", padx=3)

            ltp = stk.get("ltp", 0)
            ctk.CTkLabel(row, text=f"{ltp:.1f}",
                         font=FONT_TINY,
                         text_color=TEXT_LABEL, width=60, anchor="w").pack(
                             side="left", padx=3)

            strat = stk.get("strategy", "")
            sc = CYAN if "V-Recovery" in strat else AMBER
            ctk.CTkLabel(row, text=strat,
                         font=FONT_TINY,
                         text_color=sc, width=80, anchor="w").pack(
                             side="left", padx=3)

            score = stk.get("strategy_score", 0)
            sc2 = GREEN if score >= 8 else AMBER if score >= 5 else RED
            ctk.CTkLabel(row, text=str(score),
                         font=FONT_TINY_BOLD,
                         text_color=sc2, width=45, anchor="center").pack(
                             side="left", padx=3)

            trend = stk.get("trend", {})
            if isinstance(trend, dict) and trend:
                up = trend.get("is_uptrend", False)
                days = trend.get("days_above_ma20", 0)
                txt = f"{'UP' if up else 'DN'} {days}d"
            else:
                up, txt = False, "--"
            ctk.CTkLabel(row, text=txt,
                         font=FONT_TINY_BOLD,
                         text_color=GREEN if up else RED,
                         width=70, anchor="w").pack(side="left", padx=3)

            sec = stk.get("sector_check", {})
            if isinstance(sec, dict) and sec:
                chg = sec.get("sector_change", 0)
                sec_txt = f"{sec.get('sector', '')[:10]} {chg:+.1f}%"
                sec_ok = sec.get("allow_entry", False)
            else:
                sec_txt, sec_ok = "--", False
            ctk.CTkLabel(row, text=sec_txt,
                         font=FONT_TINY,
                         text_color=GREEN if sec_ok else TEXT_MUTED,
                         width=100, anchor="w").pack(side="left", padx=3)

            status = stk.get("status", "MONITORING")
            ctk.CTkLabel(row, text=status,
                         font=FONT_TINY_BOLD,
                         text_color=_STATUS_COLORS.get(status, TEXT_MUTED),
                         width=80, anchor="w").pack(side="left", padx=3)

    def _build_decisions_table(self, parent, d):
        """Recent Decisions table with reason column."""
        panel = _instrument_panel(parent, "RECENT DECISIONS")
        panel.grid(row=1, column=0, sticky="nsew", padx=(0, 4), pady=(2, 2))

        cols = [("TIME", 50), ("SYMBOL", 85), ("DECISION", 65),
                ("REASON", 100), ("CONF", 45)]
        hdr = ctk.CTkFrame(panel, fg_color=BG_HEADER, corner_radius=0, height=26)
        hdr.pack(fill="x", padx=6, pady=(6, 0))
        hdr.pack_propagate(False)
        for text, w in cols:
            ctk.CTkLabel(hdr, text=text, font=FONT_TINY_BOLD,
                         text_color=TEXT_MUTED, width=w, anchor="w").pack(
                             side="left", padx=3)

        _DEC_COLORS = {"ENTER": GREEN, "BUY": GREEN, "EXIT": AMBER,
                       "SKIP": AMBER, "BLOCKED": RED, "BLOCK": RED}

        for dec in d.get("recent", []):
            row = ctk.CTkFrame(panel, fg_color="transparent", height=26)
            row.pack(fill="x", padx=6, pady=1)
            row.pack_propagate(False)

            ctk.CTkLabel(row, text=dec.get("time", ""),
                         font=FONT_TINY,
                         text_color=TEXT_DIM, width=50, anchor="w").pack(
                             side="left", padx=3)
            ctk.CTkLabel(row, text=dec.get("symbol", ""),
                         font=FONT_TINY_BOLD,
                         text_color=TEXT_PRIMARY, width=85, anchor="w").pack(
                             side="left", padx=3)

            dec_text = dec.get("decision", "SKIP")
            dec_color = _DEC_COLORS.get(dec_text, TEXT_MUTED)
            ctk.CTkLabel(row, text=dec_text,
                         font=FONT_TINY_BOLD,
                         text_color=dec_color, width=65, anchor="w").pack(
                             side="left", padx=3)

            reason = dec.get("reason", "")
            ctk.CTkLabel(row, text=reason[:18] if reason else "",
                         font=FONT_TINY,
                         text_color=TEXT_DIM, width=100, anchor="w").pack(
                             side="left", padx=3)

            conf = dec.get("confidence", 0)
            conf_color = GREEN if conf >= 70 else AMBER if conf >= 50 else TEXT_DIM
            ctk.CTkLabel(row, text=f"{conf:.0f}",
                         font=FONT_TINY_BOLD,
                         text_color=conf_color, width=45, anchor="w").pack(
                             side="left", padx=3)

        if not d.get("recent"):
            ctk.CTkLabel(panel, text="No decisions yet today",
                         font=FONT_SMALL,
                         text_color=TEXT_DIM).pack(pady=20)

    def _build_ph3_executions(self, parent, d):
        """Stocks pushed to PH3 — orders and completed trades."""
        panel = _instrument_panel(parent, "PH3 EXECUTIONS")
        panel.grid(row=1, column=1, sticky="nsew", padx=(4, 0), pady=(2, 2))

        execs = d.get("ph3_executions", [])
        if not execs:
            ctk.CTkLabel(panel, text="No PH3 executions yet",
                         font=FONT_SMALL,
                         text_color=TEXT_DIM).pack(pady=20)
            return

        cols = [("DATE", 70), ("SYMBOL", 85), ("ENTRY", 60), ("EXIT", 60),
                ("P&L%", 55), ("W/L", 30), ("REASON", 70)]
        hdr = ctk.CTkFrame(panel, fg_color=BG_HEADER, corner_radius=0, height=26)
        hdr.pack(fill="x", padx=6, pady=(6, 0))
        hdr.pack_propagate(False)
        for text, w in cols:
            ctk.CTkLabel(hdr, text=text, font=FONT_TINY_BOLD,
                         text_color=TEXT_MUTED, width=w, anchor="w").pack(
                             side="left", padx=2)

        for ex in execs:
            row = ctk.CTkFrame(panel, fg_color="transparent", height=26)
            row.pack(fill="x", padx=6, pady=1)
            row.pack_propagate(False)

            # Date (compact: MM-DD)
            dt = ex.get("date", "")
            short_dt = dt[5:] if len(dt) >= 10 else dt
            ctk.CTkLabel(row, text=short_dt,
                         font=FONT_TINY,
                         text_color=TEXT_DIM, width=70, anchor="w").pack(
                             side="left", padx=2)

            ctk.CTkLabel(row, text=ex.get("symbol", ""),
                         font=FONT_TINY_BOLD,
                         text_color=TEXT_PRIMARY, width=85, anchor="w").pack(
                             side="left", padx=2)

            ep = ex.get("entry_price", 0)
            ctk.CTkLabel(row, text=f"{ep:.0f}" if ep else "--",
                         font=FONT_TINY,
                         text_color=TEXT_LABEL, width=60, anchor="w").pack(
                             side="left", padx=2)

            xp = ex.get("exit_price", 0)
            ctk.CTkLabel(row, text=f"{xp:.0f}" if xp else "--",
                         font=FONT_TINY,
                         text_color=TEXT_LABEL, width=60, anchor="w").pack(
                             side="left", padx=2)

            pnl = ex.get("pnl_pct", 0)
            pnl_c = GREEN if pnl > 0 else RED if pnl < 0 else TEXT_DIM
            ctk.CTkLabel(row, text=f"{pnl:+.1f}%" if pnl else "--",
                         font=FONT_TINY_BOLD,
                         text_color=pnl_c, width=55, anchor="w").pack(
                             side="left", padx=2)

            win = ex.get("win")
            if win is True:
                wl_txt, wl_c = "W", GREEN
            elif win is False:
                wl_txt, wl_c = "L", RED
            else:
                wl_txt, wl_c = "-", TEXT_DIM
            ctk.CTkLabel(row, text=wl_txt,
                         font=FONT_TINY_BOLD,
                         text_color=wl_c, width=30, anchor="center").pack(
                             side="left", padx=2)

            reason = ex.get("exit_reason", "")
            ctk.CTkLabel(row, text=reason[:12] if reason else "",
                         font=FONT_TINY,
                         text_color=TEXT_DIM, width=70, anchor="w").pack(
                             side="left", padx=2)

    def _build_historical_gauges(self, parent, d):
        """3 historical performance gauges — full width bottom row."""
        panel = _instrument_panel(parent, "HISTORICAL PERFORMANCE")
        panel.grid(row=2, column=0, columnspan=2, sticky="nsew", pady=(2, 0))

        hist = d.get("historical", {})
        total_t = hist.get("total_trades", 0) or 1
        wins = hist.get("wins", 0)
        wr = hist.get("win_rate", 0)
        avg_pnl = hist.get("avg_pnl_pct", 0)
        dec_acc = hist.get("decision_accuracy", 0)

        # Map avg P&L to 0-100 gauge (range: -5% to +5% → 0 to 100)
        pnl_gauge = max(0, min(100, int((avg_pnl + 5) / 10 * 100)))

        gauges = [
            ("WIN RATE", f"{wins}/{total_t} ({wr:.0f}%)",
             f"All-time: {total_t} trades",
             int(wr),
             [(0, 30, "red"), (30, 50, "amber"), (50, 100, "green")]),
            ("AVG P&L", f"{avg_pnl:+.2f}%",
             "Per-trade average",
             pnl_gauge,
             [(0, 40, "red"), (40, 55, "amber"), (55, 100, "green")]),
            ("DECISION ACC", f"{dec_acc:.0f}%",
             f"{wins} wins / {hist.get('total_entry_decisions', 0)} entries",
             int(dec_acc),
             [(0, 30, "red"), (30, 60, "amber"), (60, 100, "green")]),
        ]

        row = ctk.CTkFrame(panel, fg_color="transparent")
        row.pack(fill="x", padx=4, pady=(4, 2))
        for i in range(len(gauges)):
            row.columnconfigure(i, weight=1)

        for col, (name, val_txt, desc, pct, zones) in enumerate(gauges):
            cell = ctk.CTkFrame(row, fg_color="transparent")
            cell.grid(row=0, column=col, sticky="nsew", padx=4)

            AviationGauge(
                cell, name, pct, 0, 100, "%",
                zones=zones, canvas_bg=BG_PANEL,
                width=130, height=95,
            ).pack(pady=(2, 0))

            clr = GREEN if pct >= 50 else AMBER if pct >= 30 else RED
            ctk.CTkLabel(cell, text=val_txt,
                         font=FONT_TINY_BOLD,
                         text_color=clr).pack()
            ctk.CTkLabel(cell, text=desc,
                         font=FONT_TINY,
                         text_color=TEXT_DIM).pack(pady=(0, 4))

        if not hist.get("total_trades"):
            ctk.CTkLabel(panel, text="No trade history yet",
                         font=FONT_TINY,
                         text_color=TEXT_DIM).pack(pady=6)


# ==========================================================================
#  PH3 DETAIL — ORDER EXECUTION  (v5.6.2)
# ==========================================================================

class PH3Detail(ctk.CTkFrame):

    def __init__(self, parent, on_back, data_bridge=None):
        super().__init__(parent, fg_color="transparent")
        self._on_back = on_back
        self._data_bridge = data_bridge
        self._data = {}
        self._build()

        if self._data_bridge:
            self._data_bridge.register_callback(self, self._on_live_data)
            self.after(500, self._try_live)

    def _try_live(self):
        if self._data_bridge:
            live = self._data_bridge.get_latest()
            if live and live.db_available:
                self._on_live_data(live)

    def _on_live_data(self, live):
        if not live or not live.db_available:
            return
        try:
            ph3 = self._data_bridge.get_ph3_data()
            if ph3:
                self._data = ph3
                self._refresh_display()
        except Exception:
            pass

    def _refresh_display(self):
        for w in self.winfo_children():
            w.destroy()
        self._build()

    def _build(self):
        d = self._data

        _back_button(self, self._on_back).pack(anchor="w", padx=8, pady=(4, 4))
        _title_bar(self, "PH3 . ORDER EXECUTION -- FLIGHT DECK").pack(
            fill="x", padx=8, pady=(0, 4))

        content = ctk.CTkFrame(self, fg_color="transparent")
        content.pack(fill="both", expand=True, padx=8, pady=(0, 4))
        content.columnconfigure(0, weight=2)
        content.columnconfigure(1, weight=3)
        content.rowconfigure(0, weight=1)

        # -- Left: EXECUTION STATUS --
        left = _instrument_panel(content, "EXECUTION STATUS")
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 4))

        active = d.get("active_positions", 0)
        max_pos = d.get("max_positions", 3) or 3
        slot_pct = int(active / max_pos * 100)

        gauge_frame = ctk.CTkFrame(left, fg_color="transparent")
        gauge_frame.pack(pady=(8, 4))
        AviationGauge(
            gauge_frame, "Slot Usage", slot_pct, 0, 100, "%",
            zones=[(0, 33, "green"), (33, 66, "amber"), (66, 100, "red")],
            canvas_bg=BG_PANEL,
        ).pack()

        info = ctk.CTkFrame(left, fg_color=BG_INPUT, corner_radius=6)
        info.pack(fill="x", padx=10, pady=(4, 8))

        _stat_row(info, "Active Positions", f"{active} / {max_pos}",
                  GREEN if active < max_pos else RED)
        _stat_row(info, "Trades Today", str(d.get("trades_today", 0)), CYAN)

        wr = d.get("win_rate", 0)
        wr_color = GREEN if wr >= 50 else AMBER if wr >= 30 else RED
        _stat_row(info, "Win Rate", f"{wr:.0f}%", wr_color)

        pnl = d.get("total_pnl", 0)
        pnl_color = GREEN if pnl > 0 else RED if pnl < 0 else TEXT_LABEL
        pnl_text = f"Rs.{pnl:+,.0f}" if pnl != 0 else "Rs.0"
        _stat_row(info, "Total P&L", pnl_text, pnl_color)

        # -- Right: POSITIONS + TRADES --
        right = ctk.CTkFrame(content, fg_color="transparent")
        right.grid(row=0, column=1, sticky="nsew", padx=(4, 0))
        right.rowconfigure(0, weight=1)
        right.rowconfigure(1, weight=1)
        right.columnconfigure(0, weight=1)

        # ---- Active Positions sub-panel ----
        pos_panel = _instrument_panel(right, "ACTIVE POSITIONS")
        pos_panel.grid(row=0, column=0, sticky="nsew", pady=(0, 2))

        pos_hdr = ctk.CTkFrame(pos_panel, fg_color=BG_HEADER, corner_radius=0, height=28)
        pos_hdr.pack(fill="x", padx=8, pady=(6, 0))
        pos_hdr.pack_propagate(False)
        for text, w in [("SYMBOL", 100), ("DIR", 50), ("ENTRY", 80), ("CURRENT", 80), ("P&L", 70), ("STATUS", 80)]:
            ctk.CTkLabel(pos_hdr, text=text, font=FONT_TINY_BOLD,
                         text_color=TEXT_MUTED, width=w, anchor="w").pack(side="left", padx=4)

        for pos in d.get("positions", []):
            row = ctk.CTkFrame(pos_panel, fg_color="transparent", height=28)
            row.pack(fill="x", padx=8, pady=1)
            row.pack_propagate(False)

            ctk.CTkLabel(row, text=pos.get("symbol", ""),
                         font=FONT_BODY_BOLD,
                         text_color=TEXT_PRIMARY, width=100, anchor="w").pack(side="left", padx=4)
            ctk.CTkLabel(row, text=pos.get("direction", ""),
                         font=FONT_SMALL,
                         text_color=TEXT_LABEL, width=50, anchor="w").pack(side="left", padx=4)
            ctk.CTkLabel(row, text=f"{pos.get('entry', 0):.0f}",
                         font=FONT_SMALL,
                         text_color=TEXT_LABEL, width=80, anchor="w").pack(side="left", padx=4)
            ctk.CTkLabel(row, text=f"{pos.get('current', 0):.0f}",
                         font=FONT_SMALL,
                         text_color=TEXT_LABEL, width=80, anchor="w").pack(side="left", padx=4)

            pnl_str = pos.get("pnl", "0%")
            pc = GREEN if pnl_str.startswith("+") else RED if pnl_str.startswith("-") else TEXT_LABEL
            ctk.CTkLabel(row, text=pnl_str,
                         font=FONT_BODY_BOLD,
                         text_color=pc, width=70, anchor="w").pack(side="left", padx=4)
            ctk.CTkLabel(row, text=pos.get("status", ""),
                         font=FONT_TINY,
                         text_color=CYAN, width=80, anchor="w").pack(side="left", padx=4)

        if not d.get("positions"):
            ctk.CTkLabel(pos_panel, text="No active positions",
                         font=FONT_SMALL, text_color=TEXT_DIM).pack(pady=12)

        # ---- Today's Trades sub-panel ----
        trade_panel = _instrument_panel(right, "TODAY'S TRADES")
        trade_panel.grid(row=1, column=0, sticky="nsew", pady=(2, 0))

        trade_hdr = ctk.CTkFrame(trade_panel, fg_color=BG_HEADER, corner_radius=0, height=28)
        trade_hdr.pack(fill="x", padx=8, pady=(6, 0))
        trade_hdr.pack_propagate(False)
        for text, w in [("SYMBOL", 100), ("DIR", 50), ("ENTRY", 80), ("EXIT", 80), ("P&L", 70), ("REASON", 80)]:
            ctk.CTkLabel(trade_hdr, text=text, font=FONT_TINY_BOLD,
                         text_color=TEXT_MUTED, width=w, anchor="w").pack(side="left", padx=4)

        for trade in d.get("trades", []):
            row = ctk.CTkFrame(trade_panel, fg_color="transparent", height=28)
            row.pack(fill="x", padx=8, pady=1)
            row.pack_propagate(False)

            ctk.CTkLabel(row, text=trade.get("symbol", ""),
                         font=FONT_BODY_BOLD,
                         text_color=TEXT_PRIMARY, width=100, anchor="w").pack(side="left", padx=4)
            ctk.CTkLabel(row, text=trade.get("direction", ""),
                         font=FONT_SMALL,
                         text_color=TEXT_LABEL, width=50, anchor="w").pack(side="left", padx=4)
            ctk.CTkLabel(row, text=f"{trade.get('entry', 0):.0f}",
                         font=FONT_SMALL,
                         text_color=TEXT_LABEL, width=80, anchor="w").pack(side="left", padx=4)
            ctk.CTkLabel(row, text=f"{trade.get('exit', 0):.0f}",
                         font=FONT_SMALL,
                         text_color=TEXT_LABEL, width=80, anchor="w").pack(side="left", padx=4)

            pnl_str = trade.get("pnl", "0%")
            pc = GREEN if pnl_str.startswith("+") else RED if pnl_str.startswith("-") else TEXT_LABEL
            ctk.CTkLabel(row, text=pnl_str,
                         font=FONT_BODY_BOLD,
                         text_color=pc, width=70, anchor="w").pack(side="left", padx=4)
            ctk.CTkLabel(row, text=trade.get("reason", ""),
                         font=FONT_TINY,
                         text_color=AMBER, width=80, anchor="w").pack(side="left", padx=4)

        if not d.get("trades"):
            ctk.CTkLabel(trade_panel, text="No trades yet today",
                         font=FONT_SMALL, text_color=TEXT_DIM).pack(pady=12)


# ==========================================================================
#  FACTORY FUNCTION
# ==========================================================================

def create_phase_detail(phase_id, parent, on_back, data_bridge=None):
    """Create and return a phase detail view by ID."""
    views = {
        "ph1":  PH1Detail,
        "ph2":  PH2Detail,
        "ph3":  PH3Detail,
        "ph5":  PH5Detail,
        "ph5a": PH5ADetail,
        "ph4":  PH4Detail,
        "ph6":  PH6Detail,
        "ph7":  PH7Detail,
        "ph8":  PH8Detail,
    }
    cls = views.get(phase_id)
    if cls:
        # All detail views now accept data_bridge
        return cls(parent, on_back, data_bridge=data_bridge)
    return None
