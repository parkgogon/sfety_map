import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { FacilityWeather } from "./FacilitySheet";
import type { WeatherResponse } from "./types";

const weather: WeatherResponse = {
  api_version: "v1",
  facility_id: "F-1",
  status: "LIVE",
  observed_at: "2026-08-12T06:00:00+09:00",
  temperature_c: 28.5,
  rainfall_1h_mm: 1.2,
  wind_speed_ms: 2.4,
  wind_direction_deg: 225,
  detail: "",
  source: "기상청 초단기실황",
  actual_data: true,
};

describe("시설 현재 기상 표현", () => {
  it("접힌 상태에는 한 줄 요약만 표시한다", () => {
    const markup = renderToStaticMarkup(<FacilityWeather weather={weather} expanded={false} />);
    expect(markup).toContain("weather-summary");
    expect(markup).not.toContain("weather-details");
    expect(markup.match(/28\.5℃/g)).toHaveLength(1);
    expect(markup.match(/1\.2mm/g)).toHaveLength(1);
  });

  it("펼친 상태에는 요약을 숨기고 네 개 상세 카드와 관측 시각만 표시한다", () => {
    const markup = renderToStaticMarkup(<FacilityWeather weather={weather} expanded />);
    expect(markup).not.toContain("weather-summary");
    expect(markup).toContain("weather-details");
    expect(markup.match(/28\.5℃/g)).toHaveLength(1);
    expect(markup.match(/1\.2mm/g)).toHaveLength(1);
    expect(markup.match(/관측/g)).toHaveLength(1);
  });
});
