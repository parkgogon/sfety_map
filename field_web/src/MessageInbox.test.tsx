// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import MessageInbox from "./MessageInbox";
import type { MessageRecord } from "./messageRecordsApi";
import type { PreparedReview } from "./messagePreparationApi";

vi.mock("./MessageReferenceMap",()=>({MessageReferenceMap:()=> <div>검수용 지도</div>}));
const base="/internal/v1/message-records";
function sample():MessageRecord {return {id:"manual-"+"a".repeat(32),version:3,origin:"example",message:{text:"대구 청명교 인근 사고 안내입니다.",source:"창작 예문",issued_at:null,recipient_regions:[]},created_at:"2026-11-08T10:00:00+09:00",updated_at:"2026-11-08T10:00:00+09:00",source_revision:1,analysis_revision:1,reference_radius_km:3,analysis_state:"completed",analysis_error:"",review_state:"unreviewed",note:"",analysis:{input:{text:"대구 청명교 인근 사고 안내입니다.",source:"창작 예문",issued_at:null,reference_radius_km:3,input_kind:"example"},analysis:{summary:"청명교 사고 확인",parts:[],questions:[]},review_required:true,candidates:[],nearby:[],trace:[],model:"fake",model_calls:1,elapsed_ms:1}};}
function prepared():PreparedReview {return {record_version:3,proposal_hash:"1".repeat(64),catalog_digest:"2".repeat(64),outcome:"facilities_selected",selected_count:1,ready:true,issues:[],questions:[],uncertain_time:false,notice_preview:"검토 전 · 확인할 시설 · 창작 예문",locations:[{key:"0:0",text:"청명교",role:"incident_site",evidence:"청명교",candidates:[],point:{latitude:35.85,longitude:128.5,label:"청명교",source:"candidate",address:"대구",candidate_id:"P1",scope_matches_source:true},radius_km:3,facilities:[{id:"near",name:"참고 시설",facility_type:"측정소",address:"대구",latitude:35.85,longitude:128.5,distance_m:0,within_radius:true}],selected:[{id:"near",name:"참고 시설",facility_type:"측정소",address:"대구",latitude:35.85,longitude:128.5,distance_m:0,within_radius:true}],reference_required:false,representative:false,excluded_reason:null,saved_work:false}]};}

describe("간단 재난문자 검토",()=>{
 let root:Root;let container:HTMLDivElement;let record:MessageRecord;let approvals:number;let analyses:number;let registered:Record<string,unknown>|null;let requireAck:boolean;let failPreview:boolean;let stale:boolean;let copy:ReturnType<typeof vi.fn>;
 beforeEach(()=>{
  vi.useFakeTimers();vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT",true);window.history.replaceState({},"","/control/messages");record=sample();approvals=0;analyses=0;registered=null;requireAck=false;failPreview=false;stale=false;
  copy=vi.fn().mockResolvedValue(undefined);Object.defineProperty(navigator,"clipboard",{configurable:true,value:{writeText:copy}});
  vi.stubGlobal("fetch",vi.fn(async(url:string,init?:RequestInit)=>{
   const body=init?.body?JSON.parse(init.body as string):undefined;
   if(url===base&&init?.method==="POST"){registered=body;record={...sample(),origin:body.input_kind,message:{text:body.text,source:body.source,issued_at:body.issued_at,recipient_regions:body.recipient_regions},analysis:null,analysis_state:"not_analyzed"};return Response.json({record,registration:"created"});}
   if(url===base)return Response.json({records:[record],next_cursor:null});
   if(url.endsWith("/analyze")){analyses++;record={...record,analysis:sample().analysis,analysis_state:"completed",version:record.version+2};return Response.json(record);}
   if(url.endsWith("/prepare")){
    if(failPreview)return Response.json({detail:"근거 조회 실패"},{status:503});
    const p=prepared();p.record_version=record.version;
    p.notice_preview+=" "+body.manager_note;
    if(requireAck&&!body.choices.some((c:{reference_acknowledged?:boolean})=>c.reference_acknowledged)){p.ready=false;p.issues=["대표점 참고 조회 여부를 확인해 주세요."];}
    p.locations[0].reference_required=requireAck;
    return Response.json(p);
   }
   if(url.endsWith("/approve")){approvals++;expect(body.confirmed).toBe(true);expect(body.proposal_hash).toBe("1".repeat(64));record={...record,version:record.version+1,review_state:"completed",review_completion:{outcome:"facilities_selected",reason:"화면 확인",follow_up_note:"",excluded_locations:{},completed_at:record.created_at,basis_hash:"hash",selected_unique_count:1},notice_draft:{revision:1,template_version:1,basis_hash:"hash",manager_note:body.manager_note,text:"저장된 창작 안내 초안",updated_at:record.created_at}};return Response.json(record);}
   if(url.endsWith("/hold")){record={...record,version:record.version+1,review_state:"needs_confirmation",review_working_copy:{input:body,source_revision:record.source_revision,analysis_revision:record.analysis_revision,saved_at_version:record.version+1}};return Response.json(record);}
   if(url.endsWith("/review"))return Response.json({record_version:record.version,review_state:record.review_state,completion:record.review_completion,completion_current:!stale,draft:record.notice_draft,draft_current:!stale,stale_reason:stale?"시설 자료 변경":"",locations:[]});
   if(url.endsWith("/notice-copy"))return Response.json({text:record.notice_draft?.text});
   if(url===base+"/"+record.id)return Response.json(record);
   throw new Error("예상 밖 요청: "+url);
  }));
  container=document.createElement("div");document.body.append(container);root=createRoot(container);
 });
 afterEach(async()=>{await act(async()=>root.unmount());container.remove();window.history.replaceState({},"","/");vi.useRealTimers();vi.unstubAllGlobals();});
 async function tick(){await act(async()=>{await vi.advanceTimersByTimeAsync(220);});}
 async function render(){await act(async()=>root.render(<MessageInbox token="fake-session" status={{configured:true,place_search_configured:true,model:"fake"}} recordsStatus={{storage_configured:true,storage_mode:"memory",feed_configured:false}}/>));await tick();}
 function button(name:string){const b=[...container.querySelectorAll("button")].find(b=>b.textContent===name);expect(b,name).toBeTruthy();return b!;}
 async function click(name:string){await act(async()=>button(name).click());await tick();}
 async function open(){await act(async()=>container.querySelector<HTMLButtonElement>(".inbox-records button")!.click());await tick();}
 async function fill(label:string,value:string){const f=[...container.querySelectorAll("label")].find(l=>l.textContent?.startsWith(label))!.querySelector("textarea,input") as HTMLTextAreaElement;await act(async()=>{Object.getOwnPropertyDescriptor(f.tagName==="TEXTAREA"?HTMLTextAreaElement.prototype:HTMLInputElement.prototype,"value")!.set!.call(f,value);f.dispatchEvent(new Event("input",{bubbles:true}));});await tick();}

 it("explains the current input mode and finishes a clear record without separate reference or selection saves",async()=>{
  await render();expect(container.textContent).toContain("공식 문자 자동 수집 미연결");await open();
  expect(container.querySelector(".inbox-records")).toBeNull();expect(container.textContent).toContain("검토 전 · 확인할 시설");
  expect(container.textContent).not.toContain("기준점 확인 근거");expect(approvals).toBe(0);expect(analyses).toBe(0);
  await click("이 내용으로 검토 완료");expect(approvals).toBe(1);expect(container.textContent).toContain("검토 결과가 저장되어 있습니다");
  await click("안내문 복사");expect(copy).toHaveBeenCalledWith("저장된 창작 안내 초안");expect(analyses).toBe(0);
 });
 it("requires the representative-point acknowledgment only when necessary",async()=>{
  requireAck=true;await render();await open();expect(button("이 내용으로 검토 완료").disabled).toBe(true);
  await act(async()=>container.querySelector<HTMLInputElement>(".quick-ack input")!.click());await tick();
  expect(button("이 내용으로 검토 완료").disabled).toBe(false);await click("이 내용으로 검토 완료");expect(approvals).toBe(1);
 });
 it("updates a draft before enabling completion and preserves unapproved text when held",async()=>{
  await render();await open();await click("내용 수정");await fill("추가 안내","확인 중인 내용");expect(container.textContent).toContain("확인 중인 내용");
  await click("보류");expect(record.review_working_copy?.input.manager_note).toBe("확인 중인 내용");expect(record.review_completion).toBeUndefined();
  await open();await click("내용 수정");expect(container.querySelector<HTMLTextAreaElement>('[aria-label="추가 안내"]')?.value).toBe("확인 중인 내용");
 });
 it("accepts a pasted message with unknown publication time without inventing the current time",async()=>{
  await render();await click("문자 붙여넣기");await fill("문자 원문","대구 청명교 사고 발생 안내입니다.");await click("등록하고 검토안 준비");
  expect(registered?.issued_at).toBeNull();expect(registered?.source).toBe("공개 문자 수동 입력");expect(analyses).toBe(1);expect(container.textContent).toContain("발행 시각 미상");
 });
 it("shows a preview failure without enabling completion or discarding the record",async()=>{
  failPreview=true;await render();await open();expect(container.textContent).toContain("근거 조회 실패");expect(button("이 내용으로 검토 완료").disabled).toBe(true);expect(approvals).toBe(0);
 });
 it("does not offer stale completed drafts for copying",async()=>{
  await render();await open();await click("이 내용으로 검토 완료");stale=true;
  await click("← 검토 대기함");await open();expect(container.textContent).toContain("시설 자료 변경");expect(button("안내문 복사").disabled).toBe(true);
 });
 it("can reset a broken held preview while keeping the server working copy intact",async()=>{
  record.review_working_copy={input:{expected_version:2,choices:[],manager_note:"보류한 예전 안내"},source_revision:1,analysis_revision:1,saved_at_version:3};
  failPreview=true;await render();await open();expect(container.textContent).toContain("근거 조회 실패");
  failPreview=false;await click("수정 내용 초기화");expect(button("이 내용으로 검토 완료").disabled).toBe(false);
  expect(record.review_working_copy.input.manager_note).toBe("보류한 예전 안내");expect(approvals).toBe(0);
 });
});
