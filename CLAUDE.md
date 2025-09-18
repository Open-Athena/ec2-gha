# ec2-gha

**ec2-gha** is a GitHub Action for creating ephemeral, self-hosted GitHub Actions runners on AWS EC2 instances. These runners support GPU workloads, automatically terminate when idle, and can handle multi-job workflows.

## Common Development Commands

- Don't explicitly set the `AWS_PROFILE` (e.g. to `oa-ci-dev`) in your commands; assume it's set for you out of band, verify if you need.
- Instance userdata (rendered form of `src/ec2_gha/templates/user-script.sh.templ`) has to stay under 16KiB. We remove comments while "rendering", so the `templ` itself may be a bit over the limit.

### Testing
```bash
# Install test dependencies
pip install '.[test]'

# Run tests matching a pattern. You don't need to do this very often though.
cd tests/ && pytest -v -m 'not slow'

# Update `syrupy` "snapshots", run tests to verify they pass with (possibly-updated) snapshot values. Just a wrapper for:
# ```bash
# pytest --snapshot-update -m 'not slow'
# pytest -vvv -m 'not slow' .
# ```
# Update syrupy "snapshot" files. Can also be used in conjunction with `git rebase -x` (I'll mostly do that manually, when cleaning up commits).
scripts/update-snapshots.sh
```

### Linting
```bash
# Ruff is configured in pyproject.toml
ruff check src/
ruff format src/
```

## Key Architecture Components

### GitHub Actions Integration
- **`.github/workflows/runner.yml`**:
  - Main entrypoint, reusable workflow callable via external workflows' `job.uses`
  - Wraps the `action.yml` composite action
  - Outputs an `id` that subsequent jobs can pass to `job.runs-on`
- **`action.yml`**:
  - Composite action, wraps `Dockerfile` / `ec2_gha` Python module.
  - ≈20 input parameters, including:
    - AWS/EC2 configs (instance type, AMI, optional CloudWatch log group, keypair/pubkey for SSH-debugging, etc.)
    - GitHub runner configurations (timeouts / poll intervals, labels, etc.)
  - Outputs:
    - `mtx` (array of objects for matrix strategies)
    - When only one instance/runner is created, also outputs `label` and `instance-id`

### Core Python Modules
- **`src/ec2_gha/__main__.py`**: Entry point that parses environment variables and initiates runner creation
- **`src/ec2_gha/start.py`**: Contains `StartAWS` class handling EC2 operations, instance lifecycle, and template rendering

### Template and Script System
- **`src/ec2_gha/templates/user-script.sh.templ`**: Main userdata template using Python's String.Template format
- **`src/ec2_gha/scripts/runner-setup.sh`**: Main runner setup script fetched by userdata
- **`src/ec2_gha/scripts/job-started-hook.sh`**: GitHub Actions hook for job start events
- **`src/ec2_gha/scripts/job-completed-hook.sh`**: GitHub Actions hook for job completion
- **`src/ec2_gha/scripts/check-runner-termination.sh`**: Periodic termination check script

## Versioning and Security

### Action Ref Resolution
`runner.yml` requires an `action_ref` parameter that gets resolved to a Git SHA for security:
1. Python code resolves branch/tag references to immutable SHAs
2. All scripts are fetched using the resolved SHA to prevent TOCTOU attacks
3. This ensures the exact code version is used throughout execution

### Version Strategy
- Main branch (`v2`) contains stable releases
- `action_ref` defaults to the branch name in `runner.yml`
- Patch/minor version tags like `v2.0.0`, `v2.1.0` can be created from the `v2` branch

`ec2-gha`'s initial release uses a `v2` branch because the upstream `start-aws-gha-runner` has published some `v1*` tags.

### Usage Example
```yaml
# Caller workflow uses the v2 branch
uses: Open-Athena/ec2-gha/.github/workflows/runner.yml@v2
# The runner.yml on v2 branch has action_ref default of "v2"
# This gets resolved to a SHA at runtime for security
```

For complete usage examples, see `.github/workflows/demo*.yml`.

## Development Guidelines

### Template Modifications
When modifying the userdata template (`user-script.sh.templ`):
- Use `$variable` or `${variable}` syntax for template substitutions
- Escape literal `$` as `$$`
- Test template rendering in `tests/test_start.py`

### Environment Variables
The action uses a hierarchical input system:
1. Direct workflow inputs (highest priority)
2. Repository/organization variables (`vars.*`)
3. Default values

GitHub Actions declares env vars prefixed with `INPUT_` for each input, which `start.py` reads.

### Error Handling
- Use descriptive error messages that help users understand AWS/GitHub configuration issues
- Always clean up AWS resources on failure (instances, etc.)
- Log important operations to assist debugging

### Instance Lifecycle Management

#### Termination Logic
The runner uses a polling-based approach to determine when to terminate:

1. **Job Tracking**: GitHub runner hooks track job lifecycle
   - `job-started-hook.sh`: Creates JSON files in `/var/run/github-runner-jobs/`
   - `job-completed-hook.sh`: Removes job files and updates activity timestamp

2. **Periodic Polling**: Systemd timer runs `check-runner-termination.sh` every `runner_poll_interval` seconds (default: 10s)
   - Checks for running jobs (files with `"status":"running"`)
   - If no running jobs, compares idle time against grace period
   - Grace periods:
     - `runner_initial_grace_period` (default: 180s) - Before first job
     - `runner_grace_period` (default: 60s) - Between jobs

3. **Effective Termination Time**: Due to polling interval, actual termination occurs:
   - **Minimum**: grace_period seconds after last activity
   - **Maximum**: grace_period + runner_poll_interval seconds
   - Example: With 60s grace and 10s poll → terminates 60-70s after last job

4. **Clean Shutdown Sequence**:
   - Stop runner processes gracefully (SIGINT with timeout)
   - Deregister all runners from GitHub
   - Flush CloudWatch logs (if configured)

### AWS Resource Tagging
By default, launched EC2 instances are Tagged with:
- `Name`: `f"{repo}/{workflow}#{run}"`
- `Repository`: GitHub repository name
- `Workflow`: Workflow name
- `URL`: Direct link to the GitHub Actions run

## Important Implementation Details

### Multi-Job Support
- Runners are non-ephemeral to support instance reuse
- Job tracking via GitHub runner hooks (job-started, job-completed)
- Grace period prevents premature termination between sequential jobs

### Security Considerations
- Never log or expose AWS credentials or GitHub tokens
- Use IAM instance profiles for EC2 API access (not credentials)
- Support OIDC authentication for GitHub Actions

### CloudWatch Integration
When implementing CloudWatch features:
- Logs are streamed from specific paths defined in userdata template
- Instance profile (separate from launch role) required for CloudWatch API access
- Log group must exist before instance creation
- dpkg lock wait (up to 2 minutes) ensures CloudWatch agent installation succeeds on Ubuntu AMIs where cloud-init or unattended-upgrades may be running

## Testing Checklist

Before committing changes:
1. Run tests: `cd tests/ && pytest -v -m 'not slow'`
2. Verify template rendering doesn't break
