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
  calculateWeatherPanTranslation,
  createAnimationFrameScheduler,
  offsetWeatherCanvasPoint,
  weatherCanvasTransform,
  type WeatherCanvasLayout,
  type WeatherCanvasPoint,
} from "../weatherCanvasMotion";
import {
  calculateWindParticleCount,
  createWindParticleAnimation,
  drawStaticWindFlow,
  drawWindParticleFrame,
  type WindParticleAnimationController,
} from "../windParticleAnimation";
import {
  advanceWindParticleSystem,
  buildWindVectorField,
  initializeWindParticleSystem,
  type WindVectorField,
} from "../windParticleField";
import { drawWindSpeedLayer } from "../windSpeedRendering";

import type { KakaoMapProps } from "../KakaoMap";
import type { KakaoMapRuntime } from "./useKakaoMapRuntime";
import type { MapInteractions } from "./types";

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
  canvas.style.opacity = "0";
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
  );
  surfaceCanvas.style.opacity = "1";
  return null;
}

export function useWeatherMapLayer(
  runtime: KakaoMapRuntime,
  options: Required<Pick<KakaoMapProps, "weatherLayer">>,
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
  const { weatherLayer } = options;
  const {
    pickReferenceAt,
    dismissMapInformation,
    setMapInformation,
    suppressMapInspectionUntilRef,
    weatherSurfaceCanvasRef,
    windParticleCanvasRef,
  } = interactions;

  useEffect(() => {
    let dragging = false;
    let zooming = false;
    let panAnchor: {
      coordinate: KakaoLatLng;
      startPoint: WeatherCanvasPoint;
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
      const transform = weatherCanvasTransform({ x: 0, y: 0 });
      [weatherSurfaceCanvasRef.current, windParticleCanvasRef.current].forEach(
        (canvas) => {
          if (canvas) canvas.style.transform = transform;
        },
      );
    };

    const panScheduler = createAnimationFrameScheduler(
      requestFrame,
      cancelFrame,
      () => {
        const map = mapRef.current;
        if (!map || !dragging || !panAnchor) return;
        const currentPoint = map
          .getProjection()
          .containerPointFromCoords(panAnchor.coordinate);
        const transform = weatherCanvasTransform(
          calculateWeatherPanTranslation(panAnchor.startPoint, currentPoint),
        );
        [
          weatherSurfaceCanvasRef.current,
          windParticleCanvasRef.current,
        ].forEach((canvas) => {
          if (canvas) canvas.style.transform = transform;
        });
      },
    );

    const drawScheduler = createAnimationFrameScheduler(
      requestFrame,
      cancelFrame,
      () => {
        const surfaceCanvas = weatherSurfaceCanvasRef.current;
        const particleCanvas = windParticleCanvasRef.current;
        const element = elementRef.current;
        const kakao = kakaoRef.current;
        const map = mapRef.current;
        if (!surfaceCanvas || !particleCanvas || !element || !kakao || !map)
          return;
        panScheduler.cancel();
        const result = renderWeatherCanvases(
          surfaceCanvas,
          particleCanvas,
          element,
          kakao,
          map,
          weatherLayer,
        );
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
      dismissMapInformation();
      const coordinate = map.getCenter();
      const startPoint = map
        .getProjection()
        .containerPointFromCoords(coordinate);
      dragging = true;
      panAnchor = { coordinate, startPoint };
    };
    const movePan = () => {
      if (dragging && panAnchor) panScheduler.schedule();
    };
    const hideForZoom = () => {
      zooming = true;
      dismissMapInformation();
      stopWindAnimation();
      panScheduler.cancel();
      resetPan();
      [weatherSurfaceCanvasRef.current, windParticleCanvasRef.current].forEach(
        (canvas) => {
          if (canvas) canvas.style.opacity = "0";
        },
      );
    };
    const settleMap = () => {
      zooming = false;
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
        hideForZoom,
      );
      listeningKakao.maps.event.removeListener(listeningMap, "idle", settleMap);
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
      kakao.maps.event.addListener(map, "zoom_start", hideForZoom);
      kakao.maps.event.addListener(map, "idle", settleMap);
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
      panScheduler.cancel();
      resetPan();
      window.removeEventListener("resize", handleResize);
      unsubscribeReady();
      document.removeEventListener("visibilitychange", handleVisibilityChange);
      motionQuery?.removeEventListener?.("change", draw);
      detachMapListeners();
    };
  }, [dismissMapInformation, weatherLayer, pickReferenceAt, subscribeReady]);
}
