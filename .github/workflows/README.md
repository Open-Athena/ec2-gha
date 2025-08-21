# `ec2-gha` Demos
This directory contains the reusable workflow and demo workflows for ec2-gha, demonstrating various capabilities.

For documentation about the main workflow, [`runner.yml`](runner.yml), see [the main README](../../README.md).

<!-- toc -->
- [`demos` – run all demo workflows](#demos)
- [Core demos](#core)
    - [`dbg-minimal` – configurable debugging instance](#dbg-minimal)
    - [`gpu-minimal` – `nvidia-smi` "hello world"](#gpu-minimal)
    - [`cpu-sweep` – OS/architecture matrix](#cpu-sweep)
    - [`gpu-sweep` – GPU instance types with PyTorch](#gpu-sweep)
- [Parallelization](#parallel)
    - [`instances-mtx` – multiple instances for parallel jobs](#instances-mtx)
    - [`runners-mtx` – multiple runners on single instance](#runners-mtx)
    - [`jobs-split` – different job types on separate instances](#jobs-split)
- [Real-world example: Mamba installation testing](#mamba)
<!-- /toc -->

## [`demos`](demos.yml) – run all demo workflows <a id="demos"></a>
Useful regression test, demonstrates and verifies features.

[![](../../img/demos%2325%201.png)][demos#25]

## Core demos <a id="core"></a>

### [`dbg-minimal`](demo-dbg-minimal.yml) – configurable debugging instance <a id="dbg-minimal"></a>
- `workflow_dispatch` with customizable parameters (instance type, AMI, timeouts)
- Also callable via `workflow_call` (used by `cpu-sweep`)
- Extended debug mode for troubleshooting
- **Instance type:** `t3.large` (default), configurable
- **Use case:** Interactive debugging and testing

### [`gpu-minimal`](demo-gpu-minimal.yml) – `nvidia-smi` "hello world" <a id="gpu-minimal"></a>
- **Instance type:** `g4dn.xlarge`

### [`cpu-sweep`](demo-cpu-sweep.yml) – OS/architecture matrix <a id="cpu-sweep"></a>
- Tests 12 combinations across operating systems and architectures
- **OS:** Ubuntu 22.04/24.04, Debian 11/12, AL2, AL2023
- **Architectures:** x86 (`t3.*`) and ARM (`t4g.*`)
- Calls `dbg-minimal` for each combination
- **Use case:** Cross-platform compatibility testing

### [`gpu-sweep`](demo-gpu-sweep.yml) – GPU instance types with PyTorch <a id="gpu-sweep"></a>
- Tests different GPU instance families
- **Instance types:** `g4dn.xlarge`, `g5.xlarge`, `g6.xlarge`, `g5g.xlarge` (ARM64 + GPU)
- Uses Deep Learning OSS PyTorch 2.5.1 AMIs
- Activates conda environment and runs PyTorch CUDA tests
- **Use case:** GPU compatibility and performance testing

## Parallelization <a id="parallel"></a>

### [`instances-mtx`](demo-instances-mtx.yml) – multiple instances for parallel jobs <a id="instances-mtx"></a>
- Creates configurable number of instances (default: 3)
- Uses matrix strategy to run jobs in parallel
- Each job runs on its own EC2 instance
- **Instance type:** `t3.medium`
- **Use case:** Parallel test execution, distributed builds

### [`runners-mtx`](demo-runners-mtx.yml) – multiple runners on single instance <a id="runners-mtx"></a>
- Configurable runners per instance (default: 3)
- All runners share the same instance resources
- Demonstrates resource-efficient parallel execution
- **Instance type:** `t3.xlarge` (larger instance for multiple runners)
- **Use case:** Shared environment testing, resource optimization

### [`jobs-split`](demo-jobs-split.yml) – different job types on separate instances <a id="jobs-split"></a>
- Launches 2 instances
- Build job runs on first instance (`runners[0]`)
- Test job runs on second instance (`runners[1]`)
- Demonstrates targeted job placement
- **Instance type:** `t3.medium`
- **Use case:** Pipeline with dedicated instances per stage

## Real-world example: [Mamba installation testing](https://github.com/Open-Athena/mamba/blob/gha/.github/workflows/install.yaml) <a id="mamba"></a>
- Tests different versions of `mamba_ssm` package on GPU instances
- **Customizes `instance_name`**: `"$repo/$name==${{ inputs.mamba_version }} (#$run)"`
  - Results in descriptive names like `"mamba/install==2.2.5 (#123)"`
  - Makes it easy to identify which version is being tested on each instance
- Uses pre-installed PyTorch from DLAMI conda environment
- **Use case:** Package compatibility testing across versions

[![](../../img/mamba%2312.png)][mamba#12]

[mamba#12]: https://github.com/Open-Athena/mamba/actions/runs/16972369660/
[demos#25]: https://github.com/Open-Athena/ec2-gha/actions/runs/17004697889
