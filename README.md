# ec2-gha
Run GitHub Actions on ephemeral EC2 instances.

**TOC**
<!-- toc -->
- [Quick Start](#quick-start)
- [Demos](#demos)
- [Inputs](#inputs)
    - [Required](#required)
        - [`secrets.GH_SA_TOKEN`](#gh-sa-token)
        - [`ec2_launch_role` / `vars.EC2_LAUNCH_ROLE`](#ec2-launch-role)
    - [Optional](#optional)
- [Outputs](#outputs)
- [Technical Details](#technical)
    - [Runner Lifecycle](#lifecycle)
    - [Parallel Jobs (Multiple Instances)](#parallel)
    - [Multi-Job Workflows (Sequential)](#multi-job)
    - [Termination logic](#termination)
    - [CloudWatch Logs Integration](#cloudwatch)
    - [Debugging and Troubleshooting](#debugging)
        - [SSH Access](#ssh)
        - [Important Log Files](#logs)
        - [Common Issues](#issues)
    - [Implementation Notes](#implementation)
    - [Default AWS Tags](#tags)
- [Appendix: IAM Role Setup](#iam-setup-appendix)
    - [Using Pulumi](#pulumi)
    - [Using AWS CLI](#aws-cli)
- [Acknowledgements](#acks)
<!-- /toc -->

## Quick Start <a id="quick-start"></a>

Call [`runner.yml`] as a [reusable workflow]:

```yaml
name: GPU Tests
on: [push]
permissions:
  id-token: write  # Required for AWS OIDC
  contents: read   # Normally on by default, but explicit `permissions` block undoes that, so we explicitly re-enable
jobs:
  ec2:
    uses: Open-Athena/ec2-gha/.github/workflows/runner.yml@v2
    # Required:
    # - `secrets.GH_SA_TOKEN` (GitHub token with repo admin access)
    # - `vars.EC2_LAUNCH_ROLE` (role with GitHub OIDC access to this repo)
    secrets: inherit
    with:
      ec2_instance_type: g4dn.xlarge
      ec2_image_id: ami-00096836009b16a22  # Deep Learning OSS Nvidia Driver AMI GPU PyTorch
  gpu-test:
    needs: ec2
    runs-on: ${{ needs.ec2.outputs.id }}
    steps:
      - run: nvidia-smi  # GPU node!
```

## Demos <a id="demos"></a>

Example workflows demonstrating ec2-gha capabilities are in [`.github/workflows/`](.github/workflows/):

[![](img/demos%2325%201.png)][demos#25]

- [`demo-dbg-minimal.yml`](.github/workflows/demo-dbg-minimal.yml) - Configurable debugging instance
- [`demo-gpu-minimal.yml`](.github/workflows/demo-gpu-minimal.yml) - Basic GPU test
- [`demo-cpu-sweep.yml`](.github/workflows/demo-cpu-sweep.yml) - OS/arch matrix (Ubuntu, Debian, AL2/AL2023 on x86/ARM)
- [`demo-gpu-sweep.yml`](.github/workflows/demo-gpu-sweep.yml) - GPU instances (g4dn, g5, g6, g5g) with PyTorch
- [`demo-instances-mtx.yml`](.github/workflows/demo-instances-mtx.yml) - Multiple instances for parallel jobs
- [`demo-runners-mtx.yml`](.github/workflows/demo-runners-mtx.yml) - Multiple runners on single instance
- [`demo-jobs-split.yml`](.github/workflows/demo-jobs-split.yml) - Different job types on separate instances

### Test Suite
- [`demos.yml`](.github/workflows/demos.yml) - Runs all demos for regression testing
- [`test-disk-full.yml`](.github/workflows/test-disk-full.yml) - Stress test for disk-full scenarios with configurable fill strategies

See [`.github/workflows/README.md`](.github/workflows/README.md) for detailed descriptions of each demo.

## Inputs <a id="inputs"></a>

### Required <a id="required"></a>

#### `secrets.GH_SA_TOKEN` <a id="gh-sa-token"></a>
Create a GitHub Personal Access Token with `repo` scope and admin access to your repository, and add it as a repository secret named `GH_SA_TOKEN`:

```bash
gh secret set GH_SA_TOKEN --body "your_personal_access_token_here"
```

#### `ec2_launch_role` / `vars.EC2_LAUNCH_ROLE` <a id="ec2-launch-role"></a>

This role must be able to launch, tag, describe, and terminate EC2 instances, and should be integrated with GitHub's OIDC provider.

For detailed setup instructions, see [Appendix: IAM Role Setup](#iam-setup-appendix), which includes examples using both Pulumi and AWS CLI.

After creating the role, add it as a repository variable:
```bash
gh variable set EC2_LAUNCH_ROLE --body "arn:aws:iam::123456789012:role/GitHubActionsEC2Role"
```

The `EC2_LAUNCH_ROLE` is passed to [aws-actions/configure-aws-credentials]; if you'd like to authenticate with AWS using other parameters, please [file an issue] to let us know.

### Optional <a id="optional"></a>

Many of these fall back to corresponding `vars.*` (if not provided as `inputs`):

- `action_ref` - ec2-gha Git ref to checkout (branch/tag/SHA); automatically resolved to a SHA for security
- `aws_region` - AWS region for EC2 instances (falls back to `vars.AWS_REGION`, default: `us-east-1`)
- `cloudwatch_logs_group` - CloudWatch Logs group name for streaming logs (falls back to `vars.CLOUDWATCH_LOGS_GROUP`)
- `ec2_home_dir` - Home directory (default: `/home/ubuntu`)
- `ec2_image_id` - AMI ID (default: Ubuntu 24.04 LTS)
- `ec2_instance_profile` - IAM instance profile name for EC2 instances
  - Useful for on-instance debugging [via SSH][SSH access]
  - Required for [CloudWatch logging][cw]
  - Falls back to `vars.EC2_INSTANCE_PROFILE`
  - See [Appendix: IAM Role Setup](#iam-setup-appendix) for more details and sample setup code
- `ec2_instance_type` - Instance type (default: `t3.medium`)
- `ec2_key_name` - EC2 key pair name (for [SSH access])
- `instance_count` - Number of instances to create (default: 1, for parallel jobs)
- `instance_name` - Name tag template for EC2 instances. Uses Python string.Template format with variables: `$repo`, `$name` (workflow filename stem), `$workflow` (full workflow name), `$ref`, `$run` (number), `$idx` (0-based instance index for multi-instance launches). Default: `$repo/$name#$run` (or `$repo/$name#$run $idx` for multi-instance)
- `debug` - Debug mode: `false`=off, `true`/`trace`=set -x only, number=set -x + sleep N minutes before shutdown (for troubleshooting)
- `ec2_root_device_size` - Root disk size in GB: `0`=AMI default, `+N`=AMI+N GB for testing (e.g., `+2` for AMI size + 2GB), or explicit size in GB
- `ec2_security_group_id` - Security group ID (required for [SSH access], should expose inbound port 22)
- `max_instance_lifetime` - Maximum instance lifetime in minutes before automatic shutdown (falls back to `vars.MAX_INSTANCE_LIFETIME`, default: 360 = 6 hours; generally should not be relevant, instances shut down within 1-2mins of jobs completing)
- `runner_grace_period` - Grace period in seconds before terminating after last job completes (default: 60)
- `runner_initial_grace_period` - Grace period in seconds before terminating instance if no jobs start (default: 180)
- `runner_poll_interval` - How often (in seconds) to check termination conditions (default: 10)
- `ssh_pubkey` - SSH public key (for [SSH access])

## Outputs <a id="outputs"></a>

| Name | Description                                                              |
|------|--------------------------------------------------------------------------|
| id   | Single runner label for `runs-on` (when `instance_count=1`)            |
| mtx | JSON array of objects for matrix strategies (each has: idx, id, instance_id, instance_idx, runner_idx) |

## Technical Details <a id="technical"></a>

### Runner Lifecycle <a id="lifecycle"></a>

This workflow creates EC2 instances with GitHub Actions runners that:
- Automatically register with your repository
- Support both single and multi-job workflows
- Self-terminate when work is complete
- Use [GitHub's native runner hooks][hooks] for job tracking
- Optionally support [SSH access] and [CloudWatch logging][cw] (for debugging)

### Parallel Jobs (Multiple Instances) <a id="parallel"></a>

Create multiple EC2 instances for parallel execution using `instance_count`:

```yaml
jobs:
  ec2:
    uses: Open-Athena/ec2-gha/.github/workflows/runner.yml@main
    secrets: inherit
    with:
      instance_count: "3"  # Create 3 instances

  parallel-jobs:
    needs: ec2
    strategy:
      matrix:
        runner: ${{ fromJson(needs.ec2.outputs.mtx) }}
    runs-on: ${{ matrix.runner.id }}
    steps:
      - run: echo "Running on runner ${{ matrix.runner.idx }} (instance ${{ matrix.runner.instance_idx }})"
```

Each instance gets a unique runner label and can execute jobs independently. This is useful for:
- Matrix builds that need isolated environments
- Parallel testing across different configurations
- Distributed workloads

### Multi-Job Workflows (Sequential) <a id="multi-job"></a>

The runner supports multiple sequential jobs on the same instance, e.g.:

```yaml
jobs:
  ec2:
    uses: Open-Athena/ec2-gha/.github/workflows/runner.yml@main
    secrets: inherit
    with:
      runner_grace_period: "120"  # Max idle time before termination (seconds)

  prepare:
    needs: ec2
    runs-on: ${{ needs.ec2.outputs.id }}
    steps:
      - run: echo "Preparing environment"

  train:
    needs: [ec2, prepare]
    runs-on: ${{ needs.ec2.outputs.id }}
    steps:
      - run: echo "Training model"

  evaluate:
    needs: [ec2, train]
    runs-on: ${{ needs.ec2.outputs.id }}
    steps:
      - run: echo "Evaluating results"
```
(see also demo workflows in [`.github/workflows/`](.github/workflows/))

### Termination logic <a id="termination"></a>

The runner uses [GitHub Actions runner hooks][hooks] to track job lifecycle and determine when to terminate:

#### Job Tracking
- **Start/End Hooks**: Creates/removes JSON files in `/var/run/github-runner-jobs/` when jobs start/end
- **Heartbeat Mechanism**: Active jobs update their file timestamps periodically to detect stuck jobs
- **Process Monitoring**: Checks both Runner.Listener and Runner.Worker processes to verify jobs are truly running
- **Activity Tracking**: Updates `/var/run/github-runner-last-activity` timestamp on job events

#### Termination Conditions
The systemd timer checks every `runner_poll_interval` seconds (default: 10s) and terminates when:
1. No active jobs are running
2. Idle time exceeds the grace period:
   - `runner_initial_grace_period` (default: 180s) - Before first job
   - `runner_grace_period` (default: 60s) - Between jobs

#### Robustness Features
- **Stale Job Detection**: Removes job files older than 3× poll interval (likely disk full)
- **Worker Process Detection**: Distinguishes between idle runners and active jobs

#### Clean Shutdown Sequence
1. Stop runner processes gracefully (SIGINT)
2. Deregister runners from GitHub
3. Flush CloudWatch logs (if configured)
4. Execute shutdown with multiple fallback methods

### CloudWatch Logs Integration <a id="cloudwatch"></a>

CloudWatch Logs integration is optional, but particularly useful for debugging runner startup/shutdown.

To stream runner logs to CloudWatch:

1. **Create a CloudWatch Logs group**:
   ```bash
   aws logs create-log-group --log-group-name /aws/ec2/github-runners
   ```

2. **Create an IAM role and instance profile for your EC2 instances** with CloudWatch Logs permissions:

   **Important**: This is a separate role from your GitHub Actions launch role (`EC2_LAUNCH_ROLE`). The EC2 instances need their own IAM role to write logs. This role is only required if you want to use CloudWatch Logs.

   See [Appendix: IAM Role Setup](#iam-setup-appendix) for detailed instructions on creating the `EC2_INSTANCE_PROFILE`.

3. **Configure the workflow** with the IAM role:
   ```yaml
   jobs:
     ec2:
       uses: Open-Athena/ec2-gha/.github/workflows/runner.yml@main
       with:
         cloudwatch_logs_group: /aws/ec2/github-runners
         ec2_instance_profile: GitHubRunnerEC2Profile  # The instance profile from step 2
       secrets: inherit
   ```

   Or set as a repository (or org-level) variable:
   ```bash
   gh variable set EC2_INSTANCE_PROFILE --body "GitHubRunnerEC2Profile"
   ```

The following logs will be streamed to CloudWatch:
- `/var/log/runner-setup.log` - Runner installation and setup
- `/tmp/job-started-hook.log` - Job start events with workflow/job details
- `/tmp/job-completed-hook.log` - Job completion events with remaining job count
- `/tmp/termination-check.log` - Instance termination checks every 30 seconds
- `~/actions-runner/_diag/Runner_*.log` - GitHub runner diagnostic logs
- `~/actions-runner/_diag/Worker_*.log` - GitHub runner worker process logs

### Debugging and Troubleshooting <a id="debugging"></a>

#### SSH Access <a id="ssh"></a>
To enable SSH debugging, provide:
- `ec2_security_group_id`: A security group allowing SSH (port 22)
- Either:
  - `ec2_key_name`: An EC2 key pair name (for pre-existing AWS keys)
  - `ssh_pubkey`: An SSH public key string (for ad-hoc access)

#### Important Log Files <a id="logs"></a>
Once connected to the instance:
- `/var/log/runner-setup.log` - Runner installation and registration
- `/var/log/cloud-init-output.log` - Complete userdata execution
- `/tmp/job-started-hook.log` - Job start tracking with detailed metadata
- `/tmp/job-completed-hook.log` - Job completion tracking with job counts
- `/tmp/termination-check.log` - Termination check logs (runs every 30 seconds)
- `/var/run/github-runner-jobs/*.job` - Individual job status files
- `~/actions-runner/_diag/Runner_*.log` - GitHub runner process logs (job scheduling, API calls)
- `~/actions-runner/_diag/Worker_*.log` - Job execution logs

#### Common Issues <a id="issues"></a>

**Runner fails to register**
- Check that `GH_PAT` has admin access to the repository
- Verify the AMI has required dependencies (git, tar, etc.)
- Check `/var/log/cloud-init-output.log` for errors

**Multi-job workflow fails**
- Increase `runner_grace_period` to allow more time between jobs
- Check `/tmp/job-completed-hook.log` for premature termination
- Verify all jobs properly depend on the start-runner job

**Instance doesn't terminate**
- SSH to the instance and check `/tmp/job-completed-hook.log`
- Verify runner hooks are configured: `cat ~/actions-runner/.env`
- Check for stuck jobs in `/var/run/github-runner-jobs/`

### Implementation Notes <a id="implementation"></a>

- Uses non-ephemeral runners to support instance-reuse across jobs
- Uses activity-based termination with systemd timer checks every 30 seconds
- Terminates only after `runner_grace_period` seconds of inactivity (no race conditions)
- Also terminates after `max_instance_lifetime`, as a fail-safe (default: 6 hours)
- Supports custom AMIs with pre-installed dependencies

### Default AWS Tags <a id="tags"></a>

The action automatically adds these tags to EC2 instances (unless already provided):
- `Name`: Auto-generated from repository/workflow/run-number (e.g., "my-repo/test-workflow/#123")
- `Repository`: GitHub repository full name
- `Workflow`: Workflow name
- `URL`: Direct link to the GitHub Actions run

These help with debugging and cost tracking. You can override any of these by providing your own tags with the same keys.

## Appendix: IAM Role Setup <a id="iam-setup-appendix"></a>

This appendix provides detailed instructions for setting up the required IAM roles using either Pulumi or AWS CLI.

### Using Pulumi <a id="pulumi"></a>

<details>
<summary>Complete Pulumi configuration for both EC2_LAUNCH_ROLE and EC2_INSTANCE_PROFILE</summary>

```python
"""Create EC2_LAUNCH_ROLE and EC2_INSTANCE_PROFILE for GitHub Actions workflows."""

import pulumi
import pulumi_aws as aws
from pulumi import Output

current = aws.get_caller_identity()

# Create IAM OIDC provider for GitHub Actions
github_oidc_provider = aws.iam.OpenIdConnectProvider(
    "github-actions",
    client_id_lists=["sts.amazonaws.com"],
    thumbprint_lists=["2b18947a6a9fc7764fd8b5fb18a863b0c6dac24f"],
    url="https://token.actions.githubusercontent.com",
)

# Create IAM role for EC2 instances first (shared across all repos)
ec2_instance_role = aws.iam.Role("github-runner-ec2-instance-role",
    assume_role_policy="""{
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {
                    "Service": "ec2.amazonaws.com"
                },
                "Action": "sts:AssumeRole"
            }
        ]
    }"""
)

# EC2 launch policy for GitHub Actions
ec2_launch_policy = aws.iam.Policy("github-actions-ec2-launch-policy",
    policy=Output.format("""{{
        "Version": "2012-10-17",
        "Statement": [
            {{
                "Effect": "Allow",
                "Action": [
                    "ec2:RunInstances",
                    "ec2:TerminateInstances",
                    "ec2:DescribeInstances",
                    "ec2:DescribeInstanceStatus",
                    "ec2:DescribeImages",
                    "ec2:CreateTags"
                ],
                "Resource": "*"
            }},
            {{
                "Effect": "Allow",
                "Action": [
                    "iam:PassRole"
                ],
                "Resource": "{0}",
                "Condition": {{
                    "StringEquals": {{
                        "iam:PassedToService": "ec2.amazonaws.com"
                    }}
                }}
            }}
        ]
    }}""", ec2_instance_role.arn)
)

# CloudWatch Logs policy for EC2 instances
cloudwatch_logs_policy = aws.iam.Policy("ec2-instance-cloudwatch-policy",
    policy="""{
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": [
                    "logs:CreateLogGroup",
                    "logs:CreateLogStream",
                    "logs:PutLogEvents",
                    "logs:DescribeLogStreams"
                ],
                "Resource": "arn:aws:logs:*:*:*"
            }
        ]
    }"""
)

# Attach CloudWatch policy to instance role
cloudwatch_policy_attachment = aws.iam.RolePolicyAttachment("ec2-instance-cloudwatch-attachment",
    role=ec2_instance_role.name,
    policy_arn=cloudwatch_logs_policy.arn
)

# Create instance profile
ec2_instance_profile = aws.iam.InstanceProfile("github-runner-ec2-profile",
    role=ec2_instance_role.name
)

# Export the instance profile name
pulumi.export("ec2_instance_profile_name", ec2_instance_profile.name)

# Configure which repos can use the launch role
ORGS_REPOS = [
    "your-org/your-repo",
    "your-org/*",  # Allow all repos in org
]

# Create IAM role that GitHub Actions can assume, one per repo
for index, repo in enumerate(ORGS_REPOS):
    github_actions_role = aws.iam.Role(f"github-actions-launch-role-{index}",
        assume_role_policy=f"""{
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Principal": {
                        "Federated": "arn:aws:iam:{current.account_id}:oidc-provider/token.actions.githubusercontent.com"
                    },
                    "Action": "sts:AssumeRoleWithWebIdentity",
                    "Condition": {
                        "StringLike": {
                            "token.actions.githubusercontent.com:sub": "repo:{repo}:*"
                        }
                    }
                }
            ]
        }"""
    )

    # Attach the EC2 launch policy
    ec2_policy_attachment = aws.iam.RolePolicyAttachment(f"github-actions-ec2-launch-attachment-{index}",
        role=github_actions_role.name,
        policy_arn=ec2_launch_policy.arn
    )

    # Export the role ARN
    pulumi.export(f"ec2_launch_role_arn_{repo}", github_actions_role.arn)
```
</details>

### Using AWS CLI <a id="aws-cli"></a>

<details>
<summary>Complete AWS CLI commands for both EC2_LAUNCH_ROLE and EC2_INSTANCE_PROFILE</summary>

```bash
# 1. Create the OIDC provider (if not already exists)
aws iam create-open-id-connect-provider \
  --url https://token.actions.githubusercontent.com \
  --client-id-list sts.amazonaws.com \
  --thumbprint-list 2b18947a6a9fc7764fd8b5fb18a863b0c6dac24f

# 2. Create the EC2 launch policy
aws iam create-policy \
  --policy-name GitHubActionsEC2LaunchPolicy \
  --policy-document '{
    "Version": "2012-10-17",
    "Statement": [
      {
        "Effect": "Allow",
        "Action": [
          "ec2:RunInstances",
          "ec2:TerminateInstances",
          "ec2:DescribeInstances",
          "ec2:DescribeInstanceStatus",
          "ec2:DescribeImages",
          "ec2:CreateTags"
        ],
        "Resource": "*"
      },
      {
        "Effect": "Allow",
        "Action": [
          "iam:PassRole"
        ],
        "Resource": "arn:aws:iam::YOUR_ACCOUNT_ID:role/GitHubRunnerEC2InstanceRole",
        "Condition": {
          "StringEquals": {
            "iam:PassedToService": "ec2.amazonaws.com"
          }
        }
      }
    ]
  }'

# 3. Create the EC2 launch role with trust policy
# Replace YOUR_ACCOUNT_ID and YOUR_ORG/YOUR_REPO
aws iam create-role \
  --role-name GitHubActionsEC2LaunchRole \
  --assume-role-policy-document '{
    "Version": "2012-10-17",
    "Statement": [
      {
        "Effect": "Allow",
        "Principal": {
          "Federated": "arn:aws:iam::YOUR_ACCOUNT_ID:oidc-provider/token.actions.githubusercontent.com"
        },
        "Action": "sts:AssumeRoleWithWebIdentity",
        "Condition": {
          "StringLike": {
            "token.actions.githubusercontent.com:sub": "repo:YOUR_ORG/YOUR_REPO:*"
          }
        }
      }
    ]
  }'

# 4. Attach the launch policy to the role
aws iam attach-role-policy \
  --role-name GitHubActionsEC2LaunchRole \
  --policy-arn arn:aws:iam::YOUR_ACCOUNT_ID:policy/GitHubActionsEC2LaunchPolicy

# 5. Create CloudWatch Logs policy for EC2 instances
aws iam create-policy \
  --policy-name GitHubRunnerCloudWatchPolicy \
  --policy-document '{
    "Version": "2012-10-17",
    "Statement": [
      {
        "Effect": "Allow",
        "Action": [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents",
          "logs:DescribeLogStreams"
        ],
        "Resource": "arn:aws:logs:*:*:*"
      }
    ]
  }'

# 6. Create EC2 instance role
aws iam create-role \
  --role-name GitHubRunnerEC2InstanceRole \
  --assume-role-policy-document '{
    "Version": "2012-10-17",
    "Statement": [
      {
        "Effect": "Allow",
        "Principal": {
          "Service": "ec2.amazonaws.com"
        },
        "Action": "sts:AssumeRole"
      }
    ]
  }'

# 7. Attach CloudWatch policy to instance role
aws iam attach-role-policy \
  --role-name GitHubRunnerEC2InstanceRole \
  --policy-arn arn:aws:iam::YOUR_ACCOUNT_ID:policy/GitHubRunnerCloudWatchPolicy

# 8. Create instance profile
aws iam create-instance-profile \
  --instance-profile-name GitHubRunnerEC2Profile

# 9. Add role to instance profile
aws iam add-role-to-instance-profile \
  --instance-profile-name GitHubRunnerEC2Profile \
  --role-name GitHubRunnerEC2InstanceRole

# 10. Configure repository variables
gh variable set EC2_LAUNCH_ROLE --body "arn:aws:iam::YOUR_ACCOUNT_ID:role/GitHubActionsEC2LaunchRole"
gh variable set EC2_INSTANCE_PROFILE --body "GitHubRunnerEC2Profile"
```
</details>

## Acknowledgements <a id="acks"></a>
- This repo forked [omsf/start-aws-gha-runner]; it adds self-termination (bypassing [omsf/stop-aws-gha-runner]) and various features.
- [machulav/ec2-github-runner] is similar, [requires][egr ex] separate "start" and "stop" jobs
- [related-sciences/gce-github-runner] is a self-terminating GCE runner, using [job hooks][hooks])

Here's a diff porting [ec2-github-runner][machulav/ec2-github-runner]'s README [example][egr ex] to ec2-gha:
```diff
 name: do-the-job
 on: pull_request
 jobs:
-  start-runner:
+  ec2:
     name: Start self-hosted EC2 runner
-    runs-on: ubuntu-latest
-    outputs:
-      label: ${{ steps.start-ec2-runner.outputs.label }}
-      ec2-instance-id: ${{ steps.start-ec2-runner.outputs.ec2-instance-id }}
-    steps:
-      - name: Configure AWS credentials
-        uses: aws-actions/configure-aws-credentials@v4
+    uses: Open-Athena/ec2-gha/.github/workflows/runner.yml@v2
         with:
-          aws-access-key-id: ${{ secrets.AWS_ACCESS_KEY_ID }}
-          aws-secret-access-key: ${{ secrets.AWS_SECRET_ACCESS_KEY }}
-          aws-region: ${{ secrets.AWS_REGION }}
-      - name: Start EC2 runner
-        id: start-ec2-runner
-        uses: machulav/ec2-github-runner@v2
-        with:
-          mode: start
-          github-token: ${{ secrets.GH_PERSONAL_ACCESS_TOKEN }}
-          ec2-image-id: ami-123
-          ec2-instance-type: t3.nano
-          subnet-id: subnet-123
-          security-group-id: sg-123
-          iam-role-name: my-role-name # optional, requires additional permissions
-          aws-resource-tags: > # optional, requires additional permissions
-            [
-              {"Key": "Name", "Value": "ec2-github-runner"},
-              {"Key": "GitHubRepository", "Value": "${{ github.repository }}"}
-            ]
-          block-device-mappings: > # optional, to customize EBS volumes
-            [
-              {"DeviceName": "/dev/sda1", "Ebs": {"VolumeSize": 100, "VolumeType": "gp3"}}
-            ]
+      ec2_image_id: ami-123
+      ec2_instance_type: t3.nano
+      ec2_root_device_size: 100
+      ec2_subnet_id: subnet-123
+      ec2_security_group_id: sg-123
+      ec2_launch_role: my-role-name
+    secrets:
+      GH_SA_TOKEN: ${{ secrets.GH_PERSONAL_ACCESS_TOKEN }}
   do-the-job:
     name: Do the job on the runner
     needs: start-runner # required to start the main job when the runner is ready
     runs-on: ${{ needs.start-runner.outputs.label }} # run the job on the newly created runner
     steps:
       - name: Hello World
         run: echo 'Hello World!'
-  stop-runner:
-    name: Stop self-hosted EC2 runner
-    needs:
-      - start-runner # required to get output from the start-runner job
-      - do-the-job # required to wait when the main job is done
-    runs-on: ubuntu-latest
-    if: ${{ always() }} # required to stop the runner even if the error happened in the previous jobs
-    steps:
-      - name: Configure AWS credentials
-        uses: aws-actions/configure-aws-credentials@v4
-        with:
-          aws-access-key-id: ${{ secrets.AWS_ACCESS_KEY_ID }}
-          aws-secret-access-key: ${{ secrets.AWS_SECRET_ACCESS_KEY }}
-          aws-region: ${{ secrets.AWS_REGION }}
-      - name: Stop EC2 runner
-        uses: machulav/ec2-github-runner@v2
-        with:
-          mode: stop
-          github-token: ${{ secrets.GH_PERSONAL_ACCESS_TOKEN }}
-          label: ${{ needs.start-runner.outputs.label }}
-          ec2-instance-id: ${{ needs.start-runner.outputs.ec2-instance-id }}
```

[`runner.yml`]: .github/workflows/runner.yml
[aws-actions/configure-aws-credentials]: https://github.com/aws-actions/configure-aws-credentials
[hooks]: https://docs.github.com/en/actions/how-tos/manage-runners/self-hosted-runners/run-scripts
[omsf/start-aws-gha-runner]: https://github.com/omsf/start-aws-gha-runner
[omsf/stop-aws-gha-runner]: https://github.com/omsf/stop-aws-gha-runner
[machulav/ec2-github-runner]: https://github.com/machulav/ec2-github-runner
[egr ex]: https://github.com/machulav/ec2-github-runner?tab=readme-ov-file#example
[related-sciences/gce-github-runner]: https://github.com/related-sciences/gce-github-runner
[reusable workflow]: https://docs.github.com/en/actions/how-tos/reuse-automations/reuse-workflows#calling-a-reusable-workflow
[file an issue]: https://github.com/Open-Athena/ec2-gha/issues/new/choose
[SSH access]: #ssh
[cw]: #cloudwatch
[demos#25]: https://github.com/Open-Athena/ec2-gha/actions/runs/17004697889
