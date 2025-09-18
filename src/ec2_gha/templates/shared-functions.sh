#!/bin/bash
# Shared functions for runner scripts
# These functions are used by multiple scripts throughout the runner lifecycle

# Logging functions
log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a /var/log/runner-setup.log; }
log_error() { log "ERROR: $1" >&2; }

dn=/dev/null

# Wait for dpkg lock to be released (for Debian/Ubuntu systems)
wait_for_dpkg_lock() {
  local t=120
  local L=/var/lib/dpkg/lock
  while fuser $L-frontend >$dn 2>&1 || fuser $L >$dn 2>&1; do
    if [ $t -le 0 ]; then
      log "WARNING: dpkg lock t, proceeding anyway"
      break
    fi
    log "dpkg is locked, waiting... ($t seconds remaining)"
    sleep 5
    t=$((t - 5))
  done
}

# Function to flush CloudWatch logs before shutdown
flush_cloudwatch_logs() {
  log "Stopping CloudWatch agent to flush logs"
  if systemctl is-active --quiet amazon-cloudwatch-agent; then
    systemctl stop amazon-cloudwatch-agent 2>$dn || /opt/aws/amazon-cloudwatch-agent/bin/amazon-cloudwatch-agent-ctl -a stop -m ec2 2>$dn || true
  fi
}

# Get EC2 instance metadata (IMDSv2 compatible)
get_metadata() {
  local path="$1"
  local token=$(curl -X PUT -H "X-aws-ec2-metadata-token-ttl-seconds: 300" http://169.254.169.254/latest/api/token 2>$dn || true)
  if [ -n "$token" ]; then
    curl -s -H "X-aws-ec2-metadata-token: $token" "http://169.254.169.254/latest/meta-data/$path" 2>$dn || echo "unknown"
  else
    curl -s "http://169.254.169.254/latest/meta-data/$path" 2>$dn || echo "unknown"
  fi
  return 0  # Always return success to avoid set -e issues
}

# Function to deregister all runners
deregister_all_runners() {
  for RUNNER_DIR in $homedir/runner-*; do
    if [ -d "$RUNNER_DIR" ] && [ -f "$RUNNER_DIR/config.sh" ]; then
      log "Deregistering runner in $RUNNER_DIR"
      cd "$RUNNER_DIR"
      pkill -INT -f "$RUNNER_DIR/run.sh" 2>$dn || true
      sleep 1
      if [ -f "$RUNNER_DIR/.runner-token" ]; then
        TOKEN=$(cat "$RUNNER_DIR/.runner-token")
        RUNNER_ALLOW_RUNASROOT=1 ./config.sh remove --token $TOKEN 2>&1
        log "Deregistration exit: $?"
      fi
    fi
  done
}

# Function to handle debug mode sleep and shutdown
debug_sleep_and_shutdown() {
  # Check if debug is a number (sleep duration in minutes)
  if [[ "$debug" =~ ^[0-9]+$ ]]; then
    local sleep_minutes="$debug"
    local sleep_seconds=$((sleep_minutes * 60))
    log "Debug: Sleeping ${sleep_minutes} minutes before shutdown..."
    # Detect the SSH user from the home directory
    local ssh_user=$(basename "$homedir" 2>$dn || echo "ec2-user")
    local public_ip=$(curl -s http://169.254.169.254/latest/meta-data/public-ipv4)
    log "SSH into instance with: ssh ${ssh_user}@${public_ip}"
    log "Then check: /var/log/runner-setup.log and /var/log/runner-debug.log"
    sleep "$sleep_seconds"
    log "Debug period ended, shutting down"
  elif [ "$debug" = "true" ] || [ "$debug" = "True" ] || [ "$debug" = "trace" ]; then
    # Just tracing enabled, no sleep
    log "Shutting down immediately (debug tracing enabled but no sleep requested)"
  else
    log "Shutting down immediately (debug mode not enabled)"
  fi
  shutdown -h now
}

# Function to handle fatal errors and terminate the instance
terminate_instance() {
  local reason="$1"
  local instance_id=$(get_metadata "instance-id")

  # Log error prominently
  echo "========================================" | tee -a /var/log/runner-setup.log
  log "FATAL ERROR DETECTED"
  log "Reason: $reason"
  log "Instance: $instance_id"
  log "Script location: $(pwd)"
  log "User: $(whoami)"
  log "Debug trace available in: /var/log/runner-debug.log"
  echo "========================================" | tee -a /var/log/runner-setup.log

  # Try to remove runner if it was partially configured
  if [ -f "$homedir/config.sh" ] && [ -n "${RUNNER_TOKEN:-}" ]; then
    cd "$homedir" && ./config.sh remove --token "${RUNNER_TOKEN}" || true
  fi

  flush_cloudwatch_logs
  debug_sleep_and_shutdown
  exit 1
}

# Function to configure a single GitHub Actions runner
configure_runner() {
  local idx=$1
  local token=$2
  local labels=$3
  local homedir=$4
  local repo=$5
  local instance_id=$6
  local runner_grace_period=$7
  local runner_initial_grace_period=$8

  log "Configuring runner $idx..."

  # Create runner directory and extract runner binary
  local runner_dir="$homedir/runner-$idx"
  mkdir -p "$runner_dir"
  cd "$runner_dir"
  tar -xzf /tmp/runner.tar.gz

  # Install dependencies if needed
  if [ -f ./bin/installdependencies.sh ]; then
    # Quick check for common AMIs with pre-installed deps
    if command -v dpkg >$dn 2>&1 && dpkg -l libicu[0-9]* 2>$dn | grep -q ^ii; then
      log "Dependencies exist, skipping install"
    else
      log "Installing dependencies..."
      set +e
      sudo ./bin/installdependencies.sh >$dn 2>&1
      local deps_result=$?
      set -e
      if [ $deps_result -ne 0 ]; then
        log "Dependencies script failed, installing manually..."
        if command -v dnf >$dn 2>&1; then
          sudo dnf install -y libicu lttng-ust >$dn 2>&1 || true
        elif command -v yum >$dn 2>&1; then
          sudo yum install -y libicu >$dn 2>&1 || true
        elif command -v apt-get >$dn 2>&1; then
          wait_for_dpkg_lock
          sudo apt-get update >$dn 2>&1 || true
          sudo apt-get install -y libicu-dev >$dn 2>&1 || true
        fi
      fi
    fi
  fi

  # Save token for deregistration
  echo "$token" > .runner-token

  # Create env file with runner hooks
  cat > .env << EOF
ACTIONS_RUNNER_HOOK_JOB_STARTED=/usr/local/bin/job-started-hook.sh
ACTIONS_RUNNER_HOOK_JOB_COMPLETED=/usr/local/bin/job-completed-hook.sh
RUNNER_HOME=$runner_dir
RUNNER_INDEX=$idx
RUNNER_GRACE_PERIOD=$runner_grace_period
RUNNER_INITIAL_GRACE_PERIOD=$runner_initial_grace_period
EOF

  # Configure runner with GitHub
  local runner_name="ec2-$instance_id-$idx"
  RUNNER_ALLOW_RUNASROOT=1 ./config.sh --url "https://github.com/$repo" --token "$token" --labels "$labels" --name "$runner_name" --disableupdate --unattended 2>&1 | tee /tmp/runner-$idx-config.log

  if grep -q "Runner successfully added" /tmp/runner-$idx-config.log; then
    log "Runner $idx registered successfully"
  else
    log_error "Failed to register runner $idx"
    return 1
  fi

  # Start runner in background
  RUNNER_ALLOW_RUNASROOT=1 nohup ./run.sh > $dn 2>&1 &
  local pid=$!
  log "Started runner $idx in $runner_dir (PID: $pid)"

  return 0
}
