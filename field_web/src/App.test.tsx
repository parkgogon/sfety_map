// @vitest-environment jsdom
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import { act, type ComponentProps } from "react";
import type { KakaoMap } from "./KakaoMap";
import { createRoot } from "react-dom/client";
import { getFacilityIconPath } from "./facilityIcons";
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
  KakaoMap: (props: ComponentProps<typeof KakaoMap>) => <div data-testid="kakao-map">
    <span data-testid="visible-facilities">{props.facilities.map((facility) => facility.id).join(",")}</span>
    <span data-testid="reference-target">{props.referenceTarget?.id ?? ""}</span>
    {props.pickingReference && <button type="button" onClick={() => props.onPickReference?.({ latitude: 36.5, longitude: 128.71 })}>시험 지도 위치</button>}
  </div>,
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

describe("시설 범례 아이콘과 필터", () => {
  it("모든 범례에 16px 장식 아이콘을 표시하고 라벨 클릭으로 필터를 토글한다", async () => {
    vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
    window.history.replaceState({}, "", "/");
    const originalGroups = mockData.groups;
    mockData.groups = ["wastewater", "air", "water", "site", "farming_collection", "farming_plastic", "other", "new_group"]
      .map((id) => ({ id, label: id === "water" ? "수질측정소" : id, count: id === "water" ? 1 : 0 }));
    const container = document.createElement("div");
    document.body.append(container);
    const root = createRoot(container);
    try {
      await act(async () => root.render(<App />));
      await act(async () => container.querySelector<HTMLButtonElement>(".filter-button")!.click());
      const labels = Array.from(container.querySelectorAll<HTMLLabelElement>(".group-options label"));
      expect(labels).toHaveLength(mockData.groups.length);
      labels.forEach((label, index) => {
        const icon = label.querySelector("svg")!;
        expect(icon.getAttribute("width")).toBe("16");
        expect(icon.getAttribute("height")).toBe("16");
        expect(icon.getAttribute("aria-hidden")).toBe("true");
        expect(icon.getAttribute("focusable")).toBe("false");
        expect(icon.getAttribute("color")).toBe("currentColor");
        expect(icon.querySelector("path")?.getAttribute("d")).toBe(
          getFacilityIconPath(mockData.groups[index].id).match(/d="([^"]+)"/)![1],
        );
        expect(label.children[0].tagName).toBe("INPUT");
        expect(label.children[1]).toBe(icon);
      });
      const waterLabel = labels[2];
      const checkbox = waterLabel.querySelector<HTMLInputElement>("input")!;
      expect(checkbox.checked).toBe(true);
      await act(async () => waterLabel.click());
      expect(checkbox.checked).toBe(false);
      expect(container.textContent).toContain("현재 필터 조건에 해당하는 시설이 없습니다.");
      await act(async () => waterLabel.click());
      expect(checkbox.checked).toBe(true);
      expect(container.textContent).not.toContain("현재 필터 조건에 해당하는 시설이 없습니다.");
    } finally {
      await act(async () => root.unmount());
      container.remove();
      mockData.groups = originalGroups;
      vi.unstubAllGlobals();
    }
  });
});

describe("현장 지도 기준점 통합", () => {
  it("필터로 숨긴 시설도 기준점 주변 목록에서 선택하면 표시한다", async () => {
    vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
    window.history.replaceState({}, "", "/");
    const container = document.createElement("div");
    document.body.append(container);
    const root = createRoot(container);
    const click = async (text: string) => {
      const button = Array.from(container.querySelectorAll("button")).find((button) => button.textContent === text);
      expect(button, text).toBeTruthy();
      await act(async () => button!.click());
    };
    try {
      await act(async () => root.render(<App />));
      await act(async () => container.querySelector<HTMLButtonElement>(".filter-button")!.click());
      await act(async () => container.querySelector<HTMLInputElement>(".group-options input")!.click());
      await click("확인");
      expect(container.querySelector('[data-testid="visible-facilities"]')?.textContent).toBe("");
      await click("장소·주소");
      await click("지도에서 지정");
      await click("시험 지도 위치");
      await click("이곳을 기준점으로 지정");
      expect(container.querySelector(".map-stage.has-confirmed-reference")).not.toBeNull();
      expect(container.textContent).toContain("필터로 숨김 — 선택하면 표시");
      await act(async () => container.querySelector<HTMLButtonElement>(".location-nearby-list button")!.click());
      expect(container.querySelector('[data-testid="visible-facilities"]')?.textContent).toBe("F-1");
      expect(container.querySelector('[data-testid="reference-target"]')?.textContent).toBe("F-1");
      expect(window.location.search).toContain("facility_id=F-1");
      expect(container.querySelector(".map-stage.has-reference-comparison")).not.toBeNull();
      await act(async () => container.querySelector<HTMLButtonElement>('[aria-label="시설 선택 닫기"]')!.click());
      expect(container.querySelector(".has-reference-comparison")).toBeNull();
    } finally {
      await act(async () => root.unmount());
      container.remove();
      vi.unstubAllGlobals();
    }
  });
});
