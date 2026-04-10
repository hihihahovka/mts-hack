#!/usr/bin/env bash
# =====================================================
#  run_local.sh — полный аналог docker-compose up
#  Запускает Open WebUI локально без Docker
#  Использование: ./run_local.sh
# =====================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ── Цвета для вывода ──────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

log()    { echo -e "${CYAN}[run_local]${NC} $1"; }
success(){ echo -e "${GREEN}[run_local]${NC} $1"; }
warn()   { echo -e "${YELLOW}[run_local]${NC} $1"; }
error()  { echo -e "${RED}[run_local]${NC} $1"; }

# ── Загружаем .env ────────────────────────────────
if [ -f ".env" ]; then
    log "Загружаем переменные из .env..."
    set -a
    # shellcheck disable=SC1091
    source .env
    set +a
else
    warn ".env не найден, используем значения по умолчанию"
fi

# ── Проверка API ключа ────────────────────────────
if [ -z "$OPENAI_API_KEY" ] || [ "$OPENAI_API_KEY" = "sk-YOUR_API_KEY_HERE" ]; then
    error "OPENAI_API_KEY не задан! Вставь свой ключ в файл .env"
    exit 1
fi
success "API ключ найден ✓"

# ── Проверка зависимостей ─────────────────────────
check_cmd() {
    if ! command -v "$1" &>/dev/null; then
        error "Не найдена команда: $1. Установи её и повтори."
        exit 1
    fi
}

check_cmd node
check_cmd npm

# ── Ищем python3.11 (Homebrew или системный) ──────
PYTHON311=""
for candidate in \
    "/opt/homebrew/opt/python@3.11/bin/python3.11" \
    "/usr/local/opt/python@3.11/bin/python3.11" \
    "$(command -v python3.11 2>/dev/null)" ; do
    if [ -x "$candidate" ]; then
        PYTHON311="$candidate"
        break
    fi
done

if [ -z "$PYTHON311" ]; then
    error "python3.11 не найден!"
    error "Установи через Homebrew:  brew install python@3.11"
    exit 1
fi
log "Используем Python: $PYTHON311 ($($PYTHON311 --version))"

# cmake нужен для некоторых Python-пакетов
if ! command -v cmake &>/dev/null; then
    warn "cmake не найден — устанавливаем через brew..."
    brew install cmake || { error "Не удалось установить cmake. Попробуй вручную: brew install cmake"; exit 1; }
fi

# ffmpeg нужен для аудио (pydub)
if ! command -v ffmpeg &>/dev/null; then
    warn "ffmpeg не найден — устанавливаем через brew..."
    brew install ffmpeg --quiet || warn "Не удалось установить ffmpeg, но это не критично"
fi


# ── Виртуальное окружение Python ──────────────────
VENV_DIR="$SCRIPT_DIR/.venv"

# Если .venv создан другим Python — удаляем и пересоздаём
if [ -d "$VENV_DIR" ]; then
    VENV_PYTHON="$VENV_DIR/bin/python3"
    if [ -x "$VENV_PYTHON" ]; then
        VENV_VER=$("$VENV_PYTHON" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null || echo "unknown")
        if [ "$VENV_VER" != "3.11" ]; then
            warn "Существующий .venv собран на Python $VENV_VER, а нужен 3.11 — пересоздаём..."
            rm -rf "$VENV_DIR"
        fi
    fi
fi

if [ ! -d "$VENV_DIR" ]; then
    log "Создаём виртуальное окружение Python 3.11 в .venv ..."
    "$PYTHON311" -m venv "$VENV_DIR"
fi

# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"
success "venv активирован (Python $(python3 --version)) ✓"

# ── Установка Python-зависимостей ─────────────────
log "Проверяем/устанавливаем Python-зависимости (backend/requirements.txt)..."
pip install --quiet --upgrade pip uv
uv pip install -r backend/requirements.txt --quiet
success "Python-зависимости установлены ✓"

# ── Установка Node-зависимостей ───────────────────
if [ ! -d "node_modules" ]; then
    log "Устанавливаем Node-зависимости (npm ci)..."
    npm ci --force
    success "Node-зависимости установлены ✓"
else
    log "node_modules уже существует, пропускаем npm ci"
fi

# ── Генерация секретного ключа ────────────────────
KEY_FILE="backend/.webui_secret_key"
if [ -z "$WEBUI_SECRET_KEY" ]; then
    if [ ! -f "$KEY_FILE" ]; then
        log "Генерируем WEBUI_SECRET_KEY..."
        head -c 12 /dev/random | base64 > "$KEY_FILE"
    fi
    export WEBUI_SECRET_KEY
    WEBUI_SECRET_KEY=$(cat "$KEY_FILE")
    log "WEBUI_SECRET_KEY загружен из $KEY_FILE"
fi

# ── Создаём папку для данных ──────────────────────
mkdir -p backend/data
success "backend/data готова ✓"

# ── Функция cleanup при Ctrl+C ────────────────────
PIDS=()
cleanup() {
    echo ""
    warn "Останавливаем все процессы..."
    for pid in "${PIDS[@]}"; do
        kill "$pid" 2>/dev/null || true
    done
    wait 2>/dev/null
    success "Всё остановлено. Пока!"
    exit 0
}
trap cleanup SIGINT SIGTERM

# ── Запуск бэкенда ────────────────────────────────
log "Запускаем Python-бэкенд на порту ${PORT:-8080}..."

(
    cd "$SCRIPT_DIR/backend"
    WEBUI_SECRET_KEY="$WEBUI_SECRET_KEY" \
    OPENAI_API_KEY="$OPENAI_API_KEY" \
    OPENAI_API_BASE_URL="${OPENAI_API_BASE_URL:-https://api.openai.com/v1}" \
    OLLAMA_BASE_URL="${OLLAMA_BASE_URL:-}" \
    CORS_ALLOW_ORIGIN="${CORS_ALLOW_ORIGIN:-http://localhost:5173;http://localhost:8080}" \
    FORWARDED_ALLOW_IPS="${FORWARDED_ALLOW_IPS:-*}" \
    SCARF_NO_ANALYTICS=true \
    DO_NOT_TRACK=true \
    ANONYMIZED_TELEMETRY=false \
    PORT="${PORT:-8080}" \
    "$VENV_DIR/bin/python3" -m uvicorn open_webui.main:app \
        --host 0.0.0.0 \
        --port "${PORT:-8080}" \
        --forwarded-allow-ips "*" \
        2>&1 | sed 's/^/[backend] /'
) &
BACKEND_PID=$!
PIDS+=("$BACKEND_PID")

log "Ждём запуска бэкенда (до 2 минут — идут миграции БД)..."
BACKEND_PORT="${PORT:-8080}"
for i in $(seq 1 120); do
    if curl -sf "http://localhost:${BACKEND_PORT}/health" > /dev/null 2>&1; then
        success "Бэкенд запущен на http://localhost:${BACKEND_PORT} ✓"
        break
    fi
    # Показываем прогресс каждые 10 секунд
    if (( i % 10 == 0 )); then
        log "Ещё ждём... (${i}/120 сек)"
    fi
    sleep 1
    if [ "$i" -eq 120 ]; then
        error "Бэкенд не стартовал за 2 минуты. Проверь логи выше."
        cleanup
    fi
done

# ── Запуск фронтенда (dev server) ─────────────────
log "Запускаем Vite dev server (фронтенд)..."

(
    cd "$SCRIPT_DIR"
    VITE_API_BASE_URL="http://localhost:${PORT:-8080}" \
    npm run dev 2>&1 | sed 's/^/[frontend] /'
) &
FRONTEND_PID=$!
PIDS+=("$FRONTEND_PID")

echo ""
success "════════════════════════════════════════════════"
success "  Open WebUI работает!"
success "  → Фронтенд (UI):  http://localhost:5173"
success "  → Бэкенд (API):   http://localhost:${PORT:-8080}"
success "  Ctrl+C — остановить всё"
success "════════════════════════════════════════════════"
echo ""

# Ждём фоновые процессы
wait
