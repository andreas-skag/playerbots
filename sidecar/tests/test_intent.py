import asyncio
import json

from brain import intent
from brain.request_parser import parse_request


def _req(msg, group="Andreas:7:Paladin:60;Grimtok:42:Warrior:60"):
    return parse_request({
        "messages": [{"role": "user", "content": f"Andreas:{msg}"}],
        "meta": {"bot_guid": "42", "bot_name": "Grimtok", "other_guid": "7",
                 "other_name": "Andreas", "channel": "in party chat",
                 "event": "chat", "group": group},
    })


class FakeOllama:
    def __init__(self, reply):
        self.reply = reply
        self.calls = []

    async def chat(self, messages, tier="inner", format=None):
        self.calls.append((messages, tier, format))
        return self.reply


def test_prefilter_rejects_banter():
    assert intent.looks_like_command("nice weather in westfall") is False
    assert intent.looks_like_command("what do you think of this sword?") is False


def test_prefilter_accepts_command_shaped():
    assert intent.looks_like_command("can you tank this dungeon?") is True
    assert intent.looks_like_command("Grimtok kill the skull target") is True
    assert intent.looks_like_command("lead the way") is True
    assert intent.looks_like_command("come help me") is True


def test_classify_valid_verb_with_mark():
    fake = FakeOllama(json.dumps(
        {"verb": "attack", "args": {"mark": "skull"}, "addressed": "Grimtok"}))
    result = asyncio.run(intent.classify(fake, "templates", _req("Grimtok kill the skull")))
    assert result == intent.Intent(verb="attack", args={"mark": "skull"}, addressed="Grimtok")
    assert fake.calls[0][1] == "ambient"      # small model
    assert fake.calls[0][2] == "json"         # constrained output
    prompt = fake.calls[0][0][0]["content"]
    assert "attack" in prompt and "Grimtok" in prompt


def test_classify_none_verb_and_junk_return_none():
    assert asyncio.run(intent.classify(FakeOllama('{"verb": "none"}'), "templates", _req("hi"))) is None
    assert asyncio.run(intent.classify(FakeOllama("not json"), "templates", _req("hi"))) is None
    assert asyncio.run(intent.classify(FakeOllama('{"verb": "delete_character"}'), "templates", _req("hi"))) is None


def test_classify_invalid_mark_dropped_but_verb_kept():
    fake = FakeOllama('{"verb": "attack", "args": {"mark": "banana"}}')
    result = asyncio.run(intent.classify(fake, "templates", _req("kill it")))
    assert result == intent.Intent(verb="attack", args={}, addressed="")


def test_classify_model_error_returns_none():
    class Boom:
        async def chat(self, messages, tier="inner", format=None):
            raise RuntimeError("ollama down")
    assert asyncio.run(intent.classify(Boom(), "templates", _req("can you tank?"))) is None
