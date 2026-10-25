# 운영 배포·직접 검수 — 2026-10-25 KST

**main 병합·자동 배포 성공. UI·지도 포함 PDF는 확인했으나, 실황 기상 격자는 조회 실패가 남는다.**
기능 브랜치 최종 검토 `51672b1`을 main `616d7a2`로 병합했다. 충돌이 없고 병합 tree는 검토한 기능 브랜치와 같다.
기존 원본/점검/기능 작업공간을 보존하고 별도 main 작업트리에서 진행했다.

## 배포 확인

[GitHub Actions 40160348628](https://github.com/parkgogon/sfety_map/actions/runs/40160348628), [배포 요약](deployment.json).
main push로 실행했으며 수동 workflow dispatch는 하지 않았다. 2026-10-25 13:06:57 KST 전체 성공이다.

| 작업 | 확인 |
|---|---|
| test | Python 256개·외부 HTTP/TCP 0, React 215개·데이터/컴파일/빌드 통과 |
| deploy-api | API `safety-dashboard-api-00086-zn7`, 1 CPU/1GiB, 트래픽 100% |
| Worker 배포 | `safety-alert-worker-00074-47k`, 별도 브라우저 없는 이미지·기존 1 CPU/512Mi, 트래픽 100% |
| deploy-web | Firebase Hosting 성공, 실제 관제 표시 `v616d7a2` |
| configure-uptime-monitoring | 기존 공개 업타임 체크/알림 설정 성공 |

운영 사이트를 13:06~13:19 KST에 직접 조작했다. 연결된 개인 브라우저 도구가 없어 클라우드 Chromium을 사용했다.
**정적 앱·SDK·업무 API 응답 대체, 가짜 SDK/API, 외부 기상 주입은 하지 않았다.** 모바일은 viewport/DPR 에뮬레이션이다.
환경 [revision 23/current/enforced](network-policy.json), HTTPS 프록시·CA 신뢰·TLS 검증을 유지했다.

## 확인 — 실제 운영 UI·지도·PDF

- `/`, `/control`, `/settings`, `/report-map.html` 모두 200·HTML no-store이며 지도 엔트리와 해시 assets의 200/immutable·계약 버전 1을 확인했다.
  [정적 페이지](static-checks.json). API 먼저 반영됐던 전환 구간에는 지도 URL이 이전 SPA를 반환했으며 웹 배포 후 전용 페이지로 바뀌었다.
- 관제/설정 360/390/430/700/1440px의 가로 넘침 0, 새로고침 아이콘 색과 로그인 버튼 줄바꿈/너비를 확인했다.
  [기록](layout-checks.json), [관제 360px](control-layout-360.png), [설정 390px](settings-layout-390.png).
  관리자 비밀번호를 입력하거나 보호된 기능을 호출하지 않았다.
- 모바일 지도 설정 360/390/430/700px: 중복 ‘지도 보기’ 없음, 시설 수 유지, 필터 즉시 195→140개 반영,
  전체 표시 복구·Escape/상단 X/바깥 닫기·포커스 복원을 확인했다. [390px](settings-390.png), [추가 기록](mobile-settings-checks.json).
- 실제 장소 검색 후보에서 동인청사 인근을 지정하고, 도로 위 기준점·1/3/5km 원·인근 시설 선택·직선거리 연결선·마커를 확인했다.
  [거리 원](reference-rings.png), [연결선](reference-connection.png), [이동·줌 복귀](reference-moved-zoomed.png), [측정](geometry-checks.json).
  선택 시설의 거리는 이동/확대 복귀 전후 1.9km로 유지됐다. 지리/측량 정확도의 전수 검증은 아니다.
- 현장 PC/모바일·관제에서 실제 PDF를 다운로드했다. 세 응답 모두 3개소·같은 대상 digest·`X-Nearby-Map-Status: captured`였다.
  중복 form 제출에도 요청 1건, 완료 안내·Escape 닫기/포커스를 확인했다.
  [현장 기록](browser-field-checks.json), [관제 기록](browser-control-checks.json).
- [현장 PC PDF](field-1440.pdf), [현장 모바일 PDF](field-390.pdf), [관제 PDF](control-1440.pdf)와
  [0개소 PDF](zero-production.pdf)를 실제 렌더해 직접 검토했다. [대표 페이지](field-1440-page1.png), [0개소 페이지](zero-production-page1.png).
  도로·기준점·반경·번호·북쪽·카카오 로고/축척, KST·요약·목록·집계·한글 줄바꿈과 연락처 미노출을 확인했다. [PDF 검사](pdf-checks.json).
- 0개소 API PDF는 7.335초, 지도 `captured`·대상 digest 일치·no-store였다. 생성 중 공개 health 4건 모두 200(313~437ms)이었다.
  [측정](zero-report-check.json). 프록시 왕복을 포함한 짧은 표본이며 Cloud Run 전체 성능/부하 검증은 아니다.
- 기록한 브라우저의 SDK/지도/검색 응답 874건 모두 200이다. 페이지 오류·요청 가드 차단 0건.
  타일 `ERR_ABORTED` 135건과 시설 기상 GET 취소 1건은 이동·페이지 종료 취소로 구분했다.
  [요청 요약](network-summary.json). 추가 허용이 필요한 SDK 실패 호스트는 없다.

## 실패 — 실황 기상 격자

운영 바람·기온·강수 API는 HTTP 200이지만 상태 **`ERROR`·0점**, 상세는 **“기상청 격자 위치를 확인하지 못했습니다.”**다.
13:15~13:16 KST 재확인에서도 같았다. [상태/시각/응답 시간](weather-status-checks.json), [실제 오류 표시](field-wind-1440.png).
특보의 `KMA 정상`/LIVE와 별도 경로다. 오류를 무풍·무강수나 안전으로 해석하지 않았다. 주변 시설 보고서는 기상과 독립적으로 정상 생성됐다.

코드상 `GridWeatherLayerProvider._coordinate_data()`의 HTTP·파싱 오류가 이 상세로 묶인다.
대상은 `apihub.kma.go.kr/api/typ01/cgi-bin/url/nph-dfs_latlon_api`다. 이 관리 환경에서 해당 좌표 API를 읽기 전용으로
확인했을 때는 HTTP 200·37,697값·4.204초였다. [별도 원본 확인](weather-source-check.json).
이는 **운영 Cloud Run의 성공이나 실패 원인을 입증한 결과가 아니다.** 운영 로그·실제 출구 경로·서비스 권한의 대조가 필요하다.
새 환경 허용 도메인 문제로 단정하거나 프록시/TLS를 우회하지 않았다.

## 별도 확인 — 운영 모의훈련의 기상 표현

실황 오류 때문에 운영 앱의 기존 모의훈련 모드로 표현을 별도 확인했다.
실제 배포 앱/API/SDK를 사용했지만 입력은 `SIMULATION`·`actual_data: false`, 각 1,244개 훈련 격자다.
**실제 관측값 검수나 실황 복구로 표시하지 않는다.** [기록](simulation-checks.json).

- PC/390px에서 바람·기온·강수의 이동·확대·축소를 조작했다. 조작으로 기상 API 추가 응답 0, canvas opacity 최솟값 1이었다.
- 바람 canvas의 흐름·프레임 변화와 움직임 줄이기의 정적 표시를 확인했다. 기온/강수의 약한 색면·수치·마커/카드 배치를 직접 봤다.
  [바람 모바일](simulation-wind-390.png), [기온 PC](simulation-temperature-1440.png), [강수 모바일](simulation-rainfall-390.png).
- [PC 영상](simulation-wind-1440.mp4), [모바일 영상](simulation-wind-390.mp4)의 실제 연속 프레임을 검토했다.
  초기 타일 로딩·줌 전환도 포함한다. 모든 배율에서 지연/깜빡임이 없다는 보증이나 실기기 성능 검증은 아니다.

## 미검증·인계

실황 기상 회복 후 실제 값의 그래픽, 스마트폰 실기기/터치·핀치·장기 성능, 관리자 인증 후 기능,
운영 40개 동시 요청·메모리 최고치·장기 부하·취소 후 서버 프로세스 회수는 이번에 검증하지 않았다.
지도 실패 PDF·취소/과부하/잔류 프로세스는 [앞선 로컬 검수](../nearby-integration/README.md)와 구분한다.
운영에 일부러 장애나 과부하를 만들지 않았다.

검수 도구의 초기 관제 지도 대기 순서와 줌 후 화면 밖 라벨 가정은 고쳐 재검수했다. 앱 오류로 집계하지 않았다.
GitHub CLI의 `api.github.com` 조회는 403이라 GitHub 연결 도구로 Actions를 확인했다. 차단을 우회하지 않았다.
발송/dispatch/Worker 시험 경로는 요청 가드로 금지했고 실제 호출 0건이다. 자동 배포의 기존 Scheduler 설정만 적용했다.

다음 시작점은 **운영 Cloud Run의 격자 좌표 조회 실패 진단**이다. [HANDOFF](../../../HANDOFF.md)를 따른다.
키·query·쿠키·외부 응답 원문을 증빙에 담지 않았다. [SHA-256](SHA256SUMS).
