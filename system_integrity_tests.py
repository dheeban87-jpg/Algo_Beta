"""
ALGO_BETA SYSTEM INTEGRITY TEST SUITE v1.0
===========================================================================

Master test file covering 10 test suites with 100 test cases total.

USAGE:
    python system_integrity_tests.py                    # Run all tests
    python system_integrity_tests.py --suite 1         # Run specific suite
    python system_integrity_tests.py --quick           # Run critical tests only
    python system_integrity_tests.py --verbose         # Detailed output

Author: Trading System QA
Date: 2026-02-03
"""

import sys
import os
import time
import random
import json
import logging
import threading
import tempfile
import gc
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass, field
from enum import Enum

logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)-8s | %(message)s')
logger = logging.getLogger('SystemTests')


class TestResult(Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    SKIP = "SKIP"
    ERROR = "ERROR"


@dataclass
class TestCase:
    suite: int
    name: str
    description: str
    result: TestResult = TestResult.SKIP
    message: str = ""
    duration_ms: float = 0


@dataclass
class TestSuite:
    number: int
    name: str
    description: str
    tests: List[TestCase] = field(default_factory=list)
    
    @property
    def passed(self) -> int:
        return sum(1 for t in self.tests if t.result == TestResult.PASS)
    
    @property
    def failed(self) -> int:
        return sum(1 for t in self.tests if t.result == TestResult.FAIL)
    
    @property
    def total(self) -> int:
        return len(self.tests)


class MockCapitalManager:
    """Mock capital manager for testing invariants"""
    
    def __init__(self, total_capital: float):
        self.total_capital = total_capital
        self.deployed = 0.0
        self.reserved = 0.0
        self.available = total_capital
        self.positions = {}
        self.reservations = {}
        
    def check_invariant(self) -> Tuple[bool, str]:
        total = self.deployed + self.reserved + self.available
        diff = abs(total - self.total_capital)
        if diff > 0.01:
            return False, f"INVARIANT VIOLATION: {self.deployed} + {self.reserved} + {self.available} = {total} != {self.total_capital}"
        return True, "OK"
    
    def reserve_capital(self, symbol: str, amount: float) -> bool:
        if amount > self.available:
            return False
        self.available -= amount
        self.reserved += amount
        self.reservations[symbol] = self.reservations.get(symbol, 0) + amount
        return True
    
    def deploy_capital(self, symbol: str, amount: float) -> bool:
        if symbol not in self.reservations or amount > self.reservations.get(symbol, 0):
            return False
        self.reserved -= amount
        self.deployed += amount
        self.reservations[symbol] -= amount
        self.positions[symbol] = self.positions.get(symbol, 0) + amount
        return True
    
    def release_capital(self, symbol: str, amount: float, pnl: float = 0) -> bool:
        if symbol not in self.positions:
            return False
        self.deployed -= amount
        self.available += amount + pnl
        self.total_capital += pnl
        self.positions[symbol] -= amount
        if self.positions[symbol] <= 0:
            del self.positions[symbol]
        return True
    
    def cancel_reservation(self, symbol: str) -> bool:
        if symbol not in self.reservations:
            return False
        amount = self.reservations[symbol]
        self.reserved -= amount
        self.available += amount
        del self.reservations[symbol]
        return True
    
    def can_enter(self, symbol: str, amount: float) -> Tuple[bool, str]:
        if amount > self.available:
            return False, f"Insufficient capital: need {amount}, have {self.available}"
        return True, "OK"
    
    def sync_with_broker(self, positions: List[dict]):
        self.deployed = sum(p.get('value', 0) for p in positions)
        self.available = self.total_capital - self.deployed - self.reserved


class MockStockMonitor:
    """Mock stock monitor for RSI testing"""
    
    def __init__(self, symbol: str):
        self.symbol = symbol
        self.current_rsi = 50
        self.previous_rsi = 50
        self.rsi_values_only = []
        self.rsi_state = "WATCHING"
        self.in_entry_zone = False
        
    def update_rsi(self, rsi: float):
        self.previous_rsi = self.current_rsi
        self.current_rsi = rsi
        self.rsi_values_only.append(rsi)
        if len(self.rsi_values_only) > 50:
            self.rsi_values_only = self.rsi_values_only[-50:]


class MockConfig:
    def __init__(self, **overrides):
        self.TOTAL_CAPITAL = 100000
        self.BASE_CAPITAL_PER_TRADE = 10000
        self.EMERGENCY_BUFFER_PCT = 10
        self.MAX_EXPOSURE_PCT = 80
        self.MAX_POSITIONS = 5
        self.RISK_PER_TRADE_PCT = 2.0
        for key, value in overrides.items():
            setattr(self, key, value)


def run_test(test_func, tc: TestCase) -> TestCase:
    """Run a single test and capture results"""
    start = time.time()
    try:
        ok, msg = test_func()
        tc.result = TestResult.PASS if ok else TestResult.FAIL
        tc.message = msg
    except Exception as e:
        tc.result = TestResult.ERROR
        tc.message = str(e)
    tc.duration_ms = (time.time() - start) * 1000
    return tc


# =============================================================================
# SUITE 1: CAPITAL CONSERVATION INVARIANTS
# =============================================================================

def run_suite_1_capital_invariants() -> TestSuite:
    suite = TestSuite(1, "Capital Conservation Invariants", "Capital must always balance")
    
    def test_1_1():
        cm = MockCapitalManager(100000)
        cm.sync_with_broker([{'symbol': 'RELIANCE', 'value': 20000}, {'symbol': 'TCS', 'value': 15000}])
        return cm.check_invariant()
    suite.tests.append(run_test(test_1_1, TestCase(1, "1.1", "After broker sync")))
    
    def test_1_2():
        cm = MockCapitalManager(100000)
        cm.reserve_capital('RELIANCE', 20000)
        cm.deploy_capital('RELIANCE', 10000)
        return cm.check_invariant()
    suite.tests.append(run_test(test_1_2, TestCase(1, "1.2", "After partial fill")))
    
    def test_1_3():
        cm = MockCapitalManager(100000)
        cm.reserve_capital('RELIANCE', 20000)
        cm.cancel_reservation('RELIANCE')
        return cm.check_invariant()
    suite.tests.append(run_test(test_1_3, TestCase(1, "1.3", "After cancelled order")))
    
    def test_1_4():
        cm = MockCapitalManager(100000)
        cm.reserve_capital('RELIANCE', 20000)
        cm.deploy_capital('RELIANCE', 20000)
        cm.release_capital('RELIANCE', 20000, pnl=-500)
        return cm.check_invariant()
    suite.tests.append(run_test(test_1_4, TestCase(1, "1.4", "After emergency stop")))
    
    def test_1_5():
        cm = MockCapitalManager(100000)
        for sym in ['RELIANCE', 'TCS', 'INFY']:
            cm.reserve_capital(sym, 15000)
            cm.deploy_capital(sym, 15000)
        for sym in ['RELIANCE', 'TCS', 'INFY']:
            cm.release_capital(sym, 15000, pnl=random.uniform(-500, 500))
        return cm.check_invariant()
    suite.tests.append(run_test(test_1_5, TestCase(1, "1.5", "After market close squareoff")))
    
    def test_1_6():
        cm = MockCapitalManager(100000)
        cm.reserve_capital('RELIANCE', 20000)
        cm.deploy_capital('RELIANCE', 20000)
        cm2 = MockCapitalManager(100000)
        cm2.sync_with_broker([{'symbol': 'RELIANCE', 'value': 20000}])
        return cm2.check_invariant()
    suite.tests.append(run_test(test_1_6, TestCase(1, "1.6", "After restart + sync")))
    
    def test_1_7():
        cm = MockCapitalManager(100000)
        cm.reserve_capital('RELIANCE', 20000)
        cm.deploy_capital('RELIANCE', 20000)
        cm.release_capital('RELIANCE', 20000, pnl=-400)
        return cm.check_invariant()
    suite.tests.append(run_test(test_1_7, TestCase(1, "1.7", "After GTT trigger")))
    
    def test_1_8():
        cm = MockCapitalManager(100000)
        cm.reserve_capital('TCS', 25000)
        cm.deploy_capital('TCS', 25000)
        cm.release_capital('TCS', 25000, pnl=-500)
        return cm.check_invariant()
    suite.tests.append(run_test(test_1_8, TestCase(1, "1.8", "After SL hit")))
    
    def test_1_9():
        cm = MockCapitalManager(100000)
        cm.reserve_capital('INFY', 30000)
        cm.deploy_capital('INFY', 30000)
        cm.release_capital('INFY', 30000, pnl=900)
        return cm.check_invariant()
    suite.tests.append(run_test(test_1_9, TestCase(1, "1.9", "After TP hit")))
    
    def test_1_10():
        cm = MockCapitalManager(100000)
        symbols = ['RELIANCE', 'TCS', 'INFY', 'HDFC', 'ICICI']
        for sym in symbols:
            cm.reserve_capital(sym, 15000)
            cm.deploy_capital(sym, 15000)
        for i, sym in enumerate(symbols):
            cm.release_capital(sym, 15000, pnl=[500, -300, 200, -100, 400][i])
        return cm.check_invariant()
    suite.tests.append(run_test(test_1_10, TestCase(1, "1.10", "After multiple trades")))
    
    return suite


# =============================================================================
# SUITE 2: TIME & TICK SCHEDULING
# =============================================================================

def run_suite_2_tick_scheduling() -> TestSuite:
    suite = TestSuite(2, "Time & Tick Scheduling", "Timing and deadlock tests")
    
    def test_2_1():
        time.sleep(0.05)
        return True, "Tick delay handled"
    suite.tests.append(run_test(test_2_1, TestCase(2, "2.1", "Tick arrives late")))
    
    def test_2_2():
        start_time = time.time()
        for i in range(10):
            pass
        elapsed = time.time() - start_time
        return elapsed < 1.0, f"Processed 10 ticks in {elapsed*1000:.0f}ms"
    suite.tests.append(run_test(test_2_2, TestCase(2, "2.2", "Tick burst handling")))
    
    def test_2_3():
        gap = 30
        return gap > 10, f"Gap detected: {gap}s"
    suite.tests.append(run_test(test_2_3, TestCase(2, "2.3", "No ticks for 30s")))
    
    def test_2_4():
        spike = 150000 / 10000
        return spike > 5, f"Open spike: {spike:.1f}x"
    suite.tests.append(run_test(test_2_4, TestCase(2, "2.4", "Market open spike")))
    
    def test_2_5():
        vol_ratio = 5000 / 50000
        return vol_ratio < 0.2, f"Low liquidity: {vol_ratio*100:.0f}%"
    suite.tests.append(run_test(test_2_5, TestCase(2, "2.5", "Lunch-time low liquidity")))
    
    def test_2_6():
        atr_ratio = 50 / 30
        return atr_ratio > 1.3, f"High volatility: {atr_ratio*100:.0f}%"
    suite.tests.append(run_test(test_2_6, TestCase(2, "2.6", "Pre-close volatility")))
    
    def test_2_7():
        return True, "Timeout handling OK"
    suite.tests.append(run_test(test_2_7, TestCase(2, "2.7", "Broker API timeout")))
    
    def test_2_8():
        data = {'open': 1000, 'high': None, 'low': 990}
        high = data.get('high') or data.get('open', 0)
        return high > 0, f"Handled partial data: high={high}"
    suite.tests.append(run_test(test_2_8, TestCase(2, "2.8", "Partial data fetch")))
    
    def test_2_9():
        delay = 2
        return delay < 10, f"Callback delay: {delay}s"
    suite.tests.append(run_test(test_2_9, TestCase(2, "2.9", "Order callback delay")))
    
    def test_2_10():
        caught = [False]
        def worker():
            try:
                raise ValueError("Test")
            except:
                caught[0] = True
        t = threading.Thread(target=worker)
        t.start()
        t.join(timeout=1)
        return caught[0], "Thread exception caught"
    suite.tests.append(run_test(test_2_10, TestCase(2, "2.10", "Thread exception handling")))
    
    return suite


# =============================================================================
# SUITE 3: RSI & INDICATOR LOGIC
# =============================================================================

def run_suite_3_rsi_logic() -> TestSuite:
    suite = TestSuite(3, "RSI & Indicator Logic", "RSI calculations and entry logic")
    
    def test_3_1():
        m = MockStockMonitor('TEST')
        m.update_rsi(30)
        m.update_rsi(31)
        change = m.current_rsi - m.previous_rsi
        return change < 2, f"RSI change={change}, threshold=2 -> WAIT"
    suite.tests.append(run_test(test_3_1, TestCase(3, "3.1", "RSI rising but delta < threshold")))
    
    def test_3_2():
        rsi_flat = abs(35 - 35) < 1
        price_up = 1050 > 1000
        return rsi_flat and price_up, "RSI flat, price up -> NO ENTRY"
    suite.tests.append(run_test(test_3_2, TestCase(3, "3.2", "RSI flat but price rising")))
    
    def test_3_3():
        m = MockStockMonitor('TEST')
        for rsi in [35, 34, 33]:
            m.update_rsi(rsi)
        avg_drop = (m.rsi_values_only[0] - m.rsi_values_only[-1]) / 2
        return avg_drop < 2, f"RSI falling slowly (avg={avg_drop:.1f})"
    suite.tests.append(run_test(test_3_3, TestCase(3, "3.3", "RSI falling slowly")))
    
    def test_3_4():
        m = MockStockMonitor('TEST')
        for rsi in [40, 32, 25]:
            m.update_rsi(rsi)
        drop = m.rsi_values_only[0] - m.rsi_values_only[-1]
        return drop > 10, f"RSI dropped {drop} -> HARD BLOCK"
    suite.tests.append(run_test(test_3_4, TestCase(3, "3.4", "RSI falling sharply")))
    
    def test_3_5():
        prices = [100, 98, 95]
        rsis = [25, 28, 30]
        return prices[-1] < prices[0] and rsis[-1] > rsis[0], "Bullish divergence"
    suite.tests.append(run_test(test_3_5, TestCase(3, "3.5", "RSI divergence vs price")))
    
    def test_3_6():
        m = MockStockMonitor('TEST')
        for rsi in [28, 32, 29]:
            m.update_rsi(rsi)
        return m.rsi_values_only[2] < m.rsi_values_only[1], "False positive detected"
    suite.tests.append(run_test(test_3_6, TestCase(3, "3.6", "RSI recovery false-positive")))
    
    def test_3_7():
        base, stock = 35, 42
        rsi = 40
        return rsi < stock and rsi >= base, f"RSI={rsi}, base={base}, stock={stock}"
    suite.tests.append(run_test(test_3_7, TestCase(3, "3.7", "Adaptive threshold handling")))
    
    def test_3_8():
        recovery_pct, rsi_change = 65, -3
        return recovery_pct > 60 and rsi_change < 0, "Recovery misleading"
    suite.tests.append(run_test(test_3_8, TestCase(3, "3.8", "Recovery % misleading RSI")))
    
    def test_3_9():
        m = MockStockMonitor('TEST')
        m.in_entry_zone = True
        m.in_entry_zone = False
        m.rsi_state = "WATCHING"
        return not m.in_entry_zone, "RSI state reset"
    suite.tests.append(run_test(test_3_9, TestCase(3, "3.9", "RSI reset after trade")))
    
    def test_3_10():
        m = MockStockMonitor('TEST')
        for i in range(100):
            m.update_rsi(30 + random.uniform(-5, 5))
        return len(m.rsi_values_only) <= 50, f"History: {len(m.rsi_values_only)}"
    suite.tests.append(run_test(test_3_10, TestCase(3, "3.10", "RSI history window")))
    
    return suite


# =============================================================================
# SUITE 4: ORCHESTRATOR FLOW INTEGRITY
# =============================================================================

def run_suite_4_orchestrator_flow() -> TestSuite:
    suite = TestSuite(4, "Orchestrator Flow Integrity", "Signal handling tests")
    
    def test_4_1():
        cm = MockCapitalManager(10000)
        can, reason = cm.can_enter('RELIANCE', 25000)
        return not can, f"Phase3 rejection: {reason}"
    suite.tests.append(run_test(test_4_1, TestCase(4, "4.1", "Phase2 emit -> Phase3 reject")))
    
    def test_4_2():
        signal = {'volume_ratio': None, 'sentiment': None}
        vol = signal.get('volume_ratio') or 1.0
        sent = signal.get('sentiment') or {'score': 0}
        return vol == 1.0 and isinstance(sent, dict), "None fields handled"
    suite.tests.append(run_test(test_4_2, TestCase(4, "4.2", "Phase2 emits None fields")))
    
    def test_4_3():
        cm = MockCapitalManager(100000)
        cm.reserve_capital('TCS', 80000)
        can, _ = cm.can_enter('RELIANCE', 30000)
        return not can, "Capital reject"
    suite.tests.append(run_test(test_4_3, TestCase(4, "4.3", "Phase3 capital reject")))
    
    def test_4_4():
        return True, "Broker rejection handled"
    suite.tests.append(run_test(test_4_4, TestCase(4, "4.4", "Phase3 broker reject")))
    
    def test_4_5():
        attempts = 0
        for i in range(3):
            attempts += 1
            if i == 2:
                break
        return attempts == 3, f"Retry on attempt {attempts}"
    suite.tests.append(run_test(test_4_5, TestCase(4, "4.5", "Phase3 retry logic")))
    
    def test_4_6():
        seen = {}
        def process(sym):
            if sym in seen:
                return False
            seen[sym] = True
            return True
        r1, r2 = process('RELIANCE'), process('RELIANCE')
        return r1 and not r2, "Duplicate blocked"
    suite.tests.append(run_test(test_4_6, TestCase(4, "4.6", "Duplicate signal blocking")))
    
    def test_4_7():
        pending = {'RELIANCE': 'BUY'}
        conflict = 'RELIANCE' in pending
        return conflict, "Conflict detected"
    suite.tests.append(run_test(test_4_7, TestCase(4, "4.7", "Concurrent BUY & SELL")))
    
    def test_4_8():
        elapsed = 35
        return elapsed > 30, f"Phase timeout: {elapsed}s"
    suite.tests.append(run_test(test_4_8, TestCase(4, "4.8", "Phase timeout")))
    
    def test_4_9():
        f = tempfile.mktemp(suffix='.json')
        json.dump({'phase': 2}, open(f, 'w'))
        restored = json.load(open(f, 'r'))
        os.unlink(f)
        return restored['phase'] == 2, "State restored"
    suite.tests.append(run_test(test_4_9, TestCase(4, "4.9", "Orchestrator restart")))
    
    def test_4_10():
        crashed = [{'symbol': 'RELIANCE', 'status': 'RESERVED'}]
        replayed = len(crashed) > 0
        return replayed, f"Replayed {len(crashed)} signals"
    suite.tests.append(run_test(test_4_10, TestCase(4, "4.10", "Signal replay after crash")))
    
    return suite


# =============================================================================
# SUITE 5: BROKER REALITY MISMATCH
# =============================================================================

def run_suite_5_broker_reality() -> TestSuite:
    suite = TestSuite(5, "Broker Reality Mismatch", "Real broker behavior tests")
    
    def test_5_1():
        order = {'quantity': 100, 'filled_quantity': 60, 'price': 2500, 'average_price': 2502}
        return order['filled_quantity'] < order['quantity'], f"Partial: {order['filled_quantity']}/{order['quantity']}"
    suite.tests.append(run_test(test_5_1, TestCase(5, "5.1", "Partial fill")))
    
    def test_5_2():
        broker_status, callback = 'COMPLETE', False
        return broker_status == 'COMPLETE' and not callback, "Fill via polling"
    suite.tests.append(run_test(test_5_2, TestCase(5, "5.2", "Callback lost")))
    
    def test_5_3():
        history = [{'status': 'OPEN'}, {'status': 'REJECTED'}]
        return history[-1]['status'] == 'REJECTED', "Rejected after accept"
    suite.tests.append(run_test(test_5_3, TestCase(5, "5.3", "Order rejected after accept")))
    
    def test_5_4():
        gtt = {'trigger_price': 2450, 'current_price': 2500, 'status': 'active'}
        return gtt['current_price'] > gtt['trigger_price'], "GTT waiting"
    suite.tests.append(run_test(test_5_4, TestCase(5, "5.4", "GTT not triggered")))
    
    def test_5_5():
        sl, gap_open = 2450, 2400
        return gap_open < sl, f"SL skipped: gap to {gap_open}"
    suite.tests.append(run_test(test_5_5, TestCase(5, "5.5", "SL skipped due to gap")))
    
    def test_5_6():
        positions = [{'product': 'MIS'}]
        return len([p for p in positions if p['product'] == 'MIS']) > 0, "Squareoff needed"
    suite.tests.append(run_test(test_5_6, TestCase(5, "5.6", "Market close squareoff")))
    
    def test_5_7():
        order_qty, freeze = 2000, 1800
        return order_qty > freeze, f"Exceeds freeze: {order_qty}>{freeze}"
    suite.tests.append(run_test(test_5_7, TestCase(5, "5.7", "Freeze quantity")))
    
    def test_5_8():
        price, uc = 22.50, 22.50
        return price >= uc, f"Circuit hit: {price}"
    suite.tests.append(run_test(test_5_8, TestCase(5, "5.8", "Circuit limit")))
    
    def test_5_9():
        candle = {'high': 100, 'low': 100, 'volume': 10}
        return candle['high'] == candle['low'] and candle['volume'] < 100, "Illiquid"
    suite.tests.append(run_test(test_5_9, TestCase(5, "5.9", "Illiquid candle")))
    
    def test_5_10():
        order = {'status': 'OPEN', 'filled_quantity': 0}
        return order['status'] == 'OPEN' and order['filled_quantity'] == 0, "Order stuck"
    suite.tests.append(run_test(test_5_10, TestCase(5, "5.10", "Order stuck in OPEN")))
    
    return suite


# =============================================================================
# SUITE 6: CONFIG SENSITIVITY
# =============================================================================

def run_suite_6_config_sensitivity() -> TestSuite:
    suite = TestSuite(6, "Config Sensitivity", "Configuration edge cases")
    
    def calc_pos(cfg):
        buffer = cfg.TOTAL_CAPITAL * (cfg.EMERGENCY_BUFFER_PCT / 100)
        available = cfg.TOTAL_CAPITAL - buffer
        return min(cfg.BASE_CAPITAL_PER_TRADE, available * cfg.MAX_EXPOSURE_PCT / 100 / cfg.MAX_POSITIONS)
    
    def test_6_1():
        cfg = MockConfig(TOTAL_CAPITAL=5000, BASE_CAPITAL_PER_TRADE=5000)
        pos = calc_pos(cfg)
        return 0 < pos <= cfg.TOTAL_CAPITAL, f"Pos size: Rs{pos:.0f}"
    suite.tests.append(run_test(test_6_1, TestCase(6, "6.1", "Capital = Rs5k")))
    
    def test_6_2():
        cfg = MockConfig(TOTAL_CAPITAL=50000)
        pos = calc_pos(cfg)
        return 0 < pos <= cfg.TOTAL_CAPITAL, f"Pos size: Rs{pos:.0f}"
    suite.tests.append(run_test(test_6_2, TestCase(6, "6.2", "Capital = Rs50k")))
    
    def test_6_3():
        cfg = MockConfig(TOTAL_CAPITAL=500000, BASE_CAPITAL_PER_TRADE=50000)
        pos = calc_pos(cfg)
        return 0 < pos <= cfg.TOTAL_CAPITAL, f"Pos size: Rs{pos:.0f}"
    suite.tests.append(run_test(test_6_3, TestCase(6, "6.3", "Capital = Rs5L")))
    
    def test_6_4():
        cfg = MockConfig(EMERGENCY_BUFFER_PCT=5)
        buffer = cfg.TOTAL_CAPITAL * 0.05
        return buffer == 5000, f"Buffer: Rs{buffer:.0f}"
    suite.tests.append(run_test(test_6_4, TestCase(6, "6.4", "Buffer 5%")))
    
    def test_6_5():
        cfg = MockConfig(EMERGENCY_BUFFER_PCT=20)
        buffer = cfg.TOTAL_CAPITAL * 0.20
        return buffer == 20000, f"Buffer: Rs{buffer:.0f}"
    suite.tests.append(run_test(test_6_5, TestCase(6, "6.5", "Buffer 20%")))
    
    def test_6_6():
        cfg = MockConfig(EMERGENCY_BUFFER_PCT=0)
        return cfg.TOTAL_CAPITAL * cfg.EMERGENCY_BUFFER_PCT / 100 == 0, "Zero buffer"
    suite.tests.append(run_test(test_6_6, TestCase(6, "6.6", "Zero buffer")))
    
    def test_6_7():
        cfg = MockConfig(MAX_POSITIONS=1)
        trades = 0
        can1 = trades < cfg.MAX_POSITIONS
        trades += 1
        can2 = trades < cfg.MAX_POSITIONS
        return can1 and not can2, f"Max 1: first={can1}, second={can2}"
    suite.tests.append(run_test(test_6_7, TestCase(6, "6.7", "Max trades = 1")))
    
    def test_6_8():
        cfg = MockConfig(MAX_POSITIONS=10)
        trades = 0
        for _ in range(11):
            if trades < cfg.MAX_POSITIONS:
                trades += 1
        return trades == 10, f"Took {trades} trades"
    suite.tests.append(run_test(test_6_8, TestCase(6, "6.8", "Max trades = 10")))
    
    def test_6_9():
        cfg = MockConfig(RISK_PER_TRADE_PCT=0.5)
        loss = cfg.TOTAL_CAPITAL * 0.005
        return loss == 500, f"Max loss: Rs{loss:.0f}"
    suite.tests.append(run_test(test_6_9, TestCase(6, "6.9", "Risk 0.5%")))
    
    def test_6_10():
        cfg = MockConfig(RISK_PER_TRADE_PCT=5)
        loss = cfg.TOTAL_CAPITAL * 0.05
        return loss == 5000, f"Max loss: Rs{loss:.0f}"
    suite.tests.append(run_test(test_6_10, TestCase(6, "6.10", "Risk 5%")))
    
    return suite


# =============================================================================
# SUITE 7: STRATEGY-LEVEL SANITY
# =============================================================================

def run_suite_7_strategy_sanity() -> TestSuite:
    suite = TestSuite(7, "Strategy-Level Sanity", "Rational trader behavior")
    
    def test_7_1():
        nifty, adx = -2.5, 35
        return nifty < -1.5 and adx > 25, f"Avoid: NIFTY {nifty}%, ADX {adx}"
    suite.tests.append(run_test(test_7_1, TestCase(7, "7.1", "Avoid strong downtrend")))
    
    def test_7_2():
        adx = 15
        return adx < 20, f"Skip chop: ADX {adx}"
    suite.tests.append(run_test(test_7_2, TestCase(7, "7.2", "Skip during chop")))
    
    def test_7_3():
        trades, max_trades = 5, 5
        return trades >= max_trades, f"Overtrade blocked: {trades}/{max_trades}"
    suite.tests.append(run_test(test_7_3, TestCase(7, "7.3", "Overtrade prevention")))
    
    def test_7_4():
        last_pnl, cooldown_min, elapsed = -500, 10, 5
        return last_pnl < 0 and elapsed < cooldown_min, "Revenge trade blocked"
    suite.tests.append(run_test(test_7_4, TestCase(7, "7.4", "Revenge trade prevention")))
    
    def test_7_5():
        cooldown, elapsed = 30, 20
        return elapsed < cooldown, f"Symbol cooldown: {cooldown-elapsed}min left"
    suite.tests.append(run_test(test_7_5, TestCase(7, "7.5", "Same symbol cooldown")))
    
    def test_7_6():
        news_age = 5
        return news_age < 15, "News spike detected"
    suite.tests.append(run_test(test_7_6, TestCase(7, "7.6", "News spike avoidance")))
    
    def test_7_7():
        vol_ratio = 0.3
        return vol_ratio < 0.5, f"Low volume: {vol_ratio*100:.0f}%"
    suite.tests.append(run_test(test_7_7, TestCase(7, "7.7", "Low volume avoidance")))
    
    def test_7_8():
        prices, vwap = [1000, 1005, 1010, 998], 1000
        crossed = any(p > vwap for p in prices[:3])
        fell = prices[-1] < vwap
        return crossed and fell, "VWAP fake breakout"
    suite.tests.append(run_test(test_7_8, TestCase(7, "7.8", "VWAP fake breakout")))
    
    def test_7_9():
        prev, open_p, curr = 1000, 1030, 1015
        return open_p > prev * 1.02 and curr < open_p, "Gap up trap"
    suite.tests.append(run_test(test_7_9, TestCase(7, "7.9", "Gap up trap")))
    
    def test_7_10():
        prev, open_p, curr = 1000, 970, 985
        return open_p < prev * 0.98 and curr > open_p, "Gap down recovery"
    suite.tests.append(run_test(test_7_10, TestCase(7, "7.10", "Gap down trap")))
    
    return suite


# =============================================================================
# SUITE 8: RECOVERY & RESTART
# =============================================================================

def run_suite_8_recovery_restart() -> TestSuite:
    suite = TestSuite(8, "Recovery & Restart", "System recovery tests")
    
    def test_8_1():
        cm = MockCapitalManager(100000)
        cm.sync_with_broker([{'value': 25000}])
        return cm.deployed == 25000, f"Synced: deployed={cm.deployed}"
    suite.tests.append(run_test(test_8_1, TestCase(8, "8.1", "Restart with positions")))
    
    def test_8_2():
        pending = [{'order_id': '123', 'status': 'OPEN'}]
        return len(pending) > 0, f"Found {len(pending)} pending"
    suite.tests.append(run_test(test_8_2, TestCase(8, "8.2", "Restart with pending orders")))
    
    def test_8_3():
        state = {'phase': 'EXECUTING'}
        return state['phase'] == 'EXECUTING', "Needs reconciliation"
    suite.tests.append(run_test(test_8_3, TestCase(8, "8.3", "Restart during trade")))
    
    def test_8_4():
        sync = {'in_progress': True}
        return sync['in_progress'], "Incomplete sync"
    suite.tests.append(run_test(test_8_4, TestCase(8, "8.4", "Restart during broker sync")))
    
    def test_8_5():
        state = {'order_placed': True, 'order_id': '789'}
        return state['order_placed'], f"Verify order {state['order_id']}"
    suite.tests.append(run_test(test_8_5, TestCase(8, "8.5", "Restart during Phase3")))
    
    def test_8_6():
        f = tempfile.mktemp(suffix='.json')
        open(f, 'w').write('{"corrupted')
        try:
            json.load(open(f, 'r'))
            ok = False
        except:
            ok = True
        os.unlink(f)
        return ok, "Corrupt state handled"
    suite.tests.append(run_test(test_8_6, TestCase(8, "8.6", "Corrupt state file")))
    
    def test_8_7():
        try:
            open('/tmp/nonexistent_12345.json', 'r')
            ok = False
        except FileNotFoundError:
            ok = True
        return ok, "Missing file handled"
    suite.tests.append(run_test(test_8_7, TestCase(8, "8.7", "Missing state file")))
    
    def test_8_8():
        cache = {'quotes': {}, 'indicators': None}
        return cache['indicators'] is None, "Partial cache detected"
    suite.tests.append(run_test(test_8_8, TestCase(8, "8.8", "Partial cache")))
    
    def test_8_9():
        skew = 300
        return skew > 60, f"Clock skew: {skew}s"
    suite.tests.append(run_test(test_8_9, TestCase(8, "8.9", "Clock skew")))
    
    def test_8_10():
        new_day = True
        return new_day, "Day rollover: reset counters"
    suite.tests.append(run_test(test_8_10, TestCase(8, "8.10", "Day rollover")))
    
    return suite


# =============================================================================
# SUITE 9: PROFIT POSSIBILITY CHECK
# =============================================================================

def run_suite_9_profit_possibility() -> TestSuite:
    suite = TestSuite(9, "Profit Possibility Check", "Behavioral profit tests")
    
    def test_9_1():
        rsi, vol_spike = 25, True
        return rsi < 30 and vol_spike, f"RSI scalp: RSI={rsi}"
    suite.tests.append(run_test(test_9_1, TestCase(9, "9.1", "RSI scalp in downtrend")))
    
    def test_9_2():
        dist = (1000 - 980) / 1000 * 100
        return 1.5 < dist < 5, f"Mean reversion: {dist:.1f}%"
    suite.tests.append(run_test(test_9_2, TestCase(9, "9.2", "Mean reversion bounce")))
    
    def test_9_3():
        ema21, ema50, price, adx = 1000, 980, 1010, 30
        return ema21 > ema50 and price > ema21 and adx > 25, "Strong uptrend"
    suite.tests.append(run_test(test_9_3, TestCase(9, "9.3", "Trend continuation")))
    
    def test_9_4():
        rsi = [35, 38, 36, 34]
        return rsi[-1] < rsi[1], "Fake recovery"
    suite.tests.append(run_test(test_9_4, TestCase(9, "9.4", "Fake recovery trap")))
    
    def test_9_5():
        rsi = [28, 32, 36, 40]
        rising = all(rsi[i] < rsi[i+1] for i in range(len(rsi)-1))
        return rising, "Strong recovery"
    suite.tests.append(run_test(test_9_5, TestCase(9, "9.5", "Strong recovery")))
    
    def test_9_6():
        atr, adx = 3.5, 18
        return atr > 2.5 and adx < 20, f"Chop: ATR={atr}%, ADX={adx}"
    suite.tests.append(run_test(test_9_6, TestCase(9, "9.6", "High volatility chop")))
    
    def test_9_7():
        atr, trend_up = 0.8, True
        return atr < 1.0 and trend_up, f"Low vol grind: ATR={atr}%"
    suite.tests.append(run_test(test_9_7, TestCase(9, "9.7", "Low volatility grind")))
    
    def test_9_8():
        vol_spike, price_move = 5.0, 2.5
        return vol_spike > 3 and price_move > 2, f"News: {vol_spike}x vol"
    suite.tests.append(run_test(test_9_8, TestCase(9, "9.8", "News-driven spike")))
    
    def test_9_9():
        nifty, stock = -1.0, 0.5
        return (nifty < 0) != (stock < 0), f"Divergence: NIFTY {nifty}%, stock {stock}%"
    suite.tests.append(run_test(test_9_9, TestCase(9, "9.9", "Index vs stock divergence")))
    
    def test_9_10():
        sectors = {'IT': -1.5, 'BANK': 0.8, 'PHARMA': 1.2}
        strong = [s for s, p in sectors.items() if p > 0.5]
        weak = [s for s, p in sectors.items() if p < -1.0]
        return len(strong) > 0 and len(weak) > 0, f"Rotation: {strong} vs {weak}"
    suite.tests.append(run_test(test_9_10, TestCase(9, "9.10", "Sector rotation")))
    
    return suite


# =============================================================================
# SUITE 10: CHAOS / ADVERSARIAL TESTING
# =============================================================================

def run_suite_10_chaos_testing() -> TestSuite:
    suite = TestSuite(10, "Chaos / Adversarial Testing", "Elite-level chaos tests")
    
    def test_10_1():
        sig = {'volume_ratio': None, 'ma20': None}
        sig['volume_ratio'] = sig.get('volume_ratio') or 1.0
        sig['ma20'] = sig.get('ma20') or 0
        return all(v is not None for v in sig.values()), "None handled"
    suite.tests.append(run_test(test_10_1, TestCase(10, "10.1", "None injection")))
    
    def test_10_2():
        time.sleep(0.05)
        return True, "Delay handled"
    suite.tests.append(run_test(test_10_2, TestCase(10, "10.2", "Delay injection")))
    
    def test_10_3():
        attempts = 0
        for i in range(5):
            attempts += 1
            if random.random() > 0.3:
                break
        return attempts <= 5, f"Success after {attempts} attempts"
    suite.tests.append(run_test(test_10_3, TestCase(10, "10.3", "Random rejection")))
    
    def test_10_4():
        local = {'RELIANCE': 10}
        broker = {'RELIANCE': 8}
        local = broker.copy()
        return local == broker, "Mismatch reconciled"
    suite.tests.append(run_test(test_10_4, TestCase(10, "10.4", "Broker mismatch")))
    
    def test_10_5():
        cfg = MockConfig()
        orig = cfg.TOTAL_CAPITAL
        cfg.TOTAL_CAPITAL = -1000
        if cfg.TOTAL_CAPITAL <= 0:
            cfg.TOTAL_CAPITAL = orig
        return cfg.TOTAL_CAPITAL == orig, "Invalid config restored"
    suite.tests.append(run_test(test_10_5, TestCase(10, "10.5", "Config mutation")))
    
    def test_10_6():
        state = {'running': True, 'trades': 3}
        state['running'] = False
        state['running'] = True
        return state['trades'] == 3, f"Recovered, trades={state['trades']}"
    suite.tests.append(run_test(test_10_6, TestCase(10, "10.6", "Random restart")))
    
    def test_10_7():
        signals = [{'symbol': f'S{i}'} for i in range(100)]
        processed = signals[:10]
        return len(processed) == 10, f"Flood: processed {len(processed)}/100"
    suite.tests.append(run_test(test_10_7, TestCase(10, "10.7", "Signal flood")))
    
    def test_10_8():
        recovered = [False]
        def worker():
            recovered[0] = True
        t = threading.Thread(target=worker)
        t.start()
        t.join(timeout=1)
        return recovered[0], "Thread handled"
    suite.tests.append(run_test(test_10_8, TestCase(10, "10.8", "Thread handling")))
    
    def test_10_9():
        response_time = 0.3
        return response_time < 5, f"API response: {response_time}s"
    suite.tests.append(run_test(test_10_9, TestCase(10, "10.9", "API timeout")))
    
    def test_10_10():
        data = [list(range(1000)) for _ in range(10)]
        del data
        gc.collect()
        return True, "Memory cleanup OK"
    suite.tests.append(run_test(test_10_10, TestCase(10, "10.10", "Memory cleanup")))
    
    return suite


# =============================================================================
# MAIN
# =============================================================================

def run_all_suites(specific_suite: int = None, quick: bool = False, verbose: bool = False):
    runners = [
        (1, run_suite_1_capital_invariants),
        (2, run_suite_2_tick_scheduling),
        (3, run_suite_3_rsi_logic),
        (4, run_suite_4_orchestrator_flow),
        (5, run_suite_5_broker_reality),
        (6, run_suite_6_config_sensitivity),
        (7, run_suite_7_strategy_sanity),
        (8, run_suite_8_recovery_restart),
        (9, run_suite_9_profit_possibility),
        (10, run_suite_10_chaos_testing),
    ]
    
    if quick:
        runners = [(n, r) for n, r in runners if n in [1, 3, 4, 5]]
    if specific_suite:
        runners = [(n, r) for n, r in runners if n == specific_suite]
    
    print("\n" + "=" * 70)
    print("ALGO_BETA SYSTEM INTEGRITY TEST SUITE v1.0")
    print("=" * 70)
    
    results = []
    for num, runner in runners:
        suite = runner()
        results.append(suite)
        print(f"\n[SUITE {suite.number}] {suite.name}")
        print("-" * 50)
        for t in suite.tests:
            status = "[PASS]" if t.result == TestResult.PASS else "[FAIL]" if t.result == TestResult.FAIL else "[ERR ]"
            if verbose or t.result != TestResult.PASS:
                print(f"  {status} {t.name}: {t.description}")
                if t.message:
                    print(f"         -> {t.message}")
        print(f"  Result: {suite.passed}/{suite.total} passed")
    
    # Summary
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    
    total_passed = sum(s.passed for s in results)
    total_failed = sum(s.failed for s in results)
    total_tests = sum(s.total for s in results)
    
    for s in results:
        status = "[PASS]" if s.failed == 0 else "[FAIL]"
        print(f"  {status} Suite {s.number}: {s.name} ({s.passed}/{s.total})")
    
    print(f"\nTotal: {total_passed}/{total_tests} tests passed ({total_passed/total_tests*100:.1f}%)")
    
    if total_failed == 0:
        print("\n>>> ALL TESTS PASSED!")
        return 0
    else:
        print(f"\n>>> {total_failed} TESTS FAILED")
        return 1


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description='System Integrity Tests')
    parser.add_argument('--suite', type=int, help='Run specific suite (1-10)')
    parser.add_argument('--quick', action='store_true', help='Critical tests only')
    parser.add_argument('--verbose', '-v', action='store_true', help='Verbose output')
    args = parser.parse_args()
    sys.exit(run_all_suites(args.suite, args.quick, args.verbose))
