"""Night resolution. Pure logic: reads the game dict, returns proposed effects.

Nothing changes until the GM approves; each effect can be switched off first.
"""
import random

from .data.roles import ROLES, POWERS, CULT_IMMUNE, ZOMBIE, HUMAN, INDEP, role_name
from .data.locations import LOCATIONS
from .state import team

ACT_STAT = {"attack": "attack", "protect": "protect", "defuse": "defuse", "spy": "spy"}
COLOR = {
    "black": ("سیاه", "black"),
    "white": ("سفید", "white"),
    "gray": ("خاکستری", "gray"),
}


def loc_of(p):
    return p.get("night_pos") or p.get("pos")


def flags_at(sq):
    return LOCATIONS[sq]["flags"] if sq in LOCATIONS else []


def night_stats(g, p):
    """Effective powers for tonight plus a temporary hp modifier."""
    r = ROLES[p["role"]]
    s = {k: r[k] for k in POWERS}
    s["item"] = r["item"]
    hp_mod = 0
    loc = loc_of(p)
    ignore_neg = bool(p["flags"].get("ignore_neg"))
    if loc in LOCATIONS:
        L = LOCATIONS[loc]
        dmg = g["loc_damage"].get(loc, 0)
        for k, v in L["mods"].items():
            if v > 0:
                v = v * (100 - dmg) // 100
            elif ignore_neg:
                continue
            if k == "all":
                for pw in POWERS:
                    s[pw] += v
            elif k == "hp":
                hp_mod += v
            else:
                s[k] += v
        if "vienna_slots" in L["flags"] and p.get("slots") and p["slots"].get("done"):
            if p["slots"].get("hit"):
                bonus = 20 * (100 - dmg) // 100
                for pw in POWERS:
                    s[pw] += bonus
                hp_mod += bonus
            elif not ignore_neg:
                for pw in POWERS:
                    s[pw] -= 20
        if "bank" in L["flags"] and not ignore_neg:
            hp_mod -= p["hp"] // 2
    for k, v in p.get("boost", {}).items():
        if k == "all":
            for pw in POWERS:
                s[pw] += v
        elif k in s:
            s[k] += v
    if loc in LOCATIONS and "hotel" in LOCATIONS[loc]["flags"] and not ignore_neg:
        dmg = g["loc_damage"].get(loc, 0)
        if dmg < 100:
            for pw in POWERS:
                s[pw] = s[pw] // 2
    return s, hp_mod


def spy_view(g, target, by_spy_role, lang):
    """What a spy act shows about target."""
    shown = target["role"]
    if target["role"] == "clown" and target.get("disguise"):
        shown = target["disguise"]
    elif target["role"] == "godfather" and by_spy_role and target.get("fake_role"):
        shown = target["fake_role"]
    if by_spy_role:
        return role_name(shown, lang)
    t = ROLES[shown]["team"]
    if shown == "godfather" or t == HUMAN:
        c = "white"
    elif t == ZOMBIE:
        c = "black"
    else:
        c = "gray"
    return COLOR[c][0 if lang == "fa" else 1]


ACT_FA = {"attack": "⚔️ حمله", "protect": "🛡 محافظت", "defuse": "🧯 خنثی", "spy": "🔍 جاسوسی", "guess": "🎭 حدس نقش",
          "cult_check": "🕯 استعلام فرقه", "bomb": "💣 بمب", "convert": "🕯 فرقه کردن", "steal": "🦹 دزدی", "poison": "🧪 سم",
          "bullets": "🔫 تیر", "duel": "⚖️ دوئل"}
STAT_FA = {"attack": "حمله", "protect": "محافظت", "defuse": "خنثی", "spy": "جاسوسی", "stealth": "مخفی‌کاری"}


class Night:
    def __init__(self, g, rng=None):
        self.g = g
        self.rng = rng or random.Random()
        self.effects = []
        self.lines = []      # (fa, en) for the GM report
        self.dice = {}

    # ---- helpers ----
    def P(self, pid):
        return self.g["players"][str(pid)]

    def nm(self, pid):
        return self.P(pid)["name"]

    def roll(self):
        a, b = self.rng.randint(1, 6), self.rng.randint(1, 6)
        return a + b, (a, b)

    def eff(self, t, fa, en, **kw):
        e = {"id": len(self.effects) + 1, "t": t, "on": True, "fa": fa, "en": en, **kw}
        self.effects.append(e)
        return e

    def line(self, fa, en):
        self.lines.append((fa, en))

    # ---- main ----
    def resolve(self):
        g = self.g
        alive = {pid: p for pid, p in g["players"].items() if p["alive"] and p["role"]}
        stats = {pid: night_stats(g, p) for pid, p in alive.items()}
        self.stats = stats
        acts = []
        for pid, lst in g["acts"].items():
            if pid not in alive:
                continue
            for a in lst:
                a = dict(a)
                a["by"] = pid
                a["active"] = True
                a["note"] = []
                if a.get("target") is not None:
                    a["target"] = str(a["target"])
                    if a["target"] not in alive and a["type"] not in ("cult_check",):
                        a["active"] = False
                        a["note"].append("هدف قبلاً مرده")
                st = stats[pid][0]
                if a.get("as_role") in ROLES:
                    # the thief's borrowed act: the stolen role's stats, the thief's place and boosts
                    st = night_stats(g, {**alive[pid], "role": a["as_role"]})[0]
                stat = ACT_STAT.get(a["type"], "stealth")
                base = st[stat]
                a["stat"], a["stat_val"] = stat, base
                a["stat_raw"] = ROLES[a.get("as_role") or alive[pid]["role"]][stat]
                thrown = a.get("dice")
                if isinstance(thrown, (list, tuple)) and len(thrown) == 2 and all(1 <= int(v) <= 6 for v in thrown):
                    d = (int(thrown[0]), int(thrown[1]))          # the player's own 2d6
                    tot = d[0] + d[1]
                else:
                    tot, d = self.roll()                           # not thrown: the bot throws for them
                    a["note"].append("تاس را ربات ریخت")
                a["dice"] = d
                a["power"] = max(0, base + tot)
                a["power0"] = a["power"]
                acts.append(a)
        self.acts = acts

        def at_church(pid):
            return "church" in flags_at(loc_of(self.P(pid)))

        def at(pid, flag):
            return flag in flags_at(loc_of(self.P(pid)))

        # church: no attacking from inside
        for a in acts:
            if a["type"] == "attack" and a["active"] and at_church(a["by"]):
                a["active"] = False
                a["note"].append("در کلیسا حمله ممنوع")
                self.line(f"{self.nm(a['by'])} در کلیساست و نمی‌تونه حمله کنه.",
                          f"{self.nm(a['by'])} is in the church and cannot attack.")

        # ---- 1. thief ----
        # The steal itself always happens (it can't be defused); only the borrowed act can be.
        stolen_ok = set()
        for a in [x for x in acts if x["type"] == "steal" and x["active"]]:
            tid = a["target"]
            T = self.P(tid)
            if at(tid, "no_steal"):
                self.line(f"دزدی {self.nm(a['by'])} از {T['name']} در خانقاه شکست خورد.",
                          f"{self.nm(a['by'])}'s theft from {T['name']} failed (monastery).")
                continue
            if T["role"] == "spy":
                self.eff("death", f"{self.nm(a['by'])} (دزد) از جاسوس دزدید و کشته شد.",
                         f"{self.nm(a['by'])} (thief) robbed the Spy and dies.", pid=a["by"], cause="thief_spy")
                continue
            stolen_ok.add(a["by"])
            for b in acts:
                if b["by"] == tid and b["active"]:
                    b["active"] = False
                    b["note"].append("نقشش دزدیده شد")
            self.eff("stolen_role", f"دزد نقش {T['name']} ({role_name(T['role'])}) را دزدید؛ اکت {T['name']} انجام نشد.",
                     f"Thief stole {T['name']}'s role; their act is cancelled.",
                     pid=tid, by=a["by"], role=T["role"])
            if T["items"]:
                it = self.rng.choice(T["items"])
                self.eff("lose_item", f"{T['name']} آیتم {it} را به دزد باخت.",
                         f"{T['name']} loses item {it} to the thief.", pid=tid, item=it, to=a["by"])

        for a in acts:
            if a.get("as_role") and a["by"] not in stolen_ok and a["active"]:
                a["active"] = False
                a["note"].append("دزدی انجام نشد")

        # ---- 2. defuse ----
        defuses = [x for x in acts if x["type"] == "defuse" and x["active"]]
        self._team_rule(defuses, "defuse")
        # defuse on a defuser reduces that defuser first (single pass, raw powers)
        red = {}
        for d in [x for x in defuses if x["active"]]:
            red[d["target"]] = red.get(d["target"], 0) + d["power"]
        eff_def = {}
        for d in [x for x in defuses if x["active"]]:
            cut = red.get(d["by"], 0)
            p = d["power"] - cut
            if p <= 0:
                d["active"] = False
                d["note"].append(f"خنثی شد (−{cut})")
            else:
                d["power"] = p
                eff_def[d["target"]] = eff_def.get(d["target"], 0) + p
        for a in acts:
            if a["type"] in ("defuse", "steal") or not a["active"]:
                continue
            cut = eff_def.get(a["by"], 0)
            if cut <= 0:
                continue
            if cut >= a["power"]:
                a["active"] = False
                a["note"].append(f"خنثی شد (−{cut})")
                a["defused"] = True
            else:
                a["power"] -= cut
                a["note"].append(f"ضعیف شد (−{cut})")

        # ---- 3. godfather ----
        for a in [x for x in acts if x["type"] == "guess"]:
            if not a["active"]:
                continue
            T = self.P(a["target"])
            guess = a.get("extra", {}).get("role")
            if guess == T["role"]:
                if at_church(a["target"]):
                    self.line(f"گاز نقش {T['name']} را درست حدس زد ولی او در کلیساست؛ شانس باقی می‌ماند.",
                              f"Godfather guessed {T['name']} right, but they're in the church; the guess is kept.")
                else:
                    self.eff("death", f"گاز نقش {T['name']} ({role_name(T['role'])}) را درست حدس زد → مرگ قطعی (غیرقابل احیا).",
                             f"Godfather correctly guessed {T['name']} ({role_name(T['role'],'en')}) → certain death, can't be revived.",
                             pid=a["target"], cause="guess", unrevivable=True)
                    self.eff("charge", "حدس گاز مصرف شد.", "Godfather's guess is used up.", pid=a["by"], key="guess", delta=-1)
            else:
                self.line(f"حدس گاز درباره {T['name']} ({role_name(guess) if guess in ROLES else guess}) اشتباه بود.",
                          f"Godfather's guess on {T['name']} ({role_name(guess,'en') if guess in ROLES else guess}) was wrong.")
        for a in [x for x in acts if x["type"] == "cult_check"]:
            if not a["active"]:
                continue
            cult = [p["name"] for p in self.g["players"].values() if p["alive"] and team(p) == ZOMBIE and p["cult"]]
            fa = "اعضای فرقه در تیم شما: " + ("، ".join(cult) if cult else "هیچ‌کس")
            en = "Cult members in your team: " + (", ".join(cult) if cult else "none")
            self.eff("private", fa, en, pid=a["by"], to_team=ZOMBIE)
            self.eff("charge", "استعلام فرقه گاز مصرف شد.", "Godfather's cult check is used up.", pid=a["by"], key="cult_check", delta=-1)

        # ---- 4. protect ----
        shield = {}
        for a in [x for x in acts if x["type"] == "protect" and x["active"]]:
            shield[a["target"]] = shield.get(a["target"], 0) + a["power"]

        # ---- 5. attacks ----
        attacks = [x for x in acts if x["type"] == "attack" and x["active"]]
        for a in attacks:
            A, T = self.P(a["by"]), self.P(a["target"])
            arole = a.get("as_role") or A["role"]
            if arole == "sniper" and not A["cult"] and team(T) == HUMAN:
                a["active"] = False
                self.eff("death", f"اسنایپر {A['name']} به انسان ({T['name']}) شلیک کرد و خودش کشته شد.",
                         f"Sniper {A['name']} shot a human ({T['name']}) and dies instead.", pid=a["by"], cause="sniper")
            elif arole == "cult_hunter" and not (T["cult"] or team(T) == INDEP):
                a["power"] = a["power"] // 3
                a["note"].append("⅓ قدرت (هدف فرقه یا مستقل نبود)")
        self._team_rule(attacks, "attack")
        dmg = {}
        for a in [x for x in attacks if x["active"]]:
            dmg[a["target"]] = dmg.get(a["target"], 0) + a["power"]
        dead_now = {e["pid"] for e in self.effects if e["t"] == "death"}
        for tid, d in dmg.items():
            T = self.P(tid)
            if at_church(tid):
                pct = self.g["loc_damage"].get("warsaw", 0)
                d = d * pct // 100              # church: only the destroyed share of attacks gets through
            elif team(T) == INDEP and at(tid, "indep_safe"):
                pct = self.g["loc_damage"].get("wagram", 0)
                d = d * pct // 100              # monastery protects independents the same way
            hp_mod = stats[tid][1]
            sh = shield.get(tid, 0)
            remaining = T["hp"] + hp_mod + sh - d
            loss = max(0, d - sh - max(0, hp_mod))
            who = ", ".join(f"{self.nm(a['by'])}:{a['power']}" for a in attacks if a["active"] and a["target"] == tid)
            hp_txt = f"{T['hp']}" + (f" ({hp_mod:+d} امشب)" if hp_mod else "")
            church = (" · در کلیسا" if at_church(tid) else
                      " · مستقل در خانقاه" if team(T) == INDEP and at(tid, "indep_safe") else "")
            self.line(f"• {T['name']}: حمله‌ها {who} = {d}{church} | سپر {sh} | اچ‌پی {hp_txt} → {'☠️ می‌میرد' if T['hp'] + hp_mod + sh - d <= 0 else 'اچ‌پی ' + str(T['hp'] - max(0, d - sh - max(0, hp_mod)))}",
                      f"Attacks on {T['name']}: total {d} ({who}) | shield {sh} | hp {T['hp']}{hp_mod:+d}")
            if remaining <= 0 and tid not in dead_now:
                if False:
                    pass
                else:
                    self.eff("death", f"{T['name']} با {d} آسیب کشته شد.", f"{T['name']} is killed ({d} damage).",
                             pid=tid, cause="attack")
                    dead_now.add(tid)
            elif loss > 0:
                self.eff("damage", f"{T['name']} {loss} اچ‌پی از دست داد ({T['hp']}→{T['hp']-loss}).",
                         f"{T['name']} loses {loss} hp ({T['hp']}→{T['hp']-loss}).", pid=tid, amount=loss)
        if shield:
            self.line("سپرها: " + ", ".join(f"{self.nm(k)} +{v}" for k, v in shield.items()),
                      "Shields: " + ", ".join(f"{self.nm(k)} +{v}" for k, v in shield.items()))

        # ---- 6. spy ----
        for a in [x for x in acts if x["type"] == "spy" and x["active"]]:
            A, T = self.P(a["by"]), self.P(a["target"])
            is_spy = (a.get("as_role") or A["role"]) == "spy"
            vf, ve = spy_view(self.g, T, is_spy, "fa"), spy_view(self.g, T, is_spy, "en")
            self.eff("private", f"نتیجه جاسوسی شما روی {T['name']}: {vf}", f"Your spy result on {T['name']}: {ve}",
                     pid=a["by"])

        # ---- 7. cultist ----
        for a in [x for x in acts if x["type"] == "convert" and x["active"]]:
            A, T = self.P(a["by"]), self.P(a["target"])
            tid = a["target"]
            if A.get("no_recruit_until", 0) >= self.g["cycle"]:
                self.line(f"فرقه‌گر امشب نمی‌تونه عضو بگیره (دلقک).", "The cultist can't recruit tonight (clown rule).")
                continue
            if T["role"] == "spy":
                self.eff("death", f"فرقه‌گر {A['name']} خواست جاسوس را فرقه کند و کشته شد.",
                         f"Cultist {A['name']} tried to convert the Spy and dies.", pid=a["by"], cause="cult_spy")
                continue
            if T["role"] in CULT_IMMUNE or T["cult"] or at(tid, "no_convert"):
                self.line(f"فرقه کردن {T['name']} ممکن نیست.", f"{T['name']} can't be converted.")
                continue
            tt, td = self.roll()
            tpow = stats[tid][0]["stealth"] + tt
            if a["power"] >= tpow:
                self.eff("convert", f"{T['name']} ({role_name(T['role'])}) عضو فرقه شد ({a['power']} در برابر {tpow}).",
                         f"{T['name']} ({role_name(T['role'],'en')}) joins the cult ({a['power']} vs {tpow}).",
                         pid=tid, by=a["by"])
            else:
                self.line(f"{T['name']} در برابر فرقه مقاومت کرد ({a['power']} در برابر {tpow}).",
                          f"{T['name']} resisted the cult ({a['power']} vs {tpow}).")

        # ---- 8. apothecary ----
        for a in [x for x in acts if x["type"] == "poison" and x["active"]]:
            T = self.P(a["target"])
            if a["by"] in dead_now:
                self.line("عطار امشب مرد؛ سمش نرسید.", "The apothecary died tonight; the poison never arrives.")
                continue
            self.eff("charge", "یک سم عطار مصرف شد.", "One poison used.", pid=a["by"], key="poison", delta=-1)
            if T["role"] == "cultist":
                self.line("سم به فرقه‌گر اثر ندارد.", "Poison has no effect on the cultist.")
                continue
            self.eff("poison", f"سم به {T['name']} رسید (اعلام عمومی).", f"Poison reached {T['name']} (announced).",
                     pid=a["target"], by=a["by"])

        # ---- 9. bomber ----
        for a in [x for x in acts if x["type"] == "bomb" and x["active"]]:
            T = self.P(a["target"])
            if T["role"] == "cultist":
                self.line("بمب روی فرقه‌گر اثر ندارد.", "The bomb does nothing to the cultist.")
                continue
            self.eff("bomb", f"بمب به {T['name']} رسید (سیم درست: {a['extra'].get('wire')}).",
                     f"Bomb delivered to {T['name']} (correct wire: {a['extra'].get('wire')}).",
                     pid=a["target"], by=a["by"], wire=a["extra"].get("wire"), where=loc_of(T))
            if not a.get("as_role"):
                self.eff("charge", "بمب بمب‌گذار مصرف شد (فقط یک بمب دارد).", "The bomber's only bomb is used.",
                         pid=a["by"], key="bomb", delta=-1)

        # ---- 10. musketeer ----
        for a in [x for x in acts if x["type"] == "bullets"]:
            if a["by"] in dead_now:
                continue
            defused = not a["active"]
            targets = a.get("extra", {}).get("targets", [])[:3]
            war = a.get("extra", {}).get("war")
            for t in targets:
                t = str(t)
                if t not in alive:
                    continue
                kind = "war" if (str(war) == t and not defused and self.P(a["by"])["charges"].get("war_bullet", 0) > 0) else "practice"
                self.eff("bullet", f"تیر به {self.nm(t)} داده شد ({'جنگی' if kind == 'war' else 'مشقی'}).",
                         f"Bullet given to {self.nm(t)} ({kind}).", pid=t, by=a["by"], kind=kind)
                if kind == "war":
                    self.eff("charge", "یک تیر جنگی مصرف شد.", "One war bullet used.", pid=a["by"], key="war_bullet", delta=-1)
            if defused and war:
                self.line("تفنگدار خنثی شد؛ تیر جنگی مشقی حساب شد.", "Musketeer was defused; the war bullet became practice.")

        # ---- 11. judge ----
        for a in [x for x in acts if x["type"] == "duel" and x["active"]]:
            b = str(a.get("extra", {}).get("target2"))
            if b in alive:
                self.eff("duel", f"دوئل فردا: {self.nm(a['target'])} و {self.nm(b)}",
                         f"Duel tomorrow: {self.nm(a['target'])} vs {self.nm(b)}", a=a["target"], b=b)

        # act-by-act report for the GM
        report = [("🌙 اکت‌ها، یکی‌یکی:", "")]
        for a in acts:
            A = self.P(a["by"])
            if a["type"] == "bullets":
                tgt = "، ".join(self.nm(x) for x in a.get("extra", {}).get("targets", []) if str(x) in self.g["players"])
            elif a["type"] == "duel":
                ex = a.get("extra", {})
                tgt = f"{self.nm(a['target'])} و {self.nm(ex.get('target2'))}" if ex.get("target2") in self.g["players"] or str(ex.get("target2")) in self.g["players"] else "-"
            else:
                tgt = self.nm(a["target"]) if a.get("target") in self.g["players"] else "—"
            who = f"{A['name']} ({role_name(a.get('as_role') or A['role'])}{' — قرضی از دزدی' if a.get('as_role') else ''})"
            mod = a["stat_val"] - a["stat_raw"]
            modtxt = f" ({'+' if mod > 0 else '−'}{abs(mod)} مکان/خرید/آیتم)" if mod else ""
            d1, d2 = a["dice"]
            calc = f"تاس {d1}+{d2} + {STAT_FA.get(a['stat'], a['stat'])} {a['stat_raw']}{modtxt} = {a['power0']}" + (f" → {a['power']}" if a["power"] != a["power0"] else "")
            extra = ""
            if a["type"] == "guess":
                extra = f" · حدس: {role_name(a.get('extra', {}).get('role', '?'))}"
            if a["type"] == "bomb":
                extra = f" · سیم درست: {a.get('extra', {}).get('wire')}"
            status = "✅" if a["active"] else "❌"
            notes = ("\n    ⚠️ " + "، ".join(a["note"])) if a["note"] else ""
            report.append((f"{status} {ACT_FA.get(a['type'], a['type'])} · {who} ← {tgt}{extra}\n    {calc}{notes}", ""))
        if not acts:
            report.append(("— هیچ اکتی ثبت نشده —", ""))
        report.append(("", ""))
        report.append(("⚔️ حمله‌ها، سپرها و نتیجه روی هر نفر:", ""))
        self.lines = report + (self.lines or [("— حمله‌ای نبود —", "")])
        return {"cycle": self.g["cycle"], "effects": self.effects, "lines": self.lines}

    def _team_rule(self, acts, kind):
        """Hero needs 2+ zombies; priest halves a lone zombie."""
        by_target = {}
        for a in acts:
            if a["active"] and team(self.P(a["by"])) == ZOMBIE:
                by_target.setdefault(a["target"], []).append(a)
        for tid, lst in by_target.items():
            T = self.P(tid)
            if len(lst) != 1:
                continue
            a = lst[0]
            if T["role"] == "hero":
                a["active"] = False
                a["note"].append("زامبیِ تنها در برابر قهرمان")
                self.eff("death", f"{self.nm(a['by'])} تنها به قهرمان {('حمله' if kind == 'attack' else 'خنثی')} کرد و کشته شد.",
                         f"{self.nm(a['by'])} went alone ({kind}) against the Hero and dies.", pid=a["by"], cause="hero")
            elif T["role"] == "priest":
                a["power"] //= 2
                a["note"].append("نصف شد (کاهن)")


def resolve_night(g, rng=None):
    return Night(g, rng).resolve()
