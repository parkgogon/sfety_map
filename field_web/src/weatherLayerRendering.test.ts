import { describe, expect, it, vi } from "vitest";
import {
  MAX_SCALAR_RASTER_SAMPLES,
  buildScalarRaster,
  calculateScalarRasterStep,
  drawScalarLayer,
  interpolateScalarAt,
  median,
  scalarCoverage,
  scalarLayerAlpha,
  scalarNeighborSpacing,
  shouldSkipScalarPoint,
  type ScreenWeatherPoint,
} from "./weatherLayerRendering";

describe("weatherLayerRendering 단위 테스트", () => {
  describe("scalarLayerAlpha", () => {
    it("연속 색면의 지도 가독성 alpha를 레이어별로 고정한다", () => {
      expect(scalarLayerAlpha("temperature")).toBe(0.24);
      expect(scalarLayerAlpha("rainfall")).toBe(0.28);
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
  });

  describe("drawScalarLayer offscreen canvas blending", () => {
    it("유효한 데이터가 없을 때는 렌더링을 생략한다", () => {
      const dummyCtx = {
        save: vi.fn(),
        restore: vi.fn(),
        drawImage: vi.fn(),
      } as unknown as CanvasRenderingContext2D;

      drawScalarLayer(dummyCtx, 300, 300, [], "temperature");
      expect(dummyCtx.save).not.toHaveBeenCalled();
      expect(dummyCtx.drawImage).not.toHaveBeenCalled();
    });
  });
});
