export interface ReviewCompletion {
  outcome: "facilities_selected" | "no_action"; reason: string; follow_up_note: string;
  excluded_locations: Record<string, string>; completed_at: string; basis_hash: string; selected_unique_count: number;
}
export interface NoticeDraft {
  revision: number; template_version: number; basis_hash: string; manager_note: string; text: string; updated_at: string;
}
export interface MessageReviewDetail {
  record_version: number; review_state: "unreviewed" | "needs_confirmation" | "completed";
  completion: ReviewCompletion | null; completion_current: boolean; draft: NoticeDraft | null;
  draft_current: boolean; stale_reason: string;
  related_count?: number;
  locations: Array<{key: string; text: string; selected_count: number}>;
}
