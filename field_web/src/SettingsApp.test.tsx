import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import SettingsApp, { LEVEL_LABELS, PolicyMatrixEditor } from "./SettingsApp";

const WARNING_TYPES = Array.from({ length: 14 }, (_, index) => `테스트특보 ${index + 1}`);

function makePolicyMatrix() {
  return Object.fromEntries(
    WARNING_TYPES.map((warningType) => [
      warningType,
      {
        ADVISORY: "LOW",
        WARNING: "MEDIUM",
        CRITICAL: "HIGH",
      },
    ]),
  );
}

describe("SettingsApp", () => {
  it("renders admin login requirement view when not authenticated", () => {
    const html = renderToStaticMarkup(<SettingsApp />);
    expect(html).toContain("위험도 정책 설정");
    expect(html).toContain("관리자 인증이 필요합니다");
    expect(html).toContain("관리자 비밀번호");
  });

  it("renders all warning types as mobile-card-ready rows with Korean level labels", () => {
    const matrix = makePolicyMatrix();
    const html = renderToStaticMarkup(
      <PolicyMatrixEditor
        warningTypes={WARNING_TYPES}
        activeWarningTypes={new Set([WARNING_TYPES[0]])}
        editedMatrix={matrix}
        defaultMatrix={matrix}
        onCellChange={() => undefined}
      />,
    );

    expect((html.match(/class="policy-warning-row/g) || []).length).toBe(14);
    expect(html).toContain('data-label="주의보"');
    expect(html).toContain('data-label="경보"');
    expect(html).toContain('data-label="중대"');
    expect(html).toContain("● 발효 중");
    expect(html).not.toContain("(ADVISORY)");
    expect(html).not.toContain("(WARNING)");
    expect(html).not.toContain("(CRITICAL)");
  });

  it("keeps API grade values while showing Korean-only grade labels and modified state", () => {
    const defaultMatrix = makePolicyMatrix();
    const editedMatrix = makePolicyMatrix();
    editedMatrix[WARNING_TYPES[0]] = {
      ...editedMatrix[WARNING_TYPES[0]],
      ADVISORY: "HIGH",
    };

    const html = renderToStaticMarkup(
      <PolicyMatrixEditor
        warningTypes={[WARNING_TYPES[0]]}
        activeWarningTypes={new Set()}
        editedMatrix={editedMatrix}
        defaultMatrix={defaultMatrix}
        onCellChange={() => undefined}
      />,
    );

    expect(html).toContain('value="HIGH" selected=""');
    expect(html).toContain('class="col-grade-cell cell-modified"');
    expect(html).toContain('class="policy-grade-select grade-high"');
    expect(html).not.toContain("상 (HIGH)");
    expect(LEVEL_LABELS).toEqual({ ADVISORY: "주의보", WARNING: "경보", CRITICAL: "중대" });
  });
});
