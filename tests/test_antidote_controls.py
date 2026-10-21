import pytest
from tests.harness import World, run
from tests.test_bot_flow import setup, P
from zombiebot import actions, events, player_ui


async def day_world():
    w = World(seed=116)
    await setup(w, ['apothecary', 'doctor', 'spy'])
    w.g.update(phase='day', cycle=2, applied_cycle=2)
    P(w, 1)['charges']['poison'] = 0
    w.g['poisons'] = [{'id': 'p1', 'by': '1', 'target': 2, 'cycle': 2, 'status': 'pending'}]
    return w


def test_day_menu_and_old_night_button_reach_antidote_without_poison_charges():
    async def go():
        w = await day_world()
        await w.press(1, 'p:home')
        assert 'p:antidotes' in w.last_to(1).buttons()
        for button in ['p:antidotes', 'p:act']:
            await w.press(1, button)
            assert 'x:an:p1:1' in w.last_to(1).buttons()
            assert P(w, 1)['charges']['poison'] == 0
    run(go())


def test_both_antidote_choices_remain_reversible_until_next_night():
    async def go():
        w = await day_world()
        for yes in [False, True, False, True]:
            await w.press(1, f'x:an:p1:{int(yes)}')
            po = w.g['poisons'][0]
            assert po['antidote'] is yes
            assert po['status'] == ('cured' if yes else 'doomed')
            assert 'x:an:p1:0' in w.last_to(1).buttons()
            await w.press(1, 'p:antidotes')
            assert 'x:an:p1:1' in w.last_to(1).buttons()
        await events.resolve_poisons(w.bot)
        actions.start_phase(w.g, 'night')
        assert P(w, 2)['alive']
        with pytest.raises(actions.GameError):
            await events.antidote(w.bot, 1, 'p1', False)
    run(go())


def test_switching_back_to_no_takes_effect_at_next_night():
    async def go():
        w = await day_world()
        await events.antidote(w.bot, 1, 'p1', True)
        await events.antidote(w.bot, 1, 'p1', False)
        await events.resolve_poisons(w.bot)
        assert not P(w, 2)['alive']
        assert w.g['poisons'][0]['status'] == 'killed'
    run(go())


def test_other_players_dead_players_and_old_poisons_cannot_be_edited():
    async def go():
        w = await day_world()
        with pytest.raises(actions.GameError):
            await events.antidote(w.bot, 3, 'p1', True)
        po = w.g['poisons'][0]
        po.update(status='cured', antidote=True, cycle=1)
        assert not events.antidote_decisions(P(w, 1))
        with pytest.raises(actions.GameError):
            await events.antidote(w.bot, 1, 'p1', False)
        po.update(status='pending', cycle=2)
        for pid in [1, 2]:
            P(w, pid)['alive'] = False
            with pytest.raises(actions.GameError):
                await events.antidote(w.bot, 1, 'p1', True)
            P(w, pid)['alive'] = True
        assert po['status'] == 'pending'
    run(go())
