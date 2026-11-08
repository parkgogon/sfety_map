# 재난문자 검토 운영 연결

## 현재 적용 상태 — 2026-11-08 KST

운영 앱 소스는 `43b40e0aee7c9f548ef4d633158c2001c2c86a8d`다.
사용자 승인으로 [PR #1](https://github.com/parkgogon/sfety_map/pull/1)을 병합하고
[배포 42443589707](https://github.com/parkgogon/sfety_map/actions/runs/42443589707)을 완료했다.
[운영 검수 증빙](evidence/2026-11-08/production-message-release/README.md)에 리비전/Hosting·화면·회복 결과가 있다.

| 대상 | 현재 상태 | 확인 근거 |
| --- | --- | --- |
| OpenAI | Secret 버전 1 연결, `gpt-5.4-mini-2026-03-17`/low | 창작 기록 실제 분석 저장, 모델 3회 |
| Kakao Local API | REST Secret 버전 1 연결 | 실제 장소 후보/시설 조회 결과 저장 |
| Kakao 지도 | 기존 JavaScript 키/도메인 | 실제 SDK·지도 타일 24응답, 로드된 지도 이미지 9개 |
| Firestore | `MESSAGE_REVIEW_STORE=firestore` | 등록·선정·완료/초안 저장·새로고침 복구 |
| 공식 SafetyData 피드 | 미연결 | 별도 키/승인·실제 응답 확인이 남음 |

[재난문자 검토](https://keco-safety-map.web.app/control/messages)는 기존 관리자 로그인을 사용한다.
[저장된 창작 검수 기록](https://keco-safety-map.web.app/control/messages?record_id=manual-44013dfc139140e882c5c9af012ddd5b)을 열어 확인할 수 있다.
키 값·비밀번호·세션 토큰은 채팅·로컬 작업공간·Git·artifact로 가져오지 않았다.
두 키의 재등록이나 재발급은 필요하지 않다. 기존 GitHub 원본도 유지했다.

## 배포 설정

[배포 설정 생성기](../scripts/build_message_review_deploy_config.py)는 비밀값을 읽지 않고 고정 버전 참조만 만든다.
API에만 적용하며 기존 KMA/관리자/알림 참조를 보존한다. Worker/웹에는 AI 서버 키를 전달하지 않는다.

| GitHub Repository variable | 기본값 | 현재/켜는 값 |
| --- | --- | --- |
| `MESSAGE_REVIEW_AI_ENABLED` | `false` | 현재 `true` |
| `MESSAGE_REVIEW_OPENAI_VERSION` | 비어 있음 | 현재 `1` |
| `MESSAGE_REVIEW_KAKAO_VERSION` | 비어 있음 | 현재 `1` |
| `MESSAGE_REVIEW_FEED_ENABLED` | `false` | 현재 꺼짐, 공식 피드 별도 검수 후 `true` |
| `MESSAGE_REVIEW_FEED_VERSION` | 비어 있음 | 켤 때 승인한 숫자 버전 |

켜진 기능의 버전이 없거나 `latest`/잘못된 값이면 이미지 빌드 전에 중단한다.
AI를 켜면 평가 모델/low와 Firestore 저장을 명시한다. 이후 배포도 이 변수와 고정 버전을 사용한다.
등록 과정/권한 범위는 [키 설정 문서](MESSAGE_REVIEW_KEY_SETUP.md)를 따른다.

## 안전한 운영 검수

[Verify message release](../.github/workflows/verify-message-release.yml)는 main에서 명시적으로 실행한다.
`baseline`은 현재 API/Worker 리비전과 Hosting 릴리스의 허용한 메타데이터만 읽는다.
`verify`에는 실제 배포 앱 SHA를 전달한다. 선택적 `record_id`는 출처가 일치하는 기존 창작 검수 기록만 재사용한다.

검수는 Cloud Run IAM으로 보호한 임시 서비스 안에서 수행한다. 관리자 비밀번호는 Secret 참조로만 주입하고
허용한 결과 JSON/창작 화면만 반환한다. WIF ID 토큰은 GitHub 실행 안에서만 사용한다.
임시 서비스는 최소 0/최대 1·1 CPU/2Gi·요청 360초, 한 번만 검수하고 실행 후 삭제한다.
실제 전파/Worker/dispatch API는 브라우저 허용 목록에서 제외한다. AI 분석은 저장 결과가 없을 때 최대 1요청이다.

초기 Job 검수는 로그 읽기 권한과 실패 CLI 출력 회수 문제로 결과를 확인하지 못했다.
`collect` 모드는 해당 Job의 태그된 결과만 재조회하며 현재 권한으로는 unavailable일 수 있다.
이를 키/저장소 부재나 앱 실패로 단정하지 않는다. 이후 비공개 서비스 직접 결과 회수 방식으로 검수를 통과했다.

운영 검수에서 Worker의 KMA_ROUTE 오류가 발견돼 [동일 설정 재기동](../.github/workflows/refresh-worker-network.yml)을 한 번 수행했다.
예상 Worker 리비전과 앱 SHA/이미지가 다르면 중단하고, 전체 runtime spec이 유지됐는지 대조한다.
원래 Scheduler의 15:35·15:40 KST 두 실행에서 KMA LIVE·Worker 정상·공개 health 200을 확인했다.
특보 기준 상태·위험도 정책·저장소는 바꾸지 않았고 시험 발송/수동 Worker 호출도 하지 않았다.

## 공식 피드 연결과 남은 범위

공식 피드는 관리자 요청 시 지역·하루·페이지로 조회하고 공급자 원본 서명/중복·정정을 확인해 등록하는 구조다.
전체 상시 수집·실제 담당자 연락/현장 회신은 구현 범위에 포함되지 않는다.
키/이용 승인·실제 응답의 ID/본문/발행/수신지역·이용/보관 조건을 확인한 후 별도로 연결한다.
미연결 상태에서도 수동 입력/창작 시연은 운영할 수 있다.

검토 완료는 내부 검토다. 지도 대표점 반경은 위험 반경이 아니고, 복사는 실제 발송/수신 실적이 아니다.
실기기 터치/핀치·장기 부하 검증은 남아 있다. 공개 문자 보관 기간·관리자 접근·외부 AI 전송 대상은 실제 기관 운영 기준으로 확정한다.

## 이전 준비 점검 기록

[42435450742](https://github.com/parkgogon/sfety_map/actions/runs/42435450742)의
[원본 보고서](evidence/2026-11-08/message-review-deployment/report.json)는 당시 미연결 상태다.
당시 Firestore/Secret 조회의 권한 부족은 DB/키 부재를 뜻하지 않았다.
사용자 Cloud Shell에서 Native 모드와 초기 두 Secret 부재를 확인하고 생성/등록했다.
[키 등록](evidence/2026-11-08/message-key-copy/README.md),
[배포 참조 준비](evidence/2026-11-08/message-release-readiness/README.md) 이후 위 운영 배포/실제 검수로 갱신됐다.
