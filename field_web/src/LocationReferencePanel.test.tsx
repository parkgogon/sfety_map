// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { LocationReferencePanel } from "./LocationReferencePanel";
import { useLocationReference, type LocationReferenceState } from "./useLocationReference";
import { searchLocations, type LocationSearchResult } from "./locationSearch";
import type { Facility } from "./types";

vi.mock("./locationSearch", () => ({ searchLocations: vi.fn() }));
const point = { latitude: 35.4, longitude: 129.3, label: "시험 공장", address: "울산 시험 주소", source: "place" as const };
const facilities = [
  { id: "near", name: "가까운 시설", group_id: "water", group_label: "수질측정소", latitude: 35.401, longitude: 129.3 },
  { id: "far", name: "먼 시설", group_id: "air", group_label: "대기측정소", latitude: 36, longitude: 129.3 },
] as Facility[];

describe("장소·주소와 주변 시설 패널", () => {
  let container: HTMLDivElement;
  let root: Root;
  let state: LocationReferenceState;
  const onSelect = vi.fn();
  function Harness() {
    state = useLocationReference();
    return <LocationReferencePanel reference={state} facilities={facilities}
      visibleFacilityIds={new Set(["far"])} onSelectFacility={(facility) => {
        onSelect(facility);
        state.selectNearby(facility);
      }} />;
  }
  beforeEach(async () => {
    vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
    vi.clearAllMocks();
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);
    await act(async () => root.render(<Harness />));
  });
  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
    vi.unstubAllGlobals();
  });
  async function click(text: string) {
    const button = Array.from(container.querySelectorAll("button")).find((button) => button.textContent === text);
    expect(button, text).toBeTruthy();
    await act(async () => button!.click());
  }
  async function fill(value: string) {
    const input = container.querySelector<HTMLInputElement>('[aria-label="장소명 또는 주소"]')!;
    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(input, value);
      input.dispatchEvent(new Event("input", { bubbles: true }));
    });
  }
  async function searchFor(query = "공장") { await fill(query); await click("검색"); }

  it("검색 결과 확인 후에만 기준점을 확정하며 전체 시설을 거리순으로 표시한다", async () => {
    vi.mocked(searchLocations).mockResolvedValue({ points: [point], partial: false });
    await searchFor();
    await act(async () => container.querySelector<HTMLButtonElement>(".location-results button")!.click());
    expect(state.point).toBeNull();
    expect(state.candidate).toEqual(point);
    expect(state.view?.points).toEqual([point]);
    expect(container.textContent).toContain("대표 위치일 수 있습니다");
    const confirm = container.querySelector(".location-candidate-actions")!;
    expect(confirm.textContent).toContain("이곳을 기준점으로 지정");
    expect(confirm.closest(".location-panel-body")).toBeNull();
    await click("이곳을 기준점으로 지정");
    expect(state.point).toEqual(point);
    expect(state.candidate).toBeNull();
    expect(container.textContent).toContain("5km 이내 1개소");
    expect(container.textContent).toContain("필터로 숨김 — 선택하면 표시");
    const rows = container.querySelectorAll<HTMLButtonElement>(".location-nearby-list button");
    expect(rows[0].textContent).toContain("가까운 시설");
    expect(rows[1].textContent).toContain("먼 시설");
    await act(async () => rows[0].click());
    expect(onSelect).toHaveBeenCalledWith(facilities[0]);
    expect(state.targetId).toBe("near");
    expect(state.view?.points).toEqual([point, facilities[0]]);
    expect(container.querySelector(".location-panel-body")).toBeNull();
    await click("주변 시설·검색 펼치기");
    await click("기준점 지우기");
    expect(state.point).toBeNull();
    expect(state.targetId).toBe("");
    expect(state.view).toBeNull();
  });

  it("수동 지정·취소와 Escape, 거리 원 토글을 지원한다", async () => {
    await click("지도에서 지정");
    expect(state.picking).toBe(true);
    await act(async () => window.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" })));
    expect(state.picking).toBe(false);
    await click("지도에서 지정");
    await act(async () => state.pick(point));
    expect(state.candidate?.source).toBe("map");
    expect(state.view).toBeNull();
    await click("이곳을 기준점으로 지정");
    await act(async () => container.querySelector<HTMLInputElement>(".location-rings-toggle input")!.click());
    expect(state.showRings).toBe(false);
    await click("지도에서 위치 수정");
    await act(async () => state.pick({ latitude: 36, longitude: 129 }));
    await click("취소");
    expect(state.point?.latitude).toBe(35.4);
    expect(state.candidate).toBeNull();
  });

  it("늦게 돌아온 이전 검색이 최신 결과를 덮어쓰지 않는다", async () => {
    let resolveOld!: (result: LocationSearchResult) => void;
    vi.mocked(searchLocations).mockImplementationOnce(() => new Promise((resolve) => { resolveOld = resolve; }))
      .mockResolvedValueOnce({ points: [{ ...point, label: "새 검색" }], partial: false });
    await searchFor("이전");
    await searchFor("새 검색");
    await act(async () => resolveOld({ points: [{ ...point, label: "이전 결과" }], partial: false }));
    expect(container.querySelector(".location-results")?.textContent).toContain("새 검색");
    expect(container.querySelector(".location-results")?.textContent).not.toContain("이전 결과");
  });

  it("검색 실패 뒤에도 수동 위치 지정을 사용할 수 있다", async () => {
    vi.mocked(searchLocations).mockRejectedValue(new Error("provider error"));
    await searchFor();
    expect(container.textContent).toContain("장소 검색을 완료하지 못했습니다");
    expect(container.textContent).not.toContain("provider error");
    await click("지도에서 지정");
    expect(state.picking).toBe(true);
    expect(state.point).toBeNull();
  });
});
