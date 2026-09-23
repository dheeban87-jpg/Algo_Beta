"""
Algo_Beta GUI -- Dashboard View (v1.7)
=======================================
Phase status strip, today's P&L, active positions, expiry countdown.
Sub-view switching: click phase badge or sidebar info button to see phase details.
All trading data is MOCK for display purposes.
"""

import customtkinter as ctk
import datetime
import math

import sys as _sys
import os as _os
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from theme import (  # noqa: E402
    BG_APP, BG_PANEL, BG_HEADER, BG_INPUT,
    BORDER, BORDER_DIM,
    TEXT_PRIMARY, TEXT_LABEL, TEXT_MUTED, TEXT_DIM, TEXT_ENTRY,
    ACCENT_CYAN, GREEN, RED, AMBER,
    FONT_FAMILY, FONT_LOGO, FONT_TITLE, FONT_HEADING, FONT_BODY_BOLD, FONT_BODY,
    FONT_SMALL_BOLD, FONT_SMALL, FONT_TINY_BOLD, FONT_TINY,
)

# Phases that have detail sub-views (clickable badges)
CLICKABLE_PHASES = {
    "PH1": "ph1", "PH2": "ph2", "PH3": "ph3",
    "PH4": "ph4", "PH5": "ph5", "PH5A": "ph5a",
    "PH6": "ph6", "PH7": "ph7", "PH8": "ph8",
}

# -- Mock Trading Data -----------------------------------------------------
MOCK_PNL = {
    "total": 12340,
    "pct": 2.68,
    "wins": 3,
    "losses": 1,
    "win_rate": 75,
    "best_trade": ("RAMCOCEM", "+2.61%"),
    "worst_trade": ("HDFCBANK", "-0.87%"),
    "rr_achieved": "1:2.1",
}

MOCK_POSITIONS = [
    {"symbol": "RAMCOCEM",  "product": "CNC", "entry": 882.00,  "current": 905.30,  "qty": 50},
    {"symbol": "HDFCBANK",  "product": "CNC", "entry": 1445.00, "current": 1432.50, "qty": 25},
    {"symbol": "RELIANCE",  "product": "CNC", "entry": 2380.00, "current": 2417.00, "qty": 15},
]


def _section_frame(parent, title, row, col=0, columnspan=1):
    """Reusable section frame matching v1.5 style."""
    container = ctk.CTkFrame(parent, fg_color=BG_PANEL, corner_radius=8,
                             border_width=1, border_color=BORDER)
    container.grid(row=row, column=col, columnspan=columnspan,
                   sticky="nsew", padx=6, pady=6)

    title_bar = ctk.CTkFrame(container, fg_color=BG_HEADER, corner_radius=0, height=32)
    title_bar.pack(fill="x")
    title_bar.pack_propagate(False)

    ctk.CTkLabel(title_bar, text=title,
                 font=FONT_TINY_BOLD, text_color=TEXT_MUTED,
                 anchor="w").pack(side="left", padx=12, pady=6)

    ctk.CTkLabel(container, text="", height=4).pack()
    return container


class DashboardView(ctk.CTkFrame):
    """Dashboard tab -- phase overview, P&L, positions, expiry countdown.
    Supports sub-view switching for phase detail views."""

    def __init__(self, parent, config, data_bridge=None):
        super().__init__(parent, fg_color="transparent")
        self.config = config
        self.data_bridge = data_bridge
        self._countdown_job = None

        # Sub-view management
        self._current_subview = "overview"
        self._subviews = {}  # cache created phase detail views

        # Live data label references (populated by _build_* methods)
        self._pnl_total_lbl = None
        self._pnl_pct_lbl = None
        self._pnl_stat_labels = {}   # key -> (value_label, ...)
        self._pnl_bar = None
        self._pos_frame = None       # parent frame for position rows
        self._pos_rows_frame = None  # container for dynamic position rows

        self._build_ui()

        # Register for live data updates
        if self.data_bridge:
            self.data_bridge.register_callback(self, self._on_live_data)

    def _build_ui(self):
        # Overview content (the main dashboard)
        self._overview = ctk.CTkScrollableFrame(self, fg_color="transparent",
                                                scrollbar_button_color=BORDER_DIM)
        self._overview.pack(fill="both", expand=True, padx=2, pady=2)

        self._overview.columnconfigure(0, weight=1)
        self._overview.columnconfigure(1, weight=1)

        # Row 0: Phase Status Strip (full width)
        self._build_phase_status(self._overview, row=0)

        # Row 1 left: Today's P&L
        self._build_pnl_card(self._overview, row=1, col=0)

        # Row 1 right: Active Positions
        self._build_positions(self._overview, row=1, col=1)

        # Row 2: Expiry Countdown (full width)
        self._build_expiry(self._overview, row=2)

    # ==================================================================
    #  SUB-VIEW SWITCHING
    # ==================================================================

    def show_phase_detail(self, phase_id):
        """Switch to a phase detail sub-view."""
        # Hide current content
        if self._current_subview == "overview":
            self._overview.pack_forget()
        elif self._current_subview in self._subviews:
            self._subviews[self._current_subview].pack_forget()

        # Create phase detail if not cached
        if phase_id not in self._subviews:
            if phase_id == "trades_history":
                from views.trades_history import TradesHistoryView
                view = TradesHistoryView(self, on_back=self.show_overview,
                                         data_bridge=self.data_bridge)
            else:
                from views.phase_details import create_phase_detail
                view = create_phase_detail(phase_id, self, on_back=self.show_overview,
                                           data_bridge=self.data_bridge)
            if view is None:
                # Unknown phase -- go back to overview
                self.show_overview()
                return
            self._subviews[phase_id] = view

        # Show phase detail
        self._subviews[phase_id].pack(fill="both", expand=True, padx=2, pady=2)
        self._current_subview = phase_id

    def show_overview(self):
        """Return to main dashboard overview."""
        # Hide current phase detail
        if self._current_subview in self._subviews:
            self._subviews[self._current_subview].pack_forget()

        # Show overview
        self._overview.pack(fill="both", expand=True, padx=2, pady=2)
        self._current_subview = "overview"

    # ==================================================================
    #  PHASE STATUS STRIP
    # ==================================================================

    def _build_phase_status(self, parent, row):
        frame = _section_frame(parent, "PHASE STATUS", row=row, columnspan=2)

        strip = ctk.CTkFrame(frame, fg_color="transparent")
        strip.pack(fill="x", padx=10, pady=(0, 10))

        phases = [
            ("PH1", None, "RUNNING"),
            ("PH2", None, "RUNNING"),
            ("PH3", None, "RUNNING"),
            ("PH4", None, "RUNNING"),
            ("PH5", "ENABLE_PH5", None),
            ("PH5A", "ENABLE_PH5A", None),
            ("PH6", "ENABLE_PH6", None),
            ("PH7", "ENABLE_PH7", None),
            ("PH8", "ENABLE_PH8", None),
            ("MIE", "ENABLE_MIE", None),
        ]

        for name, config_key, forced_status in phases:
            badge = ctk.CTkFrame(strip, fg_color=BG_INPUT, corner_radius=6)
            badge.pack(side="left", padx=3, pady=2, fill="x", expand=True)

            inner = ctk.CTkFrame(badge, fg_color="transparent")
            inner.pack(padx=8, pady=6)

            # Determine status
            if forced_status == "RUNNING":
                color = "#22c55e"
                status_text = "RUNNING"
            elif config_key:
                enabled = self.config.get(config_key, False)
                if name == "MIE" and enabled:
                    color = "#f59e0b"
                    status_text = "ON"
                elif enabled:
                    color = "#22c55e"
                    status_text = "ON"
                else:
                    color = "#3f3f46"
                    status_text = "OFF"
            else:
                color = "#3f3f46"
                status_text = "OFF"

            dot_lbl = ctk.CTkLabel(inner, text="●", font=("", 12),
                                   text_color=color, width=14)
            dot_lbl.pack(side="left", padx=(0, 4))

            name_lbl = ctk.CTkLabel(inner, text=name,
                                    font=FONT_TINY_BOLD,
                                    text_color=TEXT_PRIMARY)
            name_lbl.pack(side="left", padx=(0, 6))

            status_lbl = ctk.CTkLabel(inner, text=status_text,
                                      font=FONT_TINY,
                                      text_color=color)
            status_lbl.pack(side="left")

            # Make clickable for phases with detail views
            if name in CLICKABLE_PHASES:
                pid = CLICKABLE_PHASES[name]
                handler = lambda e, p=pid: self.show_phase_detail(p)
                for w in [badge, inner, dot_lbl, name_lbl, status_lbl]:
                    w.configure(cursor="hand2")
                    w.bind("<Button-1>", handler)

    # ==================================================================
    #  TODAY'S P&L CARD
    # ==================================================================

    def _build_pnl_card(self, parent, row, col):
        frame = _section_frame(parent, "TODAY'S P&L", row=row, col=col)

        d = MOCK_PNL
        is_positive = d["total"] >= 0
        pnl_color = "#22c55e" if is_positive else "#ef4444"
        sign = "+" if is_positive else ""

        # Big P&L number (store reference for live update)
        self._pnl_total_lbl = ctk.CTkLabel(
            frame, text=f"{sign}Rs.{d['total']:,}",
            font=(FONT_FAMILY, 32, "bold"), text_color=pnl_color)
        self._pnl_total_lbl.pack(padx=16, pady=(4, 0), anchor="w")

        self._pnl_pct_lbl = ctk.CTkLabel(
            frame, text=f"{sign}{d['pct']}% today",
            font=FONT_HEADING, text_color=pnl_color)
        self._pnl_pct_lbl.pack(padx=16, pady=(0, 8), anchor="w")

        # Stats box
        stats = ctk.CTkFrame(frame, fg_color=BG_INPUT, corner_radius=6)
        stats.pack(fill="x", padx=12, pady=(0, 4))

        stat_keys = ["win_loss", "win_rate", "best", "worst", "rr"]
        stat_items = [
            ("Win / Loss",    f"{d['wins']}W / {d['losses']}L",    "win_loss"),
            ("Win Rate",      f"{d['win_rate']}%",                  "win_rate"),
            ("Best Trade",    f"{d['best_trade'][0]}  {d['best_trade'][1]}", "best"),
            ("Worst Trade",   f"{d['worst_trade'][0]}  {d['worst_trade'][1]}", "worst"),
            ("R:R Achieved",  d["rr_achieved"],                     "rr"),
        ]

        for label, value, key in stat_items:
            r = ctk.CTkFrame(stats, fg_color="transparent")
            r.pack(fill="x", padx=12, pady=2)
            ctk.CTkLabel(r, text=label, font=FONT_TINY,
                         text_color=TEXT_MUTED, anchor="w").pack(side="left")

            val_color = TEXT_PRIMARY
            if "+" in value:
                val_color = "#22c55e"
            elif "-" in value:
                val_color = "#ef4444"
            val_lbl = ctk.CTkLabel(r, text=value, font=FONT_SMALL_BOLD,
                                    text_color=val_color, anchor="e")
            val_lbl.pack(side="right")
            self._pnl_stat_labels[key] = val_lbl

        # Win rate progress bar
        bar_frame = ctk.CTkFrame(stats, fg_color="transparent")
        bar_frame.pack(fill="x", padx=12, pady=(4, 8))
        ctk.CTkLabel(bar_frame, text="Win Rate", font=FONT_TINY,
                     text_color=TEXT_DIM).pack(side="left")
        bar_color = "#22c55e" if d["win_rate"] >= 50 else "#ef4444"
        self._pnl_bar = ctk.CTkProgressBar(bar_frame, height=8, corner_radius=4,
                                            fg_color=BORDER_DIM, progress_color=bar_color)
        self._pnl_bar.pack(side="right", fill="x", expand=True, padx=(8, 0))
        self._pnl_bar.set(d["win_rate"] / 100)

        ctk.CTkLabel(frame, text="", height=4).pack()

    # ==================================================================
    #  ACTIVE POSITIONS TABLE
    # ==================================================================

    def _build_positions(self, parent, row, col):
        frame = _section_frame(parent, "ACTIVE POSITIONS", row=row, col=col)
        self._pos_frame = frame

        max_pos = self.config.get("MAX_TOTAL_POSITIONS", 8)
        filled = len(MOCK_POSITIONS)

        # Slots indicator (store references)
        slots_row = ctk.CTkFrame(frame, fg_color="transparent")
        slots_row.pack(fill="x", padx=12, pady=(0, 4))

        self._pos_slots_lbl = ctk.CTkLabel(
            slots_row, text=f"{filled} / {max_pos} slots filled",
            font=FONT_TINY, text_color=TEXT_LABEL)
        self._pos_slots_lbl.pack(side="left")

        self._pos_dots_frame = ctk.CTkFrame(slots_row, fg_color="transparent")
        self._pos_dots_frame.pack(side="right")
        self._pos_dots = []
        for i in range(max_pos):
            dot_color = "#22c55e" if i < filled else BORDER_DIM
            dot = ctk.CTkLabel(self._pos_dots_frame, text="●", font=("", 10),
                               text_color=dot_color, width=14)
            dot.pack(side="left")
            self._pos_dots.append(dot)

        # Table header
        hdr = ctk.CTkFrame(frame, fg_color=BG_HEADER, corner_radius=0, height=28)
        hdr.pack(fill="x", padx=8, pady=(4, 0))
        hdr.pack_propagate(False)

        cols = [("SYMBOL", 90), ("PROD", 45), ("ENTRY", 75), ("CURRENT", 75),
                ("P&L", 80), ("P&L %", 55)]
        for label, w in cols:
            ctk.CTkLabel(hdr, text=label, font=FONT_TINY_BOLD,
                         text_color=TEXT_MUTED, width=w, anchor="w"
                         ).pack(side="left", padx=4)

        # Dynamic rows container
        self._pos_rows_frame = ctk.CTkFrame(frame, fg_color="transparent")
        self._pos_rows_frame.pack(fill="x")

        # Initial mock data
        self._render_position_rows(MOCK_POSITIONS, max_pos)

        ctk.CTkLabel(frame, text="", height=4).pack()

    def _render_position_rows(self, positions, max_pos=8):
        """Render position rows (reusable for live data refresh)."""
        # Clear existing rows
        for child in self._pos_rows_frame.winfo_children():
            child.destroy()

        filled = len(positions)

        # Data rows
        for pos in positions:
            entry = pos.get("entry", pos.get("entry_price", 0))
            current = pos.get("current", pos.get("current_price", 0))
            qty = pos.get("qty", pos.get("quantity", 0))
            product = pos.get("product", pos.get("direction", "CNC"))

            pnl = (current - entry) * qty if entry > 0 else 0
            pnl_pct = ((current - entry) / entry) * 100 if entry > 0 else 0
            is_pos = pnl >= 0
            pnl_color = "#22c55e" if is_pos else "#ef4444"
            sign = "+" if is_pos else ""

            row_frame = ctk.CTkFrame(self._pos_rows_frame, fg_color="transparent", height=26)
            row_frame.pack(fill="x", padx=8, pady=1)
            row_frame.pack_propagate(False)

            vals = [
                (pos.get("symbol", ""), 90, TEXT_PRIMARY, "bold"),
                (product, 45, TEXT_MUTED, "normal"),
                (f"Rs.{entry:.0f}", 75, TEXT_LABEL, "normal"),
                (f"Rs.{current:.0f}", 75, TEXT_LABEL, "normal"),
                (f"{sign}Rs.{pnl:,.0f}", 80, pnl_color, "bold"),
                (f"{sign}{pnl_pct:.1f}%", 55, pnl_color, "bold"),
            ]
            for text, w, color, weight in vals:
                ctk.CTkLabel(row_frame, text=text,
                             font=(FONT_FAMILY, 10, weight),
                             text_color=color, width=w, anchor="w"
                             ).pack(side="left", padx=4)

        # Empty slots
        for _ in range(max(0, max_pos - filled)):
            empty = ctk.CTkFrame(self._pos_rows_frame, fg_color="transparent", height=26)
            empty.pack(fill="x", padx=8, pady=1)
            empty.pack_propagate(False)
            ctk.CTkLabel(empty, text="--", font=FONT_TINY,
                         text_color=TEXT_DIM).pack(side="left", padx=4)

        # Update slots indicator
        if hasattr(self, '_pos_slots_lbl') and self._pos_slots_lbl:
            self._pos_slots_lbl.configure(text=f"{filled} / {max_pos} slots filled")
        if hasattr(self, '_pos_dots'):
            for i, dot in enumerate(self._pos_dots):
                dot.configure(text_color="#22c55e" if i < filled else BORDER_DIM)

    # ==================================================================
    #  EXPIRY COUNTDOWN
    # ==================================================================

    def _build_expiry(self, parent, row):
        frame = _section_frame(parent, "NEXT EXPIRY -- TUESDAY CYCLE",
                               row=row, columnspan=2)

        self._expiry_frame = frame

        content = ctk.CTkFrame(frame, fg_color="transparent")
        content.pack(fill="x", padx=12, pady=(0, 8))

        # Left: expiry date
        self._expiry_date_label = ctk.CTkLabel(
            content, text="",
            font=FONT_BODY, text_color=TEXT_LABEL,
        )
        self._expiry_date_label.pack(side="left")

        # Right: countdown
        self._countdown_label = ctk.CTkLabel(
            content, text="",
            font=FONT_LOGO, text_color="#22c55e",
        )
        self._countdown_label.pack(side="right")

        # Progress bar
        self._expiry_bar = ctk.CTkProgressBar(
            frame, height=10, corner_radius=5,
            fg_color=BORDER_DIM, progress_color="#22c55e",
        )
        self._expiry_bar.pack(fill="x", padx=12, pady=(0, 10))
        self._expiry_bar.set(0)

        self._tick_expiry()

    def _get_next_tuesday(self):
        """Get next Tuesday at 15:30 IST."""
        now = datetime.datetime.now()
        target_time = now.replace(hour=15, minute=30, second=0, microsecond=0)

        # Tuesday = weekday 1
        days_ahead = (1 - now.weekday()) % 7
        if days_ahead == 0 and now >= target_time:
            days_ahead = 7

        next_tue = now + datetime.timedelta(days=days_ahead)
        return next_tue.replace(hour=15, minute=30, second=0, microsecond=0)

    def _get_prev_tuesday(self):
        """Get previous Tuesday at 15:30."""
        now = datetime.datetime.now()
        target_time = now.replace(hour=15, minute=30, second=0, microsecond=0)

        days_back = (now.weekday() - 1) % 7
        if days_back == 0 and now < target_time:
            days_back = 7

        prev_tue = now - datetime.timedelta(days=days_back)
        return prev_tue.replace(hour=15, minute=30, second=0, microsecond=0)

    def _tick_expiry(self):
        """Update countdown every second."""
        now = datetime.datetime.now()
        next_tue = self._get_next_tuesday()
        prev_tue = self._get_prev_tuesday()
        delta = next_tue - now

        total_seconds = delta.total_seconds()
        days = int(total_seconds // 86400)
        hours = int((total_seconds % 86400) // 3600)
        mins = int((total_seconds % 3600) // 60)
        secs = int(total_seconds % 60)

        # Date label
        self._expiry_date_label.configure(
            text=next_tue.strftime("Tuesday, %d %B %Y -- 15:30 IST"))

        # Countdown
        self._countdown_label.configure(text=f"{days}d {hours}h {mins}m {secs}s")

        # Color based on urgency
        if total_seconds > 86400:
            color = "#22c55e"
        elif total_seconds > 14400:
            color = "#f59e0b"
        else:
            color = "#ef4444"
        self._countdown_label.configure(text_color=color)
        self._expiry_bar.configure(progress_color=color)

        # Progress bar
        total_span = (next_tue - prev_tue).total_seconds()
        elapsed = (now - prev_tue).total_seconds()
        progress = max(0, min(1, elapsed / total_span)) if total_span > 0 else 0
        self._expiry_bar.set(progress)

        self._countdown_job = self.after(1000, self._tick_expiry)

    # ==================================================================
    #  LIVE DATA UPDATES
    # ==================================================================

    def _on_live_data(self, data):
        """Callback from DataBridge — refresh dashboard with live data."""
        if not data or not data.db_available:
            return  # No data yet — keep mock display

        self._refresh_pnl(data)
        self._refresh_positions(data)

    def _refresh_pnl(self, data):
        """Update P&L card from LiveData."""
        try:
            total = data.total_pnl_today
            is_positive = total >= 0
            pnl_color = "#22c55e" if is_positive else "#ef4444"
            sign = "+" if is_positive else ""

            # Starting capital for % calc (fallback to 1 to avoid division by 0)
            capital = data.starting_capital or data.free_capital or 1
            pct = (total / capital) * 100 if capital > 0 else 0

            if self._pnl_total_lbl:
                self._pnl_total_lbl.configure(
                    text=f"{sign}Rs.{total:,.0f}", text_color=pnl_color)
            if self._pnl_pct_lbl:
                self._pnl_pct_lbl.configure(
                    text=f"{sign}{pct:.2f}% today", text_color=pnl_color)

            wins = data.win_count
            losses = data.loss_count
            total_trades = wins + losses
            win_rate = (wins / total_trades * 100) if total_trades > 0 else 0

            # Find best/worst trades from today's trades
            best_sym, best_pct = "--", "0%"
            worst_sym, worst_pct = "--", "0%"
            if data.trades_today:
                sorted_trades = sorted(data.trades_today, key=lambda t: t.pnl_pct)
                if sorted_trades:
                    worst = sorted_trades[0]
                    best = sorted_trades[-1]
                    best_sym = best.symbol
                    best_pct = f"+{best.pnl_pct:.2f}%" if best.pnl_pct >= 0 else f"{best.pnl_pct:.2f}%"
                    worst_sym = worst.symbol
                    worst_pct = f"+{worst.pnl_pct:.2f}%" if worst.pnl_pct >= 0 else f"{worst.pnl_pct:.2f}%"

            # Compute simple R:R
            avg_win = sum(t.pnl for t in data.trades_today if t.win) / max(1, wins)
            avg_loss = abs(sum(t.pnl for t in data.trades_today if not t.win) / max(1, losses))
            rr_text = f"1:{avg_win / avg_loss:.1f}" if avg_loss > 0 else "N/A"

            stat_updates = {
                "win_loss": f"{wins}W / {losses}L",
                "win_rate": f"{win_rate:.0f}%",
                "best": f"{best_sym}  {best_pct}",
                "worst": f"{worst_sym}  {worst_pct}",
                "rr": rr_text,
            }
            for key, text in stat_updates.items():
                lbl = self._pnl_stat_labels.get(key)
                if lbl:
                    val_color = TEXT_PRIMARY
                    if "+" in text:
                        val_color = "#22c55e"
                    elif "-" in text:
                        val_color = "#ef4444"
                    lbl.configure(text=text, text_color=val_color)

            if self._pnl_bar:
                bar_color = "#22c55e" if win_rate >= 50 else "#ef4444"
                self._pnl_bar.configure(progress_color=bar_color)
                self._pnl_bar.set(win_rate / 100)

        except Exception:
            pass  # Silently ignore refresh errors — keep last display

    def _refresh_positions(self, data):
        """Update positions table from LiveData."""
        try:
            if not data.positions:
                return  # Keep mock display if no live positions

            max_pos = self.config.get("MAX_TOTAL_POSITIONS", 8)
            positions = [
                {
                    "symbol": p.symbol,
                    "product": p.direction or "CNC",
                    "entry": p.entry_price,
                    "current": p.current_price or p.entry_price,
                    "qty": p.quantity,
                }
                for p in data.positions
            ]
            self._render_position_rows(positions, max_pos)

        except Exception:
            pass  # Silently ignore refresh errors — keep last display

    def destroy(self):
        if self._countdown_job:
            self.after_cancel(self._countdown_job)
        super().destroy()
