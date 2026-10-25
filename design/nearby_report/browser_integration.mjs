// Real SDK + local 1GiB API. Fixed monitoring data; no production app/API writes.
import fs from 'node:fs/promises';
import path from 'node:path';
import http from 'node:http';
import {fileURLToPath} from 'node:url';
const {chromium}=await import(process.env.PLAYWRIGHT_MODULE || '/opt/codex/cua_node/lib/node_modules/playwright-core/index.mjs');
const root=fileURLToPath(new URL('../../',import.meta.url));
const out=process.env.NEARBY_INTEGRATION_OUT || '/workspace/nearby-integration-checks';
await fs.mkdir(out,{recursive:true});
const origin='https://keco-safety-map.web.app';
if(!process.env.HTTPS_PROXY)throw Error('Preserve HTTPS_PROXY');
function local(method,requestPath,body=null,onConnection=()=>{}){
 return new Promise((resolve,reject)=>{
  const request=http.request({hostname:'127.0.0.1',port:8877,path:requestPath,method,headers:body?{'Content-Type':'application/json'}:{}},response=>{
   const chunks=[];response.on('data',chunk=>chunks.push(chunk));response.on('end',()=>resolve({status:response.statusCode,headers:response.headers,body:Buffer.concat(chunks)}));
  });
  onConnection(request);request.on('error',reject);if(body)request.write(body);request.end();
 });
}
const browser=await chromium.launch({executablePath:process.env.CHROMIUM_EXECUTABLE || '/usr/bin/chromium',headless:true,proxy:{server:process.env.HTTPS_PROXY},args:['--no-sandbox']});
const records=[],errors=[],failures=[],forbidden=[],responses=[],apiResponses=[];
const widths=process.env.NEARBY_WIDTHS?process.env.NEARBY_WIDTHS.split(',').map(Number):[360,390,430,700,1440];
const apps=process.env.NEARBY_APPS?process.env.NEARBY_APPS.split(','):['field','control'];
try{
 for(const app of apps)for(const width of widths){
  const context=await browser.newContext({viewport:{width,height:width===1440?1000:900},acceptDownloads:true});
  await context.addInitScript(()=>{window.__realSdkMaps=[]});
  const connections=new Map();let reportPosts=0;
  context.on('requestfailed',request=>{
   const u=new URL(request.url());const connection=connections.get(request);if(connection)connection.destroy();
   failures.push({app,width,host:u.hostname,path:u.pathname,error:request.failure()?.errorText});
  });
  await context.route('**/*',async route=>{
   const request=route.request(),u=new URL(request.url());
   if(u.origin===origin){
    if((u.pathname==='/api/v1/reports/nearby.pdf'&&request.method()==='POST')||(request.method()==='GET'&&['/api/v1/monitoring','/api/v1/health','/internal/v1/admin/session'].includes(u.pathname))){
     if(request.method()==='POST')reportPosts++;
     try{
      const reply=await local(request.method(),u.pathname+u.search,request.postDataBuffer(),connection=>connections.set(request,connection));
      connections.delete(request);apiResponses.push({app,width,path:u.pathname,status:reply.status,mapStatus:reply.headers['x-nearby-map-status'],count:reply.headers['x-nearby-facility-count']});
      await route.fulfill({status:reply.status,headers:reply.headers,body:reply.body});
     }catch(error){if(!request.failure())errors.push({app,width,error:'Local API bridge: '+error.code})}
     return;
    }
    if(request.method()!=='GET'||u.pathname.startsWith('/internal/')||u.pathname.startsWith('/api/'))return route.fulfill({status:503,json:{detail:'Local QA does not provide this route'}});
    const directory=path.join(root,'field_web/dist');let file=path.resolve(directory,'.'+u.pathname);
    if(!file.startsWith(directory+path.sep)&&file!==directory)throw Error('Invalid static path');
    try{if(!(await fs.stat(file)).isFile())throw Error('SPA')}catch{file=path.join(directory,'index.html')}
    return route.fulfill({path:file});
   }
   if(request.method()!=='GET'||!['dapi.kakao.com','t1.kakaocdn.net','mts.kakaocdn.net'].includes(u.hostname)){
    forbidden.push({app,width,host:u.hostname,path:u.pathname,method:request.method()});return route.abort();
   }
   if(u.hostname==='dapi.kakao.com'&&u.pathname==='/v2/maps/sdk.js'){
    const response=await route.fetch(),source=await response.text();
    // Observe public Map instances to position the test. All map behavior remains native.
    return route.fulfill({response,body:source+`;(()=>{const load=kakao.maps.load;kakao.maps.load=(cb)=>load(()=>{if(!kakao.maps.Map.__instrumented){const Native=kakao.maps.Map;const Wrapped=new Proxy(Native,{construct(t,args){const map=Reflect.construct(t,args);window.__realSdkMaps.push({map,element:args[0]});return map}});Wrapped.__instrumented=true;kakao.maps.Map=Wrapped;}cb()});})();`});
   }
   return route.continue();
  });
  context.on('response',r=>{const u=new URL(r.url());if(u.origin!==origin)responses.push({host:u.hostname,path:u.pathname,status:r.status()})});
  const page=await context.newPage();page.on('pageerror',error=>errors.push({app,width,error:error.message.replace(/https?:\/\/[^\s)]+/g,'[URL]')}));
  await page.goto(origin+(app==='field'?'/':'/control'));
  if(app==='control')await page.getByRole('button',{name:'대상 분석·전파',exact:true}).click();
  await page.waitForFunction(()=>window.__realSdkMaps.length>0);
  await page.waitForFunction(()=>window.__realSdkMaps[0].element.querySelectorAll('img').length>0);
  const mobile=app==='field'&&width<=700;
  if(mobile){await page.getByLabel('시설·장소·주소 검색',{exact:true}).click();await page.getByRole('tab',{name:'장소·주소',exact:true}).click()}
  else await page.getByRole('button',{name:app==='control'?'장소·주소 / 주변 시설':'장소·주소',exact:true}).click();
  await page.getByRole('button',{name:'지도에서 지정',exact:true}).click();
  await page.evaluate(()=>{const m=window.__realSdkMaps[0].map;m.setLevel(7);m.setCenter(new kakao.maps.LatLng(35.8714,128.6014))});
  await page.waitForTimeout(500);
  const clickPoint=await page.evaluate(()=>{const {map,element}=window.__realSdkMaps[0],r=element.getBoundingClientRect(),p=map.getProjection().containerPointFromCoords(new kakao.maps.LatLng(35.8714,128.6014));return {x:r.left+p.x,y:r.top+p.y}});
  await page.mouse.click(clickPoint.x,clickPoint.y);
  await page.getByRole('button',{name:mobile?'이곳으로 지정':'이곳을 기준점으로 지정',exact:true}).click();
  await page.getByRole('button',{name:'주변 시설 보고서',exact:true}).click();
  const dialog=page.getByRole('dialog',{name:'주변 시설 보고서',exact:true});await dialog.waitFor();
  await dialog.getByText('반경 5km · 대상 3개소').waitFor();
  const beforePosts=reportPosts;
  const download=page.waitForEvent('download',{timeout:45000});
  await dialog.getByRole('button',{name:'PDF 생성',exact:true}).click();
  await dialog.getByText('지도와 보고서를 생성하고 있습니다.',{exact:false}).waitFor();
  if(!await dialog.getByRole('button',{name:'PDF 생성 중…',exact:true}).isDisabled())throw Error('Duplicate guard missing');
  await page.evaluate(()=>document.querySelector('.nearby-report-form').dispatchEvent(new Event('submit',{bubbles:true,cancelable:true})));
  await page.screenshot({path:path.join(out,`${app}-${width}-pending.png`)});
  await (await download).saveAs(path.join(out,`${app}-${width}.pdf`));
  await dialog.getByText('PDF를 다운로드했습니다.',{exact:true}).waitFor();
  if(reportPosts-beforePosts!==1)throw Error('Duplicate report requests');
  const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth);
  if(overflow)throw Error('Horizontal overflow');
  await page.screenshot({path:path.join(out,`${app}-${width}-complete.png`)});
  await page.keyboard.press('Escape');await dialog.waitFor({state:'detached'});
  const focus=await page.evaluate(()=>document.activeElement?.hasAttribute('data-nearby-report-trigger'));
  if(!focus)throw Error('Focus restoration failed');
  if(app==='field'&&width===390){
   await local('POST','/__qa/mode',JSON.stringify({mode:'unavailable'}));
   await page.getByRole('button',{name:'주변 시설 보고서',exact:true}).click();
   const fallback=page.waitForEvent('download');await dialog.getByRole('button',{name:'PDF 생성',exact:true}).click();
   await (await fallback).saveAs(path.join(out,'field-fallback.pdf'));
   await dialog.getByText('지도를 생성하지 못해 시설 목록·집계 보고서를 다운로드했습니다.',{exact:true}).waitFor();
   await page.screenshot({path:path.join(out,'field-fallback.png')});await page.keyboard.press('Escape');
   await local('POST','/__qa/mode',JSON.stringify({mode:'capture'}));
   const beforeCancel=JSON.parse((await local('GET','/__qa/status')).body),baseline=beforeCancel.responses.length;
   await page.getByRole('button',{name:'주변 시설 보고서',exact:true}).click();
   let cancelledDownloads=0;const onDownload=()=>cancelledDownloads++;page.on('download',onDownload);
   await dialog.getByRole('button',{name:'PDF 생성',exact:true}).click();
   const limit=Date.now()+15000;let observed=false;
   while(Date.now()<limit){
    const state=JSON.parse((await local('GET','/__qa/status')).body);
    if(state.activeCaptures===1&&state.responses.length>baseline){observed=true;break}
    await page.waitForTimeout(100);
   }
   if(!observed)throw Error('Cancellation test did not observe live SDK capture');
   const cancelStarted=Date.now();await page.keyboard.press('Escape');await dialog.waitFor({state:'detached'});
   const cleanupLimit=Date.now()+10000;let released=false;
   while(Date.now()<cleanupLimit){
    if(JSON.parse((await local('GET','/__qa/status')).body).activeCaptures===0){released=true;break}
    await page.waitForTimeout(100);
   }
   await page.waitForTimeout(300);page.off('download',onDownload);
   const afterCancel=JSON.parse((await local('GET','/__qa/status')).body);
   if(!released||cancelledDownloads!==0||afterCancel.captures.length!==beforeCancel.captures.length)throw Error('Browser cancel did not propagate to API capture');
   records.push({app,width,cancelledLiveCapture:true,serverCaptureReleased:true,lateDownloads:cancelledDownloads,
     cleanupMs:Date.now()-cancelStarted,completedServerReportsAfterCancel:afterCancel.captures.length-beforeCancel.captures.length});
  }
  records.push({app,width,facilityCount:3,download:true,duplicateRequestsPrevented:true,horizontalOverflow:overflow,focusRestored:focus});
  console.log(app,width,'passed');
  await context.close();
 }
}finally{
 await browser.close();
 await fs.writeFile(path.join(out,path.basename(process.env.NEARBY_BROWSER_RESULTS || 'browser-checks.json')),JSON.stringify({scope:'Local build and fixed monitoring, real map SDK/tiles and local 1GiB API. Owned-origin response overrides; no production app/API validation. Viewport emulation, not physical devices.',records,errors,failures,forbidden,responses,apiResponses},null,2));
}
if(errors.length||forbidden.length||responses.some(r=>r.status>=400))process.exitCode=1;
