const $ = (id) => document.getElementById(id);
const STEP_PX = 12;
const MULTS = [1, 2, 3, 4, 6, 8, 12, 16, 24, 32, 48, 64, 96];
const PC = [["","C"],["^","C"],["","D"],["^","D"],["","E"],["","F"],["^","F"],
            ["","G"],["^","G"],["","A"],["^","A"],["","B"]];
let unit = null, blocks = [], origBlocks = null, vocalId = null, flat = [], selected = null;
let layout = null, dragSrc = null;

function gcd(a, b) { while (b) { [a, b] = [b, a % b]; } return a; }
function frac(s) { const p = s.includes("/") ? s.split("/").map(Number) : [Number(s), 1]; return { n: p[0], d: p[1] }; }
function fval(f) { return f.n / f.d; }
function fdiv(a, b) { return { n: a.n * b.d, d: a.d * b.n }; }
function fstr(f) { const g = gcd(f.n, f.d); return f.d / g === 1 ? String(f.n / g) : `${f.n / g}/${f.d / g}`; }
function spell(midi) {
  const oct = Math.floor(midi / 12) - 1;
  const [acc, letter] = PC[((midi % 12) + 12) % 12];
  let lc = letter, marks = "";
  if (oct >= 4) { lc = letter.toLowerCase(); marks = "'".repeat(oct - 4); }
  else if (oct < 3) { marks = ",".repeat(3 - oct); }
  return { acc, letter: lc, oct_marks: marks, name: acc + letter + oct, pitch: midi };
}
function headerMeter() {
  const m = /(^|\n)M:\s*([0-9]+\/[0-9]+)/.exec($("score").value || "");
  return m ? m[2] : "4/4";
}
function meterSteps(mStr) {
  const p = mStr.split("/").map(Number);
  return Math.max(1, Math.round(fval(fdiv({ n: p[0], d: p[1] }, unit))));
}
function evSteps(ev, spB) {
  const mult = Math.max(1, Math.round(fval(fdiv(frac(ev.dur), unit))));
  if (ev.kind === "rest" && ev.rest_case === "Z") return mult * spB;
  return mult;
}
function streamFrom(src, vid) {
  const items = [];
  for (let bi = 0; bi < src.length; bi++) {
    const b = src[bi];
    if (b.voice !== vid) continue;
    items.push({ type: "section", bi, section: b.section });
    for (let ei = 0; ei < b.events.length; ei++) items.push({ type: "ev", bi, ei, ev: b.events[ei] });
  }
  return items;
}
function vocalStream() { return streamFrom(blocks, vocalId); }
function buildContentFrom(src, vid) {
  let cursor = 0, spB = meterSteps(headerMeter());
  const evBlocks = [], sections = [];
  let curSection = null;
  for (const it of streamFrom(src, vid)) {
    if (it.type === "section") {
      const b = src[it.bi];
      for (const ln of (b.inline || [])) {
        const mm = /^M:\s*([0-9]+\/[0-9]+)/.exec(ln);
        if (mm) spB = meterSteps(mm[1]);
      }
      if (it.section && it.section !== curSection) {
        curSection = it.section;
        sections.push({ name: curSection, start: cursor, end: null });
      }
      continue;
    }
    const ev = it.ev;
    if (ev.kind === "bar") continue;
    if (ev.kind !== "note" && ev.kind !== "rest") continue;
    const dur = evSteps(ev, spB);
    evBlocks.push({ bi: it.bi, ei: it.ei, ev, start: cursor, dur, kind: ev.kind });
    cursor += dur;
  }
  for (let i = 0; i < sections.length; i++) sections[i].end = i + 1 < sections.length ? sections[i + 1].start : cursor;
  if (!sections.length) sections.push({ name: "(без секции)", start: 0, end: cursor });
  return { evBlocks, sections, total: cursor };
}
function buildGridFrom(src, vid, maxTotal) {
  let gridSpB = meterSteps(headerMeter()), pending = null, slotStart = 0;
  const barPositions = [];
  for (const it of streamFrom(src, vid)) {
    if (it.type === "section") {
      const b = src[it.bi];
      for (const ln of (b.inline || [])) {
        const mm = /^M:\s*([0-9]+\/[0-9]+)/.exec(ln);
        if (mm) pending = meterSteps(mm[1]);
      }
      continue;
    }
    if (it.ev.kind === "bar") {
      if (pending) { gridSpB = pending; pending = null; }
      slotStart += gridSpB;
      barPositions.push(slotStart);
    }
  }
  while (slotStart < maxTotal) { slotStart += gridSpB; barPositions.push(slotStart); }
  return { barPositions, total: slotStart };
}
function newNote(durF) {
  return Object.assign({ kind: "note", dur: fstr(durF), tie: false, rest_case: "z", section: null, syllable: null }, spell(64));
}
function newRest(durF) {
  return { kind: "rest", rest_case: "z", dur: fstr(durF), tie: false, section: null, syllable: null, name: null, pitch: null, letter: null, oct_marks: "", acc: null };
}
async function build() {
  const res = await fetch("/api/align", { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ score: $("score").value, lyrics: $("lyrics").value }) });
  const data = await res.json();
  unit = frac(data.unit); blocks = data.blocks; vocalId = data.vocal_id;
  origBlocks = JSON.parse(JSON.stringify(blocks));
  flat = [];
  let prevTie = false;
  for (const it of vocalStream()) {
    if (it.type !== "ev") continue;
    const ev = it.ev;
    if (ev.kind !== "note") { prevTie = false; continue; }
    if (!prevTie && ev.syllable != null) flat.push(ev.syllable);
    prevTie = ev.tie;
  }
  flat = flat.concat(data.leftover || []);
  selected = null;
  rewalk(); render();
}
function rewalk() {
  let idx = 0, prevTie = false, prevSyl = null, without = 0;
  for (const it of vocalStream()) {
    if (it.type !== "ev") continue;
    const ev = it.ev;
    if (ev.kind !== "note") { prevTie = false; continue; }
    if (prevTie) ev.syllable = prevSyl;
    else {
      ev.syllable = idx < flat.length ? flat[idx] : null;
      if (ev.syllable != null) idx++; else without++;
    }
    prevSyl = ev.syllable; prevTie = ev.tie;
  }
  const rest = flat.length - idx;
  $("diag").textContent = "Слогов без нот: " + rest +
    (rest ? " (" + flat.slice(idx).join(" ") + ")" : "") + "   Нот без слога: " + without;
}
function addBlock(tl, bl, isIns, editable) {
  const d = document.createElement("div");
  const isSel = editable && selected && selected.bi === bl.bi && selected.ei === bl.ei;
  if (bl.kind === "rest") {
    d.className = "tl-block rest" + (isIns ? " ins" : "") + (editable ? "" : " ro") + (isSel ? " sel" : "");
    d.textContent = "S";
  } else {
    d.className = "tl-block note" + (isIns ? " ins" : "") + (editable ? "" : " ro") + (isSel ? " sel" : "");
    d.innerHTML = "<span>" + (bl.ev.name || "") + (bl.ev.tie ? " ~" : "") + "</span>" +
      (isIns ? "" : "<span class='syl'>" + (bl.ev.syllable ?? "") + "</span>");
  }
  d.style.left = (bl.start * STEP_PX) + "px";
  d.style.width = Math.max(6, bl.dur * STEP_PX - 2) + "px";
  d.title = (isIns ? "Ins: " : "Vocal: ") + (bl.ev.name || "тишина") + " / " + bl.ev.dur;
  if (editable) {
    d.draggable = true;
    d.ondragstart = (e) => { dragSrc = { bi: bl.bi, ei: bl.ei }; e.dataTransfer.setData("text/plain", ""); };
    d.onclick = () => { selected = { bi: bl.bi, ei: bl.ei }; render(); };
    const h = document.createElement("div");
    h.className = "tl-handle";
    h.onpointerdown = (e) => startResize(e, bl);
    d.appendChild(h);
  }
  tl.appendChild(d);
}
function renderTimeline(elId, src, editable) {
  if (!src) return;
  const insId = (src.find((b) => b.voice !== vocalId) || {}).voice || null;
  const cv = buildContentFrom(src, vocalId);
  const ci = insId ? buildContentFrom(src, insId) : null;
  const grid = buildGridFrom(src, vocalId, Math.max(cv.total, ci ? ci.total : 0));
  const tl = $(elId);
  tl.innerHTML = "";
  tl.style.width = (grid.total * STEP_PX) + "px";
  const boundaries = [0].concat(grid.barPositions);
  const ruler = document.createElement("div");
  ruler.className = "tl-ruler";
  boundaries.forEach((st, i) => {
    const t = document.createElement("div");
    t.className = "tl-tick";
    t.style.left = (st * STEP_PX) + "px";
    t.textContent = i + 1;
    ruler.appendChild(t);
  });
  tl.appendChild(ruler);
  cv.sections.forEach((s, i) => {
    const b = document.createElement("div");
    b.className = "tl-section" + (i % 2 ? " alt" : "");
    b.style.left = (s.start * STEP_PX) + "px";
    b.style.width = ((s.end - s.start) * STEP_PX) + "px";
    b.textContent = s.name;
    tl.appendChild(b);
  });
  grid.barPositions.forEach((st) => {
    const l = document.createElement("div");
    l.className = "tl-barline";
    l.style.left = (st * STEP_PX) + "px";
    tl.appendChild(l);
  });
  const lv = document.createElement("div");
  lv.className = "tl-lanelabel"; lv.style.top = "38px"; lv.textContent = "Vocal";
  tl.appendChild(lv);
  if (ci) {
    const li = document.createElement("div");
    li.className = "tl-lanelabel"; li.style.top = "102px"; li.textContent = insId;
    tl.appendChild(li);
  }
  cv.evBlocks.forEach((bl) => addBlock(tl, bl, false, editable));
  if (ci) ci.evBlocks.forEach((bl) => addBlock(tl, bl, true, editable));
  if (editable) {
    layout = { evBlocks: cv.evBlocks.concat(ci ? ci.evBlocks : []), barPositions: grid.barPositions, total: grid.total };
    tl.ondragover = (e) => e.preventDefault();
    tl.ondrop = (e) => { e.preventDefault(); doReorder(e); };
  } else {
    tl.ondragover = null;
    tl.ondrop = null;
  }
}
function render() {
  renderTimeline("timeline-orig", origBlocks, false);
  renderTimeline("timeline", blocks, true);
}
function doReorder(e) {
  if (!dragSrc) return;
  const rect = $("timeline").getBoundingClientRect();
  const step = Math.round((e.clientX - rect.left) / STEP_PX);
  const src = layout.evBlocks.find(b => b.bi === dragSrc.bi && b.ei === dragSrc.ei);
  dragSrc = null;
  if (!src) return;
  const targets = layout.evBlocks.filter(b => b.bi === src.bi && b.ei !== src.ei);
  const target = targets.find(b => b.start >= step);
  const arr = blocks[src.bi].events;
  const moved = arr.splice(src.ei, 1)[0];
  let insertIdx = target ? arr.indexOf(target.ev) : -1;
  if (insertIdx < 0) insertIdx = arr.length;
  arr.splice(insertIdx, 0, moved);
  selected = { bi: src.bi, ei: insertIdx };
  rewalk(); render();
}
function startResize(e, bl) {
  e.preventDefault(); e.stopPropagation();
  const evObj = blocks[bl.bi].events[bl.ei];
  if (evObj && evObj.kind === "rest" && evObj.rest_case === "Z") {
    const mult = Math.max(1, Math.round(fval(fdiv(frac(evObj.dur), unit))));
    evObj.rest_case = "z";
    evObj.dur = fstr({ n: unit.n * mult * meterSteps(headerMeter()), d: unit.d });
  }
  const st = { bi: bl.bi, ei: bl.ei, startX: e.clientX, origDur: bl.dur };
  const move = (ev) => {
    const nd = Math.max(1, st.origDur + Math.round((ev.clientX - st.startX) / STEP_PX));
    const o = blocks[st.bi].events[st.ei];
    if (o) o.dur = fstr({ n: unit.n * nd, d: unit.d });
    render();
  };
  const up = () => {
    window.removeEventListener("pointermove", move);
    window.removeEventListener("pointerup", up);
    rewalk(); render();
  };
  window.addEventListener("pointermove", move);
  window.addEventListener("pointerup", up);
}
function act(a) {
  if (!selected) return;
  const arr = blocks[selected.bi] ? blocks[selected.bi].events : null;
  const ev = arr ? arr[selected.ei] : null;
  if (!ev) return;
  if (a === "semup" || a === "semdn") {
    if (ev.kind !== "note") return;
    Object.assign(ev, spell((ev.pitch ?? 60) + (a === "semup" ? 1 : -1)));
  } else if (a === "durup" || a === "durdn") {
    if (ev.kind === "rest" && ev.rest_case === "Z") {
      const mult = Math.max(1, Math.round(fval(fdiv(frac(ev.dur), unit))));
      ev.rest_case = "z";
      ev.dur = fstr({ n: unit.n * mult * meterSteps(headerMeter()), d: unit.d });
    }
    const mult = fval(fdiv(frac(ev.dur), unit));
    let j = MULTS.findIndex(m => m === mult);
    if (j < 0) j = 3;
    j = Math.max(0, Math.min(MULTS.length - 1, j + (a === "durup" ? 1 : -1)));
    ev.dur = fstr({ n: unit.n * MULTS[j], d: unit.d });
  } else if (a === "tie") {
    if (ev.kind === "note") ev.tie = !ev.tie;
  } else if (a === "del") {
    arr.splice(selected.ei, 1); selected = null;
  } else if (a === "addnote") {
    arr.splice(selected.ei + 1, 0, newNote({ n: unit.n * 4, d: unit.d }));
    selected = { bi: selected.bi, ei: selected.ei + 1 };
  } else if (a === "addrest") {
    arr.splice(selected.ei + 1, 0, newRest({ n: unit.n * 4, d: unit.d }));
    selected = { bi: selected.bi, ei: selected.ei + 1 };
  }
  rewalk(); render();
}
function rebarredBlocks() {
  const copy = blocks.map(b => ({ ...b, inline: [...(b.inline || [])], events: b.events.map(e => ({ ...e })) }));
  let spB = meterSteps(headerMeter()), pending = null, barCursor = 0;
  for (const b of copy) {
    if (b.voice !== vocalId) continue;
    for (const ln of b.inline) {
      const mm = /^M:\s*([0-9]+\/[0-9]+)/.exec(ln);
      if (mm) pending = meterSteps(mm[1]);
    }
    const out = [];
    for (const ev of b.events) {
      if (ev.kind === "bar") continue;
      if (ev.kind === "rest" && ev.rest_case === "Z") {
        const mult = Math.max(1, Math.round(fval(fdiv(frac(ev.dur), unit))));
        for (let k = 0; k < mult; k++) {
          out.push({ ...ev, rest_case: "z", dur: fstr({ n: unit.n * spB, d: unit.d }) });
          out.push({ kind: "bar" });
          barCursor = 0;
          if (pending) { spB = pending; pending = null; }
        }
        continue;
      }
      out.push(ev);
      if (ev.kind === "note" || ev.kind === "rest") {
        barCursor += Math.max(1, Math.round(fval(fdiv(frac(ev.dur), unit))));
        while (barCursor >= spB) { out.push({ kind: "bar" }); barCursor -= spB; if (pending) { spB = pending; pending = null; } }
      }
    }
    if (barCursor > 0) { out.push({ kind: "bar" }); barCursor = 0; }
    b.events = out;
  }
  return copy;
}
async function exportAbc() {
  const res = await fetch("/api/export", { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ score: $("score").value, blocks: rebarredBlocks() }) });
  const data = await res.json();
  $("out").value = data.abc;
}
document.querySelectorAll("#toolbar button").forEach(b => { b.onclick = () => act(b.dataset.act); });
$("build").onclick = build;
$("export").onclick = exportAbc;
$("copy").onclick = () => navigator.clipboard.writeText($("out").value);
$("save").onclick = () => {
  const blob = new Blob([$("out").value], { type: "text/plain;charset=utf-8" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = "yue-score.abc";
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(a.href);
};
$("impabc").onclick = () => $("fileabc").click();
$("implyr").onclick = () => $("filelyr").click();
$("fileabc").onchange = (e) => {
  const f = e.target.files[0]; if (!f) return;
  const r = new FileReader(); r.onload = () => { $("score").value = r.result; }; r.readAsText(f);
};
$("filelyr").onchange = (e) => {
  const f = e.target.files[0]; if (!f) return;
  const r = new FileReader(); r.onload = () => { $("lyrics").value = r.result; }; r.readAsText(f);
};
window.addEventListener("error", (e) => {
  const d = document.getElementById("diag");
  if (d) d.textContent = "ОШИБКА: " + e.message + " (строка " + e.lineno + ")";
});
// --- Аудио-предпросмотр (Web Audio API) ---
let audioCtx = null, playNodes = [], playRAF = null, playStart = 0, playSecPerStep = 0, playTotalSteps = 0;
function tempoSecPerStep() {
  const m = /Q:\s*([0-9]+)\/([0-9]+)\s*=\s*([0-9]+)/.exec($("score").value || "");
  if (m) {
    const beat = frac(m[1] + "/" + m[2]);
    return (60 / Number(m[3])) / fval(fdiv(beat, unit));
  }
  return (60 / 105) / fval(fdiv(frac("1/4"), unit));
}
function midiFreq(p) { return 440 * Math.pow(2, (p - 69) / 12); }
function collectVoiceSchedule(vid) {
  const items = [];
  let cursor = 0, spB = meterSteps(headerMeter());
  for (const it of streamFrom(blocks, vid)) {
    if (it.type === "section") {
      const b = blocks[it.bi];
      for (const ln of (b.inline || [])) {
        const mm = /^M:\s*([0-9]+\/[0-9]+)/.exec(ln);
        if (mm) spB = meterSteps(mm[1]);
      }
      continue;
    }
    const ev = it.ev;
    if (ev.kind === "bar") continue;
    if (ev.kind !== "note" && ev.kind !== "rest") continue;
    const dur = evSteps(ev, spB);
    if (ev.kind === "note") items.push({ start: cursor, dur, pitch: ev.pitch ?? 60, tie: !!ev.tie });
    cursor += dur;
  }
  const merged = [];
  for (const n of items) {
    const last = merged[merged.length - 1];
    if (last && last.tie && last.pitch === n.pitch) { last.dur += n.dur; last.tie = n.tie; }
    else merged.push({ start: n.start, dur: n.dur, pitch: n.pitch, tie: n.tie });
  }
  return { notes: merged, total: cursor };
}
function playSchedule(mode) {
  stopPlay();
  if (!blocks.length || !unit) return;
  audioCtx = audioCtx || new (window.AudioContext || window.webkitAudioContext)();
  if (audioCtx.state === "suspended") audioCtx.resume();
  const secPerStep = tempoSecPerStep();
  const t0 = audioCtx.currentTime + 0.1;
  playSecPerStep = secPerStep;
  const insId = (blocks.find((b) => b.voice !== vocalId) || {}).voice || null;
  const tracks = mode === "both" && insId ? [vocalId, insId] : [vocalId];
  let total = 0;
  tracks.forEach((vid) => {
    const sch = collectVoiceSchedule(vid);
    total = Math.max(total, sch.total);
    sch.notes.forEach((n) => {
      const osc = audioCtx.createOscillator();
      const g = audioCtx.createGain();
      osc.type = vid === vocalId ? "triangle" : "sawtooth";
      osc.frequency.value = midiFreq(n.pitch);
      const st = t0 + n.start * secPerStep;
      const du = Math.max(0.06, n.dur * secPerStep - 0.02);
      const vol = vid === vocalId ? 0.22 : 0.09;
      g.gain.setValueAtTime(0.0001, st);
      g.gain.linearRampToValueAtTime(vol, st + 0.015);
      g.gain.setValueAtTime(vol, Math.max(st + 0.015, st + du - 0.04));
      g.gain.linearRampToValueAtTime(0.0001, st + du);
      osc.connect(g); g.connect(audioCtx.destination);
      osc.start(st); osc.stop(st + du + 0.03);
      playNodes.push(osc);
    });
  });
  playTotalSteps = total;
  playStart = t0;
  const ph1 = document.createElement("div");
  ph1.className = "tl-playhead"; ph1.id = "ph-edit";
  $("timeline").appendChild(ph1);
  const ph2 = document.createElement("div");
  ph2.className = "tl-playhead"; ph2.id = "ph-orig";
  $("timeline-orig").appendChild(ph2);
  const tick = () => {
    const steps = (audioCtx.currentTime - playStart) / playSecPerStep;
    if (steps >= playTotalSteps) { stopPlay(); return; }
    const x = Math.max(0, steps * STEP_PX);
    ph1.style.left = x + "px";
    ph2.style.left = x + "px";
    const wrap = $("timeline").parentElement;
    if (x > wrap.scrollLeft + wrap.clientWidth - 80) wrap.scrollLeft = Math.max(0, x - wrap.clientWidth / 2);
    playRAF = requestAnimationFrame(tick);
  };
  playRAF = requestAnimationFrame(tick);
}
function stopPlay() {
  if (playRAF) { cancelAnimationFrame(playRAF); playRAF = null; }
  playNodes.forEach((n) => { try { n.stop(); } catch (e) {} });
  playNodes = [];
  ["ph-edit", "ph-orig"].forEach((id) => { const e = document.getElementById(id); if (e) e.remove(); });
}
$("playVocal").onclick = () => playSchedule("vocal");
$("playBoth").onclick = () => playSchedule("both");
$("stopPlay").onclick = stopPlay;
// --- Сессии редактирования (JSON) ---
function collectFlat() {
  const f = [];
  let prevTie = false;
  for (const it of vocalStream()) {
    if (it.type !== "ev") continue;
    const ev = it.ev;
    if (ev.kind !== "note") { prevTie = false; continue; }
    if (!prevTie && ev.syllable != null) f.push(ev.syllable);
    prevTie = ev.tie;
  }
  return f;
}
function saveSession() {
  const sess = {
    app: "yue-score-align",
    version: 1,
    savedAt: new Date().toISOString(),
    scoreText: $("score").value,
    lyricsText: $("lyrics").value,
    unit: fstr(unit),
    vocalId: vocalId,
    flat: flat,
    blocks: blocks,
  };
  const blob = new Blob([JSON.stringify(sess, null, 2)], { type: "application/json" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = "yue-session.json";
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(a.href);
}
function loadSessionFile(file) {
  const r = new FileReader();
  r.onload = () => {
    try {
      const sess = JSON.parse(r.result);
      if (sess.app !== "yue-score-align" || !Array.isArray(sess.blocks)) {
        throw new Error("файл не является сессией yue-score-align");
      }
      $("score").value = sess.scoreText || "";
      $("lyrics").value = sess.lyricsText || "";
      unit = frac(sess.unit || "1/16");
      vocalId = sess.vocalId || "Vocal";
      blocks = sess.blocks;
      origBlocks = JSON.parse(JSON.stringify(blocks));
      flat = Array.isArray(sess.flat) ? sess.flat : collectFlat();
      selected = null;
      rewalk(); render();
    } catch (err) {
      $("diag").textContent = "ОШИБКА загрузки сессии: " + err.message;
    }
  };
  r.readAsText(file);
}
$("saveSession").onclick = saveSession;
$("loadSession").onclick = () => $("fileSession").click();
$("fileSession").onchange = (e) => {
  const f = e.target.files[0];
  if (!f) return;
  loadSessionFile(f);
  e.target.value = "";
};
