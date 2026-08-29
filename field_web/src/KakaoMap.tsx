import { useEffect, useRef, useState } from "react";
import { loadKakaoMaps } from "./kakao";
import {
  CLUSTER_GRID_SIZE,
  CLUSTER_MARKER_SIZE,
  CLUSTER_MIN_LEVEL,
  CLUSTER_MIN_SIZE,
  MAP_MARKER_Z_INDEX,
  facilityMarkerSize,
} from "./mapVisuals";
import type {
  Facility,
  MapFocusRequest,
  NearbyCctv,
  RiskGrade,
  WeatherLayerPoint,
  WeatherLayerResponse,
  WarningZoneFeature,
} from "./types";
import {
  cctvDirectionText,
  GRADE_PRIORITY_ORDER,
  shouldFitInitialFacilities,
  shouldShowMapZoomControl,
} from "./utils";
import { drawScalarLayer, type ScreenWeatherPoint } from "./weatherLayerRendering";
import {
  calculateWeatherCanvasLayout,
  calculateWeatherPanTranslation,
  createAnimationFrameScheduler,
  offsetWeatherCanvasPoint,
  weatherCanvasTransform,
  type WeatherCanvasLayout,
  type WeatherCanvasPoint,
} from "./weatherCanvasMotion";
import {
  calculateWindParticleCount,
  createWindParticleAnimation,
  drawStaticWindFlow,
  drawWindParticleFrame,
  type WindParticleAnimationController,
} from "./windParticleAnimation";
import {
  advanceWindParticleSystem,
  buildWindVectorField,
  initializeWindParticleSystem,
  type WindVectorField,
} from "./windParticleField";

interface KakaoMapProps {
  facilities: Facility[];
  warningZones: WarningZoneFeature[];
  selectedFacilityId: string;
  cctvs: NearbyCctv[];
  selectedCctvId: string;
  focusRequest: MapFocusRequest | null;
  weatherLayer: WeatherLayerResponse | null;
  onSelect: (facility: Facility) => void;
  onSelectGroup: (facilities: Facility[]) => void;
  onSelectCctv: (cctv: NearbyCctv) => void;
}

interface WindCanvasRenderResult {
  context: CanvasRenderingContext2D;
  field: WindVectorField;
  layout: WeatherCanvasLayout;
}

function projectedWeatherPoints(
  kakao: any,
  map: any,
  points: WeatherLayerPoint[],
  layout: WeatherCanvasLayout,
): ScreenWeatherPoint[] {
  const projection = map.getProjection();
  return points.map((source) => {
    const pixel = projection.containerPointFromCoords(
      new kakao.maps.LatLng(source.latitude, source.longitude),
    );
    const bufferPoint = offsetWeatherCanvasPoint(pixel, layout);
    return { source, x: bufferPoint.x, y: bufferPoint.y };
  });
}

function renderWeatherCanvas(
  canvas: HTMLCanvasElement,
  element: HTMLDivElement,
  kakao: any,
  map: any,
  layer: WeatherLayerResponse | null,
): WindCanvasRenderResult | null {
  const layout = calculateWeatherCanvasLayout(
    element.clientWidth,
    element.clientHeight,
  );
  const ratio = Math.min(2, window.devicePixelRatio || 1);
  canvas.width = Math.max(1, Math.round(layout.bufferWidth * ratio));
  canvas.height = Math.max(1, Math.round(layout.bufferHeight * ratio));
  canvas.style.left = `${-layout.overscan}px`;
  canvas.style.top = `${-layout.overscan}px`;
  canvas.style.width = `${layout.bufferWidth}px`;
  canvas.style.height = `${layout.bufferHeight}px`;
  const context = canvas.getContext("2d");
  if (!context) return null;
  context.setTransform(ratio, 0, 0, ratio, 0, 0);
  context.clearRect(0, 0, layout.bufferWidth, layout.bufferHeight);
  if (!layer || !layer.points.length) {
    canvas.style.opacity = "0";
    return null;
  }
  const points = projectedWeatherPoints(kakao, map, layer.points, layout);
  if (layer.layer === "wind") {
    const field = buildWindVectorField(
      points,
      layout.bufferWidth,
      layout.bufferHeight,
    );
    if (!field) {
      canvas.style.opacity = "0";
      return null;
    }
    canvas.style.opacity = "1";
    return { context, field, layout };
  }
  drawScalarLayer(
    context,
    layout.bufferWidth,
    layout.bufferHeight,
    points,
    layer.layer,
  );
  canvas.style.opacity = "1";
  return null;
}

const GRADE_RANK = new Map<RiskGrade, number>(
  GRADE_PRIORITY_ORDER.map((grade, index) => [
    grade,
    GRADE_PRIORITY_ORDER.length - index,
  ]),
);

function strongest(facilities: Facility[]): Facility {
  return [...facilities].sort(
    (left, right) => (GRADE_RANK.get(right.grade) ?? 0) - (GRADE_RANK.get(left.grade) ?? 0),
  )[0];
}

function markerImage(kakao: any, facilities: Facility[], selected: boolean): any {
  const primary = strongest(facilities);
  const count = facilities.length > 1 ? String(facilities.length) : "";
  const size = facilityMarkerSize(facilities.length, selected);
  const radius = size / 2 - 3;
  const svg = `
    <svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}">
      <circle cx="${size / 2}" cy="${size / 2}" r="${radius + (selected ? 1 : 0)}"
        fill="white" stroke="${selected ? "#142746" : "rgba(20,39,70,.18)"}"
        stroke-width="${selected ? 4 : 1.5}"/>
      <circle cx="${size / 2}" cy="${size / 2}" r="${Math.max(7, radius - 4)}"
        fill="${primary.grade_color}"/>
      ${count ? `<text x="50%" y="54%" dominant-baseline="middle" text-anchor="middle"
        font-family="Arial,sans-serif" font-size="${size < 38 ? 10 : 12}" font-weight="700"
        fill="white">${count}</text>` : ""}
    </svg>`;
  const url = `data:image/svg+xml;charset=UTF-8,${encodeURIComponent(svg)}`;
  return new kakao.maps.MarkerImage(
    url,
    new kakao.maps.Size(size, size),
    { offset: new kakao.maps.Point(size / 2, size / 2) },
  );
}

function coordinateGroups(facilities: Facility[]): Facility[][] {
  const groups = new Map<string, Facility[]>();
  facilities.forEach((facility) => {
    const key = `${facility.latitude.toFixed(7)}:${facility.longitude.toFixed(7)}`;
    groups.set(key, [...(groups.get(key) ?? []), facility]);
  });
  return [...groups.values()];
}

function cctvMarkerImage(kakao: any, cctv: NearbyCctv, selected: boolean): any {
  const size = selected ? 50 : 44;
  const center = size / 2;
  const bearing = cctv.bearing_deg;
  const arrow = bearing === null ? "" : `
    <path d="M ${center} 2 L ${center - 4.5} 12 L ${center + 4.5} 12 Z"
      fill="#0f766e" stroke="white" stroke-width="1.5"
      transform="rotate(${bearing} ${center} ${center})"/>`;
  const svg = `
    <svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}">
      ${arrow}
      <circle cx="${center}" cy="${center}" r="15" fill="white"
        stroke="${selected ? "#142746" : "rgba(20,39,70,.22)"}"
        stroke-width="${selected ? 3 : 1.5}"/>
      <rect x="${center - 9}" y="${center - 6}" width="14" height="12" rx="2.5"
        fill="#142746"/>
      <path d="M ${center + 5} ${center - 3} L ${center + 11} ${center - 7}
        L ${center + 11} ${center + 7} L ${center + 5} ${center + 3} Z" fill="#142746"/>
      <circle cx="${center - 3}" cy="${center}" r="2.5" fill="#7dd3fc"/>
    </svg>`;
  return new kakao.maps.MarkerImage(
    `data:image/svg+xml;charset=UTF-8,${encodeURIComponent(svg)}`,
    new kakao.maps.Size(size, size),
    { offset: new kakao.maps.Point(center, center) },
  );
}

function polygonPaths(kakao: any, feature: WarningZoneFeature): any[][][] {
  const polygons = feature.geometry.type === "Polygon"
    ? [feature.geometry.coordinates]
    : feature.geometry.coordinates;
  return (polygons as number[][][][]).map((polygon) =>
    polygon.map((ring) =>
      ring.map(([longitude, latitude]) => new kakao.maps.LatLng(latitude, longitude)),
    ),
  );
}

export function KakaoMap({
  facilities,
  warningZones,
  selectedFacilityId,
  cctvs,
  selectedCctvId,
  focusRequest,
  weatherLayer,
  onSelect,
  onSelectGroup,
  onSelectCctv,
}: KakaoMapProps) {
  const elementRef = useRef<HTMLDivElement>(null);
  const weatherCanvasRef = useRef<HTMLCanvasElement>(null);
  const mapRef = useRef<any>(null);
  const kakaoRef = useRef<any>(null);
  const clustererRef = useRef<any>(null);
  const initialBoundsFittedRef = useRef(false);
  const polygonRef = useRef<any[]>([]);
  const cctvMarkerRef = useRef<any[]>([]);
  const [error, setError] = useState("");
  const appKey = import.meta.env.VITE_KAKAO_MAP_APP_KEY?.trim() ?? "";

  useEffect(() => {
    let cancelled = false;
    loadKakaoMaps(appKey)
      .then((kakao) => {
        if (cancelled || !elementRef.current) return;
        kakaoRef.current = kakao;
        const map = new kakao.maps.Map(elementRef.current, {
          center: new kakao.maps.LatLng(36.0, 128.55),
          level: 10,
        });
        if (shouldShowMapZoomControl(window.innerWidth)) {
          map.addControl(new kakao.maps.ZoomControl(), kakao.maps.ControlPosition.RIGHT);
        }
        mapRef.current = map;
        setError("");
        window.dispatchEvent(new Event("keco-map-ready"));
      })
      .catch((reason: Error) => setError(reason.message));
    return () => {
      cancelled = true;
    };
  }, [appKey]);

  useEffect(() => {
    const onResize = () => {
      if (mapRef.current) kakaoRef.current.maps.event.trigger(mapRef.current, "resize");
    };
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  useEffect(() => {
    const render = () => {
      const kakao = kakaoRef.current;
      const map = mapRef.current;
      if (!kakao || !map) return;
      clustererRef.current?.clear();
      const clusterer = new kakao.maps.MarkerClusterer({
        map,
        averageCenter: true,
        gridSize: CLUSTER_GRID_SIZE,
        minLevel: CLUSTER_MIN_LEVEL,
        minClusterSize: CLUSTER_MIN_SIZE,
        disableClickZoom: false,
        styles: [{
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
        }],
      });
      kakao.maps.event.addListener(clusterer, "clustered", (clusters: any[]) => {
        clusters.forEach((cluster) => {
          cluster.getClusterMarker()?.setZIndex(MAP_MARKER_Z_INDEX);
        });
      });
      clustererRef.current = clusterer;
      const bounds = new kakao.maps.LatLngBounds();
      const markers = coordinateGroups(facilities).map((group) => {
        const first = group[0];
        const position = new kakao.maps.LatLng(first.latitude, first.longitude);
        const marker = new kakao.maps.Marker({
          position,
          title: group.length === 1 ? first.name : `같은 위치의 시설 ${group.length}개`,
          zIndex: MAP_MARKER_Z_INDEX,
          image: markerImage(
            kakao,
            group,
            group.some((facility) => facility.id === selectedFacilityId),
          ),
        });
        kakao.maps.event.addListener(marker, "click", () => {
          if (group.length === 1) onSelect(group[0]);
          else onSelectGroup(group);
        });
        bounds.extend(position);
        return marker;
      });
      clusterer.addMarkers(markers);

      if (shouldFitInitialFacilities(
        initialBoundsFittedRef.current,
        facilities.length,
      )) {
        map.setBounds(bounds, 48, 48, 120, 48);
        initialBoundsFittedRef.current = true;
      }
    };
    render();
    window.addEventListener("keco-map-ready", render);
    return () => window.removeEventListener("keco-map-ready", render);
  }, [facilities, onSelect, onSelectGroup, selectedFacilityId]);

  useEffect(() => {
    const focus = () => {
      const kakao = kakaoRef.current;
      const map = mapRef.current;
      if (!kakao || !map || !focusRequest) return;
      map.panTo(new kakao.maps.LatLng(
        focusRequest.latitude,
        focusRequest.longitude,
      ));
      if (focusRequest.zoom && map.getLevel() > 5) map.setLevel(5);
    };
    focus();
    window.addEventListener("keco-map-ready", focus);
    return () => window.removeEventListener("keco-map-ready", focus);
  }, [focusRequest]);

  useEffect(() => {
    const render = () => {
      const kakao = kakaoRef.current;
      const map = mapRef.current;
      if (!kakao || !map) return;
      cctvMarkerRef.current.forEach((marker) => marker.setMap(null));
      cctvMarkerRef.current = cctvs.map((cctv) => {
        const marker = new kakao.maps.Marker({
          map,
          position: new kakao.maps.LatLng(cctv.latitude, cctv.longitude),
          title: `${cctv.name} · ${cctv.distance_km.toFixed(1)}km · ${cctvDirectionText(cctv)}`,
          image: cctvMarkerImage(kakao, cctv, cctv.id === selectedCctvId),
          zIndex: 20,
        });
        kakao.maps.event.addListener(marker, "click", () => onSelectCctv(cctv));
        return marker;
      });
    };
    render();
    window.addEventListener("keco-map-ready", render);
    return () => window.removeEventListener("keco-map-ready", render);
  }, [cctvs, onSelectCctv, selectedCctvId]);

  useEffect(() => {
    const render = () => {
      const kakao = kakaoRef.current;
      const map = mapRef.current;
      if (!kakao || !map) return;
      polygonRef.current.forEach((polygon) => polygon.setMap(null));
      polygonRef.current = [];
      warningZones.forEach((feature) => {
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
          polygonRef.current.push(polygon);
        });
      });
    };
    render();
    window.addEventListener("keco-map-ready", render);
    return () => window.removeEventListener("keco-map-ready", render);
  }, [warningZones]);

  useEffect(() => {
    let dragging = false;
    let zooming = false;
    let panAnchor: { coordinate: any; startPoint: WeatherCanvasPoint } | null = null;
    let windAnimation: WindParticleAnimationController | null = null;
    const requestFrame = window.requestAnimationFrame.bind(window);
    const cancelFrame = window.cancelAnimationFrame.bind(window);
    const motionQuery = typeof window.matchMedia === "function"
      ? window.matchMedia("(prefers-reduced-motion: reduce)")
      : null;

    const stopWindAnimation = () => {
      windAnimation?.dispose();
      windAnimation = null;
    };

    const startWindAnimation = (result: WindCanvasRenderResult) => {
      let state = initializeWindParticleSystem(
        result.field,
        calculateWindParticleCount(
          result.layout.viewportWidth,
          result.layout.viewportHeight,
        ),
        0x4b45434f,
      );
      if (!state.particles.length) return;
      drawStaticWindFlow(result.context, result.field, state.particles);
      if (motionQuery?.matches) return;
      windAnimation = createWindParticleAnimation({
        requestFrame,
        cancelFrame,
        onFrame(deltaSeconds) {
          state = advanceWindParticleSystem(result.field, state, deltaSeconds);
          drawWindParticleFrame(
            result.context,
            result.layout.bufferWidth,
            result.layout.bufferHeight,
            state.particles,
          );
        },
      });
      if (!document.hidden && !zooming) windAnimation.start();
    };

    const resetPan = () => {
      dragging = false;
      panAnchor = null;
      const canvas = weatherCanvasRef.current;
      if (canvas) canvas.style.transform = weatherCanvasTransform({ x: 0, y: 0 });
    };

    const panScheduler = createAnimationFrameScheduler(
      requestFrame,
      cancelFrame,
      () => {
        const canvas = weatherCanvasRef.current;
        const map = mapRef.current;
        if (!canvas || !map || !dragging || !panAnchor) return;
        const currentPoint = map
          .getProjection()
          .containerPointFromCoords(panAnchor.coordinate);
        canvas.style.transform = weatherCanvasTransform(
          calculateWeatherPanTranslation(panAnchor.startPoint, currentPoint),
        );
      },
    );

    const drawScheduler = createAnimationFrameScheduler(
      requestFrame,
      cancelFrame,
      () => {
        const canvas = weatherCanvasRef.current;
        const element = elementRef.current;
        const kakao = kakaoRef.current;
        const map = mapRef.current;
        if (!canvas || !element || !kakao || !map) return;
        panScheduler.cancel();
        const result = renderWeatherCanvas(canvas, element, kakao, map, weatherLayer);
        resetPan();
        if (result) startWindAnimation(result);
      },
    );
    const draw = () => {
      stopWindAnimation();
      drawScheduler.schedule();
    };

    const startPan = () => {
      const map = mapRef.current;
      if (!map) return;
      const coordinate = map.getCenter();
      const startPoint = map.getProjection().containerPointFromCoords(coordinate);
      dragging = true;
      panAnchor = { coordinate, startPoint };
    };
    const movePan = () => {
      if (dragging && panAnchor) panScheduler.schedule();
    };
    const hideForZoom = () => {
      zooming = true;
      stopWindAnimation();
      panScheduler.cancel();
      resetPan();
      if (weatherCanvasRef.current) weatherCanvasRef.current.style.opacity = "0";
    };
    const settleMap = () => {
      zooming = false;
      draw();
    };
    const handleVisibilityChange = () => {
      if (document.hidden) windAnimation?.pause();
      else if (!zooming) windAnimation?.start();
    };
    const kakao = kakaoRef.current;
    const map = mapRef.current;
    if (kakao && map) {
      kakao.maps.event.addListener(map, "dragstart", startPan);
      kakao.maps.event.addListener(map, "center_changed", movePan);
      kakao.maps.event.addListener(map, "zoom_start", hideForZoom);
      kakao.maps.event.addListener(map, "idle", settleMap);
    }
    draw();
    window.addEventListener("resize", draw);
    window.addEventListener("keco-map-ready", draw);
    document.addEventListener("visibilitychange", handleVisibilityChange);
    motionQuery?.addEventListener?.("change", draw);
    return () => {
      stopWindAnimation();
      drawScheduler.cancel();
      panScheduler.cancel();
      resetPan();
      window.removeEventListener("resize", draw);
      window.removeEventListener("keco-map-ready", draw);
      document.removeEventListener("visibilitychange", handleVisibilityChange);
      motionQuery?.removeEventListener?.("change", draw);
      if (kakao && map) {
        kakao.maps.event.removeListener(map, "dragstart", startPan);
        kakao.maps.event.removeListener(map, "center_changed", movePan);
        kakao.maps.event.removeListener(map, "zoom_start", hideForZoom);
        kakao.maps.event.removeListener(map, "idle", settleMap);
      }
    };
  }, [weatherLayer]);


  return (
    <div className="map-frame" aria-label="시설 위치 지도">
      <div ref={elementRef} className="map-canvas" />
      <canvas ref={weatherCanvasRef} className="weather-map-canvas" aria-hidden="true" />
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
