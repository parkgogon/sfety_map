import { lazy, StrictMode, Suspense } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import { useLocation } from "./router";
import "../../safety_dashboard/ui/design_tokens.css";
import "./styles.css";

const ControlApp = lazy(() => import("./ControlApp"));
const SettingsApp = lazy(() => import("./SettingsApp"));

function Root() {
  const location = useLocation();
  const isControl = location.pathname === "/control" || location.pathname.startsWith("/control/");
  const isSettings = location.pathname === "/settings" || location.pathname.startsWith("/settings/");

  if (isControl) {
    return (
      <Suspense
        fallback={
          <main className="initial-state">
            <div className="brand-mark">K-ECO SAFETY MONITORING</div>
            <div className="loading-ring" aria-label="중앙관제 로드 중" />
            <strong>중앙 관제 화면을 불러오고 있습니다</strong>
          </main>
        }
      >
        <ControlApp />
      </Suspense>
    );
  }

  if (isSettings) {
    return (
      <Suspense
        fallback={
          <main className="initial-state">
            <div className="brand-mark">K-ECO SAFETY MONITORING</div>
            <div className="loading-ring" aria-label="설정 로드 중" />
            <strong>위험도 정책 설정 화면을 불러오고 있습니다</strong>
          </main>
        }
      >
        <SettingsApp />
      </Suspense>
    );
  }

  return <App />;
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <Root />
  </StrictMode>,
);

