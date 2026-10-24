import { formatReferenceTime } from "./utils";

import type { ReadyControlWorkspace } from "./useControlWorkspace";

type Props = Pick<
  ReadyControlWorkspace,
  | "adminToken"
  | "passwordInput"
  | "setPasswordInput"
  | "authError"
  | "authLoading"
  | "handleLogin"
  | "handleLogout"
  | "dateRange"
  | "setDateRange"
  | "fromDate"
  | "toDate"
  | "metrics"
  | "events"
>;

export function ControlHistory({
  adminToken,
  passwordInput,
  setPasswordInput,
  authError,
  authLoading,
  handleLogin,
  handleLogout,
  dateRange,
  setDateRange,
  fromDate,
  toDate,
  metrics,
  events,
}: Props) {
  return (
    <section className="control-content">
      {!adminToken ? (
        <div className="admin-login-card">
          <h3>관리자 인증이 필요합니다</h3>
          <p>
            자동 및 수동 전파 실적과 상세 감사 이력을 조회하려면 관리자
            비밀번호를 입력해 주세요.
          </p>
          <form onSubmit={(e) => void handleLogin(e)} className="login-form">
            <input
              type="password"
              placeholder="관리자 비밀번호"
              value={passwordInput}
              onChange={(e) => setPasswordInput(e.target.value)}
              disabled={authLoading}
            />
            <button
              className="primary-button"
              type="submit"
              disabled={authLoading}
            >
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
              <button
                className="text-button"
                type="button"
                onClick={handleLogout}
              >
                인증 해제
              </button>
            </div>
          </div>

          {metrics.data && (
            <div className="kpi-grid history-kpi">
              <div className="kpi-card">
                <span className="kpi-label">자동 관제 전파</span>
                <strong className="kpi-value">
                  {metrics.data.total_auto_batches}
                  <span>회</span>
                </strong>
                <small>
                  영향 시설 {metrics.data.total_auto_facilities}개소
                </small>
              </div>
              <div className="kpi-card">
                <span className="kpi-label">수동 상황 전파</span>
                <strong className="kpi-value">
                  {metrics.data.total_manual_batches}
                  <span>회</span>
                </strong>
                <small>
                  영향 시설 {metrics.data.total_manual_facilities}개소
                </small>
              </div>
              <div className="kpi-card">
                <span className="kpi-label">Telegram 발송</span>
                <strong className="kpi-value">
                  {metrics.data.total_telegram_sent}
                  <span>건</span>
                </strong>
                <small>시설담당자 그룹 및 관리자</small>
              </div>
              <div className="kpi-card">
                <span className="kpi-label">SMS 발송</span>
                <strong className="kpi-value">
                  {metrics.data.total_sms_sent}
                  <span>건</span>
                </strong>
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
                          <span
                            className={`badge ${evt.source === "automatic" ? "badge-auto" : "badge-manual"}`}
                          >
                            {evt.source === "automatic" ? "자동" : "수동"}
                          </span>
                        </td>
                        <td>
                          <b>{evt.category || evt.event_type}</b>
                        </td>
                        <td>{evt.facility_count}개소</td>
                        <td>
                          <span
                            className={`badge ${evt.status === "SENT" ? "badge-success" : "badge-warning"}`}
                          >
                            {evt.status}
                          </span>
                        </td>
                        <td>
                          <small>{evt.detail || "—"}</small>
                        </td>
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
  );
}
