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

5. Add the bot to the game group **as admin** (admins see every message, which `#رای` needs). Adding it registers the group automatically; `/setgroup` inside the group does the same. Optionally `/setchannel -100…` for a separate map channel.

Run locally: `pip install -r requirements.txt && BOT_TOKEN=… GM_IDS=… python -m zombiebot.bot`

## Running a round — the control room

Send `/gm` (or `/start`, `/menu`). One message shows the phase, time to the 20:00 lock and who has moved/acted/voted, plus **➡️ Next step**, which always does the next thing in order:

start night → lock the map → resolve → review & apply → start day → close the vote & execute → next night

Screens, each with a way back: **👥 Players** (tap anyone: role, ❤️/💰 ±5, move, give item, cult, kill/revive, play as them, clear their act or vote) · **🗺 Map** (picture + list of who is where) · **🌙 Acts** · **🗳 Votes** (tally, who hasn't voted, execute, remove votes) · **🎈 Balloons & battles** (minigame results) · **🧪 Test lab** · **⚙️ Setup** (force day/night, undo, new game, language).

On **review & apply** each proposed effect has a number: tap it to switch it off, **🎲 Re-roll** to roll again, **🔍** for every act's dice. Nothing happens until **✔️ Apply**. Post your story with `/story <text>`.

## Players

`/start` registers; after you give a role they get their card and menu. The home screen is a checklist for the phase (move ✅ · darts 1/2 · act ⬜) with buttons for move, darts, act or vote, shop, bag (items + units), map, role. Place buttons (taxi, slots, shoot, casino bet, clown/godfather settings) appear only when they apply.

Maps always come as a **picture and a list**. Moving shows every reachable square with a number on the map and the same numbers on the buttons.

## Voting (from the ZombieVote bot)

- In the group: `#رای name` — Persian, English, @username, a nickname you set with `/nick <who> <nickname>`, or as a reply to the person. The bot answers with the sand-and-blood GIF (their avatar behind it).
- One vote per player per day; the first counts. A vote for someone the hotel protects is struck by ⚡ lightning and doesn't count (and doesn't use up the vote).
- Paris (+1) and St Petersburg (−1) vote weights and the Légion d'honneur item apply.
- `#رایگیری` posts the tally. `/delete <name>`, `/delete all`, or reply + `/delete` (GM, in the group) removes votes; the Votes screen does it with buttons.
- Players can also vote from their menu; it's announced in the group the same way.

## Test lab — a fast game with 24 named test players

**🧪 Test lab → Build test game**: 24 players with names (مریم, علی, سارا, رضا, …) and English usernames, covering every role, placed in random cities. Night 1 starts at once.

- Fast mode: test players move, throw darts and act the moment a night starts, and vote in the group (`name: #رای …` with the GIF, ~3.5 s apart) the moment a day starts; then the tally is posted. Nothing waits for 20:00.
- **🕹 Play as…** turns you into one of them; their menu and messages come to you with a 🕹 banner. **👑 Back to GM** returns.
- **⏩ Auto-run to the next night** (in the control room) locks, resolves, applies, starts the day, lets everyone vote, executes the leader and starts the next night.
- **🗑 Remove test players** when you're done.

Telegram doesn't let a bot post *as* another account, so test players' votes come from the bot, labelled with their name.

Automated tests (33, including whole fast games and a fuzzer): `pip install pytest && python -m pytest tests`

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

- `zombiebot/data/` — role stats, places, **items (`items.py` — edit freely)**, map (`map.json`, from your campaign map).
- `engine.py` night resolution · `actions.py` everything else that changes the game · `votes.py` #رای voting · `matching.py` + `animator.py` from the ZombieVote bot.
- `gm_ui.py` control room and test lab · `player_ui.py` player menu · `mapview.py` + `render.py` maps · `events.py` bombs, poison, duels, executions · `bot.py` wiring.
- `webapp/map.html` — the map Mini App, built from your campaign map with `python tools/build_map_webapp.py` (fallback: `/map2d`).
- `tests/` — engine tests and an offline Telegram harness that plays whole games.
