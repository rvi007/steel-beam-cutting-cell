// The Jobs window: every job that ran (history, from jobs/history.json) and the saved jobs
// (jobs/<name>.json) - each with its own Delete button.
import { get, post } from "./api.js";
import { fmtTime, toast } from "./app.js";
import { openSavedJob, refreshJobs } from "./parts.js";

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);

// what went wrong while the job ran: "clean", or each stop with its time
function problems(list) {
  if (!list) return "";                                 // entries from before problems were recorded
  if (!list.length) return '<span class="tag good">clean</span>';
  return `<span class="tag warn">${list.length} stop${list.length > 1 ? "s" : ""}</span>` +
    list.map((p) => `<br><span class="small">${esc(p.time)} ${esc(p.text)}</span>`).join("");
}

export async function openJobs() {
  await render();
  if (!$("jobs-dlg").open) $("jobs-dlg").showModal();
}

async function render() {
  const [{ history }, saved] = await Promise.all([get("/api/history"), get("/api/jobs")]);
  $("hist-count").textContent = history.length ? `(${history.length})` : "";
  $("hist-clear").disabled = !history.length;
  $("hist-body").innerHTML = history.length ? history.map((h) => `<tr>
      <td class="nowrap">${esc(h.ended)}</td>
      <td><b>${esc(h.name)}</b>${h.what ? `<br><span class="muted small">${esc(h.what)}</span>` : ""}</td>
      <td>${h.parts || ""}</td><td>${h.duration_s ? fmtTime(h.duration_s) : ""}</td>
      <td><span class="tag ${h.result === "finished" ? "good" : "warn"}">${esc(h.result)}</span></td>
      <td>${problems(h.problems)}</td>
      <td><button class="danger mini" data-hist="${esc(h.id)}" title="Delete this entry">Delete</button></td></tr>`).join("")
    : '<tr><td colspan="7" class="muted">No jobs have run yet. A job is added here when it finishes (or is cleared part-way).</td></tr>';
  $("saved-body").innerHTML = saved.length ? saved.map((n) => `<tr><td><b>${esc(n)}</b> <span class="muted small">jobs/${esc(n)}.json</span></td>
      <td class="nowrap"><button class="mini" data-open="${esc(n)}">Open</button>
      <button class="danger mini" data-del="${esc(n)}">Delete</button></td></tr>`).join("")
    : '<tr><td colspan="2" class="muted">No saved jobs. Save one on the Parts &amp; NC1 tab.</td></tr>';

  for (const b of document.querySelectorAll("[data-hist]")) b.onclick = async () => {
    await post("/api/history-delete/" + encodeURIComponent(b.dataset.hist), {});
    render();
  };
  for (const b of document.querySelectorAll("[data-del]")) b.onclick = async () => {
    const name = b.dataset.del;
    if (!confirm(`Delete the saved job "${name}"? This can't be undone.`)) return;
    await post("/api/jobs-delete/" + encodeURIComponent(name), {});
    toast(`Deleted saved job "${name}"`);
    refreshJobs();
    render();
  };
  for (const b of document.querySelectorAll("[data-open]")) b.onclick = async () => {
    $("jobs-dlg").close();
    await openSavedJob(b.dataset.open);
    toast(`Opened "${b.dataset.open}" - plan a bar on the Machine tab`);
  };
}

export function initJobs() {
  $("btn-jobs").onclick = openJobs;
  $("jobs-close").onclick = () => $("jobs-dlg").close();
  $("hist-clear").onclick = async () => {
    if (!confirm("Delete the whole job history? This can't be undone.")) return;
    await post("/api/history-clear", {});
    render();
  };
}
