"""
Algo_Beta GUI -- Control Panel View (v1.5)
==========================================
Layout: System log = dominant center | Capital + Thresholds = right panel
  Row 0: System Controls (compact, full width)
  Row 1: System Log (left, big) + Right Panel (capital + thresholds stacked)
  Row 2: Info Bar (full width, compact)

Theme: Softer dark with improved readability (lighter backgrounds, bigger fonts)
Phase switches are in the sidebar (main.py).
MIE always ON (not user-controlled).
"""

import customtkinter as ctk
import datetime
import subprocess
import threading
import re
import os
import sys
import time


import sys as _sys
import os as _os
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from theme import (  # noqa: E402
    BG_APP, BG_PANEL, BG_HEADER, BG_INPUT, BG_INFOBAR,
    BORDER, BORDER_DIM,
    TEXT_PRIMARY, TEXT_LABEL, TEXT_MUTED, TEXT_DIM, TEXT_ENTRY,
    ACCENT_CYAN, ACCENT_PRIMARY, GREEN, RED, AMBER,
    FONT_FAMILY, FONT_LOGO, FONT_TITLE, FONT_HEADING,
    FONT_BODY_BOLD, FONT_BODY, FONT_SMALL_BOLD, FONT_SMALL,
    FONT_TINY_BOLD, FONT_TINY, FONT_LOG, FONT_NAV, FONT_BUTTON,
)

RIGHT_PANEL_WIDTH = 300


# ---------------------------------------------------------------
#  LED INDICATOR (compact, inline)
# ---------------------------------------------------------------

class LEDIndicator(ctk.CTkFrame):
    """Compact LED dot + label for connection status."""

    def __init__(self, parent, label, connected=False):
        super().__init__(parent, fg_color="transparent")
        self._label = label
        self._connected = connected

        self._dot = ctk.CTkLabel(self, text="●", font=("", 16), width=18)
        self._dot.pack(side="left", padx=(0, 4))

        self._name_label = ctk.CTkLabel(
            self, text=label,
            font=FONT_SMALL_BOLD, anchor="w",
        )
        self._name_label.pack(side="left", padx=(0, 3))

        self._status_label = ctk.CTkLabel(
            self, text="",
            font=FONT_TINY, anchor="w",
        )
        self._status_label.pack(side="left")
        self.set_connected(connected)

    def set_connected(self, connected):
        self._connected = connected
        if connected:
            self._dot.configure(text_color="#22c55e")
            self._name_label.configure(text_color=TEXT_PRIMARY)
            self._status_label.configure(text="OK", text_color="#22c55e")
        else:
            self._dot.configure(text_color="#ef4444")
            self._name_label.configure(text_color=TEXT_MUTED)
            self._status_label.configure(text="--", text_color="#ef4444")


# ---------------------------------------------------------------
#  SYSTEM START/STOP BUTTON
# ---------------------------------------------------------------

class IndicatorButton(ctk.CTkFrame):
    """Toggle button styled like a physical switch."""

    def __init__(self, parent, text_on, text_off,
                 color_on="#22c55e", color_on_hover="#16a34a",
                 on_toggle=None, initial=False,
                 width=180, height=40, font_size=12):
        super().__init__(parent, fg_color="transparent")
        self._text_on = text_on
        self._text_off = text_off
        self._color_on = color_on
        self._color_on_hover = color_on_hover
        self._on_toggle = on_toggle
        self._is_on = initial

        self.btn = ctk.CTkButton(
            self, text=text_on if initial else text_off,
            width=width, height=height,
            font=(FONT_FAMILY, font_size, "bold"),
            corner_radius=8, border_width=2,
            command=self._toggle,
        )
        self.btn.pack(padx=2, pady=2)
        self._apply_visuals()

    def _toggle(self):
        self._is_on = not self._is_on
        self._apply_visuals()
        if self._on_toggle:
            self._on_toggle(self._is_on)

    def set_state(self, is_on):
        self._is_on = is_on
        self._apply_visuals()

    def get_state(self):
        return self._is_on

    def _apply_visuals(self):
        if self._is_on:
            self.btn.configure(
                text=self._text_on, text_color="#ffffff",
                fg_color=self._color_on, hover_color=self._color_on_hover,
                border_color=self._color_on,
            )
        else:
            self.btn.configure(
                text=self._text_off, text_color="#FFFFFF",
                fg_color="#1B4F72", hover_color="#154360",
                border_color="#1A3E5C",
            )


# ---------------------------------------------------------------
#  ORCHESTRATOR LOG VIEWER
# ---------------------------------------------------------------

class OrchestratorLog(ctk.CTkFrame):
    """Live stdout/stderr viewer for main_orchestrator.py."""

    def __init__(self, parent, orchestrator_path=None, on_log_line=None, on_exit=None):
        super().__init__(parent, fg_color=BG_PANEL, corner_radius=8,
                         border_width=1, border_color=BORDER)

        self._process = None
        self._thread = None
        self._running = False
        self._log_file = None          # set by start_process() for log tailing
        self._on_log_line = on_log_line
        self._on_exit = on_exit       # callback(exit_code) when process dies

        # Auto-detect orchestrator path
        if orchestrator_path is None:
            gui_dir = os.path.dirname(os.path.abspath(__file__))  # views/
            package_dir = os.path.dirname(gui_dir)               # algo_beta_gui/
            project_dir = os.path.dirname(package_dir)           # Algo_Beta/
            orchestrator_path = os.path.join(project_dir, "main_orchestrator.py")
        self._orchestrator_path = orchestrator_path

        # Title bar
        title_bar = ctk.CTkFrame(self, fg_color=BG_HEADER, corner_radius=0, height=32)
        title_bar.pack(fill="x")
        title_bar.pack_propagate(False)

        ctk.CTkLabel(
            title_bar, text="SYSTEM LOG -- main_orchestrator.py",
            font=FONT_TINY_BOLD, text_color=TEXT_MUTED, anchor="w",
        ).pack(side="left", padx=12, pady=6)

        self._status_label = ctk.CTkLabel(
            title_bar, text="STOPPED",
            font=FONT_TINY_BOLD, text_color="#ef4444",
        )
        self._status_label.pack(side="right", padx=12, pady=6)

        # Log textbox -- bigger font for readability
        self._log = ctk.CTkTextbox(
            self, font=FONT_BODY,
            fg_color=BG_INPUT, text_color=TEXT_LABEL,
            border_color=BORDER_DIM, border_width=1,
            state="disabled",
        )
        self._log.pack(fill="both", expand=True, padx=6, pady=(4, 2))

        # Configure text tags (brighter colors for readability)
        self._log.configure(state="normal")
        self._log._textbox.tag_configure("error", foreground="#f87171")
        self._log._textbox.tag_configure("warning", foreground="#fbbf24")
        self._log._textbox.tag_configure("success", foreground="#4ade80")
        self._log._textbox.tag_configure("info", foreground="#9898a4")
        self._log._textbox.tag_configure("phase", foreground="#22d3ee")
        self._log.configure(state="disabled")

        # Button row
        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.pack(fill="x", padx=6, pady=(0, 4))

        path_display = self._orchestrator_path if os.path.exists(self._orchestrator_path) else "not found"
        ctk.CTkLabel(
            btn_row, text=f"Path: {path_display}",
            font=FONT_TINY, text_color=TEXT_DIM,
        ).pack(side="left")

        ctk.CTkButton(
            btn_row, text="Clear", width=55, height=24,
            font=FONT_TINY,
            fg_color=BG_HEADER, hover_color=BORDER, text_color=TEXT_MUTED,
            command=self._clear_log,
        ).pack(side="right", padx=(4, 0))

        ctk.CTkButton(
            btn_row, text="Bottom", width=65, height=24,
            font=FONT_TINY,
            fg_color=BG_HEADER, hover_color=BORDER, text_color=TEXT_MUTED,
            command=lambda: self._log.see("end"),
        ).pack(side="right")

    def start_process(self):
        if self._running:
            return
        if not os.path.exists(self._orchestrator_path):
            self._append_line(f"[ERROR] Orchestrator not found: {self._orchestrator_path}", "error")
            return

        self._running = True
        self._status_label.configure(text="RUNNING", text_color="#22c55e")
        self._append_line(f"[{self._timestamp()}] Starting main_orchestrator.py...", "success")

        try:
            python_exe = sys.executable
            orch_dir = os.path.dirname(self._orchestrator_path)
            self._process = subprocess.Popen(
                [python_exe, "-u", self._orchestrator_path],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                cwd=orch_dir,
                env={**os.environ, "PYTHONUNBUFFERED": "1"},
            )
            # The orchestrator writes to logs/orchestrator.log reliably.
            # Tail that file instead of fighting Windows pipe buffering.
            self._log_file = os.path.join(orch_dir, "logs", "orchestrator.log")
            self._thread = threading.Thread(target=self._tail_log_file, daemon=True)
            self._thread.start()
        except Exception as e:
            self._append_line(f"[ERROR] Failed to start: {e}", "error")
            self._running = False
            self._status_label.configure(text="ERROR", text_color="#ef4444")

    def stop_process(self):
        if self._process and self._running:
            self._running = False
            try:
                self._process.terminate()
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._process.kill()
            except Exception:
                pass
            self._status_label.configure(text="STOPPED", text_color="#ef4444")
            self._append_line(f"[{self._timestamp()}] System stopped.", "warning")

    def _tail_log_file(self):
        """Tail the orchestrator log file for new lines.

        The orchestrator writes reliably to logs/orchestrator.log but
        Windows pipe buffering makes subprocess.PIPE unusable.  Instead,
        we seek to the end of the file on start and poll for new content
        every 0.5 s until the subprocess exits.
        """
        try:
            # Wait briefly for the log file to appear (orchestrator may
            # need a moment to create it on first run).
            wait_limit = 20          # 10 s max wait
            while self._running and wait_limit > 0:
                if os.path.exists(self._log_file):
                    break
                time.sleep(0.5)
                wait_limit -= 1

            if not os.path.exists(self._log_file):
                self.after(0, self._append_line,
                           f"[WARN] Log file not found: {self._log_file}", "warning")
                # Still wait for process exit
                if self._process:
                    self._process.wait()
                self.after(0, self._on_process_ended)
                return

            with open(self._log_file, "r", encoding="utf-8", errors="replace") as fh:
                # Seek to end — we only want NEW lines
                fh.seek(0, 2)

                while self._running:
                    line = fh.readline()
                    if line:
                        stripped = line.rstrip("\n\r")
                        if stripped:
                            tag = self._classify_line(stripped)
                            self.after(0, self._append_line, stripped, tag)
                            if self._on_log_line:
                                self.after(0, self._on_log_line, stripped)
                        continue          # keep draining without sleeping

                    # No new data — check if process is still alive
                    if self._process and self._process.poll() is not None:
                        # Drain any remaining lines after process exit
                        remainder = fh.read()
                        for rem_line in remainder.splitlines():
                            rem_line = rem_line.strip()
                            if rem_line:
                                tag = self._classify_line(rem_line)
                                self.after(0, self._append_line, rem_line, tag)
                        break

                    time.sleep(0.5)

            self.after(0, self._on_process_ended)
        except Exception as e:
            self.after(0, self._append_line, f"[ERROR] Log tailer: {e}", "error")
            # Still signal process ended so button resets
            if self._process and self._process.poll() is not None:
                self.after(0, self._on_process_ended)

    def _read_output(self):
        """Legacy pipe reader — kept as fallback but not currently used."""
        try:
            for line in self._process.stdout:
                if not self._running:
                    break
                stripped = line.rstrip("\n\r")
                if stripped:
                    tag = self._classify_line(stripped)
                    self.after(0, self._append_line, stripped, tag)
                    if self._on_log_line:
                        self.after(0, self._on_log_line, stripped)
            self.after(0, self._on_process_ended)
        except Exception as e:
            self.after(0, self._append_line, f"[ERROR] Reader: {e}", "error")

    def _on_process_ended(self):
        exit_code = self._process.returncode if self._process else None
        self._running = False
        self._status_label.configure(text="STOPPED", text_color="#ef4444")
        self._append_line(f"[{self._timestamp()}] Process exited (code: {exit_code})", "warning")
        # Notify parent so the system toggle can reset
        if self._on_exit:
            try:
                self._on_exit(exit_code)
            except Exception:
                pass

    def _classify_line(self, line):
        lower = line.lower()
        if "error" in lower or "exception" in lower or "traceback" in lower:
            return "error"
        if "warning" in lower:
            return "warning"
        if "success" in lower or "connected" in lower or "started" in lower:
            return "success"
        if "phase" in lower or any(f"ph{i}" in lower for i in range(1, 9)):
            return "phase"
        return "info"

    def _append_line(self, text, tag="info"):
        self._log.configure(state="normal")
        self._log._textbox.insert("end", text + "\n", tag)
        self._log.see("end")
        self._log.configure(state="disabled")

    def _clear_log(self):
        self._log.configure(state="normal")
        self._log.delete("1.0", "end")
        self._log.configure(state="disabled")

    def _timestamp(self):
        return datetime.datetime.now().strftime("%H:%M:%S")

    @property
    def is_running(self):
        return self._running

    def destroy(self):
        self.stop_process()
        super().destroy()


# ---------------------------------------------------------------
#  CONTROL PANEL VIEW (v1.5)
# ---------------------------------------------------------------

class ControlPanelView(ctk.CTkFrame):
    """
    Dashboard layout:
        Row 0: System Controls (compact, full width)
        Row 1: System Log (left, dominant) + Right Panel (capital + thresholds)
        Row 2: Info Bar (compact, full width)
    """

    def __init__(self, parent, config, bridge, app=None, data_bridge=None):
        super().__init__(parent, fg_color="transparent")
        self.config = config
        self.bridge = bridge
        self.app = app
        self.data_bridge = data_bridge

        self._capital_entries = {}
        self._threshold_entries = {}
        self._cap_summary_labels = {}
        self._info_labels = {}
        self._today_pnl = 0
        self._trades_today = 0
        self._start_time = None

        self._build_ui()
        self._load_values()

        # Ensure MIE is always enabled
        self.config.update("ENABLE_MIE", True)

        # Register for live data updates
        if self.data_bridge:
            self.data_bridge.register_callback(self, self._on_live_data)

    def _build_ui(self):
        # Grid: 3 rows
        self.rowconfigure(0, weight=0)   # System controls (fixed)
        self.rowconfigure(1, weight=1)   # Main content (log + right panel)
        self.rowconfigure(2, weight=0)   # Info bar (fixed)
        self.columnconfigure(0, weight=1)

        # Row 0: System Controls
        self._build_system_controls()

        # Row 1: Log (left) + Right panel (capital + thresholds)
        self._build_main_content()

        # Row 2: Info Bar
        self._build_info_bar()

        # Start info bar refresh
        self.after(1000, self._update_info_bar)

    # === SYSTEM CONTROLS (compact top bar) =========================

    def _build_system_controls(self):
        frame = ctk.CTkFrame(self, fg_color=BG_PANEL, corner_radius=8,
                             border_width=1, border_color=BORDER)
        frame.grid(row=0, column=0, sticky="ew", padx=4, pady=(2, 2))

        inner = ctk.CTkFrame(frame, fg_color="transparent")
        inner.pack(fill="x", padx=10, pady=6)

        # START/STOP button
        self._system_btn = IndicatorButton(
            inner,
            text_on="SYSTEM ONLINE",
            text_off="START SYSTEM",
            color_on="#22c55e", color_on_hover="#16a34a",
            on_toggle=self._on_system_toggle,
            initial=self.config.get("SYSTEM_RUNNING", False),
            width=180, height=38, font_size=12,
        )
        self._system_btn.pack(side="left", padx=(0, 14))

        # LED indicators (compact, inline)
        self._kite_led = LEDIndicator(
            inner, "Kite",
            connected=self.config.get("KITE_CONNECTED", False),
        )
        self._kite_led.pack(side="left", padx=(0, 16))

        self._telegram_led = LEDIndicator(
            inner, "Telegram",
            connected=self.config.get("TELEGRAM_CONNECTED", False),
        )
        self._telegram_led.pack(side="left", padx=(0, 16))

        # Config source + version info (right side)
        info_frame = ctk.CTkFrame(inner, fg_color="transparent")
        info_frame.pack(side="right")

        is_live = self.config.is_live() if hasattr(self.config, "is_live") else False
        src_text = "LIVE config.py" if is_live else "MOCK defaults"
        src_color = "#10b981" if is_live else "#f59e0b"
        ctk.CTkLabel(info_frame, text=src_text,
                     font=FONT_TINY_BOLD, text_color=src_color,
                     ).pack(side="right", padx=(8, 0))

        ver = self.config.get("SYSTEM_VERSION", "")
        mode = self.config.get("PRODUCT_MODE", "")
        ctk.CTkLabel(info_frame, text=f"{ver} | {mode}",
                     font=FONT_TINY, text_color=TEXT_MUTED,
                     ).pack(side="right", padx=(0, 8))

    # === MAIN CONTENT (log left + right panel) =====================

    def _build_main_content(self):
        content = ctk.CTkFrame(self, fg_color="transparent")
        content.grid(row=1, column=0, sticky="nsew", padx=0, pady=0)

        content.columnconfigure(0, weight=1)          # log expands
        content.columnconfigure(1, weight=0, minsize=RIGHT_PANEL_WIDTH)
        content.rowconfigure(0, weight=1)

        # Left: System Log (dominant)
        self._orch_log = OrchestratorLog(content, on_log_line=self._on_orch_log_line,
                                          on_exit=self._on_process_exit)
        self._orch_log.grid(row=0, column=0, sticky="nsew", padx=(4, 2), pady=2)

        # Right: Capital + Thresholds stacked
        right_panel = ctk.CTkFrame(content, fg_color="transparent", width=RIGHT_PANEL_WIDTH)
        right_panel.grid(row=0, column=1, sticky="nsew", padx=(2, 4), pady=2)
        right_panel.grid_propagate(False)

        self._build_capital(right_panel)
        self._build_thresholds(right_panel)

    # === CAPITAL MANAGEMENT ========================================

    def _build_capital(self, parent):
        frame = ctk.CTkFrame(parent, fg_color=BG_PANEL, corner_radius=8,
                             border_width=1, border_color=BORDER)
        frame.pack(fill="x", pady=(0, 2))

        # Title
        title_bar = ctk.CTkFrame(frame, fg_color=BG_HEADER, corner_radius=0, height=28)
        title_bar.pack(fill="x")
        title_bar.pack_propagate(False)
        ctk.CTkLabel(title_bar, text="CAPITAL MANAGEMENT",
                     font=FONT_TINY_BOLD, text_color=TEXT_MUTED,
                     anchor="w").pack(side="left", padx=12, pady=4)

        fields = [
            ("TOTAL_CAPITAL",          "Total Capital"),
            ("BASE_CAPITAL_PER_TRADE", "Per Trade"),
            ("MAX_TOTAL_POSITIONS",    "Max Positions"),
            ("MIN_CAPITAL_BUFFER",     "Min Buffer"),
        ]

        for config_key, label in fields:
            row_frame = ctk.CTkFrame(frame, fg_color="transparent")
            row_frame.pack(fill="x", padx=10, pady=(3, 0))

            ctk.CTkLabel(row_frame, text=label,
                         font=FONT_SMALL, text_color=TEXT_LABEL,
                         anchor="w", width=130).pack(side="left")

            entry = ctk.CTkEntry(
                row_frame, width=90, height=28,
                font=FONT_BODY,
                fg_color=BG_INPUT, border_color=BORDER,
                text_color=TEXT_ENTRY, justify="right",
            )
            entry.pack(side="right")
            self._capital_entries[config_key] = entry

        # Summary (deployed / available)
        summary = ctk.CTkFrame(frame, fg_color=BG_HEADER, corner_radius=4)
        summary.pack(fill="x", padx=10, pady=(6, 2))

        cap = self.config.get_capital_summary()
        for label, value, color in [
            ("Deployed",  f"Rs.{cap['deployed']:,.0f}",   "#f59e0b"),
            ("Available", f"Rs.{cap['available']:,.0f}",  "#10b981"),
        ]:
            r = ctk.CTkFrame(summary, fg_color="transparent")
            r.pack(fill="x", padx=10, pady=2)
            ctk.CTkLabel(r, text=label, font=FONT_TINY,
                         text_color=TEXT_MUTED, anchor="w").pack(side="left")
            lbl = ctk.CTkLabel(r, text=value, font=FONT_SMALL_BOLD,
                               text_color=color, anchor="e")
            lbl.pack(side="right")
            self._cap_summary_labels[label] = lbl

        ctk.CTkButton(
            frame, text="APPLY", width=80, height=28,
            font=FONT_TINY_BOLD,
            fg_color="#1e3a5f", hover_color="#1e40af", text_color="#60a5fa",
            command=self._on_apply_capital,
        ).pack(padx=10, pady=(4, 8), anchor="e")

    # === THRESHOLD CONTROLS ========================================

    def _build_thresholds(self, parent):
        frame = ctk.CTkFrame(parent, fg_color=BG_PANEL, corner_radius=8,
                             border_width=1, border_color=BORDER)
        frame.pack(fill="both", expand=True, pady=(0, 0))

        # Title
        title_bar = ctk.CTkFrame(frame, fg_color=BG_HEADER, corner_radius=0, height=28)
        title_bar.pack(fill="x")
        title_bar.pack_propagate(False)
        ctk.CTkLabel(title_bar, text="THRESHOLD CONTROLS",
                     font=FONT_TINY_BOLD, text_color=TEXT_MUTED,
                     anchor="w").pack(side="left", padx=12, pady=4)

        # -- Scoring section --
        ctk.CTkLabel(frame, text="Scoring", font=FONT_TINY_BOLD,
                     text_color="#06b6d4", anchor="w").pack(padx=12, pady=(6, 0), anchor="w")
        for key, label in [
            ("PH2_SCORE_ENTRY_MIN",     "Entry Min"),
            ("PH2_SCORE_FULL_POSITION", "Full Position"),
            ("PH2_SCORE_STRONG_BUY",    "Strong Buy"),
        ]:
            self._add_threshold_field(frame, key, label)

        # -- TCAS section --
        ctk.CTkLabel(frame, text="TCAS (ATR)", font=FONT_TINY_BOLD,
                     text_color="#f59e0b", anchor="w").pack(padx=12, pady=(6, 0), anchor="w")
        for key, label in [
            ("TCAS_TA_THRESHOLD_ATR",   "TA Advisory"),
            ("TCAS_RA_THRESHOLD_ATR",   "RA Advisory"),
            ("TCAS_ALIM_THRESHOLD_ATR", "ALIM Exit"),
        ]:
            self._add_threshold_field(frame, key, label)

        # -- Targets section --
        ctk.CTkLabel(frame, text="Targets", font=FONT_TINY_BOLD,
                     text_color="#22c55e", anchor="w").pack(padx=12, pady=(6, 0), anchor="w")
        for key, label in [
            ("PROFIT_TARGET_PCT",     "Profit %"),
            ("STOP_LOSS_PCT",         "Stop Loss %"),
            ("SCAN_INTERVAL_MINUTES", "Scan (min)"),
        ]:
            self._add_threshold_field(frame, key, label)

        ctk.CTkButton(
            frame, text="APPLY THRESHOLDS", width=150, height=28,
            font=FONT_TINY_BOLD,
            fg_color="#1e3a5f", hover_color="#1e40af", text_color="#60a5fa",
            command=self._on_apply_thresholds,
        ).pack(padx=10, pady=(6, 8), anchor="e")

    def _add_threshold_field(self, parent, config_key, label):
        row_frame = ctk.CTkFrame(parent, fg_color="transparent")
        row_frame.pack(fill="x", padx=10, pady=(2, 0))

        ctk.CTkLabel(row_frame, text=label,
                     font=FONT_SMALL, text_color=TEXT_LABEL,
                     anchor="w", width=120).pack(side="left")

        entry = ctk.CTkEntry(
            row_frame, width=80, height=26,
            font=FONT_BODY,
            fg_color=BG_INPUT, border_color=BORDER,
            text_color=TEXT_ENTRY, justify="right",
        )
        entry.pack(side="right")
        self._threshold_entries[config_key] = entry

    # === INFO BAR ==================================================

    def _build_info_bar(self):
        bar = ctk.CTkFrame(self, fg_color=BG_INFOBAR, height=30,
                           corner_radius=0, border_width=1, border_color=BORDER_DIM)
        bar.grid(row=2, column=0, sticky="ew", padx=4, pady=(0, 2))
        bar.pack_propagate(False)

        items = [
            ("market",  "Market: --"),
            ("phases",  "Phases: 0/5"),
            ("capital", "Capital: Rs.0 / Rs.0"),
            ("uptime",  "Uptime: 0m"),
            ("pnl",     "P&L: Rs.0"),
            ("trades",  "Trades: 0"),
        ]

        for i, (key, default_text) in enumerate(items):
            lbl = ctk.CTkLabel(
                bar, text=default_text,
                font=FONT_TINY, text_color=TEXT_MUTED,
            )
            lbl.pack(side="left", padx=(10, 4))
            self._info_labels[key] = lbl

            if i < len(items) - 1:
                ctk.CTkLabel(bar, text="|", font=("", 9),
                             text_color=BORDER_DIM).pack(side="left")

    def _update_info_bar(self):
        if not hasattr(self, '_info_labels') or not self._info_labels:
            return

        now = datetime.datetime.now()

        # Market status
        try:
            mkt = self.config.get_market_hours()
            market_open = now.replace(hour=mkt["open_hour"], minute=mkt["open_minute"], second=0)
            market_close = now.replace(hour=mkt["close_hour"], minute=mkt["close_minute"], second=0)
            if market_open <= now <= market_close and now.weekday() < 5:
                remaining = market_close - now
                mins = int(remaining.total_seconds() // 60)
                self._info_labels["market"].configure(
                    text=f"Market: Open ({mins}m)", text_color="#22c55e")
            else:
                if now < market_open and now.weekday() < 5:
                    until = market_open - now
                    mins = int(until.total_seconds() // 60)
                    self._info_labels["market"].configure(
                        text=f"Market: Opens {mins}m", text_color="#f59e0b")
                else:
                    self._info_labels["market"].configure(
                        text="Market: Closed", text_color="#ef4444")
        except Exception:
            pass

        # Active phases (3-state aware: LIVE / PAPER / OFF)
        _phase_keys = ["ENABLE_PH5", "ENABLE_PH5A", "ENABLE_PH6", "ENABLE_PH7", "ENABLE_PH8"]
        try:
            _db_st = self.data_bridge.get_phase_states() if self.data_bridge else {}
        except Exception:
            _db_st = {}

        if _db_st:
            _live  = sum(1 for k in _phase_keys if _db_st.get(k) == 'LIVE')
            _paper = sum(1 for k in _phase_keys if _db_st.get(k) == 'PAPER')
            _parts = []
            if _live:
                _parts.append(f"{_live} LIVE")
            if _paper:
                _parts.append(f"{_paper} PAPER")
            _off = 5 - _live - _paper
            _parts.append(f"{_off} OFF")
            self._info_labels["phases"].configure(text="Phases: " + " / ".join(_parts))
        else:
            active = sum(1 for ph in _phase_keys if self.config.get(ph, False))
            self._info_labels["phases"].configure(text=f"Phases: {active}/5")

        # Capital
        try:
            cap = self.config.get_capital_summary()
            self._info_labels["capital"].configure(
                text=f"Capital: Rs.{cap['deployed']:,.0f} / Rs.{cap['total']:,.0f}")
        except Exception:
            pass

        # Uptime
        if self._start_time:
            elapsed = (now - self._start_time).total_seconds()
            mins = int(elapsed // 60)
            hrs = mins // 60
            if hrs > 0:
                self._info_labels["uptime"].configure(text=f"Up: {hrs}h{mins % 60}m")
            else:
                self._info_labels["uptime"].configure(text=f"Up: {mins}m")

        # P&L and trades
        pnl_color = "#22c55e" if self._today_pnl >= 0 else "#ef4444"
        self._info_labels["pnl"].configure(
            text=f"P&L: Rs.{self._today_pnl:,.0f}", text_color=pnl_color)
        self._info_labels["trades"].configure(text=f"Trades: {self._trades_today}")

        # Schedule next update
        self.after(1000, self._update_info_bar)

    # === DATA LOADING ==============================================

    def _load_values(self):
        for key, entry in self._capital_entries.items():
            val = self.config.get(key, "")
            entry.delete(0, "end")
            entry.insert(0, str(val))

        for key, entry in self._threshold_entries.items():
            val = self.config.get(key, "")
            entry.delete(0, "end")
            entry.insert(0, str(val))

    # === EVENT HANDLERS ============================================

    def _on_system_toggle(self, is_on):
        self.config.update("SYSTEM_RUNNING", is_on)
        if not hasattr(self, '_orch_log'):
            return  # Guard: toggle can fire before log widget exists
        if is_on:
            self._start_time = datetime.datetime.now()
            self.bridge.system_start()
            self._orch_log.start_process()
        else:
            self._start_time = None
            self.bridge.system_stop()
            self._orch_log.stop_process()

    def _on_process_exit(self, exit_code):
        """Called by OrchestratorLog when the orchestrator process dies.
        Reset the system toggle button so the UI stays in sync."""
        self.config.update("SYSTEM_RUNNING", False)
        self._start_time = None
        if hasattr(self, '_system_btn'):
            self._system_btn.set_state(False)

    def on_phase_changed(self, config_key, state):
        """Called by main.py when a sidebar phase switch changes (state: OFF/PAPER/LIVE)."""
        self._update_info_bar()

    def _on_orch_log_line(self, line):
        """Parse orchestrator log lines for status updates."""
        lower = line.lower()

        # Connection status -- detect "S1: Kite: <name>, Telegram: OK"
        if "s1:" in lower and "kite:" in lower:
            self._kite_led.set_connected(True)
            self.config.update("KITE_CONNECTED", True)
            if self.app:
                self.app.update_sidebar_status("KITE_CONNECTED", True)
            if "telegram:" in lower:
                self._telegram_led.set_connected(True)
                self.config.update("TELEGRAM_CONNECTED", True)
                if self.app:
                    self.app.update_sidebar_status("TELEGRAM_CONNECTED", True)

        # Connection errors
        if "kite" in lower and ("error" in lower or "failed" in lower or "exception" in lower):
            self._kite_led.set_connected(False)
            self.config.update("KITE_CONNECTED", False)
            if self.app:
                self.app.update_sidebar_status("KITE_CONNECTED", False)

        if "telegram" in lower and ("error" in lower or "failed" in lower):
            self._telegram_led.set_connected(False)
            self.config.update("TELEGRAM_CONNECTED", False)
            if self.app:
                self.app.update_sidebar_status("TELEGRAM_CONNECTED", False)

        # Track trades
        if "order executed" in lower or "trade completed" in lower or "buy order" in lower:
            self._trades_today += 1

        # Track P&L
        pnl_match = re.search(r'p[&]?l[:\s]+[Rs.]*?([-+]?[\d,]+\.?\d*)', lower)
        if pnl_match:
            try:
                self._today_pnl = float(pnl_match.group(1).replace(',', ''))
            except ValueError:
                pass

    def _on_apply_capital(self):
        for key, entry in self._capital_entries.items():
            raw = entry.get().strip()
            if raw:
                try:
                    val = float(raw) if "." in raw else int(raw)
                except ValueError:
                    val = raw
                self.config.update(key, val)
                self.bridge.set_capital(key.lower(), val)
        self._refresh_capital_summary()

    def _on_apply_thresholds(self):
        for key, entry in self._threshold_entries.items():
            raw = entry.get().strip()
            if raw:
                try:
                    val = float(raw)
                except ValueError:
                    continue
                self.config.update(key, val)
                self.bridge.set_config(key.lower(), val)

    def _refresh_capital_summary(self):
        cap = self.config.get_capital_summary()
        updates = {
            "Deployed":  f"Rs.{cap['deployed']:,.0f}",
            "Available": f"Rs.{cap['available']:,.0f}",
        }
        for label, value in updates.items():
            if label in self._cap_summary_labels:
                self._cap_summary_labels[label].configure(text=value)

    # ==================================================================
    #  LIVE DATA UPDATES
    # ==================================================================

    def _on_live_data(self, data):
        """Callback from DataBridge — refresh control panel with live data."""
        if not data or not data.db_available:
            return

        try:
            # Update capital summary labels
            deployed = data.deployed_capital
            available = data.free_capital or data.available_cash
            if deployed > 0 or available > 0:
                if "Deployed" in self._cap_summary_labels:
                    self._cap_summary_labels["Deployed"].configure(
                        text=f"Rs.{deployed:,.0f}")
                if "Available" in self._cap_summary_labels:
                    self._cap_summary_labels["Available"].configure(
                        text=f"Rs.{available:,.0f}")

            # Update LED indicators
            if hasattr(self, '_kite_led'):
                self._kite_led.set_connected(data.broker_connected)

            # Update P&L and trades count for info bar
            self._today_pnl = data.total_pnl_today
            self._trades_today = data.trades_count

            # Update info bar capital display
            total_cap = data.starting_capital or (deployed + available)
            if total_cap > 0 and "capital" in self._info_labels:
                self._info_labels["capital"].configure(
                    text=f"Capital: Rs.{deployed:,.0f} / Rs.{total_cap:,.0f}")

        except Exception:
            pass  # Silently ignore refresh errors

    def destroy(self):
        if hasattr(self, '_orch_log'):
            self._orch_log.stop_process()
        super().destroy()
