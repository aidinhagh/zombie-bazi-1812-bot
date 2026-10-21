from io import BytesIO
from types import SimpleNamespace
from tests.harness import World, run, GM
from tests.test_bot_flow import setup, next_step, place, P
from zombiebot import mapview, player_ui


def test_gm_playing_real_player_receives_delayed_and_repeat_movement_choices(monkeypatch):
    monkeypatch.setenv('WEBAPP_URL','https://example.com/map')
    async def go():
        w=World(seed=103);await setup(w,['zombie','doctor']);await next_step(w);P(w,1)['pos']='paris'
        p=P(w,1);assert not p.get('fake');w.g['as']={str(GM):'1'};w.sent.clear()
        await w.press(GM,'p:move')
        roll=p['move_roll'];assert roll and not p['moved']
        assert any(any(b.startswith('p:go:') for b in m.buttons()) for m in w.sent if m.chat_id==GM)
        assert not [m for m in w.sent if m.chat_id==1]
        count=sum(bool(m.dice) for m in w.sent)
        await w.press(GM,'p:move')
        assert p['move_roll']==roll and sum(bool(m.dice) for m in w.sent)==count
        assert any(b.startswith('p:go:') for b in w.last_to(GM).buttons())
    run(go())


def test_regular_player_still_receives_their_own_movement_choices(monkeypatch):
    monkeypatch.setenv('WEBAPP_URL','https://example.com/map')
    async def go():
        w=World(seed=104);await setup(w,['zombie','doctor']);await next_step(w);P(w,1)['pos']='paris';w.sent.clear()
        await w.press(1,'p:move')
        assert any(b.startswith('p:go:') for b in w.last_to(1).buttons())
        assert not [m for m in w.sent if m.chat_id==GM]
    run(go())


def test_first_placement_routes_to_gm_who_pressed_move(monkeypatch):
    monkeypatch.setenv('WEBAPP_URL','https://example.com/map')
    async def go():
        w=World(seed=105);await setup(w,['zombie','doctor']);await next_step(w);w.g['as']={str(GM):'1'};w.sent.clear()
        await w.press(GM,'p:move')
        assert 'p:go:paris' in w.last_to(GM).buttons()
        assert not [m for m in w.sent if m.chat_id==1]
    run(go())


def test_no_open_route_notice_goes_to_originating_chat(monkeypatch):
    monkeypatch.setattr(mapview.actions,'move_options',lambda *args:{})
    async def go():
        w=World(seed=106);await setup(w,['zombie','doctor']);await next_step(w);P(w,1)['pos']='paris';w.g['as']={str(GM):'1'};w.sent.clear()
        await w.press(GM,'p:move')
        assert 'هیچ مسیری' in w.last_to(GM, with_buttons=False).text
        assert not [m for m in w.sent if m.chat_id==1]
    run(go())


def test_photo_fallback_goes_to_originating_chat(monkeypatch):
    monkeypatch.delenv('WEBAPP_URL',raising=False)
    monkeypatch.setattr(mapview,'render',lambda *args,**kwargs:BytesIO(b'\x89PNGtest'))
    async def go():
        w=World(seed=107);await setup(w,['zombie','doctor']);await next_step(w);P(w,1)['pos']='paris';w.g['as']={str(GM):'1'};w.sent.clear()
        await w.press(GM,'p:move')
        assert any(m.photo and m.chat_id==GM for m in w.sent)
        assert any(b.startswith('p:go:') for b in w.last_to(GM).buttons())
        assert not [m for m in w.sent if m.chat_id==1]
    run(go())


def test_stale_delayed_job_does_not_send_choices_after_phase_change(monkeypatch):
    monkeypatch.setenv('WEBAPP_URL','https://example.com/map')
    async def go():
        w=World(seed=108);await setup(w,['zombie','doctor']);await next_step(w);P(w,1)['pos']='paris';w.sent.clear()
        data={'player_id':1,'chat_id':GM,'cycle':w.g['cycle'],'phase':'night'};w.g['phase']='day'
        await player_ui.job_after_roll(SimpleNamespace(bot=w.bot,job=SimpleNamespace(data=data)))
        assert not w.sent
    run(go())


