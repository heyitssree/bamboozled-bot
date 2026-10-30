"""@everyone / role pings must never go out, and player names must be neutralised (finding F3)."""
import discord

from bamboozled.services.names import ping_only, safe_name
from bot import SAFE_MENTIONS, BamboozledBot


def test_bot_default_allowed_mentions_block_everyone_and_roles():
    payload = SAFE_MENTIONS.to_dict()       # the real discord.py object, not a fake
    assert payload == {"parse": ["users"]}      # no "everyone", no "roles"; replies do not ping
    assert SAFE_MENTIONS.replied_user is False


def test_bot_is_constructed_with_them():
    bot = BamboozledBot()
    assert bot.allowed_mentions.to_dict() == SAFE_MENTIONS.to_dict()


def test_single_user_ping_merged_with_the_bot_default_pings_only_that_user():
    one = discord.AllowedMentions(users=[discord.Object(id=42)])
    merged = SAFE_MENTIONS.merge(one).to_dict()       # what discord.py actually sends
    assert merged == {"users": [42], "parse": []}


def test_ping_only_is_safe_even_without_merging():
    assert ping_only(42, 43).to_dict() == {"users": [42, 43], "parse": []}


def test_safe_name_breaks_everyone_here_and_user_mentions():
    for raw in ("@everyone", "@here", "<@123456789012345678>", "<@&123456789012345678>"):
        out = safe_name(raw)
        assert out != raw and "@everyone" not in out and "@here" not in out
        assert "<@123456789012345678>" not in out


def test_safe_name_escapes_markdown():
    assert safe_name("**bold** _x_ `c`") == "\\*\\*bold\\*\\* \\_x\\_ \\`c\\`"


def test_plain_names_pass_through():
    assert safe_name("Sree") == "Sree"
