import {
  setFacilityQuery,
  useFacilityFilters,
  useFieldFacilitySelection,
  useFieldMapPanels,
} from "./fieldMapState";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useMonitoringData } from "./api";
import { useFacilityCctv, useFacilityWeather } from "./contextApi";
import { CctvModal } from "./CctvModal";
import { FacilitySheet } from "./FacilitySheet";
import { GradeLegend } from "./GradeLegend";
import {
  MobileHeaderPanel,
  MobileMapHeader,
  KMA_OFFICIAL_WARNING_URL,
} from "./MobileMapHeader";
import { MobileBottomSheet } from "./MobileBottomSheet";
import { MobileMapSettings } from "./MobileMapSettings";
import { MobileMapSearch } from "./MobileMapSearch";
import { useMobileLayout } from "./useMobileLayout";
import "./mobileMap.css";
import { KakaoMap } from "./KakaoMap";
import { FacilityIcon } from "./facilityIcons";
import { LocationReferencePanel } from "./LocationReferencePanel";
import { useLocationReference } from "./useLocationReference";
import { WeatherLayerLegend, WeatherLayerSheet } from "./WeatherLayerControls";
import { useWeatherLayer } from "./weatherLayerApi";
import { navigateWithMode } from "./router";
import type { MapViewportRequest, MonitoringMode, NearbyCctv, RiskGrade, WeatherLayerKind } from "./types";

import { filterFacilities, formatElapsedTime, formatReferenceTime, GRADE_DISPLAY_ORDER, recommendedWeatherLayer, requestedMonitoringMode, searchFacilities, uniqueWarningText, WEATHER_LAYER_LABELS } from "./utils";

function setModeQuery(mode: MonitoringMode) {
  const url = new URL(window.location.href);
  if (mode === "simulation") url.searchParams.set("mode", "simulation");
  else url.searchParams.delete("mode");
  window.history.replaceState({}, "", url);
}

export default function App() {
  const isMobile = useMobileLayout();
  const panels = useFieldMapPanels(isMobile);
  const {
    mobilePanel,
    setMobilePanel,
    mobileSearchTab,
    setMobileSearchTab,
    mobileSettingsTab,
    setMobileSettingsTab,
    mobileModalPanelOpen,
    sameLocation,
    setSameLocation,
    filterOpen,
    weatherLayerOpen,
    setFilterOpen,
    setWeatherLayerOpen,
    selectSameLocation,
  } = panels;

  const cctvEnabled = import.meta.env.VITE_CCTV_ENABLED !== "false";
  const [monitoringMode, setMonitoringMode] = useState<MonitoringMode>(() =>
    requestedMonitoringMode(window.location.search),
  );
  const { data, loading, refreshing, error, refresh } =
    useMonitoringData(monitoringMode);

  const [searchMode, setSearchMode] = useState<"facilities" | "location">(
    "facilities",
  );
  const reference = useLocationReference();
  const filters = useFacilityFilters(data);
  const {
    selectedGroups,
    setSelectedGroups,
    selectedGrades,
    setSelectedGrades,
  } = filters;
  const {
    selectedId,
    setSelectedId,
    search,
    setSearch,
    deepLinkNotice,
    focusRequest,
    setFocusRequest,
    selectedCctvId,
    setSelectedCctvId,
    selectFacility,
  } = useFieldFacilitySelection({ data, isMobile, reference, panels, filters });

  const [viewportRequest, setViewportRequest] =
    useState<MapViewportRequest | null>(null);

  const [weatherLayerKind, setWeatherLayerKind] =
    useState<WeatherLayerKind | null>(null);

  // Legacy entry points route to the single mobile settings panel; desktop keeps its sheets.

  const [dismissedNotices, setDismissedNotices] = useState<Set<string>>(
    new Set(),
  );
  const autoSelectedSimulationRef = useRef(false);
  const userSelectedLayerRef = useRef(false);

  const viewportRevision = useRef(0);

  const visibleFacilities = useMemo(
    () =>
      data
        ? filterFacilities(data.facilities, selectedGroups, selectedGrades, "")
        : [],
    [data, selectedGroups, selectedGrades],
  );
  const searchResults = useMemo(
    () =>
      search.trim() && data ? searchFacilities(data.facilities, search, 8) : [],
    [data, search],
  );
  const selectedFacility =
    data?.facilities.find((item) => item.id === selectedId) ?? null;
  const weather = useFacilityWeather(selectedFacility?.id ?? "");
  const weatherLayer = useWeatherLayer(weatherLayerKind, monitoringMode);
  const cctv = useFacilityCctv(selectedFacility?.id ?? "");
  const cctvItems = cctvEnabled ? (cctv.data?.cctvs ?? []) : [];
  const selectedCctv =
    cctvItems.find((item) => item.id === selectedCctvId) ?? null;

  const selectCctv = useCallback((item: NearbyCctv) => {
    setSelectedCctvId(item.id);
  }, []);

  const clearFacility = useCallback(() => {
    reference.clearTarget();
    setSelectedId("");
    setSelectedCctvId("");
    setFacilityQuery("");
    setFocusRequest(null);
    if (isMobile) setMobilePanel("none");
  }, [reference.clearTarget, isMobile]);

  const resetFilters = useCallback(() => {
    if (!data) return;
    setSelectedGroups(new Set(data.groups.map((group) => group.id)));
    setSelectedGrades(new Set(GRADE_DISPLAY_ORDER));
  }, [data]);

  const requestMapViewport = useCallback((kind: MapViewportRequest["kind"]) => {
    setViewportRequest({ kind, revision: ++viewportRevision.current });
  }, []);

  const showAllFacilities = useCallback(() => {
    resetFilters();
    clearFacility();
    setSameLocation([]);
    requestMapViewport("fit-facilities");
  }, [clearFacility, requestMapViewport, resetFilters]);

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (
        event.key !== "Escape" ||
        event.defaultPrevented ||
        mobileModalPanelOpen
      )
        return;
      if (selectedCctvId) {
        setSelectedCctvId("");
        return;
      }
      if (filterOpen) {
        setFilterOpen(false);
        return;
      }
      if (weatherLayerOpen) {
        setWeatherLayerOpen(false);
        return;
      }
      if (sameLocation.length > 0) {
        setSameLocation([]);
        return;
      }
      if (search) {
        setSearch("");
        return;
      }
      if (selectedId) {
        clearFacility();
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [
    selectedCctvId,
    filterOpen,
    weatherLayerOpen,
    sameLocation,
    search,
    selectedId,
    clearFacility,
    mobileModalPanelOpen,
    setFilterOpen,
    setWeatherLayerOpen,
  ]);

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
  // 모의훈련 snapshot 도착 시 특보 기반 추천 레이어 1회 자동 선택
  useEffect(() => {
    if (monitoringMode !== "simulation") {
      autoSelectedSimulationRef.current = false;
      userSelectedLayerRef.current = false;
      return;
    }
    if (!data || data.status.health !== "SIMULATION") return;
    if (!autoSelectedSimulationRef.current && !userSelectedLayerRef.current) {
      autoSelectedSimulationRef.current = true;
      const recommended = recommendedWeatherLayer(data.warnings) ?? "wind";
      setWeatherLayerKind(recommended);
    }
  }, [data, monitoringMode]);

  const handleSelectWeatherLayer = useCallback(
    (kind: WeatherLayerKind | null) => {
      userSelectedLayerRef.current = true;
      setWeatherLayerKind(kind);
    },
    [],
  );

  const changeMonitoringMode = (mode: MonitoringMode) => {
    setModeQuery(mode);
    setMonitoringMode(mode);
    reference.clear();
    setFilterOpen(false);
    setMobilePanel("none");
    if (mode === "live") {
      setWeatherLayerKind(null);
      autoSelectedSimulationRef.current = false;
      userSelectedLayerRef.current = false;
    } else {
      autoSelectedSimulationRef.current = false;
      userSelectedLayerRef.current = false;
    }
  };

  const openMobileHeaderPanel = (panel: "status" | "more") => {
    if (reference.picking || reference.candidate) reference.cancel();
    setMobilePanel(panel);
    setSameLocation([]);
    setSelectedCctvId("");
  };

  const closeMobilePanel = () =>
    setMobilePanel(selectedId ? "facility" : "none");

  const openMobileSearch = () => {
    if (reference.picking || reference.candidate) reference.cancel();
    setSameLocation([]);
    setSelectedCctvId("");
    setMobilePanel("search");
  };

  const openMobileMapSettings = () => {
    if (reference.picking || reference.candidate) reference.cancel();
    setMobilePanel("map-settings");
    setSameLocation([]);
    setSelectedCctvId("");
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
        <button
          className="primary-button"
          type="button"
          onClick={() => void refresh()}
        >
          다시 시도
        </button>
      </main>
    );
  }

  const simulation = data.status.health === "SIMULATION";
  const live = data.status.health === "LIVE";
  const stale = data.status.health === "STALE";
  const feedAvailable = live || simulation || stale;
  const filtersApplied =
    selectedGroups.size !== data.groups.length ||
    data.groups.some((group) => !selectedGroups.has(group.id)) ||
    selectedGrades.size !== GRADE_DISPLAY_ORDER.length ||
    GRADE_DISPLAY_ORDER.some((grade) => !selectedGrades.has(grade));
  return (
    <div className={`app-shell ${isMobile ? "mobile-field-map" : ""}`}>
      {isMobile ? (
        <MobileMapHeader
          data={data}
          mode={monitoringMode}
          additionalNotice={
            !!error ||
            !!deepLinkNotice ||
            !["LIVE", "SIMULATION"].includes(data.status.zone_health)
          }
          panel={mobilePanel}
          onOpen={openMobileHeaderPanel}
        />
      ) : (
        <>
          <header className="app-header">
            <div>
              <span className="brand-mark">K-ECO SAFETY MONITORING</span>
              <h1>현장 안전지도</h1>
            </div>
            <div className="header-actions">
              <button
                className="secondary-button header-control-link"
                type="button"
                onClick={() => navigateWithMode("/control")}
                title="중앙관제 관리자 대시보드로 이동"
              >
                중앙관제 🖥️
              </button>
              <button
                className={`icon-button refresh-button ${refreshing ? "spinning" : ""}`}
                type="button"
                onClick={() => void refresh()}
                disabled={refreshing}
                aria-label="관제 자료 새로고침"
              >
                ↻
              </button>
            </div>
          </header>

          <div
            className={`status-line ${simulation ? "simulation" : live ? "live" : stale ? "stale" : "problem"}`}
            role="status"
          >
            <span className="status-dot" aria-hidden="true" />
            <b>
              {simulation
                ? "모의훈련 자료"
                : `KMA ${live ? "정상" : stale ? "수신 지연" : "조회 불가"}`}
            </b>
            <span>
              · {formatReferenceTime(data.generated_at)} 기준
              {stale && formatElapsedTime(data.generated_at)
                ? ` (${formatElapsedTime(data.generated_at)})`
                : ""}
            </span>
            <a
              className="official-warning-link"
              href={KMA_OFFICIAL_WARNING_URL}
              target="_blank"
              rel="noreferrer"
              aria-label="기상청 실제 특보 발효현황을 새 탭에서 열기"
            >
              기상청 특보 <span aria-hidden="true">↗</span>
            </a>
            <span className="facility-count">
              · 시설 {visibleFacilities.length}개 표시
              {visibleFacilities.length === 0 && (
                <button
                  className="reset-filter-inline"
                  type="button"
                  onClick={resetFilters}
                >
                  (전체 표시)
                </button>
              )}
            </span>
          </div>
        </>
      )}

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

      {(() => {
        const notices: Array<{
          key: string;
          type: "warning" | "error" | "info";
          text: string;
        }> = [];
        if (error && !dismissedNotices.has("error")) {
          notices.push({ key: "error", type: "warning", text: error });
        }
        if (!isMobile && stale && !dismissedNotices.has("stale")) {
          notices.push({
            key: "stale",
            type: "warning",
            text:
              data.status.detail ||
              "KMA 특보 자료 수신이 지연되어 마지막 정상 자료를 표시합니다.",
          });
        }
        if (
          !isMobile &&
          !feedAvailable &&
          !dismissedNotices.has("feed_unavailable")
        ) {
          notices.push({
            key: "feed_unavailable",
            type: "error",
            text:
              data.status.detail ||
              "KMA 특보를 조회하지 못했습니다. 시설 위치만 확인할 수 있습니다.",
          });
        }
        if (
          !isMobile &&
          data.status.zone_health === "FALLBACK" &&
          !dismissedNotices.has("zone_fallback")
        ) {
          notices.push({
            key: "zone_fallback",
            type: "info",
            text: "최신 특보 경계 대신 검증된 내장 경계를 사용 중입니다.",
          });
        }
        if (deepLinkNotice && !dismissedNotices.has("deeplink")) {
          notices.push({ key: "deeplink", type: "info", text: deepLinkNotice });
        }
        if (notices.length === 0) return null;
        return (
          <div className="notice-stack" aria-live="polite">
            {notices.map((n) => (
              <div key={n.key} className={`notice ${n.type}`}>
                <span className="notice-content">{n.text}</span>
                <button
                  type="button"
                  className="notice-dismiss-btn"
                  onClick={() =>
                    setDismissedNotices((prev) => new Set(prev).add(n.key))
                  }
                  aria-label="안내 배너 닫기"
                >
                  ×
                </button>
              </div>
            ))}
          </div>
        );
      })()}

      <main
        className={`map-stage ${selectedFacility ? "has-selection" : ""} ${reference.point && !reference.candidate ? "has-confirmed-reference" : ""} ${reference.point && reference.targetId && selectedFacility ? "has-reference-comparison" : ""}`}
      >
        <KakaoMap
          facilities={visibleFacilities}
          referencePoint={reference.point}
          referenceCandidate={reference.candidate}
          referenceTarget={
            data.facilities.find(
              (facility) => facility.id === reference.targetId,
            ) ?? null
          }
          referenceView={reference.view}
          referenceRings={reference.showRings}
          pickingReference={reference.picking}
          onPickReference={reference.pick}
          warningZones={data.warning_zones.features}
          warnings={data.warnings}
          isSimulation={simulation}
          selectedFacilityId={selectedId}
          cctvs={cctvItems}
          selectedCctvId={selectedCctvId}
          focusRequest={focusRequest}
          viewportRequest={viewportRequest}
          showZoomControl={!isMobile}
          weatherLayer={
            weatherLayer.data?.status !== "ERROR" ? weatherLayer.data : null
          }
          onSelect={(facility) => {
            if (!isMobile || (!reference.candidate && !reference.picking))
              selectFacility(facility);
          }}
          onSelectGroup={(facilities) => {
            if (!isMobile || (!reference.candidate && !reference.picking))
              selectSameLocation(facilities);
          }}
          onSelectCctv={selectCctv}
        />

        {visibleFacilities.length === 0 && !reference.picking && (
          <div className="empty-facilities-overlay" role="status">
            <p>현재 필터 조건에 해당하는 시설이 없습니다.</p>
            <button
              className="primary-button"
              type="button"
              onClick={resetFilters}
            >
              전체 시설 다시 표시
            </button>
          </div>
        )}

        {!isMobile && (
          <div className="map-search-panel">
            <div
              className="location-search-modes"
              role="group"
              aria-label="검색 대상"
            >
              <button
                type="button"
                aria-pressed={searchMode === "facilities"}
                onClick={() => {
                  reference.cancel();
                  setSearchMode("facilities");
                }}
              >
                우리 시설
              </button>
              <button
                type="button"
                aria-pressed={searchMode === "location"}
                onClick={() => {
                  setSearch("");
                  clearFacility();
                  setSearchMode("location");
                }}
              >
                장소·주소{reference.point ? " · 기준점 표시 중" : ""}
              </button>
            </div>
            {searchMode === "location" && (
              <LocationReferencePanel
                reference={reference}
                keyboardActive={!mobileModalPanelOpen}
                facilities={data.facilities}
                visibleFacilityIds={
                  new Set(visibleFacilities.map((facility) => facility.id))
                }
                onSelectFacility={(facility) =>
                  selectFacility(facility, "search")
                }
              />
            )}
            {searchMode === "facilities" && (
              <div className="search-row">
                <label className="search-box">
                  <span aria-hidden="true">⌕</span>
                  <input
                    value={search}
                    onChange={(event) => setSearch(event.target.value)}
                    placeholder="시설명 또는 주소 검색"
                    aria-label="시설명 또는 주소 검색"
                  />
                  {search && (
                    <button
                      type="button"
                      onClick={() => setSearch("")}
                      aria-label="검색어 지우기"
                    >
                      ×
                    </button>
                  )}
                </label>
                {!isMobile && (
                  <button
                    className="filter-button"
                    type="button"
                    onClick={() => setFilterOpen(true)}
                  >
                    <span aria-hidden="true">☷</span>
                    <span>필터</span>
                  </button>
                )}
                {!isMobile && (
                  <button
                    className={`weather-map-button ${weatherLayerKind ? "active" : ""}`}
                    type="button"
                    onClick={() => setWeatherLayerOpen(true)}
                    aria-label="기상 실황 레이어 선택"
                  >
                    <span aria-hidden="true">☁</span>
                    <b>
                      {weatherLayerKind
                        ? WEATHER_LAYER_LABELS[weatherLayerKind]
                        : "기상"}
                    </b>
                  </button>
                )}
              </div>
            )}
            {searchMode === "facilities" && search.trim() && (
              <div className="search-results">
                {searchResults.length ? (
                  searchResults.map((facility) => (
                    <button
                      type="button"
                      key={facility.id}
                      onClick={() => selectFacility(facility, "search")}
                    >
                      <span
                        className="result-grade"
                        style={{ backgroundColor: facility.grade_color }}
                      >
                        {facility.grade_label}
                      </span>
                      <span>
                        <b>{facility.name}</b>
                        <small>{facility.address}</small>
                      </span>
                    </button>
                  ))
                ) : (
                  <p>일치하는 시설이 없습니다.</p>
                )}
              </div>
            )}
            {weatherLayerKind && (
              <WeatherLayerLegend
                kind={weatherLayerKind}
                data={weatherLayer.data}
                loading={weatherLayer.loading}
                error={weatherLayer.error}
                simulation={simulation}
                onRetry={weatherLayer.retry}
              />
            )}
          </div>
        )}

        {isMobile && !reference.picking && !reference.candidate && (
          <div className="mobile-map-top-controls">
            <button
              className="mobile-search-trigger"
              type="button"
              onClick={openMobileSearch}
              aria-label="시설·장소·주소 검색"
            >
              <span aria-hidden="true">⌕</span>
              <span>시설·장소·주소 검색</span>
            </button>
            {reference.point && (
              <div className="mobile-reference-summary">
                <strong title={reference.point.label}>
                  {reference.point.label} · 기준점
                </strong>
                <button type="button" onClick={() => setMobilePanel("nearby")}>
                  주변 시설
                </button>
                <button
                  type="button"
                  onClick={reference.clear}
                  aria-label="기준점 지우기"
                >
                  ×
                </button>
              </div>
            )}
            {weatherLayerKind && (
              <div className="mobile-weather-legend">
                <WeatherLayerLegend
                  kind={weatherLayerKind}
                  data={weatherLayer.data}
                  loading={weatherLayer.loading}
                  error={weatherLayer.error}
                  simulation={simulation}
                  onRetry={weatherLayer.retry}
                />
              </div>
            )}
          </div>
        )}

        {!isMobile && (
          <GradeLegend selectedGrades={selectedGrades} onToggle={toggleGrade} />
        )}

        {isMobile &&
          mobilePanel === "none" &&
          !reference.picking &&
          !reference.candidate && (
            <div className="mobile-map-bottom-controls">
              <button
                className="mobile-show-all-button"
                type="button"
                onClick={showAllFacilities}
              >
                전체 시설
              </button>
              <div
                className="mobile-map-zoom-controls"
                role="group"
                aria-label="지도 확대 축소"
              >
                <button
                  type="button"
                  onClick={() => requestMapViewport("zoom-in")}
                  aria-label="지도 확대"
                >
                  ＋
                </button>
                <button
                  type="button"
                  onClick={() => requestMapViewport("zoom-out")}
                  aria-label="지도 축소"
                >
                  －
                </button>
              </div>
              <button
                className={`mobile-map-settings-trigger ${filtersApplied || weatherLayerKind ? "active" : ""}`}
                type="button"
                onClick={openMobileMapSettings}
                aria-label={`지도 설정${filtersApplied ? `, 필터 적용 ${visibleFacilities.length}개 표시` : ""}${weatherLayerKind ? `, ${WEATHER_LAYER_LABELS[weatherLayerKind]} 표시 중` : ""}`}
              >
                <span>지도 설정</span>
                {(filtersApplied || weatherLayerKind) && (
                  <small>
                    {filtersApplied
                      ? `필터 적용 · ${visibleFacilities.length}개`
                      : ""}
                    {filtersApplied && weatherLayerKind ? " / " : ""}
                    {weatherLayerKind
                      ? WEATHER_LAYER_LABELS[weatherLayerKind]
                      : ""}
                  </small>
                )}
              </button>
            </div>
          )}

        {!reference.picking &&
          !reference.candidate &&
          ((!isMobile && (searchMode === "facilities" || reference.targetId)) ||
            (isMobile && mobilePanel === "facility" && selectedFacility)) && (
            <FacilitySheet
              facility={selectedFacility}
              compact={isMobile}
              simulation={simulation}
              cctvEnabled={cctvEnabled}
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
          )}
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

      {!isMobile && weatherLayerOpen && (
        <WeatherLayerSheet
          active={weatherLayerKind}
          simulation={simulation}
          onSelect={(kind) => {
            handleSelectWeatherLayer(kind);
            setWeatherLayerOpen(false);
          }}
          onClose={() => setWeatherLayerOpen(false)}
        />
      )}

      {!isMobile && filterOpen && (
        <div
          className="modal-backdrop"
          role="presentation"
          onMouseDown={() => setFilterOpen(false)}
        >
          <section
            className="filter-sheet"
            role="dialog"
            aria-modal="true"
            aria-labelledby="filter-title"
            onMouseDown={(event) => event.stopPropagation()}
          >
            <span className="sheet-handle" aria-hidden="true" />
            <div className="filter-title-row">
              <div>
                <h2 id="filter-title">시설 유형</h2>
                <p>지도에 표시할 시설을 선택합니다.</p>
              </div>
              <button
                className="icon-button"
                type="button"
                onClick={() => setFilterOpen(false)}
                aria-label="필터 닫기"
              >
                ×
              </button>
            </div>
            <div className="group-options">
              {data.groups.map((group) => (
                <label key={group.id}>
                  <input
                    type="checkbox"
                    checked={selectedGroups.has(group.id)}
                    onChange={() => toggleGroup(group.id)}
                  />
                  <FacilityIcon
                    groupId={group.id}
                    size={16}
                    className="group-option-icon"
                  />
                  <span>{group.label}</span>
                  <b>{group.count}</b>
                </label>
              ))}
            </div>
            {!isMobile && (
              <div
                className={`training-option ${monitoringMode === "simulation" ? "active" : ""}`}
              >
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
                  onClick={() =>
                    changeMonitoringMode(
                      monitoringMode === "simulation" ? "live" : "simulation",
                    )
                  }
                >
                  {monitoringMode === "simulation"
                    ? "실시간 화면으로 돌아가기"
                    : "모의훈련 화면 보기"}
                </button>
              </div>
            )}
            <div className="filter-actions">
              <button
                type="button"
                onClick={() =>
                  setSelectedGroups(
                    new Set(data.groups.map((group) => group.id)),
                  )
                }
              >
                전체 선택
              </button>
              <button
                className="primary-button"
                type="button"
                onClick={() => setFilterOpen(false)}
              >
                확인
              </button>
            </div>
          </section>
        </div>
      )}

      {sameLocation.length > 0 && !isMobile && (
        <div
          className="modal-backdrop"
          role="presentation"
          onMouseDown={() => setSameLocation([])}
        >
          <section
            className="same-location-sheet"
            role="dialog"
            aria-modal="true"
            aria-labelledby="same-location-title"
            onMouseDown={(event) => event.stopPropagation()}
          >
            <span className="sheet-handle" aria-hidden="true" />
            <div className="filter-title-row">
              <div>
                <h2 id="same-location-title">같은 위치의 시설</h2>
                <p>확인할 시설을 선택하세요.</p>
              </div>
              <button
                className="icon-button"
                type="button"
                onClick={() => setSameLocation([])}
                aria-label="시설 목록 닫기"
              >
                ×
              </button>
            </div>
            <div className="same-location-options">
              {sameLocation.map((facility) => (
                <button
                  type="button"
                  key={facility.id}
                  onClick={() => selectFacility(facility, "same_location")}
                >
                  <span
                    className="grade-badge"
                    style={{ backgroundColor: facility.grade_color }}
                  >
                    {facility.grade_label}
                  </span>
                  <span>
                    <b>{facility.name}</b>
                    <small>
                      {facility.type} · {uniqueWarningText(facility)}
                    </small>
                  </span>
                </button>
              ))}
            </div>
          </section>
        </div>
      )}
      {isMobile &&
        sameLocation.length > 0 &&
        mobilePanel === "same-location" && (
          <MobileBottomSheet
            title="같은 위치의 시설"
            onClose={() => {
              setSameLocation([]);
              closeMobilePanel();
            }}
          >
            <p className="mobile-sheet-intro">확인할 시설을 선택하세요.</p>
            <div className="same-location-options">
              {sameLocation.map((facility) => (
                <button
                  type="button"
                  key={facility.id}
                  onClick={() => selectFacility(facility, "same_location")}
                >
                  <span
                    className="grade-badge"
                    style={{ backgroundColor: facility.grade_color }}
                  >
                    {facility.grade_label}
                  </span>
                  <span>
                    <b>{facility.name}</b>
                    <small>
                      {facility.type} · {uniqueWarningText(facility)}
                    </small>
                  </span>
                </button>
              ))}
            </div>
          </MobileBottomSheet>
        )}
      {isMobile && (
        <MobileMapSearch
          panel={mobilePanel}
          tab={mobileSearchTab}
          facilityQuery={search}
          facilityResults={searchResults}
          facilities={data.facilities}
          visibleFacilityIds={
            new Set(visibleFacilities.map((facility) => facility.id))
          }
          reference={reference}
          onSelectTab={setMobileSearchTab}
          onFacilityQuery={setSearch}
          onSelectFacility={(facility) => selectFacility(facility, "search")}
          onPanelChange={setMobilePanel}
          onClose={closeMobilePanel}
        />
      )}
      {isMobile && (mobilePanel === "status" || mobilePanel === "more") && (
        <MobileHeaderPanel
          panel={mobilePanel}
          data={data}
          mode={monitoringMode}
          refreshing={refreshing}
          error={error || ""}
          deepLinkNotice={deepLinkNotice}
          onClose={closeMobilePanel}
          onRefresh={() => void refresh()}
          onControl={() => {
            setMobilePanel("none");
            navigateWithMode("/control");
          }}
          onChangeMode={changeMonitoringMode}
        />
      )}
      {isMobile && mobilePanel === "map-settings" && (
        <MobileMapSettings
          tab={mobileSettingsTab}
          groups={data.groups}
          selectedGroups={selectedGroups}
          selectedGrades={selectedGrades}
          visibleCount={visibleFacilities.length}
          totalCount={data.facilities.length}
          weatherKind={weatherLayerKind}
          weatherData={weatherLayer.data}
          weatherLoading={weatherLayer.loading}
          weatherError={weatherLayer.error}
          simulation={simulation}
          onSelectTab={setMobileSettingsTab}
          onToggleGroup={toggleGroup}
          onToggleGrade={toggleGrade}
          onResetFilters={resetFilters}
          onSelectWeather={handleSelectWeatherLayer}
          onClose={closeMobilePanel}
        />
      )}
    </div>
  );
}
