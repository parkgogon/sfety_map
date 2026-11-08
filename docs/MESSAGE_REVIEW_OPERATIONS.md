# 재난문자 운영 연결 준비

2026-11-08 KST, 기능 브랜치 `feature/disaster-message-ai`. 1~4단계는 로컬 검증을 마쳤으며 미배포다.
이 문서는 운영 서버의 연결 준비와 실제 동작 검증을 구분한다.

## 현재 배포 경로에서 확인한 차이

- 점검 시작 기준 `d8f7451`의 `ci-deploy.yml` Cloud Run `--set-secrets` 목록에 `OPENAI_API_KEY`, `KAKAO_REST_API_KEY`,
  `SAFETY_DATA_API_KEY`가 없다. GitHub Actions의 같은 이름 secret은 평가용 실행에만 전달된다.
  GitHub에 등록한 키가 Cloud Run에 자동 전달되는 구성은 아니다.
- 웹 지도는 기존 `KAKAO_MAP_APP_KEY` → `VITE_KAKAO_MAP_APP_KEY` 빌드 경로를 사용한다.
  이 JavaScript 키는 서버의 카카오 REST API 키와 다르다.
- 운영 저장은 서버 프로젝트 ID와 기본 `MESSAGE_REVIEW_STORE=firestore`로 선택한다.
  설정 존재가 실제 데이터베이스 접근·트랜잭션 성공을 의미하지 않는다.
- PR에 선택적으로 켜는 연결 설정을 준비했다. 기본값은 AI/공식 피드 모두 꺼짐이며, 운영 키·IAM·변수·Worker/Scheduler는 변경하지 않았다.

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

## 2026-11-08 실제 메타데이터 점검 결과

[실행 42435450742](https://github.com/parkgogon/sfety_map/actions/runs/42435450742),
[원본 보고서](evidence/2026-11-08/message-review-deployment/report.json).
Cloud Run 조회는 성공했고 `Ready=True`, 운영 소스 `616d7a2f...`를 확인했다.
세 서버 API 키의 환경변수 연결은 모두 없다. 키의 Secret Manager 존재 여부와 구분한다.

Firestore 데이터베이스·Secret 버전·Secret IAM 조회는 `permission_denied`, 프로젝트 IAM도 조회하지 못했다.
현재 점검 계정으로는 Native 모드/키 존재/권한을 확정할 수 없다. 이를 키/DB가 없다는 판단으로 바꾸지 않는다.
워크플로는 **부분 미확인을 종료 1로 보고해 실패 상태**다. 앱 회귀 테스트 실패가 아니며
같은 소스의 일반 CI `42435443467`은 성공했다. 같은 권한으로 재시도할 이유는 없다.

공식 [긴급재난문자 상세 페이지](https://www.safetydata.go.kr/disaster-data/view?dataSn=228)는 HTTP 200으로 읽었다.
공통 이용안내에서 API 이용신청과 공공기관 제공 자료의 공공누리 제3유형 안내를 확인했다.
이는 해당 키의 이용 승인·AI 분석/보관/재제공 조건까지 확인했다는 뜻이 아니다. 신청 계정에서 별도 확인한다.

### 사용자 Cloud Shell 캡처로 추가 확인

2026-11-08 사용자가 제공한 소유자 계정의 Cloud Shell 화면에서 기본 DB는 `FIRESTORE_NATIVE`,
`OPENAI_API_KEY`와 `KAKAO_REST_API_KEY`의 Secret 조회는 각각 `NOT_FOUND`임을 확인했다.
앞선 Actions 계정의 조회 거부와 구분한다. 두 Secret은 아직 생성되지 않았고, DB의 Native 모드만 확인한 것이다.
runtime의 문서 읽기/쓰기·버전 이력/권한은 검증하지 않았다. 공식 피드 Secret도 이 캡처에서는 조회하지 않았다.

GitHub Actions에 보관한 기존 키는 [키 등록 준비 절차](MESSAGE_REVIEW_KEY_SETUP.md)에 따라 전달할 수 있도록 도구를 준비했다.
추가 사용자 캡처로 배포 계정 `github-deployer`, API 실행 계정 `safety-dashboard-runtime`을 확인했다.
사용자 캡처로 두 Secret 생성·권한 준비와 만료 `2026-11-08 03:39:23 UTC`를 확인했다.
키 값을 채팅으로 받거나 새 키를 발급하지 않고 기존 GitHub 두 값을 등록했다.
사용자의 명시적 승인 후 실행 `42439928442`에서 두 Secret 모두 **버전 1** 생성을 확인했다.
[등록 증빙](evidence/2026-11-08/message-key-copy/README.md). 실제 Cloud Run 키 참조는 아직 적용하지 않았다.

### 소유자 계정으로 다음에 확인할 최소 명령

GCP Cloud Shell의 프로젝트 권한이 있는 계정에서 다음을 실행한다. Secret **값은 출력하지 않는다**.
현재 Actions 점검 계정의 IAM을 임의로 넓히는 대신 소유자의 기존 권한으로 확인할 수 있다.

```bash
gcloud firestore databases describe --project=keco-safety-map --database='(default)' --format='value(type)'
gcloud secrets describe OPENAI_API_KEY --project=keco-safety-map --format='value(name)'
gcloud secrets describe KAKAO_REST_API_KEY --project=keco-safety-map --format='value(name)'
```

키가 이미 있으면 승인할 버전과 runtime 접근을 확인한다. 없다면 기존에 준비한 키를 Secret Manager에 등록할 단계다.
위 명령은 키 등록/권한 부여/배포를 실행하지 않는다. 공식 피드는 별도 키/이용신청 이후 연결할 수 있다.

## 준비한 배포 설정 (실행 전)

[설정 생성기](../scripts/build_message_review_deploy_config.py)는 비밀값을 읽거나 GCP에 접속하지 않고
기존 API 배포의 secret 목록에 추가할 참조만 만든다. 이미지 빌드 전에 설정을 검사한다.
기존 KMA/관리자/알림 참조는 유지하고 API 작업에만 적용한다. Worker/웹에는 서버 키를 전달하지 않는다.

| GitHub Repository variable | 기본값 | 켤 때 설정 |
| --- | --- | --- |
| `MESSAGE_REVIEW_AI_ENABLED` | `false` | 키/권한 검증 후 `true` |
| `MESSAGE_REVIEW_OPENAI_VERSION` | 비어 있음 | 등록 결과 `1` |
| `MESSAGE_REVIEW_KAKAO_VERSION` | 비어 있음 | 등록 결과 `1` |
| `MESSAGE_REVIEW_FEED_ENABLED` | `false` | 공식 키·응답·이용 조건 확인 후 `true` |
| `MESSAGE_REVIEW_FEED_VERSION` | 비어 있음 | 공식 피드 Secret Manager의 승인한 숫자 버전 |

켜진 기능의 버전이 없거나 `latest`/잘못된 값이면 배포 준비를 중단한다.
AI를 켜면 평가 모델/low를 설정하고 저장은 `firestore`로 명시한다. 기본값에서 유료 서비스 키를 연결하지 않는다.
이 변수들을 실제 GitHub에 등록하거나 운영에 적용하지 않았다. main 병합/배포 요청과 검토가 필요하다.

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

1. 두 API Secret은 버전 1 등록을 완료했다. runtime 접근의 실제 동작과 누락 연결을 확인한다.
   GitHub secret의 값을 채팅·로그로 가져오지 않는다. 기존 키를 새로 발급할 필요가 있는지부터 단정하지 않는다.
2. 사용자 준비 스크립트의 두 Secret runtime 읽기 권한과 등록 버전 1을 사용한다. 재등록은 필요하지 않다.
   배포에 사용할 secret 이름/고정 버전, 모델 `gpt-5.4-mini-2026-03-17`·reasoning `low`,
   `MESSAGE_REVIEW_STORE=firestore`를 검토 가능한 변경으로 준비한다.
3. PR에 준비한 선택적 `--set-secrets` 연결과 승인한 버전 변수를 사용해야 이후 배포에도 연결이 유지된다.
   기존 KMA/관리자/알림 secret을 누락하지 않는다. 키를 웹 번들에 넣지 않는다.
4. main 병합/배포는 별도 사용자 요청 때 실행한다. 현재 API 리비전/환경과 Hosting 소스,
   복구할 이전 리비전을 기록한 뒤 진행한다. Worker/Scheduler 시험 실행은 하지 않는다.
5. 관리자 화면의 실제 연결/창작 검수와 새로고침을 확인한다. 자동 복사와 실제 발송은 구분하고
   발송 없이 검수한다. 실패하면 실패를 남기고 키 존재·저장 성공·실제 운영 검증을 혼동하지 않는다.
