# Docker Runtime for Server + Sidecar: Design

Date: 2026-07-21
Status: approved (brainstormed with Andreas; approach and both design sections approved in conversation)
Related: `2026-07-19-humanlike-llm-bots-design.md` (architecture), `2026-07-20-m3-conversational-commands-design.md` (M3), `2026-07-20-windows-setup-scripts-design.md` (superseded native flow)
Branch: `feature/humanlike-llm-bots`

## Goal

Andreas runs the whole stack in Docker on their desktop instead of natively on
Windows: one `docker compose up` brings up MariaDB, db-init, realmd, mangosd
(built from this fork against a pinned cmangos core), and the Python sidecar.
Ollama stays native on Windows for direct RTX 3090 access. The WoW client
connects to `127.0.0.1` as before.

## Decisions made during brainstorming

- **Scope:** server + DB + sidecar in one compose stack (approved Approach A:
  self-contained multi-stage build in the fork). Ollama native, reached via
  `host.docker.internal:11434`.
- **Client data:** bind-mount the SPP repack's `Modules/vanilla`
  (maps/dbc/vmaps/mmaps) read-only via a `CLIENT_DATA_DIR` variable in `.env`.
  No copying, no in-container extraction.
- **Database:** fresh `classic-db` via `InstallFullDB.sh` with
  `PLAYERBOTS_DB=YES` in a one-shot idempotent init container. Nothing to
  migrate — the native flow never went live.
- **Native scripts:** Docker-first. `setup.ps1`/`start.ps1` get deprecation
  headers pointing at the Docker flow and are no longer maintained.
  `pick-bots.ps1` survives unchanged in spirit — it targets the MariaDB
  container's published port (localhost:3306) from Windows.
- **Toolchain note (accepted):** the desktop compile target becomes GCC/Linux
  inside the build stage instead of MSVC. The M3 C++ has been compiled by
  neither; the first `docker compose build` is the real syntax gate.

## Layout — everything under `humanlike/docker/`

| Artifact | Responsibility |
|---|---|
| `Dockerfile.server` | Multi-stage. **Build stage:** Debian + toolchain + ccache; `git clone` `cmangos/mangos-classic` at pinned build-arg `CMANGOS_REF`; copy this fork (build context = repo root) into `src/modules/PlayerBots`; `cmake -DBUILD_PLAYERBOTS=ON -DCMAKE_INSTALL_PREFIX=/opt/mangos`; build with a BuildKit cache mount for ccache + build dir. **Runtime stage:** slim Debian, `mangosd` + `realmd` binaries + runtime libs. Core `sql/` tree exported as a labeled stage for db-init. |
| `Dockerfile.sidecar` | `python:3.11-slim`; installs `sidecar/` (context `sidecar/`). |
| `docker-compose.yml` | The five services below; builds reference the two Dockerfiles. |
| `.env.example` | The only personalization: `CLIENT_DATA_DIR` (Windows path to SPP `Modules/vanilla`), DB password, optional Ollama URL override (default `http://host.docker.internal:11434`), optional `CMANGOS_REF` override. |
| `conf.example/` | Templates copied once to gitignored `conf/`: `mangosd.conf`, `realmd.conf`, `aiplayerbot.conf` (docker variant of the M3 conf — `LLMApiEndpoint = http://sidecar:8000/v1/chat/completions`, the compose service name), sidecar `config.toml` (ollama_url = host.docker.internal), `llm_character_card.txt`. Mounted read-only. |
| `db-init/` | One-shot init entrypoint script (below). |
| `README.md` | Canonical setup path + desktop verification checklist. |

`setup.ps1` and `start.ps1` receive deprecation comment headers referencing
`humanlike/docker/README.md`.

## Compose services

- **`db`** — `mariadb:10.11` (LTS), named volume `dbdata`, healthcheck,
  port published as `127.0.0.1:3306` so `pick-bots.ps1` keeps working from
  Windows.
- **`db-init`** — one-shot; `depends_on: db: condition: service_healthy`.
  Image derives from the server build's sql artifact stage plus a pinned-ref
  `classic-db` clone. Writes `InstallFullDB.config` (`PLAYERBOTS_DB=YES`,
  `CORE_PATH` at the artifact, credentials from compose env) and runs
  `InstallFullDB.sh`. **Idempotent:** exits 0 immediately if the world DB
  exists and `creature_template` is populated. Full reset = documented
  `docker compose down -v` (destroys DB volume and bot memories) then `up`.
- **`realmd`** — port 3724, `depends_on` db healthy + db-init completed.
- **`mangosd`** — port 8085, `tty: true` + `stdin_open: true` (attachable
  server console), `restart: unless-stopped`, mounts: `CLIENT_DATA_DIR`
  read-only, `conf/` read-only, a logs volume. Same `depends_on` as realmd.
- **`sidecar`** — internal port 8000 (not published; only mangosd calls it),
  mounts `conf/config.toml` and a named volume for `brain.db` so bot
  memories survive image rebuilds.

Client connects with `set realmlist 127.0.0.1` — `InstallFullDB`'s default
realmlist address already matches since ports are published to localhost.

## Iteration flow

- Fork C++ change → `docker compose build mangosd` → ccache/BuildKit cache
  mount means only changed translation units recompile (first build
  ~30-60 min; incremental typically minutes) → `docker compose up -d`.
- Sidecar change → rebuild of the small Python image, seconds.
- Core bump → edit `CMANGOS_REF` in one place, deliberate.

## Error handling

| Failure | Behavior |
|---|---|
| DB not ready / init incomplete | `depends_on` conditions hold realmd/mangosd back |
| Re-running db-init | sentinel check → exit 0, no-op |
| Ollama unreachable from containers (firewall) | M2 degradation — bots silent, no crashes; README documents the `docker compose exec sidecar` connectivity one-liner against `host.docker.internal` |
| `CLIENT_DATA_DIR` wrong/missing | mangosd's normal "map data not found" exit; README maps the symptom to the variable |
| Bad conf edit | host-side fix in `conf/`; mounts are read-only, no rebuild |
| mangosd crash | `restart: unless-stopped` |

## Testing

- **In-container (here):** `docker compose config`-level validation of the
  compose file (Docker itself is unavailable — validate YAML/spec
  statically), shellcheck on `db-init` and entrypoint scripts, and
  cross-checks of every conf template key against the real parsers
  (PlayerbotAIConfig option names, sidecar `Settings` keys, M3 conf
  requirements — the four-key M3 block with the sidecar service URL).
- **Desktop checklist (README):** first `docker compose build` succeeds
  (GCC syntax gate for the M3 C++); `up` reaches healthy; db-init log shows
  playerbots tables; realm login from the Windows client; bots spawn;
  sidecar answers a chat completion; one in-game M3 command round-trip.
  This folds the still-pending M3 in-game checklist into the same desktop
  session.

## Out of scope

- GPU-in-container Ollama (native Ollama already works; revisit only if
  Andreas moves Ollama into Docker themselves).
- CI builds of the image, multi-arch images, registry publishing.
- Migrating any existing native-Windows install (none exists).
- Removing `setup.ps1`/`start.ps1` (deprecated in place, kept as fallback).
