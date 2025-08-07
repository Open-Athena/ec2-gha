# ec2-gha
Run GitHub Actions on ephemeral EC2 instances.

**TOC**
<!-- toc -->
- [Quick Start](#quick-start)
- [Inputs](#inputs)
    - [Required](#required)
        - [`secrets.GH_SA_TOKEN`](#gh-sa-token)
        - [`ec2_launch_role` / `vars.EC2_LAUNCH_ROLE`](#ec2-launch-role)
    - [Optional](#optional)
- [Outputs](#outputs)
- [Technical Details](#technical)
    - [Runner Lifecycle](#lifecycle)
    - [Multi-Job Workflows](#multi-job)
    - [How Termination Works](#termination)
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
  gpu-test:
    needs: ec2
    runs-on: ${{ needs.ec2.outputs.instance }}
    steps:
      - run: nvidia-smi  # GPU node!
```

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

- `action_ref` - ec2-gha Git ref to checkout (branch/tag/SHA); auto-detected if not specified
- `ec2_home_dir` - Home directory (default: `/home/ubuntu`)
- `ec2_image_id` - AMI ID (default: Deep Learning AMI)
- `ec2_instance_profile` - IAM instance profile name for EC2 instances
  - Useful for on-instance debugging [via SSH][SSH access]
  - Falls back to `vars.EC2_INSTANCE_PROFILE`
  - See [Appendix: IAM Role Setup](#iam-setup-appendix) for more details and sample setup code
- `ec2_instance_type` - Instance type (default: `g4dn.xlarge`)
- `ec2_key_name` - EC2 key pair name (for [SSH access])
- `ec2_root_device_size` - Root device size in GB (default: 0 = use AMI default)
- `ec2_security_group_id` - Security group ID (required for [SSH access], should expose inbound port 22)
- `max_instance_lifetime` - Maximum instance lifetime in minutes before automatic shutdown (falls back to `vars.MAX_INSTANCE_LIFETIME`, default: 360 = 6 hours; generally should not be relevant, instances shut down within 1-2mins of jobs completing)
- `runner_grace_period` - Grace period in seconds before terminating after last job completes (default: 60)
- `runner_initial_grace_period` - Grace period in seconds before terminating instance if no jobs start (default: 180)
- `runner_poll_interval` - How often (in seconds) to check termination conditions (default: 10)
- `ssh_pubkey` - SSH public key (for [SSH access])

## Outputs <a id="outputs"></a>

| Name | Description                                 |
|------|---------------------------------------------|
| id   | Value to pass to subsequent jobs' `runs-on` |

## Technical Details <a id="technical"></a>

### Runner Lifecycle <a id="lifecycle"></a>

This workflow creates EC2 instances with GitHub Actions runners that:
- Automatically register with your repository
- Support both single and multi-job workflows
- Self-terminate when work is complete
- Use [GitHub's native runner hooks][hooks] for job tracking
- Optionally support [SSH access] and [CloudWatch logging][cw] (for debugging)

### Multi-Job Workflows <a id="multi-job"></a>

The runner supports multiple sequential jobs on the same instance, e.g.:

```yaml
jobs:
  ec2:
    uses: Open-Athena/ec2-gha/.github/workflows/runner.yml@main
    secrets: inherit
    with:
      runner_grace_period: "120"  # 2 minutes between jobs

  prepare:
    needs: ec2
    runs-on: ${{ needs.ec2.outputs.instance }}
    steps:
      - run: echo "Preparing environment"

  train:
    needs: [ec2, prepare]
    runs-on: ${{ needs.ec2.outputs.instance }}
    steps:
      - run: echo "Training model"

  evaluate:
    needs: [ec2, train]
    runs-on: ${{ needs.ec2.outputs.instance }}
    steps:
      - run: echo "Evaluating results"
```

### Termination logic <a id="termination"></a>

The runner uses [GitHub Actions runner hooks][hooks] to track job start/end events, and a `systemd` timer to poll for when there's:
1. no active jobs running, and
2. no job starts or ends in at least `runner_grace_period` seconds.

Job start/end events `touch` a "last activity" timestamp file (`/var/run/github-runner-last-activity`), and the systemd timer checks this file every `runner_poll_interval` seconds (default: 10s).

Each job's status is tracked in a JSON file like `/var/run/github-runner-jobs/<job_id>.job`.

The default `runner_grace_period` is 60s, but a longer `runner_initial_grace_period` (default: 180s) is used for the first job after instance boot (to allow time for the runner to register and start).

When terminating, the runner:
- Gracefully stops the runner process
- Removes itself from GitHub
- Flushes CloudWatch logs

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
- `/tmp/job-started-hook.log` - Job start tracking
- `/tmp/job-completed-hook.log` - Job completion tracking
- `/tmp/termination-check.log` - Termination check logs (runs every 30 seconds)
- `/var/run/github-runner-jobs/*.job` - Individual job status files
- `~/actions-runner/_diag/*.log` - GitHub runner diagnostic logs

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

# 5. Configure repository variables
gh variable set EC2_LAUNCH_ROLE --body "arn:aws:iam::YOUR_ACCOUNT_ID:role/GitHubActionsEC2LaunchRole"
gh variable set EC2_INSTANCE_PROFILE --body "GitHubRunnerEC2Profile"
```
</details>

## Acknowledgements <a id="acks"></a>
This repo borrows from or reuses:
- [omsf/start-aws-gha-runner] (upstream; this fork adds self-termination and various features)
- [related-sciences/gce-github-runner] (self-terminating GCE runner, using [job hooks][hooks])

[`runner.yml`]: .github/workflows/runner.yml
[demo-multi-job.yml]: .github/workflows/demo-multi-job.yml
[aws-actions/configure-aws-credentials]: https://github.com/aws-actions/configure-aws-credentials
[hooks]: https://docs.github.com/en/actions/how-tos/manage-runners/self-hosted-runners/run-scripts
[omsf/start-aws-gha-runner]: https://github.com/omsf/start-aws-gha-runner
[related-sciences/gce-github-runner]: https://github.com/related-sciences/gce-github-runner
[reusable workflow]: https://docs.github.com/en/actions/how-tos/reuse-automations/reuse-workflows#calling-a-reusable-workflow
[file an issue]: https://github.com/Open-Athena/ec2-gha/issues/new/choose
[SSH access]: #ssh
