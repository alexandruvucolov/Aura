"""Optional Phase 4 media: ElevenLabs TTS voice notes and FAL Flux selfies.

Everything here degrades gracefully: when the relevant API keys are missing the
functions simply return ``None`` and the chat handler falls back to text.
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
FAL_FLUX_URL = "https://fal.run/fal-ai/flux/dev"


async def synthesize_voice(text: str) -> tuple[bytes, str] | None:
    """Return ``(audio_bytes, extension)`` or ``None`` if disabled/unavailable.

    Converts MP3 → Ogg/Opus when ``ffmpeg`` is available so the result can be
    sent as a real Telegram voice note; otherwise falls back to ``mp3`` (audio).
    """
    settings = get_settings()
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
            mp3 = response.content
    except Exception:
        logger.exception("ElevenLabs TTS failed")
        return None

    if shutil.which("ffmpeg"):
        try:
            ogg = _mp3_to_ogg(mp3)
            if ogg:
                return ogg, "ogg"
        except Exception:
            logger.exception("ffmpeg MP3 → Ogg conversion failed")
    return mp3, "mp3"


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


async def generate_selfie(prompt: str) -> bytes | None:
    """Generate a consistent-character selfie via FAL Flux; returns image bytes."""
    settings = get_settings()
    if not settings.fal_key:
        return None
    headers = {"Authorization": f"Key {settings.fal_key}"}
    payload = {"prompt": prompt, "image_size": "square_hd", "num_images": 1}
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(FAL_FLUX_URL, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
        image_url = data["images"][0]["url"]
        async with httpx.AsyncClient(timeout=60) as client:
            image = await client.get(image_url)
            image.raise_for_status()
            return image.content
    except Exception:
        logger.exception("FAL Flux image generation failed")
        return None
