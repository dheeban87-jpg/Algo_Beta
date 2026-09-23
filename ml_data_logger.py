"""
ML_DATA_LOGGER.PY - Machine Learning Training Data Collection
═══════════════════════════════════════════════════════════════════════════════

This module logs ML training features for every trade.
Integrates seamlessly with backtest_engine.py and main_orchestrator.py.

FEATURES LOGGED:
────────────────────────────────────────────────────────────────────────────────
Entry Features (for XGBoost training):
  ✓ RSI, RSI percentile, RSI slope
  ✓ Volume ratio, volume MA ratio
  ✓ Sentiment score, label, confidence
  ✓ ATR percentage, target %, stop %
  ✓ V-recovery %, recovery quality
  ✓ VWAP distance, MA20 distance, EMA21 distance
  ✓ Time features (hour, minute, day of week)
  ✓ Market context (sector, volatility)

Trade Outcome:
  ✓ Win/loss (1/0)
  ✓ P&L, P&L %
  ✓ Exit reason
  ✓ Duration in minutes
  ✓ Max drawdown during trade
  ✓ Max profit during trade

OUTPUT FILES:
────────────────────────────────────────────────────────────────────────────────
1. data/ml_training/trades_ml.csv      - Training data (XGBoost ready)
2. data/ml_training/trades_ml.json     - Backup JSON format
3. data/ml_training/features_summary.xlsx - Feature statistics

USAGE:
────────────────────────────────────────────────────────────────────────────────
from ml_data_logger import MLDataLogger

# Initialize
ml_logger = MLDataLogger()

# Log trade with features
ml_logger.log_trade_with_features(
    trade=trade_dict,
    signal=signal_dict,  # Entry features
    max_drawdown=-0.5,
    max_profit=3.2
)

Author: Dheebanraj
Version: 2.0.0
Date: 2026-02-12
"""

import os
import csv
import json
import logging
from datetime import datetime
from typing import Dict, Optional, List
import pandas as pd

logger = logging.getLogger('MLDataLogger')


class MLDataLogger:
    """
    Enhanced trade logger that captures ML training features.
    """
    
    def __init__(self, output_dir: str = "data/ml_training"):
        """
        Initialize ML data logger.
        
        Args:
            output_dir: Directory for ML training data
        """
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)
        
        self.csv_file = os.path.join(output_dir, "trades_ml.csv")
        self.json_file = os.path.join(output_dir, "trades_ml.json")
        
        # Create CSV with headers if doesn't exist
        if not os.path.exists(self.csv_file):
            self._create_csv_with_headers()
            logger.info(f"✅ Created ML training CSV: {self.csv_file}")
    
    
    def _create_csv_with_headers(self):
        """Create CSV file with column headers for XGBoost training."""
        headers = [
            # Trade identifiers
            'trade_id', 'symbol', 'date', 'entry_time', 'exit_time',
            
            # Price data
            'entry_price', 'exit_price', 'quantity',
            
            # Outcome (TARGET for XGBoost)
            'pnl', 'pnl_pct', 'win',
            
            # Exit metadata
            'exit_reason', 'duration_minutes',
            
            # Entry features (FEATURES for XGBoost)
            'rsi', 'rsi_percentile', 'rsi_slope',
            'volume_ratio', 'volume_ma_ratio',
            'sentiment_score', 'sentiment_label', 'sentiment_confidence',
            'atr_pct', 'target_pct', 'stop_pct',
            'v_recovery_pct', 'v_recovery_quality',
            'vwap_distance_pct', 'ma20_distance_pct', 'ema21_distance_pct',
            
            # Time features
            'entry_hour', 'entry_minute', 'day_of_week', 'week_of_month',
            
            # Market context
            'sector', 'sector_strength',
            'volatility_regime', 'volatility_multiplier',
            
            # Trade performance metrics
            'max_drawdown_pct', 'max_profit_pct',
            'time_to_max_profit_min', 'time_to_max_drawdown_min',
            
            # System indicators
            'intelligent_score', 'ai_confidence', 
            'finbert_enabled', 'atr_adaptive_enabled'
        ]
        
        with open(self.csv_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(headers)
    
    
    def log_trade_with_features(
        self, 
        trade: Dict, 
        signal: Dict = None,
        max_drawdown: float = 0.0,
        max_profit: float = 0.0,
        time_to_max_profit: int = 0,
        time_to_max_drawdown: int = 0
    ):
        """
        Log trade with all ML training features.
        
        Args:
            trade: Trade dictionary with basic data
            signal: Signal dictionary with entry features
            max_drawdown: Maximum drawdown % during trade
            max_profit: Maximum profit % during trade
            time_to_max_profit: Minutes to reach max profit
            time_to_max_drawdown: Minutes to reach max drawdown
        """
        try:
            # Generate trade ID
            trade_id = f"{trade['symbol']}_{datetime.now().strftime('%Y%m%d%H%M%S')}"
            
            # Parse timestamps — guard against None / NaT which crash strftime
            _now = datetime.now()
            if isinstance(trade.get('entry_time'), str):
                _et = pd.to_datetime(trade['entry_time'])
                entry_time = _now if pd.isna(_et) else _et.to_pydatetime()
            else:
                entry_time = trade.get('entry_time') or _now
                if pd.isna(entry_time) if hasattr(entry_time, '__class__') and 'NaT' in type(entry_time).__name__ else False:
                    entry_time = _now

            if isinstance(trade.get('exit_time'), str):
                _xt = pd.to_datetime(trade['exit_time'])
                exit_time = _now if pd.isna(_xt) else _xt.to_pydatetime()
            else:
                exit_time = trade.get('exit_time') or _now
                if pd.isna(exit_time) if hasattr(exit_time, '__class__') and 'NaT' in type(exit_time).__name__ else False:
                    exit_time = _now

            # Ensure plain datetime objects (not pandas Timestamps) for strftime
            if hasattr(entry_time, 'to_pydatetime'):
                entry_time = entry_time.to_pydatetime()
            if hasattr(exit_time, 'to_pydatetime'):
                exit_time = exit_time.to_pydatetime()

            # Skip phantom trades — near-zero price move means the trade never
            # meaningfully executed; logging it pollutes ML training data.
            _entry_px = trade.get('entry_price', 0) or 0
            _exit_px  = trade.get('exit_price', 0)  or 0
            if _entry_px > 0 and _exit_px > 0:
                _move_pct = abs(_exit_px - _entry_px) / _entry_px * 100
                if _move_pct < 0.01:  # less than 0.01% move = phantom
                    logger.warning(
                        f"[ML] Skipping phantom trade {trade.get('symbol','?')}: "
                        f"entry={_entry_px} exit={_exit_px} move={_move_pct:.4f}%"
                    )
                    return

            # Calculate duration
            duration = (exit_time - entry_time).total_seconds() / 60
            
            # Determine win/loss
            pnl = trade.get('pnl', 0) or trade.get('P&L', 0)
            win = 1 if pnl > 0 else 0
            
            # Extract signal features (if provided)
            if signal is None:
                signal = {}
            
            # Build row data
            row_data = {
                # Identifiers
                'trade_id': trade_id,
                'symbol': trade['symbol'],
                'date': entry_time.strftime('%Y-%m-%d'),
                'entry_time': entry_time.strftime('%Y-%m-%d %H:%M:%S'),
                'exit_time': exit_time.strftime('%Y-%m-%d %H:%M:%S'),
                
                # Price data
                'entry_price': trade.get('entry_price', 0),
                'exit_price': trade.get('exit_price', 0),
                'quantity': trade.get('quantity', 1),
                
                # Outcome
                'pnl': pnl,
                'pnl_pct': trade.get('pnl_pct', 0) or trade.get('P&L %', 0),
                'win': win,
                
                # Exit metadata
                'exit_reason': trade.get('exit_reason', 'UNKNOWN') or trade.get('Exit Reason', 'UNKNOWN'),
                'duration_minutes': int(duration),
                
                # Entry features
                'rsi': signal.get('rsi', signal.get('RSI', 0)),
                'rsi_percentile': signal.get('rsi_percentile', 0),
                'rsi_slope': signal.get('rsi_slope', 0),
                'volume_ratio': signal.get('volume_ratio', signal.get('Volume Ratio', 0)),
                'volume_ma_ratio': signal.get('volume_ma_ratio', 0),
                'sentiment_score': signal.get('sentiment_score', signal.get('Sentiment Score', 0)),
                'sentiment_label': signal.get('sentiment_label', signal.get('Sentiment', '')),
                'sentiment_confidence': signal.get('sentiment_confidence', 0),
                'atr_pct': signal.get('atr_pct', signal.get('ATR %', 0)),
                'target_pct': signal.get('target_pct', 3.5),
                'stop_pct': signal.get('stop_pct', -2.5),
                'v_recovery_pct': signal.get('v_recovery_pct', signal.get('Recovery %', 0)),
                'v_recovery_quality': signal.get('v_recovery_quality', 0),
                'vwap_distance_pct': signal.get('vwap_distance_pct', 0),
                'ma20_distance_pct': signal.get('ma20_distance_pct', 0),
                'ema21_distance_pct': signal.get('ema21_distance_pct', 0),
                
                # Time features
                'entry_hour': entry_time.hour,
                'entry_minute': entry_time.minute,
                'day_of_week': entry_time.weekday(),
                'week_of_month': (entry_time.day - 1) // 7 + 1,
                
                # Market context
                'sector': signal.get('sector', ''),
                'sector_strength': signal.get('sector_strength', 0),
                'volatility_regime': signal.get('volatility_regime', 'NORMAL'),
                'volatility_multiplier': signal.get('volatility_multiplier', 1.0),
                
                # Trade performance
                'max_drawdown_pct': max_drawdown,
                'max_profit_pct': max_profit,
                'time_to_max_profit_min': time_to_max_profit,
                'time_to_max_drawdown_min': time_to_max_drawdown,
                
                # System indicators
                'intelligent_score': signal.get('score', signal.get('Score', 0)),
                'ai_confidence': signal.get('ai_confidence', 0),
                'finbert_enabled': signal.get('finbert_enabled', False),
                'atr_adaptive_enabled': signal.get('atr_adaptive_enabled', False)
            }
            
            # Append to CSV
            with open(self.csv_file, 'a', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=row_data.keys())
                writer.writerow(row_data)
            
            # Also save to JSON (backup)
            self._append_to_json(row_data)
            
            logger.info(f"📊 ML features logged: {trade['symbol']} "
                       f"(RSI: {row_data['rsi']:.1f}, "
                       f"Volume: {row_data['volume_ratio']:.2f}x, "
                       f"Score: {row_data['intelligent_score']})")
            
        except Exception as e:
            logger.error(f"❌ ML logging error: {e}")
            import traceback
            traceback.print_exc()
    
    
    def _append_to_json(self, row_data: Dict):
        """Append trade data to JSON file (backup format)."""
        try:
            # Load existing data
            if os.path.exists(self.json_file):
                with open(self.json_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
            else:
                data = []
            
            # Append new trade
            data.append(row_data)
            
            # Save back
            with open(self.json_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)
                
        except Exception as e:
            logger.warning(f"JSON backup failed: {e}")
    
    
    def export_feature_summary(self) -> Optional[str]:
        """
        Export feature summary statistics to Excel.
        
        Returns:
            Path to Excel file or None if failed
        """
        try:
            if not os.path.exists(self.csv_file):
                logger.warning("No ML training data to summarize")
                return None
            
            # Load data
            df = pd.read_csv(self.csv_file)
            
            if len(df) == 0:
                logger.warning("ML training data is empty")
                return None
            
            # Create summary Excel
            excel_file = os.path.join(self.output_dir, "features_summary.xlsx")
            
            with pd.ExcelWriter(excel_file, engine='openpyxl') as writer:
                # Sheet 1: Overall statistics
                df.describe().to_excel(writer, sheet_name='Overall Stats')
                
                # Sheet 2: Winners vs Losers
                winners = df[df['win'] == 1].describe()
                losers = df[df['win'] == 0].describe()
                
                comparison = pd.DataFrame({
                    'Winners': winners.loc['mean'],
                    'Losers': losers.loc['mean'],
                    'Difference': winners.loc['mean'] - losers.loc['mean']
                })
                comparison.to_excel(writer, sheet_name='Winners vs Losers')
                
                # Sheet 3: Feature correlation with win
                numeric_cols = df.select_dtypes(include=['number']).columns
                correlations = df[numeric_cols].corr()['win'].sort_values(ascending=False)
                correlations.to_excel(writer, sheet_name='Feature Importance')
                
                # Sheet 4: Raw data
                df.to_excel(writer, sheet_name='Raw Data', index=False)
            
            logger.info(f"✅ Feature summary saved: {excel_file}")
            return excel_file
            
        except Exception as e:
            logger.error(f"❌ Feature summary export failed: {e}")
            return None
    
    
    def get_training_data(self) -> pd.DataFrame:
        """
        Load ML training data as DataFrame.
        
        Returns:
            DataFrame ready for XGBoost training
        """
        if not os.path.exists(self.csv_file):
            logger.warning("No ML training data found")
            return pd.DataFrame()
        
        return pd.read_csv(self.csv_file)
    
    
    def get_feature_columns(self) -> List[str]:
        """Get list of feature columns for ML training."""
        return [
            'rsi', 'rsi_percentile', 'rsi_slope',
            'volume_ratio', 'volume_ma_ratio',
            'sentiment_score', 'sentiment_confidence',
            'atr_pct', 'v_recovery_pct',
            'vwap_distance_pct', 'ma20_distance_pct',
            'entry_hour', 'day_of_week',
            'sector_strength', 'volatility_multiplier',
            'intelligent_score'
        ]
    
    
    def get_label_column(self) -> str:
        """Get label column name for ML training."""
        return 'win'
    
    
    def get_stats(self) -> Dict:
        """
        Get summary statistics of collected data.
        
        Returns:
            Dictionary with statistics
        """
        try:
            if not os.path.exists(self.csv_file):
                return {'total_trades': 0, 'status': 'No data yet'}
            
            df = pd.read_csv(self.csv_file)
            
            wins = df[df['win'] == 1]
            losses = df[df['win'] == 0]
            
            stats = {
                'total_trades': len(df),
                'wins': len(wins),
                'losses': len(losses),
                'win_rate': len(wins) / len(df) * 100 if len(df) > 0 else 0,
                'avg_pnl': df['pnl'].mean(),
                'avg_duration': df['duration_minutes'].mean(),
                'xgboost_ready': len(df) >= 100,
                'trades_needed': max(0, 100 - len(df))
            }
            
            return stats
            
        except Exception as e:
            logger.error(f"Stats calculation error: {e}")
            return {'error': str(e)}


# ═══════════════════════════════════════════════════════════════════════════
# USAGE EXAMPLE
# ═══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    """Test ML data logger."""
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Initialize logger
    ml_logger = MLDataLogger()
    
    # Example trade (from backtest)
    trade = {
        'symbol': 'GODREJCP',
        'quantity': 4,
        'entry_price': 1238.50,
        'exit_price': 1276.25,
        'entry_time': '2026-01-21 15:15:00',
        'exit_time': '2026-01-22 09:15:00',
        'pnl': 42.0,
        'pnl_pct': 0.85,
        'exit_reason': 'MAX_HOLD_TIME'
    }
    
    # Example signal (entry features)
    signal = {
        'symbol': 'GODREJCP',
        'rsi': 32.5,
        'rsi_percentile': 15.2,
        'volume_ratio': 1.8,
        'sentiment_score': 0.65,
        'sentiment_label': 'BULLISH',
        'atr_pct': 2.1,
        'v_recovery_pct': 58.3,
        'score': 75
    }
    
    # Log trade with features
    ml_logger.log_trade_with_features(
        trade=trade,
        signal=signal,
        max_drawdown=-0.5,
        max_profit=3.2
    )
    
    # Get stats
    stats = ml_logger.get_stats()
    print(f"\n📊 ML Data Stats:")
    print(f"   Total trades: {stats['total_trades']}")
    print(f"   Win rate: {stats['win_rate']:.1f}%")
    
    # XGBoost readiness
    if stats['xgboost_ready']:
        xgb_status = 'Yes'
    else:
        trades_needed = stats.get('trades_needed', 0)
        xgb_status = f'No, need {trades_needed} more trades'
    print(f"   XGBoost ready: {xgb_status}")
    
    print("\n✅ ML data logger test complete!")
