/** Development-only comparison. Does not import App or call any API/SDK. */
import '../../src/styles/design_tokens.css';
import './style.css';
import { weatherColorChannels, windSpeedColorChannels } from '../../src/utils';
import { drawScalarLayer, type ScreenWeatherPoint } from '../../src/weatherLayerRendering';
import { drawWindSpeedLayer } from '../../src/windSpeedRendering';
import { advanceWindParticleSystem, buildWindVectorField, initializeWindParticleSystem, sampleWindVectorField, type WindParticleSystemState, type WindVectorField } from '../../src/windParticleField';
import { calculateWindParticleCount, drawStaticWindFlow, drawWindParticleFrame } from '../../src/windParticleAnimation';

type Option = 'current' | 'A' | 'B';
type Layer = 'wind' | 'temperature' | 'rainfall';
const names: Record<Option,string> = {current:'현재 표현',A:'A · 현재 표현 다듬기',B:'B · 지도 가독성 중심'};
const options: Option[] = ['current','A','B'];
const descriptions = {current:'현재 앱의 색면·입자 렌더러를 그대로 사용합니다.',A:'색면을 유지하고 흐름선의 대비·움직임·꼬리를 다듬습니다.',B:'색면을 낮추고 흐름선과 드문 숫자로 정보를 전달합니다.'};
const root=document.querySelector<HTMLDivElement>('#app')!;
root.innerHTML=`<header class="top"><div class="eyebrow">SAFETY MAP / MOTION STUDY 01</div><h1>기상 표현 비교실 <span class="badge">개발 시안 · 운영 미반영</span></h1><p>같은 개략도 · 같은 입력 · 같은 이동과 배율. PC는 나란히, 모바일은 탭으로 비교하세요. 지도 위를 드래그하거나 +/−를 누르면 세 안이 함께 움직입니다.</p></header>
<div class="toolbar"><div class="group" aria-label="기상 종류"><button data-layer="wind" aria-pressed="true">바람</button><button data-layer="temperature" aria-pressed="false">기온</button><button data-layer="rainfall" aria-pressed="false">강수</button></div><span class="divider"></span><div class="group" id="presets"><button data-speed="0">무풍 0</button><button data-speed="0.5" aria-pressed="true">약풍 0.5</button><button data-speed="4">보통 4</button><button data-speed="15">강풍 15m/s</button></div><span class="divider"></span><div class="group"><button class="run" id="replay">15초 비교 재생</button><button id="pause" aria-pressed="false">일시정지</button><button id="reset">위치 초기화</button></div><div class="live-status" role="status"></div></div>
<nav class="mobile-tabs" aria-label="비교안">${options.map((o,i)=>`<button data-tab="${o}" aria-pressed="${i===0}">${o==='current'?'현재':`시안 ${o}`}</button>`).join('')}</nav>
<main class="compare">${options.map((o,i)=>`<article class="option ${i===0?'is-active':''}" data-option="${o}"><header class="option-head"><span class="letter">${o==='current'?'C':o}</span><div><h2>${names[o]}</h2><small>${o==='current'?'현재 렌더러 · SDK 동작은 모사':'검토 후보 · 수치 미확정'}</small></div></header><div class="map" data-map="${o}"><canvas aria-label="${names[o]} 기상 시안"></canvas><span class="map-status"></span><div class="zoom"><button data-zoom="1" aria-label="${names[o]} 확대">+</button><button data-zoom="-1" aria-label="${names[o]} 축소">−</button></div><aside class="facility-card" hidden aria-label="시설 카드 배치 예시"><small>배치 검토용 합성 시설</small><strong>검수 시설 A</strong><span>시설 유형 · 담당부서 · 거리 예시</span></aside><div class="legend"><div class="legend-top"><span class="legend-label"></span><span>비교용 합성 자료</span></div><div class="legend-bar"></div><div class="legend-values"></div></div></div><div class="design-note">${descriptions[o]}</div></article>`).join('')}</main>
<div class="source-note">입력: 무풍/약풍/강풍 및 기온·강수 분포는 모두 시안용 합성 자료입니다. 배경은 대구 도심을 떠올리기 위한 자체 개략도이며 실제 도로 지도·관측값이 아닙니다.</div>
<section class="review"><details><summary>비교 조건·검토용 조절값과 한계</summary><p>현재 안은 운영 렌더러를 재사용합니다. 줌 때 숨김은 SDK 이벤트를 모사한 것이며 실제 Kakao 재투영 성능을 검증한 화면은 아닙니다. A/B는 기존 그림을 함께 확대·이동하는 후보입니다. 실제 SDK 검수는 표현 선택 후 진행합니다.</p><p>움직임은 풍속의 선형 배율이 아닙니다. 약풍의 가시성을 위한 후보 속도이며 0m/s에는 흐름을 그리지 않습니다. 숫자는 합성 입력을 유지합니다. 운영에 조절 항목을 추가하지 않습니다.</p><p class="group"><label>시안 색면 <input id="opacity" type="range" min="0.2" max="1.4" step="0.1" value="1"></label><label>시안 흐름 밀도 <input id="density" type="range" min="0.5" max="1.5" step="0.1" value="1"></label><label><input type="checkbox" id="reduced"> 움직임 줄이기</label><label><input type="checkbox" id="facility-card"> 시설 카드 배치 예시</label></p></details></section>`;
const W=600,H=500;
let layer:Layer='wind',speed=.5,zoom=1,pan={x:0,y:0},active:Option='current',paused=false;
let density=1,opacity=1,reduced=matchMedia('(prefers-reduced-motion: reduce)').matches;
let replayStart:number|null=null,manualTime:number|null=null,lastTime:number|null=null,zoomHideUntil=-1,lastReplayPreset=-1;
const reducedInput=root.querySelector<HTMLInputElement>('#reduced')!;reducedInput.checked=reduced;
const snapshots=new Map<Option,{surface:HTMLCanvasElement;flow:HTMLCanvasElement;field:WindVectorField;state:WindParticleSystemState}>();
const makeCanvas=()=>{const c=document.createElement('canvas');c.width=W;c.height=H;return c};
const flowAngle=(x:number,y:number)=>.38+.22*Math.sin(x/170)+.15*Math.cos(y/180);
function fixture():ScreenWeatherPoint[]{
 const points:ScreenWeatherPoint[]=[];
 for(let y=0;y<=6;y++)for(let x=0;x<=8;x++){
  const sx=x*90-60,sy=y*100-50,angle=flowAngle(sx,sy),s=speed===0?0:speed*(.85+.25*x/8);
  const warm=Math.exp(-((sx-360)**2+(sy-220)**2)/65000);
  const value=layer==='temperature'?16+14*warm+sy/170:Math.max(0,24*warm-4);
  points.push({x:sx,y:sy,source:{grid_x:x,grid_y:y,latitude:35.87+(250-sy)/10000,longitude:128.6+(sx-300)/10000,value,u_ms:Math.cos(angle)*s,v_ms:Math.sin(angle)*s,speed_ms:s}});
 }
 return points;
}
function rebuild(){
 const points=fixture(),field=buildWindVectorField(points,W,H)!;
 options.forEach(o=>{const surface=makeCanvas(),flow=makeCanvas(),ctx=surface.getContext('2d')!;
  if(layer==='wind')drawWindSpeedLayer(ctx,field);else drawScalarLayer(ctx,W,H,points,layer);
  snapshots.set(o,{surface,flow,field,state:initializeWindParticleSystem(field,o==='current'?calculateWindParticleCount(W,H):Math.round((o==='A'?135:95)*density),73124)});
 });
 root.querySelectorAll('[data-layer]').forEach(b=>b.setAttribute('aria-pressed',String((b as HTMLElement).dataset.layer===layer)));
 root.querySelectorAll('[data-speed]').forEach(b=>b.setAttribute('aria-pressed',String(Number((b as HTMLElement).dataset.speed)===speed)));
 const text=layer==='wind'?'풍속 m/s':layer==='temperature'?'기온 °C':'1시간 강수 mm';
 const values=layer==='wind'?['0','5','10','15+']:layer==='temperature'?['16','22','28','34']:['0','5','10','20+'];
 root.querySelectorAll('.legend-label').forEach(el=>el.textContent=text);
 root.querySelectorAll<HTMLElement>('.legend-values').forEach(el=>el.innerHTML=values.map(v=>`<span>${v}</span>`).join(''));
 const stops=values.map(v=>Number(v.replace('+',''))).map(v=>layer==='rainfall'&&v===0?'white':`rgb(${(layer==='wind'?windSpeedColorChannels(v):weatherColorChannels(layer,v)).join(',')})`);
 root.querySelectorAll<HTMLElement>('.legend-bar').forEach(el=>el.style.background=`linear-gradient(90deg,${stops.join(',')})`);
}
function street(ctx:CanvasRenderingContext2D,pts:number[][],width=7){
 ctx.beginPath();pts.forEach(([x,y],i)=>i?ctx.lineTo(x,y):ctx.moveTo(x,y));ctx.lineCap='round';ctx.lineJoin='round';ctx.strokeStyle='#d8d6ca';ctx.lineWidth=width+2;ctx.stroke();ctx.strokeStyle=width>8?'#fff3ce':'#fcfcf7';ctx.lineWidth=width;ctx.stroke();
}
function base(ctx:CanvasRenderingContext2D){
 ctx.fillStyle='#e9eee7';ctx.fillRect(-1500,-1500,3500,3500);
 ctx.fillStyle='#d7e6d0';ctx.beginPath();ctx.ellipse(470,80,125,65,-.2,0,Math.PI*2);ctx.fill();ctx.beginPath();ctx.ellipse(55,390,80,100,.4,0,Math.PI*2);ctx.fill();
 ctx.fillStyle='#e0e5df';for(let x=-100;x<750;x+=48)for(let y=-80;y<650;y+=51)ctx.fillRect(x+5,y+7,32,35);
 for(let x=-100;x<750;x+=95)street(ctx,[[x,-150],[x+18,170],[x-12,400],[x+8,700]],5);
 for(let y=-80;y<650;y+=92)street(ctx,[[-180,y],[180,y+15],[380,y-8],[780,y+12]],5);
 street(ctx,[[-150,255],[200,255],[390,240],[780,305]],13);street(ctx,[[240,-150],[250,140],[300,340],[285,700]],12);
 ctx.beginPath();ctx.moveTo(520,-180);ctx.bezierCurveTo(320,100,490,185,370,360);ctx.bezierCurveTo(330,450,340,550,430,700);ctx.strokeStyle='#c6dbd4';ctx.lineWidth=39;ctx.stroke();ctx.strokeStyle='#acd2df';ctx.lineWidth=26;ctx.stroke();
 street(ctx,[[310,190],[490,211]],9);street(ctx,[[255,352],[425,373]],9);
 for(const [name,x,y] of [['대구역',223,170],['중구',268,308],['동구',470,230],['수성구',462,430],['북구',177,53],['달구벌대로',74,241],['신천',399,317]] as [string,number,number][]){ctx.font=`${name.length<=3?'600 14':'11'}px system-ui`;ctx.fillStyle='#576c70';ctx.fillText(name,x,y)}
}
function candidateFlow(o:Option,dt:number){
 const data=snapshots.get(o)!,ctx=data.flow.getContext('2d')!;
 ctx.clearRect(0,0,W,H);
 if(speed===0)return;
 data.state.particles.forEach((p,i)=>{
  const vector=sampleWindVectorField(data.field,p.x,p.y);if(!vector)return;
  const length=Math.hypot(vector.dx,vector.dy);if(length<.0001)return;
  const ux=vector.dx/length,uy=vector.dy/length;
  const velocity=(o==='A'?9:11)+(o==='A'?6:7)*Math.sqrt(vector.speed);
  if(!paused&&!reduced){p.x+=ux*velocity*dt;p.y+=uy*velocity*dt;p.ageSeconds+=dt;}
  if(p.x<0||p.x>W||p.y<0||p.y>H||p.ageSeconds>p.maxAgeSeconds){p.x=(i*137.51+73)%W;p.y=(i*91.7+123)%H;p.ageSeconds=0;}
  const tail=(o==='A'?12:18)+(o==='A'?4:5)*Math.sqrt(vector.speed);
  const fade=Math.min(1,p.ageSeconds/.4,(p.maxAgeSeconds-p.ageSeconds)/.5);
  const x=p.x-ux*tail,y=p.y-uy*tail;
  ctx.beginPath();ctx.moveTo(x,y);ctx.lineTo(p.x,p.y);ctx.lineCap='round';ctx.globalAlpha=Math.max(.15,fade);
  ctx.lineWidth=3.2;ctx.strokeStyle='rgba(255,255,255,.72)';ctx.stroke();
  const gradient=ctx.createLinearGradient(x,y,p.x,p.y);gradient.addColorStop(0,'rgba(22,86,106,.05)');gradient.addColorStop(.45,o==='A'?'rgba(32,101,121,.82)':'rgba(30,82,106,.9)');gradient.addColorStop(1,o==='A'?'#145268':'#183f60');ctx.strokeStyle=gradient;ctx.lineWidth=o==='A'?1.5:1.7;ctx.stroke();
  ctx.fillStyle='#f8ffff';ctx.beginPath();ctx.arc(p.x,p.y,.85,0,Math.PI*2);ctx.fill();ctx.globalAlpha=1;
 });
}
function numericLabels(ctx:CanvasRenderingContext2D){
 const points=fixture();
 for(const index of [12,23,38,42]){
  const p=points[index],value=p.source.value!;
  const text=layer==='temperature'?`${Math.round(value)}°`:`${value<.05?'0':value.toFixed(1)}mm`;
  ctx.font='600 11px system-ui';const width=ctx.measureText(text).width+12;
  ctx.fillStyle='#ffffffed';ctx.beginPath();ctx.roundRect(p.x-width/2,p.y-10,width,21,6);ctx.fill();ctx.strokeStyle='#cfdae3';ctx.lineWidth=.8;ctx.stroke();ctx.fillStyle='#314c64';ctx.textAlign='center';ctx.fillText(text,p.x,p.y+4);ctx.textAlign='left';
 }
}
function markers(ctx:CanvasRenderingContext2D){
 for(const [x,y,n] of [[190,205,'1'],[315,340,'2'],[442,150,'3'],[114,371,'4']] as [number,number,string][]){ctx.beginPath();ctx.arc(x,y,9,0,Math.PI*2);ctx.fillStyle='#147e89';ctx.fill();ctx.strokeStyle='white';ctx.lineWidth=2;ctx.stroke();ctx.font='bold 10px system-ui';ctx.fillStyle='white';ctx.textAlign='center';ctx.fillText(n,x,y+3.5);ctx.textAlign='left'}
}
function draw(o:Option,dt:number,t:number){
 const data=snapshots.get(o)!;
 // Keep the same animation clock even when a mobile comparison tab is hidden.
 if(layer==='wind'){
  if(o==='current'){
   if(reduced){data.flow.getContext('2d')!.clearRect(0,0,W,H);drawStaticWindFlow(data.flow.getContext('2d')!,data.field,data.state.particles)}
   else if(!paused){data.state=advanceWindParticleSystem(data.field,data.state,dt);drawWindParticleFrame(data.flow.getContext('2d')!,W,H,data.state.particles)}
  }else candidateFlow(o,dt);
 }
 const el=root.querySelector<HTMLCanvasElement>(`[data-option="${o}"] canvas`)!,rect=el.getBoundingClientRect();if(rect.width===0)return;
 const ratio=Math.min(devicePixelRatio||1,2);if(el.width!==Math.round(rect.width*ratio)||el.height!==Math.round(rect.height*ratio)){el.width=Math.round(rect.width*ratio);el.height=Math.round(rect.height*ratio)}
 const ctx=el.getContext('2d')!;ctx.setTransform(ratio,0,0,ratio,0,0);ctx.clearRect(0,0,rect.width,rect.height);
 const scale=Math.max(rect.width/W,rect.height/H)*zoom;
 ctx.translate(rect.width/2+pan.x,rect.height/2+pan.y);ctx.scale(scale,scale);ctx.translate(-W/2,-H/2);base(ctx);
 if(!(o==='current'&&t<zoomHideUntil)){
  ctx.save();ctx.globalAlpha=o==='current'?1:opacity*(layer==='wind'?(o==='A'?1:.35):(o==='A'?.9:.45));ctx.drawImage(data.surface,0,0);ctx.restore();
  if(layer==='wind'){
   ctx.drawImage(data.flow,0,0);
  }else if(o==='B')numericLabels(ctx);
 }
 markers(ctx);ctx.setTransform(ratio,0,0,ratio,0,0);
 ctx.font='10px system-ui';ctx.fillStyle='#405d70';ctx.fillText('자체 개략도 · 실제 도로 아님',12,rect.height-82);
 const status=root.querySelector<HTMLElement>(`[data-option="${o}"] .map-status`)!;
 status.textContent=layer==='wind'?`${speed===0?'무풍':speed<1?'약풍':speed<10?'보통':'강풍'} · ${speed}m/s${reduced?' · 정적 표시':''}`:layer==='temperature'?'16~34°C · 비교 분포':'0~20mm · 비교 분포';
}
function render(t:number){
 const dt=lastTime===null?1/30:Math.max(0,Math.min(.1,t-lastTime));lastTime=t;
 if(replayStart!==null){const elapsed=(t-replayStart)%15;let target=elapsed<3?0:elapsed<7?.5:elapsed<11?15:.5;
  if(target!==lastReplayPreset){speed=target;lastReplayPreset=target;rebuild()}
  if(elapsed>=11){const p=(elapsed-11)/4;pan={x:30*Math.sin(p*Math.PI*2),y:12*Math.sin(p*Math.PI)};const next=1+.65*Math.sin(p*Math.PI);if(Math.abs(zoom-next)>.001)zoomHideUntil=t+.15;zoom=next}else{pan={x:0,y:0};zoom=1}
 }
 options.forEach(o=>draw(o,dt,t));
 root.querySelector('.live-status')!.textContent=`${replayStart!==null?'비교 재생 중 · ':''}배율 ${zoom.toFixed(2)}× · ${reduced?'움직임 줄임':paused?'일시정지':'움직임 켜짐'}`;
}
function stopReplay(){replayStart=null;lastReplayPreset=-1;root.querySelector('#replay')!.textContent='15초 비교 재생'}
root.querySelectorAll<HTMLElement>('[data-layer]').forEach(b=>b.onclick=()=>{layer=b.dataset.layer as Layer;rebuild()});
root.querySelectorAll<HTMLElement>('[data-speed]').forEach(b=>b.onclick=()=>{stopReplay();speed=Number(b.dataset.speed);rebuild()});
root.querySelector<HTMLButtonElement>('#replay')!.onclick=()=>{if(reduced)return;manualTime=null;replayStart=performance.now()/1000;lastReplayPreset=-1;paused=false;root.querySelector('#replay')!.textContent='비교 다시 재생'};
root.querySelector<HTMLButtonElement>('#pause')!.onclick=()=>{paused=!paused;stopReplay();const b=root.querySelector('#pause')!;b.setAttribute('aria-pressed',String(paused));b.textContent=paused?'계속 재생':'일시정지'};
root.querySelector<HTMLButtonElement>('#reset')!.onclick=()=>{stopReplay();zoom=1;pan={x:0,y:0};rebuild()};
root.querySelectorAll<HTMLElement>('[data-tab]').forEach(b=>b.onclick=()=>{active=b.dataset.tab as Option;root.querySelectorAll<HTMLElement>('[data-option]').forEach(el=>el.classList.toggle('is-active',el.dataset.option===active));root.querySelectorAll<HTMLElement>('[data-tab]').forEach(el=>el.setAttribute('aria-pressed',String(el===b)))});
function changeZoom(factor:number){stopReplay();zoom=Math.max(.7,Math.min(2.5,zoom*factor));zoomHideUntil=(manualTime??performance.now()/1000)+.3}
root.querySelectorAll<HTMLElement>('[data-zoom]').forEach(b=>b.onclick=e=>{e.stopPropagation();changeZoom(Number(b.dataset.zoom)>0?1.2:1/1.2)});
root.querySelectorAll<HTMLElement>('[data-map]').forEach(el=>{let pointer:{x:number;y:number}|null=null;el.onpointerdown=e=>{if((e.target as Element).closest('button'))return;stopReplay();pointer={x:e.clientX-pan.x,y:e.clientY-pan.y};el.setPointerCapture(e.pointerId)};el.onpointermove=e=>{if(pointer)pan={x:e.clientX-pointer.x,y:e.clientY-pointer.y}};el.onpointerup=()=>pointer=null;el.onpointercancel=()=>pointer=null;el.onwheel=e=>{e.preventDefault();changeZoom(e.deltaY<0?1.1:1/1.1)};});
root.querySelector<HTMLInputElement>('#opacity')!.oninput=e=>{opacity=Number((e.target as HTMLInputElement).value)};
root.querySelector<HTMLInputElement>('#density')!.oninput=e=>{density=Number((e.target as HTMLInputElement).value);rebuild()};
root.querySelector<HTMLInputElement>('#facility-card')!.onchange=e=>{const checked=(e.target as HTMLInputElement).checked;root.querySelectorAll<HTMLElement>('.facility-card').forEach(el=>el.hidden=!checked)};
reducedInput.onchange=()=>{reduced=reducedInput.checked;stopReplay();root.querySelector<HTMLButtonElement>('#replay')!.disabled=reduced;rebuild()};
matchMedia('(prefers-reduced-motion: reduce)').addEventListener('change',e=>{reduced=e.matches;reducedInput.checked=reduced;stopReplay();root.querySelector<HTMLButtonElement>('#replay')!.disabled=reduced;rebuild()});
// Deterministic capture hook, only present in this development entry.
Object.assign(window,{weatherPreview:{seek(t:number,replay=true){manualTime=t;if(replay&&replayStart===null)replayStart=0;if(!replay)stopReplay();render(t)},state:()=>({layer,speed,zoom,pan,reduced,paused,actualData:false,background:'self-authored schematic',sdk:false})}});
root.querySelector<HTMLButtonElement>('#replay')!.disabled=reduced;rebuild();function tick(t:number){if(manualTime===null&&!document.hidden)render(t/1000);requestAnimationFrame(tick)}requestAnimationFrame(tick);
