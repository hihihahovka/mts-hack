#!/bin/bash
# ============================================================
# MTS AI Workspace — Setup Script
# ============================================================
# Запускается после docker-compose up для дополнительной настройки
# Usage: ./scripts/setup.sh

set -e

echo "============================================"
echo "  MTS AI Workspace — Initial Setup"
echo "============================================"

# Проверяем, что все контейнеры запущены
echo "[setup] Проверяю состояние контейнеров..."
docker compose ps

# Проверяем seed логи
echo ""
echo "[setup] Логи seed-контейнера:"
docker compose logs seed 2>/dev/null || echo "[setup] Seed ещё не запускался"

echo ""
echo "============================================"
echo "  ✅ Проверка завершена!"
echo "  Откройте http://localhost:8080"
echo ""
echo "  Admin: admin@mts-ai.local"
echo "  Пароль: adminpassword123"
echo "============================================"
