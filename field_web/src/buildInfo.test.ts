import { describe, expect, it } from "vitest";
import {
  formatBuildLabel,
  formatBuildTime,
  formatShortSha,
  getBuildLabel,
} from "./buildInfo";

describe("buildInfo 단위 테스트", () => {
  describe("formatShortSha", () => {
    it("40자리 Git SHA의 앞 7자리를 정상 추출한다", () => {
      expect(formatShortSha("1bc1c03abcdef1234567890abcdef1234567890")).toBe("1bc1c03");
    });

    it("7자리 이하의 문자열은 그대로 반환한다", () => {
      expect(formatShortSha("a34bbda")).toBe("a34bbda");
      expect(formatShortSha("abc")).toBe("abc");
    });

    it("null, undefined, 공백 문자열은 빈 문자열을 반환한다", () => {
      expect(formatShortSha(null)).toBe("");
      expect(formatShortSha(undefined)).toBe("");
      expect(formatShortSha("   ")).toBe("");
    });
  });

  describe("formatBuildTime", () => {
    it("UTC ISO 날짜 문자열을 KST(UTC+9) 기준 'MM.DD HH:mm' 포맷으로 정상 변환한다", () => {
      const formatted = formatBuildTime("2026-08-30T02:00:00Z");
      expect(formatted).toBe("08.30 11:00");
    });

    it("null, undefined, 잘못된 날짜 문자열은 빈 문자열을 반환한다", () => {
      expect(formatBuildTime(null)).toBe("");
      expect(formatBuildTime(undefined)).toBe("");
      expect(formatBuildTime("invalid-time")).toBe("");
    });
  });

  describe("formatBuildLabel", () => {
    it("SHA와 빌드 시각이 모두 제공되면 'v{sha} · {time} 배포' 형태로 반환한다", () => {
      const label = formatBuildLabel("1bc1c03abcdef", "2026-08-30T11:00:00+09:00");
      expect(label).toBe("v1bc1c03 · 08.30 11:00 배포");
    });

    it("SHA만 제공되면 'v{sha}' 형태로 반환한다", () => {
      expect(formatBuildLabel("a34bbda")).toBe("va34bbda");
    });

    it("빌드 시각만 제공되면 '{time} 배포' 형태로 반환한다", () => {
      expect(formatBuildLabel("", "2026-08-30T11:00:00+09:00")).toBe("08.30 11:00 배포");
    });

    it("모두 누락되면 '개발 빌드'로 안전하게 fallback한다", () => {
      expect(formatBuildLabel(null, null)).toBe("개발 빌드");
      expect(formatBuildLabel("", "")).toBe("개발 빌드");
      expect(formatBuildLabel(undefined, undefined)).toBe("개발 빌드");
    });
  });

  describe("getBuildLabel", () => {
    it("현재 환경변수를 기반으로 유효한 빌드 레이블 문자열을 반환한다", () => {
      const label = getBuildLabel();
      expect(typeof label).toBe("string");
      expect(label.length).toBeGreaterThan(0);
    });
  });
});
