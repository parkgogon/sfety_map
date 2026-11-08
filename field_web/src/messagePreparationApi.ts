import type { SpatialFacility, MessageReference } from "./messageSpatialApi";
import type { MessageAnalysisResult } from "./messageAnalysisApi";

export interface ReviewLocationChoice {
  location_key: string;
  point?: { mode: "candidate" | "manual"; candidate_id?: string; latitude?: number; longitude?: number; label?: string; manual_source?: "map" | "coordinate" };
  radius_km?: 1 | 3 | 5 | 10;
  facilities?: Array<{ facility_id: string; reason?: string }>;
  reference_acknowledged?: boolean;
  excluded_reason?: "reference_only" | "outside_scope" | "other";
  note?: string;
}
export interface PrepareReviewInput {
  expected_version: number; choices: ReviewLocationChoice[]; manager_note: string;
  outcome?: "facilities_selected" | "no_action";
  no_action_reason?: "reference_only" | "outside_scope" | "other";
  uncertainty_acknowledged?: boolean;
}
export interface PreparedReview {
  record_version: number; proposal_hash: string; catalog_digest: string;
  outcome: "facilities_selected" | "no_action"; selected_count: number; ready: boolean;
  issues: string[]; questions: string[]; uncertain_time: boolean; notice_preview: string;
  locations: Array<{
    key: string; text: string; role: string; evidence: string;
    candidates: MessageAnalysisResult["candidates"];
    point: MessageReference["point"] | null; radius_km: 1 | 3 | 5 | 10;
    facilities: SpatialFacility[]; selected: SpatialFacility[];
    reference_required: boolean; representative: boolean; excluded_reason: string | null; saved_work: boolean;
    removed_facilities?: Array<{id:string;name:string}>;
  }>;
}
