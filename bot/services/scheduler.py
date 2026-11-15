"""Background job for proactive check-ins."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from bot.persona import build_checkin_prompt
from bot.services import llm

logger = logging.getLogger(__name__)


class CheckinScheduler:
    def __init__(self, container) -> None:
        self.container = container
        self._scheduler = AsyncIOScheduler()

    def start(self) -> None:
        self._scheduler.add_job(self._tick, "interval", hours=1, id="checkin_tick")
        self._scheduler.start()

    def shutdown(self) -> None:
        self._scheduler.shutdown(wait=False)

    async def _tick(self) -> None:
        settings = self.container.settings
        tz = ZoneInfo(settings.timezone)
        now = datetime.now(tz)
        if not (settings.checkin_day_start <= now.hour < settings.checkin_day_end):
            return
        try:
            user_ids = await self.container.db.get_all_user_ids()
        except Exception:
            logger.exception("Failed to fetch users for check-in")
            return
        for user_id in user_ids:
            await self._maybe_checkin(user_id, now)

    async def _maybe_checkin(self, user_id: int, now: datetime) -> None:
        settings = self.container.settings
        db = self.container.db
        try:
            user = await db.get_user(user_id)
            if not user or not user["last_interaction"]:
                return

            last = datetime.fromisoformat(user["last_interaction"])
            if last.tzinfo is None:
                last = last.replace(tzinfo=timezone.utc)
            elapsed_hours = (now - last).total_seconds() / 3600
            if not (settings.checkin_min_hours <= elapsed_hours <= settings.checkin_max_hours):
                return

            if user["checkin_cooldown_until"]:
                cooldown = datetime.fromisoformat(user["checkin_cooldown_until"])
                if cooldown.tzinfo is None:
                    cooldown = cooldown.replace(tzinfo=timezone.utc)
                if cooldown > now:
                    return

            facts = await self.container.memory.retrieve_relevant_facts(
                user_id, "what is the user up to lately", top_k=3
            )
            system = build_checkin_prompt(now=now, facts=facts)
            messages = [
                {"role": "system", "content": system},
                {
                    "role": "user",
                    "content": "(Your friend hasn't texted in a while. Send a natural, casual check-in.)",
                },
            ]
            text = await llm.chat(messages, temperature=0.95, max_tokens=200)
            if not text:
                return
            bubble = (llm.split_bubbles(text) or [text])[0]

            await self.container.bot.send_message(user_id, bubble)
            await db.add_message(user_id, "assistant", bubble)
            await db.set_checkin_cooldown_until(
                user_id, (now + timedelta(hours=settings.checkin_max_hours)).isoformat()
            )
            logger.info("Sent proactive check-in to user %s", user_id)
        except Exception:
            logger.exception("Check-in failed for user %s", user_id)
