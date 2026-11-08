import type { MessageRecord } from "./messageRecordsApi";

export interface MessageSegment {
  index: number; intent: string; evidence: string; starts_at: string | null; ends_at: string | null;
  locations: Array<{text: string; role: string}>;
}
export interface MessageLink {
  parent_id: string; target: MessageRecord; needs_reconfirm: boolean; segments: MessageSegment[];
  edge: {kind: "additional" | "correction" | "release"; reason: string; cross_region_reason: string; confirmed_at: string; revision: number};
}
export interface RelatedDetail { record_version: number; epoch: number; fingerprint: string; links: MessageLink[]; needs_reconfirm: boolean }
export interface RelatedPreview {
  record_version: number; parent: MessageRecord; target: MessageRecord; comparison_token: string;
  regions: {status: "unknown" | "overlap" | "disjoint"; detail: string};
  comparison: {before: MessageSegment[]; after: MessageSegment[]; has_release: boolean; has_active_restriction: boolean; caution: string;
    locations: Array<{text: string; role: string; status: "same_spelling" | "earlier_only" | "followup_only"; before: MessageSegment | null; after: MessageSegment | null}>};
}
