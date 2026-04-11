#!/bin/bash
# ============================================================
# MTS AI Workspace — Setup Script
# ============================================================
# Run this after docker-compose up to pull VLM model
# Usage: ./scripts/setup.sh

set -e

echo "============================================"
echo "  MTS AI Workspace — Initial Setup"
echo "============================================"

# Wait for Ollama to be ready
echo "[setup] Waiting for Ollama..."
until docker exec ollama ollama list &>/dev/null; do
    sleep 2
done
echo "[setup] Ollama is ready!"

# Pull Moondream 2B for VLM (image analysis)
echo "[setup] Pulling Moondream 2B model for Vision..."
docker exec ollama ollama pull moondream
echo "[setup] ✅ Moondream 2B downloaded"

echo ""
echo "============================================"
echo "  ✅ Setup complete!"
echo "  Open http://localhost:8080"
echo "============================================"
