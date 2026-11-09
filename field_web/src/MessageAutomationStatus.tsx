import { useEffect, useRef, useState } from "react";
import { recordRequest, type MessageAutomation } from "./messageRecordsApi";

const titles:Record<MessageAutomation["state"],string>={disabled:"공식 문자 자동 수집 미연결",needs_key:"공식 문자 API 연결 필요",needs_verification:"공식 문자 연결 확인 중",starting:"첫 자동 수집 대기",live:"공식 문자 자동 수집 중",partial:"공식 문자 일부 확인 필요",stale:"공식 문자 수집 지연",error:"공식 문자 조회 실패",store_unavailable:"수집·분석 상태 확인 불가",request_limit:"문자 조회 한도로 수집 대기"};
function time(value:string|null){return value?new Date(value).toLocaleString("ko-KR",{timeZone:"Asia/Seoul",dateStyle:"short",timeStyle:"short"}):"아직 없음";}

export default function MessageAutomationStatus({token,onRefresh,automaticDelivery=false}:{token:string;onRefresh:(signal:AbortSignal)=>void|Promise<void>;automaticDelivery?:boolean}) {
  const [value,setValue]=useState<MessageAutomation|null>(null);const [error,setError]=useState(false);
  const refresh=useRef(onRefresh);refresh.current=onRefresh;
  useEffect(()=>{
    let active:AbortController|null=null;
    async function load(poll=false){
      if(active)return;
      const c=new AbortController();active=c;
      try{const next=await recordRequest<MessageAutomation>(token,c.signal,"/automation");if(!c.signal.aborted){setValue(next);setError(false);if(poll)await refresh.current(c.signal);}}
      catch{if(!c.signal.aborted)setError(true);}
      finally{active=null;}
    }
    void load();const timer=window.setInterval(()=>void load(true),60000);
    return()=>{window.clearInterval(timer);active?.abort();};
  },[token]);
  return <div className="message-automation" aria-label="문자 수집·분석 상태">
    <span className="message-tag">현재 수신 방식</span><h2>{error?"수집·분석 상태 확인 불가":value?titles[value.state]:"수집 상태 확인 중"}</h2>
    <p>{error?"상태를 조회하지 못했습니다. 이전 기록은 유지되며, 이 화면에서 수집 성공 여부를 판단할 수 없습니다.":value?.detail||"저장된 수집·분석 상태를 확인하고 있습니다."}</p>
    {value?.auto_collection_enabled&&!["needs_key","needs_verification","store_unavailable"].includes(value.state)&&<><p className="message-caption">{automaticDelivery?"브라우저를 닫아도 수집·판단·전파가 이어집니다. 확인이 필요한 예외만 관리자가 확인합니다.":"브라우저를 닫아도 자동 처리가 이어집니다. 수집된 문자의 검토·승인은 관리자가 합니다."}</p><p className="message-caption">마지막 정상 조회 {time(value.last_success_at)} · 마지막 시도 {time(value.last_attempt_at)}</p></>}
    {value?.queue&&<p className="automation-counts">분석 대기 {value.queue.pending} · 분석 중 {value.queue.running} · 분석 실패 {value.queue.failed} · 수동 확인 대기 {value.queue.deferred}</p>}
    {value?.budget.attempts!==null&&value?.budget.attempts!==undefined&&<p className="message-caption">오늘 분석 시작 {value.budget.attempts}/{value.budget.limit}건 · 수동·자동 합산, 실패 포함</p>}
    {value?.feed_budget&&value.feed_configured&&<p className="message-caption">최근 24시간 문자 조회 {value.feed_budget.used}/{value.feed_budget.limit}회 · 조회 간격 {value.interval_seconds/60}분 · 실패 포함</p>}
    {value?.latest_first_enabled&&<p className="message-caption">최신 첫 페이지 정상 확인 {time(value.last_latest_success_at??null)} · 과거 보충 완료 {time(value.last_backfill_success_at??null)}</p>}
    {value?.spend_budget?.enabled&&value.spend_budget.daily&&value.spend_budget.monthly&&<>
      <p className="message-caption">문자 AI 오늘 ${value.spend_budget.daily.settled_usd.toFixed(3)} / ${value.spend_budget.daily.limit_usd.toFixed(2)} · 이번 달 ${value.spend_budget.monthly.settled_usd.toFixed(3)} / ${value.spend_budget.monthly.limit_usd.toFixed(2)}</p>
      <p className="message-caption">미정산 예약: 오늘 ${value.spend_budget.daily.reserved_usd.toFixed(3)} · 이번 달 ${value.spend_budget.monthly.reserved_usd.toFixed(3)} · 수동·자동 합산, 이 앱의 문자 분석 기준</p>
      {value.spend_budget.can_start===false&&<p className="message-notice">AI 비용 한도 또는 정산 확인으로 새 분석을 대기합니다. 원문과 준비된 안내는 유지됩니다.</p>}
    </>}
    {value?.feed_budget?.remaining===0&&<p className="message-notice">문자 조회 한도로 대기합니다. 다시 조회 가능한 시각 {time(value.feed_budget.next_available_at)} · 마지막 정상 자료와 남은 작업은 유지됩니다.</p>}
    {value?.budget.remaining===0&&<p className="message-notice">오늘 분석 한도에 도달했습니다. 대기 기록은 보존되며 다음 날 다시 처리합니다. 24시간 넘게 대기한 기록은 수동 확인이 필요합니다.</p>}
    {!!value?.queue&&value.queue.failed+value.queue.deferred>0&&<p className="message-caption">실패했거나 오래 대기한 문자는 자동 재시도하지 않습니다. 기록을 열어 확인한 뒤 직접 분석할 수 있습니다.</p>}
    {value&&!value.auto_collection_enabled&&value.feed_configured&&<p className="message-caption">공식 API 수동 조회는 상세 관리에서 사용할 수 있습니다.</p>}
  </div>;
}
