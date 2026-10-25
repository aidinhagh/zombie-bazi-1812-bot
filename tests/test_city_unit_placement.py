import pytest
from tests.test_engine import make
from tests.harness import World, run
from tests.test_bot_flow import setup, P
from zombiebot import actions, board


def neighbors(g, city, sea):
    return [sq for sq, _ in board.adjacency(g, include_blocked=True).get(city, [])
            if board.SQUARES[sq]['kind'] == 'node' and board.SQUARES[sq]['sea'] == sea]


def city_with(g, *, land=1, sea=0):
    return next(c for c in board.CITIES if len(neighbors(g, c, False)) >= land
                and len(neighbors(g, c, True)) >= sea)


def test_all_cannons_can_be_placed_around_city_without_crossing_the_nodes():
    g = make([('doctor', None)])
    city = city_with(g, land=2)
    p = g['players']['1']; p['pos'] = city
    spots = neighbors(g, city, False)
    p['units']['cannon'] = len(spots)
    assert set(actions.place_spots(g, p, 'cannon')) == set(spots)
    for sq in spots:
        actions.place_unit(g, p, 'cannon', sq)
    assert p['units']['cannon'] == 0
    assert len(g['units_on_map']) == len(spots)
    assert p['pos'] == city and not p['flags'].get('passed')


def test_ships_use_adjacent_sea_nodes_and_remote_or_wrong_terrain_is_rejected():
    g = make([('doctor', None)])
    city = city_with(g, sea=1)
    p = g['players']['1']; p['pos'] = city
    p['units'].update(ship=2, cannon=2)
    land, sea = neighbors(g, city, False), neighbors(g, city, True)
    assert set(actions.place_spots(g, p, 'ship')) == set(sea)
    actions.place_unit(g, p, 'ship', sea[0])
    for unit, sq in [('cannon', sea[0]), ('ship', land[0])]:
        with pytest.raises(actions.GameError):
            actions.place_unit(g, p, unit, sq)
    remote = next(sq for sq, data in board.SQUARES.items()
                  if data['kind'] == 'node' and not data['sea'] and sq not in land)
    with pytest.raises(actions.GameError):
        actions.place_unit(g, p, 'cannon', remote)
    p['flags']['passed'] = [remote]
    actions.place_unit(g, p, 'cannon', remote)


def test_map_lock_and_inventory_still_apply():
    g = make([('doctor', None)])
    p = g['players']['1']; p['pos'] = city_with(g)
    sq = neighbors(g, p['pos'], False)[0]
    with pytest.raises(actions.GameError):
        actions.place_unit(g, p, 'cannon', sq)
    p['units']['cannon'] = 1; g['locked'] = True
    with pytest.raises(actions.GameError):
        actions.place_unit(g, p, 'cannon', sq)
    assert p['units']['cannon'] == 1 and not g['units_on_map']


def test_city_placement_menu_and_callback_accept_every_adjacent_land_node():
    async def go():
        w = World(seed=117); await setup(w, ['doctor', 'spy'])
        w.g.update(phase='day', cycle=1, locked=False)
        p = P(w, 1); p['pos'] = city_with(w.g, land=2)
        spots = neighbors(w.g, p['pos'], False)
        p['units']['cannon'] = len(spots)
        await w.press(1, 'p:up:cannon')
        buttons = w.last_to(1).buttons()
        assert all(f'p:up:cannon:{sq}' in buttons for sq in spots)
        for sq in spots:
            await w.press(1, f'p:up:cannon:{sq}')
        assert {u['square'] for u in w.g['units_on_map']} == set(spots)
        assert p['units']['cannon'] == 0
    run(go())
