import { useEffect, useState } from "react";
import type { CctvResponse, Facility, NearbyCctv, WeatherResponse } from "./types";
import {
  cctvDirectionText,
  formatObservationTime,
  uniqueWarningText,
  weatherSummary,
  windDirectionLabel,
} from "./utils";

interface FacilitySheetProps {
  facility: Facility | null;
  simulation: boolean;
  cctvEnabled: boolean;
  weather: WeatherResponse | null;
  weatherLoading: boolean;
  weatherError: string;
  onRetryWeather: () => void;
  cctv: CctvResponse | null;
  cctvLoading: boolean;
  cctvError: string;
  cctvCooldownUntil: number;
  onLoadCctv: () => void;
  onSelectCctv: (cctv: NearbyCctv) => void;
  onClose: () => void;
}

function ActualDataBadge({ simulation }: { simulation: boolean }) {
  if (!simulation) return null;
  return <span className="actual-data-badge">실제 현재 참고정보</span>;
}

export function FacilityWeather({
  weather,
  expanded,
}: {
  weather: WeatherResponse;
  expanded: boolean;
}) {
  if (!expanded) {
    return (
      <div className="weather-summary">
        <b>{weatherSummary(weather)}</b>
        <span>{formatObservationTime(weather.observed_at)} 관측</span>
      </div>
    );
  }
  return (
    <>
      <div className="weather-details">
        <div><span>기온</span><b>{weather.temperature_c ?? "—"}℃</b></div>
        <div><span>1시간 강수</span><b>{weather.rainfall_1h_mm ?? "—"}mm</b></div>
        <div className="wind-detail">
          <span>풍향</span>
          <b>
            <i
              className="wind-arrow"
              style={{ transform: `rotate(${weather.wind_direction_deg ?? 0}deg)` }}
              aria-hidden="true"
            >↑</i>
            {windDirectionLabel(weather.wind_direction_deg)}
          </b>
        </div>
        <div><span>풍속</span><b>{weather.wind_speed_ms ?? "—"}m/s</b></div>
      </div>
      <div className="weather-observation-time">
        {formatObservationTime(weather.observed_at)} 관측
      </div>
    </>
  );
}

export function FacilitySheet({
  facility,
  simulation,
  cctvEnabled,
  weather,
  weatherLoading,
  weatherError,
  onRetryWeather,
  cctv,
  cctvLoading,
  cctvError,
  cctvCooldownUntil,
  onLoadCctv,
  onSelectCctv,
  onClose,
}: FacilitySheetProps) {
  const [expanded, setExpanded] = useState(false);
  const [now, setNow] = useState(Date.now());

  useEffect(() => setExpanded(false), [facility?.id]);
  useEffect(() => {
    setNow(Date.now());
    if (cctvCooldownUntil <= Date.now()) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1_000);
    return () => window.clearInterval(timer);
  }, [cctvCooldownUntil]);

  if (!facility) {
    return (
      <section className="facility-sheet empty-sheet" aria-label="선택 시설 안내">
        <span className="sheet-handle" aria-hidden="true" />
        <b>확인할 시설을 선택하세요</b>
        <span>지도 마커를 누르거나 시설명을 검색할 수 있습니다.</span>
      </section>
    );
  }

  const cooldownSeconds = Math.max(0, Math.ceil((cctvCooldownUntil - now) / 1_000));
  const weatherLive = weather?.status === "LIVE";
  return (
    <section className={`facility-sheet ${expanded ? "expanded" : ""}`} aria-label="선택 시설 상세">
      <span className="sheet-handle" aria-hidden="true" />
      <div className="facility-heading">
        <span className="grade-badge" style={{ backgroundColor: facility.grade_color }}>
          {facility.grade_label}
        </span>
        <div>
          <h2>{facility.name}</h2>
          <p>{facility.group_label}</p>
        </div>
        <button className="icon-button close-button" type="button" onClick={onClose} aria-label="시설 선택 닫기">
          ×
        </button>
      </div>
      <div className="facility-alert-line">
        <span>영향 특보</span>
        <strong>{uniqueWarningText(facility)}</strong>
      </div>
      <div className="facility-action">
        <span>권장 행동</span>
        <strong>{facility.recommended_action}</strong>
      </div>

      <section className="weather-context" aria-label="시설 위치 현재 기상" aria-busy={weatherLoading}>
        <div className="context-title-row">
          <strong>현재 기상</strong>
          <ActualDataBadge simulation={simulation} />
        </div>
        {weatherLoading && <div className="weather-loading">시설 위치의 기상을 확인 중입니다…</div>}
        {!weatherLoading && weatherLive && weather && (
          <FacilityWeather weather={weather} expanded={expanded} />
        )}
        {!weatherLoading && (weatherError || (weather && !weatherLive)) && (
          <div className="context-error">
            <span>{weatherError || weather?.detail || "기상 자료를 확인할 수 없습니다."}</span>
            <button type="button" onClick={onRetryWeather}>다시 시도</button>
          </div>
        )}
        <small>현장 센서가 아닌, 시설 위치가 속한 KMA 격자의 초단기실황입니다.</small>
      </section>

      {cctvEnabled && <section className="cctv-context" aria-label="인근 도로 CCTV" aria-busy={cctvLoading}>
        <div className="context-title-row">
          <strong>인근 도로 CCTV</strong>
          <ActualDataBadge simulation={simulation} />
        </div>
        {!cctv && !cctvError && (
          <button className="context-load-button" type="button" onClick={onLoadCctv} disabled={cctvLoading}>
            {cctvLoading ? "CCTV 확인 중…" : "인근 CCTV 불러오기"}
          </button>
        )}
        {cctvError && (
          <div className="context-error">
            <span>{cctvError}</span>
            <button type="button" onClick={onLoadCctv} disabled={cooldownSeconds > 0}>
              {cooldownSeconds ? `${cooldownSeconds}초 후 재시도` : "다시 시도"}
            </button>
          </div>
        )}
        {cctv && (
          <>
            <div className={`context-status ${cctv.status.toLowerCase()}`}>
              <span>{cctv.detail || (cctv.cctvs.length ? `CCTV ${cctv.cctvs.length}곳` : "조회 결과 없음")}</span>
              <button type="button" onClick={onLoadCctv} disabled={cctvLoading || cooldownSeconds > 0}>
                {cctvLoading
                  ? "조회 중…"
                  : cooldownSeconds
                    ? `${cooldownSeconds}초 후 갱신`
                    : "최신 정보 다시 조회"}
              </button>
            </div>
            {cctv.direction_warning && <p className="context-warning">{cctv.direction_warning}</p>}
            {cctv.cctvs.length > 0 ? (
              <div className="cctv-list">
                {cctv.cctvs.map((item) => (
                  <button type="button" key={item.id} onClick={() => onSelectCctv(item)}>
                    <span className="camera-badge" aria-hidden="true">▣</span>
                    <span>
                      <b>{item.name}</b>
                      <small>{item.distance_km.toFixed(1)}km · {item.road_type} · {cctvDirectionText(item)}</small>
                    </span>
                  </button>
                ))}
              </div>
            ) : (
              <p className="context-empty">반경 20km 안에 표시할 도로 CCTV가 없습니다.</p>
            )}
          </>
        )}
        <small>CCTV는 시설 자체가 아닌 인근 도로 현황 참고용입니다.</small>
      </section>}

      {expanded && (
        <div className="facility-details">
          <dl>
            <div><dt>판정 설명</dt><dd>{facility.meaning}</dd></div>
            <div><dt>주소</dt><dd>{facility.address}</dd></div>
            <div><dt>담당</dt><dd>{facility.public_contact}</dd></div>
          </dl>
          {facility.reasons.length > 0 && (
            <ul className="reason-list">
              {facility.reasons.map((reason) => (
                <li key={`${reason.warning_id}-${reason.type}`}>
                  <b>{reason.type} {reason.raw_level}</b>
                  <span>{reason.region} · 이 시설에 영향</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
      <button className="sheet-toggle" type="button" onClick={() => setExpanded((value) => !value)}>
        {expanded ? "간단히 보기" : "시설정보 자세히"}
        <span aria-hidden="true">{expanded ? "⌄" : "⌃"}</span>
      </button>
    </section>
  );
}
