import { useCallback, useEffect, useRef, useState } from "react";
import type { MonitoringMode, MonitoringResponse } from "./types";

const REFRESH_INTERVAL_MS = 5 * 60 * 1000;

export interface MonitoringState {
  data: MonitoringResponse | null;
  loading: boolean;
  refreshing: boolean;
  error: string;
  refresh: () => Promise<void>;
}

export function useMonitoringData(mode: MonitoringMode): MonitoringState {
  const [data, setData] = useState<MonitoringResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState("");
  const running = useRef<AbortController | null>(null);

  const load = useCallback(async (force = false) => {
    running.current?.abort();
    const controller = new AbortController();
    running.current = controller;
    setRefreshing(true);
    try {
      const query = new URLSearchParams();
      if (mode === "simulation") query.set("mode", "simulation");
      if (force) query.set("refresh", "true");
      const suffix = query.size ? `?${query.toString()}` : "";
      const response = await fetch(`/api/v1/monitoring${suffix}`, {
        cache: "no-store",
        signal: controller.signal,
        headers: { Accept: "application/json" },
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const next = (await response.json()) as MonitoringResponse;
      if (next.api_version !== "v1" || !Array.isArray(next.facilities)) {
        throw new Error("잘못된 API 응답");
      }
      setData(next);
      setError("");
    } catch (reason) {
      if ((reason as Error).name !== "AbortError") {
        setError("새 자료를 불러오지 못했습니다. 마지막 정상 자료를 표시합니다.");
      }
    } finally {
      if (running.current === controller) {
        setLoading(false);
        setRefreshing(false);
      }
    }
  }, [mode]);

  useEffect(() => {
    // 모드 전환 중에도 마지막 화면을 유지해 KakaoMap과 사용자가 잡은 뷰포트를
    // 언마운트하지 않습니다. 최초 진입만 data가 null인 로딩 화면을 사용합니다.
    setLoading(true);
    setError("");
    void load();
    const timer = window.setInterval(() => {
      if (document.visibilityState === "visible") void load();
    }, REFRESH_INTERVAL_MS);
    const onVisibility = () => {
      if (document.visibilityState === "visible") void load();
    };
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisibility);
      running.current?.abort();
    };
  }, [load]);

  return {
    data,
    loading,
    refreshing,
    error,
    refresh: () => load(true),
  };
}
