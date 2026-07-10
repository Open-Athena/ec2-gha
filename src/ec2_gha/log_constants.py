"""
Constants for log messages used across ec2-gha components.

These constants ensure consistency between the runner scripts that generate logs
and the analysis tools that parse them.
"""

# Log stream names (relative to instance ID prefix)
LOG_STREAM_RUNNER_SETUP = "runner-setup"
LOG_STREAM_JOB_STARTED = "job-started"
LOG_STREAM_JOB_COMPLETED = "job-completed"
LOG_STREAM_TERMINATION = "termination"
LOG_STREAM_RUNNER_DIAG = "runner-diag"

# Log message prefixes
LOG_PREFIX_JOB_STARTED = "Job started:"
LOG_PREFIX_JOB_COMPLETED = "Job completed:"

# Termination messages
LOG_MSG_TERMINATION_PROCEEDING = "proceeding with termination"
LOG_MSG_RUNNER_REMOVED = "Runner removed from GitHub successfully"

# Default CloudWatch log group
DEFAULT_CLOUDWATCH_LOG_GROUP = "/aws/ec2/github-runners"
