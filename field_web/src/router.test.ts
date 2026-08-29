// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { navigate, navigateWithMode } from "./router";

describe("router", () => {
  const pushState = vi.spyOn(window.history, "pushState").mockImplementation(() => undefined);

  afterEach(() => {
    pushState.mockClear();
    // Reset URL to default
    window.history.replaceState({}, "", "/");
  });

  it("navigate는 주어진 경로와 검색 파라미터로 이동한다", () => {
    navigate("/control", "?mode=simulation");
    expect(pushState).toHaveBeenCalledWith({}, "", "/control?mode=simulation");
  });

  it("navigateWithMode는 mode=simulation을 보존한다", () => {
    window.history.replaceState({}, "", "/?mode=simulation&facility_id=F-1");
    navigateWithMode("/control");
    expect(pushState).toHaveBeenCalledWith({}, "", "/control?mode=simulation");
  });

  it("navigateWithMode는 live 모드에서 mode 쿼리를 추가하지 않는다", () => {
    window.history.replaceState({}, "", "/?facility_id=F-1");
    navigateWithMode("/control");
    expect(pushState).toHaveBeenCalledWith({}, "", "/control");
  });

  it("navigateWithMode는 mode=live일 때 쿼리를 추가하지 않는다", () => {
    window.history.replaceState({}, "", "/?mode=live");
    navigateWithMode("/settings");
    expect(pushState).toHaveBeenCalledWith({}, "", "/settings");
  });

  it("navigateWithMode는 facility_id 등 다른 쿼리를 넘기지 않는다", () => {
    window.history.replaceState({}, "", "/?mode=simulation&facility_id=F-1&other=val");
    navigateWithMode("/");
    expect(pushState).toHaveBeenCalledWith({}, "", "/?mode=simulation");
  });
});
