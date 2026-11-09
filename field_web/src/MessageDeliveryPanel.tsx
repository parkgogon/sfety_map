import { useEffect, useRef, useState } from "react";
import { recordRequest } from "./messageRecordsApi";
import type { DeliveryItem, DeliveryKind, DeliveryPage, DeliveryStatus } from "./messageDeliveryApi";
import MessageAutomationStatus from "./MessageAutomationStatus";
import "./styles/message_delivery.css";

const STATES:Record<string,string>={pending:"전파 대기",sending:"전파 요청 중",sent:"전송 응답 확인",waiting:"재시도 대기",unknown:"수신 결과 미상",rejected:"요청 거절",cancelled:"대기 취소",invalidated:"근거 변경으로 취소",notify_ready:"요약 전파 추천",notify_source_only:"원문 중심 추천",record_only:"기록",attention_required:"판단 확인 필요",analysis_unavailable:"분석 확인 필요",blocked:"근거 확인 필요",reconsideration_required:"변경 판단 확인 필요",before_activation:"시작 전 자료"};
const path="/notifications";
function when(value?:string|null){return value?new Date(value).toLocaleString("ko-KR",{timeZone:"Asia/Seoul",dateStyle:"short",timeStyle:"short"}):"아직 없음";}
function recordUrl(id:string){return `/control/messages?view=review&record_id=${encodeURIComponent(id)}`;}

export default function MessageDeliveryPanel({token}:{token:string}) {
 const [status,setStatus]=useState<DeliveryStatus|null>(null),[page,setPage]=useState<DeliveryPage>({items:[],next_cursor:null});
 const [kind,setKind]=useState<DeliveryKind>("deliveries"),[error,setError]=useState(""),[notice,setNotice]=useState(""),[busy,setBusy]=useState(false),[loading,setLoading]=useState(true);
 const operation=useRef<AbortController|null>(null),working=useRef(false);
 const readSequence=useRef(0);
 async function load(signal:AbortSignal,append=false){
  const sequence=++readSequence.current;
  try{const [next,rows]=await Promise.all([
   recordRequest<DeliveryStatus>(token,signal,path+"/status"),
   recordRequest<DeliveryPage>(token,signal,path+`?kind=${kind}`+(append&&page.next_cursor?`&before=${encodeURIComponent(page.next_cursor)}`:""))]);
   if(!signal.aborted&&sequence===readSequence.current){setStatus(next);setPage(old=>append?{...rows,items:[...old.items,...rows.items]}:rows);setError("");}
  }catch(e){if(!signal.aborted&&sequence===readSequence.current)setError(e instanceof Error?e.message:"전파 상태를 확인하지 못했습니다.");}
  finally{if(!signal.aborted&&sequence===readSequence.current)setLoading(false);}
 }
 useEffect(()=>{const c=new AbortController();setLoading(true);setPage({items:[],next_cursor:null});void load(c.signal);
  const timer=window.setInterval(()=>{if(!working.current)void load(c.signal);},60000);
  return()=>{c.abort();operation.current?.abort();window.clearInterval(timer);};
 // Poll the current first page only; paging is an explicit operator action.
 // eslint-disable-next-line react-hooks/exhaustive-deps
 },[token,kind]);
 async function action(work:(signal:AbortSignal)=>Promise<unknown>,message:string){
  if(working.current)return;working.current=true;readSequence.current++;setBusy(true);setError("");setNotice("");
  const c=new AbortController();operation.current=c;
  try{await work(c.signal);if(!c.signal.aborted){setNotice(message);await load(c.signal);}}
  catch(e){if(!c.signal.aborted){setError(e instanceof Error?e.message:"처리를 완료하지 못했습니다.");}}
  finally{working.current=false;if(!c.signal.aborted)setBusy(false);}
 }
 function control(start:boolean){
  if(start&&!window.confirm("지금 이후 발행되는 새 공식 문자를 AI가 판단해 기존 직원 Telegram 단체방에 자동전파합니다. 이전 미리보기는 보내지 않습니다. 시작할까요?"))return;
  void action(signal=>recordRequest(token,signal,path+"/control",{action:start?"start":"pause",expected_generation:status?.generation??null}),start?"지금 이후의 새 공식 문자부터 자동전파합니다.":"자동전파를 일시정지했습니다. 이미 시작된 요청은 도착할 수 있습니다.");
 }
 async function copy(text:string){try{await navigator.clipboard.writeText(text);setNotice("문안을 복사했습니다. 복사는 발송 실적이 아닙니다.");}catch{setError("문안을 복사하지 못했습니다. 펼친 내용을 직접 확인해 주세요.");}}
 function entry(row:DeliveryItem,index:number){
  const snapshot=row.decision?.snapshot;
  const decisionState=snapshot&&!["reconsideration_required","invalidated","before_activation"].includes(row.state||"")?snapshot.decision:row.state;
  const label=STATES[decisionState||row.state||""]||"확인 필요";
  const text=row.preview_text||snapshot?.preview_text,reason=snapshot?.reason;
  return <li key={row.id||`${row.record_id}-${index}`} className={(row.state==="unknown"||row.state==="rejected")&&!row.resolved_at?"delivery-attention":""}>
   <div className="delivery-row-top"><strong>{label}</strong><span>{row.destination==="staff_group"?"직원 단체방":row.destination==="admin_group"?"관리자방":"자동 판단"}</span></div>
   <p className="message-caption">{when(row.updated_at||row.created_at)}{row.source_revision?` · 원문 ${row.source_revision}차`:""}{row.attempts!==undefined?` · 요청 ${row.attempts}회`:""}</p>
   {row.source_count!==undefined&&<p>같은 사유 원문 {row.source_count}건 · 중복 관측 제외</p>}
   {reason&&<p>{reason}</p>}
   {kind==="exceptions"&&row.preview_text&&<p className="delivery-exception-reason">{row.preview_text.split("\n")[1]||row.preview_text}</p>}
   {row.delivery_state&&<p className="message-caption">전파 결과: {STATES[row.delivery_state]||"확인 필요"}</p>}
   {row.state==="unknown"&&!row.resolved_at&&<p className="message-notice">실제 도착 여부를 확인하지 못했습니다. 중복 방지를 위해 자동 재발송하지 않습니다.</p>}
   {row.state==="sent"&&<p className="message-caption">Telegram 전송 응답을 확인했습니다. 직원의 열람·현장 확인을 뜻하지 않습니다.</p>}
   {row.state==="waiting"&&<p className="message-caption">제공자가 요청을 제한했습니다. {when(row.available_at)} 이후 최대 3회 안에서 다시 시도합니다.</p>}
   {row.resolved_at&&<p className="message-caption">관리자 확인 기록: {row.resolution==="confirmed_received"?"수신 확인":"별도 조치 완료"} · {when(row.resolved_at)}. 원래 전송 결과는 보존합니다.</p>}
   {text&&<details><summary>문안 보기</summary><pre>{text}</pre><button className="secondary-button" onClick={()=>void copy(text)}>문안 복사</button></details>}
   <div className="delivery-row-actions">
    {row.record_id&&<a className="secondary-button" href={recordUrl(row.record_id)}>원문·판단 확인</a>}
    {row.can_reconsider&&row.record_id&&snapshot&&status?.active&&<button className="secondary-button" disabled={busy} onClick={()=>void action(signal=>recordRequest(token,signal,`${path}/reconsider/${row.record_id}`,{expected_version:snapshot.record_version,expected_generation:status.generation}),"최신 판단을 미발송 대기에 반영했습니다. 정규 작업자가 다시 검증합니다.")}>변경 판단 반영</button>}
    {row.recent_record_ids?.map(id=><a key={id} className="secondary-button" href={recordUrl(id)}>해당 원문 열기</a>)}
    {row.id&&(row.state==="unknown"||row.state==="rejected")&&!row.resolved_at&&<>
     <button className="secondary-button" disabled={busy} onClick={()=>void action(signal=>recordRequest(token,signal,`${path}/${row.id}/acknowledge`,{resolution:"confirmed_received"}),"수신 확인 기록을 남겼습니다. 다시 보내지 않았습니다.")}>수신 확인 기록</button>
     <button className="secondary-button" disabled={busy} onClick={()=>void action(signal=>recordRequest(token,signal,`${path}/${row.id}/acknowledge`,{resolution:"handled_separately"}),"별도 조치 기록을 남겼습니다. 다시 보내지 않았습니다.")}>별도 조치 완료</button>
    </>}
   </div>
  </li>;
 }
 return <div className="message-delivery">
  <section className="message-card delivery-status" aria-label="자동전파 운영 상태">
   <span className="message-tag">공식 재난문자 → AI 판단 → 직원 단체방</span>
   <h2>{error?"자동전파 상태 확인 필요":status?.active?"재난문자 자동전파 중":status?.state==="paused"?"자동전파 일시정지":status?.can_activate?"자동전파 시작 대기":"자동전파 운영 연결 대기"}</h2>
   <p>{error?"상태 조회를 완료하지 못했습니다. 마지막 기록은 보존하며 새로고침으로 다시 확인할 수 있습니다.":status?.detail||"저장된 운영 상태를 확인하고 있습니다."}</p>
   {status?.started_at&&<p className="message-caption">전달 기준 시작 {when(status.started_at)} · 작업자 마지막 실행 {when(status.worker?.at)}</p>}
   {status?.worker_stale&&<p className="message-error" role="alert">자동전파 작업이 지연되고 있습니다. 시작 상태만으로 정상 전달을 판단할 수 없습니다.</p>}
   <div className="delivery-row-actions">
    {status?.active?<button className="secondary-button" disabled={busy} onClick={()=>control(false)}>전파 일시정지</button>:status?.can_activate&&<button className="primary-button" disabled={busy||!!error} onClick={()=>control(true)}>자동전파 시작</button>}
    <a className="secondary-button" href="/control/messages?view=review">문자 검토·직접 입력</a>
   </div>
   <p className="message-caption">건별 승인은 필요하지 않습니다. 판단·전파와 사람의 검토·현장 확인은 별도 기록입니다.</p>
  </section>
  <section className="message-collection"><MessageAutomationStatus token={token} automaticDelivery={status?.active} onRefresh={()=>{}}/></section>
  <section className="message-card" aria-label="전파 이력과 예외">
   <div className="delivery-row-top"><h2>전파·판단 기록</h2><button className="secondary-button" disabled={busy} onClick={()=>{const c=new AbortController();operation.current=c;void load(c.signal);}}>새로고침</button></div>
   <div className="inbox-filters" role="group" aria-label="전파 기록 분류">{([["deliveries","전파 이력"],["decisions","판단 기록"],["exceptions","확인 필요"]] as const).map(([key,label])=><button key={key} className="secondary-button" aria-pressed={kind===key} disabled={busy} onClick={()=>setKind(key)}>{label}</button>)}</div>
   {error&&<p className="message-error" role="alert">{error}</p>}{notice&&<p className="message-notice" role="status">{notice}</p>}
   {loading?<p role="status">기록을 불러오는 중…</p>:!error&&!page.items.length&&<p>{kind==="deliveries"?"아직 전파 요청 이력이 없습니다. 미리보기는 발송 이력으로 세지 않습니다.":kind==="exceptions"?"저장된 확인 필요 항목이 없습니다.":"아직 저장된 자동 판단이 없습니다."}</p>}
   <ul className="delivery-list">{page.items.map(entry)}</ul>
   {page.next_cursor&&<button className="secondary-button" disabled={busy} onClick={()=>{const c=new AbortController();operation.current=c;void load(c.signal,true);}}>이전 기록 더 보기</button>}
  </section>
 </div>;
}
