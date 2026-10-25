// Local comparison-gallery layout check; viewport emulation, not physical-device review.
import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
const {chromium}=await import(process.env.PLAYWRIGHT_MODULE || '/opt/codex/cua_node/lib/node_modules/playwright-core/index.mjs');
const root=fileURLToPath(new URL('../../',import.meta.url));
const directory=path.join(root,'docs/evidence/2026-10-25/nearby-preview');
const origin='https://keco-safety-map.web.app';
const allowed=new Set(['index.html','urban-5km-before-page1.png','urban-5km-after-page1.png']);
if(!process.env.HTTPS_PROXY)throw Error('Preserve HTTPS_PROXY');
const browser=await chromium.launch({executablePath:process.env.CHROMIUM_EXECUTABLE || '/usr/bin/chromium',headless:true,proxy:{server:process.env.HTTPS_PROXY},args:['--no-sandbox']});
const records=[],errors=[];
try{
 for(const width of [1440,390]){
  const page=await browser.newPage({viewport:{width,height:1000}});
  page.on('pageerror',e=>errors.push(e.message));
  await page.route('**/*',async route=>{
   const url=new URL(route.request().url()),name=url.pathname.split('/').at(-1);
   if(route.request().method()!=='GET'||url.origin!==origin)return route.abort();
   if(name==='favicon.ico')return route.fulfill({status:204,body:''});
   if(!url.pathname.startsWith('/__nearby-gallery/')||!allowed.has(name))return route.abort();
   return route.fulfill({status:200,contentType:name.endsWith('.html')?'text/html':'image/png',body:await fs.readFile(path.join(directory,name))});
  });
  await page.goto(origin+'/__nearby-gallery/index.html');
  await page.waitForFunction(()=>[...document.images].every(i=>i.complete&&i.naturalWidth>0));
  const check=await page.evaluate(()=>({horizontalOverflow:document.documentElement.scrollWidth>innerWidth,images:[...document.images].length,pdfLinks:[...document.querySelectorAll('a[href$=".pdf"]')].length}));
  if(check.horizontalOverflow||check.images!==2||check.pdfLinks<5)throw Error('Comparison gallery layout failed');
  records.push({width,...check});
  await page.screenshot({path:path.join(directory,`comparison-${width}.png`),fullPage:true});
  await page.close();
 }
}finally{await browser.close()}
await fs.writeFile(path.join(directory,'gallery-checks.json'),JSON.stringify({scope:'Local HTML/image response overrides at owned origin, no external requests. Viewport emulation only.',records,errors},null,2));
if(errors.length)process.exitCode=1;
console.log(JSON.stringify({records,errors}));
