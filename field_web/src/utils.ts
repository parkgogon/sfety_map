import type { Facility, MonitoringMode, RiskGrade } from "./types";

export const GRADE_ORDER: RiskGrade[] = [
  "HIGH",
  "UNAVAILABLE",
  "UNASSESSED",
  "MEDIUM",
  "LOW",
  "NONE",
];

export const GRADE_LABELS: Record<RiskGrade, string> = {
  HIGH: "상",
  MEDIUM: "중",
  LOW: "하",
  UNASSESSED: "미판정",
  NONE: "영향 없음",
  UNAVAILABLE: "조회 불가",
};

export const GRADE_COLORS: Record<RiskGrade, string> = {
  HIGH: "#d92d20",
  MEDIUM: "#e87817",
  LOW: "#b58900",
  UNASSESSED: "#667085",
  NONE: "#247ba0",
  UNAVAILABLE: "#667085",
};

export function normalizeSearch(value: string): string {
  return value.toLocaleLowerCase("ko-KR").replace(/\s+/g, "");
}

export function filterFacilities(
  facilities: Facility[],
  groupIds: ReadonlySet<string>,
  grades: ReadonlySet<RiskGrade>,
  search: string,
): Facility[] {
  const needle = normalizeSearch(search);
  return facilities.filter((facility) => {
    if (!groupIds.has(facility.group_id) || !grades.has(facility.grade)) return false;
    if (!needle) return true;
    return normalizeSearch(`${facility.name} ${facility.address} ${facility.type}`).includes(needle);
  });
}

export function requestedFacilityId(search: string): string {
  return new URLSearchParams(search).get("facility_id")?.trim().slice(0, 128) ?? "";
}

export function requestedMonitoringMode(search: string): MonitoringMode {
  return new URLSearchParams(search).get("mode") === "simulation"
    ? "simulation"
    : "live";
}

export function formatReferenceTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "시각 미확인";
  return new Intl.DateTimeFormat("ko-KR", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(date);
}

export function uniqueWarningText(facility: Facility): string {
  if (!facility.reasons.length) {
    return facility.grade === "UNAVAILABLE" ? "KMA 자료 조회 불가" : "현재 영향 특보 없음";
  }
  return [...new Set(facility.reasons.map((item) => `${item.type} ${item.raw_level}`))].join(" · ");
}
