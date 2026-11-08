# SafetyData 등록 후 연결 준비 — 2026-11-08

사용자 화면에서 긴급재난문자 이용승인과 기존 인증키를 확인했다.
사용자는 안내한 GCP 프로젝트에 `SAFETY_DATA_API_KEY`를 만들었다고 확인했다.
키 값을 채팅·로컬 작업공간·GitHub로 가져오지 않았다.

[점검 42476639226](https://github.com/parkgogon/sfety_map/actions/runs/42476639226)은 기존 읽기 전용 워크플로를
기능 브랜치 `a3bd615`에서 실행했다. 운영 API ready·앱 소스 `43b40e0`·SafetyData 환경변수 참조 미연결을 확인했다.
GitHub 점검 계정은 Secret/DB/IAM 메타데이터 조회 권한이 없어 **실행 실패·일부 확인** 상태다.
이 결과를 키 등록 실패·runtime 읽기 거부·기존 OpenAI/Kakao/Firestore 장애로 해석하지 않는다.
[값 없는 보고서](report.json)와 [요약](summary.md)을 보관한다.

실제 키 값 조회·문자 API·AI/장소 호출·DB 읽기/쓰기·배포·발송은 0건이다.
등록 버전과 runtime의 실제 읽기/네트워크 성공 여부는 아직 검증하지 않았다.

다음은 소유자 Cloud Shell에서 [점검 도구](../../../../scripts/check_safetydata_connection.py)를 실행하는 것이다.
`--grant-runtime`은 이 Secret에만 runtime 계정의 읽기 역할을 부여한다.
키는 Cloud Shell 메모리에서만 사용해 공식 문자 API를 1회 조회하며, 키/원문/원본 오류는 출력/저장하지 않는다.
이 도구는 운영 서버 배포·키 참조 연결·자동 수집 활성화를 수행하지 않는다.
Cloud Shell의 1회 응답 성공과 실제 Cloud Run의 통신/전체 API 계약 검증을 구분한다.

도구의 가짜 gcloud/API 검사 8개를 포함한 전체 Python 499개·compileall 통과(외부 HTTP/TCP 0).
고정 프로젝트/Secret/runtime·버전 고정·역할 범위·오류/불완전 응답·키/원문 출력 방지·명시적 권한 추가 옵션·1회 조회를 검사했다.
도구의 실제 소유자 실행은 아직 하지 않았으며 결과를 성공으로 기록하지 않는다.
