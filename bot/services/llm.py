"""OpenRouter async client and response helpers."""

from __future__ import annotations

from openai import AsyncOpenAI

from bot.config import get_settings

_client: AsyncOpenAI | None = None


def get_client() -> AsyncOpenAI:
    """Return a lazily-created AsyncOpenAI client pointed at OpenRouter."""
    global _client
    if _client is None:
        settings = get_settings()
        _client = AsyncOpenAI(
            base_url=settings.openrouter_base_url,
            api_key=settings.openrouter_api_key,
        )
    return _client


async def chat(
    messages: list[dict],
    *,
    model: str | None = None,
    temperature: float = 0.9,
    max_tokens: int = 2000,
) -> str:
    """Send a chat completion and return the trimmed assistant text."""
    settings = get_settings()
    response = await get_client().chat.completions.create(
        model=model or settings.openrouter_model,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    content = response.choices[0].message.content
    return (content or "").strip()


def split_bubbles(text: str, delimiter: str = "|||") -> list[str]:
    """Split a reply on the bubble delimiter into clean, non-empty parts."""
    return [part.strip() for part in text.split(delimiter) if part.strip()]


async def extract_facts(conversation: list[dict], *, model: str | None = None) -> list[str]:
    """Extract durable facts about the user from a conversation transcript."""
    settings = get_settings()
    history = "\n".join(f"{message['role']}: {message['content']}" for message in conversation)
    messages = [
        {
            "role": "system",
            "content": (
                "Extract durable facts about the USER from this conversation. "
                "Output one fact per line, in third person (e.g. 'User has a dog named Max'). "
                "Only output facts about the user, nothing else. "
                "If there are no new facts, output exactly: NONE"
            ),
        },
        {"role": "user", "content": history},
    ]
    response = await get_client().chat.completions.create(
        model=model or settings.summary_model,
        messages=messages,
        temperature=0.2,
        max_tokens=300,
    )
    content = response.choices[0].message.content or ""
    lines = [line.strip("- ").strip() for line in content.splitlines() if line.strip()]
    return [line for line in lines if line and line.upper() != "NONE"]
