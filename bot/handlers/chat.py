"""Main message handler with debouncing, typing simulation and multi-bubble output."""

from __future__ import annotations

import asyncio
import logging
import random
from datetime import datetime
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.types import BufferedInputFile, Message

from bot.container import Container
from bot.persona import build_selfie_prompt, build_system_prompt
from bot.services import llm, media

logger = logging.getLogger(__name__)

router = Router(name="chat")

DEBOUNCE_MIN = 2.0
DEBOUNCE_MAX = 4.0
TYPING_CHAR_SECONDS = 0.05
TYPING_MAX_SECONDS = 4.0
TYPING_MIN_SECONDS = 0.4


class Debouncer:
    """Buffer rapid-fire messages per user and respond once they pause."""

    def __init__(self, container: Container) -> None:
        self.container = container
        self._buffers: dict[int, list[str]] = {}
        self._tasks: dict[int, asyncio.Task] = {}

    async def enqueue(self, user_id: int, text: str) -> None:
        self._buffers.setdefault(user_id, []).append(text)
        existing = self._tasks.get(user_id)
        if existing and not existing.done():
            existing.cancel()
        delay = random.uniform(DEBOUNCE_MIN, DEBOUNCE_MAX)
        self._tasks[user_id] = asyncio.create_task(self._process_after(user_id, delay))

    async def _process_after(self, user_id: int, delay: float) -> None:
        try:
            await asyncio.sleep(delay)
        except asyncio.CancelledError:
            return
        texts = self._buffers.pop(user_id, [])
        if not texts:
            return
        try:
            await self._respond(user_id, texts)
        except Exception:
            logger.exception("Failed to respond to user %s", user_id)

    async def _respond(self, user_id: int, texts: list[str]) -> None:
        container = self.container
        db = container.db
        bot = container.bot
        combined = "\n".join(texts)

        tz = ZoneInfo(container.settings.timezone)
        now = datetime.now(tz)
        elapsed = await container.memory.get_elapsed_since_last(user_id, now)
        facts = await container.memory.retrieve_relevant_facts(user_id, combined)
        system = build_system_prompt(now=now, elapsed_since_last=elapsed, facts=facts)
        history = await container.memory.get_context_messages(user_id)

        reply = await llm.chat([{"role": "system", "content": system}, *history])
        if not reply:
            return
        bubbles = llm.split_bubbles(reply) or [reply]

        # 1) Always send the text reply first so the user gets an answer immediately.
        for bubble in bubbles:
            await bot.send_chat_action(user_id, action="typing")
            pause = min(TYPING_MAX_SECONDS, max(TYPING_MIN_SECONDS, TYPING_CHAR_SECONDS * len(bubble)))
            await asyncio.sleep(pause)
            await bot.send_message(user_id, bubble)
            await db.add_message(user_id, "assistant", bubble)

        # 2) Then send optional media (selfie / voice) as follow-ups.
        if _should_selfie(combined):
            image = await media.generate_selfie(build_selfie_prompt(combined))
            if image is not None:
                await bot.send_chat_action(user_id, action="upload_photo")
                await bot.send_photo(
                    user_id, BufferedInputFile(image, filename="selfie.jpg"),
                    caption=bubbles[0] if bubbles else None,
                )
                await db.add_message(user_id, "assistant", f"[selfie] {bubbles[0] if bubbles else ''}")

        if _should_voice(combined):
            audio = await media.synthesize_voice(bubbles[0])
            if audio is not None:
                data, extension = audio
                await bot.send_chat_action(user_id, action="record_voice")
                if extension == "ogg":
                    await bot.send_voice(user_id, BufferedInputFile(data, filename="voice.ogg"))
                else:
                    await bot.send_audio(user_id, BufferedInputFile(data, filename="voice.mp3"))
                await db.add_message(user_id, "assistant", f"[voice note] {bubbles[0]}")

        await db.set_last_interaction(user_id, now.isoformat())
        await container.memory.maybe_extract_facts(user_id)


VOICE_KEYWORDS = (
    "voice note", "voice message", "mesaj vocal", "trimite-mi un mesaj vocal",
    "trimite un mesaj vocal", "vorbeste-mi", "vorbește-mi", "cu vocea",
)

SELFIE_KEYWORDS = (
    "selfie", "poza", "poză", "o poza cu tine", "o poză cu tine", "cum arati",
    "cum arăți", "arată-mi", "aratami", "trimite o poza", "trimite o poză",
    "trimite-mi o poza", "trimite-mi o poză", "fă-ți un selfie", "fa-ti un selfie",
    "cum te vezi", "cum arati tu",
)


def _should_voice(combined: str) -> bool:
    lowered = combined.lower()
    return any(keyword in lowered for keyword in VOICE_KEYWORDS)


def _should_selfie(combined: str) -> bool:
    lowered = combined.lower()
    return any(keyword in lowered for keyword in SELFIE_KEYWORDS)


@router.message(F.text, ~F.text.startswith("/"))
async def on_message(message: Message, container: Container) -> None:
    user_id = message.from_user.id
    text = message.text or ""
    now = datetime.now(ZoneInfo(container.settings.timezone))
    await container.db.record_user_message(user_id, text, now.isoformat())
    if container.debouncer is None:
        container.debouncer = Debouncer(container)
    await container.debouncer.enqueue(user_id, text)
