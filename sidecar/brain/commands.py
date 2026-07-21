"""Authorization, routing and dedup for conversational commands.

Single-threaded by construction: FastAPI runs one event loop, and every
registry mutation happens synchronously between awaits, so no locks.
Concurrent requests for the same utterance share a single classification
via asyncio.Future; all callers await the same result.
"""
import asyncio
import logging
import time
from dataclasses import dataclass

from . import intent as intent_mod
from .intent import Intent
from .request_parser import BotRequest
from .settings import Settings

log = logging.getLogger(__name__)

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


async def _swallow(coro):
    """Classify and swallow exceptions; treat failures as no command."""
    try:
        return await coro
    except Exception:
        log.exception("intent classification failed; treating as no command")
        return None


@dataclass
class Decision:
    role: str                 # "actor" | "bystander" | "refused" | "none"
    intent: "Intent | None"


class DedupRegistry:
    def __init__(self, window_s: float, actor_ttl_s: float = 45.0):
        self.window_s = window_s
        self.actor_ttl_s = actor_ttl_s
        self._intents: dict[tuple, tuple[float, asyncio.Future]] = {}
        self._actors: dict[int, float] = {}

    def _expire(self, now: float) -> None:
        self._intents = {k: v for k, v in self._intents.items()
                         if now - v[0] < self.window_s}
        self._actors = {k: v for k, v in self._actors.items()
                        if now - v < self.actor_ttl_s}

    async def get_or_classify(self, key: tuple, coro_factory):
        now = time.monotonic()
        self._expire(now)
        if key not in self._intents:
            # Synchronous insert before the first await, so concurrent
            # requests for the same utterance all share one classification.
            self._intents[key] = (now, asyncio.ensure_future(_swallow(coro_factory())))
        future = self._intents[key][1]
        return await future

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
        # Empty roster (missing group meta) degrades to whisper-like
        # semantics: act ourselves. A roster with no routable bots
        # (only players/the speaker) routes to nobody.
        return req.bot_guid if not req.group else 0
    for cls in _CLASS_FIT.get(intent.verb, []):
        for m in sorted(candidates, key=lambda m: m.guid):
            if m.cls.lower() == cls.lower():
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
