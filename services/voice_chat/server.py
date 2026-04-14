"""
Voice Chat Server
=================
FastAPI + WebSocket server for real-time voice chat.
Pipeline: Browser Audio → VAD → Whisper STT → MWS GPT (streaming) → edge-tts → Browser Audio

WebSocket Protocol (JSON events):
  Client → Server:
    - { "type": "audio_chunk", "data": "<base64 Int16 PCM 16kHz>" }
    - { "type": "interrupt" }
    - { "type": "config", "model": "...", "system_prompt": "...", "voice": "..." }

  Server → Client:
    - { "type": "status", "state": "listening|thinking|speaking" }
    - { "type": "transcript", "text": "..." }
    - { "type": "assistant_text", "text": "...", "done": false }
    - { "type": "assistant_audio", "audio": "<base64 MP3>" }
    - { "type": "error", "message": "..." }
    - { "type": "rms", "level": 0.0 }
"""

import asyncio
import base64
import io
import json
import logging
import os
import re
import tempfile
import wave
import threading
_transcribe_lock = threading.Lock()
from pathlib import Path

import aiohttp
import numpy as np
import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from vad import EnergyVAD
import tts_engine

# ── Configuration ──────────────────────────────────────────────
MWS_API_KEY = os.getenv("MWS_API_KEY", "")
MWS_API_BASE_URL = os.getenv("MWS_API_BASE_URL", "https://api.gpt.mws.ru/v1")
DEFAULT_MODEL = os.getenv("DEFAULT_MODEL", "mws-gpt-alpha")
WHISPER_MODEL_SIZE = "tiny"  # Hardcoded to tiny for x4 speedup (overrides docker-compose)
TTS_VOICE = os.getenv("TTS_VOICE", "ru-RU-DmitryNeural")
SAMPLE_RATE = 16000

VOICE_SYSTEM_PROMPT = """Ты — голосовой ассистент. Отвечай МАКСИМАЛЬНО кратко: 1-2 коротких предложения.
Говори простым разговорным языком. Никакого markdown. Только plain text.
Язык: русский."""

# ── Logging ────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
log = logging.getLogger("voice-chat")

# ── Whisper Model (lazy-loaded) ────────────────────────────────
_whisper_model = None


def get_whisper_model():
    global _whisper_model
    if _whisper_model is None:
        from faster_whisper import WhisperModel

        log.info(f"Loading Whisper model: {WHISPER_MODEL_SIZE} (CPU, int8)")
        _whisper_model = WhisperModel(WHISPER_MODEL_SIZE, device="cpu", compute_type="int8")
        log.info("Whisper model loaded successfully")
    return _whisper_model


def transcribe_audio(audio_int16_bytes: bytes) -> str:
    """Transcribe Int16 PCM audio bytes to text using faster-whisper."""
    model = get_whisper_model()

    # Write audio to a temporary WAV file
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        tmp_path = f.name
        with wave.open(f, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)  # 16-bit
            wav.setframerate(SAMPLE_RATE)
            wav.writeframes(audio_int16_bytes)

    try:
        # CTranslate2 / faster-whisper is not thread-safe. We must ensure only one
        # transcription runs at a time. If the pipeline was cancelled, this thread will Complete
        # before the next thread is allowed to call transcribe.
        with _transcribe_lock:
            # beam_size=1 is greedy decoding: much faster, minimal accuracy loss
            segments, info = model.transcribe(
                tmp_path,
                language="ru",
                beam_size=1,
                vad_filter=True,
                vad_parameters=dict(min_silence_duration_ms=500),
            )
            text = " ".join(segment.text.strip() for segment in segments).strip()
        log.info(f"Transcribed ({info.language}, {info.duration:.1f}s): {text[:80]}...")
        return text
    except Exception as e:
        log.error(f"Transcription error: {e}")
        return ""
    finally:
        os.unlink(tmp_path)


# ── Phrase Splitting (optimized for low-latency TTS) ─────────

# Split on sentence-ending punctuation AND commas/colons/semicolons
# This lets TTS start much sooner — after each phrase, not each sentence
PHRASE_RE = re.compile(r'(?<=[.!?;,:\—–])\s+')


def split_phrases(text: str) -> tuple[list[str], str]:
    """
    Split text into speakable phrases and a remainder.
    Splits on commas, colons, periods etc. for faster TTS start.
    Returns (list_of_complete_phrases, remaining_text).
    """
    parts = PHRASE_RE.split(text)
    if not parts:
        return [], text

    phrases = []
    for part in parts[:-1]:
        p = part.strip()
        if len(p) >= 3:  # Skip tiny fragments
            phrases.append(p)

    remainder = parts[-1].strip() if parts else ""

    # If remainder ends with punctuation, it's a complete phrase
    if remainder and remainder[-1] in '.!?;,:\—–':
        if len(remainder) >= 3:
            phrases.append(remainder)
        remainder = ""

    return phrases, remainder


# ── LLM Streaming ────────────────────────────────────────────

async def stream_llm(messages: list[dict], model: str):
    """Stream tokens from MWS GPT API (OpenAI-compatible)."""
    url = f"{MWS_API_BASE_URL}/chat/completions"
    payload = {
        "model": model,
        "messages": messages,
        "stream": True,
        "temperature": 0.5,
        "max_tokens": 150,  # Short answers for voice — keeps it snappy
    }
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {MWS_API_KEY}",
    }

    timeout = aiohttp.ClientTimeout(total=60)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(url, json=payload, headers=headers) as resp:
            if resp.status != 200:
                error_text = await resp.text()
                log.error(f"LLM API error {resp.status}: {error_text[:200]}")
                raise Exception(f"LLM API error: {resp.status}")

            async for line in resp.content:
                line = line.decode("utf-8").strip()
                if not line or not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                    delta = chunk.get("choices", [{}])[0].get("delta", {})
                    content = delta.get("content", "")
                    if content:
                        yield content
                except json.JSONDecodeError:
                    continue


# ── Voice Session ────────────────────────────────────────────

class VoiceSession:
    """Manages a single voice chat WebSocket session."""

    def __init__(self, ws: WebSocket):
        self.ws = ws
        self.vad = EnergyVAD(
            speech_threshold=0.012,
            silence_threshold=0.006,
            silence_duration_ms=700,  # Greatly reduced from 1500 to catch pauses faster
            min_speech_duration_ms=400,
        )
        self.audio_buffer = bytearray()
        self.conversation_history: list[dict] = []
        self.current_task: asyncio.Task | None = None
        self.is_generating = False
        self.model = DEFAULT_MODEL
        self.system_prompt = VOICE_SYSTEM_PROMPT
        self.tts_voice = TTS_VOICE

    async def send_event(self, event_type: str, data: dict):
        """Send a JSON event to the client."""
        try:
            await self.ws.send_json({"type": event_type, **data})
        except Exception:
            pass  # Connection might be closed

    async def handle_message(self, message: dict):
        """Handle an incoming WebSocket message."""
        msg_type = message.get("type", "")

        if msg_type == "audio_chunk":
            await self.handle_audio_chunk(message.get("data", ""))

        elif msg_type == "interrupt":
            await self.interrupt()

        elif msg_type == "config":
            self.model = message.get("model", DEFAULT_MODEL)
            if message.get("system_prompt"):
                self.system_prompt = message["system_prompt"]
            if message.get("voice"):
                self.tts_voice = message["voice"]
            log.info(f"Session config: model={self.model}, voice={self.tts_voice}")

    async def handle_audio_chunk(self, data: str):
        """Process incoming audio chunk."""
        if not data:
            return

        # ★ IGNORE all audio while assistant is generating/speaking
        # This prevents accidental interruption from noise/echo
        if self.is_generating:
            return

        try:
            audio_bytes = base64.b64decode(data)
        except Exception:
            return

        # Accumulate audio
        self.audio_buffer.extend(audio_bytes)

        # Run VAD
        vad_result = self.vad.process_chunk(audio_bytes)

        # Send RMS level to client for visualization (throttled)
        if len(self.audio_buffer) % (SAMPLE_RATE // 2) < len(audio_bytes):
            await self.send_event("rms", {"level": vad_result["rms"]})

        # Check if speech ended
        if vad_result["speech_ended"]:
            log.info("Speech ended detected by VAD")

            # Grab the audio and clear the buffer
            audio_data = bytes(self.audio_buffer)
            self.audio_buffer.clear()
            self.vad.reset()

            # Avoid processing tiny audio clips
            if len(audio_data) < SAMPLE_RATE // 2:  # Less than 0.25 seconds
                await self.send_event("status", {"state": "listening"})
                return

            # Start the response pipeline
            self.current_task = asyncio.create_task(self.process_utterance(audio_data))

    async def interrupt(self):
        """Cancel the current response pipeline and stop client audio."""
        if self.current_task and not self.current_task.done():
            self.current_task.cancel()
            try:
                await self.current_task
            except asyncio.CancelledError:
                pass
        self.is_generating = False
        self.audio_buffer.clear()
        self.vad.reset()
        # Tell client to immediately stop playing audio
        await self.send_event("stop_audio", {})
        await self.send_event("status", {"state": "listening"})
        log.info("Response interrupted")

    async def process_utterance(self, audio_data: bytes):
        """Full pipeline: STT → LLM (collect full response) → TTS → speak."""
        try:
            self.is_generating = True

            # ── Step 1: Transcribe ──
            await self.send_event("status", {"state": "thinking"})
            text = await asyncio.to_thread(transcribe_audio, audio_data)

            if not text:
                await self.send_event("status", {"state": "listening"})
                self.is_generating = False
                return

            await self.send_event("transcript", {"text": text})
            log.info(f"User said: {text}")

            # ── Step 2: Add to conversation ──
            self.conversation_history.append({"role": "user", "content": text})

            # Build messages for LLM
            messages = [{"role": "system", "content": self.system_prompt}]
            # Keep last 10 messages to reduce latency
            messages.extend(self.conversation_history[-10:])

            # ── Step 3: Stream LLM, TTS each phrase in parallel ──
            await self.send_event("status", {"state": "speaking"})
            full_response = ""
            phrase_buffer = ""
            tts_tasks = []  # Background TTS tasks

            async for token in stream_llm(messages, self.model):
                if not self.is_generating:
                    break  # Interrupted via orb click

                phrase_buffer += token
                full_response += token

                # Send accumulated text for live display
                await self.send_event("assistant_text", {"text": full_response, "done": False})

                # Try to split into speakable phrases
                phrases, remainder = split_phrases(phrase_buffer)

                for phrase in phrases:
                    # Fire TTS in background — don't block LLM streaming!
                    task = asyncio.create_task(self._tts_and_send(phrase))
                    tts_tasks.append(task)

                phrase_buffer = remainder

            # Handle remaining text after LLM finishes
            if phrase_buffer.strip() and self.is_generating:
                task = asyncio.create_task(self._tts_and_send(phrase_buffer.strip()))
                tts_tasks.append(task)

            # Wait for ALL TTS tasks to complete (let assistant finish speaking)
            if tts_tasks:
                await asyncio.gather(*tts_tasks, return_exceptions=True)

            # Mark text as done
            await self.send_event("assistant_text", {"text": full_response, "done": True})

            # Save assistant response to history
            if full_response.strip():
                self.conversation_history.append({"role": "assistant", "content": full_response.strip()})

            self.is_generating = False
            self.audio_buffer.clear()
            self.vad.reset()
            await self.send_event("status", {"state": "listening"})

        except asyncio.CancelledError:
            self.is_generating = False
            log.info("Pipeline cancelled (interrupted)")
            raise

        except Exception as e:
            log.exception(f"Pipeline error: {e}")
            self.is_generating = False
            await self.send_event("error", {"message": str(e)})
            await self.send_event("status", {"state": "listening"})

    async def _tts_and_send(self, text: str):
        """Synthesize a phrase and send audio to client. Runs as background task."""
        try:
            audio = await tts_engine.synthesize(text, self.tts_voice)
            if audio and self.is_generating:
                audio_b64 = base64.b64encode(audio).decode("ascii")
                await self.send_event("assistant_audio", {"audio": audio_b64})
        except Exception as e:
            log.warning(f"TTS error for phrase: {e}")


# ── FastAPI App ──────────────────────────────────────────────

app = FastAPI(title="Voice Chat Server", version="1.0.0")

# Serve static files (UI)
STATIC_DIR = Path(__file__).parent / "static"
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
async def index():
    """Serve the voice chat UI."""
    index_path = STATIC_DIR / "index.html"
    if index_path.exists():
        return FileResponse(index_path)
    return {"error": "UI not found"}


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "model": WHISPER_MODEL_SIZE,
        "tts_voice": TTS_VOICE,
        "llm_model": DEFAULT_MODEL,
    }


@app.get("/inject.js")
async def inject_js():
    """Serve the injection script for OpenWebUI."""
    inject_path = STATIC_DIR / "inject.js"
    if inject_path.exists():
        return FileResponse(inject_path, media_type="application/javascript")
    return ""


@app.websocket("/ws/voice")
async def voice_ws(ws: WebSocket):
    """WebSocket endpoint for real-time voice chat."""
    await ws.accept()
    log.info("Voice chat session started")

    session = VoiceSession(ws)
    await session.send_event("status", {"state": "listening"})

    try:
        while True:
            data = await ws.receive_text()
            try:
                message = json.loads(data)
                await session.handle_message(message)
            except json.JSONDecodeError:
                await session.send_event("error", {"message": "Invalid JSON"})
    except WebSocketDisconnect:
        log.info("Voice chat session disconnected")
    except Exception as e:
        log.error(f"WebSocket error: {e}")
    finally:
        # Cleanup
        if session.current_task and not session.current_task.done():
            session.current_task.cancel()


# ── Startup ──────────────────────────────────────────────────

@app.on_event("startup")
async def startup():
    """Pre-load Whisper model on startup."""
    log.info("Pre-loading Whisper model...")
    await asyncio.to_thread(get_whisper_model)
    log.info("Voice Chat Server ready!")


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=9001)
