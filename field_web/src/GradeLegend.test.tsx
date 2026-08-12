import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { GRADE_HELP, GRADE_HELP_FOOTER, GradeLegend } from "./GradeLegend";
import { GRADE_DISPLAY_ORDER } from "./utils";

describe("위험등급 범례", () => {
  it("정해진 화면 순서로 여섯 등급과 도움말 버튼을 렌더링한다", () => {
    const markup = renderToStaticMarkup(
      <GradeLegend selectedGrades={new Set(GRADE_DISPLAY_ORDER)} onToggle={() => undefined} />,
    );
    const labels = ["상", "중", "하", "영향 없음", "미판정", "조회 불가"];
    labels.reduce((previousIndex, label) => {
      const index = markup.indexOf(`>${label}</button>`);
      expect(index).toBeGreaterThan(previousIndex);
      return index;
    }, -1);
    expect(markup).toContain('aria-label="위험등급 설명"');
  });

  it("모든 등급의 설명과 영향 없음 주의 문구를 제공한다", () => {
    expect(GRADE_HELP).toEqual({
      HIGH: "즉시 확인이 필요한 높은 위험",
      MEDIUM: "주의 깊은 확인이 필요한 위험",
      LOW: "특보 영향권에 포함된 관찰 대상",
      NONE: "현재 활성 특보와 연결되지 않음",
      UNASSESSED: "특보는 연결됐지만 기준 미등록으로 자동 판정 불가",
      UNAVAILABLE: "KMA 자료를 받지 못해 현재 등급 판정 불가",
    });
    expect(GRADE_HELP_FOOTER).toBe("영향 없음은 절대적인 안전을 의미하지 않습니다.");
  });
});
