# v3 아키텍처

- 문서 상태: 구현 기준
- 방향: 도메인 중심의 점진적 재구축

## 1. 결론

현재 코드를 전부 폐기하지 않습니다. 검증된 KMA 파싱, 공식 특보구역
스냅샷, 공간 도형 처리, Telegram 분할, PDF 폰트, 회귀 테스트는 가져옵니다.

배포 설정은 `app.py` 진입점으로 고정하고, 선택 실행되는 현장 지도·중앙 관제·설정
페이지와 공통 `MonitoringContext`는 `safety_dashboard/` 패키지에서 관리합니다.

시설담당자용 현장 지도를 React 정적 웹으로 분리할 때는 기존 Python 도메인과
어댑터를 HTTP API로 공유한다. 이 Python 데이터 API는 **Google Cloud Run
`asia-northeast3`(서울) 리전**에 배포한다. 기존 Streamlit 중앙 관제도 같은
API를 사용하여 KMA·CCTV·재난문자 조회가 국내 리전에서 실행되게 한다.

React 정적 웹은 **Firebase Hosting**에 배포한다. Firebase Hosting과 Cloud
Run은 같은 Google Cloud 프로젝트에서 관리하고, 브라우저의 `/api/**` 요청은
Hosting rewrite를 통해 서울 리전의 Cloud Run 서비스로 전달한다. 이에 따라
프런트엔드와 API를 하나의 운영 도메인으로 제공하고 CORS·환경별 API 주소 설정을
최소화한다. GitHub 기본 브랜치 반영 시 운영 배포, pull request에는 미리보기
채널을 만드는 자동 배포를 기본으로 한다.

1차 내부 테스트는 Firebase가 제공하는 `https://keco-safety-map.web.app` 기본
주소를 사용한다. 별도 도메인은 테스트 결과와 운영 주체가 확정된 후 연결하며,
React 코드가 특정 호스트명에 의존하지 않게 한다. 카카오 지도 JavaScript 키의
허용 도메인에는 로컬 개발 주소와 실제 Firebase Hosting 주소만 등록한다.

GitHub 기본 브랜치의 변경은 자동 테스트를 먼저 통과해야 한다. 성공한 경우에만
변경된 구성요소를 배포한다. React 변경은 Firebase Hosting, Python API 변경은
Cloud Run 서울 리전으로 각각 배포하고 기존 Streamlit 중앙 관제는 Community
Cloud의 GitHub 연동을 유지한다. 테스트나 빌드가 실패하면 기존 운영 버전을
그대로 유지한다. 장애 시 Firebase 배포 이력과 Cloud Run 리비전으로 직전 정상
버전에 복구할 수 있어야 한다.

```text
시설담당자 스마트폰
    ↓ HTTPS
Firebase Hosting (React + Kakao Maps)
    └── /api/** → Cloud Run asia-northeast3
                      ├── KMA
                      ├── ITS CCTV
                      └── 재난문자
```

### 기본 운영 관측

- Cloud Run 요청·애플리케이션 로그는 Cloud Logging에 남기되 API 키, 전화번호와
  외부 API 원문 전체는 기록하지 않는다.
- Cloud Monitoring으로 서비스 무응답과 지속적인 5xx 증가를 감시하고 운영자
  이메일로 알린다.
- Google Cloud 예산 알림을 설정해 예상하지 못한 호출량과 비용 증가를 조기에
  확인한다.
- 서비스 자체의 생존 상태와 KMA·CCTV·재난문자 같은 외부 제공자의 상태를
  구분한다. 외부 참고정보 하나의 실패는 전체 API 장애로 처리하지 않는다.
- 초기에는 Sentry 같은 별도 관측 서비스를 추가하지 않는다.

## 2. 계층 원칙

```text
UI(Streamlit)
    ↓ ViewModel / Application Service
Domain Rules
    ↑ Ports(interfaces)
Adapters(KMA, CSV, Telegram, PDF)
```

### Domain

- 시설, 특보, 위험도, 데이터 상태 모델
- 공간 매칭 정책
- 위험도 정책
- pandas, Streamlit, requests를 import하지 않음

### Application

- 현재 관제 snapshot 구성
- 시설 그룹·위험도 필터 snapshot 구성
- 체크된 시설의 작업 snapshot 구성
- 점검 요청 대상 선정
- 보고서 입력 모델 구성
- 외부 동작의 순서를 조율

### Ports

- `WarningProvider`
- `WarningZoneRepository`
- `FacilityRepository`
- `Notifier`
- `ReportRenderer`
- `DisasterMessageProvider` (핵심 snapshot과 독립된 현장 참고정보)
- `CctvProvider` (선택 시설 좌표 기준의 인근 도로 CCTV 참고정보)

### Adapters

- KMA HTTP와 응답 파싱
- CSV 또는 DB 시설 저장소
- Telegram API
- PDF 렌더러
- ITS CCTV HTTP·JSON·XML 어댑터
- ITS 조회 결과에 사람이 검증한 `cctv_directions.toml` 고정 방향만
  이름·좌표로 안전하게 결합하는 application catalog
- Streamlit 캐시와 session state

### UI

- ViewModel을 렌더링하고 사용자 의도를 application service에 전달
- 위험도 계산, API 파싱, Telegram 메시지 조립을 하지 않음

## 3. 구현 디렉터리

```text
safety_dashboard/
├── config/
│   ├── cctv_directions.toml
│   ├── risk_policy.toml
│   └── facility_groups.toml
├── domain/
│   ├── models.py
│   ├── enums.py
│   └── risk_policy.py
├── application/
│   ├── ports.py
│   ├── monitoring.py
│   ├── facility_groups.py
│   ├── selection.py
│   ├── risk_configuration.py
│   └── notifications.py
├── adapters/
│   ├── kma.py
│   ├── facility_csv.py
│   ├── region_matcher.py
│   ├── telegram.py
│   └── pdf_report.py
└── ui/
    ├── dialogs.py
    ├── map_view.py
    ├── policy_editor.py
    ├── workflow.py
    └── style.css
```

## 4. 핵심 인터페이스 예시

```python
class WarningProvider(Protocol):
    def fetch_active(self, scope: MonitoringScope) -> WarningFeed: ...

class FacilityRepository(Protocol):
    def list_monitored(self) -> list[Facility]: ...

class Notifier(Protocol):
    def send(self, request: NotificationRequest) -> NotificationResult: ...

class ReportRenderer(Protocol):
    def render(self, report: SituationReport) -> bytes: ...
```

Streamlit 캐시는 adapter를 감싸는 UI/infrastructure decorator로 적용하고 도메인
모델에는 캐시 개념을 넣지 않습니다.

### 시설담당자용 HTTP API

React 현장 지도는 초기 관제 데이터와 선택 시설의 외부 참고정보를 분리해
요청한다. 공개 경로에는 처음부터 `/api/v1` 버전을 포함한다.

```text
GET /api/v1/monitoring
    → KMA 상태, 기준 시각, 시설, 활성 특보, 시설별 위험 판정

GET /api/v1/facilities/{facility_id}/weather
    → 시설 위치 KMA 격자의 초단기실황과 상태

GET /api/v1/facilities/{facility_id}/cctv
    → 20km 이내 도로 CCTV 최대 5개와 상태

GET /api/v1/weather/layers/{temperature|rainfall|wind}
    → 5개 관제 권역의 KMA 격자 실황과 상태
```

`monitoring` 응답만으로 검색·필터·지도·시설 기본 상세를 렌더링할 수 있어야
한다. 기상은 시설 선택 250ms 후 자동으로, CCTV는 사용자 요청 후에만
호출한다. 두 endpoint는 서로 독립이며 하나가 실패해도 나머지 결과와
핵심 관제 응답을 유지한다. React 현장 지도의 이번 범위에서 재난문자는
연동하지 않는다.

#### 갱신 정책

- React 현장 지도는 화면이 활성화된 동안 `monitoring`을 5분마다 갱신한다.
- 사용자가 즉시 확인할 수 있는 수동 새로고침을 함께 제공한다.
- 브라우저 탭이 백그라운드에 있으면 주기 요청을 중지하고 다시 활성화될 때
  즉시 갱신한다.
- 갱신 실패 시 마지막 정상 자료를 유지하면서 기준 시각과 실패 상태를 함께
  표시한다. 오류를 정상 0건으로 바꾸지 않는다.
- 현재 기상은 시설 선택 후 자동 조회하고 격자별 10분 캐시한다.
- 지도 기상 레이어는 첫 화면에서 조회하지 않고, 선택한 종류만 10분
  캐시한다. 지연 시 마지막 정상 격자와 기준 시각을 함께 제공한다.
- CCTV는 사용자가 요청할 때만 조회하고 시설별 1분 캐시한다.
- 오류 결과는 30초 후 재시도할 수 있게 하며 위험도·Telegram·PDF에는 반영하지 않는다.

## 5. 관제 Snapshot

UI는 여러 DataFrame을 직접 조합하지 않고 하나의 결과를 받습니다.

```text
DashboardSnapshot
├── generated_at
├── data_health
├── warnings
├── facilities
├── assessments
├── summary
└── notices
```

지도, 대응 목록, 보고서는 모두 같은 `assessments`를 사용합니다. 화면별로 다시
계산하지 않습니다.

```text
전체 DashboardSnapshot
  → 시설 그룹·위험도 filter_snapshot
  → 체크된 시설 action_snapshot
  → Telegram / PDF
```

지도와 상단 지표는 적용 버튼으로 확정한 filter snapshot을, 두 출력물은
대상 표의 제출 시점에 확정한 동일 action snapshot을 사용합니다.

화면에서 편집한 위험도 행렬은 `risk_configuration` service가 기본
정책을 복제해 세션 정책으로 만듭니다. 파일이나 다른 세션은 변경하지
않으며, 기본 버전과 행렬 해시를 조합한 임시 버전이 snapshot에 남습니다.

## 6. 설정

설정 우선순위는 다음과 같습니다.

1. 환경변수
2. Streamlit secrets adapter
3. 비밀이 아닌 기본 설정 파일

설정 예시:

```text
KMA_API_KEY
TELEGRAM_BOT_TOKEN
TELEGRAM_ADMIN_CHAT_ID
TELEGRAM_USER_CHAT_ID
# TELEGRAM_ADMIN_CHAT_ID 미설정 시 기존 TELEGRAM_CHAT_ID 호환
ALERT_USER_DELIVERY_MODE=telegram
DASHBOARD_BASE_URL
SAFETY_DATA_API_KEY
SAFETY_DATA_API_URL
WARNING_CACHE_SECONDS
RISK_POLICY_PATH
FACILITY_GROUPS_PATH
FACILITY_DATA_PATH
```

API 키는 URL 문자열, 로그, 예외 메시지, 보고서에 포함하지 않습니다.

## 7. 저장소 선택

- 시설 원본은 GitHub 저장소의 CSV로 관리하고 Cloud Run 배포 이미지에 포함한다.
- 시설 변경은 `CSV 수정 → 자동 검증 → GitHub 반영 → 재배포` 순서로 처리한다.
  검증은 시설 ID 중복, 필수값 누락, 좌표 범위, 시설 그룹 매핑과 행 개수를
  확인하며 실패하면 배포하지 않는다. Git 이력을 변경 기록과 복구 수단으로
  사용한다.
- 사용자별 담당 시설 묶음은 저장하지 않는다. 담당자는 현장 지도에서 시설을
  검색하고 그때그때 원하는 시설을 선택한다.
- 점검 상태와 발송 이력은 저장하지 않습니다.
- 내부 검증 단계에서는 별도 로그인을 두지 않고 Firebase Hosting 주소를 내부에
  직접 공유한다. `robots.txt`와 페이지 메타 태그로 검색엔진 색인을 막되, 이는
  접근 통제가 아니며 URL을 아는 사람은 접속할 수 있음을 운영자가 인지한다.
- KMA·CCTV·재난문자 인증키는 React 빌드와 응답에 포함하지 않고 Cloud Run의
  서버 환경에만 둔다.
- 외부 공개나 사용자 범위 확대 전에는 Google 로그인을 이용한 허용 사용자
  방식을 별도 단계로 도입한다.
- 현재 단계에는 데이터베이스와 감사 로그를 도입하지 않습니다.
- Streamlit session state는 화면 선택, 세션 위험도 기준과 일시적인 보고서
  결과에만 사용합니다.

## 8. 재사용할 현재 자산

| 현재 자산 | v3 사용 방식 |
|---|---|
| `parse_warning_response` | KMA parser contract test와 함께 이동 |
| `filter_warning_scope` | `MonitoringScope` 정책으로 이동 |
| 공식 warning zone fetch/fallback | 경계 repository로 이동 |
| `WarningZoneIndex` | Shapely 기반 domain service로 정리 |
| Telegram batch 분할 | notifier adapter로 이동 |
| PDF 한글 폰트 설정 | report renderer로 이동 |
| 시뮬레이션 데이터 | fixture 파일로 이동 |
| 현재 테스트 | unit/contract/integration으로 재분류 |

## 9. 제거할 결합

- provider가 `streamlit`을 직접 import하는 구조
- domain 함수가 pandas `Series/DataFrame`을 직접 받는 구조
- UI가 Telegram 메시지를 조립하는 구조
- UI가 보고서용 날씨를 순회 조회하는 구조
- CSS 문자열 전체를 Python 모듈에 보관하는 구조
- 보고서와 화면이 위험도를 각각 계산하는 구조
- 배포 진입점에 화면·업무 로직을 중복 구현하는 구조

## 10. 테스트 전략

### Unit

- 단계 정규화
- 공간 경계 포함·경계선·인접 구역
- 위험도 등급 경계값
- 알림 대상 선정
- 데이터 상태 전이

### Contract

- 저장된 KMA 원본 응답을 표준 Warning으로 파싱
- 공식 GeoJSON 필드 변화 감지
- Telegram 메시지 길이와 HTML escape

### Integration

- fixture 특보 + fixture 시설 → 예상 영향 시설
- 동일 snapshot → 지도·알림·보고서 동일 등급
- live 실패 → fallback 또는 ERROR 상태

### E2E

- 실시간 기본 화면
- 모의훈련 전환
- 시설 그룹·위험도 필터
- 작업 대상 체크와 출력 범위 일치
- 알림 미리보기
- PDF 생성
- 모바일 핵심 흐름

## 11. 점진적 전환 계획

### 0단계: 결정 확정 — 완료

- 조회·Telegram 발송·PDF 보고서 범위
- 대구·경북·부산·울산·경남 관제
- 수정 가능한 직접 매핑형 위험도 정책

### 1단계: 현재 동작 고정

- 시뮬레이션별 예상 시설과 등급 fixture 작성
- KMA 원본 응답 contract fixture 작성
- 현재 PDF와 Telegram 결과의 필수 필드 테스트

### 2단계: domain v3

- dataclass/enum 모델
- 공간 매칭과 위험도 정책 이전
- pandas 비종속 unit test

### 3단계: adapters

- KMA, 경계, CSV, Telegram, PDF 이전
- UI 없이 integration test

### 4단계: UI v3

- 중복 없는 정보 구조 적용
- 지도·목록·상세 선택 연동
- 모바일 분리 흐름 구현

### 5단계: 동등성·운영 검증

- v2와 v3의 영향 시설 결과 비교
- 훈련 시나리오 사용자 검수
- API 실패·fallback·STALE 훈련

### 6단계: 전환 (완료)

- `app.py`가 v3 화면을 실행하도록 배포 진입점 전환
- 구버전 화면 진입점 제거
- README와 운영 절차 갱신

### 7단계: React 현장 지도 병행 검증

- 시설담당자용 React 현장 지도를 Firebase 기본 주소에 별도로 배포
- 기존 Streamlit 현장 지도를 비상용 비교 화면으로 유지
- 스마트폰에서 시설 검색·선택, KMA 영향 판정, 새로고침과 외부 참고정보 검증
- 검증 기간에는 중앙 관제와 설정 화면의 동작 및 주소를 변경하지 않음

### 8단계: 현장 지도 전환

- 사용자 검증이 끝난 뒤 Streamlit의 현장 지도 진입을 React 주소로 연결
- React 장애 시 기존 Streamlit 현장 지도로 되돌릴 수 있는 운영 절차 유지
- 중앙 관제·설정·Telegram·PDF는 Streamlit에서 계속 운영

## 12. 완료 조건

- UI 파일에 KMA 응답 필드명이나 위험도 상수가 없음
- provider 파일에 Streamlit import가 없음
- 동일 snapshot이 UI·알림·보고서에서 동일한 결과를 사용
- 데이터 오류가 정상 0건으로 표시되지 않음
- P-001~P-003 결정과 정책 버전이 문서와 코드에 기록됨
- 자동 테스트와 모바일 브라우저 검증 통과
