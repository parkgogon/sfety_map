# 재난문자 간소화 제한 운영 배포 검수

**제한 운영 배포·예약 분석/화면 검수 완료. 공식 첫 수집은 partial이며 전체 자료 확보 완료는 아니다.**

- 사용자 승인: 1·2단계를 먼저 제한 운영하고 실제 불편으로 다음 개선을 정한다.
- [PR #2](https://github.com/parkgogon/sfety_map/pull/2) 병합 `8f46f9a`, 예약 상태 처리 보완 후 앱 소스 `a63fec51a1ec8a17bd2c2e228a2a0cc12c1be707`.
- [최종 배포 42485619427](https://github.com/parkgogon/sfety_map/actions/runs/42485619427): API·문자 worker/예약·KMA worker/예약·Hosting·외부 감시 모두 성공.
- API `safety-dashboard-api-00089-795`, 문자 worker `safety-message-worker-00001-xzd`, KMA worker `safety-alert-worker-00077-8dp`, 각 앱 소스/100%.
  Hosting `83a6d1990ef8b73d`, 2026-11-08 13:40:27 UTC 배포. `pilot-metadata.json`/`postdeployment-baseline.json`.

## 검증한 동작과 범위

- 최종 CI: Python **528개**, React **268개**·41파일, compileall·시설 CSV 195개·웹 빌드/활성 설정 통과.
  자동 검사의 실제 외부 HTTP/TCP 시도 0. `test-summary.json`.
- [실제 예약 분석/브라우저 42486131095](https://github.com/parkgogon/sfety_map/actions/runs/42486131095) 통과.
  창작 기록 `manual-d12aca68e2b74015983de42ff6c6afc1`, 출처 `운영 배포 검수 · 창작 예문`만 검수 대기열에 넣었다.
  다음 **정규 Scheduler 분석 1회**가 Firestore 저장까지 마쳤다. 저장된 모델 응답 4회, 선정 7개소.
  브라우저 유료 분석 요청은 0. 실제 재난/업무 성과로 세지 않는다.
- 새 한 화면 검토/확정·초안 복사·새로고침 저장 복구·재열기/재확정과 실제 Kakao SDK/타일 통과.
  1440/390px 가로 넘침·page error·예상 밖 요청 0, 타일 35응답/지도 이미지 9개.
  `verification.json`, `desktop.jpg`, `mobile.jpg`를 직접 시각 검토했다. 실기기 터치 검수는 아니다.
- API/worker의 Firestore 모드·15분·4페이지·최근 24시간 450회·AI 한국 날짜 하루 20건과 세 Secret 버전 1을 확인했다.
  문자 worker는 IAM 비공개, 두 문자 예약과 기존 5분 KMA 예약은 ENABLED/OIDC다.
  문자 worker에는 관리자/KMA/Telegram/SMS 키를 연결하지 않았다.

## 공식 수집의 실제 관측과 남은 문제

- **2026-11-08 22:45:00 KST** 첫 정규 수집 실행. 오늘·전일 조회 2회가 공통 Firestore 요청 집계에 기록됐다.
  진행 잔여 0/범위 누락 false지만 **건너뜀 2건**이라 `partial`, `last_success_at=null`이다.
  최초 시작 시각도 이때 저장했다. 이후 발행 문자부터 쌓이므로 최종 조회 페이지에 공식 기록은 0건이었다.
- 최초 [상태 검수 42486436414](https://github.com/parkgogon/sfety_map/actions/runs/42486436414)는
  검수 도구가 LIVE만 허용해 실패했다. `first-collection-verification.json`에 이 실패와 partial 상태를 보존했다.
- 검수 도구만 `2ff6714 [skip ci]`로 보완하고 관련 10개 테스트를 통과했다. 운영 앱을 재배포하거나 수집 상태/기록을 바꾸지 않았다.
  partial은 실행을 관측한 결과로 남기고, 전체 완료와 구분하는 `collection_complete=false`를 결과에 포함했다.
  [최종 읽기 관측 42486861802](https://github.com/parkgogon/sfety_map/actions/runs/42486861802)는 통과했으며
  `final-status-verification.json`/`final-status-pilot-metadata.json`에 전체 결과를 보존했다.
  이 통과는 전체 수집/정확도 통과가 아니다. **건너뜀 2건의 원인은 아직 분류하지 못했으며 우선 진단 대상이다.**
- 정규 실행 지연·24시간 분석 대기·한도/저장소/제공자 실패·450회 차단 자체는 가짜 제공자/저장소 검증과 구분한다.
  실운영의 450회 강제 소진/장애 주입·장기 지연/완전성/효과 측정은 하지 않았다.

## 기상특보 상태 대조

`predeployment-health.json`: 22:30 KST 배포 전부터 KMA error였다. worker 예약 실행은 이어졌다.
22:40 KST에는 정규 실행에서 LIVE/연속 오류 0/NO_CHANGE로 회복했으나 **22:45·22:50 KST KMA_ROUTE 오류가 재발**했다.
`postdeployment-health-first.json`, `postdeployment-health-latest.json`과 최종 보호된 상태에서 확인했다.
따라서 KMA 문제가 해결됐다고 표시하지 않는다. 새 문자 수집 문제와 별도로 기존 간헐 연결 오류를 추적한다.
KMA 정책/기준 상태를 초기화하거나 dispatch를 수동 실행하지 않았고, 마지막 정상 자료/오류 처리 정책은 유지했다.

## 사전 검수·중단 이력과 경계

- `baseline.json`: 배포 전 API/KMA worker/Hosting 복구 지점.
  기존 baseline 도구의 서비스 이미지 projection은 빈 배열이라 이미지 확인 근거로 사용하지 않는다. 이미지 확인은 `pilot-metadata.json`을 따른다.
- 최초 배포 `42485409689`는 예약 작업의 ENABLED/PAUSED 상태 처리 오류를 발견해 **서비스 변경 전 CI 단계에서 취소**했다.
  이미 ENABLED인 작업을 resume/PAUSED인 작업을 pause하지 않게 고치고 가짜 CLI 상태 회귀 검사를 추가했다.
- API 사전 검수 `42485152223`: 첫 외부 읽기 실패 1회 후 한 차례 재실행에서 5회로 통과.
  `feed-preflight-attempt1.json`/`feed-preflight-attempt2.json`. 당일/전일 범위·지역·페이지/ID 겹침·첫 페이지를 대조했다.
  두 시도 시작 합계 6회. 원문/공식 ID/키를 내보내거나 DB/모델/발송을 호출하지 않았다.
- 모든 임시 Cloud Run 검수 서비스는 정리 단계 성공으로 삭제를 확인했다.
  비밀번호/키는 서버의 Secret 참조로 사용하고 작업공간·Git·artifact로 가져오지 않았다.
- 실제 Telegram/SMS 시험 발송·수동 dispatch·KMA 기준 초기화는 0이다.
  운영 시스템의 원래 정규 감시 업무 알림과 구분한다.

다음은 건너뜀 2건과 KMA_ROUTE 재발의 원인을 분리 진단하고 실제 검토 피드백을 모으는 일이다.
후속 문자 제안/변경 비교 UI는 그 다음 개선으로 두며, 자동 현장 연락·회신은 이번 범위에 포함하지 않는다.
