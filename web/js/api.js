// Talking to the Python server (beamcell/server.py).
export async function get(path) {
  const r = await fetch(path);
  const data = await r.json();
  if (!r.ok) throw new Error(data.error || r.statusText);
  return data;
}

export async function post(path, body, asText = false) {
  const r = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (asText) return r.text();
  const data = await r.json();
  if (!r.ok || data.error) throw new Error(data.error || r.statusText);
  return data;
}

export function download(name, text, type = "text/plain") {
  const blob = text instanceof Blob ? text : new Blob([text], { type });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 2000);
}
