import { useEffect, useRef, useState } from "react";
import { useKakaoMapRuntime } from "./map/useKakaoMapRuntime";
import { referenceBounds, type MapCoordinate } from "./locationReference";
import type { KakaoMouseEvent, KakaoOverlay } from "./kakaoTypes";
import type { SpatialFacility } from "./messageSpatialApi";

export function MessageReferenceMap({ point, draft, radius, facilities, selectedIds, picking, onPick, preview = false }: {
  point: MapCoordinate | null; draft: MapCoordinate | null; radius: number; facilities: SpatialFacility[];
  selectedIds: string[]; picking: boolean; onPick: (point: MapCoordinate) => void; preview?: boolean;
}) {
  const runtime = useKakaoMapRuntime(true);
  const { elementRef, mapRef, kakaoRef, error, subscribeReady } = runtime;
  const latest = useRef({ picking, onPick }); latest.current = { picking, onPick };
  const [inspected, setInspected] = useState("");
  useEffect(() => {
    let remove = () => {};
    const attach = () => {
      remove(); const map = mapRef.current; const sdk = kakaoRef.current; if (!map || !sdk) return;
      const click = (event: KakaoMouseEvent) => {
        if (latest.current.picking && event.latLng) latest.current.onPick({ latitude: event.latLng.getLat(), longitude: event.latLng.getLng() });
      };
      sdk.maps.event.addListener(map, "click", click);
      remove = () => sdk.maps.event.removeListener(map, "click", click);
    };
    attach(); const off = subscribeReady(attach);
    return () => { off(); remove(); };
  }, [mapRef, kakaoRef, subscribeReady]);
  useEffect(() => {
    let overlays: KakaoOverlay[] = [];
    const clear = () => { overlays.forEach(item => item.setMap(null)); overlays = []; };
    const draw = () => {
      clear(); const map = mapRef.current; const sdk = kakaoRef.current; if (!map || !sdk) return;
      function marker(position: MapCoordinate, text: string, className: string, click?: () => void) {
        const element = document.createElement(click ? "button" : "span");
        element.className = `message-spatial-marker ${className}`; element.textContent = text;
        if (click) { element.setAttribute("type", "button"); element.setAttribute("aria-label", `시설 보기: ${text}`); element.addEventListener("click", event => { event.stopPropagation(); if (!latest.current.picking) click(); }); }
        if (picking) element.style.pointerEvents = "none";
        overlays.push(new sdk!.maps.CustomOverlay({ map, position: new sdk!.maps.LatLng(position.latitude, position.longitude), content: element, yAnchor: 1.15, zIndex: click ? 2 : 5 }));
      }
      facilities.forEach(f => marker(f, f.name, selectedIds.includes(f.id) ? "is-selected" : "is-facility", () => setInspected(`${f.name} · ${(f.distance_m / 1000).toFixed(2)}km`)));
      if (point) {
        overlays.push(new sdk.maps.Circle({ map, center: new sdk.maps.LatLng(point.latitude, point.longitude), radius: radius * 1000,
          strokeColor: "#176b87", strokeWeight: 2, strokeOpacity: .7, fillColor: "#86bed0", fillOpacity: .08 }));
        marker(point, preview ? "추천 조회 위치" : "저장한 기준점", "is-reference");
      }
      if (draft) marker(draft, "확인 전 후보", "is-draft");
    };
    draw(); const off = subscribeReady(draw);
    return () => { off(); clear(); };
  }, [point, draft, radius, facilities, selectedIds, picking, preview, mapRef, kakaoRef, subscribeReady]);
  useEffect(() => {
    const focus = () => {
      const map = mapRef.current; const sdk = kakaoRef.current; const center = draft || point;
      if (!map || !sdk || !center) return;
      map.relayout?.(); const bounds = new sdk.maps.LatLngBounds();
      referenceBounds(center, radius * 1000).forEach(p => bounds.extend(new sdk.maps.LatLng(p.latitude, p.longitude)));
      if (point) bounds.extend(new sdk.maps.LatLng(point.latitude, point.longitude));
      map.setBounds(bounds, 45, 45, 45, 45);
    };
    focus(); const off = subscribeReady(focus);
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(focus);
    if (elementRef.current) observer?.observe(elementRef.current);
    return () => { off(); observer?.disconnect(); };
  }, [point, draft, radius, mapRef, kakaoRef, elementRef, subscribeReady]);
  return <div className="message-spatial-map-wrap">
    <div ref={elementRef} className={`message-spatial-map ${picking ? "is-picking" : ""}`} aria-label="문자 조회 기준점과 참고 시설 지도" />
    {error && <p className="message-notice">지도를 표시할 수 없습니다. 후보 선택·좌표 직접 입력과 시설 목록은 사용할 수 있습니다.</p>}
    <p className="message-caption">{preview ? "추천 위치와 업무 확인 대상 제안입니다." : "청록: 저장한 기준점 · 노랑: 확인 전 후보 · 진한 시설 표식: 현재 선택"}<br />{radius}km 원은 참고 조회 거리입니다.</p>
    {inspected && <p role="status">지도에서 확인한 시설: {inspected} · 업무 대상 선정은 아래 목록에서 해 주세요.</p>}
  </div>;
}
