"""
INTELLIGENT DECISION ENGINE v1.4.1 - VWAP time filter - CRITICAL FIXES
═══════════════════════════════════════════════════════════════════════════════

🔴 v1.4.1 - VWAP time filter CRITICAL FIXES (2026-02-05):
───────────────────────────────────────────────
1. ✅ FIXED: All signal.get() calls now handle None values properly
   - Using 'or default' pattern to prevent TypeError crashes
   - Added warning logs when using fallback defaults

2. ✅ FIXED: sentiment_score field name corrected
   - Was: signal.get('sentiment_score', 0) - wrong field!
   - Now: Extracts from sentiment dict properly

3. ✅ ADDED: Defensive None checks throughout scoring
   - Every comparison now safe from None values
   - Logging when fallback values used

Previous versions:
- v1.2.0: VWAP institutional flow filter
- v1.1.0: Lower thresholds, starvation prevention
- v1.0.0: Initial intelligent scoring

Author: Trading System v1.3 (Audit Fix)
Date: 2026-02-03
"""

import logging
import numpy as np
from datetime import datetime, timedelta, time
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger('IntelligentEngine')


# ═══════════════════════════════════════════════════════════════════════════════
# ENUMS AND DATA CLASSES
# ═══════════════════════════════════════════════════════════════════════════════

class MarketRegime(Enum):
    TRENDING_UP = "TRENDING_UP"
    TRENDING_DOWN = "TRENDING_DOWN"
    RANGE_BOUND = "RANGE_BOUND"
    HIGH_VOLATILITY = "HIGH_VOLATILITY"
    LOW_VOLATILITY = "LOW_VOLATILITY"
    MIXED = "MIXED"


class SignalStrength(Enum):
    STRONG = "STRONG"
    MODERATE = "MODERATE"
    WEAK = "WEAK"
    SKIP = "SKIP"


@dataclass
class MarketContext:
    regime: MarketRegime
    nifty_trend: str
    nifty_change_pct: float
    nifty_vwap_position: str
    volatility_level: str
    adx_value: float
    market_breadth: float
    timestamp: datetime


@dataclass
class IntelligentSignal:
    symbol: str
    raw_signal: dict
    
    # Scoring
    total_score: float
    signal_strength: SignalStrength
    
    # Component scores
    technical_score: float
    momentum_score: float
    volume_score: float
    support_score: float
    sentiment_score: float
    nifty_correlation_score: float
    
    # Prediction
    predicted_direction: str
    prediction_confidence: float
    expected_move_pct: float
    
    # Position sizing
    recommended_position_pct: float
    recommended_capital: float
    
    # Risk parameters
    suggested_stop_loss_pct: float
    suggested_target_pct: float
    
    # Metadata
    market_regime: MarketRegime
    trade_reason: str
    risk_notes: List[str]


# ═══════════════════════════════════════════════════════════════════════════════
# INTELLIGENT DECISION ENGINE v1.3
# ═══════════════════════════════════════════════════════════════════════════════

class IntelligentDecisionEngine:
    """
    🧠 The Brain of the Trading System v1.3
    
    v1.3.0: AUDIT FIX - All None handling bugs fixed
    """
    
    def __init__(self, kite, config, telegram=None, starvation_prevention=None):
        self.kite = kite
        self.config = config
        self.telegram = telegram
        self.starvation_prevention = starvation_prevention
        
        # ═══════════════════════════════════════════════════════════════
        # SCORING WEIGHTS
        # ═══════════════════════════════════════════════════════════════
        self.SCORING_WEIGHTS = {
            'technical': 25,
            'momentum': 20,
            'volume': 15,
            'support': 15,
            'sentiment': 10,
            'nifty_correlation': 15
        }
        
        # ═══════════════════════════════════════════════════════════════
        # SIGNAL THRESHOLDS (v5.2.1: Read from config for easy tuning)
        # ═══════════════════════════════════════════════════════════════
        self.THRESHOLDS = {
            'strong': getattr(config, 'SCORE_THRESHOLD_STRONG', 80),
            'moderate': getattr(config, 'SCORE_THRESHOLD_MODERATE', 70),
            'weak': getattr(config, 'SCORE_THRESHOLD_WEAK', 60),
            'skip': getattr(config, 'SCORE_THRESHOLD_SKIP', 60)
        }
        # MARKER mode: a 1-share radar position only needs the Phase 2 entry minimum
        if getattr(config, 'MARKER_MODE_ENABLED', False) and getattr(config, 'MARKER_BUY_ON_CONFIRMATION', False):
            self.THRESHOLDS['skip'] = min(self.THRESHOLDS['skip'], getattr(config, 'PH2_SCORE_ENTRY_MIN', 45))
        logger.info(f"   📊 Score Thresholds: Strong≥{self.THRESHOLDS['strong']} | Moderate≥{self.THRESHOLDS['moderate']} | Weak≥{self.THRESHOLDS['weak']} | Skip<{self.THRESHOLDS['skip']}")
        
        # ═══════════════════════════════════════════════════════════════
        # REGIME-SPECIFIC PARAMETERS
        # ═══════════════════════════════════════════════════════════════
        self.REGIME_PARAMS = {
            MarketRegime.TRENDING_UP: {
                'rsi_entry_max': 45,
                'target_pct': 3.0,
                'stop_loss_pct': 2.0,
                'position_mult': 1.0,
                'strategy': 'MOMENTUM'
            },
            MarketRegime.TRENDING_DOWN: {
                'rsi_entry_max': 30,
                'target_pct': 2.0,
                'stop_loss_pct': 1.5,
                'position_mult': 0.6,
                'strategy': 'COUNTER_TREND'
            },
            MarketRegime.RANGE_BOUND: {
                'rsi_entry_max': 35,
                'target_pct': 1.5,
                'stop_loss_pct': 1.0,
                'position_mult': 0.8,
                'strategy': 'MEAN_REVERSION'
            },
            MarketRegime.HIGH_VOLATILITY: {
                'rsi_entry_max': 30,
                'target_pct': 2.5,
                'stop_loss_pct': 2.0,
                'position_mult': 0.6,
                'strategy': 'QUICK_SCALP'
            },
            MarketRegime.MIXED: {
                'rsi_entry_max': 38,
                'target_pct': 2.0,
                'stop_loss_pct': 1.5,
                'position_mult': 0.7,
                'strategy': 'ADAPTIVE'
            }
        }
        
        # Cache
        self.nifty_cache = {'data': None, 'timestamp': None, 'cache_duration': 60}
        self.current_market_context: Optional[MarketContext] = None
        
        logger.info("=" * 80)
        logger.info("🧠 INTELLIGENT DECISION ENGINE v1.4.1 - VWAP time filter - CRITICAL FIXES")
        logger.info("=" * 80)
        logger.info("")
        logger.info("v1.3.0 Audit Fixes:")
        logger.info("  ✅ All signal.get() calls now handle None properly")
        logger.info("  ✅ Fixed sentiment_score field extraction")
        logger.info("  ✅ Added defensive None checks throughout")
        logger.info("  ✅ Warning logs when using fallback defaults")
        logger.info("")
    
    def set_starvation_prevention(self, starvation_prevention):
        """Set the starvation prevention module"""
        self.starvation_prevention = starvation_prevention
        logger.info("✅ Trade starvation prevention linked to Intelligent Engine")
    
    def detect_market_regime(self, nifty_data: dict = None) -> MarketContext:
        """Detect current market regime"""
        logger.info("🔍 Detecting market regime...")
        
        try:
            if nifty_data is None:
                nifty_data = self._fetch_nifty_data()
            
            if not nifty_data:
                return self._default_market_context()
            
            # v1.3.0 FIX: Safe extraction with 'or' pattern
            ltp = nifty_data.get('ltp') or 0
            vwap = nifty_data.get('vwap') or ltp
            change_pct = nifty_data.get('change_pct') or 0
            adx = nifty_data.get('adx') or 20
            
            # Safe division for ATR ratio
            avg_atr = nifty_data.get('avg_atr') or 1
            atr = nifty_data.get('atr') or 1
            atr_ratio = atr / avg_atr if avg_atr > 0 else 1
            
            vwap_position = "ABOVE" if ltp > vwap else "BELOW"
            
            if change_pct > 0.3:
                nifty_trend = "UP"
            elif change_pct < -0.3:
                nifty_trend = "DOWN"
            else:
                nifty_trend = "NEUTRAL"
            
            # Determine volatility
            if atr_ratio > 1.5:
                volatility = "HIGH"
            elif atr_ratio < 0.7:
                volatility = "LOW"
            else:
                volatility = "MEDIUM"
            
            # Determine regime
            if adx > 25:
                if nifty_trend == "UP" or (vwap_position == "ABOVE" and change_pct > 0):
                    regime = MarketRegime.TRENDING_UP
                elif nifty_trend == "DOWN" or (vwap_position == "BELOW" and change_pct < 0):
                    regime = MarketRegime.TRENDING_DOWN
                else:
                    regime = MarketRegime.MIXED
            elif atr_ratio > 1.5:
                regime = MarketRegime.HIGH_VOLATILITY
            elif atr_ratio < 0.7:
                regime = MarketRegime.LOW_VOLATILITY
            elif adx < 20:
                regime = MarketRegime.RANGE_BOUND
            else:
                regime = MarketRegime.MIXED
            
            ctx = MarketContext(
                regime=regime,
                nifty_trend=nifty_trend,
                nifty_change_pct=change_pct,
                nifty_vwap_position=vwap_position,
                volatility_level=volatility,
                adx_value=adx,
                market_breadth=50,
                timestamp=datetime.now()
            )
            
            self.current_market_context = ctx
            
            logger.info(f"   📊 Regime: {regime.value}")
            logger.info(f"   📈 NIFTY: {nifty_trend} ({change_pct:+.2f}%)")
            logger.info(f"   📍 VWAP Position: {vwap_position}")
            
            return ctx
            
        except Exception as e:
            logger.error(f"Error detecting market regime: {e}")
            return self._default_market_context()
    
    def _fetch_nifty_data(self) -> dict:
        """Fetch NIFTY data with caching"""
        try:
            # Check cache
            if self.nifty_cache['data'] and self.nifty_cache['timestamp']:
                age = (datetime.now() - self.nifty_cache['timestamp']).total_seconds()
                if age < self.nifty_cache['cache_duration']:
                    return self.nifty_cache['data']
            
            # Fetch fresh data
            quote = self.kite.quote("NSE:NIFTY 50")
            if not quote or "NSE:NIFTY 50" not in quote:
                return {}
            
            nifty = quote["NSE:NIFTY 50"]
            ltp = nifty.get('last_price') or 0
            open_price = nifty.get('ohlc', {}).get('open') or ltp
            high = nifty.get('ohlc', {}).get('high') or ltp
            low = nifty.get('ohlc', {}).get('low') or ltp
            
            change_pct = ((ltp - open_price) / open_price * 100) if open_price else 0
            vwap = (high + low + ltp) / 3 if (high and low and ltp) else ltp
            
            data = {
                'ltp': ltp,
                'open': open_price,
                'high': high,
                'low': low,
                'change_pct': change_pct,
                'vwap': vwap,
                'adx': 20,
                'atr': 1,
                'avg_atr': 1
            }
            
            # Update cache
            self.nifty_cache['data'] = data
            self.nifty_cache['timestamp'] = datetime.now()
            
            return data
            
        except Exception as e:
            logger.error(f"Error fetching NIFTY data: {e}")
            return {}
    
    def _default_market_context(self) -> MarketContext:
        """Default market context when detection fails"""
        logger.warning("   ⚠️ Using default market context")
        return MarketContext(
            regime=MarketRegime.MIXED, nifty_trend="NEUTRAL",
            nifty_change_pct=0, nifty_vwap_position="NEUTRAL",
            volatility_level="MEDIUM", adx_value=20,
            market_breadth=50, timestamp=datetime.now()
        )
    
    def calculate_signal_score(self, signal: dict, market_context: MarketContext) -> IntelligentSignal:
        """
        Calculate comprehensive score with None-safe value extraction.
        
        v1.3.0 FIX: All signal.get() calls now use 'or default' pattern
        to prevent TypeError when values are None.
        """
        
        symbol = signal.get('symbol')
        if not symbol:
            logger.critical(f"🔴 CRITICAL BUG: Symbol missing from signal!")
            logger.critical(f"   Available keys: {list(signal.keys())}")
            logger.critical(f"   Signal data: {signal}")
            symbol = 'UNKNOWN'
        logger.info(f"📊 Scoring: {symbol}")
        
        scores = {k: 0 for k in self.SCORING_WEIGHTS}
        risk_notes = []
        
        # ═══════════════════════════════════════════════════════════════
        # 1. TECHNICAL SCORE (25 points)
        # ═══════════════════════════════════════════════════════════════
        
        # v1.3.0 FIX: Use 'or' pattern to handle None
        ema_slope = signal.get('ema21_slope')
        if ema_slope is None:
            ema_slope = 0
        
        if ema_slope > 0.5:
            scores['technical'] += 12
        elif ema_slope > 0:
            scores['technical'] += 9
        elif ema_slope > -0.2:
            scores['technical'] += 6
        elif ema_slope > -0.5:
            scores['technical'] += 3
        
        # v1.3.0 FIX: Safe price and MA20 extraction
        price = signal.get('ltp') or signal.get('entry_price') or 0
        ma20 = signal.get('ma20')
        if ma20 is None or ma20 == 0:
            ma20 = price  # Fallback to price
        
        # Safe division
        if ma20 and ma20 > 0 and price > 0:
            ma20_dist = (price - ma20) / ma20 * 100
        else:
            ma20_dist = 0
        
        if ma20_dist > 0:
            scores['technical'] += 8
        elif ma20_dist > -1.5:
            scores['technical'] += 6
        elif ma20_dist > -3:
            scores['technical'] += 4
        elif ma20_dist > -5:
            scores['technical'] += 2
        
        # v1.3.0 FIX: Safe boolean extraction
        if signal.get('uptrend'):
            scores['technical'] += 5
        elif signal.get('ema21_above_ema50'):
            scores['technical'] += 3
        
        # VWAP Filter (0-20 points)
        vwap_score = self._calculate_vwap_score(signal)
        scores['technical'] += vwap_score
        
        # v5.2.1 FIX: Cap technical at max weight (25) — VWAP was causing overflow to 45
        scores['technical'] = min(25, scores['technical'])
        
        # ═══════════════════════════════════════════════════════════════
        # 2. MOMENTUM SCORE (20 points)
        # ═══════════════════════════════════════════════════════════════
        
        # v1.3.0 FIX: Safe RSI extraction
        rsi = signal.get('rsi')
        if rsi is None:
            rsi = 50
        
        rsi_change = signal.get('rsi_change')
        if rsi_change is None:
            rsi_change = 0
        
        # v5.3.1 CALIBRATED RSI SCORING (from real 15min chart analysis):
        # AUROPHARMA: RSI 25→76 = +5.4%, BAJFINANCE: RSI 32→77 = +10.6%
        # TORNTPOWER: RSI 32→64 = +10.8%
        # RSI 40-70 on 15min candles = CLIMB PHASE (best price momentum)
        # Old scoring gave 0 points to RSI > 50 — killed profitable entries
        
        if 20 <= rsi <= 35:
            scores['momentum'] += 10   # Ramp zone — ideal V-recovery entry
        elif 35 < rsi <= 50:
            scores['momentum'] += 9    # Transition → climb starting
        elif 50 < rsi <= 65:
            scores['momentum'] += 7    # CLIMB phase — strong momentum
        elif 65 < rsi <= 80:
            scores['momentum'] += 5    # Late climb — still valid
        elif 15 <= rsi < 20:
            scores['momentum'] += 8    # Deep oversold
        elif rsi < 15:
            scores['momentum'] += 5
            risk_notes.append("RSI extremely low - potential capitulation")
        elif rsi > 80:
            scores['momentum'] += 2    # Caution zone
        
        # RSI recovering
        if rsi_change > 2:
            scores['momentum'] += 10
        elif rsi_change > 0:
            scores['momentum'] += 7
        elif rsi_change > -1:
            scores['momentum'] += 4
        elif rsi_change > -2:
            scores['momentum'] += 2
        
        # ═══════════════════════════════════════════════════════════════
        # v5.3.1 RECALIBRATED MOMENTUM GATE
        # Only penalize when RSI > 80 with zero momentum (true exhaustion)
        # RSI 55-80 with zero change = consolidation, not exhaustion
        # ═══════════════════════════════════════════════════════════════
        if scores['momentum'] == 0 and rsi > 80:
            penalty = -10
            level = "EXHAUSTED"
            risk_notes.append(f"⚠️ MOMENTUM GATE ({level}): RSI {rsi:.0f} with zero momentum")
            scores['momentum'] = penalty
            logger.warning(f"   [{symbol}] 🚫 Momentum gate ({level}): RSI {rsi:.1f} > 80 with 0 momentum → {penalty} penalty")
        
        # ═══════════════════════════════════════════════════════════════
        # 3. VOLUME SCORE (15 points)
        # ═══════════════════════════════════════════════════════════════
        
        # v1.3.0 FIX: This was the CRASH point - volume_ratio was None!
        volume_ratio = signal.get('volume_ratio')
        if volume_ratio is None:
            volume_ratio = 1.0
            logger.warning(f"   [{symbol}] ⚠️ volume_ratio is None, using default 1.0")
        
        if volume_ratio >= 2.0:
            scores['volume'] += 15
        elif volume_ratio >= 1.5:
            scores['volume'] += 12
        elif volume_ratio >= 1.2:
            scores['volume'] += 9
        elif volume_ratio >= 1.0:
            scores['volume'] += 6
        elif volume_ratio >= 0.8:
            scores['volume'] += 3
        else:
            risk_notes.append("Low volume")
        
        # ═══════════════════════════════════════════════════════════════
        # 4. SUPPORT/V-RECOVERY SCORE (15 points)
        # ═══════════════════════════════════════════════════════════════
        
        # v1.3.0 FIX: Safe support distance extraction
        support_dist = signal.get('support_distance_pct')
        if support_dist is None:
            support_dist = 10  # Default to 10% (no score)
        
        if support_dist <= 1:
            scores['support'] += 8
        elif support_dist <= 2:
            scores['support'] += 6
        elif support_dist <= 3:
            scores['support'] += 4
        elif support_dist <= 5:
            scores['support'] += 2
        
        # v1.3.0 FIX: Safe recovery percentage extraction
        recovery_pct = signal.get('recovery_percentage')
        if recovery_pct is None:
            recovery_pct = 0
        
        if 50 <= recovery_pct <= 75:
            scores['support'] += 7
        elif 40 <= recovery_pct <= 85:
            scores['support'] += 5
        elif recovery_pct > 30:
            scores['support'] += 3
        elif recovery_pct > 20:
            scores['support'] += 1
        
        # v5.3.1: Ramp detector confirmation bonus
        # If ramp detected, the V-recovery has Kalman+MA+RisingLows backing
        if signal.get('ramp_detected'):
            ramp_lows = signal.get('ramp_rising_lows', 0)
            ramp_vel = signal.get('ramp_kalman_velocity', 0)
            if ramp_lows >= 3 and ramp_vel > 0.3:
                scores['support'] += 4  # Strong ramp confirmation
            elif ramp_lows >= 2:
                scores['support'] += 2  # Moderate ramp
            else:
                scores['support'] += 1  # Basic ramp
        
        scores['support'] = min(15, scores['support'])
        
        # ═══════════════════════════════════════════════════════════════
        # 5. SENTIMENT SCORE (10 points)
        # ═══════════════════════════════════════════════════════════════
        
        # v1.3.0 FIX: sentiment is a dict with 'score' inside, not 'sentiment_score'!
        # OLD (WRONG): sentiment = signal.get('sentiment_score', 0)
        # NEW (CORRECT): Extract from sentiment dict
        sentiment_data = signal.get('sentiment')
        sentiment = 0
        
        if isinstance(sentiment_data, dict):
            sentiment = sentiment_data.get('score') or 0
        elif sentiment_data is not None:
            # Maybe it's already a number
            try:
                sentiment = float(sentiment_data)
            except (TypeError, ValueError):
                sentiment = 0
        
        # Also try direct sentiment_score field as fallback
        if sentiment == 0:
            direct_score = signal.get('sentiment_score')
            if direct_score is not None:
                sentiment = direct_score
        
        news_count = signal.get('news_count')
        if news_count is None:
            news_count = 0
        
        if sentiment > 0.3:
            scores['sentiment'] += 10
        elif sentiment > 0:
            scores['sentiment'] += 8
        elif sentiment > -0.2:
            scores['sentiment'] += 6
        elif sentiment > -0.4:
            scores['sentiment'] += 3
        else:
            risk_notes.append("Negative sentiment")
        
        if news_count == 0 and scores['sentiment'] == 0:
            scores['sentiment'] = 6  # No news AND no FinBERT data = neutral
        
        # ═══════════════════════════════════════════════════════════════
        # 6. NIFTY CORRELATION (15 points)
        # ═══════════════════════════════════════════════════════════════
        
        scores['nifty_correlation'] = self._calculate_nifty_score(signal, market_context)
        
        # ═══════════════════════════════════════════════════════════════
        # CALCULATE TOTAL SCORE
        # ═══════════════════════════════════════════════════════════════
        
        total_score = sum(scores.values())
        
        # ═══════════════════════════════════════════════════════════════
        # BONUS POINTS
        # ═══════════════════════════════════════════════════════════════
        
        strong_factors = sum(1 for s in scores.values() if s >= 10)
        if strong_factors >= 3:
            total_score += 5
            logger.info(f"   +5 bonus: {strong_factors} strong factors")
        
        if rsi < 35 and market_context.nifty_trend == "UP":
            total_score += 3
            logger.info(f"   +3 bonus: RSI oversold + NIFTY UP")
        
        # ═══════════════════════════════════════════════════════════════
        # APPLY STARVATION PREVENTION (if enabled)
        # v5.1.1 FIX: Enforce hard floor so starvation can NEVER lower
        # threshold below STARVATION_MINIMUM_THRESHOLD. Previously,
        # position-limit blocks were counted as starvation,
        # lowering quality standards from 45→35, letting weak trades through.
        # ═══════════════════════════════════════════════════════════════
        
        skip_threshold = self.THRESHOLDS['skip']
        min_floor = getattr(self.config, 'STARVATION_MINIMUM_THRESHOLD', 45)
        
        if self.starvation_prevention:
            adjusted_threshold, reason = self.starvation_prevention.get_adjusted_threshold(skip_threshold)
            # HARD FLOOR: Never allow threshold below minimum
            if adjusted_threshold < min_floor:
                logger.warning(f"🚨 Starvation prevention BLOCKED: wanted {adjusted_threshold} but floor is {min_floor}")
                adjusted_threshold = min_floor
            if adjusted_threshold < skip_threshold:
                skip_threshold = adjusted_threshold
                logger.warning(f"🚨 Starvation prevention: {reason}")
        
        # ═══════════════════════════════════════════════════════════════
        # DETERMINE SIGNAL STRENGTH
        # ═══════════════════════════════════════════════════════════════
        
        if total_score >= self.THRESHOLDS['strong']:
            signal_strength = SignalStrength.STRONG
        elif total_score >= self.THRESHOLDS['moderate']:
            signal_strength = SignalStrength.MODERATE
        elif total_score >= skip_threshold:
            signal_strength = SignalStrength.WEAK
        else:
            signal_strength = SignalStrength.SKIP
        
        # ═══════════════════════════════════════════════════════════════
        # PREDICTION
        # ═══════════════════════════════════════════════════════════════
        
        prediction = self._predict_move(signal, market_context, scores)
        
        # ═══════════════════════════════════════════════════════════════
        # POSITION SIZING
        # ═══════════════════════════════════════════════════════════════
        
        regime_params = self.REGIME_PARAMS.get(market_context.regime, self.REGIME_PARAMS[MarketRegime.MIXED])
        position_sizing = self._calculate_position_size(total_score, signal_strength, regime_params)
        
        # ═══════════════════════════════════════════════════════════════
        # BUILD SIGNAL
        # ═══════════════════════════════════════════════════════════════
        
        trade_reason = self._build_reason(signal, scores, market_context, prediction)
        
        int_signal = IntelligentSignal(
            symbol=symbol,
            raw_signal=signal,
            total_score=total_score,
            signal_strength=signal_strength,
            technical_score=scores['technical'],
            momentum_score=scores['momentum'],
            volume_score=scores['volume'],
            support_score=scores['support'],
            sentiment_score=scores['sentiment'],
            nifty_correlation_score=scores['nifty_correlation'],
            predicted_direction=prediction['direction'],
            prediction_confidence=prediction['confidence'],
            expected_move_pct=prediction['expected_move'],
            recommended_position_pct=position_sizing['position_pct'],
            recommended_capital=position_sizing['capital'],
            suggested_stop_loss_pct=regime_params['stop_loss_pct'],
            suggested_target_pct=regime_params['target_pct'],
            market_regime=market_context.regime,
            trade_reason=trade_reason,
            risk_notes=risk_notes
        )
        
        # Log score breakdown
        # v1.4.1 - VWAP time filter: Clear score breakdown showing base + bonuses
        base_score = sum(scores.values())
        bonus_score = total_score - base_score
        
        logger.info(f"   📊 Base Score Breakdown:")
        logger.info(f"      Technical:  {scores['technical']:>2.0f}/25")
        logger.info(f"      Momentum:   {scores['momentum']:>2.0f}/20")
        logger.info(f"      Volume:     {scores['volume']:>2.0f}/15")
        logger.info(f"      Support:    {scores['support']:>2.0f}/15")
        logger.info(f"      Sentiment:  {scores['sentiment']:>2.0f}/10")
        logger.info(f"      NIFTY Corr: {scores['nifty_correlation']:>2.0f}/15")
        logger.info(f"      ────────────────────")
        logger.info(f"      Subtotal:   {base_score:>2.0f}/100")
        
        if bonus_score > 0:
            logger.info(f"      +{bonus_score:.0f} bonus points")
        
        logger.info(f"      ════════════════════")
        logger.info(f"      TOTAL:      {total_score:>2.0f}/100")
        logger.info(f"      ────────────────────")
        logger.info(f"      Decision: Score {total_score:.0f} vs Threshold {skip_threshold:.0f}")
        
        if signal_strength == SignalStrength.SKIP:
            logger.info(f"      → SKIP (< {skip_threshold:.0f}) ❌")
        else:
            logger.info(f"      → PROCEED (≥ {skip_threshold:.0f}) ✅")
        
        return int_signal
    
    def _calculate_nifty_score(self, signal: dict, ctx: MarketContext) -> float:
        """Calculate NIFTY correlation score"""
        score = 0
        rsi = signal.get('rsi')
        if rsi is None:
            rsi = 50
        oversold = rsi < 35
        
        if ctx.nifty_trend == "UP":
            score += 7
            if oversold:
                score += 5
        elif ctx.nifty_trend == "NEUTRAL":
            score += 5
        else:
            score += 2
        
        if ctx.nifty_vwap_position == "ABOVE":
            score += 3
        
        return min(15, score)
    
    def _calculate_vwap_score(self, signal: dict) -> float:
        """
        Calculate VWAP-based score for institutional flow confirmation.
        
        v1.4.1: Disabled before 10:00 AM (VWAP unstable with limited data)
        v1.3.0 FIX: Safe None handling for vwap and ltp
        """
        # v1.4.1: VWAP unstable before 10:00 AM
        current_time = datetime.now().time()
        if current_time < time(10, 0):
            logger.debug(f"  VWAP Score: 0 (disabled before 10:00 AM)")
            return 0
        vwap = signal.get('vwap')
        if vwap is None:
            vwap = 0
        
        vwap_std = signal.get('vwap_std')
        if vwap_std is None:
            vwap_std = 0
        
        ltp = signal.get('ltp')
        if ltp is None:
            ltp = 0
        
        # No VWAP data = no score
        if vwap == 0 or ltp == 0:
            logger.debug(f"  VWAP Score: 0 (no VWAP data)")
            return 0
        
        # Calculate deviation from VWAP
        deviation_pct = ((ltp - vwap) / vwap) * 100
        
        # Calculate position relative to VWAP bands (if available)
        std_distance = None
        if vwap_std > 0:
            std_distance = (ltp - vwap) / vwap_std
        
        # Score based on position relative to VWAP
        score = 0
        reason = ""
        
        if -0.5 <= deviation_pct <= 0:
            score = 20
            reason = "Perfect entry (slight VWAP discount)"
        elif 0 < deviation_pct <= 0.3:
            score = 18
            reason = "Good entry (slight VWAP premium)"
        elif 0.3 < deviation_pct <= 0.8:
            score = 12
            reason = "Acceptable (moderate premium)"
        elif 0.8 < deviation_pct <= 1.5:
            score = 8
            reason = "Caution (higher premium)"
        elif deviation_pct > 1.5:
            score = 3
            reason = "Overextended above VWAP"
        elif -1.0 <= deviation_pct < -0.5:
            score = 15
            reason = "Moderate discount (institutional accumulation?)"
        elif deviation_pct < -1.0:
            score = 5
            reason = "Deep discount (weak institutional support)"
        
        # Bonus: If within 1 standard deviation band
        if std_distance is not None and -1 <= std_distance <= 1:
            score = min(20, score + 2)
            reason += " [within 1σ band]"
        
        logger.debug(f"  VWAP Score: {score:.0f}/20 - {reason}")
        
        return score
    
    def _predict_move(self, signal: dict, ctx: MarketContext, scores: dict) -> dict:
        """Simple direction prediction with safe None handling"""
        bullish = 0
        
        # v1.3.0 FIX: Safe value extraction
        rsi = signal.get('rsi')
        if rsi is None:
            rsi = 50
        
        rsi_change = signal.get('rsi_change')
        if rsi_change is None:
            rsi_change = 0
        
        volume_ratio = signal.get('volume_ratio')
        if volume_ratio is None:
            volume_ratio = 1
        
        if rsi < 35 and rsi_change > 0:
            bullish += 2  # Ramp zone recovery
        if rsi >= 35 and rsi <= 65 and rsi_change > 0:
            bullish += 1  # Climb phase with momentum
        if volume_ratio > 1.3:
            bullish += 1
        if ctx.nifty_trend == "UP":
            bullish += 1
        if scores['technical'] >= 15:
            bullish += 1
        
        if bullish >= 3:
            return {'direction': 'UP', 'confidence': 60 + bullish * 5, 'expected_move': 1.5}
        elif bullish >= 1:
            return {'direction': 'NEUTRAL', 'confidence': 50, 'expected_move': 0.5}
        else:
            return {'direction': 'DOWN', 'confidence': 50, 'expected_move': -0.5}
    
    def _calculate_position_size(self, score: float, strength: SignalStrength, 
                                  regime_params: dict) -> dict:
        """Calculate position size"""
        base_capital = getattr(self.config, 'BASE_CAPITAL_PER_TRADE', 8000)
        
        if strength == SignalStrength.STRONG:
            conf_mult = 1.0
        elif strength == SignalStrength.MODERATE:
            conf_mult = 0.75
        elif strength == SignalStrength.WEAK:
            conf_mult = 0.5
        else:
            conf_mult = 0
        
        regime_mult = regime_params.get('position_mult') or 0.7
        final_mult = conf_mult * regime_mult
        
        return {
            'position_pct': final_mult,
            'capital': base_capital * final_mult
        }
    
    def _build_reason(self, signal: dict, scores: dict, ctx: MarketContext, pred: dict) -> str:
        """Build trade reason string with safe None handling"""
        reasons = []
        
        sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        top = [f for f, s in sorted_scores[:2] if s >= 8]
        
        # v1.3.0 FIX: Safe value extraction
        if 'momentum' in top:
            rsi = signal.get('rsi') or 0
            reasons.append(f"RSI {rsi:.0f}")
        if 'volume' in top:
            vol = signal.get('volume_ratio') or 1
            reasons.append(f"Vol {vol:.1f}x")
        if 'nifty_correlation' in top:
            reasons.append(f"NIFTY {ctx.nifty_trend}")
        
        reasons.append(f"Regime: {ctx.regime.value}")
        
        return " | ".join(reasons)
    
    def process_signals(self, raw_signals: List[dict]) -> List[IntelligentSignal]:
        """Process all signals through intelligent engine"""
        if not raw_signals:
            return []
        
        logger.info("")
        logger.info("=" * 80)
        logger.info(f"🧠 INTELLIGENT ENGINE v1.3.0: Processing {len(raw_signals)} signals")
        logger.info("=" * 80)
        
        ctx = self.detect_market_regime()
        
        signals = []
        for signal in raw_signals:
            try:
                int_sig = self.calculate_signal_score(signal, ctx)
                signals.append(int_sig)
            except Exception as e:
                symbol = signal.get('symbol') or '?'
                logger.error(f"Error scoring {symbol}: {e}")
                import traceback
                logger.error(traceback.format_exc())
        
        signals.sort(key=lambda x: x.total_score, reverse=True)
        
        # Log summary
        logger.info("")
        logger.info("📊 RANKING:")
        for i, s in enumerate(signals, 1):
            status = "✅ TRADE" if s.signal_strength != SignalStrength.SKIP else "❌ SKIP"
            logger.info(f"   {i}. {s.symbol}: {s.total_score:.0f}/100 ({s.signal_strength.value}) {status}")
        
        return signals
    
    def get_tradeable_signals(self, signals: List[IntelligentSignal]) -> List[IntelligentSignal]:
        """Get only tradeable signals"""
        return [s for s in signals if s.signal_strength != SignalStrength.SKIP]
    
    def send_analysis_notification(self, signals: List[IntelligentSignal]):
        """Send Telegram notification"""
        if not self.telegram or not signals:
            return
        
        tradeable = self.get_tradeable_signals(signals)
        ctx = self.current_market_context
        
        nifty_change = ctx.nifty_change_pct if ctx else 0
        msg = (
            f"🧠 INTELLIGENT ANALYSIS v1.3.0\n"
            f"{'─' * 25}\n"
            f"📊 Market: {ctx.regime.value if ctx else 'UNKNOWN'}\n"
            f"📈 NIFTY: {ctx.nifty_trend if ctx else '?'} "
            f"({nifty_change:+.2f}%)\n\n"
        )
        
        if tradeable:
            msg += f"✅ TRADEABLE: {len(tradeable)}\n"
            for s in tradeable[:3]:
                msg += (
                    f"\n{s.symbol}\n"
                    f"  Score: {s.total_score:.0f}/100 ({s.signal_strength.value})\n"
                    f"  Position: {s.recommended_position_pct*100:.0f}%\n"
                )
        else:
            msg += "❌ No tradeable signals\n"
        
        skipped = len(signals) - len(tradeable)
        if skipped > 0:
            threshold = self.THRESHOLDS['skip']
            if self.starvation_prevention:
                adjusted, _ = self.starvation_prevention.get_adjusted_threshold(threshold)
                min_floor = getattr(self.config, 'STARVATION_MINIMUM_THRESHOLD', 45)
                threshold = max(adjusted, min_floor)
            msg += f"\n⏭️ Skipped: {skipped} (score < {threshold})"
        
        try:
            self.telegram.send_message(msg)
        except Exception as e:
            logger.error(f"Failed to send Telegram notification: {e}")
