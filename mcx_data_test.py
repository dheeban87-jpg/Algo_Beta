"""
MCX_DATA_TEST.PY - Phase 7 Step 1: MCX Data Access Verification
================================================================

PURPOSE: Verify Kite Connect API can access MCX market data
         before building the Phase 7 Paper Trading module.

TESTS:
  T1: Download MCX instrument list
  T2: Filter instruments by margin fit (≤₹10,000 capital)
  T3: Live quotes for key commodities
  T4: Historical 5-minute candle data
  T5: WebSocket subscription (30-second tick capture)

RUN: python mcx_data_test.py
     (Run between 3:30 PM - 11:30 PM when MCX is open for live data)
     (Historical data test works anytime)

REQUIRES: Same environment as Algo_Beta (kiteconnect, selenium, pyotp)

Author: Dheebanraj + Claude
Version: 1.0.0
Date: 2026-02-16
"""

import os
import sys
import time
import csv
import json
import logging
import pyotp
import traceback
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

# ─── Logging Setup ────────────────────────────────────────────────────────────

os.makedirs('logs', exist_ok=True)
os.makedirs('data/mcx_test', exist_ok=True)

log_file = f"logs/mcx_data_test_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-7s | %(message)s',
    datefmt='%H:%M:%S',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(log_file, encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)

# ─── Kite Connect Imports ─────────────────────────────────────────────────────

try:
    from kiteconnect import KiteConnect, KiteTicker
    logger.info("✅ kiteconnect imported successfully")
except ImportError:
    logger.error("❌ kiteconnect not installed. Run: pip install kiteconnect")
    sys.exit(1)

# Selenium imports for login
try:
    from selenium import webdriver
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service
    from webdriver_manager.chrome import ChromeDriverManager
    logger.info("✅ selenium imported successfully")
except ImportError:
    logger.error("❌ selenium not installed. Run: pip install selenium webdriver-manager")
    sys.exit(1)


# ═══════════════════════════════════════════════════════════════════════════════
# CONFIGURATION - Uses same credentials as Algo_Beta
# ═══════════════════════════════════════════════════════════════════════════════

# Import from Algo_Beta config if available, else use env vars
try:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from config import Config
    API_KEY = Config.ZERODHA_API_KEY
    API_SECRET = Config.ZERODHA_API_SECRET
    USER_ID = Config.ZERODHA_USER_ID
    PASSWORD = Config.ZERODHA_PASSWORD
    TOTP_SECRET = Config.ZERODHA_TOTP_SECRET
    logger.info("✅ Loaded credentials from Algo_Beta config.py")
except ImportError:
    API_KEY = os.environ.get('ZERODHA_API_KEY', '')
    API_SECRET = os.environ.get('ZERODHA_API_SECRET', '')
    USER_ID = os.environ.get('ZERODHA_USER_ID', '')
    PASSWORD = os.environ.get('ZERODHA_PASSWORD', '')
    TOTP_SECRET = os.environ.get('ZERODHA_TOTP_SECRET', '')
    logger.info("⚠️  Loaded credentials from environment variables")

# Target commodities to test
MCX_TARGET_SYMBOLS = [
    # Affordable (fits ₹9,400 capital)
    'COTTONOIL',    # ~₹714 NRML margin
    'GOLDPETAL',    # ~₹3,348 NRML margin
    # Borderline MIS
    'LEADMINI',     # ~₹7,680 MIS margin
    'CRUDEOILM',    # ~₹9,740 MIS margin
    # Aspirational (need more capital)
    'NATURALGAS',   # For data observation
    'SILVERM',      # For data observation
    'SILVERMIC',    # Micro silver
    'GOLDM',        # Gold mini
    'GOLD',         # Gold main
    'CRUDEOIL',     # Crude main
    'ZINC',         # Base metal
    'LEAD',         # Base metal
    'ALUMINIUM',    # Base metal
    'COPPER',       # Base metal
    'NICKEL',       # Base metal
    'NATGASMINI',   # Natural gas mini
]


# ═══════════════════════════════════════════════════════════════════════════════
# LOGIN - Reuses Algo_Beta's Selenium auth flow
# ═══════════════════════════════════════════════════════════════════════════════

def kite_login() -> Optional[KiteConnect]:
    """Automated Kite login using Selenium (same as main_orchestrator)."""
    
    logger.info("=" * 70)
    logger.info("KITE LOGIN")
    logger.info("=" * 70)
    
    driver = None
    try:
        # Configure headless Chrome
        chrome_options = Options()
        chrome_options.add_argument('--headless')
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--disable-dev-shm-usage')
        chrome_options.add_argument('--disable-gpu')
        chrome_options.add_argument('--window-size=1920,1080')
        chrome_options.add_argument('--disable-extensions')
        chrome_options.add_argument('--disable-logging')
        chrome_options.add_argument('--log-level=3')
        
        logger.info("Starting Chrome headless...")
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=chrome_options)
        
        # Navigate to login
        login_url = f"https://kite.zerodha.com/connect/login?v=3&api_key={API_KEY}"
        driver.get(login_url)
        logger.info("Navigated to Kite login page")
        
        # Fill user ID
        user_input = WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.ID, "userid"))
        )
        user_input.send_keys(USER_ID)
        
        # Fill password
        pwd_input = driver.find_element(By.ID, "password")
        pwd_input.send_keys(PASSWORD)
        
        # Click login
        login_btn = driver.find_element(By.XPATH, "//button[@type='submit']")
        login_btn.click()
        logger.info("Submitted credentials")
        
        # Wait for TOTP field (exact XPath from main_orchestrator)
        totp_input = WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.XPATH, "//input[@type='number' or @type='text'][@inputmode='numeric' or contains(@class,'totp') or @label='External TOTP']"))
        )
        
        # Generate and enter TOTP
        totp = pyotp.TOTP(TOTP_SECRET)
        totp_code = totp.now()
        totp_input.send_keys(totp_code)
        logger.info("Entered TOTP code")
        
        # Wait for redirect with request token
        WebDriverWait(driver, 20).until(
            lambda d: "request_token=" in d.current_url
        )
        
        # Extract request token
        current_url = driver.current_url
        request_token = current_url.split("request_token=")[1].split("&")[0]
        logger.info("✅ Request token obtained")
        
        # Generate access token
        kite = KiteConnect(api_key=API_KEY)
        data = kite.generate_session(request_token, api_secret=API_SECRET)
        access_token = data["access_token"]
        kite.set_access_token(access_token)
        
        logger.info("✅ Access token generated - Kite Connect ready")
        return kite
        
    except Exception as e:
        logger.error(f"❌ Login failed: {e}")
        logger.error(traceback.format_exc())
        # Save debug screenshot
        if driver:
            try:
                os.makedirs('logs/screenshots', exist_ok=True)
                screenshot_path = f"logs/screenshots/mcx_test_login_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
                driver.save_screenshot(screenshot_path)
                logger.error(f"📸 Debug screenshot saved: {screenshot_path}")
                logger.error(f"   Current URL: {driver.current_url}")
            except:
                pass
        return None
        
    finally:
        if driver:
            try:
                driver.quit()
            except:
                pass


# ═══════════════════════════════════════════════════════════════════════════════
# TEST T1: Download MCX Instrument List
# ═══════════════════════════════════════════════════════════════════════════════

def test_t1_instruments(kite: KiteConnect) -> List[Dict]:
    """Download and analyze MCX instrument list."""
    
    logger.info("")
    logger.info("=" * 70)
    logger.info("T1: MCX INSTRUMENT LIST DOWNLOAD")
    logger.info("=" * 70)
    
    try:
        instruments = kite.instruments('MCX')
        logger.info(f"✅ Downloaded {len(instruments)} MCX instruments")
        
        # Categorize by type
        types = {}
        for inst in instruments:
            itype = inst.get('instrument_type', 'UNKNOWN')
            if itype not in types:
                types[itype] = []
            types[itype].append(inst)
        
        logger.info(f"\nInstrument types:")
        for itype, items in sorted(types.items()):
            logger.info(f"  {itype}: {len(items)} instruments")
        
        # Extract unique commodity names
        names = set()
        for inst in instruments:
            name = inst.get('name', '')
            if name:
                names.add(name)
        
        logger.info(f"\nUnique commodity names ({len(names)}):")
        for name in sorted(names):
            logger.info(f"  {name}")
        
        # Find our target symbols - look for FUTURES (nearest expiry)
        logger.info(f"\nTarget symbols search:")
        found_instruments = []
        
        for target in MCX_TARGET_SYMBOLS:
            matches = [i for i in instruments 
                       if target in i['tradingsymbol'] 
                       and i['instrument_type'] == 'FUT']
            
            if matches:
                # Sort by expiry, pick nearest
                matches.sort(key=lambda x: x.get('expiry', ''))
                nearest = matches[0]
                found_instruments.append(nearest)
                logger.info(f"  ✅ {target:15s} → {nearest['tradingsymbol']:30s} "
                           f"| Lot: {nearest['lot_size']:>5} "
                           f"| Tick: {nearest['tick_size']} "
                           f"| Expiry: {nearest.get('expiry', 'N/A')}")
            else:
                logger.info(f"  ❌ {target:15s} → NOT FOUND in MCX futures")
        
        # Save full instrument list to CSV
        csv_path = 'data/mcx_test/mcx_instruments.csv'
        if instruments:
            keys = instruments[0].keys()
            with open(csv_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=keys)
                writer.writeheader()
                writer.writerows(instruments)
            logger.info(f"\n📁 Full instrument list saved: {csv_path}")
        
        return found_instruments
        
    except Exception as e:
        logger.error(f"❌ T1 FAILED: {e}")
        logger.error(traceback.format_exc())
        return []


# ═══════════════════════════════════════════════════════════════════════════════
# TEST T2: Check Margins for Target Instruments
# ═══════════════════════════════════════════════════════════════════════════════

def test_t2_margins(kite: KiteConnect, instruments: List[Dict]) -> Dict:
    """Check margin requirements for target MCX instruments."""
    
    logger.info("")
    logger.info("=" * 70)
    logger.info("T2: MARGIN REQUIREMENTS CHECK")
    logger.info("=" * 70)
    
    capital = 9400  # Current capital
    margin_info = {}
    
    try:
        for inst in instruments:
            symbol = inst['tradingsymbol']
            exchange = 'MCX'
            
            try:
                # Try to get margin for a single lot buy
                margins = kite.order_margins([{
                    "exchange": exchange,
                    "tradingsymbol": symbol,
                    "transaction_type": "BUY",
                    "variety": "regular",
                    "product": "MIS",
                    "order_type": "MARKET",
                    "quantity": inst['lot_size'],
                }])
                
                if margins and len(margins) > 0:
                    margin_data = margins[0]
                    total_margin = margin_data.get('total', 0)
                    
                    # Also check NRML
                    try:
                        nrml_margins = kite.order_margins([{
                            "exchange": exchange,
                            "tradingsymbol": symbol,
                            "transaction_type": "BUY",
                            "variety": "regular",
                            "product": "NRML",
                            "order_type": "MARKET",
                            "quantity": inst['lot_size'],
                        }])
                        nrml_total = nrml_margins[0].get('total', 0) if nrml_margins else 0
                    except:
                        nrml_total = 0
                    
                    fits_mis = "✅" if total_margin <= capital else "❌"
                    fits_nrml = "✅" if nrml_total <= capital else "❌"
                    
                    margin_info[symbol] = {
                        'symbol': symbol,
                        'lot_size': inst['lot_size'],
                        'mis_margin': round(total_margin, 2),
                        'nrml_margin': round(nrml_total, 2),
                        'fits_mis': total_margin <= capital,
                        'fits_nrml': nrml_total <= capital,
                    }
                    
                    logger.info(f"  {symbol:30s} | Lot: {inst['lot_size']:>5} "
                               f"| MIS: ₹{total_margin:>10,.0f} {fits_mis} "
                               f"| NRML: ₹{nrml_total:>10,.0f} {fits_nrml}")
                               
            except Exception as e:
                logger.warning(f"  {symbol:30s} | ⚠️  Margin check failed: {str(e)[:60]}")
                margin_info[symbol] = {
                    'symbol': symbol,
                    'lot_size': inst['lot_size'],
                    'error': str(e)[:100]
                }
            
            time.sleep(0.3)  # Rate limit
        
        # Summary
        tradeable = [s for s, m in margin_info.items() if m.get('fits_mis') or m.get('fits_nrml')]
        logger.info(f"\n📊 MARGIN SUMMARY (Capital: ₹{capital:,})")
        logger.info(f"   Tradeable instruments: {len(tradeable)}/{len(margin_info)}")
        for s in tradeable:
            m = margin_info[s]
            product = "NRML" if m.get('fits_nrml') else "MIS"
            margin = m.get('nrml_margin') if m.get('fits_nrml') else m.get('mis_margin')
            logger.info(f"   ✅ {s} ({product}) - ₹{margin:,.0f}")
        
        # Save margins to CSV
        csv_path = 'data/mcx_test/mcx_margins.csv'
        with open(csv_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=['symbol', 'lot_size', 'mis_margin', 'nrml_margin', 'fits_mis', 'fits_nrml', 'error'])
            writer.writeheader()
            for m in margin_info.values():
                row = {k: m.get(k, '') for k in writer.fieldnames}
                writer.writerow(row)
        logger.info(f"📁 Margin data saved: {csv_path}")
        
        return margin_info
        
    except Exception as e:
        logger.error(f"❌ T2 FAILED: {e}")
        logger.error(traceback.format_exc())
        return {}


# ═══════════════════════════════════════════════════════════════════════════════
# TEST T3: Live Quotes
# ═══════════════════════════════════════════════════════════════════════════════

def test_t3_quotes(kite: KiteConnect, instruments: List[Dict]) -> Dict:
    """Fetch live quotes for MCX instruments."""
    
    logger.info("")
    logger.info("=" * 70)
    logger.info("T3: LIVE MARKET QUOTES")
    logger.info("=" * 70)
    
    now = datetime.now()
    mcx_open = now.replace(hour=9, minute=0, second=0)
    mcx_close = now.replace(hour=23, minute=30, second=0)
    is_market_hours = mcx_open <= now <= mcx_close and now.weekday() < 5
    
    if not is_market_hours:
        logger.warning("⚠️  MCX market may be closed right now")
        logger.warning(f"   Current time: {now.strftime('%H:%M:%S')} | MCX hours: 9:00 AM - 11:30 PM (Mon-Fri)")
        logger.info("   Will still attempt quote fetch (may return last traded data)...")
    
    try:
        # Build quote keys: MCX:SYMBOL
        quote_keys = [f"MCX:{inst['tradingsymbol']}" for inst in instruments]
        
        if not quote_keys:
            logger.warning("No instruments to quote")
            return {}
        
        # Fetch in batches of 10 (API limit)
        all_quotes = {}
        for i in range(0, len(quote_keys), 10):
            batch = quote_keys[i:i+10]
            try:
                quotes = kite.quote(batch)
                all_quotes.update(quotes)
                logger.info(f"  Fetched batch {i//10 + 1}: {len(quotes)} quotes")
            except Exception as e:
                logger.error(f"  Batch {i//10 + 1} failed: {e}")
            time.sleep(0.3)
        
        # Display results
        logger.info(f"\n{'Symbol':30s} | {'LTP':>10s} | {'Open':>10s} | {'High':>10s} | {'Low':>10s} | {'Volume':>10s} | {'OI':>10s}")
        logger.info("-" * 115)
        
        quote_data = {}
        for key, q in all_quotes.items():
            symbol = key.split(':')[1] if ':' in key else key
            ltp = q.get('last_price', 0)
            ohlc = q.get('ohlc', {})
            volume = q.get('volume', 0)
            oi = q.get('oi', 0)
            
            has_data = ltp > 0 or volume > 0
            status = "✅" if has_data else "⚠️ "
            
            logger.info(f"  {status} {symbol:28s} | {ltp:>10.2f} | {ohlc.get('open', 0):>10.2f} | "
                       f"{ohlc.get('high', 0):>10.2f} | {ohlc.get('low', 0):>10.2f} | "
                       f"{volume:>10,} | {oi:>10,}")
            
            quote_data[symbol] = {
                'symbol': symbol,
                'ltp': ltp,
                'open': ohlc.get('open', 0),
                'high': ohlc.get('high', 0),
                'low': ohlc.get('low', 0),
                'close': ohlc.get('close', 0),
                'volume': volume,
                'oi': oi,
                'has_data': has_data,
            }
        
        active = sum(1 for q in quote_data.values() if q['has_data'])
        logger.info(f"\n📊 QUOTE SUMMARY: {active}/{len(quote_data)} instruments with active data")
        
        # Save quotes
        csv_path = f"data/mcx_test/mcx_quotes_{now.strftime('%Y%m%d_%H%M%S')}.csv"
        if quote_data:
            with open(csv_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=list(list(quote_data.values())[0].keys()))
                writer.writeheader()
                writer.writerows(quote_data.values())
            logger.info(f"📁 Quotes saved: {csv_path}")
        
        return quote_data
        
    except Exception as e:
        logger.error(f"❌ T3 FAILED: {e}")
        logger.error(traceback.format_exc())
        return {}


# ═══════════════════════════════════════════════════════════════════════════════
# TEST T4: Historical 5-Minute Candle Data
# ═══════════════════════════════════════════════════════════════════════════════

def test_t4_historical(kite: KiteConnect, instruments: List[Dict]) -> Dict:
    """Fetch historical 5-minute candles for MCX instruments."""
    
    logger.info("")
    logger.info("=" * 70)
    logger.info("T4: HISTORICAL 5-MINUTE CANDLE DATA")
    logger.info("=" * 70)
    
    # Fetch last 5 trading days of 5-min candles
    to_date = datetime.now()
    from_date = to_date - timedelta(days=7)  # 7 calendar days ≈ 5 trading days
    
    logger.info(f"  Period: {from_date.strftime('%Y-%m-%d')} to {to_date.strftime('%Y-%m-%d')}")
    logger.info(f"  Interval: 5minute")
    
    historical_data = {}
    
    for inst in instruments:
        symbol = inst['tradingsymbol']
        token = inst['instrument_token']
        
        try:
            candles = kite.historical_data(
                instrument_token=token,
                from_date=from_date,
                to_date=to_date,
                interval='5minute',
                oi=True  # Include Open Interest
            )
            
            if candles:
                historical_data[symbol] = candles
                
                # Analyze the data
                total = len(candles)
                first = candles[0]['date'] if candles else None
                last = candles[-1]['date'] if candles else None
                
                # Count unique trading days
                days = set()
                for c in candles:
                    d = c['date']
                    if hasattr(d, 'date'):
                        days.add(d.date())
                    else:
                        days.add(str(d)[:10])
                
                # Price range
                highs = [c['high'] for c in candles]
                lows = [c['low'] for c in candles]
                volumes = [c['volume'] for c in candles]
                ois = [c.get('oi', 0) for c in candles]
                
                avg_vol = sum(volumes) / len(volumes) if volumes else 0
                avg_oi = sum(ois) / len(ois) if ois else 0
                
                logger.info(f"  ✅ {symbol:30s} | {total:>5} candles | {len(days)} days "
                           f"| ₹{min(lows):.2f}-{max(highs):.2f} "
                           f"| AvgVol: {avg_vol:,.0f} | AvgOI: {avg_oi:,.0f}")
                
                # Save individual CSV
                csv_path = f"data/mcx_test/candles_{symbol}_{to_date.strftime('%Y%m%d')}.csv"
                with open(csv_path, 'w', newline='', encoding='utf-8') as f:
                    writer = csv.DictWriter(f, fieldnames=['date', 'open', 'high', 'low', 'close', 'volume', 'oi'])
                    writer.writeheader()
                    for c in candles:
                        writer.writerow({
                            'date': c['date'],
                            'open': c['open'],
                            'high': c['high'],
                            'low': c['low'],
                            'close': c['close'],
                            'volume': c['volume'],
                            'oi': c.get('oi', 0),
                        })
                
            else:
                logger.warning(f"  ⚠️  {symbol:30s} | No candle data returned")
                
        except Exception as e:
            logger.error(f"  ❌ {symbol:30s} | Error: {str(e)[:80]}")
        
        time.sleep(0.5)  # Rate limit - historical API is strict
    
    # Summary
    logger.info(f"\n📊 HISTORICAL DATA SUMMARY:")
    logger.info(f"   Instruments with data: {len(historical_data)}/{len(instruments)}")
    total_candles = sum(len(c) for c in historical_data.values())
    logger.info(f"   Total candles fetched: {total_candles:,}")
    logger.info(f"📁 Individual CSVs saved in: data/mcx_test/")
    
    return historical_data


# ═══════════════════════════════════════════════════════════════════════════════
# TEST T5: WebSocket Live Tick Subscription (30-second test)
# ═══════════════════════════════════════════════════════════════════════════════

def test_t5_websocket(kite: KiteConnect, instruments: List[Dict]) -> Dict:
    """Test WebSocket subscription for MCX instruments (30-second capture)."""
    
    logger.info("")
    logger.info("=" * 70)
    logger.info("T5: WEBSOCKET LIVE TICK TEST (30 seconds)")
    logger.info("=" * 70)
    
    now = datetime.now()
    mcx_open = now.replace(hour=9, minute=0, second=0)
    mcx_close = now.replace(hour=23, minute=30, second=0)
    is_market_hours = mcx_open <= now <= mcx_close and now.weekday() < 5
    
    if not is_market_hours:
        logger.warning("⚠️  MCX market is closed - WebSocket test may not receive ticks")
        logger.warning("   Run this test between 9:00 AM - 11:30 PM Mon-Fri for live ticks")
        logger.info("   Proceeding anyway to test connection establishment...")
    
    # Collect token IDs
    tokens = [inst['instrument_token'] for inst in instruments[:10]]  # Limit to 10 for test
    token_map = {inst['instrument_token']: inst['tradingsymbol'] for inst in instruments[:10]}
    
    if not tokens:
        logger.warning("No instrument tokens to subscribe")
        return {}
    
    logger.info(f"  Subscribing to {len(tokens)} MCX tokens...")
    for t in tokens:
        logger.info(f"    Token {t} → {token_map.get(t, 'UNKNOWN')}")
    
    # Tick collection
    tick_data = {
        'ticks_received': 0,
        'symbols_ticked': set(),
        'first_tick_time': None,
        'last_tick_time': None,
        'connected': False,
        'errors': [],
        'sample_ticks': [],
    }
    
    test_duration = 30  # seconds
    start_time = time.time()
    
    def on_ticks(ws, ticks):
        """Handle incoming ticks."""
        now_ts = datetime.now()
        
        for tick in ticks:
            tick_data['ticks_received'] += 1
            token = tick.get('instrument_token')
            symbol = token_map.get(token, f'TOKEN_{token}')
            tick_data['symbols_ticked'].add(symbol)
            
            if tick_data['first_tick_time'] is None:
                tick_data['first_tick_time'] = now_ts
            tick_data['last_tick_time'] = now_ts
            
            # Store first 5 ticks as samples
            if len(tick_data['sample_ticks']) < 5:
                tick_data['sample_ticks'].append({
                    'time': now_ts.strftime('%H:%M:%S.%f'),
                    'symbol': symbol,
                    'ltp': tick.get('last_price', 0),
                    'volume': tick.get('volume_traded', tick.get('volume', 0)),
                    'oi': tick.get('oi', 0),
                })
            
            # Log every 50th tick
            if tick_data['ticks_received'] % 50 == 0:
                logger.info(f"    📡 {tick_data['ticks_received']} ticks received "
                           f"| {len(tick_data['symbols_ticked'])} symbols active")
        
        # Check if test duration exceeded
        if time.time() - start_time > test_duration:
            ws.close()
    
    def on_connect(ws, response):
        """Subscribe to MCX tokens on connect."""
        tick_data['connected'] = True
        logger.info(f"  ✅ WebSocket connected! Subscribing to {len(tokens)} tokens...")
        ws.subscribe(tokens)
        ws.set_mode(ws.MODE_FULL, tokens)
        logger.info(f"  ✅ Subscribed in FULL mode. Listening for {test_duration} seconds...")
    
    def on_close(ws, code, reason):
        """Handle WebSocket close."""
        logger.info(f"  WebSocket closed: code={code}, reason={reason}")
    
    def on_error(ws, code, reason):
        """Handle WebSocket errors."""
        tick_data['errors'].append(f"code={code}, reason={reason}")
        logger.error(f"  ❌ WebSocket error: code={code}, reason={reason}")
    
    try:
        kws = KiteTicker(API_KEY, kite.access_token)
        kws.on_ticks = on_ticks
        kws.on_connect = on_connect
        kws.on_close = on_close
        kws.on_error = on_error
        
        # Connect with timeout
        logger.info(f"  Connecting WebSocket (timeout: {test_duration}s)...")
        
        # Run in a thread with timeout
        import threading
        ws_thread = threading.Thread(target=kws.connect, kwargs={'threaded': False})
        ws_thread.daemon = True
        ws_thread.start()
        
        # Wait for test duration
        ws_thread.join(timeout=test_duration + 5)
        
        # Force close if still running
        try:
            kws.close()
        except:
            pass
        
    except Exception as e:
        logger.error(f"  ❌ WebSocket test error: {e}")
        tick_data['errors'].append(str(e))
    
    # Report results
    logger.info(f"\n📊 WEBSOCKET TEST RESULTS:")
    logger.info(f"   Connected: {'✅ Yes' if tick_data['connected'] else '❌ No'}")
    logger.info(f"   Ticks received: {tick_data['ticks_received']}")
    logger.info(f"   Symbols with ticks: {len(tick_data['symbols_ticked'])}")
    
    if tick_data['symbols_ticked']:
        logger.info(f"   Active symbols: {', '.join(sorted(tick_data['symbols_ticked']))}")
    
    if tick_data['first_tick_time']:
        duration = (tick_data['last_tick_time'] - tick_data['first_tick_time']).total_seconds()
        rate = tick_data['ticks_received'] / max(duration, 0.001)
        logger.info(f"   Tick rate: {rate:.1f} ticks/second")
    
    if tick_data['sample_ticks']:
        logger.info(f"\n   Sample ticks:")
        for t in tick_data['sample_ticks']:
            logger.info(f"     {t['time']} | {t['symbol']:25s} | LTP: {t['ltp']:>10.2f} "
                       f"| Vol: {t['volume']:>10,} | OI: {t['oi']:>10,}")
    
    if tick_data['errors']:
        logger.info(f"\n   Errors: {len(tick_data['errors'])}")
        for e in tick_data['errors'][:3]:
            logger.info(f"     {e}")
    
    return tick_data


# ═══════════════════════════════════════════════════════════════════════════════
# FINAL REPORT
# ═══════════════════════════════════════════════════════════════════════════════

def generate_report(t1_result, t2_result, t3_result, t4_result, t5_result):
    """Generate final test report."""
    
    logger.info("")
    logger.info("=" * 70)
    logger.info("MCX DATA ACCESS TEST REPORT")
    logger.info("=" * 70)
    logger.info(f"  Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("")
    
    results = {
        'T1_Instruments': '✅ PASS' if len(t1_result) > 0 else '❌ FAIL',
        'T2_Margins': '✅ PASS' if len(t2_result) > 0 else '❌ FAIL / ⚠️  SKIP (needs MCX segment?)',
        'T3_Quotes': '✅ PASS' if any(q.get('has_data') for q in t3_result.values()) else '⚠️  NO LIVE DATA (market closed?)',
        'T4_Historical': '✅ PASS' if len(t4_result) > 0 else '❌ FAIL',
        'T5_WebSocket': '✅ PASS' if (isinstance(t5_result, dict) and t5_result.get('connected')) else '⚠️  CHECK (market closed?)',
    }
    
    all_pass = True
    for test, result in results.items():
        status_icon = "✅" if "PASS" in result else "⚠️ " if "SKIP" in result or "NO LIVE" in result or "CHECK" in result else "❌"
        logger.info(f"  {test:20s}: {result}")
        if "FAIL" in result:
            all_pass = False
    
    logger.info("")
    if all_pass:
        logger.info("  🎯 VERDICT: MCX data access CONFIRMED — ready to build Phase 7!")
    else:
        logger.info("  ⚠️  VERDICT: Some tests need attention. Check details above.")
    
    logger.info("")
    logger.info(f"  📁 All test data saved in: data/mcx_test/")
    logger.info(f"  📄 Full log: {log_file}")
    
    # Phase 7 readiness assessment
    logger.info("")
    logger.info("─" * 70)
    logger.info("PHASE 7 READINESS:")
    logger.info("─" * 70)
    
    if len(t1_result) > 0:
        logger.info("  ✅ Can download MCX instruments → Scanner will work")
    
    if len(t4_result) > 0:
        logger.info("  ✅ Can fetch historical candles → Backtesting will work")
    
    if isinstance(t5_result, dict) and t5_result.get('connected'):
        if t5_result.get('ticks_received', 0) > 0:
            logger.info("  ✅ WebSocket receives MCX ticks → Live paper trading will work")
        else:
            logger.info("  ⚠️  WebSocket connects but no ticks (run during MCX hours to confirm)")
    
    t2_any_fit = any(m.get('fits_mis') or m.get('fits_nrml') for m in t2_result.values()) if t2_result else False
    if t2_any_fit:
        logger.info("  ✅ Margin data accessible → Position sizing will work")
    elif t2_result:
        logger.info("  ⚠️  No instruments fit current capital — paper trading still works")
    else:
        logger.info("  ⚠️  Margin check inconclusive — may need MCX segment for order margins")
    
    logger.info("")
    logger.info("=" * 70)
    logger.info("TEST COMPLETE")
    logger.info("=" * 70)
    
    # Save summary JSON
    summary = {
        'test_date': datetime.now().isoformat(),
        'results': results,
        'instruments_found': len(t1_result),
        'margins_checked': len(t2_result),
        'quotes_with_data': sum(1 for q in t3_result.values() if q.get('has_data')),
        'historical_instruments': len(t4_result),
        'websocket_connected': t5_result.get('connected', False) if isinstance(t5_result, dict) else False,
        'websocket_ticks': t5_result.get('ticks_received', 0) if isinstance(t5_result, dict) else 0,
    }
    
    with open('data/mcx_test/test_summary.json', 'w') as f:
        json.dump(summary, f, indent=2, default=str)
    
    return summary


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    """Run all MCX data access tests."""
    
    logger.info("╔══════════════════════════════════════════════════════════════════════╗")
    logger.info("║        MCX DATA ACCESS TEST - Phase 7 Step 1                        ║")
    logger.info("║        Testing Kite Connect API for MCX commodity data               ║")
    logger.info("╚══════════════════════════════════════════════════════════════════════╝")
    logger.info("")
    logger.info(f"  Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info(f"  MCX Hours: 9:00 AM - 11:30 PM (Mon-Fri)")
    
    now = datetime.now()
    mcx_open = now.replace(hour=9, minute=0, second=0)
    mcx_close = now.replace(hour=23, minute=30, second=0)
    is_market_hours = mcx_open <= now <= mcx_close and now.weekday() < 5
    logger.info(f"  Market Status: {'🟢 OPEN' if is_market_hours else '🔴 CLOSED'}")
    logger.info(f"  Note: T1 & T4 (instruments + history) work anytime")
    logger.info(f"        T3 & T5 (quotes + websocket) need market hours for live data")
    logger.info("")
    
    # Step 0: Login
    kite = kite_login()
    if not kite:
        logger.info("")
        logger.info("─" * 70)
        logger.info("FALLBACK: Manual access token entry")
        logger.info("─" * 70)
        logger.info("  Login failed. Possible reasons:")
        logger.info("  1. Algo_Beta is already running (only one session per API key)")
        logger.info("  2. TOTP timing issue")
        logger.info("")
        logger.info("  OPTION A: Stop Algo_Beta first, then re-run this script")
        logger.info("  OPTION B: Paste access token from running Algo_Beta session")
        logger.info("            (Check Algo_Beta logs for 'Access token generated')")
        logger.info("")
        
        token_input = input("  Paste access_token (or press Enter to exit): ").strip()
        if token_input:
            kite = KiteConnect(api_key=API_KEY)
            kite.set_access_token(token_input)
            try:
                profile = kite.profile()
                logger.info(f"  ✅ Token valid! User: {profile.get('user_id')}")
            except Exception as e:
                logger.error(f"  ❌ Invalid token: {e}")
                sys.exit(1)
        else:
            logger.error("  Exiting.")
            sys.exit(1)
    
    # Step 1: Check account profile - what segments are enabled?
    logger.info("")
    logger.info("─" * 70)
    logger.info("ACCOUNT PROFILE CHECK")
    logger.info("─" * 70)
    try:
        profile = kite.profile()
        logger.info(f"  User: {profile.get('user_name', 'N/A')} ({profile.get('user_id', 'N/A')})")
        logger.info(f"  Email: {profile.get('email', 'N/A')}")
        logger.info(f"  Exchanges: {profile.get('exchanges', [])}")
        logger.info(f"  Products: {profile.get('products', [])}")
        logger.info(f"  Order types: {profile.get('order_types', [])}")
        
        exchanges = profile.get('exchanges', [])
        mcx_enabled = 'MCX' in exchanges
        logger.info(f"\n  MCX Segment: {'✅ ENABLED' if mcx_enabled else '❌ NOT ENABLED'}")
        if not mcx_enabled:
            logger.info("  ℹ️  MCX not in your exchange list.")
            logger.info("     Data access (quotes/history) may still work via API.")
            logger.info("     Order placement will need MCX activation via Zerodha Console.")
    except Exception as e:
        logger.error(f"  Profile check failed: {e}")
        mcx_enabled = False
    
    # Check commodity margin
    try:
        margins = kite.margins()
        eq_margin = margins.get('equity', {})
        cm_margin = margins.get('commodity', {})
        logger.info(f"\n  Equity Balance: ₹{eq_margin.get('available', {}).get('live_balance', 0):,.2f}")
        logger.info(f"  Commodity Balance: ₹{cm_margin.get('available', {}).get('live_balance', 0):,.2f}")
    except Exception as e:
        logger.warning(f"  Margin check: {e}")
    
    # Run tests
    t1_result = test_t1_instruments(kite)
    
    # T2: Margins (may fail if MCX not enabled)
    t2_result = test_t2_margins(kite, t1_result) if t1_result else {}
    
    # T3: Live quotes
    t3_result = test_t3_quotes(kite, t1_result) if t1_result else {}
    
    # T4: Historical data
    t4_result = test_t4_historical(kite, t1_result) if t1_result else {}
    
    # T5: WebSocket (only if market hours and we have instruments)
    if t1_result:
        t5_result = test_t5_websocket(kite, t1_result)
    else:
        t5_result = {'connected': False, 'ticks_received': 0}
        logger.info("\n⚠️  Skipping WebSocket test - no instruments found")
    
    # Final report
    summary = generate_report(t1_result, t2_result, t3_result, t4_result, t5_result)
    
    return summary


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        logger.info("\n\n⚠️  Test interrupted by user (Ctrl+C)")
    except Exception as e:
        logger.error(f"\n\n❌ Unexpected error: {e}")
        logger.error(traceback.format_exc())
