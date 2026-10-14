const fs=require('node:fs');
const path=require('node:path');
const assert=require('node:assert/strict');
const {pathToFileURL}=require('node:url');
const {chromium}=require('C:/Users/nicholas/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright-core');
const root=path.resolve(__dirname,'../../隐盾整合交付_20261012');
const screenshots=path.join(root,'验证结果/界面截图');
fs.mkdirSync(screenshots,{recursive:true});
const active=JSON.parse(fs.readFileSync(root+'/人工复核/当前试标.json','utf8'));
(async()=>{
 const browser=await chromium.launch({executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true});
 try{
  const page=await browser.newPage({viewport:{width:1250,height:1050},acceptDownloads:true});
  const errors=[],network=[];page.on('pageerror',e=>errors.push(e.message));
  page.on('request',r=>{if(/^https?:/.test(r.url()))network.push(r.url());});
  await page.goto(pathToFileURL(path.join(root,active.directory,'独立复核.html')).href);
  assert.equal(await page.locator('section').count(),9);
  assert.equal(await page.locator('section > div:visible').count(),0);
  await page.locator('#reviewer').fill('automated_ui_check_not_human');
  for(const section of await page.locator('section').all()){
   await section.locator('textarea').nth(0).fill('自动化界面测试数据，不是人工金标');
   await section.locator('textarea').nth(1).fill('仅用于检查页面保存功能');
   await section.locator('button').click();
   await section.locator('select').nth(0).selectOption('uncertain');
   await section.locator('select').nth(1).selectOption('na');
   await section.locator('select').nth(2).selectOption('uncertain');
   await section.locator('textarea').nth(2).fill('自动化生成，不代表真实人工复核');
  }
  const download=page.waitForEvent('download');await page.locator('#save').click();
  const output=path.join(__dirname,'automated_review_ui_only.json');
  await(await download).saveAs(output);
  const saved=JSON.parse(fs.readFileSync(output,'utf8'));assert(saved.complete);assert.equal(saved.records.length,9);
  await page.reload();await page.locator('#import').setInputFiles(output);
  await page.waitForFunction(()=>document.querySelector('#status').textContent.includes('已恢复'));
  assert.equal(await page.locator('#reviewer').inputValue(),'automated_ui_check_not_human');
  assert.equal(await page.locator('section > div:visible').count(),9);
  assert(await page.locator('section textarea').first().getAttribute('readonly')!==null);
  await page.screenshot({path:path.join(screenshots,'review-ui.png')});
  assert.deepEqual(errors,[]);assert.deepEqual(network,[]);
  fs.writeFileSync(root+'/验证结果/复核工具界面检查.json',JSON.stringify({units:9,prejudgment_before_output:true,export_and_resume:true,no_network_requests:true,javascript_errors:errors,generated_annotations_are_automated_test_only:true},null,2));
  console.log('Review UI: 9 units, staged review, JSON export/resume, no network or JS errors; passed.');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1);});
