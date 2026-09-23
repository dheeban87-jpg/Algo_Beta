# Algo_Beta — System Performance Review
**Generated:** 2026-04-15 | **Period Covered:** Feb 4 – Apr 15, 2026 | **Version:** v4.9.0

---

## Executive Summary

The system is architecturally sound and technically stable — zero errors across 41 logged sessions is a genuine achievement. However, trading performance is currently negative. Of 14 completed exit trades, only 4 were profitable, producing a win rate of 28.6% and a total realised P&L of **−₹1,044.06**. Two GTT-triggered losses (CHOLAFIN and PAYTM, combined −₹1,203.45) are the primary culprit and mask what is otherwise a near-breakeven set of intraday trades. The most urgent action is preventing large overnight losses. Beyond that, signal generation is too cautious, entry quality is too weak, and the regime-switching logic is anchoring too long in HALT/CAUTIOUS modes on days that clearly reward participation.

---

## Trading Statistics (Feb 4 – Apr 15, 2026)

| Metric | Value |
|---|---|
| Total sessions logged | 41 |
| Sessions with at least 1 trade | 10 |
| Sessions with 0 trades (full-day run) | 18 |
| Total exit trades | 14 |
| Wins | 4 (28.6%) |
| Losses | 10 (71.4%) |
| Total P&L | **−₹1,044.06** |
| Average win | +₹86.44 |
| Average loss | −₹138.98 |
| Reward:Risk ratio | **0.62x** (target: ≥1.5x) |
| Expectancy per trade | **−₹74.58** |
| Phase 2 conversion rate | **4.8%** (4 entries / 83 opportunities) |
| Average entry score | 70.0 (range: 67–79) |
| Strong signals executed (≥80) | **0** |

---

## Daily P&L Timeline

| Date | Exits | P&L | Notes |
|---|---|---|---|
| 2026-02-20 | 1 | −₹14.90 | CHATGPT_EXIT on LUPIN |
| 2026-02-23 | 1 | −₹24.70 | Max hold 25min on SRF |
| 2026-02-25 | 4 | −₹14.25 | Best intraday day — 4 trades, 1 win |
| 2026-02-27 | 1 | −₹13.70 | CHATGPT_EXIT on GODREJCP |
| 2026-03-02 | 1 | +₹172.80 | ✅ Best day — COFORGE predictive stop |
| 2026-03-04 | 2 | −₹39.66 | ICICIBANK double exit |
| 2026-03-05 | 1 | +₹156.40 | ✅ COFORGE hard time exit |
| 2026-03-30 | 1 | **−₹559.65** | ⚠️ CHOLAFIN GTT triggered externally |
| 2026-03-31 | 1 | **−₹643.80** | ⚠️ PAYTM GTT triggered externally |
| 2026-04-08 | 1 | −₹62.60 | ICICIBANK breakeven exit |

---

## What Went Well

**1. System stability is excellent.**
Zero errors across all 41 sessions. The system boots cleanly, runs full-day sessions (up to 8+ hours), and shuts down gracefully. This is the foundation everything else builds on, and it's solid.

**2. COFORGE trades proved the strategy works.**
March 2 and March 5 produced +₹172.80 and +₹156.40 respectively — both from the Predictive Stop and hard time exit logic. When the system finds a genuine V-Recovery with momentum, it manages the exit well. These trades validate the core thesis.

**3. Phase 1 scanner is finding real setups.**
The April 9 scan data shows rich technical output per stock — V-Recovery confirmation, weekly EMA alignment, sector checks, trend scoring. The scanner is doing its job. The problem is downstream filtering, not upstream discovery.

**4. Phase 9 (Fund Manager) self-reflection is impressive.**
The journal entries show the system correctly diagnosing its own mistakes in real time. On April 15, it noted: *"Zero trades on a +1.5% Nifty day represents a significant missed opportunity cost"* — and immediately prescribed a regime upgrade for tomorrow. This level of self-awareness in an autonomous system is genuinely valuable.

**5. Predictive Stop is working.**
The two PREDICTIVE_STOP exits (DRREDDY +₹8.20, ICICIBANK +₹8.34) both exited before the trade reversed. This logic is functioning as designed.

**6. Intraday P&L is nearly breakeven without GTT events.**
Strip out the two GTT disasters and the remaining 12 trades total approximately +₹159 P&L. The intraday engine is not far off — it needs tuning, not a rebuild.

---

## What Needs Improvement

### 🔴 Critical: GTT Overnight Losses (−₹1,203.45)

The two biggest losses in the entire period — CHOLAFIN (−₹559.65) and PAYTM (−₹643.80) — were both `GTT_TRIGGERED_EXTERNAL`. These were CNC (delivery) positions held overnight where the broker's Good-Till-Triggered stop order fired. Together they represent 115% of all losses and completely erase the intraday gains.

The issue is not that stop orders fired — stops should fire. The issue is **position sizing on overnight holds is not scaled to account for gap risk**. With a ₹8,500 base capital, a single overnight loss of ₹643 is a 7.6% drawdown from one trade. That is disproportionate.

**Fix:** Add a per-trade maximum loss cap for CNC positions (e.g., ₹150 maximum loss rule). When a GTT stop is placed, verify the stop distance × quantity ≤ ₹150. If not, reduce quantity. This one change would have turned −₹1,203 into approximately −₹300 across those two trades.

---

### 🔴 Critical: Negative Reward:Risk Ratio (0.62x)

The system's average win (₹86.44) is smaller than its average loss (₹138.98). A profitable system requires the opposite — wins should be meaningfully larger than losses. Even at a 40% win rate, a 1.5x R:R ratio produces positive expectancy.

The core problem is that **exit logic is cutting winners too early and letting losers run to their full stop**. DRREDDY was exited at +₹8.20 because "velocity decaying rapidly" — the right call, but the position could have potentially run further. Meanwhile, stops are being hit for full loss amounts.

**Fix:** Review target ATR multiplier settings. The `target_atr_multiplier` appears to be set at 1.0x in CAUTIOUS mode — consider raising to 1.5x–2.0x. Also review whether PREDICTIVE_STOP is exiting too conservatively.

---

### 🟠 High Priority: Signal Starvation (4.8% Phase 2 Conversion)

79 Phase 2 monitoring slots timed out without generating a signal, versus only 4 entries actually executed. A 4.8% conversion rate means the system is watching 20+ stocks per entry. This is too selective.

Looking at the data: on Feb 25, five stocks were monitored simultaneously (ADANIPORTS, GODREJCP, ADANIGREEN, RAMCOCEM, LAURUSLABS) and all five timed out within the same 2-hour window. On Feb 27, nine stocks timed out in rapid succession. The 2-hour Phase 2 window combined with strict RSI zone requirements is the bottleneck.

**Fix:** Extend the Phase 2 monitoring window from 2 hours to 3 hours for V-Recovery candidates (they often consolidate before breaking). Alternatively, consider a "second look" mechanism — if a stock passes Phase 1 twice in the same day, lower its Phase 2 RSI zone threshold by 5 points.

---

### 🟠 High Priority: Weak Entry Quality

75% of recorded entries were classified as WEAK (score 60–69), 25% MODERATE (70–79), and 0% STRONG (≥80). The system is taking trades at the minimum acceptable threshold. Not a single strong signal has been executed in the entire period.

This is partly a regime issue (CAUTIOUS mode blocks many entries) but also suggests the Phase 2 scoring conditions for strong signals are rarely being met simultaneously.

**Fix:** Temporarily raise the minimum execution threshold from 60 to 67 (eliminate WEAK signals entirely). Then diagnose why strong signals (≥80) are never being generated — likely ADX, VWAP, or volume burst conditions are rarely combining in the current market.

---

### 🟠 High Priority: Regime Anchoring (CAUTIOUS/HALT Overstay)

Today (April 15) is the clearest example: Nifty ran +1.5–1.7% intraday with VIX steady at 18.5–18.9. The Fund Manager stayed CAUTIOUS for the entire session, missed every PH5A window, and logged zero trades. The system's own journal called it *"a strategic failure"*.

This is a pattern. Looking at the full dataset, March had 8 zero-trade days in a row (March 6–13). April has had 5 consecutive near-zero days (April 7–13). The regime is not updating fast enough on improving conditions.

**Fix:** Implement a hard regime upgrade trigger in Phase 9: *"If Nifty change > +1.2% for 3 consecutive heartbeats AND VIX < 19.5, FORCE regime to NORMAL and activate PH5A NEUTRAL regardless of prior posture."* The current logic treats CAUTIOUS as a default that requires evidence to exit, when it should be a temporary state with a time-based expiry.

---

### 🟡 Medium Priority: Breakeven Exit Generating Losses (−₹127.20)

Three trades exited via `TIER1_BREAKEVEN_EXIT` with a combined loss of −₹127.20. A breakeven exit should produce approximately ₹0. The losses suggest the breakeven trail is being triggered before the position has actually reached breakeven (likely due to the copy bug in ISSUE-2), or slippage on exit is eating into the breakeven calculation.

The LUPIN exit on Feb 25 is the most concerning: entered at ₹2,257.20, exited at ₹2,265.50 — that is above entry price, yet the P&L is −₹16.60 on 2 shares. Something is wrong with either the entry price reference, the quantity, or the P&L calculation at exit.

**Fix:** This is directly tied to ISSUE-2 (the position copy bug). `breakeven_trail_applied` and `stop_price` mutations written during Tier 1 are being lost because they go to a local copy, not the orchestrator's central store. Fix ISSUE-2 first and this symptom will likely resolve.

---

### 🟡 Medium Priority: ChatGPT Exits All Negative (−₹32.45)

All 3 ChatGPT-driven exits produced losses: LUPIN −₹14.90, ADANIGREEN −₹3.85, GODREJCP −₹13.70. This does not mean ChatGPT integration is wrong — exiting a losing trade is correct. But the pattern of 0/3 correct exits worth examining.

On ADANIGREEN, the exit came 33 minutes after entry (9:40 buy, 10:43 exit) with the stock down ₹3.85. On GODREJCP, the position was held overnight from Feb 25 to Feb 27 — two full days — before ChatGPT advised exit at −₹13.70. A faster exit trigger on this position would have saved approximately ₹10.

**Fix:** Review the ChatGPT exit prompt for overnight CNC positions. It may be too optimistic about recovery potential. Add a session-end rule: if a CNC position is down more than 1% at the 2:30 PM review, the ChatGPT prompt should explicitly flag it as a "close today" candidate rather than defaulting to HOLD.

---

## Code-Level Issues (from Audit Report)

These are known bugs in the codebase that directly affect trading reliability:

**P0 — ISSUE-2: Position copy bug (13 remaining sites).** State mutations (breakeven trail, stop price, trailing active flags, Kalman reversal count) written during Tier 1 monitoring go to local dict copies and are never persisted back to the orchestrator. The system is "forgetting" its own decisions between cycles. The fix — adding `update_position_field()` calls — has been partially done but 13 fallback paths in Tier 2/3 still use direct dict mutation. This is the highest-priority code fix.

**P1 — ISSUE-3: No ATR proximity check in Tier 1.** The infrastructure is already in place (`dist_to_stop` is computed at line 9696, `atr` is in scope at line 9250), but there's no conditional exit logic using it. Adding one check — "if price within 1× ATR of stop, escalate to Tier 2 immediately" — would catch deteriorating positions faster.

**P1 — ISSUE-9: BREAKEVEN_TRAIL_TIME feature flag.** The config flag exists but its behavior in the code path is unclear. Three breakeven exits produced losses, suggesting this logic needs review and the dead flag should be cleaned up.

**P2 — Dual Phase 5 files.** Both `phase5_intraday_engine.py` and `phase5_gap_strategy.py` exist. It's unclear which is canonical. The older file should be archived to prevent confusion and accidental execution of stale logic.

---

## Priority Action Plan

| Priority | Action | Expected Impact |
|---|---|---|
| 1 | Add CNC position max-loss cap (≤₹150/trade) | Prevents catastrophic GTT overnight losses |
| 2 | Fix ISSUE-2 remaining 13 copy bug sites | Fixes breakeven trail, trailing stop, banner P&L |
| 3 | Hard regime upgrade trigger (Nifty >+1.2% × 3 heartbeats + VIX <19.5) | Participates in trending days currently being missed |
| 4 | Raise minimum entry score to 67 (remove WEAK signal execution) | Improves win rate by filtering marginal entries |
| 5 | Add ATR proximity early-exit to Tier 1 (ISSUE-3) | Faster exit before stops are hit |
| 6 | Review CHATGPT_EXIT prompt for overnight CNC positions | Reduces overnight hold losses |
| 7 | Extend Phase 2 monitoring window to 3 hours | Increases signal conversion from 4.8% |
| 8 | Archive `phase5_gap_strategy.py`, confirm canonical Phase 5 | Removes code ambiguity |

---

## Overall Assessment

The system's architecture, stability, and intelligence layer are genuinely impressive for an autonomous trading system at this stage. The Phase 9 Fund Manager's self-reflection quality is particularly notable — it is correctly diagnosing problems in real time. The core V-Recovery strategy is sound and produces good trades when it fires (COFORGE ×2).

The current losses stem from two identifiable, fixable problems: uncontrolled overnight risk (fix with a hard loss cap per position) and excessive regime caution that prevents participation on good days (fix with a hard upgrade trigger). Addressing these two issues alone would likely push the system to breakeven or better on intraday performance. The longer-term improvement path is raising signal quality (entry scores), fixing the copy bug, and extending Phase 2 conversion.

The system is closer to being profitable than the raw P&L suggests. The -₹1,044 headline is almost entirely two anomalous GTT events. Without them, the intraday engine is running at approximately +₹159 across 12 trades — modest but positive, and a foundation to build from.
