# Human-like / LLM-driven Playerbots — Design

**Date:** 2026-07-19
**Status:** Approved by Andreas
**Target:** `andreas-skag/playerbots` fork (cmangos vanilla/classic), Windows PC (RTX 3090 24GB), local Ollama. Private fork — free to diverge from upstream.

## Goal

Bots on a singleplayer vanilla server that feel human:

1. **Believable chat** — distinct personalities in say/party/guild, banter with the player and each other
2. **Memory & relationships** — bots remember past interactions and build sentiment toward the player across sessions
3. **LLM-driven behavior** — natural-language commands, bot-initiated activity, and slow-cadence combat shot-calling

Explicitly out of scope: gear-inspection reactions, per-action LLM combat control (latency-infeasible), upstream-friendliness constraints.

**Depth tiers:** full treatment (memory, relationships, initiative, tactics) for the "inner circle" — ~5–40 bots. Membership: any bot currently in the player's group or guild (checked per request), plus a static GUID list in the sidecar config. Once a bot has memory it keeps it, even after leaving the group. Nearby world bots get cheap stateless persona-only banter. Everything keys on character GUID so memory survives restarts.

## Architecture

```
mangos-classic + playerbots fork (C++)
  · existing: ChatReplyAction → std::async → PlayerbotLLMInterface::Generate() → HTTP POST
  · new hooks: richer request context, directive executor, initiative tick, tactic tick
        │ HTTP, OpenAI-compatible JSON (AiPlayerbot.LLMApiEndpoint)
        ▼
Brain sidecar (Python, FastAPI)        ← all AI-logic iteration happens here
  · persona store · relationship memory (SQLite) · prompt assembly
  · reply post-processing → say-text + optional {command|strategy|tactic} directive
        ▼
Ollama on the 3090 — ~14B chat model + small (~3–4B) model for ambient banter & summarization
```

Key idea: the server already POSTs configurable JSON to a configurable endpoint and regex-parses the reply (`AiPlayerbot.LLM*` config). The sidecar is a drop-in endpoint that enriches prompts with persona + memory before calling Ollama. Existing async plumbing (`SayAction.cpp` worker threads, delayed packet delivery) is reused untouched.

## Milestones (each independently playable)

- **M1 — Great chat, zero code:** Ollama direct; model selection; tuned `LLMPrePrompt`/templates; per-bot character cards (`llm_character_card.txt`); bot-to-bot chat (`LLMBotToBotChatChance`) and RPG/NPC chat enabled
- **M2 — Sidecar + memory:** insert sidecar between server and Ollama; move prompt assembly into it; personas + relationship/sentiment persistence — bots remember you across sessions
- **M3 — Conversational commands:** "can you tank?" → directive → existing command system
- **M4 — Bot initiative:** periodic "thought" tick → bots start conversations, suggest activities, whisper the player
- **M5 — Tactical advisor:** slow-cadence combat policy calls in group content

## Components

### C++ hooks (fork changes — small, stable surface)

1. **Richer request context** — extend placeholder substitution in `ChatReplyAction::GenerateReplyMessage` (`playerbot/strategy/actions/SayAction.cpp`) with a compact `meta` block: bot GUID, speaker GUID, group composition, bot health/mana, in-combat flag, event type (`chat` | `invite` | `thought` | `tactic`).
2. **Directive executor** — new `LLMDirectiveHandler`: extracts an optional fenced JSON directive from replies and routes via whitelist:
   - `{"command": "tank"}` → `PlayerbotAI::HandleCommand` (`playerbot/PlayerbotAI.h:373`) — reuses the entire existing chat-command vocabulary
   - `{"strategy": {"+": "tank", "-": "dps"}}` → `PlayerbotAI::ChangeStrategy` (`playerbot/PlayerbotAI.h:383`)
   - Unknown/invalid directives: ignored, logged. Whitelist contains only things a party member could ask of a bot — never GM or economy-affecting commands.
3. **Initiative tick** — new non-combat action, long random timer, inner-circle only: POSTs a `thought` event; a non-empty reply becomes say/whisper/action. Modeled on the existing `LLMBotToBotChatChance` pattern.
4. **Tactic tick** — new combat action, group content only, ~8s cadence + on-pull: POSTs a compact combat snapshot; reply maps to strategy toggles + focus-target. Fire-and-forget; last directive cached; short timeout (~3s); combat never blocks on the LLM.

### Sidecar (Python + FastAPI + SQLite; lives in `sidecar/` in this fork)

- **Endpoint** matching the server's configured JSON template (OpenAI-compatible chat-completions shape)
- **Persona service:** per-bot card generated once, seeded deterministically by GUID/class/race/name (traits, speech style, quirks, combat temperament); persisted, regenerable
- **Memory service:** SQLite — `interactions` (who/what/when), `sentiment` (bot→player score updated per interaction), `summaries` (periodic LLM-compressed history to keep prompts small)
- **Prompt assembler:** persona + relationship summary + sentiment + situation → templates per event type; templates are plain files, hot-reloadable
- **Model router:** chat/thought/tactic → 14B model; ambient banter + summarization → small model
- **Tier logic:** inner-circle GUIDs get memory & full features; strangers get stateless banter
- **Rate caps:** per-bot and global, on top of the server's `LLMMaxSimultaniousGenerations`

## Data flow (example: "can you tank this dungeon?", M3)

1. Player says it in party → `ChatReplyAction` builds JSON incl. `meta` → async POST to sidecar
2. Sidecar loads persona + relationship, assembles prompt, calls Ollama
3. Reply: in-character say-text + `{"command": "tank"}`; sidecar logs interaction, updates sentiment
4. Server regex-parses say-text (existing patterns); `LLMDirectiveHandler` validates and executes the directive

Tactic flow identical but initiated by the combat tick; replies are usually directive-only (rare battle-cry text).

## Error handling — server never cares if the brain is sick

- **Sidecar/Ollama down:** existing HTTP-failure tolerance → bot doesn't reply; no directive → no action; bots degrade to normal playerbots
- **Slow generation:** existing `LLMGenerationTimeout` + concurrency caps; tactic tick keeps last policy on miss
- **Malformed/hallucinated directives:** C++ whitelist + argument validation; rejects logged for prompt tuning
- **Memory DB loss:** memories gone, personas regenerate from seed, everything else works
- **Runaway spend:** sidecar rate caps

## Testing

- **Sidecar:** pytest — memory ops, sentiment math, prompt assembly (golden files), directive validity; plus a replay CLI to iterate prompts against recorded server requests without running WoW
- **C++:** Linux validation build (`/workspace/mangos-classic`, build2) against a mock sidecar with canned responses — directive extraction, whitelist rejection, tick cadence, graceful degradation (kill sidecar mid-session)
- **End-to-end:** Windows machine with real client; scripted checklist per milestone (e.g. M2: full restart, bot references yesterday's run)
