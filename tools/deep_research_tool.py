"""
Deep Research Tool v2
====================================
OpenWebUI Tool — Multi-step research agent с Map-Reduce pipeline.

Архитектура (вдохновлено GPT Researcher + STORM + Open Deep Research):
┌─────────────────────────────────────────────────────────────────┐
│  ШАГ 1: ДЕКОМПОЗИЦИЯ (Multi-Perspective Query Expansion)       │
│  ─────────────────────────────────────────────────────          │
│  LLM генерирует 5-6 диверсифицированных поисковых запросов      │
│  + дедупликация через n-gram overlap                           │
├─────────────────────────────────────────────────────────────────┤
│  ШАГ 2: ПОИСК (Search Engine API)                               │
│  ─────────────────────────────────                               │
│  SearXNG (meta-search) возвращает топ URL по каждому запросу    │
│  Параллельно, asyncio.gather                                    │
├─────────────────────────────────────────────────────────────────┤
│  ШАГ 3: ПАРСИНГ (Crawling & Filtering)                          │
│  ─────────────────────────────────────                           │
│  Jina Reader API конвертирует HTML → чистый Markdown            │
│  + ContextCompressor: chunk → BM25 → dedup → reorder            │
├─────────────────────────────────────────────────────────────────┤
│  ШАГ 3.5: MAP (Parallel Fact Extraction)                        │
│  ────────────────────────────────────────                        │
│  LLM параллельно извлекает ключевые факты из каждого источника  │
│  Результат: структурированные экстракты вместо сырого текста    │
├─────────────────────────────────────────────────────────────────┤
│  ШАГ 4: REDUCE (Synthesis from MAP extracts)                    │
│  ────────────────────────────────────────────                    │
│  LLM получает чистые экстракты + исходный вопрос                │
│  Синтезирует аналитический отчёт по ТЕМАМ, не по источникам     │
└─────────────────────────────────────────────────────────────────┘
"""

import httpx
import asyncio
import ipaddress
import json
import logging
import os
import re
import socket
from collections import Counter
from typing import List, Dict, Any, Optional
from urllib.parse import urlsplit, urlunsplit, urlparse
from pydantic import BaseModel, Field


# ─── SSRF Protection ───────────────────────────────────────────────
# Блокируем запросы к внутренним/приватным сетям и Docker-сервисам,
# чтобы LLM не могла быть обманута в чтение метаданных облака,
# внутренних БД или других контейнеров в docker-compose сети.
# ────────────────────────────────────────────────────────────────────

BLOCKED_HOSTNAMES = {
    "localhost", "postgres", "searxng", "whisper-api", "open-webui",
    "seed", "portainer", "dozzle", "redis", "mongo", "mysql",
    "metadata.google.internal", "metadata.internal",
}


def is_safe_url(url: str) -> tuple[bool, str]:
    """
    Validates that a URL does not point to internal/private network resources.
    Returns (is_safe, reason) tuple.
    """
    try:
        parsed = urlparse(url)
    except Exception:
        return False, "Invalid URL"

    if parsed.scheme not in ("http", "https"):
        return False, f"Blocked scheme: {parsed.scheme}"

    hostname = (parsed.hostname or "").strip().lower()
    if not hostname:
        return False, "Missing hostname"

    if hostname in BLOCKED_HOSTNAMES:
        return False, f"Blocked internal host: {hostname}"

    try:
        resolved_ips = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
        for family, _, _, _, sockaddr in resolved_ips:
            ip = ipaddress.ip_address(sockaddr[0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                return False, f"Address {ip} is in a private/reserved range"
    except socket.gaierror:
        pass

    return True, ""

# ═══════════════════════════════════════════════════════════════════════════════
# PROMPTS — English versions from research (GPT Researcher / STORM patterns)
# All prompts in English for better LLM performance.
# Output language controlled by "Write in Russian" instruction.
# ═══════════════════════════════════════════════════════════════════════════════

STAGE_1_SYSTEM = """You are a research query strategist. Generate diverse search queries
for comprehensive research on the user's topic.

Each query should target DIFFERENT:
- Aspects (definition, history, current state, challenges, applications)
- Perspectives (academic, industry, policy, user/consumer)
- Specificity levels (overview vs. detailed technical)
- Phrasings (question form, keyword form, phrase form)

RULES:
- Return a JSON array of 5-6 strings
- Keep queries concise (under 8 words each)
- Avoid redundant queries that would return the same results
- Include locations, names, dates if present in the user's question
- Make queries in the SAME LANGUAGE as the user's question

IMPORTANT: Return ONLY a JSON array of strings, no explanations.
Example: ["query 1", "query 2", "query 3", "query 4", "query 5"]"""

STAGE_MAP_SYSTEM = """You are a precise information extractor. Your task is to extract
ONLY relevant information from the given source text.

STRICT RULES:
- Extract ONLY facts supported by the source text
- Do NOT hallucinate or add information from your own knowledge
- If the source contains no relevant information — say so
- Always include numbers, dates, names, and statistics verbatim
- Be concise and specific"""

STAGE_MAP_USER_TEMPLATE = """Extract key findings from this source relevant to: "{query}"

Source URL: {url}
---
{content}
---

Provide:
- MAIN FINDINGS (3-5 bullet points with specifics)
- KEY DATA (numbers, dates, statistics — if available)
- UNIQUE INSIGHTS (what this source adds that others might not)
- RELEVANCE: high / medium / low

If the source contains NO useful information on the topic, respond with
"IRRELEVANT SOURCE" and nothing else."""

STAGE_REDUCE_SYSTEM = """You are an expert research analyst. Write a structured report in Russian.

RULES:
- Organize by THEME, not by source
- Use ONLY facts from the provided sources — do NOT invent data
- Include specific names, numbers, dates from sources
- If sources contradict each other, mention it
- Keep the report concise: MAX 3-5 subsections in "Подробный анализ"
- Do NOT repeat the same information in different sections
- Do NOT add a "Sources" section

STRICT FORMAT (use ## headers exactly as shown):

## Краткий ответ
2-3 sentences summarizing the key finding.

## Подробный анализ
3-5 subsections with ### headers. Each subsection: 2-4 paragraphs with facts.

## Ключевые выводы
3-5 bullet points with specific, actionable takeaways."""

STAGE_REDUCE_USER_TEMPLATE = """Topic: "{topic}"

Source extracts ({n_sources} sources):
{map_extractions}

Write ONE report in Russian. MAX 5 subsections. Do NOT repeat information. No "Sources" section."""

STAGE_4_SYSTEM = STAGE_REDUCE_SYSTEM

STAGE_4_USER_TEMPLATE = """Topic: "{topic}"

Collected materials:
{combined_content}

Write ONE report in Russian. MAX 5 subsections. Do NOT repeat information. No "Sources" section."""

logger = logging.getLogger(__name__)

# Опциональная зависимость: rank-bm25 для контекстной компрессии
try:
    from rank_bm25 import BM25Okapi
    HAS_BM25 = True
except ImportError:
    HAS_BM25 = False
    logger.info("rank-bm25 not installed — context compression will use fallback mode")


# ═══════════════════════════════════════════════════════════════════════════════
# CONTEXT COMPRESSOR
# ═══════════════════════════════════════════════════════════════════════════════
# Контекстная фильтрация: chunk → BM25 pre-filter → dedup → reorder
# Убирает мусор (навигация, реклама, нерелевант) без GPU и embeddings.


class ContextCompressor:
    """Фильтрует и ранжирует контент для LLM-синтеза.
    
    Pipeline:
    1. Chunk: разбиваем текст на куски по 800 символов
    2. BM25 pre-filter: оставляем только top-N по релевантности к запросу
    3. Dedup: убираем near-duplicates через n-gram overlap
    4. Reorder: лучшие чанки в начало и конец (lost-in-the-middle fix)
    """

    def __init__(
        self,
        chunk_size: int = 800,
        chunk_overlap: int = 150,
        bm25_top_n: int = 30,
        dedup_threshold: float = 0.6,
        top_k: int = 15,
    ):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.bm25_top_n = bm25_top_n
        self.dedup_threshold = dedup_threshold
        self.top_k = top_k

    def _chunk_text(self, text: str) -> List[str]:
        """Разбивает текст на чанки с overlap, по markdown-aware разделителям."""
        separators = ["\n## ", "\n### ", "\n\n", "\n", ". ", " "]
        chunks = []
        
        # Простое chunking с overlap
        start = 0
        while start < len(text):
            end = start + self.chunk_size
            if end >= len(text):
                chunk = text[start:]
                if chunk.strip():
                    chunks.append(chunk.strip())
                break
            
            # Ищем лучшую точку разрыва
            best_break = end
            for sep in separators:
                idx = text.rfind(sep, start + self.chunk_size // 2, end)
                if idx > start:
                    best_break = idx + len(sep)
                    break
            
            chunk = text[start:best_break].strip()
            if chunk:
                chunks.append(chunk)
            start = best_break - self.chunk_overlap
        
        return chunks

    def _ngram_set(self, text: str, n: int = 3) -> set:
        """Создаёт множество char n-grams для fuzzy сравнения."""
        text = text.lower()
        return {text[i:i+n] for i in range(len(text) - n + 1)} if len(text) >= n else {text}

    def _similarity(self, text_a: str, text_b: str) -> float:
        """Jaccard similarity на основе char n-grams."""
        set_a = self._ngram_set(text_a)
        set_b = self._ngram_set(text_b)
        if not set_a or not set_b:
            return 0.0
        return len(set_a & set_b) / len(set_a | set_b)

    def _dedup(self, chunks: List[str]) -> List[str]:
        """Убирает near-duplicate чанки через n-gram Jaccard similarity."""
        if len(chunks) <= 1:
            return chunks
        
        kept = []
        for chunk in chunks:
            is_dup = False
            for existing in kept:
                if self._similarity(chunk, existing) >= self.dedup_threshold:
                    is_dup = True
                    break
            if not is_dup:
                kept.append(chunk)
        return kept

    def _reorder_lost_in_middle(self, chunks: List[str]) -> List[str]:
        """Размещает лучшие чанки в начало и конец (для LLM attention)."""
        if len(chunks) <= 2:
            return chunks
        reordered = []
        for i, chunk in enumerate(chunks):
            if i % 2 == 0:
                reordered.insert(0, chunk)
            else:
                reordered.append(chunk)
        return reordered

    def process(self, query: str, raw_texts: List[str]) -> List[str]:
        """Полный pipeline: chunk → BM25 → dedup → reorder.
        
        Args:
            query: Исходный запрос пользователя
            raw_texts: Список текстов источников
            
        Returns:
            Отфильтрованные и ранжированные чанки
        """
        # 1. Chunk all texts
        all_chunks = []
        for text in raw_texts:
            all_chunks.extend(self._chunk_text(text))
        
        if not all_chunks:
            return raw_texts  # fallback
        
        # 2. BM25 pre-filter (если есть rank-bm25)
        if HAS_BM25 and len(all_chunks) > self.bm25_top_n:
            tokenized = [c.lower().split() for c in all_chunks]
            bm25 = BM25Okapi(tokenized)
            scores = bm25.get_scores(query.lower().split())
            top_indices = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
            all_chunks = [all_chunks[i] for i in top_indices[:self.bm25_top_n]]
        
        # 3. Dedup
        all_chunks = self._dedup(all_chunks)
        
        # 4. Top-K
        all_chunks = all_chunks[:self.top_k]
        
        # 5. Reorder (lost-in-the-middle)
        all_chunks = self._reorder_lost_in_middle(all_chunks)
        
        return all_chunks


# ═══════════════════════════════════════════════════════════════════════════════
# QUERY DEDUPLICATION
# ═══════════════════════════════════════════════════════════════════════════════


def deduplicate_queries(queries: List[str], threshold: float = 0.7) -> List[str]:
    """Убирает семантически похожие запросы через n-gram Jaccard similarity."""
    if len(queries) <= 1:
        return queries
    
    compressor = ContextCompressor()
    kept = []
    for q in queries:
        is_dup = False
        for existing in kept:
            if compressor._similarity(q, existing) >= threshold:
                is_dup = True
                break
        if not is_dup:
            kept.append(q)
    return kept


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN TOOL CLASS
# ═══════════════════════════════════════════════════════════════════════════════


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
        enable_map_reduce: bool = Field(
            default=True,
            description="Enable Map-Reduce pipeline (disable for monolithic fallback)"
        )
        enable_context_compression: bool = Field(
            default=True,
            description="Enable BM25-based context compression"
        )
        map_max_tokens: int = Field(
            default=800,
            description="Max tokens for MAP extraction per source"
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

    async def _call_llm(self, prompt: str, system: str, timeout: int = 60, max_tokens: int = None) -> str:
        """
        Вызов LLM через OpenAI-совместимый API.

        Args:
            prompt: Пользовательский промпт
            system: Системный промпт (роль модели)
            timeout: Таймаут в секундах
            max_tokens: Максимальное количество токенов (если None — не ограничиваем)
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
            "temperature": 0.1,
        }

        if max_tokens is not None:
            payload["max_tokens"] = max_tokens

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

    async def _call_llm_streaming(
        self, prompt: str, system: str, __event_emitter__,
        timeout: int = 180,
        stop_on_duplicate_header: str = None,
        stop_on_headers: list = None,
    ) -> str:
        """Стриминговый вызов LLM с реалтайм-фильтрами.
        
        Args:
            stop_on_duplicate_header: Заголовок, при ВТОРОМ появлении которого стрим обрывается.
                                     Пример: "## Краткий ответ"
            stop_on_headers: Список заголовков, при ПЕРВОМ появлении которых стрим обрывается.
                             Пример: ["## Источники", "## Sources"]
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
            "stream": True,
            "temperature": 0.3,
        }
        
        stream_timeout = httpx.Timeout(
            connect=15.0,
            read=max(30.0, float(timeout)),
            write=30.0,
            pool=15.0
        )

        full_text = ""
        chunk_count = 0
        ui_buffer = ""
        stopped_early = False

        # --- Helpers for stop detection ---
        dup_header_count = 0
        stop_on_headers = stop_on_headers or []

        def _find_header(text: str, header_text: str) -> list:
            """Find ALL positions of a header in any format: ## Header, **Header**, ### Header, etc."""
            positions = []
            # Regex: line start + optional whitespace + (## or ### or **) + header text
            pattern = re.compile(
                r'(?:^|\n)\s*(?:#{1,4}\s+|(?:\*\*))' + re.escape(header_text),
                re.IGNORECASE
            )
            for m in pattern.finditer(text):
                positions.append(m.start())
            return positions

        def _check_stop(text: str) -> int:
            """Returns the trim position if we should stop, or -1 to continue."""
            
            # Check duplicate header (e.g. second "Краткий ответ" in any format)
            if stop_on_duplicate_header:
                header_text = stop_on_duplicate_header.lstrip('#').lstrip('*').strip()
                positions = _find_header(text, header_text)
                if len(positions) >= 2:
                    return max(0, positions[1])
            
            # Check stop headers (e.g. "Источники" in any format)
            for header in stop_on_headers:
                header_text = header.lstrip('#').lstrip('*').strip()
                positions = _find_header(text, header_text)
                if positions:
                    return max(0, positions[0])
            
            # LOOP DETECTION: if model generates too many ### subsections, stop
            subsection_count = len(re.findall(r'(?:^|\n)\s*###\s+', text))
            if subsection_count > 7:
                # Find the 7th ### and trim there
                matches = list(re.finditer(r'(?:^|\n)\s*###\s+', text))
                if len(matches) > 7:
                    logger.warning(f"Loop detected: {subsection_count} subsections, trimming at 7th")
                    return max(0, matches[7].start())
            
            return -1

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
                                if stopped_early:
                                    break
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

                                        # --- Real-time stop check ---
                                        trim_pos = _check_stop(full_text)
                                        if trim_pos >= 0:
                                            # Trim everything after the stop point
                                            overflow = len(full_text) - trim_pos
                                            full_text = full_text[:trim_pos].rstrip()
                                            # Trim UI buffer too
                                            if overflow > 0 and len(ui_buffer) >= overflow:
                                                ui_buffer = ui_buffer[:-overflow].rstrip()
                                            elif overflow > 0:
                                                ui_buffer = ""
                                            stopped_early = True
                                            logger.info(f"Stream stopped early at pos {trim_pos} (total {chunk_count} chunks)")
                                            break

                                        # Батчим отправку
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
        
        logger.info(f"Streaming complete: {chunk_count} chunks, {len(full_text)} chars, stopped_early={stopped_early}")
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
        Включает SSRF-проверку перед любыми HTTP-запросами.
        """
        # ── SSRF Guard ──
        safe, reason = is_safe_url(url)
        if not safe:
            logger.warning(f"SSRF blocked: {url} — {reason}")
            return f"### Источник: {url}\n\n[🛡️ Запрос заблокирован (SSRF): {reason}]"

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

    # ═══════════════════════════════════════════════════════════════
    # MAP PHASE: параллельная экстракция фактов
    # ═══════════════════════════════════════════════════════════════

    async def _map_extract(self, source_url: str, source_content: str, query: str) -> Optional[str]:
        """Извлекает ключевые факты из одного источника (MAP-фаза).
        
        Args:
            source_url: URL источника
            source_content: Текст источника
            query: Исходный запрос пользователя
            
        Returns:
            Структурированные факты или None если источник нерелевантен
        """
        # Ограничиваем контент для MAP (4000 символов — ~1000 токенов)
        content_for_map = source_content[:4000]
        
        prompt = STAGE_MAP_USER_TEMPLATE.format(
            query=query,
            url=source_url,
            content=content_for_map
        )
        
        try:
            extraction = await self._call_llm(
                prompt,
                STAGE_MAP_SYSTEM,
                timeout=45,
                max_tokens=self.valves.map_max_tokens,
            )
            
            # Если модель определила как нерелевантный — пропускаем
            if "IRRELEVANT SOURCE" in extraction.upper():
                logger.info(f"MAP: irrelevant source skipped: {source_url}")
                return None
            
            return f"### Источник: {source_url}\n{extraction}"
        except Exception as e:
            logger.error(f"MAP extraction failed for {source_url}: {e}")
            return None

    # ═══════════════════════════════════════════════════════════════
    # MAIN PIPELINE
    # ═══════════════════════════════════════════════════════════════

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
        # ШАГ 1: ДЕКОМПОЗИЦИЯ ЗАПРОСА (Multi-Perspective Query Expansion)
        # ═══════════════════════════════════════════════════════════

        await self.emit_status(
            __event_emitter__,
            "🧠 Шаг 1/4: Анализирую тему и составляю план поиска...",
            False
        )

        try:
            json_str = await self._call_llm(topic, STAGE_1_SYSTEM, timeout=30)
            # Извлекаем JSON из ответа (LLM может добавить markdown)
            match = re.search(r'\[.*?\]', json_str.replace('\n', ' '), re.DOTALL)
            if match:
                sub_queries = json.loads(match.group(0))
                # Валидация
                if not isinstance(sub_queries, list) or len(sub_queries) == 0:
                    sub_queries = [topic]
                # Фильтруем нестроковые элементы
                sub_queries = [q for q in sub_queries if isinstance(q, str) and q.strip()]
                if not sub_queries:
                    sub_queries = [topic]
            else:
                sub_queries = [topic]
        except Exception as e:
            logger.error(f"Query decomposition failed: {e}")
            sub_queries = [topic]

        # Дедупликация запросов через n-gram similarity
        sub_queries = deduplicate_queries(sub_queries, threshold=0.7)

        # Показываем план пользователю
        queries_preview = "\n".join([f"  • {q}" for q in sub_queries[:6]])
        await self.emit_status(
            __event_emitter__,
            f"📋 План поиска:\n{queries_preview}",
            False
        )

        # ═══════════════════════════════════════════════════════════
        # ШАГ 2: ПОИСК (Search Engine API)
        # ═══════════════════════════════════════════════════════════

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

        # --- Сбор source_lines для секции "Источники" ---
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
                # Убираем квадратные скобки из title (бывает [D], [PDF] и т.п.)
                safe_title = re.sub(r'\[.*?\]\s*', '', title).strip()
                if safe_title:
                    source_lines.append(f"- [{safe_title}]({url})")
                else:
                    source_lines.append(f"- [{url}]({url})")
            else:
                source_lines.append(f"- [{url}]({url})")

        # ═══════════════════════════════════════════════════════════
        # КОНТЕКСТНАЯ КОМПРЕССИЯ (если включена)
        # ═══════════════════════════════════════════════════════════

        if self.valves.enable_context_compression:
            await self.emit_status(
                __event_emitter__,
                "🗜️ Фильтрую и ранжирую собранные данные...",
                False
            )

            # Извлекаем чистый текст (без заголовков "### Источник:")
            raw_texts = []
            for chunk in read_results:
                # Убираем заголовок источника
                lines = chunk.split("\n", 2)
                if len(lines) > 2:
                    raw_texts.append(lines[2])
                else:
                    raw_texts.append(chunk)
            
            compressor = ContextCompressor()
            compressed_chunks = compressor.process(topic, raw_texts)
            
            logger.info(
                f"Context compression: {sum(len(t) for t in raw_texts)} chars → "
                f"{sum(len(c) for c in compressed_chunks)} chars "
                f"({len(compressed_chunks)} chunks)"
            )
        
        # ═══════════════════════════════════════════════════════════
        # ШАГ 3.5 / 4: MAP-REDUCE или МОНОЛИТНЫЙ СИНТЕЗ
        # ═══════════════════════════════════════════════════════════

        if self.valves.enable_map_reduce:
            # ─── MAP-REDUCE PIPELINE ───
            
            await self.emit_status(
                __event_emitter__,
                f"🔬 Шаг 3.5/4: Извлекаю ключевые факты из {len(read_results)} источников...",
                False
            )

            # MAP: параллельная экстракция фактов
            sem_map = asyncio.Semaphore(5)

            async def bounded_map(chunk):
                async with sem_map:
                    # Извлекаем URL и контент из chunk
                    m = re.match(r"^### Источник: (.+?)\n", chunk)
                    url = m.group(1).strip() if m else "unknown"
                    lines = chunk.split("\n", 2)
                    content = lines[2] if len(lines) > 2 else chunk
                    
                    # Пропускаем неудачные загрузки
                    if "[Не удалось загрузить страницу:" in chunk:
                        return None
                    
                    return await self._map_extract(url, content, topic)

            map_tasks = [bounded_map(chunk) for chunk in read_results]
            map_results = await asyncio.gather(*map_tasks, return_exceptions=True)
            
            # Фильтруем: убираем None (нерелевантные) и исключения
            map_extractions = [
                r for r in map_results
                if isinstance(r, str) and r is not None
            ]
            
            n_relevant = len(map_extractions)
            n_total = len(read_results)
            
            await self.emit_status(
                __event_emitter__,
                f"📊 Извлечено фактов из {n_relevant}/{n_total} источников",
                False
            )

            if not map_extractions:
                # Fallback на монолитный если MAP ничего не дал
                logger.warning("MAP phase produced no results — falling back to monolithic")
                combined_content = "\n\n".join(read_results)
                if len(combined_content) > self.valves.max_total_content:
                    combined_content = combined_content[:self.valves.max_total_content]
                
                sys_synth = STAGE_4_SYSTEM
                prompt_synth = STAGE_4_USER_TEMPLATE.format(
                    topic=topic,
                    combined_content=combined_content
                )
            else:
                # REDUCE: синтез из MAP-экстрактов
                separator = "\n\n" + "─" * 40 + "\n\n"
                map_combined = separator.join(map_extractions)
                
                # Обрезка если нужно
                if len(map_combined) > self.valves.max_total_content:
                    map_combined = map_combined[:self.valves.max_total_content]
                    map_combined += "\n\n...[часть экстрактов опущена]"
                
                sys_synth = STAGE_REDUCE_SYSTEM
                prompt_synth = STAGE_REDUCE_USER_TEMPLATE.format(
                    topic=topic,
                    n_sources=n_relevant,
                    map_extractions=map_combined
                )
        else:
            # ─── МОНОЛИТНЫЙ FALLBACK (старый режим) ───
            
            if self.valves.enable_context_compression:
                separator = "\n\n" + "═" * 60 + "\n\n"
                combined_content = separator.join(compressed_chunks)
            else:
                separator = "\n\n" + "═" * 60 + "\n\n"
                combined_content = separator.join(read_results)
            
            if len(combined_content) > self.valves.max_total_content:
                combined_content = combined_content[:self.valves.max_total_content]
                combined_content += "\n\n...[часть материалов опущена из-за ограничений]"
            
            sys_synth = STAGE_4_SYSTEM
            prompt_synth = STAGE_4_USER_TEMPLATE.format(
                topic=topic,
                combined_content=combined_content
            )

        # ═══════════════════════════════════════════════════════════
        # ШАГ 4: ФИНАЛЬНЫЙ СИНТЕЗ (Streaming)
        # ═══════════════════════════════════════════════════════════

        await self.emit_status(
            __event_emitter__,
            "📝 Шаг 4/4: Синтезирую финальный отчёт...",
            False
        )

        try:
            # Даем строку отступа перед началом текста
            if __event_emitter__:
                await __event_emitter__({
                    "type": "message",
                    "data": {"content": "\n\n"}
                })
            
            logger.info(f"Starting synthesis: {len(prompt_synth)} chars of prompt")
                
            final_report = await self._call_llm_streaming(
                prompt_synth,
                sys_synth,
                __event_emitter__,
                timeout=self.valves.llm_timeout,
                stop_on_duplicate_header="## Краткий ответ",
                stop_on_headers=["## Источники", "## Sources", "## References"],
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

            # --- Post-processing: убираем дубликаты и секции "Источники" ---
            summary_header_re = re.compile(r"(?im)^\s*#{0,3}\s*Краткий ответ\s*$")
            summary_matches = list(summary_header_re.finditer(final_report))
            if len(summary_matches) >= 2:
                final_report = final_report[:summary_matches[1].start()].rstrip()

            sources_header_re = re.compile(r"(?im)^\s*#{0,3}\s*Источники\s*$")
            m_sources = sources_header_re.search(final_report)
            if m_sources:
                final_report = final_report[:m_sources.start()].rstrip()

            if source_lines and __event_emitter__:
                links_md = "\n".join(source_lines)
                sources_text = "\n\n## Источники\n" + links_md + "\n"
                await __event_emitter__({
                    "type": "message",
                    "data": {"content": sources_text}
                })

            await self.emit_status(
                __event_emitter__,
                "✅ Исследование завершено!",
                True
            )

            # Заменяем финальный ответ модели пустой строкой,
            # чтобы thinking-модель не добавляла рассуждения после источников.
            if __event_emitter__:
                await __event_emitter__({
                    "type": "replace",
                    "data": {"content": ""}
                })

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

{combined_content[:10000] if 'combined_content' in dir() else 'Данные недоступны'}"""
