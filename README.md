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
docker-compose up -d

# 4. (Первый запуск) Скачать VLM модель для анализа изображений
chmod +x scripts/setup.sh
./scripts/setup.sh

# 5. Открыть в браузере
open http://localhost:8080
```

## 📦 Сервисы

| Сервис | Порт | Назначение |
|---|---|---|
| **OpenWebUI** | 8080 | Основной интерфейс |
| **SearXNG** | 8888 | Web Search |
| **Ollama** | 11434 | VLM (Moondream 2B) |
| **Whisper API** | 9000 | Голосовой ввод (ASR) |

## 🧠 Модели MWS GPT

| Модель | Назначение |
|---|---|
| `mws-gpt-alpha` | Основной LLM (общие запросы) |
| `kodify-2.0` | Код-генерация, дебаг |
| `cotype-preview-32k` | Длинные документы (32k контекст) |
| `bge-m3` | Embeddings для RAG |

## ⚡ Ключевые фичи

- ✅ **Автоматическая маршрутизация** — система сама выбирает модель под задачу
- ✅ **Голосовой ввод** — faster-whisper (локальный, русский язык)
- ✅ **Генерация изображений** — Pollinations API (~5-15 сек)
- ✅ **Анализ изображений** — Moondream 2B VLM (CPU)
- ✅ **Web Search** — SearXNG (self-hosted)
- ✅ **Web Scraping** — Jina Reader API
- ✅ **RAG** — загрузка PDF/DOCX с поиском через bge-m3
- ✅ **Долгосрочная память** — экстракция фактов о пользователе
- ✅ **TTS** — edge-tts (русский язык)
- ✅ **Deep Research** — multi-step research agent
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
   │ MWS GPT  │ │ Ollama │ │  Tools     │
   │ API      │ │Moondream│ │            │
   │·alpha    │ │  (VLM)  │ │·ImageGen   │
   │·kodify   │ └────────┘ │·WebScraper │
   │·cotype   │            │·Research   │
   │·bge-m3   │            └────────────┘
   └──────────┘
        ▲               ┌─────────────┐
        │               │  SearXNG    │
   ┌────┴─────┐         │ (Web Search)│
   │ Whisper  │         └─────────────┘
   │ API(ASR) │
   └──────────┘
```

## 📁 Структура проекта

```
mts-ai-workspace/
├── docker-compose.yml          # Однострочный запуск
├── .env.example                # Переменные окружения
├── README.md
├── config/searxng/             # Конфигурация SearXNG
├── services/whisper/           # faster-whisper ASR сервис
├── tools/                      # OpenWebUI Tools
│   ├── image_gen_tool.py       # Pollinations API
│   ├── web_scraper_tool.py     # Jina Reader
│   └── deep_research_tool.py   # Multi-step research
├── functions/                  # OpenWebUI Filter Functions
│   ├── auto_router_filter.py   # Автовыбор модели
│   ├── memory_extract_filter.py# Экстракция фактов
│   └── context_inject_filter.py# Инжекция памяти
├── themes/custom.css           # 7 цветовых тем
├── scripts/
│   ├── setup.sh                # Загрузка VLM модели
│   └── seed_tools.py           # Автозагрузка tools/functions
└── docs/
    ├── architecture.md         # Архитектурная схема
    └── features.md             # Шаблон фичей
```

## 🔧 Требования

- Docker + Docker Compose
- ~8 GB свободной RAM
- Интернет-соединение (для MWS GPT API и Pollinations)

## 📄 Лицензия

Hackathon project — MTS AI Workspace
