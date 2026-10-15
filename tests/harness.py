"""Offline stand-in for Telegram: records what the bot sends and lets tests press buttons as any user."""
import asyncio
import os
import random
import tempfile
from types import SimpleNamespace

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp())

from zombiebot import bot as B          # noqa: E402
from zombiebot.state import Store       # noqa: E402

GM = 1000


class Msg:
    _n = 0

    def __init__(self, world, chat_id, text, markup=None, dice=None, photo=False):
        Msg._n += 1
        self.message_id = Msg._n
        self.world, self.chat_id, self.text, self.markup = world, chat_id, text, markup
        self.dice = SimpleNamespace(value=dice) if dice else None
        self.photo = photo

    def buttons(self):
        if not self.markup:
            return []
        return [b.callback_data for row in self.markup.inline_keyboard for b in row]

    async def reply_text(self, text, reply_markup=None, **kw):
        return await self.world.bot.send_message(self.chat_id, text, reply_markup=reply_markup)

    async def reply_photo(self, photo, caption=None, **kw):
        return await self.world.bot.send_photo(self.chat_id, photo, caption=caption)

    async def edit_reply_markup(self, markup=None):
        self.markup = markup


class FakeBot:
    def __init__(self, world, rng):
        self.world, self.rng = world, rng

    async def send_message(self, chat_id, text, reply_markup=None, **kw):
        assert isinstance(text, str) and text.strip(), "empty message"
        assert len(text) <= 4096, f"message too long ({len(text)})"
        if reply_markup:
            for row in reply_markup.inline_keyboard:
                for b in row:
                    assert len(b.callback_data.encode()) <= 64, f"callback_data too long: {b.callback_data}"
                    assert b.text, "button without text"
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


class FakeJobQueue:
    def __init__(self, world):
        self.world = world

    def run_once(self, cb, when, data=None, **kw):
        self.world.jobs.append((cb, data))

    def run_daily(self, *a, **kw):
        pass


class World:
    def __init__(self, seed=1):
        self.rng = random.Random(seed)
        B.store = Store(os.path.join(tempfile.mkdtemp(), "state.json"))
        B.ENV_GMS.clear()
        B.ENV_GMS.add(GM)
        self.sent, self.jobs, self.forced_dice = [], [], []
        self.bot = FakeBot(self, self.rng)
        self.jq = FakeJobQueue(self)
        self.user_data = {}
        self.errors = []

    @property
    def g(self):
        return B.store.g

    def ctx(self, uid, args=None):
        return SimpleNamespace(bot=self.bot, job_queue=self.jq, args=args or [],
                               user_data=self.user_data.setdefault(uid, {}), job=None)

    async def flush_jobs(self):
        while self.jobs:
            cb, data = self.jobs.pop(0)
            c = self.ctx(0)
            c.job = SimpleNamespace(data=data)
            await cb(c)

    def user(self, uid, name=None):
        return SimpleNamespace(id=uid, full_name=name or f"User{uid}", username=f"u{uid}")

    async def cmd(self, uid, name, *args, chat_type="private", chat_id=None, text=None):
        handler = {**self._handlers()}[name]
        chat = SimpleNamespace(id=chat_id or uid, type=chat_type)
        msg = Msg(self, chat.id, text or ("/" + name + (" " + " ".join(args) if args else "")))
        upd = SimpleNamespace(effective_user=self.user(uid), effective_chat=chat, message=msg, callback_query=None)
        await handler(upd, self.ctx(uid, list(args)))
        await self.flush_jobs()

    async def press(self, uid, data, message=None):
        message = message or Msg(self, uid, "x")
        answers = []

        async def answer(text=None, show_alert=False):
            answers.append(text)

        async def edit_message_text(text, reply_markup=None, **kw):
            assert isinstance(text, str) and text.strip(), "empty edit"
            assert len(text) <= 4096
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
            for group in app.handlers.values():
                for h in group:
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


def run(coro):
    return asyncio.run(coro)
