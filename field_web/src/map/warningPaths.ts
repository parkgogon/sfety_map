import type { KakaoSDK, KakaoLatLng } from "../kakaoTypes";

import type { WarningZoneFeature } from "../types";

export function polygonPaths(
  kakao: KakaoSDK,
  feature: WarningZoneFeature,
): KakaoLatLng[][][] {
  const polygons =
    feature.geometry.type === "Polygon"
      ? [feature.geometry.coordinates]
      : feature.geometry.coordinates;
  return (polygons as number[][][][]).map((polygon) =>
    polygon.map((ring) =>
      ring.map(
        ([longitude, latitude]) => new kakao.maps.LatLng(latitude, longitude),
      ),
    ),
  );
}
