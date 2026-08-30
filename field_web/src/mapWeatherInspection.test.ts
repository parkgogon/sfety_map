import { describe, expect, it } from "vitest";
import type { WeatherLayerResponse } from "./types";
import type { ScreenWeatherPoint } from "./weatherLayerRendering";
import {
  inspectMapWeatherAt,
  windFlowDirectionDegrees,
  windFlowDirectionText,
} from "./mapWeatherInspection";

const layer = (
  kind: WeatherLayerResponse["layer"],
  overrides: Partial<WeatherLayerResponse> = {},
): WeatherLayerResponse => ({
  api_version: "v1",
  layer: kind,
  status: "LIVE",
  observed_at: "2026-08-30T10:10:00+09:00",
  fetched_at: "2026-08-30T10:11:00+09:00",
  unit: kind === "temperature" ? "℃" : kind === "rainfall" ? "mm" : "m/s",
  points: [],
  detail: "",
  source: "기상청",
  scope: "관제 권역",
  actual_data: true,
  ...overrides,
});

const scalarPoint = (
  x: number,
  gridX: number,
  value: number,
): ScreenWeatherPoint => ({
  x,
  y: 0,
  source: {
    grid_x: gridX,
    grid_y: 1,
    latitude: 36,
    longitude: 128 + gridX * 0.01,
    value,
  },
});

describe("mapWeatherInspection", () => {
  it("기온과 강수를 같은 scalar IDW로 보간해 소수점 한 자리·올바른 단위로 표시한다", () => {
    const points = [scalarPoint(0, 1, 20), scalarPoint(10, 2, 30)];
    const temperature = inspectMapWeatherAt(layer("temperature"), points, 5, 0);
    expect(temperature.value).toBe("25.0℃");
    expect(temperature.eyebrow).toBe("선택 지점 보간값");
    expect(temperature.meta[0]).toContain("자료 기준");
    expect(temperature.outOfRange).toBe(false);

    const rainPoints = [scalarPoint(0, 1, 0), scalarPoint(10, 2, 2)];
    expect(inspectMapWeatherAt(layer("rainfall"), rainPoints, 5, 0).value).toBe("1.0mm");
  });

  it("바람 u/v를 보간해 파티클과 같은 진행 방향·풍속을 표시한다", () => {
    const points: ScreenWeatherPoint[] = [
      {
        x: 0,
        y: 0,
        source: { grid_x: 1, grid_y: 1, latitude: 36, longitude: 128, u_ms: 10, v_ms: 0 },
      },
      {
        x: 10,
        y: 0,
        source: { grid_x: 2, grid_y: 1, latitude: 36, longitude: 128.1, u_ms: 10, v_ms: 0 },
      },
    ];
    const inspection = inspectMapWeatherAt(layer("wind"), points, 5, 0);
    expect(inspection.value).toBe("10.0m/s");
    expect(inspection.lines).toEqual(["동 90.0° 방향으로 흐름"]);
    expect(inspection.outOfRange).toBe(false);
  });

  it("흐름 방향을 북쪽 0° 기준 8방위로 정규화하고 무풍은 방향을 단정하지 않는다", () => {
    const northwest = { u: -5, v: 5, speed: Math.hypot(5, 5), dx: -5, dy: -5 };
    expect(windFlowDirectionDegrees(northwest)).toBeCloseTo(315);
    expect(windFlowDirectionText(northwest)).toBe("북서 315.0° 방향으로 흐름");
    expect(windFlowDirectionText({ u: 0, v: 0, speed: 0, dx: 0, dy: 0 }))
      .toBe("바람 흐름이 거의 없음");
  });

  it("1.75배 coverage 밖은 수치를 만들지 않고 범위 밖 안내를 표시한다", () => {
    const inspection = inspectMapWeatherAt(
      layer("temperature"),
      [scalarPoint(0, 1, 20), scalarPoint(10, 2, 30)],
      100,
      0,
    );
    expect(inspection.value).toBeUndefined();
    expect(inspection.outOfRange).toBe(true);
    expect(inspection.lines).toEqual(["이 지점은 기상 격자 범위 밖입니다."]);
  });

  it("모의훈련과 지연 실황을 실제 관측으로 오해하지 않게 구분한다", () => {
    const points = [scalarPoint(0, 1, 20), scalarPoint(10, 2, 30)];
    const simulation = inspectMapWeatherAt(
      layer("temperature", { status: "SIMULATION", actual_data: false }),
      points,
      5,
      0,
    );
    expect(simulation.tone).toBe("simulation");
    expect(simulation.meta).toContain("훈련 가정값 · 실제 관측 아님");

    const stale = inspectMapWeatherAt(
      layer("temperature", { status: "STALE" }),
      points,
      5,
      0,
    );
    expect(stale.meta).toContain("지연된 기상청 격자 실황 참고정보");
  });
});
