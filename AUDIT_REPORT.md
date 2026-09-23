# AUDIT REPORT — AUBANK INCIDENT
Generated: 2026-04-06

---

## SUMMARY TABLE

| Issue | Priority | Status | Confirmed? | Line Numbers |
|-------|----------|--------|------------|--------------|
| ISSUE-1 | P0 | market_protection missing | YES | L7883, L7914 |
| ISSUE-2 | P0 | copy bug — state lost | YES | L1420, L9310, L7688, L7723 |
| ISSUE-3 | P1 | no TCAS proximity in Tier1 | YES | L9226–9714 (absent) |
| ISSUE-4 | P1 | stop distance handoff | PARTIAL | L2531–2540, L2849, L2857, L2959 |
| ISSUE-5 | P2 | EXIT_IN_PROGRESS loop | YES | L7596, L7690, L7725, L1498–1500 |
| ISSUE-6 | P2 | banner P&L stale | PARTIAL | L5984 |
| ISSUE-7 | P3 | target sign display | NOT CONFIRMED | L1908–1909 |

---

## DETAIL PER ISSUE

### ISSUE-1
**Confirmed: YES**

Both exit methods use `self.kite.place_order()` with `ORDER_TYPE_MARKET`. Neither passes `market_protection`. No `requests.post()` raw calls exist in either method.

Evidence:

**`_place_exit_order_internal`** — starts at line 7861, `place_order` call at line 7883:
```python
order_id = self.kite.place_order(
    variety=self.kite.VARIETY_REGULAR, exchange=self.kite.EXCHANGE_NSE,
    tradingsymbol=symbol, transaction_type=kite_transaction, quantity=quantity,
    product=self.kite.PRODUCT_CNC if product == 'CNC' else self.kite.PRODUCT_MIS,
    order_type=self.kite.ORDER_TYPE_MARKET, validity=self.kite.VALIDITY_DAY
)
# market_protection NOT present
```

**`_place_market_order_internal`** — starts at line 7899, `place_order` call at line 7914:
```python
order_id = self.kite.place_order(
    tradingsymbol=symbol, exchange=self.kite.EXCHANGE_NSE,
    transaction_type=transaction_type, quantity=quantity,
    order_type=self.kite.ORDER_TYPE_MARKET,
    product=self.kite.PRODUCT_CNC if product == 'CNC' else self.kite.PRODUCT_MIS,
    variety=self.kite.VARIETY_REGULAR
)
# market_protection NOT present
```

Fix location: Add `market_protection=0.05` (5% buffer, SEBI mandated range) to both `place_order()` calls at lines 7883 and 7914.

---

### ISSUE-2
**Confirmed: YES**

**Phase4.positions property** — line 2204 calls `self.orchestrator.get_all_positions(include_closing=True)`.

**orchestrator.get_all_positions** — line 1420 returns per-position shallow copies:
```python
return {s: p.copy() for s, p in self._central_positions.items()}
```

**State mutations written to local copy (never persisted):**

| Field | Line(s) | Location |
|-------|---------|---------|
| `position['exit_retries'] = retry_count` | 7688, 7723 | `_execute_exit_order` |
| `position['breakeven_trail_applied'] = True` | 9310 | `_run_tier1_fast_check` CHECK 1.7 |
| `position['stop_price'] = entry_price` | 9313, 9331 | `_run_tier1_fast_check` CHECK 1.7 |
| `position['tier1_trailing_active'] = True` | 9471, 9510 | `_run_tier1_fast_check` CHECK 3.5 |
| `position['tier1_kalman_reversal_count']` | 9607, 9611 | `_run_tier1_fast_check` CHECK 3.6 |

`_save_positions()` at line 7691 calls `list(self.positions.values())` — which re-fetches a **fresh copy** every time, so mutations on the local `position` dict are completely discarded.

**`update_position_field` / `write_position` / `set_position_field`** — NONE of these exist in `orchestrator.py`. Only `update_position` (line 1439) exists but is not called from the Tier-1 fast-check path.

Fix location:
- `orchestrator.py` line ~1439 — add `update_position_field(symbol, field, value)` method
- `phase4_portfolio_manager.py` lines 7688, 7723, 9310, 9313, 9331, 9471, 9510, 9607, 9611 — replace direct dict mutations with calls to the new method

---

### ISSUE-3
**Confirmed: YES**

`_run_tier1_fast_check` — lines 9226–9714. All CHECK blocks found:

| Block | Line | Description |
|-------|------|-------------|
| CHECK 1 | 9255 | Hard stop hit via `_is_stop_hit()` |
| CHECK 1.5 | 9275 | Hard exit time deadline |
| CHECK 1.7 | 9299 | Breakeven trail time |
| CHECK 2 | 9347 | Target hit via `_is_target_hit()` |
| CHECK 3 | 9368 | Predictive stop (Kalman) |
| CHECK 3.5 | 9447 | Smart TCAS trailing stop (profit ratchet) |
| CHECK 3.6 | 9557 | Kalman momentum reversal |
| CHECK 4 | 9642 | Max hold time exceeded |
| CHECK 5 | 9674 | MIS mandatory exit |

**CHECK 1 = hard stop only:** `_is_stop_hit` at line 9257 checks `current_price >= stop_price` for SHORT (lines 1946–1947). No ATR proximity calculation.

**Distance_to_stop vs ATR:** `dist_to_stop` is computed at line 9696 but used only for status logging at line 9711 — **not used as an exit trigger anywhere in the method**.

**`_calculate_tcas_status()` called in Tier1:** NO. It is defined at line 4479 and called at line 9973, which is inside `run_monitoring_cycle` (Tier 2 pipeline). It is absent from lines 9226–9714. TCAS alert levels within Tier 1 are computed inline via Kalman velocity heuristics at lines 9416–9430.

**ATR proximity check:** MISSING — no check computes "price within 1× ATR of stop" as an early exit signal.

Fix location: Insert ATR-proximity early-exit block after CHECK 1 at line 9275 (before or alongside CHECK 1.5).

---

### ISSUE-4
**Confirmed: PARTIAL**

**Phase 5 stop formula** (`phase5_intraday_engine.py`):
- `STOP_ATR_MULTIPLIER = 0.5` — line 247
- Pre-fill: `stop_distance = candidate.atr * self.config.STOP_ATR_MULTIPLIER` — line ~2531
- For SHORT: `stop_price = entry_price + stop_distance` — line ~2540 (correct: stop above entry)
- Post-fill recalculation: `stop_price = actual_fill_price + stop_distance` → then `round(stop_price * 20) / 20` — lines ~2582–2589

**Phase 4 `add_phase5_position`** (`phase4_portfolio_manager.py`):
- Default fallback exists: line 2849 → `position_data.get('stop_price', entry_price * 1.015)` — 1.5% flat default if dict is malformed
- Tick rounding: line 2857 → `round(stop_price * 20) / 20`
  - Effect on ₹864.93: `864.93 × 20 = 17298.6 → round = 17299 → / 20 = ₹864.95` (widens by ₹0.02)
- Log statement at handoff: YES — line 2959 → `logger.info(f"      Stop: ₹{stop_price:.2f} | Target: ₹{target_price:.2f}")`

**Why PARTIAL:** The Phase 5 ATR formula is correct and handoff log exists. Tick rounding causes minor widening (+₹0.02 on ₹864.93) which is acceptable. The 1.5% flat fallback at line 2849 would produce a different stop distance than the ATR formula if triggered — but it only fires on malformed handoff data. No structural bug, but the fallback divergence is a silent risk.

Fix location: Add log at line 2849 explicitly warning when the default fallback is used instead of Phase 5 stop_price.

---

### ISSUE-5
**Confirmed: YES**

**`original_status` capture and restore in `phase4_portfolio_manager.py`:**
- Line 7596: `original_status = position.get('status', PositionState.OPEN)` — captured from local copy
- Line 7690: `position['status'] = original_status` — restored on placement failure
- Line 7725: `position['status'] = original_status` — restored on fill failure

Both restores are on the **local copy**. The orchestrator's `_central_positions` is never updated. On the next cycle, `get_all_positions()` returns a fresh copy where `status` is still `OPEN` (as stored in the live dict), so the state machine sees a valid `OPEN → EXIT_IN_PROGRESS` transition and fires again.

**Orchestrator transition guard** — lines 1498–1500:
- Valid map: `'OPEN': ['CLOSING', 'EXIT_IN_PROGRESS', 'CLOSED']`
- Guard logs warning and returns `False` on invalid transition
- However: the guard manages the `'state'` key in `_central_positions`, while `_execute_exit` reads and writes the `'status'` key — these are **different keys, not synchronized**. The guard on `'state'` does not prevent the `'status'` field from being re-mutated on the local copy each cycle.
- **The guard does NOT block re-execution.** It only logs a warning.

Fix location: Dependent on ISSUE-2 fix. Once `update_position_field` exists, set `status = EXIT_IN_PROGRESS` via orchestrator at line 7601, and restore it via orchestrator at lines 7690/7725.

---

### ISSUE-6
**Confirmed: PARTIAL**

**Banner method** (`_log_phase4_status_if_needed`) — lines 5944–6188:
```python
# Lines 5983–5984
entry_price = position.get('entry_price', 0)
current_price = position.get('current_price', entry_price)   # fallback to entry_price
```

Line 5984: `current_price` falls back to `entry_price` if absent from position dict. P&L is then computed via `_calculate_pnl_pct(position, current_price)` at line 5992. If `current_price == entry_price`, P&L = ₹0.00.

**Why PARTIAL:** The fallback exists at line 5984, and the copy bug (ISSUE-2) means `position['current_price']` updates written during monitoring (line ~9797) on local copies are not persisted to the orchestrator. On subsequent banner renders, the position dict from `get_all_positions()` may still lack `current_price`, causing the fallback to fire. This reproduces the ₹+0.00 symptom structurally.

Fix location: Dependent on ISSUE-2 fix. Once write-back is implemented for `current_price` mutations, the fallback will stop firing.

---

### ISSUE-7
**Confirmed: NOT CONFIRMED**

The Tier 1 log line is at lines 9708–9711:
```python
logger.info(
    f"🏎️ TIER1 {symbol}: ₹{current_price:.2f} | {direction} | P&L: {pnl_pct:+.2f}% | "
    f"Target: ₹{dist_to_target:.2f} away ({progress:.0f}%) | "
    f"Stop: ₹{dist_to_stop:.2f} safe{trail_info}{kalman_info}"
)
```

`_calculate_distance_to_target` (lines 1898–1911) is direction-aware:
```python
if direction == 'SHORT':
    return current_price - target_price   # positive = downside remaining
else:
    return target_price - current_price   # positive = upside remaining
```

For SHORT: `current_price - target_price` produces a positive number when price is still above target (i.e., trade has not yet hit profit target). The log format `:.2f` prints it positive. No sign bug found. The claim of "-36%" cannot be reproduced from this code path.

---

## UNEXPECTED FINDINGS

1. **`_save_positions()` re-fetch bug (line 7691):** `_save_positions()` calls `list(self.positions.values())` to get positions for persistence. Since `self.positions` is a property that calls `get_all_positions()` returning fresh copies, any in-flight mutations are silently dropped by the save operation itself. This means persistence is also broken — saved state will always reflect the last durable orchestrator state, not the last in-memory computation.

2. **`'state'` vs `'status'` key divergence (related to ISSUE-5):** `orchestrator.py` manages a `'state'` key via `transition_position_state()`, but `phase4_portfolio_manager.py` reads and writes a `'status'` key throughout its exit logic. These two keys exist independently in the position dict and are never synchronized. The transition guard is effectively monitoring a shadow field that the exit code ignores.

3. **Tier 1 ATR proximity gap (ISSUE-3 extension):** `dist_to_stop` is correctly computed at line 9696 and `atr` is available in scope as of line 9250. The infrastructure for an ATR proximity check is already present — only the conditional exit logic is absent. Adding one line for proximity detection would be low-risk.

4. **Phase 5 double tick-rounding:** Phase 5 applies `round(stop_price * 20) / 20` at line ~2589 before handoff. Phase 4 applies the same rounding again at line 2857 after receiving the value. For most inputs this is idempotent, but if Phase 5's rounded value produces a non-exact float representation (IEEE 754), the Phase 4 re-rounding could produce a different tick. Low risk but worth noting.
