# 운영형 구조 개선 로드맵

- 문서 상태: 확정
- 기준일: 2026-08-26
- 목적: 운영 중인 기능을 유지하면서 관제 결과의 신뢰성과 변경 용이성을 높인다.

## 1. 최종 방향

전면 재작성이나 기능별 MSA를 도입하지 않는다. 하나의 코드베이스를 업무 기능별로
나누는 **모듈형 모놀리스**를 사용하고, 실행 단위만 공개 API와 비공개 자동 작업자로
분리한다.

```text
Firebase React 웹
├── /           현장 안전지도
├── /control    중앙 관제
└── /settings   설정
        │
        ▼
Cloud Run 공통 애플리케이션
├── API          사용자·관리자 요청
└── Worker       5분 주기 자동 관제
        │
        ▼
Firestore        관제 상태·알림·실적·감사 이력
```

서버 내부의 목표 모듈은 다음과 같다.

- `monitoring`: 시설, KMA 특보, 공간 매칭, 위험도
- `notifications`: 발효·격상·해제, Telegram, SMS, 재시도
- `reporting`: PDF 보고서
- `operations`: 시스템 상태, 실적, 감사 이력
- `context`: 현재 기상, CCTV 등 독립 참고정보
- `admin`: 관리자 잠금과 수동 작업
- `shared`: 공통 설정, 시계, 오류, 저장 인터페이스

## 2. 변경 원칙

1. 자동알림 기준 상태를 초기화하거나 기존 특보를 재전파하지 않는다.
2. KMA 장애를 특보 해제로 해석하지 않는다.
3. 사용자 지도, 중앙관제, 자동알림과 PDF가 같은 관제 snapshot을 사용한다.
4. 사용자와 관리자는 하나의 사이트를 사용하되 작업 화면은 분리한다.
5. React 관리자 기능이 검증되기 전에는 Streamlit 중앙관제를 제거하지 않는다.
6. 구버전 코드는 현행 테스트로 동작을 이전한 뒤 별도 커밋에서 제거한다.
7. 비밀번호와 API 키는 브라우저 코드에 포함하지 않는다.

## 3. 단계별 계획

### 1단계 — 운영 안정성

- 공개 강제 새로고침에 서버 최소 간격을 적용한다.
- 동시 새로고침 요청은 하나의 KMA 조회 결과를 공유한다.
- KMA 장애 시 마지막 정상 특보·시설 등급·경계를 `STALE` 상태로 유지한다.
- 마지막 정상 조회 시각과 자료 경과시간을 사용자에게 표시한다.
- 현재 Streamlit 관리자 화면에 임시 서버 검증 잠금을 적용한다.
- API 상태와 자동 작업자 지연을 외부에서 감시할 수 있게 한다.

### 2단계 — 공통 관제 snapshot

- [x] 자동 작업자가 5분마다 최신 정상 `MonitoringSnapshot`을 저장한다.
- [x] snapshot ID, 생성 시각, KMA 조회 시각, 정책 버전과 자료 상태를 기록한다.
- [x] React 사용자 API와 API 수동 전파가 최신 snapshot을 우선 읽는다.
- [x] Streamlit 중앙관제와 PDF를 공통 snapshot 읽기로 전환한다.
- [x] 모의훈련과 브라우저 세션 임시정책은 실시간 기준 상태와 분리한다.
- [x] Streamlit의 KMA 직접 조회를 제거한다.

### 3단계 — 서버 모듈화

- [x] 관제 영향·기준화·변화 감지를 순수 `AlertCyclePlanner`로 분리한다.
- [x] Telegram outbox 생성·재시도·결과 보고를
  `TelegramOutboxService`로 분리한다.
- [x] SOLAPI 잔액 점검과 09·18시 운영보고를
  `AlertOperationsService`로 분리한다.
- [x] `AlertDispatcher`에 남은 SMS 연락처 준비·발송·비용 상한·
  Telegram 대체 전파를 `SmsDeliveryService`로 분리한다.
- [x] `FirestoreAlertStore`를 상태, 발송, outbox, 실적과 감사
  저장소로 나눈다.
- [x] 보류 전환과 Telegram outbox의 전체 스캔을 `status == PENDING`
  조건 쿼리로 교체한다. 자동 단일 필드 인덱스를 사용하므로 별도 composite
  index와 배포 권한은 추가하지 않는다.
- [x] 오래된 outbox와 임시 상태에 보존기간(7일)과 `delete_after` Firestore TTL을 적용한다.

### 4단계 — 저장소 정리

- [x] `core/region_resolver.py`를 `safety_dashboard/domain/`으로 이전하고 패키지 내 참조를 전환한다. (`core/region_resolver.py`는 구버전 호환 facade로 유지)
- [x] 운영 시설 CSV(`facilities_info.csv`)와 템플릿의 단일 기준을 확정한다.
- 구버전 `data_providers/`, `services/`, 루트 위험도·보고서·Telegram·UI 코드를
  현행 테스트 이전 후 제거하거나 `legacy/`로 격리한다.
- `tmp/`, 생성 산출물과 최종 보고자료의 보관 위치를 분리한다.
- README, 아키텍처와 사용자 안내를 현재 배포 구조에 맞춘다.

### 5단계 — 사용자 지도 UX

- [x] 시설 검색은 현재 필터와 무관하게 전체 시설에서 수행한다.
- [x] 필터 밖 시설을 고르면 필요한 유형과 등급을 자동으로 표시한다.
- [x] 표시 시설 0개 상태에 `전체 시설 다시 표시` 동작을 제공한다.
- [x] 즉시 반영 필터의 버튼 문구와 실제 동작을 일치시킨다.
- [x] KMA 지연 자료의 기준 시각과 경과시간을 표시한다.
- [x] 바텀시트·모달의 Esc, 포커스 이동·복귀와 모바일 성능을 검증한다.

### 6단계 — React 중앙관제 전환

- [x] 1. `/control`에 운영 상태·KPI·우선순위·실적·이력을 먼저 옮긴다.
- [x] 2. 대상 분석, 관리자 지도, 시설 선택과 특보 원문을 옮긴다.
- [x] 3. 수동 Telegram, 중복·훈련 확인과 PDF 생성을 옮긴다.
- [x] 4. `/settings`에 위험도 정책 편집을 옮긴다.
- [x] 5. 관리자 코드는 필요할 때만 지연 로드해 현장 지도의 초기 성능을 보존한다.

### 7단계 — 관리자 잠금

- [x] 공용 관리자 비밀번호는 Cloud Run에서 검증한다.
- [x] 성공 시 HttpOnly 세션을 발급하고 `/control`, `/settings`와 관리자 API를 허용한다.
- [x] Secret Manager 저장, 반복 실패 제한과 자동 만료를 적용한다.
- [x] 수동 전파의 기존 최종 확인과 감사 기록은 유지한다.

### 8단계 — Streamlit 종료

- [x] React 기능 동등성(현장 지도, 중앙관제, 수동 전파, PDF 생성, 위험도 정책 설정)을 확인했다.
- [x] Streamlit 진입점(`app.py`)을 React 정식 웹 앱 이동 안내 및 상태 페이지로 경량화했다.
- [x] 도메인 모델이 레거시 UI에 의존하지 않도록 `RISK_GRADE_COLORS` 등 공통 상수를 도메인으로 이전했다.
- [x] 아키텍처 다이어그램 및 배포 문서를 React SPA + Cloud Run 모듈형 모놀리스 기준으로 최신화했다.

### 9단계 — 지속적 품질 관리

- [x] Python 단위 테스트 224개 및 데이터 무결성 검증을 표준화했다.
- [x] React Vitest 단위 테스트 및 TypeScript strict 타입 검사를 구축했다.
- [x] `scripts/verify_all.sh` 원클릭 5단계 통합 검증 스크립트를 작성하여 CI와 로컬 검증 체계를 일치시켰다.
- [x] React·Vite·TypeScript와 배포 의존성 버전을 명시적으로 관리하고 프로덕션 번들 빌드를 검증했다.
- [x] GitHub Actions CI/CD 워크플로우(`.github/workflows/ci-deploy.yml`) 검증 및 통과를 확립했다.

### 10단계 — 모바일 UI 밀도 개선

- [x] 1. 현장 지도 범례를 모바일 2줄 구조로 정리하고 미선택 안내판을 압축한다.
- [x] 2. 중앙관제 운영 상황의 KPI를 비조작형 요약 패널로 단순화한다.
- [ ] 3. 대상 분석·전파의 모바일 선택·작업 흐름과 시설 목록을 정리한다.
- [ ] 4. 위험도 정책 설정을 모바일 특보 카드 편집 방식으로 정리한다.
- [ ] 5. 390px·430px·데스크톱 통합 검증과 UX·디자인 문서를 완료한다.

진행률은 `20% → 40% → 65% → 85% → 100%`로 관리하며, 각 항목은 구현·테스트·
독립 커밋과 handoff 갱신을 마친 뒤 완료로 표시한다.

## 4. 이번 작업 순서

**개선 로드맵 1~9단계 완료, 10단계 진행 중**:
- 1단계: API/Worker 듀얼 런타임 확립
- 2단계: KMA 장애 복원력 및 Stale 격리
- 3단계: 5분 자동 감시 체계 및 Telegram 발송
- 4단계: 시설 103개소 단일 기준 및 Region Resolver 도메인 이전
- 5단계: 현장 안전지도 React SPA 스마트폰 UX 개선
- 6단계: React 중앙관제 전환 완료 (`/control`, 관제 지도, 다중 선택, 수동 전파 모달, PDF 다운로드, `/settings` 정책 설정)
- 7단계: 관리자 잠금 고도화 (Cloud Run HMAC-SHA256 HttpOnly 세션 쿠키 발급, 자동 세션 확인, 로그아웃, 보안 감사 로그)
- 8단계: Streamlit 종료 및 레거시 격리 (React 기능 동등성 100% 확보, 도메인 색상 독립화, app.py 안내 모드 전환)
- 9단계: 지속적 품질 관리 (`scripts/verify_all.sh` 5단계 통합 검증, TypeScript 타입 검사, CI/CD 정합성 확인)
- 10단계: 모바일 UI 밀도 개선 (현장 지도 범례 → 운영 상황 → 대상 분석·전파 → 위험도 정책 → 통합 검증)

현재 10단계 2차 작업을 완료했고, 대상 분석·전파 모바일 개선을 다음으로 진행합니다.
상세 운영 상태와 인수인계 내용은 [`HANDOFF.md`](HANDOFF.md)를 따른다.




## 5. 이번 개선에서 제외하는 것

- KMA·Telegram·PDF를 각각 독립 서버로 만드는 MSA
- 사용자와 관리자 기능을 한 화면에 혼합하는 구성
- React 관리자 화면을 한 번에 전부 재작성하는 작업
- 브라우저 번들에 관리자 비밀번호를 넣는 방식
- React 관리자 검증 전 Streamlit 제거
- 자동알림의 현재 `live` 기준 상태 초기화

## 6. 진행 기록

### 2026-08-26

- [x] 공개 강제 새로고침을 서버 기준 60초에 한 번으로 제한
- [x] 같은 프로세스의 동시 요청이 하나의 KMA 조회 결과를 공유
- [x] KMA 일시 실패 시 프로세스에 남아 있는 마지막 정상 관제 결과를 `STALE`로 제공
- [x] 사용자 화면에 `KMA 수신 지연`과 마지막 정상 자료 기준 시각 표시
- [x] 공통 `MonitoringSnapshot` v1 계약과 Firestore 최신 포인터·불변 문서 저장소 추가
- [x] 자동 작업자가 정상 관제 회차를 기존 알림 처리와 병행 저장하도록 연결
- [x] 사용자 API와 API 수동 전파의 Firestore 공통 snapshot 우선 읽기 전환
- [x] 15분 이내 저장본 우선, 정책 불일치·손상·Firestore 장애 시 KMA 직접 조회 fallback
- [x] 오래된 저장본과 KMA 장애가 겹치면 마지막 정상 기준 시각을 유지한 `STALE` 응답 제공
- [x] Streamlit 중앙관제·PDF의 Cloud Run 보호 경로를 통한 공통 snapshot 읽기 전환
- [x] Streamlit의 KMA 특보 직접 조회 제거 및 60초 snapshot 캐시·세션 내 마지막 자료 보존
- [x] 세션 임시 정책은 저장된 특보–시설 연결을 유지하고 등급만 재판정
- [x] KMA STALE·ERROR 상태의 수동 Telegram·PDF 작업 차단
- [x] Streamlit 중앙 관제·설정에 Cloud Run 검증 방식의 8시간 임시 세션 잠금 적용
- [x] `ADMIN_ACCESS_PASSWORD` Secret 생성·권한 부여와 실제 배포 확인
- [x] 외부 감시용 자동 관제 준비 상태 API와 Cloud Monitoring 멱등 배포 설정 추가
- [x] Cloud Monitoring 배포 권한과 업타임 체크·알림 채널·경보 정책 생성 확인
- [ ] 실제 장애 발생 시 이메일 알림 실수신 확인
- [x] 자동 관제 회차 계산을 `AlertCyclePlanner`로 분리하고 직접 단위 테스트 추가
- [x] Telegram outbox와 운영보고·SOLAPI 잔액 점검을 독립 서비스로 분리
- [x] `AlertDispatcher` 외부 생성 규격과 Firestore 상태·자동알림 기준을 유지한 채
  1,413줄에서 972줄로 축소

### 2026-08-27

- [x] 999줄 `FirestoreAlertStore`를 상태·SMS·Telegram outbox·실적/감사
  저장 모듈로 분리
- [x] 기존 `FirestoreAlertStore(...)` facade, collection 이름, 핵심 문서 필드와
  Worker/API 메서드 계약 회귀 테스트 추가
- [x] 보류 전환과 Telegram outbox 조회를 `status == PENDING` 서버 필터로 전환
- [x] 만료·재시도·limit 의미의 동등성 테스트 추가. Firestore 자동 단일 필드
  인덱스로 충분해 별도 composite index와 배포 설정은 추가하지 않음
- [x] `alert_pending` 및 `alert_telegram_outbox`에 terminal 보존기간(7일)과 `delete_after`
  Firestore TTL 필드 적용 및 배포 문서 추가
- [x] `core/region_resolver.py`를 `safety_dashboard/domain/region_resolver.py`로 이전하고
  현행 패키지 의존성을 도메인 계층으로 전환. `core/region_resolver.py`는 구버전 호환 facade로 유지
- [x] 사용자 지도 UX 개선: 필터 무관 전체 시설 검색, 필터 밖 시설 선택 시 자동 완화,
  0개 표시 상태 복구 액션, KMA 지연 경과시간 표시, Esc 키보드 모달/시트 닫기 추가
- [x] React 중앙관제 전환 1차: `/control` 라우팅 체계 및 지연 로딩(Code-Splitting, 18kB),
  운영 상황 요약, 103개 시설 위험등급 KPI 카드, 점검 우선순위 정렬 테이블,
  실적·이력 탭 및 CSV 다운로드 연동 완료
- [x] React 중앙관제 전환 2차: `[대상 분석·전파]` 워크스페이스에 관리자 관제 지도(`KakaoMap`),
  다중 시설 선택(체크박스, 영향 시설 선택, 전체 선택), 수동 Telegram 상황전파 모달(`ManualDispatchModal`),
  백엔드 A4 가로형 PDF 초동보고서 스트리밍 다운로드 API(`GET /internal/v1/monitoring/report.pdf`) 연동 완료
- [x] React 중앙관제 전환 3차: `/settings` 위험도 정책 설정 화면(`SettingsApp`),
  14종 특보 × 3단계 위험등급 매트릭스 편집 그리드, 발효 특보 하이라이트,
  임시 정책 브라우저 로컬 저장 및 백엔드 정책 조회 API(`GET /internal/v1/policy`) 연동 완료 (6단계 전체 완료)
- [x] 7단계 관리자 잠금 고도화: HMAC-SHA256 서명 기반 `AdminSessionManager` 구현,
  Cloud Run 백엔드 HttpOnly 세션 쿠키 발급(`POST /internal/v1/admin/access`), 세션 상태 확인(`GET /internal/v1/admin/session`),
  로그아웃(`POST /internal/v1/admin/logout`), 보호 API 쿠키 인증 검증 및 보안 감사 로그(`LOGGER`) 체계화 완료
- [x] 8단계 Streamlit 종료 및 레거시 격리: React 기능 동등성(현장 지도, 중앙관제, 수동전파, PDF, 정책 설정) 100% 확보 확인,
  도메인 모델 색상 상수(`RISK_GRADE_COLORS`) 독립화, `app.py` 공식 React 웹 앱 안내 모드 전환 및 시스템 아키텍처 최신화 완료
- [x] 9단계 지속적 품질 관리: `scripts/verify_all.sh` 5단계 원클릭 검증 스크립트 구축,
  Python 224개 테스트·데이터 검증·바이트코드 컴파일·React 29개 Vitest·TypeScript strict 타입 검사 및 프로덕션 번들 빌드 통과 확인






