# Repository boundary

This repository owns Helm charts, their defaults/value schemas and chart tests.
Application configuration belongs to its `<product>-deployment` repository.
Image building belongs to `ci-workflows`; rendering adapters, image resolution,
runtime packaging, secret publication and host activation belong to `deployments`.

Chart templates emit native Kubernetes resources. Never embed Compose-only
values such as `host-gateway` or `${ENV}` into typed Kubernetes fields. Typed
backend bindings belong in documented annotations and are interpreted by CD.
Charts must not resolve image tags or enforce one registry/release tag for all
containers. Preserve explicitly selected image references.

Use `qgate run` for local chart tests. The Helm/PyYAML runner reports missing
dependencies as ENVFAIL. Do not edit `quality-gates.lock` manually. CI verifies
the resulting attestations through `ci-workflows` without rerunning test suites.
Test native Kubernetes output and explicit product-independent contracts;
never compare generated output with a historical product Compose file.
