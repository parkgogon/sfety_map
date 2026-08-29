import type { WeatherLayerKind, WeatherLayerResponse } from "./types";
import {
  formatReferenceTime,
  rainfallColor,
  temperatureColor,
  WEATHER_LAYER_LABELS,
  windSpeedColor,
} from "./utils";

const OPTIONS: Array<{
  kind: WeatherLayerKind;
  icon: string;
  description: string;
}> = [
  { kind: "rainfall", icon: "◉", description: "1시간 강수량 분포" },
  { kind: "wind", icon: "↗", description: "향하는 방향과 풍속" },
  { kind: "temperature", icon: "°", description: "현재 기온 분포" },
];

interface WeatherLayerSheetProps {
  active: WeatherLayerKind | null;
  simulation?: boolean;
  onSelect: (kind: WeatherLayerKind | null) => void;
  onClose: () => void;
}

export function WeatherLayerSheet({ active, simulation, onSelect, onClose }: WeatherLayerSheetProps) {
  return (
    <div className="modal-backdrop" role="presentation" onMouseDown={onClose}>
      <section
        className="weather-layer-sheet"
        role="dialog"
        aria-modal="true"
        aria-labelledby="weather-layer-title"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <span className="sheet-handle" aria-hidden="true" />
        <div className="filter-title-row">
          <div>
            <h2 id="weather-layer-title">{simulation ? "기상 가정" : "기상 실황"}</h2>
            <p>{simulation ? "모의훈련 특보에 연관된 기상 가정값 하나를 선택하세요." : "지도에 표시할 자료 하나를 선택하세요."}</p>
          </div>
          <button className="icon-button" type="button" onClick={onClose} aria-label="기상 선택 닫기">×</button>
        </div>
        <div className="weather-layer-options">
          {OPTIONS.map((option) => (
            <button
              type="button"
              key={option.kind}
              className={active === option.kind ? "active" : ""}
              onClick={() => onSelect(option.kind)}
            >
              <span aria-hidden="true">{option.icon}</span>
              <span><b>{WEATHER_LAYER_LABELS[option.kind]}</b><small>{option.description}</small></span>
              <i aria-hidden="true">{active === option.kind ? "✓" : ""}</i>
            </button>
          ))}
        </div>
        <button
          className="weather-layer-off"
          type="button"
          onClick={() => onSelect(null)}
          disabled={active === null}
        >
          기상 그래픽 끄기
        </button>
        <small className="weather-layer-caveat">
          {simulation
            ? "모의훈련 특보에 연관된 기상 가정값입니다. 실제 관측이 아니며 시설 위험등급에는 반영하지 않습니다."
            : "기상청 격자 실황 참고정보이며 시설 위험등급에는 반영하지 않습니다."}
        </small>
      </section>
    </div>
  );
}

interface WeatherLayerLegendProps {
  kind: WeatherLayerKind;
  data: WeatherLayerResponse | null;
  loading: boolean;
  error: string;
  simulation: boolean;
  onRetry: () => void;
}

const legendValues = (kind: WeatherLayerKind): number[] => {
  if (kind === "temperature") return [-10, 0, 10, 20, 30, 40];
  if (kind === "rainfall") return [0.1, 1, 5, 15, 30, 60];
  return [0, 4, 8, 14, 20, 25];
};

const colorFor = (kind: WeatherLayerKind, value: number): string => {
  if (kind === "temperature") return temperatureColor(value);
  if (kind === "rainfall") return rainfallColor(value);
  return windSpeedColor(value);
};

export function WeatherLayerLegend({
  kind,
  data,
  loading,
  error,
  simulation,
  onRetry,
}: WeatherLayerLegendProps) {
  const isSimulation = simulation || data?.status === "SIMULATION";
  const failed = error || data?.status === "ERROR";
  const noRain = kind === "rainfall"
    && data?.status !== "ERROR"
    && data?.points.every((point) => (point.value ?? 0) <= 0);
  const values = legendValues(kind);
  return (
    <aside className={`weather-layer-legend ${data?.status === "STALE" ? "stale" : ""} ${isSimulation ? "simulation" : ""}`} aria-live="polite">
      <div className="weather-layer-legend-title">
        <div>
          <b>{WEATHER_LAYER_LABELS[kind]} {isSimulation ? "(모의훈련 가정)" : "실황"}</b>
          {isSimulation && <span>실제 관측이 아님</span>}
        </div>
        {data && (
          <small>
            {data.status === "STALE" ? "지연 · " : ""}
            {isSimulation ? (data.scenario_label || "모의훈련 시나리오") : formatReferenceTime(data.observed_at)}
          </small>
        )}
      </div>
      {loading && !data && <p>{isSimulation ? "기상 가정을 생성하는 중…" : "기상 격자를 불러오는 중…"}</p>}
      {failed && !data?.points.length ? (
        <div className="weather-layer-error">
          <span>{error || data?.detail}</span>
          <button type="button" onClick={onRetry}>다시 시도</button>
        </div>
      ) : data ? (
        <>
          <div className="weather-scale-row" aria-label={`${WEATHER_LAYER_LABELS[kind]} 범례`}>
            <span>{values[0]}</span>
            <div className="weather-color-scale">
              {values.map((value) => (
                <span key={value} style={{ backgroundColor: colorFor(kind, value) }} />
              ))}
            </div>
            <span>{values.at(-1)}{data.unit}</span>
          </div>
          {failed && data.points.length > 0 && (
            <p>갱신 실패 · 이전 정상 자료를 표시하고 있습니다.</p>
          )}
          {noRain && <p>{isSimulation ? "모의훈련 시나리오에 강수가 없습니다." : "현재 관제 권역에 표시할 강수가 없습니다."}</p>}
        </>
      ) : null}
    </aside>
  );
}

