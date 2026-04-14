"""
Image Generation Pipe — qwen-image as a selectable model
==========================================================
OpenWebUI Pipe Function that registers qwen-image and qwen-image-lightning
as selectable models in the model dropdown.

When the user selects one of these models and sends a message,
the pipe intercepts the request and calls the MWS GPT image generation
API (/v1/images/generations) instead of chat completions.

Usage:
  Appears as "🖼️ qwen-image" and "⚡ qwen-image-lightning" in the model selector.
  Just type what you want to draw and send — the pipe handles the rest.
"""

import os
import logging
import asyncio
import base64
import httpx
from typing import Union, Generator, Iterator
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class Pipe:
    class Valves(BaseModel):
        """Configurable parameters visible in OpenWebUI Admin Panel."""
        api_base_url: str = Field(
            default="https://api.gpt.mws.ru/v1",
            description="MWS GPT API base URL"
        )
        api_key: str = Field(
            default="",
            description="MWS API Key. If empty, falls back to MWS_API_KEY or OPENAI_API_KEY env var."
        )
        default_size: str = Field(
            default="1024x1024",
            description="Default image size (e.g. 1024x1024, 512x512)"
        )
        request_timeout: int = Field(
            default=120,
            description="Timeout in seconds for image generation request"
        )

    def __init__(self):
        self.valves = self.Valves()

    def _get_api_key(self) -> str:
        """Get API key from valves or environment."""
        if self.valves.api_key:
            return self.valves.api_key
        return os.environ.get("MWS_API_KEY") or os.environ.get("OPENAI_API_KEY", "")

    def pipes(self) -> list[dict]:
        """
        Register available image generation models.
        These will appear in the model selector dropdown.
        """
        return [
            {"id": "qwen-image", "name": "🖼️ qwen-image"},
            {"id": "qwen-image-lightning", "name": "⚡ qwen-image-lightning"},
        ]

    async def pipe(
        self,
        body: dict,
        __event_emitter__=None,
    ) -> str:
        """
        Handle incoming chat request by generating an image.
        Extracts the last user message as the prompt and calls the image API.
        """
        # Skip background tasks — OpenWebUI sends title_generation, tags_generation,
        # emoji_generation, etc. to the same model. Without this check, each task
        # would trigger a separate image generation API call.
        BACKGROUND_TASKS = {
            "title_generation", "tags_generation", "emoji_generation",
            "follow_up_generation", "query_generation",
            "autocomplete_generation", "image_prompt_generation",
            "moa_response_generation", "function_calling",
        }
        task = body.get("metadata", {}).get("task", "")
        if task in BACKGROUND_TASKS:
            return ""
        # Determine which model was selected
        model_id = body.get("model", "")
        # OpenWebUI prefixes pipe model IDs with the function id
        # e.g. "image_gen_pipe.qwen-image" → extract "qwen-image"
        if "." in model_id:
            model_id = model_id.split(".", 1)[1]

        # If model_id is still not one of ours, default
        if model_id not in ("qwen-image", "qwen-image-lightning"):
            model_id = "qwen-image"

        # Extract the last user message as the image prompt
        messages = body.get("messages", [])
        prompt = ""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                content = msg.get("content", "")
                if isinstance(content, str):
                    prompt = content.strip()
                elif isinstance(content, list):
                    # Multimodal: extract text parts
                    text_parts = []
                    for part in content:
                        if isinstance(part, dict) and part.get("type") == "text":
                            text_parts.append(part.get("text", ""))
                    prompt = " ".join(text_parts).strip()
                break

        if not prompt:
            return "❌ Пожалуйста, опишите что нужно нарисовать."

        api_key = self._get_api_key()
        if not api_key:
            return "❌ API ключ не настроен. Укажите MWS_API_KEY в переменных окружения или в настройках Pipe."

        # Emit status
        if __event_emitter__:
            await __event_emitter__({
                "type": "status",
                "data": {"description": f"🎨 Генерирую изображение ({model_id})...", "done": False}
            })

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": model_id,
            "prompt": prompt,
            "n": 1,
            "size": self.valves.default_size,
        }

        try:
            async with httpx.AsyncClient(timeout=self.valves.request_timeout) as client:
                response = await client.post(
                    f"{self.valves.api_base_url}/images/generations",
                    headers=headers,
                    json=payload,
                )

            if response.status_code != 200:
                error_text = response.text[:500]
                logger.error(f"[ImagePipe] API error {response.status_code}: {error_text}")
                if __event_emitter__:
                    await __event_emitter__({
                        "type": "status",
                        "data": {"description": f"❌ Ошибка API: {response.status_code}", "done": True}
                    })
                return f"❌ Ошибка генерации: HTTP {response.status_code}\n\n```\n{error_text}\n```"

            result = response.json()
            data = result.get("data", [])

            if not data:
                if __event_emitter__:
                    await __event_emitter__({
                        "type": "status",
                        "data": {"description": "❌ API не вернул изображений", "done": True}
                    })
                return "❌ API не вернул изображений. Попробуйте другой промпт."

            image_url = data[0].get("url", "")
            revised_prompt = data[0].get("revised_prompt", prompt)

            if not image_url:
                if __event_emitter__:
                    await __event_emitter__({
                        "type": "status",
                        "data": {"description": "❌ Нет URL в ответе", "done": True}
                    })
                return "❌ API не вернул URL изображения."

            if __event_emitter__:
                await __event_emitter__({
                    "type": "status",
                    "data": {"description": "⬇️ Загружаю изображение...", "done": False}
                })

            # Download the image and convert to base64 data URI.
            # MWS API returns temporary URLs that expire quickly —
            # without this conversion, images appear as broken links.
            display_url = None
            max_retries = 3
            for attempt in range(1, max_retries + 1):
                try:
                    timeout = 30 * attempt  # 30s, 60s, 90s
                    async with httpx.AsyncClient(timeout=timeout) as dl_client:
                        img_response = await dl_client.get(image_url)
                        img_response.raise_for_status()
                        b64_data = base64.b64encode(img_response.content).decode("utf-8")
                        content_type = img_response.headers.get("content-type", "image/png")
                        display_url = f"data:{content_type};base64,{b64_data}"
                        break
                except Exception as e:
                    logger.warning(f"[ImagePipe] Download attempt {attempt}/{max_retries} failed: {e}")
                    if attempt < max_retries:
                        await asyncio.sleep(2 * attempt)

            if not display_url:
                logger.error(f"[ImagePipe] All {max_retries} download attempts failed for {image_url}")
                if __event_emitter__:
                    await __event_emitter__({
                        "type": "status",
                        "data": {"description": "❌ Не удалось загрузить изображение", "done": True}
                    })
                return "❌ Изображение было сгенерировано, но не удалось загрузить для отображения. Попробуйте ещё раз."

            if __event_emitter__:
                await __event_emitter__({
                    "type": "status",
                    "data": {"description": "✅ Изображение сгенерировано!", "done": True}
                })

            return f"![{revised_prompt}]({display_url})\n\n*Модель: **{model_id}** | Запрос: \"{prompt}\"*"

        except httpx.TimeoutException:
            logger.error("[ImagePipe] Request timed out")
            if __event_emitter__:
                await __event_emitter__({
                    "type": "status",
                    "data": {"description": "❌ Таймаут", "done": True}
                })
            return "❌ Таймаут при генерации. Попробуйте ещё раз или используйте более короткий промпт."

        except Exception as e:
            logger.error(f"[ImagePipe] Error: {type(e).__name__}: {e}")
            if __event_emitter__:
                await __event_emitter__({
                    "type": "status",
                    "data": {"description": f"❌ Ошибка: {e}", "done": True}
                })
            return f"❌ Ошибка: {type(e).__name__}: {str(e)[:300]}"
