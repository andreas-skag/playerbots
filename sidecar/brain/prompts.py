"""Assemble chat prompts from persona, memory and the incoming request."""
from pathlib import Path

from .request_parser import BotRequest


def describe_sentiment(score: float) -> str:
    if score >= 60:
        return "a close friend"
    if score >= 25:
        return "a friend"
    if score >= 5:
        return "a friendly acquaintance"
    if score > -5:
        return "a stranger"
    if score > -25:
        return "someone you are wary of"
    return "someone you dislike"


def assemble(templates_dir: str | Path, persona: str, summary: str, score: float,
             recent: list[tuple[str, str]], req: BotRequest,
             directive_note: str = "") -> list[dict]:
    template = (Path(templates_dir) / "chat.txt").read_text()
    history = "\n".join(
        f"{req.other_name}: {msg}\n{req.bot_name}: {reply}" for msg, reply in recent
    ) or "(none)"
    system = template.format(
        game_system=req.system,
        persona=persona,
        relationship=describe_sentiment(score),
        summary=summary or "no shared history yet",
        history=history,
        bot_name=req.bot_name,
        other_name=req.other_name,
        directive_note=directive_note,
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": f"{req.speaker_name}: {req.message}"},
    ]
