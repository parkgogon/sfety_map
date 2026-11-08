import { useEffect, useRef, useState, type FormEvent } from "react";
import { recordRequest, type MessageRecord, type RecordPage, type RecordStatus } from "./messageRecordsApi";
import type { MessageAnalysisStatus } from "./messageAnalysisApi";
import type { MessageReviewDetail } from "./messageReviewApi";
import MessageQuickReview from "./MessageQuickReview";
import MessageAutomationStatus from "./MessageAutomationStatus";
import examples from "./messageExamples.json";
import "./styles/message_inbox.css";

const ORIGIN = {manual:"직접 입력",example:"창작 예문",official:"공식 API"};
export function messageTime(value: string | null) {
  return value ? new Date(value).toLocaleString("ko-KR", {timeZone:"Asia/Seoul",dateStyle:"short",timeStyle:"short"}) : "발행 시각 미상";
}
function advancedUrl(id?: string) {return `/control/messages?view=advanced${id ? `&record_id=${encodeURIComponent(id)}` : ""}`;}

function CompletedReview({token,record,onChange}:{token:string;record:MessageRecord;onChange:(r:MessageRecord)=>void}) {
  const [detail,setDetail]=useState<MessageReviewDetail|null>(null); const [error,setError]=useState("");
  const [notice,setNotice]=useState(""); const [busy,setBusy]=useState(false);
  const operation=useRef<AbortController|null>(null); const working=useRef(false);
  useEffect(()=>{const c=new AbortController();void recordRequest<MessageReviewDetail>(token,c.signal,`/${record.id}/review`).then(v=>{if(!c.signal.aborted)setDetail(v);}).catch(e=>{if(!c.signal.aborted)setError(e instanceof Error?e.message:"저장한 결과를 확인하지 못했습니다.");});return()=>{c.abort();operation.current?.abort();};},[token,record.id,record.version]);
  async function act(copy:boolean) {
    if(working.current)return;working.current=true;setBusy(true);setError("");const c=new AbortController();operation.current=c;
    try {
      if(copy){const value=await recordRequest<{text:string}>(token,c.signal,`/${record.id}/notice-copy`,{expected_version:record.version,draft_revision:detail!.draft!.revision});
        await navigator.clipboard.writeText(value.text);if(!c.signal.aborted)setNotice("안내문을 복사했습니다. 기존 보고·전달에 사용할 수 있습니다.");
      }else{const value=await recordRequest<MessageRecord>(token,c.signal,`/${record.id}/reopen`,{expected_version:record.version,reason:"관리자가 내용 보완을 위해 검토를 다시 엶"});if(!c.signal.aborted)onChange(value);}
    }catch(e){if(!c.signal.aborted)setError(e instanceof Error?e.message:"작업을 완료하지 못했습니다.");}
    finally{working.current=false;if(!c.signal.aborted)setBusy(false);}
  }
  return <section className="message-card quick-completed" aria-label="저장한 검토 결과"><span className="message-tag">내부 검토 완료</span><h2>검토 결과가 저장되어 있습니다</h2>
    <p>확인 대상 {record.review_completion?.selected_unique_count || 0}개소 · {messageTime(record.review_completion?.completed_at||null)}</p>
    {!detail&&!error&&<p role="status">저장한 초안의 근거를 확인하고 있습니다…</p>}
    {detail&&!detail.draft_current&&<p className="message-error" role="alert">{detail.stale_reason||"근거가 바뀌어 다시 검토해야 합니다."}</p>}
    {error&&<p role="alert" className="message-error">{error}</p>}{notice&&<p role="status" className="message-notice">{notice}</p>}
    {detail?.draft&&<pre className="quick-saved-notice" aria-label="저장한 안내 초안">{detail.draft.text}</pre>}
    <div className="quick-review-actions"><button className="primary-button" disabled={busy||!detail?.draft_current} onClick={()=>void act(true)}>안내문 복사</button><button className="secondary-button" disabled={busy} onClick={()=>void act(false)}>내용 보완·다시 검토</button></div>
    <p className="message-caption">내부 검토 기록입니다. 현장 확인이나 실제 발송·수신 여부를 뜻하지 않습니다.</p>
    <details><summary>위치·시설·변경 이력 자세히 보기</summary><a href={advancedUrl(record.id)}>상세 관리 열기</a></details>
  </section>;
}

export default function MessageInbox({token,status,recordsStatus}:{token:string;status:MessageAnalysisStatus|null;recordsStatus:RecordStatus}) {
  const [records,setRecords]=useState<MessageRecord[]>([]); const [cursor,setCursor]=useState<string|null>(null);
  const [record,setRecord]=useState<MessageRecord|null>(null); const [showForm,setShowForm]=useState(false);
  const [filter,setFilter]=useState("all");const [listError,setListError]=useState("");const [error,setError]=useState("");const [notice,setNotice]=useState("");
  const [busy,setBusy]=useState(false); const [loading,setLoading]=useState(true); const [reviewBusy,setReviewBusy]=useState(false); const [dirty,setDirty]=useState(false);
  const [text,setText]=useState("");const [source,setSource]=useState("");const [issued,setIssued]=useState("");const [regions,setRegions]=useState("");
  const [kind,setKind]=useState<"manual"|"example">("manual");const [exampleMode,setExampleMode]=useState(false);
  const op=useRef<AbortController|null>(null); const registration=useRef<string|null>(null); const submitting=useRef(false);
  async function list(signal:AbortSignal,append=false,poll=false) {
    try {const page=await recordRequest<RecordPage>(token,signal,append&&cursor?`?before=${encodeURIComponent(cursor)}`:"");if(!signal.aborted){setRecords(old=>append?[...old,...page.records.filter(r=>!old.some(o=>o.id===r.id))]:poll?[...page.records,...old.filter(r=>!page.records.some(n=>n.id===r.id))]:page.records);if(!poll)setCursor(page.next_cursor);setListError("");}}
    catch(e){if(!signal.aborted)setListError(e instanceof Error?e.message:"기록을 불러오지 못했습니다.");}
  }
  function choose(value:MessageRecord|null) {
    setRecord(value);setDirty(false);setShowForm(false);const url=new URL(window.location.href);
    if(value)url.searchParams.set("record_id",value.id);else url.searchParams.delete("record_id");
    window.history.replaceState({},"",url.pathname+url.search);
  }
  useEffect(()=>{const c=new AbortController();void list(c.signal);
    const id=new URLSearchParams(window.location.search).get("record_id");
    const restore=async()=>{try{if(id){const value=await recordRequest<MessageRecord>(token,c.signal,`/${encodeURIComponent(id)}`);if(!c.signal.aborted)choose(value);}}catch(e){if(!c.signal.aborted)setError(e instanceof Error?e.message:"기록을 열지 못했습니다.");}finally{if(!c.signal.aborted)setLoading(false);}};
    void restore();return()=>{c.abort();op.current?.abort();};
  // A new token starts a new authenticated workspace; paging is user-driven.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  },[token]);
  async function open(id:string) {
    if(dirty&&!window.confirm("저장 전 수정 내용을 취소하고 다른 기록을 열까요?"))return;
    op.current?.abort();const c=new AbortController();op.current=c;setBusy(true);setError("");setNotice("");
    try{const value=await recordRequest<MessageRecord>(token,c.signal,`/${id}`);if(!c.signal.aborted)choose(value);}
    catch(e){if(!c.signal.aborted)setError(e instanceof Error?e.message:"기록을 열지 못했습니다.");}
    finally{if(!c.signal.aborted)setBusy(false);}
  }
  function newInput(example:boolean) {
    if(dirty&&!window.confirm("저장 전 수정 내용을 취소하고 새 문자를 입력할까요?"))return;
    choose(null);setShowForm(true);setExampleMode(example);setText("");setSource("");setIssued("");setRegions("");setKind(example?"example":"manual");registration.current=null;setError("");setNotice("");
  }
  async function analyze(value:MessageRecord,c:AbortController) {
    const saved=await recordRequest<MessageRecord>(token,c.signal,`/${value.id}/analyze`,{expected_version:value.version,reference_radius_km:value.reference_radius_km});
    if(!c.signal.aborted){choose(saved);await list(c.signal);}
  }
  async function submit(e:FormEvent) {
    e.preventDefault();if(submitting.current||!status?.configured)return;submitting.current=true;setBusy(true);setError("");
    const c=new AbortController();op.current=c;
    try {
      registration.current??=crypto.randomUUID();
      const value=await recordRequest<{record:MessageRecord}>(token,c.signal,"",{registration_key:registration.current,text:text.trim(),source:source.trim()||(kind==="example"?"창작 예문":"공개 문자 수동 입력"),issued_at:issued?`${issued}:00+09:00`:null,recipient_regions:regions.split(",").map(s=>s.trim()).filter(Boolean),input_kind:kind,reference_radius_km:3});
      if(!c.signal.aborted){
        choose(value.record);await list(c.signal);
        if(value.record.analysis_state!=="completed"&&value.record.analysis_state!=="running")await analyze(value.record,c);
      }
    }catch(e){if(!c.signal.aborted){setError(e instanceof Error?e.message:"등록 또는 분석을 완료하지 못했습니다.");const id=new URLSearchParams(window.location.search).get("record_id");if(id){try{const latest=await recordRequest<MessageRecord>(token,c.signal,`/${id}`);if(!c.signal.aborted)choose(latest);}catch{/* Preserve the saved record and report the original failure. */}}}}
    finally{submitting.current=false;if(!c.signal.aborted)setBusy(false);}
  }
  async function analyzeSaved(){if(!record||submitting.current)return;submitting.current=true;setBusy(true);setError("");const c=new AbortController();op.current=c;try{await analyze(record,c);}catch(e){if(!c.signal.aborted)setError(e instanceof Error?e.message:"분석을 완료하지 못했습니다.");}finally{submitting.current=false;if(!c.signal.aborted)setBusy(false);}}
  function changed(value:MessageRecord){choose(value);const c=new AbortController();op.current=c;void list(c.signal);}
  const category=(r:MessageRecord)=>r.review_state==="completed"?"completed":r.review_state==="needs_confirmation"||r.analysis_state==="failed"?"attention":"pending";
  const visible=records.filter(r=>filter==="all"||category(r)===filter);
  return <div className="message-inbox">
    <section className="message-collection"><MessageAutomationStatus token={token} onRefresh={signal=>{if(!record&&!showForm&&!busy&&!reviewBusy&&!dirty)return list(signal,false,true);}}/>
      <div className="quick-entry-actions"><button className="primary-button" disabled={busy||reviewBusy} onClick={()=>newInput(false)}>문자 붙여넣기</button><button className="secondary-button" disabled={busy||reviewBusy} onClick={()=>newInput(true)}>예문으로 시연</button></div>
    </section>
    {status&&!status.configured&&<p className="message-error">문자 분석 연결이 설정되지 않았습니다. 기존 검토 기록은 계속 확인할 수 있습니다.</p>}
    {recordsStatus.storage_mode==="memory"&&<p className="message-notice">로컬 임시 저장입니다. 서버를 다시 시작하면 기록이 사라집니다.</p>}
    {(record||showForm)&&<button className="secondary-button inbox-back" disabled={busy||reviewBusy} onClick={()=>{if(dirty&&!window.confirm("저장 전 수정 내용을 취소하고 대기함으로 돌아갈까요?"))return;choose(null);}}>← 검토 대기함</button>}
    {!record&&!showForm&&<section className="message-card inbox-list" aria-label="검토 대기함"><div className="quick-heading"><div><h2>검토 대기함</h2><p className="message-caption">상황을 열고 준비된 위치·시설·안내 내용을 확인해 주세요.</p></div><button className="secondary-button" disabled={busy||reviewBusy} onClick={()=>{const c=new AbortController();op.current=c;void list(c.signal);}}>목록 새로고침</button></div>
      <div className="inbox-filters" role="group" aria-label="기록 분류">{[["all","전체"],["pending","검토 대기"],["attention","확인 필요"],["completed","완료"]].map(([key,label])=><button key={key} className="secondary-button" disabled={busy||reviewBusy} aria-pressed={filter===key} onClick={()=>setFilter(key)}>{label}</button>)}</div>
      {listError&&<p role="alert" className="message-error">{listError}</p>}
      {!records.length&&!listError&&<p>아직 등록한 문자가 없습니다. 위에서 문자를 입력하거나 예문을 선택해 주세요.</p>}
      {!!records.length&&!visible.length&&<p>불러온 기록 중 이 분류의 문자가 없습니다.</p>}
      <ul className="inbox-records">{visible.map(r=><li key={r.id}><button disabled={busy||reviewBusy} onClick={()=>void open(r.id)}>
        <span className="message-tag">{ORIGIN[r.origin]} · {{pending:"검토 대기",attention:"확인 필요",completed:"완료"}[category(r)]}</span><strong>{r.analysis?.analysis.summary||r.message.text}</strong><small>{r.message.recipient_regions.join(", ")||"수신지역 미상"} · {messageTime(r.message.issued_at)}{r.analysis_state==="running"?" · 분석 중":r.analysis_state==="not_analyzed"?" · 분석 전":""}</small>
      </button></li>)}</ul>
      {cursor&&<button className="secondary-button" disabled={busy||reviewBusy} onClick={()=>{const c=new AbortController();op.current=c;void list(c.signal,true);}}>이전 기록 더 보기</button>}
    </section>}
    {error&&<p className="message-error" role="alert">{error}</p>}{notice&&<p className="message-notice" role="status">{notice}</p>}
    {loading&&<p role="status">기록을 불러오는 중…</p>}
    {showForm&&<section className="message-card inbox-input"><h2>{exampleMode?"창작 예문으로 시연":"공개 문자 붙여넣기"}</h2>
      {exampleMode&&<div className="message-examples">{examples.map(ex=><button key={ex.id} className="secondary-button" disabled={busy} onClick={()=>{setText(ex.text);setSource(ex.source);setIssued(ex.issued_at.slice(0,16));setKind("example");registration.current=null;}}>{ex.label}</button>)}</div>}
      <form onSubmit={e=>void submit(e)}><fieldset disabled={busy}><label>문자 원문<textarea required minLength={10} maxLength={2000} rows={5} value={text} onChange={e=>{setText(e.target.value);registration.current=null;}} placeholder="공개 재난문자 원문을 붙여넣으세요."/></label>
        {kind==="example"&&<p className="message-notice">창작 예문입니다. 실제 재난·업무 실적과 구분해 저장합니다.</p>}
        <details><summary>출처·발행 시각·수신지역 추가 · 선택</summary><p className="message-caption">발행 시각을 모르면 비워두세요. 입력 시각을 발행 시각으로 사용하지 않습니다.</p>
          <label>발신처·출처<input maxLength={80} value={source} onChange={e=>{setSource(e.target.value);registration.current=null;}} placeholder="공개 문자 수동 입력"/></label>
          <label>발행 시각 (한국 시간)<input type="datetime-local" value={issued} onChange={e=>{setIssued(e.target.value);registration.current=null;}}/></label>
          <label>문자 수신지역<input maxLength={3600} value={regions} onChange={e=>{setRegions(e.target.value);registration.current=null;}} placeholder="예: 대구광역시 달서구, 경상북도 경산시"/></label>
        </details><p className="message-caption">분석 시 공개 원문은 OpenAI에, 장소 검색어는 Kakao에 전송됩니다.</p>
        <button className="primary-button" disabled={busy||!status?.configured||text.trim().length<10}>등록하고 검토안 준비</button>
      </fieldset></form>
    </section>}
    {busy&&<p role="status">{record?"저장한 문자를 분석하고 있습니다. 최대 약 80초가 걸릴 수 있습니다…":"기록을 불러오거나 저장하고 있습니다…"}</p>}
    {record&&<section className="message-card quick-situation"><span className="message-tag">{ORIGIN[record.origin]}</span><h2>{record.analysis?.analysis.summary||"등록한 문자"}</h2><p className="message-caption">{record.message.source} · {messageTime(record.message.issued_at)} · {record.message.recipient_regions.join(", ")||"수신지역 미상"}</p>
      {record.origin==="example"&&<p className="message-notice">창작 예문이며 실제 재난·업무 실적이 아닙니다.</p>}
      <details><summary>원문 보기</summary><blockquote>{record.message.text}</blockquote></details>
      {record.analysis_error&&<p role="alert" className="message-error">{record.analysis_error}</p>}
      {record.analysis_state==="failed"&&record.analysis&&<p className="message-notice">마지막 저장 분석입니다. 새 분석이 실패했으므로 현재 정보를 확인해 주세요.</p>}
      {!busy&&record.analysis_state==="running"&&<button className="secondary-button" onClick={()=>void open(record.id)}>분석 상태 새로고침</button>}
      {!busy&&record.review_state!=="completed"&&record.analysis_state!=="running"&&(!record.analysis||record.analysis_state==="failed")&&<button className="primary-button" disabled={!status?.configured} onClick={()=>void analyzeSaved()}>저장한 문자로 검토안 준비</button>}
      <details><summary>검색 과정·변경 이력·후속 문자 관리</summary>{record.analysis&&<ol>{record.analysis.trace.map((step,i)=><li key={i}>{step.detail}</li>)}</ol>}<a href={advancedUrl(record.id)} onClick={e=>{if(reviewBusy||dirty&&!window.confirm("저장 전 수정 내용을 취소하고 상세 관리를 열까요?"))e.preventDefault();}}>상세 관리 열기</a></details>
    </section>}
    {record&&!busy&&(record.review_state==="completed"?<CompletedReview key={`${record.id}:${record.version}`} token={token} record={record} onChange={changed}/>:record.analysis&&record.analysis_state!=="running"?<MessageQuickReview key={`${record.id}:${record.version}`} token={token} record={record} onChange={changed} onHold={value=>{changed(value);choose(null);setNotice("추가 확인이 필요한 기록으로 보류했습니다.");}} onBusyChange={setReviewBusy} onDirtyChange={setDirty}/>:null)}
  </div>;
}
