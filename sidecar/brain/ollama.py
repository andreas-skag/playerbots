"""Async Ollama client with tier-based model routing and a concurrency cap."""
import asyncio

import httpx

from .settings import Settings


def pick_model(settings: Settings, tier: str) -> str:
    return settings.chat_model if tier == "inner" else settings.utility_model


class OllamaClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._sem = asyncio.Semaphore(settings.max_concurrent)
        self._client = httpx.AsyncClient(base_url=settings.ollama_url, timeout=60.0)

    async def chat(self, messages: list[dict], tier: str = "inner",
                   format: str | None = None) -> str:
        payload = {"model": pick_model(self.settings, tier),
                   "messages": messages, "stream": False}
        if format:
            payload["format"] = format
        async with self._sem:
            resp = await self._client.post("/api/chat", json=payload)
        resp.raise_for_status()
        return resp.json()["message"]["content"].strip()
