import { useState } from "react";
import type { Facility } from "./types";
import { uniqueWarningText } from "./utils";

interface FacilitySheetProps {
  facility: Facility | null;
  onClose: () => void;
}

export function FacilitySheet({ facility, onClose }: FacilitySheetProps) {
  const [expanded, setExpanded] = useState(false);

  if (!facility) {
    return (
      <section className="facility-sheet empty-sheet" aria-label="선택 시설 안내">
        <span className="sheet-handle" aria-hidden="true" />
        <b>확인할 시설을 선택하세요</b>
        <span>지도 마커를 누르거나 시설명을 검색할 수 있습니다.</span>
      </section>
    );
  }

  return (
    <section className={`facility-sheet ${expanded ? "expanded" : ""}`} aria-label="선택 시설 상세">
      <span className="sheet-handle" aria-hidden="true" />
      <div className="facility-heading">
        <span className="grade-badge" style={{ backgroundColor: facility.grade_color }}>
          {facility.grade_label}
        </span>
        <div>
          <h2>{facility.name}</h2>
          <p>{facility.group_label}</p>
        </div>
        <button className="icon-button close-button" type="button" onClick={onClose} aria-label="시설 선택 닫기">
          ×
        </button>
      </div>
      <div className="facility-alert-line">
        <span>영향 특보</span>
        <strong>{uniqueWarningText(facility)}</strong>
      </div>
      <div className="facility-action">
        <span>권장 행동</span>
        <strong>{facility.recommended_action}</strong>
      </div>
      {expanded && (
        <div className="facility-details">
          <dl>
            <div><dt>판정 설명</dt><dd>{facility.meaning}</dd></div>
            <div><dt>주소</dt><dd>{facility.address}</dd></div>
            <div><dt>담당</dt><dd>{facility.public_contact}</dd></div>
          </dl>
          {facility.reasons.length > 0 && (
            <ul className="reason-list">
              {facility.reasons.map((reason) => (
                <li key={`${reason.warning_id}-${reason.type}`}>
                  <b>{reason.type} {reason.raw_level}</b>
                  <span>{reason.region} · 이 시설에 영향</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
      <button className="sheet-toggle" type="button" onClick={() => setExpanded((value) => !value)}>
        {expanded ? "간단히 보기" : "시설정보 자세히"}
        <span aria-hidden="true">{expanded ? "⌄" : "⌃"}</span>
      </button>
    </section>
  );
}
