"""OFS-style preview player: video + live position bar + scrolling action timeline + speed heatmap.

Produces a self-contained HTML document; the web UI embeds it in an <iframe srcdoc> so its script runs.
"""

from __future__ import annotations

import html
import json
import re

from funscript_gen import i18n
from funscript_gen.export.funscript import Funscript
from funscript_gen.multiaxis import MAIN_AXIS

AXIS_STRIP_PX = 62  # what one axis strip adds to the player: its canvas (58 px) and the gap

_PLAYER = r"""<!doctype html>
<html lang="__LANG__">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>funscript preview</title>
<style>
:root {
  --bg: #ffffff; --panel: #f4f4f5; --text: #18181b; --muted: #71717a; --grid: #d4d4d8;
  --line: #ea580c; --axis: #2563eb; --ref: #52525b; --cursor: #dc2626; --scene: #a1a1aa; --fill: #ea580c;
  --check: rgba(234, 179, 8, .22); --checkline: #ca8a04;
}
@media (prefers-color-scheme: dark) {
  :root { --bg: #0b0f19; --panel: #1f2937; --text: #e5e7eb; --muted: #9ca3af; --grid: #374151;
          --line: #fb923c; --axis: #60a5fa; --ref: #9ca3af; --cursor: #f87171; --scene: #6b7280; --fill: #fb923c;
          --check: rgba(250, 204, 21, .18); --checkline: #facc15; }
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--text); font: 13px/1.4 system-ui, sans-serif; }
#wrap { display: flex; flex-direction: column; gap: 6px; padding: 6px; }
#top { display: flex; gap: 6px; align-items: stretch; }
#vwrap { flex: 1; min-width: 0; position: relative; display: flex; }
#video { width: 100%; max-height: calc(100vh - 380px - __AXH__px);  /* the iframe grows with the axis strips: the video does not */ background: #000; border-radius: 6px; }
#roi { position: absolute; pointer-events: none; display: none; background: none; border-radius: 0; }  /* over the video */
#bar { width: 56px; background: var(--panel); border-radius: 6px; position: relative; overflow: hidden; }
#barfill { position: absolute; left: 0; right: 0; bottom: 0; background: var(--fill); opacity: .85; }
#barref { position: absolute; left: 0; right: 0; height: 3px; background: var(--ref); display: none; }
#barval { position: absolute; top: 4px; width: 100%; text-align: center; font-weight: 600;
          font-variant-numeric: tabular-nums; mix-blend-mode: difference; color: #fff; }
canvas { width: 100%; display: block; background: var(--panel); border-radius: 6px; cursor: pointer; }
#timeline { height: 190px; }
#axes { display: flex; flex-direction: column; gap: 4px; }
canvas.axis { height: 58px; }
#overview { height: 34px; }
#info { display: flex; flex-wrap: wrap; gap: 4px 16px; color: var(--muted); font-variant-numeric: tabular-nums; }
#info b { color: var(--text); font-weight: 600; }
#err { color: var(--cursor); display: none; }
.key { border: 1px solid var(--grid); border-radius: 3px; padding: 0 4px; }
#nextcheck { display: none; font: inherit; color: var(--text); background: var(--check); border: 1px solid var(--checkline);
             border-radius: 4px; padding: 0 8px; cursor: pointer; }
#icheck { color: var(--checkline); font-weight: 600; }
#iedit { color: var(--cursor); font-weight: 600; }
#info button.small { font: inherit; color: var(--text); background: var(--panel); border: 1px solid var(--grid);
                     border-radius: 4px; padding: 0 6px; cursor: pointer; }
#info input[type=number] { font: inherit; width: 3.5em; color: var(--text); background: var(--panel);
                           border: 1px solid var(--grid); border-radius: 4px; padding: 0 2px; }
#help { display: none; flex-wrap: wrap; gap: 4px 16px; padding: 4px 8px; border: 1px solid var(--line);
        border-radius: 6px; font-variant-numeric: tabular-nums; }
body.editing #help { display: flex; }
body.editing #timeline { outline: 2px solid var(--line); cursor: crosshair; }
body.editing #bar { cursor: ns-resize; }
</style>
</head>
<body>
<div id="wrap">
  <div id="top">
    <div id="vwrap"><video id="video" controls preload="metadata" src="__VIDEO__"></video><canvas id="roi"></canvas></div>
    <div id="bar" title="@@preview.bar_title@@"><div id="barfill"></div><div id="barref"></div><div id="barval">-</div></div>
  </div>
  <div id="err">@@preview.err@@</div>
  <canvas id="timeline" title="@@preview.timeline_title@@"></canvas>
  <div id="axes">__AXES__</div>
  <canvas id="overview" title="@@preview.overview_title@@"></canvas>
  <div id="info">
    <span>@@preview.time@@ <b id="itime">0:00.000</b></span>
    <span>@@preview.scene@@ <b id="iscene">-</b><span id="icheck"></span></span>
    <span id="scenenav" title="@@preview.scenenav_title@@">
      <button class="small" id="prevscene">@@preview.prev_scene@@</button> <button class="small" id="nextscene">@@preview.next_scene@@</button>
      @@preview.scene_keys@@</span>
    <button id="nextcheck" title="@@preview.nextcheck_title@@">@@preview.nextcheck@@</button>
    <label title="@@preview.edit_title@@">
      <input type="checkbox" id="editon"> @@preview.edit@@<span id="iedit"></span></label>
    <span title="@@preview.scale_title@@">@@preview.scale@@
      <button class="small" id="scaledown">−</button><button class="small" id="scaleup">+</button>
      @@preview.scale_keys@@<b id="iscale"></b></span>
    <span title="@@preview.peaks_title@@">
      @@preview.top@@ <input type="number" id="topval" min="0" max="100" value="100"> <button class="small" id="settop">@@preview.set@@</button>
      @@preview.bottom@@ <input type="number" id="botval" min="0" max="100" value="0"> <button class="small" id="setbot">@@preview.set@@</button></span>
    <span title="@@preview.rate@@">@@preview.rate@@
      <button class="small" id="slower">−</button> <b id="irate">1×</b> <button class="small" id="faster">+</button>
      @@preview.rate_keys@@</span>
    <label id="roilabel" title="@@preview.roi_title@@">
      <input type="checkbox" id="roion" checked> @@preview.roi@@<b id="iroi"></b></label>
    <span>@@preview.position@@ <b id="ipos">-</b></span>
    <span>@@preview.speed@@ <b id="ispeed">-</b> @@preview.speed_unit@@</span>
    <span>@@preview.actions@@ <b id="icount">__COUNT__</b></span>
    <span>@@preview.window@@ <b id="iwin">10</b> @@preview.seconds@@</span>
    <span>@@preview.keys@@</span>
  </div>
  <div id="help">
    <b>@@preview.help.edit@@</b>
    <span>@@preview.help.select@@</span>
    <span>@@preview.help.move@@</span>
    <span>@@preview.help.add@@</span>
    <span>@@preview.help.delete@@</span>
    <span>@@preview.help.position@@</span>
    <span>@@preview.help.size@@</span>
    <span>@@preview.help.peaks@@</span>
    <span>@@preview.help.scope@@</span>
    <span>@@preview.help.undo@@</span>
    <span>@@preview.help.save@@</span>
  </div>
</div>
<script>
const DATA = __DATA__;
const I18N = __I18N__;  // the language pack's preview.js.* texts
function T(key, p) { let s = I18N[key] || key; for (const k in p || {}) s = s.split("{" + k + "}").join(p[k]); return s; }
const acts = DATA.actions, axes = DATA.axes, ref = DATA.reference, scenes = DATA.scenes, sceneList = DATA.scene_list;
const checks = sceneList.filter(x => (x.check || x.unsure) && !x.flipped);  // possibly upside down or no evidence for the direction, not flipped since
const hasRegions = sceneList.some(x => x.region);
const video = document.getElementById("video");
const tl = document.getElementById("timeline"), ov = document.getElementById("overview");
const axCanvas = Array.from(document.querySelectorAll("canvas.axis"));
const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
let windowS = 10;

function posAt(a, t) {  // linear interpolation of position at time t (ms)
  if (!a.length) return null;
  if (t <= a[0].at) return a[0].pos;
  if (t >= a[a.length - 1].at) return a[a.length - 1].pos;
  let lo = 0, hi = a.length - 1;
  while (hi - lo > 1) { const m = (lo + hi) >> 1; if (a[m].at <= t) lo = m; else hi = m; }
  const p = a[lo], q = a[hi];
  return p.pos + (q.pos - p.pos) * (t - p.at) / Math.max(1, q.at - p.at);
}
function sceneAt(t) {  // the scene playing at t (ms): the last one starting at or before it
  let s = null;
  for (const x of sceneList) { if (x.at <= t) s = x; else break; }
  return s;
}
function sceneEnd(s) {
  const k = sceneList.indexOf(s);
  return k + 1 < sceneList.length ? sceneList[k + 1].at : duration();
}
function nextCheck() {  // the next scene to check after the one playing, wrapping around
  if (!checks.length) return;
  const t = video.currentTime * 1000, cur = sceneAt(t);
  const s = checks.find(x => x.at > t && x !== cur) || checks[0];
  video.currentTime = s.at / 1000;
  video.play().catch(() => {});
}
function jumpScene(fwd) {  // to the start of the next scene, or of the one before the scene playing
  const starts = [0, ...scenes], t = video.currentTime * 1000 + 1;  // + 1: a seek to a start can land just before it
  const k = starts.filter(s => s <= t).length - 1 + (fwd ? 1 : -1);
  if (k < starts.length) video.currentTime = starts[Math.max(0, k)] / 1000;
}
function speedAt(a, t) {
  if (a.length < 2) return 0;
  let i = a.findIndex(x => x.at > t);
  if (i <= 0) return 0;
  return Math.abs(a[i].pos - a[i - 1].pos) / Math.max(1, a[i].at - a[i - 1].at) * 1000;
}
function speedColor(v) {  // OFS-like heat: slow blue -> green -> yellow -> red
  const h = 240 - Math.min(1, v / 500) * 240;
  return `hsl(${h}, 85%, 50%)`;
}
function fmt(ms) {
  const s = Math.max(0, ms) / 1000, m = Math.floor(s / 60);
  return `${m}:${(s - m * 60).toFixed(3).padStart(6, "0")}`;
}
function setup(c) {
  const r = c.getBoundingClientRect(), d = window.devicePixelRatio || 1;
  if (c.width !== Math.round(r.width * d) || c.height !== Math.round(r.height * d)) {
    c.width = Math.round(r.width * d); c.height = Math.round(r.height * d);
  }
  const g = c.getContext("2d"); g.setTransform(d, 0, 0, d, 0, 0);
  return [g, r.width, r.height];
}
function duration() {
  const last = Math.max(acts.length ? acts[acts.length - 1].at : 0, ref.length ? ref[ref.length - 1].at : 0);
  return isFinite(video.duration) && video.duration > 0 ? video.duration * 1000 : last + 1000;
}

function drawSeries(g, a, t0, t1, x, y, color, width, dots) {
  if (!a.length) return;
  let i = 0;
  while (i < a.length - 1 && a[i + 1].at < t0) i++;
  g.strokeStyle = color; g.lineWidth = width; g.beginPath();
  let started = false;
  for (let j = i; j < a.length; j++) {
    const px = x(a[j].at), py = y(a[j].pos);
    started ? g.lineTo(px, py) : g.moveTo(px, py); started = true;
    if (a[j].at > t1) break;
  }
  g.stroke();
  if (dots) {
    g.fillStyle = color;
    for (let j = i; j < a.length && a[j].at <= t1; j++) {
      g.beginPath(); g.arc(x(a[j].at), y(a[j].pos), 3, 0, 2 * Math.PI); g.fill();
    }
  }
}

function geom(t) {  // the timeline's mapping between (ms, pos) and canvas pixels around time t
  const r = tl.getBoundingClientRect(), w = r.width, h = r.height;
  const pad = 14, half = windowS * 500, t0 = t - half, t1 = t + half;
  return { w, h, t0, t1, x: ms => (ms - t0) / (t1 - t0) * w, y: p => pad + (1 - p / 100) * (h - 2 * pad),
           ms: px => t0 + px / w * (t1 - t0), pos: py => Math.round(Math.min(100, Math.max(0, (1 - (py - pad) / (h - 2 * pad)) * 100))) };
}
function drawTimeline(t) {
  const [g, w, h] = setup(tl);
  const { t0, t1, x, y } = geom(t);
  g.clearRect(0, 0, w, h);
  g.strokeStyle = css("--grid"); g.lineWidth = 1; g.fillStyle = css("--muted"); g.font = "10px system-ui";
  for (const p of [0, 50, 100]) { g.beginPath(); g.moveTo(0, y(p)); g.lineTo(w, y(p)); g.stroke(); g.fillText(p, 3, y(p) - 2); }
  const step = windowS > 30 ? 5000 : windowS > 12 ? 2000 : 1000;
  for (let s = Math.ceil(t0 / step) * step; s <= t1; s += step) {
    if (s < 0) continue;
    g.beginPath(); g.moveTo(x(s), h - 10); g.lineTo(x(s), h); g.stroke();
    g.fillText(fmt(s).replace(/\.\d+$/, ""), x(s) + 2, h - 2);
  }
  if (axes.length) { g.fillStyle = css("--text"); g.font = "600 11px system-ui"; g.fillText(DATA.main_label, 30, 12); }
  g.fillStyle = css("--check");
  for (const s of checks) { const a = x(s.at), b = x(sceneEnd(s)); if (b > 0 && a < w) g.fillRect(a, 0, b - a, h); }
  g.setLineDash([4, 4]); g.strokeStyle = css("--scene");
  for (const s of scenes) if (s > t0 && s < t1) { g.beginPath(); g.moveTo(x(s), 0); g.lineTo(x(s), h); g.stroke(); }
  g.setLineDash([]);
  drawSeries(g, ref, t0, t1, x, y, css("--ref"), 1.2, false);
  drawSeries(g, acts, t0, t1, x, y, css("--line"), 2, true);
  if (editing && selected.size) {
    g.strokeStyle = css("--text"); g.lineWidth = 2;
    for (const a of selected) if (a.at >= t0 && a.at <= t1) { g.beginPath(); g.arc(x(a.at), y(a.pos), 7, 0, 2 * Math.PI); g.stroke(); }
    g.fillStyle = css("--text"); g.font = "11px system-ui";
    const a = [...selected][0];
    g.fillText(selected.size > 1 ? T("preview.js.selected", {n: selected.size}) : `${fmt(a.at)}  ${a.pos}`,
               Math.min(w - 120, Math.max(0, x(a.at) + 10)), Math.max(12, y(a.pos) - 10));
  }
  if (band) {
    g.strokeStyle = css("--text"); g.lineWidth = 1; g.setLineDash([3, 3]);
    g.strokeRect(x(band.ms0), y(band.pos0), x(band.ms1) - x(band.ms0), y(band.pos1) - y(band.pos0));
    g.setLineDash([]);
  }
  g.strokeStyle = css("--cursor"); g.lineWidth = 2;
  g.beginPath(); g.moveTo(w / 2, 0); g.lineTo(w / 2, h); g.stroke();
}

// The other axes of a multi-axis script: one strip each under the timeline, in the same time window and with the same
// cursor. They are shown, not edited.
function drawAxes(t) {
  if (!axes.length) return;
  const { t0, t1, x } = geom(t);
  axes.forEach((ax, k) => {
    const [g, w, h] = setup(axCanvas[k]), pad = 6, y = p => pad + (1 - p / 100) * (h - 2 * pad);
    g.clearRect(0, 0, w, h);
    g.strokeStyle = css("--grid"); g.lineWidth = 1;
    for (const p of [0, 50, 100]) { g.beginPath(); g.moveTo(0, y(p)); g.lineTo(w, y(p)); g.stroke(); }
    drawSeries(g, ax.actions, t0, t1, x, y, css("--axis"), 1.8, false);
    g.strokeStyle = css("--cursor"); g.lineWidth = 2;
    g.beginPath(); g.moveTo(w / 2, 0); g.lineTo(w / 2, h); g.stroke();
    const p = posAt(ax.actions, t);
    if (p !== null) { g.fillStyle = css("--axis"); g.beginPath(); g.arc(w / 2, y(p), 4, 0, 2 * Math.PI); g.fill(); }
    const label = ax.id + " " + ax.label + "  " + (p === null ? "-" : Math.round(p));
    g.font = "600 11px system-ui";
    g.globalAlpha = .85; g.fillStyle = css("--panel"); g.fillRect(28, 2, g.measureText(label).width + 8, 15); g.globalAlpha = 1;
    g.fillStyle = css("--text"); g.fillText(label, 32, 13);
  });
}

let heat = null;  // cached overview background
function drawOverview(t) {
  const [g, w, h] = setup(ov);
  const dur = duration();
  if (!heat || heat.w !== w || heat.dur !== dur) {
    const off = document.createElement("canvas"), d = window.devicePixelRatio || 1;
    off.width = Math.round(w * d); off.height = Math.round(h * d);
    const o = off.getContext("2d"); o.setTransform(d, 0, 0, d, 0, 0);
    for (let i = 1; i < acts.length; i++) {
      const a = acts[i - 1], b = acts[i];
      const v = Math.abs(b.pos - a.pos) / Math.max(1, b.at - a.at) * 1000;
      o.fillStyle = speedColor(v);
      const x0 = a.at / dur * w, x1 = Math.max(x0 + 0.5, b.at / dur * w);
      o.fillRect(x0, 0, x1 - x0, h);
    }
    o.strokeStyle = "rgba(255,255,255,.55)"; o.lineWidth = 1; o.beginPath();
    acts.forEach((a, i) => { const px = a.at / dur * w, py = 2 + (1 - a.pos / 100) * (h - 4); i ? o.lineTo(px, py) : o.moveTo(px, py); });
    o.stroke();
    heat = { w, dur, canvas: off };
  }
  g.clearRect(0, 0, w, h);
  g.drawImage(heat.canvas, 0, 0, w, h);
  g.fillStyle = css("--checkline");
  for (const s of checks) { const a = s.at / dur * w; g.fillRect(a, 0, Math.max(2, sceneEnd(s) / dur * w - a), 4); }
  g.fillStyle = "rgba(0,0,0,.18)"; g.fillRect(t / dur * w - windowS * 500 / dur * w, 0, windowS * 1000 / dur * w, h);
  g.strokeStyle = css("--cursor"); g.lineWidth = 2;
  g.beginPath(); g.moveTo(t / dur * w, 0); g.lineTo(t / dur * w, h); g.stroke();
}

const roiCanvas = document.getElementById("roi"), roiOn = document.getElementById("roion");
function regionsAt(sc, t) {  // [[box 0..1 or null = whole frame, label, in use], ...] of the scene at t
  const r = sc && sc.region;
  if (!r) return [];
  if (!r.hybrid) return [[r.box, T("preview.js.region"), true]];
  let focus = false;  // the nearest key frame's decision, as frame_choice
  if (r.box && r.dec.length) focus = r.dec.reduce((a, b) => Math.abs(b[0] - t) < Math.abs(a[0] - t) ? b : a)[1];
  const out = [[r.alt, T("preview.js.region_general"), !focus]];
  if (r.box) out.push([r.box, T("preview.js.region_genital"), focus]);
  return out;
}
function drawRegions(t) {
  const show = hasRegions && roiOn.checked;
  roiCanvas.style.display = show ? "block" : "none";
  const shown = show ? regionsAt(sceneAt(t), t) : [];
  document.getElementById("iroi").textContent = shown.length
    ? T("preview.js.colon") + shown.filter(x => x[2]).map(x => x[1] + (x[0] ? "" : T("preview.js.whole_frame"))).join("") : "";
  if (!show) return;
  roiCanvas.style.left = video.offsetLeft + "px"; roiCanvas.style.top = video.offsetTop + "px";
  roiCanvas.style.width = video.clientWidth + "px"; roiCanvas.style.height = video.clientHeight + "px";
  const [g, w, h] = setup(roiCanvas);
  g.clearRect(0, 0, w, h);
  if (!video.videoWidth || !shown.length) return;
  const k = Math.min(w / video.videoWidth, h / video.videoHeight);  // the picture inside the element (contain)
  const pw = video.videoWidth * k, ph = video.videoHeight * k, ox = (w - pw) / 2, oy = (h - ph) / 2;
  g.font = "600 12px system-ui"; g.textBaseline = "top";
  for (const [box, label, used] of shown) {
    const [x1, y1, x2, y2] = box || [0, 0, 1, 1];
    const x = ox + x1 * pw, y = oy + y1 * ph, bw = (x2 - x1) * pw, bh = (y2 - y1) * ph;
    if (!used) {  // dark under the dashes, so they show on bright pictures too
      g.setLineDash([]); g.lineWidth = 3; g.strokeStyle = "rgba(0,0,0,.45)"; g.strokeRect(x + 1.5, y + 1.5, bw - 3, bh - 3);
    }
    g.setLineDash(used ? [] : [6, 4]); g.lineWidth = used ? 3 : 1.5;
    g.strokeStyle = used ? css("--line") : "rgba(255,255,255,.9)";
    g.strokeRect(x + 1.5, y + 1.5, bw - 3, bh - 3);
    g.setLineDash([]); g.fillStyle = "rgba(0,0,0,.6)";
    const tw = g.measureText(label).width + 8;
    g.fillRect(x + 2, y + 2, tw, 17);
    g.fillStyle = used ? css("--line") : "#fff"; g.fillText(label, x + 6, y + 4);
  }
}
const fill = document.getElementById("barfill"), refm = document.getElementById("barref"), val = document.getElementById("barval");
function frame() {
  if (!tl.getBoundingClientRect().width) { requestAnimationFrame(frame); return; }  // hidden (other tab): nothing to draw
  const t = video.currentTime * 1000;
  const p = posAt(acts, t), rp = posAt(ref, t);
  fill.style.height = p === null ? "0" : p + "%";
  val.textContent = p === null ? "-" : Math.round(p);
  if (rp !== null) { refm.style.display = "block"; refm.style.bottom = `calc(${rp}% - 1px)`; }
  document.getElementById("itime").textContent = fmt(t);
  document.getElementById("ipos").textContent = p === null ? "-" : Math.round(p) + (rp !== null ? T("preview.js.reference", {n: Math.round(rp)}) : "");
  document.getElementById("ispeed").textContent = Math.round(speedAt(acts, t));
  document.getElementById("icount").textContent = acts.length;
  const sc = sceneAt(t);
  document.getElementById("iscene").textContent = sc === null ? "-" : sc.i + (sc.flipped ? T("preview.js.flipped") : "");
  document.getElementById("icheck").textContent = sc !== null && checks.includes(sc) ? T(sc.check ? "preview.js.check" : "preview.js.unsure") : "";
  document.getElementById("iscale").textContent =
    scaled && scaled.at === dirty && scaled.key === target().key ? ` ×${scaled.factor.toFixed(2)}` : "";
  drawTimeline(t); drawAxes(t); drawOverview(t); drawRegions(t);
  requestAnimationFrame(frame);
}

// Editing: the actions are changed in place; window.getEdits() gives them to the page around the player (the
// 儲存編輯 / 反轉 buttons), or null when nothing changed.
// The selection is a set of the action objects themselves, so it survives the inserts and deletes around it.
let editing = false, selected = new Set(), drag = null, band = null, pan = null, barDrag = null, held = false, dirty = 0;
const undo = [], editOn = document.getElementById("editon");
function edited() {
  dirty++; heat = null;
  document.getElementById("iedit").textContent = T("preview.js.unsaved");
}
function snapshot() { undo.push(acts.map(a => ({ ...a }))); if (undo.length > 200) undo.shift(); }
function setEditing(on) { editing = on; editOn.checked = on; document.body.classList.toggle("editing", on); if (!on) selected.clear(); }
function select(...as) { selected = new Set(as.filter(Boolean)); }
function selectedIdx() { return acts.map((a, k) => selected.has(a) ? k : -1).filter(k => k >= 0); }
// What the amplitude and top / bottom tools change: the selected actions when two or more are selected while
// editing, otherwise the scene playing.
function target() {
  if (editing && selected.size > 1) { const idx = selectedIdx(); return { idx, key: "sel " + idx.join(","), sel: true }; }
  const t = video.currentTime * 1000, sc = sceneAt(t), t0 = sc ? sc.at : 0, t1 = sc ? sceneEnd(sc) : Infinity;
  const idx = [];
  acts.forEach((a, k) => { if (a.at >= t0 && a.at < t1) idx.push(k); });
  return { idx, key: "scene " + t0, sel: false };
}
function hit(e) {  // the action under the mouse (within 8 px) and the mouse in timeline terms
  const r = tl.getBoundingClientRect(), G = geom(video.currentTime * 1000);
  const px = e.clientX - r.left, py = e.clientY - r.top;
  let best = -1, bd = 64;
  acts.forEach((a, k) => {
    if (a.at < G.t0 || a.at > G.t1) return;
    const d = (G.x(a.at) - px) ** 2 + (G.y(a.pos) - py) ** 2;
    if (d < bd) { bd = d; best = k; }
  });
  return { k: best, ms: Math.round(G.ms(px)), pos: G.pos(py) };
}
// How far the selected actions (indices idx, ascending) can move together in time: each run of selected neighbours
// stays between the unselected actions around it, so the order never changes.
function moveLimits(idx) {
  let lo = -acts[idx[0]].at, hi = Infinity;
  idx.forEach((k, j) => {
    if (j === 0 || idx[j - 1] !== k - 1) { if (k > 0) lo = Math.max(lo, acts[k - 1].at + 1 - acts[k].at); }
    if (j === idx.length - 1 || idx[j + 1] !== k + 1) { if (k + 1 < acts.length) hi = Math.min(hi, acts[k + 1].at - 1 - acts[k].at); }
  });
  return [lo, hi];
}
window.getEdits = () => dirty ? acts.map(a => [a.at, a.pos]) : null;
editOn.addEventListener("change", () => setEditing(editOn.checked));
tl.addEventListener("contextmenu", e => e.preventDefault());
tl.addEventListener("mousedown", e => {
  held = false;
  if (e.button === 2) {  // right drag: scroll the timeline
    pan = { x: e.clientX, t: video.currentTime, play: !video.paused };
    video.pause(); tl.style.cursor = "grabbing"; return;
  }
  if (e.button !== 0 || !editing) return;
  const h = hit(e);
  if (h.k < 0) { band = { ms0: h.ms, pos0: h.pos, ms1: h.ms, pos1: h.pos, add: e.shiftKey, x: e.clientX, y: e.clientY }; return; }
  held = true; video.pause();
  const a = acts[h.k];
  if (e.shiftKey) { if (selected.has(a)) { selected.delete(a); return; } selected.add(a); }
  else if (!selected.has(a)) select(a);
  const idx = selectedIdx();
  drag = { ms: h.ms, pos: h.pos, base: idx.map(k => ({ ...acts[k] })), idx, lim: moveLimits(idx), moved: false };
});
// Position bar while editing: dragging on it sets the position of the selected action (the first one when several
// are selected; the others move with it, as far as 0 or 100 allow). The video seeks to that action, so the frame
// and the bar show what is being set.
const bar = document.getElementById("bar");
function barMove(e) {
  const r = bar.getBoundingClientRect(), { idx, base } = barDrag;
  const p = Math.round(Math.min(100, Math.max(0, (1 - (e.clientY - r.top) / r.height) * 100)));
  const d = Math.min(100 - Math.max(...base), Math.max(-Math.min(...base), p - base[0]));
  if (acts[idx[0]].pos === base[0] + d) return;
  if (!barDrag.moved) { snapshot(); barDrag.moved = true; }
  idx.forEach((k, j) => { acts[k].pos = base[j] + d; });
  edited();
}
bar.addEventListener("mousedown", e => {
  if (e.button !== 0 || !editing || !selected.size) return;
  e.preventDefault();
  const idx = selectedIdx();
  video.pause(); video.currentTime = acts[idx[0]].at / 1000;
  barDrag = { idx, base: idx.map(k => acts[k].pos), moved: false };
  barMove(e);
});
window.addEventListener("mousemove", e => {
  if (barDrag) { barMove(e); return; }
  if (pan) {
    const w = tl.getBoundingClientRect().width;
    video.currentTime = Math.max(0, pan.t - (e.clientX - pan.x) / w * windowS); return;
  }
  if (band) { const h = hit(e); band.ms1 = h.ms; band.pos1 = h.pos; return; }
  if (!drag) return;
  const h = hit(e), { base, idx, lim } = drag;
  if (!drag.moved) { snapshot(); drag.moved = true; }
  const lo = Math.min(...base.map(a => a.pos)), hi = Math.max(...base.map(a => a.pos));
  const dt = Math.min(lim[1], Math.max(lim[0], h.ms - drag.ms)), dp = Math.min(100 - hi, Math.max(-lo, h.pos - drag.pos));
  idx.forEach((k, j) => { acts[k].at = base[j].at + dt; acts[k].pos = base[j].pos + dp; });
  edited();
});
window.addEventListener("mouseup", e => {
  if (pan) { if (pan.play) video.play().catch(() => {}); pan = null; tl.style.cursor = ""; }
  if (band) {
    if (Math.abs(e.clientX - band.x) + Math.abs(e.clientY - band.y) > 4) {  // a drag, not a click: no seek
      held = true;
      const [m0, m1] = [band.ms0, band.ms1].sort((a, b) => a - b), [p0, p1] = [band.pos0, band.pos1].sort((a, b) => a - b);
      const inside = acts.filter(a => a.at >= m0 && a.at <= m1 && a.pos >= p0 && a.pos <= p1);
      if (band.add) inside.forEach(a => selected.add(a)); else select(...inside);
    } else if (!band.add) selected.clear();
    band = null;
  }
  drag = null; barDrag = null;
});
tl.addEventListener("click", e => {
  if (held) return;  // a click on an action selects it, it does not seek
  const r = tl.getBoundingClientRect(), t = video.currentTime * 1000;
  video.currentTime = Math.max(0, (t + ((e.clientX - r.left) / r.width - 0.5) * windowS * 1000) / 1000);
});
tl.addEventListener("dblclick", e => {
  if (!editing) return;
  const h = hit(e);
  if (h.k >= 0 || h.ms < 0 || acts.some(a => a.at === h.ms)) return;
  snapshot();
  let k = acts.findIndex(a => a.at > h.ms); if (k < 0) k = acts.length;
  acts.splice(k, 0, { at: h.ms, pos: h.pos }); select(acts[k]);
  edited();
});
function editKey(e) {  // true when the key was an editing command
  if (e.key === "Delete" || e.key === "Backspace") {
    if (!selected.size) return true;
    snapshot();
    const k = acts.findIndex(a => selected.has(a));
    acts.splice(0, acts.length, ...acts.filter(a => !selected.has(a)));
    select(selected.size === 1 ? acts[Math.min(k, acts.length - 1)] : null);  // one deleted: on to the next
    edited(); return true;
  }
  if (e.key === "ArrowUp" || e.key === "ArrowDown") {  // the selection moves together, as far as 0 or 100 allow
    if (!selected.size) return true;
    const ps = [...selected].map(a => a.pos);
    const d = Math.min(100 - Math.max(...ps), Math.max(-Math.min(...ps), (e.key === "ArrowUp" ? 1 : -1) * (e.shiftKey ? 1 : 5)));
    if (!d) return true;
    snapshot(); selected.forEach(a => { a.pos += d; });
    edited(); return true;
  }
  if ((e.key === "z" || e.key === "Z") && (e.ctrlKey || e.metaKey)) {
    if (undo.length) { acts.splice(0, acts.length, ...undo.pop()); selected.clear(); edited(); }
    return true;
  }
  if (e.key === "a" || e.key === "A" || e.key === "Insert") {
    if (e.ctrlKey || e.metaKey) return false;
    const t = Math.round(video.currentTime * 1000), same = acts.findIndex(a => a.at === t);
    if (same >= 0) { select(acts[same]); return true; }
    snapshot();
    let k = acts.findIndex(a => a.at > t); if (k < 0) k = acts.length;
    const p = posAt(acts, t);
    acts.splice(k, 0, { at: t, pos: p === null ? 50 : Math.round(p) }); select(acts[k]);
    edited(); return true;
  }
  if (e.key === "Escape") { selected.clear(); return true; }
  return false;
}

// Amplitude of the scene playing (or of the selected actions): each stroke is scaled around its own middle, so strokes that drift up or down
// within the scene keep their level instead of being pushed against 0 or 100. A point is moved around the mean of
// the middles of the strokes on either side of it; a run of equal positions (a hold) counts as one point, so it stays
// flat. Repeated steps on the same scene with nothing edited in between scale the positions it had before the first
// step, so − undoes + exactly even where a step was clipped at 0 or 100.
function strokeCenters(base) {
  return base.map((p, j) => {
    let a = j, b = j;
    while (a > 0 && base[a] === p) a--;
    while (b < base.length - 1 && base[b] === p) b++;
    const mids = [a, b].filter(k => base[k] !== p).map(k => (p + base[k]) / 2);
    return mids.length ? mids.reduce((s, m) => s + m, 0) / mids.length : p;
  });
}
// Selected actions take their strokes from all the actions, so a point's unselected neighbours count too.
let scaled = null;  // {key, base: positions before the first step, centers, factor, at: the edit count after the last step}
function scaleScene(up) {
  const { idx, key, sel } = target();
  if (idx.length < 2) return;
  setEditing(true);
  if (!scaled || scaled.key !== key || scaled.at !== dirty) {
    const base = idx.map(k => acts[k].pos), all = sel ? strokeCenters(acts.map(a => a.pos)) : null;
    scaled = { key, base, centers: sel ? idx.map(k => all[k]) : strokeCenters(base), factor: 1 };
  }
  snapshot();
  scaled.factor = Math.min(5, Math.max(0.2, scaled.factor * (up ? 1.25 : 0.8)));
  const { base, centers, factor } = scaled;
  idx.forEach((k, j) => { acts[k].pos = Math.round(Math.min(100, Math.max(0, centers[j] + (base[j] - centers[j]) * factor))); });
  edited(); scaled.at = dirty;
}

// Tops and bottoms: the points nearest each crest and trough of the curve through the actions. A run of equal
// positions counts as one point; the first and last action are one when they end a stroke.
function turns(pos) {  // 1 at a top, -1 at a bottom, 0 between
  const kind = pos.map(() => 0);
  for (let a = 0; a < pos.length;) {
    let b = a;
    while (b + 1 < pos.length && pos[b + 1] === pos[a]) b++;
    const sides = [pos[a - 1], pos[b + 1]].filter(p => p !== undefined);
    kind.fill(!sides.length ? 0 : sides.every(p => p < pos[a]) ? 1 : sides.every(p => p > pos[a]) ? -1 : 0, a, b + 1);
    a = b + 1;
  }
  return kind;
}
// Positions with the tops (or bottoms) among the indices idx set to value; the points of idx between move with the
// stroke they lie on, keeping their fraction of it, so the strokes stay monotonic.
function setTurns(pos, idx, top, value) {
  const kind = turns(pos), want = top ? 1 : -1, inside = new Set(idx);
  const moved = k => kind[k] === want && inside.has(k) ? value : pos[k];
  const out = pos.slice();
  for (const k of idx) {
    if (kind[k]) { out[k] = moved(k); continue; }
    let a = k, b = k;
    while (a > 0 && !kind[a]) a--;
    while (b < pos.length - 1 && !kind[b]) b++;
    if (kind[a] && kind[b]) out[k] = Math.round(moved(a) + (pos[k] - pos[a]) / (pos[b] - pos[a]) * (moved(b) - moved(a)));
  }
  return out;
}
function levelScene(top) {
  const input = document.getElementById(top ? "topval" : "botval"), v = parseFloat(input.value);
  if (isNaN(v)) return;
  const value = Math.round(Math.min(100, Math.max(0, v)));
  input.value = value;
  try { localStorage.setItem(top ? "funscript-gen-top" : "funscript-gen-bottom", String(value)); } catch (_) {}
  const out = setTurns(acts.map(a => a.pos), target().idx, top, value);
  if (out.every((p, k) => p === acts[k].pos)) return;
  setEditing(true); snapshot();
  out.forEach((p, k) => { acts[k].pos = p; });
  edited();
}

// Playback speed, kept for the next player (it is rebuilt after a flip or a save).
const RATES = [0.25, 0.5, 0.75, 1, 1.25, 1.5, 2];
function setRate(r) {
  video.playbackRate = video.defaultPlaybackRate = r;
  document.getElementById("irate").textContent = r + "×";
  try { localStorage.setItem("funscript-gen-rate", String(r)); } catch (_) {}
}
function stepRate(up) {
  const k = RATES.indexOf(video.playbackRate), cur = k >= 0 ? k : RATES.indexOf(1);
  setRate(RATES[Math.min(RATES.length - 1, Math.max(0, cur + (up ? 1 : -1)))]);
}
function zoom(e) {
  e.preventDefault();
  windowS = Math.min(120, Math.max(2, windowS * (e.deltaY > 0 ? 1.2 : 1 / 1.2)));
  document.getElementById("iwin").textContent = windowS.toFixed(windowS < 10 ? 1 : 0);
}
tl.addEventListener("wheel", zoom, { passive: false });
for (const c of axCanvas) {  // the strips take the same wheel zoom and click-to-seek as the timeline
  c.addEventListener("wheel", zoom, { passive: false });
  c.addEventListener("click", e => {
    const r = c.getBoundingClientRect(), t = video.currentTime * 1000;
    video.currentTime = Math.max(0, (t + ((e.clientX - r.left) / r.width - 0.5) * windowS * 1000) / 1000);
  });
}
ov.addEventListener("click", e => {
  const r = ov.getBoundingClientRect();
  video.currentTime = (e.clientX - r.left) / r.width * duration() / 1000;
});
document.addEventListener("keydown", e => {
  if (e.target.tagName === "INPUT" && e.target.type !== "checkbox") return;
  const t = video.currentTime * 1000;
  if (e.key === "e" || e.key === "E") { if (!e.ctrlKey && !e.metaKey) { e.preventDefault(); setEditing(!editing); } return; }
  if (editing && editKey(e)) { e.preventDefault(); return; }
  if (e.key === " ") { e.preventDefault(); video.paused ? video.play() : video.pause(); }
  else if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
    e.preventDefault();
    const fwd = e.key === "ArrowRight";
    if (e.shiftKey) { video.currentTime = Math.max(0, video.currentTime + (fwd ? 5 : -5)); return; }
    const next = fwd ? acts.find(a => a.at > t + 1) : [...acts].reverse().find(a => a.at < t - 1);
    if (next) { video.currentTime = next.at / 1000; if (editing) select(next); }
  }
  else if (e.key === "n" || e.key === "N") { e.preventDefault(); nextCheck(); }
  else if (e.key === "PageUp" || e.key === "PageDown") { e.preventDefault(); jumpScene(e.key === "PageDown"); }
  else if (e.key === "-" || e.key === "_") { e.preventDefault(); scaleScene(false); }
  else if (e.key === "+" || e.key === "=") { e.preventDefault(); scaleScene(true); }
  else if (e.key === "[" || e.key === "]") { e.preventDefault(); stepRate(e.key === "]"); }
  else if ((e.key === "r" || e.key === "R") && hasRegions) { e.preventDefault(); roiOn.checked = !roiOn.checked; }
  else if (e.key === "." || e.key === ",") { video.pause(); video.currentTime = Math.max(0, video.currentTime + (e.key === "." ? 1 : -1) / DATA.fps); }
});
for (const [id, f] of [["scaledown", () => scaleScene(false)], ["scaleup", () => scaleScene(true)],
                       ["prevscene", () => jumpScene(false)], ["nextscene", () => jumpScene(true)],
                       ["settop", () => levelScene(true)], ["setbot", () => levelScene(false)],
                       ["slower", () => stepRate(false)], ["faster", () => stepRate(true)]]) {
  const b = document.getElementById(id);
  b.addEventListener("click", () => { f(); b.blur(); });  // keep the space key for play / pause
}
try { const r = parseFloat(localStorage.getItem("funscript-gen-rate")); if (RATES.includes(r)) setRate(r); } catch (_) {}
// Volume and mute, kept for the next player the same way (a new <video> starts at full volume).
try {
  const v = parseFloat(localStorage.getItem("funscript-gen-volume"));
  if (v >= 0 && v <= 1) video.volume = v;
  video.muted = localStorage.getItem("funscript-gen-muted") === "1";
} catch (_) {}
video.addEventListener("volumechange", () => {
  try {
    localStorage.setItem("funscript-gen-volume", String(video.volume));
    localStorage.setItem("funscript-gen-muted", video.muted ? "1" : "0");
  } catch (_) {}
});
for (const [id, key, top] of [["topval", "funscript-gen-top", true], ["botval", "funscript-gen-bottom", false]]) {
  const input = document.getElementById(id);
  try { const v = localStorage.getItem(key); if (v !== null && v !== "") input.value = v; } catch (_) {}
  input.addEventListener("keydown", e => { if (e.key === "Enter") { e.preventDefault(); levelScene(top); input.blur(); } });
}
const nb = document.getElementById("nextcheck");
if (checks.length) { nb.style.display = "inline-block"; nb.addEventListener("click", nextCheck); }
if (!hasRegions) document.getElementById("roilabel").style.display = "none";
if (!scenes.length) document.getElementById("scenenav").style.display = "none";
video.addEventListener("error", () => { document.getElementById("err").style.display = "block"; });
video.addEventListener("loadedmetadata", () => {
  heat = null;
  if (DATA.start_ms > 0) video.currentTime = DATA.start_ms / 1000;  // reopened after an edit: same place
  setRate(video.defaultPlaybackRate);  // loading resets playbackRate to the default
  if (DATA.play) video.play().catch(() => {});
});
requestAnimationFrame(frame);
</script>
</body>
</html>
"""


_VIEWER = r"""<!doctype html>
<html lang="__LANG__">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>multi-axis funscript</title>
<style>
:root {
  --bg: #ffffff; --panel: #f4f4f5; --text: #18181b; --muted: #71717a; --grid: #d4d4d8;
  --line: #ea580c; --axis: #2563eb; --cursor: #dc2626;
}
@media (prefers-color-scheme: dark) {
  :root { --bg: #0b0f19; --panel: #1f2937; --text: #e5e7eb; --muted: #9ca3af; --grid: #374151;
          --line: #fb923c; --axis: #60a5fa; --cursor: #f87171; }
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--text); font: 13px/1.4 system-ui, sans-serif; }
#sets { display: flex; flex-direction: column; gap: 14px; padding: 6px; }
.set { display: flex; flex-direction: column; gap: 4px; }
.head { display: flex; flex-wrap: wrap; gap: 4px 16px; align-items: baseline; }
.head .hint, .head .time { color: var(--muted); font-variant-numeric: tabular-nums; }
canvas { width: 100%; height: 58px; display: block; background: var(--panel); border-radius: 6px; cursor: crosshair; }
</style>
</head>
<body>
<div id="sets"></div>
<script>
const DATA = __DATA__;
const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
function posAt(a, t) {  // linear interpolation of position at time t (ms)
  if (!a.length) return null;
  if (t <= a[0].at) return a[0].pos;
  if (t >= a[a.length - 1].at) return a[a.length - 1].pos;
  let lo = 0, hi = a.length - 1;
  while (hi - lo > 1) { const m = (lo + hi) >> 1; if (a[m].at <= t) lo = m; else hi = m; }
  const p = a[lo], q = a[hi];
  return p.pos + (q.pos - p.pos) * (t - p.at) / Math.max(1, q.at - p.at);
}
function fmt(ms) {
  const s = Math.max(0, ms) / 1000, m = Math.floor(s / 60);
  return `${m}:${(s - m * 60).toFixed(1).padStart(4, "0")}`;
}
function setup(c) {
  const r = c.getBoundingClientRect(), d = window.devicePixelRatio || 1;
  if (c.width !== Math.round(r.width * d) || c.height !== Math.round(r.height * d)) {
    c.width = Math.round(r.width * d); c.height = Math.round(r.height * d);
  }
  const g = c.getContext("2d"); g.setTransform(d, 0, 0, d, 0, 0);
  return [g, r.width, r.height];
}
function build(set) {
  const root = document.createElement("div"); root.className = "set";
  const head = document.createElement("div"); head.className = "head";
  const title = document.createElement("b"); title.textContent = set.name;
  const time = document.createElement("span"); time.className = "time";
  const hint = document.createElement("span"); hint.className = "hint"; hint.textContent = "@@viewer.hint@@";
  head.append(title, time, hint); root.append(head);
  const dur = Math.max(1000, set.duration);
  let t0 = 0, t1 = dur, hover = null, pan = null;
  const canvases = set.axes.map((ax, k) => {
    const c = document.createElement("canvas"); root.append(c); return c;
  });
  function draw() {
    const x = (t, w) => (t - t0) / (t1 - t0) * w;
    const step = [1, 2, 5, 10, 30, 60, 120, 300, 600, 1800, 3600].find(s => s * 1000 * 8 >= t1 - t0) || 3600;
    set.axes.forEach((ax, k) => {
      const [g, w, h] = setup(canvases[k]), pad = 6, y = p => pad + (1 - p / 100) * (h - 2 * pad);
      g.clearRect(0, 0, w, h);
      g.strokeStyle = css("--grid"); g.lineWidth = 1; g.fillStyle = css("--muted"); g.font = "10px system-ui";
      for (const p of [0, 50, 100]) { g.beginPath(); g.moveTo(0, y(p)); g.lineTo(w, y(p)); g.stroke(); }
      for (let s = Math.ceil(t0 / 1000 / step) * step; s * 1000 <= t1; s += step) {
        g.beginPath(); g.moveTo(x(s * 1000, w), h - 8); g.lineTo(x(s * 1000, w), h); g.stroke();
        g.fillText(fmt(s * 1000), x(s * 1000, w) + 2, h - 1);
      }
      g.strokeStyle = css(k ? "--axis" : "--line"); g.lineWidth = 1.6; g.beginPath();
      let started = false;
      const a = ax.actions;
      let i = 0, j = a.length - 1;  // the actions that reach into the window, and one either side
      while (i < a.length - 1 && a[i + 1].at < t0) i++;
      while (j > 0 && a[j - 1].at > t1) j--;
      for (let n = i; n <= j; n++) {
        const px = x(a[n].at, w), py = y(a[n].pos);
        started ? g.lineTo(px, py) : g.moveTo(px, py); started = true;
      }
      g.stroke();
      let label = ax.id + " " + ax.label + " (" + a.length + ")";
      if (hover !== null) {
        const p = posAt(a, hover);
        g.strokeStyle = css("--cursor"); g.lineWidth = 1;
        g.beginPath(); g.moveTo(x(hover, w), 0); g.lineTo(x(hover, w), h); g.stroke();
        if (p !== null) label += "  " + Math.round(p);
      }
      g.font = "600 11px system-ui";
      g.globalAlpha = .85; g.fillStyle = css("--panel"); g.fillRect(2, 2, g.measureText(label).width + 8, 15); g.globalAlpha = 1;
      g.fillStyle = css("--text"); g.fillText(label, 6, 13);
    });
    time.textContent = hover === null ? fmt(t0) + " – " + fmt(t1) : fmt(hover);
  }
  const at = (e, c) => { const r = c.getBoundingClientRect(); return t0 + (e.clientX - r.left) / r.width * (t1 - t0); };
  canvases.forEach(c => {
    c.addEventListener("mousemove", e => {
      if (pan) {
        const r = c.getBoundingClientRect(), d = (e.clientX - pan.x) / r.width * (pan.t1 - pan.t0);
        const lo = Math.min(Math.max(0, pan.t0 - d), Math.max(0, dur - (pan.t1 - pan.t0)));
        t0 = lo; t1 = lo + (pan.t1 - pan.t0);
      }
      hover = at(e, c); draw();
    });
    c.addEventListener("mouseleave", () => { hover = null; pan = null; draw(); });
    c.addEventListener("mousedown", e => { pan = { x: e.clientX, t0, t1 }; });
    window.addEventListener("mouseup", () => { pan = null; });
    c.addEventListener("dblclick", () => { t0 = 0; t1 = dur; draw(); });
    c.addEventListener("wheel", e => {
      e.preventDefault();
      const m = at(e, c), f = e.deltaY > 0 ? 1.25 : 0.8, span = Math.min(dur, Math.max(2000, (t1 - t0) * f));
      const share = (m - t0) / (t1 - t0);
      t0 = Math.min(Math.max(0, m - share * span), dur - span); t1 = t0 + span;
      draw();
    }, { passive: false });
  });
  document.getElementById("sets").append(root);
  window.addEventListener("resize", draw);
  draw();
}
DATA.sets.forEach(build);
</script>
</body>
</html>
"""


_TOKEN = re.compile(r"@@([\w.]+)@@")
_KEYCAP = re.compile(r"&lt;k&gt;(.*?)&lt;/k&gt;")


def _markup(text: str) -> str:
    """A pack text as HTML: escaped, with [[Key]] drawn as a key cap."""
    return _KEYCAP.sub(r'<span class="key">\1</span>', html.escape(text, quote=True))


def _localize(page: str) -> str:
    """Fill the page's @@preview.*@@ texts (in the chosen language) and its script's preview.js.* texts."""
    texts = i18n.prefixed("preview.js.")
    payload = json.dumps(texts, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    return (_TOKEN.sub(lambda m: _markup(i18n.t(m.group(1))), page)
            .replace("__I18N__", payload).replace("__LANG__", html.escape(i18n.current())))


def axis_label(axis: str) -> str:
    """The name of an axis in the chosen language: "前後推移 (Surge)"."""
    return i18n.t(f"axis.{axis}")


def _actions(fs: Funscript | None) -> list[dict]:
    return [{"at": a.at, "pos": a.pos} for a in fs.normalized().actions] if fs else []


def player_html(
    video_url: str,
    script: Funscript,
    reference: Funscript | None = None,
    scene_starts_ms: list[float] | None = None,
    fps: float = 30.0,
    scene_list: list[tuple[float, int, bool]] | None = None,
    start_ms: float = 0.0,
    play: bool = False,
    checks: list[int] | None = None,
    unsure: list[int] | None = None,
    regions: dict[int, dict] | None = None,
    axes: dict[str, Funscript] | None = None,
) -> str:
    """`scene_list`: (start ms, number, flipped) per scene, shown under the player and drawn as cuts when
    `scene_starts_ms` is not given. `checks`: numbers of the scenes to check by hand (possibly upside down), `unsure`: those whose direction has no evidence, shaded
    while not flipped, with a button to jump from one to the next. `start_ms` / `play`: where to resume when the
    player is rebuilt. `regions`: per scene number, the region its motion was analysed in, drawn over the video
    (see scene_regions). `axes`: the other axes of a multi-axis script by id (L1, R1, ...), drawn as strips under the
    timeline (the editing tools work on `script`, the main axis, only)."""
    if scene_list and scene_starts_ms is None:
        scene_starts_ms = [s for s, _, _ in scene_list]
    data = {
        "actions": _actions(script),
        "reference": _actions(reference),
        "scenes": [round(s) for s in (scene_starts_ms or []) if s > 0],
        "scene_list": [{"at": round(s), "i": i, "flipped": bool(f), "check": i in set(checks or []), "unsure": i in set(unsure or []),
                        "region": (regions or {}).get(i)} for s, i, f in sorted(scene_list or [])],
        "axes": [{"id": a, "label": axis_label(a), "actions": _actions(fs)} for a, fs in (axes or {}).items()],
        "main_label": f"{MAIN_AXIS} {axis_label(MAIN_AXIS)}",
        "fps": fps or 30.0,
        "start_ms": max(0.0, float(start_ms)),
        "play": bool(play),
    }
    payload = json.dumps(data, separators=(",", ":")).replace("</", "<\\/")  # keep </script> out of the JSON
    return _localize(
        _PLAYER.replace("__VIDEO__", html.escape(video_url, quote=True))
        .replace("__COUNT__", str(len(data["actions"])))
        .replace("__AXH__", str(AXIS_STRIP_PX * len(data["axes"])))
        .replace("__AXES__", "".join('<canvas class="axis" title="@@preview.timeline_title@@"></canvas>' for _ in data["axes"]))
        .replace("__DATA__", payload)
    )


def axes_viewer_html(sets) -> str:
    """A page showing the axes of multi-axis scripts (multiaxis.ScriptSet) with no video: per script one strip per
    axis over its whole length, with a cursor that reads the position of every axis at the mouse, wheel zoom, drag to
    scroll and a double click to show everything again."""
    data = {"sets": []}
    for s in sets:
        main, axes = s.funscripts()
        strips = [(MAIN_AXIS, main), *axes.items()]
        data["sets"].append({
            "name": s.name,
            "duration": max((fs.actions[-1].at for _, fs in strips if fs.actions), default=0),
            "axes": [{"id": a, "label": axis_label(a), "actions": _actions(fs)} for a, fs in strips],
        })
    payload = json.dumps(data, separators=(",", ":"), ensure_ascii=False).replace("</", "<\\/")
    return _localize(_VIEWER.replace("__DATA__", payload))


def viewer_height(sets) -> int:
    """The iframe height that shows every strip of `sets` (axes_viewer_html)."""
    return 16 + sum(30 + 62 * (1 + len(s.axes)) + 14 for s in sets)


def scene_regions(plans) -> dict[int, dict]:
    """Per scene number (ScenePlan.scene.index), the region its optical flow was measured in, for player_html:
    `box` (x1, y1, x2, y2 in 0..1, None = the whole frame); in the hybrid focus also `alt` (the general region) and
    `dec` ([key frame ms, 1 = the genital region]): each frame uses the region of the nearest key frame. Scenes
    without flow (skipped, resting, skeleton) have none."""
    out = {}
    for p in plans:
        if p.mode != "flow" or p.skip or p.rest or p.signal is None:
            continue
        box = [round(float(v), 4) for v in p.roi] if p.roi is not None else None
        if p.decisions:
            alt = [round(float(v), 4) for v in p.alt_roi] if p.alt_roi is not None else None
            out[p.scene.index] = {"hybrid": True, "box": box, "alt": alt,
                                  "dec": [[round(t), int(bool(u))] for t, u in p.decisions]}
        else:
            out[p.scene.index] = {"hybrid": False, "box": box}
    return out


def iframe(document: str, height: int = 880) -> str:
    """Embed a full HTML document so that its script runs (gr.HTML does not execute inline scripts)."""
    return (
        f'<iframe srcdoc="{html.escape(document, quote=True)}" '
        f'style="width:100%;height:{height}px;border:0;" allow="fullscreen"></iframe>'
    )
