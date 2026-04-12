"""
Deep Research Tool
====================================
OpenWebUI Tool — Multi-step research agent.

Архитектура (вдохновлено Perplexity + LangChain):
┌─────────────────────────────────────────────────────────────────┐
│  ШАГ 1: ДЕКОМПОЗИЦИЯ (Query Analysis)                          │
│  ─────────────────────────────────────                          │
│  LLM разбивает сложный вопрос на 3-4 поисковых запроса          │
│  "Что такое X и как работает?" → ["что такое X", "как X работает"] │
├─────────────────────────────────────────────────────────────────┤
│  ШАГ 2: ПОИСК (Search Engine API)                               │
│  ─────────────────────────────────                               │
│  SearXNG (meta-search) возвращает топ URL по каждому запросу    │
│  Параллельно, asyncio.gather                                    │
├─────────────────────────────────────────────────────────────────┤
│  ШАГ 3: ПАРСИНГ (Crawling & Filtering)                          │
│  ─────────────────────────────────────                           │
│  Jina Reader API конвертирует HTML → чистый Markdown            │
│  Убирает рекламу, меню, скрипты. Оставляет только контент.      │
├─────────────────────────────────────────────────────────────────┤
│  ШАГ 4: СИНТЕЗ (Context Injection & Reasoning)                  │
│  ──────────────────────────────────────────────                  │
│  LLM получает собранные тексты + исходный вопрос                │
│  Анализирует, находит противоречия, генерирует отчёт            │
│  Это называется "синтезатор" — объединяет данные в ответ        │
└─────────────────────────────────────────────────────────────────┘
"""

import httpx
import asyncio
import json
import logging
import os
import re
from typing import List, Dict, Any
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class Tools:
    class Valves(BaseModel):
        """Configurable parameters."""
        searxng_base_url: str = Field(
            default="http://searxng:8080/search",
            description="SearXNG API base URL"
        )
        jina_base_url: str = Field(
            default="https://r.jina.ai",
            description="Jina Reader API base URL"
        )
        llm_base_url: str = Field(
            default="https://api.gpt.mws.ru/v1",
            description="LLM OpenAI-Compatible API Base URL"
        )
        llm_api_key: str = Field(
            default="",
            description="LLM API Key. If empty, falls back to MWS_API_KEY or OPENAI_API_KEY env."
        )
        llm_model: str = Field(
            default="mws-gpt-alpha",
            description="Model used for decomposition and synthesis"
        )
        max_links_per_query: int = Field(
            default=3,
            description="Maximum number of links to parse per sub-query"
        )
        max_content_length: int = Field(
            default=12000,
            description="Maximum content length in characters per page"
        )
        max_total_content: int = Field(
            default=50000,
            description="Maximum total content for LLM synthesis (~12k tokens)"
        )
        llm_timeout: int = Field(
            default=180,
            description="Timeout in seconds for LLM synthesis call"
        )

    def __init__(self):
        self.valves = self.Valves()

    async def emit_status(self, __event_emitter__, description: str, done: bool = False):
        """Отправляет статус в UI для показа прогресса пользователю."""
        if __event_emitter__:
            await __event_emitter__({
                "type": "status",
                "data": {"description": description, "done": done}
            })

    async def _call_llm(self, prompt: str, system: str, timeout: int = 60) -> str:
        """
        Вызов LLM через OpenAI-совместимый API.

        Args:
            prompt: Пользовательский промпт
            system: Системный промпт (роль модели)
            timeout: Таймаут в секундах
        """
        api_key = (
            self.valves.llm_api_key
            or os.environ.get("MWS_API_KEY")
            or os.environ.get("OPENAI_API_KEY", "")
        )

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }

        payload = {
            "model": self.valves.llm_model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt}
            ]
        }

        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                f"{self.valves.llm_base_url}/chat/completions",
                headers=headers,
                json=payload
            )
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]

    async def _search_query(self, query: str) -> List[Dict[str, str]]:
        """
        Поиск через SearXNG.

        Returns:
            List of {"url": str, "title": str, "snippet": str}
        """
        try:
            params = {"q": query, "format": "json"}
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(self.valves.searxng_base_url, params=params)
                resp.raise_for_status()
                results = resp.json().get("results", [])

                parsed = []
                for res in results:
                    parsed.append({
                        "url": res.get("url", ""),
                        "title": res.get("title", ""),
                        "snippet": res.get("content", "")[:500]
                    })
                    if len(parsed) >= self.valves.max_links_per_query:
                        break
                return parsed
        except Exception as e:
            logger.error(f"SearXNG search failed for '{query}': {e}")
            return []

    async def _read_url(self, url: str, __event_emitter__=None) -> str:
        """
        Парсинг страницы через Jina Reader API.
        Jina убирает рекламу, меню, скрипты — оставляет чистый текст.
        """
        # Показываем пользователю что читаем
        if __event_emitter__:
            short_url = url[:60] + "..." if len(url) > 60 else url
            await self.emit_status(__event_emitter__, f"📖 Читаю: {short_url}", False)

        try:
            jina_url = f"{self.valves.jina_base_url}/{url}"
            async with httpx.AsyncClient(timeout=25, follow_redirects=True) as client:
                resp = await client.get(
                    jina_url,
                    headers={
                        "Accept": "text/markdown",
                        "X-Return-Format": "markdown",
                    }
                )
                resp.raise_for_status()
                content = resp.text

                # Обрезаем слишком длинный контент
                if len(content) > self.valves.max_content_length:
                    # Обрезаем по последнему полному предложению
                    truncated = content[:self.valves.max_content_length]
                    last_period = truncated.rfind('.')
                    if last_period > self.valves.max_content_length // 2:
                        content = truncated[:last_period + 1] + "\n\n...[контент обрезан]"
                    else:
                        content = truncated + "\n\n...[контент обрезан]"

                return f"### Источник: {url}\n\n{content}"

        except Exception as e:
            logger.error(f"Jina Reader failed for '{url}': {e}")
            return f"### Источник: {url}\n\n[Не удалось загрузить страницу: {str(e)[:100]}]"

    async def deep_research(
        self,
        topic: str,
        __event_emitter__=None,
    ) -> str:
        """
        Выполняет глубокое исследование темы.

        Используй этот инструмент когда пользователь просит:
        - "исследуй тему X"
        - "сделай анализ Y"
        - "собери информацию о Z"
        - "глубокий разбор W"

        :param topic: Тема или вопрос для исследования.
        :return: Структурированный отчёт с источниками.
        """

        # ═══════════════════════════════════════════════════════════
        # ШАГ 1: ДЕКОМПОЗИЦИЯ ЗАПРОСА (Query Analysis)
        # ═══════════════════════════════════════════════════════════
        # LLM разбивает сложный вопрос на простые поисковые запросы.
        # Это как "менеджер" который делегирует задачи.

        await self.emit_status(
            __event_emitter__,
            "🧠 Шаг 1/4: Анализирую тему и составляю план поиска...",
            False
        )

        sys_decompose = """Ты — эксперт по поиску информации.
Разбей исследовательский вопрос пользователя на 3-4 конкретных поисковых запроса.
Каждый запрос должен искать разный аспект темы.

ВАЖНО: Верни ТОЛЬКО JSON массив строк, без пояснений.
Пример: ["запрос 1", "запрос 2", "запрос 3"]"""

        try:
            json_str = await self._call_llm(topic, sys_decompose, timeout=30)
            # Извлекаем JSON из ответа (LLM может добавить markdown)
            match = re.search(r'\[.*?\]', json_str.replace('\n', ' '), re.DOTALL)
            if match:
                sub_queries = json.loads(match.group(0))
                # Валидация
                if not isinstance(sub_queries, list) or len(sub_queries) == 0:
                    sub_queries = [topic]
            else:
                sub_queries = [topic]
        except Exception as e:
            logger.error(f"Query decomposition failed: {e}")
            sub_queries = [topic]

        # Показываем план пользователю
        queries_preview = "\n".join([f"  • {q}" for q in sub_queries[:4]])
        await self.emit_status(
            __event_emitter__,
            f"📋 План поиска:\n{queries_preview}",
            False
        )

        # ═══════════════════════════════════════════════════════════
        # ШАГ 2: ПОИСК (Search Engine API)
        # ═══════════════════════════════════════════════════════════
        # SearXNG — meta-search движок, агрегирует результаты из
        # Google, Bing, DuckDuckGo и других. Self-hosted, без трекинга.

        await self.emit_status(
            __event_emitter__,
            f"🔍 Шаг 2/4: Ищу по {len(sub_queries)} направлениям...",
            False
        )

        # Параллельный поиск по всем запросам
        search_tasks = [self._search_query(q) for q in sub_queries]
        search_results = await asyncio.gather(*search_tasks)

        # Собираем уникальные URL (дедупликация)
        seen_urls = set()
        all_results = []
        for results in search_results:
            for res in results:
                if res["url"] not in seen_urls:
                    seen_urls.add(res["url"])
                    all_results.append(res)

        if not all_results:
            await self.emit_status(
                __event_emitter__,
                "❌ Не удалось найти информацию по теме.",
                True
            )
            return "К сожалению, я не смог найти релевантную информацию в интернете по вашему запросу. Попробуйте переформулировать вопрос."

        await self.emit_status(
            __event_emitter__,
            f"✅ Найдено {len(all_results)} источников",
            False
        )

        # ═══════════════════════════════════════════════════════════
        # ШАГ 3: ПАРСИНГ (Crawling & Filtering)
        # ═══════════════════════════════════════════════════════════
        # Jina Reader API — это "чистильщик" HTML.
        # Он убирает рекламу, меню, скрипты и возвращает чистый Markdown.
        # Аналог внутреннего движка Perplexity.

        await self.emit_status(
            __event_emitter__,
            f"📖 Шаг 3/4: Читаю {len(all_results)} статей...",
            False
        )

        # Параллельный парсинг всех URL
        urls_to_read = [r["url"] for r in all_results]
        read_tasks = [self._read_url(url, __event_emitter__) for url in urls_to_read]
        read_results = await asyncio.gather(*read_tasks)

        # Объединяем контент с разделителями
        separator = "\n\n" + "═" * 60 + "\n\n"
        combined_content = separator.join(read_results)

        # Обрезаем если слишком много (защита от token overflow)
        if len(combined_content) > self.valves.max_total_content:
            combined_content = combined_content[:self.valves.max_total_content]
            combined_content += "\n\n...[часть материалов опущена из-за ограничений]"
            logger.warning(f"Content truncated to {self.valves.max_total_content} chars")

        # ═══════════════════════════════════════════════════════════
        # ШАГ 4: СИНТЕЗ (Context Injection & Reasoning)
        # ═══════════════════════════════════════════════════════════
        # "Синтезатор" — это LLM который получает:
        #   1. Исходный вопрос пользователя
        #   2. Собранные тексты из интернета
        # И генерирует структурированный отчёт.
        #
        # Это аналог Chain-of-Thought: модель анализирует данные,
        # находит противоречия, выделяет главное и пишет ответ.

        await self.emit_status(
            __event_emitter__,
            "📝 Шаг 4/4: Синтезирую финальный отчёт...",
            False
        )

        sys_synth = """Ты — аналитик экспертного уровня.

ЗАДАЧА: Составь подробный структурированный отчёт по теме на основе собранных материалов.

ТРЕБОВАНИЯ К ОТЧЁТУ:
1. Используй Markdown форматирование (заголовки, списки, выделение)
2. Структурируй информацию логически
3. Если источники противоречат друг другу — укажи это
4. В конце добавь раздел "Источники" со списком URL

ФОРМАТ:
## Краткий ответ
[2-3 предложения — суть]

## Подробный анализ
[Основной контент с подзаголовками]

## Ключевые выводы
[Буллеты с главными тезисами]

## Источники
[Список URL из материалов]"""

        prompt_synth = f"""ТЕМА ИССЛЕДОВАНИЯ: {topic}

СОБРАННЫЕ МАТЕРИАЛЫ ИЗ ИНТЕРНЕТА:
{combined_content}

Составь отчёт по теме, используя эти материалы как источник информации."""

        try:
            final_report = await self._call_llm(
                prompt_synth,
                sys_synth,
                timeout=self.valves.llm_timeout
            )
            await self.emit_status(
                __event_emitter__,
                "✅ Исследование завершено!",
                True
            )
            return final_report

        except Exception as e:
            logger.error(f"Synthesis failed: {e}")
            await self.emit_status(
                __event_emitter__,
                "❌ Ошибка при генерации отчёта",
                True
            )
            # Fallback: возвращаем сырые данные
            return f"""## Ошибка синтеза

Не удалось сгенерировать отчёт: {str(e)[:200]}

## Собранные материалы

{combined_content[:10000]}"""
