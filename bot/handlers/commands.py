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
        f"hei, sunt {PERSONA_NAME} ✨\n"
        "în sfârșit ai venit. scrie-mi ca unui prieten.\n\n"
        "câteva lucruri pe care le pot face:\n"
        "/reset — șterg istoricul recent\n"
        "/memory — vezi ce îmi amintesc despre tine"
    )
    await message.answer(text)


@router.message(Command("reset"))
async def on_reset(message: Message, container: Container) -> None:
    await container.db.clear_messages(message.from_user.id)
    await message.answer("gata — o luăm de la capăt. ce faci?")


@router.message(Command("memory"))
async def on_memory(message: Message, container: Container) -> None:
    facts = await container.db.get_facts(message.from_user.id)
    if not facts:
        await message.answer("nu am nimic salvat despre tine încă. hai să vorbim 🙂")
        return
    lines = "\n".join(f"• {fact['content']}" for fact in facts)
    await message.answer(f"uite ce îmi amintesc:\n{lines}")
