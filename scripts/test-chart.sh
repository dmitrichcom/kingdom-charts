#!/bin/sh
set -eu
helm lint charts/kingdom-workload -f tests/values.yaml
helm template example charts/kingdom-workload --namespace dev -f tests/values.yaml > /tmp/kingdom-chart-render-$$.yaml
trap 'rm -f /tmp/kingdom-chart-render-$$.yaml' EXIT HUP INT TERM
grep -q '^kind: Deployment$' /tmp/kingdom-chart-render-$$.yaml
grep -q '^kind: Service$' /tmp/kingdom-chart-render-$$.yaml
grep -q 'sha256:aaaaaaaa' /tmp/kingdom-chart-render-$$.yaml
helm lint charts/kingdom-workload -f tests/values-version.yaml
helm template versioned charts/kingdom-workload --namespace dev -f tests/values-version.yaml > /tmp/kingdom-versioned-render-$$.yaml
trap 'rm -f /tmp/kingdom-chart-render-$$.yaml /tmp/kingdom-versioned-render-$$.yaml' EXIT HUP INT TERM
grep -q 'image: ghcr.io/dmitrichcom/demo:v1.2.3' /tmp/kingdom-versioned-render-$$.yaml
grep -q 'image: ghcr.io/dmitrichcom/demo-worker:v1.2.3' /tmp/kingdom-versioned-render-$$.yaml
python3 -m unittest discover -s tests -p 'test_*.py'
