import type { ScreenWeatherPoint } from "./weatherLayerRendering";

export interface MapLabelRect { x: number; y: number; width: number; height: number }
export interface ScalarMapLabel extends MapLabelRect { text: string; point: ScreenWeatherPoint }
export const READABLE_SCALAR_ALPHA = { temperature: 0.108, rainfall: 0.126 } as const;

function intersects(a: MapLabelRect, b: MapLabelRect, gap = 8): boolean {
  return a.x < b.x + b.width + gap && a.x + a.width + gap > b.x
    && a.y < b.y + b.height + gap && a.y + a.height + gap > b.y;
}

/** Use real source grid values. Never synthesize labels in uncovered/invalid areas. */
export function scalarMapLabels(points: ScreenWeatherPoint[], kind: keyof typeof READABLE_SCALAR_ALPHA,
  viewport: MapLabelRect, exclusions: MapLabelRect[] = []): ScalarMapLabel[] {
  const labels: ScalarMapLabel[] = [];
  const candidates = points.flatMap((point) => {
    const value = point.source.value;
    if (!Number.isFinite(value) || (kind === "rainfall" && value! < 0.1)) return [];
    const text = `${Number(value!.toFixed(1))}${kind === "temperature" ? "°" : "mm"}`;
    const width = text.length * 6.8 + 12;
    const label = { x: point.x - width / 2, y: point.y - 11, width, height: 22, text, point };
    if (label.x < viewport.x + 14 || label.x + width > viewport.x + viewport.width - 14
      || label.y < viewport.y + 14 || label.y + label.height > viewport.y + viewport.height - 14
      || exclusions.some((rect) => intersects(label, rect))) return [];
    return [label];
  });
  for (const [fractionX, fractionY] of [[0.27, 0.3], [0.73, 0.3], [0.27, 0.7], [0.73, 0.7]]) {
    const x = viewport.x + viewport.width * fractionX, y = viewport.y + viewport.height * fractionY;
    const sorted = candidates.filter((candidate) => !labels.some((label) =>
      Math.hypot(candidate.point.x - label.point.x, candidate.point.y - label.point.y) < 120))
      .sort((a, b) => Math.hypot(a.point.x - x, a.point.y - y) - Math.hypot(b.point.x - x, b.point.y - y)
        || a.point.source.grid_x - b.point.source.grid_x || a.point.source.grid_y - b.point.source.grid_y);
    if (sorted[0]) labels.push(sorted[0]);
  }
  return labels;
}

export function drawScalarMapLabels(context: CanvasRenderingContext2D, labels: ScalarMapLabel[]) {
  context.save();
  context.font = "600 11px sans-serif";
  context.textAlign = "center"; context.textBaseline = "middle";
  for (const label of labels) {
    context.fillStyle = "rgba(255,255,255,.95)"; context.strokeStyle = "#cfdae3"; context.lineWidth = 0.8;
    context.beginPath(); context.roundRect(label.x, label.y, label.width, label.height, 6);
    context.fill(); context.stroke(); context.fillStyle = "#314c64";
    context.fillText(label.text, label.x + label.width / 2, label.y + label.height / 2);
  }
  context.restore();
}
