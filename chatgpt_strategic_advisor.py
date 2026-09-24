"""
CHATGPT_STRATEGIC_ADVISOR.PY - AI-Powered Trading Decisions v3.4.0
═══════════════════════════════════════════════════════════════════════════════

v3.4.0 UPGRADE: SQLite Database Integration
────────────────────────────────────────────
- All AI consultations logged to database
- Query: "Show me all HOLD decisions this week"
- Track ChatGPT accuracy over time

Uses ChatGPT for HIGH-LEVEL strategic decisions:
├─ Entry Signal Approval (with Kalman predictions)
├─ Fund Management (position sizing based on market conditions)
├─ Exit Timing (Fibonacci levels, support/resistance analysis)
├─ Order Parameters (dynamic stop-loss/targets)
├─ Portfolio Risk Management (overall exposure, correlation)
├─ Adaptive Scan Decisions
├─ End-of-Day Shutdown Decisions
└─ PHASE 4: Position Exit Evaluation & Landing Probability

Author: Dheebanraj
Version: 3.4.0
Date: 2026-02-04
"""

import anthropic
import logging
import re
from trader_persona import TRADER_PERSONA
from typing import Dict, List, Optional, Tuple
from datetime import datetime
import json

# v3.4.0 NEW: Database import
try:
    from unified_data_manager import get_db, UnifiedDataManager
    DATABASE_AVAILABLE = True
except ImportError:
    DATABASE_AVAILABLE = False
    get_db = None

logger = logging.getLogger('ChatGPT_Strategic_Advisor')


class ChatGPTStrategicAdvisor:
    """
    AI-powered strategic advisor for trading decisions.
    
    Uses ChatGPT for:
    ├─ Entry approval (Kalman predictions)
    ├─ Position sizing (market conditions, volatility)
    ├─ Exit strategy (Fibonacci, S/R levels, time-based)
    ├─ Order parameters (stops, targets, trailing)
    ├─ Portfolio management (correlation, exposure)
    ├─ Adaptive scan decisions
    ├─ Shutdown decisions
    └─ PHASE 4: Exit evaluation, Landing probability, Morning briefing (NEW!)
    """
    
    def __init__(self, api_key: str, model: str = "claude-fable-5-1"):
        """
        Initialize ChatGPT strategic advisor.
        
        Args:
            api_key: OpenAI API key
            model: Model to use (claude-fable-5-1 recommended)
        """
        self.api_key = api_key
        self.model = model
        self.client = anthropic.Anthropic(api_key=api_key, timeout=30.0, max_retries=1)
        
        logger.info("=" * 80)
        logger.info("🤖 CHATGPT STRATEGIC ADVISOR v3.2 (Enhanced Entry Data)")
        logger.info("=" * 80)
        logger.info(f"   Model: {model}")
        logger.info("")
        logger.info("Capabilities:")
        logger.info("  ✅ Entry signal approval (with Kalman)")
        logger.info("  ✅ Dynamic position sizing")
        logger.info("  ✅ Exit level calculation")
        logger.info("  ✅ Adaptive scan decisions")
        logger.info("  ✅ Shutdown decisions")
        logger.info("  ✅ Phase 4: Exit evaluation (NEW)")
        logger.info("  ✅ Phase 4: Landing probability (NEW)")
        logger.info("  ✅ Phase 4: Morning briefing (NEW)")
        logger.info("=" * 80)
        
        # Track conversation history
        self.conversation_history = []

        # v3.4.0 NEW: Database connection
        self._db = None
        if DATABASE_AVAILABLE:
            try:
                self._db = get_db()
                logger.info("✅ ChatGPT Advisor connected to SQLite database")
            except Exception as e:
                logger.warning(f"⚠️ Database not available: {e}")

        # v5.5: ChatGPT mode (LANDMINE_ONLY or FULL_ANALYSIS)
        try:
            from config import AlgoConfig
            self._chatgpt_mode = getattr(AlgoConfig, 'CHATGPT_MODE', 'LANDMINE_ONLY')
        except Exception:
            self._chatgpt_mode = 'LANDMINE_ONLY'
        logger.info(f"   ChatGPT Mode: {self._chatgpt_mode}")


    def _log_ai_analysis(self, analysis_type: str, symbol: str, context: Dict, 
                        response: Dict, prompt_snippet: str = None):
        """
        v3.4.0 NEW: Log AI analysis to database.
        
        Args:
            analysis_type: 'ENTRY_REVIEW', 'EXIT_EVALUATION', 'POSITION_SIZING', etc.
            symbol: Stock symbol or 'PORTFOLIO' for general analysis
            context: Input data sent to ChatGPT
            response: ChatGPT response (parsed JSON)
            prompt_snippet: First 500 chars of prompt for reference
        """
        if not hasattr(self, '_db') or not self._db:
            return
        
        try:
            self._db.save_ai_analysis(
                analysis_type=analysis_type,
                symbol=symbol,
                context=context,
                response=response,
                model=self.model,
                prompt_snippet=prompt_snippet
            )
        except Exception as e:
            logger.debug(f"AI analysis log failed: {e}")
    
    
    # ═══════════════════════════════════════════════════════════════════════════
    # GENERIC PROMPT → RESPONSE (Used by Phase 5 for ad-hoc decisions)
    # ═══════════════════════════════════════════════════════════════════════════

    def get_decision(self, prompt: str) -> Optional[str]:
        """
        Send a free-form prompt to ChatGPT and return the raw response text.

        Used by Phase 5 for post-entry assessments and pre-entry approvals
        where the caller builds the prompt and parses the response themselves.
        """
        try:
            response = self.client.messages.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=500,
            )
            return response.content[0].text.strip()
        except Exception as e:
            logger.warning(f"ChatGPT get_decision failed: {e}")
            return None

    # ═══════════════════════════════════════════════════════════════════════════
    # DECISION #1: ENTRY SIGNAL APPROVAL (Most Critical)
    # ═══════════════════════════════════════════════════════════════════════════
    
    def review_entry_signal(
        self,
        symbol: str,
        entry_price: float,
        rsi: float,
        rsi_threshold: float,
        sentiment: Dict,
        market_regime: str,
        technical_score: float,
        intelligent_score: float = 0,
        v_recovery_data: Dict = None,
        volume_ratio: float = 1.0,
        nifty_change_pct: float = 0,
        kalman_prediction: Dict = None,
        # v3.2.0 NEW PARAMETERS:
        rsi_history: List[float] = None,
        adx_value: float = None,
        volume_spike_at_reversal: float = None,
        entry_score: float = None,
        finbert_contribution: int = None,
        **kwargs
    ) -> Dict:
        """
        ✅ ENHANCED v3.2.0: Review entry signal with ALL calculated data.
        
        Called BEFORE Phase 3 execution to get AI strategic approval.
        Now receives comprehensive data for smarter GO/NOGO decisions!
        
        Args:
            symbol: Stock symbol
            entry_price: Proposed entry price
            rsi: Current RSI value
            rsi_threshold: Adaptive RSI threshold for this stock
            sentiment: FinBERT sentiment data
            market_regime: Market regime from Intelligent Engine
            technical_score: Technical score (0-100)
            intelligent_score: Intelligent Engine total score (0-100)
            v_recovery_data: V-Recovery pattern data if available
            volume_ratio: Current volume vs average ratio
            nifty_change_pct: NIFTY 50 change percentage today
            kalman_prediction: Kalman filter predictions
            
            NEW v3.2.0:
            rsi_history: Last 4 RSI readings [oldest..newest]
            adx_value: ADX value (trend strength)
            volume_spike_at_reversal: Volume spike ratio at RSI bottom
            entry_score: Composite entry score (0-100)
            finbert_contribution: Points from FinBERT sentiment
            
        Returns:
            {
                'decision': 'ENTER' | 'SKIP' | 'WAIT',
                'confidence': 0-100,
                'reasoning': str,
                'risk_notes': str,
                'suggested_position_pct': 0.5-2.0,
                'suggested_stop_pct': -2.0 to -3.0,
                'suggested_target_pct': 2.0 to 4.0
            }
        """
        # v5.5: Route based on CHATGPT_MODE config
        chatgpt_mode = getattr(self, '_chatgpt_mode', 'LANDMINE_ONLY')

        # MIE v1.0.0: Append intelligence package to chatgpt_package if present
        chatgpt_pkg = kwargs.get('chatgpt_package', '')
        mie_ip = kwargs.get('intelligence_package')
        if mie_ip and chatgpt_pkg:
            mie_entry_section = self._build_mie_prompt_section(mie_ip)
            if mie_entry_section:
                chatgpt_pkg = chatgpt_pkg + "\n" + mie_entry_section

        if chatgpt_mode == 'LANDMINE_ONLY' and kwargs.get('chatgpt_package'):
            return self.review_entry_signal_v55(
                symbol=symbol,
                entry_price=entry_price,
                entry_score=entry_score or technical_score,
                chatgpt_package=chatgpt_pkg,
            )
        elif kwargs.get('chatgpt_package'):
            return self.review_entry_signal_v532(
                symbol=symbol,
                chatgpt_package=chatgpt_pkg,
                entry_price=entry_price,
                entry_score=entry_score or technical_score,
            )

        logger.info(f"ChatGPT STRATEGIC REVIEW: {symbol}")
        logger.info(f"   Price: {entry_price:.2f}")
        logger.info(f"   RSI: {rsi:.1f} (threshold: {rsi_threshold:.1f})")
        logger.info(f"   Sentiment: {sentiment.get('label', 'UNKNOWN')}")
        logger.info(f"   Entry Score: {entry_score:.0f}/100" if entry_score else "   Entry Score: N/A")

        if kalman_prediction:
            logger.info(f"   Kalman: {kalman_prediction.get('trend', 'UNKNOWN')}")
        if adx_value is not None:
            logger.info(f"   ADX: {adx_value:.1f} ({'RANGING' if adx_value < 25 else 'TRENDING'})")
        
        try:
            # Build V-Recovery context
            v_recovery_text = ""
            if v_recovery_data:
                recovery_pct = v_recovery_data.get('recovery_pct', 0)
                # Determine Fibonacci level
                if recovery_pct >= 76.4:
                    fib_level = "78.6% (Deep)"
                elif recovery_pct >= 61.8:
                    fib_level = "61.8% (Golden Ratio) ✨"
                elif recovery_pct >= 50:
                    fib_level = "50.0% (Midpoint)"
                elif recovery_pct >= 38.2:
                    fib_level = "38.2% (Shallow)"
                else:
                    fib_level = f"{recovery_pct:.0f}% (Weak)"
                
                v_recovery_text = f"""
📊 V-RECOVERY PATTERN:
- Drop from high: {v_recovery_data.get('drop_pct', 0):.1f}%
- Recovery: {recovery_pct:.1f}%
- Fibonacci Level: {fib_level}
- Quality: {v_recovery_data.get('quality', 'Unknown')}
"""
            
            # Build Kalman predictions context
            kalman_text = ""
            if kalman_prediction:
                kalman_text = f"""
🔬 KALMAN FILTER PREDICTIONS (15-min ahead):
- Predicted Price: ₹{kalman_prediction.get('price_15min', 0):.2f}
- Expected Move: {kalman_prediction.get('expected_move_pct', 0):+.2f}%
- Velocity: {kalman_prediction.get('velocity', 0):+.2f} ₹/tick ({"UP ↑" if kalman_prediction.get('velocity', 0) > 0 else "DOWN ↓"})
- Acceleration: {kalman_prediction.get('acceleration', 0):+.2f} ({"Accelerating 🚀" if kalman_prediction.get('acceleration', 0) > 0 else "Decelerating ⚠️"})
- Trend: {kalman_prediction.get('trend', 'UNKNOWN')}
- Confidence: {kalman_prediction.get('confidence', 0):.0f}%
"""
            
            # v3.2.0: Build RSI momentum context
            rsi_momentum_text = ""
            if rsi_history and len(rsi_history) >= 4:
                rsi_sequence = " → ".join([f"{r:.1f}" for r in rsi_history[-4:]])
                total_rise = rsi_history[-1] - rsi_history[0] if len(rsi_history) >= 2 else 0
                rsi_momentum_text = f"""
📈 RSI MOMENTUM SEQUENCE:
- Last 4 readings: {rsi_sequence}
- Total rise: {total_rise:+.1f} points
- Pattern: {"RISING ✅" if all(rsi_history[i] < rsi_history[i+1] for i in range(len(rsi_history)-1)) else "MIXED ⚠️"}
"""
            
            # v3.2.0: Build ADX context
            adx_text = ""
            if adx_value is not None:
                if adx_value < 20:
                    adx_assessment = "WEAK/NO TREND - Perfect for V-Recovery! ✅"
                elif adx_value < 25:
                    adx_assessment = "RANGING - V-Recovery should work ✅"
                elif adx_value < 40:
                    adx_assessment = "TRENDING - V-Recovery may struggle ⚠️"
                else:
                    adx_assessment = "STRONG TREND - V-Recovery NOT recommended ❌"
                
                adx_text = f"""
📊 ADX TREND FILTER:
- ADX Value: {adx_value:.1f}
- Assessment: {adx_assessment}
"""
            
            # v3.2.0: Build volume spike context
            volume_spike_text = ""
            if volume_spike_at_reversal is not None:
                if volume_spike_at_reversal >= 2.0:
                    spike_assessment = "STRONG SPIKE - Institutional buying confirmed! ✅"
                elif volume_spike_at_reversal >= 1.5:
                    spike_assessment = "MODERATE SPIKE - Some buying interest ⚠️"
                else:
                    spike_assessment = "NO SPIKE - Weak reversal signal ❌"
                
                volume_spike_text = f"""
📊 VOLUME AT RSI REVERSAL:
- Spike Ratio: {volume_spike_at_reversal:.1f}x average
- Assessment: {spike_assessment}
"""
            
            # v3.2.0: Build entry score context
            entry_score_text = ""
            if entry_score is not None:
                if entry_score >= 75:
                    score_assessment = "STRONG BUY - High confidence setup!"
                elif entry_score >= 60:
                    score_assessment = "MODERATE BUY - Decent setup"
                elif entry_score >= 50:
                    score_assessment = "WEAK BUY - Marginal setup"
                else:
                    score_assessment = "SKIP - Below threshold"
                
                finbert_text = ""
                if finbert_contribution is not None:
                    finbert_text = f"\n- FinBERT contribution: {finbert_contribution:+d} pts"
                
                entry_score_text = f"""
🎯 COMPOSITE ENTRY SCORE:
- Total Score: {entry_score:.0f}/100
- Assessment: {score_assessment}{finbert_text}
"""
            
            prompt = f"""You are a professional intraday trader reviewing an entry signal for the Indian NSE market.

═══════════════════════════════════════════════════════════════════════════════
ENTRY SIGNAL DATA (v3.2 - COMPREHENSIVE)
═══════════════════════════════════════════════════════════════════════════════

BASIC INFO:
- Symbol: {symbol}
- Entry Price: ₹{entry_price:.2f}
- Current Time: {datetime.now().strftime('%H:%M')} IST

RSI ANALYSIS:
- Current RSI: {rsi:.1f}
- Stock's Adaptive Threshold: {rsi_threshold:.1f}
- Position: RSI {"ABOVE ✅" if rsi > rsi_threshold else "BELOW"} threshold
{rsi_momentum_text}
SENTIMENT:
- FinBERT Label: {sentiment.get('label', 'NEUTRAL')}
- Sentiment Score: {sentiment.get('sentiment_score', sentiment.get('score', 0)):.2f}
- Confidence: {sentiment.get('confidence', 50)}%

MARKET CONTEXT:
- Market Regime: {market_regime}
- NIFTY 50 Today: {nifty_change_pct:+.2f}%
- Volume Ratio: {volume_ratio:.2f}x average
{adx_text}{volume_spike_text}{v_recovery_text}{kalman_text}{entry_score_text}
SCORES:
- Technical Score: {technical_score:.0f}/100
- Intelligent Engine Score: {intelligent_score:.0f}/100
{self._build_mie_prompt_section(mie_ip) if mie_ip else ''}
═══════════════════════════════════════════════════════════════════════════════
YOUR TASK: GO or NOGO?
═══════════════════════════════════════════════════════════════════════════════

Based on ALL the data above, decide: Should we ENTER this trade?

CRITICAL DECISION RULES:
1. ADX > 25 (trending) + V-Recovery strategy → SKIP (mean reversion fails in trends!)
2. Volume spike < 1.5x at reversal → SKIP (no institutional buying)
3. Kalman velocity NEGATIVE → SKIP (downtrend)
4. Entry score < 50 → SKIP (below threshold)
5. NIFTY < -0.5% + bearish sentiment → SKIP (swimming upstream)

ADX CONTEXT (use this to weigh your decision):
- ADX < 20: Strong V-Recovery zone, favor ENTER
- ADX 20-25: V-Recovery viable, normal position size
- ADX 25-30: V-Recovery risky, need strong volume + Kalman confirmation to ENTER
- ADX > 30: V-Recovery likely fails, favor SKIP unless exceptional setup
- If ADX is falling (was higher recently): Trend weakening, V-Recovery becoming viable

STRONG ENTRY SIGNALS:
1. ADX < 25 (ranging) + RSI above threshold + Volume spike 2x+ → ENTER!
2. Kalman velocity positive + acceleration positive → ENTER!
3. Recovery at 61.8% Fibonacci + bullish sentiment → ENTER!
4. Entry score > 75 + all filters pass → ENTER!

MIE INTELLIGENCE RULES (if Market Intelligence data present above):
- ADX < 25 (RANGING) + VWAP WITHIN_1σ + Recovery at Fibonacci → Strong ENTER
- ADX > 25 (TRENDING DOWN) + Price BELOW_2σ of VWAP → Strong SKIP
- Stochastic BULLISH_CROSS in OVERSOLD zone + MACD BULLISH_CROSS → Strong ENTER signal
- RESPECT Composite Score ranking — higher ranked stock gets priority
- CHECK real performance data — if backtest_vs_real_gap > 10%, discount confidence
- CHECK capital state — don't recommend what can't be executed
- FOLLOW the Context Instruction for this phase/product combination

Respond in JSON format:
{{
    "decision": "ENTER" or "SKIP" or "WAIT",
    "confidence": 0-100,
    "reasoning": "Brief explanation focusing on KEY deciding factors (max 100 words)",
    "risk_notes": "Key risks to watch",
    "suggested_position_pct": 0.5 to 2.0,
    "suggested_stop_pct": -2.0 to -3.0,
    "suggested_target_pct": 2.0 to 4.0
}}

Position sizing guide:
- 2.0 = Very strong (ADX<20, volume spike 2x+, Kalman bullish, entry score >75)
- 1.5 = Strong (good setup, positive momentum)
- 1.0 = Normal (standard conditions)
- 0.75 = Weak (marginal setup, some concerns)
- 0.5 = Very weak (high risk, use caution)
"""
            
            response = self.client.messages.create(
                model=self.model,
                system="You are an expert intraday trading advisor. Respond only in valid JSON format. Be decisive - give clear GO or NOGO.",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=500
            )
            
            content = response.content[0].text.strip()
            decision = self._extract_json(content)
            
            # Validate decision
            if decision.get('decision') not in ['ENTER', 'SKIP', 'WAIT']:
                decision['decision'] = 'SKIP'
            
            # Ensure position_pct is reasonable
            pos_pct = decision.get('suggested_position_pct', 1.0)
            decision['suggested_position_pct'] = max(0.5, min(2.0, pos_pct))
            
            logger.info(f"   Decision: {decision['decision']}")
            logger.info(f"   Confidence: {decision.get('confidence', 0)}%")
            logger.info(f"   Position: {decision['suggested_position_pct']}x")
            logger.info(f"   Reasoning: {decision.get('reasoning', 'N/A')[:100]}")
            
            # Track in history
            self.conversation_history.append({
                'timestamp': datetime.now().isoformat(),
                'type': 'entry_review_v3.2',
                'symbol': symbol,
                'decision': decision['decision'],
                'confidence': decision.get('confidence', 0),
                'entry_score': entry_score,
                'adx': adx_value
            })
            
            
            # v3.4.0 NEW: Log to database
            self._log_ai_analysis(
                analysis_type='ENTRY_REVIEW',
                symbol=symbol,
                context={
                    'entry_price': entry_price,
                    'rsi': rsi,
                    'rsi_threshold': rsi_threshold,
                    'technical_score': technical_score,
                    'intelligent_score': intelligent_score,
                    'volume_ratio': volume_ratio,
                    'market_regime': market_regime,
                    'entry_score': entry_score
                },
                response=decision
            )
            
            return decision
            
        except Exception as e:
            logger.error(f"❌ ChatGPT entry review failed: {e}")
            # Fail-closed: AI gate failure must block entry. The AI gate exists to add judgment
            # beyond technical score. Bypassing it on failure defeats its purpose and creates
            # a silent risk-control degradation that is harder to detect than a hard block.
            return {
                'decision': 'SKIP',
                'confidence': 0,
                'reasoning': f'AI entry gate unavailable ({str(e)}). Blocking entry until AI is reachable.',
                'risk_notes': 'AI unavailable - fail-closed for safety',
                'suggested_position_pct': 0.0,
                'suggested_stop_pct': -2.0,
                'suggested_target_pct': 2.0
            }
    
    # ═══════════════════════════════════════════════════════════════════════════
    # DECISION #1C: v5.5 LANDMINE-ONLY ENTRY REVIEW (2 web searches)
    # ═══════════════════════════════════════════════════════════════════════════

    def review_entry_signal_v55(
        self,
        symbol: str,
        entry_price: float,
        entry_score: float = 0,
        chatgpt_package: str = '',
    ) -> Dict:
        """
        v5.5: LANDMINE-ONLY entry review.
        Searches for disqualifiers only. Does NOT evaluate technicals.
        Does NOT return S/R levels, stops, or targets.

        Returns:
            {
                'decision': 'ENTER' or 'SKIP',
                'confidence': int (entry_score passed through if ENTER),
                'reasoning': str,
                'risk_notes': str,
                'web_news': str,
                'delivery_signal': str,
                'oi_signal': str,
                'landmine_found': bool,
                'landmine_type': str or None,
            }
        """
        logger.info(f"ChatGPT v5.5 REVIEW (landmine-only): {symbol}")

        system_prompt = """You are a Risk Screening Agent for NSE intraday trading.
Your ONLY job: Check if this stock has any disqualifying news.
You are NOT a technical analyst. Do NOT evaluate the trade setup.
If no disqualifiers found, return ENTER with the score package confidence.
Respond in valid JSON format only."""

        prompt = f"""STOCK: {symbol} at ₹{entry_price:.2f}
SYSTEM SCORE: {entry_score:.0f}/100 (already validated by our scoring engine)

STEP 1 — WEB SEARCH (do BOTH):

Search 1: "{symbol} NSE news today"
  CHECK FOR AUTOMATIC DISQUALIFIERS:
  - Stock in ASM/GSM surveillance
  - Trading halt or suspension
  - SEBI investigation or fraud allegations
  - Earnings miss or profit warning (today/yesterday)
  - Promoter pledge increase or insider selling
  - Bulk/block deal indicating institutional exit
  - Merger/acquisition uncertainty
  - Credit downgrade

Search 2: "{symbol} delivery percentage open interest NSE"
  EXTRACT:
  - Delivery % > 50% = "HIGH_DELIVERY", < 30% = "LOW_DELIVERY", else "UNKNOWN"
  - OI interpretation: Price UP+OI UP = "LONG_BUILDUP", Price DOWN+OI UP = "SHORT_BUILDUP",
    Price DOWN+OI DOWN = "LONG_UNWINDING", Price UP+OI DOWN = "SHORT_COVERING", else "UNKNOWN"

STEP 2 — DECISION:
- Any disqualifier found → SKIP with reason
- LOW_DELIVERY + SHORT_BUILDUP together → SKIP (weak hands + bearish conviction)
- No disqualifiers → ENTER (pass through system score as confidence)
- DO NOT evaluate entry quality, support/resistance, or technical patterns
- DO NOT suggest stop or target prices

SCORE PACKAGE (for context only, do NOT override):
{chatgpt_package}

Respond in JSON:
{{
    "decision": "ENTER" or "SKIP",
    "confidence": {entry_score:.0f} if ENTER else 30,
    "reasoning": "max 50 words",
    "risk_notes": "any caution flags, max 30 words",
    "web_news": "news summary, max 30 words",
    "delivery_signal": "HIGH_DELIVERY" or "LOW_DELIVERY" or "UNKNOWN",
    "oi_signal": "LONG_BUILDUP" or "SHORT_BUILDUP" or "LONG_UNWINDING" or "SHORT_COVERING" or "UNKNOWN",
    "landmine_found": true or false,
    "landmine_type": "ASM" or "EARNINGS_MISS" or "INSIDER_SELLING" etc, or null
}}
"""

        content = None

        # ─── PRIMARY: messages.create with web search ───
        try:
            response = self.client.messages.create(
                model=self.model,
                system=system_prompt,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=1024,
                tools=[{"type": "web_search_20260209", "name": "web_search"}]
            )
            content = next((b.text for b in response.content if b.type == "text"), None)
            logger.info(f"   v5.5 Responses API + web search succeeded for {symbol}")
        except Exception as e:
            logger.warning(f"v5.5 Responses API failed for {symbol}: {e}, falling back to Chat Completions")

        # ─── FALLBACK 1: Chat Completions without web search ───
        if content is None:
            try:
                response = self.client.messages.create(
                    model=self.model,
                    system=system_prompt,
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=400
                )
                content = response.content[0].text.strip()
                logger.info(f"   v5.5 Chat Completions fallback succeeded for {symbol}")
            except Exception as e2:
                logger.error(f"v5.5 Both APIs failed for {symbol}: {e2}")

        # ─── FALLBACK 2: Score-based decision ───
        if content is None:
            logger.warning(f"   v5.5 All APIs failed -- using score-based decision for {symbol}")
            if entry_score >= 65:
                return {
                    'decision': 'ENTER',
                    'confidence': int(entry_score),
                    'reasoning': f'All APIs failed. Score {entry_score:.0f} meets threshold.',
                    'risk_notes': 'AI unavailable - using score only',
                    'web_news': 'API unavailable',
                    'delivery_signal': 'UNKNOWN',
                    'oi_signal': 'UNKNOWN',
                    'landmine_found': False,
                    'landmine_type': None,
                    'suggested_position_pct': 0.75,
                }
            return {
                'decision': 'SKIP',
                'confidence': 30,
                'reasoning': f'All APIs failed. Score {entry_score:.0f} below threshold.',
                'risk_notes': 'AI unavailable and score insufficient',
                'web_news': 'API unavailable',
                'delivery_signal': 'UNKNOWN',
                'oi_signal': 'UNKNOWN',
                'landmine_found': False,
                'landmine_type': None,
                'suggested_position_pct': 0.5,
            }

        # ─── Parse response ───
        try:
            decision = self._extract_json(content)

            # Validate decision
            if decision.get('decision') not in ['ENTER', 'SKIP']:
                decision['decision'] = 'SKIP'

            # Ensure required fields
            decision.setdefault('confidence', int(entry_score) if decision.get('decision') == 'ENTER' else 30)
            decision.setdefault('reasoning', '')
            decision.setdefault('risk_notes', '')
            decision.setdefault('web_news', 'No significant news')
            decision.setdefault('delivery_signal', 'UNKNOWN')
            decision.setdefault('oi_signal', 'UNKNOWN')
            decision.setdefault('landmine_found', False)
            decision.setdefault('landmine_type', None)
            decision.setdefault('suggested_position_pct', 1.0)

            # Ensure position_pct is reasonable
            pos_pct = decision.get('suggested_position_pct', 1.0)
            decision['suggested_position_pct'] = max(0.5, min(2.0, pos_pct))

            # Log AI analysis to database
            self._log_ai_analysis(
                analysis_type='ENTRY_REVIEW_V55',
                symbol=symbol,
                context={'entry_price': entry_price, 'entry_score': entry_score,
                         'chatgpt_mode': 'LANDMINE_ONLY'},
                response=decision,
                prompt_snippet=prompt[:200]
            )

            action = "✅ CLEAR" if decision['decision'] == 'ENTER' else "🚫 BLOCKED"
            logger.info(f"   v5.5 Decision: {action} | Confidence: {decision['confidence']}")
            if decision.get('landmine_found'):
                logger.info(f"   ⚠️ LANDMINE: {decision.get('landmine_type', 'unknown')}")
            logger.info(f"   Delivery: {decision.get('delivery_signal')} | OI: {decision.get('oi_signal')}")

            return decision

        except Exception as e:
            logger.error(f"Failed to parse v5.5 response for {symbol}: {e}")
            logger.error(f"Raw content: {content[:300] if content else 'None'}")
            # Safe fallback: let the trade through if score is good
            if entry_score >= 70:
                return {
                    'decision': 'ENTER',
                    'confidence': int(entry_score),
                    'reasoning': f'Parse failed. Score {entry_score:.0f} is strong enough.',
                    'risk_notes': 'AI parse failure - using score only',
                    'web_news': 'Parse error',
                    'delivery_signal': 'UNKNOWN',
                    'oi_signal': 'UNKNOWN',
                    'landmine_found': False,
                    'landmine_type': None,
                    'suggested_position_pct': 0.75,
                }
            return {
                'decision': 'SKIP',
                'confidence': 30,
                'reasoning': f'Parse failed and score {entry_score:.0f} below safety threshold.',
                'risk_notes': 'AI parse failure',
                'web_news': 'Parse error',
                'delivery_signal': 'UNKNOWN',
                'oi_signal': 'UNKNOWN',
                'landmine_found': False,
                'landmine_type': None,
                'suggested_position_pct': 0.5,
            }

    # ═══════════════════════════════════════════════════════════════════════════
    # DECISION #1B: v5.3.2 ENTRY REVIEW WITH WEB SEARCH (Responses API)
    # ═══════════════════════════════════════════════════════════════════════════

    def review_entry_signal_v532(
        self,
        symbol: str,
        chatgpt_package: str,
        entry_price: float,
        entry_score: float = 0,
    ) -> Dict:
        """
        v5.3.2: Trading Manager with web search.
        Uses OpenAI Responses API with web_search tool.
        ChatGPT searches internet for stock news before GO/NOGO.

        Fallback chain:
          1. Responses API + web search (primary)
          2. Chat Completions without web search (if Responses fails)
          3. Score-based decision (if both APIs fail)

        Returns:
            Same dict as review_entry_signal() plus:
            - web_news: str (news findings from web)
            - web_pattern: str (analyst pattern findings)
            - analyst_confirms_entry: bool (external pattern confirmation)
        """
        logger.info(f"ChatGPT v5.3.2 REVIEW (web search): {symbol}")

        system_prompt = TRADER_PERSONA + """You are a professional NSE intraday Trading Manager.
Your job: Make final GO/NOGO decisions on trade entries.

WORKFLOW:
1. FIRST: Search the web for recent news AND technical analysis about the stock
2. THEN: Analyze the score package from the Phase 2 system
3. FINALLY: Give your GO/NOGO decision

You understand Indian stock market patterns, NSE regulations, and intraday trading.
Respond in valid JSON format only."""

        prompt = f"""
STEP 1 -- WEB SEARCH (do ALL of these FIRST):

Search 1: "{symbol} NSE news today"
Search 2: "{symbol} NSE technical analysis today"
Search 3: "{symbol} pivot points support resistance today"
Search 4: "{symbol} delivery percentage NSE"
Search 5: "{symbol} open interest change"

FROM NEWS (Search 1), check for AUTOMATIC SKIP triggers:
- Stock in ASM/GSM surveillance
- Trading halt or suspension
- SEBI investigation or fraud allegations
- Earnings miss or profit warning (today/yesterday)
- Promoter pledge increase
- Bulk/block deal indicating insider selling

FROM TECHNICAL ANALYSIS (Search 2), look for:
- BULLISH patterns mentioned by analysts (double bottom, bullish reversal,
  support holding, accumulation, oversold bounce, hammer) -> CONFIRMATION
- BEARISH patterns mentioned by analysts (head & shoulders, breakdown,
  distribution, resistance rejection, death cross) -> RED FLAG
- Support/resistance levels mentioned -> compare with our entry at {entry_price:.2f}
- Analyst target prices -> compare with our system targets

FROM PIVOT POINTS (Search 3), extract:
- Nearest SUPPORT level below current price {entry_price:.2f} (pivot S1, S2, or analyst support)
- Nearest RESISTANCE level above current price {entry_price:.2f} (pivot R1, R2, or analyst resistance)
- If entry price is within 0.5% ABOVE a support level, suggest that support as entry_price

FROM DELIVERY DATA (Search 4), check:
- Delivery percentage > 50% = "HIGH_DELIVERY" (institutional buying signal)
- Delivery percentage < 30% = "LOW_DELIVERY" (speculative, caution)
- If data not found = "UNKNOWN"

FROM OPEN INTEREST (Search 5), check:
- Price UP + OI UP = "LONG_BUILDUP" (bullish conviction)
- Price DOWN + OI UP = "SHORT_BUILDUP" (bearish conviction)
- Price DOWN + OI DOWN = "LONG_UNWINDING" (longs exiting)
- Price UP + OI DOWN = "SHORT_COVERING" (not genuine buying)
- If data not found or stock not in F&O = "UNKNOWN"

STEP 2 -- ANALYZE SCORE PACKAGE:
{chatgpt_package}

STEP 3 -- DECISION:
Based on ALL web search results AND the score package, decide: GO or NOGO?

DECISION RULES:
1. Any negative NEWS (ASM/GSM/halt/fraud) -> automatic NOGO
2. Score >= 85 + no negative news -> Strong GO
3. Score 75-84 + no negative news -> GO
4. Score 65-74 + bullish analyst patterns -> GO (confirmation boosts confidence)
5. Score 65-74 + no analyst data -> GO (0.75x position, rely on system score)
6. Score 65-74 + bearish analyst patterns -> NOGO (external disagreement)
7. Analyst support level BELOW our stop loss -> caution (wider stop may be needed)
8. HIGH_DELIVERY + LONG_BUILDUP -> boost confidence by 10
9. LOW_DELIVERY or SHORT_BUILDUP -> reduce confidence by 10

ENTRY PRICE LOGIC:
- If current price {entry_price:.2f} is within 0.5% ABOVE a support level, suggest that support level as suggested_entry_price (buy at support for better risk:reward)
- If no meaningful support level is close, set suggested_entry_price to null
- NEVER suggest an entry price more than 0.5% below current LTP

STOP/TARGET LOGIC:
- Set adjusted_stop_price BELOW the nearest support level (support - 0.3%)
- Set adjusted_target_price AT or NEAR the nearest resistance level
- If no S/R data found, set both to null (system will use percentage-based defaults)

Respond in JSON:
{{
    "decision": "ENTER" or "SKIP",
    "confidence": 0-100,
    "reasoning": "Brief explanation (max 100 words)",
    "risk_notes": "Key risks",
    "web_news": "News findings (max 30 words, or 'No significant news')",
    "web_pattern": "Analyst pattern findings (max 30 words, or 'No analyst data found')",
    "analyst_confirms_entry": true or false,
    "suggested_position_pct": 0.5 to 2.0,
    "suggested_stop_pct": -2.0 to -3.0,
    "suggested_target_pct": 2.0 to 4.0,
    "suggested_entry_price": float or null,
    "nearest_support": float or null,
    "nearest_resistance": float or null,
    "adjusted_stop_price": float or null,
    "adjusted_target_price": float or null,
    "delivery_signal": "HIGH_DELIVERY" or "LOW_DELIVERY" or "UNKNOWN",
    "oi_signal": "LONG_BUILDUP" or "SHORT_BUILDUP" or "LONG_UNWINDING" or "SHORT_COVERING" or "UNKNOWN"
}}
"""

        content = None

        # ─── PRIMARY: messages.create with web search ───
        try:
            response = self.client.messages.create(
                model=self.model,
                system=system_prompt,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=1024,
                tools=[{"type": "web_search_20260209", "name": "web_search"}]
            )
            content = next((b.text for b in response.content if b.type == "text"), None)
            logger.info(f"   Responses API + web search succeeded for {symbol}")
        except Exception as e:
            logger.warning(f"Responses API failed for {symbol}: {e}, falling back to Chat Completions")

        # ─── FALLBACK 1: Chat Completions without web search ───
        if content is None:
            try:
                response = self.client.messages.create(
                    model=self.model,
                    system=system_prompt,
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=500
                )
                content = response.content[0].text.strip()
                logger.info(f"   Chat Completions fallback succeeded for {symbol}")
            except Exception as e2:
                logger.error(f"Both APIs failed for {symbol}: {e2}")

        # ─── FALLBACK 2: Score-based decision ───
        if content is None:
            logger.warning(f"   All APIs failed -- using score-based decision for {symbol}")
            if entry_score >= 65:
                return {
                    'decision': 'ENTER',
                    'confidence': int(entry_score),
                    'reasoning': f'All APIs failed. Score {entry_score:.0f} meets threshold.',
                    'risk_notes': 'AI unavailable - using score only',
                    'web_news': 'API unavailable',
                    'web_pattern': 'API unavailable',
                    'analyst_confirms_entry': False,
                    'suggested_position_pct': 0.75,
                    'suggested_stop_pct': -2.0,
                    'suggested_target_pct': 2.5,
                    'suggested_entry_price': None,
                    'nearest_support': None,
                    'nearest_resistance': None,
                    'adjusted_stop_price': None,
                    'adjusted_target_price': None,
                    'delivery_signal': 'UNKNOWN',
                    'oi_signal': 'UNKNOWN',
                }
            return {
                'decision': 'SKIP',
                'confidence': 30,
                'reasoning': f'All APIs failed. Score {entry_score:.0f} below threshold.',
                'risk_notes': 'AI unavailable and score insufficient',
                'web_news': 'API unavailable',
                'web_pattern': 'API unavailable',
                'analyst_confirms_entry': False,
                'suggested_position_pct': 0.5,
                'suggested_stop_pct': -2.0,
                'suggested_target_pct': 2.0,
                'suggested_entry_price': None,
                'nearest_support': None,
                'nearest_resistance': None,
                'adjusted_stop_price': None,
                'adjusted_target_price': None,
                'delivery_signal': 'UNKNOWN',
                'oi_signal': 'UNKNOWN',
            }

        # ─── Parse response ───
        try:
            decision = self._extract_json(content)

            # Validate decision
            if decision.get('decision') not in ['ENTER', 'SKIP', 'WAIT']:
                decision['decision'] = 'SKIP'

            # Ensure required fields
            decision.setdefault('web_news', 'No significant news')
            decision.setdefault('web_pattern', 'No analyst data found')
            decision.setdefault('analyst_confirms_entry', False)
            decision.setdefault('confidence', 50)
            decision.setdefault('reasoning', '')
            decision.setdefault('risk_notes', '')

            # Ensure position_pct is reasonable
            pos_pct = decision.get('suggested_position_pct', 1.0)
            decision['suggested_position_pct'] = max(0.5, min(2.0, pos_pct))

            # v5.4: Defaults for new S/R + institutional fields
            decision.setdefault('suggested_entry_price', None)
            decision.setdefault('nearest_support', None)
            decision.setdefault('nearest_resistance', None)
            decision.setdefault('adjusted_stop_price', None)
            decision.setdefault('adjusted_target_price', None)
            decision.setdefault('delivery_signal', 'UNKNOWN')
            decision.setdefault('oi_signal', 'UNKNOWN')

            # v5.4: Validate suggested_entry_price (must be within 0.5% of entry_price)
            sep = decision.get('suggested_entry_price')
            if sep is not None:
                try:
                    sep = float(sep)
                    max_slip = entry_price * 0.005  # 0.5%
                    if sep > entry_price or sep < (entry_price - max_slip):
                        logger.warning(f"   Suggested entry {sep:.2f} out of range, ignoring")
                        decision['suggested_entry_price'] = None
                    else:
                        decision['suggested_entry_price'] = sep
                except (TypeError, ValueError):
                    decision['suggested_entry_price'] = None

            # v5.4: Validate S/R prices are positive floats
            for field in ['nearest_support', 'nearest_resistance', 'adjusted_stop_price', 'adjusted_target_price']:
                val = decision.get(field)
                if val is not None:
                    try:
                        val = float(val)
                        if val <= 0:
                            decision[field] = None
                        else:
                            decision[field] = val
                    except (TypeError, ValueError):
                        decision[field] = None

            logger.info(f"   Decision: {decision['decision']} ({decision['confidence']}%)")
            logger.info(f"   Web news: {decision['web_news']}")
            logger.info(f"   Analyst pattern: {decision['web_pattern']}")
            logger.info(f"   Analyst confirms: {decision['analyst_confirms_entry']}")
            logger.info(f"   Delivery: {decision.get('delivery_signal', 'UNKNOWN')} | OI: {decision.get('oi_signal', 'UNKNOWN')}")
            if decision.get('suggested_entry_price'):
                logger.info(f"   Suggested LIMIT entry: Rs{decision['suggested_entry_price']:.2f}")
            if decision.get('nearest_support'):
                logger.info(f"   Support: Rs{decision['nearest_support']:.2f}")
            if decision.get('nearest_resistance'):
                logger.info(f"   Resistance: Rs{decision['nearest_resistance']:.2f}")
            if decision.get('adjusted_stop_price'):
                logger.info(f"   Adjusted stop: Rs{decision['adjusted_stop_price']:.2f}")
            if decision.get('adjusted_target_price'):
                logger.info(f"   Adjusted target: Rs{decision['adjusted_target_price']:.2f}")

            # Track in history
            self.conversation_history.append({
                'timestamp': datetime.now().isoformat(),
                'type': 'entry_review_v532_web',
                'symbol': symbol,
                'decision': decision['decision'],
                'confidence': decision.get('confidence', 0),
                'entry_score': entry_score,
                'web_search': True,
            })

            # v3.4.0: Log to database
            self._log_ai_analysis(
                analysis_type='ENTRY_REVIEW_V532',
                symbol=symbol,
                context={
                    'entry_price': entry_price,
                    'entry_score': entry_score,
                    'web_search': True,
                },
                response=decision
            )

            return decision

        except Exception as e:
            logger.error(f"JSON parsing failed for {symbol}: {e}")
            # Fallback to score-based
            if entry_score >= 65:
                return {
                    'decision': 'ENTER',
                    'confidence': int(entry_score),
                    'reasoning': f'JSON parse failed. Score {entry_score:.0f} meets threshold.',
                    'risk_notes': 'AI response unparseable',
                    'web_news': 'Parse error',
                    'web_pattern': 'Parse error',
                    'analyst_confirms_entry': False,
                    'suggested_position_pct': 0.75,
                    'suggested_stop_pct': -2.0,
                    'suggested_target_pct': 2.5,
                    'suggested_entry_price': None,
                    'nearest_support': None,
                    'nearest_resistance': None,
                    'adjusted_stop_price': None,
                    'adjusted_target_price': None,
                    'delivery_signal': 'UNKNOWN',
                    'oi_signal': 'UNKNOWN',
                }
            return {
                'decision': 'SKIP',
                'confidence': 30,
                'reasoning': f'JSON parse failed. Score {entry_score:.0f} below threshold.',
                'risk_notes': 'AI response unparseable',
                'web_news': 'Parse error',
                'web_pattern': 'Parse error',
                'analyst_confirms_entry': False,
                'suggested_position_pct': 0.5,
                'suggested_stop_pct': -2.0,
                'suggested_target_pct': 2.0,
                'suggested_entry_price': None,
                'nearest_support': None,
                'nearest_resistance': None,
                'adjusted_stop_price': None,
                'adjusted_target_price': None,
                'delivery_signal': 'UNKNOWN',
                'oi_signal': 'UNKNOWN',
            }

    # ═══════════════════════════════════════════════════════════════════════════
    # DECISION #2: END-OF-DAY SHUTDOWN
    # ═══════════════════════════════════════════════════════════════════════════
    
    def should_continue_trading(self, context: Dict) -> Dict:
        """
        NEW v2.0: Decide if system should continue or shutdown early.
        
        Args:
            context: {
                'current_time': str,
                'stocks_monitored': int,
                'scans_today': int,
                'market_regime': str,
                'nifty_change': float,
                'minutes_until_close': int,
                'trades_today': int,
                'last_scan_result': int
            }
        
        Returns:
            {
                'recommendation': 'CONTINUE' or 'SHUTDOWN',
                'reasoning': str,
                'confidence': int (0-100)
            }
        """
        try:
            prompt = f"""You are an autonomous trading system advisor. Decide if the system should continue monitoring or shutdown early.

CURRENT STATE:
==============
Time: {context.get('current_time', 'UNKNOWN')}
Minutes Until Market Close: {context.get('minutes_until_close', 0)}

SYSTEM STATUS:
==============
- Stocks Monitored: {context.get('stocks_monitored', 0)}
- Scans Completed Today: {context.get('scans_today', 0)}
- Last Scan Result: {context.get('last_scan_result', 0)} stocks found
- Trades Executed Today: {context.get('trades_today', 0)}

MARKET CONDITIONS:
==================
- Market Regime: {context.get('market_regime', 'UNKNOWN')}
- NIFTY Change: {context.get('nifty_change', 0):+.2f}%

DECISION FACTORS:
=================
1. If 0 stocks monitored + bearish market + <15 min to close → SHUTDOWN
2. If 0 stocks monitored + bullish market + >30 min to close → CONTINUE
3. If open positions exist → CONTINUE (must monitor exits)
4. If 0 stocks + last 3 scans found 0 → SHUTDOWN
5. If >1 trade today + 0 stocks + <30 min → SHUTDOWN (goals met)
6. If 0 trades + >20 min → CONTINUE (still time)

Respond in JSON format:
{{
    "recommendation": "CONTINUE" or "SHUTDOWN",
    "reasoning": "Brief explanation (max 80 words)",
    "confidence": 0-100
}}
"""
            
            response = self.client.messages.create(
                model=self.model,
                system="You are an autonomous trading system advisor. Respond only in valid JSON.",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=300
            )
            
            content = response.content[0].text.strip()
            decision = self._extract_json(content)
            
            logger.info(f"🤖 GPT SHUTDOWN DECISION:")
            logger.info(f"   Recommendation: {decision['recommendation']}")
            logger.info(f"   Confidence: {decision['confidence']}%")
            logger.info(f"   Reasoning: {decision['reasoning']}")
            
            return decision
            
        except Exception as e:
            logger.error(f"❌ GPT shutdown decision failed: {e}")
            return {
                'recommendation': 'CONTINUE',
                'reasoning': f'GPT failed ({str(e)}). Defaulting to continue.',
                'confidence': 50
            }
    
    # ═══════════════════════════════════════════════════════════════════════════
    # DECISION #3: ADAPTIVE SCAN DECISION
    # ═══════════════════════════════════════════════════════════════════════════
    
    def should_run_adaptive_scan(self, context: Dict) -> Dict:
        """
        NEW v2.0: Decide if adaptive scan is worth running.
        
        Args:
            context: {
                'current_time': str,
                'stocks_monitored': int,
                'last_scan_time': str,
                'last_scan_result': int,
                'recent_scan_results': List[int],
                'market_regime': str,
                'nifty_change': float,
                'api_calls_remaining': int
            }
        
        Returns:
            {
                'should_scan': bool,
                'reasoning': str,
                'confidence': int
            }
        """
        try:
            recent_results = context.get('recent_scan_results', [])
            avg_recent = sum(recent_results) / len(recent_results) if recent_results else 0
            
            prompt = f"""You are an autonomous trading system advisor. Decide if running an adaptive scan is worthwhile.

CURRENT STATE:
==============
Time: {context.get('current_time', 'UNKNOWN')}
Stocks Currently Monitored: {context.get('stocks_monitored', 0)}

SCAN HISTORY:
=============
- Last Scan: {context.get('last_scan_time', 'UNKNOWN')}
- Last Scan Result: {context.get('last_scan_result', 0)} stocks found
- Recent Scan Results: {recent_results} stocks
- Average Recent: {avg_recent:.1f} stocks

MARKET CONDITIONS:
==================
- Market Regime: {context.get('market_regime', 'UNKNOWN')}
- NIFTY Change: {context.get('nifty_change', 0):+.2f}%

DECISION FACTORS:
=================
1. If last 3 scans found 0 stocks + bearish → SKIP (waste of API)
2. If bearish market + time >14:30 → SKIP (low probability)
3. If volatile market + stocks < 3 → SCAN (opportunities)
4. If API calls low (<100) + average < 1 → SKIP (conserve)
5. If bullish market + stocks < 3 → SCAN (good probability)
6. If time <13:00 → SCAN (plenty of time)

Respond in JSON format:
{{
    "should_scan": true or false,
    "reasoning": "Brief explanation (max 60 words)",
    "confidence": 0-100
}}
"""
            
            response = self.client.messages.create(
                model=self.model,
                system="You are an autonomous trading system advisor. Respond only in valid JSON.",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=250
            )
            
            content = response.content[0].text.strip()
            decision = self._extract_json(content)
            
            logger.info(f"🤖 GPT ADAPTIVE SCAN DECISION:")
            logger.info(f"   Should Scan: {decision['should_scan']}")
            logger.info(f"   Confidence: {decision['confidence']}%")
            logger.info(f"   Reasoning: {decision['reasoning']}")
            
            return decision
            
        except Exception as e:
            logger.error(f"❌ GPT adaptive scan decision failed: {e}")
            return {
                'should_scan': context.get('stocks_monitored', 0) < 3,
                'reasoning': f'GPT failed ({str(e)}). Using simple rule.',
                'confidence': 50
            }
    
    # ═══════════════════════════════════════════════════════════════════════════
    # NOTIFICATION METHODS (Track Positions)
    # ═══════════════════════════════════════════════════════════════════════════
    
    def notify_position_opened(self, position: Dict):
        """
        NEW v2.0: Inform GPT that a position was opened.
        Maintains conversation history for context.
        """
        try:
            self.conversation_history.append({
                'timestamp': datetime.now().isoformat(),
                'event': 'POSITION_OPENED',
                'data': position
            })
            
            logger.info(f"🤖 GPT notified: Position opened for {position.get('symbol')}")
            
        except Exception as e:
            logger.error(f"❌ Failed to notify GPT of position: {e}")
    
    def notify_position_closed(self, position: Dict):
        """
        NEW v2.0: Inform GPT that a position was closed.
        """
        try:
            self.conversation_history.append({
                'timestamp': datetime.now().isoformat(),
                'event': 'POSITION_CLOSED',
                'data': position
            })
            
            logger.info(f"🤖 GPT notified: Position closed for {position.get('symbol')}")
            
        except Exception as e:
            logger.error(f"❌ Failed to notify GPT of exit: {e}")
    
    # ═══════════════════════════════════════════════════════════════════════════
    # EXISTING METHODS (Preserved from v1.0)
    # ═══════════════════════════════════════════════════════════════════════════
    
    def calculate_position_size(
        self,
        symbol: str,
        entry_price: float,
        base_capital: float,
        atr: float,
        market_regime: str,
        nifty_volatility: float,
        portfolio_exposure: float = 0,
        correlation_with_existing: float = 0
    ) -> Dict:
        """
        Calculate position size using ChatGPT intelligence.
        
        Returns:
            {
                'suggested_capital': float,
                'risk_adjustment': float,
                'reasoning': str
            }
        """
        logger.info(f"🤖 CHATGPT POSITION SIZING: {symbol}")
        
        try:
            prompt = f"""You are a professional risk manager. Calculate the optimal position size for this trade.

TRADE DETAILS:
==============
Symbol: {symbol}
Entry Price: ₹{entry_price:.2f}
Base Capital: ₹{base_capital:,.0f}
ATR (14): ₹{atr:.2f}

MARKET CONDITIONS:
==================
Market Regime: {market_regime}
NIFTY Volatility: {nifty_volatility:.2f}%
Current Portfolio Exposure: {portfolio_exposure:.1f}%
Correlation with Existing Positions: {correlation_with_existing:.2f}

GUIDELINES:
===========
- Bull market → 100-120% of base capital
- Mixed market → 75-100% of base capital
- Bear market → 50-75% of base capital
- High volatility (>2%) → Reduce by 20-30%
- High portfolio exposure (>60%) → Reduce size
- High correlation (>0.7) → Reduce to avoid concentration

Respond in JSON format:
{{
    "suggested_capital": amount in rupees,
    "risk_adjustment": 0.5 to 1.2,
    "reasoning": "Brief explanation"
}}
"""
            
            response = self.client.messages.create(
                model=self.model,
                system="You are an expert risk manager. Respond only in valid JSON.",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=300
            )
            
            content = response.content[0].text.strip()
            result = self._extract_json(content)
            
            logger.info(f"   Suggested Capital: ₹{result.get('suggested_capital', base_capital):,.0f}")
            logger.info(f"   Risk Adjustment: {result.get('risk_adjustment', 1.0):.2f}x")
            
            return result
            
        except Exception as e:
            logger.error(f"❌ Position sizing failed: {e}")
            return {
                'suggested_capital': base_capital,
                'risk_adjustment': 1.0,
                'reasoning': f'ChatGPT failed: {str(e)}'
            }
    
    def calculate_exit_levels(
        self,
        symbol: str,
        entry_price: float,
        atr: float,
        support_levels: List[float],
        resistance_levels: List[float],
        fibonacci_levels: Dict[str, float] = None
    ) -> Dict:
        """
        Calculate optimal stop-loss and target levels.
        
        Returns:
            {
                'stop_loss': float,
                'target_1': float,
                'target_2': float,
                'trailing_stop_trigger': float,
                'reasoning': str
            }
        """
        logger.info(f"🤖 CHATGPT EXIT LEVELS: {symbol}")
        
        try:
            fib_text = ""
            if fibonacci_levels:
                fib_text = f"""
Fibonacci Levels:
- 23.6%: ₹{fibonacci_levels.get('23.6', 0):.2f}
- 38.2%: ₹{fibonacci_levels.get('38.2', 0):.2f}
- 50.0%: ₹{fibonacci_levels.get('50.0', 0):.2f}
- 61.8%: ₹{fibonacci_levels.get('61.8', 0):.2f}
"""
            
            prompt = f"""You are a professional trader. Calculate optimal exit levels for this trade.

TRADE DETAILS:
==============
Symbol: {symbol}
Entry Price: ₹{entry_price:.2f}
ATR (14): ₹{atr:.2f}

TECHNICAL LEVELS:
=================
Support Levels: {[f'₹{s:.2f}' for s in support_levels]}
Resistance Levels: {[f'₹{r:.2f}' for r in resistance_levels]}
{fib_text}

GUIDELINES:
===========
- Stop Loss: 1.5-2.0 × ATR below entry
- Place stop just below nearest support
- Target 1: 2.0-2.5 × ATR (quick profit)
- Target 2: 3.0-4.0 × ATR (runner)
- Align targets with resistance/Fibonacci
- Trailing stop: Activate at Target 1

Respond in JSON format:
{{
    "stop_loss": price in rupees,
    "target_1": price in rupees,
    "target_2": price in rupees,
    "trailing_stop_trigger": price in rupees,
    "reasoning": "Brief explanation"
}}
"""
            
            response = self.client.messages.create(
                model=self.model,
                system="You are an expert trader. Respond only in valid JSON.",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=400
            )
            
            content = response.content[0].text.strip()
            result = self._extract_json(content)
            
            logger.info(f"   Stop Loss: ₹{result.get('stop_loss', 0):.2f}")
            logger.info(f"   Target 1: ₹{result.get('target_1', 0):.2f}")
            logger.info(f"   Target 2: ₹{result.get('target_2', 0):.2f}")
            
            return result
            
        except Exception as e:
            logger.error(f"❌ Exit levels failed: {e}")
            # Fallback: Simple ATR-based
            return {
                'stop_loss': entry_price - (2.0 * atr),
                'target_1': entry_price + (2.5 * atr),
                'target_2': entry_price + (4.0 * atr),
                'trailing_stop_trigger': entry_price + (2.0 * atr),
                'reasoning': f'ChatGPT failed: {str(e)}'
            }

    # ===================================================================
    # v6.0: OPTIONS SPREAD STRATEGY — Bull Call Spread Advisory
    # ===================================================================

    def review_marker_second_dip(self, context: dict) -> Optional[Dict]:
        """Expert review of a 2nd-dip setup on a 1-share marker stock.

        Returns the parsed JSON verdict (ENTER / WAIT / SKIP plus a full plan), or None if the
        API is unavailable or the answer cannot be parsed. The caller validates the plan and
        falls back to its rule-based suggestion on None.
        """
        import json as _json

        system_prompt = TRADER_PERSONA + """
YOUR TASK: A stock we hold as a 1-share equity marker has finished a second dip and is now bouncing. The
system's Kalman filter says the fall has slowed and turned up. Decide whether a human should buy options on
this bounce, and design the best structure. The human enters manually; you only advise.

Choose between: LONG_CALL, BULL_CALL_SPREAD, or NONE (verdict WAIT or SKIP). Prefer defined risk. Prefer a
spread when days-to-expiry is short or premium is rich; prefer a long call when there is room to run and
implied volatility is reasonable. The setup is only as good as its worst realistic scenario.

Return ONE JSON object and nothing else:
{
  "verdict": "ENTER" | "WAIT" | "SKIP",
  "confidence": <0-100>,
  "strategy": "LONG_CALL" | "BULL_CALL_SPREAD" | "NONE",
  "legs": [{"action": "BUY"|"SELL", "symbol": "<exact CE symbol from the table>", "strike": <float>, "premium": <float from the table>}],
  "scenarios": [
    {"name": "strong follow-through", "probability_pct": <int>, "underlying": "<level or move>", "option_result": "<approx % or Rs per lot>"},
    {"name": "slow grind / chop (theta)", "probability_pct": <int>, "underlying": "...", "option_result": "..."},
    {"name": "bounce fails, low breaks", "probability_pct": <int>, "underlying": "...", "option_result": "..."},
    {"name": "gap / event shock", "probability_pct": <int>, "underlying": "...", "option_result": "..."}
  ],
  "expected_value": "<one line: probability-weighted outcome per lot and reward:risk>",
  "entry_zone": {"underlying_min": <float>, "underlying_max": <float>},
  "t1": <float underlying>, "t2": <float underlying>,
  "stop_underlying": <float underlying invalidation>,
  "premium_stop": <float>,
  "time_stop_sessions": <int>,
  "lots": 1,
  "pre_mortem": "<the most likely way this loses>",
  "manage_plan": "<when to book, trail, cut; what to do on a gap against>",
  "reasoning": "<max 110 words, desk-head style>"
}
Scenario probabilities must sum to 100. If verdict is WAIT or SKIP, still fill scenarios, pre_mortem and
reasoning; set strategy NONE and legs [].
"""
        user_prompt = "SETUP DATA (JSON):\n" + _json.dumps(context, default=str, indent=1)

        client = self.client.with_options(timeout=120.0)
        text = None
        try:
            resp = client.messages.create(
                model=self.model, system=system_prompt, max_tokens=2500,
                messages=[{"role": "user", "content": user_prompt}],
                tools=[{"type": "web_search_20260209", "name": "web_search"}],
            )
            text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
        except Exception as e1:
            logger.warning(f"   Marker AI review with web search failed: {e1}")
            try:
                resp = client.messages.create(
                    model=self.model, system=system_prompt, max_tokens=2500,
                    messages=[{"role": "user", "content": user_prompt}],
                )
                text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
            except Exception as e2:
                logger.error(f"   Marker AI review failed: {e2}")
                return None

        if not text:
            return None
        try:
            return _json.loads(text[text.index("{"): text.rindex("}") + 1])
        except (ValueError, _json.JSONDecodeError):
            logger.error(f"   Marker AI review: could not parse JSON: {text[:200]!r}")
            return None

    def review_options_strategy(
        self,
        symbol: str,
        spot_price: float,
        chain_data: dict,
        equity_entry_price: float,
        phase2_score: float = 0,
    ) -> Optional[Dict]:
        """
        v6.0: Ask ChatGPT to recommend a Bull Call Spread for a stock
        that just received an equity BUY entry.

        Uses Responses API with web_search (primary) or Chat Completions (fallback).

        Args:
            symbol: Stock symbol (e.g. 'RELIANCE')
            spot_price: Current spot price
            chain_data: Dict with keys: expiry, lot_size, strikes[], pcr, max_pain,
                        total_ce_oi, total_pe_oi, oi_buildup
            equity_entry_price: Price at which equity BUY was placed
            phase2_score: Phase 2 entry score (0-100)

        Returns:
            Dict with strategy recommendation, or None if failed/low confidence
        """
        import json as _json

        logger.info(f"")
        logger.info(f"{'='*60}")
        logger.info(f"📊 OPTIONS STRATEGY REVIEW: {symbol}")
        logger.info(f"{'='*60}")
        logger.info(f"   Spot: ₹{spot_price:.2f} | Equity Entry: ₹{equity_entry_price:.2f}")
        logger.info(f"   Expiry: {chain_data.get('expiry', 'N/A')} | Lot: {chain_data.get('lot_size', 0)}")
        logger.info(f"   PCR: {chain_data.get('pcr', 0)} | Max Pain: ₹{chain_data.get('max_pain', 0):.2f}")
        logger.info(f"   Strikes available: {len(chain_data.get('strikes', []))}")

        system_prompt = TRADER_PERSONA + """You are a professional NSE Stock Options Strategist.
You specialize in BULL CALL SPREAD strategies for Indian stock options.

A Bull Call Spread is:
- BUY 1 lot of a lower-strike CE (near ATM, slightly ITM or ATM)
- SELL 1 lot of a higher-strike CE (OTM)
- Same expiry, same underlying, defined risk

CRITICAL RULES:
- ONLY recommend BULL_CALL_SPREAD (you are bullish, matching the equity BUY)
- Both legs must use the SAME expiry date
- Use strikes with adequate OI (>1000) and volume (>50) from the data provided
- Lot size is fixed per stock (e.g. RELIANCE=250, TCS=175). Order quantity = lot_size shares. Recommend 1 lot.
- Max loss = net debit paid (buy premium - sell premium) × lot_size
- Max profit = (sell_strike - buy_strike - net_debit_per_share) × lot_size
- Breakeven = buy_strike + net_debit_per_share
- This is PAPER TRADING (advisory only) — recommend what you'd actually trade

Respond in valid JSON format ONLY. No markdown, no explanation outside JSON."""

        # Build strikes table for prompt
        strikes_text = "Strike | CE_LTP | CE_OI | CE_Vol | PE_LTP | PE_OI | PE_Vol | CE_Symbol\n"
        strikes_text += "-" * 90 + "\n"
        for s in chain_data.get('strikes', []):
            strikes_text += (
                f"{s.get('strike', 0):>8.0f} | "
                f"₹{s.get('ce_ltp', 0):>7.2f} | "
                f"{s.get('ce_oi', 0):>7,} | "
                f"{s.get('ce_volume', 0):>6,} | "
                f"₹{s.get('pe_ltp', 0):>7.2f} | "
                f"{s.get('pe_oi', 0):>7,} | "
                f"{s.get('pe_volume', 0):>6,} | "
                f"{s.get('ce_symbol', '')}\n"
            )

        oi_buildup = chain_data.get('oi_buildup', {})

        prompt = f"""
STEP 1 — WEB SEARCH:
Search 1: "{symbol} options open interest analysis today"
Search 2: "{symbol} FII DII activity options"

STEP 2 — ANALYZE THIS OPTIONS DATA:
Symbol: {symbol}
Spot Price: ₹{spot_price:.2f}
Equity Entry Price: ₹{equity_entry_price:.2f} (we already BOUGHT the stock)
Expiry: {chain_data.get('expiry', 'N/A')}
Lot Size: {chain_data.get('lot_size', 0)}
Phase 2 Score: {phase2_score}/100

OI ANALYSIS:
- PCR (Put-Call Ratio): {chain_data.get('pcr', 0):.2f}
- Max Pain: ₹{chain_data.get('max_pain', 0):.2f}
- Total CE OI: {chain_data.get('total_ce_oi', 0):,}
- Total PE OI: {chain_data.get('total_pe_oi', 0):,}
- Highest CE OI at: ₹{oi_buildup.get('highest_ce_oi_strike', 0):.0f} (resistance ceiling)
- Highest PE OI at: ₹{oi_buildup.get('highest_pe_oi_strike', 0):.0f} (support floor)
- Top 3 CE OI: {oi_buildup.get('top_3_ce_oi', [])}
- Top 3 PE OI: {oi_buildup.get('top_3_pe_oi', [])}

AVAILABLE STRIKES:
{strikes_text}

STEP 3 — RECOMMEND A BULL CALL SPREAD:
Pick the best buy_strike (near ATM) and sell_strike (OTM, ideally at or near resistance).
Use strikes that have OI > 1000 and volume > 50.

Respond in this exact JSON format:
{{
    "strategy_type": "BULL_CALL_SPREAD",
    "buy_strike": <float>,
    "buy_premium": <float from CE_LTP column>,
    "buy_symbol": "<exact CE_Symbol from table>",
    "sell_strike": <float>,
    "sell_premium": <float from CE_LTP column>,
    "sell_symbol": "<exact CE_Symbol from table>",
    "net_debit_per_share": <float: buy_premium - sell_premium>,
    "max_profit_per_lot": <float: (sell_strike - buy_strike - net_debit_per_share) × lot_size>,
    "max_loss_per_lot": <float: net_debit_per_share × lot_size>,
    "breakeven": <float: buy_strike + net_debit_per_share>,
    "confidence": <0-100>,
    "reasoning": "<max 150 words: why these strikes, OI analysis, web findings>",
    "risk_reward_ratio": <float: max_profit / max_loss>,
    "web_news": "<key findings from web search, max 50 words>"
}}
"""

        content = None

        # ─── PRIMARY: messages.create with web search ───
        try:
            response = self.client.messages.create(
                model=self.model,
                system=system_prompt,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=1024,
                tools=[{"type": "web_search_20260209", "name": "web_search"}]
            )
            content = next((b.text for b in response.content if b.type == "text"), None)
            logger.info(f"   Responses API + web search succeeded for {symbol} options")
        except Exception as e1:
            logger.warning(f"   Responses API failed for {symbol} options: {e1}")

            # ─── FALLBACK: Chat Completions without web search ───
            try:
                response = self.client.messages.create(
                    model=self.model,
                    system=system_prompt,
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=800
                )
                content = response.content[0].text.strip()
                logger.info(f"   Chat Completions fallback succeeded for {symbol} options")
            except Exception as e2:
                logger.error(f"   Both APIs failed for {symbol} options: {e2}")
                return None

        if not content:
            logger.warning(f"   Empty response for {symbol} options")
            return None

        # ─── Parse JSON ───
        try:
            # Strip markdown code fences if present
            clean = content
            if '```' in clean:
                clean = clean.split('```json')[-1] if '```json' in clean else clean.split('```')[-2]
                clean = clean.replace('```', '').strip()

            # Find JSON object
            start_idx = clean.find('{')
            end_idx = clean.rfind('}')
            if start_idx == -1 or end_idx == -1:
                logger.error(f"   No JSON found in options response for {symbol}")
                return None

            json_str = clean[start_idx:end_idx + 1]
            result = _json.loads(json_str)

            # Validate required fields
            required = ['strategy_type', 'buy_strike', 'sell_strike', 'buy_premium',
                        'sell_premium', 'confidence']
            for field in required:
                if field not in result:
                    logger.error(f"   Missing required field '{field}' in options response")
                    return None

            # Validate strategy type
            if result.get('strategy_type') != 'BULL_CALL_SPREAD':
                logger.warning(f"   ChatGPT suggested {result.get('strategy_type')} "
                              f"instead of BULL_CALL_SPREAD, skipping")
                return None

            # Validate strikes make sense
            buy_strike = float(result['buy_strike'])
            sell_strike = float(result['sell_strike'])
            if sell_strike <= buy_strike:
                logger.error(f"   Invalid spread: sell_strike {sell_strike} <= buy_strike {buy_strike}")
                return None

            # Set defaults for optional fields
            lot_size = chain_data.get('lot_size', 1)
            buy_prem = float(result['buy_premium'])
            sell_prem = float(result['sell_premium'])
            net_debit = buy_prem - sell_prem

            result.setdefault('net_debit_per_share', round(net_debit, 2))
            result.setdefault('max_profit_per_lot', round((sell_strike - buy_strike - net_debit) * lot_size, 2))
            result.setdefault('max_loss_per_lot', round(net_debit * lot_size, 2))
            result.setdefault('breakeven', round(buy_strike + net_debit, 2))
            result.setdefault('risk_reward_ratio',
                              round((sell_strike - buy_strike - net_debit) / net_debit, 2) if net_debit > 0 else 0)
            result.setdefault('reasoning', '')
            result.setdefault('web_news', 'No data')

            logger.info(f"   ✅ Bull Call Spread: BUY {buy_strike} CE @ ₹{buy_prem:.2f} | "
                       f"SELL {sell_strike} CE @ ₹{sell_prem:.2f}")
            logger.info(f"   Net Debit: ₹{net_debit:.2f}/share | "
                       f"Max Profit: ₹{result['max_profit_per_lot']:,.0f} | "
                       f"Max Loss: ₹{result['max_loss_per_lot']:,.0f}")
            logger.info(f"   Confidence: {result.get('confidence', 0)}/100 | "
                       f"R:R = 1:{result.get('risk_reward_ratio', 0):.1f}")

            return result

        except (_json.JSONDecodeError, ValueError, TypeError) as e:
            logger.error(f"   Failed to parse options response for {symbol}: {e}")
            logger.debug(f"   Raw content: {content[:500]}")
            return None

    # ═══════════════════════════════════════════════════════════════════════
    # v8.0.0: PHASE 8 MOMENTUM — CE Shadow Approval Gate
    # ═══════════════════════════════════════════════════════════════════════

    def review_momentum_options(
        self,
        symbol: str,
        spot_price: float,
        entry_price: float,
        weekly_return_pct: float,
        weekly_technicals: Dict,
        options_context: Dict,
    ) -> Optional[Dict]:
        """
        v8.0.0: ChatGPT approval gate for Phase 8 momentum CE shadow.

        The cash position is ALREADY executed. This only decides whether to
        paper-shadow with a CE option. Score > 70 = approve shadow.

        Args:
            symbol: Stock symbol
            spot_price: Current spot price
            entry_price: CNC entry price
            weekly_return_pct: 1-week return that triggered the pick
            weekly_technicals: Dict with RSI, ADX, DI+/-, VWAP, volume, etc.
            options_context: Dict with IV, chain, theta estimate, etc.

        Returns:
            Dict with confidence, decision, strike, reasoning — or None on failure.
        """
        import json as _json

        logger.info(f"")
        logger.info(f"{'='*60}")
        logger.info(f"PH8 MOMENTUM OPTIONS GATE: {symbol}")
        logger.info(f"{'='*60}")

        system_prompt = """You are the options shadow advisor for Phase 8 momentum trades.
You evaluate whether a weekly momentum cash position should be shadowed with a CE option.

CONTEXT: The cash CNC BUY is already executed. You only decide on the CE shadow.
Your evaluation considers: trend strength, IV level (high IV = expensive options),
theta cost vs expected move, momentum sustainability.

RESPOND IN VALID JSON ONLY. No markdown, no text outside JSON."""

        # Build prompt
        wt = weekly_technicals
        oc = options_context

        prompt = f"""CASH POSITION (already executed):
  Stock: {symbol} | Entry: Rs{entry_price:.2f} | CNC delivery
  Momentum rank: #1 | 1-week return: {weekly_return_pct:+.2f}%

WEEKLY TECHNICAL DATA:
  RSI(14w): {wt.get('rsi', 'N/A')} | ADX(14w): {wt.get('adx', 'N/A')}
  +DI: {wt.get('plus_di', 'N/A')} | -DI: {wt.get('minus_di', 'N/A')}
  VWAP position: {wt.get('vwap_position', 'N/A')} by {wt.get('vwap_distance_pct', 'N/A')}%
  EMA21w trend: {wt.get('ema_trend', 'N/A')}
  Volume: {wt.get('current_volume', 'N/A')} vs {wt.get('avg_volume', 'N/A')} ({wt.get('volume_ratio', 'N/A')}x)
  ATR(14w): Rs{wt.get('atr', 0):.2f} ({wt.get('atr_pct', 0):.1f}% of price)
  Sector health: {wt.get('sector_score', 'N/A')}/100

OPTIONS CONTEXT:
  IV percentile: {oc.get('iv_percentile', 'N/A')}% (30-day range: {oc.get('iv_low', 'N/A')}-{oc.get('iv_high', 'N/A')})
  ATM strike: {oc.get('atm_strike', 'N/A')} | Premium: Rs{oc.get('atm_premium', 0):.2f}
  ATM delta: {oc.get('delta', 'N/A')} | Theta/day: Rs{oc.get('theta', 0):.2f}
  2-week expiry: {oc.get('expiry_date', 'N/A')} ({oc.get('dte', 'N/A')} days)
  Option chain summary: {oc.get('chain_summary', 'N/A')}

DECISION REQUIRED:
  1. Confidence score 0-100: Should we shadow this cash position with a CE option?
  2. If score > 70: Recommend strike (ATM or specific OTM), with reasoning.

RESPOND IN JSON:
{{
  "confidence": <0-100>,
  "decision": "APPROVE" or "REJECT",
  "reasoning": "<2-3 sentences>",
  "recommended_strike": <strike price or null>,
  "recommended_expiry": "<date or null>",
  "expected_delta": <float or null>,
  "risk_flag": "<any concerns>"
}}"""

        try:
            response = self.client.messages.create(
                model=self.model,
                system=system_prompt,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=500
            )

            content = response.content[0].text.strip()
            result = self._extract_json(content)

            if not result:
                logger.error(f"   PH8 Options gate: Failed to parse ChatGPT response")
                return None

            confidence = result.get('confidence', 0)
            decision = result.get('decision', 'REJECT')

            logger.info(f"   PH8 Options gate: confidence={confidence}, decision={decision}")
            logger.info(f"   Reasoning: {result.get('reasoning', 'N/A')}")
            logger.info(f"   Risk flag: {result.get('risk_flag', 'N/A')}")

            if result.get('recommended_strike'):
                logger.info(f"   Recommended strike: {result['recommended_strike']}")

            return result

        except Exception as e:
            logger.error(f"   PH8 Options gate error: {type(e).__name__}: {e}")
            return None

    def optimize_order_parameters(
        self,
        symbol: str,
        entry_price: float,
        quantity: int = 0,
        market_depth: Dict = None,
        execution_urgency: str = "NORMAL",
        atr: float = 0.0,
        volatility_regime: str = "NORMAL",
        time_of_day: str = "MIDDAY",
        current_positions: int = 0
    ) -> Dict:
        """
        Optimize order placement parameters.
        
        v5.1.0 FIX: Accepts both old signature (quantity, market_depth) and
        new signature (atr, volatility_regime, time_of_day, current_positions).
        Returns keys that Phase 3 expects: profit_target_pct, stop_loss_pct, risk_reward_ratio.
        
        Returns:
            {
                'order_type': 'MARKET' | 'LIMIT',
                'profit_target_pct': float,
                'stop_loss_pct': float,
                'risk_reward_ratio': float,
                'reasoning': str
            }
        """
        logger.info(f"🤖 CHATGPT ORDER OPTIMIZATION: {symbol}")
        
        try:
            prompt = f"""You are a professional execution trader. Optimize order parameters.

ORDER DETAILS:
==============
Symbol: {symbol}
Entry Price: ₹{entry_price:.2f}
ATR: ₹{atr:.2f} ({atr/entry_price*100:.1f}% of price)
Volatility Regime: {volatility_regime}
Time of Day: {time_of_day}
Current Open Positions: {current_positions}

GUIDELINES:
===========
- NORMAL volatility: Stop 1.5-2.0%, Target 2.5-3.5%
- HIGH volatility: Stop 2.0-3.0%, Target 3.0-5.0%
- LOW volatility: Stop 1.0-1.5%, Target 2.0-3.0%
- MORNING: Wider stops (volatility higher), aggressive targets
- MIDDAY: Standard stops and targets
- AFTERNOON: Tighter stops (less time for recovery)
- More positions open = tighter risk per trade
- Minimum risk:reward ratio of 1:1.5

Respond in JSON format:
{{
    "order_type": "MARKET" or "LIMIT",
    "profit_target_pct": target percentage (positive, e.g. 3.0),
    "stop_loss_pct": stop loss percentage (negative, e.g. -2.0),
    "risk_reward_ratio": ratio (e.g. 1.5),
    "reasoning": "brief explanation"
}}
"""
            
            response = self.client.messages.create(
                model=self.model,
                system="You are an execution trader. Respond only in valid JSON.",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=300
            )
            
            content = response.content[0].text.strip()
            result = self._extract_json(content)
            
            # Ensure required keys exist with sane defaults
            result.setdefault('profit_target_pct', 3.0)
            result.setdefault('stop_loss_pct', -2.0)
            result.setdefault('risk_reward_ratio', 1.5)
            result.setdefault('order_type', 'MARKET')
            result.setdefault('reasoning', 'AI optimized')
            
            logger.info(f"   Order Type: {result.get('order_type', 'MARKET')}")
            logger.info(f"   Target: +{result['profit_target_pct']:.1f}%")
            logger.info(f"   Stop: {result['stop_loss_pct']:.1f}%")
            
            return result
            
        except Exception as e:
            logger.error(f"❌ Order optimization failed: {e}")
            return {
                'order_type': 'MARKET',
                'profit_target_pct': 3.0,
                'stop_loss_pct': -2.0,
                'risk_reward_ratio': 1.5,
                'reasoning': f'ChatGPT failed: {str(e)} — using defaults'
            }
    
    def assess_portfolio_risk(
        self,
        current_positions: List[Dict],
        available_capital: float,
        max_positions: int = 2
    ) -> Dict:
        """
        Assess overall portfolio risk.
        
        Returns:
            {
                'risk_level': 'LOW' | 'MEDIUM' | 'HIGH',
                'can_add_position': bool,
                'suggestions': List[str],
                'reasoning': str
            }
        """
        logger.info(f"🤖 CHATGPT PORTFOLIO RISK ASSESSMENT")
        
        try:
            positions_text = "\n".join([
                f"- {p['symbol']}: ₹{p.get('investment', 0):,.0f} ({p.get('pnl_pct', 0):+.1f}%)"
                for p in current_positions
            ])
            
            prompt = f"""You are a portfolio risk manager. Assess current portfolio risk.

PORTFOLIO STATUS:
=================
Current Positions: {len(current_positions)}/{max_positions}
{positions_text if positions_text else '- No positions'}

Available Capital: ₹{available_capital:,.0f}
Total Capital Usage: {sum(p.get('investment', 0) for p in current_positions):,.0f}

GUIDELINES:
===========
- Max positions: {max_positions}
- Risk per trade: Max 2% of capital
- Total exposure: Max 80% of capital
- Sector concentration: Max 40%

Assess:
1. Can we add another position?
2. Is current risk acceptable?
3. Any rebalancing needed?

Respond in JSON format:
{{
    "risk_level": "LOW" or "MEDIUM" or "HIGH",
    "can_add_position": true or false,
    "suggestions": ["suggestion 1", "suggestion 2"],
    "reasoning": "brief explanation"
}}
"""
            
            response = self.client.messages.create(
                model=self.model,
                system="You are a risk manager. Respond only in valid JSON.",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=400
            )
            
            content = response.content[0].text.strip()
            result = self._extract_json(content)
            
            logger.info(f"   Risk Level: {result.get('risk_level', 'MEDIUM')}")
            logger.info(f"   Can Add Position: {result.get('can_add_position', True)}")
            
            return result
            
        except Exception as e:
            logger.error(f"❌ Portfolio risk assessment failed: {e}")
            return {
                'risk_level': 'MEDIUM',
                'can_add_position': len(current_positions) < max_positions,
                'suggestions': [],
                'reasoning': f'ChatGPT failed: {str(e)}'
            }
    
    # ═══════════════════════════════════════════════════════════════════════════
    # PHASE 4 DECISION #1: POSITION EXIT EVALUATION (NEW!)
    # ═══════════════════════════════════════════════════════════════════════════
    
    def evaluate_position_for_phase4(
        self,
        position_data: Dict,
        market_strategist_opinion: Dict,
        live_market_sentiment: Dict = None,
        intelligence_package: Dict = None
    ) -> Dict:
        """
        Phase 4 Portfolio Manager decision - INTELLIGENT AI-FIRST SYSTEM.
        
        v4.8.1 TRANSFORMATION: From "Portfolio Risk Manager" to "PhD-Level Swing Trader"
        
        NEW CAPABILITIES:
        ─────────────────
        ✅ Probabilistic reasoning (P(target)=68%, not binary yes/no)
        ✅ Web search integration (breaking news, catalysts)
        ✅ Historical pattern matching (similar setups, outcomes)
        ✅ Multi-factor weighing (Weekly 40%, Cost 25%, Recovery 15%, etc.)
        ✅ Reasoning chain documentation (show probability calculations)
        ✅ Expected Value analysis (EV of HOLD vs EXIT)
        ✅ Alternative scenario exploration ("what if we tighten stop?")
        ✅ Stock-specific intelligence (typical recovery times, volatility profiles)
        ✅ Exit quality scoring (0-100 score for exit opportunity)
        
        OLD APPROACH: "TCAS RA → Ask ChatGPT → Get HOLD/EXIT"
        NEW APPROACH: "Synthesize ALL data → Calculate probabilities → Recommend with EV"
        
        Args:
            position_data: COMPREHENSIVE data package with:
                - position (symbol, prices, P&L)
                - tcas, ils, health, kalman (safety systems)
                - multi_timeframe (weekly/daily trends)
                - trading_costs (net P&L after fees)
                - stock_profile (typical behavior, volatility)
                - exit_score (0-100 exit opportunity quality)
                - regime (market conditions)
            market_strategist_opinion: Phase 1's market analysis
            live_market_sentiment: Fresh sentiment from Orchestrator
            
        Returns:
            {
                'decision': 'HOLD' | 'TIGHTEN_STOP' | 'EXIT' | 'PARTIAL_50' | ...,
                'confidence': float (0-1),
                
                # NEW v4.8.1: Probabilistic Analysis
                'probabilistic_analysis': {
                    'probability_target_hit': float,  # e.g., 0.68 (68%)
                    'probability_stop_hit': float,    # e.g., 0.22 (22%)
                    'expected_value_hold': float,     # e.g., +₹47
                    'expected_value_exit': float,     # e.g., -₹14
                    'time_horizon_minutes': int,      # e.g., 120
                    'probability_confidence': float   # How confident in the probabilities
                },
                
                # NEW v4.8.1: Reasoning Chain
                'reasoning_chain': [
                    "Step 1: Weekly trend UPTREND (85% confidence) - strong structural bias",
                    "Step 2: Current 65% recovered - typical V-pattern for this stock",
                    "Step 3: Net P&L negative (₹-14) - exit locks loss vs hold has upside",
                    "Step 4: Similar SYMPHONY setups: 4/5 hit target in 90-180 min",
                    "Step 5: Exit score 43/100 (POOR_EXIT) - too early",
                    "Step 6: Probability calc: 65% base × 1.05 health factor = 68%",
                    "Step 7: EV calc: 0.68×₹85 - 0.22×₹100 = +₹36 vs -₹14 exit",
                    "Conclusion: HOLD has +₹50 better EV, weekly trend supports"
                ],
                
                # NEW v4.8.1: Historical Context
                'similar_historical_cases': [
                    {
                        'date': '2026-01-28',
                        'symbol': 'SYMPHONY',
                        'setup': 'Weekly uptrend, daily dip, 60% recovered',
                        'decision_made': 'HOLD',
                        'outcome': 'Hit target in 95 min, +₹87'
                    }
                ],
                
                # NEW v4.8.1: Alternative Scenarios
                'alternative_scenarios': {
                    'if_tighten_stop_50pct': {
                        'new_stop': 901,
                        'locked_profit': 19,
                        'probability_stop_hit': 0.35,
                        'ev_change': -12,
                        'recommendation': 'Not optimal - reduces upside more than downside'
                    },
                    'if_partial_exit_50': {
                        'realized_pnl': -7,
                        'remaining_exposure': 50,
                        'ev_change': -18,
                        'recommendation': 'Worse than HOLD - locks loss on half position'
                    }
                },
                
                # EXISTING: Original format
                'reasoning': dict,
                'gtt_modifications': dict,
                'action_urgency': str
            }
        """
        
        # ═══════════════════════════════════════════════════════════════════
        # v4.8.1: INTELLIGENT SYSTEM PROMPT
        # ═══════════════════════════════════════════════════════════════════
        
        system_prompt = TRADER_PERSONA + """You are a PhD-LEVEL SWING TRADER with PROBABILISTIC INTELLIGENCE.

NOT a simple "Portfolio Risk Manager" - you are an INTELLIGENT TRADING BRAIN that:
✓ Thinks in PROBABILITIES, not binary yes/no
✓ Calculates EXPECTED VALUE for every decision
✓ Searches WEB for breaking news and catalysts
✓ Matches HISTORICAL PATTERNS from past trades
✓ Weighs MULTIPLE FACTORS intelligently
✓ Documents REASONING CHAIN transparently
✓ Explores ALTERNATIVE SCENARIOS

═══════════════════════════════════════════════════════════════════════════════
YOUR DECISION FRAMEWORK
═══════════════════════════════════════════════════════════════════════════════

STEP 1: GATHER ALL CONTEXT
───────────────────────────
You receive comprehensive data:
• Position details (entry, current, target, stop, P&L)
• Safety systems (TCAS, ILS, Health Score, Kalman predictions)
• Multi-timeframe trends (weekly uptrend? daily neutral?)
• Trading costs (gross vs net P&L after fees)
• Stock profile (typical recovery time, volatility, sector)
• Exit score (0-100 quality of this exit opportunity)
• Market regime (trending up/down, volatile, range-bound)

STEP 2: CALCULATE PROBABILITIES
────────────────────────────────
For EVERY decision, calculate:

P(target hit) = Base probability × Adjustments
  Base: Historical win rate for this setup type
  Adjustments:
    × 1.10 if weekly uptrend AND daily aligned
    × 0.90 if weekly uptrend BUT daily counter
    × 1.05 if health score > 70
    × 0.85 if health score < 50
    × 1.08 if exit score < 50 (poor exit = better hold)
    × 0.92 if exit score > 80 (good exit = maybe take)

P(stop hit) = 1 - P(target) - P(sideways)
  Typically: P(sideways) ≈ 10-15%

Time Horizon = Stock's avg recovery time × (% remaining to target / 100)
  Example: 120min typical recovery, 35% to go = 42 minutes

STEP 3: CALCULATE EXPECTED VALUE
─────────────────────────────────
For each option:

EV(HOLD) = P(target) × Gain_if_target - P(stop) × Loss_if_stop
  Example: 0.68 × ₹85 - 0.22 × ₹100 = +₹36

EV(EXIT_NOW) = Net P&L (after fees)
  Example: -₹14 (locking small loss)

EV(PARTIAL_50) = 0.5 × EXIT_NOW + 0.5 × EV(HOLD)
  Example: 0.5 × (-14) + 0.5 × 36 = +₹11

EV(TIGHTEN_STOP) = Modify P(stop) and recalculate
  Example: Tighten 50% → P(stop)=0.35 instead of 0.22
           0.68 × ₹65 - 0.35 × ₹80 = +₹16

Choose option with HIGHEST EV (unless other factors override)

STEP 4: APPLY INTELLIGENT WEIGHING
───────────────────────────────────
Weight factors by importance:

1. Weekly Trend (35% weight):
   - UPTREND with 85%+ confidence → Very bullish bias
   - DOWNTREND → Need very strong technicals to hold
   - NEUTRAL → Rely on daily trend

2. NSE Market Context (20% weight) — NEW:
   - NIFTY bullish + VIX low + breadth positive → Market supports holding
   - NIFTY bearish + VIX spiking + FII selling → Defensive, consider tightening
   - If stock is CNC and market is calm → daily noise is irrelevant

3. Daily Kalman Direction (15% weight) — NEW:
   - For CNC positions, use DAILY Kalman as PRIMARY direction indicator
   - 15-min Kalman is secondary (intraday noise for swing trades)
   - Daily BULLISH + Weekly UPTREND = strong hold signal
   - Daily BEARISH + Weekly still UPTREND = normal pullback, hold

4. Recovery Stage (10% weight):
   - Early recovery (20-40%) → lots of runway
   - Mid recovery (40-70%) → normal
   - Late recovery (70-90%) → target near

5. Health/Safety Systems (10% weight):
   - TCAS RA + Kalman bearish → Override EV, exit for safety
   - Health < 30 → Exit regardless
   - Otherwise trust EV calculation

6. Exit Score (5% weight):
   - Score < 50 (POOR_EXIT) → Favor HOLD
   - Score > 80 (EXCELLENT_EXIT) → Consider taking

7. Position Age & Product (5% weight) — NEW:
   - CNC Day 1-3: Very patient, do NOT exit for small losses
   - CNC Day 4+: Review thesis, is weekly trend still intact?
   - CNC: Fees are SUNK COST. Evaluate PURELY on price direction.
   - MIS: Must consider fees and same-day exit urgency

⚠️ CRITICAL CNC RULES (OVERRIDE ALL):
───────────────────────────────────────
1. CNC = delivery position. Can hold weeks/months. NO panic over daily noise.
2. Trading fees are ALREADY COMMITTED — ignore them in HOLD vs EXIT.
   Do NOT say "EXIT = net loss because of fees" as a reason to HOLD.
   Evaluate: "Is the STOCK going up or down?" not "Will fees make this a loss?"
3. Exit CNC ONLY when: weekly trend REVERSES, weekly support BREAKS,
   or the original entry thesis is FUNDAMENTALLY invalidated.
4. Small daily losses (1-2%) are NORMAL for swing positions.
5. If entry flight plan showed 70%+ BULLISH and weekly trend unchanged → HOLD.
6. If VIX spike >20 + NIFTY bearish + weekly trend breaking → consider EXIT.
7. Use Daily Kalman (1-3 day) for direction, NOT 15-min Kalman.

STEP 5: SEARCH WEB (When Needed)
─────────────────────────────────
Search for:
• Breaking news on the stock
• Sector-specific developments
• Market-moving events
• Analyst upgrades/downgrades

If found something material → adjust probabilities
Example: "Negative news on SYMPHONY → reduce P(target) by 10%"

STEP 6: MATCH HISTORICAL PATTERNS
──────────────────────────────────
Think: "Have I seen this setup before?"

Weekly uptrend + daily dip + 60-70% recovered + net loss
→ Check: How did similar cases resolve?
→ If 4 out of 5 hit target in 90-180 min → use this data!

STEP 7: DOCUMENT REASONING CHAIN
─────────────────────────────────
Show your work! Each step should be clear:

"Step 1: Weekly trend UPTREND (85%) provides strong structural support"
"Step 2: Recovery 65% complete, typical for V-pattern"
"Step 3: Net P&L -₹14 is minimal (< typical fee)"
"Step 4: Historical: 4/5 similar setups hit target in 90-180min"
"Step 5: P(target) = 65% base × 1.10 weekly × 1.05 health = 74.4%"
"Step 6: EV(HOLD) = 0.744×85 - 0.206×100 = +₹42.6"
"Step 7: EV(EXIT) = -₹14"
"Step 8: HOLD has ₹56.6 better EV → Recommend HOLD"

STEP 8: EXPLORE ALTERNATIVES
─────────────────────────────
Don't just pick one option - analyze 2-3:

"Alternative 1: HOLD → EV +₹42.6"
"Alternative 2: TIGHTEN_STOP_50% → EV +₹16 (worse, reduces upside)"
"Alternative 3: PARTIAL_50 → EV +₹11 (worse, locks loss on half)"
"Alternative 4: EXIT_NOW → EV -₹14 (worst option)"

Recommendation: HOLD (best EV by ₹26)

═══════════════════════════════════════════════════════════════════════════════
DECISION OPTIONS
═══════════════════════════════════════════════════════════════════════════════

HOLD - Continue monitoring, no changes
TIGHTEN_STOP - Move stop closer to lock profits (provide new price)
WIDEN_STOP - Move stop wider for overnight (only if weekly uptrend strong)
PARTIAL_25 - Exit 25% of position
PARTIAL_50 - Exit 50% of position  
EXIT - Full exit immediately
EXTEND_TARGET - Raise target if momentum very strong

═══════════════════════════════════════════════════════════════════════════════
CRITICAL RULES (OVERRIDE EV)
═══════════════════════════════════════════════════════════════════════════════

1. TCAS ALIM - Already handled, you won't see this
2. Health < 30 - EXIT immediately (critical condition)
3. TCAS RA + Kalman velocity < -0.05 + Health < 50 - EXIT (triple negative)
4. Net P&L > +₹500 + Exit Score > 85 - STRONGLY consider taking profit
5. Weekly DOWNTREND + Daily DOWNTREND + Net negative - EXIT (don't fight trend)

═══════════════════════════════════════════════════════════════════════════════
RESPONSE FORMAT
═══════════════════════════════════════════════════════════════════════════════

Respond ONLY with JSON (no other text):

{
  "decision": "HOLD|TIGHTEN_STOP|EXIT|...",
  "confidence": 0.75,
  
  "probabilistic_analysis": {
    "probability_target_hit": 0.744,
    "probability_stop_hit": 0.206,
    "expected_value_hold": 42.6,
    "expected_value_exit": -14.0,
    "time_horizon_minutes": 95,
    "probability_confidence": 0.85
  },
  
  "reasoning_chain": [
    "Step 1: ...",
    "Step 2: ...",
    ...
    "Conclusion: ..."
  ],
  
  "similar_historical_cases": [
    {
      "date": "2026-01-28",
      "symbol": "SYMPHONY",
      "setup": "Weekly up, daily dip, 60% recovered",
      "decision_made": "HOLD",
      "outcome": "Target hit 95min, +₹87"
    }
  ],
  
  "alternative_scenarios": {
    "if_tighten_stop_50pct": {
      "new_stop": 901,
      "locked_profit": 19,
      "probability_stop_hit": 0.35,
      "ev_change": -26.6,
      "recommendation": "Worse than HOLD by ₹26.6"
    }
  },
  
  "reasoning": {
    "primary": "EV(HOLD) = +₹42.6 vs EV(EXIT) = -₹14, weekly uptrend supports",
    "supporting": [
      "Historical: 4/5 similar setups succeeded",
      "Exit score 43/100 indicates poor timing",
      "Net loss minimal (₹14 < typical fees)"
    ],
    "risks": [
      "Market could reverse (20.6% chance)",
      "Time to target ~95min (may extend)"
    ]
  },
  
  "gtt_modifications": {
    "modify_stop": false,
    "new_stop_price": null,
    "modify_target": false,
    "new_target_price": null
  },
  
  "action_urgency": "NEXT_CYCLE"
}

═══════════════════════════════════════════════════════════════════════════════
REMEMBER
═══════════════════════════════════════════════════════════════════════════════

You are NOT just pattern matching rules.
You are CALCULATING probabilities and OPTIMIZING expected value.
You are SYNTHESIZING multiple data sources INTELLIGENTLY.
You are EXPLAINING your reasoning TRANSPARENTLY.

Be the PhD-level swing trader the system needs!
═══════════════════════════════════════════════════════════════════════════════
"""


        # ═══════════════════════════════════════════════════════════════════
        # v4.8.1: INTELLIGENT USER PROMPT - Rich Data Package
        # ═══════════════════════════════════════════════════════════════════
        
        # Prepare live sentiment section
        live_sentiment_text = ""
        if live_market_sentiment:
            live_sentiment_text = f"""
LIVE MARKET SENTIMENT (Most Recent):
{json.dumps(live_market_sentiment, indent=2)}
"""

        # Extract key metrics for easy access
        position = position_data.get('position', {})
        symbol = position.get('symbol', 'UNKNOWN')
        current_price = position.get('current_price', 0)
        entry_price = position.get('entry_price', current_price)
        target_price = position.get('target_price', current_price * 1.02)
        stop_price = position.get('stop_price', current_price * 0.98)
        
        # Calculate key percentages
        to_target_pct = ((target_price - current_price) / current_price) * 100 if current_price > 0 else 0
        to_stop_pct = ((current_price - stop_price) / current_price) * 100 if current_price > 0 else 0
        recovery_pct = ((current_price - entry_price) / (target_price - entry_price)) * 100 if (target_price - entry_price) > 0 else 0
        
        # Extract intelligence data
        multi_tf = position_data.get('multi_timeframe', {})
        weekly_trend = multi_tf.get('weekly_trend', 'UNKNOWN')
        weekly_confidence = multi_tf.get('weekly_confidence', 0)
        daily_trend = multi_tf.get('daily_trend', 'UNKNOWN')
        daily_confidence = multi_tf.get('daily_confidence', 0)
        
        trading_costs = position_data.get('trading_costs', {})
        net_pnl = trading_costs.get('net_pnl', 0)
        net_pnl_pct = trading_costs.get('net_pnl_pct', 0)
        
        stock_profile = position_data.get('stock_profile', {})
        typical_recovery_time = stock_profile.get('avg_recovery_time_min', 150)
        volatility_status = stock_profile.get('volatility_status', 'NORMAL')
        
        exit_score_data = position_data.get('exit_score', {})
        exit_score = exit_score_data.get('total_score', 50)
        exit_interpretation = exit_score_data.get('interpretation', 'UNKNOWN')
        
        health = position_data.get('health', {})
        health_score = health.get('total_score', 50) if isinstance(health, dict) else 50
        
        kalman = position_data.get('kalman', {})
        velocity = kalman.get('velocity', 0) if isinstance(kalman, dict) else 0
        acceleration = kalman.get('acceleration', 0) if isinstance(kalman, dict) else 0
        prediction_15min = kalman.get('prediction_15min', current_price) if isinstance(kalman, dict) else current_price
        
        # v4.15.0: CNC Swing Context extraction
        position_age = position_data.get('position_age', {})
        product_context = position_data.get('product_type_context', {})
        is_cnc = product_context.get('product', 'CNC') == 'CNC'
        daily_kalman = position_data.get('daily_kalman', {})
        nse_market = position_data.get('nse_market_context', {})
        flight_plan = position_data.get('flight_plan', {})
        
        # Build CNC-specific sections
        cnc_context_section = ""
        if is_cnc:
            cnc_context_section = f"""
POSITION TYPE & AGE:
────────────────────
Product: CNC (Delivery — can hold indefinitely, no same-day exit pressure)
{position_age.get('description', 'Unknown age')}
⚠️ CNC RULE: Daily noise (1-2% swings) is NORMAL for swing positions.
   Exit ONLY on: weekly trend reversal, weekly support break, or thesis invalidation.
   Fees are SUNK COST — do NOT let them bias HOLD vs EXIT analysis.
"""
        
        daily_kalman_section = ""
        if daily_kalman.get('available', False):
            dk = daily_kalman
            daily_kalman_section = f"""
DAILY KALMAN (Swing-Level Prediction):
───────────────────────────────────────
Direction: {dk.get('direction', 'UNKNOWN')} (Confidence: {dk.get('confidence', 0):.0f}%)
Daily Velocity: ₹{dk.get('daily_velocity', 0):.2f}/day
1-Day Prediction: ₹{dk['predictions'].get('1_day', 0):.2f} ({dk['prediction_change_pct'].get('1_day', 0):+.2f}%)
3-Day Prediction: ₹{dk['predictions'].get('3_day', 0):.2f} ({dk['prediction_change_pct'].get('3_day', 0):+.2f}%)
1-Week Prediction: ₹{dk['predictions'].get('1_week', 0):.2f} ({dk['prediction_change_pct'].get('1_week', 0):+.2f}%)
⚠️ For CNC: Use daily predictions as PRIMARY direction. 15-min Kalman is secondary (intraday noise).
"""
        
        nse_market_section = ""
        if nse_market:
            nifty = nse_market.get('nifty', {})
            vix = nse_market.get('vix', {})
            breadth = nse_market.get('breadth', {})
            fii_dii = nse_market.get('fii_dii', {})
            nse_market_section = f"""
NSE MARKET CONTEXT (Live):
──────────────────────────
NIFTY 50: {nifty.get('level', 0):.0f} ({nifty.get('change_pct', 0):+.2f}%) — {nifty.get('intraday_trend', 'UNKNOWN')}
India VIX: {vix.get('value', 15):.1f} ({vix.get('change_pct', 0):+.1f}%) — {vix.get('interpretation', 'UNKNOWN')}
Market Breadth: {breadth.get('advancing', 0)} advancing / {breadth.get('declining', 0)} declining — {breadth.get('interpretation', 'UNKNOWN')}
FII/DII: {json.dumps(fii_dii, indent=2) if isinstance(fii_dii, dict) and fii_dii.get('available', True) else 'Not available (use NIFTY+VIX as proxy)'}
Overall Mood: {nse_market.get('market_mood', 'UNKNOWN')}
"""
        
        flight_plan_section = ""
        if flight_plan:
            tf_scores = flight_plan.get('timeframe_scores', {})
            tf_display = " | ".join([f"{tf}={score:.0f}%" for tf, score in tf_scores.items()]) if tf_scores else "N/A"
            flight_plan_section = f"""
ENTRY FLIGHT PLAN (Generated at Position Open):
────────────────────────────────────────────────
Overall Truth Score: {flight_plan.get('overall_truth_score', 50):.0f}% {flight_plan.get('overall_direction', 'MIXED')}
By Timeframe: {tf_display}
Recommended Action: {flight_plan.get('recommended_action', 'UNKNOWN')} (Conf: {flight_plan.get('action_confidence', 50):.0f}%)
Strategy Note: {flight_plan.get('strategy_note', 'N/A')}
"""
        
        # v4.15.0: Volume+Price signal context
        vp_signal = position_data.get('position', {})  # Check phase4_tracking
        vp_tracking = position_data.get('phase4_tracking', {}) if isinstance(position_data.get('phase4_tracking'), dict) else {}
        last_vp = vp_tracking.get('last_vp_signal', {})
        # Also check nested in position_data structure
        if not last_vp:
            pos_tracking = position_data.get('position', {})
            if isinstance(pos_tracking, dict):
                last_vp = pos_tracking.get('phase4_tracking', {}).get('last_vp_signal', {}) if isinstance(pos_tracking.get('phase4_tracking'), dict) else {}
        
        vp_signal_section = ""
        if last_vp and last_vp.get('signal_type'):
            vp_signal_section = f"""
⚡ VOLUME + PRICE ALERT (ACTIVE):
──────────────────────────────────
Signal: {last_vp.get('emoji', '⚡')} {last_vp.get('signal_type', 'UNKNOWN')}
Volume: {last_vp.get('volume_ratio', 1.0):.1f}× normal ({last_vp.get('current_volume', 0):,.0f} vs {last_vp.get('expected_volume', 0):,.0f} expected)
Price Change: {last_vp.get('price_change_pct', 0):+.2f}% from open
Interpretation: {last_vp.get('interpretation', 'N/A')}
⚠️ This is a REAL-TIME institutional activity signal. Weight it heavily in your decision.
   BEARISH CONVICTION with volume = institutions are EXITING → consider following them.
   BULLISH CONVICTION with volume = institutions are ACCUMULATING → hold position.
"""

        # ═══════════════════════════════════════════════════════════════
        # MIE v1.0.0: Build Market Intelligence section for prompt
        # ═══════════════════════════════════════════════════════════════
        mie_section = ""
        if intelligence_package:
            mie_section = self._build_mie_prompt_section(intelligence_package)

        user_prompt = f"""
═══════════════════════════════════════════════════════════════════════════════
POSITION: {symbol}
═══════════════════════════════════════════════════════════════════════════════

CURRENT STATE:
─────────────
Entry: ₹{entry_price:.2f}
Current: ₹{current_price:.2f}
Target: ₹{target_price:.2f} ({to_target_pct:+.1f}% away)
Stop: ₹{stop_price:.2f} ({to_stop_pct:.1f}% cushion)
Recovery: {recovery_pct:.0f}% complete

FINANCIALS:
────────────────────────
Gross P&L: ₹{trading_costs.get('gross_pnl', 0):.2f}
Trading Fees: ₹{trading_costs.get('total_fees', 0):.2f} (sunk cost — already committed regardless of decision)
Net P&L: ₹{net_pnl:.2f} ({net_pnl_pct:+.2f}%)
Net Profit Potential (if target hit): ₹{trading_costs.get('net_profit_potential', 0):.2f}
Net Loss Risk (if stop hit): ₹{trading_costs.get('net_loss_risk', 0):.2f}
⚠️ NOTE: For CNC positions, fees should NOT influence HOLD vs EXIT decision.
   Evaluate purely on: "Is the stock price going towards target or stop?"

MULTI-TIMEFRAME TRENDS:
───────────────────────
Weekly: {weekly_trend} (Confidence: {weekly_confidence:.0f}%)
Daily: {daily_trend} (Confidence: {daily_confidence:.0f}%)
Alignment: {multi_tf.get('trend_alignment', 'UNKNOWN')}
Weekly Support: ₹{multi_tf.get('weekly_support', 0):.2f}
Weekly Resistance: ₹{multi_tf.get('weekly_resistance', 0):.2f}

⚠️ CRITICAL INSIGHT:
{multi_tf.get('trading_guidance', 'No guidance available')}

STOCK-SPECIFIC INTELLIGENCE:
─────────────────────────────
Sector: {stock_profile.get('sector', 'UNKNOWN')}
Typical Recovery Time: {typical_recovery_time} minutes
Current Volatility: {volatility_status} (vs typical {stock_profile.get('typical_atr_pct', 2.0):.1f}%)
NIFTY Correlation: {stock_profile.get('correlation_nifty', 0.5):.2f}
Typical RSI Bounce: {stock_profile.get('typical_rsi_bounce', 40)}
Notes: {stock_profile.get('notes', 'No specific notes')}

EXIT OPPORTUNITY SCORE:
───────────────────────
Total Score: {exit_score}/100 ({exit_interpretation})
Recommendation: {exit_score_data.get('recommendation', 'No recommendation')}
Confidence: {exit_score_data.get('confidence', 0.5):.0%}

Component Breakdown:
• Profit Quality: {exit_score_data.get('components', {}).get('profit', 0)}/25
• Technical Divergence: {exit_score_data.get('components', {}).get('divergence', 0)}/20
• Trend Alignment: {exit_score_data.get('components', {}).get('alignment', 0)}/20
• Momentum Fade: {exit_score_data.get('components', {}).get('momentum', 0)}/20
• Hold Time: {exit_score_data.get('components', {}).get('time', 0)}/15

SAFETY SYSTEMS:
───────────────
TCAS Alert: {position_data.get('tcas', {}).get('alert_level', 'UNKNOWN')}
ILS Phase: {position_data.get('ils', {}).get('landing_phase', 'UNKNOWN')}
Health Score: {health_score:.0f}/100 (Prediction component: {health.get('component_scores', {}).get('prediction', 0) if isinstance(health, dict) else 0:.0f}/15)

KALMAN PREDICTIONS (Intraday — 15min horizon):
────────────────────────────────────────────────
Velocity: {velocity:.4f} (rate of price change)
Acceleration: {acceleration:.4f} (momentum change)
15-min Prediction: ₹{prediction_15min:.2f}
Prediction Change: {((prediction_15min - current_price) / current_price * 100) if current_price > 0 else 0:+.2f}%
{daily_kalman_section}
{cnc_context_section}
{nse_market_section}
{flight_plan_section}
{vp_signal_section}
{mie_section}
MARKET STRATEGIST OPINION (Startup):
─────────────────────────────────────
{json.dumps(market_strategist_opinion, indent=2)}
{live_sentiment_text}

═══════════════════════════════════════════════════════════════════════════════
YOUR TASK
═══════════════════════════════════════════════════════════════════════════════

Based on this comprehensive data, make an INTELLIGENT, PROBABILISTIC decision.

Follow the framework in your system prompt:
1. Calculate P(target hit) and P(stop hit)
2. Calculate EV for HOLD, EXIT, and alternatives
3. Weigh factors (Weekly 40%, Cost 25%, Recovery 15%, Health 10%, Exit Score 10%)
4. Search web if needed for breaking news
5. Match historical patterns if similar
6. Document reasoning chain step-by-step
7. Explore 2-3 alternative scenarios
8. Choose option with best EV (unless critical rules override)

MIE INTELLIGENCE RULES (if Market Intelligence data present above):
- If ADX < 25 AND ATR interpretation = LOSS_WITHIN_NORMAL AND price WITHIN_1σ of VWAP → This is NOISE, bias HOLD
- If ADX > 25 AND price BELOW_2σ of VWAP AND MACD BEARISH_CROSS → REAL breakdown, consider EXIT
- If ATR interpretation = GAIN_OVEREXTENDED → Consider profit-taking, momentum may fade
- RESPECT your track record — if EXIT accuracy for similar setups is < 50%, bias HOLD
- CHECK real vs backtest gap — if backtest_vs_real_gap > 10%, your model is overoptimistic
- Product is shown in Context Instruction — follow the patience guidance for CNC vs MIS
- Use Composite Score ranking to prioritize which positions deserve most attention

RESPOND WITH JSON ONLY - NO OTHER TEXT.

Include:
• decision (HOLD|EXIT|TIGHTEN_STOP|etc)
• confidence (0-1)
• probabilistic_analysis (probabilities, EVs, time horizon)
• reasoning_chain (step-by-step logic)
• similar_historical_cases (if any match)
• alternative_scenarios (at least 1-2 alternatives)
• reasoning (primary/supporting/risks)
• gtt_modifications
• action_urgency

═══════════════════════════════════════════════════════════════════════════════
"""


        try:
            response = self.client.messages.create(
                model=self.model,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
                max_tokens=2000   # Increased for detailed reasoning chains
            )
            
            content = response.content[0].text
            result = self._extract_json(content)
            
            # ═══════════════════════════════════════════════════════════════
            # v4.8.1: Validate and provide defaults for new fields
            # ═══════════════════════════════════════════════════════════════
            
            # Core decision fields (existing)
            if 'decision' not in result:
                result['decision'] = 'HOLD'
            if 'confidence' not in result:
                result['confidence'] = 0.5
            if 'reasoning' not in result:
                result['reasoning'] = {'primary': 'No reasoning provided'}
            if 'gtt_modifications' not in result:
                result['gtt_modifications'] = {'modify_stop': False, 'modify_target': False}
            if 'action_urgency' not in result:
                result['action_urgency'] = 'NEXT_CYCLE'
            
            # NEW v4.8.1: Probabilistic analysis
            if 'probabilistic_analysis' not in result:
                result['probabilistic_analysis'] = {
                    'probability_target_hit': 0.5,
                    'probability_stop_hit': 0.3,
                    'expected_value_hold': 0,
                    'expected_value_exit': net_pnl,
                    'time_horizon_minutes': typical_recovery_time,
                    'probability_confidence': 0.5
                }
            
            # NEW v4.8.1: Reasoning chain
            if 'reasoning_chain' not in result:
                result['reasoning_chain'] = [
                    "Reasoning chain not provided by model",
                    f"Decision: {result['decision']} with {result['confidence']:.0%} confidence"
                ]
            
            # NEW v4.8.1: Historical cases
            if 'similar_historical_cases' not in result:
                result['similar_historical_cases'] = []
            
            # NEW v4.8.1: Alternative scenarios
            if 'alternative_scenarios' not in result:
                result['alternative_scenarios'] = {}
            
            # ═══════════════════════════════════════════════════════════════
            # v4.8.1: Enhanced logging with probabilistic insights
            # ═══════════════════════════════════════════════════════════════
            
            prob_analysis = result.get('probabilistic_analysis', {})
            logger.info(f"🤖 Phase 4 Decision: {result['decision']} (Confidence: {result['confidence']:.0%})")
            logger.info(f"   📊 Probabilities: P(target)={prob_analysis.get('probability_target_hit', 0):.0%}, "
                       f"P(stop)={prob_analysis.get('probability_stop_hit', 0):.0%}")
            logger.info(f"   💰 Expected Value: HOLD=₹{prob_analysis.get('expected_value_hold', 0):.0f}, "
                       f"EXIT=₹{prob_analysis.get('expected_value_exit', 0):.0f}")
            logger.info(f"   ⏱️ Time Horizon: {prob_analysis.get('time_horizon_minutes', 0):.0f} minutes")
            
            # Log reasoning chain
            reasoning_chain = result.get('reasoning_chain', [])
            if reasoning_chain and len(reasoning_chain) > 0:
                logger.info(f"   🧠 Reasoning Chain:")
                for step in reasoning_chain[:5]:  # First 5 steps
                    logger.info(f"      • {step}")
                if len(reasoning_chain) > 5:
                    logger.info(f"      ... +{len(reasoning_chain) - 5} more steps")
            
            
            # v3.4.0 NEW: Log to database
            self._log_ai_analysis(
                analysis_type='EXIT_EVALUATION',
                symbol=position.get('symbol', 'UNKNOWN'),
                context={
                    'current_price': position.get('current_price'),
                    'entry_price': position.get('entry_price'),
                    'net_pnl': position.get('net_pnl'),
                    'tcas_alert': position_data.get('tcas', {}).get('alert_level') if isinstance(position_data, dict) else None,
                    'health_score': position_data.get('health', {}).get('score') if isinstance(position_data, dict) else None
                },
                response=result
            )
            
            return result
            
        except Exception as e:
            logger.error(f"Phase 4 ChatGPT evaluation failed: {e}")
            return {
                'decision': 'HOLD',
                'confidence': 0.5,
                'reasoning': {'primary': f'Error: {str(e)}'},
                'gtt_modifications': {'modify_stop': False, 'modify_target': False},
                'action_urgency': 'NEXT_CYCLE',
                'probabilistic_analysis': {
                    'probability_target_hit': 0.5,
                    'probability_stop_hit': 0.3,
                    'expected_value_hold': 0,
                    'expected_value_exit': 0,
                    'time_horizon_minutes': 120,
                    'probability_confidence': 0.3
                },
                'reasoning_chain': [f"Error occurred: {str(e)}", "Defaulting to HOLD for safety"],
                'similar_historical_cases': [],
                'alternative_scenarios': {}
            }

    # ═══════════════════════════════════════════════════════════════════════════
    # PHASE 4 DECISION #2: LANDING PROBABILITY ANALYSIS (NEW!)
    # ═══════════════════════════════════════════════════════════════════════════
    
    def analyze_landing_probability(
        self,
        position_data: Dict,
        time_analysis: Dict,
        historical_data: Dict = None
    ) -> Dict:
        """
        Analyze probability of reaching target today vs tomorrow.
        
        Called at 14:30 to decide whether to:
        - Let GTT target trigger today
        - Hold overnight for tomorrow
        - Take partial profit now
        - Exit immediately
        
        Args:
            position_data: Position with Kalman predictions
            time_analysis: Time remaining, market hours, etc.
            historical_data: Optional historical stock behavior
            
        Returns:
            {
                'landing_decision': 'LAND_TODAY' | 'HOLD_FOR_TOMORROW' | 
                                   'PARTIAL_PROFIT_NOW' | 'EXIT_NOW',
                'confidence': float,
                'probability_analysis': {
                    'prob_target_today': float,
                    'prob_target_tomorrow': float,
                    'prob_stop_hit_overnight': float
                },
                'gtt_modifications': dict,
                'product_conversion': dict
            }
        """
        system_prompt = """You are a LANDING PROBABILITY ANALYST for an autonomous trading system.

Your job is to analyze whether a position can reach its target TODAY, or if it should be held OVERNIGHT for tomorrow.

ANALYSIS FACTORS:
=================
1. Current progress towards target (%)
2. Kalman velocity (price movement rate)
3. Time remaining in market hours
4. Tomorrow's expected market conditions
5. Overnight gap risk

DECISIONS:
==========
- LAND_TODAY: High probability of hitting target today, keep current GTT
- HOLD_FOR_TOMORROW: Won't reach today, but tomorrow looks good, widen stop for overnight
- PARTIAL_PROFIT_NOW: Momentum fading, take some profit, let rest ride
- EXIT_NOW: Low probability of target, conditions deteriorating

CONSIDERATIONS:
===============
- MIS positions MUST be converted to CNC for overnight hold
- Overnight gaps average 0.3-0.5% for NIFTY stocks
- Wider stop needed for overnight to survive gaps
- Friday holding = weekend risk

Respond ONLY with a JSON object."""

        user_prompt = f"""POSITION DATA:
{json.dumps(position_data, indent=2)}

TIME ANALYSIS:
{json.dumps(time_analysis, indent=2)}

Analyze landing probability and provide decision.

Respond with:
{{
    "landing_decision": "LAND_TODAY|HOLD_FOR_TOMORROW|PARTIAL_PROFIT_NOW|EXIT_NOW",
    "confidence": 0.0-1.0,
    "probability_analysis": {{
        "prob_target_today": 0.0-1.0,
        "prob_target_tomorrow": 0.0-1.0,
        "prob_stop_hit_overnight": 0.0-1.0
    }},
    "reasoning": "explanation",
    "gtt_modifications": {{
        "modify_stop": true/false,
        "new_stop_price": price or null,
        "reason": "why modifying"
    }},
    "product_conversion": {{
        "convert_to_cnc": true/false,
        "reason": "why converting"
    }},
    "expected_landing": {{
        "expected_day": "TODAY|TOMORROW|UNCERTAIN",
        "expected_exit_reason": "TARGET|TRAILING|TIME"
    }}
}}"""

        try:
            response = self.client.messages.create(
                model=self.model,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
                max_tokens=800
            )
            
            content = response.content[0].text
            result = self._extract_json(content)
            
            # Validate
            if 'landing_decision' not in result:
                result['landing_decision'] = 'HOLD_FOR_TOMORROW'
            if 'confidence' not in result:
                result['confidence'] = 0.5
            
            logger.info(f"🛬 Landing Decision: {result['landing_decision']} (Confidence: {result['confidence']:.0%})")
            
            return result
            
        except Exception as e:
            logger.error(f"Landing probability analysis failed: {e}")
            return {
                'landing_decision': 'HOLD_FOR_TOMORROW',
                'confidence': 0.5,
                'probability_analysis': {
                    'prob_target_today': 0.3,
                    'prob_target_tomorrow': 0.5,
                    'prob_stop_hit_overnight': 0.15
                },
                'gtt_modifications': {'modify_stop': False},
                'product_conversion': {'convert_to_cnc': False}
            }

    # ═══════════════════════════════════════════════════════════════════════════
    # PHASE 4 DECISION #3: PORTFOLIO MORNING BRIEFING (NEW!)
    # ═══════════════════════════════════════════════════════════════════════════
    
    def portfolio_morning_briefing(
        self,
        yesterday_data: Dict,
        current_positions: List[Dict],
        market_strategist_opinion: Dict,
        live_market_sentiment: Dict = None
    ) -> Dict:
        """
        Morning briefing for Phase 4 startup.
        
        Reviews yesterday's performance and current open positions
        to decide operation mode for today.
        
        Args:
            yesterday_data: Performance data from yesterday
            current_positions: List of open positions (overnight holds)
            market_strategist_opinion: Phase 1's market analysis
            live_market_sentiment: Fresh sentiment from Orchestrator (if available)
            
        Returns:
            {
                'operation_mode': 'NORMAL' | 'CAUTIOUS' | 'DEFENSIVE' | 'CLOSE_ALL',
                'position_decisions': [per-position decisions],
                'risk_assessment': str,
                'summary': str
            }
        """
        system_prompt = """You are the PORTFOLIO RISK MANAGER conducting a morning briefing.

Your colleague, the MARKET STRATEGIST, has analyzed today's market outlook.
You may also have LIVE MARKET SENTIMENT which is more current - use it if available.
You have overnight positions that need to be evaluated.

YOUR TASKS:
===========
1. Assess each overnight position based on market outlook
2. Decide operation mode for today
3. Give specific action for each position

OPERATION MODES:
================
- NORMAL: Standard monitoring, all systems active
- CAUTIOUS: Tighter stops, quicker exits, reduced new entries
- DEFENSIVE: Very tight stops, close positions at first sign of weakness
- CLOSE_ALL: Exit all positions immediately (crisis mode)

POSITION ACTIONS:
=================
- HOLD: Continue monitoring
- TIGHTEN_STOP: Lock in overnight gap profit
- EXIT: Close position
- WATCH_CLOSELY: Position at risk, monitor closely

Respond ONLY with a JSON object."""

        # Prepare live sentiment section
        live_sentiment_text = ""
        if live_market_sentiment:
            live_sentiment_text = f"""

LIVE MARKET SENTIMENT (More Recent):
{json.dumps(live_market_sentiment, indent=2)}
"""

        user_prompt = f"""MARKET STRATEGIST OPINION:
{json.dumps(market_strategist_opinion, indent=2)}
{live_sentiment_text}
OVERNIGHT POSITIONS:
{json.dumps(current_positions, indent=2)}

YESTERDAY DATA:
{json.dumps(yesterday_data, indent=2)}

Provide morning briefing.

Respond with:
{{
    "operation_mode": "NORMAL|CAUTIOUS|DEFENSIVE|CLOSE_ALL",
    "mode_reasoning": "why this mode",
    "position_decisions": [
        {{
            "symbol": "STOCK",
            "action": "HOLD|TIGHTEN_STOP|EXIT|WATCH_CLOSELY",
            "reasoning": "why",
            "new_stop_price": null or price
        }}
    ],
    "risk_assessment": "overall risk assessment",
    "today_outlook": "brief outlook",
    "summary": "2-3 sentence summary"
}}"""

        try:
            response = self.client.messages.create(
                model=self.model,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
                max_tokens=1000
            )
            
            content = response.content[0].text
            result = self._extract_json(content)
            
            if 'operation_mode' not in result:
                result['operation_mode'] = 'NORMAL'
            if 'position_decisions' not in result:
                result['position_decisions'] = []
            if 'summary' not in result:
                result['summary'] = 'Morning briefing completed.'
            
            logger.info(f"☀️ Morning Briefing: {result['operation_mode']} mode")
            logger.info(f"   {result.get('summary', '')}")
            
            return result
            
        except Exception as e:
            logger.error(f"Morning briefing failed: {e}")
            return {
                'operation_mode': 'NORMAL',
                'position_decisions': [],
                'risk_assessment': 'Unable to assess',
                'summary': f'Morning briefing error: {str(e)}'
            }
    
    # ═══════════════════════════════════════════════════════════════════════════
    # MIE v1.0.0: Market Intelligence Prompt Builder
    # ═══════════════════════════════════════════════════════════════════════════

    def _build_mie_prompt_section(self, ip: Dict) -> str:
        """
        Build the MARKET INTELLIGENCE section for ChatGPT prompts.
        Takes an IntelligencePackage.to_dict() output and formats it
        for insertion into entry or exit prompts.

        Args:
            ip: dict from IntelligencePackage.to_dict()

        Returns:
            Formatted string section, or empty string if ip is None/empty.
        """
        if not ip:
            return ""

        mie_section = """
MARKET INTELLIGENCE (MIE v1.0.0):
══════════════════════════════════
"""
        # VWAP Context
        if ip.get('vwap'):
            v = ip['vwap']
            mie_section += f"""📍 VWAP CONTEXT:
- VWAP: ₹{v.get('vwap_price', 0):.2f} | Current: ₹{v.get('current_price', 0):.2f} ({v.get('distance_from_vwap_pct', 0):+.2f}%)
- Band Position: {v.get('band_position', 'UNKNOWN')} | Signal: {v.get('signal', 'UNKNOWN')}
- Prev Day POC: ₹{v.get('prev_day_poc', 0):.2f} | Value Area: {v.get('price_vs_value_area', 'UNKNOWN')}
"""

        # Momentum Stack
        if ip.get('momentum'):
            m = ip['momentum']
            mie_section += f"""📊 MOMENTUM ANALYSIS:
- MACD: {m.get('macd_signal_cross', 'NONE')} | Trend: {m.get('macd_trend', 'FLAT')} | Histogram: {m.get('macd_histogram', 0):.4f}
- Stochastic: K={m.get('stochastic_k', 50):.1f} D={m.get('stochastic_d', 50):.1f} | Zone: {m.get('stochastic_zone', 'NEUTRAL')} | Cross: {m.get('stochastic_cross', 'NONE')}
- ADX: {m.get('adx_value', 0):.1f} → {m.get('adx_trend_strength', 'UNKNOWN')} | {m.get('adx_implication', '')}
- Verdict: {m.get('momentum_verdict', 'NEUTRAL')}
"""

        # V-Recovery Quality
        if ip.get('v_recovery'):
            vr = ip['v_recovery']
            mie_section += f"""🔄 V-RECOVERY QUALITY:
- {vr.get('interpretation', 'No data')}
- Quality Score: {vr.get('quality_score', 0):.1f}/20 → {vr.get('quality_grade', 'UNKNOWN')}
"""

        # ATR Context
        if ip.get('atr'):
            a = ip['atr']
            mie_section += f"""📏 ATR VOLATILITY CONTEXT:
- ATR(14): ₹{a.get('atr_value', 0)} ({a.get('atr_pct_of_price', 0):.2f}% of price)
- Move from entry: ₹{a.get('current_drop_from_entry', 0):.2f} = {a.get('drop_as_atr_multiple', 0):.1f}× ATR → {a.get('drop_interpretation', 'UNKNOWN')}
- Suggested Stop: ₹{a.get('suggested_stop_normal', 0):.2f} (2×ATR) | Target: ₹{a.get('suggested_target_3x', 0):.2f} (3×ATR)
- Risk:Reward from current: {a.get('risk_reward_from_current', 0):.1f}:1 → {a.get('risk_reward_interpretation', 'UNKNOWN')}
"""

        # Composite Score
        if ip.get('composite'):
            c = ip['composite']
            mie_section += f"""🏆 COMPOSITE SCORE: {c.get('total_score', 0):.0f}/100 → {c.get('position_size_recommendation', 'UNKNOWN')}
- R:R={c.get('risk_reward_score', 0)}/25 | V-Rec={c.get('v_recovery_score', 0):.0f}/20 | Trend={c.get('trend_alignment_score', 0)}/15 | Vol={c.get('volume_confirmation_score', 0)}/15
- Timing={c.get('session_timing_score', 0)}/10 | Confluence={c.get('indicator_confluence_score', 0)}/10 | Liq={c.get('liquidity_score', 0)}/5
"""
            if c.get('total_candidates', 0) > 0:
                mie_section += f"- Rank: #{c.get('rank_among_candidates', 0)} of {c.get('total_candidates', 0)} candidates\n"

        # Expiry Cycle
        if ip.get('expiry_cycle'):
            e = ip['expiry_cycle']
            mie_section += f"""📅 EXPIRY CYCLE:
- {e.get('today_weekday', 'UNKNOWN')}: {e.get('cycle_position', 'UNKNOWN')} | Pressure: {e.get('expected_pressure', 'UNKNOWN')}
- {e.get('trading_implication', '')}
"""

        # Decision History
        if ip.get('decision_history'):
            dh = ip['decision_history']
            mie_section += f"""🧠 YOUR TRACK RECORD:
- Total Decisions: {dh.get('total_decisions', 0)} | EXIT Accuracy: {dh.get('exit_accuracy_pct', 0):.0f}% | HOLD Accuracy: {dh.get('hold_accuracy_pct', 0):.0f}%
- {dh.get('learning_insight', 'No insight available')}
"""
            if dh.get('similar_past_cases'):
                mie_section += "- Similar Past Cases:\n"
                for case in dh['similar_past_cases'][:3]:
                    mie_section += f"  • {case.get('date', '?')}: {case.get('symbol', '?')} — {case.get('decision_made', '?')} → {case.get('outcome', '?')}\n"

        # Performance Metrics (Layer 8)
        if ip.get('performance'):
            perf = ip['performance']
            mie_section += f"""📈 REAL vs SIMULATED PERFORMANCE:
- Phase 3 (CNC): {perf.get('phase3_real_trades', 0)} real trades | Win Rate: {perf.get('phase3_real_win_rate', 0):.1f}% | Avg Profit: {perf.get('phase3_real_avg_profit_pct', 0):.2f}% | Avg Loss: {perf.get('phase3_real_avg_loss_pct', 0):.2f}%
- Phase 5 (MIS): {perf.get('phase5_real_trades', 0)} real trades | Win Rate: {perf.get('phase5_real_win_rate', 0):.1f}%
- Backtest Win Rate: {perf.get('backtest_win_rate', 0):.1f}% | Gap (backtest - real): {perf.get('backtest_vs_real_gap', 0):+.1f}%
- {perf.get('confidence_note', 'No performance data')}
"""

        # Capital State
        if ip.get('capital'):
            cap = ip['capital']
            mie_section += f"""💰 CAPITAL STATE:
- Total: ₹{cap.get('total_capital', 0):,.0f} | Deployed: ₹{cap.get('deployed_amount', 0):,.0f} | Available: ₹{cap.get('available_amount', 0):,.0f}
- Max per stock: ₹{cap.get('max_per_stock', 0):,.0f} | Can fit entry: {'YES' if cap.get('can_fit_new_entry', False) else 'NO'}
- Entry budget: ₹{cap.get('entry_budget', 0):,.0f} | Buffer remaining: ₹{cap.get('buffer_remaining', 0):,.0f}
"""

        # Crash Matrix (CRITICAL)
        if ip.get('crash_matrix'):
            cm = ip['crash_matrix']
            mie_section += f"""⚠️ CONTEXT INSTRUCTION:
- Phase: {cm.get('phase_source', 'UNKNOWN')} | Product: {cm.get('product_type', 'UNKNOWN')} | Patience: {cm.get('patience_level', 'UNKNOWN')}
- {cm.get('crash_response_instruction', 'No instruction')}
"""

        return mie_section

    # ═══════════════════════════════════════════════════════════════════════════
    # UTILITY METHODS
    # ═══════════════════════════════════════════════════════════════════════════

    def _extract_json(self, text: str) -> Dict:
        """Extract JSON from ChatGPT response"""
        try:
            # Remove markdown if present
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                text = text.split("```")[1].split("```")[0].strip()
            
            return json.loads(text)
        except:
            # Fallback: Try to find JSON in text
            match = re.search(r'\{.*\}', text, re.DOTALL)
            if match:
                return json.loads(match.group(0))
            raise ValueError("Could not extract JSON from response")
    
    def _format_dict(self, d: Dict) -> str:
        """Format dict for logging"""
        return "\n".join([f"  {k}: {v}" for k, v in d.items()])


# ═══════════════════════════════════════════════════════════════════════════════
# HELPER FUNCTION
# ═══════════════════════════════════════════════════════════════════════════════

def classify_kalman_trend(kalman_state: Dict) -> str:
    """
    Classify Kalman trend based on velocity and acceleration.
    
    Returns: One of:
    - ACCELERATING_UP
    - STEADY_UP
    - FADING_UP
    - ACCELERATING_DOWN
    - STEADY_DOWN
    - FADING_DOWN
    - STAGNANT
    """
    velocity = kalman_state.get('velocity', 0)
    acceleration = kalman_state.get('acceleration', 0)
    
    if abs(velocity) < 1:
        return 'STAGNANT'
    
    if velocity > 0:
        if acceleration > 1:
            return 'ACCELERATING_UP'
        elif acceleration < -1:
            return 'FADING_UP'
        else:
            return 'STEADY_UP'
    else:
        if acceleration < -1:
            return 'ACCELERATING_DOWN'
        elif acceleration > 1:
            return 'FADING_DOWN'
        else:
            return 'STEADY_DOWN'


if __name__ == "__main__":
    print("ChatGPT Strategic Advisor v3.0 - Phase 4 Integrated")
    print("=" * 80)
    print("Capabilities:")
    print("1. Entry signal approval (with Kalman predictions)")
    print("2. Position sizing")
    print("3. Adaptive scan decisions")
    print("4. Shutdown decisions")
    print("5. Position tracking")
    print("6. Phase 4: Exit evaluation (NEW)")
    print("7. Phase 4: Landing probability (NEW)")
    print("8. Phase 4: Morning briefing (NEW)")
