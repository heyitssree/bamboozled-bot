"""One registry declares every setting. The admin panel, /bamboozled-admin set, validation, defaults, export and import
all read from it, and the game server reads values at use time. Unknown keys fail at startup."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

KINDS = ("bool", "int", "choice", "id_list", "role")


@dataclass(frozen=True)
class Setting:
    key: str
    kind: str
    default: Any
    category: str
    label: str
    help: str = ""
    min: Optional[int] = None
    max: Optional[int] = None
    choices: tuple = ()
    legacy_keys: tuple = ()  # old names this setting replaces (for importing old configuration)
    hidden: bool = False  # kept out of the panel (still settable with /bamboozled-admin set)

    def __post_init__(self):
        assert self.kind in KINDS, self.kind


SETTINGS: tuple[Setting, ...] = (
    Setting("system.killswitch", "bool", False, "System", "Master kill switch", help="Closes all rooms and rejects new ones."),
    Setting(
        "system.testing_guilds",
        "id_list",
        [],
        "System",
        "Testing servers",
        help="Games in these servers are not recorded and post no result card.",
        legacy_keys=("server_settings.test_mode",),
    ),
    Setting("system.panel_role", "role", None, "System", "Role allowed to open the admin panel"),
    Setting("feature.bamboozled", "bool", True, "Features", "Bamboozled mode"),
    Setting("feature.fff", "bool", True, "Features", "Fastest Fingers First mode"),
    Setting("feature.survival", "bool", True, "Features", "Survival mode"),
    Setting(
        "feature.text_mode",
        "bool",
        True,
        "Features",
        "Legacy text games (/bamboozled, /fff, /survival)",
        help="Retired after cutover.",
    ),
    Setting("feature.post_results", "bool", True, "Features", "Post a result card in the channel"),
    Setting("game.total_rounds", "int", 5, "Gameplay", "Rounds (Bamboozled)", min=3, max=20),
    Setting("game.question_timeout_seconds", "int", 30, "Gameplay", "Seconds to answer", min=10, max=90),
    Setting("game.fff_rounds", "int", 10, "Gameplay", "Questions per FFF game", min=5, max=30),
    Setting("game.reveal_pause_seconds", "int", 3, "Gameplay", "Seconds to show each answer",
            help="How long the result of a question stays on screen before the next one is asked.", min=0, max=10),
    Setting("activity.max_rooms", "int", 20, "Activity", "Rooms at once", min=1, max=100),
    Setting("activity.max_players", "int", 10, "Activity", "Players per room", min=2, max=20),
    Setting("activity.allow_spectators", "bool", True, "Activity", "Late joiners may watch"),
    Setting("activity.lobby_ttl_minutes", "int", 15, "Activity", "Close an idle lobby after", min=2, max=120),
    Setting("activity.idle_ttl_minutes", "int", 30, "Activity", "Close an idle game after", min=5, max=240),
    Setting("activity.reconnect_grace_seconds", "int", 30, "Activity", "Seat kept after a disconnect", min=5, max=120),
    Setting("activity.require_proxy_signature", "bool", False, "Activity", "Require Discord proxy signatures on REST"),
    Setting("trivia.sources", "choice", "both", "Trivia", "Question sources", choices=("opentdb", "tapi", "both", "custom_only")),
    Setting("trivia.safety_strictness", "choice", "standard", "Trivia", "Screening strictness", choices=("standard", "strict")),
    Setting("channel.results", "id_list", [], "Channels", "Channels allowed for result cards (empty = the game's channel)"),
    Setting("privacy.optin_cooldown_days", "int", 7, "Privacy", "Days before a user can opt back in", min=0, max=90),
    Setting("privacy.block_during_game", "bool", True, "Privacy", "Refuse opt-out while the user is in a running game"),
)

BY_KEY: dict[str, Setting] = {s.key: s for s in SETTINGS}
CATEGORIES: tuple[str, ...] = tuple(dict.fromkeys(s.category for s in SETTINGS))
assert len(BY_KEY) == len(SETTINGS), "duplicate setting key in the registry"


def by_legacy_key(old: str) -> Optional[Setting]:
    return next((s for s in SETTINGS if old in s.legacy_keys), None)
