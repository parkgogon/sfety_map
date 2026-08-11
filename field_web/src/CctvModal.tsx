import { useEffect, useState } from "react";
import type { CctvResponse, NearbyCctv } from "./types";
import { cctvDirectionText, formatObservationTime } from "./utils";

interface CctvModalProps {
  cctv: NearbyCctv | null;
  feed: CctvResponse | null;
  simulation: boolean;
  loading: boolean;
  cooldownUntil: number;
  onRefresh: () => void;
  onClose: () => void;
}

export function CctvModal({
  cctv,
  feed,
  simulation,
  loading,
  cooldownUntil,
  onRefresh,
  onClose,
}: CctvModalProps) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    if (!cctv) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [cctv, onClose]);
  useEffect(() => {
    setNow(Date.now());
    if (!cctv || cooldownUntil <= Date.now()) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1_000);
    return () => window.clearInterval(timer);
  }, [cctv, cooldownUntil]);

  if (!cctv || !feed) return null;
  const cooldownSeconds = Math.max(0, Math.ceil((cooldownUntil - now) / 1_000));
  return (
    <div className="cctv-modal-backdrop" role="presentation" onMouseDown={onClose}>
      <section
        className="cctv-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="cctv-title"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <div className="cctv-modal-heading">
          <div>
            <span className="context-eyebrow">CCTV 영상 확인</span>
            <h2 id="cctv-title">{cctv.name}</h2>
            <p>{cctv.distance_km.toFixed(1)}km · {cctv.road_type}</p>
          </div>
          <button className="icon-button" type="button" onClick={onClose} aria-label="CCTV 영상 닫기">×</button>
        </div>
        {simulation && <div className="actual-data-notice">모의훈련 특보와 관계없는 <b>실제 현재 참고정보</b>입니다.</div>}
        <div className="cctv-time-grid">
          <div><span>영상 자료 시각</span><b>{formatObservationTime(cctv.updated_at)}</b></div>
          <div><span>API 조회 시각</span><b>{formatObservationTime(feed.fetched_at)}</b></div>
          <div><span>촬영 방향</span><b>{cctvDirectionText(cctv)}</b></div>
        </div>
        {cctv.bearing_deg !== null && cctv.direction_source && (
          <p className="direction-source">방향 검증 근거 · {cctv.direction_source}</p>
        )}
        <div className="video-frame">
          {cctv.embed_allowed ? (
            <video key={`${cctv.video_url}-${feed.fetched_at}`} controls playsInline preload="metadata">
              <source src={cctv.video_url} type="video/mp4" />
              이 브라우저는 MP4 영상 재생을 지원하지 않습니다.
            </video>
          ) : (
            <div className="video-fallback">
              <strong>내장 재생할 수 없는 영상 주소입니다.</strong>
              <span>HTTPS MP4가 아닌 경우 브라우저 보안 정책으로 재생이 차단될 수 있습니다.</span>
            </div>
          )}
        </div>
        <p className="video-caveat">
          ITS가 최근 영상 URL을 다시 반환할 수 있어, 재조회해도 같은 30초 영상이 보일 수 있습니다. 시각이 없으면 정확한 촬영 시점은 확인할 수 없습니다.
        </p>
        <div className="cctv-modal-actions">
          <button type="button" onClick={onRefresh} disabled={loading || cooldownSeconds > 0}>
            {loading ? "조회 중…" : cooldownSeconds ? `${cooldownSeconds}초 후 재조회` : "최신 정보 다시 조회"}
          </button>
          <a href={cctv.video_url} target="_blank" rel="noreferrer">새 탭에서 영상 열기</a>
          <a href={feed.official_map_url} target="_blank" rel="noreferrer">ITS 공식 교통지도</a>
        </div>
        <small className="cctv-source">{feed.source} · 시설 자체 CCTV가 아닌 인근 도로 현황 참고용</small>
      </section>
    </div>
  );
}
