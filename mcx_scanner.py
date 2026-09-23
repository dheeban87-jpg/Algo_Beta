"""
MCX_SCANNER.PY - Phase 7.1: MCX Instrument Scanner
====================================================

Downloads MCX instruments daily, filters by margin fit and liquidity,
and provides the active instrument list for signal generation.

Author: Dheebanraj + Claude
Version: 7.0.0
Date: 2026-02-16
"""

import logging
import time
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import mcx_config as cfg

logger = logging.getLogger(__name__)


class MCXScanner:
    """
    Phase 7.1: Scans MCX instruments and filters by tradability.
    
    Outputs:
        - instruments_paper: All instruments for paper trading (data only)
        - instruments_live:  Instruments within capital for live trading
        - token_map:         instrument_token → symbol mapping for WebSocket
    """
    
    def __init__(self, kite):
        """
        Args:
            kite: Authenticated KiteConnect instance
        """
        self.kite = kite
        self.all_instruments = []
        self.paper_instruments = []    # For paper trading (all with data)
        self.live_instruments = []     # For live trading (capital fits)
        self.token_map = {}            # token → symbol
        self.margin_data = {}          # symbol → margin info
        self.last_scan_time = None
    
    def scan(self) -> Dict:
        """
        Run full MCX instrument scan.
        
        Returns:
            dict with 'paper', 'live', 'token_map', 'scan_time'
        """
        logger.info("")
        logger.info("=" * 70)
        logger.info("PHASE 7.1: MCX INSTRUMENT SCAN")
        logger.info("=" * 70)
        
        start = time.time()
        
        # Step 1: Download all MCX instruments
        self._download_instruments()
        
        # Step 2: Find target futures (nearest expiry)
        self._find_target_futures()
        
        # Step 3: Get live quotes for liquidity filtering
        self._check_liquidity()
        
        # Step 4: Check margins for capital fit
        self._check_margins()
        
        # Step 5: Build final lists
        self._build_lists()
        
        elapsed = time.time() - start
        self.last_scan_time = datetime.now()
        
        logger.info(f"\n📊 SCAN COMPLETE ({elapsed:.1f}s)")
        logger.info(f"   Paper trade instruments: {len(self.paper_instruments)}")
        logger.info(f"   Live trade instruments:  {len(self.live_instruments)}")
        logger.info(f"   WebSocket tokens:        {len(self.token_map)}")
        
        return {
            'paper': self.paper_instruments,
            'live': self.live_instruments,
            'token_map': self.token_map,
            'margin_data': self.margin_data,
            'scan_time': self.last_scan_time,
        }
    
    def _download_instruments(self):
        """Download all MCX instruments from Kite."""
        try:
            self.all_instruments = self.kite.instruments('MCX')
            futures = [i for i in self.all_instruments if i['instrument_type'] == 'FUT']
            logger.info(f"  Downloaded {len(self.all_instruments)} MCX instruments "
                       f"({len(futures)} futures)")
        except Exception as e:
            logger.error(f"  ❌ Failed to download MCX instruments: {e}")
            self.all_instruments = []
    
    def _find_target_futures(self):
        """Find nearest-expiry futures for target symbols."""
        self.paper_instruments = []
        futures = [i for i in self.all_instruments if i['instrument_type'] == 'FUT']
        
        for target in cfg.MCX_PAPER_UNIVERSE:
            matches = [i for i in futures if i['tradingsymbol'].startswith(target)]
            
            if matches:
                # Sort by expiry, pick nearest
                matches.sort(key=lambda x: x.get('expiry', ''))
                nearest = matches[0]
                self.paper_instruments.append(nearest)
                logger.info(f"  ✅ {target:15s} → {nearest['tradingsymbol']:30s} "
                           f"| Expiry: {nearest.get('expiry', 'N/A')}")
            else:
                logger.warning(f"  ❌ {target:15s} → NOT FOUND")
    
    def _check_liquidity(self):
        """Fetch live quotes and filter by minimum liquidity."""
        if not self.paper_instruments:
            return
        
        quote_keys = [f"MCX:{i['tradingsymbol']}" for i in self.paper_instruments]
        
        try:
            # Fetch in batches of 10
            all_quotes = {}
            for idx in range(0, len(quote_keys), 10):
                batch = quote_keys[idx:idx + 10]
                quotes = self.kite.quote(batch)
                all_quotes.update(quotes)
                time.sleep(0.3)
            
            # Filter by liquidity
            liquid = []
            for inst in self.paper_instruments:
                key = f"MCX:{inst['tradingsymbol']}"
                q = all_quotes.get(key, {})
                volume = q.get('volume', 0)
                oi = q.get('oi', 0)
                ltp = q.get('last_price', 0)
                
                inst['_ltp'] = ltp
                inst['_volume'] = volume
                inst['_oi'] = oi
                
                if volume >= cfg.MCX_MIN_VOLUME or oi >= cfg.MCX_MIN_OI:
                    liquid.append(inst)
                    logger.info(f"  💧 {inst['tradingsymbol']:30s} | LTP: {ltp:>10.2f} "
                               f"| Vol: {volume:>8,} | OI: {oi:>8,}")
                else:
                    logger.info(f"  🏜️  {inst['tradingsymbol']:30s} | LTP: {ltp:>10.2f} "
                               f"| Vol: {volume:>8,} | OI: {oi:>8,} (ILLIQUID)")
            
            self.paper_instruments = liquid
            logger.info(f"  Liquid instruments: {len(liquid)}/{len(quote_keys)}")
            
        except Exception as e:
            logger.error(f"  ⚠️  Liquidity check failed: {e} — keeping all instruments")
    
    def _check_margins(self):
        """Check margin requirements for each instrument."""
        self.margin_data = {}
        
        for inst in self.paper_instruments:
            symbol = inst['tradingsymbol']
            try:
                margins = self.kite.order_margins([{
                    "exchange": "MCX",
                    "tradingsymbol": symbol,
                    "transaction_type": "BUY",
                    "variety": "regular",
                    "product": "NRML",
                    "order_type": "MARKET",
                    "quantity": inst['lot_size'],
                }])
                
                if margins:
                    total = margins[0].get('total', 0)
                    self.margin_data[symbol] = {
                        'nrml_margin': round(total, 2),
                        'fits_capital': total <= cfg.MCX_CAPITAL,
                        'lot_size': inst['lot_size'],
                    }
                    
                    fit = "✅" if total <= cfg.MCX_CAPITAL else "  "
                    logger.info(f"  {fit} {symbol:30s} | Margin: ₹{total:>10,.0f} "
                               f"| Lot: {inst['lot_size']}")
                               
            except Exception as e:
                logger.warning(f"  ⚠️  {symbol}: margin check failed ({str(e)[:50]})")
                self.margin_data[symbol] = {'error': str(e)[:100]}
            
            time.sleep(0.3)
    
    def _build_lists(self):
        """Build final instrument lists and token map."""
        self.live_instruments = []
        self.token_map = {}
        
        for inst in self.paper_instruments:
            symbol = inst['tradingsymbol']
            token = inst['instrument_token']
            
            # Token map for WebSocket
            self.token_map[token] = {
                'symbol': symbol,
                'name': inst.get('name', ''),
                'lot_size': inst['lot_size'],
                'tick_size': inst['tick_size'],
                'expiry': str(inst.get('expiry', '')),
                'ltp': inst.get('_ltp', 0),
            }
            
            # Live tradeable check
            margin = self.margin_data.get(symbol, {})
            if margin.get('fits_capital', False):
                self.live_instruments.append(inst)
        
        if self.live_instruments:
            logger.info(f"\n  🎯 LIVE TRADEABLE (fits ₹{cfg.MCX_CAPITAL:,}):")
            for inst in self.live_instruments:
                m = self.margin_data.get(inst['tradingsymbol'], {})
                logger.info(f"     {inst['tradingsymbol']} — ₹{m.get('nrml_margin', 0):,.0f}")
        else:
            logger.info(f"\n  ⚠️  No instruments fit ₹{cfg.MCX_CAPITAL:,} capital")
            logger.info(f"     Paper trading ALL instruments for strategy validation")
    
    def get_websocket_tokens(self) -> List[int]:
        """Return list of instrument tokens for WebSocket subscription."""
        return list(self.token_map.keys())
    
    def get_symbol_for_token(self, token: int) -> Optional[str]:
        """Look up trading symbol from instrument token."""
        info = self.token_map.get(token)
        return info['symbol'] if info else None
    
    def get_tick_size(self, symbol: str) -> float:
        """Get tick size for a symbol."""
        for token, info in self.token_map.items():
            if info['symbol'] == symbol:
                return info['tick_size']
        return 1.0
    
    def get_lot_size(self, symbol: str) -> int:
        """Get lot size for a symbol."""
        for token, info in self.token_map.items():
            if info['symbol'] == symbol:
                return info['lot_size']
        return 1
