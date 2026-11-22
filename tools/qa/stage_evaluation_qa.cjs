'use strict';
const {spawn}=require('node:child_process');
const path=require('node:path');
const fs=require('node:fs');
const net=require('node:net');
const assert=require('node:assert/strict');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE || 'playwright-core');
const root=path.resolve(__dirname,'../..'), appRoot=path.join(root,'delivery/app');
const out=path.join(appRoot,'outputs/stage_ui_20261102_'+Date.now());
const delay=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function main(){
  fs.mkdirSync(out,{recursive:true});
  const socket=net.createServer();
  await new Promise(resolve=>socket.listen(0,'127.0.0.1',resolve));
  const port=socket.address().port;await new Promise(resolve=>socket.close(resolve));
  const origin=`http://127.0.0.1:${port}`;
  const service=spawn(path.join(root,'delivery/runtime/training_env/Scripts/python.exe'),['-X','utf8','-B','-m','uvicorn','llm_shield.server:app','--host','127.0.0.1','--port',String(port)],{
    cwd:appRoot,windowsHide:true,stdio:['ignore','ignore','pipe'],env:{...process.env,LLM_MODE:'mock',SHIELD_USE_GLINER:'true',SHIELD_DETECTOR_MODE:'gliner',
      SHIELD_GLINER_MODEL_DIR:path.join(appRoot,'models/gliner_official_multi_v2.1'),
      SHIELD_ACTION_MODEL_PATH:path.join(appRoot,'models/necessity_action.joblib'),
      SHIELD_UPLOAD_DIR:path.join(out,'uploads'),HF_HUB_OFFLINE:'1',TRANSFORMERS_OFFLINE:'1',TOKENIZERS_PARALLELISM:'false',PYTHONDONTWRITEBYTECODE:'1',OMP_NUM_THREADS:'4'}});
  const log=fs.createWriteStream(path.join(out,'service.log'));service.stderr.pipe(log);
  let browser;
  const result={gliner_profile:'official_multi_v2.1',generation:'mock',external_requests:[],page_errors:[],viewports:[]};
  try{
    let ready=false;
    for(let i=0;i<150;i++){
      if(service.exitCode!==null)throw Error('Service exited');
      try{const response=await fetch(origin+'/api/health',{signal:AbortSignal.timeout(1500)});const state=await response.json();if(state.ready_local){result.health=state;ready=true;break;}}catch{}
      await delay(500);
    }
    assert(ready,'Local official model service did not become ready');
    assert(result.health.gliner_enabled);assert.equal(result.health.llm_mode,'mock');
    browser=await chromium.launch({headless:true,executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'});
    const context=await browser.newContext();
    await context.route('**/*',route=>{const url=new URL(route.request().url());if(url.origin===origin)return route.continue();result.external_requests.push(url.origin);return route.abort();});
    const page=await context.newPage();page.on('pageerror',error=>result.page_errors.push(error.message));
    for(const width of [1440,768,390]){
      await page.setViewportSize({width,height:1000});await page.goto(origin+'/evaluation');
      await page.waitForSelector('#report:not([hidden])');
      assert.equal(await page.locator('#stageRows tr').count(),10);
      assert.equal(await page.locator('#policyRows tr').count(),5);
      assert((await page.locator('#weaknesses').innerText()).includes('0/6'));
      assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'Document overflow');
      await page.screenshot({path:path.join(out,`evaluation-${width}.png`),fullPage:true});
      result.viewports.push({width,overflow:false});
    }
    await page.selectOption('#nerConfig','gliner_semantic');await page.selectOption('#nerMode','cover');
    assert((await page.locator('#nerTotals').innerText()).includes('0.7676'));
    await page.goto(origin+'/');await page.waitForFunction(()=>!document.getElementById('send').disabled || document.querySelector('#modelStatus').textContent.includes('就绪'));
    await page.locator('#message').fill('负责人：张明。电话13900001234。任务是整理器材，期限是周五。请整理会议纪要。');
    const pending=page.waitForResponse(response=>response.url().includes('/messages')&&response.request().method()==='POST');
    await page.locator('#send').click();const turn=await (await pending).json();
    assert(Array.isArray(turn.stages)&&turn.stages.length===8);
    assert(!JSON.stringify(turn).includes('13900001234'),'Phone canary exposed in response');
    assert.equal(await page.locator('#stageTrace li').count(),8);
    await page.locator('#processing').evaluate(node=>node.open=true);
    await page.screenshot({path:path.join(out,'chat-stages-390.png'),fullPage:true});
    result.chat={ok:turn.ok,paused:turn.paused,engine:turn.engine||null,stages:turn.stages};
    assert.deepEqual(result.page_errors,[]);assert.deepEqual(result.external_requests,[]);
    result.passed=true;
  }finally{
    if(browser)await browser.close();service.kill();log.end();
    fs.writeFileSync(path.join(out,'summary.json'),JSON.stringify(result,null,2));
    console.log(JSON.stringify({out,...result},null,2));
  }
}
main().catch(error=>{console.error(error);process.exitCode=1;});
