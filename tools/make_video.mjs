// Makes a 30-second promo video of the cell (1920x1080, 30 fps, MP4) from the app's own 3D view:
//   0-10 s  a whole job, start to finish, as a time-lapse, camera circling the cell
//  10-20 s  following the Cutter: the notch (cope), then the bolt holes
//  20-30 s  following the Handler: holds the part while it is cut free, carries it to the outfeed table
// The job is a manual job on a UB 305x165x40: a notch, web and flange holes, a square cut, a second
// notch and a 30 degree mitred cut. Every frame is drawn at an exact time, so the video is smooth
// even on a slow computer.
//
//   python3 -c "import beamcell.server as s; s.SAFETY.cfg['heartbeat_timeout_s'] = 600; s.main(['--port', '8099'])" &
//   node tools/make_video.mjs http://localhost:8099 docs/video/beam_cell_30s.mp4
// Needs Playwright and ffmpeg. (The longer screen watchdog is only for recording: drawing a frame
// in software can take longer than the 2 s the real screen is allowed.)
import { chromium } from "playwright";
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

const base = process.argv[2] || "http://localhost:8099";
const out = process.argv[3] || "docs/video/beam_cell_30s.mp4";
const FPS = 30, W = 1920, H = 1080;
const frames = fs.mkdtempSync(path.join(os.tmpdir(), "beamcell-video-"));

const JOB = { section: "UB 305x165x40", length: 3600, cuts: [
  { type: "notch", x: 0, side: "top", length: 110, depth: 55, radius: 10 },
  { type: "hole", face: "v", x: 70, d: 22 },
  { type: "hole", face: "v", x: 70, y: 80, d: 22 },
  { type: "hole", face: "o", x: 600, y: 40, d: 22 },
  { type: "hole", face: "o", x: 600, y: 125, d: 22 },
  { type: "hole", face: "v", x: 1080, y: 100, d: 22 },
  { type: "hole", face: "v", x: 1080, y: 200, d: 22 },
  { type: "cut", x: 1200 },
  { type: "notch", x: 1200, side: "bottom", on: "after", length: 110, depth: 55 },
  { type: "hole", face: "v", x: 1300, y: 100, d: 22 },
  { type: "hole", face: "v", x: 1300, y: 200, d: 22 },
  { type: "cut", x: 2400, angle: 30 },
] };

// [from s, to s, view, job time at start, job time at end, captions [[from job time, title, text]]]
// The job times come from the plan itself (see shotsFrom), so the video still fits if the cutting speeds change.
let SHOTS = [];
function shotsFrom(plan) {
  const step = (re, who) => plan.steps.find((s) => (!who || s[1] === who) && re.test(s[2]))[0];
  const notch = plan.cuts[0].t_on, holes = step(/hole 1/, "Cutter"), cutoff = step(/cut-off/, "Cutter");
  const carry = step(/carrying/, "Handler");
  return [
    [0, 10, "orbit", 0, plan.summary.duration_s * 0.96, [[0, "A whole job, start to finish",
      "Time-lapse - notches, bolt holes, a square cut and a 30\u00b0 mitre on a UB 305x165x40 - planned and cut automatically"]]],
    [10, 20, "cutter", notch, cutoff - 1, [[notch, "Follow the Cutter", "Plasma notch (cope) at the end of the beam"],
                                          [holes, "Follow the Cutter", "Bolt holes in the web and flanges - placed exactly where the drawing says"]]],
    [20, 30, "handler", carry - 26, carry + 21, [[carry - 26, "Follow the Handler", "Holds the part while the Cutter cuts it free"],
                                               [carry - 1, "Follow the Handler", "Carries the finished part to the outfeed table"]]],
  ];
}
const END_CARD = 28.4;                     // seconds: the closing card fades in

const browser = await chromium.launch({ args: ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"] });
const page = await browser.newPage({ viewport: { width: W, height: H } });
page.on("pageerror", (e) => console.error("page error:", e.message));
// time control: once recording starts, animation frames run only when the recorder steps them
await page.addInitScript((job) => {
  localStorage.setItem("manual", JSON.stringify(job));
  localStorage.setItem("quality", "high");
  const realRaf = window.requestAnimationFrame.bind(window), realNow = performance.now.bind(performance);
  const v = (window.__video = { on: false, now: 0, queue: [] });
  window.requestAnimationFrame = (cb) => (v.on ? v.queue.push(cb) : realRaf(cb));
  performance.now = () => (v.on ? v.now : realNow());
  v.start = () => { v.now = realNow(); v.on = true; };
  v.step = (ms) => { v.now += ms; const q = v.queue.splice(0); for (const cb of q) cb(v.now); };
}, JOB);

await page.goto(base, { waitUntil: "load" });
await page.waitForFunction(() => window.app && app.scene && app.scene.loaded && app.bars, null, { timeout: 120000 });
const api = (p, body = {}) => page.evaluate(([p, b]) => fetch(p, { method: "POST", body: JSON.stringify(b) }).then((r) => r.json()), [p, body]);

// the job: manual mode, plan it, then Reset + checklist + Start like an operator
await api("/api/safety/release", { source: "screen" });
await api("/api/safety/mode", { mode: "AUTO" });
await page.click("#mode-manual");
await page.waitForTimeout(800);
await page.click("#btn-plan");
await page.waitForFunction(() => app.plan && app.plan.manual, null, { timeout: 120000 });
SHOTS = shotsFrom(await page.evaluate(() => ({ steps: app.plan.steps, cuts: app.plan.cuts.map((c) => ({ t_on: c.t_on })),
  summary: app.plan.summary })));
await page.waitForTimeout(500);
await api("/api/safety/reset");
await api("/api/safety/checklist");
const started = await api("/api/safety/start");
if (!started.ok) throw new Error("could not start: " + started.why.join("; "));
await page.waitForFunction(() => window.app.playing, null, { timeout: 10000 });

// full-screen 3D, the app's buttons hidden, our captions on top
await page.addStyleTag({ content: `
  header.top, aside.side, footer.transport, .views, .hud, .stacklight, #safety-banner, #toast, #hover-label, #loading { display: none !important; }
  main, #tab-cell, .viewport { position: fixed !important; inset: 0 !important; width: 100vw !important; height: 100vh !important; margin: 0 !important; padding: 0 !important; display: block !important; }
  #cell-canvas { width: 100vw !important; height: 100vh !important; display: block; }
  .vt { position: fixed; z-index: 50; font-family: "Helvetica Neue", Arial, sans-serif; color: #fff; text-shadow: 0 2px 10px rgba(0,0,0,.45); }
  #vt-brand { top: 36px; left: 48px; font-weight: 800; letter-spacing: .14em; font-size: 30px; background: rgba(16,20,26,.72); padding: 12px 22px 14px; border-radius: 8px; }
  #vt-brand span { color: #f26b1d; } #vt-brand small { display: block; font-weight: 500; letter-spacing: .02em; font-size: 18px; opacity: .9; margin-top: 4px; }
  #vt-chip { top: 40px; right: 48px; background: #f26b1d; padding: 8px 18px; border-radius: 999px; font-weight: 700; font-size: 20px; letter-spacing: .06em; text-shadow: none; }
  #vt-cap { left: 48px; bottom: 56px; max-width: 1150px; background: rgba(16,20,26,.72); border-left: 8px solid #f26b1d; padding: 18px 26px 20px; border-radius: 6px; transition: opacity .25s; }
  #vt-cap b { display: block; font-size: 40px; margin-bottom: 6px; } #vt-cap span { font-size: 25px; line-height: 1.35; opacity: .95; }
  #vt-end { inset: 0; display: flex; flex-direction: column; align-items: center; justify-content: center; text-align: center;
            background: rgba(14,18,24,.86); opacity: 0; }
  #vt-end h1 { font-size: 78px; margin: 0; letter-spacing: .1em; } #vt-end h1 span { color: #f26b1d; }
  #vt-end p { font-size: 32px; margin: 18px 0 0; max-width: 1300px; line-height: 1.35; }
  #vt-end .ask { margin-top: 34px; background: #f26b1d; padding: 14px 34px; border-radius: 999px; font-weight: 800; font-size: 34px; }
  #vt-end .who { margin-top: 30px; font-size: 26px; opacity: .85; }
`});
await page.evaluate(() => {
  document.body.insertAdjacentHTML("beforeend", `
    <div id="vt-brand" class="vt"><span>&#9638;</span> BEAM CELL<small>Robotic cutting of UK structural steel</small></div>
    <div id="vt-chip" class="vt"></div>
    <div id="vt-cap" class="vt"><b></b><span></span></div>
    <div id="vt-end" class="vt"><h1><span>&#9638;</span> BEAM CELL</h1>
      <p>Two robot arms on gantries: a plasma Cutter and a magnet Handler.<br>NC1 files in, finished beams out - with a full safety system.</p>
      <div class="ask">1:10 prototype in build - looking for sponsors</div>
      <div class="who">Ravi Mahadeva &middot; github.com/rvi007/steel-beam-cutting-cell</div></div>`);
  window.dispatchEvent(new Event("resize"));
  app.scene._adapt = () => {};                      // keep full quality, however slow a frame is
  app.speed = 0;
  window.__video.start();
});

const total = +process.env.FRAMES || SHOTS[SHOTS.length - 1][1] * FPS;      // FRAMES=60: a quick test
let shot = -1;
const t0 = Date.now();
for (let f = 0; f < total; f++) {
  const s = f / FPS;
  const k = SHOTS.findIndex((x) => s >= x[0] && s < x[1]);
  const [a, b, view, ja, jb, caps] = SHOTS[k];
  const u = (s - a) / (b - a);
  const jobT = ja + (jb - ja) * u;
  const cap = caps.filter((c) => c[0] <= jobT + 1e-6).pop();
  await page.evaluate(([newShot, view, jobT, speed, u, cap, chip, endA]) => {
    const sc = app.scene;
    if (newShot) { app.t = jobT; sc.view(view === "orbit" ? "overview" : view); }
    app.speed = speed;                                 // job seconds per video second
    if (view === "orbit") {                            // slow half-circle round the cell
      const cx = 2.6, ang = -2.25 + 1.35 * u, r = 9.5;     // centred on the 3.6 m bar being cut
      sc.camera.position.set(cx + r * Math.cos(ang), r * Math.sin(ang), 6.2 - 2.0 * u);
      sc.controls.target.set(cx, 0, 1.3);
    }
    document.querySelector("#vt-cap b").textContent = cap[1];
    document.querySelector("#vt-cap span").textContent = cap[2];
    document.getElementById("vt-chip").textContent = chip;
    document.getElementById("vt-end").style.opacity = endA;
    document.getElementById("vt-cap").style.opacity = 1 - endA;
  }, [k !== shot, view, jobT, (jb - ja) / (b - a), u, cap, `${k + 1} / 3`, Math.min(Math.max((s - END_CARD) / 0.5, 0), 1)]);
  shot = k;
  await page.evaluate((ms) => window.__video.step(ms), 1000 / FPS);
  await page.screenshot({ path: path.join(frames, `f${String(f).padStart(4, "0")}.jpg`), type: "jpeg", quality: 92 });
  if (f % 30 === 0) {
    const st = await page.evaluate(() => [app.t.toFixed(1), app.motion.toFixed(2)]);
    console.log(`frame ${f}/${total}  job t ${st[0]} s  motion ${st[1]}  (${((Date.now() - t0) / 1000).toFixed(0)} s)`);
  }
}
await browser.close();

fs.mkdirSync(path.dirname(out), { recursive: true });
execFileSync("ffmpeg", ["-y", "-loglevel", "error", "-framerate", String(FPS), "-i", path.join(frames, "f%04d.jpg"),
  "-c:v", "libx264", "-preset", "slow", "-crf", "20", "-pix_fmt", "yuv420p", "-movflags", "+faststart", out], { stdio: "inherit" });
fs.rmSync(frames, { recursive: true, force: true });
console.log(out);
