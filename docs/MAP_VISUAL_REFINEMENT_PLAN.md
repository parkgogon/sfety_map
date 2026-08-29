# 지도 마커·기상 그래픽 시각 개선 계획

> 상태: 1~3단계 완료, 4단계 진행 중(자동·문서 검증 완료 / 실화면 미검수)
>
> 작성 기준: 2026-08-30, `main` `b7603c3`, 시작 시 tracked working tree clean
>
> 진행 규칙: 한 차례에 다음 미완료 단계 하나만 구현·검증하고 사용자에게 보고한
> 뒤 멈춘다. 커밋·push·배포는 전체 완료 후 별도 요청을 받아 수행한다.

## 확정 방향

- 미선택 단일 시설 마커는 위험등급과 관계없이 30px로 통일한다.
- 클러스터는 현재보다 한 지도 단계 늦게 생성한다.
- 기온·강수는 점무늬 대신 부드러운 연속 색면으로 표현한다.
- 바람은 저채도 풍속 색면 위에 정적인 방향 화살표를 표시한다.
- Windy식 입자 애니메이션과 서버·기상값 변경은 범위에서 제외한다.

## 1단계 — 빈 구멍 제거와 마커·클러스터 정리

상태: **완료 (2026-08-30)**

구현 결과:

- 기상 canvas에서 시설 103개 위치를 원형으로 지우던
  `clearAroundFacilities()` 호출과 helper를 제거했다.
- 개별 시설 Marker와 클러스터 overlay의 z-index를 4로 명시하고 기상 canvas의
  z-index 2보다 위에 두었다.
- 마커 크기는 미선택 단일 시설 30px, 같은 위치 숫자 마커 34px, 선택 시설 44px,
  일반 클러스터 38px로 고정했다. 위험등급은 크기가 아니라 색상으로 구분한다.
- 클러스터는 `minLevel: 9`, `gridSize: 48`, `minClusterSize: 2`로 조정했다. 숫자
  클러스터 클릭 확대와 단일 마커 선택 배율 유지 동작은 보존했다.
- `mapVisuals.ts`에 순수 시각 규칙을 분리하고 단위 테스트 4개를 추가했다.

검증:

- `npm test -- --run mapVisuals.test.ts weatherLayerRendering.test.ts`: 15개 통과
- `npm test`: React 61개 통과
- `npm run build`: TypeScript strict 및 Vite production build 통과
- `scripts/verify_all.sh`: 시설 103개, Python 256개, React 61개, compile/build 통과
- 브라우저 실화면은 전체 구현 후 4단계에서 통합 검수한다.

## 2단계 — 기온·강수의 연속 색면 렌더링

상태: **완료 (2026-08-30)**

- 격자점별 방사형 원을 4px 간격, 최대 120,000개 샘플의 저해상도 raster로
  교체했다. 큰 viewport는 샘플 상한을 지키도록 간격을 자동 확장한다.
- 화면 공간 bucket index로 가까운 유효점만 찾고, 최대 4개의 값을 거리 제곱
  역가중치 `1 / (distance² + 1)`로 결정적으로 보간한다.
- 인접 격자 간격 0.9배까지 완전히 표시하고 0.9~1.75배에서 smoothstep으로
  감쇠하며 1.75배 바깥은 투명 처리한다.
- 강수 0mm도 경계 보간에는 포함하되 최종값 0.1mm 미만 raster 픽셀은 투명하게
  두었다.
- 저해상도 ImageData를 high-quality image smoothing으로 확대하고 최종 alpha는
  기온 0.24, 강수 0.28로 적용했다. 외부 라이브러리와 Canvas filter는 사용하지
  않았다.
- 기존 색상표를 문자열 재파싱 없이 raster에서 재사용할 수 있도록
  `weatherColorChannels()`를 추가했다.

수용 조건과 검증:

- 원형 점무늬와 빈 구멍 없이 연속적인 hotspot이 보인다.
- 지도 지명·도로·행정경계·특보 경계가 색면 아래에서 읽힌다.
- 정확점·중간값·입력 순서 불변성, 강수 0, 외곽 감쇠, 샘플 상한을 순수 helper
  테스트로 고정했다.
- `scripts/verify_all.sh`: 시설 103개, Python 256개, React 66개, compile/build 통과.
- 브라우저 실화면은 전체 구현 후 4단계에서 통합 검수한다.

## 3단계 — 바람 그래픽 시각 정돈

상태: **완료 (2026-08-30)**

- 2단계 IDW raster가 바람의 `speed_ms`를 입력값으로 사용할 수 있게 확장하고,
  화살표를 그리기 전에 alpha 0.12의 저채도 풍속 색면을 합성했다.
- 음수·무효 풍속은 보간에서 제외하고 0m/s는 잔잔한 영역의 경계값으로 포함했다.
- 기존 결정적 화살표 표본 추출, 화면 대응 간격(48~120px), 22px 가장자리 보호는
  그대로 유지했다.
- 화살표는 풍속에 따라 14~30px, 흰색 외곽선 3.6px/alpha 0.78, 풍속 색상 본선
  2px로 정돈했다. 애니메이션·입자 흐름은 추가하지 않았다.

수용 조건과 검증:

- 풍속 raster가 `value`가 아닌 `speed_ms`를 쓰는지, alpha 0.12, 풍속별 화살표
  길이 제한과 두 번의 stroke 순서를 단위 테스트로 고정했다.
- 기존 확대·축소 밀도, 입력 순서 결정성, 가장자리 잘림 방지 테스트가 모두
  유지됐다.
- 관련 테스트 35개, React 전체 70개와 production build가 통과했다.
- `scripts/verify_all.sh`: 시설 103개, Python 256개, React 70개, compile/build 통과.
- 지도 가독성과 풍속 분포의 실화면 평가는 4단계 통합 검수에 남겼다.

## 4단계 — 통합 검수와 문서 마감

상태: **진행 중 — 자동·문서 검증 완료, 실화면 미검수**

- 현장지도/중앙관제, 실시간/모의훈련, 390×844/1440×900, 지도 레벨 7·8·9·10,
  기온·강수·바람 조합을 실화면으로 검수한다.
- 레벨 8/9 클러스터 전환, 같은 위치 숫자 마커, 선택 강조, 지도 가독성, 구멍
  부재, 이동·확대 후 redraw와 클릭 동작을 확인한다.
- `scripts/verify_all.sh` 전체를 통과시킨다.
- `DESIGN_SYSTEM.md`, `UI_FLOW.md`, `HANDOFF.md`를 현재형으로 갱신하고 완료된 임시
  계획서를 삭제한다.

2026-08-30 진행 결과:

- 로컬 Vite에서 `/`, `/?mode=simulation`, `/control`,
  `/control?mode=simulation` 네 경로가 모두 HTTP 200으로 응답했다.
- `DESIGN_SYSTEM.md`와 `UI_FLOW.md`의 과거 방사형 격자·마커 크기 문구를 현재
  클러스터, IDW 연속 raster, 풍속 색면·화살표 규칙으로 갱신했다.
- 시설 103개, Python 256개, React 70개와 production build를 포함한
  `scripts/verify_all.sh`가 통과했다.
- 인앱 브라우저 연결을 시도했으나 런타임의 사용 가능 브라우저 목록이 비어 있어
  캡처·클릭 기반 PC/모바일 실화면 매트릭스는 수행하지 못했다. 실제 화면을 보지
  않은 채 수용 조건을 통과했다고 간주하지 않는다.
- 구현은 `40e0ddd`로 `main`에 커밋·push했고 GitHub Actions 실행
  `33278837855`에서 테스트, Cloud Run API·Worker, Firebase Hosting, 가동상태
  감시 설정이 모두 성공했다. 운영 `/`, `/control`, `/settings`는 HTTP 200과
  `no-cache, no-store`였고 07:40 KST 자동감시에서 Worker·KMA가 모두 `live`였다.
- 따라서 계획서 삭제와 최종 완료 표시는 보류한다. 브라우저가 연결되거나 사용자가
  배포 화면을 확인하면 아래 실화면 항목만 이어서 검수한다.

## 다음 작업자 실행 문구

```text
AGENTS.md, docs/HANDOFF.md와 docs/MAP_VISUAL_REFINEMENT_PLAN.md를 읽고 현재
Git·코드·테스트와 짧게 대조해줘. 계획을 다시 만들지 말고 다음 미완료 단계 하나만
구현·검증한 뒤 계획서와 HANDOFF를 갱신해줘. 완료 결과를 보고하고 다음 단계로는
넘어가지 마. 커밋·push·배포도 하지 마.
```
