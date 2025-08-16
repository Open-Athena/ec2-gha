# `ec2-gha` Demos
This directory contains the reusable workflow and demo workflows for ec2-gha, demonstrating various capabilities.

For documentation about the main workflow, [`runner.yml`](runner.yml), see [the main README](../../README.md).

<!-- toc -->
- [GPU demos](#gpu)
    - [`gpu-minimal` – `nvidia-smi` "hello world"](#gpu-minimal)
    - [`gpu-job-seq` – GPU train/test/eval (sequential jobs)](#gpu-job-seq)
- [Architecture & Parallelization](#arch)
    - [`demos` – run all demo workflows](#demos)
    - [`archs` – launch x86 and ARM nodes](#archs)
    - [`multi-instance` – launch multiple instances, use in matrix](#multi-instance)
    - [`multi-job` – launch multiple instances, use individually](#multi-job)
<!-- /toc -->


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

## Architecture & Parallelization <a id="arch"></a>

### [`demos`](demos.yml) – run all demo workflows <a id="demos"></a>
Useful regression test, demonstrates and verifies features.

### [`archs`](demo-archs.yml) – launch x86 and ARM nodes <a id="archs"></a>
- Verify architecture-specific behavior
- Customizes `instance_name` to distinguish architectures (e.g., `repo/name-x86`)
- **Instance types:** `t3.medium` (x86), `t4g.medium` (ARM)

### [`multi-instance`](demo-multi-instance.yml) – launch multiple instances, use in matrix <a id="multi-instance"></a>
- Creates configurable number of instances (default: 3)
- Uses matrix strategy to run jobs in parallel
- Each job runs on its own EC2 instance
- **Instance type:** `t3.medium`
- **Use case:** Parallel test execution

### [`multi-job`](demo-multi-job.yml) – launch multiple instances, use individually <a id="multi-job"></a>
- Launch 2 instances
- Run build job on first instance
- Run test job on second instance
- Aggregate results from both instances
- **Instance type:** `t3.medium`
- **Use case:** Pipeline with dedicated instances per stage

