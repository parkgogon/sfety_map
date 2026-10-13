// @vitest-environment jsdom
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { loadKakaoMaps } from "./kakao";
import { getFacilityIconPath } from "./facilityIcons";
import type { Facility } from "./types";
import { KakaoMap } from "./KakaoMap";

describe("KakaoMap 기상 canvas 계층", () => {
  it("정적 기상 색면과 바람 파티클을 독립 canvas로 렌더링한다", () => {
    const markup = renderToStaticMarkup(
      <KakaoMap
        facilities={[]}
        warningZones={[]}
        selectedFacilityId=""
        cctvs={[]}
        selectedCctvId=""
        focusRequest={null}
        weatherLayer={null}
        onSelect={() => undefined}
        onSelectGroup={() => undefined}
        onSelectCctv={() => undefined}
      />,
    );
    expect(markup.match(/<canvas/g)).toHaveLength(2);
    expect(markup).toContain("weather-map-canvas weather-map-surface");
    expect(markup).toContain("weather-map-canvas wind-particle-canvas");
    expect(markup.match(/aria-hidden="true"/g)).toHaveLength(2);
  });

  it("특보 및 모의훈련 props가 제공되어도 에러 없이 렌더링된다", () => {
    const markup = renderToStaticMarkup(
      <KakaoMap
        facilities={[]}
        warningZones={[]}
        warnings={[
          {
            id: "w1",
            region_code: "L1020100",
            region: "대구광역시",
            type: "호우",
            raw_level: "경보",
          },
        ]}
        isSimulation={true}
        selectedFacilityId=""
        cctvs={[]}
        selectedCctvId=""
        focusRequest={null}
        weatherLayer={null}
        onSelect={() => undefined}
        onSelectGroup={() => undefined}
        onSelectCctv={() => undefined}
      />,
    );
    expect(markup).toContain("map-canvas");
  });
});

vi.mock("./kakao", () => ({ loadKakaoMaps: vi.fn() }));

describe("시설 마커 이미지", () => {
  let root: Root;
  let container: HTMLDivElement;
  let imageUrls: string[];
  let markerOptions: Array<{ title: string }>;
  let clusterOptions: Array<{ minLevel: number; gridSize: number }>;

  beforeEach(() => {
    vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
    vi.spyOn(window, "requestAnimationFrame").mockReturnValue(1);
    vi.spyOn(window, "cancelAnimationFrame").mockImplementation(() => undefined);
    imageUrls = [];
    markerOptions = [];
    clusterOptions = [];
    vi.mocked(loadKakaoMaps).mockResolvedValue({
      maps: {
        Map: class { addControl() {} setBounds() {} },
        LatLng: class {},
        LatLngBounds: class { extend() {} },
        ZoomControl: class {},
        ControlPosition: { RIGHT: "right" },
        Size: class {},
        Point: class {},
        MarkerImage: class { constructor(url: string) { imageUrls.push(url); } },
        Marker: class { constructor(options: { title: string }) { markerOptions.push(options); } },
        MarkerClusterer: class {
          constructor(options: { minLevel: number; gridSize: number }) { clusterOptions.push(options); }
          clear() {}
          addMarkers() {}
        },
        event: { addListener: vi.fn(), removeListener: vi.fn() },
      },
    });
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  function facility(groupId: string, overrides: Partial<Facility> = {}): Facility {
    return {
      id: "F-1", name: "시설", type: "수질측정소", group_id: groupId,
      group_label: "수질측정소", latitude: 36.5, longitude: 128.7,
      address: "경북", public_contact: "", grade: "HIGH", grade_label: "상",
      grade_color: "#d92d20", meaning: "", recommended_action: "", reasons: [],
      ...overrides,
    };
  }

  async function renderMarkers(facilities: Facility[], selectedFacilityId = "") {
    await act(async () => {
      root.render(<KakaoMap
        facilities={facilities} warningZones={[]} selectedFacilityId={selectedFacilityId}
        cctvs={[]} selectedCctvId="" focusRequest={null} weatherLayer={null}
        onSelect={() => undefined} onSelectGroup={() => undefined} onSelectCctv={() => undefined}
      />);
    });
    expect(container.querySelector(".map-error")).toBeNull();
    expect(imageUrls).toHaveLength(1);
    return new DOMParser().parseFromString(
      decodeURIComponent(imageUrls[0].split(",")[1]), "image/svg+xml",
    ).documentElement;
  }

  it.each(["wastewater", "air", "water", "site", "farming_collection", "farming_plastic", "other", "new_group"])(
    "%s 단일 시설은 흰색 아이콘을 표시한다", async (groupId) => {
      const svg = await renderMarkers([facility(groupId)]);
      expect(svg.getAttribute("width")).toBe("30");
      const icon = svg.querySelector("svg")!;
      expect(icon.getAttribute("width")).toBe("15");
      expect(icon.getAttribute("x")).toBe("7.5");
      expect(icon.getAttribute("y")).toBe("7.5");
      expect(icon.getAttribute("color")).toBe("white");
      expect(icon.innerHTML).toContain(getFacilityIconPath(groupId).match(/d="([^"]+)"/)![1]);
      expect(svg.querySelector("text")).toBeNull();
      expect(svg.children[1].getAttribute("fill")).toBe("#d92d20");
      expect(clusterOptions[0]).toMatchObject({ minLevel: 10, gridSize: 35 });
    },
  );

  it("선택 시 44px 마커 중앙에 22px 아이콘을 표시한다", async () => {
    const svg = await renderMarkers([facility("site")], "F-1");
    expect(svg.getAttribute("width")).toBe("44");
    expect(svg.querySelector("svg")?.getAttribute("width")).toBe("22");
    expect(svg.querySelector("svg")?.getAttribute("x")).toBe("11");
    expect(svg.querySelector("svg")?.getAttribute("y")).toBe("11");
    expect(svg.children[0].getAttribute("stroke")).toBe("#142746");
    expect(svg.children[0].getAttribute("stroke-width")).toBe("4");
  });

  it.each([false, true])("같은 좌표의 다른 종류 시설은 개수와 가장 높은 위험색을 유지한다 (선택 %s)", async (selected) => {
    const svg = await renderMarkers([
      facility("water", { grade: "LOW", grade_color: "#8a6d00" }),
      facility("site", { id: "F-2" }),
    ], selected ? "F-2" : "");
    expect(svg.getAttribute("width")).toBe(selected ? "44" : "34");
    expect(svg.querySelector("svg")).toBeNull();
    expect(svg.querySelector("text")?.textContent).toBe("2");
    expect(svg.querySelector("text")?.getAttribute("fill")).toBe("white");
    expect(svg.children[1].getAttribute("fill")).toBe("#d92d20");
    expect(markerOptions[0].title).toBe("같은 위치의 시설 2개");
  });
});
