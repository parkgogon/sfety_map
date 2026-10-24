import type { Facility, MonitoringResponse } from "./types";

export function monitoringOutputsAvailable(
  health: MonitoringResponse["status"]["health"],
): boolean {
  return health === "LIVE" || health === "SIMULATION";
}

export function resolveSelectedFacilityScope(
  facilities: readonly Facility[],
  selectedIds: ReadonlySet<string>,
): { ids: string[]; facilities: Facility[] } {
  const selectedFacilities = facilities.filter((facility) =>
    selectedIds.has(facility.id),
  );
  return {
    ids: selectedFacilities.map((facility) => facility.id),
    facilities: selectedFacilities,
  };
}
