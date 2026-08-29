import {
  scalarNeighborSpacing,
  type ScreenWeatherPoint,
} from "./weatherLayerRendering";

export const WIND_FIELD_BASE_STEP = 12;
export const WIND_FIELD_MAX_SAMPLES = 40_000;
export const WIND_FIELD_NEIGHBOR_LIMIT = 4;
export const WIND_FIELD_COVERAGE_RATIO = 1.75;
export const WIND_PARTICLE_MIN_SPEED = 2;
export const WIND_PARTICLE_MAX_SPEED = 38;
export const WIND_PARTICLE_SPEED_SCALE = 1.8;
export const WIND_PARTICLE_MIN_LIFETIME_SECONDS = 1.2;
export const WIND_PARTICLE_MAX_LIFETIME_SECONDS = 4.8;
export const WIND_PARTICLE_SPAWN_ATTEMPTS = 64;

interface WindPoint extends ScreenWeatherPoint {
  u: number;
  v: number;
}

interface WindSpatialIndex {
  bucketSize: number;
  buckets: Map<string, WindPoint[]>;
}

export interface WindComponents {
  u: number;
  v: number;
}

export interface WindVector extends WindComponents {
  speed: number;
  dx: number;
  dy: number;
}

export interface ScreenWindVelocity {
  x: number;
  y: number;
  speed: number;
}

export interface WindFieldLayout {
  width: number;
  height: number;
  step: number;
  columns: number;
  rows: number;
  sampleCount: number;
}

export interface WindVectorField extends WindFieldLayout {
  vectors: Array<WindVector | null>;
}

export interface WindParticle {
  x: number;
  y: number;
  previousX: number;
  previousY: number;
  ageSeconds: number;
  maxAgeSeconds: number;
}

export interface WindParticleSystemState {
  particles: WindParticle[];
  randomState: number;
}

interface ParticleSpawnResult {
  particle: WindParticle;
  randomState: number;
}

function windVector(u: number, v: number): WindVector {
  return {
    u,
    v,
    speed: Math.hypot(u, v),
    dx: u,
    dy: -v,
  };
}

/**
 * KMA의 동쪽 성분 u, 북쪽 성분 v를 우선 사용합니다. 두 성분이 모두 없는
 * 호환 입력에 한해서만 북쪽 0°, 시계방향의 진행 방향과 풍속을 복원합니다.
 */
export function windComponentsFromPoint(
  point: ScreenWeatherPoint,
): WindComponents | null {
  const { u_ms: u, v_ms: v } = point.source;
  if (Number.isFinite(u) && Number.isFinite(v)) {
    return { u: u as number, v: v as number };
  }
  const uMissing = u === undefined || u === null;
  const vMissing = v === undefined || v === null;
  if (!uMissing || !vMissing) return null;

  const speed = point.source.speed_ms;
  const direction = point.source.direction_to_deg;
  if (
    !Number.isFinite(speed) ||
    !Number.isFinite(direction) ||
    (speed as number) < 0
  ) {
    return null;
  }
  const radians = (((direction as number) % 360) * Math.PI) / 180;
  return {
    u: (speed as number) * Math.sin(radians),
    v: (speed as number) * Math.cos(radians),
  };
}

function validWindPoints(points: ScreenWeatherPoint[]): WindPoint[] {
  return points.flatMap((point) => {
    const components = windComponentsFromPoint(point);
    if (!components) return [];
    return [{ ...point, ...components }];
  });
}

function compareCandidates(
  left: { point: WindPoint; distance: number },
  right: { point: WindPoint; distance: number },
): number {
  if (left.distance !== right.distance) return left.distance - right.distance;
  if (left.point.source.grid_x !== right.point.source.grid_x) {
    return left.point.source.grid_x - right.point.source.grid_x;
  }
  return left.point.source.grid_y - right.point.source.grid_y;
}

function interpolateWindCandidates(
  candidates: WindPoint[],
  x: number,
  y: number,
  spacing: number,
): WindVector | null {
  const maximumDistance = Math.max(1, spacing) * WIND_FIELD_COVERAGE_RATIO;
  const nearest = candidates
    .map((point) => ({ point, distance: Math.hypot(point.x - x, point.y - y) }))
    .filter(({ distance }) => distance <= maximumDistance)
    .sort(compareCandidates)
    .slice(0, WIND_FIELD_NEIGHBOR_LIMIT);
  if (!nearest.length) return null;
  if (nearest[0].distance < 0.001) {
    return windVector(nearest[0].point.u, nearest[0].point.v);
  }

  let weightedU = 0;
  let weightedV = 0;
  let totalWeight = 0;
  nearest.forEach(({ point, distance }) => {
    const weight = 1 / (distance * distance + 1);
    weightedU += point.u * weight;
    weightedV += point.v * weight;
    totalWeight += weight;
  });
  return totalWeight > 0
    ? windVector(weightedU / totalWeight, weightedV / totalWeight)
    : null;
}

export function interpolateWindAt(
  points: ScreenWeatherPoint[],
  x: number,
  y: number,
  spacing = scalarNeighborSpacing(points),
): WindVector | null {
  return interpolateWindCandidates(validWindPoints(points), x, y, spacing);
}

function buildWindSpatialIndex(points: WindPoint[], spacing: number): WindSpatialIndex {
  const bucketSize = Math.max(
    WIND_FIELD_BASE_STEP,
    spacing * WIND_FIELD_COVERAGE_RATIO,
  );
  const buckets = new Map<string, WindPoint[]>();
  points.forEach((point) => {
    const key = `${Math.floor(point.x / bucketSize)}:${Math.floor(point.y / bucketSize)}`;
    const bucket = buckets.get(key);
    if (bucket) bucket.push(point);
    else buckets.set(key, [point]);
  });
  return { bucketSize, buckets };
}

function windCandidatesNear(
  index: WindSpatialIndex,
  x: number,
  y: number,
): WindPoint[] {
  const centerX = Math.floor(x / index.bucketSize);
  const centerY = Math.floor(y / index.bucketSize);
  const result: WindPoint[] = [];
  for (let offsetY = -1; offsetY <= 1; offsetY += 1) {
    for (let offsetX = -1; offsetX <= 1; offsetX += 1) {
      const bucket = index.buckets.get(`${centerX + offsetX}:${centerY + offsetY}`);
      if (bucket) result.push(...bucket);
    }
  }
  return result;
}

export function calculateWindFieldLayout(
  width: number,
  height: number,
): WindFieldLayout | null {
  if (!Number.isFinite(width) || !Number.isFinite(height) || width <= 0 || height <= 0) {
    return null;
  }
  const safeWidth = Math.max(1, Math.ceil(width));
  const safeHeight = Math.max(1, Math.ceil(height));
  let step = WIND_FIELD_BASE_STEP;
  let columns = Math.ceil(safeWidth / step) + 1;
  let rows = Math.ceil(safeHeight / step) + 1;
  while (columns * rows > WIND_FIELD_MAX_SAMPLES) {
    step += 1;
    columns = Math.ceil(safeWidth / step) + 1;
    rows = Math.ceil(safeHeight / step) + 1;
  }
  return {
    width: safeWidth,
    height: safeHeight,
    step,
    columns,
    rows,
    sampleCount: columns * rows,
  };
}

export function buildWindVectorField(
  points: ScreenWeatherPoint[],
  width: number,
  height: number,
): WindVectorField | null {
  const layout = calculateWindFieldLayout(width, height);
  const validPoints = validWindPoints(points);
  if (!layout || !validPoints.length) return null;
  const spacing = scalarNeighborSpacing(validPoints);
  const index = buildWindSpatialIndex(validPoints, spacing);
  const vectors: Array<WindVector | null> = [];

  for (let row = 0; row < layout.rows; row += 1) {
    const y = Math.min(layout.height, row * layout.step);
    for (let column = 0; column < layout.columns; column += 1) {
      const x = Math.min(layout.width, column * layout.step);
      vectors.push(
        interpolateWindCandidates(
          windCandidatesNear(index, x, y),
          x,
          y,
          spacing,
        ),
      );
    }
  }

  return { ...layout, vectors };
}

function fieldVector(field: WindVectorField, column: number, row: number) {
  return field.vectors[row * field.columns + column] ?? null;
}

/** 유효한 네 모서리의 bilinear weight를 정규화해 저해상도 vector field를 읽습니다. */
export function sampleWindVectorField(
  field: WindVectorField,
  x: number,
  y: number,
): WindVector | null {
  if (
    !Number.isFinite(x) ||
    !Number.isFinite(y) ||
    x < 0 ||
    y < 0 ||
    x > field.width ||
    y > field.height ||
    field.columns < 2 ||
    field.rows < 2
  ) {
    return null;
  }

  const column = Math.min(field.columns - 2, Math.floor(x / field.step));
  const row = Math.min(field.rows - 2, Math.floor(y / field.step));
  const x0 = column * field.step;
  const y0 = row * field.step;
  const x1 = Math.min(field.width, (column + 1) * field.step);
  const y1 = Math.min(field.height, (row + 1) * field.step);
  const ratioX = x1 > x0 ? (x - x0) / (x1 - x0) : 0;
  const ratioY = y1 > y0 ? (y - y0) / (y1 - y0) : 0;
  const corners = [
    { vector: fieldVector(field, column, row), weight: (1 - ratioX) * (1 - ratioY) },
    { vector: fieldVector(field, column + 1, row), weight: ratioX * (1 - ratioY) },
    { vector: fieldVector(field, column, row + 1), weight: (1 - ratioX) * ratioY },
    { vector: fieldVector(field, column + 1, row + 1), weight: ratioX * ratioY },
  ];
  let weightedU = 0;
  let weightedV = 0;
  let totalWeight = 0;
  corners.forEach(({ vector, weight }) => {
    if (!vector || weight <= 0) return;
    weightedU += vector.u * weight;
    weightedV += vector.v * weight;
    totalWeight += weight;
  });
  return totalWeight > 0
    ? windVector(weightedU / totalWeight, weightedV / totalWeight)
    : null;
}

export function windParticleSpeed(speed: number): number {
  const finiteSpeed = Number.isFinite(speed) ? Math.max(0, speed) : 0;
  return Math.min(
    WIND_PARTICLE_MAX_SPEED,
    Math.max(WIND_PARTICLE_MIN_SPEED, finiteSpeed * WIND_PARTICLE_SPEED_SCALE),
  );
}

export function screenWindVelocity(vector: WindVector): ScreenWindVelocity {
  const visualSpeed = windParticleSpeed(vector.speed);
  if (vector.speed < 0.0001) return { x: 0, y: 0, speed: visualSpeed };
  return {
    x: (vector.dx / vector.speed) * visualSpeed,
    y: (vector.dy / vector.speed) * visualSpeed,
    speed: visualSpeed,
  };
}

export function nextSeededRandom(randomState: number): {
  value: number;
  randomState: number;
} {
  const nextState = (Math.imul(randomState >>> 0, 1_664_525) + 1_013_904_223) >>> 0;
  return { value: nextState / 4_294_967_296, randomState: nextState };
}

function spawnWindParticle(
  field: WindVectorField,
  initialRandomState: number,
): ParticleSpawnResult | null {
  let randomState = initialRandomState >>> 0;
  let x = 0;
  let y = 0;
  let found = false;

  for (let attempt = 0; attempt < WIND_PARTICLE_SPAWN_ATTEMPTS; attempt += 1) {
    const randomX = nextSeededRandom(randomState);
    const randomY = nextSeededRandom(randomX.randomState);
    randomState = randomY.randomState;
    x = randomX.value * field.width;
    y = randomY.value * field.height;
    if (sampleWindVectorField(field, x, y)) {
      found = true;
      break;
    }
  }

  if (!found) {
    const index = field.vectors.findIndex((vector) => vector !== null);
    if (index < 0) return null;
    const column = index % field.columns;
    const row = Math.floor(index / field.columns);
    x = Math.min(field.width, column * field.step);
    y = Math.min(field.height, row * field.step);
  }

  const lifetimeRandom = nextSeededRandom(randomState);
  const maxAgeSeconds = WIND_PARTICLE_MIN_LIFETIME_SECONDS +
    lifetimeRandom.value *
      (WIND_PARTICLE_MAX_LIFETIME_SECONDS - WIND_PARTICLE_MIN_LIFETIME_SECONDS);
  return {
    particle: {
      x,
      y,
      previousX: x,
      previousY: y,
      ageSeconds: 0,
      maxAgeSeconds,
    },
    randomState: lifetimeRandom.randomState,
  };
}

export function initializeWindParticleSystem(
  field: WindVectorField,
  particleCount: number,
  seed: number,
): WindParticleSystemState {
  let randomState = seed >>> 0;
  const particles: WindParticle[] = [];
  const safeCount = Math.max(0, Math.floor(particleCount));
  for (let index = 0; index < safeCount; index += 1) {
    const spawned = spawnWindParticle(field, randomState);
    if (!spawned) break;
    particles.push(spawned.particle);
    randomState = spawned.randomState;
  }
  return { particles, randomState };
}

function advanceWindParticle(
  field: WindVectorField,
  particle: WindParticle,
  deltaSeconds: number,
  randomState: number,
): ParticleSpawnResult | null {
  if (
    particle.ageSeconds >= particle.maxAgeSeconds ||
    particle.x < 0 ||
    particle.y < 0 ||
    particle.x > field.width ||
    particle.y > field.height
  ) {
    return spawnWindParticle(field, randomState);
  }
  const vector = sampleWindVectorField(field, particle.x, particle.y);
  if (!vector) return spawnWindParticle(field, randomState);
  const velocity = screenWindVelocity(vector);
  const nextX = particle.x + velocity.x * deltaSeconds;
  const nextY = particle.y + velocity.y * deltaSeconds;
  const nextAge = particle.ageSeconds + deltaSeconds;
  if (
    nextAge >= particle.maxAgeSeconds ||
    nextX < 0 ||
    nextY < 0 ||
    nextX > field.width ||
    nextY > field.height ||
    !sampleWindVectorField(field, nextX, nextY)
  ) {
    return spawnWindParticle(field, randomState);
  }
  return {
    particle: {
      x: nextX,
      y: nextY,
      previousX: particle.x,
      previousY: particle.y,
      ageSeconds: nextAge,
      maxAgeSeconds: particle.maxAgeSeconds,
    },
    randomState,
  };
}

export function advanceWindParticleSystem(
  field: WindVectorField,
  state: WindParticleSystemState,
  deltaSeconds: number,
): WindParticleSystemState {
  const safeDelta = Number.isFinite(deltaSeconds) ? Math.max(0, deltaSeconds) : 0;
  let randomState = state.randomState;
  const particles: WindParticle[] = [];
  state.particles.forEach((particle) => {
    const advanced = advanceWindParticle(
      field,
      particle,
      safeDelta,
      randomState,
    );
    if (!advanced) return;
    particles.push(advanced.particle);
    randomState = advanced.randomState;
  });
  return { particles, randomState };
}
