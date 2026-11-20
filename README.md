# Kingdom charts

Versioned, portable **Kubernetes Helm source**. Rendering happens in GitHub Actions, not on the VPS. No cluster, controller, or additional runtime service is installed on the host.

`charts/kingdom-workload` renders one standard Kubernetes `Deployment` and, optionally, a `Service`. Its values are a Kubernetes `PodSpec` plus metadata. Docker-specific compatibility is deliberately **not** part of the general chart: it belongs to the separately tested Kingdom compiler extension. Kubernetes ignores those annotations safely.

Environment files belong to the private [kingdom-environments](https://github.com/dmitrichcom/kingdom-environments) repository, while application source remains independently publishable. Source revision is pinned in the environment CI.

To inspect locally:

```sh
helm template stations-gateway ./charts/kingdom-workload -f /path/to/kingdom-environments/environments/production/stations-gateway/values.yaml
```

A future Argo CD `Application` can reference this chart and the environment values through Argo CD multi-source Helm value files. The chart is not tied to Docker or Kingdom.


## Build-time Kingdom backend

`ops/shadow/compile.py` adapts the pinned `helmfile2compose` output into the
exact Kingdom OCI v2 runtime bundle contract. The source is intentionally kept
alongside the portable Helm chart so downstream CI can check it out using only
read access to this public repository; no personal access token or repository
secret is needed to fetch a private CI workflow implementation.

The adapter never runs on the VPS, ships no secret values, and requires strict
structural parity against an explicit golden production Compose model.

Validation: `qgate run --only-fresh` or `sh scripts/test-compiler.sh`.
