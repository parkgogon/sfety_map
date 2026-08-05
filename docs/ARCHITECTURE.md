# v3 아키텍처

- 문서 상태: 구현 기준
- 방향: 도메인 중심의 점진적 재구축

## 1. 결론

현재 코드를 전부 폐기하지 않습니다. 검증된 KMA 파싱, 공식 특보구역
스냅샷, 공간 도형 처리, Telegram 분할, PDF 폰트, 회귀 테스트는 가져옵니다.

대신 `app.py`와 `app_v2.py`를 계속 확장하지 않고 새 패키지 안에 v3를 만들고,
동등성 검증 후 기존 진입점을 제거합니다.

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
TELEGRAM_CHAT_ID
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

- 시설은 v3 첫 배포에서 CSV repository를 유지합니다.
- 점검 상태와 발송 이력은 저장하지 않습니다.
- 데이터베이스, 사용자 인증, 감사 로그는 도입하지 않습니다.
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
- `app.py`와 `app_v2.py` 두 진입점을 계속 유지하는 구조

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

### 6단계: 전환

- 실행 진입점을 v3로 변경
- 한 번의 안정화 기간 후 `app.py`, `app_v2.py` 제거
- README와 운영 절차 갱신

## 12. 완료 조건

- UI 파일에 KMA 응답 필드명이나 위험도 상수가 없음
- provider 파일에 Streamlit import가 없음
- 동일 snapshot이 UI·알림·보고서에서 동일한 결과를 사용
- 데이터 오류가 정상 0건으로 표시되지 않음
- P-001~P-003 결정과 정책 버전이 문서와 코드에 기록됨
- 자동 테스트와 모바일 브라우저 검증 통과
