# Windows Setup/Start Automation Scripts — Design

**Date:** 2026-07-20
**Status:** Approved by Andreas
**Parent feature:** Human-like LLM bots M1+M2 (`2026-07-19-humanlike-llm-bots-design.md`); lands on `feature/humanlike-llm-bots` / PR #1.

## Goal

Collapse the manual target-machine setup in `humanlike/README.md` into three PowerShell scripts so the repeatable ~90% is one command each, leaving only bot-name choices and in-game verification manual.

Out of scope: smoke-test script (declined), SPP-style launcher menu (possible later wrapper), building mangosd itself, Linux/macOS support.

## Architecture

Three single-purpose PowerShell scripts in `humanlike/scripts/`, sharing a git-ignored settings file. PowerShell 5.1-compatible (preinstalled on Windows 10/11; no pwsh 7 requirement).

```
humanlike/scripts/
  setup.ps1       one-time install & configure (idempotent, re-runnable)
  start.ps1       per-session ordered startup with health checks
  pick-bots.ps1   DB-driven bot-name picker → config.toml + character cards
  settings.json   (git-ignored) { serverDir, chatModel, utilityModel, dbHost, dbUser, dbName }
```

`settings.json` is created/updated by `setup.ps1` and `pick-bots.ps1`, read by all three. No passwords are ever stored.

## Components

### setup.ps1

Parameters: `-Milestone M1|M2` (default `M1`), `-ServerDir <path>` (else prompted once and saved).

Steps, each idempotent with a `[done]/[skipped]/[FAILED]` status line:
1. Check `winget` exists → if Ollama not on PATH, `winget install Ollama.Ollama`; else skip.
2. `ollama pull` the chat model and (M2 only) utility model. Models default to `mistral-small3.2` / `qwen3:4b`, overridable via saved settings.
3. M2 only: check `python --version` ≥ 3.11 (actionable error otherwise); create `sidecar\.venv` if absent; `pip install -e .`; copy `config.example.toml` → `config.toml` if absent.
4. Resolve server dir (parameter > saved setting > prompt; validated: must contain `mangosd.exe` or `aiplayerbot.conf`, warn-and-confirm otherwise). Save to `settings.json`.
5. Patch `<serverDir>\aiplayerbot.conf`: write timestamped backup (`aiplayerbot.conf.bak-yyyyMMdd-HHmmss`), delete all existing uncommented `AiPlayerbot.LLM*` lines, append the full block from `humanlike/conf/m1-ollama-direct.conf.example` or `m2-sidecar.conf.example` per `-Milestone` (M2 = M1 block with the two overridden keys applied). Marker comments (`# BEGIN/END humanlike-llm block`) delimit the block so re-runs replace rather than duplicate.
6. Copy `humanlike\llm_character_card.txt` to the server dir (skip + warn if a newer file already exists there — don't clobber user edits).
7. Print summary + next steps (edit cards / run pick-bots / run start).

### start.ps1

Parameters: `-Server` (also start mangosd+realmd), `-Milestone M1|M2` (default: infer M2 if `sidecar\config.toml` exists).

1. Ollama: GET `http://127.0.0.1:11434/api/tags`; if unreachable, start `ollama serve` in a new window and poll up to 30 s. ✓/✗ line.
2. M2: start sidecar in a new window (`.venv\Scripts\uvicorn --factory brain.server:create_app --host 127.0.0.1 --port 8085`, cwd `sidecar\`); poll TCP 8085 up to 15 s. Skip cleanly in M1 mode.
3. `-Server` only: start `realmd.exe` then `mangosd.exe` from `serverDir`, each in its own window. No health polling (mangosd startup is long and interactive).
4. Fail fast: any ✗ stops the sequence with the failing URL/command and the likely fix.

### pick-bots.ps1

1. Locate `mysql.exe` (PATH, else common install dirs, else prompt for path).
2. Connection: defaults host `127.0.0.1`, user `root`, DB `classiccharacters`; all overridable; password via `Read-Host -AsSecureString`, passed with `MYSQL_PWD` env var (not on command line), never stored.
3. `SELECT name FROM characters ORDER BY name` → numbered list → user picks by numbers/ranges (e.g. `1,3,7-9`).
4. Writes:
   - `sidecar\config.toml`: replace the `inner_circle = [...]` line with the picked names (file created from example first if absent).
   - `humanlike\llm_character_card.txt`: append `Name:: ` stub lines for picked bots not already present (existing card lines untouched).
5. Reminds: flesh out the card stubs, then re-run `setup.ps1` (or copy the file) to deploy; restart server to reload cards.

### README integration

`humanlike/README.md` gets an "Automated setup" section at the top of M1 and M2 (three commands: `setup.ps1`, `pick-bots.ps1`, `start.ps1`), with the existing manual steps kept below as reference/fallback. Execution-policy note included (`powershell -ExecutionPolicy Bypass -File ...`).

## Error handling

- Every external tool (winget, ollama, python, mysql) is checked before use; missing → one actionable line (what to install, where) and non-zero exit.
- Conf patching never runs without a successful backup write.
- No destructive operation lacks either a backup or a skip-if-exists guard.
- Scripts exit non-zero on failure so a future launcher wrapper can chain them.

## Testing

- This machine has no PowerShell: scripts are verified by careful review (syntax, 5.1 compatibility — no `??`, no `-AsPlainText` on 5.1-only APIs, ASCII-safe output) plus a dedicated reviewer pass.
- Real verification is on the target machine: run `setup.ps1` twice (second run must be all `[skipped]`), `start.ps1` cold and warm, `pick-bots.ps1` against the real DB. These steps are appended to the README M1/M2 checklists.
