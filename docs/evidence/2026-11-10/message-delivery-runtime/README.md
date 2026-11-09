# 자동전파 연결·저장·시작/중지 검수 — 2026-11-10 KST

[최종 실행](https://github.com/parkgogon/sfety_map/actions/runs/42713082207), 후보 `0e49d501f3dd3b1cb476a369184b713ac37636a1`.
운영 앱 `5f58be1`·세 서비스의 트래픽·세 예약·운영 제어는 그대로다. main 반영/운영 배포/자동전파 시작/실제 시험 발송 0.

## 확인한 연결

기존 API와 KMA worker의 Telegram 참조와 런타임 계정이 같음을 확인했다. 동일한 런타임 계정의 기존 Secret accessor 권한으로 현재 참조를 읽고 응답의 숫자 버전을 확인했다. 값은 메모리에서만 사용했으며 키 재발급·등록·IAM 변경을 하지 않았다.

| 용도 | 기존 Secret | 확인한 숫자 버전 |
| --- | --- | --- |
| 봇 | TELEGRAM_BOT_TOKEN | 1 |
| 직원 단체방 | TELEGRAM_USER_CHAT_ID | **2** |
| 관리자 수신처 | TELEGRAM_CHAT_ID | 1 |

Telegram에는 getMe/getChat/getChatMember **읽기 4회**만 요청했다. 직원 수신처는 실제 단체방이고 봇의 가입/게시 권한이 확인됐다. 관리자 수신처는 기존 개인 대화이며 직원방과 다르다.
관리자 개인 대화의 getChat 성공은 상대가 봇을 차단하지 않았음이나 실제 수신을 증명하지 않는다. 실제 발송 receipt·직원 열람/현장 확인은 검수하지 않았다. 방 ID·이름·봇 토큰은 보고서에 없다.
latest의 현재 해석을 확인한 것이며 과거에 시작된 모든 인스턴스의 메모리 값을 조회한 것은 아니다. 다음 배포에는 위 숫자를 API/문자 worker에 함께 고정하고 다시 확인한다.

공개 지도는 로그인 없는 HTTP 200/HTML을 확인했고 문안의 링크가 공개 지도 루트임을 재검증했다. 실제 직원 기기의 SDK 표시/접속 검수와 구분한다.

## 같은 계정에서 실제 Firestore와 현재 코드 재현

운영 의존성 파일이 동일한 기존 worker 이미지에 후보 Python 코드/시설 CSV/점검 스크립트만 복사한 임시 이미지와 IAM 비공개 gen2 서비스다. OpenAI/Kakao/공식 피드/KMA 요청과 실제 발송 제공자는 연결하지 않았다.

- 운영 pipeline의 전파 제어·준비 설정 **읽기 4회**. 전파 제어는 아직 없으며 전후 값이 같았다. 운영 저장·제어 변경 0.
- 실제 Firestore의 `message_delivery_preflight/<실행 ID>/disaster_message_pipeline` 및 `disaster_message_reviews`에 현재 저장 어댑터를 연결했다. 다른 컬렉션 접근은 wrapper에서 거부한다.
- 이전 예문 결과를 복제하고 시각을 옮긴 **격리된 합성 fixture**로 준비→전파 outbox→가짜 성공 receipt→이력 조회를 재현했다. 격리 공간에서만 공식 처리 분기를 사용했으며 운영 공식 기록/실적으로 등록하지 않았다. 새 AI 품질 실험이 아니다.
- 시작 전 preview 제외, 중지 중 요청 없음, 재시작 시 이전 대기 제외, 오래된 generation의 제어 충돌, 새 revision의 재시작 필요, 재실행 뒤 가짜 요청 1회 유지, 사람 검토 이력 불변을 통과했다.
- root와 하위 문서 **33개 삭제**, 남은 문서 없음. 임시 서비스 삭제 성공.

같은 계정/어댑터의 실제 트랜잭션·단일 필드 조회·이력 동작을 확인한 결과다. 운영 컬렉션에 실제 전파를 기록하거나 새 운영 배포를 시작/중지한 검사는 아니다. 배포 후 꺼진 상태에서의 API/worker 연결 검수는 남는다.

## 결과 보존과 제한

[1차](https://github.com/parkgogon/sfety_map/actions/runs/42712462654)는 관리자 개인 대화도 단체방이어야 한다는 과한 점검 조건으로 `group_chat_required`에서 중단했다. 직원 단체방 조건은 유지하고 기존 관리자 개인 수신처를 별도로 검사하도록 고쳤다. 실패 보고서도 `attempt-1/`에 보존했다.
[최종 CI](https://github.com/parkgogon/sfety_map/actions/runs/42713094363): Python **706개**·React **279개/43파일**·빌드/CSV 195개/컴파일/배포 변수 검사 통과. 자동 검사 외부 HTTP/TCP 0, 운영 배포 job 모두 제외. 실제 실연결 검사와 가짜 제공자 자동 검사를 구분한다.

임시 이미지 두 태그 `delivery-preflight:42712462654`, `delivery-preflight:42713082207`는 점검 계정의 `artifactregistry.tags.delete` 권한이 없어 저장소에 남아 있다. 실행 중인 임시 서비스나 시험 데이터는 없다. 이미지 정리를 위해 권한을 확대하지 않았다. `attempt-1/cleanup.json`, `attempt-2/image-cleanup.json` 참조. 해당 저장소의 삭제 권한이 있는 소유자가 두 태그만 정리할 수 있다.

## 검토 가능한 전환 설정

`proposed-repository-variables.json`과 외부 호출 없이 생성기로 검증한 `proposed-generated-config.json`은 **미적용 제안**이다. 직원방은 확인한 버전 2이며 임의로 1/latest를 쓰지 않는다. 기존 수집 시작 시각/저장 기록/한도 집계/기상 기준은 보존한다.
20건/한국 날짜·하루 $1/월 $20·피드 최근 24시간 450회는 초기 제한값이며 처리량/정확도/지연 보장이 아니다.

다음은 [운영 반영 절차](../../../MESSAGE_DELIVERY_ROLLOUT.md)에 따라 사용자 요청을 받은 뒤 설정/PR을 반영하고, 전파가 꺼진 상태의 새 배포를 검수하는 것이다. 새 revision의 명시적 시작 전에는 전파하지 않는다. 수집 오류의 운영 회복·정규 순회/지연·실제 직원 수신은 배포 후 관측한다.
