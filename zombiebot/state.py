"""Game state, stored as one JSON document (survives restarts on a Railway volume)."""
import copy
import json
import os
import random
import tempfile
import threading

from .data.roles import ROLES, START_UNITS, START_CHARGES, START_COINS, POWERS

DATA_DIR = os.environ.get("DATA_DIR", os.path.join(os.path.dirname(os.path.dirname(__file__)), "var"))
STATE_FILE = os.path.join(DATA_DIR, "state.json")


def new_game():
    return {
        "phase": "lobby",          # lobby | day | night
        "cycle": 0,                # night number
        "locked": False,           # 20:00 map lock for the current phase
        "group_id": None,
        "channel_id": None,
        "gm_ids": [],
        "players": {},
        "acts": {},                # pid -> [act]
        "units_on_map": [],        # {"kind","owner","square"}
        "route_state": {},         # rid -> ok|broken|mined
        "extra_routes": [],
        "balloons": [],            # {"kind","owner","target","origin","cycle","result","publish"}
        "loc_damage": {},          # city -> percent destroyed
        "revived_by_team": {},
        "pending": None,           # night result awaiting GM approval
        "poisons": [],
        "bombs": [],
        "duels": [],
        "bets": [],
        "battles": [],
        "artillery": [],           # cannon duels (the Counter-Battery minigame)
        "approve_group": True,     # group posts wait for the GM's ✅ (voting excepted)
        "outbox": [],
        "votes": {},               # voter pid -> target pid
        "vote_cancelled": False,
        "log": [],
        "seq": 0,
    }


def new_player(uid, name, username=None):
    return {
        "id": uid, "name": name, "username": username, "lang": "fa",
        "role": None, "fake_role": None, "alive": True, "hp": 0, "coins": START_COINS,
        "cult": False, "cult_lost_clown": False,
        "pos": None, "night_pos": None, "last_night_pos": None, "public_pos": None,
        "char": None, "fake_char": None, "fake_pos": None, "fake_public_pos": None,
        "items": [], "units": {}, "charges": {}, "bullets": [],
        "boost": {}, "flags": {}, "bought": {},
        "moved": False, "move_roll": None, "darts": {"money": False, "item": False},
        "disguise": None, "slots": None, "double_act": False,
        "no_recruit_until": 0, "unrevivable": False, "death_cycle": None,
    }


class Store:
    def __init__(self, path=STATE_FILE):
        self.path = path
        self.lock = threading.RLock()
        self.g = self._load()

    def _load(self):
        if os.path.exists(self.path):
            with open(self.path, encoding="utf8") as f:
                g = json.load(f)
            base = new_game()
            base.update(g)
            return base
        return new_game()

    def save(self):
        with self.lock:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=os.path.dirname(self.path), suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf8") as f:
                json.dump(self.g, f, ensure_ascii=False, indent=1)
            os.replace(tmp, self.path)

    def backup(self):
        """Snapshot before risky GM actions, so /undo can restore."""
        with self.lock:
            snap = os.path.join(os.path.dirname(self.path), "state.prev.json")
            with open(snap, "w", encoding="utf8") as f:
                json.dump(self.g, f, ensure_ascii=False)

    def snapshot(self, tag="auto", keep=60):
        """A dated copy of the whole game in DATA_DIR/backups (kept on the volume, newest 60)."""
        import time
        with self.lock:
            d = os.path.join(os.path.dirname(self.path), "backups")
            os.makedirs(d, exist_ok=True)
            name = os.path.join(d, time.strftime("state-%Y%m%d-%H%M%S-") + "".join(c for c in tag if c.isalnum())[:20] + ".json")
            with open(name, "w", encoding="utf8") as f:
                json.dump(self.g, f, ensure_ascii=False)
            old = sorted(x for x in os.listdir(d) if x.startswith("state-"))
            for x in old[:-keep]:
                try:
                    os.remove(os.path.join(d, x))
                except OSError:
                    pass
            return name

    def replace(self, g):
        """Load a whole game (from /import). The current one is snapshotted first."""
        with self.lock:
            self.snapshot("before-import")
            base = new_game()
            base.update(g)
            self.g = base
            self.save()

    def undo(self):
        snap = os.path.join(os.path.dirname(self.path), "state.prev.json")
        if not os.path.exists(snap):
            return False
        with open(snap, encoding="utf8") as f:
            self.g = json.load(f)
        self.save()
        return True


# ---------- helpers on the game dict ----------

def player(g, pid):
    return g["players"].get(str(pid))


def alive_players(g):
    return [p for p in g["players"].values() if p["alive"] and p["role"]]


def assign_role(p, role, fake_role=None):
    r = ROLES[role]
    p["role"] = role
    p["hp"] = r["hp"]
    p["fake_role"] = fake_role
    p["units"] = dict(START_UNITS.get(role, {}))
    p["charges"] = dict(START_CHARGES.get(role, {}))
    p["unit_origin"] = {k: "start" for k in p["units"]}


def needs_fake_char(p):
    """Zombies and independents (everyone who isn't human) carry a fake character too."""
    return bool(p.get("role")) and ROLES[p["role"]]["team"] != "human"


def give_characters(g, rng=None):
    """Hand out story characters to everyone with a role who has none yet (and fake ones to non-humans).
    Humans lose a leftover fake character if their role changed."""
    import random as _r
    from .data.characters import CHARACTERS
    rng = rng or _r
    used = set()
    for p in g["players"].values():
        used.update(x for x in (p.get("char"), p.get("fake_char")) if x)
    free = [c for c in CHARACTERS if c not in used]
    rng.shuffle(free)

    def take():
        return free.pop() if free else f"شخصیت {len(used) + 1}"
    for p in sorted(g["players"].values(), key=lambda x: str(x["id"])):
        if not p.get("role"):
            continue
        if not p.get("char"):
            p["char"] = take()
            used.add(p["char"])
        if needs_fake_char(p):
            if not p.get("fake_char"):
                p["fake_char"] = take()
                used.add(p["fake_char"])
        elif p.get("fake_char"):
            p["fake_char"] = p["fake_pos"] = p["fake_public_pos"] = None
        if p["role"] == "godfather" and not p.get("fake_role"):
            p["fake_role"] = rng.choice([k for k, r in ROLES.items() if r["team"] == "human"])


def char_of(p):
    return p.get("char") or p["name"]


def next_id(g, prefix):
    g["seq"] = g.get("seq", 0) + 1
    return f"{prefix}{g['seq']}"


def log(g, text):
    g["log"].append({"cycle": g["cycle"], "phase": g["phase"], "text": text})
    g["log"] = g["log"][-500:]


def team(p):
    return ROLES[p["role"]]["team"] if p.get("role") else None


def find_player(g, query):
    """Find by number in roster, @username, user id or (partial) name."""
    q = str(query).strip().lstrip("@").lower()
    plist = sorted(g["players"].values(), key=lambda p: p["name"].lower())
    if q.isdigit():
        n = int(q)
        if 1 <= n <= len(plist):
            return plist[n - 1]
        if str(n) in g["players"]:
            return g["players"][str(n)]
    for p in plist:
        if (p.get("username") or "").lower() == q:
            return p
    for p in plist:
        if p["name"].lower() == q:
            return p
    hits = [p for p in plist if q in p["name"].lower()]
    return hits[0] if len(hits) == 1 else None


def roster(g):
    return sorted(g["players"].values(), key=lambda p: p["name"].lower())
