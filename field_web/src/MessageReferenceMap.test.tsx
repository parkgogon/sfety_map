// @vitest-environment jsdom
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { loadKakaoMaps } from './kakao';
import { MessageReferenceMap } from './MessageReferenceMap';
import type { KakaoSDK } from './kakaoTypes';

vi.mock('./kakao',()=>({loadKakaoMaps:vi.fn()}));
describe('문자 검토 지도',()=>{
  let root:Root;let container:HTMLDivElement;let host:HTMLElement;
  let handlers:Array<{name:string;callback:(event:any)=>void}>;let bounds:Array<any[]>;let radii:number[];
  const point={latitude:35.85,longitude:128.5};
  const facility={id:'F1',name:'검수 시설',facility_type:'측정소',address:'검수 주소',latitude:35.851,longitude:128.5,distance_m:111,within_radius:true};
  beforeEach(()=>{
    vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);handlers=[];bounds=[];radii=[];
    class LatLng{constructor(public lat:number,public lng:number){}getLat(){return this.lat;}getLng(){return this.lng;}}
    class Bounds{points:any[]=[];extend(p:any){this.points.push(p);}}
    class Map{constructor(element:HTMLElement){host=element;}addControl(){}removeControl(){}relayout(){}setBounds(b:Bounds){bounds.push(b.points);}}
    class Overlay{element?:HTMLElement;constructor(options:any){this.element=options.content;if(this.element)host.append(this.element);}setMap(map:any){if(!map)this.element?.remove();}}
    class Circle extends Overlay{constructor(options:any){super(options);radii.push(options.radius);}}
    vi.mocked(loadKakaoMaps).mockResolvedValue({maps:{Map,LatLng,LatLngBounds:Bounds,ZoomControl:class{},ControlPosition:{RIGHT:1},CustomOverlay:Overlay,Circle,
      event:{addListener:(_target:any,name:string,callback:(event:any)=>void)=>handlers.push({name,callback}),removeListener:(_target:any,name:string,callback:any)=>{handlers=handlers.filter(h=>h.name!==name||h.callback!==callback);},trigger:()=>{}}}} as unknown as KakaoSDK);
    container=document.createElement('div');document.body.append(container);root=createRoot(container);
  });
  afterEach(async()=>{await act(async()=>root.unmount());container.remove();vi.unstubAllGlobals();});
  it('uses neutral reference markers and the actual 10km query radius without weather grades',async()=>{
    const onPick=vi.fn();
    await act(async()=>root.render(<MessageReferenceMap point={point} draft={null} radius={10} facilities={[facility]} selectedIds={[]} picking={false} onPick={onPick}/>));
    expect(radii.at(-1)).toBe(10000);expect(container.textContent).toContain('저장한 기준점');
    expect(container.textContent).not.toMatch(/위험|영향 없음/);expect(container.querySelector('.is-facility')).toBeTruthy();
    const fitCount=bounds.length;
    await act(async()=>root.render(<MessageReferenceMap point={point} draft={null} radius={10} facilities={[facility]} selectedIds={['F1']} picking={false} onPick={onPick}/>));
    expect(container.querySelector('.is-selected')).toBeTruthy();expect(bounds.length).toBe(fitCount);
    expect(bounds.at(-1)![1].lat-bounds.at(-1)![0].lat).toBeGreaterThan(.17);
  });
  it('picks coordinates only in explicit map-picking mode and cleans up overlays',async()=>{
    const onPick=vi.fn();
    await act(async()=>root.render(<MessageReferenceMap point={point} draft={null} radius={3} facilities={[facility]} selectedIds={[]} picking={false} onPick={onPick}/>));
    const event={latLng:{getLat:()=>35.86,getLng:()=>128.51}};
    await act(async()=>handlers.find(h=>h.name==='click')!.callback(event));expect(onPick).not.toHaveBeenCalled();
    await act(async()=>root.render(<MessageReferenceMap point={point} draft={null} radius={3} facilities={[facility]} selectedIds={[]} picking={true} onPick={onPick}/>));
    await act(async()=>handlers.find(h=>h.name==='click')!.callback(event));expect(onPick).toHaveBeenCalledWith({latitude:35.86,longitude:128.51});
    await act(async()=>root.unmount());expect(handlers.filter(h=>h.name==='click')).toHaveLength(0);expect(container.querySelector('.message-spatial-marker')).toBeNull();root=createRoot(container);
  });
  it('keeps the non-map workflow available when SDK loading fails',async()=>{
    vi.mocked(loadKakaoMaps).mockRejectedValue(new Error('fixture SDK failure'));
    await act(async()=>root.render(<MessageReferenceMap point={null} draft={null} radius={3} facilities={[]} selectedIds={[]} picking={false} onPick={()=>{}}/>));
    expect(container.textContent).toContain('후보 선택·좌표 직접 입력');
    expect(container.textContent).not.toContain('fixture SDK failure');
  });
});
