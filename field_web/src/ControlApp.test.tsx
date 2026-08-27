import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import ControlApp from "./ControlApp";
import type { MonitoringResponse } from "./types";

const mockMonitoringData: MonitoringResponse = {
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
  warnings: [],
  notices: [],
  groups: [
    { id: "water", label: "수질측정소", count: 2 },
    { id: "air", label: "대기측정소", count: 1 },
  ],
  facilities: [
    {
      id: "F-1",
      name: "구미 수질측정소",
      type: "수질측정소",
      group_id: "water",
      group_label: "수질측정소",
      latitude: 36.1,
      longitude: 128.4,
      address: "경북 구미시",
      public_contact: "홍길동 대리",
      grade: "HIGH",
      grade_label: "상",
      grade_color: "#dc2626",
      meaning: "긴급 점검",
      recommended_action: "현장 확인",
      reasons: [{ warning_id: "W-1", type: "호우", raw_level: "경보", grade: "HIGH", region: "구미" }],
    },
    {
      id: "F-2",
      name: "포항 대기측정소",
      type: "대기측정소",
      group_id: "air",
      group_label: "대기측정소",
      latitude: 36.0,
      longitude: 129.3,
      address: "경북 포항시",
      public_contact: "이순신 과장",
      grade: "MEDIUM",
      grade_label: "중",
      grade_color: "#ea580c",
      meaning: "주의",
      recommended_action: "상황 관찰",
      reasons: [{ warning_id: "W-2", type: "강풍", raw_level: "주의보", grade: "MEDIUM", region: "포항" }],
    },
    {
      id: "F-3",
      name: "안동 수질측정소",
      type: "수질측정소",
      group_id: "water",
      group_label: "수질측정소",
      latitude: 36.5,
      longitude: 128.7,
      address: "경북 안동시",
      public_contact: "강감찬 차장",
      grade: "NONE",
      grade_label: "영향 없음",
      grade_color: "#16a34a",
      meaning: "정상",
      recommended_action: "통상 운영",
      reasons: [],
    },
  ],
  warning_zones: {
    type: "FeatureCollection",
    features: [],
  },
};

vi.mock("./api", () => ({
  useMonitoringData: () => ({
    data: mockMonitoringData,
    loading: false,
    refreshing: false,
    error: null,
    refresh: vi.fn(),
  }),
}));

vi.mock("./controlApi", () => ({
  getStoredAdminToken: () => "",
  setStoredAdminToken: vi.fn(),
  verifyAdminPassword: vi.fn(),
  useControlOverview: () => ({ data: null, loading: false, error: null, refresh: vi.fn() }),
  useAlertMetrics: () => ({ data: null, loading: false, error: null, refresh: vi.fn() }),
  useAlertEvents: () => ({ data: [], loading: false, error: null, refresh: vi.fn() }),
}));

describe("ControlApp 중앙관제 대시보드", () => {
  it("중앙관제 헤더와 워크스페이스 탭, KPI 카드를 정상 렌더링한다", () => {
    const html = renderToStaticMarkup(<ControlApp />);
    expect(html).toContain("중앙 관제");
    expect(html).toContain("소관시설 전체");
    expect(html).toContain("특보 영향 시설");
    expect(html).toContain("위험등급 [상]");
    expect(html).toContain("위험등급 [중]");
    expect(html).toContain("운영 상황");
    expect(html).toContain("대상 분석·전파");
    expect(html).toContain("실적·이력");
  });

  it("우선순위 목록에서 3개 시설을 모두 렌더링한다", () => {
    const html = renderToStaticMarkup(<ControlApp />);
    expect(html).toContain("점검 우선순위 시설 목록");
    expect(html).toContain("구미 수질측정소");
    expect(html).toContain("포항 대기측정소");
    expect(html).toContain("안동 수질측정소");
    expect(html).toContain("col-rank");
  });
});
