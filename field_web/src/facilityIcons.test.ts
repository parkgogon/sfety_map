// @vitest-environment jsdom
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { FacilityIcon, facilityMarkerIconSvg, getFacilityIconPath } from "./facilityIcons";

describe("시설 공통 아이콘", () => {
  it.each([
    ["wastewater", "M4 4v14"], ["air", "M12.8 19.6"],
    ["water", "M12 22a7"], ["site", "M10 10V5"],
    ["farming_collection", "M14 18V6"], ["farming_plastic", "M7 19H4.8"],
    ["other", "M6 22V4"],
  ])("%s 그룹은 지정된 도형을 지도와 범례에서 공유한다", (groupId, pathStart) => {
    expect(getFacilityIconPath(groupId)).toContain('d="' + pathStart);
    const marker = new DOMParser().parseFromString(facilityMarkerIconSvg(groupId, 15, 15, 15), "image/svg+xml");
    const legend = new DOMParser().parseFromString(renderToStaticMarkup(createElement(FacilityIcon, { groupId })), "image/svg+xml");
    expect(marker.querySelector("parsererror")).toBeNull();
    expect(marker.documentElement.innerHTML).toBe(legend.documentElement.innerHTML);
    expect(legend.documentElement.getAttribute("aria-hidden")).toBe("true");
    expect(legend.documentElement.getAttribute("width")).toBe("16");
    expect(legend.documentElement.getAttribute("stroke")).toBe("currentColor");
  });

  it.each([undefined, "", "new_group", "constructor", "__proto__"])("알 수 없는 그룹 %s는 건물로 표시한다", (groupId) => {
    expect(getFacilityIconPath(groupId)).toBe(getFacilityIconPath("other"));
  });

  it.each([[15, 15, 7.5], [22, 22, 11]])("중심 %s에 크기 %s 아이콘을 배치한다", (center, size, origin) => {
    const svg = new DOMParser().parseFromString(facilityMarkerIconSvg("site", center, center, size), "image/svg+xml").documentElement;
    expect(svg.getAttribute("x")).toBe(String(origin));
    expect(svg.getAttribute("y")).toBe(String(origin));
    expect(svg.getAttribute("width")).toBe(String(size));
    expect(svg.getAttribute("height")).toBe(String(size));
    expect(svg.getAttribute("color")).toBe("white");
    expect(svg.getAttribute("viewBox")).toBe("0 0 24 24");
    expect(svg.getAttribute("stroke-width")).toBe("2.5");
  });
});
