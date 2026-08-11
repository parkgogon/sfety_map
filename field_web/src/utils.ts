import type {
  Facility,
  MonitoringMode,
  NearbyCctv,
  RiskGrade,
  WeatherResponse,
} from "./types";

export type FacilitySelectionSource =
  | "marker"
  | "same_location"
  | "search"
  | "deep_link";

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

export function formatObservationTime(value: string | null): string {
  if (!value) return "시각 미확인";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "시각 미확인";
  return new Intl.DateTimeFormat("ko-KR", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).format(date);
}

export function windDirectionLabel(value: number | null): string {
  if (value === null || !Number.isFinite(value)) return "풍향 —";
  const labels = ["북", "북동", "동", "남동", "남", "남서", "서", "북서"];
  const normalized = ((value % 360) + 360) % 360;
  const degrees = Number.isInteger(normalized)
    ? String(normalized)
    : normalized.toFixed(1).replace(/\.0$/, "");
  return `${labels[Math.floor((normalized + 22.5) / 45) % 8]} ${degrees}°`;
}

export function weatherSummary(weather: WeatherResponse): string {
  const measurement = (value: number | null, unit: string) =>
    value === null ? "—" : `${value}${unit}`;
  const wind = [
    windDirectionLabel(weather.wind_direction_deg).replace("풍향 ", ""),
    measurement(weather.wind_speed_ms, "m/s"),
  ].join(" ");
  return [
    measurement(weather.temperature_c, "℃"),
    `강수 ${measurement(weather.rainfall_1h_mm, "mm")}`,
    wind,
  ].join(" · ");
}

export function shouldZoomForSelection(source: FacilitySelectionSource): boolean {
  return source === "search" || source === "deep_link";
}

export function cctvDirectionText(cctv: NearbyCctv): string {
  if (cctv.bearing_deg === null) return "촬영방향 미확인";
  const verified = cctv.direction_verified_on
    ? `${cctv.direction_verified_on} 검증`
    : "검증일 미확인";
  return `촬영방향 ${cctv.direction_label} ${cctv.bearing_deg}° · ${verified}`;
}

export function uniqueWarningText(facility: Facility): string {
  if (!facility.reasons.length) {
    return facility.grade === "UNAVAILABLE" ? "KMA 자료 조회 불가" : "현재 영향 특보 없음";
  }
  return [...new Set(facility.reasons.map((item) => `${item.type} ${item.raw_level}`))].join(" · ");
}
