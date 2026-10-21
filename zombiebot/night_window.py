"""Per-night deadlines; an override never carries into another cycle."""
import datetime

def window(g):
    w = g.get("night_window") or {}
    return w if g.get("phase") == "night" and w.get("cycle") == g.get("cycle") else {}

def before(g, key, now=None):
    value = window(g).get(key)
    return bool(value and (now or datetime.datetime.now(datetime.timezone.utc)) < datetime.datetime.fromisoformat(value))

def expired(g, key, now=None):
    return bool(window(g).get(key)) and not before(g, key, now)

def check_actions(g):
    if g.get("phase") == "night" and g.get("applied_cycle") == g.get("cycle"):
        from .actions import GameError
        raise GameError("نتیجه این شب قبلاً اعمال شده است.")
    if expired(g, "acts_until"):
        from .actions import GameError
        raise GameError("مهلت اکت امشب (۰۱:۰۰ تهران) تمام شده است.")

def fingerprint(g):
    import hashlib, json
    return hashlib.sha256(json.dumps({k:v for k,v in g.items() if k not in ("pending", "pending_fingerprint")}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
