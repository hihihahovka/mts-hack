"""
TTS Engine — edge-tts wrapper
==============================
Async text-to-speech using Microsoft Edge TTS (free, high quality).
Supports Russian voices with natural intonation.
"""

import os
import logging
import edge_tts

log = logging.getLogger(__name__)

# Available Russian voices
VOICES = {
    "male": "ru-RU-DmitryNeural",
    "female": "ru-RU-SvetlanaNeural",
}

DEFAULT_VOICE = os.getenv("TTS_VOICE", VOICES["male"])


async def synthesize(text: str, voice: str | None = None) -> bytes | None:
    """
    Synthesize text to MP3 audio bytes using edge-tts.
    
    Args:
        text: Text to synthesize
        voice: Voice ID (default from env or DmitryNeural)
        
    Returns:
        MP3 audio bytes, or None on error
    """
    if not text or not text.strip():
        return None

    voice = voice or DEFAULT_VOICE

    try:
        communicate = edge_tts.Communicate(text.strip(), voice)
        audio_data = b""
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_data += chunk["data"]

        if audio_data:
            return audio_data
        return None

    except Exception as e:
        log.error(f"TTS synthesis error: {e}")
        return None


async def list_voices(language: str = "ru") -> list[dict]:
    """List available voices for a language."""
    voices = await edge_tts.list_voices()
    return [v for v in voices if v["Locale"].startswith(language)]
