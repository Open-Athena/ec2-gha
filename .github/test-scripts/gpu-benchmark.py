#!/usr/bin/env python3
"""GPU benchmark script for testing PyTorch CUDA capabilities.

Used by ``demo-gpu.yml``.
"""

import sys
import time
import torch


def main():
    print(f'PyTorch version: {torch.__version__}')
    print(f'CUDA available: {torch.cuda.is_available()}')

    if not torch.cuda.is_available():
        print('ERROR: CUDA not available!')
        sys.exit(1)

    # Get GPU information
    device = torch.cuda.get_device_properties(0)
    print(f'GPU: {device.name}')
    print(f'Memory: {device.total_memory / 1e9:.1f} GB')
    print(f'CUDA version: {torch.version.cuda}')

    # Matrix multiplication benchmark
    print('\nRunning matrix multiplication benchmark...')
    size = 8192
    x = torch.randn(size, size, dtype=torch.float32).cuda()
    torch.cuda.synchronize()

    # Warmup
    print('  Warming up...')
    for _ in range(3):
        _ = torch.matmul(x, x.T)
    torch.cuda.synchronize()

    # Benchmark
    print('  Running benchmark...')
    start = time.time()
    y = torch.matmul(x, x.T)
    torch.cuda.synchronize()
    elapsed = time.time() - start

    gflops = (2 * size**3) / (elapsed * 1e9)
    print(f'  Matrix size: {size}x{size}')
    print(f'  Time: {elapsed:.3f} seconds')
    print(f'  Performance: {gflops:.1f} GFLOPS')
    print(f'  Memory used: {torch.cuda.max_memory_allocated()/1e9:.2f} GB')

    # Quick training simulation
    print('\nSimulating model training...')
    model = torch.nn.Sequential(
        torch.nn.Linear(1024, 512),
        torch.nn.ReLU(),
        torch.nn.Linear(512, 256),
        torch.nn.ReLU(),
        torch.nn.Linear(256, 10)
    ).cuda()

    optimizer = torch.optim.Adam(model.parameters())
    data = torch.randn(32, 1024).cuda()

    for i in range(10):
        output = model(data)
        loss = output.sum()
        loss.backward()
        optimizer.step()
        optimizer.zero_grad()
        if i == 0 or i == 9:
            print(f'  Iteration {i+1}: loss = {loss.item():.4f}')

    print('\nGPU workload completed successfully!')
    return 0


if __name__ == '__main__':
    sys.exit(main())
