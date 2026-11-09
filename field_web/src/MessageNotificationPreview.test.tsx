// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import MessageNotificationPreview from "./MessageNotificationPreview";
import type { NotificationPreview } from "./messageAnalysisApi";

function sample(): NotificationPreview {
  return {policy_version:"test-preview",phase:"preview",dispatch_enabled:false,record_version:3,
    source_revision:1,analysis_revision:1,catalog_digest:"a".repeat(64),input_kind:"example",
    decision:"notify_source_only",reason:"지역의 대피 안내를 공유할 필요가 있습니다.",
    assessment:{need:"notify",urgency:"immediate",relevance:"area_operations",reason:"지역의 대피 안내",evidence:["대구광역시 달서구 대피 안내입니다."],basis_refs:[]},
    facilities:[],limitations:["정확한 위치는 미확인입니다."],preview_text:"[창작 예문 · 미발송]\n대구광역시 달서구 대피 안내입니다.",map_url:"https://example.test/"};
}

describe("전파 판단 미리보기", () => {
  let container: HTMLDivElement; let root: Root; let value: NotificationPreview; let failure: boolean;
  let requests: Array<{url:string;method:string}>;
  beforeEach(() => {
    vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT",true); value=sample();failure=false;requests=[];
    vi.stubGlobal("fetch",vi.fn(async (url:string, init?:RequestInit) => {
      requests.push({url,method:init?.method||"GET"});
      if (!url.includes("/notification-preview?expected_version=")) throw new Error(`Unexpected request: ${url}`);
      return failure ? Response.json({detail:"기록 버전이 바뀌었습니다."},{status:409}) : Response.json(value);
    }));
    container=document.createElement("div");document.body.append(container);root=createRoot(container);
  });
  afterEach(async () => {await act(async()=>root.unmount());container.remove();vi.unstubAllGlobals();});
  async function render(version=3) {await act(async()=>root.render(<MessageNotificationPreview token="local-test-token" recordId="manual-test" version={version}/>));}

  it("shows an unsent source-only recommendation through one read-only request",async()=>{
    await render();expect(container.textContent).toContain("원문 중심 전파 추천");
    expect(container.textContent).toContain("미발송");expect(container.textContent).toContain("정확한 위치는 미확인");
    expect(container.querySelector('[aria-label="전달 문안 미리보기"]')?.textContent).toContain("창작 예문");
    expect(requests).toEqual([{url:"/internal/v1/message-records/manual-test/notification-preview?expected_version=3",method:"GET"}]);
    expect(container.querySelectorAll("button")).toHaveLength(0);
  });
  it("shows record-only reasons without creating a message preview",async()=>{
    value={...value,decision:"record_only",reason:"일반적인 예방 안내입니다.",preview_text:null,limitations:[]};
    await render();expect(container.textContent).toContain("기록 추천");expect(container.textContent).toContain("일반적인 예방 안내");
    expect(container.querySelector('[aria-label="전달 문안 미리보기"]')).toBeNull();
  });
  it("removes the previous preview after a version change and reports stale evidence",async()=>{
    await render();failure=true;await render(4);
    expect(container.textContent).toContain("기록 버전이 바뀌었습니다.");
    expect(container.querySelector('[aria-label="전달 문안 미리보기"]')).toBeNull();
    expect(requests.every(r=>r.method==="GET")).toBe(true);
  });
  it("rejects a mismatched record or non-preview response without displaying a send result",async()=>{
    value={...value,record_version:99};await render();
    expect(container.textContent).toContain("현재 기록의 미리보기인지 확인하지 못했습니다.");
    expect(container.querySelector('[aria-label="전달 문안 미리보기"]')).toBeNull();
  });
});
