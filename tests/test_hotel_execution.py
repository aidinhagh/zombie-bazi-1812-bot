from tests.harness import World, run, GM, GROUP
from tests.test_bot_flow import setup, P
from zombiebot import actions, events


def test_hotel_votes_count_and_protection_is_revealed_only_at_execution():
    async def go():
        w = World(seed=118); await setup(w, ['doctor', 'zombie'])
        w.g.update(phase='day', cycle=2)
        P(w, 2)['flags']['hotel_immune'] = True
        hp = P(w, 2)['hp']
        w.sent.clear()
        await w.say(1, '#رای علی')
        assert w.g['votes'] == {'1': '2'}
        assert actions.tally(w.g)[0] == [('2', 1)]
        assert not any('هتل' in t or 'صاعقه' in t for t in w.texts_to(GROUP))
        await events.close_vote(w.bot)
        texts = w.texts_to(GROUP)
        assert any('نتیجه نهایی' in t for t in texts)
        assert any('در هتل بود' in t and 'زنده ماند' in t for t in texts)
        assert P(w, 2)['alive'] and P(w, 2)['hp'] == hp
        assert w.g['closed_cycle'] == 2
    run(go())


def test_judge_still_decides_before_hotel_survival_is_revealed():
    async def go():
        w = World(seed=119); await setup(w, ['doctor', 'zombie', 'judge'])
        w.g.update(phase='day', cycle=2)
        P(w, 2)['flags']['hotel_immune'] = True
        await w.say(1, '#رای علی')
        await events.close_vote(w.bot)
        assert w.g['judgement']['cands'] == ['2']
        assert w.g['judgement']['status'] == 'waiting'
        assert not any('در هتل بود' in t for t in w.texts_to(GROUP))
        await w.press(3, 'x:jd:ok')
        assert P(w, 2)['alive'] and w.g['closed_cycle'] == 2
        assert any('در هتل بود' in t for t in w.texts_to(GROUP))
    run(go())
