// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import MessageAnalysisApp, { MessageAnalysisOutput } from "./MessageAnalysisApp";
import { checkAdminSession } from "./controlApi";
import type { MessageAnalysisResult, MessageInput } from "./messageAnalysisApi";
import examples from "./messageExamples.json";

const sample: MessageAnalysisResult = {
  input: { text: examples[3].text, source: "창작 예문", issued_at: examples[3].issued_at, input_kind: "example", reference_radius_km: 3 },
  analysis: { summary: "일부 구간만 해제되었습니다.", questions: ["푸른교의 정확한 위치를 확인해 주세요."], parts: [
    { intent: "release", description: "가람교 해제", evidence: "가람교 하부도로 통제는 15시 해제되었습니다.", time_text: "15시", starts_at: null, ends_at: null, locations: [] },
    { intent: "active_restriction", description: "푸른교 통제 유지", evidence: "푸른교 하부도로는 침수로 계속 통제 중", time_text: "", starts_at: null, ends_at: null, locations: [] },
  ] },
  review_required: true, candidates: [], nearby: [], trace: [{ tool: "submit_analysis", detail: "근거 검증 완료", status: "ok" }],
  model: "fake-model", model_calls: 1, elapsed_ms: 250,
};

describe("재난문자 검토", () => {
  let container: HTMLDivElement;
  let root: Root;
  let configured: boolean;
  let failure: boolean;
  let submitted: MessageInput | undefined;
  beforeEach(() => {
    vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
    window.sessionStorage.setItem("keco_admin_token", "signed-test-token");
    configured = true; failure = false; submitted = undefined;
    vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
      if (url.endsWith("/admin/session")) return Response.json({ authenticated: true });
      if (url.endsWith("/status")) return Response.json({ configured, place_search_configured: false, model: "fake-model" });
      if (url === "/internal/v1/message-analysis") {
        submitted = JSON.parse(init?.body as string) as MessageInput;
        return failure ? Response.json({ detail: "AI 서비스 연결에 실패했습니다." }, { status: 503 }) : Response.json(sample);
      }
      throw new Error(`Unexpected fake URL: ${url}`);
    }));
    container = document.createElement("div"); document.body.append(container); root = createRoot(container);
  });
  afterEach(async () => {
    await act(async () => root.unmount()); container.remove(); window.sessionStorage.clear(); vi.unstubAllGlobals();
  });
  async function click(label: string) {
    const button = [...container.querySelectorAll("button")].find(row => row.textContent === label);
    expect(button).toBeTruthy();
    await act(async () => button!.click());
  }
  async function submit() {
    await act(async () => container.querySelector("form")!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })));
  }

  it("blocks inference when the server has no key and still allows example inspection", async () => {
    configured = false;
    await act(async () => root.render(<MessageAnalysisApp />));
    await click("내일 통제");
    expect(container.querySelector("textarea")!.value).toContain("내일 09시");
    expect(container.textContent).toContain("AI 연결 준비 중");
    expect(container.querySelector<HTMLButtonElement>(".message-submit")!.disabled).toBe(true);
    await submit();
    expect(submitted).toBeUndefined();
  });

  it("sends the publication time with KST offset and marks the synthetic input", async () => {
    await act(async () => root.render(<MessageAnalysisApp />));
    await click("내일 통제"); await submit();
    expect(submitted?.issued_at).toBe("2026-11-07T17:00:00+09:00");
    expect(submitted?.input_kind).toBe("example");
    expect(submitted?.reference_radius_km).toBe(3);
    expect(container.textContent).toContain("담당자 검토 전");
    expect(container.textContent).toContain("푸른교 통제 유지");
    expect(container.textContent).toContain("위험 범위나 피해 시설을 뜻하지 않습니다");
    expect(container.textContent).not.toContain("안전합니다");
  });

  it("clears a previous result before displaying a failed retry", async () => {
    await act(async () => root.render(<MessageAnalysisApp />));
    await click("일부만 해제"); await submit();
    expect(container.textContent).toContain("일부 구간만 해제되었습니다");
    failure = true; await submit();
    expect(container.textContent).not.toContain("일부 구간만 해제되었습니다");
    expect(container.querySelector('[role="alert"]')!.textContent).toContain("연결에 실패");
  });

  it("shows a truncated facility list and ID-based map links as reference candidates", async () => {
    await act(async () => root.render(<MessageAnalysisOutput result={{ ...sample,
      candidates: [{ id: "P1", name: "시험 장소", address: "시험 주소", latitude: 35, longitude: 128, query: "시험", evidence: "시험" }],
      nearby: [{ candidate_id: "P1", total_count: 21, shown_count: 1, facilities: [{ id: "F & 1", name: "시험 시설", facility_type: "측정소", address: "시험 주소", distance_m: 123 }] }],
    }} />));
    expect(container.textContent).toContain("가까운 1개소를 표시");
    expect(container.querySelector("a")!.getAttribute("href")).toBe("/?facility_id=F%20%26%201");
    expect(container.textContent).toContain("시험 장소 후보 기준");
  });

  it("restores cookie authentication without sending the UI sentinel as a signed token", async () => {
    const fetcher = vi.mocked(fetch);
    await checkAdminSession("active-session");
    const options = fetcher.mock.calls.at(-1)![1]!;
    expect(options.credentials).toBe("same-origin");
    expect(options.headers).toEqual({});
  });
});
