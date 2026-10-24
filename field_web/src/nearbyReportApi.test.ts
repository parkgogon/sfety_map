// @vitest-environment jsdom
import { afterEach, expect, it, vi } from "vitest";
import { downloadNearbyReport } from "./nearbyReportApi";
const point = { latitude: 35, longitude: 129, label: "기준점", address: "주소", source: "map" as const };
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); vi.useRealTimers(); });
it("기준점과 반경만 POST하며 PDF를 다운로드하고 URL을 회수한다", async () => {
  vi.useFakeTimers();
  const fetch = vi.fn().mockResolvedValue(new Response("%PDF", { headers: { "Content-Type": "application/pdf", "X-Nearby-Facility-Count": "0" } }));
  vi.stubGlobal("fetch", fetch);
  const create = vi.fn().mockReturnValue("blob:report"); const revoke = vi.fn();
  Object.defineProperty(URL, "createObjectURL", { configurable: true, value: create });
  Object.defineProperty(URL, "revokeObjectURL", { configurable: true, value: revoke });
  const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
  const signal = new AbortController().signal;
  await downloadNearbyReport(point, 0.1, 0, signal);
  expect(fetch).toHaveBeenCalledOnce();
  const [url, request] = fetch.mock.calls[0];
  expect(url).toBe("/api/v1/reports/nearby.pdf"); expect(request.signal).toBe(signal);
  expect(JSON.parse(request.body)).toEqual({ latitude: 35, longitude: 129, label: "기준점", address: "주소", radius_km: 0.1 });
  expect(click).toHaveBeenCalledOnce(); expect(create).toHaveBeenCalledOnce();
  vi.advanceTimersByTime(60_000); expect(revoke).toHaveBeenCalledWith("blob:report");
});
it("오류·다른 형식·화면과 다른 시설 수는 다운로드하지 않는다", async () => {
  for (const response of [new Response("unavailable", { status: 503 }), new Response("html"),
    new Response("%PDF", { headers: { "Content-Type": "application/pdf", "X-Nearby-Facility-Count": "1" } })]) {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response));
    await expect(downloadNearbyReport(point, 5, 0, new AbortController().signal)).rejects.toThrow();
  }
});
