const {chromium}=await import(process.env.PLAYWRIGHT_MODULE || '/opt/codex/cua_node/lib/node_modules/playwright-core/index.mjs');
import fs from 'node:fs/promises';import path from 'node:path';import {execFileSync} from 'node:child_process';import {fileURLToPath} from 'node:url';import os from 'node:os';
const dir=process.env.WEATHER_CHECK_DIR || await fs.mkdtemp(path.join(os.tmpdir(),'sfety-map-weather-'));await fs.mkdir(dir,{recursive:true});
const root=process.env.WEATHER_APP_ROOT || fileURLToPath(new URL('../../../../',import.meta.url));const origin='https://keco-safety-map.web.app';
const monitoring=JSON.parse(execFileSync(process.env.PYTHON || 'python3',[fileURLToPath(new URL('./export-fixture.py',import.meta.url)),root],{encoding:'utf8'}));
const records=[],failures=[],errors=[],forbidden=[];let speed=.5;
const fixture=kind=>({api_version:'v1',layer:kind,status:'SIMULATION',observed_at:'2026-10-25T07:00:00+09:00',fetched_at:'2026-10-25T07:00:00+09:00',unit:kind==='wind'?'m/s':kind==='temperature'?'℃':'mm',actual_data:false,source:'검수용 합성 격자',scope:'소관 권역',scenario_id:'visual-fixture',scenario_label:'합성 시각 검수',detail:'기상 표현 검수용 합성 자료',points:Array.from({length:45*41},(_,i)=>{const x=i%41,y=Math.floor(i/41),lat=34.5+y*.08,lng=127.5+x*.08,a=.4+.2*Math.sin(x/7);return {grid_x:x,grid_y:y,latitude:lat,longitude:lng,u_ms:Math.cos(a)*speed,v_ms:Math.sin(a)*speed,value:kind==='temperature'?18+14*Math.exp(-((lat-35.9)**2+(lng-128.6)**2)/.5):Math.max(0,25*Math.exp(-((lat-35.9)**2+(lng-128.6)**2)/.5)-2)}})});
const browser=await chromium.launch({executablePath:process.env.CHROMIUM_EXECUTABLE || '/usr/bin/chromium',headless:true,proxy:{server:process.env.HTTPS_PROXY},args:['--no-sandbox']});
const requests=[];
function canvasSpy(){
 const c=document.querySelector('.weather-map-surface'),ctx=c.getContext('2d');window.__labelBoxes=[];
 const clear=ctx.clearRect.bind(ctx),round=ctx.roundRect.bind(ctx),text=ctx.fillText.bind(ctx);
 ctx.clearRect=(...args)=>{window.__labelBoxes=[];return clear(...args)};
 ctx.roundRect=(x,y,w,h,...args)=>{window.__labelBoxes.push({x,y,w,h});return round(x,y,w,h,...args)};
 ctx.fillText=(value,...args)=>{if(window.__labelBoxes.length)window.__labelBoxes.at(-1).text=value;return text(value,...args)};
}
function canvasState(){
 const surface=document.querySelector('.weather-map-surface'),flow=document.querySelector('.wind-particle-canvas');
 const data=flow.getContext('2d').getImageData(0,0,flow.width,flow.height).data;let hash=2166136261,alpha=0;
 for(let i=3;i<data.length;i+=4){alpha+=data[i];hash=Math.imul(hash^data[i],16777619)}
 const base=window.__realSdkMaps[0].element.getBoundingClientRect(),matrix=new DOMMatrix(getComputedStyle(surface).transform);
 const boxes=(window.__labelBoxes||[]).map(b=>{const a=new DOMPoint(b.x,b.y).matrixTransform(matrix),z=new DOMPoint(b.x+b.w,b.y+b.h).matrixTransform(matrix);return {x:base.left+parseFloat(surface.style.left)+a.x,y:base.top+parseFloat(surface.style.top)+a.y,width:z.x-a.x,height:z.y-a.y,text:b.text}});
 const exclusions=[...document.querySelectorAll('.map-search-panel,.control-location-panel,.facility-sheet,.mobile-map-top-controls,.mobile-map-bottom-controls,.weather-layer-legend,.map-information-card,[data-facility-cluster]')].map(e=>e.getBoundingClientRect()).filter(r=>r.width>0&&r.height>0);
 const overlaps=boxes.filter(b=>exclusions.some(r=>b.x<r.right&&b.x+b.width>r.left&&b.y<r.bottom&&b.y+b.height>r.top));
 return {hash:hash>>>0,alpha,labels:boxes,overlaps:overlaps.length,opacity:getComputedStyle(surface).opacity,horizontalOverflow:document.documentElement.scrollWidth>innerWidth,tiles:[...window.__realSdkMaps[0].element.querySelectorAll('img')].filter(i=>i.src.includes('/tile/')&&i.naturalWidth>0).length};
}
async function videoStart(page,name){
 const cdp=await page.context().newCDPSession(page);const frames=[];
 cdp.on('Page.screencastFrame',e=>{frames.push({data:Buffer.from(e.data,'base64'),time:e.metadata.timestamp});cdp.send('Page.screencastFrameAck',{sessionId:e.sessionId}).catch(()=>{})});
 await cdp.send('Page.startScreencast',{format:'jpeg',quality:80,maxWidth:1440,maxHeight:900,everyNthFrame:2});
 return async()=>{
  await cdp.send('Page.stopScreencast');const frameDir=path.join(dir,name+'-frames');await fs.mkdir(frameDir,{recursive:true});
  let concat='';for(let i=0;i<frames.length;i++){const f=path.join(frameDir,String(i).padStart(4,'0')+'.jpg');await fs.writeFile(f,frames[i].data);concat+=`file '${f}'\nduration ${i+1<frames.length?Math.max(.02,frames[i+1].time-frames[i].time):.25}\n`}
  if(frames.length){concat+=`file '${path.join(frameDir,String(frames.length-1).padStart(4,'0')+'.jpg')}'\n`;const list=path.join(frameDir,'frames.txt');await fs.writeFile(list,concat);execFileSync('ffmpeg',['-y','-loglevel','error','-f','concat','-safe','0','-i',list,'-vf','pad=ceil(iw/2)*2:ceil(ih/2)*2','-c:v','libx264','-crf','21','-pix_fmt','yuv420p','-movflags','+faststart',path.join(dir,name+'.mp4')])}
  await cdp.detach();return frames.length;
 };
}
for(const app of ['field','control'])for(const [width,height] of [[1440,900],[390,844]]){
 const context=await browser.newContext({viewport:{width,height},deviceScaleFactor:width<700?2:1,locale:'ko-KR',timezoneId:'Asia/Seoul',serviceWorkers:'block'});
 let weatherRequests=0;speed=.5;
 await context.addInitScript(()=>{window.__realSdkMaps=[];document.addEventListener('DOMContentLoaded',()=>{const note=document.createElement('div');note.textContent='개발 빌드 · 실제 Kakao SDK / 고정 시설·합성 기상자료 · 실기기 아님';note.style='position:fixed;bottom:0;right:0;z-index:9999;background:#fff3d6;color:#674913;font-size:10px;padding:2px 6px;pointer-events:none';document.body.append(note)})});
 await context.route('**/*',async route=>{
  const q=route.request(),u=new URL(q.url());if(!['GET','HEAD','OPTIONS'].includes(q.method())||/\/(dispatch|worker|notifications|send|test)(\/|$)/i.test(u.pathname)){forbidden.push({method:q.method(),host:u.hostname,path:u.pathname});return route.abort('blockedbyclient')}
  if(u.origin===origin){
   if(u.pathname.startsWith('/api/v1/weather/layers/')){weatherRequests++;return route.fulfill({json:fixture(u.pathname.split('/').at(-1))})}
   if(u.pathname==='/api/v1/monitoring')return route.fulfill({json:monitoring});
   if(u.pathname==='/internal/v1/admin/session')return route.fulfill({json:{authenticated:false}});
   if(u.pathname.startsWith('/api/')||u.pathname.startsWith('/internal/'))return route.fulfill({status:503,json:{detail:'검수 범위 밖 조회'}});
   let file=path.join(root,'field_web/dist',u.pathname);try{if(!(await fs.stat(file)).isFile())throw Error('spa')}catch{file=path.join(root,'field_web/dist/index.html')}
   return route.fulfill({path:file});
  }
  if(u.hostname==='dapi.kakao.com'&&u.pathname==='/v2/maps/sdk.js'){
   const response=await route.fetch(),source=await response.text();
   return route.fulfill({response,body:source+`;(()=>{const load=kakao.maps.load;kakao.maps.load=(cb)=>load(()=>{if(!kakao.maps.Map.__instrumented){const Native=kakao.maps.Map;const Wrapped=new Proxy(Native,{construct(t,args){const map=Reflect.construct(t,args);window.__realSdkMaps.push({map,element:args[0]});return map}});Wrapped.__instrumented=true;kakao.maps.Map=Wrapped;}cb()});})();`});
  }
  return route.continue();
 });
 context.on('response',r=>{const u=new URL(r.url());if(u.origin!==origin)requests.push({host:u.hostname,path:u.pathname,status:r.status()})});
 context.on('requestfailed',r=>{const u=new URL(r.url());failures.push({host:u.hostname,path:u.pathname,error:r.failure()?.errorText})});
 const page=await context.newPage();page.on('pageerror',e=>errors.push({app,width,error:e.message.replace(/https?:\/\/[^\s)]+/g,'[URL]')}));
 await page.goto(origin+(app==='field'?'/':'/control'));
 if(app==='control')await page.getByRole('button',{name:'대상 분석·전파',exact:true}).click();
 await page.waitForFunction(()=>window.__realSdkMaps?.length>0);
 await page.evaluate(()=>{const m=window.__realSdkMaps[0].map;m.setLevel(8);m.setCenter(new kakao.maps.LatLng(35.8714,128.6014))});
 const waitTiles=()=>page.waitForFunction(()=>{const el=window.__realSdkMaps[0].element,r=el.getBoundingClientRect();const top=document.elementsFromPoint(r.left+r.width/2,r.top+r.height/2).find(e=>e.tagName==='IMG'&&e.src.includes('/tile/')&&el.contains(e));if(!top)return false;const imgs=[...top.parentElement.querySelectorAll('img')].filter(i=>{const b=i.getBoundingClientRect();return i.src.includes('/tile/')&&b.right>r.left&&b.left<r.right&&b.bottom>r.top&&b.top<r.bottom});return imgs.length>0&&imgs.every(i=>i.complete&&i.naturalWidth>0)},undefined,{timeout:20000});
 await page.locator('.map-canvas').scrollIntoViewIfNeeded();await waitTiles();await page.evaluate(canvasSpy);
 const labels={wind:'바람',temperature:'기온',rainfall:'강수'};
 const select=async kind=>{
  if(app==='control')await page.locator('.control-layer-chip').filter({hasText:labels[kind]}).click();
  else if(width<=700){await page.locator('.mobile-map-settings-trigger').click();await page.getByRole('tab',{name:'기상',exact:true}).click();await page.getByRole('button',{name:labels[kind]+' 기상 레이어',exact:true}).click();await page.getByLabel('지도 설정 닫기',{exact:true}).click()}
  else{await page.getByLabel('기상 실황 레이어 선택',{exact:true}).click();await page.locator('.weather-layer-options button').filter({hasText:labels[kind]}).click()}
  await page.waitForTimeout(350);
 };
 const stopVideo=app==='field'?await videoStart(page,'field-'+width):null;
 for(const kind of ['wind','temperature','rainfall']){
  await select(kind);await page.locator('.map-canvas').scrollIntoViewIfNeeded();await waitTiles();const initial=await page.evaluate(canvasState);
  if(initial.horizontalOverflow||initial.overlaps||initial.tiles===0)throw Error('화면 검수 실패 '+JSON.stringify({app,width,kind,...initial}));
  const before=weatherRequests;const startMap=await page.evaluate(()=>{const m=window.__realSdkMaps[0].map;return {lat:m.getCenter().getLat(),lng:m.getCenter().getLng(),level:m.getLevel()}});
  const box=await page.locator('.map-canvas').boundingBox();const x=box.x+box.width*.55,y=box.y+box.height*.48;
  await page.mouse.move(x,y);await page.mouse.down();await page.mouse.move(x+40,y+25,{steps:10});await page.mouse.up();await page.waitForTimeout(250);const movedMap=await page.evaluate(()=>{const m=window.__realSdkMaps[0].map;return {lat:m.getCenter().getLat(),lng:m.getCenter().getLng()}});if(Math.hypot(startMap.lat-movedMap.lat,startMap.lng-movedMap.lng)<.000001)throw Error('실제 지도 이동 미발생');
  const opacityPromise=page.evaluate(async()=>{const out=[];for(let i=0;i<45;i++){out.push(getComputedStyle(document.querySelector('.weather-map-surface')).opacity);await new Promise(r=>requestAnimationFrame(r))}return out});
  await page.mouse.move(x,y);await page.mouse.wheel(0,-120);await page.waitForTimeout(430);const zoomedLevel=await page.evaluate(()=>window.__realSdkMaps[0].map.getLevel());if(zoomedLevel>=startMap.level)throw Error('실제 지도 확대 미발생');
  await page.mouse.wheel(0,120);await page.waitForTimeout(430);const opacitySamples=await opacityPromise;
  await waitTiles();const final=await page.evaluate(canvasState);if(final.overlaps||final.horizontalOverflow)throw Error('이동 후 배치 오류');
  if(weatherRequests!==before)throw Error('지도 조작으로 기상 API 재호출');
  if(opacitySamples.some(x=>Number(x)===0))throw Error('그래픽 숨김');
  records.push({app,width,kind,initial,final,viewportWeatherRequests:weatherRequests-before,minimumOpacity:Math.min(...opacitySamples.map(Number)),startLevel:startMap.level,zoomedLevel,centerMoved:true});
  await page.screenshot({path:path.join(dir,`${app}-${kind}-${width}.png`)});
 }
 if(stopVideo)records.push({app,width,videoFrames:await stopVideo()});
 // Wind reduced-motion uses a static frame and resumes without fetching data.
 await select('wind');await page.emulateMedia({reducedMotion:'reduce'});await page.waitForTimeout(150);const staticA=await page.evaluate(canvasState);await page.waitForTimeout(180);const staticB=await page.evaluate(canvasState);
 if(staticA.hash!==staticB.hash)throw Error('움직임 줄이기에도 입자가 이동함');records.push({app,width,reducedMotionStable:true});
 await context.close();console.log(app,width,'passed');
}
await browser.close();await fs.writeFile(path.join(dir,'results.json'),JSON.stringify({scope:'Local development build, fixed monitoring and synthetic weather; REAL Kakao SDK and tiles. Registered origin reused via response overrides, no production application/API validation or deployment. Viewport emulation, no physical devices.',records,requests,failures,errors,forbidden},null,2));
console.log(JSON.stringify({outputDirectory:dir,cases:records.length,externalResponses:requests.length,failures:failures.length,errors,forbidden}));if(errors.length||forbidden.length)process.exitCode=1;
