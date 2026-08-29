import { describe, expect, it, vi } from "vitest";
import type { WeatherLayerResponse } from "./types";
import {
  MAX_SCALAR_RASTER_SAMPLES,
  buildScalarRaster,
  calculateScalarRasterStep,
  calculateWindSpacing,
  drawScalarLayer,
  drawWindArrow,
  interpolateScalarAt,
  median,
  sampleWindPoints,
  scalarCoverage,
  scalarLayerAlpha,
  scalarNeighborSpacing,
  shouldSkipScalarPoint,
  windArrowLength,
  WIND_ARROW_LINE_WIDTH,
  WIND_ARROW_MAX_LENGTH,
  WIND_ARROW_MIN_LENGTH,
  WIND_ARROW_OUTLINE_WIDTH,
  type ScreenWeatherPoint,
} from "./weatherLayerRendering";

describe("weatherLayerRendering 단위 테스트", () => {
  describe("scalarLayerAlpha", () => {
    it("연속 색면의 지도 가독성 alpha를 레이어별로 고정한다", () => {
      expect(scalarLayerAlpha("temperature")).toBe(0.24);
      expect(scalarLayerAlpha("rainfall")).toBe(0.28);
      expect(scalarLayerAlpha("wind")).toBe(0.12);
    });
  });

  describe("scalarNeighborSpacing & median", () => {
    it("빈 배열에 대해 기본값을 반환한다", () => {
      expect(median([])).toBe(12);
      expect(scalarNeighborSpacing([])).toBe(12);
    });

    it("화면에 투영된 인접 KMA 격자의 중앙 간격을 반환한다", () => {
      const mockPoints: ScreenWeatherPoint[] = [
        { source: { grid_x: 10, grid_y: 10, latitude: 36, longitude: 128 }, x: 100, y: 100 },
        { source: { grid_x: 11, grid_y: 10, latitude: 36, longitude: 128.1 }, x: 140, y: 100 },
        { source: { grid_x: 10, grid_y: 11, latitude: 36.1, longitude: 128 }, x: 100, y: 140 },
      ];
      expect(scalarNeighborSpacing(mockPoints)).toBe(40);
    });
  });

  describe("shouldSkipScalarPoint", () => {
    it("강수 0mm를 경계 보간에 포함하고 음수·무효값만 제외한다", () => {
      expect(shouldSkipScalarPoint("rainfall", 0)).toBe(false);
      expect(shouldSkipScalarPoint("rainfall", -1)).toBe(true);
      expect(shouldSkipScalarPoint("rainfall", 0.5)).toBe(false);
      expect(shouldSkipScalarPoint("rainfall", Number.NaN)).toBe(true);
    });

    it("기온 레이어에서는 영하나 0도도 정상 렌더링하고 NaN/undefined만 생략한다", () => {
      expect(shouldSkipScalarPoint("temperature", 0)).toBe(false);
      expect(shouldSkipScalarPoint("temperature", -15)).toBe(false);
      expect(shouldSkipScalarPoint("temperature", 35)).toBe(false);
      expect(shouldSkipScalarPoint("temperature", undefined)).toBe(true);
      expect(shouldSkipScalarPoint("temperature", Number.NaN)).toBe(true);
    });

    it("풍속 0은 포함하고 음수·무효값은 제외한다", () => {
      expect(shouldSkipScalarPoint("wind", 0)).toBe(false);
      expect(shouldSkipScalarPoint("wind", -1)).toBe(true);
      expect(shouldSkipScalarPoint("wind", 12)).toBe(false);
      expect(shouldSkipScalarPoint("wind", undefined)).toBe(true);
    });
  });

  describe("IDW scalar interpolation", () => {
    it("격자점에서는 원래 값을 유지하고 두 점의 중앙에서는 같은 비중으로 보간한다", () => {
      const points: ScreenWeatherPoint[] = [
        { source: { grid_x: 1, grid_y: 1, latitude: 36, longitude: 128, value: 0 }, x: 0, y: 0 },
        { source: { grid_x: 2, grid_y: 1, latitude: 36, longitude: 128.1, value: 10 }, x: 10, y: 0 },
      ];
      expect(interpolateScalarAt(points, "temperature", 0, 0, 10)?.value).toBe(0);
      expect(interpolateScalarAt(points, "temperature", 5, 0, 10)?.value).toBeCloseTo(5, 6);
    });

    it("입력 배열 순서가 달라도 같은 보간값을 반환한다", () => {
      const points: ScreenWeatherPoint[] = [
        { source: { grid_x: 1, grid_y: 1, latitude: 36, longitude: 128, value: 2 }, x: 0, y: 0 },
        { source: { grid_x: 2, grid_y: 1, latitude: 36, longitude: 128.1, value: 8 }, x: 10, y: 0 },
        { source: { grid_x: 1, grid_y: 2, latitude: 36.1, longitude: 128, value: 14 }, x: 0, y: 10 },
        { source: { grid_x: 2, grid_y: 2, latitude: 36.1, longitude: 128.1, value: 20 }, x: 10, y: 10 },
      ];
      const forward = interpolateScalarAt(points, "temperature", 5, 5, 10);
      const reversed = interpolateScalarAt([...points].reverse(), "temperature", 5, 5, 10);
      expect(forward).toEqual(reversed);
    });

    it("0.9배까지 완전히 표시하고 1.75배 바깥은 투명하게 감쇠한다", () => {
      expect(scalarCoverage(9, 10)).toBe(1);
      expect(scalarCoverage(13, 10)).toBeGreaterThan(0);
      expect(scalarCoverage(13, 10)).toBeLessThan(1);
      expect(scalarCoverage(17.5, 10)).toBe(0);
    });
  });

  describe("continuous scalar raster", () => {
    it("4px 이상 간격을 사용하고 어떤 viewport도 120,000 샘플을 넘지 않는다", () => {
      const step = calculateScalarRasterStep(3840, 2160);
      const samples = Math.ceil(3840 / step) * Math.ceil(2160 / step);
      expect(step).toBeGreaterThanOrEqual(4);
      expect(samples).toBeLessThanOrEqual(MAX_SCALAR_RASTER_SAMPLES);
      expect(calculateScalarRasterStep(390, 844)).toBe(4);
    });

    it("강수 0mm는 보간하되 최종 0.1mm 미만 raster 픽셀은 투명하게 둔다", () => {
      const points: ScreenWeatherPoint[] = [
        { source: { grid_x: 1, grid_y: 1, latitude: 36, longitude: 128, value: 0 }, x: 2, y: 2 },
        { source: { grid_x: 2, grid_y: 1, latitude: 36, longitude: 128.1, value: 2 }, x: 10, y: 2 },
      ];
      const raster = buildScalarRaster(points, "rainfall", 12, 4);
      expect(raster).not.toBeNull();
      expect(raster?.pixels[3]).toBe(0);
      expect(raster?.pixels[11]).toBeGreaterThan(0);
    });

    it("같은 데이터는 입력 순서와 무관하게 동일한 raster를 만든다", () => {
      const points: ScreenWeatherPoint[] = [
        { source: { grid_x: 1, grid_y: 1, latitude: 36, longitude: 128, value: 10 }, x: 2, y: 2 },
        { source: { grid_x: 2, grid_y: 1, latitude: 36, longitude: 128.1, value: 20 }, x: 10, y: 2 },
        { source: { grid_x: 1, grid_y: 2, latitude: 36.1, longitude: 128, value: 30 }, x: 2, y: 10 },
      ];
      const forward = buildScalarRaster(points, "temperature", 12, 12);
      const reversed = buildScalarRaster([...points].reverse(), "temperature", 12, 12);
      expect(forward?.pixels).toEqual(reversed?.pixels);
    });

    it("바람 raster는 value가 아니라 speed_ms를 풍속 값으로 사용한다", () => {
      const points: ScreenWeatherPoint[] = [
        {
          source: {
            grid_x: 1,
            grid_y: 1,
            latitude: 36,
            longitude: 128,
            value: 99,
            speed_ms: 0,
          },
          x: 2,
          y: 2,
        },
        {
          source: {
            grid_x: 2,
            grid_y: 1,
            latitude: 36,
            longitude: 128.1,
            value: 0,
            speed_ms: 25,
          },
          x: 10,
          y: 2,
        },
      ];
      const raster = buildScalarRaster(points, "wind", 12, 4);
      expect(raster).not.toBeNull();
      expect(raster?.pixels[0]).not.toBe(raster?.pixels[8]);
      expect(raster?.pixels[1]).not.toBe(raster?.pixels[9]);
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
    it("풍속별 화살표 길이를 14~30px로 제한한다", () => {
      expect(windArrowLength(0)).toBe(WIND_ARROW_MIN_LENGTH);
      expect(windArrowLength(10)).toBeCloseTo(20.4);
      expect(windArrowLength(100)).toBe(WIND_ARROW_MAX_LENGTH);
      expect(windArrowLength(Number.NaN)).toBe(WIND_ARROW_MIN_LENGTH);
    });

    it("흰색 외곽선 3.6px 뒤에 풍속 본선 2px를 그린다", () => {
      const strokes: Array<{ style: string; width: number }> = [];
      const strokeState = { style: "", width: 0 };
      const context = {
        get strokeStyle() {
          return strokeState.style;
        },
        set strokeStyle(value: string | CanvasGradient | CanvasPattern) {
          strokeState.style = String(value);
        },
        get lineWidth() {
          return strokeState.width;
        },
        set lineWidth(value: number) {
          strokeState.width = value;
        },
        lineCap: "butt",
        lineJoin: "miter",
        save: vi.fn(),
        restore: vi.fn(),
        translate: vi.fn(),
        rotate: vi.fn(),
        beginPath: vi.fn(),
        moveTo: vi.fn(),
        lineTo: vi.fn(),
        stroke() {
          strokes.push({ style: strokeState.style, width: strokeState.width });
        },
      } as unknown as CanvasRenderingContext2D;
      const point: ScreenWeatherPoint = {
        source: {
          grid_x: 1,
          grid_y: 1,
          latitude: 36,
          longitude: 128,
          speed_ms: 12,
          direction_to_deg: 90,
        },
        x: 100,
        y: 100,
      };

      drawWindArrow(context, point);

      expect(strokes).toHaveLength(2);
      expect(strokes[0]).toEqual({
        style: "rgba(255,255,255,.78)",
        width: WIND_ARROW_OUTLINE_WIDTH,
      });
      expect(strokes[1].width).toBe(WIND_ARROW_LINE_WIDTH);
      expect(strokes[1].style).toMatch(/^rgba\(/);
    });

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
