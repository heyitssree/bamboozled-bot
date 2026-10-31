"""Fake Discord objects for driving the real cogs and views without a connection."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bamboozled.config import Config
from bamboozled.context import Context
from bamboozled.settings import Settings
from tests.server_helpers import make

OWNER = 900000000000000001
ADMIN_ROLE = 123456789012345678


def user(uid: int, name: str = None, roles=()):
    return SimpleNamespace(
        id=uid, display_name=name or f"User{uid}", roles=[SimpleNamespace(id=r) for r in roles], mention=f"<@{uid}>"
    )


class FakeResponse:
    def __init__(self):
        self.send_message, self.edit_message, self.defer = AsyncMock(), AsyncMock(), AsyncMock()
        self.send_modal, self.launch_activity = AsyncMock(), AsyncMock()
        self._done = False
        for name in ("send_message", "edit_message", "defer", "send_modal", "launch_activity"):
            getattr(self, name).side_effect = self._mark

    async def _mark(self, *a, **k):
        self._done = True

    def is_done(self):
        return self._done


class FakeInteraction:
    def __init__(self, bot, who, guild_id=555, command=None, data=None):
        self.client, self.user, self.guild_id, self.command, self.data = bot, who, guild_id, command, data or {}
        self.guild = SimpleNamespace(id=guild_id, get_member=lambda uid: None, me=None) if guild_id else None
        self.response = FakeResponse()
        self.followup = SimpleNamespace(send=AsyncMock())
        self.edit_original_response = AsyncMock()
        self.channel_id = 777
        self.message = None

    @property
    def said(self) -> str:
        """Everything sent back to the user, as one string (for simple assertions)."""
        calls = list(self.response.send_message.call_args_list) + list(self.followup.send.call_args_list)
        edits = list(self.response.edit_message.call_args_list) + list(self.edit_original_response.call_args_list)
        parts = []
        for c in calls + edits:
            if c.args:
                parts.append(str(c.args[0]))
            if c.kwargs.get("content"):
                parts.append(str(c.kwargs["content"]))
            emb = c.kwargs.get("embed")
            if emb is not None:
                parts.append(
                    (emb.title or "") + " " + (emb.description or "") + " " + " ".join(f"{f.name} {f.value}" for f in emb.fields)
                )
        return "\n".join(parts)

    def sent_kwargs(self):
        return self.response.send_message.call_args.kwargs


class FakeBot:
    def __init__(self, ctx, owner_ids=(OWNER,)):
        self.ctx = ctx
        self.owner_ids = set(owner_ids)
        self.is_owner = AsyncMock(side_effect=lambda u: u.id in self.owner_ids)
        self.get_user = lambda uid: SimpleNamespace(display_name=f"User{uid}")
        self.fetch_user = AsyncMock(side_effect=lambda uid: SimpleNamespace(display_name=f"User{uid}"))
        self.channels = {}
        self.get_channel = lambda cid: self.channels.get(cid)
        self.fetch_channel = AsyncMock(side_effect=lambda cid: self.channels[cid])


def make_ctx(with_manager=True, **setting_overrides) -> Context:
    settings = Settings(setting_overrides)
    ctx = Context.create(Config(env="test"), settings)
    if with_manager:
        mgr, clock, rec = make(settings=settings)
        ctx.manager = mgr
        ctx.privacy.in_running_game = mgr.in_running_game
        ctx.privacy.evict = mgr.evict_user
        mgr.is_opted_out = ctx.privacy.is_opted_out
        ctx._clock, ctx._rec = clock, rec
    return ctx


@pytest.fixture
def ctx(tmp_db):
    c = make_ctx()
    asyncio.run(c.privacy.load())
    return c


@pytest.fixture
def bot(ctx):
    b = FakeBot(ctx)
    ctx.bot = b
    return b


def interaction(bot, uid=1, **kw):
    return FakeInteraction(bot, user(uid), **kw)
