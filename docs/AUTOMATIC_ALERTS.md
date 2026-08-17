# 시설담당자 자동 재난특보 알림 운영

자동 알림 작업자는 5분마다 공식 KMA 특보를 확인하고 시설의
`발효·격상·해제`를 감지한다. Telegram 봇 하나를 서로 다른 두
`chat_id`에 연결해 용도를 분리한다.

- 관리자방: KMA·SOLAPI·Telegram 전달 결과, 장애, 잔액, 운영 상태
- 사용자 비공개 채널: 시설·특보·등급·행동 지침·대시보드 링크

기본 사용자 전달 경로는 `telegram`이다. `sms`로 바꾸면 SOLAPI LMS를
우선 발송하고, 문자 경로가 사용 불가능한 사건만 사용자 Telegram에
한 번 대체 전파한다. 배포 초기값은 반드시 `preview`로 유지한다.

## 1. Telegram 두 곳 준비

1. 기존 관리자방은 그대로 사용한다.
2. 시설담당자용 **비공개 채널**을 새로 만든다.
3. 기존 봇을 사용자 채널의 관리자로 추가하고 `메시지 게시`만
   허용한다.
4. 관리자방과 사용자 채널의 `chat_id`를 각각 확인한다.
5. 사용자 채널은 `가입 요청 후 승인` 초대 링크를 배포한다.

Secret Manager에 다음 값을 둔다.

```text
TELEGRAM_BOT_TOKEN
TELEGRAM_ADMIN_CHAT_ID
TELEGRAM_USER_CHAT_ID
```

`TELEGRAM_ADMIN_CHAT_ID`가 없으면 기존 `TELEGRAM_CHAT_ID`를 관리자방으로
계속 사용한다. 사용자 채널은 잘못된 방으로 전송하지 않도록
`TELEGRAM_USER_CHAT_ID`의 대체값을 두지 않는다.
배포 워크플로는 기본적으로 기존 `TELEGRAM_CHAT_ID` Secret을
관리자방에 연결한다. 새 `TELEGRAM_ADMIN_CHAT_ID` Secret으로 바꾸려면
GitHub Repository variable `TELEGRAM_ADMIN_SECRET_NAME`을
`TELEGRAM_ADMIN_CHAT_ID`로 설정한다.

중앙 관제에서 수동 발송하는 Telegram도 사용자 채널로 보내므로,
Streamlit secrets에도 다음을 설정한다.

```toml
[telegram]
bot_token = "<기존 봇 토큰>"
admin_chat_id = "<관리자방 chat_id>"
user_chat_id = "<사용자 채널 chat_id>"
```

## 2. 배포 변수와 발송 경로

GitHub Repository variables는 다음처럼 시작한다.

```text
ALERT_AUTOMATION_ENABLED=true
ALERT_AUTOMATION_MODE=preview
ALERT_USER_DELIVERY_MODE=telegram
DASHBOARD_BASE_URL=https://keco-safety-map.web.app
```

- `ALERT_USER_DELIVERY_MODE=telegram`: Sheet와 SOLAPI를 호출하지 않는 기본 경로
- `ALERT_USER_DELIVERY_MODE=sms`: 담당자별 LMS 우선, 실패 시 사용자
  Telegram 대체 전파
- `ALERT_AUTOMATION_MODE=preview`: 변화와 메시지만 산출하고 실제 자동
  Telegram·SMS는 전송하지 않음
- `ALERT_AUTOMATION_MODE=live`: 최초 1회는 현재 특보를 기준 상태로만
  저장하고, 그 다음 변화부터 전파
- `ALERT_AUTOMATION_MODE=paused`: Scheduler는 유지하되 감지·전파 중지

전달 경로만 바꾸는 것은 특보 기준 상태를 초기화하지 않으며,
이미 발효 중인 특보를 다시 발송하지 않는다.

공통 Cloud 자원은 Firestore 기본 데이터베이스, Cloud Scheduler API,
Firestore API가 필요하다. `safety-dashboard-runtime` 실행 계정은
`Cloud Datastore User`, `safety-alert-scheduler` 계정은 비공개
`safety-alert-worker`의 `Cloud Run Invoker` 권한을 가져야 한다.

`main` 배포 또는 수동 workflow 실행 후 다음이 구성된다.

- 공개 `safety-dashboard-api`: SOLAPI 웹훅과 토큰 보호 통계 API
- 비공개 `safety-alert-worker`: KMA 감지·Telegram·SMS 발송
- `safety-alert-dispatch`: 5분 간격 Scheduler

중앙 관제 실적 패널을 위해 Streamlit secrets에도 다음을 둔다.

```toml
[alerting]
admin_api_url = "https://<safety-dashboard-api Cloud Run 주소>"
admin_token = "<ALERT_ADMIN_TOKEN과 같은 값>"
```

## 3. 채널 시험

작업자는 비공개 Cloud Run이므로 Cloud Shell에서 ID 토큰으로 호출한다.

```bash
WORKER_URL="$(gcloud run services describe safety-alert-worker \
  --region asia-northeast3 --format='value(status.url)')"

# 관리자방 시험
curl -sS -X POST \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  "$WORKER_URL/internal/v1/test/telegram/admin"

# 사용자 채널 시험
curl -sS -X POST \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  "$WORKER_URL/internal/v1/test/telegram/user"
```

두 요청이 각각 다른 곳에 도착한 후에도 `preview`를 유지해 KMA 정상
조회와 메시지 미리보기를 확인한다. 시험 Telegram과 지정 시험번호
문자는 운영 실적에 포함하지 않는다.

## 4. SMS 우선 경로

SMS를 사용할 때만 [`contact_sheet_template.csv`](contact_sheet_template.csv)를
Google Sheet로 가져오고 시트 이름을 `Recipients`로 지정한다.

| 열 | 필수 | 설명 |
| --- | --- | --- |
| `facility_id` | 예 | `facilities_info.csv`의 시설코드 |
| `recipient_name` | 예 | 명부 관리용 담당자 식별명 |
| `phone` | 예 | 국내 휴대전화 번호 |
| `active` | 예 | `TRUE` 또는 `FALSE` |
| `note` | 아니요 | 인수인계 등 내부 메모 |

- 시설 하나에 담당자가 여러 명이면 행을 추가한다.
- 같은 사람이 여러 시설을 맡으면 같은 번호를 각 시설 행에 반복한다.
- 동일 시설·번호 중복행은 한 건으로 처리한다.
- Sheet를 `safety-dashboard-runtime@<PROJECT_ID>.iam.gserviceaccount.com`에
  **뷰어**로 공유한다. 링크 공개 공유는 사용하지 않는다.
- 전화번호 파일과 Sheet 내보내기 파일은 Git에 커밋하지 않는다.

추가 Secret은 다음과 같다.

```text
SOLAPI_API_KEY
SOLAPI_API_SECRET
SOLAPI_SENDER_NUMBER
SOLAPI_WEBHOOK_SECRET
CONTACT_SHEET_ID
ALERT_HMAC_SECRET
ALERT_TEST_PHONE
ALERT_ADMIN_TOKEN
```

SOLAPI에서 발신번호를 등록하고 `SINGLE-REPORT` 웹훅을
`https://<PUBLIC_API_HOST>/api/v1/webhooks/solapi`에 연결한다.
`SOLAPI_WEBHOOK_SECRET`은 SOLAPI 웹훅 화면과 Secret Manager에 같은
원문을 넣는다. `ALERT_HMAC_SECRET`과 `ALERT_ADMIN_TOKEN`은 충분히
긴 난수로 만들고 원문을 GitHub 변수·로그·문서에 남기지 않는다.

코드 내부 상한은 SOLAPI 시도 기준 일 100건(경고 80), 월 500건(경고
400)이다. SOLAPI 외부 일 한도 500건보다 낮게 두어 프로그램 오류로
인한 과다 발송을 막는다. 사용 가능 금액은 SMS 모드에서만 최대
1시간에 한 번 확인하며 1만원 미만 주의, 3천원 미만 긴급, 충전 후
회복을 관리자방에 알린다.

다음 경우 사용자 Telegram 대체 전파를 사건 당 한 번만 예약한다.

- 연락처 Sheet 오류, 미등록 시설, 필수 설정 오류
- 일·월 코드 상한 초과
- SOLAPI 접수 실패·잔액 부족·응답 확인 불가
- SOLAPI 웹훅의 통신사 최종 수신 실패

SMS 성공 접수 시에는 사용자 채널에 같은 사건을 중복 게시하지
않는다. SOLAPI 웹훅은 기존
`/api/v1/webhooks/solapi` 경로와 `X-Solapi-Secret` SHA-1 검증 방식을
그대로 유지한다.

## 5. 재시도·중복 방지·실적

- Telegram 작업은 Firestore outbox에 `채널·배치·용도`별 고유 ID로
  저장한다.
- Scheduler 재시도와 동일 SOLAPI 웹훅은 같은 사건을 중복 게시하지
  않는다.
- 사용자 Telegram 실패 시 5분 간격으로 30분까지 재시도한다.
- 사용자 Telegram이 실패해도 SMS로 역전환하지 않는다.
- 매일 09:00에 전날 자동 관제·특보 변화·SMS·Telegram 실적과
  현재 운영 상태를 관리자방으로 보낸다.
- 매일 18:00에는 실적을 제외한 현재 웹·API·KMA·사용자 Telegram·배포
  상태를 보낸다. 전부 정상이면 무음, 하나라도 이상이면 일반 알림이다.
- KMA 실패는 `인증·설정`, `사용량 제한`, `KMA 서버`, `KMA API 통신경로`,
  `Cloud Run 외부통신`, `응답 형식`, `원인 미확정`으로 추정 분류한다.
  분류는 단정이 아니며 이전 특보 상태는 계속 보존한다.
- 무변화 정상 조회는 Telegram으로 보내지 않는다.
- `preview`, 지정 시험번호, 시험 Telegram, 수동 Telegram은 운영 실적에서
  제외한다.
- Firestore와 CSV에는 전화번호 대신 HMAC 수신자 코드만 저장한다.
- SOLAPI `수신 완료`는 통신사 결과이며 담당자의 실제 열람을 의미하지
  않는다.

Streamlit `자동 알림 실적`에서 현재 전달 모드, 일·월 SMS 사용량,
잔액·포인트, SMS 접수·수신·실패·대기, 사용자 Telegram 주경로·대체·실패
수를 확인한다.

즉시 운영 보고 시험은 Cloud Scheduler 실행 계정으로 다음 보호 경로를
호출한다. 시험 보고는 실적에 포함되지 않는다.

```text
POST /internal/v1/test/heartbeat
```

## 6. 운영 전환 순서

1. 관리자방과 사용자 채널 시험을 각각 성공시킨다.
2. `ALERT_USER_DELIVERY_MODE=telegram`, `ALERT_AUTOMATION_MODE=preview`에서
   KMA 정상 조회와 미리보기를 확인한다.
3. `ALERT_AUTOMATION_MODE=live`로 바꾸고 workflow를 다시 실행한다.
4. 첫 live 실행이 `BASELINED`이고 실제 알림은 나가지 않았는지 확인한다.
5. 이후 공식 특보 변화부터 자동 사용자 Telegram 전파를 운영한다.
6. SMS가 필요할 때만 Sheet·SOLAPI 잔액·웹훅을 확인한 뒤
   `ALERT_USER_DELIVERY_MODE=sms`로 재배포한다.

위험도 기본 정책 버전이 바뀌면 첫 실행은 새 기준 상태로만 등록한다.
정책 변경이 대량 `격상` 알림으로 오인되는 것을 막기 위한 보호장치다.
