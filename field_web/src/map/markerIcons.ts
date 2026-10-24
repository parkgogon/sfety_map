import type { KakaoSDK } from "../kakaoTypes";

import { facilityMarkerIconSvg } from "../facilityIcons";

import { facilityMarkerSize } from "../mapVisuals";
import type { Facility, NearbyCctv, RiskGrade } from "../types";
import { GRADE_PRIORITY_ORDER } from "../utils";

export const GRADE_RANK = new Map<RiskGrade, number>(
  GRADE_PRIORITY_ORDER.map((grade, index) => [
    grade,
    GRADE_PRIORITY_ORDER.length - index,
  ]),
);

export function strongest(facilities: Facility[]): Facility {
  return [...facilities].sort(
    (left, right) =>
      (GRADE_RANK.get(right.grade) ?? 0) - (GRADE_RANK.get(left.grade) ?? 0),
  )[0];
}

export function markerImage(
  kakao: KakaoSDK,
  facilities: Facility[],
  selected: boolean,
): object {
  const primary = strongest(facilities);
  const size = facilityMarkerSize(facilities.length, selected);
  const radius = size / 2 - 3;
  const content =
    facilities.length > 1
      ? `<text x="50%" y="54%" dominant-baseline="middle" text-anchor="middle"
        font-family="Arial,sans-serif" font-size="${size < 38 ? 10 : 12}" font-weight="700"
        fill="white">${facilities.length}</text>`
      : facilityMarkerIconSvg(
          primary.group_id,
          size / 2,
          size / 2,
          selected ? 22 : 15,
        );
  const svg = `
    <svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}">
      <circle cx="${size / 2}" cy="${size / 2}" r="${radius + (selected ? 1 : 0)}"
        fill="white" stroke="${selected ? "#142746" : "rgba(20,39,70,.18)"}"
        stroke-width="${selected ? 4 : 1.5}"/>
      <circle cx="${size / 2}" cy="${size / 2}" r="${Math.max(7, radius - 4)}"
        fill="${primary.grade_color}"/>
      ${content}
    </svg>`;
  const url = `data:image/svg+xml;charset=UTF-8,${encodeURIComponent(svg)}`;
  return new kakao.maps.MarkerImage(url, new kakao.maps.Size(size, size), {
    offset: new kakao.maps.Point(size / 2, size / 2),
  });
}

export function coordinateGroups(facilities: Facility[]): Facility[][] {
  const groups = new Map<string, Facility[]>();
  facilities.forEach((facility) => {
    const key = `${facility.latitude.toFixed(7)}:${facility.longitude.toFixed(7)}`;
    groups.set(key, [...(groups.get(key) ?? []), facility]);
  });
  return [...groups.values()];
}

export function cctvMarkerImage(
  kakao: KakaoSDK,
  cctv: NearbyCctv,
  selected: boolean,
): object {
  const size = selected ? 50 : 44;
  const center = size / 2;
  const bearing = cctv.bearing_deg;
  const arrow =
    bearing === null
      ? ""
      : `
    <path d="M ${center} 2 L ${center - 4.5} 12 L ${center + 4.5} 12 Z"
      fill="#0f766e" stroke="white" stroke-width="1.5"
      transform="rotate(${bearing} ${center} ${center})"/>`;
  const svg = `
    <svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}">
      ${arrow}
      <circle cx="${center}" cy="${center}" r="15" fill="white"
        stroke="${selected ? "#142746" : "rgba(20,39,70,.22)"}"
        stroke-width="${selected ? 3 : 1.5}"/>
      <rect x="${center - 9}" y="${center - 6}" width="14" height="12" rx="2.5"
        fill="#142746"/>
      <path d="M ${center + 5} ${center - 3} L ${center + 11} ${center - 7}
        L ${center + 11} ${center + 7} L ${center + 5} ${center + 3} Z" fill="#142746"/>
      <circle cx="${center - 3}" cy="${center}" r="2.5" fill="#7dd3fc"/>
    </svg>`;
  return new kakao.maps.MarkerImage(
    `data:image/svg+xml;charset=UTF-8,${encodeURIComponent(svg)}`,
    new kakao.maps.Size(size, size),
    { offset: new kakao.maps.Point(center, center) },
  );
}
