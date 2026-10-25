import copy
import pytest
from tests.test_engine import make
from tests.harness import World, run
from tests.test_bot_flow import setup, next_step, P
from zombiebot import actions


def test_rejected_launch_does_not_move_cooldown():
    g = make([('bomber', 'paris')]); p = g['players']['1']
    g['cycle'] = 3; p['war_cycle'] = 1
    g['balloons'] = [{'id': 'old', 'owner': 1, 'kind': 'war', 'cycle': 3, 'phase': 'night', 'name': 'old'}]
    before = copy.deepcopy(g)
    with pytest.raises(actions.GameError):
        actions.launch_balloon(g, p, 'war', 'milan')
    assert g == before


def test_war_balloon_rests_one_full_night_and_reports_exact_next_night():
    g = make([('bomber', 'paris')]); p = g['players']['1']
    b = actions.launch_balloon(g, p, 'war', 'milan')
    b.update(result='done', pct=50)
    for cycle in [1, 2]:
        g['cycle'] = cycle
        with pytest.raises(actions.GameError) as error:
            actions.launch_balloon(g, p, 'war', 'berlin')
        assert 'شب 3' in error.value.text('fa')
        assert p['war_cycle'] == 1
    g['cycle'] = 3
    assert actions.launch_balloon(g, p, 'war', 'berlin')['cycle'] == 3


def test_launch_button_and_stale_target_button_resume_previous_unfinished_flight(monkeypatch):
    monkeypatch.setenv('WEBAPP_URL', 'https://example.test/map')
    async def go():
        w = World(seed=125); await setup(w, ['bomber', 'doctor']); await next_step(w)
        w.g.update(cycle=3, locked=True)
        b = actions.launch_balloon(w.g, P(w, 1), 'war', 'wagram')
        w.g['cycle'] = 4
        before = copy.deepcopy(w.g['balloons'])
        for button in ['p:ub:war', 'p:ubt:war:milan']:
            await w.press(1, button)
            msg = w.last_to(1)
            assert 'واگرام' in msg.text and 'شب ۳' in msg.text
            assert any(b['id'] in cb for cb in msg.buttons())
            assert w.g['balloons'] == before and P(w, 1)['war_cycle'] == 3
    run(go())


def test_scheduled_flight_before_lock_is_not_relaunched():
    async def go():
        w = World(seed=126); await setup(w, ['bomber', 'doctor']); await next_step(w)
        b = actions.launch_balloon(w.g, P(w, 1), 'war', 'wagram')
        assert b['result'] is None
        await w.press(1, 'p:ub:war')
        assert 'بعد از قفل' in w.last_to(1).text
        assert len(w.g['balloons']) == 1
    run(go())
