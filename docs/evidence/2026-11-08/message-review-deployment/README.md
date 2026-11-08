# 재난문자 운영 연결 준비 점검

2026-11-08 10:43 KST, 코드 `d8f7451`, 프로젝트 `keco-safety-map`.
[원본 보고서](report.json), [원본 요약](summary.md), [실행 근거](run.json).
[실제 점검](https://github.com/parkgogon/sfety_map/actions/runs/42435450742)은 **부분 미확인으로 실패**다.
이는 실제 연결 준비 완료나 앱 테스트 실패를 의미하지 않는다.

## 확인한 사실

- 기존 Actions GCP 인증으로 Cloud Run 메타데이터 조회 성공. `Ready=True`, 운영 소스 `616d7a2f...`다.
  이는 프로세스 설정 상태이며 KMA/현장/관제 전체 동작 검증은 아니다.
- Cloud Run에 OpenAI·카카오 REST·SafetyData 키 환경변수 연결이 없다.
  Secret Manager의 키 자체 존재 여부와 혼동하지 않는다.
- Firestore DB·Secret 버전/권한 조회는 권한 부족, 프로젝트 IAM도 조회하지 못했다.
  현재 계정으로 Native 모드·키의 존재/버전·runtime 접근을 확인할 수 없다.
- 같은 코드의 [일반 CI 42435443467](https://github.com/parkgogon/sfety_map/actions/runs/42435443467)은 성공했다.
  Python 403개·React 255개·시설/컴파일/웹 빌드 검사 통과, 배포 작업은 건너뛰었다.
- 공식 재난문자 상세 페이지는 별도 공개 HTTP 200으로 읽었다. API 이용신청과 공통 이용허락 안내는 확인했고,
  신청 계정의 승인·AI 분석/보관/재제공 조건은 아직 미확인이다.

점검에서 Secret 값과 Firestore 문서를 읽거나 쓰지 않았다. 유료 AI/장소 검색·공식 피드 호출·발송·배포 0건이다.
원본 전체 Cloud Run 환경이나 IAM 정책·원본 오류는 증빙에 포함하지 않았다.
GitHub 설정 목록은 현재 연동 권한에서 403이므로 Actions secret 존재를 새로 검증했다고 주장하지 않는다.

## 준비한 변경과 남은 일

[운영 준비 문서](../../../MESSAGE_REVIEW_OPERATIONS.md)에 소유자 Cloud Shell의 읽기 전용 확인 명령과
필요 설정/실제 검증 순서를 기록했다. PR에는 AI/공식 피드를 별도로 켜고 승인한 숫자 Secret 버전을
검증하는 API 배포 설정을 준비했다. 기본 꺼짐, 모델/low 고정, 운영 저장 firestore, 기존 알림 참조 유지다.
실제 GitHub 변수·키·권한을 변경하지 않았다. 버전 미지정/주입·오류를 포함한 추가 검사를 합쳐
최종 로컬 Python **409개**가 통과했다. 앱/화면 코드 변경은 없다.

다음 작업은 소유자 권한으로 DB/두 Secret의 존재·승인 버전·runtime 접근을 확인하는 것이다.
추가 권한을 임의로 부여하거나 같은 계정으로 점검을 반복하지 않는다. main/운영 적용은 별도 요청 때 수행한다.
