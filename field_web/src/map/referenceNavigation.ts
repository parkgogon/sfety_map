import { useEffect } from "react";

import type { KakaoMapProps } from "../KakaoMap";
import type { KakaoMapRuntime } from "./useKakaoMapRuntime";
import type { MapInteractions } from "./types";
import { mapViewportPadding, overlayElements } from "./viewport";

export function useReferenceNavigation(
  runtime: KakaoMapRuntime,
  options: Required<
    Pick<KakaoMapProps, "referenceView" | "referenceCandidate">
  >,
  interactions: Pick<MapInteractions, "dismissMapInformation">,
) {
  const { elementRef, mapRef, kakaoRef, subscribeReady } = runtime;
  const { referenceView, referenceCandidate } = options;
  const { dismissMapInformation } = interactions;

  useEffect(() => {
    let lastLayout = "";
    const focus = () => {
      const kakao = kakaoRef.current;
      const map = mapRef.current;
      if (!kakao || !map || !referenceView?.points.length) return;
      const points = referenceView.points;
      const element = elementRef.current;
      const padding = element
        ? mapViewportPadding(element)
        : { top: 48, right: 48, bottom: 48, left: 48 };
      const layout = [
        element?.clientWidth,
        element?.clientHeight,
        padding.top,
        padding.right,
        padding.bottom,
        padding.left,
      ].join(":");
      if (layout === lastLayout) return;
      lastLayout = layout;
      if (points.length === 1) {
        map.setLevel(5);
        map.setCenter(
          new kakao.maps.LatLng(points[0].latitude, points[0].longitude),
        );
        map.panBy(
          (padding.right - padding.left) / 2,
          (padding.bottom - padding.top) / 2,
        );
      } else {
        const bounds = new kakao.maps.LatLngBounds();
        points.forEach((point) =>
          bounds.extend(new kakao.maps.LatLng(point.latitude, point.longitude)),
        );
        map.setBounds(
          bounds,
          padding.top,
          padding.right,
          padding.bottom,
          padding.left,
        );
      }
      dismissMapInformation();
    };
    focus();
    // Weather content, panel expansion and viewport changes can cover a previously
    // visible endpoint. Refit only when overlay geometry changes, never on map drag.
    const observer =
      referenceView && typeof ResizeObserver !== "undefined"
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
  }, [referenceView, dismissMapInformation, subscribeReady]);
  useEffect(() => {
    if (!referenceCandidate || referenceCandidate.source !== "map") return;
    let lastLayout = "";
    const keepVisible = () => {
      const kakao = kakaoRef.current;
      const map = mapRef.current;
      const element = elementRef.current;
      const projection = map?.getProjection?.();
      if (!kakao || !map || !element || !projection) return;
      const padding = mapViewportPadding(element);
      const layout = [
        element.clientWidth,
        element.clientHeight,
        padding.top,
        padding.right,
        padding.bottom,
        padding.left,
      ].join(":");
      if (layout === lastLayout) return;
      lastLayout = layout;
      const point = projection.containerPointFromCoords(
        new kakao.maps.LatLng(
          referenceCandidate.latitude,
          referenceCandidate.longitude,
        ),
      );
      const minX = padding.left;
      const maxX = element.clientWidth - padding.right;
      const minY = padding.top;
      const maxY = element.clientHeight - padding.bottom;
      const dx =
        point.x < minX ? point.x - minX : point.x > maxX ? point.x - maxX : 0;
      const dy =
        point.y < minY ? point.y - minY : point.y > maxY ? point.y - maxY : 0;
      if (dx || dy) map.panBy(dx, dy);
    };
    keepVisible();
    const observer =
      typeof ResizeObserver !== "undefined"
        ? new ResizeObserver(keepVisible)
        : null;
    const element = elementRef.current;
    if (element) observer?.observe(element);
    if (element)
      overlayElements(element).forEach((overlay) => observer?.observe(overlay));
    const unsubscribeReady = subscribeReady(keepVisible);
    return () => {
      observer?.disconnect();
      unsubscribeReady();
    };
  }, [referenceCandidate, subscribeReady]);
}
