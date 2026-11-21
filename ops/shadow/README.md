# Build-time Kubernetes → Compose contract

The common GitHub Actions workflow renders application Helm values into Kubernetes manifests, pins every declared image to an immutable GHCR digest, then runs the **SHA-256-pinned dekube converter**. `compile.py` validates the Kubernetes and provisional Compose models, restores explicitly supported Docker-only semantics and rejects unsupported/ambiguous resources. Optional `expected-compose.json` supplies an additional exact golden comparison; it is not required for new applications.

The resulting runtime OCI contains the source and pinned Kubernetes manifests, compiled `stacks/<id>/compose.yaml`, declared read-only ConfigMap files, `deploy/kingdom-runtime.json` and `sources.lock.json`. No plaintext secrets or Docker build contexts are included. Kubernetes Secret *references* become read-only Compose mounts; actual values arrive through a **separate encrypted secrets OCI**, independently attested by the central deployment worker.

Compilation never activates production. The VPS consumes verified, digest-pinned Compose and secrets only. The public compiler knows no product identity beyond the validated, caller-provided runtime descriptor. The only application contract and host prerequisites are documented at [`kingdom-environments/AGENTS.md`](https://github.com/dmitrichcom/kingdom-environments/blob/main/AGENTS.md).
