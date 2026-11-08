# 운영 오류 수정·실제 검수 — 2026-11-09 KST

**수집 오판정 수정 배포와 정규 수집 정상 완료를 확인했고, KMA는 최신 배포에서 3회 연속 정규 조회가 회복됐다.**
정확한 저수준 연결 원인은 미확정이며 장기 재발 방지를 입증한 결과로 확대하지 않는다.

- [PR #3](https://github.com/parkgogon/sfety_map/pull/3), 최종 앱 소스 `5f58be1d12a8ac57c0ec365e4eeb86b392fc348c`.
- [최종 배포 42520955495](https://github.com/parkgogon/sfety_map/actions/runs/42520955495): API·문자 worker/예약·KMA worker/예약·Hosting·외부 감시 모두 성공.
- 최종 CI Python **539개**·React **268개**·컴파일/시설 CSV 195개/웹 빌드 통과. 자동 검사 실제 외부 HTTP/TCP 0.
  `test-summary.json`. 첫 PR CI는 바뀐 제목을 기대하지 못한 기존 UI 검사 1건이 실패했고 기대 문구를 맞춘 후 전체 통과했다.
- 최초 `1169791` 배포는 API/worker/웹 성공 후 외부 감시 작업 중 날짜 검증 경계 보완 push로 취소됐고, 최종 `5f58be1`은 전 단계 성공했다.

## 문자 오판정 원인과 수정

실제 11월 8일/7일 겹침 조회에서 각각 수신지역을 광역지역으로 인식할 수 없는 항목 1회가 있었다.
둘 다 운영 시작 전 발행이고 정상 파싱된 자료였다. 이 증빙은 원문/공식 ID를 내보내지 않아 유일 항목 수를 주장하지 않는다.
미등록 과거 항목까지 현재 범위의 실패로 세어 partial/last_success_at=null이 반복되는 버그였다.

- 발행 시각이 정상이고 요청 날짜 범위에 맞는 미등록 시작 전 항목은 수신지역/본문 검사 전에 제외한다.
- 기존 저장 ID의 정정·시작 이후 수신지역 불명·시각/필드 해석 실패·요청 날짜 밖 응답은 계속 검증한다.
- API가 잘못된 과거 날짜를 돌려줄 경우에도 시범 시작 전이라고 숨기지 않도록 날짜 검증을 먼저 유지했다.
- 사유별 건너뜀과 시작 전 제외를 관측 횟수로 분리하며 추가 페이지 대기/항목 확인 필요를 구분한다.

[실제 상태 검수 42521866421](https://github.com/parkgogon/sfety_map/actions/runs/42521866421):
**05:45 KST 정규 수집에서 LIVE/건너뜀 0/남은 진행 0/정상 완료 시각 저장**을 확인했다.
시작 전 제외는 41회 관측(겹침 포함), 공통 조회 집계 90/450이었다.
시작 시각은 11월 8일 22:45 KST 그대로이며 키/원문/저장 기록/대기열/한도/기상 기준을 초기화하지 않았다.
조회 페이지의 공식 기록은 아직 0건이고, 새로운 실제 문자의 유료 분석을 이 검수에서 수행한 것은 아니다.
`post-fix-verification.json`/`post-fix-pilot-metadata.json`.

## KMA 회복 관측과 한계

- 기존 worker는 80회 이상 연속 실패/마지막 성공 11월 8일 22:40 KST였다.
- 같은 이미지/runtime/키의 임시 서버 네 실행에서 KMA 직접 HTTP 각 3회가 200/정상 형식이었다.
  마지막은 실제 worker와 같은 전체 snapshot 경로도 LIVE/시설 195개소로 통과했다. 키/파서/응답 지연만의 문제로 보기는 어려웠다.
- 기본 환경의 실행마다 SafetyData 결과도 달랐고, gen2 임시 서버에서는 SafetyData TCP timeout/KMA 정상으로 관측됐다.
  특정 고유 출구/제공자 차단은 규명하지 못했다. 기존 환경은 execution annotation 미지정이라 gen1이라고 단정하지 않는다.
- KMA worker만 gen2로 명시했다. 첫 gen2 리비전의 05:35 실행도 실패했으므로 gen2 자체가 원인/해결이라고 단정하지 않는다.
  최신 `5f58be1`/`safety-alert-worker-00079-twg`에서 회복했다.
- **05:45:00·05:50:01·05:55:01 KST 정규 실행 3회 연속 LIVE/health 200**을 확인했다.
  `kma-three-regular-successes.json`은 서로 다른 5분 실행 세 개를 담고, `kma-regular-observations.jsonl`은 실패부터 회복까지의 공개 읽기 관측이다.
  이 관측으로 장기 안정성이나 제공자 측 원인을 확정하지 않는다.
- ERROR여도 worker 실행만 있으면 ready/200이던 health를 KMA 실패/미상/STALE에 kma_unavailable/503으로 수정했다.
  실제 배포 후 ERROR 상태 503과 회복 후 200을 모두 관측했다. 실패를 정상으로 감추지 않는다.
- API/문자 worker의 실행 환경과 기존 기상 정책/알림 기준을 유지했다. KMA도 최소 0·최대 1/기존 CPU·512Mi이고 NAT/상주 자원을 추가하지 않았다.
- 회복되지 않을 경우의 새 private worker 전환/읽기 전용 사전 점검안은 로컬 `fix/kma-worker-replacement`/`b0876d3`에만 보존했다.
  이 초안은 543개 테스트를 통과했으나 원격 push·배포·예약 전환을 하지 않았다. 현재 회복이 확인돼 보류했다.
  실제 운영은 기존 `safety-alert-worker`다. 초안을 현재 앱 코드로 오인하지 않는다.

## 실제 화면/기록 회귀 검수

[기존 창작 기록 재검수 42522145075](https://github.com/parkgogon/sfety_map/actions/runs/42522145075) 통과.
`manual-d12aca68e2b74015983de42ff6c6afc1`의 저장된 분석 4응답/선정 7개소를 재사용했다.
새 AI 분석 요청 0, 현재 한국 날짜 분석 시작 0/20. 확정·복사·새로고침 복구·재열기/재확정과 실제 SDK/지도 타일을 확인했다.
PC/390px 가로 넘침·화면 오류/예상 밖 요청 0, 타일 22응답/표시 9개.
`browser-verification.json`, `browser-pilot-metadata.json`, `browser-desktop.jpg`, `browser-mobile.jpg`를 직접 검토했다.
이 기록은 창작 예문이며 실제 재난/현장/업무 성과가 아니다. 실기기 터치/핀치 검수도 아니다.

현재 리비전/100%: API `safety-dashboard-api-00091-wjr`, 문자 `safety-message-worker-00003-sj2`, KMA `safety-alert-worker-00079-twg`(gen2).
이미지/세 Secret 버전 1/기존 예약 3개는 browser-pilot-metadata.json, Hosting 버전은 post-fix-baseline.json에 있다.

## 진단 경계와 보존 파일

- 기본1 run42518943134: 공식 3회 연결 실패/KMA 3회 정상.
- 기본 단계 run42519155230: 공식 3회 정상/모든 행 파싱 정상/과거 수신지역 문제 확인, KMA 3회 정상.
- gen2 run42519579492: 공식 3회 TCP timeout/KMA 3회 정상.
- 전체 snapshot run42521167406 (producer `9fb10ee`): 공식 3회, KMA 직접 3회+관제 snapshot 1회.
  `snapshot-path-diagnostic.json`/`execution-after-gen2-first.json`. 진단 소스는 해당 고정 commit의 scripts/diagnose_sources_runtime.py다.
- 총 공식 요청 12회는 실패도 포함해 앱 공통 최근 24시간 450회에 HTTP 전에 예약했다. KMA 직접 12회+snapshot 1회.
  진단/재검수의 새 AI·실제 시험 발송·소스 기록 쓰기·기상 기준 초기화·수동 dispatch는 0이다.
  창작 검토 기록의 재확정과 조회 집계 쓰기는 별도이며 실제 전파/회신이 아니다.
- 네 진단과 두 비공개 UI 검수의 임시 서비스는 cleanup 단계 성공으로 삭제를 확인했다.
  키/비밀번호/문자 원문/공식 ID를 작업공간·Git·artifact에 가져오지 않았다.
- baseline.json은 수정 전 복구 지점이다. baseline 도구의 image projection 빈 배열은 이미지 확인 근거로 쓰지 않고 pilot-metadata를 따른다.

다음은 실제 검토의 수정/보류 이유를 모아 후속 문자 제안·변경 비교를 구체화하는 일이다.
KMA 재발 시 현재 revision과 원래 예외/마지막 정상 실행을 먼저 대조하고, 회복 관측을 영구 해결로 확대하지 않는다.
