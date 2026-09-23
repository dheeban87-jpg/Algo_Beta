"""
FINBERT_ANALYZER.PY - Financial Sentiment Analysis v2.0.0
═════════════════════════════════════════════════════════════════════════════

✅ ZERO COST (replaces ChatGPT API $0.03/call)
✅ 86-97% accuracy (vs. ChatGPT ~70%)
✅ Runs locally (no internet needed after download)
✅ 50-100ms per analysis (faster than API)

v2.0.0 CHANGES (2026-01-28):
────────────────────────────
✅ NEW: get_entry_score_contribution() - Returns score points for entry scoring
✅ NEW: BULLISH sentiment adds +15 points (was ignored!)
✅ NEW: NEUTRAL sentiment adds +5 points
✅ NEW: BEARISH sentiment subtracts -20 points (or blocks)
✅ NEW: Entity match gives 1.5x multiplier

Research-backed improvements:
├─ Entity-level sentiment (only analyze news mentioning the stock)
├─ Temporal weighting (4-hour half-life for news decay)
└─ Financial domain expertise (trained on Reuters financial corpus)

Author: Dheebanraj
Date: 2026-01-28
Version: 2.0.0
"""

import torch
import numpy as np
from transformers import BertTokenizer, BertForSequenceClassification
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Optional

logger = logging.getLogger('FinBERT_Analyzer')


class FinBERTAnalyzer:
    """
    Local FinBERT sentiment analyzer for financial news.
    
    v2.0.0: Now contributes to ENTRY SCORING (not just blocking!)
    
    Advantages over ChatGPT:
    ├─ Cost: $0 vs. $0.03 per call
    ├─ Speed: 50-100ms vs. 1-3 seconds
    ├─ Accuracy: 86-97% vs. ~70% for financial text
    ├─ Offline: No internet needed after initial download
    └─ Privacy: All processing local
    """
    
    # v2.0.0: Scoring contribution settings
    BULLISH_BONUS = 15          # Add 15 points for BULLISH
    NEUTRAL_BONUS = 5           # Add 5 points for NEUTRAL
    BEARISH_PENALTY = -20       # Subtract 20 points for BEARISH
    ENTITY_MATCH_MULTIPLIER = 1.5  # 1.5x if news mentions exact stock
    
    def __init__(self, config=None):
        """
        Initialize FinBERT model (one-time download ~500MB).
        
        First run will download the model from Hugging Face.
        Subsequent runs load from cache (~2 seconds).
        
        Args:
            config: Optional config object for scoring settings
        """
        logger.info("=" * 80)
        logger.info("INITIALIZING FINBERT SENTIMENT ANALYZER v2.0.0")
        logger.info("=" * 80)
        logger.info("")
        logger.info("⏳ Loading FinBERT model...")
        logger.info("(First run downloads ~500MB, subsequent runs load from cache)")
        
        # Load scoring settings from config if provided
        if config:
            self.BULLISH_BONUS = getattr(config, 'FINBERT_BULLISH_BONUS', 15)
            self.NEUTRAL_BONUS = getattr(config, 'FINBERT_NEUTRAL_BONUS', 5)
            self.BEARISH_PENALTY = getattr(config, 'FINBERT_BEARISH_PENALTY', -20)
            self.ENTITY_MATCH_MULTIPLIER = getattr(config, 'FINBERT_ENTITY_MATCH_MULTIPLIER', 1.5)
        
        try:
            # Load pre-trained financial sentiment model
            self.tokenizer = BertTokenizer.from_pretrained('ProsusAI/finbert')
            self.model = BertForSequenceClassification.from_pretrained('ProsusAI/finbert')
            self.model.eval()  # Set to evaluation mode (no training)
            
            # Get label mapping (verify model configuration)
            self.id2label = self.model.config.id2label
            logger.info(f"Label mapping: {self.id2label}")
            
            logger.info("✅ FinBERT model loaded successfully")
            logger.info(f"   Scoring: BULLISH +{self.BULLISH_BONUS}, "
                       f"NEUTRAL +{self.NEUTRAL_BONUS}, "
                       f"BEARISH {self.BEARISH_PENALTY}")
            logger.info("")
            
        except Exception as e:
            logger.error("=" * 80)
            logger.error("❌ FAILED TO LOAD FINBERT MODEL")
            logger.error("=" * 80)
            logger.error(f"Error: {e}")
            logger.error("")
            logger.error("Solution:")
            logger.error("1. Install transformers: pip install transformers torch")
            logger.error("2. Check internet connection (for first-time download)")
            logger.error("3. Ensure sufficient disk space (~1GB)")
            raise
    
    
    def analyze_sentiment(
        self, 
        text_list: List[str], 
        symbol: Optional[str] = None,
        timestamps: Optional[List[datetime]] = None,
        use_temporal_decay: bool = True
    ) -> Dict:
        """
        Analyze sentiment of news headlines/articles.
        
        Args:
            text_list: List of news headlines or articles
            symbol: Stock symbol (for entity-level filtering)
            timestamps: Optional timestamps for temporal weighting
            use_temporal_decay: Apply 4-hour half-life decay
            
        Returns:
            {
                'sentiment_score': -1.0 to +1.0,
                'label': 'BULLISH', 'BEARISH', or 'NEUTRAL',
                'confidence': 0-100,
                'positive_prob': 0-1,
                'negative_prob': 0-1,
                'neutral_prob': 0-1,
                'num_articles': int,
                'entity_matched': bool,  # v2.0.0: Did news mention stock?
                'entry_score_contribution': int  # v2.0.0: Points to add to entry score
            }
        """
        
        # Handle empty input
        if not text_list:
            logger.warning("No news text provided - returning neutral sentiment")
            return self._neutral_response()
        
        # RESEARCH IMPROVEMENT #1: Entity-Level Sentiment Filtering
        # Only analyze headlines that mention the specific stock
        filtered_text = text_list
        entity_matched = False
        
        if symbol:
            # Check if any headline mentions the stock
            symbol_variations = [
                symbol.upper(),
                symbol.lower(),
                symbol.replace('&', 'AND'),
                symbol.replace('AND', '&')
            ]
            
            matched_headlines = []
            for text in text_list:
                text_upper = text.upper()
                for variation in symbol_variations:
                    if variation.upper() in text_upper:
                        matched_headlines.append(text)
                        entity_matched = True
                        break
            
            # Use matched headlines if available, otherwise all headlines
            if matched_headlines:
                filtered_text = matched_headlines
                logger.info(f"📰 Found {len(matched_headlines)} headlines mentioning {symbol}")
            else:
                logger.info(f"📰 No headlines mention {symbol}, using all {len(text_list)} headlines")
        
        # Analyze each headline
        all_scores = []
        all_probs = []
        
        for i, text in enumerate(filtered_text):
            try:
                # Tokenize
                inputs = self.tokenizer(
                    text, 
                    return_tensors="pt", 
                    truncation=True, 
                    max_length=512,
                    padding=True
                )
                
                # Get model prediction
                with torch.no_grad():
                    outputs = self.model(**inputs)
                    probs = torch.softmax(outputs.logits, dim=1).numpy()[0]
                
                # FinBERT labels: 0=positive, 1=negative, 2=neutral
                # (May vary - check id2label)
                pos_idx = [k for k, v in self.id2label.items() if 'positive' in v.lower()][0]
                neg_idx = [k for k, v in self.id2label.items() if 'negative' in v.lower()][0]
                
                pos_prob = probs[pos_idx]
                neg_prob = probs[neg_idx]
                
                # Calculate score: -1 (bearish) to +1 (bullish)
                score = pos_prob - neg_prob
                
                # Apply temporal decay if timestamps provided
                weight = 1.0
                if use_temporal_decay and timestamps and i < len(timestamps):
                    hours_old = (datetime.now() - timestamps[i]).total_seconds() / 3600
                    half_life = 4.0  # 4-hour half-life
                    weight = 0.5 ** (hours_old / half_life)
                
                all_scores.append(score * weight)
                all_probs.append(probs)
                
            except Exception as e:
                logger.warning(f"Error analyzing text: {e}")
                continue
        
        # Aggregate results
        if not all_scores:
            return self._neutral_response()
        
        # Weighted average sentiment
        avg_score = np.mean(all_scores)
        avg_probs = np.mean(all_probs, axis=0)
        
        pos_idx = [k for k, v in self.id2label.items() if 'positive' in v.lower()][0]
        neg_idx = [k for k, v in self.id2label.items() if 'negative' in v.lower()][0]
        neu_idx = [k for k, v in self.id2label.items() if 'neutral' in v.lower()][0]
        
        # Determine label
        if avg_score > 0.2:
            label = 'BULLISH'
        elif avg_score < -0.2:
            label = 'BEARISH'
        else:
            label = 'NEUTRAL'
        
        # Calculate confidence (0-100)
        confidence = int(max(avg_probs) * 100)
        
        # v2.0.0: Calculate entry score contribution
        entry_score_contribution = self._calculate_entry_score_contribution(
            label, avg_score, confidence, entity_matched
        )
        
        result = {
            'sentiment_score': float(avg_score),
            'label': label,
            'confidence': confidence,
            'positive_prob': float(avg_probs[pos_idx]),
            'negative_prob': float(avg_probs[neg_idx]),
            'neutral_prob': float(avg_probs[neu_idx]),
            'num_articles': len(filtered_text),
            'entity_matched': entity_matched,
            'entry_score_contribution': entry_score_contribution
        }
        
        logger.info(f"📊 FinBERT Result: {label} (score: {avg_score:.2f}, "
                   f"confidence: {confidence}%, "
                   f"entry contribution: {entry_score_contribution:+d} pts)")
        
        return result
    
    
    def _calculate_entry_score_contribution(
        self, 
        label: str, 
        score: float, 
        confidence: int,
        entity_matched: bool
    ) -> int:
        """
        v2.0.0: Calculate contribution to entry score.
        
        Scoring logic:
        - BULLISH: +15 points (confirms trade thesis)
        - NEUTRAL: +5 points (no negative news)
        - BEARISH: -20 points (warns against entry)
        
        Multipliers:
        - Entity match (news mentions stock): 1.5x
        - High confidence (>80%): score scaled by confidence
        
        Args:
            label: Sentiment label (BULLISH/NEUTRAL/BEARISH)
            score: Sentiment score (-1 to +1)
            confidence: Confidence percentage (0-100)
            entity_matched: Whether news mentioned the stock
            
        Returns:
            Points to add to entry score (can be negative)
        """
        # Base score by label
        if label == 'BULLISH':
            base_score = self.BULLISH_BONUS
        elif label == 'BEARISH':
            base_score = self.BEARISH_PENALTY
        else:  # NEUTRAL
            base_score = self.NEUTRAL_BONUS
        
        # Scale by confidence (higher confidence = stronger signal)
        confidence_multiplier = confidence / 100.0
        scaled_score = base_score * confidence_multiplier
        
        # Entity match bonus (1.5x if news mentions exact stock)
        if entity_matched:
            scaled_score *= self.ENTITY_MATCH_MULTIPLIER
        
        return int(round(scaled_score))
    
    
    def get_entry_score_contribution(
        self,
        text_list: List[str],
        symbol: Optional[str] = None,
        timestamps: Optional[List[datetime]] = None
    ) -> Dict:
        """
        v2.0.0: Convenience method to get entry score contribution.
        
        Use this when you just need the score contribution for entry decisions.
        
        Args:
            text_list: List of news headlines
            symbol: Stock symbol
            timestamps: Optional timestamps
            
        Returns:
            {
                'contribution': int (-20 to +22),
                'label': str,
                'confidence': int,
                'should_block': bool (if BEARISH + strong confidence)
            }
        """
        result = self.analyze_sentiment(text_list, symbol, timestamps)
        
        # Determine if we should block entry
        should_block = (
            result['label'] == 'BEARISH' and 
            result['sentiment_score'] < -0.3 and
            result['confidence'] >= 70 and
            result['num_articles'] >= 2
        )
        
        return {
            'contribution': result['entry_score_contribution'],
            'label': result['label'],
            'confidence': result['confidence'],
            'score': result['sentiment_score'],
            'should_block': should_block,
            'num_articles': result['num_articles'],
            'entity_matched': result['entity_matched']
        }
    
    
    def _neutral_response(self) -> Dict:
        """Return neutral sentiment when no data available."""
        return {
            'sentiment_score': 0.0,
            'label': 'NEUTRAL',
            'confidence': 50,
            'positive_prob': 0.33,
            'negative_prob': 0.33,
            'neutral_prob': 0.34,
            'num_articles': 0,
            'entity_matched': False,
            'entry_score_contribution': 0
        }
    
    
    def should_block_entry(
        self,
        text_list: List[str],
        symbol: Optional[str] = None,
        min_headlines: int = 2,
        min_bearish_score: float = -0.3,
        min_confidence: int = 70
    ) -> tuple:
        """
        Determine if sentiment should BLOCK trade entry.
        
        v2.2.0 fix: Requires multiple headlines before blocking.
        
        Args:
            text_list: News headlines
            symbol: Stock symbol
            min_headlines: Minimum headlines needed to block (default 2)
            min_bearish_score: Minimum bearish score to block (default -0.3)
            min_confidence: Minimum confidence to block (default 70)
            
        Returns:
            (should_block: bool, reason: str)
        """
        result = self.analyze_sentiment(text_list, symbol)
        
        # Not enough headlines to make a decision
        if result['num_articles'] < min_headlines:
            return False, f"Only {result['num_articles']} headlines (need {min_headlines})"
        
        # Check blocking conditions
        if (result['label'] == 'BEARISH' and 
            result['sentiment_score'] < min_bearish_score and
            result['confidence'] >= min_confidence):
            
            reason = (f"BEARISH sentiment detected! "
                     f"Score: {result['sentiment_score']:.2f}, "
                     f"Confidence: {result['confidence']}%, "
                     f"Headlines: {result['num_articles']}")
            return True, reason
        
        return False, "Sentiment OK for entry"


# Singleton instance
_finbert_instance = None

def get_finbert_analyzer(config=None) -> FinBERTAnalyzer:
    """
    Get global FinBERT analyzer instance (singleton).
    
    Args:
        config: Optional config for scoring settings
        
    Returns:
        FinBERTAnalyzer instance
    """
    global _finbert_instance
    if _finbert_instance is None:
        _finbert_instance = FinBERTAnalyzer(config)
    return _finbert_instance
