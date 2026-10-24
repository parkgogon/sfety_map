import {chromium} from '/opt/codex/cua_node/lib/node_modules/playwright-core/index.mjs';
import fs from 'node:fs/promises';
const dir='/workspace/improvement-checks/weather';await fs.mkdir(dir,{recursive:true});
const browser=await chromium.launch({executablePath:'/usr/bin/chromium',headless:true,args:['--no-sandbox'],proxy:{server:process.env.HTTPS_PROXY,bypass:'localhost,127.0.0.1'}});
const errors=[],results=[];
for(const [width,height] of [[1440,960],[390,844]]){
 const page=await browser.newPage({viewport:{width,height}});page.on('pageerror',e=>errors.push(e.message));
 await page.goto('http://127.0.0.1:5174/design/weather/');await page.waitForFunction(()=>window.weatherPreview);
 await page.waitForTimeout(1300);
 for(const layer of ['wind','temperature','rainfall']){
  await page.locator(`[data-layer="${layer}"]`).click();
  if(width===390)await page.locator('[data-tab=B]').click();
  await page.screenshot({path:dir+`/${layer}-${width}.png`,fullPage:true});
 }
 await page.locator('[data-layer=wind]').click();
 await page.locator('[data-speed="0"]').click();await page.waitForTimeout(100);results.push({width,calm:await page.evaluate(()=>window.weatherPreview.state())});
 await page.locator('[data-speed="0.5"]').click();
 const selected=width===390?'B':'A';
 await page.locator(`[data-option="${selected}"] [data-zoom="1"]`).click();
 let state=await page.evaluate(()=>window.weatherPreview.state());if(state.zoom<=1)throw Error('줌 동작 실패');
 const map=page.locator(`[data-option="${selected}"] .map`),box=await map.boundingBox();
 await page.mouse.move(box.x+box.width/2,box.y+box.height/2);await page.mouse.down();await page.mouse.move(box.x+box.width/2+35,box.y+box.height/2+20,{steps:5});await page.mouse.up();
 state=await page.evaluate(()=>window.weatherPreview.state());if(state.pan.x<30)throw Error('이동 동작 실패');
 await page.locator('summary').click();await page.locator('#facility-card').check();
 const card=await page.locator(`[data-option="${selected}"] .facility-card`).boundingBox();const legend=await page.locator(`[data-option="${selected}"] .legend`).boundingBox();if(card.y+card.height>=legend.y)throw Error('시설 카드와 범례 겹침');
 await page.screenshot({path:dir+`/card-${width}.png`,fullPage:true});await page.locator('#reduced').check();
 state=await page.evaluate(()=>window.weatherPreview.state());if(!state.reduced)throw Error('움직임 줄이기 실패');
 const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth);if(overflow)throw Error('가로 넘침');results.push({width,interaction:state,overflow});
 await page.close();
}
await fs.writeFile(dir+'/results.json',JSON.stringify({results,errors,scope:'Synthetic data + self-authored schematic; no SDK or production validation'},null,2));await browser.close();console.log({results:results.length,errors});if(errors.length)process.exitCode=1;
