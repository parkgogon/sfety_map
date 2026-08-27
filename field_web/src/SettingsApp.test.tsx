import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import SettingsApp from "./SettingsApp";

describe("SettingsApp", () => {
  it("renders admin login requirement view when not authenticated", () => {
    const html = renderToStaticMarkup(<SettingsApp />);
    expect(html).toContain("위험도 정책 설정");
    expect(html).toContain("관리자 인증이 필요합니다");
    expect(html).toContain("관리자 비밀번호");
  });
});
