# Kingdom Helm charts

This repository owns reusable Helm templates, defaults, schemas and chart tests.
It contains no image resolver, Compose compiler, OCI publisher or deployment
executor. Those CD mechanisms live in
[`dmitrichcom/deployments`](https://github.com/dmitrichcom/deployments).
Product values, runtime-input declarations, generated `rendered` history and the
workflow dispatch entry point belong to each `<product>-deployment` repository.

## `kingdom-workload` 0.3

The chart renders a map of independent Kubernetes workloads:

```yaml
stack: example-production
workloads:
  app:
    kind: Deployment
    podSpec:
      containers:
        - name: app
          image: ghcr.io/example/app:v1.2.3
          ports: [{name: http, containerPort: 8080}]
          readinessProbe:
            exec: {command: [/app, healthcheck]}
    service:
      clusterIP: None
      publishNotReadyAddresses: true
      ports: [{name: http, port: 8080, targetPort: http}]
  postgres:
    kind: StatefulSet
    workloadSpec:
      serviceName: postgres
    podSpec:
      containers:
        - name: postgres
          image: postgres:17-alpine
          ports: [{name: postgres, containerPort: 5432}]
    service:
      clusterIP: None
      publishNotReadyAddresses: true
      ports: [{name: postgres, port: 5432, targetPort: postgres}]
resources:
  - apiVersion: networking.k8s.io/v1
    kind: NetworkPolicy
    metadata: {name: app-connectivity}
    spec:
      podSelector: {matchLabels: {app.kubernetes.io/name: app}}
      policyTypes: [Ingress, Egress]
      ingress:
        - from: [{podSelector: {matchLabels: {app.kubernetes.io/name: postgres}}}]
      egress: [{}]
  - apiVersion: networking.k8s.io/v1
    kind: NetworkPolicy
    metadata: {name: postgres-connectivity}
    spec:
      podSelector: {matchLabels: {app.kubernetes.io/name: postgres}}
      policyTypes: [Ingress, Egress]
      ingress:
        - from: [{podSelector: {matchLabels: {app.kubernetes.io/name: app}}}]
      egress:
        - to: [{podSelector: {matchLabels: {app.kubernetes.io/name: app}}}]
```

| Value | Responsibility |
|---|---|
| `stack` | Default stack identity; defaults to the Helm release name. A workload may override it. |
| `workloads.<name>.kind` | `Deployment`, `StatefulSet` or `Job`. |
| `podSpec` | Native Kubernetes container, volume, security, probe and runtime configuration. |
| `replicas` | Native Deployment/StatefulSet replica count. Docker's supported scaling subset is checked by its CD adapter. |
| `workloadSpec` | Additional native workload specification, such as `serviceName`, `volumeClaimTemplates` or Job `backoffLimit`. Template, selectors and replica fields are chart-owned. |
| `service` | Native Service specification. The chart owns its workload selector. |
| `podAnnotations`, `podLabels`, `annotations` | Metadata. Chart-owned workload identity keys cannot be overridden. |
| `telemetry.traces` | Opt in to platform OTLP trace ingestion. The Docker adapter checks that native policy permits the required outbound connection. |
| `resources` | Additional native Kubernetes objects, including NetworkPolicies, ConfigMaps and PVCs. Backend capability validation remains a CD responsibility. |

Images are complete references selected by the product. Different containers can
use different registries and versions. Registry ownership, Semantic Versioning
release policy, digest resolution and promotion authorization are not chart rules.
Jobs default explicitly to `restartPolicy: Never` and `backoffLimit: 0`.

## Connectivity

Author connectivity once, using native `Service` and `NetworkPolicy` resources.
The chart passes policy semantics through unchanged and supplies workload
identity labels (`app.kubernetes.io/name` and `kingdom.dmitrich.com/stack`). It
does not generate a second network-group language or Docker network annotations.
Additional resources inherit the Helm release namespace when none is supplied.

For Docker delivery, the renderer uses the admitted stack identity as the native
namespace. The adapter compiles native resources into typed `networking.yaml`,
which is locked and committed beside pinned Compose in the deployment
repository's `docker-release` branch. The host derives private pair bridges and
Service DNS aliases from this admitted intent. Products do not choose Docker
network names or require per-application host network grants.

The initial Docker subset supports one container and replica per workload,
headless Services without port translation, and all-port `matchLabels` peers.
Services explicitly set `publishNotReadyAddresses: true`, matching Docker DNS
aliases which remain resolvable independently of container health. Application
health checks still gate successful delivery; they do not filter Service DNS.
A cross-namespace peer must combine its pod selector with an exact
`kubernetes.io/metadata.name` namespace selector. Effective peer communication
must be symmetric because a Docker bridge permits both directions. Restricted
ports, one-way connectivity, IP blocks and other unimplemented policy forms
are rejected before release. `egress: [{}]` explicitly permits outbound access.
An isolated worker receives no implicit internet or peer-network access.

The chart remains usable for native Kubernetes features outside that Docker
subset; the adapter owns rejection of unsupported targets. Kubernetes delivery
needs a CNI enforcing the policies, RuntimeClasses, storage provisioning and
runtime secret bindings. Existing generic Docker host mappings stay in backend
annotations; `host-gateway` is never a Kubernetes `hostAliases.ip` value. See
[`deployments/render/README.md`](https://github.com/dmitrichcom/deployments/blob/main/render/README.md)
for the exact backend contract and extension boundary.

## Application traces

Set `workloads.<name>.telemetry.traces: true` to use the shared host collector.
The chart injects `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` and
`OTEL_EXPORTER_OTLP_TRACES_PROTOCOL` into regular containers and generates the
existing typed Docker `extra-hosts` mapping. Network policy does not change.
The adapter rejects tracing when native policy provides no outbound capability;
the chart rejects host networking, conflicting transport settings and host
mappings. Products own instrumentation,
service identity and sampling. Remove product-specific export endpoints and
cloud credentials when migrating. See the
[observability integration contract](https://github.com/dmitrichcom/infra-ops/blob/HEAD/docs/observability.md)
for the admitted networks and actual host readiness. Kubernetes deployment of
this endpoint is not implemented by the chart.

## Development and CI

Run `qgate run` with Helm 3.19.0 and PyYAML 6.0.3 available. The gate lints and
renders native workloads, Services, ConfigMaps and NetworkPolicies, and checks
independent image references and invalid inputs. CI runs only `qgate run
--only-fresh`; it does not rerun Helm tests or install their dependencies.
The generated `quality-gates.lock` remains QGate's responsibility.

Because this repository is public, GitHub does not permit it to call the private
`ci-workflows` reusable workflow. `.github/workflows/verify.yml` is a thin local
entry point: it downloads `qgate-v0.16.3` from `coding-harness-utilities`, checks the
reviewed SHA-256, and verifies the existing attestation. Its only secret,
`KINGDOM_HARNESS_READ_TOKEN`, needs contents-read permission on that harness
repository. No application or delivery credentials belong here. Fork pull
requests stop before checkout or credential use; a maintainer must review and
import the change into a branch in this repository before verification.

The 0.3 values API uses native policies in `resources` in place of the 0.2
`networks` fields. Existing consumers remain reproducible through their already
pinned chart commits. New deployment repositories use the workload map and
native connectivity resources. The previous `ops/shadow` compiler
and image-pinning scripts have moved into the separate CD responsibilities in
`deployments/render` and `deployments/runtime`; the chart contains only Helm logic.
