"""Two-tier memory: short-term sliding window + long-term fact store.

Long-term memory uses SQLite + lightweight token-overlap scoring so the bot
works out of the box with no extra infrastructure. The retrieval function is
isolated in :meth:`MemoryService.retrieve_relevant_facts` so it can later be
swapped for `chromadb` / `mem0ai` embeddings without touching call sites.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from bot.services import llm

logger = logging.getLogger(__name__)

FACT_EXTRACTION_EVERY = 10
SHORT_TERM_WINDOW = 30
EXTRACTION_CONTEXT = 20


def _score_fact(fact: str, query: str) -> float:
    """Score a fact by the share of query tokens it covers (Jaccard-ish)."""
    fact_tokens = {token for token in fact.lower().split() if token.isalnum()}
    query_tokens = {token for token in query.lower().split() if token.isalnum()}
    if not query_tokens:
        return 0.0
    return len(fact_tokens & query_tokens) / len(query_tokens)


class MemoryService:
    def __init__(self, db) -> None:
        self.db = db
        self._extraction_lock = asyncio.Lock()

    async def get_context_messages(
        self, user_id: int, limit: int = SHORT_TERM_WINDOW
    ) -> list[dict]:
        rows = await self.db.get_recent_messages(user_id, limit)
        return [{"role": row["role"], "content": row["content"]} for row in rows]

    async def get_elapsed_since_last(self, user_id: int, now: datetime) -> float | None:
        """Seconds since the user's previous interaction (None on first contact)."""
        user = await self.db.get_user(user_id)
        if not user or not user["last_interaction"]:
            return None
        last = datetime.fromisoformat(user["last_interaction"])
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        return (now - last).total_seconds()

    async def retrieve_relevant_facts(
        self, user_id: int, query: str, top_k: int = 5
    ) -> list[str]:
        facts = await self.db.get_facts(user_id)
        if not facts:
            return []
        scored = [
            (fact["content"], _score_fact(fact["content"], query)) for fact in facts
        ]
        scored = [item for item in scored if item[1] > 0]
        scored.sort(key=lambda item: item[1], reverse=True)
        return [content for content, _ in scored[:top_k]]

    async def maybe_extract_facts(self, user_id: int) -> None:
        """Kick off background fact extraction once enough messages accumulate."""
        user = await self.db.get_user(user_id)
        if not user or user["messages_since_extraction"] < FACT_EXTRACTION_EVERY:
            return
        async with self._extraction_lock:
            user = await self.db.get_user(user_id)
            if not user or user["messages_since_extraction"] < FACT_EXTRACTION_EVERY:
                return
            await self.db.reset_extraction_counter(user_id)
        # Fire-and-forget the network call so it never blocks the reply path.
        asyncio.create_task(self._extract_and_store(user_id))

    async def _extract_and_store(self, user_id: int) -> None:
        try:
            history = await self.get_context_messages(user_id, limit=EXTRACTION_CONTEXT)
            if len(history) < 2:
                return
            facts = await llm.extract_facts(history)
            existing = {fact["content"].strip().lower() for fact in await self.db.get_facts(user_id)}
            added = 0
            for fact in facts:
                if fact.strip().lower() not in existing:
                    await self.db.add_fact(user_id, fact)
                    existing.add(fact.strip().lower())
                    added += 1
            if added:
                logger.info("Stored %d new fact(s) for user %s", added, user_id)
        except Exception:  # best-effort background task
            logger.exception("Fact extraction failed for user %s", user_id)
