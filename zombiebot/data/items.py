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
  extra_dart     throw one more money/item dart this phase
  unit           get a unit (spy balloon, shovel, cannon…)
  vote_guard     today: votes against you count n less
  mute           (target) today: that player's vote counts 0
  armor          tonight: attacks on you are n weaker
  revenge        tonight: if attacks kill you, each attacker takes pct% of their attack back
  reflect        tonight: each attacker takes pct% of their attack back, even if you live
  last_stand     tonight: a deadly attack leaves you at 1 hp instead
  spy_mask       tonight: spying on you shows white / a human role
  defuse_immune  tonight: defuses on you don't work
  extra_act      tonight: one more act
  bullet_vest    until used: the next war bullet fired at you fails
  bomb_safe      until used: the next bomb blast doesn't kill you
  poison_safe    until used: the next poison doesn't kill you
  pardon         until used: your next execution is cancelled
  pickpocket     (target) take n coins from them
  trace          (target) learn where they are right now
  reveal         (target) learn their team colour (white / black / gray)
  slow           (target) their next movement roll is n smaller

"Tonight" effects used during the day carry over to the coming night.
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

# ---------------- second wave (x3 list) ----------------
def _it(fa, en, rarity, effect, dfa, den):
    return {"fa": fa, "en": en, "rarity": rarity, "effect": effect, "desc_fa": dfa, "desc_en": den}


ITEMS.update({
    # stat boosts for one night
    "sabre": _it("شمشیر سواره‌نظام", "Cavalry Sabre", "common", {"type": "boost", "stats": {"attack": 4}},
                 "حمله +۴ برای یک شب", "Attack +4 for one night"),
    "cuirass": _it("زره سینه کوراسیه", "Cuirassier's Breastplate", "common", {"type": "boost", "stats": {"protect": 5}},
                   "محافظت +۵ برای یک شب", "Protect +5 for one night"),
    "topo_map": _it("نقشه توپوگرافی", "Topographic Survey", "uncommon", {"type": "boost", "stats": {"spy": 5}},
                    "جاسوسی +۵ برای یک شب", "Spy +5 for one night"),
    "sapper_kit": _it("جعبه ابزار مهندسی", "Engineer's Kit", "uncommon", {"type": "boost", "stats": {"defuse": 5}},
                      "خنثی +۵ برای یک شب", "Defuse +5 for one night"),
    "invisible_ink": _it("مرکب نامرئی", "Invisible Ink", "uncommon", {"type": "boost", "stats": {"stealth": 6}},
                         "مخفی‌کاری +۶ برای یک شب", "Stealth +6 for one night"),
    "grenade": _it("نارنجک دستی", "Hand Grenade", "uncommon", {"type": "boost", "stats": {"attack": 7}, "hp": -3},
                   "حمله +۷ برای یک شب، ولی ۳ اچ‌پی دائمی کم می‌شه", "Attack +7 for one night, −3 HP"),
    "tricolour": _it("پرچم سه‌رنگ", "Tricolour", "rare", {"type": "boost", "stats": {"all": 3}},
                     "همه قدرت‌ها +۳ برای یک شب", "All powers +3 for one night"),
    "guard_bearskin": _it("مدال گارد قدیم", "Old Guard Medal", "rare", {"type": "boost", "stats": {"attack": 5, "protect": 5}},
                          "حمله و محافظت +۵ برای یک شب", "Attack and protect +5 for one night"),
    # hp and coins
    "ration": _it("جیره نان سربازی", "Soldier's Ration", "common", {"type": "heal", "hp": 2},
                  "اچ‌پی +۲ (دائمی)", "+2 HP"),
    "surgeon_kit": _it("کیف جراحی لاری", "Larrey's Surgical Case", "uncommon", {"type": "heal", "hp": 8},
                       "اچ‌پی +۸ (دائمی)", "+8 HP"),
    "relic": _it("یادگار مقدس", "Holy Relic", "rare", {"type": "heal", "hp": 12},
                 "اچ‌پی +۱۲ (دائمی)", "+12 HP"),
    "silver": _it("کیسه سکه نقره", "Purse of Silver", "common", {"type": "coins", "n": 2}, "۲ سکه", "2 coins"),
    "spoils": _it("غنیمت جنگی", "Spoils of War", "uncommon", {"type": "coins", "n": 6}, "۶ سکه", "6 coins"),
    "treasury": _it("صندوق خزانه", "Army Pay Chest", "rare", {"type": "coins", "n": 10}, "۱۰ سکه", "10 coins"),
    # movement
    "courier": _it("اسب پیک", "Courier's Horse", "uncommon", {"type": "move_plus", "n": 2},
                   "+۲ به تاس حرکت بعدی", "+2 to your next movement roll"),
    "relay": _it("ایستگاه تعویض اسب", "Post Relay", "rare", {"type": "move_plus", "n": 3},
                 "+۳ به تاس حرکت بعدی", "+3 to your next movement roll"),
    "customs_seal": _it("مهر گمرک", "Customs Seal", "common", {"type": "toll_free"},
                        "عوارض بعدی رو نمی‌دی", "Skip the next toll"),
    "caltrops": _it("خارپای آهنی", "Caltrops", "common", {"type": "slow", "n": 2, "target": True},
                    "تاس حرکت بعدی یک نفر ۲ تا کم می‌شه", "Someone's next movement roll −2"),
    # darts
    "lucky_coin": _it("سکه شانس", "Lucky Sou", "common", {"type": "money_dart", "n": 3},
                      "+۳ سکه روی دارت پول بعدی", "+3 coins on your next money dart"),
    "clover": _it("شبدر چهاربرگ", "Four-leaf Clover", "rare", {"type": "item_dart", "n": 2},
                  "+۲ قدرت آیتم در دارت آیتم بعدی", "+2 item power on your next item dart"),
    "spare_dart": _it("دارت یدکی", "Spare Dart", "common", {"type": "extra_dart", "kind": "money"},
                      "یک دارت پول دیگه در همین فاز", "One more money dart this phase"),
    "feathered_dart": _it("دارت پَردار", "Feathered Dart", "uncommon", {"type": "extra_dart", "kind": "item"},
                          "یک دارت آیتم دیگه در همین فاز", "One more item dart this phase"),
    # votes
    "petition": _it("طومار مردمی", "Petition", "uncommon", {"type": "vote_plus", "n": 1},
                    "+۱ رأی در رأی‌گیری بعدی", "+1 vote in the next execution vote"),
    "senate_seal": _it("مهر سنا", "Seal of the Senate", "rare", {"type": "vote_plus", "n": 2},
                       "+۲ رأی در رأی‌گیری بعدی", "+2 votes in the next execution vote"),
    "false_witness": _it("شاهد دروغین", "False Witness", "uncommon", {"type": "vote_guard", "n": 1},
                         "امروز رأی‌های علیه تو ۱ تا کمتر حساب می‌شه", "Today, votes against you count 1 less"),
    "bribe": _it("رشوه به کلانتر", "Bribe for the Provost", "rare", {"type": "vote_guard", "n": 2},
                 "امروز رأی‌های علیه تو ۲ تا کمتر حساب می‌شه", "Today, votes against you count 2 less"),
    "gag": _it("دهان‌بند", "Gag", "rare", {"type": "mute", "target": True},
               "امروز رأی یک نفر صفر حساب می‌شه", "Today, someone's vote counts 0"),
    # night defence and revenge
    "vengeance": _it("سوگند انتقام", "Oath of Vengeance", "uncommon", {"type": "revenge", "pct": 80},
                     "امشب اگه با حمله بمیری، هر کی بهت حمله کرده ۸۰٪ حمله‌ی خودش رو می‌خوره",
                     "Tonight, if attacks kill you, each attacker takes 80% of their own attack"),
    "spiked_cuirass": _it("زره خاردار", "Spiked Cuirass", "uncommon", {"type": "reflect", "pct": 30},
                          "امشب هر کی بهت حمله کنه ۳۰٪ حمله‌ش به خودش برمی‌گرده", "Tonight attackers take 30% of their attack back"),
    "wooden_shield": _it("سپر چوبی", "Wooden Shield", "common", {"type": "armor", "n": 5},
                         "امشب حمله‌ها به تو ۵ تا ضعیف‌تر", "Tonight attacks on you are 5 weaker"),
    "gabion": _it("سنگر سبدی", "Gabion Wall", "uncommon", {"type": "armor", "n": 10},
                  "امشب حمله‌ها به تو ۱۰ تا ضعیف‌تر", "Tonight attacks on you are 10 weaker"),
    "iron_will": _it("اراده آهنین", "Iron Will", "rare", {"type": "last_stand"},
                     "امشب اگه حمله تو رو بکشه، با ۱ اچ‌پی زنده می‌مونی", "Tonight a deadly attack leaves you at 1 HP"),
    "venetian_mask": _it("نقاب ونیزی", "Venetian Mask", "uncommon", {"type": "spy_mask"},
                         "امشب هر کی ازت جاسوسی کنه سفید / یه نقش انسانی می‌بینه", "Tonight spying on you shows white / a human role"),
    "seal_ring": _it("انگشتر مهر", "Signet Ring", "uncommon", {"type": "defuse_immune"},
                     "امشب خنثی روی تو اثر نداره", "Tonight defuses on you don't work"),
    "black_coffee": _it("قهوه سیاه", "Black Coffee", "rare", {"type": "extra_act"},
                        "امشب یک اکت معمولی اضافه (دو اکت ویژه نه)", "Tonight one extra basic act"),
    # day protection, until used
    "silk_vest": _it("جلیقه ابریشمی", "Silk Waistcoat", "uncommon", {"type": "bullet_vest"},
                     "اولین تیر جنگی که بهت شلیک بشه اثر نمی‌کنه", "The next war bullet fired at you fails"),
    "wet_blanket": _it("پتوی خیس", "Wet Blanket", "uncommon", {"type": "bomb_safe"},
                       "از انفجار بمب بعدی جون سالم به در می‌بری", "You survive the next bomb blast"),
    "theriac": _it("تریاق", "Theriac", "uncommon", {"type": "poison_safe"},
                   "سم بعدی تو رو نمی‌کشه", "The next poison doesn't kill you"),
    "pardon": _it("فرمان عفو امپراتور", "Imperial Pardon", "rare", {"type": "pardon"},
                  "اعدام بعدی تو لغو می‌شه", "Your next execution is cancelled"),
    # aimed at someone
    "pickpocket": _it("انگشت جیب‌بر", "Pickpocket's Fingers", "uncommon", {"type": "pickpocket", "n": 5, "target": True},
                      "۵ سکه از یک نفر برمی‌داری", "Take 5 coins from someone"),
    "informant": _it("خبرچین", "Informant", "uncommon", {"type": "trace", "target": True},
                     "می‌فهمی یک نفر الان کجای نقشه است", "Learn where someone is right now"),
    "fouche_file": _it("پرونده پلیس فوشه", "Fouché's File", "rare", {"type": "reveal", "target": True},
                       "رنگ تیم یک نفر رو می‌فهمی (سفید/سیاه/خاکستری)", "Learn someone's team colour"),
    # units
    "balloon_kit": _it("کیت بالن", "Balloon Kit", "uncommon", {"type": "unit", "unit": "spy_balloon"},
                       "یک بالن جاسوسی می‌گیری", "Get a spy balloon"),
    "entrenching_tool": _it("بیل سنگرکنی", "Entrenching Tool", "common", {"type": "unit", "unit": "shovel"},
                            "یک بیل می‌گیری", "Get a shovel"),
    "field_gun": _it("توپ صحرایی", "Field Gun", "rare", {"type": "unit", "unit": "cannon"},
                     "یک توپ جنگی می‌گیری", "Get a cannon"),
})
