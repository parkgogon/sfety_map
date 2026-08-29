import { useCallback, useEffect, useRef, useState } from "react";
import type { MonitoringMode, WeatherLayerKind, WeatherLayerResponse } from "./types";

const REFRESH_INTERVAL_MS = 10 * 60 * 1000;

interface CachedLayer {
  data: WeatherLayerResponse;
  expiresAt: number;
}

export interface WeatherLayerState {
  data: WeatherLayerResponse | null;
  loading: boolean;
  error: string;
  retry: () => void;
}

export async function fetchWeatherLayer(
  kind: WeatherLayerKind,
  mode: MonitoringMode = "live",
  signal?: AbortSignal,
): Promise<WeatherLayerResponse> {
  const query = mode === "simulation" ? "?mode=simulation" : "";
  const response = await fetch(`/api/v1/weather/layers/${kind}${query}`, {
    cache: "no-store",
    signal,
    headers: { Accept: "application/json" },
  });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  const payload = (await response.json()) as WeatherLayerResponse;
  if (
    payload.api_version !== "v1"
    || payload.layer !== kind
    || !Array.isArray(payload.points)
  ) {
    throw new Error("잘못된 기상 레이어 API 응답");
  }
  return payload;
}

export function useWeatherLayer(
  kind: WeatherLayerKind | null,
  mode: MonitoringMode = "live",
): WeatherLayerState {
  const [data, setData] = useState<WeatherLayerResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const cache = useRef(new Map<string, CachedLayer>());
  const running = useRef<AbortController | null>(null);

  const retry = useCallback(() => setAttempt((value) => value + 1), []);

  useEffect(() => {
    running.current?.abort();
    if (!kind) {
      setData(null);
      setLoading(false);
      setError("");
      return;
    }

    const cacheKey = `${mode}:${kind}`;
    const cached = cache.current.get(cacheKey);
    if (cached) setData(cached.data);
    else setData(null);
    setError("");

    let timer = 0;
    const load = async (force = false) => {
      const current = cache.current.get(cacheKey);
      if (!force && current && Date.now() < current.expiresAt) {
        setData(current.data);
        return;
      }
      running.current?.abort();
      const controller = new AbortController();
      running.current = controller;
      setLoading(true);
      try {
        const next = await fetchWeatherLayer(kind, mode, controller.signal);
        if (controller.signal.aborted) return;
        cache.current.set(cacheKey, {
          data: next,
          expiresAt: Date.now() + REFRESH_INTERVAL_MS,
        });
        setData(next);
        setError("");
      } catch (reason) {
        if ((reason as Error).name !== "AbortError") {
          setError("기상 레이어를 불러오지 못했습니다.");
        }
      } finally {
        if (running.current === controller) {
          running.current = null;
          setLoading(false);
        }
      }
    };

    void load(attempt > 0);
    timer = window.setInterval(() => {
      if (document.visibilityState === "visible") void load(true);
    }, REFRESH_INTERVAL_MS);
    const onVisibility = () => {
      const current = cache.current.get(cacheKey);
      if (
        document.visibilityState === "visible"
        && (!current || Date.now() >= current.expiresAt)
      ) void load(true);
    };
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisibility);
      running.current?.abort();
    };
  }, [attempt, kind, mode]);

  return { data, loading, error, retry };
}

