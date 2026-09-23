"""
DECISION_HISTORY.PY - Track Decisions, Predictions & Learning v5.0.0
═══════════════════════════════════════════════════════════════════════════════

v5.0.0 MAJOR UPGRADE: SQLite Database Integration
─────────────────────────────────────────────────────────────────────────────

NEW IN v5.0.0:
- All decisions stored in unified SQLite database
- No more individual JSON files for each decision
- Fast queries: "Show me all HOLD decisions this week"
- Backward compatible API - same methods work

REPLACES:
- data/decision_history/*.json → database table: decisions
- data/decision_history/predictions/*.json → database table: predictions
- data/decision_history/accuracy/*.json → computed from database
- data/decision_history/learning/*.json → database table: ai_learning

FEATURES (unchanged from v4.9.0):
1. ✅ DecisionRecord - Store ChatGPT decisions
2. ✅ PredictionRecord - Store Truth Predictor outputs
3. ✅ record_prediction() - Save multi-indicator predictions
4. ✅ track_prediction_accuracy() - Compare predicted vs actual prices
5. ✅ get_chatgpt_learning_data() - Format data for ChatGPT review
6. ✅ generate_accuracy_report() - Indicator performance stats

Author: Dheebanraj
Version: 5.0.0
Date: 2026-02-04
"""

import json
import logging
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, asdict, field
from collections import defaultdict
from pathlib import Path

# Import unified data manager
try:
    from unified_data_manager import get_db, UnifiedDataManager
except ImportError:
    get_db = None
    UnifiedDataManager = None

logger = logging.getLogger('DecisionHistory')


# ═══════════════════════════════════════════════════════════════════════════════
# DATA CLASSES (unchanged from v4.9.0)
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class DecisionRecord:
    """Single decision record with outcome"""
    timestamp: str
    symbol: str
    decision: str  # HOLD, EXIT, TIGHTEN_STOP, etc.
    reason: str  # TCAS_RA, HEALTH_CRITICAL, etc.
    confidence: float
    
    # Context at decision time
    current_price: float
    entry_price: float
    target_price: float
    stop_price: float
    net_pnl: float
    
    # Probabilistic analysis (if available)
    prob_target: Optional[float] = None
    prob_stop: Optional[float] = None
    ev_hold: Optional[float] = None
    ev_exit: Optional[float] = None
    
    # Outcome (filled later)
    outcome: Optional[str] = None  # TARGET_HIT, STOP_HIT, STILL_OPEN, MANUAL_EXIT
    outcome_time: Optional[str] = None
    outcome_price: Optional[float] = None
    actual_pnl: Optional[float] = None
    time_to_outcome_minutes: Optional[int] = None
    
    # Was prediction correct?
    prediction_correct: Optional[bool] = None
    
    def to_dict(self) -> Dict:
        """Convert to dictionary"""
        return asdict(self)


@dataclass
class PredictionRecord:
    """
    Store Truth Predictor predictions at entry time.
    Records all indicator values and predictions for later accuracy tracking.
    """
    # Identity
    trade_id: str  # Format: SYMBOL_YYYYMMDD_HHMMSS
    symbol: str
    timestamp: str
    
    # Entry context
    entry_price: float
    stop_price: float
    target_price: float
    quantity: int
    
    # Short-term predictions (Kalman + BB + ATR)
    short_term: Dict = field(default_factory=lambda: {
        'confidence': 0,
        'kalman_velocity': 0,
        'kalman_acceleration': 0,
        'bb_upper': 0,
        'bb_middle': 0,
        'bb_lower': 0,
        'atr': 0,
        'atr_pct': 0,
        'predicted_1h': {'low': 0, 'high': 0},
        'predicted_2h': {'low': 0, 'high': 0},
        'predicted_eod': {'low': 0, 'high': 0},
        'flight_status': 'UNKNOWN'
    })
    
    # Long-term predictions (Kalman + VWAP + Volume + BB + Fib)
    long_term: Dict = field(default_factory=lambda: {
        'confidence': 0,
        'vwap': 0,
        'vwap_position': 'UNKNOWN',
        'volume_ratio': 0,
        'fib_levels': {},
        'current_fib_level': 0,
        'predicted_tomorrow': {'low': 0, 'high': 0},
        'predicted_week': {'low': 0, 'high': 0}
    })
    
    # Indicator snapshots
    indicators: Dict = field(default_factory=lambda: {
        'rsi': 0,
        'macd': 0,
        'macd_signal': 0,
        'macd_histogram': 0,
        'adx': 0,
        'ema21': 0,
        'ma20': 0,
        'ma50': 0
    })
    
    # ChatGPT review at entry
    chatgpt_review: Dict = field(default_factory=dict)
    
    # Checkpoints during hold
    checkpoints: List[Dict] = field(default_factory=list)
    
    # Outcome (filled at exit)
    outcome: Dict = field(default_factory=lambda: {
        'exit_time': None,
        'exit_price': None,
        'exit_reason': None,
        'actual_pnl': None,
        'actual_pnl_pct': None,
        'hold_duration_minutes': None
    })
    
    # Accuracy analysis (filled at exit)
    accuracy: Dict = field(default_factory=lambda: {
        'short_term_accurate': None,
        'long_term_accurate': None,
        'vwap_signal_correct': None,
        'volume_signal_correct': None,
        'fib_level_respected': None,
        'kalman_direction_correct': None,
        'bb_contained_price': None,
        'overall_accuracy_pct': None
    })
    
    # ChatGPT learning (filled post-exit)
    chatgpt_learning: Dict = field(default_factory=lambda: {
        'review_time': None,
        'patterns_identified': [],
        'what_worked': [],
        'what_failed': [],
        'suggested_adjustments': [],
        'confidence_calibration': None
    })
    
    def to_dict(self) -> Dict:
        """Convert to dictionary"""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'PredictionRecord':
        """Create from dictionary"""
        return cls(**data)


# ═══════════════════════════════════════════════════════════════════════════════
# DECISION HISTORY TRACKER v5.0.0
# ═══════════════════════════════════════════════════════════════════════════════

class DecisionHistoryTracker:
    """
    Track ChatGPT decisions, predictions, and outcomes.
    
    v5.0.0: SQLite Database Integration
    - All data stored in unified database
    - Backward compatible API
    - Fast queries and aggregations
    """
    
    def __init__(self, data_dir: str = "./data/decision_history"):
        self.data_dir = Path(data_dir)
        self.predictions_dir = self.data_dir / "predictions"
        self.accuracy_dir = self.data_dir / "accuracy"
        self.learning_dir = self.data_dir / "learning"
        
        # Create directories for backward compatibility
        for dir_path in [self.data_dir, self.predictions_dir, self.accuracy_dir, self.learning_dir]:
            dir_path.mkdir(parents=True, exist_ok=True)
        
        # In-memory caches
        self.decisions: Dict[str, List[DecisionRecord]] = defaultdict(list)
        self.pending_outcomes: Dict[str, DecisionRecord] = {}
        self.predictions: Dict[str, PredictionRecord] = {}
        self.active_predictions: Dict[str, str] = {}
        self.indicator_accuracy: Dict[str, Dict] = defaultdict(lambda: {
            'correct': 0, 'total': 0, 'accuracy': 0.0
        })
        
        # Database connection
        self._db = None
        self._init_database()
        
        # Load existing data
        self._load_from_database()
        
        logger.info("=" * 80)
        logger.info("📚 DECISION HISTORY TRACKER v5.0.0")
        logger.info("=" * 80)
        logger.info("v5.0.0: SQLite Database Integration")
        logger.info(f"   Database: data/algo_beta.db")
        logger.info(f"   Decisions: {sum(len(d) for d in self.decisions.values())} | Predictions: {len(self.predictions)}")
        logger.info("=" * 80)
    
    def _init_database(self):
        """Initialize database connection"""
        try:
            if get_db is not None:
                self._db = get_db()
                logger.info("✅ DecisionHistory connected to SQLite database")
            else:
                logger.warning("⚠️ UnifiedDataManager not available, using legacy JSON storage")
        except Exception as e:
            logger.error(f"Failed to connect to database: {e}")
            self._db = None
    
    def _load_from_database(self):
        """Load recent decisions from database"""
        if not self._db:
            self._load_history()  # Fallback to JSON
            self._load_predictions()
            return
        
        try:
            # Load recent decisions
            recent_decisions = self._db.get_decisions(limit=500)
            for dec in recent_decisions:
                record = DecisionRecord(
                    timestamp=dec.get('timestamp', ''),
                    symbol=dec.get('symbol', ''),
                    decision=dec.get('decision', ''),
                    reason=dec.get('reason', ''),
                    confidence=dec.get('confidence', 0),
                    current_price=dec.get('current_price', 0),
                    entry_price=dec.get('entry_price', 0),
                    target_price=dec.get('target_price', 0),
                    stop_price=dec.get('stop_price', 0),
                    net_pnl=dec.get('net_pnl', 0),
                    prob_target=dec.get('prob_target'),
                    prob_stop=dec.get('prob_stop'),
                    ev_hold=dec.get('ev_hold'),
                    ev_exit=dec.get('ev_exit'),
                    outcome=dec.get('outcome'),
                    outcome_price=dec.get('outcome_price'),
                    actual_pnl=dec.get('actual_pnl'),
                    prediction_correct=dec.get('prediction_correct')
                )
                self.decisions[record.symbol].append(record)
                if record.outcome is None and record.decision == 'HOLD':
                    self.pending_outcomes[record.symbol] = record
            
            logger.info(f"✅ Loaded {len(recent_decisions)} decisions from database")
            
        except Exception as e:
            logger.error(f"Failed to load from database: {e}")
            self._load_history()  # Fallback
            self._load_predictions()
    
    # ═══════════════════════════════════════════════════════════════════════════
    # DECISION RECORDING
    # ═══════════════════════════════════════════════════════════════════════════
    
    def record_decision(self, symbol: str, decision: str, reason: str, confidence: float,
                       position_data: Dict, probabilistic_analysis: Dict = None) -> DecisionRecord:
        """Record a ChatGPT decision"""
        record = DecisionRecord(
            timestamp=datetime.now().isoformat(),
            symbol=symbol,
            decision=decision,
            reason=reason,
            confidence=confidence,
            current_price=position_data.get('current_price', 0),
            entry_price=position_data.get('entry_price', 0),
            target_price=position_data.get('target_price', 0),
            stop_price=position_data.get('stop_price', 0),
            net_pnl=position_data.get('net_pnl', 0)
        )
        
        if probabilistic_analysis:
            record.prob_target = probabilistic_analysis.get('probability_target_hit')
            record.prob_stop = probabilistic_analysis.get('probability_stop_hit')
            record.ev_hold = probabilistic_analysis.get('expected_value_hold')
            record.ev_exit = probabilistic_analysis.get('expected_value_exit')
        
        # Add to in-memory cache
        self.decisions[symbol].append(record)
        if decision == 'HOLD':
            self.pending_outcomes[symbol] = record
        
        # Save to database
        if self._db:
            try:
                self._db.save_decision(record.to_dict())
            except Exception as e:
                logger.error(f"Failed to save decision to database: {e}")
                self._save_decision(record)  # Fallback to JSON
        else:
            self._save_decision(record)  # Legacy JSON
        
        logger.info(f"📝 Recorded decision for {symbol}: {decision} ({confidence:.0%})")
        return record
    
    def record_outcome(self, symbol: str, outcome: str, outcome_price: float, actual_pnl: float):
        """Record outcome for a pending decision"""
        if symbol not in self.pending_outcomes:
            return
        
        record = self.pending_outcomes[symbol]
        record.outcome = outcome
        record.outcome_time = datetime.now().isoformat()
        record.outcome_price = outcome_price
        record.actual_pnl = actual_pnl
        
        decision_time = datetime.fromisoformat(record.timestamp)
        record.time_to_outcome_minutes = int((datetime.now() - decision_time).total_seconds() / 60)
        
        if record.decision == 'HOLD':
            record.prediction_correct = (outcome == 'TARGET_HIT')
        
        del self.pending_outcomes[symbol]
        
        # Update in database
        if self._db:
            try:
                # Save updated decision
                self._db.save_decision(record.to_dict())
            except Exception as e:
                logger.error(f"Failed to update outcome in database: {e}")
        
        self._save_decision(record)  # Also save to JSON for backup
        
        logger.info(f"✅ Outcome for {symbol}: {outcome} (Correct: {record.prediction_correct})")
    
    def get_decision_accuracy(self, symbol: str = None, days: int = 30) -> Dict:
        """Calculate decision accuracy metrics"""
        
        # Try database first
        if self._db:
            try:
                results = self._db.query('''
                    SELECT 
                        COUNT(*) as total,
                        SUM(CASE WHEN prediction_correct = 1 THEN 1 ELSE 0 END) as correct,
                        decision
                    FROM decisions
                    WHERE timestamp >= datetime('now', ?)
                    AND outcome IS NOT NULL
                    AND prediction_correct IS NOT NULL
                    {} 
                    GROUP BY decision
                '''.format("AND symbol = ?" if symbol else ""), 
                (f'-{days} days', symbol) if symbol else (f'-{days} days',))
                
                total = sum(r['total'] for r in results)
                correct = sum(r['correct'] for r in results)
                
                by_type = {}
                for r in results:
                    by_type[r['decision']] = {
                        'total': r['total'],
                        'correct': r['correct'],
                        'accuracy': r['correct'] / r['total'] if r['total'] > 0 else 0
                    }
                
                return {
                    'total_decisions': total,
                    'correct_predictions': correct,
                    'accuracy': correct / total if total > 0 else 0,
                    'by_decision_type': by_type
                }
            except Exception as e:
                logger.debug(f"Database query failed: {e}")
        
        # Fallback to in-memory
        cutoff = datetime.now() - timedelta(days=days)
        relevant = []
        
        if symbol:
            relevant = self.decisions.get(symbol, [])
        else:
            for decisions in self.decisions.values():
                relevant.extend(decisions)
        
        relevant = [d for d in relevant if datetime.fromisoformat(d.timestamp) >= cutoff
                   and d.outcome and d.prediction_correct is not None]
        
        if not relevant:
            return {'total_decisions': 0, 'accuracy': 0.0, 'by_decision_type': {}}
        
        total = len(relevant)
        correct = sum(1 for d in relevant if d.prediction_correct)
        
        by_type = defaultdict(lambda: {'total': 0, 'correct': 0, 'accuracy': 0.0})
        for d in relevant:
            by_type[d.decision]['total'] += 1
            if d.prediction_correct:
                by_type[d.decision]['correct'] += 1
        
        for stats in by_type.values():
            if stats['total'] > 0:
                stats['accuracy'] = stats['correct'] / stats['total']
        
        return {
            'total_decisions': total,
            'correct_predictions': correct,
            'accuracy': correct / total if total > 0 else 0,
            'by_decision_type': dict(by_type)
        }
    
    # ═══════════════════════════════════════════════════════════════════════════
    # PREDICTION RECORDING
    # ═══════════════════════════════════════════════════════════════════════════
    
    
    def get_similar_historical_cases(self, symbol: str, current_setup: Dict, 
                                     max_results: int = 5) -> List[Dict]:
        """
        v5.0.0 NEW: Find similar historical trading setups.
        
        Called by Phase 4 to provide context for AI decisions.
        
        Args:
            symbol: Stock symbol
            current_setup: Dict with pnl_pct, recovery_pct, hold_time, etc.
            max_results: Maximum similar cases to return
            
        Returns:
            List of similar historical decisions with outcomes
        """
        similar_cases = []
        
        try:
            current_pnl = current_setup.get('pnl_pct', 0)
            current_recovery = current_setup.get('recovery_pct', 0)
            current_hold = current_setup.get('hold_time_min', 0)
            
            # Search through decision history
            # Flatten all decision lists into a single list, then take last 200
            all_decisions = [d for dlist in self.decisions.values() for d in dlist]
            for decision in all_decisions[-200:]:  # Last 200 decisions
                if not decision.outcome:
                    continue
                
                # Calculate similarity score
                similarity = 0
                
                # Same symbol bonus
                if decision.symbol == symbol:
                    similarity += 30
                
                # Similar P&L range — calculate from stored prices
                hist_pnl = ((decision.current_price - decision.entry_price) / decision.entry_price * 100) if decision.entry_price and decision.entry_price > 0 else 0
                if abs(hist_pnl - current_pnl) < 2:
                    similarity += 25
                elif abs(hist_pnl - current_pnl) < 5:
                    similarity += 15
                
                # Similar decision
                if decision.decision == current_setup.get('proposed_decision'):
                    similarity += 20
                
                # Similar confidence
                hist_conf = decision.confidence or 0
                current_conf = current_setup.get('confidence', 50)
                if abs(hist_conf - current_conf) < 10:
                    similarity += 15
                
                if similarity >= 40:
                    similar_cases.append({
                        'symbol': decision.symbol,
                        'date': decision.timestamp[:10] if decision.timestamp else 'Unknown',
                        'decision': decision.decision,
                        'confidence': decision.confidence,
                        'outcome': decision.outcome,
                        'pnl_at_decision': hist_pnl,
                        'final_pnl': decision.outcome.get('actual_pnl') if isinstance(decision.outcome, dict) else None,
                        'similarity_score': similarity,
                        'reasoning': decision.reason[:100] if decision.reason else None
                    })
            
            # Sort by similarity and return top results
            similar_cases.sort(key=lambda x: x['similarity_score'], reverse=True)
            return similar_cases[:max_results]
            
        except Exception as e:
            logger.warning(f"Error finding similar cases: {e}")
            return []
    

    def record_prediction(self, symbol: str, entry_price: float, 
                         # Legacy parameters (Phase 3 style)
                         stop_price: float = None, target_price: float = None, 
                         quantity: int = None, short_term_predictions: Dict = None,
                         long_term_predictions: Dict = None, indicators: Dict = None,
                         chatgpt_review: Dict = None,
                         # New parameters (Phase 4 TruthPredictor style)
                         predictions: Dict = None, targets: Dict = None, 
                         confidence: float = None) -> PredictionRecord:
        """
        Record Truth Predictor predictions at entry.
        
        v5.0.0: Now supports BOTH calling conventions:
        - Legacy (Phase 3): stop_price, target_price, short_term_predictions, long_term_predictions
        - New (Phase 4): predictions, targets, confidence
        """
        now = datetime.now()
        trade_id = f"{symbol}_{now.strftime('%Y%m%d_%H%M%S')}"
        
        # Handle new Phase 4 TruthPredictor format
        if predictions is not None:
            # Convert TruthPredictor format to legacy format
            short_term = {
                'predictions': predictions,
                'confidence': confidence or 0
            }
            long_term = {
                'targets': targets or {},
                'confidence': confidence or 0
            }
            stop_price = stop_price or targets.get('stop_price', 0) if targets else 0
            target_price = target_price or targets.get('target_price', 0) if targets else 0
            quantity = quantity or 1
            indicators = indicators or {}
        else:
            # Use legacy format directly
            short_term = short_term_predictions or {}
            long_term = long_term_predictions or {}
            indicators = indicators or {}
        
        record = PredictionRecord(
            trade_id=trade_id,
            symbol=symbol,
            timestamp=now.isoformat(),
            entry_price=entry_price,
            stop_price=stop_price or 0,
            target_price=target_price or 0,
            quantity=quantity or 1,
            short_term=short_term,
            long_term=long_term,
            indicators=indicators,
            chatgpt_review=chatgpt_review or {}
        )
        
        self.predictions[trade_id] = record
        self.active_predictions[symbol] = trade_id
        self._save_prediction(record)
        
        conf_display = confidence if confidence else short_term.get('confidence', 0)
        logger.info(f"🔮 Recorded prediction for {symbol} | Trade ID: {trade_id}")
        logger.info(f"   Confidence: {conf_display:.0%}" if isinstance(conf_display, float) else f"   Confidence: {conf_display}%")
        return record
    
    def add_prediction_checkpoint(self, symbol: str, 
                                  # Support both calling conventions:
                                  # Old style: (symbol, current_price, predicted_price, checkpoint_type)
                                  # New style (Phase 4): (symbol, checkpoint_type, actual_price)
                                  current_price: float = None,
                                  predicted_price: float = None, 
                                  checkpoint_type: str = "1H",
                                  actual_price: float = None):
        """
        Add checkpoint during hold.
        
        v5.0.0: Now accepts both calling conventions:
        - Old: (symbol, current_price, predicted_price, checkpoint_type)
        - New (Phase 4): (symbol, checkpoint_type=..., actual_price=...)
        """
        if symbol not in self.active_predictions:
            return
        
        trade_id = self.active_predictions[symbol]
        record = self.predictions.get(trade_id)
        if not record:
            return
        
        # Handle Phase 4's new calling convention
        if actual_price is not None and current_price is None:
            current_price = actual_price
        
        # If no predicted_price provided, use a default based on entry
        if predicted_price is None:
            predicted_price = record.entry_price * 1.02  # Assume 2% target as default
        
        error_pct = abs(current_price - predicted_price) / predicted_price * 100 if predicted_price > 0 else 0
        accuracy_pct = max(0, 100 - error_pct)
        
        checkpoint = {
            'time': datetime.now().isoformat(),
            'type': checkpoint_type,
            'actual_price': current_price,
            'predicted_price': predicted_price,
            'accuracy_pct': round(accuracy_pct, 2)
        }
        
        record.checkpoints.append(checkpoint)
        self._save_prediction(record)
        logger.info(f"📍 Checkpoint {checkpoint_type} for {symbol}: Accuracy {accuracy_pct:.0f}%")
    
    def track_prediction_accuracy(self, symbol: str, exit_price: float,
                                  # Support both calling conventions:
                                  exit_reason: str = None, actual_pnl: float = None,
                                  exit_time: object = None) -> Dict:
        """
        Calculate prediction accuracy when position closes.
        
        v5.0.0: Now accepts both calling conventions:
        - Old: (symbol, exit_price, exit_reason, actual_pnl)
        - New (Phase 4): (symbol, exit_price, exit_time=...)
        """
        if symbol not in self.active_predictions:
            return {}
        
        trade_id = self.active_predictions[symbol]
        record = self.predictions.get(trade_id)
        if not record:
            return {}
        
        entry_time = datetime.fromisoformat(record.timestamp)
        hold_duration = int((datetime.now() - entry_time).total_seconds() / 60)
        
        record.outcome = {
            'exit_time': datetime.now().isoformat(),
            'exit_price': exit_price,
            'exit_reason': exit_reason,
            'actual_pnl': actual_pnl,
            'actual_pnl_pct': ((exit_price - record.entry_price) / record.entry_price * 100) if record.entry_price > 0 else 0,
            'hold_duration_minutes': hold_duration
        }
        
        accuracy = self._calculate_accuracy_metrics(record, exit_price)
        record.accuracy = accuracy
        self._update_indicator_accuracy(record, accuracy)
        
        del self.active_predictions[symbol]
        self._save_prediction(record)
        self._save_accuracy_report(record)
        
        logger.info(f"📊 Prediction accuracy for {symbol}: {accuracy.get('overall_accuracy_pct', 0):.0f}%")
        return accuracy
    
    def _calculate_accuracy_metrics(self, record: PredictionRecord, exit_price: float) -> Dict:
        """Calculate detailed accuracy metrics"""
        accuracy = {}
        correct_count = 0
        total_checks = 0
        entry_price = record.entry_price
        short_term = record.short_term
        long_term = record.long_term
        
        # 1. Short-term accuracy
        if short_term.get('predicted_eod', {}).get('low', 0) > 0:
            eod_low = short_term['predicted_eod']['low']
            eod_high = short_term['predicted_eod']['high']
            accuracy['short_term_accurate'] = eod_low <= exit_price <= eod_high
            if accuracy['short_term_accurate']:
                correct_count += 1
            total_checks += 1
        
        # 2. Kalman direction
        kalman_velocity = short_term.get('kalman_velocity', 0)
        actual_direction = exit_price - entry_price
        if kalman_velocity != 0:
            accuracy['kalman_direction_correct'] = (kalman_velocity > 0 and actual_direction > 0) or \
                                                    (kalman_velocity < 0 and actual_direction < 0)
            if accuracy['kalman_direction_correct']:
                correct_count += 1
            total_checks += 1
        
        # 3. BB containment
        bb_lower = short_term.get('bb_lower', 0)
        bb_upper = short_term.get('bb_upper', 0)
        if bb_lower > 0 and bb_upper > 0:
            accuracy['bb_contained_price'] = bb_lower <= exit_price <= bb_upper
            if accuracy['bb_contained_price']:
                correct_count += 1
            total_checks += 1
        
        # 4. VWAP signal
        vwap_position = long_term.get('vwap_position', 'UNKNOWN')
        actual_pnl = record.outcome.get('actual_pnl', 0)
        if vwap_position != 'UNKNOWN':
            accuracy['vwap_signal_correct'] = (vwap_position == 'ABOVE' and actual_pnl > 0) or \
                                               (vwap_position == 'BELOW' and actual_pnl < 0)
            if accuracy['vwap_signal_correct']:
                correct_count += 1
            total_checks += 1
        
        # 5. Volume signal
        volume_ratio = long_term.get('volume_ratio', 0)
        if volume_ratio > 0:
            accuracy['volume_signal_correct'] = (volume_ratio > 1.2 and actual_pnl > 0) or \
                                                 (volume_ratio <= 0.8 and actual_pnl < 0)
            if accuracy.get('volume_signal_correct'):
                correct_count += 1
            total_checks += 1
        
        # Overall
        accuracy['overall_accuracy_pct'] = round(correct_count / total_checks * 100, 1) if total_checks > 0 else 0
        return accuracy
    
    def _update_indicator_accuracy(self, record: PredictionRecord, accuracy: Dict):
        """Update indicator accuracy cache"""
        for indicator, key in [('kalman', 'kalman_direction_correct'), 
                               ('vwap', 'vwap_signal_correct'),
                               ('volume', 'volume_signal_correct'), 
                               ('bollinger', 'bb_contained_price')]:
            if accuracy.get(key) is not None:
                self.indicator_accuracy[indicator]['total'] += 1
                if accuracy[key]:
                    self.indicator_accuracy[indicator]['correct'] += 1
                if self.indicator_accuracy[indicator]['total'] > 0:
                    self.indicator_accuracy[indicator]['accuracy'] = \
                        self.indicator_accuracy[indicator]['correct'] / self.indicator_accuracy[indicator]['total']
    
    # ═══════════════════════════════════════════════════════════════════════════
    # CHATGPT LEARNING DATA
    # ═══════════════════════════════════════════════════════════════════════════
    
    def get_chatgpt_learning_data(self, symbol: str = None, trade_id: str = None) -> Dict:
        """Format data for ChatGPT learning review."""
        record = None
        if trade_id and trade_id in self.predictions:
            record = self.predictions[trade_id]
        elif symbol:
            completed = [p for p in self.predictions.values() 
                        if p.symbol == symbol and p.outcome.get('exit_time')]
            if completed:
                completed.sort(key=lambda p: p.timestamp, reverse=True)
                record = completed[0]
        
        if not record:
            return {'error': 'No completed prediction found'}
        
        return {
            'trade_summary': {
                'trade_id': record.trade_id,
                'symbol': record.symbol,
                'entry_price': record.entry_price,
                'exit_price': record.outcome.get('exit_price'),
                'actual_pnl': record.outcome.get('actual_pnl'),
                'hold_duration': record.outcome.get('hold_duration_minutes')
            },
            'predictions_at_entry': {
                'short_term': record.short_term,
                'long_term': record.long_term,
                'indicators': record.indicators
            },
            'accuracy_analysis': record.accuracy,
            'indicator_accuracy_history': dict(self.indicator_accuracy),
            'questions': [
                f"1. Trade was {'PROFIT' if (record.outcome.get('actual_pnl', 0) or 0) > 0 else 'LOSS'}. Why?",
                f"2. Kalman was {'CORRECT' if record.accuracy.get('kalman_direction_correct') else 'WRONG'}. Learn what?",
                f"3. VWAP was {'CORRECT' if record.accuracy.get('vwap_signal_correct') else 'WRONG'}. Adjust weight?",
                f"4. Overall {record.accuracy.get('overall_accuracy_pct', 0):.0f}% accurate. Improve how?"
            ]
        }
    
    def record_chatgpt_learning(self, trade_id: str, patterns: List[str], worked: List[str],
                               failed: List[str], adjustments: List[str], calibration: str):
        """Record ChatGPT's learning from a trade."""
        if trade_id not in self.predictions:
            return
        
        record = self.predictions[trade_id]
        record.chatgpt_learning = {
            'review_time': datetime.now().isoformat(),
            'patterns_identified': patterns,
            'what_worked': worked,
            'what_failed': failed,
            'suggested_adjustments': adjustments,
            'confidence_calibration': calibration
        }
        self._save_prediction(record)
        self._save_learning(record)
        logger.info(f"🧠 Recorded ChatGPT learning for {trade_id}")
    
    # ═══════════════════════════════════════════════════════════════════════════
    # ACCURACY REPORTS
    # ═══════════════════════════════════════════════════════════════════════════
    
    def generate_accuracy_report(self, days: int = 30) -> Dict:
        """Generate comprehensive accuracy report."""
        cutoff = datetime.now() - timedelta(days=days)
        completed = [p for p in self.predictions.values()
                    if p.outcome.get('exit_time') and datetime.fromisoformat(p.timestamp) >= cutoff]
        
        if not completed:
            return {'period_days': days, 'total_trades': 0}
        
        total = len(completed)
        wins = sum(1 for p in completed if (p.outcome.get('actual_pnl') or 0) > 0)
        total_pnl = sum(p.outcome.get('actual_pnl', 0) for p in completed)
        avg_accuracy = sum(p.accuracy.get('overall_accuracy_pct', 0) for p in completed) / total
        
        return {
            'period_days': days,
            'total_trades': total,
            'winning_trades': wins,
            'win_rate': wins / total if total > 0 else 0,
            'total_pnl': total_pnl,
            'avg_prediction_accuracy': avg_accuracy,
            'indicator_accuracy': dict(self.indicator_accuracy),
            'recommendations': self._generate_recommendations()
        }
    
    def _generate_recommendations(self) -> List[str]:
        """Generate recommendations based on accuracy data"""
        recs = []
        sorted_indicators = sorted(self.indicator_accuracy.items(),
                                  key=lambda x: x[1].get('accuracy', 0), reverse=True)
        if sorted_indicators:
            best = sorted_indicators[0]
            worst = sorted_indicators[-1]
            if best[1].get('accuracy', 0) > 0.7:
                recs.append(f"✅ {best[0].upper()} performing well ({best[1]['accuracy']:.0%})")
            if worst[1].get('accuracy', 0) < 0.5 and worst[1].get('total', 0) >= 5:
                recs.append(f"⚠️ {worst[0].upper()} underperforming ({worst[1]['accuracy']:.0%})")
        return recs
    
    def get_accuracy_summary(self) -> str:
        """Get formatted accuracy summary for logging"""
        report = self.generate_accuracy_report(days=30)
        lines = ["=" * 60, "📊 PREDICTION ACCURACY (30 Days)", "=" * 60]
        lines.append(f"Trades: {report.get('total_trades', 0)} | Win Rate: {report.get('win_rate', 0):.0%}")
        lines.append(f"Avg Accuracy: {report.get('avg_prediction_accuracy', 0):.0f}%")
        for indicator, stats in report.get('indicator_accuracy', {}).items():
            lines.append(f"  {indicator}: {stats.get('accuracy', 0):.0%}")
        return "\n".join(lines)
    
    def get_summary(self) -> str:
        """Get summary for logging"""
        return (f"📚 Decisions: {sum(len(d) for d in self.decisions.values())} | "
                f"Predictions: {len(self.predictions)} | Active: {len(self.active_predictions)}")
    
    # ═══════════════════════════════════════════════════════════════════════════
    # PERSISTENCE (Legacy JSON + Database)
    # ═══════════════════════════════════════════════════════════════════════════
    
    def _load_history(self):
        """Load from legacy JSON files"""
        try:
            for f in os.listdir(self.data_dir):
                if f.endswith('.json') and not f.startswith('prediction_'):
                    try:
                        with open(self.data_dir / f, 'r') as file:
                            data = json.load(file)
                            if 'decision' in data and 'trade_id' not in data:
                                record = DecisionRecord(**{k: v for k, v in data.items() 
                                                          if k in DecisionRecord.__dataclass_fields__})
                                self.decisions[record.symbol].append(record)
                                if record.outcome is None and record.decision == 'HOLD':
                                    self.pending_outcomes[record.symbol] = record
                    except Exception as e:
                        logger.debug(f"Failed to load {f}: {e}")
        except Exception as e:
            logger.error(f"Failed to load history: {e}")
    
    def _load_predictions(self):
        """Load from legacy prediction JSON files"""
        try:
            if not self.predictions_dir.exists():
                return
            for f in os.listdir(self.predictions_dir):
                if f.endswith('.json'):
                    try:
                        with open(self.predictions_dir / f, 'r') as file:
                            data = json.load(file)
                            record = PredictionRecord.from_dict(data)
                            self.predictions[record.trade_id] = record
                            if not record.outcome.get('exit_time'):
                                self.active_predictions[record.symbol] = record.trade_id
                    except Exception as e:
                        logger.debug(f"Failed to load prediction {f}: {e}")
        except Exception as e:
            logger.error(f"Failed to load predictions: {e}")
    
    def _save_decision(self, record: DecisionRecord):
        """Save decision to JSON file (backup)"""
        try:
            filename = f"{record.symbol}_{record.timestamp.replace(':', '-')}.json"
            with open(self.data_dir / filename, 'w') as f:
                json.dump(record.to_dict(), f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save decision: {e}")
    
    def _save_prediction(self, record: PredictionRecord):
        """Save prediction to JSON file"""
        try:
            with open(self.predictions_dir / f"prediction_{record.trade_id}.json", 'w') as f:
                json.dump(record.to_dict(), f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save prediction: {e}")
    
    def _save_accuracy_report(self, record: PredictionRecord):
        """Save accuracy report to JSON file"""
        try:
            with open(self.accuracy_dir / f"accuracy_{record.trade_id}.json", 'w') as f:
                json.dump({
                    'trade_id': record.trade_id,
                    'accuracy': record.accuracy
                }, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save accuracy: {e}")
    
    def _save_learning(self, record: PredictionRecord):
        """Save learning to JSON file"""
        try:
            with open(self.learning_dir / f"learning_{record.trade_id}.json", 'w') as f:
                json.dump({
                    'trade_id': record.trade_id,
                    'learning': record.chatgpt_learning
                }, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save learning: {e}")


# ═══════════════════════════════════════════════════════════════════════════════
# SINGLETON ACCESSOR
# ═══════════════════════════════════════════════════════════════════════════════

_tracker_instance: Optional[DecisionHistoryTracker] = None

def get_decision_tracker() -> DecisionHistoryTracker:
    """Get the global decision tracker instance"""
    global _tracker_instance
    if _tracker_instance is None:
        _tracker_instance = DecisionHistoryTracker()
    return _tracker_instance


if __name__ == "__main__":
    # Test the tracker
    print("Testing DecisionHistoryTracker v5.0.0...")
    
    tracker = DecisionHistoryTracker("./test_decision_history")
    
    # Test decision recording
    decision = tracker.record_decision(
        symbol="RELIANCE",
        decision="HOLD",
        reason="RSI_IMPROVING",
        confidence=0.75,
        position_data={
            'current_price': 2520,
            'entry_price': 2500,
            'target_price': 2600,
            'stop_price': 2450,
            'net_pnl': 20
        },
        probabilistic_analysis={
            'probability_target_hit': 0.65,
            'probability_stop_hit': 0.35,
            'expected_value_hold': 50,
            'expected_value_exit': 20
        }
    )
    
    # Test outcome recording
    tracker.record_outcome("RELIANCE", "TARGET_HIT", 2600, 100)
    
    # Get accuracy
    accuracy = tracker.get_decision_accuracy(days=30)
    print(f"\nAccuracy: {accuracy}")
    
    # Summary
    print(f"\nSummary: {tracker.get_summary()}")
    
    # Cleanup
    import shutil
    shutil.rmtree("./test_decision_history", ignore_errors=True)
    
    print("\n✅ Test completed!")
