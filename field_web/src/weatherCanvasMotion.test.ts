import { describe, expect, it, vi } from "vitest";
import {
  calculateWeatherCanvasLayout,
  calculateWeatherPanTranslation,
  createAnimationFrameScheduler,
  offsetWeatherCanvasPoint,
  weatherCanvasTransform,
  WEATHER_CANVAS_MAX_OVERSCAN,
  WEATHER_CANVAS_MIN_OVERSCAN,
} from "./weatherCanvasMotion";

describe("weatherCanvasMotion", () => {
  it("짧은 변의 30%를 128~256px로 제한해 buffer를 만든다", () => {
    const mobile = calculateWeatherCanvasLayout(390, 844);
    expect(mobile).toEqual({
      viewportWidth: 390,
      viewportHeight: 844,
      overscan: WEATHER_CANVAS_MIN_OVERSCAN,
      bufferWidth: 646,
      bufferHeight: 1100,
      offsetX: WEATHER_CANVAS_MIN_OVERSCAN,
      offsetY: WEATHER_CANVAS_MIN_OVERSCAN,
    });

    const desktop = calculateWeatherCanvasLayout(1440, 900);
    expect(desktop.overscan).toBe(WEATHER_CANVAS_MAX_OVERSCAN);
    expect(desktop.bufferWidth).toBe(1952);
    expect(desktop.bufferHeight).toBe(1412);

    expect(calculateWeatherCanvasLayout(800, 600).overscan).toBe(180);
  });

  it("viewport 투영점에 buffer의 overscan offset을 더한다", () => {
    const layout = calculateWeatherCanvasLayout(800, 600);
    expect(offsetWeatherCanvasPoint({ x: 25.5, y: 80 }, layout)).toEqual({
      x: 205.5,
      y: 260,
    });
  });

  it("같은 지도 좌표의 화면점 차이를 canvas translate3d로 변환한다", () => {
    const translation = calculateWeatherPanTranslation(
      { x: 400, y: 300 },
      { x: 438.5, y: 276 },
    );
    expect(translation).toEqual({ x: 38.5, y: -24 });
    expect(weatherCanvasTransform(translation)).toBe(
      "translate3d(38.5px, -24px, 0)",
    );
  });

  it("여러 갱신을 animation frame 하나로 합치고 cleanup에서 취소한다", () => {
    const queuedCallbacks: FrameRequestCallback[] = [];
    let nextFrameId = 1;
    const requestFrame = vi.fn((callback: FrameRequestCallback) => {
      queuedCallbacks.push(callback);
      return nextFrameId++;
    });
    const cancelFrame = vi.fn();
    const callback = vi.fn();
    const scheduler = createAnimationFrameScheduler(
      requestFrame,
      cancelFrame,
      callback,
    );

    scheduler.schedule();
    scheduler.schedule();
    scheduler.schedule();
    expect(requestFrame).toHaveBeenCalledTimes(1);

    queuedCallbacks[0](16);
    expect(callback).toHaveBeenCalledWith(16);

    scheduler.schedule();
    expect(requestFrame).toHaveBeenCalledTimes(2);
    scheduler.cancel();
    expect(cancelFrame).toHaveBeenCalledWith(2);
  });
});
