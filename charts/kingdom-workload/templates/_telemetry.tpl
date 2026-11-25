{{/* Native OTLP environment and an existing typed Docker host binding. No
     shared network, credentials, or implicit egress exceptions. */}}
{{- define "kingdom.telemetry.traces" -}}
{{- if .pod.hostNetwork -}}
{{- fail "telemetry.traces does not support hostNetwork" -}}
{{- end -}}
{{- $outbound := eq (len .networks) 0 -}}
{{- range $_, $network := .networks -}}
{{- if not $network.internal -}}{{- $outbound = true -}}{{- end -}}
{{- end -}}
{{- if not $outbound -}}{{- fail "telemetry.traces requires an existing outbound network" -}}{{- end -}}
{{- $key := "kingdom.dmitrich.com/extra-hosts" -}}
{{- $host := "otel.kingdom.internal" -}}
{{- $hosts := list -}}
{{- if hasKey .annotations $key -}}
{{- $existing := mustFromJson (index .annotations $key) -}}
{{- if kindIs "map" $existing -}}
{{- range $name, $address := $existing -}}
{{- if not (kindIs "string" $address) -}}{{- fail "invalid extra-hosts for telemetry" -}}{{- end -}}
{{- $hosts = append $hosts (printf "%s=%s" $name $address) -}}
{{- end -}}
{{- else if kindIs "slice" $existing -}}
{{- $hosts = $existing -}}
{{- else -}}{{- fail "invalid extra-hosts for telemetry" -}}{{- end -}}
{{- end -}}
{{- range $entry := $hosts -}}
{{- if not (kindIs "string" $entry) -}}{{- fail "invalid extra-hosts for telemetry" -}}{{- end -}}
{{- if or (hasPrefix (printf "%s=" $host) (lower $entry)) (hasPrefix (printf "%s:" $host) (lower $entry)) -}}
{{- fail "telemetry owns the otel.kingdom.internal host mapping" -}}
{{- end -}}
{{- end -}}
{{- range $alias := .pod.hostAliases | default list -}}
{{- range $name := $alias.hostnames -}}
{{- if eq (lower $name) $host -}}{{- fail "telemetry owns the otel.kingdom.internal host mapping" -}}{{- end -}}
{{- end -}}
{{- end -}}
{{- $_ := set .annotations $key (toJson (append $hosts (printf "%s=host-gateway" $host))) -}}
{{- $settings := list (dict "name" "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT" "value" (printf "http://%s:4318/v1/traces" $host)) (dict "name" "OTEL_EXPORTER_OTLP_TRACES_PROTOCOL" "value" "http/protobuf") -}}
{{- range $container := .pod.containers -}}
{{- $env := $container.env | default list -}}
{{- range $entry := $env -}}
{{- if has $entry.name (list "OTEL_EXPORTER_OTLP_ENDPOINT" "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT" "OTEL_EXPORTER_OTLP_PROTOCOL" "OTEL_EXPORTER_OTLP_TRACES_PROTOCOL" "OTEL_EXPORTER_OTLP_HEADERS" "OTEL_EXPORTER_OTLP_TRACES_HEADERS") -}}
{{- fail (printf "telemetry.traces owns transport settings; remove %s from container %s" $entry.name $container.name) -}}
{{- end -}}
{{- end -}}
{{- $_ := set $container "env" (concat $env $settings) -}}
{{- end -}}
{{- end -}}
