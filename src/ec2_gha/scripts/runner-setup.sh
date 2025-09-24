#!/bin/bash
set -e

# This script is fetched and executed by the minimal userdata script
# All variables are already exported by the userdata script

# Enable debug tracing to a file for troubleshooting
exec 2> >(tee -a /var/log/runner-debug.log >&2)

# Conditionally enable debug mode (set -x) for tracing
# Debug can be: true/True/trace (trace only), or a number (trace + sleep minutes)
if [ "$debug" = "true" ] || [ "$debug" = "True" ] || [ "$debug" = "trace" ] || [[ "$debug" =~ ^[0-9]+$ ]]; then
  set -x
fi

# Determine home directory early since it's needed by shared functions
if [ -z "$homedir" ] || [ "$homedir" = "AUTO" ]; then
  # Try to find the default non-root user's home directory
  for user in ubuntu ec2-user centos admin debian fedora alpine arch; do
    if id "$user" &>/dev/null; then
      homedir="/home/$user"
      echo "[$(date '+%Y-%m-%d %H:%M:%S')] Auto-detected homedir: $homedir" | tee -a /var/log/runner-setup.log
      break
    fi
  done

  # Fallback if no standard user found
  if [ -z "$homedir" ] || [ "$homedir" = "AUTO" ]; then
    homedir=$(getent passwd | awk -F: '$3 >= 1000 && $3 < 65534 && $6 ~ /^\/home\// {print $6}' | while read dir; do
      if [ -d "$dir" ]; then
        echo "$dir"
        break
      fi
    done)
    if [ -z "$homedir" ]; then
      homedir="/home/ec2-user"  # Ultimate fallback
      echo "[$(date '+%Y-%m-%d %H:%M:%S')] Using fallback homedir: $homedir" | tee -a /var/log/runner-setup.log
    else
      owner=$(stat -c "%U" "$homedir" 2>/dev/null || stat -f "%Su" "$homedir" 2>/dev/null)
      echo "[$(date '+%Y-%m-%d %H:%M:%S')] Detected homedir: $homedir (owner: $owner)" | tee -a /var/log/runner-setup.log
    fi
  fi
else
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] Using specified homedir: $homedir" | tee -a /var/log/runner-setup.log
fi
export homedir

# Set common paths
B=/usr/local/bin
V=/var/run/github-runner

# Fetch shared functions from GitHub
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Fetching shared functions from GitHub (SHA: ${action_sha})" | tee -a /var/log/runner-setup.log
FUNCTIONS_URL="https://raw.githubusercontent.com/Open-Athena/ec2-gha/${action_sha}/src/ec2_gha/templates/shared-functions.sh"
if ! curl -sSL "$FUNCTIONS_URL" -o /tmp/shared-functions.sh && ! wget -q "$FUNCTIONS_URL" -O /tmp/shared-functions.sh; then
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: Failed to download shared functions" | tee -a /var/log/runner-setup.log
  shutdown -h now
  exit 1
fi

# Write shared functions that will be used by multiple scripts
cat > $B/runner-common.sh << EOSF
# Auto-generated shared functions and variables
# Set homedir for scripts that source this file
homedir="$homedir"
debug="$debug"
export homedir debug

EOSF

# Append the downloaded shared functions
cat /tmp/shared-functions.sh >> $B/runner-common.sh

chmod +x $B/runner-common.sh
source $B/runner-common.sh

logger "EC2-GHA: Starting userdata script"
trap 'logger "EC2-GHA: Script failed at line $LINENO with exit code $?"' ERR
trap 'terminate_instance "Setup script failed with error on line $LINENO"' ERR
# Handle watchdog termination signal
trap 'if [ -f $V-watchdog-terminate ]; then terminate_instance "No runners registered within timeout"; else terminate_instance "Script terminated"; fi' TERM

# Set up registration timeout failsafe - terminate if runner doesn't register in time
REGISTRATION_TIMEOUT="$runner_registration_timeout"
if ! [[ "$REGISTRATION_TIMEOUT" =~ ^[0-9]+$ ]]; then
  REGISTRATION_TIMEOUT=300
fi
# Create a marker file for watchdog termination request
touch $V-watchdog-active
(
  sleep $REGISTRATION_TIMEOUT
  if [ ! -f $V-registered ]; then
    touch $V-watchdog-terminate
    kill -TERM $$ 2>/dev/null || true
  fi
  rm -f $V-watchdog-active
) &
REGISTRATION_WATCHDOG_PID=$!
echo $REGISTRATION_WATCHDOG_PID > $V-watchdog.pid

# Run any custom user data script provided by the user
if [ -n "$userdata" ]; then
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] Running custom userdata" | tee -a /var/log/runner-setup.log
  eval "$userdata"
fi

exec >> /var/log/runner-setup.log 2>&1
log "Starting runner setup"

# Fetch instance metadata for labeling and logging
INSTANCE_TYPE=$(get_metadata "instance-type")
INSTANCE_ID=$(get_metadata "instance-id")
REGION=$(get_metadata "placement/region")
AZ=$(get_metadata "placement/availability-zone")
log "Instance metadata: Type=${INSTANCE_TYPE} ID=${INSTANCE_ID} Region=${REGION} AZ=${AZ}"

# Set up maximum lifetime timeout - instance will terminate after this time regardless of job status
MAX_LIFETIME_MINUTES=$max_instance_lifetime
log "Setting up maximum lifetime timeout: ${MAX_LIFETIME_MINUTES} minutes"
# Use ; instead of && so shutdown runs even if echo fails (e.g., disk full)
# Try multiple shutdown methods as fallbacks
nohup bash -c "
  sleep ${MAX_LIFETIME_MINUTES}m
  echo '[$(date)] Maximum lifetime reached' 2>/dev/null || true
  # Try normal shutdown
  shutdown -h now 2>/dev/null || {
    # If shutdown fails, try halt
    halt -f 2>/dev/null || {
      # If halt fails, try sysrq if available (Linux only)
      if [ -w /proc/sysrq-trigger ]; then
        echo 1 > /proc/sys/kernel/sysrq 2>/dev/null
        echo o > /proc/sysrq-trigger 2>/dev/null
      fi
      # Last resort: force immediate reboot
      reboot -f 2>/dev/null || true
    }
  }
" > /var/log/max-lifetime.log 2>&1 &

# Configure CloudWatch Logs if a log group is specified
if [ "$cloudwatch_logs_group" != "" ]; then
  log "Installing CloudWatch agent"
  (
    if command -v dpkg >/dev/null 2>&1; then
      wait_for_dpkg_lock
      wget -q https://s3.amazonaws.com/amazoncloudwatch-agent/ubuntu/amd64/latest/amazon-cloudwatch-agent.deb
      dpkg -i -E ./amazon-cloudwatch-agent.deb
      rm amazon-cloudwatch-agent.deb
    elif command -v rpm >/dev/null 2>&1; then
      wget -q https://s3.amazonaws.com/amazoncloudwatch-agent/amazon_linux/amd64/latest/amazon-cloudwatch-agent.rpm
      rpm -U ./amazon-cloudwatch-agent.rpm
      rm amazon-cloudwatch-agent.rpm
    fi
    # Build CloudWatch config with factored strings
    P='"file_path":'
    G=',"log_group_name":"'$cloudwatch_logs_group'","log_stream_name":"{instance_id}/'
    Z='","timezone":"UTC"}'
    H="$homedir"
    cat > /opt/aws/amazon-cloudwatch-agent/etc/amazon-cloudwatch-agent.json << EOF
{"agent":{"run_as_user":"cwagent"},"logs":{"logs_collected":{"files":{"collect_list":[
{"$P/var/log/runner-setup.log${G}runner-setup$Z",
{"$P/var/log/runner-debug.log${G}runner-debug$Z",
{"$P/tmp/job-started-hook.log${G}job-started$Z",
{"$P/tmp/job-completed-hook.log${G}job-completed$Z",
{"$P/tmp/termination-check.log${G}termination$Z",
{"$P/tmp/runner-*-config.log${G}runner-config$Z",
{"$P$H/_diag/Runner_**.log${G}runner-diag$Z",
{"$P$H/_diag/Worker_**.log${G}worker-diag$Z"
]}}}}
EOF
    /opt/aws/amazon-cloudwatch-agent/bin/amazon-cloudwatch-agent-ctl -a fetch-config -m ec2 -c file:/opt/aws/amazon-cloudwatch-agent/etc/amazon-cloudwatch-agent.json -s
    log "CloudWatch agent started"
  ) || log "WARNING: CloudWatch agent installation failed, continuing without it"
fi

# Configure SSH access if public key provided (useful for debugging)
if [ -n "$ssh_pubkey" ]; then
  log "Configuring SSH access"
  # Determine the default user based on the home directory owner
  DEFAULT_USER=$(stat -c "%U" "$homedir" 2>/dev/null || echo "root")
  mkdir -p "$homedir/.ssh"
  chmod 700 "$homedir/.ssh"
  echo "$ssh_pubkey" >> "$homedir/.ssh/authorized_keys"
  chmod 600 "$homedir/.ssh/authorized_keys"
  if [ "$DEFAULT_USER" != "root" ]; then
    chown -R "$DEFAULT_USER:$DEFAULT_USER" "$homedir/.ssh"
  fi
  log "SSH key added for user $DEFAULT_USER"
fi

log "Working directory: $homedir"
cd "$homedir"

# Run any pre-runner script provided by the user
if [ -n "$script" ]; then
  echo "$script" > pre-runner-script.sh
  log "Running pre-runner script"
  source pre-runner-script.sh
fi
export RUNNER_ALLOW_RUNASROOT=1

# Number of runners to configure on this instance
RUNNERS_PER_INSTANCE=$runners_per_instance

# Download GitHub Actions runner binary
ARCH=$(uname -m)
if [ "$ARCH" = "aarch64" ] || [ "$ARCH" = "arm64" ]; then
  RUNNER_URL=$(echo "$runner_release" | sed 's/x64/arm64/g')
  log "ARM detected, using: $RUNNER_URL"
else
  RUNNER_URL="$runner_release"
  log "x64 detected, using: $RUNNER_URL"
fi

if command -v curl >/dev/null 2>&1; then
  curl -L $RUNNER_URL -o /tmp/runner.tar.gz
elif command -v wget >/dev/null 2>&1; then
  wget -q $RUNNER_URL -O /tmp/runner.tar.gz
else
  log_error "Neither curl nor wget found. Cannot download runner."
  terminate_instance "No download tool available"
fi
log "Downloaded runner binary"

# Helper function to fetch scripts
fetch_script() {
  local script_name="$1"
  local url="${BASE_URL}/${script_name}"
  local dest="${B}/${script_name}"

  if command -v curl >/dev/null 2>&1; then
    curl -fsSL "$url" -o "$dest" || {
      log_error "Failed to fetch $script_name"
      terminate_instance "Failed to download $script_name"
    }
  elif command -v wget >/dev/null 2>&1; then
    wget -q "$url" -O "$dest" || {
      log_error "Failed to fetch $script_name"
      terminate_instance "Failed to download $script_name"
    }
  else
    log_error "Neither curl nor wget found. Cannot download scripts."
    terminate_instance "No download tool available"
  fi
}

# Fetch job tracking scripts from GitHub
# These scripts are called by GitHub runner hooks
log "Fetching runner hook scripts"
BASE_URL="https://raw.githubusercontent.com/Open-Athena/ec2-gha/${action_sha}/src/ec2_gha/scripts"

fetch_script "job-started-hook.sh"
fetch_script "job-completed-hook.sh"
fetch_script "check-runner-termination.sh"

# Replace log prefix placeholders with actual values
sed -i "s/LOG_PREFIX_JOB_STARTED/${log_prefix_job_started}/g" $B/job-started-hook.sh
sed -i "s/LOG_PREFIX_JOB_COMPLETED/${log_prefix_job_completed}/g" $B/job-completed-hook.sh

chmod +x $B/job-started-hook.sh $B/job-completed-hook.sh $B/check-runner-termination.sh

# Set up job tracking directory
mkdir -p $V-jobs
touch $V-last-activity

# Set up periodic termination check using systemd
cat > /etc/systemd/system/runner-termination-check.service << EOF
[Unit]
Description=Check GitHub runner termination conditions
After=network.target
[Service]
Type=oneshot
Environment="RUNNER_GRACE_PERIOD=$runner_grace_period"
Environment="RUNNER_INITIAL_GRACE_PERIOD=$runner_initial_grace_period"
Environment="RUNNER_POLL_INTERVAL=$runner_poll_interval"
ExecStart=$B/check-runner-termination.sh
EOF

cat > /etc/systemd/system/runner-termination-check.timer << EOF
[Unit]
Description=Periodic GitHub runner termination check
Requires=runner-termination-check.service
[Timer]
OnBootSec=60s
OnUnitActiveSec=${runner_poll_interval}s
[Install]
WantedBy=timers.target
EOF

systemctl daemon-reload
systemctl enable runner-termination-check.timer
systemctl start runner-termination-check.timer

# Build metadata labels (these will be added to the runner labels)
METADATA_LABELS=",${INSTANCE_ID},${INSTANCE_TYPE}"
# Add instance name as a label if provided
if [ -n "$instance_name" ]; then
  INSTANCE_NAME_LABEL=$(echo "$instance_name" | tr ' /' '-' | tr -cd '[:alnum:]-_#')
  METADATA_LABELS="${METADATA_LABELS},${INSTANCE_NAME_LABEL}"
fi

log "Setting up $RUNNERS_PER_INSTANCE runner(s)"

# Export functions for subprocesses (variables already exported from runner-common.sh)
export -f configure_runner
export -f log
export -f log_error
export -f get_metadata
export -f flush_cloudwatch_logs
export -f deregister_all_runners
export -f debug_sleep_and_shutdown
export -f wait_for_dpkg_lock

# Parse space-delimited tokens and pipe-delimited labels
IFS=' ' read -ra tokens <<< "$runner_tokens"
IFS='|' read -ra labels <<< "$runner_labels"

num_runners=${#tokens[@]}
log "Configuring $num_runners runner(s) in parallel"

# Start configuration for each runner in parallel
pids=()
for i in ${!tokens[@]}; do
  token=${tokens[$i]}
  label=${labels[$i]:-}
  if [ -z "$token" ]; then
    log_error "No token for runner $i"
    continue
  fi
  (
    # Override ERR trap in subshell to prevent global side effects
    trap 'echo "Subshell error on line $LINENO" >&2; exit 1' ERR
    configure_runner $i "$token" "${label}$METADATA_LABELS" "$homedir" "$repo" "$INSTANCE_ID" "$runner_grace_period" "$runner_initial_grace_period"
    echo $? > /tmp/runner-$i-status
  ) &
  pids+=($!)
  log "Started configuration for runner $i (PID: ${pids[-1]})"
done

# Wait for all background jobs to complete
log "Waiting for all runner configurations to complete..."
failed=0
succeeded=0
for i in ${!pids[@]}; do
  wait ${pids[$i]}
  if [ -f /tmp/runner-$i-status ]; then
    status=$(cat /tmp/runner-$i-status)
    rm -f /tmp/runner-$i-status
    if [ "$status" != "0" ]; then
      log_error "Runner $i configuration failed"
      failed=$((failed + 1))
    else
      succeeded=$((succeeded + 1))
    fi
  fi
done

# Allow partial success - only terminate if ALL runners failed
if [ $succeeded -eq 0 ] && [ $failed -gt 0 ]; then
  terminate_instance "All runners failed to register"
elif [ $failed -gt 0 ]; then
  log "WARNING: $failed runner(s) failed, but $succeeded succeeded. Continuing with partial capacity."
fi

if [ $succeeded -gt 0 ]; then
  log "$succeeded runner(s) registered and started successfully"
  touch $V-registered
else
  log_error "No runners registered successfully"
  terminate_instance "No runners registered successfully"
fi

# Kill registration watchdog now that runners are registered
if [ -f $V-watchdog.pid ]; then
  WATCHDOG_PID=$(cat $V-watchdog.pid)
  kill $WATCHDOG_PID 2>/dev/null || true
  rm -f $V-watchdog.pid
fi

# Final setup - ensure runner directories are accessible for debugging
touch $V-started
chmod o+x $homedir
for RUNNER_DIR in $homedir/runner-*; do
  [ -d "$RUNNER_DIR/_diag" ] && chmod 755 "$RUNNER_DIR/_diag"
done

log "Runner setup complete"
