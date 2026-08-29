import { describe, expect, it, vi } from "vitest";
import type { WindParticle, WindVectorField } from "./windParticleField";
import {
  calculateWindParticleCount,
  createWindParticleAnimation,
  drawStaticWindFlow,
  drawWindParticleFrame,
  WIND_PARTICLE_FRAME_INTERVAL_MS,
  WIND_PARTICLE_MAX_COUNT,
  WIND_PARTICLE_MAX_DELTA_SECONDS,
  WIND_PARTICLE_MIN_COUNT,
  WIND_PARTICLE_OUTLINE,
  WIND_PARTICLE_STROKE,
} from "./windParticleAnimation";

function fakeCanvasContext() {
  const strokes: Array<{ style: string; width: number }> = [];
  const state = { strokeStyle: "", lineWidth: 0 };
  const context = {
    globalCompositeOperation: "source-over",
    fillStyle: "",
    lineCap: "butt",
    lineJoin: "miter",
    get strokeStyle() {
      return state.strokeStyle;
    },
    set strokeStyle(value: string | CanvasGradient | CanvasPattern) {
      state.strokeStyle = String(value);
    },
    get lineWidth() {
      return state.lineWidth;
    },
    set lineWidth(value: number) {
      state.lineWidth = value;
    },
    save: vi.fn(),
    restore: vi.fn(),
    fillRect: vi.fn(),
    beginPath: vi.fn(),
    moveTo: vi.fn(),
    lineTo: vi.fn(),
    stroke() {
      strokes.push({ style: state.strokeStyle, width: state.lineWidth });
    },
  } as unknown as CanvasRenderingContext2D;
  return { context, strokes };
}

describe("windParticleAnimation", () => {
  it("viewport 면적에 따라 파티클을 120~600개로 제한한다", () => {
    expect(calculateWindParticleCount(100, 100)).toBe(WIND_PARTICLE_MIN_COUNT);
    expect(calculateWindParticleCount(390, 844)).toBeGreaterThan(WIND_PARTICLE_MIN_COUNT);
    expect(calculateWindParticleCount(1_440, 900)).toBeLessThanOrEqual(WIND_PARTICLE_MAX_COUNT);
    expect(calculateWindParticleCount(4_000, 4_000)).toBe(WIND_PARTICLE_MAX_COUNT);
  });

  it("animation frame을 약 30fps로 제한하고 긴 중단 뒤 delta를 상한 처리한다", () => {
    let nextId = 1;
    const queued = new Map<number, FrameRequestCallback>();
    const requestFrame = vi.fn((callback: FrameRequestCallback) => {
      const id = nextId++;
      queued.set(id, callback);
      return id;
    });
    const cancelFrame = vi.fn((id: number) => queued.delete(id));
    const onFrame = vi.fn();
    const animation = createWindParticleAnimation({
      requestFrame,
      cancelFrame,
      onFrame,
    });
    const step = (timestamp: number) => {
      const callbacks = [...queued.values()];
      queued.clear();
      callbacks.forEach((callback) => callback(timestamp));
    };

    animation.start();
    animation.start();
    expect(queued.size).toBe(1);
    step(0);
    step(WIND_PARTICLE_FRAME_INTERVAL_MS - 1);
    expect(onFrame).not.toHaveBeenCalled();
    step(WIND_PARTICLE_FRAME_INTERVAL_MS + 1);
    expect(onFrame).toHaveBeenCalledTimes(1);

    step(500);
    expect(onFrame).toHaveBeenLastCalledWith(WIND_PARTICLE_MAX_DELTA_SECONDS, 500);
    animation.pause();
    expect(animation.isRunning()).toBe(false);
    expect(queued.size).toBe(0);
    animation.start();
    expect(animation.isRunning()).toBe(true);
    animation.dispose();
    expect(queued.size).toBe(0);
    expect(cancelFrame).toHaveBeenCalled();
  });

  it("기존 궤적을 감쇠하고 위험색이 아닌 중립색 두 겹 선분을 그린다", () => {
    const { context, strokes } = fakeCanvasContext();
    const particles: WindParticle[] = [{
      x: 20,
      y: 18,
      previousX: 15,
      previousY: 18,
      ageSeconds: 0.1,
      maxAgeSeconds: 2,
    }];
    drawWindParticleFrame(context, 100, 80, particles);
    expect(context.fillRect).toHaveBeenCalledWith(0, 0, 100, 80);
    expect(strokes.map((stroke) => stroke.style)).toEqual([
      WIND_PARTICLE_OUTLINE,
      WIND_PARTICLE_STROKE,
    ]);
    expect(strokes.join(" ")).not.toMatch(/#(?:dc2626|f97316|eab308)/i);
  });

  it("reduced-motion 정적 흐름선도 field 방향과 상대 풍속 길이를 보존한다", () => {
    const { context, strokes } = fakeCanvasContext();
    const east = { u: 10, v: 0, speed: 10, dx: 10, dy: 0 };
    const field: WindVectorField = {
      width: 100,
      height: 100,
      step: 100,
      columns: 2,
      rows: 2,
      sampleCount: 4,
      vectors: [east, east, east, east],
    };
    const particle: WindParticle = {
      x: 50,
      y: 50,
      previousX: 50,
      previousY: 50,
      ageSeconds: 0,
      maxAgeSeconds: 2,
    };
    drawStaticWindFlow(context, field, [particle]);
    expect(context.moveTo).toHaveBeenCalled();
    expect(context.lineTo).toHaveBeenCalled();
    const from = vi.mocked(context.moveTo).mock.calls[0];
    const to = vi.mocked(context.lineTo).mock.calls[0];
    expect(to[0]).toBeGreaterThan(from[0]);
    expect(to[1]).toBeCloseTo(from[1]);
    expect(strokes).toHaveLength(2);
  });
});
