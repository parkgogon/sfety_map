import { useEffect, useRef, useState } from "react";
import type { RiskGrade } from "./types";
import {
  GRADE_COLORS,
  GRADE_DISPLAY_ORDER,
  GRADE_LABELS,
} from "./utils";

interface GradeLegendProps {
  selectedGrades: ReadonlySet<RiskGrade>;
  onToggle: (grade: RiskGrade) => void;
}

export const GRADE_HELP: Record<RiskGrade, string> = {
  HIGH: "즉시 확인이 필요한 높은 위험",
  MEDIUM: "주의 깊은 확인이 필요한 위험",
  LOW: "특보 영향권에 포함된 관찰 대상",
  NONE: "특보의 영향권에 들지 않음",
  UNASSESSED: "기준 미등록 특보로 위험등급 판정불가",
  UNAVAILABLE: "기상청 데이터 미수신으로 위험등급 판정불가",
};
export const GRADE_HELP_FOOTER = "영향 없음은 절대적인 안전을 의미하지 않습니다.";

export const WARNING_ZONE_LEGENDS = [
  { key: "WARNING", label: "경보", color: "#D92D20", desc: "심각한 재해 위험 특보 (호우/폭염/태풍 등)" },
  { key: "ADVISORY", label: "주의보", color: "#E87817", desc: "주의가 필요한 기상특보" },
] as const;

export function GradeLegend({ selectedGrades, onToggle }: GradeLegendProps) {
  const rootRef = useRef<HTMLDivElement>(null);
  const helpButtonRef = useRef<HTMLButtonElement>(null);
  const [collapsed, setCollapsed] = useState(false);
  const [helpOpen, setHelpOpen] = useState(false);
  const [mouseHover, setMouseHover] = useState(false);
  const [focusWithin, setFocusWithin] = useState(false);
  const helpVisible = helpOpen || mouseHover || focusWithin;

  useEffect(() => {
    if (!helpVisible) return;
    const closeOutside = (event: PointerEvent) => {
      if (rootRef.current?.contains(event.target as Node)) return;
      setHelpOpen(false);
      setMouseHover(false);
      setFocusWithin(false);
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      setHelpOpen(false);
      setMouseHover(false);
      setFocusWithin(false);
      helpButtonRef.current?.blur();
    };
    document.addEventListener("pointerdown", closeOutside);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("pointerdown", closeOutside);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [helpVisible]);

  const collapseLegend = () => {
    setHelpOpen(false);
    setMouseHover(false);
    setFocusWithin(false);
    helpButtonRef.current?.blur();
    setCollapsed(true);
  };

  if (collapsed) {
    return (
      <div
        ref={rootRef}
        className="grade-legend grade-legend-collapsed"
        aria-label="위험등급 지도 표시 설정"
      >
        <button
          className="grade-legend-expand"
          type="button"
          aria-expanded="false"
          aria-controls="grade-legend-options"
          onClick={() => setCollapsed(false)}
        >
          범례 <span aria-hidden="true">›</span>
        </button>
      </div>
    );
  }

  return (
    <div
      ref={rootRef}
      className={`grade-legend ${helpVisible ? "help-visible" : ""}`}
      aria-label="위험등급 및 특보구역 지도 표시 설정"
    >
      <button
        className="grade-legend-collapse"
        type="button"
        aria-label="범례 접기"
        aria-expanded="true"
        aria-controls="grade-legend-options"
        onClick={collapseLegend}
      >
        <span aria-hidden="true">‹</span>
      </button>
      <div id="grade-legend-options" className="grade-options">
        {GRADE_DISPLAY_ORDER.map((grade) => (
          <button
            type="button"
            key={grade}
            className={selectedGrades.has(grade) ? "active" : ""}
            onClick={() => onToggle(grade)}
            aria-pressed={selectedGrades.has(grade)}
          >
            <span style={{ backgroundColor: GRADE_COLORS[grade] }} />
            {GRADE_LABELS[grade]}
          </button>
        ))}
        <div className="grade-legend-divider" aria-hidden="true" />
        <div className="zone-legend-group" title="기상청 특보 발효 구역 색상">
          <span className="zone-legend-label">구역:</span>
          {WARNING_ZONE_LEGENDS.map((zone) => (
            <span key={zone.key} className="zone-legend-chip">
              <span className="zone-color-box" style={{ backgroundColor: zone.color, borderColor: zone.color }} />
              {zone.label}
            </span>
          ))}
        </div>
      </div>
      <div
        className="grade-help"
        onPointerEnter={(event) => {
          if (event.pointerType === "mouse") setMouseHover(true);
        }}
        onPointerLeave={(event) => {
          if (event.pointerType === "mouse") setMouseHover(false);
        }}
        onFocusCapture={() => setFocusWithin(true)}
        onBlurCapture={(event) => {
          if (!event.currentTarget.contains(event.relatedTarget as Node | null)) {
            setFocusWithin(false);
          }
        }}
        onPointerDown={(event) => event.stopPropagation()}
        onClick={(event) => event.stopPropagation()}
      >
        <button
          ref={helpButtonRef}
          className="grade-help-button"
          type="button"
          aria-label="범례 상세 설명"
          aria-expanded={helpVisible}
          aria-controls="grade-help-popover"
          onClick={() => {
            setMouseHover(false);
            setFocusWithin(false);
            setHelpOpen((value) => !value);
          }}
        >
          ?
        </button>
        {helpVisible && (
          <div id="grade-help-popover" className="grade-help-popover" role="tooltip">
            <div className="help-section">
              <strong className="help-section-title">📍 시설 위험등급 (마커)</strong>
              <dl>
                {GRADE_DISPLAY_ORDER.map((grade) => (
                  <div key={grade}>
                    <dt><span style={{ backgroundColor: GRADE_COLORS[grade] }} />{GRADE_LABELS[grade]}</dt>
                    <dd>{GRADE_HELP[grade]}</dd>
                  </div>
                ))}
              </dl>
              <p className="help-subtext">{GRADE_HELP_FOOTER}</p>
            </div>

            <div className="help-divider" />

            <div className="help-section">
              <strong className="help-section-title">🗺️ 특보 발효 구역 (지도 배경)</strong>
              <dl>
                {WARNING_ZONE_LEGENDS.map((zone) => (
                  <div key={zone.key}>
                    <dt>
                      <span className="zone-color-box" style={{ backgroundColor: zone.color, borderColor: zone.color }} />
                      {zone.label}
                    </dt>
                    <dd>{zone.desc}</dd>
                  </div>
                ))}
              </dl>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

