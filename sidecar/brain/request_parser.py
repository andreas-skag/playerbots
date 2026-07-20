"""Parse the game server's LLMApiJson POST body into a BotRequest."""
from dataclasses import dataclass, field


@dataclass
class GroupMember:
    name: str
    guid: int
    cls: str
    level: int


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
    group: list["GroupMember"] = field(default_factory=list)


def _to_int(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _meta_str(meta: dict, key: str) -> str:
    value = meta.get(key)
    if not isinstance(value, str):
        return ""
    if value.startswith("<") and value.endswith(">"):
        return ""  # unsubstituted server placeholder
    return value


def _parse_group(raw: str) -> list[GroupMember]:
    members = []
    for entry in raw.split(";"):
        parts = entry.split(":")
        if len(parts) != 4:
            continue
        name, guid, cls, level = (p.strip() for p in parts)
        if not name or not guid.isdigit() or not level.isdigit():
            continue
        members.append(GroupMember(name=name, guid=int(guid), cls=cls, level=int(level)))
    return members


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
        speaker_name=_meta_str(meta, "other_name") or speaker,
        message=message,
        bot_guid=_to_int(meta.get("bot_guid")),
        bot_name=_meta_str(meta, "bot_name"),
        other_guid=_to_int(meta.get("other_guid")),
        other_name=_meta_str(meta, "other_name") or speaker,
        channel=_meta_str(meta, "channel"),
        event=_meta_str(meta, "event") or "chat",
        group=_parse_group(_meta_str(meta, "group")),
    )
