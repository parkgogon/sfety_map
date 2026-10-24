// @vitest-environment jsdom
import { act, useEffect, type ComponentProps } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import type { KakaoMap } from "./KakaoMap";
import { formatMobileReferenceTime } from "./MobileMapHeader";
import type { MonitoringResponse } from "./types";
import { MOBILE_MAP_QUERY } from "./useMobileLayout";

const { locationSearch } = vi.hoisted(() => ({ locationSearch: vi.fn() }));

const refresh = vi.fn(async () => {});
let mapMounts = 0;
let data: MonitoringResponse;
let refreshing = false;
let monitoringError = "";
const fixture = (): MonitoringResponse => ({
  api_version: "v1", generated_at: "2026-10-15T12:55:00+09:00",
  policy: { version: "test", temporary: false },
  status: { health: "LIVE", fetched_at: "2026-10-15T12:55:00+09:00", detail: "", zone_health: "LIVE", zone_detail: "" },
  summary: null, warnings: [], warning_zones: { type: "FeatureCollection", features: [] }, notices: [],
  groups: [{ id: "water", label: "수질측정소", count: 1 }],
  facilities: [{ id: "F-1", name: "시험 수질측정소", group_id: "water", group_label: "수질측정소", type: "수질측정소",
    latitude: 36.5, longitude: 128.7, address: "경북", public_contact: "", grade: "NONE", grade_label: "영향 없음",
    grade_color: "#176B87", meaning: "특보 영향권 밖", recommended_action: "추가 행동 없음", reasons: [] }],
});
vi.mock("./api", () => ({ useMonitoringData: () => ({ data, loading: false, refreshing, error: monitoringError, refresh }) }));
vi.mock("./contextApi", () => ({
  useFacilityWeather: () => ({ data: null, loading: false, error: "", retry: vi.fn() }),
  useFacilityCctv: () => ({ data: null, loading: false, error: "", cooldownUntil: 0, load: vi.fn() }),
}));
vi.mock("./weatherLayerApi", () => ({ useWeatherLayer: () => ({ data: null, loading: false, error: "", retry: vi.fn() }) }));
vi.mock("./locationSearch", () => ({ searchLocations: locationSearch }));
vi.mock("./KakaoMap", () => ({ KakaoMap: (props: ComponentProps<typeof KakaoMap>) => {
  useEffect(() => { mapMounts += 1; }, []);
  return <div data-testid="map" data-selected={props.selectedFacilityId} data-reference={props.referencePoint?.label ?? ""}
    data-viewport={props.viewportRequest ? `${props.viewportRequest.kind}:${props.viewportRequest.revision}` : ""}
    data-native-zoom={String(props.showZoomControl)}>
    {props.facilities[0] && <button type="button" onClick={() => props.onSelect(props.facilities[0])}>시험 시설 선택</button>}
    {props.pickingReference && <button type="button" onClick={() => props.onPickReference?.({ latitude: 36.5, longitude: 128.71 })}>시험 위치 지정</button>}
  </div>;
} }));

let root: Root;
let container: HTMLDivElement;
let mobile: boolean;
let listeners: Set<() => void>;
const render = async () => { await act(async () => root.render(<App />)); };
const byText = (text: string) => Array.from(container.querySelectorAll<HTMLButtonElement>("button")).find((b) => b.textContent?.trim() === text)!;
const byLabel = (label: string) => container.querySelector<HTMLButtonElement>(`button[aria-label="${label}"]`)!;
const click = async (button: HTMLButtonElement) => {
  expect(button).toBeTruthy();
  await act(async () => { button.focus(); button.click(); });
};
const key = async (value: string, shiftKey = false) => {
  await act(async () => { document.activeElement!.dispatchEvent(new KeyboardEvent("keydown", { key: value, shiftKey, bubbles: true, cancelable: true })); });
};
const resize = async (value: boolean) => {
  await act(async () => { mobile = value; listeners.forEach((listener) => listener()); });
};
const fill = async (input: HTMLInputElement, value: string) => {
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
};

beforeEach(() => {
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  vi.stubGlobal("scrollTo", vi.fn());
  data = fixture(); refreshing = false; monitoringError = ""; mapMounts = 0; refresh.mockClear();
  locationSearch.mockReset();
  locationSearch.mockResolvedValue({ points: [], partial: false });
  window.history.replaceState({}, "", "/");
  mobile = true; listeners = new Set();
  vi.stubGlobal("matchMedia", vi.fn((query: string) => ({
    media: query, get matches() { return query === MOBILE_MAP_QUERY && mobile; },
    addEventListener: (_event: string, callback: () => void) => { listeners.add(callback); },
    removeEventListener: (_event: string, callback: () => void) => { listeners.delete(callback); },
  })));
  container = document.createElement("div"); document.body.append(container); root = createRoot(container);
});
afterEach(async () => {
  await act(async () => root.unmount());
  expect(listeners.size).toBe(0);
  container.remove(); vi.unstubAllGlobals();
});

describe("모바일 헤더와 패널", () => {
  it("모바일 헤더를 합치고 PC 전환에도 지도와 시설 선택을 유지한다", async () => {
    window.history.replaceState({}, "", "/?facility_id=F-1");
    data.status.zone_detail = "KMA 공식 특보구역 최신본";
    await render();
    expect(container.querySelector(".mobile-map-header")?.textContent).toContain("KMA 정상");
    expect(container.querySelector(".mobile-map-header")?.textContent).not.toContain("안내");
    expect(container.querySelector(".app-header")).toBeNull();
    expect(container.querySelector(".status-line")).toBeNull();
    const map = container.querySelector('[data-testid="map"]');
    await click(byLabel("더보기"));
    await resize(false);
    expect(container.querySelector('[role="dialog"]')).toBeNull();
    expect(container.querySelector(".app-header")?.textContent).toContain("K-ECO SAFETY MONITORING");
    expect(container.querySelector(".status-line")?.textContent).toContain("KMA 정상");
    expect(container.querySelector('[data-testid="map"]')).toBe(map);
    expect(map?.getAttribute("data-selected")).toBe("F-1");
    expect(map?.getAttribute("data-native-zoom")).toBe("true");
    expect(map?.closest("main")?.hasAttribute("inert")).toBe(false);
    await resize(true);
    expect(container.querySelector(".mobile-map-header")).not.toBeNull();
    expect(container.querySelector('[data-testid="map"]')).toBe(map);
    expect(mapMounts).toBe(1);
    expect(map?.getAttribute("data-native-zoom")).toBe("false");
    expect(window.location.search).toBe("?facility_id=F-1");
  });

  it.each([
    ["LIVE", "KMA 정상", ""],
    ["STALE", "KMA 수신 지연", "수신 지연 · 마지막 정상 자료 표시 중"],
    ["ERROR", "KMA 조회 불가", "특보 조회 불가 · 시설 위치만 확인 가능"],
    ["FALLBACK", "KMA 조회 불가", "특보 조회 불가 · 시설 위치만 확인 가능"],
    ["SIMULATION", "모의훈련 · 실제 상황 아님", ""],
  ] as const)("%s의 수신 상태는 상태 패널을 닫아도 남는다", async (health, label, notice) => {
    data.status.health = health;
    if (health === "SIMULATION") window.history.replaceState({}, "", "/?mode=simulation");
    await render();
    expect(container.querySelector(".mobile-map-header")?.textContent).toContain(label);
    if (notice) expect(container.querySelector(".mobile-data-notice")?.textContent).toContain(notice);
    else expect(container.querySelector(".mobile-data-notice")).toBeNull();
    await click(container.querySelector<HTMLButtonElement>(".mobile-status-button")!);
    expect(container.querySelector('[role="dialog"]')?.textContent).toContain("2026.10.15 12:55 (KST)");
    if (health === "STALE") expect(container.querySelector('[role="dialog"]')?.textContent).toContain("마지막 정상 자료 기준");
    await key("Escape");
    expect(container.querySelector('[role="dialog"]')).toBeNull();
    expect(container.querySelector(".mobile-map-header")?.textContent).toContain(label);
    if (notice) expect(container.querySelector(".mobile-data-notice")?.textContent).toContain(notice);
  });

  it("Escape는 현재 패널만 닫고 포커스와 선택 시설을 복원한다", async () => {
    window.history.replaceState({}, "", "/?facility_id=F-1");
    await render();
    const trigger = byLabel("더보기");
    await click(trigger);
    const dialog = container.querySelector('[role="dialog"]')!;
    expect(container.querySelectorAll('[role="dialog"]')).toHaveLength(1);
    expect(container.querySelector("main")?.hasAttribute("inert")).toBe(true);
    const buttons = Array.from(dialog.querySelectorAll<HTMLElement>("button, a"));
    expect(document.activeElement).toBe(buttons[0]);
    await key("Tab", true);
    expect(document.activeElement).toBe(buttons.at(-1));
    await key("Tab");
    expect(document.activeElement).toBe(buttons[0]);
    byText("시험 시설 선택").focus();
    expect(dialog.contains(document.activeElement)).toBe(true);
    await key("Escape");
    expect(container.querySelector('[role="dialog"]')).toBeNull();
    expect(document.activeElement).toBe(trigger);
    expect(container.querySelector("main")?.hasAttribute("inert")).toBe(false);
    expect(window.location.search).toBe("?facility_id=F-1");
    expect(container.querySelector('[data-testid="map"]')?.getAttribute("data-selected")).toBe("F-1");
    expect(mapMounts).toBe(1);
  });

  it("경계 대체·조회 오류·잘못된 딥링크의 안내를 상태 패널에 유지한다", async () => {
    data.status.zone_health = "FALLBACK";
    data.status.zone_detail = "검증된 경계 자료 사용";
    monitoringError = "자료 갱신을 완료하지 못했습니다.";
    window.history.replaceState({}, "", "/?facility_id=missing");
    await render();
    expect(container.querySelector(".mobile-map-header")?.textContent).toContain("안내");
    expect(container.querySelector(".notice-stack")?.textContent).toContain("요청한 시설을 찾을 수 없어");
    await click(container.querySelector<HTMLButtonElement>(".mobile-status-button")!);
    const text = container.querySelector('[role="dialog"]')?.textContent;
    expect(text).toContain("검증된 내장 경계를 사용 중");
    expect(text).toContain("검증된 경계 자료 사용");
    expect(text).toContain(monitoringError);
    expect(text).toContain("요청한 시설을 찾을 수 없어");
  });

  it("더보기는 기존 갱신을 호출하고 갱신 중 중복 실행을 막는다", async () => {
    await render(); await click(byLabel("더보기"));
    await click(byText("관제 자료 새로고침"));
    expect(refresh).toHaveBeenCalledTimes(1);
    refreshing = true; await render();
    expect(byText("관제 자료 갱신 중…").disabled).toBe(true);
    await act(async () => byText("관제 자료 갱신 중…").click());
    expect(refresh).toHaveBeenCalledTimes(1);
    const official = container.querySelector<HTMLAnchorElement>('[role="dialog"] a')!;
    expect(official.href).toBe("https://www.weather.go.kr/w/special-report/overall.do");
    expect(official.target).toBe("_blank"); expect(official.rel).toBe("noreferrer");
  });

  it("모의훈련은 모바일 필터에서 더보기로 옮기고 모드와 관제 이동을 유지한다", async () => {
    await render();
    await click(container.querySelector<HTMLButtonElement>(".mobile-map-settings-trigger")!);
    expect(container.querySelector('[role="dialog"]')?.textContent).not.toContain("모의훈련 화면 보기");
    await click(byLabel("지도 설정 닫기")); await click(byLabel("더보기"));
    await click(byText("모의훈련 화면 보기"));
    expect(window.location.search).toContain("mode=simulation");
    expect(container.querySelector('[role="dialog"]')).toBeNull();
    expect(container.querySelector(".mobile-map-header")?.textContent).toContain("실제 상황 아님");
    expect(container.querySelector(".simulation-banner")?.textContent).toContain("실시간으로 돌아가기");
    await click(byLabel("더보기")); await click(byText("실시간 화면으로 돌아가기"));
    expect(window.location.search).not.toContain("mode=simulation");
    await click(byLabel("더보기")); await click(byText("모의훈련 화면 보기"));
    await click(byLabel("더보기")); await click(byText("중앙관제 열기"));
    expect(window.location.pathname).toBe("/control");
    expect(window.location.search).toBe("?mode=simulation");
  });

  it("시설·기상·읽기 전용 범례를 한 지도 설정 패널에서 전환한다", async () => {
    await render();
    expect(container.querySelector(".grade-legend")).toBeNull();
    expect(container.querySelector(".filter-button")).toBeNull();
    expect(container.querySelector(".weather-map-button")).toBeNull();
    await click(container.querySelector<HTMLButtonElement>(".mobile-map-settings-trigger")!);
    const dialog = container.querySelector('[role="dialog"]')!;
    expect(dialog.querySelectorAll('[role="tab"]')).toHaveLength(3);
    expect(dialog.textContent).toContain("현재 1개 / 전체 1개 표시");

    const groupCheckbox = dialog.querySelector<HTMLInputElement>('.group-options input[type="checkbox"]')!;
    await act(async () => groupCheckbox.click());
    expect(dialog.textContent).toContain("표시할 시설이 없습니다.");
    expect(dialog.textContent).toContain("현재 0개 / 전체 1개 표시");
    await click(byText("전체 시설 복구"));
    expect(groupCheckbox.checked).toBe(true);

    await click(byText("기상"));
    await click(byLabel("바람 기상 레이어"));
    expect(container.querySelector('[role="dialog"]')).toBe(dialog);
    expect(byLabel("바람 기상 레이어 선택됨").getAttribute("aria-pressed")).toBe("true");

    await click(byText("범례"));
    expect(dialog.querySelectorAll("input")).toHaveLength(0);
    expect(dialog.textContent).toContain("시설 마커 위험등급");
    expect(dialog.textContent).toContain("특보 발효 구역");
    await click(byLabel("지도 설정 닫기"));
    expect(container.querySelector('[role="dialog"]')).toBeNull();
    expect(container.querySelector(".mobile-map-settings-trigger")?.textContent).toContain("바람");
    expect(document.activeElement).toBe(container.querySelector(".mobile-map-settings-trigger"));
  });

  it("자료 갱신 후 해제한 기존 유형은 유지하고 새 유형만 선택한다", async () => {
    data = {
      ...data,
      groups: [
        { id: "water", label: "수질측정소", count: 1 },
        { id: "air", label: "대기측정소", count: 0 },
      ],
    };
    await render();
    await click(container.querySelector<HTMLButtonElement>(".mobile-map-settings-trigger")!);
    const checkboxFor = (label: string) => Array.from(container.querySelectorAll<HTMLLabelElement>(".group-options label"))
      .find((item) => item.textContent?.includes(label))!.querySelector<HTMLInputElement>("input")!;
    await act(async () => checkboxFor("대기측정소").click());
    expect(checkboxFor("대기측정소").checked).toBe(false);

    data = {
      ...data,
      groups: [
        { id: "water", label: "수질측정소", count: 1 },
        { id: "air", label: "대기측정소", count: 0 },
        { id: "site", label: "시설현장", count: 0 },
      ],
    };
    await render();
    expect(checkboxFor("대기측정소").checked).toBe(false);
    expect(checkboxFor("시설현장").checked).toBe(true);

    data = { ...data, groups: data.groups.filter((group) => group.id !== "water") };
    await render();
    expect(container.querySelectorAll(".group-options label")).toHaveLength(2);
    expect(checkboxFor("대기측정소").checked).toBe(false);
    expect(checkboxFor("시설현장").checked).toBe(true);
  });

  it("직접 지정 후보를 확인한 뒤 주변 시설로 이어지고 일반 패널을 닫아도 기준점을 유지한다", async () => {
    await render();
    expect(container.querySelector(".empty-sheet")).toBeNull();
    expect(container.querySelector(".location-search-modes")).toBeNull();
    await click(byLabel("시설·장소·주소 검색"));
    await click(byText("장소·주소"));
    await click(byText("지도에서 지정"));
    await click(byText("시험 위치 지정"));
    expect(container.querySelector(".mobile-candidate-panel")).not.toBeNull();
    await click(byText("이곳으로 지정"));
    const map = container.querySelector('[data-testid="map"]');
    expect(map?.getAttribute("data-reference")).toBe("사고 확인 지점");
    expect(container.querySelector('[role="dialog"]')?.textContent).toContain("주변 시설");
    await click(byLabel("주변 시설 닫기"));
    await click(byLabel("더보기")); await key("Escape");
    expect(container.querySelector('[role="dialog"]')).toBeNull();
    expect(map?.getAttribute("data-reference")).toBe("사고 확인 지점");
    await click(byText("주변 시설")); await click(byText("이름·위치 수정"));
    expect(container.querySelector(".mobile-candidate-panel")).not.toBeNull();
    await click(byLabel("더보기"));
    expect(container.querySelector(".mobile-candidate-panel")).toBeNull();
    await key("Escape");
    expect(map?.getAttribute("data-reference")).toBe("사고 확인 지점");
  });

  it("전체 시설 검색은 숨은 필터를 복구하고 접힌 시설 요약으로 전환한다", async () => {
    await render();
    await click(container.querySelector<HTMLButtonElement>(".mobile-map-settings-trigger")!);
    const group = container.querySelector<HTMLInputElement>('.group-options input[type="checkbox"]')!;
    await act(async () => group.click());
    await click(byLabel("지도 설정 닫기"));
    expect(container.querySelector('[data-testid="map"] button')).toBeNull();

    await click(byLabel("시설·장소·주소 검색"));
    const input = container.querySelector<HTMLInputElement>('input[aria-label="시설명 또는 주소 검색"]')!;
    await fill(input, "시험 수질");
    await click(container.querySelector<HTMLButtonElement>(".mobile-search-results button")!);
    expect(container.querySelector(".facility-sheet.mobile-compact")).not.toBeNull();
    expect(container.querySelector(".weather-context")).toBeNull();
    expect(container.querySelector('[data-testid="map"] button')).not.toBeNull();
    expect(window.location.search).toBe("?facility_id=F-1");
    await click(byText("자세히 보기⌃"));
    expect(container.querySelector(".weather-context")).not.toBeNull();
    await click(byText("간단히 보기⌄"));
    expect(container.querySelector(".weather-context")).toBeNull();
  });

  it("닫힌 장소 검색의 늦은 응답은 패널이나 후보를 다시 열지 않는다", async () => {
    let resolveSearch!: (value: { points: Array<{ latitude: number; longitude: number; label: string; address: string; source: "place" }>; partial: boolean }) => void;
    locationSearch.mockReturnValue(new Promise((resolve) => { resolveSearch = resolve; }));
    await render();
    await click(byLabel("시설·장소·주소 검색"));
    await click(byText("장소·주소"));
    const input = container.querySelector<HTMLInputElement>('input[aria-label="장소명 또는 주소"]')!;
    await fill(input, "온산공단");
    await click(byText("검색"));
    await click(byLabel("검색 닫기"));
    await act(async () => resolveSearch({ points: [{ latitude: 35.4, longitude: 129.3, label: "온산공단", address: "울산", source: "place" }], partial: false }));
    expect(container.querySelector('[role="dialog"]')).toBeNull();
    expect(container.querySelector(".mobile-candidate-panel")).toBeNull();
  });

  it("전체 시설과 모바일 확대·축소는 기준점·기상 선택을 보존하며 명시적인 지도 요청만 보낸다", async () => {
    await render();
    const map = container.querySelector<HTMLElement>('[data-testid="map"]')!;
    expect(map.getAttribute("data-native-zoom")).toBe("false");
    expect(container.querySelectorAll(".mobile-map-zoom-controls button")).toHaveLength(2);

    await click(byLabel("시설·장소·주소 검색"));
    await click(byText("장소·주소"));
    await click(byText("지도에서 지정"));
    await click(byText("시험 위치 지정"));
    await click(byText("이곳으로 지정"));
    await click(byLabel("주변 시설 닫기"));

    await click(container.querySelector<HTMLButtonElement>(".mobile-map-settings-trigger")!);
    const group = container.querySelector<HTMLInputElement>('.group-options input[type="checkbox"]')!;
    await act(async () => group.click());
    await click(byText("기상"));
    await click(byLabel("바람 기상 레이어"));
    await click(byLabel("지도 설정 닫기"));
    expect(container.querySelector('[data-testid="map"] button')).toBeNull();

    await click(byLabel("지도 확대"));
    expect(map.getAttribute("data-viewport")).toMatch(/^zoom-in:/);
    await click(byLabel("지도 축소"));
    expect(map.getAttribute("data-viewport")).toMatch(/^zoom-out:/);
    await click(byText("전체 시설"));
    expect(map.getAttribute("data-viewport")).toMatch(/^fit-facilities:/);
    expect(map.getAttribute("data-reference")).toBe("사고 확인 지점");
    expect(container.querySelector('[data-testid="map"] button')).not.toBeNull();
    expect(container.querySelector(".mobile-map-settings-trigger")?.textContent).toContain("바람");
  });
});

describe("모바일 기준 시각", () => {
  it("KST 오늘은 시각만, 다른 날과 전체 보기에는 날짜를 표시한다", () => {
    const now = new Date("2026-10-15T23:30:00Z"); // Oct 16 in KST.
    expect(formatMobileReferenceTime("2026-10-16T00:05:00+09:00", false, now)).toBe("00:05");
    expect(formatMobileReferenceTime("2026-10-15T23:55:00+09:00", false, now)).toBe("10.15 23:55");
    expect(formatMobileReferenceTime("2026-10-15T23:55:00+09:00", true, now)).toBe("2026.10.15 23:55 (KST)");
  });
  it("유효하지 않은 시각을 정상 시각처럼 표시하지 않는다", () => {
    expect(formatMobileReferenceTime("invalid")).toBe("시각 미확인");
  });
});
