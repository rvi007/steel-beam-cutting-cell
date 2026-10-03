// Help tab: how to use the app, in plain words.
export function initHelp() {
  document.getElementById("help").innerHTML = `
<h2>What this is</h2>
<p>A working model of a <b>12 m beam cutting cell</b> for UK structural steel. Two robot "hands" hang from an
overhead gantry: the <b>Cutter</b> (orange, plasma torch) cuts holes, slots, notches and parts to length; the
<b>Handler</b> (blue, magnet) holds each part while it is cut free and puts it on the outfeed rack.</p>

<h2>Quick start</h2>
<ol>
<li><b>Safety</b>: press <b>Reset</b>, tick the pre-start checklist and confirm. Nothing moves until you do.</li>
<li><b>Parts &amp; NC1</b>: drop NC1 files from Tekla / Advance Steel / SDS2 onto the page, pick an example, or press <b>+ New part</b>.</li>
<li>Check each part: the <b>Checks</b> box lists anything that breaks a UK rule, with the clause. The drawing shows every face.</li>
<li><b>Machine</b>: parts are nested onto stock bars (pick the stock length). Click a bar, then <b>Plan this bar</b>.</li>
<li>Press <b>Run</b> (or the space bar). Drag the time bar to jump, pick a speed, and use the view buttons to follow either hand.</li>
<li><b>Camera</b>: start the camera to watch the gate. If someone walks into the zone the machine stops until the zone is clear and you press <b>Reset</b>.</li>
</ol>

<h2>UK rules it checks</h2>
<table>
<tr><th>Rule</th><th>From</th></tr>
<tr><td>Hole sizes for bolts: normal (M12-M14 +1 mm, M16-M24 +2 mm, M27+ +3 mm), oversize, short and long slots</td><td>BS EN 1090-2</td></tr>
<tr><td>End distance e1 and edge distance e2 at least 1.2 d0, spacing at least 2.2 d0</td><td>BS EN 1993-1-8 Table 3.3 + UK NA</td></tr>
<tr><td>Holes clear of the root radius between web and flange</td><td>section geometry (BS 4-1)</td></tr>
<tr><td>Notch corners rounded (10 mm used, at least 5 mm)</td><td>BS EN 1090-2</td></tr>
<tr><td>Notch depth at least tf + r; deep or long notches flagged for the engineer</td><td>Blue Book / SCI P358</td></tr>
<tr><td>Default bolt: M20 grade 8.8 in 22 mm holes; notch sizes N x n from the supporting section</td><td>SCI P358 / Blue Book</td></tr>
<tr><td>Grades S275 / S355 (JR, J0, J2, K2)</td><td>BS EN 10025-2</td></tr>
</table>
<p class="muted">Limits of this machine (not code rules): plasma holes at least the plate thickness and 10 mm; parts at least
150 mm long; bottom-flange holes on I sections and channels can't be reached from above; the Handler lifts up to 500 kg.</p>

<h2>Sections</h2>
<p>All UK sections are in the <b>Section library</b>: UB, UC, UBP, PFC (BS 4-1), equal and unequal angles (BS EN 10056-1)
and hollow sections (BS EN 10210-2 / 10219-2) - 993 sizes with their real root and toe radii. You can download any of
them as an STL file at any scale for 3D printing, and the whole machine too.</p>

<h2>NC1 files</h2>
<p>The DSTV NC1 format is what Tekla exports for beam lines. The cell reads the header (mark, grade, quantity,
profile, length, end-cut angles), holes and slots (BO), outer contours (AK - notches, copes, end cuts) and inner
contours (IK - openings). Hard stamping and marking blocks are listed in the import report but not cut. If a profile
name isn't in the UK library, the sizes in the file are used. More detail: <code>docs/NC1_FILES.md</code>.</p>

<h2>Safety</h2>
<p><b>E-STOP</b> (top right, or the <code>Esc</code> key) stops everything at once. Releasing it does not restart the
machine: press <b>Reset</b> (blue lamp), then <b>Start</b>. The gate, light curtain, fume extraction and camera
danger zone cause a protective stop the same way. Manual mode runs at 250 mm/s and only while you hold
<b>Hold to move</b>. Maintenance mode isolates the machine (Lock Out Tag Out). Full details and the UK
regulations: <code>docs/SAFETY.md</code>. These software stops are a prototype - a real machine needs them in
certified safety hardware.</p>

<h2>Keyboard</h2>
<p><code>Esc</code> E-STOP. <code>Space</code> run / pause. Mouse: left-drag to turn the view, right-drag to move it, wheel to zoom.</p>

<h2>Graphics too slow?</h2>
<p><button id="q-low">Use low graphics (no shadows)</button> <button id="q-high">Use high graphics</button></p>
`;
  document.getElementById("q-low").onclick = () => { localStorage.setItem("quality", "low"); location.reload(); };
  document.getElementById("q-high").onclick = () => { localStorage.setItem("quality", "high"); location.reload(); };
}
