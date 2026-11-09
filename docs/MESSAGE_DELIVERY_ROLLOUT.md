# 공식 문자 자동전파 — 운영 반영 전 확인과 시작/중단

2026-11-09 KST. 1~4단계는 로컬 구현/가짜 제공자 검증 결과다. 현재 운영 앱 `5f58be1`을 이 작업에서 변경하지 않았다.
기존 OpenAI·Kakao·SafetyData 키와 Telegram 봇/직원방/관리자방을 재사용한다. 키를 재발급하거나 채팅/GitHub 파일에 넣지 않는다.

## 11월 10일 사전 점검 — 전환 보류

[Draft PR #4](https://github.com/parkgogon/sfety_map/pull/4)와 [실제 점검 증빙](evidence/2026-11-10/message-delivery-preflight/README.md).
공식 표본은 발행 시각 최신순이 아니었고 기존 수집은 ERROR였다. 이후 [순서 독립 수집·연결 오류 보완](evidence/2026-11-10/message-collection-fix/README.md)을 구현했으며 아직 운영 미배포다. 이후 [AI 판단/근거 보완](evidence/2026-11-10/message-ai-judgment-fix/README.md)도 같은 6예문/엄격한 서버 기준에서 최종 6/6 통과했다. 고정 예문 검수이며 일반 정확도는 아니다.
**아래 전환 값은 아직 적용하면 안 된다.** 남은 실제 방 연결/고정 숫자 버전·런타임 저장/제어를 검수한 뒤 전환 설정을 확정한다.
직원/관리자방의 latest 참조도 고정 숫자 버전 확인이 남아 있다. Secret/Firestore 조회 권한 부족을 키 누락으로 단정하지 않는다.

## 구현된 운영 흐름

```text
공식 API 수집 → 저장/중복 제거 → AI의 도구 조회·판단 → 근거/시각 검증
  ├─ 전달 필요 → 별도 전파 outbox → 기존 직원 단체방
  ├─ 기록 → 사유 보존
  └─ 분석 불가/판단 불명확 → 긴급 원문 기준 또는 묶음 관리자 예외
```

관리자는 `/control/messages?view=delivery`에서 전체 시작·일시정지와 이력/예외를 확인한다. 건별 승인은 없다.
기존 수동 검토·직접 입력은 `view=review`, 상세 관리는 `view=advanced`로 유지한다.
자동 판단/전송을 사람의 검토 완료·직원 열람·현장 확인으로 기록하지 않는다.

## 배포 전에 남은 실제 검수

1. 동일한 기준 commit/이미지로 통합할 변경과 아래 설정을 검토한다. 기존 KMA LIVE·기준 상태·정규 예약을 보존한다.
   현재 배포의 문자 상태·권한/키 연결·운영방 접근을 읽기 전용으로 확인한다. 실제 시험 발송/기상 dispatch/기준 초기화는 하지 않는다.
2. 정렬에 의존하지 않는 실제 페이지 순회·공개 지연·실제 처리량과 500회 한도 안의 수집을 확인한다.
   당일 전체 순회/과거 보충 완료 시각·누락/지연과 적응형 순회 간격을 확인한다. 현재 20건/하루와 $1/하루·$20/월은 제한 운영의 초기값이며 처리량 보장값이 아니다.
   새 AI 판단의 실제 품질은 호출/토큰 상한을 정한 별도 평가로 측정한다. 자동 테스트를 그 정확도 실적으로 쓰지 않는다.
3. `main` push/운영 배포는 사용자 요청 후 수행한다. 배포 후에도 실제 전파는 꺼진 상태로 검수하며,
   새 배포의 API/worker 버전·같은 봇/방 고정 버전·Firestore·1분 예약·직원 공개 링크를 확인한 뒤 전파 시작을 실행한다.
   실제 직원의 수신/접속과 장기 장애/지연 관측은 로컬 검수와 구분한다.

## 준비할 비밀값 없는 설정

| 변수 | 전환 시 값 |
| --- | --- |
| `MESSAGE_COLLECTION_ENABLED` / `MESSAGE_COLLECTION_CONTRACT_VERIFIED` | true / true |
| `MESSAGE_NOTIFICATION_PREPARATION_ENABLED` | true |
| `MESSAGE_COLLECTION_FAST_ENABLED` / `MESSAGE_COLLECTION_INTERVAL_MINUTES` | true / 5 (진행 예약, 전체 순회 간격은 조회량에 따라 늘어남) |
| `MESSAGE_FEED_REQUEST_LIMIT` | 450 (사용자 500회 중 앱 공통 최근 24시간 상한) |
| `MESSAGE_ANALYSIS_DAILY_LIMIT` | 20, 실제 처리량과 함께 확정 |
| `MESSAGE_AI_SPEND_BUDGET_ENABLED` | true |
| `MESSAGE_AI_DAILY_BUDGET_CENTS` / `MESSAGE_AI_MONTHLY_BUDGET_CENTS` | 100 / 2000, 전환 전 확정 |
| `MESSAGE_EMERGENCY_FALLBACK_ENABLED` | true |
| `MESSAGE_DELIVERY_ENABLED` | true는 서버 전송 기능 연결 허용. 그 자체가 전파 시작은 아님 |
| `MESSAGE_DELIVERY_BOT_VERSION` / `MESSAGE_DELIVERY_STAFF_VERSION` / `MESSAGE_DELIVERY_ADMIN_VERSION` | 기존 Secret의 확인한 고정 숫자 버전. 임의로 1/latest를 가정하지 않음 |
| `TELEGRAM_ADMIN_SECRET_NAME` | 기존 `TELEGRAM_CHAT_ID` 또는 `TELEGRAM_ADMIN_CHAT_ID` |

OpenAI/Kakao/SafetyData는 기존 고정 버전 설정을 유지한다. 새 Telegram 바인딩은 API와 문자 worker에 같은 버전을 연결한다.
직원방과 관리자방이 같은 값이면 시작할 수 없다. KMA worker의 바인딩·정책·기준 상태는 이 경로로 변경하지 않는다.
배포 설정 생성기는 외부 호출 없이 검증하며, 플래그/버전이 빠지면 배포 전에 실패한다.
현재 CI의 새 플래그 기본값은 모두 false다. 별도의 상주 서버나 추가 예약 작업은 만들지 않는다.

## 시작과 정지 경계

- 전파 시작은 서버 시각·현재 배포 revision·봇/방 연결의 지문·새 generation을 저장한다.
  원문 발행 시각과 작업 생성 시각이 모두 시작 이후이고, 작업에 같은 generation이 기록되어야 한다.
  이전 preview를 자동 승격하지 않으며 미리보기의 `dispatch_enabled=false`도 변경하지 않는다. 실제 권한은 별도 outbox에만 있다.
- 각 새 앱 배포 후에는 관리자 화면에서 다시 시작한다. API/worker의 현재 revision·고정 방 연결이 맞아야 전송한다.
  과거 시작 시각을 환경변수 변경이나 재시작으로 초기화하지 않는다. 제어 변경은 generation 비교로 충돌을 막는다.
- 일시정지는 전달만 멈춘다. 수집/판단/예산/저장 기록은 유지한다. 다시 시작하면 그 시각 이후 자료만 대상이며 멈춘 동안의 대기를 일괄 전파하지 않는다.
  이미 요청을 시작한 Telegram 전송은 정지로 회수할 수 없다.
- 서버 연결의 긴급 차단은 `MESSAGE_DELIVERY_ENABLED=false`로 배포한다. 저장 기록/일일 집계/원문/기상 기준은 지우지 않는다.
  정상적인 중단은 화면의 일시정지를 우선 사용한다. 새 배포에서 다시 전파하려면 새 시작이 필요하다.

## 전송 결과와 복구

| 상태 | 처리 |
| --- | --- |
| `sent` | 올바른 방의 `message_id`가 있는 성공 응답 보존. 열람/현장 확인 아님 |
| `rejected` | 명시적 거절. 자동 반복하지 않고 연결/내용과 이력을 확인 |
| `waiting` | 명시적 429 + 유효한 retry_after만 최소 60초 뒤 재검증/재시도. 총 3회 한도 |
| `unknown` | timeout/불완전 응답/중단 등 도착 미상. 자동 재발송하지 않음 |
| `sending` | 요청 전 원자적으로 저장한 상태. 300초가 지나면 미상으로 복구 |
| `cancelled` | 원문·분석·시설·정책·전파 시작 경계 불일치. 보내지 않음 |

전파 직전 원본·준비 작업·head·현재 제어를 같은 트랜잭션에서 검증하고 시도 상태를 저장한 뒤 HTTP를 1회 실행한다.
Telegram과 Firestore를 하나의 트랜잭션으로 묶을 수 없으므로 중복 없는 전달을 보장한다고 주장하지 않는다.
직원 전파와 관리자 예외는 별도 큐를 사용하며, 분석 건수/비용 한도가 차도 저장된 전파 작업을 먼저 처리한다.
관리자 알림 실패를 다시 관리자 알림으로 생성하는 순환은 없다. 같은 사유/날짜는 묶어 알린다.

결과 미상/거절은 `수신 확인 기록` 또는 `별도 조치 완료`를 남길 수 있다. 원래 결과와 시도 이력은 유지하고 다시 보내지 않는다.
변경된 판단의 명시적 반영은 **아직 요청한 적 없는 최신 공식 버전**만 가능하다. 이미 시도한 버전은 재등록할 수 없다.
필요한 별도 전달은 이력 문안을 복사해 관리자가 처리하며 앱의 API 성공 실적으로 바꾸지 않는다.

## 검증 근거

[4단계 로컬 검수](evidence/2026-11-09/message-auto-forwarding-stage4/README.md).
새 업무 기록은 기존 `disaster_message_pipeline`/`disaster_message_reviews`에 한정하며 KMA 실적·outbox와 섞지 않는다.
`queue_key` 한 필드의 범위/정렬 조회를 사용해 새 복합 색인/고정비 인프라를 추가하지 않았다.
