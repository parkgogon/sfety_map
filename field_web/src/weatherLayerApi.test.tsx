import { renderToString } from "react-dom/server";
import { afterEach, describe, expect, it, vi } from "vitest";
import { fetchWeatherLayer, useWeatherLayer } from "./weatherLayerApi";


function DisabledLayerProbe() {
  const state = useWeatherLayer(null);
  return <span>{state.loading ? "loading" : "off"}</span>;
}


describe("기상 레이어 API", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("레이어가 꺼진 초기 화면에서는 API를 호출하지 않는다", () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    expect(renderToString(<DisabledLayerProbe />)).toContain("off");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("선택한 종류의 읽기 전용 경로만 호출한다", async () => {
    const payload = {
      api_version: "v1",
      layer: "wind",
      status: "LIVE",
      observed_at: "2026-08-12T07:00:00+09:00",
      fetched_at: "2026-08-12T07:01:00+09:00",
      unit: "m/s",
      points: [],
      detail: "",
      source: "KMA",
      scope: "관제 권역",
      actual_data: true,
    };
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => payload,
    });
    vi.stubGlobal("fetch", fetchMock);
    const result = await fetchWeatherLayer("wind");
    expect(result.layer).toBe("wind");
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/weather/layers/wind");
  });

  it("종류가 다른 응답은 화면에 적용하지 않는다", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ api_version: "v1", layer: "rainfall", points: [] }),
    }));
    await expect(fetchWeatherLayer("temperature")).rejects.toThrow("잘못된");
  });
});
