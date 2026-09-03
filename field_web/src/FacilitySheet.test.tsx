import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { FacilitySheet, FacilityWeather } from "./FacilitySheet";
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

  it("기상 조회 실패 시 기술 에러명 대신 친절한 지연 안내 문구를 표시한다", () => {
    const facility = {
      id: "F-1",
      name: "테스트 시설",
      type: "수질측정소",
      group_id: "water",
      group_label: "수질측정소",
      latitude: 36.5,
      longitude: 128.7,
      address: "경상북도",
      public_contact: "홍길동",
      grade: "LOW" as const,
      grade_label: "하",
      grade_color: "#eab308",
      meaning: "주의",
      recommended_action: "관찰",
      reasons: [],
    };
    const markup = renderToStaticMarkup(
      <FacilitySheet
        facility={facility}
        simulation={false}
        cctvEnabled={false}
        weather={null}
        weatherLoading={false}
        weatherError="ConnectTimeout: KMA 서버 응답 지연"
        onRetryWeather={() => undefined}
        cctv={null}
        cctvLoading={false}
        cctvError=""
        cctvCooldownUntil={0}
        onLoadCctv={() => undefined}
        onSelectCctv={() => undefined}
        onClose={() => undefined}
      />,
    );
    expect(markup).toContain("기상청 실황 일시 수신 지연 (재시도 중)");
    expect(markup).not.toContain("ConnectTimeout");
    expect(markup).toContain("다시 시도");
  });
});
