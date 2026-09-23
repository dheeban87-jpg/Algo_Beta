"""
PHASE 2 INTELLIGENT INTEGRATION v2.1.0 - AUDIT FIX RELEASE
===============================================================================

v2.1.0 CRITICAL AUDIT FIXES (2026-02-03):
- FIXED: All getattr() calls now handle None values properly
- FIXED: Wrong attribute name 'prev_rsi' -> 'previous_rsi'  
- ADDED: Defensive None checks in signal enrichment
- ADDED: Warning logs when using fallback defaults

Author: Trading System v2.1 (Audit Fix)
Date: 2026-02-03
"""

import logging
from typing import List, Optional, Dict, Any
from datetime import datetime

logger = logging.getLogger('IntelligentPhase2')

# Try to import
try:
    from intelligent_engine import (
        IntelligentDecisionEngine, 
        IntelligentSignal, 
        SignalStrength,
        MarketRegime
    )
    ENGINE_VERSION = "1.3"
except ImportError:
    try:
        from intelligent_engine_v1_1 import (
            IntelligentDecisionEngine, 
            IntelligentSignal, 
            SignalStrength,
            MarketRegime
        )
        ENGINE_VERSION = "1.1"
    except ImportError:
        raise ImportError("Could not import IntelligentDecisionEngine")

# Import ChatGPT Strategic Advisor
try:
    from chatgpt_strategic_advisor import ChatGPTStrategicAdvisor, classify_kalman_trend
    CHATGPT_AVAILABLE = True
except ImportError:
    logger.warning("ChatGPTStrategicAdvisor not available - signals will auto-approve")
    CHATGPT_AVAILABLE = False


def safe_getattr(obj, attr: str, default):
    """
    Safely get attribute from object, handling None values.
    
    Python gotcha: getattr(obj, 'attr', default) returns None if attr EXISTS with value None!
    This function ensures we always get a usable value.
    """
    value = getattr(obj, attr, None)
    if value is None:
        return default
    return value


class IntelligentPhase2Wrapper:
    """
    Wrapper that adds intelligent scoring to Phase 2 signals.
    
    v2.1.0: AUDIT FIX - All None handling bugs fixed
    """
    
    def __init__(self, phase2, kite, config, telegram=None):
        self.phase2 = phase2
        self.kite = kite
        self.config = config
        self.telegram = telegram
        
        # Initialize Intelligent Engine
        self.intelligent_engine = IntelligentDecisionEngine(kite, config, telegram)
        
        # Initialize ChatGPT Strategic Advisor
        if CHATGPT_AVAILABLE and getattr(config, 'ENABLE_CHATGPT_STRATEGIC_ADVISOR', False):
            try:
                logger.info("Initializing ChatGPT Strategic Advisor...")
                self.strategic_advisor = ChatGPTStrategicAdvisor(
                    api_key=config.CHATGPT_API_KEY,
                    model=getattr(config, 'GPT_MODEL', 'gpt-4o')
                )
                logger.info("Strategic Advisor ready")
            except Exception as e:
                logger.error(f"Strategic Advisor initialization failed: {e}")
                self.strategic_advisor = None
        else:
            self.strategic_advisor = None
            logger.info("Strategic Advisor DISABLED - signals will auto-approve")
        
        self.last_raw_signals = []
        self.last_intelligent_signals = []

        # MIE v1.0.0: Market Intelligence Engine (set by Orchestrator)
        self.mie = None
        
        logger.info("=" * 80)
        logger.info(f"INTELLIGENT PHASE 2 WRAPPER v2.1.0 - AUDIT FIX (Engine v{ENGINE_VERSION})")
        logger.info("=" * 80)
        logger.info("v2.1.0 Audit Fixes:")
        logger.info("  - All getattr() calls now handle None properly")
        logger.info("  - Fixed wrong attribute name prev_rsi -> previous_rsi")
        logger.info("  - Warning logs when using fallback defaults")
    
    def get_intelligent_signals(self) -> List[IntelligentSignal]:
        """Get signals from Phase 2 and enhance them with intelligent scoring."""
        logger.info("")
        logger.info("-" * 80)
        logger.info("INTELLIGENT SIGNAL ANALYSIS v2.1.0")
        logger.info("-" * 80)
        
        # Step 1: Get raw signals from Phase 2
        raw_signals = self.phase2.check_entry_signals()
        self.last_raw_signals = raw_signals
        
        if not raw_signals:
            logger.info("No raw signals from Phase 2")
            return []
        
        logger.info(f"Received {len(raw_signals)} raw signals from Phase 2")
        
        # Step 2: Enrich signals with additional data for scoring
        enriched_signals = self._enrich_signals(raw_signals)
        
        # Step 2.5 (v5.3.0): RANK signals by composite score — best candidates first
        # Like Phase 5 Step 4: score = recovery% × volume × ADX × trend
        enriched_signals = self._rank_signals(enriched_signals)
        
        # Step 2.6 (v5.3.0): Limit to top N candidates based on available positions
        max_candidates = getattr(self.config, 'MAX_CANDIDATES_PER_CYCLE', 5)
        if len(enriched_signals) > max_candidates:
            logger.info(f"📊 Ranking: {len(enriched_signals)} signals → top {max_candidates}")
            enriched_signals = enriched_signals[:max_candidates]
        
        # Step 3: Process through Intelligent Engine
        intelligent_signals = self.intelligent_engine.process_signals(enriched_signals)
        self.last_intelligent_signals = intelligent_signals
        
        # Step 4: Send notification if enabled
        if getattr(self.config, 'SEND_INTELLIGENT_ANALYSIS', True):
            self.intelligent_engine.send_analysis_notification(intelligent_signals)
        
        return intelligent_signals
    
    def get_tradeable_signals(self) -> List[IntelligentSignal]:
        """Get only signals that should be traded (score >= threshold)."""
        intelligent_signals = self.get_intelligent_signals()
        
        # Filter by score first
        tradeable = self.intelligent_engine.get_tradeable_signals(intelligent_signals)
        
        if not tradeable:
            return []
        
        # GPT APPROVAL GATE
        if self.strategic_advisor and getattr(self.config, 'GPT_APPROVE_ENTRIES', True):
            approved_signals = []
            
            for signal in tradeable:
                try:
                    logger.info("")
                    logger.info("Consulting ChatGPT for approval...")
                    
                    raw = signal.raw_signal
                    kalman_prediction = raw.get('kalman_prediction') or {}
                    
                    # ═══════════════════════════════════════════════════════
                    # MIE v1.0.0: Build entry intelligence context
                    # ═══════════════════════════════════════════════════════
                    mie_intelligence = None
                    if self.mie:
                        try:
                            monitor = self._get_monitor(signal.symbol)
                            intelligence = self.mie.get_entry_context(
                                symbol=signal.symbol,
                                stock_monitor=monitor,
                                phase_source="PHASE_2",
                                product_type=getattr(self.config, 'PRODUCT_TYPE', 'CNC'),
                                all_candidates=[{
                                    'symbol': s.symbol,
                                    'raw_signal': s.raw_signal,
                                    'monitor': self._get_monitor(s.symbol)
                                } for s in tradeable],
                                v_recovery_data=raw.get('v_recovery_data')
                            )
                            mie_intelligence = intelligence.to_dict() if intelligence else None
                            if mie_intelligence:
                                logger.info(f"   📊 MIE entry context built for {signal.symbol}")
                        except Exception as e:
                            logger.warning(f"   ⚠️ MIE entry context failed: {e}")
                            mie_intelligence = None

                    gpt_decision = self.strategic_advisor.review_entry_signal(
                        symbol=signal.symbol,
                        entry_price=raw.get('entry_price') or raw.get('ltp') or 0,
                        rsi=raw.get('rsi') or 50,
                        rsi_threshold=raw.get('rsi_threshold') or 35,
                        sentiment=raw.get('sentiment') or {'label': 'NEUTRAL', 'score': 0},
                        market_regime=signal.market_regime.value,
                        technical_score=signal.technical_score,
                        intelligent_score=signal.total_score,
                        v_recovery_data=raw.get('v_recovery_data'),
                        volume_ratio=raw.get('volume_ratio') or 1.0,
                        nifty_change_pct=raw.get('nifty_change_pct') or 0,
                        kalman_prediction=kalman_prediction,
                        rsi_history=raw.get('rsi_history'),
                        adx_value=raw.get('adx_value'),
                        volume_spike_at_reversal=raw.get('volume_spike_at_reversal'),
                        entry_score=raw.get('entry_score') or raw.get('phase2_score'),
                        finbert_contribution=raw.get('finbert_contribution'),
                        # v5.3.2: Pass chatgpt_package for web search routing
                        chatgpt_package=raw.get('phase2_chatgpt_package'),
                        # MIE v1.0.0: Intelligence package for enriched prompts
                        intelligence_package=mie_intelligence,
                    )
                    
                    if gpt_decision['decision'] == 'ENTER':
                        signal.raw_signal['gpt_decision'] = gpt_decision
                        signal.raw_signal['gpt_approved'] = True
                        # v5.6 FIX: Preserve Phase 2 grade-based multiplier when GPT doesn't provide sizing
                        # In LANDMINE_ONLY mode, GPT doesn't suggest position_pct → use Phase 2's 0.75x for MODERATE_BUY
                        gpt_position_pct = gpt_decision.get('suggested_position_pct')
                        if gpt_position_pct and gpt_position_pct > 0:
                            signal.raw_signal['position_multiplier'] = gpt_position_pct
                        else:
                            signal.raw_signal['position_multiplier'] = signal.raw_signal.get('phase2_position_multiplier', 1.0)
                        signal.raw_signal['chatgpt_web_news'] = gpt_decision.get('web_news', '')
                        signal.raw_signal['chatgpt_delivery_signal'] = gpt_decision.get('delivery_signal', 'UNKNOWN')
                        signal.raw_signal['chatgpt_oi_signal'] = gpt_decision.get('oi_signal', 'UNKNOWN')
                        signal.raw_signal['chatgpt_landmine_found'] = gpt_decision.get('landmine_found', False)

                        # v5.5: These fields NO LONGER come from ChatGPT in LANDMINE_ONLY mode
                        # S/R, stops, targets come from Phase 2 signal dict (PDH/PDL/ATR)
                        # Only set them from ChatGPT if in FULL_ANALYSIS mode (rollback)
                        if getattr(self.config, 'CHATGPT_MODE', 'LANDMINE_ONLY') == 'FULL_ANALYSIS':
                            signal.raw_signal['chatgpt_web_pattern'] = gpt_decision.get('web_pattern', '')
                            signal.raw_signal['chatgpt_analyst_confirms'] = gpt_decision.get('analyst_confirms_entry', False)
                            signal.raw_signal['chatgpt_suggested_entry_price'] = gpt_decision.get('suggested_entry_price')
                            signal.raw_signal['chatgpt_nearest_support'] = gpt_decision.get('nearest_support')
                            signal.raw_signal['chatgpt_nearest_resistance'] = gpt_decision.get('nearest_resistance')
                            signal.raw_signal['chatgpt_adjusted_stop_price'] = gpt_decision.get('adjusted_stop_price')
                            signal.raw_signal['chatgpt_adjusted_target_price'] = gpt_decision.get('adjusted_target_price')

                        # v5.3.1: Reserve capital HERE (after GPT approval, not in Phase 2)
                        # This eliminates phantom reservations from IE/GPT rejected signals
                        if self.phase2 and hasattr(self.phase2, 'capital_manager') and self.phase2.capital_manager:
                            entry_size = signal.raw_signal.get('entry_size', 0)
                            if entry_size > 0:
                                reserve_result = self.phase2.capital_manager.reserve_capital(
                                    symbol=signal.symbol,
                                    amount=entry_size
                                )
                                if reserve_result.get('reserved', False):
                                    signal.raw_signal['capital_reserved'] = True
                                    signal.raw_signal['reservation_id'] = reserve_result.get('reservation_id')
                                    logger.info(f"💰 {signal.symbol}: Capital reserved ₹{entry_size:,.0f} (post-GPT)")
                                else:
                                    logger.warning(f"💰 {signal.symbol}: Capital reservation failed — skipping")
                                    continue  # Skip this signal if can't reserve
                        
                        approved_signals.append(signal)
                        
                        logger.info(f"GPT APPROVED: {signal.symbol}")
                        logger.info(f"   Confidence: {gpt_decision.get('confidence', 0)}%")
                        
                        if self.telegram:
                            entry_price = raw.get('entry_price') or 0
                            # v5.4: Enhanced notification with S/R + institutional data
                            sr_info = ""
                            if gpt_decision.get('nearest_support'):
                                sr_info += f"\nSupport: Rs{gpt_decision['nearest_support']:.2f}"
                            if gpt_decision.get('nearest_resistance'):
                                sr_info += f"\nResistance: Rs{gpt_decision['nearest_resistance']:.2f}"
                            if gpt_decision.get('suggested_entry_price'):
                                sr_info += f"\nLIMIT Entry: Rs{gpt_decision['suggested_entry_price']:.2f}"
                            # v5.5: Show PDH/PDL when ChatGPT S/R not available
                            if not sr_info:
                                pdh = raw.get('prev_day_high', 0)
                                pdl = raw.get('prev_day_low', 0)
                                if pdh > 0:
                                    sr_info += f"\nPDH: Rs{pdh:.2f}"
                                if pdl > 0:
                                    sr_info += f"\nPDL: Rs{pdl:.2f}"
                            delivery_oi = ""
                            ds = gpt_decision.get('delivery_signal', 'UNKNOWN')
                            oi = gpt_decision.get('oi_signal', 'UNKNOWN')
                            if ds != 'UNKNOWN' or oi != 'UNKNOWN':
                                delivery_oi = f"\nDelivery: {ds} | OI: {oi}"
                            self.telegram.send_message(
                                f"GPT APPROVED ENTRY\n\n"
                                f"Symbol: {signal.symbol}\n"
                                f"Price: Rs{entry_price:.2f}\n"
                                f"Score: {signal.total_score:.0f}/100\n\n"
                                f"GPT Confidence: {gpt_decision.get('confidence', 0)}%\n"
                                f"Position: {gpt_decision.get('suggested_position_pct', 1.0)}x"
                                f"{sr_info}{delivery_oi}"
                            )
                    else:
                        logger.warning(f"GPT REJECTED: {signal.symbol}")
                        logger.warning(f"   Reason: {gpt_decision.get('reasoning', 'N/A')[:100]}")
                        logger.warning(f"   News: {gpt_decision.get('web_news', '')}")
                        logger.warning(f"   Pattern: {gpt_decision.get('web_pattern', '')}")

                        if self.telegram:
                            entry_price = raw.get('entry_price') or 0
                            web_news = gpt_decision.get('web_news', '')
                            web_pattern = gpt_decision.get('web_pattern', '')
                            self.telegram.send_message(
                                f"GPT REJECTED ENTRY\n\n"
                                f"Symbol: {signal.symbol}\n"
                                f"Price: Rs{entry_price:.2f}\n"
                                f"Score: {signal.total_score:.0f}/100\n\n"
                                f"Reason: {gpt_decision.get('reasoning', 'N/A')}\n"
                                f"News: {web_news}\n"
                                f"Analyst: {web_pattern}"
                            )
                
                except Exception as e:
                    logger.error(f"GPT approval failed for {signal.symbol}: {e}")
                    # v5.3.0 FIX: Default to REJECT on GPT failure (was auto-approve)
                    if getattr(self.config, 'GPT_FALLBACK_APPROVE_ENTRIES', False):
                        signal.raw_signal['gpt_decision'] = {'error': str(e), 'fallback': True}
                        signal.raw_signal['gpt_approved'] = True
                        signal.raw_signal['position_multiplier'] = getattr(self.config, 'GPT_FALLBACK_POSITION_MULTIPLIER', 0.5)
                        
                        # v5.3.1: Reserve capital for fallback approvals too
                        if self.phase2 and hasattr(self.phase2, 'capital_manager') and self.phase2.capital_manager:
                            entry_size = signal.raw_signal.get('entry_size', 0)
                            if entry_size > 0:
                                reserve_result = self.phase2.capital_manager.reserve_capital(
                                    symbol=signal.symbol, amount=entry_size
                                )
                                if reserve_result.get('reserved', False):
                                    signal.raw_signal['capital_reserved'] = True
                                    signal.raw_signal['reservation_id'] = reserve_result.get('reservation_id')
                        
                        approved_signals.append(signal)
                        logger.warning(f"⚠️ GPT failed, using fallback APPROVE for {signal.symbol} (config override)")
                    else:
                        logger.warning(f"❌ GPT failed, REJECTING {signal.symbol} (safe default)")
            
            return approved_signals
        
        else:
            logger.info(f"GPT Advisor disabled - auto-approving {len(tradeable)} signals")
            approved_no_gpt = []
            for signal in tradeable:
                signal.raw_signal['gpt_approved'] = False
                signal.raw_signal['position_multiplier'] = 1.0
                
                # v5.3.1: Reserve capital even when GPT disabled
                if self.phase2 and hasattr(self.phase2, 'capital_manager') and self.phase2.capital_manager:
                    entry_size = signal.raw_signal.get('entry_size', 0)
                    if entry_size > 0:
                        reserve_result = self.phase2.capital_manager.reserve_capital(
                            symbol=signal.symbol,
                            amount=entry_size
                        )
                        if reserve_result.get('reserved', False):
                            signal.raw_signal['capital_reserved'] = True
                            signal.raw_signal['reservation_id'] = reserve_result.get('reservation_id')
                
                approved_no_gpt.append(signal)
            return approved_no_gpt
    
    def _enrich_signals(self, raw_signals: List[dict]) -> List[dict]:
        """
        Add additional data to signals for better scoring.
        
        v2.1.0 AUDIT FIX: All getattr() calls now properly handle None values.
        
        Python gotcha: getattr(obj, 'attr', default) returns None if attr EXISTS with value None!
        Fix: Use safe_getattr() or getattr(..., None) or default pattern
        """
        enriched = []
        
        for signal in raw_signals:
            try:
                enriched_signal = signal.copy()
                symbol = signal.get('symbol') or ''
                
                # Get monitor for this stock
                monitor = self._get_monitor(symbol)
                
                if monitor:
                    # ═══════════════════════════════════════════════════════════════
                    # RSI CHANGE (momentum indicator)
                    # v2.1.0 FIX: Wrong attribute name was 'prev_rsi', correct is 'previous_rsi'
                    # ═══════════════════════════════════════════════════════════════
                    current_rsi = signal.get('rsi') or 50
                    
                    # FIX: Use correct attribute name 'previous_rsi'
                    prev_rsi = safe_getattr(monitor, 'previous_rsi', current_rsi)
                    enriched_signal['rsi_change'] = current_rsi - prev_rsi
                    
                    # ═══════════════════════════════════════════════════════════════
                    # PRICE CHANGE PERCENTAGE
                    # ═══════════════════════════════════════════════════════════════
                    ltp = signal.get('ltp') or signal.get('entry_price') or 0
                    
                    # FIX: safe_getattr handles None properly
                    prev_close = safe_getattr(monitor, 'prev_close', ltp)
                    if prev_close > 0:
                        enriched_signal['price_change_pct'] = (ltp - prev_close) / prev_close * 100
                    else:
                        enriched_signal['price_change_pct'] = 0
                    
                    # ═══════════════════════════════════════════════════════════════
                    # ATR PERCENTAGE
                    # ═══════════════════════════════════════════════════════════════
                    atr = safe_getattr(monitor, 'atr', 0)
                    if ltp > 0 and atr > 0:
                        enriched_signal['atr_pct'] = atr / ltp * 100
                    else:
                        enriched_signal['atr_pct'] = 0
                    enriched_signal['atr'] = atr
                    
                    # ═══════════════════════════════════════════════════════════════
                    # SUPPORT DISTANCE
                    # ═══════════════════════════════════════════════════════════════
                    support = safe_getattr(monitor, 'support_level', 0)
                    if support > 0 and ltp > 0:
                        enriched_signal['support_distance_pct'] = (ltp - support) / ltp * 100
                    else:
                        enriched_signal['support_distance_pct'] = 10  # Default far from support
                    
                    # ═══════════════════════════════════════════════════════════════
                    # RECOVERY PERCENTAGE (V-pattern)
                    # ═══════════════════════════════════════════════════════════════
                    day_high = signal.get('high') or ltp
                    day_low = signal.get('low') or ltp
                    if day_high > day_low:
                        enriched_signal['recovery_percentage'] = (ltp - day_low) / (day_high - day_low) * 100
                    else:
                        enriched_signal['recovery_percentage'] = 50  # Mid-point default
                    
                    # ═══════════════════════════════════════════════════════════════
                    # EMA21 SLOPE
                    # ═══════════════════════════════════════════════════════════════
                    ema21 = safe_getattr(monitor, 'ema21', 0)
                    ema21_prev = safe_getattr(monitor, 'ema21_prev', ema21)
                    if ema21_prev > 0:
                        enriched_signal['ema21_slope'] = (ema21 - ema21_prev) / ema21_prev * 100
                    else:
                        enriched_signal['ema21_slope'] = 0
                    
                    # ═══════════════════════════════════════════════════════════════
                    # UPTREND CHECK (price > MA20)
                    # ═══════════════════════════════════════════════════════════════
                    ma20 = safe_getattr(monitor, 'ma20', 0)
                    enriched_signal['uptrend'] = ltp > ma20 if ma20 > 0 else False
                    enriched_signal['ma20'] = ma20
                    
                    # ═══════════════════════════════════════════════════════════════
                    # EMA RELATIONSHIP (ema21 > ema50)
                    # ═══════════════════════════════════════════════════════════════
                    ema50 = safe_getattr(monitor, 'ema50', 0)
                    enriched_signal['ema21_above_ema50'] = ema21 > ema50 if ema50 > 0 else False
                    
                    # ═══════════════════════════════════════════════════════════════
                    # VOLUME RATIO
                    # v2.1.0 FIX: This was the original crash point!
                    # ═══════════════════════════════════════════════════════════════
                    volume_ratio = safe_getattr(monitor, 'volume_ratio', 1.0)
                    enriched_signal['volume_ratio'] = volume_ratio
                    
                    if volume_ratio == 1.0:
                        # Check if it was actually calculated or just default
                        raw_value = getattr(monitor, 'volume_ratio', None)
                        if raw_value is None:
                            logger.warning(f"   [{symbol}] volume_ratio is None, using default 1.0")
                    
                    # ═══════════════════════════════════════════════════════════════
                    # KALMAN FILTER PREDICTIONS
                    # ═══════════════════════════════════════════════════════════════
                    kalman_prediction = {}
                    if hasattr(self.phase2, 'kalman_enabled') and self.phase2.kalman_enabled:
                        if hasattr(self.phase2, 'kalman_filters') and symbol in self.phase2.kalman_filters:
                            try:
                                kf = self.phase2.kalman_filters[symbol]
                                kalman_state = kf.get_state_dict()
                                
                                current_price = ltp
                                predicted_price = kalman_state.get('prediction_15min') or current_price
                                expected_move_pct = ((predicted_price - current_price) / current_price) * 100 if current_price > 0 else 0
                                
                                trend = classify_kalman_trend(kalman_state) if CHATGPT_AVAILABLE else 'UNKNOWN'
                                
                                uncertainty = kalman_state.get('uncertainty') or 1.0
                                confidence = max(0, min(100, 100 - (uncertainty * 10)))
                                
                                kalman_prediction = {
                                    'price_15min': float(predicted_price),
                                    'velocity': float(kalman_state.get('velocity') or 0),
                                    'acceleration': float(kalman_state.get('acceleration') or 0),
                                    'expected_move_pct': float(expected_move_pct),
                                    'uncertainty': float(uncertainty),
                                    'confidence': float(confidence),
                                    'trend': trend
                                }
                                
                                logger.info(f"Kalman Prediction for {symbol}:")
                                logger.info(f"   15-min Price: Rs{predicted_price:.2f} ({expected_move_pct:+.2f}%)")
                                logger.info(f"   Trend: {trend}")
                                
                            except Exception as e:
                                logger.error(f"Failed to extract Kalman predictions: {e}")
                                kalman_prediction = {'error': str(e), 'available': False}
                    
                    enriched_signal['kalman_prediction'] = kalman_prediction
                    
                    # ═══════════════════════════════════════════════════════════════
                    # RSI HISTORY (for ChatGPT context)
                    # ═══════════════════════════════════════════════════════════════
                    rsi_history = safe_getattr(monitor, 'rsi_values_only', [])
                    if rsi_history:
                        enriched_signal['rsi_history'] = rsi_history[-10:]  # Last 10 values
                    
                    # ═══════════════════════════════════════════════════════════════
                    # ADX VALUE
                    # ═══════════════════════════════════════════════════════════════
                    adx_value = safe_getattr(monitor, 'adx_value', None)
                    enriched_signal['adx_value'] = adx_value
                    
                    # ═══════════════════════════════════════════════════════════════
                    # VOLUME SPIKE AT REVERSAL
                    # ═══════════════════════════════════════════════════════════════
                    volume_spike = safe_getattr(monitor, 'volume_spike_at_reversal', None)
                    enriched_signal['volume_spike_at_reversal'] = volume_spike
                    
                    # ═══════════════════════════════════════════════════════════════
                    # VWAP
                    # ═══════════════════════════════════════════════════════════════
                    vwap = safe_getattr(monitor, 'vwap', 0)
                    enriched_signal['vwap'] = vwap
                
                enriched.append(enriched_signal)
                
            except Exception as e:
                logger.warning(f"Error enriching signal {signal.get('symbol', '?')}: {e}")
                import traceback
                logger.debug(traceback.format_exc())
                enriched.append(signal)  # Use original if enrichment fails
        
        return enriched
    
    def _rank_signals(self, signals: List[dict]) -> List[dict]:
        """
        v5.3.0: Rank signals by composite score (like Phase 5 Step 4).
        
        Score = recovery_factor × volume_factor × adx_factor × trend_factor
        Sort descending — best candidates processed first.
        """
        if len(signals) <= 1:
            return signals
        
        for signal in signals:
            try:
                # Recovery factor (0 to 2.0)
                recovery_pct = signal.get('recovery_percentage', 50)
                if recovery_pct >= 60:
                    recovery_factor = 1.5 + (min(recovery_pct, 100) - 60) / 80
                elif recovery_pct >= 40:
                    recovery_factor = 1.0
                else:
                    recovery_factor = 0.5
                
                # Volume factor (0.5 to 2.0)
                volume_ratio = signal.get('volume_ratio', 1.0)
                volume_factor = min(2.0, max(0.5, volume_ratio))
                
                # Trend factor (0.5 to 1.5)
                uptrend = signal.get('uptrend', False)
                ema_above = signal.get('ema21_above_ema50', False)
                trend_factor = 1.0
                if uptrend and ema_above:
                    trend_factor = 1.5
                elif uptrend:
                    trend_factor = 1.2
                elif not uptrend:
                    trend_factor = 0.7
                
                # ADX factor (0.5 to 1.5) — v5.3.0 FIX: was missing from ranking
                adx = signal.get('adx_value')
                adx_factor = 1.0
                if adx is not None:
                    if 20 <= adx <= 35:
                        adx_factor = 1.3  # Sweet spot for V-recovery
                    elif 15 <= adx < 20:
                        adx_factor = 1.0  # Low but acceptable
                    elif 35 < adx <= 45:
                        adx_factor = 0.8  # Strong trend, risky for mean reversion
                    else:
                        adx_factor = 0.5  # Too low (choppy) or too high (extreme)
                
                signal['_rank_score'] = round(recovery_factor * volume_factor * trend_factor * adx_factor, 3)
                
            except Exception:
                signal['_rank_score'] = 1.0
        
        # Sort descending by rank score
        signals.sort(key=lambda s: s.get('_rank_score', 0), reverse=True)
        
        logger.info("📊 Signal Ranking:")
        for i, s in enumerate(signals[:5]):
            logger.info(f"   {i+1}. {s.get('symbol')}: rank_score={s.get('_rank_score', 0):.3f}")
        
        return signals
    
    def _get_monitor(self, symbol: str):
        """Get StockMonitor for a symbol from Phase 2"""
        if hasattr(self.phase2, 'monitors'):
            for monitor in self.phase2.monitors:
                if monitor.symbol == symbol:
                    return monitor
        return None
    
    def convert_to_phase3_signal(self, intelligent_signal: IntelligentSignal) -> dict:
        """Convert IntelligentSignal to format expected by Phase 3."""
        raw = intelligent_signal.raw_signal.copy()
        
        # Add intelligent enhancements
        raw['intelligent_score'] = intelligent_signal.total_score
        raw['signal_strength'] = intelligent_signal.signal_strength.value
        raw['recommended_capital'] = intelligent_signal.recommended_capital
        
        # Use GPT position multiplier if available
        if 'position_multiplier' not in raw:
            raw['position_multiplier'] = intelligent_signal.recommended_position_pct
        
        # Adaptive risk parameters
        raw['suggested_stop_loss_pct'] = intelligent_signal.suggested_stop_loss_pct
        raw['suggested_target_pct'] = intelligent_signal.suggested_target_pct
        
        # Prediction info
        raw['predicted_direction'] = intelligent_signal.predicted_direction
        raw['prediction_confidence'] = intelligent_signal.prediction_confidence
        
        # Market context
        raw['market_regime'] = intelligent_signal.market_regime.value
        raw['trade_reason'] = intelligent_signal.trade_reason
        raw['risk_notes'] = intelligent_signal.risk_notes
        
        return raw
    
    def get_market_regime(self) -> MarketRegime:
        """Get current market regime from Intelligent Engine"""
        if self.intelligent_engine.current_market_context:
            return self.intelligent_engine.current_market_context.regime
        
        context = self.intelligent_engine.detect_market_regime()
        return context.regime


class IntelligentSignalProcessor:
    """Helper class to process intelligent signals for Phase 3."""
    
    @staticmethod
    def filter_tradeable(signals: List[IntelligentSignal], 
                         min_score: float = 45) -> List[IntelligentSignal]:
        """Filter to signals with score >= min_score"""
        return [s for s in signals if s.total_score >= min_score]
    
    @staticmethod
    def sort_by_score(signals: List[IntelligentSignal]) -> List[IntelligentSignal]:
        """Sort signals by score (highest first)"""
        return sorted(signals, key=lambda x: x.total_score, reverse=True)
    
    @staticmethod
    def get_best_signal(signals: List[IntelligentSignal]) -> Optional[IntelligentSignal]:
        """Get the highest scoring signal"""
        if not signals:
            return None
        sorted_signals = IntelligentSignalProcessor.sort_by_score(signals)
        return sorted_signals[0] if sorted_signals else None
    
    @staticmethod
    def should_trade_in_mixed_market(signal: IntelligentSignal, config) -> bool:
        """Check if we should trade this signal in mixed market conditions."""
        if not getattr(config, 'ENABLE_MIXED_MARKET_TRADING', True):
            return signal.signal_strength == SignalStrength.STRONG
        
        min_score = getattr(config, 'MIXED_MARKET_MIN_SCORE', 45)
        return signal.total_score >= min_score
    
    @staticmethod
    def calculate_adjusted_quantity(signal: IntelligentSignal, 
                                     base_capital: float,
                                     stock_price: float) -> int:
        """Calculate position size based on intelligent signal"""
        adjusted_capital = base_capital * signal.recommended_position_pct
        quantity = int(adjusted_capital / stock_price) if stock_price > 0 else 1
        return max(1, quantity)
    
    @staticmethod
    def format_signal_summary(signal: IntelligentSignal) -> str:
        """Format signal for logging/notification"""
        return (
            f"{signal.symbol}: {signal.total_score:.0f}/100 ({signal.signal_strength.value})\n"
            f"  T={signal.technical_score:.0f} M={signal.momentum_score:.0f} "
            f"V={signal.volume_score:.0f} S={signal.support_score:.0f} "
            f"N={signal.nifty_correlation_score:.0f}\n"
            f"  Predict: {signal.predicted_direction} ({signal.prediction_confidence:.0f}%)\n"
            f"  Position: {signal.recommended_position_pct*100:.0f}% "
            f"(Rs{signal.recommended_capital:,.0f})\n"
            f"  Reason: {signal.trade_reason}"
        )
