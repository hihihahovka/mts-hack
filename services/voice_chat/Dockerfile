FROM python:3.11-slim

WORKDIR /app

# System deps for audio processing
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg && \
    rm -rf /var/lib/apt/lists/*

# Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# App code
COPY server.py .
COPY vad.py .
COPY tts_engine.py .
COPY static/ static/

# Pre-download whisper model at build time for faster startup
RUN python -c "from faster_whisper import WhisperModel; WhisperModel('small', device='cpu', compute_type='int8')" || true

EXPOSE 9001

CMD ["python", "server.py"]
