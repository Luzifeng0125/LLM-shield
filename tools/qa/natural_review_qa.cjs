"use strict";
// Offline synthetic UI checks. These exported answers are test fixtures, never human reviews.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {pathToFileURL} = require('node:url');
const {chromium} = require('C:/Users/nicholas/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright-core');
const root = path.resolve(__dirname, '../..');
const pack = path.join(root, '03_数据与人工复核/任务必要性复核_自然文档_v3_20261029');
const out = path.join(root, 'delivery/app/outputs/natural_review_qa_20261029');

async function main() {
  fs.mkdirSync(out, {recursive:true});
  const taskPath = path.join(pack, 'review-first-batch.json');
  const task = JSON.parse(fs.readFileSync(taskPath, 'utf8'));
  assert(task.cases.length > 0);
  const browser = await chromium.launch({headless:true, executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'});
  try {
    const page = await browser.newPage({viewport:{width:1280,height:950}});
    const errors = [], network = [];
    page.on('pageerror', e => errors.push(String(e)));
    await page.route(/^https?:/, route => {network.push(route.request().url()); return route.abort();});
    await page.goto(pathToFileURL(path.join(pack, 'action_review.html')).href);
    await page.locator('#taskFile').setInputFiles(taskPath);
    await page.locator('#work').waitFor({state:'visible'});
    assert.equal(await page.locator('#instruction').textContent(), task.cases[0].task_description);
    assert.equal(await page.locator('#context').textContent(), task.cases[0].context);
    assert((await page.locator('#source').textContent()).includes(task.cases[0].text));
    assert.equal(await page.locator('#action').inputValue(), '');
    assert.equal(await page.locator('#facts').inputValue(), '');
    assert.equal(await page.locator('#reason').inputValue(), '');
    await page.screenshot({path:path.join(out, 'full-document-review.png'), fullPage:true});
    await page.locator('#reviewer').fill('AI草稿-UI自动测试-不计入人工复核');
    await page.locator('#representation').selectOption('uncertain');
    await page.locator('#action').selectOption('PAUSE');
    await page.locator('#facts').fill('自动测试夹具，不是人工判断。');
    await page.locator('#reason').fill('仅验证页面保存/导出/续标流程。');
    await page.locator('#save').click();
    const downloadPromise = page.waitForEvent('download');
    await page.locator('#export').click();
    const download = await downloadPromise;
    const exportPath = path.join(out, 'automated_fixture_not_human.json');
    await download.saveAs(exportPath);
    const response = JSON.parse(fs.readFileSync(exportPath, 'utf8'));
    assert.equal(response.reviews.length, 1);
    assert.equal(response.reviews[0].case_sha256, task.cases[0].case_sha256);
    await page.reload();
    await page.locator('#taskFile').setInputFiles(taskPath);
    await page.locator('#work').waitFor({state:'visible'});
    await page.locator('#resumeFile').setInputFiles(exportPath);
    await page.waitForFunction(() => document.getElementById('action').value === 'PAUSE');
    assert.equal(await page.locator('#reviewer').inputValue(), response.reviewer);
    await page.setViewportSize({width:390,height:844});
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth));
    assert.deepEqual(errors, []);
    assert.deepEqual(network, []);
    const result = {passed:true, mode:'offline_synthetic_ui_only', first_batch_decisions:task.cases.length,
      full_context_visible:true, answers_initially_blank:true, export_resume:true, mobile_no_overflow:true,
      network_requests:network.length, page_errors:errors, human_reviews_created:0};
    fs.writeFileSync(path.join(out, 'report.json'), JSON.stringify(result,null,2));
    process.stdout.write(JSON.stringify(result));
  } finally {await browser.close();}
}
main().catch(error => {process.stderr.write(String(error.stack || error)); process.exitCode = 1;});
