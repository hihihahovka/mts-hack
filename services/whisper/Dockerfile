FROM python:3.11-slim

WORKDIR /app

# Install system dependencies for audio processing
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg && \
    rm -rf /var/lib/apt/lists/*

# Install Python dependencies
RUN pip install --no-cache-dir \
    faster-whisper==1.1.0 \
    fastapi==0.115.6 \
    uvicorn[standard]==0.34.0 \
    python-multipart==0.0.18 \
    requests

# Model will be downloaded on first request (~1-2 min)
# This avoids slow/fragile downloads during docker build
ENV WHISPER_MODEL=medium
ENV WHISPER_COMPUTE_TYPE=int8

COPY main.py .

EXPOSE 9000

CMD ["python", "main.py"]
