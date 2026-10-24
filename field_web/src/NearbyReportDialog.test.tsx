// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { NearbyReportDialog } from "./NearbyReportDialog";
import { downloadNearbyReport } from "./nearbyReportApi";
import type { Facility } from "./types";
vi.mock("./nearbyReportApi", () => ({ downloadNearbyReport: vi.fn() }));
const point = { latitude: 0, longitude: 0, label: "기준점", address: "검수 주소", source: "map" as const };
const earth = 6371008.8;
const facilities = [
  { id: "b", name: "같은 이름 시설", latitude: 0, longitude: 0 },
  { id: "a", name: "같은 이름 시설", latitude: 0, longitude: 0 },
  { id: "edge", name: "경계 시설", latitude: 1000 / earth * 180 / Math.PI, longitude: 0 },
  { id: "out", name: "바깥 시설", latitude: 1000.4 / earth * 180 / Math.PI, longitude: 0 },
] as Facility[];

describe("독립적인 주변 시설 보고서", () => {
  let root: Root;
  let container: HTMLDivElement;
  const onClose = vi.fn();
  const button = (name: string) => Array.from(document.querySelectorAll("button")).find((b) => b.textContent === name)!;
  const click = async (name: string) => act(async () => { button(name).click(); });
  const fill = async (value: string) => act(async () => {
    const input = document.querySelector("input")!;
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
  beforeEach(async () => {
    vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
    vi.clearAllMocks();
    vi.mocked(downloadNearbyReport).mockResolvedValue();
    container = document.createElement("div"); document.body.append(container); root = createRoot(container);
    await act(async () => root.render(<NearbyReportDialog point={point} facilities={facilities} onClose={onClose} />));
  });
  afterEach(async () => { await act(async () => root.unmount()); container.remove(); vi.unstubAllGlobals(); });

  it("기본 5km, 경계 포함과 반올림 전 제외, 같은 좌표의 별도 ID를 보존한다", async () => {
    expect(document.body.textContent).toContain("대상 4개소");
    await click("1km");
    expect(document.body.textContent).toContain("대상 3개소");
    expect(document.querySelector("ol")?.children).toHaveLength(3);
    expect(document.querySelector("ol")?.textContent).not.toContain("바깥 시설");
    await click("PDF 생성");
    expect(downloadNearbyReport).toHaveBeenCalledWith(point, 1, 3, expect.any(AbortSignal));
  });
  it("직접 입력은 0.1km 단위로 제한하며 0개도 생성한다", async () => {
    for (const value of ["", "0", "50.1", "0.15"]) {
      await fill(value); expect(button("PDF 생성").disabled).toBe(true);
    }
    await fill("0.1"); expect(button("PDF 생성").disabled).toBe(false);
    await act(async () => root.render(<NearbyReportDialog point={{ ...point, latitude: 35 }} facilities={facilities} onClose={onClose} />));
    expect(document.body.textContent).toContain("0개소 보고서");
    await click("PDF 생성");
    expect(downloadNearbyReport).toHaveBeenCalledWith(expect.objectContaining({ latitude: 35 }), 0.1, 0, expect.any(AbortSignal));
  });
  it("중복 요청을 막고 닫을 때 취소하며 늦게 완료돼도 다운로드 성공을 표시하지 않는다", async () => {
    let resolve!: () => void;
    vi.mocked(downloadNearbyReport).mockImplementation(() => new Promise<void>((r) => { resolve = r; }));
    await click("PDF 생성");
    const signal = vi.mocked(downloadNearbyReport).mock.calls[0][3];
    await act(async () => document.querySelector("form")!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })));
    expect(downloadNearbyReport).toHaveBeenCalledTimes(1);
    await click("생성 취소·닫기");
    expect(signal.aborted).toBe(true); expect(onClose).toHaveBeenCalledOnce();
    await act(async () => resolve());
    expect(document.body.textContent).not.toContain("다운로드했습니다");
  });
  it("실패를 0개로 표현하지 않고 재시도할 수 있다", async () => {
    vi.mocked(downloadNearbyReport).mockRejectedValueOnce(new Error("시설 자료를 읽지 못했습니다."));
    await click("PDF 생성");
    expect(document.body.textContent).toContain("시설 자료를 읽지 못했습니다.");
    expect(document.body.textContent).toContain("대상 4개소");
    expect(button("PDF 생성").disabled).toBe(false);
  });
});
