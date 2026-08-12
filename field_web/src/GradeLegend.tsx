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
  NONE: "현재 활성 특보와 연결되지 않음",
  UNASSESSED: "특보는 연결됐지만 기준 미등록으로 자동 판정 불가",
  UNAVAILABLE: "KMA 자료를 받지 못해 현재 등급 판정 불가",
};
export const GRADE_HELP_FOOTER = "영향 없음은 절대적인 안전을 의미하지 않습니다.";

export function GradeLegend({ selectedGrades, onToggle }: GradeLegendProps) {
  const rootRef = useRef<HTMLDivElement>(null);
  const helpButtonRef = useRef<HTMLButtonElement>(null);
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

  return (
    <div
      ref={rootRef}
      className={`grade-legend ${helpVisible ? "help-visible" : ""}`}
      aria-label="위험등급 지도 표시 설정"
    >
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
          aria-label="위험등급 설명"
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
            <strong>위험등급 안내</strong>
            <dl>
              {GRADE_DISPLAY_ORDER.map((grade) => (
                <div key={grade}>
                  <dt><span style={{ backgroundColor: GRADE_COLORS[grade] }} />{GRADE_LABELS[grade]}</dt>
                  <dd>{GRADE_HELP[grade]}</dd>
                </div>
              ))}
            </dl>
            <p>{GRADE_HELP_FOOTER}</p>
          </div>
        )}
      </div>
    </div>
  );
}
