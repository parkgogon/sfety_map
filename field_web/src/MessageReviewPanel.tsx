import { useEffect, useRef, useState } from "react";
import { recordRequest, type MessageRecord } from "./messageRecordsApi";
import type { MessageReviewDetail } from "./messageReviewApi";

export default function MessageReviewPanel({ token, record, disabled, unsavedWork, onRecordChanged, onBusyChange, onDirtyChange }: {
  token: string; record: MessageRecord; disabled: boolean; unsavedWork: boolean;
  onRecordChanged: (record: MessageRecord) => void; onBusyChange: (busy: boolean) => void; onDirtyChange?: (dirty: boolean) => void;
}) {
  const [detail, setDetail] = useState<MessageReviewDetail | null>(null);
  const [reload, setReload] = useState(0); const [loading, setLoading] = useState(false); const [busy, setBusy] = useState(false);
  const [outcome, setOutcome] = useState<"facilities_selected" | "no_action">("facilities_selected");
  const [reason, setReason] = useState(""); const [followUp, setFollowUp] = useState("");
  const [excluded, setExcluded] = useState<Record<string,string>>({});
  const [reopenReason, setReopenReason] = useState(""); const [managerNote, setManagerNote] = useState("");
  const [error, setError] = useState(""); const [notice, setNotice] = useState("");
  const mounted = useRef(true); const operation = useRef<AbortController | null>(null);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; operation.current?.abort(); }; }, []);
  useEffect(() => {
    const controller = new AbortController(); setLoading(true); setDetail(null); setError(""); setNotice("");
    void recordRequest<MessageReviewDetail>(token, controller.signal, `/${record.id}/review`).then(value => {
      if (controller.signal.aborted) return;
      setDetail(value); setManagerNote(value.draft?.manager_note || "");
      if (value.completion) { setOutcome(value.completion.outcome); setReason(value.completion.reason); setFollowUp(value.completion.follow_up_note); }
    }).catch(reason => { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "검토 기록을 불러오지 못했습니다."); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [token, record.id, record.version, reload]);
  async function run(work: (signal: AbortSignal) => Promise<void>) {
    operation.current?.abort(); const controller = new AbortController(); operation.current = controller;
    setBusy(true); onBusyChange(true); setError(""); setNotice("");
    try { await work(controller.signal); }
    catch (reason) { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "작업을 완료하지 못했습니다."); }
    finally { if (mounted.current) { setBusy(false); onBusyChange(false); } }
  }
  async function save(path: string, body: unknown) {
    await run(async signal => {
      const updated = await recordRequest<MessageRecord>(token, signal, `/${record.id}/${path}`, body);
      if (!signal.aborted) { onRecordChanged(updated); setReopenReason(""); if (path === "reopen") { setReason(""); setFollowUp(""); setExcluded({}); setOutcome("facilities_selected"); } }
    });
  }
  const locked = disabled || busy || loading || !detail || detail.record_version !== record.version;
  const completed = record.review_state === "completed";
  const missing = detail?.locations.filter(l => l.selected_count === 0) || [];
  const totalSelections = detail?.locations.reduce((sum,l) => sum + l.selected_count, 0) || 0;
  const draft = detail?.draft; const draftDirty = !!draft && managerNote !== draft.manager_note;
  useEffect(() => { onDirtyChange?.(draftDirty); }, [draftDirty, onDirtyChange]);
  useEffect(() => () => onDirtyChange?.(false), [onDirtyChange]);
  return <section className="message-card message-review" aria-label="검토 결과와 안내 초안">
    <div className="message-record-toolbar"><h2>검토 결과 · 안내 초안</h2><button className="secondary-button" disabled={disabled || busy} onClick={() => setReload(n => n + 1)}>검토 결과 다시 불러오기</button></div>
    <p>검토 완료는 내부 판단 기록입니다. 재난 종료나 현장 확인 완료를 의미하지 않습니다.</p>
    {loading && <p role="status">현재 검토 근거를 확인하는 중…</p>}
    {error && <p role="alert" className="message-error">{error}</p>}
    {notice && <p role="status" className="message-notice">{notice}</p>}
    {unsavedWork && <p className="message-notice">저장하지 않은 메모·기준점·시설 선택이 있습니다. 먼저 저장하거나 변경을 되돌려 주세요.</p>}
    {detail && detail.record_version !== record.version && <p className="message-notice">기록의 새 버전이 있습니다. 위의 ‘현재 기록 다시 불러오기’를 눌러 최신 기록을 확인해 주세요.</p>}
    {detail?.stale_reason && <p className="message-notice">{detail.stale_reason}</p>}
    {detail && !completed && <>
      <label>검토 결과<select aria-label="완료할 검토 결과" value={outcome} disabled={locked || unsavedWork} onChange={e => setOutcome(e.target.value as typeof outcome)}><option value="facilities_selected">확인 대상 선정</option><option value="no_action">추가 조치 없음</option></select></label>
      {outcome === "facilities_selected" && <><p>저장한 장소별 선정: 총 {totalSelections}건 · 완료 시 같은 시설은 중복을 제외해 집계합니다.</p>
        {missing.map(loc => <label key={loc.key}>{loc.text} 미선정 사유<textarea aria-label={`${loc.text} 미선정 사유`} maxLength={500} rows={2} disabled={locked || unsavedWork} value={excluded[loc.key] || ""} onChange={e => setExcluded(old => ({ ...old, [loc.key]: e.target.value }))} /></label>)}
      </>}
      <label>검토 완료 사유<textarea aria-label="검토 완료 사유" maxLength={1000} rows={3} disabled={locked || unsavedWork} value={reason} onChange={e => setReason(e.target.value)} placeholder="선정 시설을 확인할 이유 또는 추가 조치가 필요하지 않은 이유" /></label>
      <label>확인 질문·후속 변경에 대한 보완 메모{(detail.related_count || 0) > 0 && " (후속 연결 시 필수)"}<textarea aria-label="확인 질문 보완 메모" maxLength={1000} rows={2} disabled={locked || unsavedWork} value={followUp} onChange={e => setFollowUp(e.target.value)} placeholder="해결한 질문과 아직 확인할 사항을 구분해 적어 주세요 (선택)" /></label>
      <button className="primary-button" disabled={locked || unsavedWork || !!detail.stale_reason || !reason.trim() || ((detail.related_count || 0) > 0 && !followUp.trim()) || (outcome === "facilities_selected" && (!totalSelections || missing.some(l => !excluded[l.key]?.trim()))) || (outcome === "no_action" && totalSelections > 0)}
        onClick={() => void save("complete", { expected_version: record.version, outcome, reason: reason.trim(), follow_up_note: followUp.trim(),
          excluded_locations: outcome === "facilities_selected" ? missing.map(l => ({location_key:l.key,reason:excluded[l.key].trim()})) : [] })}>검토 완료하고 초안 만들기</button>
      {outcome === "no_action" && totalSelections > 0 && <p className="message-notice">선정 시설을 해제한 뒤 추가 조치 없음으로 완료할 수 있습니다.</p>}
    </>}
    {completed && detail?.completion && <>
      <div className="message-review-completion"><h3>검토 완료 · {detail.completion.outcome === "facilities_selected" ? "확인 대상 선정" : "추가 조치 없음"}</h3>
        <p>{detail.completion.reason}</p><p>선정 시설 중복 제외 {detail.completion.selected_unique_count}개소</p>
        <small>{new Date(detail.completion.completed_at).toLocaleString("ko-KR", { timeZone: "Asia/Seoul" })} (한국 시간){!detail.completion_current && " · 현재 근거 재확인 필요"}</small>
      </div>
      <details><summary>검토 다시 열기</summary><label>다시 여는 사유<textarea aria-label="검토 재열기 사유" rows={2} maxLength={1000} disabled={locked} value={reopenReason} onChange={e => setReopenReason(e.target.value)} /></label>
        <button className="secondary-button" disabled={locked || !reopenReason.trim()} onClick={() => void save("reopen", { expected_version: record.version, reason: reopenReason.trim() })}>사유를 남기고 다시 열기</button>
      </details>
    </>}
    {draft && <div className="message-notice-draft"><h3>안내 초안 · {draft.revision}판</h3>
      <p className="message-caption">저장한 원문·조회 기준·선정 시설·미확인 사항을 반영합니다. 추가로 전할 내용을 아래에서 편집할 수 있습니다.</p>
      {!detail?.draft_current && <p className="message-notice">현재 근거로 확인되지 않은 초안입니다. 다시 검토하기 전에는 복사할 수 없습니다.</p>}
      <label>관리자 추가 안내<textarea aria-label="관리자 추가 안내" rows={3} maxLength={2000} value={managerNote} disabled={locked || !detail?.draft_current} onChange={e => setManagerNote(e.target.value)} /></label>
      <button className="secondary-button" disabled={locked || !detail?.draft_current || !draftDirty} onClick={() => void save("notice", { expected_version: record.version, draft_revision: draft.revision, manager_note: managerNote })}>추가 안내를 초안에 저장</button>
      {draftDirty && <p className="message-notice">추가 안내를 저장하면 아래 초안에 반영됩니다. 저장 후 복사해 주세요.</p>}
      <label>저장한 안내 초안<textarea aria-label="저장한 안내 초안" rows={18} value={draft.text} readOnly /></label>
      <button className="primary-button" disabled={locked || unsavedWork || !detail?.draft_current || draftDirty} onClick={() => void run(async signal => {
        const checked = await recordRequest<{ text: string; draft_revision: number }>(token, signal, `/${record.id}/notice-copy`, { expected_version: record.version, draft_revision: draft.revision });
        if (signal.aborted) return;
        if (!navigator.clipboard?.writeText) throw new Error("자동 복사를 사용할 수 없습니다. 현재 초안을 다시 확인한 뒤 위 텍스트를 직접 선택해 복사해 주세요.");
        try { await navigator.clipboard.writeText(checked.text); }
        catch { throw new Error("클립보드에 복사하지 못했습니다. 위 텍스트를 직접 선택해 복사할 수 있습니다."); }
        if (!signal.aborted) setNotice("초안을 클립보드에 복사했습니다. 실제 발송·수신 기록은 아닙니다.");
      })}>현재 초안 복사</button>
    </div>}
  </section>;
}

export function MessageReviewHistory({ record }: { record: MessageRecord }) {
  const completion = record.review_completion; const draft = record.notice_draft;
  if (!completion && !draft && !record.review_reopen_reason) return null;
  return <section aria-label="과거 검토 결과와 안내 초안" className="message-review-history">
    <h3>이 버전의 검토 결과·안내 초안</h3>
    {completion && <><p>{completion.outcome === "facilities_selected" ? "확인 대상 선정" : "추가 조치 없음"} · {completion.reason}</p><p>관리자 보완: {completion.follow_up_note || "없음"}</p></>}
    {record.review_reopen_reason && <p>재열기 사유: {record.review_reopen_reason}</p>}
    {draft && <><p>과거 초안 {draft.revision}판 · 현재 초안과 구분해 주세요.</p><pre>{draft.text}</pre></>}
  </section>;
}
