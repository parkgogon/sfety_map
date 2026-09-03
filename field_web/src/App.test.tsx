// @vitest-environment jsdom
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import App from "./App";
import type { MonitoringResponse } from "./types";

const mockData: MonitoringResponse = {
  api_version: "v1",
  generated_at: "2026-08-27T10:00:00+09:00",
  policy: {
    version: "2026-08-26-official",
    temporary: false,
  },
  status: {
    health: "LIVE",
    fetched_at: "2026-08-27T10:00:00+09:00",
    detail: "",
    zone_health: "LIVE",
    zone_detail: "",
  },
  summary: null,
  warnings: [
    { id: "W-1", region: "경북 안동", type: "태풍", raw_level: "경보" },
  ],
  warning_zones: {
    type: "FeatureCollection",
    features: [],
  },
  notices: [],
  groups: [{ id: "water", label: "수질측정소", count: 1 }],
  facilities: [
    {
      id: "F-1",
      name: "안동 수질측정소",
      type: "수질측정소",
      group_id: "water",
      group_label: "수질측정소",
      latitude: 36.5,
      longitude: 128.7,
      address: "경북 안동시",
      public_contact: "홍길동",
      grade: "HIGH",
      grade_label: "상",
      grade_color: "#dc2626",
      meaning: "긴급 점검",
      recommended_action: "현장 확인",
      reasons: [{ warning_id: "W-1", type: "태풍", raw_level: "경보", grade: "HIGH", region: "안동" }],
    },
  ],
};

vi.mock("./api", () => ({
  useMonitoringData: (_mode: string) => ({
    data: mockData,
    loading: false,
    refreshing: false,
    error: null,
    refresh: () => Promise.resolve(),
  }),
  useFacilityWeather: () => ({ data: null, loading: false, error: null }),
  useFacilityCctv: () => ({ data: null, loading: false, error: null }),
}));

vi.mock("./weatherLayerApi", () => ({
  useWeatherLayer: () => ({
    data: null,
    loading: false,
    error: "",
    refresh: () => undefined,
  }),
}));

vi.mock("./KakaoMap", () => ({
  KakaoMap: () => <div data-testid="kakao-map" />,
}));

describe("App 모의훈련 및 기상 레이어 동작", () => {
  it("실시간 모드에서는 모의훈련 배너를 표시하지 않는다", () => {
    window.history.replaceState({}, "", "/");
    const html = renderToStaticMarkup(<App />);
    expect(html).not.toContain("simulation-banner");
    expect(html).not.toContain("실제 상황이 아닙니다");
  });

  it("직접 ?mode=simulation URL 진입 시 상단 모의훈련 배너와 실시간 복귀 링크를 렌더링한다", () => {
    window.history.replaceState({}, "", "/?mode=simulation");
    const originalHealth = mockData.status.health;
    mockData.status.health = "SIMULATION";
    try {
      const html = renderToStaticMarkup(<App />);
      expect(html).toContain("simulation-banner");
      expect(html).toContain("실제 상황이 아닙니다");
      expect(html).toContain("실시간으로 돌아가기");
    } finally {
      mockData.status.health = originalHealth;
    }
  });

  it("KMA 수신 지연(STALE) 상태일 때 닫기 가능한 안내 배너를 렌더링한다", () => {
    window.history.replaceState({}, "", "/");
    const originalHealth = mockData.status.health;
    mockData.status.health = "STALE";
    try {
      const html = renderToStaticMarkup(<App />);
      expect(html).toContain("notice warning");
      expect(html).toContain("KMA 특보 자료 수신이 지연되어");
      expect(html).toContain("notice-dismiss-btn");
    } finally {
      mockData.status.health = originalHealth;
    }
  });
});
