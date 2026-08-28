import { useCallback, useEffect, useMemo, useState } from "react";
import { useMonitoringData } from "./api";
import {
  checkAdminSession,
  downloadReportPdf,
  getReportPdfUrl,
  getStoredAdminToken,
  logoutAdmin,
  setStoredAdminToken,
  useAlertEvents,
  useAlertMetrics,
  useControlOverview,
  verifyAdminPassword,
} from "./controlApi";
import { KakaoMap } from "./KakaoMap";
import { ManualDispatchModal } from "./ManualDispatchModal";
import { navigate } from "./router";
import type { Facility, MapFocusRequest, MonitoringMode, RiskGrade } from "./types";
import {
  filterFacilities,
  formatReferenceTime,
  GRADE_COLORS,
  GRADE_DISPLAY_ORDER,
  GRADE_LABELS,
  GRADE_PRIORITY_ORDER,
  requestedMonitoringMode,
  uniqueWarningText,
} from "./utils";

type ControlWorkspace = "overview" | "analysis" | "history";

const KMA_OFFICIAL_WARNING_URL = "https://www.weather.go.kr/w/special-report/overall.do";

function todayYMD(): string {
  const now = new Date();
  return now.toISOString().slice(0, 10);
}

function daysAgoYMD(days: number): string {
  const date = new Date();
  date.setDate(date.getDate() - days);
  return date.toISOString().slice(0, 10);
}

export default function ControlApp() {
  const [workspace, setWorkspace] = useState<ControlWorkspace>("overview");
  const [monitoringMode, setMonitoringMode] = useState<MonitoringMode>(() =>
    requestedMonitoringMode(typeof window !== "undefined" ? window.location.search : ""),
  );
  const { data, loading, refreshing, error, refresh } = useMonitoringData(monitoringMode);

  // 관리자 인증
  const [adminToken, setAdminToken] = useState<string>(getStoredAdminToken);
  const [passwordInput, setPasswordInput] = useState("");
  const [authError, setAuthError] = useState<string | null>(null);
  const [authLoading, setAuthLoading] = useState(false);

  // 세션 자동 확인
  useEffect(() => {
    let active = true;
    void checkAdminSession(adminToken).then((status) => {
      if (!active) return;
      if (status.authenticated && !adminToken) {
        setAdminToken("active-session");
      } else if (!status.authenticated && adminToken) {
        setAdminToken("");
        setStoredAdminToken("");
      }
    });
    return () => {
      active = false;
    };
  }, [adminToken]);

  // 대상 분석 다중 선택
  const [selectedFacilityIds, setSelectedFacilityIds] = useState<Set<string>>(new Set());
  const [focusedFacilityId, setFocusedFacilityId] = useState("");
  const [focusRequest, setFocusRequest] = useState<MapFocusRequest | null>(null);
  const [dispatchModalOpen, setDispatchModalOpen] = useState(false);
  const [dispatchSuccessId, setDispatchSuccessId] = useState<string | null>(null);

  // 우선순위 목록 필터/검색
  const [search, setSearch] = useState("");
  const [selectedGrade, setSelectedGrade] = useState<string>("ALL");
  const [selectedGroup, setSelectedGroup] = useState<string>("ALL");

  // 실적/이력 기간
  const [dateRange, setDateRange] = useState<"today" | "7d" | "30d">("today");
  const fromDate = useMemo(() => {
    if (dateRange === "today") return todayYMD();
    if (dateRange === "7d") return daysAgoYMD(7);
    return daysAgoYMD(30);
  }, [dateRange]);
  const toDate = useMemo(() => todayYMD(), []);

  const overview = useControlOverview(adminToken);
  const metrics = useAlertMetrics(adminToken, fromDate, toDate);
  const events = useAlertEvents(adminToken, fromDate, toDate);


  // 초기 특보 영향 시설 자동 선택
  useEffect(() => {
    if (!data) return;
    const affected = data.facilities
      .filter((f) => f.grade === "HIGH" || f.grade === "MEDIUM" || f.grade === "LOW")
      .map((f) => f.id);
    setSelectedFacilityIds(new Set(affected.length > 0 ? affected : data.facilities.map((f) => f.id)));
  }, [data]);

  const [loginModalOpen, setLoginModalOpen] = useState(false);

  const handleLogin = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!passwordInput.trim()) return;
    setAuthLoading(true);
    setAuthError(null);
    try {
      const token = await verifyAdminPassword(passwordInput.trim());
      setAdminToken(token);
      setPasswordInput("");
      setLoginModalOpen(false);
    } catch (err) {
      setAuthError(err instanceof Error ? err.message : "인증 실패");
    } finally {
      setAuthLoading(false);
    }
  };

  const handleLogout = () => {
    void logoutAdmin();
    setAdminToken("");
  };


  // 우선순위 정렬된 시설 목록
  const prioritySortedFacilities = useMemo(() => {
    if (!data) return [];
    const gradeRankMap = new Map(GRADE_PRIORITY_ORDER.map((grade, index) => [grade, index]));
    const list = [...data.facilities];
    list.sort((a, b) => {
      const rankA = gradeRankMap.get(a.grade) ?? 99;
      const rankB = gradeRankMap.get(b.grade) ?? 99;
      if (rankA !== rankB) return rankA - rankB;
      // 발효 특보 개수 많은 순
      if (b.reasons.length !== a.reasons.length) return b.reasons.length - a.reasons.length;
      return a.name.localeCompare(b.name, "ko-KR");
    });
    return list;
  }, [data]);

  // 필터링된 시설 목록
  const filteredPriorityFacilities = useMemo(() => {
    if (!data) return [];
    const groupSet = selectedGroup === "ALL"
      ? new Set(data.groups.map((g) => g.id))
      : new Set([selectedGroup]);
    const gradeSet = selectedGrade === "ALL"
      ? new Set(GRADE_DISPLAY_ORDER)
      : new Set([selectedGrade as RiskGrade]);
    return filterFacilities(prioritySortedFacilities, groupSet, gradeSet, search);
  }, [data, prioritySortedFacilities, selectedGroup, selectedGrade, search]);

  // 다중 선택 헬퍼
  const toggleFacilitySelection = (id: string) => {
    setSelectedFacilityIds((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const selectAllFacilities = () => {
    if (!data) return;
    setSelectedFacilityIds(new Set(data.facilities.map((f) => f.id)));
  };

  const selectAffectedFacilities = () => {
    if (!data) return;
    const affected = data.facilities
      .filter((f) => f.grade === "HIGH" || f.grade === "MEDIUM" || f.grade === "LOW")
      .map((f) => f.id);
    setSelectedFacilityIds(new Set(affected));
  };

  const clearFacilitySelection = () => {
    setSelectedFacilityIds(new Set());
  };

  // 선택된 시설 객체 목록
  const selectedFacilitiesList = useMemo(() => {
    if (!data) return [];
    return data.facilities.filter((f) => selectedFacilityIds.has(f.id));
  }, [data, selectedFacilityIds]);

  const handleMapFacilitySelect = useCallback((facility: Facility) => {
    setFocusedFacilityId(facility.id);
    setFocusRequest({
      latitude: facility.latitude,
      longitude: facility.longitude,
      zoom: true,
      revision: Date.now(),
    });
  }, []);

  // PDF 다운로드 실행
  const [pdfLoading, setPdfLoading] = useState(false);
  const handlePdfDownload = async () => {
    if (!data || pdfLoading) return;
    if (!adminToken) {
      setLoginModalOpen(true);
      return;
    }
    const selectedIds = Array.from(selectedFacilityIds);
    const scopeLabel = selectedIds.length === data.facilities.length
      ? "전체 소관시설"
      : `선택 ${selectedIds.length}개소`;
    setPdfLoading(true);
    try {
      await downloadReportPdf(adminToken, monitoringMode, selectedIds, scopeLabel);
    } catch (err) {
      alert(err instanceof Error ? err.message : "PDF 다운로드에 실패했습니다.");
    } finally {
      setPdfLoading(false);
    }
  };


  // 위험등급별 집계
  const gradeCounts = useMemo(() => {
    const counts: Record<RiskGrade, number> = {
      HIGH: 0,
      MEDIUM: 0,
      LOW: 0,
      NONE: 0,
      UNASSESSED: 0,
      UNAVAILABLE: 0,
    };
    if (!data) return counts;
    for (const f of data.facilities) {
      if (counts[f.grade] !== undefined) {
        counts[f.grade] += 1;
      }
    }
    return counts;
  }, [data]);

  const activeWarningCount = gradeCounts.HIGH + gradeCounts.MEDIUM + gradeCounts.LOW;

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
        <button className="primary-button" type="button" onClick={() => void refresh()}>다시 시도</button>
      </main>
    );
  }

  const simulation = data.status.health === "SIMULATION";
  const live = data.status.health === "LIVE";
  const stale = data.status.health === "STALE";

  return (
    <div className="control-shell">
      <header className="control-header">
        <div className="control-brand">
          <span className="brand-mark">K-ECO SAFETY MONITORING</span>
          <h1>중앙 관제</h1>
        </div>
        <div className="control-header-actions">
          {adminToken ? (
            <button
              className="secondary-button auth-status-btn logged-in"
              type="button"
              onClick={handleLogout}
              title="관리자 인증 해제 (로그아웃)"
            >
              🔓 <span className="btn-text-full">관리자 로그아웃</span><span className="btn-text-short">로그아웃</span>
            </button>
          ) : (
            <button
              className="primary-button auth-status-btn"
              type="button"
              onClick={() => setLoginModalOpen(true)}
              title="관리자 인증 로그인"
            >
              🔒 <span className="btn-text-full">관리자 인증</span><span className="btn-text-short">인증</span>
            </button>
          )}
          <button
            className="secondary-button"
            type="button"
            onClick={() => navigate("/settings")}
            title="위험도 정책 기준 설정"
          >
            ⚙ <span className="btn-text-full">위험도 설정</span><span className="btn-text-short">설정</span>
          </button>
          <button
            className="secondary-button"
            type="button"
            onClick={() => navigate("/")}
            title="스마트폰 현장 안전지도로 이동"
          >
            <span className="btn-text-full">현장 지도 보기 ↗</span><span className="btn-text-short">현장지도 ↗</span>
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


      {/* 상태 스트립 */}
      <div
        className={`status-line ${simulation ? "simulation" : live ? "live" : stale ? "stale" : "problem"}`}
        role="status"
      >
        <span className="status-dot" aria-hidden="true" />
        <b>{simulation ? "모의훈련 자료" : `KMA ${live ? "정상" : stale ? "수신 지연" : "조회 불가"}`}</b>
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
          · 총 103개소 중 <b>{activeWarningCount}개소</b> 특보 영향
        </span>
      </div>

      {dispatchSuccessId && (
        <div className="dispatch-success-banner" role="status">
          <span>✓ 시설담당자 그룹에 상황전파를 성공적으로 발송했습니다. (요청 ID: {dispatchSuccessId})</span>
          <button type="button" onClick={() => setDispatchSuccessId(null)}>×</button>
        </div>
      )}

      {/* 워크스페이스 탭 네비게이션 */}
      <nav className="control-workspace-tabs" aria-label="중앙관제 작업 화면 선택">
        <button
          type="button"
          className={`tab-button ${workspace === "overview" ? "active" : ""}`}
          onClick={() => setWorkspace("overview")}
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
          onClick={() => setWorkspace("history")}
        >
          실적·이력
        </button>
      </nav>

      {/* 탭 1: 운영 상황 */}
      {workspace === "overview" && (
        <section className="control-content">
          <section className="overview-summary-panel" aria-label="관제 현황 요약">
            <div className="overview-primary-summary">
              <div className="overview-primary-item">
                <span>소관시설 전체</span>
                <strong>{data.facilities.length}<small>개소</small></strong>
              </div>
              <div className="overview-primary-item affected">
                <span>특보 영향 시설</span>
                <strong>{activeWarningCount}<small>개소</small></strong>
              </div>
            </div>

            <div className="overview-grade-summary" aria-label="위험등급별 시설 수">
              {(["HIGH", "MEDIUM", "LOW", "NONE"] as const).map((grade) => (
                <div className="overview-grade-item" key={grade} aria-label={`${GRADE_LABELS[grade]} ${gradeCounts[grade]}개소`}>
                  <span className="overview-grade-dot" style={{ backgroundColor: GRADE_COLORS[grade] }} aria-hidden="true" />
                  <span>{GRADE_LABELS[grade]}</span>
                  <strong>{gradeCounts[grade]}</strong>
                </div>
              ))}
            </div>

            {(gradeCounts.UNASSESSED > 0 || gradeCounts.UNAVAILABLE > 0) && (
              <div className="overview-exception-summary" aria-label="판정 예외 시설">
                <span className="overview-exception-label">확인 필요</span>
                {gradeCounts.UNASSESSED > 0 && (
                  <span className="overview-exception-item">
                    <i style={{ backgroundColor: GRADE_COLORS.UNASSESSED }} aria-hidden="true" />
                    미판정 <b>{gradeCounts.UNASSESSED}</b>
                  </span>
                )}
                {gradeCounts.UNAVAILABLE > 0 && (
                  <span className="overview-exception-item">
                    <i style={{ backgroundColor: GRADE_COLORS.UNAVAILABLE }} aria-hidden="true" />
                    조회 불가 <b>{gradeCounts.UNAVAILABLE}</b>
                  </span>
                )}
              </div>
            )}
          </section>

          {/* 시스템 자동 감시 상태 요약 (관리자 토큰 연동 시) */}
          {overview.data && (
            <div className="system-health-panel">
              <div className="panel-header">
                <h3>5분 자동 관제 시스템 상태</h3>
                <span className={`badge ${overview.data.healthy ? "badge-success" : "badge-warning"}`}>
                  {overview.data.healthy ? "정상 감시 중" : "점검 필요"}
                </span>
              </div>
              <div className="health-grid">
                <div>
                  <span className="label">마지막 자동 실행:</span>
                  <b>{overview.data.last_run_at ? formatReferenceTime(overview.data.last_run_at) : "—"}</b>
                  <small>({overview.data.worker_detail || (overview.data.worker_fresh ? "정상" : "지연")})</small>
                </div>
                <div>
                  <span className="label">KMA 통신 상태:</span>
                  <b>{overview.data.kma_health === "LIVE" ? "정상 (LIVE)" : overview.data.kma_health || "정상"}</b>
                </div>
                <div>
                  <span className="label">운영 모드:</span>
                  <b>{overview.data.mode === "live" ? "실시간 운영 (Live)" : (overview.data.mode || "모의")}</b>
                </div>
              </div>
              {overview.data.checks && overview.data.checks.length > 0 && (
                <div className="health-checks-list" style={{ marginTop: 8, display: "flex", gap: 12, flexWrap: "wrap", fontSize: "0.75rem" }}>
                  {overview.data.checks.map((chk, idx) => (
                    <span key={idx} style={{ color: chk.healthy ? "var(--color-risk-low, #15803d)" : "var(--color-risk-high, #b91c1c)" }}>
                      {chk.healthy ? "✓" : "⚠"} {chk.name}: {chk.detail}
                    </span>
                  ))}
                </div>
              )}
            </div>
          )}


          {/* 점검 우선순위 목록 */}
          <div className="priority-panel">
            <div className="priority-header">
              <div>
                <h2>점검 우선순위 시설 목록</h2>
                <p>위험등급과 특보 단계에 따라 정렬된 103개 시설입니다.</p>
              </div>
              <div className="priority-filters">
                <select
                  value={selectedGrade}
                  onChange={(e) => setSelectedGrade(e.target.value)}
                  aria-label="위험등급 필터"
                >
                  <option value="ALL">전체 위험등급</option>
                  {GRADE_DISPLAY_ORDER.map((grade) => (
                    <option key={grade} value={grade}>
                      {GRADE_LABELS[grade]} ({gradeCounts[grade]})
                    </option>
                  ))}
                </select>
                <select
                  value={selectedGroup}
                  onChange={(e) => setSelectedGroup(e.target.value)}
                  aria-label="시설 유형 필터"
                >
                  <option value="ALL">전체 시설 유형</option>
                  {data.groups.map((group) => (
                    <option key={group.id} value={group.id}>
                      {group.label} ({group.count})
                    </option>
                  ))}
                </select>
                <input
                  type="text"
                  placeholder="시설명 또는 주소 검색"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  aria-label="시설 검색"
                />
              </div>
            </div>

            <div className="priority-table-wrapper">
              <table className="priority-table">
                <thead>
                  <tr>
                    <th>순위</th>
                    <th>위험등급</th>
                    <th>시설명</th>
                    <th>시설 유형</th>
                    <th>주소 / 행정구역</th>
                    <th>발효 기상특보</th>
                    <th>담당 연락처</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredPriorityFacilities.length > 0 ? (
                    filteredPriorityFacilities.map((facility, index) => (
                      <tr key={facility.id} className={facility.grade === "HIGH" ? "row-high" : ""}>
                        <td className="col-rank">{index + 1}</td>
                        <td className="col-grade">
                          <span
                            className="grade-badge"
                            style={{ backgroundColor: facility.grade_color }}
                          >
                            {facility.grade_label}
                          </span>
                        </td>
                        <td className="col-name">
                          <strong>{facility.name}</strong>
                        </td>
                        <td className="col-type">{facility.type}</td>
                        <td className="col-address">{facility.address}</td>
                        <td className="col-warnings">
                          <span className={facility.reasons.length > 0 ? "warning-tag active" : "warning-tag"}>
                            {uniqueWarningText(facility)}
                          </span>
                        </td>
                        <td className="col-contact">
                          <small>{facility.public_contact || "—"}</small>
                        </td>
                      </tr>
                    ))
                  ) : (
                    <tr>
                      <td colSpan={7} className="no-data">
                        일치하는 시설이 없습니다.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </section>
      )}

      {/* 탭 2: 대상 분석·전파 */}
      {workspace === "analysis" && (
        <section className="control-content">
          <div className="analysis-action-bar">
            <div className="selection-stats">
              <strong>선택된 시설: {selectedFacilityIds.size}개소</strong>
              <span>(전체 {data.facilities.length}개소 중)</span>
            </div>
            <div className="selection-buttons">
              <button type="button" className="secondary-button" onClick={selectAffectedFacilities}>
                특보 영향 시설만 선택 ({activeWarningCount})
              </button>
              <button type="button" className="secondary-button" onClick={selectAllFacilities}>
                전체 선택 (103)
              </button>
              <button type="button" className="secondary-button" onClick={clearFacilitySelection}>
                선택 해제
              </button>
            </div>
            <div className="action-buttons">
              <button
                type="button"
                className="secondary-button pdf-button"
                onClick={handlePdfDownload}
                disabled={selectedFacilityIds.size === 0 || pdfLoading}
              >
                {pdfLoading ? "PDF 생성 중..." : "PDF 초동보고서 다운로드 ⤓"}
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
                disabled={selectedFacilityIds.size === 0}
              >
                수동 Telegram 상황전파 📢
              </button>
            </div>
          </div>

          <div className="analysis-split-layout">
            <div className="analysis-map-card">
              <div className="map-card-header">
                <h3>소관시설 관제 지도</h3>
                <small>마커를 클릭하면 우측 목록에서 해당 시설로 포커스됩니다.</small>
              </div>
              <div className="control-map-container">
                <KakaoMap
                  facilities={data.facilities}
                  warningZones={data.warning_zones.features}
                  selectedFacilityId={focusedFacilityId}
                  cctvs={[]}
                  selectedCctvId=""
                  focusRequest={focusRequest}
                  weatherLayer={null}
                  onSelect={handleMapFacilitySelect}
                  onSelectGroup={() => {}}
                  onSelectCctv={() => {}}
                />
              </div>
            </div>

            <div className="analysis-table-card">
              <div className="table-card-header">
                <h3>전파 대상 시설 선택</h3>
                <small>체크박스를 선택하여 수동 전파 및 보고서 대상 범위를 확정하세요.</small>
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
                          <td><strong>{facility.name}</strong></td>
                          <td>{facility.type}</td>
                          <td>
                            <span className={facility.reasons.length > 0 ? "warning-tag active" : "warning-tag"}>
                              {uniqueWarningText(facility)}
                            </span>
                          </td>
                          <td><small>{facility.address}</small></td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        </section>
      )}

      {/* 관리자 인증 모달 */}
      {loginModalOpen && (
        <div className="modal-backdrop" onClick={() => setLoginModalOpen(false)}>
          <div className="modal-card admin-login-modal" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h2>🔒 관리자 인증</h2>
              <button type="button" className="close-button" onClick={() => setLoginModalOpen(false)}>×</button>
            </div>
            <p className="modal-description">
              수동 상황전파, PDF 초동보고서 다운로드 및 발송 이력을 관리하려면 관리자 비밀번호를 입력해 주세요.
            </p>
            <form onSubmit={async (e) => {
              await handleLogin(e);
            }} className="login-form">
              <input
                type="password"
                placeholder="관리자 비밀번호"
                value={passwordInput}
                onChange={(e) => setPasswordInput(e.target.value)}
                disabled={authLoading}
                autoFocus
              />
              <div className="modal-actions" style={{ display: "flex", gap: "8px", marginTop: "12px", justifyContent: "flex-end" }}>
                <button type="button" className="secondary-button" onClick={() => setLoginModalOpen(false)}>
                  취소
                </button>
                <button className="primary-button" type="submit" disabled={authLoading}>
                  {authLoading ? "인증 중..." : "인증 확인"}
                </button>
              </div>
            </form>
            {authError && <div className="notice error" style={{ marginTop: 12 }}>{authError}</div>}
          </div>
        </div>
      )}

      {/* 수동 전파 모달 */}
      {dispatchModalOpen && (
        <ManualDispatchModal

          facilities={selectedFacilitiesList}
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
        <section className="control-content">
          {!adminToken ? (
            <div className="admin-login-card">
              <h3>관리자 인증이 필요합니다</h3>
              <p>자동 및 수동 전파 실적과 상세 감사 이력을 조회하려면 관리자 비밀번호를 입력해 주세요.</p>
              <form onSubmit={(e) => void handleLogin(e)} className="login-form">
                <input
                  type="password"
                  placeholder="관리자 비밀번호"
                  value={passwordInput}
                  onChange={(e) => setPasswordInput(e.target.value)}
                  disabled={authLoading}
                />
                <button className="primary-button" type="submit" disabled={authLoading}>
                  {authLoading ? "인증 중..." : "확인"}
                </button>
              </form>
              {authError && <div className="notice error">{authError}</div>}
            </div>
          ) : (
            <div className="history-container">
              <div className="history-header">
                <div>
                  <h2>자동·수동 상황전파 실적 및 감사 이력</h2>
                  <p>실제 전파된 이력과 정량 지표를 투명하게 조회합니다.</p>
                </div>
                <div className="history-actions">
                  <div className="date-range-buttons">
                    <button
                      type="button"
                      className={dateRange === "today" ? "active" : ""}
                      onClick={() => setDateRange("today")}
                    >
                      오늘
                    </button>
                    <button
                      type="button"
                      className={dateRange === "7d" ? "active" : ""}
                      onClick={() => setDateRange("7d")}
                    >
                      최근 7일
                    </button>
                    <button
                      type="button"
                      className={dateRange === "30d" ? "active" : ""}
                      onClick={() => setDateRange("30d")}
                    >
                      최근 30일
                    </button>
                  </div>
                  <a
                    className="secondary-button"
                    href={`/internal/v1/notifications/export.csv?from=${fromDate}&to=${toDate}`}
                    target="_blank"
                    rel="noreferrer"
                  >
                    CSV 내보내기 ⤓
                  </a>
                  <button className="text-button" type="button" onClick={handleLogout}>
                    인증 해제
                  </button>
                </div>
              </div>

              {metrics.data && (
                <div className="kpi-grid history-kpi">
                  <div className="kpi-card">
                    <span className="kpi-label">자동 관제 전파</span>
                    <strong className="kpi-value">{metrics.data.total_auto_batches}<span>회</span></strong>
                    <small>영향 시설 {metrics.data.total_auto_facilities}개소</small>
                  </div>
                  <div className="kpi-card">
                    <span className="kpi-label">수동 상황 전파</span>
                    <strong className="kpi-value">{metrics.data.total_manual_batches}<span>회</span></strong>
                    <small>영향 시설 {metrics.data.total_manual_facilities}개소</small>
                  </div>
                  <div className="kpi-card">
                    <span className="kpi-label">Telegram 발송</span>
                    <strong className="kpi-value">{metrics.data.total_telegram_sent}<span>건</span></strong>
                    <small>시설담당자 그룹 및 관리자</small>
                  </div>
                  <div className="kpi-card">
                    <span className="kpi-label">SMS 발송</span>
                    <strong className="kpi-value">{metrics.data.total_sms_sent}<span>건</span></strong>
                    <small>SOLAPI 연동 실적</small>
                  </div>
                </div>
              )}

              <div className="events-table-panel">
                <h3>발송 이력 목록 ({events.data.length}건)</h3>
                <div className="priority-table-wrapper">
                  <table className="priority-table">
                    <thead>
                      <tr>
                        <th>발송 시각</th>
                        <th>구분</th>
                        <th>이벤트 분류</th>
                        <th>대상 시설 수</th>
                        <th>상태</th>
                        <th>상세 내용</th>
                      </tr>
                    </thead>
                    <tbody>
                      {events.data.length > 0 ? (
                        events.data.map((evt) => (
                          <tr key={evt.id}>
                            <td>{formatReferenceTime(evt.timestamp)}</td>
                            <td>
                              <span className={`badge ${evt.source === "automatic" ? "badge-auto" : "badge-manual"}`}>
                                {evt.source === "automatic" ? "자동" : "수동"}
                              </span>
                            </td>
                            <td><b>{evt.category || evt.event_type}</b></td>
                            <td>{evt.facility_count}개소</td>
                            <td>
                              <span className={`badge ${evt.status === "SENT" ? "badge-success" : "badge-warning"}`}>
                                {evt.status}
                              </span>
                            </td>
                            <td><small>{evt.detail || "—"}</small></td>
                          </tr>
                        ))
                      ) : (
                        <tr>
                          <td colSpan={6} className="no-data">
                            해당 기간에 기록된 발송 이력이 없습니다.
                          </td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          )}
        </section>
      )}
    </div>
  );
}
