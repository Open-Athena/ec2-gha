#!/bin/bash
# GitHub Actions runner job-started hook
# Called when a job starts running on this runner
# Environment variables provided by GitHub Actions runner

exec >> /tmp/job-started-hook.log 2>&1

# Get runner index from environment (defaults to 0 for single-runner instances)
I="${RUNNER_INDEX:-0}"

# Log the job start with a specific prefix for CloudWatch filtering
# The LOG_PREFIX will be substituted during setup
echo "[$(date)] Runner-$I: LOG_PREFIX_JOB_STARTED Runner-$I: ${GITHUB_JOB}"

# Create a job tracking file to indicate this runner has an active job
# Format: RUNID-JOBNAME-RUNNER.job
mkdir -p /var/run/github-runner-jobs
echo '{"status":"running","runner":"'$I'"}' > /var/run/github-runner-jobs/${GITHUB_RUN_ID}-${GITHUB_JOB}-$I.job

# Update activity timestamps to reset the idle timer
touch /var/run/github-runner-last-activity /var/run/github-runner-has-run-job
