// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import MessageDeliveryPanel from "./MessageDeliveryPanel";
import type { DeliveryItem, DeliveryStatus } from "./messageDeliveryApi";

vi.mock("./MessageAutomationStatus",()=>({default:()=> <div>검수용 수집·비용 상태</div>}));
const base="/internal/v1/message-records/notifications";
describe("자동전파 운영 화면",()=>{
 let root:Root,container:HTMLDivElement,status:DeliveryStatus,items:DeliveryItem[],posts:{url:string;body:Record<string,unknown>}[],failed:boolean;
 beforeEach(()=>{
  vi.useFakeTimers();vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT",true);posts=[];failed=false;
  status={deployment_enabled:true,can_activate:true,active:false,state:"ready",generation:null,started_at:null,detail:"시작 전 자료는 보내지 않습니다.",worker:null};
  items=[{id:"message-delivery-"+"a".repeat(64),record_id:"official-"+"b".repeat(64),state:"unknown",destination:"staff_group",preview_text:"창작 원문 <script>는 문자로 보존합니다.",updated_at:"2026-11-09T01:00:00Z",attempts:1}];
  vi.stubGlobal("confirm",vi.fn(()=>true));
  Object.defineProperty(navigator,"clipboard",{configurable:true,value:{writeText:vi.fn().mockResolvedValue(undefined)}});
  vi.stubGlobal("fetch",vi.fn(async(url:string,init:RequestInit)=>{
   if(failed)return Response.json({detail:"상태 조회 실패"},{status:503});
   if(init.method==="POST"){
    const body=JSON.parse(init.body as string);posts.push({url,body});
    if(url.endsWith("/control")){status={...status,active:body.action==="start",state:body.action==="start"?"active":"paused",generation:"c".repeat(32)};return Response.json(status);}
    if(url.endsWith("/acknowledge")){items=[{...items[0],resolution:body.resolution,resolved_at:"2026-11-09T01:05:00Z"}];return Response.json({state:"acknowledged",resent:false});}
    throw new Error("예상 밖 변경 요청: "+url);
   }
   if(url===base+"/status")return Response.json(status);
   if(url.startsWith(base+"?kind=exceptions"))return Response.json({items:[{id:"incident",preview_text:"AI 비용 한도 확인 필요",source_count:3,recent_record_ids:["official-"+"d".repeat(64)]}],next_cursor:null});
   if(url.startsWith(base+"?kind=decisions"))return Response.json({items:[{record_id:"official-"+"e".repeat(64),state:"record_only",decision:{snapshot:{decision:"record_only",reason:"일반적인 건강관리 안내",preview_text:null}}}],next_cursor:null});
   if(url.startsWith(base+"?kind=deliveries"))return Response.json({items,next_cursor:null});
   throw new Error("예상 밖 조회: "+url);
  }));
  container=document.createElement("div");document.body.append(container);root=createRoot(container);
 });
 afterEach(async()=>{await act(async()=>root.unmount());container.remove();vi.useRealTimers();vi.unstubAllGlobals();});
 async function render(){await act(async()=>root.render(<MessageDeliveryPanel token="fake-session"/>));}
 async function click(text:string){const button=[...container.querySelectorAll("button")].find(b=>b.textContent===text);expect(button,text).toBeTruthy();await act(async()=>button!.click());}
 it("does not start on opening or polling and keeps a missing receipt distinct from success",async()=>{
  await render();expect(container.textContent).toContain("자동전파 시작 대기");expect(container.textContent).toContain("수신 결과 미상");
  expect(container.textContent).toContain("자동 재발송하지 않습니다");expect(container.querySelector("script")).toBeNull();
  await act(async()=>vi.advanceTimersByTimeAsync(60000));expect(posts).toEqual([]);
  expect(container.querySelector<HTMLAnchorElement>('a[href*="record_id="]')!.href).toContain("view=review");
 });
 it("supports one global activation and pause without per-message approvals",async()=>{
  await render();await click("자동전파 시작");
  expect(posts).toHaveLength(1);expect(posts[0].body).toEqual({action:"start",expected_generation:null});
  expect(container.textContent).toContain("재난문자 자동전파 중");
  await click("전파 일시정지");expect(posts[1].body).toEqual({action:"pause",expected_generation:"c".repeat(32)});
  expect(container.textContent).toContain("자동전파 일시정지");
 });
 it("leaves activation unchanged if the operator declines the start confirmation",async()=>{
  vi.mocked(window.confirm).mockReturnValue(false);await render();await click("자동전파 시작");expect(posts).toHaveLength(0);
 });
 it("records manual resolution without resending or changing an unknown result to API success",async()=>{
  await render();await click("별도 조치 완료");
  expect(posts).toHaveLength(1);expect(posts[0].url).toContain("/acknowledge");
  expect(container.textContent).toContain("수신 결과 미상");expect(container.textContent).toContain("원래 전송 결과는 보존");
  expect(container.textContent).not.toContain("전송 응답 확인");
 });
 it("shows aggregated exceptions and reasons for record-only decisions without new model requests",async()=>{
  await render();await click("확인 필요");expect(container.textContent).toContain("같은 사유 원문 3건");
  expect(container.querySelector('.delivery-exception-reason')?.textContent).toContain('AI 비용 한도 확인 필요');
  await click("판단 기록");expect(container.textContent).toContain("일반적인 건강관리 안내");expect(posts).toHaveLength(0);
 });
 it("marks failed reads as unknown state and retains saved history",async()=>{
  await render();failed=true;await act(async()=>vi.advanceTimersByTimeAsync(60000));
  expect(container.textContent).toContain("자동전파 상태 확인 필요");expect(container.textContent).toContain("상태 조회 실패");
  expect(container.textContent).toContain("수신 결과 미상");
 });
});
