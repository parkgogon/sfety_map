import type { Facility } from "./types";
import { distanceMeters, formatDistance, REFERENCE_RADII_METERS, type ReferencePoint } from "./locationReference";

export function referenceMapOverlays(
  kakao: any, map: any, point: ReferencePoint | null, candidate: ReferencePoint | null,
  target: Facility | null, showRings: boolean,
): () => void {
  const overlays: any[] = [];
  const visiblePoint = candidate ?? point;
  if (!visiblePoint) return () => undefined;
  const position = (p: { latitude: number; longitude: number }) => new kakao.maps.LatLng(p.latitude, p.longitude);
  const label = (text: string, className: string, at: any, yAnchor = 1.2) => {
    const content = document.createElement("div");
    content.className = className;
    content.textContent = text;
    overlays.push(new kakao.maps.CustomOverlay({ map, position: at, content, yAnchor, zIndex: 8 }));
  };
  if (point && !candidate && showRings) {
    REFERENCE_RADII_METERS.forEach((radius) => {
      overlays.push(new kakao.maps.Circle({
        map, center: position(point), radius, strokeWeight: 1.5, strokeColor: "#475569",
        strokeOpacity: 0.75, strokeStyle: "dash", fillOpacity: 0, zIndex: 1,
      }));
      label(`${radius / 1000}km`, "location-radius-label",
        position({ latitude: Math.min(90, point.latitude + radius / 111195.08), longitude: point.longitude }), 0.5);
    });
  }
  const pin = document.createElement("div");
  pin.className = "location-reference-pin";
  const caption = document.createElement("span");
  caption.textContent = candidate ? "선택한 위치 · 확인 전" : `${visiblePoint.label} · 기준점`;
  const diamond = document.createElement("span");
  diamond.className = "location-reference-diamond";
  diamond.textContent = "＋";
  pin.append(caption, diamond);
  overlays.push(new kakao.maps.CustomOverlay({
    map, position: position(visiblePoint), content: pin, xAnchor: 0.5, yAnchor: 1, zIndex: 9,
  }));
  if (point && !candidate && target) {
    overlays.push(new kakao.maps.Polyline({
      map, path: [position(point), position(target)], strokeWeight: 2, strokeColor: "#334155",
      strokeOpacity: 0.9, strokeStyle: "shortdash", zIndex: 3,
    }));
    label(`직선거리 ${formatDistance(distanceMeters(point, target))}`, "location-distance-label",
      position({ latitude: (point.latitude + target.latitude) / 2, longitude: (point.longitude + target.longitude) / 2 }));
  }
  return () => overlays.forEach((overlay) => overlay.setMap(null));
}
