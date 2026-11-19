import { useState, useEffect } from "react";
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
              <p>기상특보·재난문자의 직원방 전파와 수동전파 결과를 확인합니다.</p>
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
              <button
                className="text-button"
                type="button"
                onClick={handleLogout}
              >
                인증 해제
              </button>
            </div>
          </div>

          <HistoryResults key={JSON.stringify([adminToken, fromDate, toDate])}
            token={adminToken} from={fromDate} to={toDate} />
        </div>
      )}
    </section>
  );
}

const sources = { automatic: "기상특보 자동", manual: "수동", disaster: "재난문자 자동" };
interface HistoryRow {
  id: string; processed_at: string; source: keyof typeof sources; event: string; status: string;
  channel: string; facility_count: number | null; message_count: number | null; detail: string;
  record_id: string | null; drill: boolean; sms_accepted: number;
}
interface Report {
  sent: Partial<Record<keyof typeof sources, number>>;
  sms_accepted: number;
  events: HistoryRow[];
}
const states: Record<string, string> = {
  SENT: "전송 응답 확인", FAILED: "발송 실패", UNKNOWN: "결과 미상", REJECTED: "요청 거절",
  WAITING: "재시도 대기", RETRY_QUEUED: "재시도 대기", CANCELLED: "대기 취소",
  SENDING: "전송 중", PENDING: "대기", DISPATCHED: "처리 완료",
};
function historyHeaders(token: string): HeadersInit {
  return token === "active-session" ? {} : {"X-Alert-Admin-Token": token};
}

function HistoryResults({token, from, to}: {token: string; from: string; to: string}) {
  const [report, setReport] = useState<Report | null>(null);
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);
  const [limit, setLimit] = useState(100);
  const [exportError, setExportError] = useState("");
  const [exporting, setExporting] = useState(false);
  const path = `/internal/v1/notifications/history?from=${from}&to=${to}`;
  useEffect(() => {
    const controller = new AbortController();
    fetch(path, {signal: controller.signal, credentials: "same-origin", headers: historyHeaders(token)})
      .then(async response => {
        if (!response.ok) throw new Error(response.status === 403 ? "관리자 인증을 다시 확인해 주세요." : "전파 이력을 불러오지 못했습니다.");
        const result: Report = await response.json();
        if (!controller.signal.aborted) setReport(result);
      })
      .catch(reason => { if (!controller.signal.aborted) setError(String(reason.message)); });
    return () => controller.abort();
  }, [token, path, retry]);

  async function exportCsv() {
    setExporting(true);
    setExportError("");
    try {
      const response = await fetch(path + "&format=csv", {credentials: "same-origin", headers: historyHeaders(token)});
      if (!response.ok) throw new Error("CSV를 불러오지 못했습니다.");
      const url = URL.createObjectURL(await response.blob());
      const link = document.createElement("a");
      link.href = url;
      link.download = `전파이력_${from}_${to}.csv`;
      document.body.append(link);
      link.click();
      link.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 30_000);
    } catch {
      setExportError("CSV를 불러오지 못했습니다. 다시 시도해 주세요.");
    } finally {
      setExporting(false);
    }
  }

  if (error) return <div role="alert">{error} <button onClick={() => {setError(""); setRetry(n => n+1);}}>다시 시도</button></div>;
  if (!report) return <p role="status">전파 이력을 불러오는 중…</p>;
  return <>
    <div className="history-report-heading"><span>{from} ~ {to} (한국시간)</span>
      <button type="button" disabled={exporting} onClick={exportCsv}>CSV 내보내기</button></div>
    {exportError && <p role="alert">{exportError}</p>}
    <div className="kpi-grid history-kpi">
      {(Object.keys(sources) as Array<keyof typeof sources>).map(source =>
        <div className="kpi-card" key={source}><span>{sources[source]} · 직원방 전파</span>
          <strong className="kpi-value">{report.sent[source] ?? 0}<span>회</span></strong></div>)}
      <div className="kpi-card"><span>SMS 접수</span><strong className="kpi-value">{report.sms_accepted}<span>건</span></strong></div>
    </div>
    <div className="events-table-panel"><h3>전파 이력 ({report.events.length}건)</h3>
      {report.events.length === 0 ? <p>선택한 기간에 기록된 전파 이력이 없습니다.</p> :
        <div className="priority-table-wrapper"><table className="priority-table">
          <thead><tr>{["처리 시각", "구분", "이벤트", "대상 시설", "채널", "메시지", "처리 결과"].map(label => <th key={label}>{label}</th>)}</tr></thead>
          <tbody>{report.events.slice(0, limit).map(row => <tr key={row.source + row.id}>
            <td>{formatReferenceTime(row.processed_at)}</td>
            <td>{sources[row.source]}{row.drill && " · 훈련"}</td>
            <td>{row.event}{row.record_id && <a className="history-detail" href={`/control/messages?view=review&record_id=${encodeURIComponent(row.record_id)}`}>원문·판단 근거</a>}</td>
            <td>{row.facility_count === null ? "미집계" : row.facility_count + "개소"}</td>
            <td>{row.channel}</td><td>{row.message_count === null ? "미집계" : row.message_count + "건"}{row.sms_accepted > 0 && ` · SMS 접수 ${row.sms_accepted}건`}</td>
            <td>{states[row.status] ?? row.status}{row.source !== "disaster" && row.detail && <small className="history-detail">{row.detail}</small>}</td>
          </tr>)}</tbody></table></div>}
      {report.events.length > limit && <button onClick={() => setLimit(n => n + 100)}>이력 더 보기</button>}
    </div>
  </>;
}
