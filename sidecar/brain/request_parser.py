"""Parse the game server's LLMApiJson POST body into a BotRequest."""
from dataclasses import dataclass


@dataclass
class BotRequest:
    system: str
    speaker_name: str
    message: str
    bot_guid: int
    bot_name: str
    other_guid: int
    other_name: str
    channel: str
    event: str


def _to_int(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def parse_request(body: dict) -> BotRequest:
    system = ""
    user = ""
    for m in body.get("messages", []):
        if m.get("role") == "system":
            system = m.get("content", "")
        elif m.get("role") == "user":
            user = m.get("content", "")

    speaker, sep, message = user.partition(":")
    if not sep:
        speaker, message = "", user

    meta = body.get("meta") or {}
    return BotRequest(
        system=system,
        speaker_name=meta.get("other_name") or speaker,
        message=message,
        bot_guid=_to_int(meta.get("bot_guid")),
        bot_name=meta.get("bot_name", ""),
        other_guid=_to_int(meta.get("other_guid")),
        other_name=meta.get("other_name") or speaker,
        channel=meta.get("channel", ""),
        event=meta.get("event", "chat"),
    )
