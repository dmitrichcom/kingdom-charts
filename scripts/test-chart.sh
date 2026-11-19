#!/bin/sh
set -eu
helm lint charts/kingdom-workload -f tests/values.yaml
helm template example charts/kingdom-workload --namespace dev -f tests/values.yaml > /tmp/kingdom-chart-render-$$.yaml
trap 'rm -f /tmp/kingdom-chart-render-$$.yaml' EXIT HUP INT TERM
grep -q '^kind: Deployment$' /tmp/kingdom-chart-render-$$.yaml
grep -q '^kind: Service$' /tmp/kingdom-chart-render-$$.yaml
grep -q 'sha256:aaaaaaaa' /tmp/kingdom-chart-render-$$.yaml
