"""
Algo_Beta GUI -- Settings View
================================
Zerodha Kite API & Telegram Bot credential management.
Credentials stored locally in credentials.json.
"""

import customtkinter as ctk
import json
import os

import sys as _sys
import os as _os
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from theme import (  # noqa: E402
    BG_APP, BG_PANEL, BG_HEADER, BG_INPUT,
    BORDER, BORDER_DIM,
    TEXT_PRIMARY, TEXT_LABEL, TEXT_MUTED, TEXT_DIM, TEXT_ENTRY,
    ACCENT_CYAN, GREEN, RED,
    FONT_FAMILY, FONT_TITLE, FONT_HEADING, FONT_BODY_BOLD, FONT_BODY,
    FONT_SMALL_BOLD, FONT_SMALL, FONT_TINY_BOLD, FONT_TINY,
)

# Credentials file path
CREDENTIALS_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "algo_beta_gui", "credentials.json"
)


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


class SettingsView(ctk.CTkFrame):
    """Settings tab -- API credentials for Kite and Telegram."""

    def __init__(self, parent, config):
        super().__init__(parent, fg_color="transparent")
        self.config = config

        self._entries = {}
        self._show_vars = {}
        self._status_job = None

        self._build_ui()
        self._load_saved_credentials()

    def _build_ui(self):
        # Scrollable container
        scroll = ctk.CTkScrollableFrame(self, fg_color="transparent",
                                         scrollbar_button_color=BORDER_DIM)
        scroll.pack(fill="both", expand=True, padx=2, pady=2)

        scroll.columnconfigure(0, weight=1)
        scroll.columnconfigure(1, weight=1)

        # Row 0 left: Zerodha Kite API
        self._build_kite_section(scroll, row=0, col=0)

        # Row 0 right: Telegram Bot
        self._build_telegram_section(scroll, row=0, col=1)

        # Row 1: Actions (full width)
        self._build_actions(scroll, row=1)

    # === ZERODHA KITE API ==========================================

    def _build_kite_section(self, parent, row, col):
        frame = _section_frame(parent, "ZERODHA KITE API", row=row, col=col)

        # LED indicator
        led_row = ctk.CTkFrame(frame, fg_color="transparent")
        led_row.pack(fill="x", padx=14, pady=(0, 6))
        self._kite_dot = ctk.CTkLabel(led_row, text="●", font=("", 18),
                                       text_color="#ef4444", width=20)
        self._kite_dot.pack(side="left", padx=(0, 6))
        self._kite_status = ctk.CTkLabel(led_row, text="Not configured",
                                          font=FONT_TINY_BOLD,
                                          text_color="#ef4444")
        self._kite_status.pack(side="left")

        # Fields
        self._add_field(frame, "api_key", "API Key", masked=False)
        self._add_field(frame, "api_secret", "API Secret", masked=True)
        self._add_field(frame, "user_id", "User ID", masked=False)

        ctk.CTkLabel(frame, text="", height=8).pack()

    # === TELEGRAM BOT ==============================================

    def _build_telegram_section(self, parent, row, col):
        frame = _section_frame(parent, "TELEGRAM BOT", row=row, col=col)

        # LED indicator
        led_row = ctk.CTkFrame(frame, fg_color="transparent")
        led_row.pack(fill="x", padx=14, pady=(0, 6))
        self._telegram_dot = ctk.CTkLabel(led_row, text="●", font=("", 18),
                                           text_color="#ef4444", width=20)
        self._telegram_dot.pack(side="left", padx=(0, 6))
        self._telegram_status = ctk.CTkLabel(led_row, text="Not configured",
                                              font=FONT_TINY_BOLD,
                                              text_color="#ef4444")
        self._telegram_status.pack(side="left")

        # Fields
        self._add_field(frame, "bot_token", "Bot Token", masked=True)
        self._add_field(frame, "chat_id", "Chat ID", masked=False)

        ctk.CTkLabel(frame, text="", height=8).pack()

    # === ACTIONS ===================================================

    def _build_actions(self, parent, row):
        frame = _section_frame(parent, "ACTIONS", row=row, columnspan=2)

        btn_row = ctk.CTkFrame(frame, fg_color="transparent")
        btn_row.pack(fill="x", padx=14, pady=(0, 6))

        ctk.CTkButton(
            btn_row, text="SAVE CREDENTIALS", width=180, height=36,
            font=FONT_SMALL_BOLD,
            fg_color="#166534", hover_color="#15803d", text_color="#4ade80",
            command=self._on_save,
        ).pack(side="left")

        self._save_status = ctk.CTkLabel(
            btn_row, text="",
            font=FONT_TINY_BOLD, text_color="#22c55e",
        )
        self._save_status.pack(side="left", padx=(12, 0))

        # Info box
        info = ctk.CTkFrame(frame, fg_color=BG_INPUT, corner_radius=6)
        info.pack(fill="x", padx=14, pady=(4, 10))

        ctk.CTkLabel(info, text=f"Saves to: {CREDENTIALS_FILE}",
                     font=FONT_TINY, text_color=TEXT_DIM,
                     anchor="w").pack(padx=10, pady=(6, 2), anchor="w")

        ctk.CTkLabel(info, text="Secrets stored locally. Add credentials.json to .gitignore.",
                     font=FONT_TINY, text_color="#f59e0b",
                     anchor="w").pack(padx=10, pady=(0, 6), anchor="w")

    # === FIELD HELPER ==============================================

    def _add_field(self, parent, key, label, masked=False):
        row_frame = ctk.CTkFrame(parent, fg_color="transparent")
        row_frame.pack(fill="x", padx=14, pady=(2, 2))

        ctk.CTkLabel(row_frame, text=label,
                     font=FONT_SMALL, text_color=TEXT_LABEL,
                     anchor="w", width=120).pack(side="left")

        entry_frame = ctk.CTkFrame(row_frame, fg_color="transparent")
        entry_frame.pack(side="right", fill="x", expand=True)

        show_char = "bullet" if masked else ""
        entry = ctk.CTkEntry(
            entry_frame, height=30,
            font=FONT_SMALL,
            fg_color=BG_INPUT, border_color=BORDER,
            text_color=TEXT_ENTRY, show="bullet" if masked else "",
        )
        entry.pack(side="left", fill="x", expand=True)
        self._entries[key] = entry

        if masked:
            show_var = ctk.BooleanVar(value=False)
            self._show_vars[key] = show_var
            eye_btn = ctk.CTkButton(
                entry_frame, text="Show", width=50, height=30,
                font=FONT_TINY,
                fg_color=BG_HEADER, hover_color=BORDER, text_color=TEXT_MUTED,
                command=lambda e=entry, sv=show_var, b=None: self._toggle_visibility(e, sv),
            )
            eye_btn.pack(side="left", padx=(4, 0))

    def _toggle_visibility(self, entry, show_var):
        current = show_var.get()
        show_var.set(not current)
        entry.configure(show="" if current else "bullet")

    # === LOAD / SAVE ===============================================

    def _load_saved_credentials(self):
        if not os.path.exists(CREDENTIALS_FILE):
            return

        try:
            with open(CREDENTIALS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return

        for key, value in data.items():
            if key in self._entries and value:
                self._entries[key].delete(0, "end")
                self._entries[key].insert(0, str(value))

        self._update_led_status()

    def _on_save(self):
        data = {}
        for key, entry in self._entries.items():
            data[key] = entry.get().strip()

        try:
            os.makedirs(os.path.dirname(CREDENTIALS_FILE), exist_ok=True)
            with open(CREDENTIALS_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            self._save_status.configure(text=f"Error: {e}", text_color="#ef4444")
            return

        self._update_led_status()
        self._save_status.configure(text="Saved successfully", text_color="#22c55e")

        # Clear status after 3 seconds
        if self._status_job:
            self.after_cancel(self._status_job)
        self._status_job = self.after(3000, lambda: self._save_status.configure(text=""))

    def _update_led_status(self):
        # Kite: green if api_key AND user_id non-empty
        api_key = self._entries.get("api_key", None)
        user_id = self._entries.get("user_id", None)
        kite_ok = (api_key and api_key.get().strip()) and (user_id and user_id.get().strip())

        if kite_ok:
            self._kite_dot.configure(text_color="#22c55e")
            self._kite_status.configure(text="Configured", text_color="#22c55e")
        else:
            self._kite_dot.configure(text_color="#ef4444")
            self._kite_status.configure(text="Not configured", text_color="#ef4444")

        # Telegram: green if bot_token AND chat_id non-empty
        bot_token = self._entries.get("bot_token", None)
        chat_id = self._entries.get("chat_id", None)
        tg_ok = (bot_token and bot_token.get().strip()) and (chat_id and chat_id.get().strip())

        if tg_ok:
            self._telegram_dot.configure(text_color="#22c55e")
            self._telegram_status.configure(text="Configured", text_color="#22c55e")
        else:
            self._telegram_dot.configure(text_color="#ef4444")
            self._telegram_status.configure(text="Not configured", text_color="#ef4444")

    def destroy(self):
        if self._status_job:
            self.after_cancel(self._status_job)
        super().destroy()
