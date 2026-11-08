import { useEffect, useRef, useState } from "react";
import { recordRequest, type MessageRecord } from "./messageRecordsApi";
import { ROLE_LABELS, INTENT_LABELS } from "./messageAnalysisApi";
import { MessageReferenceMap } from "./MessageReferenceMap";
import type { SpatialDetail, SpatialFacility, SpatialPage, SpatialProps, MessageReference } from "./messageSpatialApi";

type DraftPoint = { mode: "candidate" | "manual"; candidate_id?: string; latitude: number; longitude: number;
  label: string; manual_source: "map" | "coordinate" };

export default function MessageSpatialWorkspace({ token, record, disabled, onRecordChanged, onBusyChange, onDirtyChange }: SpatialProps) {
  const [detail, setDetail] = useState<SpatialDetail | null>(null);
  const [restoredContext, setRestoredContext] = useState("");
  const [key, setKey] = useState(""); const [reload, setReload] = useState(0);
  const [point, setPoint] = useState<DraftPoint | null>(null); const [radius, setRadius] = useState<1 | 3 | 5 | 10>(3);
  const [confirmation, setConfirmation] = useState(""); const [confirmed, setConfirmed] = useState(false); const [picking, setPicking] = useState(false);
  const [latitude, setLatitude] = useState(""); const [longitude, setLongitude] = useState("");
  const [page, setPage] = useState<SpatialPage | null>(null); const [scope, setScope] = useState<"nearby" | "all">("nearby");
  const [term, setTerm] = useState(""); const [query, setQuery] = useState(""); const [offset, setOffset] = useState(0);
  const [selected, setSelected] = useState<Record<string, string>>({}); const [selectionNote, setSelectionNote] = useState("");
  const [known, setKnown] = useState<Record<string, SpatialFacility>>({});
  const [loading, setLoading] = useState(false); const [pageLoading, setPageLoading] = useState(false); const [busy, setBusy] = useState(false);
  const [error, setError] = useState(""); const [notice, setNotice] = useState("");
  const mounted = useRef(true); const operation = useRef<AbortController | null>(null);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; operation.current?.abort(); }; }, []);
  useEffect(() => {
    const controller = new AbortController(); setLoading(true); setError(""); setDetail(null); setPage(null); setRestoredContext("");
    void recordRequest<SpatialDetail>(token, controller.signal, `/${record.id}/spatial`).then(value => {
      if (controller.signal.aborted) return;
      setDetail(value); setKey(old => value.locations.some(l => l.key === old && l.eligible) ? old : value.locations.find(l => l.eligible)?.key || "");
    }).catch(reason => { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "지도 검토 자료를 불러오지 못했습니다."); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [token, record.id, record.version, reload]);
  const location = detail?.locations.find(l => l.key === key);
  const ref = location?.reference;
  useEffect(() => {
    if (!detail) return;
    const saved = detail.locations.find(l => l.key === key)?.reference;
    setPoint(saved ? { mode: saved.point.source === "candidate" ? "candidate" : "manual", candidate_id: saved.point.candidate_id || undefined,
      latitude: saved.point.latitude, longitude: saved.point.longitude, label: saved.point.label,
      manual_source: saved.point.source === "coordinate" ? "coordinate" : "map" } : null);
    setRadius(saved?.radius_km || 3); setConfirmation(saved?.confirmation_note || ""); setConfirmed(false); setPicking(false);
    setSelected(Object.fromEntries((saved?.selected || []).map(f => [f.id, f.reason || ""])));
    setSelectionNote(saved?.selection_note || ""); setKnown(Object.fromEntries((saved?.selected || []).map(f => [f.id, f])));
    setTerm(""); setQuery(""); setScope("nearby"); setOffset(0); setPage(null); setLatitude(""); setLongitude("");
    setRestoredContext(`${detail.record_version}:${key}`);
  }, [detail, key]);
  useEffect(() => {
    if (!detail || !ref || restoredContext !== `${detail.record_version}:${key}`) return;
    const controller = new AbortController(); setPageLoading(true); setPage(null);
    const params = new URLSearchParams({ location_key: key, expected_version: String(detail.record_version),
      offset: String(offset), scope, query, catalog_digest: detail.catalog_digest });
    void recordRequest<SpatialPage>(token, controller.signal, `/${record.id}/facilities?${params}`).then(value => {
      if (controller.signal.aborted) return;
      setPage(value); setKnown(old => ({ ...old, ...Object.fromEntries([...value.map_facilities, ...value.facilities].map(f => [f.id, f])) }));
    }).catch(reason => { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "시설 목록을 읽지 못했습니다."); })
      .finally(() => { if (!controller.signal.aborted) setPageLoading(false); });
    return () => controller.abort();
  }, [token, record.id, detail, ref, key, offset, scope, query, restoredContext]);

  async function save(path: string, body: unknown, message: string) {
    operation.current?.abort(); const controller = new AbortController(); operation.current = controller;
    setBusy(true); onBusyChange(true); setError(""); setNotice("");
    try {
      const updated = await recordRequest<MessageRecord>(token, controller.signal, `/${record.id}/${path}`, body);
      if (!controller.signal.aborted) { onRecordChanged(updated); setNotice(message); }
    } catch (reason) { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "저장하지 못했습니다."); }
    finally { if (mounted.current) { setBusy(false); onBusyChange(false); } }
  }
  function changePoint(value: DraftPoint) { setPoint(value); setConfirmed(false); setPicking(false); }
  const changed = !!ref && (!point || point.latitude !== ref.point.latitude || point.longitude !== ref.point.longitude
    || radius !== ref.radius_km || (point.mode === "candidate" ? point.candidate_id : null) !== ref.point.candidate_id);
  const dirty = !!detail && restoredContext === `${detail.record_version}:${key}` && (
    changed || (!ref && !!point) || (!!point && confirmation !== (ref?.confirmation_note || ""))
    || selectionNote !== (ref?.selection_note || "")
    || JSON.stringify(Object.entries(selected).sort()) !== JSON.stringify((ref?.selected || []).map(f => [f.id, f.reason || ""]).sort()));
  useEffect(() => { onDirtyChange?.(dirty); }, [dirty, onDirtyChange]);
  useEffect(() => () => { onDirtyChange?.(false); }, [onDirtyChange]);
  const locked = disabled || busy || loading || !detail || detail.record_version !== record.version || restoredContext !== `${detail.record_version}:${key}`;
  const selectable = !!ref && !!location?.catalog_current && !!page?.catalog_current && !changed && !locked && !pageLoading;
  const selectedRows = Object.keys(selected).map(id => known[id]).filter((f): f is SpatialFacility => !!f);
  const mapRows = [...(page?.map_facilities || []), ...selectedRows.filter(f => !f.within_radius && location?.catalog_current)];
  const uniqueMapRows = [...new Map(mapRows.map(f => [f.id, f])).values()];
  const displayDraft = point && (!ref || changed) ? point : null;

  return <section className="message-card message-spatial" aria-label="지도 확인과 업무 대상 시설 선정">
    <div className="message-record-toolbar"><h2>지도 확인 · 업무 대상 시설 선정</h2>
      <button className="secondary-button" disabled={disabled || busy} onClick={() => setReload(n => n + 1)}>지도 검토 다시 불러오기</button></div>
    <p>문자에 나온 사고·통제 장소별로 조회 기준점을 확인하고, 업무상 확인할 시설을 고릅니다.</p>
    {loading && <p role="status">지도 검토 자료를 불러오는 중…</p>}
    {error && <p className="message-error" role="alert">{error}</p>}
    {notice && <p className="message-notice" role="status">{notice}</p>}
    {detail?.reset_reason && <p className="message-notice">원문 또는 분석이 바뀌어 이전 기준점과 시설 선정은 이력에 보존했습니다. 현재 분석을 기준으로 다시 확인해 주세요.</p>}
    {detail && <>
      <label>검토할 사고·통제 장소<select aria-label="검토할 사고·통제 장소" disabled={locked} value={key} onChange={e => { setPoint(null); setSelected({}); setPage(null); setPicking(false); setKey(e.target.value); }}>
        {!key && <option value="">선택할 사고·통제 장소 없음</option>}
        {detail.locations.map(l => <option key={l.key} value={l.key} disabled={!l.eligible}>{l.text} · {ROLE_LABELS[l.role as keyof typeof ROLE_LABELS]} · {INTENT_LABELS[l.intent as keyof typeof INTENT_LABELS]}{!l.eligible ? " (조회 대상 제외)" : ""}</option>)}
      </select></label>
      {detail.locations.some(l => !l.eligible) && <p className="message-caption">대피 목적지·참고 장소·이미 해제된 구간은 사고·통제 기준점 선택에서 제외합니다.</p>}
      {!key && <p>현재 분석에 조회할 사고·통제 장소가 없습니다. 원문과 분석을 확인해 주세요.</p>}
    </>}
    {location && <>
      <blockquote>{location.evidence}</blockquote>
      <div className="message-spatial-workspace">
        <div>
          <MessageReferenceMap point={ref?.point || null} draft={displayDraft} radius={ref?.radius_km || radius}
            facilities={uniqueMapRows} selectedIds={location.catalog_current ? Object.keys(selected) : []} picking={picking && !locked}
            onPick={coordinate => changePoint({ ...coordinate, label: location.text.slice(0, 80), mode: "manual", manual_source: "map" })} />
          <p className="message-caption">지도에서 기준점을 지정해도 실제 사고 지점의 현장 확인을 뜻하지 않습니다.</p>
        </div>
        <div className="message-spatial-controls">
          <h3>조회 기준점</h3>
          {ref && <p className="message-caption">저장한 기준점 확인 시각: {new Date(ref.confirmed_at).toLocaleString("ko-KR", { timeZone: "Asia/Seoul" })} (한국 시간)</p>}
          {location.candidates.length > 0 ? <ul className="message-candidate-list">{location.candidates.map(c => <li key={c.id}>
            <button className="secondary-button" disabled={locked} aria-pressed={point?.candidate_id === c.id} onClick={() => changePoint({ mode: "candidate", candidate_id: c.id, latitude: c.latitude, longitude: c.longitude, label: c.name, manual_source: "map" })}>{c.name} 후보 선택</button>
            <small>{c.address}{c.scope_matches_source === false ? " · 원문 지역과의 일치 미확인" : ""}</small>
          </li>)}</ul> : <p>확인된 장소 후보가 없습니다. 지도에서 위치를 지정할 수 있습니다.</p>}
          <button className="secondary-button" disabled={locked} onClick={() => { setPicking(!picking); setConfirmed(false); }}>{picking ? "지도 지정 취소" : "지도에서 위치 지정·수정"}</button>
          {picking && <p role="status">지도에서 조회 기준점으로 사용할 위치를 눌러 주세요.</p>}
          <details><summary>좌표 직접 입력</summary><p className="message-caption">지도 연결이 어려울 때 확인한 좌표를 직접 입력할 수 있습니다.</p>
            <div className="message-form-row"><label>위도<input aria-label="기준점 위도" type="number" step="any" min={-90} max={90} value={latitude} disabled={locked} onChange={e => setLatitude(e.target.value)} /></label>
              <label>경도<input aria-label="기준점 경도" type="number" step="any" min={-180} max={180} value={longitude} disabled={locked} onChange={e => setLongitude(e.target.value)} /></label></div>
            <button className="secondary-button" disabled={locked || !latitude || !longitude || !Number.isFinite(Number(latitude)) || !Number.isFinite(Number(longitude)) || Math.abs(Number(latitude)) > 90 || Math.abs(Number(longitude)) > 180}
              onClick={() => changePoint({ latitude: Number(latitude), longitude: Number(longitude), label: location.text.slice(0, 80), mode: "manual", manual_source: "coordinate" })}>입력한 좌표를 후보로 사용</button>
          </details>
          {point && <p className="message-notice">{point.label}<br />{point.latitude.toFixed(5)}, {point.longitude.toFixed(5)} · {point.mode === "candidate" ? "검색 후보" : "관리자 지정 위치"}</p>}
          <label>참고 조회 거리<select aria-label="지도 참고 조회 거리" value={radius} disabled={locked} onChange={e => { setRadius(Number(e.target.value) as typeof radius); setConfirmed(false); }}>{[1, 3, 5, 10].map(km => <option key={km} value={km}>{km}km</option>)}</select></label>
          <label>기준점 확인 근거<textarea aria-label="기준점 확인 근거" value={confirmation} maxLength={500} rows={2} disabled={locked} placeholder="예: 정확한 공장 위치 미상, 산업단지 대표점을 참고 기준으로 사용" onChange={e => { setConfirmation(e.target.value); setConfirmed(false); }} /></label>
          <label className="message-spatial-check"><input type="checkbox" checked={confirmed} disabled={locked || !point} onChange={e => setConfirmed(e.target.checked)} />이 위치와 거리를 참고 조회 기준으로 확인했습니다.</label>
          <button className="primary-button" disabled={locked || !point || !confirmed || !confirmation.trim()} onClick={() => point && void save("reference", {
            expected_version: record.version, location_key: key, radius_km: radius, confirmation_note: confirmation.trim(), confirmed: true,
            point: point.mode === "candidate" ? { mode: "candidate", candidate_id: point.candidate_id } : { mode: "manual", latitude: point.latitude, longitude: point.longitude, label: point.label, manual_source: point.manual_source },
          }, "조회 기준점을 저장했습니다. 이 기준의 시설을 확인해 주세요.")}>이 기준점으로 조회</button>
        </div>
      </div>
      {ref && <div className="message-spatial-selection">
        <h3>업무상 확인할 시설</h3>
        <p>저장 기준: {ref.point.label} · {ref.radius_km}km · 전체 자료 기준 {ref.nearby_count}개소</p>
        <p className="message-caption">주변 시설은 기본 미선택입니다. 시설 선정은 업무 검토 대상이며 피해나 현장 확인 완료를 의미하지 않습니다.</p>
        {changed && <p className="message-notice">기준점 또는 조회 거리 입력이 바뀌었습니다. 아래는 저장한 이전 기준의 목록입니다. 새 기준점으로 조회한 뒤 다시 선택해 주세요.</p>}
        {!location.catalog_current && <p className="message-notice">시설 자료가 변경됐습니다. 저장한 선정은 이전 자료 기준입니다. 기준점을 다시 조회한 뒤 시설을 선택해 주세요.</p>}
        {ref.selection_needs_review && <p className="message-notice">조회 기준이 바뀌어 이전 선정은 이력에 보존했습니다. 새 기준으로 시설을 다시 선택해 주세요.</p>}
        <div className="message-spatial-query">
          <label>시설 목록 범위<select aria-label="시설 목록 범위" value={scope} disabled={locked} onChange={e => { setScope(e.target.value as typeof scope); setOffset(0); }}><option value="nearby">조회 반경 안 시설</option><option value="all">전체 등록 시설 · 반경 밖 추가</option></select></label>
          <form onSubmit={e => { e.preventDefault(); setQuery(term.trim()); setOffset(0); }}><label>시설명·ID·주소 검색<input aria-label="선정할 시설 검색" disabled={locked} maxLength={120} value={term} onChange={e => setTerm(e.target.value)} /></label><button className="secondary-button" disabled={locked}>시설 검색</button></form>
        </div>
        {pageLoading && <p role="status">시설 목록을 다시 계산하는 중…</p>}
        {page && <><p>{page.total_count}개소 중 {page.facilities.length ? page.offset + 1 : 0}~{page.offset + page.facilities.length}번째 표시</p>
          {!page.facilities.length && <p>이 조회 조건에 등록 시설이 없습니다. 안전 판정은 아닙니다.</p>}
          <ul className="message-selection-list">{page.facilities.map(f => <li key={f.id}>
            <label className="message-spatial-check"><input type="checkbox" aria-label={`${f.name} 업무 대상 선택`} disabled={!selectable} checked={f.id in selected} onChange={e => setSelected(old => { const next = { ...old }; if (e.target.checked) next[f.id] = ""; else delete next[f.id]; return next; })} />
              <span><strong>{f.name}</strong><small>{f.facility_type} · {(f.distance_m / 1000).toFixed(2)}km{!f.within_radius && " · 조회 반경 밖"}<br />{f.address}</small></span></label>
          </li>)}</ul>
          <div className="message-record-toolbar"><button className="secondary-button" disabled={locked || pageLoading || offset === 0} onClick={() => setOffset(Math.max(0, offset - 20))}>이전 시설 페이지</button>
            <button className="secondary-button" disabled={locked || pageLoading || page.next_offset === null} onClick={() => setOffset(page.next_offset || 0)}>다음 시설 페이지</button></div>
        </>}
        <h4>현재 선택 {Object.keys(selected).length}개소</h4>
        <ul className="message-selected-list">{selectedRows.map(f => <li key={f.id}><strong>{f.name}</strong> · {(f.distance_m / 1000).toFixed(2)}km
          <button className="secondary-button" disabled={!selectable} onClick={() => setSelected(old => { const next = { ...old }; delete next[f.id]; return next; })}>{f.name} 선택 해제</button>
          {!f.within_radius && <label>반경 밖 시설 추가 사유<textarea aria-label={`${f.name} 반경 밖 추가 사유`} rows={2} maxLength={500} disabled={!selectable} value={selected[f.id]} onChange={e => setSelected(old => ({ ...old, [f.id]: e.target.value }))} /></label>}
        </li>)}</ul>
        <label>시설 선정 사유<textarea aria-label="시설 선정 사유" rows={2} maxLength={1000} disabled={!selectable} value={selectionNote} onChange={e => setSelectionNote(e.target.value)} placeholder="선택한 시설을 업무상 확인해야 하는 이유" /></label>
        <button className="primary-button" disabled={!selectable || (Object.keys(selected).length > 0 && !selectionNote.trim()) || selectedRows.some(f => !f.within_radius && !selected[f.id].trim())}
          onClick={() => void save("selection", { expected_version: record.version, location_key: key, reference_revision: ref.revision,
            catalog_digest: page?.catalog_digest, facilities: Object.entries(selected).map(([facility_id, reason]) => ({ facility_id, reason: reason.trim() })), note: selectionNote.trim() }, "업무 대상 시설 선정을 저장했습니다.")}>선정 시설 저장</button>
        {ref.selection_saved_at && <p className="message-caption">마지막 선정 저장: {new Date(ref.selection_saved_at).toLocaleString("ko-KR", { timeZone: "Asia/Seoul" })} (한국 시간)</p>}
      </div>}
    </>}
  </section>;
}


export function MessageSpatialHistory({ references }: { references?: Record<string, MessageReference> }) {
  if (!references || !Object.keys(references).length) return null;
  return <section className="message-spatial-history" aria-label="과거 버전의 기준점과 선정 시설">
    <h3>이 버전에 저장한 기준점과 시설</h3>
    <p className="message-notice">과거 기록입니다. 현재 기준점·업무 대상 선정과 구분해 확인해 주세요.</p>
    {Object.values(references).map(ref => <article key={ref.location_key} className="message-part">
      <h4>{ref.point.label} · {ref.radius_km}km</h4><blockquote>{ref.evidence}</blockquote>
      <p>기준점 확인 근거: {ref.confirmation_note}</p>
      <p>선정 사유: {ref.selection_note || "선정 저장 전"}</p>
      <ul>{ref.selected.map(f => <li key={f.id}>{f.name} · 직선 {(f.distance_m / 1000).toFixed(2)}km
        {!f.within_radius && <> · 반경 밖 추가 사유: {f.reason}</>}
      </li>)}</ul>
      {!ref.selected.length && <p>이 버전에는 선정한 시설이 없습니다.</p>}
    </article>)}
  </section>;
}
