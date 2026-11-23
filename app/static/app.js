"use strict";

// ---------- helpers ----------
const $ = (s, el = document) => el.querySelector(s);
const view = $("#view");
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

async function api(path, opts = {}) {
  const res = await fetch(path, opts);
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  return res.json();
}
const jsonOpts = (method, body) => ({ method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

function toast(msg) {
  const t = $("#toast");
  t.textContent = msg;
  t.classList.add("show");
  clearTimeout(toast._t);
  toast._t = setTimeout(() => t.classList.remove("show"), 2600);
}

const fmtDate = (s) => new Date(s).toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric", year: "numeric" });
const fmtTime = (s) => new Date(s).toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
const fmtDT = (s) => `${fmtDate(s)}, ${fmtTime(s)}`;
const sourceName = (s) => ({ kardia: "Kardia", pixel: "Pixel Watch" }[s] || s);
const localInputValue = (d = new Date()) => new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16);

function levelOf(det) {
  const t = (det || "").toLowerCase();
  if (/fibrillation|afib/.test(t)) return "flag";
  if (/pvc|sve|ectopy|wide|brady|tachy|high heart|low heart|unclassified|inconclusive|unreadable|too short|no analysis/.test(t)) return "note";
  if (/sinus|normal/.test(t)) return "info";
  return "plain";
}
const badge = (det) => `<span class="badge ${levelOf(det)}">${esc(det || "Unknown")}</span>`;

// Only the trace on the current page redraws on resize.
let redrawOnResize = null, resizeTimer;
window.addEventListener("resize", () => {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(() => redrawOnResize && $("#ecg") && redrawOnResize(), 150);
});

// ---------- router ----------
const routes = [
  [/^#?\/?$/, overview, "overview"],
  [/^#\/recordings$/, recordings, "recordings"],
  [/^#\/recordings\/(\d+)$/, recordingDetail, "recordings"],
  [/^#\/symptoms$/, symptoms, "symptoms"],
  [/^#\/import$/, importPage, "import"],
  [/^#\/report$/, report, "report"],
];

async function route() {
  const h = location.hash || "#/";
  for (const [re, fn, nav] of routes) {
    const m = h.match(re);
    if (m) {
      document.querySelectorAll("nav a").forEach((a) => a.classList.toggle("active", a.dataset.nav === nav));
      redrawOnResize = null;
      view.innerHTML = `<p class="muted">Loading…</p>`;
      try { await fn(...m.slice(1)); } catch (e) { view.innerHTML = `<div class="card"><h2>Something went wrong</h2><p class="muted">${esc(e.message)}</p></div>`; }
      window.scrollTo(0, 0);
      return;
    }
  }
  location.hash = "#/";
}
window.addEventListener("hashchange", route);

// ---------- overview ----------
async function overview() {
  const [s, syms] = await Promise.all([api("/api/summary"), api("/api/symptoms")]);
  if (!s.recording_count && !s.symptom_count) {
    view.innerHTML = `
      <div class="card empty">
        <h2>No recordings yet</h2>
        <p>Import your Kardia and Pixel Watch ECG PDFs to build your history.</p>
        <p><a class="btn primary" href="#/import">Import recordings</a></p>
      </div>`;
    return;
  }
  const dets = Object.entries(s.by_determination).sort((a, b) => b[1] - a[1]);
  const recent = s.trend.slice(-6).reverse();
  view.innerHTML = `
    <div class="stack">
      <div class="row between"><h1>Overview</h1>
        <span class="muted small">${s.first ? `${fmtDate(s.first)} – ${fmtDate(s.last)}` : ""}</span></div>
      <div class="tiles">
        <div class="tile"><div class="label">Recordings</div><div class="value">${s.recording_count}</div>
          <div class="sub">${Object.entries(s.by_source).map(([k, v]) => `${v} ${sourceName(k)}`).join(" · ")}</div></div>
        <div class="tile"><div class="label">Average heart rate</div><div class="value">${s.hr_avg ?? "–"} <small>bpm</small></div>
          <div class="sub">across all recordings</div></div>
        <div class="tile"><div class="label">With early beats</div><div class="value">${s.early_beat_recordings}</div>
          <div class="sub">recordings with ≥1 early beat</div></div>
        <div class="tile"><div class="label">Symptoms logged</div><div class="value">${s.symptom_count}</div>
          <div class="sub">${s.symptoms_with_recording} with a recording within 1 h</div></div>
      </div>
      <div class="cols">
        <div class="card chart"><h2>Heart rate over time</h2><div id="trend"></div>
          <div class="legend" style="margin-top:8px"><span><i style="background:var(--ok)"></i>Normal result</span>
          <span><i style="background:var(--warn)"></i>Other / unclassified</span><span><i style="background:var(--bad)"></i>Possible AFib</span>
          <span>● Kardia&nbsp;&nbsp;■ Pixel Watch</span><span><i style="background:var(--ok-bg)"></i>60–100 bpm</span></div></div>
        <div class="card"><h2>Results</h2>
          <table><tbody>${dets.map(([d, n]) => `<tr><td>${badge(d)}</td><td class="num" style="text-align:right">${n}</td></tr>`).join("")}</tbody></table></div>
      </div>
      <div class="cols">
        <div class="card"><div class="row between"><h2>Recent recordings</h2><a href="#/recordings">All recordings →</a></div>
          <table><tbody>${recent.map((r) => `<tr class="link" data-href="#/recordings/${r.id}">
            <td>${fmtDT(r.t)}</td><td>${sourceName(r.source)}</td><td>${badge(r.det)}</td>
            <td class="num">${r.hr ? Math.round(r.hr) + " bpm" : "–"}</td>
            <td>${r.early ? `<span class="badge note">${r.early} early</span>` : ""}</td></tr>`).join("")}</tbody></table></div>
        <div class="card"><div class="row between"><h2>Recent symptoms</h2><a href="#/symptoms">All →</a></div>
          ${syms.length ? `<table><tbody>${syms.slice(0, 6).map((x) => `<tr><td>${fmtDT(x.occurred_at)}<br><span class="muted small">${esc(x.kind)}</span></td>
            <td>${x.recordings.length ? `<a href="#/recordings/${x.recordings[0].id}">ECG ${x.recordings[0].minutes_apart} min away</a>` : `<span class="muted small">no ECG</span>`}</td></tr>`).join("")}</tbody></table>`
            : `<p class="muted">Nothing logged yet. Use <strong>Log a symptom now</strong> when you feel palpitations.</p>`}
        </div>
      </div>
      <div class="card"><h2>Catching palpitations</h2>
        <ul class="steps">
          <li><strong>Record during symptoms.</strong> A recording taken while you feel it is far more useful than one taken later. Keep the Kardia within reach.</li>
          <li><strong>Log it here</strong> with the time and what you were doing, so recordings can be matched to symptoms.</li>
          <li><strong>Also record when you feel fine</strong>, at similar times of day, so there's a baseline to compare against.</li>
          <li>If episodes are frequent but hard to catch, ask your doctor about a <strong>wearable patch monitor</strong> (records continuously for 1–2 weeks).</li>
        </ul></div>
    </div>`;
  bindRowLinks();
  trendChart($("#trend"), s.trend);
}

function bindRowLinks(root = view) {
  root.querySelectorAll("tr[data-href]").forEach((tr) => tr.addEventListener("click", () => (location.hash = tr.dataset.href)));
}

function trendChart(el, pts) {
  pts = pts.filter((p) => p.hr);
  if (!pts.length) { el.innerHTML = `<p class="muted">No heart-rate data yet.</p>`; return; }
  const W = 760, H = 260, L = 40, R = 12, T = 10, B = 28;
  const ts = pts.map((p) => +new Date(p.t));
  let t0 = Math.min(...ts), t1 = Math.max(...ts);
  if (t1 - t0 < 864e5) { t0 -= 432e5; t1 += 432e5; }
  const pad = (t1 - t0) * 0.04; t0 -= pad; t1 += pad;
  const hrs = pts.map((p) => p.hr);
  const y0 = Math.min(40, Math.floor(Math.min(...hrs) / 10) * 10 - 10), y1 = Math.max(120, Math.ceil(Math.max(...hrs) / 10) * 10 + 10);
  const x = (t) => L + ((t - t0) / (t1 - t0)) * (W - L - R);
  const y = (v) => T + (1 - (v - y0) / (y1 - y0)) * (H - T - B);
  const col = { info: "var(--ok)", note: "var(--warn)", flag: "var(--bad)", plain: "var(--muted)" };
  let g = `<rect class="band" x="${L}" y="${y(100)}" width="${W - L - R}" height="${y(60) - y(100)}"/>`;
  for (let v = y0; v <= y1; v += 20) g += `<line class="gridline" x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}"/><text x="${L - 6}" y="${y(v) + 4}" text-anchor="end">${v}</text>`;
  const ticks = 5;
  for (let i = 0; i <= ticks; i++) {
    const t = t0 + ((t1 - t0) * i) / ticks;
    g += `<text x="${x(t)}" y="${H - 8}" text-anchor="middle">${new Date(t).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "2-digit" })}</text>`;
  }
  for (const p of pts) {
    const cx = x(+new Date(p.t)), cy = y(p.hr), c = col[levelOf(p.det)];
    const tip = `<title>${esc(fmtDT(p.t))}\n${esc(p.det)} · ${Math.round(p.hr)} bpm${p.early ? ` · ${p.early} early beats` : ""}</title>`;
    g += `<a href="#/recordings/${p.id}">` + (p.source === "pixel"
      ? `<rect x="${cx - 5}" y="${cy - 5}" width="10" height="10" rx="2" fill="${c}" stroke="var(--surface)" stroke-width="1.5">${tip}</rect>`
      : `<circle cx="${cx}" cy="${cy}" r="5.5" fill="${c}" stroke="var(--surface)" stroke-width="1.5">${tip}</circle>`) + `</a>`;
  }
  el.innerHTML = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Heart rate per recording over time">${g}</svg>`;
}

// ---------- recordings list ----------
async function recordings() {
  const rows = await api("/api/recordings");
  if (!rows.length) {
    view.innerHTML = `<div class="card empty"><h2>No recordings yet</h2><p><a class="btn primary" href="#/import">Import recordings</a></p></div>`;
    return;
  }
  view.innerHTML = `
    <div class="stack">
      <div class="row between"><h1>Recordings</h1>
        <div class="row"><select id="f-src" style="width:auto"><option value="">All devices</option><option value="kardia">Kardia</option><option value="pixel">Pixel Watch</option></select>
        <a class="btn" href="#/import">Import</a></div></div>
      <div class="card" style="padding:6px 10px"><table>
        <thead><tr><th>When</th><th>Device</th><th>Device result</th><th>Heart rate</th><th>Range</th><th>Findings</th><th>Signal</th></tr></thead>
        <tbody id="rec-body"></tbody></table></div>
    </div>`;
  const render = () => {
    const src = $("#f-src").value;
    $("#rec-body").innerHTML = rows.filter((r) => !src || r.source === src).map((r) => `
      <tr class="link" data-href="#/recordings/${r.id}">
        <td>${fmtDT(r.recorded_at)}</td>
        <td>${esc(r.device)}</td>
        <td>${badge(r.determination)}</td>
        <td class="num">${r.hr_mean ? Math.round(r.hr_mean) + " bpm" : "–"}${r.reported_hr && r.hr_mean && Math.abs(r.reported_hr - r.hr_mean) > 8 ? ` <span class="muted small">(device: ${r.reported_hr})</span>` : ""}</td>
        <td class="num muted">${r.hr_min ? `${r.hr_min}–${r.hr_max}` : ""}</td>
        <td>${r.early_beats ? `<span class="badge note">${r.early_beats} early</span> ` : ""}${r.pauses ? `<span class="badge flag">${r.pauses} pause</span>` : ""}${!r.early_beats && !r.pauses && r.quality !== "poor" ? `<span class="muted small">none</span>` : ""}</td>
        <td><span class="badge ${r.quality === "good" ? "info" : r.quality === "fair" ? "note" : "flag"}">${esc(r.quality || "?")}</span></td>
      </tr>`).join("");
    bindRowLinks();
  };
  $("#f-src").addEventListener("change", render);
  render();
}

// ---------- recording detail ----------
async function recordingDetail(id) {
  const [r, sig] = await Promise.all([api(`/api/recordings/${id}`), api(`/api/recordings/${id}/signal`)]);
  const m = r.metrics;
  const leads = Object.keys(sig.leads);
  const di = r.determination_info;
  view.innerHTML = `
    <div class="stack">
      <div class="row between">
        <div><a href="#/recordings" class="small">← Recordings</a><h1>${fmtDT(r.recorded_at)}</h1>
          <div class="muted">${esc(r.device)} · ${r.duration_s?.toFixed(0)} s · ${leads.length} lead${leads.length > 1 ? "s" : ""}</div></div>
        <div class="row no-print"><a class="btn" href="/api/recordings/${r.id}/pdf" target="_blank" rel="noopener">Original PDF</a>
          <button class="btn danger" id="del">Delete</button></div>
      </div>

      <div class="tiles">
        <div class="tile"><div class="label">Heart rate</div><div class="value">${m.hr_mean ? Math.round(m.hr_mean) : "–"} <small>bpm</small></div>
          <div class="sub">${r.reported_hr ? `device said ${r.reported_hr}` : ""}${m.hr_min ? ` · range ${m.hr_min}–${m.hr_max}` : ""}</div></div>
        <div class="tile"><div class="label">Beats measured</div><div class="value">${m.beat_count ?? "–"}</div><div class="sub">${m.usable_s} of ${m.duration_s} s clean</div></div>
        <div class="tile"><div class="label">Early beats</div><div class="value">${m.early_beats.length}</div><div class="sub">${m.pauses.length} pause${m.pauses.length === 1 ? "" : "s"}</div></div>
        <div class="tile"><div class="label">Beat-to-beat variation</div><div class="value">${m.rmssd_ms ?? "–"} <small>ms</small></div>
          <div class="sub">RMSSD${m.sdnn_ms ? ` · SDNN ${m.sdnn_ms} ms` : ""}</div></div>
      </div>

      <div class="card">
        <div class="row between"><h2>ECG trace</h2>
          <div class="row no-print">
            <label class="row" style="flex-direction:row;gap:6px">Lead
              <select id="lead" style="width:auto">${leads.map((l) => `<option>${l}</option>`).join("")}${leads.length > 1 ? `<option value="__all">All ${leads.length} leads</option>` : ""}</select></label>
            <label class="row" id="win-wrap" style="flex-direction:row;gap:6px;display:none">Seconds
              <select id="win" style="width:auto"></select></label>
          </div></div>
        <div class="legend" style="margin:6px 0 10px"><span>25 mm/s · 10 mm/mV</span>
          <span><i style="background:var(--info)"></i>detected beat</span><span><i style="background:var(--bad)"></i>early beat</span>
          <span><i style="background:rgba(128,128,128,.35)"></i>noise (excluded)</span></div>
        <div class="ecg-wrap"><canvas id="ecg"></canvas></div>
      </div>

      <div class="cols">
        <div class="stack">
          <div class="card stack"><h2>What this recording shows</h2>
            <div class="obs ${di.level}"><div><strong>Device result: ${esc(r.determination)}</strong><p>${esc(di.detail)}</p></div></div>
            ${m.observations.map((o) => `<div class="obs ${o.level}"><div><strong>${esc(o.title)}</strong><p>${esc(o.detail)}</p></div></div>`).join("")}
          </div>
          ${m.rr_ms?.length > 3 ? `<div class="card chart"><h2>Time between beats</h2>
            <p class="muted small" style="margin-top:-6px">Each dot is one beat-to-beat interval. A dip followed by a jump is the classic early-beat pattern.</p>
            <div id="tacho"></div></div>` : ""}
        </div>
        <div class="stack">
          <div class="card"><h2>Notes</h2>
            <textarea id="notes" rows="4" placeholder="How were you feeling? What were you doing?">${esc(r.notes)}</textarea>
            <div class="row end" style="margin-top:8px"><button class="btn sm" id="save-notes">Save notes</button></div></div>
          <div class="card"><h2>Symptoms within 1 hour</h2>
            ${r.nearby_symptoms.length ? `<table><tbody>${r.nearby_symptoms.map((s) => `<tr><td>${fmtTime(s.occurred_at)}</td><td>${esc(s.kind)}${s.severity ? ` <span class="muted small">(${s.severity}/5)</span>` : ""}<br><span class="muted small">${esc(s.activity)}</span></td></tr>`).join("")}</tbody></table>`
              : `<p class="muted small">None logged.</p>`}</div>
          <div class="card"><h2>Measurements</h2><dl class="kv">
            <dt>Sample rate</dt><dd>${sig.fs} Hz</dd>
            <dt>Mean HR</dt><dd>${m.hr_mean ?? "–"} bpm</dd>
            <dt>RMSSD</dt><dd>${m.rmssd_ms ?? "–"} ms</dd>
            <dt>SDNN</dt><dd>${m.sdnn_ms ?? "–"} ms</dd>
            <dt>pNN50</dt><dd>${m.pnn50 ?? "–"} %</dd>
            <dt>Irregularity (CV)</dt><dd>${m.irregularity_cv ?? "–"}</dd>
            <dt>Signal quality</dt><dd>${esc(m.quality)}</dd>
            <dt>Imported</dt><dd>${esc(r.imported_at)}</dd></dl></div>
        </div>
      </div>
    </div>`;

  const leadSel = $("#lead"), winSel = $("#win");
  const dur = sig.leads[leads[0]].length / sig.fs;
  for (let s = 0; s < dur; s += 10) winSel.insertAdjacentHTML("beforeend", `<option value="${s}">${s}–${Math.min(dur, s + 10).toFixed(0)} s</option>`);
  const draw = () => {
    const all = leadSel.value === "__all";
    $("#win-wrap").style.display = all ? "flex" : "none";
    drawECG($("#ecg"), sig, all ? { leads, start: +winSel.value } : { leads: [leadSel.value] });
  };
  leadSel.addEventListener("change", draw);
  winSel.addEventListener("change", draw);
  draw();
  redrawOnResize = draw;
  if ($("#tacho")) tachogram($("#tacho"), m);

  $("#save-notes").addEventListener("click", async () => {
    await api(`/api/recordings/${id}`, jsonOpts("PATCH", { notes: $("#notes").value }));
    toast("Notes saved");
  });
  $("#del").addEventListener("click", async () => {
    if (!confirm("Delete this recording? The original PDF stored here will be removed too.")) return;
    await api(`/api/recordings/${id}`, { method: "DELETE" });
    toast("Recording deleted");
    location.hash = "#/recordings";
  });
}

/** Draw ECG on standard paper. opts.leads: one lead = full recording in 10 s rows; several = one 10 s window, a row per lead. */
function drawECG(canvas, sig, opts) {
  const fs = sig.fs, secPerRow = 10;
  const width = canvas.parentElement.clientWidth;
  const pxmm = width / (secPerRow * 25);
  const multi = opts.leads.length > 1;
  const rowMm = multi ? 20 : 32;
  const n = sig.leads[opts.leads[0]].length;
  const rows = multi
    ? opts.leads.map((l) => ({ lead: l, a: Math.round(opts.start * fs), b: Math.min(n, Math.round((opts.start + secPerRow) * fs)) }))
    : Array.from({ length: Math.ceil(n / (secPerRow * fs)) }, (_, i) => ({ lead: opts.leads[0], a: i * secPerRow * fs, b: Math.min(n, (i + 1) * secPerRow * fs) }));
  const height = Math.ceil(rows.length * rowMm * pxmm);
  const dpr = window.devicePixelRatio || 1;
  canvas.width = Math.round(width * dpr); canvas.height = Math.round(height * dpr);
  canvas.style.height = height + "px";
  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.fillStyle = css("--paper"); ctx.fillRect(0, 0, width, height);

  // paper grid
  for (const [step, color, lw] of [[1, css("--grid-minor"), 0.6], [5, css("--grid-major"), 1]]) {
    ctx.strokeStyle = color; ctx.lineWidth = lw; ctx.beginPath();
    for (let mm = 0; mm * pxmm <= width; mm += step) { const X = Math.round(mm * pxmm) + 0.5; ctx.moveTo(X, 0); ctx.lineTo(X, height); }
    for (let mm = 0; mm * pxmm <= height; mm += step) { const Y = Math.round(mm * pxmm) + 0.5; ctx.moveTo(0, Y); ctx.lineTo(width, Y); }
    ctx.stroke();
  }

  const pxPerSample = (25 * pxmm) / fs, pxPerMv = 10 * pxmm;
  const earlySamples = new Set(sig.early.map((t) => Math.round(t * fs)));
  const isEarly = (b) => [...earlySamples].some((e) => Math.abs(e - b) < 0.12 * fs);
  rows.forEach((row, ri) => {
    const top = ri * rowMm * pxmm, mid = top + (rowMm * pxmm) / 2;
    const data = sig.leads[row.lead];
    const t0 = row.a / fs;
    // noise shading
    ctx.fillStyle = "rgba(128,128,128,.22)";
    for (const [s, e] of sig.artifacts) {
      const xa = (Math.max(s, t0) - t0) * 25 * pxmm, xb = (Math.min(e, row.b / fs) - t0) * 25 * pxmm;
      if (xb > xa) ctx.fillRect(xa, top, xb - xa, rowMm * pxmm);
    }
    // baseline-centred trace
    const seg = data.slice(row.a, row.b);
    const sorted = [...seg].sort((p, q) => p - q);
    const base = sorted[Math.floor(sorted.length / 2)] || 0;
    ctx.save(); ctx.beginPath(); ctx.rect(0, top, width, rowMm * pxmm); ctx.clip();
    ctx.strokeStyle = css("--trace"); ctx.lineWidth = 1.2; ctx.lineJoin = "round"; ctx.beginPath();
    seg.forEach((v, i) => { const X = i * pxPerSample, Y = mid - (v - base) * pxPerMv; i ? ctx.lineTo(X, Y) : ctx.moveTo(X, Y); });
    ctx.stroke();
    // beat markers (primary lead indices apply to every lead: same timebase)
    for (const b of sig.beats) {
      if (b < row.a || b >= row.b) continue;
      const X = (b - row.a) * pxPerSample, early = isEarly(b);
      ctx.fillStyle = early ? css("--bad") : css("--info");
      ctx.beginPath(); ctx.moveTo(X - 4, top + 3); ctx.lineTo(X + 4, top + 3); ctx.lineTo(X, top + 9); ctx.fill();
      if (early) { ctx.font = "600 11px system-ui"; ctx.fillText("early", X + 6, top + 11); }
    }
    ctx.restore();
    // labels
    ctx.fillStyle = css("--muted"); ctx.font = "600 12px system-ui";
    ctx.fillText(multi ? row.lead : `${t0.toFixed(0)} s`, 6, top + rowMm * pxmm - 6);
    ctx.strokeStyle = css("--grid-major"); ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(0, top + rowMm * pxmm); ctx.lineTo(width, top + rowMm * pxmm); ctx.stroke();
  });
}

function tachogram(el, m) {
  const rr = m.rr_ms, W = 520, H = 180, L = 44, R = 10, T = 10, B = 24;
  const lo = Math.max(200, Math.min(...rr) - 60), hi = Math.max(...rr) + 60;
  const x = (i) => L + (i / Math.max(1, rr.length - 1)) * (W - L - R);
  const y = (v) => T + (1 - (v - lo) / (hi - lo)) * (H - T - B);
  const earlyRR = new Set(m.early_beats.map((e) => e.rr_ms));
  let g = "";
  const step = Math.max(50, Math.round((hi - lo) / 4 / 50) * 50);
  for (let v = Math.ceil(lo / step) * step; v <= hi; v += step) g += `<line class="gridline" x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}"/><text x="${L - 6}" y="${y(v) + 4}" text-anchor="end">${v}</text>`;
  g += `<text x="${L}" y="${H - 6}">beat 1</text><text x="${W - R}" y="${H - 6}" text-anchor="end">beat ${rr.length}</text>`;
  g += `<polyline fill="none" stroke="var(--line)" stroke-width="1.5" points="${rr.map((v, i) => `${x(i)},${y(v)}`).join(" ")}"/>`;
  rr.forEach((v, i) => { g += `<circle cx="${x(i)}" cy="${y(v)}" r="3.5" fill="${earlyRR.has(v) ? "var(--bad)" : "var(--info)"}"><title>${v} ms (${Math.round(60000 / v)} bpm)</title></circle>`; });
  el.innerHTML = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Beat to beat intervals in milliseconds">${g}</svg>`;
}

// ---------- symptoms ----------
async function symptoms() {
  const rows = await api("/api/symptoms");
  view.innerHTML = `
    <div class="stack">
      <div class="row between"><h1>Symptoms</h1><button class="btn primary" id="add-sym">+ Log a symptom</button></div>
      <p class="muted">Each entry is matched to any ECG recorded within an hour of it. Symptoms with a matching recording are the most useful thing to show your doctor.</p>
      ${rows.length ? `<div class="card" style="padding:6px 10px"><table>
        <thead><tr><th>When</th><th>Symptom</th><th>Strength</th><th>Doing</th><th>Notes</th><th>Matching ECG</th><th></th></tr></thead>
        <tbody>${rows.map((s) => `<tr>
          <td>${fmtDT(s.occurred_at)}</td><td>${esc(s.kind)}${s.duration_min ? `<br><span class="muted small">~${s.duration_min} min</span>` : ""}</td>
          <td class="num">${s.severity ? `${s.severity}/5` : ""}</td><td>${esc(s.activity)}</td><td class="small">${esc(s.notes)}</td>
          <td>${s.recordings.length ? s.recordings.map((r) => `<a href="#/recordings/${r.id}">${esc(r.determination)}</a> <span class="muted small">(${r.minutes_apart} min)</span>`).join("<br>") : `<span class="muted small">none</span>`}</td>
          <td><button class="btn sm danger" data-del="${s.id}" aria-label="Delete">✕</button></td></tr>`).join("")}</tbody></table></div>`
        : `<div class="card empty"><h2>Nothing logged yet</h2><p>When you feel palpitations, click <strong>Log a symptom now</strong> and, if you can, take an ECG at the same time.</p></div>`}
    </div>`;
  $("#add-sym").addEventListener("click", openLog);
  view.querySelectorAll("[data-del]").forEach((b) => b.addEventListener("click", async () => {
    if (!confirm("Delete this symptom entry?")) return;
    await api(`/api/symptoms/${b.dataset.del}`, { method: "DELETE" });
    route();
  }));
}

function openLog() {
  const f = $("#log-form");
  f.reset();
  f.occurred_at.value = localInputValue();
  f.querySelector("output").value = 3;
  $("#log-dialog").showModal();
}
$("#quick-log").addEventListener("click", openLog);
$("#log-dialog").addEventListener("close", async () => {
  if ($("#log-dialog").returnValue !== "save") return;
  const f = $("#log-form");
  const body = {
    occurred_at: f.occurred_at.value, kind: f.kind.value, severity: +f.severity.value,
    duration_min: f.duration_min.value ? +f.duration_min.value : null, activity: f.activity.value, notes: f.notes.value,
  };
  try {
    await api("/api/symptoms", jsonOpts("POST", body));
    toast("Symptom logged");
    if (/symptoms|^#?\/?$/.test(location.hash) || !location.hash) route();
  } catch (e) { toast("Couldn't save: " + e.message); }
});

// ---------- import ----------
async function importPage() {
  const st = await api("/api/status");
  view.innerHTML = `
    <div class="stack">
      <h1>Import recordings</h1>
      <label class="drop" id="drop">
        <strong>Drop ECG PDFs here</strong><br><span class="muted">or click to choose files. You can select many at once.</span>
        <input type="file" id="file" accept="application/pdf,.pdf" multiple hidden>
      </label>
      <div id="results"></div>
      <div class="grid2">
        <div class="card"><h2>Kardia</h2><ol class="steps">
          <li>In the Kardia app, open <strong>History</strong> and tap a recording.</li>
          <li>Tap <strong>Share</strong> (or the PDF icon) and save it to Google Drive, email it to yourself, or AirDrop it.</li>
          <li>Drop the PDF here. All 6 leads are read from KardiaMobile 6L reports.</li></ol></div>
        <div class="card"><h2>Pixel Watch / Fitbit</h2><ol class="steps">
          <li>In the Fitbit app, go to <strong>Today → ECG</strong> (or Health metrics → ECG) and open a reading.</li>
          <li>Choose <strong>Export PDF for your doctor</strong> and save or share the PDF.</li>
          <li>Drop it here.</li></ol></div>
      </div>
      <div class="card"><h2>Automatic import folder</h2>
        ${st.import_dir_ok
          ? `<p>Watching <code>${esc(st.import_dir)}</code> every ${st.import_interval_s} s. Any PDF saved there (for example, a Google Drive folder synced to your server) is imported automatically. Files are never moved or deleted.</p>`
          : `<p class="muted">Not set up. Mount a folder at <code>/import</code> in <code>docker-compose.yml</code> (e.g. a synced Google Drive folder), and new PDFs saved there will import on their own.</p>`}
      </div>
    </div>`;
  const drop = $("#drop"), input = $("#file");
  ["dragenter", "dragover"].forEach((e) => drop.addEventListener(e, (ev) => { ev.preventDefault(); drop.classList.add("over"); }));
  ["dragleave", "drop"].forEach((e) => drop.addEventListener(e, (ev) => { ev.preventDefault(); drop.classList.remove("over"); }));
  drop.addEventListener("drop", (ev) => upload(ev.dataTransfer.files));
  input.addEventListener("change", () => upload(input.files));
}

async function upload(files) {
  if (!files.length) return;
  const out = $("#results");
  out.innerHTML = `<div class="card"><p class="muted">Reading ${files.length} file${files.length > 1 ? "s" : ""}…</p></div>`;
  const fd = new FormData();
  [...files].forEach((f) => fd.append("files", f));
  try {
    const { results } = await api("/api/import", { method: "POST", body: fd });
    const icon = { imported: ["info", "Imported"], duplicate: ["plain", "Already here"], error: ["flag", "Couldn't read"] };
    out.innerHTML = `<div class="card"><h2>Results</h2><table><tbody>${results.map((r) => `<tr>
      <td><span class="badge ${icon[r.status][0]}">${icon[r.status][1]}</span></td><td>${esc(r.filename)}</td>
      <td class="small">${esc(r.message)}</td><td>${r.id ? `<a href="#/recordings/${r.id}">View →</a>` : ""}</td></tr>`).join("")}</tbody></table></div>`;
  } catch (e) { out.innerHTML = `<div class="card"><p>Upload failed: ${esc(e.message)}</p></div>`; }
}

// ---------- doctor report ----------
async function report() {
  const [s, recs, syms] = await Promise.all([api("/api/summary"), api("/api/recordings"), api("/api/symptoms")]);
  const flagged = recs.filter((r) => r.flags || levelOf(r.determination) !== "info");
  view.innerHTML = `
    <div class="report">
      <div class="row between no-print" style="margin-bottom:16px"><span class="muted">A one-page summary to print or save as PDF for your doctor.</span>
        <button class="btn primary" onclick="window.print()">Print / Save PDF</button></div>
      <h1>Heart rhythm recordings summary</h1>
      <div class="muted">${s.first ? `${fmtDate(s.first)} – ${fmtDate(s.last)}` : "No recordings"} · generated ${fmtDate(new Date())}</div>
      <section><div class="tiles">
        <div class="tile"><div class="label">Recordings</div><div class="value">${s.recording_count}</div></div>
        <div class="tile"><div class="label">Average HR</div><div class="value">${s.hr_avg ?? "–"} <small>bpm</small></div></div>
        <div class="tile"><div class="label">Symptom entries</div><div class="value">${s.symptom_count}</div><div class="sub">${s.symptoms_with_recording} with ECG ±1 h</div></div>
        <div class="tile"><div class="label">Recordings w/ early beats</div><div class="value">${s.early_beat_recordings}</div></div>
      </div></section>
      <section><h2>Device results</h2><p>${Object.entries(s.by_determination).map(([d, n]) => `${badge(d)} × ${n}`).join("&nbsp;&nbsp; ")}</p></section>
      <section class="chart"><h2>Heart rate per recording</h2><div id="trend"></div></section>
      <section><h2>Symptoms and matching recordings</h2>
        ${syms.length ? `<table><thead><tr><th>When</th><th>Symptom</th><th>Strength</th><th>Activity / notes</th><th>ECG within 1 h</th></tr></thead><tbody>
          ${syms.map((x) => `<tr><td>${fmtDT(x.occurred_at)}</td><td>${esc(x.kind)}${x.duration_min ? ` (~${x.duration_min} min)` : ""}</td><td>${x.severity ? x.severity + "/5" : ""}</td>
          <td class="small">${esc([x.activity, x.notes].filter(Boolean).join(" — "))}</td>
          <td class="small">${x.recordings.map((r) => `${esc(r.determination)} (${r.minutes_apart} min)`).join("<br>") || "–"}</td></tr>`).join("")}</tbody></table>`
          : `<p class="muted">No symptoms logged.</p>`}</section>
      <section><h2>Recordings worth a look</h2>
        ${flagged.length ? `<table><thead><tr><th>When</th><th>Device</th><th>Result</th><th>HR</th><th>Findings</th></tr></thead><tbody>
          ${flagged.map((r) => `<tr><td>${fmtDT(r.recorded_at)}</td><td>${esc(r.device)}</td><td>${badge(r.determination)}</td><td>${r.hr_mean ? Math.round(r.hr_mean) : "–"}</td>
          <td class="small">${[r.early_beats && `${r.early_beats} early beat(s)`, r.pauses && `${r.pauses} pause(s)`, r.quality === "poor" && "poor signal"].filter(Boolean).join(", ") || "–"}</td></tr>`).join("")}</tbody></table>`
          : `<p class="muted">None: every recording had a normal device result and no early beats or pauses detected.</p>`}</section>
      <section><h2>All recordings</h2><table><thead><tr><th>When</th><th>Device</th><th>Result</th><th>HR (range)</th><th>RMSSD</th></tr></thead><tbody>
        ${recs.map((r) => `<tr><td>${fmtDT(r.recorded_at)}</td><td>${esc(r.device)}</td><td>${esc(r.determination)}</td>
        <td class="num">${r.hr_mean ? `${Math.round(r.hr_mean)} (${r.hr_min}–${r.hr_max})` : "–"}</td><td class="num">${r.rmssd_ms ?? "–"} ms</td></tr>`).join("")}</tbody></table></section>
      <p class="muted small" style="margin-top:24px">Heart rate, early-beat and variability figures were computed by the Heart Monitor app from the raw traces in the
        exported device PDFs. Device results are the manufacturers' own classifications. Not a diagnosis; original PDFs are available for review.</p>
    </div>`;
  trendChart($("#trend"), s.trend);
}

route();
