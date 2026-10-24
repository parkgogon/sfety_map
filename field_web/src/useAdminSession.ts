import { useEffect, useState, type FormEvent } from "react";
import {
  checkAdminSession,
  getStoredAdminToken,
  logoutAdmin,
  setStoredAdminToken,
  verifyAdminPassword,
} from "./controlApi";

export function useAdminSession(onAuthenticated?: () => void) {
  const [adminToken, setAdminToken] = useState<string>(getStoredAdminToken);
  const [passwordInput, setPasswordInput] = useState("");
  const [authError, setAuthError] = useState<string | null>(null);
  const [authLoading, setAuthLoading] = useState(false);

  useEffect(() => {
    let active = true;
    void checkAdminSession(adminToken).then((status) => {
      if (!active) return;
      if (status.authenticated && !adminToken) setAdminToken("active-session");
      else if (!status.authenticated && adminToken) {
        setAdminToken("");
        setStoredAdminToken("");
      }
    });
    return () => {
      active = false;
    };
  }, [adminToken]);

  const handleLogin = async (event: FormEvent) => {
    event.preventDefault();
    if (!passwordInput.trim()) return;
    setAuthLoading(true);
    setAuthError(null);
    try {
      const token = await verifyAdminPassword(passwordInput.trim());
      setAdminToken(token);
      setPasswordInput("");
      onAuthenticated?.();
    } catch (error) {
      setAuthError(error instanceof Error ? error.message : "인증 실패");
    } finally {
      setAuthLoading(false);
    }
  };

  const handleLogout = () => {
    void logoutAdmin();
    setAdminToken("");
  };

  return {
    adminToken,
    passwordInput,
    setPasswordInput,
    authError,
    authLoading,
    handleLogin,
    handleLogout,
  };
}
