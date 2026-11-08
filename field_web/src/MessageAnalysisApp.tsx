import { useEffect, useRef, useState, type FormEvent } from "react";
import { useAdminSession } from "./useAdminSession";
import { navigateWithMode } from "./router";
import { INTENT_LABELS, ROLE_LABELS, messageRequest, type MessageAnalysisResult, type MessageAnalysisStatus, type MessageInput } from "./messageAnalysisApi";
import examples from "./messageExamples.json";
import "./styles/message_analysis.css";
import MessageRecordWorkspace from "./MessageRecordWorkspace";
import { recordRequest, type RecordStatus } from "./messageRecordsApi";

function koreanTime(value: string): string {
  return new Intl.DateTimeFormat("ko-KR", { timeZone: "Asia/Seoul", dateStyle: "medium", timeStyle: "short" }).format(new Date(value));
}

export function MessageAnalysisOutput({ result, reviewCompleted = false }: { result: MessageAnalysisResult; reviewCompleted?: boolean }) {
  const { analysis } = result;
  return <section className="message-result" aria-label="문자 분석 결과">
    <div className="message-result-heading"><h2>검토 초안</h2><span className="message-tag">{reviewCompleted ? "검토에 사용한 AI 초안" : "담당자 검토 전"}</span></div>
    <p className="message-summary">{analysis.summary}</p>
    <p className="message-caption">{{ example: "창작 예문", manual: "수동 입력", official: "공식 API" }[result.input.input_kind]} · {result.input.source} · 발행 {koreanTime(result.input.issued_at)} (한국 시간)</p>
    {!!result.input.recipient_regions?.length && <p className="message-caption">문자 수신지역: {result.input.recipient_regions.join(", ")}</p>}
    <p className="message-notice">이 문자 발행 시점의 내용입니다. 현재 상황과 후속 해제·정정은 별도로 확인해 주세요.</p>
    {analysis.parts.map((part, index) => <article className="message-part" key={index}>
      <span className="message-tag">{INTENT_LABELS[part.intent]}</span>
      <h3>{part.description}</h3>
      <blockquote>{part.evidence}</blockquote>
      <p className="message-caption">시점 근거: {part.time_text || "명시되지 않음"}
        {part.starts_at && <> · 시작 {koreanTime(part.starts_at)}</>}
        {part.ends_at && <> · 종료 {koreanTime(part.ends_at)}</>}
      </p>
      {part.locations.map((location, locationIndex) => <div className="message-location" key={locationIndex}>
        <strong>{ROLE_LABELS[location.role]} · {location.text}</strong>
        <p className="message-caption">근거: “{location.evidence}”</p>
        {location.candidate_ids.length === 0 ? <p>위치 미확인 · 원문 지역 또는 지도 위치를 확인해 주세요.</p> : <ul>
          {location.candidate_ids.map(id => {
            const candidate = result.candidates.find(row => row.id === id);
            return candidate ? <li key={id}>미확정 후보: {candidate.name}<span className="message-caption"> · {candidate.address}</span>
              {candidate.scope_matches_source === false && <p className="message-notice">지역을 먼저 확인해 주세요. 이 후보의 주변 시설 조회는 보류합니다.</p>}</li> : null;
          })}
        </ul>}
      </div>)}
    </article>)}
    {analysis.questions.length > 0 && <aside className="message-notice"><h3>추가로 확인할 내용</h3><ul>{analysis.questions.map((question, index) => <li key={index}>{question}</li>)}</ul></aside>}
    <section className="message-nearby"><h3>장소 후보 주변의 참고 시설</h3>
      <p>선택한 {result.input.reference_radius_km}km는 조회 거리입니다. 위험 범위나 피해 시설을 뜻하지 않습니다. 넓은 지역·도로 구간은 대표점과 실제 범위가 다를 수 있습니다.</p>
      {result.nearby.length === 0 && <p className="message-caption">주변 시설 조회 결과가 없습니다. 조회 생략·실패 또는 위치 미확인일 수 있으며, 안전 판정이 아닙니다.</p>}
      {result.nearby.map(lookup => <div className="message-part" key={lookup.candidate_id}>
        <h4>{result.candidates.find(place => place.id === lookup.candidate_id)?.name} 후보 기준 · {lookup.total_count}개소</h4>
        {lookup.total_count > lookup.shown_count && <p>가까운 {lookup.shown_count}개소를 표시합니다.</p>}
        {lookup.total_count === 0 ? <p>이 후보의 조회 거리 안에 등록 시설이 없습니다. 다른 장소·범위는 확인되지 않았습니다.</p> : <ul className="message-facilities">
          {lookup.facilities.map(facility => <li key={facility.id}>
            <a href={`/?facility_id=${encodeURIComponent(facility.id)}`} target="_blank" rel="noreferrer">{facility.name} ↗</a>
            <span>{facility.facility_type} · 직선 {(facility.distance_m / 1000).toFixed(2)}km</span>
            <small>{facility.address}</small>
          </li>)}
        </ul>}
      </div>)}
    </section>
    <details className="message-trace"><summary>AI의 조회 과정 · {result.model_calls}회 응답 · {(result.elapsed_ms / 1000).toFixed(1)}초</summary>
      <ol>{result.trace.map((step, index) => <li key={index}>{step.detail}</li>)}</ol>
      <p className="message-caption">모델: {result.model} · 인용과 후보 식별자 검증은 의미 해석의 정확성을 보증하지 않습니다.</p>
    </details>
    <details><summary>분석에 사용한 원문</summary><blockquote>{result.input.text}</blockquote></details>
  </section>;
}

export default function MessageAnalysisApp() {
  const auth = useAdminSession();
  const [recordsStatus, setRecordsStatus] = useState<RecordStatus | null>(null);
  const [recordsError, setRecordsError] = useState("");
  const [status, setStatus] = useState<MessageAnalysisStatus | null>(null);
  const [text, setText] = useState("");
  const [source, setSource] = useState("");
  const [issuedAt, setIssuedAt] = useState("");
  const [radius, setRadius] = useState<MessageInput["reference_radius_km"]>(3);
  const [kind, setKind] = useState<MessageInput["input_kind"]>("manual");
  const [result, setResult] = useState<MessageAnalysisResult | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const pending = useRef<AbortController | null>(null);

  useEffect(() => {
    setRecordsStatus(null); setRecordsError(""); setStatus(null); setResult(null); setError(""); setBusy(false);
    if (!auth.adminToken) return;
    const controller = new AbortController();
    void messageRequest<MessageAnalysisStatus>(auth.adminToken, controller.signal).then(value => {
      if (!controller.signal.aborted) setStatus(value);
    }).catch(error => {
      if (!controller.signal.aborted) setError(error instanceof Error ? error.message : "연결 상태를 확인하지 못했습니다.");
    });
    void recordRequest<RecordStatus>(auth.adminToken, controller.signal, "/status").then(value => {
      if (!controller.signal.aborted) setRecordsStatus(value);
    }).catch(() => {
      if (!controller.signal.aborted) setRecordsError("검토 기록 저장 연결을 확인하지 못했습니다. 아래 분석 결과는 화면에서만 확인할 수 있습니다.");
    });
    return () => { controller.abort(); pending.current?.abort(); };
  }, [auth.adminToken]);

  const edited = () => { setKind("manual"); setResult(null); setError(""); };
  const chooseExample = (id: string) => {
    const example = examples.find(item => item.id === id);
    if (!example) return;
    setText(example.text); setSource(example.source); setIssuedAt(example.issued_at.slice(0, 16));
    setKind("example"); setResult(null); setError("");
  };
  const analyze = async (event: FormEvent) => {
    event.preventDefault();
    if (busy || !status?.configured) return;
    const controller = new AbortController();
    pending.current = controller;
    setBusy(true); setError(""); setResult(null);
    try {
      const value = await messageRequest<MessageAnalysisResult>(auth.adminToken, controller.signal, {
        text: text.trim(), source: source.trim(), issued_at: `${issuedAt}:00+09:00`,
        reference_radius_km: radius, input_kind: kind,
      });
      if (!controller.signal.aborted) setResult(value);
    } catch (error) {
      if (!controller.signal.aborted) setError(error instanceof Error ? error.message : "분석하지 못했습니다.");
    } finally {
      if (!controller.signal.aborted) setBusy(false);
    }
  };

  return <div className="control-shell message-shell">
    <header className="control-header">
      <div className="control-brand"><span className="brand-mark">K-ECO SAFETY MONITORING</span><h1>재난문자 검토</h1></div>
      <div className="control-header-actions">
        <button className="secondary-button" onClick={() => navigateWithMode("/control")}>중앙 관제 ↗</button>
        {auth.adminToken && <button className="secondary-button" onClick={auth.handleLogout}>로그아웃</button>}
      </div>
    </header>
    <main className="message-main">
      {!auth.adminToken ? <section className="message-card message-login"><h2>관리자 인증이 필요합니다</h2><p>재난문자 분석과 참고 시설 조회를 위해 로그인해 주세요.</p>
        <form onSubmit={auth.handleLogin} className="login-form">
          <label>관리자 비밀번호<input type="password" value={auth.passwordInput} autoComplete="current-password" onChange={event => auth.setPasswordInput(event.target.value)} required /></label>
          <button className="primary-button" disabled={auth.authLoading}>{auth.authLoading ? "인증 중…" : "로그인"}</button>
          {auth.authError && <p role="alert">{auth.authError}</p>}
        </form>
      </section> : <>
        <section className="message-intro"><span className="message-tag">시범 기능</span><h2>문자의 맥락을 읽고,<br />확인할 장소를 좁힙니다.</h2>
          <p>발생·예방·통제를 구분하고, 필요한 경우 장소와 주변 시설을 조회합니다.</p>
          <p className="message-caption">AI 결과는 검토용 참고자료이며 공식 특보 위험등급과 별개입니다.</p>
        </section>
        {!recordsStatus && !recordsError ? <p role="status">검토 기록 연결을 확인하고 있습니다…</p> : recordsStatus?.storage_configured ? <MessageRecordWorkspace token={auth.adminToken} status={status} recordsStatus={recordsStatus} renderResult={(value, completed) => <MessageAnalysisOutput result={value} reviewCompleted={completed} />} /> : <>
        {recordsError && <p className="message-error" role="alert">{recordsError}</p>}
        {recordsStatus && !recordsStatus.storage_configured && <p className="message-notice">검토 기록 저장소가 연결되지 않았습니다. 아래 결과는 저장되지 않으며 새로고침하면 초기화됩니다.</p>}
        <div className="message-workspace">
          <section className="message-card message-input"><h2>분석할 문자</h2>
            <div className="message-examples"><p>창작 예문으로 살펴보기</p><div>{examples.map(example => <button type="button" className="secondary-button" key={example.id} disabled={busy} onClick={() => chooseExample(example.id)}>{example.label}</button>)}</div></div>
            <form onSubmit={event => void analyze(event)}>
              <fieldset disabled={busy}>
                <label>문자 원문<textarea value={text} minLength={10} maxLength={2000} rows={7} required placeholder="공개된 재난문자를 붙여 넣으세요." onChange={event => { setText(event.target.value); edited(); }} /></label>
                <div className="message-form-row">
                  <label>발신처·출처<input value={source} maxLength={80} required placeholder="예: ○○시 공개 재난문자" onChange={event => { setSource(event.target.value); edited(); }} /></label>
                  <label>발행 시각 (한국 시간)<input type="datetime-local" value={issuedAt} required onChange={event => { setIssuedAt(event.target.value); edited(); }} /></label>
                </div>
                <label>주변 시설 참고 조회 거리<select value={radius} onChange={event => { setRadius(Number(event.target.value) as MessageInput["reference_radius_km"]); setResult(null); }}>{[1, 3, 5, 10].map(km => <option value={km} key={km}>{km}km</option>)}</select></label>
                <p className="message-caption">공개 문자만 입력해 주세요. 분석 시 원문은 OpenAI에, 장소 검색어는 Kakao에 전송됩니다.</p>
                {kind === "example" && <p className="message-notice">창작한 시연용 문자입니다. 실제 재난·업무 실적이 아닙니다.</p>}
                {status && !status.configured && <p className="message-notice">AI 연결 준비 중입니다. 서버 연결을 설정한 뒤 분석할 수 있습니다.</p>}
                {status?.configured && !status.place_search_configured && <p className="message-notice">문자 해석은 가능합니다. 장소 검색이 연결되지 않아 위치·주변 시설은 확인되지 않습니다.</p>}
                <button className="primary-button message-submit" disabled={busy || !status?.configured}>{busy ? "문자를 해석하고 필요한 자료를 조회하는 중…" : "문자 분석하기"}</button>
              </fieldset>
            </form>
            {error && <p className="message-error" role="alert">{error}</p>}
            {busy && <p role="status">조회할 자료에 따라 최대 약 80초가 걸릴 수 있습니다.</p>}
          </section>
          <div className="message-card message-output" aria-live="polite">
            {result ? <MessageAnalysisOutput result={result} /> : <div className="message-empty"><span aria-hidden="true">◎</span><h2>{busy ? "근거를 확인하고 있습니다" : "원문에서 확인까지"}</h2>
              <ol><li>상황·시점·장소 역할 해석</li><li>필요한 장소·시설 자료 조회</li><li>근거와 확인 질문을 포함한 초안</li></ol>
              <p>분석을 마치면 AI가 선택한 조회 과정도 함께 볼 수 있습니다.</p>
            </div>}
          </div>
        </div>
        </>}
      </>}
    </main>
  </div>;
}
