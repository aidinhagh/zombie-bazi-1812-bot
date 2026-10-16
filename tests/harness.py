"""Offline stand-in for Telegram: records what the bot sends and lets tests press buttons or post in the group."""
import asyncio
import datetime
import os
import random
import tempfile
from types import SimpleNamespace

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp())

from zombiebot import bot as B, common, votes   # noqa: E402
from zombiebot.state import new_game            # noqa: E402

GM = 1000
GROUP = -500
_REAL_GIF = votes.make_gif


class Msg:
    _n = 0

    def __init__(self, world, chat_id, text, markup=None, dice=None, photo=False, animation=False,
                 from_user=None, reply_to=None, entities=None):
        Msg._n += 1
        self.message_id = Msg._n
        self.world, self.chat_id, self.text, self.markup = world, chat_id, text, markup
        self.caption = None
        self.dice = SimpleNamespace(value=dice) if dice else None
        self.photo, self.animation = photo, animation
        self.from_user = from_user
        self.reply_to_message = reply_to
        self.entities = entities or []
        self.date = datetime.datetime.now(datetime.timezone.utc)
        self.edit_date = None
        self.forward_origin = None
        self.chat = SimpleNamespace(id=chat_id, type="private" if chat_id > 0 else "supergroup")

    def buttons(self):
        if not self.markup:
            return []
        return [b.callback_data or ("webapp:" + b.web_app.url) for row in self.markup.inline_keyboard for b in row]

    async def reply_text(self, text, reply_markup=None, **kw):
        return await self.world.bot.send_message(self.chat_id, text, reply_markup=reply_markup)

    async def reply_photo(self, photo, caption=None, **kw):
        return await self.world.bot.send_photo(self.chat_id, photo, caption=caption)

    async def edit_reply_markup(self, markup=None):
        self.markup = markup


class FakeBot:
    def __init__(self, world, rng):
        self.world, self.rng = world, rng

    def _check_markup(self, reply_markup):
        if reply_markup:
            for row in reply_markup.inline_keyboard:
                for b in row:
                    assert b.text, "button without text"
                    if b.web_app:
                        assert b.web_app.url.startswith("https://")
                        continue
                    assert len(b.callback_data.encode()) <= 64, f"callback_data too long: {b.callback_data}"

    async def send_message(self, chat_id, text, reply_markup=None, **kw):
        assert isinstance(text, str) and text.strip(), "empty message"
        assert len(text) <= 4096, f"message too long ({len(text)})"
        assert chat_id is not None
        self._check_markup(reply_markup)
        m = Msg(self.world, chat_id, text, reply_markup)
        self.world.sent.append(m)
        return m

    async def send_dice(self, chat_id, emoji="🎲", **kw):
        top = 64 if emoji == "🎰" else 6
        v = self.world.forced_dice.pop(0) if self.world.forced_dice else self.rng.randint(1, top)
        m = Msg(self.world, chat_id, emoji, dice=v)
        self.world.sent.append(m)
        return m

    async def send_photo(self, chat_id, photo, caption=None, **kw):
        data = photo.read() if hasattr(photo, "read") else photo
        assert data[:4] == b"\x89PNG"
        if caption:
            assert len(caption) <= 1024, "caption too long"
        m = Msg(self.world, chat_id, caption or "[photo]", photo=True)
        self.world.sent.append(m)
        return m

    async def send_animation(self, chat_id, animation=None, caption=None, **kw):
        data = animation.read() if hasattr(animation, "read") else animation
        assert data[:3] == b"GIF"
        assert caption and len(caption) <= 1024, "caption too long"
        m = Msg(self.world, chat_id, caption, animation=True)
        self.world.sent.append(m)
        return m

    async def get_user_profile_photos(self, user_id, limit=1):
        return SimpleNamespace(total_count=0, photos=[])


class FakeJobQueue:
    def __init__(self, world):
        self.world = world

    def run_once(self, cb, when, data=None, **kw):
        if when > 600:   # long timers (the judge's 2 hours) don't fire by themselves in tests
            self.world.deferred.append((cb, data))
            self.world.scheduled.append((getattr(cb, "__name__", ""), when))
            return
        self.world.jobs.append((cb, data))
        self.world.scheduled.append((getattr(cb, "__name__", ""), when))

    def run_daily(self, *a, **kw):
        pass


class World:
    def __init__(self, seed=1, real_gifs=False):
        self.rng = random.Random(seed)
        random.seed(seed)
        common.store.path = os.path.join(tempfile.mkdtemp(), "state.json")
        common.store.g = new_game()
        common.ENV_GMS.clear()
        common.ENV_GMS.add(GM)
        votes.make_gif = _REAL_GIF if real_gifs else (lambda *a, **k: b"GIF89a-test")
        votes._seen.clear()
        votes._last_tally.clear()
        self.sent, self.jobs, self.forced_dice, self.scheduled, self.deferred = [], [], [], [], []
        self.bot = FakeBot(self, self.rng)
        self.jq = FakeJobQueue(self)
        self.user_data = {}

    @property
    def g(self):
        return common.store.g

    def ctx(self, uid, args=None):
        return SimpleNamespace(bot=self.bot, job_queue=self.jq, args=args or [],
                               user_data=self.user_data.setdefault(uid, {}), job=None)

    async def flush_jobs(self):
        while self.jobs:
            cb, data = self.jobs.pop(0)
            c = self.ctx(0)
            c.job = SimpleNamespace(data=data)
            await cb(c)

    def user(self, uid, name=None, username=None):
        return SimpleNamespace(id=uid, full_name=name or f"User{uid}", first_name=name or f"User{uid}",
                               username=username or f"u{uid}", is_bot=False)

    async def cmd(self, uid, name, *args, chat_type="private", chat_id=None, user=None):
        handler = self._handlers()[name]
        chat = SimpleNamespace(id=chat_id or uid, type=chat_type)
        msg = Msg(self, chat.id, "/" + name + (" " + " ".join(args) if args else ""), from_user=user or self.user(uid))
        upd = SimpleNamespace(effective_user=user or self.user(uid), effective_chat=chat, message=msg,
                              effective_message=msg, callback_query=None)
        await handler(upd, self.ctx(uid, list(args)))
        await self.flush_jobs()

    async def say(self, uid, text, chat_id=GROUP, reply_to=None, user=None):
        """Someone writes a message in the group."""
        u = user or self.user(uid)
        msg = Msg(self, chat_id, text, from_user=u, reply_to=reply_to)
        upd = SimpleNamespace(effective_user=u, effective_chat=msg.chat, message=msg, effective_message=msg)
        await votes.on_group_text(upd, self.ctx(uid))
        await self.flush_jobs()
        return msg

    async def dm_text(self, uid, text):
        """Someone types a message to the bot in private."""
        from zombiebot import player_ui
        u = self.user(uid)
        msg = Msg(self, uid, text, from_user=u)
        upd = SimpleNamespace(effective_user=u, effective_chat=msg.chat, message=msg, effective_message=msg)
        await player_ui.on_private_text(upd, self.ctx(uid))
        await self.flush_jobs()
        return msg

    async def press(self, uid, data, message=None):
        message = message or Msg(self, uid, "x")
        answers = []

        async def answer(text=None, show_alert=False):
            answers.append(text)

        async def edit_message_text(text, reply_markup=None, **kw):
            assert isinstance(text, str) and text.strip(), "empty edit"
            assert len(text) <= 4096, f"edit too long ({len(text)})"
            FakeBot._check_markup(None, reply_markup)
            message.text, message.markup = text, reply_markup
            if message not in self.sent:
                self.sent.append(message)

        async def edit_message_reply_markup(reply_markup=None):
            message.markup = reply_markup

        q = SimpleNamespace(data=data, from_user=self.user(uid), message=message, answer=answer,
                            edit_message_text=edit_message_text, edit_message_reply_markup=edit_message_reply_markup)
        upd = SimpleNamespace(effective_user=q.from_user, effective_chat=SimpleNamespace(id=uid, type="private"),
                              callback_query=q, message=None)
        await B.on_button(upd, self.ctx(uid))
        await self.flush_jobs()
        return answers

    def _handlers(self):
        if not hasattr(self, "_h"):
            app = B.build_app("123:TEST")
            self._h = {}
            for grp in app.handlers.values():
                for h in grp:
                    if hasattr(h, "commands"):
                        for c in h.commands:
                            self._h[c] = h.callback
        return self._h

    def last_to(self, chat_id, with_buttons=True):
        for m in reversed(self.sent):
            if m.chat_id == chat_id and (m.buttons() or not with_buttons):
                return m
        return None

    def texts_to(self, chat_id):
        return [m.text for m in self.sent if m.chat_id == chat_id]

    def player(self, name):
        return next(p for p in self.g["players"].values() if p["name"] == name)


def run(coro):
    return asyncio.run(coro)
