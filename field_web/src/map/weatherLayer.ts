import type { KakaoSDK, KakaoMapInstance, KakaoLatLng } from "../kakaoTypes";
import { useEffect } from "react";

import { inspectMapWeatherAt } from "../mapWeatherInspection";

import type { WeatherLayerPoint, WeatherLayerResponse } from "../types";

import {
  drawScalarLayer,
  type ScreenWeatherPoint,
} from "../weatherLayerRendering";
import {
  calculateWeatherCanvasLayout,
  createAnimationFrameScheduler,
  offsetWeatherCanvasPoint,
  weatherCanvasTransform,
  weatherCanvasAffineTransform,
  type WeatherCanvasLayout,
  type WeatherCanvasPoint,
} from "../weatherCanvasMotion";
import {
  createWindParticleAnimation,
  type WindParticleAnimationController,
} from "../windParticleAnimation";
import {
  advanceWindParticleSystem,
  buildWindVectorField,
  initializeWindParticleSystem,
  type WindVectorField,
} from "../windParticleField";
import { drawWindSpeedLayer } from "../windSpeedRendering";
import { drawRefinedWindFlow, refinedWindCount, refinedWindSpeed } from "../refinedWindFlow";
import { drawScalarMapLabels, scalarMapLabels, READABLE_SCALAR_ALPHA, type MapLabelRect } from "../scalarMapLabels";
import type { Facility } from "../types";

import type { KakaoMapProps } from "../KakaoMap";
import type { KakaoMapRuntime } from "./useKakaoMapRuntime";
import type { MapInteractions } from "./types";
import { captureWeatherTiles, currentWeatherTilePoints, type WeatherTileAnchor } from "./weatherProjection";

interface WindCanvasRenderResult {
  context: CanvasRenderingContext2D;
  field: WindVectorField;
  layout: WeatherCanvasLayout;
}

function projectedWeatherPoints(
  kakao: KakaoSDK,
  map: KakaoMapInstance,
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

function prepareWeatherCanvas(
  canvas: HTMLCanvasElement,
  layout: WeatherCanvasLayout,
  ratio: number,
): CanvasRenderingContext2D | null {
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
  return context;
}

function renderWeatherCanvases(
  surfaceCanvas: HTMLCanvasElement,
  particleCanvas: HTMLCanvasElement,
  element: HTMLDivElement,
  kakao: KakaoSDK,
  map: KakaoMapInstance,
  layer: WeatherLayerResponse | null,
  facilities: Facility[],
): WindCanvasRenderResult | null {
  const layout = calculateWeatherCanvasLayout(
    element.clientWidth,
    element.clientHeight,
  );
  const ratio = Math.min(2, window.devicePixelRatio || 1);
  const surfaceContext = prepareWeatherCanvas(surfaceCanvas, layout, ratio);
  const particleContext = prepareWeatherCanvas(particleCanvas, layout, ratio);
  if (!layer || !layer.points.length) {
    return null;
  }
  if (!surfaceContext || !particleContext) return null;
  const points = projectedWeatherPoints(kakao, map, layer.points, layout);
  if (layer.layer === "wind") {
    const field = buildWindVectorField(
      points,
      layout.bufferWidth,
      layout.bufferHeight,
    );
    if (!field) return null;
    drawWindSpeedLayer(surfaceContext, field);
    surfaceCanvas.style.opacity = "1";
    particleCanvas.style.opacity = "1";
    return { context: particleContext, field, layout };
  }
  drawScalarLayer(
    surfaceContext,
    layout.bufferWidth,
    layout.bufferHeight,
    points,
    layer.layer,
    READABLE_SCALAR_ALPHA[layer.layer],
  );
  const mapRect = element.getBoundingClientRect();
  const exclusions: MapLabelRect[] = [...weatherOverlayElements(element), ...element.querySelectorAll("[data-facility-cluster]")].map((overlay) => {
    const rect = overlay.getBoundingClientRect();
    return { x: rect.left - mapRect.left + layout.offsetX, y: rect.top - mapRect.top + layout.offsetY,
      width: rect.width, height: rect.height };
  }).filter((rect) => rect.width > 0 && rect.height > 0);
  for (const facility of facilities) {
    const point = map.getProjection().containerPointFromCoords(new kakao.maps.LatLng(facility.latitude, facility.longitude));
    exclusions.push({ x: point.x + layout.offsetX - 20, y: point.y + layout.offsetY - 38, width: 40, height: 50 });
  }
  drawScalarMapLabels(surfaceContext, scalarMapLabels(points, layer.layer, {
    x: layout.offsetX, y: layout.offsetY, width: layout.viewportWidth, height: layout.viewportHeight,
  }, exclusions));
  surfaceCanvas.style.opacity = "1";
  return null;
}

function weatherOverlayElements(element: HTMLElement): Element[] {
  const container = element.closest(".map-stage, .control-map-container");
  return Array.from(container?.querySelectorAll(
    ".map-search-panel, .control-location-panel, .facility-sheet, .mobile-map-top-controls, "
    + ".mobile-map-bottom-controls, .weather-layer-legend, .map-information-card, .mobile-candidate-panel, .mobile-picking-guide",
  ) ?? []);
}

export function useWeatherMapLayer(
  runtime: KakaoMapRuntime,
  options: Required<Pick<KakaoMapProps, "weatherLayer" | "facilities">>,
  interactions: Pick<
    MapInteractions,
    | "pickReferenceAt"
    | "dismissMapInformation"
    | "setMapInformation"
    | "suppressMapInspectionUntilRef"
    | "weatherSurfaceCanvasRef"
    | "windParticleCanvasRef"
  >,
) {
  const { elementRef, mapRef, kakaoRef, subscribeReady } = runtime;
  const { weatherLayer, facilities } = options;
  const {
    pickReferenceAt,
    dismissMapInformation,
    setMapInformation,
    suppressMapInspectionUntilRef,
    weatherSurfaceCanvasRef,
    windParticleCanvasRef,
  } = interactions;

  useEffect(() => {
    let moving = false;
    let zooming = false;
    let renderedProjection: {
      coordinates: KakaoLatLng[];
      points: WeatherCanvasPoint[];
      layout: WeatherCanvasLayout;
      tiles: WeatherTileAnchor[] | null;
    } | null = null;
    let windAnimation: WindParticleAnimationController | null = null;
    const requestFrame = window.requestAnimationFrame.bind(window);
    const cancelFrame = window.cancelAnimationFrame.bind(window);
    const motionQuery =
      typeof window.matchMedia === "function"
        ? window.matchMedia("(prefers-reduced-motion: reduce)")
        : null;

    const stopWindAnimation = () => {
      windAnimation?.dispose();
      windAnimation = null;
    };

    const startWindAnimation = (result: WindCanvasRenderResult) => {
      let state = initializeWindParticleSystem(
        result.field,
        refinedWindCount(
          result.layout.viewportWidth,
          result.layout.viewportHeight,
        ),
        0x4b45434f,
      );
      if (!state.particles.length) return;
      state.particles.forEach((particle, index) => { particle.ageSeconds = particle.maxAgeSeconds * ((index * 0.618034) % 1); });
      drawRefinedWindFlow(result.context, result.field, state.particles, Boolean(motionQuery?.matches));
      if (motionQuery?.matches) return;
      windAnimation = createWindParticleAnimation({
        requestFrame,
        cancelFrame,
        onFrame(deltaSeconds) {
          state = advanceWindParticleSystem(result.field, state, deltaSeconds, refinedWindSpeed);
          drawRefinedWindFlow(result.context, result.field, state.particles);
        },
      });
      if (!document.hidden && !zooming) windAnimation.start();
    };

    const resetPan = () => {
      const transform = weatherCanvasTransform({ x: 0, y: 0 });
      [weatherSurfaceCanvasRef.current, windParticleCanvasRef.current].forEach(
        (canvas) => {
          if (canvas) { canvas.style.transformOrigin = "0 0"; canvas.style.transform = transform; }
        },
      );
    };

    const alignRenderedPicture = () => {
      const map = mapRef.current;
      const element = elementRef.current;
      if (!map || !element || !renderedProjection) return;
      const tilePoints = renderedProjection.tiles ? currentWeatherTilePoints(renderedProjection.tiles, element, renderedProjection.layout) : null;
      const points = tilePoints ?? renderedProjection.coordinates.map((coordinate) => offsetWeatherCanvasPoint(
        map.getProjection().containerPointFromCoords(coordinate), renderedProjection!.layout));
      const original = tilePoints ? renderedProjection.tiles!.map((tile) => tile.point) : renderedProjection.points;
      const transform = weatherCanvasAffineTransform(original, points);
      [weatherSurfaceCanvasRef.current, windParticleCanvasRef.current].forEach((canvas) => {
        if (canvas && transform) { canvas.style.transformOrigin = "0 0"; canvas.style.transform = transform; }
      });
    };
    const followMapScheduler = createAnimationFrameScheduler(requestFrame, cancelFrame, () => {
      alignRenderedPicture();
      if (moving) followMapScheduler.schedule();
    });

    const drawScheduler = createAnimationFrameScheduler(
      requestFrame,
      cancelFrame,
      () => {
        if (zooming) return;
        const surfaceCanvas = weatherSurfaceCanvasRef.current;
        const particleCanvas = windParticleCanvasRef.current;
        const element = elementRef.current;
        const kakao = kakaoRef.current;
        const map = mapRef.current;
        if (!surfaceCanvas || !particleCanvas || !element || !kakao || !map)
          return;
        followMapScheduler.cancel();
        const result = renderWeatherCanvases(
          surfaceCanvas,
          particleCanvas,
          element,
          kakao,
          map,
          weatherLayer,
          facilities,
        );
        const layout = calculateWeatherCanvasLayout(element.clientWidth, element.clientHeight);
        const center = map.getCenter();
        const span = 0.02 * 2 ** (map.getLevel() - 5);
        const coordinates = [center,
          new kakao.maps.LatLng(Math.min(85, center.getLat() + span), center.getLng()),
          new kakao.maps.LatLng(center.getLat(), Math.min(180, center.getLng() + span))];
        renderedProjection = weatherLayer?.points.length ? { coordinates, layout, tiles: captureWeatherTiles(element, layout),
          points: coordinates.map((coordinate) => offsetWeatherCanvasPoint(map.getProjection().containerPointFromCoords(coordinate), layout)),
        } : null;
        resetPan();
        observeOverlaySizes();
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
      dismissMapInformation();
      moving = true;
      alignRenderedPicture();
      followMapScheduler.schedule();
    };
    const movePan = () => {
      moving = true;
      alignRenderedPicture();
      followMapScheduler.schedule();
    };
    const startZoom = () => {
      zooming = true;
      moving = true;
      dismissMapInformation();
      windAnimation?.pause();
      alignRenderedPicture();
      followMapScheduler.schedule();
    };
    const settleMap = () => {
      zooming = false;
      moving = false;
      alignRenderedPicture();
      draw();
    };
    const handleVisibilityChange = () => {
      if (document.hidden) windAnimation?.pause();
      else if (!zooming) windAnimation?.start();
    };
    const inspectMapPoint = (mouseEvent: { latLng?: KakaoLatLng }) => {
      if (Date.now() <= suppressMapInspectionUntilRef.current) {
        suppressMapInspectionUntilRef.current = 0;
        return;
      }
      if (pickReferenceAt(mouseEvent.latLng)) return;
      const element = elementRef.current;
      const kakao = kakaoRef.current;
      const map = mapRef.current;
      if (!element || !kakao || !map || !weatherLayer || !mouseEvent.latLng) {
        dismissMapInformation();
        return;
      }
      const viewportPoint = map
        .getProjection()
        .containerPointFromCoords(mouseEvent.latLng);
      const layout = calculateWeatherCanvasLayout(
        element.clientWidth,
        element.clientHeight,
      );
      const bufferPoint = offsetWeatherCanvasPoint(viewportPoint, layout);
      const points = projectedWeatherPoints(
        kakao,
        map,
        weatherLayer.points,
        layout,
      );
      setMapInformation({
        anchor: { x: viewportPoint.x, y: viewportPoint.y },
        viewport: {
          width: layout.viewportWidth,
          height: layout.viewportHeight,
        },
        content: inspectMapWeatherAt(
          weatherLayer,
          points,
          bufferPoint.x,
          bufferPoint.y,
        ),
      });
    };
    const handleResize = () => {
      dismissMapInformation();
      draw();
    };
    const observedOverlays = new Set<Element>();
    const resizeObserver = typeof ResizeObserver !== "undefined" ? new ResizeObserver((entries) => {
      if (weatherLayer?.layer !== "wind" || entries.some((entry) => entry.target === elementRef.current)) draw();
    }) : null;
    const observeOverlaySizes = () => {
      const element = elementRef.current;
      if (!element || !resizeObserver) return;
      const elements = new Set([element, ...weatherOverlayElements(element)]);
      const changed = elements.size !== observedOverlays.size || [...elements].some((overlay) => !observedOverlays.has(overlay));
      observedOverlays.forEach((overlay) => { if (!elements.has(overlay)) { resizeObserver.unobserve(overlay); observedOverlays.delete(overlay); } });
      elements.forEach((overlay) => { if (!observedOverlays.has(overlay)) { observedOverlays.add(overlay); resizeObserver.observe(overlay); } });
      if (changed) {
        overlayObserver?.disconnect();
        if (container) overlayObserver?.observe(container, { childList: true });
        elements.forEach((overlay) => {
          if (overlay !== element) overlayObserver?.observe(overlay, { attributes: true, attributeFilter: ["style", "class", "hidden"] });
        });
      }
    };
    const overlayObserver = typeof MutationObserver !== "undefined" ? new MutationObserver((records) => {
      observeOverlaySizes();
      if (weatherLayer?.layer !== "wind" && records.some((record) => record.type === "attributes")) draw();
    }) : null;
    const container = elementRef.current?.closest(".map-stage, .control-map-container");
    if (container) overlayObserver?.observe(container, { childList: true });
    let listeningKakao: KakaoSDK | null = null;
    let listeningMap: KakaoMapInstance | null = null;
    const detachMapListeners = () => {
      if (!listeningKakao || !listeningMap) return;
      listeningKakao.maps.event.removeListener(
        listeningMap,
        "dragstart",
        startPan,
      );
      listeningKakao.maps.event.removeListener(
        listeningMap,
        "center_changed",
        movePan,
      );
      listeningKakao.maps.event.removeListener(
        listeningMap,
        "zoom_start",
        startZoom,
      );
      listeningKakao.maps.event.removeListener(listeningMap, "idle", settleMap);
      listeningKakao.maps.event.removeListener(listeningMap, "zoom_changed", settleMap);
      listeningKakao.maps.event.removeListener(
        listeningMap,
        "click",
        inspectMapPoint,
      );
      listeningKakao = null;
      listeningMap = null;
    };
    const attachMapListeners = () => {
      const kakao = kakaoRef.current;
      const map = mapRef.current;
      if (!kakao || !map || map === listeningMap) return;
      detachMapListeners();
      kakao.maps.event.addListener(map, "dragstart", startPan);
      kakao.maps.event.addListener(map, "center_changed", movePan);
      kakao.maps.event.addListener(map, "zoom_start", startZoom);
      kakao.maps.event.addListener(map, "idle", settleMap);
      kakao.maps.event.addListener(map, "zoom_changed", settleMap);
      kakao.maps.event.addListener(map, "click", inspectMapPoint);
      listeningKakao = kakao;
      listeningMap = map;
    };
    const handleMapReady = () => {
      attachMapListeners();
      draw();
    };
    attachMapListeners();
    draw();
    window.addEventListener("resize", handleResize);
    const unsubscribeReady = subscribeReady(handleMapReady);
    document.addEventListener("visibilitychange", handleVisibilityChange);
    motionQuery?.addEventListener?.("change", draw);
    return () => {
      stopWindAnimation();
      drawScheduler.cancel();
      followMapScheduler.cancel();
      resizeObserver?.disconnect();
      overlayObserver?.disconnect();
      resetPan();
      window.removeEventListener("resize", handleResize);
      unsubscribeReady();
      document.removeEventListener("visibilitychange", handleVisibilityChange);
      motionQuery?.removeEventListener?.("change", draw);
      detachMapListeners();
    };
  }, [dismissMapInformation, weatherLayer, facilities, pickReferenceAt, subscribeReady]);
}
