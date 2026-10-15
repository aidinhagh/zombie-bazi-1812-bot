"""Draft item list for the 1812 round — edit freely.

Won with the item dart. Each item is single-use. Rarity weights:
common 6, uncommon 3, rare 1.

Effect types the bot understands:
  boost          stats added for the coming night (key "all" = every power)
  heal           permanent +hp
  coins          coins now
  move_plus      +n to your next movement roll
  reroll         roll your movement dice again (use right after a bad roll)
  free_move      next move: go to any city, ignoring the dice
  toll_free      skip the next toll you would pay
  hide           spy balloons don't see you tonight
  ignore_neg     tonight your location's negative modifiers don't apply
  money_dart     +n coins on your next money dart
  item_dart      +n item power on your next item dart
  vote_plus      your vote counts +n in the next execution vote
"""

RARITY_WEIGHT = {"common": 6, "uncommon": 3, "rare": 1}

ITEMS = {
    "bearskin": {
        "fa": "کلاه پوستی گرنادیر", "en": "Grenadier's Bearskin", "rarity": "common",
        "effect": {"type": "boost", "stats": {"protect": 3}},
        "desc_fa": "محافظت +۳ برای یک شب", "desc_en": "Protect +3 for one night",
    },
    "flint": {
        "fa": "سنگ چخماق شارلویل", "en": "Charleville Flint", "rarity": "common",
        "effect": {"type": "boost", "stats": {"attack": 2}},
        "desc_fa": "حمله +۲ برای یک شب", "desc_en": "Attack +2 for one night",
    },
    "spyglass": {
        "fa": "دوربین تک‌چشمی", "en": "Brass Spyglass", "rarity": "common",
        "effect": {"type": "boost", "stats": {"spy": 3}},
        "desc_fa": "جاسوسی +۳ برای یک شب", "desc_en": "Spy +3 for one night",
    },
    "cipher": {
        "fa": "کتابچه رمز", "en": "Cipher Book", "rarity": "common",
        "effect": {"type": "boost", "stats": {"defuse": 3}},
        "desc_fa": "خنثی +۳ برای یک شب", "desc_en": "Defuse +3 for one night",
    },
    "cloak": {
        "fa": "شنل کلاه‌دار", "en": "Hooded Cloak", "rarity": "common",
        "effect": {"type": "boost", "stats": {"stealth": 4}},
        "desc_fa": "مخفی‌کاری +۴ برای یک شب", "desc_en": "Stealth +4 for one night",
    },
    "dressing": {
        "fa": "باند زخم صحرایی", "en": "Field Dressing", "rarity": "common",
        "effect": {"type": "heal", "hp": 3},
        "desc_fa": "اچ‌پی +۳ (دائمی)", "desc_en": "+3 HP (permanent)",
    },
    "louis": {
        "fa": "سکه طلای ناپلئون", "en": "Gold Napoléon", "rarity": "common",
        "effect": {"type": "coins", "n": 4},
        "desc_fa": "۴ سکه", "desc_en": "4 coins",
    },
    "post_horse": {
        "fa": "حواله اسب چاپار", "en": "Post-Horse Warrant", "rarity": "common",
        "effect": {"type": "move_plus", "n": 1},
        "desc_fa": "+۱ به تاس حرکت بعدی", "desc_en": "+1 to your next movement roll",
    },
    "cognac": {
        "fa": "قمقمه کنیاک", "en": "Flask of Cognac", "rarity": "uncommon",
        "effect": {"type": "heal", "hp": 5},
        "desc_fa": "اچ‌پی +۵ (دائمی)", "desc_en": "+5 HP (permanent)",
    },
    "loaded_dice": {
        "fa": "تاس‌های سربی", "en": "Loaded Dice", "rarity": "uncommon",
        "effect": {"type": "reroll"},
        "desc_fa": "تاس حرکتت رو دوباره بریز", "desc_en": "Reroll your movement dice",
    },
    "toll_pass": {
        "fa": "جواز عبور امپراتوری", "en": "Imperial Laissez-passer", "rarity": "uncommon",
        "effect": {"type": "toll_free"},
        "desc_fa": "عوارض بعدی رو نمی‌دی", "desc_en": "Skip the next toll",
    },
    "forged_papers": {
        "fa": "گذرنامه جعلی", "en": "Forged Papers", "rarity": "uncommon",
        "effect": {"type": "hide"},
        "desc_fa": "امشب بالن جاسوسی تو رو نمی‌بینه", "desc_en": "Spy balloons don't see you tonight",
    },
    "letter_credit": {
        "fa": "برات بانک رتشیلد", "en": "Rothschild Letter of Credit", "rarity": "uncommon",
        "effect": {"type": "money_dart", "n": 2},
        "desc_fa": "+۲ سکه روی دارت پول بعدی", "desc_en": "+2 coins on your next money dart",
    },
    "horseshoe": {
        "fa": "نعل اسب خوش‌یمن", "en": "Lucky Horseshoe", "rarity": "uncommon",
        "effect": {"type": "item_dart", "n": 1},
        "desc_fa": "+۱ قدرت آیتم در دارت آیتم بعدی", "desc_en": "+1 item power on your next item dart",
    },
    "powder_keg": {
        "fa": "بشکه باروت سنگرکن", "en": "Sapper's Powder Keg", "rarity": "uncommon",
        "effect": {"type": "boost", "stats": {"attack": 5}, "hp": -2},
        "desc_fa": "حمله +۵ برای یک شب، ولی ۲ اچ‌پی دائمی کم می‌شه", "desc_en": "Attack +5 for one night, but −2 HP (permanent)",
    },
    "laudanum": {
        "fa": "شیشه لودانوم", "en": "Vial of Laudanum", "rarity": "uncommon",
        "effect": {"type": "ignore_neg"},
        "desc_fa": "امشب منفی‌های مکانت اعمال نمی‌شه", "desc_en": "Tonight your location's negative modifiers don't apply",
    },
    "eagle": {
        "fa": "عقاب امپراتوری", "en": "Imperial Eagle Standard", "rarity": "rare",
        "effect": {"type": "boost", "stats": {"all": 2}},
        "desc_fa": "همه قدرت‌ها +۲ برای یک شب", "desc_en": "All powers +2 for one night",
    },
    "legion": {
        "fa": "نشان لژیون دونور", "en": "Légion d'honneur", "rarity": "rare",
        "effect": {"type": "vote_plus", "n": 1},
        "desc_fa": "رأیت در رأی‌گیری بعدی +۱ حساب می‌شه", "desc_en": "Your vote counts +1 in the next execution vote",
    },
    "smuggler_map": {
        "fa": "نقشه قاچاقچی", "en": "Smuggler's Chart", "rarity": "rare",
        "effect": {"type": "free_move"},
        "desc_fa": "حرکت بعدی: بدون تاس به هر شهری برو", "desc_en": "Next move: go to any city, no dice needed",
    },
}
