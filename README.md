# Kingdom Helm charts

This repository owns reusable Helm templates, defaults, schemas and chart tests.
It contains no image resolver, Compose compiler, OCI publisher or deployment
executor. Those CD mechanisms live in
[`dmitrichcom/deployments`](https://github.com/dmitrichcom/deployments).
Product values, runtime-input declarations, generated `rendered` history and the
workflow dispatch entry point belong to each `<product>-deployment` repository.

## `kingdom-workload` 0.2

The chart renders a map of independent Kubernetes workloads:

```yaml
stack: example-production
networks:
  backend: {internal: true}
  outbound: {internal: false}
workloads:
  app:
    kind: Deployment
    networks: [backend, outbound]
    podSpec:
      containers:
        - name: app
          image: ghcr.io/example/app:v1.2.3
          readinessProbe:
            exec: {command: [/app, healthcheck]}
    service:
      ports: [{name: http, port: 8080, targetPort: 8080}]
  postgres:
    kind: StatefulSet
    networks: [backend]
    workloadSpec:
      serviceName: postgres
    podSpec:
      containers:
        - name: postgres
          image: postgres:17-alpine
    service:
      clusterIP: None
      ports: [{name: postgres, port: 5432}]
```

| Value | Responsibility |
|---|---|
| `stack` | Default stack identity; defaults to the Helm release name. A workload may override it. |
| `workloads.<name>.kind` | `Deployment`, `StatefulSet` or `Job`. |
| `podSpec` | Native Kubernetes container, volume, security, probe and runtime configuration. |
| `replicas` | Native Deployment/StatefulSet replica count. Docker's supported scaling subset is checked by its CD adapter. |
| `workloadSpec` | Additional native workload specification, such as `serviceName`, `volumeClaimTemplates` or Job `backoffLimit`. Template, selectors and replica fields are chart-owned. |
| `service` | Native Service specification. The chart owns its workload selector. |
| `podAnnotations`, `podLabels`, `annotations` | Metadata. Generated identity/network keys cannot be overridden. |
| `networks` | Declared connectivity groups with explicit `internal` flags. Every workload selects its groups when the map is nonempty. |
| `resources` | Additional native Kubernetes objects, such as ConfigMaps and PVCs. Backend capability validation remains a CD responsibility. |

Images are complete references selected by the product. Different containers can
use different registries and versions. Registry ownership, Semantic Versioning
release policy, digest resolution and promotion authorization are not chart rules.
Jobs default explicitly to `restartPolicy: Never` and `backoffLimit: 0`.

## Connectivity

Each workload's groups produce native pod labels and a native NetworkPolicy.
Peers are scoped to the same stack. Internal groups allow ingress/egress only
among their members; a non-internal group permits external egress. There is no
automatic DNS or internet exception for isolated workers. The same declaration
is encoded in a typed `kingdom.dmitrich.com/compose-networks` annotation for the
Docker adapter, which checks the native policy before emitting Compose networks.

The chart therefore records network intent in Kubernetes resources as well as
backend metadata. A Kubernetes deployment needs a CNI that enforces those
policies, its RuntimeClasses, storage provisioning and runtime secret bindings.
Specific Docker host mappings stay in backend annotations; `host-gateway` is
never a Kubernetes `hostAliases.ip` value. The Docker adapter's supported subset
and explicit errors are documented in `deployments/render/README.md`.

## Development and CI

Run `qgate run` with Helm 3.19.0 and PyYAML 6.0.3 available. The gate lints and
renders native workloads, Services, ConfigMaps and NetworkPolicies, and checks
independent image references and invalid inputs. CI calls the immutable
`ci-workflows` quality verifier with `--only-fresh` behavior. Test execution and
the generated `quality-gates.lock` remain QGate's responsibility.

The 0.2 values API replaces the old single `name/podSpec` chart interface. Existing
consumers remain reproducible through their already pinned chart commits. New
deployment repositories use the workload map. The previous `ops/shadow` compiler
and image-pinning scripts have moved into the separate CD responsibilities in
`deployments/render` and `deployments/runtime`; the chart contains only Helm logic.
