"""
Web Scraper Tool — Jina Reader API
====================================
OpenWebUI Tool that parses web pages and returns clean markdown content
using the free Jina Reader API (r.jina.ai).

The LLM calls scrape_url(url) when the user provides a URL or asks
to "прочитай эту страницу", "проанализируй ссылку", etc.
"""

import urllib.parse
from pydantic import BaseModel, Field


class Tools:
    class Valves(BaseModel):
        """Configurable parameters."""
        jina_base_url: str = Field(
            default="https://r.jina.ai",
            description="Jina Reader API base URL"
        )
        max_content_length: int = Field(
            default=15000,
            description="Maximum content length in characters to return"
        )

    def __init__(self):
        self.valves = self.Valves()

    async def scrape_url(
        self,
        url: str,
        __event_emitter__=None,
    ) -> str:
        """
        Scrapes a web page and returns its content as clean markdown.

        :param url: The URL of the web page to scrape.
        :return: Markdown content of the web page.
        """
        import httpx

        if __event_emitter__:
            await __event_emitter__(
                {"type": "status", "data": {"description": f"🌐 Загружаю {url}...", "done": False}}
            )

        try:
            # Use Jina Reader API — prefix URL to get clean markdown
            jina_url = f"{self.valves.jina_base_url}/{url}"
            async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
                response = await client.get(
                    jina_url,
                    headers={
                        "Accept": "text/markdown",
                        "X-Return-Format": "markdown",
                    }
                )
                response.raise_for_status()
                content = response.text

            # Truncate if too long
            if len(content) > self.valves.max_content_length:
                content = content[:self.valves.max_content_length] + "\n\n...[контент обрезан]"

            if __event_emitter__:
                await __event_emitter__(
                    {"type": "status", "data": {"description": "✅ Страница загружена!", "done": True}}
                )

            return f"# Содержимое: {url}\n\n{content}"

        except httpx.HTTPStatusError as e:
            error_msg = f"Ошибка загрузки {url}: HTTP {e.response.status_code}"
            if __event_emitter__:
                await __event_emitter__(
                    {"type": "status", "data": {"description": f"❌ {error_msg}", "done": True}}
                )
            return error_msg

        except Exception as e:
            error_msg = f"Ошибка при парсинге {url}: {str(e)}"
            if __event_emitter__:
                await __event_emitter__(
                    {"type": "status", "data": {"description": f"❌ {error_msg}", "done": True}}
                )
            return error_msg
