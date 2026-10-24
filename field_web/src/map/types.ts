import type { RefObject } from "react";
import type { KakaoLatLng } from "../kakaoTypes";
import type { MapInformationCardContent } from "../MapInformationCard";
import type { WeatherCanvasPoint } from "../weatherCanvasMotion";

export interface PositionedMapInformation {
  anchor: WeatherCanvasPoint;
  viewport: { width: number; height: number };
  content: MapInformationCardContent;
}

export interface MapInteractions {
  pickReferenceAt(point: KakaoLatLng | undefined): boolean;
  dismissMapInformation(suppressNextMapClick?: boolean): void;
  setMapInformation(value: PositionedMapInformation | null): void;
  suppressMapInspectionUntilRef: RefObject<number>;
  weatherSurfaceCanvasRef: RefObject<HTMLCanvasElement | null>;
  windParticleCanvasRef: RefObject<HTMLCanvasElement | null>;
}
