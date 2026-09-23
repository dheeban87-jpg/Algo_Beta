"""
PHASE 4 HOLDING MONITOR v5.0.0 - CNC Holdings OBSERVE_ONLY Mode
═══════════════════════════════════════════════════════════════════════════════

New module for v5.0.0 SSOT architecture.
Handles CNC holdings in OBSERVE_ONLY mode - P&L display only, no control.

CNC Holdings vs MIS Positions:
- CNC Holdings: Inventory, you OWN the shares, T+1 settlement
  -> OBSERVE_ONLY: P&L monitoring, NO TCAS, NO ILS, NO exits
  
- MIS Positions: Margin-backed, must close by 3:20 PM
  -> ACTIVE_CONTROL: Full TCAS, ILS, predictive stops, exits

This prevents the "ADANIPORTS false positive" bug.

Author: Trading System v5.0.0
Date: 2026-02-06
"""

import logging
from datetime import datetime
from typing import Dict, List, Optional
from dataclasses import dataclass

logger = logging.getLogger('Phase4_HoldingMonitor')


@dataclass
class HoldingRecord:
    """CNC Holding record for OBSERVE_ONLY monitoring"""
    symbol: str
    quantity: int
    quantity_settled: int = 0
    quantity_t1: int = 0
    avg_price: float = 0.0
    last_price: float = 0.0
    pnl: float = 0.0
    pnl_pct: float = 0.0
    phase4_mode: str = 'OBSERVE_ONLY'
    source: str = 'BROKER_ADOPTED'
    added_at: str = ""
    last_updated: str = ""
    
    def __post_init__(self):
        if not self.added_at:
            self.added_at = datetime.now().isoformat()
        if not self.last_updated:
            self.last_updated = self.added_at
        if self.quantity_settled == 0 and self.quantity_t1 == 0:
            self.quantity_settled = self.quantity
    
    def to_dict(self) -> Dict:
        return {
            'symbol': self.symbol,
            'quantity': self.quantity,
            'quantity_settled': self.quantity_settled,
            'quantity_t1': self.quantity_t1,
            'avg_price': self.avg_price,
            'last_price': self.last_price,
            'pnl': self.pnl,
            'pnl_pct': self.pnl_pct,
            'phase4_mode': self.phase4_mode,
            'source': self.source,
            'added_at': self.added_at,
            'last_updated': self.last_updated
        }


class HoldingMonitor:
    """
    v5.0.0: CNC Holding Monitor - OBSERVE_ONLY Mode
    
    Monitors CNC holdings for P&L display only.
    NO control actions are taken:
    - NO TCAS alerts
    - NO ILS guidance
    - NO predictive stops
    - NO exit execution
    - NO capital release tracking
    """
    
    def __init__(self, telegram=None):
        self.holdings: Dict[str, HoldingRecord] = {}
        self.telegram = telegram
        
        logger.info("=" * 60)
        logger.info("PHASE 4 HOLDING MONITOR v5.0.0")
        logger.info("   Mode: OBSERVE_ONLY (P&L display only)")
        logger.info("   NO TCAS, NO ILS, NO exits")
        logger.info("=" * 60)
    
    def add_holding(
        self,
        symbol: str,
        quantity: int,
        avg_price: float,
        quantity_settled: int = None,
        quantity_t1: int = None,
        source: str = 'BROKER_ADOPTED'
    ) -> bool:
        if quantity <= 0:
            return False
        
        if quantity_settled is None:
            quantity_settled = quantity
        if quantity_t1 is None:
            quantity_t1 = 0
        
        self.holdings[symbol] = HoldingRecord(
            symbol=symbol,
            quantity=quantity,
            quantity_settled=quantity_settled,
            quantity_t1=quantity_t1,
            avg_price=avg_price,
            source=source
        )
        
        t1_note = f" ({quantity_t1} T+1 pending)" if quantity_t1 > 0 else ""
        logger.info(f"Added CNC holding: {symbol} - {quantity} @ Rs{avg_price:.2f}{t1_note}")
        logger.info(f"   Mode: OBSERVE_ONLY (P&L display only)")
        
        return True
    
    def add_holding_monitor(
        self,
        symbol: str,
        quantity: int,
        avg_price: float,
        phase4_mode: str = 'OBSERVE_ONLY'
    ) -> bool:
        """Alias for add_holding() - compatibility with orchestrator"""
        return self.add_holding(symbol, quantity, avg_price)
    
    def update_prices(self, prices: Dict[str, float]):
        for symbol, holding in self.holdings.items():
            if symbol in prices:
                ltp = prices[symbol]
                holding.last_price = ltp
                holding.pnl = (ltp - holding.avg_price) * holding.quantity
                if holding.avg_price > 0:
                    holding.pnl_pct = ((ltp - holding.avg_price) / holding.avg_price) * 100
                else:
                    holding.pnl_pct = 0
                holding.last_updated = datetime.now().isoformat()
    
    def update_holding(
        self,
        symbol: str,
        quantity: int = None,
        quantity_settled: int = None,
        quantity_t1: int = None
    ) -> bool:
        if symbol not in self.holdings:
            return False
        
        holding = self.holdings[symbol]
        
        if quantity is not None:
            holding.quantity = quantity
        if quantity_settled is not None:
            holding.quantity_settled = quantity_settled
        if quantity_t1 is not None:
            holding.quantity_t1 = quantity_t1
        
        holding.last_updated = datetime.now().isoformat()
        
        logger.info(f"Updated holding: {symbol} - {holding.quantity} "
                   f"({holding.quantity_settled} settled, {holding.quantity_t1} T+1)")
        
        return True
    
    def remove_holding(self, symbol: str) -> bool:
        if symbol not in self.holdings:
            return True
        
        del self.holdings[symbol]
        logger.info(f"Removed CNC holding: {symbol}")
        
        return True
    
    def get_holding(self, symbol: str) -> Optional[Dict]:
        holding = self.holdings.get(symbol)
        return holding.to_dict() if holding else None
    
    def get_all_status(self) -> Dict[str, Dict]:
        return {symbol: h.to_dict() for symbol, h in self.holdings.items()}
    
    def get_total_pnl(self) -> float:
        return sum(h.pnl for h in self.holdings.values())
    
    def get_holdings_count(self) -> int:
        return len(self.holdings)
    
    def has_holding(self, symbol: str) -> bool:
        return symbol in self.holdings
    
    def get_symbols(self) -> List[str]:
        return list(self.holdings.keys())
    
    def log_status(self):
        if not self.holdings:
            logger.info("No CNC holdings being monitored")
            return
        
        logger.info("-" * 60)
        logger.info(f"CNC HOLDINGS STATUS ({len(self.holdings)} holdings)")
        logger.info("-" * 60)
        
        total_pnl = 0
        for symbol, holding in self.holdings.items():
            pnl_emoji = "+" if holding.pnl > 0 else "-" if holding.pnl < 0 else " "
            t1_note = f" ({holding.quantity_t1} T+1)" if holding.quantity_t1 > 0 else ""
            
            logger.info(
                f"   {pnl_emoji} {symbol}: {holding.quantity}{t1_note} @ "
                f"Rs{holding.avg_price:.2f} -> Rs{holding.last_price:.2f} "
                f"({holding.pnl_pct:+.2f}%) [OBSERVE_ONLY]"
            )
            total_pnl += holding.pnl
        
        logger.info("-" * 60)
        logger.info(f"   Total Holdings P&L: Rs{total_pnl:,.2f}")
        logger.info("-" * 60)
    
    def get_telegram_status(self) -> str:
        if not self.holdings:
            return "No CNC holdings"
        
        lines = [f"CNC HOLDINGS ({len(self.holdings)})"]
        lines.append("-" * 25)
        
        total_pnl = 0
        for symbol, holding in self.holdings.items():
            pnl_emoji = "+" if holding.pnl > 0 else "-" if holding.pnl < 0 else " "
            lines.append(f"{pnl_emoji} {symbol}: {holding.quantity} @ Rs{holding.avg_price:.2f}")
            lines.append(f"   -> Rs{holding.last_price:.2f} ({holding.pnl_pct:+.1f}%)")
            total_pnl += holding.pnl
        
        lines.append("-" * 25)
        lines.append(f"Total P&L: Rs{total_pnl:,.0f}")
        lines.append("Mode: OBSERVE_ONLY")
        
        return "\n".join(lines)
