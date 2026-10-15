import type { Facility } from "./types";

export interface MapCoordinate {
  latitude: number;
  longitude: number;
}

export interface ReferencePoint extends MapCoordinate {
  label: string;
  address: string;
  source: "place" | "address" | "map";
}

export interface ReferenceView {
  points: MapCoordinate[];
  revision: number;
}

export const REFERENCE_RADII_METERS = [1000, 3000, 5000] as const;
const EARTH_RADIUS_METERS = 6371008.8;

export function validCoordinate(point: MapCoordinate): boolean {
  return Number.isFinite(point.latitude) && Number.isFinite(point.longitude)
    && Math.abs(point.latitude) <= 90 && Math.abs(point.longitude) <= 180;
}

// Great-circle distance, not driving distance or an estimate of disaster impact.
export function distanceMeters(a: MapCoordinate, b: MapCoordinate): number {
  const radians = Math.PI / 180;
  const lat = (b.latitude - a.latitude) * radians;
  const lng = (b.longitude - a.longitude) * radians;
  const h = Math.sin(lat / 2) ** 2
    + Math.cos(a.latitude * radians) * Math.cos(b.latitude * radians) * Math.sin(lng / 2) ** 2;
  return EARTH_RADIUS_METERS * 2 * Math.asin(Math.sqrt(Math.min(1, Math.max(0, h))));
}

export function formatDistance(meters: number): string {
  return meters < 1000 ? `${Math.round(meters)}m` : `${(meters / 1000).toFixed(1)}km`;
}

export function nearbyFacilities(facilities: Facility[], point: MapCoordinate) {
  return facilities.filter(validCoordinate)
    .map((facility) => ({ facility, meters: distanceMeters(point, facility) }))
    .sort((a, b) => a.meters - b.meters || a.facility.id.localeCompare(b.facility.id));
}

export function referenceBounds(point: MapCoordinate): MapCoordinate[] {
  const latitudeDelta = 5000 / EARTH_RADIUS_METERS * 180 / Math.PI;
  const longitudeDelta = latitudeDelta / Math.max(0.01, Math.cos(point.latitude * Math.PI / 180));
  return [
    { latitude: Math.max(-90, point.latitude - latitudeDelta), longitude: Math.max(-180, point.longitude - longitudeDelta) },
    { latitude: Math.min(90, point.latitude + latitudeDelta), longitude: Math.min(180, point.longitude + longitudeDelta) },
  ];
}
