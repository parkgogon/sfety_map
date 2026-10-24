import type { KakaoSDK, KakaoMapInstance } from "../kakaoTypes";
import { useCallback, useEffect, useRef, useState } from "react";
import { loadKakaoMaps } from "../kakao";

import { shouldShowMapZoomControl } from "../utils";

import type { KakaoMapProps } from "../KakaoMap";

export function useKakaoMapRuntime(
  showZoomControl: KakaoMapProps["showZoomControl"],
) {
  const elementRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<KakaoMapInstance | null>(null);
  const kakaoRef = useRef<KakaoSDK | null>(null);
  const zoomControlRef = useRef<object | null>(null);
  const zoomControlVisibleRef = useRef(false);
  const showZoomControlRef = useRef(showZoomControl);
  const [error, setError] = useState("");
  const readyListeners = useRef(new Set<() => void>());
  const subscribeReady = useCallback((listener: () => void) => {
    readyListeners.current.add(listener);
    return () => {
      readyListeners.current.delete(listener);
    };
  }, []);
  const appKey = import.meta.env.VITE_KAKAO_MAP_APP_KEY?.trim() ?? "";
  const syncZoomControl = useCallback(() => {
    const kakao = kakaoRef.current;
    const map = mapRef.current;
    if (!kakao || !map) return;
    if (!zoomControlRef.current)
      zoomControlRef.current = new kakao.maps.ZoomControl();
    const visible =
      showZoomControlRef.current ?? shouldShowMapZoomControl(window.innerWidth);
    if (visible === zoomControlVisibleRef.current) return;
    if (visible)
      map.addControl(zoomControlRef.current, kakao.maps.ControlPosition.RIGHT);
    else map.removeControl?.(zoomControlRef.current);
    zoomControlVisibleRef.current = visible;
  }, []);
  showZoomControlRef.current = showZoomControl;
  useEffect(() => {
    let cancelled = false;
    loadKakaoMaps(appKey)
      .then((kakao) => {
        if (cancelled || !elementRef.current) return;
        kakaoRef.current = kakao;
        const map = new kakao.maps.Map(elementRef.current, {
          center: new kakao.maps.LatLng(36.0, 128.55),
          level: 10,
        });
        mapRef.current = map;
        syncZoomControl();
        setError("");
        readyListeners.current.forEach((listener) => listener());
      })
      .catch((reason: Error) => setError(reason.message));
    return () => {
      cancelled = true;
    };
  }, [appKey, syncZoomControl]);
  useEffect(() => {
    const onResize = () => {
      if (mapRef.current && kakaoRef.current) {
        kakaoRef.current.maps.event.trigger(mapRef.current, "resize");
        syncZoomControl();
      }
    };
    syncZoomControl();
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, [syncZoomControl]);
  useEffect(() => {
    syncZoomControl();
  }, [showZoomControl, syncZoomControl]);
  return { elementRef, mapRef, kakaoRef, error, subscribeReady };
}

export type KakaoMapRuntime = ReturnType<typeof useKakaoMapRuntime>;
