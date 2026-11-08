# 재난문자 운영 배포·창작 검수 — 2026-11-08 KST

운영 앱 소스는 `43b40e0aee7c9f548ef4d633158c2001c2c86a8d`다.
사용자가 main 병합/운영 배포와 후속 검수를 명시적으로 승인한 후 [PR #1](https://github.com/parkgogon/sfety_map/pull/1)을 squash merge했다.
배포 후 검수 도구/문서는 `[skip ci]` 커밋으로 보완했으며 운영 앱 이미지/웹 버전과 구분한다.

## 배포와 복구 기준

| 작업 | Actions 실행 | 결과 |
| --- | --- | --- |
| 배포 전 리비전/Hosting 기록 | [42443443848](https://github.com/parkgogon/sfety_map/actions/runs/42443443848) | 성공, before-baseline.json |
| main 테스트·API/Worker/Scheduler·웹·외부 감시 적용 | [42443589707](https://github.com/parkgogon/sfety_map/actions/runs/42443589707) | 모두 성공 |
| 배포 후 리비전/Hosting 조회 | [42454331719](https://github.com/parkgogon/sfety_map/actions/runs/42454331719) | 성공, after-deploy-baseline.json |
| 창작 기록 최종 브라우저 검수 | [42455143090](https://github.com/parkgogon/sfety_map/actions/runs/42455143090) | 성공, verification.json |
| Worker 동일 설정 재기동 | [42455222467](https://github.com/parkgogon/sfety_map/actions/runs/42455222467) | 성공, worker-refresh.json |

API는 `safety-dashboard-api-00088-b7t`, Hosting 버전은 `208642a1dcee0450`이다.
Worker는 최초 `00075-58q` 배포 후 KMA 연결 오류가 이어져 아래 동일 이미지 재기동으로 복구했다.
두 서버 키는 Secret Manager 버전 1을 참조하며 저장은 Firestore다.
키 등록의 별도 원본 증빙은 [message-key-copy](../message-key-copy/README.md)에 있다.

## 실제 운영 브라우저 검수

[검수 기록 열기](https://keco-safety-map.web.app/control/messages?record_id=manual-44013dfc139140e882c5c9af012ddd5b).
기존 관리자 로그인이 필요하다. 원문은 창작 예문이고 출처는 `운영 배포 검수 · 창작 예문`이다.

- 관리자 로그인·Firestore 저장소와 AI/장소 검색 설정·정적 웹 소스 SHA를 확인했다.
- 창작 사고 예문을 등록하고 실제 OpenAI/Kakao 분석 결과를 저장했다. 저장된 모델 호출은 **3회**다.
- 후보 기준점 확인, CSV의 실제 시설 **1개** 선정/사유, 내부 검토 완료와 근거 기반 초안 생성을 수행했다.
- 새로고침 후 완료 상태/선정/초안 복구와 서버의 현재 초안 판정을 확인했다.
- 초안 복사 후 검수 브라우저 클립보드 내용이 저장된 초안과 같은지 확인했다.
- 실제 SDK/지도 타일 **24개 HTTP 200**, DOM에서 로드된 지도 이미지 **9개**를 확인했다.
- PC 1440×1050과 모바일 390×844에서 지도·한글·가로 넘침을 확인했다.
  [desktop.jpg](desktop.jpg), [mobile.jpg](mobile.jpg)는 실제 운영 화면이다. 모바일은 viewport 에뮬레이션이다.
- 페이지 오류·예상 밖 요청 **0건**이다. 공개 로그인 화면은 1440/390/360px,
  무인증 보호 API는 **403 + private/no-store**도 확인했다(public-browser.json).

최종 검수는 저장된 같은 기록을 재사용하여 `analysis_requests=0`이다.
첫 비공개 브라우저 실행 [42454723413](https://github.com/parkgogon/sfety_map/actions/runs/42454723413)에서
등록/분석/선정/완료/복구/복사까지 진행했지만 마지막 지도 계측에서 실패했다(initial-browser-failure.json).
검수 도구가 예전 `map*.daumcdn.net/map_2d...` 주소만 세고 있었으며 실제 새 타일은
`mts.kakaocdn.net/api/v1/tile/...`였다. 실제 공개 지도 요청으로 대조하고 계측을 수정한 뒤 전체를 통과했다.
검수 컨테이너의 한글 폰트도 앱에 동봉된 NotoSansKR을 읽도록 보완했다. 운영 앱 UI 결함으로 집계하지 않는다.

이전 첫 Job 실행 [42444039882](https://github.com/parkgogon/sfety_map/actions/runs/42444039882)은 실패했고
CLI가 빈 execution.json을 남겼다. 별도 회수 [42454328555](https://github.com/parkgogon/sfety_map/actions/runs/42454328555)도
실행 계정의 로그 열람 권한 때문에 내부 원인을 확인하지 못했다(initial-job-evidence-unavailable.json).
이후 IAM 비공개 임시 서비스에서 허용한 결과만 직접 반환하도록 바꾸었다.
관리자 비밀번호는 GCP 실행 안에서만 사용했고 임시 Job/서비스는 각 실행 후 삭제했다.
위 모델 3회는 확인된 저장 기록의 수치이며 로그를 읽지 못한 초기 Job의 전체 사용량을 단정하지 않는다.

## Worker 기상 연계 복구

배포 전 12:11 KST의 공개 상태는 KMA LIVE였고 배포 후 12:45부터 Worker에서 KMA_ROUTE 오류가 이어졌다.
15:32 검수에서 34회 연속 오류·마지막 성공 12:40을 확인했다(verification.json의 operations).
같은 시각 API의 일반 공개 특보 조회는 LIVE였다(monitoring.json).

Worker 이미지는 `worker:43b40e0...`를 유지하고 새 리비전
`safety-alert-worker-net-refresh-20261108063331`을 생성해 100% 적용했다.
전후 **전체 runtime spec 동일**을 확인했다. 이미지·Secret 참조·CPU/메모리·실행 계정·환경변수는 보존했다.
자동알림 기준 상태/실적 저장소와 위험도 정책은 변경하지 않았다.
**15:35 KST 원래 5분 Scheduler 실행 후 KMA LIVE**, Worker 최근 21초·health 2종 HTTP 200을 확인했다(health.json).
15:40 KST 다음 정규 실행에서도 KMA LIVE·Worker 최근 34초·HTTP 200을 재확인했다(health-followup.json).
정확한 이전 인스턴스의 연결 실패 원인과 장기 재발 여부는 미확정이다.

## 검증과 범위

배포 CI는 Python 423개·React 255개·컴파일·데이터·웹 빌드를 통과했다.
검수/복구 도구 보완 후 Python 전체 **429개**(실제 외부 HTTP/TCP 시도 0건)와 compileall·시설 195개 검증을 통과했다.

본 검수의 실제 Telegram/SMS·dispatch·Worker 시험 호출은 **0건**이다.
기존 자동감시의 정상 업무 알림 수치를 뜻하지 않는다. 복사는 발송/수신 실적이 아니며 내부 검토 완료는 현장 확인이 아니다.
대표점 참고 반경은 위험 반경이 아니다. 창작 1건을 일반 정확도·실제 피해 예방 실적으로 확대하지 않는다.
공식 SafetyData 피드 키/실제 응답·실기기 조작·장기 부하 검증은 남아 있다.

이 디렉터리는 허용한 운영 메타데이터·창작 화면과 실패/성공 구분만 보관한다.
비밀번호·API 키·관리자 세션/ID 토큰·개인 연락처는 포함하지 않는다.
