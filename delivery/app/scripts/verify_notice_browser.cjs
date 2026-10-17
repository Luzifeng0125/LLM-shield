"use strict";
// Uses an existing headless browser; no install, external requests, or raw-data artifacts.
const fs = require("node:fs");
const path = require("node:path");
function arg(name) {
  const index = process.argv.indexOf(name);
  if (index < 0 || !process.argv[index + 1]) throw new Error("Missing required argument");
  return process.argv[index + 1];
}
function check(condition, message) { if (!condition) throw new Error(message); }

async function main() {
  const outputs = fs.realpathSync(path.join(__dirname, "..", "outputs"));
  const input = fs.realpathSync(arg("--input"));
  const requestedOut = path.resolve(arg("--out"));
  const out = path.join(fs.realpathSync(path.dirname(requestedOut)), path.basename(requestedOut));
  const within = candidate => { const rel = path.relative(outputs, candidate); return rel && !rel.startsWith("..") && !path.isAbsolute(rel); };
  check(within(input) && within(out) && !fs.existsSync(out), "Use an ignored input and a new ignored output directory");
  const {chromium} = require(arg("--playwright-package"));
  const source = JSON.parse(fs.readFileSync(input, "utf8").replace(/^\uFEFF/, ""));
  const privateValues = Object.values(source.expected_entities).flat();
  const base = "http://127.0.0.1:8787";
  const browser = await chromium.launch({headless: true, executablePath: arg("--browser")});
  let stage = "configuration";
  const requests = [], pageErrors = [], outside = [];
  try {
    const context = await browser.newContext({viewport: {width: 1440, height: 1000}});
    const response = await context.request.get(base + "/api/config");
    check((await response.json()).models.llm.mode === "mock", "Only mock mode is permitted");
    await context.route("**/*", route => {
      const url = new URL(route.request().url());
      if (url.origin !== base) { outside.push(url.origin); return route.abort(); }
      return route.continue();
    });
    const page = await context.newPage();
    page.on("pageerror", error => pageErrors.push(error.name));
    page.on("request", request => {
      if (request.method() !== "POST") return;
      const body = request.postDataJSON();
      requests.push({path: new URL(request.url()).pathname, keys: Object.keys(body).sort(),
                     containsPrivateValues: privateValues.some(value => JSON.stringify(body).includes(value))});
    });
    await page.goto(base + "/notice");
    await page.waitForFunction(() => !document.getElementById("draftButton").disabled);
    stage = "local_review";
    await page.locator("#roster").fill(source.text);
    await page.locator("#reviewButton").click();
    await page.waitForFunction(expected => document.querySelectorAll("#reviewRows tr").length === expected, privateValues.length);
    stage = "notice_generation";
    await page.locator("#activityName").fill(arg("--activity-name"));
    await page.locator("#draftButton").click();
    await page.waitForFunction(() => document.getElementById("draft").textContent.includes("模拟"));
    const text = await page.locator("#draft").textContent();
    check(!privateValues.some(value => text.includes(value)), "Draft contains a private field");
    const draftRequests = requests.filter(item => item.path === "/api/notice/draft");
    check(draftRequests.length === 1 && !draftRequests[0].containsPrivateValues, "Private data entered generation request");
    check(JSON.stringify(draftRequests[0].keys) === JSON.stringify(["activity_name", "identity", "items"]), "Unexpected draft fields");
    stage = "clear_and_layout";
    await page.locator("#clearRoster").click();
    check(await page.locator("#roster").inputValue() === "", "Roster was not cleared");
    check(await page.locator("#reviewRows tr").count() === 0, "Review values were not cleared");
    await page.locator("#outgoingDetails summary").click();
    check(await page.evaluate(() => localStorage.length === 0 && sessionStorage.length === 0), "Unexpected persisted browser state");
    fs.mkdirSync(out);
    const layouts = [];
    for (const width of [1440, 390]) {
      await page.setViewportSize({width, height: 1000});
      const layout = await page.evaluate(() => ({
        width: innerWidth, contentWidth: document.documentElement.scrollWidth,
        scrollable: getComputedStyle(document.body).overflowY !== "hidden",
      }));
      check(layout.contentWidth <= width && layout.scrollable, "Layout overflow or inaccessible content");
      layouts.push(layout);
      await page.screenshot({path: path.join(out, `notice_${width}.png`), fullPage: true});
    }
    check(pageErrors.length === 0 && outside.length === 0, "Browser errors or nonlocal request");
    const report = {status: "passed", mode: "mock", localReviewedFields: privateValues.length,
                    requests, outsideRequests: outside.length, pageErrors, rosterCleared: true, layouts};
    fs.writeFileSync(path.join(out, "summary.json"), JSON.stringify(report, null, 2) + "\n");
    console.log(JSON.stringify(report));
  } catch (error) {
    console.error(JSON.stringify({status: "failed", stage, error: error.name,
                                  reason: error.message.includes("Timeout") ? "Browser check timed out" : "Browser verification failed; raw context omitted"}));
    process.exitCode = 1;
  } finally { await browser.close(); }
}
main().catch(error => { console.error(JSON.stringify({status: "failed", error: error.name})); process.exitCode = 1; });
