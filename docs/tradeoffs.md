# When to choose WASM, and when not to

Based on the measurements in [findings.md](findings.md). Everything marked *not tested* is background knowledge about the ecosystem, not something this project verified.

## Short answer

On this setup WASM was clearly better than a **typical interpreted-runtime container** (Python/Flask) on memory limit, density and runtime-level start time.
It was clearly worse than a **static native binary** (Rust in a `scratch` image) on memory, throughput and, in our Kubernetes scale-from-zero test, latency.
The question is not "WASM or containers" but "compared to what container".

| Measured | WASM (Spin) | Rust static container | Python container |
|---|---|---|---|
| Start without Kubernetes | 35 ms | 150 ms | 306 ms |
| Start as a K3s pod (Running) | 577 ms | 565 ms | 579 ms |
| Scale from zero via KEDA (request to response) | 2015 ms | 1246 ms | 1762 ms |
| Minimum memory limit that ran | 8 MiB (4 MiB degraded) | 4 MiB or less | 48 MiB |
| Pods under a 512Mi quota | 64 | 95 (capped by node pod limit) | 10 |
| Total memory incl. shim, idle | 42 MiB | 6.5 MiB | 57 MiB |
| Throughput at 20 connections | 11.6k req/s | 287k req/s | 2.8k req/s |

## Choose WASM when

- **The alternative is an interpreter or VM based container** (Python, Node, JVM) and memory per workload is the constraint. We saw 8 MiB vs 48 MiB minimum limit and 6.4x more pods under the same quota.
- **Many small, request-scoped handlers on limited hardware**, where you want to keep lots of them deployed. Density is the real business case; raw start time is not (see below).
- **Startup matters and the platform can start modules without creating a pod per instance.** The runtime itself started in ~35 ms, but a Kubernetes pod adds ~570 ms for every workload type. Running Spin apps in-process (for example with a Spin-native platform) was *not tested*, so the benefit there is unverified.
- **Untrusted or third-party code needs a tight sandbox.** Our `spin.toml` grants no outbound hosts (`allowed_outbound_hosts = []`) and the module has no other access unless granted. Capability-based isolation is a real design advantage; a security comparison was *not tested*.
- **A mixed x86/ARM fleet where one build artifact is convenient.** The same `.wasm` (identical sha256) ran on emulated arm64. The runtime still has to exist per architecture.

## Choose containers when

- **The service is already a small static binary (Rust, Go).** In our tests it used 4-10x less memory, served ~25x more requests per second, and had lower scale-from-zero latency than the WASM version.
- **CPU or throughput bound work.** Per-request instances and the WASI HTTP boundary cost real throughput.
- **Long-running, stateful, or syscall-heavy programs** (databases, anything needing broad filesystem, raw sockets, threads, subprocesses). Support depends on the WASI version and runtime; *not tested here*.
- **You depend on the container ecosystem**: sidecars, service mesh, profilers, `exec` into a running process, existing images. What works unchanged with WASM pods was *not tested* beyond kubectl, Services, Ingress and KEDA.
- **You cannot afford moving parts.** We hit these while building this project:
  - Spin CLI, Spin SDK and the shim's embedded Spin version must line up (shim v0.25.1 embeds Spin 4.0.1; Spin 4 moved Rust templates to `wasm32-wasip2`).
  - The KEDA HTTP add-on replaced `HTTPScaledObject` with `InterceptorRoute` in v0.14, so older tutorials no longer apply.
  - Our SDK build pulled in a crate tagged as a WASI 0.3 release candidate, which suggests the API surface is still moving.
- **Memory limits and quotas will under-count.** WASM pods showed ~4 MiB in their cgroup while ~10-20 MiB of host RAM was actually used per pod (shim processes sit outside the pod cgroup). Capacity planning from quotas alone would be optimistic.

## What we did not test (so no claim is made)

- Real ARM hardware, or a genuine 1 vCPU / 512 MB machine.
- Applications larger than an echo service; anything with state, files, databases or outbound calls.
- A tuned Python deployment, or Go/other native containers.
- CPU-bound workloads, request bodies, and long-running connections.
- Observability, debugging and profiling of WASM workloads.
- Running many Spin apps inside one process/shim instead of one pod per app.

## What would change the conclusion

- If pod creation were cheap (or modules started without pods), WASM's 35 ms start would matter much more than the 570 ms Kubernetes overhead we measured.
- If the comparison were against a distroless Go/Rust container instead of Python, WASM's density advantage would likely disappear (the static Rust container beat it here).
- If shim memory were shared across many WASM pods, the per-pod host cost could drop; we saw it vary from ~10 to ~20 MiB and did not isolate why.
