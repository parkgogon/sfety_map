export interface MessageInput {
  text: string;
  source: string;
  issued_at: string;
  reference_radius_km: 1 | 3 | 5 | 10;
  input_kind: "example" | "manual";
}

export const INTENT_LABELS = {
  event: "사고·재난 발생", prevention: "예방 안내", advisory: "일반 안내",
  scheduled_restriction: "예정된 통제", active_restriction: "통제 중",
  release: "해제", correction: "정정", unknown: "판단 보류",
};

export const ROLE_LABELS = {
  incident_site: "발생 장소", restricted_area: "통제 대상", evacuation_area: "대피 대상 지역",
  evacuation_destination: "대피 목적지", reference: "참고 장소",
};

export interface MessageAnalysisResult {
  input: MessageInput;
  analysis: {
    summary: string;
    parts: Array<{
      intent: keyof typeof INTENT_LABELS;
      description: string;
      evidence: string;
      time_text: string;
      starts_at: string | null;
      ends_at: string | null;
      locations: Array<{
        text: string; role: keyof typeof ROLE_LABELS; evidence: string; candidate_ids: string[];
      }>;
    }>;
    questions: string[];
  };
  review_required: true;
  candidates: Array<{ id: string; name: string; address: string; latitude: number; longitude: number; query: string; evidence: string }>;
  nearby: Array<{
    candidate_id: string; total_count: number; shown_count: number;
    facilities: Array<{ id: string; name: string; facility_type: string; address: string; distance_m: number }>;
  }>;
  trace: Array<{ tool: string; detail: string; status: string }>;
  model: string;
  model_calls: number;
  elapsed_ms: number;
}

export interface MessageAnalysisStatus {
  configured: boolean;
  place_search_configured: boolean;
  model: string;
}

export async function messageRequest<T>(token: string, signal: AbortSignal, input?: MessageInput): Promise<T> {
  const headers: Record<string, string> = {};
  if (token && token !== "active-session") headers["X-Alert-Admin-Token"] = token;
  if (input) headers["Content-Type"] = "application/json";
  const response = await fetch(`/internal/v1/message-analysis${input ? "" : "/status"}`, {
    method: input ? "POST" : "GET", headers, credentials: "same-origin", signal,
    ...(input ? { body: JSON.stringify(input) } : {}),
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({})) as { detail?: unknown };
    throw new Error(typeof data.detail === "string" ? data.detail : "문자 분석에 실패했습니다. 입력과 연결 상태를 확인해 주세요.");
  }
  return response.json() as Promise<T>;
}
