"""
Whisper ASR API Service
=======================
Provides OpenAI-compatible /v1/audio/transcriptions endpoint
powered by faster-whisper (medium model, INT8 quantization, CPU).

Endpoints:
  POST /v1/audio/transcriptions  — OpenAI-compatible STT
  GET  /health                    — Health check
"""

import io
import tempfile
import os
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import JSONResponse
import uvicorn

app = FastAPI(title="Whisper ASR API", version="1.0.0")

# Lazy-load model to avoid import-time delays
_model = None


def get_model():
    global _model
    if _model is None:
        from faster_whisper import WhisperModel

        model_size = os.getenv("WHISPER_MODEL", "medium")
        compute_type = os.getenv("WHISPER_COMPUTE_TYPE", "int8")
        print(f"[whisper-api] Loading model: {model_size} (compute_type={compute_type})")
        _model = WhisperModel(model_size, device="cpu", compute_type=compute_type)
        print(f"[whisper-api] Model loaded successfully")
    return _model


@app.get("/health")
async def health():
    return {"status": "ok", "model": os.getenv("WHISPER_MODEL", "medium")}


@app.post("/v1/audio/transcriptions")
async def transcribe(
    file: UploadFile = File(...),
    model: str = Form(default="whisper-1"),
    language: str = Form(default="ru"),
    response_format: str = Form(default="json"),
):
    """
    OpenAI-compatible transcription endpoint.
    Accepts audio file, returns transcribed text.
    """
    try:
        # Read uploaded audio
        audio_bytes = await file.read()

        if len(audio_bytes) == 0:
            raise HTTPException(status_code=400, detail="Empty audio file")

        # Write to temp file (faster-whisper needs file path)
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp.write(audio_bytes)
            tmp_path = tmp.name

        try:
            # Transcribe with faster-whisper
            whisper_model = get_model()
            segments, info = whisper_model.transcribe(
                tmp_path,
                language=language if language != "auto" else None,
                beam_size=5,
                vad_filter=True,  # Skip silence for speed
                vad_parameters=dict(
                    min_silence_duration_ms=500,
                ),
            )

            # Collect all segments
            text = " ".join(segment.text.strip() for segment in segments)

            return JSONResponse(content={
                "text": text,
                "language": info.language,
                "duration": info.duration,
            })
        finally:
            # Clean up temp file
            os.unlink(tmp_path)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Transcription error: {str(e)}")


if __name__ == "__main__":
    # Pre-load model on startup
    get_model()
    uvicorn.run(app, host="0.0.0.0", port=9000)
