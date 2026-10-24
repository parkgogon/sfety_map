import { useKakaoMapRuntime } from "./map/useKakaoMapRuntime";
import type { PositionedMapInformation } from "./map/types";
export { mapViewportPadding } from "./map/viewport";
import { useFacilityMarkers } from "./map/facilityMarkers";
import { useMapNavigation } from "./map/navigation";
import { useCctvMarkers } from "./map/cctvLayer";
import { useWarningZones } from "./map/warningZones";
import { useWeatherMapLayer } from "./map/weatherLayer";
import { useReferenceOverlays } from "./map/referenceLayer";
import { useReferenceNavigation } from "./map/referenceNavigation";
import type { KakaoLatLng } from "./kakaoTypes";
import { useCallback, useEffect, useRef, useState } from "react";

import type {
  MapCoordinate,
  ReferencePoint,
  ReferenceView,
} from "./locationReference";
import { MapInformationCard } from "./MapInformationCard";

import type {
  Facility,
  MapFocusRequest,
  MapViewportRequest,
  MonitoringWarningItem,
  NearbyCctv,
  WeatherLayerResponse,
  WarningZoneFeature,
} from "./types";

export interface KakaoMapProps {
  facilities: Facility[];
  referencePoint?: ReferencePoint | null;
  referenceCandidate?: ReferencePoint | null;
  referenceTarget?: Facility | null;
  referenceView?: ReferenceView | null;
  referenceRings?: boolean;
  pickingReference?: boolean;
  onPickReference?: (point: MapCoordinate) => void;
  warningZones: WarningZoneFeature[];
  warnings?: MonitoringWarningItem[];
  isSimulation?: boolean;
  selectedFacilityId: string;
  cctvs: NearbyCctv[];
  selectedCctvId: string;
  focusRequest: MapFocusRequest | null;
  viewportRequest?: MapViewportRequest | null;
  showZoomControl?: boolean;
  weatherLayer: WeatherLayerResponse | null;
  onSelect: (facility: Facility) => void;
  onSelectGroup: (facilities: Facility[]) => void;
  onSelectCctv: (cctv: NearbyCctv) => void;
}

export function KakaoMap({
  facilities,
  referencePoint = null,
  referenceCandidate = null,
  referenceTarget = null,
  referenceView = null,
  referenceRings = true,
  pickingReference = false,
  onPickReference,
  warningZones,
  warnings = [],
  isSimulation = false,
  selectedFacilityId,
  cctvs,
  selectedCctvId,
  focusRequest,
  viewportRequest = null,
  showZoomControl,
  weatherLayer,
  onSelect,
  onSelectGroup,
  onSelectCctv,
}: KakaoMapProps) {
  const runtime = useKakaoMapRuntime(showZoomControl);
  const { elementRef, error } = runtime;

  const weatherSurfaceCanvasRef = useRef<HTMLCanvasElement>(null);
  const windParticleCanvasRef = useRef<HTMLCanvasElement>(null);

  const suppressMapInspectionUntilRef = useRef(0);

  const [mapInformation, setMapInformation] =
    useState<PositionedMapInformation | null>(null);
  const referencePickingRef = useRef({
    active: pickingReference,
    onPick: onPickReference,
  });
  referencePickingRef.current = {
    active: pickingReference,
    onPick: onPickReference,
  };

  const pickReferenceAt = useCallback(
    (latLng: KakaoLatLng | undefined): boolean => {
      const state = referencePickingRef.current;
      if (!state.active || !latLng || !state.onPick) return false;
      state.onPick({ latitude: latLng.getLat(), longitude: latLng.getLng() });
      suppressMapInspectionUntilRef.current = Date.now() + 350;
      setMapInformation(null);
      return true;
    },
    [],
  );

  const dismissMapInformation = useCallback((suppressNextMapClick = false) => {
    if (suppressNextMapClick)
      suppressMapInspectionUntilRef.current = Date.now() + 250;
    setMapInformation(null);
  }, []);

  const interactions = {
    pickReferenceAt,
    dismissMapInformation,
    setMapInformation,
    suppressMapInspectionUntilRef,
    weatherSurfaceCanvasRef,
    windParticleCanvasRef,
  };

  useFacilityMarkers(
    runtime,
    { facilities, selectedFacilityId, onSelect, onSelectGroup },
    interactions,
  );

  useMapNavigation(
    runtime,
    { focusRequest, viewportRequest, referenceView, facilities },
    interactions,
  );

  useCctvMarkers(
    runtime,
    { cctvs, selectedCctvId, onSelectCctv },
    interactions,
  );

  useEffect(() => {
    dismissMapInformation();
  }, [
    dismissMapInformation,
    focusRequest?.revision,
    selectedCctvId,
    selectedFacilityId,
    weatherLayer?.layer,
    weatherLayer?.observed_at,
    weatherLayer?.status,
  ]);

  useEffect(() => {
    if (!mapInformation) return;
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      event.stopImmediatePropagation();
      dismissMapInformation();
    };
    window.addEventListener("keydown", handleKeyDown, true);
    return () => window.removeEventListener("keydown", handleKeyDown, true);
  }, [dismissMapInformation, mapInformation]);

  useWarningZones(
    runtime,
    { warningZones, warnings, isSimulation },
    interactions,
  );

  useWeatherMapLayer(runtime, { weatherLayer }, interactions);

  useEffect(() => {
    if (pickingReference) dismissMapInformation();
  }, [pickingReference, dismissMapInformation]);

  useReferenceOverlays(runtime, {
    referencePoint,
    referenceCandidate,
    referenceTarget,
    referenceRings,
    pickingReference,
  });

  useReferenceNavigation(
    runtime,
    { referenceView, referenceCandidate },
    interactions,
  );

  return (
    <div className="map-frame" aria-label="시설 위치 지도">
      <div
        ref={elementRef}
        className={`map-canvas ${pickingReference ? "picking-reference" : ""}`}
      />
      <canvas
        ref={weatherSurfaceCanvasRef}
        className="weather-map-canvas weather-map-surface"
        aria-hidden="true"
      />
      <canvas
        ref={windParticleCanvasRef}
        className="weather-map-canvas wind-particle-canvas"
        aria-hidden="true"
      />
      {mapInformation && (
        <MapInformationCard
          anchor={mapInformation.anchor}
          viewport={mapInformation.viewport}
          content={mapInformation.content}
          onClose={() => dismissMapInformation()}
        />
      )}
      {error && (
        <div className="map-error" role="alert">
          <strong>지도를 표시할 수 없습니다.</strong>
          <span>{error}</span>
          <small>시설 검색과 상세정보는 계속 사용할 수 있습니다.</small>
        </div>
      )}
    </div>
  );
}
