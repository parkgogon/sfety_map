# 지도 이동 동기화·바람 파티클 개선 계획

> 상태: 1~3단계 구현 완료, 4단계 자동 통합 검증·문서 완료 / 실화면 확인 대기
>
> 작성 기준: 2026-08-30, `main` `431486c`, tracked working tree clean
>
> 진행 규칙: 한 차례에 다음 미완료 단계 하나만 구현·검증하고 사용자에게 보고한
> 뒤 멈춘다. 커밋·push·배포는 전체 구현과 실화면 확인 후 별도 요청을 받아
> 수행한다.

## 1. 현재 사실

- 운영 배포 `40e0ddd`의 마커·클러스터, 기온·강수 IDW 연속 색면, 바람 색면·
  화살표는 사용자가 PC·모바일에서 문제없다고 확인했다.
- `KakaoMap.tsx`는 `dragstart`에서 기상 canvas의 opacity를 0으로 만들고 `idle`에서
  다시 투영·렌더링한다. `.weather-map-canvas`의 0.16초 opacity transition까지
  더해져 지도 이동 중 그래픽이 사라지고 정지 후 반박자 늦게 나타난다.
- 기상 canvas는 viewport 크기의 절대 위치 요소이며 Kakao 지도 pane에 포함되지
  않아 지도와 자동으로 함께 이동하지 않는다.
- 실시간 KMA와 모의훈련 바람점 모두 `u_ms`, `v_ms`, `speed_ms`,
  `direction_to_deg`를 제공한다. 파티클 방향장은 각도 자체가 아니라 `u_ms`와
  `v_ms`를 보간해 만들 수 있다.
- 현재 바람은 alpha 0.12 풍속 색면과 풍속색 화살표를 함께 그려 위험등급·특보의
  빨강·주황과 시각적으로 충돌한다.

## 2. 목표와 제외 범위

### 목표

- 기온·강수·바람 그래픽이 지도 panning 중 사라지지 않고 지도와 같은 방향·속도로
  이동하도록 한다.
- 바람의 풍속 색면과 색상 화살표를 제거하고, 중립색 파티클의 진행 방향·속도·
  꼬리 길이로 풍향과 상대 풍속을 표현한다.
- 현장지도와 중앙관제, 실시간과 모의훈련에서 같은 renderer를 사용한다.
- 모바일 배터리·성능, 탭 비활성 상태, `prefers-reduced-motion`을 고려한다.

### 제외 범위

- Windy와 동일한 고해상도 예보 모델·정확도·GPU 효과를 재현하지 않는다.
- 예보 시간축, 레이더 타일, WebGL, Worker, 새 외부 라이브러리와 새 서버 API를
  추가하지 않는다.
- 기온·강수 연속 색면, 시설 위험도, 특보 경계, 자동알림·PDF 판단값은 바꾸지
  않는다.
- panning은 실시간 동기화하되 zoom 중에는 좌표 축척이 바뀌므로 애니메이션을
  잠시 멈추고 `idle`에서 즉시 재투영하는 현재 안전한 경계를 유지한다.

## 3. 확정 표현·성능 기준

- 바람 입자는 흰색·옅은 청회색 계열의 중립색만 사용한다. 빨강·주황·노랑 풍속
  색면과 화살표는 제거한다.
- 풍향은 파티클 궤적, 풍속은 이동 속도와 자연스럽게 남는 꼬리 길이로 표현한다.
- 파티클은 약 30fps로 제한하고 viewport 면적에 따라 120~600개 범위에서 조정한다.
- 장치 pixel ratio는 기존처럼 최대 2로 제한하고, 한 프레임의 시간 간격은 급격한
  점프가 없도록 상한을 둔다.
- 레이어가 꺼지거나 바뀌고, 컴포넌트가 해제되거나, 문서가 숨겨지면 animation
  frame을 반드시 취소한다.
- `prefers-reduced-motion: reduce`에서는 애니메이션 대신 중립색의 짧은 정적
  흐름선을 표시해 풍향 정보 자체는 남긴다.

## 4. 단계별 구현

### 1단계 — 기상 canvas panning 동기화 기반

상태: **구현·자동 검증 완료** (실화면 확인은 4단계 통합 검수에서 수행)

범위:

- `weatherCanvasMotion.ts`와 단위 테스트를 추가해 canvas buffer 크기, overscan,
  panning translation 계산을 순수 함수로 분리한다.
- overscan은 viewport 짧은 변의 30%를 기준으로 128~256px 범위에서 계산한다.
  canvas는 viewport보다 overscan만큼 넓게 그리고 화면 밖으로 배치한다.
- 투영한 KMA 점에는 overscan offset을 더해 기존 기온·강수와 현재 바람 renderer가
  같은 buffer 좌표계를 사용하게 한다.
- `dragstart`에서는 canvas를 숨기지 않고 시작 중심 좌표와 화면점을 보관한다.
  `center_changed`를 `requestAnimationFrame`으로 합쳐 같은 기준점의 현재 화면 위치
  차이만큼 `translate3d`를 적용한다.
- `idle`에서는 현재 중심으로 buffer를 다시 그린 뒤 같은 animation frame 안에서
  transform을 0으로 되돌린다. `zoom_start`의 일시 숨김과 `idle` 재표시는 유지한다.
- 모든 Kakao event listener와 animation frame을 effect cleanup에서 제거한다.

수용 조건과 검증:

- 기온·강수와 현행 바람 그래픽이 일반적인 한 번의 panning 동안 완전히 사라지지
  않고 지도와 같은 방향으로 움직인다.
- panning 중 위치 갱신은 animation frame당 최대 한 번이며, 정지 후 기존 0.16초
  재등장 지연이 없다.
- `idle` 재투영 후 누적 transform과 위치 오차가 남지 않는다.
- zoom, resize, 레이어 변경, 마커 클릭과 canvas `pointer-events: none`에 회귀가 없다.
- overscan·offset·translation·frame 병합 helper 테스트와 React 전체 테스트 및
  production build가 통과한다.

구현 결과 (2026-08-30):

- `weatherCanvasMotion.ts`에 짧은 변 30%·128~256px 제한의 buffer layout,
  투영점 offset, 기준점 translation, animation frame 병합·취소 helper를 분리하고
  단위 테스트 4개로 고정했다.
- `KakaoMap.tsx`는 viewport 밖 overscan canvas를 렌더링하고 `dragstart` 기준
  좌표를 `center_changed`에서 animation frame당 한 번만 추적한다. panning 중
  opacity를 숨기지 않으며 `idle`의 같은 frame에서 재투영 후 transform을 0으로
  되돌린다. zoom 중 일시 숨김과 모든 listener/frame cleanup은 유지했다.
- 현행 바람 화살표의 화면 기준 밀도가 overscan buffer 크기에 따라 달라지지 않도록
  buffer 경계와 density viewport 크기를 분리했다. 파티클 계산·표현은 시작하지
  않았다.
- `field_web`에서 React 13개 파일·74개 테스트와 production build가 통과했다.
  현재 세션에는 연결 가능한 브라우저가 없어 실제 drag 화면은 확인하지 못했으며,
  계획된 PC·모바일 실화면 검수는 4단계에 남긴다.

### 2단계 — 결정적 바람 벡터장·파티클 계산 코어

상태: **구현·자동 검증 완료**

범위:

- `windParticleField.ts`와 단위 테스트를 추가한다. 이 단계에서는 화면의 현행 바람
  색면·화살표를 아직 교체하지 않는다.
- 가까운 유효점 최대 4개의 `u_ms`, `v_ms`를 거리 제곱 역가중치로 각각 보간한다.
  방향 각도를 직접 평균내지 않는다.
- `u_ms`·`v_ms`가 없는 호환 입력만 `speed_ms`와 `direction_to_deg`로 복원하고,
  무효값·관측 범위 밖은 사용하지 않는다.
- 12px 간격의 저해상도 벡터장을 미리 만들고 파티클은 이 field를 bilinear
  sampling한다. 전체 field sample은 40,000개를 넘지 않게 간격을 자동 확장한다.
- 화면 좌표는 `dx = u`, `dy = -v` 방향을 사용한다. 시각 이동 속도는 상대 풍속에
  비례하되 2~38px/s로 제한한다.
- seeded PRNG로 초기 위치·수명을 결정하고, 유효 field 밖·최대 수명·buffer 밖으로
  나간 파티클은 유효 영역에 재생성한다.

수용 조건과 검증:

- 동·서·남·북과 대각선 `u/v` 입력이 올바른 화면 이동 방향을 만든다.
- 0/약/강풍의 상대 속도가 보존되고 2~38px/s 제한을 넘지 않는다.
- 359°/1° 같은 각도 경계에서도 `u/v` 보간 방향이 뒤집히지 않는다.
- 같은 seed·field·시간 간격은 같은 파티클 상태를 만든다.
- field sample 상한, coverage, bilinear sampling, 재생성 조건을 순수 테스트로
  고정하고 React 전체 테스트와 build를 통과한다.

구현 결과 (2026-08-30):

- `windParticleField.ts`에 유효한 최근접 점 최대 4개의 `u_ms`·`v_ms` IDW 보간과
  1.75배 coverage 제한을 구현했다. 두 성분이 모두 없는 호환 입력만 풍속과 진행
  방향에서 복원하며 각도를 직접 평균하지 않는다.
- 기본 12px 간격, 최대 40,000 sample의 저해상도 vector field와 유효 모서리 weight를
  정규화하는 bilinear sampling을 구현했다. 화면 이동은 `dx=u`, `dy=-v`이며 풍속은
  2~38px/s 시각 속도로 제한한다.
- 명시적 PRNG state를 사용하는 seeded particle 초기화·이동을 추가했다. 같은
  seed·field·delta는 같은 결과를 만들며 수명 만료, buffer·유효 field 이탈 시
  유효 영역에 결정적으로 재생성한다.
- 방향·속도·359°/1° 경계·최근접 4점·sample 상한·coverage·bilinear sampling·
  결정성·이동·재생성을 단위 테스트로 고정했다. `field_web`에서 React 14개 파일·
  85개 테스트와 production build가 통과했다.
- 새 계산 모듈은 아직 UI renderer에 연결하지 않았다. 현행 풍속 색면·색상 화살표와
  운영 화면 표현은 그대로이며 3단계 파티클 renderer 작업은 시작하지 않았다.

### 3단계 — 중립색 파티클 renderer와 범례 전환

상태: **구현·자동 검증 완료** (실화면·성능 확인은 4단계에서 수행)

범위:

- `windParticleAnimation.ts`를 추가해 particle lifecycle과 30fps animation loop를
  canvas 세부 구현에서 분리한다.
- 바람 활성 시 `drawScalarLayer(wind)`와 색상 화살표 경로를 중단하고 2단계
  벡터장 기반 중립색 파티클만 표시한다. 기온·강수 renderer는 그대로 둔다.
- 짧은 선분을 누적하고 투명하게 감쇠시켜 속도가 빠를수록 자연스럽게 긴 꼬리가
  남게 한다. 빨강·주황·노랑은 사용하지 않는다.
- 1단계 panning transform 동안 animation은 계속 실행하고, `idle`에서 field와
  입자를 새 viewport로 재설정한다. zoom 중에는 멈추고 재투영 후 재개한다.
- viewport 면적으로 파티클을 120~600개로 제한하고 30fps throttling, delta-time
  상한, `visibilitychange` pause/resume, layer switch/unmount cleanup을 적용한다.
- reduced-motion에서는 animation loop 없이 중립색 정적 흐름선을 한 번 그린다.
- 바람 선택 설명과 범례를 색상 단계표에서 `입자 방향=풍향, 이동 속도·꼬리=풍속`
  안내로 바꾸고 스크린리더 레이블에도 같은 의미를 제공한다.
- 교체 후 사용되지 않는 풍속 색면·색상 화살표 helper와 테스트를 제거한다.

수용 조건과 검증:

- 바람 레이어에 위험색과 혼동되는 풍속 색면·색상 화살표가 남지 않는다.
- 약풍은 느리고 짧게, 태풍 모의훈련 강풍은 빠르고 길게 흐르며 방향이 시나리오
  `u/v`와 일치한다.
- panning 중 입자가 지도와 함께 이동하면서 계속 흐르고, 정지 후 위치가 튀거나
  이중 canvas 잔상이 남지 않는다.
- inactive/hidden/unmount에서 animation frame이 남지 않고 reduced-motion에서도
  풍향 정보를 확인할 수 있다.
- fake clock/RAF 기반 lifecycle 테스트, 범례 접근성 테스트, React 전체 테스트와
  production build가 통과한다.

구현 결과 (2026-08-30):

- `windParticleAnimation.ts`에 viewport 면적 기준 120~600개 계산, 약 30fps
  throttling, 0.1초 delta 상한과 중단·재개·폐기 가능한 animation lifecycle을
  구현했다. 중립 청회색·백색 이중 선분과 alpha 감쇠로 빠른 바람일수록 긴 궤적이
  자연스럽게 남고, reduced-motion은 같은 방향의 짧은 정적 흐름선을 그린다.
- `KakaoMap.tsx`는 바람일 때 2단계 vector field와 particle system을 연결한다.
  panning 중에는 animation과 1단계 canvas translation을 함께 유지하고 `idle`에서
  field·particle을 재생성한다. zoom 중지·재개, `visibilitychange`, resize, layer
  switch, motion preference 변경과 unmount에서 frame·listener를 정리한다.
- 바람의 IDW 풍속 색면·색상 화살표 및 위험색 풍속표를 제거했다. 기온·강수만 기존
  연속 색면 renderer를 사용하며 바람 범례와 선택 설명은
  `입자 방향=풍향, 이동 속도·꼬리=풍속`으로 바꾸고 동일한 접근성 레이블을 제공한다.
- fake RAF lifecycle·개수·delta 상한·중립색 궤적·reduced-motion 정적 방향과 바람
  범례 접근성을 테스트로 고정했다. 폐기된 풍속 색면·화살표 helper와 테스트를
  제거한 뒤 `field_web` React 15개 파일·82개 테스트와 production build가 통과했다.
- 현재 세션에는 연결 가능한 브라우저가 없어 실제 지도 움직임·파티클 밀도·발열은
  확인하지 못했다. `DESIGN_SYSTEM.md`·`UI_FLOW.md` 현행화와 PC·모바일 실화면·성능
  확인은 계획대로 4단계에 남긴다.

### 4단계 — 통합 실화면·성능 검수와 문서 마감

상태: **자동 통합 검증·문서 현행화 완료 / 실화면·운영 성능 확인 대기**

범위:

- 현장지도·중앙관제, 실시간·모의훈련, 390×844·1440×900, 지도 level 7·8·9·10의
  기온·강수·바람을 확인한다.
- 짧은 drag, 화면 절반 이상의 drag, 연속 drag, drag 직후 zoom, resize와 레이어
  전환을 반복해 이동 동기화·재투영·cleanup을 검수한다.
- 마커·클러스터·특보 경계가 파티클보다 앞에 보이고 클릭이 막히지 않으며, 위험색과
  바람 표현이 혼동되지 않는지 확인한다.
- 모바일에서 장시간 animation, 백그라운드 전환, reduced-motion을 확인하고 목표
  30fps에서 지속적인 끊김이나 과도한 발열 징후가 있으면 입자 상한·DPR만 조정한다.
- `scripts/verify_all.sh` 전체를 통과시킨다.
- `DESIGN_SYSTEM.md`, `UI_FLOW.md`, `HANDOFF.md`를 현재형으로 갱신한다. 사용자
  실화면 확인까지 끝나면 이 임시 계획서를 삭제하고 결과를 HANDOFF에 옮긴다.

수용 조건과 검증:

- 기온·강수·바람 모두 panning 중 사라지지 않고 지도와 동기화된다.
- 파티클이 실시간·모의훈련에서 풍향과 상대 풍속을 일관되게 전달한다.
- 지도 위험도·특보·시설 선택성이 유지되고 PC·모바일에서 사용 가능한 성능을
  보인다.
- 시설 103개, Python 전체, React 전체, compile과 production build가 모두
  통과하며 실제 미확인 항목은 완료로 표시하지 않는다.

검증 결과 (2026-08-30):

- `scripts/verify_all.sh` 5단계 전체 검증이 성공했다. 시설 103개 무결성, Python
  `tests` 22개와 `tests_v3` 234개(합계 256개), Python compile, React 15개 파일·
  82개 테스트, TypeScript와 production build가 모두 통과했다.
- 현장지도와 중앙관제는 같은 `KakaoMap`·weather renderer를 사용하고 실시간·
  모의훈련 모두 같은 `WeatherLayerResponse`의 `u_ms`·`v_ms` 경로를 사용함을 코드와
  테스트로 재확인했다. canvas `pointer-events: none`, marker z-index, listener·RAF
  cleanup, reduced-motion 범례와 정적 흐름선도 자동 검증 범위에서 확인했다.
- `DESIGN_SYSTEM.md`와 `UI_FLOW.md`를 overscan panning, 12px vector field,
  중립 파티클, 120~600개·30fps, visibility·reduced-motion과 새 범례 의미에 맞게
  현행화했다.
- 현재 세션에는 연결 가능한 브라우저가 없어 390×844·1440×900, level 7~10의
  실제 화면, 짧은·긴·연속 drag와 zoom·resize·탭 전환, 장시간 밀도·끊김·발열은
  확인하지 못했다. 자동 검증 완료와 실화면 미확인을 구분하기 위해 이 계획서는
  아직 삭제하지 않으며 커밋·push·배포 후 사용자 확인까지 남긴다.

사용자 실화면 확인 항목:

- 현장지도와 중앙관제에서 실시간·모의훈련 바람이 위험색 색면·화살표 없이 중립
  파티클로 보이는지 확인한다.
- 약풍은 느리고 짧게, 태풍 훈련 강풍은 빠르고 길게 흐르며 방향이 자연스러운지
  확인한다.
- 짧은·긴·연속 panning 중 기온·강수·바람이 지도와 함께 움직이고, 정지·zoom·
  resize·레이어 전환 뒤 위치 튀김·빈 화면·이중 잔상이 없는지 확인한다.
- PC·모바일에서 마커·클러스터·특보 경계와 범례가 읽히고 클릭이 막히지 않으며,
  장시간 사용 시 눈에 띄는 끊김이나 과도한 발열이 없는지 확인한다.

## 5. 단계 운영·인수인계 규칙

- 새 작업자는 계획을 다시 만들지 말고 Git·코드·테스트와 짧게 대조한 뒤 다음
  미완료 단계 하나만 구현한다.
- 단계 종료 시 diff를 검토하고 관련 테스트와 build를 통과시킨다. 완료 범위,
  변경 파일, 테스트 결과, 남은 첫 작업을 계획서와 HANDOFF에 남기고 반드시 멈춘다.
- 한 단계가 완전히 검증되지 않았으면 다음 단계를 시작하거나 완료로 표시하지 않는다.
- 서버·API·기상값 변경이 필요해 보이면 계획 범위 밖이므로 구현하지 말고 근거와
  영향을 사용자에게 먼저 보고한다.
- commit·push·배포는 사용자가 별도로 요청하기 전에는 수행하지 않는다.

## 6. 배포·실화면 확인 시 다음 AI 실행 문구

```text
AGENTS.md, docs/HANDOFF.md와 docs/WIND_PARTICLE_PANNING_PLAN.md를 끝까지 읽고 현재
Git·코드·테스트와 짧게 대조해줘. 1~3단계 구현과 4단계 자동 검증은 끝났으므로
다시 구현하지 마. 사용자가 요청한 경우에만 검증된 working tree를 커밋·push·배포하고,
배포 뒤 사용자에게 계획서의 PC·모바일 실화면 확인 항목을 안내해줘. 사용자 확인 전에는
계획서를 삭제하거나 실화면 검수를 완료로 표시하지 마.
```
