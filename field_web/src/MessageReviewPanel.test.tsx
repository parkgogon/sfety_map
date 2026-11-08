// @vitest-environment jsdom
import { act, useState } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import MessageReviewPanel, { MessageReviewHistory } from './MessageReviewPanel';
import type { MessageRecord } from './messageRecordsApi';

const initial = {id:'manual-'+'a'.repeat(32),version:5,origin:'example',review_state:'needs_confirmation',analysis_revision:1,
  created_at:'2026-11-08T10:00:00+09:00',updated_at:'2026-11-08T10:00:00+09:00',source_revision:1,analysis_state:'completed',note:'',analysis_error:'',reference_radius_km:3,
  message:{text:'창작 재난문자입니다.',source:'창작 예문',issued_at:'2026-11-08T10:00:00+09:00',recipient_regions:[]}} as MessageRecord;
describe('검토 완료와 안내 초안',()=>{
  let root:Root;let container:HTMLDivElement;let saved:MessageRecord;
  let requests:Array<{path:string;body:any}>;let noSelection:boolean;let stale:boolean;let failCopy:boolean;let failSave:boolean;let unsaved:boolean;
  let clipboard:ReturnType<typeof vi.fn>;
  function Harness(){const [record,setRecord]=useState(saved);const [busy,setBusy]=useState(false);return <><span data-busy>{String(busy)}</span><MessageReviewPanel token='fixture' record={record} disabled={false} unsavedWork={unsaved} onRecordChanged={setRecord} onBusyChange={setBusy}/></>;}
  beforeEach(()=>{
    vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);saved=structuredClone(initial);requests=[];noSelection=false;stale=false;failCopy=false;failSave=false;unsaved=false;
    clipboard=vi.fn().mockResolvedValue(undefined);vi.stubGlobal('navigator',{clipboard:{writeText:clipboard}});
    vi.stubGlobal('fetch',vi.fn(async(url:string,init?:RequestInit)=>{
      const body=init?.body?JSON.parse(init.body as string):null;requests.push({path:url,body});
      if(url.endsWith('/review'))return Response.json({record_version:saved.version,review_state:saved.review_state,
        completion:saved.review_completion||null,completion_current:!stale&&saved.review_state==='completed',
        draft:saved.notice_draft||null,draft_current:!stale&&saved.review_state==='completed',stale_reason:stale?'시설 자료가 변경됐습니다.':'',
        locations:[{key:'0:0',text:'산업단지',selected_count:noSelection?0:1},{key:'1:0',text:'사거리',selected_count:0}]});
      if(url.endsWith('/complete')){
        if(failSave)return Response.json({detail:'저장 연결 실패'},{status:503});
        saved={...saved,version:saved.version+1,review_state:'completed',review_completion:{outcome:body.outcome,reason:body.reason,follow_up_note:body.follow_up_note,
          excluded_locations:{},completed_at:'2026-11-08T10:30:00+09:00',basis_hash:'basis',selected_unique_count:body.outcome==='no_action'?0:1},
          notice_draft:{revision:1,template_version:1,basis_hash:'basis',manager_note:'',text:'[창작 예문] 원문·조회 기준·선정 시설·확인 질문이 담긴 초안',updated_at:'2026-11-08T10:30:00+09:00'}};
        return Response.json(saved);
      }
      if(url.endsWith('/notice-copy'))return failCopy?Response.json({detail:'초안 근거가 변경됐습니다.'},{status:409}):Response.json({text:saved.notice_draft!.text,draft_revision:saved.notice_draft!.revision});
      if(url.endsWith('/notice')){saved={...saved,version:saved.version+1,notice_draft:{...saved.notice_draft!,revision:saved.notice_draft!.revision+1,manager_note:body.manager_note,text:'[창작 예문] 고정 원문 근거\n관리자 추가 안내: '+body.manager_note}};return Response.json(saved);}
      if(url.endsWith('/reopen')){saved={...saved,version:saved.version+1,review_state:'needs_confirmation',review_completion:null,notice_draft:null,review_reopen_reason:body.reason};return Response.json(saved);}
      throw new Error(`Unexpected fixture request ${url}`);
    }));container=document.createElement('div');document.body.append(container);root=createRoot(container);
  });
  afterEach(async()=>{await act(async()=>root.unmount());container.remove();vi.unstubAllGlobals();});
  async function render(){await act(async()=>root.render(<Harness/>));}
  async function click(text:string){const button=[...container.querySelectorAll('button')].find(b=>b.textContent===text);expect(button,text).toBeTruthy();await act(async()=>button!.click());}
  function field(label:string){return container.querySelector<HTMLInputElement|HTMLTextAreaElement|HTMLSelectElement>(`[aria-label="${label}"]`)!;}
  async function fill(label:string,value:string){const f=field(label);const prototype=f.tagName==='SELECT'?HTMLSelectElement.prototype:HTMLTextAreaElement.prototype;
    await act(async()=>{Object.getOwnPropertyDescriptor(prototype,'value')!.set!.call(f,value);f.dispatchEvent(new Event(f.tagName==='SELECT'?'change':'input',{bubbles:true}));});}
  async function complete(){await fill('검토 완료 사유','선정 시설을 추가 확인하기로 함');await fill('사거리 미선정 사유','다른 관할 여부 별도 확인');await click('검토 완료하고 초안 만들기');}

  it('requires a decision reason and reasons for other unselected incident scopes',async()=>{
    await render();await fill('검토 완료 사유','시설 확인');
    expect([...container.querySelectorAll('button')].find(b=>b.textContent==='검토 완료하고 초안 만들기')!.disabled).toBe(true);
    await fill('사거리 미선정 사유','별도 확인');await click('검토 완료하고 초안 만들기');
    const posted=requests.find(r=>r.path.endsWith('/complete'))!.body;expect(posted.excluded_locations).toEqual([{location_key:'1:0',reason:'별도 확인'}]);
    expect(container.textContent).toContain('검토 완료 · 확인 대상 선정');expect(container.textContent).toContain('안내 초안 · 1판');expect(container.querySelector('[data-busy]')!.textContent).toBe('false');
  });
  it('blocks completion for unsaved upstream work',async()=>{
    unsaved=true;await render();expect(container.textContent).toContain('저장하지 않은 메모');
    expect(field('검토 완료 사유').disabled).toBe(true);expect(requests.filter(r=>r.path.endsWith('/complete'))).toHaveLength(0);
  });
  it('supports no-action completion without facility selection',async()=>{
    noSelection=true;await render();await fill('완료할 검토 결과','no_action');await fill('검토 완료 사유','예방 안내 검토 완료');await click('검토 완료하고 초안 만들기');
    expect(saved.review_completion!.outcome).toBe('no_action');expect(saved.review_completion!.selected_unique_count).toBe(0);
  });
  it('requires saving the additional note and checks the current server draft before clipboard write',async()=>{
    await render();await complete();await fill('관리자 추가 안내','현장 여건을 추가 확인해 주세요.');
    expect([...container.querySelectorAll('button')].find(b=>b.textContent==='현재 초안 복사')!.disabled).toBe(true);
    await click('추가 안내를 초안에 저장');expect(field('저장한 안내 초안').value).toContain('현장 여건을 추가 확인');
    await click('현재 초안 복사');expect(requests.at(-1)!.path).toContain('/notice-copy');expect(clipboard).toHaveBeenCalledWith(saved.notice_draft!.text);
    expect(container.textContent).toContain('실제 발송·수신 기록은 아닙니다');
  });
  it('does not copy or claim success if the server basis check fails',async()=>{
    await render();await complete();failCopy=true;await click('현재 초안 복사');
    expect(clipboard).not.toHaveBeenCalled();expect(container.textContent).toContain('초안 근거가 변경');expect(container.textContent).not.toContain('클립보드에 복사했습니다');
  });
  it('reports clipboard failure separately from server checking',async()=>{
    await render();await complete();clipboard.mockRejectedValue(new Error('fixture permission failure'));await click('현재 초안 복사');
    expect(container.textContent).toContain('클립보드에 복사하지 못했습니다');expect(container.textContent).not.toContain('클립보드에 복사했습니다');
  });
  it('requires a reopen reason and clears the old draft from current use',async()=>{
    await render();await complete();expect([...container.querySelectorAll('button')].find(b=>b.textContent==='사유를 남기고 다시 열기')!.disabled).toBe(true);
    await fill('검토 재열기 사유','확인 결과 보완');await click('사유를 남기고 다시 열기');
    expect(saved.review_state).toBe('needs_confirmation');expect(container.textContent).not.toContain('안내 초안 ·');expect(field('검토 완료 사유').value).toBe('');
  });
  it('disables copying a completed draft after catalog/basis changes',async()=>{
    await render();await complete();stale=true;await click('검토 결과 다시 불러오기');
    expect(container.textContent).toContain('현재 근거로 확인되지 않은 초안');expect([...container.querySelectorAll('button')].find(b=>b.textContent==='현재 초안 복사')!.disabled).toBe(true);
  });
  it('does not show completed success on storage failure and keeps completed history read-only',async()=>{
    await render();failSave=true;await complete();expect(container.textContent).toContain('저장 연결 실패');expect(saved.review_state).toBe('needs_confirmation');
    failSave=false;await complete();const old=structuredClone(saved);await act(async()=>root.render(<MessageReviewHistory record={old}/>));
    expect(container.textContent).toContain('과거 초안 1판');expect(container.querySelectorAll('input,textarea,button')).toHaveLength(0);
  });
});
