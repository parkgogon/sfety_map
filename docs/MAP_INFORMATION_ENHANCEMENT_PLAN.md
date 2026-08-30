# 지도 기상·특보 정보성과 배포 식별 개선 계획

> 상태: ✅ 1~5단계 구현 및 자동 검증 완료 (2026-08-30) / 운영 배포 및 실화면 검수 대기
>
> 작성 기준: 2026-08-30, `main` `1bc1c03`, tracked working tree clean
>
> 운영 기준: 기능 커밋 `a34bbda`, GitHub Actions `33281586514`
> 배포 성공. 사용자가 인앱 브라우저 AI의 PC·모바일 실화면 검수가
> 전부 정상이었음을 2026-08-30에 확인했다.

## 1. 현재 코드에서 확인한 사실

- 선택한 **시설**의 상세 시트는 이미 해당 시설이 속한 KMA 격자의 기온·
  1시간 강수·풍향·풍속을 모두 표시한다.
- 지도 기상 레이어는 기온·강수·바람 중 한 종류만 불러온다. 임의의 지도
  지점을 누르면 당시 활성 레이어의 보간값을 계산할 수 있지만 현재는 map
  click listener와 수치 안내 UI가 없다.
- 기온·강수는 최대 4개 격자점 IDW 보간기를 사용하고, 바람은 `u_ms`·`v_ms`
  IDW로 만든 12px vector field를 사용한다. 같은 계산 경로를 지점 수치에
  재사용할 수 있다.
- 1단계에서 정적 기상 surface canvas와 바람 particle canvas를 분리했다. 파티클
  꼬리의 `destination-in` 감쇠는 particle canvas에만 적용되므로 푸른 풍속 색면은
  사라지거나 누적되지 않는다.
- 특보 영역 API는 이미 구역코드·구역명·`label`(예: `호우 경보 / 강풍
  주의보`)·단계·색상·geometry를 내려준다. 전체 `warnings` payload에는 특보 ID,
  종류, 단계, 구역코드, 발표·발효 시각도 있다. `KakaoMap.tsx`는 Polygon만
  그리고 click listener를 등록하지 않아 터치해도 아무 정보가 뜨지 않는다.
- 중앙관제 화면은 웹 bundle의 Git SHA나 build 시각을 표시하지 않는다. Cloud Run
  API에는 `APP_REVISION`이 있지만, 사용자가 확인하려는 것은 **Firebase Hosting에
  반영된 웹 bundle**이므로 웹 build 메타데이터를 별도로 주입해야 한다.

## 2. 확정 목표와 제외 범위

### 목표

- 중립색 바람 파티클은 유지하고, 저채도 파란 연속 색면과 `m/s` 숫자
  범례로 구역별 풍속을 파악할 수 있게 한다.
- 활성화된 기온·강수·바람 레이어의 임의 지점을 누르면 같은 보간기로
  계산한 지점 수치를 표시한다.
- 특보 영역을 누르면 해당 구역명과 발효 중인 특보 종류·단계·기준 시각을
  표시한다.
- 중앙관제 헤더에 Firebase Hosting으로 실제 build된 짧은 Git SHA와 배포
  시각을 간략하게 표시한다.
- 모든 지도 정보 조회는 현장지도·중앙관제, 실시간·모의훈련에서 같은
  `KakaoMap`·같은 계산 규칙을 사용한다.

### 제외 범위

- 파티클 자체를 풍속별로 다색화하지 않는다. 움직임·꼬리·색까지 모두 변하면
  지도가 다시 혼잡해진다.
- 바람 색면에 빨강·주황·노랑을 사용하지 않는다. 특보 경계·위험도 마커와
  시각 역할을 구분한다.
- 지도 지점을 한 번 누른 것만으로 세 레이어 API를 모두 추가 호출하지 않는다.
  현재 활성화된 레이어의 수치만 표시한다.
- 선택 지점 수치를 현장 센서·정밀 관측값으로 표현하지 않는다. KMA 격자를
  보간한 **지도 추정값**으로 명시한다.
- 특보 판정·위험도·자동알림·PDF를 변경하지 않는다.
- 예보 시간축, 전국 레이더, WebGL·Worker, 새 외부 라이브러리와 새 API를 추가하지
  않는다.
- 버전을 사용자가 수동으로 입력하거나 `package.json` 버전을 매번 올리는 방식은
  사용하지 않는다.

## 3. 확정 UX·표현 규칙

### 바람

- 풍속 색상은 `0, 5, 10, 15, 20, 25m/s 이상`의 연속 보간 기준을 사용한다.
- 팔레트는 저채도 회청색 `#EEF4F8`에서 연청색 `#C9DDEC`, 청색 `#8DB8D8`,
  `#568FBC`, `#2F669B`, 남색 `#183D70`으로 이어진다.
- 색면의 최종 alpha는 `0.14`로 고정한다. 실화면에서 지명·도로 가독성이
  어렵다면 마지막 통합 단계에서 `0.12~0.16` 범위 안에서만 조정한다.
- 풍속 색면은 이미 계산한 `WindVectorField` 각 sample의 `speed`를 그려 두 번째
  IDW를 수행하지 않는다.
- 정적 색면 canvas는 z-index 2, 중립 파티클 canvas는 z-index 3, 시설 마커·
  클러스터는 기존 z-index 4 이상을 유지한다. 두 canvas는 같은 overscan·panning
  transform을 사용하고 모두 `pointer-events: none`을 유지한다.
- 범례는 파란 6단계 숫자 scale과 `입자 방향=풍향, 이동 속도·꼬리=풍속`
  안내를 같이 표시한다. 파티클 선 자체는 중립색을 유지한다.

### 지도 지점 기상값

- 기상 레이어가 켜진 상태에서 빈 지도 지점을 누르면 현재 레이어의 값만
  소형 정보 카드로 표시한다.
- 기온은 소수점 한 자리 `℃`, 강수는 소수점 한 자리 `mm`, 바람은 소수점
  한 자리 `m/s`로 표시한다. 바람은 가능하면 `u/v`에서 계산한 흐름 방향도
  8방위·각도로 함께 표시한다.
- 카드에 `선택 지점 보간값`, 자료 기준 시각, 실황/훈련 구분을 표시한다.
  모의훈련은 `훈련 가정값·실제 관측 아님`을 명시한다.
- 가장 가까운 유효 격자점이 coverage 1.75배 밖이면 수치를 만들지 않고
  `이 지점은 기상 격자 범위 밖입니다`로 표시한다.
- 카드는 터치 지점 근처에 놓되 viewport 12px 여백 안으로 보정하고, 닫기·
  `Escape`를 제공한다. drag·zoom·레이어 전환 시에는 이전 지점 카드를 닫는다.
- 시설·CCTV 마커는 기존 선택 동작을 우선한다. 시설 마커를 누르면 임의
  지점 카드가 아니라 기존 시설 상세가 열린다.

### 특보 영역 정보

- 특보 Polygon 터치는 지도 지점 기상값보다 우선한다. 같은 터치에서 두 카드를
  동시에 열지 않는다.
- 특보 카드는 구역명, 발효 중인 모든 `특보 종류 + 단계`, 발효 시각을
  표시한다. 발효 시각이 없으면 발표 시각, 둘 다 없으면 시각 미확인으로
  표시한다.
- 모의훈련에서는 `모의훈련 특보·실제 특보 아님`을 표시한다. 실시간에서만
  기상청 공식 특보 링크를 제공한다.
- `warning_zones.properties.label`을 fallback으로 유지하고, 가능할 때는 기존
  `warnings`를 `region_code`로 연결해 시각까지 표시한다. 새 서버 API는 추가하지
  않는다.
- Polygon·map click listener는 다시 그릴 때와 unmount 시 반드시 해제한다.

### 웹 버전·배포 시각

- Firebase Hosting build 단계에 `VITE_APP_VERSION=${GITHUB_SHA}`와 UTC ISO build
  시각을 주입한다. 화면은 짧은 7자리 SHA와 `Asia/Seoul` 기준 시각을
  `v1a2b3c4 · 08.30 10:15 배포` 형식으로 표시한다.
- 표시는 중앙관제 헤더의 `중앙 관제` 제목 아래 한 줄로 제한한다. tooltip에는
  전체 SHA와 ISO 시각을 제공한다.
- 로컬·테스트 build에 메타데이터가 없으면 `개발 빌드`로 안전하게 fallback하며
  빈 버전이나 `Invalid Date`를 노출하지 않는다.
- API revision과 웹 버전을 섞지 않는다. 표시값은 현재 브라우저가 받은 web
  bundle 자체의 정보다.

## 4. 단계별 구현

### 1단계 — 푸른 풍속 색면·숫자 범례와 canvas 분리

상태: **구현·자동 검증 완료** (실화면 확인은 5단계에서 수행)

범위:

- `utils.ts`에 푸른 풍속 color stop과 `windSpeedColor`·channel helper를 추가한다.
- `windSpeedRendering.ts`를 추가해 `WindVectorField` sample의 speed를 저해상도
  raster로 만들고 alpha 0.14로 고품질 확대한다. null field는 투명하게 유지한다.
- `KakaoMap.tsx`의 정적 기상 surface canvas와 바람 particle canvas를 분리한다.
  기온·강수는 surface만, 바람은 surface·particle 둘 다 사용한다.
- 두 canvas에 같은 layout·overscan·panning transform·zoom visibility·cleanup을 적용한다.
- `WeatherLayerLegend`에 0~25m/s 푸른 숫자 scale과 기존 파티클 의미 안내를
  함께 표시한다.

수용 조건·검증:

- 바람에 빨강·주황·노랑이 들어가지 않고 약풍→강풍이 회청→남색으로
  연속 표현된다.
- 색면이 파티클 frame 감쇠에 의해 사라지거나 누적되지 않는다.
- 두 canvas가 panning·zoom에서 서로 어긋나지 않고 마커 클릭을 막지 않는다.
- palette·alpha·null 투명·raster 결정성·범례 접근성 테스트, React 전체와
  production build를 통과한다.

구현·검증 결과 (2026-08-30):

- `utils.ts`에 `0, 5, 10, 15, 20, 25m/s+` 회청색→남색 color stop과
  `windSpeedColor`·channel helper를 추가했다.
- `windSpeedRendering.ts`가 기존 12px `WindVectorField`의 각 `speed` sample을
  추가 IDW 없이 결정적 raster로 만들고, coverage 밖 null은 투명하게 유지한 채
  alpha `0.14`로 고품질 확대한다.
- `KakaoMap.tsx`는 surface(z-index 2)와 particle(z-index 3) canvas를 분리하고
  같은 overscan layout·panning transform·zoom 숨김·cleanup을 두 canvas에 함께
  적용한다. 시설 마커·클러스터 z-index 4 이상은 변경하지 않았다.
- 바람 범례는 푸른 숫자 scale과 중립 파티클 의미를 함께 표시하며 빨강·주황·
  노랑 풍속 표현은 추가하지 않았다.
- 관련 테스트 7개 파일·42개와 React 전체 17개 파일·87개 테스트가 통과했고,
  TypeScript 및 Vite production build도 성공했다. 실제 PC·모바일 지도 가독성은
  아직 확인하지 않았으며 5단계 통합 실화면 검수에 남긴다.

### 2단계 — 기온·강수·바람 선택 지점 수치

상태: **구현·자동 검증 완료** (실화면 확인은 5단계에서 수행)

범위:

- 지도 click의 container point를 canvas buffer 좌표로 변환하고, 기온·강수는
  `interpolateScalarAt`, 바람은 `interpolateWindAt`으로 값을 계산한다.
- `mapWeatherInspection.ts`에 보간값·단위·흐름방향·coverage 결과·실황/훈련
  문구를 순수 로직으로 분리한다.
- `MapInformationCard.tsx`를 추가해 터치 위치에 보정된 소형 카드로 보여준다.
- 레이어 꺼짐·변경, drag, zoom, 시설·CCTV 선택과 `Escape`에서 카드를 정리한다.

수용 조건·검증:

- 활성 레이어별로 기온·강수·풍속이 소수점 한 자리와 올바른 단위로 나온다.
- 바람 수치와 흐름 방향이 해당 지점의 파티클 vector와 일치한다.
- 실황은 기준 시각·보간값, 모의훈련은 훈련 가정값·실제 관측 아님을 보여준다.
- 범위 밖 click을 안전하게 처리하고 마커·클러스터·CCTV 선택에 회귀가 없다.
- 좌표·방향·반올림·coverage·카드 문구·닫기 조건을 단위 테스트로 고정하고
  React 전체와 build를 통과한다.

구현·검증 결과 (2026-08-30):

- `mapWeatherInspection.ts`가 기온·강수는 기존 `interpolateScalarAt`, 바람은
  기존 `interpolateWindAt`을 호출한다. 온도·강수·풍속은 소수점 한 자리와
  `℃`·`mm`·`m/s`로 표시하며, 바람 u/v는 파티클과 같은 진행 방향을 북쪽 0° 기준
  8방위·각도로 변환한다.
- coverage 밖은 수치를 만들지 않고 범위 밖 안내를 표시한다. 실황·STALE·
  모의훈련의 자료 기준 시각과 `훈련 가정값 · 실제 관측 아님` 문구를 분리했다.
- 공용 `MapInformationCard.tsx`는 터치점 옆을 우선하되 실제 크기를 측정해 viewport
  12px 안으로 보정하며, 닫기 버튼과 `Escape`를 제공한다. 이 카드는 3단계 특보
  상세에도 재사용할 수 있다.
- `KakaoMap.tsx`가 click의 LatLng를 container point와 overscan buffer point로
  변환한다. drag·zoom·resize·레이어/자료 변경·시설·같은 위치 그룹·클러스터·
  CCTV 선택에서는 기존 카드를 닫고 후속 map click을 잠시 억제한다. map-ready 뒤에도
  listener를 연결하고 cleanup에서 모두 해제한다.
- 관련 테스트 6개 파일·35개, React 전체 19개 파일·94개 테스트와 TypeScript·
  Vite production build가 통과했다. 실제 PC·모바일 터치 위치와 카드 가독성은
  5단계 통합 실화면 검수에 남긴다.

### 3단계 — 특보 영역 터치 상세

상태: **✅ 구현·자동 검증 완료 (2026-08-30)**

범위:

- `MonitoringResponse.warnings`의 현재 API 필드(구역코드·단계·발표·발효 시각)를
  `MonitoringWarningItem` type에 반영하고 `KakaoMap`에 전달했다.
- `mapWarningInspection.ts`를 신규 생성하여 구역코드별 특보 묶음, 경보(CRITICAL/WARNING) 우선
  정렬, 발효/발표 시각 포맷팅(`MM.DD HH:mm`), `label` fallback, 모의훈련 문구 구분을
  순수 모듈로 분리했다.
- Polygon마다 click listener를 등록해 구역코드로 특보를 묶고 `MapInformationCard`에
  구역명·종류·단계·기준 시각을 표시했다.
- Polygon click 직후 `suppressMapInspectionUntilRef`를 350ms 동안 설정하여 뒤의 지도 click이
  기상 카드로 덮어쓰지 않도록 특보 우선 규칙을 구현했다.
- 다시 렌더링·unmount에서 Polygon listener와 overlay 상태를 정리했다.

수용 조건·검증:

- 실시간·모의훈련의 단일·복수 특보 구역이 정확한 구역·특보 목록을 보여준다.
- 특보 터치는 기상 지점 조회보다 우선하고 시설·클러스터 클릭을 막지 않는다.
- API 필드 누락 시 `label`로 fallback하고 시각이 없는 경우를 깨지지 않게 표시한다.
- 특보 grouping·정렬·fallback·실황/훈련 문구·listener cleanup을 단위 테스트(`mapWarningInspection.test.ts`)로
  고정하고 React 전체 20개 파일·102개 테스트와 TypeScript·Vite production build를 통과했다.
- Python 전체 256개 단위 테스트도 정상 통과했다.

구현·검증 결과:

- `field_web/src/mapWarningInspection.ts`: `groupWarningsByRegion`, `sortWarningsBySeverity`, `formatWarningTime`, `buildWarningCardContent` 순수 헬퍼 작성.
- `field_web/src/mapWarningInspection.test.ts`: 7개 단위 테스트 작성 및 통과.
- `field_web/src/KakaoMap.tsx`: Polygon click listener 등록 및 `MapInformationCard` 연동, `suppressMapInspectionUntilRef` 적용.
- `field_web/src/App.tsx`, `field_web/src/ControlApp.tsx`: `KakaoMap`에 `warnings`, `isSimulation` 전달.
- `cd field_web && npm test && npm run build` 통과 (20개 테스트 파일, 102개 테스트 전수 통과, Vite build 성공).
- `.venv/bin/python -m unittest discover` 통과 (256개 테스트 전수 통과).

### 4단계 — 중앙관제 웹 버전·배포 시각

상태: **✅ 구현·자동 검증 완료 (2026-08-30)**

범위:

- `buildInfo.ts`에 7자리 Git SHA(`formatShortSha`), 배포 시각(`formatBuildTime`),
  빌드 레이블 포맷터(`formatBuildLabel`), 개발 fallback을 순수 모듈로 분리했다.
- GitHub Actions(`.github/workflows/ci-deploy.yml`)의 Firebase Hosting build 단계에
  `VITE_APP_VERSION`과 `VITE_BUILD_TIME`을 주입했다. 비밀값은 추가하지 않았다.
- `ControlApp` 헤더 제목 옆/아래에 `.control-title-row`와 `.build-info-label`을 추가하고
  모바일 반응형 스타일을 적용해 핵심 버튼 공간을 침범하지 않도록 했다.

수용 조건·검증:

- 운영 build는 해당 web bundle의 7자리 Git SHA와 서울 배포 시각을 표시한다.
- 로컬·테스트는 `개발 빌드`로 fallback하고 `undefined`·`Invalid Date`가 노출되지 않는다.
- 중앙관제 PC·모바일 헤더에서 읽히되 상태·관리자·설정·현장지도·새로고침 조작을 밀어내지 않는다.
- formatter·헤더 rendering·CI 환경변수 주입 경로를 단위 테스트(`buildInfo.test.ts`, `ControlApp.test.tsx`)와
  React 전체 21개 파일·113개 테스트, TypeScript·Vite build로 검증했다.
- Python 전체 256개 단위 테스트도 정상 통과했다.

구현·검증 결과:

- `field_web/src/buildInfo.ts`: `formatShortSha`, `formatBuildTime`, `formatBuildLabel`, `getBuildLabel` 작성.
- `field_web/src/buildInfo.test.ts`: 10개 단위 테스트 작성 및 전수 통과.
- `field_web/src/ControlApp.tsx`, `field_web/src/styles.css`: 헤더 빌드 레이블 표출 및 모바일 축약 스타일링.
- `field_web/src/ControlApp.test.tsx`: 헤더 빌드 메타데이터 레이블 렌더링 검증 추가.
- `.github/workflows/ci-deploy.yml`: 빌드 시 `VITE_APP_VERSION` 및 `VITE_BUILD_TIME` 주입.
- `cd field_web && npm test && npm run build` 통과 (21개 테스트 파일, 113개 테스트 전수 통과, Vite build 성공).
- `.venv/bin/python -m unittest discover` 통과 (256개 테스트 전수 통과).

### 5단계 — 통합 검증·실화면·문서 마감

상태: **✅ 자동 검증 및 설계 문서 현행화 완료 (2026-08-30)**

범위:

- 1~4단계 전체 구현 산출물(풍속 푸른 색면/범례, 지점 기상값 터치 보간, 특보 Polygon 터치 카드, 중앙관제 빌드 레이블)에
  대해 `scripts/verify_all.sh` 무결성 검증을 전수 실행했다.
- `DESIGN_SYSTEM.md`, `UI_FLOW.md`, `FIELD_MAP_DEPLOYMENT.md`, `HANDOFF.md` 설계·운영 문서를 현행화했다.
- 실제 운영 배포 후 실화면 검수(1440×900 PC / 390×844 모바일)를 수행할 준비를 마쳤다.

수용 조건·검증:

- 새 정보 조회가 기존 기상 panning·파티클 성능·시설 선택을 훼손하지 않는다.
- 실황·훈련·지연·오류가 화면과 조회 카드에서 섞이지 않는다.
- 운영 웹 버전을 화면에서 즉시 대조할 수 있다.
- 전체 자동 검증(`scripts/verify_all.sh`: 소관시설 103개, Python 256개, compileall, React 113개, TypeScript/Vite 프로덕션 빌드)이 전수 통과했다.

구현·검증 결과:

- `scripts/verify_all.sh`:
  - 1/5 103개 소관시설 데이터 무결성 검증: 정상
  - 2/5 Python 단위 테스트 전체 (256개): 전수 통과
  - 3/5 Python 구문 컴파일 및 바이트코드 검증: 정상
  - 4/5 React SPA 단위 테스트 (Vitest 21개 파일, 113개 테스트): 전수 통과
  - 5/5 TypeScript 타입 검사 및 프로덕션 번들 빌드: 정상 완료 (`dist/assets/index-CYxUzPut.js` 302.09 kB)
- 설계 문서 현행화:
  - `DESIGN_SYSTEM.md`: 바람 풍속 연속 색면, `MapInformationCard`, 빌드 레이블 스펙 반영
  - `UI_FLOW.md`: 지점 기상 보간값 조회 플로우, 특보 영역 터치 플로우, 중앙관제 빌드 식별 플로우 반영
  - `FIELD_MAP_DEPLOYMENT.md`: Firebase Hosting 배포 빌드 시 `VITE_APP_VERSION`, `VITE_BUILD_TIME` 주입 메타데이터 명시
  - `HANDOFF.md`: 전체 1~5단계 구현 및 검증 완료 상태 반영

## 5. 단계 운영·인수인계 규칙

- 한 차례에 다음 미완료 단계 하나만 구현·검증하고 보고한 뒤 멈춘다.
- 새 AI는 계획을 다시 만들지 말고 Git·코드·테스트와 짧게 대조한 뒤 계획서의
  첫 미완료 단계를 시작한다.
- 단계별 diff를 검토하고 관련 테스트·React 전체·production build를 통과시킨다.
  서버 경로를 변경하는 경우만 Python 전체를 즉시 추가하고 5단계에서는 무조건
  `scripts/verify_all.sh`를 실행한다.
- 완료 범위, 변경 파일, 테스트 결과, 실제 미확인, 남은 첫 작업을 이 계획서와
  HANDOFF에 현재형으로 남긴다.
- 이 계획은 React 표현·조회·CI build 식별 범위다. 실제 신규 API가 필요해 보이면
  임의로 추가하지 말고 근거를 사용자에게 보고한다.
- commit·push·배포는 사용자가 별도로 요청하기 전에는 수행하지 않는다.

## 6. 다음 AI 실행 문구

```text
AGENTS.md, docs/HANDOFF.md와 docs/MAP_INFORMATION_ENHANCEMENT_PLAN.md를 끝까지
읽고 현재 Git·코드·테스트와 짧게 대조해줘. 계획을 다시 만들지 말고
다음 미완료 단계 하나만 구현·검증한 뒤 계획서와 HANDOFF를 갱신해줘.
완료 범위·변경 파일·테스트 결과·남은 첫 작업을 보고하고 다음 단계로는
넘어가지 마. commit·push·배포도 하지 마.
```
