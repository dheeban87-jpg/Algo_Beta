"""
Algo_Beta Control Center v2.0
==============================
Main entry point -- sidebar with phase toggles + info buttons, tab routing.
Tabs: Control Panel | Dashboard | Settings
Theme: Claude-inspired warm light theme with CMD-prompt sized fonts.
"""

import sys
import os
import customtkinter as ctk

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from theme import (
    BG_APP, BG_SIDEBAR, BG_NAV_ACTIVE, BORDER, BORDER_DIM,
    TEXT_PRIMARY, TEXT_LABEL, TEXT_MUTED, TEXT_DIM, ACCENT_CYAN,
    ACCENT_PRIMARY, GREEN, RED, AMBER,
    SIDEBAR_BTN_BG, SIDEBAR_BTN_HOVER, SIDEBAR_BTN_TEXT,
    PHASE_BTN_BG, PHASE_BTN_HOVER, PHASE_BTN_BORDER, PHASE_BTN_TEXT,
    FONT_LOGO, FONT_TITLE, FONT_BODY_BOLD, FONT_BODY, FONT_SMALL_BOLD,
    FONT_NAV, FONT_BUTTON, FONT_VERSION, FONT_TINY,
    CTK_APPEARANCE, CTK_THEME,
)
from config_reader import ConfigReader
from telegram_bridge import TelegramBridge
from data_bridge import DataBridge
from views.control_panel import ControlPanelView
from views.dashboard import DashboardView
from views.settings import SettingsView


APP_TITLE = "ALGO_BETA -- Control Center v2.0"
APP_SIZE = "1440x860"
SIDEBAR_WIDTH = 260

# Mapping from config key to phase_id for detail views
CONFIG_TO_PHASE = {
    "ENABLE_PH5":  "ph5",
    "ENABLE_PH5A": "ph5a",
    "ENABLE_PH6":  "ph6",
    "ENABLE_PH7":  "ph7",
    "ENABLE_PH8":  "ph8",
}


class AlgoBetaApp(ctk.CTk):

    def __init__(self):
        super().__init__()

        self.title(APP_TITLE)
        self.geometry(APP_SIZE)
        self.minsize(1100, 650)

        ctk.set_appearance_mode(CTK_APPEARANCE)
        ctk.set_default_color_theme(CTK_THEME)
        self.configure(fg_color=BG_APP)

        self.config_data = ConfigReader()
        self.bridge = TelegramBridge()

        # Live data bridge (read-only SQLite poller)
        _gui_dir = os.path.dirname(os.path.abspath(__file__))
        _data_dir = os.path.join(os.path.dirname(_gui_dir), "data")
        self.data_bridge = DataBridge(
            algo_db_path=os.path.join(_data_dir, "algo_beta.db"),
            mc_db_path=os.path.join(_data_dir, "mission_control.db"),
        )
        self.data_bridge.start()

        # View management
        self._views = {}
        self._active_tab = None
        self._nav_items = {}
        self._phase_buttons = {}

        self._build_ui()
        self._switch_view("control")

        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _on_close(self):
        if hasattr(self, 'data_bridge'):
            self.data_bridge.stop()
        for view in self._views.values():
            try:
                view.destroy()
            except Exception:
                pass
        self.destroy()

    def _build_ui(self):
        # -- Left Sidebar --
        self._build_sidebar()

        # -- Main Area --
        self.main_area = ctk.CTkFrame(self, fg_color=BG_APP, corner_radius=0)
        self.main_area.pack(side="right", fill="both", expand=True)

    # ==================================================================
    #  SIDEBAR
    # ==================================================================

    def _build_sidebar(self):
        self.sidebar = ctk.CTkFrame(
            self, width=SIDEBAR_WIDTH, fg_color=BG_SIDEBAR,
            border_width=1, border_color=BORDER_DIM, corner_radius=0,
        )
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)

        # -- Logo --
        title_frame = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        title_frame.pack(fill="x", padx=16, pady=(14, 4))

        dot_frame = ctk.CTkFrame(title_frame, fg_color="transparent")
        dot_frame.pack(anchor="w")
        ctk.CTkLabel(dot_frame, text="●", font=FONT_BODY,
                     text_color=RED, width=16).pack(side="left", padx=(0, 6))
        ctk.CTkLabel(dot_frame, text="ALGO_BETA",
                     font=FONT_LOGO, text_color=TEXT_PRIMARY
                     ).pack(side="left")

        ctk.CTkLabel(title_frame,
                     text=f"{self.config_data.get('SYSTEM_VERSION')} . Control Center",
                     font=FONT_VERSION, text_color=TEXT_MUTED,
                     ).pack(anchor="w", pady=(2, 0))

        ctk.CTkFrame(self.sidebar, fg_color=BORDER_DIM, height=1
                     ).pack(fill="x", padx=12, pady=(6, 4))

        # -- Nav: CONTROL PANEL --
        self._add_nav_item_in(self.sidebar, "control", "CONTROL PANEL")

        # -- TRADE HISTORY button (under Control Panel) --
        th_top_row = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        th_top_row.pack(fill="x", padx=12, pady=(2, 4))
        ctk.CTkButton(
            th_top_row, text="TRADE HISTORY", height=36,
            font=FONT_BUTTON,
            corner_radius=6, border_width=1,
            fg_color=SIDEBAR_BTN_BG, hover_color=SIDEBAR_BTN_HOVER,
            border_color=SIDEBAR_BTN_BG, text_color=SIDEBAR_BTN_TEXT,
            command=self._open_trades_history,
        ).pack(fill="x")

        # -- Phase Status Viewers (PH1-PH4: always-on, view-only) --
        status_phases = [
            ("ph1", "PH1 . SELECTION"),
            ("ph2", "PH2 . MONITOR"),
            ("ph3", "PH3 . EXECUTION"),
            ("ph4", "PH4 . ENTRY"),
        ]
        for phase_id, label in status_phases:
            row = ctk.CTkFrame(self.sidebar, fg_color="transparent")
            row.pack(fill="x", padx=12, pady=2)

            status_btn = ctk.CTkButton(
                row, text=label, height=38,
                font=FONT_BODY_BOLD,
                corner_radius=6, border_width=2,
                fg_color=PHASE_BTN_BG, hover_color=PHASE_BTN_HOVER,
                border_color=PHASE_BTN_BORDER, text_color=PHASE_BTN_TEXT,
                command=lambda pid=phase_id: self._open_phase_detail(pid),
            )
            status_btn.pack(side="left", fill="x", expand=True)

            info_btn = ctk.CTkButton(
                row, text=">", width=30, height=38,
                font=FONT_BODY_BOLD,
                corner_radius=6, border_width=2,
                fg_color="transparent", hover_color=BORDER,
                border_color=BORDER_DIM, text_color=TEXT_MUTED,
                command=lambda pid=phase_id: self._open_phase_detail(pid),
            )
            info_btn.pack(side="right", padx=(2, 0))

        ctk.CTkFrame(self.sidebar, fg_color=BORDER_DIM, height=1
                     ).pack(fill="x", padx=12, pady=(4, 4))

        # -- Phase Toggle Buttons with Info Buttons --
        phases = [
            ("ENABLE_PH5",  "PH5 . GAP"),
            ("ENABLE_PH5A", "PH5A . PVAT"),
            ("ENABLE_PH6",  "PH6 . OPTIONS"),
            ("ENABLE_PH7",  "PH7 . MCX"),
            ("ENABLE_PH8",  "PH8 . MOMENTUM"),
        ]

        _db_states = {}
        if hasattr(self, 'data_bridge') and self.data_bridge:
            try:
                _db_states = self.data_bridge.get_phase_states()
            except Exception:
                pass

        for config_key, base_label in phases:
            initial_state = _db_states.get(config_key, 'OFF')
            phase_id = CONFIG_TO_PHASE.get(config_key, "")

            row = ctk.CTkFrame(self.sidebar, fg_color="transparent")
            row.pack(fill="x", padx=12, pady=2)

            btn = _SidebarToggle(
                row,
                base_label=base_label,
                initial_state=initial_state,
                on_toggle=lambda state, k=config_key: self._on_phase_toggle(k, state),
            )
            btn.pack(side="left", fill="x", expand=True)
            self._phase_buttons[config_key] = btn

            info_btn = ctk.CTkButton(
                row, text=">", width=30, height=38,
                font=FONT_BODY_BOLD,
                corner_radius=6, border_width=2,
                fg_color="transparent", hover_color=BORDER,
                border_color=BORDER_DIM, text_color=TEXT_MUTED,
                command=lambda pid=phase_id: self._open_phase_detail(pid),
            )
            info_btn.pack(side="right", padx=(2, 0))

        ctk.CTkFrame(self.sidebar, fg_color=BORDER_DIM, height=1
                     ).pack(fill="x", padx=12, pady=(6, 4))

        # -- MIE static ON label --
        mie_lbl = ctk.CTkLabel(
            self.sidebar, text="MIE . ON",
            font=FONT_BODY_BOLD, text_color="#ffffff",
            fg_color=AMBER, corner_radius=6,
            height=36,
        )
        mie_lbl.pack(fill="x", padx=12, pady=(0, 4))
        self.config_data.update("ENABLE_MIE", True)

        # -- Divider before SETTINGS --
        ctk.CTkFrame(self.sidebar, fg_color=BORDER_DIM, height=1
                     ).pack(fill="x", padx=12, pady=(6, 4))

        # -- SETTINGS (packed normally — no overlay) --
        self._add_nav_item_in(self.sidebar, "settings", "SETTINGS")

        # -- Sidebar status dict (status shown in top bar) --
        self._sidebar_status = {}

    def _add_nav_item_in(self, parent, tab_id, label):
        """Create a clickable nav button inside a specific container."""
        self._create_nav_button(tab_id, label, parent=parent)

    def _create_nav_button(self, tab_id, label, parent=None):
        """Internal: create nav button inside the given parent frame."""
        if parent is None:
            parent = self.sidebar
        nav = ctk.CTkFrame(parent, fg_color="transparent")
        nav.pack(fill="x", padx=8, pady=(0, 0))

        indicator = ctk.CTkFrame(nav, fg_color="transparent", width=3, corner_radius=2)
        indicator.pack(side="left", fill="y")

        inner = ctk.CTkFrame(nav, fg_color="transparent", cursor="hand2")
        inner.pack(fill="x", padx=4, pady=0)

        lbl = ctk.CTkLabel(inner, text=label,
                           font=FONT_NAV, text_color=SIDEBAR_BTN_BG,
                           anchor="w", cursor="hand2")
        lbl.pack(side="left", fill="x", expand=True, padx=12, pady=6)

        # Click binding on inner frame and label
        inner.bind("<Button-1>", lambda e, t=tab_id: self._switch_view(t))
        lbl.bind("<Button-1>", lambda e, t=tab_id: self._switch_view(t))

        self._nav_items[tab_id] = {
            "frame": nav, "indicator": indicator, "inner": inner, "label": lbl,
        }

    # ==================================================================
    #  TAB SWITCHING
    # ==================================================================

    def _switch_view(self, tab_id):
        """Switch between Control Panel, Dashboard, and Settings views."""
        if tab_id == self._active_tab:
            return

        # Hide current view
        if self._active_tab and self._active_tab in self._views:
            self._views[self._active_tab].pack_forget()

        # Create view on first access
        if tab_id not in self._views:
            if tab_id == "control":
                view = ControlPanelView(self.main_area, self.config_data, self.bridge,
                                         app=self, data_bridge=self.data_bridge)
            elif tab_id == "dashboard":
                view = DashboardView(self.main_area, self.config_data,
                                      data_bridge=self.data_bridge)
            elif tab_id == "settings":
                view = SettingsView(self.main_area, self.config_data)
            else:
                return
            self._views[tab_id] = view

        # Show view
        self._views[tab_id].pack(fill="both", expand=True, padx=4, pady=4)

        # Update nav highlighting
        for nid, nav_data in self._nav_items.items():
            if nid == tab_id:
                nav_data["indicator"].configure(fg_color=SIDEBAR_BTN_BG)
                nav_data["inner"].configure(fg_color=BG_NAV_ACTIVE)
                nav_data["label"].configure(text_color=SIDEBAR_BTN_BG)
            else:
                nav_data["indicator"].configure(fg_color="transparent")
                nav_data["inner"].configure(fg_color="transparent")
                nav_data["label"].configure(text_color=SIDEBAR_BTN_BG)

        self._active_tab = tab_id

    # ==================================================================
    #  PHASE TOGGLES, DETAIL VIEWS & STATUS
    # ==================================================================

    def _on_phase_toggle(self, config_key, state):
        """Handle phase toggle OFF/PAPER/LIVE — writes to SQLite bridge."""
        # Write to mission_control.db (orchestrator reads this each loop)
        if hasattr(self, 'data_bridge') and self.data_bridge:
            self.data_bridge.set_phase_state(config_key, state)
        # Update local config for info bar display
        self.config_data.update(config_key, state != 'OFF')
        # Notify control panel if it exists
        cp = self._views.get("control")
        if cp and hasattr(cp, 'on_phase_changed'):
            cp.on_phase_changed(config_key, state)

    def _open_phase_detail(self, phase_id):
        """Navigate to a phase detail sub-view inside Dashboard."""
        # Switch to Dashboard tab (creates it if needed)
        self._switch_view("dashboard")
        # Open the phase detail sub-view
        dashboard = self._views.get("dashboard")
        if dashboard:
            dashboard.show_phase_detail(phase_id)

    def _open_trades_history(self):
        """Navigate to trades history sub-view inside Dashboard."""
        self._switch_view("dashboard")
        dashboard = self._views.get("dashboard")
        if dashboard:
            dashboard.show_phase_detail("trades_history")

    def update_sidebar_status(self, config_key, connected):
        """Update sidebar connection status dots."""
        if config_key in self._sidebar_status:
            color = GREEN if connected else RED
            text = "OK" if connected else "--"
            self._sidebar_status[config_key]["dot"].configure(text_color=color)
            self._sidebar_status[config_key]["text"].configure(text=text)


class _SidebarToggle(ctk.CTkFrame):
    """3-state toggle button: OFF → PAPER → LIVE → OFF (cycle)."""

    _CYCLE = ['OFF', 'PAPER', 'LIVE']

    _STYLES = {
        'OFF':   {'text_color': '#8A8A8A', 'fg_color': '#E0D8C8',
                  'hover_color': '#D5CDB8', 'border_color': BORDER},
        'PAPER': {'text_color': '#ffffff', 'fg_color': '#D97706',
                  'hover_color': '#B45309', 'border_color': '#D97706'},
        'LIVE':  {'text_color': '#ffffff', 'fg_color': '#16A34A',
                  'hover_color': '#15803D', 'border_color': '#16A34A'},
    }

    def __init__(self, parent, base_label, initial_state='OFF', on_toggle=None):
        super().__init__(parent, fg_color="transparent")
        self._base_label = base_label
        self._on_toggle = on_toggle
        self._state = initial_state if initial_state in self._CYCLE else 'OFF'

        self.btn = ctk.CTkButton(
            self, text=self._make_text(),
            height=38,
            font=FONT_BODY_BOLD,
            corner_radius=6, border_width=2,
            command=self._toggle,
        )
        self.btn.pack(fill="x")
        self._apply()

    def _make_text(self):
        return f"{self._base_label} {self._state}"

    def _toggle(self):
        idx = self._CYCLE.index(self._state)
        self._state = self._CYCLE[(idx + 1) % 3]
        self._apply()
        if self._on_toggle:
            self._on_toggle(self._state)

    def _apply(self):
        style = self._STYLES[self._state]
        self.btn.configure(
            text=self._make_text(),
            text_color=style['text_color'],
            fg_color=style['fg_color'],
            hover_color=style['hover_color'],
            border_color=style['border_color'],
        )

    @property
    def state(self):
        return self._state


def main():
    print("=" * 56)
    print("  ALGO_BETA - Control Center v1.7")
    print("=" * 56)
    app = AlgoBetaApp()
    app.mainloop()


if __name__ == "__main__":
    main()
