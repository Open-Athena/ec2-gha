"""Default values for ec2-gha configuration."""

# Instance lifetime and timing defaults
MAX_INSTANCE_LIFETIME = "360"  # 6 hours (in minutes)
RUNNER_GRACE_PERIOD = "60"     # 1 minute (in seconds)
RUNNER_INITIAL_GRACE_PERIOD = "180"  # 3 minutes (in seconds)
RUNNER_POLL_INTERVAL = "10"    # 10 seconds
RUNNER_REGISTRATION_TIMEOUT = "300"  # 5 minutes (in seconds)

# EC2 instance defaults
EC2_IMAGE_ID = "ami-00096836009b16a22"  # Deep Learning OSS Nvidia Driver AMI GPU PyTorch
EC2_INSTANCE_TYPE = "g4dn.xlarge"

# Instance naming default template
INSTANCE_NAME = "$repo/$name#$run_number"

# Default instance count
INSTANCE_COUNT = 1

# Home directory auto-detection sentinel
AUTO = "AUTO"
