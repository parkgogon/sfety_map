// Development-only native browser capture. No production business API is contacted.
import fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import {fileURLToPath} from 'node:url';
import {execFileSync} from 'node:child_process';
import {createHash} from 'node:crypto';
const {chromium}=await import(process.env.PLAYWRIGHT_MODULE || '/opt/codex/cua_node/lib/node_modules/playwright-core/index.mjs');
const root=fileURLToPath(new URL('../../',import.meta.url));
const out=process.env.NEARBY_PREVIEW_DIR || await fs.mkdtemp(path.join(os.tmpdir(),'nearby-report-'));
const origin='https://keco-safety-map.web.app';
if(!process.env.HTTPS_PROXY || !process.env.VITE_KAKAO_MAP_APP_KEY)throw Error('HTTPS_PROXY and registered VITE_KAKAO_MAP_APP_KEY are required');
await fs.mkdir(out,{recursive:true});
const all=JSON.parse(execFileSync(process.env.PYTHON || 'python3',['-m','design.nearby_report.cases'],{cwd:root,encoding:'utf8'}));
const cases=process.env.NEARBY_CASES?all.filter(c=>process.env.NEARBY_CASES.split(',').includes(c.id)):all;
if(!cases.length)throw Error('No preview cases selected');
let html=await fs.readFile(new URL('map.html',import.meta.url),'utf8');
html=html.replace('<script>',`<script src="https://dapi.kakao.com/v2/maps/sdk.js?appkey=${encodeURIComponent(process.env.VITE_KAKAO_MAP_APP_KEY)}&autoload=false"></script><script>`);
const font=await fs.readFile(path.join(root,'fonts/NotoSansKR-Regular.ttf'));
const requests=[],failures=[],errors=[],forbidden=[],records=[];
const started=performance.now();
const browser=await chromium.launch({executablePath:process.env.CHROMIUM_EXECUTABLE || '/usr/bin/chromium',headless:true,proxy:{server:process.env.HTTPS_PROXY},args:['--no-sandbox']});
const launchMs=performance.now()-started;
const browserSession=await browser.newBrowserCDPSession();
async function rssSample(){
 const {processInfo}=await browserSession.send('SystemInfo.getProcessInfo');let rssKb=0,pssKb=0;
 for(const p of processInfo){try{
  const status=await fs.readFile('/proc/'+p.id+'/status','utf8');rssKb+=Number(status.match(/^VmRSS:\s+(\d+)/m)?.[1]||0);
  const shared=await fs.readFile('/proc/'+p.id+'/smaps_rollup','utf8');pssKb+=Number(shared.match(/^Pss:\s+(\d+)/m)?.[1]||0);
 }catch{}}
 return {rssMiB:rssKb/1024,pssMiB:pssKb/1024};
}
let peakRssMiB=0,peakPssMiB=0;
const monitor=setInterval(()=>rssSample().then(v=>{peakRssMiB=Math.max(peakRssMiB,v.rssMiB);peakPssMiB=Math.max(peakPssMiB,v.pssMiB)}).catch(()=>{}),100);
try {
 for(const data of cases) {
  const context=await browser.newContext({viewport:{width:1200,height:620},deviceScaleFactor:2,locale:'ko-KR'});
  await context.route('**/*',async route=>{
   const req=route.request(),u=new URL(req.url());
   if(req.method()!=='GET'){forbidden.push({host:u.hostname,path:u.pathname,reason:'non-GET'});return route.abort()}
   if(u.origin===origin){
    if(u.pathname==='/__nearby-preview.html')return route.fulfill({status:200,contentType:'text/html',body:html});
    if(u.pathname==='/__nearby-preview-font.ttf')return route.fulfill({status:200,contentType:'font/ttf',body:font});
    forbidden.push({host:u.hostname,path:u.pathname,reason:'production request blocked'});return route.abort();
   }
   if(!['dapi.kakao.com','t1.kakaocdn.net','mts.kakaocdn.net'].includes(u.hostname)){
    forbidden.push({host:u.hostname,path:u.pathname,reason:'outside SDK allowlist'});return route.abort();
   }
   return route.continue();
  });
  context.on('response',res=>{const u=new URL(res.url());if(u.origin!==origin)requests.push({host:u.hostname,path:u.pathname,status:res.status()})});
  context.on('requestfailed',req=>{const u=new URL(req.url());failures.push({case:data.id,host:u.hostname,path:u.pathname,error:req.failure()?.errorText})});
  const page=await context.newPage();page.on('pageerror',e=>errors.push({case:data.id,error:e.message.replace(/https?:\/\/[^\s)]+/g,'[URL]')}));
  const start=performance.now();
  await page.goto(origin+'/__nearby-preview.html');
  const geometry=await page.evaluate(data=>window.renderReportMap(data),data);
  await page.waitForFunction(()=>{
   const el=document.getElementById('map'),r=el.getBoundingClientRect();
   const tile=document.elementsFromPoint(r.width/2,r.height/2).find(e=>e.tagName==='IMG'&&e.src.includes('/tile/'));
   if(!tile)return false;
   const imgs=[...tile.parentElement.querySelectorAll('img')].filter(i=>{const b=i.getBoundingClientRect();return i.src.includes('/tile/')&&b.right>0&&b.left<r.width&&b.bottom>0&&b.top<r.height});
   return imgs.length>0&&imgs.every(i=>i.complete&&i.naturalWidth>0);
  },undefined,{timeout:25000});
  await page.waitForTimeout(120);
  const image=await page.locator('#map').screenshot({type:'png'});
  const elapsed=performance.now()-start;
  const visible=await page.evaluate(()=>{
   const map=document.getElementById('map'),labels=[...map.querySelectorAll('.badge')].map(e=>{const r=e.getBoundingClientRect();return {text:e.textContent,x:r.x,y:r.y,width:r.width,height:r.height}});
   return {labels,text:map.innerText,loadedTiles:[...map.querySelectorAll('img')].filter(i=>i.src.includes('/tile/')&&i.naturalWidth>0).length};
  });
  if(geometry.circlePixels.some(p=>p.x<0||p.x>1200||p.y<45||p.y>590))throw Error('Radius clipped: '+data.id);
  if(geometry.groups.flatMap(g=>g.ids).sort().join('|')!==data.facilities.map(f=>f.id).sort().join('|'))throw Error('Map target mismatch');
  if(visible.labels.some(b=>b.x<0||b.y<0||b.x+b.width>1200||b.y+b.height>590))throw Error('Number badge clipped');
  if(visible.labels.some((a,i)=>visible.labels.slice(i+1).some(b=>a.x<b.x+b.width&&a.x+a.width>b.x&&a.y<b.y+b.height&&a.y+a.height>b.y)))throw Error('Overlapping map numbers');
  const imagePath=path.join(out,data.id+'.png');await fs.writeFile(imagePath,image);
  const memory=await rssSample();
  records.push({id:data.id,synthetic:data.synthetic,facilityCount:data.facilities.length,summary:data.summary,geometry,visible,captureMs:Math.round(elapsed),pngBytes:image.length,pngSha256:createHash('sha256').update(image).digest('hex'),browserRssMiB:Math.round(memory.rssMiB),browserPssMiB:Math.round(memory.pssMiB)});
  await fs.writeFile(path.join(out,data.id+'.json'),JSON.stringify({...data,...records.at(-1)},null,2));
  console.log(data.id,data.facilities.length,'facilities',Math.round(elapsed)+'ms');
  await context.close();
 }
} finally {
 clearInterval(monitor);await browser.close();
 await fs.writeFile(path.join(out,'capture-results.json'),JSON.stringify({scope:'Development HTML response overrides at the owned registered origin; real Kakao SDK/tiles via HTTPS proxy with TLS verification. No production app/API calls or deployment.',launchMs:Math.round(launchMs),peakBrowserRssMiB:Math.round(peakRssMiB),peakBrowserPssMiB:Math.round(peakPssMiB),records,requests,failures,errors,forbidden},null,2));
}
console.log('Output:',out);if(errors.length||forbidden.length||requests.some(r=>r.status>=400))process.exitCode=1;
