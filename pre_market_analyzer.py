"""
PRE_MARKET_ANALYZER.PY - Daily Market Intelligence Briefing
═══════════════════════════════════════════════════════════════════════════════

🧠 Uses ChatGPT + FinBERT to analyze yesterday and predict today
🎯 Runs at 8:30 AM before market opens
📊 Provides actionable trading guidance
💬 Sends comprehensive Telegram briefing

What it analyzes:
├─ Yesterday's NIFTY movement
├─ Yesterday's sector performance
├─ Overnight global markets (US, Asia)
├─ Today's news sentiment (FinBERT)
├─ Market regime (trending, ranging, volatile)
└─ Trading opportunities (which strategies to focus)

Author: Dheebanraj
Version: 1.1.0 (OpenAI 2.x API)
Date: 2026-01-13
"""

from ai_text import first_text
import logging
import anthropic
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import requests
from kiteconnect import KiteConnect

logger = logging.getLogger('PreMarketAnalyzer')


class PreMarketAnalyzer:
    """
    Daily pre-market intelligence briefing.
    
    Runs at 8:30 AM before market opens to:
    ├─ Analyze yesterday's market conditions
    ├─ Predict today's market behavior
    ├─ Recommend trading strategies
    └─ Set expectations for the day
    """
    
    def __init__(self, kite: KiteConnect, config, telegram=None, 
                 finbert=None, chatgpt_key: str = None):
        """
        Initialize pre-market analyzer.
        
        Args:
            kite: KiteConnect instance
            config: System configuration
            telegram: Telegram notifier
            finbert: FinBERT analyzer (for news sentiment)
            chatgpt_key: OpenAI API key
        """
        self.kite = kite
        self.config = config
        self.telegram = telegram
        self.finbert = finbert
        self.chatgpt_key = chatgpt_key
        
        self.claude_client = anthropic.Anthropic(api_key=chatgpt_key, timeout=30.0, max_retries=1) if chatgpt_key else None
        
        logger.info("=" * 80)
        logger.info("PRE-MARKET ANALYZER INITIALIZED")
        logger.info("=" * 80)
        logger.info("Features:")
        logger.info("  ├─ Yesterday's market analysis")
        logger.info("  ├─ Global markets overnight")
        logger.info("  ├─ Today's news sentiment")
        logger.info("  ├─ Market regime prediction")
        logger.info("  └─ Strategy recommendations")
        logger.info("")
    
    
    def run_daily_briefing(self) -> Dict:
        """
        Run complete pre-market analysis and send briefing.
        
        Call this at 8:30 AM before market opens.
        
        Returns:
            {
                'market_outlook': 'BULLISH/BEARISH/NEUTRAL',
                'confidence': 0-100,
                'recommended_strategies': ['V-Recovery', 'Momentum'],
                'risk_level': 'LOW/MEDIUM/HIGH',
                'key_insights': [list of insights],
                'sector_focus': ['BANK', 'IT'],
                'volatility_expected': 'LOW/MEDIUM/HIGH'
            }
        """
        logger.info("=" * 80)
        logger.info("🌅 RUNNING DAILY PRE-MARKET ANALYSIS")
        logger.info("=" * 80)
        logger.info(f"Date: {datetime.now().strftime('%A, %B %d, %Y')}")
        logger.info(f"Time: {datetime.now().strftime('%H:%M:%S')}")
        logger.info("")
        
        try:
            # Step 1: Analyze yesterday's market
            logger.info("📊 Step 1/5: Analyzing yesterday's market...")
            yesterday_data = self._analyze_yesterday()
            
            # Step 2: Check overnight global markets
            logger.info("🌍 Step 2/5: Checking global markets...")
            global_data = self._analyze_global_markets()
            
            # Step 3: Analyze today's news sentiment
            logger.info("📰 Step 3/5: Analyzing news sentiment...")
            news_sentiment = self._analyze_news_sentiment()
            
            # Step 4: Get ChatGPT prediction
            logger.info("🧠 Step 4/5: Getting AI prediction...")
            ai_prediction = self._get_chatgpt_prediction(
                yesterday_data, 
                global_data, 
                news_sentiment
            )
            
            # Step 5: Generate recommendations
            logger.info("🎯 Step 5/5: Generating recommendations...")
            recommendations = self._generate_recommendations(
                yesterday_data,
                global_data,
                news_sentiment,
                ai_prediction
            )
            
            # Send Telegram briefing
            if self.telegram:
                self._send_telegram_briefing(recommendations)
            
            logger.info("=" * 80)
            logger.info("✅ PRE-MARKET ANALYSIS COMPLETE")
            logger.info("=" * 80)
            logger.info(f"Outlook: {recommendations['market_outlook']}")
            logger.info(f"Confidence: {recommendations['confidence']}%")
            logger.info(f"Recommended: {', '.join(recommendations['recommended_strategies'])}")
            logger.info("")
            
            return recommendations
            
        except Exception as e:
            logger.error(f"❌ Pre-market analysis failed: {e}")
            
            # Return neutral outlook on failure
            return {
                'market_outlook': 'NEUTRAL',
                'confidence': 50,
                'recommended_strategies': ['V-Recovery'],
                'risk_level': 'MEDIUM',
                'key_insights': ['Analysis failed - use standard approach'],
                'sector_focus': [],
                'volatility_expected': 'MEDIUM'
            }
    
    
    def _analyze_yesterday(self) -> Dict:
        """
        Analyze yesterday's market performance.
        
        Returns:
            {
                'nifty_change': %,
                'nifty_close': price,
                'volume': ratio vs avg,
                'volatility': HIGH/MEDIUM/LOW,
                'trend': UP/DOWN/SIDEWAYS,
                'top_gainers': [symbols],
                'top_losers': [symbols],
                'sector_performance': {sector: %}
            }
        """
        try:
            # Get yesterday's date
            yesterday = datetime.now() - timedelta(days=1)
            # If today is Monday, get Friday's data
            if yesterday.weekday() >= 5:  # Saturday/Sunday
                yesterday = yesterday - timedelta(days=yesterday.weekday() - 4)
            
            # Get NIFTY 50 data
            from_date = yesterday.date()
            to_date = yesterday.date()
            
            nifty_data = self.kite.historical_data(
                instrument_token=256265,  # NIFTY 50
                from_date=from_date,
                to_date=to_date,
                interval='day'
            )
            
            if nifty_data:
                yesterday_candle = nifty_data[-1]
                nifty_change = ((yesterday_candle['close'] - yesterday_candle['open']) / 
                               yesterday_candle['open']) * 100
                
                # Determine trend
                if nifty_change > 0.5:
                    trend = 'UP'
                elif nifty_change < -0.5:
                    trend = 'DOWN'
                else:
                    trend = 'SIDEWAYS'
                
                # Determine volatility (range as % of close)
                range_pct = ((yesterday_candle['high'] - yesterday_candle['low']) / 
                            yesterday_candle['close']) * 100
                
                if range_pct > 1.5:
                    volatility = 'HIGH'
                elif range_pct > 0.8:
                    volatility = 'MEDIUM'
                else:
                    volatility = 'LOW'
                
                return {
                    'nifty_change': round(nifty_change, 2),
                    'nifty_close': yesterday_candle['close'],
                    'nifty_high': yesterday_candle['high'],
                    'nifty_low': yesterday_candle['low'],
                    'range_pct': round(range_pct, 2),
                    'volatility': volatility,
                    'trend': trend,
                    'volume': 0,  # TODO: Calculate volume ratio
                    'top_gainers': [],  # TODO: Get from market data
                    'top_losers': [],  # TODO: Get from market data
                    'sector_performance': {}  # TODO: Get sector data
                }
            
        except Exception as e:
            logger.warning(f"Could not analyze yesterday: {e}")
        
        return {
            'nifty_change': 0,
            'nifty_close': 0,
            'volatility': 'MEDIUM',
            'trend': 'SIDEWAYS',
            'volume': 1.0
        }
    
    
    def _analyze_global_markets(self) -> Dict:
        """
        Check overnight global markets (US, Asia).
        
        Returns:
            {
                'us_markets': {
                    'sp500_change': %,
                    'nasdaq_change': %,
                    'dow_change': %
                },
                'asian_markets': {
                    'nikkei_change': %,
                    'hangseng_change': %
                },
                'global_sentiment': 'RISK_ON/RISK_OFF/NEUTRAL'
            }
        """
        # TODO: Integrate with financial data API
        # For now, return placeholder
        return {
            'us_markets': {
                'sp500_change': 0,
                'nasdaq_change': 0,
                'dow_change': 0
            },
            'asian_markets': {
                'nikkei_change': 0,
                'hangseng_change': 0
            },
            'global_sentiment': 'NEUTRAL'
        }
    
    
    def _analyze_news_sentiment(self) -> Dict:
        """
        Analyze today's news sentiment using FinBERT.
        
        Returns:
            {
                'sentiment_score': -1 to +1,
                'sentiment_label': 'BULLISH/BEARISH/NEUTRAL',
                'confidence': 0-100,
                'key_headlines': [headlines],
                'top_stocks_mentioned': [symbols]
            }
        """
        try:
            if not self.finbert:
                return {
                    'sentiment_score': 0,
                    'sentiment_label': 'NEUTRAL',
                    'confidence': 0,
                    'key_headlines': [],
                    'top_stocks_mentioned': []
                }
            
            # TODO: Fetch today's news headlines
            # For now, return placeholder
            headlines = [
                "Market opens cautiously amid global uncertainty",
                "IT sector shows strength, BANK sector mixed"
            ]
            
            # Analyze sentiment
            sentiment = self.finbert.analyze_sentiment(
                text_list=headlines,
                symbol=None  # General market sentiment
            )
            
            return {
                'sentiment_score': sentiment['sentiment_score'],
                'sentiment_label': sentiment['label'],
                'confidence': sentiment['confidence'],
                'key_headlines': headlines[:5],
                'top_stocks_mentioned': []
            }
            
        except Exception as e:
            logger.warning(f"Could not analyze news: {e}")
            return {
                'sentiment_score': 0,
                'sentiment_label': 'NEUTRAL',
                'confidence': 0,
                'key_headlines': [],
                'top_stocks_mentioned': []
            }
    
    
    def _get_chatgpt_prediction(
        self, 
        yesterday_data: Dict,
        global_data: Dict,
        news_sentiment: Dict
    ) -> Dict:
        """
        Get ChatGPT's prediction for today's market.
        
        Returns:
            {
                'outlook': 'BULLISH/BEARISH/NEUTRAL',
                'confidence': 0-100,
                'reasoning': str,
                'key_risks': [list],
                'opportunities': [list]
            }
        """
        if not self.chatgpt_key or not self.claude_client:
            return {
                'outlook': 'NEUTRAL',
                'confidence': 50,
                'reasoning': 'ChatGPT not configured',
                'key_risks': [],
                'opportunities': []
            }
        
        try:
            # Build analysis prompt
            prompt = f"""You are a professional Indian stock market analyst. Analyze the data below and predict today's market behavior for NSE intraday trading.

YESTERDAY'S MARKET:
- NIFTY 50 Change: {yesterday_data['nifty_change']:+.2f}%
- NIFTY Close: {yesterday_data['nifty_close']:.2f}
- Trend: {yesterday_data['trend']}
- Volatility: {yesterday_data['volatility']}
- Range: {yesterday_data.get('range_pct', 0):.2f}% (High: {yesterday_data.get('nifty_high', 0):.2f}, Low: {yesterday_data.get('nifty_low', 0):.2f})

GLOBAL MARKETS (Overnight):
- S&P 500: {global_data['us_markets']['sp500_change']:+.2f}%
- NASDAQ: {global_data['us_markets']['nasdaq_change']:+.2f}%
- Global Sentiment: {global_data['global_sentiment']}

NEWS SENTIMENT (Today):
- Sentiment: {news_sentiment['sentiment_label']} ({news_sentiment['sentiment_score']:+.2f})
- Confidence: {news_sentiment['confidence']:.0f}%

Provide your analysis in JSON format:
{{
    "outlook": "BULLISH/BEARISH/NEUTRAL",
    "confidence": 0-100,
    "reasoning": "2-3 sentences explaining your outlook",
    "key_risks": ["risk1", "risk2"],
    "opportunities": ["opportunity1", "opportunity2"],
    "volatility_forecast": "LOW/MEDIUM/HIGH",
    "recommended_approach": "AGGRESSIVE/MODERATE/CONSERVATIVE"
}}

Focus on:
1. Continuation or reversal of yesterday's trend
2. Impact of global markets
3. News sentiment influence
4. Intraday volatility expectations
5. Best strategies for today (V-Recovery, Momentum, or Pullback)
"""
            
            response = self.claude_client.messages.create(
                model=getattr(self.config, 'AI_MODEL_TOP', "claude-fable-5-1"),
                system="You are a professional Indian stock market analyst specializing in NSE intraday trading. Provide concise, actionable analysis in JSON format.",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=600
            )

            result_text = first_text(response).strip()
            
            # Extract JSON
            import json
            if "```json" in result_text:
                result_text = result_text.split("```json")[1].split("```")[0]
            elif "```" in result_text:
                result_text = result_text.split("```")[1].split("```")[0]
            
            prediction = json.loads(result_text.strip())
            
            logger.info(f"🧠 ChatGPT Prediction: {prediction['outlook']} ({prediction['confidence']}%)")
            logger.info(f"   Reasoning: {prediction['reasoning']}")
            
            return prediction
            
        except Exception as e:
            logger.error(f"ChatGPT prediction failed: {e}")
            return {
                'outlook': 'NEUTRAL',
                'confidence': 50,
                'reasoning': 'Analysis failed - use standard approach',
                'key_risks': [],
                'opportunities': []
            }
    
    
    def _generate_recommendations(
        self,
        yesterday_data: Dict,
        global_data: Dict,
        news_sentiment: Dict,
        ai_prediction: Dict
    ) -> Dict:
        """
        Generate actionable trading recommendations.
        
        Returns:
            {
                'market_outlook': 'BULLISH/BEARISH/NEUTRAL',
                'confidence': 0-100,
                'recommended_strategies': [list],
                'risk_level': 'LOW/MEDIUM/HIGH',
                'key_insights': [list],
                'sector_focus': [list],
                'volatility_expected': 'LOW/MEDIUM/HIGH',
                'position_sizing_advice': str,
                'entry_timing_advice': str
            }
        """
        # Combine all signals
        outlook = ai_prediction['outlook']
        confidence = ai_prediction['confidence']
        
        # Determine recommended strategies
        recommended_strategies = []
        
        if outlook == 'BULLISH':
            if yesterday_data['volatility'] == 'HIGH':
                recommended_strategies = ['V-Recovery', 'Pullback to Value']
            else:
                recommended_strategies = ['Momentum Breakout', 'Pullback to Value']
        
        elif outlook == 'BEARISH':
            recommended_strategies = ['V-Recovery']  # Only reversal plays
        
        else:  # NEUTRAL
            recommended_strategies = ['V-Recovery', 'Pullback to Value']
        
        # Determine risk level
        if yesterday_data['volatility'] == 'HIGH' or confidence < 60:
            risk_level = 'HIGH'
        elif yesterday_data['volatility'] == 'MEDIUM' and confidence >= 70:
            risk_level = 'MEDIUM'
        else:
            risk_level = 'LOW'
        
        # Generate insights
        insights = []
        insights.append(f"Yesterday: NIFTY {yesterday_data['nifty_change']:+.2f}% ({yesterday_data['trend']})")
        insights.append(f"AI Outlook: {outlook} ({confidence}% confidence)")
        insights.append(f"News Sentiment: {news_sentiment['sentiment_label']}")
        
        if ai_prediction.get('reasoning'):
            insights.append(ai_prediction['reasoning'])
        
        # Position sizing advice
        if risk_level == 'LOW' and confidence >= 75:
            position_advice = "Use 2-share positions on high-confidence setups"
        elif risk_level == 'MEDIUM':
            position_advice = "Use 1-share positions, consider 2 on very high scores"
        else:
            position_advice = "Use 1-share positions only, avoid aggressive sizing"
        
        # Entry timing advice
        if outlook == 'BULLISH':
            entry_advice = "Look for pullbacks in uptrend, buy dips early"
        elif outlook == 'BEARISH':
            entry_advice = "Wait for strong V-Recovery patterns, be patient"
        else:
            entry_advice = "Standard approach: RSI 20-35 entry zones"
        
        return {
            'market_outlook': outlook,
            'confidence': confidence,
            'recommended_strategies': recommended_strategies,
            'risk_level': risk_level,
            'key_insights': insights,
            'sector_focus': [],  # TODO: Add sector analysis
            'volatility_expected': yesterday_data['volatility'],
            'position_sizing_advice': position_advice,
            'entry_timing_advice': entry_advice,
            'ai_risks': ai_prediction.get('key_risks', []),
            'ai_opportunities': ai_prediction.get('ai_opportunities', [])
        }
    
    
    def _send_telegram_briefing(self, recommendations: Dict):
        """Send comprehensive pre-market briefing to Telegram."""
        if not self.telegram:
            return
        
        outlook_emoji = {
            'BULLISH': '🟢',
            'BEARISH': '🔴',
            'NEUTRAL': '🟡'
        }
        
        risk_emoji = {
            'LOW': '🟢',
            'MEDIUM': '🟡',
            'HIGH': '🔴'
        }
        
        message = f"""
╔════════════════════════════════════════╗
║  🌅 <b>PRE-MARKET BRIEFING</b>
╚════════════════════════════════════════╝

📅 <b>{datetime.now().strftime('%A, %B %d, %Y')}</b>
🕐 <b>{datetime.now().strftime('%H:%M:%S')}</b>

{outlook_emoji[recommendations['market_outlook']]} <b>MARKET OUTLOOK: {recommendations['market_outlook']}</b>
📊 Confidence: {recommendations['confidence']}%

<b>📋 KEY INSIGHTS:</b>
"""
        
        for i, insight in enumerate(recommendations['key_insights'][:4], 1):
            message += f"{i}. {insight}\n"
        
        message += f"""
<b>🎯 RECOMMENDED STRATEGIES TODAY:</b>
"""
        for strategy in recommendations['recommended_strategies']:
            message += f"  • {strategy}\n"
        
        message += f"""
{risk_emoji[recommendations['risk_level']]} <b>RISK LEVEL: {recommendations['risk_level']}</b>
⚡ Volatility Expected: {recommendations['volatility_expected']}

<b>💡 TRADING ADVICE:</b>
• Position Sizing: {recommendations['position_sizing_advice']}
• Entry Timing: {recommendations['entry_timing_advice']}

<b>⏰ TODAY'S SCHEDULE:</b>
09:15 AM → Market opens
10:00 AM → First scan
01:30 PM → Second scan
02:55 PM → Final scan

<b>🎯 FOCUS:</b>
"""
        
        if recommendations['market_outlook'] == 'BULLISH':
            message += "Look for momentum breakouts and pullback entries\n"
        elif recommendations['market_outlook'] == 'BEARISH':
            message += "Be patient, wait for strong V-Recovery patterns\n"
        else:
            message += "Standard approach, follow the system signals\n"
        
        message += f"""
Good luck today! 💪📈
"""
        
        self.telegram.send_message(message)
        logger.info("✅ Pre-market briefing sent to Telegram")


# ═══════════════════════════════════════════════════════════════════════════
# USAGE EXAMPLE
# ═══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    """Test pre-market analyzer."""
    
    logging.basicConfig(level=logging.INFO)
    
    print("=" * 80)
    print("PRE-MARKET ANALYZER TEST")
    print("=" * 80)
    print()
    print("This module provides daily market intelligence before market opens.")
    print()
    print("Integration: Add to main_orchestrator.py at 8:30 AM")
    print()
    print("=" * 80)
