import fs from 'node:fs/promises';
import path from 'node:path';
import {execFileSync} from 'node:child_process';
const {chromium}=await import('/opt/codex/cua_node/lib/node_modules/playwright-core/index.mjs');
const origin='https://keco-safety-map.web.app',out='/workspace/production-deploy-check';
if(!process.env.HTTPS_PROXY)throw Error('Preserve HTTPS_PROXY');
const browser=await chromium.launch({executablePath:'/usr/bin/chromium',headless:true,proxy:{server:process.env.HTTPS_PROXY},args:['--no-sandbox']});
const records=[],responses=[],failures=[],errors=[],forbidden=[],weather=[],reports=[];
const names={wind:'바람',temperature:'기온',rainfall:'강수'};
let reportPosts=0;
async function context(width){
 const c=await browser.newContext({viewport:{width,height:width===1440?1000:900},deviceScaleFactor:width===390?2:1,locale:'ko-KR',timezoneId:'Asia/Seoul',acceptDownloads:true,serviceWorkers:'block'});
 await c.route('**/*',route=>{
  const q=route.request(),u=new URL(q.url());
  const prohibited=/\/(dispatch|worker|notifications|send|test)(\/|$)/i.test(u.pathname);
  const own=u.origin===origin;
  const allowed=own?(q.method()==='GET'&&!prohibited&&(u.pathname.startsWith('/assets/')||['/','/control','/settings','/report-map.html','/favicon.ico','/api/v1/monitoring','/api/v1/health','/internal/v1/admin/session','/api/v1/risk-policy'].includes(u.pathname)||/^\/api\/v1\/(weather\/layers\/|facilities\/[^/]+\/weather)/.test(u.pathname)))||(q.method()==='POST'&&u.pathname==='/api/v1/reports/nearby.pdf')
   :q.method()==='GET'&&['dapi.kakao.com','t1.kakaocdn.net','mts.kakaocdn.net'].includes(u.hostname);
  if(!allowed){forbidden.push({host:u.hostname,path:u.pathname,method:q.method()});return route.abort('blockedbyclient')}
  if(q.method()==='POST')reportPosts++;
  return route.continue(); // No local responses, fixtures, API or SDK replacements.
 });
 c.on('requestfailed',q=>{const u=new URL(q.url());failures.push({host:u.hostname,path:u.pathname,error:q.failure()?.errorText})});
 c.on('response',async r=>{
  const u=new URL(r.url());responses.push({host:u.hostname,path:u.pathname,status:r.status()});
  try{
   if(u.origin===origin&&u.pathname.startsWith('/api/v1/weather/layers/')){const d=await r.json();weather.push({layer:d.layer,status:d.status,actualData:d.actual_data,observedAt:d.observed_at,points:d.points?.length})}
   if(u.pathname==='/api/v1/reports/nearby.pdf'){const h=r.headers();reports.push({status:r.status(),mapStatus:h['x-nearby-map-status'],count:h['x-nearby-facility-count'],digest:h['x-nearby-facility-digest']})}
  }catch{}
 });
 return c;
}
async function pageIn(c,url='/'){
 const p=await c.newPage();p.setDefaultTimeout(20000);p.on('pageerror',e=>errors.push(e.message.replace(/https?:\/\/[^\s)]+/g,'[URL]')));
 await p.goto(origin+url,{waitUntil:'domcontentloaded'});if(!url.startsWith('/control'))await p.locator('.map-canvas').first().waitFor();return p;
}
async function waitTiles(p){
 await p.locator('.map-canvas').first().scrollIntoViewIfNeeded();
 await p.waitForFunction(()=>{const el=document.querySelector('.map-canvas');if(!el)return false;return [...el.querySelectorAll('img')].some(i=>i.src.includes('/tile/')&&i.complete&&i.naturalWidth>0)});
}
async function settings(p,width){
 await p.locator('.mobile-map-settings-trigger').click();const dialog=p.getByRole('dialog',{name:'지도 설정',exact:true});
 if(await dialog.getByRole('button',{name:'지도 보기',exact:true}).count())throw Error('Redundant map button');
 const before=await dialog.locator('.mobile-settings-footer').innerText();
 const check=dialog.getByRole('checkbox').first();await check.uncheck();
 const after=await dialog.locator('.mobile-settings-footer').innerText();
 if(before===after)throw Error('Filter did not immediately update count');
 await p.screenshot({path:path.join(out,`settings-${width}.png`)});
 await dialog.getByRole('button',{name:'전체 표시',exact:true}).click();
 await p.keyboard.press('Escape');await dialog.waitFor({state:'detached'});
 const focus=await p.evaluate(()=>document.activeElement?.classList.contains('mobile-map-settings-trigger'));
 if(!focus)throw Error('Settings focus restoration');
 records.push({case:'settings',width,before,after,duplicateMapButton:false,escapeFocusRestored:focus});
}
async function selectWeather(p,app,width,kind){
 const loaded=p.waitForResponse(r=>new URL(r.url()).pathname==='/api/v1/weather/layers/'+kind,{timeout:65000});
 if(app==='control')await p.locator('.control-layer-chip').filter({hasText:names[kind]}).click();
 else if(width<=700){await p.locator('.mobile-map-settings-trigger').click();await p.getByRole('tab',{name:'기상',exact:true}).click();await p.getByRole('button',{name:new RegExp('^'+names[kind]+' 기상 레이어')}).click();await p.getByLabel('지도 설정 닫기',{exact:true}).click()}
 else{await p.getByLabel('기상 실황 레이어 선택',{exact:true}).click();await p.locator('.weather-layer-options button').filter({hasText:names[kind]}).click();if(await p.getByLabel('기상 선택 닫기',{exact:true}).count())await p.getByLabel('기상 선택 닫기',{exact:true}).click()}
 await p.locator('.weather-layer-legend').first().waitFor();
 await (await loaded).finished();
 await p.waitForFunction(()=>!document.querySelector('.weather-layer-legend')?.textContent?.includes('불러오는 중'),undefined,{timeout:65000});
 await p.waitForTimeout(500);
}
function canvasState(){
 const c=document.querySelector('.wind-particle-canvas'),s=document.querySelector('.weather-map-surface');
 const a=c.getContext('2d').getImageData(0,0,c.width,c.height).data;let hash=2166136261,alpha=0;
 for(let i=3;i<a.length;i+=4){alpha+=a[i];hash=Math.imul(hash^a[i],16777619)}
 return {hash:hash>>>0,alpha,transform:getComputedStyle(s).transform,opacity:getComputedStyle(s).opacity,overflow:document.documentElement.scrollWidth>innerWidth};
}
async function videoStart(p,name){
 const cdp=await p.context().newCDPSession(p),frames=[];
 cdp.on('Page.screencastFrame',e=>{frames.push({data:Buffer.from(e.data,'base64'),time:e.metadata.timestamp});cdp.send('Page.screencastFrameAck',{sessionId:e.sessionId}).catch(()=>{})});
 await cdp.send('Page.startScreencast',{format:'jpeg',quality:75,maxWidth:1440,maxHeight:1000,everyNthFrame:2});
 return async()=>{
  await cdp.send('Page.stopScreencast');await cdp.detach();const dir=path.join(out,name+'-frames');await fs.mkdir(dir,{recursive:true});let concat='';
  for(let i=0;i<frames.length;i++){const file=path.join(dir,String(i).padStart(4,'0')+'.jpg');await fs.writeFile(file,frames[i].data);concat+=`file '${file}'\nduration ${i+1<frames.length?Math.max(.02,frames[i+1].time-frames[i].time):.25}\n`}
  if(frames.length){concat+=`file '${path.join(dir,String(frames.length-1).padStart(4,'0')+'.jpg')}'\n`;const list=path.join(dir,'frames.txt');await fs.writeFile(list,concat);execFileSync('ffmpeg',['-y','-loglevel','error','-f','concat','-safe','0','-i',list,'-vf','pad=ceil(iw/2)*2:ceil(ih/2)*2','-c:v','libx264','-crf','23','-pix_fmt','yuv420p','-movflags','+faststart',path.join(out,name+'.mp4')])}
  return frames.length;
 };
}
async function motion(p,app,width,kind){
 await waitTiles(p);const initial=await p.evaluate(canvasState),before=weather.length;
 const box=await p.locator('.map-canvas').first().boundingBox(),x=box.x+box.width*.76,y=box.y+box.height*.44;
 await p.waitForTimeout(600);await p.mouse.move(x,y);await p.mouse.down();await p.mouse.move(x-45,y+25,{steps:12});await p.mouse.up();
 const samples=p.evaluate(async()=>{const a=[];for(let i=0;i<50;i++){a.push(getComputedStyle(document.querySelector('.weather-map-surface')).opacity);await new Promise(r=>requestAnimationFrame(r))}return a});
 await p.mouse.wheel(0,-120);await p.waitForTimeout(450);await p.mouse.wheel(0,120);await p.waitForTimeout(500);await samples;
 const final=await p.evaluate(canvasState);
 if(final.overflow)throw Error('Overflow');
 records.push({case:'weather-motion',app,width,kind,initial,final,weatherResponsesDuringMotion:weather.length-before,minimumOpacity:Math.min(...(await samples).map(Number))});
 await p.screenshot({path:path.join(out,`${app}-${kind}-${width}.png`)});
}
async function reference(p,app,width){
 const mobile=app==='field'&&width<=700;
 if(mobile){await p.getByLabel('시설·장소·주소 검색',{exact:true}).click();await p.getByRole('tab',{name:'장소·주소',exact:true}).click()}
 else await p.getByRole('button',{name:app==='control'?'장소·주소 / 주변 시설':'장소·주소',exact:true}).click();
 const input=p.getByLabel('장소명 또는 주소',{exact:true});await input.fill('대구광역시청 동인청사');await input.press('Enter');
 const candidates=p.getByLabel('장소·주소 검색 결과',{exact:true});await candidates.locator('button').first().waitFor();
 await p.screenshot({path:path.join(out,`${app}-${width}-candidates.png`)});
 const first=await candidates.locator('button').first().innerText();await candidates.locator('button').first().click();
 await p.getByRole('button',{name:mobile?'이곳으로 지정':'이곳을 기준점으로 지정',exact:true}).click();
 await p.getByRole('button',{name:'주변 시설 보고서',exact:true}).click();
 const dialog=p.getByRole('dialog',{name:'주변 시설 보고서',exact:true});await dialog.waitFor();
 const count=await dialog.locator('.nearby-report-count').innerText();
 const before=reportPosts,download=p.waitForEvent('download',{timeout:50000});await dialog.getByRole('button',{name:'PDF 생성',exact:true}).click();
 await dialog.getByText('지도와 보고서를 생성하고 있습니다.',{exact:false}).waitFor();
 await p.evaluate(()=>document.querySelector('.nearby-report-form').dispatchEvent(new Event('submit',{bubbles:true,cancelable:true})));
 const file=await download;await file.saveAs(path.join(out,`${app}-${width}.pdf`));
 const message=await dialog.getByRole('status').last().innerText();
 await p.screenshot({path:path.join(out,`${app}-${width}-report.png`)});
 if(reportPosts-before!==1)throw Error('Duplicate reports');
 await p.keyboard.press('Escape');await dialog.waitFor({state:'detached'});
 records.push({case:'nearby-report',app,width,firstCandidate:first,count,message,posts:reportPosts-before,focusRestored:await p.evaluate(()=>document.activeElement?.hasAttribute('data-nearby-report-trigger'))});
}
try{
 const c=await context(1440),p=await pageIn(c);await waitTiles(p);
 await p.getByRole('button',{name:'장소·주소',exact:true}).click();
 const input=p.getByLabel('장소명 또는 주소',{exact:true});await input.fill('대구광역시청 동인청사');await input.press('Enter');
 const candidates=p.getByLabel('장소·주소 검색 결과',{exact:true});await candidates.locator('button').first().click();
 await p.getByRole('button',{name:'이곳을 기준점으로 지정',exact:true}).click();await p.waitForTimeout(900);
 await p.screenshot({path:path.join(out,'reference-rings.png')});
 const rings=await p.locator('.location-radius-label').allTextContents();
 await p.locator('.location-nearby-list button').first().click();await p.waitForTimeout(900);
 await p.screenshot({path:path.join(out,'reference-connection.png')});
 const distance=await p.locator('.location-distance-label').innerText();
 const labelBox=await p.locator('.location-distance-label').boundingBox();const x=labelBox.x+labelBox.width/2,y=labelBox.y+labelBox.height/2;
 await p.mouse.move(x,y);await p.mouse.down();await p.mouse.move(x-25,y+15,{steps:10});await p.mouse.up();
 await p.mouse.wheel(0,120);await p.waitForTimeout(600);await p.mouse.wheel(0,-120);await p.waitForTimeout(1800);
 await p.screenshot({path:path.join(out,'reference-moved-zoomed.png')});
 records.push({case:'reference-geometry',rings,distance,afterMovingDistance:await p.locator('.location-distance-label').innerText()});
 await c.close();
}finally{await browser.close();await fs.writeFile(path.join(out,'geometry-checks.json'),JSON.stringify({scope:'Actual deployed UI, APIs, Kakao SDK and tiles; real place search/reference/rings/nearest facility selection and mouse pan/zoom. No response overrides.',records,responses,failures,errors,forbidden},null,2))}
