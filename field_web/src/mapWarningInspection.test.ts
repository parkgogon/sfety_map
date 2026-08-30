import { describe, expect, it } from "vitest";
import {
  buildWarningCardContent,
  formatWarningTime,
  groupWarningsByRegion,
  sortWarningsBySeverity,
} from "./mapWarningInspection";
import type { MonitoringWarningItem, WarningZoneFeature } from "./types";

describe("mapWarningInspection 단위 테스트", () => {
  describe("formatWarningTime", () => {
    it("ISO 시각 문자열을 'MM.DD HH:mm' 포맷으로 정상 변환한다", () => {
      const formatted = formatWarningTime("2026-08-30T09:30:00+09:00");
      expect(formatted).toBe("08.30 09:30");
    });

    it("null, undefined, 잘못된 형식은 빈 문자열을 반환한다", () => {
      expect(formatWarningTime(null)).toBe("");
      expect(formatWarningTime(undefined)).toBe("");
      expect(formatWarningTime("invalid-date")).toBe("");
    });
  });

  describe("groupWarningsByRegion & sortWarningsBySeverity", () => {
    const warnings: MonitoringWarningItem[] = [
      {
        id: "w1",
        region_code: "L1020100",
        region: "대구광역시",
        type: "폭염",
        raw_level: "주의보",
        level: "ADVISORY",
        effective_at: "2026-08-30T10:00:00+09:00",
      },
      {
        id: "w2",
        region_code: "L1020100",
        region: "대구광역시",
        type: "호우",
        raw_level: "경보",
        level: "WARNING",
        effective_at: "2026-08-30T09:00:00+09:00",
      },
      {
        id: "w3",
        region_code: "L1020200",
        region: "경주시",
        type: "강풍",
        raw_level: "주의보",
        level: "ADVISORY",
        effective_at: "2026-08-30T08:00:00+09:00",
      },
    ];

    it("구역코드별로 특보 목록을 정상 그룹화한다", () => {
      const grouped = groupWarningsByRegion(warnings);
      expect(grouped.get("L1020100")).toHaveLength(2);
      expect(grouped.get("L1020200")).toHaveLength(1);
      expect(grouped.get("L9999999")).toBeUndefined();
    });

    it("경보가 주의보보다 우선하여 정렬된다", () => {
      const daegu = warnings.filter((w) => w.region_code === "L1020100");
      const sorted = sortWarningsBySeverity(daegu);
      expect(sorted[0].type).toBe("호우");
      expect(sorted[0].raw_level).toBe("경보");
      expect(sorted[1].type).toBe("폭염");
      expect(sorted[1].raw_level).toBe("주의보");
    });
  });

  describe("buildWarningCardContent", () => {
    const sampleFeature: WarningZoneFeature = {
      type: "Feature",
      properties: {
        region_code: "L1020100",
        region: "대구광역시",
        label: "호우 경보 / 폭염 주의보",
        level: "WARNING",
        color: "#D92D20",
      },
      geometry: {
        type: "Polygon",
        coordinates: [[[128.5, 35.8], [128.6, 35.8], [128.6, 35.9], [128.5, 35.8]]],
      },
    };

    it("실시간 모드에서 발효 시각과 특보 목록을 올바르게 포함하는 카드 콘텐츠를 생성한다", () => {
      const regionWarnings: MonitoringWarningItem[] = [
        {
          id: "w1",
          region_code: "L1020100",
          region: "대구광역시",
          type: "호우",
          raw_level: "경보",
          level: "WARNING",
          effective_at: "2026-08-30T09:00:00+09:00",
        },
        {
          id: "w2",
          region_code: "L1020100",
          region: "대구광역시",
          type: "폭염",
          raw_level: "주의보",
          level: "ADVISORY",
          effective_at: "2026-08-30T10:00:00+09:00",
        },
      ];

      const content = buildWarningCardContent(sampleFeature, regionWarnings, false);
      expect(content.eyebrow).toBe("기상특보 발효 구역");
      expect(content.title).toBe("대구광역시");
      expect(content.value).toBe("호우 경보 외 1건");
      expect(content.lines).toHaveLength(2);
      expect(content.lines[0]).toContain("호우 경보");
      expect(content.lines[0]).toContain("08.30 09:00 발효");
      expect(content.lines[1]).toContain("폭염 주의보");
      expect(content.meta).toContain("기상청 공식 발효 특보");
      expect(content.tone).toBe("default");
    });

    it("모의훈련 모드에서는 시나리오 훈련 가정 안내와 simulation 톤을 적용한다", () => {
      const regionWarnings: MonitoringWarningItem[] = [
        {
          id: "sim1",
          region_code: "L1020100",
          region: "대구광역시",
          type: "태풍",
          raw_level: "경보",
          level: "CRITICAL",
        },
      ];

      const content = buildWarningCardContent(sampleFeature, regionWarnings, true);
      expect(content.eyebrow).toBe("기상특보 (모의훈련)");
      expect(content.title).toBe("대구광역시");
      expect(content.value).toBe("태풍 경보");
      expect(content.lines[0]).toContain("태풍 경보 (훈련 가정)");
      expect(content.meta[0]).toBe("모의훈련 특보 · 실제 상황이 아님");
      expect(content.tone).toBe("simulation");
    });

    it("특보 상세 목록이 없을 때는 feature.properties.label로 안전하게 fallback한다", () => {
      const content = buildWarningCardContent(sampleFeature, [], false);
      expect(content.title).toBe("대구광역시");
      expect(content.value).toBe("호우 경보 / 폭염 주의보");
      expect(content.lines).toEqual(["• 호우 경보", "• 폭염 주의보"]);
      expect(content.meta).toContain("기상청 공식 발효 특보");
    });
  });
});
