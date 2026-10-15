import { useSyncExternalStore } from "react";

export const MOBILE_MAP_QUERY = "(max-width: 700px)";

function subscribe(onChange: () => void) {
  if (typeof window === "undefined" || !window.matchMedia) return () => {};
  const query = window.matchMedia(MOBILE_MAP_QUERY);
  query.addEventListener("change", onChange);
  return () => query.removeEventListener("change", onChange);
}

export function useMobileLayout(): boolean {
  return useSyncExternalStore(
    subscribe,
    () => typeof window !== "undefined" && !!window.matchMedia?.(MOBILE_MAP_QUERY).matches,
    () => false,
  );
}

export type MobilePanel = "none" | "search" | "map-settings" | "status" | "more"
  | "nearby" | "same-location" | "facility";
export type MobileSettingsTab = "facilities" | "weather" | "legend";
export type MobileSearchTab = "facilities" | "location";
