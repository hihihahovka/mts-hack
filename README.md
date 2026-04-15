# MTS AI Workspace

> Единое ИИ-пространство на базе OpenWebUI + MWS GPT API

## 🚀 Быстрый запуск

```bash
# 1. Клонировать репозиторий
git clone <repo-url>
cd mts-ai-workspace

# 2. Настроить API ключ
cp .env.example .env
# Вписать MWS_API_KEY в .env

# 3. Запустить всё одной командой
make install

# 4. Проверить что всё работает
make test

# 5. Открыть в браузере
open http://localhost:8080
```

**Учётные данные администратора:**
- Email: `admin@mts-ai.local`
- Пароль: `adminpassword123`

Или зарегистрируйтесь через **Sign Up** (каждый новый пользователь получает права админа).

> 💡 `make test` запускает автоматические smoke-тесты: проверяет связность сервисов, авторизацию, модели, tools, functions, TTS и поиск.

## 📦 Сервисы

| Сервис | Порт | Назначение |
|---|---|---|
| **OpenWebUI** | 8080 | Основной чат-интерфейс |
| **PostgreSQL** | 5432 | База данных |
| **SearXNG** | 8888 | Web Search (self-hosted) |
| **Whisper API** | 9000 | Голосовой ввод (ASR, faster-whisper) |
| **Portainer** | 9010 | Мониторинг контейнеров |
| **Dozzle** | 9990 | Просмотр логов в реальном времени |

## 🧠 Модели MWS GPT

| Модель | Назначение |
|---|---|
| `mws-gpt-alpha` | Основной LLM (общие запросы) |
| `kodify-2.0` | Код-генерация, дебаг |
| `cotype-preview-32k` | Длинные документы (32k контекст) |
| `bge-m3` | Embeddings для RAG |
| `qwen-image` / `qwen-image-lightning` | Генерация изображений |

## ⚡ Ключевые фичи

- ✅ **Автоматическая маршрутизация** — система сама выбирает модель под задачу
- ✅ **Голосовой ввод** — faster-whisper (локальный, русский язык)
- ✅ **Генерация изображений** — MWS GPT API (qwen-image)
- ✅ **Web Search** — SearXNG (self-hosted)
- ✅ **Web Scraping** — Jina Reader API
- ✅ **RAG** — загрузка PDF/DOCX с поиском через bge-m3
- ✅ **Долгосрочная память** — экстракция фактов о пользователе
- ✅ **TTS** — озвучивание ответов (русский язык)
- ✅ **Deep Research** — multi-step research agent
- ✅ **Realtime Voice Chat** — голосовой чат как в ChatGPT (WebSocket + Whisper + edge-tts)
- ✅ **Система тем** — 7 цветовых палитр

## 🏗️ Архитектура

```
┌─────────────────────────────────────────────────┐
│                  OpenWebUI (8080)                │
│  ┌───────────┐ ┌──────────┐ ┌─────────────────┐ │
│  │ Chat UI   │ │ RAG+Files│ │ Tools/Functions  │ │
│  └─────┬─────┘ └────┬─────┘ └───────┬─────────┘ │
│        │            │               │            │
│  ┌─────▼────────────▼───────────────▼─────────┐  │
│  │           🧠 Auto Router Filter            │  │
│  │  (модальность → ключевые слова → LLM)      │  │
│  └──────┬──────────┬────────────┬─────────────┘  │
└─────────┼──────────┼────────────┼────────────────┘
          │          │            │
   ┌──────▼───┐ ┌───▼────┐ ┌───▼────────┐
   │ MWS GPT  │ │Whisper │ │  Tools     │
   │ API      │ │  API   │ │            │
   │·alpha    │ │ (ASR)  │ │·ImagePipe  │
   │·kodify   │ └────────┘ │·WebScraper │
   │·cotype   │            │·Research   │
   │·bge-m3   │ ┌────────┐ └────────────┘
   │·qwen-img │ │SearXNG │
   └──────────┘ │(Search)│
                └────────┘
```

## 🛠️ Управление проектом (Makefile)

```bash
make install  # Первоначальная настройка + запуск
make start    # Запустить все сервисы
make stop     # Остановить сервисы
make restart  # Перезапустить
make status   # Проверить состояние контейнеров
make logs     # Логи в реальном времени
make seed     # Обновить tools/functions (пересобрать seed)
make update   # Обновить seed + open-webui
make wipe     # ⚠️ Удалить всё + базы данных
```

## 📁 Структура проекта

```
mts-ai-workspace/
├── docker-compose.yml          # Оркестрация сервисов
├── Dockerfile.openwebui        # Кастомный образ OpenWebUI (темы, патчи)
├── .env.example                # Шаблон переменных окружения
├── Makefile                    # Управление проектом
├── README.md
├── config/searxng/             # Конфигурация SearXNG
├── services/whisper/           # faster-whisper ASR сервис
│   ├── Dockerfile
│   └── main.py
├── tools/                      # OpenWebUI Tools
│   ├── web_scraper_tool.py     # Jina Reader
│   └── deep_research_tool.py   # Multi-step research agent
├── functions/                  # OpenWebUI Functions (Filters/Pipes)
│   ├── auto_router_filter.py   # Автовыбор модели
│   ├── memory_extract_filter.py# Экстракция фактов (Outlet)
│   ├── context_inject_filter.py# Инжекция памяти (Inlet)
│   └── image_gen_pipe.py       # Генерация картинок (Pipe)
├── themes/
│   ├── custom.css              # 7 цветовых тем
│   └── theme-selector.js       # Виджет переключения тем
└── scripts/
    ├── setup.sh                # Проверка состояния
    ├── seed_tools.py           # Автозагрузка tools/functions
    └── Dockerfile.seed         # Образ для seed
```

## 🔧 Требования

- Docker + Docker Compose
- ~8 GB свободной RAM
- Интернет-соединение (для MWS GPT API)

## 📄 Лицензия

Hackathon project — MTS AI Workspace
