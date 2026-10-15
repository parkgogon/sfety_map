// @vitest-environment jsdom
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, type ComponentProps } from "react";
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
  let listeners: Array<{ target: { kind?: string }; name: string; handler: (event?: any) => void }>;
  let fittedPoints: Array<Array<{ latitude: number; longitude: number }>>;
  let fittedPadding: number[][];

  beforeEach(() => {
    vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
    vi.spyOn(window, "requestAnimationFrame").mockReturnValue(1);
    vi.spyOn(window, "cancelAnimationFrame").mockImplementation(() => undefined);
    imageUrls = [];
    markerOptions = [];
    clusterOptions = [];
    listeners = [];
    fittedPoints = [];
    fittedPadding = [];
    vi.mocked(loadKakaoMaps).mockResolvedValue({
      maps: {
        Map: class {
          kind = "map";
          addControl() {}
          setBounds(bounds: { points: Array<{ latitude: number; longitude: number }> }, ...padding: number[]) {
            fittedPoints.push(bounds.points);
            fittedPadding.push(padding);
          }
          setCenter() {}
          setLevel() {}
          panBy() {}
        },
        LatLng: class {
          constructor(public latitude: number, public longitude: number) {}
          getLat() { return this.latitude; }
          getLng() { return this.longitude; }
        },
        LatLngBounds: class {
          points: Array<{ latitude: number; longitude: number }> = [];
          extend(point: { latitude: number; longitude: number }) { this.points.push(point); }
        },
        ZoomControl: class {},
        ControlPosition: { RIGHT: "right" },
        Size: class {},
        Point: class {},
        MarkerImage: class { constructor(url: string) { imageUrls.push(url); } },
        Marker: class { kind = "marker"; constructor(options: { title: string }) { markerOptions.push(options); } },
        Polygon: class { kind = "polygon"; setMap() {} },
        MarkerClusterer: class {
          constructor(options: { minLevel: number; gridSize: number }) { clusterOptions.push(options); }
          clear() {}
          addMarkers() {}
        },
        event: {
          addListener: vi.fn((target, name, handler) => listeners.push({ target, name, handler })),
          removeListener: vi.fn((target, name, handler) => {
            listeners = listeners.filter((listener) => listener.target !== target || listener.name !== name || listener.handler !== handler);
          }),
        },
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

  async function renderMarkers(facilities: Facility[], selectedFacilityId = "", props: Partial<ComponentProps<typeof KakaoMap>> = {}) {
    await act(async () => {
      root.render(<KakaoMap
        facilities={facilities} warningZones={[]} selectedFacilityId={selectedFacilityId}
        cctvs={[]} selectedCctvId="" focusRequest={null} weatherLayer={null}
        onSelect={() => undefined} onSelectGroup={() => undefined} onSelectCctv={() => undefined}
        {...props}
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
  it("기준점 지정 모드에서는 빈 지도와 시설 클릭을 위치 지정으로 처리한다", async () => {
    const pick = vi.fn();
    const select = vi.fn();
    await renderMarkers([facility("water")], "", { pickingReference: true, onPickReference: pick, onSelect: select });
    const mapClick = listeners.find((listener) => listener.target.kind === "map" && listener.name === "click")!;
    await act(async () => mapClick.handler({ latLng: { getLat: () => 35.4, getLng: () => 129.3 } }));
    expect(pick).toHaveBeenCalledWith({ latitude: 35.4, longitude: 129.3 });
    const markerClick = listeners.find((listener) => listener.target.kind === "marker" && listener.name === "click")!;
    await act(async () => markerClick.handler());
    expect(pick).toHaveBeenLastCalledWith({ latitude: 36.5, longitude: 128.7 });
    expect(select).not.toHaveBeenCalled();
  });

  it("특보 폴리곤 위에서도 기상 카드 대신 기준점을 지정한다", async () => {
    const pick = vi.fn();
    await renderMarkers([facility("water")], "", {
      pickingReference: true, onPickReference: pick,
      warningZones: [{
        type: "Feature",
        properties: { region_code: "test", region: "울산", label: "강풍", level: "ADVISORY", color: "#abc" },
        geometry: { type: "Polygon", coordinates: [[[129, 35], [130, 35], [130, 36], [129, 35]]] },
      }],
    });
    const click = listeners.find((listener) => listener.target.kind === "polygon" && listener.name === "click")!;
    await act(async () => click.handler({ latLng: { getLat: () => 35.4, getLng: () => 129.3 } }));
    expect(pick).toHaveBeenCalledWith({ latitude: 35.4, longitude: 129.3 });
    expect(container.querySelector(".map-information-card")).toBeNull();
  });

  it("일반 모드의 시설 선택은 유지하고 비교 요청은 두 좌표를 함께 맞춘다", async () => {
    const select = vi.fn();
    const points = [{ latitude: 35.4, longitude: 129.3 }, { latitude: 36.5, longitude: 128.7 }];
    await renderMarkers([facility("water")], "", { onSelect: select, referenceView: { revision: 1, points } });
    expect(fittedPoints.at(-1)).toEqual(points);
    const click = listeners.find((listener) => listener.target.kind === "marker" && listener.name === "click")!;
    await act(async () => click.handler());
    expect(select).toHaveBeenCalledWith(facility("water"));
  });

  it("검색 후보 한 지점의 이동 요청도 지도 오류 없이 처리한다", async () => {
    await renderMarkers([facility("water")], "", {
      referenceView: { revision: 1, points: [{ latitude: 35.4, longitude: 129.3 }] },
    });
    expect(container.querySelector(".map-error")).toBeNull();
  });

  it("기상 로딩으로 상세 카드 높이가 변하면 거리 비교 범위를 다시 맞춘다", async () => {
    let resize!: () => void;
    const observed: Element[] = [];
    vi.stubGlobal("ResizeObserver", class {
      constructor(callback: () => void) { resize = callback; }
      observe(element: Element) { observed.push(element); }
      disconnect() {}
    });
    let sheetHeight = 100;
    vi.spyOn(HTMLElement.prototype, "clientHeight", "get").mockReturnValue(500);
    vi.spyOn(HTMLElement.prototype, "clientWidth", "get").mockReturnValue(390);
    vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(function (this: HTMLElement) {
      const height = this.className === "facility-sheet" ? sheetHeight : this.className === "map-search-panel" ? 120 : 500;
      return { top: 0, bottom: height, left: 0, right: 390, width: 390, height, x: 0, y: 0, toJSON() {} };
    });
    const points = [{ latitude: 35.4, longitude: 129.3 }, { latitude: 36.5, longitude: 128.7 }];
    await act(async () => root.render(<main className="map-stage">
      <div className="map-search-panel" /><section className="facility-sheet" />
      <KakaoMap facilities={[facility("water")]} warningZones={[]} selectedFacilityId=""
        cctvs={[]} selectedCctvId="" focusRequest={null} weatherLayer={null}
        onSelect={() => undefined} onSelectGroup={() => undefined} onSelectCctv={() => undefined}
        referenceView={{ points, revision: 1 }} />
    </main>));
    expect(observed.some((element) => element.className === "facility-sheet")).toBe(true);
    const initialBottom = fittedPadding.at(-1)![2];
    sheetHeight = 180;
    await act(async () => resize());
    expect(fittedPadding.at(-1)![2]).toBeGreaterThan(initialBottom);
    expect(fittedPoints.at(-1)).toEqual(points);
    const fittedCount = fittedPoints.length;
    await act(async () => resize());
    expect(fittedPoints).toHaveLength(fittedCount);
  });

});
