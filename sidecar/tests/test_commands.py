import asyncio
import time

from brain import commands
from brain.intent import Intent
from brain.memory import MemoryStore
from brain.request_parser import parse_request
from brain.settings import CommandSettings, Settings

ROSTER = "Andreas:7:paladin:60;Grimtok:42:warrior:60;Zinnia:43:priest:58"


def _req(msg="can someone tank?", bot_guid="42", other_guid="7",
         channel="in party chat", group=ROSTER):
    return parse_request({
        "messages": [{"role": "user", "content": f"X:{msg}"}],
        "meta": {"bot_guid": bot_guid, "bot_name": "Grimtok",
                 "other_guid": other_guid, "other_name": "Andreas",
                 "channel": channel, "event": "chat", "group": group},
    })


class FakeOllama:
    def __init__(self, reply='{"verb": "role_tank", "args": {}, "addressed": ""}'):
        self.reply = reply
        self.calls = 0

    async def chat(self, messages, tier="inner", format=None):
        self.calls += 1
        return self.reply


def _settings(**cmd):
    return Settings(player_guids=["7"], commands=CommandSettings(**cmd))


def _decide(registry, ollama, settings, store, req):
    return asyncio.run(commands.decide(registry, ollama, settings, store, req))


def test_unauthorized_stranger_no_classifier_call():
    fake = FakeOllama()
    req = _req(other_guid="999", channel="in private message")
    d = _decide(commands.DedupRegistry(3.0), fake, _settings(), MemoryStore(":memory:"), req)
    assert d.role == "none" and fake.calls == 0


def test_player_whisper_makes_this_bot_actor():
    req = _req(channel="in private message", group="")
    d = _decide(commands.DedupRegistry(3.0), FakeOllama(), _settings(), MemoryStore(":memory:"), req)
    assert d.role == "actor"
    assert d.intent == Intent(verb="role_tank")


def test_best_fit_routes_tank_to_warrior():
    registry = commands.DedupRegistry(3.0)
    fake = FakeOllama()
    store = MemoryStore(":memory:")
    warrior = _decide(registry, fake, _settings(), store, _req(bot_guid="42"))
    priest = _decide(registry, fake, _settings(), store, _req(bot_guid="43"))
    assert warrior.role == "actor"
    assert priest.role == "bystander"
    assert fake.calls == 1  # classified once, cached for the second bot


def test_addressed_bot_wins_over_class_fit():
    fake = FakeOllama('{"verb": "role_tank", "args": {}, "addressed": "Zinnia"}')
    d = _decide(commands.DedupRegistry(3.0), fake, _settings(), MemoryStore(":memory:"),
                _req(bot_guid="43"))
    assert d.role == "actor"


def test_low_sentiment_refuses_and_always_obey_overrides():
    store = MemoryStore(":memory:")
    store.adjust_sentiment(42, 7, -50)
    d = _decide(commands.DedupRegistry(3.0), FakeOllama(), _settings(), store, _req())
    assert d.role == "refused"
    d2 = _decide(commands.DedupRegistry(3.0), FakeOllama(), _settings(always_obey=True),
                 store, _req())
    assert d2.role == "actor"


def test_bot_commander_allowed_in_group_only():
    # Zinnia (43, in roster, not the player) commands in party chat
    req = _req(other_guid="43")
    d = _decide(commands.DedupRegistry(3.0), FakeOllama(), _settings(), MemoryStore(":memory:"), req)
    assert d.role == "actor"
    # but not when allow_bot_commanders is off
    d2 = _decide(commands.DedupRegistry(3.0), FakeOllama(),
                 _settings(allow_bot_commanders=False), MemoryStore(":memory:"), req)
    assert d2.role == "none"
    # and never via whisper
    d3 = _decide(commands.DedupRegistry(3.0), FakeOllama(), _settings(),
                 MemoryStore(":memory:"), _req(other_guid="43", channel="in private message"))
    assert d3.role == "none"


def test_cascade_guard_blocks_recent_actor():
    registry = commands.DedupRegistry(3.0)
    store = MemoryStore(":memory:")
    first = _decide(registry, FakeOllama(), _settings(), store, _req(bot_guid="42"))
    assert first.role == "actor"
    # now Grimtok (42) speaks a command-shaped line — he just acted, so ignore
    fake = FakeOllama()
    d = _decide(registry, fake, _settings(), store, _req(bot_guid="43", other_guid="42"))
    assert d.role == "none" and fake.calls == 0


def test_directive_json_and_describe():
    assert commands.directive_json(Intent(verb="role_tank")) == {"verb": "role_tank"}
    assert commands.directive_json(Intent(verb="attack", args={"mark": "skull"})) == {
        "verb": "attack", "args": {"mark": "skull"}}
    assert commands.describe(Intent(verb="attack", args={"mark": "skull"})) == \
        "attack the skull target"
    assert commands.describe(Intent(verb="role_tank")) == "switch to tanking"


def test_concurrent_bots_share_one_classification():
    registry = commands.DedupRegistry(3.0)
    store = MemoryStore(":memory:")
    settings = _settings()

    class SlowOllama(FakeOllama):
        async def chat(self, messages, tier="inner", format=None):
            self.calls += 1
            await asyncio.sleep(0.01)
            return self.reply

    fake = SlowOllama()

    async def run():
        return await asyncio.gather(
            commands.decide(registry, fake, settings, store, _req(bot_guid="42")),
            commands.decide(registry, fake, settings, store, _req(bot_guid="43")))

    warrior, priest = asyncio.run(run())
    assert warrior.role == "actor"
    assert priest.role == "bystander"
    assert fake.calls == 1


def test_no_routable_candidates_means_no_actor():
    # Roster contains only the player (the speaker) — nobody to route to.
    d = _decide(commands.DedupRegistry(3.0), FakeOllama(), _settings(),
                MemoryStore(":memory:"), _req(group="Andreas:7:Paladin:60"))
    assert d.role == "bystander"


def test_empty_roster_degrades_to_acting_self():
    d = _decide(commands.DedupRegistry(3.0), FakeOllama(), _settings(),
                MemoryStore(":memory:"), _req(group=""))
    assert d.role == "actor"


def test_actor_tag_outlives_dedup_window():
    # A bot's spoken acknowledgment reaches other bots 5-15s later (LLM
    # generation + C++ typing delay), well after the short dedup window
    # expires. The cascade guard must use its own, much longer TTL so it
    # still blocks that late-arriving echo from being treated as a new
    # command.
    registry = commands.DedupRegistry(0.01, actor_ttl_s=3.0)
    store = MemoryStore(":memory:")
    first = _decide(registry, FakeOllama(), _settings(), store, _req(bot_guid="42"))
    assert first.role == "actor"
    time.sleep(0.05)  # dedup window (0.01s) has now expired
    fake = FakeOllama()
    d = _decide(registry, fake, _settings(), store, _req(bot_guid="43", other_guid="42"))
    assert d.role == "none" and fake.calls == 0


def test_best_fit_matches_lowercase_wire_classes():
    # The real C++ producer (ChatHelper::formatClass) sends lowercase class
    # names. Guids are chosen so the warrior does NOT have the lowest guid
    # among candidates, so a case-sensitive compare falling back to
    # min(guid) would (wrongly) pick the priest instead of matching class.
    roster = "Andreas:7:paladin:60;Grimtok:45:warrior:60;Zinnia:43:priest:58"
    registry = commands.DedupRegistry(3.0)
    fake = FakeOllama()
    store = MemoryStore(":memory:")
    warrior = _decide(registry, fake, _settings(), store, _req(bot_guid="45", group=roster))
    priest = _decide(registry, fake, _settings(), store, _req(bot_guid="43", group=roster))
    assert warrior.role == "actor"
    assert warrior.intent.verb == "role_tank"
    assert priest.role == "bystander"
