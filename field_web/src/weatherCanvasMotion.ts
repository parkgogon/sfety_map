export const WEATHER_CANVAS_MIN_OVERSCAN = 128;
export const WEATHER_CANVAS_MAX_OVERSCAN = 256;

export interface WeatherCanvasPoint {
  x: number;
  y: number;
}

export interface WeatherCanvasLayout {
  viewportWidth: number;
  viewportHeight: number;
  overscan: number;
  bufferWidth: number;
  bufferHeight: number;
  offsetX: number;
  offsetY: number;
}

export function calculateWeatherCanvasLayout(
  viewportWidth: number,
  viewportHeight: number,
): WeatherCanvasLayout {
  const width = Math.max(1, Math.round(viewportWidth));
  const height = Math.max(1, Math.round(viewportHeight));
  const overscan = Math.min(
    WEATHER_CANVAS_MAX_OVERSCAN,
    Math.max(
      WEATHER_CANVAS_MIN_OVERSCAN,
      Math.round(Math.min(width, height) * 0.3),
    ),
  );

  return {
    viewportWidth: width,
    viewportHeight: height,
    overscan,
    bufferWidth: width + overscan * 2,
    bufferHeight: height + overscan * 2,
    offsetX: overscan,
    offsetY: overscan,
  };
}

export function offsetWeatherCanvasPoint(
  point: WeatherCanvasPoint,
  layout: WeatherCanvasLayout,
): WeatherCanvasPoint {
  return {
    x: point.x + layout.offsetX,
    y: point.y + layout.offsetY,
  };
}

export function calculateWeatherPanTranslation(
  startPoint: WeatherCanvasPoint,
  currentPoint: WeatherCanvasPoint,
): WeatherCanvasPoint {
  return {
    x: currentPoint.x - startPoint.x,
    y: currentPoint.y - startPoint.y,
  };
}

export function weatherCanvasTransform(translation: WeatherCanvasPoint): string {
  return `translate3d(${translation.x}px, ${translation.y}px, 0)`;
}

/** Transform a rendered picture using three non-collinear map coordinates. */
export function weatherCanvasAffineTransform(from: WeatherCanvasPoint[], to: WeatherCanvasPoint[]): string | null {
  if (from.length !== 3 || to.length !== 3 || [...from, ...to].some((p) => !Number.isFinite(p.x) || !Number.isFinite(p.y))) return null;
  const u = { x: from[1].x - from[0].x, y: from[1].y - from[0].y };
  const v = { x: from[2].x - from[0].x, y: from[2].y - from[0].y };
  const nextU = { x: to[1].x - to[0].x, y: to[1].y - to[0].y };
  const nextV = { x: to[2].x - to[0].x, y: to[2].y - to[0].y };
  const determinant = u.x * v.y - u.y * v.x;
  if (Math.abs(determinant) < 0.000001) return null;
  const a = (nextU.x * v.y - nextV.x * u.y) / determinant;
  const b = (nextU.y * v.y - nextV.y * u.y) / determinant;
  const c = (nextV.x * u.x - nextU.x * v.x) / determinant;
  const d = (nextV.y * u.x - nextU.y * v.x) / determinant;
  const e = to[0].x - a * from[0].x - c * from[0].y;
  const f = to[0].y - b * from[0].x - d * from[0].y;
  return `matrix(${[a, b, c, d, e, f].map((value) => Number(value.toFixed(8))).join(", ")})`;
}

export interface AnimationFrameScheduler {
  schedule: () => void;
  cancel: () => void;
}

export function createAnimationFrameScheduler(
  requestFrame: (callback: FrameRequestCallback) => number,
  cancelFrame: (frameId: number) => void,
  callback: (timestamp: number) => void,
): AnimationFrameScheduler {
  let frameId: number | null = null;

  return {
    schedule() {
      if (frameId !== null) return;
      frameId = requestFrame((timestamp) => {
        frameId = null;
        callback(timestamp);
      });
    },
    cancel() {
      if (frameId === null) return;
      cancelFrame(frameId);
      frameId = null;
    },
  };
}
