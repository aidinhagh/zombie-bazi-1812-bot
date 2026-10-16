"""City places: night modifiers, special rules and shops.

Modifiers are active only for the night you are locked in that city.
"all" adds to every power (attack, protect, defuse, spy, stealth).
"hp" here is a *temporary* hp change for that night (Barcelona's loss is
permanent and handled separately). A war-balloon raid that destroys d% of a
place cuts its positive modifiers by d% (negatives stay).
"""

LOCATIONS = {
    "london": {
        "fa": "لندن (تاکسی)", "en": "London (Taxi)", "place_fa": "تاکسی", "place_en": "Taxi",
        "mods": {}, "flags": ["taxi"], "shop": "ship",
        "desc_fa": "بعد از قفل نقشه می‌تونی با تاکسی مخفیانه به هر شهری بری.",
        "desc_en": "After the 20:00 lock you may take a taxi to any city; the public map keeps showing London.",
    },
    "paris": {
        "fa": "پاریس (میدان شهر)", "en": "Paris (Town Square)", "place_fa": "میدان شهر", "place_en": "Town Square",
        "mods": {"all": -4}, "flags": ["vote_plus"], "shop": None,
        "desc_fa": "شب اینجا باشی، روز بعد رأیت +۱ می‌شه ولی همه قدرت‌ها −۴.",
        "desc_en": "Spend the night here: next day your vote counts +1, but all powers −4.",
    },
    "birmingham": {
        "fa": "بیرمنگام (ایستگاه پلیس)", "en": "Birmingham (Police Station)", "place_fa": "ایستگاه پلیس", "place_en": "Police Station",
        "mods": {"attack": 8, "hp": -4, "protect": -4, "stealth": -4}, "flags": [], "shop": None,
        "desc_fa": "حمله +۸، اچ‌پی −۴، محافظت −۴، مخفی‌کاری −۴", "desc_en": "Attack +8, HP −4, Protect −4, Stealth −4",
    },
    "amsterdam": {
        "fa": "آمستردام (بیمارستان)", "en": "Amsterdam (Hospital)", "place_fa": "بیمارستان", "place_en": "Hospital",
        "mods": {"protect": 6, "hp": 6, "attack": -8}, "flags": [], "shop": "shovel",
        "desc_fa": "محافظت +۶، اچ‌پی +۶، حمله −۸. محل خرید بیل.", "desc_en": "Protect +6, HP +6, Attack −8. Shovel shop.",
    },
    "barcelona": {
        "fa": "بارسلونا (هتل)", "en": "Barcelona (Hotel)", "place_fa": "هتل", "place_en": "Hotel",
        "mods": {}, "flags": ["hotel"], "shop": None,
        "desc_fa": "اعدام نمی‌شی ولی استت‌ها نصف و ۱۰ اچ‌پی دائمی کم می‌شه (اگه اچ‌پی بالای ۲۰ باشه: نصف و بعد −۱۰).",
        "desc_en": "Can't be executed, but stats are halved and you lose 10 HP permanently (above 20 HP: halved, then −10).",
    },
    "milan": {
        "fa": "میلان (رادیو)", "en": "Milan (Radio)", "place_fa": "رادیو", "place_en": "Radio",
        "mods": {"spy": 5, "stealth": 8}, "flags": ["radio"], "shop": None,
        "desc_fa": "جاسوسی +۵، مخفی‌کاری +۸، دسترسی به رادیو.", "desc_en": "Spy +5, Stealth +8, radio access.",
    },
    "vienna": {
        "fa": "وین (کارخانه)", "en": "Vienna (Factory)", "place_fa": "کارخانه", "place_en": "Factory",
        "mods": {}, "flags": ["vienna_slots"], "shop": None,
        "desc_fa": "۳ بار ماشین اسلات: سه‌تای یکسان → همه قدرت‌ها و اچ‌پی +۲۰، وگرنه همه قدرت‌ها −۲۰. نتیجه دائمی است (حتی بعد از مرگ و زنده شدن) و با دفعه‌های بعد جمع می‌شود.",
        "desc_en": "3 slot pulls: three of a kind → all powers and HP +20, otherwise all powers −20. Permanent, even after revival; stacks.",
    },
    "wagram": {
        "fa": "واگرام (خانقاه)", "en": "Wagram (Monastery)", "place_fa": "خانقاه", "place_en": "Monastery",
        "mods": {}, "flags": ["indep_safe", "double_act_50", "no_convert", "no_steal"], "shop": None,
        "desc_fa": "مستقل‌ها اینجا نمی‌میرن. ۵۰٪ شانس دو اکت. فرقه‌گر و دزد اینجا کار نمی‌کنن.",
        "desc_en": "Independents can't die here. 50% chance of two acts. Cultist and thief can't target you here.",
    },
    "berlin": {
        "fa": "برلین (قبرستان)", "en": "Berlin (Graveyard)", "place_fa": "قبرستان", "place_en": "Graveyard",
        "mods": {"stealth": 4, "protect": 4}, "flags": ["berlin_slots"], "shop": None,
        "desc_fa": "۵ بار اسلات: یک‌بار سه‌تای یکسان → یک مرده زنده می‌شه (هر تیم فقط ۱ نفر). مخفی‌کاری +۴، محافظت +۴.",
        "desc_en": "5 slot pulls: one three of a kind revives a dead player (one per team). Stealth +4, Protect +4.",
    },
    "warsaw": {
        "fa": "ورشو (کلیسا)", "en": "Warsaw (Church)", "place_fa": "کلیسا", "place_en": "Church",
        "mods": {"all": -6}, "flags": ["church"], "shop": None,
        "desc_fa": "کشته نمی‌شی ولی حمله هم نمی‌تونی بکنی. همه قدرت‌ها −۶.",
        "desc_en": "You can't be killed but can't attack. All powers −6.",
    },
    "copenhagen": {
        "fa": "کپنهاگ (بانک)", "en": "Copenhagen (Bank)", "place_fa": "بانک", "place_en": "Bank",
        "mods": {}, "flags": ["bank"], "shop": "mine",
        "desc_fa": "۱۰ سکه می‌گیری ولی اچ‌پی نصف می‌شه. محل خرید مین دریایی.",
        "desc_en": "Get 10 coins but your HP is halved for the night. Sea-mine shop.",
    },
    "stockholm": {
        "fa": "استکهلم (کازینو)", "en": "Stockholm (Casino)", "place_fa": "کازینو", "place_en": "Casino",
        "mods": {"stealth": 6}, "flags": ["casino"], "shop": None,
        "desc_fa": "شرط‌بندی با بقیه (حکم، چهاربرگ، سنگ‌کاغذقیچی). مخفی‌کاری +۶.",
        "desc_en": "Bet against others here (Hokm, four-card, rock-paper-scissors). Stealth +6.",
    },
    "stpetersburg": {
        "fa": "سنت پترزبورگ (بازار)", "en": "St Petersburg (Market)", "place_fa": "بازار", "place_en": "Market",
        "mods": {"all": 4}, "flags": ["vote_minus"], "shop": "war_balloon",
        "desc_fa": "رأی −۱، همه قدرت‌ها +۴. خرید بالن جنگی.", "desc_en": "Vote −1, all powers +4. War-balloon shop.",
    },
    "moscow": {
        "fa": "مسکو (خرابه)", "en": "Moscow (Ruins)", "place_fa": "خرابه", "place_en": "Ruins",
        "mods": {"attack": 4, "stealth": 8, "defuse": 8}, "flags": [], "shop": "spy_balloon",
        "desc_fa": "حمله +۴، مخفی‌کاری +۸، خنثی +۸. خرید بالن جاسوسی.", "desc_en": "Attack +4, Stealth +8, Defuse +8. Spy-balloon shop.",
    },
    "constantinople": {
        "fa": "کنستانتینوپل (مغازه)", "en": "Constantinople (Shop)", "place_fa": "مغازه", "place_en": "Shop",
        "mods": {"defuse": 4, "stealth": 6, "item": 1}, "flags": ["money_plus2"], "shop": "cannon",
        "desc_fa": "خنثی +۴، شانس آیتم +۱، پول +۲، مخفی‌کاری +۶. خرید توپ جنگی.",
        "desc_en": "Defuse +4, item find +1, money +2, Stealth +6. Cannon shop.",
    },
}

# Coins per +1 power for one night (hp is a permanent heal).
POWER_PRICES = {"attack": 3, "protect": 2, "spy": 2, "defuse": 2, "hp": 5, "stealth": 4}

UNIT_PRICES = {"war_balloon": 5, "spy_balloon": 4, "mine": 3, "cannon": 6, "ship": 5, "shovel": 6}
UNIT_NAMES = {
    "war_balloon": ("بالن جنگی", "War balloon"),
    "spy_balloon": ("بالن جاسوسی", "Spy balloon"),
    "mine": ("مین دریایی", "Sea mine"),
    "cannon": ("توپ جنگی", "Cannon"),
    "ship": ("کشتی", "Ship"),
    "shovel": ("بیل", "Shovel"),
}

TOLL = 10            # coins paid when passing someone's cannon/ship square
COINS_PER_HP = 5     # shortfall in a toll is taken from HP at the shop rate
BANK_COINS = 10


# Short city names for squares and routes.
CITY_SHORT = {
    "london": ("لندن", "London"), "paris": ("پاریس", "Paris"), "birmingham": ("بیرمنگام", "Birmingham"),
    "amsterdam": ("آمستردام", "Amsterdam"), "barcelona": ("بارسلونا", "Barcelona"), "milan": ("میلان", "Milan"),
    "vienna": ("وین", "Vienna"), "wagram": ("واگرام", "Wagram"), "berlin": ("برلین", "Berlin"), "warsaw": ("ورشو", "Warsaw"),
    "copenhagen": ("کپنهاگ", "Copenhagen"), "stockholm": ("استکهلم", "Stockholm"), "stpetersburg": ("سن‌پترزبورگ", "St Petersburg"),
    "moscow": ("مسکو", "Moscow"), "constantinople": ("کنستانتینوپل", "Constantinople"),
}
