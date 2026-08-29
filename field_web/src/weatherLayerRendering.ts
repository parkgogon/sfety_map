import type {
  WeatherLayerKind,
  WeatherLayerPoint,
} from "./types";
import { weatherColorChannels } from "./utils";

export interface ScreenWeatherPoint {
  source: WeatherLayerPoint;
  x: number;
  y: number;
}

type ScalarLayerKind = Exclude<WeatherLayerKind, "wind">;

interface ScalarPointWithValue extends ScreenWeatherPoint {
  value: number;
}

interface ScalarSpatialIndex {
  bucketSize: number;
  buckets: Map<string, ScalarPointWithValue[]>;
}

export interface ScalarInterpolation {
  value: number;
  coverage: number;
  nearestDistance: number;
}

export interface ScalarRaster {
  width: number;
  height: number;
  step: number;
  pixels: Uint8ClampedArray;
}

export const MIN_SCALAR_RASTER_STEP = 4;
export const MAX_SCALAR_RASTER_SAMPLES = 120_000;
const SCALAR_FULL_COVERAGE_RATIO = 0.9;
const SCALAR_EDGE_COVERAGE_RATIO = 1.75;
const SCALAR_NEIGHBOR_LIMIT = 4;

export function median(values: number[]): number {
  if (!values.length) return 12;
  const ordered = [...values].sort((left, right) => left - right);
  return ordered[Math.floor(ordered.length / 2)];
}

export function scalarNeighborSpacing(points: ScreenWeatherPoint[]): number {
  const byGrid = new Map(
    points.map((point) => [`${point.source.grid_x}:${point.source.grid_y}`, point]),
  );
  const distances: number[] = [];
  for (const point of points) {
    const neighbor =
      byGrid.get(`${point.source.grid_x + 1}:${point.source.grid_y}`) ??
      byGrid.get(`${point.source.grid_x}:${point.source.grid_y + 1}`);
    if (!neighbor) continue;
    distances.push(Math.hypot(point.x - neighbor.x, point.y - neighbor.y));
  }
  return Math.max(1, median(distances));
}

/**
 * 레이어 종류별 화면 전체 합성 불투명도(alpha)를 반환합니다.
 * - 기온: 0.24
 * - 강수: 0.28
 */
export function scalarLayerAlpha(layer: ScalarLayerKind): number {
  if (layer === "temperature") return 0.24;
  return 0.28;
}

/** 보간 입력에서 무효값과 음수 강수를 제외합니다. 0은 경계 보간에 사용합니다. */
export function shouldSkipScalarPoint(
  kind: ScalarLayerKind,
  value: number | undefined,
): boolean {
  if (value === undefined || !Number.isFinite(value)) return true;
  if (kind === "rainfall" && value < 0) return true;
  return false;
}

function scalarPointsWithValues(
  points: ScreenWeatherPoint[],
  kind: ScalarLayerKind,
): ScalarPointWithValue[] {
  return points.flatMap((point) => {
    const value = point.source.value;
    if (shouldSkipScalarPoint(kind, value)) return [];
    return [{ ...point, value: value as number }];
  });
}

export function calculateScalarRasterStep(width: number, height: number): number {
  const safeWidth = Math.max(1, Math.ceil(width));
  const safeHeight = Math.max(1, Math.ceil(height));
  let step = Math.max(
    MIN_SCALAR_RASTER_STEP,
    Math.ceil(Math.sqrt((safeWidth * safeHeight) / MAX_SCALAR_RASTER_SAMPLES)),
  );
  while (Math.ceil(safeWidth / step) * Math.ceil(safeHeight / step) > MAX_SCALAR_RASTER_SAMPLES) {
    step += 1;
  }
  return step;
}

export function scalarCoverage(nearestDistance: number, spacing: number): number {
  if (!Number.isFinite(nearestDistance)) return 0;
  const safeSpacing = Math.max(1, spacing);
  const fullDistance = safeSpacing * SCALAR_FULL_COVERAGE_RATIO;
  const edgeDistance = safeSpacing * SCALAR_EDGE_COVERAGE_RATIO;
  if (nearestDistance <= fullDistance) return 1;
  if (nearestDistance >= edgeDistance) return 0;
  const ratio = (nearestDistance - fullDistance) / (edgeDistance - fullDistance);
  const smooth = ratio * ratio * (3 - 2 * ratio);
  return 1 - smooth;
}

function compareScalarCandidates(
  left: { point: ScalarPointWithValue; distance: number },
  right: { point: ScalarPointWithValue; distance: number },
): number {
  if (left.distance !== right.distance) return left.distance - right.distance;
  if (left.point.source.grid_x !== right.point.source.grid_x) {
    return left.point.source.grid_x - right.point.source.grid_x;
  }
  return left.point.source.grid_y - right.point.source.grid_y;
}

function interpolateScalarCandidates(
  candidates: ScalarPointWithValue[],
  x: number,
  y: number,
  spacing: number,
): ScalarInterpolation | null {
  const edgeDistance = Math.max(1, spacing) * SCALAR_EDGE_COVERAGE_RATIO;
  const nearest = candidates
    .map((point) => ({ point, distance: Math.hypot(point.x - x, point.y - y) }))
    .filter((candidate) => candidate.distance <= edgeDistance)
    .sort(compareScalarCandidates)
    .slice(0, SCALAR_NEIGHBOR_LIMIT);
  if (!nearest.length) return null;
  if (nearest[0].distance < 0.001) {
    return { value: nearest[0].point.value, coverage: 1, nearestDistance: 0 };
  }

  let weightedValue = 0;
  let totalWeight = 0;
  nearest.forEach(({ point, distance }) => {
    const weight = 1 / (distance * distance + 1);
    weightedValue += point.value * weight;
    totalWeight += weight;
  });
  const nearestDistance = nearest[0].distance;
  return {
    value: weightedValue / totalWeight,
    coverage: scalarCoverage(nearestDistance, spacing),
    nearestDistance,
  };
}

export function interpolateScalarAt(
  points: ScreenWeatherPoint[],
  kind: ScalarLayerKind,
  x: number,
  y: number,
  spacing = scalarNeighborSpacing(points),
): ScalarInterpolation | null {
  return interpolateScalarCandidates(scalarPointsWithValues(points, kind), x, y, spacing);
}

function buildScalarSpatialIndex(
  points: ScalarPointWithValue[],
  spacing: number,
): ScalarSpatialIndex {
  const bucketSize = Math.max(MIN_SCALAR_RASTER_STEP, spacing * SCALAR_EDGE_COVERAGE_RATIO);
  const buckets = new Map<string, ScalarPointWithValue[]>();
  points.forEach((point) => {
    const key = `${Math.floor(point.x / bucketSize)}:${Math.floor(point.y / bucketSize)}`;
    const bucket = buckets.get(key);
    if (bucket) bucket.push(point);
    else buckets.set(key, [point]);
  });
  return { bucketSize, buckets };
}

function scalarCandidatesNear(
  index: ScalarSpatialIndex,
  x: number,
  y: number,
): ScalarPointWithValue[] {
  const centerX = Math.floor(x / index.bucketSize);
  const centerY = Math.floor(y / index.bucketSize);
  const result: ScalarPointWithValue[] = [];
  for (let offsetY = -1; offsetY <= 1; offsetY += 1) {
    for (let offsetX = -1; offsetX <= 1; offsetX += 1) {
      const bucket = index.buckets.get(`${centerX + offsetX}:${centerY + offsetY}`);
      if (bucket) result.push(...bucket);
    }
  }
  return result;
}

export function buildScalarRaster(
  points: ScreenWeatherPoint[],
  kind: ScalarLayerKind,
  width: number,
  height: number,
): ScalarRaster | null {
  const validPoints = scalarPointsWithValues(points, kind);
  if (!validPoints.length || width <= 0 || height <= 0) return null;
  const spacing = scalarNeighborSpacing(points);
  const index = buildScalarSpatialIndex(validPoints, spacing);
  const step = calculateScalarRasterStep(width, height);
  const rasterWidth = Math.max(1, Math.ceil(width / step));
  const rasterHeight = Math.max(1, Math.ceil(height / step));
  const pixels = new Uint8ClampedArray(rasterWidth * rasterHeight * 4);

  for (let row = 0; row < rasterHeight; row += 1) {
    const sampleY = Math.min(height, (row + 0.5) * step);
    for (let column = 0; column < rasterWidth; column += 1) {
      const sampleX = Math.min(width, (column + 0.5) * step);
      const interpolation = interpolateScalarCandidates(
        scalarCandidatesNear(index, sampleX, sampleY),
        sampleX,
        sampleY,
        spacing,
      );
      if (!interpolation || interpolation.coverage <= 0) continue;
      if (kind === "rainfall" && interpolation.value < 0.1) continue;
      const color = weatherColorChannels(kind, interpolation.value);
      const offset = (row * rasterWidth + column) * 4;
      pixels[offset] = color[0];
      pixels[offset + 1] = color[1];
      pixels[offset + 2] = color[2];
      pixels[offset + 3] = Math.round(interpolation.coverage * 255);
    }
  }

  return { width: rasterWidth, height: rasterHeight, step, pixels };
}

/** 저해상도 IDW raster를 고품질 확대해 점무늬 없는 연속 기상장으로 합성합니다. */
export function drawScalarLayer(
  visibleContext: CanvasRenderingContext2D,
  width: number,
  height: number,
  points: ScreenWeatherPoint[],
  kind: ScalarLayerKind,
): void {
  const raster = buildScalarRaster(points, kind, width, height);
  if (!raster) return;

  let offscreen: HTMLCanvasElement | OffscreenCanvas | null = null;
  let offCtx: CanvasRenderingContext2D | OffscreenCanvasRenderingContext2D | null = null;

  if (typeof OffscreenCanvas !== "undefined") {
    try {
      offscreen = new OffscreenCanvas(raster.width, raster.height);
      offCtx = offscreen.getContext("2d");
    } catch {
      offscreen = null;
      offCtx = null;
    }
  }

  if (!offCtx && typeof document !== "undefined") {
    const docCanvas = document.createElement("canvas");
    docCanvas.width = raster.width;
    docCanvas.height = raster.height;
    offscreen = docCanvas;
    offCtx = docCanvas.getContext("2d");
  }

  if (!offCtx || !offscreen) return;

  const imageData = offCtx.createImageData(raster.width, raster.height);
  imageData.data.set(raster.pixels);
  offCtx.putImageData(imageData, 0, 0);

  visibleContext.save();
  visibleContext.globalAlpha = scalarLayerAlpha(kind);
  visibleContext.imageSmoothingEnabled = true;
  visibleContext.imageSmoothingQuality = "high";
  visibleContext.drawImage(
    offscreen as CanvasImageSource,
    0,
    0,
    raster.width,
    raster.height,
    0,
    0,
    width,
    height,
  );
  visibleContext.restore();
}
