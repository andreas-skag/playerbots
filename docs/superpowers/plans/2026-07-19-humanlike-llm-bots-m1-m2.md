# Human-like LLM Bots — M1+M2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Milestone 1 (great LLM chat via config only) and Milestone 2 (Python "brain" sidecar with personas + persistent relationship memory) of the human-like playerbots design.

**Architecture:** The cmangos playerbots module already POSTs configurable JSON (`AiPlayerbot.LLMApiJson`) to a configurable endpoint (`AiPlayerbot.LLMApiEndpoint`) and regex-parses replies. M1 points it directly at Ollama's OpenAI-compatible endpoint with tuned prompts and per-bot character cards. M2 inserts a FastAPI sidecar at that endpoint which enriches prompts with generated personas and SQLite-backed relationship memory before calling Ollama. One 3-line C++ change adds GUID placeholders.

**Tech Stack:** Python 3.11, FastAPI, uvicorn, httpx, SQLite (stdlib `sqlite3`), pytest; Ollama on target machine (RTX 3090); C++ (fork, compiled on target only).

**Spec:** `docs/superpowers/specs/2026-07-19-humanlike-llm-bots-design.md`

## Global Constraints

- **NEVER compile C++ on this machine** (low specs). C++ changes are code-reviewed here, built and verified by Andreas on the target Windows machine. This supersedes the spec's "Linux validation build" testing note for M1–M2.
- All work on branch `feature/humanlike-llm-bots` in `/workspace/playerbots`.
- Git has no global identity here. Task 1 sets repo-local identity; if committing before that, use: `git -c user.name="Andreas Skag" -c user.email="andreas.skag@gmail.com" commit ...`
- Python: `python3` is 3.11.2; create the venv at `sidecar/.venv`; run tests as `cd /workspace/playerbots/sidecar && .venv/bin/pytest`.
- Sidecar responses MUST match the OpenAI chat-completions shape (`{"choices":[{"message":{"content":"..."}}]}`) — the server's `LLMResponseStartPattern = ("content":\s*")` extracts from it.
- Anything Ollama-dependent (real generations, replay against live model) runs on the target machine only; tests here use fakes.
- Character-card file format (parsed by `PlayerbotAIConfig::LoadLLMDefaultPrompts`, `playerbot/PlayerbotAIConfig.cpp:1249`): one `CharacterName:: personality text` per line, `#` starts a comment, name must match an existing character in the characters DB at server start.

---

### Task 1: M1 config pack — Ollama-direct configuration + target-machine README

**Files:**
- Create: `humanlike/README.md`
- Create: `humanlike/conf/m1-ollama-direct.conf.example`

**Interfaces:**
- Produces: conf keys later tasks build on. M2's conf example (Task 12) overrides only `LLMApiEndpoint` and `LLMApiJson` from this file.
- Context placeholders available in `LLMApiJson`/prompts (from `ChatReplyAction::GetAIChatPlaceholders`, `playerbot/strategy/actions/SayAction.cpp:145`): `<bot name>`, `<bot gender>`, `<bot level>`, `<bot class>`, `<bot race>`, `<bot faction>`, `<bot zone>`, `<bot subzone>`, `<bot type>` — same set with `other` prefix — plus `<channel name>`, `<expansion name>`, `<initial message>`, and the meta-placeholders `<pre prompt>`, `<context>`, `<prompt>`, `<post prompt>`.

- [ ] **Step 1: Set repo-local git identity**

```bash
cd /workspace/playerbots
git config user.name "Andreas Skag"
git config user.email "andreas.skag@gmail.com"
```

- [ ] **Step 2: Write the M1 conf example**

Create `humanlike/conf/m1-ollama-direct.conf.example`:

```ini
# ── Milestone 1: LLM chat direct to Ollama ─────────────────────────────
# Paste this block into aiplayerbot.conf on the target machine
# (replacing any existing AiPlayerbot.LLM* lines).

# 2 = 'ai chat' strategy on for all bots by default
AiPlayerbot.LLMEnabled = 2

# Ollama's OpenAI-compatible endpoint
AiPlayerbot.LLMApiEndpoint = http://127.0.0.1:11434/v1/chat/completions
AiPlayerbot.LLMApiKey =

# Request template. <pre prompt>/<context>/<prompt> are filled by the server.
AiPlayerbot.LLMApiJson = {"model":"mistral-small3.2","messages":[{"role":"system","content":"<pre prompt> <context>"},{"role":"user","content":"<prompt>"}],"max_tokens":120,"stream":false}

# Tuned system prompt (single line!)
AiPlayerbot.LLMPrePrompt = You are roleplaying <bot name>, a level <bot level> <bot gender> <bot race> <bot class> in World of Warcraft: <expansion name>, currently in <bot subzone> <bot zone>. The <other type> <other name> (<other gender> <other race> <other class>, level <other level>) speaks to you <channel name>. Stay fully in character. Speak plainly and briefly like a real player: 1-2 short sentences, no modern slang, no emoji, never mention being an AI, do not narrate actions in prose. You may use *asterisks* for a short emote.

AiPlayerbot.LLMPrompt = <other name>:<initial message>
AiPlayerbot.LLMPostPrompt = <bot name>:

# Parse the OpenAI-style response; end/delete/split patterns keep defaults
AiPlayerbot.LLMResponseStartPattern = ("content":\s*")

AiPlayerbot.LLMContextLength = 4096
AiPlayerbot.LLMGenerationTimeout = 60
AiPlayerbot.LLMMaxSimultaniousGenerations = 4

# Occasional bot-to-bot banter (percent chance to reply to another bot)
AiPlayerbot.LLMBotToBotChatChance = 5

# Bots chat with NPCs during rpg behavior
AiPlayerbot.LLMRpgAIChatChance = 20

# Per-bot personality cards (Task 2), file placed next to the server binary
AiPlayerbot.LLMDefaultPromptsFile = llm_character_card.txt
```

- [ ] **Step 3: Write `humanlike/README.md`**

````markdown
# Human-like LLM bots — setup guide

Companion files for the design in
`docs/superpowers/specs/2026-07-19-humanlike-llm-bots-design.md`.
All steps below run on the **target Windows machine** (RTX 3090).

## Milestone 1 — LLM chat direct to Ollama (no code changes)

### 1. Install Ollama and pull models

Install from https://ollama.com/download/windows, then:

```powershell
ollama pull mistral-small3.2   # 24B, ~14 GB VRAM at Q4 — main chat model
ollama pull qwen3:14b          # lighter/faster alternative, worth A/B testing
```

Keep whichever you prefer; put its exact tag in the `"model"` field of
`AiPlayerbot.LLMApiJson`.

### 2. Configure the server

- Open `aiplayerbot.conf` (next to `mangosd.exe`).
- Replace the `AiPlayerbot.LLM*` section with the contents of
  `humanlike/conf/m1-ollama-direct.conf.example`.
- Copy `humanlike/llm_character_card.txt` next to `mangosd.exe` and edit the
  character names to bots that exist on YOUR realm (names must match exactly;
  the server logs how many cards loaded at startup).

### 3. Verify (M1 checklist)

1. Start Ollama (`ollama serve` runs automatically as a service on Windows).
2. Start the server. Startup log should print
   `Loaded N LLM character personalities from llm_character_card.txt`.
3. Log in, stand next to a bot, `/say` hello to it → in-character reply
   within a few seconds.
4. Whisper a bot with a card → reply should reflect its card personality.
5. Party up with a bot, chat in /p → it replies in party chat.
6. Wait near two bots with `LLMBotToBotChatChance` > 0 → occasional banter.
7. Toggle per-bot debugging if replies look wrong: target the bot and
   `/w <bot> co +debug llm` shows prompt/response details in whispers.

Troubleshooting: no reply at all → check `mangosd` console for `BotLLM:`
errors; `curl http://127.0.0.1:11434/v1/chat/completions -d
"{\"model\":\"mistral-small3.2\",\"messages\":[{\"role\":\"user\",\"content\":\"hi\"}]}"`
must return JSON with a `"content"` field.
````

(M2 section is appended by Task 12.)

- [ ] **Step 4: Commit**

```bash
cd /workspace/playerbots
git add humanlike/
git commit -m "feat(m1): Ollama-direct LLM chat config pack and setup guide"
```

---

### Task 2: M1 character cards

**Files:**
- Create: `humanlike/llm_character_card.txt`

**Interfaces:**
- Consumes: file format from `PlayerbotAIConfig::LoadLLMDefaultPrompts` (`playerbot/PlayerbotAIConfig.cpp:1249`): `Name:: text`, `#` comments, name must exist in the characters DB.
- Produces: card text is appended to `LLMPrePrompt` per bot at chat time (via `manual saved string::llmdefaultprompt`, `SayAction.cpp:564`), so cards must be written as system-prompt fragments.

- [ ] **Step 1: Write the card file**

Create `humanlike/llm_character_card.txt`:

```text
# Per-bot personality cards, loaded at server startup.
# Format: CharacterName:: personality text (single line per bot).
# The name MUST match a character on your realm exactly, or the server
# logs "Character 'X' not found" and skips the line.
# The text is appended to the system prompt for that bot only.
# EDIT THE NAMES below to your own bots — these five are examples of the
# style: personality, speech pattern, a quirk, and an attitude hook.
Grimtok:: Personality: gruff orc veteran, terse and dry, secretly softhearted. Speech: short clipped sentences, calls everyone "whelp" affectionately. Quirk: complains his old axe was better than any upgrade. Attitude: respects deeds, not words.
Elaria:: Personality: cheerful night elf herbalist, endlessly curious. Speech: warm, asks questions back, sprinkles in herb lore. Quirk: names every wolf she sees. Attitude: trusts quickly, hurt deeply by rudeness.
Baldrek:: Personality: boastful dwarf tank, loud and loyal. Speech: exclamations, tavern metaphors, laughs at his own jokes. Quirk: rates every dungeon by how good the ale would taste after. Attitude: fiercely protective of party members.
Miravelle:: Personality: haughty human mage, precise and impatient. Speech: formal vocabulary, corrects people, rarely uses contractions. Quirk: refuses to admit when lost. Attitude: warms up only to those who prove competent.
Zenrik:: Personality: laid-back troll rogue, superstitious gambler. Speech: relaxed drawl, "mon" and "ya", fond of odds and omens. Quirk: flips a coin before decisions and blames it after. Attitude: friendly to all, loyal to none... he claims.
```

- [ ] **Step 2: Validate the file format mechanically**

```bash
cd /workspace/playerbots
awk 'NF && $0 !~ /^#/ && $0 !~ /::/' humanlike/llm_character_card.txt
```

Expected: no output (every non-comment, non-empty line contains `::`).

- [ ] **Step 3: Commit**

```bash
git add humanlike/llm_character_card.txt
git commit -m "feat(m1): example per-bot LLM character cards"
```

---

### Task 3: Sidecar scaffold + settings

**Files:**
- Create: `sidecar/pyproject.toml`
- Create: `sidecar/.gitignore`
- Create: `sidecar/brain/__init__.py`
- Create: `sidecar/brain/settings.py`
- Test: `sidecar/tests/test_settings.py`

**Interfaces:**
- Produces: `Settings` dataclass with fields `ollama_url: str`, `chat_model: str`, `utility_model: str`, `db_path: str`, `templates_dir: str`, `inner_circle: list[str]` (character names), `max_concurrent: int`, `per_bot_cooldown: float` (seconds between generations per bot; the per-bot rate cap from the spec), `summarize_after: int`, `request_log: str`; classmethod `Settings.load(path: str | Path = "config.toml") -> Settings`. All later tasks receive a `Settings` instance.

- [ ] **Step 1: Scaffold project and venv**

Create `sidecar/pyproject.toml`:

```toml
[project]
name = "brain"
version = "0.1.0"
description = "Human-like playerbot brain sidecar: personas, memory, prompt assembly"
requires-python = ">=3.11"
dependencies = [
    "fastapi>=0.110",
    "uvicorn>=0.29",
    "httpx>=0.27",
]

[project.optional-dependencies]
dev = ["pytest>=8.0"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

Create `sidecar/.gitignore`:

```text
.venv/
__pycache__/
*.db
requests.jsonl
config.toml
```

Create empty `sidecar/brain/__init__.py`, then:

```bash
cd /workspace/playerbots/sidecar
python3 -m venv .venv
.venv/bin/pip install -q -e ".[dev]"
```

Expected: installs without error.

- [ ] **Step 2: Write the failing test**

Create `sidecar/tests/test_settings.py`:

```python
from pathlib import Path

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
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd /workspace/playerbots/sidecar && .venv/bin/pytest tests/test_settings.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'brain.settings'`

- [ ] **Step 4: Implement settings**

Create `sidecar/brain/settings.py`:

```python
"""Sidecar configuration, loaded from an optional config.toml."""
import tomllib
from dataclasses import dataclass, field
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
        return cls(**tomllib.loads(p.read_text()))
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /workspace/playerbots/sidecar && .venv/bin/pytest -v`
Expected: 2 passed

- [ ] **Step 6: Commit**

```bash
cd /workspace/playerbots
git add sidecar/
git commit -m "feat(m2): sidecar scaffold with Settings loader"
```

---

### Task 4: Request parser

**Files:**
- Create: `sidecar/brain/request_parser.py`
- Test: `sidecar/tests/test_request_parser.py`

**Interfaces:**
- Consumes: the POST body produced by the server's M2 `LLMApiJson` template (Task 12): `{"model": "brain", "messages": [{"role": "system", "content": ...}, {"role": "user", "content": "<other name>:<initial message>"}], "max_tokens": 120, "meta": {"bot_guid": "...", "other_guid": "...", "bot_name": "...", "other_name": "...", "channel": "...", "event": "chat"}}`. Meta values are strings (the server does textual placeholder substitution). M1-style bodies without `meta` must parse too.
- Produces: `BotRequest` dataclass: `system: str`, `speaker_name: str`, `message: str`, `bot_guid: int`, `bot_name: str`, `other_guid: int`, `other_name: str`, `channel: str`, `event: str`; function `parse_request(body: dict) -> BotRequest`.

- [ ] **Step 1: Write the failing test**

Create `sidecar/tests/test_request_parser.py`:

```python
from brain.request_parser import parse_request


def full_body():
    return {
        "model": "brain",
        "messages": [
            {"role": "system", "content": "You are Grimtok, an orc warrior."},
            {"role": "user", "content": "Andreas:hey, ready for Deadmines?"},
        ],
        "max_tokens": 120,
        "meta": {
            "bot_guid": "42",
            "other_guid": "7",
            "bot_name": "Grimtok",
            "other_name": "Andreas",
            "channel": "in party chat",
            "event": "chat",
        },
    }


def test_parses_full_m2_body():
    req = parse_request(full_body())
    assert req.bot_guid == 42
    assert req.other_guid == 7
    assert req.bot_name == "Grimtok"
    assert req.other_name == "Andreas"
    assert req.channel == "in party chat"
    assert req.event == "chat"
    assert req.speaker_name == "Andreas"
    assert req.message == "hey, ready for Deadmines?"
    assert "orc warrior" in req.system


def test_message_may_contain_colons():
    body = full_body()
    body["messages"][1]["content"] = "Andreas:meet at 10:30, ok?"
    req = parse_request(body)
    assert req.message == "meet at 10:30, ok?"


def test_tolerates_missing_meta():
    body = full_body()
    del body["meta"]
    req = parse_request(body)
    assert req.bot_guid == 0
    assert req.other_guid == 0
    assert req.speaker_name == "Andreas"
    assert req.event == "chat"


def test_tolerates_junk_guid():
    body = full_body()
    body["meta"]["bot_guid"] = "<bot guid>"  # unsubstituted placeholder
    req = parse_request(body)
    assert req.bot_guid == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /workspace/playerbots/sidecar && .venv/bin/pytest tests/test_request_parser.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'brain.request_parser'`

- [ ] **Step 3: Implement the parser**

Create `sidecar/brain/request_parser.py`:

```python
"""Parse the game server's LLMApiJson POST body into a BotRequest."""
from dataclasses import dataclass


@dataclass
class BotRequest:
    system: str
    speaker_name: str
    message: str
    bot_guid: int
    bot_name: str
    other_guid: int
    other_name: str
    channel: str
    event: str


def _to_int(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def parse_request(body: dict) -> BotRequest:
    system = ""
    user = ""
    for m in body.get("messages", []):
        if m.get("role") == "system":
            system = m.get("content", "")
        elif m.get("role") == "user":
            user = m.get("content", "")

    speaker, sep, message = user.partition(":")
    if not sep:
        speaker, message = "", user

    meta = body.get("meta") or {}
    return BotRequest(
        system=system,
        speaker_name=meta.get("other_name") or speaker,
        message=message,
        bot_guid=_to_int(meta.get("bot_guid")),
        bot_name=meta.get("bot_name", ""),
        other_guid=_to_int(meta.get("other_guid")),
        other_name=meta.get("other_name") or speaker,
        channel=meta.get("channel", ""),
        event=meta.get("event", "chat"),
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /workspace/playerbots/sidecar && .venv/bin/pytest -v`
Expected: all passed (settings + parser)

- [ ] **Step 5: Commit**

```bash
cd /workspace/playerbots
git add sidecar/
git commit -m "feat(m2): parse server LLM requests into BotRequest"
```

---

### Task 5: Memory store (SQLite)

**Files:**
- Create: `sidecar/brain/memory.py`
- Test: `sidecar/tests/test_memory.py`

**Interfaces:**
- Produces: `MemoryStore(path: str = ":memory:")` with methods:
  - `record_interaction(bot_guid: int, other_guid: int, other_name: str, channel: str, message: str, reply: str) -> int` (returns row id)
  - `recent(bot_guid: int, other_guid: int, limit: int = 8) -> list[tuple[str, str]]` — (message, reply) pairs, oldest→newest
  - `sentiment(bot_guid: int, other_guid: int) -> float`
  - `adjust_sentiment(bot_guid: int, other_guid: int, delta: float) -> float` — returns new score, clamped to [-100, 100]
  - `summary(bot_guid: int, other_guid: int) -> tuple[str, int]` — (text, last_summarized_id); `("", 0)` if none
  - `set_summary(bot_guid: int, other_guid: int, text: str, last_id: int) -> None`
  - `unsummarized(bot_guid: int, other_guid: int) -> list[tuple[int, str, str]]` — (id, message, reply) after last summarized id
  - `get_persona(bot_guid: int) -> str | None` / `set_persona(bot_guid: int, card: str) -> None`
- Uses `check_same_thread=False` so FastAPI worker threads can share it.

- [ ] **Step 1: Write the failing test**

Create `sidecar/tests/test_memory.py`:

```python
from brain.memory import MemoryStore


def make_store():
    return MemoryStore(":memory:")


def test_record_and_recent_ordering():
    s = make_store()
    s.record_interaction(42, 7, "Andreas", "in party chat", "hi", "Hrm. Whelp.")
    s.record_interaction(42, 7, "Andreas", "in party chat", "ready?", "Aye.")
    assert s.recent(42, 7) == [("hi", "Hrm. Whelp."), ("ready?", "Aye.")]
    assert s.recent(42, 99) == []  # other pair untouched


def test_recent_respects_limit():
    s = make_store()
    for i in range(10):
        s.record_interaction(42, 7, "Andreas", "say", f"m{i}", f"r{i}")
    got = s.recent(42, 7, limit=3)
    assert got == [("m7", "r7"), ("m8", "r8"), ("m9", "r9")]


def test_sentiment_defaults_zero_and_clamps():
    s = make_store()
    assert s.sentiment(42, 7) == 0
    assert s.adjust_sentiment(42, 7, 5) == 5
    assert s.adjust_sentiment(42, 7, 1000) == 100
    assert s.adjust_sentiment(42, 7, -1000) == -100


def test_summary_roundtrip_and_unsummarized():
    s = make_store()
    i1 = s.record_interaction(42, 7, "Andreas", "say", "a", "b")
    i2 = s.record_interaction(42, 7, "Andreas", "say", "c", "d")
    assert s.summary(42, 7) == ("", 0)
    assert [r[0] for r in s.unsummarized(42, 7)] == [i1, i2]
    s.set_summary(42, 7, "They ran Deadmines together.", i1)
    assert s.summary(42, 7) == ("They ran Deadmines together.", i1)
    assert [r[0] for r in s.unsummarized(42, 7)] == [i2]


def test_persona_roundtrip():
    s = make_store()
    assert s.get_persona(42) is None
    s.set_persona(42, "gruff veteran")
    assert s.get_persona(42) == "gruff veteran"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /workspace/playerbots/sidecar && .venv/bin/pytest tests/test_memory.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'brain.memory'`

- [ ] **Step 3: Implement the store**

Create `sidecar/brain/memory.py`:

```python
"""SQLite-backed relationship memory: interactions, sentiment, summaries, personas."""
import sqlite3
import time

_SCHEMA = """
CREATE TABLE IF NOT EXISTS interactions(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bot_guid INTEGER NOT NULL,
    other_guid INTEGER NOT NULL,
    other_name TEXT NOT NULL,
    channel TEXT NOT NULL,
    message TEXT NOT NULL,
    reply TEXT NOT NULL,
    ts REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_interactions_pair ON interactions(bot_guid, other_guid, id);
CREATE TABLE IF NOT EXISTS sentiment(
    bot_guid INTEGER NOT NULL,
    other_guid INTEGER NOT NULL,
    score REAL NOT NULL DEFAULT 0,
    PRIMARY KEY(bot_guid, other_guid)
);
CREATE TABLE IF NOT EXISTS summaries(
    bot_guid INTEGER NOT NULL,
    other_guid INTEGER NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    last_id INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY(bot_guid, other_guid)
);
CREATE TABLE IF NOT EXISTS personas(
    bot_guid INTEGER PRIMARY KEY,
    card TEXT NOT NULL
);
"""


class MemoryStore:
    def __init__(self, path: str = ":memory:"):
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.executescript(_SCHEMA)
        self.conn.commit()

    def record_interaction(self, bot_guid: int, other_guid: int, other_name: str,
                           channel: str, message: str, reply: str) -> int:
        cur = self.conn.execute(
            "INSERT INTO interactions(bot_guid, other_guid, other_name, channel, message, reply, ts)"
            " VALUES(?,?,?,?,?,?,?)",
            (bot_guid, other_guid, other_name, channel, message, reply, time.time()))
        self.conn.commit()
        return cur.lastrowid

    def recent(self, bot_guid: int, other_guid: int, limit: int = 8) -> list[tuple[str, str]]:
        rows = self.conn.execute(
            "SELECT message, reply FROM interactions WHERE bot_guid=? AND other_guid=?"
            " ORDER BY id DESC LIMIT ?", (bot_guid, other_guid, limit)).fetchall()
        return list(reversed(rows))

    def sentiment(self, bot_guid: int, other_guid: int) -> float:
        row = self.conn.execute(
            "SELECT score FROM sentiment WHERE bot_guid=? AND other_guid=?",
            (bot_guid, other_guid)).fetchone()
        return row[0] if row else 0.0

    def adjust_sentiment(self, bot_guid: int, other_guid: int, delta: float) -> float:
        new = max(-100.0, min(100.0, self.sentiment(bot_guid, other_guid) + delta))
        self.conn.execute(
            "INSERT INTO sentiment(bot_guid, other_guid, score) VALUES(?,?,?)"
            " ON CONFLICT(bot_guid, other_guid) DO UPDATE SET score=excluded.score",
            (bot_guid, other_guid, new))
        self.conn.commit()
        return new

    def summary(self, bot_guid: int, other_guid: int) -> tuple[str, int]:
        row = self.conn.execute(
            "SELECT summary, last_id FROM summaries WHERE bot_guid=? AND other_guid=?",
            (bot_guid, other_guid)).fetchone()
        return (row[0], row[1]) if row else ("", 0)

    def set_summary(self, bot_guid: int, other_guid: int, text: str, last_id: int) -> None:
        self.conn.execute(
            "INSERT INTO summaries(bot_guid, other_guid, summary, last_id) VALUES(?,?,?,?)"
            " ON CONFLICT(bot_guid, other_guid) DO UPDATE SET summary=excluded.summary,"
            " last_id=excluded.last_id",
            (bot_guid, other_guid, text, last_id))
        self.conn.commit()

    def unsummarized(self, bot_guid: int, other_guid: int) -> list[tuple[int, str, str]]:
        _, last_id = self.summary(bot_guid, other_guid)
        return self.conn.execute(
            "SELECT id, message, reply FROM interactions"
            " WHERE bot_guid=? AND other_guid=? AND id>? ORDER BY id",
            (bot_guid, other_guid, last_id)).fetchall()

    def get_persona(self, bot_guid: int) -> str | None:
        row = self.conn.execute(
            "SELECT card FROM personas WHERE bot_guid=?", (bot_guid,)).fetchone()
        return row[0] if row else None

    def set_persona(self, bot_guid: int, card: str) -> None:
        self.conn.execute(
            "INSERT INTO personas(bot_guid, card) VALUES(?,?)"
            " ON CONFLICT(bot_guid) DO UPDATE SET card=excluded.card",
            (bot_guid, card))
        self.conn.commit()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /workspace/playerbots/sidecar && .venv/bin/pytest -v`
Expected: all passed

- [ ] **Step 5: Commit**

```bash
cd /workspace/playerbots
git add sidecar/
git commit -m "feat(m2): SQLite memory store for interactions, sentiment, summaries, personas"
```

---

### Task 6: Persona generation + inner-circle tiering

**Files:**
- Create: `sidecar/brain/personas.py`
- Test: `sidecar/tests/test_personas.py`

**Interfaces:**
- Consumes: `MemoryStore.get_persona` / `set_persona` (Task 5); `BotRequest` (Task 4); `Settings.inner_circle` (Task 3).
- Produces:
  - `generate_card(bot_guid: int, bot_name: str) -> str` — deterministic from guid (falls back to name hash when guid is 0)
  - `get_persona(store: MemoryStore, bot_guid: int, bot_name: str) -> str` — cached in DB
  - `is_inner_circle(req: BotRequest, settings: Settings) -> bool` — True for party/raid/guild/whisper channels or names listed in `settings.inner_circle` (spec: group/guild membership per request + static config list; channel is our proxy for membership in M2)

- [ ] **Step 1: Write the failing test**

Create `sidecar/tests/test_personas.py`:

```python
from brain.memory import MemoryStore
from brain.personas import generate_card, get_persona, is_inner_circle
from brain.request_parser import BotRequest
from brain.settings import Settings


def req(channel="in world chat", bot_name="Grimtok"):
    return BotRequest(system="", speaker_name="Andreas", message="hi",
                      bot_guid=42, bot_name=bot_name, other_guid=7,
                      other_name="Andreas", channel=channel, event="chat")


def test_card_is_deterministic_and_varied():
    assert generate_card(42, "Grimtok") == generate_card(42, "Grimtok")
    # different guids must not all collapse to one card
    assert any(generate_card(42, "Grimtok") != generate_card(g, "Elaria")
               for g in range(43, 48))
    card = generate_card(42, "Grimtok")
    assert "Personality:" in card and "Speech:" in card


def test_zero_guid_falls_back_to_name():
    assert generate_card(0, "Grimtok") == generate_card(0, "Grimtok")
    assert any(generate_card(0, "Grimtok") != generate_card(0, n)
               for n in ("Elaria", "Baldrek", "Miravelle"))


def test_get_persona_caches_in_store():
    store = MemoryStore(":memory:")
    card = get_persona(store, 42, "Grimtok")
    assert store.get_persona(42) == card
    store.set_persona(42, "hand-written card")
    assert get_persona(store, 42, "Grimtok") == "hand-written card"


def test_inner_circle_by_channel_and_list():
    s = Settings()
    assert is_inner_circle(req(channel="in party chat"), s)
    assert is_inner_circle(req(channel="in guild chat"), s)
    assert is_inner_circle(req(channel="in private message"), s)
    assert not is_inner_circle(req(channel="in world chat"), s)
    s2 = Settings(inner_circle=["Grimtok"])
    assert is_inner_circle(req(channel="in world chat", bot_name="Grimtok"), s2)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /workspace/playerbots/sidecar && .venv/bin/pytest tests/test_personas.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'brain.personas'`

- [ ] **Step 3: Implement personas**

Create `sidecar/brain/personas.py`:

```python
"""Deterministic persona cards and inner-circle tiering."""
import random
import zlib

from .memory import MemoryStore
from .request_parser import BotRequest
from .settings import Settings

_ARCHETYPES = [
    "gruff veteran, terse and dry, secretly softhearted",
    "cheerful optimist, endlessly curious about everything",
    "boastful show-off, loud, loyal to a fault",
    "haughty perfectionist, precise, slow to warm up",
    "laid-back drifter, superstitious, jokes under pressure",
    "nervous newcomer, eager to please, easily startled",
    "scheming merchant at heart, always angling for profit",
    "stoic protector, few words, watches everyone's back",
]
_SPEECH = [
    "short clipped sentences, no pleasantries",
    "warm and chatty, asks questions back",
    "exclamations and tavern metaphors",
    "formal vocabulary, rarely uses contractions",
    "relaxed drawl, fond of odds and omens",
    "rambling, trails off mid-thought sometimes",
]
_QUIRKS = [
    "complains that old gear was better than any upgrade",
    "names every animal they come across",
    "rates every place by how good the ale would taste there",
    "refuses to admit being lost or wrong",
    "flips a coin before decisions and blames it after",
    "collects rumors and repeats them as fact",
]
_ATTITUDES = [
    "respects deeds, not words",
    "trusts quickly, hurt deeply by rudeness",
    "fiercely protective of companions",
    "warms only to those who prove competent",
    "friendly to all, loyal to none... they claim",
    "keeps score of every favor owed",
]

_INNER_CHANNELS = {"in party chat", "in raid chat", "in guild chat", "in private message"}


def generate_card(bot_guid: int, bot_name: str) -> str:
    seed = bot_guid or zlib.crc32(bot_name.encode())
    rng = random.Random(seed)
    return (f"Personality: {rng.choice(_ARCHETYPES)}. "
            f"Speech: {rng.choice(_SPEECH)}. "
            f"Quirk: {rng.choice(_QUIRKS)}. "
            f"Attitude: {rng.choice(_ATTITUDES)}.")


def get_persona(store: MemoryStore, bot_guid: int, bot_name: str) -> str:
    card = store.get_persona(bot_guid)
    if card is None:
        card = generate_card(bot_guid, bot_name)
        store.set_persona(bot_guid, card)
    return card


def is_inner_circle(req: BotRequest, settings: Settings) -> bool:
    return req.channel in _INNER_CHANNELS or req.bot_name in settings.inner_circle
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /workspace/playerbots/sidecar && .venv/bin/pytest -v`
Expected: all passed

- [ ] **Step 5: Commit**

```bash
cd /workspace/playerbots
git add sidecar/
git commit -m "feat(m2): deterministic persona cards and inner-circle tiering"
```

---

### Task 7: Prompt assembler with hot-reloadable template

**Files:**
- Create: `sidecar/brain/prompts.py`
- Create: `sidecar/templates/chat.txt`
- Test: `sidecar/tests/test_prompts.py`

**Interfaces:**
- Consumes: `BotRequest` (Task 4).
- Produces:
  - `describe_sentiment(score: float) -> str`
  - `assemble(templates_dir: str | Path, persona: str, summary: str, score: float, recent: list[tuple[str, str]], req: BotRequest) -> list[dict]` — OpenAI-style messages `[{"role": "system", ...}, {"role": "user", ...}]`. The template file is re-read on every call (hot-reload by design; it's tiny).
- Template placeholders (Python `str.format` fields): `{game_system}`, `{persona}`, `{relationship}`, `{summary}`, `{history}`, `{bot_name}`, `{other_name}`.

- [ ] **Step 1: Write the template**

Create `sidecar/templates/chat.txt`:

```text
{game_system}

Your persona: {persona}

Your relationship with {other_name}: you consider them {relationship}.
What you remember about them: {summary}

Recent conversation:
{history}

Reply as {bot_name} in one or two short sentences, in character, consistent
with your persona, relationship and memories. Never mention being an AI.
```

- [ ] **Step 2: Write the failing test**

Create `sidecar/tests/test_prompts.py`:

```python
from brain.prompts import assemble, describe_sentiment
from brain.request_parser import BotRequest


def req():
    return BotRequest(system="You are Grimtok in Westfall.", speaker_name="Andreas",
                      message="ready for Deadmines?", bot_guid=42, bot_name="Grimtok",
                      other_guid=7, other_name="Andreas", channel="in party chat",
                      event="chat")


def test_describe_sentiment_bands():
    assert describe_sentiment(80) == "a close friend"
    assert describe_sentiment(30) == "a friend"
    assert describe_sentiment(10) == "a friendly acquaintance"
    assert describe_sentiment(0) == "a stranger"
    assert describe_sentiment(-10) == "someone you are wary of"
    assert describe_sentiment(-50) == "someone you dislike"


def test_assemble_builds_system_and_user(tmp_path):
    tpl = tmp_path / "chat.txt"
    tpl.write_text("{game_system}|{persona}|{relationship}|{summary}|{history}|{bot_name}|{other_name}")
    msgs = assemble(tmp_path, "gruff veteran", "Ran Deadmines once.", 30,
                    [("hi", "Hrm."), ("ready?", "Aye.")], req())
    assert msgs[0]["role"] == "system"
    sys = msgs[0]["content"]
    assert "You are Grimtok in Westfall." in sys
    assert "gruff veteran" in sys
    assert "a friend" in sys
    assert "Ran Deadmines once." in sys
    assert "Andreas: hi" in sys and "Grimtok: Hrm." in sys
    assert msgs[1] == {"role": "user", "content": "Andreas: ready for Deadmines?"}


def test_assemble_handles_empty_memory(tmp_path):
    tpl = tmp_path / "chat.txt"
    tpl.write_text("{summary}|{history}")
    msgs = assemble(tmp_path, "p", "", 0, [], req())
    assert "no shared history yet" in msgs[0]["content"]
    assert "(none)" in msgs[0]["content"]
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd /workspace/playerbots/sidecar && .venv/bin/pytest tests/test_prompts.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'brain.prompts'`

- [ ] **Step 4: Implement the assembler**

Create `sidecar/brain/prompts.py`:

```python
"""Assemble chat prompts from persona, memory and the incoming request."""
from pathlib import Path

from .request_parser import BotRequest


def describe_sentiment(score: float) -> str:
    if score >= 60:
        return "a close friend"
    if score >= 25:
        return "a friend"
    if score >= 5:
        return "a friendly acquaintance"
    if score > -5:
        return "a stranger"
    if score > -25:
        return "someone you are wary of"
    return "someone you dislike"


def assemble(templates_dir: str | Path, persona: str, summary: str, score: float,
             recent: list[tuple[str, str]], req: BotRequest) -> list[dict]:
    template = (Path(templates_dir) / "chat.txt").read_text()
    history = "\n".join(
        f"{req.other_name}: {msg}\n{req.bot_name}: {reply}" for msg, reply in recent
    ) or "(none)"
    system = template.format(
        game_system=req.system,
        persona=persona,
        relationship=describe_sentiment(score),
        summary=summary or "no shared history yet",
        history=history,
        bot_name=req.bot_name,
        other_name=req.other_name,
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": f"{req.speaker_name}: {req.message}"},
    ]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /workspace/playerbots/sidecar && .venv/bin/pytest -v`
Expected: all passed

- [ ] **Step 6: Commit**

```bash
cd /workspace/playerbots
git add sidecar/
git commit -m "feat(m2): prompt assembler with hot-reloadable chat template"
```

---

### Task 8: Ollama client with model routing and concurrency cap

**Files:**
- Create: `sidecar/brain/ollama.py`
- Test: `sidecar/tests/test_ollama.py`

**Interfaces:**
- Consumes: `Settings` (Task 3).
- Produces:
  - `pick_model(settings: Settings, tier: str) -> str` — `"inner"` → `settings.chat_model`, anything else → `settings.utility_model`
  - `class OllamaClient(settings: Settings)` with `async chat(messages: list[dict], tier: str = "inner") -> str` — POSTs Ollama native `/api/chat` (`{"model", "messages", "stream": False}`), returns `resp["message"]["content"].strip()`; global `asyncio.Semaphore(settings.max_concurrent)` limits concurrent generations. Raises on HTTP error (caller handles).
- Note: the FastAPI integration test (Task 10) covers the async path with a fake; here we unit-test only the pure routing function. Real-network behavior is verified on the target machine.

- [ ] **Step 1: Write the failing test**

Create `sidecar/tests/test_ollama.py`:

```python
from brain.ollama import pick_model
from brain.settings import Settings


def test_pick_model_routes_by_tier():
    s = Settings(chat_model="big", utility_model="small")
    assert pick_model(s, "inner") == "big"
    assert pick_model(s, "ambient") == "small"
    assert pick_model(s, "utility") == "small"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /workspace/playerbots/sidecar && .venv/bin/pytest tests/test_ollama.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'brain.ollama'`

- [ ] **Step 3: Implement the client**

Create `sidecar/brain/ollama.py`:

```python
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

    async def chat(self, messages: list[dict], tier: str = "inner") -> str:
        payload = {"model": pick_model(self.settings, tier),
                   "messages": messages, "stream": False}
        async with self._sem:
            resp = await self._client.post("/api/chat", json=payload)
        resp.raise_for_status()
        return resp.json()["message"]["content"].strip()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /workspace/playerbots/sidecar && .venv/bin/pytest -v`
Expected: all passed

- [ ] **Step 5: Commit**

```bash
cd /workspace/playerbots
git add sidecar/
git commit -m "feat(m2): Ollama client with model routing and concurrency cap"
```

---

### Task 9: Summarizer (memory compression + sentiment drift)

**Files:**
- Create: `sidecar/brain/summarizer.py`
- Test: `sidecar/tests/test_summarizer.py`

**Interfaces:**
- Consumes: `MemoryStore` (Task 5); an object with `async chat(messages, tier) -> str` (Task 8's `OllamaClient` or a fake).
- Produces:
  - `extract_json(text: str) -> dict` — tolerant: returns the first parseable `{...}` block in the text, else `{}`
  - `async maybe_summarize(store, ollama, bot_guid: int, other_guid: int, bot_name: str, other_name: str, threshold: int) -> bool` — when `len(unsummarized) >= threshold`, asks the utility model for `{"summary": ..., "sentiment_delta": ...}` covering old summary + unsummarized lines, stores the new summary, applies `sentiment_delta` clamped to [-5, 5]. Returns True if it summarized. Any exception is swallowed (memory compression must never break chat).

- [ ] **Step 1: Write the failing test**

Create `sidecar/tests/test_summarizer.py`:

```python
import asyncio

from brain.memory import MemoryStore
from brain.summarizer import extract_json, maybe_summarize


class FakeOllama:
    def __init__(self, reply):
        self.reply = reply
        self.calls = []

    async def chat(self, messages, tier="inner"):
        self.calls.append((messages, tier))
        return self.reply


def test_extract_json_tolerates_chatter():
    assert extract_json('Sure! {"summary": "s", "sentiment_delta": 2} done') == \
        {"summary": "s", "sentiment_delta": 2}
    assert extract_json("no json here") == {}


def seeded_store(n):
    store = MemoryStore(":memory:")
    for i in range(n):
        store.record_interaction(42, 7, "Andreas", "say", f"m{i}", f"r{i}")
    return store


def test_below_threshold_does_nothing():
    store = seeded_store(2)
    fake = FakeOllama('{"summary": "x", "sentiment_delta": 0}')
    assert asyncio.run(maybe_summarize(store, fake, 42, 7, "Grimtok", "Andreas", 3)) is False
    assert fake.calls == []


def test_summarizes_and_applies_clamped_delta():
    store = seeded_store(3)
    fake = FakeOllama('{"summary": "They quested in Westfall.", "sentiment_delta": 40}')
    assert asyncio.run(maybe_summarize(store, fake, 42, 7, "Grimtok", "Andreas", 3)) is True
    text, last_id = store.summary(42, 7)
    assert text == "They quested in Westfall."
    assert last_id == 3
    assert store.unsummarized(42, 7) == []
    assert store.sentiment(42, 7) == 5  # 40 clamped to +5
    assert fake.calls[0][1] == "utility"


def test_swallows_bad_llm_output():
    store = seeded_store(3)
    fake = FakeOllama("total nonsense")
    assert asyncio.run(maybe_summarize(store, fake, 42, 7, "Grimtok", "Andreas", 3)) is False
    assert store.summary(42, 7) == ("", 0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /workspace/playerbots/sidecar && .venv/bin/pytest tests/test_summarizer.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'brain.summarizer'`

- [ ] **Step 3: Implement the summarizer**

Create `sidecar/brain/summarizer.py`:

```python
"""Compress old interactions into a summary and drift sentiment accordingly."""
import json
import logging
import re

from .memory import MemoryStore

log = logging.getLogger(__name__)

_PROMPT = """You maintain the memory of {bot_name}, a World of Warcraft character,
about the player {other_name}.

Current memory: {old_summary}

New conversations (player line, then {bot_name}'s reply):
{lines}

Reply with ONLY a JSON object:
{{"summary": "<max 60 words, third person, merge current memory with the new events, keep the most personal or emotionally notable details>",
"sentiment_delta": <integer -5..5, how these conversations should shift {bot_name}'s feelings toward {other_name}>}}"""


def extract_json(text: str) -> dict:
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return {}
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return {}


async def maybe_summarize(store: MemoryStore, ollama, bot_guid: int, other_guid: int,
                          bot_name: str, other_name: str, threshold: int) -> bool:
    try:
        rows = store.unsummarized(bot_guid, other_guid)
        if len(rows) < threshold:
            return False
        old_summary, _ = store.summary(bot_guid, other_guid)
        lines = "\n".join(f"{other_name}: {m}\n{bot_name}: {r}" for _, m, r in rows)
        reply = await ollama.chat(
            [{"role": "user", "content": _PROMPT.format(
                bot_name=bot_name, other_name=other_name,
                old_summary=old_summary or "(none yet)", lines=lines)}],
            tier="utility")
        data = extract_json(reply)
        summary = data.get("summary")
        if not summary:
            return False
        store.set_summary(bot_guid, other_guid, summary, rows[-1][0])
        try:
            delta = max(-5.0, min(5.0, float(data.get("sentiment_delta", 0))))
        except (TypeError, ValueError):
            delta = 0.0
        if delta:
            store.adjust_sentiment(bot_guid, other_guid, delta)
        return True
    except Exception:
        log.exception("summarize failed for bot=%s other=%s", bot_guid, other_guid)
        return False
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /workspace/playerbots/sidecar && .venv/bin/pytest -v`
Expected: all passed

- [ ] **Step 5: Commit**

```bash
cd /workspace/playerbots
git add sidecar/
git commit -m "feat(m2): interaction summarizer with sentiment drift"
```

---

### Task 10: FastAPI server — wire everything together

**Files:**
- Create: `sidecar/brain/server.py`
- Test: `sidecar/tests/test_server.py`

**Interfaces:**
- Consumes: everything above — `Settings.load`, `MemoryStore`, `parse_request`, `personas.get_persona`/`is_inner_circle`, `prompts.assemble`, `OllamaClient.chat`, `summarizer.maybe_summarize`.
- Produces:
  - `create_app(settings: Settings | None = None, store: MemoryStore | None = None, ollama=None) -> FastAPI` — dependency injection for tests; defaults built from `Settings.load()`. Run in production with `uvicorn --factory brain.server:create_app --host 127.0.0.1 --port 8085`.
  - Route `POST /v1/chat/completions` returning `{"choices":[{"message":{"role":"assistant","content": <reply>}}]}`. On ANY internal error: same shape with `"content": ""` (bot stays silent; server must never see a 5xx surprise shape).
  - Every request body is appended to `settings.request_log` as one JSON line `{"ts": ..., "body": ...}` (replay input, Task 11).
  - Per-bot rate cap: if the same `bot_guid` generated less than `settings.per_bot_cooldown` seconds ago, return empty content without calling Ollama (bot stays silent — indistinguishable from choosing not to reply).
  - Flow: parse → per-bot cooldown check → tier → persona → (inner only) load recent/summary/sentiment → assemble → generate → (inner + both guids known) record interaction, `adjust_sentiment(+1)`, schedule `maybe_summarize` as a FastAPI background task.

- [ ] **Step 1: Write the failing test**

Create `sidecar/tests/test_server.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /workspace/playerbots/sidecar && .venv/bin/pytest tests/test_server.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'brain.server'`

- [ ] **Step 3: Implement the server**

Create `sidecar/brain/server.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /workspace/playerbots/sidecar && .venv/bin/pytest -v`
Expected: all passed (entire suite)

- [ ] **Step 5: Commit**

```bash
cd /workspace/playerbots
git add sidecar/
git commit -m "feat(m2): FastAPI sidecar endpoint wiring personas, memory and Ollama"
```

---

### Task 11: Replay CLI

**Files:**
- Create: `sidecar/brain/replay.py`
- Test: `sidecar/tests/test_replay.py`

**Interfaces:**
- Consumes: the `requests.jsonl` format written by Task 10 (`{"ts": ..., "body": ...}` per line); `create_app` (Task 10).
- Produces: `python -m brain.replay <logfile> [--index N]` — re-sends the Nth recorded request (default: last) through a fresh app and prints the JSON response. On the target machine this hits real Ollama — the prompt-iteration loop: edit `templates/chat.txt`, replay, read the reply, repeat. `main(argv: list[str] | None = None, app=None) -> dict` is importable for tests (injected `app` skips real Ollama).

- [ ] **Step 1: Write the failing test**

Create `sidecar/tests/test_replay.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /workspace/playerbots/sidecar && .venv/bin/pytest tests/test_replay.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'brain.replay'`

- [ ] **Step 3: Implement the CLI**

Create `sidecar/brain/replay.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /workspace/playerbots/sidecar && .venv/bin/pytest -v`
Expected: all passed

- [ ] **Step 5: Commit**

```bash
cd /workspace/playerbots
git add sidecar/
git commit -m "feat(m2): replay CLI for prompt iteration against recorded requests"
```

---

### Task 12: C++ GUID placeholders + M2 config + target-machine docs

**Files:**
- Modify: `playerbot/strategy/actions/SayAction.cpp` (function `ChatReplyAction::GetAIChatPlaceholders(std::map<std::string, std::string>&, Unit*, const std::string, Player*)`, starts at line 145)
- Create: `humanlike/conf/m2-sidecar.conf.example`
- Create: `sidecar/config.example.toml`
- Modify: `humanlike/README.md` (append M2 section)

**Interfaces:**
- Produces: new placeholders `<bot guid>` and `<other guid>` (low GUID / character DB id, matching what M2's `LLMApiJson` meta block and the sidecar's `bot_guid`/`other_guid` expect). Same prefix mechanism as the existing `<bot name>` etc., so the RPG-chat path's `unit` prefix gains `<unit guid>` for free (harmless, useful for M4+).
- **DO NOT COMPILE** — code change is reviewed here, built on the target machine.

- [ ] **Step 1: Add the placeholder in C++**

In `playerbot/strategy/actions/SayAction.cpp`, in the prefix overload of `GetAIChatPlaceholders` (line ~145), directly after:

```cpp
    placeholders["<" + preFix + " name>"] = unit->GetName();
```

add:

```cpp
    placeholders["<" + preFix + " guid>"] = std::to_string(unit->GetObjectGuid().GetCounter());
```

- [ ] **Step 2: Review the diff (no compile)**

Run: `cd /workspace/playerbots && git diff playerbot/strategy/actions/SayAction.cpp`
Expected: exactly one added line; `GetObjectGuid()` is available on `Unit` via `Object`, and `GetCounter()` returns the low guid used as `characters.guid`.

- [ ] **Step 3: Write the M2 conf example**

Create `humanlike/conf/m2-sidecar.conf.example`:

```ini
# ── Milestone 2: LLM chat through the brain sidecar ────────────────────
# Same as m1-ollama-direct.conf.example EXCEPT these two keys.
# Requires the sidecar running: see humanlike/README.md, "Milestone 2".

AiPlayerbot.LLMApiEndpoint = http://127.0.0.1:8085/v1/chat/completions

# The extra "meta" object is read by the sidecar (guids key the memory DB)
# and ignored by ordinary OpenAI-compatible endpoints.
AiPlayerbot.LLMApiJson = {"model":"brain","messages":[{"role":"system","content":"<pre prompt> <context>"},{"role":"user","content":"<prompt>"}],"max_tokens":120,"meta":{"bot_guid":"<bot guid>","other_guid":"<other guid>","bot_name":"<bot name>","other_name":"<other name>","channel":"<channel name>","event":"chat"}}
```

- [ ] **Step 4: Write the sidecar config example**

Create `sidecar/config.example.toml`:

```toml
# Copy to sidecar/config.toml on the target machine and adjust.
ollama_url = "http://127.0.0.1:11434"
chat_model = "mistral-small3.2"   # inner-circle bots
utility_model = "qwen3:4b"        # ambient banter + memory summarization
db_path = "brain.db"
templates_dir = "templates"
# Bots that always get the full treatment even outside party/guild chat:
inner_circle = ["Grimtok", "Elaria"]
max_concurrent = 4        # global cap on simultaneous Ollama generations
per_bot_cooldown = 2.0    # min seconds between generations for one bot
summarize_after = 30
request_log = "requests.jsonl"
```

- [ ] **Step 5: Append the M2 section to `humanlike/README.md`**

Append:

````markdown
## Milestone 2 — brain sidecar (personas + relationship memory)

Requires: M1 working, this branch's server rebuilt (adds `<bot guid>` /
`<other guid>` placeholders), and models from M1 plus:

```powershell
ollama pull qwen3:4b   # small utility model
```

### 1. Rebuild the server

Rebuild `mangosd` from this branch on the target machine (Visual Studio /
CMake as usual). The only C++ change since M1 is one line in
`playerbot/strategy/actions/SayAction.cpp`.

### 2. Run the sidecar

```powershell
cd <checkout>\sidecar
python -m venv .venv
.venv\Scripts\pip install -e .
copy config.example.toml config.toml   # then edit inner_circle etc.
.venv\Scripts\uvicorn --factory brain.server:create_app --host 127.0.0.1 --port 8085
```

### 3. Point the game server at it

In `aiplayerbot.conf`, replace the two keys shown in
`humanlike/conf/m2-sidecar.conf.example` (endpoint + ApiJson). Restart mangosd.

### 4. Verify (M2 checklist)

1. Party up with a bot, chat in /p → reply arrives AND `brain.db` appears in
   `sidecar/`; `requests.jsonl` grows by one line per message.
2. Reply reflects a persona (`Personality:` card auto-generated per bot —
   inspect with `.venv\Scripts\python -c "from brain.memory import MemoryStore; print(MemoryStore('brain.db').get_persona(<guid>))"`).
3. Say something memorable ("I'll give you this axe"), chat ~30 more
   exchanges → summary appears (check `summaries` table) and the bot can
   reference it in later replies.
4. **Restart everything** (mangosd + sidecar), whisper the same bot →
   it still knows you (summary + sentiment survived).
5. Chat from world chat as a stranger to a non-inner-circle bot → reply
   still comes (ambient tier) but `interactions` gains no row.
6. Kill the sidecar mid-session → bots go silent but nothing crashes;
   restart sidecar → chat resumes.
7. Prompt iteration: edit `sidecar/templates/chat.txt`, then
   `.venv\Scripts\python -m brain.replay requests.jsonl` — the last real
   request replays against the new template without touching the game.
````

- [ ] **Step 6: Run the full suite one last time**

Run: `cd /workspace/playerbots/sidecar && .venv/bin/pytest -v`
Expected: all passed

- [ ] **Step 7: Commit**

```bash
cd /workspace/playerbots
git add playerbot/strategy/actions/SayAction.cpp humanlike/ sidecar/config.example.toml
git commit -m "feat(m2): guid placeholders, sidecar config examples and M2 setup guide"
```

---

## Verification (overall)

- **On this machine:** full pytest suite green (`cd /workspace/playerbots/sidecar && .venv/bin/pytest -v`); `git log --oneline` shows one commit per task on `feature/humanlike-llm-bots`; no C++ was compiled.
- **On the target machine (Andreas):** follow `humanlike/README.md` — M1 checklist (7 steps), then rebuild + M2 checklist (7 steps). The M2 checklist IS the end-to-end test of the spec's M2 acceptance criterion ("bot references yesterday's run after full restart" = checklist step 4).
