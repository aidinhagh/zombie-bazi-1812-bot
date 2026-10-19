"""Build webapp/balloon.html (the war-balloon bombing Mini App) from the user's game (webapp/balloon_source.html).
The bot decides the city, its current damage, time of day and weather; the raid's result is reported back once."""
import os

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "..", "zombiebot", "webapp", "balloon_source.html")
OUT = os.path.join(HERE, "..", "zombiebot", "webapp", "balloon.html")

CSS = """<style>
#cityList,.cols>div:first-child>.lblh,#diffChips,#diffNote,#timeChips,#wxChips,.field[for=prevDmg],#againBtn,#menuBtn,#copyBtn{display:none!important}
#titleScreen .lblh{display:none}
#netNote{margin:8px 0;padding:8px 10px;border:1px solid rgba(201,161,75,.4);font-size:14px;direction:rtl}
</style>"""

NET = r"""
/* ================= Zombie Bazi bot: the raid is set by the bot and its result goes back to it ================= */
(function(){
 const TG=window.Telegram&&window.Telegram.WebApp;if(TG){try{TG.ready();TG.expand();}catch(e){}}
 const bid=new URLSearchParams(location.search).get('b');
 const init=()=>(TG&&TG.initData)||new URLSearchParams(location.search).get('init')||'';
 async function api(path,body){const o={headers:{'X-Init-Data':init()}};if(body){o.method='POST';o.headers['Content-Type']='application/json';o.body=JSON.stringify(body);}
  const r=await fetch(path,o),t=await r.text();let j;try{j=JSON.parse(t);}catch(e){throw new Error(t||r.status);}if(!r.ok)throw new Error(j.error||r.status);return j;}
 const note=document.createElement('div');note.id='netNote';const sb=$('startBtn');sb.parentNode.insertBefore(note,sb);
 sb.disabled=true;note.textContent='⏳ در حال گرفتن مأموریت از ربات…';
 let sent=false;
 api('/api/balloon?b='+encodeURIComponent(bid||'')).then(S=>{
  if(S.done){note.textContent='این بمباران قبلاً انجام شده: '+S.done;return;}
  SEL.city=S.city;SEL.t=S.time;SEL.w=S.weather;SEL.d='normal';$('prevDmg').value=S.prev;
  renderTitle();build();note.textContent=`🎯 هدف: ${S.city_fa} · ویرانی فعلی ${fa(S.prev)}٪ · فقط یک بار می‌توانی پرواز کنی.`;sb.disabled=false;
 }).catch(e=>{note.textContent='⚠️ '+e.message;});
 const _end=endGame;
 endGame=function(){const was=G.state;_end();if(was!=='play'||sent)return;sent=true;
  api('/api/balloon/result',{b:bid,pct:raidPct(),shot:G.reason==='shot'}).then(()=>{$('reportText').textContent='✅ نتیجه به ربات رسید.\n\n'+$('reportText').textContent;})
  .catch(e=>{$('reportText').textContent='⚠️ '+e.message+'\n\n'+$('reportText').textContent;});};
 if(window.__dbg)window.__dbg.endGame=endGame;
})();
"""

def build():
    s = open(SRC, encoding="utf8").read()
    s = s.replace('<script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>',
                  '<script src="https://telegram.org/js/telegram-web-app.js"></script>\n<script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>', 1)
    s = s.replace("</style>", "</style>" + CSS, 1)
    s = s.replace("← عددی که گاد در ربات وارد می‌کند", "← خودکار در ربات ثبت می‌شود")
    assert s.count("\nstart();\n") == 1
    s = s.replace("\nstart();\n", "\nstart();\n" + NET, 1)
    open(OUT, "w", encoding="utf8").write(s)
    print("wrote", OUT)

if __name__ == "__main__":
    build()
