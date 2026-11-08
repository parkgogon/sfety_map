#!/usr/bin/env bash
# Called by deployment only. No dispatch/test routes and no secret-value reads.
set -euo pipefail

job_exists() {
  local message_job_error
  message_job_error="$(mktemp)"
  if gcloud scheduler jobs describe "$1" --project "$GCP_PROJECT_ID" --location "$GCP_REGION" >/dev/null 2>"$message_job_error"; then
    rm -f "$message_job_error"
    return 0
  fi
  if grep -Eq 'NOT_FOUND|not found' "$message_job_error"; then
    rm -f "$message_job_error"
    return 1
  fi
  rm -f "$message_job_error"
  echo '문자 예약 작업 상태 조회 실패. 배포를 중단합니다.' >&2
  exit 1
}

if [[ "${MESSAGE_COLLECTION_ENABLED:-false}" != "true" ]]; then
  for job in safety-message-collect safety-message-analyze; do
    if job_exists "$job"; then
      gcloud scheduler jobs pause "$job" --project "$GCP_PROJECT_ID" --location "$GCP_REGION" --quiet
    fi
  done
  exit 0
fi

[[ -n "$MESSAGE_REVIEW_SECRET_BINDINGS" ]]
gcloud run deploy safety-message-worker \
  --image "$WORKER_IMAGE" --project "$GCP_PROJECT_ID" --region "$GCP_REGION" \
  --platform managed --no-allow-unauthenticated \
  --service-account "safety-dashboard-runtime@$GCP_PROJECT_ID.iam.gserviceaccount.com" \
  --port 8080 --cpu 1 --memory 512Mi --concurrency 2 --timeout 180 \
  --min-instances 0 --max-instances 1 \
  --set-env-vars "APP_MODULE=safety_dashboard.operations.message_worker:app,GOOGLE_CLOUD_PROJECT=$GCP_PROJECT_ID,TZ=Asia/Seoul,APP_REVISION=$GITHUB_SHA,$MESSAGE_REVIEW_ENV_VARS" \
  --set-secrets "$MESSAGE_REVIEW_SECRET_BINDINGS" --quiet

MESSAGE_WORKER_URL="$(gcloud run services describe safety-message-worker --project "$GCP_PROJECT_ID" --region "$GCP_REGION" --format='value(status.url)')"
MESSAGE_SCHEDULER_ACCOUNT="safety-alert-scheduler@$GCP_PROJECT_ID.iam.gserviceaccount.com"
gcloud run services add-iam-policy-binding safety-message-worker \
  --project "$GCP_PROJECT_ID" --region "$GCP_REGION" \
  --member="serviceAccount:$MESSAGE_SCHEDULER_ACCOUNT" --role=roles/run.invoker --quiet

for kind in collect analyze; do
  job="safety-message-$kind"
  schedule="*/5 * * * *"
  route="collect"
  if [[ "$kind" == "analyze" ]]; then schedule="* * * * *"; route="analyze-next"; fi
  action=create
  if job_exists "$job"; then action=update; fi
  gcloud scheduler jobs "$action" http "$job" \
    --project "$GCP_PROJECT_ID" --location "$GCP_REGION" --schedule="$schedule" --time-zone=Asia/Seoul \
    --uri="$MESSAGE_WORKER_URL/internal/v1/$route" --http-method=POST \
    --oidc-service-account-email="$MESSAGE_SCHEDULER_ACCOUNT" --oidc-token-audience="$MESSAGE_WORKER_URL" \
    --attempt-deadline=180s --max-retry-attempts=0 --quiet
  # Updating a paused job preserves its paused state.
  gcloud scheduler jobs resume "$job" --project "$GCP_PROJECT_ID" --location "$GCP_REGION" --quiet
done
