"""Legendary items: the only items that are not single-use. Whoever finds one keeps its power for the rest of the game.
They appear one at a time (one per day, starting day 1) in a random city; whoever stands there at the 20:00 lock takes it.
If several people are there, they bid coins for it in a sealed auction. Add more entries here to make more spawn."""

LEGENDARY = {
    "fouche_cipher": {"fa": "رمزنامه سیاه فوشه", "stats": {"spy": 20, "defuse": 20}, "hp": 0,
                      "desc_fa": "جاسوسی +۲۰ و خنثی +۲۰ تا آخر بازی"},
    "charlemagne_mail": {"fa": "زره شارلمانی", "stats": {"protect": 20}, "hp": 20,
                         "desc_fa": "محافظت +۲۰ و اچ‌پی +۲۰ تا آخر بازی"},
    "austerlitz_sabre": {"fa": "شمشیر خورشید آسترلیتز", "stats": {"stealth": 20, "attack": 20}, "hp": 0,
                         "desc_fa": "مخفی‌کاری +۲۰ و حمله +۲۰ تا آخر بازی"},
}
