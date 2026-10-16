// Optional local software QA; never a human review.
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'C:/Users/nicholas/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright-core');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {pathToFileURL}=require('node:url');const root=path.resolve(__dirname,'..');
const read=p=>fs.readFileSync(p,'utf8').trim().split(/\r?\n/).map(x=>JSON.parse(x));
(async()=>{const browser=await chromium.launch({executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true});
try{const page=await browser.newPage({viewport:{width:1280,height:1000},acceptDownloads:true});const errors=[],requests=[];let views=0;
page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>{if(/^https?:/.test(r.url()))requests.push(r.url())});page.on('dialog',d=>d.dismiss());
for(const batch of fs.readdirSync(path.join(root,'批次'))){for(const who of ['A','B']){const folder=path.join(root,'批次',batch,'复核员'+who),rows=read(path.join(folder,'空白复核表.jsonl'));
await page.goto(pathToFileURL(path.join(folder,'打开复核.html')).href);assert.equal(await page.locator('#jump option').count(),rows.length);
for(let i=0;i<rows.length;i++){await page.locator('#jump').selectOption(String(i));assert((await page.locator('#record').innerText()).includes(rows[i].id));views++;}
}}
const folder=path.join(root,'批次','01_训练试标','复核员A');await page.goto(pathToFileURL(path.join(folder,'打开复核.html')).href);
const original=read(path.join(folder,'空白复核表.jsonl'));const first=read(path.join(root,'裁决员专用','01_训练试标','机器建议勿提前给AB.jsonl'))[0].entities[0];
await page.locator('textarea.source').evaluate((el,entity)=>{el.focus();el.setSelectionRange(entity.start,entity.end)},first);
await page.getByRole('button',{name:'添加所选实体'}).click();assert((await page.locator('.entity').innerText()).includes(first.text));
await page.getByRole('checkbox',{name:'确认本条全部标注已完成'}).check();assert((await page.locator('#status').innerText()).includes('1/128'));
const dl=page.waitForEvent('download');await page.locator('#save').click();const download=await dl;const qa=path.join(root,'qa');fs.mkdirSync(qa,{recursive:true});const progress=path.join(qa,'SOFTWARE_TEST_progress.jsonl');await download.saveAs(progress);
const saved=read(progress);assert.equal(saved[0].reviewed,true);assert.deepEqual(saved[0].annotation.entities,[Object.fromEntries(['start','end','text','category'].map(k=>[k,first[k]]))]);assert.equal(saved.filter(x=>x.reviewed).length,1);
await page.getByRole('button',{name:'移除',exact:true}).click();assert((await page.locator('#status').innerText()).includes('0/128'));await page.locator('#load').setInputFiles(progress);await page.locator('.entity').first().waitFor();assert.equal(await page.locator('.entity').count(),1);
const policyIndex=original.findIndex(x=>x.kind==='policy');await page.locator('#jump').selectOption(String(policyIndex));
await page.locator('#record select').last().selectOption('DELETE');await page.getByRole('checkbox',{name:'删除',exact:true}).check();
await page.locator('#record textarea').nth(1).fill('软件测试示例，不是人工答案。');await page.locator('#record textarea').nth(2).fill('软件测试理由');await page.getByRole('checkbox',{name:'确认本条全部标注已完成'}).check();
const chatIndex=original.findIndex(x=>x.kind==='dialogue');await page.locator('#jump').selectOption(String(chatIndex));assert.equal(await page.locator('textarea.source').count(),3);
const chatSection=page.locator('#record > section').nth(1);await chatSection.locator('select').last().selectOption('PSEUDONYMIZE');await chatSection.locator('textarea').nth(1).fill('软件测试前轮外发文本');assert((await page.locator('[data-history-index]').first().innerText()).includes('软件测试前轮外发文本'));await chatSection.locator('select').last().selectOption('PAUSE');assert.equal((await page.locator('[data-history-index]').first().innerText()).trim(),'[]');await page.evaluate(()=>window.scrollTo(0,0));
await page.screenshot({path:path.join(qa,'reviewer-desktop.png'),fullPage:true});await page.setViewportSize({width:390,height:844});const noOverflow=await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth);assert(noOverflow);assert.equal(errors.length,0);assert.equal(requests.length,0);
const result={software_test_only:true,record_views:views,progress_export_import:true,entity_selection:true,action_form:true,dialogue_three_turns:true,external_requests:requests,javascript_errors:errors,mobile_no_overflow:noOverflow,human_gold_count:0};fs.writeFileSync(path.join(qa,'reviewer_check.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result));
}finally{await browser.close()}})().catch(e=>{console.error(e.stack);process.exit(1)});
