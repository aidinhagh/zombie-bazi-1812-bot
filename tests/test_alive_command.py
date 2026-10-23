from tests.harness import World, run, GROUP
from tests.test_bot_flow import setup, P
from zombiebot.state import new_player


def test_alive_works_for_player_in_group_and_reveals_only_living_names():
    async def go():
        w = World(seed=123); await setup(w, ['doctor', 'zombie', 'spy'])
        P(w, 1).update(name='Living Alpha', char='SECRET_CHARACTER', fake_char='SECRET_FAKE')
        P(w, 2).update(name='Living Beta', char='SECRET_CHARACTER_TWO')
        P(w, 3).update(name='Dead Gamma', alive=False)
        w.g['players']['4'] = new_player(4, 'Unassigned Delta')
        w.sent.clear()
        await w.cmd(1, 'alive', chat_type='supergroup', chat_id=GROUP)
        text = '\n'.join(w.texts_to(GROUP))
        assert 'Living Alpha' in text and 'Living Beta' in text
        assert all(secret not in text for secret in ['SECRET_', 'Dead Gamma', 'Unassigned Delta', 'doctor', 'zombie', 'spy', 'دکتر', 'زامبی', 'جاسوس'])
        assert '۲ نفر' in text
    run(go())


def test_alive_does_not_publish_the_game_roster_in_another_group():
    async def go():
        w = World(seed=124); await setup(w, ['doctor', 'zombie'])
        w.sent.clear()
        await w.cmd(1, 'alive', chat_type='group', chat_id=GROUP - 1)
        assert not w.sent
    run(go())
