#!/usr/bin/env bash
# Owner-only bootstrap: empty secrets and narrowly scoped IAM. No key payloads.
set -euo pipefail

project_id=keco-safety-map
deployer=serviceAccount:github-deployer@keco-safety-map.iam.gserviceaccount.com
runtime=serviceAccount:safety-dashboard-runtime@keco-safety-map.iam.gserviceaccount.com
expires_at=$(date -u -d '+1 hour' '+%Y-%m-%dT%H:%M:%SZ')
condition="expression=request.time < timestamp('$expires_at'),title=message-key-copy"

for secret_name in OPENAI_API_KEY KAKAO_REST_API_KEY; do
  if ! gcloud secrets describe "$secret_name" --project="$project_id" --format=none --quiet >/dev/null 2>&1; then
    # If describe was denied rather than not-found, create also fails and we stop.
    gcloud secrets create "$secret_name" --project="$project_id" --replication-policy=automatic --format=none --quiet
  fi
  gcloud secrets add-iam-policy-binding "$secret_name" --project="$project_id" \
    --member="$deployer" --role=roles/secretmanager.secretVersionAdder \
    --condition="$condition" --format=none --quiet
  gcloud secrets add-iam-policy-binding "$secret_name" --project="$project_id" \
    --member="$runtime" --role=roles/secretmanager.secretAccessor \
    --condition=None --format=none --quiet
done
printf '등록 준비 완료. GitHub의 버전 추가 권한은 %s 에 만료됩니다.\n' "$expires_at"
printf '키 값 등록·배포·발송은 이 명령에서 실행하지 않았습니다.\n'
