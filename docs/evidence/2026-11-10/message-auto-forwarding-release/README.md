# 공식 문자 자동전파 운영 반영 — 2026-11-10 KST

사용자는 운영 배포·배포 후 점검·전체 시작까지 명시적으로 승인했다. 토큰 중단 후 계속 진행도 요청했다.
[PR #4](https://github.com/parkgogon/sfety_map/pull/4)는 병합됐고, 실제 앱 소스는 `363ac2edf5139b87ee0c6bcbe6bf5c134d1807d2`다. 후속 점검 도구/증빙 commit은 `[skip ci]`로 앱 배포와 분리한다.

## 배포와 설정

[배포 42716325390](https://github.com/parkgogon/sfety_map/actions/runs/42716325390)의 테스트/API·문자·기상 worker/웹/외부 감시가 모두 성공했다. Python 715개·React 279개/43파일·CSV 195개·컴파일/빌드/확정 설정 검사 통과, 자동 검사 외부 HTTP/TCP 0.
GitHub 변수 API 권한을 확대하지 않고 승인된 비밀값 없는 설정을 `.github/message-delivery-release.json`과 배포 기본값으로 반영했다. 명시적 저장소 변수는 우선하며 `MESSAGE_DELIVERY_ENABLED=false` 긴급 중단 배포도 허용한다. 앱 자체의 기본값은 계속 비활성이다.

- 기존 봇/직원방/관리자 수신처 숫자 버전 **1/2/1**, 관리자 Secret `TELEGRAM_CHAT_ID`. API와 문자 worker에 같은 버전을 연결했다. 실제 키 값은 옮기거나 내보내지 않았다.
- 당일 순회 진행 예약 5분/분석·준비·전파 예약 1분. 실제 전체 순회 간격은 페이지/시도 수와 예산에 따라 늘어난다. 피드 공통 450회/최근 24시간, AI 20건/한국 날짜·하루 $1/월 $20.
- 기존 수집 시작 시각은 **`2026-11-08T13:45:00.961104+00:00`** 그대로다. 원문·검토·작업·한도와 KMA 기준 상태를 초기화하지 않았다.
- 공개 웹의 `/assets/index-BHT-1Qlo.js`에 실제 앱 SHA가 있음을 확인했다. `web-version-check.json` 참조.

## 배포 후 발견한 문제와 보완

1. [첫 상태 검수](https://github.com/parkgogon/sfety_map/actions/runs/42717211956): 새 API/worker·고정 방·예약은 맞고 자동전파는 ready/미시작이었다. 점검 도구의 시작 시각 비교가 초 단위로 반올림돼 소수점 이하가 있는 원래 저장값을 다르게 판정했다. 저장값은 바꾸지 않고 기존 증빙과 정확히 같은 시각을 비교하도록 수정했다. health도 실제 `status=ok/reason=ready` 계약에 맞췄다. 관련 격리 검사 10개 통과.
2. [재개 후 상태 검수](https://github.com/parkgogon/sfety_map/actions/runs/42719201079): 시작 시각 불변과 새 정규 작업자 heartbeat는 통과했으나 08:15 KST 수집 ERROR/최근 당일 순회 없음/잔여 파티션 4였다. 전파 제어 요청 0, 따라서 전체 시작을 실행하지 않았다.
3. [현재 코드의 읽기 전용 재현](https://github.com/parkgogon/sfety_map/actions/runs/42719821482): 같은 운영 이미지/계정/키·gen2 임시 환경에서 피드 2회 성공, 관측 3회/메모리 기록 2개/예외 0. 운영 쓰기·AI·발송 0. 당일 bucket이 운영 상태와 같아 current lane을 다시 실행하지 않았고, background lane의 같은 당일/전일 조회를 확인했다. 기존 current 오류를 보존해 replay 결과는 error이며 전체 수집 회복 증거로 쓰지 않는다.
4. [문자 실행 환경 1회 갱신](https://github.com/parkgogon/sfety_map/actions/runs/42720290101): `MESSAGE_RUNTIME_REFRESH` 표식 하나만 추가해 기존 `safety-message-worker`를 `00004-lnl`→`00005-5bc`로 갱신했다. 이미지·원래 설정·키 버전·예약 주소 불변, API/KMA revision과 트래픽 불변을 전후 비교했다. 수동 job 실행/시험 발송 0. 저수준 오류 원인은 미확정이며 회복 여부는 다음 정규 수집으로 판단한다.

위 실패 결과와 metadata는 `status-first/`, `status-second/`, `current-collection-replay.json`, `runtime-refresh/`에 보존했다. 시험/훈련 메시지를 운영방에 보내거나 기상 dispatch를 호출하지 않았다.

## 최종 상태

[08:31 KST 비활성 상태 검수](https://github.com/parkgogon/sfety_map/actions/runs/42720980571) 통과. 08:30 정규 수집은 LIVE/잔여 0이며 당일 순회·과거 보충 완료 시각을 저장했다. 피드 103/450, AI 건수/비용 원장 0이었다. 기존 시작 시각·고정 버전·원래 설정을 유지했고 1440/390px의 3탭에서 페이지 오류/예상 밖 요청/전파 제어 요청 0이었다.
갱신 후 관측한 회복이며 정확한 저수준 원인·장기 안정성은 확정하지 않는다. 실패/재시도도 순회 예산에 포함하므로 이 시점의 적응형 간격 표시는 1800초였다. 다음 순회는 scan 시작/완료 경계와 마지막 완료 뒤 최소 300초 조건에 따라 이어진다.

[전체 시작 42721260303](https://github.com/parkgogon/sfety_map/actions/runs/42721260303): **2026-11-10 08:35:13.641318 KST**에 제어 POST 1회로 active를 저장했다. generation `8b94a48268ff4b4481328d618b673272`다. 이전 preview/시작 전 원문을 일괄 전파하지 않으며 그 시각 이후 새 공식 원문과 같은 generation의 새 준비만 대상으로 한다.

[읽기 전용 시작 후 검수 42721724026](https://github.com/parkgogon/sfety_map/actions/runs/42721724026): **08:36:02 정규 worker가 같은 source revision/generation으로 active**를 저장했다. worker 지연 없음, 시작 시각 불변/추가 제어 POST 0. PC 1440/390px에서 자동전파 중/세 탭을 확인했고 페이지 오류·예상 밖 요청 0이다. 수집은 LIVE/잔여 0을 유지했다.

08:36 상태의 정규 처리 분석 건수는 1/20, 비용 원장은 모델 응답 2회·요금표 기준 정산 **$0.0061632**, 미정산 0이다. 수동 유료 평가가 아니라 정규 처리 사용량이며 실제 계정 청구는 Usage와 대조한다. 검사 코드가 보낸 시험 메시지는 0건이고, 이를 운영 시스템의 향후 실제 업무 전파 건수로 해석하지 않는다. 실제 Telegram receipt·직원 열람/현장 확인을 시작 상태나 합성 시험으로 증명하지 않는다.

기존 점검용 이미지 태그 두 개의 삭제 권한 제한은 [이전 런타임 검수](../message-delivery-runtime/README.md)에 기록돼 있다. 이번 상태 검수의 임시 서버는 각 workflow의 정리 단계에서 삭제한다. 실제 직원 수신/접속·제공 지연·장기 장애/판단 품질 관측은 별도이며 가짜 제공자 검사나 시작 상태로 대체하지 않는다.
