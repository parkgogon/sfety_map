import type { WeatherLayerKind, WeatherLayerResponse } from "./types";
import {
  formatReferenceTime,
  rainfallColor,
  temperatureColor,
  WEATHER_LAYER_LABELS,
  WIND_SPEED_LEGEND_VALUES,
  windSpeedColor,
} from "./utils";

const OPTIONS: Array<{
  kind: WeatherLayerKind;
  icon: string;
  description: string;
}> = [
  { kind: "rainfall", icon: "◉", description: "1시간 강수량 분포" },
  { kind: "wind", icon: "≈", description: "푸른 풍속 색면과 입자로 보는 바람" },
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

const legendValues = (kind: WeatherLayerKind): readonly number[] => {
  if (kind === "temperature") return [-10, 0, 10, 20, 30, 40];
  if (kind === "wind") return WIND_SPEED_LEGEND_VALUES;
  return [0.1, 1, 5, 15, 30, 60];
};

const colorFor = (kind: WeatherLayerKind, value: number): string => {
  if (kind === "temperature") return temperatureColor(value);
  if (kind === "wind") return windSpeedColor(value);
  return rainfallColor(value);
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
  const windMeaning = "입자 방향=풍향, 이동 속도·꼬리=풍속";
  const labelPrefix = isSimulation
    ? `${WEATHER_LAYER_LABELS[kind]} 모의훈련 기상 가정 (실제 관측이 아님)`
    : `${WEATHER_LAYER_LABELS[kind]} 범례`;
  const values = legendValues(kind);
  return (
    <aside
      className={`weather-layer-legend ${data?.status === "STALE" ? "stale" : ""} ${isSimulation ? "simulation" : ""}`}
      aria-live="polite"
      aria-label={kind === "wind"
        ? `${labelPrefix}. 풍속 색면 0에서 25m/s 이상. ${windMeaning}`
        : labelPrefix}
    >
      <div className="weather-layer-legend-title">
        <div>
          <b>{WEATHER_LAYER_LABELS[kind]}{isSimulation ? " · 훈련값" : " 실황"}</b>
        </div>
        {data && !isSimulation && (
          <small>
            {data.status === "STALE" ? "지연 · " : ""}
            {formatReferenceTime(data.observed_at)}
          </small>
        )}
      </div>
      {loading && !data && <p>{isSimulation ? "기상 가정을 생성하는 중…" : "기상 격자를 불러오는 중…"}</p>}
      {failed && !data?.points.length ? (
        <div className="weather-layer-error">
          <span>⚠️ {(() => {
            const raw = String(error || data?.detail || "");
            if (raw.includes("격자") || raw.includes("Timeout") || raw.includes("연결") || !raw) {
              return "기상청 실황 격자 일시 수신 지연 (재시도 중)";
            }
            return raw;
          })()}</span>
          <button type="button" onClick={onRetry}>다시 시도</button>
        </div>
      ) : data ? (
        <>
          {kind === "wind" ? (
            <>
              <div className="weather-scale-row" aria-label="풍속 색면 범례: 0에서 25m/s 이상">
                <span>{values[0]}</span>
                <div className="weather-color-scale">
                  {values.map((value) => (
                    <span key={value} style={{ backgroundColor: colorFor(kind, value) }} />
                  ))}
                </div>
                <span>{values.at(-1)}{data.unit}+</span>
              </div>
              <div className="weather-particle-key" role="img" aria-label={windMeaning}>
                <span className="weather-particle-swatch" aria-hidden="true">
                  <i /><i /><i />
                </span>
                <span>{windMeaning}</span>
              </div>
            </>
          ) : (
            <div className="weather-scale-row" aria-label={`${WEATHER_LAYER_LABELS[kind]} 범례`}>
              <span>{values[0]}</span>
              <div className="weather-color-scale">
                {values.map((value) => (
                  <span key={value} style={{ backgroundColor: colorFor(kind, value) }} />
                ))}
              </div>
              <span>{values.at(-1)}{data.unit}</span>
            </div>
          )}
          {failed && data.points.length > 0 && (
            <p>갱신 실패 · 이전 정상 자료를 표시하고 있습니다.</p>
          )}
          {noRain && <p>{isSimulation ? "모의훈련 시나리오에 강수가 없습니다." : "현재 관제 권역에 표시할 강수가 없습니다."}</p>}
        </>
      ) : null}
    </aside>
  );
}
