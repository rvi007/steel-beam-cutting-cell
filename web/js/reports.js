// Problem reports: every stop during a job saves a report on the machine (reports/ folder). The
// Reports button (top bar) shows how many haven't gone to the developer yet; the window lets the
// operator add a note and send one as a GitHub issue, copy it, or download it.
import { get, post, download } from "./api.js";
import { toast } from "./app.js";

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);

const rp = { list: [], settings: {}, open: null, known: null };

async function refresh() {
  try {
    const r = await get("/api/reports");
    const fresh = rp.known && r.reports.filter((x) => !rp.known.has(x.id));
    rp.list = r.reports;
    rp.settings = r.settings;
    rp.known = new Set(r.reports.map((x) => x.id));
    const unsent = r.reports.filter((x) => !x.sent).length;
    $("rep-badge").textContent = unsent || "";
    $("rep-badge").hidden = !unsent;
    $("btn-reports").classList.toggle("alert", !!unsent);
    if (fresh && fresh.length) toast(`Problem report saved: ${fresh[0].title} - send it to the developer from Reports (top right)`, true);
    if ($("reports-dlg").open) renderList();
  } catch (e) { /* server not answering: the safety code already shows that */ }
}

function renderList() {
  $("rep-count").textContent = rp.list.length ? `(${rp.list.length})` : "";
  $("rep-clear").disabled = !rp.list.length;
  $("rep-list").innerHTML = rp.list.length ? rp.list.map((r) => `
    <button class="rep-item ${rp.open && rp.open.id === r.id ? "on" : ""}" data-rep="${esc(r.id)}">
      <span><b>${esc(r.title)}</b></span>
      <span class="muted small">${esc(r.time)}${r.job ? " &middot; " + esc(r.job) : ""}</span>
      <span>${r.sent ? `<span class="tag good">sent &middot; ${esc(r.sent)}</span>` : '<span class="tag warn">not sent</span>'}
        ${r.send_error ? `<span class="tag badtag" title="${esc(r.send_error)}">send failed</span>` : ""}</span>
    </button>`).join("")
    : '<div class="muted empty">No problem reports. One is saved every time the machine stops during a job.</div>';
  for (const b of document.querySelectorAll("[data-rep]")) b.onclick = () => openReport(b.dataset.rep);
}

async function openReport(id) {
  rp.open = await get("/api/reports/" + encodeURIComponent(id));
  renderList();
  const r = rp.open, repo = rp.settings.github_repo;
  $("rep-detail").innerHTML = `
    <h3>${esc(r.title)}</h3>
    <div class="muted small">${esc(r.time)} &middot; reports/${esc(r.id)}.json ${r.sent ? "&middot; sent: " + esc(r.sent) : ""}</div>
    <label class="f">What were you doing? Anything the developer should know?
      <textarea id="rep-note" rows="3" class="full" placeholder="e.g. the Handler had just picked up the 2nd part when the gate light flickered">${esc(r.note)}</textarea></label>
    <div class="toolbar">
      ${repo ? '<button id="rep-send" class="primary" title="Opens a new GitHub issue with this report - check it and press Submit">Send to developer (GitHub)</button>' : ""}
      <button id="rep-copy">Copy text</button>
      <button id="rep-dl">Download</button>
      ${!r.sent ? '<button id="rep-mark">Mark as sent</button>' : ""}
      <button id="rep-del" class="danger">Delete</button>
    </div>
    <pre class="rep-text">${esc(r.text)}</pre>`;
  const saveNote = async () => {
    const note = $("rep-note").value;
    if (note !== r.note) { rp.open = await post("/api/reports/note", { id: r.id, note }); }
    return rp.open;
  };
  $("rep-note").onchange = saveNote;
  if ($("rep-send")) $("rep-send").onclick = async () => {
    const full = await saveNote();
    let body = full.text + "\n\n(Full report: reports/" + full.id + ".json on the machine.)";
    if (body.length > 6000) body = body.slice(0, 6000) + "\n... (shortened - attach reports/" + full.id + ".json)";
    const url = `https://github.com/${repo}/issues/new?` + new URLSearchParams({ title: "Machine stop: " + full.title, body, labels: "problem report" });
    window.open(url, "_blank", "noopener");
    await post("/api/reports-sent/" + encodeURIComponent(full.id), {});
    toast("GitHub opened in a new tab - check the report and press Submit");
    await refresh(); openReport(full.id);
  };
  $("rep-copy").onclick = async () => {
    const full = await saveNote();
    try { await navigator.clipboard.writeText(full.text); toast("Copied - paste it into an email or message"); }
    catch (e) { toast("Couldn't copy here - use Download instead", true); }
  };
  $("rep-dl").onclick = async () => { const full = await saveNote(); download(`beamcell-report-${full.id}.txt`, full.text); };
  if ($("rep-mark")) $("rep-mark").onclick = async () => {
    await post("/api/reports-sent/" + encodeURIComponent(r.id), {}); await refresh(); openReport(r.id);
  };
  $("rep-del").onclick = async () => {
    if (!confirm("Delete this report?")) return;
    await post("/api/reports-delete/" + encodeURIComponent(r.id), {});
    rp.open = null; $("rep-detail").innerHTML = ""; await refresh(); renderList();
  };
}

export async function openReports() {
  await refresh();
  renderList();
  if (!rp.open && rp.list.length) await openReport(rp.list[0].id);
  if (!rp.list.length) $("rep-detail").innerHTML = "";
  $("rep-auto").innerHTML = rp.settings.webhook
    ? "Reports are also sent automatically (webhook_url in config/cell.toml)."
    : `Reports stay on this machine until you send them. To send them automatically, set <code>webhook_url</code> under [reports] in config/cell.toml.`;
  if (!$("reports-dlg").open) $("reports-dlg").showModal();
}

export function initReports() {
  $("btn-reports").onclick = openReports;
  $("rep-close").onclick = () => $("reports-dlg").close();
  $("rep-clear").onclick = async () => {
    if (!confirm("Delete every problem report? This can't be undone.")) return;
    await post("/api/reports-clear", {});
    rp.open = null; $("rep-detail").innerHTML = ""; await refresh();
  };
  refresh();
  setInterval(refresh, 4000);
}
