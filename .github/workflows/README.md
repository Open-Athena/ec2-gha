# GitHub Actions Workflows

This directory contains the reusable workflow and demo workflows for ec2-gha.

## Core Workflow

### [`runner.yml`](runner.yml)
The main reusable workflow that creates EC2 instances as self-hosted GitHub Actions runners. This workflow:
- Assumes an AWS role via OIDC authentication
- Launches EC2 instances with the specified configuration
- Installs and registers GitHub Actions runners on the instances
- Outputs runner labels for use in subsequent jobs

**Key features:**
- Supports organization/repository variables as fallbacks for all inputs
- Automatic CloudWatch Logs integration for debugging
- Configurable instance lifetime and idle termination
- Multi-instance support for parallel jobs

## Demo Workflows

These workflows demonstrate various ec2-gha capabilities:

### [`demo-gpu-minimal.yml`](demo-gpu-minimal.yml)
Minimal example that launches a GPU instance and runs `nvidia-smi` to verify GPU access.
- **Instance type:** `g4dn.xlarge`
- **Use case:** Quick GPU availability test

### [`demo-gpu.yml`](demo-gpu.yml)
Complete GPU workload example that:
- Installs PyTorch with CUDA support
- Runs a GPU benchmark
- Supports optional sleep for SSH debugging
- **Instance type:** `g4dn.xlarge`
- **Use case:** Real GPU workload testing

### [`demo-archs.yml`](demo-archs.yml)
Tests both x86 and ARM architectures:
- Launches separate runners for each architecture
- Verifies architecture-specific behavior
- Demonstrates matrix strategy across different instance types
- **Instance types:** `t3.medium` (x86), `t4g.medium` (ARM)
- **Use case:** Cross-architecture testing

### [`demo-multi-instance.yml`](demo-multi-instance.yml)
Shows how to launch multiple instances for parallel jobs:
- Creates configurable number of instances (default: 3)
- Uses matrix strategy to run jobs in parallel
- Each job runs on its own EC2 instance
- **Instance type:** `t3.medium`
- **Use case:** Parallel test execution

### [`demo-multi-job.yml`](demo-multi-job.yml)
Demonstrates different job types on separate instances:
- Launches 2 instances
- Runs build job on first instance
- Runs test job on second instance
- Aggregates results from both instances
- **Instance type:** `t3.medium`
- **Use case:** Pipeline with dedicated instances per stage

### [`demos.yml`](demos.yml)
Runs all demo workflows as a test suite. Useful for:
- Regression testing after changes
- Verifying all features work correctly
- CI/CD validation

## Usage

### From External Repositories

```yaml
jobs:
  runner:
    uses: Open-Athena/ec2-gha/.github/workflows/runner.yml@v2
    secrets: inherit
    with:
      ec2_instance_type: t3.medium
      ec2_image_id: ami-0e86e20dae9224db8  # Ubuntu 24.04 LTS

  my-job:
    needs: runner
    runs-on: ${{ needs.runner.outputs.id }}
    steps:
      - run: echo "Running on EC2!"
```

### Required Configuration

1. **AWS OIDC Setup**: Configure OIDC provider in AWS and create IAM role
2. **GitHub Secrets**: Add `GH_SA_TOKEN` with `admin:org` and `repo` scopes
3. **Variables** (organization or repository level):
   - `EC2_LAUNCH_ROLE`: ARN of IAM role for launching instances
   - `EC2_INSTANCE_PROFILE` (optional): IAM instance profile for EC2 instances
   - `EC2_KEY_NAME` (optional): EC2 key pair name for SSH access

See the [main README](../../README.md) for complete setup instructions.

## Workflow Inputs

The `runner.yml` workflow accepts many inputs, all with organization/repository variable fallbacks:

| Input | Variable Fallback | Description |
|-------|------------------|-------------|
| `ec2_instance_type` | `EC2_INSTANCE_TYPE` | Instance type (default: `t3.medium`) |
| `ec2_image_id` | `EC2_IMAGE_ID` | AMI ID (required) |
| `ec2_instance_profile` | `EC2_INSTANCE_PROFILE` | IAM instance profile name |
| `ec2_key_name` | `EC2_KEY_NAME` | SSH key pair name |
| `max_instance_lifetime` | `MAX_INSTANCE_LIFETIME` | Max lifetime in minutes (default: 360) |
| `runner_registration_timeout` | `RUNNER_REGISTRATION_TIMEOUT` | Registration timeout in seconds (default: 300) |

## Debugging

To debug runner issues:

1. **Enable CloudWatch Logs**: Set `cloudwatch_logs_group` input
2. **SSH Access**: Provide `ec2_key_name` and optionally `ssh_pubkey`
3. **Keep Instance Alive**: Use `sleep` input in demo workflows
4. **Check Logs**: View `/aws/ec2/github-runners` log group in CloudWatch

## Architecture Notes

- Instances use IMDSv2-compatible metadata fetching
- Runners auto-terminate when idle (configurable grace period)
- Failed registration triggers automatic instance termination
- Supports both x86 and ARM architectures
- Runner binaries are automatically selected based on architecture