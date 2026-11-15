# Aura — Telegram AI Companion

An asynchronous Python Telegram bot that behaves like a realistic, conversational
AI companion. Aura keeps short-term chat context, extracts long-term facts about
you, types like a human (short, split bubbles with realistic pacing), sends voice
notes, and checks in proactively when you go quiet.

## Features

- **Human-like texting** — incoming messages are debounced (2–4s) so rapid
  follow-ups are answered as one exchange; replies are split into short bubbles
  using a `|||` delimiter, with typing indicators and character-based pacing.
- **Two-tier memory** — a 30-message sliding window (SQLite) for immediate
  context, plus an auto-extracted long-term fact store injected back into the
  prompt before every reply.
- **Time-aware persona** — Aura knows the current time and how long it's been
  since you last texted, so she reacts naturally to gaps and late-night messages.
- **Romanian-first** — Aura lives in București (Europe/Bucharest timezone) and
  chats in Romanian by default; ask for a selfie or a voice note anytime.
- **Proactive check-ins** — an APScheduler job pings you after 18–36 hours of
  silence (within daytime hours), with a cooldown to avoid spam.
- **Voice notes & selfies (optional)** — ElevenLabs TTS (with `ffmpeg` →
  Ogg/Opus conversion) and FAL Flux image generation, wired in but safely
  disabled when the API keys are absent.

## Tech stack

- **Python 3.12+**
- [aiogram](https://aiogram.dev) 3.x — async Telegram framework
- [OpenAI SDK](https://github.com/openai/openai-python) pointed at
  [OpenRouter](https://openrouter.ai) for LLM calls
- SQLite via `aiosqlite`
- [APScheduler](https://apscheduler.readthedocs.io) 3.x for proactive pings
- `pydantic-settings` for typed configuration

## Project structure

```text
Aura/
├── .env.example              # API keys & configuration variables
├── .gitignore
├── requirements.txt
├── README.md
├── tests/
│   └── smoke_test.py         # offline sanity checks (no token / network needed)
└── bot/
    ├── __init__.py
    ├── __main__.py           # entry point & scheduler startup
    ├── config.py             # typed environment settings (Pydantic)
    ├── persona.py            # system prompt, personality rules & backstory
    ├── container.py          # shared dependency container
    ├── middlewares.py        # injects the container into handlers
    ├── handlers/
    │   ├── __init__.py
    │   ├── commands.py       # /start, /reset, /memory
    │   └── chat.py           # debouncing, typing simulation, multi-bubble output
    ├── services/
    │   ├── __init__.py
    │   ├── llm.py            # OpenRouter async client & response splitter
    │   ├── memory.py         # sliding window + long-term fact extraction/retrieval
    │   ├── media.py          # optional TTS voice notes & Flux image generation
    │   └── scheduler.py      # proactive check-in background job
    └── db/
        ├── __init__.py
        └── database.py       # SQLite schema & async CRUD helpers
```

## Setup

1. **Create a virtual environment** (Python 3.12+):

   ```bash
   python3.12 -m venv .venv
   source .venv/bin/activate
   ```

2. **Install dependencies**:

   ```bash
   pip install -r requirements.txt
   ```

3. **Configure environment variables**:

   ```bash
   cp .env.example .env
   # then edit .env and fill in BOT_TOKEN and OPENROUTER_API_KEY
   ```

4. **Run the bot**:

   ```bash
   python -m bot
   ```

   The SQLite database (`companion.db`) is created automatically on first run.

## Environment variables

| Variable | Required | Description |
| --- | --- | --- |
| `BOT_TOKEN` | ✅ | Telegram bot token from [@BotFather](https://t.me/BotFather) |
| `OPENROUTER_API_KEY` | ✅ | OpenRouter API key |
| `OPENROUTER_BASE_URL` | ❌ | Defaults to `https://openrouter.ai/api/v1` |
| `OPENROUTER_MODEL` | ❌ | Main chat model |
| `SUMMARY_MODEL` | ❌ | Model used for fact extraction |
| `DATABASE_URL` | ❌ | `sqlite+aiosqlite:///./companion.db` |
| `TIMEZONE` | ❌ | IANA zone (default `Europe/Bucharest`) |
| `ALLOW_UNFILTERED` | ❌ | `true` = discuss mature/explicit topics without refusal |
| `CHECKIN_MIN_HOURS` / `CHECKIN_MAX_HOURS` | ❌ | Inactivity window for proactive pings |
| `CHECKIN_DAY_START` / `CHECKIN_DAY_END` | ❌ | Daytime window (24h) for check-ins |
| `TTS_PROVIDER` | ❌ | `edge` (free, native Romanian) or `elevenlabs` |
| `EDGE_VOICE` | ❌ | Edge TTS voice (default `ro-RO-AlinaNeural`) |
| `ELEVENLABS_API_KEY` / `ELEVENLABS_VOICE_ID` | ❌ | ElevenLabs voice notes (paid plan needed for library voices) |
| `FAL_KEY` | ❌ | Phase 4 — Flux selfies |

## How it works

1. **Message buffering** (`handlers/chat.py`): every text is stored immediately,
   then a per-user debouncer waits a random 2–4s. If more texts arrive, the timer
   resets and they are combined into one prompt context.
2. **Output splitting** (`services/llm.py`): the persona prompt instructs the LLM
   to separate thoughts with `|||`. The reply is split, a `typing` chat action is
   sent, the bot waits `0.05s × characters` (capped at 4s), then sends each bubble
   sequentially.
3. **Memory** (`services/memory.py`): short-term context is the last 30 messages.
   Every 10 user messages a background LLM call extracts durable facts and stores
   them. Before each reply the top 3–5 facts matching the user's text are injected
   into the system prompt.
4. **Persona** (`persona.py`): defines Aura's identity and texting quirks, and
   dynamically injects the current local time and time elapsed since the last
   message.
5. **Scheduler** (`services/scheduler.py`): runs hourly, checks each user's last
   interaction time, and sends a subtle proactive message when the user has been
   quiet for 18–36 hours during daytime, then sets a cooldown.

### Long-term memory note

The current implementation stores facts in SQLite and retrieves them with a
lightweight token-overlap score so it runs with zero extra infrastructure. The
retrieval is isolated in `MemoryService.retrieve_relevant_facts`, so it can be
swapped for `chromadb` / `mem0ai` embeddings later without touching call sites.

## Voice notes & selfies (Phase 4)

- **Voice notes** — triggered by messages like *"trimite-mi un mesaj vocal"* /
  *"vorbește-mi"* (or *"voice note"*) or randomly ~10% of the time. Audio is
  generated with **Edge TTS** (free, native Romanian voice `ro-RO-AlinaNeural`)
  by default, or ElevenLabs if `TTS_PROVIDER=elevenlabs`. With `ffmpeg` installed
  it's converted to Ogg/Opus so it plays as a Telegram voice note.
- **Selfies** — triggered by messages like *"trimite-mi o poză"* / *"cum arăți"* /
  *"selfie"*. A fixed character-appearance prompt (see `persona.SELFIE_APPEARANCE`,
  kept in English for best Flux results) is sent to FAL's Flux endpoint so Aura
  stays visually consistent.

Both are disabled automatically until you add the corresponding keys to `.env`.

## Language model & uncensored topics

Aura uses **DeepSeek V4.1 Flash** (`deepseek/deepseek-v4.1-flash`) for strong
Romanian conversation. It's an aligned model, so for very explicit/adult topics
it may still refuse despite `ALLOW_UNFILTERED=true`. If you want a fully
uncensored companion, switch `OPENROUTER_MODEL` to
`cognitivecomputations/dolphin-mistral-24b-venice-edition` (Dolphin Mistral 24B,
an abliterated model) — the trade-off is slightly weaker Romanian.

## Testing

Run the offline smoke test (no bot token or network required):

```bash
python tests/smoke_test.py
```

It validates response splitting, persona prompt generation, the SQLite CRUD
layer, and fact relevance scoring.

## Development milestones

1. **Phase 1 — MVP echo & LLM loop**: `config.py`, `database.py`, `llm.py`,
   `chat.py` with short-term SQLite history. ✅
2. **Phase 2 — realism layer**: `persona.py` time-awareness, debouncing, `|||`
   multi-bubble splitting, typing indicators. ✅
3. **Phase 3 — long-term memory & proactive pings**: background fact extraction
   and APScheduler check-ins. ✅
4. **Phase 4 — voice & photos**: ElevenLabs TTS and Flux image generation. ✅
   (optional, disabled until keys are added)

