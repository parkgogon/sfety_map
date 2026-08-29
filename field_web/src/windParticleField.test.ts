import { describe, expect, it } from "vitest";
import type { ScreenWeatherPoint } from "./weatherLayerRendering";
import {
  advanceWindParticleSystem,
  buildWindVectorField,
  calculateWindFieldLayout,
  initializeWindParticleSystem,
  interpolateWindAt,
  sampleWindVectorField,
  screenWindVelocity,
  windComponentsFromPoint,
  windParticleSpeed,
  WIND_FIELD_BASE_STEP,
  WIND_FIELD_MAX_SAMPLES,
  WIND_PARTICLE_MAX_SPEED,
  WIND_PARTICLE_MIN_SPEED,
  type WindParticle,
  type WindVector,
  type WindVectorField,
} from "./windParticleField";

interface PointWind {
  u_ms?: number;
  v_ms?: number;
  speed_ms?: number;
  direction_to_deg?: number;
}

function point(
  x: number,
  y: number,
  gridX: number,
  gridY: number,
  wind: PointWind,
): ScreenWeatherPoint {
  return {
    x,
    y,
    source: {
      grid_x: gridX,
      grid_y: gridY,
      latitude: 36 + gridY * 0.01,
      longitude: 128 + gridX * 0.01,
      ...wind,
    },
  };
}

function vector(u: number, v: number): WindVector {
  return { u, v, speed: Math.hypot(u, v), dx: u, dy: -v };
}

function uniformField(u = 10, v = 0): WindVectorField {
  const fieldVector = vector(u, v);
  return {
    width: 200,
    height: 200,
    step: 100,
    columns: 3,
    rows: 3,
    sampleCount: 9,
    vectors: Array.from({ length: 9 }, () => fieldVector),
  };
}

describe("windParticleField", () => {
  it("u/v를 우선하고 두 성분이 모두 없는 호환 입력만 풍속·방향으로 복원한다", () => {
    expect(
      windComponentsFromPoint(point(0, 0, 0, 0, {
        u_ms: 3,
        v_ms: 4,
        speed_ms: 100,
        direction_to_deg: 180,
      })),
    ).toEqual({ u: 3, v: 4 });

    const fallback = windComponentsFromPoint(
      point(0, 0, 0, 0, { speed_ms: 10, direction_to_deg: 90 }),
    );
    expect(fallback?.u).toBeCloseTo(10);
    expect(fallback?.v).toBeCloseTo(0);

    expect(
      windComponentsFromPoint(point(0, 0, 0, 0, {
        u_ms: Number.NaN,
        speed_ms: 10,
        direction_to_deg: 90,
      })),
    ).toBeNull();
    expect(
      windComponentsFromPoint(point(0, 0, 0, 0, {
        speed_ms: -1,
        direction_to_deg: 90,
      })),
    ).toBeNull();
  });

  it("동·서·남·북과 대각선 u/v를 올바른 화면 이동 방향으로 변환한다", () => {
    const east = screenWindVelocity(vector(10, 0));
    const west = screenWindVelocity(vector(-10, 0));
    const north = screenWindVelocity(vector(0, 10));
    const south = screenWindVelocity(vector(0, -10));
    const southeast = screenWindVelocity(vector(10, -10));

    expect(east.x).toBeGreaterThan(0);
    expect(east.y).toBeCloseTo(0);
    expect(west.x).toBeLessThan(0);
    expect(north.y).toBeLessThan(0);
    expect(south.y).toBeGreaterThan(0);
    expect(southeast.x).toBeGreaterThan(0);
    expect(southeast.y).toBeGreaterThan(0);
  });

  it("풍속의 상대 크기를 유지하면서 시각 이동 속도를 2~38px/s로 제한한다", () => {
    expect(windParticleSpeed(0)).toBe(WIND_PARTICLE_MIN_SPEED);
    expect(windParticleSpeed(2)).toBeCloseTo(3.6);
    expect(windParticleSpeed(10)).toBeCloseTo(18);
    expect(windParticleSpeed(100)).toBe(WIND_PARTICLE_MAX_SPEED);
    expect(windParticleSpeed(Number.NaN)).toBe(WIND_PARTICLE_MIN_SPEED);
  });

  it("가까운 점 최대 4개의 u/v를 IDW 보간하고 관측 범위 밖은 제외한다", () => {
    const points = [
      point(0, 5, 0, 0, { u_ms: 4, v_ms: 0 }),
      point(10, 5, 0, 1, { u_ms: 8, v_ms: 0 }),
      point(5, 0, 1, 0, { u_ms: 12, v_ms: 0 }),
      point(5, 10, 1, 1, { u_ms: 16, v_ms: 0 }),
      point(0, 5, 2, 2, { u_ms: 1_000, v_ms: 0 }),
    ];
    const center = interpolateWindAt(points, 5, 5, 10);
    expect(center?.u).toBeCloseTo(10);
    expect(center?.v).toBeCloseTo(0);
    expect(interpolateWindAt([points[0]], 18, 0, 10)).toBeNull();
  });

  it("359°와 1° 입력도 각도가 아닌 u/v로 보간해 북향을 유지한다", () => {
    const points = [
      point(0, 0, 0, 0, { speed_ms: 10, direction_to_deg: 359 }),
      point(10, 0, 1, 0, { speed_ms: 10, direction_to_deg: 1 }),
    ];
    const interpolated = interpolateWindAt(points, 5, 0, 10);
    expect(interpolated?.u).toBeCloseTo(0, 5);
    expect(interpolated?.v).toBeGreaterThan(9.9);
    expect(interpolated?.dy).toBeLessThan(0);
  });

  it("12px field를 기본으로 사용하고 큰 화면에서도 sample 40,000개를 넘지 않는다", () => {
    const ordinary = calculateWindFieldLayout(800, 600);
    expect(ordinary?.step).toBe(WIND_FIELD_BASE_STEP);
    expect(ordinary?.sampleCount).toBeLessThanOrEqual(WIND_FIELD_MAX_SAMPLES);

    const huge = calculateWindFieldLayout(10_000, 10_000);
    expect(huge?.step).toBeGreaterThan(WIND_FIELD_BASE_STEP);
    expect(huge?.sampleCount).toBeLessThanOrEqual(WIND_FIELD_MAX_SAMPLES);
    expect(calculateWindFieldLayout(0, 600)).toBeNull();
  });

  it("field가 화면 끝까지 포함되고 네 모서리 vector를 bilinear sampling한다", () => {
    const field = buildWindVectorField([
      point(0, 0, 0, 0, { u_ms: 0, v_ms: 0 }),
      point(12, 0, 1, 0, { u_ms: 12, v_ms: 0 }),
      point(0, 12, 0, 1, { u_ms: 0, v_ms: 12 }),
      point(12, 12, 1, 1, { u_ms: 12, v_ms: 12 }),
    ], 12, 12);
    expect(field).not.toBeNull();
    expect(field?.columns).toBe(2);
    expect(field?.rows).toBe(2);
    const center = sampleWindVectorField(field as WindVectorField, 6, 6);
    expect(center?.u).toBeCloseTo(6);
    expect(center?.v).toBeCloseTo(6);
    expect(center?.dx).toBeCloseTo(6);
    expect(center?.dy).toBeCloseTo(-6);
    expect(sampleWindVectorField(field as WindVectorField, 12, 12)).not.toBeNull();
  });

  it("관측점 coverage 밖의 field sample은 null로 남긴다", () => {
    const field = buildWindVectorField([
      point(0, 0, 0, 0, { u_ms: 5, v_ms: 5 }),
    ], 120, 120);
    expect(field?.vectors[0]).not.toBeNull();
    expect(field?.vectors.at(-1)).toBeNull();
    expect(sampleWindVectorField(field as WindVectorField, 120, 120)).toBeNull();
  });

  it("같은 seed·field·시간 간격이면 같은 파티클 상태를 만든다", () => {
    const field = uniformField();
    const firstInitial = initializeWindParticleSystem(field, 24, 20260830);
    const secondInitial = initializeWindParticleSystem(field, 24, 20260830);
    expect(firstInitial).toEqual(secondInitial);

    const firstAdvanced = advanceWindParticleSystem(field, firstInitial, 0.25);
    const secondAdvanced = advanceWindParticleSystem(field, secondInitial, 0.25);
    expect(firstAdvanced).toEqual(secondAdvanced);
    expect(firstAdvanced.particles).toHaveLength(24);
  });

  it("파티클 이동 시 현재 위치를 이전점으로 남기고 화면 풍향·속도를 적용한다", () => {
    const field = uniformField(10, 0);
    const particle: WindParticle = {
      x: 100,
      y: 100,
      previousX: 100,
      previousY: 100,
      ageSeconds: 0,
      maxAgeSeconds: 3,
    };
    const advanced = advanceWindParticleSystem(
      field,
      { particles: [particle], randomState: 5 },
      0.5,
    ).particles[0];
    expect(advanced.previousX).toBe(100);
    expect(advanced.previousY).toBe(100);
    expect(advanced.x).toBeCloseTo(109);
    expect(advanced.y).toBeCloseTo(100);
    expect(advanced.ageSeconds).toBeCloseTo(0.5);
  });

  it("수명 만료·buffer 이탈·유효 field 이탈 파티클을 유효 영역에 재생성한다", () => {
    const field = uniformField();
    const initial = initializeWindParticleSystem(field, 1, 7);
    const base = initial.particles[0];
    const expired: WindParticle = {
      ...base,
      ageSeconds: base.maxAgeSeconds,
    };
    const outside: WindParticle = { ...base, x: -1 };
    const respawned = advanceWindParticleSystem(
      field,
      { particles: [expired, outside], randomState: initial.randomState },
      0.1,
    );
    expect(respawned.particles).toHaveLength(2);
    respawned.particles.forEach((particle) => {
      expect(particle.ageSeconds).toBe(0);
      expect(sampleWindVectorField(field, particle.x, particle.y)).not.toBeNull();
    });

    const partlyValidField: WindVectorField = {
      width: 100,
      height: 100,
      step: 50,
      columns: 3,
      rows: 3,
      sampleCount: 9,
      vectors: [vector(5, 0), vector(5, 0), null, vector(5, 0), null, null, null, null, null],
    };
    const invalidParticle: WindParticle = {
      x: 100,
      y: 100,
      previousX: 100,
      previousY: 100,
      ageSeconds: 0,
      maxAgeSeconds: 3,
    };
    expect(sampleWindVectorField(partlyValidField, 100, 100)).toBeNull();
    const recovered = advanceWindParticleSystem(
      partlyValidField,
      { particles: [invalidParticle], randomState: 11 },
      0.1,
    );
    expect(recovered.particles).toHaveLength(1);
    expect(
      sampleWindVectorField(
        partlyValidField,
        recovered.particles[0].x,
        recovered.particles[0].y,
      ),
    ).not.toBeNull();
  });
});
