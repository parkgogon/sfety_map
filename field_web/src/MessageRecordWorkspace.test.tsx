// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import MessageAnalysisApp from "./MessageAnalysisApp";
import type { MessageRecord } from "./messageRecordsApi";
import type { MessageAnalysisResult } from "./messageAnalysisApi";
import examples from "./messageExamples.json";

const sample = (): MessageRecord => ({
  id: "manual-" + "a".repeat(32), version: 1, origin: "example",
  message: { text: examples[1].text, source: examples[1].source, issued_at: examples[1].issued_at, recipient_regions: ["대구광역시 달서구"] },
  created_at: examples[1].issued_at, updated_at: examples[1].issued_at,
  source_revision: 1, analysis_state: "not_analyzed", review_state: "unreviewed", note: "", analysis_revision: 0,
  analysis_error: "", reference_radius_km: 3, analysis: null,
});
function analysis(record: MessageRecord): MessageAnalysisResult {
  return { input: { ...record.message, input_kind: record.origin, reference_radius_km: 3 },
    analysis: { summary: "저장된 화재 검토 결과입니다.", parts: [], questions: ["정확한 공장을 확인해 주세요."] },
    review_required: true, candidates: [], nearby: [], trace: [], model: "fake", model_calls: 1, elapsed_ms: 10 };
}

describe("재난문자 등록·저장 작업", () => {
  let root: Root; let container: HTMLDivElement;
  let saved: MessageRecord | null; let analysisCalls: number; let posted: Record<string, unknown> | null;
  let listFailure: boolean; let analysisFailure: boolean; let noteConflict: boolean; let feedFailure: boolean;
  const base = "/internal/v1/message-records";
  beforeEach(() => {
    vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
    window.sessionStorage.setItem("keco_admin_token", "signed-test-token");
    window.history.replaceState({}, "", "/control/messages");
    saved = null; analysisCalls = 0; posted = null; listFailure = false; analysisFailure = false; noteConflict = false; feedFailure = false;
    vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
      const body = init?.body ? JSON.parse(init.body as string) : undefined;
      if (url.endsWith("/admin/session")) return Response.json({ authenticated: true });
      if (url === "/internal/v1/message-analysis/status") return Response.json({ configured: true, place_search_configured: true, model: "fake" });
      if (url === base + "/status") return Response.json({ storage_configured: true, storage_mode: "memory", feed_configured: true });
      if (url === base && (!init?.method || init.method === "GET")) return listFailure ? Response.json({ detail: "목록 조회 실패" }, { status: 503 }) : Response.json({ records: saved ? [saved] : [], next_cursor: null });
      if (url === base && init?.method === "POST") {
        posted = body; saved = { ...sample(), origin: body.input_kind,
          message: { text: body.text, source: body.source, issued_at: body.issued_at, recipient_regions: body.recipient_regions } };
        return Response.json({ record: saved, registration: "created" });
      }
      if (url === base + "/feed") return feedFailure ? Response.json({ detail: "공식 조회 실패" }, { status: 503 }) : Response.json({ status: "LIVE", detail: "선택한 지역·하루의 요청 페이지입니다.", page: 3, region: body.region, date: body.date,
        page_limit_reached: true, has_more: true, skipped: 1,
        messages: [{ official_id: "SN-1", message: sample().message, import_token: "server-signed-fixture", disaster_type: "화재", emergency_step: "안전안내" }] });
      if (url === base + "/import") { saved ??= { ...sample(), origin: "official" }; return Response.json({ record: saved, registration: "unchanged" }); }
      if (url.endsWith("/review")) return Response.json({ record_version: saved?.version, review_state: saved?.review_state, completion: null, completion_current: false, draft: null, draft_current: false, stale_reason: "", locations: [] });
      if (url.endsWith("/spatial")) return Response.json({ record_version: saved?.version, analysis_revision: 1, catalog_digest: "0".repeat(64), locations: [], reset_reason: "" });
      if (url.endsWith("/history")) return Response.json({ versions: [{ event: "registered", record: { ...sample(), note: "최초 기록 메모" } }], next_cursor: null });
      if (saved && url === base + "/" + saved.id + "/analyze") {
        analysisCalls++;
        if (analysisFailure) { saved = { ...saved, version: saved.version + 2, analysis_state: "failed", analysis_error: "이전 분석 결과를 유지합니다." }; return Response.json({ detail: "분석 연결 실패" }, { status: 503 }); }
        saved = { ...saved, version: saved.version + 2, analysis_state: "completed", analysis_revision: 1, analysis: analysis(saved) };
        return Response.json(saved);
      }
      if (saved && url === base + "/" + saved.id) {
        if (init?.method === "PATCH") {
          if (noteConflict) return Response.json({ detail: "기록이 변경됐습니다. 다시 불러와 주세요." }, { status: 409 });
          saved = { ...saved, version: saved.version + 1, note: body.note, review_state: body.review_state };
        }
        return Response.json(saved);
      }
      throw new Error(`Unexpected fixture URL: ${url}`);
    }));
    container = document.createElement("div"); document.body.append(container); root = createRoot(container);
  });
  afterEach(async () => {
    await act(async () => root.unmount()); container.remove(); window.sessionStorage.clear();
    window.history.replaceState({}, "", "/"); vi.unstubAllGlobals();
  });
  async function render() { await act(async () => root.render(<MessageAnalysisApp />)); }
  async function click(text: string) {
    const button = [...container.querySelectorAll("button")].find(b => b.textContent === text);
    expect(button, text).toBeTruthy(); await act(async () => button!.click());
  }
  async function fill(label: string, value: string) {
    const field = [...container.querySelectorAll("label")].find(l => l.textContent?.startsWith(label))!.querySelector("input,textarea") as HTMLInputElement | HTMLTextAreaElement;
    const prototype = field.tagName === "INPUT" ? HTMLInputElement.prototype : HTMLTextAreaElement.prototype;
    await act(async () => {
      Object.getOwnPropertyDescriptor(prototype, "value")!.set!.call(field, value);
      field.dispatchEvent(new Event("input", { bubbles: true }));
    });
  }

  it("registers without inference and preserves recipient regions separately from source", async () => {
    await render(); await click("사고 발생"); await fill("문자 수신지역", "대구광역시 달서구, 경상북도 경산시"); await click("문자 등록");
    expect(posted?.recipient_regions).toEqual(["대구광역시 달서구", "경상북도 경산시"]);
    expect(posted?.source).toBe(examples[1].source); expect(posted?.input_kind).toBe("example");
    expect(analysisCalls).toBe(0); expect(container.textContent).toContain("문자를 등록했습니다");
    expect(window.location.search).toContain("record_id=");
    expect(container.querySelector<HTMLTextAreaElement>("textarea")!.readOnly).toBe(true);
  });

  it("restores saved analysis after remount without another paid request", async () => {
    await render(); await click("사고 발생"); await click("등록하고 분석하기");
    expect(analysisCalls).toBe(1); expect(container.textContent).toContain("저장된 화재 검토 결과");
    await act(async () => root.unmount()); root = createRoot(container); await render();
    expect(container.textContent).toContain("저장된 화재 검토 결과"); expect(analysisCalls).toBe(1);
    expect(container.textContent).toContain("원문 1판");
  });

  it("retains the previous saved analysis when reanalysis fails", async () => {
    saved = { ...sample(), analysis_state: "completed", analysis_revision: 1, analysis: analysis(sample()) };
    window.history.replaceState({}, "", `?record_id=${saved.id}`);
    await render(); analysisFailure = true; await click("저장된 문자 분석");
    expect(container.textContent).toContain("분석 연결 실패");
    expect(container.textContent).toContain("저장된 화재 검토 결과"); expect(container.textContent).toContain("이전 분석 결과를 유지합니다");
  });

  it("does not claim save success on conflicting edits", async () => {
    saved = sample(); window.history.replaceState({}, "", `?record_id=${saved.id}`);
    await render(); await fill("확인할 사항", "교차로 위치 확인"); noteConflict = true; await click("검토 메모 저장");
    expect(saved.note).toBe(""); expect(container.textContent).toContain("기록이 변경됐습니다");
    expect(container.textContent).not.toContain("검토 메모를 저장했습니다");
  });

  it("retains the previous list when refreshing fails", async () => {
    saved = sample(); await render(); listFailure = true; await click("목록 새로고침");
    expect(container.textContent).toContain("목록 조회 실패");
    expect(container.querySelector(".message-record-choice strong")!.textContent).toBe(saved.message.text);
  });

  it("imports official content without inference and shows incomplete query limits", async () => {
    await render(); await click("최근 문자 조회");
    expect(container.textContent).toContain("3페이지 조회 상한"); expect(container.textContent).toContain("1건은 제외");
    await click("이 문자 등록·열기");
    expect(container.textContent).toContain("이미 등록한 문자"); expect(saved!.origin).toBe("official"); expect(analysisCalls).toBe(0);
    feedFailure = true; await click("최근 문자 조회");
    expect(container.textContent).toContain("공식 조회 실패"); expect(container.textContent).toContain("3페이지 조회 상한");
  });

  it("marks history as read-only and keeps the original when starting another record", async () => {
    saved = sample(); window.history.replaceState({}, "", `?record_id=${saved.id}`); await render();
    await click("변경 이력 보기"); await click("1판 · 문자 등록");
    expect(container.textContent).toContain("과거 1판"); expect(container.textContent).toContain("최초 기록 메모");
    await click("새 문자 등록"); expect(container.querySelector<HTMLTextAreaElement>("textarea")!.readOnly).toBe(false);
    expect(window.location.search).not.toContain("record_id"); expect(saved!.message.text).toBe(examples[1].text);
  });
});
