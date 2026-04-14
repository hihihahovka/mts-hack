"""
Web Scraper Tool — Jina Reader API
====================================
OpenWebUI Tool that parses web pages and returns clean markdown content
using the free Jina Reader API (r.jina.ai).

The LLM calls scrape_url(url) when the user provides a URL or asks
to "прочитай эту страницу", "проанализируй ссылку", etc.
"""

import ipaddress
import socket
import urllib.parse
from pydantic import BaseModel, Field


# ─── SSRF Protection ───────────────────────────────────────────────
# Блокируем запросы к внутренним/приватным сетям и Docker-сервисам,
# чтобы LLM не могла быть обманута в чтение метаданных облака,
# внутренних БД или других контейнеров в docker-compose сети.
# ────────────────────────────────────────────────────────────────────

# Docker-compose service names and common internal hostnames
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
        parsed = urllib.parse.urlparse(url)
    except Exception:
        return False, "Невалидный URL"

    # Must be http or https
    if parsed.scheme not in ("http", "https"):
        return False, f"Недопустимая схема: {parsed.scheme}"

    hostname = (parsed.hostname or "").strip().lower()

    if not hostname:
        return False, "Отсутствует hostname"

    # Block known internal hostnames
    if hostname in BLOCKED_HOSTNAMES:
        return False, f"Заблокированный внутренний хост: {hostname}"

    # Resolve hostname to IP and check against private ranges
    try:
        resolved_ips = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
        for family, _, _, _, sockaddr in resolved_ips:
            ip = ipaddress.ip_address(sockaddr[0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                return False, f"Адрес {ip} принадлежит приватной/зарезервированной сети"
    except socket.gaierror:
        # Cannot resolve — allow (Jina Reader will handle the error)
        pass

    return True, ""


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

        # ── SSRF Guard ──
        safe, reason = is_safe_url(url)
        if not safe:
            error_msg = f"🛡️ Запрос заблокирован (SSRF): {reason}"
            if __event_emitter__:
                await __event_emitter__(
                    {"type": "status", "data": {"description": f"❌ {error_msg}", "done": True}}
                )
            return error_msg

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
