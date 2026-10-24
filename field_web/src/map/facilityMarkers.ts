import { mapEvents } from "./events";
import type { KakaoClusterer, KakaoCluster } from "../kakaoTypes";
import { useEffect, useRef } from "react";

import {
  CLUSTER_GRID_SIZE,
  CLUSTER_MARKER_SIZE,
  CLUSTER_MIN_LEVEL,
  CLUSTER_MIN_SIZE,
  MAP_MARKER_Z_INDEX,
} from "../mapVisuals";

import { shouldFitInitialFacilities } from "../utils";

import type { KakaoMapProps } from "../KakaoMap";
import type { KakaoMapRuntime } from "./useKakaoMapRuntime";
import type { MapInteractions } from "./types";
import { mapViewportPadding } from "./viewport";
import { markerImage, coordinateGroups } from "./markerIcons";

export function useFacilityMarkers(
  runtime: KakaoMapRuntime,
  options: Required<
    Pick<
      KakaoMapProps,
      "facilities" | "selectedFacilityId" | "onSelect" | "onSelectGroup"
    >
  >,
  interactions: Pick<
    MapInteractions,
    "pickReferenceAt" | "dismissMapInformation"
  >,
) {
  const { elementRef, mapRef, kakaoRef, subscribeReady } = runtime;
  const { facilities, selectedFacilityId, onSelect, onSelectGroup } = options;
  const { pickReferenceAt, dismissMapInformation } = interactions;
  const clustererRef = useRef<KakaoClusterer | null>(null);
  const initialBoundsFittedRef = useRef(false);
  useEffect(() => {
    let eventScope: ReturnType<typeof mapEvents> | undefined;
    const clear = () => {
      eventScope?.dispose();
      clustererRef.current?.clear();
      clustererRef.current = null;
    };
    const render = () => {
      const kakao = kakaoRef.current;
      const map = mapRef.current;
      if (!kakao || !map) return;
      clear();
      const subscriptions = mapEvents(kakao);
      eventScope = subscriptions;
      const clusterer = new kakao.maps.MarkerClusterer({
        map,
        averageCenter: true,
        gridSize: CLUSTER_GRID_SIZE,
        minLevel: CLUSTER_MIN_LEVEL,
        minClusterSize: CLUSTER_MIN_SIZE,
        disableClickZoom: false,
        styles: [
          {
            width: `${CLUSTER_MARKER_SIZE}px`,
            height: `${CLUSTER_MARKER_SIZE}px`,
            background: "rgba(20,39,70,.9)",
            border: "3px solid white",
            borderRadius: "50%",
            boxSizing: "border-box",
            color: "white",
            textAlign: "center",
            fontWeight: "700",
            lineHeight: `${CLUSTER_MARKER_SIZE - 6}px`,
            boxShadow: "0 2px 8px rgba(20,39,70,.22)",
          },
        ],
      });
      subscriptions.add(clusterer, "clustered", (clusters: KakaoCluster[]) => {
        clusters.forEach((cluster) => {
          cluster.getClusterMarker()?.setZIndex(MAP_MARKER_Z_INDEX);
        });
      });
      subscriptions.add(clusterer, "clusterclick", () => {
        dismissMapInformation(true);
      });
      clustererRef.current = clusterer;
      const bounds = new kakao.maps.LatLngBounds();
      const markers = coordinateGroups(facilities).map((group) => {
        const first = group[0];
        const position = new kakao.maps.LatLng(first.latitude, first.longitude);
        const marker = new kakao.maps.Marker({
          position,
          title:
            group.length === 1
              ? first.name
              : `같은 위치의 시설 ${group.length}개`,
          zIndex: MAP_MARKER_Z_INDEX,
          image: markerImage(
            kakao,
            group,
            group.some((facility) => facility.id === selectedFacilityId),
          ),
        });
        subscriptions.add(marker, "click", () => {
          if (pickReferenceAt(position)) return;
          dismissMapInformation(true);
          if (group.length === 1) onSelect(group[0]);
          else onSelectGroup(group);
        });
        bounds.extend(position);
        return marker;
      });
      clusterer.addMarkers(markers);

      if (
        shouldFitInitialFacilities(
          initialBoundsFittedRef.current,
          facilities.length,
        )
      ) {
        const padding = elementRef.current
          ? mapViewportPadding(elementRef.current)
          : { top: 48, right: 48, bottom: 120, left: 48 };
        map.setBounds(
          bounds,
          padding.top,
          padding.right,
          padding.bottom,
          padding.left,
        );
        initialBoundsFittedRef.current = true;
      }
    };
    render();
    const unsubscribeReady = subscribeReady(render);
    return () => {
      unsubscribeReady();
      clear();
    };
  }, [
    dismissMapInformation,
    facilities,
    onSelect,
    onSelectGroup,
    selectedFacilityId,
    pickReferenceAt,
    subscribeReady,
  ]);
}
