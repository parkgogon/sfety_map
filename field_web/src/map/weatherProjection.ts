import type { WeatherCanvasLayout, WeatherCanvasPoint } from "../weatherCanvasMotion";

export interface WeatherTileAnchor { image: HTMLImageElement; source: string; point: WeatherCanvasPoint }

/** The SDK's projection jumps to the final zoom before its tiles finish animating.
 * Read only the live tile rectangles to follow that visual transition. No pixels,
 * tile downloads, private SDK methods, or map requests are involved. */
export function captureWeatherTiles(element: HTMLElement, layout: WeatherCanvasLayout): WeatherTileAnchor[] | null {
  const mapRect = element.getBoundingClientRect();
  let candidates = Array.from(element.querySelectorAll<HTMLImageElement>("img"))
    .filter((image) => image.src.includes("/tile/")
      && (image.checkVisibility?.({ opacityProperty: true, visibilityProperty: true }) ?? true))
    .flatMap((image) => {
      const rect = image.getBoundingClientRect();
      if (rect.width <= 0 || rect.height <= 0 || rect.right <= mapRect.left || rect.left >= mapRect.right
        || rect.bottom <= mapRect.top || rect.top >= mapRect.bottom) return [];
      return [{ image, source: image.src, point: { x: rect.left - mapRect.left + layout.offsetX, y: rect.top - mapRect.top + layout.offsetY } }];
    });
  // During zoom the SDK can keep both an old and a new tile plane. Follow the
  // front plane that is actually painted, not a cached picture behind it.
  const painted = element.ownerDocument.elementsFromPoint?.(mapRect.left + mapRect.width / 2,
    mapRect.top + mapRect.height / 2).find((node) => node instanceof HTMLImageElement
      && candidates.some((candidate) => candidate.image === node));
  const plane = painted?.parentElement ?? candidates.sort((a, b) =>
    Number(getComputedStyle(b.image.parentElement!).zIndex || 0) - Number(getComputedStyle(a.image.parentElement!).zIndex || 0))[0]?.image.parentElement;
  candidates = candidates.filter((candidate) => candidate.image.parentElement === plane);
  if (candidates.length < 3) return null;
  const distance = (a: WeatherCanvasPoint, b: WeatherCanvasPoint) => Math.hypot(a.x - b.x, a.y - b.y);
  const center = { x: layout.offsetX + layout.viewportWidth / 2, y: layout.offsetY + layout.viewportHeight / 2 };
  const a = candidates.sort((p, q) => distance(p.point, center) - distance(q.point, center))[0];
  const b = candidates.sort((p, q) => distance(q.point, a.point) - distance(p.point, a.point))[0];
  const cross = (p: WeatherTileAnchor) => Math.abs((b.point.x - a.point.x) * (p.point.y - a.point.y)
    - (b.point.y - a.point.y) * (p.point.x - a.point.x));
  const c = candidates.sort((p, q) => cross(q) - cross(p))[0];
  return cross(c) > 1 ? [a, b, c] : null;
}

export function currentWeatherTilePoints(anchors: WeatherTileAnchor[], element: HTMLElement,
  layout: WeatherCanvasLayout): WeatherCanvasPoint[] | null {
  const mapRect = element.getBoundingClientRect();
  const points: WeatherCanvasPoint[] = [];
  for (const { image, source } of anchors) {
    const rect = image.getBoundingClientRect();
    if (!image.isConnected || image.src !== source || rect.width <= 0 || rect.height <= 0) return null;
    points.push({ x: rect.left - mapRect.left + layout.offsetX, y: rect.top - mapRect.top + layout.offsetY });
  }
  return points;
}
