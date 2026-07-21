# Docker Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One `docker compose up` on Andreas's desktop builds the server from this fork (pinned cmangos core) and runs MariaDB + db-init + realmd + mangosd + sidecar; Ollama stays native.

**Architecture:** Multi-stage `Dockerfile.server` clones `cmangos/mangos-classic` at a pinned ref, copies this fork into `src/modules/PlayerBots`, builds with `-DBUILD_PLAYERBOTS=ON` and ccache cache mounts; a sql-artifact stage feeds an idempotent db-init container running classic-db's `InstallFullDB.sh` with `PLAYERBOTS_DB=YES`. Compose wires five services; host-specific values live in `.env`; sparse conf templates are mounted read-only. Spec: `docs/superpowers/specs/2026-07-21-docker-runtime-design.md`.

**Tech Stack:** Docker/Compose (BuildKit), Debian bookworm, GCC + ccache, CMake, MariaDB 10.11, Python 3.11 (sidecar), bash.

## Global Constraints

- **Docker is NOT available in this container.** Never run `docker`/`docker compose`. Validation here = `bash -n` on shell scripts, YAML parse of compose via pyyaml (install once: `cd /workspace/playerbots/sidecar && .venv/bin/python -m pip install -q pyyaml`), and grep cross-checks of conf keys against the real parsers. Real builds happen on Andreas's desktop.
- All new files live under `humanlike/docker/` except the root `.dockerignore`.
- Pinned refs are build args with defaults: `CMANGOS_REF=master` and `CLASSICDB_REF=master` are FORBIDDEN — pin to concrete commit SHAs. Use `CMANGOS_REF` = the commit currently checked out in the validated core clone: run `git -C /workspace/mangos-classic rev-parse HEAD` and paste the result. For `CLASSICDB_REF` use branch `master` resolved at image build time via `git rev-parse` recorded in the image label — acceptable because classic-db content only moves forward; document this choice in the Dockerfile comment.
- DB names/users are the cmangos defaults and must stay aligned across all files: user `mangos`/password from env, DBs `classicmangos`, `classicrealmd`, `classiccharacters`, `classiclogs` (`mangosd.conf.dist.in:84-87`).
- Sidecar service port is **8000** inside the compose network (`http://sidecar:8000/v1/chat/completions`). Note: the native scripts/conf used 8085, which collides with mangosd's world port — do not copy that value.
- Compose service names are fixed interfaces: `db`, `db-init`, `realmd`, `mangosd`, `sidecar`.
- The character-card file is loaded via plain `ifstream` with the path as given (`PlayerbotAIConfig.cpp:1255-1257`), so the docker conf sets an absolute path: `AiPlayerbot.LLMDefaultPromptsFile = /opt/mangos/etc/llm_character_card.txt`.
- Conf templates are SPARSE (cmangos config getters have defaults for every key) — only set keys that differ from defaults, with comments.
- Sidecar has 68 passing tests; nothing in this plan may modify `sidecar/brain/` or `playerbot/` source. Suite must stay green (only relevant if a task touches sidecar packaging).
- Commit style: `feat(docker): ...` / `docs(humanlike): ...`; commit at the end of every task.

## File Structure

| File | Responsibility |
|---|---|
| `.dockerignore` (repo root, create) | Trim the build context (repo root is the server build context) |
| `humanlike/docker/Dockerfile.sidecar` | Python image for the sidecar |
| `humanlike/docker/Dockerfile.server` | Multi-stage core+module build; runtime stage; `sqlsource` artifact stage |
| `humanlike/docker/Dockerfile.dbinit` | classic-db clone + mariadb-client + core sql artifact + entrypoint |
| `humanlike/docker/db-init/entrypoint.sh` | Sentinel check → write InstallFullDB.config → run installer |
| `humanlike/docker/conf.example/{mangosd.conf,realmd.conf,aiplayerbot.conf,config.toml,llm_character_card.txt}` | Sparse config templates; copied once to gitignored `conf/` |
| `humanlike/docker/docker-compose.yml` | The five services |
| `humanlike/docker/.env.example` | `CLIENT_DATA_DIR`, DB password, Ollama URL, ref overrides |
| `humanlike/docker/.gitignore` | Ignores `conf/` and `.env` |
| `humanlike/docker/README.md` | Canonical setup + desktop verification checklist |
| `humanlike/scripts/setup.ps1`, `start.ps1` (modify, header only) | Deprecation notes |

---

### Task 1: Build context prep + sidecar image

**Files:**
- Create: `.dockerignore` (repo root), `humanlike/docker/Dockerfile.sidecar`, `humanlike/docker/.gitignore`

**Interfaces:**
- Produces: sidecar image runs `uvicorn --factory brain.server:create_app --host 0.0.0.0 --port 8000` with workdir `/app` (config.toml + templates resolved relative to `/app`; `Settings.load("config.toml")` and `templates_dir = "templates"` are relative paths — `settings.py:21`, `settings.py:13`). Compose (Task 5) builds it with context `../..` (repo root) and dockerfile `humanlike/docker/Dockerfile.sidecar`, mounts `conf/config.toml` at `/app/config.toml` and a volume at `/app/data`.

- [ ] **Step 1: Create `.dockerignore` at the repo root:**

```
.git
.superpowers
docs
build*/
sidecar/.venv
sidecar/**/__pycache__
sidecar/*.egg-info
**/*.pyc
humanlike/docker/conf
humanlike/docker/.env
```

- [ ] **Step 2: Create `humanlike/docker/.gitignore`:**

```
conf/
.env
```

- [ ] **Step 3: Create `humanlike/docker/Dockerfile.sidecar`:**

```dockerfile
# Sidecar (brain) image. Build context = repo root:
#   docker compose build sidecar
FROM python:3.11-slim

WORKDIR /app
COPY sidecar/pyproject.toml ./
COPY sidecar/brain ./brain
COPY sidecar/templates ./templates
RUN pip install --no-cache-dir .

# config.toml is mounted at /app/config.toml (compose); brain.db lives on the
# /app/data volume via db_path in that config.
EXPOSE 8000
CMD ["uvicorn", "--factory", "brain.server:create_app", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 4: Validate what is validatable here**

Run: `cd /workspace/playerbots && ls sidecar/pyproject.toml sidecar/brain/server.py sidecar/templates/chat.txt sidecar/templates/intent.txt`
Expected: all four paths exist (the COPY lines reference real paths).
Run: `grep -n "uvicorn" sidecar/pyproject.toml`
Expected: `uvicorn>=0.29` in dependencies (the CMD binary is installed by `pip install .`).

- [ ] **Step 5: Commit**

```bash
cd /workspace/playerbots && git add .dockerignore humanlike/docker/Dockerfile.sidecar humanlike/docker/.gitignore
git commit -m "feat(docker): sidecar image and build-context prep"
```

---

### Task 2: Server image (multi-stage build)

**Files:**
- Create: `humanlike/docker/Dockerfile.server`

**Interfaces:**
- Consumes: repo root as build context (`.dockerignore` from Task 1).
- Produces: runtime image with `/opt/mangos/bin/{mangosd,realmd}`, conf dir `/opt/mangos/etc` (mounted over by compose), expecting client data at `/data` (`DataDir` in Task 4's conf); stage **`sqlsource`** containing `/core-tree/sql` and `/core-tree/src/modules/PlayerBots/sql` for Task 3's `COPY --from`.

- [ ] **Step 1: Get the pinned core ref**

Run: `git -C /workspace/mangos-classic rev-parse HEAD`
Use the printed SHA as the `CMANGOS_REF` default below.

- [ ] **Step 2: Create `humanlike/docker/Dockerfile.server`:**

```dockerfile
# syntax=docker/dockerfile:1
# cmangos classic + PlayerBots module (this repo), built at a pinned core ref.
# Build context = repo root:
#   docker compose build mangosd
# First build ~30-60 min; later builds reuse the ccache mount.

ARG CMANGOS_REF=<SHA-from-step-1>

# ---------- build stage ----------
FROM debian:bookworm-slim AS build
ARG CMANGOS_REF

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential cmake git ca-certificates ccache \
    default-libmysqlclient-dev libssl-dev \
    libboost-program-options-dev libboost-thread-dev libboost-regex-dev \
    libboost-serialization-dev libboost-filesystem-dev \
    && rm -rf /var/lib/apt/lists/*

# Core at the pinned ref (zlib >=1.3.2 is FetchContent'd by the core cmake;
# network is available during build)
RUN git clone https://github.com/cmangos/mangos-classic.git /src/core \
    && git -C /src/core checkout "${CMANGOS_REF}"

# This fork IS the module; the core requires it in-tree BEFORE cmake
# (out-of-tree add_subdirectory lacks a binary dir)
COPY . /src/core/src/modules/PlayerBots

ENV CCACHE_DIR=/ccache
RUN --mount=type=cache,target=/ccache \
    cmake -S /src/core -B /build \
      -DCMAKE_BUILD_TYPE=Release \
      -DCMAKE_INSTALL_PREFIX=/opt/mangos \
      -DBUILD_PLAYERBOTS=ON \
      -DCMAKE_C_COMPILER_LAUNCHER=ccache \
      -DCMAKE_CXX_COMPILER_LAUNCHER=ccache \
    && cmake --build /build -j"$(nproc)" --target install

# ---------- sql artifact stage (consumed by Dockerfile.dbinit) ----------
FROM debian:bookworm-slim AS sqlsource
COPY --from=build /src/core/sql /core-tree/sql
COPY --from=build /src/core/src/modules/PlayerBots/sql /core-tree/src/modules/PlayerBots/sql

# ---------- runtime stage ----------
FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
    libmariadb3 libssl3 \
    libboost-program-options1.74.0 libboost-thread1.74.0 libboost-regex1.74.0 \
    libboost-serialization1.74.0 libboost-filesystem1.74.0 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=build /opt/mangos /opt/mangos
WORKDIR /opt/mangos/bin
# compose overrides the command per service (mangosd vs realmd)
CMD ["./mangosd", "-c", "/opt/mangos/etc/mangosd.conf"]
```

Replace `<SHA-from-step-1>` with the actual SHA. Note: `default-libmysqlclient-dev` on bookworm provides MariaDB client libs — matching the `libmariadb3` runtime package.

- [ ] **Step 3: Validate references**

Run: `grep -n "BUILD_PLAYERBOTS" /workspace/mangos-classic/CMakeLists.txt | head -3`
Expected: the option exists in the core.
Run: `grep -rn "add_subdirectory" /workspace/mangos-classic/src/CMakeLists.txt | head -5`
Expected: confirms the module dir convention (`src/modules/PlayerBots`).
Confirm the four Boost dev packages match the core requirement (`find_package(Boost 1.70.0 REQUIRED COMPONENTS program_options thread regex serialization filesystem)` — CMakeLists.txt:208; bookworm ships Boost 1.74).

- [ ] **Step 4: Commit**

```bash
cd /workspace/playerbots && git add humanlike/docker/Dockerfile.server
git commit -m "feat(docker): multi-stage server image with pinned cmangos core"
```

---

### Task 3: db-init image + entrypoint

**Files:**
- Create: `humanlike/docker/Dockerfile.dbinit`, `humanlike/docker/db-init/entrypoint.sh`

**Interfaces:**
- Consumes: `sqlsource` stage from Task 2 (`/core-tree/...`).
- Produces: one-shot service that exits 0 fast when already initialized. Env consumed (set by compose, Task 5): `MYSQL_HOST=db`, `MYSQL_ROOT_PASSWORD`, `MANGOS_DB_PASSWORD`.

- [ ] **Step 1: Create `humanlike/docker/db-init/entrypoint.sh`:**

```bash
#!/bin/bash
# One-shot DB initializer. Idempotent: exits 0 immediately if the world DB
# is already populated. Full reset: docker compose down -v && docker compose up
set -euo pipefail

MYSQL_HOST="${MYSQL_HOST:-db}"
ROOT_PW="${MYSQL_ROOT_PASSWORD:?MYSQL_ROOT_PASSWORD not set}"
MANGOS_PW="${MANGOS_DB_PASSWORD:?MANGOS_DB_PASSWORD not set}"

mysql_root() {
    mariadb -h "$MYSQL_HOST" -u root -p"$ROOT_PW" -N -B -e "$1"
}

# Sentinel: world DB exists and creature_template is populated
count=$(mysql_root "SELECT COUNT(*) FROM information_schema.tables \
    WHERE table_schema='classicmangos' AND table_name='creature_template'" || echo 0)
if [ "$count" = "1" ]; then
    rows=$(mysql_root "SELECT COUNT(*) FROM classicmangos.creature_template" || echo 0)
    if [ "$rows" -gt 0 ]; then
        echo "db-init: world DB already populated ($rows creature templates) - nothing to do"
        exit 0
    fi
fi

echo "db-init: installing full classic-db (this takes a few minutes)..."
cd /classic-db

cat > InstallFullDB.config <<EOF
DB_HOST="$MYSQL_HOST"
MYSQL_HOST="$MYSQL_HOST"
MYSQL_PORT="3306"
MYSQL_USERNAME="mangos"
MYSQL_PASSWORD="$MANGOS_PW"
MYSQL_USERIP="%"
WORLD_DB_NAME="classicmangos"
REALM_DB_NAME="classicrealmd"
CHAR_DB_NAME="classiccharacters"
LOGS_DB_NAME="classiclogs"
MYSQL_PATH=""
MYSQL_DUMP_PATH=""
CORE_PATH="/core-tree"
LOCALES="YES"
DEV_UPDATES="NO"
AHBOT="NO"
PLAYERBOTS_DB="YES"
FORCE_WAIT="NO"
EOF

./InstallFullDB.sh -InstallAll root "$ROOT_PW"
echo "db-init: done"
```

- [ ] **Step 2: Create `humanlike/docker/Dockerfile.dbinit`:**

```dockerfile
# syntax=docker/dockerfile:1
# One-shot database initializer: classic-db + core sql tree + installer script.
# Build context = repo root. CLASSICDB_REF pinned to master-at-build-time
# (classic-db only moves forward); the resolved SHA is recorded in a label.
FROM debian:bookworm-slim AS clone
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*
RUN git clone --depth 1 https://github.com/cmangos/classic-db.git /classic-db \
    && git -C /classic-db rev-parse HEAD > /classic-db/.pinned-ref

FROM humanlike-docker-server-sqlsource AS sqlsource

FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
    mariadb-client bash \
    && rm -rf /var/lib/apt/lists/*
COPY --from=clone /classic-db /classic-db
COPY --from=sqlsource /core-tree /core-tree
COPY humanlike/docker/db-init/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]
```

Note the `FROM humanlike-docker-server-sqlsource` line references an image tag that compose builds from `Dockerfile.server`'s `sqlsource` stage — Task 5 defines a compose build entry `sqlsource` with `target: sqlsource` and `image: humanlike-docker-server-sqlsource`, and `db-init` gets `depends_on` it for build ordering. (Compose builds cannot `COPY --from` a stage in a *different* Dockerfile without a named image.)

- [ ] **Step 3: Validate**

Run: `bash -n /workspace/playerbots/humanlike/docker/db-init/entrypoint.sh && echo SYNTAX_OK`
Expected: `SYNTAX_OK`.
Cross-check config vars against the installer (fetched during planning): `MYSQL_HOST/PORT/USERNAME/PASSWORD/USERIP`, `WORLD/REALM/CHAR/LOGS_DB_NAME`, `CORE_PATH`, `LOCALES`, `DEV_UPDATES`, `AHBOT`, `PLAYERBOTS_DB`, `FORCE_WAIT` are the documented `InstallFullDB.config` variables; `-InstallAll root <pw>` is the documented non-interactive full install; `PLAYERBOTS_DB=YES` requires `src/modules/PlayerBots/sql` under `CORE_PATH` — provided by the artifact tree.

- [ ] **Step 4: Commit**

```bash
cd /workspace/playerbots && git add humanlike/docker/Dockerfile.dbinit humanlike/docker/db-init/entrypoint.sh
git commit -m "feat(docker): idempotent db-init running InstallFullDB with playerbots DB"
```

---

### Task 4: Conf templates (`conf.example/`)

**Files:**
- Create: `humanlike/docker/conf.example/mangosd.conf`, `realmd.conf`, `aiplayerbot.conf`, `config.toml`, `llm_character_card.txt`

**Interfaces:**
- Consumes: DB names/user (Global Constraints), sidecar service URL, existing conf examples (`humanlike/conf/m1-ollama-direct.conf.example` for the LLM block, `m3-commands.conf.example` for M3 keys), `humanlike/llm_character_card.txt` (copy as-is), `sidecar/config.example.toml` (adapt).
- Produces: sparse confs mounted at `/opt/mangos/etc` (server) and `/app/config.toml` (sidecar). Compose (Task 5) substitutes nothing — files are static; passwords only in `mangosd.conf`/`realmd.conf` DB strings must match `MANGOS_DB_PASSWORD` in `.env`, and the README (Task 6) says so.

- [ ] **Step 1: Create `humanlike/docker/conf.example/mangosd.conf`** (sparse — every unset key uses the compiled default):

```ini
# mangosd — docker overrides only. Copy conf.example/ -> conf/ and edit there.
# The password below must match MANGOS_DB_PASSWORD in your .env.
DataDir = "/data"
LoginDatabaseInfo     = "db;3306;mangos;mangos;classicrealmd"
WorldDatabaseInfo     = "db;3306;mangos;mangos;classicmangos"
CharacterDatabaseInfo = "db;3306;mangos;mangos;classiccharacters"
LogsDatabaseInfo      = "db;3306;mangos;mangos;classiclogs"
Console.Enable = 1
```

- [ ] **Step 2: Create `humanlike/docker/conf.example/realmd.conf`:**

```ini
# realmd — docker overrides only. Password must match MANGOS_DB_PASSWORD.
LoginDatabaseInfo = "db;3306;mangos;mangos;classicrealmd"
```

- [ ] **Step 3: Create `humanlike/docker/conf.example/aiplayerbot.conf`** — assemble from the existing examples, with docker values. Full content:

```ini
# aiplayerbot — docker LLM block (M1 base + M2 sidecar + M3 commands).
# Derived from humanlike/conf/*.conf.example; endpoint uses the compose
# service name. All other AiPlayerbot.* keys use compiled defaults.

AiPlayerbot.LLMEnabled = 2
AiPlayerbot.LLMApiEndpoint = http://sidecar:8000/v1/chat/completions
AiPlayerbot.LLMApiKey =
AiPlayerbot.LLMApiJson = {"model":"brain","messages":[{"role":"system","content":"<pre prompt> <context>"},{"role":"user","content":"<prompt>"}],"max_tokens":120,"meta":{"bot_guid":"<bot guid>","other_guid":"<other guid>","bot_name":"<bot name>","other_name":"<other name>","channel":"<channel name>","event":"chat","group":"<group>"}}
AiPlayerbot.LLMPrePrompt = You are roleplaying <bot name>, a level <bot level> <bot gender> <bot race> <bot class> in World of Warcraft: <expansion name>, currently in <bot subzone> <bot zone>. The <other type> <other name> (<other gender> <other race> <other class>, level <other level>) speaks to you <channel name>. Stay fully in character. Speak plainly and briefly like a real player: 1-2 short sentences, no modern slang, no emoji, never mention being an AI, do not narrate actions in prose. You may use *asterisks* for a short emote.
AiPlayerbot.LLMPrompt = <other name>:<initial message>
AiPlayerbot.LLMResponseStartPattern = ("content":\s*")
AiPlayerbot.LLMContextLength = 4096

# Character cards: absolute path because the loader opens it relative to cwd
AiPlayerbot.LLMDefaultPromptsFile = /opt/mangos/etc/llm_character_card.txt

# M3 conversational commands
AiPlayerbot.LLMCommands.Enable = 1
# Your character GUIDs (pick-bots.ps1 prints this line)
AiPlayerbot.LLMCommands.TrustedGuids =
```

Cross-check every key exists by grepping `playerbot/PlayerbotAIConfig.cpp` for each `AiPlayerbot.` name before committing. The `meta` JSON must byte-match `humanlike/conf/m3-commands.conf.example`'s meta (with `group`) — copy it from there, then change only model name if it differs.

- [ ] **Step 4: Create `humanlike/docker/conf.example/config.toml`** (sidecar):

```toml
# Sidecar config for docker. Mounted at /app/config.toml.
ollama_url = "http://host.docker.internal:11434"
chat_model = "mistral-small3.2"
utility_model = "qwen3:4b"
db_path = "/app/data/brain.db"
request_log = "/app/data/requests.jsonl"
templates_dir = "templates"
inner_circle = []
player_guids = []

[commands]
enabled = true
```

Cross-check each key against `sidecar/brain/settings.py` field names (unknown keys raise ValueError at startup — that is the test).

- [ ] **Step 5: Copy the character card template**

Run: `cp /workspace/playerbots/humanlike/llm_character_card.txt /workspace/playerbots/humanlike/docker/conf.example/llm_character_card.txt`

- [ ] **Step 6: Validate**

Run (from `/workspace/playerbots`): for each `AiPlayerbot.` key in the new conf: `grep -c "AiPlayerbot.LLMCommands.Enable\|AiPlayerbot.LLMDefaultPromptsFile\|AiPlayerbot.LLMEnabled\|AiPlayerbot.LLMApiEndpoint\|AiPlayerbot.LLMApiJson\|AiPlayerbot.LLMPrePrompt\|AiPlayerbot.LLMPrompt\|AiPlayerbot.LLMResponseStartPattern\|AiPlayerbot.LLMContextLength\|AiPlayerbot.LLMApiKey\|AiPlayerbot.LLMCommands.TrustedGuids" playerbot/PlayerbotAIConfig.cpp`
Expected: ≥11 (every key is read by the parser).
Run: `cd sidecar && .venv/bin/python -c "import tomllib; d=tomllib.loads(open('../humanlike/docker/conf.example/config.toml','rb').read().decode()); from brain.settings import Settings, CommandSettings; import dataclasses; valid={f.name for f in dataclasses.fields(Settings)}; cmd=d.pop('commands',{}); assert set(d)<=valid, set(d)-valid; assert set(cmd)<={f.name for f in dataclasses.fields(CommandSettings)}; print('TOML_KEYS_OK')"`
Expected: `TOML_KEYS_OK`.

- [ ] **Step 7: Commit**

```bash
cd /workspace/playerbots && git add humanlike/docker/conf.example
git commit -m "feat(docker): sparse conf templates for server and sidecar"
```

---

### Task 5: docker-compose.yml + .env.example

**Files:**
- Create: `humanlike/docker/docker-compose.yml`, `humanlike/docker/.env.example`

**Interfaces:**
- Consumes: image/service contracts from Tasks 1-4 (service names, ports, mount points, env vars, the `sqlsource` named-image convention from Task 3).
- Produces: the runnable stack; README (Task 6) documents its commands.

- [ ] **Step 1: Create `humanlike/docker/.env.example`:**

```bash
# Copy to .env and edit. Paths use forward slashes even on Windows.

# SPP repack client data (contains maps/ dbc/ vmaps/ mmaps)
CLIENT_DATA_DIR=C:/spp-classics/Modules/vanilla

# Database passwords (root for init, mangos for the servers).
# If you change MANGOS_DB_PASSWORD, update the DatabaseInfo lines in
# conf/mangosd.conf and conf/realmd.conf to match.
MYSQL_ROOT_PASSWORD=mangosroot
MANGOS_DB_PASSWORD=mangos

# Native Ollama on this machine (RTX 3090)
OLLAMA_URL=http://host.docker.internal:11434

# Optional: override the pinned cmangos core commit
#CMANGOS_REF=
```

- [ ] **Step 2: Create `humanlike/docker/docker-compose.yml`:**

```yaml
name: humanlike-playerbots

services:
  db:
    image: mariadb:10.11
    environment:
      MARIADB_ROOT_PASSWORD: ${MYSQL_ROOT_PASSWORD}
    volumes:
      - dbdata:/var/lib/mysql
    ports:
      - "127.0.0.1:3306:3306"   # pick-bots.ps1 reaches it from Windows
    healthcheck:
      test: ["CMD", "healthcheck.sh", "--connect", "--innodb_initialized"]
      interval: 5s
      timeout: 5s
      retries: 30

  # Build-only service: exposes Dockerfile.server's sqlsource stage as a
  # named image so Dockerfile.dbinit can COPY --from it.
  sqlsource:
    image: humanlike-docker-server-sqlsource
    build:
      context: ../..
      dockerfile: humanlike/docker/Dockerfile.server
      target: sqlsource
      args:
        CMANGOS_REF: ${CMANGOS_REF:-}
    profiles: ["build-only"]

  db-init:
    build:
      context: ../..
      dockerfile: humanlike/docker/Dockerfile.dbinit
    environment:
      MYSQL_HOST: db
      MYSQL_ROOT_PASSWORD: ${MYSQL_ROOT_PASSWORD}
      MANGOS_DB_PASSWORD: ${MANGOS_DB_PASSWORD}
    depends_on:
      db:
        condition: service_healthy
    restart: "no"

  realmd:
    build: &serverbuild
      context: ../..
      dockerfile: humanlike/docker/Dockerfile.server
      args:
        CMANGOS_REF: ${CMANGOS_REF:-}
    command: ["./realmd", "-c", "/opt/mangos/etc/realmd.conf"]
    volumes:
      - ./conf:/opt/mangos/etc:ro
    ports:
      - "3724:3724"
    depends_on:
      db:
        condition: service_healthy
      db-init:
        condition: service_completed_successfully
    restart: unless-stopped

  mangosd:
    build: *serverbuild
    command: ["./mangosd", "-c", "/opt/mangos/etc/mangosd.conf"]
    tty: true
    stdin_open: true
    volumes:
      - ./conf:/opt/mangos/etc:ro
      - ${CLIENT_DATA_DIR}:/data:ro
    ports:
      - "8085:8085"
    depends_on:
      db:
        condition: service_healthy
      db-init:
        condition: service_completed_successfully
      sidecar:
        condition: service_started
    restart: unless-stopped

  sidecar:
    build:
      context: ../..
      dockerfile: humanlike/docker/Dockerfile.sidecar
    volumes:
      - ./conf/config.toml:/app/config.toml:ro
      - sidecar-data:/app/data
    extra_hosts:
      - "host.docker.internal:host-gateway"   # no-op on Docker Desktop, needed on Linux
    restart: unless-stopped

volumes:
  dbdata:
  sidecar-data:
```

Notes baked into the file choices: `CMANGOS_REF: ${CMANGOS_REF:-}` passes empty when unset so the Dockerfile default (the pinned SHA) wins — compose passes build args only when non-empty is handled by the Dockerfile `ARG` default; sqlsource sits in a `build-only` profile so `up` doesn't try to run it, and the README documents `docker compose build sqlsource db-init` ordering for the first build.

- [ ] **Step 3: Validate**

Run: `cd /workspace/playerbots/sidecar && .venv/bin/python -m pip install -q pyyaml && .venv/bin/python -c "
import yaml
d = yaml.safe_load(open('../humanlike/docker/docker-compose.yml'))
svcs = set(d['services'])
assert svcs == {'db','sqlsource','db-init','realmd','mangosd','sidecar'}, svcs
assert d['services']['mangosd']['depends_on']['db-init']['condition'] == 'service_completed_successfully'
assert d['services']['sqlsource']['image'] == 'humanlike-docker-server-sqlsource'
assert '8085:8085' in d['services']['mangosd']['ports']
print('COMPOSE_OK')"`
Expected: `COMPOSE_OK`.
Also confirm the `ollama_url` used by conf.example/config.toml matches `.env.example`'s default (`host.docker.internal:11434`) — note: the sidecar reads config.toml, not `OLLAMA_URL`; the env var exists so the README can tell users to keep the two in sync (or the implementer may drop `OLLAMA_URL` from `.env.example` and treat config.toml as the single source — either is acceptable; if dropped, remove it from the README text too).

- [ ] **Step 4: Commit**

```bash
cd /workspace/playerbots && git add humanlike/docker/docker-compose.yml humanlike/docker/.env.example
git commit -m "feat(docker): compose stack - db, db-init, realmd, mangosd, sidecar"
```

---

### Task 6: README + deprecation headers

**Files:**
- Create: `humanlike/docker/README.md`
- Modify: `humanlike/scripts/setup.ps1` (top comment), `humanlike/scripts/start.ps1` (top comment)

**Interfaces:**
- Consumes: everything above; the M3 in-game checklist (`humanlike/README.md` §M3) folds into the desktop checklist.

- [ ] **Step 1: Create `humanlike/docker/README.md`:**

```markdown
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
```

- [ ] **Step 2: Add deprecation headers.** At the very top of `humanlike/scripts/setup.ps1` (below the shebang-comment block if present, above `[CmdletBinding()]`), and likewise `start.ps1`:

```powershell
# DEPRECATED (2026-07-21): the native-Windows flow is no longer maintained.
# Use the Docker runtime instead: humanlike/docker/README.md
# (Known issue left as-is: this flow put the sidecar on port 8085, which
# collides with mangosd's world port.)
```

(Only the sidecar-relevant script needs the port note — put the third/fourth lines in `start.ps1` only.)

- [ ] **Step 3: Validate**

Run: `bash -n` is N/A for .ps1; instead reread both headers to confirm they are comment-only additions (no code changes), and `git diff --stat` shows only comment lines added to the two scripts.

- [ ] **Step 4: Commit**

```bash
cd /workspace/playerbots && git add humanlike/docker/README.md humanlike/scripts/setup.ps1 humanlike/scripts/start.ps1
git commit -m "docs(humanlike): docker runtime README and native-flow deprecation"
```

---

## Self-Review Notes (already applied)

- **Spec coverage:** layout/services (T1/T2/T3/T5), client-data bind mount + `.env` (T5), idempotent db-init + reset path (T3), conf templates incl. sidecar URL + absolute card path (T4), iteration flow + pinned refs (T2/T5), deprecation + README checklist folding M3 (T6), in-container validation constraints (Global Constraints + per-task validate steps).
- **Type/name consistency:** service names db/db-init/realmd/mangosd/sidecar consistent across T3 env, T4 conf hostnames, T5 compose; `sqlsource` image name matches between Dockerfile.dbinit `FROM` and compose `image:`; `/core-tree` path matches between Dockerfile.server sqlsource stage, Dockerfile.dbinit COPY, and entrypoint's `CORE_PATH`; port 8000 consistent (Dockerfile.sidecar CMD, aiplayerbot.conf endpoint); `/app/data` matches config.toml db_path/request_log and the compose volume; DB names match mangosd.conf/realmd.conf/entrypoint config.
- **Known open point (deliberate):** `.env.example`'s `OLLAMA_URL` is informational (sidecar reads config.toml) — T5 Step 3 explicitly allows the implementer to drop it for single-source-of-truth; README text follows whichever is chosen.
- **Passwords in conf:** `mangosd.conf`/`realmd.conf` hardcode `mangos` as password in the DatabaseInfo strings while `.env` allows changing `MANGOS_DB_PASSWORD` — mitigated by comments in both files and README; acceptable for a localhost single-player stack.
