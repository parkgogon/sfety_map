import { useEffect, useRef, useState } from "react";
import { recordRequest, type MessageRecord, type RecordPage } from "./messageRecordsApi";
import type { MessageSegment, RelatedDetail, RelatedPreview } from "./messageRelationsApi";

const KINDS = { additional: "추가 안내", correction: "정정", release: "해제 관련" };
const INTENTS: Record<string,string> = {event:"발생",prevention:"예방",advisory:"안내",scheduled_restriction:"예정 통제",active_restriction:"통제 유지",release:"해제",correction:"정정",unknown:"판단 보류"};
const ROLES: Record<string,string> = {incident_site:"발생 장소",restricted_area:"통제 장소",evacuation_destination:"대피 목적지",evacuation_area:"대피 대상 지역",reference:"참고 장소"};
const ORIGINS = {example:"창작 예문",manual:"수동 입력",official:"공식 API"};
function time(value: string | null) { return value ? new Date(value).toLocaleString("ko-KR", {timeZone:"Asia/Seoul"}) + " (한국 시간)" : "발행 시각 미상"; }
function Parts({parts}: {parts: MessageSegment[]}) {
  return <ul className="message-segment-list">{parts.map(p => <li key={p.index}><strong>{INTENTS[p.intent] || p.intent}</strong><blockquote>{p.evidence}</blockquote>
    {p.starts_at && <p>시작: {time(p.starts_at)}</p>}{p.ends_at && <p>종료·해제: {time(p.ends_at)}</p>}
    <p>{p.locations.map(l => `${ROLES[l.role] || l.role}: ${l.text}`).join(" · ") || "명시한 장소 없음"}</p></li>)}</ul>;
}
export default function MessageRelatedPanel({token,record,disabled,unsavedWork,onRecordChanged,onBusyChange}: {
  token:string; record:MessageRecord; disabled:boolean; unsavedWork:boolean;
  onRecordChanged:(r:MessageRecord)=>void; onBusyChange:(busy:boolean)=>void;
}) {
  const [detail,setDetail] = useState<RelatedDetail|null>(null); const [page,setPage] = useState<RecordPage|null>(null);
  const [preview,setPreview] = useState<RelatedPreview|null>(null); const [reload,setReload] = useState(0);
  const [kind,setKind] = useState<keyof typeof KINDS>("additional"); const [reason,setReason] = useState("");
  const [confirmed,setConfirmed] = useState(false); const [cross,setCross] = useState(false); const [crossReason,setCrossReason] = useState("");
  const [unlinkId,setUnlinkId] = useState(""); const [unlinkReason,setUnlinkReason] = useState("");
  const [busy,setBusy] = useState(false); const [loading,setLoading] = useState(false); const [error,setError] = useState("");
  const operation = useRef<AbortController|null>(null); const mounted=useRef(true);
  useEffect(() => { mounted.current=true; return () => { mounted.current=false; operation.current?.abort(); }; },[]);
  useEffect(() => {
    const controller = new AbortController(); setLoading(true); setDetail(null); setPreview(null); setPage(null); setError("");
    setReason(""); setConfirmed(false); setCross(false); setCrossReason(""); setUnlinkId(""); setUnlinkReason("");
    void recordRequest<RelatedDetail>(token,controller.signal,`/${record.id}/related`).then(v=>{if(!controller.signal.aborted)setDetail(v);})
      .catch(e=>{if(!controller.signal.aborted)setError(e instanceof Error?e.message:"후속 정보를 불러오지 못했습니다.");})
      .finally(()=>{if(!controller.signal.aborted)setLoading(false);});
    return ()=>controller.abort();
  },[token,record.id,record.version,reload]);
  async function run(work:(signal:AbortSignal)=>Promise<void>) {
    operation.current?.abort(); const controller=new AbortController(); operation.current=controller;
    setBusy(true); onBusyChange(true); setError("");
    try { await work(controller.signal); } catch(e){if(!controller.signal.aborted)setError(e instanceof Error?e.message:"작업을 완료하지 못했습니다.");}
    finally{if(mounted.current){setBusy(false);onBusyChange(false);}}
  }
  function compare(target:string) { void run(async signal=>{
    setPreview(null);setConfirmed(false);setCross(false);setCrossReason("");setReason("");
    const v=await recordRequest<RelatedPreview>(token,signal,`/${record.id}/related/preview?target_id=${encodeURIComponent(target)}`);
    if(!signal.aborted){setPreview(v);setKind(detail?.links.find(l=>l.parent_id===record.id&&l.target.id===target)?.edge.kind||"additional");}
  }); }
  const locked=disabled||busy||loading||!detail||detail.record_version!==record.version;
  const existing=preview&&detail?.links.some(l=>l.parent_id===record.id&&l.target.id===preview.target.id);
  return <section className="message-card message-related" aria-label="후속 문자 연결과 구간 비교">
    <div className="message-record-toolbar"><h2>후속 문자 연결 · 구간 비교</h2><button className="secondary-button" disabled={disabled||busy} onClick={()=>setReload(n=>n+1)}>후속 연결 다시 불러오기</button></div>
    <p>같은 상황의 추가·정정·해제 문자를 직접 확인해 연결합니다. 각 원문과 분석은 별도 기록으로 보존합니다.</p>
    <p className="message-caption">연결·재확인·해제 시 기존 검토 완료와 초안은 무효화됩니다. 직접 연결 최대 10건·연쇄 4단계·전체 30건입니다.</p>
    {loading&&<p role="status">후속 연결을 확인하는 중…</p>}{error&&<p role="alert" className="message-error">{error}</p>}
    {unsavedWork&&<p className="message-notice">저장하지 않은 메모·기준점·시설 선택·추가 안내가 있습니다. 저장하거나 되돌린 뒤 연결을 변경해 주세요.</p>}
    {detail&&detail.record_version!==record.version&&<p className="message-notice">현재 기록을 다시 불러와 주세요.</p>}
    {detail?.needs_reconfirm&&<p className="message-notice">후속 원문·분석 또는 연결이 바뀌었습니다. 해당 연결의 비교를 다시 확인해야 검토를 완료할 수 있습니다.</p>}
    {detail&&!detail.links.length&&<p>연결한 후속 문자가 없습니다.</p>}
    <ul className="message-record-list">{detail?.links.map(link=><li key={`${link.parent_id}-${link.target.id}`}>
      <strong>{KINDS[link.edge.kind]} · {ORIGINS[link.target.origin]} · {link.needs_reconfirm?"재확인 필요":"연결 확인됨"}</strong>
      <p>{link.target.message.text}</p><small>{time(link.target.message.issued_at)} · {link.target.message.recipient_regions.join(", ")||"수신지역 미상"}</small>
      <p>연결 사유: {link.edge.reason}</p>{link.edge.cross_region_reason&&<p>지역 간 연결 근거: {link.edge.cross_region_reason}</p>}
      <a href={`/control/messages?record_id=${encodeURIComponent(link.target.id)}`} target="_blank" rel="noreferrer">후속 원문 별도 열기</a>
      {link.parent_id===record.id?<div className="message-record-toolbar"><button className="secondary-button" disabled={locked} onClick={()=>compare(link.target.id)}>이 연결 비교·재확인</button>
        <button className="secondary-button" disabled={locked||unsavedWork} onClick={()=>{setUnlinkId(link.target.id);setUnlinkReason("");}}>연결 해제 사유 입력</button></div>
        :<p>연쇄 연결입니다. <a href={`/control/messages?record_id=${encodeURIComponent(link.parent_id)}`} target="_blank" rel="noreferrer">연결한 기존 기록에서 확인</a></p>}
    </li>)}</ul>
    {unlinkId&&<div><label>연결 해제 사유<textarea aria-label="연결 해제 사유" maxLength={500} value={unlinkReason} disabled={locked||unsavedWork} onChange={e=>setUnlinkReason(e.target.value)}/></label>
      <button className="secondary-button" disabled={locked||unsavedWork||!unlinkReason.trim()} onClick={()=>void run(async signal=>{
        const v=await recordRequest<MessageRecord>(token,signal,`/${record.id}/related/unlink`,{expected_version:record.version,target_id:unlinkId,reason:unlinkReason.trim()});if(!signal.aborted)onRecordChanged(v);
      })}>사유를 남기고 연결 해제</button><p className="message-caption">문자 기록을 삭제하지 않습니다. 과거 연결·검토는 변경 이력에서 볼 수 있습니다.</p></div>}
    <button className="secondary-button" disabled={locked} onClick={()=>void run(async signal=>{const v=await recordRequest<RecordPage>(token,signal,`/${record.id}/related/candidates`);if(!signal.aborted)setPage(v);})}>연결할 후속 문자 찾기</button>
    {page&&<div><p>저장된 문자 중 후속 문자를 선택하세요. 먼저 발행된 기록에서 이후 문자를 연결하며, 현재 원문의 저장된 분석이 필요합니다.</p>
      <ul className="message-record-list">{page.records.map(r=><li key={r.id}><p>{ORIGINS[r.origin]} · {time(r.message.issued_at)} · {r.message.recipient_regions.join(", ")||"수신지역 미상"}</p><p>{r.message.text}</p><button className="secondary-button" disabled={locked} onClick={()=>compare(r.id)}>이 문자와 비교</button></li>)}</ul>
      {!page.records.length&&<p>이 페이지에 비교할 문자가 없습니다.</p>}
      {page.next_cursor&&<button className="secondary-button" disabled={locked} onClick={()=>void run(async signal=>{const v=await recordRequest<RecordPage>(token,signal,`/${record.id}/related/candidates?before=${encodeURIComponent(page.next_cursor!)}`);if(!signal.aborted)setPage(v);})}>후속 후보 다음 페이지</button>}
    </div>}
    {preview&&<div className="message-related-preview" role="region" aria-label="후속 문자 원문 비교">
      <h3>원문과 구간별 근거 비교</h3><p className="message-notice">{preview.regions.detail}</p>
      {preview.comparison.has_release&&preview.comparison.has_active_restriction&&<p className="message-notice">일부 구간 해제와 통제 유지가 함께 있습니다. 전체 종료로 처리하지 말고 구간별로 확인해 주세요.</p>}
      <div className="message-comparison-columns">{[{title:"기존 문자",r:preview.parent,parts:preview.comparison.before},{title:"후속 문자",r:preview.target,parts:preview.comparison.after}].map(side=><div key={side.title}><h4>{side.title} · {ORIGINS[side.r.origin]}</h4>
        <p>{side.r.message.source} · {time(side.r.message.issued_at)}</p><p>수신지역: {side.r.message.recipient_regions.join(", ")||"미상"}</p><blockquote>{side.r.message.text}</blockquote><Parts parts={side.parts}/></div>)}</div>
      <h4>장소 표기 대조</h4><ul>{preview.comparison.locations.map((loc,i)=><li key={i}>{loc.text} ({ROLES[loc.role]||loc.role}) · {{same_spelling:"같은 표기",earlier_only:"이전 문자에만 표시 · 해제 추정 불가",followup_only:"후속 문자에 표시"}[loc.status]}{loc.before&&` · 이전: ${INTENTS[loc.before.intent]||loc.before.intent}`}{loc.after&&` · 후속: ${INTENTS[loc.after.intent]||loc.after.intent}`}</li>)}</ul>
      <p className="message-caption">{preview.comparison.caution}</p>
      <label>연결 종류<select aria-label="후속 연결 종류" value={kind} disabled={locked||unsavedWork} onChange={e=>setKind(e.target.value as typeof kind)}>{Object.entries(KINDS).map(([key,label])=><option value={key} key={key}>{label}</option>)}</select></label>
      <label>연결·재확인 사유<textarea aria-label="후속 연결 사유" rows={2} maxLength={500} value={reason} disabled={locked||unsavedWork} onChange={e=>setReason(e.target.value)}/></label>
      {preview.regions.status==="disjoint"&&<><label className="message-check"><input type="checkbox" checked={cross} disabled={locked||unsavedWork} onChange={e=>setCross(e.target.checked)}/>수신지역이 다르지만 같은 광역 상황임을 확인했습니다</label><label>지역 간 연결 근거<textarea aria-label="지역 간 연결 근거" maxLength={500} value={crossReason} disabled={locked||unsavedWork} onChange={e=>setCrossReason(e.target.value)}/></label></>}
      <label className="message-check"><input type="checkbox" checked={confirmed} disabled={locked||unsavedWork} onChange={e=>setConfirmed(e.target.checked)}/>원문·시각·지역·구간을 대조했으며 같은 상황의 후속 문자로 연결합니다</label>
      <button className="primary-button" disabled={locked||unsavedWork||!confirmed||!reason.trim()||preview.record_version!==record.version||(preview.regions.status==="disjoint"&&(!cross||!crossReason.trim()))} onClick={()=>void run(async signal=>{
        const v=await recordRequest<MessageRecord>(token,signal,`/${record.id}/related`,{expected_version:record.version,target_id:preview.target.id,kind,reason:reason.trim(),confirmed,comparison_token:preview.comparison_token,cross_region_confirmed:cross,cross_region_reason:crossReason.trim()});if(!signal.aborted)onRecordChanged(v);
      })}>{existing?"비교를 다시 확인하고 저장":"검토 대상으로 연결"}</button>
    </div>}
  </section>;
}

export function MessageRelatedHistory({record}:{record:MessageRecord}) {
  if(!record.relation_epoch)return null;
  return <section aria-label="과거 후속 연결"><h3>이 버전의 후속 연결</h3><p>현재 후속 원문과 다를 수 있습니다. 당시 확인 버전과 사유입니다.</p>
    <ul>{Object.entries(record.related_messages||{}).map(([id,edge])=><li key={id}>{id} · {KINDS[edge.kind]} · 원문 {edge.target_source_revision}판 / 분석 {edge.target_analysis_revision}판 · {edge.reason}</li>)}</ul>
    {record.relation_last_change&&<p>마지막 연결 변경 사유: {record.relation_last_change.reason}</p>}
  </section>;
}
