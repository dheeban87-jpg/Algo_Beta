"""
Regret Ratio Tracker
====================
Tracks trades that were REJECTED by the system filters (score < 75, RSI neutral, etc.)
and monitors what WOULD have happened if they had been executed.

Purpose: Build hard evidence that rejecting weak trades improves overall P&L.
After 20-30 data points, the regret ratio proves the filter policy is correct.

Usage:
    from regret_tracker import RegretTracker
    tracker = RegretTracker()

    # When a trade is rejected:
    tracker.log_rejected_trade(
        stock="LUPIN",
        phase="Phase5",
        score=66,
        signal="WEAK",
        rejection_reason="SCORE_BELOW_75",
        entry_price=2045.50,
        proposed_stop=2035.00,
        proposed_target=2070.00
    )

    # End of day — update with actual price movement:
    tracker.update_hypothetical_outcome(
        stock="LUPIN",
        date="2026-02-25",
        actual_high=2048.00,
        actual_low=2020.00,
        actual_close=2025.00
    )

    # Generate report:
    tracker.generate_regret_report()
"""

import json
import os
import csv
from datetime import datetime, date


class RegretTracker:
    """Tracks rejected trades and their hypothetical outcomes."""

    def __init__(self, log_dir=None):
        if log_dir is None:
            log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "regret_logs")
        self.log_dir = log_dir
        os.makedirs(self.log_dir, exist_ok=True)

        self.today_file = os.path.join(
            self.log_dir,
            f"regret_{date.today().strftime('%Y%m%d')}.json"
        )
        self.summary_file = os.path.join(self.log_dir, "regret_summary.csv")
        self.today_rejections = self._load_today()

    def _load_today(self):
        if os.path.exists(self.today_file):
            with open(self.today_file, 'r') as f:
                return json.load(f)
        return []

    def _save_today(self):
        with open(self.today_file, 'w') as f:
            json.dump(self.today_rejections, f, indent=2, default=str)

    def log_rejected_trade(self, stock, phase, score, signal,
                           rejection_reason, entry_price,
                           proposed_stop=None, proposed_target=None,
                           rsi_value=None, atr_value=None,
                           extra_context=None):
        """
        Log a trade that was REJECTED by system filters.

        Standard rejection_reason codes:
            - "SCORE_BELOW_75" (Fix 1 - PVAT)
            - "WEAK_SIGNAL_BLOCKED" (Fix 1)
            - "PH2_SCORE_BELOW_75" (Fix 1 - Phase 2)
            - "RSI_NEUTRAL_ZONE" (Fix 3)
            - "STOP_TOO_TIGHT" (Fix 2 - informational)
        """
        rejection = {
            "timestamp": datetime.now().isoformat(),
            "date": date.today().strftime("%Y-%m-%d"),
            "stock": stock,
            "phase": phase,
            "score": score,
            "signal": signal,
            "rejection_reason": rejection_reason,
            "entry_price": entry_price,
            "proposed_stop": proposed_stop,
            "proposed_target": proposed_target,
            "rsi_value": rsi_value,
            "atr_value": atr_value,
            "extra_context": extra_context or {},
            "hypothetical_outcome": None,
            "hypothetical_pnl": None,
            "would_have_hit_stop": None,
            "would_have_hit_target": None,
            "actual_high": None,
            "actual_low": None,
            "actual_close": None
        }

        self.today_rejections.append(rejection)
        self._save_today()

        print(f"[REGRET TRACKER] REJECTED: {stock} | Phase: {phase} | "
              f"Score: {score} | Reason: {rejection_reason} | "
              f"Entry would have been: {entry_price}")

        return rejection

    def update_hypothetical_outcome(self, stock, trade_date,
                                     actual_high, actual_low, actual_close):
        """End-of-day update: What would have happened if we took the trade?"""
        day_file = os.path.join(
            self.log_dir,
            f"regret_{trade_date.replace('-', '')}.json"
        )
        if not os.path.exists(day_file):
            print(f"[REGRET TRACKER] No rejections found for {trade_date}")
            return

        with open(day_file, 'r') as f:
            rejections = json.load(f)

        updated = False
        for r in rejections:
            if r["stock"] == stock and r["date"] == trade_date:
                r["actual_high"] = actual_high
                r["actual_low"] = actual_low
                r["actual_close"] = actual_close

                entry = r["entry_price"]
                stop = r["proposed_stop"]
                target = r["proposed_target"]

                if stop and actual_low <= stop:
                    r["would_have_hit_stop"] = True
                    r["would_have_hit_target"] = False
                    r["hypothetical_pnl"] = stop - entry
                    r["hypothetical_outcome"] = "LOSS"
                elif target and actual_high >= target:
                    r["would_have_hit_stop"] = False
                    r["would_have_hit_target"] = True
                    r["hypothetical_pnl"] = target - entry
                    r["hypothetical_outcome"] = "WIN"
                else:
                    r["would_have_hit_stop"] = False
                    r["would_have_hit_target"] = False
                    r["hypothetical_pnl"] = actual_close - entry
                    r["hypothetical_outcome"] = "WIN" if actual_close > entry else "LOSS"

                updated = True
                print(f"[REGRET TRACKER] Updated {stock} ({trade_date}): "
                      f"Would have been {r['hypothetical_outcome']} "
                      f"({r['hypothetical_pnl']:.2f})")

        if updated:
            with open(day_file, 'w') as f:
                json.dump(rejections, f, indent=2, default=str)

    def generate_regret_report(self, last_n_days=30):
        """
        Generate summary report across all tracked days.

        Returns dict with regret ratio stats proving filter effectiveness.
        """
        all_rejections = []

        for fname in sorted(os.listdir(self.log_dir)):
            if fname.startswith("regret_") and fname.endswith(".json"):
                fpath = os.path.join(self.log_dir, fname)
                with open(fpath, 'r') as f:
                    day_data = json.load(f)
                    all_rejections.extend(day_data)

        if not all_rejections:
            print("[REGRET TRACKER] No data yet. Keep trading!")
            return None

        with_outcomes = [r for r in all_rejections if r["hypothetical_outcome"] is not None]
        without_outcomes = [r for r in all_rejections if r["hypothetical_outcome"] is None]

        total = len(all_rejections)
        evaluated = len(with_outcomes)
        wins = [r for r in with_outcomes if r["hypothetical_outcome"] == "WIN"]
        losses = [r for r in with_outcomes if r["hypothetical_outcome"] == "LOSS"]

        avoided_loss = sum(abs(r["hypothetical_pnl"]) for r in losses)
        missed_profit = sum(r["hypothetical_pnl"] for r in wins)
        net_benefit = avoided_loss - missed_profit

        by_reason = {}
        for r in with_outcomes:
            reason = r["rejection_reason"]
            if reason not in by_reason:
                by_reason[reason] = {"total": 0, "wins": 0, "losses": 0,
                                     "avoided_loss": 0, "missed_profit": 0}
            by_reason[reason]["total"] += 1
            if r["hypothetical_outcome"] == "WIN":
                by_reason[reason]["wins"] += 1
                by_reason[reason]["missed_profit"] += r["hypothetical_pnl"]
            else:
                by_reason[reason]["losses"] += 1
                by_reason[reason]["avoided_loss"] += abs(r["hypothetical_pnl"])

        report = {
            "report_date": datetime.now().isoformat(),
            "total_rejected": total,
            "evaluated": evaluated,
            "pending_evaluation": len(without_outcomes),
            "would_have_won": len(wins),
            "would_have_lost": len(losses),
            "win_rate_if_taken": len(wins) / evaluated * 100 if evaluated > 0 else 0,
            "total_avoided_loss": round(avoided_loss, 2),
            "total_missed_profit": round(missed_profit, 2),
            "net_benefit": round(net_benefit, 2),
            "regret_ratio": round(len(losses) / total * 100, 2) if total > 0 else 0,
            "verdict": "FILTERS WORKING" if net_benefit > 0 else "REVIEW FILTERS",
            "by_reason": by_reason
        }

        print("\n" + "=" * 60)
        print("   REGRET RATIO REPORT")
        print("=" * 60)
        print(f"Total trades rejected:     {total}")
        print(f"Evaluated (EOD data):      {evaluated}")
        print(f"Would have WON:            {len(wins)} ({report['win_rate_if_taken']:.1f}%)")
        print(f"Would have LOST:           {len(losses)} ({100 - report['win_rate_if_taken']:.1f}%)")
        print(f"Total loss AVOIDED:        {avoided_loss:,.2f}")
        print(f"Total profit MISSED:       {missed_profit:,.2f}")
        print(f"NET BENEFIT of filters:    {net_benefit:,.2f}")
        print(f"Regret ratio (% losers):   {report['regret_ratio']}%")
        print(f"Verdict:                   {report['verdict']}")
        print("-" * 60)
        print("Breakdown by rejection reason:")
        for reason, stats in by_reason.items():
            print(f"  {reason}: {stats['total']} rejected "
                  f"({stats['wins']}W/{stats['losses']}L) | "
                  f"Avoided: {stats['avoided_loss']:,.2f} | "
                  f"Missed: {stats['missed_profit']:,.2f}")
        print("=" * 60 + "\n")

        self._append_summary_csv(report)

        return report

    def _append_summary_csv(self, report):
        file_exists = os.path.exists(self.summary_file)

        with open(self.summary_file, 'a', newline='') as f:
            writer = csv.writer(f)
            if not file_exists:
                writer.writerow([
                    "date", "total_rejected", "would_have_won",
                    "would_have_lost", "avoided_loss", "missed_profit",
                    "net_benefit", "regret_ratio", "verdict"
                ])
            writer.writerow([
                date.today().strftime("%Y-%m-%d"),
                report["total_rejected"],
                report["would_have_won"],
                report["would_have_lost"],
                report["total_avoided_loss"],
                report["total_missed_profit"],
                report["net_benefit"],
                report["regret_ratio"],
                report["verdict"]
            ])


# Singleton instance for easy import
_tracker_instance = None

def get_regret_tracker(log_dir=None):
    """Get or create the singleton RegretTracker instance."""
    global _tracker_instance
    if _tracker_instance is None:
        _tracker_instance = RegretTracker(log_dir)
    return _tracker_instance


def log_regret_trade(stock, score, signal, rejection_reason,
                     entry_price=None, phase=None, **kwargs):
    """
    Convenience function -- call from any phase file.

    Usage in phase files:
        from regret_tracker import log_regret_trade
        log_regret_trade("LUPIN", 66, "WEAK", "SCORE_BELOW_75",
                        entry_price=2045.50, phase="Phase5")
    """
    tracker = get_regret_tracker()
    return tracker.log_rejected_trade(
        stock=stock,
        phase=phase or "unknown",
        score=score,
        signal=signal,
        rejection_reason=rejection_reason,
        entry_price=entry_price or 0,
        **kwargs
    )
