# Docker runtime (canonical setup)

Runs MariaDB, db-init, realmd, mangosd (built from this fork against a pinned
cmangos core) and the brain sidecar in one compose stack. Ollama stays native
on this machine for GPU access. Replaces the deprecated native-Windows flow
(`../scripts/setup.ps1` / `start.ps1`).

## One-time setup

1. Install Docker Desktop. Ollama runs natively with your models pulled
   (`mistral-small3.2`, `qwen3:4b`).
2. `cd humanlike/docker`
3. `cp .env.example .env` and set `CLIENT_DATA_DIR` to your SPP repack's
   `Modules/vanilla` folder (forward slashes).
4. `cp -r conf.example conf` (PowerShell: `Copy-Item -Recurse conf.example conf`).
   Fill in character cards in `conf/llm_character_card.txt` and, once you have
   picked companions, the `AiPlayerbot.LLMCommands.TrustedGuids` line in
   `conf/aiplayerbot.conf` (pick-bots.ps1 prints it — run it against
   `localhost:3306` once the db container is up).
5. First build + start (30-60 min for the core compile):
   `docker compose build sqlsource && docker compose up -d --build`
6. Watch db-init: `docker compose logs -f db-init` — it installs the full
   classic-db with the playerbots tables, then exits.
7. Windows client: `set realmlist 127.0.0.1` — then log in and create your
   account via the mangosd console:
   `docker compose attach mangosd` then `account create <user> <pass>`
   (detach with Ctrl-P Ctrl-Q — plain Ctrl-C stops the server).

## Daily use

- Start: `docker compose up -d` · Stop: `docker compose down`
- Rebuild after fork C++ changes: `docker compose build mangosd && docker compose up -d`
  (ccache makes this minutes, not the initial 30-60)
- Sidecar changes: `docker compose build sidecar && docker compose up -d sidecar`
- Server console: `docker compose attach mangosd`
- Full DB reset (destroys characters AND bot memories):
  `docker compose down -v && docker compose up -d`

## Troubleshooting

- **mangosd exits with map/dbc errors** → `CLIENT_DATA_DIR` in `.env` doesn't
  point at a folder containing `maps/ dbc/ vmaps/ mmaps`.
- **Bots don't chat** → test Ollama from inside the stack:
  `docker compose exec sidecar python -c "import httpx; print(httpx.get('http://host.docker.internal:11434/api/tags', timeout=5).status_code)"`
  → `200` means connectivity is fine; otherwise allow Docker through the
  firewall or check Ollama is running.
- **Changed a conf** → files are mounted read-only; edit `conf/` on the host
  and `docker compose restart mangosd` (or realmd/sidecar).
- **Ollama URL mismatch** → the effective Ollama URL for the sidecar lives in
  `conf/config.toml` (key `ollama_url`). The `.env` file's `OLLAMA_URL` is
  informational; keep them in sync.

## Desktop verification checklist (first run — includes pending M3 items)

- [ ] `docker compose build` completes (GCC is the first-ever compile of the
      M3 C++ — fix errors here)
- [ ] `docker compose up -d` reaches healthy; `db-init` log ends with "done"
      and mentions playerbots tables
- [ ] Client logs in via `127.0.0.1`; world loads (client data mount works)
- [ ] Bots spawn and chat (sidecar round-trip through host Ollama)
- [ ] The full M3 in-game checklist in `../README.md` §M3 passes (tank
      request, someone-heal single actor, marked-target attack, lead/follow,
      refusal, sidecar-kill degradation)
- [ ] `docker compose exec sidecar python -m brain.replay /app/data/requests.jsonl`
      prints a reply + `directive:` line
