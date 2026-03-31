{{/*
Expand the name of the chart.
*/}}
{{- define "duplicacy.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
We truncate at 63 chars because some Kubernetes name fields are limited to this (by the DNS naming spec).
If release name contains chart name it will be used as a full name.
*/}}
{{- define "duplicacy.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Create chart name and version as used by the chart label.
*/}}
{{- define "duplicacy.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "duplicacy.labels" -}}
helm.sh/chart: {{ include "duplicacy.chart" . }}
{{ include "duplicacy.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels
*/}}
{{- define "duplicacy.selectorLabels" -}}
app.kubernetes.io/name: {{ include "duplicacy.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Cron selector labels
*/}}
{{- define "duplicacy.cron.selectorLabels" -}}
{{ include "duplicacy.selectorLabels" . }}
app.kubernetes.io/component: cron
{{- end }}

{{/*
Exporter selector labels
*/}}
{{- define "duplicacy.exporter.selectorLabels" -}}
{{ include "duplicacy.selectorLabels" . }}
app.kubernetes.io/component: exporter
{{- end }}

{{/*
Create the name of the service account to use
*/}}
{{- define "duplicacy.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "duplicacy.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}
