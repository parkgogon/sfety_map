import { chromium } from '/opt/codex/cua_node/lib/node_modules/playwright-core/index.mjs';
import fs from 'node:fs/promises';
const dir='/workspace/improvement-checks/report';await fs.mkdir(dir,{recursive:true});
const browser=await chromium.launch({executablePath:'/usr/bin/chromium',headless:true,args:['--no-sandbox'],proxy:{server:process.env.HTTPS_PROXY,bypass:'localhost,127.0.0.1'}});
const results=[];const errors=[];
for(const path of ['/', '/control'])for(const [width,height] of [[360,740],[390,844],[430,932],[700,700],[1440,900]]){
 const context=await browser.newContext({viewport:{width,height},acceptDownloads:true});
 await context.addInitScript({path:'/workspace/improvement-checks/fake-sdk.js'});
 await context.route('**/*',route=>{const u=new URL(route.request().url());if(['127.0.0.1','localhost'].includes(u.hostname))route.continue();else route.abort()});
 const page=await context.newPage();page.on('pageerror',e=>errors.push({path,width,error:e.message}));
 await page.goto('http://127.0.0.1:8765'+path);await page.waitForSelector('.app-shell, .control-shell');
 const mobile=path==='/'&&width<=700;if(path==='/control')await page.getByRole('button',{name:'대상 분석·전파',exact:true}).click();
 if(mobile){await page.getByLabel('시설·장소·주소 검색',{exact:true}).click();await page.getByRole('tab',{name:'장소·주소',exact:true}).click()}
 else await page.getByRole('button',{name:path==='/control'?'장소·주소 / 주변 시설':'장소·주소',exact:true}).click();
 await page.getByRole('textbox',{name:'장소명 또는 주소',exact:true}).fill('검수 지점');await page.getByRole('button',{name:'검색',exact:true}).click();
 await page.getByRole('button',{name:/동인청사 인근 검수 기준점/}).click();
 if(await page.getByRole('button',{name:'주변 시설 보고서',exact:true}).count())throw Error('미확정 기준점에 보고서 버튼');
 await page.getByRole('button',{name:mobile?'이곳으로 지정':'이곳을 기준점으로 지정',exact:true}).click();
 await page.getByRole('button',{name:'주변 시설 보고서',exact:true}).click();
 const dialog=page.getByRole('dialog',{name:'주변 시설 보고서',exact:true});await dialog.waitFor();
 await dialog.getByText('반경 5km · 대상 3개소').waitFor();
 await dialog.getByRole('button',{name:'1km',exact:true}).click();await dialog.getByText('0개소 보고서를 생성합니다.',{exact:false}).waitFor();
 if(width===390&&path==='/'){
  const download=page.waitForEvent('download');await dialog.getByRole('button',{name:'PDF 생성',exact:true}).click();await (await download).saveAs(dir+'/zero.pdf');
 }
 await dialog.getByRole('spinbutton',{name:'직접 입력 (km)',exact:true}).fill('0.15');
 if(await dialog.getByRole('button',{name:'PDF 생성',exact:true}).isEnabled())throw Error('비정상 반경 허용');
 await dialog.getByRole('button',{name:'5km',exact:true}).click();
 const screenshot=dir+`/${path==='/control'?'control':'field'}-${width}.png`;await page.screenshot({path:screenshot});
 if((width===390&&path==='/')||(width===1440&&path==='/control')){
 const download=page.waitForEvent('download');await dialog.getByRole('button',{name:'PDF 생성',exact:true}).click();await (await download).saveAs(dir+`/${path==='/control'?'control':'field'}-5km.pdf`);
 }
 const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth);
 const rect=await dialog.boundingBox();if(overflow||rect.x<0||rect.x+rect.width>width+.5)throw Error('가로 넘침');
 await page.keyboard.press('Escape');await dialog.waitFor({state:'detached'});
 const focused=await page.evaluate(()=>document.activeElement?.hasAttribute('data-nearby-report-trigger'));if(!focused)throw Error('포커스 미복원 '+path+width);
 console.log(path,width,"passed");results.push({path,width,height,count:3,zeroCount:0,invalidRejected:true,focusRestored:focused,overflow});await context.close();
}
await fs.writeFile(dir+'/results.json',JSON.stringify({environment:'LOCAL fixed API + fake map SDK; not production or physical devices',results,errors},null,2));
await browser.close();console.log(JSON.stringify({checks:results.length,errors}));if(errors.length)process.exitCode=1;
