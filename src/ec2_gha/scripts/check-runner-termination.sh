#!/bin/bash
# Periodic check for GitHub Actions runner termination conditions
# Called by systemd timer to determine if the instance should shut down

exec >> /tmp/termination-check.log 2>&1

# Source common functions and variables
source /usr/local/bin/runner-common.sh

# File paths for tracking
A="$RUNNER_STATE_DIR/last-activity"
J="$RUNNER_STATE_DIR/jobs"
H="$RUNNER_STATE_DIR/has-run-job"

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

# Check job files and update timestamps for active runners
# This creates a heartbeat mechanism to detect stuck/failed job completion
for job_file in $J/*.job; do
  [ -f "$job_file" ] || continue
  if grep -q '"status":"running"' "$job_file" 2>/dev/null; then
    # Extract runner number from job file name (format: RUNID-JOBNAME-RUNNER.job)
    runner_num=$(basename "$job_file" .job | rev | cut -d- -f1 | rev)

    # For a job to be truly running, we need BOTH Listener AND Worker processes
    # Listener alone means the runner is idle/waiting, not actually running a job
    listener_alive=$(pgrep -f "runner-${runner_num}/.*Runner.Listener" 2>/dev/null | wc -l)
    worker_alive=$(pgrep -f "runner-${runner_num}/.*Runner.Worker" 2>/dev/null | wc -l)

    if [ $listener_alive -gt 0 ] && [ $worker_alive -gt 0 ]; then
      # Both processes exist, job is truly running - update heartbeat
      touch "$job_file" 2>/dev/null || true
    elif [ $listener_alive -gt 0 ] && [ $worker_alive -eq 0 ]; then
      # Listener exists but no Worker - job has likely failed/completed but hook couldn't run
      job_age=$((N - $(stat -c %Y "$job_file" 2>/dev/null || echo 0)))
      log "WARNING: Runner $runner_num Listener alive but Worker dead - job likely completed (file age: ${job_age}s)"
      rm -f "$job_file"
      touch "$A"  # Update last activity since we just cleaned up a job
    else
      # No Listener at all - runner is completely dead
      job_age=$((N - $(stat -c %Y "$job_file" 2>/dev/null || echo 0)))
      log "WARNING: Job file $(basename $job_file) exists but runner $runner_num is dead (file age: ${job_age}s)"
      rm -f "$job_file"
    fi
  fi
done

# Now check for stale job files that couldn't be touched (e.g., disk full)
# With polling every ${RUNNER_POLL_INTERVAL:-10}s, files should never be older than ~30s
# If they are, something is preventing the touch (likely disk full)
STALE_THRESHOLD=$((${RUNNER_POLL_INTERVAL:-10} * 3))  # 3x the poll interval
for job_file in $J/*.job; do
  [ -f "$job_file" ] || continue
  if grep -q '"status":"running"' "$job_file" 2>/dev/null; then
    job_age=$((N - $(stat -c %Y "$job_file" 2>/dev/null || echo 0)))
    if [ $job_age -gt $STALE_THRESHOLD ]; then
      log "ERROR: Job file $(basename $job_file) is stale (${job_age}s old, threshold ${STALE_THRESHOLD}s)"
      log "Touch must be failing (disk full?) - removing stale job file"
      rm -f "$job_file"
    fi
  fi
done

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
