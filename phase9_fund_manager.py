"""
Phase 9: AI Fund Manager — Claude as Strategic Decision Layer
═══════════════════════════════════════════════════════════════

v1.0.0 — April 2026

Architecture:
    Level 1 — Strategic Overseer
    ├─ Morning Briefing (pre-market): market regime, capital allocation, phase activation
    ├─ EOD Review (post-market): performance analysis, parameter adjustment, journal

    Level 2 — Selective Decision Maker
    ├─ Trade Approval Gate: approve/reject/modify every entry before execution
    └─ Exit Advisor: approve/reject exits on TCAS/stop triggers

Safety Rails (non-negotiable, override Claude):
    ├─ MAX_DAILY_LOSS circuit breaker
    ├─ MAX_POSITION_SIZE hard cap
    ├─ MAX_OPEN_POSITIONS limit
    ├─ CLAUDE_TIMEOUT fallback to rules
    └─ HARD_STOP_OVERRIDE always enforced

Data Flow:
    System collects → packages → sends to Claude → parses JSON → executes
    Claude has NO internet access. All data is pre-fetched.
"""

import html as _html
import json
import re
import logging
import os
import socket
import traceback
from datetime import datetime, time as dt_time, date
from typing import Dict, Optional, List, Any

try:
    import anthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False

try:
    from database import get_db
    DATABASE_AVAILABLE = True
except ImportError:
    DATABASE_AVAILABLE = False

logger = logging.getLogger('Phase9_FundManager')


# ═══════════════════════════════════════════════════════════════════════════════
# NETWORK CONNECTIVITY CHECK (v1.0.1)
# ═══════════════════════════════════════════════════════════════════════════════

def _network_reachable(host: str = "api.anthropic.com", port: int = 443,
                       timeout: float = 2.0) -> bool:
    """
    Fast TCP reachability check — does NOT retry. Returns True if host is reachable.
    Used to gate Claude API calls so we fail-fast on VPN/DNS drops instead of
    hanging on anthropic's internal retry loop.
    """
    try:
        socket.setdefaulttimeout(timeout)
        # DNS resolution
        socket.gethostbyname(host)
        # TCP handshake
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (socket.gaierror, socket.timeout, OSError):
        return False
    except Exception:
        return False
    finally:
        socket.setdefaulttimeout(None)


# ═══════════════════════════════════════════════════════════════════════════════
# PHASE 9: AI FUND MANAGER
# ═══════════════════════════════════════════════════════════════════════════════

class Phase9FundManager:
    """
    Claude-powered Fund Manager that operates at two levels:

    Level 1 (Strategic): Morning briefing + EOD review
    Level 2 (Tactical): Entry approval gate + exit advisor

    All decisions are logged to database and Telegram.
    Safety rails ALWAYS override Claude's decisions.
    """

    VERSION = "1.1.0"  # v1.1.0 — cost optimization (dual-model, gray-zone, budget)

    # ═══════════════════════════════════════════════════════════════════════════
    # COST MODEL — INR per 1K tokens (as of April 2026)
    # Haiku: ~$0.25 in / $1.25 out → ~₹0.02/1K in, ₹0.10/1K out
    # Sonnet: ~$3 in / $15 out    → ~₹0.25/1K in, ₹1.25/1K out
    # ═══════════════════════════════════════════════════════════════════════════
    COST_TABLE = {
        'haiku': {'input_per_1k': 0.02, 'output_per_1k': 0.10},   # INR
        'sonnet': {'input_per_1k': 0.25, 'output_per_1k': 1.25},  # INR
    }

    def __init__(self, config, telegram=None, kite=None, capital_manager=None):
        """
        Initialize Phase 9 Fund Manager (v1.1.0 cost-optimized).

        Args:
            config: AlgoConfig instance
            telegram: TelegramNotifier for alerts
            kite: Authenticated KiteConnect (for portfolio data)
            capital_manager: CapitalManager for budget info
        """
        self.config = config
        self.telegram = telegram
        self.kite = kite
        self.capital_manager = capital_manager

        # ═══════════════════════════════════════════════════════════════════
        # DUAL-MODEL STRATEGY (v1.1.0)
        # Sonnet = strategic reasoning (morning briefing, EOD review) — 2/day
        # Haiku  = tactical gates (entry/exit) — 10-20/day
        # ═══════════════════════════════════════════════════════════════════
        self.client = None
        self.model_sonnet = getattr(config, 'PH9_MODEL_SONNET',
                                    'claude-sonnet-4-20250514')
        self.model_haiku = getattr(config, 'PH9_MODEL_HAIKU',
                                   'claude-haiku-4-20250514')
        # Backward compat
        self.model = self.model_sonnet

        if ANTHROPIC_AVAILABLE:
            # Priority: config object (has hardcoded fallback) → env var → empty
            env_var_name = getattr(config, 'PH9_API_KEY_ENV_VAR', 'ANTHROPIC_API_KEY')
            api_key = (
                getattr(config, 'ANTHROPIC_API_KEY', None)      # config.py fallback key
                or getattr(config, 'CHATGPT_API_KEY', None)     # alias used by other phases
                or os.environ.get(env_var_name, '')              # env var as last resort
            )
            if api_key:
                # v1.0.1: max_retries=0 — fail fast on network issues.
                self.client = anthropic.Anthropic(
                    api_key=api_key,
                    timeout=getattr(config, 'PH9_CLAUDE_TIMEOUT', 8.0),
                    max_retries=0
                )
                logger.info(f"Phase 9 Fund Manager: Claude client initialized")
                logger.info(f"   Strategic model (briefings): {self.model_sonnet}")
                logger.info(f"   Tactical model (gates):      {self.model_haiku}")
            else:
                logger.warning("Phase 9: ANTHROPIC_API_KEY not set — Fund Manager DISABLED")
        else:
            logger.warning("Phase 9: anthropic package not installed — Fund Manager DISABLED")

        # Database
        self._db = None
        if DATABASE_AVAILABLE:
            try:
                self._db = get_db()
            except Exception:
                pass

        # ═══════════════════════════════════════════════════════════════════
        # STATE TRACKING
        # ═══════════════════════════════════════════════════════════════════

        self._morning_briefing_done = False
        self._morning_briefing_date = None
        self._eod_review_done = False
        self._eod_review_date = None
        # v1.1.0: Midday + weekly state
        self._midday_check_done = False
        self._midday_check_date = None
        self._weekly_review_date = None
        self.weekly_directive = {}

        # v1.3.2: Post-ALIM re-entry tracking
        self._reentry_done_today: Dict[str, int] = {}  # symbol → count re-entered today
        self._pending_reentry_plans: Dict[str, Dict] = {}  # symbol → approved plan for orchestrator

        # Today's strategic directives (set by morning briefing)
        self.todays_regime = 'NORMAL'           # NORMAL / CAUTIOUS / AGGRESSIVE / HALT
        self.todays_max_positions = getattr(config, 'PH9_MAX_POSITIONS', 5)
        self.todays_size_multiplier = 1.0       # 0.5 = half size, 1.5 = 1.5x
        self.todays_phases_active = ['PH1', 'PH2', 'PH3', 'PH4', 'PH5', 'PH5A', 'PH8']
        self.todays_notes             = ''
        self.todays_day_plan          = ''
        self.todays_unlock_conditions = ''
        self.todays_watch_stocks      = ''

        # v1.3.0: Extended strategic directives — all phases read these
        self.todays_market_bias      = 'NEUTRAL'  # BULLISH / BEARISH / NEUTRAL
        self.todays_vix_regime       = 'NORMAL'   # LOW(<12) / NORMAL(12-18) / HIGH(18-25) / EXTREME(>25)
        self.todays_ph5_size_mult    = 1.0        # VIX-tiered size scalar for PH5 (0.25–1.0)
        self.todays_ph5_stop_mult    = 1.0        # VIX-tiered stop width scalar for PH5 (1.0–2.0)
        self.todays_sector_focus     : List[str] = []  # e.g. ['IT', 'PHARMA'] — score-boost these
        self.todays_sector_avoid     : List[str] = []  # e.g. ['METALS'] — skip these entirely
        self.todays_entry_window     = '09:15'    # earliest safe entry time HH:MM
        self.todays_stop_atr_mult    = 1.0        # global stop ATR scalar applied on top of regime
        self.todays_target_atr_mult  = 1.0        # global target ATR scalar
        self.todays_exit_aggression  = 'NORMAL'   # EARLY(80% target) / NORMAL / HOLD(trail)
        self.todays_ph6_options_bias = 'NEUTRAL'  # CALL / PUT / NEUTRAL — gates TCAS pivot
        self.todays_risk_level       = 'MEDIUM'   # LOW / MEDIUM / HIGH
        self.todays_confidence       = 70         # Claude's confidence in today's read 0-100

        # v1.4.0: Per-phase directives (set by morning briefing + heartbeat)
        self.todays_ph5_directive  = 'ACTIVE'   # ACTIVE / SKIP / REDUCED_SIZE_50
        self.todays_ph5a_directive = 'ACTIVE'   # ACTIVE / PAUSE
        self.todays_ph4_directive  = 'NORMAL'   # NORMAL / DEFENSIVE
        self.todays_ph6_directive  = 'ACTIVE'   # ACTIVE / HOLD
        self.todays_ph8_directive  = 'HOLD'     # HOLD / CLOSE_WEAKEST / ADD_WATCHLIST
        self.todays_ph8_watchlist_add: List[str] = []  # symbols Claude wants added to PH8
        self._last_heartbeat_time: Optional[datetime] = None  # track 25-min interval

        # Live market data slot — kept fresh by orchestrator every 60s via _get_live_market_data()
        self._live_nifty_chg: str = 'N/A'       # Nifty % change from prev close (string with sign)
        self._live_nifty_curr: float = None      # Current Nifty price (absolute)
        self._live_nifty_direction: str = 'N/A'  # 'rising' | 'falling' | 'flat' (intraday trend)
        self._live_vix:       str = 'N/A'        # India VIX last price

        # v1.5.0: Signal queue for batch heartbeat evaluation (cost saving)
        self._signal_queue: List[Dict] = []
        self._queue_mode: bool = getattr(config, 'PH9_QUEUE_MODE_ENABLED', False)

        # v1.6.0: Phase-specific tuning parameters (set by morning briefing)
        self.todays_ph2_min_score: float = 55.0        # PH2 composite score threshold
        self.todays_ph5a_sensitivity: str = 'normal'   # tight / normal / loose
        self.todays_ph8_momentum_threshold: float = 3.0  # min weekly return % to qualify

        # v1.6.0: Per-phase P&L attribution (populated during day via record_trade_pnl)
        self._phase_pnl_today: Dict[str, float] = {}
        self._phase_trade_count: Dict[str, int] = {}

        # Daily P&L tracking
        self.daily_pnl = 0.0
        self.trades_today = 0
        self.entries_approved = 0
        self.entries_blocked = 0
        self.exits_advised = 0

        # Decision journal (in-memory, flushed at EOD)
        self.decision_journal: List[Dict] = []

        # Safety rails
        self.max_daily_loss = getattr(config, 'PH9_MAX_DAILY_LOSS', -5000)
        self.max_position_size = getattr(config, 'PH9_MAX_POSITION_SIZE', 100000)
        self.max_open_positions = getattr(config, 'PH9_MAX_POSITIONS', 5)
        self.claude_timeout = getattr(config, 'PH9_CLAUDE_TIMEOUT', 8.0)
        self.min_entry_confidence = getattr(config, 'PH9_ENTRY_MIN_CONFIDENCE', 65)

        # ═══════════════════════════════════════════════════════════════════
        # COST OPTIMIZATION (v1.1.0)
        # ═══════════════════════════════════════════════════════════════════

        # Gray-zone gating: skip Claude for obviously good/bad trades
        # Score > upper → auto-approve (skip Claude)
        # Score < lower → auto-reject (skip Claude)
        # lower <= score <= upper → call Claude
        self.gate_score_lower = getattr(config, 'PH9_ENTRY_GATE_SCORE_LOWER', 50)
        self.gate_score_upper = getattr(config, 'PH9_ENTRY_GATE_SCORE_UPPER', 75)

        # Daily budget hard stop
        self.max_daily_api_cost = getattr(config, 'PH9_MAX_DAILY_API_COST_INR', 15.0)
        self.max_daily_call_count = getattr(config, 'PH9_DAILY_CALL_COUNT_MAX', 30)

        # Token limits (aggressive truncation)
        self.max_prompt_tokens_gate = getattr(config, 'PH9_GATE_MAX_PROMPT_TOKENS', 500)
        self.max_response_tokens_gate      = getattr(config, 'PH9_GATE_MAX_RESPONSE_TOKENS', 200)
        self.max_response_tokens_heartbeat = getattr(config, 'PH9_HEARTBEAT_MAX_RESPONSE_TOKENS', 600)
        self.max_prompt_tokens_strategic = getattr(config, 'PH9_STRATEGIC_MAX_PROMPT_TOKENS', 1500)
        self.max_response_tokens_strategic = getattr(config, 'PH9_STRATEGIC_MAX_RESPONSE_TOKENS', 1500)

        # Cost tracking
        self.daily_api_cost_inr = 0.0
        self.daily_api_calls = 0
        self.cost_by_type = {}  # {'morning_briefing': 3.0, 'entry_gate': 0.5, ...}
        self.budget_exhausted = False

        # ═══════════════════════════════════════════════════════════════════
        # PERSISTENT MEMORY (v3.0.0) — Rolling history + Structured lessons
        # Lessons are now dicts with type, confidence, validation tracking.
        # ═══════════════════════════════════════════════════════════════════
        self.memory_enabled = getattr(config, 'PH9_MEMORY_ENABLED', True)
        self.memory_history_file = getattr(config, 'PH9_MEMORY_HISTORY_FILE',
                                           'ph9_memory.json')
        self.memory_history_days = getattr(config, 'PH9_MEMORY_HISTORY_DAYS', 3)
        # Legacy txt file kept for migration detection; new storage is JSON
        self.lessons_file_legacy = getattr(config, 'PH9_LESSONS_FILE', 'ph9_lessons.txt')
        self.lessons_file = getattr(config, 'PH9_LESSONS_FILE_JSON', 'ph9_lessons.json')
        self.lessons_max_count = getattr(config, 'PH9_LESSONS_MAX_COUNT', 30)
        self.inject_lessons_into_gates = getattr(config, 'PH9_INJECT_LESSONS_INTO_GATES', True)
        self.rolling_history: List[Dict] = []  # Last-N-days list of summaries
        self.lessons: List[Dict] = []          # Structured lesson dicts (v3.0.0)
        if self.memory_enabled:
            try:
                self._load_memory()
                logger.info(f"🧠 PH9 memory loaded: {len(self.rolling_history)} days history, "
                            f"{len(self.lessons)} lessons")
            except Exception as _mem_e:
                logger.warning(f"PH9 memory load failed: {_mem_e}")

        logger.info("=" * 80)
        logger.info(f"🧠 PHASE 9: AI FUND MANAGER v{self.VERSION}")
        logger.info("=" * 80)
        logger.info(f"   Strategic Model: {self.model_sonnet}")
        logger.info(f"   Tactical Model:  {self.model_haiku}")
        logger.info(f"   Safety Rails:")
        logger.info(f"     Max Daily Loss: ₹{self.max_daily_loss:,.0f}")
        logger.info(f"     Max Position Size: ₹{self.max_position_size:,.0f}")
        logger.info(f"     Max Open Positions: {self.max_open_positions}")
        logger.info(f"     Min Entry Confidence: {self.min_entry_confidence}%")
        logger.info(f"   Cost Controls:")
        logger.info(f"     Daily API Budget: ₹{self.max_daily_api_cost:.0f}")
        logger.info(f"     Daily Call Limit: {self.max_daily_call_count}")
        logger.info(f"     Gray Zone Score: [{self.gate_score_lower}-{self.gate_score_upper}]")
        logger.info("=" * 80)

    # ═══════════════════════════════════════════════════════════════════════════
    # PERSISTENT MEMORY HELPERS (v1.2.0)
    # ═══════════════════════════════════════════════════════════════════════════

    def _load_memory(self) -> None:
        """Load rolling history JSON + structured lessons JSON from disk.
        Automatically migrates legacy ph9_lessons.txt to JSON on first load.
        """
        # Rolling history
        if os.path.exists(self.memory_history_file):
            try:
                with open(self.memory_history_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                hist = data.get('history', []) if isinstance(data, dict) else []
                self.rolling_history = hist[-self.memory_history_days:]
            except Exception as e:
                logger.warning(f"Corrupt memory file: {e}")
                self.rolling_history = []

        # Structured lessons (v3.0.0 JSON format)
        if os.path.exists(self.lessons_file):
            try:
                with open(self.lessons_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                self.lessons = data.get('lessons', [])
                if not isinstance(self.lessons, list):
                    self.lessons = []
                logger.info(f"🧠 Loaded {len(self.lessons)} structured lessons from {self.lessons_file}")
            except Exception as e:
                logger.warning(f"Corrupt lessons JSON: {e}")
                self.lessons = []

        # Migrate legacy txt file if JSON doesn't exist yet
        elif os.path.exists(self.lessons_file_legacy):
            try:
                with open(self.lessons_file_legacy, 'r', encoding='utf-8') as f:
                    raw = f.read().strip()
                old_lessons = [ln.strip() for ln in raw.split('\n')
                               if ln.strip() and not ln.strip().startswith('#')]
                today_str = date.today().isoformat()
                self.lessons = [
                    self._make_lesson_dict(text=ln, lesson_type='LEGACY',
                                           confidence=2, date_added=today_str,
                                           source_event='Migrated from ph9_lessons.txt')
                    for ln in old_lessons
                ]
                self._save_memory()
                logger.info(f"🧠 Migrated {len(self.lessons)} legacy lessons → {self.lessons_file}")
            except Exception as e:
                logger.warning(f"Legacy lessons migration failed: {e}")
                self.lessons = []

    def _make_lesson_dict(self, text: str, lesson_type: str = 'GENERAL',
                          confidence: int = 3, date_added: str = '',
                          source_event: str = '') -> Dict:
        """Create a new structured lesson dict."""
        import uuid as _uuid
        return {
            'id':                _uuid.uuid4().hex[:8],
            'text':              text,
            'type':              lesson_type,   # BIAS_DECISION|PHASE_GATE|SIGNAL_QUALITY|RISK_SIZING|TIMING|CODE_BUG|LEGACY|GENERAL
            'confidence':        confidence,    # 1-5 (5=very certain, 1=speculative)
            'date_added':        date_added or date.today().isoformat(),
            'date_last_validated': '',
            'times_applied':     0,
            'times_helped':      0,
            'times_hurt':        0,
            'source_event':      source_event,
        }

    def _save_memory(self) -> None:
        """Persist rolling history + structured lessons to disk."""
        try:
            payload = {'version': '3.0.0',
                       'updated': datetime.now().isoformat(),
                       'history': self.rolling_history[-self.memory_history_days:]}
            with open(self.memory_history_file, 'w', encoding='utf-8') as f:
                json.dump(payload, f, indent=2, default=str)
        except Exception as e:
            logger.warning(f"Memory save failed: {e}")
        try:
            payload = {
                'version': '3.0.0',
                'updated': datetime.now().isoformat(),
                'count': len(self.lessons),
                'lessons': self.lessons[:self.lessons_max_count]
            }
            with open(self.lessons_file, 'w', encoding='utf-8') as f:
                json.dump(payload, f, indent=2, default=str)
        except Exception as e:
            logger.warning(f"Lessons save failed: {e}")

    def _append_today_to_history(self, day_summary: Dict) -> None:
        """Append today's compact summary to rolling history; prune to N days."""
        if not self.memory_enabled:
            return
        try:
            entry = {
                'date': date.today().isoformat(),
                'regime': self.todays_regime,
                'pnl': round(float(day_summary.get('total_pnl', self.daily_pnl) or 0), 2),
                'trades': int(day_summary.get('trade_count', self.trades_today) or 0),
                'approved': self.entries_approved,
                'blocked': self.entries_blocked,
                'wins': sum(1 for t in day_summary.get('trades', []) if t.get('pnl', 0) > 0),
                'losses': sum(1 for t in day_summary.get('trades', []) if t.get('pnl', 0) <= 0),
                'best': '', 'worst': '',
                'api_cost': round(self.daily_api_cost_inr, 2),
            }
            _trades = day_summary.get('trades', []) or []
            if _trades:
                _b = max(_trades, key=lambda t: t.get('pnl', 0))
                _w = min(_trades, key=lambda t: t.get('pnl', 0))
                entry['best'] = f"{_b.get('symbol','?')} {_b.get('pnl',0):+.0f}"
                entry['worst'] = f"{_w.get('symbol','?')} {_w.get('pnl',0):+.0f}"
            # Remove any existing entry for today (re-runs)
            self.rolling_history = [h for h in self.rolling_history
                                    if h.get('date') != entry['date']]
            self.rolling_history.append(entry)
            self.rolling_history = self.rolling_history[-self.memory_history_days:]
            self._save_memory()
        except Exception as e:
            logger.warning(f"History append failed: {e}")

    def _format_history_for_prompt(self) -> str:
        """Compact one-line-per-day history string for prompt injection."""
        if not self.rolling_history:
            return "(none)"
        lines = []
        for h in self.rolling_history:
            lines.append(
                f"{h.get('date')}: {h.get('regime','?')} "
                f"P&L=₹{h.get('pnl',0):+,.0f} trades={h.get('trades',0)} "
                f"(W{h.get('wins',0)}/L{h.get('losses',0)}) "
                f"best={h.get('best','-')} worst={h.get('worst','-')}")
        return "\n  ".join(lines)

    def _format_lessons_for_prompt(self, compact: bool = False) -> str:
        """Return lessons formatted for prompt injection, sorted by usefulness.

        v3.0.0: Structured lessons — sorted by confidence DESC then times_helped DESC.
        CODE_BUG lessons are separated into a special warning block.
        Compact mode returns a short pipe-separated string for gate prompts.
        """
        if not self.lessons:
            return "(none yet)"

        # Normalise: accept both legacy strings and new dicts
        def _to_dict(l):
            if isinstance(l, dict):
                return l
            return {'text': str(l), 'type': 'LEGACY', 'confidence': 2,
                    'times_helped': 0, 'times_applied': 0}

        all_lessons = [_to_dict(l) for l in self.lessons]

        # Split CODE_BUG from strategy lessons
        code_bugs    = [l for l in all_lessons if l.get('type') == 'CODE_BUG']
        strategy     = [l for l in all_lessons if l.get('type') != 'CODE_BUG']

        # Sort strategy lessons: confidence DESC, then times_helped DESC
        strategy.sort(key=lambda l: (l.get('confidence', 1), l.get('times_helped', 0)), reverse=True)

        if compact:
            # Compact: top 8 highest-confidence strategy lessons only
            top = strategy[:8]
            return " | ".join(f"[conf={l.get('confidence',1)}] {l['text']}" for l in top)

        lines = []

        # CODE_BUG section — always at the top so Claude sees them first
        if code_bugs:
            lines.append("  ⚠ KNOWN CODE ISSUES (flag for developer fix, do not route around in-session):")
            for l in code_bugs:
                conf_str = f"conf={l.get('confidence',1)}/5"
                lines.append(f"    🚨 [{conf_str}] {l['text']}")

        if strategy:
            lines.append("  STRATEGY LESSONS (apply to today's decisions):")
            for l in strategy:
                conf = l.get('confidence', 1)
                times_a = l.get('times_applied', 0)
                times_h = l.get('times_helped', 0)
                ltype   = l.get('type', 'GENERAL')
                # High confidence (4-5): show with validation stats
                if conf >= 4:
                    lines.append(
                        f"    ✅ [conf={conf}/5 | {ltype} | applied={times_a} helped={times_h}] {l['text']}"
                    )
                elif conf >= 3:
                    lines.append(f"    • [conf={conf}/5 | {ltype}] {l['text']}")
                else:
                    # Low confidence: show in background, smaller weight
                    lines.append(f"    ~ [conf={conf}/5 | tentative] {l['text']}")

        return "\n".join(lines) if lines else "(none yet)"

    def _extract_lessons_from_eod(self, eod_result: Dict) -> None:
        """Parse structured lessons from EOD review response and merge into lessons list.

        v3.0.0: Each lesson is now a dict with type, confidence, source_event.
        Backward compat: plain strings are accepted and tagged as GENERAL/confidence=2.
        """
        if not self.memory_enabled:
            return
        try:
            today_str = date.today().isoformat()
            new_lessons_raw = eod_result.get('new_lessons') or eod_result.get('lessons') or []
            if isinstance(new_lessons_raw, str):
                new_lessons_raw = [x.strip() for x in re.split(r'[\n•;]', new_lessons_raw) if x.strip()]
            if not isinstance(new_lessons_raw, list):
                return

            existing_texts = [l.get('text', '').lower() if isinstance(l, dict) else l.lower()
                               for l in self.lessons]
            added = 0

            for raw in new_lessons_raw:
                # Accept both plain strings (legacy) and dicts (new structured format)
                if isinstance(raw, dict):
                    text         = str(raw.get('text', '')).strip().strip('"').strip("'").strip('-').strip()
                    lesson_type  = str(raw.get('type', 'GENERAL')).upper()
                    confidence   = max(1, min(5, int(raw.get('confidence', 3))))
                    source_event = str(raw.get('source_event', ''))[:200]
                elif isinstance(raw, str):
                    text         = raw.strip().strip('"').strip("'").strip('-').strip()
                    lesson_type  = 'GENERAL'
                    confidence   = 2
                    source_event = 'EOD auto-generated'
                else:
                    continue

                if not text or len(text) < 8 or len(text) > 300:
                    continue

                # Dedup: skip if very similar lesson already exists
                lower = text.lower()
                if any(lower in ex or ex in lower for ex in existing_texts):
                    continue

                lesson = self._make_lesson_dict(
                    text=text, lesson_type=lesson_type,
                    confidence=confidence, date_added=today_str,
                    source_event=source_event
                )
                self.lessons.append(lesson)
                existing_texts.append(lower)
                added += 1

                # CODE_BUG lessons always logged prominently
                if lesson_type == 'CODE_BUG':
                    logger.warning(f"🚨 PH9 CODE_BUG lesson recorded: {text}")

            # Enforce max count — drop oldest low-confidence lessons first
            if len(self.lessons) > self.lessons_max_count:
                self.lessons.sort(key=lambda l: (
                    l.get('confidence', 1) if isinstance(l, dict) else 1,
                    l.get('times_helped', 0) if isinstance(l, dict) else 0
                ))
                self.lessons = self.lessons[-(self.lessons_max_count):]

            if added:
                logger.info(f"🧠 PH9 learned {added} new lesson(s); total={len(self.lessons)}")
            self._save_memory()
        except Exception as e:
            logger.warning(f"Lesson extraction failed: {e}")

    def _validate_lessons_at_eod(self, eod_result: Dict) -> None:
        """Update lesson confidence scores based on today's validation feedback.

        EOD review returns 'lesson_validations': list of {lesson_id, applied, helped, note}.
        - applied=True + helped=True  → confidence += 1 (capped at 5)
        - applied=True + helped=False → confidence -= 1 (floored at 1)
        - applied=True (neutral)      → times_applied++
        Also bumps confidence for any CODE_BUG lesson that was fixed (helped=True).
        """
        if not self.memory_enabled:
            return
        try:
            validations = eod_result.get('lesson_validations', [])
            if not validations or not isinstance(validations, list):
                return

            lesson_index = {l.get('id'): l for l in self.lessons if isinstance(l, dict) and l.get('id')}
            updated = 0
            today_str = date.today().isoformat()

            for v in validations:
                lid = v.get('lesson_id', '')
                if lid not in lesson_index:
                    continue
                lesson = lesson_index[lid]
                applied = bool(v.get('applied', False))
                helped  = v.get('helped')  # True / False / None (neutral)

                if applied:
                    lesson['times_applied'] = lesson.get('times_applied', 0) + 1
                    lesson['date_last_validated'] = today_str
                    if helped is True:
                        lesson['times_helped'] = lesson.get('times_helped', 0) + 1
                        lesson['confidence']   = min(5, lesson.get('confidence', 3) + 1)
                    elif helped is False:
                        lesson['times_hurt']  = lesson.get('times_hurt', 0) + 1
                        lesson['confidence']  = max(1, lesson.get('confidence', 3) - 1)
                    updated += 1

            if updated:
                logger.info(f"🧠 PH9 validated {updated} lesson(s) — confidences updated")
                self._save_memory()
        except Exception as e:
            logger.warning(f"Lesson validation failed: {e}")

    def _prune_stale_lessons(self, weekly_result: Dict) -> None:
        """Weekly review can return 'drop_lessons' indices or substrings to remove."""
        if not self.memory_enabled or not weekly_result:
            return
        try:
            drops = weekly_result.get('drop_lessons', [])
            if not drops:
                return
            before = len(self.lessons)
            kept = []
            for ln in self.lessons:
                drop = False
                ln_text = ln.get('text', '') if isinstance(ln, dict) else str(ln)
                ln_id   = ln.get('id', '')   if isinstance(ln, dict) else ''
                for d in drops:
                    if isinstance(d, int) and 0 <= d < before and self.lessons[d] is ln:
                        drop = True
                        break
                    if isinstance(d, str):
                        # Match by lesson ID or text substring
                        if (ln_id and d == ln_id) or (d.lower() in ln_text.lower()):
                            drop = True
                            break
                if not drop:
                    kept.append(ln)
            if len(kept) != before:
                self.lessons = kept
                logger.info(f"🧠 PH9 pruned {before - len(kept)} stale lesson(s)")
                self._save_memory()
        except Exception as e:
            logger.warning(f"Lesson prune failed: {e}")

    # ═══════════════════════════════════════════════════════════════════════════
    # LEVEL 1: MORNING BRIEFING (Pre-Market)
    # ═══════════════════════════════════════════════════════════════════════════

    def morning_briefing(self, market_data: Dict) -> Dict:
        """
        Pre-market strategic briefing. Called once before market open.

        Claude receives:
            - Previous day P&L and trade summary
            - Current open positions (CNC holds)
            - Market indicators (Nifty, VIX, FII/DII, sector heatmap)
            - Capital available
            - PMBI (Pre-Market Breadth Intelligence) if available

        Claude returns:
            - Operation mode: NORMAL / CAUTIOUS / AGGRESSIVE / HALT
            - Max positions for today
            - Size multiplier (0.5x to 1.5x)
            - Phases to keep active
            - Watchlist priorities
            - Risk notes

        Args:
            market_data: Dict with keys like 'nifty_close', 'vix', 'fii_dii',
                        'open_positions', 'yesterday_pnl', 'capital_available',
                        'pmbi', 'sector_heatmap'

        Returns:
            Dict with strategic directives
        """
        today = date.today()
        if self._morning_briefing_date == today and self._morning_briefing_done:
            logger.info("Morning briefing already completed today — skipping")
            return self._get_current_directives()

        if not self._claude_available():
            logger.warning("Claude unreachable (network/DNS) — using default directives")
            # Mark done so orchestrator doesn't retry every loop iteration
            self._morning_briefing_done = True
            self._morning_briefing_date = today
            return self._get_default_directives()

        logger.info("=" * 80)
        logger.info("☀️  PHASE 9: MORNING BRIEFING")
        logger.info("=" * 80)

        # Build prompt
        prompt = self._build_morning_prompt(market_data)

        try:
            response = self.client.messages.create(
                model=self.model_sonnet,
                system=self._get_fund_manager_system_prompt(),
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=self.max_response_tokens_strategic
            )

            # Track cost
            self._track_cost(self.model_sonnet, getattr(response, 'usage', None),
                             'morning_briefing')

            content = response.content[0].text
            result = self._extract_json(content)

            # Apply directives with safety clamps
            self.todays_regime = result.get('operation_mode', 'NORMAL')
            if self.todays_regime == 'HALT':
                logger.warning("🛑 FUND MANAGER: HALT MODE — No new trades today")

            self.todays_max_positions = min(
                result.get('max_positions', self.max_open_positions),
                self.max_open_positions  # Safety: never exceed config max
            )

            # size_multiplier removed — each phase owns its own sizing
            # (VIX tier in orchestrator, ATR-based stops in PH5A, Kalman in PH4)
            self.todays_size_multiplier = 1.0

            self.todays_phases_active = result.get('phases_active',
                ['PH1', 'PH2', 'PH3', 'PH4', 'PH5', 'PH5A', 'PH8'])
            self.todays_notes = result.get('notes', '')

            # v1.4.0: Parse per-phase directives
            _phase_dirs = result.get('phase_directives', {})
            self.todays_ph5_directive  = str(_phase_dirs.get('PH5',  'ACTIVE')).upper()
            self.todays_ph5a_directive = str(_phase_dirs.get('PH5A', 'ACTIVE')).upper()
            self.todays_ph4_directive  = str(_phase_dirs.get('PH4',  'NORMAL')).upper()
            self.todays_ph6_directive  = str(_phase_dirs.get('PH6',  'ACTIVE')).upper()
            self.todays_ph8_directive  = str(_phase_dirs.get('PH8',  'HOLD')).upper()

            # PH8 watchlist additions from morning briefing
            _raw_wl = result.get('ph8_watchlist_add', [])
            if isinstance(_raw_wl, list):
                self.todays_ph8_watchlist_add = [str(s).upper() for s in _raw_wl if s]
            elif isinstance(_raw_wl, str) and _raw_wl.strip():
                self.todays_ph8_watchlist_add = [_raw_wl.strip().upper()]

            # v1.3.0: Extended directives — parse with safety clamps
            self.todays_market_bias = result.get('market_bias', 'NEUTRAL').upper()
            if self.todays_market_bias not in ('BULLISH', 'BEARISH', 'NEUTRAL'):
                self.todays_market_bias = 'NEUTRAL'

            self.todays_vix_regime = result.get('vix_regime', 'NORMAL').upper()
            if self.todays_vix_regime not in ('LOW', 'NORMAL', 'HIGH', 'EXTREME'):
                self.todays_vix_regime = 'NORMAL'

            # v1.8.0: VIX-tiered PH5 params (Claude can hint; orchestrator enforces via _get_vix_tier_params)
            self.todays_ph5_size_mult = max(0.25, min(1.0,
                float(result.get('ph5_size_mult', 1.0) or 1.0)))
            self.todays_ph5_stop_mult = max(1.0, min(2.0,
                float(result.get('ph5_stop_mult', 1.0) or 1.0)))

            raw_focus = result.get('sector_focus', [])
            self.todays_sector_focus = [s.upper() for s in raw_focus if isinstance(s, str)][:3]

            raw_avoid = result.get('sector_avoid', [])
            self.todays_sector_avoid = [s.upper() for s in raw_avoid if isinstance(s, str)][:2]

            raw_window = result.get('entry_window_start', '09:15')
            import re as _re
            self.todays_entry_window = (raw_window if isinstance(raw_window, str)
                                        and _re.match(r'^\d{2}:\d{2}$', raw_window)
                                        else '09:15')

            self.todays_stop_atr_mult = max(0.5, min(2.0,
                float(result.get('stop_atr_multiplier', 1.0) or 1.0)))

            self.todays_target_atr_mult = max(0.5, min(2.5,
                float(result.get('target_atr_multiplier', 1.0) or 1.0)))

            self.todays_exit_aggression = result.get('exit_aggression', 'NORMAL').upper()
            if self.todays_exit_aggression not in ('EARLY', 'NORMAL', 'HOLD'):
                self.todays_exit_aggression = 'NORMAL'

            self.todays_ph6_options_bias = result.get('ph6_options_bias', 'NEUTRAL').upper()
            if self.todays_ph6_options_bias not in ('CALL', 'PUT', 'NEUTRAL'):
                self.todays_ph6_options_bias = 'NEUTRAL'

            self.todays_risk_level = result.get('risk_level', 'MEDIUM').upper()
            if self.todays_risk_level not in ('LOW', 'MEDIUM', 'HIGH'):
                self.todays_risk_level = 'MEDIUM'

            self.todays_confidence = int(min(100, max(0,
                int(result.get('confidence', 70) or 70))))

            # v1.6.0: Phase-specific tuning parameters
            self.todays_ph2_min_score = float(max(40.0, min(80.0,
                float(result.get('ph2_min_score', 55.0) or 55.0))))
            _ph5a_sens = str(result.get('ph5a_sensitivity', 'normal')).lower()
            self.todays_ph5a_sensitivity = _ph5a_sens if _ph5a_sens in ('tight', 'normal', 'loose') else 'normal'
            self.todays_ph8_momentum_threshold = float(max(1.0, min(10.0,
                float(result.get('ph8_momentum_threshold', 3.0) or 3.0))))

            # v1.7.0: Forward plan fields — stored for heartbeat context + Telegram
            self.todays_day_plan          = result.get('day_plan', '')
            self.todays_unlock_conditions = result.get('unlock_conditions', '')
            self.todays_watch_stocks      = result.get('watch_stocks', '')

            self._morning_briefing_done = True
            self._morning_briefing_date = today

            # Log
            logger.info(f"   Regime: {self.todays_regime} | Risk: {self.todays_risk_level} | Confidence: {self.todays_confidence}%")
            logger.info(f"   Market Bias: {self.todays_market_bias} | VIX Regime: {self.todays_vix_regime}")
            logger.info(f"   Max Positions: {self.todays_max_positions}")
            logger.info(f"   Entry Window: >= {self.todays_entry_window}")
            logger.info(f"   Stop ATR Mult: {self.todays_stop_atr_mult:.2f}x | Target ATR Mult: {self.todays_target_atr_mult:.2f}x | Exit: {self.todays_exit_aggression}")
            logger.info(f"   PH6 Options Bias: {self.todays_ph6_options_bias}")
            logger.info(f"   Sector Focus: {self.todays_sector_focus or 'ALL'} | Avoid: {self.todays_sector_avoid or 'NONE'}")
            logger.info(f"   Active Phases: {', '.join(self.todays_phases_active)}")
            logger.info(f"   PH2 min score: {self.todays_ph2_min_score} | PH5A sensitivity: {self.todays_ph5a_sensitivity} | PH8 momentum: {self.todays_ph8_momentum_threshold}%")
            logger.info(f"   Notes: {self.todays_notes[:200]}")

            # Journal
            self._journal('MORNING_BRIEFING', 'PORTFOLIO', result)

            # Telegram
            if self.telegram:
                focus_str = ', '.join(self.todays_sector_focus) if self.todays_sector_focus else 'ALL'
                avoid_str = ', '.join(self.todays_sector_avoid) if self.todays_sector_avoid else 'none'
                _e  = _html.escape
                def _tw(text: str, limit: int = 300) -> str:
                    """Truncate at word boundary with ellipsis if cut."""
                    if len(text) <= limit:
                        return _e(text)
                    return _e(text[:limit].rsplit(' ', 1)[0] + '…')
                _brief_msg = (
                    f"☀️ ALPHA — MORNING BRIEFING\n"
                    f"{'─'*32}\n"
                    f"Regime : {self.todays_regime} | Risk: {self.todays_risk_level} | Confidence: {self.todays_confidence}%\n"
                    f"Bias   : {self.todays_market_bias} | VIX: {self.todays_vix_regime}\n"
                    f"Max pos: {self.todays_max_positions}\n"
                    f"Entry  : >= {self.todays_entry_window} | Exit: {self.todays_exit_aggression}\n"
                    f"Stops  : {self.todays_stop_atr_mult:.2f}x ATR | Tgt: {self.todays_target_atr_mult:.2f}x ATR\n"
                    f"Focus  : {focus_str} | Avoid: {avoid_str}\n"
                    f"PH2 score≥{self.todays_ph2_min_score:.0f} | PH5A: {self.todays_ph5a_sensitivity}\n"
                    f"Phases : {', '.join(self.todays_phases_active)}\n"
                    f"\n📊 READ:\n{_tw(self.todays_notes)}\n"
                )
                if self.todays_day_plan:
                    _brief_msg += f"\n📅 TODAY'S PLAN:\n{_tw(self.todays_day_plan)}\n"
                if self.todays_unlock_conditions:
                    _brief_msg += f"\n🔓 UNLOCK CONDITIONS:\n{_tw(self.todays_unlock_conditions)}\n"
                if self.todays_watch_stocks:
                    _brief_msg += f"\n👁 WATCH:\n{_tw(self.todays_watch_stocks)}\n"
                self.telegram.send_message(_brief_msg)

            # DB log
            self._log_to_db('MORNING_BRIEFING', 'PORTFOLIO', market_data, result, prompt[:500])

            return result

        except Exception as e:
            logger.error(f"Morning briefing failed: {e}")
            logger.error(traceback.format_exc())
            self._morning_briefing_done = True
            self._morning_briefing_date = today
            return self._get_default_directives()

    # ═══════════════════════════════════════════════════════════════════════════
    # LEVEL 1B: MIDDAY SANITY CHECK (v1.1.0)
    # ═══════════════════════════════════════════════════════════════════════════

    def midday_check(self, market_data: Dict) -> Dict:
        """
        One-shot mid-day reassessment (12:00 PM). Cheap (Haiku).
        Can downgrade regime (e.g. NORMAL → CAUTIOUS) if the day's P&L or
        market conditions have deteriorated. Cannot upgrade to AGGRESSIVE.
        """
        today = date.today()
        if getattr(self, '_midday_check_date', None) == today and getattr(self, '_midday_check_done', False):
            return self._get_current_directives()
        self._midday_check_done = True
        self._midday_check_date = today

        if not self._claude_available():
            return self._get_current_directives()
        if getattr(self, 'budget_exhausted', False):
            logger.info("🧠 PH9 midday: budget exhausted — skipping")
            return self._get_current_directives()

        logger.info("🧠 PH9 MIDDAY CHECK (12:00 PM)")
        prompt = (f"MIDDAY CHECK — {datetime.now().strftime('%H:%M')}\n"
                  f"Regime: {self.todays_regime}\n"
                  f"Daily P&L: ₹{self.daily_pnl:+,.0f} / limit ₹{self.max_daily_loss:,.0f}\n"
                  f"Trades: {self.trades_today} | Approved:{self.entries_approved} Blocked:{self.entries_blocked}\n"
                  f"Open positions: {len((market_data or {}).get('open_positions', {}))}\n"
                  f"Nifty: {(market_data or {}).get('nifty_change_pct', 'N/A')}% | VIX: {(market_data or {}).get('vix', 'N/A')}\n\n"
                  f"Should the afternoon session continue? JSON only:\n"
                  f'{{"new_regime":"NORMAL|CAUTIOUS|HALT","reasoning":"<=20 words"}}')
        try:
            response = self.client.messages.create(
                model=self.model_haiku,
                system=self._get_fund_manager_system_prompt_short(),
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
                max_tokens=self.max_response_tokens_gate,
            )
            self._track_cost(self.model_haiku, getattr(response, 'usage', None), 'midday_check')
            result = self._extract_json(response.content[0].text)
            new_regime = result.get('new_regime', self.todays_regime)
            # Only allow risk-increases: AGGRESSIVE→NORMAL→CAUTIOUS→HALT
            # AGGRESSIVE=-1 (least restrictive), HALT=2 (most restrictive)
            # BUG-FIX: was {'NORMAL':0,'AGGRESSIVE':0} → both 0 meant AGGRESSIVE→NORMAL was blocked
            downgrade_order = {'AGGRESSIVE': -1, 'NORMAL': 0, 'CAUTIOUS': 1, 'HALT': 2}
            if downgrade_order.get(new_regime, 0) > downgrade_order.get(self.todays_regime, -1):
                logger.warning(f"🧠 PH9 MIDDAY: regime downgrade {self.todays_regime} → {new_regime}")
                self.todays_regime = new_regime
                if self.telegram:
                    self.telegram.send_message(
                        f"⚠️ PH9 MIDDAY: {new_regime}\n"
                        f"{result.get('reasoning', '')[:200]}")
            return result
        except Exception as e:
            logger.error(f"Midday check failed: {e}")
            return self._get_current_directives()

    # ═══════════════════════════════════════════════════════════════════════════
    # LEVEL 3: 25-MINUTE HEARTBEAT (Intraday full portfolio review)
    # ═══════════════════════════════════════════════════════════════════════════

    def heartbeat_brief(self, system_state: Dict) -> Dict:
        """
        25-minute intraday heartbeat. Haiku call (~₹0.20 each, ~₹2/day max).
        Re-reads full portfolio state and can update phase directives mid-session.
        Can downgrade/upgrade directives but cannot override hard safety rails.

        Args:
            system_state: Full portfolio + market snapshot from orchestrator

        Returns:
            Dict with updated directives + any position_actions
        """
        now = datetime.now()

        if not self._morning_briefing_done:
            logger.debug("Heartbeat skipped — morning briefing not done yet")
            return {}

        if not self._claude_available():
            logger.debug("Heartbeat skipped — Claude not reachable")
            return {}

        if getattr(self, 'budget_exhausted', False):
            logger.debug("Heartbeat skipped — budget exhausted")
            return {}

        logger.info("🧠 PH9 HEARTBEAT — 25-min portfolio review")

        # Build compact prompt
        _positions = system_state.get('open_positions', {})
        _pos_lines = []
        for sym, pos in list(_positions.items())[:8]:  # cap at 8 positions
            _entry = pos.get('entry_price', 0)
            _cur   = pos.get('current_price', _entry)
            _pnl_p = ((_cur - _entry) / _entry * 100) if _entry else 0
            _dir   = pos.get('direction', 'LONG')
            if _dir.upper() in ('SHORT', 'SELL'):
                _pnl_p = -_pnl_p
            # Kalman velocity — earliest reversal signal
            _tracking = pos.get('phase4_tracking', {})
            _kalman = _tracking.get('kalman_state', {})
            _vel = _kalman.get('velocity', None)
            _vel_str = f" vel={_vel:+.2f}" if _vel is not None else ''
            # Time held — context for whether trade has had fair chance
            _entry_time = pos.get('entry_time', None)
            _held_str = ''
            if _entry_time:
                try:
                    _et = datetime.fromisoformat(_entry_time) if isinstance(_entry_time, str) else _entry_time
                    _held_min = int((now - _et).total_seconds() / 60)
                    _held_str = f" held={_held_min}min"
                except Exception:
                    pass
            # Stop distance
            _stop = pos.get('stop_price', 0)
            _stop_str = f" SL=₹{_stop:.0f}" if _stop else ''
            _pos_lines.append(
                f"  {sym}: {_dir} ₹{_entry:.0f}→₹{_cur:.0f} ({_pnl_p:+.1f}%){_vel_str}{_held_str}{_stop_str}"
            )

        _pos_str = '\n'.join(_pos_lines) or '  (none)'

        # v1.5.0: Include queued signals for batch evaluation
        _queued = self._signal_queue[:6]  # cap at 6 to stay within token budget
        _queued_summary = [
            {'symbol':    q['symbol'],
             'direction': q['direction'],
             'score':     q.get('score', '?'),
             'source':    q.get('source', '?'),
             'entry':     round(q['entry_price'], 2),
             'stop':      round(q['stop_price'], 2),
             'target':    round(q['target_price'], 2),
             'qty':       q['quantity']}
            for q in _queued
        ]
        _queued_str = json.dumps(_queued_summary, default=str)[:600] if _queued else '[]'
        _queue_instruction = (
            f"\nQUEUED SIGNALS TO EVALUATE ({len(_queued)}): {_queued_str}\n"
            f"For each queued signal decide approve/reject based on current market context."
            if _queued else "\nQUEUED SIGNALS: none\n"
        )

        # v1.7.0: monitors snapshot for opportunity scanning
        _monitors = system_state.get('monitors', [])
        _mon_str = ', '.join(
            f"{m['symbol']} RSI={m.get('rsi','?')} ({m.get('state','?')})"
            for m in _monitors[:6]
        ) or 'none'

        # v2.0.0: Load phase knowledge for intelligent orchestration decisions
        _phase_ref = self._load_phase_knowledge_compact()

        prompt = (
            f"HEARTBEAT — {now.strftime('%H:%M')} IST\n"
            f"Regime: {self.todays_regime} | Bias: {self.todays_market_bias} | "
            f"P&L: ₹{self.daily_pnl:+,.0f} | "
            f"Trades: {self.trades_today} | Approved:{self.entries_approved} Blocked:{self.entries_blocked}\n"
            f"Capital deployed: {system_state.get('capital_deployed_pct', 0):.0f}%\n"
            f"Nifty: {system_state.get('nifty_change_pct', 'N/A')}% | "
            f"VIX: {system_state.get('vix', 'N/A')} | "
            f"Breadth: {system_state.get('market_breadth', 'N/A')}\n"
            f"Monitors: {_mon_str}\n"
            f"\nOPEN POSITIONS:\n{_pos_str}\n"
            f"{_queue_instruction}\n"
            f"Current directives: PH5={self.todays_ph5_directive} "
            f"PH5A={self.todays_ph5a_directive} PH4={self.todays_ph4_directive} "
            f"PH2_interval={system_state.get('ph2_interval_min', 5)}min\n"
            f"{_phase_ref}\n"
            f"\nYour job: (1) update directives if market conditions changed, "
            f"(2) identify developing setups, (3) request dynamic actions if needed — "
            f"e.g. RUN_PH1 for fresh stocks, RUN_PH2_EXTRA for immediate scan, "
            f"SET_PH2_INTERVAL:2 to scan every 2 min near a trigger.\n"
            f"\nReturn JSON:\n"
            f'{{"operation_mode":"NORMAL|CAUTIOUS|AGGRESSIVE|HALT",'
            f'"market_bias":"BULLISH|BEARISH|NEUTRAL",'
            f'"phase_directives":{{"PH5":"ACTIVE|SKIP","PH5A":"ACTIVE|PAUSE","PH4":"NORMAL|DEFENSIVE","PH6":"ACTIVE|HOLD"}},'
            f'"ph5_size_mult":<0.25-1.0 only if VIX changed — omit if unchanged>,'
            f'"ph5_stop_mult":<1.0-2.0 only if VIX changed — omit if unchanged>,'
            f'"next_cycle_actions":[],'
            f'"approved_signals":[],'
            f'"position_actions":[],'
            f'"ph8_watchlist_add":[],'
            f'"regime_change_justification":"REQUIRED if operation_mode differs from current ({self.todays_regime}). >=15 words citing Nifty %, VIX level, breadth, and why the shift is warranted now. Leave empty string if regime unchanged.",'
            f'"bias_change_justification":"REQUIRED if market_bias differs from current ({self.todays_market_bias}). >=10 words citing specific Nifty/VIX/breadth data. Leave empty string if bias unchanged.",'
            f'"situation":"<=40 words: market read and why directives set this way",'
            f'"watching":"<=25 words: exact levels being watched",'
            f'"opportunity":"<=25 words: setup developing, what needs to happen",'
            f'"next_action":"<=25 words: exact trigger for regime change or trade"}}\n'
            f"\nYou have FULL authority to change regime and bias in either direction. "
            f"Do not be artificially cautious — read the live data and decide like a pro trader. "
            f"If Nifty is strongly positive and VIX stable, upgrading CAUTIOUS→NORMAL or "
            f"NEUTRAL→BULLISH is the correct call; justify it in the respective justification field. "
            f"IMPORTANT: if morning briefing set bias to BULLISH, do NOT flip to NEUTRAL unless "
            f"you have specific live data (Nifty reversal, VIX spike, breadth deterioration) to back it."
        )

        try:
            response = self.client.messages.create(
                model=self.model_haiku,
                system=self._get_fund_manager_system_prompt_short(),
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
                max_tokens=self.max_response_tokens_heartbeat,
            )
            self._track_cost(self.model_haiku, getattr(response, 'usage', None), 'heartbeat')
            result = self._extract_json(response.content[0].text)

            # v2.2.0: Claude has full bidirectional authority over regime.
            # Safety net: ANY regime change requires a justification >=15 words citing
            # Nifty/VIX/breadth. If Claude didn't justify, the change is rejected — this
            # blocks sloppy flips without blocking genuine reasoning.
            _valid_regimes = ('AGGRESSIVE', 'NORMAL', 'CAUTIOUS', 'HALT')
            _new_regime = str(result.get('operation_mode', self.todays_regime)).upper()
            if _new_regime in _valid_regimes and _new_regime != self.todays_regime:
                _justification = str(result.get('regime_change_justification', '')).strip()
                _jus_words = len(_justification.split())
                _lc = _justification.lower()
                _cites_data = any(k in _lc for k in ('nifty', 'vix', 'breadth', 'fii', 'dii'))
                if _jus_words >= 15 and _cites_data:
                    logger.warning(
                        f"🧠 PH9 Heartbeat regime: {self.todays_regime} → {_new_regime} "
                        f"| Justification: {_justification[:200]}"
                    )
                    self.todays_regime = _new_regime
                    if self.telegram:
                        self.telegram.send_message(
                            f"🔄 Regime shift: → {_new_regime}\n"
                            f"📝 {_justification[:300]}"
                        )
                else:
                    logger.warning(
                        f"🧠 Regime change {self.todays_regime}→{_new_regime} REJECTED — "
                        f"justification insufficient ({_jus_words} words, "
                        f"cites_data={_cites_data}): {_justification[:120]!r}"
                    )

            # Apply market_bias update — requires justification to prevent silent BULLISH→NEUTRAL freezes.
            # Root cause of 2026-04-21 zero-trade day: first heartbeat flipped BULLISH→NEUTRAL with
            # no data backing, and it stuck all day because there was no guard here.
            _new_bias = str(result.get('market_bias', '')).upper()
            if _new_bias in ('BULLISH', 'BEARISH', 'NEUTRAL') and _new_bias != self.todays_market_bias:
                _bias_just = str(result.get('bias_change_justification', '')).strip()
                _bias_words = len(_bias_just.split())
                _bias_cites = any(k in _bias_just.lower()
                                  for k in ('nifty', 'vix', 'breadth', 'fii', 'dii', 'falling', 'rising', 'reversal'))
                if _bias_words >= 10 and _bias_cites:
                    logger.info(
                        f"🧠 Heartbeat bias shift: {self.todays_market_bias} → {_new_bias} "
                        f"| Justification: {_bias_just[:200]}"
                    )
                    self.todays_market_bias = _new_bias
                    if self.telegram:
                        self.telegram.send_message(
                            f"🔄 Bias shift: {_new_bias}\n📝 {_bias_just[:300]}"
                        )
                else:
                    logger.warning(
                        f"🧠 Bias change {self.todays_market_bias}→{_new_bias} REJECTED — "
                        f"justification insufficient ({_bias_words} words, cites_data={_bias_cites}): "
                        f"{_bias_just[:120]!r} — keeping {self.todays_market_bias}"
                    )
            # If same bias, silently keep it (no log needed)

            # Apply per-phase directives (heartbeat can update any direction)
            _dirs = result.get('phase_directives', {})
            if _dirs.get('PH5'):  self.todays_ph5_directive  = str(_dirs['PH5']).upper()
            if _dirs.get('PH5A'): self.todays_ph5a_directive = str(_dirs['PH5A']).upper()
            if _dirs.get('PH4'):  self.todays_ph4_directive  = str(_dirs['PH4']).upper()
            if _dirs.get('PH6'):  self.todays_ph6_directive  = str(_dirs['PH6']).upper()
            if _dirs.get('PH8'):  self.todays_ph8_directive  = str(_dirs['PH8']).upper()

            # v1.8.0: VIX-tiered PH5 hints from heartbeat
            if result.get('ph5_size_mult') is not None:
                self.todays_ph5_size_mult = max(0.25, min(1.0, float(result['ph5_size_mult'])))
            if result.get('ph5_stop_mult') is not None:
                self.todays_ph5_stop_mult = max(1.0, min(2.0, float(result['ph5_stop_mult'])))

            # v2.2.0: Hardcoded VIX<19.5 / streak≥3 upgrade rule removed.
            # Claude now has direct bidirectional regime authority (see gate above).
            # No numeric heuristic should override the model's live read of the tape.

            # PH8 watchlist updates
            _raw_wl = result.get('ph8_watchlist_add', [])
            if isinstance(_raw_wl, list):
                for s in _raw_wl:
                    if s and str(s).upper() not in self.todays_ph8_watchlist_add:
                        self.todays_ph8_watchlist_add.append(str(s).upper())

            # v1.5.0: Log queued signal decisions
            _approved_sigs = result.get('approved_signals', [])
            if _approved_sigs:
                _ok  = sum(1 for a in _approved_sigs if a.get('approved'))
                _rej = len(_approved_sigs) - _ok
                logger.info(f"   🧠 Heartbeat signal verdicts: {_ok} approved, {_rej} rejected")
                for _a in _approved_sigs:
                    _verdict = "✅ APPROVED" if _a.get('approved') else "⛔ REJECTED"
                    logger.info(f"      {_verdict}: {_a.get('symbol','?')} — {_a.get('reasoning','')[:80]}")

            self._last_heartbeat_time = now
            reasoning = result.get('reasoning', '')
            logger.info(f"   🧠 Heartbeat: regime={self.todays_regime} "
                        f"PH5={self.todays_ph5_directive} PH5A={self.todays_ph5a_directive} "
                        f"PH4={self.todays_ph4_directive} | {reasoning[:100]}")

            if self.telegram:
                _pos_actions = result.get('position_actions', [])
                _action_str = ''
                if _pos_actions:
                    _action_str = '\n📌 Actions:\n' + '\n'.join(
                        f"  → {a.get('symbol','?')}: {a.get('action','?')} — {a.get('reason','')}"
                        for a in _pos_actions[:4])

                _sig_str = ''
                if _approved_sigs:
                    _sig_str = '\n📶 Signals: ' + ', '.join(
                        f"{'✅' if a.get('approved') else '⛔'}{a.get('symbol','?')}"
                        for a in _approved_sigs[:5])

                # Situation report fields — escape all Claude-generated text to avoid Telegram HTML errors
                def _trunc(text: str, limit: int) -> str:
                    """Truncate at word boundary; append … only if actually cut."""
                    if len(text) <= limit:
                        return text
                    cut = text[:limit].rsplit(' ', 1)[0]
                    return cut + '…'

                _e = _html.escape
                _situation   = _e(_trunc(result.get('situation', reasoning), 350))
                _watching    = _e(_trunc(result.get('watching', ''), 300))
                _opportunity = _e(_trunc(result.get('opportunity', ''), 300))
                _next_action = _e(_trunc(result.get('next_action', ''), 300))

                msg = (
                    f"🧠 ALPHA — {now.strftime('%H:%M')} SITUATION REPORT\n"
                    f"{'─'*32}\n"
                    f"Regime: {self.todays_regime} | P&L: ₹{self.daily_pnl:+,.0f} | Trades: {self.trades_today}\n"
                    f"PH4:{self.todays_ph4_directive} PH5:{self.todays_ph5_directive} "
                    f"PH5A:{self.todays_ph5a_directive} PH6:{self.todays_ph6_directive}\n"
                    f"\n📊 READ:\n{_situation}\n"
                )
                if _watching:
                    msg += f"\n👁 WATCHING:\n{_watching}\n"
                if _opportunity:
                    msg += f"\n💡 OPPORTUNITY:\n{_opportunity}\n"
                if _next_action:
                    msg += f"\n⚡ NEXT TRIGGER:\n{_next_action}\n"
                msg += _sig_str + _action_str

                self.telegram.send_message(msg)

            self._journal('HEARTBEAT', 'PORTFOLIO', result)
            return result

        except Exception as e:
            logger.error(f"Heartbeat failed: {e}")
            self._last_heartbeat_time = now  # prevent rapid retry
            return {}

    # ═══════════════════════════════════════════════════════════════════════════
    # LEVEL 1C: WEEKLY REVIEW (Sundays, v1.1.0)
    # ═══════════════════════════════════════════════════════════════════════════

    def weekly_review(self, week_summary: Dict) -> Dict:
        """
        Sunday strategic reset. Runs once per week. Uses Sonnet.
        Reviews past week's performance and generates next-week directives.
        """
        today = date.today()
        if getattr(self, '_weekly_review_date', None) == today:
            return {}
        # NOTE: done-flag set AFTER success (below) so transient failures can retry
        if not self._claude_available():
            return {}
        if getattr(self, 'budget_exhausted', False):
            return {}

        logger.info("=" * 80)
        logger.info("📅 PHASE 9: WEEKLY REVIEW")
        logger.info("=" * 80)

        # v1.2.0: feed history + current lessons so Claude can audit them
        hist_blk = ""
        lessons_blk = ""
        if self.memory_enabled:
            hist_blk = f"\nHISTORY:\n  {self._format_history_for_prompt()}\n"
            if self.lessons:
                numbered = "\n  ".join(f"[{i}] {l}" for i, l in enumerate(self.lessons))
                lessons_blk = (f"\nCURRENT LESSONS (review; propose indices/substrings to drop if stale):\n  {numbered}\n")

        prompt = (f"WEEKLY REVIEW — Week ending {today.strftime('%Y-%m-%d')}\n"
                  f"{hist_blk}{lessons_blk}\n"
                  f"Week P&L: ₹{week_summary.get('week_pnl', 0):+,.0f}\n"
                  f"Trades: {week_summary.get('trades_count', 0)} "
                  f"(W:{week_summary.get('wins', 0)}/L:{week_summary.get('losses', 0)})\n"
                  f"Best: {week_summary.get('best_trade', 'N/A')}\n"
                  f"Worst: {week_summary.get('worst_trade', 'N/A')}\n"
                  f"Phase P&L: {json.dumps(week_summary.get('phase_pnl', {}), default=str)[:400]}\n"
                  f"Exit reason mix: {json.dumps(week_summary.get('exit_reasons', {}), default=str)[:300]}\n\n"
                  f"Provide next-week strategic directive as JSON:\n"
                  f'{{"week_theme":"<short>","focus_phases":["PH3","PH5",...],'
                  f'"avoid_phases":[],"default_regime":"NORMAL|CAUTIOUS|AGGRESSIVE",'
                  f'"default_size_mult":0.5-1.3,"key_lessons":"<=50 words",'
                  f'"risk_notes":"<=30 words",'
                  f'"drop_lessons":[<indices or substrings of stale lessons to remove>],'
                  f'"new_lessons":[<0-2 NEW high-level weekly rules>]}}')

        try:
            response = self.client.messages.create(
                model=self.model_sonnet,
                system=self._get_fund_manager_system_prompt(),
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=self.max_response_tokens_strategic,
            )
            self._track_cost(self.model_sonnet, getattr(response, 'usage', None), 'weekly_review')
            result = self._extract_json(response.content[0].text)
            self.weekly_directive = result
            logger.info(f"   Week theme: {result.get('week_theme', 'N/A')}")
            logger.info(f"   Focus: {result.get('focus_phases', [])}")
            logger.info(f"   Default regime: {result.get('default_regime', 'NORMAL')}")
            # Mark done ONLY on success (allows retry on transient failure)
            self._weekly_review_date = today
            # v1.2.0: prune stale lessons + absorb any weekly new_lessons
            if self.memory_enabled:
                self._prune_stale_lessons(result)
                self._extract_lessons_from_eod(result)  # reuses new_lessons handler
            self._journal('WEEKLY_REVIEW', 'PORTFOLIO', result)
            if self.telegram:
                self.telegram.send_message(
                    f"📅 PH9 WEEKLY REVIEW\n\n"
                    f"Theme: {result.get('week_theme', 'N/A')}\n"
                    f"Regime: {result.get('default_regime', 'NORMAL')}\n"
                    f"Focus: {', '.join(result.get('focus_phases', []))}\n\n"
                    f"Lessons: {result.get('key_lessons', '')[:200]}\n"
                    f"Risks: {result.get('risk_notes', '')[:150]}")
            return result
        except Exception as e:
            logger.error(f"Weekly review failed: {e}")
            return {}

    # ═══════════════════════════════════════════════════════════════════════════
    # LEVEL 2A: TRADE APPROVAL GATE (Before every entry)
    # ═══════════════════════════════════════════════════════════════════════════

    def approve_entry(self, signal: Dict, current_price: float, quantity: int,
                      portfolio_state: Dict = None) -> Dict:
        """
        Gate check before Phase 3 places any order.

        Claude receives:
            - Stock symbol, direction, entry price
            - Composite score & breakdown (for gap trades)
            - Technical indicators (RSI, VWAP position, ATR)
            - Current portfolio (open positions, daily P&L)
            - Capital utilization
            - Signal source (PH5 gap / PH5A PVAT / PH2 swing)

        Claude returns:
            - approved: True/False
            - confidence: 0-100
            - size_adjustment: 0.5 to 1.5 (multiply suggested quantity)
            - stop_adjustment: None or new stop price
            - reasoning: text

        Safety rails checked FIRST (before Claude):
            - Daily loss limit
            - Max positions
            - Max position size
            - Regime HALT

        Args:
            signal: Entry signal dict from Phase 2/5/5A
            current_price: Current LTP
            quantity: Suggested quantity from Phase 3
            portfolio_state: Current portfolio snapshot

        Returns:
            Dict with 'approved', 'confidence', 'size_adjustment', 'reasoning'
        """
        symbol = signal.get('symbol', 'UNKNOWN')
        order_value = current_price * quantity

        # ═══════════════════════════════════════════════════════════════════
        # SAFETY RAILS — These override Claude (checked first, always)
        # ═══════════════════════════════════════════════════════════════════

        # Rail 1: HALT mode
        if self.todays_regime == 'HALT':
            reason = "HALT mode active — no new entries today"
            self._log_gate_decision(symbol, False, reason, 'SAFETY_RAIL')
            return {'approved': False, 'confidence': 0, 'size_adjustment': 1.0,
                    'reasoning': reason, 'gate': 'SAFETY_HALT'}

        # Rail 2: Daily loss circuit breaker
        if self.daily_pnl <= self.max_daily_loss:
            reason = f"Daily loss ₹{self.daily_pnl:,.0f} exceeds limit ₹{self.max_daily_loss:,.0f}"
            self._log_gate_decision(symbol, False, reason, 'SAFETY_RAIL')
            return {'approved': False, 'confidence': 0, 'size_adjustment': 1.0,
                    'reasoning': reason, 'gate': 'SAFETY_DAILY_LOSS'}

        # Rail 3: Max positions
        open_count = len(portfolio_state.get('positions', {})) if portfolio_state else 0
        if open_count >= self.todays_max_positions:
            reason = f"Max positions reached ({open_count}/{self.todays_max_positions})"
            self._log_gate_decision(symbol, False, reason, 'SAFETY_RAIL')
            return {'approved': False, 'confidence': 0, 'size_adjustment': 1.0,
                    'reasoning': reason, 'gate': 'SAFETY_MAX_POS'}

        # Rail 4: Max position size
        if order_value > self.max_position_size:
            reason = f"Position ₹{order_value:,.0f} exceeds max ₹{self.max_position_size:,.0f}"
            self._log_gate_decision(symbol, False, reason, 'SAFETY_RAIL')
            return {'approved': False, 'confidence': 0, 'size_adjustment': 1.0,
                    'reasoning': reason, 'gate': 'SAFETY_SIZE'}

        # ═══════════════════════════════════════════════════════════════════
        # AUTO-APPROVE — safety rails passed, each phase handles its own
        # sizing (VIX tier, ATR-based stops, Kalman). No Claude gate here.
        # ═══════════════════════════════════════════════════════════════════
        self.entries_approved += 1
        self._log_gate_decision(symbol, True, 'Safety rails passed — auto-approved', 'AUTO_APPROVED')
        return {
            'approved': True,
            'confidence': 100,
            'size_adjustment': 1.0,
            'reasoning': 'Safety rails passed — auto-approved',
            'gate': 'AUTO_APPROVED'
        }

    # ═══════════════════════════════════════════════════════════════════════════
    # LEVEL 2B: EXIT ADVISOR (Before exit execution)
    # ═══════════════════════════════════════════════════════════════════════════

    def advise_exit(self, symbol: str, position: Dict, exit_reason: str,
                    market_context: Dict = None) -> Dict:
        """
        Advisory check before Phase 4 executes an exit.

        NOTE: Hard stops (STOP_LOSS, MIS_CUTOFF, MARKET_CLOSE) are NEVER blocked.
        Claude can only advise on discretionary exits (TCAS_RA, TRAILING_STOP, CHATGPT_EXIT).

        Claude receives:
            - Position details (entry, current, P&L, duration)
            - Exit reason and TCAS level
            - Kalman state (velocity, acceleration)
            - Time remaining in session
            - Portfolio context

        Claude returns:
            - action: EXIT / HOLD / TRAIL
            - confidence: 0-100
            - new_stop: (if TRAIL) new stop price
            - reasoning: text

        Args:
            symbol: Stock symbol
            position: Full position dict
            exit_reason: Why Phase 4 wants to exit
            market_context: Additional market data

        Returns:
            Dict with 'action', 'confidence', 'reasoning'
        """
        # ═══════════════════════════════════════════════════════════════════
        # NON-NEGOTIABLE EXITS — Claude cannot override these
        # ═══════════════════════════════════════════════════════════════════

        hard_exit_reasons = [
            # Stop / mandatory exits
            'STOP_LOSS', 'MIS_CUTOFF', 'MIS_MANDATORY', 'MARKET_CLOSE',
            # TCAS emergency
            'TCAS_ALIM', 'HEALTH_CRITICAL', 'GO_AROUND',
            # System-triggered (non-negotiable)
            'GTT_TRIGGERED', 'GTT_EXTERNAL',
            # Target hit — profit is confirmed, don't question it
            'TARGET_HIT', 'TARGET',
            # ChatGPT already decided — no need for dual review
            'CHATGPT_EXIT',
            # Hard-coded TIER1 exits
            'TIER1_HARD_STOP', 'TIER1_FORCED_EXIT',
            # Manual overrides
            'MANUAL', 'EMERGENCY', 'CIRCUIT',
        ]

        reason_upper = exit_reason.upper()
        is_hard_exit = any(hr in reason_upper for hr in hard_exit_reasons)

        if is_hard_exit:
            logger.info(f"   🧠 Fund Manager: HARD EXIT — {symbol} ({exit_reason}) — no override")
            self.exits_advised += 1
            return {
                'action': 'EXIT',
                'confidence': 100,
                'reasoning': f'Hard exit ({exit_reason}) — non-negotiable',
                'gate': 'HARD_EXIT'
            }

        # Daily loss circuit breaker — if already deep, don't hold losers
        if self.daily_pnl <= self.max_daily_loss:
            logger.info(f"   🧠 Fund Manager: CIRCUIT BREAKER EXIT — daily loss ₹{self.daily_pnl:,.0f}")
            return {
                'action': 'EXIT',
                'confidence': 100,
                'reasoning': 'Circuit breaker — daily loss limit reached',
                'gate': 'SAFETY_CIRCUIT'
            }

        if not self._claude_available():
            return {'action': 'EXIT', 'confidence': 75,
                    'reasoning': 'Default exit (Claude unreachable)', 'gate': 'AUTO'}

        # ═══════════════════════════════════════════════════════════════════
        # CLAUDE ADVISORY (soft exits only: TCAS_RA, TRAILING, BREAKEVEN)
        # ═══════════════════════════════════════════════════════════════════

        try:
            prompt = self._build_exit_prompt(symbol, position, exit_reason, market_context)

            # v1.1.0: Use Haiku for tactical exit decisions
            response = self.client.messages.create(
                model=self.model_haiku,
                system=self._get_fund_manager_system_prompt_short(),
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
                max_tokens=self.max_response_tokens_gate
            )

            # Track cost
            self._track_cost(self.model_haiku, getattr(response, 'usage', None),
                             'exit_advisor')

            content = response.content[0].text
            result = self._extract_json(content)

            action = result.get('action', 'EXIT').upper()
            if action not in ('EXIT', 'HOLD', 'TRAIL'):
                action = 'EXIT'  # Default safe

            confidence = result.get('confidence', 50)
            reasoning = result.get('reasoning', '')

            self.exits_advised += 1

            logger.info(f"   🧠 Fund Manager EXIT ADVICE: {symbol}")
            logger.info(f"      Action: {action} (confidence: {confidence}%)")
            logger.info(f"      Reason: {reasoning[:150]}")

            self._journal('EXIT_ADVICE', symbol, result)
            self._log_to_db('EXIT_ADVICE', symbol,
                           {'position': str(position)[:500], 'exit_reason': exit_reason},
                           result, prompt[:500])

            # Telegram for HOLD decisions (unusual — worth alerting)
            if action == 'HOLD' and self.telegram:
                self.telegram.send_message(
                    f"🧠 FUND MANAGER — HOLD OVERRIDE\n\n"
                    f"Stock: {symbol}\n"
                    f"Original exit reason: {exit_reason}\n"
                    f"Claude says: HOLD ({confidence}%)\n"
                    f"Reasoning: {reasoning[:200]}"
                )

            return {
                'action': action,
                'confidence': confidence,
                'reasoning': reasoning,
                'new_stop': result.get('new_stop'),
                'gate': 'CLAUDE'
            }

        except anthropic.APITimeoutError:
            logger.warning(f"⏱️ Fund Manager exit timeout — defaulting to EXIT for {symbol}")
            return {'action': 'EXIT', 'confidence': 60,
                    'reasoning': 'Default exit (Claude timeout)', 'gate': 'TIMEOUT'}
        except Exception as e:
            logger.error(f"Fund Manager exit advisor error: {e}")
            return {'action': 'EXIT', 'confidence': 60,
                    'reasoning': f'Default exit (error: {str(e)[:100]})', 'gate': 'ERROR'}

    # ═══════════════════════════════════════════════════════════════════════════
    # ═══════════════════════════════════════════════════════════════════════════
    # LEVEL 2C: POSITION RECOVERY ADVISOR (v1.3.0)
    # Claude actively manages underwater positions to bring them to profit zone.
    # Called once per morning (after briefing) for each underwater position.
    # Claude mandate: "Land this trade in profit zone by any legitimate means."
    # ═══════════════════════════════════════════════════════════════════════════

    def recovery_advisor(self, symbol: str, position: Dict,
                         available_capital: float = 0,
                         market_data: Dict = None) -> Dict:
        """
        Per-position recovery consultation. Claude evaluates an underwater position
        and returns a concrete action plan to restore profitability.

        Claude can authorize:
          HOLD          — Keep position, tighten/widen stop, give it N more days
          AVERAGE       — Buy/sell more at a specific price to lower avg entry
          SCALE_OUT     — Exit N% of position now to reduce risk exposure
          CONVERT_CNC   — Convert MIS→CNC to hold overnight (margin check required)
          WIDEN_STOP    — Give position more breathing room (widen stop)
          EXIT          — Cut losses, move on

        Hard rails (enforced here, Claude cannot override):
          • P&L < RECOVERY_EJECT_PCT: always EXIT regardless
          • Days in recovery > RECOVERY_MAX_DAYS: always EXIT
          • Averaging: qty cap, capital cap, max-averages-per-position enforced
          • MIS→CNC: only if conversion time not past and margin available
        """
        # ── Load recovery config ──────────────────────────────────────────────
        cfg               = self.config
        trigger_pct       = getattr(cfg, 'PH9_RECOVERY_TRIGGER_PCT',    -2.0)
        eject_pct         = getattr(cfg, 'PH9_RECOVERY_EJECT_PCT',      -15.0)
        max_days          = getattr(cfg, 'PH9_RECOVERY_MAX_DAYS',        5)
        max_averages      = getattr(cfg, 'PH9_RECOVERY_MAX_AVERAGES',    1)
        avg_max_qty_pct   = getattr(cfg, 'PH9_RECOVERY_AVG_MAX_QTY_PCT', 100) / 100.0
        avg_capital_pct   = getattr(cfg, 'PH9_RECOVERY_AVG_CAPITAL_PCT', 20) / 100.0
        allow_cnc_conv    = getattr(cfg, 'PH9_RECOVERY_ALLOW_CNC_CONV',  True)
        cnc_conv_time     = getattr(cfg, 'PH9_RECOVERY_CNC_CONV_TIME',   dt_time(14, 30))

        entry_price   = float(position.get('entry_price', 0) or 0)
        current_price = float(position.get('current_price', entry_price) or entry_price)
        quantity      = int(position.get('quantity', 0) or 0)
        direction     = str(position.get('direction', 'LONG')).upper()
        product       = str(position.get('product', 'CNC')).upper()
        is_long       = direction in ('LONG', 'BUY')

        if entry_price <= 0 or quantity <= 0:
            return {'action': 'SKIP', 'reason': 'Invalid position data'}

        # Direction-aware P&L
        if is_long:
            pnl_pct = (current_price - entry_price) / entry_price * 100
        else:
            pnl_pct = (entry_price - current_price) / entry_price * 100

        # ── Trigger check: only engage if sufficiently underwater ─────────────
        if pnl_pct >= trigger_pct:
            return {'action': 'SKIP',
                    'reason': f'P&L {pnl_pct:.2f}% above trigger {trigger_pct}%'}

        # ── Recovery state tracking ───────────────────────────────────────────
        if not hasattr(self, '_recovery_state'):
            self._recovery_state = {}
        rs = self._recovery_state.setdefault(symbol, {
            'days_in_recovery': 0,
            'times_averaged': 0,
            'first_recovery_date': date.today().isoformat(),
            'history': [],
        })

        # Count today as a recovery day
        _today_str = date.today().isoformat()
        if rs.get('last_checked') != _today_str:
            rs['days_in_recovery'] = rs.get('days_in_recovery', 0) + 1
            rs['last_checked'] = _today_str

        # ── HARD RAIL 1: Eject if too deep ───────────────────────────────────
        if pnl_pct <= eject_pct:
            logger.warning(f"🚨 PH9 RECOVERY EJECT: {symbol} P&L {pnl_pct:.2f}% ≤ {eject_pct}% — forcing EXIT")
            rs['history'].append({'date': _today_str, 'action': 'FORCE_EXIT',
                                  'reason': f'P&L {pnl_pct:.2f}% breached eject threshold'})
            if self.telegram:
                self.telegram.send_message(
                    f"🚨 PH9 RECOVERY EJECT: {symbol}\n"
                    f"P&L {pnl_pct:.2f}% breached hard limit {eject_pct}%\n"
                    f"Forcing EXIT regardless of strategy.")
            return {'action': 'EXIT', 'confidence': 100,
                    'reason': f'Hard eject: P&L {pnl_pct:.2f}% ≤ {eject_pct}%',
                    'gate': 'HARD_EJECT'}

        # ── HARD RAIL 2: Eject if too many days in recovery ──────────────────
        if rs['days_in_recovery'] > max_days:
            logger.warning(f"🚨 PH9 RECOVERY TIMEOUT: {symbol} day {rs['days_in_recovery']} > {max_days} — forcing EXIT")
            rs['history'].append({'date': _today_str, 'action': 'TIMEOUT_EXIT',
                                  'reason': f'Day {rs["days_in_recovery"]} > {max_days} limit'})
            return {'action': 'EXIT', 'confidence': 100,
                    'reason': f'Recovery timeout: {rs["days_in_recovery"]} days > {max_days} limit',
                    'gate': 'TIMEOUT_EJECT'}

        # ── Budget/network check ──────────────────────────────────────────────
        if not self._claude_available():
            return {'action': 'HOLD', 'reason': 'Claude unavailable — holding', 'gate': 'NETWORK_FAIL'}

        # ── Compute averaging limits ──────────────────────────────────────────
        max_avg_qty     = int(quantity * avg_max_qty_pct)
        max_avg_capital = available_capital * avg_capital_pct
        max_avg_qty_by_capital = int(max_avg_capital / current_price) if current_price > 0 else 0
        safe_avg_qty    = min(max_avg_qty, max_avg_qty_by_capital)
        already_averaged = rs.get('times_averaged', 0) >= max_averages

        # ── TCAS / Kalman (intraday) ──────────────────────────────────────────
        tcas   = position.get('tcas_level', 'N/A')
        kalman = position.get('kalman_state', {})
        kal_v  = kalman.get('velocity', 'N/A')
        kal_a  = kalman.get('acceleration', 'N/A')
        stop   = float(position.get('stop_price', 0) or 0)
        target = float(position.get('target_price', 0) or 0)
        entry_time_raw = position.get('entry_time', '')
        if entry_time_raw:
            try:
                _et = datetime.fromisoformat(str(entry_time_raw)) if isinstance(entry_time_raw, str) else entry_time_raw
                days_held = (datetime.now() - _et).days
            except Exception:
                days_held = rs['days_in_recovery']
        else:
            days_held = rs['days_in_recovery']

        # ── Unpack market_data context (from orchestrator enrichment) ─────────
        md = market_data or {}
        rsi          = md.get('rsi')
        atr          = md.get('atr')
        vwap_pos     = md.get('vwap_pos', 'N/A')
        nifty_pct    = md.get('nifty_pct')
        vix          = md.get('vix')
        sector       = md.get('sector', 'N/A')
        sector_perf  = md.get('sector_perf', 'N/A')
        ohlcv_5d     = md.get('ohlcv_5d', [])
        oi_walls     = md.get('oi_walls', {})
        kal_daily    = md.get('kalman_daily', {})

        # ── CNC conversion eligibility ────────────────────────────────────────
        can_convert = (allow_cnc_conv and product == 'MIS'
                       and datetime.now().time() < cnc_conv_time)

        # ── Lessons for context ───────────────────────────────────────────────
        lessons_line = ""
        if self.memory_enabled and self.lessons:
            lessons_line = f"\nLessons: {self._format_lessons_for_prompt(compact=True)[:600]}"

        # ── Build enriched market context lines ───────────────────────────────
        tech_line = "  TECHNICALS: "
        tech_line += f"RSI={rsi:.1f}" if rsi is not None else "RSI=N/A"
        tech_line += f" | ATR={atr:.2f}" if atr is not None else " | ATR=N/A"
        tech_line += f" | {vwap_pos}"

        mkt_line = "  MARKET: "
        mkt_line += f"Nifty={nifty_pct:+.2f}%" if nifty_pct is not None else "Nifty=N/A"
        mkt_line += f" | VIX={vix:.1f}" if vix is not None else " | VIX=N/A"
        mkt_line += f" | Sector={sector}"
        if sector_perf != 'N/A':
            mkt_line += f" perf={sector_perf}"

        ohlcv_line = ""
        if ohlcv_5d:
            rows = [f"{c['date']}: O={c['o']} H={c['h']} L={c['l']} C={c['c']}" for c in ohlcv_5d]
            ohlcv_line = f"\n5D PRICE ACTION:\n  " + "\n  ".join(rows)

        oi_line = ""
        if oi_walls:
            oi_line = (
                f"\nOI WALLS:"
                f" PutSupport={oi_walls.get('put_wall', 'N/A')}"
                f" | CallResist={oi_walls.get('call_wall', 'N/A')}"
                f" | MaxPain={oi_walls.get('max_pain', 'N/A')}"
                f" | PCR={oi_walls.get('pcr', 'N/A')}"
            )

        kal_daily_line = ""
        if kal_daily and kal_daily.get('available'):
            kal_daily_line = (
                f"\nKALMAN DAILY:"
                f" dir={kal_daily.get('daily_direction', 'N/A')}"
                f" | vel={kal_daily.get('daily_velocity', 'N/A')}"
                f" | 1d_pred=₹{kal_daily.get('pred_1day', 0):.2f}"
                f" | 3d_pred=₹{kal_daily.get('pred_3day', 0):.2f}"
            )

        # ── Build prompt ──────────────────────────────────────────────────────
        prompt = (
            f"RECOVERY ADVISOR: {symbol} {direction} — MANDATE: Land in profit zone.\n\n"
            f"POSITION:\n"
            f"  Entry: ₹{entry_price:.2f} | Current: ₹{current_price:.2f} | P&L: {pnl_pct:+.2f}%\n"
            f"  Qty: {quantity} | Value: ₹{entry_price*quantity:,.0f} | Days held: {days_held}\n"
            f"  Stop: ₹{stop:.2f} | Target: ₹{target:.2f} | Product: {product}\n"
            f"  TCAS: {tcas} | IntraKalVel: {kal_v} | IntraKalAccel: {kal_a}\n\n"
            f"MARKET CONTEXT:\n"
            f"{tech_line}\n"
            f"{mkt_line}"
            f"{ohlcv_line}"
            f"{oi_line}"
            f"{kal_daily_line}\n\n"
            f"RECOVERY HISTORY:\n"
            f"  Days in recovery: {rs['days_in_recovery']}/{max_days}\n"
            f"  Times averaged: {rs['times_averaged']}/{max_averages}\n"
            f"  {'[AVERAGING LOCKED — max reached]' if already_averaged else f'[CAN AVERAGE: up to {safe_avg_qty} qty @ ₹{max_avg_capital:,.0f} capital]'}\n"
            f"  {'[CAN CONVERT MIS→CNC for overnight hold]' if can_convert else '[CANNOT CONVERT — product=CNC or time past]'}\n\n"
            f"PORTFOLIO CONTEXT:\n"
            f"  Regime: {self.todays_regime} | Daily P&L: ₹{self.daily_pnl:+,.0f}\n"
            f"  Available capital: ₹{available_capital:,.0f}"
            f"{lessons_line}\n\n"
            f"ACTIONS AVAILABLE: HOLD, AVERAGE, SCALE_OUT, CONVERT_CNC, WIDEN_STOP, EXIT\n"
            f"Rules: AVERAGE only if RSI/Kalman/OI walls confirm recovery potential AND times_averaged < {max_averages}.\n"
            f"       CONVERT_CNC only if daily Kalman is BULLISH and sector/market supports overnight hold.\n"
            f"       SCALE_OUT if momentum is clearly broken; EXIT if recovery thesis is invalidated.\n"
            f"       WIDEN_STOP only if volatility (ATR) justifies it and recovery thesis intact.\n\n"
            f"JSON only:\n"
            f'{{"action":"HOLD|AVERAGE|SCALE_OUT|CONVERT_CNC|WIDEN_STOP|EXIT",'
            f'"confidence":0-100,"reason":"<=30 words",'
            f'"average":{{"qty":<int>,"limit_price":<float>,"new_avg_entry":<float>}} | null,'
            f'"scale_out":{{"exit_pct":<25|50|75>,"order_type":"MARKET|LIMIT","limit_price":<float>|null}} | null,'
            f'"new_stop":<float> | null,'
            f'"recovery_target":<float>,'
            f'"give_up_below":<float>,'
            f'"hold_days_more":<int 1-{max_days}>}}'
        )

        logger.info(f"🔄 PH9 RECOVERY: consulting Claude for {symbol} "
                    f"({pnl_pct:+.2f}% | day {rs['days_in_recovery']})")

        try:
            response = self.client.messages.create(
                model=self.model_sonnet,   # Sonnet — recovery is high-stakes
                system=self._get_fund_manager_system_prompt_short(),
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
                max_tokens=400,
            )
            self._track_cost(self.model_sonnet, getattr(response, 'usage', None), 'recovery')
            result = self._extract_json(response.content[0].text)

            action = str(result.get('action', 'HOLD')).upper()

            # ── Validate + clamp Claude's averaging suggestion ────────────────
            if action == 'AVERAGE':
                if already_averaged:
                    logger.warning(f"PH9 Recovery: Claude said AVERAGE but max reached — converting to HOLD")
                    action = 'HOLD'
                    result['action'] = 'HOLD'
                    result['reason'] = 'Averaging locked (max reached) — holding'
                else:
                    avg_info = result.get('average') or {}
                    req_qty   = int(avg_info.get('qty', 0) or 0)
                    req_price = float(avg_info.get('limit_price', current_price) or current_price)
                    clamped_qty = min(req_qty, safe_avg_qty)
                    if clamped_qty <= 0:
                        logger.warning(f"PH9 Recovery: AVERAGE qty 0 after clamp — converting to HOLD")
                        action = 'HOLD'
                        result['action'] = 'HOLD'
                    else:
                        avg_info['qty'] = clamped_qty
                        avg_info['limit_price'] = req_price
                        result['average'] = avg_info
                        logger.info(f"   ✅ AVERAGE authorized: {clamped_qty} @ ₹{req_price:.2f}")

            # ── Validate CNC conversion ───────────────────────────────────────
            if action == 'CONVERT_CNC':
                if not can_convert:
                    logger.warning(f"PH9 Recovery: CONVERT_CNC not eligible — converting to HOLD")
                    action = 'HOLD'
                    result['action'] = 'HOLD'

            # ── Log + notify ──────────────────────────────────────────────────
            logger.info(f"🔄 PH9 RECOVERY {symbol}: {action} (confidence {result.get('confidence',0)}%)")
            logger.info(f"   Reason: {result.get('reason','')[:200]}")
            logger.info(f"   Target: ₹{result.get('recovery_target', 0):.2f} | "
                        f"Give up below: ₹{result.get('give_up_below', 0):.2f} | "
                        f"Hold {result.get('hold_days_more', 1)} more day(s)")

            # Record in history
            rs['history'].append({'date': _today_str, 'action': action,
                                  'pnl_pct': round(pnl_pct, 2),
                                  'reason': result.get('reason', '')[:100]})

            # Telegram alert
            if self.telegram and action not in ('HOLD', 'WIDEN_STOP'):
                self.telegram.send_message(
                    f"🔄 PH9 RECOVERY: {symbol}\n"
                    f"Action: {action} | P&L: {pnl_pct:+.2f}%\n"
                    f"Day {rs['days_in_recovery']}/{max_days}\n"
                    f"{result.get('reason','')[:200]}")

            self._journal('RECOVERY', symbol, result)
            result['action'] = action  # ensure clamped action is returned
            return result

        except Exception as e:
            logger.error(f"Recovery advisor failed for {symbol}: {e}")
            return {'action': 'HOLD', 'reason': f'Claude error — holding: {e}', 'gate': 'ERROR'}

    def mark_averaged(self, symbol: str):
        """Called by Phase 4 after successful averaging to update recovery counter."""
        if not hasattr(self, '_recovery_state'):
            self._recovery_state = {}
        rs = self._recovery_state.setdefault(symbol, {'times_averaged': 0, 'days_in_recovery': 0, 'history': []})
        rs['times_averaged'] = rs.get('times_averaged', 0) + 1
        logger.info(f"🔄 PH9 Recovery: {symbol} averaged ({rs['times_averaged']}x)")

    def clear_recovery(self, symbol: str):
        """Called when position is closed or reaches profit zone."""
        if hasattr(self, '_recovery_state') and symbol in self._recovery_state:
            del self._recovery_state[symbol]
            logger.info(f"✅ PH9 Recovery: {symbol} cleared (position closed or recovered)")

    # ═══════════════════════════════════════════════════════════════════════════
    # LEVEL 2D: POST-ALIM RE-ENTRY ADVISOR (v1.3.2)
    # After TCAS ALIM forces an exit at a realized loss, Claude gets ONE chance
    # to assess whether re-entering at the current (presumably better) price
    # makes sense given the updated market context.
    #
    # Hard rails (Python enforces — Claude cannot override):
    #   • Time > PH9_REENTRY_CUTOFF_TIME (13:30): always STAND_DOWN
    #   • Reentry count for symbol already ≥ PH9_REENTRY_MAX_PER_SYMBOL: STAND_DOWN
    #   • New stop MUST be tighter than original stop (Claude must provide one)
    #   • Budget exhausted: STAND_DOWN
    #
    # Claude returns: REENTER | WATCHLIST | STAND_DOWN
    # Orchestrator picks up _pending_reentry_plans and executes via phase3.
    # ═══════════════════════════════════════════════════════════════════════════

    def post_exit_reentry_advisor(self, symbol: str, closed_position: Dict,
                                  realized_pnl_inr: float, exit_price: float,
                                  market_data: Dict = None) -> Dict:
        """
        Called immediately after TCAS ALIM closes a position at a loss.
        Claude assesses whether a re-entry at the current price is justified
        by the updated market picture (RSI, OI walls, Kalman, sector).

        Result is stored in self._pending_reentry_plans[symbol].
        Orchestrator picks it up and executes via phase3 within seconds.
        """
        cfg             = self.config
        cutoff_time     = getattr(cfg, 'PH9_REENTRY_CUTOFF_TIME',    dt_time(13, 30))
        max_per_symbol  = getattr(cfg, 'PH9_REENTRY_MAX_PER_SYMBOL', 1)
        now             = datetime.now()

        # ── HARD RAIL 1: Time cutoff ──────────────────────────────────────────
        if now.time() >= cutoff_time:
            logger.info(f"🔁 PH9 REENTRY: {symbol} — STAND_DOWN (time {now.strftime('%H:%M')} ≥ cutoff {cutoff_time})")
            return {'action': 'STAND_DOWN', 'reason': 'Past re-entry cutoff time', 'gate': 'TIME_CUTOFF'}

        # ── HARD RAIL 2: Max re-entries today ────────────────────────────────
        done = self._reentry_done_today.get(symbol, 0)
        if done >= max_per_symbol:
            logger.info(f"🔁 PH9 REENTRY: {symbol} — STAND_DOWN (already re-entered {done}x today)")
            return {'action': 'STAND_DOWN', 'reason': f'Re-entry limit reached ({done}/{max_per_symbol})', 'gate': 'MAX_REENTRY'}

        # ── HARD RAIL 3: Budget check ─────────────────────────────────────────
        if not self._claude_available():
            return {'action': 'STAND_DOWN', 'reason': 'Claude unavailable', 'gate': 'BUDGET'}

        # ── Build context ─────────────────────────────────────────────────────
        md           = market_data or {}
        rsi          = md.get('rsi')
        atr          = md.get('atr')
        vwap_pos     = md.get('vwap_pos', 'N/A')
        ohlcv_5d     = md.get('ohlcv_5d', [])
        oi_walls     = md.get('oi_walls', {})
        kal_daily    = md.get('kalman_daily', {})

        direction    = str(closed_position.get('direction', 'LONG')).upper()
        orig_entry   = float(closed_position.get('entry_price', 0) or 0)
        orig_stop    = float(closed_position.get('stop_price', 0) or 0)
        orig_target  = float(closed_position.get('target_price', 0) or 0)
        orig_qty     = int(closed_position.get('quantity', 0) or 0)
        product      = str(closed_position.get('product', 'MIS')).upper()
        loss_pct     = (realized_pnl_inr / (orig_entry * orig_qty) * 100) if orig_entry * orig_qty > 0 else 0

        # MIS cutoff remaining
        mis_remaining = max(0, int((
            datetime.combine(now.date(), dt_time(15, 15)) - now
        ).total_seconds() / 60))

        # Lines
        tech_line = (f"RSI={rsi:.1f}" if rsi is not None else "RSI=N/A")
        tech_line += (f" | ATR={atr:.2f}" if atr is not None else " | ATR=N/A")
        tech_line += f" | {vwap_pos}"

        oi_line = ""
        if oi_walls:
            oi_line = (f"\n  OI: PutSupport={oi_walls.get('put_wall','N/A')}"
                       f" CallResist={oi_walls.get('call_wall','N/A')}"
                       f" MaxPain={oi_walls.get('max_pain','N/A')}"
                       f" PCR={oi_walls.get('pcr','N/A')}")

        kal_line = ""
        if kal_daily and kal_daily.get('available'):
            kal_line = (f"\n  KalmanDaily: {kal_daily.get('daily_direction','N/A')}"
                        f" | 1d=₹{kal_daily.get('pred_1day',0):.2f}"
                        f" | 3d=₹{kal_daily.get('pred_3day',0):.2f}")

        ohlcv_line = ""
        if ohlcv_5d:
            rows = [f"{c['date']} C={c['c']}" for c in ohlcv_5d[-3:]]
            ohlcv_line = "\n  5D-closes: " + " | ".join(rows)

        lessons_line = ""
        if self.memory_enabled and self.lessons:
            lessons_line = f"\nLessons: {self._format_lessons_for_prompt(compact=True)[:500]}"

        prompt = (
            f"POST-ALIM REENTRY ADVISOR: {symbol} {direction}\n\n"
            f"ALIM EXIT JUST HAPPENED:\n"
            f"  Original entry: ₹{orig_entry:.2f} | Exit at: ₹{exit_price:.2f}"
            f" | Realized loss: ₹{realized_pnl_inr:,.0f} ({loss_pct:+.2f}%)\n"
            f"  Original stop: ₹{orig_stop:.2f} | Target was: ₹{orig_target:.2f}"
            f" | Qty: {orig_qty} | Product: {product}\n\n"
            f"CURRENT MARKET STATE (post-ALIM, right now):\n"
            f"  Current price: ₹{exit_price:.2f} (same as exit)\n"
            f"  TECH: {tech_line}"
            f"{ohlcv_line}{oi_line}{kal_line}\n\n"
            f"PORTFOLIO: Regime={self.todays_regime} | DayP&L=₹{self.daily_pnl:+,.0f}"
            f" | MIS cutoff in {mis_remaining}m"
            f"{lessons_line}\n\n"
            f"MANDATE: The position just force-exited at a loss. Should we re-enter?\n"
            f"REENTER only if: RSI<35 (oversold) OR price at OI put wall AND Kalman daily BULLISH.\n"
            f"New stop MUST be tighter than original stop ₹{orig_stop:.2f}.\n"
            f"WATCHLIST if recovery likely but timing is not right now.\n"
            f"STAND_DOWN if thesis is broken or momentum is clearly bearish.\n\n"
            f"JSON only:\n"
            f'{{"action":"REENTER|WATCHLIST|STAND_DOWN","confidence":0-100,'
            f'"reentry_price":<float>|null,"reentry_qty":<int>|null,'
            f'"new_stop":<float — must be tighter than {orig_stop:.2f}>|null,'
            f'"direction":"{direction}",'
            f'"recovery_target":<float>|null,'
            f'"reason":"<=25 words"}}'
        )

        logger.info(f"🔁 PH9 REENTRY: consulting Claude for {symbol} "
                    f"(loss=₹{realized_pnl_inr:,.0f}, exit=₹{exit_price:.2f})")

        try:
            response = self.client.messages.create(
                model=self.model_sonnet,   # High-stakes — use Sonnet
                system=self._get_fund_manager_system_prompt_short(),
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
                max_tokens=300,
            )
            self._track_cost(self.model_sonnet, getattr(response, 'usage', None), 'reentry_advisor')
            result = self._extract_json(response.content[0].text)

            action = str(result.get('action', 'STAND_DOWN')).upper()
            if action not in ('REENTER', 'WATCHLIST', 'STAND_DOWN'):
                action = 'STAND_DOWN'

            logger.info(f"🔁 PH9 REENTRY {symbol}: {action} (confidence {result.get('confidence',0)}%)")
            logger.info(f"   Reason: {result.get('reason','')[:200]}")

            # ── HARD RAIL: Validate REENTER stop is tighter ───────────────────
            if action == 'REENTER':
                new_stop = float(result.get('new_stop') or 0)
                reentry_price = float(result.get('reentry_price') or exit_price)
                is_long = direction in ('LONG', 'BUY')

                # Stop tightness: for LONG, new_stop must be higher than orig_stop (closer to price)
                stop_ok = True
                if new_stop <= 0:
                    logger.warning(f"🔁 PH9 REENTRY {symbol}: no valid stop — STAND_DOWN")
                    stop_ok = False
                elif is_long and new_stop <= orig_stop:
                    logger.warning(f"🔁 PH9 REENTRY {symbol}: new_stop ₹{new_stop:.2f} ≤ orig ₹{orig_stop:.2f} — STAND_DOWN")
                    stop_ok = False
                elif not is_long and new_stop >= orig_stop:
                    logger.warning(f"🔁 PH9 REENTRY {symbol}: new_stop ₹{new_stop:.2f} ≥ orig ₹{orig_stop:.2f} (SHORT) — STAND_DOWN")
                    stop_ok = False

                if not stop_ok:
                    action = 'STAND_DOWN'
                    result['action'] = 'STAND_DOWN'
                    result['reason'] = 'Stop not tighter than original — re-entry unsafe'
                else:
                    # Count the re-entry
                    self._reentry_done_today[symbol] = done + 1
                    # Store plan for orchestrator to execute
                    self._pending_reentry_plans[symbol] = {
                        'action':          'REENTER',
                        'symbol':          symbol,
                        'direction':       direction,
                        'reentry_price':   reentry_price,
                        'reentry_qty':     int(result.get('reentry_qty') or orig_qty),
                        'new_stop':        new_stop,
                        'recovery_target': float(result.get('recovery_target') or orig_target),
                        'confidence':      result.get('confidence', 0),
                        'reason':          result.get('reason', ''),
                        'product':         product,
                    }
                    logger.info(f"   ✅ REENTER approved: qty={self._pending_reentry_plans[symbol]['reentry_qty']}"
                                f" @ ₹{reentry_price:.2f} stop=₹{new_stop:.2f}")

            elif action == 'WATCHLIST':
                self._pending_reentry_plans[symbol] = {
                    'action':  'WATCHLIST',
                    'symbol':  symbol,
                    'reason':  result.get('reason', ''),
                }

            # Telegram alert
            if self.telegram and action == 'REENTER':
                _plan = self._pending_reentry_plans.get(symbol, {})
                self.telegram.send_message(
                    f"🔁 PH9 REENTRY: {symbol}\n"
                    f"ALIM exit ₹{realized_pnl_inr:,.0f} loss → re-entering\n"
                    f"Entry: ₹{_plan.get('reentry_price',0):.2f}"
                    f" | Stop: ₹{_plan.get('new_stop',0):.2f}"
                    f" | Qty: {_plan.get('reentry_qty',0)}\n"
                    f"{result.get('reason','')[:150]}")

            self._journal('REENTRY_ADVICE', symbol, result)
            return result

        except Exception as e:
            logger.error(f"Post-exit reentry advisor failed for {symbol}: {e}")
            return {'action': 'STAND_DOWN', 'reason': f'Claude error: {str(e)[:80]}', 'gate': 'ERROR'}

    # ═══════════════════════════════════════════════════════════════════════════
    # LEVEL 1: EOD REVIEW (Post-Market)
    # ═══════════════════════════════════════════════════════════════════════════

    def eod_review(self, day_summary: Dict) -> Dict:
        """
        End-of-day performance review. Called after market close.

        Claude receives:
            - All trades today with P&L
            - Entry/exit decisions and reasoning
            - Missed opportunities (scored but not traded)
            - Portfolio state at close
            - Decision journal from today

        Claude returns:
            - performance_rating: 1-10
            - lessons: list of strings
            - tomorrow_adjustments: dict of parameter tweaks
            - journal_entry: free-text reflection

        Args:
            day_summary: Dict with 'trades', 'pnl', 'missed', 'portfolio',
                        'entries_approved', 'entries_blocked'

        Returns:
            Dict with review results
        """
        today = date.today()
        if self._eod_review_date == today and self._eod_review_done:
            logger.info("EOD review already completed today")
            return {}

        if not self._claude_available():
            logger.warning("Claude unreachable (network/DNS) — skipping EOD review")
            # Mark done so shutdown doesn't retry
            self._eod_review_done = True
            self._eod_review_date = today
            return self._get_default_eod()

        logger.info("=" * 80)
        logger.info("🌙 PHASE 9: END-OF-DAY REVIEW")
        logger.info("=" * 80)

        # Include today's decision journal
        day_summary['decision_journal'] = self.decision_journal[-50:]  # Last 50 entries
        day_summary['entries_approved'] = self.entries_approved
        day_summary['entries_blocked'] = self.entries_blocked
        day_summary['exits_advised'] = self.exits_advised
        day_summary['regime_today'] = self.todays_regime

        prompt = self._build_eod_prompt(day_summary)

        try:
            # v1.1.0: Sonnet for EOD (needs deep reasoning, only 1/day)
            response = self.client.messages.create(
                model=self.model_sonnet,
                system=self._get_fund_manager_system_prompt(),
                messages=[{"role": "user", "content": prompt}],
                temperature=0.4,
                max_tokens=self.max_response_tokens_strategic
            )

            # Track cost
            self._track_cost(self.model_sonnet, getattr(response, 'usage', None),
                             'eod_review')

            content = response.content[0].text
            result = self._extract_json(content)

            self._eod_review_done = True
            self._eod_review_date = today

            # v1.4.0: Parse ph8 watchlist additions from EOD review
            _eod_wl = result.get('ph8_watchlist_add', [])
            if isinstance(_eod_wl, list):
                for _s in _eod_wl:
                    if _s and str(_s).upper() not in self.todays_ph8_watchlist_add:
                        self.todays_ph8_watchlist_add.append(str(_s).upper())
                        logger.info(f"   🧠 PH9 EOD: {str(_s).upper()} → PH8 watchlist")

            logger.info(f"   Rating: {result.get('performance_rating', '?')}/10")
            lessons = result.get('new_lessons', result.get('lessons', []))
            for i, lesson in enumerate(lessons[:5], 1):
                logger.info(f"   Lesson {i}: {lesson}")

            # v3.0.0: Validate existing lessons first (update confidence scores),
            # then extract any new structured lessons from today's EOD.
            if self.memory_enabled:
                self._validate_lessons_at_eod(result)
                self._extract_lessons_from_eod(result)
                self._append_today_to_history(day_summary)

            journal_text = result.get('journal_entry', '')
            logger.info(f"   Journal: {journal_text[:300]}")

            # Save journal to file
            self._save_journal_to_file(today, result)

            # Telegram
            if self.telegram:
                # Separate code bugs from strategy lessons for Telegram
                _new_lessons_raw = result.get('new_lessons', [])
                _strategy_lessons = []
                _code_bugs = []
                for _l in _new_lessons_raw:
                    if isinstance(_l, dict):
                        if _l.get('type') == 'CODE_BUG':
                            _code_bugs.append(_l.get('text', ''))
                        else:
                            _strategy_lessons.append(f"[conf={_l.get('confidence','?')}|{_l.get('type','?')}] {_l.get('text','')}")
                    else:
                        _strategy_lessons.append(str(_l))

                lessons_text = '\n'.join([f"  {i}. {l}" for i, l in enumerate(_strategy_lessons[:5], 1)])
                msg = (
                    f"🌙 FUND MANAGER — EOD REVIEW\n\n"
                    f"Rating: {result.get('performance_rating', '?')}/10\n"
                    f"Total P&L: ₹{day_summary.get('total_pnl', 0):+,.0f}\n"
                    f"Trades: {day_summary.get('trade_count', 0)}\n"
                    f"Entries: {self.entries_approved} approved, {self.entries_blocked} blocked\n\n"
                    f"Strategy lessons:\n{lessons_text or '  (none)'}\n\n"
                    f"{journal_text[:300]}"
                )
                if _code_bugs:
                    bugs_text = '\n'.join([f"  🚨 {b}" for b in _code_bugs])
                    msg += f"\n\n⚠ CODE BUGS IDENTIFIED (fix before next session):\n{bugs_text}"
                self.telegram.send_message(msg)

            self._log_to_db('EOD_REVIEW', 'PORTFOLIO', day_summary, result, prompt[:500])

            return result

        except Exception as e:
            logger.error(f"EOD review failed: {e}")
            self._eod_review_done = True
            self._eod_review_date = today
            # v1.2.0: still persist today's summary even if Claude failed
            if self.memory_enabled:
                try:
                    self._append_today_to_history(day_summary)
                except Exception:
                    pass
            return self._get_default_eod()

    # ═══════════════════════════════════════════════════════════════════════════
    # LIVE CHAT — User asks questions / issues directives via Telegram
    # ═══════════════════════════════════════════════════════════════════════════

    def chat(self, question: str, context: dict) -> dict:
        """
        Conversational interface. User sends a free-text question or instruction
        via Telegram; Claude responds in plain English AND optionally returns
        directive overrides that the orchestrator will apply immediately.

        Args:
            question:  Raw user message, e.g. "why no trades?", "pause ph5a"
            context:   Dict built by orchestrator with live system state.

        Returns:
            {
              'answer':     str   — human-readable reply to send to Telegram,
              'directives': dict  — optional overrides (only keys that should change),
              'error':      str   — set only on failure
            }
        """
        if not self.client:
            return {'answer': 'Claude unavailable — no API client.', 'directives': {}}

        if not self._claude_available():
            return {'answer': 'Claude unreachable (network) — using rule-based mode.', 'directives': {}}

        # ── Build state summary for prompt ──────────────────────────────────
        now_str   = context.get('time', 'unknown')
        regime    = context.get('regime', self.todays_regime)
        vix       = context.get('vix', '?')
        nifty_chg = context.get('nifty_change_pct', '?')
        positions = context.get('open_positions', [])
        monitors  = context.get('monitors', [])
        trades    = context.get('trades_today', self.trades_today)
        pnl       = context.get('daily_pnl', self.daily_pnl)
        blocks    = context.get('active_blocks', [])
        ph5_dir   = self.todays_ph5_directive
        ph5a_dir  = self.todays_ph5a_directive
        ph4_dir   = self.todays_ph4_directive
        ph6_dir   = self.todays_ph6_directive

        monitors_str  = ', '.join(f"{m['symbol']} RSI={m.get('rsi','?')}" for m in monitors) or 'none'
        positions_str = ', '.join(f"{p['symbol']} P&L=₹{p.get('pnl',0):+.0f}" for p in positions) or 'none'
        blocks_str    = ' | '.join(blocks) if blocks else 'none'

        state_summary = f"""LIVE SYSTEM STATE — {now_str}
Regime: {regime} | VIX: {vix} | Nifty: {nifty_chg}%
Directives: PH4={ph4_dir} PH5={ph5_dir} PH5A={ph5a_dir} PH6={ph6_dir}
Max positions: {self.todays_max_positions}
Entry window: >= {self.todays_entry_window} | Exit aggression: {self.todays_exit_aggression}
Sector focus: {self.todays_sector_focus or 'ALL'} | Avoid: {self.todays_sector_avoid or 'none'}
PH2 min score: {self.todays_ph2_min_score} | PH5A sensitivity: {self.todays_ph5a_sensitivity}
Active blocks: {blocks_str}
Monitors: {monitors_str}
Open positions: {positions_str}
Trades today: {trades} | Daily P&L: ₹{pnl:+,.0f}
Confidence: {self.todays_confidence}% | Notes: {self.todays_notes[:200]}"""

        prompt = f"""{state_summary}

USER MESSAGE: {question}

Respond conversationally and directly. If the user is asking a question, answer it clearly using the state above.
If the user wants to change strategy (e.g. "resume ph5a", "go defensive", "lower the score threshold"), apply the change.

IMPORTANT: End your response with a JSON block ONLY if directives should change. Format:
```json
{{
  "regime": "CAUTIOUS",
  "ph4_directive": "NORMAL",
  "ph5_directive": "ACTIVE",
  "ph5a_directive": "ACTIVE",
  "ph6_directive": "ACTIVE",
  "size_multiplier": 1.0,
  "max_positions": 3,
  "exit_aggression": "NORMAL",
  "entry_window": "09:45",
  "ph2_min_score": 55.0,
  "ph5a_sensitivity": "normal",
  "sector_focus": [],
  "sector_avoid": []
}}
```
Include ONLY the keys you want to change. Omit the JSON block entirely if no changes needed.
Never override HALT regime — that is a circuit breaker."""

        try:
            response = self.client.messages.create(
                model=self.model_sonnet,
                system=self._get_fund_manager_system_prompt(),
                messages=[{'role': 'user', 'content': prompt}],
                temperature=0.4,
                max_tokens=600,
            )
            self._track_cost(self.model_sonnet, getattr(response, 'usage', None), 'chat')
            raw = response.content[0].text

            # Extract answer (text before JSON block) and optional directives
            directives = {}
            answer = raw
            json_match = __import__('re').search(r'```json\s*([\s\S]*?)```', raw)
            if json_match:
                answer = raw[:json_match.start()].strip()
                try:
                    parsed = __import__('json').loads(json_match.group(1))

                    # Apply with safety clamps — never let chat override HALT
                    if self.todays_regime == 'HALT':
                        parsed.pop('regime', None)

                    allowed_regimes = ('NORMAL', 'CAUTIOUS', 'DEFENSIVE', 'HALT')
                    if 'regime' in parsed and parsed['regime'] in allowed_regimes:
                        self.todays_regime = parsed['regime']
                        directives['regime'] = parsed['regime']

                    for key, attr in (
                        ('ph4_directive',  'todays_ph4_directive'),
                        ('ph5_directive',  'todays_ph5_directive'),
                        ('ph5a_directive', 'todays_ph5a_directive'),
                        ('ph6_directive',  'todays_ph6_directive'),
                        ('exit_aggression','todays_exit_aggression'),
                        ('ph5a_sensitivity','todays_ph5a_sensitivity'),
                    ):
                        if key in parsed and isinstance(parsed[key], str):
                            setattr(self, attr, str(parsed[key]).upper() if key != 'ph5a_sensitivity' else str(parsed[key]).lower())
                            directives[key] = parsed[key]

                    if 'max_positions' in parsed:
                        self.todays_max_positions = max(1, min(self.max_open_positions, int(parsed['max_positions'])))
                        directives['max_positions'] = self.todays_max_positions

                    if 'ph2_min_score' in parsed:
                        self.todays_ph2_min_score = max(40.0, min(80.0, float(parsed['ph2_min_score'])))
                        directives['ph2_min_score'] = self.todays_ph2_min_score

                    if 'entry_window' in parsed:
                        _ew = str(parsed['entry_window'])
                        if __import__('re').match(r'^\d{2}:\d{2}$', _ew):
                            self.todays_entry_window = _ew
                            directives['entry_window'] = _ew

                    if 'sector_focus' in parsed and isinstance(parsed['sector_focus'], list):
                        self.todays_sector_focus = [s.upper() for s in parsed['sector_focus'] if isinstance(s, str)]
                        directives['sector_focus'] = self.todays_sector_focus

                    if 'sector_avoid' in parsed and isinstance(parsed['sector_avoid'], list):
                        self.todays_sector_avoid = [s.upper() for s in parsed['sector_avoid'] if isinstance(s, str)][:2]
                        directives['sector_avoid'] = self.todays_sector_avoid

                except Exception as _je:
                    logger.warning(f"Chat directive parse failed: {_je}")

            logger.info(f"🧠 PH9 Chat response ({len(answer)} chars, {len(directives)} directive changes)")
            return {'answer': answer, 'directives': directives}

        except Exception as e:
            logger.error(f"PH9 chat failed: {e}")
            return {'answer': f'Brain unavailable: {e}', 'directives': {}, 'error': str(e)}

    # ═══════════════════════════════════════════════════════════════════════════
    # P&L TRACKING (called by Phase 4 on every exit)
    # ═══════════════════════════════════════════════════════════════════════════

    def update_daily_pnl(self, pnl_amount: float, symbol: str = None):
        """Update running daily P&L. Called after every trade exit."""
        self.daily_pnl += pnl_amount
        self.trades_today += 1
        logger.info(f"   🧠 Fund Manager: Daily P&L updated → ₹{self.daily_pnl:+,.0f} "
                    f"(trade #{self.trades_today})")

        # Circuit breaker check
        if self.daily_pnl <= self.max_daily_loss:
            logger.warning(f"🛑 CIRCUIT BREAKER: Daily loss ₹{self.daily_pnl:,.0f} "
                          f"exceeds limit ₹{self.max_daily_loss:,.0f}")
            self.todays_regime = 'HALT'
            if self.telegram:
                self.telegram.send_message(
                    f"🛑 FUND MANAGER — CIRCUIT BREAKER\n\n"
                    f"Daily P&L: ₹{self.daily_pnl:+,.0f}\n"
                    f"Limit: ₹{self.max_daily_loss:,.0f}\n\n"
                    f"ALL NEW ENTRIES BLOCKED for rest of day.\n"
                    f"Existing positions will still be managed."
                )

    def record_trade_pnl(self, source: str, pnl: float, symbol: str = ''):
        """
        v1.6.0: Per-phase P&L attribution. Called by Phase 4 on every position close.
        Normalises source string → phase key for aggregation.
        """
        _src = str(source).upper()
        if 'PH5A' in _src or 'PVAT' in _src:
            key = 'PH5A'
        elif 'PH5' in _src:
            key = 'PH5'
        elif 'PH8' in _src:
            key = 'PH8'
        elif 'PH2' in _src or 'INT' in _src or 'FALLBACK' in _src:
            key = 'PH2'
        else:
            key = 'OTHER'
        self._phase_pnl_today[key] = round(self._phase_pnl_today.get(key, 0) + pnl, 2)
        self._phase_trade_count[key] = self._phase_trade_count.get(key, 0) + 1
        logger.debug(f"   📊 Phase attribution: {key} ₹{pnl:+.0f} | "
                    f"running ₹{self._phase_pnl_today[key]:+.0f} ({self._phase_trade_count[key]} trades)")

    def _format_phase_performance(self) -> str:
        """
        v1.6.0: Build a phase performance summary block for the morning prompt.
        Uses today's partial data + rolling_history for multi-day view.
        """
        lines = []

        # Today's data (partial — trades already closed this session if reset_daily_state
        # wasn't called yet, or yesterday's data when called at morning briefing)
        if self._phase_pnl_today:
            lines.append("YESTERDAY (phase breakdown):")
            for ph in sorted(self._phase_pnl_today):
                cnt = self._phase_trade_count.get(ph, 0)
                pnl = self._phase_pnl_today[ph]
                win_loss = "▲" if pnl >= 0 else "▼"
                lines.append(f"  {ph}: {win_loss} ₹{pnl:+,.0f} ({cnt} trades)")

        # Rolling history — per-phase aggregation (if stored in history)
        if self.memory_enabled and len(self.rolling_history) >= 2:
            _recent = self.rolling_history[-5:]
            ph_pnl: Dict[str, float] = {}
            ph_cnt: Dict[str, int] = {}
            for h in _recent:
                for ph, p in (h.get('phase_pnl') or {}).items():
                    ph_pnl[ph] = round(ph_pnl.get(ph, 0) + float(p or 0), 2)
                    ph_cnt[ph] = ph_cnt.get(ph, 0) + int(h.get('phase_trades', {}).get(ph, 0))
            if ph_pnl:
                lines.append(f"LAST {len(_recent)} DAYS (phase totals):")
                for ph in sorted(ph_pnl):
                    pnl = ph_pnl[ph]
                    win_loss = "▲" if pnl >= 0 else "▼"
                    lines.append(f"  {ph}: {win_loss} ₹{pnl:+,.0f}")

        return '\n'.join(lines) if lines else "  No per-phase attribution data yet (accumulating)"

    def reset_daily_state(self):
        """Reset daily tracking. Called at start of each trading day."""
        # Log yesterday's cost before resetting
        if self.daily_api_cost_inr > 0:
            logger.info(f"🧠 PH9: Yesterday's Claude cost: ₹{self.daily_api_cost_inr:.2f} "
                       f"({self.daily_api_calls} calls)")
            if self.cost_by_type:
                for k, v in sorted(self.cost_by_type.items(), key=lambda x: -x[1]):
                    logger.info(f"     {k}: ₹{v:.2f}")

        self.daily_pnl = 0.0
        self.trades_today = 0
        self.entries_approved = 0
        self.entries_blocked = 0
        self.exits_advised = 0
        self.decision_journal.clear()
        self._morning_briefing_done = False
        self._eod_review_done = False
        self._midday_check_done = False
        self.todays_regime = 'NORMAL'
        self.todays_size_multiplier = 1.0
        self.todays_max_positions = self.max_open_positions
        self.todays_phases_active = ['PH1', 'PH2', 'PH3', 'PH4', 'PH5', 'PH5A', 'PH8']
        self.todays_notes             = ''
        self.todays_day_plan          = ''
        self.todays_unlock_conditions = ''
        self.todays_watch_stocks      = ''

        # v1.3.0: Reset extended directives
        self.todays_market_bias      = 'NEUTRAL'
        self.todays_vix_regime       = 'NORMAL'
        self.todays_ph5_size_mult    = 1.0
        self.todays_ph5_stop_mult    = 1.0
        self.todays_sector_focus     = []
        self.todays_sector_avoid     = []
        self.todays_entry_window     = '09:15'
        self.todays_stop_atr_mult    = 1.0
        self.todays_target_atr_mult  = 1.0
        self.todays_exit_aggression  = 'NORMAL'
        self.todays_ph6_options_bias = 'NEUTRAL'
        self.todays_risk_level       = 'MEDIUM'
        self.todays_confidence       = 70

        # v1.4.0: Reset per-phase directives
        self.todays_ph5_directive  = 'ACTIVE'
        self.todays_ph5a_directive = 'ACTIVE'
        self.todays_ph4_directive  = 'NORMAL'
        self.todays_ph6_directive  = 'ACTIVE'
        self.todays_ph8_directive  = 'HOLD'
        self.todays_ph8_watchlist_add = []
        self._last_heartbeat_time = None
        self._signal_queue = []       # v1.5.0: clear any overnight queue
        self._reentry_done_today  = {}  # v1.3.2: reset per-day re-entry counts
        self._pending_reentry_plans = {}  # v1.3.2: clear stale plans

        # v1.6.0: Reset phase-specific tuning params
        self.todays_ph2_min_score = 55.0
        self.todays_ph5a_sensitivity = 'normal'
        self.todays_ph8_momentum_threshold = 3.0

        # v1.6.0: Clear phase P&L attribution (save to history before clearing)
        self._phase_pnl_today = {}
        self._phase_trade_count = {}

        # v1.1.0: Reset cost tracking
        self.daily_api_cost_inr = 0.0
        self.daily_api_calls = 0
        self.cost_by_type = {}
        self.budget_exhausted = False

        logger.info("🧠 Fund Manager: Daily state reset")

    # ═══════════════════════════════════════════════════════════════════════════
    # PROMPT BUILDERS
    # ═══════════════════════════════════════════════════════════════════════════

    def morning_self_calibration(self) -> bool:
        """
        v2.1.0: Auto-updates data/claude_phase_knowledge.md with a TODAY'S CALIBRATION
        section derived from yesterday's journal + accumulated lessons. Haiku call (~₹0.10).

        Flow:
          1. Read yesterday's journal JSON (data/fund_manager/journal_YYYY-MM-DD.json)
          2. Call Haiku → distill 2-3 numbered rules for today
          3. Write rules as ## TODAY'S CALIBRATION section in claude_phase_knowledge.md
          4. Every heartbeat reads this section via _load_phase_knowledge_compact()

        Called once at startup in orchestrator, before morning_briefing().
        Returns True if calibration was written, False if skipped.
        """
        if not self._claude_available():
            logger.info("🧠 Self-calibration: Claude unreachable, skipping")
            return False

        from datetime import timedelta
        import re as _re

        yesterday = (date.today() - timedelta(days=1)).strftime('%Y-%m-%d')
        journal_path = os.path.join('data', 'fund_manager', f'journal_{yesterday}.json')

        journal_data: dict = {}
        if os.path.isfile(journal_path):
            try:
                with open(journal_path, 'r', encoding='utf-8') as _f:
                    journal_data = json.load(_f)
            except Exception as _e:
                logger.warning(f"Self-calibration: could not read journal — {_e}")

        if not journal_data and not self.lessons:
            logger.info("🧠 Self-calibration: no journal or lessons to learn from, skipping")
            return False

        eod             = journal_data.get('eod_review', {})
        journal_entry   = eod.get('journal_entry', '')[:400]
        new_lessons     = eod.get('new_lessons', [])
        rating          = eod.get('performance_rating', '?')
        tomorrow_adj    = eod.get('tomorrow_adjustments', {})
        lessons_text    = self._format_lessons_for_prompt(compact=False)

        prompt = (
            f"Yesterday's session (rated {rating}/10):\n"
            f"Journal: {journal_entry}\n"
            f"New lessons from yesterday: {chr(10).join(new_lessons)}\n"
            f"Tomorrow adjustments: {json.dumps(tomorrow_adj)}\n\n"
            f"Accumulated lessons ({len(self.lessons)} total):\n{lessons_text}\n\n"
            f"Distill exactly 2-3 numbered, actionable rules for TODAY's trading session. "
            f"Each rule ≤20 words, specific, directly applicable to regime/phase decisions. "
            f"Output the numbered rules only — no JSON, no extra text."
        )

        try:
            response = self.client.messages.create(
                model=self.model_haiku,
                system=(
                    "You are a trading rule synthesizer for an Indian equity algo system. "
                    "Output 2-3 numbered rules only, each ≤20 words."
                ),
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=150,
            )
            self._track_cost(self.model_haiku, getattr(response, 'usage', None),
                             'self_calibration')
            calibration_text = response.content[0].text.strip()

            # Write/replace TODAY'S CALIBRATION section in phase knowledge file
            knowledge_path = os.path.join('data', 'claude_phase_knowledge.md')
            content = ""
            if os.path.isfile(knowledge_path):
                with open(knowledge_path, 'r', encoding='utf-8') as _f:
                    content = _f.read()

            today_str = date.today().strftime('%Y-%m-%d')
            section   = f"\n## TODAY'S CALIBRATION ({today_str})\n{calibration_text}\n"

            if "## TODAY'S CALIBRATION" in content:
                content = _re.sub(
                    r"\n## TODAY'S CALIBRATION[^\n]*\n.*?(?=\n## |\Z)",
                    section,
                    content,
                    flags=_re.DOTALL,
                )
            else:
                content += section

            with open(knowledge_path, 'w', encoding='utf-8') as _f:
                _f.write(content)

            logger.info(f"🧠 Self-calibration written to phase knowledge:\n{calibration_text}")
            return True

        except Exception as _e:
            logger.warning(f"Self-calibration failed: {_e}")
            return False

    def _load_phase_knowledge_compact(self) -> str:
        """Load phase knowledge reference for heartbeat context. Compact version only."""
        try:
            import os
            _path = os.path.join('data', 'claude_phase_knowledge.md')
            if not os.path.isfile(_path):
                return ""
            with open(_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            # Extract only the AVAILABLE DYNAMIC ACTIONS table and MARKET TIMING section
            # to keep token cost low — full file is human reference only
            compact = []
            _capture = False
            for line in lines:
                if ('## AVAILABLE DYNAMIC ACTIONS' in line or '## MARKET TIMING' in line
                    or "## TODAY'S CALIBRATION" in line):
                    _capture = True
                elif (line.startswith('## ') and _capture
                      and 'DYNAMIC' not in line and 'TIMING' not in line
                      and 'CALIBRATION' not in line):
                    if len(compact) > 5:
                        break
                if _capture:
                    compact.append(line.rstrip())
            return '\n'.join(compact[:40]) if compact else ""
        except Exception:
            return ""

    def _get_fund_manager_system_prompt_short(self) -> str:
        """Compact system prompt for tactical Haiku gate calls (entry/exit/heartbeat).
        Token-optimized: keeps phase context brief for cost efficiency."""
        return """You are ALPHA, AI trading gate for an Indian equity system (NSE/Zerodha, ₹50k-2L account).
Role: Approve/reject single entry or advise single exit. Protect capital first.
Phase guide: PH2=RSI-zone intraday, PH5=gap-fade 09:15-10:00 only, PH5A=PVAT-breakout 10:00-14:30 (excels low VIX<16), PH8=weekly-momentum CNC hold.
Rules:
- No internet. All data is given.
- Hard safety rails (daily loss, stops, MIS cutoff 15:15) override you always.
- Respond with valid JSON only. No markdown, no prose outside JSON.
- Be decisive. Keep reasoning under 20 words."""

    def _get_fund_manager_system_prompt(self) -> str:
        return """You are ALPHA, AI Fund Manager for an Indian equity algo trading system (NSE/Zerodha, ₹50k-2L retail account).

═══ MANDATE ═══
Capital protection > Consistent returns. Deploy the RIGHT strategy in the RIGHT conditions.
A wrong strategy in wrong market × N trades = large loss. Right strategy in right market = compounding edge.
When unsure: CAUTIOUS > NORMAL. Preservation always beats recovery.

═══ YOUR TRADING SYSTEM ═══

PHASE 2 — RSI ZONE MONITOR (continuous, 09:15-15:00, MIS intraday)
  Strategy: Kalman-filtered RSI monitoring. Waits for RSI to enter oversold (<35), then fires on
            zone exit with momentum confirmation. Stop = recent swing low.
  Signal score 0-100: technical + momentum + volume + support + Nifty correlation.
  Excels: Trending intraday market, clear RSI cycles, broad market breadth >60%.
  Struggles: Choppy mean-reverting day, VIX>20, pre-expiry volatile open, thin breadth.
  Your controls: ph2_min_score (default 55; raise to 65+ on weak/choppy days),
                 entry_window_start (delay entries on volatile opens).

PHASE 3 — ORDER EXECUTOR
  Executes orders from PH2/PH5/PH5A/PH8 via Zerodha Kite. Not directly controllable.

PHASE 4 — PORTFOLIO MANAGER (continuous, per open position)
  Kalman-filter velocity + TCAS (stop-collision avoidance) + ILS (target approach tracking).
  Manages dynamic stops, trailing, health scoring, exit timing.
  Your controls: NORMAL (standard Kalman trailing) vs DEFENSIVE (tighten ALL stops to 50% of
                 current distance right now — call this when protecting open profits in reversal).

PHASE 5 — GAP TRADING (09:15-10:00 AM ONLY — first 45 minutes)
  Strategy: Fade large morning gaps (>2%: mean-reversion). BIDIRECTIONAL — trades both sides:
    GAP-UP  > 2% → SHORT SELL (MIS) — sell into the gap, target reversion to previous close.
    GAP-DOWN > 2% → LONG BUY (MIS) — buy the dip, target reversion up.
  This phase executes SHORT/SELL orders automatically on gap-up fade days.
  Excels: Clear directional bias, FII-driven gap, VIX<18, strong pre-market.
  Struggles: VIX>20, random gaps, mixed signals, equity F&O expiry.
  SKIP if: VIX>20 OR gap direction unclear OR expiry day.

PHASE 5A — PVAT BREAKOUT/BREAKDOWN SNIPER (10:00 AM - 2:30 PM)
  Strategy: BIDIRECTIONAL — trades both breakouts (LONG) AND breakdowns (SHORT).
    LONG  (BUY)  : Price breaks ABOVE resistance with volume surge. Tight stop below zone.
    SHORT (SELL) : Price breaks BELOW support with volume. Tight stop above zone.
  You control direction via market_bias:
    market_bias=BULLISH  → PH5A prioritizes BUY breakouts.
    market_bias=BEARISH  → PH5A prioritizes SELL breakdowns (SHORT MIS orders).
    market_bias=NEUTRAL  → PH5A trades whichever setup appears first.
  Excels LONG: VIX<16, breadth>65%, FII buying.
  Excels SHORT: VIX 16-22, Nifty trending down, breadth<45%, distribution in large-caps.
  Your controls: ph5a_sensitivity (tight/normal/loose), market_bias (BULLISH/BEARISH/NEUTRAL).
  PAUSE only if: VIX>25 OR 3+ consecutive stop-outs this week (regardless of direction).

PHASE 6 — OPTIONS ADVISORY (no auto-execution, advisory alerts only)
  Index options signals based on TCAS pivot detection. Advises user on CE/PE trades.
  Your controls: ACTIVE (send advisories) vs HOLD (silence — use on uncertain/rangy days).

PHASE 8 — WEEKLY MOMENTUM (CNC delivery, 1-week hold)
  Strategy: Buy the strongest large-cap stock each week. Tuesday VWAP entry, hold until
            Friday exit or momentum breaks. Ranks Nifty 50 by 5-day price momentum.
  Excels: Trending week, sector rotation clarity, FII net buyers, VIX<15.
  Struggles: Event-heavy weeks (FOMC/RBI/Budget), broad volatility, VIX>20.
  Your controls: ph8_momentum_threshold (min weekly return % to qualify; raise on weak weeks),
                 HOLD (stay in position) vs CLOSE_WEAKEST (exit if week deteriorates).
  Watchlist: Add names showing weekly breakout for next week's candidate pool.

═══ PHASE SYNERGY MAP ═══
STRONG BULL DAY (Nifty>0.5%, breadth>70%, VIX<15, FII buying):
  PH5 ACTIVE + PH5A ACTIVE (normal, market_bias=BULLISH) + PH2 ACTIVE (ph2_min_score=52) + PH8 HOLD
  → Full long deployment. Size 1.0-1.25x. AGGRESSIVE mode possible.

BULLISH WITH ELEVATED VIX (Nifty>1%, VIX 16-20, breadth>55%, sustained rally):
  PH5 ACTIVE + PH5A ACTIVE (normal, market_bias=BULLISH) + PH2 ACTIVE (ph2_min_score=57) + PH4 NORMAL
  → Clear bull trend despite elevated VIX. VIX 16-20 alone is NOT a reason for CAUTIOUS.
  → NORMAL mode, size 0.9x. Activate PH5A NEUTRAL by 11:00 if Nifty sustains >+1%.
  → Only upgrade to CAUTIOUS if breadth drops below 50% AND Nifty starts wavering — not on VIX alone.

TRENDING BUT CAUTIOUS LONG (Nifty flat-to-0.5%, VIX 16-20, mixed breadth):
  PH5 ACTIVE + PH5A ACTIVE (tight, market_bias=NEUTRAL) + PH2 ACTIVE (ph2_min_score=60) + PH4 NORMAL
  → Selective longs. Standard sizing. NORMAL mode.

BEARISH TRENDING DAY — OFFENSIVE SHORT (Nifty<-0.7%, breadth<45%, VIX 16-22, sustained selling):
  market_bias=BEARISH + PH5 ACTIVE (gap-up SHORT fade) + PH5A ACTIVE (normal, SELL breakdowns priority)
  + PH2 SKIP or ph2_min_score=70 (RSI oversold — too risky for longs now) + PH4 DEFENSIVE + PH8 HOLD
  → This is a PROFIT DAY via SHORT. Set market_bias=BEARISH. PH5A will hunt SELL breakdowns.
  → Do NOT HALT just because market falls. Deploy SHORT strategy, reduce LONG exposure.
  → Approve SELL/SHORT signals from PH5A in entry gate. Size 0.75x on first SHORT, 1.0x if confirmed.

SHARP INTRADAY REVERSAL (Nifty was -1%+ then recovering, VIX contracting, breadth flipping):
  market_bias=NEUTRAL → BULLISH + PH5A ACTIVE (loose, switch to BUY breakouts) + PH2 ACTIVE (ph2_min_score=55)
  → Regime flip opportunity. Update market_bias in heartbeat to capture the reversal.

GAP-DOWN OPEN + RECOVERY (Nifty gap<-0.7% then recovering above open):
  PH5 ACTIVE (LONG fade of gap-down) + PH5A ACTIVE (loose, market_bias=NEUTRAL) + PH4 NORMAL
  → Fade the gap long. Let PH5A pick breakouts as dust settles after 10:30.

CHOPPY/VOLATILE NO TREND (VIX 20-25, breadth 40-60%, Nifty whipsawing both ways):
  PH5 SKIP + PH5A PAUSE + PH2 ACTIVE (ph2_min_score=65) + PH4 DEFENSIVE
  → No clear edge for PH5/PH5A in either direction. PH2 only with high bar. CAUTIOUS.

EXTREME (VIX>25, circuit risk, global macro event):
  HALT or CAUTIOUS. PH5 SKIP + PH5A PAUSE + PH2 ph2_min_score=70+ + PH4 DEFENSIVE.
  → Only HALT when VIX is truly extreme or circuit-breaker risk exists. Not on normal down days.

F&O EXPIRY DAY (monthly/weekly expiry — chaotic derivatives unwinding):
  PH5 SKIP + PH5A PAUSE + PH2 ph2_min_score=65 + PH6 HOLD + PH8 HOLD

═══ OPERATION MODES ═══
NORMAL:     Standard deployment. All phases per directive. Standard sizes (1.0x). Both LONG and SHORT.
CAUTIOUS:   50% position sizes. Raise all thresholds. Only high-conviction signals. Both directions.
AGGRESSIVE: 1.25x sizes. Only on confirmed strong trending day (bull OR bear). Use sparingly.
HALT:       No new entries. Only manage existing positions. Reserve for VIX>25 or circuit risk.
            ⚠ Do NOT use HALT simply because market is falling. A falling market = SHORT opportunity.
            Use CAUTIOUS + market_bias=BEARISH instead on normal bearish trending days.

═══ PROFIT IN ALL CONDITIONS ═══
Your job is to MAKE MONEY regardless of market direction. You have two weapons:
  LONG  → market rising, breadth strong, VIX falling
  SHORT → market falling, breadth weak, VIX rising (set market_bias=BEARISH)
Never leave the system idle when there is a clear directional trend. Match your tools to the trend.
Idle = missed profit. Wrong direction = loss. Right direction = edge compounding over time.

═══ CONSTRAINTS ═══
- No internet access. All data is pre-fetched and provided.
- Hard safety rails always override: daily loss limit, max positions, MIS cutoff 15:15.
- You cannot execute — only decide. Return JSON decisions only.

Always respond with valid JSON only. No markdown, no extra text."""

    def _build_morning_prompt(self, data: Dict) -> str:
        # v1.2.0: Inject rolling history + lessons
        history_block = ""
        lessons_block = ""
        if self.memory_enabled:
            history_block = f"\nRECENT HISTORY (last {len(self.rolling_history)} days):\n  {self._format_history_for_prompt()}\n"
            if self.lessons:
                lessons_block = (
                    f"\nLESSONS LEARNED (apply these today — IDs shown for EOD validation):\n"
                    f"{self._format_lessons_for_prompt(compact=False)}\n"
                    f"  [Lesson IDs for EOD feedback: "
                    + ", ".join(
                        f"{l.get('id','?')}={l.get('type','?')}"
                        for l in self.lessons
                        if isinstance(l, dict) and l.get('type') != 'CODE_BUG'
                    )[:300]
                    + "]\n"
                )
            # Weekly directive hint
            if self.weekly_directive:
                wd = self.weekly_directive
                lessons_block += (f"\nWEEKLY THEME: {wd.get('week_theme','N/A')} | "
                                  f"Default regime: {wd.get('default_regime','NORMAL')} | "
                                  f"Focus: {','.join(wd.get('focus_phases', []))}\n")

        # v1.6.0: Monthly/trend context block
        _trend = data.get('nifty_trend', {})
        if isinstance(_trend.get('vs_20dma'), (int, float)):
            trend_label = _trend.get('trend', 'N/A')
            trend_block = (
                f"\nNIFTY TREND (multi-timeframe):\n"
                f"  Current: {_trend.get('current', 'N/A')}\n"
                f"  vs 20DMA: {_trend.get('vs_20dma', 0):+.2f}% | vs 50DMA: {_trend.get('vs_50dma', 0):+.2f}%\n"
                f"  Weekly change: {_trend.get('weekly_change', 0):+.2f}% | Monthly change: {_trend.get('monthly_change', 0):+.2f}%\n"
                f"  Structural trend: {trend_label} (UPTREND=price>20DMA>50DMA, DOWNTREND=inverse)\n"
            )
        else:
            trend_block = ""

        _vix_trend = data.get('vix_trend', 'N/A')
        _fii_trend = data.get('fii_5d_trend', 'N/A')
        trend_block += (f"  VIX 5-day trend: {_vix_trend}\n"
                       f"  FII 5-day flow: {_fii_trend}\n") if (_vix_trend != 'N/A' or _fii_trend != 'N/A') else ""

        # v1.6.0: Phase performance block
        phase_perf_block = f"\nPHASE PERFORMANCE:\n{self._format_phase_performance()}\n"

        return f"""MORNING BRIEFING — {date.today().strftime('%A, %B %d, %Y')}
{history_block}{lessons_block}
PORTFOLIO STATE:
  Capital Available: ₹{data.get('capital_available', 0):,.0f}
  Open Positions: {json.dumps(data.get('open_positions', {}), indent=2, default=str)[:1000]}
  Yesterday P&L: ₹{data.get('yesterday_pnl', 0):+,.0f}
  Week P&L: ₹{data.get('week_pnl', 0):+,.0f}
{phase_perf_block}
MARKET INDICATORS:
  Nifty Close: {data.get('nifty_close', 'N/A')}
  Nifty Change: {data.get('nifty_change_pct', 'N/A')}%
  India VIX: {data.get('vix', 'N/A')}
  FII/DII: {data.get('fii_dii', 'N/A')}
  SGX Nifty: {data.get('sgx_nifty', 'N/A')}
{trend_block}
PMBI (Pre-Market Breadth):
  {json.dumps(data.get('pmbi', {}), indent=2, default=str)[:500]}

SECTOR HEATMAP:
  {json.dumps(data.get('sector_heatmap', {}), indent=2, default=str)[:500]}

VIX REGIME GUIDE: LOW=<12, NORMAL=12-20, HIGH=20-25, EXTREME=>25
(Note: VIX 18-20 is elevated but NOT a blocking condition — PH5A operates normally up to VIX 22, PH5 skips only above 20. Reserve CAUTIOUS for VIX>20 + bearish Nifty combination, not VIX alone.)
ENTRY WINDOW GUIDE: 09:15=normal open; 09:45=volatile open (gap>1.5% or VIX HIGH); 10:00=extreme (gap>2.5% or VIX EXTREME)
STOP ATR MULT: 0.8=tighter stops (trend clear), 1.0=normal, 1.2=wider (choppy), max 2.0
TARGET ATR MULT: 0.8=take profits early, 1.0=normal, 1.5=let it run (strong trend), max 2.5
EXIT AGGRESSION: EARLY=exit at 80% of target (choppy day), NORMAL=full target, HOLD=trail after target
PH6 OPTIONS BIAS: CALL=bullish day (FII buying+gap-up), PUT=bearish day, NEUTRAL=mixed signals
PH2 MIN SCORE: 50=permissive (good trending day), 55=default, 65=selective (choppy), 70=very selective
PH5A SENSITIVITY: loose=more signals (trending), normal=default, tight=only top conviction (uncertain)
PH8 MOMENTUM THRESHOLD: 2.0=low bar, 3.0=default, 5.0=only strong momentum (volatile week)

Based on all the above, analyze the market situation holistically (yesterday context, weekly trend, monthly structure,
phase performance) and provide your morning strategic directive as a single JSON object:
{{
    "operation_mode": "NORMAL|CAUTIOUS|AGGRESSIVE|HALT",
    "max_positions": <int 1-5>,
    "phases_active": ["PH1", "PH2", "PH3", "PH4", "PH5", "PH5A", "PH8"],
    "market_bias": "BULLISH|BEARISH|NEUTRAL",
    "vix_regime": "LOW|NORMAL|HIGH|EXTREME",
    "sector_focus": ["up to 3 sectors showing strength today, e.g. IT, PHARMA, BANKING"],
    "sector_avoid": ["up to 2 sectors showing weakness today"],
    "entry_window_start": "HH:MM",
    "stop_atr_multiplier": <float 0.5-2.0>,
    "target_atr_multiplier": <float 0.5-2.5>,
    "exit_aggression": "EARLY|NORMAL|HOLD",
    "ph6_options_bias": "CALL|PUT|NEUTRAL",
    "risk_level": "LOW|MEDIUM|HIGH",
    "confidence": <int 0-100>,
    "ph2_min_score": <float 45-75>,
    "ph5a_sensitivity": "tight|normal|loose",
    "ph8_momentum_threshold": <float 2.0-8.0>,
    "notes": "<=15 words: market regime and key reason for these settings",
    "day_plan": "<=15 words: when to act, what to see, profit target",
    "unlock_conditions": "<=15 words: e.g. Nifty+1%, VIX<18, breadth>60%",
    "watch_stocks": "<=15 words: symbol and specific trigger to watch",
    "phase_directives": {{
        "PH5":  "ACTIVE|SKIP",
        "PH5A": "ACTIVE|PAUSE",
        "PH4":  "NORMAL|DEFENSIVE",
        "PH6":  "ACTIVE|HOLD",
        "PH8":  "HOLD|CLOSE_WEAKEST"
    }},
    "ph5_size_mult": <float 0.25-1.0 — VIX-tiered size for PH5: 1.0 if VIX<15, 0.75 if 15-20, 0.5 if 20-25, 0.25 if 25-30>,
    "ph5_stop_mult": <float 1.0-2.0 — VIX-tiered stop width: 1.0 if VIX<15, 1.3 if 15-20, 1.5 if 20-25, 2.0 if 25-30>,
    "ph8_watchlist_add": ["SYMBOL1", "SYMBOL2"],
    "position_actions": [
        {{"symbol": "RELIANCE", "action": "TIGHTEN_STOP|WATCH_CLOSELY|CLOSE", "reason": "<=15 words"}}
    ]
}}

PHASE DIRECTIVE GUIDE:
PH5  SKIP = gap strategy blocked. Use ONLY for VIX>30 (extreme panic), F&O expiry day, or circuit-breaker risk.
            VIX 18-25 is NOT a reason to skip — set ph5_size_mult and ph5_stop_mult instead.
            The system will override SKIP if VIX < 30; Claude's SKIP is only honoured in genuine extremes.
PH5A PAUSE = PVAT breakouts unreliable (choppy/low-volume market)
PH4  DEFENSIVE = tighten all open stops to 50% distance now (protect profits)
PH6  HOLD = silence options advisories today
PH8  CLOSE_WEAKEST = close the weakest weekly momentum position
ph2_min_score = raise on choppy/uncertain days to filter weak signals
ph5a_sensitivity = tight on uncertain days, loose on strong trending days
ph8_momentum_threshold = raise to 5+ on volatile/event-heavy weeks
ph8_watchlist_add = symbols showing weekly strength worth monitoring for next PH8 entry"""

    def _build_entry_prompt(self, signal: Dict, price: float, qty: int,
                            portfolio: Dict = None) -> str:
        symbol = signal.get('symbol', 'UNKNOWN')
        direction = signal.get('direction', signal.get('signal_type', 'BUY'))
        source = signal.get('source', signal.get('phase', 'UNKNOWN'))

        # Core signal fields
        composite_score = signal.get('composite_score', signal.get('score', 'N/A'))
        gap_pct   = signal.get('gap_pct', 'N/A')
        rsi       = signal.get('rsi', signal.get('rsi_14', 'N/A'))
        atr_raw   = signal.get('atr', None)
        atr_src   = signal.get('atr_source', 'daily')   # 'daily' or '15min'
        stop_price  = signal.get('stop_price',  signal.get('stop_loss', None))
        target_price = signal.get('target_price', signal.get('target', None))

        # Stop as % distance — critical for judging tightness
        if stop_price and price > 0:
            stop_dist_pct = abs(price - stop_price) / price * 100
            sl_str = f"₹{stop_price:.2f} ({stop_dist_pct:.1f}% away)"
        else:
            sl_str = str(stop_price or 'N/A')

        # Target as % upside
        if target_price and price > 0:
            tgt_dist_pct = abs(target_price - price) / price * 100
            tgt_str = f"₹{target_price:.2f} ({tgt_dist_pct:.1f}% away)"
        else:
            tgt_str = str(target_price or 'N/A')

        # ATR with source label so Claude can spot wrong-timeframe ATR
        atr_str = f"₹{atr_raw:.2f} [{atr_src}]" if atr_raw and atr_raw != 'N/A' else 'N/A'

        # Trend alignment data from signal (PH5A sets these via passes_elite_filter)
        trend_aligned = signal.get('trend_aligned', None)
        price_vs_ma20 = signal.get('price_vs_ma20', 'N/A')
        trend_label   = signal.get('trend_label', 'N/A')
        if trend_aligned is True:
            trend_str = f"ALIGNED ({price_vs_ma20} MA20) ✅"
        elif trend_aligned is False:
            trend_str = f"AGAINST TREND ({price_vs_ma20} MA20) ⚠️"
        else:
            trend_str = f"{trend_label} (no trend data in signal)"

        # Nifty intraday direction — not just daily %, but is it rising or falling NOW
        nifty_direction = getattr(self, '_live_nifty_direction', 'N/A')
        nifty_context = f"Nifty {self._live_nifty_chg}% day ({nifty_direction} intraday)"

        # Time context — critical for knowing entry window quality
        now_str = datetime.now().strftime('%H:%M')
        if datetime.now().hour < 10:
            time_ctx = f"{now_str} [IB forming — early, high momentum window]"
        elif datetime.now().hour < 11:
            time_ctx = f"{now_str} [prime entry window]"
        elif datetime.now().hour < 13:
            time_ctx = f"{now_str} [mid-session, momentum fading]"
        elif datetime.now().hour < 14:
            time_ctx = f"{now_str} [afternoon, lower probability]"
        else:
            time_ctx = f"{now_str} [late session — prefer exits over entries]"

        # Portfolio summary
        open_count = len(portfolio.get('positions', {})) if portfolio else 0
        open_symbols = list((portfolio or {}).get('positions', {}).keys())
        port_str = f"{open_count} open{(' (' + ','.join(open_symbols) + ')') if open_symbols else ''}"

        # v1.2.0: inject compact lessons
        lessons_line = ""
        if self.memory_enabled and self.inject_lessons_into_gates and self.lessons:
            lessons_line = f"\nLessons: {self._format_lessons_for_prompt(compact=True)[:800]}"

        return f"""ENTRY GATE: {symbol} {direction} @ ₹{price:.2f} x{qty} (₹{price*qty:,.0f})
Source:{source} | Score:{composite_score} | RSI:{rsi} | ATR:{atr_str}
SL:{sl_str} | TGT:{tgt_str} | Gap%:{gap_pct}
Trend:{trend_str}
Market: {nifty_context} | VIX:{self._live_vix} | Time:{time_ctx}
Portfolio:{port_str} | DailyP&L:₹{self.daily_pnl:+,.0f}/₹{self.max_daily_loss:,.0f} | {self.entries_approved}apr/{self.entries_blocked}blk | Regime:{self.todays_regime}
Note: size_adjustment scales qty (0.5=half). stop_adjustment overrides SL price if you want tighter/wider.{lessons_line}

JSON only:
{{"approved":true|false,"confidence":0-100,"size_adjustment":0.5-1.5,"stop_adjustment":null|<price>,"reasoning":"<=20 words"}}"""

    def _build_exit_prompt(self, symbol: str, position: Dict, reason: str,
                           context: Dict = None) -> str:
        entry_price = position.get('entry_price', 0)
        current_price = position.get('current_price', entry_price)
        direction = position.get('direction', 'LONG')
        stop_price = position.get('stop_price', 0)
        target_price = position.get('target_price', 0)
        quantity = position.get('quantity', 0)

        # P&L
        if direction == 'SHORT':
            pnl_pct = (entry_price - current_price) / entry_price * 100 if entry_price else 0
        else:
            pnl_pct = (current_price - entry_price) / entry_price * 100 if entry_price else 0

        # Kalman state
        kalman = position.get('kalman_state', {})
        velocity = kalman.get('velocity', 'N/A')
        acceleration = kalman.get('acceleration', 'N/A')

        # TCAS
        tcas = position.get('tcas_level', 'N/A')

        # Time context
        now = datetime.now()
        entry_time = position.get('entry_time', now)
        if isinstance(entry_time, str):
            try:
                entry_time = datetime.fromisoformat(entry_time)
            except:
                entry_time = now
        duration_min = (now - entry_time).total_seconds() / 60

        mis_min = max(0, (datetime.combine(now.date(), dt_time(15, 15)) - now).total_seconds() / 60)

        # v3.0.0: top lessons compact (exit gate — strategy lessons only, no CODE_BUG noise)
        lessons_line = ""
        if self.memory_enabled and self.inject_lessons_into_gates and self.lessons:
            lessons_line = f"\nLessons: {self._format_lessons_for_prompt(compact=True)[:500]}"

        # v1.3.2: Unpack enriched context (OHLCV/RSI/ATR/Kalman daily/OI walls)
        ctx = context or {}
        rsi         = ctx.get('rsi')
        atr         = ctx.get('atr')
        vwap_pos    = ctx.get('vwap_pos', 'N/A')
        ohlcv_5d    = ctx.get('ohlcv_5d', [])
        oi_walls    = ctx.get('oi_walls', {})
        kal_daily   = ctx.get('kalman_daily', {})

        tech_line = (f"RSI={rsi:.1f}" if rsi is not None else "RSI=N/A")
        tech_line += (f" ATR={atr:.2f}" if atr is not None else " ATR=N/A")
        tech_line += f" {vwap_pos}"

        oi_line = ""
        if oi_walls:
            oi_line = (f"\nOI: Put-support={oi_walls.get('put_wall','N/A')}"
                       f" Call-resist={oi_walls.get('call_wall','N/A')}"
                       f" MaxPain={oi_walls.get('max_pain','N/A')}"
                       f" PCR={oi_walls.get('pcr','N/A')}")

        kal_d_line = ""
        if kal_daily and kal_daily.get('available'):
            kal_d_line = (f"\nKalmanDaily: {kal_daily.get('daily_direction','N/A')}"
                          f" 1d=₹{kal_daily.get('pred_1day',0):.2f}"
                          f" 3d=₹{kal_daily.get('pred_3day',0):.2f}")

        ohlcv_line = ""
        if ohlcv_5d:
            rows = [f"{c['date']} C={c['c']}" for c in ohlcv_5d[-3:]]  # last 3 closes only
            ohlcv_line = "\n5D-closes: " + " | ".join(rows)

        return (
            f"EXIT GATE: {symbol} {direction} Ent:₹{entry_price:.2f} Cur:₹{current_price:.2f}"
            f" P&L:{pnl_pct:+.2f}% Qty:{quantity} Dur:{duration_min:.0f}m\n"
            f"SL:₹{stop_price:.2f} TGT:₹{target_price:.2f} TCAS:{tcas}"
            f" KalV:{velocity} KalA:{acceleration}\n"
            f"TECH: {tech_line}"
            f"{ohlcv_line}{oi_line}{kal_d_line}\n"
            f"Trigger:{reason} | MIS cutoff:{mis_min:.0f}m{lessons_line}\n"
            f"TRAIL rule: only if RSI<35 OR price at put-wall support AND stop≥ATR from current.\n\n"
            f"JSON only:\n"
            f'{{"action":"EXIT|HOLD|TRAIL","confidence":0-100,'
            f'"new_stop":null|<price>,"reasoning":"<=25 words"}}'
        )

    def _build_eod_prompt(self, summary: Dict) -> str:
        trades = summary.get('trades', [])
        trades_text = ""
        for t in trades[:10]:
            trades_text += (f"  {t.get('symbol', '?')}: {t.get('direction', '?')} "
                          f"₹{t.get('pnl', 0):+,.0f} ({t.get('pnl_pct', 0):+.2f}%) "
                          f"— {t.get('exit_reason', '?')}\n")

        journal_text = ""
        for j in summary.get('decision_journal', [])[-20:]:
            # decision may be a dict (full result) or a legacy string — stringify safely
            _dec = j.get('decision', '?')
            if isinstance(_dec, dict):
                _dec_str = json.dumps(_dec, default=str)[:500]
            else:
                _dec_str = str(_dec)[:500]
            journal_text += f"  [{j.get('time', '?')}] {j.get('type', '?')}: {j.get('symbol', '?')} — {_dec_str}\n"

        # v1.2.0: Include rolling history + existing lessons so Claude can
        # learn incrementally and avoid duplicate lessons.
        history_block = ""
        existing_lessons_block = ""
        if self.memory_enabled:
            history_block = f"\nRECENT HISTORY:\n  {self._format_history_for_prompt()}\n"
            if self.lessons:
                existing_lessons_block = (
                    f"\nEXISTING LESSONS (do NOT duplicate, propose only NEW ones):\n"
                    f"{self._format_lessons_for_prompt(compact=False)}\n")

        # Build lesson ID list so Claude can reference them in validations
        lesson_ids_block = ""
        if self.lessons:
            id_list = [
                f"{l.get('id','?')} → \"{l.get('text','')[:60]}...\""
                for l in self.lessons if isinstance(l, dict)
            ]
            lesson_ids_block = "\nLESSON IDs FOR VALIDATION:\n  " + "\n  ".join(id_list[:20]) + "\n"

        return f"""END-OF-DAY REVIEW — {date.today().strftime('%A, %B %d, %Y')}
{history_block}{existing_lessons_block}{lesson_ids_block}
PERFORMANCE:
  Total P&L: ₹{summary.get('total_pnl', 0):+,.0f}
  Trades Executed: {summary.get('trade_count', 0)}
  Win Rate: {summary.get('win_rate', 0):.0f}%
  Entries Approved: {summary.get('entries_approved', 0)}
  Entries Blocked: {summary.get('entries_blocked', 0)}
  Exits Advised: {summary.get('exits_advised', 0)}
  Regime: {summary.get('regime_today', 'NORMAL')}

TRADES:
{trades_text or '  No trades today.'}

DECISION JOURNAL:
{journal_text or '  No decisions recorded.'}

MISSED OPPORTUNITIES:
  {json.dumps(summary.get('missed_opportunities', [])[:5], indent=2, default=str)[:500]}

Review today's performance and provide JSON:
{{
    "performance_rating": <1-10>,
    "new_lessons": [
        {{
            "text": "concrete actionable rule (<=200 chars)",
            "type": "BIAS_DECISION|PHASE_GATE|SIGNAL_QUALITY|RISK_SIZING|TIMING|CODE_BUG|GENERAL",
            "confidence": <1-5: 5=certain from clear data, 3=probable, 1=speculative>,
            "source_event": "one sentence describing what happened today that generated this lesson"
        }}
    ],
    "lesson_validations": [
        {{
            "lesson_id": "<id from LESSON IDs FOR VALIDATION above>",
            "applied": <true if you consciously used this lesson today>,
            "helped": <true|false|null — did applying it improve the outcome?>,
            "note": "brief note on how it played out (<=50 chars)"
        }}
    ],
    "what_worked": "brief summary",
    "what_failed": "brief summary",
    "tomorrow_adjustments": {{
        "regime_suggestion": "NORMAL|CAUTIOUS|AGGRESSIVE",
        "size_suggestion": <0.5-1.5>,
        "focus_sectors": ["sector1", "sector2"]
    }},
    "journal_entry": "Your personal reflection as the fund manager (3-5 sentences)",
    "ph8_watchlist_add": ["SYMBOL1"]
}}

RULES for new_lessons:
- Propose 0-3 lessons ONLY if clearly supported by today's data
- type=CODE_BUG for anything that requires a code change (e.g. missing guard, broken parser, truncation)
- type=BIAS_DECISION for market_bias / regime call errors
- type=PHASE_GATE for PH2/PH5/PH5A signal filtering issues
- type=SIGNAL_QUALITY for stock selection or entry timing errors
- type=TIMING for entry/exit window issues
- confidence=5 only if cause-effect is unambiguous; confidence=3 if plausible but uncertain
- Do NOT restate existing lessons; propose only genuinely new insights"""

    # ═══════════════════════════════════════════════════════════════════════════
    # NETWORK GATING (v1.0.1)
    # ═══════════════════════════════════════════════════════════════════════════

    def _claude_available(self) -> bool:
        """
        Check if Claude is reachable before making API call.
        Returns False if:
        - No client initialized
        - No network (VPN dropped, DNS failing)
        - Daily budget exhausted

        Callers MUST check this before client.messages.create() to avoid
        hanging on anthropic's internal retry loop.
        """
        if not self.client:
            return False
        if self.budget_exhausted:
            return False
        if not _network_reachable("api.anthropic.com", 443, timeout=2.0):
            logger.warning("🌐 Network check failed — api.anthropic.com unreachable")
            return False
        return True

    # ═══════════════════════════════════════════════════════════════════════════
    # COST TRACKING (v1.1.0)
    # ═══════════════════════════════════════════════════════════════════════════

    def _model_tier(self, model: str) -> str:
        """Return 'haiku' or 'sonnet' based on model name."""
        if 'haiku' in model.lower():
            return 'haiku'
        return 'sonnet'

    def _track_cost(self, model: str, usage, call_type: str = 'unknown'):
        """
        Track API cost from a response's usage field.
        Updates daily totals and trips budget_exhausted if limit hit.
        """
        try:
            tier = self._model_tier(model)
            rates = self.COST_TABLE.get(tier, self.COST_TABLE['sonnet'])

            input_tokens = getattr(usage, 'input_tokens', 0) if usage else 0
            output_tokens = getattr(usage, 'output_tokens', 0) if usage else 0

            cost = (input_tokens / 1000.0 * rates['input_per_1k']
                    + output_tokens / 1000.0 * rates['output_per_1k'])

            self.daily_api_cost_inr += cost
            self.daily_api_calls += 1
            self.cost_by_type[call_type] = self.cost_by_type.get(call_type, 0.0) + cost

            logger.debug(f"   💰 PH9 cost: {call_type} on {tier} → "
                        f"{input_tokens}in/{output_tokens}out = ₹{cost:.3f} "
                        f"(daily total ₹{self.daily_api_cost_inr:.2f}/{self.max_daily_api_cost:.0f})")

            # Budget check
            if self.daily_api_cost_inr >= self.max_daily_api_cost:
                if not self.budget_exhausted:
                    self.budget_exhausted = True
                    logger.warning(f"💰🛑 PH9 BUDGET EXHAUSTED: "
                                  f"₹{self.daily_api_cost_inr:.2f} ≥ ₹{self.max_daily_api_cost:.0f} "
                                  f"({self.daily_api_calls} calls) — no more Claude calls today")
                    if self.telegram:
                        breakdown = '\n'.join([f"  {k}: ₹{v:.2f}"
                                              for k, v in sorted(self.cost_by_type.items(),
                                                                 key=lambda x: -x[1])])
                        self.telegram.send_message(
                            f"💰 FUND MANAGER — BUDGET EXHAUSTED\n\n"
                            f"Today's cost: ₹{self.daily_api_cost_inr:.2f}\n"
                            f"Budget: ₹{self.max_daily_api_cost:.0f}\n"
                            f"Calls: {self.daily_api_calls}\n\n"
                            f"Breakdown:\n{breakdown}\n\n"
                            f"No more Claude calls today. Rules-based fallback active."
                        )

            # Call count check (separate safety)
            if self.daily_api_calls >= self.max_daily_call_count and not self.budget_exhausted:
                self.budget_exhausted = True
                logger.warning(f"📞🛑 PH9 CALL LIMIT HIT: {self.daily_api_calls} calls today")

        except Exception as e:
            logger.debug(f"Cost tracking error: {e}")

    # ═══════════════════════════════════════════════════════════════════════════
    # UTILITY METHODS
    # ═══════════════════════════════════════════════════════════════════════════
    # UTILITY METHODS
    # ═══════════════════════════════════════════════════════════════════════════

    def _extract_json(self, text: str) -> dict:
        """Extract and parse the first valid JSON object from a Claude response.

        Handles raw JSON, code-fenced JSON, and JSON embedded in prose.
        Raises ValueError if no valid JSON object is found.
        """
        import json as _j
        import re as _r
        original = text

        # 1. Code fence
        m = _r.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, _r.DOTALL)
        if m:
            try:
                return _j.loads(m.group(1))
            except _j.JSONDecodeError:
                pass

        # 2. Brace-matched span
        start = text.find('{')
        if start != -1:
            depth = 0
            for i, ch in enumerate(text[start:], start):
                if ch == '{':
                    depth += 1
                elif ch == '}':
                    depth -= 1
                    if depth == 0:
                        candidate = text[start:i + 1]
                        try:
                            return _j.loads(candidate)
                        except _j.JSONDecodeError:
                            cleaned = _r.sub(r',\s*([}\]])', r'\1', candidate)
                            try:
                                return _j.loads(cleaned)
                            except _j.JSONDecodeError:
                                pass
                        break

        # 3. Whole text
        try:
            return _j.loads(text.strip())
        except _j.JSONDecodeError:
            pass

        raise ValueError(f"Could not extract JSON from response: {original[:300]}")

    def _get_current_directives(self) -> dict:
        """Return current directives without making a Claude API call.
        Used as a fast fallback when heartbeat/briefing is skipped.
        """
        return {
            'operation_mode':   self.todays_regime,
            'market_bias':      self.todays_market_bias,
            'phase_directives': {
                'PH5':  self.todays_ph5_directive,
                'PH5A': self.todays_ph5a_directive,
                'PH4':  self.todays_ph4_directive,
                'PH6':  self.todays_ph6_directive,
                'PH8':  self.todays_ph8_directive,
            },
            'next_cycle_actions': [],
            'approved_signals':   [],
            'position_actions':   [],
            'ph8_watchlist_add':  self.todays_ph8_watchlist_add[:],
            'ph5_size_mult':      self.todays_ph5_size_mult,
            'ph5_stop_mult':      self.todays_ph5_stop_mult,
            'reasoning':          'Directives carried forward (no Claude call)',
            'situation':          '',
            'watching':           '',
            'opportunity':        '',
            'next_action':        '',
        }

    def _journal(self, decision_type: str, symbol: str, result: dict):
        """Add entry to in-memory decision journal.

        v3.0.0: stores the full result dict without truncation.
        The old str(result)[:300] caused the 2026-04-21 silent failure
        where MORNING_BRIEFING was cut mid-field in the journal record,
        making Phase9 EOD diagnose the wrong root cause.
        """
        from datetime import datetime as _dt
        self.decision_journal.append({
            'time':      _dt.now().strftime('%H:%M:%S'),
            'type':      decision_type,
            'symbol':    symbol,
            'decision':  result,
            'timestamp': _dt.now().isoformat(),
        })

    def _log_to_db(self, analysis_type: str, symbol: str, context: dict,
                   response: dict, prompt_snippet: str = None):
        """Log a Phase 9 decision to the database (best-effort, never raises)."""
        try:
            import logging as _log
            _log.getLogger(__name__).debug(
                f"PH9 DB log: {analysis_type} {symbol}")
        except Exception as e:
            try:
                import logging as _log
                _log.getLogger(__name__).debug(f"PH9 DB log failed: {e}")
            except Exception:
                pass

    def _save_journal_to_file(self, today, eod_result: dict):
        """Persist today's decision journal and EOD review to a dated JSON file."""
        import json as _j
        import os as _os
        import logging as _log
        _logger = _log.getLogger(__name__)
        try:
            journal_dir = _os.path.join('data', 'fund_manager')
            _os.makedirs(journal_dir, exist_ok=True)
            filepath = _os.path.join(journal_dir, f'journal_{today}.json')
            journal_data = {
                'date':              str(today),
                'daily_pnl':        self.daily_pnl,
                'trades_today':     self.trades_today,
                'entries_approved': self.entries_approved,
                'entries_blocked':  self.entries_blocked,
                'exits_advised':    self.exits_advised,
                'regime':           self.todays_regime,
                'eod_review':       eod_result,
                'decision_journal': self.decision_journal,
            }
            with open(filepath, 'w', encoding='utf-8') as f:
                _j.dump(journal_data, f, indent=2, default=str)
            _logger.info(f"   Journal saved: {filepath}")
        except Exception as e:
            _logger.error(f"Failed to save journal: {e}")

    def get_briefing(self) -> dict:
        """Return current morning briefing parameters as a flat dict.

        Called by the orchestrator to push directives into sub-phases.
        Guard: check 'briefing_done' before consuming values.
        """
        return {
            'briefing_done':          self._morning_briefing_done,
            'operation_mode':         self.todays_regime,
            'market_bias':            self.todays_market_bias,
            'vix_regime':             self.todays_vix_regime,
            'max_positions':          self.todays_max_positions,
            'phases_active':          self.todays_phases_active,
            'sector_focus':           self.todays_sector_focus,
            'sector_avoid':           self.todays_sector_avoid,
            'entry_window_start':     self.todays_entry_window,
            'stop_atr_multiplier':    self.todays_stop_atr_mult,
            'target_atr_multiplier':  self.todays_target_atr_mult,
            'exit_aggression':        self.todays_exit_aggression,
            'ph6_options_bias':       self.todays_ph6_options_bias,
            'risk_level':             self.todays_risk_level,
            'confidence':             self.todays_confidence,
            'ph2_min_score':          self.todays_ph2_min_score,
            'ph5a_sensitivity':       self.todays_ph5a_sensitivity,
            'ph8_momentum_threshold': self.todays_ph8_momentum_threshold,
            'ph5_size_mult':          self.todays_ph5_size_mult,
            'ph5_stop_mult':          self.todays_ph5_stop_mult,
            'notes':                  self.todays_notes,
            'day_plan':               self.todays_day_plan,
            'unlock_conditions':      self.todays_unlock_conditions,
            'watch_stocks':           self.todays_watch_stocks,
            'ph5_directive':          self.todays_ph5_directive,
            'ph5a_directive':         self.todays_ph5a_directive,
            'ph4_directive':          self.todays_ph4_directive,
            'ph6_directive':          self.todays_ph6_directive,
            'ph8_directive':          self.todays_ph8_directive,
        }
