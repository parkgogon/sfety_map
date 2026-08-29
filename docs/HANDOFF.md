# 프로젝트 현재 상태와 인수인계

> 살아 있는 현재 상태 문서입니다. 작업일지가 아닙니다.
>
> 마지막 정리: 2026-08-29 12:34 KST
> 기준 배포 Git: `main` (`3e1f65f`) / STALE·ERROR 출력 차단 운영 배포 및 검증 완료

새 작업자는 먼저 루트의 [`AGENTS.md`](../AGENTS.md)를 읽고, 이 문서를 실제
Git·코드·테스트와 대조해야 합니다. 아래 운영 상태는 시간이 지나면 달라질 수
있으므로 날짜가 붙은 값은 반드시 다시 확인합니다.

## 0. 현재 진행 중인 개선

K-ECO 기상재난 시설 영향 보고서 PDF의 5단계 고도화(PART 1 ~ PART 5)는 운영에
배포됐고, 공개 운영 엔드포인트에서 실시간·모의훈련 PDF를 직접 내려받아 전체
페이지를 렌더링 검수했습니다.

- 완료 (PART 1: Compact/Standard Mode): 소량 데이터(영향시설 <= 10개 & 활성특보 잔여공간 수용 가능) 시 활성특보까지 1페이지 하단에 수용하여 1페이지 완결
- 완료 (PART 2: 지도 Callout & Leader Line): TOP 1~4 마커 원형 번호 뱃지 + 좌우 레일 배치 + 엘보 지시선 자동 배치로 충돌 방지 및 위치 시인성 극대화
- 완료 (PART 3: 안전관리요령 Master & Panel): 13종 공식 특보 100% 매핑 `SafetyGuidelineMaster`, 핵심 Action Items 불릿 표출, 중점관리시설 카운트 뱃지(`0개소`/`N개소`/`상위 4개소`) 및 특보단계(`호우 · 경보`) 명시
- 완료 (PART 4: Header Metadata & Department Display): Header에 `발행: YYYY-MM-DD HH:MM | 데이터 기준: YYYY-MM-DD HH:MM` 분리 표출, 1페이지 테이블 담당부서 Display Name(마지막 단위 부서명) 축약 처리, 지도 범례 3행 구조 흑백/컬러 가독성 최적화
- 완료 (PART 5: Scenario A ~ O 통합검증 & 운영 배포): 15개 재난 시나리오 전수 검증 및 CI/CD(Cloud Run API, Firebase Hosting) 배포 완료
- 완료 (운영 실물 검수): 2026-08-29 10:36 KST 실시간 평시 PDF는 A4 1페이지,
  모의훈련 PDF는 A4 2페이지로 생성됐고 지도 callout·TOP 4·안전요령·표·페이지
  번호에 겹침, 잘림, 깨진 한글, 전화번호 노출이 없음을 확인
- 완료 (운영 배포): 공개 PDF와 수동 상황전파가 `STALE`·`ERROR`
  snapshot에서도 실행될 수 있던 누락을 PDF 렌더러·API·관리자
  서비스·React UI에서 차단하고 `3e1f65f`로 배포
- 완료: 전체 Python 단위 테스트 246개, React 35개 및 5단계 무결성 검증
  (`verify_all.sh`) 통과
- 정리: 낡은 직원용 안내서·AI 원문 규칙은 현행 문서 목록에서 제거하고,
  생성 PDF·렌더·임시 산출물은 `.trash/obsolete_artifacts_20260829/`로 이동

**다음 작업 하나**: [`SIMULATION_IMPROVEMENT_PLAN.md`](SIMULATION_IMPROVEMENT_PLAN.md)를
코드·테스트와 다시 대조한 뒤, 현장지도·중앙관제의 모의훈련 모드를
통합하고 특보에 연관된 훈련 기상 그래픽을 구현한다. 수용 조건은
모드 이동·PDF·수동 훈련 일치, 훈련·실황 표식 분리, 자동알림 baseline
불변, `scripts/verify_all.sh` 통과다.


## 1. 프로젝트 한 문장

대구·경북·부산·울산·경남의 소관시설 103개소와 KMA 공식 기상특보를 자동으로
대조해 시설담당자에게 영향 변화를 알리고, 스마트폰 지도 확인과 중앙관제·PDF
보고를 지원하는 내부 시범 운영 시스템입니다.

궁극적인 목표는 단순한 지도나 알림 봇이 아니라 다음 흐름을 하나의 설명 가능한
업무 기준으로 연결하는 것입니다.

```text
KMA 특보 → 시설 위치 대조 → 위험도·우선순위 → 담당자 알림·현장 확인
                                      └→ 중앙관제 분석·PDF 초동보고
```

## 2. 현재 실제 구성

### 시설담당자 화면

- 운영 주소: `https://keco-safety-map.web.app`
- Firebase Hosting의 React·Kakao Maps 화면이며 주 사용 환경은 스마트폰입니다.
- 시설 103개 전체, 시설명·주소 검색, 6개 시설 유형 필터, 위험등급 레이어,
  특보 경계와 시설 상세를 제공합니다.
- 단일 마커 선택은 현재 배율을 유지하고, 숫자 클러스터만 확대합니다.
- 선택 시설의 KMA 격자 현재 기상을 자동 조회합니다.
- 강수·바람·기온 실황 그래픽은 요청 시 한 종류만 표시합니다.
- 모의훈련은 특보·위험등급만 훈련 자료이며 현재 기상은 실제 참고자료로 구분합니다.
- KMA 공식 특보 현황 링크를 제공합니다.

### 중앙관제·설정

- Firebase React 앱의 `/control`, `/settings` 화면이며 `app.py`는 React 정식 웹으로
  이동시키는 경량 안내 진입점입니다.
- 공용 관리자 비밀번호를 Cloud Run에서 검증하고 성공 세션을 8시간 유지합니다.
- 중앙관제는 `운영 상황 / 대상 분석·전파 / 실적·이력`으로 나뉩니다.
- 조회 필터, 우선순위, 지도, 대상 체크, 시설담당자 그룹 수동 전파, PDF 생성,
  자동·수동 실적과 이력을 제공합니다.
- 설정 화면의 위험도 편집은 브라우저 세션에만 적용되며 TOML을 수정하지 않습니다.

### 서버와 자동알림

- 공개 API: Cloud Run `safety-dashboard-api`, 서울 `asia-northeast3`
- 비공개 작업자: Cloud Run `safety-alert-worker`, 최대 인스턴스 1
- Scheduler: `safety-alert-dispatch`, 5분마다 OIDC로 작업자 호출
- Firestore: 자동알림 기준 상태, 공통 `MonitoringSnapshot`, outbox, 실적과 감사
  이력을 저장합니다.
- GitHub `main` push는 테스트 성공 후 API·Worker·Firebase를 자동 배포합니다.
- 외부 uptime check는 사용자 웹과 최근 Worker 실행을 감시합니다.

## 3. 운영 설정 — 2026-08-29 확인

- 자동관제 모드: `live`
- 시설담당자 전달 방식: `telegram`
- 시설담당자 수신처: 대화 가능한 비공개 그룹
- 관리자 수신처: 별도 관리자 Telegram 대화방
- 자동알림 기본 제외 특보: `열대야`
- SMS/SOLAPI: 구현·실전 송수신·웹훅 검증은 완료했지만 현재 주 전달 경로가 아님
- CCTV: 코드와 테스트는 있으나 운영 플래그가 꺼져 있음

자동 사용자 알림은 모든 활성 특보를 반복 게시하지 않습니다. 시설 영향 상태가
`발효`, `격상`, `해제`로 바뀐 경우만 보냅니다. 전달 경로나 필터를 바꿀 때 기존
활성 특보를 다시 보내지 않도록 기준 상태를 보존합니다.

### 최근 운영 이슈와 복구 확인

2026-08-27 09:35 KST 확인 당시:

- Worker 자체는 5분마다 정상 실행 중이었습니다.
- KMA 마지막 정상 조회는 2026-08-27 05:00 KST였습니다.
- 이후 KMA 연결이 55회 연속 실패했고 진단은 `KMA API 통신경로`였습니다.
- 일반 외부통신은 정상이어서 현재 근거로는 Telegram 코드나 전체 Cloud Run
  장애보다 `Cloud Run → KMA API허브` 경로의 간헐/지속 장애 가능성이 큽니다.
- 마지막 정상 공통 snapshot은 `LIVE`로 보존됐고, 장애를 해제로 오인하지
  않았습니다.
- 시설담당자 자동 Telegram의 마지막 성공은 2026-08-24 16:10 KST였습니다.
  시설담당자 그룹 전환은 그 이후였고 새 그룹 연결 시험은 성공했습니다. 전환 후
  실제 발효·격상·해제 사건이 없어 새 그룹에는 아직 실전 자동알림이 없었습니다.

다음 작업자는 이 문장을 현재 사실로 가정하지 말고 관리자 overview/status API와
KMA 복구 여부를 다시 확인합니다. KMA 장애 중 새로 발효됐다가 복구 전에 해제된
특보는 시스템이 관측할 수 없다는 한계가 있습니다.

2026-08-28 11:10 KST 공개 API를 읽기 전용으로 다시 확인한 결과:

- 사용자 웹과 `/api/v1/health`는 HTTP 200이었고 API 상태는 `ok`였습니다.
- 공개 운영 준비 상태는 `ready`였으며 자동관제 `live`, 최근 Worker 실행 약 3분,
  KMA 상태 `live`였습니다.
- 공통 monitoring 응답은 `LIVE`, 특보구역 `LIVE`, 시설 103개, 정책
  `2026.08-v1`이었습니다.
- 따라서 위 2026-08-27 KMA 통신 장애는 현재 복구된 상태입니다. 재발 가능성과
  장애 중 미관측 사건 한계는 계속 주의합니다.

2026-08-29 10:35 KST 재확인 결과:

- 공개 API와 운영 준비 상태는 HTTP 200이었고, KMA·특보구역 모두 `LIVE`, 시설
  103개, 활성 특보 0건, 정책 `2026.08-v1`이었습니다.
- `/`, `/control`, `/settings` HTML은 모두
  `Cache-Control: no-cache, no-store, must-revalidate`가 적용됐습니다.
- 공개 PDF 실시간·모의훈련 생성은 정상이며, `3e1f65f`의
  `STALE`·`ERROR` 출력 차단은 Cloud Run API·Worker와 Firebase Hosting에
  배포됐습니다. GitHub Actions 실행 `33227585812`는 전체 성공했습니다.

## 4. 구현 완료 상태

### 제품 기능

- 103개 시설과 6개 시설 그룹 검증
- KMA 공식 특보구역·내장 경계 fallback·공간 매칭·설명 가능한 위험도
- React 모바일 현장 지도와 검색·필터·시설 상세·딥링크
- 시설 현재 기상과 5개 권역 강수·바람·기온 실황 레이어
- 시설담당자/관리자 Telegram 분리, HTML 메시지, 시설 딥링크와 안전한 분할
- 5분 자동감시, 발효·격상·해제, 중복 방지, KMA 장애 상태 보존
- 관리자 09:00/18:00 상태보고와 KMA 장애 추정 진단
- 중앙관제 수동 전파의 분류·훈련·중복 확인·감사 기록·재시도
- 전체 103개 소관시설과 활성 특보를 포함하는 A4 세로 PDF 종합보고서
- SOLAPI SMS 우선 경로, 비용 상한, 웹훅 최종 결과와 Telegram 대체 경로
- 공통 Firestore `MonitoringSnapshot`을 React API·자동알림·Streamlit이 공유
- 관리자 임시 비밀번호 잠금과 외부 uptime monitoring

### 최근 구조 개선

운영 기능을 유지한 채 `AlertDispatcher`의 책임을 단계적으로 분리했습니다.

- `AlertCyclePlanner`: snapshot에서 영향 상태와 변화 계획 계산
- `TelegramOutboxService`: 사용자/관리자 Telegram outbox와 재시도
- `AlertOperationsService`: SOLAPI 잔액과 09/18시 운영보고
- `SmsDeliveryService`: 연락처, 비용 상한, SMS와 Telegram 대체 전달

`fb6c6ff`에서 999줄 `FirestoreAlertStore`를 다음 저장 책임으로 분리했습니다.

- `FirestoreAlertStateRepository`: 잠금, 기준 상태, 배치와 보류 전환
- `FirestoreAlertDeliveryRepository`: SMS 예약과 SOLAPI 최종 결과
- `FirestoreTelegramOutboxRepository`: Telegram 큐, 재시도와 완료
- `FirestoreAlertAuditRepository`: 상태, 실적, 수동 전파와 감사 이력

기존 `FirestoreAlertStore(...)`는 46줄 compatibility facade로 남겼고 collection
이름·핵심 문서 필드·Worker/API 메서드 계약을 테스트로 고정했습니다.

`faeeacb`에서 `load_pending()`과 `due_telegram()`을
`status == PENDING` Firestore 조건 쿼리로 전환했습니다. 완료·만료 이력은 더 이상
매 회차 읽지 않으며 만료 갱신, 다음 재시도 시각과 limit 적용은 기존 애플리케이션
순서를 유지합니다. 자동 단일 필드 인덱스로 충분하므로 composite index 파일,
Firebase 배포 범위와 IAM은 변경하지 않았습니다.

이어서 `alert_pending`과 `alert_telegram_outbox` 컬렉션의 완료·만료(terminal) 문서에
운영 분석용 7일 보존기간과 `delete_after` 타임스탬프 필드를 기록하도록 적용했습니다.
미처리 `PENDING` 문서에는 `delete_after`를 기록하지 않아 활성 작업이 보존되며,
Firestore TTL 정책 설정 가이드를 `docs/FIELD_MAP_DEPLOYMENT.md`에 추가했습니다.

`core/region_resolver.py`의 특보구역 인덱싱 및 공간 매칭 로직을
`safety_dashboard/domain/region_resolver.py`로 이전하고, 현행 패키지(`adapters/`,
`api/`, `ui/`) 내부의 모든 참조를 도메인 계층으로 전환했습니다. 루트의
`core/region_resolver.py`는 구버전 코드 호환 facade로 유지되며, 운영 시설 CSV
(`facilities_info.csv`) 103개소를 단일 기준으로 확립했습니다.

**5단계 사용자 지도 UX 개선**을 완료했습니다:
- **전체 시설 검색**: 현재 선택된 필터(유형·등급)와 무관하게 전체 103개 시설에서 검색을 수행합니다 (`searchFacilities`).
- **필터 자동 완화**: 검색창이나 딥링크에서 필터 밖에 있는 시설을 선택하면, 해당 시설이 지도에 보이도록 필요한 유형과 등급 필터를 자동으로 활성화합니다.
- **0개 표시 상태 복구**: 필터 조합으로 지도에 표시되는 시설이 0개일 때, '전체 시설 다시 표시' 원클릭 액션 버튼과 오버레이를 제공하여 즉시 기본 필터로 리셋합니다.
- **즉시 반영 필터 UX 정렬**: 필터 시트 버튼 문구를 `확인`으로 변경하여 즉시 반영되는 동작과 일치시켰습니다.
- **KMA 지연 표시**: KMA 통신 지연(`stale`) 시 마지막 정상 자료 기준 시각과 함께 경과시간(`formatElapsedTime`, 예: `15분 전`)을 직관적으로 표시합니다.
- **키보드 및 모달 인터랙션**: `Escape` 키 입력 시 열려 있는 모달(CCTV, 필터 시트, 기상 레이어, 같은 위치 목록, 시설 상세 시트)을 순차적으로 닫도록 개선했습니다.

**6단계 React 중앙관제 전환 전체 (1차: 대시보드, 2차: 관제 지도·수동 전파·PDF, 3차: /settings 위험도 정책 설정)**를 완료했습니다:
- **경로 분기와 단일 번들**: SPA 라우터(`router.ts`)로 `/`, `/control`,
  `/settings` 화면을 분기합니다. 초기 구현의 `React.lazy` 청크는 `709d542`에서
  화면 전환 직후 이전 청크가 보이는 문제를 피하기 위해 정적 import 단일 번들로
  전환했습니다. 현재 로컬 프로덕션 JS는 280.60kB(gzip 83.42kB)이며 초기 번들 크기를 계속
  모니터링합니다.
- **운영 상황 대시보드**: 103개 소관시설의 실시간 관제 snapshot을 기반으로 총 시설 수, 특보 영향 시설 수, 위험등급별(상·중·하·영향없음·조회불가) KPI 카드 및 5분 자동 감시 시스템 상태를 표출합니다.
- **점검 우선순위 목록**: 위험등급 높은 순 및 발효 특보 단계 순으로 정렬된 시설 테이블을 제공하며, 등급별/유형별 필터 및 검색 기능을 지원합니다.
- **관리자 관제 지도 & 대상 다중 선택**: 103개 시설의 위치와 특보 경계를 실시간 조망하는 `KakaoMap`을 연동하고, 체크박스 다중 선택(`특보 영향 시설만 선택`, `전체 선택`, `선택 해제`)을 제공합니다.
- **수동 Telegram 상황전파 모달 (`ManualDispatchModal`)**: 재공지/정정/추가안내/모의훈련 분류, 관리자 메모(필수 검증), 문안 자동 미리보기, 중복 발송 방지 최종 확인 및 Cloud Run 관리자 API(`POST /internal/v1/notifications/manual`) 호출을 완벽 연동했습니다.
- **A4 세로형 PDF 현황보고서 다운로드 API (공개 접근)**: 백엔드 `GET /internal/v1/monitoring/report.pdf` 및 `GET /api/v1/monitoring/report.pdf` 엔드포인트를 통해 영남권 특보·시설 정적 지도와 안전수칙이 포함된 공식 보고서를 관리자 인증 없이도 누구나 원클릭으로 스트리밍 다운로드할 수 있도록 공개 전환했습니다.
- **위험도 정책 설정 화면 (`SettingsApp.tsx`) & API**: 백엔드 `GET /internal/v1/policy`를 통해 기본 위험도 정책을 조회하고, 14종 특보 × 3단계(주의보·경보·중대) 위험등급(상·중·하·미판정·없음) 매트릭스 편집 그리드, 발효 특보 상단 하이라이트, 변경 셀 하이라이트 및 브라우저 세션 로컬 저장을 지원합니다.
- **7단계 관리자 잠금 고도화**:
  - HMAC-SHA256 서명 기반 `AdminSessionManager`([session.py](file:///home/dev2/바탕화면/dev2_workfolder/260723_safetydashboard/safety_dashboard/admin/session.py))를 구현하여 안전한 시간 기반 서명 세션 토큰을 생성 및 엄격 검증합니다.
  - Cloud Run 백엔드 `POST /internal/v1/admin/access`에서 비밀번호 검증 성공 시 `Set-Cookie: keco_admin_session=...; HttpOnly; SameSite=Lax; Max-Age=28800`를 발급합니다.
  - 세션 유효성 확인(`GET /internal/v1/admin/session`), 로그아웃(`POST /internal/v1/admin/logout`) 엔드포인트를 추가하고, 모든 보호된 내부 API(`_authorized_admin`)에서 헤더 토큰 및 쿠키 세션을 모두 지원합니다.
  - 관리자 접근 성공/실패/잠금 및 로그아웃 시 구조화된 보안 감사 로그(`LOGGER`)를 체계적으로 기록합니다.
- **9단계 지속적 품질 관리**:
  - `scripts/verify_all.sh` 5단계 통합 검증 스크립트를 작성하여 103개 시설 무결성 검증, Python 단위 테스트 246개, 바이트코드 컴파일, React Vitest 35개 테스트, TypeScript strict 타입 검사 및 프로덕션 번들 빌드를 원클릭으로 통과하도록 체계화했습니다.
  - GitHub Actions CI/CD(`.github/workflows/ci-deploy.yml`) 검증 환경과 로컬 검증 체계를 100% 일치시켰습니다.
  - React·Vite·TypeScript·Vitest의 `latest` 범위를 제거하고 현재 잠금파일에서
    검증한 정확한 버전을 `package.json`과 `package-lock.json`에 기록했습니다.

2026-08-29 10:45 KST에 `scripts/verify_all.sh` 5단계 전체 검증(Python 246개,
React 35개, 시설 데이터 103개, 컴파일 및 프로덕션 빌드)이 모두 통과했습니다.

## 5. 현재 운영 상태 및 최종 인수인계

개선 로드맵([`IMPROVEMENT_ROADMAP.md`](IMPROVEMENT_ROADMAP.md))의 1~9단계와
10단계 구현·자동 검증은 완료했습니다. PDF 5단계 고도화와 운영 산출물 시각
검수도 완료했습니다. STALE·ERROR 차단 변경도 운영에 배포했고,
브라우저가 제공되는 세션의 PC·모바일 버튼 실화면 확인만 남아 있습니다.


### 주요 시스템 구성 및 서비스 현황
1. **현장 안전지도 (`/`)**:
   - 스마트폰 최적화 React SPA (관리자 화면을 포함한 단일 JS 280.60kB,
     gzip 83.42kB)
   - Kakao 지도 기반 103개 시설 위험등급 마커, 원클릭 필터/검색, 실시간 KMA 특보 및 지연 경과시간 표출
2. **중앙관제 대시보드 (`/control`)**:
   - SPA 경로 분기와 정적 import 단일 번들
   - 103개 시설 실시간 관제 KPI 요약, 점검 우선순위 목록, 관제 지도 및 다중 시설 선택 바
   - 수동 Telegram 상황전파 모달(`ManualDispatchModal`)과 선택 상태와 독립된
     A4 세로형 전체 103개소 PDF 종합보고서 다운로드
   - 5분 자동감시 진단, 실적/이력 탭 및 CSV 내보내기
3. **위험도 정책 설정 (`/settings`)**:
   - SPA 경로 분기와 정적 import 단일 번들
   - 14종 기상특보 × 3단계 위험등급 매트릭스 편집 그리드, 발효 특보 하이라이트 및 브라우저 세션 로컬 저장
4. **보안 및 백엔드 API/Worker (Cloud Run)**:
   - HMAC-SHA256 HttpOnly 세션 쿠키 발급, 자동 세션 유지, 로그아웃 및 보안 감사 로그
   - 5분 주기 Cloud Scheduler 기반 자동감시 Worker




## 6. 사용자 의도와 확정 결정

코드만 보면 놓치기 쉬운 현재 유효한 결정입니다.

- **모듈형 모놀리스 유지**: 기능별 MSA나 전면 재작성은 하지 않습니다. API와
  Worker만 실행 단위로 분리하고 내부 모듈 책임을 작게 만듭니다.
- **같은 사이트, 다른 작업 화면**: 시설담당자와 관리자의 정보를 한 화면에
  뒤섞지 않습니다. 장기적으로 React `/control`, `/settings`로 합치되 화면은
  역할별로 분리합니다.
- **관리자 화면은 현재 단일 번들**: `709d542`에서 경로 전환 직후 최신 화면을
  안정적으로 표시하기 위해 `React.lazy` 청크를 정적 import로 합쳤습니다. 다시
  분리하려면 캐시·청크 갱신 문제와 현장 지도 초기 성능을 함께 검증합니다.
- **React가 정식 UI**: 현장 지도·중앙관제·설정은 React에서 운영하며 Streamlit
  진입점은 React 웹 이동 안내만 유지합니다.
- **시설담당자 지도 우선**: 스마트폰·단일 시설 선택·빠른 시각 파악이 우선입니다.
- **내 시설 목록 없음**: 담당 시설이 자주 바뀌므로 개인별 영구 묶음을 만들지
  않고 검색·필터로 선택합니다.
- **Telegram 우선**: 관리자방은 시스템 상태, 시설담당자 그룹은 특보와 현장
  대화입니다. SMS는 필요 시 선택 가능한 보조 경로입니다.
- **사건 기반 자동알림**: 발효·격상·해제만 보내며 무변화 반복 알림은 보내지
  않습니다. 열대야는 자동알림에서 제외합니다.
- **운영 실적의 신뢰성**: 시험·preview·훈련·수동·자동을 섞지 않고 감사 가능한
  정량 실적을 남깁니다.
- **위험도는 정책표**: 공식 내부 기준이 없어 TOML의 직접 등급표를 쓰며, 임시
  편집은 현재 브라우저 세션에만 적용합니다.
- **외부 참고정보 격리**: 현재 기상, 기상 그래픽, 뉴스, 재난문자, CCTV가
  위험등급·자동알림·PDF 기준을 바꾸지 않습니다.
- **CCTV 보류**: ITS 접속 문제를 고정 출구 IP로 해결하면 월비용과 복잡도가 생겨
  시범 단계에서는 운영하지 않습니다. 촬영 방향은 공식 값이 없어 검증된 TOML
  항목만 표시합니다.
- **예보/애니메이션 보류**: 전국 레이더·바람 입자·예보 시간축은 별도 타일
  파이프라인과 모바일 성능 부담 때문에 현재 범위 밖입니다.
- **보안과 비용**: 내부 링크 공유 단계라도 secret은 Git에 넣지 않습니다. 불필요한
  월 고정비와 과도한 클라우드 자원을 피합니다.
- **설명 방식**: 사용자는 쉬운 한국어와 단계별 안내를 선호합니다. 외부 서비스
  설정은 한 번에 한 단계씩 진행합니다.
- **큰 작업은 계획과 구현 분리**: 작은 수정은 바로 처리하되, 여러 영역을 건드리거나
  장시간 걸리는 작업은 먼저 계획만 확정하고 구현은 2~5개의 검증 가능한 단계로
  진행합니다. AI 교체 전에는 새 단계를 시작하지 않고 현재 완료 범위·테스트·다음
  시작점을 계획서와 이 문서에 남깁니다.

## 7. 알려진 부채와 주의점

- `FirestoreAlertStore` 구현은 책임별로 분리됐지만 `AlertStateStore` 포트는 아직
  너무 많은 메서드를 가집니다.
- `AlertDispatcher`는 819줄로 줄었지만 KMA 오류 처리와 경로 조율이 아직 큽니다.
- 루트 구버전 모듈과 `tests/`를 현행 패키지로 완전히 이전하지 못했습니다.
- 제품·기능·도메인 문서의 초기 자동알림 제외 문구는 2026-08-27 현재 운영
  기준으로 정리했지만, 세부 구현 여부는 여전히 코드·테스트와 대조해야 합니다.
- TypeScript strict 타입 검사는 빌드에 포함되어 있고 프런트엔드 의존성은 정확한
  버전으로 고정했습니다. ESLint 정적 규칙은 아직 통합 검증에 포함되지 않았습니다.
- 실제 장애 이메일 수신 시험은 로드맵에 미완료로 남아 있습니다.
- KMA API허브 연결 장애의 근본 해결 또는 공공데이터포털 대체 경로는 미완료입니다.
- 재난문자 API는 신청했지만 React 운영 흐름에서는 보류 상태입니다.

## 8. 작업공간과 비밀정보

- 기준 branch는 `main`, remote는 GitHub `parkgogon/sfety_map`입니다.
- 2026-08-27 문서 작업 시작 시 tracked 변경은 없었습니다.
- 생성 PDF·렌더·제작 중간물은 2026-08-29 사용자 요청으로
  `.trash/obsolete_artifacts_20260829/`로 이동했습니다. `.trash/`, `output/`,
  `tmp/`는 Git에서 제외하며 요청 없이 삭제·커밋하지 않습니다.
- `.streamlit/secrets.toml`, `field_web/.env.local`, 전화번호 명부는 Git에서
  제외됩니다.
- KMA, Kakao, Telegram, SOLAPI, 관리자 토큰·비밀번호는 GitHub/Google Secret
  Manager/Streamlit secrets에 있으며 원문을 문서·로그·응답에 남기지 않습니다.
- `main` push는 운영 배포를 일으킬 수 있으므로 push 권한은 사용자의 요청으로
  확인합니다.

## 9. 새 작업자 시작 체크리스트

```text
[ ] AGENTS.md와 이 문서를 읽음
[ ] branch/status/diff/staged/log 확인
[ ] 최신 사용자 요청과 관련 문서·코드·테스트를 직접 확인
[ ] handoff의 날짜 의존 운영 상태를 재검증
[ ] 기존 dirty/untracked 파일의 소유권을 보존
[ ] 변경 전 수용 조건과 테스트 범위를 정함
```

## 10. 작업 종료 체크리스트

```text
[ ] 실제 변경과 git diff 검토
[ ] 관련 테스트·빌드 결과 확인
[ ] 중요한 완료/미완료/결정을 이 문서의 현재형 내용으로 교체
[ ] 다음 작업을 하나의 구체적인 시작점으로 유지
[ ] 로드맵 체크 상태가 바뀌었다면 함께 갱신
[ ] 비밀값·개인정보·초대 링크가 문서와 diff에 없는지 확인
[ ] push/배포 여부와 운영 영향 보고
```

## 11. 사용자가 새 AI에 붙여넣을 짧은 프롬프트

> 이 프로젝트의 `AGENTS.md`와 `docs/HANDOFF.md`를 먼저 끝까지 읽고, 현재 Git
> branch/status/diff/log 및 관련 코드·테스트와 대조해 실제 상태를 복구한 뒤 기존
> 작업을 이어가라. 문서와 코드가 다르면 코드·테스트·최신 요구사항을 우선하고
> handoff도 갱신하라.
