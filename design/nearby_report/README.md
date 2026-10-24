# 기준점 주변 시설 보고서 · 개발용 시안

운영 앱/API에 연결되지 않은 시안 도구다. `POST /api/v1/reports/nearby.pdf`의 입력·CSV 선정·응답은 변경하지 않는다.
실제 Kakao SDK/타일과 연락처 없는 CSV 입력을 사용한다. 합성 195개 시설 사례는 명시적으로 표시한다.

## 실행

저장소 루트에서, 기존 Python 개발 환경과 Playwright Core·Chromium이 있는 환경을 사용한다.
환경의 `HTTPS_PROXY`, CA 신뢰와 등록된 `VITE_KAKAO_MAP_APP_KEY`가 필요하다. 키를 코드·명령 인자·증빙에 쓰지 않는다.

```bash
NEARBY_PREVIEW_DIR=/absolute/temporary/nearby-preview \
PYTHON=/absolute/venv/bin/python node design/nearby_report/capture.mjs
/absolute/venv/bin/python -m design.nearby_report.render /absolute/temporary/nearby-preview
```

- `PLAYWRIGHT_MODULE`, `CHROMIUM_EXECUTABLE`, `PYTHON`으로 설치 경로를 지정할 수 있다.
- `NEARBY_CASES=urban-5km,rural-5km`으로 캡처를 제한하고 렌더링에는 같은 `--cases`를 준다.
- 도시/농촌/해안 × 0.1/1/3/5/50km = 실제 위치 15개와 합성 195개소 1개 입력이 기본이다.
- 실제 SDK 등록 원점인 소유 사이트에서 **개발 HTML 응답만 로컬 파일로 대체**한다.
  SDK·타일 응답은 실제 외부 응답이며 프록시/TLS를 유지한다. 운영 앱/API를 검수·수정·배포한 것이 아니다.
  이 응답 대체는 개발 검증 도구용이며 향후 운영 캡처 서버의 배포 방식으로 사용하지 않는다.
- SDK/타일 3개 호스트의 GET 외 네트워크 요청은 차단한다. 운영 HTML·업무 API·Worker·발송을 호출하지 않는다.
- 지도 픽셀을 캔버스로 읽거나 CORS 헤더를 바꾸지 않고 Chromium의 실제 화면을 한 장 캡처한다.
  로고·축척을 포함한 전체 지도 영역을 보존한다. 여러 캡처/타일을 병합하지 않는다.
- 시안의 실제 PDF는 `*-after.pdf`, 같은 입력의 기존 PDF는 `*-before.pdf`다.
  지도·목록의 ID/좌표/반경/집계와 PNG SHA-256을 확인한 뒤 렌더한다. 기준점·시설명·부서에 전화번호를 담지 않는다.
- 출력 폴더에는 검수용 PNG/메타데이터/PDF가 생긴다. 이는 개발 증빙이며 서버 저장 기능을 추가한 것이 아니다.
  운영에 넣을 때는 필요한 지역 한 장을 요청 단위 메모리에서 처리하는 별도 통합 검토가 필요하다.

## 성능 검수

```bash
/absolute/venv/bin/python -m design.nearby_report.benchmark /absolute/temporary/nearby-benchmark
```

자신과 자식 프로세스를 같은 Linux 논리 CPU 하나에 고정한다. 네트워크를 차단한 TestClient로 기존 API의
health/PDF를 측정하고 실제 SDK 캡처 프로세스와 병행한 값도 기록한다. 운영 API·KMA에 접속하지 않는다.
브라우저 프로세스 RSS 합계는 공유 페이지를 중복 포함하므로 PSS도 함께 기록한다.
Cloud Run의 512Mi 메모리 제한·컨테이너 시작·40개 동시 요청 검증과 구분한다.

## 디자인

KST 생성 시각·기준점 정보, 한 줄 요약, 시설 수/최근접/유형 수/부서 수 카드, 실제 위치도,
가까운 시설 TOP5, 거리대·유형·부서별 막대, 거리순 전체 목록을 제공한다.
시설 5개소 이하는 TOP5와 전체 목록을 하나로 합친다. 분량이 맞으면 분석도 같은 페이지에 담는다.
거리 구간은 1/3/5km와 선택 반경의 오름차순 경계이며, 0m를 포함하고 공통 경계는 가까운 구간에 한 번 센다.
유형은 CSV 원문 유형(앱의 7개 유형 그룹과 다를 수 있음), 부서는 CSV 등록 부서별로 집계한다.
밀집 번호 묶음의 실제 좌표는 점으로 보존하며 이동한 번호에만 안내선을 연결한다.
분석 항목·전체 목록·한 페이지보다 긴 행을 생략하지 않고 다음 페이지로 이어간다.

공식 캡처 안내: [일부 지역 업무용 캡처](https://devtalk.kakao.com/t/javascript-sdk-png/152174),
[출판·인쇄물 출처 표기](https://kakaomap.tistory.com/257).
