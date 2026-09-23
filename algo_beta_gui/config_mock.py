"""
Algo_Beta GUI — Mock Data Layer
================================
Simulates reading from config.py and SQLite DB.
Replace this module with real config reader when wiring to live system.

Usage:
    from config_mock import MockConfig
    cfg = MockConfig()
    cfg.get_all()           # Returns full config dict
    cfg.update(key, value)  # Updates a value (routes through telegram_bridge)
"""


class MockConfig:
    """
    Mock configuration that mirrors your config.py variables.
    When you go live, replace this with:
        import importlib
        config = importlib.import_module('config')
    """

    def __init__(self):
        self._data = {
            # ── System ──────────────────────────────────────
            "SYSTEM_VERSION": "v5.6.0",
            "SYSTEM_RUNNING": False,
            "PRODUCT_MODE": "CNC-first",
            "EXPIRY_DAY": "Tuesday",

            # ── Phase Enables ───────────────────────────────
            "ENABLE_PH1": True,       # Stock Selection
            "ENABLE_PH2": True,       # Entry Timing
            "ENABLE_PH3": True,       # Order Execution
            "ENABLE_PH4": True,       # Portfolio Management
            "ENABLE_PH5": False,      # Intraday Gap Strategy
            "ENABLE_PH5A": True,      # PVAT Scanner
            "ENABLE_PH6": True,       # Options Shadow (paper only)
            "ENABLE_PH7": False,      # MCX Commodities
            "ENABLE_PH8": False,      # Momentum Trade
            "ENABLE_MIE": True,       # Market Intelligence Engine (always on)

            # ── Phase 2 Scoring Thresholds ────────────────
            "PH2_SCORE_ENTRY_MIN": 65,
            "PH2_SCORE_FULL_POSITION": 70,
            "PH2_SCORE_STRONG_BUY": 80,

            # ── TCAS Thresholds (ATR units) ───────────────
            "TCAS_TA_THRESHOLD_ATR": 2.0,
            "TCAS_RA_THRESHOLD_ATR": 1.5,
            "TCAS_ALIM_THRESHOLD_ATR": 0.75,

            # ── Profit/Loss ───────────────────────────────
            "PROFIT_TARGET_PCT": 5.0,
            "STOP_LOSS_PCT": 2.0,

            # ── Scanning ──────────────────────────────────
            "SCAN_INTERVAL_MINUTES": 30,

            # ── Legacy Thresholds ─────────────────────────
            "MIN_SCORE": 60,
            "MAX_POSITIONS": 8,
            "SCAN_INTERVAL_SEC": 60,
            "MIN_RSI_DEFAULT": 35,
            "MIN_VOLUME_MULTIPLE": 1.5,
            "MAX_DRAWDOWN_PCT": 10.0,

            # ── RSI Overrides (stock-specific) ────────────
            "RSI_OVERRIDES": {
                "RAMCOCEM": 42,
                "NIFTY": 32,
                "HDFCBANK": 36,
                "RELIANCE": 38,
                "TATAMOTORS": 40,
                "SBIN": 35,
            },

            # ── Capital Management ────────────────────────
            "TOTAL_CAPITAL": 500000,
            "BASE_CAPITAL_PER_TRADE": 60000,
            "MAX_TOTAL_POSITIONS": 2,
            "MIN_CAPITAL_BUFFER": 1000,
            "CAPITAL_DEPLOYED": 0,
            "CAPITAL_AVAILABLE": 500000,

            # Legacy capital keys
            "MAX_PER_TRADE": 60000,
            "MAX_EXPOSURE_PCT": 80.0,
            "CNC_CAPITAL_PCT": 70.0,
            "MIS_CAPITAL_PCT": 30.0,

            # ── Market Hours ──────────────────────────────
            "MARKET_OPEN_HOUR": 9,
            "MARKET_OPEN_MINUTE": 15,
            "MARKET_CLOSE_HOUR": 15,
            "MARKET_CLOSE_MINUTE": 30,

            # ── Zerodha / Telegram Status ─────────────────
            "KITE_CONNECTED": True,
            "TELEGRAM_CONNECTED": True,
            "KITE_API_KEY": "••••••4f2a",
            "TELEGRAM_CHAT_ID": "••••5678",
        }

    def is_live(self):
        return False

    def get(self, key, default=None):
        return self._data.get(key, default)

    def get_all(self):
        return self._data.copy()

    def update(self, key, value):
        self._data[key] = value
        return True

    def get_phase_enables(self):
        return {k: v for k, v in self._data.items() if k.startswith("ENABLE_PH")}

    def get_rsi_overrides(self):
        return self._data.get("RSI_OVERRIDES", {}).copy()

    def set_rsi_override(self, symbol, value):
        self._data["RSI_OVERRIDES"][symbol] = value

    def remove_rsi_override(self, symbol):
        self._data["RSI_OVERRIDES"].pop(symbol, None)

    def get_capital_summary(self):
        total = self._data["TOTAL_CAPITAL"]
        return {
            "total": total,
            "per_trade": self._data["BASE_CAPITAL_PER_TRADE"],
            "max_positions": self._data["MAX_TOTAL_POSITIONS"],
            "min_buffer": self._data["MIN_CAPITAL_BUFFER"],
            "deployed": self._data["CAPITAL_DEPLOYED"],
            "available": self._data.get("CAPITAL_AVAILABLE",
                                        total - self._data["CAPITAL_DEPLOYED"]),
            "deployed_pct": (self._data["CAPITAL_DEPLOYED"] / total * 100)
                            if total > 0 else 0,
        }

    def get_market_hours(self):
        return {
            "open_hour": self._data["MARKET_OPEN_HOUR"],
            "open_minute": self._data["MARKET_OPEN_MINUTE"],
            "close_hour": self._data["MARKET_CLOSE_HOUR"],
            "close_minute": self._data["MARKET_CLOSE_MINUTE"],
        }
