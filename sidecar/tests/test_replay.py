import json

from brain.memory import MemoryStore
from brain.replay import main
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
