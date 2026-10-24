import type { KakaoSDK } from "./kakaoTypes";
import { afterEach, describe, expect, it, vi } from "vitest";
import { loadKakaoMaps } from "./kakao";
import { searchLocations } from "./locationSearch";

vi.mock("./kakao", () => ({ loadKakaoMaps: vi.fn() }));
function sdk(place: Function, address: Function) {
  vi.mocked(loadKakaoMaps).mockResolvedValue({
    maps: {
      services: {
        Status: { OK: "OK", ZERO_RESULT: "ZERO_RESULT" },
        Places: class {
          keywordSearch = place;
        },
        Geocoder: class {
          addressSearch = address;
        },
      },
    },
  } as unknown as KakaoSDK);
}
afterEach(() => {
  vi.useRealTimers();
  vi.clearAllMocks();
});

describe("장소·주소 검색", () => {
  it("장소와 주소를 함께 검색하고 좌표 형식과 중복을 정리한다", async () => {
    const place = vi.fn((_q, cb) =>
      cb(
        [
          { x: "129.3", y: "35.4", place_name: "공장", address_name: "울산" },
          { x: "", y: "35.4", place_name: "잘못된 위치" },
          { x: "200", y: "35.4", place_name: "범위 밖" },
        ],
        "OK",
      ),
    );
    const address = vi.fn((_q, cb) =>
      cb(
        [
          { x: "129.3", y: "35.4", address_name: "울산 온산읍" },
          { x: "129.3", y: "35.4", address_name: "울산 온산읍" },
        ],
        "OK",
      ),
    );
    sdk(place, address);
    const result = await searchLocations("  온산  ");
    expect(place.mock.calls[0][0]).toBe("온산");
    expect(address.mock.calls[0][0]).toBe("온산");
    expect(result.points).toHaveLength(2);
    expect(result.points[0]).toMatchObject({
      label: "공장",
      latitude: 35.4,
      longitude: 129.3,
      source: "place",
    });
    expect(result.partial).toBe(false);
  });
  it("검색 결과 없음과 서비스 실패를 구분한다", async () => {
    sdk(
      (_q: string, cb: Function) => cb([], "ZERO_RESULT"),
      (_q: string, cb: Function) => cb([], "ZERO_RESULT"),
    );
    await expect(searchLocations("없는 주소")).resolves.toEqual({
      points: [],
      partial: false,
    });
    sdk(
      (_q: string, cb: Function) => cb([], "ERROR"),
      (_q: string, cb: Function) => cb([], "ERROR"),
    );
    await expect(searchLocations("공장")).rejects.toThrow();
  });
  it("주소 검색만 성공해도 그 결과와 부분 실패를 전달한다", async () => {
    sdk(
      (_q: string, cb: Function) => cb([], "ERROR"),
      (_q: string, cb: Function) =>
        cb([{ x: "129", y: "35", address_name: "주소" }], "OK"),
    );
    const result = await searchLocations("주소");
    expect(result.partial).toBe(true);
    expect(result.points[0].source).toBe("address");
  });
  it("SDK가 응답하지 않아도 제한시간 후 검색을 종료한다", async () => {
    vi.useFakeTimers();
    vi.mocked(loadKakaoMaps).mockImplementation(() => new Promise(() => {}));
    const assertion = expect(searchLocations("공장")).rejects.toThrow(
      "검색 시간 초과",
    );
    await vi.advanceTimersByTimeAsync(12000);
    await assertion;
  });
});
