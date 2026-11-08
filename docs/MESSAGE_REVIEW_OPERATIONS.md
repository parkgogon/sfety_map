# 재난문자 운영 연결 준비

2026-11-08 KST, 기능 브랜치 `feature/disaster-message-ai`. 1~4단계는 로컬 검증을 마쳤으며 미배포다.
이 문서는 운영 서버의 연결 준비와 실제 동작 검증을 구분한다.

## 현재 배포 경로에서 확인한 차이

- `ci-deploy.yml`의 Cloud Run `--set-secrets` 목록에 `OPENAI_API_KEY`, `KAKAO_REST_API_KEY`,
  `SAFETY_DATA_API_KEY`가 없다. GitHub Actions의 같은 이름 secret은 평가용 실행에만 전달된다.
  GitHub에 등록한 키가 Cloud Run에 자동 전달되는 구성은 아니다.
- 웹 지도는 기존 `KAKAO_MAP_APP_KEY` → `VITE_KAKAO_MAP_APP_KEY` 빌드 경로를 사용한다.
  이 JavaScript 키는 서버의 카카오 REST API 키와 다르다.
- 운영 저장은 서버 프로젝트 ID와 기본 `MESSAGE_REVIEW_STORE=firestore`로 선택한다.
  설정 존재가 실제 데이터베이스 접근·트랜잭션 성공을 의미하지 않는다.
- 이 단계는 기존 CI 배포 명령·운영 키·IAM·Worker/Scheduler를 변경하지 않는다.

## 읽기 전용 점검

[점검 워크플로](../.github/workflows/check-message-review-deployment.yml)는 수동 실행하거나
동일 저장소 PR에 `message-review-preflight` 라벨을 추가할 때만 실행한다.
일반 push/PR 갱신과 `ai-evaluation` 라벨로는 시작하지 않는다. Fork PR에는 실행하지 않는다.
기존 배포용 `GCP_WORKLOAD_IDENTITY_PROVIDER`·`GCP_SERVICE_ACCOUNT` 인증과 `GCP_PROJECT_ID` 변수를 사용한다.

[점검 스크립트](../scripts/check_message_review_deployment.py)는 다음 **메타데이터만** 읽는다.

- 서울 리전 `safety-dashboard-api`의 Ready·소스 버전, 필요한 환경변수/secret 참조 존재.
- 기본 Firestore 데이터베이스의 Native 모드와 프로젝트 IAM의 알려진 허용 역할 단서.
- 세 API secret의 연결 버전 상태와 secret/project IAM의 runtime 서비스 계정 허용 역할 단서.

Secret의 값·Firestore 문서/문자·연락처는 읽지 않으며 실제 API/SDK·발송·배포를 호출하지 않는다.
Cloud Run의 전체 환경설정과 IAM 원본은 메모리에서 필요한 필드만 골라 쓰고 보고서에 보관하지 않는다.
요청별 25초/자동 재시도 없음, 최대 3개 동시 메타데이터 요청이다. 출력은 `report.json`, `summary.md` 두 파일이다.
보고서는 7일 GitHub artifact와 Actions 요약에 남는다. 조회 권한 부족은 미확인으로 표시한다.

프로젝트를 조회할 자격이 있는 Cloud Shell에서는 다음 명령으로도 실행할 수 있다.

```bash
python scripts/check_message_review_deployment.py \
  --project keco-safety-map \
  --output-dir output/message-review-deployment
```

`audit_complete`와 종료 0은 메타데이터 조회 완료를 뜻하며 설정 완비나 서비스 준비 완료라는 뜻이 아니다.
`findings`와 각 항목을 함께 본다. 키가 없거나 연결이 빠져도 사실을 보고한 정상 점검일 수 있다.
조회 실패는 종료 1, 프로젝트 입력 오류는 종료 2다. IAM 허용 역할 발견은 실제 권한 검증이 아니다.
조건부/custom 역할·그룹·deny 정책 등을 평가하지 않아 `unverified`를 권한 없음으로 단정하지 않는다.

## 운영 적용 전에 순서대로 확인할 것

| 대상 | 필요한 설정/검증 | 통과 근거 |
| --- | --- | --- |
| OpenAI 수동 분석 | Secret Manager 키, runtime 접근, Cloud Run 참조, 평가 모델/low 설정 | 설정 점검 후 창작 입력 1건의 제한된 실제 연결 검증 |
| 카카오 장소 검색 | 서버 REST 키, runtime 접근/참조, Local API 사용 설정 | 원문 지역·역할에 맞는 검색과 CSV 시설 대조 |
| 지도 | 기존 JavaScript 키, 실제 서비스 도메인 등록 | 새 재난문자 지도 화면에서 실제 SDK·타일·기준점 이동/복구 |
| 검토 저장 | Native Firestore, runtime 데이터 읽기/쓰기 권한 | 별도 창작 검수 기록의 저장·버전 이력·충돌·새로고침 복구 |
| 공식 피드 | SafetyData 별도 발급/승인 키, API 응답·조회 범위·이용/보관 조건 | 관리자 지역/하루/페이지 조회와 ID·본문·발행·수신지역 대조 |

공식 피드 키가 준비되지 않아도 공개 문자 수동 입력과 창작 시연을 먼저 운영 적용할 수 있다.
미설정 피드는 화면에서 준비 중으로 표시한다. 공식 자동 수집·상황전파·현장 회신은 이번 범위가 아니다.
공개 문자 보관 기간·관리자 접근 범위·외부 AI 전송 대상은 실제 운영 전 기관 기준으로 확정한다.

## 적용 변경을 준비할 때

1. 점검 결과로 Secret Manager의 존재/버전·runtime 권한과 누락 연결을 확정한다.
   GitHub secret의 값을 채팅·로그로 가져오지 않는다. 기존 키를 새로 발급할 필요가 있는지부터 단정하지 않는다.
2. 사용자 승인 후 Secret Manager에 필요한 값/버전을 등록하고 runtime에 최소 접근을 부여한다.
   배포에 사용할 secret 이름/고정 버전, 모델 `gpt-5.4-mini-2026-03-17`·reasoning `low`,
   `MESSAGE_REVIEW_STORE=firestore`를 검토 가능한 변경으로 준비한다.
3. `ci-deploy.yml`의 `--set-secrets` 목록에도 해당 연결을 반영해야 이후 배포에서 사라지지 않는다.
   기존 KMA/관리자/알림 secret을 누락하지 않는다. 키를 웹 번들에 넣지 않는다.
4. main 병합/배포는 별도 사용자 요청 때 실행한다. 현재 API 리비전/환경과 Hosting 소스,
   복구할 이전 리비전을 기록한 뒤 진행한다. Worker/Scheduler 시험 실행은 하지 않는다.
5. 관리자 화면의 실제 연결/창작 검수와 새로고침을 확인한다. 자동 복사와 실제 발송은 구분하고
   발송 없이 검수한다. 실패하면 실패를 남기고 키 존재·저장 성공·실제 운영 검증을 혼동하지 않는다.
