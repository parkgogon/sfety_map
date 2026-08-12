import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { WeatherLayerResponse } from "./types";
import { WeatherLayerLegend } from "./WeatherLayerControls";

const data: WeatherLayerResponse = {
  api_version: "v1",
  layer: "temperature",
  status: "LIVE",
  observed_at: "2026-08-12T13:10:00+09:00",
  fetched_at: "2026-08-12T13:11:00+09:00",
  unit: "℃",
  points: [{ grid_x: 89, grid_y: 91, latitude: 36.1, longitude: 128.4, value: 28 }],
  detail: "",
  source: "기상청",
  scope: "관제 권역",
  actual_data: true,
};

describe("기상 실황 범례", () => {
  it("정상 자료를 제목·시각과 하나의 압축 색상 행으로 표시한다", () => {
    const markup = renderToStaticMarkup(
      <WeatherLayerLegend
        kind="temperature"
        data={data}
        loading={false}
        error=""
        simulation={false}
        onRetry={() => undefined}
      />,
    );
    expect(markup).toContain("기온 실황");
    expect(markup).toContain("08. 12.");
    expect(markup).toContain('class="weather-scale-row"');
    expect(markup).toContain("-10");
    expect(markup).toContain("40℃");
    expect(markup).not.toContain("weather-scale-labels");
  });

  it("모의훈련에서는 실제 현재 정보 배지를 유지한다", () => {
    const markup = renderToStaticMarkup(
      <WeatherLayerLegend
        kind="temperature"
        data={data}
        loading={false}
        error=""
        simulation
        onRetry={() => undefined}
      />,
    );
    expect(markup).toContain("실제 현재 정보");
  });
});
