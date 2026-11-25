{{- define "kingdom.stack" -}}
{{- coalesce .workload.stack .root.Values.stack .root.Release.Name -}}
{{- end -}}

{{- define "kingdom.labels" -}}
{{- $labels := deepCopy (.workload.podLabels | default dict) -}}
{{- range $key, $_ := $labels -}}
{{- if or (eq $key "app.kubernetes.io/name") (hasPrefix "kingdom.dmitrich.com/" $key) -}}
{{- fail (printf "pod label %s is chart-owned" $key) -}}
{{- end -}}
{{- end -}}
{{- $_ := set $labels "app.kubernetes.io/name" .name -}}
{{- $_ := set $labels "kingdom.dmitrich.com/stack" (include "kingdom.stack" .) -}}
{{- toYaml $labels -}}
{{- end -}}
