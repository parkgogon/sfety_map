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
    expect(markup).toContain('aria-label="위험등급 범례 접기"');
    expect(markup).toContain('aria-expanded="true"');
  });

  it("모든 등급의 설명과 영향 없음 주의 문구를 제공한다", () => {
    expect(GRADE_HELP).toEqual({
      HIGH: "즉시 확인이 필요한 높은 위험",
      MEDIUM: "주의 깊은 확인이 필요한 위험",
      LOW: "특보 영향권에 포함된 관찰 대상",
      NONE: "특보의 영향권에 들지 않음",
      UNASSESSED: "기준 미등록 특보로 위험등급 판정불가",
      UNAVAILABLE: "기상청 데이터 미수신으로 위험등급 판정불가",
    });
    expect(GRADE_HELP_FOOTER).toBe("영향 없음은 절대적인 안전을 의미하지 않습니다.");
  });
});
