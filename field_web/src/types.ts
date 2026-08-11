export type DataHealth = "LIVE" | "FALLBACK" | "STALE" | "ERROR" | "SIMULATION";
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
