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
