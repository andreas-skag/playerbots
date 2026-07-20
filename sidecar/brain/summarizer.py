"""Compress old interactions into a summary and drift sentiment accordingly."""
import json
import logging

from .memory import MemoryStore

log = logging.getLogger(__name__)

_PROMPT = """You maintain the memory of {bot_name}, a World of Warcraft character,
about the player {other_name}.

Current memory: {old_summary}

New conversations (player line, then {bot_name}'s reply):
{lines}

Reply with ONLY a JSON object:
{{"summary": "<max 60 words, third person, merge current memory with the new events, keep the most personal or emotionally notable details>",
"sentiment_delta": <integer -5..5, how these conversations should shift {bot_name}'s feelings toward {other_name}>}}"""


def extract_json(text: str) -> dict:
    decoder = json.JSONDecoder()
    for i, ch in enumerate(text):
        if ch == "{":
            try:
                obj, _ = decoder.raw_decode(text[i:])
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict):
                return obj
    return {}


async def maybe_summarize(store: MemoryStore, ollama, bot_guid: int, other_guid: int,
                          bot_name: str, other_name: str, threshold: int) -> bool:
    try:
        rows = store.unsummarized(bot_guid, other_guid)
        if len(rows) < threshold:
            return False
        old_summary, _ = store.summary(bot_guid, other_guid)
        lines = "\n".join(f"{other_name}: {m}\n{bot_name}: {r}" for _, m, r in rows)
        reply = await ollama.chat(
            [{"role": "user", "content": _PROMPT.format(
                bot_name=bot_name, other_name=other_name,
                old_summary=old_summary or "(none yet)", lines=lines)}],
            tier="utility")
        data = extract_json(reply)
        summary = data.get("summary")
        if not summary:
            return False
        store.set_summary(bot_guid, other_guid, summary, rows[-1][0])
        try:
            delta = max(-5.0, min(5.0, float(data.get("sentiment_delta", 0))))
        except (TypeError, ValueError):
            delta = 0.0
        if delta:
            store.adjust_sentiment(bot_guid, other_guid, delta)
        return True
    except Exception:
        log.exception("summarize failed for bot=%s other=%s", bot_guid, other_guid)
        return False
