"""Deterministic persona cards and inner-circle tiering."""
import random
import zlib

from .memory import MemoryStore
from .request_parser import BotRequest
from .settings import Settings

_ARCHETYPES = [
    "gruff veteran, terse and dry, secretly softhearted",
    "cheerful optimist, endlessly curious about everything",
    "boastful show-off, loud, loyal to a fault",
    "haughty perfectionist, precise, slow to warm up",
    "laid-back drifter, superstitious, jokes under pressure",
    "nervous newcomer, eager to please, easily startled",
    "scheming merchant at heart, always angling for profit",
    "stoic protector, few words, watches everyone's back",
]
_SPEECH = [
    "short clipped sentences, no pleasantries",
    "warm and chatty, asks questions back",
    "exclamations and tavern metaphors",
    "formal vocabulary, rarely uses contractions",
    "relaxed drawl, fond of odds and omens",
    "rambling, trails off mid-thought sometimes",
]
_QUIRKS = [
    "complains that old gear was better than any upgrade",
    "names every animal they come across",
    "rates every place by how good the ale would taste there",
    "refuses to admit being lost or wrong",
    "flips a coin before decisions and blames it after",
    "collects rumors and repeats them as fact",
]
_ATTITUDES = [
    "respects deeds, not words",
    "trusts quickly, hurt deeply by rudeness",
    "fiercely protective of companions",
    "warms only to those who prove competent",
    "friendly to all, loyal to none... they claim",
    "keeps score of every favor owed",
]

_INNER_CHANNELS = {"in party chat", "in raid chat", "in guild chat", "in private message"}


def generate_card(bot_guid: int, bot_name: str) -> str:
    seed = bot_guid or zlib.crc32(bot_name.encode())
    rng = random.Random(seed)
    return (f"Personality: {rng.choice(_ARCHETYPES)}. "
            f"Speech: {rng.choice(_SPEECH)}. "
            f"Quirk: {rng.choice(_QUIRKS)}. "
            f"Attitude: {rng.choice(_ATTITUDES)}.")


def get_persona(store: MemoryStore, bot_guid: int, bot_name: str) -> str:
    card = store.get_persona(bot_guid)
    if card is None:
        card = generate_card(bot_guid, bot_name)
        store.set_persona(bot_guid, card)
    return card


def is_inner_circle(req: BotRequest, settings: Settings) -> bool:
    return req.channel in _INNER_CHANNELS or req.bot_name in settings.inner_circle
