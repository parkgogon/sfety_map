import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import ControlApp from "./ControlApp";
import SettingsApp from "./SettingsApp";
import { useLocation } from "./router";
import "../../safety_dashboard/ui/design_tokens.css";
import "./styles.css";

function Root() {
  const location = useLocation();
  const isControl = location.pathname === "/control" || location.pathname.startsWith("/control/");
  const isSettings = location.pathname === "/settings" || location.pathname.startsWith("/settings/");

  if (isControl) {
    return <ControlApp />;
  }

  if (isSettings) {
    return <SettingsApp />;
  }

  return <App />;
}


createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <Root />
  </StrictMode>,
);

