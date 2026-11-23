{{- define "kingdom.stack" -}}
{{- coalesce .workload.stack .root.Values.stack .root.Release.Name -}}
{{- end -}}

{{- define "kingdom.networks" -}}
{{- $networks := dict -}}
{{- $names := .workload.networks | default list -}}
{{- if and (gt (len .root.Values.networks) 0) (eq (len $names) 0) -}}
{{- fail (printf "workload %s must declare network membership" .name) -}}
{{- end -}}
{{- range $network := $names -}}
{{- if not (hasKey $.root.Values.networks $network) -}}
{{- fail (printf "workload %s refers to undeclared network %s" $.name $network) -}}
{{- end -}}
{{- $_ := set $networks $network (index $.root.Values.networks $network) -}}
{{- end -}}
{{- toJson $networks -}}
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
{{- range $network, $_ := (include "kingdom.networks" . | fromJson) -}}
{{- $_ := set $labels (printf "kingdom.dmitrich.com/network-%s" $network) "true" -}}
{{- end -}}
{{- toYaml $labels -}}
{{- end -}}

{{- define "kingdom.policyName" -}}
{{- if gt (len .) 50 -}}
{{- printf "%s-%s-connectivity" (trunc 41 . | trimSuffix "-") (sha256sum . | trunc 8) -}}
{{- else -}}
{{- printf "%s-connectivity" . -}}
{{- end -}}
{{- end -}}
