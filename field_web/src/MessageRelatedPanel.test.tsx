// @vitest-environment jsdom
import { act, useState } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import MessageRelatedPanel, { MessageRelatedHistory } from './MessageRelatedPanel';
import type { MessageRecord } from './messageRecordsApi';
import type { RelatedPreview } from './messageRelationsApi';

const initial = {id:'manual-'+'a'.repeat(32),version:3,origin:'example',review_state:'completed',analysis_revision:1,
  created_at:'2026-11-08T10:00:00+09:00',updated_at:'2026-11-08T10:00:00+09:00',source_revision:1,analysis_state:'completed',note:'',analysis_error:'',reference_radius_km:3,
  message:{text:'가람교·푸른교 통제 시작 안내입니다.',source:'창작 예문',issued_at:'2026-11-08T10:00:00+09:00',recipient_regions:['경북 구미시']}} as MessageRecord;
const target={...initial,id:'manual-'+'b'.repeat(32),message:{...initial.message,text:'가람교 해제, 푸른교 통제 유지 안내입니다.',issued_at:'2026-11-08T15:00:00+09:00'}};
function part(index:number,intent:string,text:string){return {index,intent,evidence:text,starts_at:null,ends_at:null,locations:[{text,role:'restricted_area'}]};}
const basePreview:RelatedPreview={record_version:3,parent:initial,target,comparison_token:'c'.repeat(64),regions:{status:'overlap',detail:'수신지역이 겹쳐도 동일 사건이라는 증명은 아닙니다.'},
  comparison:{before:[part(0,'active_restriction','가람교'),part(1,'active_restriction','푸른교')],after:[part(0,'release','가람교'),part(1,'active_restriction','푸른교')],has_release:true,has_active_restriction:true,caution:'누락된 장소를 해제로 추정하지 않습니다.',
    locations:[{text:'가람교',role:'restricted_area',status:'same_spelling',before:part(0,'active_restriction','가람교'),after:part(0,'release','가람교')},{text:'별도 도로',role:'restricted_area',status:'earlier_only',before:part(2,'active_restriction','별도 도로'),after:null}]}};

describe('후속 문자 연결',()=>{
  let root:Root;let container:HTMLDivElement;let saved:MessageRecord;let preview:RelatedPreview;
  let unsaved:boolean;let failure:boolean;let stale:boolean;let calls:Array<{path:string;body:any}>;
  const changed=vi.fn();
  function Harness(){const [r,setR]=useState(saved);const [busy,setBusy]=useState(false);return <><span data-busy>{String(busy)}</span><MessageRelatedPanel token='fixture' record={r} disabled={false} unsavedWork={unsaved} onBusyChange={setBusy} onRecordChanged={v=>{changed(v);setR(v);}}/></>;}
  beforeEach(()=>{
    vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);saved=structuredClone(initial);preview=structuredClone(basePreview);unsaved=false;failure=false;stale=false;calls=[];changed.mockClear();
    vi.stubGlobal('fetch',vi.fn(async(url:string,init?:RequestInit)=>{
      const body=init?.body?JSON.parse(init.body as string):null;calls.push({path:url,body});
      if(url.endsWith('/related')&&!body)return Response.json({record_version:saved.version,epoch:saved.relation_epoch||0,fingerprint:'d'.repeat(64),needs_reconfirm:stale,
        links:Object.entries(saved.related_messages||{}).map(([id,e])=>({parent_id:saved.id,target:{...target,id},edge:e,needs_reconfirm:stale,segments:preview.comparison.after}))});
      if(url.includes('/related/candidates'))return Response.json({records:[target],next_cursor:url.includes('before')?null:'older-page'});
      if(url.includes('/related/preview'))return Response.json({...preview,record_version:saved.version,parent:saved});
      if(failure)return Response.json({detail:'비교 대상이 변경됐습니다.'},{status:409});
      if(url.endsWith('/related')&&body){saved={...saved,version:saved.version+1,review_state:'needs_confirmation',notice_draft:null,review_completion:null,relation_epoch:(saved.relation_epoch||0)+1,
        related_messages:{[target.id]:{kind:body.kind,reason:body.reason,target_source_revision:1,target_analysis_revision:1}},relation_last_change:{action:'message_linked',target_id:target.id,reason:body.reason,at:initial.updated_at}};return Response.json(saved);}
      if(url.endsWith('/related/unlink')){saved={...saved,version:saved.version+1,related_messages:{},relation_epoch:2,relation_last_change:{action:'message_unlinked',target_id:target.id,reason:body.reason,at:initial.updated_at}};return Response.json(saved);}
      throw new Error('Unexpected fixture '+url);
    }));container=document.createElement('div');document.body.append(container);root=createRoot(container);
  });
  afterEach(async()=>{await act(async()=>root.unmount());container.remove();vi.unstubAllGlobals();});
  async function render(){await act(async()=>root.render(<Harness/>));}
  function button(text:string){return [...container.querySelectorAll('button')].find(b=>b.textContent===text)!;}
  async function click(text:string){expect(button(text),text).toBeTruthy();await act(async()=>button(text).click());}
  async function fill(label:string,value:string){const f=container.querySelector<HTMLTextAreaElement>(`[aria-label="${label}"]`)!;await act(async()=>{Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value')!.set!.call(f,value);f.dispatchEvent(new Event('input',{bubbles:true}));});}
  async function compare(){await click('연결할 후속 문자 찾기');await click('이 문자와 비교');}
  async function acknowledge(){await fill('후속 연결 사유','같은 상황의 부분 해제 안내');const checkbox=[...container.querySelectorAll<HTMLInputElement>('input[type=checkbox]')].at(-1)!;await act(async()=>checkbox.click());}

  it('shows two originals and both release and active scopes without whole-event release',async()=>{
    await render();await compare();expect(container.textContent).toContain('일부 구간 해제와 통제 유지가 함께');expect(container.textContent).toContain(initial.message.text);expect(container.textContent).toContain(target.message.text);
    expect(container.textContent).toContain('이전 문자에만 표시 · 해제 추정 불가');expect(button('검토 대상으로 연결').disabled).toBe(true);
    await acknowledge();await click('검토 대상으로 연결');expect(saved.review_state).toBe('needs_confirmation');expect(saved.notice_draft).toBeNull();expect(changed).toHaveBeenCalledOnce();
    const posted=calls.find(c=>c.body&&c.path.endsWith('/related'))!.body;expect(posted.comparison_token).toBe('c'.repeat(64));expect(posted.confirmed).toBe(true);
    expect(calls.some(c=>c.path.includes('/analyze')||c.path.includes('dispatch'))).toBe(false);
  });
  it('requires extra confirmation and evidence for different regions',async()=>{
    preview.regions={status:'disjoint',detail:'수신지역이 다릅니다.'};await render();await compare();await acknowledge();expect(button('검토 대상으로 연결').disabled).toBe(true);
    const checkbox=container.querySelector<HTMLInputElement>('input[type=checkbox]')!;await act(async()=>checkbox.click());expect(button('검토 대상으로 연결').disabled).toBe(true);
    await fill('지역 간 연결 근거','양쪽 시에 걸친 상황 확인');await click('검토 대상으로 연결');expect(calls.find(c=>c.body&&c.path.endsWith('/related'))!.body.cross_region_confirmed).toBe(true);
  });
  it('blocks changing relationships while upstream or draft work is unsaved',async()=>{
    unsaved=true;await render();await compare();expect(container.textContent).toContain('저장하지 않은 메모');expect(container.querySelector<HTMLTextAreaElement>('[aria-label="후속 연결 사유"]')!.disabled).toBe(true);expect(button('검토 대상으로 연결').disabled).toBe(true);
  });
  it('preserves state and shows conflict without claiming saved relationship',async()=>{
    await render();await compare();await acknowledge();failure=true;await click('검토 대상으로 연결');expect(container.textContent).toContain('비교 대상이 변경');expect(changed).not.toHaveBeenCalled();expect(container.querySelector('[data-busy]')!.textContent).toBe('false');
  });
  it('supports reconfirmation after target changes and resets old preview after save',async()=>{
    saved={...saved,related_messages:{[target.id]:{kind:'release',reason:'기존 확인',target_source_revision:1,target_analysis_revision:1}},relation_epoch:1};stale=true;
    await render();expect(container.textContent).toContain('재확인 필요');await click('이 연결 비교·재확인');await acknowledge();await click('비교를 다시 확인하고 저장');
    expect(container.querySelector('[aria-label="후속 문자 원문 비교"]')).toBeNull();expect(saved.relation_epoch).toBe(2);
  });
  it('requires unlink reason and preserves a read-only relationship history',async()=>{
    await render();await compare();await acknowledge();await click('검토 대상으로 연결');const old=structuredClone(saved);
    await click('연결 해제 사유 입력');expect(button('사유를 남기고 연결 해제').disabled).toBe(true);await fill('연결 해제 사유','별개 사건 확인');await click('사유를 남기고 연결 해제');expect(saved.related_messages).toEqual({});
    await act(async()=>root.render(<MessageRelatedHistory record={old}/>));expect(container.textContent).toContain('같은 상황의 부분 해제 안내');expect(container.querySelectorAll('input,textarea,button')).toHaveLength(0);
  });
  it('pages bounded candidates and labels unknown regions without inventing an issuer region',async()=>{
    preview.regions={status:'unknown',detail:'수신지역만으로 지역 관계를 판단하기 어렵습니다.'};await render();await click('연결할 후속 문자 찾기');await click('후속 후보 다음 페이지');expect(calls.some(c=>c.path.includes('before=older-page'))).toBe(true);await click('이 문자와 비교');expect(container.textContent).toContain(preview.regions.detail);
  });
});
