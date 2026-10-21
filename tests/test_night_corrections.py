from tests.test_engine import make, act, effects, FixedRng
from zombiebot.engine import resolve_night, night_stats
from zombiebot import legendary


def test_defused_attack_still_prevents_priest_lone_attacker_penalty():
    g = make([('zombie', 'n15'), ('yakuza', 'n17'), ('priest', 'n19'), ('saboteur', 'n21')])
    act(g, 1, 'attack', 3)
    act(g, 2, 'attack', 3)
    act(g, 4, 'defuse', 1)
    res = resolve_night(g, FixedRng())
    assert [(e['pid'], e['amount']) for e in effects(res, 'damage')] == [('3', 19)]
    assert not any('نصف شد (کاهن)' in fa for fa, _ in res['lines'])


def test_two_attacks_by_one_zombie_still_count_as_one_attacker():
    g = make([('zombie', 'n15'), ('priest', 'n17')])
    act(g, 1, 'attack', 2)
    act(g, 1, 'attack', 2)
    res = resolve_night(g, FixedRng())
    assert effects(res, 'damage')[0]['amount'] == 20


def test_attack_on_another_target_does_not_remove_priest_penalty():
    g = make([('zombie', 'n15'), ('yakuza', 'n17'), ('priest', 'n19'), ('doctor', 'n21')])
    act(g, 1, 'attack', 3)
    act(g, 2, 'attack', 4)
    res = resolve_night(g, FixedRng())
    assert next(e['amount'] for e in effects(res, 'damage') if e['pid'] == '3') == 10


def test_gm_dice_totals_are_used_without_inventing_individual_dice():
    g = make([('zombie_doctor', 'london'), ('zombie', 'n17'), ('sniper', 'n19'), ('godfather', 'n21')])
    act(g, 1, 'protect', 2)
    g['acts']['1'][0].update(gm_override=True, dice_total=8)
    act(g, 3, 'attack', 2)
    act(g, 4, 'attack', 3)
    g['acts']['4'][0].update(gm_override=True, dice_total=9)
    res = resolve_night(g, FixedRng())
    assert not [e for e in effects(res, 'damage') if e['pid'] == '2']
    assert next(e['amount'] for e in effects(res, 'damage') if e['pid'] == '3') == 24
    assert any('تاس جمع 8 (گاد)' in fa for fa, _ in res['lines'])
    assert any('تاس جمع 9 (گاد)' in fa for fa, _ in res['lines'])


def test_mail_hp_is_added_once_and_hotel_adjusts_protection_not_defuse_bonus():
    g = make([('bomber', 'barcelona')])
    p = g['players']['1']
    p['hp'] = 9  # already paid the hotel's lock cost
    legendary.give(g, p, 'charlemagne_mail')
    assert p['hp'] == 29
    stats, _ = night_stats(g, p)
    assert stats['protect'] == 11  # (2 + 20) // 2
    assert stats['defuse'] == 6    # 13 // 2; mail adds no defuse
    res = resolve_night(g, FixedRng())
    assert p['hp'] == 29
    assert any('زره شارلمانی' in fa and 'اچ‌پی +20' in fa and 'محافظت +20' in fa for fa, _ in res['lines'])
