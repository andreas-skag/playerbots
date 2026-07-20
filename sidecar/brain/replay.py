"""Replay recorded server requests through the sidecar to iterate on prompts.

Usage (target machine, hits real Ollama):
    .venv/bin/python -m brain.replay requests.jsonl            # last request
    .venv/bin/python -m brain.replay requests.jsonl --index 0  # first request
"""
import argparse
import json
import shutil
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from .settings import Settings


def replay_settings(base: Settings) -> Settings:
    """A sandbox copy of the runtime settings: replays read real memory but
    never mutate production state."""
    scratch = Path(tempfile.mkdtemp(prefix="brain-replay-"))
    db_copy = scratch / "brain.db"
    if Path(base.db_path).exists():
        shutil.copy(base.db_path, db_copy)
    return Settings(
        ollama_url=base.ollama_url,
        chat_model=base.chat_model,
        utility_model=base.utility_model,
        db_path=str(db_copy),
        templates_dir=base.templates_dir,
        inner_circle=list(base.inner_circle),
        max_concurrent=base.max_concurrent,
        per_bot_cooldown=0.0,
        summarize_after=base.summarize_after,
        request_log=str(scratch / "requests.jsonl"),
        player_guids=list(base.player_guids),
        commands=base.commands,
    )


def main(argv: list[str] | None = None, app=None) -> dict:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("logfile")
    parser.add_argument("--index", type=int, default=-1,
                        help="which recorded request to replay (default: last)")
    args = parser.parse_args(argv)

    with open(args.logfile) as f:
        entries = [json.loads(line) for line in f if line.strip()]
    body = entries[args.index]["body"]

    if app is None:
        from .server import create_app
        app = create_app(settings=replay_settings(Settings.load()))

    response = TestClient(app).post("/v1/chat/completions", json=body).json()
    print(json.dumps(response, indent=2, ensure_ascii=False))
    print("directive:", json.dumps(response.get("directive")) if response.get("directive") else "(none)")
    return response


if __name__ == "__main__":
    main()
