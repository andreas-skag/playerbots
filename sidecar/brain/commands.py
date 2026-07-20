"""Authorization, routing and dedup for conversational commands.

Single-threaded by construction: FastAPI runs one event loop, and every
registry mutation happens synchronously between awaits, so no locks.
"""
import time
from dataclasses import dataclass

from . import intent as intent_mod
from .intent import Intent
from .request_parser import BotRequest
from .settings import Settings

_COMMAND_CHANNELS = {"in party chat", "in raid chat"}
_WHISPER = "in private message"

_CLASS_FIT = {
    "role_tank": ["Warrior", "Paladin", "Druid"],
    "lead": ["Warrior", "Paladin", "Druid"],
    "attack": ["Warrior", "Paladin", "Druid"],
    "role_heal": ["Priest", "Druid", "Shaman", "Paladin"],
}

_DESCRIPTIONS = {
    "role_tank": "switch to tanking",
    "role_heal": "switch to healing",
    "role_dps": "switch to dealing damage",
    "follow": "follow them",
    "stay": "stay where you are",
    "guard": "guard this spot",
    "flee": "run from the fight",
    "attack": "attack their target",
    "lead": "lead the way",
    "loot": "gather the loot",
    "release": "release your spirit",
    "come": "come to them",
    "give_leader": "hand them group lead",
    "reset": "snap out of it and reset your behavior",
}


@dataclass
class Decision:
    role: str                 # "actor" | "bystander" | "refused" | "none"
    intent: "Intent | None"


class DedupRegistry:
    def __init__(self, window_s: float):
        self.window_s = window_s
        self._intents: dict[tuple, tuple[float, "Intent | None"]] = {}
        self._actors: dict[int, float] = {}

    def _expire(self, now: float) -> None:
        self._intents = {k: v for k, v in self._intents.items()
                         if now - v[0] < self.window_s}
        self._actors = {k: v for k, v in self._actors.items()
                        if now - v < self.window_s}

    async def get_or_classify(self, key: tuple, coro_factory):
        now = time.monotonic()
        self._expire(now)
        if key in self._intents:
            return self._intents[key][1]
        # Reserve the slot before awaiting so concurrent requests for the
        # same utterance don't classify twice; they briefly see None, which
        # only costs a missed bystander note.
        self._intents[key] = (now, None)
        result = await coro_factory()
        self._intents[key] = (now, result)
        return result

    def record_actor(self, bot_guid: int) -> None:
        self._actors[bot_guid] = time.monotonic()

    def was_recent_actor(self, guid: int) -> bool:
        self._expire(time.monotonic())
        return guid in self._actors


def _authorized(req: BotRequest, settings: Settings) -> bool:
    speaker_is_player = str(req.other_guid) in settings.player_guids
    if req.channel == _WHISPER:
        return speaker_is_player
    if req.channel not in _COMMAND_CHANNELS:
        return False
    if speaker_is_player:
        return True
    in_roster = any(m.guid == req.other_guid for m in req.group)
    return in_roster and settings.commands.allow_bot_commanders


def _pick_actor(req: BotRequest, intent: Intent, settings: Settings) -> int:
    if req.channel == _WHISPER:
        return req.bot_guid
    if intent.addressed:
        for m in req.group:
            if m.name == intent.addressed:
                return m.guid
    candidates = [m for m in req.group
                  if m.guid != req.other_guid and str(m.guid) not in settings.player_guids]
    if not candidates:
        return req.bot_guid
    for cls in _CLASS_FIT.get(intent.verb, []):
        for m in sorted(candidates, key=lambda m: m.guid):
            if m.cls == cls:
                return m.guid
    return min(c.guid for c in candidates)


async def decide(registry: DedupRegistry, ollama, settings: Settings, store,
                 req: BotRequest) -> Decision:
    if not _authorized(req, settings):
        return Decision("none", None)
    if registry.was_recent_actor(req.other_guid):
        return Decision("none", None)

    key = (req.other_guid, req.message.strip().lower())
    intent = await registry.get_or_classify(
        key, lambda: intent_mod.classify(ollama, settings.templates_dir, req))
    if intent is None:
        return Decision("none", None)

    if _pick_actor(req, intent, settings) != req.bot_guid:
        return Decision("bystander", intent)

    score = store.sentiment(req.bot_guid, req.other_guid)
    if score < settings.commands.sentiment_threshold and not settings.commands.always_obey:
        return Decision("refused", intent)

    registry.record_actor(req.bot_guid)
    return Decision("actor", intent)


def directive_json(intent: Intent) -> dict:
    out = {"verb": intent.verb}
    if intent.args:
        out["args"] = dict(intent.args)
    return out


def describe(intent: Intent) -> str:
    if intent.verb == "attack" and intent.args.get("mark"):
        return f"attack the {intent.args['mark']} target"
    return _DESCRIPTIONS[intent.verb]
