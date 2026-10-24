import { mapEvents } from "./events";
import type { KakaoOverlay } from "../kakaoTypes";
import { useEffect, useRef } from "react";

import { cctvDirectionText } from "../utils";

import type { KakaoMapProps } from "../KakaoMap";
import type { KakaoMapRuntime } from "./useKakaoMapRuntime";
import type { MapInteractions } from "./types";

import { cctvMarkerImage } from "./markerIcons";

export function useCctvMarkers(
  runtime: KakaoMapRuntime,
  options: Required<
    Pick<KakaoMapProps, "cctvs" | "selectedCctvId" | "onSelectCctv">
  >,
  interactions: Pick<
    MapInteractions,
    "pickReferenceAt" | "dismissMapInformation"
  >,
) {
  const { mapRef, kakaoRef, subscribeReady } = runtime;
  const { cctvs, selectedCctvId, onSelectCctv } = options;
  const { pickReferenceAt, dismissMapInformation } = interactions;
  const cctvMarkerRef = useRef<KakaoOverlay[]>([]);
  useEffect(() => {
    let eventScope: ReturnType<typeof mapEvents> | undefined;
    const clear = () => {
      eventScope?.dispose();
      cctvMarkerRef.current.forEach((marker) => marker.setMap(null));
      cctvMarkerRef.current = [];
    };
    const render = () => {
      const kakao = kakaoRef.current;
      const map = mapRef.current;
      if (!kakao || !map) return;
      clear();
      const subscriptions = mapEvents(kakao);
      eventScope = subscriptions;
      cctvMarkerRef.current = cctvs.map((cctv) => {
        const marker = new kakao.maps.Marker({
          map,
          position: new kakao.maps.LatLng(cctv.latitude, cctv.longitude),
          title: `${cctv.name} · ${cctv.distance_km.toFixed(1)}km · ${cctvDirectionText(cctv)}`,
          image: cctvMarkerImage(kakao, cctv, cctv.id === selectedCctvId),
          zIndex: 20,
        });
        subscriptions.add(marker, "click", () => {
          if (
            pickReferenceAt(
              new kakao.maps.LatLng(cctv.latitude, cctv.longitude),
            )
          )
            return;
          dismissMapInformation(true);
          onSelectCctv(cctv);
        });
        return marker;
      });
    };
    render();
    const unsubscribeReady = subscribeReady(render);
    return () => {
      unsubscribeReady();
      clear();
    };
  }, [
    cctvs,
    dismissMapInformation,
    onSelectCctv,
    selectedCctvId,
    pickReferenceAt,
    subscribeReady,
  ]);
}
