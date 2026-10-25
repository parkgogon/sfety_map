// @vitest-environment jsdom
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { downloadNearbyReport } from "./nearbyReportApi";
const point = { latitude: 35, longitude: 129, label: "기준점", address: "주소", source: "map" as const };
const { webcrypto } = await vi.importActual<{ webcrypto: Crypto }>("node:crypto");
const digest = async (ids: string[]) => Array.from(new Uint8Array(await webcrypto.subtle.digest(
  "SHA-256", new TextEncoder().encode(JSON.stringify([...ids].sort())),
)), (byte) => byte.toString(16).padStart(2, "0")).join("");
beforeEach(() => { vi.stubGlobal("crypto", webcrypto); });
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); vi.useRealTimers(); });
it("기준점과 반경만 POST하며 PDF를 다운로드하고 URL을 회수한다", async () => {
  vi.useFakeTimers();
  const fetch = vi.fn().mockResolvedValue(new Response("%PDF", { headers: { "Content-Type": "application/pdf", "X-Nearby-Facility-Count": "0", "X-Nearby-Facility-Digest": await digest([]) } }));
  vi.stubGlobal("fetch", fetch);
  const create = vi.fn().mockReturnValue("blob:report"); const revoke = vi.fn();
  Object.defineProperty(URL, "createObjectURL", { configurable: true, value: create });
  Object.defineProperty(URL, "revokeObjectURL", { configurable: true, value: revoke });
  const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
  const signal = new AbortController().signal;
  await downloadNearbyReport(point, 0.1, [], signal);
  expect(fetch).toHaveBeenCalledOnce();
  const [url, request] = fetch.mock.calls[0];
  expect(url).toBe("/api/v1/reports/nearby.pdf"); expect(request.signal).toBeInstanceOf(AbortSignal);
  expect(JSON.parse(request.body)).toEqual({ latitude: 35, longitude: 129, label: "기준점", address: "주소", radius_km: 0.1 });
  expect(click).toHaveBeenCalledOnce(); expect(create).toHaveBeenCalledOnce();
  vi.advanceTimersByTime(60_000); expect(revoke).toHaveBeenCalledWith("blob:report");
});
it("클라이언트 시간 초과와 사용자 닫기 취소를 구분한다", async () => {
  vi.useFakeTimers();
  const signals: AbortSignal[] = [];
  vi.stubGlobal("fetch", vi.fn().mockImplementation((_url, request) => new Promise((_resolve, reject) => {
    signals.push(request.signal);
    request.signal.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")));
  })));
  const controller = new AbortController();
  const timed = downloadNearbyReport(point, 5, [], controller.signal);
  const assertion = expect(timed).rejects.toThrow("시간이 초과");
  await vi.waitFor(() => expect(signals).toHaveLength(1));
  await vi.advanceTimersByTimeAsync(45_000);
  await assertion;
  const cancel = new AbortController();
  const pending = downloadNearbyReport(point, 5, [], cancel.signal);
  const cancelled = expect(pending).rejects.toThrow("Aborted");
  await vi.waitFor(() => expect(signals).toHaveLength(2));
  cancel.abort(); await cancelled;
});
it("지도 실패 응답도 검증한 PDF를 내려받고 과부하는 재시도를 안내한다", async () => {
  Object.defineProperty(URL, "createObjectURL", { configurable: true, value: vi.fn().mockReturnValue("blob:report") });
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("%PDF", { headers: {
    "Content-Type": "application/pdf", "X-Nearby-Facility-Count": "0", "X-Nearby-Facility-Digest": await digest([]), "X-Nearby-Map-Status": "timeout",
  } })));
  expect(await downloadNearbyReport(point, 5, [], new AbortController().signal)).toEqual({ mapIncluded: false });
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("busy", { status: 429 })));
  await expect(downloadNearbyReport(point, 5, [], new AbortController().signal)).rejects.toThrow("많습니다");
});
it("오류·다른 형식·화면과 다른 시설 수는 다운로드하지 않는다", async () => {
  for (const response of [new Response("unavailable", { status: 503 }), new Response("html"),
    new Response("%PDF", { headers: { "Content-Type": "application/pdf", "X-Nearby-Facility-Count": "1" } })]) {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response));
    await expect(downloadNearbyReport(point, 5, [], new AbortController().signal)).rejects.toThrow();
  }
});
it("시설 수가 같아도 ID 구성이 다르면 다운로드하지 않는다", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("%PDF", { headers: {
    "Content-Type": "application/pdf", "X-Nearby-Facility-Count": "1", "X-Nearby-Facility-Digest": await digest(["server-id"]),
  } })));
  await expect(downloadNearbyReport(point, 5, ["screen-id"], new AbortController().signal)).rejects.toThrow("시설 자료가 변경");
});
