"""Sidecar configuration, loaded from an optional config.toml."""
import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path


@dataclass
class Settings:
    ollama_url: str = "http://127.0.0.1:11434"
    chat_model: str = "mistral-small3.2"
    utility_model: str = "qwen3:4b"
    db_path: str = "brain.db"
    templates_dir: str = "templates"
    inner_circle: list[str] = field(default_factory=list)
    max_concurrent: int = 4
    per_bot_cooldown: float = 2.0
    summarize_after: int = 30
    request_log: str = "requests.jsonl"

    @classmethod
    def load(cls, path: str | Path = "config.toml") -> "Settings":
        p = Path(path)
        if not p.exists():
            return cls()
        data = tomllib.loads(p.read_text())
        valid = {f.name for f in fields(cls)}
        unknown = sorted(set(data) - valid)
        if unknown:
            raise ValueError(
                f"Unknown key(s) in {p}: {', '.join(unknown)} — valid keys: {', '.join(sorted(valid))}")
        return cls(**data)
