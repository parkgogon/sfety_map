# 시설담당자 자동 재난특보 알림 운영

자동 알림은 5분마다 공식 KMA 특보를 확인하고 시설의 `발효·격상·해제`를
감지한다. 담당자에게는 SOLAPI 문자, 관리자방에는 Telegram 요약을 보낸다.
초기 배포값은 반드시 `preview`이며 현재 발효 중인 특보를 대량 발송하지 않는다.

## 1. 연락처 Google Sheet

[`contact_sheet_template.csv`](contact_sheet_template.csv)를 Google Sheet로 가져오고
시트 이름을 `Recipients`로 지정한다.

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

## 2. Google Cloud와 SOLAPI 준비

1. SOLAPI에서 계정 인증과 기관 소유 발신번호 등록을 완료한다.
2. SOLAPI `SINGLE-REPORT` 웹훅을 아래 주소로 등록한다.
   `https://<PUBLIC_API_HOST>/api/v1/webhooks/solapi`
3. Google Cloud에서 Firestore 기본 데이터베이스를 Native 모드, 서울
   `asia-northeast3`에 만든다. 이미 데이터베이스가 있으면 기존 위치를 유지한다.
4. `Cloud Scheduler API`, `Google Sheets API`, `Firestore API`를 활성화한다.
5. 실행 계정에 `Cloud Datastore User` 역할을 주고 아래 Secret에만
   `Secret Manager Secret Accessor` 권한을 준다.
6. `safety-alert-scheduler` 서비스 계정을 만들고 배포 후
   `safety-alert-worker`의 `Cloud Run Invoker` 역할을 부여한다.

Secret Manager에는 다음 값을 각각 버전 1로 만든다.

```text
SOLAPI_API_KEY
SOLAPI_API_SECRET
SOLAPI_SENDER_NUMBER
SOLAPI_WEBHOOK_SECRET
CONTACT_SHEET_ID
ALERT_HMAC_SECRET
ALERT_TEST_PHONE
TELEGRAM_BOT_TOKEN
TELEGRAM_CHAT_ID
ALERT_ADMIN_TOKEN
```

- `ALERT_HMAC_SECRET`과 `ALERT_ADMIN_TOKEN`은 충분히 긴 난수로 만든다.
- `SOLAPI_WEBHOOK_SECRET`은 SOLAPI 웹훅 등록 화면과 같은 원문을 저장한다.
- `CONTACT_SHEET_ID`는 Sheet URL의 `/d/`와 `/edit` 사이 값이다.
- `ALERT_TEST_PHONE`은 운영 전 실제 수신을 확인할 내부 시험번호다.
- Secret 원문을 GitHub 변수, 로그, 문서에 붙여 넣지 않는다.

GitHub 배포 계정에는 기존 역할 외에 Cloud Scheduler 작업을 만들고 갱신할
권한이 필요하다. Repository variables는 다음과 같이 시작한다.

```text
ALERT_AUTOMATION_ENABLED=true
ALERT_AUTOMATION_MODE=preview
DASHBOARD_BASE_URL=https://keco-safety-map.web.app
```

`main` 배포 또는 수동 workflow 실행 후 다음 리소스가 만들어진다.

- 공개 `safety-dashboard-api`: SOLAPI 웹훅과 토큰 보호 통계 API
- 비공개 `safety-alert-worker`: Scheduler만 호출하는 실제 감지·발송 작업자
- `safety-alert-dispatch`: 5분 간격 Scheduler 작업

## 3. 미리보기와 운영 전환

1. `preview`로 최소 두 차례 실행해 KMA, 연락처, Firestore 상태를 확인한다.
2. 비공개 작업자의 `POST /internal/v1/test`를 인증된 `gcloud` 요청으로 한 번
   호출해 지정 시험번호와 Telegram 시험 결과를 확인한다.
3. SOLAPI 웹훅에서 시험 문자의 최종 상태가 들어오는지 확인한다.
4. Streamlit secrets에 아래 값을 추가한다.

```toml
[alerting]
admin_api_url = "https://<safety-dashboard-api Cloud Run 주소>"
admin_token = "<ALERT_ADMIN_TOKEN과 같은 값>"
```

5. 중앙 관제의 `자동 알림 실적`에서 최근 실행, 연락처 수, 미리보기 건수를
   확인한다.
6. GitHub variable `ALERT_AUTOMATION_MODE`를 `live`로 바꾸고 workflow를 다시
   실행한다. 첫 live 실행은 현재 특보를 기준 상태로만 등록하고 문자로 보내지
   않는다. 이후 변화부터 자동 발송한다.

기본 위험도 정책 버전이 바뀌어도 첫 실행은 새 기준 상태로만 등록한다.
정책 변경 자체가 대량 `격상` 문자로 잘못 전파되는 것을 막기 위한 보호장치다.

긴급 중지는 `ALERT_AUTOMATION_MODE=paused`로 바꾸고 재배포한다. Scheduler를
삭제하거나 공개 API를 중지할 필요는 없다.

## 4. 집계와 장애 기준

- 운영 통계: 자동 관제, 발효·격상·해제, 영향시설, 문자 시도·접수·수신 완료,
  실패, 고유 수신자, 연락처 미매핑과 상한 차단
- 특보 발효·격상·해제는 `지역코드+특보종류`를 고유 1건으로,
  영향시설은 중복 제거한 시설 수로 집계해 실적을 부풀리지 않는다.
- 별도 통계: `preview`, 지정 시험번호, 수동 Telegram
- KMA 오류는 해제로 처리하지 않고 이전 상태를 보존한다.
- 연락처 오류는 전체 문자를 차단하며 변화는 최대 30분 보류한다.
- 같은 담당자의 동시 변화는 한 통으로 묶는다.
- 현재 개인 SOLAPI 계정 한도에 맞춰 하루 40통에서 경고하고 50통 이후를
  차단한다. 계정 한도가 변경되기 전에는 이 상한을 높이지 않으며 Telegram
  요약은 유지한다.
- Firestore와 CSV에는 원 전화번호 대신 HMAC 수신자 코드만 저장한다.
- SOLAPI `수신 완료`는 통신사 결과이며 담당자의 실제 열람을 뜻하지 않는다.

## 5. Telegram 참여 링크

시설담당자는 문자만으로도 알림을 받을 수 있다. 관리자방 참여가 필요한 사람에게는
Telegram 비공개 그룹의 단일 초대 링크를 QR로 변환해 배포하고 `가입 요청 후
관리자 승인`을 켠다. 봇에 초대 권한을 줄 필요는 없으며, 기존 자동 요약 봇은
메시지 전송 권한만 유지해도 된다.
