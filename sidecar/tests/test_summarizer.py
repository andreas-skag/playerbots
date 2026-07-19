import asyncio

from brain.memory import MemoryStore
from brain.summarizer import extract_json, maybe_summarize


class FakeOllama:
    def __init__(self, reply):
        self.reply = reply
        self.calls = []

    async def chat(self, messages, tier="inner"):
        self.calls.append((messages, tier))
        return self.reply


def test_extract_json_tolerates_chatter():
    assert extract_json('Sure! {"summary": "s", "sentiment_delta": 2} done') == \
        {"summary": "s", "sentiment_delta": 2}
    assert extract_json("no json here") == {}


def seeded_store(n):
    store = MemoryStore(":memory:")
    for i in range(n):
        store.record_interaction(42, 7, "Andreas", "say", f"m{i}", f"r{i}")
    return store


def test_below_threshold_does_nothing():
    store = seeded_store(2)
    fake = FakeOllama('{"summary": "x", "sentiment_delta": 0}')
    assert asyncio.run(maybe_summarize(store, fake, 42, 7, "Grimtok", "Andreas", 3)) is False
    assert fake.calls == []


def test_summarizes_and_applies_clamped_delta():
    store = seeded_store(3)
    fake = FakeOllama('{"summary": "They quested in Westfall.", "sentiment_delta": 40}')
    assert asyncio.run(maybe_summarize(store, fake, 42, 7, "Grimtok", "Andreas", 3)) is True
    text, last_id = store.summary(42, 7)
    assert text == "They quested in Westfall."
    assert last_id == 3
    assert store.unsummarized(42, 7) == []
    assert store.sentiment(42, 7) == 5  # 40 clamped to +5
    assert fake.calls[0][1] == "utility"


def test_swallows_bad_llm_output():
    store = seeded_store(3)
    fake = FakeOllama("total nonsense")
    assert asyncio.run(maybe_summarize(store, fake, 42, 7, "Grimtok", "Andreas", 3)) is False
    assert store.summary(42, 7) == ("", 0)


def test_extract_json_ignores_trailing_braces():
    reply = '{"summary": "ok", "sentiment_delta": 1} — try the {AoE} build'
    assert extract_json(reply) == {"summary": "ok", "sentiment_delta": 1}


def test_swallows_real_exception():
    store = seeded_store(3)

    class ExplodingOllama:
        async def chat(self, messages, tier="inner"):
            raise RuntimeError("ollama down")

    assert asyncio.run(
        maybe_summarize(store, ExplodingOllama(), 42, 7, "Grimtok", "Andreas", 3)) is False
    assert store.summary(42, 7) == ("", 0)
