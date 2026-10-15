import { useEffect, useMemo, useRef, useState } from "react";
import type { Facility } from "./types";
import { FacilityIcon } from "./facilityIcons";
import { formatDistance, nearbyFacilities, type ReferencePoint } from "./locationReference";
import { searchLocations } from "./locationSearch";
import type { LocationReferenceState } from "./useLocationReference";

interface Props {
  reference: LocationReferenceState;
  facilities: Facility[];
  visibleFacilityIds: Set<string>;
  onSelectFacility: (facility: Facility) => void;
}

export function LocationReferencePanel({ reference, facilities, visibleFacilityIds, onSelectFacility }: Props) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<ReferencePoint[]>([]);
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(false);
  const [name, setName] = useState("");
  const [collapsed, setCollapsed] = useState(false);
  const [limit, setLimit] = useState(10);
  const request = useRef(0);
  const nearby = useMemo(
    () => reference.point ? nearbyFacilities(facilities, reference.point) : [],
    [facilities, reference.point],
  );
  useEffect(() => () => { request.current += 1; }, []);
  useEffect(() => { setName(reference.candidate?.label ?? ""); }, [reference.candidate]);
  useEffect(() => { setLimit(10); }, [reference.point]);
  // Capture Escape before the page's facility/weather dismissal shortcuts.
  useEffect(() => {
    const close = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      if (reference.picking || reference.candidate) reference.cancel();
      else if (!collapsed) setCollapsed(true);
      else return;
      event.preventDefault();
      event.stopImmediatePropagation();
    };
    window.addEventListener("keydown", close, true);
    return () => window.removeEventListener("keydown", close, true);
  }, [reference, collapsed]);

  function invalidateSearch() {
    request.current += 1;
    setLoading(false);
    setResults([]);
    setMessage("");
  }
  async function search(event: React.FormEvent) {
    event.preventDefault();
    const keyword = query.trim();
    if (!keyword) return;
    const current = ++request.current;
    setLoading(true);
    setMessage("");
    setResults([]);
    try {
      const result = await searchLocations(keyword);
      if (current !== request.current) return;
      setResults(result.points);
      setMessage(result.partial ? "일부 검색 결과만 표시합니다. 다시 검색하거나 지도에서 지정할 수 있습니다."
        : result.points.length ? "위치를 선택한 뒤 지도에서 확인해 주세요."
        : "검색 결과가 없습니다. 주소를 더 자세히 입력하거나 지도에서 지정해 주세요.");
    } catch {
      if (current === request.current) setMessage("장소 검색을 완료하지 못했습니다. 다시 검색하거나 지도에서 지정해 주세요.");
    } finally {
      if (current === request.current) setLoading(false);
    }
  }
  function selectResult(point: ReferencePoint) {
    invalidateSearch();
    reference.preview(point);
  }
  function startPicking() {
    invalidateSearch();
    setCollapsed(false);
    reference.startPicking();
  }
  function clear() {
    invalidateSearch();
    setCollapsed(false);
    reference.clear();
  }

  if (reference.picking) return (
    <section className="location-reference-panel location-picking" aria-label="기준점 위치 지정">
      <p role="status">지도에서 기준점으로 삼을 위치를 눌러 주세요.</p>
      <button type="button" onClick={reference.cancel}>지정 취소</button>
    </section>
  );

  return (
    <section className={`location-reference-panel ${collapsed ? "is-collapsed" : ""} ${reference.candidate ? "has-candidate" : ""}`} aria-label="장소·주소와 주변 시설">
      <div className="location-panel-heading">
        <strong title={reference.point?.label}>{reference.point ? reference.point.label : "장소·주소 찾기"}</strong>
        <button type="button" aria-expanded={!collapsed} onClick={() => setCollapsed(!collapsed)}>
          {collapsed ? "주변 시설·검색 펼치기" : "접기"}
        </button>
      </div>
      {!collapsed && <div className="location-panel-body">
        <form className="location-search-form" onSubmit={search}>
          <input
            aria-label="장소명 또는 주소" placeholder="공장명, 지역명 또는 주소" maxLength={120}
            value={query} onChange={(event) => { setQuery(event.target.value); invalidateSearch(); }}
          />
          <button type="submit" disabled={!query.trim() || loading}>{loading ? "검색 중…" : "검색"}</button>
        </form>
        <div className="location-actions">
          <button type="button" onClick={startPicking}>지도에서 {reference.point ? "위치 수정" : "지정"}</button>
          {reference.point && <>
            <button type="button" onClick={reference.recenter}>기준점 보기</button>
            <button type="button" onClick={clear}>기준점 지우기</button>
          </>}
        </div>
        {message && <p role="status">{message}</p>}
        {results.length > 0 && <ul className="location-results" aria-label="장소·주소 검색 결과">
          {results.map((point, index) => <li key={index}>
            <button type="button" onClick={() => selectResult(point)}>
              <strong>{point.label}</strong><span>{point.address}</span>
              <small>{point.source === "place" ? "장소" : "주소"} · 지도에서 위치 확인</small>
            </button>
          </li>)}
        </ul>}
        {reference.candidate && <div className="location-candidate">
          <strong>선택한 위치 확인</strong>
          <p>{reference.candidate.address || `${reference.candidate.latitude.toFixed(5)}, ${reference.candidate.longitude.toFixed(5)}`}</p>
          <p>지역·공단 검색 결과는 대표 위치일 수 있습니다. 실제 위치와 맞는지 지도에서 확인해 주세요.</p>
          <label>기준점 이름
            <input aria-label="기준점 이름" maxLength={80} value={name} onChange={(event) => setName(event.target.value)} />
          </label>
        </div>}
        {reference.point && !reference.candidate && <>
          <p className="location-reference-note">직선거리 참고용 · 피해 여부나 영향 범위를 뜻하지 않습니다.</p>
          <label className="location-rings-toggle">
            <input type="checkbox" checked={reference.showRings} onChange={(event) => reference.setShowRings(event.target.checked)} />
            1·3·5km 거리 원 표시
          </label>
          <p>전체 {facilities.length}개소 기준 · 5km 이내 {nearby.filter((row) => row.meters <= 5000).length}개소</p>
          {nearby.length === 0 ? <p>좌표를 확인할 수 있는 시설이 없습니다.</p> : <>
            <ol className="location-nearby-list" aria-label="가까운 시설 순서">
              {nearby.slice(0, limit).map(({ facility, meters }) => <li key={facility.id}>
                <button type="button" aria-pressed={reference.targetId === facility.id} onClick={() => {
                  onSelectFacility(facility);
                  setCollapsed(true);
                }}>
                  <FacilityIcon groupId={facility.group_id} />
                  <span><strong>{facility.name}</strong><small>{facility.group_label}
                    {!visibleFacilityIds.has(facility.id) && " · 필터로 숨김 — 선택하면 표시"}
                  </small></span>
                  <b>{formatDistance(meters)}</b>
                </button>
              </li>)}
            </ol>
            <p>가까운 순 {Math.min(limit, nearby.length)} / {nearby.length}개소</p>
            {limit < nearby.length && <button type="button" onClick={() => setLimit(limit + 10)}>주변 시설 10개 더 보기</button>}
          </>}
          {nearby.length < facilities.length && <p>좌표가 유효하지 않은 {facilities.length - nearby.length}개소는 거리 계산에서 제외했습니다.</p>}
        </>}
        {!reference.point && !reference.candidate && <p>위치를 지정하면 전체 소관시설을 가까운 순서로 확인할 수 있습니다.</p>}
        <small>기준점은 현재 화면에서만 사용하며 새로고침하면 지워집니다.</small>
      </div>}
      {!collapsed && reference.candidate && <div className="location-candidate-actions">
        <button type="button" onClick={() => reference.confirm(name)}>이곳을 기준점으로 지정</button>
        <button type="button" onClick={reference.cancel}>취소</button>
      </div>}
    </section>
  );
}
