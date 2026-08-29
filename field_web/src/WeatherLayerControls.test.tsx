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

  it("모의훈련에서는 간결한 훈련값 표기와 스크린리더 안전 접근성 레이블을 제공한다", () => {
    const simData: WeatherLayerResponse = {
      ...data,
      status: "SIMULATION",
      actual_data: false,
      scenario_id: "multi_hazard_demo",
      scenario_label: "종합 기상재난 모의훈련",
    };
    const markup = renderToStaticMarkup(
      <WeatherLayerLegend
        kind="temperature"
        data={simData}
        loading={false}
        error=""
        simulation
        onRetry={() => undefined}
      />,
    );
    expect(markup).toContain("기온 · 훈련값");
    expect(markup).toContain('aria-label="기온 모의훈련 기상 가정 (실제 관측이 아님)"');
    expect(markup).not.toContain("종합 기상재난 모의훈련");
    expect(markup).not.toContain("기온 실황");
  });

  it("바람은 위험색 풍속표 대신 입자 방향·속도·꼬리의 의미를 안내한다", () => {
    const windData: WeatherLayerResponse = {
      ...data,
      layer: "wind",
      unit: "m/s",
      points: [{
        grid_x: 89,
        grid_y: 91,
        latitude: 36.1,
        longitude: 128.4,
        u_ms: 8,
        v_ms: 3,
        speed_ms: 8.5,
        direction_to_deg: 69.4,
      }],
    };
    const markup = renderToStaticMarkup(
      <WeatherLayerLegend
        kind="wind"
        data={windData}
        loading={false}
        error=""
        simulation={false}
        onRetry={() => undefined}
      />,
    );
    expect(markup).toContain("바람 실황");
    expect(markup).toContain("입자 방향=풍향, 이동 속도·꼬리=풍속");
    expect(markup).toContain('class="weather-particle-key"');
    expect(markup).toContain('aria-label="바람 범례. 입자 방향=풍향, 이동 속도·꼬리=풍속"');
    expect(markup).not.toContain("weather-color-scale");
    expect(markup).not.toContain("25m/s");
  });
});
