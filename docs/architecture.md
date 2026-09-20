# Architecture

Single-node K3s cluster where WebAssembly pods and regular container pods are scheduled side by side.
The only difference from Kubernetes' point of view is `runtimeClassName` on the WASM Deployment.

```mermaid
flowchart TB
  client([Client])

  subgraph node["K3s node: Ubuntu 26.04, x86_64, 12 CPU"]
    traefik["Traefik Ingress<br/>wasm.local / container.local / python.local"]

    subgraph kedans["namespace: keda"]
      interceptor["KEDA HTTP interceptor proxy<br/>holds requests while replicas = 0"]
      scaler["HTTP external scaler"]
      kedaop["KEDA operator<br/>scales Deployments 0 to N"]
    end

    subgraph defns["namespace: default"]
      svcw["Service wasm-echo"] --> podw["Pod wasm-echo<br/>runtimeClassName: wasmtime-spin-v2"]
      svcc["Service container-echo"] --> podc["Pod container-echo<br/>Rust static binary, scratch image"]
      svcp["Service container-python"] --> podp["Pod container-python<br/>Flask + gunicorn"]
    end

    subgraph ctrd["containerd (embedded in K3s)"]
      shimspin["containerd-shim-spin-v2<br/>Wasmtime, handler: spin"]
      runc["default runtime: runc"]
    end
  end

  registry[("Local registry :5000<br/>Docker container")]

  client --> traefik
  traefik --> svcw
  traefik --> svcc
  traefik --> svcp

  client -. "scale-to-zero benchmark path" .-> interceptor
  interceptor --> svcw
  interceptor --> svcc
  interceptor --> svcp
  interceptor -- "request metrics" --> scaler
  scaler --> kedaop

  podw -. "run by" .-> shimspin
  podc -. "run by" .-> runc
  podp -. "run by" .-> runc
  registry -. "image pull" .-> ctrd
```

## How the pieces map to this repo

| Piece | Where |
|---|---|
| K3s + Spin shim install | `scripts/01-install-k3s-wasm.sh` |
| RuntimeClass `wasmtime-spin-v2` (handler `spin`) | `k8s/base/runtimeclass-spin.yaml` |
| WASM app (Rust, Spin SDK 6, wasm32-wasip2) | `apps/wasm-echo/` |
| Container equivalents (Rust scratch, Python) | `apps/container-echo/`, `apps/container-python/` |
| Deployments, Services, Ingress | `k8s/base/` |
| Scale-to-zero (InterceptorRoute + ScaledObject) | `k8s/keda/scale-to-zero.yaml` |

## Notes on what the diagram does and does not show

- The scale-from-zero benchmark sent requests **directly to the interceptor's ClusterIP**, not through Traefik. Traefik-to-interceptor chaining was not built or tested.
- Containers run through the default runtime (`runc`); only the WASM pod goes through the Spin shim.
- The local registry runs in Docker on the host and is reached by K3s through `registries.yaml`.
