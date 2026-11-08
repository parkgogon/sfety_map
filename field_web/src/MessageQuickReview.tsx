import { useEffect, useRef, useState } from "react";
import { recordRequest, type MessageRecord } from "./messageRecordsApi";
import type { PreparedReview, PrepareReviewInput, ReviewLocationChoice } from "./messagePreparationApi";
import { MessageReferenceMap } from "./MessageReferenceMap";

type Props = { token: string; record: MessageRecord; onChange: (record: MessageRecord) => void; onHold: (record: MessageRecord) => void; onBusyChange?: (busy:boolean)=>void; onDirtyChange?: (dirty:boolean)=>void };

export default function MessageQuickReview({ token, record, onChange, onHold, onBusyChange, onDirtyChange }: Props) {
  const [input, setInput] = useState<PrepareReviewInput>(()=>{
    const saved=record.review_working_copy;
    return saved&&saved.saved_at_version===record.version&&saved.source_revision===record.source_revision&&saved.analysis_revision===record.analysis_revision
      ? {...saved.input,expected_version:record.version} : { expected_version: record.version, choices: [], manager_note: "" };
  });
  const [view, setView] = useState<PreparedReview | null>(null);
  const [viewKey, setViewKey] = useState(""); const [error, setError] = useState("");
  const [preparing, setPreparing] = useState(true);
  const [editing, setEditing] = useState(false); const [working, setWorking] = useState(false);
  const [retry, setRetry] = useState(0); const [locationKey, setLocationKey] = useState("");
  const [search, setSearch] = useState(""); const [showAll, setShowAll] = useState(false); const [picking, setPicking] = useState(false);
  const [coordinates, setCoordinates] = useState({ latitude: "", longitude: "" });
  const operation = useRef<AbortController | null>(null);
  const locked = useRef(false);
  const bodyKey = JSON.stringify(input);
  const current = !!view && viewKey === bodyKey && !preparing && !error;
  const dirty = !!input.choices.length || !!input.manager_note || !!input.no_action_reason || !!input.uncertainty_acknowledged;
  useEffect(()=>{onDirtyChange?.(dirty);return()=>onDirtyChange?.(false);},[dirty,onDirtyChange]);
  useEffect(()=>{onBusyChange?.(working);return()=>onBusyChange?.(false);},[working,onBusyChange]);
  useEffect(() => {
    const controller = new AbortController(); setError(""); setPreparing(true);
    const timer = setTimeout(() => {
      void recordRequest<PreparedReview>(token, controller.signal, `/${record.id}/prepare`, JSON.parse(bodyKey)).then(value => {
        if (!controller.signal.aborted) { setView(value); setViewKey(bodyKey); setLocationKey(old => value.locations.some(l => l.key === old) ? old : value.locations[0]?.key || ""); }
      }).catch(e => { if (!controller.signal.aborted) setError(e instanceof Error ? e.message : "추천안을 준비하지 못했습니다."); })
        .finally(()=>{if(!controller.signal.aborted)setPreparing(false);});
    }, 180);
    return () => { clearTimeout(timer); controller.abort(); };
  }, [token, record.id, bodyKey, retry]);
  useEffect(() => () => operation.current?.abort(), []);
  const location = view?.locations.find(l => l.key === locationKey);
  function changeLocation(patch: Partial<ReviewLocationChoice>) {
    if (!location) return;
    const key = location.key;
    setInput(old => ({ ...old, choices: [...old.choices.filter(c => c.location_key !== key), { ...old.choices.find(c => c.location_key === key), location_key: key, ...patch }] }));
  }
  async function act(approve: boolean) {
    if (locked.current || approve && (!current || !view?.ready)) return;
    locked.current = true; setWorking(true); setError("");
    const controller = new AbortController(); operation.current = controller;
    try {
      const saved = await recordRequest<MessageRecord>(token, controller.signal, `/${record.id}${approve ? "/approve" : "/hold"}`,
        approve ? { ...input, proposal_hash: view!.proposal_hash, confirmed: true } : input);
      if (!controller.signal.aborted) (approve ? onChange : onHold)(saved);
    } catch (e) { if (!controller.signal.aborted) setError(e instanceof Error ? e.message : "검토를 저장하지 못했습니다."); }
    finally { locked.current = false; if (!controller.signal.aborted) setWorking(false); }
  }
  const choice = input.choices.find(c => c.location_key === locationKey);
  return <section className="message-card quick-review" aria-label="한 화면 검토">
    <div className="quick-heading"><div><span className="message-tag">담당자 검토 전</span><h2>확인할 대상과 안내 내용</h2></div>
      <button className="secondary-button" disabled={working} onClick={() => setEditing(v => !v)}>{editing ? "수정 닫기" : "내용 수정"}</button></div>
    <div className="quick-review-actions"><button className="primary-button" disabled={working || !current || !view?.ready} onClick={()=>void act(true)}>{working ? "저장 중…" : view?.outcome==="no_action" ? "추가 조치 없이 검토 완료" : "이 내용으로 검토 완료"}</button>
      <button className="secondary-button" disabled={working} onClick={()=>void act(false)}>보류</button></div>
    {error && <div role="alert" className="message-error">{error} <button className="secondary-button" onClick={() => setRetry(n => n+1)}>추천안 다시 불러오기</button></div>}
    {!current && !error && <p role="status">{view ? "수정한 내용으로 지도와 초안을 갱신하고 있습니다…" : "위치·시설·안내 초안을 준비하고 있습니다…"}</p>}
    {view && <>
      {!!view.issues.length && <aside className="quick-attention"><h3>이 부분만 확인해 주세요</h3><ul>{view.issues.map(i => <li key={i}>{i}</li>)}</ul>
      </aside>}
      {view.uncertain_time && <label className="message-spatial-check"><input type="checkbox" disabled={working} checked={input.uncertainty_acknowledged || false} onChange={e => setInput(old => ({...old, uncertainty_acknowledged:e.target.checked}))}/>발행 시각 미상인 점을 반영해 참고 검토로 남깁니다.</label>}
      {view.locations.length > 1 && <label>검토 장소<select aria-label="검토 장소" value={locationKey} disabled={working} onChange={e => { setLocationKey(e.target.value); setSearch(""); setPicking(false); }}>{view.locations.map(l => <option key={l.key} value={l.key}>{l.text} · {l.selected.length}개소</option>)}</select></label>}
      {location ? <div className="quick-review-grid">
        <div><h3>{location.text}</h3>
          {location.point ? <>
            <MessageReferenceMap point={location.point} draft={null} radius={location.radius_km} facilities={location.facilities.filter(f => f.within_radius || location.selected.some(s => s.id === f.id))}
              selectedIds={location.selected.map(f => f.id)} preview picking={picking && editing && !working} onPick={p => { changeLocation({point:{mode:"manual",...p,manual_source:"map"},facilities:undefined,reference_acknowledged:false}); setPicking(false); }}/>
            <p className="message-caption">{location.point.label} 기준 {location.radius_km}km · {location.representative ? "대표점 참고 조회" : "원문 장소의 검색 후보"}</p>
          </> : <p className="message-notice">조회할 위치를 선택하면 주변 시설이 표시됩니다.</p>}
          {location.reference_required && <label className="message-spatial-check quick-ack"><input type="checkbox" disabled={working} checked={choice?.reference_acknowledged || false} onChange={e => changeLocation({reference_acknowledged:e.target.checked})}/>이 위치와 거리를 참고 조회 기준으로 사용합니다.</label>}
          {(editing || !location.point) && <fieldset disabled={working} className="quick-edit">
            <legend>조회 위치 수정</legend>
            <label>장소 후보<select aria-label="장소 후보" value={location.point?.candidate_id || ""} onChange={e => { if (e.target.value) changeLocation({point:{mode:"candidate",candidate_id:e.target.value},facilities:undefined,reference_acknowledged:false}); }}>
              <option value="">후보 선택</option>{location.candidates.map(c => <option key={c.id} value={c.id}>{c.name} · {c.address}</option>)}</select></label>
            <label>참고 조회 거리<select aria-label="참고 조회 거리" value={location.radius_km} onChange={e => changeLocation({radius_km:Number(e.target.value) as 1|3|5|10, facilities:undefined, reference_acknowledged:false})}>{[1,3,5,10].map(n => <option key={n} value={n}>{n}km</option>)}</select></label>
            {location.point && <button type="button" className="secondary-button" onClick={() => setPicking(v => !v)}>{picking ? "지도 지정 취소" : "지도에서 위치 수정"}</button>}
            <details><summary>좌표로 위치 보완</summary>
              <label>위도<input aria-label="수정할 위도" type="number" step="any" value={coordinates.latitude} onChange={e => setCoordinates(old => ({...old,latitude:e.target.value}))}/></label>
              <label>경도<input aria-label="수정할 경도" type="number" step="any" value={coordinates.longitude} onChange={e => setCoordinates(old => ({...old,longitude:e.target.value}))}/></label>
              <button type="button" className="secondary-button" disabled={!coordinates.latitude || !coordinates.longitude || !Number.isFinite(Number(coordinates.latitude)) || !Number.isFinite(Number(coordinates.longitude)) || Math.abs(Number(coordinates.latitude))>90 || Math.abs(Number(coordinates.longitude))>180} onClick={() => changeLocation({point:{mode:"manual",latitude:Number(coordinates.latitude),longitude:Number(coordinates.longitude),manual_source:"coordinate"},facilities:undefined,reference_acknowledged:false})}>이 좌표 사용</button>
            </details>
          </fieldset>}
        </div>
        <div><h3>업무 확인 대상 제안 · {view.selected_count}개소</h3><p className="message-caption">거리와 소관시설 자료를 바탕으로 제안합니다. 피해 시설 판정이 아닙니다.</p>
          {!!location.removed_facilities?.length && <p className="message-notice">현재 시설 자료에서 제외됨: {location.removed_facilities.map(f=>f.name).join(", ")}. 최신 목록에서 다시 선택해 주세요.</p>}
          {!editing ? <ul className="quick-facilities">{location.selected.slice(0,5).map(f => <li key={f.id}><strong>{f.name}</strong><span>{f.facility_type} · 직선 {(f.distance_m/1000).toFixed(2)}km</span></li>)}</ul> : <>
            <label>시설 검색<input aria-label="확인 대상 시설 검색" value={search} onChange={e => setSearch(e.target.value)}/></label>
            <label className="message-spatial-check"><input type="checkbox" checked={showAll} onChange={e => setShowAll(e.target.checked)}/>반경 밖 시설도 검색</label>
            <ul className="quick-facilities quick-facility-picker">{location.facilities.filter(f => (showAll || f.within_radius || location.selected.some(s=>s.id===f.id)) && `${f.name} ${f.address} ${f.id}`.includes(search)).map(f => <li key={f.id}>
              <label className="message-spatial-check"><input type="checkbox" disabled={working || !current} checked={location.selected.some(s => s.id===f.id)} onChange={e => changeLocation({facilities:e.target.checked ? [...location.selected.map(s=>({facility_id:s.id,reason:s.reason})),{facility_id:f.id}] : location.selected.filter(s=>s.id!==f.id).map(s=>({facility_id:s.id,reason:s.reason}))})}/><span><strong>{f.name}</strong><small>직선 {(f.distance_m/1000).toFixed(2)}km{!f.within_radius && " · 반경 밖"}</small></span></label>
            </li>)}</ul>
          </>}
          {!editing && location.selected.length>5 && <details><summary>나머지 {location.selected.length-5}개소 펼쳐보기</summary><ul className="quick-facilities">{location.selected.slice(5).map(f=><li key={f.id}><strong>{f.name}</strong><span>{f.facility_type} · 직선 {(f.distance_m/1000).toFixed(2)}km</span></li>)}</ul></details>}
          {location.selected.filter(f=>!f.within_radius).map(f=><label key={f.id}>{f.name} 반경 밖 추가 사유<select aria-label={`${f.name} 반경 밖 추가 사유`} value={f.reason||""} disabled={working} onChange={e=>changeLocation({facilities:location.selected.map(s=>({facility_id:s.id,reason:s.id===f.id?e.target.value:s.reason}))})}><option value="">사유 선택</option><option value="같은 업무 상황으로 별도 확인이 필요함">같은 업무 상황으로 별도 확인</option><option value="소관 업무상 함께 확인할 시설임">소관 업무상 함께 확인</option></select></label>)}
          {!location.selected.length && <label>이 장소의 처리<select aria-label="이 장소의 처리" disabled={working} value={choice?.excluded_reason || ""} onChange={e=>changeLocation({excluded_reason:(e.target.value||undefined) as ReviewLocationChoice["excluded_reason"]})}><option value="">시설 추가 또는 처리 선택</option><option value="reference_only">참고 안내로 기록</option><option value="outside_scope">이번 업무 대상에서 제외</option></select></label>}
        </div>
      </div> : <p>별도 사고·통제 장소 없이 원문 안내 내용을 검토합니다.</p>}
      {!view.selected_count && <label>검토 결과<select aria-label="검토 결과" disabled={working} value={input.no_action_reason || (view.locations.length ? "" : "reference_only")} onChange={e=>setInput(old=>({...old,outcome:"no_action",no_action_reason:e.target.value as PrepareReviewInput["no_action_reason"]}))}><option value="">처리 선택</option><option value="reference_only">추가 업무 대상 없이 참고 기록</option><option value="outside_scope">소관 업무와 직접 관련 없음</option><option value="other">별도 사유로 추가 조치 없음</option></select></label>}
      {!!view.questions.length && <details className="quick-questions"><summary>분석에서 제시한 확인 사항 {view.questions.length}개</summary><ul>{view.questions.map(q=><li key={q}>{q}</li>)}</ul></details>}
      <section className="quick-notice"><h3>전달할 안내 초안</h3><pre aria-label="안내 초안 미리보기">{view.notice_preview}</pre></section>
      {editing && <label>추가 안내 · 선택<textarea aria-label="추가 안내" rows={3} maxLength={2000} value={input.manager_note} disabled={working} onChange={e=>setInput(old=>({...old,manager_note:e.target.value}))}/></label>}
    </>}
    <p className="message-caption">완료하면 표시한 위치·시설·안내 내용을 함께 저장합니다. 내부 검토 기록이며 현장 확인·실제 발송을 뜻하지 않습니다.</p>
  </section>;
}
