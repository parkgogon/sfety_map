import { ControlOverview } from "./ControlOverview";
import { ControlAnalysis } from "./ControlAnalysis";
import { ControlHistory } from "./ControlHistory";
import { useControlWorkspace } from "./useControlWorkspace";

export {
  monitoringOutputsAvailable,
  resolveSelectedFacilityScope,
} from "./controlModel";
export { AnalysisMobileFacilityList } from "./controlComponents";

import { ManualDispatchModal } from "./ManualDispatchModal";

import { getBuildLabel } from "./buildInfo";
import { navigateWithMode } from "./router";

import { formatReferenceTime } from "./utils";



const KMA_OFFICIAL_WARNING_URL =
  "https://www.weather.go.kr/w/special-report/overall.do";

export default function ControlApp() {
  const {
    adminToken,
    passwordInput,
    setPasswordInput,
    authError,
    authLoading,
    handleLogin,
    handleLogout,
    workspace,
    setWorkspace,
    reference,
    locationOpen,
    setLocationOpen,
    monitoringMode,
    weatherLayerKind,
    data,
    loading,
    refreshing,
    error,
    refresh,
    selectedFacilityIds,
    focusedFacilityId,
    focusRequest,
    dispatchModalOpen,
    setDispatchModalOpen,
    dispatchSuccessId,
    setDispatchSuccessId,
    search,
    setSearch,
    selectedGrade,
    setSelectedGrade,
    selectedGroup,
    setSelectedGroup,
    dateRange,
    setDateRange,
    fromDate,
    toDate,
    overview,
    metrics,
    events,
    weatherLayer,
    loginModalOpen,
    setLoginModalOpen,
    handleSelectWeatherLayer,
    changeMonitoringMode,
    prioritySortedFacilities,
    filteredPriorityFacilities,
    toggleFacilitySelection,
    selectAllFacilities,
    selectAffectedFacilities,
    clearFacilitySelection,
    selectedFacilityScope,
    handleMapFacilitySelect,
    pdfLoading,
    handlePdfDownload,
    gradeCounts,
    activeWarningCount,
    simulation,
    live,
    stale,
    actionsBlocked,
  } = useControlWorkspace();
  if (loading && !data) {
    return (
      <main className="initial-state">
        <div className="brand-mark">K-ECO SAFETY MONITORING</div>
        <div className="loading-ring" aria-label="중앙관제 자료 불러오는 중" />
        <strong>중앙 관제 화면을 준비하고 있습니다</strong>
      </main>
    );
  }

  if (!data) {
    return (
      <main className="initial-state error-state">
        <div className="brand-mark">K-ECO SAFETY MONITORING</div>
        <strong>관제 자료를 불러오지 못했습니다</strong>
        <span>{error || "네트워크 상태를 확인한 뒤 다시 시도해 주세요."}</span>
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

  return (
    <div className="control-shell">
      <header className="control-header">
        <div className="control-brand">
          <span className="brand-mark">K-ECO SAFETY MONITORING</span>
          <div className="control-title-row">
            <h1>중앙 관제</h1>
            <span
              className="build-info-label"
              title={`웹 배포 버전: ${getBuildLabel()}`}
            >
              {getBuildLabel()}
            </span>
          </div>
        </div>
        <div className="control-header-actions">
          {adminToken ? (
            <button
              className="secondary-button auth-status-btn logged-in"
              type="button"
              onClick={handleLogout}
              title="관리자 인증 해제 (로그아웃)"
            >
              🔓 <span className="btn-text-full">관리자 로그아웃</span>
              <span className="btn-text-short">로그아웃</span>
            </button>
          ) : (
            <button
              className="primary-button auth-status-btn"
              type="button"
              onClick={() => setLoginModalOpen(true)}
              title="관리자 인증 로그인"
            >
              🔒 <span className="btn-text-full">관리자 인증</span>
              <span className="btn-text-short">인증</span>
            </button>
          )}
          <button
            className="secondary-button"
            type="button"
            onClick={() => navigateWithMode("/settings")}
            title="위험도 정책 기준 설정"
          >
            ⚙ <span className="btn-text-full">위험도 설정</span>
            <span className="btn-text-short">설정</span>
          </button>
          <button
            className="secondary-button"
            type="button"
            onClick={() => navigateWithMode("/")}
            title="스마트폰 현장 안전지도로 이동"
          >
            <span className="btn-text-full">현장 지도 보기 ↗</span>
            <span className="btn-text-short">현장지도 ↗</span>
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

      {/* 상태 스트립 */}
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
        <span>· {formatReferenceTime(data.generated_at)} 기준</span>
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
          · 총 {data?.facilities.length ?? 195}개소 중{" "}
          <b>{activeWarningCount}개소</b> 특보 영향
        </span>
      </div>

      {dispatchSuccessId && (
        <div className="dispatch-success-banner" role="status">
          <span>
            ✓ 시설담당자 그룹에 상황전파를 성공적으로 발송했습니다. (요청 ID:{" "}
            {dispatchSuccessId})
          </span>
          <button type="button" onClick={() => setDispatchSuccessId(null)}>
            ×
          </button>
        </div>
      )}

      {/* 워크스페이스 탭 네비게이션 */}
      <nav
        className="control-workspace-tabs"
        aria-label="중앙관제 작업 화면 선택"
      >
        <button
          type="button"
          className={`tab-button ${workspace === "overview" ? "active" : ""}`}
          onClick={() => {
            reference.cancel();
            setWorkspace("overview");
          }}
        >
          운영 상황
        </button>
        <button
          type="button"
          className={`tab-button ${workspace === "analysis" ? "active" : ""}`}
          onClick={() => setWorkspace("analysis")}
        >
          대상 분석·전파
        </button>
        <button
          type="button"
          className={`tab-button ${workspace === "history" ? "active" : ""}`}
          onClick={() => {
            reference.cancel();
            setWorkspace("history");
          }}
        >
          실적·이력
        </button>
      </nav>

      {/* 탭 1: 운영 상황 */}
      {workspace === "overview" && (
        <ControlOverview
          monitoringMode={monitoringMode}
          data={data}
          search={search}
          setSearch={setSearch}
          selectedGrade={selectedGrade}
          setSelectedGrade={setSelectedGrade}
          selectedGroup={selectedGroup}
          setSelectedGroup={setSelectedGroup}
          overview={overview}
          changeMonitoringMode={changeMonitoringMode}
          filteredPriorityFacilities={filteredPriorityFacilities}
          gradeCounts={gradeCounts}
          activeWarningCount={activeWarningCount}
        />
      )}

      {/* 탭 2: 대상 분석·전파 */}
      {workspace === "analysis" && (
        <ControlAnalysis
          adminToken={adminToken}
          workspace={workspace}
          reference={reference}
          locationOpen={locationOpen}
          setLocationOpen={setLocationOpen}
          monitoringMode={monitoringMode}
          weatherLayerKind={weatherLayerKind}
          data={data}
          selectedFacilityIds={selectedFacilityIds}
          focusedFacilityId={focusedFacilityId}
          focusRequest={focusRequest}
          setDispatchModalOpen={setDispatchModalOpen}
          weatherLayer={weatherLayer}
          setLoginModalOpen={setLoginModalOpen}
          handleSelectWeatherLayer={handleSelectWeatherLayer}
          prioritySortedFacilities={prioritySortedFacilities}
          toggleFacilitySelection={toggleFacilitySelection}
          selectAllFacilities={selectAllFacilities}
          selectAffectedFacilities={selectAffectedFacilities}
          clearFacilitySelection={clearFacilitySelection}
          handleMapFacilitySelect={handleMapFacilitySelect}
          pdfLoading={pdfLoading}
          handlePdfDownload={handlePdfDownload}
          activeWarningCount={activeWarningCount}
          simulation={simulation}
          actionsBlocked={actionsBlocked}
        />
      )}

      {/* 관리자 인증 모달 */}
      {loginModalOpen && (
        <div
          className="modal-backdrop"
          onClick={() => setLoginModalOpen(false)}
        >
          <div
            className="modal-card admin-login-modal"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="modal-header">
              <h2>🔒 관리자 인증</h2>
              <button
                type="button"
                className="close-button"
                onClick={() => setLoginModalOpen(false)}
              >
                ×
              </button>
            </div>
            <p className="modal-description">
              수동 상황전파, PDF 초동보고서 다운로드 및 발송 이력을 관리하려면
              관리자 비밀번호를 입력해 주세요.
            </p>
            <form
              onSubmit={async (e) => {
                await handleLogin(e);
              }}
              className="login-form"
            >
              <input
                type="password"
                placeholder="관리자 비밀번호"
                value={passwordInput}
                onChange={(e) => setPasswordInput(e.target.value)}
                disabled={authLoading}
                autoFocus
              />
              <div
                className="modal-actions"
                style={{
                  display: "flex",
                  gap: "8px",
                  marginTop: "12px",
                  justifyContent: "flex-end",
                }}
              >
                <button
                  type="button"
                  className="secondary-button"
                  onClick={() => setLoginModalOpen(false)}
                >
                  취소
                </button>
                <button
                  className="primary-button"
                  type="submit"
                  disabled={authLoading}
                >
                  {authLoading ? "인증 중..." : "인증 확인"}
                </button>
              </div>
            </form>
            {authError && (
              <div className="notice error" style={{ marginTop: 12 }}>
                {authError}
              </div>
            )}
          </div>
        </div>
      )}

      {/* 수동 전파 모달 */}
      {dispatchModalOpen && (
        <ManualDispatchModal
          facilities={selectedFacilityScope.facilities}
          adminToken={adminToken}
          monitoringMode={monitoringMode}
          onClose={() => setDispatchModalOpen(false)}
          onSuccess={(id) => {
            setDispatchModalOpen(false);
            setDispatchSuccessId(id);
          }}
        />
      )}

      {/* 탭 3: 실적·이력 */}
      {workspace === "history" && (
        <ControlHistory
          adminToken={adminToken}
          passwordInput={passwordInput}
          setPasswordInput={setPasswordInput}
          authError={authError}
          authLoading={authLoading}
          handleLogin={handleLogin}
          handleLogout={handleLogout}
          dateRange={dateRange}
          setDateRange={setDateRange}
          fromDate={fromDate}
          toDate={toDate}
          metrics={metrics}
          events={events}
        />
      )}
    </div>
  );
}
