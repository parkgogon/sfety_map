import { windSpeedColorChannels } from "./utils";
import type { WindVectorField } from "./windParticleField";

export const WIND_SPEED_LAYER_ALPHA = 0.14;

export interface WindSpeedRaster {
  width: number;
  height: number;
  pixels: Uint8ClampedArray;
}

/** 기존 vector field의 풍속 sample을 그대로 색상 raster로 변환합니다. */
export function buildWindSpeedRaster(
  field: WindVectorField | null,
): WindSpeedRaster | null {
  if (!field || field.columns <= 0 || field.rows <= 0) return null;
  const pixels = new Uint8ClampedArray(field.columns * field.rows * 4);
  field.vectors.forEach((vector, index) => {
    if (!vector || !Number.isFinite(vector.speed) || vector.speed < 0) return;
    const color = windSpeedColorChannels(vector.speed);
    const offset = index * 4;
    pixels[offset] = color[0];
    pixels[offset + 1] = color[1];
    pixels[offset + 2] = color[2];
    pixels[offset + 3] = 255;
  });
  return { width: field.columns, height: field.rows, pixels };
}

function createRasterCanvas(
  raster: WindSpeedRaster,
): {
  canvas: HTMLCanvasElement | OffscreenCanvas;
  context: CanvasRenderingContext2D | OffscreenCanvasRenderingContext2D;
} | null {
  if (typeof OffscreenCanvas !== "undefined") {
    try {
      const canvas = new OffscreenCanvas(raster.width, raster.height);
      const context = canvas.getContext("2d");
      if (context) return { canvas, context };
    } catch {
      // 일부 브라우저의 불완전한 OffscreenCanvas 구현에서는 DOM canvas를 사용합니다.
    }
  }
  if (typeof document === "undefined") return null;
  const canvas = document.createElement("canvas");
  canvas.width = raster.width;
  canvas.height = raster.height;
  const context = canvas.getContext("2d");
  return context ? { canvas, context } : null;
}

/** 저해상도 풍속 raster를 정적 surface canvas에 확대 합성합니다. */
export function drawWindSpeedLayer(
  visibleContext: CanvasRenderingContext2D,
  field: WindVectorField | null,
): void {
  const raster = buildWindSpeedRaster(field);
  if (!raster || !field) return;
  const offscreen = createRasterCanvas(raster);
  if (!offscreen) return;

  const imageData = offscreen.context.createImageData(raster.width, raster.height);
  imageData.data.set(raster.pixels);
  offscreen.context.putImageData(imageData, 0, 0);

  visibleContext.save();
  visibleContext.globalAlpha = WIND_SPEED_LAYER_ALPHA;
  visibleContext.imageSmoothingEnabled = true;
  visibleContext.imageSmoothingQuality = "high";
  visibleContext.drawImage(
    offscreen.canvas as CanvasImageSource,
    0,
    0,
    raster.width,
    raster.height,
    0,
    0,
    field.width,
    field.height,
  );
  visibleContext.restore();
}
