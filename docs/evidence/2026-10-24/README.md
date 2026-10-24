# 운영 브라우저 점검 증빙 — 2026-10-24

이 폴더는 점검 브랜치에 보관한 증빙이다. 새 환경에서 같은 브랜치를 checkout하면 문서와 이미지를 함께 읽을 수 있다.
브랜치: `inspection/production-browser-check-20261024`. 운영 `main`에 병합하거나 배포 워크플로를 수동 실행하지 않는다.

먼저 [HANDOFF](../../HANDOFF.md), [상세 점검 기록](../../REFACTORING_BROWSER_CHECK.md)을 읽는다.

## 확인 범위

- 확인: 2026-10-24 20:31~20:50 KST, 운영 웹 버전 `e1f6c0d`, Chromium 154 headless.
- 실제 운영 SDK/API와 UI를 사용했다. 아래 50개 PNG는 직접 검토한 원본을 바이트 변경 없이 복사했다.
- 모바일은 viewport 에뮬레이션이다. 관리자 인증은 제출하지 않았다.
- 지도 타일은 `mts.kakaocdn.net`의 프록시 CONNECT 403에 차단됐다. 마커·거리·기상 오버레이의 실제 렌더링과 이동은 확인했지만, 타일과의 지리적 정합은 미검증이다.
- 사용자가 이후 `mts.kakaocdn.net`을 설정에 추가했다고 알렸다. 새 환경에서 정책과 실제 타일 요청을 확인하기 전까지 차단 해소로 기록하지 않는다.

## 요약 파일

| 파일 | 내용 |
|---|---|
| [summary.json](summary.json) | 버전·브랜치·확인/차단/미검증 범위 |
| [network-summary.json](network-summary.json) | 실제 요청의 호스트·응답 상태·실패 요약, SDK/검색 성공 경로와 타일 CONNECT 403 |
| [http-summary.json](http-summary.json) | 세 웹 경로와 공개 health 2종의 HTTP·캐시 요약 |
| [weather-summary.jsonl](weather-summary.jsonl) | 실제 세 기상 응답의 상태·격자 수·관측 시각 |
| [motion-observations.jsonl](motion-observations.jsonl) | 드래그 전후 canvas·마커 DOM 관측 |
| [layout-observations.jsonl](layout-observations.jsonl) | viewport별 문서 너비·관제 새로고침 위치 |
| [control-refresh-style.json](control-refresh-style.json) | 흰 헤더 위 흰 새로고침 아이콘의 실제 스타일 |
| [settings-login-dimensions.json](settings-login-dimensions.json) | 로그인 버튼·입력칸 줄바꿈과 크기 |
| [screenshots-sha256.json](screenshots-sha256.json) | 원본 캡처와의 무결성 확인값 |

원시 API 응답, query 문자열, 인증 헤더·쿠키, 비밀번호·키, 환경 설정 전체, 브라우저 실행 스크립트는 이 폴더에 넣지 않았다.
환경 밖 원본 폴더나 이전 대화의 첨부 파일이 남아 있다고 가정하지 않는다.

## 캡처 찾아보기

01~10: 기본 지도·검색·기준점·마커. 11~20: 세 기상 그래픽의 전후·이동·확대. 21~28: 현장 모바일. 29~33: 관제. 34: 설정 로그인. 35~36: 모바일 관제 배치.

| 캡처 | 파일 |
|---|---|
| 01-desktop-initial.png | [열기](screenshots/01-desktop-initial.png) |
| 02-place-search.png | [열기](screenshots/02-place-search.png) |
| 03-place-candidate.png | [열기](screenshots/03-place-candidate.png) |
| 04-reference-rings-nearby.png | [열기](screenshots/04-reference-rings-nearby.png) |
| 05-nearby-connection.png | [열기](screenshots/05-nearby-connection.png) |
| 06-rings-off.png | [열기](screenshots/06-rings-off.png) |
| 07-direct-pick-rings.png | [열기](screenshots/07-direct-pick-rings.png) |
| 08-marker-selected.png | [열기](screenshots/08-marker-selected.png) |
| 09-cluster-zoom.png | [열기](screenshots/09-cluster-zoom.png) |
| 10-pan-after-zoom.png | [열기](screenshots/10-pan-after-zoom.png) |
| 11-wind-before-pan.png | [열기](screenshots/11-wind-before-pan.png) |
| 12-wind-animation.png | [열기](screenshots/12-wind-animation.png) |
| 13-wind-during-pan.png | [열기](screenshots/13-wind-during-pan.png) |
| 14-wind-after-zoom.png | [열기](screenshots/14-wind-after-zoom.png) |
| 15-rain-before-pan.png | [열기](screenshots/15-rain-before-pan.png) |
| 16-rain-during-pan.png | [열기](screenshots/16-rain-during-pan.png) |
| 17-rain-after-zoom.png | [열기](screenshots/17-rain-after-zoom.png) |
| 18-temperature-before-pan.png | [열기](screenshots/18-temperature-before-pan.png) |
| 19-temperature-during-pan.png | [열기](screenshots/19-temperature-during-pan.png) |
| 20-temperature-after-zoom.png | [열기](screenshots/20-temperature-after-zoom.png) |
| 21-mobile390-initial.png | [열기](screenshots/21-mobile390-initial.png) |
| 22-mobile390-facility-card.png | [열기](screenshots/22-mobile390-facility-card.png) |
| 23-mobile390-facility-detail.png | [열기](screenshots/23-mobile390-facility-detail.png) |
| 24-mobile360-candidate.png | [열기](screenshots/24-mobile360-candidate.png) |
| 25-mobile360-nearby.png | [열기](screenshots/25-mobile360-nearby.png) |
| 26-mobile360-distance.png | [열기](screenshots/26-mobile360-distance.png) |
| 27-field-360x740.png | [열기](screenshots/27-field-360x740.png) |
| 27-field-390x844.png | [열기](screenshots/27-field-390x844.png) |
| 27-field-430x932.png | [열기](screenshots/27-field-430x932.png) |
| 27-field-700x360.png | [열기](screenshots/27-field-700x360.png) |
| 28-mobile-more-version.png | [열기](screenshots/28-mobile-more-version.png) |
| 29-control-1440x900.png | [열기](screenshots/29-control-1440x900.png) |
| 29-control-360x740.png | [열기](screenshots/29-control-360x740.png) |
| 29-control-390x844.png | [열기](screenshots/29-control-390x844.png) |
| 29-control-430x932.png | [열기](screenshots/29-control-430x932.png) |
| 29-control-700x360.png | [열기](screenshots/29-control-700x360.png) |
| 30-control-analysis-desktop.png | [열기](screenshots/30-control-analysis-desktop.png) |
| 31-control-pick-mode.png | [열기](screenshots/31-control-pick-mode.png) |
| 32-control-history-preauth.png | [열기](screenshots/32-control-history-preauth.png) |
| 33-control-tab-preservation.png | [열기](screenshots/33-control-tab-preservation.png) |
| 34-settings-1440x900.png | [열기](screenshots/34-settings-1440x900.png) |
| 34-settings-360x740.png | [열기](screenshots/34-settings-360x740.png) |
| 34-settings-390x844.png | [열기](screenshots/34-settings-390x844.png) |
| 34-settings-430x932.png | [열기](screenshots/34-settings-430x932.png) |
| 34-settings-700x360.png | [열기](screenshots/34-settings-700x360.png) |
| 35-control-analysis-360x740.png | [열기](screenshots/35-control-analysis-360x740.png) |
| 35-control-analysis-390x844.png | [열기](screenshots/35-control-analysis-390x844.png) |
| 35-control-analysis-430x932.png | [열기](screenshots/35-control-analysis-430x932.png) |
| 36-control-mobile-location-panel.png | [열기](screenshots/36-control-mobile-location-panel.png) |
| mobile-search-current.png | [열기](screenshots/mobile-search-current.png) |

## 다음 환경에서 이어가기

1. Git 브랜치를 `inspection/production-browser-check-20261024`로 선택한다. 기존 변경이 있으면 지우거나 강제 전환하지 말고 별도 작업트리를 사용한다.
2. AGENTS.md, HANDOFF.md, 상세 점검 기록 및 이 폴더를 읽고 실제 Git·원격 최신 상태를 대조한다.
3. `mts.kakaocdn.net` 허용 반영과 실제 운영 타일 HTTP 성공·도로/지형 표시부터 확인한다.
4. 타일 위에서 마커·검색 후보·거리 원·연결선·바람/강수/기온의 위치와 이동·확대 정합을 검수한다.
5. 결과와 핵심 증빙은 이 점검 브랜치에 커밋·push해 인계한다. 앱 코드 수정, main push/병합, 수동 배포, 운영 수동전파·Worker·dispatch·Telegram/SMS 발송 시험은 이 인수인계 범위에 포함하지 않는다.
