"""The movement board: cities and the blank squares (nodes) on the routes between them."""
import json
import os
from collections import deque

_MAP = json.load(open(os.path.join(os.path.dirname(__file__), "data", "map.json"), encoding="utf8"))

CITIES = {c["id"]: c for c in _MAP["cities"]}
ROUTES = {r["id"]: r for r in _MAP["routes"]}
COAST = _MAP["coast"]

# square id -> {"id","kind": "city"|"node","lat","lon","route": route id (nodes only),"sea": bool}
SQUARES = {}
for c in _MAP["cities"]:
    SQUARES[c["id"]] = {"id": c["id"], "kind": "city", "lat": c["lat"], "lon": c["lon"], "route": None, "sea": False}
for r in _MAP["routes"]:
    for n in r["nodes"]:
        SQUARES[n["id"]] = {"id": n["id"], "kind": "node", "lat": n["lat"], "lon": n["lon"],
                            "route": r["id"], "sea": r["kind"] == "sea"}


def route_sequence(r):
    return [r["from"], *[n["id"] for n in r["nodes"]], r["to"]]


def all_routes(game):
    """Built-in routes plus routes dug with a shovel."""
    out = dict(ROUTES)
    for r in game.get("extra_routes", []):
        out[r["id"]] = r
    return out


def route_status(game, rid):
    return game.get("route_state", {}).get(rid, "ok")


def adjacency(game, include_blocked=False):
    adj = {}
    for rid, r in all_routes(game).items():
        if not include_blocked and route_status(game, rid) != "ok":
            continue
        seq = route_sequence(r)
        for a, b in zip(seq, seq[1:]):
            adj.setdefault(a, []).append((b, rid))
            adj.setdefault(b, []).append((a, rid))
    return adj


def reachable(game, start, steps):
    """Squares reachable in 1..steps moves -> shortest path (list of squares, excluding start)."""
    adj = adjacency(game)
    prev = {start: None}
    dist = {start: 0}
    q = deque([start])
    while q:
        cur = q.popleft()
        if dist[cur] >= steps:
            continue
        for nb, _ in adj.get(cur, []):
            if nb not in dist:
                dist[nb] = dist[cur] + 1
                prev[nb] = cur
                q.append(nb)
    out = {}
    for sq, d in dist.items():
        if d == 0:
            continue
        path, k = [], sq
        while k != start:
            path.append(k)
            k = prev[k]
        out[sq] = list(reversed(path))
    return out


def routes_touching(game, square, kind=None, include_blocked=True):
    res = []
    for rid, r in all_routes(game).items():
        if kind and r["kind"] != kind:
            continue
        if square in route_sequence(r):
            if include_blocked or route_status(game, rid) == "ok":
                res.append(rid)
    return res


def square_name(sq, lang="fa"):
    s = SQUARES.get(sq)
    if not s:
        return str(sq)
    if s["kind"] == "city":
        from .data.locations import LOCATIONS
        return LOCATIONS[sq][lang]
    r = ROUTES[s["route"]]
    a, b = CITIES[r["from"]]["name"], CITIES[r["to"]]["name"]
    seq = route_sequence(r)
    idx = seq.index(sq)
    sea = r["kind"] == "sea"
    if lang == "fa":
        return f"{'دریا' if sea else 'جاده'} {a}–{b} ({idx}) [{sq}]"
    return f"{'Sea' if sea else 'Road'} {a}–{b} ({idx}) [{sq}]"


def route_name(game, rid, lang="fa"):
    r = all_routes(game)[rid]
    def nm(s):
        return CITIES[s]["name"] if s in CITIES else s
    kind = ("دریایی" if r["kind"] == "sea" else "زمینی") if lang == "fa" else r["kind"]
    return f"{nm(r['from'])}–{nm(r['to'])} ({kind})"
