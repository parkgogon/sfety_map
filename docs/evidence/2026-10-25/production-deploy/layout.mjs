import fs from 'node:fs/promises';
import path from 'node:path';
const {chromium}=await import('/opt/codex/cua_node/lib/node_modules/playwright-core/index.mjs');
const out='/workspace/production-deploy-check',origin='https://keco-safety-map.web.app';
const browser=await chromium.launch({executablePath:'/usr/bin/chromium',headless:true,proxy:{server:process.env.HTTPS_PROXY},args:['--no-sandbox']});
const records=[],errors=[],blocked=[];
try{
 for(const width of [360,390,430,700,1440])for(const app of ['control','settings']){
  const c=await browser.newContext({viewport:{width,height:900},locale:'ko-KR',timezoneId:'Asia/Seoul'});
  await c.route('**/*',route=>{
   const q=route.request(),u=new URL(q.url());
   if(q.method()!=='GET'||/\/(dispatch|worker|notifications|send|test)(\/|$)/i.test(u.pathname)){blocked.push({host:u.hostname,path:u.pathname,method:q.method()});return route.abort()}
   return route.continue();
  });
  const p=await c.newPage();p.on('pageerror',e=>errors.push({app,width,message:e.message.replace(/https?:\/\/[^\s)]+/g,'[URL]')}));
  await p.goto(origin+'/'+app);
  await p.getByRole('heading',{name:app==='control'?'중앙 관제':'관리자 인증이 필요합니다',exact:true}).waitFor();
  await p.waitForTimeout(250);
  const r=await p.evaluate(()=>{
   const icon=document.querySelector('[aria-label="관제 자료 새로고침"]'),button=document.querySelector('.login-form button'),input=document.querySelector('.login-form input');
   return {overflow:document.documentElement.scrollWidth>innerWidth,refreshColor:icon?getComputedStyle(icon).color:null,refreshBackground:icon?getComputedStyle(icon).backgroundColor:null,
    login:button?{text:button.textContent,whiteSpace:getComputedStyle(button).whiteSpace,buttonInViewport:button.getBoundingClientRect().right<=innerWidth,inputInViewport:input.getBoundingClientRect().right<=innerWidth}:null};
  });
  if(r.overflow)throw Error('Overflow '+app+' '+width);
  if(app==='control'&&r.refreshColor==='rgb(255, 255, 255)')throw Error('White refresh');
  if(r.login&&(!r.login.buttonInViewport||!r.login.inputInViewport||r.login.whiteSpace!=='nowrap'))throw Error('Login layout');
  await p.screenshot({path:path.join(out,`${app}-layout-${width}.png`)});records.push({app,width,...r});await c.close();
  console.log(app,width,'passed');
 }
}finally{await browser.close();await fs.writeFile(path.join(out,'layout-checks.json'),JSON.stringify({scope:'Actual production unauthenticated UI; viewport emulation.',records,errors,blocked},null,2))}
if(errors.length||blocked.length)process.exitCode=1;
