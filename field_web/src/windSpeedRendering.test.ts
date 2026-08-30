import { describe, expect, it, vi } from "vitest";
import type { WindVector, WindVectorField } from "./windParticleField";
import {
  buildWindSpeedRaster,
  drawWindSpeedLayer,
  WIND_SPEED_LAYER_ALPHA,
} from "./windSpeedRendering";

function vector(speed: number): WindVector {
  return { u: speed, v: 0, speed, dx: speed, dy: 0 };
}

function field(vectors: Array<WindVector | null>): WindVectorField {
  return {
    width: 24,
    height: 12,
    step: 12,
    columns: 3,
    rows: 1,
    sampleCount: 3,
    vectors,
  };
}

describe("windSpeedRendering", () => {
  it("기존 vector field sample을 0.14 alpha의 결정적 푸른 raster로 변환한다", () => {
    expect(WIND_SPEED_LAYER_ALPHA).toBe(0.14);
    const source = field([vector(0), vector(12.5), vector(25)]);
    const first = buildWindSpeedRaster(source);
    const second = buildWindSpeedRaster(source);
    expect(first).toEqual(second);
    expect(first?.width).toBe(3);
    expect(first?.height).toBe(1);
    expect(Array.from(first?.pixels ?? [])).toEqual([
      238, 244, 248, 255,
      114, 164, 202, 255,
      24, 61, 112, 255,
    ]);
  });

  it("coverage 밖 null sample은 투명하게 두고 null field는 만들지 않는다", () => {
    const raster = buildWindSpeedRaster(field([vector(5), null, vector(20)]));
    expect(Array.from(raster?.pixels.slice(4, 8) ?? [])).toEqual([0, 0, 0, 0]);
    expect(buildWindSpeedRaster(null)).toBeNull();
  });

  it("field가 없으면 visible canvas를 변경하지 않는다", () => {
    const context = {
      save: vi.fn(),
      drawImage: vi.fn(),
    } as unknown as CanvasRenderingContext2D;
    drawWindSpeedLayer(context, null);
    expect(context.save).not.toHaveBeenCalled();
    expect(context.drawImage).not.toHaveBeenCalled();
  });
});
