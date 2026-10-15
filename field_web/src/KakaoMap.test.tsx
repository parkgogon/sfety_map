// @vitest-environment jsdom
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, type ComponentProps } from "react";
import { createRoot, type Root } from "react-dom/client";
import { loadKakaoMaps } from "./kakao";
import { getFacilityIconPath } from "./facilityIcons";
import type { Facility } from "./types";
import { KakaoMap, mapViewportPadding } from "./KakaoMap";

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
  let addedControls: unknown[];
  let removedControls: unknown[];
  let mapCreations: number;
  let levels: number[];
  let panOffsets: Array<[number, number]>;

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
    addedControls = [];
    removedControls = [];
    mapCreations = 0;
    levels = [];
    panOffsets = [];
    vi.mocked(loadKakaoMaps).mockResolvedValue({
      maps: {
        Map: class {
          kind = "map";
          level = 10;
          constructor() { mapCreations += 1; }
          addControl(control: unknown) { addedControls.push(control); }
          removeControl(control: unknown) { removedControls.push(control); }
          setBounds(bounds: { points: Array<{ latitude: number; longitude: number }> }, ...padding: number[]) {
            fittedPoints.push(bounds.points);
            fittedPadding.push(padding);
          }
          setCenter() {}
          getLevel() { return this.level; }
          setLevel(level: number) { this.level = level; levels.push(level); }
          panBy(x: number, y: number) { panOffsets.push([x, y]); }
          getProjection() {
            return { containerPointFromCoords: () => ({ x: 350, y: 450 }) };
          }
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
        CustomOverlay: class { setMap() {} },
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

  it("화면 폭 모드가 바뀌어도 지도를 다시 만들지 않고 SDK 확대 막대만 교체한다", async () => {
    const props = {
      facilities: [facility("water")], warningZones: [], selectedFacilityId: "",
      cctvs: [], selectedCctvId: "", focusRequest: null, weatherLayer: null,
      onSelect: () => undefined, onSelectGroup: () => undefined, onSelectCctv: () => undefined,
    };
    await act(async () => root.render(<KakaoMap {...props} showZoomControl={false} />));
    expect(mapCreations).toBe(1);
    expect(addedControls).toHaveLength(0);
    await act(async () => root.render(<KakaoMap {...props} showZoomControl={true} />));
    expect(mapCreations).toBe(1);
    expect(addedControls).toHaveLength(1);
    await act(async () => root.render(<KakaoMap {...props} showZoomControl={false} />));
    expect(mapCreations).toBe(1);
    expect(removedControls).toEqual(addedControls);
  });

  it("모바일 확대·축소와 전체 시설 범위 요청을 최신 요청 한 번씩 적용한다", async () => {
    const props = {
      facilities: [facility("water"), facility("air", { id: "F-2", latitude: 35.4, longitude: 129.3 })],
      warningZones: [], selectedFacilityId: "", cctvs: [], selectedCctvId: "",
      focusRequest: null, weatherLayer: null, showZoomControl: false,
      onSelect: () => undefined, onSelectGroup: () => undefined, onSelectCctv: () => undefined,
    };
    await act(async () => root.render(<KakaoMap {...props} viewportRequest={{ kind: "zoom-in", revision: 1 }} />));
    expect(levels.at(-1)).toBe(9);
    await act(async () => root.render(<KakaoMap {...props} viewportRequest={{ kind: "zoom-out", revision: 2 }} />));
    expect(levels.at(-1)).toBe(10);
    const beforeFit = fittedPoints.length;
    await act(async () => root.render(<KakaoMap {...props} viewportRequest={{ kind: "fit-facilities", revision: 3 }} />));
    expect(fittedPoints).toHaveLength(beforeFit + 1);
    expect(fittedPoints.at(-1)).toEqual([
      { latitude: 36.5, longitude: 128.7 },
      { latitude: 35.4, longitude: 129.3 },
    ]);
    await act(async () => root.render(<KakaoMap {...props} viewportRequest={{ kind: "fit-facilities", revision: 3 }} />));
    expect(fittedPoints).toHaveLength(beforeFit + 1);
    expect(panOffsets).toEqual([]);
  });

  it("지도에서 고른 후보가 실제 하단 확인 패널에 가리면 필요한 만큼만 이동한다", async () => {
    vi.spyOn(HTMLElement.prototype, "clientHeight", "get").mockReturnValue(500);
    vi.spyOn(HTMLElement.prototype, "clientWidth", "get").mockReturnValue(390);
    vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(function (this: HTMLElement) {
      if (this.classList.contains("mobile-candidate-panel")) {
        return { top: 300, bottom: 500, left: 0, right: 390, width: 390, height: 200, x: 0, y: 300, toJSON() {} };
      }
      return { top: 0, bottom: 500, left: 0, right: 390, width: 390, height: 500, x: 0, y: 0, toJSON() {} };
    });
    await act(async () => root.render(<div className="mobile-field-map"><main className="map-stage">
      <KakaoMap facilities={[facility("water")]} warningZones={[]} selectedFacilityId=""
        cctvs={[]} selectedCctvId="" focusRequest={null} weatherLayer={null}
        onSelect={() => undefined} onSelectGroup={() => undefined} onSelectCctv={() => undefined}
        referenceCandidate={{ latitude: 35.4, longitude: 129.3, label: "후보", address: "", source: "map" }} />
      <section className="mobile-candidate-panel" />
    </main></div>));
    expect(panOffsets.at(-1)).toEqual([8, 166]);
  });

});

describe("모바일 지도 가림 영역", () => {
  it("실제 상단·하단 오버레이 크기를 지도 여백으로 계산한다", () => {
    const shell = document.createElement("div");
    shell.className = "mobile-field-map";
    shell.innerHTML = `<main class="map-stage"><div class="mobile-map-top-controls"></div><div class="map-frame"><div class="map-canvas"></div></div><div class="mobile-map-bottom-controls"></div></main>`;
    document.body.append(shell);
    const map = shell.querySelector<HTMLElement>(".map-canvas")!;
    const top = shell.querySelector<HTMLElement>(".mobile-map-top-controls")!;
    const bottom = shell.querySelector<HTMLElement>(".mobile-map-bottom-controls")!;
    Object.defineProperty(map, "clientWidth", { value: 390 });
    Object.defineProperty(map, "clientHeight", { value: 700 });
    vi.spyOn(map, "getBoundingClientRect").mockReturnValue({ top: 0, bottom: 700, left: 0, right: 390, width: 390, height: 700, x: 0, y: 0, toJSON() {} });
    vi.spyOn(top, "getBoundingClientRect").mockReturnValue({ top: 12, bottom: 118, left: 12, right: 378, width: 366, height: 106, x: 12, y: 12, toJSON() {} });
    vi.spyOn(bottom, "getBoundingClientRect").mockReturnValue({ top: 520, bottom: 660, left: 12, right: 378, width: 366, height: 140, x: 12, y: 520, toJSON() {} });
    expect(mapViewportPadding(map)).toEqual({ top: 134, right: 48, bottom: 196, left: 48 });
    shell.remove();
  });
});
