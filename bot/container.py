"""A small dependency container shared across handlers and services."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover
    from aiogram import Bot

    from bot.config import Settings
    from bot.db.database import Database
    from bot.services.memory import MemoryService


@dataclass
class Container:
    settings: "Settings"
    db: "Database"
    bot: "Bot"
    memory: "MemoryService"
    debouncer: Any = None
