// @vitest-environment jsdom
import { afterEach, expect, it, vi } from "vitest";
import { captureWeatherTiles, currentWeatherTilePoints } from "./weatherProjection";
import { calculateWeatherCanvasLayout, weatherCanvasAffineTransform } from "../weatherCanvasMotion";
const layout = calculateWeatherCanvasLayout(600, 400);
afterEach(() => { document.body.replaceChildren(); vi.restoreAllMocks(); });
function mapFixture(collinear = false) {
  const element = document.createElement("div"); document.body.append(element);
  vi.spyOn(element, "getBoundingClientRect").mockReturnValue({ x: 0, y: 0, left: 0, top: 0, right: 600, bottom: 400, width: 600, height: 400 } as DOMRect);
  let scale = 1, dx = 0, dy = 0;
  for (const [i, [x, y]] of [[0, 0], [256, 0], [0, 256], [256, 256]].entries()) {
    const img = document.createElement("img");img.src = `https://mts.kakaocdn.net/api/v1/tile/${i}.png`;element.append(img);
    vi.spyOn(img, "getBoundingClientRect").mockImplementation(() => {
      const left = x * scale + dx, top = (collinear ? 0 : y) * scale + dy;
      return { x: left, y: top, left, top, right: left + 256 * scale, bottom: top + 256 * scale, width: 256 * scale, height: 256 * scale } as DOMRect;
    });
  }
  return { element, move: (s: number, x: number, y: number) => { scale = s; dx = x; dy = y; } };
}
it("실제 화면 사각형으로 줌 중간 배율·이동을 연결하고 픽셀이나 HTTP를 읽지 않는다", () => {
  const map = mapFixture(), anchors = captureWeatherTiles(map.element, layout)!;
  expect(anchors).toHaveLength(3);
  map.move(1.5, 30, -20);
  expect(weatherCanvasAffineTransform(anchors.map((a) => a.point), currentWeatherTilePoints(anchors, map.element, layout)!))
    .toBe("matrix(1.5, 0, 0, 1.5, -34, -84)");
});
it("SDK가 이미지를 재사용하거나 지우면 기존 참조를 쓰지 않고 좌표 투영으로 돌아간다", () => {
  const map = mapFixture(), anchors = captureWeatherTiles(map.element, layout)!;
  anchors[0].image.src = "https://mts.kakaocdn.net/api/v1/tile/new.png";
  expect(currentWeatherTilePoints(anchors, map.element, layout)).toBeNull();
  anchors[0].image.remove();expect(currentWeatherTilePoints(anchors, map.element, layout)).toBeNull();
});
it("지도 이미지가 없거나 일직선의 점뿐이면 대체 좌표 경로를 사용한다", () => {
  expect(captureWeatherTiles(document.createElement("div"), layout)).toBeNull();
  expect(captureWeatherTiles(mapFixture(true).element, layout)).toBeNull();
});
