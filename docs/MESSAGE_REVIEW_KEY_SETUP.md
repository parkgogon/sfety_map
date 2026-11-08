# 기존 GitHub 키를 GCP에 등록하는 절차

> 2026-11-08 현재: 두 키 **버전 1 등록·운영 API 연결·실제 창작 검수 완료**.
> 아래 준비/등록 과정은 당시 절차이며 다시 실행할 필요가 없다.
> [최신 운영 검수](evidence/2026-11-08/production-message-release/README.md), [운영 설정](MESSAGE_REVIEW_OPERATIONS.md).

2026-11-08. 사용자는 휴대폰 Cloud Shell로 작업하고 결과를 캡처로 제공한다.
새 키를 채팅으로 받거나 재발급하지 않고, GitHub Actions의 기존 두 값을 Secret Manager로 전달한다.
도구의 로컬 검증·사용자 Cloud Shell 준비와 실제 두 키 등록을 완료했고, 이후 서버 연결/배포·운영 검수까지 마쳤다.

## 확인한 계정과 대상

소유자 Cloud Shell 캡처에서 다음을 확인했다.

- 프로젝트 `keco-safety-map`, 번호 `531222653541`, 기본 DB `FIRESTORE_NATIVE`.
- `OPENAI_API_KEY`, `KAKAO_REST_API_KEY` Secret은 `NOT_FOUND`.
- `github-deployer@keco-safety-map.iam.gserviceaccount.com`: GitHub Actions Deployer.
- `safety-dashboard-runtime@keco-safety-map.iam.gserviceaccount.com`: K-ECO Safety API Runtime.

키 이름과 역할이 같은 이름이라는 사실을 실제 키 등록 성공으로 해석하지 않는다.
공식 피드 키/DB runtime 문서 권한/새 지도 SDK는 이 절차에서 검증하지 않는다.

## 1. 소유자의 준비 명령

[준비 스크립트](../scripts/prepare_message_key_secrets.sh)를 검토한 고정 commit URL에서
휴대폰 Cloud Shell의 임시 파일로 다운로드한 뒤 실행한다. 채팅에서는 실행할 한 블록만 안내한다.
저장소는 공개지만 스크립트에 키 값은 없다. TLS 검증을 유지하고 다운로드 실패 시 실행하지 않는다.

스크립트가 변경하는 것은 다음 두 Secret뿐이다.

1. 없다면 빈 보관함을 생성한다. 기존 Secret/버전은 덮어쓰거나 지우지 않는다.
2. GitHub 배포 계정에 각 Secret의 `roles/secretmanager.secretVersionAdder`를 부여한다.
   `request.time < timestamp(...)` 조건으로 실행 시각부터 **1시간 후 만료**한다.
   조회/값 읽기/삭제/프로젝트 전체 관리자 역할을 부여하지 않는다.
3. API runtime 계정에 각 Secret의 `roles/secretmanager.secretAccessor`를 부여한다.
   이 읽기 권한은 이후 서버 연결에 필요하며 두 Secret에만 유지한다.

스크립트는 키 값을 읽거나 등록하지 않고 API/Worker/Hosting 배포·알림·기상 상태를 변경하지 않는다.
실패하면 즉시 중단하므로 앞서 성공한 일부 보관함/권한은 남을 수 있다. 성공 문구와 만료 시각을 캡처로 확인한다.
만료 후에는 준비 명령을 다시 실행할 수 있다. 기존 버전을 삭제하지 않으며 새 1시간 권한을 추가한다.
만료한 IAM 조건 항목 자체는 남지만 해당 조건의 추가 권한은 유효하지 않다.

### 실제 준비 결과 — 사용자 캡처

사용자가 고정 소스 `072f416`의 준비 명령을 실행했고, 캡처에서 두 Secret 생성과 네 IAM 갱신,
`등록 준비 완료`를 확인했다. GitHub 버전 추가 권한 만료는 **2026-11-08 03:39:23 UTC**다.
조건부 권한을 처음 추가한다는 WARNING은 오류가 아니며 이후 갱신/완료 문구가 출력됐다.
이 확인은 빈 보관함/권한 준비이며 실제 값 등록/서버 연결 성공이 아니다.

자동 승인 검토가 `message-keys-copy` 라벨 추가를 거부했다. 이유는 GitHub의 두 민감한 값을
프로젝트 `keco-safety-map`의 동일 이름 Secret Manager에 전송·등록하는 정확한 작업에 대한
명시적 사용자 승인이 없다는 것이다. 라벨 추가/등록 워크플로는 실행되지 않았다.
대체 트리거·직접 등록 등으로 우회하지 않는다. 사용자에게 정확한 두 키/대상과 등록 승인 여부를 물었다.
명시적 승인 후에만, 만료 시각과 PR의 등록 코드가 검증한 것과 같은지 다시 확인하고 실행한다.

사용자가 “응, OpenAI·카카오 키를 GCP에 등록해줘”라고 명시적으로 승인했다.
2026-11-08 02:44 UTC에 만료 전임과 등록 코드가 `072f416`과 같음을 확인하고 트리거를 요청했다.
문서 커밋의 `[skip ci]` 때문에 PR 라벨 이벤트의 워크플로 실행이 생성되지 않았다.
키 등록 실행이 없음을 확인하고, 승인 기록을 일반 커밋에 반영한 뒤 한 번 실행했다.
라벨 실행을 계획할 때 `[skip ci]`인 head에서는 실제 workflow run 생성 여부부터 확인한다.

## 2. 기존 두 값 등록

소유자의 준비 완료/만료 시각을 확인한 뒤에만 [등록 워크플로](../.github/workflows/copy-message-api-keys.yml)를
수동 실행한다. main 반영 전에는 동일 저장소 PR의 `message-keys-copy` 라벨을 명시적으로 추가해 실행할 수 있다.
일반 push/PR 갱신/검토 라벨로는 실행하지 않으며 Fork PR에는 키를 전달하지 않는다.
두 값은 해당 복사 단계의 환경변수로만 주입하고 gcloud stdin으로 고정 프로젝트에 보낸다.
[복사 도구](../scripts/copy_message_api_keys.py)는 `--execute`가 없으면 변경하지 않는다.

키 값/해시/길이·제공자 오류 원문을 출력하거나 파일/artifact에 기록하지 않는다.
자식 프로세스의 환경변수와 명령 인수에서도 두 값을 제거한다. CLI 파일/HTTP 로그와 자동 재시도를 끈다.
결과에는 대상 이름·등록 여부·생성한 버전 번호만 남긴다. 실제 서비스 호출·배포·자동 활성화를 하지 않는다.

결과 미확인/실패 후 두 값을 무조건 재복사하지 않는다. 소유자가 버전 목록 메타데이터를 확인한다.
`outcome_unknown`은 원격 등록 뒤 응답만 실패한 경우도 포함한다. 성공한 버전 번호는 그대로 보존한다.
필요하면 `message-openai-key-copy` 또는 `message-kakao-key-copy` 라벨로 미등록 대상만 재실행한다.
명시적으로 다시 실행하면 기존 Secret에 **새 버전**이 추가된다. 기존 버전은 수정하거나 삭제하지 않는다.
자동 취소/삭제나 성공 버전의 재생성으로 부분 실패를 숨기지 않는다.

### 실제 등록 결과 — 2026-11-08 02:46 UTC

사용자 승인 후 [등록 실행 42439928442](https://github.com/parkgogon/sfety_map/actions/runs/42439928442)이 성공했다.
[키 값 없는 원본 보고서](evidence/2026-11-08/message-key-copy/report.json)에서 다음을 확인했다.

| 대상 Secret | 생성한 버전 | 결과 |
| --- | --- | --- |
| `OPENAI_API_KEY` | `1` | `version_created` |
| `KAKAO_REST_API_KEY` | `1` | `version_created` |

실행 소스는 `024e02d`이며 등록 코드는 검증한 `072f416`과 같다. 만료 전에 각각 한 번 등록했다.
성공 뒤 트리거 라벨은 제거했다. 두 Secret을 다시 생성하거나 키를 다시 복사할 필요가 없다.
GitHub 원본 키는 유지했고 키 값/해시를 로컬 환경·채팅·증빙 파일로 가져오지 않았다.
이 등록 단계에서는 실제 AI/장소 검색 호출, GitHub 배포 변수 변경, Cloud Run 참조 적용·main 병합·배포·발송을 하지 않았다.

## 3. 등록 이후 현재 상태

사용자가 세 GitHub Variables를 등록했으며 실제 CI에서 두 Secret 버전 1 참조를 확인했다.
명시적 배포 승인 후 main `43b40e0`으로 운영 API에 연결했다.
실제 창작 기록에서 AI/장소 검색·Firestore 저장/복구·지도·초안 복사를 검수했다.
GitHub 원본 키는 유지한다. 운영 Telegram/SMS/dispatch/Worker 시험 호출은 하지 않는다.
공식 피드 키는 별도 준비 대상이며 두 키의 재등록과 구분한다.

## 검증

Python **419개**(공통 실행기의 실제 외부 HTTP/TCP 시도 0), compileall, 준비 스크립트의 bash 구문 검사 통과.
가짜 gcloud로 두 Secret/두 계정 역할 범위, 생성 실패 시 IAM 변경 중단, 고정 프로젝트/출력 버전 확인,
누락 키의 첫 쓰기 차단, stdin 전송/인수·로그/자식 환경에서 값 제외, 일부 실패·타임아웃/재시도 방지를 검사했다.
등록 워크플로는 YAML 파싱과 수동/동일 저장소 조건·한 단계 secret 주입 범위를 확인했다.
실제 GCP 준비는 사용자 캡처로, 두 키 등록 성공은 위 워크플로와 원본 버전 보고서로 확인했다. 실제 서버 연결은 위 운영 검수에서 확인했다.
