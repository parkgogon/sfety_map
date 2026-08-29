import { describe, expect, it, vi } from "vitest";
import type { WeatherLayerResponse } from "./types";
import {
  calculateWindSpacing,
  drawScalarLayer,
  filterScalarPoints,
  median,
  sampleWindPoints,
  scalarCellRadius,
  scalarLayerAlpha,
  shouldSkipScalarPoint,
  type ScreenWeatherPoint,
} from "./weatherLayerRendering";

describe("weatherLayerRendering 단위 테스트", () => {
  describe("scalarLayerAlpha", () => {
    it("기온과 강수 레이어의 불투명도가 계획된 가독성 범위(0.26~0.38) 내에 있다", () => {
      const tempAlpha = scalarLayerAlpha("temperature");
      const rainAlpha = scalarLayerAlpha("rainfall");
      const windAlpha = scalarLayerAlpha("wind");

      expect(tempAlpha).toBeGreaterThanOrEqual(0.26);
      expect(tempAlpha).toBeLessThanOrEqual(0.32);

      expect(rainAlpha).toBeGreaterThanOrEqual(0.30);
      expect(rainAlpha).toBeLessThanOrEqual(0.38);

      expect(windAlpha).toBe(1.0);
    });
  });

  describe("scalarCellRadius & median", () => {
    it("빈 배열에 대해 기본값을 반환한다", () => {
      expect(median([])).toBe(12);
      expect(scalarCellRadius([])).toBeCloseTo(6.48, 2);
    });

    it("격자 간격의 약 0.54배로 계산되고 min/max 범위(5~90)를 준수한다", () => {
      const mockPoints: ScreenWeatherPoint[] = [
        { source: { grid_x: 10, grid_y: 10, latitude: 36, longitude: 128 }, x: 100, y: 100 },
        { source: { grid_x: 11, grid_y: 10, latitude: 36, longitude: 128.1 }, x: 140, y: 100 },
        { source: { grid_x: 10, grid_y: 11, latitude: 36.1, longitude: 128 }, x: 100, y: 140 },
      ];
      // distance = 40, 40 * 0.54 = 21.6
      const radius = scalarCellRadius(mockPoints);
      expect(radius).toBeCloseTo(21.6, 1);
      expect(radius).toBeGreaterThanOrEqual(5);
      expect(radius).toBeLessThanOrEqual(90);
    });
  });

  describe("shouldSkipScalarPoint", () => {
    it("강수 레이어에서 0mm 이하는 생략하고 양수 강수는 포함한다", () => {
      expect(shouldSkipScalarPoint("rainfall", 0)).toBe(true);
      expect(shouldSkipScalarPoint("rainfall", -1)).toBe(true);
      expect(shouldSkipScalarPoint("rainfall", 0.5)).toBe(false);
      expect(shouldSkipScalarPoint("rainfall", 10)).toBe(false);
    });

    it("기온 레이어에서는 영하나 0도도 정상 렌더링하고 NaN/undefined만 생략한다", () => {
      expect(shouldSkipScalarPoint("temperature", 0)).toBe(false);
      expect(shouldSkipScalarPoint("temperature", -15)).toBe(false);
      expect(shouldSkipScalarPoint("temperature", 35)).toBe(false);
      expect(shouldSkipScalarPoint("temperature", undefined)).toBe(true);
      expect(shouldSkipScalarPoint("temperature", Number.NaN)).toBe(true);
    });
  });

  describe("filterScalarPoints", () => {
    const mockLayer: WeatherLayerResponse = {
      api_version: "v1",
      layer: "rainfall",
      status: "LIVE",
      observed_at: "2026-08-29T12:00:00+09:00",
      fetched_at: "2026-08-29T12:00:00+09:00",
      unit: "mm",
      points: [],
      detail: "",
      source: "KMA",
      scope: "ALL",
      actual_data: true,
    };

    it("화면 경계 바깥의 점과 강수 0인 점을 제외한다", () => {
      const points: ScreenWeatherPoint[] = [
        // 화면 안쪽 정상 강수
        { source: { grid_x: 1, grid_y: 1, latitude: 36, longitude: 128, value: 5 }, x: 100, y: 100 },
        // 화면 안쪽 무강수 (제외 대상)
        { source: { grid_x: 2, grid_y: 1, latitude: 36, longitude: 128.1, value: 0 }, x: 150, y: 100 },
        // 화면 바깥 멀리 있는 점 (제외 대상, radius=20, width=500, height=500)
        { source: { grid_x: 3, grid_y: 1, latitude: 36, longitude: 128.2, value: 10 }, x: 600, y: 100 },
      ];

      const filtered = filterScalarPoints(points, mockLayer, 500, 500, 20);
      expect(filtered).toHaveLength(1);
      expect(filtered[0].source.value).toBe(5);
    });
  });

  describe("drawScalarLayer offscreen canvas blending", () => {
    it("유효한 데이터가 없을 때는 렌더링을 생략한다", () => {
      const dummyCtx = {
        save: vi.fn(),
        restore: vi.fn(),
        drawImage: vi.fn(),
      } as unknown as CanvasRenderingContext2D;

      const emptyLayer: WeatherLayerResponse = {
        api_version: "v1",
        layer: "temperature",
        status: "LIVE",
        observed_at: "",
        fetched_at: "",
        unit: "℃",
        points: [],
        detail: "",
        source: "",
        scope: "",
        actual_data: true,
      };

      drawScalarLayer(dummyCtx, 300, 300, [], emptyLayer);
      expect(dummyCtx.save).not.toHaveBeenCalled();
      expect(dummyCtx.drawImage).not.toHaveBeenCalled();
    });
  });

  describe("calculateWindSpacing & sampleWindPoints (바람 대표점 추출)", () => {
    it("화면 너비(PC vs 모바일) 및 mapLevel에 따라 적절한 spacing을 계산한다", () => {
      // PC (1000px, level 8)
      const pcSpacing = calculateWindSpacing(1000, 800, 8);
      expect(pcSpacing).toBeGreaterThanOrEqual(70);
      expect(pcSpacing).toBeLessThanOrEqual(120);

      // 모바일 (390px, level 10)
      const mobileSpacing = calculateWindSpacing(390, 844, 10);
      expect(mobileSpacing).toBeGreaterThanOrEqual(48);
      expect(mobileSpacing).toBeLessThanOrEqual(90);
    });

    it("점 배열의 순서를 섞어도 항상 동일한 대표점을 100% 결정적으로 선택한다", () => {
      const points: ScreenWeatherPoint[] = [
        { source: { grid_x: 1, grid_y: 1, latitude: 36, longitude: 128, speed_ms: 12, direction_to_deg: 45 }, x: 100, y: 100 },
        { source: { grid_x: 1, grid_y: 2, latitude: 36, longitude: 128.1, speed_ms: 5, direction_to_deg: 90 }, x: 110, y: 105 },
        { source: { grid_x: 2, grid_y: 1, latitude: 36.1, longitude: 128, speed_ms: 18, direction_to_deg: 180 }, x: 300, y: 300 },
        { source: { grid_x: 2, grid_y: 2, latitude: 36.1, longitude: 128.1, speed_ms: 8, direction_to_deg: 270 }, x: 310, y: 290 },
      ];

      const result1 = sampleWindPoints(800, 600, points, 8);
      // 순서 역순
      const reversedPoints = [...points].reverse();
      const result2 = sampleWindPoints(800, 600, reversedPoints, 8);

      expect(result1.length).toBe(result2.length);
      expect(result1.map((p) => p.source.grid_x + ":" + p.source.grid_y)).toEqual(
        result2.map((p) => p.source.grid_x + ":" + p.source.grid_y),
      );
    });

    it("화면 가장자리 Inset(22px) 안쪽의 점만 선택하여 잘림을 방지한다", () => {
      const points: ScreenWeatherPoint[] = [
        // Inset 바깥 (x=10, inset=22) -> 제외 대상
        { source: { grid_x: 1, grid_y: 1, latitude: 36, longitude: 128, speed_ms: 10, direction_to_deg: 90 }, x: 10, y: 100 },
        // Inset 바깥 (x=490, width=500, inset=22) -> 제외 대상
        { source: { grid_x: 2, grid_y: 1, latitude: 36, longitude: 128.1, speed_ms: 10, direction_to_deg: 90 }, x: 490, y: 100 },
        // Inset 안쪽 정상 점
        { source: { grid_x: 3, grid_y: 1, latitude: 36, longitude: 128.2, speed_ms: 10, direction_to_deg: 90 }, x: 150, y: 150 },
      ];

      const sampled = sampleWindPoints(500, 500, points, 8);
      expect(sampled).toHaveLength(1);
      expect(sampled[0].source.grid_x).toBe(3);
    });

    it("유효하지 않은 풍속/풍향 값을 가진 점을 제외한다", () => {
      const points: ScreenWeatherPoint[] = [
        { source: { grid_x: 1, grid_y: 1, latitude: 36, longitude: 128, speed_ms: undefined, direction_to_deg: 90 }, x: 100, y: 100 },
        { source: { grid_x: 2, grid_y: 1, latitude: 36, longitude: 128, speed_ms: 10, direction_to_deg: undefined }, x: 150, y: 150 },
        { source: { grid_x: 3, grid_y: 1, latitude: 36, longitude: 128, speed_ms: 10, direction_to_deg: 90 }, x: 200, y: 200 },
      ];

      const sampled = sampleWindPoints(500, 500, points, 8);
      expect(sampled).toHaveLength(1);
      expect(sampled[0].source.grid_x).toBe(3);
    });
  });
});
