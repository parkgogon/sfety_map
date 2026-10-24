import { mapEvents } from "./events";
import type { KakaoOverlay, KakaoMouseEvent } from "../kakaoTypes";
import { useEffect, useRef } from "react";

import {
  buildWarningCardContent,
  groupWarningsByRegion,
} from "../mapWarningInspection";
import type { KakaoMapProps } from "../KakaoMap";
import type { KakaoMapRuntime } from "./useKakaoMapRuntime";
import type { MapInteractions } from "./types";

import { polygonPaths } from "./warningPaths";

export function useWarningZones(
  runtime: KakaoMapRuntime,
  options: Required<
    Pick<KakaoMapProps, "warningZones" | "warnings" | "isSimulation">
  >,
  interactions: Pick<
    MapInteractions,
    "pickReferenceAt" | "setMapInformation" | "suppressMapInspectionUntilRef"
  >,
) {
  const { elementRef, mapRef, kakaoRef, subscribeReady } = runtime;
  const { warningZones, warnings, isSimulation } = options;
  const { pickReferenceAt, setMapInformation, suppressMapInspectionUntilRef } =
    interactions;
  const polygonRef = useRef<KakaoOverlay[]>([]);
  useEffect(() => {
    let eventScope: ReturnType<typeof mapEvents> | undefined;
    const clear = () => {
      eventScope?.dispose();
      polygonRef.current.forEach((polygon) => polygon.setMap(null));
      polygonRef.current = [];
    };
    const render = () => {
      const kakao = kakaoRef.current;
      const map = mapRef.current;
      if (!kakao || !map) return;
      clear();
      const subscriptions = mapEvents(kakao);
      eventScope = subscriptions;
      const warningMap = groupWarningsByRegion(warnings);
      warningZones.forEach((feature) => {
        if (feature.properties?.level === "UNKNOWN") return;
        polygonPaths(kakao, feature).forEach((path) => {
          const polygon = new kakao.maps.Polygon({
            map,
            path,
            strokeWeight: 2,
            strokeColor: feature.properties.color,
            strokeOpacity: 0.7,
            fillColor: feature.properties.color,
            fillOpacity: 0.13,
          });
          subscriptions.add(polygon, "click", (mouseEvent: KakaoMouseEvent) => {
            if (pickReferenceAt(mouseEvent?.latLng)) return;
            suppressMapInspectionUntilRef.current = Date.now() + 350;
            const element = elementRef.current;
            const projection = map.getProjection();
            if (!element || !projection || !mouseEvent?.latLng) return;
            const viewportPoint = projection.containerPointFromCoords(
              mouseEvent.latLng,
            );
            const regionWarnings =
              warningMap.get(feature.properties.region_code) ?? [];
            const content = buildWarningCardContent(
              feature,
              regionWarnings,
              isSimulation,
            );
            setMapInformation({
              anchor: { x: viewportPoint.x, y: viewportPoint.y },
              viewport: {
                width: element.clientWidth,
                height: element.clientHeight,
              },
              content,
            });
          });
          polygonRef.current.push(polygon);
        });
      });
    };
    render();
    const unsubscribeReady = subscribeReady(render);
    return () => {
      unsubscribeReady();
      clear();
    };
  }, [isSimulation, warningZones, warnings, pickReferenceAt, subscribeReady]);
}
