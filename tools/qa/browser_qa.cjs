const {spawn} = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const {chromium} = require('C:/Users/nicholas/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright-core');
const root = path.resolve(__dirname, '../../隐盾整合交付_20261012');
const screenshots = path.join(root, '验证结果/界面截图');
fs.mkdirSync(screenshots, {recursive:true});
const portablePython = path.join(root, 'runtime/python/python.exe');
const python = fs.existsSync(portablePython) ? portablePython : path.join(root, 'app/.venv/Scripts/python.exe');
const origin = 'http://127.0.0.1:8798';
const app = spawn(python, ['-B','-X','utf8','run.py','--host','127.0.0.1','--port','8798'], {
  cwd: root + '/app', env: {...process.env, LLM_MODE: 'mock'}, windowsHide: true, stdio: 'pipe'
});
let browser, uploaded, sessionId;
let logs = '';
app.stderr.on('data', b => logs += b.toString());
const sleep = ms => new Promise(r => setTimeout(r,ms));
(async () => {
  try {
    let ready = false;
    for (let n=0;n<60;n++) {
      try { if ((await fetch(origin + '/api/config')).ok) {ready=true;break;} } catch {}
      await sleep(500);
    }
    assert(ready, 'Portable server did not start: ' + logs);
    browser = await chromium.launch({executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true});
    const page = await browser.newPage({viewport:{width:1440,height:1050}});
    const errors=[];
    page.on('pageerror', e=>errors.push(e.message));
    page.on('response', async r => {
      if (r.url().endsWith('/api/chat/sessions') && r.request().method()==='POST' && r.ok()) sessionId=(await r.json()).session_id;
      if (r.url().endsWith('/api/upload') && r.request().method()==='POST' && r.ok()) uploaded=(await r.json()).doc_id;
    });
    await page.goto(origin+'/chat');
    await page.waitForFunction(()=>document.querySelector('#modelStatus').textContent.includes('已就绪'));
    assert.equal(page.url(),origin+'/');
    assert((await page.locator('#apiStatus').innerText()).includes('未调用真实 API'));
    await page.locator('#file').setInputFiles({name:'browser_test.txt',mimeType:'text/plain',buffer:Buffer.from('负责人：张明，期限：2026年10月20日，电话13812345678。请整理会议纪要。')});
    await page.waitForFunction(()=>document.querySelector('#attachments').textContent.includes('browser_test.txt'));
    // 新版把「移出本轮」简化为「移出」（所在分组已表达「本轮」语义）
    await page.getByRole('button',{name:'移出',exact:true}).click();
    assert.equal(await page.locator('#attachments').innerText(),'');
    // 文件库里「加入本轮」由 button 改成了 iOS 拨动开关（role=switch），
    // getByRole('button') 再也匹配不到；aria-label 形如 将「<文件名>」加入本轮。
    await page.getByRole('switch',{name:/加入本轮/}).check();
    await page.locator('#send').click();
    // 轮次标签去掉冗余的「轮」字（进度条已表达同一含义）
    await page.waitForFunction(()=>document.querySelector('#turns').textContent==='1 / 20');
    await page.locator('#message').fill('负责人：张明。任务：海报设计，期限：2026年10月20日。');
    await page.locator('#send').click();
    await page.waitForFunction(()=>document.querySelector('#turns').textContent==='2 / 20');
    const safeText=await page.locator('#messages').innerText();
    assert(!safeText.includes('张明') && !safeText.includes('13812345678'));
    assert.equal(await page.locator('.chat-message').count(),4);
    assert((await page.locator('#apiStatus').innerText()).includes('离线演示'));
    assert(await page.locator('#identity').isDisabled());
    assert(await page.locator('#processing').isVisible());
    await page.screenshot({path:path.join(screenshots,'chat-desktop.png'),fullPage:true});
    await page.setViewportSize({width:390,height:844});
    assert(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth));
    await page.screenshot({path:path.join(screenshots,'chat-mobile.png'),fullPage:true});
    // Simulate expiry by removing the current session on the server, then recreate from the page.
    assert(sessionId);
    await fetch(origin+'/api/chat/'+sessionId,{method:'DELETE'});
    await page.locator('#newChat').click();
    await page.waitForFunction(()=>document.querySelector('#turns').textContent==='0 / 20' && document.querySelector('#notice').textContent.includes('新对话已准备好'));
    assert(await page.locator('#identity').isEnabled());
    await page.locator('#clearChat').click();
    await page.waitForFunction(()=>document.querySelector('#notice').textContent.includes('代号映射已清除'));
    // 新版删除本机材料改成「先弹确认框再删」的两步操作：
    // 材料行按钮的 aria-label 是 删除「<文件名>」，确认框主按钮文案是「删除」。
    await page.getByRole('button',{name:/^删除「/}).click();
    await page.getByRole('button',{name:'删除',exact:true}).click();
    await page.waitForFunction(()=>document.querySelector('#library').textContent.includes('还没有文件'));
    await page.goto(origin+'/');
    assert.equal(await page.locator('a[href="/chat"]').count(),0);
    assert.deepEqual(errors,[]);
    const result={portable_server_started:true,single_conversation_entry:true,attachment_and_two_turns:true,remove_and_readd_attachment:true,delete_local_material:true,api_status_explicit:true,sensitive_values_absent_in_visible_history:true,mobile_no_horizontal_overflow:true,recreate_after_session_expiry:true,clear_session:true,javascript_errors:errors,mode:'mock'};
    fs.writeFileSync(root+'/验证结果/网页交互检查.json',JSON.stringify(result,null,2),'utf8');
    console.log(JSON.stringify(result));
  } finally {
    if (uploaded) await fetch(origin+'/api/upload/'+uploaded,{method:'DELETE'}).catch(()=>{});
    if (browser) await browser.close();
    app.kill();
  }
})().catch(error=>{console.error(error);process.exitCode=1;});
