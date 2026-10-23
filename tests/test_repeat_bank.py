from tests.test_engine import make
from tests.harness import World, run
from tests.test_bot_flow import setup, next_step, P
from zombiebot import actions
from zombiebot.engine import night_stats


def test_consecutive_bank_visit_has_neither_coins_nor_hp_penalty():
    g = make([('priest', 'copenhagen')]); p = g['players']['1']
    p['last_night_pos'] = 'copenhagen'
    coins, hp = p['coins'], p['hp']
    summary = actions.lock_map(g)
    assert p['coins'] == coins and p['hp'] == hp
    assert night_stats(g, p)[1] == 0
    assert any('نه سکه بانک' in fa for pid, fa, en in summary['private'] if pid == 1)


def test_bank_after_a_different_night_retains_both_effects():
    g = make([('priest', 'copenhagen')]); p = g['players']['1']
    p['last_night_pos'] = 'paris'
    coins, hp = p['coins'], p['hp']
    actions.lock_map(g)
    assert p['coins'] == coins + 10 and p['hp'] == hp
    assert night_stats(g, p)[1] == -(hp // 2)


def test_ship_in_moscow_explains_location_but_works_on_connected_mined_sea():
    async def go():
        w = World(seed=122); await setup(w, ['bomber', 'doctor']); await next_step(w)
        p = P(w, 1); p['units']['ship'] = 1; p['pos'] = 'moscow'
        w.g['route_state']['p50'] = 'mined'
        p['flags']['passed'] = ['london']
        ans = await w.press(1, 'p:us:ship')
        assert any('مسکو' in text and 'مکان فعلی' in text for text in ans)
        assert w.g['route_state']['p50'] == 'mined' and p['units']['ship'] == 1
        p['pos'] = 'london'
        await w.press(1, 'p:us:ship')
        assert 'p:ur:ship:p50' in w.last_to(1).buttons()
        await w.press(1, 'p:ur:ship:p50')
        assert w.g['route_state']['p50'] == 'ok' and p['units']['ship'] == 1
    run(go())
