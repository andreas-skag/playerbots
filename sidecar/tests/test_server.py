from fastapi.testclient import TestClient

from brain.memory import MemoryStore
from brain.server import create_app
from brain.settings import Settings


class FakeOllama:
    def __init__(self, reply="Aye. Deadmines it is, whelp.", intent_reply='{"verb": "none"}'):
        self.reply = reply
        self.intent_reply = intent_reply
        self.calls = []

    async def chat(self, messages, tier="inner", format=None):
        self.calls.append((messages, tier, format))
        return self.intent_reply if format == "json" else self.reply


def body(channel="in party chat"):
    return {
        "model": "brain",
        "messages": [
            {"role": "system", "content": "You are Grimtok in Westfall."},
            {"role": "user", "content": "Andreas:ready for Deadmines?"},
        ],
        "meta": {"bot_guid": "42", "other_guid": "7", "bot_name": "Grimtok",
                 "other_name": "Andreas", "channel": channel, "event": "chat"},
    }


def make_client(tmp_path, fake, per_bot_cooldown=0.0):
    settings = Settings(db_path=":memory:", request_log=str(tmp_path / "req.jsonl"),
                        templates_dir="templates", summarize_after=1000,
                        per_bot_cooldown=per_bot_cooldown)
    store = MemoryStore(":memory:")
    app = create_app(settings=settings, store=store, ollama=fake)
    return TestClient(app), store


def test_inner_circle_reply_records_memory(tmp_path):
    fake = FakeOllama()
    client, store = make_client(tmp_path, fake)
    r = client.post("/v1/chat/completions", json=body())
    assert r.status_code == 200
    assert r.json()["choices"][0]["message"]["content"] == "Aye. Deadmines it is, whelp."
    # persona + memory made it into the prompt
    system = fake.calls[0][0][0]["content"]
    assert "You are Grimtok in Westfall." in system
    assert "Personality:" in system
    assert fake.calls[0][1] == "inner"
    # interaction recorded, sentiment bumped
    assert store.recent(42, 7) == [("ready for Deadmines?", "Aye. Deadmines it is, whelp.")]
    assert store.sentiment(42, 7) == 1


def test_stranger_gets_reply_but_no_memory(tmp_path):
    fake = FakeOllama()
    client, store = make_client(tmp_path, fake)
    r = client.post("/v1/chat/completions", json=body(channel="in world chat"))
    assert r.status_code == 200
    assert fake.calls[0][1] == "ambient"
    assert store.recent(42, 7) == []
    assert store.sentiment(42, 7) == 0


def test_second_message_sees_history(tmp_path):
    fake = FakeOllama()
    client, _ = make_client(tmp_path, fake)
    client.post("/v1/chat/completions", json=body())
    client.post("/v1/chat/completions", json=body())
    system = fake.calls[1][0][0]["content"]
    assert "Andreas: ready for Deadmines?" in system  # history from call 1


def test_ollama_failure_returns_empty_content(tmp_path):
    class Exploding:
        async def chat(self, messages, tier="inner"):
            raise RuntimeError("ollama down")
    client, store = make_client(tmp_path, Exploding())
    r = client.post("/v1/chat/completions", json=body())
    assert r.status_code == 200
    assert r.json()["choices"][0]["message"]["content"] == ""
    assert store.recent(42, 7) == []  # failed generation not recorded


def test_per_bot_cooldown_silences_rapid_fire(tmp_path):
    fake = FakeOllama()
    client, store = make_client(tmp_path, fake, per_bot_cooldown=60.0)
    r1 = client.post("/v1/chat/completions", json=body())
    r2 = client.post("/v1/chat/completions", json=body())
    assert r1.json()["choices"][0]["message"]["content"] != ""
    assert r2.json()["choices"][0]["message"]["content"] == ""
    assert len(fake.calls) == 1  # second request never reached Ollama
    assert len(store.recent(42, 7)) == 1


def test_requests_are_logged_for_replay(tmp_path):
    import json
    fake = FakeOllama()
    client, _ = make_client(tmp_path, fake)
    client.post("/v1/chat/completions", json=body())
    lines = (tmp_path / "req.jsonl").read_text().strip().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["body"]["meta"]["bot_name"] == "Grimtok"


def test_failed_generation_does_not_start_cooldown(tmp_path):
    class Flaky:
        def __init__(self):
            self.calls = 0

        async def chat(self, messages, tier="inner"):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("ollama down")
            return "Back now, whelp."

    flaky = Flaky()
    client, _ = make_client(tmp_path, flaky, per_bot_cooldown=60.0)
    r1 = client.post("/v1/chat/completions", json=body())
    r2 = client.post("/v1/chat/completions", json=body())
    assert r1.json()["choices"][0]["message"]["content"] == ""
    assert r2.json()["choices"][0]["message"]["content"] == "Back now, whelp."
    assert flaky.calls == 2


GROUP = "Andreas:7:Paladin:60;Grimtok:42:Warrior:60;Zinnia:43:Priest:58"


def command_body(msg="can you tank this dungeon?", bot_guid="42", channel="in party chat"):
    b = body(channel=channel)
    b["messages"][1]["content"] = f"Andreas:{msg}"
    b["meta"]["bot_guid"] = bot_guid
    b["meta"]["group"] = GROUP
    return b


def make_command_client(tmp_path, fake):
    from brain.settings import CommandSettings
    settings = Settings(db_path=":memory:", request_log=str(tmp_path / "req.jsonl"),
                        templates_dir="templates", summarize_after=1000,
                        per_bot_cooldown=0.0, player_guids=["7"],
                        commands=CommandSettings())
    store = MemoryStore(":memory:")
    app = create_app(settings=settings, store=store, ollama=fake)
    return TestClient(app), store


def test_actor_gets_directive_and_ack_context(tmp_path):
    fake = FakeOllama(reply="Fine, I'll keep it busy.",
                      intent_reply='{"verb": "role_tank", "args": {}, "addressed": ""}')
    client, _ = make_command_client(tmp_path, fake)
    r = client.post("/v1/chat/completions", json=command_body()).json()
    assert r["directive"] == {"verb": "role_tank"}
    assert r["choices"][0]["message"]["content"] == "Fine, I'll keep it busy."
    chat_system = [c for c in fake.calls if c[2] is None][0][0][0]["content"]
    assert "switch to tanking" in chat_system


def test_bystander_and_banter_have_no_directive(tmp_path):
    fake = FakeOllama(intent_reply='{"verb": "role_tank", "args": {}, "addressed": ""}')
    client, _ = make_command_client(tmp_path, fake)
    r = client.post("/v1/chat/completions", json=command_body(bot_guid="43")).json()
    assert "directive" not in r
    fake2 = FakeOllama()
    client2, _ = make_command_client(tmp_path, fake2)
    r2 = client2.post("/v1/chat/completions",
                      json=command_body(msg="lovely day in the barrens")).json()
    assert "directive" not in r2
    assert all(c[2] is None for c in fake2.calls)  # pre-filter skipped classifier


def test_refusal_has_no_directive_but_refusal_context(tmp_path):
    fake = FakeOllama(reply="Tank it yourself.",
                      intent_reply='{"verb": "role_tank", "args": {}, "addressed": ""}')
    client, store = make_command_client(tmp_path, fake)
    store.adjust_sentiment(42, 7, -50)
    r = client.post("/v1/chat/completions", json=command_body()).json()
    assert "directive" not in r
    chat_system = [c for c in fake.calls if c[2] is None][0][0][0]["content"]
    assert "refusing" in chat_system
