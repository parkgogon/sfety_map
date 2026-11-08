// @vitest-environment jsdom
import { act, useState } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import MessageSpatialWorkspace, { MessageSpatialHistory } from './MessageSpatialWorkspace';
import type { MessageRecord } from './messageRecordsApi';
import type { MessageReference, SpatialFacility, SpatialLocation } from './messageSpatialApi';

vi.mock('./MessageReferenceMap', () => ({ MessageReferenceMap: ({ picking, onPick }: { picking: boolean; onPick: (v: { latitude:number; longitude:number }) => void }) =>
  <div><span>검수용 지도</span>{picking && <button onClick={() => onPick({ latitude:35.86, longitude:128.51 })}>지도 위치 클릭</button>}</div> }));
const recordBase = { id:'manual-'+'a'.repeat(32), version:3, analysis_revision:1, source_revision:1,
  origin:'example', analysis_state:'completed', review_state:'unreviewed', note:'',
  message:{ text:'검수용 문자 원문입니다.', source:'창작 예문', issued_at:'2026-11-08T10:00:00+09:00', recipient_regions:[] },
  created_at:'2026-11-08T10:00:00+09:00', updated_at:'2026-11-08T10:00:00+09:00', reference_radius_km:3, analysis_error:'' } as MessageRecord;
const digest = '1'.repeat(64);
const row = (id:string, within=true): SpatialFacility => ({id,name:`시험 시설 ${id}`,facility_type:'측정소',address:'대구 시험 주소',latitude:35.85,longitude:128.5,distance_m:within?100:8000,within_radius:within});
const rows = [...Array.from({length:25},(_,i)=>row(String(i))),row('far',false)];
const contexts: SpatialLocation[] = [
  {key:'0:0',text:'성서산업단지',role:'incident_site',intent:'event',evidence:'성서산업단지',eligible:true,
    candidates:[{id:'P1',name:'성서산업단지',address:'대구 달서구',latitude:35.85,longitude:128.5,query:'대구 성서산업단지',evidence:'성서산업단지',scope_matches_source:true}],reference:null,catalog_current:true},
  {key:'0:1',text:'성서초등학교',role:'evacuation_destination',intent:'event',evidence:'성서초등학교',eligible:false,candidates:[],reference:null,catalog_current:false},
  {key:'1:0',text:'중앙동 사거리',role:'restricted_area',intent:'active_restriction',evidence:'중앙동 사거리',eligible:true,candidates:[],reference:null,catalog_current:true},
];

describe('지도 확인과 시설 선정',()=>{
  let root:Root;let container:HTMLDivElement;let saved:MessageRecord;
  let refs:Record<string,MessageReference>;let requests:Array<{path:string;body:any}>;let failSave:boolean;let catalogCurrent:boolean;
  function Harness(){const [record,setRecord]=useState(saved);const [busy,setBusy]=useState(false);return <><span data-parent-busy>{String(busy)}</span><MessageSpatialWorkspace token='fixture' record={record} disabled={false} onRecordChanged={setRecord} onBusyChange={setBusy}/></>;}
  beforeEach(()=>{
    vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);saved=structuredClone(recordBase);refs={};requests=[];failSave=false;catalogCurrent=true;
    vi.stubGlobal('fetch',vi.fn(async(url:string,init?:RequestInit)=>{
      const u=new URL(url,'http://fixture');const body=init?.body?JSON.parse(init.body as string):null;
      requests.push({path:u.pathname,body});
      if(u.pathname.endsWith('/spatial')) return Response.json({record_version:saved.version,analysis_revision:1,catalog_digest:digest,
        locations:contexts.map(l=>({...l,reference:refs[l.key]||null,catalog_current:catalogCurrent})),reset_reason:''});
      if(u.pathname.endsWith('/reference')){
        if(failSave)return Response.json({detail:'저장 연결 실패'},{status:503});
        const p=body.point;const previous=refs[body.location_key];
        refs[body.location_key]={revision:(previous?.revision||0)+1,location_key:body.location_key,role:'incident_site',evidence:'성서산업단지',analysis_revision:1,source_revision:1,
          point:{latitude:p.latitude||35.85,longitude:p.longitude||128.5,label:p.label||'성서산업단지',address:'',source:p.mode==='candidate'?'candidate':p.manual_source,candidate_id:p.candidate_id||null,scope_matches_source:true},
          radius_km:body.radius_km,confirmation_note:body.confirmation_note,confirmed_at:saved.updated_at,catalog_digest:digest,nearby_count:25,
          selected:[],selection_note:'',selection_saved_at:null,selection_needs_review:!!previous};
        saved={...saved,version:saved.version+1};return Response.json(saved);
      }
      if(u.pathname.endsWith('/facilities')){
        const query=u.searchParams.get('query')||'';const scope=u.searchParams.get('scope');const offset=Number(u.searchParams.get('offset'));
        const list=rows.filter(r=>(scope==='all'||r.within_radius)&&(!query||r.name.includes(query)));
        return Response.json({facilities:list.slice(offset,offset+20),total_count:list.length,offset,next_offset:offset+20<list.length?offset+20:null,
          catalog_digest:digest,catalog_current:catalogCurrent,reference_revision:refs[u.searchParams.get('location_key')!]!.revision,record_version:saved.version,map_facilities:rows.filter(r=>r.within_radius)});
      }
      if(u.pathname.endsWith('/selection')){
        if(failSave)return Response.json({detail:'기록이 변경됐습니다. 다시 불러와 주세요.'},{status:409});
        const reference=refs[body.location_key];reference.selected=body.facilities.map((f:{facility_id:string;reason:string})=>({...rows.find(r=>r.id===f.facility_id)!,reason:f.reason}));
        reference.selection_note=body.note;reference.selection_saved_at=saved.updated_at;reference.selection_needs_review=false;
        saved={...saved,version:saved.version+1};return Response.json(saved);
      }
      throw new Error(`Unexpected fixture request ${url}`);
    }));container=document.createElement('div');document.body.append(container);root=createRoot(container);
  });
  afterEach(async()=>{await act(async()=>root.unmount());container.remove();vi.unstubAllGlobals();});
  async function render(){await act(async()=>root.render(<Harness/>));}
  async function click(text:string){const b=[...container.querySelectorAll('button')].find(b=>b.textContent===text);expect(b,text).toBeTruthy();await act(async()=>b!.click());}
  function labeled(label:string){return container.querySelector<HTMLInputElement|HTMLTextAreaElement|HTMLSelectElement>(`[aria-label="${label}"]`)!;}
  async function fill(label:string,value:string){const field=labeled(label);const prototype=field.tagName==='TEXTAREA'?HTMLTextAreaElement.prototype:field.tagName==='SELECT'?HTMLSelectElement.prototype:HTMLInputElement.prototype;
    await act(async()=>{Object.getOwnPropertyDescriptor(prototype,'value')!.set!.call(field,value);field.dispatchEvent(new Event(field.tagName==='SELECT'?'change':'input',{bubbles:true}));});}
  async function confirm(){await fill('기준점 확인 근거','산업단지 대표점을 참고 기준으로 사용');const check=container.querySelector<HTMLInputElement>('.message-spatial-check input')!;await act(async()=>check.click());await click('이 기준점으로 조회');}
  async function start(){await render();await click('성서산업단지 후보 선택');await confirm();}

  it('excludes destinations and requires explicit reference confirmation before listing facilities',async()=>{
    await render();expect(labeled('검토할 사고·통제 장소').querySelector<HTMLOptionElement>('option[value="0:1"]')!.disabled).toBe(true);
    expect(requests.some(r=>r.path.endsWith('/facilities'))).toBe(false);
    await click('성서산업단지 후보 선택');expect([...container.querySelectorAll('button')].find(b=>b.textContent==='이 기준점으로 조회')!.disabled).toBe(true);
    await confirm();expect(container.textContent).toContain('25개소 중 1~20번째');
    const posted=requests.find(r=>r.path.endsWith('/reference'))!.body;expect(posted.point).toEqual({mode:'candidate',candidate_id:'P1'});expect(posted.confirmed).toBe(true);
    expect(container.querySelector('[data-parent-busy]')!.textContent).toBe('false');
  });
  it('preserves selected facilities across pages and restores them after remount',async()=>{
    await start();await act(async()=>labeled('시험 시설 0 업무 대상 선택').click());await click('다음 시설 페이지');
    await act(async()=>labeled('시험 시설 21 업무 대상 선택').click());await fill('시설 선정 사유','인근 시설 업무 확인');await click('선정 시설 저장');
    expect(refs['0:0'].selected.map(r=>r.id)).toEqual(['0','21']);
    await act(async()=>root.unmount());root=createRoot(container);await render();expect(container.textContent).toContain('현재 선택 2개소');
    expect(requests.filter(r=>r.path.endsWith('/analyze'))).toHaveLength(0);
  });
  it('blocks selections after unsaved radius changes and clears previous selections on new criteria',async()=>{
    await start();await act(async()=>labeled('시험 시설 0 업무 대상 선택').click());await fill('시설 선정 사유','확인 필요');await click('선정 시설 저장');
    await fill('지도 참고 조회 거리','1');expect((labeled('시험 시설 0 업무 대상 선택') as HTMLInputElement).disabled).toBe(true);
    expect(container.textContent).toContain('저장한 이전 기준');await confirm();expect(refs['0:0'].selected).toEqual([]);expect(container.textContent).toContain('시설을 다시 선택');
  });
  it('requires an individual reason for a facility outside the query radius',async()=>{
    await start();await fill('시설 목록 범위','all');await fill('선정할 시설 검색','far');await click('시설 검색');
    await act(async()=>labeled('시험 시설 far 업무 대상 선택').click());await fill('시설 선정 사유','업무 연관 시설');
    expect([...container.querySelectorAll('button')].find(b=>b.textContent==='선정 시설 저장')!.disabled).toBe(true);
    await fill('시험 시설 far 반경 밖 추가 사유','같은 진입로 이용');await click('선정 시설 저장');expect(refs['0:0'].selected[0].reason).toBe('같은 진입로 이용');
  });
  it('saves a manager-picked map location with provenance and keeps scopes independent',async()=>{
    await start();await fill('검토할 사고·통제 장소','1:0');expect(container.textContent).toContain('확인된 장소 후보가 없습니다');
    await click('지도에서 위치 지정·수정');await click('지도 위치 클릭');await confirm();
    expect(requests.filter(r=>r.path.endsWith('/reference')).at(-1)!.body.point.manual_source).toBe('map');
    expect(Object.keys(refs)).toEqual(['0:0','1:0']);
  });
  it('keeps a failed selection visible and does not announce save success',async()=>{
    await start();await act(async()=>labeled('시험 시설 0 업무 대상 선택').click());await fill('시설 선정 사유','확인 필요');failSave=true;await click('선정 시설 저장');
    expect(container.textContent).toContain('기록이 변경됐습니다');expect(container.textContent).not.toContain('업무 대상 시설 선정을 저장했습니다');
    expect((labeled('시험 시설 0 업무 대상 선택') as HTMLInputElement).checked).toBe(true);expect(refs['0:0'].selected).toEqual([]);
  });
  it('shows changed catalog information and disables reuse of old selections',async()=>{
    await start();catalogCurrent=false;await click('지도 검토 다시 불러오기');expect(container.textContent).toContain('선정은 이전 자료 기준');
    expect((labeled('시험 시설 0 업무 대상 선택') as HTMLInputElement).disabled).toBe(true);
  });
  it('shows historical reference and selections without editable controls',async()=>{
    await start();await act(async()=>labeled('시험 시설 0 업무 대상 선택').click());await fill('시설 선정 사유','이전 선정 사유');await click('선정 시설 저장');
    const old=structuredClone(refs);await act(async()=>root.render(<MessageSpatialHistory references={old}/>));
    expect(container.textContent).toContain('과거 기록입니다');expect(container.textContent).toContain('시험 시설 0');expect(container.textContent).toContain('이전 선정 사유');
    expect(container.querySelectorAll('input,textarea,button')).toHaveLength(0);
  });

});
