import json

from brain.memory import MemoryStore
from brain.replay import main, replay_settings
from brain.server import create_app
from brain.settings import Settings


class FakeOllama:
    async def chat(self, messages, tier="inner"):
        return "replayed reply"


def test_replays_recorded_request(tmp_path, capsys):
    logfile = tmp_path / "req.jsonl"
    body = {"messages": [{"role": "user", "content": "Andreas:hi"}],
            "meta": {"bot_guid": "42", "other_guid": "7", "bot_name": "Grimtok",
                     "other_name": "Andreas", "channel": "in party chat",
                     "event": "chat"}}
    logfile.write_text(json.dumps({"ts": 1, "body": body}) + "\n")

    settings = Settings(db_path=":memory:", request_log=str(tmp_path / "out.jsonl"),
                        templates_dir="templates")
    app = create_app(settings=settings, store=MemoryStore(":memory:"),
                     ollama=FakeOllama())
    result = main([str(logfile)], app=app)
    assert result["choices"][0]["message"]["content"] == "replayed reply"
    assert "replayed reply" in capsys.readouterr().out


def test_replay_settings_sandboxes_state(tmp_path):
    db = tmp_path / "brain.db"
    db.write_bytes(b"")  # existence is enough for the copy branch
    base = Settings(db_path=str(db), request_log=str(tmp_path / "req.jsonl"),
                    per_bot_cooldown=2.0)
    sandbox = replay_settings(base)
    assert sandbox.db_path != base.db_path
    assert sandbox.request_log != base.request_log
    assert sandbox.per_bot_cooldown == 0.0
    assert sandbox.chat_model == base.chat_model
