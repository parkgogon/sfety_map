import type {
  WeatherLayerKind,
  WeatherLayerPoint,
  WeatherLayerResponse,
} from "./types";
import { weatherColorChannels, windSpeedColor } from "./utils";

export interface ScreenWeatherPoint {
  source: WeatherLayerPoint;
  x: number;
  y: number;
}

type ScalarLayerKind = WeatherLayerKind;

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
 * - 바람: 0.12 (저채도 풍속 색면, 화살표는 별도 렌더링)
 */
export function scalarLayerAlpha(layer: WeatherLayerKind): number {
  if (layer === "temperature") return 0.24;
  if (layer === "rainfall") return 0.28;
  return 0.12;
}

/** 보간 입력에서 무효값과 음수 강수·풍속을 제외합니다. 0은 경계 보간에 사용합니다. */
export function shouldSkipScalarPoint(
  kind: WeatherLayerKind,
  value: number | undefined,
): boolean {
  if (value === undefined || !Number.isFinite(value)) return true;
  if ((kind === "rainfall" || kind === "wind") && value < 0) return true;
  return false;
}

function scalarPointValue(point: ScreenWeatherPoint, kind: ScalarLayerKind): number | undefined {
  return kind === "wind" ? point.source.speed_ms : point.source.value;
}

function scalarPointsWithValues(
  points: ScreenWeatherPoint[],
  kind: ScalarLayerKind,
): ScalarPointWithValue[] {
  return points.flatMap((point) => {
    const value = scalarPointValue(point, kind);
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
  layer: WeatherLayerResponse,
): void {
  const raster = buildScalarRaster(points, layer.layer, width, height);
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
  visibleContext.globalAlpha = scalarLayerAlpha(layer.layer);
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

/**
 * 화면 너비와 지도 레벨에 따라 바람 화살표의 최적 격자 간격(spacing)을 계산합니다.
 * - PC (가로 >= 768px): 가로 약 7~12개 격자
 * - 모바일 (가로 < 768px): 가로 약 5~8개 격자
 */
export function calculateWindSpacing(
  width: number,
  _height: number,
  mapLevel: number,
): number {
  const isMobile = width < 768;
  const targetCols = isMobile ? (mapLevel >= 9 ? 5 : 6) : mapLevel >= 9 ? 8 : 10;
  const rawSpacing = width / Math.max(1, targetCols);
  return Math.min(120, Math.max(48, Math.round(rawSpacing)));
}

export const WIND_EDGE_INSET = 22;
export const WIND_ARROW_MIN_LENGTH = 14;
export const WIND_ARROW_MAX_LENGTH = 30;
export const WIND_ARROW_OUTLINE_WIDTH = 3.6;
export const WIND_ARROW_LINE_WIDTH = 2;

export function windArrowLength(speed: number): number {
  const finiteSpeed = Number.isFinite(speed) ? Math.max(0, speed) : 0;
  return Math.min(
    WIND_ARROW_MAX_LENGTH,
    Math.max(WIND_ARROW_MIN_LENGTH, WIND_ARROW_MIN_LENGTH + finiteSpeed * 0.64),
  );
}

/**
 * 보이는 바람 점들을 격자로 묶고, 각 셀에서 중심 거리와 풍속을 고려해
 * 결정적(deterministic)인 대표점을 1개씩 선별합니다.
 * 원본 배열의 순서와 무관하게 동일한 결과를 보장합니다.
 */
export function sampleWindPoints(
  width: number,
  height: number,
  points: ScreenWeatherPoint[],
  mapLevel: number,
): ScreenWeatherPoint[] {
  const inset = WIND_EDGE_INSET;
  const validWidth = width - inset * 2;
  const validHeight = height - inset * 2;
  if (validWidth <= 0 || validHeight <= 0) return [];

  const spacing = calculateWindSpacing(width, height, mapLevel);
  const cells = new Map<string, ScreenWeatherPoint[]>();

  // 1. Inset 영역 내 유효한 풍향·풍속 점들을 격자별로 수집
  points.forEach((point) => {
    const speed = point.source.speed_ms;
    const dir = point.source.direction_to_deg;
    if (speed === undefined || dir === undefined || !Number.isFinite(speed)) return;
    if (
      point.x < inset ||
      point.x > width - inset ||
      point.y < inset ||
      point.y > height - inset
    ) {
      return;
    }

    const cellX = Math.floor((point.x - inset) / spacing);
    const cellY = Math.floor((point.y - inset) / spacing);
    const key = `${cellX}:${cellY}`;

    const list = cells.get(key);
    if (list) list.push(point);
    else cells.set(key, [point]);
  });

  const selected: ScreenWeatherPoint[] = [];

  // 2. 각 셀에서 중심 거리 + 풍속 대표성 + 결정적 tie-breaker로 최고점 선택
  cells.forEach((candidates, key) => {
    const [cellXStr, cellYStr] = key.split(":");
    const cellX = Number.parseInt(cellXStr, 10);
    const cellY = Number.parseInt(cellYStr, 10);
    const centerX = inset + (cellX + 0.5) * spacing;
    const centerY = inset + (cellY + 0.5) * spacing;
    const maxDistance = spacing * 0.7071; // 대각선 반길이

    let bestPoint = candidates[0];
    let bestScore = -Infinity;

    candidates.forEach((pt) => {
      const dist = Math.hypot(pt.x - centerX, pt.y - centerY);
      const distRatio = Math.min(1, dist / Math.max(1, maxDistance));
      const speed = pt.source.speed_ms ?? 0;
      // 중심에 가까울수록 높은 점수(0.6 비중) + 유의미한 풍속 가중치(0.4 비중)
      const score = (1 - distRatio) * 0.6 + Math.min(1, speed / 20) * 0.4;

      if (score > bestScore) {
        bestScore = score;
        bestPoint = pt;
      } else if (Math.abs(score - bestScore) < 1e-6) {
        // Tie breaker: 고유 grid 좌표로 100% 결정성 보장
        if (
          pt.source.grid_x < bestPoint.source.grid_x ||
          (pt.source.grid_x === bestPoint.source.grid_x &&
            pt.source.grid_y < bestPoint.source.grid_y)
        ) {
          bestPoint = pt;
        }
      }
    });

    selected.push(bestPoint);
  });

  return selected.sort((a, b) => {
    if (a.source.grid_x !== b.source.grid_x) return a.source.grid_x - b.source.grid_x;
    return a.source.grid_y - b.source.grid_y;
  });
}

/**
 * 단일 바람 화살표를 그립니다.
 */
export function drawWindArrow(
  context: CanvasRenderingContext2D,
  point: ScreenWeatherPoint,
): void {
  const speed = point.source.speed_ms;
  const direction = point.source.direction_to_deg;
  if (speed === undefined || direction === undefined) return;
  const length = windArrowLength(speed);
  const radians = (direction * Math.PI) / 180;
  context.save();
  context.translate(point.x, point.y);
  context.rotate(radians);
  context.lineCap = "round";
  context.lineJoin = "round";
  context.beginPath();
  context.moveTo(0, length / 2);
  context.lineTo(0, -length / 2);
  context.lineTo(-4.5, -length / 2 + 6);
  context.moveTo(0, -length / 2);
  context.lineTo(4.5, -length / 2 + 6);
  context.strokeStyle = "rgba(255,255,255,.78)";
  context.lineWidth = WIND_ARROW_OUTLINE_WIDTH;
  context.stroke();
  context.strokeStyle = windSpeedColor(speed, 0.96);
  context.lineWidth = WIND_ARROW_LINE_WIDTH;
  context.stroke();
  context.restore();
}

/**
 * 바람 격자 레이어를 그립니다.
 */
export function drawWindLayer(
  context: CanvasRenderingContext2D,
  width: number,
  height: number,
  points: ScreenWeatherPoint[],
  mapLevel: number,
): void {
  const sampled = sampleWindPoints(width, height, points, mapLevel);
  sampled.forEach((point) => {
    drawWindArrow(context, point);
  });
}
