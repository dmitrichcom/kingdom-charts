# Kingdom shadow OCI compiler

This is the **build-time** Kubernetes/dekube → Kingdom runtime bundle backend.
It is deliberately independent of the VPS runtime and of the production
GitHub Deployment registration workflow.

1. Helm renders standard Kubernetes manifests in the trusted GitHub runner.
2. Pinned dekube renders a provisional Docker Compose service model.
3. `compile.py` validates the manifest against the Kingdom runtime v1 contract,
   restores Docker-only semantics from the PodSpec/explicit annotations, and
   emits an immutable bundle **with no secret values**.
4. `semantic_diff()` requires exact equality with the previously deployed,
   normalized golden Compose snapshot. Any extra/removed/changed key fails.
5. The workflow archives `deploy/kingdom-runtime.json`,
   `stacks/<id>/compose.yaml`, static ConfigMap files, rendered Kubernetes
   manifests, and `sources.lock.json` and publishes an OCI artifact with the
   *same media type* as the current runtime bundle.

There is no automatic production delivery. No new major release or new VPS
software is required. New manifests and values belong to the environment
repo; the universal chart belongs to `kingdom-charts`.

Secrets: Kubernetes `Secret` objects are explicitly rejected from the source.
Pod volume Secret references are compiled into existing `KINGDOM_STACK_ROOT`
secret-file paths. Current secret delivery remains external and encrypted.
The source repo must NEVER include private key material.

The current Stations Gateway has mutable `/state/stations.json`. Its source
snapshot can be carried in the OCI artifact as a ConfigMap, but **must not be
mounted over the writable state file** until application hot reload and
migrations are implemented. Shadow builds do not alter running state.
