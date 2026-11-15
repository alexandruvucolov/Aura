"""Optional media: TTS voice notes (Edge TTS / ElevenLabs) and FAL Flux selfies.

Everything degrades gracefully: when a provider is unavailable the functions
return ``None`` and the chat handler falls back to text.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile

import httpx

from bot.config import get_settings

logger = logging.getLogger(__name__)

ELEVENLABS_TTS_URL = "https://api.elevenlabs.io/v1/text-to-speech"


async def synthesize_voice(text: str) -> tuple[bytes, str] | None:
    """Return ``(audio_bytes, extension)`` or ``None`` if unavailable.

    Uses Edge TTS (free, native Romanian) or ElevenLabs depending on
    ``TTS_PROVIDER``. Converts MP3 → Ogg/Opus via ``ffmpeg`` when available so
    the result plays as a real Telegram voice note; otherwise returns ``mp3``.
    """
    settings = get_settings()
    if settings.tts_provider == "elevenlabs":
        mp3 = await _elevenlabs_tts(text, settings)
    else:
        mp3 = await _edge_tts(text, settings.edge_voice)
    if not mp3:
        return None

    if shutil.which("ffmpeg"):
        try:
            ogg = _mp3_to_ogg(mp3)
            if ogg:
                return ogg, "ogg"
        except Exception:
            logger.exception("ffmpeg MP3 → Ogg conversion failed")
    return mp3, "mp3"


async def _elevenlabs_tts(text: str, settings) -> bytes | None:
    if not settings.elevenlabs_api_key or not settings.elevenlabs_voice_id:
        return None
    url = f"{ELEVENLABS_TTS_URL}/{settings.elevenlabs_voice_id}"
    headers = {"xi-api-key": settings.elevenlabs_api_key}
    payload = {"text": text, "model_id": "eleven_multilingual_v2"}
    params = {"output_format": "mp3_44100_128"}
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(url, json=payload, headers=headers, params=params)
            response.raise_for_status()
            return response.content
    except Exception:
        logger.exception("ElevenLabs TTS failed")
        return None


async def _edge_tts(text: str, voice: str) -> bytes | None:
    try:
        import edge_tts

        communicate = edge_tts.Communicate(text, voice)
        chunks: list[bytes] = []
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                chunks.append(chunk["data"])
        return b"".join(chunks)
    except Exception:
        logger.exception("Edge TTS failed")
        return None


def _mp3_to_ogg(mp3: bytes) -> bytes | None:
    with tempfile.NamedTemporaryFile(suffix=".mp3") as source, tempfile.NamedTemporaryFile(
        suffix=".ogg"
    ) as destination:
        source.write(mp3)
        source.flush()
        subprocess.run(
            ["ffmpeg", "-y", "-i", source.name, "-c:a", "libopus", "-b:a", "64k", destination.name],
            check=True,
            capture_output=True,
        )
        destination.seek(0)
        return destination.read()


async def generate_selfie(prompt: str, use_nsfw_lora: bool = False) -> bytes | None:
    """Generate a selfie via FAL (configurable model + optional NSFW LoRA)."""
    settings = get_settings()
    if not settings.fal_key:
        return None
    url = f"https://fal.run/{settings.fal_model}"
    headers = {"Authorization": f"Key {settings.fal_key}"}
    payload = {"prompt": prompt, "image_size": "square_hd", "num_images": 1}
    if use_nsfw_lora and settings.fal_lora_url:
        payload["loras"] = [{"path": settings.fal_lora_url, "scale": settings.fal_lora_scale}]
    try:
        async with httpx.AsyncClient(timeout=300) as client:
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
        image_url = data["images"][0]["url"]
        async with httpx.AsyncClient(timeout=60) as client:
            image = await client.get(image_url)
            image.raise_for_status()
            return image.content
    except httpx.HTTPStatusError as exc:
        logger.exception("FAL image generation failed: %s", exc.response.text[:500])
        return None
    except Exception:
        logger.exception("FAL image generation failed")
        return None
