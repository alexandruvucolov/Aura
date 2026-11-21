"""Userbot: runs Aura on a real Telegram account via Telethon (no "bot" badge)."""

from __future__ import annotations

import asyncio
import logging
import random
from datetime import datetime
from zoneinfo import ZoneInfo

from telethon import TelegramClient, events
from telethon.tl.functions.messages import SetTypingRequest

from bot.config import get_settings
from bot.db.database import Database
from bot.persona import build_system_prompt
from bot.services import llm
from bot.services.memory import MemoryService

logger = logging.getLogger(__name__)

DEBOUNCE_MIN = 2.0
DEBOUNCE_MAX = 4.0
TYPING_CHAR_SECONDS = 0.05
TYPING_MAX_SECONDS = 4.0
TYPING_MIN_SECONDS = 0.4


class Userbot:
    def __init__(self, settings, db, memory) -> None:
        self.settings = settings
        self.db = db
        self.memory = memory
        self.client = TelegramClient(
            settings.userbot_session,
            settings.userbot_api_id,
            settings.userbot_api_hash,
        )
        self._buffers: dict[int, list[str]] = {}
        self._tasks: dict[int, asyncio.Task] = {}

    async def start(self) -> None:
        await self.client.connect()
        if not await self.client.is_user_authorized():
            raise RuntimeError("Userbot is not authorized. Run the login flow first.")
        self.client.add_event_handler(self._on_message, events.NewMessage(incoming=True))
        me = await self.client.get_me()
        logger.info("Userbot running as %s %s (@%s)", me.first_name, me.last_name, me.username)
        print(f"Userbot running as {me.first_name} {me.last_name or ''} (@{me.username or 'no-username'})")
        await self.client.run_until_disconnected()

    async def _on_message(self, event) -> None:
        if not event.message.text or event.message.text.startswith("/"):
            return
        user_id = event.sender_id
        text = event.message.text
        now = datetime.now(ZoneInfo(self.settings.timezone))
        await self.db.record_user_message(user_id, text, now.isoformat())
        await self._enqueue(user_id, text)

    async def _enqueue(self, user_id: int, text: str) -> None:
        self._buffers.setdefault(user_id, []).append(text)
        existing = self._tasks.get(user_id)
        if existing and not existing.done():
            existing.cancel()
        delay = random.uniform(DEBOUNCE_MIN, DEBOUNCE_MAX)
        self._tasks[user_id] = asyncio.create_task(self._process(user_id, delay))

    async def _process(self, user_id: int, delay: float) -> None:
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
            logger.exception("Userbot failed to respond to %s", user_id)

    async def _respond(self, user_id: int, texts: list[str]) -> None:
        combined = "\n".join(texts)
        tz = ZoneInfo(self.settings.timezone)
        now = datetime.now(tz)
        elapsed = await self.memory.get_elapsed_since_last(user_id, now)
        facts = await self.memory.retrieve_relevant_facts(user_id, combined)
        system = build_system_prompt(now=now, elapsed_since_last=elapsed, facts=facts)
        history = await self.memory.get_context_messages(user_id)

        reply = await llm.chat([{"role": "system", "content": system}, *history])
        if not reply:
            return
        bubbles = llm.split_bubbles(reply) or [reply]

        for bubble in bubbles:
            await self._typing(user_id)
            pause = min(TYPING_MAX_SECONDS, max(TYPING_MIN_SECONDS, TYPING_CHAR_SECONDS * len(bubble)))
            await asyncio.sleep(pause)
            await self.client.send_message(user_id, bubble)
            await self.db.add_message(user_id, "assistant", bubble)

        await self.db.set_last_interaction(user_id, now.isoformat())
        await self.memory.maybe_extract_facts(user_id)

    async def _typing(self, peer, action: str = "typing") -> None:
        try:
            await self.client(SetTypingRequest(peer, action))
        except Exception:
            pass

    async def send_message(self, peer, text: str) -> None:
        await self.client.send_message(peer, text)


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    settings = get_settings()
    db = Database(settings.db_path)
    await db.connect()
    memory = MemoryService(db)
    userbot = Userbot(settings, db, memory)
    try:
        await userbot.start()
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
