// Captures the 1:10 prototype assembly views (with part-number balloons) from the Prototype tab, for
// docs/Prototype_Assembly.pdf. Start the app first:
//   ./start.sh --port 8099 &
//   node tools/assembly_views.mjs http://localhost:8099      (needs playwright)
// then: python3 tools/make_assembly_pdf.py
import { chromium } from "playwright";

const base = process.argv[2] || "http://localhost:8099";
const out = "docs/images";
const b = await chromium.launch({ args: ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"] });
const p = await b.newPage({ viewport: { width: 2000, height: 1250 } });
p.on("pageerror", (e) => console.log("page error:", e.message));
await p.goto(base, { waitUntil: "load" });
await p.waitForFunction(() => window.app && app.info, null, { timeout: 60000 });
await p.click(".tabs button[data-tab=proto]");
await p.waitForFunction(() => window.prototypeView && prototypeView.solids && Object.keys(prototypeView.solids).length > 50, null, { timeout: 60000 });
await p.addStyleTag({ content: ".pr-views { display: none !important } #tab-proto { grid-template-columns: 1fr !important } .proto-side { display: none }" });
await p.evaluate(() => window.dispatchEvent(new Event("resize")));
const views = [
  ["assembly_iso", "iso", 0, "part"],
  ["assembly_exploded", "iso", 0.7, "part"],
  ["assembly_front", "front", 0, "part"],
  ["assembly_top", "top", 0, "part"],
  ["assembly_positions", "iso", 0.7, "all"],
];
for (const [name, view, explode, mode] of views) {
  await p.evaluate(([view, explode, mode]) => {
    const v = prototypeView;
    document.getElementById("pr-balloons").value = mode;
    document.getElementById("pr-balloons").dispatchEvent(new Event("change"));
    const ex = document.getElementById("pr-explode");
    ex.value = explode;
    ex.dispatchEvent(new Event("input"));
    document.querySelector(`[data-pview="${view}"]`).click();
    if (explode) {                               // exploded: everything spreads out, so step back further
      v.controls.target.z -= 0.16;
      v.camera.position.sub(v.controls.target).multiplyScalar(1.65).add(v.controls.target);
      v.controls.update();
    }
  }, [view, explode, mode]);
  await p.waitForTimeout(1500);
  const box = await p.locator(".proto-view").boundingBox();
  await p.screenshot({ path: `${out}/${name}.png`, clip: box, timeout: 120000 });
  console.log(`${out}/${name}.png`);
}
await b.close();
