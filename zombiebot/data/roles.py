"""Role cards for the Napoleonic round (from the round's stat tables).

Stats: stealth, hp, defuse, spy, protect, attack, item (item = dart power).
"""

ZOMBIE, HUMAN, INDEP = "zombie", "human", "independent"

# key: (fa, en, team, stealth, hp, defuse, spy, protect, attack, item)
_RAW = {
    # ---- zombie team ----
    "zombie":        ("زامبی",         "Zombie",          ZOMBIE, 30, 38, 3, 3, 2, 14, 3),
    "godfather":     ("گاداف زامبی",   "Godfather Zombie", ZOMBIE, 30, 40, 13, 3, 2, 15, 4),
    "zombie_doctor": ("دکتر زامبی",    "Zombie Doctor",   ZOMBIE, 30, 38, 5, 5, 13, 1, 4),
    "undead":        ("آندد",          "Undead",          ZOMBIE, 30, 38, 15, 3, 2, 2, 3),
    "bomber":        ("بمب گذار",      "Bomber",          ZOMBIE, 31, 39, 13, 3, 2, 2, 4),
    "yakuza":        ("یاکوزا",        "Yakuza",          ZOMBIE, 32, 38, 2, 2, 2, 13, 3),
    # ---- independents ----
    "clown":         ("دلقک",          "Clown",           INDEP, 30, 39, 5, 15, 13, 0, 4),
    "cultist":       ("فرقه گر",       "Cultist",         INDEP, 32, 39, 2, 1, 2, 1, 4),
    "thief":         ("دزد",           "Thief",           INDEP, 30, 39, 2, 2, 2, 2, 4),
    # ---- humans ----
    "hero":          ("قهرمان",        "Hero",            HUMAN, 29, 39, 3, 3, 13, 15, 4),
    "priest":        ("کاهن",          "Priest",          HUMAN, 30, 39, 2, 3, 14, 14, 3),
    "doctor":        ("دکتر",          "Doctor",          HUMAN, 31, 38, 1, 2, 15, 1, 3),
    "spy":           ("جاسوس",         "Spy",             HUMAN, 31, 38, 2, 15, 2, 2, 3),
    "saboteur":      ("خرابکار",       "Saboteur",        HUMAN, 30, 38, 15, 2, 3, 2, 3),
    "apothecary":    ("عطار",          "Apothecary",      HUMAN, 30, 38, 3, 3, 2, 2, 4),
    "sniper":        ("اسنایپر",       "Sniper",          HUMAN, 30, 37, 1, 3, 1, 15, 3),
    "cult_hunter":   ("شکارچی فرقه",   "Cult Hunter",     HUMAN, 29, 39, 4, 4, 1, 15, 3),
    "musketeer":     ("تفنگدار",       "Musketeer",       HUMAN, 31, 39, 4, 4, 1, 3, 4),
    "judge":         ("قاضی",          "Judge",           HUMAN, 30, 39, 4, 4, 1, 3, 4),
}

STATS = ("stealth", "hp", "defuse", "spy", "protect", "attack", "item")
# "All powers" in location/item text = these five (not hp, not item).
POWERS = ("attack", "protect", "defuse", "spy", "stealth")

ROLES = {}
for key, (fa, en, team, *vals) in _RAW.items():
    ROLES[key] = {"key": key, "fa": fa, "en": en, "team": team, **dict(zip(STATS, vals))}

# Roles the cultist can never convert.
CULT_IMMUNE = {"godfather", "hero", "cult_hunter", "thief"}

# Special night acts per role (in addition to attack/protect/defuse/spy, which everyone has).
SPECIALS = {
    "godfather": ["guess", "cult_check"],
    "bomber": ["bomb"],
    "cultist": ["convert"],
    "thief": ["steal"],
    "apothecary": ["poison"],
    "musketeer": ["bullets"],
    "judge": ["duel"],
}

# Starting extras: balloons and consumables.
START_UNITS = {
    "bomber": {"war_balloon": 1},
    "hero": {"war_balloon": 1},
    "spy": {"spy_balloon": 1},
    "zombie_doctor": {"spy_balloon": 1},
}
START_CHARGES = {
    "bomber": {"bomb": 1},
    "apothecary": {"poison": 2},
    "musketeer": {"war_bullet": 2},
    "godfather": {"guess": 1, "cult_check": 1},
    "judge": {"nullify": 1},   # one cancelled execution per game
}
START_COINS = 10


def role_name(key, lang="fa"):
    r = ROLES.get(key)
    return r[lang] if r else key


def team_of(key):
    return ROLES[key]["team"]
