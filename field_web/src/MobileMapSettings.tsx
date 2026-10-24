import { FacilityIcon } from "./facilityIcons";
import { GRADE_HELP, WARNING_ZONE_LEGENDS } from "./GradeLegend";
import { MobileBottomSheet } from "./MobileBottomSheet";
import type {
  FacilityGroup,
  RiskGrade,
  WeatherLayerKind,
  WeatherLayerResponse,
} from "./types";
import type { MobileSettingsTab } from "./useMobileLayout";
import { formatReferenceTime, GRADE_COLORS, GRADE_DISPLAY_ORDER, GRADE_LABELS } from "./utils";

interface Props {
  tab: MobileSettingsTab;
  groups: FacilityGroup[];
  selectedGroups: ReadonlySet<string>;
  selectedGrades: ReadonlySet<RiskGrade>;
  visibleCount: number;
  totalCount: number;
  weatherKind: WeatherLayerKind | null;
  weatherData: WeatherLayerResponse | null;
  weatherLoading: boolean;
  weatherError: string;
  simulation: boolean;
  onSelectTab: (tab: MobileSettingsTab) => void;
  onToggleGroup: (id: string) => void;
  onToggleGrade: (grade: RiskGrade) => void;
  onResetFilters: () => void;
  onSelectWeather: (kind: WeatherLayerKind | null) => void;
  onClose: () => void;
}

const WEATHER_OPTIONS: Array<{ kind: WeatherLayerKind | null; label: string; description: string }> = [
  { kind: null, label: "끄기", description: "기상 그래픽을 표시하지 않습니다." },
  { kind: "rainfall", label: "강수", description: "1시간 강수량 분포" },
  { kind: "wind", label: "바람", description: "풍속 색면과 입자로 보는 바람" },
  { kind: "temperature", label: "기온", description: "현재 기온 분포" },
];

function WeatherStatus({ data, loading, error, simulation }: {
  data: WeatherLayerResponse | null;
  loading: boolean;
  error: string;
  simulation: boolean;
}) {
  if (loading && !data) return <p className="mobile-settings-note">기상 자료를 불러오는 중입니다.</p>;
  if (error && !data) return <p className="mobile-settings-note problem">기상 자료를 불러오지 못했습니다. 지도에서 다시 시도할 수 있습니다.</p>;
  if (!data) return null;
  const status = simulation || data.status === "SIMULATION"
    ? "모의훈련 값 · 실제 관측 아님"
    : data.status === "STALE"
      ? "수신 지연 · 이전 정상 자료 표시 중"
      : data.status === "ERROR"
        ? "자료 조회 불가"
        : "기상청 실황";
  return <p className={`mobile-settings-note ${data.status === "STALE" || data.status === "ERROR" ? "problem" : ""}`}>
    <b>{status}</b>{data.observed_at ? ` · ${formatReferenceTime(data.observed_at)}` : ""}
  </p>;
}

export function MobileMapSettings({
  tab,
  groups,
  selectedGroups,
  selectedGrades,
  visibleCount,
  totalCount,
  weatherKind,
  weatherData,
  weatherLoading,
  weatherError,
  simulation,
  onSelectTab,
  onToggleGroup,
  onToggleGrade,
  onResetFilters,
  onSelectWeather,
  onClose,
}: Props) {
  return <MobileBottomSheet
    title="지도 설정"
    onClose={onClose}
    footer={<div className="mobile-settings-footer">
      <span>현재 <b>{visibleCount}개</b> / 전체 {totalCount}개 표시</span>
      <button className="primary-button" type="button" onClick={onClose}>지도 보기</button>
    </div>}
  >
    <div className="mobile-settings-tabs" role="tablist" aria-label="지도 설정 항목">
      {(["facilities", "weather", "legend"] as const).map((item) => <button
        key={item}
        type="button"
        role="tab"
        aria-selected={tab === item}
        onClick={() => onSelectTab(item)}
      >{{ facilities: "시설", weather: "기상", legend: "범례" }[item]}</button>)}
    </div>

    {tab === "facilities" && <div className="mobile-settings-section" role="tabpanel">
      <div className="mobile-settings-section-heading">
        <div><h3>시설 유형</h3><p>각 개수는 전체 시설 기준입니다.</p></div>
        <button type="button" onClick={onResetFilters}>전체 표시</button>
      </div>
      <div className="mobile-setting-options group-options">
        {groups.map((group) => <label key={group.id}>
          <input type="checkbox" checked={selectedGroups.has(group.id)} onChange={() => onToggleGroup(group.id)} />
          <FacilityIcon groupId={group.id} size={16} className="group-option-icon" />
          <span>{group.label}</span><b>{group.count}</b>
        </label>)}
      </div>
      <div className="mobile-settings-section-heading grade-heading"><div><h3>위험등급</h3><p>여러 등급을 함께 선택할 수 있습니다.</p></div></div>
      <div className="mobile-setting-options grade-filter-options">
        {GRADE_DISPLAY_ORDER.map((grade) => <label key={grade}>
          <input type="checkbox" checked={selectedGrades.has(grade)} onChange={() => onToggleGrade(grade)} />
          <span className="mobile-legend-color round" style={{ backgroundColor: GRADE_COLORS[grade] }} />
          <span>{GRADE_LABELS[grade]}</span>
        </label>)}
      </div>
      {visibleCount === 0 && <div className="mobile-zero-results" role="status">
        <span>표시할 시설이 없습니다.</span>
        <button type="button" onClick={onResetFilters}>전체 시설 복구</button>
      </div>}
    </div>}

    {tab === "weather" && <div className="mobile-settings-section" role="tabpanel">
      <h3>{simulation ? "기상 가정" : "기상 실황"}</h3>
      <div className="mobile-weather-options">
        {WEATHER_OPTIONS.map((option) => <button
          type="button"
          key={option.kind ?? "off"}
          className={weatherKind === option.kind ? "active" : ""}
          aria-pressed={weatherKind === option.kind}
          aria-label={`${option.label} 기상 레이어${weatherKind === option.kind ? " 선택됨" : ""}`}
          onClick={() => onSelectWeather(option.kind)}
        >
          <span><b>{option.label}</b><small>{option.description}</small></span>
          <i aria-hidden="true">{weatherKind === option.kind ? "✓" : ""}</i>
        </button>)}
      </div>
      <WeatherStatus data={weatherData} loading={weatherLoading} error={weatherError} simulation={simulation} />
      <p className="mobile-settings-caveat">
        {simulation
          ? "모의훈련 특보에 연관된 기상 가정값이며 실제 관측이 아닙니다. 시설 위험등급에는 반영하지 않습니다."
          : "기상청 격자 실황 참고정보이며 시설 위험등급에는 반영하지 않습니다."}
      </p>
    </div>}

    {tab === "legend" && <div className="mobile-settings-section mobile-readonly-legend" role="tabpanel">
      <h3>시설 유형</h3>
      <div className="mobile-facility-legend">
        {groups.map((group) => <div key={group.id}>
          <FacilityIcon groupId={group.id} size={18} />
          <span>{group.label}</span>
        </div>)}
      </div>
      <h3>시설 마커 위험등급</h3>
      <dl>
        {GRADE_DISPLAY_ORDER.map((grade) => <div key={grade}>
          <dt><span className="mobile-legend-color round" style={{ backgroundColor: GRADE_COLORS[grade] }} />{GRADE_LABELS[grade]}</dt>
          <dd>{GRADE_HELP[grade]}</dd>
        </div>)}
      </dl>
      <h3>특보 발효 구역</h3>
      <dl>
        {WARNING_ZONE_LEGENDS.map((zone) => <div key={zone.key}>
          <dt><span className="mobile-legend-color" style={{ backgroundColor: zone.color }} />{zone.label}</dt>
          <dd>{zone.desc}</dd>
        </div>)}
      </dl>
    </div>}
  </MobileBottomSheet>;
}
