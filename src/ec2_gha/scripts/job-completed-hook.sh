#!/bin/bash
# GitHub Actions runner job-completed hook
# Called when a job finishes (success or failure) on this runner
# Environment variables provided by GitHub Actions runner

exec >> /tmp/job-completed-hook.log 2>&1

# Get runner index from environment (defaults to 0 for single-runner instances)
I="${RUNNER_INDEX:-0}"

# Log the job completion with a specific prefix for CloudWatch filtering
# The LOG_PREFIX will be substituted during setup
echo "[$(date)] Runner-$I: LOG_PREFIX_JOB_COMPLETED ${GITHUB_JOB}"

# Remove the job tracking file to indicate this runner no longer has an active job
rm -f /var/run/github-runner-jobs/${GITHUB_RUN_ID}-${GITHUB_JOB}-$I.job

# Update activity timestamp to reset the idle timer
touch /var/run/github-runner-last-activity
