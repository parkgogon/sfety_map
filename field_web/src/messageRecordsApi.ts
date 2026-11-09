import type { ReviewCompletion, NoticeDraft } from "./messageReviewApi";
import type { MessageReference } from "./messageSpatialApi";
import type { MessageAnalysisResult, MessageInput } from "./messageAnalysisApi";
import type { PrepareReviewInput } from "./messagePreparationApi";

export interface MessageSource {
  text: string; source: string; issued_at: string | null; recipient_regions: string[];
}
export interface MessageRecord {
  id: string; version: number; origin: "manual" | "example" | "official";
  message: MessageSource; created_at: string; updated_at: string; source_revision: number;
  analysis_state: "not_analyzed" | "running" | "completed" | "failed";
  review_state: "unreviewed" | "needs_confirmation" | "completed"; note: string;
  analysis?: MessageAnalysisResult | null; analysis_revision: number; analysis_error: string;
  reference_radius_km: MessageInput["reference_radius_km"];
  spatial_references?: Record<string, MessageReference>;
  review_completion?: ReviewCompletion | null; notice_draft?: NoticeDraft | null; review_reopen_reason?: string;
  relation_epoch?: number;
  related_messages?: Record<string,{kind:"additional"|"correction"|"release";reason:string;target_source_revision:number;target_analysis_revision:number}>;
  review_working_copy?: { input: PrepareReviewInput; source_revision:number; analysis_revision:number; saved_at_version:number };
  relation_last_change?: {action:string;target_id:string;reason:string;at:string}|null;
}
export interface RecordStatus { storage_configured: boolean; storage_mode: string; feed_configured: boolean; auto_collection_enabled?: boolean; notification_preparation_enabled?:boolean }
export interface MessageAutomation {
  auto_collection_enabled: boolean; feed_configured: boolean; interval_seconds: number;
  state: "disabled"|"needs_key"|"needs_verification"|"starting"|"live"|"partial"|"stale"|"error"|"store_unavailable"|"request_limit";
  detail: string; last_attempt_at: string|null; last_success_at: string|null; start_at: string|null;
  queue: Record<"pending"|"running"|"done"|"failed"|"obsolete"|"deferred",number>|null;
  budget: { limit:number; attempts:number|null; remaining:number|null; active:boolean };
  feed_budget?: { limit:number; used:number; remaining:number; window_hours:number; next_available_at:string|null };
  latest_first_enabled?: boolean; last_latest_success_at?:string|null; last_backfill_success_at?:string|null;
  recent_scan_enabled?:boolean; last_current_scan_success_at?:string|null; current_scan_interval_seconds?:number;
  spend_budget?: { enabled:boolean; currency?:string; reservation_usd?:number; can_start?:boolean; blocked?:boolean;
    daily?: { limit_usd:number; settled_usd:number; reserved_usd:number; unsettled_calls:number };
    monthly?: { limit_usd:number; settled_usd:number; reserved_usd:number; unsettled_calls:number } };
}
export interface RecordPage { records: MessageRecord[]; next_cursor: string | null }
export interface OfficialPage {
  status: "LIVE" | "NOT_CONFIGURED"; detail: string;
  region?: string; date?: string; page?: number; has_more?: boolean; page_limit_reached?: boolean; skipped?: number;
  messages: Array<{ official_id: string; message: MessageSource; import_token: string; disaster_type: string; emergency_step: string }>;
}
export interface RecordHistory { versions: Array<{ event: string; record: MessageRecord }>; next_cursor: number | null }

export async function recordRequest<T>(token: string, signal: AbortSignal, path = "", body?: unknown, method = "POST"): Promise<T> {
  const headers: Record<string, string> = {};
  if (token && token !== "active-session") headers["X-Alert-Admin-Token"] = token;
  if (body !== undefined) headers["Content-Type"] = "application/json";
  const response = await fetch(`/internal/v1/message-records${path}`, {
    method: body === undefined ? "GET" : method, credentials: "same-origin", headers, signal,
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });
  if (!response.ok) {
    const value = await response.json().catch(() => ({})) as { detail?: unknown };
    throw new Error(typeof value.detail === "string" ? value.detail : "기록을 조회하거나 저장하지 못했습니다.");
  }
  return response.json() as Promise<T>;
}
