import type { MapInformationCardContent } from "./MapInformationCard";
import type { WeatherLayerResponse } from "./types";
import { formatReferenceTime, WEATHER_LAYER_LABELS } from "./utils";
import {
  interpolateScalarAt,
  type ScreenWeatherPoint,
} from "./weatherLayerRendering";
import { interpolateWindAt, type WindVector } from "./windParticleField";

const FLOW_LABELS = ["북", "북동", "동", "남동", "남", "남서", "서", "북서"];

export interface MapWeatherInspection extends MapInformationCardContent {
  layer: WeatherLayerResponse["layer"];
  outOfRange: boolean;
}

export function windFlowDirectionDegrees(vector: WindVector): number {
  return (Math.atan2(vector.u, vector.v) * 180 / Math.PI + 360) % 360;
}

export function windFlowDirectionText(vector: WindVector): string {
  if (vector.speed < 0.05) return "바람 흐름이 거의 없음";
  const degrees = windFlowDirectionDegrees(vector);
  const direction = FLOW_LABELS[Math.floor((degrees + 22.5) / 45) % 8];
  return `${direction} ${degrees.toFixed(1)}° 방향으로 흐름`;
}

function inspectionMeta(layer: WeatherLayerResponse): {
  meta: string[];
  tone: "default" | "simulation";
} {
  const simulation = layer.status === "SIMULATION" || !layer.actual_data;
  const source = simulation
    ? "훈련 가정값 · 실제 관측 아님"
    : layer.status === "STALE"
      ? "지연된 기상청 격자 실황 참고정보"
      : "기상청 격자 실황 참고정보";
  return {
    meta: [`자료 기준 ${formatReferenceTime(layer.observed_at)}`, source],
    tone: simulation ? "simulation" : "default",
  };
}

function outOfRangeInspection(layer: WeatherLayerResponse): MapWeatherInspection {
  const context = inspectionMeta(layer);
  return {
    layer: layer.layer,
    outOfRange: true,
    eyebrow: "선택 지점 보간값",
    title: WEATHER_LAYER_LABELS[layer.layer],
    lines: ["이 지점은 기상 격자 범위 밖입니다."],
    ...context,
  };
}

/** 활성 레이어와 화면 좌표를 같은 renderer의 IDW 규칙으로 조회합니다. */
export function inspectMapWeatherAt(
  layer: WeatherLayerResponse,
  points: ScreenWeatherPoint[],
  x: number,
  y: number,
): MapWeatherInspection {
  const context = inspectionMeta(layer);
  if (layer.layer === "wind") {
    const wind = interpolateWindAt(points, x, y);
    if (!wind) return outOfRangeInspection(layer);
    return {
      layer: layer.layer,
      outOfRange: false,
      eyebrow: "선택 지점 보간값",
      title: WEATHER_LAYER_LABELS[layer.layer],
      value: `${wind.speed.toFixed(1)}m/s`,
      lines: [windFlowDirectionText(wind)],
      ...context,
    };
  }

  const scalar = interpolateScalarAt(points, layer.layer, x, y);
  if (!scalar || scalar.coverage <= 0) return outOfRangeInspection(layer);
  const unit = layer.layer === "temperature" ? "℃" : "mm";
  return {
    layer: layer.layer,
    outOfRange: false,
    eyebrow: "선택 지점 보간값",
    title: WEATHER_LAYER_LABELS[layer.layer],
    value: `${scalar.value.toFixed(1)}${unit}`,
    lines: [],
    ...context,
  };
}
