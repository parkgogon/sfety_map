import { describe, expect, it } from "vitest";
import type { Facility, NearbyCctv, WeatherResponse } from "./types";
import {
  cctvDirectionText,
  filterFacilities,
  formatReferenceTime,
  GRADE_COLORS,
  GRADE_DISPLAY_ORDER,
  GRADE_PRIORITY_ORDER,
  requestedFacilityId,
  requestedMonitoringMode,
  rainfallColor,
  shouldFitInitialFacilities,
  shouldZoomForSelection,
  shouldShowMapZoomControl,
  temperatureColor,
  weatherSummary,
  windSpeedColor,
  windDirectionLabel,
} from "./utils";

const facility = (overrides: Partial<Facility>): Facility => ({
  id: "F-1",
  name: "구미 수질측정소",
  type: "수질측정소",
  group_id: "water",
  group_label: "수질측정소",
  latitude: 36.1,
  longitude: 128.4,
  address: "경북 구미시 테스트로 1",
  public_contact: "환경서비스처 · 홍길동 대리",
  grade: "MEDIUM",
  grade_label: "중",
  grade_color: "#c2410c",
  meaning: "확인 필요",
  recommended_action: "현장 확인",
  reasons: [],
  ...overrides,
});

describe("현장 지도 필터", () => {
  const facilities = [
    facility({}),
    facility({ id: "F-2", name: "포항 대기측정소", group_id: "air", grade: "NONE", address: "경북 포항시" }),
  ];

  it("시설 유형·등급과 공백을 제거한 한글 검색을 함께 적용한다", () => {
    const result = filterFacilities(
      facilities,
      new Set(["water"]),
      new Set(["MEDIUM"]),
      "구미수질 측정소",
    );
    expect(result.map((item) => item.id)).toEqual(["F-1"]);
  });

  it("딥링크는 facility_id만 읽고 길이를 제한한다", () => {
    expect(requestedFacilityId("?region=구미&facility_id=F-1")).toBe("F-1");
    expect(requestedFacilityId(`?facility_id=${"x".repeat(200)}`)).toHaveLength(128);
  });

  it("모의훈련 주소만 simulation 모드로 인정한다", () => {
    expect(requestedMonitoringMode("?mode=simulation")).toBe("simulation");
    expect(requestedMonitoringMode("?mode=live")).toBe("live");
    expect(requestedMonitoringMode("?mode=unknown")).toBe("live");
  });

  it("API 기준 시각을 한국식 월일 시각으로 표시한다", () => {
    expect(formatReferenceTime("2026-08-11T09:05:00+09:00")).toContain("08. 11.");
    expect(formatReferenceTime("invalid")).toBe("시각 미확인");
  });

  it("단일 마커는 배율을 유지하고 검색·딥링크만 확대한다", () => {
    expect(shouldZoomForSelection("marker")).toBe(false);
    expect(shouldZoomForSelection("same_location")).toBe(false);
    expect(shouldZoomForSelection("search")).toBe(true);
    expect(shouldZoomForSelection("deep_link")).toBe(true);
  });

  it("카카오 확대 컨트롤은 700px보다 넓은 화면에만 표시한다", () => {
    expect(shouldShowMapZoomControl(390)).toBe(false);
    expect(shouldShowMapZoomControl(700)).toBe(false);
    expect(shouldShowMapZoomControl(701)).toBe(true);
    expect(shouldShowMapZoomControl(1280)).toBe(true);
  });

  it("시설 전체 맞춤은 최초로 시설이 준비됐을 때 한 번만 수행한다", () => {
    expect(shouldFitInitialFacilities(false, 0)).toBe(false);
    expect(shouldFitInitialFacilities(false, 103)).toBe(true);
    expect(shouldFitInitialFacilities(true, 103)).toBe(false);
    expect(shouldFitInitialFacilities(true, 3)).toBe(false);
  });

  it("기온·강수·풍향·풍속을 한 줄로 표시한다", () => {
    const weather: WeatherResponse = {
      api_version: "v1",
      facility_id: "F-1",
      status: "LIVE",
      observed_at: "2026-08-12T06:00:00+09:00",
      temperature_c: 28.5,
      rainfall_1h_mm: 0,
      wind_speed_ms: 2.4,
      wind_direction_deg: 225,
      detail: "",
      source: "기상청 초단기실황",
      actual_data: true,
    };
    expect(weatherSummary(weather)).toBe("28.5℃ · 강수 0mm · 남서 225° 2.4m/s");
    expect(windDirectionLabel(-90)).toBe("서 270°");
  });

  it("검증된 CCTV 방향만 각도와 검증일을 표시한다", () => {
    const cctv: NearbyCctv = {
      id: "C-1",
      name: "교차로",
      latitude: 36,
      longitude: 128,
      distance_km: 1.2,
      road_type: "국도",
      video_url: "https://example.com/video.mp4",
      video_format: "MP4",
      embed_allowed: true,
      updated_at: null,
      bearing_deg: 90,
      direction_label: "동",
      direction_verified_on: "2026-08-01",
      direction_source: "현장 확인",
    };
    expect(cctvDirectionText(cctv)).toBe("촬영방향 동 90° · 2026-08-01 검증");
    expect(cctvDirectionText({ ...cctv, bearing_deg: null })).toBe("촬영방향 미확인");
  });

  it("기상 레이어는 고정 범례와 무강수 투명 색을 사용한다", () => {
    expect(rainfallColor(0)).toBe("rgba(0,0,0,0)");
    expect(rainfallColor(5)).toMatch(/^rgba\(/);
    expect(temperatureColor(30, 0.4)).toContain(",0.4)");
    expect(windSpeedColor(12)).toMatch(/^rgba\(/);
    expect(temperatureColor(-100)).not.toContain("NaN");
  });

  it("범례 표시 순서와 운영 우선순위를 독립적으로 유지한다", () => {
    expect(GRADE_DISPLAY_ORDER).toEqual([
      "HIGH", "MEDIUM", "LOW", "NONE", "UNASSESSED", "UNAVAILABLE",
    ]);
    expect(GRADE_PRIORITY_ORDER).toEqual([
      "HIGH", "UNAVAILABLE", "UNASSESSED", "MEDIUM", "LOW", "NONE",
    ]);
    expect(GRADE_DISPLAY_ORDER).not.toEqual(GRADE_PRIORITY_ORDER);
  });

  it("여섯 등급이 각각 하나의 공통 CSS 색상 토큰을 사용한다", () => {
    expect(GRADE_COLORS).toEqual({
      HIGH: "var(--color-risk-high)",
      MEDIUM: "var(--color-risk-medium)",
      LOW: "var(--color-risk-low)",
      UNASSESSED: "var(--color-risk-unassessed)",
      NONE: "var(--color-risk-none)",
      UNAVAILABLE: "var(--color-risk-unavailable)",
    });
    expect(new Set(Object.values(GRADE_COLORS))).toHaveLength(6);
  });
});
