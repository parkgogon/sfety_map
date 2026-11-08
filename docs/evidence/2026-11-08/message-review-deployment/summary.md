# 재난문자 운영 연결 메타데이터 점검

확인 시각: 2026-11-08T01:43:20.979785+00:00
메타데이터 조회: 일부 미확인

이 보고서는 설정 존재만 확인합니다. 실제 키 사용·저장 성공·지도 동작 검증을 대신하지 않습니다.

| 서버 환경변수 | 연결 방식 | Secret 버전 | 권한 단서 |
| --- | --- | --- | --- |
| OPENAI_API_KEY | missing | unverified | unverified |
| KAKAO_REST_API_KEY | missing | unverified | unverified |
| SAFETY_DATA_API_KEY | missing | unverified | unverified |

## 확인할 설정

- `firestore_metadata_permission_denied`
- `project_iam_metadata_unavailable`
- `OPENAI_API_KEY_binding_missing`
- `OPENAI_API_KEY_version_unverified`
- `OPENAI_API_KEY_iam_unverified`
- `KAKAO_REST_API_KEY_binding_missing`
- `KAKAO_REST_API_KEY_version_unverified`
- `KAKAO_REST_API_KEY_iam_unverified`
- `SAFETY_DATA_API_KEY_binding_missing`
- `SAFETY_DATA_API_KEY_version_unverified`
- `SAFETY_DATA_API_KEY_iam_unverified`

## 남은 실제 검증

- `runtime_secret_access`
- `firestore_transaction_and_history`
- `official_api_response_and_terms`
- `real_kakao_sdk_on_message_screen`
- `mobile_device`

비밀값·문자 내용·전화번호·원본 오류는 보고서에 포함하지 않습니다. 배포·발송·유료 API 호출을 실행하지 않습니다.
