# Kingdom charts

Versioned, portable **Kubernetes Helm source**. Rendering happens in GitHub Actions, not on the VPS. No cluster, controller, or additional runtime service is installed on the host.

`charts/kingdom-workload` renders one standard Kubernetes `Deployment` and, optionally, a `Service`. Its values are a Kubernetes `PodSpec` plus metadata. Docker-specific compatibility is deliberately **not** part of the general chart: it belongs to the separately tested Kingdom compiler extension. Kubernetes ignores those annotations safely.

Environment files belong to the private [kingdom-environments](https://github.com/dmitrichcom/kingdom-environments) repository, while application source remains independently publishable. Source revision is pinned in the environment CI.

To inspect locally:

```sh
helm template stations-gateway ./charts/kingdom-workload -f /path/to/kingdom-environments/environments/production/stations-gateway/values.yaml
```

A future Argo CD `Application` can reference this chart and the environment values through Argo CD multi-source Helm value files. The chart is not tied to Docker or Kingdom.
