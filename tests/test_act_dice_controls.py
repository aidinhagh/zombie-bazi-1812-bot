from tests.harness import World,run,GM
from tests.test_bot_flow import setup,next_step,P
from zombiebot import actions,gm_ui,player_ui


def test_action_dice_stay_on_home_and_reopened_act_menu():
    async def go():
        w=World(seed=110);await setup(w,['zombie','doctor']);await next_step(w)
        p=P(w,1);p['pos']='paris';player_ui.add_act(p,{'type':'attack','target':2,'extra':{}})
        for button in ['p:home','p:act','p:home','p:act']:
            await w.press(1,button);assert 'p:dice:0' in w.last_to(1).buttons()
        await w.press(1,'p:dice:0');dice=list(w.g['acts']['1'][0]['dice']);assert len(dice)==2
        await w.press(1,'p:home');assert 'p:dice:0' not in w.last_to(1).buttons()
        await w.press(1,'p:act');assert 'p:dice:0' not in w.last_to(1).buttons()
        await w.press(1,'p:dice:0');assert w.g['acts']['1'][0]['dice']==dice
    run(go())


def test_wagram_control_on_lock_notice_home_and_acts_then_second_act():
    async def go():
        w=World(seed=111);await setup(w,['zombie','doctor']);await next_step(w)
        p=P(w,1);p['pos']='wagram';await gm_ui.do_lock(w.bot)
        assert any(m.chat_id==1 and 'p:wroll' in m.buttons() for m in w.sent)
        for button in ['p:home','p:act']:
            await w.press(1,button);assert 'p:wroll' in w.last_to(1).buttons()
        w.forced_dice=[4];await w.press(1,'p:wroll');assert p['double_act'] and p['flags']['wagram_roll']==4
        player_ui.add_act(p,{'type':'attack','target':2,'extra':{}});player_ui.add_act(p,{'type':'protect','target':1,'extra':{}})
        assert len(w.g['acts']['1'])==2
        await w.press(1,'p:home');assert 'p:wroll' not in w.last_to(1).buttons()
        count=sum(bool(m.dice) for m in w.sent);await w.press(1,'p:wroll');assert sum(bool(m.dice) for m in w.sent)==count
    run(go())


def test_wagram_is_not_available_before_lock():
    async def go():
        w=World(seed=112);await setup(w,['zombie','doctor']);await next_step(w);P(w,1)['pos']='wagram'
        assert not any(b[1]=='p:wroll' for row in player_ui.dice_rows(P(w,1)) for b in row)
        count=sum(bool(m.dice) for m in w.sent);await w.press(1,'p:wroll');assert sum(bool(m.dice) for m in w.sent)==count
    run(go())


def test_relock_notice_restores_missing_wagram_control_without_resetting_roll():
    async def go():
        w=World(seed=113);await setup(w,['zombie','doctor']);await next_step(w)
        P(w,1)['pos']='wagram';await gm_ui.do_lock(w.bot)
        w.g['locked']=False;w.g['relock_positions_only']=True;w.g['relock_settled_positions']={'1':'wagram'};w.sent.clear()
        await gm_ui.do_lock(w.bot)
        assert any(m.chat_id==1 and 'p:wroll' in m.buttons() for m in w.sent)
    run(go())


def test_gm_gets_action_dice_result_in_originating_chat():
    async def go():
        w=World(seed=114);await setup(w,['zombie','doctor']);await next_step(w);P(w,1)['pos']='paris'
        player_ui.add_act(P(w,1),{'type':'attack','target':2,'extra':{}});w.g['as']={str(GM):'1'};w.sent.clear()
        await w.press(GM,'p:dice:0')
        assert any('ثبت شد' in m.text and m.chat_id==GM for m in w.sent)
        assert not [m for m in w.sent if m.chat_id==1]
    run(go())


def test_slot_results_use_supplied_chat_for_miss_and_berlin_hit():
    async def go():
        w=World(seed=115);await setup(w,['zombie','doctor']);await next_step(w)
        p=P(w,1);p['pos']=p['night_pos']='vienna';w.g['locked']=True;w.g['as']={str(GM):'1'}
        w.forced_dice=[2];w.sent.clear()
        await player_ui.pull_slot(w.bot,w.ctx(GM),p,GM);await w.flush_jobs()
        assert any(m.chat_id==GM and 'بار دیگه' in m.text for m in w.sent)
        assert not [m for m in w.sent if m.chat_id==1]
        p['pos']=p['night_pos']='berlin';p['slots']=None;P(w,2)['alive']=False;w.forced_dice=[1];w.sent.clear()
        await player_ui.pull_slot(w.bot,w.ctx(GM),p,GM);await w.flush_jobs()
        assert any(m.chat_id==GM and 'p:rv:2' in m.buttons() for m in w.sent)
        assert not [m for m in w.sent if m.chat_id==1]
    run(go())
