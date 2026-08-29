export const FACILITY_MARKER_SIZE = 30;
export const SAME_LOCATION_MARKER_SIZE = 34;
export const SELECTED_MARKER_SIZE = 44;
export const CLUSTER_MARKER_SIZE = 38;

export const MAP_MARKER_Z_INDEX = 4;
export const CLUSTER_MIN_LEVEL = 9;
export const CLUSTER_GRID_SIZE = 48;
export const CLUSTER_MIN_SIZE = 2;

export function facilityMarkerSize(facilityCount: number, selected: boolean): number {
  if (selected) return SELECTED_MARKER_SIZE;
  return facilityCount > 1 ? SAME_LOCATION_MARKER_SIZE : FACILITY_MARKER_SIZE;
}
