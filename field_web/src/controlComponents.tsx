import type { Facility } from "./types";
import { uniqueWarningText } from "./utils";

interface AnalysisMobileFacilityListProps {
  facilities: readonly Facility[];
  selectedIds: ReadonlySet<string>;
  focusedFacilityId: string;
  onToggle: (facilityId: string) => void;
}

export function AnalysisMobileFacilityList({
  facilities,
  selectedIds,
  focusedFacilityId,
  onToggle,
}: AnalysisMobileFacilityListProps) {
  return (
    <div
      className="analysis-mobile-list"
      aria-label="모바일 전파 대상 시설 목록"
    >
      {facilities.map((facility) => {
        const isSelected = selectedIds.has(facility.id);
        return (
          <label
            key={facility.id}
            className={[
              "analysis-mobile-card",
              isSelected ? "selected" : "",
              facility.id === focusedFacilityId ? "focused" : "",
            ]
              .filter(Boolean)
              .join(" ")}
          >
            <input
              type="checkbox"
              checked={isSelected}
              onChange={() => onToggle(facility.id)}
              aria-label={`${facility.name} 선택`}
            />
            <span
              className="grade-badge"
              style={{ backgroundColor: facility.grade_color }}
            >
              {facility.grade_label}
            </span>
            <span className="analysis-mobile-facility">
              <strong>{facility.name}</strong>
              <span
                className={
                  facility.reasons.length > 0
                    ? "warning-tag active"
                    : "warning-tag"
                }
              >
                {uniqueWarningText(facility)}
              </span>
              <small>
                {facility.type} · {facility.address}
              </small>
            </span>
          </label>
        );
      })}
    </div>
  );
}
