# 기존 GitHub API 키의 Secret Manager 등록 결과

2026-11-08 11:46 KST. 사용자의 명시적 승인 후 두 키를 GCP `keco-safety-map`에 등록했다.
[등록 실행 42439928442](https://github.com/parkgogon/sfety_map/actions/runs/42439928442),
[키 값 없는 원본 보고서](report.json), [원본 요약](summary.md), [실행 근거](run.json), [코드 해시](source-hashes.json).

| 대상 | 생성한 버전 | 결과 |
| --- | --- | --- |
| `OPENAI_API_KEY` | `1` | `version_created` |
| `KAKAO_REST_API_KEY` | `1` | `version_created` |

사용자는 소유자 Cloud Shell에서 두 빈 Secret과 역할을 준비했다.
GitHub 배포 계정은 두 Secret에만 버전 추가 권한을 받았으며 **2026-11-08 03:39:23 UTC**에 만료한다.
API runtime 계정에는 두 Secret의 읽기 권한을 설정했다. 프로젝트 전체 관리자 역할은 추가하지 않았다.
이 준비 상태는 사용자 캡처로 확인했고 실제 두 값의 등록 성공은 워크플로/보고서로 확인했다.

실행 소스 `024e02d`의 등록 코드는 검증한 `072f416`과 같다. 두 키를 각각 한 번 등록했고 자동 재시도하지 않았다.
문서 head의 `[skip ci]`에서 발생한 첫 라벨 요청은 workflow run을 생성하지 않았다.
실제 실행이 없음을 확인한 뒤 일반 커밋의 명시적 승인 기록으로 위 run을 한 번 실행했다.
성공 후 등록 트리거 라벨을 제거했다. 다시 라벨을 추가해 키 버전을 중복 생성하지 않는다.

키는 GitHub Actions의 해당 단계 환경에서 gcloud stdin으로만 전달했다.
키 값/해시를 명령 인수·자식 환경변수·로컬 파일·채팅·artifact에 기록하지 않았다.
이 증빙에는 고정한 대상 이름·프로젝트·결과·생성 버전만 있으며 Secret의 내용을 다시 읽지 않았다.
GitHub 원본 키와 기존 Secret 버전은 삭제/수정하지 않았다. 새 키 발급도 하지 않았다.

같은 소스의 [일반 CI 42439906686](https://github.com/parkgogon/sfety_map/actions/runs/42439906686)도 성공했다.
Python 419개(실제 외부 HTTP/TCP 시도 0)·React 255개, 컴파일·시설 195개·웹 빌드 통과, 배포 작업은 건너뛰었다.
키 등록 실행에서 실제 OpenAI/Kakao/공식 피드 호출·발송·Cloud Run/Worker/Hosting 배포는 하지 않았다.
GitHub 배포 변수와 Cloud Run 키 참조도 아직 변경하지 않았다.

다음은 [운영 준비](../../../MESSAGE_REVIEW_OPERATIONS.md)의 세 배포 변수를 설정하는 단계다.
두 키의 등록 버전은 모두 1이며, 재등록/재발급은 필요하지 않다.
키가 저장됐다는 사실은 실제 API 인증·runtime 접근·저장 트랜잭션·새 지도 SDK 검증을 대신하지 않는다.
