import { useEffect, useRef, useState } from "react";
import type { WeatherCanvasPoint } from "./weatherCanvasMotion";

export interface MapInformationCardContent {
  eyebrow: string;
  title: string;
  value?: string;
  lines: string[];
  meta: string[];
  tone?: "default" | "simulation";
}

interface MapInformationCardProps {
  anchor: WeatherCanvasPoint;
  viewport: { width: number; height: number };
  content: MapInformationCardContent;
  onClose: () => void;
}

export interface MapInformationCardSize {
  width: number;
  height: number;
}

const CARD_GAP = 12;
const FALLBACK_CARD_SIZE: MapInformationCardSize = { width: 260, height: 152 };

const clamp = (value: number, minimum: number, maximum: number) =>
  Math.min(Math.max(value, minimum), Math.max(minimum, maximum));

/** 터치점 옆을 우선하되 카드 전체를 viewport 12px 안에 유지합니다. */
export function clampMapInformationCardPosition(
  anchor: WeatherCanvasPoint,
  viewport: { width: number; height: number },
  card: MapInformationCardSize,
): WeatherCanvasPoint {
  const right = viewport.width - CARD_GAP;
  const bottom = viewport.height - CARD_GAP;
  const preferredX = anchor.x + CARD_GAP + card.width <= right
    ? anchor.x + CARD_GAP
    : anchor.x - card.width - CARD_GAP;
  const preferredY = anchor.y + CARD_GAP + card.height <= bottom
    ? anchor.y + CARD_GAP
    : anchor.y - card.height - CARD_GAP;
  return {
    x: clamp(preferredX, CARD_GAP, viewport.width - card.width - CARD_GAP),
    y: clamp(preferredY, CARD_GAP, viewport.height - card.height - CARD_GAP),
  };
}

export function MapInformationCard({
  anchor,
  viewport,
  content,
  onClose,
}: MapInformationCardProps) {
  const cardRef = useRef<HTMLElement>(null);
  const [size, setSize] = useState(FALLBACK_CARD_SIZE);

  useEffect(() => {
    const card = cardRef.current;
    if (!card) return;
    setSize({ width: card.offsetWidth, height: card.offsetHeight });
  }, [content]);

  const position = clampMapInformationCardPosition(anchor, viewport, size);
  return (
    <aside
      ref={cardRef}
      className={`map-information-card ${content.tone === "simulation" ? "simulation" : ""}`}
      style={{ left: position.x, top: position.y }}
      role="dialog"
      aria-modal="false"
      aria-label={`${content.title} 지도 정보`}
    >
      <header>
        <span>{content.eyebrow}</span>
        <button type="button" onClick={onClose} aria-label="지도 정보 닫기">×</button>
      </header>
      <strong>{content.title}</strong>
      {content.value && <b className="map-information-value">{content.value}</b>}
      {content.lines.map((line, index) => <p key={`${index}:${line}`}>{line}</p>)}
      <footer>
        {content.meta.map((item, index) => <small key={`${index}:${item}`}>{item}</small>)}
      </footer>
    </aside>
  );
}
