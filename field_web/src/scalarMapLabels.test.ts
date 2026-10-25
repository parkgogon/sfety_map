import { describe, expect, it } from "vitest";
import { scalarMapLabels } from "./scalarMapLabels";
import type { ScreenWeatherPoint } from "./weatherLayerRendering";
const points: ScreenWeatherPoint[] = Array.from({ length: 20 }, (_, i) => ({ x: 90 + (i % 5) * 110, y: 80 + Math.floor(i / 5) * 110,
  source: { latitude: 35, longitude: 128, grid_x: i % 5, grid_y: Math.floor(i / 5), value: 21.4 + i / 10 } }));
const viewport = { x: 0, y: 0, width: 650, height: 500 };
describe("채택한 기온·강수 B 수치", () => {
  it("실제 격자값을 최대 4곳에 띄엄띄엄 표시하며 입력을 바꾸지 않는다", () => {
    const before = JSON.stringify(points), labels = scalarMapLabels(points, "temperature", viewport);
    expect(labels).toHaveLength(4);
    for (const label of labels) {
      expect(label.text).toBe(`${Number(label.point.source.value!.toFixed(1))}°`);
      for (const other of labels.filter((l) => l !== label)) expect(Math.hypot(label.point.x - other.point.x, label.point.y - other.point.y)).toBeGreaterThanOrEqual(120);
    }
    expect(JSON.stringify(points)).toBe(before);
  });
  it("시설 카드·범례·마커의 제외 영역과 화면 가장자리를 피한다", () => {
    const exclusions = [{ x: 0, y: 0, width: 400, height: 500 }];
    const labels = scalarMapLabels(points, "temperature", viewport, exclusions);
    expect(labels.length).toBeGreaterThan(0);
    expect(labels.every((l) => l.x > 408)).toBe(true);
    expect(scalarMapLabels(points, "temperature", viewport, [viewport])).toEqual([]);
  });
  it("미관측·무효값·음수 강수와 강수 없음에 임의 수치를 만들지 않는다", () => {
    const invalid = points.slice(0, 4).map((p, i) => ({ ...p, source: { ...p.source, value: [undefined, Number.NaN, -1, 0][i] } }));
    expect(scalarMapLabels(invalid, "rainfall", viewport)).toEqual([]);
    expect(scalarMapLabels([], "temperature", viewport)).toEqual([]);
    expect(scalarMapLabels([{ ...points[0], source: { ...points[0].source, value: 0.4 } }], "rainfall", viewport)[0].text).toBe("0.4mm");
  });
});
