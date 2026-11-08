# 프로젝트 현재 상태와 인수인계

> 마지막 정리: 2026-11-08 KST — 운영 확인 15:40 KST, 간소화 1·2단계 코드·로컬 검증 완료/운영 미반영.
> 운영 앱 소스: `43b40e0aee7c9f548ef4d633158c2001c2c86a8d` ([PR #1](https://github.com/parkgogon/sfety_map/pull/1) squash merge).
> 배포: [42443589707](https://github.com/parkgogon/sfety_map/actions/runs/42443589707), API·Worker/Scheduler·웹·외부 감시 모두 성공.
> 검수: [42455143090](https://github.com/parkgogon/sfety_map/actions/runs/42455143090) 성공. [운영 증빙](evidence/2026-11-08/production-message-release/README.md).

새 작업자는 [AGENTS.md](../AGENTS.md)와 이 문서를 읽고 실제 Git·코드·테스트를 대조한다.
배포 후 검수 도구·문서 커밋은 `[skip ci]`로 추가했으므로 main HEAD와 운영 앱 소스가 다르다.
원본 기능 작업공간 `/workspace/sfety_map`은 보존했다. 배포 후속 작업공간은
`/workspace/sfety_map-release-20261108`, 브랜치는 `release/message-review-20261108`이다.

## 진행 중인 개선 — 재난문자 업무 간소화

사용자 실사용 피드백: 자동 수신/수동 등록 여부부터 불명확하고, 사람이 입력·확인·저장할 단계가 너무 많다.
자동 수집 → AI가 추천 위치/시설·초안을 준비 → 사람이 한 화면에서 검토하는 방향으로 정리한다.
[간소화 계획](MESSAGE_REVIEW_SIMPLIFICATION_PLAN.md)은 기준 `899e792`에서 작성했고, 사용자 실행 승인으로 **1·2단계 구현·로컬 검증을 완료**했다.
새 작업공간은 `/workspace/sfety_map-simplify`, 브랜치는 `feature/message-review-simplification`이다.
정상 건은 목록에서 열기/검토 완료의 주요 조작 2회, 안내문 복사는 필요할 때 추가하는 것이 목표다.
추천안과 사람의 승인 기록을 분리하고 서버에서 한 번에 검증·확정해야 한다. 화면 접기만으로 해결하지 않는다.
공식 지속 수집·중복 방지·대기열·수동/자동 공통 일일 상한·상태 표시를 구현했다. 실제 공식 키/연결 검증과 운영 활성화는 남았다.
1차 구현 `c70e145`와 후속 예외 복구 보완. [검토용 PR #2](https://github.com/parkgogon/sfety_map/pull/2). 기본은 대기함 → 추천 위치/대상·초안 → 한 번의 내부 검토 완료다.
`prepare`는 확인 기록을 쓰지 않으며 `approve`가 현재 근거를 재검증해 한 버전에 확정한다.
보류 입력은 미승인 작업본으로 보존하고 시설 자료 조회 실패 중에도 저장할 수 있다.
재개/승인 시 현재 근거를 검증하며, 오래된 작업본은 명시적으로 입력을 초기화해 복구할 수 있다. 추천과 승인 결과를 분리하고 기존 상세 관리는 `view=advanced`로 유지한다.
발행 시각 미상은 null이며 현재 시각을 대입하지 않는다. 기존 날짜가 있는 기록과 공식 입력은 유지한다.
1단계 [증빙](evidence/2026-11-08/message-review-simple-stage1/README.md)과 2단계 [검증·화면](evidence/2026-11-08/message-review-auto-stage2/README.md)을 구분한다.
2단계 Python 491개·React 267개·컴파일/빌드/시설 195개 검증을 통과했다.
이후 소유자/서버 연결 점검 검사를 추가한 최신 Python 509개도 통과했다(자동 검사의 실제 외부 HTTP/TCP 0).
로컬 실제 빌드/API/CSV·메모리 저장소/가짜 공식 제공자·합성 분석·가짜 지도 SDK로 PC/390/360px를 확인했다.
브라우저를 열기 전 수집/분석 → 대기함 읽기, 추가 수신 후 읽기 갱신, 미승인 입력 보존과 한도/오류 표시를 검증했다.
로컬 검수의 실제 SafetyData/OpenAI/Kakao 호출은 0건이다. 이후 별도 연결 검수에서 SafetyData를 소유자 1회·임시 서버 4회 조회했다.
AI/장소 추가 호출·실제 발송·운영 앱 배포는 0건이다. 운영 앱은 위의 `43b40e0` 그대로다.

2단계는 별도 IAM 비공개 `safety-message-worker`와 문자 전용 예약 작업 두 개를 opt-in 배포하도록 준비했다.
기존 KMA Worker/dispatch에 모델 실행을 붙이지 않는다. 수집은 기본 오늘·전일, 중단 보충은 최대 7일이며 페이지/행 진행을 저장한다.
원문 버전별 자동 시도 표시와 공통 실행권/한국 날짜 일일 20건 상한으로 중복 분석을 막는다.
한도 초과는 대기 보존, 24시간 넘은 대기/불확실한 중단/제공자 실패는 수동 확인으로 남긴다. 설정·복구 기준은 [운영 안내](MESSAGE_AUTOMATION.md)에 있다.

## 현재 운영 상태 — 2026-11-08 KST

- [재난문자 검토](https://keco-safety-map.web.app/control/messages)는 기존 관리자 로그인으로 사용한다.
  수동·창작 입력 → AI 해석 → 지도 기준점 확인·시설 선정 → 내부 검토 완료·안내 초안/복사 → 후속 문자 연결 흐름이다.
- 정형 KMA 특보는 기존 규칙, 비정형 문자 문맥은 AI가 처리한다. OpenAI Responses가
  장소 검색·주변 시설 조회·최종 제출 도구를 선택하고 조회/검증 피드백에 따라 다음 행동을 정한다.
  모델은 `gpt-5.4-mini-2026-03-17`, reasoning `low`, 최대 6회·80초 처리 예산이다.
- 원문 인용·시간·장소 역할·수신지역·후보 ID를 서버에서 검증한다. 사고지/진행·예정 통제와
  대피 목적지/참고/해제를 구분한다. 좌표는 실제 Kakao 검색, 시설 ID·거리는 CSV 195개소로 계산한다.
- 원문/분석·기준/시설 선정·완료/초안·후속 연결은 전용 Firestore `disaster_message_reviews`에
  버전/CAS·이력으로 저장한다. 재분석/원문/후속 근거 변경은 재검토와 오래된 초안 복사 차단으로 이어진다.
  [업무 계획 완료 기록](archive/DISASTER_MESSAGE_WORKFLOW_PLAN_20261108.md), 단계별 로컬 증빙을 참고한다.
- 사용자 승인으로 GitHub의 기존 키를 GCP에 안전하게 등록했다. 두 Secret 모두 **버전 1**이며 API에 연결했다.
  `MESSAGE_REVIEW_AI_ENABLED=true`, `MESSAGE_REVIEW_OPENAI_VERSION=1`, `MESSAGE_REVIEW_KAKAO_VERSION=1`.
  키 값은 채팅·작업공간·Git·artifact로 가져오지 않았다. 재등록/재발급은 필요하지 않다.
  등록 계정의 임시 버전 추가 권한은 만료됐으며 runtime 읽기 권한은 유지한다.
- 현재 API는 `safety-dashboard-api-00088-b7t`·100%다. Hosting 버전은 `208642a1dcee0450`이다.
  Worker는 배포 후 KMA 경로 연결 실패가 34회까지 이어져 동일 이미지/실행 설정으로
  `safety-alert-worker-net-refresh-20261108063331`·100%로 재기동했다.
  [재기동 42455222467](https://github.com/parkgogon/sfety_map/actions/runs/42455222467)에서 전체 runtime spec 동일을 확인했다.
  **15:35 KST 원래 Scheduler 감시 실행 후 KMA LIVE·Worker 정상·health 2종 HTTP 200**이다.
  15:40 KST 다음 정규 실행에서도 KMA LIVE·Worker 정상·운영 health 200을 재확인했다.
  특정 이전 인스턴스의 정확한 네트워크 장애 원인과 장기 재발 여부는 미확정이다.
- 창작 검수 기록은 `manual-44013dfc139140e882c5c9af012ddd5b`, 출처는 `운영 배포 검수 · 창작 예문`이다.
  저장된 AI 모델 호출은 3회, 시설 1개 선정·초안/클립보드·새로고침 복구·실제 SDK/타일을 확인했다.
  최종 재검수는 AI 요청 0회, 타일 24응답/렌더된 지도 이미지 9개, 화면 오류/예상 밖 요청 0건이다.
  PC·390px 캡처의 한글/지도와 가로 넘침을 확인했고 로그인 화면은 1440/390/360px도 확인했다.
- 검수는 관리자 비밀번호가 GCP 임시 실행 안에만 머무는 IAM 비공개 서비스로 수행하고 삭제했다.
  첫 Job 검수의 내부 로그는 실행 계정 권한으로 읽을 수 없었다. 결과 회수/타일 계측을 보완한 뒤
  같은 창작 기록으로 전체 검수를 통과했다. 첫 실패와 이후 성공을 증빙에서 구분한다.
- 공식 SafetyData 키의 GCP 생성은 사용자 확인했지만 **운영 참조/실제 API 연결은 미완료**다. 관리자 지역·하루·페이지 조회 코드는 있으나
  현재 자동 상시 수집이 아니다. 실기기 터치/핀치·장기 운영 부하 검수는 남았다.
- 검토 완료는 내부 검토이며 현장 확인·실제 발송이 아니다. 대표점 반경은 위험 반경이 아니며
  창작 시연을 정확도·피해 예방 실적으로 확대하지 않는다. 기존 위험도/알림 기준은 유지한다.

## 1. 프로젝트와 현재 구성

대구·경북·부산·울산·경남 소관시설 195개소를 KMA 공식 기상특보와 대조해
영향도와 점검 우선순위를 보여주는 내부 시범 운영 시스템이다.

```text
KMA 특보 → 시설 위치 대조 → 위험도·점검 우선순위 → 지도·담당자 알림·PDF
```

- 정식 UI: Firebase React SPA + Kakao Maps. `/` 현장 지도, `/control` 중앙관제, `/settings` 정책 설정, `/control/messages` 재난문자 검토.
- 중앙관제: 운영 상황 / 대상 분석·전파 / 실적·이력. 관리자 비밀번호를 서버에서 검증하고
  8시간 서명 세션·HttpOnly 쿠키와 기존 관리자 토큰 헤더 호환을 유지한다.
- API: Cloud Run `safety-dashboard-api`, 서울 `asia-northeast3`.
  조립 진입점·공통 서비스·요청 모델·인증 경계와 업무별 라우터로 분리했다.
- Worker: Cloud Run `safety-alert-worker`, 최대 인스턴스 1. Scheduler가 5분마다 OIDC로 호출한다.
- Firestore: 공통 MonitoringSnapshot, 자동알림 기준 상태, outbox, 실적·감사 이력.
- 코드 구조는 모듈형 모놀리스이며 API와 Worker만 실행 단위로 분리한다.
- Streamlit 화면·실행/접속 경로, 루트 구버전 provider/service/위험도/보고서/UI는 제거했다.
  Python 테스트는 `tests/`, 프런트엔드 지도 내부는 `field_web/src/map/`에 모았다.
- 서버는 환경변수만 읽는다. Streamlit secrets fallback은 제거했고 로컬 `.env`는 Git에서 제외한다.
  원본 시설 자료·KMZ·폰트와 기존 Git 제외 산출물은 보존했다.

시설 데이터는 `facilities_info.csv`가 단일 기준이다. 데이터 검증 결과는 다음과 같다.

| 유형 그룹 | 개수 |
|---|---:|
| 대기측정소 | 55 |
| 수질측정소 | 21 |
| 영농폐기물 수거사업소 | 8 |
| 영농폐비닐 재활용시설 | 3 |
| 공공하수처리시설 | 78 |
| 시설현장 | 14 |
| 기타시설 | 16 |

## 2. 검증과 이전 운영 기록

- 배포 CI: Python 423개·React 255개, 컴파일·CSV 195개·웹 빌드 통과.
- 배포 후 검수/복구 도구 포함 Python **429개**, 실제 외부 HTTP/TCP 시도 0건, compileall·CSV 검증 통과.
- 최신 실제 운영 검수와 복구 전후 리비전/Hosting 정보는 [2026-11-08 증빙](evidence/2026-11-08/production-message-release/README.md)에 있다.
- 구조 개선은 [보관 계획](archive/REFACTORING_PLAN_20261024.md)과 [브라우저 검수](REFACTORING_BROWSER_CHECK.md)를 따른다.
- 기존 주변 시설 PDF·기상 혼합형과 실제 지도/PDF 검수는 [2026-10-25 최초 배포](evidence/2026-10-25/production-deploy/README.md),
  [기상 복구](evidence/2026-10-25/weather-recovery/README.md)에 보존한다. 당시 버전/관측이며 최신 버전은 위와 같다.

## 3. 시험 발송 금지 — 사용자 확정 요구

운영 Telegram방에 실제 참여자가 있다. 개선·자동 테스트·브라우저 검수에서
실제 Telegram·SMS를 보내지 않고 운영 수동전파·Worker 시험/dispatch 경로를 호출하지 않는다.

```bash
.venv/bin/python scripts/run_python_tests.py
bash scripts/verify_all.sh
```

Python 공통 실행기는 테스트 수집 전부터 실제 HTTP·TCP를 차단한다. 앱이 차단 예외를
처리해도 통신 시도가 있으면 실패한다. 프런트엔드도 테스트 사이의 비동기 작업까지
실제 fetch/XHR/beacon을 차단하고 가짜 API 누락을 실패로 판정한다.
수동전파·실패·재시도는 가짜 제공자와 메모리 저장소로만 검증한다.
자동 테스트의 실제 외부 통신 시도는 0건이며, 이 작업에서 Telegram/SMS 시험 발송은 0건이다.
이 수치는 운영 시스템이 정상 감시 중 보내는 실제 업무 알림의 건수를 뜻하지 않는다.

## 4. 유지해야 할 제품·업무 결정

- 스마트폰 현장 지도와 관리자의 기상 종합보고·전파 작업은 역할별로 분리한다.
  기준점 주변 시설 현황 보고서는 사용자 승인에 따라 현장·관제 모두 제공한다.
  담당 시설이 자주 바뀌므로 개인별 영구 내 시설 묶음은 만들지 않는다.
- 위험도는 특보 종류 × 단계 TOML 정책표다. 최고 등급을 적용하고 모든 근거를 보존한다.
  브라우저 임시 정책과 훈련은 운영 기본 정책·기준 상태에 섞지 않는다.
- KMA 실패를 해제로 보지 않는다. 마지막 정상 특보를 보존하고 STALE·ERROR에서는 새 수동전파·기상 PDF를 차단한다.
  기상과 독립적인 주변 시설 현황 PDF는 시설 CSV가 정상인 경우 생성할 수 있다.
- 자동알림은 발효·격상·해제 변화만 전파하며 무변화를 반복 발송하지 않는다. 열대야는 자동알림 제외 기본값이다.
- 시설담당자 그룹은 시설 특보·현장 대화, 관리자방은 시스템 운영 상태에 사용한다.
  Telegram 우선이며 SMS는 선택형 보조 경로다. 자동·수동·훈련·시험 실적을 분리한다.
- 선택 시설과 거리가 가까운 임시 기준점은 참고정보다. 위험도·자동알림·수동전파 대상·기상 PDF를 바꾸지 않는다.
  별도 주변 시설 PDF에는 확정 기준점과 보고서 반경을 사용한다.
  새로고침·페이지 이동·실시간/훈련 전환 시 초기화하고 관제 내부 탭 이동 시에는 유지한다.
- 현재 기상·기상 그래픽·뉴스·CCTV도 참고정보이며 위험도에 혼합하지 않는다.
- 단일 시설 마커는 배율 유지, 클러스터는 확대한다. 검색·딥링크는 숨은 시설 필터를 완화해 표시한다.
- 바람은 중립색 파티클과 푸른 풍속 색면을 유지한다. 기상 canvas는 지도 이동과 동기화한다.
- 기상 PDF는 전체 소관시설 종합보고가 기본이며 선택 시설 API 계약도 유지한다.
  주변 시설 PDF는 CSV로 반경 안 시설을 다시 계산하며 기상 PDF·특보 영향 판정과 구분한다.
  주변 시설 고도화 시안은 카카오 일부 지역 캡처·자동 요약 중심이다. 사건명/메모 입력을 추가하지 않는다.
  인접성으로 피해·위험도·도착 시간을 추정하지 않으며 시안 검토와 운영 통합은 구분한다.
- 전화번호·키·비밀번호·원본 외부 응답을 화면·보고서·전파·로그·snapshot에 노출하지 않는다.
- 큰 작업은 승인한 계획을 한 단계씩 검증한다. 사용자는 쉬운 한국어와 외부 서비스 설정의 단계별 안내를 선호한다.
- `main` push가 API·Worker·웹 운영 배포를 일으킨다. 커밋·push·배포는 별도 사용자 요청 시 수행한다.
- 이전 운영 검수 기록은 `inspection/production-browser-check-20261024`에 보존한다.
  기능 브랜치 `feature/map-ui-nearby-report-20261025`의 최종 검토 `51672b1`은 사용자 요청으로
  main `616d7a2`에 반영·자동 배포했다. 당시 배포에서는 별도 수동 워크플로 실행이나 발송 시험을 하지 않았다.

## 5. 다음 시작점

다음 시작점은 **본인 SafetyData 일일 호출 한도와 조회 주기/범위를 맞춘 활성화 설정 확정**이다.
사용자 캡처에서 기존 긴급재난문자 이용신청의 `승인` 상태를 확인했고, 기존 인증키도 찾았다.
사용자는 GCP `keco-safety-map`에 `SAFETY_DATA_API_KEY`를 만들었다고 확인했다. 재신청/재발급/재등록을 반복하지 않는다.
키 값은 채팅/GitHub 파일로 받지 않는다. 기존 OpenAI/Kakao Secret 버전 1도 다시 등록하지 않는다.
2026-11-08 11:38 UTC [읽기 전용 점검 42476639226](https://github.com/parkgogon/sfety_map/actions/runs/42476639226)은
API ready·운영 이미지 `43b40e0`·SafetyData 환경변수 참조 미연결을 확인했다. 점검 계정의 Secret/DB/IAM 메타데이터 조회가
권한 부족이어서 실행은 실패했다. 이것은 키 등록 실패나 기존 AI/Firestore의 운영 장애를 증명하지 않는다.
실제 키 값 조회·API 호출·DB 접근·배포·발송은 0건이다.
사용자가 소유자용 도구 `467234b --grant-runtime`을 실행했다. [키 값 없는 실행 결과](evidence/2026-11-08/safetydata-registration-preflight/owner-check.json)에서
ENABLED 버전 **1**, runtime 읽기 역할 추가, API 1회 응답을 확인했다. 오늘 대구 조건은 `valid_empty_response`/0건이었다.
이 결과는 Cloud Shell에서의 응답이며 실제 문자 필드·날짜/지역/페이지·Cloud Run 통신 확인은 아직 아니다. 권한 추가를 반복하지 않는다.
추가 [실제 서버 점검 42478871279](https://github.com/parkgogon/sfety_map/actions/runs/42478871279)은 성공했다.
고정 기존 worker 이미지·동일 runtime 계정·Secret 버전 1로 임시 IAM 비공개 서비스에서 4회 조회했다.
오늘 전국 첫/둘째 페이지 각 2건·부산 1건과 첫 페이지 재대조를 확인했고 날짜/지역·요청 페이지 크기·ID 비중복·첫 페이지 안정 검사가 통과했다.
임시 서비스 삭제 단계도 성공했다. 원문/ID·키는 내보내지 않았다. [값 없는 결과](evidence/2026-11-08/safetydata-registration-preflight/runtime-check.json).
운영 API/기존 Worker/예약 실행/DB/AI/발송 경로를 바꾸지 않았으며, 실제 운영 상시 수집은 아직 아니다.
기본 5분/5지역/오늘·전일 조회는 첫 페이지만 하루 2,880회다(추가 페이지/대조/수동 조회 별도). 사용자 계정의 실제 일일 한도를 비동기 질문으로 확인 중이다.
한도 숫자를 받기 전 설정을 활성화하지 않는다. 제공 지연·과거 날짜/자정 경계·실제 계정 쿼터·이용 조건은 [연결 기준](MESSAGE_AUTOMATION.md)에 따라 추가 확인한다.
실제 계약 확인 전 `MESSAGE_COLLECTION_ENABLED`와 `MESSAGE_COLLECTION_CONTRACT_VERIFIED`는 false다.
별도 사용자 요청 전 main 반영/운영 배포·실제 전파 시험을 하지 않는다. 3단계 후속 제안/비교는 아직 미구현이다.
후속 문자 자동 제안/변경 검토와 운영 전환은 3·4단계다. 단계별 수용 조건은 위 계획을 따른다.

- [재난문자 운영](MESSAGE_REVIEW_OPERATIONS.md), [키 설정](MESSAGE_REVIEW_KEY_SETUP.md)
- [로드맵](IMPROVEMENT_ROADMAP.md), [배포](FIELD_MAP_DEPLOYMENT.md)
- [제품](PRODUCT.md), [업무 규칙](DOMAIN_RULES.md), [구조](ARCHITECTURE.md)
