# GitHub Actions Workflows

This directory contains the reusable workflow and demo workflows for ec2-gha.

## Core Workflow

### [`runner.yml`](runner.yml)

See the [main README](../../README.md) for complete documentation on:
- [Quick Start](../../README.md#quick-start) - How to use the reusable workflow
- [Inputs](../../README.md#inputs) - All available inputs and their defaults
- [Outputs](../../README.md#outputs) - Available outputs for job coordination
- [Technical Details](../../README.md#technical) - Implementation details and troubleshooting

## Demo Workflows

These workflows demonstrate various ec2-gha capabilities:

### [`demo-gpu-minimal.yml`](demo-gpu-minimal.yml)
Minimal example that launches a GPU instance and runs `nvidia-smi` to verify GPU access.
- **Instance type:** `g4dn.xlarge`
- **Use case:** Quick GPU availability test

### [`demo-gpu-job-seq.yml`](demo-gpu-job-seq.yml)
Comprehensive GPU workload with sequential jobs that:
- Runs 3 jobs sequentially on the same GPU instance (prepare, train, evaluate)
- Installs PyTorch with CUDA support
- Runs GPU benchmark with matrix operations and training simulation
- Verifies same GPU is used across all jobs
- Demonstrates instance reuse for multi-stage ML workflows
- **Instance type:** `g4dn.xlarge`
- **Use case:** ML/AI workflow testing with GPU acceleration

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

