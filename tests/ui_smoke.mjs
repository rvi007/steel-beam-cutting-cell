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
if (process.env.SLOW) {                                 // SLOW=4: act like a 4x slower computer
  const cdp = await page.context().newCDPSession(page);
  await cdp.send("Emulation.setCPUThrottlingRate", { rate: +process.env.SLOW });
}
const errors = [];
page.on("pageerror", (e) => errors.push(e.message));
page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
// screenshots are for people to look at; a slow one (software WebGL on CI) must not fail the test
// wait for a condition instead of a fixed time: CI runners are much slower than a desk PC
const state = () => page.evaluate(() => fetch("/api/safety").then((r) => r.json()));
const until = async (what, fn, arg, timeout = 20000) => {
  try { await page.waitForFunction(fn, arg, { timeout, polling: 200 }); } catch (e) { fail(what); }
};
const untilState = async (want) => {
  for (let i = 0; i < 100; i++) { if ((await state()).state === want) return; await page.waitForTimeout(200); }
  fail("safety state never became " + want + " (is " + (await state()).state + ")");
};
const shot = async (name) => {
  if (!shots) return;
  try { await page.screenshot({ path: `${shots}/${name}.png`, timeout: 60000 }); }
  catch (e) { console.warn(`screenshot ${name} skipped: ${e.message.split("\n")[0]}`); }
};
// CI runners have no GPU: use the app's own low-graphics setting (no shadows) so frames stay fast
if (process.env.CI) await page.addInitScript(() => localStorage.setItem("quality", "low"));

await page.goto(base, { waitUntil: "load" });   // the safety check-in never lets the network go idle
await page.waitForFunction(() => window.app && window.app.bars && window.app.bars.length > 0, null, { timeout: 30000 });
await shot("1_start");

// the machine can't run until Reset + checklist (like a real machine)
await page.click("#btn-plan");
await page.waitForFunction(() => window.app.plan, null, { timeout: 120000 });
const plan = await page.evaluate(() => ({ c: app.plan.collisions, d: app.plan.summary.duration_s, w: app.plan.warnings }));
if (plan.c !== 0) fail(`plan has ${plan.c} collisions`);
await page.click("#btn-play");
await page.waitForTimeout(800);
if (await page.evaluate(() => app.t > 0)) fail("machine moved without Reset and checklist");
await page.click(".tabs button[data-tab=safety]");
await page.click("#sf-reset");
for (const box of await page.$$("[data-ck]")) await box.check();
await page.click("#sf-check-ok");
await untilState("READY");
await page.click(".tabs button[data-tab=cell]");
await page.click("#btn-play");
await until("time didn't move after Reset + checklist + Run", () => app.t > 0);

// E-stop: everything stops at once, release alone doesn't restart, reset + start does
await page.keyboard.press("Escape");
await untilState("ESTOP");
await page.waitForTimeout(300);
const t1 = await page.evaluate(() => app.t);
await page.waitForTimeout(800);
if ((await page.evaluate(() => app.t)) !== t1) fail("machine moved after the E-stop");
if (!(await page.isVisible("#safety-banner"))) fail("no E-stop banner");
await page.click("#btn-release");
await page.waitForTimeout(600);
if ((await page.evaluate(() => app.t)) !== t1) fail("machine restarted on E-stop release");
await page.click("#btn-safety-reset");
await untilState("READY");
await page.click("#btn-play");
await until("didn't restart after reset + start", (t) => app.t > t, t1);
await shot("2_running");

// opening the gate in Auto = protective stop
await page.click(".tabs button[data-tab=safety]");
await page.click("[data-input=gate_closed]");
await untilState("FAULT");
const st = await state();
if (st.state !== "FAULT" || !st.latched.some((f) => f.code === "GATE")) fail("gate open didn't stop: " + st.state);
await shot("2b_safety_tab");
await page.click("[data-input=gate_closed]");
await page.waitForTimeout(500);
await page.click("#sf-reset");
await untilState("READY");

// Manual mode: moves only while "Hold to move" is held
await page.click("[data-mode=MANUAL]");
await page.waitForTimeout(400);
await page.click("#sf-reset");
await untilState("READY");
await page.click("#sf-start");
await untilState("RUNNING");
await page.click(".tabs button[data-tab=cell]");
const t2 = await page.evaluate(() => app.t);
await page.waitForTimeout(700);
if ((await page.evaluate(() => app.t)) !== t2) fail("Manual mode moved without hold-to-run");
const hold = await page.$("#btn-hold");
const box = await hold.boundingBox();
await page.mouse.move(box.x + 20, box.y + 10);
await page.mouse.down();
await page.waitForTimeout(1500);
await page.mouse.up();
const t3 = await page.evaluate(() => app.t);
if (!(t3 > t2)) fail("hold-to-run didn't move");
await page.waitForTimeout(800);
if ((await page.evaluate(() => app.t)) - t3 > 0.5) fail("kept moving after letting go");
for (const t of [0.3, 0.6, 1.0]) {
  await page.evaluate((f) => { app.t = app.plan.summary.duration_s * f; }, t);
  await page.waitForTimeout(400);
}
await shot("2c_finished");

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

for (const tab of ["camera", "help", "safety", "cell"]) {
  await page.click(`.tabs button[data-tab=${tab}]`);
  await page.waitForTimeout(500);
}
if (errors.length) fail("JavaScript errors:\n" + errors.join("\n"));
console.log(`PASS - plan ${Math.round(plan.d)} s, 0 collisions; reset+checklist needed; E-stop, release, reset, restart; gate stop; Manual hold-to-run; NC1 import; editor checks; STL ${fs.statSync(file).size} bytes`);
await browser.close();
