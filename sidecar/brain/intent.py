"""Turn command-shaped chat into a validated Intent via the small model."""
import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from .request_parser import BotRequest

log = logging.getLogger(__name__)

VERBS = frozenset({
    "role_tank", "role_heal", "role_dps", "follow", "stay", "guard", "flee",
    "attack", "lead", "loot", "release", "come", "give_leader", "reset",
})
MARKS = frozenset({
    "star", "circle", "diamond", "triangle", "moon", "square", "cross", "skull",
})

# Cheap pre-filter: only messages containing a command-ish keyword reach the
# classifier. Generous on purpose — false positives cost one small-model call,
# false negatives cost a missed command.
_KEYWORDS = re.compile(
    r"\b(tank|heal|dps|damage|follow|stay|wait|guard|protect|hold|flee|run"
    r"|attack|kill|fight|lead|loot|release|come|here|help|summon|leader"
    r"|reset|stop|skull|cross|square|moon|triangle|diamond|circle|star)\b",
    re.IGNORECASE)


@dataclass
class Intent:
    verb: str
    args: dict[str, str] = field(default_factory=dict)
    addressed: str = ""


def looks_like_command(message: str) -> bool:
    return bool(_KEYWORDS.search(message))


def _validate(raw: dict, req: BotRequest) -> "Intent | None":
    verb = raw.get("verb")
    if verb not in VERBS:
        return None
    args = {}
    raw_args = raw.get("args") or {}
    if verb == "attack" and isinstance(raw_args, dict):
        mark = raw_args.get("mark", "")
        if isinstance(mark, str) and mark.lower() in MARKS:
            args["mark"] = mark.lower()
    addressed = raw.get("addressed") or ""
    roster_names = {m.name.lower(): m.name for m in req.group}
    addressed = roster_names.get(str(addressed).lower(), "")
    return Intent(verb=verb, args=args, addressed=addressed)


async def classify(ollama, templates_dir, req: BotRequest) -> "Intent | None":
    template = (Path(templates_dir) / "intent.txt").read_text()
    roster = ", ".join(f"{m.name} ({m.cls} {m.level})" for m in req.group) or "(none)"
    system = template.format(speaker=req.speaker_name, roster=roster)
    messages = [{"role": "system", "content": system},
                {"role": "user", "content": req.message}]
    try:
        reply = await ollama.chat(messages, tier="ambient", format="json")
        raw = json.loads(reply)
    except Exception:
        log.exception("intent classification failed")
        return None
    if not isinstance(raw, dict):
        return None
    return _validate(raw, req)
