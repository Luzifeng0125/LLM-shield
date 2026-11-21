"use strict";
// Software QA only: mock generation, rule detectors, isolated synthetic uploads.
const {spawn} = require('node:child_process');
const fs = require('node:fs');
const {createHash} = require('node:crypto');
const path = require('node:path');
const net = require('node:net');
const {pathToFileURL} = require('node:url');
const assert = require('node:assert/strict');
const {chromium} = require('C:/Users/nicholas/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright-core');
const root = path.resolve(__dirname, '../..');
const appRoot = path.join(root, 'delivery/app');
const nameIndex = process.argv.indexOf('--out-name');
const outName = nameIndex >= 0 ? process.argv[nameIndex+1] : 'browser';
assert(/^[a-z0-9_-]+$/i.test(outName), 'Invalid output name');
const out = path.join(appRoot, 'outputs/continuation_20261026', outName);
const python = path.join(root, 'delivery/runtime/training_env/Scripts/python.exe');
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));

async function freePort() {
  const server = net.createServer();
  await new Promise((resolve, reject) => {server.once('error', reject); server.listen(0, '127.0.0.1', resolve);});
  const port = server.address().port;
  await new Promise(resolve => server.close(resolve));
  return port;
}

async function main() {
  assert(!fs.existsSync(out), 'Use a new output directory; do not overwrite QA evidence');
  fs.mkdirSync(out, {recursive:true});
  const port = await freePort(), origin = `http://127.0.0.1:${port}`;
  const app = spawn(python, ['-B','-X','utf8','-m','uvicorn','llm_shield.server:app','--host','127.0.0.1','--port',String(port)], {
    cwd:appRoot, windowsHide:true, stdio:['ignore','ignore','pipe'],
    env:{...process.env, LLM_MODE:'mock', SHIELD_USE_GLINER:'false',
         SHIELD_MODEL_DIR:path.join(appRoot,'models'),
         SHIELD_ACTION_MODEL_PATH:path.join(appRoot,'models/necessity_action.joblib'),
         SHIELD_UPLOAD_DIR:path.join(out,'uploads'), PYTHONDONTWRITEBYTECODE:'1'}
  });
  let browser, sessionId, stage='startup', ready=false;
  const uploaded=[], external=[], errors=[];
  const result={mode:'mock',detectors:'rules_only_not_real_gliner',human_reviews_created:0,
    code_hashes:Object.fromEntries([
      'web/style.css','web/chat.css','web/chat.js','llm_shield/server.py',
      'llm_shield/chat.py','llm_shield/pipeline.py','llm_shield/material_policy.py',
      'llm_shield/m1_access/loader.py','llm_shield/m1_access/file_loader.py','llm_shield/m7_egress/gateway.py'
    ].map(name=>[name,createHash('sha256').update(fs.readFileSync(path.join(appRoot,name))).digest('hex')]))};
  try {
    for(let n=0;n<100;n++) {
      if(app.exitCode!==null) throw Error('QA service exited');
      try {
        const response=await fetch(origin+'/api/health');
        const health=await response.json();
        if(health.ready_local){assert.equal(health.llm_mode,'mock');assert.equal(health.gliner_enabled,false);ready=true;break;}
      } catch(error) {if(error.code==='ERR_ASSERTION')throw error;}
      await delay(300);
    }
    assert(ready,'QA service did not become ready');
    browser=await chromium.launch({headless:true,executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'});
    const context=await browser.newContext({viewport:{width:1440,height:1000}});
    await context.route('**/*', route=>{
      const url=new URL(route.request().url());
      if(url.origin===origin||url.protocol==='file:')return route.continue();
      external.push(url.origin);return route.abort();
    });
    const page=await context.newPage();
    page.on('pageerror',error=>errors.push(error.name));
    stage='chat_upload';
    await page.goto(origin+'/');
    await page.waitForFunction(()=>!document.getElementById('uploadBtn').classList.contains('is-disabled'));
    assert.equal(await page.locator('#uploadStorage').inputValue(),'temporary');
    let pending=page.waitForResponse(r=>r.url().endsWith('/api/upload')&&r.request().method()==='POST');
    await page.locator('#file').setInputFiles({name:'qa-temporary.txt',mimeType:'text/plain',
      buffer:Buffer.from('负责人：张明。任务：布置会场。期限：周五。电话13812345678。')});
    let upload=await (await pending).json();uploaded.push(upload.doc_id);
    assert.equal(upload.storage_mode,'temporary');assert(upload.expires_at);
    assert.deepEqual(upload.allowed_purposes,['meeting_minutes']);
    await page.waitForFunction(()=>!document.getElementById('send').disabled);
    await page.locator('#uploadStorage').selectOption('library');
    pending=page.waitForResponse(r=>r.url().endsWith('/api/upload')&&r.request().method()==='POST');
    await page.locator('#file').setInputFiles({name:'qa-library.txt',mimeType:'text/plain',buffer:Buffer.from('本周会议讨论公开的活动安排。')});
    upload=await (await pending).json();uploaded.push(upload.doc_id);
    assert.equal(upload.storage_mode,'library');assert.equal(upload.expires_at,null);
    stage='chat_generation';
    const sessionResponse=page.waitForResponse(r=>r.url().endsWith('/api/chat/sessions')&&r.request().method()==='POST');
    await page.locator('#message').fill('请整理会议纪要。');
    await page.locator('#send').click();
    sessionId=(await (await sessionResponse).json()).session_id;
    await page.waitForFunction(()=>document.getElementById('turns').textContent==='1 / 20');
    const visible=await page.locator('#messages').innerText();
    assert(!visible.includes('张明')&&!visible.includes('13812345678'));
    const history=await (await fetch(origin+'/api/chat/'+sessionId)).text();
    assert(!history.includes('张明')&&!history.includes('13812345678'));
    result.chat_upload_and_generation=true;
    result.upload_storage_choices=true;
    result.chat_layouts=[];
    for(const width of [320,360,390,768,1440]) {
      await page.setViewportSize({width,height:1000});
      if(await page.locator('.chat-layout').evaluate(e=>e.classList.contains('rail-collapsed')))
        await page.locator('#railToggle').click();
      await page.locator('#task').scrollIntoViewIfNeeded();
      if(await page.locator('#task').isEnabled())await page.locator('#task').click({trial:true});
      const contentWidth=await page.evaluate(()=>document.documentElement.scrollWidth);
      if(contentWidth>width) {
        await page.screenshot({path:path.join(out,`overflow-${width}.png`),fullPage:true});
        fs.writeFileSync(path.join(out,`overflow-${width}.json`),JSON.stringify(await page.evaluate(()=>
          [...document.querySelectorAll('body *')].filter(e=>{const r=e.getBoundingClientRect();return r.width&&r.right>innerWidth+1;})
            .map(e=>({tag:e.tagName,class:e.className,id:e.id,width:e.getBoundingClientRect().width,right:e.getBoundingClientRect().right}))),null,2));
      }
      assert(contentWidth<=width,'Chat has horizontal overflow');
      const heading=await page.locator('.brand h1').boundingBox();
      assert(heading.height<30,'Brand title wrapped vertically');
      const turns=await page.locator('#turns').boundingBox();
      const turnsLineHeight=await page.locator('#turns').evaluate(e=>Number.parseFloat(getComputedStyle(e).lineHeight));
      assert(turns.height<=turnsLineHeight+1,`Turn label wrapped vertically at ${width}: ${turns.height}/${turnsLineHeight}`);
      const nav=await page.locator('.topbar > a').boundingBox();
      assert(nav && nav.x>=0 && nav.x+nav.width<=width,'Notice link escaped viewport');
      await page.locator('#railToggle').click();
      await page.waitForTimeout(250);
      assert(await page.evaluate(()=>document.documentElement.scrollWidth)<=width,'Collapsed rail overflow');
      await page.locator('#railToggle').click();
      await page.waitForTimeout(250);
      result.chat_layouts.push({width,contentWidth});
      await page.screenshot({path:path.join(out,`chat-${width}.png`),fullPage:true});
    }
    await page.setViewportSize({width:1440,height:1000});
    await page.locator('#clearChat').click();
    await page.getByRole('button',{name:'确认清除',exact:true}).click();
    await page.waitForFunction(()=>document.getElementById('turns').textContent==='0 / 20');
    assert.equal((await fetch(origin+'/api/chat/'+sessionId)).status,404);
    result.clear_chat=true;

    stage='notice';
    await page.goto(origin+'/notice');
    await page.waitForFunction(()=>!document.getElementById('draftButton').disabled);
    await page.locator('#roster').fill('测试电话13812345678，邮箱qa@example.invalid');
    await page.locator('#reviewButton').click();
    await page.waitForFunction(()=>document.querySelectorAll('#reviewRows tr').length>=2);
    await page.locator('#activityName').fill('校园交流日');
    const draftResponse=page.waitForResponse(r=>r.url().endsWith('/api/notice/draft'));
    await page.locator('#draftButton').click();
    const draft=await (await draftResponse).text();
    assert(!draft.includes('13812345678')&&!draft.includes('qa@example.invalid'));
    await page.waitForFunction(()=>document.getElementById('draft').textContent.includes('模拟'));
    await page.locator('#clearRoster').click();
    assert.equal(await page.locator('#roster').inputValue(),'');
    result.notice_layouts=[];
    for(const width of [1440,390]) {
      await page.setViewportSize({width,height:1000});
      const contentWidth=await page.evaluate(()=>document.documentElement.scrollWidth);
      assert(contentWidth<=width,'Notice has horizontal overflow');
      result.notice_layouts.push({width,contentWidth});
      await page.screenshot({path:path.join(out,`notice-${width}.png`),fullPage:true});
    }
    result.notice_public_input_only=true;

    stage='review_form';
    await page.goto(pathToFileURL(path.join(appRoot,'scripts/action_review.html')).href);
    await page.locator('#taskFile').setInputFiles(path.join(root,'research/datasets/legacy/任务必要性复核_20261026_v2/review-first-batch.json'));
    await page.waitForFunction(()=>!document.getElementById('work').hidden);
    assert((await page.locator('#progress').innerText()).includes('/ 28'));
    await page.locator('#reviewer').fill('AUTOMATED_UI_TEST_NOT_A_HUMAN');
    await page.locator('#representation').selectOption('none');
    await page.locator('#action').selectOption('DELETE');
    await page.locator('#facts').fill('仅用于界面自动化测试');
    await page.locator('#reason').fill('自动化测试不构成人工标注');
    await page.locator('#save').click();
    const downloaded=page.waitForEvent('download');
    await page.locator('#export').click();
    const download=await downloaded, stream=await download.createReadStream(), chunks=[];
    for await(const chunk of stream)chunks.push(chunk);
    const exported=JSON.parse(Buffer.concat(chunks).toString());
    assert.equal(exported.reviewer,'AUTOMATED_UI_TEST_NOT_A_HUMAN');
    assert.equal(exported.reviews.length,1);
    await download.delete(); // No test answer is placed in the actual human review folder.
    result.review_form_load_save_export=true;
    assert.deepEqual(errors,[]);assert.deepEqual(external,[]);
    result.status='passed';result.external_browser_requests=0;result.javascript_errors=[];
    fs.writeFileSync(path.join(out,'summary.json'),JSON.stringify(result,null,2)+'\n');
    console.log(JSON.stringify(result));
  } catch(error) {
    fs.writeFileSync(path.join(out,'failure.json'),JSON.stringify({status:'failed',stage,error:error.name,reason:error.message},null,2));
    throw error;
  } finally {
    for(const id of uploaded)await fetch(origin+'/api/upload/'+encodeURIComponent(id),{method:'DELETE'}).catch(()=>{});
    if(browser)await browser.close();
    app.kill();
  }
}
main().catch(error=>{console.error(error.message);process.exitCode=1;});
