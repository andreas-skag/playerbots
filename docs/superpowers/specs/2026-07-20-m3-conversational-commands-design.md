# M3 — Conversational Commands: Design

Date: 2026-07-20
Status: approved (brainstormed with Andreas; approach and all sections approved in conversation)
Parent spec: `2026-07-19-humanlike-llm-bots-design.md` (M3 of 5)
Branch: `feature/humanlike-llm-bots`

## Goal

Talking to a bot like a human party member gets human results: "can you tank this
dungeon?", "lead the way", "kill the skull target", "come help me" — the bot answers
in character *and does the thing*, via the existing playerbot command/strategy system.
Bots can also command each other when their own chat naturally produces a request.

## Decisions made during brainstorming

- **Command scope:** curated mid-size verb set (~14 verbs), grown incrementally. Not
  full `HandleCommand` passthrough, not minimal role-only.
- **Authorization:** bots obey group members plus inner-circle GUIDs (whispers work
  outside a group for inner circle). Strangers get chat replies; their directives are
  dropped.
- **Compliance:** sentiment-gated refusal. High/neutral sentiment → comply in
  character; sentiment below `sentiment_threshold` → refuse in character, no
  directive. The refusal *decision* is deterministic Python (never the LLM);
  persona only colors the phrasing. `always_obey` config kill-switch forces
  compliance.
- **Addressing:** named bot or whisper → that bot. Unaddressed group request
  ("someone tank") → sidecar picks the single best-fit bot from group composition;
  others may react in chat but emit no directive.
- **Bot-to-bot:** bots may command each other within the same group (config-gated).
- **C++ workflow:** authored in the container, **write-only**; Andreas compiles on
  the Windows desktop (possibly via docker for portability). Keep the C++ diff small
  and self-contained for a clean first compile.

## Architecture (approved Approach 1: structured directive field + two-step brain)

All language understanding lives in the sidecar; C++ is a validating executor that
never trusts the sidecar. The 14B chat model never formats JSON — directives are
composed deterministically in Python from a constrained classification step.

### Data flow — "can you tank this dungeon?" in party chat

1. **C++ → sidecar.** Each listening bot's `ChatReplyAction` fires as today
   (`playerbot/strategy/actions/SayAction.cpp`). The M2 `meta` block gains one
   field: `group` — a compact roster string (`name:guid:class:level` per member,
   `;`-separated) built from new placeholders.
2. **Sidecar understands.** A keyword pre-filter decides whether the message is even
   command-shaped; pure banter takes the M2 chat path with zero added latency.
   Command-shaped messages go to the **small model** with constrained JSON output:
   verb (from a fixed enum, or `none`), optional args, and which bot (if any) was
   addressed. Then plain-Python gates run: authorization (speaker in group / inner
   circle), sentiment threshold, and best-fit routing for unaddressed requests.
3. **Sidecar → C++.** The response body gains a top-level `directive` field,
   e.g. `{"verb": "attack", "args": {"mark": "skull"}}`, alongside normal chat
   content. The chat model receives "you just agreed to X" / "you are refusing X"
   context so the spoken acknowledgment matches the action. Per-utterance dedup
   (speaker guid + message hash + ~3 s bucket, lock per key) guarantees exactly one
   bot acts on a group-wide request.
4. **C++ executes safely.** The LLM response is handled on a worker thread
   (`std::async` → `GenerateResponsePackets`, SayAction.cpp:654), so the async
   thread only *parses* the directive and enqueues it. Execution happens on the
   world thread, where `LLMDirectiveHandler` re-validates everything using C++'s
   own knowledge — the speaker C++ already knows (never the sidecar's claim),
   group/trusted membership *at execution time*, hard verb+args whitelist — then
   maps verb → `PlayerbotAI::HandleCommand` / `ChangeStrategy`.

Two authorization layers by design: the sidecar's gate is *social* (refusal,
sentiment, routing); the C++ gate is *security* (a hallucinating or compromised
sidecar can only make a bot do whitelisted party-member things, or nothing).

## Verb whitelist

Sidecar emits abstract verbs; C++ owns the mapping to real commands/strategies, so
the LLM never composes raw command strings. Grounded against
`playerbot/strategy/actions/ChatActionContext.h`.

| Verb | Args | C++ mapping |
|---|---|---|
| `role_tank` / `role_heal` / `role_dps` | — | combat-strategy toggles via `ChangeStrategy` (e.g. `+tank,-dps`); no-ops harmlessly for classes lacking the strategy |
| `follow` | — | `follow chat shortcut`; **extended:** if bot is currently group leader, first hand leadership back to the requester ("follow me" ends leading) |
| `stay` | — | `stay chat shortcut` |
| `guard` | — | `guard chat shortcut` |
| `flee` | — | `flee chat shortcut` |
| `attack` | `mark?` | no mark: `attack my target` (requester's target). With mark: set RTI (`rti <mark>`) + `attack rti target`. "Tank the skull" = `attack`+`skull` routed to the tank by best-fit — no separate verb |
| `lead` | — | promote bot to group leader (`Group::ChangeLeader`, as `PlayerbotMgr.cpp:441` already does) + switch follow → autonomous movement; `dungeon` strategy (`StrategyContext.h:168`) covers instance behavior. Exact strategy-toggle strings pinned during implementation |
| `loot` | — | `add all loot` |
| `release` | — | `release` |
| `come` | — | `summon` |
| `give_leader` | — | `give leader` |
| `reset` | — | `reset ai soft` ("you're acting weird, snap out of it") |

Directive schema: `{"verb": <string>, "args": {<string>: <string>}?}`. The C++
whitelist validates arg values too — `mark` must be one of the eight raid-icon names
(`star circle diamond triangle moon square cross skull`, per `RtiTargetValue.h:20`).

## Bot-to-bot commands

The pipeline is speaker-agnostic, so this mostly falls out for free: bot-to-bot chat
already exists (`LLMBotToBotChatChance`), and a bot speaker in the same group passes
the group-membership gate. Guards:

- Bot-issued directives are honored **only within the same group** — bots do not
  command each other via inner-circle whispers. Config flag `allow_bot_commanders`
  (default on).
- **Cascade protection:** acknowledgments are statements, not requests, so they
  don't classify as commands; additionally the dedup registry tags bot-authored ack
  utterances so a command chain cannot bounce back — depth limit 1 per originating
  utterance.

Scope note: in M3 bots speak only reactively, so bot-to-bot commands occur when
banter naturally produces a request (healer tells the warrior "you should tank
this"). Proactive calling ("everyone burn the skull!") is M4 (initiative tick) /
M5 (tactical advisor); both reuse this directive path unchanged.

## Components

### C++ (authored here, compiled on the desktop — keep the diff small)

1. **`SayAction.cpp`:** add `<group>` roster placeholder to the meta block (same
   pattern as M2's `<bot guid>` change).
2. **New `playerbot/LLMDirectiveHandler.{h,cpp}`:**
   - *Parser* (async-thread-safe, no bot pointers): brace-scans the raw response
     body for the `directive` object — the codebase has no JSON library, and
     pattern-extraction matches how `PlayerbotLLMInterface::ParseResponse` works.
   - *Pending queue*: global, mutex-guarded, keyed by bot GUID; entries
     `{verb, args, requester guid, timestamp}`. The async thread enqueues; entries
     expire after ~10 s.
   - *Drain + execute*: called from `PlayerbotAI::UpdateAIInternal` on the world
     thread. Re-validates requester online + (in bot's group ∨ trusted GUID),
     verb+args whitelist, freshness — then executes via
     `HandleCommand` (`PlayerbotAI.h:373`) / `ChangeStrategy` (`PlayerbotAI.h:383`)
     / `Group::ChangeLeader` for `lead`.
3. **Config (`AiPlayerbot.*`):** `LLMCommands.Enable` (0/1),
   `LLMCommands.TrustedGuids` (comma-separated inner-circle GUIDs;
   `humanlike/scripts/pick-bots.ps1` writes it in sync with the sidecar's
   `inner_circle`).

### Sidecar (Python — fully testable in the container)

- **`brain/intent.py`** — keyword pre-filter; small-model classification with
  constrained JSON output (verb enum + args + addressed bot, or `none`).
- **`brain/commands.py`** — authorization gate, sentiment threshold, best-fit
  routing (uses class info from the `group` roster — never asks the mage to tank),
  per-utterance dedup registry with bot-ack tagging.
- **`brain/server.py` + templates** — attach the `directive` response field; inject
  agreed/refused context into the chat prompt.
- **`config.toml` `[commands]`:** `enabled`, `always_obey`, `sentiment_threshold`,
  `dedup_window_s`, `allow_bot_commanders`.
- **`brain/request_parser.py`** — parse the `group` meta field.

## Error handling

| Failure | Behavior |
|---|---|
| Sidecar/Ollama down | existing M2 degradation — bot doesn't reply, nothing executes |
| Malformed/unknown verb or args | ignored + logged (C++ side) |
| Requester logged off / left group during the async gap | dropped at world-thread re-validation |
| Stale queue entry (bot lagging/loading) | expires after ~10 s |
| Refusal | text only, no directive — nothing to mis-execute |
| Misclassification | tune via replay CLI; `debug llm` strategy whispers include the parsed directive |
| Command spam / cascades | dedup window, per-bot rate caps (M2), ack tagging, depth limit 1 |
| Kill-switches | `AiPlayerbot.LLMCommands.Enable` (C++), `[commands].enabled` and `always_obey` (sidecar) |

## Testing

- **pytest:** intent classification golden tests (mocked model); gate matrix
  (authorized × sentiment × addressed/unaddressed × human/bot speaker); dedup
  concurrency (N simultaneous per-bot requests → exactly one directive); directive
  schema + arg validation; request parsing with `group` field.
- **Replay CLI:** extended to print the directive a recorded message would produce;
  new fixtures with group meta.
- **C++:** write-only here. In-game verification checklist added to `humanlike/`
  docs: party tank request → role switch; "lead the way" → bot takes lead and
  walks; "kill the skull" → correct target; stranger whisper → reply but no action;
  low-sentiment refusal; "someone tank" → exactly one actor; sidecar killed
  mid-session → graceful degradation.

## Explicitly out of scope for M3

- Proactive bot speech/commands (M4 initiative tick, M5 tactical advisor).
- Combat-cadence tactical directives (M5).
- Economy/trade/GM verbs — never whitelisted.
- Upstreaming discipline — private-fork divergence is accepted.
