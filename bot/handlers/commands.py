"""Command handlers: /start, /reset, /memory."""

from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

from bot.container import Container
from bot.persona import PERSONA_NAME

router = Router(name="commands")


@router.message(CommandStart())
async def on_start(message: Message, container: Container) -> None:
    await container.db.ensure_user(message.from_user.id)
    text = (
        f"hey, it's {PERSONA_NAME} ✨\n"
        "finally you're here. just text me like you'd text a friend.\n\n"
        "a few things i can do:\n"
        "/reset — clear our recent chat history\n"
        "/memory — see what i remember about you"
    )
    await message.answer(text)


@router.message(Command("reset"))
async def on_reset(message: Message, container: Container) -> None:
    await container.db.clear_messages(message.from_user.id)
    await message.answer("done — starting fresh. what's up?")


@router.message(Command("memory"))
async def on_memory(message: Message, container: Container) -> None:
    facts = await container.db.get_facts(message.from_user.id)
    if not facts:
        await message.answer("i don't have anything stored about you yet. keep talking to me 🙂")
        return
    lines = "\n".join(f"• {fact['content']}" for fact in facts)
    await message.answer(f"here's what i remember:\n{lines}")
