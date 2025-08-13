# ec2-gha

**ec2-gha** is a GitHub Action for creating ephemeral, self-hosted GitHub Actions runners on AWS EC2 instances. These runners support GPU workloads, automatically terminate when idle, and can handle multi-job workflows.

## Common Development Commands

- Don't explicitly set the `AWS_PROFILE` (e.g. to `oa-ci-dev`) in your commands; assume it's set for you out of band, verify if you need.
- Instance userdata (rendered form of `src/ec2_gha/templates/user-script.sh.templ`) has to stay under 16KiB.

### Testing
```bash
# Install test dependencies
pip install '.[test]'

# Run tests matching a pattern
cd tests/ && pytest -v -m 'not slow'

# Update `syrupy` "snapshots", run tests to verify they pass with (possibly-updated) snapshot values. Just a wrapper for:
# ```bash
# pytest --snapshot-update -m 'not slow'
# pytest -vvv -m 'not slow' .
# ```
# Can be used in conjunction with `git rebase -x`.
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
    - `mapping`, `instances`
    - When only one instance/runner is created, also outputs `label` and `instance-id`

### Core Python Modules
- **`src/ec2_gha/__main__.py`**: Entry point that parses environment variables and initiates runner creation
- **`src/ec2_gha/start.py`**: Contains `StartAWS` class handling EC2 operations, instance lifecycle, and template rendering

### Template System
- **`src/ec2_gha/templates/user-script.sh.templ`**: Main userdata template using Python's String.Template format, includes inline runner lifecycle hooks

## Versioning

`runner.yml` runs `actions/checkout` on this repo but, when called from another workflow, GitHub Actions provides no way to checkout the same ref that this workflow was called at. To avoid this, `inputs.action_ref` gets a default value corresponding to a branch or tag name that each commit (in this repo) is expected to be referenced as (e.g. `v2`). This allows the workflow to check out the correct code without the user needing to explicitly pass an `action_ref` input.

Patch/minor version tags like `v2.0.0`, `v2.1.0` can be created from the `v2` branch, with the `action_ref` default pinned to those values (similar to syncing a project's `pyproject.toml` version with a Git tag pointing at a given commit).

`ec2-gha`'s initial release uses a `v2` branch because the upstream `start-aws-gha-runner` has published some `v1*` tags.

### Usage Example
```yaml
# Caller workflow uses the v2 branch
uses: Open-Athena/ec2-gha/.github/workflows/runner.yml@v2
# The runner.yml on v2 branch has action_ref default of "v2", so it automatically checks out the correct code
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

1. **Job Tracking**: GitHub runner hooks (`job-started`, `job-completed`) track job lifecycle
   - Creates/updates JSON files in `/var/run/github-runner-jobs/`
   - Updates "last activity" timestamp at `/var/run/github-runner-last-activity`

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
   - Stop runner process gracefully (SIGINT)
   - Remove runner from GitHub (`config.sh remove`)
   - Flush CloudWatch logs
   - Execute `shutdown -h now`

### AWS Resource Tagging
By default, launched EC2 instances are Tagged with:
- `Name`: `f"{repo}/{workflow}#{run_number}"`
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
