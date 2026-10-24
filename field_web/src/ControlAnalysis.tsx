import { KakaoMap } from "./KakaoMap";
import { LocationReferencePanel } from "./LocationReferencePanel";

import { WeatherLayerLegend } from "./WeatherLayerControls";

import { uniqueWarningText, WEATHER_LAYER_LABELS } from "./utils";
import { AnalysisMobileFacilityList } from "./controlComponents";
import type { ReadyControlWorkspace } from "./useControlWorkspace";

type Props = Pick<
  ReadyControlWorkspace,
  | "adminToken"
  | "workspace"
  | "reference"
  | "locationOpen"
  | "setLocationOpen"
  | "monitoringMode"
  | "weatherLayerKind"
  | "data"
  | "selectedFacilityIds"
  | "focusedFacilityId"
  | "focusRequest"
  | "setDispatchModalOpen"
  | "weatherLayer"
  | "setLoginModalOpen"
  | "handleSelectWeatherLayer"
  | "prioritySortedFacilities"
  | "toggleFacilitySelection"
  | "selectAllFacilities"
  | "selectAffectedFacilities"
  | "clearFacilitySelection"
  | "handleMapFacilitySelect"
  | "pdfLoading"
  | "handlePdfDownload"
  | "activeWarningCount"
  | "simulation"
  | "actionsBlocked"
>;

export function ControlAnalysis({
  adminToken,
  workspace,
  reference,
  locationOpen,
  setLocationOpen,
  monitoringMode,
  weatherLayerKind,
  data,
  selectedFacilityIds,
  focusedFacilityId,
  focusRequest,
  setDispatchModalOpen,
  weatherLayer,
  setLoginModalOpen,
  handleSelectWeatherLayer,
  prioritySortedFacilities,
  toggleFacilitySelection,
  selectAllFacilities,
  selectAffectedFacilities,
  clearFacilitySelection,
  handleMapFacilitySelect,
  pdfLoading,
  handlePdfDownload,
  activeWarningCount,
  simulation,
  actionsBlocked,
}: Props) {
  return (
    <section className="control-content">
      <div className="analysis-action-bar">
        <div className="selection-stats">
          <strong>선택된 시설: {selectedFacilityIds.size}개소</strong>
          <span>(전체 {data.facilities.length}개소 중)</span>
        </div>
        <div className="selection-buttons">
          <button
            type="button"
            className="secondary-button"
            onClick={selectAffectedFacilities}
          >
            <span className="btn-text-full">
              특보 영향 시설만 선택 ({activeWarningCount})
            </span>
            <span className="btn-text-short">
              영향시설 ({activeWarningCount})
            </span>
          </button>
          <button
            type="button"
            className="secondary-button"
            onClick={selectAllFacilities}
          >
            <span className="btn-text-full">
              전체 선택 ({data.facilities.length})
            </span>
            <span className="btn-text-short">
              전체 ({data.facilities.length})
            </span>
          </button>
          <button
            type="button"
            className="secondary-button"
            onClick={clearFacilitySelection}
          >
            <span className="btn-text-full">선택 해제</span>
            <span className="btn-text-short">해제</span>
          </button>
        </div>
        <div className="action-buttons">
          <button
            type="button"
            className="secondary-button pdf-button"
            onClick={handlePdfDownload}
            disabled={pdfLoading || actionsBlocked}
            title={`선택 상태와 무관하게 전체 ${data?.facilities.length ?? 195}개 소관시설 종합보고서를 다운로드합니다.`}
          >
            {pdfLoading ? (
              "PDF 생성 중..."
            ) : (
              <>
                <span className="btn-text-full">
                  전체 {data?.facilities.length ?? 195}개소 PDF 보고서 ⤓
                </span>
                <span className="btn-text-short">전체 PDF ⤓</span>
              </>
            )}
          </button>

          <button
            type="button"
            className="primary-button dispatch-button"
            onClick={() => {
              if (!adminToken) {
                setLoginModalOpen(true);
                return;
              }
              setDispatchModalOpen(true);
            }}
            disabled={selectedFacilityIds.size === 0 || actionsBlocked}
          >
            <span className="btn-text-full">수동 Telegram 상황전파 📢</span>
            <span className="btn-text-short">수동 상황전파 📢</span>
          </button>
        </div>
        {actionsBlocked && (
          <p className="analysis-action-warning" role="alert">
            KMA 실시간 자료가 정상이 아닌 상태에서는 PDF와 수동 상황전파를
            사용할 수 없습니다.
          </p>
        )}
      </div>

      <div className="analysis-split-layout">
        <div className="analysis-map-card">
          <div className="map-card-header">
            <div>
              <h3>소관시설 관제 지도</h3>
              <small>마커를 클릭하면 대상 목록의 해당 시설이 강조됩니다.</small>
            </div>
            <div
              className="control-layer-buttons"
              role="group"
              aria-label="기상 레이어 선택"
            >
              {(["rainfall", "wind", "temperature"] as const).map((kind) => (
                <button
                  key={kind}
                  type="button"
                  className={`control-layer-chip ${weatherLayerKind === kind ? "active" : ""}`}
                  onClick={() =>
                    handleSelectWeatherLayer(
                      weatherLayerKind === kind ? null : kind,
                    )
                  }
                >
                  {WEATHER_LAYER_LABELS[kind]}
                </button>
              ))}
            </div>
          </div>
          <div className="control-map-container">
            <div className="control-location-panel">
              <button
                className="location-open-button"
                type="button"
                aria-expanded={locationOpen}
                onClick={() => {
                  if (locationOpen) reference.cancel();
                  setLocationOpen(!locationOpen);
                }}
              >
                {locationOpen
                  ? "장소·주소 닫기"
                  : reference.point
                    ? "기준점·주변 시설"
                    : "장소·주소 / 주변 시설"}
              </button>
              {locationOpen && (
                <LocationReferencePanel
                  reference={reference}
                  facilities={data.facilities}
                  visibleFacilityIds={
                    new Set(data.facilities.map((facility) => facility.id))
                  }
                  onSelectFacility={handleMapFacilitySelect}
                />
              )}
            </div>
            <KakaoMap
              facilities={data.facilities}
              referencePoint={reference.point}
              referenceCandidate={reference.candidate}
              referenceTarget={
                data.facilities.find(
                  (facility) => facility.id === reference.targetId,
                ) ?? null
              }
              referenceView={reference.view}
              referenceRings={reference.showRings}
              pickingReference={reference.picking && workspace === "analysis"}
              onPickReference={reference.pick}
              warningZones={data.warning_zones.features}
              warnings={data.warnings}
              isSimulation={simulation}
              selectedFacilityId={focusedFacilityId}
              cctvs={[]}
              selectedCctvId=""
              focusRequest={focusRequest}
              weatherLayer={
                weatherLayer.data?.status !== "ERROR" ? weatherLayer.data : null
              }
              onSelect={handleMapFacilitySelect}
              onSelectGroup={() => {}}
              onSelectCctv={() => {}}
            />
            {weatherLayerKind && (
              <div className="control-map-legend-wrapper">
                <WeatherLayerLegend
                  kind={weatherLayerKind}
                  data={weatherLayer.data}
                  loading={weatherLayer.loading}
                  error={weatherLayer.error}
                  simulation={monitoringMode === "simulation"}
                  onRetry={weatherLayer.retry}
                />
              </div>
            )}
          </div>
        </div>

        <div className="analysis-table-card">
          <div className="table-card-header">
            <h3>전파 대상 시설 선택</h3>
            <small>
              체크박스를 선택하여 수동 전파 및 보고서 대상 범위를 확정하세요.
            </small>
          </div>
          <div className="analysis-table-wrapper">
            <table className="priority-table analysis-table">
              <thead>
                <tr>
                  <th style={{ width: 40 }}>선택</th>
                  <th>위험등급</th>
                  <th>시설명</th>
                  <th>시설 유형</th>
                  <th>발효 특보</th>
                  <th>주소</th>
                </tr>
              </thead>
              <tbody>
                {prioritySortedFacilities.map((facility) => {
                  const isSelected = selectedFacilityIds.has(facility.id);
                  return (
                    <tr
                      key={facility.id}
                      className={`${isSelected ? "row-selected" : ""} ${facility.id === focusedFacilityId ? "row-focused" : ""}`}
                      onClick={() => toggleFacilitySelection(facility.id)}
                    >
                      <td onClick={(e) => e.stopPropagation()}>
                        <input
                          type="checkbox"
                          checked={isSelected}
                          onChange={() => toggleFacilitySelection(facility.id)}
                          aria-label={`${facility.name} 선택`}
                        />
                      </td>
                      <td>
                        <span
                          className="grade-badge"
                          style={{ backgroundColor: facility.grade_color }}
                        >
                          {facility.grade_label}
                        </span>
                      </td>
                      <td>
                        <strong>{facility.name}</strong>
                      </td>
                      <td>{facility.type}</td>
                      <td>
                        <span
                          className={
                            facility.reasons.length > 0
                              ? "warning-tag active"
                              : "warning-tag"
                          }
                        >
                          {uniqueWarningText(facility)}
                        </span>
                      </td>
                      <td>
                        <small>{facility.address}</small>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <AnalysisMobileFacilityList
            facilities={prioritySortedFacilities}
            selectedIds={selectedFacilityIds}
            focusedFacilityId={focusedFacilityId}
            onToggle={toggleFacilitySelection}
          />
        </div>
      </div>
    </section>
  );
}
