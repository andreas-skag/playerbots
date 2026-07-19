"""FastAPI sidecar: the drop-in LLM endpoint the game server talks to."""
import json
import logging
import time

from fastapi import BackgroundTasks, FastAPI, Request
from fastapi.responses import JSONResponse

from . import personas, prompts, summarizer
from .memory import MemoryStore
from .ollama import OllamaClient
from .request_parser import parse_request
from .settings import Settings

log = logging.getLogger(__name__)


def _completion(text: str) -> JSONResponse:
    return JSONResponse(
        {"choices": [{"message": {"role": "assistant", "content": text}}]})


def create_app(settings: Settings | None = None, store: MemoryStore | None = None,
               ollama=None) -> FastAPI:
    settings = settings or Settings.load()
    store = store or MemoryStore(settings.db_path)
    ollama = ollama or OllamaClient(settings)
    app = FastAPI()

    last_generation: dict[int, float] = {}

    @app.post("/v1/chat/completions")
    async def complete(request: Request, background_tasks: BackgroundTasks):
        try:
            body = await request.json()
            with open(settings.request_log, "a") as f:
                f.write(json.dumps({"ts": time.time(), "body": body}) + "\n")

            req = parse_request(body)
            now = time.monotonic()
            if req.bot_guid and now - last_generation.get(req.bot_guid, -1e9) < settings.per_bot_cooldown:
                return _completion("")
            last_generation[req.bot_guid] = now

            inner = personas.is_inner_circle(req, settings)
            persona = personas.get_persona(store, req.bot_guid, req.bot_name)

            if inner and req.bot_guid and req.other_guid:
                recent = store.recent(req.bot_guid, req.other_guid)
                summary, _ = store.summary(req.bot_guid, req.other_guid)
                score = store.sentiment(req.bot_guid, req.other_guid)
            else:
                recent, summary, score = [], "", 0.0

            messages = prompts.assemble(settings.templates_dir, persona, summary,
                                        score, recent, req)
            reply = await ollama.chat(messages, tier="inner" if inner else "ambient")

            if reply and inner and req.bot_guid and req.other_guid:
                store.record_interaction(req.bot_guid, req.other_guid, req.other_name,
                                         req.channel, req.message, reply)
                store.adjust_sentiment(req.bot_guid, req.other_guid, 1)
                background_tasks.add_task(
                    summarizer.maybe_summarize, store, ollama, req.bot_guid,
                    req.other_guid, req.bot_name, req.other_name,
                    settings.summarize_after)

            return _completion(reply)
        except Exception:
            log.exception("request failed; returning empty reply")
            return _completion("")

    return app
