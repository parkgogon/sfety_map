import {
  sampleWindVectorField,
  screenWindVelocity,
  type WindParticle,
  type WindVectorField,
} from "./windParticleField";

export const WIND_PARTICLE_TARGET_FPS = 30;
export const WIND_PARTICLE_FRAME_INTERVAL_MS = 1_000 / WIND_PARTICLE_TARGET_FPS;
export const WIND_PARTICLE_MAX_DELTA_SECONDS = 0.1;
export const WIND_PARTICLE_MIN_COUNT = 120;
export const WIND_PARTICLE_MAX_COUNT = 600;
export const WIND_PARTICLE_AREA_PER_ITEM = 2_200;
export const WIND_PARTICLE_FADE_ALPHA = 0.9;
export const WIND_PARTICLE_OUTLINE = "rgba(75, 105, 121, .34)";
export const WIND_PARTICLE_STROKE = "rgba(224, 241, 247, .86)";

export interface WindParticleAnimationController {
  start: () => void;
  pause: () => void;
  dispose: () => void;
  isRunning: () => boolean;
}

interface WindParticleAnimationOptions {
  requestFrame: (callback: FrameRequestCallback) => number;
  cancelFrame: (frameId: number) => void;
  onFrame: (deltaSeconds: number, timestamp: number) => void;
}

export function calculateWindParticleCount(width: number, height: number): number {
  const safeArea = Math.max(0, width) * Math.max(0, height);
  return Math.min(
    WIND_PARTICLE_MAX_COUNT,
    Math.max(WIND_PARTICLE_MIN_COUNT, Math.round(safeArea / WIND_PARTICLE_AREA_PER_ITEM)),
  );
}

/** Canvas와 무관한 30fps lifecycle입니다. pause 이후 start하면 시간 기준을 새로 잡습니다. */
export function createWindParticleAnimation(
  options: WindParticleAnimationOptions,
): WindParticleAnimationController {
  let running = false;
  let frameId: number | null = null;
  let lastFrameTimestamp: number | null = null;

  const schedule = () => {
    if (!running || frameId !== null) return;
    frameId = options.requestFrame(tick);
  };
  const tick = (timestamp: number) => {
    frameId = null;
    if (!running) return;
    if (lastFrameTimestamp === null) {
      lastFrameTimestamp = timestamp;
    } else {
      const elapsed = timestamp - lastFrameTimestamp;
      if (elapsed >= WIND_PARTICLE_FRAME_INTERVAL_MS) {
        const deltaSeconds = Math.min(
          WIND_PARTICLE_MAX_DELTA_SECONDS,
          Math.max(0, elapsed / 1_000),
        );
        lastFrameTimestamp = timestamp;
        options.onFrame(deltaSeconds, timestamp);
      }
    }
    schedule();
  };
  const pause = () => {
    running = false;
    lastFrameTimestamp = null;
    if (frameId !== null) {
      options.cancelFrame(frameId);
      frameId = null;
    }
  };

  return {
    start() {
      if (running) return;
      running = true;
      lastFrameTimestamp = null;
      schedule();
    },
    pause,
    dispose: pause,
    isRunning: () => running,
  };
}

function strokeSegments(
  context: CanvasRenderingContext2D,
  segments: Array<{ fromX: number; fromY: number; toX: number; toY: number }>,
): void {
  if (!segments.length) return;
  context.save();
  context.lineCap = "round";
  context.lineJoin = "round";
  context.beginPath();
  segments.forEach((segment) => {
    context.moveTo(segment.fromX, segment.fromY);
    context.lineTo(segment.toX, segment.toY);
  });
  context.strokeStyle = WIND_PARTICLE_OUTLINE;
  context.lineWidth = 2.8;
  context.stroke();
  context.strokeStyle = WIND_PARTICLE_STROKE;
  context.lineWidth = 1.25;
  context.stroke();
  context.restore();
}

/** 이전 프레임을 투명하게 감쇠시킨 뒤 현재 파티클의 짧은 이동 선분을 누적합니다. */
export function drawWindParticleFrame(
  context: CanvasRenderingContext2D,
  width: number,
  height: number,
  particles: WindParticle[],
): void {
  context.save();
  context.globalCompositeOperation = "destination-in";
  context.fillStyle = `rgba(0, 0, 0, ${WIND_PARTICLE_FADE_ALPHA})`;
  context.fillRect(0, 0, width, height);
  context.restore();

  strokeSegments(
    context,
    particles
      .filter((particle) =>
        Math.hypot(
          particle.x - particle.previousX,
          particle.y - particle.previousY,
        ) >= 0.05)
      .map((particle) => ({
        fromX: particle.previousX,
        fromY: particle.previousY,
        toX: particle.x,
        toY: particle.y,
      })),
  );
}

/** reduced-motion에서도 풍향 정보를 남기는 중립색의 짧은 정적 흐름선입니다. */
export function drawStaticWindFlow(
  context: CanvasRenderingContext2D,
  field: WindVectorField,
  particles: WindParticle[],
): void {
  const segments = particles.flatMap((particle) => {
    const vector = sampleWindVectorField(field, particle.x, particle.y);
    if (!vector || vector.speed < 0.0001) return [];
    const velocity = screenWindVelocity(vector);
    const magnitude = Math.hypot(velocity.x, velocity.y);
    if (magnitude < 0.0001) return [];
    const length = Math.min(18, Math.max(5, velocity.speed * 0.45));
    const unitX = velocity.x / magnitude;
    const unitY = velocity.y / magnitude;
    return [{
      fromX: particle.x - unitX * length * 0.5,
      fromY: particle.y - unitY * length * 0.5,
      toX: particle.x + unitX * length * 0.5,
      toY: particle.y + unitY * length * 0.5,
    }];
  });
  strokeSegments(context, segments);
}
