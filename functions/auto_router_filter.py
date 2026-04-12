"""
Auto Router Filter — Automatic Model Selection
================================================
OpenWebUI Filter Function (inlet + outlet) that automatically routes
user requests to the optimal MWS GPT model based on:

Level 1 (instant heuristics):
  - Modality: image → VLM, audio → ASR
  - Keywords: code → kodify-2.0, long docs → cotype-preview-32k
  - Triggers: "нарисуй" → image_gen tool, "найди" → web search

Level 2 (LLM fallback):
  - Uses mws-gpt-alpha for intent classification

Outlet:
  - Injects a routing badge showing which model was used and why

Usage:
  Upload via Admin Panel → Functions → Create new filter function
  Assign to all models in Workspace → Models
"""

import re
from pydantic import BaseModel, Field
from typing import Optional


class Filter:
    class Valves(BaseModel):
        """Configurable parameters visible in OpenWebUI Admin Panel."""
        default_model: str = Field(
            default="mws-gpt-alpha",
            description="Default model for general queries"
        )
        code_model: str = Field(
            default="kodify-2.0",
            description="Model for code-related queries"
        )
        long_context_model: str = Field(
            default="cotype-preview-32k",
            description="Model for long documents (>16k tokens)"
        )

        enable_auto_routing: bool = Field(
            default=True,
            description="Enable automatic model routing"
        )
        show_routing_badge: bool = Field(
            default=True,
            description="Show routing badge in response"
        )
        long_context_threshold: int = Field(
            default=16000,
            description="Character count threshold for long context routing"
        )

    def __init__(self):
        self.valves = self.Valves()
        self._routing_reason = ""
        self._routed_model = ""

        # === Keyword patterns (Russian + English) ===
        self.CODE_PATTERNS = re.compile(
            r"(напиши код|напиши функци|напиши класс|исправь баг|дебагни|debug|"
            r"refactor|рефакторинг|код на python|код на javascript|код на java|"
            r"программ|алгоритм|скрипт|```|def\s+\w|class\s+\w|import\s+\w|"
            r"function\s+\w|const\s+\w|let\s+\w|var\s+\w)",
            re.IGNORECASE
        )

        self.IMAGE_GEN_PATTERNS = re.compile(
            r"(нарисуй|сгенерируй\s*(картинк|изображени|фото)|"
            r"создай\s*(картинк|изображени|иллюстраци)|"
            r"generate\s*(image|picture|photo)|draw\s+)",
            re.IGNORECASE
        )

        self.WEB_SEARCH_PATTERNS = re.compile(
            r"(найди\s+в\s+интернете|загугли|поищи\s+в\s+сети|"
            r"search\s+(the\s+)?web|google\s+|найди\s+информаци)",
            re.IGNORECASE
        )

    def _get_last_user_message(self, messages: list) -> str:
        """Extract the last user message content as string."""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                content = msg.get("content", "")
                if isinstance(content, str):
                    return content
                elif isinstance(content, list):
                    # Handle multimodal messages (text + images)
                    text_parts = []
                    for part in content:
                        if isinstance(part, dict) and part.get("type") == "text":
                            text_parts.append(part.get("text", ""))
                    return " ".join(text_parts)
        return ""

    def _has_images(self, messages: list) -> bool:
        """Check if the last user message contains image attachments."""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                content = msg.get("content", "")
                if isinstance(content, list):
                    for part in content:
                        if isinstance(part, dict) and part.get("type") == "image_url":
                            return True
                # Check for image files in message metadata
                if msg.get("images"):
                    return True
                break
        return False

    def _estimate_context_length(self, messages: list) -> int:
        """Rough estimate of total context length in characters."""
        total = 0
        for msg in messages:
            content = msg.get("content", "")
            if isinstance(content, str):
                total += len(content)
            elif isinstance(content, list):
                for part in content:
                    if isinstance(part, dict) and part.get("type") == "text":
                        total += len(part.get("text", ""))
        return total

    async def inlet(self, body: dict, __user__: dict = None, __event_emitter__=None) -> dict:
        """
        INLET: Intercepts request BEFORE it reaches the LLM.
        Analyzes the user's message and routes to the optimal model.
        """
        if not self.valves.enable_auto_routing:
            return body

        messages = body.get("messages", [])
        if not messages:
            return body

        last_message = self._get_last_user_message(messages)
        original_model = body.get("model", "")

        # === Level 1: Heuristic routing (instant) ===

        # 1. (VLM image routing was removed because Ollama is removed)

        # 2. Code-related keywords → kodify-2.0
        if self.CODE_PATTERNS.search(last_message):
            self._routed_model = self.valves.code_model
            self._routing_reason = "обнаружен код/программирование"
            body["model"] = self._routed_model
            return body

        # 3. Long context → cotype-preview-32k
        context_length = self._estimate_context_length(messages)
        if context_length > self.valves.long_context_threshold:
            self._routed_model = self.valves.long_context_model
            self._routing_reason = f"длинный контекст ({context_length // 1000}k символов)"
            body["model"] = self._routed_model
            return body

        # 4. Default → mws-gpt-alpha
        self._routed_model = self.valves.default_model
        self._routing_reason = "общий запрос"
        body["model"] = self._routed_model
        return body

    async def outlet(self, body: dict, __user__: dict = None, __event_emitter__=None) -> dict:
        """
        OUTLET: Intercepts response AFTER the LLM generates it.
        Injects a routing badge showing which model was used.
        """
        if not self.valves.show_routing_badge or not self._routed_model:
            return body

        messages = body.get("messages", [])
        if not messages:
            return body

        # Find the last assistant message and prepend the badge
        for msg in reversed(messages):
            if msg.get("role") == "assistant":
                content = msg.get("content", "")
                if isinstance(content, str) and content:
                    badge = f"\n\n---\n🤖 *{self._routed_model}* — {self._routing_reason}\n"
                    msg["content"] = content + badge
                break

        # Reset for next request
        self._routing_reason = ""
        self._routed_model = ""

        return body
