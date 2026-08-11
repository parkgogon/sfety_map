import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useMonitoringData } from "./api";
import { useFacilityCctv, useFacilityWeather } from "./contextApi";
import { CctvModal } from "./CctvModal";
import { FacilitySheet } from "./FacilitySheet";
import { KakaoMap } from "./KakaoMap";
import type {
  Facility,
  MapFocusRequest,
  MonitoringMode,
  NearbyCctv,
  RiskGrade,
} from "./types";
import {
  type FacilitySelectionSource,
  filterFacilities,
  formatReferenceTime,
  GRADE_COLORS,
  GRADE_LABELS,
  GRADE_ORDER,
  requestedFacilityId,
  requestedMonitoringMode,
  shouldZoomForSelection,
  uniqueWarningText,
} from "./utils";

function setFacilityQuery(facilityId: string) {
  const url = new URL(window.location.href);
  if (facilityId) url.searchParams.set("facility_id", facilityId);
  else url.searchParams.delete("facility_id");
  window.history.replaceState({}, "", url);
}

function setModeQuery(mode: MonitoringMode) {
  const url = new URL(window.location.href);
  if (mode === "simulation") url.searchParams.set("mode", "simulation");
  else url.searchParams.delete("mode");
  window.history.replaceState({}, "", url);
}

export default function App() {
  const [monitoringMode, setMonitoringMode] = useState<MonitoringMode>(() =>
    requestedMonitoringMode(window.location.search),
  );
  const { data, loading, refreshing, error, refresh } = useMonitoringData(monitoringMode);
  const [selectedGroups, setSelectedGroups] = useState<Set<string>>(new Set());
  const [selectedGrades, setSelectedGrades] = useState<Set<RiskGrade>>(new Set(GRADE_ORDER));
  const [selectedId, setSelectedId] = useState("");
  const [search, setSearch] = useState("");
  const [filterOpen, setFilterOpen] = useState(false);
  const [sameLocation, setSameLocation] = useState<Facility[]>([]);
  const [deepLinkNotice, setDeepLinkNotice] = useState("");
  const [focusRequest, setFocusRequest] = useState<MapFocusRequest | null>(null);
  const [selectedCctvId, setSelectedCctvId] = useState("");
  const initializedGroups = useRef(false);
  const handledDeepLink = useRef(false);
  const focusRevision = useRef(0);

  const selectFacility = useCallback((
    facility: Facility,
    source: FacilitySelectionSource = "marker",
  ) => {
    setSelectedId(facility.id);
    setSearch("");
    setSameLocation([]);
    setSelectedCctvId("");
    setFacilityQuery(facility.id);
    focusRevision.current += 1;
    setFocusRequest({
      latitude: facility.latitude,
      longitude: facility.longitude,
      zoom: shouldZoomForSelection(source),
      revision: focusRevision.current,
    });
  }, []);

  useEffect(() => {
    if (!data || initializedGroups.current) return;
    setSelectedGroups(new Set(data.groups.map((group) => group.id)));
    initializedGroups.current = true;
  }, [data]);

  useEffect(() => {
    if (!data || handledDeepLink.current) return;
    handledDeepLink.current = true;
    const requested = requestedFacilityId(window.location.search);
    if (!requested) return;
    const facility = data.facilities.find((item) => item.id === requested);
    if (!facility) {
      setDeepLinkNotice("요청한 시설을 찾을 수 없어 전체 지도를 표시합니다.");
      setFacilityQuery("");
      return;
    }
    setSelectedGroups((current) => new Set([...current, facility.group_id]));
    setSelectedGrades((current) => new Set([...current, facility.grade]));
    selectFacility(facility, "deep_link");
  }, [data, selectFacility]);

  const visibleFacilities = useMemo(
    () => data ? filterFacilities(data.facilities, selectedGroups, selectedGrades, "") : [],
    [data, selectedGroups, selectedGrades],
  );
  const searchResults = useMemo(
    () => search.trim() && data
      ? filterFacilities(data.facilities, selectedGroups, selectedGrades, search).slice(0, 8)
      : [],
    [data, search, selectedGroups, selectedGrades],
  );
  const selectedFacility = data?.facilities.find((item) => item.id === selectedId) ?? null;
  const weather = useFacilityWeather(selectedFacility?.id ?? "");
  const cctv = useFacilityCctv(selectedFacility?.id ?? "");
  const cctvItems = cctv.data?.cctvs ?? [];
  const selectedCctv = cctvItems.find((item) => item.id === selectedCctvId) ?? null;

  const selectCctv = useCallback((item: NearbyCctv) => {
    setSelectedCctvId(item.id);
  }, []);

  const clearFacility = useCallback(() => {
    setSelectedId("");
    setSelectedCctvId("");
    setFacilityQuery("");
  }, []);

  const toggleGroup = (id: string) => {
    setSelectedGroups((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };
  const toggleGrade = (grade: RiskGrade) => {
    setSelectedGrades((current) => {
      const next = new Set(current);
      if (next.has(grade)) next.delete(grade);
      else next.add(grade);
      return next;
    });
  };
  const changeMonitoringMode = (mode: MonitoringMode) => {
    setModeQuery(mode);
    setMonitoringMode(mode);
    setFilterOpen(false);
  };

  if (loading && !data) {
    return (
      <main className="initial-state">
        <div className="brand-mark">K-ECO SAFETY MONITORING</div>
        <div className="loading-ring" aria-label="관제 자료 불러오는 중" />
        <strong>현장 지도를 준비하고 있습니다</strong>
      </main>
    );
  }

  if (!data) {
    return (
      <main className="initial-state error-state">
        <div className="brand-mark">K-ECO SAFETY MONITORING</div>
        <strong>관제 자료를 불러오지 못했습니다</strong>
        <span>네트워크 상태를 확인한 뒤 다시 시도해 주세요.</span>
        <button className="primary-button" type="button" onClick={() => void refresh()}>다시 시도</button>
      </main>
    );
  }

  const simulation = data.status.health === "SIMULATION";
  const live = data.status.health === "LIVE";
  const feedAvailable = live || simulation;
  return (
    <div className="app-shell">
      <header className="app-header">
        <div>
          <span className="brand-mark">K-ECO SAFETY MONITORING</span>
          <h1>현장 안전지도</h1>
        </div>
        <button
          className={`icon-button refresh-button ${refreshing ? "spinning" : ""}`}
          type="button"
          onClick={() => void refresh()}
          disabled={refreshing}
          aria-label="관제 자료 새로고침"
        >
          ↻
        </button>
      </header>

      <div
        className={`status-line ${simulation ? "simulation" : live ? "live" : "problem"}`}
        role="status"
      >
        <span className="status-dot" aria-hidden="true" />
        <b>{simulation ? "모의훈련 자료" : `KMA ${live ? "정상" : "조회 불가"}`}</b>
        <span>· {formatReferenceTime(data.generated_at)} 기준</span>
        <span className="facility-count">· 시설 {visibleFacilities.length}개 표시</span>
      </div>

      {monitoringMode === "simulation" && (
        <div className="simulation-banner" role="alert">
          <div>
            <strong>모의훈련</strong>
            <span>실제 상황이 아닙니다</span>
          </div>
          <button type="button" onClick={() => changeMonitoringMode("live")}>
            실시간으로 돌아가기
          </button>
        </div>
      )}

      {(error || !feedAvailable || data.status.zone_health === "FALLBACK" || deepLinkNotice) && (
        <div className="notice-stack" aria-live="polite">
          {error && <div className="notice warning">{error}</div>}
          {!feedAvailable && <div className="notice error">{data.status.detail || "KMA 특보를 조회하지 못했습니다. 시설 위치만 확인할 수 있습니다."}</div>}
          {data.status.zone_health === "FALLBACK" && <div className="notice info">최신 특보 경계 대신 검증된 내장 경계를 사용 중입니다.</div>}
          {deepLinkNotice && <div className="notice info">{deepLinkNotice}</div>}
        </div>
      )}

      <main className={`map-stage ${selectedFacility ? "has-selection" : ""}`}>
        <KakaoMap
          facilities={visibleFacilities}
          warningZones={data.warning_zones.features}
          selectedFacilityId={selectedId}
          cctvs={cctvItems}
          selectedCctvId={selectedCctvId}
          focusRequest={focusRequest}
          onSelect={selectFacility}
          onSelectGroup={setSameLocation}
          onSelectCctv={selectCctv}
        />

        <div className="map-search-panel">
          <div className="search-row">
            <label className="search-box">
              <span aria-hidden="true">⌕</span>
              <input
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder="시설명 또는 주소 검색"
                aria-label="시설명 또는 주소 검색"
              />
              {search && <button type="button" onClick={() => setSearch("")} aria-label="검색어 지우기">×</button>}
            </label>
            <button className="filter-button" type="button" onClick={() => setFilterOpen(true)}>
              <span aria-hidden="true">☷</span>
              <span>필터</span>
            </button>
          </div>
          {search.trim() && (
            <div className="search-results">
              {searchResults.length ? searchResults.map((facility) => (
                <button type="button" key={facility.id} onClick={() => selectFacility(facility, "search")}>
                  <span className="result-grade" style={{ backgroundColor: facility.grade_color }}>{facility.grade_label}</span>
                  <span><b>{facility.name}</b><small>{facility.address}</small></span>
                </button>
              )) : <p>현재 필터에서 일치하는 시설이 없습니다.</p>}
            </div>
          )}
        </div>

        <div className="grade-legend" aria-label="위험등급 지도 표시 설정">
          {GRADE_ORDER.map((grade) => (
            <button
              type="button"
              key={grade}
              className={selectedGrades.has(grade) ? "active" : ""}
              onClick={() => toggleGrade(grade)}
              aria-pressed={selectedGrades.has(grade)}
            >
              <span style={{ backgroundColor: GRADE_COLORS[grade] }} />
              {GRADE_LABELS[grade]}
            </button>
          ))}
        </div>

        <FacilitySheet
          facility={selectedFacility}
          simulation={simulation}
          weather={weather.data}
          weatherLoading={weather.loading}
          weatherError={weather.error}
          onRetryWeather={weather.retry}
          cctv={cctv.data}
          cctvLoading={cctv.loading}
          cctvError={cctv.error}
          cctvCooldownUntil={cctv.cooldownUntil}
          onLoadCctv={cctv.load}
          onSelectCctv={selectCctv}
          onClose={clearFacility}
        />
      </main>

      <CctvModal
        cctv={selectedCctv}
        feed={cctv.data}
        simulation={simulation}
        loading={cctv.loading}
        cooldownUntil={cctv.cooldownUntil}
        onRefresh={cctv.load}
        onClose={() => setSelectedCctvId("")}
      />

      {filterOpen && (
        <div className="modal-backdrop" role="presentation" onMouseDown={() => setFilterOpen(false)}>
          <section className="filter-sheet" role="dialog" aria-modal="true" aria-labelledby="filter-title" onMouseDown={(event) => event.stopPropagation()}>
            <span className="sheet-handle" aria-hidden="true" />
            <div className="filter-title-row">
              <div><h2 id="filter-title">시설 유형</h2><p>지도에 표시할 시설을 선택합니다.</p></div>
              <button className="icon-button" type="button" onClick={() => setFilterOpen(false)} aria-label="필터 닫기">×</button>
            </div>
            <div className="group-options">
              {data.groups.map((group) => (
                <label key={group.id}>
                  <input type="checkbox" checked={selectedGroups.has(group.id)} onChange={() => toggleGroup(group.id)} />
                  <span>{group.label}</span><b>{group.count}</b>
                </label>
              ))}
            </div>
            <div className={`training-option ${monitoringMode === "simulation" ? "active" : ""}`}>
              <div>
                <strong>화면 확인</strong>
                <span>
                  {monitoringMode === "simulation"
                    ? "현재 고정된 훈련 특보를 표시하고 있습니다."
                    : "특보 발생 시 화면을 미리 확인합니다."}
                </span>
              </div>
              <button
                type="button"
                onClick={() => changeMonitoringMode(
                  monitoringMode === "simulation" ? "live" : "simulation",
                )}
              >
                {monitoringMode === "simulation"
                  ? "실시간 화면으로 돌아가기"
                  : "모의훈련 화면 보기"}
              </button>
            </div>
            <div className="filter-actions">
              <button type="button" onClick={() => setSelectedGroups(new Set(data.groups.map((group) => group.id)))}>전체 선택</button>
              <button className="primary-button" type="button" onClick={() => setFilterOpen(false)}>지도에 적용</button>
            </div>
          </section>
        </div>
      )}

      {sameLocation.length > 0 && (
        <div className="modal-backdrop" role="presentation" onMouseDown={() => setSameLocation([])}>
          <section className="same-location-sheet" role="dialog" aria-modal="true" aria-labelledby="same-location-title" onMouseDown={(event) => event.stopPropagation()}>
            <span className="sheet-handle" aria-hidden="true" />
            <div className="filter-title-row">
              <div><h2 id="same-location-title">같은 위치의 시설</h2><p>확인할 시설을 선택하세요.</p></div>
              <button className="icon-button" type="button" onClick={() => setSameLocation([])} aria-label="시설 목록 닫기">×</button>
            </div>
            <div className="same-location-options">
              {sameLocation.map((facility) => (
                <button type="button" key={facility.id} onClick={() => selectFacility(facility, "same_location")}>
                  <span className="grade-badge" style={{ backgroundColor: facility.grade_color }}>{facility.grade_label}</span>
                  <span><b>{facility.name}</b><small>{facility.type} · {uniqueWarningText(facility)}</small></span>
                </button>
              ))}
            </div>
          </section>
        </div>
      )}
    </div>
  );
}
