from pathlib import Path

import pytest

from brain.settings import Settings


def test_defaults_when_no_config_file(tmp_path):
    s = Settings.load(tmp_path / "missing.toml")
    assert s.ollama_url == "http://127.0.0.1:11434"
    assert s.chat_model == "mistral-small3.2"
    assert s.utility_model == "qwen3:4b"
    assert s.max_concurrent == 4
    assert s.inner_circle == []


def test_loads_overrides_from_toml(tmp_path):
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        'chat_model = "qwen3:14b"\ninner_circle = ["Grimtok", "Elaria"]\n'
    )
    s = Settings.load(cfg)
    assert s.chat_model == "qwen3:14b"
    assert s.inner_circle == ["Grimtok", "Elaria"]
    assert s.ollama_url == "http://127.0.0.1:11434"  # untouched default


def test_unknown_key_raises_readable_error(tmp_path):
    cfg = tmp_path / "config.toml"
    cfg.write_text('chat_moddel = "typo"\n')
    with pytest.raises(ValueError, match="chat_moddel"):
        Settings.load(cfg)
