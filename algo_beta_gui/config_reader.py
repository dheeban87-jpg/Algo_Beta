"""
Algo_Beta GUI — Config Reader
===============================
Reads REAL values from ../config.py (parent Algo_Beta folder).
Falls back to mock defaults if config.py is not found.

Location assumption:
    Algo_Beta/
    ├── config.py             ← your real config
    ├── algo_beta_gui/
    │   ├── config_reader.py  ← this file
    │   └── main.py
"""

import sys
import os
import importlib


class ConfigReader:

    def __init__(self):
        self._live = False
        self._real_config = None
        self._data = {}
        self._try_load_real_config()
        self._build_data()

    def _try_load_real_config(self):
        """Try importing config.py from parent directory."""
        try:
            gui_dir = os.path.dirname(os.path.abspath(__file__))
            parent_dir = os.path.dirname(gui_dir)

            if parent_dir not in sys.path:
                sys.path.insert(0, parent_dir)

            if "config" in sys.modules:
                self._real_config = importlib.reload(sys.modules["config"])
            else:
                self._real_config = importlib.import_module("config")

            self._live = True
            print(f"[CONFIG] OK - Loaded REAL config.py from: {parent_dir}")

        except ImportError:
            print("[CONFIG] WARN - config.py not found - using mock defaults")
            self._live = False
        except Exception as e:
            print(f"[CONFIG] ERR - Error loading config.py: {e} - using mock defaults")
            self._live = False

    def _read_real(self, key, default):
        """Read a value from real config.py with fallback.
        Checks both module-level and class Config: attributes."""
        if self._real_config is None:
            return default
        # Check module-level first, then Config class
        sources = [self._real_config]
        config_cls = getattr(self._real_config, "Config", None)
        if config_cls is not None:
            sources.append(config_cls)
        for source in sources:
            for variant in [key, key.upper(), key.lower()]:
                val = getattr(source, variant, None)
                if val is not None:
                    return val
        return default

    def _read_real_dict(self, dict_key, item_key, default):
        """Read a value from a dict attribute in real config.py."""
        if self._real_config is None:
            return default
        sources = [self._real_config]
        config_cls = getattr(self._real_config, "Config", None)
        if config_cls is not None:
            sources.append(config_cls)
        for source in sources:
            d = getattr(source, dict_key, None)
            if d and isinstance(d, dict) and item_key in d:
                return d[item_key]
        return default

    def _build_data(self):
        """Build unified config dict — real values override mock defaults."""
        defaults = {
            # System
            "SYSTEM_VERSION": "v5.6.0",
            "SYSTEM_RUNNING": False,
            "PRODUCT_MODE": "CNC-first",
            "EXPIRY_DAY": "Tuesday",

            # Phase Enables (only user-controlled phases)
            "ENABLE_PH5": False,
            "ENABLE_PH5A": False,
            "ENABLE_PH6": False,
            "ENABLE_PH7": False,
            "ENABLE_PH8": False,
            "ENABLE_MIE": True,

            # Phase 2 Scoring Thresholds
            "PH2_SCORE_ENTRY_MIN": 65,
            "PH2_SCORE_FULL_POSITION": 70,
            "PH2_SCORE_STRONG_BUY": 80,

            # TCAS Thresholds (ATR units)
            "TCAS_TA_THRESHOLD_ATR": 2.0,
            "TCAS_RA_THRESHOLD_ATR": 1.5,
            "TCAS_ALIM_THRESHOLD_ATR": 0.75,

            # Profit/Loss
            "PROFIT_TARGET_PCT": 5.0,
            "STOP_LOSS_PCT": 2.0,

            # Scanning
            "SCAN_INTERVAL_MINUTES": 30,

            # Legacy thresholds (kept for compatibility)
            "MIN_SCORE": 60,
            "MAX_POSITIONS": 8,
            "SCAN_INTERVAL_SEC": 60,
            "MIN_RSI_DEFAULT": 35,
            "MIN_VOLUME_MULTIPLE": 1.5,
            "MAX_DRAWDOWN_PCT": 10.0,

            # RSI Overrides
            "RSI_OVERRIDES": {
                "RAMCOCEM": 42, "NIFTY": 32, "HDFCBANK": 36,
                "RELIANCE": 38, "TATAMOTORS": 40, "SBIN": 35,
            },

            # Capital
            "TOTAL_CAPITAL": 500000,
            "BASE_CAPITAL_PER_TRADE": 60000,
            "MAX_TOTAL_POSITIONS": 2,
            "MIN_CAPITAL_BUFFER": 1000,
            "CAPITAL_DEPLOYED": 0,
            "CAPITAL_AVAILABLE": 500000,

            # Legacy capital keys (kept for compatibility)
            "MAX_PER_TRADE": 60000,
            "MAX_EXPOSURE_PCT": 80.0,
            "CNC_CAPITAL_PCT": 70.0,
            "MIS_CAPITAL_PCT": 30.0,

            # Market Hours
            "MARKET_OPEN_HOUR": 9,
            "MARKET_OPEN_MINUTE": 15,
            "MARKET_CLOSE_HOUR": 15,
            "MARKET_CLOSE_MINUTE": 30,

            # Connections
            "KITE_CONNECTED": False,
            "TELEGRAM_CONNECTED": False,
            "KITE_API_KEY": "not set",
            "TELEGRAM_CHAT_ID": "not set",
        }

        for key, mock_val in defaults.items():
            self._data[key] = self._read_real(key, mock_val)

        # Post-processing for live config
        if self._live and self._real_config:
            # Extract MIN_CAPITAL_BUFFER from CAPITAL_MANAGEMENT dict
            buf = self._read_real_dict("CAPITAL_MANAGEMENT", "MIN_CAPITAL_BUFFER", None)
            if buf is not None:
                self._data["MIN_CAPITAL_BUFFER"] = buf

            # Sync legacy MAX_PER_TRADE with BASE_CAPITAL_PER_TRADE
            self._data["MAX_PER_TRADE"] = self._data["BASE_CAPITAL_PER_TRADE"]

            # CAPITAL_AVAILABLE = TOTAL_CAPITAL - CAPITAL_DEPLOYED
            self._data["CAPITAL_AVAILABLE"] = (
                self._data["TOTAL_CAPITAL"] - self._data["CAPITAL_DEPLOYED"]
            )

        src = "LIVE config.py" if self._live else "MOCK defaults"
        print(f"[CONFIG] Source: {src}")
        print(f"[CONFIG] Capital: Rs.{self._data['TOTAL_CAPITAL']:,.0f}, "
              f"Per Trade: Rs.{self._data['BASE_CAPITAL_PER_TRADE']:,.0f}")
        print(f"[CONFIG] Scoring: Entry={self._data['PH2_SCORE_ENTRY_MIN']}, "
              f"Full={self._data['PH2_SCORE_FULL_POSITION']}, "
              f"Strong={self._data['PH2_SCORE_STRONG_BUY']}")

    def is_live(self):
        return self._live

    def get(self, key, default=None):
        return self._data.get(key, default)

    def get_all(self):
        return self._data.copy()

    def update(self, key, value):
        self._data[key] = value
        return True

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

    def reload(self):
        if self._real_config:
            try:
                self._real_config = importlib.reload(self._real_config)
                self._build_data()
                print("[CONFIG] OK - Reloaded config.py")
                return True
            except Exception as e:
                print(f"[CONFIG] ERR - Reload failed: {e}")
        return False
