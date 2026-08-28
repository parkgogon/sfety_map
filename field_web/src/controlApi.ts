import { useCallback, useEffect, useState } from "react";

const ADMIN_TOKEN_KEY = "keco_admin_token";

export interface HealthCheckItem {
  name: string;
  healthy: boolean;
  detail: string;
}

export interface ControlOverview {
  checked_at?: string;
  healthy?: boolean;
  worker_fresh?: boolean;
  worker_detail?: string;
  kma_health?: string;
  last_run_at?: string | null;
  mode?: string;
  user_delivery_mode?: string;
  daily_cap?: number;
  sms_today?: number;
  sms_month?: number;
  checks?: HealthCheckItem[];
}


export interface AlertMetrics {
  from: string;
  to: string;
  total_auto_batches: number;
  total_auto_facilities: number;
  total_manual_batches: number;
  total_manual_facilities: number;
  total_telegram_sent: number;
  total_sms_sent: number;
  daily_breakdown: Array<{
    date: string;
    auto_batches: number;
    auto_facilities: number;
    manual_batches: number;
    manual_facilities: number;
    telegram_messages: number;
    sms_messages: number;
  }>;
}

export interface AlertEvent {
  id: string;
  timestamp: string;
  source: "automatic" | "manual";
  category: string;
  event_type: string;
  facility_count: number;
  facilities: string[];
  status: string;
  detail: string;
}

export function getStoredAdminToken(): string {
  if (typeof window === "undefined") return "";
  return window.sessionStorage.getItem(ADMIN_TOKEN_KEY) || "";
}

export function setStoredAdminToken(token: string): void {
  if (typeof window === "undefined") return;
  if (token) {
    window.sessionStorage.setItem(ADMIN_TOKEN_KEY, token);
  } else {
    window.sessionStorage.removeItem(ADMIN_TOKEN_KEY);
  }
}

export interface AdminSessionStatus {
  authenticated: boolean;
  created_at?: number;
  expires_at?: number;
}

export async function checkAdminSession(token = ""): Promise<AdminSessionStatus> {
  try {
    const headers: Record<string, string> = {};
    if (token) headers["X-Alert-Admin-Token"] = token;
    const response = await fetch("/internal/v1/admin/session", {
      headers,
      credentials: "same-origin",
    });
    if (!response.ok) return { authenticated: false };
    return (await response.json()) as AdminSessionStatus;
  } catch {
    return { authenticated: false };
  }
}

export async function logoutAdmin(): Promise<void> {
  try {
    await fetch("/internal/v1/admin/logout", {
      method: "POST",
      credentials: "same-origin",
    });
  } catch {
    // 무시
  } finally {
    setStoredAdminToken("");
  }
}

export async function verifyAdminPassword(password: string): Promise<string> {
  const response = await fetch("/internal/v1/admin/access", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "same-origin",
    body: JSON.stringify({ password }),
  });
  if (!response.ok) {
    if (response.status === 429) {
      throw new Error("인증 실패가 반복되었습니다. 5분 후 다시 시도해 주세요.");
    }
    throw new Error("관리자 비밀번호가 올바르지 않습니다.");
  }
  const data = (await response.json().catch(() => ({}))) as { token?: string };
  const token = data.token || password;
  setStoredAdminToken(token);
  return token;
}

export function useControlOverview(token: string) {
  const [data, setData] = useState<ControlOverview | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchOverview = useCallback(async () => {
    if (!token) {
      setData(null);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const response = await fetch("/internal/v1/notifications/overview", {
        headers: { "X-Alert-Admin-Token": token },
        credentials: "same-origin",
      });
      if (response.status === 403) {
        setStoredAdminToken("");
        throw new Error("관리자 인증이 만료되었습니다. 다시 로그인해 주세요.");
      }
      if (!response.ok) {
        throw new Error(`개요 정보를 불러오지 못했습니다 (${response.status})`);
      }
      const json = await response.json() as ControlOverview;
      setData(json);
    } catch (err) {
      setError(err instanceof Error ? err.message : "통계 통신 실패");
    } finally {
      setLoading(false);
    }
  }, [token]);


  useEffect(() => {
    void fetchOverview();
  }, [fetchOverview]);

  return { data, loading, error, refresh: fetchOverview };
}

export function useAlertMetrics(token: string, fromDate: string, toDate: string) {
  const [data, setData] = useState<AlertMetrics | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchMetrics = useCallback(async () => {
    if (!token || !fromDate || !toDate) return;
    setLoading(true);
    setError(null);
    try {
      const response = await fetch(
        `/internal/v1/notifications/metrics?from=${fromDate}&to=${toDate}`,
        {
          headers: { "X-Alert-Admin-Token": token },
          credentials: "same-origin",
        },
      );
      if (!response.ok) {
        throw new Error(`통계 자료를 불러오지 못했습니다 (${response.status})`);
      }
      const json = await response.json() as AlertMetrics;
      setData(json);
    } catch (err) {
      setError(err instanceof Error ? err.message : "지표 통신 실패");
    } finally {
      setLoading(false);
    }
  }, [token, fromDate, toDate]);

  useEffect(() => {
    void fetchMetrics();
  }, [fetchMetrics]);

  return { data, loading, error, refresh: fetchMetrics };
}

export function useAlertEvents(token: string, fromDate: string, toDate: string, source = "all") {
  const [data, setData] = useState<AlertEvent[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchEvents = useCallback(async () => {
    if (!token || !fromDate || !toDate) return;
    setLoading(true);
    setError(null);
    try {
      const response = await fetch(
        `/internal/v1/notifications/events?from=${fromDate}&to=${toDate}&source=${source}&limit=100`,
        {
          headers: { "X-Alert-Admin-Token": token },
          credentials: "same-origin",
        },
      );
      if (!response.ok) {
        throw new Error(`이력 자료를 불러오지 못했습니다 (${response.status})`);
      }
      const json = await response.json() as { events: AlertEvent[] };
      setData(json.events || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : "이력 통신 실패");
    } finally {
      setLoading(false);
    }
  }, [token, fromDate, toDate, source]);

  useEffect(() => {
    void fetchEvents();
  }, [fetchEvents]);

  return { data, loading, error, refresh: fetchEvents };
}

export interface ManualDispatchPayload {
  request_id: string;
  category: "REMINDER" | "CORRECTION" | "ADDITIONAL" | "DRILL";
  mode: "live" | "simulation";
  note: string;
  facility_ids: string[];
  warning_keys: string[];
  messages: Array<{
    text: string;
    silent: boolean;
    action_label?: string;
    action_url?: string;
  }>;
  policy_version?: string;
  temporary_policy?: boolean;
  allow_duplicate?: boolean;
}

export async function dispatchManualTelegram(
  token: string,
  payload: ManualDispatchPayload,
): Promise<{ status: string; dispatch_id: string; message_count: number }> {
  const response = await fetch("/internal/v1/notifications/manual", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Alert-Admin-Token": token,
    },
    credentials: "same-origin",
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    if (response.status === 409) {
      const errorJson = await response.json().catch(() => ({ detail: "중복 발송" }));
      const detailMsg = typeof errorJson.detail === "object" ? errorJson.detail.message : errorJson.detail;
      throw new Error(`중복 발송 경고: ${detailMsg || "동일한 내용이 최근에 발송되었습니다."}`);
    }
    const errorJson = await response.json().catch(() => ({ detail: "발송 실패" }));
    throw new Error(errorJson.detail || `수동 전파에 실패했습니다 (${response.status})`);
  }

  return await response.json();
}

export function getReportPdfUrl(
  token: string = "",
  mode: "live" | "simulation" = "live",
  facilityIds: string[] = [],
  scopeLabel = "전체 소관시설",
): string {
  const params = new URLSearchParams();
  params.set("mode", mode);
  if (facilityIds.length > 0) {
    params.set("facility_ids", facilityIds.join(","));
  }
  params.set("scope_label", scopeLabel);
  if (token) {
    params.set("token", token);
  }
  return `/internal/v1/monitoring/report.pdf?${params.toString()}`;
}

export async function downloadReportPdf(
  token: string = "",
  mode: "live" | "simulation" = "live",
  facilityIds: string[] = [],
  scopeLabel = "전체 소관시설",
): Promise<void> {
  const url = getReportPdfUrl(token, mode, facilityIds, scopeLabel);
  const response = await fetch(url, {
    headers: token ? { "X-Alert-Admin-Token": token } : {},
    credentials: "same-origin",
  });
  if (!response.ok) {
    const errorJson = (await response.json().catch(() => ({ detail: "" }))) as { detail?: string };
    throw new Error(errorJson.detail || "PDF 보고서를 다운로드하지 못했습니다.");
  }
  const blob = await response.blob();
  const downloadUrl = window.URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = downloadUrl;
  const now = new Date();
  const dateStr = `${now.getFullYear()}${String(now.getMonth() + 1).padStart(2, "0")}${String(now.getDate()).padStart(2, "0")}`;
  a.download = `keco_safety_report_${dateStr}.pdf`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  window.URL.revokeObjectURL(downloadUrl);
}


export interface PolicyGradeDef {
  rank: number;
  label: string;
  meaning: string;
  action: string;
  color: string;
}

export interface PolicyResponse {
  version: string;
  description: string;
  default_grade: string;
  grades: Record<string, PolicyGradeDef>;
  warning_types: Record<string, Record<string, string>>;
}

const TEMPORARY_POLICY_KEY = "keco_temporary_risk_matrix";

export function getStoredTemporaryPolicy(): Record<string, Record<string, string>> | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(TEMPORARY_POLICY_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

export function setStoredTemporaryPolicy(matrix: Record<string, Record<string, string>>): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(TEMPORARY_POLICY_KEY, JSON.stringify(matrix));
  } catch {
    // 무시
  }
}

export function clearStoredTemporaryPolicy(): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.removeItem(TEMPORARY_POLICY_KEY);
  } catch {
    // 무시
  }
}

export function useRiskPolicy(token: string) {
  const [data, setData] = useState<PolicyResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchPolicy = useCallback(async () => {
    if (!token) return;
    setLoading(true);
    setError(null);
    try {
      const response = await fetch("/internal/v1/policy", {
        headers: { "X-Alert-Admin-Token": token },
        credentials: "same-origin",
      });
      if (!response.ok) {
        throw new Error(`위험도 정책을 불러오지 못했습니다 (${response.status})`);
      }
      const json = await response.json() as PolicyResponse;
      setData(json);
    } catch (err) {
      setError(err instanceof Error ? err.message : "정책 통신 실패");
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => {
    void fetchPolicy();

  }, [fetchPolicy]);

  return { data, loading, error, refresh: fetchPolicy };
}


