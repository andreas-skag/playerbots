# Human-like LLM bots — setup guide

Companion files for the design in
`docs/superpowers/specs/2026-07-19-humanlike-llm-bots-design.md`.
All steps below run on the **target Windows machine** (RTX 3090).

## Milestone 1 — LLM chat direct to Ollama (no code changes)

### Automated setup (recommended)

From the repo checkout, in PowerShell:

```powershell
cd humanlike\scripts
powershell -ExecutionPolicy Bypass -File setup.ps1            # install + configure (M1)
powershell -ExecutionPolicy Bypass -File pick-bots.ps1        # choose companion bots from your DB
# edit humanlike\llm_character_card.txt (personality per bot), then:
powershell -ExecutionPolicy Bypass -File setup.ps1            # re-run to deploy the cards
powershell -ExecutionPolicy Bypass -File start.ps1            # start Ollama (add -Server to also start the game server)
```

`setup.ps1` is idempotent — re-running it skips finished steps. It backs up
`aiplayerbot.conf` (timestamped `.bak-*`) before patching. The manual steps
below do the same things by hand and serve as reference/fallback.

### 1. Install Ollama and pull models

Install from https://ollama.com/download/windows, then:

```powershell
ollama pull mistral-small3.2   # 24B, ~14 GB VRAM at Q4 — main chat model
ollama pull qwen3:14b          # lighter/faster alternative, worth A/B testing
```

Keep whichever you prefer; put its exact tag in the `"model"` field of
`AiPlayerbot.LLMApiJson`.

Note: qwen3 models default to 'thinking' mode under Ollama, which slows
replies and can leak reasoning text; prefer mistral-small3.2, or disable
thinking if you use qwen3.

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
errors; `curl.exe http://127.0.0.1:11434/v1/chat/completions -d
"{\"model\":\"mistral-small3.2\",\"messages\":[{\"role\":\"user\",\"content\":\"hi\"}]}"` 
must return JSON with a `"content"` field. (PowerShell's built-in `curl`
alias won't work — use `curl.exe`.)

## Milestone 2 — brain sidecar (personas + relationship memory)

### Automated setup (recommended)

After rebuilding the server from this branch (step 1 below — the rebuild
itself is not automated):

```powershell
cd humanlike\scripts
powershell -ExecutionPolicy Bypass -File setup.ps1 -Milestone M2   # models, venv, config, conf patch
powershell -ExecutionPolicy Bypass -File start.ps1                 # Ollama + sidecar (add -Server for the game server)
```

The manual steps below are the reference/fallback.

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

Requires Python 3.11+ on the target machine (`python --version`).

```powershell
cd <checkout>\sidecar
python -m venv .venv
.venv\Scripts\pip install -e .
copy config.example.toml config.toml   # then edit inner_circle etc.
.venv\Scripts\uvicorn --factory brain.server:create_app --host 127.0.0.1 --port 8085
```

Add your regular companion bots to `inner_circle` — party/guild/whisper chat
always builds memory, but plain /say near a bot only does if the bot is
listed.

### 3. Point the game server at it

In `aiplayerbot.conf`, replace the two keys shown in
`humanlike/conf/m2-sidecar.conf.example` (endpoint + ApiJson). Restart mangosd.

### Note: character cards vs sidecar personas

The sidecar generates a persona per bot automatically. If you kept M1's
`llm_character_card.txt`, a bot with a card gets BOTH personalities in its
prompt (the card via the server, the generated one via the sidecar) — they
will often contradict each other. Pick one:

- **Prefer the sidecar (recommended):** blank the card text while keeping
  the file configured — edit `llm_character_card.txt` so each line is just
  the name (e.g. `Grimtok::` with nothing after the `::`) and restart; the
  loader then replaces the stored card with empty text. (Just emptying
  `AiPlayerbot.LLMDefaultPromptsFile` is NOT enough — already-loaded cards
  persist in the `ai_playerbot_db_store` table. Alternatively purge them
  directly: `DELETE FROM ai_playerbot_db_store WHERE value LIKE 'manual
  saved string::llmdefaultprompt>%';` on the characters DB.)
- **Keep your hand-written cards:** copy each card into the sidecar so it
  replaces the generated persona:
  `.venv\Scripts\python -c "from brain.memory import MemoryStore; MemoryStore('brain.db').set_persona(<guid>, 'Personality: ...your card text...')"`

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
8. Script check: run `setup.ps1 -Milestone M2` a second time — every step
   should print `[skipped]` or `[done]` with no duplicate LLM block in
   `aiplayerbot.conf` (search for exactly one `BEGIN humanlike-llm block`).
9. Script check: run `start.ps1` while everything is already running - Ollama
   reports `[ok] Ollama is up` and the other services report
   `[ok] ... already running`.

## M3 — Conversational commands

Bots act on party requests: "can you tank?", "lead the way", "kill the skull
target". Requires the M2 sidecar setup plus:

### 1. Switch your configuration

In `aiplayerbot.conf`, add or replace the four keys shown in
`humanlike/conf/m3-commands.conf.example` (LLMApiEndpoint, LLMApiJson,
LLMCommands.Enable, LLMCommands.TrustedGuids), keeping the rest of your
existing M1/M2 LLM block intact. This adds `"group"` to the request meta and
enables `LLMCommands`. Note that out-of-group whisper commands from
TrustedGuids additionally require the bot to be on your own account — the
server's PlayerbotSecurity layer enforces this independently of
LLMDirectiveHandler's own gate; group commands are unaffected.

### 2. Re-run scripts/pick-bots.ps1

Re-run `scripts/pick-bots.ps1` — it now also asks which characters are *yours*,
writes `player_guids` into `sidecar\config.toml`, and prints the
`AiPlayerbot.LLMCommands.TrustedGuids` line to paste into the conf.

### 3. Rebuild the server

Rebuild `mangosd` from this branch on the target machine (new files:
`playerbot/LLMDirectiveHandler.h` and `playerbot/LLMDirectiveHandler.cpp`;
re-run CMake configure so the glob picks them up), then restart everything via
`scripts/start.ps1`.

### 4. Verify (M3 checklist)

In a party with your bots (warrior + healer recommended), in party chat:

1. "can you tank this dungeon?" → the warrior answers in character AND
   switches to tank strategies (check with `co ?` whisper: `tank` listed)
2. "someone heal me" → exactly ONE bot (the healer) responds with action;
   others at most banter, no double role-switch
3. Mark a mob skull, "Grimtok kill the skull" → bot attacks the marked mob
4. "lead the way" in a dungeon → bot takes group lead and walks; "follow me"
   → bot returns lead and resumes following
5. Whisper a companion (not in your group) "come here" → bot obeys
   (TrustedGuids works out-of-group). This passes only when that companion
   bot is on your own account — for a bot on a different account, the reply
   is "Invite me to your group first"; that is current expected behavior
   (PlayerbotSecurity requires GM, same account, or same group), not a bug
6. From a character NOT in `player_guids` and not grouped, whisper a command
   → chat reply, but NO action
7. Drop a bot's sentiment below the threshold (repeated insults, or set
   `sentiment_threshold = 999` temporarily) → command is refused in character,
   no action; set `always_obey = true` in `[commands]` → bot complies again
8. Kill the sidecar mid-session → bots keep fighting normally, no chat, no
   actions, no server errors
9. `.venv\Scripts\python -m brain.replay requests.jsonl` on a recorded command
   shows a `directive:` line
