import { createElement } from "react";

// Static SVG markup shared by markers and the legend.
const FACILITY_ICON_PATHS: Readonly<Record<string, string>> = {
  wastewater: '<path d="M4 4v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V4"/><path d="M4 12c1.3 0 1.4-1.6 2.7-1.6S8 12 9.3 12s1.4-1.6 2.7-1.6 1.4 1.6 2.7 1.6 1.4-1.6 2.7-1.6S19 12 20 12"/>',
  air: '<path d="M12.8 19.6A2 2 0 1 0 14 16H2"/><path d="M17.5 8a2.5 2.5 0 1 1 2 4H2"/><path d="M9.8 4.4A2 2 0 1 1 11 8H2"/>',
  water: '<path d="M12 22a7 7 0 0 0 7-7c0-2-1-3.9-3-5.5s-3.5-4-4-6.5c-.5 2.5-2 4.9-4 6.5C6 11.1 5 13 5 15a7 7 0 0 0 7 7z"/>',
  site: '<path d="M10 10V5a1 1 0 0 1 1-1h2a1 1 0 0 1 1 1v5"/><path d="M14 6a6 6 0 0 1 6 6v3"/><path d="M4 15v-3a6 6 0 0 1 6-6"/><rect x="2" y="15" width="20" height="4" rx="1"/>',
  farming_collection: '<path d="M14 18V6a2 2 0 0 0-2-2H4a2 2 0 0 0-2 2v11a1 1 0 0 0 1 1h2"/><path d="M15 18H9"/><path d="M19 18h2a1 1 0 0 0 1-1v-3.65a1 1 0 0 0-.22-.62l-3.48-4.35A1 1 0 0 0 17.52 8H14"/><circle cx="17" cy="18" r="2"/><circle cx="7" cy="18" r="2"/>',
  farming_plastic: '<path d="M7 19H4.8a1.8 1.8 0 0 1-1.6-.9 1.8 1.8 0 0 1 0-1.8L7.2 9.5"/><path d="M11 19h8.2a1.8 1.8 0 0 0 1.6-.9 1.8 1.8 0 0 0 0-1.8l-1.2-2.1"/><path d="m14 16-3 3 3 3"/><path d="M8.3 13.6 7.2 9.5 3.1 10.6"/><path d="m9.3 5.8 1.1-1.9A1.8 1.8 0 0 1 12 3a1.8 1.8 0 0 1 1.5.9l3.9 6.8"/><path d="m13.4 9.6 4.1 1.1 1.1-4.1"/>',
  other: '<path d="M6 22V4a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2v18Z"/><path d="M6 12H4a2 2 0 0 0-2 2v6a2 2 0 0 0 2 2h2"/><path d="M18 9h2a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2h-2"/><path d="M10 6h4"/><path d="M10 10h4"/><path d="M10 14h4"/><path d="M10 18h4"/>',
};

export function getFacilityIconPath(groupId?: string): string {
  return groupId && Object.prototype.hasOwnProperty.call(FACILITY_ICON_PATHS, groupId)
    ? FACILITY_ICON_PATHS[groupId]
    : FACILITY_ICON_PATHS.other;
}

function escapeAttribute(value: string): string {
  return value.replace(/[&<>"']/g, (character) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&apos;",
  })[character]!);
}

export function facilityMarkerIconSvg(
  groupId: string,
  cx: number,
  cy: number,
  size: number,
  color = "white",
): string {
  return `<svg x="${cx - size / 2}" y="${cy - size / 2}" width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" color="${escapeAttribute(color)}" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">${getFacilityIconPath(groupId)}</svg>`;
}

export interface FacilityIconProps {
  groupId?: string;
  size?: number;
  className?: string;
  color?: string;
}

export function FacilityIcon({
  groupId,
  size = 16,
  className,
  color = "currentColor",
}: FacilityIconProps) {
  return createElement("svg", {
    width: size,
    height: size,
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 2.5,
    strokeLinecap: "round",
    strokeLinejoin: "round",
    color,
    className,
    "aria-hidden": true,
    focusable: "false",
    // Only the static, allowlisted paths above reach this HTML sink.
    dangerouslySetInnerHTML: { __html: getFacilityIconPath(groupId) },
  });
}
