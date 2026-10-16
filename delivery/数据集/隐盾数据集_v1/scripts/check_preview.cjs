// Optional UI verification. Needs local Playwright and Edge; dataset generation does not.
const {chromium}=require(process.env.PLAYWRIGHT_MODULE || 'C:/Users/nicholas/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright-core');
const fs=require('node:fs');
const path=require('node:path');
const {pathToFileURL}=require('node:url');
const root=path.resolve(__dirname,'..');
(async()=>{
  const browser=await chromium.launch({executablePath:process.env.EDGE_EXECUTABLE || 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true});
  try {
    const page=await browser.newPage({viewport:{width:1200,height:900}});
    const errors=[],requests=[];
    page.on('pageerror',e=>errors.push(e.message));
    page.on('request',r=>{if(/^https?:/.test(r.url()))requests.push(r.url());});
    await page.goto(pathToFileURL(path.join(root,'预览数据.html')).href);
    let tested=0;
    for(const kind of ['实体识别','动作决策','多轮对话','公开数据']) {
      await page.getByRole('button',{name:kind,exact:true}).click();
      const count=await page.locator('#choose option').count();
      for(let i=0;i<count;i++) {
        await page.locator('#choose').selectOption(String(i));
        if(!(await page.locator('#content').innerText()).trim())throw Error('Empty preview');
        tested++;
      }
    }
    await page.getByRole('button',{name:'多轮对话',exact:true}).click();
    await page.screenshot({path:path.join(root,'evaluation/preview-desktop.png'),fullPage:true});
    await page.setViewportSize({width:390,height:844});
    const noOverflow=await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth);
    if(errors.length||requests.length||!noOverflow)throw Error(JSON.stringify({errors,requests,noOverflow}));
    const result={sample_views_checked:tested,javascript_errors:errors,external_requests:requests,mobile_no_horizontal_overflow:noOverflow};
    fs.writeFileSync(path.join(root,'evaluation/preview_check.json'),JSON.stringify(result,null,2));
    console.log(JSON.stringify(result));
  } finally {await browser.close();}
})().catch(e=>{console.error(e.message);process.exit(1);});
