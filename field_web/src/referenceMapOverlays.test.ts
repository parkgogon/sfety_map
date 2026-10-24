import type { KakaoSDK, KakaoMapInstance } from "./kakaoTypes";
// @vitest-environment jsdom
import { describe, expect, it } from "vitest";
import { referenceMapOverlays } from "./referenceMapOverlays";
import type { Facility } from "./types";

function setup() {
  const created: Array<{
    kind: string;
    options: any;
    map: unknown;
    setMap: (map: unknown) => void;
  }> = [];
  const overlay = (kind: string) =>
    class {
      kind = kind;
      map: unknown;
      constructor(public options: any) {
        this.map = options.map;
        created.push(this);
      }
      setMap(map: unknown) {
        this.map = map;
      }
    };
  return {
    created,
    kakao: {
      maps: {
        LatLng: class {
          constructor(
            public latitude: number,
            public longitude: number,
          ) {}
        },
        CustomOverlay: overlay("label"),
        Circle: overlay("circle"),
        Polyline: overlay("line"),
      },
    },
  };
}
const point = {
  latitude: 35.4,
  longitude: 129.3,
  label: '<img src=x onerror="alert(1)">',
  address: "",
  source: "map" as const,
};

describe("기준점 지도 표시", () => {
  it("거리 원은 1·3·5km로 그리고 시설과 연결한 선·거리 표시를 정리한다", () => {
    const { kakao, created } = setup();
    const target = { latitude: 35.41, longitude: 129.3 } as Facility;
    const dispose = referenceMapOverlays(
      kakao as unknown as KakaoSDK,
      {} as KakaoMapInstance,
      point,
      null,
      target,
      true,
    );
    expect(
      created.filter((o) => o.kind === "circle").map((o) => o.options.radius),
    ).toEqual([1000, 3000, 5000]);
    expect(
      created
        .filter((o) => o.kind === "circle")
        .every((o) => o.options.fillOpacity === 0),
    ).toBe(true);
    expect(created.filter((o) => o.kind === "line")).toHaveLength(1);
    const labels = created.filter((o) => o.kind === "label");
    const pin = labels.find(
      (o) => o.options.content.className === "location-reference-pin",
    )!;
    expect(pin.options.content.querySelector("img")).toBeNull();
    expect(pin.options.content.textContent).toContain("<img");
    expect(
      labels.some((o) => o.options.content.textContent === "직선거리 1.1km"),
    ).toBe(true);
    expect(
      labels
        .filter((o) => o.options.content.className === "location-radius-label")
        .map((o) => o.options.content.textContent),
    ).toEqual(["1km", "3km", "5km"]);
    dispose();
    expect(created.every((o) => o.map === null)).toBe(true);
  });
  it("확정 전에는 후보 위치만 표시하고 영향 범위처럼 보이는 원을 그리지 않는다", () => {
    const { kakao, created } = setup();
    referenceMapOverlays(
      kakao as unknown as KakaoSDK,
      {} as KakaoMapInstance,
      point,
      point,
      null,
      true,
    );
    expect(created).toHaveLength(1);
    expect(created[0].options.content.textContent).toContain("확인 전");
  });
  it("거리 원을 끄거나 기준점을 지울 수 있다", () => {
    const { kakao, created } = setup();
    referenceMapOverlays(
      kakao as unknown as KakaoSDK,
      {} as KakaoMapInstance,
      point,
      null,
      null,
      false,
    );
    expect(created.map((o) => o.kind)).toEqual(["label"]);
    const second = setup();
    referenceMapOverlays(
      second.kakao as unknown as KakaoSDK,
      {} as KakaoMapInstance,
      null,
      null,
      null,
      true,
    )();
    expect(second.created).toHaveLength(0);
  });
});
