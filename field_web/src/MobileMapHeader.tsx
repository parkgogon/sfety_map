import type { MonitoringMode, MonitoringResponse } from "./types";
import { formatElapsedTime } from "./utils";
import { MobileBottomSheet } from "./MobileBottomSheet";
import type { MobilePanel } from "./useMobileLayout";

export const KMA_OFFICIAL_WARNING_URL = "https://www.weather.go.kr/w/special-report/overall.do";

/** Explicit KST keeps the compact header and the full status timestamp consistent. */
export function formatMobileReferenceTime(value: string, full = false, now = new Date()): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "시각 미확인";
  const formatter = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Seoul", year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", hourCycle: "h23",
  });
  const parts = (target: Date) => Object.fromEntries(formatter.formatToParts(target).map((part) => [part.type, part.value]));
  const p = parts(date);
  const today = parts(now);
  const time = `${p.hour}:${p.minute}`;
  if (full) return `${p.year}.${p.month}.${p.day} ${time} (KST)`;
  return ["year", "month", "day"].every((key) => p[key] === today[key]) ? time : `${p.month}.${p.day} ${time}`;
}

interface HeaderProps {
  data: MonitoringResponse;
  mode: MonitoringMode;
  additionalNotice: boolean;
  panel: MobilePanel;
  onOpen: (panel: "status" | "more") => void;
}

export function MobileMapHeader({ data, mode, additionalNotice, panel, onOpen }: HeaderProps) {
  const health = data.status.health;
  const simulation = mode === "simulation" || health === "SIMULATION";
  const state = simulation ? "simulation" : health === "LIVE" ? "live" : health === "STALE" ? "stale" : "error";
  const label = simulation ? "모의훈련 · 실제 상황 아님" : health === "LIVE" ? "KMA 정상"
    : health === "STALE" ? "KMA 수신 지연" : "KMA 조회 불가";
  return <>
    <header className="mobile-map-header">
      <h1>
        <button type="button" className="mobile-status-button" onClick={() => onOpen("status")}
          aria-label={`현장 안전지도 자료 상태: ${label}${additionalNotice ? ", 추가 안내 있음" : ""}`}
          aria-haspopup="dialog" aria-expanded={panel === "status"}>
          <span className="mobile-map-title">현장 안전지도</span>
          <span className={`mobile-map-status ${state}`} role="status">
            <span className="mobile-status-dot" aria-hidden="true" />
            <span>{label} · {formatMobileReferenceTime(data.generated_at)} 기준{additionalNotice ? " · 안내" : ""}</span>
          </span>
        </button>
      </h1>
      <button type="button" className="mobile-icon-button" aria-label="더보기" aria-haspopup="dialog"
        aria-expanded={panel === "more"} onClick={() => onOpen("more")}>
        <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="5" cy="12" r="1" /><circle cx="12" cy="12" r="1" /><circle cx="19" cy="12" r="1" /></svg>
      </button>
    </header>
    {!simulation && state !== "live" && <div className={`mobile-data-notice ${state}`} role="status">
      <span>{state === "stale" ? "수신 지연 · 마지막 정상 자료 표시 중" : "특보 조회 불가 · 시설 위치만 확인 가능"}</span>
      <button type="button" onClick={() => onOpen("status")} aria-label="자료 상태 자세히">자세히</button>
    </div>}
  </>;
}

interface PanelProps {
  panel: "status" | "more";
  data: MonitoringResponse;
  mode: MonitoringMode;
  refreshing: boolean;
  error: string;
  deepLinkNotice: string;
  onClose: () => void;
  onRefresh: () => void;
  onControl: () => void;
  onChangeMode: (mode: MonitoringMode) => void;
}

export function MobileHeaderPanel({ panel, data, mode, refreshing, error, deepLinkNotice,
  onClose, onRefresh, onControl, onChangeMode }: PanelProps) {
  const stale = data.status.health === "STALE";
  return <MobileBottomSheet title={panel === "status" ? "자료 상태" : "더보기"} onClose={onClose}>
    {panel === "status" ? <div className="mobile-status-details">
      <p>KMA 수신 상태는 시설의 안전 판정과 다릅니다.</p>
      {(mode === "simulation" || data.status.health === "SIMULATION") && <p>모의훈련 자료입니다. 실제 상황이 아닙니다.</p>}
      <dl>
        <div><dt>{stale ? "마지막 정상 자료 기준" : "자료 기준"}</dt><dd>{formatMobileReferenceTime(data.generated_at, true)}
          {stale && <span> · {formatElapsedTime(data.generated_at)}</span>}</dd></div>
        <div><dt>수신 기준 시각</dt><dd>{formatMobileReferenceTime(data.status.fetched_at, true)}</dd></div>
      </dl>
      {data.status.detail && <p>{data.status.detail}</p>}
      {data.status.zone_health === "FALLBACK" && <p>최신 특보 경계 대신 검증된 내장 경계를 사용 중입니다.</p>}
      {data.status.zone_detail && <p>{data.status.zone_detail}</p>}
      {error && <p>{error}</p>}
      {deepLinkNotice && <p>{deepLinkNotice}</p>}
    </div> : <nav className="mobile-more-actions" aria-label="현장 지도 작업">
      <button type="button" onClick={onControl}>중앙관제 열기</button>
      <button type="button" onClick={onRefresh} disabled={refreshing}>{refreshing ? "관제 자료 갱신 중…" : "관제 자료 새로고침"}</button>
      <a href={KMA_OFFICIAL_WARNING_URL} target="_blank" rel="noreferrer">기상청 특보 보기 ↗</a>
      <button type="button" onClick={() => onChangeMode(mode === "simulation" ? "live" : "simulation")}>
        {mode === "simulation" ? "실시간 화면으로 돌아가기" : "모의훈련 화면 보기"}
      </button>
    </nav>}
  </MobileBottomSheet>;
}
