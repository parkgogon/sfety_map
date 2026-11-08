// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from "vitest";
import MessageAutomationStatus from "./MessageAutomationStatus";
import type { MessageAutomation } from "./messageRecordsApi";

describe("문자 수집·분석 상태",()=>{
 let root:Root;let container:HTMLDivElement;let value:MessageAutomation;let fail:boolean;let refresh:Mock<(signal:AbortSignal)=>void>;
 beforeEach(()=>{
  vi.useFakeTimers();vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT",true);fail=false;refresh=vi.fn();
  value={state:"live",detail:"공식 공개 문자를 주기적으로 수집합니다.",auto_collection_enabled:true,feed_configured:true,interval_seconds:300,last_attempt_at:"2026-11-08T01:05:00Z",last_success_at:"2026-11-08T01:00:00Z",start_at:"2026-11-08T00:00:00Z",queue:{pending:3,running:1,failed:2,deferred:1,done:0,obsolete:0},budget:{limit:20,attempts:20,remaining:0,active:false}};
  vi.stubGlobal("fetch",vi.fn(async(url:string,init:RequestInit)=>{expect(url).toBe("/internal/v1/message-records/automation");expect(init.method).toBe("GET");return fail?Response.json({detail:"failure"},{status:503}):Response.json(value);}));
  container=document.createElement("div");document.body.append(container);root=createRoot(container);
 });
 afterEach(async()=>{await act(async()=>root.unmount());container.remove();vi.useRealTimers();vi.unstubAllGlobals();});
 async function render(){await act(async()=>root.render(<MessageAutomationStatus token="active-session" onRefresh={signal=>{refresh(signal);}}/>));}
 it("shows saved freshness, backlog and the shared conservative daily limit",async()=>{
  await render();expect(container.textContent).toContain("공식 문자 자동 수집 중");expect(container.textContent).toContain("브라우저를 닫아도");
  expect(container.textContent).toContain("분석 대기 3");expect(container.textContent).toContain("분석 실패 2");expect(container.textContent).toContain("수동 확인 대기 1");
  expect(container.textContent).toContain("20/20건");expect(container.textContent).toContain("수동·자동 합산, 실패 포함");expect(container.textContent).toContain("대기 기록은 보존");
  expect(refresh).not.toHaveBeenCalled();await act(async()=>vi.advanceTimersByTimeAsync(60000));expect(refresh).toHaveBeenCalledTimes(1);
 });
 it("does not label a failed or partial refresh as successful collection",async()=>{
  value.state="partial";value.detail="일부 페이지 확인 중";await render();expect(container.textContent).toContain("일부 조회 진행 중");
  fail=true;await act(async()=>vi.advanceTimersByTimeAsync(60000));expect(container.textContent).toContain("수집·분석 상태 확인 불가");expect(container.textContent).toContain("수집 성공 여부를 판단할 수 없습니다");expect(container.textContent).not.toContain("자동 수집 중");expect(refresh).not.toHaveBeenCalled();
  fail=false;value.state="stale";await act(async()=>vi.advanceTimersByTimeAsync(60000));expect(container.textContent).toContain("공식 문자 수집 지연");
 });
 it("aborts an in-flight status read and removes polling when leaving the page",async()=>{
  let signal:AbortSignal|undefined;
  vi.stubGlobal("fetch",vi.fn((_url:string,init:RequestInit)=>{signal=init.signal as AbortSignal;return new Promise(()=>{});}));
  await render();expect(signal?.aborted).toBe(false);await act(async()=>root.unmount());expect(signal?.aborted).toBe(true);
  root=createRoot(container);const calls=vi.mocked(fetch).mock.calls.length;await act(async()=>vi.advanceTimersByTimeAsync(120000));expect(fetch).toHaveBeenCalledTimes(calls);
 });
 it("distinguishes official request exhaustion from the separate AI analysis limit",async()=>{
  value.state="request_limit";value.detail="문자 조회 한도로 대기 중입니다.";value.interval_seconds=900;
  value.budget={limit:20,attempts:1,remaining:19,active:false};
  value.feed_budget={limit:450,used:450,remaining:0,window_hours:24,next_available_at:"2026-11-09T01:00:00Z"};
  await render();expect(container.textContent).toContain("문자 조회 한도로 수집 대기");
  expect(container.textContent).toContain("최근 24시간 문자 조회 450/450회");expect(container.textContent).toContain("조회 간격 15분");
  expect(container.textContent).toContain("오늘 분석 시작 1/20건");expect(container.textContent).not.toContain("오늘 분석 한도에 도달했습니다");
  expect(container.textContent).toContain("다시 조회 가능한 시각");expect(container.textContent).toContain("남은 작업은 유지");
 });
});
