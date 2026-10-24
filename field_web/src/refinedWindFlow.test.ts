import { describe, expect, it, vi } from "vitest";
import { drawRefinedWindFlow, refinedWindCount, refinedWindSpeed } from "./refinedWindFlow";
import { advanceWindParticleSystem, type WindVectorField, type WindParticle } from "./windParticleField";

function field(speed: number): WindVectorField {
  const vector = { u: speed, v: 0, dx: speed, dy: 0, speed };
  return { width: 200, height: 200, step: 200, columns: 2, rows: 2, sampleCount: 4, vectors: [vector, vector, vector, vector] };
}
const particle: WindParticle = { x: 100, y: 100, previousX: 100, previousY: 100, ageSeconds: 1, maxAgeSeconds: 5 };

describe("채택한 바람 A 표현", () => {
  it("약풍에서도 진행 방향으로 움직이며 원본 u/v와 풍속은 바꾸지 않는다", () => {
    const source = field(0.5), before = JSON.stringify(source);
    const next = advanceWindParticleSystem(source, { particles: [particle], randomState: 1 }, 0.1, refinedWindSpeed);
    expect(next.particles[0].x - particle.x).toBeGreaterThan(1);
    expect(next.particles[0].y).toBe(particle.y);
    expect(JSON.stringify(source)).toBe(before);
    expect(refinedWindSpeed(15)).toBeGreaterThan(refinedWindSpeed(0.5));
  });
  it("무풍에는 이동과 흐름선을 만들지 않고 화면 밖 대량 입자를 제한한다", () => {
    const source = field(0);
    const next = advanceWindParticleSystem(source, { particles: [particle], randomState: 1 }, 0.1, refinedWindSpeed);
    expect(next.particles[0].x).toBe(particle.x); expect(next.particles[0].y).toBe(particle.y);
    const context = { clearRect: vi.fn(), save: vi.fn(), restore: vi.fn(), stroke: vi.fn() } as unknown as CanvasRenderingContext2D;
    drawRefinedWindFlow(context, source, next.particles, true);
    expect(context.clearRect).toHaveBeenCalledOnce(); expect(context.stroke).not.toHaveBeenCalled();
    expect(refinedWindSpeed(Number.NaN)).toBe(0);
    expect(refinedWindCount(4000, 4000)).toBeLessThanOrEqual(600);
  });
  it("정적 표시에서도 실제 방향을 따라 꼬리를 그리며 움직임은 발생시키지 않는다", () => {
    const calls: number[][] = [];
    const context = { clearRect() {}, save() {}, restore() {}, beginPath() {}, lineTo() {}, stroke() {}, arc() {}, fill() {},
      moveTo: (x: number, y: number) => calls.push([x, y]),
      createLinearGradient: () => ({ addColorStop() {} }),
    } as unknown as CanvasRenderingContext2D;
    const before = JSON.stringify(particle);
    drawRefinedWindFlow(context, field(0.5), [particle], true);
    expect(calls[0][0]).toBeLessThan(particle.x); expect(calls[0][1]).toBe(particle.y);
    expect(JSON.stringify(particle)).toBe(before);
  });
});
