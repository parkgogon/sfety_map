# 프로젝트 현재 상태와 인수인계

> 마지막 정리: 2026-10-25 KST
> 운영 소스: `616d7a2` — 최종 검토한 기능 브랜치 `51672b1`을 main에 병합·push했다.
> 배포 근거: [GitHub Actions 40160348628](https://github.com/parkgogon/sfety_map/actions/runs/40160348628) 테스트·API/Worker·웹·외부 감시 설정 모두 성공.
> 운영 직접 검수: 2026-10-25 13:06~13:19 KST. 웹 버전 `616d7a2`, UI·카카오 지도 포함 PDF 확인. **실황 기상 격자 조회 실패가 남으며, 후속 진단에서 시설 기상의 `ConnectTimeout`을 확인했다.**

새 작업자는 [AGENTS.md](../AGENTS.md)와 이 문서를 읽고 실제 Git·코드·테스트를 대조한다.
문서 인계 커밋은 배포 후 `[skip ci]`로 추가하며 운영 앱 소스 버전과 구분한다.

## 최신 배포·검수 — 2026-10-25

사용자가 main 병합/push·자동 배포·운영 검수를 명시적으로 승인했다.
기존 원본/점검/기능 작업공간을 보존하고 별도 `/workspace/sfety_map-release-20261025`의 main에서 반영했다.
Telegram·SMS 시험 발송과 운영 수동전파·Worker·dispatch·발송 시험 경로 호출 금지는 유지한다.
자동 배포는 기존 Worker/Scheduler 설정도 적용했으며 수동 시험 실행은 하지 않았다.

- 지도 설정의 중복 ‘지도 보기’를 제거하고 시설 수·즉시 필터 반영·닫기/포커스를 유지했다.
  관제 헤더 넘침·새로고침 색·설정 로그인 줄바꿈을 운영 360/390/430/700/1440px에서 확인했다.
- 혼합형 기상(바람 A, 기온/강수 B)을 운영 공통 레이어에 적용했다. 원본 관측·위험도는 바꾸지 않는다.
  실황은 현재 `ERROR`/0점·“기상청 격자 위치를 확인하지 못했습니다.”다. 특보 상태 `LIVE`와 별개다.
  운영 모의훈련 API의 `SIMULATION`/실제 관측 아님 표시로 표현·이동/줌·움직임 줄이기를 따로 확인했다.
- 주변 시설 보고서는 현장 PC/모바일·관제에서 실제 장소를 지정해 생성했다. 세 화면 모두 3개소·지도 `captured`였고
  0개소 보고서도 지도 포함 정상 발급됐다. 실제 PDF를 렌더해 도로·번호·목록·집계·한글을 직접 검토했다.
  CSV 재계산·대상 digest·기상 독립성과 기존 기상 PDF STALE/ERROR 차단을 유지한다.
- 요청 제한은 인스턴스당 캡처 1·보고서 3·PDF 계산 1건이다. 대기 중 취소는 계산을 시작하지 않고,
  이미 시작한 계산은 슬롯 반환까지 정리한다. 지도 실패는 명시한 목록/집계 PDF, 시설 자료 오류는 503이다.
- API `safety-dashboard-api-00086-zn7`: 1 CPU/1GiB·캡처 활성. Worker `safety-alert-worker-00074-47k`:
  기존 1 CPU/512Mi·별도 브라우저 없는 이미지. 두 서비스 모두 배포 로그의 트래픽 100%를 확인했다.
- CI Python 256개(외부 HTTP/TCP 0)·React 215개·컴파일/데이터/빌드 통과.
  로컬 SDK 검수와 구분한 [운영 배포·직접 검수 증빙](evidence/2026-10-25/production-deploy/README.md),
  [보고서 동작](NEARBY_FACILITY_REPORT.md), [배포 설정](FIELD_MAP_DEPLOYMENT.md)을 따른다.

개인 로컬 브라우저 도구가 없어 클라우드 Chromium으로 조작했다. 모바일은 viewport 에뮬레이션이며 실기기가 아니다.
운영 검수에는 정적/SDK/API 응답 대체나 가짜 기상 주입을 쓰지 않았다. 운영 모의훈련은 명시한 합성 훈련값이다.
후속 [기상 진단](evidence/2026-10-25/weather-diagnosis/README.md)에서 운영 시설별 기상이 `ConnectTimeout`/7.342초임을 확인했다.
같은 provider의 로컬 API 이미지(1 CPU/1GiB)는 실제 기온 1,244점을 정상 처리했고 운영 지도 캡처도 다시 성공했다.
API의 KMA 연결 경로 문제가 가장 유력하다. 후속 사용자 Cloud Shell 조회에서 API/Worker의 VPC·egress annotation은 null,
프록시 변수는 없고 서비스 계정·KMA Secret 참조는 같았다. 격자 경로의 세부 예외·실제 출구 차이·정확한 차단 원인은
아직 확인하지 못했다. 앱/운영 설정을 바꾸거나 재배포하지 않았다.

이전 [최종 리뷰](evidence/2026-10-25/final-review/README.md), [로컬 통합](evidence/2026-10-25/nearby-integration/README.md),
[보고서 시안](evidence/2026-10-25/nearby-preview/README.md), [기상 시안·선택](WEATHER_VISUAL_REVIEW.md)은 당시 단계 기록이다.

## 1. 프로젝트와 현재 구성

대구·경북·부산·울산·경남 소관시설 195개소를 KMA 공식 기상특보와 대조해
영향도와 점검 우선순위를 보여주는 내부 시범 운영 시스템이다.

```text
KMA 특보 → 시설 위치 대조 → 위험도·점검 우선순위 → 지도·담당자 알림·PDF
```

- 정식 UI: Firebase React SPA + Kakao Maps. `/` 현장 지도, `/control` 중앙관제, `/settings` 정책 설정.
- 중앙관제: 운영 상황 / 대상 분석·전파 / 실적·이력. 관리자 비밀번호를 서버에서 검증하고
  8시간 서명 세션·HttpOnly 쿠키와 기존 관리자 토큰 헤더 호환을 유지한다.
- API: Cloud Run `safety-dashboard-api`, 서울 `asia-northeast3`.
  조립 진입점·공통 서비스·요청 모델·인증 경계와 업무별 7개 라우터로 분리했다.
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

## 2. 완료한 구조 개선과 검증

1. 안전한 테스트 실행기를 도입하고, 누락된 STALE·ERROR 수동전파 차단 검증을 기본 실행에 포함했다.
2. Streamlit·구버전·중복 자료를 정리하고 현행 검증을 이전했다. 디자인 토큰은 React로 옮겼다.
3. 공통 관리자 인증 훅, 중앙관제 3개 화면과 상태 훅, 현장 선택·필터·패널 훅과 영역별 CSS를 분리했다.
4. 지도 런타임·시설/CCTV·특보·기상·기준점/이동을 분리했다. SDK 타입, 지도별 준비 구독과 이벤트/오버레이 해제를 적용했다.
5. API 조립·7개 라우터와 Worker의 MonitoringHealthService, 상태·발송·outbox·감사 저장 포트를 분리했다.

최종 `bash scripts/verify_all.sh` 검증:

- 시설 195개·7그룹, Python 231개·React 195개 테스트 통과.
- Python 컴파일, TypeScript strict·미사용 선언 검사, 프로덕션 빌드 통과.
- Streamlit·pandas·Folium이 없는 새 가상환경에서도 Python 전체와 의존성 검사가 통과했다.
- 기존 `create_app` 테스트 주입 인자와 20개 HTTP 경로의 OpenAPI 명세가 변경 전후 동일하다.
- Worker 생성 인자·응답 직렬화와 KMA/snapshot 처리 로직을 대조했다.
  상태 서비스 위임을 제외하면 기존 업무 메서드 본문과 실행 순서가 동일하다.
- Firestore 어댑터·스키마·문서 ID·중복 방지 키·스케줄·위험도 정책·운영 시설 데이터는 변경하지 않았다.
- CSS 선언 순서를 보존했고 프로덕션 CSS 해시는 `B8mJRUsf`로 유지됐다.

로컬 Chromium에서 390×844·430×932·700×360·1440×900의 세 화면을 검수했다.
가로 넘침·페이지 오류가 없고 지도 인스턴스 보존, 관제 탭 간 시설 선택 유지,
가짜 수동전파 1회와 대상 일치를 확인했다. 실제 API/SDK 대신 가짜 구현을 사용했으며
실제 Kakao 타일·실기기 검수 범위는 [검수 기록](REFACTORING_BROWSER_CHECK.md)에 구분했다.

2026-10-24 사용자 요청에 따라 `e1f6c0d`를 main에 push하고 기존 GitHub Actions로 배포했다.
CI의 Python 231개·React 195개 테스트와 빌드, 다음 운영 배포 작업이 모두 성공했다.

- API: `safety-dashboard-api-00085-gg5`, 트래픽 100% 적용.
- Worker: `safety-alert-worker-00073-6d5`, 트래픽 100% 적용.
- Scheduler: 기존 `*/5 * * * *`, `Asia/Seoul`, 활성 상태 유지.
- Firebase Hosting: [운영 지도](https://keco-safety-map.web.app), 웹 소스 버전 `e1f6c0d`.
- 외부 가동상태 감시 설정 작업 성공.

배포 성공은 Actions 결과와 배포 로그로 확인했다. 이후 2026-10-24 새 환경에서
운영 세 화면·공개 health 2종의 HTTP 200과 웹 버전 `e1f6c0d`를 직접 확인했다.
20:31~20:50 KST에는 타일이 차단됐으나, 21:15~21:28 KST 재점검에서 실제 타일 200과
도로·지형 위 마커·검색·거리·기상 그래픽의 표시 및 이동·확대 정합을 확인했다.
직접 확인과 차단·미검증 범위는 아래 5절 및 [검수 기록](REFACTORING_BROWSER_CHECK.md)을 따른다.
운영 dispatch·시험 발송은 호출하지 않았다.

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
  main `616d7a2`에 반영·자동 배포했다. 별도 수동 워크플로 실행이나 발송 시험은 하지 않는다.

## 5. 운영 관측의 범위와 남은 검수

최신 직접 검수는 **2026-10-25 13:06~13:19 KST**다. [운영 증빙](evidence/2026-10-25/production-deploy/README.md)에
확인·실패/차단·미검증과 PDF·캡처·모의훈련 영상·요청 요약을 보관했다.

- SDK/타일과 장소 검색은 실제 응답을 사용했고 환경 revision 23/current/enforced·프록시/TLS를 유지했다.
  추가 허용이 필요한 실패 SDK 호스트는 없다. 타일 이동/페이지 종료의 `ERR_ABORTED`는 별도로 기록했다.
- 실황 바람·기온·강수 API는 HTTP 200이지만 업무 상태 `ERROR`/0점이다. 운영 Cloud Run의 격자 좌표 조회 실패다.
  관리 환경에서 같은 원본 좌표 API는 200·37,697값을 받았지만 운영 Cloud Run의 실패 원인을 입증한 것은 아니다.
  Cloud Run 로그/출구 경로·KMA 서비스 권한의 실제 대조는 남는다. 오류를 무풍·무강수로 바꾸지 않았다.
- 기상 그래픽은 운영 모의훈련 값으로만 움직임/줌을 확인했다. 실제 관측값 표현이 통과했다고 표시하지 않는다.
  초기 타일 로딩과 줌 전환을 영상에 포함했으며 모든 배율에서의 지연/성능을 보장하는 검수가 아니다.
- 현장 PC/모바일·관제 PDF 3건과 0개소 API PDF 1건이 실제 `captured`다. 0개소 생성 7.335초,
  병행 공개 health 4건 모두 200(313~437ms)이었다. 프록시 왕복을 포함한 표본이며 부하 검증이 아니다.
- 관리자 인증이 없어 인증 전 화면까지만 확인했다. 실기기 터치/핀치·장시간 배터리/발열,
  운영 40개 동시 요청/장기 부하·메모리 최고치·취소 후 서버 프로세스 정리는 이번에 검증하지 않았다.
- CCTV는 웹/API 모두 비활성이다. 실제 발송·운영 dispatch·Worker 시험 호출도 하지 않았다.
- 이전 운영 점검의 차단·해소 이력은 [2026-10-24 기록](evidence/2026-10-24/tile-followup/README.md)에 보존한다.

## 6. 시작점과 주요 문서

지도 UI·기상 혼합형·지도 포함 보고서의 구현/최종 리뷰·main 병합·운영 배포와 직접 검수를 마쳤다.

**다음 시작점 하나**: 사용자의 Cloud Shell에서 [인증키 없는 KMA 연결/TLS 대조 명령](evidence/2026-10-25/weather-diagnosis/README.md)을 실행한다.
API/Worker 설정 비교는 사용자 제공 조회 결과로 완료했고, 조회 항목에서 차이를 발견하지 못했다.
Cloud Shell 결과와 운영 API의 실제 출구는 구분하며, 필요하면 revision/traffic·실제 출구 IP·KMA 접근 정책으로 좁힌다.
현재 관리 환경에는 GCP identity/manifest와 gcloud가 없어 제어 영역 직접 조회는 실행하지 못했다.
연결 문제 해결 후 실제 실황으로 바람/기온/강수 표현을 재검수한다.
프록시·TLS 우회나 시험 발송/Worker·dispatch 호출로 확인하지 않는다.

현재 배포/인계 작업공간: `/workspace/sfety_map-release-20261025`, main. 운영 앱 소스는 `616d7a2`다.
기능 작업공간 `/workspace/sfety_map-improvements`의 `feature/map-ui-nearby-report-20261025` 최종 `51672b1`은 보존했다.

이전 운영 점검 작업공간(2026-10-24):


- 원본 `/workspace/sfety_map`: `work`, HEAD `99e47f2`. 시작 시 미커밋·미추적 변경이 없었고
  원본 파일·사용자 산출물을 변경하지 않았다. 원격 fetch만 수행했다.
- 점검 `/workspace/sfety_map-inspection`: `inspection/production-browser-check-20261024`,
  시작 커밋 `4993731`. 원격 점검 브랜치와 main `24180e5`를 시작·종료 전에 직접 대조했다.
  다른 환경의 로컬 경로가 존재한다고 가정하지 않는다.
- Git 전달 증빙은 [기존 증빙](evidence/2026-10-24/README.md)의 PNG 50장과
  [최신 증빙](evidence/2026-10-24/tile-followup/README.md)의 PNG 45장·요약이다.
  기존 증빙은 변경하지 않았다. query·헤더·쿠키·키·원시 API 응답·환경 설정 전체는 넣지 않았다.
  이번 실행 스크립트·중간 캡처·query 제거 상세 요청 로그는 `/workspace/inspection-runtime/`에만
  남겨 두며 새 환경에서 해당 로컬 파일의 존재를 전제로 하지 않는다.

- [아키텍처](ARCHITECTURE.md), [배포·로컬 실행](FIELD_MAP_DEPLOYMENT.md), [자동알림](AUTOMATIC_ALERTS.md)
- [업무 규칙](DOMAIN_RULES.md), [디자인](DESIGN_SYSTEM.md), [UI 흐름](UI_FLOW.md)
- [구조 개선 완료 기록](archive/REFACTORING_PLAN_20261024.md), [이번 브라우저 검수](REFACTORING_BROWSER_CHECK.md)
- [모바일 UI 완료 계획](archive/MOBILE_MAP_UX_PLAN.md), [당시 검수](MOBILE_MAP_UX_BROWSER_CHECK.md)

`output/`·`tmp/`·`.trash/`는 Git 제외 산출물·임시·보관 공간이다. 요청 없이 삭제·추가·커밋하지 않는다.
기존 `.streamlit/secrets.toml`이 남아 있더라도 읽거나 복사·커밋하지 않는다. 앱은 이 파일을 사용하지 않는다.
