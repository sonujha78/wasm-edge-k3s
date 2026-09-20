# wasm-edge-k3s

Edge computing with WebAssembly on K3s.

Runs WASM workloads (Fermyon Spin via containerd-wasm-shims) side by side with
regular containers in the same K3s cluster, and benchmarks cold start, memory
footprint, scale-to-zero and behaviour on a resource-constrained edge node.

## Status
- [x] 1. Environment setup (K3s + wasm shims)
- [x] 2. Build WASM workload (Rust + spin-sdk)
- [x] 3. Deploy WASM + container side by side
- [ ] 4. Cold-start & memory comparison
- [ ] 5. Scale-to-zero test
- [ ] 6. Edge simulation (1 vCPU / 512MB)
- [ ] 7. Portability test (x86 vs ARM)
- [ ] 8. Documentation & trade-off analysis
