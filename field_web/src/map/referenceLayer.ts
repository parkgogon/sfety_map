import { useEffect } from "react";

import { referenceMapOverlays } from "../referenceMapOverlays";

import type { KakaoMapProps } from "../KakaoMap";
import type { KakaoMapRuntime } from "./useKakaoMapRuntime";

export function useReferenceOverlays(
  runtime: KakaoMapRuntime,
  options: Required<
    Pick<
      KakaoMapProps,
      | "referencePoint"
      | "referenceCandidate"
      | "referenceTarget"
      | "referenceRings"
      | "pickingReference"
    >
  >,
) {
  const { mapRef, kakaoRef, subscribeReady } = runtime;
  const {
    referencePoint,
    referenceCandidate,
    referenceTarget,
    referenceRings,
    pickingReference,
  } = options;

  useEffect(() => {
    let dispose = () => {};
    const draw = () => {
      dispose();
      if (!kakaoRef.current || !mapRef.current) return;
      dispose = referenceMapOverlays(
        kakaoRef.current,
        mapRef.current,
        referencePoint,
        referenceCandidate,
        pickingReference ? null : referenceTarget,
        referenceRings && !pickingReference,
      );
    };
    draw();
    const unsubscribeReady = subscribeReady(draw);
    return () => {
      dispose();
      unsubscribeReady();
    };
  }, [
    referencePoint,
    referenceCandidate,
    referenceTarget,
    referenceRings,
    pickingReference,
    subscribeReady,
  ]);
}
