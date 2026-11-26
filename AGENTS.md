# Repository boundary

This repository owns Helm charts, their defaults/value schemas and chart tests.
Application configuration belongs to its `<product>-deployment` repository.
Image building belongs to `ci-workflows`; rendering adapters, image resolution,
runtime packaging, secret publication and host activation belong to `deployments`.

Chart templates emit native Kubernetes resources. Never embed Compose-only
values such as `host-gateway` or `${ENV}` into typed Kubernetes fields. Docker provider defaults and infrastructure bindings belong to CD and infra-ops;
never generate backend annotations in Kubernetes resources.
Charts must not resolve image tags or enforce one registry/release tag for all
containers. Preserve explicitly selected image references.

Use `qgate run` for local chart tests. The Helm/PyYAML runner reports missing
dependencies as ENVFAIL. Do not edit `quality-gates.lock` manually. CI verifies
the resulting attestations with `qgate run --only-fresh` without rerunning tests.
This repository is public, so its thin verification workflow cannot call the
private `ci-workflows` reusable workflow. It downloads the SHA-256-pinned verifier
from `coding-harness-utilities` using `KINGDOM_HARNESS_READ_TOKEN`, scoped to read
that repository. Fork changes require maintainer review and a repository branch;
the workflow stops before checkout or credential use for a fork pull request.
Test native Kubernetes output and explicit product-independent contracts;
never compare generated output with a historical product Compose file.

## Platform overview

Maintain the [Kingdom overview](https://github.com/dmitrichcom/kingdom-overview) when platform capabilities, ownership boundaries, or guarantees change.

Follow its [documentation maintenance rules](https://github.com/dmitrichcom/kingdom-overview/blob/HEAD/AGENTS.md). Include required overview updates in the same change scope.
