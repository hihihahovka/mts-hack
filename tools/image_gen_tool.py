"""
Image Generation Tool — Pollinations API
==========================================
OpenWebUI Tool that generates images via the free Pollinations API.
Provides fast (~5-15s) image generation without requiring GPU.

The LLM calls generate_image(prompt) when the user asks to
"нарисуй", "сгенерируй картинку", "create an image", etc.
"""

import urllib.parse
from pydantic import BaseModel, Field


class Tools:
    class Valves(BaseModel):
        """Configurable parameters."""
        base_url: str = Field(
            default="https://image.pollinations.ai/prompt",
            description="Pollinations API base URL"
        )
        default_width: int = Field(default=1024, description="Default image width")
        default_height: int = Field(default=1024, description="Default image height")

    def __init__(self):
        self.valves = self.Valves()

    async def generate_image(
        self,
        prompt: str,
        width: int = 1024,
        height: int = 1024,
        __event_emitter__=None,
    ) -> str:
        """
        Generates an image from a text description using Pollinations AI.

        :param prompt: Text description of the image to generate (in English for best results).
        :param width: Image width in pixels (default 1024).
        :param height: Image height in pixels (default 1024).
        :return: Markdown with the generated image.
        """
        if __event_emitter__:
            await __event_emitter__(
                {"type": "status", "data": {"description": "🎨 Генерирую изображение...", "done": False}}
            )

        # URL-encode the prompt
        encoded_prompt = urllib.parse.quote(prompt)
        image_url = f"{self.valves.base_url}/{encoded_prompt}?width={width}&height={height}&nologo=true"

        if __event_emitter__:
            await __event_emitter__(
                {"type": "status", "data": {"description": "✅ Изображение сгенерировано!", "done": True}}
            )

        # Return markdown image — OpenWebUI will render it inline
        return f"![{prompt}]({image_url})\n\n*Сгенерировано по запросу: \"{prompt}\"*"
