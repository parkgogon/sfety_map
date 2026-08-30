import type { MapInformationCardContent } from "./MapInformationCard";
import type { MonitoringWarningItem, WarningZoneFeature } from "./types";

const LEVEL_WEIGHT: Record<string, number> = {
  CRITICAL: 4,
  WARNING: 3,
  ADVISORY: 2,
  UNKNOWN: 1,
};

/** ISO 시각 문자열을 'MM.DD HH:mm' 형태로 변환합니다. */
export function formatWarningTime(isoTime?: string | null): string {
  if (!isoTime) return "";
  try {
    const date = new Date(isoTime);
    if (Number.isNaN(date.getTime())) return "";
    const month = String(date.getMonth() + 1).padStart(2, "0");
    const day = String(date.getDate()).padStart(2, "0");
    const hours = String(date.getHours()).padStart(2, "0");
    const minutes = String(date.getMinutes()).padStart(2, "0");
    return `${month}.${day} ${hours}:${minutes}`;
  } catch {
    return "";
  }
}

/** 구역코드별로 발효 중인 특보 목록을 그룹화합니다. */
export function groupWarningsByRegion(
  warnings: MonitoringWarningItem[],
): Map<string, MonitoringWarningItem[]> {
  const map = new Map<string, MonitoringWarningItem[]>();
  warnings.forEach((warning) => {
    if (!warning.region_code) return;
    const list = map.get(warning.region_code);
    if (list) list.push(warning);
    else map.set(warning.region_code, [warning]);
  });
  return map;
}

/** 특보 우선순위(경보 > 주의보 > 발표시각)에 따라 정렬합니다. */
export function sortWarningsBySeverity(
  warnings: MonitoringWarningItem[],
): MonitoringWarningItem[] {
  return [...warnings].sort((a, b) => {
    const weightA = LEVEL_WEIGHT[a.level ?? ""] ?? (a.raw_level.includes("경보") ? 3 : 2);
    const weightB = LEVEL_WEIGHT[b.level ?? ""] ?? (b.raw_level.includes("경보") ? 3 : 2);
    if (weightA !== weightB) return weightB - weightA;
    return (b.effective_at ?? b.issued_at ?? "").localeCompare(a.effective_at ?? a.issued_at ?? "");
  });
}

/**
 * 특보 폴리곤 클릭 시 표시할 MapInformationCard용 콘텐츠를 생성합니다.
 */
export function buildWarningCardContent(
  feature: WarningZoneFeature,
  regionWarnings: MonitoringWarningItem[],
  isSimulation = false,
): MapInformationCardContent {
  const regionName = feature.properties.region || "특보 구역";
  const labelFallback = feature.properties.label || "기상특보";

  const eyebrow = isSimulation ? "기상특보 (모의훈련)" : "기상특보 발효 구역";
  const title = regionName;

  // 매칭된 특보 목록이 있는 경우
  if (regionWarnings.length > 0) {
    const sorted = sortWarningsBySeverity(regionWarnings);
    const primary = sorted[0];
    const value = `${primary.type} ${primary.raw_level}${sorted.length > 1 ? ` 외 ${sorted.length - 1}건` : ""}`;

    const lines = sorted.map((item) => {
      const timeStr = formatWarningTime(item.effective_at ?? item.issued_at);
      const suffix = isSimulation
        ? " (훈련 가정)"
        : timeStr
        ? ` (${timeStr} 발효)`
        : "";
      return `• ${item.type} ${item.raw_level}${suffix}`;
    });

    const meta: string[] = isSimulation
      ? ["모의훈련 특보 · 실제 상황이 아님", `구역코드: ${feature.properties.region_code}`]
      : ["기상청 공식 발효 특보", `구역코드: ${feature.properties.region_code}`];

    return {
      eyebrow,
      title,
      value,
      lines,
      meta,
      tone: isSimulation ? "simulation" : "default",
    };
  }

  // 매칭된 목록이 없을 때 feature.properties.label fallback
  const lines = labelFallback
    .split("/")
    .map((item) => item.trim())
    .filter(Boolean)
    .map((item) => `• ${item}`);

  const meta: string[] = isSimulation
    ? ["모의훈련 특보 · 실제 상황이 아님", `구역코드: ${feature.properties.region_code}`]
    : ["기상청 공식 발효 특보", `구역코드: ${feature.properties.region_code}`];

  return {
    eyebrow,
    title,
    value: labelFallback,
    lines: lines.length > 0 ? lines : [`• ${labelFallback}`],
    meta,
    tone: isSimulation ? "simulation" : "default",
  };
}
