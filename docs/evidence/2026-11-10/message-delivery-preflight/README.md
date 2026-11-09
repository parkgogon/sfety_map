# 자동전파 운영 전 점검 — 2026-11-10 KST

운영 앱은 `5f58be1d12a8ac57c0ec365e4eeb86b392fc348c` 그대로다. 기능 브랜치에서만 검증한다.

- [기준 조회](https://github.com/parkgogon/sfety_map/actions/runs/42646979204): 기존 API/KMA/Hosting 일치.
- [기존 연결 메타데이터](https://github.com/parkgogon/sfety_map/actions/runs/42646972888): 서비스 Ready/키 참조 있음. Secret 버전·IAM/Firestore 설정 조회 권한 부족으로 incomplete. 키가 없거나 런타임 사용이 실패했다는 뜻이 아니다.
- [읽기 전용 상태](https://github.com/parkgogon/sfety_map/actions/runs/42648004407): 로그인 뒤 수집 ERROR를 관측해 검수 실패. 기준/예약 검사와 임시 서버 삭제는 성공. 원문·공식 ID·키 값은 내보내지 않았다.
- 공개 `/api/v1/health/operations`: 00:46 KST `ready`, KMA LIVE, 마지막 정규 감시 00:45 KST.

`status-before.json`은 00:45 KST 문자 수집 오류, 마지막 전체 정상 11월 9일 08:00 KST, 남은 파티션 3을 보여준다. 운영 수집/분석을 수동 실행하거나 기준 상태를 초기화하지 않았다. 실제 시험 발송은 0건이다. 임시 검수 서비스 생성/삭제는 운영 앱 배포와 구분한다.

## 실제 점검 결과

- [기능 브랜치 CI](https://github.com/parkgogon/sfety_map/actions/runs/42648802413) 성공: Python 664/React 279, 빌드·CSV·컴파일. PR이므로 배포 job은 실행하지 않았다. 이후 메타데이터/평가 보완 관련 검사 45개도 통과했다.
- [확장 메타데이터](https://github.com/parkgogon/sfety_map/actions/runs/42649023753): 기존 서비스 3개/예약 3개는 그대로다. 봇은 버전 1, 직원방/관리자방은 latest 참조다. 버전 1이라고 추정하지 않는다. Secret/Firestore 메타데이터 조회는 권한 부족으로 미확인이다.
- [공식 API](https://github.com/parkgogon/sfety_map/actions/runs/42649030373): 5회, 기록/모델/발송 0. 당일은 비었으며 전일 소표본 두 페이지는 날짜/지역/ID 분리/head 안정성은 맞고 발행 시각 내림차순은 아니었다. `latest_order_verified=false`. 실제 공개 지연은 미측정이다.
- [실제 AI 평가](https://github.com/parkgogon/sfety_map/actions/runs/42649017948): 창작 6건/23 Responses, 표준 요금 기준 정산 $0.04697715, 미정산 예약 0, 실행 상한 $1. 계정 청구는 Usage와 대조한다. 처음 부분 검사 4통과/1확인/1실패였으나 서버 검증까지 포함한 재평가는 **2통과/3확인/1실패**다.

| 예문 | 실제 결과/보완점 | 서버 재현 |
| --- | --- | --- |
| 예방 | 기록만 판단 | record_only |
| 화재 | 적합한 장소/주변 조회 | notify_ready |
| 예정 통제 | 6응답 내 완료 실패 | 분석 불가 |
| 일부 해제 | 해제 지점의 부적합/범위 미상 후보를 basis로 사용 | attention_required |
| 지역 미상 | 근거 없는 notify | attention_required |
| 산불/대피소 | 대피 목적지를 basis에 포함 | attention_required |

실제 모델 응답은 `ai-original-results.json`, 당시 요약은 `ai-original-summary.md`에 보존했다.
보완한 평가기로 네트워크를 차단해 재검사한 결과는 `ai-rechecked/`다. 다음으로 재현한다.

```bash
.venv/bin/python docs/evidence/2026-11-10/message-delivery-preflight/check_ai_results.py
```

재평가 추가 API 0. 각 예문의 발행 시각+1분을 기준으로 저장된 결과의 근거만 검사하며 origin은 example로 유지한다.
실제 현재 상황·모델 전체 정확도·실제 전달 실적으로 해석하지 않는다. 잘못된 notify를 서버가 차단하는 것은 확인했지만, 정상 자동전파의 품질은 아직 충분하지 않다.

## 다음 작업 수용 조건

1. 운영 수집 ERROR의 발생 지점을 읽기 전용으로 좁힌다. 원문/한도/진행 지점/시작 시각을 초기화하지 않는다.
2. 정렬이 없고 첫 페이지가 그대로여도 뒤 페이지의 새 자료를 놓치지 않는 수집을 450회/최근 24시간 안에서 검증한다. 당일 첫 페이지만 조회한 결과를 최신 전체 수집으로 표시하지 않는다.
3. 예정 통제의 반복 조회, 지역 미상의 판단, 해제 구간·대피 목적지의 근거 연결을 보완하고 동일 6예문을 제한 비용으로 재평가한다. 실패를 없애려고 검사 조건을 완화하지 않는다.

고정 숫자 버전은 소유자의 Cloud Shell에서 `scripts/check_message_review_deployment.py --project keco-safety-map --delivery --output-dir /tmp/message-delivery-audit`로 읽을 수 있다. 도구는 Secret payload나 문서를 읽거나 IAM을 변경하지 않는다. 키 재발급/재등록은 필요 없다.

위 보완 전에는 `MESSAGE_COLLECTION_FAST_ENABLED`·새 자동전파를 활성화하지 않는다. Draft PR #4는 검토용이며 main/운영에 반영하지 않았다.
