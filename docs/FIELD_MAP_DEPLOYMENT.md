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
- `GET /api/v1/monitoring`: 시설 103개, KMA 상태·특보·위험도·현재 특보 경계
- `GET /api/v1/monitoring?refresh=true`: 수동 강제 갱신
- `GET /api/v1/facilities/{facility_id}/weather`: 시설 KMA 격자의 초단기실황
- `GET /api/v1/facilities/{facility_id}/cctv`: 반경 20km 이내 도로 CCTV 최대 5개

전화번호와 KMA 인증키는 응답에 포함하지 않는다. KMA 조회 실패 시 시설 등급을
`영향 없음`이 아닌 `조회 불가`로 반환한다. 기상과 CCTV는 독립 상태를
반환하므로 한 제공자의 장애가 핵심 관제 지도를 중단하지 않는다. 재난문자는
React 현장 지도의 이번 범위에 포함하지 않는다.

## Google Cloud 최초 준비

한 Google Cloud/Firebase 프로젝트에서 다음을 준비한다.

1. 결제 계정을 연결하고 Cloud Run, Artifact Registry, Secret Manager API를
   활성화한다.
2. 서울 리전에 Docker 저장소 `safety-dashboard`를 만든다.
3. Secret Manager에 `KMA_API_KEY`와 `ITS_CCTV_API_KEY`를 만들고 각 키를 저장한다.
   최초 배포는 비밀 버전 `1`을 명시적으로 사용한다. 키를 교체하면 새 버전을
   추가하고 배포 설정의 버전 번호도 함께 올린다.
4. Cloud Run 실행 전용 서비스 계정 `safety-dashboard-runtime`을 만들고
   두 비밀에만 Secret Accessor 권한을 부여한다.
5. Firebase Hosting을 활성화한다. 1차 주소는
   `https://keco-safety-map.web.app`을 사용한다.
6. 카카오 개발자 콘솔에 실제 `.web.app` 주소를 추가한다.
7. GitHub Actions용 Workload Identity와 서비스 계정을 만들고 Cloud Run,
   Artifact Registry, Firebase Hosting 배포 및 Secret Manager 접근 권한을
   부여한다.

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
```

Repository secrets:

```text
GCP_WORKLOAD_IDENTITY_PROVIDER=<Workload Identity Provider 전체 이름>
GCP_SERVICE_ACCOUNT=<배포 서비스 계정 이메일>
KAKAO_MAP_APP_KEY=<카카오 JavaScript 키>
ITS_CCTV_API_KEY=<ITS CCTV 인증키·최초 Secret Manager 등록용>
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
