"""
Algo_Beta GUI -- Trades History View
=====================================
Sub-view inside Dashboard tab showing all-time trade history
with P/L, broker charges deduction, and performance tracking.
Paginated table with consolidated summary panel.
"""

import customtkinter as ctk

import sys as _sys
import os as _os
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from theme import (  # noqa: E402
    BG_APP, BG_PANEL, BG_HEADER, BG_INPUT,
    BORDER, BORDER_DIM,
    TEXT_PRIMARY, TEXT_LABEL, TEXT_MUTED, TEXT_DIM,
    GREEN, RED, AMBER, CYAN,
    FONT_FAMILY, FONT_TITLE, FONT_HEADING, FONT_BODY_BOLD, FONT_BODY,
    FONT_SMALL_BOLD, FONT_SMALL, FONT_TINY_BOLD, FONT_TINY,
)

ROWS_PER_PAGE = 25


# ═══════════════════════════════════════════════════════════════════════════════
# TRADES HISTORY VIEW
# ═══════════════════════════════════════════════════════════════════════════════

class TradesHistoryView(ctk.CTkFrame):
    """All-time trade history with P/L, broker charges, pagination."""

    def __init__(self, parent, on_back, data_bridge=None):
        super().__init__(parent, fg_color="transparent")
        self._on_back = on_back
        self._data_bridge = data_bridge
        self._current_page = 1
        self._total_pages = 1
        self._data = {}

        # Widget refs for dynamic updates
        self._table_scroll = None
        self._page_label = None
        self._prev_btn = None
        self._next_btn = None
        self._status_bar_frame = None

        self._load_data()
        self._build()

    # ------------------------------------------------------------------
    #  DATA
    # ------------------------------------------------------------------

    def _load_data(self):
        """Fetch trade history page from DataBridge."""
        if self._data_bridge:
            try:
                self._data = self._data_bridge.get_trades_history(
                    page=self._current_page,
                    per_page=ROWS_PER_PAGE,
                )
                self._total_pages = self._data.get("total_pages", 1) or 1
            except Exception:
                self._data = {}
                self._total_pages = 1

    # ------------------------------------------------------------------
    #  BUILD
    # ------------------------------------------------------------------

    def _build(self):
        """Build full view layout."""
        d = self._data
        agg = d.get("aggregates", {})

        # ── Back button ───────────────────────────────────────────────
        back = ctk.CTkButton(
            self, text="<  RETURN TO OVERVIEW",
            font=FONT_BODY_BOLD,
            fg_color=BG_HEADER, hover_color=BORDER,
            text_color=TEXT_LABEL, height=32, width=220,
            anchor="w", command=self._on_back,
        )
        back.pack(anchor="w", padx=8, pady=(4, 4))

        # ── Title bar ────────────────────────────────────────────────
        title = ctk.CTkFrame(self, fg_color=BG_PANEL, corner_radius=8,
                             border_width=1, border_color=BORDER, height=38)
        title.pack(fill="x", padx=8, pady=(0, 4))
        title.pack_propagate(False)
        ctk.CTkLabel(title, text="TRADES HISTORY -- PERFORMANCE TRACKER",
                     font=FONT_HEADING,
                     text_color=CYAN, anchor="w").pack(side="left", padx=14, pady=6)

        # ── Summary panel ────────────────────────────────────────────
        agg["total_trades"] = d.get("total_trades", 0)
        self._build_summary(agg)

        # ── Trade table ──────────────────────────────────────────────
        self._build_table(d.get("trades", []))

        # ── Pagination ───────────────────────────────────────────────
        self._build_pagination()

        # ── Status bar ───────────────────────────────────────────────
        self._build_status_bar(d)

    # ------------------------------------------------------------------
    #  SUMMARY PANEL
    # ------------------------------------------------------------------

    def _build_summary(self, agg):
        """Consolidated performance summary at top."""
        panel = ctk.CTkFrame(self, fg_color=BG_PANEL, corner_radius=8,
                             border_width=1, border_color=BORDER)
        panel.pack(fill="x", padx=8, pady=(0, 4))

        # Title bar
        tb = ctk.CTkFrame(panel, fg_color=BG_HEADER, corner_radius=0, height=30)
        tb.pack(fill="x")
        tb.pack_propagate(False)
        ctk.CTkLabel(tb, text="CONSOLIDATED SUMMARY",
                     font=FONT_SMALL_BOLD,
                     text_color=TEXT_MUTED, anchor="w").pack(side="left", padx=12, pady=5)

        body = ctk.CTkFrame(panel, fg_color="transparent")
        body.pack(fill="x", padx=4, pady=(4, 8))

        # Row 1: Trades | Gross P/L | Charges | Net P/L
        r1 = ctk.CTkFrame(body, fg_color="transparent")
        r1.pack(fill="x", padx=8, pady=2)
        self._summary_item(r1, "Total Trades", str(agg.get("total_trades", 0)),
                           TEXT_PRIMARY)
        self._summary_item(r1, "Gross P/L",
                           self._fmt_pnl(agg.get("total_gross_pnl", 0)),
                           GREEN if agg.get("total_gross_pnl", 0) >= 0 else RED)
        self._summary_item(r1, "Total Charges",
                           f"Rs.{agg.get('total_charges', 0):,.2f}", AMBER)
        net = agg.get("total_net_pnl", 0)
        self._summary_item(r1, "Net P/L", self._fmt_pnl(net),
                           GREEN if net >= 0 else RED)

        # Row 2: Win Rate | Profit Factor | Avg P/L
        r2 = ctk.CTkFrame(body, fg_color="transparent")
        r2.pack(fill="x", padx=8, pady=2)

        wr = agg.get("win_rate", 0)
        self._summary_item(r2, "Win Rate", f"{wr:.1f}%",
                           GREEN if wr >= 50 else RED)
        pf = agg.get("profit_factor", 0)
        self._summary_item(r2, "Profit Factor", f"{pf:.2f}",
                           GREEN if pf >= 1.0 else RED)
        avg = agg.get("avg_pnl_per_trade", 0)
        self._summary_item(r2, "Avg P/L / Trade", self._fmt_pnl(avg),
                           GREEN if avg >= 0 else RED)

        wc = agg.get("win_count", 0)
        lc = agg.get("loss_count", 0)
        self._summary_item(r2, "W / L", f"{wc}W / {lc}L", TEXT_PRIMARY)

        # Row 3: Best | Worst | Avg Duration
        r3 = ctk.CTkFrame(body, fg_color="transparent")
        r3.pack(fill="x", padx=8, pady=2)

        best = agg.get("best_trade", {})
        self._summary_item(r3, "Best Trade",
                           f"{best.get('symbol', '--')} {self._fmt_pnl(best.get('net_pnl', 0))}",
                           GREEN)
        worst = agg.get("worst_trade", {})
        self._summary_item(r3, "Worst Trade",
                           f"{worst.get('symbol', '--')} {self._fmt_pnl(worst.get('net_pnl', 0))}",
                           RED)
        dur = agg.get("avg_duration_min", 0)
        dur_text = f"{dur:.0f}m" if dur else "--"
        self._summary_item(r3, "Avg Duration", dur_text, TEXT_LABEL)

    @staticmethod
    def _summary_item(parent, label, value, value_color):
        """Single summary stat item (inline, pack side=left)."""
        f = ctk.CTkFrame(parent, fg_color=BG_INPUT, corner_radius=6)
        f.pack(side="left", fill="x", expand=True, padx=3, pady=2)
        inner = ctk.CTkFrame(f, fg_color="transparent")
        inner.pack(padx=8, pady=4)
        ctk.CTkLabel(inner, text=label, font=FONT_TINY,
                     text_color=TEXT_MUTED).pack(anchor="w")
        ctk.CTkLabel(inner, text=value, font=FONT_BODY_BOLD,
                     text_color=value_color).pack(anchor="w")

    # ------------------------------------------------------------------
    #  TRADE TABLE
    # ------------------------------------------------------------------

    TABLE_COLS = [
        ("DATE",     85),
        ("SYMBOL",   80),
        ("TYPE",     40),
        ("QTY",      40),
        ("ENTRY",    70),
        ("EXIT",     70),
        ("GROSS",    75),
        ("CHARGES",  65),
        ("NET P/L",  75),
        ("SOURCE",   65),
        ("TCAS",     55),
        ("DUR",      40),
        ("REASON",  100),
    ]

    def _build_table(self, trades):
        """Scrollable trades table with header."""
        # Container
        tbl = ctk.CTkFrame(self, fg_color=BG_PANEL, corner_radius=8,
                           border_width=1, border_color=BORDER)
        tbl.pack(fill="both", expand=True, padx=8, pady=(0, 4))

        # Header
        hdr = ctk.CTkFrame(tbl, fg_color=BG_HEADER, corner_radius=0, height=26)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        for label, w in self.TABLE_COLS:
            ctk.CTkLabel(hdr, text=label, font=FONT_TINY_BOLD,
                         text_color=TEXT_MUTED, width=w, anchor="w"
                         ).pack(side="left", padx=4)

        # Scrollable rows area
        self._table_scroll = ctk.CTkScrollableFrame(
            tbl, fg_color="transparent",
            scrollbar_button_color=BORDER_DIM,
        )
        self._table_scroll.pack(fill="both", expand=True, padx=0, pady=0)

        self._render_rows(trades)

    def _render_rows(self, trades):
        """Render trade rows inside _table_scroll."""
        if not trades:
            ctk.CTkLabel(self._table_scroll, text="No trades recorded yet",
                         font=FONT_BODY, text_color=TEXT_DIM,
                         ).pack(pady=40)
            return

        for t in trades:
            row = ctk.CTkFrame(self._table_scroll, fg_color="transparent", height=24)
            row.pack(fill="x", pady=1)
            row.pack_propagate(False)

            gross = t.get("gross_pnl", 0)
            net = t.get("net_pnl", 0)
            charges_total = t.get("charges", {}).get("total", 0)
            direction = t.get("direction", "LONG")
            dur = t.get("duration_minutes")
            dur_text = f"{dur:.0f}m" if dur is not None else "--"

            # Format date to DD/MM/YYYY
            raw_date = t.get("date", "")
            try:
                # "2026-03-05" → "05/03/2026"
                parts = raw_date.split("-")
                date_display = f"{parts[2]}/{parts[1]}/{parts[0]}" if len(parts) == 3 else raw_date
            except Exception:
                date_display = raw_date

            # Trade type: LONG/BUY → BUY, SHORT/SELL → SELL
            type_label = "SELL" if direction.upper() in ("SHORT", "SELL") else "BUY"
            type_color = RED if type_label == "SELL" else GREEN

            pnl_color_g = GREEN if gross >= 0 else RED
            pnl_color_n = GREEN if net >= 0 else RED
            sign_g = "+" if gross >= 0 else ""
            sign_n = "+" if net >= 0 else ""

            # Source phase display
            src = t.get("source_phase", "") or "--"

            # TCAS display: "RA(3)" or "--"
            tcas_level = t.get("tcas_max_level", "")
            tcas_count = t.get("tcas_count", 0)
            tcas_text = f"{tcas_level}({tcas_count})" if tcas_level else "--"
            tcas_color = RED if tcas_level == "ALIM" else (AMBER if tcas_level == "RA" else (CYAN if tcas_level == "TA" else TEXT_MUTED))

            vals = [
                (date_display,                              85, TEXT_LABEL,  "normal"),
                (t.get("symbol", ""),                       80, TEXT_PRIMARY, "bold"),
                (type_label,                                40, type_color,  "bold"),
                (str(t.get("quantity", 0)),                 40, TEXT_LABEL,  "normal"),
                (f"{t.get('entry_price', 0):.1f}",         70, TEXT_LABEL,  "normal"),
                (f"{t.get('exit_price', 0):.1f}",          70, TEXT_LABEL,  "normal"),
                (f"{sign_g}{gross:,.1f}",                   75, pnl_color_g, "bold"),
                (f"{charges_total:,.1f}",                   65, AMBER,       "normal"),
                (f"{sign_n}{net:,.1f}",                     75, pnl_color_n, "bold"),
                (src,                                       65, CYAN,        "normal"),
                (tcas_text,                                 55, tcas_color,  "normal"),
                (dur_text,                                  40, TEXT_MUTED,  "normal"),
                (t.get("exit_reason", "")[:14],            100, TEXT_DIM,    "normal"),
            ]

            for text, w, color, weight in vals:
                ctk.CTkLabel(row, text=text,
                             font=(FONT_FAMILY, 10, weight),
                             text_color=color, width=w, anchor="w"
                             ).pack(side="left", padx=4)

    def _rebuild_table(self):
        """Destroy and re-render table rows for current page."""
        if self._table_scroll is None:
            return
        for child in self._table_scroll.winfo_children():
            child.destroy()
        self._render_rows(self._data.get("trades", []))

    # ------------------------------------------------------------------
    #  PAGINATION
    # ------------------------------------------------------------------

    def _build_pagination(self):
        """Prev / Page X of Y / Next controls."""
        pag = ctk.CTkFrame(self, fg_color=BG_PANEL, corner_radius=8,
                           border_width=1, border_color=BORDER, height=40)
        pag.pack(fill="x", padx=8, pady=(0, 4))
        pag.pack_propagate(False)

        inner = ctk.CTkFrame(pag, fg_color="transparent")
        inner.pack(expand=True)

        self._prev_btn = ctk.CTkButton(
            inner, text="< PREV", width=80, height=28,
            font=FONT_TINY_BOLD,
            fg_color=BG_HEADER, hover_color=BORDER,
            text_color=TEXT_LABEL,
            command=lambda: self._change_page(-1),
        )
        self._prev_btn.pack(side="left", padx=8)

        self._page_label = ctk.CTkLabel(
            inner, text=f"Page {self._current_page} of {self._total_pages}",
            font=FONT_SMALL_BOLD, text_color=TEXT_PRIMARY,
        )
        self._page_label.pack(side="left", padx=16)

        self._next_btn = ctk.CTkButton(
            inner, text="NEXT >", width=80, height=28,
            font=FONT_TINY_BOLD,
            fg_color=BG_HEADER, hover_color=BORDER,
            text_color=TEXT_LABEL,
            command=lambda: self._change_page(1),
        )
        self._next_btn.pack(side="left", padx=8)

        self._update_pagination_controls()

    def _update_pagination_controls(self):
        """Update page label and button enabled/disabled states."""
        if self._page_label:
            self._page_label.configure(
                text=f"Page {self._current_page} of {self._total_pages}")

        if self._prev_btn:
            if self._current_page <= 1:
                self._prev_btn.configure(state="disabled", text_color=TEXT_DIM)
            else:
                self._prev_btn.configure(state="normal", text_color=TEXT_LABEL)

        if self._next_btn:
            if self._current_page >= self._total_pages:
                self._next_btn.configure(state="disabled", text_color=TEXT_DIM)
            else:
                self._next_btn.configure(state="normal", text_color=TEXT_LABEL)

    def _change_page(self, delta):
        """Navigate to a different page."""
        new_page = self._current_page + delta
        if new_page < 1 or new_page > self._total_pages:
            return
        self._current_page = new_page
        self._load_data()
        self._rebuild_table()
        self._update_pagination_controls()
        self._refresh_status_bar()

    # ------------------------------------------------------------------
    #  STATUS BAR
    # ------------------------------------------------------------------

    def _build_status_bar(self, d):
        """Bottom status bar with page + P/L summary."""
        self._status_bar_frame = ctk.CTkFrame(
            self, fg_color=BG_PANEL, corner_radius=8,
            border_width=1, border_color=BORDER, height=36,
        )
        self._status_bar_frame.pack(fill="x", padx=8, pady=(0, 4))
        self._status_bar_frame.pack_propagate(False)
        self._render_status_items(d)

    def _render_status_items(self, d):
        """Render status bar items."""
        for child in self._status_bar_frame.winfo_children():
            child.destroy()

        inner = ctk.CTkFrame(self._status_bar_frame, fg_color="transparent")
        inner.pack(expand=True)

        total = d.get("total_trades", 0)
        page = d.get("page", 1)
        per_page = d.get("per_page", ROWS_PER_PAGE)
        total_pages = d.get("total_pages", 1)
        start_idx = (page - 1) * per_page + 1 if total > 0 else 0
        end_idx = min(page * per_page, total)

        net = d.get("aggregates", {}).get("total_net_pnl", 0)
        net_color = GREEN if net >= 0 else RED

        items = [
            (f"SHOWING {start_idx}-{end_idx} OF {total}", TEXT_MUTED),
            (f"PAGE {page}/{total_pages}", CYAN),
            (f"NET P/L: {self._fmt_pnl(net)}", net_color),
        ]

        for i, (text, color) in enumerate(items):
            ctk.CTkLabel(inner, text=text,
                         font=FONT_SMALL_BOLD,
                         text_color=color).pack(side="left", padx=8)
            if i < len(items) - 1:
                ctk.CTkLabel(inner, text="|", font=("", 10),
                             text_color=BORDER).pack(side="left", padx=2)

    def _refresh_status_bar(self):
        """Re-render status bar after page change."""
        if self._status_bar_frame:
            self._render_status_items(self._data)

    # ------------------------------------------------------------------
    #  HELPERS
    # ------------------------------------------------------------------

    @staticmethod
    def _fmt_pnl(value):
        """Format P/L with sign and Rs prefix."""
        try:
            v = float(value)
        except (TypeError, ValueError):
            return "Rs.0.00"
        sign = "+" if v >= 0 else ""
        return f"{sign}Rs.{v:,.2f}"
