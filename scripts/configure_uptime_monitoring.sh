#!/usr/bin/env bash
set -euo pipefail

PROJECT_ID="${GCP_PROJECT_ID:?GCP_PROJECT_ID is required}"
DASHBOARD_URL="${DASHBOARD_BASE_URL:-https://keco-safety-map.web.app}"
ALERT_EMAIL="${UPTIME_ALERT_EMAIL:-}"

if [[ "$DASHBOARD_URL" != https://* ]]; then
  echo "DASHBOARD_BASE_URL must be an HTTPS URL" >&2
  exit 2
fi

DASHBOARD_HOST="${DASHBOARD_URL#https://}"
DASHBOARD_HOST="${DASHBOARD_HOST%%/*}"
if [[ -z "$DASHBOARD_HOST" || "$DASHBOARD_HOST" == *:* ]]; then
  echo "DASHBOARD_BASE_URL must use the default HTTPS port" >&2
  exit 2
fi

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

ensure_uptime_check() {
  local display_name="$1"
  local path="$2"
  local matcher="$3"
  local check_name check_id configs current_host created

  if ! configs="$(
      gcloud monitoring uptime list-configs \
      --project "$PROJECT_ID" \
      --format=json
    )"; then
    echo "Unable to list uptime checks; verify Monitoring IAM roles" >&2
    return 5
  fi
  check_name="$(
    printf '%s' "$configs" |
      jq -r --arg name "$display_name" \
        '.[] | select(.displayName == $name) | .name' |
      head -1
  )"

  if [[ -z "$check_name" ]]; then
    if ! created="$(
        gcloud monitoring uptime create "$display_name" \
        --project "$PROJECT_ID" \
        --resource-type=uptime-url \
        --resource-labels="host=$DASHBOARD_HOST,project_id=$PROJECT_ID" \
        --protocol=https \
        --path="$path" \
        --request-method=get \
        --validate-ssl=true \
        --status-codes=200 \
        --matcher-type=contains-string \
        --matcher-content="$matcher" \
        --period=5 \
        --timeout=10 \
        --regions=asia-pacific,usa-iowa,usa-oregon \
        --user-labels="managed_by=github_actions,component=keco_safety" \
        --format='value(name)'
      )"; then
      echo "Unable to create uptime check: $display_name" >&2
      return 6
    fi
    check_name="$created"
    echo "Created uptime check: $display_name" >&2
  else
    current_host="$(
      gcloud monitoring uptime describe "$check_name" \
        --project "$PROJECT_ID" \
        --format='value(monitoredResource.labels.host)'
    )"
    if [[ "$current_host" != "$DASHBOARD_HOST" ]]; then
      echo "Existing uptime check host mismatch: $display_name" >&2
      exit 3
    fi
    gcloud monitoring uptime update "$check_name" \
      --project "$PROJECT_ID" \
      --path="$path" \
      --request-method=get \
      --validate-ssl=true \
      --set-status-codes=200 \
      --matcher-type=contains-string \
      --matcher-content="$matcher" \
      --period=5 \
      --timeout=10 \
      --set-regions=asia-pacific,usa-iowa,usa-oregon \
      --update-user-labels="managed_by=github_actions,component=keco_safety" \
      --quiet >/dev/null
    echo "Updated uptime check: $display_name" >&2
  fi

  check_id="${check_name##*/}"
  if [[ -z "$check_id" ]]; then
    echo "Unable to resolve uptime check ID: $display_name" >&2
    exit 4
  fi
  printf '%s' "$check_id"
}

ensure_email_channel() {
  local channel_name channels created
  if [[ -z "$ALERT_EMAIL" ]]; then
    return 0
  fi
  if ! channels="$(
      gcloud beta monitoring channels list \
      --project "$PROJECT_ID" \
      --format=json
    )"; then
    echo "Unable to list Monitoring notification channels" >&2
    return 7
  fi
  channel_name="$(
    printf '%s' "$channels" |
      jq -r --arg email "$ALERT_EMAIL" \
        '.[] | select(.type == "email" and .labels.email_address == $email) | .name' |
      head -1
  )"
  if [[ -z "$channel_name" ]]; then
    if ! created="$(
        gcloud beta monitoring channels create \
        --project "$PROJECT_ID" \
        --display-name="K-ECO safety uptime administrator" \
        --description="External availability alerts for the K-ECO safety dashboard" \
        --type=email \
        --channel-labels="email_address=$ALERT_EMAIL" \
        --user-labels="managed_by=github_actions,component=keco_safety" \
        --format='value(name)'
      )"; then
      echo "Unable to create uptime notification channel" >&2
      return 8
    fi
    channel_name="$created"
    echo "Created uptime notification channel" >&2
  else
    gcloud beta monitoring channels update "$channel_name" \
      --project "$PROJECT_ID" \
      --enabled \
      --quiet >/dev/null
  fi
  printf '%s' "$channel_name"
}

ensure_alert_policy() {
  local display_name="$1"
  local check_id="$2"
  local notification_channel="$3"
  local policy_name policy_file policies

  policy_file="$TMP_DIR/$(printf '%s' "$check_id" | tr -cd '[:alnum:]_-').json"
  jq -n \
    --arg display_name "$display_name" \
    --arg check_id "$check_id" \
    --arg channel "$notification_channel" \
    --arg dashboard "$DASHBOARD_URL" \
    '{
      displayName: $display_name,
      combiner: "OR",
      enabled: true,
      userLabels: {
        managed_by: "github_actions",
        component: "keco_safety"
      },
      documentation: {
        mimeType: "text/markdown",
        content: ("K-ECO 재난안전 관제 외부 가동상태 점검이 10분 이상 실패했습니다. 사용자 지도와 Cloud Run·Scheduler 상태를 확인하세요.\n\n" + $dashboard)
      },
      notificationChannels: (if $channel == "" then [] else [$channel] end),
      conditions: [
        {
          displayName: ("Uptime check failure: " + $check_id),
          conditionThreshold: {
            aggregations: [
              {
                alignmentPeriod: "1200s",
                perSeriesAligner: "ALIGN_NEXT_OLDER",
                crossSeriesReducer: "REDUCE_COUNT_FALSE",
                groupByFields: ["resource.label.*"]
              }
            ],
            comparison: "COMPARISON_GT",
            duration: "600s",
            filter: ("metric.type=\"monitoring.googleapis.com/uptime_check/check_passed\" AND metric.label.check_id=\"" + $check_id + "\" AND resource.type=\"uptime_url\""),
            thresholdValue: 1,
            trigger: {count: 1}
          }
        }
      ]
    }' > "$policy_file"

  if ! policies="$(
      gcloud monitoring policies list \
      --project "$PROJECT_ID" \
      --format=json
    )"; then
    echo "Unable to list Monitoring alert policies" >&2
    return 9
  fi
  policy_name="$(
    printf '%s' "$policies" |
      jq -r --arg name "$display_name" \
        '.[] | select(.displayName == $name) | .name' |
      head -1
  )"
  if [[ -z "$policy_name" ]]; then
    gcloud monitoring policies create \
      --project "$PROJECT_ID" \
      --policy-from-file="$policy_file" \
      --quiet
    echo "Created alert policy: $display_name"
  else
    gcloud monitoring policies update "$policy_name" \
      --project "$PROJECT_ID" \
      --policy-from-file="$policy_file" \
      --quiet
    echo "Updated alert policy: $display_name"
  fi
}

WEB_CHECK_ID="$(
  ensure_uptime_check \
    "K-ECO field map availability" \
    "/" \
    "<title>K-ECO 현장 안전지도</title>"
)"
OPERATIONS_CHECK_ID="$(
  ensure_uptime_check \
    "K-ECO automatic monitoring freshness" \
    "/api/v1/health/operations" \
    '"status":"ok"'
)"
NOTIFICATION_CHANNEL="$(ensure_email_channel)"

ensure_alert_policy \
  "K-ECO field map unavailable" \
  "$WEB_CHECK_ID" \
  "$NOTIFICATION_CHANNEL"
ensure_alert_policy \
  "K-ECO automatic monitoring delayed" \
  "$OPERATIONS_CHECK_ID" \
  "$NOTIFICATION_CHANNEL"

if [[ -z "$NOTIFICATION_CHANNEL" ]]; then
  echo "WARNING: uptime checks are active but no email notification channel is set" >&2
fi
