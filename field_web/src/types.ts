export type DataHealth = "LIVE" | "FALLBACK" | "STALE" | "ERROR" | "SIMULATION";
export type ContextStatus = "LIVE" | "NOT_CONFIGURED" | "ERROR";
export type MonitoringMode = "live" | "simulation";
export type WeatherLayerKind = "temperature" | "rainfall" | "wind";
export type RiskGrade =
  | "HIGH"
  | "MEDIUM"
  | "LOW"
  | "UNASSESSED"
  | "NONE"
  | "UNAVAILABLE";

export interface FacilityReason {
  warning_id: string;
  type: string;
  raw_level: string;
  grade: Exclude<RiskGrade, "UNAVAILABLE">;
  region: string;
}

export interface Facility {
  id: string;
  name: string;
  type: string;
  group_id: string;
  group_label: string;
  latitude: number;
  longitude: number;
  address: string;
  public_contact: string;
  grade: RiskGrade;
  grade_label: string;
  grade_color: string;
  meaning: string;
  recommended_action: string;
  reasons: FacilityReason[];
}

export interface FacilityGroup {
  id: string;
  label: string;
  count: number;
}

export interface WeatherResponse {
  api_version: "v1";
  facility_id: string;
  status: "LIVE" | "ERROR";
  observed_at: string;
  temperature_c: number | null;
  rainfall_1h_mm: number | null;
  wind_speed_ms: number | null;
  wind_direction_deg: number | null;
  detail: string;
  source: string;
  actual_data: true;
}

export interface WeatherLayerPoint {
  grid_x: number;
  grid_y: number;
  latitude: number;
  longitude: number;
  value?: number;
  u_ms?: number;
  v_ms?: number;
  speed_ms?: number;
  direction_to_deg?: number;
}

export interface WeatherLayerResponse {
  api_version: "v1";
  layer: WeatherLayerKind;
  status: "LIVE" | "STALE" | "ERROR" | "SIMULATION";
  observed_at: string;
  fetched_at: string;
  unit: string;
  points: WeatherLayerPoint[];
  detail: string;
  source: string;
  scope: string;
  actual_data: boolean;
  scenario_id?: string;
  scenario_label?: string;
}

export interface NearbyCctv {
  id: string;
  name: string;
  latitude: number;
  longitude: number;
  distance_km: number;
  road_type: string;
  video_url: string;
  video_format: string;
  embed_allowed: boolean;
  updated_at: string | null;
  bearing_deg: number | null;
  direction_label: string;
  direction_verified_on: string | null;
  direction_source: string;
}

export interface CctvResponse {
  api_version: "v1";
  facility_id: string;
  status: ContextStatus;
  fetched_at: string;
  detail: string;
  direction_warning: string;
  radius_km: number;
  limit: number;
  cctvs: NearbyCctv[];
  source: string;
  source_url: string;
  official_map_url: string;
  actual_data: true;
}

export interface MapFocusRequest {
  latitude: number;
  longitude: number;
  zoom: boolean;
  revision: number;
}

export interface WarningZoneFeature {
  type: "Feature";
  properties: {
    region_code: string;
    region: string;
    label: string;
    level: string;
    color: string;
  };
  geometry: {
    type: "Polygon" | "MultiPolygon";
    coordinates: number[][][] | number[][][][];
  };
}

export interface MonitoringResponse {
  api_version: "v1";
  generated_at: string;
  status: {
    health: DataHealth;
    fetched_at: string;
    detail: string;
    zone_health: DataHealth;
    zone_detail: string;
  };
  policy: { version: string; temporary: boolean };
  summary: null | {
    active_warning_count: number;
    affected_facility_count: number;
    high_risk_count: number;
    unassessed_count: number;
    highest_warning_level: string;
  };
  groups: FacilityGroup[];
  warnings: Array<{
    id: string;
    region: string;
    type: string;
    raw_level: string;
  }>;
  warning_zones: {
    type: "FeatureCollection";
    features: WarningZoneFeature[];
  };
  facilities: Facility[];
  notices: string[];
}
