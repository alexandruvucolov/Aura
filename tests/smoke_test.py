"""Offline smoke test — exercises core logic without a live bot or network.

Run with:  python tests/smoke_test.py
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Configure required settings before importing anything that reads them.
os.environ.setdefault("BOT_TOKEN", "123:TEST")
os.environ.setdefault("OPENROUTER_API_KEY", "sk-test")

from bot.db.database import Database  # noqa: E402
from bot.persona import build_checkin_prompt, build_system_prompt  # noqa: E402
from bot.services import llm  # noqa: E402
from bot.services.memory import MemoryService  # noqa: E402


def test_split_bubbles() -> None:
    bubbles = llm.split_bubbles("hey how are you ||| missed you |||")
    assert bubbles == ["hey how are you", "missed you"], bubbles
    # No delimiter → single bubble.
    assert llm.split_bubbles("just one line") == ["just one line"]


def test_persona() -> None:
    now = datetime(2026, 11, 15, 3, 0, tzinfo=timezone.utc)
    prompt = build_system_prompt(
        now=now,
        elapsed_since_last=3 * 24 * 3600,
        facts=["User has a dog named Max"],
    )
    assert "Aura" in prompt
    assert "Max" in prompt
    assert "|||" in prompt
    assert "3 day" in prompt  # humanized gap

    checkin = build_checkin_prompt(now=now, facts=["User has a dog named Max"])
    assert "Aura" in checkin
    assert "Max" in checkin


async def test_database_and_memory() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db = Database(os.path.join(tmp, "test.db"))
        await db.connect()

        await db.record_user_message(42, "hi", "2026-11-15T00:00:00+00:00")
        await db.add_message(42, "assistant", "hey!")
        rows = await db.get_recent_messages(42)
        assert len(rows) == 2, rows
        assert rows[0]["role"] == "user"

        await db.set_last_interaction(42, "2026-11-15T00:00:00+00:00")
        user = await db.get_user(42)
        assert user is not None
        assert user["messages_since_extraction"] == 1

        await db.add_fact(42, "User has a dog named Max")
        await db.add_fact(42, "User works as a backend engineer")

        memory = MemoryService(db)
        facts = await memory.retrieve_relevant_facts(42, "how is your dog Max doing")
        assert facts, "expected at least one relevant fact"
        assert "Max" in facts[0]

        later = datetime(2026, 11, 16, 0, 0, tzinfo=timezone.utc)
        elapsed = await memory.get_elapsed_since_last(42, later)
        assert elapsed == 24 * 3600, elapsed

        await db.close()


def main() -> None:
    test_split_bubbles()
    test_persona()
    asyncio.run(test_database_and_memory())
    print("All smoke tests passed ✔")


if __name__ == "__main__":
    main()
