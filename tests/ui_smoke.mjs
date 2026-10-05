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
  const st = await state();
  fail("safety state never became " + want + " (is " + st.state + ", stops: " + st.latched.map((f) => f.code).join(", ") + ")");
};
// On CI (software 3D, no GPU) a screenshot can freeze the page for seconds; while the machine runs
// that rightly trips the screen watchdog (HEARTBEAT stop), so CI skips screenshots of a running machine.
const shot = async (name, running = false) => {
  if (!shots || (running && process.env.CI)) return;
  try { await page.screenshot({ path: `${shots}/${name}.png`, timeout: 60000 }); }
  catch (e) { console.warn(`screenshot ${name} skipped: ${e.message.split("\n")[0]}`); }
};
// CI runners have no GPU: use the app's own low-graphics setting (no shadows) so frames stay fast
if (process.env.CI) await page.addInitScript(() => localStorage.setItem("quality", "low"));

await page.goto(base, { waitUntil: "load" });   // the safety check-in never lets the network go idle
await page.waitForFunction(() => window.app && window.app.bars && window.app.bars.length > 0, null, { timeout: 30000 });
await until("the machine's CAD model (web/models/*.glb) didn't load", () => app.scene.loaded, null, 60000);
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
await page.click("[data-mode=AUTO]");                     // the server may still be in another mode
await page.waitForTimeout(300);
if (await page.isEnabled("#sf-reset")) await page.click("#sf-reset");
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
await shot("2_running", true);

// opening the gate in Auto = protective stop
await page.click(".tabs button[data-tab=safety]");
await page.click("[data-input=gate_closed]");
await untilState("FAULT");
const st = await state();
if (!st.latched.some((f) => f.code === "GATE")) fail("gate open didn't stop: " + st.state + " " + st.latched.map((f) => f.code).join(", "));
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
const manualSt = await state();
if (manualSt.state !== "RUNNING" || manualSt.latched.length) fail("Manual mode didn't start: " + manualSt.state + " " + manualSt.latched.map((f) => f.code).join(", "));
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
if (!(t3 > t2)) { const st2 = await state(); fail("hold-to-run didn't move: " + st2.state + " " + st2.latched.map((f) => f.code).join(", ")); }
await page.waitForTimeout(800);
if ((await page.evaluate(() => app.t)) - t3 > 0.5) fail("kept moving after letting go");
for (const t of [0.3, 0.6, 1.0]) {
  await page.evaluate((f) => { app.t = app.plan.summary.duration_s * f; }, t);
  await page.waitForTimeout(400);
}
await shot("2c_finished", true);

// a finished job: the "Job finished" window, the checklist is needed again, Clear the job deletes it
try { await page.waitForFunction(() => document.getElementById("job-done").open, null, { timeout: 30000, polling: 200 }); }
catch (e) {
  const st = await state(), t = await page.evaluate(() => [app.t, app.plan && app.plan.summary.duration_s]);
  fail(`no Job finished window (safety ${st.state}, mode ${st.mode}, stops: ${st.latched.map((f) => f.code).join(", ")}, t ${t[0]} of ${t[1]})`);
}
const done = await state();
if (!done.job || done.job.state !== "finished" || done.checklist_ok) fail("finished job: " + JSON.stringify(done.job) + " checklist " + done.checklist_ok);
const again = await page.evaluate(() => fetch("/api/safety/start", { method: "POST", body: "{}" }).then((r) => r.json()));
if (again.ok) fail("a finished job restarted without a new checklist");
await shot("2d_job_done");
await page.click("#jd-clear");
await until("job not cleared", () => app.job.parts.length === 0 && !app.plan);
if ((await state()).job) fail("the safety controller still has the cleared job");
// the finished job is in the job history, and can be deleted from it
await page.click("#btn-jobs");
await until("job history didn't open", () => document.getElementById("jobs-dlg").open && document.querySelector("#hist-body [data-hist]"));
const hist = await page.evaluate(() => fetch("/api/history").then((r) => r.json()).then((h) => h.history));
if (!hist.length || hist[0].result !== "finished" || !hist[0].parts) fail("job history: " + JSON.stringify(hist[0]));
await page.click(`[data-hist="${hist[0].id}"]`);
await until("history entry not deleted", (id) => !document.querySelector(`[data-hist="${id}"]`), hist[0].id);
await page.click("#jobs-close");

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
await until("CAD file list", () => document.getElementById("cad-files").textContent.includes("beam_cell.step"));
const [download] = await Promise.all([page.waitForEvent("download"), page.click("#btn-stl")]);
const file = await download.path();
if (fs.statSync(file).size < 1000) fail("STL too small");
await shot("4_library");

// manual cutting: a cut and a hole by button, a hole by clicking the web in 3D, check, plan, run
await page.click(".tabs button[data-tab=cell]");
await page.click("#mode-manual");
await page.waitForSelector("#mc-add-cut");
await page.click("#mc-clear");
await page.waitForSelector("#mc-add-cut");
await page.selectOption("#mc-fam", "UB");
await page.waitForTimeout(300);
await page.selectOption("#mc-sec", "UB 305x165x40");
await page.waitForTimeout(300);
await page.fill("#mc-len", "4000");
await page.dispatchEvent("#mc-len", "change");
await page.waitForTimeout(300);
await page.click("#mc-add-cut");                                   // cut at the middle (2000)
await page.waitForTimeout(300);
await page.click("#mc-add-hole");                                  // hole at the middle of the web
await page.waitForTimeout(300);
await page.fill(".mc-row[data-i='1'] [data-f=x]", "1000");
await page.dispatchEvent(".mc-row[data-i='1'] [data-f=x]", "change");
// click on the web face at x = 3000 mm, mid-depth: work out where that is on the screen
await page.evaluate(() => { const sc = app.scene, o = sc.origin; sc.camera.position.set(o.x + 3, o.y - 2.5, o.z + 0.4); sc.controls.target.set(o.x + 3, o.y, o.z + 0.15); sc.controls.update(); });
await page.waitForTimeout(500);
const spot = await page.evaluate(() => {
  const sc = app.scene, o = sc.origin, r = document.getElementById("cell-canvas").getBoundingClientRect();
  sc.camera.updateMatrixWorld();
  const v = o.clone(); v.x += 3.0; v.y -= 0.004; v.z += 0.15;
  v.project(sc.camera);
  return { x: r.left + ((v.x + 1) / 2) * r.width, y: r.top + ((1 - v.y) / 2) * r.height };
});
await page.mouse.click(spot.x, spot.y);
await page.waitForTimeout(800);
const mc = await page.evaluate(() => JSON.parse(localStorage.getItem("manual")));
const clicked = mc.cuts.find((c) => c.type === "hole" && Math.abs(c.x - 3000) <= 10);
if (!clicked || clicked.face !== "v") {
  await shot("fail_click");
  fail("clicking the web didn't add a web hole near x = 3000: " + JSON.stringify(mc.cuts) + " toast: " + (await page.textContent("#toast")) +
    " at " + JSON.stringify(spot) + " element " + (await page.evaluate(({ x, y }) => document.elementFromPoint(x, y).id, spot)));
}
await page.waitForFunction(() => document.querySelector("#mc-check").textContent.includes("The bar becomes"), null, { timeout: 15000 });
const checkText = await page.textContent("#mc-check");
if (!checkText.includes("stays on the rollers") || !checkText.includes("outfeed table")) fail("manual check: " + checkText);
await page.click("#btn-plan");
await until("manual plan didn't load", () => app.plan && app.plan.manual, null, 120000);
const mplan = await page.evaluate(() => ({ c: app.plan.collisions, w: app.plan.warnings, n: app.plan.bar.placements.length, holes: app.plan.ops.filter((o) => o.kind === "hole").length }));
if (mplan.c || mplan.w.length || mplan.n !== 2 || mplan.holes !== 2) fail("manual plan: " + JSON.stringify(mplan));
await page.click("[data-view=overview]");
await page.evaluate(() => { app.t = app.plan.summary.duration_s * 0.5; });
await page.waitForTimeout(500);
await shot("5_manual", true);
await page.click("#mode-job");
await page.waitForTimeout(300);

// prototype tab: the assembly loads with a part number on every solid; clicking a row selects that part
await page.click(".tabs button[data-tab=proto]");
await until("prototype assembly didn't load", () => window.prototypeView && prototypeView.solids && Object.keys(prototypeView.solids).length > 80, null, 60000);
await page.click("#pr-list tr[data-pn=P11]");
const info = await page.textContent("#pr-info");
if (!info.includes("P11") || !info.includes("NEMA 17")) fail("prototype info: " + info);

// sensors tab: every sensor listed, the bar check passes, the plasma chart shows; a simulated slipping load is
// refused at Reset until the load is secure again
await page.click(".tabs button[data-tab=sensors]");
await until("sensors tab didn't fill", () => document.querySelectorAll("#sn-list tr").length >= 15 && document.querySelector("#sn-bar .good")
  && document.querySelectorAll("#sn-plasma tbody tr").length > 5);
await page.click("[data-sim=LOAD]");
const blocked = await state();
if (!blocked.reset_blockers.some((b) => b.includes("Handler"))) fail("simulated load slip not seen: " + JSON.stringify(blocked.reset_blockers));
await page.evaluate(() => fetch("/api/safety/input", { method: "POST", body: JSON.stringify({ name: "load_secure", value: true }) }));

for (const tab of ["camera", "help", "safety", "cell"]) {
  await page.click(`.tabs button[data-tab=${tab}]`);
  await page.waitForTimeout(500);
}
if (errors.length) fail("JavaScript errors:\n" + errors.join("\n"));
console.log(`PASS - plan ${Math.round(plan.d)} s, 0 collisions; reset+checklist needed; E-stop, release, reset, restart; gate stop; Manual hold-to-run; job finished -> checklist again, clear job; NC1 import; editor checks; manual cut (click, check, plan); CAD model + files; prototype assembly; sensors + bar check + load slip; STL ${fs.statSync(file).size} bytes`);
await browser.close();
