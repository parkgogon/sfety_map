# React 현장 지도 로컬 실행과 배포

> 상태: 1차 핵심 현장 지도 구현 기준

시설담당자용 React 화면은 Firebase Hosting, Python API는 Cloud Run 서울
`asia-northeast3`에 배포한다. 기존 Streamlit 현장 지도·중앙 관제·설정은
검증 기간 동안 그대로 유지한다.

## 로컬 실행

Python API를 먼저 실행한다.

```bash
.venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn safety_dashboard.api.app:app --host 127.0.0.1 --port 8080
```

다른 터미널에서 React를 실행한다.

```bash
cd field_web
cp .env.example .env.local
# .env.local에 카카오 JavaScript 키 입력
npm install
npm run dev
```

`http://localhost:5173`을 카카오 개발자 콘솔의 Web 플랫폼 허용 주소에
등록한다. `.env.local`과 `.streamlit/secrets.toml`은 Git에 올리지 않는다.
로컬 API는 환경변수 `KMA_API_KEY`를 우선하며, 없으면 Git에서 제외된 기존
Streamlit secrets를 읽는다.

## API 계약

- `GET /api/v1/health`: Cloud Run 프로세스 상태
- `GET /api/v1/health/operations`: 5분 자동 관제 작업자의 최근 실행 상태
- `GET /api/v1/monitoring`: 시설 103개, KMA 상태·특보·위험도·현재 특보 경계
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

## Streamlit 관리자 화면 잠금

기존 Streamlit의 `/control`, `/settings`는 Cloud Run에서 비밀번호를 확인한
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

Streamlit secrets에는 비밀번호를 저장하지 않는다. 기존 관리자 API 주소가
`[alerting].admin_api_url`에 있으면 그대로 사용한다. 별도 값을 쓰려면 다음만
추가한다.

```toml
[admin]
api_url = "https://<safety-dashboard-api Cloud Run 주소>"
```

인증 실패가 5회 누적되면 5분 동안 로그인을 제한한다. `관리자 화면 잠금`을
누르거나 Streamlit 세션이 종료되면 다시 비밀번호를 입력해야 한다. 이 잠금은
React 관리자 화면으로 이전하기 전까지 사용하는 임시 보호수단이며, 수동 전파와
실적 API의 기존 `ALERT_ADMIN_TOKEN` 인증은 계속 유지한다.

현재 배포 파일의 고정값은 다음과 같다.

- Cloud Run 서비스: `safety-dashboard-api`
- Cloud Run 리전: `asia-northeast3`
- Firebase API rewrite: `/api/**`
- 기본 Artifact Registry 저장소: `safety-dashboard`

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

## 배포 전 확인

```bash
.venv/bin/python -m safety_dashboard.api.validate_data
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m unittest discover -s tests_v3 -v
cd field_web && npm test && npm run build
```

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
