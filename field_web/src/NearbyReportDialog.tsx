import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { MobileBottomSheet } from "./MobileBottomSheet";
import { formatDistance, nearbyFacilities, type ReferencePoint } from "./locationReference";
import { downloadNearbyReport } from "./nearbyReportApi";
import type { Facility } from "./types";
import "./styles/nearby-report.css";

export function NearbyReportDialog({ point, facilities, onClose }: {
  point: ReferencePoint; facilities: Facility[]; onClose: () => void;
}) {
  const [input, setInput] = useState("5");
  const [pending, setPending] = useState(false);
  const [message, setMessage] = useState("");
  const running = useRef<AbortController | null>(null);
  useEffect(() => () => { running.current?.abort(); running.current = null; }, []);
  const radius = Number(input);
  const valid = input.trim() !== "" && Number.isFinite(radius) && radius >= 0.1 && radius <= 50
    && Math.abs(radius * 10 - Math.round(radius * 10)) < 1e-9;
  const nearby = useMemo(() => nearbyFacilities(facilities, point), [facilities, point]);
  const rows = valid ? nearby.filter((row) => row.meters <= radius * 1000) : [];
  const complete = nearby.length === facilities.length && new Set(facilities.map((f) => f.id)).size === facilities.length;
  const close = () => { running.current?.abort(); onClose(); };
  async function generate(event: React.FormEvent) {
    event.preventDefault();
    if (running.current || !valid || !complete) return;
    const controller = new AbortController();
    running.current = controller;
    setPending(true); setMessage("");
    try {
      const outcome = await downloadNearbyReport(point, radius, rows.map((row) => row.facility.id), controller.signal);
      if (!controller.signal.aborted) setMessage(outcome?.mapIncluded === false
        ? "지도를 생성하지 못해 시설 목록·집계 보고서를 다운로드했습니다." : "PDF를 다운로드했습니다.");
    } catch (error) {
      if (!controller.signal.aborted) setMessage(error instanceof Error ? error.message : "보고서를 생성하지 못했습니다.");
    } finally {
      if (!controller.signal.aborted) { running.current = null; setPending(false); }
    }
  }
  return createPortal(<MobileBottomSheet title="주변 시설 보고서" onClose={close}
    className="nearby-report-dialog" returnFocusSelector="[data-nearby-report-trigger]">
    <form className="nearby-report-form" onSubmit={generate}>
      <div className="nearby-report-reference">
        <strong>{point.label}</strong><span>{point.address || "주소 정보 없음"}</span>
        <small>{point.latitude.toFixed(5)}, {point.longitude.toFixed(5)}</small>
      </div>
      <fieldset disabled={pending}>
        <legend>보고서 반경</legend>
        <div className="nearby-report-radii">{[1, 3, 5].map((km) => <button key={km} type="button"
          aria-pressed={valid && radius === km} onClick={() => setInput(String(km))}>{km}km</button>)}</div>
        <label className="nearby-report-radius-input">직접 입력 (km)
          <input type="number" inputMode="decimal" min="0.1" max="50" step="0.1" required
            aria-describedby="nearby-radius-help" value={input} onChange={(e) => setInput(e.target.value)} />
        </label>
        <small id="nearby-radius-help">0.1~50km · 0.1km 단위 · 지도 거리 원과 별도로 적용</small>
      </fieldset>
      {!valid && <p role="alert">반경을 0.1~50km 사이에서 0.1km 단위로 입력해 주세요.</p>}
      {!complete && <p role="alert">일부 시설 좌표를 확인하지 못했습니다. 새로고침 후 다시 시도해 주세요.</p>}
      {valid && complete && <>
        <p className="nearby-report-count" role="status">반경 {radius}km · 대상 <b>{rows.length}개소</b></p>
        <small>전체 {facilities.length}개소 기준 · 지도 필터·전파 선택과 무관</small>
        <ol className="nearby-report-list" aria-label="보고서 대상 시설 거리순">
          {rows.map(({ facility, meters }) => <li key={facility.id}>
            <span><strong>{facility.name}</strong><small>{facility.type || facility.group_label}</small><small>{facility.address}</small></span>
            <b>{formatDistance(meters)}</b>
          </li>)}
        </ol>
        {rows.length === 0 && <p>반경 내 등록시설이 없습니다. 0개소 보고서를 생성합니다.</p>}
      </>}
      <p className="nearby-report-note">직선거리 기준입니다. 반경 안의 위치가 실제 피해나 영향을 뜻하지 않습니다.</p>
      {pending && <p role="status">지도와 보고서를 생성하고 있습니다. 지도 생성에 실패하면 시설 목록·집계를 제공합니다.</p>}
      <div className="nearby-report-buttons">
        <button type="button" onClick={close}>{pending ? "생성 취소·닫기" : "취소"}</button>
        <button className="nearby-report-submit" type="submit" disabled={pending || !valid || !complete}>
          {pending ? "PDF 생성 중…" : "PDF 생성"}</button>
      </div>
      {message && <p role="status">{message}</p>}
    </form>
  </MobileBottomSheet>, document.body);
}
