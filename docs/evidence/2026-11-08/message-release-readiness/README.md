# 재난문자 기능 배포 전 최종 점검

2026-11-08, 소스 `ac51c06`, [검토 PR #1](https://github.com/parkgogon/sfety_map/pull/1).
이 점검은 main 병합/운영 배포를 실행하지 않았다. 두 키 등록 승인을 배포 승인으로 확대하지 않는다.

## 실제 배포 변수

사용자가 GitHub Variables에 등록한 값을 CI에서 직접 읽어 검증했다.
[일반 CI 42441415634](https://github.com/parkgogon/sfety_map/actions/runs/42441415634)의
`Check message review deployment variables` 단계 출력에서 다음을 확인했다.
[값 없는 연결 설정 증빙](deployment-config.json)은 키 참조/모델만 포함하며 실제 키 값은 아니다.

| 변수 | 실제 인식된 값 |
| --- | --- |
| `MESSAGE_REVIEW_AI_ENABLED` | `true` |
| `MESSAGE_REVIEW_OPENAI_VERSION` | `1` |
| `MESSAGE_REVIEW_KAKAO_VERSION` | `1` |

출력은 `OPENAI_API_KEY=OPENAI_API_KEY:1,KAKAO_REST_API_KEY=KAKAO_REST_API_KEY:1`,
`MESSAGE_REVIEW_STORE=firestore`, 평가 모델 `gpt-5.4-mini-2026-03-17`·reasoning `low`다.
공식 피드 Secret 참조는 추가되지 않았다. Python **419개**·React **255개**, compileall·시설 195개·웹 빌드 통과.
이 CI는 GCP에 인증하거나 값을 조회/배포하지 않았고 배포 job은 건너뛰었다.

## 기존 운영 상태

[공개 GET 점검](public-health.json), 2026-11-08 03:11 UTC:

- `/api/v1/health`: HTTP 200, `status=ok`.
- `/api/v1/health/operations`: HTTP 200, `reason=ready`, worker 최근 **102초**, KMA `live`.

KMA 강제 조회·dispatch·Worker 시험·발송·키 값 읽기는 하지 않았다. 확인 시점의 상태이며 미래 상태를 보증하지 않는다.

## 승인받을 적용 범위

PR #1을 main에 병합하면 기존 GitHub Actions 배포가 실행된다.
API·Firebase 웹에 문자 등록/AI 검토·지도 기준/시설 선정·완료/초안·후속 연결 기능과 두 키 참조를 적용한다.
현재 `ALERT_AUTOMATION_ENABLED=true`, `ALERT_AUTOMATION_MODE=live`여서 기존 배포 절차의
Worker/Scheduler 재적용도 포함된다. 활성 상태에 따라 기존 uptime 설정도 재적용된다.

이번 변경에는 `safety_dashboard/alerts`, Dockerfile, requirements, 기존 위험 정책의 변경이 없다.
기존 KMA/관리자/알림 참조와 설정을 유지하며 새 AI 키는 API에만 전달한다.
실제 Telegram/SMS·dispatch·Worker 시험 호출로 배포를 검수하지 않는다.
공식 피드 키 연결은 별도이며 수동 공개 문자/창작 시연부터 운영 적용한다.

승인 후 배포 직전에 API/Worker 현재 리비전과 Hosting 상태를 기록하고 기존 경로로 배포한다.
그 뒤 관리자 문자 화면의 실제 SDK·창작 기록 저장/복구·제한된 AI 연결을 확인한다.
실제 서버 검수가 끝나기 전에 runtime 저장/지도/모델 연결을 완료했다고 주장하지 않는다.
프로젝트 AGENTS.md의 main/배포 별도 요청 규칙에 따라 현재는 명시적 사용자 승인을 기다린다.
