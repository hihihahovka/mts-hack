"""
Auto Router Filter — Neural Network Model Selection
===================================================
OpenWebUI Filter Function that automatically routes
user requests to the optimal model strictly using an LLM.

The LLM is prompted to decide the model ID based on the user's
request and standard rules (images, audio, files).

Usage:
  Upload via Admin Panel → Functions → Create new filter function
"""

import json
import logging
import re
from pydantic import BaseModel, Field
from typing import Optional, Any

from fastapi import Request
from open_webui.utils.chat import generate_chat_completion

log = logging.getLogger(__name__)


class Filter:
    class Valves(BaseModel):
        """Configurable parameters visible in OpenWebUI Admin Panel."""

        enable_auto_routing: bool = Field(
            default=True, description="Enable automatic neural network model routing"
        )
        show_routing_badge: bool = Field(
            default=True, description="Show routing badge in response"
        )
        router_model: str = Field(
            default="",
            description="The model to use for routing decisions. Leave blank to use system default TASK_MODEL.",
        )
        research_tool_id: str = Field(
            default="deep_research_tool",
            description="ID инструмента для глубокого поиска",
        )

    def __init__(self):
        self.valves = self.Valves()
        self._routing_reason = "Выбор нейросети-маршрутизатора"
        self._routed_model = ""

    def _get_last_user_message(self, messages: list) -> str:
        for msg in reversed(messages):
            if msg.get("role") == "user":
                content = msg.get("content", "")
                if isinstance(content, str):
                    return content
                elif isinstance(content, list):
                    text_parts = []
                    for part in content:
                        if isinstance(part, dict) and part.get("type") == "text":
                            text_parts.append(part.get("text", ""))
                    return " ".join(text_parts)
        return ""

    def _has_modality(
        self, messages: list, files: list, file_type_keywords: list, file_exts: tuple
    ) -> bool:
        # Check files array
        for file_item in files:
            t = file_item.get("type", "")
            n = file_item.get("name", "").lower()
            if any(k in t for k in file_type_keywords) or n.endswith(file_exts):
                return True
        # Check messages for attachments
        for msg in messages:
            if msg.get("role") == "user":
                if "image" in file_type_keywords and msg.get("images"):
                    return True
                content = msg.get("content", "")
                if isinstance(content, list):
                    for part in content:
                        if (
                            part.get("type") == "image_url"
                            and "image" in file_type_keywords
                        ):
                            return True
                for file_item in msg.get("files", []):
                    if isinstance(file_item, dict):
                        t = file_item.get("type", "")
                        n = file_item.get("name", "").lower()
                        if any(k in t for k in file_type_keywords) or n.endswith(
                            file_exts
                        ):
                            return True
        return False

    async def inlet(
        self, body: dict, __user__: dict = None, __request__: Request = None
    ) -> dict:
        """
        INLET: Analyzes the user's message and routes to the optimal model
        based on the selected tier (Light/Pro) and modalities.
        """
        if not self.valves.enable_auto_routing or __request__ is None:
            return body

        messages = body.get("messages", [])
        if not messages:
            return body

        # Avoid routing internal routing requests (if any)
        if body.get("metadata", {}).get("task") == "MODEL_AUTOROUTING":
            return body

        original_model = body.get("model", "")

        # Читаем режим авторутинга из HTTP-заголовка (X-MTS-Routing-Mode)
        # Этот метод гарантированно доходит до фильтра независимо от Pydantic-валидации
        autorouting_mode = __request__.headers.get("x-mts-routing-mode", "off").lower().strip()
        if autorouting_mode not in ("off", "light", "pro"):
            autorouting_mode = "off"

        log.info(f"[AutoRouter] mode={autorouting_mode}, model={original_model}")

        LIGHT_MODELS = {
            "text": "llama-3.1-8b-instruct",
            "reasoning": "deepseek-r1-distill-qwen-32b",
            "code": "qwen3-coder-480b-a35b",
            "vision": "qwen2.5-vl",
            "image": "image_gen_pipe.qwen-image-lightning",
            "audio": "whisper-turbo-local",
        }

        PRO_MODELS = {
            "text": "glm-4.6-357b",
            "reasoning": "QwQ-32B",
            "code": "qwen3-coder-480b-a35b",
            "vision": "qwen2.5-vl-72b",
            "image": "image_gen_pipe.qwen-image",
            "audio": "whisper-medium",
        }

        model_tier = LIGHT_MODELS if autorouting_mode in ("light", "off") else PRO_MODELS

        last_message = self._get_last_user_message(messages)
        files = body.get("files", [])
        last_message_lower = last_message.lower()

        research_keywords = [
            "исследуй", "найди в интернете", "поиск в интернете", "глубокий поиск", "погугли",
            "search the web", "deep research", "find online", "internet search",
            "сделай рисёрч", "сделай ресерч", "research"
        ]
        
        is_research = any(keyword in last_message_lower for keyword in research_keywords)

        # Если авторутинг выключен, используется только выбранная пользователем модель,
        # за исключением случаев глубокого поиска (когда мы подключаем тул).
        if autorouting_mode == "off" and not is_research:
            self._routing_reason = "Автопереключение выключено"
            return body

        # Ключевые слова для определения интентов (РУ + EN)
        img_keywords = [
            # Русский
            "нарисуй", "сделай картинку", "сгенерируй картинку", "сгенерировать картинку",
            "сгенерируй изображение", "сгенерировать изображение", "изобрази",
            # English
            "draw", "generate image", "generate a picture", "create image",
            "create a picture", "make an image", "make a picture",
            "paint", "render image", "visualize", "illustrate",
        ]
        code_keywords = [
            # Русский
            "скрипт", "закодить", "напиши код", "ошибка в коде", "напиши функцию",
            # Языки программирования (одинаковый код для RU+EN)
            "python", "javascript", "html", "css", "c++", "java ",
            "typescript", "golang", "rust", "kotlin", "swift", "php",
            # English
            "write code", "fix the code", "write a function", "write a script",
            "debug", "refactor", "implement", "coding", "programming",
            "write a class", "write a program",
        ]
        reasoning_keywords = [
            # Русский
            "подумай", "логика", "математика", "реши задачу", "докажи",
            "головоломка", "посчитай", "уравнение", "как решить",
            # English
            "think step by step", "reason", "logic", "mathematics", "math",
            "solve", "prove", "puzzle", "calculate", "equation", "how to solve",
            "step by step", "chain of thought",
        ]

        routed_id = None
        routing_reason = ""

        # Строгая детерминированная логика переключения
        if is_research:
            if "tool_ids" not in body:
                body["tool_ids"] = []
            if getattr(self.valves, "research_tool_id", "deep_research_tool") not in body["tool_ids"]:
                body["tool_ids"].append(getattr(self.valves, "research_tool_id", "deep_research_tool"))
            
            non_text_keywords = ["image", "whisper", "vl", "audio", "vision", "embedding"]
            is_text_model = original_model and not any(k in original_model.lower() for k in non_text_keywords)
            
            if is_text_model:
                routed_id = original_model
                routing_reason = "Запрос на глубокий поиск (Deep Research Tool + Текущая текстовая модель)"
            else:
                routed_id = model_tier["text"]
                routing_reason = "Запрос на глубокий поиск (Deep Research Tool + Смена на текстовую модель)"

        elif autorouting_mode == "off":
            self._routing_reason = "Автопереключение выключено"
            return body

        elif any(keyword in last_message_lower for keyword in img_keywords) and "код" not in last_message_lower:
            routed_id = model_tier["image"]
            routing_reason = "Запрос на генерацию изображения (Image Gen)"
        elif self._has_modality(messages, files, ["image"], (".png", ".jpg", ".jpeg", ".gif", ".webp")):
            routed_id = model_tier["vision"]
            routing_reason = "Прикреплено изображение (Vision LLM)"
        elif self._has_modality(messages, files, ["audio"], (".mp3", ".wav", ".ogg", ".m4a")):
            routed_id = model_tier["audio"]
            routing_reason = "Прикреплено аудио (Распознавание Речи STT)"
        elif any(keyword in last_message_lower for keyword in code_keywords):
            routed_id = model_tier["code"]
            routing_reason = "Запрос на написание кода (Code LLM)"
        elif any(keyword in last_message_lower for keyword in reasoning_keywords):
            routed_id = model_tier["reasoning"]
            routing_reason = "Сложный логический запрос (Reasoning LLM)"
        else:
            routed_id = model_tier["text"]
            routing_reason = "Общий текстовый запрос (General LLM)"

        if "metadata" not in body:
            body["metadata"] = {}
            
        body["metadata"]["_routed_model"] = routed_id
        body["model"] = routed_id
        
        self._routing_reason = f"{routing_reason} • Режим: {autorouting_mode.upper()}"
        return body

    async def outlet(
        self, body: dict, __user__: dict = None, __event_emitter__=None
    ) -> dict:
        """
        OUTLET: Injects a routing badge showing which model was used.
        """
        routed_model = body.get("metadata", {}).get("_routed_model", "")
        if not self.valves.show_routing_badge or not routed_model:
            return body

        messages = body.get("messages", [])
        if not messages:
            return body

        for msg in reversed(messages):
            if msg.get("role") == "assistant":
                content = msg.get("content", "")
                if isinstance(content, str) and content:
                    msg["content"] += f"\n\n---\n🤖 *{routed_model}* — {self._routing_reason}\n"
                    break 
        return body