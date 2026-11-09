# 공식 재난문자 자동전파 4단계 — 연결·이력·예외·전체 제어

2026-11-09 KST. 기준 `b7b0a55`, `plan/message-auto-forwarding-20261109`의 1~4단계 미커밋 작업공간이다.
운영 앱은 이 작업에서 변경하지 않았다. 전송 제공자·원문·시설은 가짜이며 실제 발송/모델 호출 결과로 집계하지 않는다.

## 검증 결과

- Python **657개**(4단계 신규 27개), React **279개/43파일**, 컴파일·시설 CSV 195개·웹 빌드·셸 문법·diff 검사 통과.
- [전송 경계 재현 10건](delivery-checks.json): 같은 원문/동시/재시작, 시작 전 preview 제외, 미상/거절/명시적 429, 저장 응답 유실,
  원문/시설 변경, 요청 전 수동 재판단, Firestore 트랜잭션 모형의 중단, 별도 관리자 큐.
- [브라우저 검수](browser-checks.json): 실제 빌드+로컬 API, PC 1440/모바일 390·360px의 3탭과 전체 일시정지/새 시작.
  가로 넘침/페이지 오류/예상 밖 요청 0. 조회와 전체 제어가 새 분석·가짜 발송·사람 검토 버전을 추가하지 않았다.
- 공통 NetworkGuard 자동 검사의 실제 외부 HTTP/TCP **0**. 실제 OpenAI HTTP·Telegram/SMS 시험 발송·운영 배포도 **0**.
  Python ASGI/Chromium은 기본 샌드박스의 대기/실행 제약을 피하는 권한 확장으로 실행했고 차단/가짜 제공자 조건을 유지했다.

## 화면 — 창작 데이터/가짜 전송 표시

| 폭 | 전파 이력 | 확인 필요 |
| --- | --- | --- |
| PC 1440 | [보기](deliveries-1440.png) | [보기](exceptions-1440.png) |
| 모바일 390 | [보기](deliveries-390.png) | [보기](exceptions-390.png) |
| 모바일 360 | [보기](deliveries-360.png) | [보기](exceptions-360.png) |

휴대폰 화면 크기를 모사한 Chromium 검수다. 실제 직원 단말/Telegram 수신·카카오 타일은 검수하지 않았다.
직원 문안의 공개 지도 링크와 관리자용 원문 링크를 구분해 코드 계약으로 확인했다. 실제 운영 직원 접속은 후속 검수다.

## 구현 경계

- 기존 `TelegramNotifier.send_batch`와 KMA 기준/지표/outbox는 유지한다. 문자 전용 `send_once`는 plain text 한 번의 요청이며 redirect/자동 HTTP retry를 하지 않는다.
  성공은 올바른 방의 `message_id`가 있는 응답이다. timeout/5xx/불완전 영수증/중단은 미상이고 자동 재발송하지 않는다.
- 명시적 429와 유효 retry_after만 최소 60초 뒤 재검증하고 총 3회로 제한한다. 관리자 알림 실패를 다시 같은 방 알림으로 생성하지 않는다.
- 현재 원문/분석/시설/정책·preview head·전파 제어를 교차 읽고 요청 시작을 원자적으로 저장한다.
  HTTP와 DB를 같은 트랜잭션으로 묶을 수 없으므로 중복 없는 1회 전달을 보장한다고 표시하지 않는다.
- preview 작업은 그대로 `phase=preview`, `dispatch_enabled=false`다. 별도의 전파 outbox만 전송 권한을 가진다.
  공식 전달 문안에는 미리보기의 `미발송` 표시를 붙이지 않는다. 관리자 미리보기와 실제 전송 상태는 별도 표시다.
  시작 후 만들어진 같은 generation의 작업과 시작 이후 발행 원문만 대상이다. 새 배포·새 시작은 과거 preview를 승격하지 않는다.
- 전파 상태/제어/예외는 관리자 보호 API이며 GET은 읽기 전용이다. 예외의 확인 기록은 원래 전송 결과를 유지하고,
  변경 판단 반영은 한 번도 요청하지 않은 최신 공식 버전만 허용한다. 실제 직원방/관리자방 주소를 모델이나 브라우저에 전달하지 않는다.

## 재현

```bash
python scripts/run_python_tests.py
python docs/evidence/2026-11-09/message-auto-forwarding-stage4/check_delivery.py
cd field_web && npm test && npm run build
```

브라우저는 `test_server.py`의 가짜 서비스만 사용한다. 같은 로컬 환경에서 `check_browser.py`를 실행하며,
이 스크립트는 로컬 origin 외 요청을 차단한다. 운영 API/방 주소로 바꿔 재현하지 않는다.
[검사 요약](test-summary.json), [원본 검사 끝부분](verification.txt), [운영 반영 전 절차](../../../MESSAGE_DELIVERY_ROLLOUT.md).

실제 Firestore IAM/네트워크, Telegram 수신, 공식 API 최신순/공개 지연·처리량, 새 모델의 판단 품질은 이 검증에 포함하지 않는다.
전파 기능의 기본값은 false이며 새 배포에서 관리자 전체 시작 전에는 실제 전송하지 않는다.
