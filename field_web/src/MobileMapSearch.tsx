import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { FacilityIcon } from "./facilityIcons";
import { formatDistance, nearbyFacilities, type ReferencePoint } from "./locationReference";
import { searchLocations } from "./locationSearch";
import { MobileBottomSheet } from "./MobileBottomSheet";
import type { Facility } from "./types";
import type { LocationReferenceState } from "./useLocationReference";
import type { MobilePanel, MobileSearchTab } from "./useMobileLayout";

interface Props {
  panel: MobilePanel;
  tab: MobileSearchTab;
  facilityQuery: string;
  facilityResults: Facility[];
  facilities: Facility[];
  visibleFacilityIds: ReadonlySet<string>;
  reference: LocationReferenceState;
  onSelectTab: (tab: MobileSearchTab) => void;
  onFacilityQuery: (query: string) => void;
  onSelectFacility: (facility: Facility) => void;
  onPanelChange: (panel: MobilePanel) => void;
  onClose: () => void;
}

export function MobileMapSearch({
  panel,
  tab,
  facilityQuery,
  facilityResults,
  facilities,
  visibleFacilityIds,
  reference,
  onSelectTab,
  onFacilityQuery,
  onSelectFacility,
  onPanelChange,
  onClose,
}: Props) {
  const [locationQuery, setLocationQuery] = useState("");
  const [locationResults, setLocationResults] = useState<ReferencePoint[]>([]);
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(false);
  const [candidateName, setCandidateName] = useState("");
  const [editingName, setEditingName] = useState(false);
  const [limit, setLimit] = useState(10);
  const request = useRef(0);
  const nearby = useMemo(
    () => reference.point ? nearbyFacilities(facilities, reference.point) : [],
    [facilities, reference.point],
  );

  useEffect(() => () => { request.current += 1; }, []);
  useEffect(() => {
    setCandidateName(reference.candidate?.label ?? "");
    setEditingName(false);
  }, [reference.candidate]);
  useEffect(() => { setLimit(10); }, [reference.point]);
  useEffect(() => {
    if (panel === "search") return;
    request.current += 1;
    setLoading(false);
  }, [panel]);
  useEffect(() => {
    if (!reference.picking && !reference.candidate) return;
    const cancelCurrent = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      event.stopImmediatePropagation();
      reference.cancel();
      onPanelChange("search");
    };
    window.addEventListener("keydown", cancelCurrent, true);
    return () => window.removeEventListener("keydown", cancelCurrent, true);
  }, [reference.picking, reference.candidate, reference.cancel, onPanelChange]);

  const clearLocationResults = () => {
    request.current += 1;
    setLocationResults([]);
    setMessage("");
    setLoading(false);
  };

  const searchLocation = async (event: FormEvent) => {
    event.preventDefault();
    const keyword = locationQuery.trim();
    if (!keyword) return;
    const current = ++request.current;
    setLoading(true);
    setMessage("");
    setLocationResults([]);
    try {
      const result = await searchLocations(keyword);
      if (current !== request.current || panel !== "search") return;
      setLocationResults(result.points);
      setMessage(result.partial
        ? "일부 검색 결과만 표시합니다. 다시 검색하거나 지도에서 지정할 수 있습니다."
        : result.points.length
          ? "위치를 선택한 뒤 지도에서 확인해 주세요."
          : "검색 결과가 없습니다. 주소를 더 자세히 입력하거나 지도에서 지정해 주세요.");
    } catch {
      if (current === request.current && panel === "search") {
        setMessage("장소 검색을 완료하지 못했습니다. 다시 검색하거나 지도에서 지정해 주세요.");
      }
    } finally {
      if (current === request.current) setLoading(false);
    }
  };

  const selectCandidate = (point: ReferencePoint) => {
    clearLocationResults();
    if (document.activeElement instanceof HTMLElement) document.activeElement.blur();
    reference.preview(point);
    onPanelChange("none");
  };

  const startPicking = () => {
    clearLocationResults();
    if (document.activeElement instanceof HTMLElement) document.activeElement.blur();
    reference.startPicking();
    onPanelChange("none");
  };

  if (reference.picking) return <section className="mobile-picking-guide" aria-label="기준점 위치 지정">
    <p role="status">기준점으로 삼을 위치를 눌러 주세요.</p>
    <button type="button" onClick={() => { reference.cancel(); onPanelChange("search"); }}>취소</button>
  </section>;

  if (reference.candidate) {
    const coordinate = `${reference.candidate.latitude.toFixed(5)}, ${reference.candidate.longitude.toFixed(5)}`;
    return <section className="mobile-candidate-panel" aria-label="후보 위치 확인">
      <div className="mobile-candidate-heading">
        <div>
          <strong title={candidateName || reference.candidate.label}>{candidateName || reference.candidate.label}</strong>
          <span>{reference.candidate.address || coordinate}</span>
        </div>
        <button type="button" onClick={() => setEditingName((value) => !value)}>이름 수정</button>
      </div>
      {editingName && <label>기준점 이름
        <input aria-label="기준점 이름" maxLength={80} value={candidateName} onChange={(event) => setCandidateName(event.target.value)} />
      </label>}
      <p>검색 결과는 대표 위치일 수 있습니다. 지도에서 확인해 주세요.</p>
      <div className="mobile-candidate-actions">
        <button type="button" onClick={() => { reference.cancel(); onPanelChange("search"); }}>다시 찾기</button>
        {reference.candidate.source === "map" && <button type="button" onClick={startPicking}>위치 다시 지정</button>}
        <button className="primary-button" type="button" onClick={() => {
          reference.confirm(candidateName);
          onPanelChange("nearby");
        }}>이곳으로 지정</button>
      </div>
    </section>;
  }

  if (panel === "nearby" && reference.point) return <MobileBottomSheet
    title="주변 시설"
    onClose={onClose}
    footer={<p className="mobile-nearby-caveat">직선거리 참고용이며 피해 여부나 영향 범위를 뜻하지 않습니다.</p>}
  >
    <div className="mobile-nearby-heading">
      <div><strong>{reference.point.label}</strong><span>{reference.point.address || `${reference.point.latitude.toFixed(5)}, ${reference.point.longitude.toFixed(5)}`}</span></div>
      <button type="button" onClick={reference.recenter}>기준점 보기</button>
    </div>
    <div className="mobile-nearby-actions">
      <label><input type="checkbox" checked={reference.showRings} onChange={(event) => reference.setShowRings(event.target.checked)} />1·3·5km 거리 원</label>
      <button type="button" onClick={() => { reference.preview(reference.point!); onPanelChange("none"); }}>이름·위치 수정</button>
    </div>
    <p className="mobile-nearby-count">전체 {facilities.length}개소 기준 · 5km 이내 {nearby.filter((row) => row.meters <= 5000).length}개소</p>
    {nearby.length ? <>
      <ol className="mobile-nearby-list" aria-label="가까운 시설 순서">
        {nearby.slice(0, limit).map(({ facility, meters }) => <li key={facility.id}>
          <button type="button" aria-pressed={reference.targetId === facility.id} onClick={() => {
            onSelectFacility(facility);
            onPanelChange("facility");
          }}>
            <FacilityIcon groupId={facility.group_id} />
            <span><strong>{facility.name}</strong><small>{facility.group_label}
              {!visibleFacilityIds.has(facility.id) && " · 필터로 숨김 — 선택하면 표시"}
            </small></span>
            <b>{formatDistance(meters)}</b>
          </button>
        </li>)}
      </ol>
      <p className="mobile-nearby-count">가까운 순 {Math.min(limit, nearby.length)} / {nearby.length}개소</p>
      {limit < nearby.length && <button className="mobile-nearby-more" type="button" onClick={() => setLimit((value) => value + 10)}>주변 시설 10개 더 보기</button>}
    </> : <p>좌표를 확인할 수 있는 시설이 없습니다.</p>}
  </MobileBottomSheet>;

  if (panel !== "search") return null;
  return <MobileBottomSheet title="검색" onClose={() => { clearLocationResults(); onClose(); }}>
    <div className="mobile-search-tabs" role="tablist" aria-label="검색 대상">
      <button type="button" role="tab" aria-selected={tab === "facilities"} onClick={() => onSelectTab("facilities")}>우리 시설</button>
      <button type="button" role="tab" aria-selected={tab === "location"} onClick={() => onSelectTab("location")}>장소·주소</button>
    </div>
    {tab === "facilities" ? <div className="mobile-search-content" role="tabpanel">
      <label className="mobile-search-input">
        <span aria-hidden="true">⌕</span>
        <input autoFocus value={facilityQuery} onChange={(event) => onFacilityQuery(event.target.value)} placeholder="시설명 또는 주소 검색" aria-label="시설명 또는 주소 검색" />
        {facilityQuery && <button type="button" onClick={() => onFacilityQuery("")} aria-label="검색어 지우기">×</button>}
      </label>
      {facilityQuery.trim() && <div className="mobile-search-results">
        {facilityResults.length ? facilityResults.map((facility) => <button type="button" key={facility.id} onClick={() => {
          if (document.activeElement instanceof HTMLElement) document.activeElement.blur();
          onSelectFacility(facility);
          onPanelChange("facility");
        }}>
          <span className="result-grade" style={{ backgroundColor: facility.grade_color }}>{facility.grade_label}</span>
          <span><b>{facility.name}</b><small>{facility.address}</small></span>
        </button>) : <p>일치하는 시설이 없습니다.</p>}
      </div>}
    </div> : <div className="mobile-search-content" role="tabpanel">
      <form className="mobile-location-form" onSubmit={searchLocation}>
        <input autoFocus aria-label="장소명 또는 주소" placeholder="공장명, 지역명 또는 주소" maxLength={120}
          value={locationQuery} onChange={(event) => { setLocationQuery(event.target.value); clearLocationResults(); }} />
        <button type="submit" disabled={!locationQuery.trim() || loading}>{loading ? "검색 중…" : "검색"}</button>
      </form>
      <button className="mobile-pick-button" type="button" onClick={startPicking}>지도에서 지정</button>
      {message && <p className="mobile-search-message" role="status">{message}</p>}
      {locationResults.length > 0 && <ul className="mobile-location-results" aria-label="장소·주소 검색 결과">
        {locationResults.map((point, index) => <li key={`${point.latitude}-${point.longitude}-${index}`}>
          <button type="button" onClick={() => selectCandidate(point)}>
            <strong>{point.label}</strong><span>{point.address}</span>
            <small>{point.source === "place" ? "장소" : "주소"} · 지도에서 위치 확인</small>
          </button>
        </li>)}
      </ul>}
    </div>}
  </MobileBottomSheet>;
}
