"""Replay recorded server requests through the sidecar to iterate on prompts.

Usage (target machine, hits real Ollama):
    .venv/bin/python -m brain.replay requests.jsonl            # last request
    .venv/bin/python -m brain.replay requests.jsonl --index 0  # first request
"""
import argparse
import json

from fastapi.testclient import TestClient


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
        app = create_app()

    response = TestClient(app).post("/v1/chat/completions", json=body).json()
    print(json.dumps(response, indent=2, ensure_ascii=False))
    return response


if __name__ == "__main__":
    main()
