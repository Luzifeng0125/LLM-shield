// Synthetic UI fixtures only; never count these exports as a human review.
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {pathToFileURL}=require('node:url');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE || 'playwright-core');
const root=path.resolve(__dirname,'../..');
const dir=path.join(root,'app/outputs/natural_action_experiment_20261030_v1');
const out=path.join(dir,'ui_qa');
(async()=>{fs.mkdirSync(out,{recursive:true});const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'});try{
 const page=await browser.newPage({viewport:{width:1280,height:950}}),errors=[],requests=[];
 page.on('pageerror',e=>errors.push(String(e)));await page.route(/^https?:/,r=>{requests.push(r.request().url());return r.abort();});
 await page.goto(pathToFileURL(path.join(dir,'打开实验辅助二审.html')).href);
 assert.match(await page.locator('#progress').textContent(),/0 \/ 138/);
 await page.locator('#filter').selectOption('priority');assert.equal(await page.locator('#jump option').count(),36);
 await page.locator('#filter').selectOption('all');
 await page.locator('#jump').selectOption(String(0));
 const target=await page.locator('#jump option').evaluateAll(options=>options.findIndex(o=>o.textContent.startsWith('na17-s05')));
 assert(target>=0);await page.locator('#jump').selectOption(String(target));
 assert((await page.locator('#note').textContent()).includes('候选判断 RETAIN'));
 assert.equal(await page.locator('#action').inputValue(),'PAUSE');
 await page.screenshot({path:path.join(out,'disagreement-review.png'),fullPage:true});
 await page.locator('#reviewer').fill('自动测试夹具-不计入真人复核');
 await page.locator('#confirm').click();let wait=page.waitForEvent('download');await page.locator('#export').click();
 const file=path.join(out,'automated_fixture_not_human.json');await(await wait).saveAs(file);
 const saved=JSON.parse(fs.readFileSync(file,'utf8'));assert.equal(saved.confirmed_case_ids.length,1);assert.equal(saved.human_reviewed,false);
 assert.equal(saved.reviews.filter(r=>r.human_reviewed).length,1);assert.equal(saved.reviews.filter(r=>r.reviewer_kind==='ai').length,137);
 await page.reload();await page.locator('#resume').setInputFiles(file);
 await page.waitForFunction(()=>document.getElementById('progress').textContent.includes('1 / 138'));
 await page.setViewportSize({width:390,height:844});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth));
 assert.deepEqual(errors,[]);assert.deepEqual(requests,[]);
 const result={passed:true,mode:'synthetic_ui_only',cases:138,priority_cases:36,experiment_does_not_overwrite_labels:true,
  export_preserves_pending_ai:true,resume:true,mobile_no_horizontal_overflow:true,network_requests:0,page_errors:errors,human_reviews_created:0};
 fs.writeFileSync(path.join(out,'report.json'),JSON.stringify(result,null,2));process.stdout.write(JSON.stringify(result));
}finally{await browser.close();}})().catch(e=>{process.stderr.write(String(e.stack));process.exitCode=1;});
