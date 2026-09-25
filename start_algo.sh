#!/bin/bash
# Starts Algo_Beta on trading days. Safe to run repeatedly (cron does): it exits if the system is
# already running or if it is outside the Mon-Fri 07:45-15:10 start window. DRY_RUN=1 only prints.
cd "$(dirname "$0")" || exit 1
hm=$((10#$(date +%H%M))); dow=$(date +%u)
if [ "$dow" -gt 5 ] || [ "$hm" -lt 745 ] || [ "$hm" -gt 1510 ]; then
  echo "$(date '+%F %T') skip: outside start window (dow=$dow hm=$hm)"; exit 0
fi
exec 9>/tmp/algo_beta_start.lock
flock -n 9 || { echo "$(date '+%F %T') skip: already running (lock held)"; exit 0; }
if pgrep -f "^venv/bin/python main_orchestrator" >/dev/null; then
  echo "$(date '+%F %T') skip: main_orchestrator already running"; exit 0
fi
mkdir -p logs
LOG="logs/run_$(date +%Y%m%d).log"
[ -f "$LOG" ] && mv "$LOG" "logs/run_$(date +%Y%m%d)_$(date +%H%M).log"
if [ -n "$DRY_RUN" ]; then echo "$(date '+%F %T') DRY RUN: would start -> $LOG"; exit 0; fi
echo "$(date '+%F %T') starting main_orchestrator -> $LOG"
nohup venv/bin/python main_orchestrator.py > "$LOG" 2>&1 &
