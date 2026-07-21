"""Sidecar configuration, loaded from an optional config.toml."""
import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path


@dataclass
class CommandSettings:
    enabled: bool = True
    always_obey: bool = False
    sentiment_threshold: float = -25.0
    dedup_window_s: float = 3.0
    actor_ttl_s: float = 45.0
    allow_bot_commanders: bool = True


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
    player_guids: list[str] = field(default_factory=list)
    commands: CommandSettings = field(default_factory=CommandSettings)

    @classmethod
    def load(cls, path: str | Path = "config.toml") -> "Settings":
        p = Path(path)
        if not p.exists():
            return cls()
        data = tomllib.loads(p.read_text())
        commands_data = data.pop("commands", {})
        valid_cmd = {f.name for f in fields(CommandSettings)}
        unknown_cmd = sorted(set(commands_data) - valid_cmd)
        if unknown_cmd:
            raise ValueError(
                f"Unknown key(s) in {p} [commands]: {', '.join(unknown_cmd)} — valid keys: {', '.join(sorted(valid_cmd))}")
        valid = {f.name for f in fields(cls)}
        unknown = sorted(set(data) - valid)
        if unknown:
            raise ValueError(
                f"Unknown key(s) in {p}: {', '.join(unknown)} — valid keys: {', '.join(sorted(valid))}")
        return cls(commands=CommandSettings(**commands_data), **data)
