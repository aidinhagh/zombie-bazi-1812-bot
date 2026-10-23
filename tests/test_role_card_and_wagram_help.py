from tests.test_engine import make
from tests.harness import World, run
from tests.test_bot_flow import setup, next_step, P
from zombiebot import actions, player_ui, gm_ui
from zombiebot.texts import role_card, stat_name
from zombiebot.data.roles import ROLES


def test_role_card_shows_purchased_totals_and_current_hp_without_temporary_bonuses():
    g = make([('doctor', 'constantinople')]); p = g['players']['1']
    p['coins'] = 1000
    actions.buy_power(g, p, 'attack', 3)
    actions.buy_power(g, p, 'hp', 2)
    p['bought'] = {'spy': 2}
    p['boost'] = {'attack': 100}
    text = role_card(p, 'fa')
    assert f"{stat_name('attack', 'fa')} {ROLES['doctor']['attack'] + 3}" in text
    assert f"{stat_name('spy', 'fa')} {ROLES['doctor']['spy'] + 2}" in text
    assert f"{stat_name('hp', 'fa')} {p['hp']}" in text
    assert 'حمله +3' in text and 'جاسوسی +2' in text
    assert '104' not in text


def test_wagram_arrival_home_and_lock_explain_when_and_how_to_roll():
    async def go():
        w = World(seed=120); await setup(w, ['zombie', 'doctor']); await next_step(w)
        await w.press(1, 'p:go:wagram')
        text = w.last_to(1).text
        for phrase in ['هنگام قفل نقشه', 'خودکار تاس نمی‌ریزد', 'زوج', 'فرد', 'تاس حرکت', 'فقط یک اکت ویژه']:
            assert phrase in text
        assert 'p:wroll' not in w.last_to(1).buttons()
        await w.press(1, 'p:home')
        assert 'بعد از قفل' in w.last_to(1).text
        w.sent.clear(); await gm_ui.do_lock(w.bot)
        notices = [m for m in w.sent if m.chat_id == 1 and 'p:wroll' in m.buttons()]
        assert notices and any('خودکار تاس نمی‌ریزد' in m.text for m in notices)
    run(go())


def test_taxi_arrival_in_wagram_explains_the_second_act_die():
    async def go():
        w = World(seed=121); await setup(w, ['zombie', 'doctor']); await next_step(w)
        p = P(w, 1); p['pos'] = p['night_pos'] = 'london'; w.g['locked'] = True
        await w.press(1, 'p:tx:wagram')
        assert 'تاس خانقاه' in w.last_to(1).text
    run(go())
