# 프로젝트 현재 상태와 인수인계

> 살아 있는 현재 상태 문서입니다. 작업일지가 아닙니다.
>
> 마지막 정리: 2026-08-27 10:07 KST
> 기준 Git: `main` / `fb6c6ff Split Firestore alert store responsibilities`

새 작업자는 먼저 루트의 [`AGENTS.md`](../AGENTS.md)를 읽고, 이 문서를 실제
Git·코드·테스트와 대조해야 합니다. 아래 운영 상태는 시간이 지나면 달라질 수
있으므로 날짜가 붙은 값은 반드시 다시 확인합니다.

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

- 현재는 `app.py` Streamlit 앱의 `/control`, `/settings` 화면입니다.
- Streamlit 운영 URL은 저장소에 기록하지 않습니다. Streamlit Cloud 배포 화면에서
  확인해야 합니다.
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

## 3. 운영 설정 — 2026-08-27 확인

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

### 현재 운영 이슈

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
- 선택 시설과 연결 특보만 포함하는 A4 가로 PDF 보고서
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
2026-08-27 10:07 KST에 구버전 Python 22개, v3 Python 185개, React 21개,
데이터 검증, Python compileall과 React production build가 모두 통과했습니다.

## 5. 진행 중인 개선과 다음 작업

확정 로드맵은 [`IMPROVEMENT_ROADMAP.md`](IMPROVEMENT_ROADMAP.md)입니다.
현재는 **3단계 Firestore 쿼리 효율화** 직전에 멈춰 있습니다.

### 다음 개발 작업

`load_pending()`과 `due_telegram()`의 collection 전체 scan을 조건 query로
바꾸고 필요한 Firestore index를 배포 설정에 명시합니다.

권장 진행 순서:

1. `alert_pending`은 `status == PENDING`으로 서버 필터링하고 만료 처리와
   반환 의미가 기존과 같은지 가짜 query로 검증합니다.
2. `alert_telegram_outbox`는 `status == PENDING`과 `next_attempt_at <= now`를
   이용하고, 만료 작업·limit·재시도 순서가 변하지 않게 합니다.
3. 필요한 composite index를 `firestore.indexes.json`과 Firebase 설정에 추가하고
   CI 배포 범위를 확인합니다.
4. 구조 분리 커밋과 쿼리 변경 커밋을 합치지 않습니다.
5. TTL은 쿼리 동등성을 확인한 뒤 다음 작업으로 남깁니다.

수용 조건:

- 반환되는 보류 전환과 due Telegram 작업이 기존 구현과 같습니다.
- 만료 상태 갱신, 수동 전파·배치 실패 반영과 실적 카운터가 유지됩니다.
- 기존 자동알림 기준 상태와 outbox 문서를 초기화하거나 재생성하지 않습니다.
- 필요한 index가 코드와 함께 재현 가능하게 관리됩니다.
- 전체 Python·React 테스트와 데이터 검증이 통과합니다.

그 다음은 오래된 outbox·임시 상태 TTL을 적용한 뒤 로드맵 4단계 구버전
코드/CSV/산출물 정리, 사용자 지도 UX, React 중앙관제 전환 순서입니다.

## 6. 사용자 의도와 확정 결정

코드만 보면 놓치기 쉬운 현재 유효한 결정입니다.

- **모듈형 모놀리스 유지**: 기능별 MSA나 전면 재작성은 하지 않습니다. API와
  Worker만 실행 단위로 분리하고 내부 모듈 책임을 작게 만듭니다.
- **같은 사이트, 다른 작업 화면**: 시설담당자와 관리자의 정보를 한 화면에
  뒤섞지 않습니다. 장기적으로 React `/control`, `/settings`로 합치되 화면은
  역할별로 분리합니다.
- **Streamlit은 임시 관리자 UI**: React 기능 동등성 전에는 제거하지 않습니다.
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

## 7. 알려진 부채와 주의점

- `FirestoreAlertStore` 구현은 책임별로 분리됐지만 `AlertStateStore` 포트는 아직
  너무 많은 메서드를 가집니다.
- `AlertDispatcher`는 819줄로 줄었지만 KMA 오류 처리와 경로 조율이 아직 큽니다.
- 루트 구버전 모듈과 `tests/`를 현행 패키지로 완전히 이전하지 못했습니다.
- 제품·기능·도메인 문서의 초기 자동알림 제외 문구는 2026-08-27 현재 운영
  기준으로 정리했지만, 세부 구현 여부는 여전히 코드·테스트와 대조해야 합니다.
- Firestore의 일부 pending/event 조회는 전체 scan을 사용합니다. 구조 분리 뒤
  query/index/TTL 개선이 필요합니다.
- React 의존성이 `latest`로 고정되어 재현성이 약합니다. 품질관리 단계에서 명시
  버전과 ESLint/타입 검사를 추가할 예정입니다.
- 실제 장애 이메일 수신 시험은 로드맵에 미완료로 남아 있습니다.
- KMA API허브 연결 장애의 근본 해결 또는 공공데이터포털 대체 경로는 미완료입니다.
- 재난문자 API는 신청했지만 React 운영 흐름에서는 보류 상태입니다.

## 8. 작업공간과 비밀정보

- 기준 branch는 `main`, remote는 GitHub `parkgogon/sfety_map`입니다.
- 2026-08-27 문서 작업 시작 시 tracked 변경은 없었습니다.
- `output/`, `tmp/`는 untracked이며 보고자료와 임시 산출물이 있으므로 삭제하거나
  이번 작업에 섞지 않습니다.
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
