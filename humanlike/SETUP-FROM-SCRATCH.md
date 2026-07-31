# Humanlike/LLM Playerbots — From-Scratch Setup Guide (Windows + Docker)

**Target:** cmangos vanilla (WoW 1.12) server + playerbots fork with humanlike/LLM bots (M1–M3) running in Docker Desktop, Ollama running natively on the host for RTX 3090 GPU access, the WoW 1.12 client connecting, and M3 conversational commands verified in-game.

> **⚠️ Known-unverified steps.** Two things in this guide have never been exercised on a real desktop:
>
> 1. **The first `docker compose build` is the first-ever GCC compile of the M3 C++** (it has been compiled by neither GCC nor MSVC). Compile errors are *expected* to surface here — this build is the real syntax gate. Fix errors in the fork source and rebuild.
> 2. The compose stack was only validated statically (Docker was unavailable in the dev container), and the **M3 in-game checklist is still pending** — your first session *is* the verification run.

---

## 1. Prerequisites

All of this happens on the Windows desktop (the RTX 3090 machine).

### 1.1 Hardware / OS

- Windows desktop with an NVIDIA RTX 3090 (the chat model `mistral-small3.2` is a 24B model, ~14 GB VRAM at Q4 — the 3090's 24 GB is comfortable).
- Windows PowerShell 5.1 is sufficient for all scripts (no PowerShell 7 required).

### 1.2 Docker Desktop

1. Install Docker Desktop for Windows (WSL2 backend, which is the default). The docs require only Docker Desktop with BuildKit — no specific WSL2 memory/CPU sizing or `.wslconfig` is prescribed, but the first build compiles a C++ core, so don't starve WSL2 of RAM/CPU.

2. Verify it works:

```powershell
# PowerShell (Windows host)
docker version
docker compose version
```

> You should see client and server versions with no errors.

### 1.3 Ollama — **native on the host, NOT in Docker**

Ollama must run natively on Windows so it gets direct GPU access; the containerized sidecar reaches it at `http://host.docker.internal:11434`.

1. Install Ollama for Windows from ollama.com (it runs automatically as a service on Windows).
2. Pull **exactly** these two model tags (they are what the sidecar config references):

```powershell
# PowerShell (Windows host)
ollama pull mistral-small3.2
ollama pull qwen3:4b
```

- `mistral-small3.2` = `chat_model` (full LLM treatment for inner-circle bots)
- `qwen3:4b` = `utility_model` (ambient banter + memory summarization)

3. Verify Ollama is up:

```powershell
# PowerShell (Windows host)
curl.exe http://127.0.0.1:11434/api/tags
```

> You should see JSON listing both models. (Use `curl.exe`, not PowerShell's `curl` alias.)

### 1.4 Git

Install Git for Windows (git-scm.com) so you can clone the fork.

### 1.5 MySQL client (for pick-bots.ps1)

`pick-bots.ps1` needs a `mysql.exe`. It searches PATH, then common install paths (`C:\Program Files\MySQL\MySQL Server 8.0/8.4/5.7\bin\mysql.exe`, `C:\Program Files\MariaDB 10.6/11.4\bin\mysql.exe`), and finally prompts you for a full path. Install any MySQL or MariaDB client if you don't have one.

### 1.6 WoW 1.12 client + SPP client data

- You need a **WoW 1.12 vanilla client** (the core is a pinned cmangos vanilla core — the SPP Classics vanilla module).
- You need the **SPP Classics repack** installed somewhere (e.g. `C:\spp-classics`) — specifically its `Modules\vanilla` folder, which contains the extracted server-side client data: `maps/`, `dbc/`, `vmaps/`, `mmaps/`. This folder is bind-mounted into the server container; nothing is copied or extracted in-container.

> Confirm now that `C:\spp-classics\Modules\vanilla` (or your equivalent) contains all four subfolders `maps`, `dbc`, `vmaps`, `mmaps`. If it doesn't, mangosd will exit with map/dbc errors later.

---

## 2. Get the code

1. Clone the fork and check out the humanlike branch:

```powershell
# PowerShell (Windows host)
cd C:\
git clone https://github.com/andreas-skag/playerbots.git
cd C:\playerbots
git checkout feature/humanlike-llm-bots
```

2. Orientation — everything you touch lives under `humanlike\`:

- `humanlike\docker\` — the **canonical setup** (compose stack). This replaces the deprecated native-Windows flow (`humanlike\scripts\setup.ps1` / `start.ps1` are deprecated in place; **`pick-bots.ps1` is NOT deprecated** and is still used).
- `humanlike\docker\README.md` — the canonical doc this guide follows.
- `humanlike\docker\conf.example\` — config templates (`aiplayerbot.conf`, `config.toml`, `llm_character_card.txt`, `mangosd.conf`, `realmd.conf`).

**All `docker compose` commands in this guide must be run from `humanlike\docker`** (that's where `docker-compose.yml` lives; the compose project name is `humanlike-playerbots`).

---

## 3. Supply client data

Nothing to copy — the data is bind-mounted read-only.

- **Source:** your SPP repack's `Modules\vanilla` folder (must contain `maps/ dbc/ vmaps/ mmaps/`), e.g. `C:\spp-classics\Modules\vanilla`.
- **Destination:** mounted into the mangosd container at `/data` (compose mounts `${CLIENT_DATA_DIR}:/data:ro`; the server conf sets `DataDir = "/data"`).
- **You configure this via one variable:** `CLIENT_DATA_DIR` in `.env` (next section). **The path must use forward slashes, even on Windows:** `C:/spp-classics/Modules/vanilla`.

---

## 4. Configure

1. Go to the docker directory:

```powershell
# PowerShell (Windows host)
cd C:\playerbots\humanlike\docker
```

2. Create `.env` from the example:

```powershell
# PowerShell (Windows host)
copy .env.example .env
notepad .env
```

Edit these keys:

| Key | What to do |
|---|---|
| `CLIENT_DATA_DIR` | **MUST edit.** Set to your SPP data folder with **forward slashes**, e.g. `CLIENT_DATA_DIR=C:/spp-classics/Modules/vanilla`. Folder must contain `maps/ dbc/ vmaps/ mmaps/`. |
| `MYSQL_ROOT_PASSWORD=mangosroot` | Leave default (this is also the password you'll type into pick-bots.ps1 later). |
| `MANGOS_DB_PASSWORD=mangos` | Leave default. If you change it, you must also change the password field in every `DatabaseInfo` line of `conf/mangosd.conf` and `conf/realmd.conf`, and passwords must be **alphanumeric only** (they are written into a sourced shell config). |
| `OLLAMA_URL=http://host.docker.internal:11434` | **Informational only** — the sidecar actually reads `ollama_url` from `conf/config.toml`. Keep the two in sync. |
| `#CMANGOS_REF=` | Leave commented out. Only set to deliberately override the pinned cmangos core commit. |

3. Create the live `conf/` directory from the templates (containers mount `./conf` read-only at `/opt/mangos/etc`; `conf/` is gitignored — it's your personalization):

```powershell
# PowerShell (Windows host)
Copy-Item -Recurse conf.example conf
```

4. What's in `conf/` and what to change **now** vs **later**:

- `conf/mangosd.conf`, `conf/realmd.conf` — leave as-is unless you changed `MANGOS_DB_PASSWORD` (the second `mangos` in each `...;mangos;mangos;...` DatabaseInfo line is the password).
- `conf/aiplayerbot.conf` — already correct for Docker: `AiPlayerbot.LLMEnabled = 2`, `AiPlayerbot.LLMApiEndpoint = http://sidecar:8000/v1/chat/completions` (compose service name — do **not** change to 127.0.0.1:8085; that was the deprecated native flow), `AiPlayerbot.LLMCommands.Enable = 1`, `AiPlayerbot.LLMDefaultPromptsFile = /opt/mangos/etc/llm_character_card.txt` (must stay an **absolute** path — the loader opens it relative to the process cwd). The one key you can't fill yet: `AiPlayerbot.LLMCommands.TrustedGuids =` — filled in step 7 after `pick-bots.ps1` prints it.
- `conf/config.toml` (sidecar) — already correct for Docker (`ollama_url = "http://host.docker.internal:11434"`, `chat_model = "mistral-small3.2"`, `utility_model = "qwen3:4b"`, `db_path = "/app/data/brain.db"`, `request_log = "/app/data/requests.jsonl"`, `[commands] enabled = true`). You'll fill `inner_circle = []` and `player_guids = []` in step 7. **Warning:** unknown keys in this file raise `ValueError` at sidecar startup. The valid `[commands]` keys are: `enabled`, `always_obey`, `sentiment_threshold`, `dedup_window_s`, `actor_ttl_s`, `allow_bot_commanders` — adding any of those is safe (you'll use two of them in the M3 checklist).
- `conf/llm_character_card.txt` — per-bot personality cards; edited in step 7 once you know your bot names.

Because conf mounts are read-only, all future config edits are: edit `conf\...` on the host, then `docker compose restart mangosd` (or `realmd` / `sidecar`) — never a rebuild.

---

## 5. First build & run

> ⚠️ This is the **known-unverified first-ever GCC compile of the M3 C++** flagged at the top. Budget 30–60 minutes for the core compile and expect that compile errors, if any, surface here.

1. **Build the `sqlsource` image FIRST.** This is mandatory: `Dockerfile.dbinit` does `FROM humanlike-docker-server-sqlsource`, an image that only exists after the build-only `sqlsource` service is built. Skipping this yields `pull access denied for humanlike-docker-server-sqlsource`.

```powershell
# PowerShell (Windows host), in C:\playerbots\humanlike\docker
docker compose build sqlsource
docker compose up -d --build
```

(First build: 30–60 min — it clones cmangos mangos-classic at a pinned commit, builds with `-DBUILD_PLAYERBOTS=ON` against the fork copied in-tree, using ccache so later rebuilds take minutes. Note: the build FetchContent-downloads zlib, so the build needs network access.)

> You should see all images build without error, then containers start: `db` (mariadb:10.11), `db-init` (one-shot), `sidecar`, `realmd`, `mangosd`. Compose ordering guarantees realmd/mangosd wait for the db healthcheck **and** db-init completing; mangosd also waits for the sidecar to start.

2. Watch the database install (installs full classic-db plus playerbots tables, then exits):

```powershell
# PowerShell (Windows host), in humanlike\docker
docker compose logs -f db-init
```

> You should see `db-init: installing full classic-db (this takes a few minutes)...`, the classic-db `InstallFullDB.sh -InstallAll root <pw> DeleteAll` run, and finally the line `db-init: done`.
>
> **The sentinel:** on success db-init creates the table `classicmangos._dbinit_complete`. On every later `docker compose up`, db-init sees the marker, prints `db-init: install marker present - nothing to do`, and exits 0 — the DB is never re-installed. A crash mid-install leaves no marker, so init simply re-runs (the `DeleteAll` argument makes reruns safe).

3. Confirm the world server is up and actually contains the fork:

```powershell
# PowerShell (Windows host), in humanlike\docker
docker compose logs mangosd
```

> You should see `AiPlayerbot` config lines in the log — this guards against the server image not containing the fork. You should NOT see map/dbc errors (if you do, see Troubleshooting: `CLIENT_DATA_DIR`).

Ports published to the host (all loopback-only): realmd auth `127.0.0.1:3724`, mangosd world `127.0.0.1:8085`, MariaDB `127.0.0.1:3306` (for pick-bots.ps1). The sidecar's port 8000 is internal-only (only mangosd calls it).

---

## 6. Create accounts & connect the client

1. Attach to the mangosd console and create your account:

```powershell
# PowerShell (Windows host), in humanlike\docker
docker compose attach mangosd
```

```text
# mangosd console (inside the attached session)
account create youruser yourpass
```

> You should see the console confirm the account was created.

**Detach with `Ctrl-P` then `Ctrl-Q`.** A plain `Ctrl-C` in the attached console **restarts the server** (compose restarts it via `restart: unless-stopped`); to actually stop it use `docker compose stop mangosd`.

> **Note on GM level:** no `account set gmlevel` step is documented anywhere in this project's docs — plain `account create` is the entire documented account flow. If you want GM powers, that's standard cmangos console usage outside this guide's scope; nothing in the M1–M3 checklists requires it.

2. Point the client at the server. Edit `realmlist.wtf` in your WoW 1.12 client folder:

```text
set realmlist 127.0.0.1
```

3. Launch the client, log in with the account you created, and create a character.

> You should reach character creation, enter the world, and see the world load (this proves the client-data mount works).

---

## 7. Bots up

### 7.1 Pick your companion bots (pick-bots.ps1)

Run this **after the db container is up** (it queries MariaDB at `127.0.0.1:3306`) and after bot characters exist in the characters DB. It takes no parameters — everything is interactive.

```powershell
# PowerShell (Windows host)
cd C:\playerbots\humanlike\scripts
powershell -ExecutionPolicy Bypass -File pick-bots.ps1
```

Answer the prompts:

- **DB host** `[127.0.0.1]` → accept default (Enter)
- **DB user** `[root]` → accept default
- **Characters DB name** `[classiccharacters]` → accept default
- **DB password** (input hidden, never stored) → `mangosroot` (your `MYSQL_ROOT_PASSWORD` from `.env`)

Then:

1. It lists every character (`SELECT guid, name FROM characters ORDER BY name`), numbered.
2. **"Pick your companion bots (numbers/ranges, e.g. 1,3,7-9)"** — a warrior (tank) + a healer are recommended for the M3 checklist.
3. **"Which characters are YOURS (the human's)?"** — pick your own character(s). This is what makes out-of-group whisper commands work; if you skip it, it prints `[skipped] No player characters selected - whisper commands stay group-only`.

The script writes `inner_circle = ["Name", ...]` and `player_guids = ["guid", ...]` into `sidecar\config.toml` at the repo root, appends `Name:: ` card stubs to `humanlike\llm_character_card.txt`, and prints the line to copy:

```text
AiPlayerbot.LLMCommands.TrustedGuids = <guid1>,<guid2>
```

### 7.2 Carry the results into the Docker conf (important gotcha)

The containerized sidecar mounts `humanlike\docker\conf\config.toml`, **not** `sidecar\config.toml`, and pick-bots.ps1's final "re-run setup.ps1" hint refers to the deprecated native flow. So do this by hand:

1. Copy the `inner_circle = [...]` and `player_guids = [...]` lines from `sidecar\config.toml` into `humanlike\docker\conf\config.toml` (replacing the empty `inner_circle = []` / `player_guids = []` lines). `inner_circle` bots always get the full LLM treatment even outside party/guild — plain `/say` near a bot only builds memory if the bot is listed.
2. Paste the printed `AiPlayerbot.LLMCommands.TrustedGuids = <guids>` value into `humanlike\docker\conf\aiplayerbot.conf` (the key already exists, empty).

### 7.3 Character cards

Edit `humanlike\docker\conf\llm_character_card.txt`. Format: one line per bot, `CharacterName:: personality text`. The name must **exactly** match a character on your realm, or the server logs `Character 'X' not found` and skips the line. The five shipped entries (Grimtok, Elaria, Baldrek, Miravelle, Zenrik) are style examples, e.g.:

```text
Grimtok:: Personality: gruff orc veteran, terse and dry, secretly softhearted. Speech: short clipped sentences, calls everyone "whelp" affectionately. Quirk: complains his old axe was better than any upgrade. Attitude: respects deeds, not words.
```

> **Cards vs sidecar personas:** the sidecar auto-generates a persona per bot. A bot with a card gets **both** personalities in its prompt, often contradictory. Recommended: let the sidecar personas rule — keep each line as just `Name::` with nothing after (the loader then replaces any stored card with empty text; merely unsetting `LLMDefaultPromptsFile` is NOT enough, because already-loaded cards persist). Alternative for hand-written personalities — overwrite the sidecar persona instead:
>
> ```powershell
> # PowerShell (Windows host), in humanlike\docker
> docker compose exec sidecar python -c "from brain.memory import MemoryStore; MemoryStore('/app/data/brain.db').set_persona(<guid>, 'Personality: ...')"
> ```

### 7.4 Apply the config

```powershell
# PowerShell (Windows host), in humanlike\docker
docker compose restart mangosd sidecar
```

> You should see in `docker compose logs mangosd`: `Loaded N LLM character personalities from llm_character_card.txt` (with N = number of non-comment card lines).

Note: out-of-group whisper commands from TrustedGuids additionally require the bot to be **on your own account** — the server's PlayerbotSecurity layer (GM, same account, or same group) enforces this independently. A bot on a different account replies "Invite me to your group first". Group commands are unaffected.

---

## 8. Verify M1 → M2 → M3

Under Docker, M1's plumbing (chat) and M2's plumbing (sidecar) are already wired, so these checklists collapse into a single in-game verification pass. Everything marked "party chat" is typed in `/p` in the WoW client.

### 8.1 M1-level: basic LLM chat

1. Ollama is already running as a Windows service. Stand next to a bot and:

```text
# WoW client chat
/say hello
```

> You should get an in-character reply within a few seconds.

2. Whisper (`/w`) a bot that has a card → the reply should reflect its card personality.
3. Party up with a bot, chat in `/p` → it replies in party chat.
4. Wait near two bots (with `LLMBotToBotChatChance > 0`) → occasional bot-to-bot banter.
5. If replies look wrong, enable per-bot debugging:

```text
# WoW client chat
/w <bot> co +debug llm
```

> The bot whispers back prompt/response details.

### 8.2 M2-level: sidecar memory & personas

1. Party up with a bot, chat in `/p` → reply arrives AND the sidecar log grows one line per message:

```powershell
# PowerShell (Windows host), in humanlike\docker
docker compose exec sidecar sh -c "wc -l /app/data/requests.jsonl"
```

2. Reply reflects an auto-generated persona. Inspect it:

```powershell
# PowerShell (Windows host), in humanlike\docker
docker compose exec sidecar python -c "from brain.memory import MemoryStore; print(MemoryStore('/app/data/brain.db').get_persona(<guid>))"
```

3. Say something memorable ("I'll give you this axe"), chat ~30 more exchanges → a summary appears (the `summaries` table) and the bot can reference it later.
4. Restart everything (`docker compose restart mangosd sidecar`), whisper the same bot → it still knows you (summary + sentiment survived on the `sidecar-data` volume).
5. Chat as a stranger (non-inner-circle bot, plain world chat) → a reply still comes (ambient tier) but no `interactions` row is added.
6. Kill the sidecar mid-session (`docker compose stop sidecar`) → bots go silent but nothing crashes; `docker compose up -d sidecar` → chat resumes.

### 8.3 M3: conversational commands (the 9-step checklist)

Run in a **party with your bots** (warrior + healer recommended), commands in **party chat** unless noted:

1. `can you tank this dungeon?` → the warrior answers in character **and** switches to tank strategies. Verify:

```text
# WoW client chat
/w <warrior-bot> co ?
```

> You should see `tank` in the listed strategies.

2. `someone heal me` → exactly **one** bot (the healer) responds with action; others at most banter, no double role-switch.
3. Mark a mob with skull, then `Grimtok kill the skull` (use your bot's name) → that bot attacks the marked mob.
4. `lead the way` in a dungeon → bot takes group lead and walks; `follow me` → bot returns lead and resumes following.
5. **Out of group:** whisper a companion bot `come here` → bot obeys (TrustedGuids works out-of-group). This passes **only** when the bot is on your own account; a bot on a different account replies "Invite me to your group first" — expected behavior (PlayerbotSecurity), not a bug.
6. From a character **not** in `player_guids` and not grouped, whisper a command → chat reply, but **no action**.
7. **Refusal + kill-switch:** drop a bot's sentiment below threshold (repeated insults, or temporarily set `sentiment_threshold = 999` in the `[commands]` section of `conf/config.toml` and restart the sidecar) → command is refused in character, no action. Then set `always_obey = true` in `[commands]` (the refusal kill-switch: skips sentiment-based refusals entirely), restart the sidecar → bot complies again. (Both are valid `[commands]` keys — no `ValueError` risk.)
8. Kill the sidecar mid-session → bots keep fighting normally: no chat, no actions, no server errors.
9. Replay a recorded command:

```powershell
# PowerShell (Windows host), in humanlike\docker
docker compose exec sidecar python -m brain.replay /app/data/requests.jsonl
```

> You should see a reply **plus** a `directive:` line.

---

## 9. Day-2 operations

All from `C:\playerbots\humanlike\docker` in PowerShell.

**Start / stop (db-init does NOT re-run):**

```powershell
# PowerShell (Windows host)
docker compose up -d
docker compose down
```

The `dbdata` volume persists, so on the next `up` db-init sees the `_dbinit_complete` marker and exits immediately (`db-init: install marker present - nothing to do`).

**Logs / console:**

```powershell
# PowerShell (Windows host)
docker compose logs mangosd
docker compose logs -f db-init
docker compose attach mangosd    # detach: Ctrl-P Ctrl-Q; Ctrl-C restarts the server
docker compose stop mangosd      # the actual way to stop the world server
```

**Update the code (fork C++ changes):**

```powershell
# PowerShell (Windows host), in C:\playerbots
git pull
cd humanlike\docker
docker compose build mangosd
docker compose up -d
```

> ccache makes this minutes, not the initial 30–60. If you change `CMANGOS_REF` in `.env`, you must also re-run `docker compose build sqlsource` so db-init's `/core-tree` matches.

**Sidecar (Python) changes:**

```powershell
# PowerShell (Windows host)
docker compose build sidecar
docker compose up -d sidecar
```

**Conf changes (no rebuild ever):** edit files under `humanlike\docker\conf\`, then `docker compose restart mangosd` (or `realmd` / `sidecar`).

**Full DB reset — destroys characters AND bot memories (brain.db):**

```powershell
# PowerShell (Windows host)
docker compose down -v
docker compose up -d
```

**Backup the data volumes** (generic Docker technique — not project-specific; stop the stack first for a consistent snapshot). The compose project is named `humanlike-playerbots`, so the volumes are `humanlike-playerbots_dbdata` (MariaDB) and `humanlike-playerbots_sidecar-data` (brain.db + requests.jsonl):

```powershell
# PowerShell (Windows host)
docker compose down
docker run --rm -v humanlike-playerbots_dbdata:/from -v ${PWD}/backup:/to debian:bookworm-slim tar czf /to/dbdata.tar.gz -C /from .
docker run --rm -v humanlike-playerbots_sidecar-data:/from -v ${PWD}/backup:/to debian:bookworm-slim tar czf /to/sidecar-data.tar.gz -C /from .
docker compose up -d
```

---

## 10. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `pull access denied for humanlike-docker-server-sqlsource` | You skipped the mandatory first step: run `docker compose build sqlsource` **before** `docker compose up -d --build`. Also required again after changing `CMANGOS_REF`. |
| mangosd exits with map/dbc ("map data not found") errors | `CLIENT_DATA_DIR` in `.env` doesn't point at a folder containing `maps/ dbc/ vmaps/ mmaps/`. Fix the variable (forward slashes!), `docker compose up -d` — no rebuild needed. |
| Bots don't chat | Test Ollama from inside the stack: `docker compose exec sidecar python -c "import httpx; print(httpx.get('http://host.docker.internal:11434/api/tags', timeout=5).status_code)"` — `200` means connectivity is fine (look elsewhere); otherwise allow Docker through the Windows firewall or check Ollama is running. Ollama being unreachable degrades safely: bots go silent, nothing crashes. |
| Changed a conf file but nothing happened | Conf mounts are **read-only**; the containers never see in-container edits. Edit `humanlike\docker\conf\` on the host, then `docker compose restart mangosd` (or `realmd` / `sidecar`). |
| Sidecar ignores the Ollama URL you set in `.env` | `OLLAMA_URL` in `.env` is informational only — the effective value is `ollama_url` in `conf/config.toml`. Keep them in sync. |
| Sidecar crash-loops at startup with `ValueError` | Unknown key in `conf/config.toml` — the sidecar rejects keys it doesn't know (the error message lists the valid keys). Remove the stray key and `docker compose restart sidecar`. |
| Server log: `Character 'X' not found` for a card line | Name in `llm_character_card.txt` doesn't exactly match a realm character. Fix the name, restart mangosd. |
| Bot personality is incoherent/contradictory | Card + auto-generated sidecar persona are both in the prompt. Blank the card lines to `Name::` and restart (unsetting `LLMDefaultPromptsFile` alone is NOT enough — loaded cards persist in `ai_playerbot_db_store`; direct purge: `DELETE FROM ai_playerbot_db_store WHERE value LIKE 'manual saved string::llmdefaultprompt>%';` on the characters DB). |
| Out-of-group whisper command → "Invite me to your group first" | The bot is on a different account. PlayerbotSecurity requires GM, same account, or same group — put companion bots on your own account for out-of-group commands. Expected behavior, not a bug. |
| Changed `MANGOS_DB_PASSWORD`, servers can't connect to DB | You must also update the password field in every `DatabaseInfo` line of `conf/mangosd.conf` and `conf/realmd.conf` (format `db;3306;mangos;<password>;<dbname>`). Alphanumeric passwords only. |
| pick-bots.ps1: `mysql query failed - check host/user/password/database name` | Wrong password (use `MYSQL_ROOT_PASSWORD`, default `mangosroot`), or the db container isn't up yet, or wrong DB name (default `classiccharacters`). |
| pick-bots.ps1 ran but the containerized sidecar doesn't see inner_circle/player_guids | It writes to `sidecar\config.toml` at the repo root; the Docker sidecar mounts `humanlike\docker\conf\config.toml`. Copy the two lines over and restart the sidecar. |
| Pressed Ctrl-C in the mangosd console and the server "died" | It restarted (`restart: unless-stopped`). Detach with `Ctrl-P Ctrl-Q`; stop with `docker compose stop mangosd`. |
| First build fails during zlib download | zlib is FetchContent'd by the core CMake (not apt-installed) — the Docker build needs network access. |
| M1-style direct-endpoint debugging | Check the mangosd console for `BotLLM:` errors; sanity-test Ollama's OpenAI endpoint: `curl.exe http://127.0.0.1:11434/v1/chat/completions -d "{\"model\":\"mistral-small3.2\",\"messages\":[{\"role\":\"user\",\"content\":\"hi\"}]}"` must return JSON with a `content` field (PowerShell's `curl` alias won't work — use `curl.exe`). |
| Copied config from the old native scripts | Do **not** reuse the native sidecar port `8085` — it collides with mangosd's world port. The Docker flow uses `http://sidecar:8000/v1/chat/completions`, already set in `conf/aiplayerbot.conf`. |
