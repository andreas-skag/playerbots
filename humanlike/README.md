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

(M2 section is appended by Task 12.)
