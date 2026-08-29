import { useCallback, useEffect, useState } from "react";

export interface RouteLocation {
  pathname: string;
  search: string;
}

const NAVIGATE_EVENT = "keco:navigate";

export function getCurrentLocation(): RouteLocation {
  if (typeof window === "undefined") {
    return { pathname: "/", search: "" };
  }
  return {
    pathname: window.location.pathname || "/",
    search: window.location.search || "",
  };
}

export function navigate(path: string, search = ""): void {
  if (typeof window === "undefined") return;
  const target = search ? `${path}${search.startsWith("?") ? search : `?${search}`}` : path;
  window.history.pushState({}, "", target);
  window.dispatchEvent(new CustomEvent(NAVIGATE_EVENT));
  window.scrollTo(0, 0);
}

/**
 * Navigate to `path` while preserving the current URL's `mode` query parameter.
 * Other query parameters (e.g. `facility_id`) are intentionally dropped so that
 * page-specific state does not leak between screens.
 */
export function navigateWithMode(path: string): void {
  if (typeof window === "undefined") return;
  const currentMode = new URLSearchParams(window.location.search).get("mode");
  const search = currentMode === "simulation" ? "?mode=simulation" : "";
  navigate(path, search);
}


export function useLocation(): RouteLocation {
  const [location, setLocation] = useState<RouteLocation>(getCurrentLocation);

  const update = useCallback(() => {
    setLocation(getCurrentLocation());
  }, []);

  useEffect(() => {
    window.addEventListener("popstate", update);
    window.addEventListener(NAVIGATE_EVENT, update);
    return () => {
      window.removeEventListener("popstate", update);
      window.removeEventListener(NAVIGATE_EVENT, update);
    };
  }, [update]);

  return location;
}
