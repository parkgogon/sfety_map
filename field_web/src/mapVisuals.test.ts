import { describe, expect, it } from "vitest";
import {
  CLUSTER_GRID_SIZE,
  CLUSTER_MARKER_SIZE,
  CLUSTER_MIN_LEVEL,
  CLUSTER_MIN_SIZE,
  FACILITY_MARKER_SIZE,
  MAP_MARKER_Z_INDEX,
  SAME_LOCATION_MARKER_SIZE,
  SELECTED_MARKER_SIZE,
  facilityMarkerSize,
} from "./mapVisuals";

describe("지도 마커 시각 규칙", () => {
  it("위험등급과 무관하게 단일 시설의 기본 크기를 30px로 고정한다", () => {
    expect(FACILITY_MARKER_SIZE).toBe(30);
    expect(facilityMarkerSize(1, false)).toBe(30);
  });

  it("같은 위치 시설과 선택 시설만 필요한 만큼 확대한다", () => {
    expect(SAME_LOCATION_MARKER_SIZE).toBe(34);
    expect(SELECTED_MARKER_SIZE).toBe(44);
    expect(facilityMarkerSize(2, false)).toBe(34);
    expect(facilityMarkerSize(1, true)).toBe(44);
    expect(facilityMarkerSize(3, true)).toBe(44);
  });

  it("클러스터를 한 단계 늦게 만들고 묶음 범위를 줄인다", () => {
    expect(CLUSTER_MIN_LEVEL).toBe(9);
    expect(CLUSTER_GRID_SIZE).toBe(48);
    expect(CLUSTER_MIN_SIZE).toBe(2);
    expect(CLUSTER_MARKER_SIZE).toBe(38);
  });

  it("시설과 클러스터를 기상 canvas보다 높은 4번 레이어에 둔다", () => {
    expect(MAP_MARKER_Z_INDEX).toBe(4);
  });
});
