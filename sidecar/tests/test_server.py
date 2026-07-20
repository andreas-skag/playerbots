from fastapi.testclient import TestClient

from brain.memory import MemoryStore
from brain.server import create_app
from brain.settings import Settings


class FakeOllama:
    def __init__(self, reply="Aye. Deadmines it is, whelp."):
        self.reply = reply
        self.calls = []

    async def chat(self, messages, tier="inner"):
        self.calls.append((messages, tier))
        return self.reply


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
