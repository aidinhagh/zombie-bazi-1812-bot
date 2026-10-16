"""Build the map web app from the campaign map file (zombiebot/webapp/campaign_map_source.html).

Keeps every bit of the original graphics (3D relief, roads, sea lanes, ships, city models) and adds the game:
Persian city names, the player's pawn, numbered pins on the squares they can reach, closed routes in red,
cannons and ships on the board, and tap-to-move with a walking animation.

    python tools/build_map_webapp.py
"""
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "zombiebot", "webapp", "campaign_map_source.html")
OUT = os.path.join(ROOT, "zombiebot", "webapp", "map.html")

HEAD = """<script src="https://telegram.org/js/telegram-web-app.js"></script>
<style>
@font-face{font-family:Vazir;src:url(/font.ttf) format("truetype");font-weight:400 900}
.brand,#ledgerToggle,#panel,#hint,#tip{display:none!important}
.lbl{font-family:Vazir,Tahoma,sans-serif!important;letter-spacing:0!important}
.lbl .occ{display:none!important}
#loading h2,#loading p{font-family:Vazir,Tahoma,sans-serif!important;direction:rtl}
#gTop{position:absolute;inset:0 0 auto 0;z-index:8;direction:rtl;font-family:Vazir,Tahoma,sans-serif;padding:calc(10px + env(safe-area-inset-top,0px)) 12px 8px;
  background:linear-gradient(180deg,var(--imperial-2),var(--imperial));border-bottom:1px solid var(--gold);
  box-shadow:0 3px 0 var(--imperial-3),0 4px 0 var(--rule),0 10px 24px rgba(0,0,0,.45)}
#gWho{display:flex;align-items:center;gap:8px;font-size:15px;color:var(--gold-soft)}
#gWho b{font-weight:800}#gWho .role{color:var(--parch-dim);font-size:13px}
#gWho .stats{margin-inline-start:auto;display:flex;gap:10px;font-size:14px;color:var(--parch)}
#gHint{margin-top:6px;display:flex;align-items:center;gap:8px;font-size:14px;color:var(--parch);line-height:1.6}
#gDie{width:30px;height:30px;flex:none;border-radius:7px;background:var(--parch);color:var(--ink);display:grid;place-items:center;font-weight:900;font-size:17px;
  box-shadow:inset 0 -3px 0 #c9bb98,0 0 0 1px var(--gold)}
#gPhase{margin-inline-start:auto;font-size:12px;color:var(--parch-dim);border:1px solid var(--rule);padding:2px 8px;border-radius:20px;white-space:nowrap}
#gSheet{position:absolute;inset:auto 0 0 0;z-index:9;direction:rtl;font-family:Vazir,Tahoma,sans-serif;transform:translateY(105%);transition:transform .25s ease;
  background:linear-gradient(180deg,var(--imperial-2),var(--imperial) 40%,var(--imperial-3));border-top:1px solid var(--gold);
  box-shadow:0 -3px 0 var(--imperial-3),0 -4px 0 var(--rule),0 -14px 30px rgba(0,0,0,.5);padding:14px 16px calc(16px + env(safe-area-inset-bottom,0px))}
#gSheet.open{transform:none}
#gSheet h2{margin:0 0 4px;font-size:19px;color:var(--gold-soft);font-weight:800}
#gSheet .meta{font-size:13px;color:var(--parch-dim);margin-bottom:8px}
#gSheet p{margin:0 0 10px;font-size:14px;line-height:1.7;color:var(--parch);white-space:pre-line}
#gSheet p.warn{color:#f1a39c}
.gRow{display:flex;gap:8px}
.gBtn{flex:1;appearance:none;border:1px solid var(--gold);background:rgba(0,0,0,.25);color:var(--parch);font:inherit;font-size:15px;padding:11px;border-radius:8px;cursor:pointer;font-family:Vazir,Tahoma,sans-serif}
.gBtn.gold{background:linear-gradient(180deg,#d9b65e,#b88f37);color:var(--ink);border-color:#f0dc9c;font-weight:800}
.gBtn:disabled{opacity:.5}
#gMsg{position:absolute;inset:0;z-index:30;display:none;place-items:center;background:rgba(16,12,8,.6);direction:rtl;font-family:Vazir,Tahoma,sans-serif}
#gMsg .card{max-width:320px;margin:20px;background:var(--imperial);border:1px solid var(--gold);border-radius:12px;padding:18px;text-align:center;color:var(--parch)}
#gMsg h3{margin:0 0 8px;color:var(--gold-soft)}#gMsg p{margin:0 0 14px;line-height:1.7;white-space:pre-line}
#gList{position:absolute;z-index:8;inset:auto 12px calc(14px + env(safe-area-inset-bottom,0px)) auto;direction:rtl;font-family:Vazir,Tahoma,sans-serif}
#gList button{display:block;margin-top:6px;border:1px solid var(--gold);background:rgba(14,36,29,.9);color:var(--gold-soft);border-radius:8px;padding:8px 12px;font:inherit;font-size:13px}
</style>
"""

BODY = """<div id="gTop"><div id="gWho"><b id="gName">…</b><span class="role" id="gRole"></span><span class="stats"><span id="gHp"></span><span id="gCoins"></span></span></div>
  <div id="gHint"><div id="gDie" hidden></div><span id="gHintText">در حال آماده کردن نقشه…</span><span id="gPhase"></span></div></div>
<div id="gList"><button id="gMe">📍 جای من</button><button id="gAll">🗺 کل نقشه</button></div>
<div id="gSheet" role="dialog" aria-live="polite"><h2 id="gSName"></h2><div class="meta" id="gSMeta"></div><p id="gSDesc"></p>
  <div class="gRow"><button class="gBtn" id="gCancel">انصراف</button><button class="gBtn gold" id="gGo">حرکت به اینجا</button></div></div>
<div id="gMsg"><div class="card"><h3 id="gMTitle"></h3><p id="gMText"></p><button class="gBtn gold" id="gMBtn">بستن</button></div></div>
"""

GAME = r"""
/* ================= Zombie Bazi game layer ================= */
const TG = window.Telegram && Telegram.WebApp; if (TG) { try { TG.ready(); TG.expand(); } catch (e) {} }
const INIT = (TG && TG.initData) || new URLSearchParams(location.search).get("init") || "";
const FA = n => String(n).replace(/\d/g, d => "۰۱۲۳۴۵۶۷۸۹"[d]);
const G = {S: null, markers: [], token: null, chosen: null, busy: false};
async function gApi(path, opts = {}) {
  const r = await fetch(path, {...opts, headers: {"Content-Type": "application/json", "X-Init-Data": INIT, ...(opts.headers || {})}});
  if (!r.ok) { let t = await r.text(); try { t = JSON.parse(t).error || t; } catch (e) {} throw new Error(t); }
  return r.json();
}
function sqPos(id) {
  if (cityObj.has(id)) return cityObj.get(id).pos.clone();
  for (const r of routes.values()) { const n = r.nodes.find(n => n.id === id); if (n) return n.g.position.clone(); }
  const s = G.S && G.S.squares.find(s => s.id === id);
  return s ? new THREE.Vector3(toX(s.lon), Math.max(hAt(s.lon, s.lat), 0), toZ(s.lat)) : null;
}
function pinTexture(n, gold) {
  const c = document.createElement("canvas"); c.width = c.height = 128; const x = c.getContext("2d");
  x.beginPath(); x.arc(64, 58, 50, 0, 7); x.fillStyle = gold ? "#d9b65e" : "#a3322a"; x.fill();
  x.lineWidth = 8; x.strokeStyle = gold ? "#24180e" : "#fff"; x.stroke();
  x.beginPath(); x.moveTo(44, 100); x.lineTo(84, 100); x.lineTo(64, 126); x.closePath(); x.fillStyle = gold ? "#d9b65e" : "#a3322a"; x.fill();
  x.fillStyle = gold ? "#24180e" : "#fff"; x.font = "900 62px Vazir, Tahoma, sans-serif"; x.textAlign = "center"; x.textBaseline = "middle";
  x.fillText(FA(n), 64, 62);
  const t = new THREE.CanvasTexture(c); t.encoding = THREE.sRGBEncoding; return t;
}
function makePin(o) {
  const mat = new THREE.SpriteMaterial({map: pinTexture(o.n, false), depthTest: false, transparent: true});
  const s = new THREE.Sprite(mat); s.center.set(.5, 0); s.renderOrder = 10;
  const p = sqPos(o.sq); const city = cityObj.has(o.sq);
  s.position.copy(p).add(new THREE.Vector3(city ? .42 : 0, .08, city ? .22 : 0)); s.userData = {opt: o, base: .62};
  s.scale.setScalar(.62); scene.add(s); G.markers.push(s); return s;
}
function makePawn(p) {
  const g = new THREE.Group();
  const green = new THREE.MeshStandardMaterial({color: "#1f7a45", roughness: .45, metalness: .25, emissive: "#0b3a1f", emissiveIntensity: .5});
  const gold = new THREE.MeshStandardMaterial({color: "#c9a24a", roughness: .3, metalness: .7});
  const base = new THREE.Mesh(new THREE.CylinderGeometry(.13, .16, .06, 24).translate(0, .03, 0), gold);
  const body = new THREE.Mesh(new THREE.CylinderGeometry(.06, .11, .24, 20).translate(0, .18, 0), green);
  const head = new THREE.Mesh(new THREE.SphereGeometry(.08, 20, 14).translate(0, .34, 0), green);
  base.castShadow = body.castShadow = head.castShadow = true;
  const ring = new THREE.Mesh(new THREE.RingGeometry(.22, .28, 40).rotateX(-Math.PI / 2), new THREE.MeshBasicMaterial({color: "#2fbf6a", transparent: true, opacity: .9, depthWrite: false}));
  ring.position.y = .02; g.add(base, body, head, ring); g.userData.ring = ring;
  g.position.copy(p); scene.add(g); return g;
}
function markClosedRoutes(S) {
  for (const r of S.routes) {
    if (r.status === "ok") continue; const rr = routes.get(r.id); if (!rr) continue;
    const mat = new THREE.MeshBasicMaterial({color: "#b3261e", transparent: true, opacity: .8, depthWrite: false});
    scene.add(ribbon(rr.P, .13, .03, mat, 1, r.kind === "sea"));
    const m = rr.P[Math.floor(rr.P.length / 2)]; const y = Math.max(hXZ(m[0], m[1]), 0) + .05;
    const xm = new THREE.MeshBasicMaterial({color: "#b3261e"});
    for (const a of [Math.PI / 4, -Math.PI / 4]) { const b = new THREE.Mesh(new THREE.BoxGeometry(.42, .03, .07), xm); b.position.set(m[0], y, m[1]); b.rotation.y = a; scene.add(b); }
  }
}
function textSprite(lines, color) {
  const c = document.createElement("canvas"); const x = c.getContext("2d"); const fs = 34;
  x.font = `800 ${fs}px Vazir, Tahoma, sans-serif`;
  const w = Math.max(...lines.map(l => x.measureText(l).width)) + 40, h = lines.length * (fs + 12) + 22;
  c.width = Math.ceil(w); c.height = Math.ceil(h); x.font = `800 ${fs}px Vazir, Tahoma, sans-serif`;
  x.fillStyle = "rgba(246,238,214,.95)"; x.strokeStyle = color || "#2c4f86"; x.lineWidth = 5;
  x.beginPath(); x.roundRect(3, 3, c.width - 6, c.height - 6, 14); x.fill(); x.stroke();
  x.textAlign = "center"; x.textBaseline = "middle"; x.direction = "rtl";
  lines.forEach((l, i) => { x.fillStyle = i === 0 ? (color || "#2c4f86") : "#24180e"; x.fillText(l, c.width / 2, 22 + i * (fs + 12) + fs / 2); });
  const t = new THREE.CanvasTexture(c); t.encoding = THREE.sRGBEncoding;
  const s = new THREE.Sprite(new THREE.SpriteMaterial({map: t, depthTest: false, transparent: true})); s.renderOrder = 9;
  s.center.set(.5, 0); s.scale.set(.0042 * c.width, .0042 * c.height, 1); return s;
}
function balloonModel() {
  const g = new THREE.Group();
  const env = new THREE.Mesh(new THREE.SphereGeometry(.2, 20, 16), new THREE.MeshStandardMaterial({color: "#c9a24a", roughness: .5}));
  env.scale.set(1, 1.2, 1); env.position.y = .95;
  const stripe = new THREE.Mesh(new THREE.SphereGeometry(.202, 20, 16, 0, Math.PI * 2, Math.PI * .45, Math.PI * .1), new THREE.MeshStandardMaterial({color: "#2c4f86"}));
  stripe.scale.copy(env.scale); stripe.position.copy(env.position);
  const basket = new THREE.Mesh(new THREE.BoxGeometry(.08, .06, .08), new THREE.MeshStandardMaterial({color: "#6b4423"})); basket.position.y = .66;
  g.add(env, stripe, basket); g.traverse(m => { if (m.isMesh) m.castShadow = true; }); return g;
}
function placeReports(S) {
  for (const b of S.reports || []) {
    const p = sqPos(b.target); if (!p) continue;
    const m = balloonModel(); m.position.copy(p).add(new THREE.Vector3(-.3, 0, -.1)); scene.add(m);
    const l = textSprite(["🎈 " + b.name, b.seen.length ? b.seen.join("، ") : "هیچ‌کس"], "#2c4f86");
    l.position.copy(p).add(new THREE.Vector3(-.3, 1.25, -.1)); scene.add(l);
  }
}
function placeUnits(S) {
  for (const u of S.units) {
    const p = sqPos(u.square); if (!p) continue; let o;
    if (u.kind === "ship") { o = shipModel(); o.scale.multiplyScalar(.9); o.position.copy(p).add(new THREE.Vector3(.22, .01, .1)); }
    else { o = new THREE.Group(); const m = new THREE.MeshStandardMaterial({color: "#1d1b19", metalness: .6, roughness: .35});
      const barrel = new THREE.Mesh(new THREE.CylinderGeometry(.035, .05, .34, 14), m); barrel.rotation.z = Math.PI / 2.4; barrel.position.y = .1;
      const wood = new THREE.MeshStandardMaterial({color: "#6b4423"}); const w1 = new THREE.Mesh(new THREE.CylinderGeometry(.07, .07, .03, 16), wood); w1.rotation.x = Math.PI / 2; w1.position.set(0, .07, .07);
      const w2 = w1.clone(); w2.position.z = -.07; o.add(barrel, w1, w2); o.position.copy(p).add(new THREE.Vector3(.24, 0, .08)); }
    o.traverse(m => { if (m.isMesh) m.castShadow = true; }); scene.add(o);
    if (u.name) { const l = textSprite([u.type + " «" + u.name + "»"], "#24180e"); l.position.copy(o.position).add(new THREE.Vector3(0, .32, 0)); l.scale.multiplyScalar(.7); scene.add(l); }
  }
}
function persianLabels(S) {
  for (const s of S.squares) {
    if (s.kind !== "city" || !cityObj.has(s.id)) continue; const lb = cityObj.get(s.id).label;
    const dmg = S.damage[s.id] || 0; lb.firstChild.textContent = s.city + (dmg ? ` (${FA(dmg)}٪ ویران)` : "");
    if (dmg) lb.style.color = "#8a1c14"; cityObj.get(s.id).w = 0;
  }
  labelsDirty = true;
}
function lookAt(p, near) {
  const off = camera.position.clone().sub(controls.target); const want = near ? 8 : 22;
  off.setLength(want); controls.target.set(p.x, 0, p.z); camera.position.copy(controls.target).add(off); labelsDirty = true;
}
function focusOptions() {
  const pts = G.markers.map(m => m.position); if (G.token) pts.push(G.token.position);
  if (!pts.length) return;
  const box = new THREE.Box3().setFromPoints(pts); const c = box.getCenter(new THREE.Vector3()); const size = box.getSize(new THREE.Vector3());
  const off = camera.position.clone().sub(controls.target); off.setLength(Math.max(6, Math.max(size.x, size.z) * 1.35 + 3));
  controls.target.set(c.x, 0, c.z); camera.position.copy(controls.target).add(off); labelsDirty = true;
}
function hud(S) {
  document.getElementById("gName").textContent = S.me.name; document.getElementById("gRole").textContent = S.me.role + (S.me.char ? " · 🎭 " + S.me.char : "");
  document.getElementById("gHp").textContent = "❤️ " + FA(S.me.hp); document.getElementById("gCoins").textContent = "💰 " + FA(S.me.coins);
  document.getElementById("gPhase").textContent = S.phase;
  document.getElementById("gHintText").textContent = S.options.length ? S.hint + " روی یک شماره بزن." : S.hint;
  if (S.mode === "roll") { const d = document.getElementById("gDie"); d.hidden = false; d.textContent = FA(S.me.roll + (S.me.plus || 0)); }
}
function select(o) {
  if (G.busy) return; G.chosen = o;
  for (const m of G.markers) { const on = m.userData.opt === o; m.material.map = pinTexture(m.userData.opt.n, on); m.material.needsUpdate = true; m.userData.base = on ? .8 : .62; }
  const s = G.S.squares.find(s => s.id === o.sq);
  document.getElementById("gSName").textContent = s.name;
  document.getElementById("gSMeta").textContent = G.S.mode === "roll" ? `${FA(o.path.length)} خانه · گزینه ${FA(o.n)}` : `گزینه ${FA(o.n)}`;
  let desc = s.desc || (s.sea ? "خانه‌ای روی مسیر دریایی." : "خانه‌ای روی جاده بین دو شهر.");
  if (o.tolls.length) desc += `\n⚠️ از ${FA(o.tolls.length)} خانه با توپ/کشتی دیگران رد می‌شوی: هر کدام ۱۰ سکه عوارض.`;
  const d = document.getElementById("gSDesc"); d.textContent = desc; d.className = o.tolls.length ? "warn" : "";
  document.getElementById("gSheet").classList.add("open");
  const p = sqPos(o.sq); fly = {from: controls.target.clone(), to: new THREE.Vector3(p.x, 0, p.z), t: 0};
  if (TG) { TG.MainButton.setText("حرکت به " + (s.city || ("خانه " + FA(s.id.slice(1))))); TG.MainButton.show(); }
}
function unselect() {
  G.chosen = null; document.getElementById("gSheet").classList.remove("open");
  for (const m of G.markers) { m.material.map = pinTexture(m.userData.opt.n, false); m.material.needsUpdate = true; m.userData.base = .62; }
  if (TG) TG.MainButton.hide();
}
function walk(ids) {
  return new Promise(res => {
    const pts = ids.map(sqPos).filter(Boolean);
    if (!G.token) G.token = makePawn(pts[0]);
    if (pts.length < 2) { G.token.position.copy(pts[0]); return res(); }
    let i = 0, t0 = null; const per = 520;
    function step(ts) {
      if (!t0) t0 = ts; const k = Math.min(1, (ts - t0) / per); const a = pts[i], b = pts[i + 1];
      const e = k < .5 ? 2 * k * k : 1 - Math.pow(-2 * k + 2, 2) / 2;
      G.token.position.lerpVectors(a, b, e); G.token.position.y += Math.sin(k * Math.PI) * .35;
      const tg = G.token.position; fly = null; const d = new THREE.Vector3(tg.x, 0, tg.z).sub(controls.target).multiplyScalar(.12);
      controls.target.add(d); camera.position.add(d); labelsDirty = true;
      if (k < 1) return requestAnimationFrame(step);
      i++; t0 = null; if (i >= pts.length - 1) return res(); requestAnimationFrame(step);
    }
    requestAnimationFrame(step);
  });
}
function showMsg(title, text, label, fn) {
  document.getElementById("gMTitle").textContent = title; document.getElementById("gMText").textContent = text;
  const b = document.getElementById("gMBtn"); b.textContent = label; b.onclick = fn; document.getElementById("gMsg").style.display = "grid";
}
async function go() {
  if (!G.chosen || G.busy) return; G.busy = true; const btn = document.getElementById("gGo"); btn.disabled = true;
  if (TG) TG.MainButton.showProgress();
  try {
    const r = await gApi("/api/move", {method: "POST", body: JSON.stringify({dest: G.chosen.sq, init: INIT})});
    document.getElementById("gSheet").classList.remove("open"); if (TG) { TG.MainButton.hideProgress(); TG.MainButton.hide(); }
    for (const m of G.markers) if (m.userData.opt !== G.chosen) m.visible = false;
    await walk(G.S.me.pos ? [G.S.me.pos, ...r.path] : r.path);
    for (const m of G.markers) m.visible = false;
    if (TG && TG.HapticFeedback) TG.HapticFeedback.notificationOccurred("success");
    document.getElementById("gCoins").textContent = "💰 " + FA(r.coins);
    document.getElementById("gHintText").textContent = "📍 " + r.name;
    showMsg("📍 رسیدی!", r.name + (r.tolls.length ? "\n" + r.tolls.join("\n") : ""), "برگشت به ربات", () => { if (TG) TG.close(); else document.getElementById("gMsg").style.display = "none"; });
  } catch (e) {
    G.busy = false; btn.disabled = false; if (TG) TG.MainButton.hideProgress();
    showMsg("نشد", e.message, "باشه", () => document.getElementById("gMsg").style.display = "none");
  }
}
(function pulse() { requestAnimationFrame(pulse); const t = performance.now() / 1000;
  for (const m of G.markers) m.scale.setScalar(m.userData.base * (1 + Math.sin(t * 3 + m.userData.opt.n) * .07));
  if (G.token) { const r = G.token.userData.ring; r.scale.setScalar(1 + (t * .8 % 1) * .6); r.material.opacity = .9 * (1 - t * .8 % 1); } })();
let gDown = null;
canvas.addEventListener("pointerdown", e => gDown = {x: e.clientX, y: e.clientY}, true);
canvas.addEventListener("pointerup", e => {
  if (!gDown || Math.hypot(e.clientX - gDown.x, e.clientY - gDown.y) > 6 || !G.markers.length) return;
  setMouse(e); const hits = ray.intersectObjects(G.markers.filter(m => m.visible), false);
  let o = hits.length ? hits[0].object.userData.opt : null;
  if (!o) { const h = pick(); const id = h && (h.type === "city" || h.type === "node") ? h.id : null; o = id && G.S.options.find(x => x.sq === id); }
  if (o) { e.stopImmediatePropagation(); select(o); }
}, true);
document.getElementById("gCancel").onclick = unselect;
document.getElementById("gGo").onclick = go;
document.getElementById("gMe").onclick = () => { if (G.token) lookAt(G.token.position, true); else focusOptions(); };
document.getElementById("gAll").onclick = () => lookAt(new THREE.Vector3(-.2, 0, -1.4), false);
if (TG) TG.MainButton.onClick(go);
async function gameInit() {
  try {
    const S = await gApi("/api/state"); G.S = S;
    hud(S); persianLabels(S); markClosedRoutes(S); placeUnits(S); placeReports(S);
    if (S.me.pos) G.token = makePawn(sqPos(S.me.pos));
    S.options.forEach(makePin);
    renderer.shadowMap.needsUpdate = true;
    if (S.options.length) focusOptions(); else if (G.token) lookAt(G.token.position, true);
  } catch (e) { document.getElementById("gHintText").textContent = "⚠️ " + e.message; }
}
"""

LOADING = {
    "Engraving the plates": "در حال کشیدن نقشه",
    "Tracing the coasts of Europe…": "کشیدن سواحل اروپا…",
    "Raising the Alps and the Carpathians…": "بالا بردن کوه‌های آلپ و کارپات…",
    "Engraving rivers, coasts and frontiers…": "حک رودها، سواحل و مرزها…",
    "Surveying the roads and charting the sea lanes…": "نقشه‌برداری جاده‌ها و مسیرهای دریایی…",
    "Building the capitals…": "ساختن پایتخت‌ها…",
}


def build():
    s = open(SRC, encoding="utf8").read()
    s = s.replace("<title>Europe 1812 Campaign Map</title>", "<title>نقشه زامبی‌بازی ۱۸۱۲</title>")
    s = s.replace("</head>", HEAD + "</head>", 1) if "</head>" in s else s.replace("<style>", HEAD + "<style>", 1)
    s = s.replace('<div id="app">', '<div id="app">\n' + BODY, 1)
    for en, fa in LOADING.items():
        s = s.replace(en, fa)
    # lighter shadows on phones
    s = s.replace("sun.shadow.mapSize.set(4096,4096);", "sun.shadow.mapSize.set(innerWidth<800?2048:4096,innerWidth<800?2048:4096);")
    # start the game layer once the map is built
    s = re.sub(r"\nboot\(\);\n</script>", "\n" + GAME.replace("\\", "\\\\") + "\nboot().then(gameInit);\n</script>", s, count=1)
    assert "boot().then(gameInit)" in s, "could not hook the game layer"
    open(OUT, "w", encoding="utf8").write(s)
    print("wrote", OUT, len(s) // 1024, "KB")


if __name__ == "__main__":
    build()
