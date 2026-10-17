"""Build webapp/battle.html (the cannon-duel Mini App) from the user's Counter-Battery game (webapp/battle_source.html).

The game itself stays as it is: terrain, cities, weather, ballistics, effects. This script swaps the local
two-player / computer modes for network play against the bot: the bot decides the battlefield (city, weather,
time of day, terrain seed), whose turn it is and the wind; the shooter's phone flies the shot and reports what it
did (craters, damage, the trail), and everyone else's phone replays that.
"""
import os

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "..", "zombiebot", "webapp", "battle_source.html")
OUT = os.path.join(HERE, "..", "zombiebot", "webapp", "battle.html")

CSS = r"""
<style>
#startOv{display:none!important}
#menuTitle{display:none!important}
:root{--ottoman:#c8352e;--prussia:#9aa3b5;--russia:#4f9b5c;--austria:#e9d27a;--spain:#e0a23a;--sweden:#4f8ad6}
.report,.banner,.toast,#netBar,#netRoster,#tgtBtn,#netLoad,#endOv .card{font-family:var(--fa),var(--body)}
.pname .fa{font-size:15px}
#netBar{position:fixed;left:50%;transform:translateX(-50%);top:calc(64px + env(safe-area-inset-top,0px));z-index:3;background:var(--panel);
  border:1px solid var(--rule);padding:6px 12px;font-size:13px;direction:rtl;white-space:nowrap;max-width:calc(100vw - 24px);overflow:hidden;text-overflow:ellipsis;pointer-events:none}
#netRoster{position:fixed;right:max(12px,env(safe-area-inset-right,0px));top:calc(100px + env(safe-area-inset-top,0px));z-index:3;display:flex;flex-direction:column;gap:4px;
  direction:rtl;font-size:12px;pointer-events:none}
#netRoster div{background:var(--panel);border:1px solid var(--rule);padding:3px 8px;display:flex;gap:6px;align-items:center}
#netRoster div.dead{opacity:.45;text-decoration:line-through}
#netRoster div.turn{border-color:var(--brass-hi)}
#netRoster i{display:inline-block;width:14px;height:9px;border:1px solid rgba(0,0,0,.4)}
#tgtBtn{pointer-events:auto;background:rgba(201,161,75,.15);border:1px solid var(--rule);color:var(--linen);padding:8px 10px;cursor:pointer;direction:rtl;font-size:13px;white-space:nowrap}
#tgtBtn[hidden]{display:none}
#netLoad{position:fixed;inset:0;z-index:9;display:grid;place-items:center;background:var(--night);color:var(--linen);font-size:16px;direction:rtl;text-align:center;padding:24px}
#endOv .card{direction:rtl}
</style>
"""

BODY = r"""
<div id="netLoad">⏳ در حال آماده کردن میدان نبرد…</div>
<div id="netBar" hidden></div>
<div id="netRoster"></div>
"""

NET_JS = r"""
/* ===================== network play (Zombie Bazi bot) ===================== */
const TG = window.Telegram && window.Telegram.WebApp;
if (TG) { try { TG.ready(); TG.expand(); } catch (e) { /* ignore */ } }
const NET = { b: new URLSearchParams(location.search).get('b'), S: null, rec: null, myTurn: false, status: 'live', applied: 0, deadline: 0, sending: false, playing: false };
const FA = n => String(n).replace(/\d/g, d => '۰۱۲۳۴۵۶۷۸۹'[d]);
function netInitData() { return (TG && TG.initData) || new URLSearchParams(location.search).get('init') || ''; }
async function netApi(path, body) {
  const opt = { headers: { 'X-Init-Data': netInitData() } };
  if (body) { opt.method = 'POST'; opt.headers['Content-Type'] = 'application/json'; opt.body = JSON.stringify(body); }
  const r = await fetch(path, opt), t = await r.text();
  let j; try { j = JSON.parse(t); } catch (e) { throw new Error(t || ('HTTP ' + r.status)); }
  if (!r.ok) throw new Error(j.error || ('HTTP ' + r.status));
  return j;
}
function meGun() { return guns.find(g => g.mine && !g.destroyed) || guns.find(g => g.mine) || guns[game.turn] || guns[0]; }
function foeOf(g) {
  const t = guns[g.target];
  if (t && t !== g && !t.destroyed) return t;
  return guns.find(x => x !== g && !x.destroyed && !(g.mine && x.mine)) || guns.find(x => x !== g) || g;
}
function aimBase(g) { const o = foeOf(g); if (o !== g) g.baseYaw = Math.atan2(-(o.z - g.z), o.x - g.x); }
function placeGuns(r) {
  const n = guns.length;
  if (n === 2) { guns[0].x = -80; guns[0].z = (r() - 0.5) * 44; guns[1].x = 80; guns[1].z = (r() - 0.5) * 44; }
  else for (let i = 0; i < n; i++) { const a = Math.PI + i / n * 2 * Math.PI; guns[i].x = Math.cos(a) * 92; guns[i].z = Math.sin(a) * 46 + (r() - 0.5) * 8; }
  for (const g of guns) aimBase(g);
}
function makeGuns(S) {
  for (const g of guns) scene.remove(g.mesh.root);
  guns = S.units.map((u, i) => ({ n: i, uid: u.id, uname: u.name, mine: !!u.mine, team: TEAM_BY[u.flag] || TEAMS[0], x: 0, z: 0, baseYaw: 0,
    elev: 20, trav: 0, charge: 3.5, ammo: 'shot', shells: 4, hp: 100, mesh: null, report: '', destroyed: false, target: -1 }));
  guns.forEach(g => { g.mesh = buildGun(g.team); });
  guns.forEach(g => { const o = guns.find(x => x !== g && !(g.mine && x.mine)); g.target = o ? o.n : -1; });
  game.mode = 'net';
}
function wreck(g) {   // a destroyed gun, without the explosion (for replays)
  g.destroyed = true; g.hp = 0;
  const m = g.mesh;
  m.yawG.rotation.x = 0.32; m.yawG.rotation.y += 0.25; m.pivot.rotation.z = -0.12;
  m.mats.forEach(mt => mt.color.multiplyScalar(0.3));
  m.crew.forEach((cw, i) => { cw.rotation.x = (i % 2 ? 1 : -1) * 1.45; cw.position.y = 0.2; });
}
function applyShot(s) { for (const c of s.craters || []) crater(c[0], c[1], c[2], c[3], c[4]); }
function applyUnits(S, boom) {
  for (const u of S.units) {
    const g = guns.find(x => x.uid === u.id); if (!g) continue;
    const was = g.hp; g.hp = u.hp; g.shells = u.shells;
    if (boom && u.hp < was && !g.mine) floatText('−' + Math.round(was - u.hp), gunCenter(g).add(new V3(0, 3, 0)));
    if (!u.alive && !g.destroyed) { if (boom) destroyGun(g); else wreck(g); }
  }
}
function playTrail(s) {
  return new Promise(res => {
    const pts = s.trail || []; if (pts.length < 2) return res();
    NET.playing = true; game.state = 'replay'; ball.visible = true; fuse.visible = s.ammo === 'shell';
    const from = guns.find(g => g.uid === s.by);
    if (from) { from.mesh.recoilG.position.x = -0.9; from.mesh.flinch = 1; const mz = muzzleDir(from, s.elev || 20, s.trav || 0); muzzleSmoke(mz.muzzle, mz.dir); boom(1, mz.muzzle, 1400); }
    lineReset(liveTrail); let i = 0;
    const step = () => {
      if (i >= pts.length) {
        ball.visible = false; fuse.visible = false; NET.playing = false;
        const e = pts[pts.length - 1], p = new V3(e[0], e[1], e[2]);
        if (s.ammo === 'shell' || s.kind === 'hit') { shellBurst(p); boom(1, p, 900); } else grazeDust(p);
        game.afterPoint.copy(p); return res();
      }
      const q = pts[i]; ball.position.set(q[0], q[1], q[2]); fuse.position.copy(ball.position); linePush(liveTrail, ball.position);
      game.afterPoint.copy(ball.position); i++; setTimeout(step, 30);
    };
    step();
  });
}
function rosterUI() {
  const S = NET.S; if (!S) return;
  const el = $('netRoster'); el.innerHTML = '';
  for (const g of guns) {
    const d = document.createElement('div');
    d.className = (g.destroyed ? 'dead ' : '') + (S.turn === g.uid && NET.status === 'live' ? 'turn' : '');
    d.innerHTML = `<i style="background:${g.team.chip}"></i>${g.mine ? '⭐ ' : ''}«${esc(g.uname)}» ❤️ ${FA(Math.max(0, Math.round(g.hp)))}`;
    el.appendChild(d);
  }
}
function barUI() {
  const S = NET.S, bar = $('netBar'); if (!S) return;
  bar.hidden = false;
  if (NET.status !== 'live') { bar.textContent = S.result || 'نبرد تمام شد.'; return; }
  const left = Math.max(0, NET.deadline - Date.now() / 1000), h = Math.floor(left / 3600), m = Math.floor(left % 3600 / 60);
  const tg = guns.find(g => g.uid === S.turn);
  const who = NET.myTurn ? 'نوبت توست' : `نوبت «${esc(tg ? tg.uname : '?')}»`;
  bar.textContent = `⏳ ${who} — ${FA(h)}:${FA(String(m).padStart(2, '0'))} مانده — ${S.city_fa}`;
}
setInterval(barUI, 20000);
function tgtUI() {
  const b = $('tgtBtn'), me = meGun(), foes = guns.filter(g => g !== me && !g.destroyed && !(me.mine && g.mine));
  b.hidden = !(NET.myTurn && foes.length > 1);
  const t = foeOf(me); b.textContent = '🎯 هدف: «' + (t ? t.uname : '?') + '»';
}
function setPlates() {
  const A = meGun(), B = foeOf(A);
  [[0, A], [1, B]].forEach(([k, g]) => {
    const pl = $('plate' + k); pl.style.setProperty('--team', g.team.css);
    pl.querySelector('.pname').innerHTML = (k === 0 ? '<span class="dot"></span>' : '') + '<span class="fa">«' + esc(g.uname) + '»</span>' + (k === 1 ? '<span class="dot"></span>' : '');
    $('hp' + k).style.width = Math.max(0, g.hp) + '%'; $('hpn' + k).textContent = FA(Math.max(0, Math.round(g.hp)));
  });
  rosterUI(); tgtUI();
}
function adopt(S) {
  NET.S = S; NET.status = S.status; NET.myTurn = !!S.my_turn; NET.deadline = Date.now() / 1000 + (S.deadline_in || 0);
  const me = meGun(); game.turn = me.n;
  game.wind = { x: S.wind.x, z: S.wind.z };
  if (NET.status !== 'live') { game.state = 'over'; game.winner = me.n; showEnd(S); }
  else game.state = NET.myTurn && !me.destroyed ? 'aim' : 'wait';
  if (game.state === 'aim') { aimBase(me); poseGun(me); banner('نوبت توست<small>توپ را تنظیم کن و آتش کن</small>', 2.4); }
  setPlates(); setTurnUI(); barUI();
}
function showEnd(S) {
  $('endEyebrow').textContent = S.city_fa;
  $('endTitle').textContent = S.won ? 'پیروز شدی!' : (S.lost ? 'توپت منهدم شد' : 'نبرد تمام شد');
  $('endText').textContent = S.result || '';
  setTimeout(() => { $('endOv').hidden = false; }, 1400);
}
async function netLoad(first) {
  const S = await netApi('/api/battle?b=' + encodeURIComponent(NET.b));
  if (first) {
    env.loc = S.city; env.time = S.time; env.weather = S.weather;
    makeGuns(S); seed = S.seed >>> 0; newField();
    const seen = +(localStorage.getItem('cb-seen-' + NET.b) || 0) || 0;
    const shots = S.shots, last = shots[shots.length - 1];
    const playLast = last && seen < shots.length && !(guns.find(g => g.uid === last.by) || {}).mine;
    shots.slice(0, playLast ? shots.length - 1 : shots.length).forEach(applyShot);
    if (playLast) {
      const earlier = JSON.parse(JSON.stringify(S)); // hp before the last shot
      for (const u of earlier.units) { const h = (last.before || {})[u.id]; if (h !== undefined) { u.hp = h; u.alive = h > 0 || u.alive; } }
      applyUnits(earlier, false);
    } else applyUnits(S, false);
    $('netLoad').hidden = true; resize();
    NET.applied = shots.length;
    if (playLast) { game.state = 'replay'; setPlates(); await new Promise(r => setTimeout(r, 1200)); await playTrail(last); applyShot(last); applyUnits(S, true); }
    try { localStorage.setItem('cb-seen-' + NET.b, String(shots.length)); } catch (e) { /* private mode */ }
    adopt(S);
    return;
  }
  if (S.shots.length > NET.applied) {
    const fresh = S.shots.slice(NET.applied);
    for (let k = 0; k < fresh.length; k++) {
      const s = fresh[k], mine = (guns.find(g => g.uid === s.by) || {}).mine;
      if (k === fresh.length - 1 && !mine) await playTrail(s);
      applyShot(s);
    }
    applyUnits(S, true); NET.applied = S.shots.length;
    try { localStorage.setItem('cb-seen-' + NET.b, String(S.shots.length)); } catch (e) { /* private mode */ }
  }
  adopt(S);
}
async function netAfterShot() {
  if (NET.sending) return; NET.sending = true; game.state = 'sending'; setTurnUI();
  const g = cur(), t = foeOf(g), rec = NET.rec || {}; NET.rec = null;
  const hp = {}; for (const x of guns) hp[x.uid] = Math.max(0, Math.round(x.hp));
  try {
    const S = await netApi('/api/battle/shot', { b: NET.b, unit: g.uid, target: t.uid, elev: g.elev, trav: g.trav, charge: g.charge,
      ammo: rec.ammo || 'shot', wind: game.wind, trail: rec.trail || [], craters: rec.craters || [], kind: rec.kind || '', hp });
    NET.applied = S.shots.length;
    try { localStorage.setItem('cb-seen-' + NET.b, String(S.shots.length)); } catch (e) { /* private mode */ }
    applyUnits(S, false); adopt(S);
    if (S.status === 'live') toast('شلیک ثبت شد. نوبت بعدی که برسد، ربات خبرت می‌کند.');
  } catch (e) { toast('⚠️ ' + e.message); try { await netLoad(false); } catch (e2) { /* ignore */ } }
  NET.sending = false;
}
async function netBoot() {
  if (!NET.b) { $('netLoad').textContent = 'این صفحه را از دکمه ربات باز کن.'; return; }
  try { await netLoad(true); } catch (e) { $('netLoad').textContent = '⚠️ ' + e.message; return; }
  setInterval(async () => { if (game.state === 'wait' && !NET.playing && document.visibilityState === 'visible') { try { await netLoad(false); } catch (e) { /* offline */ } } }, 20000);
}
$('tgtBtn').addEventListener('click', () => {
  const me = meGun(), foes = guns.filter(g => g !== me && !g.destroyed && !(me.mine && g.mine)); if (!foes.length || !humanCanAct()) return;
  const k = foes.indexOf(foeOf(me)); me.target = foes[(k + 1) % foes.length].n; aimBase(me); poseGun(me); setPlates(); updateWindUI();
});
$('againBtn').addEventListener('click', () => { if (TG) TG.close(); else $('endOv').hidden = true; });
$('titleBtn').addEventListener('click', () => { $('endOv').hidden = true; });
"""

FLAGS_JS = r"""
const TEAMS = [
  { key: 'fr', name: 'Grande Batterie', side: 'French battery', css: 'var(--france)', chip: '#5b7fd6', carriage: 0x56602f, flag: 'fr', coat: 0x1f2c5c, facing: 0xb02a22, plume: 0xb02a22 },
  { key: 'gb', name: 'Royal Artillery', side: 'British battery', css: 'var(--britain)', chip: '#d24a3c', carriage: 0x5d6970, flag: 'gb', coat: 0x1b2240, facing: 0xb02a22, plume: 0xeeeae0 },
  { key: 'ot', name: 'Topçu Ocağı', side: 'Ottoman battery', css: 'var(--ottoman)', chip: '#c8352e', carriage: 0x6a3a22, flag: 'ot', coat: 0x8a1c1c, facing: 0x1d4a7a, plume: 0xeeeae0 },
  { key: 'pr', name: 'Prussian Artillery', side: 'Prussian battery', css: 'var(--prussia)', chip: '#9aa3b5', carriage: 0x3f4a54, flag: 'pr', coat: 0x1a1d26, facing: 0x111111, plume: 0x222222 },
  { key: 'ru', name: 'Russian Artillery', side: 'Russian battery', css: 'var(--russia)', chip: '#4f9b5c', carriage: 0x4e5a34, flag: 'ru', coat: 0x24402a, facing: 0x9a1f1f, plume: 0x111111 },
  { key: 'at', name: 'Austrian Artillery', side: 'Austrian battery', css: 'var(--austria)', chip: '#e9d27a', carriage: 0x5b4a2e, flag: 'at', coat: 0xd8d2c2, facing: 0x8a1c1c, plume: 0xe9d27a },
  { key: 'es', name: 'Spanish Artillery', side: 'Spanish battery', css: 'var(--spain)', chip: '#e0a23a', carriage: 0x5a4430, flag: 'es', coat: 0x22305a, facing: 0xb02a22, plume: 0xe0a23a },
  { key: 'se', name: 'Swedish Artillery', side: 'Swedish battery', css: 'var(--sweden)', chip: '#4f8ad6', carriage: 0x4a5a6a, flag: 'se', coat: 0x2a4a8a, facing: 0xe9d27a, plume: 0xe9d27a },
];
const TEAM_BY = Object.fromEntries(TEAMS.map(t => [t.key, t]));
function flagTexture(kind) {
  return canvasTex(240, 150, x => {
    const bands = (cols, vertical) => cols.forEach((c, i) => { x.fillStyle = c; if (vertical) x.fillRect(i * 240 / cols.length, 0, 240 / cols.length + 1, 150); else x.fillRect(0, i * 150 / cols.length, 240, 150 / cols.length + 1); });
    if (kind === 'fr') bands(['#25439b', '#efeadf', '#c42f29'], true);
    else if (kind === 'ru') bands(['#efeadf', '#2c4ea0', '#c42f29'], false);
    else if (kind === 'at') bands(['#1b1b1b', '#e8c43a'], false);
    else if (kind === 'pr') { bands(['#efeadf'], false); x.fillStyle = '#1b1b1b'; x.fillRect(0, 0, 240, 30); x.fillRect(0, 120, 240, 30); x.beginPath(); x.arc(120, 75, 26, 0, 7); x.fill(); }
    else if (kind === 'es') { bands(['#c42f29', '#e8c43a', '#e8c43a', '#c42f29'], false); }
    else if (kind === 'se') { bands(['#2c5ea0'], false); x.fillStyle = '#e8c43a'; x.fillRect(70, 0, 30, 150); x.fillRect(0, 60, 240, 30); }
    else if (kind === 'ot') {
      bands(['#c42f29'], false); x.fillStyle = '#efeadf'; x.beginPath(); x.arc(105, 75, 40, 0, 7); x.fill();
      x.fillStyle = '#c42f29'; x.beginPath(); x.arc(118, 75, 33, 0, 7); x.fill();
      x.fillStyle = '#efeadf'; x.beginPath(); for (let k = 0; k < 10; k++) { const a = -Math.PI / 2 + k * Math.PI / 5, r = k % 2 ? 7 : 17; x.lineTo(160 + Math.cos(a) * r, 75 + Math.sin(a) * r); } x.fill();
    }
    else {
      x.fillStyle = '#1d3474'; x.fillRect(0, 0, 240, 150); x.strokeStyle = '#efeadf'; x.lineWidth = 30;
      x.beginPath(); x.moveTo(0, 0); x.lineTo(240, 150); x.moveTo(240, 0); x.lineTo(0, 150); x.stroke();
      x.strokeStyle = '#c42f29'; x.lineWidth = 10; x.stroke();
      x.fillStyle = '#efeadf'; x.fillRect(0, 50, 240, 50); x.fillRect(95, 0, 50, 150);
      x.fillStyle = '#c42f29'; x.fillRect(0, 60, 240, 30); x.fillRect(105, 0, 30, 150);
    }
  });
}
"""

REPL = [
    # telegram script
    ('<script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>',
     '<script src="https://telegram.org/js/telegram-web-app.js"></script>\n'
     '<script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>'),
    ('<title>Counter-Battery</title>', '<title>نبرد توپخانه</title>'),
    # Persian controls
    ('<label for="elev">Elevation</label>', '<label for="elev">زاویه</label>'),
    ('<label for="trav">Traverse</label>', '<label for="trav">چرخش</label>'),
    ('<label for="charge">Powder</label>', '<label for="charge">باروت</label>'),
    ('aria-checked="true">Shot</button>', 'aria-checked="true">گلوله</button>'),
    ('aria-checked="false">Shell <span', 'aria-checked="false">خمپاره <span'),
    ('<button type="button" class="fire" id="fireBtn">Fire</button>',
     '<button type="button" id="tgtBtn" hidden>🎯 هدف</button>\n      <button type="button" class="fire" id="fireBtn">آتش!</button>'),
    ('<strong>New engagement</strong><span>Fresh ground, new sky.</span>', '<strong>بستن</strong><span>برگشت به ربات</span>'),
    ('<strong>Change battlefield</strong><span>Back to the start.</span>', '<strong>دیدن میدان</strong><span>نگاهی به میدان نبرد</span>'),
    # teams and flags
    (None, 'TEAMS'),
    # guns are made from the bot's battle data
    ("const guns = [0, 1].map(n => ({ n, team: TEAMS[n], x: 0, z: 0, baseYaw: 0, elev: 20, trav: 0, charge: 3.5, ammo: 'shot', shells: 4, hp: 100, mesh: null, report: '', destroyed: false }));\nguns.forEach(g => { g.mesh = buildGun(g.team); });",
     "let guns = [];"),
    ("const isAI = n => game.mode === 'ai' && n === 1;", "const isAI = n => false;"),
    ("function frameFor(g) { const o = guns[1 - g.n],", "function frameFor(g) { const o = foeOf(g),"),
    ("  guns[0].x = -80; guns[0].z = (r() - 0.5) * 44; guns[0].baseYaw = 0;\n  guns[1].x = 80; guns[1].z = (r() - 0.5) * 44; guns[1].baseYaw = Math.PI;\n  propSpot = { x: (r() - 0.5) * 50, z: -58 };",
     "  placeGuns(r);\n  propSpot = { x: (r() - 0.5) * 50, z: guns.length > 2 ? -68 : -58 };"),
    ("const avoid = [{ x: guns[0].x, z: guns[0].z, r: 9 }, { x: guns[1].x, z: guns[1].z, r: 9 }, { x: propSpot.x, z: propSpot.z, r: 16 }];",
     "const avoid = guns.map(g => ({ x: g.x, z: g.z, r: 13 })).concat([{ x: propSpot.x, z: propSpot.z, r: 16 }]);"),
    ("game.turn = 0; game.shotsFired = [0, 0]; game.aiErr = 1.35; game.trails = [[], []]; game.winner = -1;",
     "game.turn = 0; game.shotsFired = guns.map(() => 0); game.aiErr = 1.35; game.trails = guns.map(() => []); game.winner = -1;"),
    ("$('rangeTxt').textContent = Math.round(f.dist * YARDS) + ' yds apart';", "$('rangeTxt').textContent = FA(Math.round(f.dist * YARDS)) + ' یارد فاصله';"),
    # whose turn / who can shoot
    ("function humanCanAct() { return game.state === 'aim' && !isAI(game.turn); }",
     "function humanCanAct() { return game.state === 'aim' && NET.myTurn && cur().mine && !cur().destroyed; }"),
    ("  $('plate0').classList.toggle('active', game.turn === 0);\n  $('plate1').classList.toggle('active', game.turn === 1);",
     "  $('plate0').classList.toggle('active', !!(NET.S && NET.S.turn === meGun().uid));\n  $('plate1').classList.toggle('active', !!(NET.S && NET.S.turn === foeOf(meGun()).uid));"),
    ("ui.fire.textContent = can ? 'Fire' : (game.state === 'flight' || game.state === 'after' ? 'Round away' : 'Wait');",
     "ui.fire.textContent = can ? 'آتش!' : (game.state === 'flight' || game.state === 'after' || game.state === 'sending' ? 'گلوله در راه…' : NET.status !== 'live' ? 'پایان نبرد' : 'نوبت حریف');"),
    ("function updateHP() {\n  guns.forEach(g => {\n    $('hp' + g.n).style.width = Math.max(0, g.hp) + '%';\n    $('hpn' + g.n).textContent = Math.max(0, Math.round(g.hp));\n  });\n}",
     "function updateHP() { if (guns.length) setPlates(); }"),
    # wind words
    ("$('windTxt').textContent = mph + ' mph';", "$('windTxt').textContent = FA(mph) + ' مایل';"),
    ("let d = 'calm';\n  if (mph >= 2) { if (Math.abs(along) > Math.abs(side)) d = along > 0 ? 'following wind' : 'head wind'; else d = side > 0 ? 'blowing to your right' : 'blowing to your left'; }",
     "let d = 'آرام';\n  if (mph >= 2) { if (Math.abs(along) > Math.abs(side)) d = along > 0 ? 'باد از پشت' : 'باد روبه‌رو'; else d = side > 0 ? 'باد به راست' : 'باد به چپ'; }"),
    # record what the shot does
    ("function crater(x, z, r, depth, burn) {", "function crater(x, z, r, depth, burn) {\n  if (NET.rec) NET.rec.craters.push([+x.toFixed(2), +z.toFixed(2), r, depth, burn]);"),
    ("  game.state = 'flight'; preview.visible = false;", "  NET.rec = { craters: [], trail: [], ammo: g.ammo === 'shell' || shot.ammo === 'shell' ? 'shell' : 'shot' };\n  game.state = 'flight'; preview.visible = false;"),
    ("        shot.trailStep = 0; linePush(liveTrail, shot.p);", "        shot.trailStep = 0; linePush(liveTrail, shot.p);\n        if (NET.rec) NET.rec.trail.push([+shot.p.x.toFixed(2), +shot.p.y.toFixed(2), +shot.p.z.toFixed(2)]);"),
    ("  game.afterPoint.copy(point);\n  const g = guns[s.owner], name = s.ammo === 'shell' ? 'Shell' : 'Round shot';",
     "  game.afterPoint.copy(point);\n  if (NET.rec) { NET.rec.kind = kind; NET.rec.trail.push([+point.x.toFixed(2), +point.y.toFixed(2), +point.z.toFixed(2)]); }\n  const g = guns[s.owner], name = s.ammo === 'shell' ? 'خمپاره' : 'گلوله';"),
    ("lineCopy(oldTrails[s.owner], liveTrail);", "lineCopy(oldTrails[s.owner % 2], liveTrail);"),
    ("if (kind === 'hit') txt = '<b>' + name + ' · direct hit</b>';\n  else if (kind === 'lost') txt = '<b>' + name + '</b> · lost beyond the field';",
     "if (kind === 'hit') txt = '<b>' + name + ' · اصابت مستقیم</b>';\n  else if (kind === 'lost') txt = '<b>' + name + '</b> · از میدان بیرون رفت';"),
    ("const rangeTxt = al < 6 ? 'on the range' : al + ' yds ' + (sp.along < 0 ? 'short' : 'over');\n    const sideTxt = si < 4 ? 'dead on line' : si + ' yds ' + (sp.side > 0 ? 'right' : 'left');\n    txt = '<b>' + name + '</b> · ' + rangeTxt + ' · ' + sideTxt + (s.bounces ? ' · ' + s.bounces + (s.bounces === 1 ? ' ricochet' : ' ricochets') : '');",
     "const rangeTxt = al < 6 ? 'برد درست' : FA(al) + ' یارد ' + (sp.along < 0 ? 'کوتاه' : 'بلند');\n    const sideTxt = si < 4 ? 'روی خط' : FA(si) + ' یارد ' + (sp.side > 0 ? 'راست' : 'چپ');\n    txt = '<b>' + name + '</b>، ' + rangeTxt + '، ' + sideTxt + (s.bounces ? '، ' + FA(s.bounces) + ' بار کمانه' : '');"),
    ("showReport((isAI(s.owner) ? 'Enemy · ' : game.mode === 'duo' ? esc(g.team.name) + ' · ' : '') + txt);",
     "showReport('<span class=\"fa\">«' + esc(g.uname || '') + '» · ' + txt + '</span>');"),
    ("if (kind === 'hit') banner('Direct hit<small>' + esc(guns[1 - s.owner].team.name) + ' is struck</small>', 1.8);",
     "if (kind === 'hit') banner('اصابت!<small>«' + esc(foeOf(g).uname) + '» آسیب دید</small>', 1.8);"),
    ("const target = guns[1 - g.n], tc = gunCenter(target), f = frameFor(g);", "const target = foeOf(g), tc = gunCenter(target), f = frameFor(g);"),
    ("const w = guns.find(g => !g.destroyed) || guns[0], l = guns[1 - w.n];", "const w = guns.find(g => !g.destroyed) || guns[0], l = guns.find(g => g.destroyed) || guns[0];"),
    # camera
    ("if (s === 'over') { const g = guns[1 - game.winner];", "if (s === 'over') { const g = guns.find(x => x.destroyed) || meGun();"),
    ("if ((s === 'aim' || s === 'aiThink' || s === 'aiLay') && game.fieldView) { const mz = (guns[0].z + guns[1].z) / 2;",
     "if ((s === 'aim' || s === 'wait' || s === 'aiThink' || s === 'aiLay') && game.fieldView) { const mz = guns.reduce((a, g) => a + g.z, 0) / Math.max(1, guns.length);"),
    ("  if (s === 'aim' || s === 'aiThink' || s === 'aiLay') {\n    const g = cur(),",
     "  if (s === 'aim' || s === 'wait' || s === 'aiThink' || s === 'aiLay') {\n    const g = cur(),"),
    # range profile between me and my target
    ("const A = guns[0], B = guns[1], Ln = Math.hypot(B.x - A.x, B.z - A.z);", "const A = cur(), B = foeOf(A), Ln = Math.hypot(B.x - A.x, B.z - A.z) || 1;"),
    ("pctx.strokeStyle = colors[n] + (live ? '0.95)' : '0.55)');", "pctx.strokeStyle = colors[n % 2] + (live ? '0.95)' : '0.55)');"),
    ("const A = guns[0], B = guns[1], L2 = (B.x - A.x) ** 2 + (B.z - A.z) ** 2;", "const A = cur(), B = foeOf(A), L2 = ((B.x - A.x) ** 2 + (B.z - A.z) ** 2) || 1;"),
    ("game.trails[shot.owner].push(", "(game.trails[shot.owner] || (game.trails[shot.owner] = [])).push("),
    # after the shot: report to the bot instead of the local next turn
    ("if (game.timer <= 0) { if (guns.some(g => g.destroyed)) gameOver(); else nextTurn(); }", "if (game.timer <= 0) netAfterShot();"),
    # start: ask the bot for the battle
    ("choice.city = 'random'; optCity.value = 'random';\nrollEnv(); newField(); setPlaceLine();\nresize();\nsetTurnUI();",
     "resize();\nnetBoot();"),
]


def build():
    s = open(SRC, encoding="utf8").read()
    for old, new in REPL:
        if old is None:
            a = s.index("const TEAMS = [")
            b = s.index("const lanternMats = [];")
            s = s[:a] + FLAGS_JS.strip() + "\n" + s[b:]
            continue
        assert s.count(old) == 1, ("not found once", old[:80], s.count(old))
        s = s.replace(old, new)
    s = s.replace("</style>", "</style>" + CSS, 1)
    s = s.replace('<canvas id="scene"', BODY + '<canvas id="scene"', 1)
    marker = "/* ===================== main loop ===================== */"
    assert s.count(marker) == 1
    s = s.replace(marker, NET_JS + "\n" + marker)
    open(OUT, "w", encoding="utf8").write(s)
    print("wrote", OUT, len(s) // 1024, "KB")


if __name__ == "__main__":
    build()
