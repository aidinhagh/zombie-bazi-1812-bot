import datetime
import copy
import pytest
from tests.harness import World, run, GM
from tests.test_bot_flow import setup, place, next_step, P
from zombiebot import actions, board, gm_ui, common, legendary, player_ui
from zombiebot.night_window import before, expired
from zombiebot.state import new_game, new_player


def test_deadlines_expire_and_do_not_leak_to_next_night():
    g=new_game();g.update(phase='night',cycle=2,night_window={'cycle':2,'move_until':'2026-10-21T23:00:00+03:30','acts_until':'2026-10-22T01:00:00+03:30'})
    assert before(g,'move_until',datetime.datetime.fromisoformat('2026-10-21T22:59:59+03:30'))
    assert expired(g,'move_until',datetime.datetime.fromisoformat('2026-10-21T23:00:00+03:30'))
    assert before(g,'acts_until',datetime.datetime.fromisoformat('2026-10-22T00:59:59+03:30'))
    assert expired(g,'acts_until',datetime.datetime.fromisoformat('2026-10-22T01:00:00+03:30'))
    g['cycle']=3
    assert not expired(g,'acts_until',datetime.datetime.fromisoformat('2026-10-23T01:00:00+03:30'))


def test_preview_does_not_block_acts_and_change_invalidates_result():
    async def go():
        w=World(seed=100);await setup(w,['zombie','doctor']);await next_step(w)
        await place(w,1,'paris');await place(w,2,'berlin');await gm_ui.do_lock(w.bot)
        await w.press(GM,'g:resolve');assert w.g['pending']
        player_ui.add_act(P(w,1),{'type':'attack','target':2,'extra':{}})
        assert w.g['acts']['1'] and w.g['pending'] is None
        await w.press(GM,'g:resolve');assert w.g['pending']
        P(w,2)['hp']+=1;common.save();assert w.g['pending'] is None
    run(go())


def test_extended_night_cannot_be_locked_or_applied_early_and_blocks_late_acts():
    async def go():
        w=World(seed=101);await setup(w,['zombie','doctor']);await next_step(w)
        await place(w,1,'paris');await place(w,2,'berlin')
        w.g['night_window']={'cycle':w.g['cycle'],'move_until':'2099-01-01T23:00:00+03:30','acts_until':'2099-01-02T01:00:00+03:30'}
        await gm_ui.do_lock(w.bot);assert not w.g['locked']
        await w.press(GM,'g:resolve');assert w.g['pending']
        before_hp=P(w,2)['hp'];await w.press(GM,'g:apply');assert P(w,2)['hp']==before_hp and w.g.get('applied_cycle')!=w.g['cycle']
        w.g['night_window']['acts_until']='2000-01-01T01:00:00+03:30'
        with pytest.raises(actions.GameError):player_ui.add_act(P(w,1),{'type':'attack','target':2,'extra':{}})
    run(go())


def test_shovel_cannot_clear_mines_and_two_shovels_repair_two_roads():
    g=new_game();p=new_player(1,'one');p['units']={'shovel':2};g['players']['1']=p
    mine=next((rid,r) for rid,r in board.ROUTES.items() if r['kind']=='sea');p['pos']=mine[1]['from'];g['route_state'][mine[0]]='mined'
    with pytest.raises(actions.GameError):actions.strike_route(g,p,'shovel',mine[0])
    assert g['route_state'][mine[0]]=='mined' and p['units']['shovel']==2
    for rid,r in list((rid,r) for rid,r in board.ROUTES.items() if r['kind']=='road')[:2]:
        p['pos']=r['from'];g['route_state'][rid]='broken';actions.strike_route(g,p,'shovel',rid);assert g['route_state'][rid]=='ok'
    assert p['units']['shovel']==0


def test_cannon_lifetime_limit_survives_phase_reset():
    g=new_game();p=new_player(1,'one');p['units']={'cannon':1};g['players']['1']=p
    roads=list((rid,r) for rid,r in board.ROUTES.items() if r['kind']=='road')[:2]
    p['pos']=roads[0][1]['from'];actions.strike_route(g,p,'cannon',roads[0][0]);p['flags']={};p['pos']=roads[1][1]['from']
    with pytest.raises(actions.GameError):actions.strike_route(g,p,'cannon',roads[1][0])
    assert board.route_status(g,roads[1][0])=='ok'


def test_invalid_road_removed_without_clearing_original_mine():
    g=new_game();g['extra_routes']=[{'id':'x18','from':'n37','to':'copenhagen','kind':'road','nodes':[]}];g['route_state']['p50']='mined'
    with pytest.raises(actions.GameError):actions.dig_route(g,'n37','copenhagen')
    actions.drop_bad_dug_roads(g)
    assert not g['extra_routes'] and g['route_state']['p50']=='mined'


def test_relocking_extension_does_not_charge_hotel_or_pay_bank_twice():
    g=new_game();g.update(phase='night',cycle=2)
    for i,city in enumerate(['amsterdam','stpetersburg','paris'],1):
        p=new_player(i,str(i));p.update(pos=city,hp=50);g['players'][str(i)]=p
    actions.lock_map(g);snapshot=copy.deepcopy(g['players']);g['locked']=False;g['relock_positions_only']=True;actions.lock_map(g)
    assert g['players']==snapshot


def test_legendary_can_move_to_city_but_not_sea_square():
    g=new_game();legendary.spawn_next(g,where='paris');key=legendary.state(g)['active']['key']
    legendary.move_active(g,'moscow');assert legendary.state(g)['active']=={'key':key,'where':'moscow','cycle':0}
    with pytest.raises(actions.GameError):legendary.move_active(g,'n37')

def test_gm_has_secret_legendary_location_picker():
    async def go():
        w=World(seed=102);await setup(w,['zombie','doctor']);await next_step(w)
        if not legendary.state(w.g)['active']:legendary.spawn_next(w.g,where='paris')
        await w.press(GM,'g:home');assert 'g:legendmove' in w.last_to(GM).buttons()
        await w.press(GM,'g:legendmove');assert 'g:legendmove:moscow' in w.last_to(GM).buttons()
        await w.press(GM,'g:legendmove:moscow');assert legendary.state(w.g)['active']['where']=='moscow'
    run(go())


def test_applied_night_does_not_accept_more_acts():
    from zombiebot.night_window import check_actions
    g=new_game();g.update(phase='night',cycle=2,applied_cycle=2)
    with pytest.raises(actions.GameError):check_actions(g)
