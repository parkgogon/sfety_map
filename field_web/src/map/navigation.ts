import { useEffect, useRef } from "react";

import type { KakaoMapProps } from "../KakaoMap";
import type { KakaoMapRuntime } from "./useKakaoMapRuntime";
import type { MapInteractions } from "./types";
import { mapViewportPadding, overlayElements } from "./viewport";

export function useMapNavigation(
  runtime: KakaoMapRuntime,
  options: Required<
    Pick<
      KakaoMapProps,
      "focusRequest" | "viewportRequest" | "referenceView" | "facilities"
    >
  >,
  interactions: Pick<MapInteractions, "dismissMapInformation">,
) {
  const { elementRef, mapRef, kakaoRef, subscribeReady } = runtime;
  const { focusRequest, viewportRequest, referenceView, facilities } = options;
  const { dismissMapInformation } = interactions;
  const handledViewportRevisionRef = useRef(0);
  const referenceViewRef = useRef(referenceView);
  referenceViewRef.current = referenceView;
  useEffect(() => {
    let lastLayout = "";
    const focus = () => {
      const kakao = kakaoRef.current;
      const map = mapRef.current;
      if (
        !kakao ||
        !map ||
        !focusRequest ||
        referenceViewRef.current?.points.length
      )
        return;
      const padding = elementRef.current
        ? mapViewportPadding(elementRef.current)
        : { top: 48, right: 48, bottom: 48, left: 48 };
      const layout = [
        elementRef.current?.clientWidth,
        elementRef.current?.clientHeight,
        padding.top,
        padding.right,
        padding.bottom,
        padding.left,
      ].join(":");
      if (layout === lastLayout) return;
      lastLayout = layout;
      map.panTo(
        new kakao.maps.LatLng(focusRequest.latitude, focusRequest.longitude),
      );
      if (focusRequest.zoom && map.getLevel() > 5) map.setLevel(5);
      map.panBy?.(
        (padding.right - padding.left) / 2,
        (padding.bottom - padding.top) / 2,
      );
    };
    focus();
    const observer =
      focusRequest && typeof ResizeObserver !== "undefined"
        ? new ResizeObserver(focus)
        : null;
    const element = elementRef.current;
    if (element) observer?.observe(element);
    if (element)
      overlayElements(element).forEach((overlay) => observer?.observe(overlay));
    const unsubscribeReady = subscribeReady(focus);
    return () => {
      observer?.disconnect();
      unsubscribeReady();
    };
  }, [focusRequest, subscribeReady]);
  useEffect(() => {
    const apply = () => {
      const kakao = kakaoRef.current;
      const map = mapRef.current;
      if (!kakao || !map || !viewportRequest) return;
      if (handledViewportRevisionRef.current === viewportRequest.revision)
        return;
      handledViewportRevisionRef.current = viewportRequest.revision;
      if (
        viewportRequest.kind === "zoom-in" ||
        viewportRequest.kind === "zoom-out"
      ) {
        const current = map.getLevel();
        const delta = viewportRequest.kind === "zoom-in" ? -1 : 1;
        map.setLevel(Math.max(1, Math.min(14, current + delta)));
        return;
      }
      if (!facilities.length) return;
      const bounds = new kakao.maps.LatLngBounds();
      facilities.forEach((facility) =>
        bounds.extend(
          new kakao.maps.LatLng(facility.latitude, facility.longitude),
        ),
      );
      const padding = elementRef.current
        ? mapViewportPadding(elementRef.current)
        : { top: 48, right: 48, bottom: 48, left: 48 };
      map.setBounds(
        bounds,
        padding.top,
        padding.right,
        padding.bottom,
        padding.left,
      );
      dismissMapInformation();
    };
    apply();
    const unsubscribeReady = subscribeReady(apply);
    return () => unsubscribeReady();
    // A data refresh must not refit a map the user has already moved.
    // The current facilities are read only when an explicit viewport request changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [viewportRequest, dismissMapInformation, subscribeReady]);
}
