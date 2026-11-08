import { useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import type { MessageAnalysisResult, MessageAnalysisStatus, MessageInput } from "./messageAnalysisApi";
import { recordRequest, type RecordStatus, type MessageRecord, type RecordPage, type OfficialPage, type RecordHistory } from "./messageRecordsApi";
import examples from "./messageExamples.json";
import MessageRelatedPanel, { MessageRelatedHistory } from "./MessageRelatedPanel";
import MessageReviewPanel, { MessageReviewHistory } from "./MessageReviewPanel";
import MessageSpatialWorkspace, { MessageSpatialHistory } from "./MessageSpatialWorkspace";

const ORIGINS = { manual: "수동 입력", example: "창작 예문", official: "공식 API" };
const AI_STATES = { not_analyzed: "미분석", running: "분석 중", completed: "분석 완료", failed: "분석 실패" };
const EVENTS: Record<string, string> = { registered: "문자 등록", source_changed: "원문 변경", source_observed: "원문 재조회", note_saved: "검토 메모 저장", analysis_started: "분석 시작", analysis_completed: "분석 저장", analysis_failed: "분석 실패", reference_saved: "조회 기준점 변경", reference_confirmed: "조회 기준점 재확인", facilities_selected: "업무 대상 시설 선정", review_completed: "검토 완료", review_reopened: "검토 재열기", notice_updated: "안내 초안 수정", message_linked: "후속 문자 연결", message_reconfirmed: "후속 연결 재확인", message_unlinked: "후속 연결 해제" };
export function koreanDate() {
  const parts = new Intl.DateTimeFormat("en", { timeZone: "Asia/Seoul", year: "numeric", month: "2-digit", day: "2-digit" }).formatToParts(new Date());
  return ["year", "month", "day"].map(type => parts.find(p => p.type === type)!.value).join("-");
}
function issuedTime(value: string | null) {
  if (!value) return "발행 시각 미상";
  return new Intl.DateTimeFormat("ko-KR", { timeZone: "Asia/Seoul", dateStyle: "short", timeStyle: "short" }).format(new Date(value));
}
function localInput(value: string | null) {
  if (!value) return "";
  const date = new Date(new Date(value).getTime() + 9 * 3600_000);
  return date.toISOString().slice(0, 16);
}

export default function MessageRecordWorkspace({ token, status, recordsStatus, renderResult }: {
  token: string; status: MessageAnalysisStatus | null; recordsStatus: RecordStatus;
  renderResult: (result: MessageAnalysisResult, reviewCompleted?: boolean) => ReactNode;
}) {
  const [records, setRecords] = useState<MessageRecord[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [selected, setSelected] = useState<MessageRecord | null>(null);
  const [text, setText] = useState(""); const [source, setSource] = useState("");
  const [issuedAt, setIssuedAt] = useState(""); const [regions, setRegions] = useState("");
  const [kind, setKind] = useState<"manual" | "example">("manual");
  const [radius, setRadius] = useState<MessageInput["reference_radius_km"]>(3);
  const [note, setNote] = useState(""); const [review, setReview] = useState<MessageRecord["review_state"]>("unreviewed");
  const [reviewBusy, setReviewBusy] = useState(false); const [spatialDirty, setSpatialDirty] = useState(false);
  const [spatialBusy, setSpatialBusy] = useState(false);
  const [relatedBusy, setRelatedBusy] = useState(false); const [draftDirty, setDraftDirty] = useState(false);
  const [busy, setBusy] = useState(false); const [listBusy, setListBusy] = useState(false);
  const [error, setError] = useState(""); const [listError, setListError] = useState(""); const [notice, setNotice] = useState("");
  const [feed, setFeed] = useState<OfficialPage | null>(null);
  const [feedRegion, setFeedRegion] = useState("대구광역시"); const [feedDate, setFeedDate] = useState(koreanDate);
  const [history, setHistory] = useState<RecordHistory | null>(null); const [past, setPast] = useState<MessageRecord | null>(null);
  const operation = useRef<AbortController | null>(null); const listOperation = useRef<AbortController | null>(null);
  const registrationKey = useRef<string | null>(null);

  function choose(record: MessageRecord) {
    setSelected(record); setText(record.message.text); setSource(record.message.source);
    setIssuedAt(localInput(record.message.issued_at)); setRegions(record.message.recipient_regions.join(", "));
    setRadius(record.reference_radius_km); setNote(record.note); setReview(record.review_state);
    setHistory(null); setPast(null);
    const url = new URL(window.location.href); url.searchParams.set("record_id", record.id);
    window.history.replaceState({}, "", url.pathname + url.search);
  }
  async function loadList(append = false, signal?: AbortSignal) {
    if (!signal) { listOperation.current?.abort(); listOperation.current = new AbortController(); signal = listOperation.current.signal; }
    setListBusy(true); setListError("");
    try {
      const page = await recordRequest<RecordPage>(token, signal, append && cursor ? `?before=${encodeURIComponent(cursor)}` : "");
      if (signal.aborted) return;
      setRecords(old => append ? [...old, ...page.records.filter(r => !old.some(o => o.id === r.id))] : page.records);
      setCursor(page.next_cursor);
    } catch (reason) { if (!signal.aborted) setListError(reason instanceof Error ? reason.message : "목록 조회 실패"); }
    finally { if (!signal.aborted) setListBusy(false); }
  }
  useEffect(() => {
    const controller = new AbortController();
    void loadList(false, controller.signal);
    const identifier = new URLSearchParams(window.location.search).get("record_id");
    if (identifier) setBusy(true);
    if (identifier) void recordRequest<MessageRecord>(token, controller.signal, `/${encodeURIComponent(identifier)}`)
      .then(record => { if (!controller.signal.aborted) choose(record); })
      .catch(reason => { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "기록 조회 실패"); })
      .finally(() => { if (!controller.signal.aborted) setBusy(false); });
    return () => { controller.abort(); operation.current?.abort(); listOperation.current?.abort(); };
    // Each authenticated session owns this workspace and its requests.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

  async function act(work: (signal: AbortSignal) => Promise<void>) {
    operation.current?.abort(); const controller = new AbortController(); operation.current = controller;
    setBusy(true); setError(""); setNotice("");
    try { await work(controller.signal); }
    catch (reason) { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "작업 실패"); }
    finally { if (!controller.signal.aborted) setBusy(false); }
  }
  function newMessage() {
    setSelected(null); setText(""); setSource(""); setIssuedAt(""); setRegions(""); setKind("manual"); setRadius(3);
    setNote(""); setReview("unreviewed"); setHistory(null); setPast(null); setError(""); setNotice(""); registrationKey.current = null;
    const url = new URL(window.location.href); url.searchParams.delete("record_id"); window.history.replaceState({}, "", url.pathname + url.search);
  }
  function edited() { registrationKey.current = null; setNotice(""); }
  async function register(signal: AbortSignal) {
    registrationKey.current ??= crypto.randomUUID();
    const value = await recordRequest<{ record: MessageRecord; registration: string }>(token, signal, "", {
      registration_key: registrationKey.current, text: text.trim(), source: source.trim(), issued_at: `${issuedAt}:00+09:00`,
      recipient_regions: regions.split(/[,;\n]/).map(r => r.trim()).filter(Boolean), input_kind: kind, reference_radius_km: radius,
    });
    if (signal.aborted) throw new DOMException("Aborted", "AbortError");
    choose(value.record); await loadList(); return value.record;
  }
  async function submit(event: FormEvent<HTMLFormElement>, analyze: boolean) {
    event.preventDefault(); if (busy || spatialBusy || reviewBusy || relatedBusy || selected?.review_state === "completed") return;
    if (!event.currentTarget.reportValidity()) return;
    await act(async signal => {
      const record = selected || await register(signal);
      if (!analyze) { setNotice("문자를 등록했습니다. AI 분석은 별도로 실행합니다."); return; }
      try {
        const updated = await recordRequest<MessageRecord>(token, signal, `/${record.id}/analyze`, { expected_version: record.version, reference_radius_km: radius });
        if (!signal.aborted) { choose(updated); setNotice("분석 결과를 저장했습니다."); await loadList(); }
      } catch (reason) {
        if (!signal.aborted) {
          try { const latest = await recordRequest<MessageRecord>(token, signal, `/${record.id}`); if (!signal.aborted) choose(latest); } catch { /* Keep last saved data visible. */ }
          await loadList();
        }
        throw reason;
      }
    });
  }
  const currentResult = selected?.analysis;
  const operationBusy = busy || spatialBusy || reviewBusy || relatedBusy;
  const completed = selected?.review_state === "completed";
  const unsavedNote = !!selected && (note !== selected.note || review !== selected.review_state);
  function updateRecord(value: MessageRecord) {
    setReview(old => old === selected?.review_state ? value.review_state : old);
    setSelected(value); setHistory(null); setPast(null); void loadList();
  }

  return <>
    {recordsStatus.storage_mode === "memory" && <p className="message-notice">로컬 임시 저장입니다. 새로고침 후 복구되지만 서버를 재시작하면 삭제됩니다.</p>}
    <section className="message-card message-records" aria-label="등록한 재난문자">
      <div className="message-record-toolbar"><h2>등록한 재난문자</h2><div>
        <button className="secondary-button" disabled={operationBusy || listBusy} onClick={() => void loadList()}>목록 새로고침</button>
        <button className="secondary-button" disabled={operationBusy} onClick={newMessage}>새 문자 등록</button>
      </div></div>
      <p className="message-caption">문자를 등록해도 AI 분석이나 상황전파가 자동 실행되지 않습니다.</p>
      {listBusy && <p role="status">기록을 불러오는 중…</p>}
      {listError && <p className="message-error" role="alert">{listError}</p>}
      {!records.length && !listBusy && !listError && <p>등록한 문자가 없습니다.</p>}
      <ul className="message-record-list">{records.map(record => <li key={record.id}>
        <button className="message-record-choice" disabled={operationBusy} aria-pressed={selected?.id === record.id} onClick={() => void act(async signal => {
          const value = await recordRequest<MessageRecord>(token, signal, `/${record.id}`); if (!signal.aborted) choose(value);
        })}>
          <span className="message-tag">{ORIGINS[record.origin]} · {AI_STATES[record.analysis_state]}</span>
          <strong>{record.message.text}</strong>
          <small>{record.message.recipient_regions.join(", ") || "수신지역 미상"} · {issuedTime(record.message.issued_at)} · {{ unreviewed: "미검토", needs_confirmation: "추가 확인", completed: "검토 완료" }[record.review_state]}</small>
        </button>
      </li>)}</ul>
      {cursor && <button className="secondary-button" disabled={operationBusy || listBusy} onClick={() => void loadList(true)}>이전 기록 더 보기</button>}
      <details className="message-official"><summary>공식 재난문자 불러오기</summary>
        {!recordsStatus.feed_configured ? <p>공식 문자 조회 연결 준비 중입니다. 문자를 직접 등록할 수 있습니다.</p> : <>
          <div className="message-form-row"><label>조회 지역<select aria-label="조회 지역" disabled={operationBusy} value={feedRegion} onChange={e => { setFeedRegion(e.target.value); setFeed(null); }}>
            {["대구광역시", "경상북도", "부산광역시", "울산광역시", "경상남도"].map(r => <option key={r}>{r}</option>)}</select></label>
            <label>조회 날짜 (한국 시간)<input type="date" disabled={operationBusy} value={feedDate} max={koreanDate()} onChange={e => { setFeedDate(e.target.value); setFeed(null); }} /></label></div>
          <button className="secondary-button" disabled={operationBusy || !feedDate} onClick={() => void act(async signal => {
            const value = await recordRequest<OfficialPage>(token, signal, "/feed", { region: feedRegion, date: feedDate, page: 1 });
            if (!signal.aborted) setFeed(value);
          })}>최근 문자 조회</button>
          <p className="message-caption">최근 7일 중 하루·지역을 선택합니다. 한 페이지 50건, 최대 3페이지이며 전체 감시 목록이 아닙니다.</p>
        </>}
        {feed && <div><p>{feed.detail}</p>
          {feed.page && <p>{feed.region} · {feed.date} · {feed.page}페이지</p>}
          {!!feed.skipped && <p className="message-notice">필드를 확인할 수 없는 {feed.skipped}건은 제외됐습니다. 전체 목록이 아닐 수 있습니다.</p>}
          {feed.status === "LIVE" && !feed.messages.length && <p>이 페이지에 표시할 문자가 없습니다.</p>}
          <ul className="message-record-list">{feed.messages.map((row, i) => <li key={`${row.official_id}-${i}`}>
            <p>{row.message.text}</p><small>{row.message.recipient_regions.join(", ")} · {issuedTime(row.message.issued_at)}</small>
            <button className="secondary-button" disabled={operationBusy} onClick={() => void act(async signal => {
              const value = await recordRequest<{ record: MessageRecord; registration: string }>(token, signal, "/import", { import_token: row.import_token });
              if (!signal.aborted) { choose(value.record); setNotice(value.registration === "unchanged" ? "이미 등록한 문자입니다. 기존 기록을 열었습니다." : value.registration === "updated" ? "원문 변경을 새 버전으로 저장했습니다. 다시 검토해 주세요." : "공식 문자를 등록했습니다."); await loadList(); }
            })}>이 문자 등록·열기</button>
          </li>)}</ul>
          {feed.page_limit_reached && <p className="message-notice">3페이지 조회 상한에 도달했습니다. 뒤에 문자가 더 있을 수 있습니다.</p>}
          {feed.has_more && !feed.page_limit_reached && <button className="secondary-button" disabled={operationBusy} onClick={() => void act(async signal => {
            const value = await recordRequest<OfficialPage>(token, signal, "/feed", { region: feed.region, date: feed.date, page: (feed.page || 1) + 1 });
            if (!signal.aborted) setFeed(value);
          })}>공식 문자 다음 페이지</button>}
        </div>}
      </details>
    </section>
    {error && <p className="message-error" role="alert">{error}</p>}
    {notice && <p className="message-notice" role="status">{notice}</p>}
    <div className="message-workspace">
      <section className="message-card message-input"><h2>{selected ? "등록한 문자" : "새 문자 등록"}</h2>
        {selected ? <p className="message-caption">{ORIGINS[selected.origin]} · 원문 {selected.source_revision}판 · {AI_STATES[selected.analysis_state]}<br />원문은 보존합니다. 다른 내용은 새 문자로 등록해 주세요.</p> : <div className="message-examples"><p>창작 예문으로 살펴보기</p><div>{examples.map(example => <button key={example.id} className="secondary-button" disabled={operationBusy} onClick={() => {
          setText(example.text); setSource(example.source); setIssuedAt(localInput(example.issued_at)); setRegions(""); setKind("example"); registrationKey.current = null;
        }}>{example.label}</button>)}</div></div>}
        <form onSubmit={event => void submit(event, (event.nativeEvent as SubmitEvent).submitter?.getAttribute("data-action") === "analyze")}>
          <fieldset disabled={operationBusy || completed}>
            <label>문자 원문<textarea aria-label="문자 원문" value={text} minLength={10} maxLength={2000} required rows={6} readOnly={!!selected} onChange={e => { setText(e.target.value); edited(); }} /></label>
            <label>발신처·출처<input value={source} maxLength={80} required readOnly={!!selected} onChange={e => { setSource(e.target.value); edited(); }} /></label>
            <label>발행 시각 (한국 시간)<input type="datetime-local" value={issuedAt} required readOnly={!!selected} onChange={e => { setIssuedAt(e.target.value); edited(); }} /></label>
            <label>문자 수신지역<input value={regions} maxLength={3600} readOnly={!!selected} placeholder="예: 경상남도 창원시 (여러 지역은 쉼표로 구분)" onChange={e => { setRegions(e.target.value); edited(); }} /></label>
            <p className="message-caption">수신지역은 문자 전달 대상이며 실제 사고 장소와 다를 수 있습니다. 공개 문자만 입력해 주세요.</p>
            <label>주변 시설 참고 조회 거리<select value={radius} onChange={e => setRadius(Number(e.target.value) as MessageInput["reference_radius_km"])}>{[1, 3, 5, 10].map(km => <option key={km} value={km}>{km}km</option>)}</select></label>
            {kind === "example" && !selected && <p className="message-notice">창작 예문이며 실제 재난·업무 실적이 아닙니다.</p>}
            <p className="message-caption">분석 시 원문·지역 정보는 OpenAI에, 장소 검색어는 Kakao에 전송됩니다.</p>
            {!selected && <button className="secondary-button message-save" type="submit">문자 등록</button>}
            <button className="primary-button message-submit" type="submit" data-action="analyze" disabled={!status?.configured}>{busy ? "처리 중…" : selected ? "저장된 문자 분석" : "등록하고 분석하기"}</button>
            {!status?.configured && <p className="message-notice">AI 연결 준비 중입니다. 문자 등록과 기록 조회는 가능합니다.</p>}
          </fieldset>
        </form>
        {selected && <div className="message-record-note"><h3>검토 메모</h3>
          <label>검토 상태<select aria-label="검토 상태" disabled={operationBusy || completed} value={review} onChange={e => setReview(e.target.value as typeof review)}><option value="unreviewed">미검토</option><option value="needs_confirmation">추가 확인</option><option value="completed" disabled>검토 완료</option></select></label>
          <label>확인할 사항<textarea aria-label="확인할 사항" disabled={operationBusy || completed} maxLength={1000} rows={3} value={note} onChange={e => setNote(e.target.value)} /></label>
          <button className="secondary-button" disabled={operationBusy || completed} onClick={() => void act(async signal => {
            const value = await recordRequest<MessageRecord>(token, signal, `/${selected.id}`, { expected_version: selected.version, review_state: review, note }, "PATCH");
            if (!signal.aborted) { choose(value); setNotice("검토 메모를 저장했습니다."); await loadList(); }
          })}>검토 메모 저장</button>
          <button className="secondary-button" disabled={operationBusy} onClick={() => void act(async signal => { const value = await recordRequest<MessageRecord>(token, signal, `/${selected.id}`); if (!signal.aborted) choose(value); })}>현재 기록 다시 불러오기</button>
          <button className="secondary-button" disabled={operationBusy} onClick={() => void act(async signal => { const value = await recordRequest<RecordHistory>(token, signal, `/${selected.id}/history`); if (!signal.aborted) { setHistory(value); setPast(null); } })}>변경 이력 보기</button>
          {history && <div className="message-record-history"><h4>변경 이력</h4><ul>{history.versions.map(row => <li key={row.record.version}>
            <button className="secondary-button" disabled={operationBusy} onClick={() => setPast(row.record)}>{row.record.version}판 · {EVENTS[row.event] || "기록 변경"}</button> · {issuedTime(row.record.updated_at)}
          </li>)}</ul>{history.next_cursor && <button className="secondary-button" disabled={operationBusy} onClick={() => void act(async signal => {
            const value = await recordRequest<RecordHistory>(token, signal, `/${selected.id}/history?before=${history.next_cursor}`);
            if (!signal.aborted) setHistory({ versions: [...history.versions, ...value.versions], next_cursor: value.next_cursor });
          })}>더 오래된 이력 보기</button>}</div>}
        </div>}
      </section>
      <div className="message-card message-output" aria-live="polite">
        {busy && <p role="status">조회·저장 또는 분석을 진행하고 있습니다. 분석은 최대 약 80초가 걸릴 수 있습니다.</p>}
        {selected?.analysis_error && <p className="message-notice">{selected.analysis_error}</p>}
        {selected?.analysis_state === "running" && <p className="message-notice">서버에서 분석 중이거나 완료 저장을 확인하지 못했습니다. 기록을 다시 불러와 주세요. 2분 이상 지난 작업은 다시 분석할 수 있습니다.</p>}
        {past ? <><p className="message-notice">과거 {past.version}판을 보고 있습니다. 원문 {past.source_revision}판 · 수정할 수 없습니다.</p><blockquote>{past.message.text}</blockquote><p>{past.note}</p>{past.analysis && renderResult(past.analysis, past.review_state === "completed")}<MessageReviewHistory record={past} /><MessageRelatedHistory record={past} /><MessageSpatialHistory references={past.spatial_references} /><button className="secondary-button" onClick={() => setPast(null)}>현재 결과로 돌아가기</button></>
          : currentResult ? <><p className="message-caption">저장한 분석 {selected.analysis_revision}판 · 조회 거리 {currentResult.input.reference_radius_km}km</p>{currentResult.input.reference_radius_km !== radius && <p className="message-notice">조회 거리 입력이 저장한 분석과 다릅니다. 아래는 이전 분석 결과입니다.</p>}{renderResult(currentResult, completed)}</>
            : <div className="message-empty"><span aria-hidden="true">◎</span><h2>{selected ? "문자가 저장되었습니다" : "문자에서 검토 기록까지"}</h2><p>{selected ? "AI 분석을 실행하면 결과와 조회 과정이 이 기록에 저장됩니다." : "공식 문자를 불러오거나 공개 문자를 직접 등록해 주세요."}</p></div>}
      </div>
    </div>
    {selected?.analysis && !past && <MessageSpatialWorkspace key={selected.id} token={token} record={selected} disabled={busy || reviewBusy || relatedBusy || completed}
      onBusyChange={setSpatialBusy} onDirtyChange={setSpatialDirty} onRecordChanged={updateRecord} />}
    {selected?.analysis && !past && <MessageRelatedPanel key={`related-${selected.id}`} token={token} record={selected} disabled={busy || spatialBusy || reviewBusy}
      unsavedWork={unsavedNote || spatialDirty || draftDirty} onRecordChanged={updateRecord} onBusyChange={setRelatedBusy} />}
    {selected?.analysis && !past && <MessageReviewPanel key={`review-${selected.id}-${selected.analysis_revision}-${selected.relation_epoch || 0}`} token={token} record={selected}
      disabled={busy || spatialBusy || relatedBusy} onDirtyChange={setDraftDirty} unsavedWork={unsavedNote || spatialDirty} onRecordChanged={updateRecord} onBusyChange={setReviewBusy} />}
  </>;
}
