import { describe, expect, it } from "vitest";
import { distanceMeters, formatDistance, nearbyFacilities, referenceBounds, validCoordinate } from "./locationReference";
import type { Facility } from "./types";

describe("기준점 거리 계산", () => {
  it("동일 좌표와 알려진 적도 1도 거리를 계산한다", () => {
    const origin = { latitude: 0, longitude: 0 };
    expect(distanceMeters(origin, origin)).toBe(0);
    expect(distanceMeters(origin, { latitude: 0, longitude: 1 })).toBeCloseTo(111195.08, 1);
    expect(distanceMeters(origin, { latitude: 0, longitude: 180 })).toBeCloseTo(20015114.44, 1);
  });
  it("거리순으로 모든 시설을 유지하고 같은 거리에서도 ID로 구분한다", () => {
    const facilities = [
      { id: "B", latitude: 35, longitude: 129 },
      { id: "C", latitude: 36, longitude: 129 },
      { id: "A", latitude: 35, longitude: 129 },
      { id: "invalid", latitude: NaN, longitude: 129 },
    ] as Facility[];
    expect(nearbyFacilities(facilities, { latitude: 35, longitude: 129 }).map((row) => row.facility.id)).toEqual(["A", "B", "C"]);
    expect(facilities[0].id).toBe("B");
  });
  it("유효 좌표와 직선거리 표시, 5km 표시 범위를 제공한다", () => {
    expect(validCoordinate({ latitude: 91, longitude: 129 })).toBe(false);
    expect(formatDistance(0)).toBe("0m");
    expect(formatDistance(820)).toBe("820m");
    expect(formatDistance(2400)).toBe("2.4km");
    const bounds = referenceBounds({ latitude: 35, longitude: 129 });
    expect(bounds[0].latitude).toBeLessThan(35);
    expect(bounds[1].longitude).toBeGreaterThan(129);
  });
});
