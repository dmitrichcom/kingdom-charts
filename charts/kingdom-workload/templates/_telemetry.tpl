{{/* Native OTLP environment. Infrastructure DNS and transport belong to the
     platform provider; this chart adds no network grants or backend metadata. */}}
{{- define "kingdom.telemetry.traces" -}}
{{- if .pod.hostNetwork -}}
{{- fail "telemetry.traces does not support hostNetwork" -}}
{{- end -}}
{{- $host := "otel.kingdom.internal" -}}
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
