# `ec2-gha` Demos
This directory contains the reusable workflow and demo workflows for ec2-gha, demonstrating various capabilities.

For documentation about the main workflow, [`runner.yml`](runner.yml), see [the main README](../../README.md).

<!-- toc -->
- [GPU demos](#gpu)
    - [`gpu-minimal` – `nvidia-smi` "hello world"](#gpu-minimal)
    - [`gpu-job-seq` – GPU train/test/eval (sequential jobs)](#gpu-job-seq)
    - [Real-world example: Mamba installation testing](#mamba)
- [Architecture & Parallelization](#arch)
    - [`demos` – run all demo workflows](#demos)
    - [`archs` – launch x86 and ARM nodes](#archs)
    - [`multi-instance` – launch multiple instances, use in matrix](#multi-instance)
    - [`multi-job` – launch multiple instances, use individually](#multi-job)
<!-- /toc -->

## [`demos`](demos.yml) – run all demo workflows <a id="demos"></a>
Useful regression test, demonstrates and verifies features.

[![](../../img/demos%2325%201.png)][demos#25]

## GPU demos <a id="gpu"></a>

### [`gpu-minimal`](demo-gpu-minimal.yml) – `nvidia-smi` "hello world" <a id="gpu-minimal"></a>
- **Instance type:** `g4dn.xlarge`

### [`gpu-job-seq`](demo-gpu-job-seq.yml) – GPU train/test/eval (sequential jobs) <a id="gpu-job-seq"></a>
- Runs 3 jobs sequentially on the same GPU instance (prepare, train, evaluate)
- Uses pre-installed PyTorch from Deep Learning AMI's conda environment
- Runs GPU benchmark with matrix operations and training simulation
- Verifies same GPU is used across all jobs
- Demonstrates instance reuse for multi-stage ML workflows
- **Instance type:** `g4dn.xlarge`
- **Use case:** ML/AI workflow testing with GPU acceleration

### Real-world example: [Mamba installation testing](https://github.com/Open-Athena/mamba/blob/gha/.github/workflows/install.yaml) <a id="mamba"></a>
- Tests different versions of `mamba_ssm` package on GPU instances
- **Customizes `instance_name`**: `"$repo/$name==${{ inputs.mamba_version }} (#$run_number)"`
  - Results in descriptive names like `"Open-Athena/mamba/install==2.2.5 (#123)"`
  - Makes it easy to identify which version is being tested on each instance
- Uses pre-installed PyTorch from DLAMI conda environment
- **Use case:** Package compatibility testing across versions

[![](../../img/mamba%2312.png)][mamba#12]

## Architecture & Parallelization <a id="arch"></a>

### [`archs`](demo-archs.yml) – launch x86 and ARM nodes <a id="archs"></a>
- Verify architecture-specific behavior
- **Instance types:** `t3.medium` (x86), `t4g.medium` (ARM)

### [`multi-instance`](demo-multi-instance.yml) – launch multiple instances, use in matrix <a id="multi-instance"></a>
- Creates configurable number of instances (default: 3)
- Uses matrix strategy to run jobs in parallel
- Each job runs on its own EC2 instance
- **Customizes `instance_name`**: `"$repo/$name-$idx (#$run_number)"`
  - Uses `$idx` template variable (0-based index) to distinguish instances
  - Results in names like `"ec2-gha/multi-instance-0 (#123)"`, `"ec2-gha/multi-instance-1 (#123)"`, etc.
- **Instance type:** `t3.medium`
- **Use case:** Parallel test execution

### [`multi-job`](demo-multi-job.yml) – launch multiple instances, use individually <a id="multi-job"></a>
- Launch 2 instances
- Run build job on first instance
- Run test job on second instance
- Aggregate results from both instances
- **Customizes `instance_name`**: `"$repo/$name-$idx (#$run_number)"`
  - Results in names like `"ec2-gha/multi-job-0 (#123)"` and `"ec2-gha/multi-job-1 (#123)"`
- **Instance type:** `t3.medium`
- **Use case:** Pipeline with dedicated instances per stage

[mamba#12]: https://github.com/Open-Athena/mamba/actions/runs/16972369660/
[demos#25]: https://github.com/Open-Athena/ec2-gha/actions/runs/17004697889

