#!/bin/bash
# Periodic check for GitHub Actions runner termination conditions
# Called by systemd timer to determine if the instance should shut down

exec >> /tmp/termination-check.log 2>&1

# Source common functions and variables
source /usr/local/bin/runner-common.sh

# File paths for tracking
A="/var/run/github-runner-last-activity"
J="/var/run/github-runner-jobs"
H="/var/run/github-runner-has-run-job"

# Current timestamp
N=$(date +%s)

# Check if any runners are actually running
RUNNER_PROCS=$(pgrep -f "Runner.Listener" | wc -l)
if [ $RUNNER_PROCS -eq 0 ]; then
  # No runner processes, check if we have stale job files
  if ls $J/*.job 2>/dev/null | grep -q .; then
    log "WARNING: Found job files but no runner processes - cleaning up stale jobs"
    rm -f $J/*.job
  fi
fi

# Ensure activity file exists and get its timestamp
[ ! -f "$A" ] && touch "$A"
L=$(stat -c %Y "$A" 2>/dev/null || echo 0)

# Calculate idle time
I=$((N-L))

# Determine grace period based on whether any job has run yet
[ -f "$H" ] && G=${RUNNER_GRACE_PERIOD:-60} || G=${RUNNER_INITIAL_GRACE_PERIOD:-180}

# Count running jobs
R=$(grep -l '"status":"running"' $J/*.job 2>/dev/null | wc -l || echo 0)

# Check if we should terminate
if [ $R -eq 0 ] && [ $I -gt $G ]; then
  log "TERMINATING: idle $I > grace $G"
  deregister_all_runners
  flush_cloudwatch_logs
  debug_sleep_and_shutdown
else
  [ $R -gt 0 ] && log "$R job(s) running" || log "Idle $I/$G sec"
fi
