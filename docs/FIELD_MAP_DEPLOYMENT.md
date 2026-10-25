# React 웹 로컬 실행과 배포

> 상태: 현장 지도·중앙관제·설정 운영 기준

현장 지도(`/`)·중앙관제(`/control`)·설정(`/settings`) React SPA는 Firebase
Hosting, Python API는 Cloud Run 서울 `asia-northeast3`에 배포한다. Streamlit 진입점과
구화면은 제거했으며 API·React만 실행한다.

## 로컬 실행

Python API를 먼저 실행한다.

```bash
.venv/bin/pip install -r requirements.txt
cp .env.example .env
# .env에 KMA_API_KEY와 ADMIN_ACCESS_PASSWORD를 입력한다.
.venv/bin/uvicorn safety_dashboard.api.app:app --env-file .env --host 127.0.0.1 --port 8080
```

다른 터미널에서 React를 실행한다.

```bash
cd field_web
cp .env.example .env.local
# .env.local에 카카오 JavaScript 키 입력
npm ci
npm run dev
```

`http://localhost:5173`을 카카오 개발자 콘솔의 Web 플랫폼 허용 주소에
등록한다. `.env`와 `.env.local`은 Git에 올리지 않는다.
API·Worker는 환경변수만 읽으며 기존 Streamlit secrets fallback은 제거했다.

## API 계약

- `GET /api/v1/health`: Cloud Run 프로세스 상태
- `GET /api/v1/health/operations`: 5분 자동 관제 작업자의 최근 실행 상태
- `GET /api/v1/monitoring`: 시설 195개, KMA 상태·특보·위험도·현재 특보 경계
- `GET /api/v1/monitoring?refresh=true`: 수동 강제 갱신
- `GET /api/v1/facilities/{facility_id}/weather`: 시설 KMA 격자의 초단기실황
- `GET /api/v1/facilities/{facility_id}/cctv`: 반경 20km 이내 도로 CCTV 최대 5개
- `GET /api/v1/weather/layers/{temperature|rainfall|wind}`: 관제 5개 권역 KMA 격자 실황

전화번호와 KMA 인증키는 응답에 포함하지 않는다. KMA 조회 실패 시 시설 등급을
`영향 없음`이 아닌 `조회 불가`로 반환한다. 기상과 CCTV는 독립 상태를
반환하므로 한 제공자의 장애가 핵심 관제 지도를 중단하지 않는다. 재난문자는
React 현장 지도의 이번 범위에 포함하지 않는다.
기상 격자 레이어는 기본으로 꺼져 있고 사용자가 선택한 경우에만 조회한다.

## Google Cloud 최초 준비

한 Google Cloud/Firebase 프로젝트에서 다음을 준비한다.

1. 결제 계정을 연결하고 Cloud Run, Artifact Registry, Secret Manager API를
   활성화한다.
2. 서울 리전에 Docker 저장소 `safety-dashboard`를 만든다.
3. Secret Manager에 `KMA_API_KEY`, `ITS_CCTV_API_KEY`와
   `ADMIN_ACCESS_PASSWORD`를 만들고 각 값을 저장한다.
   최초 배포는 비밀 버전 `1`을 명시적으로 사용한다. 키를 교체하면 새 버전을
   추가하고 배포 설정의 버전 번호도 함께 올린다.
4. Cloud Run 실행 전용 서비스 계정 `safety-dashboard-runtime`을 만들고
   해당 비밀에만 Secret Accessor 권한을 부여한다.
5. Firebase Hosting을 활성화한다. 1차 주소는
   `https://keco-safety-map.web.app`을 사용한다.
6. 카카오 개발자 콘솔에 실제 `.web.app` 주소를 추가한다.
7. GitHub Actions용 Workload Identity와 서비스 계정을 만들고 Cloud Run,
   Artifact Registry, Firebase Hosting 배포 및 Secret Manager 접근 권한을
   부여한다.

## React 관리자 화면 잠금

React의 `/control`, `/settings`와 보호 API는 Cloud Run에서 비밀번호를 확인한
브라우저 세션만 8시간 동안 이용할 수 있다. 현장 지도는 잠그지 않는다. 관리자
비밀번호는 기존 `ALERT_ADMIN_TOKEN`과 분리하고 코드나 GitHub 저장소에 넣지 않는다.

Cloud Shell에서 비밀번호를 화면에 노출하지 않고 Secret을 생성한다.

```bash
gcloud config set project keco-safety-map

read -rsp "새 관리자 비밀번호: " ADMIN_PASSWORD_INPUT
echo
printf '%s' "$ADMIN_PASSWORD_INPUT" |
  gcloud secrets create ADMIN_ACCESS_PASSWORD \
    --project=keco-safety-map \
    --replication-policy=automatic \
    --data-file=-
unset ADMIN_PASSWORD_INPUT

gcloud secrets add-iam-policy-binding ADMIN_ACCESS_PASSWORD \
  --project=keco-safety-map \
  --member="serviceAccount:safety-dashboard-runtime@keco-safety-map.iam.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"
```

이미 Secret이 있으면 `secrets create` 대신 새 버전을 추가한다.

```bash
read -rsp "변경할 관리자 비밀번호: " ADMIN_PASSWORD_INPUT
echo
printf '%s' "$ADMIN_PASSWORD_INPUT" |
  gcloud secrets versions add ADMIN_ACCESS_PASSWORD \
    --project=keco-safety-map \
    --data-file=-
unset ADMIN_PASSWORD_INPUT
```

인증 실패가 5회 누적되면 5분 동안 로그인을 제한한다. `관리자 화면 잠금`을
누르거나 8시간 세션이 만료되면 다시 비밀번호를 입력해야 한다. 비밀번호는
브라우저 번들이나 `.env.local`에 넣지 않고 Cloud Run Secret Manager에서만 읽는다.

현재 배포 파일의 고정값은 다음과 같다.

- Cloud Run 서비스: `safety-dashboard-api`
- Cloud Run 리전: `asia-northeast3`
- Firebase API rewrite: `/api/**`
- Firebase 보호 API rewrite: `/internal/**`
- 기본 Artifact Registry 저장소: `safety-dashboard`

## 주변 시설 보고서 지도 캡처 — 운영 적용

2026-10-25 사용자 승인으로 main `616d7a2`를 자동 배포했다. [운영 검수](evidence/2026-10-25/production-deploy/README.md). 수동 워크플로 실행은 하지 않았다.
기존 `POST /api/v1/reports/nearby.pdf`에 실제 지도와 고도화 PDF를 연결했으며 입력은 유지한다.
19:14 KST 사용자가 같은 이미지로 API만 `safety-dashboard-api-kma-refresh-20261025101443`에 재기동하고 100% LATEST로 전환했다.
[후속 운영 복구 검수](evidence/2026-10-25/weather-recovery/README.md)에서 시설/세 실황 LIVE·캐시 만료 후 새 자료 갱신·지도 PDF를 확인했다.
웹 소스는 `616d7a2`로 같고 Worker/Scheduler는 이번 복구에서 변경하지 않았다.

| 설정 | 기본값 / 운영 설정 |
|---|---|
| `NEARBY_MAP_CAPTURE_ENABLED` | 코드 기본 `false`, 운영 API `true` |
| `DASHBOARD_BASE_URL` | 등록된 소유 HTTPS 원점, 기본 `https://keco-safety-map.web.app` |
| `NEARBY_MAP_TIMEOUT_SECONDS` | 20초, 허용 5~30초 |
| `NEARBY_CHROMIUM_EXECUTABLE` | `/usr/bin/chromium` |
| API 자원 | 1 CPU / 1GiB, 기존 concurrency 40·min 0·max 3 유지 |
| Worker 자원 | 기존 1 CPU / 512Mi·concurrency 1·max 1 유지, 브라우저 미포함 |

`Dockerfile.api --target api`는 Chromium·Python Playwright·tini를 포함하고 `--target worker`는
기존 Python 실행 환경만 포함한다. CI에서 서로 다른 API/Worker 이미지로 빌드한다.
인스턴스당 캡처 1·보고서 요청 3·PDF 계산 1건을 제한한다. 서비스 전체 캡처 1건 제한은 아니다.
전용 `report-map.html`은 같은 웹 빌드에서 생성하며 기존 `VITE_KAKAO_MAP_APP_KEY`만 사용한다.
서버용 카카오 비밀키를 추가하지 않는다. 새 페이지도 no-store, 해시 assets는 immutable이다.

배포·재검수 수용 조건:

- 등록된 원점의 `report-map.html`과 연결된 assets가 200이며 지도 페이지 계약 버전이 1인지 확인한다.
- 해당 정적 페이지와 API를 같은 변경으로 반영한다. API가 먼저 반영돼 페이지가 없으면 목록/집계 PDF로 전환한다.
- Cloud Run에서 실제 SDK/타일·CA 신뢰·시작 시간·메모리·기존 조회 API 지연을 확인한다.
- 현장/관제에서 지도 포함 PDF와 실패 안내 PDF, 닫기 취소·중복 방지를 배포 후 확인한다.
- 지도 장애 복구는 API의 `NEARBY_MAP_CAPTURE_ENABLED=false`로 캡처를 끈다. 목록/집계 PDF는 유지된다.

서버는 지정 원점의 지도 HTML/assets 및 `dapi.kakao.com`, `t1.kakaocdn.net`, `mts.kakaocdn.net` GET만
허용하며 보고서 생성으로 업무 API·KMA·Worker·발송 경로를 호출하지 않는다. 기준점·캡처·PDF를 영구 저장하지 않는다.
로컬 1 CPU/1GiB 검수 결과는 [통합 증빙](evidence/2026-10-25/nearby-integration/README.md)에 있으며
Cloud Run 배포 후 검증을 대신하지 않는다.

## Firebase Hosting 캐시

Firebase의 사용자 지정 헤더는 rewrite 후 파일이 아니라 최초 요청 URL에 맞춰
적용됩니다. 따라서 `firebase.json`은 `/index.html`뿐 아니라 SPA 진입 경로인 `/`,
`/control{,/**}`, `/settings{,/**}`에도 `no-cache, no-store`를 지정합니다. 해시가
붙는 `/assets/**` 파일만 1년 `immutable`로 캐시합니다. 자세한 매칭 순서는
[Firebase Hosting 구성 문서](https://firebase.google.com/docs/hosting/full-config)를
따릅니다.

배포 후 세 진입 경로의 `Cache-Control`이 실제로 무캐시인지 확인합니다. 운영 응답이
여전히 기본 `max-age=3600`이면 요청 경로 헤더 규칙이 배포되지 않은 것입니다.

## GitHub 설정

Repository variables:

```text
GCP_PROJECT_ID=keco-safety-map
GCP_ARTIFACT_REPOSITORY=safety-dashboard
UPTIME_MONITORING_ENABLED=true
UPTIME_ALERT_EMAIL=<외부 장애 알림을 받을 관리자 이메일>
```

## 외부 가동상태 감시

`UPTIME_MONITORING_ENABLED=true`이면 배포 완료 후 GitHub Actions가
Cloud Monitoring에 다음 두 개의 공개 업타임 체크를 생성하거나 갱신한다.

- 사용자 시설지도 HTML 응답
- 자동 관제 작업자의 최근 10분 이내 실행 여부

점검은 5분 주기로 아시아·미국 3개 지역에서 실행한다. 10분간
복수 지역의 실패가 지속될 때만 인시던트를 열어 일시적인 통신 지연으로
인한 오경보를 줄인다. `UPTIME_ALERT_EMAIL`이 설정되면 장애·복구를 해당
주소로 통지한다.

KMA 수신 장애는 자동 관제 작업자가 기존 관리자 Telegram으로 별도
통지한다. KMA가 잠시 응답하지 않더라도 작업자가 계속 실행 중이면
`/api/v1/health/operations`는 가동 중으로 판정한다. 이로써 우리 시스템
장애와 외부 KMA 자료 지연을 구분한다.

배포 계정에는 다음 권한이 필요하다.

```text
roles/monitoring.uptimeCheckConfigEditor
roles/monitoring.alertPolicyEditor
roles/monitoring.notificationChannelEditor
```

업타임 체크는 JavaScript나 지도 타일을 실행하지 않고 HTTP 응답과
필수 문구만 검증한다. 상세 구성은
[`scripts/configure_uptime_monitoring.sh`](../scripts/configure_uptime_monitoring.sh)에서
멱등적으로 관리한다.

자동 시설담당자 알림은 기본 배포에서 꺼져 있다. 관리자방·시설담당자
Telegram 그룹 준비 후 `ALERT_AUTOMATION_ENABLED=true`를 설정해야 비공개 작업자와
5분 Scheduler가 배포된다. 전체 절차는
[`AUTOMATIC_ALERTS.md`](AUTOMATIC_ALERTS.md)를 따른다.

Repository secrets:

```text
GCP_WORKLOAD_IDENTITY_PROVIDER=<Workload Identity Provider 전체 이름>
GCP_SERVICE_ACCOUNT=<배포 서비스 계정 이메일>
KAKAO_MAP_APP_KEY=<카카오 JavaScript 키>
```

`GCP_PROJECT_ID` 변수가 없으면 자동 테스트만 실행하고 배포 작업은 안전하게
건너뛴다. 설정 후 `main` 브랜치의 테스트가 통과하면 API를 먼저 배포하고 React
화면을 이어서 배포한다. pull request는 테스트만 수행한다.

## Firestore TTL(보존기간 만료 자동정리) 설정

완료·만료된 임시 보류 전이(`alert_pending`) 및 Telegram 발송 큐(`alert_telegram_outbox`)
문서는 terminal 상태(`SENT`, `EXPIRED`, `RESOLVED`)로 변경될 때 7일 뒤 시각이
`delete_after` 필드로 기록된다. 미처리 `PENDING` 문서에는 이 필드가 없으므로
살아 있는 작업은 안전하게 보존된다.

Firestore에서 이 필드를 기준으로 자동 삭제하도록 TTL 정책을 활성화한다.

```bash
# 1. alert_pending 컬렉션 TTL 활성화
gcloud firestore fields ttls update delete_after \
  --collection-group=alert_pending \
  --project=keco-safety-map \
  --enable-ttl

# 2. alert_telegram_outbox 컬렉션 TTL 활성화
gcloud firestore fields ttls update delete_after \
  --collection-group=alert_telegram_outbox \
  --project=keco-safety-map \
  --enable-ttl
```

현재 상태 확인:

```bash
gcloud firestore fields ttls list --project=keco-safety-map
```


## 배포 전 확인

```bash
bash scripts/verify_all.sh
```

또는 개별 검증:

```bash
.venv/bin/python -m safety_dashboard.api.validate_data
.venv/bin/python scripts/run_python_tests.py
cd field_web && npm test && npm run build
```

Firebase Hosting 배포 빌드 시에는 CI 환경변수 `VITE_APP_VERSION="${GITHUB_SHA:-}"`와
`VITE_BUILD_TIME="$(date -u +'%Y-%m-%dT%H:%M:%SZ')"`가 주입되어 중앙관제 화면
헤더에 배포 커밋(7자리)과 배포 시각이 표시됩니다. 로컬 실행에서는 `개발 빌드`로
안전하게 fallback합니다.

시설 CSV 검증은 시설 ID 중복, 필수값 누락, 좌표 범위와 시설 그룹별 개수를
확인한다. 배포 후에는 390px 스마트폰에서 검색·필터·동일 좌표 시설 선택과
`?facility_id=...` 딥링크를 확인한다.
추가로 Cloud Run 서울 리전에서 실제 기상과 CCTV endpoint를 호출해
국내 출구 IP의 ITS 응답과 HTTPS MP4 재생 가능 여부도 확인한다.

2026-08-12 시범 배포에서는 서울 Cloud Run에서도 ITS API가 7초 내에
응답하지 않아 CCTV를 보류했다. 운영 워크플로에는
`CCTV_ENABLED=false`, `VITE_CCTV_ENABLED=false`를 설정해 외부 호출과 화면 버튼을
모두 비활성화한다. 향후 고정 국내 출구 IP 또는 중계가 준비되면
두 플래그를 `true`로 바꾸고 실사용 검증한다.
