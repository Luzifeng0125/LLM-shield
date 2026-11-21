// Browser regression with artificial software fixtures only; never approves user work.
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'C:/Users/nicholas/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright-core');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {pathToFileURL}=require('node:url');
const root=path.resolve(__dirname,'..'),qa=path.join(root,'qa');
const entity={start:1,end:3,text:'小王',category:'PERSON_NAME'};
const target={preferred_action:'DELETE',acceptable_actions:['DELETE'],send_allowed:true,sanitized_text:'请确认会议时间。',reason:'软件测试：联系方式与任务无关'};
const pause={preferred_action:'PAUSE',acceptable_actions:['PAUSE'],send_allowed:false,sanitized_text:null,reason:'软件测试：权限不足'};
const base=(id,kind)=>({id,kind,batch:'SOFTWARE_TEST',reviewer:'A',split:'train',reviewed:false,notes:'保留原备注'});
const ner=(id,entities)=>({...base(id,'ner'),text:'😀小王参加会议',annotation:{entities}});
const policy=(id,t)=>({...base(id,'policy'),text:'😀小王参加会议',annotation:{entities:[entity],target:t}});
const dialogue=id=>({...base(id,'dialogue'),turns:[{turn_id:1,text:'😀小王参加会议'},{turn_id:2,text:'继续处理此材料'}],annotation:{turns:[{turn_id:1,entities:[entity],target},{turn_id:2,entities:[],target:pause}]}});
const fixtures=JSON.parse(JSON.stringify([
 ner('N01',[entity]),ner('N02',[entity]),{...ner('N03',[]),text:'今天是晴天'},
 policy('P01',target),policy('P02',{...target,reason:''}),
 {...policy('P03',pause),annotation:{entities:[],target:pause}},dialogue('D01'),
 dialogue('D02'),{...ner('N04',[entity]),reviewed:true},
 ner('N05',[entity,{start:2,end:3,text:'王',category:'PERSON_NAME'}]),
 ner('N06',[{...entity,start:0}])
]));
fixtures[7].annotation.turns[1].target={preferred_action:null,acceptable_actions:[],send_allowed:null,sanitized_text:null,reason:''};
fs.mkdirSync(qa,{recursive:true});
const fixturePath=path.join(qa,'SOFTWARE_TEST_bulk.html');
fs.writeFileSync(fixturePath,fs.readFileSync(path.join(__dirname,'reviewer.html'),'utf8').replace('__PAYLOAD__',()=>JSON.stringify(fixtures).replaceAll('<','\\u003c')));
(async()=>{
 const browser=await chromium.launch({executablePath:process.env.EDGE_EXECUTABLE||'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true});
 try{
  const page=await browser.newPage({viewport:{width:1280,height:1000},acceptDownloads:true});
  const errors=[],requests=[],dialogs=[];
  page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>{if(/^https?:/.test(r.url()))requests.push(r.url())});
  page.on('dialog',async d=>{dialogs.push(d.message());await d.dismiss()});
  const snapshot=()=>page.evaluate(()=>JSON.parse(JSON.stringify(data)));
  const selectedIds=()=>page.locator('#bulk-list input:checked').evaluateAll(xs=>xs.map(x=>x.closest('tr').dataset.id));
  const completed=async()=> (await snapshot()).filter(r=>r.reviewed).map(r=>r.id);
  const importRows=async rows=>{
   await page.locator('#load').setInputFiles({name:'SOFTWARE_TEST.jsonl',mimeType:'application/json',buffer:Buffer.from(rows.map(x=>JSON.stringify(x)).join('\n'))});
   await page.waitForFunction(()=>document.getElementById('load').value==='');
  };
  await page.goto(pathToFileURL(fixturePath).href);await page.locator('#bulk > summary').click();
  assert(await page.locator('#bulk-empty-label').isHidden());
  for(const id of ['P02','D02','N05','N06'])assert(await page.locator(`#bulk-list tr[data-id="${id}"] input`).isDisabled());
  assert.equal(await page.locator('#bulk-list tr[data-id="N04"]').count(),0);
  await page.locator('#bulk-state').selectOption('ready');await page.locator('#bulk-select').click();
  assert.deepEqual(await selectedIds(),['N01','N02','P01']);
  // Editing a selected action to an incomplete state blocks the entire operation.
  await page.locator('#jump').selectOption('3');await page.locator('#record textarea').nth(2).fill('');
  assert(await page.locator('#bulk-approve').isDisabled());
  await page.evaluate(()=>document.getElementById('bulk-approve').onclick());assert.deepEqual(await completed(),['N04']);
  await page.locator('#record textarea').nth(2).fill(target.reason);await page.locator('#bulk-approve').click();
  assert.deepEqual(await completed(),['N01','N02','P01','N04']);
  const saved=await snapshot(),batchId=saved[0].review_audit[0].batch_id;
  for(let i=0;i<saved.length;i++){
   assert.deepEqual(saved[i].annotation,fixtures[i].annotation);assert.equal(saved[i].notes,fixtures[i].notes);
   if([0,1,3].includes(i)){
    const event=saved[i].review_audit[0];assert.equal(event.batch_id,batchId);assert.equal(event.reviewer,'A');
    assert.equal(event.method,'batch');assert.equal(event.action,'approve');assert.equal(new Date(event.at).toISOString(),event.at);
   }else assert.equal(saved[i].review_audit,undefined);
  }
  const downloadPromise=page.waitForEvent('download');await page.locator('#save').click();
  const output=path.join(qa,'SOFTWARE_TEST_bulk_progress.jsonl');await (await downloadPromise).saveAs(output);
  assert.deepEqual(fs.readFileSync(output,'utf8').trim().split('\n').map(JSON.parse),saved);
  await page.locator('#bulk-undo').click();assert.deepEqual(await completed(),['N04']);
  assert.equal((await snapshot())[0].review_audit.at(-1).action,'reopen');
  // Undo never reverses a later manual edit and independent single-item approval.
  await page.locator('#bulk-kind').selectOption('ner');await page.locator('#bulk-select').click();await page.locator('#bulk-approve').click();
  await page.locator('#jump').selectOption('0');await page.getByRole('button',{name:'移除',exact:true}).click();
  await page.locator('[data-completed]').check();await page.locator('#bulk-undo').click();
  assert.deepEqual(await completed(),['N01','N04']);assert.equal((await snapshot())[0].review_audit.at(-1).method,'single');
  // Exported progress round-trips, including audits; import clears obsolete undo state.
  await importRows(saved);assert.deepEqual(await snapshot(),saved);assert(await page.locator('#bulk-undo').isDisabled());
  const invalid=JSON.parse(JSON.stringify(saved));invalid[3].annotation.target.reason='';
  await importRows(invalid);assert(dialogs.at(-1).includes('理由'));assert.deepEqual(await snapshot(),saved);
  const wrong=JSON.parse(JSON.stringify(saved));wrong[0].review_audit[0].reviewer='B';
  await importRows(wrong);assert(dialogs.at(-1).includes('复核员'));assert.deepEqual(await snapshot(),saved);
  // Valid negative samples and conversations with an empty turn need explicit confirmation.
  await page.locator('#bulk-kind').selectOption('all');await page.locator('#bulk-state').selectOption('pending');
  await page.locator('#bulk-select').click();assert.deepEqual(await selectedIds(),['N03','P03','D01']);
  assert(await page.locator('#bulk-empty-label').isVisible());assert(await page.locator('#bulk-approve').isDisabled());
  await page.locator('#bulk-empty').check();await page.locator('#bulk-approve').click();
  assert.deepEqual(await completed(),['N01','N02','N03','P01','P03','D01','N04']);
  for(const [i,r] of (await snapshot()).entries())assert.deepEqual(r.annotation,fixtures[i].annotation);
  // Search and select-all only affect visible eligible records; changing filters clears selection.
  await importRows(fixtures);await page.locator('#bulk-search').fill('N02');await page.locator('#bulk-select').click();
  assert.deepEqual(await selectedIds(),['N02']);await page.locator('#bulk-search').fill('小王');assert.deepEqual(await selectedIds(),[]);
  await page.locator('#bulk-search').fill('');await page.locator('#bulk-state').selectOption('all');
  assert(await page.locator('#bulk-empty-label').isHidden());
  assert(await page.locator('#bulk-list tr[data-id="N04"] input').isDisabled());
  await page.evaluate(()=>window.scrollTo(0,0));await page.screenshot({path:path.join(qa,'bulk-desktop.png'),fullPage:true});
  await page.setViewportSize({width:390,height:844});
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  await page.screenshot({path:path.join(qa,'bulk-mobile.png'),fullPage:true});
  assert.deepEqual(errors,[]);assert.deepEqual(requests,[]);
  const report={software_test_only:true,bulk_selection:true,annotation_preserved:true,invalid_items_blocked:true,
   empty_entities_confirmation:true,dialogue_all_turns_checked:true,undo_preserves_later_edits:true,
   audit_export_import:true,legacy_import:true,invalid_import_atomic:true,filter_scope:true,
   mobile_no_overflow:true,javascript_errors:errors,external_requests:requests,human_gold_count:0};
  // Optional existing progress compatibility check: read/import only; never saves over user files.
  if(process.argv[2]&&process.argv[3]){
   await page.goto(pathToFileURL(path.resolve(process.argv[2])).href);
   const old=fs.readFileSync(process.argv[3],'utf8').replace(/^\uFEFF/,'').trim().split(/\r?\n/).map(JSON.parse);
   const before=dialogs.length;await importRows(old);assert.equal(dialogs.length,before);
   const loaded=new Map((await snapshot()).map(r=>[r.id,r]));for(const r of old)assert.deepEqual(loaded.get(r.id),r);
   report.existing_progress_read_only_import=true;
  }
  fs.writeFileSync(path.join(qa,'bulk_review_check.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report));
 }finally{await browser.close()}
})().catch(e=>{console.error(e.stack);process.exit(1)});
