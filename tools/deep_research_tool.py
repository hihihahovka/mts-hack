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
from urllib.parse import urlsplit, urlunsplit
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
            default=5,
            description="Maximum number of links to parse per sub-query"
        )
        max_content_length: int = Field(
            default=12000,
            description="Maximum content length in characters per page"
        )
        max_total_content: int = Field(
            default=40000,
            description="Maximum total content for LLM synthesis (~10k tokens)"
        )
        llm_timeout: int = Field(
            default=180,
            description="Timeout in seconds for LLM synthesis call"
        )
        llm_retries: int = Field(
            default=2,
            description="Number of retries for transient LLM network failures"
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

        last_error = None
        for attempt in range(self.valves.llm_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    resp = await client.post(
                        f"{self.valves.llm_base_url}/chat/completions",
                        headers=headers,
                        json=payload
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    return data["choices"][0]["message"]["content"]
            except (httpx.ConnectTimeout, httpx.ConnectError, httpx.ReadError) as e:
                last_error = e
                if attempt >= self.valves.llm_retries:
                    break
                await asyncio.sleep(1 + attempt)

        raise last_error

    async def _call_llm_streaming(self, prompt: str, system: str, __event_emitter__, timeout: int = 180) -> str:
        """Стриминговый вызов LLM, пишет токены прямо в чат.
        
        Ключевое: используем httpx.Timeout с раздельными таймаутами.
        connect=15s — быстро подключиться к серверу.
        read=300s — каждый отдельный chunk может ждать до 5 мин.
        Это предотвращает убийство стрима из-за медленной генерации.
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
            ],
            "stream": True
        }
        
        # Раздельные таймауты: connect быстро, read берём из timeout.
        stream_timeout = httpx.Timeout(
            connect=15.0,
            read=max(30.0, float(timeout)),
            write=30.0,
            pool=15.0
        )

        full_text = ""
        chunk_count = 0
        ui_buffer = ""
        try:
            last_error = None
            for attempt in range(self.valves.llm_retries + 1):
                try:
                    async with httpx.AsyncClient(timeout=stream_timeout) as client:
                        async with client.stream(
                            "POST",
                            f"{self.valves.llm_base_url}/chat/completions",
                            headers=headers,
                            json=payload
                        ) as response:
                            response.raise_for_status()
                            async for line in response.aiter_lines():
                                if not line:
                                    continue
                                if not line.startswith("data:"):
                                    continue

                                data_line = line[5:].strip()
                                if data_line == "[DONE]":
                                    break
                                try:
                                    data = json.loads(data_line)
                                    delta = data["choices"][0]["delta"].get("content", "")
                                    if delta:
                                        full_text += delta
                                        chunk_count += 1
                                        ui_buffer += delta

                                        # Батчим отправку, чтобы не блокировать UI/сокет на каждый токен.
                                        if __event_emitter__:
                                            if len(ui_buffer) >= 120 or "\n" in delta:
                                                await __event_emitter__({
                                                    "type": "message",
                                                    "data": {"content": ui_buffer}
                                                })
                                                ui_buffer = ""
                                except (json.JSONDecodeError, KeyError, IndexError):
                                    pass

                    break
                except (httpx.ConnectTimeout, httpx.ConnectError, httpx.ReadError) as e:
                    last_error = e
                    if full_text or attempt >= self.valves.llm_retries:
                        raise
                    await asyncio.sleep(1 + attempt)

            if __event_emitter__ and ui_buffer:
                await __event_emitter__({
                    "type": "message",
                    "data": {"content": ui_buffer}
                })
        except httpx.ReadTimeout:
            logger.error("Streaming LLM read timeout — модель перестала отвечать")
            if not full_text:
                full_text = "Ошибка: модель перестала отвечать (ReadTimeout). Попробуйте снова."
        except httpx.ConnectTimeout:
            logger.error("Streaming LLM connect timeout — не удалось подключиться к API")
            if not full_text:
                full_text = "Ошибка: не удалось подключиться к API (ConnectTimeout)."
        except Exception as e:
            logger.error(f"Streaming failed: {type(e).__name__}: {e}")
            if not full_text:
                full_text = f"Ошибка генерации: {type(e).__name__}: {e}"
        
        logger.info(f"Streaming complete: {chunk_count} chunks, {len(full_text)} chars")
        return full_text

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

    async def _direct_scrape(self, url: str) -> str:
        """
        Fallback-скрейпер: загружает страницу напрямую и убирает HTML-теги.
        Используется когда Jina Reader не может загрузить (451, timeout и т.д.).
        Запрос идёт с IP контейнера (= ваш IP), поэтому гео-блокировок нет.
        """
        async with httpx.AsyncClient(
            timeout=15,
            follow_redirects=True,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
            }
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            html = resp.text

        # Убираем script, style, nav, footer, header блоки
        for tag in ["script", "style", "nav", "footer", "header", "aside", "noscript"]:
            html = re.sub(rf"<{tag}[^>]*>.*?</{tag}>", "", html, flags=re.DOTALL | re.IGNORECASE)

        # Убираем все HTML-теги, оставляем текст
        text = re.sub(r"<[^>]+>", " ", html)
        # Убираем лишние пробелы и пустые строки
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n\s*\n", "\n\n", text)
        text = text.strip()

        return text

    async def _read_url(self, url: str, __event_emitter__=None) -> str:
        """
        Парсинг страницы: сначала Jina Reader, при ошибке — прямой скрейпинг.
        """
        if __event_emitter__:
            short_url = url[:60] + "..." if len(url) > 60 else url
            await self.emit_status(__event_emitter__, f"📖 Читаю: {short_url}", False)

        content = None

        # --- Попытка 1: Jina Reader (чистый markdown) ---
        try:
            jina_url = f"{self.valves.jina_base_url}/{url}"
            async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
                resp = await client.get(
                    jina_url,
                    headers={
                        "Accept": "text/markdown",
                        "X-Return-Format": "markdown",
                    }
                )
                resp.raise_for_status()
                content = resp.text
                logger.info(f"Jina OK: {url} ({len(content)} chars)")
        except Exception as e:
            logger.warning(f"Jina failed for '{url}': {e} — trying direct scrape")

        # --- Попытка 2: Прямой скрейпинг (если Jina не смогла) ---
        if not content:
            try:
                content = await self._direct_scrape(url)
                logger.info(f"Direct scrape OK: {url} ({len(content)} chars)")
            except Exception as e2:
                logger.error(f"Direct scrape also failed for '{url}': {e2}")
                return f"### Источник: {url}\n\n[Не удалось загрузить страницу: {str(e2)[:100]}]"

        # --- Обрезка ---
        if len(content) > self.valves.max_content_length:
            truncated = content[:self.valves.max_content_length]
            last_period = truncated.rfind('.')
            if last_period > self.valves.max_content_length // 2:
                content = truncated[:last_period + 1] + "\n\n...[контент обрезан]"
            else:
                content = truncated + "\n\n...[контент обрезан]"

        return f"### Источник: {url}\n\n{content}"

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
Разбей исследовательский вопрос пользователя на 4-5 конкретных поисковых запросов.
Каждый запрос должен искать разный аспект темы.
Делай запросы на том же языке, что и вопрос пользователя.

ВАЖНО: Верни ТОЛЬКО JSON массив строк, без пояснений.
Пример: ["запрос 1", "запрос 2", "запрос 3", "запрос 4", "запрос 5"]"""

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

        # Параллельный поиск по всем запросам (ограничение 2 одновременно)
        sem_search = asyncio.Semaphore(2)

        async def bounded_search(q):
            async with sem_search:
                return await self._search_query(q)

        search_tasks = [bounded_search(q) for q in sub_queries]
        search_results = await asyncio.gather(*search_tasks, return_exceptions=True)
        # Отфильтровываем исключения
        search_results = [res for res in search_results if isinstance(res, list)]

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

        url_to_title = {}
        for res in all_results:
            raw_url = (res.get("url") or "").strip()
            if raw_url:
                url_to_title[raw_url] = (res.get("title") or "").strip()

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

        # Параллельный парсинг всех URL (ограничение 3 одновременно)
        sem_read = asyncio.Semaphore(3)

        async def bounded_read(url):
            async with sem_read:
                return await self._read_url(url, __event_emitter__)

        urls_to_read = [r["url"] for r in all_results]
        read_tasks = [bounded_read(url) for url in urls_to_read]
        read_results = await asyncio.gather(*read_tasks, return_exceptions=True)
        
        # Отфильтровать возможные исключения от asyncio
        read_results = [res for res in read_results if isinstance(res, str)]

        # Объединяем контент с разделителями
        separator = "\n\n" + "═" * 60 + "\n\n"
        combined_content = separator.join(read_results)

        source_lines = []
        source_seen = set()
        for chunk in read_results:
            m = re.match(r"^### Источник: (.+?)\n", chunk)
            if not m:
                continue

            url = m.group(1).strip()
            if "[Не удалось загрузить страницу:" in chunk:
                continue

            try:
                p = urlsplit(url)
                if p.scheme in ("http", "https") and p.netloc:
                    url = urlunsplit((p.scheme, p.netloc, p.path, p.query, p.fragment))
            except Exception:
                pass

            if not url.startswith(("http://", "https://")):
                continue
            if url in source_seen:
                continue
            source_seen.add(url)

            title = url_to_title.get(url, "")
            if title:
                safe_title = title.replace("[", "\\[").replace("]", "\\]")
                source_lines.append(f"- [{safe_title}]({url})")
            else:
                source_lines.append(f"- [{url}]({url})")

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
4. Верни ОДИН цельный отчёт без повторений и альтернативных версий
5. Не добавляй раздел "Источники" (он будет добавлен автоматически)

ФОРМАТ:
## Краткий ответ
[2-3 предложения — суть]

## Подробный анализ
[Основной контент с подзаголовками]

## Ключевые выводы
[Буллеты с главными тезисами]"""

        prompt_synth = f"""ТЕМА ИССЛЕДОВАНИЯ: {topic}

СОБРАННЫЕ МАТЕРИАЛЫ ИЗ ИНТЕРНЕТА:
{combined_content}

Составь ОДИН отчёт по теме, используя эти материалы как источник информации.
Не добавляй раздел 'Источники'."""

        try:
            # Даем строку отступа перед началом текста
            if __event_emitter__:
                await __event_emitter__({
                    "type": "message",
                    "data": {"content": "\n\n"}
                })
            
            logger.info(f"Starting synthesis: {len(combined_content)} chars of context")
                
            final_report = await self._call_llm_streaming(
                prompt_synth,
                sys_synth,
                __event_emitter__,
                timeout=self.valves.llm_timeout
            )
            
            if not final_report or final_report.startswith("Ошибка"):
                logger.error(f"Synthesis returned error or empty: {final_report[:200]}")
                await self.emit_status(
                    __event_emitter__,
                    "❌ Ошибка при генерации отчёта",
                    True
                )
                if __event_emitter__ and final_report:
                    await __event_emitter__({
                        "type": "message",
                        "data": {"content": f"\n\n{final_report}"}
                    })
                return ""

            summary_header_re = re.compile(r"(?im)^\s*#{0,3}\s*Краткий ответ\s*$")
            summary_matches = list(summary_header_re.finditer(final_report))
            if len(summary_matches) >= 2:
                final_report = final_report[:summary_matches[1].start()].rstrip()

            sources_header_re = re.compile(r"(?im)^\s*#{0,3}\s*Источники\s*$")
            m_sources = sources_header_re.search(final_report)
            if m_sources:
                final_report = final_report[:m_sources.start()].rstrip()

            if source_lines and __event_emitter__:
                sources_text = "\n\n## Источники\n" + "\n".join(source_lines)
                await __event_emitter__({
                    "type": "message",
                    "data": {"content": sources_text}
                })
            
            await self.emit_status(
                __event_emitter__,
                "✅ Исследование завершено!",
                True
            )
            # Контент уже застримлен в UI через event_emitter.
            # Возвращаем пустую строку, чтобы OpenWebUI не пытался
            # повторно отобразить/парсить return value.
            return ""

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
