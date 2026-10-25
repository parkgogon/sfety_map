# 기준점 주변 시설 보고서 · 개발용 시안

시안 비교와 통합 검수 도구다. 채택한 PDF/집계는 공통 코드로 옮겨 기존 API에 연결했고 운영 배포는 하지 않았다.
`POST /api/v1/reports/nearby.pdf`의 입력·CSV 선정·대상 검증 계약을 유지한다.
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
  연결한 API에서는 필요한 지역 한 장을 요청 단위 메모리에서 처리하며 검수용 파일 저장을 하지 않는다.

## 기존 시안의 성능 검수

```bash
/absolute/venv/bin/python -m design.nearby_report.benchmark /absolute/temporary/nearby-benchmark
```

자신과 자식 프로세스를 같은 Linux 논리 CPU 하나에 고정한다. 네트워크를 차단한 TestClient로 기존 API의
health/PDF를 측정하고 실제 SDK 캡처 프로세스와 병행한 값도 기록한다. 운영 API·KMA에 접속하지 않는다.
브라우저 프로세스 RSS 합계는 공유 페이지를 중복 포함하므로 PSS도 함께 기록한다.
Cloud Run의 512Mi 메모리 제한·컨테이너 시작·40개 동시 요청 검증과 구분한다.

## 기존 API와 화면 통합 검수

통합 검수는 수정 웹 빌드와 실제 API를 로컬 Docker 1 CPU/1GiB로 실행한다.
정적 응답만 등록된 소유 원점에서 대체하며 SDK/타일은 환경 HTTPS 프록시·TLS 검증을 유지한다.
가짜 SDK가 아니다. 업무 자료는 고정 검수 자료이며 운영 API 검증·배포나 실기기 검수는 아니다.

```bash
cd field_web && npm run build
cd ..
# 관리 환경에서는 세션의 HTTPS_PROXY/HTTP_PROXY/CA를 그대로 전달해 로컬 이미지만 빌드한다.
docker build -f Dockerfile.api --target api -t sfety-nearby-api:local \
  --build-arg HTTPS_PROXY --build-arg HTTP_PROXY --secret id=ca_bundle,src="$CODEX_PROXY_CERT" .
/absolute/venv/bin/python -m design.nearby_report.container_check start /absolute/temporary/integration
NEARBY_INTEGRATION_OUT=/absolute/temporary/integration /absolute/venv/bin/python -m design.nearby_report.integration_checks
NEARBY_INTEGRATION_OUT=/absolute/temporary/integration node design/nearby_report/browser_integration.mjs
/absolute/venv/bin/python -m design.nearby_report.container_check check /absolute/temporary/integration
/absolute/venv/bin/python -m design.nearby_report.container_check stop /absolute/temporary/integration
```

BuildKit CA secret는 세션 CA 파일 경로를 전달한다.
Docker daemon 선택·프록시 전달은 해당 관리 환경 지침을 따른다. CA를 이미지나 Git에 복사하지 않는다.
`container_check`는 이 작업 라벨의 컨테이너만 시작/확인/종료하며 세션 CA를 런타임에 읽기 전용으로 장착한다.
내부 API 연결은 고정 loopback 127.0.0.1:8877만 사용한다. 외부 지도 통신은 프록시를 유지한다.

- `integration_server`의 `/__qa/*`·고정 관제·지도 응답 대체는 개발 도구에만 있으며 운영 이미지/API에 포함하지 않는다.
- API 검수: 0/1/3/41개소, 4건 동시 요청의 1캡처/2목록PDF/1거절, SDK 로딩 후 TCP 취소,
  의도적으로 타일을 막은 20초 제한과 명시적 지도 실패 PDF를 확인한다.
- 화면 검수: 현장/관제 × 360/390/430/700/1440px, 실제 지정·생성·다운로드·중복 방지·Escape/포커스,
  지도 실패 안내와 SDK 로딩 후 취소 전파·늦은 다운로드 0건을 확인한다.
- `check`는 실제 cgroup 한도/최고 메모리/OOM과 유휴 프로세스를 기록한다. 종료 후 Chromium/좀비가 없어야 한다.
- 결과는 [최종 통합 증빙](../../docs/evidence/2026-10-25/nearby-integration/README.md)에서 확인한다.

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

저장소의 증빙 비교 HTML은 `node design/nearby_report/gallery.mjs`로 1440/390px 배치를 검수한다.
로컬 HTML/이미지 응답만 사용한다. 관리 브라우저의 `file://` 제한 때문에 소유 원점의 응답을 대체하며
정책을 변경하거나 외부 서버에 검수 파일을 업로드하지 않는다. 모바일 폭은 에뮬레이션이다.
