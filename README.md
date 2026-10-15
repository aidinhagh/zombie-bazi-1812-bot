# Zombie Bazi 1812 — GM bot

A Telegram bot that runs the Napoleonic London round of Zombie Bazi: movement on the campaign map, darts, slots, shops, items, units, balloons, night acts, voting and every role's special rule. The bot does the arithmetic and proposes what happened each night; **you approve, switch off, or override every effect before anything is applied.** You still write the story.

## Deploy on Railway

1. Create a new bot with @BotFather and copy the token.
2. Push this folder to a new GitHub repo and create a Railway project from it.
3. Add a **Volume** mounted at `/data`.
4. Variables:

| Variable | Value |
|---|---|
| `BOT_TOKEN` | token from BotFather |
| `GM_IDS` | your Telegram user id (several: comma-separated). Send `/whoami` to the bot to see it |
| `DATA_DIR` | `/data` (game state survives restarts and redeploys) |
| `LOCK_HOUR` | `20` (map lock hour, Tehran time) |
| `VOTES_PUBLIC` | `1` to post each vote in the group, `0` to keep votes secret until you tally |

5. Add the bot to the game group as admin and send `/setgroup` **inside the group**. Optionally add it as admin of the map channel and send `/setchannel -100…` to the bot in private (without a channel, maps go to the group).

Run locally: `pip install -r requirements.txt && BOT_TOKEN=… GM_IDS=… python -m zombiebot.bot`

## Running a round

1. Players send `/start` to the bot in private. You see them in `/players`.
2. `/assign <who> <role> [fake_role]` for each (role keys: `/roles`). `<who>` = roster number, @username or name. Each player gets their role card and the menu.
3. `/gm` opens your panel:
   - **🌙 Night** — players move (first move: any city; then 🎲 up to N squares), throw both 🎯 darts, buy powers, use items, place units, launch balloons, submit acts.
   - **🔒 Lock** happens automatically at 20:00 Tehran (or press it). The public map (units, broken routes, damage) is posted; hotel, bank, monastery effects apply; spy balloons report; war balloons and battles wait for your minigame result under **🎈 Balloons & battles**.
   - **🧮 Resolve** shows every act with dice and power, then the list of proposed effects. Tap a number to switch an effect off, **🎲 Re-roll** to roll the dice again, **✔️ Apply** to commit. Spy results, bombs, poison, bullets and duels go out on apply.
   - `/story <text>` posts your story to the group and channel.
   - **☀️ Day** — votes come in from the player menu. **🗳 Tally** → execute.
   - **↩️ Undo** restores the state from before the last apply, execution or phase change.
4. You get a 00:00 reminder of what's next.

Any number can be fixed by hand: `/hp`, `/coins`, `/pos`, `/give`, `/unit`, `/charge`, `/kill`, `/revive`, `/cult`, `/route`, `/dig`, `/damage`, `/actadd`, `/actclear`. Full list: `/help`.

## Testing it yourself before the round

You don't need 24 friends to try it. With only your GM account:

1. `/fake 24` creates 24 test players with a full role spread (`/fake clear` removes them).
2. `/as Test05` — you now *are* Test05: `/menu` shows their menu and their private messages come to you, marked `[→ Test05]`. Use this to try every role's buttons. `/as off` returns to GM.
3. `/autoplay` makes every test player move, throw darts, and pick a random act (night) or vote (day).
4. Then lock, resolve, apply, day, tally, execute — and repeat.

Suggested checks: one test per role's special act; a bomb in the group (the GM can cut the wire while playing as the target); poison then antidote; a judge duel; musketeer bullets then `/shoot` by day; a London taxi; slots in Vienna and Berlin; a war balloon raid; two ships on one square; a casino `/bet`; tolls from a placed cannon.

Automated tests (28, including a fuzzer that presses random buttons through four full cycles of a 24-player game): `pip install pytest && python -m pytest tests`

## How the rules were read

These were my interpretations where the rules left room; each one is easy to change.

- **Phases**: one move and two darts (money + item) per phase, day or night. Night location = where you are at the 20:00 lock; you can't spend two nights in a row in the same place (the bot hides that destination).
- **Acts**: power = 2d6 + stat. Special acts use 2d6 + stealth. Order: thief → defuse → godfather → protect → attacks → spy → cult → poison/bomb/bullets/duel.
- **Defuse** cancels an act only if it's ≥ the act's power; otherwise it weakens it. A defuse aimed at a defuser weakens that defuse first.
- **Protect** works as a shield on top of HP. Attacks on one target add up.
- **Locations**: modifiers last only for the night; “all powers” = attack, protect, defuse, spy, stealth. Birmingham/Amsterdam/bank HP changes are temporary. The hotel loss is permanent and applied at lock.
- **Vienna slots**: not playing means no effect; three pulls with no triple means −20.
- **War balloon**: destruction % cuts the place's positive bonuses permanently; it stacks to 100%. Church/hotel protection is multiplied by the destroyed %. People there lose 10 × % HP.
- **Tolls**: 10 coins; any shortfall is taken as HP at the shop rate (5 coins = 1 HP).
- **Units**: cannons and ships are placed on your own blank square. Cannon/mine/shovel act on routes touching your square. A cannon or mine is used up when fired, a shovel when used; a ship can clear mines repeatedly. New shovel roads need your approval.
- **Balloons** are single-use and resolve at the lock. The spy's starting balloon is always published, the zombie doctor's never; bought ones ask the owner.
- **Spy results**: the Spy role sees the exact role (the godfather shows his fake role; the clown shows what he picked). Everyone else sees a colour.
- **Thief**: the target's act is cancelled, they lose a random item to the thief, and the thief is told the role. What the thief does with a stolen role (e.g. becoming cult) is up to you.
- **Bomb**: wrong wire kills the target and 80% chance each for anyone on the same square (except the cultist). The bomber only loses the bomb when it's defused.
- **Poison**: the apothecary decides by the start of the next night; no answer = death. Poison fails if the apothecary dies first.
- **Musketeer**: bullets are handed out; holders don't know the type and `/shoot` by day. A war bullet kills outright.
- **Judge**: the tie-break message tells you the judge decides; you then execute by hand.
- **Wins**: an executed clown is announced in the group at once. Everything else — clown in the final 4, thief and cult in the final 3, team wins — is checked after every death and sent to you, not announced.

## Files

- `zombiebot/data/` — role stats, places, **items (`items.py` — edit freely)**, map (`map.json`, extracted from your campaign map).
- `zombiebot/engine.py` — night resolution. `actions.py` — everything else that changes the game. `bot.py` — Telegram menus and commands. `render.py` — map image.
- `tests/` — engine tests and the offline Telegram harness.
