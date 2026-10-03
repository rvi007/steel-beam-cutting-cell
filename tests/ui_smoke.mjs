// Browser test: drives the real app in headless Chromium and fails on any JavaScript error.
//   python3 -m beamcell.server --port 8099 &
//   node tests/ui_smoke.mjs http://localhost:8099 [screenshot-folder]
// Needs Playwright (npm i -D playwright && npx playwright install chromium).
import { chromium } from "playwright";
import fs from "node:fs";

const base = process.argv[2] || "http://localhost:8099";
const shots = process.argv[3];
const fail = (msg) => { console.error("FAIL:", msg); process.exit(1); };

const browser = await chromium.launch({ args: ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"] });
const page = await browser.newPage({ viewport: { width: 1600, height: 900 } });
const errors = [];
page.on("pageerror", (e) => errors.push(e.message));
page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
const shot = async (name) => { if (shots) await page.screenshot({ path: `${shots}/${name}.png` }); };

await page.goto(base, { waitUntil: "networkidle" });
await page.waitForFunction(() => window.app && window.app.bars && window.app.bars.length > 0, null, { timeout: 30000 });
await shot("1_start");

// plan the first bar and play it
await page.click("#btn-plan");
await page.waitForFunction(() => window.app.plan, null, { timeout: 120000 });
const plan = await page.evaluate(() => ({ c: app.plan.collisions, d: app.plan.summary.duration_s, w: app.plan.warnings }));
if (plan.c !== 0) fail(`plan has ${plan.c} collisions`);
await page.click("#btn-play");
await page.waitForTimeout(1500);
if (!(await page.evaluate(() => app.t > 0))) fail("time didn't move after Run");
for (const t of [0.3, 0.6, 1.0]) {
  await page.evaluate((f) => { app.t = app.plan.summary.duration_s * f; }, t);
  await page.waitForTimeout(500);
}
await shot("2_finished");

// import an NC1 file through the file picker
await page.click(".tabs button[data-tab=parts]");
const before = await page.evaluate(() => app.job.parts.length);
await page.setInputFiles("#file-nc1", "examples/nc1/P1.nc1");
await page.waitForFunction((n) => app.job.parts.length === n + 1, before, { timeout: 15000 });
await page.waitForTimeout(800);
const report = await page.textContent("#import-report");
if (!report.includes("PFC 200x90x30")) fail("import report: " + report);
await shot("3_parts");

// edit: add a bolt group, checks must update
await page.click("#grp-add");
await page.waitForTimeout(800);
const checks = await page.textContent("#ed-checks");
if (!checks || checks.includes("checking")) fail("checks didn't run");

// library: pick a section and download an STL
await page.click(".tabs button[data-tab=library]");
await page.fill("#lib-search", "203x203x46");
await page.click("#lib-list tbody tr");
await page.waitForTimeout(800);
const [download] = await Promise.all([page.waitForEvent("download"), page.click("#btn-stl")]);
const file = await download.path();
if (fs.statSync(file).size < 1000) fail("STL too small");
await shot("4_library");

for (const tab of ["camera", "help", "cell"]) {
  await page.click(`.tabs button[data-tab=${tab}]`);
  await page.waitForTimeout(500);
}
if (errors.length) fail("JavaScript errors:\n" + errors.join("\n"));
console.log(`PASS - plan ${Math.round(plan.d)} s, 0 collisions, NC1 import, editor checks, STL download ${fs.statSync(file).size} bytes`);
await browser.close();
