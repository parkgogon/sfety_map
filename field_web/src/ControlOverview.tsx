import {
  formatReferenceTime,
  GRADE_COLORS,
  GRADE_DISPLAY_ORDER,
  GRADE_LABELS,
  uniqueWarningText,
} from "./utils";

import type { ReadyControlWorkspace } from "./useControlWorkspace";

type Props = Pick<
  ReadyControlWorkspace,
  | "monitoringMode"
  | "data"
  | "search"
  | "setSearch"
  | "selectedGrade"
  | "setSelectedGrade"
  | "selectedGroup"
  | "setSelectedGroup"
  | "overview"
  | "changeMonitoringMode"
  | "filteredPriorityFacilities"
  | "gradeCounts"
  | "activeWarningCount"
>;

export function ControlOverview({
  monitoringMode,
  data,
  search,
  setSearch,
  selectedGrade,
  setSelectedGrade,
  selectedGroup,
  setSelectedGroup,
  overview,
  changeMonitoringMode,
  filteredPriorityFacilities,
  gradeCounts,
  activeWarningCount,
}: Props) {
  return (
    <section className="control-content">
      <section className="overview-summary-panel" aria-label="관제 현황 요약">
        <div className="overview-primary-summary">
          <div className="overview-primary-item">
            <span>소관시설 전체</span>
            <strong>
              {data.facilities.length}
              <small>개소</small>
            </strong>
          </div>
          <div className="overview-primary-item affected">
            <span>특보 영향 시설</span>
            <strong>
              {activeWarningCount}
              <small>개소</small>
            </strong>
          </div>
        </div>

        <div className="overview-grade-summary" aria-label="위험등급별 시설 수">
          {(["HIGH", "MEDIUM", "LOW", "NONE"] as const).map((grade) => (
            <div
              className="overview-grade-item"
              key={grade}
              aria-label={`${GRADE_LABELS[grade]} ${gradeCounts[grade]}개소`}
            >
              <span
                className="overview-grade-dot"
                style={{ backgroundColor: GRADE_COLORS[grade] }}
                aria-hidden="true"
              />
              <span>{GRADE_LABELS[grade]}</span>
              <strong>{gradeCounts[grade]}</strong>
            </div>
          ))}
        </div>

        {(gradeCounts.UNASSESSED > 0 || gradeCounts.UNAVAILABLE > 0) && (
          <div
            className="overview-exception-summary"
            aria-label="판정 예외 시설"
          >
            <span className="overview-exception-label">확인 필요</span>
            {gradeCounts.UNASSESSED > 0 && (
              <span className="overview-exception-item">
                <i
                  style={{ backgroundColor: GRADE_COLORS.UNASSESSED }}
                  aria-hidden="true"
                />
                미판정 <b>{gradeCounts.UNASSESSED}</b>
              </span>
            )}
            {gradeCounts.UNAVAILABLE > 0 && (
              <span className="overview-exception-item">
                <i
                  style={{ backgroundColor: GRADE_COLORS.UNAVAILABLE }}
                  aria-hidden="true"
                />
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
            <span
              className={`badge ${overview.data.healthy ? "badge-success" : "badge-warning"}`}
            >
              {overview.data.healthy ? "정상 감시 중" : "점검 필요"}
            </span>
          </div>
          <div className="health-grid">
            <div>
              <span className="label">마지막 자동 실행:</span>
              <b>
                {overview.data.last_run_at
                  ? formatReferenceTime(overview.data.last_run_at)
                  : "—"}
              </b>
              <small>
                (
                {overview.data.worker_detail ||
                  (overview.data.worker_fresh ? "정상" : "지연")}
                )
              </small>
            </div>
            <div>
              <span className="label">KMA 통신 상태:</span>
              <b>
                {overview.data.kma_health === "LIVE"
                  ? "정상 (LIVE)"
                  : overview.data.kma_health || "정상"}
              </b>
            </div>
            <div>
              <span className="label">운영 모드:</span>
              <b>
                {overview.data.mode === "live"
                  ? "실시간 운영 (Live)"
                  : overview.data.mode || "모의"}
              </b>
            </div>
          </div>
          {overview.data.checks && overview.data.checks.length > 0 && (
            <div
              className="health-checks-list"
              style={{
                marginTop: 8,
                display: "flex",
                gap: 12,
                flexWrap: "wrap",
                fontSize: "0.75rem",
              }}
            >
              {overview.data.checks.map((chk, idx) => (
                <span
                  key={idx}
                  style={{
                    color: chk.healthy
                      ? "var(--color-risk-low, #15803d)"
                      : "var(--color-risk-high, #b91c1c)",
                  }}
                >
                  {chk.healthy ? "✓" : "⚠"} {chk.name}: {chk.detail}
                </span>
              ))}
            </div>
          )}
        </div>
      )}

      {/* 모의훈련 시작 진입점 (실시간 모드에서만 표시, 훈련 중에는 상단 보라색 배너 1곳으로 복귀 단일화) */}
      {monitoringMode !== "simulation" && (
        <div className="simulation-entry-panel">
          <div>
            <strong>모의훈련</strong>
            <span>
              특보 발생 시 화면을 미리 확인합니다. 실제 운영에 영향 없이 고정된
              훈련 특보를 표시합니다.
            </span>
          </div>
          <button
            className="secondary-button"
            type="button"
            onClick={() => changeMonitoringMode("simulation")}
          >
            모의훈련 시작
          </button>
        </div>
      )}

      {/* 점검 우선순위 목록 */}
      <div className="priority-panel">
        <div className="priority-header">
          <div>
            <h2>점검 우선순위 시설 목록</h2>
            <p>
              위험등급과 특보 단계에 따라 정렬된{" "}
              {data?.facilities.length ?? 195}개 시설입니다.
            </p>
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
                  <tr
                    key={facility.id}
                    className={facility.grade === "HIGH" ? "row-high" : ""}
                  >
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

        {/* 모바일 최적화 점검 우선순위 카드 리스트 */}
        <div
          className="priority-card-list"
          role="list"
          aria-label="점검 우선순위 시설 모바일 카드 목록"
        >
          {filteredPriorityFacilities.length > 0 ? (
            filteredPriorityFacilities.map((facility, index) => (
              <div
                key={facility.id}
                className={`priority-card ${facility.grade === "HIGH" ? "card-high" : ""}`}
                role="listitem"
              >
                <div className="priority-card-top">
                  <div className="priority-card-rank-grade">
                    <span className="priority-rank">{index + 1}위</span>
                    <span
                      className="grade-badge"
                      style={{ backgroundColor: facility.grade_color }}
                    >
                      {facility.grade_label}
                    </span>
                    <strong className="priority-name">{facility.name}</strong>
                  </div>
                  <span className="priority-type">{facility.type}</span>
                </div>

                <div className="priority-card-body">
                  <div className="priority-row">
                    <span className="priority-label">특보</span>
                    <span
                      className={
                        facility.reasons.length > 0
                          ? "warning-tag active"
                          : "warning-tag"
                      }
                    >
                      {uniqueWarningText(facility)}
                    </span>
                  </div>
                  <div className="priority-row">
                    <span className="priority-label">위치</span>
                    <span className="priority-value">{facility.address}</span>
                  </div>
                  <div className="priority-row">
                    <span className="priority-label">담당</span>
                    <span className="priority-value">
                      {facility.public_contact || "—"}
                    </span>
                  </div>
                </div>
              </div>
            ))
          ) : (
            <div className="priority-card-empty">일치하는 시설이 없습니다.</div>
          )}
        </div>
      </div>
    </section>
  );
}
