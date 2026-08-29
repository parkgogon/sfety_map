import type {
  Facility,
  WeatherLayerKind,
  WeatherLayerPoint,
  WeatherLayerResponse,
} from "./types";
import { rainfallColor, temperatureColor, windSpeedColor } from "./utils";

export interface ScreenWeatherPoint {
  source: WeatherLayerPoint;
  x: number;
  y: number;
}

export function median(values: number[]): number {
  if (!values.length) return 12;
  const ordered = [...values].sort((left, right) => left - right);
  return ordered[Math.floor(ordered.length / 2)];
}

/**
 * 기온·강수 스칼라 레이어의 격자 반경을 계산합니다.
 * 인접점 간격의 약 0.54배(0.50~0.58 범위)를 사용하여 과도한 겹침과 바둑판 무늬를 방지합니다.
 */
export function scalarCellRadius(points: ScreenWeatherPoint[]): number {
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
    if (distances.length >= 80) break;
  }
  return Math.min(90, Math.max(5, median(distances) * 0.54));
}

/**
 * 레이어 종류별 화면 전체 합성 불투명도(alpha)를 반환합니다.
 * - 기온: 0.28 (0.26~0.32 범위)
 * - 강수: 0.34 (0.30~0.38 범위)
 * - 바람: 1.0 (별도 선명한 화살표 렌더링)
 */
export function scalarLayerAlpha(layer: WeatherLayerKind): number {
  if (layer === "temperature") return 0.28;
  if (layer === "rainfall") return 0.34;
  return 1.0;
}

/**
 * 스칼라 레이어에서 무효값 또는 강수량 0 이하 점을 생략할지 여부를 판정합니다.
 */
export function shouldSkipScalarPoint(
  kind: WeatherLayerKind,
  value: number | undefined,
): boolean {
  if (value === undefined || !Number.isFinite(value)) return true;
  if (kind === "rainfall" && value <= 0) return true;
  return false;
}

/**
 * 화면 영역 안쪽에 유효한 스칼라 포인트만 필터링합니다.
 */
export function filterScalarPoints(
  points: ScreenWeatherPoint[],
  layer: WeatherLayerResponse,
  width: number,
  height: number,
  radius: number,
): ScreenWeatherPoint[] {
  return points.filter((point) => {
    if (shouldSkipScalarPoint(layer.layer, point.source.value)) return false;
    return (
      point.x >= -radius &&
      point.x <= width + radius &&
      point.y >= -radius &&
      point.y <= height + radius
    );
  });
}

/**
 * 기온·강수 스칼라 레이어를 offscreen canvas에 먼저 렌더링한 후,
 * visible canvas에 레이어별 단일 alpha로 합성하여 불투명도 누적 폭증을 방지합니다.
 */
export function drawScalarLayer(
  visibleContext: CanvasRenderingContext2D,
  width: number,
  height: number,
  points: ScreenWeatherPoint[],
  layer: WeatherLayerResponse,
): void {
  const radius = scalarCellRadius(points);
  const visible = filterScalarPoints(points, layer, width, height, radius);
  if (!visible.length) return;

  // Offscreen canvas 생성
  let offscreen: HTMLCanvasElement | OffscreenCanvas | null = null;
  let offCtx: CanvasRenderingContext2D | OffscreenCanvasRenderingContext2D | null = null;

  if (typeof OffscreenCanvas !== "undefined") {
    try {
      offscreen = new OffscreenCanvas(Math.max(1, width), Math.max(1, height));
      offCtx = offscreen.getContext("2d");
    } catch {
      offscreen = null;
      offCtx = null;
    }
  }

  if (!offCtx && typeof document !== "undefined") {
    const docCanvas = document.createElement("canvas");
    docCanvas.width = Math.max(1, width);
    docCanvas.height = Math.max(1, height);
    offscreen = docCanvas;
    offCtx = docCanvas.getContext("2d");
  }

  if (!offCtx || !offscreen) {
    // 캔버스 생성 불가 환경(SSR/테스트 등) fallback
    return;
  }

  visible.forEach((point) => {
    const value = point.source.value;
    if (value === undefined) return;
    const color =
      layer.layer === "temperature"
        ? temperatureColor(value, 0.95)
        : rainfallColor(value, 0.95);

    const gradient = offCtx.createRadialGradient(
      point.x,
      point.y,
      0,
      point.x,
      point.y,
      radius,
    );
    gradient.addColorStop(0, color);
    gradient.addColorStop(0.60, color);
    gradient.addColorStop(1, "rgba(255,255,255,0)");

    offCtx.fillStyle = gradient;
    offCtx.fillRect(point.x - radius, point.y - radius, radius * 2, radius * 2);
  });

  // Visible canvas에 단일 불투명도로 합성
  visibleContext.save();
  visibleContext.globalAlpha = scalarLayerAlpha(layer.layer);
  visibleContext.drawImage(offscreen as CanvasImageSource, 0, 0);
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
  const length = Math.min(34, Math.max(15, 15 + speed * 0.9));
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
  context.strokeStyle = "rgba(255,255,255,.92)";
  context.lineWidth = 5;
  context.stroke();
  context.strokeStyle = windSpeedColor(speed, 0.96);
  context.lineWidth = 2.2;
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

/**
 * 시설 주변 마커 가독성을 위해 기상 레이어를 잘라냅니다.
 */
export function clearAroundFacilities(
  context: CanvasRenderingContext2D,
  kakao: any,
  map: any,
  facilities: Facility[],
  selectedFacilityId: string,
): void {
  const projection = map.getProjection();
  context.save();
  context.globalCompositeOperation = "destination-out";
  facilities.forEach((facility) => {
    const point = projection.containerPointFromCoords(
      new kakao.maps.LatLng(facility.latitude, facility.longitude),
    );
    context.beginPath();
    context.arc(
      point.x,
      point.y,
      facility.id === selectedFacilityId ? 28 : 23,
      0,
      Math.PI * 2,
    );
    context.fill();
  });
  context.restore();
}
