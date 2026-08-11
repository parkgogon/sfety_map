import { useCallback, useEffect, useRef, useState } from "react";
import type { CctvResponse, WeatherResponse } from "./types";

const WEATHER_DELAY_MS = 250;
const CCTV_SUCCESS_COOLDOWN_MS = 60_000;
const CCTV_RETRY_COOLDOWN_MS = 30_000;

interface FacilityWeatherState {
  data: WeatherResponse | null;
  loading: boolean;
  error: string;
  retry: () => void;
}

interface FacilityCctvState {
  data: CctvResponse | null;
  loading: boolean;
  error: string;
  load: () => void;
  cooldownUntil: number;
}

async function responseJson<T>(response: Response): Promise<T> {
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return (await response.json()) as T;
}

export function useFacilityWeather(facilityId: string): FacilityWeatherState {
  const [data, setData] = useState<WeatherResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    setData(null);
    setError("");
    if (!facilityId) {
      setLoading(false);
      return;
    }

    const controller = new AbortController();
    setLoading(true);
    const timer = window.setTimeout(async () => {
      try {
        const encodedId = encodeURIComponent(facilityId);
        const next = await responseJson<WeatherResponse>(await fetch(
          `/api/v1/facilities/${encodedId}/weather`,
          { cache: "no-store", signal: controller.signal, headers: { Accept: "application/json" } },
        ));
        if (next.api_version !== "v1" || next.facility_id !== facilityId) {
          throw new Error("잘못된 기상 API 응답");
        }
        setData(next);
        setError("");
      } catch (reason) {
        if ((reason as Error).name !== "AbortError") {
          setError("현재 기상을 불러오지 못했습니다.");
        }
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    }, WEATHER_DELAY_MS);

    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [facilityId, attempt]);

  return {
    data,
    loading,
    error,
    retry: () => setAttempt((value) => value + 1),
  };
}

export function useFacilityCctv(facilityId: string): FacilityCctvState {
  const [data, setData] = useState<CctvResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [cooldownUntil, setCooldownUntil] = useState(0);
  const running = useRef<AbortController | null>(null);
  const facilityIdRef = useRef(facilityId);

  useEffect(() => {
    facilityIdRef.current = facilityId;
    running.current?.abort();
    setData(null);
    setError("");
    setLoading(false);
    setCooldownUntil(0);
    return () => running.current?.abort();
  }, [facilityId]);

  const load = useCallback(() => {
    if (!facilityId || loading || Date.now() < cooldownUntil) return;
    running.current?.abort();
    const requestedId = facilityId;
    const controller = new AbortController();
    running.current = controller;
    setLoading(true);
    setError("");
    void (async () => {
      try {
        const encodedId = encodeURIComponent(requestedId);
        const next = await responseJson<CctvResponse>(await fetch(
          `/api/v1/facilities/${encodedId}/cctv`,
          { cache: "no-store", signal: controller.signal, headers: { Accept: "application/json" } },
        ));
        if (next.api_version !== "v1" || next.facility_id !== requestedId) {
          throw new Error("잘못된 CCTV API 응답");
        }
        if (facilityIdRef.current !== requestedId) return;
        setData(next);
        setError("");
        const retryAfter = next.status === "LIVE"
          ? CCTV_SUCCESS_COOLDOWN_MS
          : CCTV_RETRY_COOLDOWN_MS;
        setCooldownUntil(Date.now() + retryAfter);
      } catch (reason) {
        if ((reason as Error).name !== "AbortError" && facilityIdRef.current === requestedId) {
          setError("인근 도로 CCTV를 불러오지 못했습니다.");
          setCooldownUntil(Date.now() + CCTV_RETRY_COOLDOWN_MS);
        }
      } finally {
        if (running.current === controller) {
          running.current = null;
          setLoading(false);
        }
      }
    })();
  }, [cooldownUntil, facilityId, loading]);

  return { data, loading, error, load, cooldownUntil };
}
