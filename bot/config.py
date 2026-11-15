"""Typed environment settings loaded from the environment / `.env` file."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # Required
    bot_token: str
    openrouter_api_key: str

    # OpenRouter
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_model: str = "mistralai/mistral-small-24b-instruct-2501"
    summary_model: str = "openai/gpt-4o-mini"

    # Database
    database_url: str = "sqlite+aiosqlite:///./companion.db"

    # Persona / behaviour
    timezone: str = "Europe/Bucharest"
    allow_unfiltered: bool = False
    checkin_min_hours: int = 18
    checkin_max_hours: int = 36
    checkin_day_start: int = 9
    checkin_day_end: int = 22

    # Optional Phase 4 keys
    elevenlabs_api_key: str | None = None
    elevenlabs_voice_id: str | None = None
    fal_key: str | None = None

    # TTS / voice
    tts_provider: str = "edge"  # "edge" (free, native Romanian) or "elevenlabs"
    edge_voice: str = "ro-RO-AlinaNeural"

    # FAL image generation (selfies)
    fal_model: str = "fal-ai/fast-sdxl"
    fal_lora_url: str | None = None
    fal_lora_scale: float = 1.0
    nsfw_trigger: str = "goala"  # comma-separated trigger words for NSFW selfies
    selfie_nsfw_prompt: str = ""  # NSFW prompt suffix (filled by you)

    @property
    def db_path(self) -> str:
        """Extract the plain SQLite file path from the SQLAlchemy-style URL."""
        prefix = "sqlite+aiosqlite:///"
        if self.database_url.startswith(prefix):
            return self.database_url[len(prefix):]
        return self.database_url


@lru_cache
def get_settings() -> Settings:
    return Settings()
