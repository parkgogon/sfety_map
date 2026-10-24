// @vitest-environment jsdom
import { act, type FormEvent } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  checkAdminSession,
  getStoredAdminToken,
  logoutAdmin,
  setStoredAdminToken,
  verifyAdminPassword,
} from "./controlApi";
import { useAdminSession } from "./useAdminSession";

vi.mock("./controlApi", () => ({
  checkAdminSession: vi.fn(),
  getStoredAdminToken: vi.fn(),
  logoutAdmin: vi.fn().mockResolvedValue(undefined),
  setStoredAdminToken: vi.fn(),
  verifyAdminPassword: vi.fn(),
}));

describe("관리자 공통 세션", () => {
  let root: Root;
  let container: HTMLDivElement;
  let session: ReturnType<typeof useAdminSession>;
  const onAuthenticated = vi.fn();
  function Probe() {
    session = useAdminSession(onAuthenticated);
    return <output>{session.adminToken}</output>;
  }
  async function render() {
    await act(async () => root.render(<Probe />));
  }
  async function login(password: string) {
    await act(async () => session.setPasswordInput(password));
    await act(async () =>
      session.handleLogin({ preventDefault() {} } as FormEvent),
    );
  }

  beforeEach(() => {
    vi.clearAllMocks();
    vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
    vi.mocked(getStoredAdminToken).mockReturnValue("");
    vi.mocked(checkAdminSession).mockImplementation(async (token) => ({
      authenticated: Boolean(token),
    }));
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);
  });
  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
    vi.unstubAllGlobals();
  });

  it("유효한 쿠키 세션을 비밀번호 없이 복원한다", async () => {
    vi.mocked(checkAdminSession).mockResolvedValue({ authenticated: true });
    await render();
    expect(session.adminToken).toBe("active-session");
    expect(verifyAdminPassword).not.toHaveBeenCalled();
    expect(setStoredAdminToken).not.toHaveBeenCalled();
  });

  it("로그인 성공 시 서명 토큰을 사용하고 입력값과 대기 상태를 정리한다", async () => {
    vi.mocked(verifyAdminPassword).mockResolvedValue("signed-test-session");
    await render();
    await login(" test-password ");
    expect(verifyAdminPassword).toHaveBeenCalledWith("test-password");
    expect(session.adminToken).toBe("signed-test-session");
    expect(session.passwordInput).toBe("");
    expect(session.authLoading).toBe(false);
    expect(onAuthenticated).toHaveBeenCalledOnce();
  });

  it("로그인 실패 메시지를 표시하고 인증 성공 콜백을 실행하지 않는다", async () => {
    vi.mocked(verifyAdminPassword).mockRejectedValue(new Error("인증 실패"));
    await render();
    await login("wrong");
    expect(session.adminToken).toBe("");
    expect(session.authError).toBe("인증 실패");
    expect(session.authLoading).toBe(false);
    expect(onAuthenticated).not.toHaveBeenCalled();
  });

  it("만료된 저장 토큰을 화면과 저장소에서 지운다", async () => {
    vi.mocked(getStoredAdminToken).mockReturnValue("expired-token");
    vi.mocked(checkAdminSession).mockResolvedValue({ authenticated: false });
    await render();
    expect(session.adminToken).toBe("");
    expect(setStoredAdminToken).toHaveBeenCalledWith("");
  });

  it("로그아웃 후 인증 상태를 비운다", async () => {
    vi.mocked(getStoredAdminToken).mockReturnValue("signed-test-session");
    await render();
    await act(async () => session.handleLogout());
    expect(logoutAdmin).toHaveBeenCalledOnce();
    expect(session.adminToken).toBe("");
  });
});
