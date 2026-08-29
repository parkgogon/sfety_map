import type {
  Facility,
  MonitoringMode,
  NearbyCctv,
  RiskGrade,
  WeatherResponse,
  WeatherLayerKind,
} from "./types";

export type FacilitySelectionSource =
  | "marker"
  | "same_location"
  | "search"
  | "deep_link";

/** 화면 범례 순서. 위험 우선순위 계산에는 사용하지 않습니다. */
export const GRADE_DISPLAY_ORDER: RiskGrade[] = [
  "HIGH",
  "MEDIUM",
  "LOW",
  "NONE",
  "UNASSESSED",
  "UNAVAILABLE",
];

/** 클러스터 대표 시설 등 운영 판단에 사용하는 기존 우선순위. */
export const GRADE_PRIORITY_ORDER: RiskGrade[] = [
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
  HIGH: "var(--color-risk-high)",
  MEDIUM: "var(--color-risk-medium)",
  LOW: "var(--color-risk-low)",
  UNASSESSED: "var(--color-risk-unassessed)",
  NONE: "var(--color-risk-none)",
  UNAVAILABLE: "var(--color-risk-unavailable)",
};

export const WEATHER_LAYER_LABELS: Record<WeatherLayerKind, string> = {
  rainfall: "강수",
  wind: "바람",
  temperature: "기온",
};

type ColorStop = readonly [number, string, string];

const TEMPERATURE_STOPS: readonly ColorStop[] = [
  [-20, "--color-weather-temp-cold", "#2563eb"],
  [0, "--color-weather-temp-cool", "#06b6d4"],
  [15, "--color-weather-temp-mild", "#22c55e"],
  [25, "--color-weather-temp-warm", "#facc15"],
  [32, "--color-weather-temp-hot", "#f97316"],
  [40, "--color-weather-temp-extreme", "#dc2626"],
];
const RAINFALL_STOPS: readonly ColorStop[] = [
  [0.1, "--color-weather-rain-trace", "#60a5fa"],
  [1, "--color-weather-rain-light", "#2563eb"],
  [5, "--color-weather-rain-moderate", "#4f46e5"],
  [15, "--color-weather-rain-heavy", "#7e22ce"],
  [30, "--color-weather-rain-severe", "#be123c"],
  [60, "--color-weather-rain-extreme", "#7f1d1d"],
];
const WIND_STOPS: readonly ColorStop[] = [
  [0, "--color-weather-wind-calm", "#38bdf8"],
  [4, "--color-weather-wind-gentle", "#14b8a6"],
  [8, "--color-weather-wind-strong", "#eab308"],
  [14, "--color-weather-wind-gale", "#f97316"],
  [25, "--color-weather-wind-severe", "#dc2626"],
];

const DESIGN_COLOR_CACHE = new Map<string, string>();

function designColor(token: string, fallback: string): string {
  const cached = DESIGN_COLOR_CACHE.get(token);
  if (cached) return cached;
  if (typeof document === "undefined") return fallback;
  const value = getComputedStyle(document.documentElement).getPropertyValue(token).trim();
  const result = /^#[0-9a-f]{6}$/i.test(value) ? value : fallback;
  DESIGN_COLOR_CACHE.set(token, result);
  return result;
}

function hexRgb(value: string): [number, number, number] {
  const normalized = value.replace("#", "");
  return [
    Number.parseInt(normalized.slice(0, 2), 16),
    Number.parseInt(normalized.slice(2, 4), 16),
    Number.parseInt(normalized.slice(4, 6), 16),
  ];
}

function scaleColorChannels(value: number, stops: readonly ColorStop[]): [number, number, number] {
  const finite = Number.isFinite(value) ? value : stops[0][0];
  let lower = stops[0];
  let upper = stops[stops.length - 1];
  for (let index = 1; index < stops.length; index += 1) {
    if (finite <= stops[index][0]) {
      upper = stops[index];
      lower = stops[index - 1];
      break;
    }
    lower = stops[index];
  }
  const span = Math.max(0.0001, upper[0] - lower[0]);
  const ratio = Math.min(1, Math.max(0, (finite - lower[0]) / span));
  const left = hexRgb(designColor(lower[1], lower[2]));
  const right = hexRgb(designColor(upper[1], upper[2]));
  return left.map((channel, index) =>
    Math.round(channel + (right[index] - channel) * ratio)) as [number, number, number];
}

function scaleColor(value: number, stops: readonly ColorStop[], alpha: number): string {
  const channels = scaleColorChannels(value, stops);
  return `rgba(${channels[0]},${channels[1]},${channels[2]},${alpha})`;
}

export function weatherColorChannels(
  kind: WeatherLayerKind,
  value: number,
): [number, number, number] {
  if (kind === "temperature") return scaleColorChannels(value, TEMPERATURE_STOPS);
  if (kind === "rainfall") return scaleColorChannels(value, RAINFALL_STOPS);
  return scaleColorChannels(value, WIND_STOPS);
}

export function temperatureColor(value: number, alpha = 1): string {
  return scaleColor(value, TEMPERATURE_STOPS, alpha);
}

export function rainfallColor(value: number, alpha = 1): string {
  if (!Number.isFinite(value) || value <= 0) return "rgba(0,0,0,0)";
  return scaleColor(value, RAINFALL_STOPS, alpha);
}

export function windSpeedColor(value: number, alpha = 1): string {
  return scaleColor(value, WIND_STOPS, alpha);
}

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

export function searchFacilities(
  facilities: Facility[],
  search: string,
  limit = 8,
): Facility[] {
  const needle = normalizeSearch(search);
  if (!needle) return [];
  const results: Facility[] = [];
  for (const facility of facilities) {
    if (normalizeSearch(`${facility.name} ${facility.address} ${facility.type}`).includes(needle)) {
      results.push(facility);
      if (results.length >= limit) break;
    }
  }
  return results;
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

export function formatElapsedTime(value: string, now = new Date()): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  const elapsedMs = Math.max(0, now.getTime() - date.getTime());
  const elapsedMinutes = Math.floor(elapsedMs / (1000 * 60));
  if (elapsedMinutes < 1) return "방금 전";
  if (elapsedMinutes < 60) return `${elapsedMinutes}분 전`;
  const elapsedHours = Math.floor(elapsedMinutes / 60);
  if (elapsedHours < 24) return `${elapsedHours}시간 전`;
  const elapsedDays = Math.floor(elapsedHours / 24);
  return `${elapsedDays}일 전`;
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

export function shouldShowMapZoomControl(viewportWidth: number): boolean {
  return viewportWidth > 700;
}

export function recommendedWeatherLayer(
  warnings: Array<{ type?: string; warning_type?: string }>,
): WeatherLayerKind | null {
  const isType = (item: { type?: string; warning_type?: string }, pattern: string) => {
    const t = item.type ?? item.warning_type ?? "";
    return t.includes(pattern);
  };
  if (warnings.some((w) => isType(w, "태풍") || isType(w, "강풍"))) {
    return "wind";
  }
  if (warnings.some((w) => isType(w, "호우") || isType(w, "대설"))) {
    return "rainfall";
  }
  if (warnings.some((w) => isType(w, "폭염") || isType(w, "한파"))) {
    return "temperature";
  }
  return null;
}

export function shouldFitInitialFacilities(
  initialBoundsFitted: boolean,
  facilityCount: number,
): boolean {
  return !initialBoundsFitted && facilityCount > 0;
}

export function cctvDirectionText(cctv: NearbyCctv): string {
  if (cctv.bearing_deg === null) return "촬영방향 미확인";
  const verified = cctv.direction_verified_on
    ? `${cctv.direction_verified_on} 검증`
    : "검증일 미확인";
  return `촬영방향 ${cctv.direction_label} ${cctv.bearing_deg}° · ${verified}`;
}

export function uniqueWarningText(facility: Facility): string {
  const activeReasons = facility.reasons.filter((item) => item.grade !== "NONE");
  if (!activeReasons.length) {
    return facility.grade === "UNAVAILABLE" ? "KMA 자료 조회 불가" : "현재 영향 특보 없음";
  }
  return [...new Set(activeReasons.map((item) => `${item.type} ${item.raw_level}`))].join(" · ");
}
