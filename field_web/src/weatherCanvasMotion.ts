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
