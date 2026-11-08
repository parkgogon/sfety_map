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
사용자가 고정 소스 `467234b --grant-runtime` 실행 결과를 제공했다. [소유자 결과](owner-check.json)에서
버전 1·runtime 역할 추가·API 1회 빈 응답을 확인했다. 실제 키/원문은 출력·공유하지 않았다.
`passed`는 이 소유자 Cloud Shell 단계의 결과이며, 0건 응답으로 실제 문자 필드·날짜/지역/페이지나 Cloud Run 통신을 검증한 것은 아니다.

## 임시 Cloud Run의 실제 키 사용 — 소스 `93fad6a`

[실행 42478871279](https://github.com/parkgogon/sfety_map/actions/runs/42478871279)이 성공했다.
운영과 동일한 runtime 계정과 기존 고정 worker 이미지, `SAFETY_DATA_API_KEY:1`만 연결한 새 IAM 비공개 점검 서비스를 사용했다.
추가 관리자/모델/지도/발송 키를 연결하지 않았고 운영 API·기존 Worker·예약 실행·Firestore 기록을 바꾸지 않았다.
배포한 것은 임시 점검 서비스이며 기능의 운영 배포가 아니다. **임시 서비스 삭제 단계도 성공했다.**

[결과](runtime-check.json)에서 다음을 확인했다.

- API **4회**: 오늘 전국 첫 페이지 2건, 둘째 페이지 2건, 부산 1건, 첫 페이지 재확인 2건.
- 발행 날짜·수신지역·요청 페이지 크기, 페이지 간 ID 비중복, 짧은 조회 동안 첫 페이지 안정 검사 통과.
- 서버의 실제 키 읽기/통신 확인. 원문·ID·키 값은 결과에 포함하지 않았다.
- DB 쓰기·모델 호출·실제 발송 **0건**. 소유자 1회와 합친 이 연결 검수의 실제 SafetyData 조회는 **5회**다.

이는 당일 제한 표본이다. 과거 날짜/자정·장기 지연·실제 계정 한도·이용 조건을 검증한 것은 아니다.
계정의 일일 호출 한도는 사용자에게 질문했으며, 확인 전 자동 수집을 활성화하지 않는다.
기본 첫 페이지 조회만 하루 2,880회(5분/5지역/2일)이므로 그대로 켜기 전에 한도와 조회 전략을 맞춰야 한다.
검수 도구 포함 Python **509개**, compileall·[CI 42478856096](https://github.com/parkgogon/sfety_map/actions/runs/42478856096) 통과.

이후 사용자에게 일일 한도 **500회**를 확인해 조회 전략과 공통 상한을 변경했다.
최신 설정/검증은 [500회 대응 증빙](../message-feed-500-limit/README.md)을 따른다. 위 2,880회는 변경 전의 계획 수치다.
