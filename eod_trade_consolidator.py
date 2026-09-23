"""
EOD_TRADE_CONSOLIDATOR.PY
=========================
Run this once after market close (or schedule it at 16:30 IST) to consolidate
all paper trade data into Paper_Trade_Log.xlsx.

DATA SOURCES (in priority order):
  1. data/blackbox/blackbox_YYYY-MM-DD.json   ← primary: has entry+exit+P&L for all phases
  2. data/ph5_paper_trades.json               ← PH5 entries without exits (OPEN positions)
  3. data/ph8_paper_signals.json              ← PH8 weekly signals
  4. data/mcx/paper_trades.csv                ← MCX commodity paper trades

HOW TO RUN:
  python eod_trade_consolidator.py              # consolidates ALL dates
  python eod_trade_consolidator.py --today      # only today's data
  python eod_trade_consolidator.py --date 2026-05-01   # specific date

SCHEDULE (Windows Task Scheduler):
  Trigger : Daily, 16:30 IST (Mon–Fri)
  Action  : python "C:\\...\\Algo_Beta\\eod_trade_consolidator.py" --today

Author : Dheebanraj + Claude
Version: 1.0.0  |  Paper mode start: 2026-04-20
"""

import os
import sys
import json
import csv
import glob
import argparse
import logging
from datetime import datetime, date, timedelta
from collections import defaultdict
from typing import List, Dict, Optional

# ── Setup ──────────────────────────────────────────────────────────────────
BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
DATA_DIR   = os.path.join(BASE_DIR, "data")
XLSX_OUT   = os.path.join(DATA_DIR, "Paper_Trade_Log.xlsx")
LOG_FILE   = os.path.join(BASE_DIR, "logs", "eod_consolidator.log")

os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(sys.stdout),
    ]
)
log = logging.getLogger("EOD")

# Phase label normaliser (maps source strings → clean phase names)
SOURCE_TO_PHASE = {
    "PHASE5_GAP":             "PH5",
    "PHASE5A_PVAT":           "PH5A",
    "PHASE4_MANUAL_POSITIONS":"PH4",
    "PHASE3":                 "PH3",
    "PHASE3_CASH":            "PH3",
    "PHASE8":                 "PH8",
    "PH8":                    "PH8",
    "MCX":                    "MCX",
}

PAPER_MODE_START = date(2026, 4, 20)   # Only include trades from this date onwards


# ════════════════════════════════════════════════════════════════════════════
# 1. DATA READERS — each returns a list of normalised trade dicts
# ════════════════════════════════════════════════════════════════════════════

def read_blackbox_files(filter_date: Optional[date] = None) -> List[Dict]:
    """
    Read all blackbox_YYYY-MM-DD.json files.
    Each file's phase3_trades[] array contains EXIT records with full P&L.
    These are the most reliable records — entry_price + exit_price + pnl all present.
    """
    trades = []
    pattern = os.path.join(DATA_DIR, "blackbox", "blackbox_*.json")
    files   = sorted(glob.glob(pattern))

    for fpath in files:
        fname     = os.path.basename(fpath)
        file_date_str = fname.replace("blackbox_", "").replace(".json", "")
        try:
            file_date = date.fromisoformat(file_date_str)
        except ValueError:
            continue

        # Filter: skip dates before paper mode start
        if file_date < PAPER_MODE_START:
            continue
        if filter_date and file_date != filter_date:
            continue

        try:
            with open(fpath, "r", encoding="utf-8") as f:
                bb = json.load(f)
        except Exception as e:
            log.warning(f"  Could not read {fname}: {e}")
            continue

        for t in bb.get("phase3_trades", []):
            if t.get("action") != "EXIT":
                continue   # blackbox only logs exits; skip entries to avoid duplicates

            details = t.get("details", {})
            ts      = t.get("timestamp", "")
            source  = details.get("source", "UNKNOWN")
            phase   = SOURCE_TO_PHASE.get(source, source)

            entry_price = details.get("entry_price", 0) or 0
            exit_price  = details.get("exit_price", 0)  or 0
            quantity    = details.get("quantity", 0)     or 0
            pnl         = details.get("pnl", None)
            reason      = details.get("reason", "")

            # Derive P&L if not stored (should always be present in blackbox)
            if pnl is None and entry_price > 0 and exit_price > 0 and quantity > 0:
                pnl = (exit_price - entry_price) * quantity

            pnl_pct = 0.0
            if entry_price > 0 and quantity > 0:
                cost    = entry_price * quantity
                pnl_pct = round((pnl / cost) * 100, 4) if pnl is not None else 0.0

            try:
                dt_obj     = datetime.fromisoformat(ts)
                trade_date = dt_obj.strftime("%Y-%m-%d")
                exit_time  = dt_obj.strftime("%H:%M:%S")
            except Exception:
                trade_date = file_date_str
                exit_time  = ""

            # Unique ID to prevent duplicates across re-runs
            trade_id = f"{phase}-{t.get('symbol','?')}-{trade_date}-BB-{abs(hash(ts)) % 10000:04d}"

            trades.append({
                "trade_id":    trade_id,
                "date":        trade_date,
                "entry_time":  "",           # blackbox doesn't store entry time separately
                "exit_time":   exit_time,
                "phase":       phase,
                "symbol":      t.get("symbol", ""),
                "direction":   "BUY",        # gap strategy is always BUY (short not yet in system)
                "entry_price": round(float(entry_price), 2),
                "exit_price":  round(float(exit_price), 2),
                "stop_loss":   0,
                "target":      0,
                "quantity":    int(quantity),
                "pnl_rs":      round(float(pnl), 2) if pnl is not None else "",
                "pnl_pct":     pnl_pct,
                "exit_reason": reason,
                "status":      _pnl_to_status(pnl),
                "strategy":    source,
                "score":       0,
                "regime":      "",
                "notes":       f"Source: blackbox {file_date_str}",
            })

    log.info(f"  Blackbox  → {len(trades)} exit records")
    return trades


def read_ph5_paper_trades() -> List[Dict]:
    """
    Read ph5_paper_trades.json — PH5 paper ENTRY records.
    These are entries where we may not have a recorded exit yet (OPEN positions).
    Only include date >= paper mode start.
    """
    fpath = os.path.join(DATA_DIR, "ph5_paper_trades.json")
    if not os.path.exists(fpath):
        return []

    try:
        with open(fpath, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except Exception as e:
        log.warning(f"  ph5_paper_trades.json read error: {e}")
        return []

    trades = []
    for t in raw:
        ts = t.get("timestamp", "")
        try:
            dt_obj     = datetime.fromisoformat(ts)
            trade_date = dt_obj.strftime("%Y-%m-%d")
            entry_time = dt_obj.strftime("%H:%M:%S")
            if date.fromisoformat(trade_date) < PAPER_MODE_START:
                continue
        except Exception:
            trade_date = ""
            entry_time = ""

        direction = t.get("transaction_type", "BUY").upper()
        trade_id  = f"PH5-{t.get('symbol','?')}-{trade_date}-{t.get('order_id','')[-6:]}"

        trades.append({
            "trade_id":    trade_id,
            "date":        trade_date,
            "entry_time":  entry_time,
            "exit_time":   "",
            "phase":       "PH5",
            "symbol":      t.get("symbol", ""),
            "direction":   direction,
            "entry_price": round(float(t.get("sim_price", 0) or 0), 2),
            "exit_price":  "",
            "stop_loss":   0,
            "target":      0,
            "quantity":    int(t.get("quantity", 0) or 0),
            "pnl_rs":      "",
            "pnl_pct":     "",
            "exit_reason": "",
            "status":      "OPEN",
            "strategy":    "Gap Strategy (PH5 Paper)",
            "score":       0,
            "regime":      "",
            "notes":       f"Paper entry | order: {t.get('order_id','')}",
        })

    log.info(f"  PH5 paper → {len(trades)} entry records")
    return trades


def read_ph8_paper_signals() -> List[Dict]:
    """
    Read ph8_paper_signals.json — PH8 weekly momentum signals.
    Note: entry_price/stop/target are currently all 0 in the actual files.
    Logged as SIGNAL (advisory) rows.
    """
    fpath = os.path.join(DATA_DIR, "ph8_paper_signals.json")
    if not os.path.exists(fpath):
        return []

    try:
        with open(fpath, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except Exception as e:
        log.warning(f"  ph8_paper_signals.json read error: {e}")
        return []

    trades = []
    for t in raw:
        ts = t.get("timestamp", "")
        try:
            dt_obj     = datetime.fromisoformat(ts)
            trade_date = dt_obj.strftime("%Y-%m-%d")
            entry_time = dt_obj.strftime("%H:%M:%S")
            if date.fromisoformat(trade_date) < PAPER_MODE_START:
                continue
        except Exception:
            trade_date = ""
            entry_time = ""

        trade_id = f"PH8-{t.get('symbol','?')}-{trade_date}-{abs(hash(ts)) % 9999:04d}"

        trades.append({
            "trade_id":    trade_id,
            "date":        trade_date,
            "entry_time":  entry_time,
            "exit_time":   "",
            "phase":       "PH8",
            "symbol":      t.get("symbol", ""),
            "direction":   t.get("direction", "BUY").upper(),
            "entry_price": round(float(t.get("entry_price", 0) or 0), 2),
            "exit_price":  "",
            "stop_loss":   round(float(t.get("stop_loss", 0) or 0), 2),
            "target":      round(float(t.get("target", 0) or 0), 2),
            "quantity":    0,
            "pnl_rs":      "",
            "pnl_pct":     "",
            "exit_reason": "",
            "status":      "SIGNAL",
            "strategy":    "Weekly Momentum (PH8)",
            "score":       t.get("score", 0),
            "regime":      "",
            "notes":       "PH8 signal — exit tracked manually",
        })

    log.info(f"  PH8 paper → {len(trades)} signal records")
    return trades


def read_mcx_paper_trades() -> List[Dict]:
    """
    Read data/mcx/paper_trades.csv — MCX commodity paper trades.
    CSV columns: date,id,symbol,strategy,direction,entry_price,exit_price,
                 stop_loss,target,entry_time,exit_time,exit_reason,pnl,
                 hold_duration_min,confidence,reason
    """
    fpath = os.path.join(DATA_DIR, "mcx", "paper_trades.csv")
    if not os.path.exists(fpath):
        return []

    trades = []
    try:
        with open(fpath, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                trade_date = row.get("date", "")
                try:
                    if date.fromisoformat(trade_date) < PAPER_MODE_START:
                        continue
                except Exception:
                    pass

                pnl = _safe_float(row.get("pnl"))
                entry_p = _safe_float(row.get("entry_price"))
                exit_p  = _safe_float(row.get("exit_price"))
                qty     = _safe_int(row.get("quantity", 1))

                pnl_pct = 0.0
                if pnl is not None and entry_p > 0 and qty > 0:
                    pnl_pct = round((pnl / (entry_p * qty)) * 100, 4)

                trade_id = f"MCX-{row.get('symbol','?')}-{trade_date}-{row.get('id','')[-6:]}"

                trades.append({
                    "trade_id":    trade_id,
                    "date":        trade_date,
                    "entry_time":  row.get("entry_time", ""),
                    "exit_time":   row.get("exit_time", ""),
                    "phase":       "MCX",
                    "symbol":      row.get("symbol", ""),
                    "direction":   row.get("direction", "BUY").upper(),
                    "entry_price": round(entry_p, 2),
                    "exit_price":  round(exit_p, 2) if exit_p else "",
                    "stop_loss":   _safe_float(row.get("stop_loss")) or 0,
                    "target":      _safe_float(row.get("target")) or 0,
                    "quantity":    qty,
                    "pnl_rs":      round(pnl, 2) if pnl is not None else "",
                    "pnl_pct":     pnl_pct,
                    "exit_reason": row.get("exit_reason", row.get("reason", "")),
                    "status":      _pnl_to_status(pnl),
                    "strategy":    row.get("strategy", "MCX Paper"),
                    "score":       _safe_float(row.get("confidence")) or 0,
                    "regime":      "",
                    "notes":       f"Hold: {row.get('hold_duration_min','')} min",
                })
    except Exception as e:
        log.warning(f"  MCX CSV read error: {e}")

    log.info(f"  MCX paper → {len(trades)} records")
    return trades


# ════════════════════════════════════════════════════════════════════════════
# 2. DEDUPLICATION — blackbox EXIT records supersede ph5 ENTRY records
# ════════════════════════════════════════════════════════════════════════════

def deduplicate(all_trades: List[Dict]) -> List[Dict]:
    """
    If blackbox already has an EXIT record for (date, symbol, phase),
    remove the raw PH5/PH5A OPEN entry record to avoid double-counting.
    The blackbox EXIT record contains both entry + exit info, so it's complete.
    """
    # Build a set of (date, symbol, phase) tuples that are closed in blackbox
    closed = set()
    for t in all_trades:
        if t["status"] not in ("OPEN", "SIGNAL") and t.get("exit_price", "") != "":
            closed.add((t["date"], t["symbol"], t["phase"]))

    # Keep OPEN/SIGNAL records only if they're NOT already closed in blackbox
    result = []
    seen_ids = set()
    for t in all_trades:
        tid = t["trade_id"]
        if tid in seen_ids:
            continue
        seen_ids.add(tid)

        if t["status"] == "OPEN":
            key = (t["date"], t["symbol"], t["phase"])
            if key in closed:
                log.debug(f"  Dedup: dropping OPEN {key} — covered by blackbox EXIT")
                continue

        result.append(t)

    log.info(f"  After dedup: {len(result)} unique records")
    return result


# ════════════════════════════════════════════════════════════════════════════
# 3. EXCEL WRITER
# ════════════════════════════════════════════════════════════════════════════

def write_excel(trades: List[Dict]) -> str:
    try:
        import openpyxl
        from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
        from openpyxl.utils import get_column_letter
    except ImportError:
        log.error("openpyxl not installed. Run: pip install openpyxl")
        sys.exit(1)

    wb = openpyxl.Workbook()

    _write_trade_log(wb, trades)
    _write_daily_summary(wb, trades)
    _write_phase_performance(wb, trades)
    _write_month_overview(wb, trades)
    _write_how_to_use(wb)

    os.makedirs(os.path.dirname(XLSX_OUT), exist_ok=True)
    wb.save(XLSX_OUT)
    log.info(f"  Saved → {XLSX_OUT}")
    return XLSX_OUT


def _style_header(cell, bg="1F4E79"):
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    thin = Side(style="thin", color="BFBFBF")
    cell.font      = Font(name="Arial", bold=True, color="FFFFFF", size=10)
    cell.fill      = PatternFill("solid", start_color=bg)
    cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    cell.border    = Border(left=thin, right=thin, top=thin, bottom=thin)


def _thin_border():
    from openpyxl.styles import Border, Side
    thin = Side(style="thin", color="BFBFBF")
    return Border(left=thin, right=thin, top=thin, bottom=thin)


def _write_trade_log(wb, trades: List[Dict]):
    from openpyxl.styles import Font, PatternFill, Alignment
    from openpyxl.utils import get_column_letter

    ws = wb.active
    ws.title = "Trade Log"

    HEADERS = [
        "Trade ID", "Date", "Entry Time", "Exit Time",
        "Phase", "Symbol", "Direction",
        "Entry ₹", "Exit ₹", "Stop Loss ₹", "Target ₹", "Qty",
        "P&L (₹)", "P&L (%)", "Strategy", "Exit Reason", "Status", "Notes"
    ]
    COL_KEYS = [
        "trade_id", "date", "entry_time", "exit_time",
        "phase", "symbol", "direction",
        "entry_price", "exit_price", "stop_loss", "target", "quantity",
        "pnl_rs", "pnl_pct", "strategy", "exit_reason", "status", "notes"
    ]

    for ci, h in enumerate(HEADERS, 1):
        _style_header(ws.cell(row=1, column=ci, value=h))
    ws.row_dimensions[1].height = 30

    STATUS_FILL = {
        "WIN":      PatternFill("solid", start_color="E2EFDA"),
        "LOSS":     PatternFill("solid", start_color="FCE4D6"),
        "OPEN":     PatternFill("solid", start_color="FFF2CC"),
        "SIGNAL":   PatternFill("solid", start_color="EBF3FB"),
        "BREAKEVEN":PatternFill("solid", start_color="F2F2F2"),
    }
    BASE = Font(name="Arial", size=9)
    border = _thin_border()

    sorted_trades = sorted(trades, key=lambda t: (t.get("date",""), t.get("exit_time",""), t.get("entry_time","")))

    for ri, trade in enumerate(sorted_trades, 2):
        status   = trade.get("status", "OPEN")
        row_fill = STATUS_FILL.get(status, None)

        for ci, key in enumerate(COL_KEYS, 1):
            val  = trade.get(key, "")
            cell = ws.cell(row=ri, column=ci, value=val)
            cell.font      = BASE
            cell.border    = border
            cell.alignment = Alignment(vertical="center")
            if row_fill:
                cell.fill = row_fill

            # Formatting
            if key == "pnl_rs" and isinstance(val, (int, float)):
                cell.number_format = '#,##0.00;[Red](#,##0.00)'
                cell.font = Font(name="Arial", size=9, bold=True,
                                 color="375623" if val >= 0 else "9C0006")
            elif key == "pnl_pct" and isinstance(val, (int, float)):
                cell.number_format = '0.00"%"'
            elif key in ("entry_price", "exit_price", "stop_loss", "target"):
                if isinstance(val, (int, float)) and val > 0:
                    cell.number_format = '#,##0.00'
            elif key == "direction":
                cell.font = Font(name="Arial", size=9, bold=True,
                                 color="375623" if str(val)=="BUY" else "9C0006")
            elif key == "status":
                status_colors = {"WIN":"375623","LOSS":"9C0006","OPEN":"7F6000","SIGNAL":"2E75B6"}
                cell.font = Font(name="Arial", size=9, bold=True,
                                 color=status_colors.get(status, "000000"))

    widths = [26, 12, 10, 10, 7, 12, 9, 10, 10, 10, 10, 5, 10, 8, 22, 18, 10, 30]
    for ci, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(ci)].width = w

    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(HEADERS))}1"

    # Legend row at bottom
    last = len(sorted_trades) + 3
    ws.cell(row=last, column=1,
            value="🟢 WIN  |  🔴 LOSS  |  🟡 OPEN (exit not yet recorded)  |  🔵 SIGNAL (PH8 advisory)").font = \
        Font(name="Arial", size=8, italic=True, color="595959")


def _write_daily_summary(wb, trades: List[Dict]):
    from openpyxl.styles import Font, PatternFill, Alignment
    from openpyxl.utils import get_column_letter

    ws = wb.create_sheet("Daily Summary")
    HEADERS = ["Date", "Trades", "Wins", "Losses", "Win Rate %",
               "Total P&L (₹)", "Best (₹)", "Worst (₹)", "Avg P&L (₹)",
               "Open", "Phases Active"]

    for ci, h in enumerate(HEADERS, 1):
        _style_header(ws.cell(row=1, column=ci, value=h), bg="2E75B6")
    ws.row_dimensions[1].height = 30

    by_date = defaultdict(list)
    for t in trades:
        by_date[t.get("date","")].append(t)

    border   = _thin_border()
    alt_fill = PatternFill("solid", start_color="EBF3FB")
    base     = Font(name="Arial", size=9)

    for ri, day in enumerate(sorted(by_date), 2):
        day_trades = by_date[day]
        closed = [t for t in day_trades if t["status"] not in ("OPEN","SIGNAL")]
        wins   = [t for t in closed if t["status"] == "WIN"]
        losses = [t for t in closed if t["status"] == "LOSS"]
        opens  = [t for t in day_trades if t["status"] == "OPEN"]
        pnls   = [t["pnl_rs"] for t in closed if isinstance(t.get("pnl_rs"),(int,float))]
        phases = ",".join(sorted(set(t.get("phase","") for t in day_trades)))

        total_pnl = sum(pnls)
        wr        = len(wins)/len(closed)*100 if closed else 0
        best      = max(pnls) if pnls else ""
        worst     = min(pnls) if pnls else ""
        avg_pnl   = total_pnl/len(pnls) if pnls else ""

        row_fill = alt_fill if ri % 2 == 0 else None
        vals = [day, len(day_trades), len(wins), len(losses),
                round(wr, 1) if closed else "",
                round(total_pnl, 2) if pnls else "",
                round(best, 2) if best != "" else "",
                round(worst, 2) if worst != "" else "",
                round(avg_pnl, 2) if avg_pnl != "" else "",
                len(opens), phases]

        for ci, val in enumerate(vals, 1):
            cell = ws.cell(row=ri, column=ci, value=val)
            cell.font   = base
            cell.border = border
            cell.alignment = Alignment(vertical="center")
            if row_fill:
                cell.fill = row_fill
            if ci == 6 and isinstance(val, (int, float)):  # P&L
                cell.number_format = '#,##0.00;[Red](#,##0.00)'
                cell.font = Font(name="Arial", size=9, bold=True,
                                 color="375623" if val >= 0 else "9C0006")
            elif ci in (7,8,9) and isinstance(val,(int,float)):
                cell.number_format = '#,##0.00'
            elif ci == 5 and isinstance(val,(int,float)):
                cell.number_format = '0.0"%"'

    # Totals
    last = len(by_date) + 2
    ws.cell(row=last, column=1, value="TOTAL").font = Font(name="Arial", bold=True, size=10)
    for ci, col in [(2,"B"),(3,"C"),(4,"D")]:
        c = ws.cell(row=last, column=ci, value=f"=SUM({col}2:{col}{last-1})")
        c.font = Font(name="Arial", bold=True)
        c.border = border
    pnl_cell = ws.cell(row=last, column=6, value=f"=SUM(F2:F{last-1})")
    pnl_cell.font = Font(name="Arial", bold=True, size=11)
    pnl_cell.number_format = '#,##0.00;[Red](#,##0.00)'
    pnl_cell.border = border
    ws.cell(row=last, column=1).fill = PatternFill("solid", start_color="D6E4F0")

    widths = [14, 8, 6, 8, 11, 16, 14, 14, 13, 6, 22]
    for ci, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(ci)].width = w
    ws.freeze_panes = "A2"


def _write_phase_performance(wb, trades: List[Dict]):
    from openpyxl.styles import Font, PatternFill, Alignment
    from openpyxl.utils import get_column_letter

    ws = wb.create_sheet("Phase Performance")
    HEADERS = ["Phase", "Trades", "Wins", "Losses", "Win Rate %",
               "Total P&L (₹)", "Avg P&L (₹)", "Best (₹)", "Worst (₹)"]

    for ci, h in enumerate(HEADERS, 1):
        _style_header(ws.cell(row=1, column=ci, value=h), bg="375623")
    ws.row_dimensions[1].height = 30

    by_phase = defaultdict(list)
    for t in trades:
        by_phase[t.get("phase","?")].append(t)

    PHASE_COLORS = {
        "PH3":"CFE2F3","PH4":"DCE6F1","PH5":"D9EAD3",
        "PH5A":"EAD1DC","PH6":"FFF2CC","PH8":"FCE5CD","MCX":"D0E4F1",
    }
    border = _thin_border()

    for ri, phase in enumerate(sorted(by_phase), 2):
        pts    = by_phase[phase]
        closed = [t for t in pts if t["status"] not in ("OPEN","SIGNAL")]
        wins   = [t for t in closed if t["status"] == "WIN"]
        losses = [t for t in closed if t["status"] == "LOSS"]
        pnls   = [t["pnl_rs"] for t in closed if isinstance(t.get("pnl_rs"),(int,float))]

        total_pnl = sum(pnls)
        wr        = len(wins)/len(closed)*100 if closed else 0
        avg_pnl   = total_pnl/len(pnls) if pnls else ""
        best      = max(pnls) if pnls else ""
        worst     = min(pnls) if pnls else ""
        fill      = PatternFill("solid", start_color=PHASE_COLORS.get(phase,"F2F2F2"))

        vals = [phase, len(pts), len(wins), len(losses),
                round(wr,1) if closed else "",
                round(total_pnl,2) if pnls else "",
                round(avg_pnl,2) if avg_pnl != "" else "",
                round(best,2) if best != "" else "",
                round(worst,2) if worst != "" else ""]

        for ci, val in enumerate(vals, 1):
            cell = ws.cell(row=ri, column=ci, value=val)
            cell.font   = Font(name="Arial", size=9, bold=(ci==1))
            cell.fill   = fill
            cell.border = border
            cell.alignment = Alignment(vertical="center")
            if ci == 6 and isinstance(val,(int,float)):
                cell.number_format = '#,##0.00;[Red](#,##0.00)'
                cell.font = Font(name="Arial", size=9, bold=True,
                                 color="375623" if val >= 0 else "9C0006")
            elif ci in (7,8,9) and isinstance(val,(int,float)):
                cell.number_format = '#,##0.00'
            elif ci == 5 and isinstance(val,(int,float)):
                cell.number_format = '0.0"%"'

    widths = [10, 8, 6, 8, 11, 16, 14, 14, 14]
    for ci, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(ci)].width = w
    ws.freeze_panes = "A2"


def _write_month_overview(wb, trades: List[Dict]):
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

    ws = wb.create_sheet("Month Overview")
    ws.column_dimensions["A"].width = 30
    ws.column_dimensions["B"].width = 22

    border = _thin_border()
    title_fill = PatternFill("solid", start_color="DEEAF1")

    # Title
    ws.merge_cells("A1:B1")
    ws["A1"] = "PAPER TRADE — 1 MONTH VERIFICATION"
    ws["A1"].font = Font(name="Arial", bold=True, size=13, color="1F4E79")
    ws["A1"].fill = title_fill
    ws["A1"].alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 32

    run_date = datetime.now().strftime("%Y-%m-%d %H:%M")
    ws["A2"] = f"Last updated: {run_date}   |   Period: 2026-04-20 onwards"
    ws["A2"].font = Font(name="Arial", italic=True, size=9, color="595959")

    closed = [t for t in trades if t["status"] not in ("OPEN","SIGNAL")]
    opens  = [t for t in trades if t["status"] == "OPEN"]
    wins   = [t for t in closed if t["status"] == "WIN"]
    losses = [t for t in closed if t["status"] == "LOSS"]
    pnls   = [t["pnl_rs"] for t in closed if isinstance(t.get("pnl_rs"),(int,float))]
    total_pnl = sum(pnls)
    wr        = len(wins)/len(closed)*100 if closed else 0
    avg_pnl   = total_pnl/len(pnls) if pnls else 0
    best      = max(pnls) if pnls else 0
    worst     = min(pnls) if pnls else 0
    days      = sorted(set(t["date"] for t in trades if t.get("date")))

    def section_hdr(row, label, bg):
        ws.merge_cells(f"A{row}:B{row}")
        c = ws.cell(row=row, column=1, value=label)
        c.font = Font(name="Arial", bold=True, size=10, color="FFFFFF")
        c.fill = PatternFill("solid", start_color=bg)
        ws.row_dimensions[row].height = 22

    def metric(row, label, value, bold_val=False, red_if_negative=False):
        cl = ws.cell(row=row, column=1, value=label)
        cv = ws.cell(row=row, column=2, value=value)
        cl.font = Font(name="Arial", bold=True, size=9)
        cl.border = border
        cv.border = border
        color = "000000"
        if red_if_negative and isinstance(value,(int,float)) and value < 0:
            color = "9C0006"
        elif red_if_negative and isinstance(value,(int,float)) and value >= 0:
            color = "375623"
        cv.font = Font(name="Arial", size=9, bold=bold_val, color=color)

    section_hdr(4, "OVERALL RESULTS", "1F4E79")
    metric(5,  "Total Paper Trades",   len(trades))
    metric(6,  "Closed Trades",        len(closed))
    metric(7,  "Open Positions",       len(opens))
    metric(8,  "Wins",                 len(wins))
    metric(9,  "Losses",               len(losses))
    metric(10, "Win Rate",             f"{wr:.1f}%" if closed else "—")
    metric(11, "Total P&L (₹)",        f"₹{total_pnl:,.2f}" if pnls else "—",
               bold_val=True, red_if_negative=True)
    metric(12, "Avg P&L per Trade",    f"₹{avg_pnl:,.2f}" if pnls else "—",
               red_if_negative=True)
    metric(13, "Best Trade (₹)",       f"₹{best:,.2f}" if pnls else "—")
    metric(14, "Worst Trade (₹)",      f"₹{worst:,.2f}" if pnls else "—",
               red_if_negative=True)
    metric(15, "Trading Days",         len(days))
    metric(16, "Date Range",           f"{days[0]}  →  {days[-1]}" if days else "—")

    section_hdr(18, "PHASE BREAKDOWN", "375623")
    by_phase = defaultdict(list)
    for t in trades:
        by_phase[t.get("phase","?")].append(t)
    ri = 19
    for phase in sorted(by_phase):
        pts = by_phase[phase]
        cl  = [t for t in pts if t["status"] not in ("OPEN","SIGNAL")]
        pp  = [t["pnl_rs"] for t in cl if isinstance(t.get("pnl_rs"),(int,float))]
        wns = [t for t in cl if t["status"]=="WIN"]
        wr2 = f"{len(wns)/len(cl)*100:.0f}% WR" if cl else "no closed trades"
        summary = f"{len(pts)} trades | {wr2} | P&L ₹{sum(pp):,.0f}" if pp else f"{len(pts)} trades | {wr2}"
        metric(ri, phase, summary)
        ri += 1

    section_hdr(ri+1, "LIVE READINESS CRITERIA", "7F3F00")
    metric(ri+2, "Target Win Rate",      "≥ 55%  (yours: " + (f"{wr:.1f}%)" if closed else "—)"))
    metric(ri+3, "Target Total P&L",     "≥ ₹0  (no capital loss)")
    metric(ri+4, "Max Weekly Drawdown",  "≤ ₹5,000 in any single week")
    metric(ri+5, "Min Trading Days",     "≥ 20 days observed")
    verdict = "✅ REVIEW COMPLETE — READY FOR LIVE" if (wr >= 55 and total_pnl >= 0 and len(days) >= 20) \
              else "⏳ 1-MONTH REVIEW IN PROGRESS"
    metric(ri+6, "Verdict", verdict, bold_val=True)


def _write_how_to_use(wb):
    from openpyxl.styles import Font, PatternFill, Alignment

    ws = wb.create_sheet("How To Use")
    ws.column_dimensions["A"].width = 90
    ws.merge_cells("A1:A1")
    ws["A1"] = "HOW TO USE THIS PAPER TRADE LOG"
    ws["A1"].font = Font(name="Arial", bold=True, size=14, color="1F4E79")
    ws["A1"].fill = PatternFill("solid", start_color="DEEAF1")
    ws.row_dimensions[1].height = 30

    lines = [
        "",
        "PURPOSE",
        "  This workbook is your 1-month paper-trading proof record (starting 2026-04-20).",
        "  Run eod_trade_consolidator.py every evening after market close to update it.",
        "  At the end of 1 month, review the Month Overview sheet to decide on going live.",
        "",
        "HOW TO RUN THE CONSOLIDATOR",
        "  # Update with today's trades only:",
        "  python eod_trade_consolidator.py --today",
        "",
        "  # Rebuild full history (all dates since 2026-04-20):",
        "  python eod_trade_consolidator.py",
        "",
        "  # Rebuild a specific date:",
        "  python eod_trade_consolidator.py --date 2026-05-01",
        "",
        "SCHEDULE IT (Windows Task Scheduler)",
        "  Program : python",
        "  Args    : \"C:\\...\\Algo_Beta\\eod_trade_consolidator.py\" --today",
        "  Trigger : Daily 16:30 IST, Mon–Fri",
        "",
        "DATA SOURCES USED",
        "  data/blackbox/blackbox_YYYY-MM-DD.json  ← PRIMARY (all exits with P&L)",
        "  data/ph5_paper_trades.json              ← PH5 open/unfilled entries",
        "  data/ph8_paper_signals.json             ← PH8 weekly signals",
        "  data/mcx/paper_trades.csv               ← MCX commodity paper trades",
        "",
        "SHEET GUIDE",
        "  Trade Log         — Every trade row, colour-coded WIN/LOSS/OPEN/SIGNAL",
        "  Daily Summary     — Day-by-day P&L aggregation",
        "  Phase Performance — Win rate and P&L per phase",
        "  Month Overview    — Scorecard with live-readiness verdict",
        "",
        "COLOUR CODING",
        "  Green  = WIN     (trade closed in profit)",
        "  Red    = LOSS    (trade closed at a loss)",
        "  Yellow = OPEN    (entry logged, exit not yet in blackbox)",
        "  Blue   = SIGNAL  (PH8 advisory signal, no position taken)",
        "",
        "GOING LIVE (after 1-month review)",
        "  1. Open config.py",
        "  2. Set MASTER_PAPER_MODE = False",
        "  3. Flip individual phase flags as needed",
        "  4. Keep running this consolidator — it becomes your live trade audit log",
    ]
    for ri, line in enumerate(lines, 2):
        cell = ws.cell(row=ri, column=1, value=line)
        if line and not line.startswith("  "):
            cell.font = Font(name="Arial", bold=True, size=10, color="1F4E79")
        else:
            cell.font = Font(name="Arial", size=9)


# ════════════════════════════════════════════════════════════════════════════
# 4. UTILITY HELPERS
# ════════════════════════════════════════════════════════════════════════════

def _pnl_to_status(pnl) -> str:
    if pnl is None:
        return "OPEN"
    if isinstance(pnl, (int, float)):
        if pnl > 0:   return "WIN"
        if pnl < 0:   return "LOSS"
        return "BREAKEVEN"
    return "OPEN"


def _safe_float(val, default=0.0) -> float:
    try:
        return float(val) if val not in (None, "", "nan") else default
    except (ValueError, TypeError):
        return default


def _safe_int(val, default=0) -> int:
    try:
        return int(float(val)) if val not in (None, "") else default
    except (ValueError, TypeError):
        return default


# ════════════════════════════════════════════════════════════════════════════
# 5. MAIN
# ════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="EOD Paper Trade Consolidator")
    parser.add_argument("--today",  action="store_true",
                        help="Only process today's blackbox file")
    parser.add_argument("--date",   type=str, default=None,
                        help="Process a specific date (YYYY-MM-DD)")
    args = parser.parse_args()

    filter_date = None
    if args.today:
        filter_date = date.today()
        log.info(f"Mode: TODAY ({filter_date})")
    elif args.date:
        filter_date = date.fromisoformat(args.date)
        log.info(f"Mode: SPECIFIC DATE ({filter_date})")
    else:
        log.info("Mode: FULL HISTORY (all dates since 2026-04-20)")

    log.info("=" * 60)
    log.info("EOD TRADE CONSOLIDATOR — reading data sources")
    log.info("=" * 60)

    # Collect from all sources
    all_trades = []
    all_trades.extend(read_blackbox_files(filter_date))
    all_trades.extend(read_ph5_paper_trades())
    all_trades.extend(read_ph8_paper_signals())
    all_trades.extend(read_mcx_paper_trades())

    log.info(f"  Total raw records : {len(all_trades)}")

    all_trades = deduplicate(all_trades)

    log.info(f"  Writing Excel     : {len(all_trades)} rows across 4 sheets")
    log.info("=" * 60)

    out = write_excel(all_trades)

    # Summary
    closed = [t for t in all_trades if t["status"] not in ("OPEN","SIGNAL")]
    wins   = [t for t in closed if t["status"] == "WIN"]
    pnls   = [t["pnl_rs"] for t in closed if isinstance(t.get("pnl_rs"),(int,float))]

    log.info("DONE")
    log.info(f"  Total trades   : {len(all_trades)}")
    log.info(f"  Closed         : {len(closed)}  (W:{len(wins)} L:{len(closed)-len(wins)})")
    log.info(f"  Total P&L      : ₹{sum(pnls):,.2f}" if pnls else "  Total P&L      : —")
    log.info(f"  Excel saved to : {out}")
    log.info("=" * 60)


if __name__ == "__main__":
    main()
