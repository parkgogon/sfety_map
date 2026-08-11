import { describe, expect, it } from "vitest";
import type { Facility } from "./types";
import {
  filterFacilities,
  formatReferenceTime,
  requestedFacilityId,
  requestedMonitoringMode,
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
  grade_color: "#e87817",
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
});
