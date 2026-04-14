"""
Image Generation Tool — MWS GPT API (qwen-image)
===================================================
OpenWebUI Tool that generates images via MWS GPT image generation API.
Uses the qwen-image or qwen-image-lightning model through the
OpenAI-compatible /v1/images/generations endpoint.

The LLM calls generate_image(prompt) when the user asks to
"нарисуй", "сгенерируй картинку", "create an image", etc.
"""

import os
import logging
import httpx
import base64
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class Tools:
    class Valves(BaseModel):
        """Configurable parameters."""
        api_base_url: str = Field(
            default="https://api.gpt.mws.ru/v1",
            description="MWS GPT API base URL"
        )
        api_key: str = Field(
            default="",
            description="MWS API Key. If empty, falls back to MWS_API_KEY or OPENAI_API_KEY env var."
        )
        model: str = Field(
            default="qwen-image",
            description="Image generation model (qwen-image or qwen-image-lightning)"
        )
        default_size: str = Field(
            default="1024x1024",
            description="Default image size (e.g. 1024x1024, 512x512)"
        )

    def __init__(self):
        self.valves = self.Valves()

    def _get_api_key(self) -> str:
        """Get API key from valves or environment."""
        if self.valves.api_key:
            return self.valves.api_key
        return os.environ.get("MWS_API_KEY") or os.environ.get("OPENAI_API_KEY", "")

    async def generate_image(
        self,
        prompt: str,
        size: str = "",
        __event_emitter__=None,
    ) -> str:
        """
        Generates an image from a text description using MWS GPT API.

        :param prompt: Text description of the image to generate (in English for best results).
        :param size: Image size, e.g. "1024x1024" or "512x512". Leave empty for default.
        :return: Markdown with the generated image.
        """
        api_key = self._get_api_key()
        if not api_key:
            return "❌ Ошибка: API ключ не настроен. Укажите MWS_API_KEY в переменных окружения или в настройках инструмента."

        image_size = size if size else self.valves.default_size

        if __event_emitter__:
            await __event_emitter__(
                {"type": "status", "data": {"description": f"🎨 Генерирую изображение ({self.valves.model})...", "done": False}}
            )

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": self.valves.model,
            "prompt": prompt,
            "n": 1,
            "size": image_size,
        }

        try:
            async with httpx.AsyncClient(timeout=120) as client:
                response = await client.post(
                    f"{self.valves.api_base_url}/images/generations",
                    headers=headers,
                    json=payload,
                )

            if response.status_code != 200:
                error_text = response.text[:300]
                logger.error(f"[ImageGen] API error {response.status_code}: {error_text}")
                if __event_emitter__:
                    await __event_emitter__(
                        {"type": "status", "data": {"description": f"❌ Ошибка API: {response.status_code}", "done": True}}
                    )
                return f"❌ Ошибка генерации изображения: HTTP {response.status_code}\n\n```\n{error_text}\n```"

            result = response.json()
            data = result.get("data", [])

            if not data:
                if __event_emitter__:
                    await __event_emitter__(
                        {"type": "status", "data": {"description": "❌ API не вернул изображений", "done": True}}
                    )
                return "❌ API не вернул изображений. Попробуйте другой промпт."

            image_url = data[0].get("url", "")
            revised_prompt = data[0].get("revised_prompt", prompt)

            if not image_url:
                if __event_emitter__:
                    await __event_emitter__(
                        {"type": "status", "data": {"description": "❌ Нет URL изображения в ответе", "done": True}}
                    )
                return "❌ API вернул пустой URL изображения. Попробуйте ещё раз."

            if __event_emitter__:
                await __event_emitter__(
                    {"type": "status", "data": {"description": "⬇️ Загружаю изображение...", "done": False}}
                )

            # Download the image and convert to base64 data URI
            # Retry up to 3 times to handle transient failures
            display_url = None
            for attempt in range(3):
                try:
                    async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
                        img_response = await client.get(image_url)
                        img_response.raise_for_status()
                        b64_data = base64.b64encode(img_response.content).decode("utf-8")
                        content_type = img_response.headers.get("content-type", "image/png")
                        display_url = f"data:{content_type};base64,{b64_data}"
                        break
                except Exception as e:
                    logger.warning(f"[ImageGen] Download attempt {attempt+1}/3 failed: {e}")
                    if attempt == 2:
                        logger.error(f"[ImageGen] All download attempts failed, using raw URL")
                        display_url = image_url

            if __event_emitter__:
                await __event_emitter__(
                    {"type": "status", "data": {"description": "✅ Изображение сгенерировано!", "done": True}}
                )

            # Emit image via event emitter for reliable inline display
            # This avoids message size limits that can break rendering on repeat generations
            image_markdown = f"![{revised_prompt}]({display_url})"
            caption = f"\n\n*Модель: **{self.valves.model}** | Запрос: \"{prompt}\"*"

            if __event_emitter__:
                await __event_emitter__(
                    {"type": "message", "data": {"content": image_markdown + caption}}
                )
                return ""
            else:
                # Fallback: return markdown directly if no event emitter
                return image_markdown + caption

        except httpx.TimeoutException:
            logger.error("[ImageGen] Request timed out")
            if __event_emitter__:
                await __event_emitter__(
                    {"type": "status", "data": {"description": "❌ Таймаут запроса", "done": True}}
                )
            return "❌ Таймаут при генерации изображения. Попробуйте ещё раз или используйте более короткий промпт."

        except Exception as e:
            logger.error(f"[ImageGen] Unexpected error: {type(e).__name__}: {e}")
            if __event_emitter__:
                await __event_emitter__(
                    {"type": "status", "data": {"description": f"❌ Ошибка: {e}", "done": True}}
                )
            return f"❌ Непредвиденная ошибка: {type(e).__name__}: {str(e)[:200]}"
