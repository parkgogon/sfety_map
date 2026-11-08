import type { MessageRecord } from "./messageRecordsApi";
import type { MessageAnalysisResult } from "./messageAnalysisApi";

export interface SpatialFacility {
  id: string; name: string; facility_type: string; address: string;
  latitude: number; longitude: number; distance_m: number; within_radius: boolean; reason?: string;
}
export interface MessageReference {
  revision: number; location_key: string; role: string; evidence: string;
  analysis_revision: number; source_revision: number;
  point: { latitude: number; longitude: number; label: string; address: string;
    source: "candidate" | "map" | "coordinate"; candidate_id: string | null; scope_matches_source: boolean };
  radius_km: 1 | 3 | 5 | 10; confirmation_note: string; confirmed_at: string; catalog_digest: string;
  nearby_count: number; selected: SpatialFacility[]; selection_note: string;
  selection_saved_at: string | null; selection_needs_review: boolean;
}
export interface SpatialLocation {
  key: string; text: string; role: string; intent: string; evidence: string; eligible: boolean;
  candidates: MessageAnalysisResult["candidates"]; reference: MessageReference | null; catalog_current: boolean;
}
export interface SpatialDetail {
  record_version: number; analysis_revision: number; catalog_digest: string;
  locations: SpatialLocation[]; reset_reason: string;
}
export interface SpatialPage {
  facilities: SpatialFacility[]; total_count: number; offset: number; next_offset: number | null;
  catalog_digest: string; catalog_current: boolean; reference_revision: number; record_version: number;
  map_facilities: SpatialFacility[];
}
export interface SpatialProps {
  token: string; record: MessageRecord; disabled: boolean;
  onRecordChanged: (record: MessageRecord) => void; onBusyChange: (busy: boolean) => void; onDirtyChange?: (dirty: boolean) => void;
}
