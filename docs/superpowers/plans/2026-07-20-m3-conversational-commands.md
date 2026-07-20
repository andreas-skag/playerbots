# M3 Conversational Commands Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** "Can you tank this dungeon?" said to a bot makes it answer in character *and* switch to tanking — via a sidecar-emitted structured directive that C++ validates and routes to the existing playerbot command system.

**Architecture:** Two-step brain in the Python sidecar (keyword pre-filter → small-model intent classification → deterministic Python gates → `directive` field in the response JSON); thin C++ executor (`LLMDirectiveHandler`) that parses the directive on the async response thread, queues it by bot GUID, and drains/validates/executes on the world thread. Spec: `docs/superpowers/specs/2026-07-20-m3-conversational-commands-design.md`.

**Tech Stack:** Python 3.11+ (FastAPI, pytest, httpx), C++ (cmangos playerbots module), PowerShell 5.1 (setup scripts), TOML config.

## Global Constraints

- **C++ is write-only in this container.** Never attempt to compile C++ here. C++ tasks end at "commit"; Andreas compiles on the Windows desktop (possibly docker). Keep the C++ diff small, self-contained, and conservative (match surrounding style; no C++17-beyond features not already used).
- CMake uses `file(GLOB ...)` (`CMakeLists.txt:25`) — new `playerbot/*.cpp` files are picked up automatically, but Andreas must re-run CMake configure. No CMakeLists edit needed.
- Sidecar tests: run from `/workspace/playerbots/sidecar` with `python -m pytest tests/ -q`. All 37 existing tests must stay green.
- PowerShell must stay 5.1-compatible (no PS7-only syntax), matching existing scripts.
- Channel strings from the server are full phrases: `"in party chat"`, `"in raid chat"`, `"in guild chat"`, `"in private message"` (see `SayAction.cpp` sourceName map).
- `inner_circle` in `config.toml` holds bot **names**; the new `player_guids` holds character **GUID strings**.
- Directive schema (spec): `{"verb": "<verb>", "args": {"<k>": "<v>"}}`, args optional. Verbs: `role_tank role_heal role_dps follow stay guard flee attack lead loot release come give_leader reset`. `mark` arg values: `star circle diamond triangle moon square cross skull`.
- Refusal decisions are deterministic Python (sentiment threshold) — never the LLM.
- Commit style: existing repo convention, e.g. `feat(sidecar): ...`, `feat(playerbot): ...`, `docs: ...`. Commit after every task (and at each Commit step).

## File Structure

| File | Responsibility |
|---|---|
| `sidecar/brain/request_parser.py` (modify) | + `GroupMember` dataclass, `group` roster parsing from meta |
| `sidecar/brain/settings.py` (modify) | + `CommandSettings` (`[commands]` table), `player_guids` |
| `sidecar/config.example.toml` (modify) | + documented new keys |
| `sidecar/brain/ollama.py` (modify) | + optional `format="json"` param for constrained output |
| `sidecar/brain/intent.py` (create) | verb/mark constants, keyword pre-filter, small-model classifier |
| `sidecar/templates/intent.txt` (create) | classifier system prompt |
| `sidecar/brain/commands.py` (create) | authorization, sentiment gate, best-fit routing, dedup registry, `decide()` |
| `sidecar/brain/prompts.py` (modify) | + `directive_note` slot in prompt assembly |
| `sidecar/templates/chat.txt` (modify) | + `{directive_note}` line |
| `sidecar/brain/server.py` (modify) | wire `decide()`, attach `directive` response field |
| `sidecar/brain/replay.py` (modify) | print directive summary line |
| `playerbot/LLMDirectiveHandler.h/.cpp` (create) | directive parse (async-thread), pending queue, world-thread execute |
| `playerbot/strategy/actions/SayAction.cpp/.h` (modify) | `<group>` placeholder; pass bot/requester GUIDs into `GenerateResponsePackets`; extract+enqueue |
| `playerbot/strategy/actions/RpgSubActions.cpp` (modify) | second `GenerateResponsePackets` call site — pass `0, 0` |
| `playerbot/PlayerbotAIConfig.h/.cpp` (modify) | `LLMCommands.Enable`, `LLMCommands.TrustedGuids` |
| `playerbot/PlayerbotAI.cpp` (modify) | drain hook in `UpdateAIInternal` |
| `humanlike/conf/m3-commands.conf.example` (create) | M3 server conf (meta gains `group`, command keys) |
| `humanlike/scripts/pick-bots.ps1` (modify) | + player-character pick → `player_guids` + TrustedGuids conf line |
| `humanlike/README.md` (modify) | M3 setup section + verification checklist |

**One deliberate refinement vs. spec wording:** `TrustedGuids`/`player_guids` hold the *player's own character GUIDs*, not the companion-bot list. Group membership already authorizes everyone in the party (humans and bots); the only out-of-group commanders we want are the player's characters whispering their companions. Bot-to-bot commands are same-group-only by spec, so bots never need trusted status.

---

### Task 1: Group roster parsing (`request_parser.py`)

**Files:**
- Modify: `sidecar/brain/request_parser.py`
- Test: `sidecar/tests/test_request_parser.py`

**Interfaces:**
- Produces: `GroupMember` dataclass (`name: str, guid: int, cls: str, level: int`); `BotRequest.group: list[GroupMember]` (default `[]`). Roster wire format from C++: `Name:guid:Class Name:level` joined with `;` (class names may contain spaces, e.g. `Warrior`, `Hunter`).

- [ ] **Step 1: Write the failing tests** — append to `sidecar/tests/test_request_parser.py`:

```python
from brain.request_parser import GroupMember, parse_request


def _body_with_group(group):
    return {
        "messages": [{"role": "user", "content": "Andreas:can you tank?"}],
        "meta": {"bot_guid": "42", "bot_name": "Grimtok", "other_guid": "7",
                 "other_name": "Andreas", "channel": "in party chat",
                 "event": "chat", "group": group},
    }


def test_group_roster_parsed():
    req = parse_request(_body_with_group(
        "Andreas:7:Paladin:60;Grimtok:42:Warrior:60;Zinnia:43:Priest:58"))
    assert req.group == [
        GroupMember(name="Andreas", guid=7, cls="Paladin", level=60),
        GroupMember(name="Grimtok", guid=42, cls="Warrior", level=60),
        GroupMember(name="Zinnia", guid=43, cls="Priest", level=58),
    ]


def test_group_missing_or_placeholder_is_empty():
    assert parse_request(_body_with_group("")).group == []
    assert parse_request(_body_with_group("<group>")).group == []
    body = _body_with_group("x")
    del body["meta"]["group"]
    assert parse_request(body).group == []


def test_group_malformed_entries_skipped():
    req = parse_request(_body_with_group("Broken;Andreas:7:Paladin:60;A:B:C:D"))
    assert req.group == [GroupMember(name="Andreas", guid=7, cls="Paladin", level=60)]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /workspace/playerbots/sidecar && python -m pytest tests/test_request_parser.py -q`
Expected: FAIL — `ImportError: cannot import name 'GroupMember'`

- [ ] **Step 3: Implement** — in `sidecar/brain/request_parser.py`, add after the imports:

```python
@dataclass
class GroupMember:
    name: str
    guid: int
    cls: str
    level: int
```

Add `group: list[GroupMember] = None` — no: dataclasses need a real default. Instead add to `BotRequest` (after `event: str`):

```python
    group: list["GroupMember"] = field(default_factory=list)
```

and change the import line to `from dataclasses import dataclass, field`. Add the parser helper:

```python
def _parse_group(raw: str) -> list[GroupMember]:
    members = []
    for entry in raw.split(";"):
        parts = entry.split(":")
        if len(parts) != 4:
            continue
        name, guid, cls, level = (p.strip() for p in parts)
        if not name or not guid.isdigit() or not level.isdigit():
            continue
        members.append(GroupMember(name=name, guid=int(guid), cls=cls, level=int(level)))
    return members
```

In `parse_request`, add to the returned `BotRequest(...)`:

```python
        group=_parse_group(_meta_str(meta, "group")),
```

(`_meta_str` already returns `""` for unsubstituted `<group>` placeholders.)

- [ ] **Step 4: Run the full suite**

Run: `cd /workspace/playerbots/sidecar && python -m pytest tests/ -q`
Expected: all pass (37 existing + 3 new)

- [ ] **Step 5: Commit**

```bash
cd /workspace/playerbots && git add sidecar/brain/request_parser.py sidecar/tests/test_request_parser.py
git commit -m "feat(sidecar): parse group roster from request meta"
```

---

### Task 2: Command settings (`settings.py` + `config.example.toml`)

**Files:**
- Modify: `sidecar/brain/settings.py`, `sidecar/config.example.toml`, `sidecar/brain/replay.py`
- Test: `sidecar/tests/test_settings.py`

**Interfaces:**
- Produces: `CommandSettings` dataclass — `enabled: bool = True`, `always_obey: bool = False`, `sentiment_threshold: float = -25.0`, `dedup_window_s: float = 3.0`, `allow_bot_commanders: bool = True`. `Settings.commands: CommandSettings`; `Settings.player_guids: list[str]` (GUIDs as strings, matching meta format).

- [ ] **Step 1: Write the failing tests** — append to `sidecar/tests/test_settings.py`:

```python
def test_commands_defaults():
    s = Settings()
    assert s.commands.enabled is True
    assert s.commands.always_obey is False
    assert s.commands.sentiment_threshold == -25.0
    assert s.commands.dedup_window_s == 3.0
    assert s.commands.allow_bot_commanders is True
    assert s.player_guids == []


def test_commands_table_loaded(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text('player_guids = ["7"]\n[commands]\nenabled = false\nsentiment_threshold = -10.0\n')
    s = Settings.load(p)
    assert s.commands.enabled is False
    assert s.commands.sentiment_threshold == -10.0
    assert s.commands.always_obey is False
    assert s.player_guids == ["7"]


def test_unknown_commands_key_rejected(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text("[commands]\nbogus = 1\n")
    try:
        Settings.load(p)
        assert False, "expected ValueError"
    except ValueError as e:
        assert "bogus" in str(e)
```

(Match the existing import style at the top of `test_settings.py` — it already imports `Settings`.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /workspace/playerbots/sidecar && python -m pytest tests/test_settings.py -q`
Expected: FAIL — `AttributeError: 'Settings' object has no attribute 'commands'`

- [ ] **Step 3: Implement** — in `sidecar/brain/settings.py`, add above `Settings`:

```python
@dataclass
class CommandSettings:
    enabled: bool = True
    always_obey: bool = False
    sentiment_threshold: float = -25.0
    dedup_window_s: float = 3.0
    allow_bot_commanders: bool = True
```

Add fields to `Settings` (after `request_log`):

```python
    player_guids: list[str] = field(default_factory=list)
    commands: CommandSettings = field(default_factory=CommandSettings)
```

In `Settings.load`, handle the nested table before the unknown-key check:

```python
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
```

In `sidecar/brain/replay.py`, `replay_settings` builds a `Settings(...)` explicitly — add these two lines to its constructor call so replays honor command config:

```python
        player_guids=list(base.player_guids),
        commands=base.commands,
```

Append to `sidecar/config.example.toml`:

```toml
# Your own character GUIDs (characters.guid) — whisper commands outside a group
# are only obeyed from these. pick-bots.ps1 fills this in.
player_guids = []

[commands]
enabled = true               # master switch for conversational commands
always_obey = false          # true = skip sentiment-based refusals
sentiment_threshold = -25.0  # refuse commands from speakers below this score
dedup_window_s = 3.0         # window for one-actor-per-utterance dedup
allow_bot_commanders = true  # bots may command each other within the group
```

- [ ] **Step 4: Run the full suite**

Run: `cd /workspace/playerbots/sidecar && python -m pytest tests/ -q`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
cd /workspace/playerbots && git add sidecar/brain/settings.py sidecar/brain/replay.py sidecar/config.example.toml sidecar/tests/test_settings.py
git commit -m "feat(sidecar): [commands] settings table and player_guids"
```

---

### Task 3: Intent classifier (`intent.py`, `templates/intent.txt`, `ollama.py` format param)

**Files:**
- Create: `sidecar/brain/intent.py`, `sidecar/templates/intent.txt`
- Modify: `sidecar/brain/ollama.py`
- Test: `sidecar/tests/test_intent.py` (create)

**Interfaces:**
- Consumes: `BotRequest` (Task 1), `OllamaClient.chat`.
- Produces:
  - `VERBS: frozenset[str]`, `MARKS: frozenset[str]` (values from Global Constraints).
  - `looks_like_command(message: str) -> bool` — cheap keyword pre-filter.
  - `Intent` dataclass: `verb: str`, `args: dict[str, str]` (default `{}`), `addressed: str` (default `""`, a character name or empty).
  - `async classify(ollama, templates_dir, req: BotRequest) -> Intent | None` — None means "not a command" (including any malformed/invalid model output).
  - `OllamaClient.chat(messages, tier="inner", format=None)` — passes `"format": "json"` through to Ollama when set.

- [ ] **Step 1: Write the failing tests** — create `sidecar/tests/test_intent.py`:

```python
import asyncio
import json

from brain import intent
from brain.request_parser import parse_request


def _req(msg, group="Andreas:7:Paladin:60;Grimtok:42:Warrior:60"):
    return parse_request({
        "messages": [{"role": "user", "content": f"Andreas:{msg}"}],
        "meta": {"bot_guid": "42", "bot_name": "Grimtok", "other_guid": "7",
                 "other_name": "Andreas", "channel": "in party chat",
                 "event": "chat", "group": group},
    })


class FakeOllama:
    def __init__(self, reply):
        self.reply = reply
        self.calls = []

    async def chat(self, messages, tier="inner", format=None):
        self.calls.append((messages, tier, format))
        return self.reply


def test_prefilter_rejects_banter():
    assert intent.looks_like_command("nice weather in westfall") is False
    assert intent.looks_like_command("what do you think of this sword?") is False


def test_prefilter_accepts_command_shaped():
    assert intent.looks_like_command("can you tank this dungeon?") is True
    assert intent.looks_like_command("Grimtok kill the skull target") is True
    assert intent.looks_like_command("lead the way") is True
    assert intent.looks_like_command("come help me") is True


def test_classify_valid_verb_with_mark():
    fake = FakeOllama(json.dumps(
        {"verb": "attack", "args": {"mark": "skull"}, "addressed": "Grimtok"}))
    result = asyncio.run(intent.classify(fake, "templates", _req("Grimtok kill the skull")))
    assert result == intent.Intent(verb="attack", args={"mark": "skull"}, addressed="Grimtok")
    assert fake.calls[0][1] == "ambient"      # small model
    assert fake.calls[0][2] == "json"         # constrained output
    prompt = fake.calls[0][0][0]["content"]
    assert "attack" in prompt and "Grimtok" in prompt


def test_classify_none_verb_and_junk_return_none():
    assert asyncio.run(intent.classify(FakeOllama('{"verb": "none"}'), "templates", _req("hi"))) is None
    assert asyncio.run(intent.classify(FakeOllama("not json"), "templates", _req("hi"))) is None
    assert asyncio.run(intent.classify(FakeOllama('{"verb": "delete_character"}'), "templates", _req("hi"))) is None


def test_classify_invalid_mark_dropped_but_verb_kept():
    fake = FakeOllama('{"verb": "attack", "args": {"mark": "banana"}}')
    result = asyncio.run(intent.classify(fake, "templates", _req("kill it")))
    assert result == intent.Intent(verb="attack", args={}, addressed="")


def test_classify_model_error_returns_none():
    class Boom:
        async def chat(self, messages, tier="inner", format=None):
            raise RuntimeError("ollama down")
    assert asyncio.run(intent.classify(Boom(), "templates", _req("can you tank?"))) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /workspace/playerbots/sidecar && python -m pytest tests/test_intent.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'brain.intent'`

- [ ] **Step 3: Extend `OllamaClient.chat`** — in `sidecar/brain/ollama.py` replace the `chat` method:

```python
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
```

- [ ] **Step 4: Create `sidecar/templates/intent.txt`:**

```text
You extract commands from World of Warcraft party chat. The speaker is
{speaker}. The group roster is: {roster}.

If the message asks someone to DO one of these actions, output it as JSON;
otherwise output {{"verb": "none"}}.

Verbs:
role_tank (switch to tanking), role_heal (switch to healing), role_dps
(switch to damage), follow (follow the speaker / stop leading), stay,
guard (hold this position and protect), flee (run away), attack (attack a
target; args.mark = star|circle|diamond|triangle|moon|square|cross|skull
if a raid icon is named), lead (lead the way / take point), loot (pick up
loot), release (release spirit when dead), come (come to the speaker),
give_leader (make the speaker group leader), reset (stop acting weird,
reset behavior).

"addressed" is the roster name the message is directed at, or "" if it is
directed at no one in particular ("someone", "anyone", the whole group).

Output ONLY a JSON object: {{"verb": "...", "args": {{}}, "addressed": "..."}}
```

- [ ] **Step 5: Create `sidecar/brain/intent.py`:**

```python
"""Turn command-shaped chat into a validated Intent via the small model."""
import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from .request_parser import BotRequest

log = logging.getLogger(__name__)

VERBS = frozenset({
    "role_tank", "role_heal", "role_dps", "follow", "stay", "guard", "flee",
    "attack", "lead", "loot", "release", "come", "give_leader", "reset",
})
MARKS = frozenset({
    "star", "circle", "diamond", "triangle", "moon", "square", "cross", "skull",
})

# Cheap pre-filter: only messages containing a command-ish keyword reach the
# classifier. Generous on purpose — false positives cost one small-model call,
# false negatives cost a missed command.
_KEYWORDS = re.compile(
    r"\b(tank|heal|dps|damage|follow|stay|wait|guard|protect|hold|flee|run"
    r"|attack|kill|fight|lead|loot|release|come|here|help|summon|leader"
    r"|reset|stop|skull|cross|square|moon|triangle|diamond|circle|star)\b",
    re.IGNORECASE)


@dataclass
class Intent:
    verb: str
    args: dict[str, str] = field(default_factory=dict)
    addressed: str = ""


def looks_like_command(message: str) -> bool:
    return bool(_KEYWORDS.search(message))


def _validate(raw: dict, req: BotRequest) -> "Intent | None":
    verb = raw.get("verb")
    if verb not in VERBS:
        return None
    args = {}
    raw_args = raw.get("args") or {}
    if verb == "attack" and isinstance(raw_args, dict):
        mark = raw_args.get("mark", "")
        if isinstance(mark, str) and mark.lower() in MARKS:
            args["mark"] = mark.lower()
    addressed = raw.get("addressed") or ""
    roster_names = {m.name.lower(): m.name for m in req.group}
    addressed = roster_names.get(str(addressed).lower(), "")
    return Intent(verb=verb, args=args, addressed=addressed)


async def classify(ollama, templates_dir, req: BotRequest) -> "Intent | None":
    template = (Path(templates_dir) / "intent.txt").read_text()
    roster = ", ".join(f"{m.name} ({m.cls} {m.level})" for m in req.group) or "(none)"
    system = template.format(speaker=req.speaker_name, roster=roster)
    messages = [{"role": "system", "content": system},
                {"role": "user", "content": req.message}]
    try:
        reply = await ollama.chat(messages, tier="ambient", format="json")
        raw = json.loads(reply)
    except Exception:
        log.exception("intent classification failed")
        return None
    if not isinstance(raw, dict):
        return None
    return _validate(raw, req)
```

- [ ] **Step 6: Run the full suite**

Run: `cd /workspace/playerbots/sidecar && python -m pytest tests/ -q`
Expected: all pass

- [ ] **Step 7: Commit**

```bash
cd /workspace/playerbots && git add sidecar/brain/intent.py sidecar/templates/intent.txt sidecar/brain/ollama.py sidecar/tests/test_intent.py
git commit -m "feat(sidecar): keyword pre-filter and small-model intent classifier"
```

---

### Task 4: Gates, routing, dedup (`commands.py`)

**Files:**
- Create: `sidecar/brain/commands.py`
- Test: `sidecar/tests/test_commands.py` (create)

**Interfaces:**
- Consumes: `Intent`, `classify`, `looks_like_command` (Task 3); `BotRequest.group` (Task 1); `Settings.commands`, `Settings.player_guids` (Task 2); `store.sentiment(bot_guid, other_guid) -> float`.
- Produces:
  - `Decision` dataclass: `role: str` (`"actor" | "bystander" | "refused" | "none"`), `intent: Intent | None`.
  - `DedupRegistry` class: `__init__(window_s: float)`; internals below.
  - `async decide(registry, ollama, settings, store, req) -> Decision` — the single entry point `server.py` calls. Handles authorization, classification caching, best-fit routing, sentiment gate, cascade guard.
  - `directive_json(intent: Intent) -> dict` — `{"verb": ..., "args": {...}}` (args key omitted when empty).
  - `describe(intent: Intent) -> str` — short English description for prompt notes, e.g. `"switch to tanking"`, `"attack the skull target"`.

**Behavior rules (implement exactly):**
1. **Authorization** (before any model call): speaker is *the player* if `str(req.other_guid) in settings.player_guids`. Channel `"in private message"`: authorized only if speaker is the player (bots and strangers cannot whisper-command). Channels `"in party chat"` / `"in raid chat"`: authorized if speaker is the player, OR speaker guid is in the roster (`req.group`) and `commands.allow_bot_commanders` is true, OR speaker guid is in the roster and speaker is a real (non-inner-circle-bot) group member — simplification: roster membership authorizes; `allow_bot_commanders=False` additionally requires the speaker to be the player. All other channels: not authorized. Unauthorized → `Decision("none", None)` with **no classifier call**.
2. **Cascade guard:** if the speaker guid was an *actor* for any directive within the dedup window (`registry.was_recent_actor(req.other_guid)`), return `Decision("none", None)` — depth limit 1.
3. **Classification caching (dedup):** key = `(req.other_guid, req.message.strip().lower())`. `registry.get_or_classify(key, coro_factory)` — first caller runs `classify()` and stores the result (including `None`); callers within the window reuse it. Cached `None` → `Decision("none", None)`.
4. **Actor selection:** whisper → this bot is the actor. `intent.addressed` set → actor is that name's guid (if it's this bot → actor, else bystander). Unaddressed: candidates = roster members whose guid is not the speaker's and not in `player_guids`; pick by class preference for the verb — `role_tank`/`lead`/`attack`: `["Warrior", "Paladin", "Druid"]`; `role_heal`: `["Priest", "Druid", "Shaman", "Paladin"]`; everything else: no preference. First candidate whose `cls` matches the preference list (in list order); no match or no preference → lowest guid. If chosen guid != `req.bot_guid` → `Decision("bystander", intent)`.
5. **Sentiment gate** (actors only): `store.sentiment(req.bot_guid, req.other_guid) < commands.sentiment_threshold` and not `commands.always_obey` → `Decision("refused", intent)`. Otherwise `registry.record_actor(req.bot_guid)` and `Decision("actor", intent)`.

- [ ] **Step 1: Write the failing tests** — create `sidecar/tests/test_commands.py`:

```python
import asyncio
import json

from brain import commands
from brain.intent import Intent
from brain.memory import MemoryStore
from brain.request_parser import parse_request
from brain.settings import CommandSettings, Settings

ROSTER = "Andreas:7:Paladin:60;Grimtok:42:Warrior:60;Zinnia:43:Priest:58"


def _req(msg="can someone tank?", bot_guid="42", other_guid="7",
         channel="in party chat", group=ROSTER):
    return parse_request({
        "messages": [{"role": "user", "content": f"X:{msg}"}],
        "meta": {"bot_guid": bot_guid, "bot_name": "Grimtok",
                 "other_guid": other_guid, "other_name": "Andreas",
                 "channel": channel, "event": "chat", "group": group},
    })


class FakeOllama:
    def __init__(self, reply='{"verb": "role_tank", "args": {}, "addressed": ""}'):
        self.reply = reply
        self.calls = 0

    async def chat(self, messages, tier="inner", format=None):
        self.calls += 1
        return self.reply


def _settings(**cmd):
    return Settings(player_guids=["7"], commands=CommandSettings(**cmd))


def _decide(registry, ollama, settings, store, req):
    return asyncio.run(commands.decide(registry, ollama, settings, store, req))


def test_unauthorized_stranger_no_classifier_call():
    fake = FakeOllama()
    req = _req(other_guid="999", channel="in private message")
    d = _decide(commands.DedupRegistry(3.0), fake, _settings(), MemoryStore(":memory:"), req)
    assert d.role == "none" and fake.calls == 0


def test_player_whisper_makes_this_bot_actor():
    req = _req(channel="in private message", group="")
    d = _decide(commands.DedupRegistry(3.0), FakeOllama(), _settings(), MemoryStore(":memory:"), req)
    assert d.role == "actor"
    assert d.intent == Intent(verb="role_tank")


def test_best_fit_routes_tank_to_warrior():
    registry = commands.DedupRegistry(3.0)
    fake = FakeOllama()
    store = MemoryStore(":memory:")
    warrior = _decide(registry, fake, _settings(), store, _req(bot_guid="42"))
    priest = _decide(registry, fake, _settings(), store, _req(bot_guid="43"))
    assert warrior.role == "actor"
    assert priest.role == "bystander"
    assert fake.calls == 1  # classified once, cached for the second bot


def test_addressed_bot_wins_over_class_fit():
    fake = FakeOllama('{"verb": "role_tank", "args": {}, "addressed": "Zinnia"}')
    d = _decide(commands.DedupRegistry(3.0), fake, _settings(), MemoryStore(":memory:"),
                _req(bot_guid="43"))
    assert d.role == "actor"


def test_low_sentiment_refuses_and_always_obey_overrides():
    store = MemoryStore(":memory:")
    store.adjust_sentiment(42, 7, -50)
    d = _decide(commands.DedupRegistry(3.0), FakeOllama(), _settings(), store, _req())
    assert d.role == "refused"
    d2 = _decide(commands.DedupRegistry(3.0), FakeOllama(), _settings(always_obey=True),
                 store, _req())
    assert d2.role == "actor"


def test_bot_commander_allowed_in_group_only():
    # Zinnia (43, in roster, not the player) commands in party chat
    req = _req(other_guid="43")
    d = _decide(commands.DedupRegistry(3.0), FakeOllama(), _settings(), MemoryStore(":memory:"), req)
    assert d.role == "actor"
    # but not when allow_bot_commanders is off
    d2 = _decide(commands.DedupRegistry(3.0), FakeOllama(),
                 _settings(allow_bot_commanders=False), MemoryStore(":memory:"), req)
    assert d2.role == "none"
    # and never via whisper
    d3 = _decide(commands.DedupRegistry(3.0), FakeOllama(), _settings(),
                 MemoryStore(":memory:"), _req(other_guid="43", channel="in private message"))
    assert d3.role == "none"


def test_cascade_guard_blocks_recent_actor():
    registry = commands.DedupRegistry(3.0)
    store = MemoryStore(":memory:")
    first = _decide(registry, FakeOllama(), _settings(), store, _req(bot_guid="42"))
    assert first.role == "actor"
    # now Grimtok (42) speaks a command-shaped line — he just acted, so ignore
    fake = FakeOllama()
    d = _decide(registry, fake, _settings(), store, _req(bot_guid="43", other_guid="42"))
    assert d.role == "none" and fake.calls == 0


def test_directive_json_and_describe():
    assert commands.directive_json(Intent(verb="role_tank")) == {"verb": "role_tank"}
    assert commands.directive_json(Intent(verb="attack", args={"mark": "skull"})) == {
        "verb": "attack", "args": {"mark": "skull"}}
    assert commands.describe(Intent(verb="attack", args={"mark": "skull"})) == \
        "attack the skull target"
    assert commands.describe(Intent(verb="role_tank")) == "switch to tanking"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /workspace/playerbots/sidecar && python -m pytest tests/test_commands.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'brain.commands'`

- [ ] **Step 3: Create `sidecar/brain/commands.py`:**

```python
"""Authorization, routing and dedup for conversational commands.

Single-threaded by construction: FastAPI runs one event loop, and every
registry mutation happens synchronously between awaits, so no locks.
"""
import time
from dataclasses import dataclass

from . import intent as intent_mod
from .intent import Intent
from .request_parser import BotRequest
from .settings import Settings

_COMMAND_CHANNELS = {"in party chat", "in raid chat"}
_WHISPER = "in private message"

_CLASS_FIT = {
    "role_tank": ["Warrior", "Paladin", "Druid"],
    "lead": ["Warrior", "Paladin", "Druid"],
    "attack": ["Warrior", "Paladin", "Druid"],
    "role_heal": ["Priest", "Druid", "Shaman", "Paladin"],
}

_DESCRIPTIONS = {
    "role_tank": "switch to tanking",
    "role_heal": "switch to healing",
    "role_dps": "switch to dealing damage",
    "follow": "follow them",
    "stay": "stay where you are",
    "guard": "guard this spot",
    "flee": "run from the fight",
    "attack": "attack their target",
    "lead": "lead the way",
    "loot": "gather the loot",
    "release": "release your spirit",
    "come": "come to them",
    "give_leader": "hand them group lead",
    "reset": "snap out of it and reset your behavior",
}


@dataclass
class Decision:
    role: str                 # "actor" | "bystander" | "refused" | "none"
    intent: "Intent | None"


class DedupRegistry:
    def __init__(self, window_s: float):
        self.window_s = window_s
        self._intents: dict[tuple, tuple[float, "Intent | None"]] = {}
        self._actors: dict[int, float] = {}

    def _expire(self, now: float) -> None:
        self._intents = {k: v for k, v in self._intents.items()
                         if now - v[0] < self.window_s}
        self._actors = {k: v for k, v in self._actors.items()
                        if now - v < self.window_s}

    async def get_or_classify(self, key: tuple, coro_factory):
        now = time.monotonic()
        self._expire(now)
        if key in self._intents:
            return self._intents[key][1]
        # Reserve the slot before awaiting so concurrent requests for the
        # same utterance don't classify twice; they briefly see None, which
        # only costs a missed bystander note.
        self._intents[key] = (now, None)
        result = await coro_factory()
        self._intents[key] = (now, result)
        return result

    def record_actor(self, bot_guid: int) -> None:
        self._actors[bot_guid] = time.monotonic()

    def was_recent_actor(self, guid: int) -> bool:
        self._expire(time.monotonic())
        return guid in self._actors


def _authorized(req: BotRequest, settings: Settings) -> bool:
    speaker_is_player = str(req.other_guid) in settings.player_guids
    if req.channel == _WHISPER:
        return speaker_is_player
    if req.channel not in _COMMAND_CHANNELS:
        return False
    if speaker_is_player:
        return True
    in_roster = any(m.guid == req.other_guid for m in req.group)
    return in_roster and settings.commands.allow_bot_commanders


def _pick_actor(req: BotRequest, intent: Intent, settings: Settings) -> int:
    if req.channel == _WHISPER:
        return req.bot_guid
    if intent.addressed:
        for m in req.group:
            if m.name == intent.addressed:
                return m.guid
    candidates = [m for m in req.group
                  if m.guid != req.other_guid and str(m.guid) not in settings.player_guids]
    if not candidates:
        return req.bot_guid
    for cls in _CLASS_FIT.get(intent.verb, []):
        for m in sorted(candidates, key=lambda m: m.guid):
            if m.cls == cls:
                return m.guid
    return min(c.guid for c in candidates)


async def decide(registry: DedupRegistry, ollama, settings: Settings, store,
                 req: BotRequest) -> Decision:
    if not _authorized(req, settings):
        return Decision("none", None)
    if registry.was_recent_actor(req.other_guid):
        return Decision("none", None)

    key = (req.other_guid, req.message.strip().lower())
    intent = await registry.get_or_classify(
        key, lambda: intent_mod.classify(ollama, settings.templates_dir, req))
    if intent is None:
        return Decision("none", None)

    if _pick_actor(req, intent, settings) != req.bot_guid:
        return Decision("bystander", intent)

    score = store.sentiment(req.bot_guid, req.other_guid)
    if score < settings.commands.sentiment_threshold and not settings.commands.always_obey:
        return Decision("refused", intent)

    registry.record_actor(req.bot_guid)
    return Decision("actor", intent)


def directive_json(intent: Intent) -> dict:
    out = {"verb": intent.verb}
    if intent.args:
        out["args"] = dict(intent.args)
    return out


def describe(intent: Intent) -> str:
    if intent.verb == "attack" and intent.args.get("mark"):
        return f"attack the {intent.args['mark']} target"
    return _DESCRIPTIONS[intent.verb]
```

- [ ] **Step 4: Run the full suite**

Run: `cd /workspace/playerbots/sidecar && python -m pytest tests/ -q`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
cd /workspace/playerbots && git add sidecar/brain/commands.py sidecar/tests/test_commands.py
git commit -m "feat(sidecar): command gates, best-fit routing and dedup registry"
```

---

### Task 5: Directive note in prompts (`prompts.py`, `chat.txt`)

**Files:**
- Modify: `sidecar/brain/prompts.py`, `sidecar/templates/chat.txt`
- Test: `sidecar/tests/test_prompts.py`

**Interfaces:**
- Produces: `assemble(templates_dir, persona, summary, score, recent, req, directive_note="")` — the note lands in the system prompt; empty note leaves no stray text.

- [ ] **Step 1: Write the failing tests** — append to `sidecar/tests/test_prompts.py` (it already defines a module-level `req()` helper; `"templates"` is the real templates dir relative to `sidecar/`, same as `test_server.py` uses):

```python
def test_directive_note_in_system_prompt():
    messages = assemble("templates", "persona", "", 0.0, [], req(),
                        directive_note="You just agreed to switch to tanking.")
    assert "You just agreed to switch to tanking." in messages[0]["content"]


def test_no_directive_note_leaves_no_marker():
    messages = assemble("templates", "persona", "", 0.0, [], req())
    assert "{directive_note}" not in messages[0]["content"]
```

(The existing `test_assemble_*` tests write their own minimal templates without the new slot — that stays valid because `str.format` ignores unused kwargs.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /workspace/playerbots/sidecar && python -m pytest tests/test_prompts.py -q`
Expected: FAIL — `TypeError: assemble() got an unexpected keyword argument 'directive_note'`

- [ ] **Step 3: Implement** — in `sidecar/templates/chat.txt`, insert a line between the `Recent conversation:` block and the final `Reply as ...` paragraph:

```text
{directive_note}
```

In `sidecar/brain/prompts.py`, change the `assemble` signature and format call:

```python
def assemble(templates_dir: str | Path, persona: str, summary: str, score: float,
             recent: list[tuple[str, str]], req: BotRequest,
             directive_note: str = "") -> list[dict]:
```

and add `directive_note=directive_note,` to the `template.format(...)` kwargs.

- [ ] **Step 4: Run the full suite**

Run: `cd /workspace/playerbots/sidecar && python -m pytest tests/ -q`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
cd /workspace/playerbots && git add sidecar/brain/prompts.py sidecar/templates/chat.txt sidecar/tests/test_prompts.py
git commit -m "feat(sidecar): directive note slot in chat prompt"
```

---

### Task 6: Server wiring (`server.py`, replay printout)

**Files:**
- Modify: `sidecar/brain/server.py`, `sidecar/brain/replay.py`
- Test: `sidecar/tests/test_server.py`

**Interfaces:**
- Consumes: `commands.DedupRegistry`, `commands.decide`, `commands.directive_json`, `commands.describe` (Task 4); `intent.looks_like_command` (Task 3); `assemble(..., directive_note=...)` (Task 5).
- Produces: response JSON gains top-level `"directive": {"verb": ..., "args": {...}}` **only** when this bot is the actor. C++ (Task 8) greps the raw body for `"directive"` — never emit the key otherwise.

- [ ] **Step 1: Write the failing tests** — in `sidecar/tests/test_server.py`, update `FakeOllama` to accept the new kwarg and record it:

```python
class FakeOllama:
    def __init__(self, reply="Aye. Deadmines it is, whelp.", intent_reply='{"verb": "none"}'):
        self.reply = reply
        self.intent_reply = intent_reply
        self.calls = []

    async def chat(self, messages, tier="inner", format=None):
        self.calls.append((messages, tier, format))
        return self.intent_reply if format == "json" else self.reply
```

Then append tests:

```python
GROUP = "Andreas:7:Paladin:60;Grimtok:42:Warrior:60;Zinnia:43:Priest:58"


def command_body(msg="can you tank this dungeon?", bot_guid="42", channel="in party chat"):
    b = body(channel=channel)
    b["messages"][1]["content"] = f"Andreas:{msg}"
    b["meta"]["bot_guid"] = bot_guid
    b["meta"]["group"] = GROUP
    return b


def make_command_client(tmp_path, fake):
    from brain.settings import CommandSettings
    settings = Settings(db_path=":memory:", request_log=str(tmp_path / "req.jsonl"),
                        templates_dir="templates", summarize_after=1000,
                        per_bot_cooldown=0.0, player_guids=["7"],
                        commands=CommandSettings())
    store = MemoryStore(":memory:")
    app = create_app(settings=settings, store=store, ollama=fake)
    return TestClient(app), store


def test_actor_gets_directive_and_ack_context(tmp_path):
    fake = FakeOllama(reply="Fine, I'll keep it busy.",
                      intent_reply='{"verb": "role_tank", "args": {}, "addressed": ""}')
    client, _ = make_command_client(tmp_path, fake)
    r = client.post("/v1/chat/completions", json=command_body()).json()
    assert r["directive"] == {"verb": "role_tank"}
    assert r["choices"][0]["message"]["content"] == "Fine, I'll keep it busy."
    chat_system = [c for c in fake.calls if c[2] is None][0][0][0]["content"]
    assert "switch to tanking" in chat_system


def test_bystander_and_banter_have_no_directive(tmp_path):
    fake = FakeOllama(intent_reply='{"verb": "role_tank", "args": {}, "addressed": ""}')
    client, _ = make_command_client(tmp_path, fake)
    r = client.post("/v1/chat/completions", json=command_body(bot_guid="43")).json()
    assert "directive" not in r
    fake2 = FakeOllama()
    client2, _ = make_command_client(tmp_path, fake2)
    r2 = client2.post("/v1/chat/completions",
                      json=command_body(msg="lovely day in the barrens")).json()
    assert "directive" not in r2
    assert all(c[2] is None for c in fake2.calls)  # pre-filter skipped classifier


def test_refusal_has_no_directive_but_refusal_context(tmp_path):
    fake = FakeOllama(reply="Tank it yourself.",
                      intent_reply='{"verb": "role_tank", "args": {}, "addressed": ""}')
    client, store = make_command_client(tmp_path, fake)
    store.adjust_sentiment(42, 7, -50)
    r = client.post("/v1/chat/completions", json=command_body()).json()
    assert "directive" not in r
    chat_system = [c for c in fake.calls if c[2] is None][0][0][0]["content"]
    assert "refusing" in chat_system
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /workspace/playerbots/sidecar && python -m pytest tests/test_server.py -q`
Expected: FAIL — `KeyError: 'directive'`

- [ ] **Step 3: Implement** — in `sidecar/brain/server.py`:

Add imports: `from . import commands as commands_mod` and `from . import intent as intent_mod`.

In `create_app`, after `last_generation = ...` add:

```python
    registry = commands_mod.DedupRegistry(settings.commands.dedup_window_s)
```

Replace the block from `messages = prompts.assemble(...)` through `return _completion(reply)` with:

```python
            decision = commands_mod.Decision("none", None)
            if (settings.commands.enabled and req.event == "chat"
                    and intent_mod.looks_like_command(req.message)):
                decision = await commands_mod.decide(registry, ollama, settings,
                                                     store, req)

            directive_note = ""
            if decision.role == "actor":
                directive_note = (f"You just agreed to {commands_mod.describe(decision.intent)}. "
                                  "Acknowledge briefly, in character.")
            elif decision.role == "refused":
                directive_note = (f"{req.other_name} asked you to "
                                  f"{commands_mod.describe(decision.intent)}, but you are "
                                  "refusing because of how you feel about them. Say so in character.")

            messages = prompts.assemble(settings.templates_dir, persona, summary,
                                        score, recent, req,
                                        directive_note=directive_note)
            reply = await ollama.chat(messages, tier="inner" if inner else "ambient")
            last_generation[req.bot_guid] = now

            if reply and inner and req.bot_guid and req.other_guid:
                store.record_interaction(req.bot_guid, req.other_guid, req.other_name,
                                         req.channel, req.message, reply)
                store.adjust_sentiment(req.bot_guid, req.other_guid, 1)
                background_tasks.add_task(
                    summarizer.maybe_summarize, store, ollama, req.bot_guid,
                    req.other_guid, req.bot_name, req.other_name,
                    settings.summarize_after)

            payload = {"choices": [{"message": {"role": "assistant", "content": reply}}]}
            if decision.role == "actor":
                payload["directive"] = commands_mod.directive_json(decision.intent)
            return JSONResponse(payload)
```

(The bare-exception handler at the bottom still returns `_completion("")` — unchanged, and correctly directive-free.)

In `sidecar/brain/replay.py` `main()`, after the `print(json.dumps(...))` line add:

```python
    print("directive:", json.dumps(response.get("directive")) if response.get("directive") else "(none)")
```

- [ ] **Step 4: Run the full suite**

Run: `cd /workspace/playerbots/sidecar && python -m pytest tests/ -q`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
cd /workspace/playerbots && git add sidecar/brain/server.py sidecar/brain/replay.py sidecar/tests/test_server.py
git commit -m "feat(sidecar): emit directive field and agreed/refused prompt context"
```

---

### Task 7: C++ `LLMDirectiveHandler` (parser + queue + executor) — WRITE-ONLY

**Files:**
- Create: `playerbot/LLMDirectiveHandler.h`, `playerbot/LLMDirectiveHandler.cpp`

**Interfaces:**
- Consumes: `PlayerbotAI::HandleCommand(uint32, const std::string&, Player&, uint32)` (`PlayerbotAI.h:373`), `PlayerbotAI::ChangeStrategy(const std::string&, BotState)` (`PlayerbotAI.h:383`), `sObjectAccessor.FindPlayer` (pattern at `SayAction.cpp:516`), `sPlayerbotAIConfig.llmCommandTrustedGuids` (Task 9).
- Produces (used by Tasks 8 and 10): `struct PendingDirective { std::string verb; std::map<std::string,std::string> args; uint32 requesterGuid; time_t enqueuedAt; }`; statics `ExtractDirective(const std::string&, PendingDirective&) -> bool`, `Enqueue(uint32 botGuid, const PendingDirective&)`, `Drain(uint32 botGuid) -> std::vector<PendingDirective>`, `Execute(Player* bot, PlayerbotAI* ai, const PendingDirective&)`.

- [ ] **Step 1: Create `playerbot/LLMDirectiveHandler.h`:**

```cpp
#pragma once

#include <cstdint>
#include <ctime>
#include <map>
#include <mutex>
#include <string>
#include <unordered_map>
#include <vector>

class Player;
class PlayerbotAI;

// A whitelisted command extracted from a sidecar reply. Parsed on the async
// response thread, executed on the world thread (never call Execute off it).
// uint32_t keeps this header self-contained (no cmangos includes, matching
// PlayerbotLLMInterface.h); it is the same underlying type as cmangos uint32.
struct PendingDirective
{
    std::string verb;
    std::map<std::string, std::string> args;
    uint32_t requesterGuid = 0;
    time_t enqueuedAt = 0;
};

class LLMDirectiveHandler
{
public:
    // Thread-safe, no game-object access: pulls {"directive":{...}} out of the
    // raw sidecar response body. Returns false when absent or malformed.
    static bool ExtractDirective(const std::string& rawResponse, PendingDirective& directive);

    static void Enqueue(uint32_t botGuid, const PendingDirective& directive);
    static std::vector<PendingDirective> Drain(uint32_t botGuid);

    // World thread only. Re-validates requester/whitelist/freshness, then routes
    // to HandleCommand / ChangeStrategy / Group::ChangeLeader.
    static void Execute(Player* bot, PlayerbotAI* ai, const PendingDirective& directive);

private:
    static std::string ExtractJsonStringValue(const std::string& object, const std::string& key);

    static std::mutex queueMutex;
    static std::unordered_map<uint32_t, std::vector<PendingDirective>> queues;
};
```

- [ ] **Step 2: Create `playerbot/LLMDirectiveHandler.cpp`:**

```cpp
#include "playerbot/LLMDirectiveHandler.h"

#include "playerbot/playerbot.h"
#include "playerbot/PlayerbotAIConfig.h"

#include <algorithm>

std::mutex LLMDirectiveHandler::queueMutex;
std::unordered_map<uint32_t, std::vector<PendingDirective>> LLMDirectiveHandler::queues;

namespace
{
    const time_t DIRECTIVE_MAX_AGE_SECONDS = 10;

    bool IsValidMark(const std::string& mark)
    {
        static const std::vector<std::string> marks =
            { "star", "circle", "diamond", "triangle", "moon", "square", "cross", "skull" };
        return std::find(marks.begin(), marks.end(), mark) != marks.end();
    }
}

std::string LLMDirectiveHandler::ExtractJsonStringValue(const std::string& object, const std::string& key)
{
    size_t keyPos = object.find("\"" + key + "\"");
    if (keyPos == std::string::npos)
        return "";
    size_t colon = object.find(':', keyPos);
    if (colon == std::string::npos)
        return "";
    size_t openQuote = object.find('"', colon);
    if (openQuote == std::string::npos)
        return "";
    size_t closeQuote = object.find('"', openQuote + 1);
    if (closeQuote == std::string::npos)
        return "";
    return object.substr(openQuote + 1, closeQuote - openQuote - 1);
}

bool LLMDirectiveHandler::ExtractDirective(const std::string& rawResponse, PendingDirective& directive)
{
    size_t keyPos = rawResponse.find("\"directive\"");
    if (keyPos == std::string::npos)
        return false;
    size_t start = rawResponse.find('{', keyPos);
    if (start == std::string::npos)
        return false;
    int depth = 0;
    size_t end = start;
    for (; end < rawResponse.size(); end++)
    {
        if (rawResponse[end] == '{') depth++;
        if (rawResponse[end] == '}' && --depth == 0) break;
    }
    if (end >= rawResponse.size())
        return false;

    std::string object = rawResponse.substr(start, end - start + 1);
    directive.verb = ExtractJsonStringValue(object, "verb");
    if (directive.verb.empty())
        return false;

    size_t argsPos = object.find("\"args\"");
    if (argsPos != std::string::npos)
    {
        size_t argsStart = object.find('{', argsPos);
        size_t argsEnd = argsStart == std::string::npos ? std::string::npos : object.find('}', argsStart);
        if (argsStart != std::string::npos && argsEnd != std::string::npos)
        {
            std::string argsObject = object.substr(argsStart, argsEnd - argsStart + 1);
            std::string mark = ExtractJsonStringValue(argsObject, "mark");
            if (!mark.empty())
                directive.args["mark"] = mark;
        }
    }
    return true;
}

void LLMDirectiveHandler::Enqueue(uint32_t botGuid, const PendingDirective& directive)
{
    std::lock_guard<std::mutex> lock(queueMutex);
    queues[botGuid].push_back(directive);
}

std::vector<PendingDirective> LLMDirectiveHandler::Drain(uint32_t botGuid)
{
    std::lock_guard<std::mutex> lock(queueMutex);
    auto it = queues.find(botGuid);
    if (it == queues.end())
        return {};
    std::vector<PendingDirective> result = std::move(it->second);
    queues.erase(it);
    return result;
}

void LLMDirectiveHandler::Execute(Player* bot, PlayerbotAI* ai, const PendingDirective& directive)
{
    if (time(nullptr) - directive.enqueuedAt > DIRECTIVE_MAX_AGE_SECONDS)
        return;

    Player* requester = sObjectAccessor.FindPlayer(ObjectGuid(HIGHGUID_PLAYER, directive.requesterGuid));
    if (!requester || !requester->IsInWorld())
        return;

    Group* group = bot->GetGroup();
    bool sameGroup = group && requester->GetGroup() == group;
    bool trusted = sPlayerbotAIConfig.llmCommandTrustedGuids.find(directive.requesterGuid)
        != sPlayerbotAIConfig.llmCommandTrustedGuids.end();
    if (!sameGroup && !trusted)
        return;

    const std::string& verb = directive.verb;
    if (verb == "role_tank")
        ai->HandleCommand(CHAT_MSG_WHISPER, "co +tank,-dps", *requester);
    else if (verb == "role_heal")
        ai->HandleCommand(CHAT_MSG_WHISPER, "co +heal,-dps", *requester);
    else if (verb == "role_dps")
        ai->HandleCommand(CHAT_MSG_WHISPER, "co +dps,-tank,-heal", *requester);
    else if (verb == "follow")
    {
        if (group && group->IsLeader(bot->GetObjectGuid()) && sameGroup)
            group->ChangeLeader(requester->GetObjectGuid());
        ai->HandleCommand(CHAT_MSG_WHISPER, "follow", *requester);
    }
    else if (verb == "stay")
        ai->HandleCommand(CHAT_MSG_WHISPER, "stay", *requester);
    else if (verb == "guard")
        ai->HandleCommand(CHAT_MSG_WHISPER, "guard", *requester);
    else if (verb == "flee")
        ai->HandleCommand(CHAT_MSG_WHISPER, "flee", *requester);
    else if (verb == "attack")
    {
        auto markIt = directive.args.find("mark");
        if (markIt != directive.args.end() && IsValidMark(markIt->second))
        {
            ai->HandleCommand(CHAT_MSG_WHISPER, "rti " + markIt->second, *requester);
            ai->HandleCommand(CHAT_MSG_WHISPER, "attack rti target", *requester);
        }
        else
            ai->HandleCommand(CHAT_MSG_WHISPER, "attack my target", *requester);
    }
    else if (verb == "lead")
    {
        if (group && sameGroup && !group->IsLeader(bot->GetObjectGuid()))
            group->ChangeLeader(bot->GetObjectGuid());
        // Stop shadowing the master and let the travel logic walk the dungeon.
        ai->ChangeStrategy("-follow,+travel", BotState::BOT_STATE_NON_COMBAT);
    }
    else if (verb == "loot")
        ai->HandleCommand(CHAT_MSG_WHISPER, "loot", *requester);
    else if (verb == "release")
        ai->HandleCommand(CHAT_MSG_WHISPER, "release", *requester);
    else if (verb == "come")
        ai->HandleCommand(CHAT_MSG_WHISPER, "summon", *requester);
    else if (verb == "give_leader")
        ai->HandleCommand(CHAT_MSG_WHISPER, "give leader", *requester);
    else if (verb == "reset")
        ai->HandleCommand(CHAT_MSG_WHISPER, "reset ai soft", *requester);
    else
        sLog.outBasic("LLMDirectiveHandler: ignoring unknown verb '%s' for bot %s",
            verb.c_str(), bot->GetName());
}
```

- [ ] **Step 3: Self-check references** (no compile available): confirm every symbol used exists — `sObjectAccessor.FindPlayer(ObjectGuid(HIGHGUID_PLAYER, ...))` (`SayAction.cpp:516`), `HandleCommand`/`ChangeStrategy` signatures (`PlayerbotAI.h:373,383`), `Group::ChangeLeader`/`IsLeader` (`PlayerbotMgr.cpp:439-441`), `sLog.outBasic` (used throughout module). Verify includes: `playerbot/playerbot.h` is the module's umbrella header (used by other root-level `playerbot/*.cpp` files — check one, e.g. `PlayerbotFactory.cpp`, and match its include style exactly).

Run: `grep -n '#include' /workspace/playerbots/playerbot/PlayerbotFactory.cpp | head -5`
Expected: shows the umbrella-include convention to copy.

- [ ] **Step 4: Commit**

```bash
cd /workspace/playerbots && git add playerbot/LLMDirectiveHandler.h playerbot/LLMDirectiveHandler.cpp
git commit -m "feat(playerbot): LLMDirectiveHandler - directive parse, queue, execute"
```

---

### Task 8: C++ SayAction wiring (`<group>` placeholder + GUID plumbing) — WRITE-ONLY

**Files:**
- Modify: `playerbot/strategy/actions/SayAction.h:37` (signature), `playerbot/strategy/actions/SayAction.cpp` (placeholder ~line 540, call site ~line 654, function body ~line 422), `playerbot/strategy/actions/RpgSubActions.cpp:549` (second call site)

**Interfaces:**
- Consumes: `LLMDirectiveHandler::ExtractDirective/Enqueue` (Task 7), `sPlayerbotAIConfig.llmCommandsEnabled` (Task 9).
- Produces: `<group>` placeholder (roster wire format `Name:guid:Class Name:level;...` — must match Task 1's parser); `GenerateResponsePackets(..., bool debug, uint32 botGuid, uint32 requesterGuid)`.

- [ ] **Step 1: Add the `<group>` placeholder** — in `SayAction.cpp`, directly after the two `GetAIChatPlaceholders(...)` calls (~line 541), add:

```cpp
                std::string groupRoster;
                if (Group* botGroup = bot->GetGroup())
                {
                    for (GroupReference* ref = botGroup->GetFirstMember(); ref; ref = ref->next())
                    {
                        Player* member = ref->getSource();
                        if (!member)
                            continue;
                        if (!groupRoster.empty())
                            groupRoster += ";";
                        groupRoster += member->GetName();
                        groupRoster += ":" + std::to_string(member->GetObjectGuid().GetCounter());
                        groupRoster += ":" + ChatHelper::formatClass(member->getClass());
                        groupRoster += ":" + std::to_string(member->GetLevel());
                    }
                }
                placeholders["<group>"] = groupRoster;
```

(`GroupReference` iteration pattern matches `SayAction.cpp:67`; `ChatHelper::formatClass` is already used in this file.)

- [ ] **Step 2: Extend `GenerateResponsePackets`** — in `SayAction.h:37`, change the declaration to append two parameters:

```cpp
        static delayedPackets GenerateResponsePackets(const std::string json
            , const WorldPacket chatTemplate, const WorldPacket emoteTemplate, const WorldPacket systemTemplate, const std::string startPattern, const std::string endPattern, const std::string deletePattern, const std::string splitPattern, bool debug, uint32 botGuid, uint32 requesterGuid);
```

In `SayAction.cpp` (~line 422), update the definition to match, add `#include "playerbot/LLMDirectiveHandler.h"` to the top of the file, and insert directly after the `PlayerbotLLMInterface::Generate(...)` call (~line 432):

```cpp
    if (sPlayerbotAIConfig.llmCommandsEnabled && botGuid)
    {
        PendingDirective directive;
        if (LLMDirectiveHandler::ExtractDirective(response, directive))
        {
            directive.requesterGuid = requesterGuid;
            directive.enqueuedAt = time(nullptr);
            LLMDirectiveHandler::Enqueue(botGuid, directive);
        }
    }
```

- [ ] **Step 3: Update both call sites.** `SayAction.cpp:654` — append arguments (the surrounding code has `bot` and `player`, the speaker):

```cpp
                futurePackets futPackets = std::async(std::launch::async, ChatReplyAction::GenerateResponsePackets, json, chatTemplate, emoteTemplate, systemTemplate, startPattern, endPattern, deletePattern, splitPattern, debug, bot->GetObjectGuid().GetCounter(), player->GetObjectGuid().GetCounter());
```

`RpgSubActions.cpp:549` — NPC/rpg chatter must never execute directives; append `, 0, 0`:

```cpp
    futPackets = std::async(std::launch::async, ChatReplyAction::GenerateResponsePackets, json, chatTemplate, emoteTemplate, systemTemplate, startPattern, endPattern, deletePattern, splitPattern, debug, 0, 0);
```

(Defaulted parameters do not work through `std::async`, so both call sites pass all arguments explicitly.)

- [ ] **Step 4: Self-check** — reread the diff (`git diff`): the signature, definition, and both call sites all have 11 parameters in the same order; `player` at the SayAction call site is the speaker (verify against the `player != bot` check ~line 535).

- [ ] **Step 5: Commit**

```bash
cd /workspace/playerbots && git add playerbot/strategy/actions/SayAction.h playerbot/strategy/actions/SayAction.cpp playerbot/strategy/actions/RpgSubActions.cpp
git commit -m "feat(playerbot): group roster placeholder and directive extraction wiring"
```

---

### Task 9: C++ config options — WRITE-ONLY

**Files:**
- Modify: `playerbot/PlayerbotAIConfig.h`, `playerbot/PlayerbotAIConfig.cpp`

**Interfaces:**
- Produces: `sPlayerbotAIConfig.llmCommandsEnabled` (`bool`), `sPlayerbotAIConfig.llmCommandTrustedGuids` (`std::unordered_set<uint32>`).

- [ ] **Step 1: Header** — in `PlayerbotAIConfig.h`, next to the existing `llm*` members (search for `llmEnabled`), add:

```cpp
    bool llmCommandsEnabled;
    std::unordered_set<uint32> llmCommandTrustedGuids;
```

Add `#include <unordered_set>` at the top if not already present.

- [ ] **Step 2: Loading** — in `PlayerbotAIConfig.cpp`, next to the other LLM options (~line 654), add:

```cpp
    llmCommandsEnabled = config.GetIntDefault("AiPlayerbot.LLMCommands.Enable", 0);
    llmCommandTrustedGuids.clear();
    std::list<uint32> llmCommandTrustedList;
    LoadList<std::list<uint32>>(config.GetStringDefault("AiPlayerbot.LLMCommands.TrustedGuids", ""), llmCommandTrustedList);
    llmCommandTrustedGuids.insert(llmCommandTrustedList.begin(), llmCommandTrustedList.end());
```

(`LoadList` pattern: `PlayerbotAIConfig.cpp:42,165`.)

- [ ] **Step 3: Commit**

```bash
cd /workspace/playerbots && git add playerbot/PlayerbotAIConfig.h playerbot/PlayerbotAIConfig.cpp
git commit -m "feat(playerbot): LLMCommands.Enable and TrustedGuids config"
```

---

### Task 10: C++ drain hook in `UpdateAIInternal` — WRITE-ONLY

**Files:**
- Modify: `playerbot/PlayerbotAI.cpp` (in `UpdateAIInternal`, `PlayerbotAI.cpp:1128`)

**Interfaces:**
- Consumes: `LLMDirectiveHandler::Drain/Execute` (Task 7), `sPlayerbotAIConfig.llmCommandsEnabled` (Task 9).

- [ ] **Step 1: Implement** — add `#include "playerbot/LLMDirectiveHandler.h"` to `PlayerbotAI.cpp`. In `UpdateAIInternal`, immediately after the chat-replies scoped-lock block (the `{ std::scoped_lock lock(chatRepliesMutex); ... }` block starting ~line 1141), insert:

```cpp
    // conversational-command directives parsed from sidecar replies (M3)
    if (sPlayerbotAIConfig.llmCommandsEnabled)
    {
        for (const PendingDirective& directive : LLMDirectiveHandler::Drain(bot->GetObjectGuid().GetCounter()))
            LLMDirectiveHandler::Execute(bot, this, directive);
    }
```

- [ ] **Step 2: Self-check** — `Execute` runs on the world thread here (UpdateAIInternal), which is the only place it may be called; the drain is guarded by the same config flag as enqueue, so disabled servers never touch the queue map.

- [ ] **Step 3: Commit**

```bash
cd /workspace/playerbots && git add playerbot/PlayerbotAI.cpp
git commit -m "feat(playerbot): drain and execute LLM directives on world thread"
```

---

### Task 11: Conf pack + pick-bots.ps1 player GUIDs

**Files:**
- Create: `humanlike/conf/m3-commands.conf.example`
- Modify: `humanlike/scripts/pick-bots.ps1`

**Interfaces:**
- Consumes: meta JSON shape (`humanlike/conf/m2-sidecar.conf.example:9`), Task 2's `player_guids` toml key.
- Produces: M3 conf file; pick-bots writes `player_guids` into `sidecar/config.toml` and prints the `TrustedGuids` conf line.

- [ ] **Step 1: Create `humanlike/conf/m3-commands.conf.example`** — copy `m2-sidecar.conf.example`, then: (a) in the `AiPlayerbot.LLMApiJson` line, extend the `meta` object with `"group":"<group>"` (insert after `"event":"chat"`); (b) append:

```ini
# --- M3: conversational commands -------------------------------------------
# Bots act on party requests ("can you tank?") via sidecar directives.
AiPlayerbot.LLMCommands.Enable = 1
# Your own character GUIDs (characters.guid). Whispered commands outside a
# group are only obeyed from these. pick-bots.ps1 prints this line for you.
AiPlayerbot.LLMCommands.TrustedGuids =
```

(c) update the header comment at the top of the file to say it supersedes the M2 example when running M3.

- [ ] **Step 2: Extend `pick-bots.ps1`.** Change the character query (line 59) to fetch GUIDs too:

```powershell
    $rows = & $mysqlPath -h $dbHost -u $dbUser -N -B -e "SELECT guid, name FROM characters ORDER BY name" $dbName
```

Parse into parallel arrays right after the `$LASTEXITCODE` check (replacing the current `$names = @($names | ...)` line):

```powershell
$guids = @(); $names = @()
foreach ($row in @($rows | Where-Object { $_ })) {
    $cols = $row -split "`t"
    if ($cols.Count -ge 2) { $guids += $cols[0]; $names += $cols[1] }
}
```

The companion-pick section (steps 4-6) keeps working on `$names` unchanged. After section 5 (inner_circle write, line ~112), add a player-character pick that reuses the same numbered list and selection parser:

```powershell
# --- 5b. player_guids in sidecar\config.toml ---------------------------------
$playerSel = Read-Host "Which characters are YOURS (the human's)? (numbers/ranges, e.g. 2)"
$playerIdx = @()
foreach ($part in $playerSel.Split(',')) {
    $part = $part.Trim()
    if ($part -match '^(\d+)-(\d+)$') { $playerIdx += ([int]$Matches[1])..([int]$Matches[2]) }
    elseif ($part -match '^\d+$') { $playerIdx += [int]$part }
}
$playerGuids = @($playerIdx | Sort-Object -Unique |
    Where-Object { $_ -ge 1 -and $_ -le $names.Count } |
    ForEach-Object { $guids[$_ - 1] })
if ($playerGuids.Count -gt 0) {
    $guidList = ($playerGuids | ForEach-Object { '"' + $_ + '"' }) -join ", "
    $playerLine = "player_guids = [$guidList]"
    $lines = Get-Content $configToml
    $replaced = $false
    $lines = $lines | ForEach-Object {
        if ($_ -match '^\s*player_guids\s*=') { $replaced = $true; $playerLine } else { $_ }
    }
    if (-not $replaced) { $lines = @($lines) + $playerLine }
    Set-Content -Path $configToml -Value $lines -Encoding ASCII
    Write-Status "done" "player_guids updated in sidecar\config.toml"
    Write-Host ""
    Write-Host "Add this line to your aiplayerbot.conf (see m3-commands.conf.example):"
    Write-Host ("  AiPlayerbot.LLMCommands.TrustedGuids = " + ($playerGuids -join ","))
} else {
    Write-Status "skipped" "No player characters selected - whisper commands stay group-only"
}
```

- [ ] **Step 3: Syntax-check the script** (PowerShell unavailable here, so parse-check via pwsh if present, else careful reread):

Run: `command -v pwsh && pwsh -NoProfile -Command "[void][System.Management.Automation.Language.Parser]::ParseFile('/workspace/playerbots/humanlike/scripts/pick-bots.ps1', [ref]$null, [ref]$err); $err" || echo "pwsh not available - reread diff manually"`
Expected: no parse errors reported, or manual reread confirms balanced braces/quotes and PS 5.1-only syntax.

- [ ] **Step 4: Commit**

```bash
cd /workspace/playerbots && git add humanlike/conf/m3-commands.conf.example humanlike/scripts/pick-bots.ps1
git commit -m "feat(humanlike): M3 conf example and player-guid picker"
```

---

### Task 12: README — M3 setup + verification checklist

**Files:**
- Modify: `humanlike/README.md` (after the M2 sections; match the existing `### 3. Verify (M1 checklist)` / `### 4. Verify (M2 checklist)` style)

- [ ] **Step 1: Write the M3 section** — append a new top-level section mirroring the M2 one's structure:

```markdown
## M3 — Conversational commands

Bots act on party requests: "can you tank?", "lead the way", "kill the skull
target". Requires the M2 sidecar setup plus:

1. Switch your `aiplayerbot.conf` LLM block to `conf/m3-commands.conf.example`
   (adds `"group"` to the request meta and enables `LLMCommands`).
2. Re-run `scripts/pick-bots.ps1` — it now also asks which characters are
   *yours*, writes `player_guids` into `sidecar\config.toml`, and prints the
   `AiPlayerbot.LLMCommands.TrustedGuids` line to paste into the conf.
3. Rebuild the server from this branch (new files: `playerbot/LLMDirectiveHandler.*`;
   re-run CMake configure so the glob picks them up), restart everything via
   `scripts/start.ps1`.

### 5. Verify (M3 checklist)

In a party with your bots (warrior + healer recommended), in party chat:

- [ ] "can you tank this dungeon?" → the warrior answers in character AND
      switches to tank strategies (check with `co ?` whisper: `tank` listed)
- [ ] "someone heal me" → exactly ONE bot (the healer) responds with action;
      others at most banter, no double role-switch
- [ ] Mark a mob skull, "Grimtok kill the skull" → bot attacks the marked mob
- [ ] "lead the way" in a dungeon → bot takes group lead and walks; "follow me"
      → bot returns lead and resumes following
- [ ] Whisper a companion (not in your group) "come here" → bot obeys
      (TrustedGuids works out-of-group)
- [ ] From a character NOT in `player_guids` and not grouped, whisper a command
      → chat reply, but NO action
- [ ] Drop a bot's sentiment below the threshold (repeated insults, or set
      `sentiment_threshold = 999` temporarily) → command is refused in character,
      no action; set `always_obey = true` in `[commands]` → bot complies again
- [ ] Kill the sidecar mid-session → bots keep fighting normally, no chat, no
      actions, no server errors
- [ ] `python -m brain.replay requests.jsonl` on a recorded command shows a
      `directive:` line
```

Adjust numbering/heading levels to match the file's actual structure when editing.

- [ ] **Step 2: Commit**

```bash
cd /workspace/playerbots && git add humanlike/README.md
git commit -m "docs(humanlike): M3 setup and verification checklist"
```

---

## Self-Review Notes (already applied)

- **Spec coverage:** every spec section maps to a task — roster meta (T1/T8), two-step brain (T3/T4), directive field (T6/T8), sentiment refusal (T4/T6), dedup/best-fit (T4), bot-to-bot + cascade guard (T4), C++ parse/queue/world-thread execute (T7/T8/T10), config + kill-switches (T2/T9), conf pack + scripts (T11), testing (per-task + T12 checklist). The spec's "TrustedGuids in sync with inner_circle" is refined to player-character GUIDs — rationale in File Structure section; flag to Andreas at review.
- **Type consistency:** `PendingDirective` fields match between T7 (definition) and T8/T10 (use); `Intent`/`Decision` names match T3→T4→T6; roster wire format identical in T1 (parser) and T8 (producer); `format=None` kwarg consistent across FakeOllama updates (T3/T4/T6) and `OllamaClient` (T3).
- **Known risk accepted:** `lead` movement strategy (`-follow,+travel`) is the one mapping in-game verification may overturn (checklist item covers it); if the bot stands still, the fallback to try is `+rpg` or making lead rely on `dungeon` strategy alone — a one-line change in `LLMDirectiveHandler.cpp`.
