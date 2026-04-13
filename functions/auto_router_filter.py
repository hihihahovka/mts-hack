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
        INLET: Analyzes the user's message using an LLM and routes to the optimal model.
        """
        if not self.valves.enable_auto_routing or __request__ is None:
            return body

        messages = body.get("messages", [])
        if not messages:
            return body

        # Avoid routing the routing request itself
        if body.get("metadata", {}).get("task") == "MODEL_AUTOROUTING":
            return body

        original_model = body.get("model", "")

        last_message = self._get_last_user_message(messages)
        files = body.get("files", [])

        last_message_lower = last_message.lower()
        
        # Hardcode image generation routing FIRST (safe keywords)
        img_keywords = [
            "нарисуй", "сделай картинку", "сгенерируй картинку", "сгенерировать картинку",
            "сгенерируй изображение", "сгенерировать изображение", "draw an image", 
            "create an image", "изобрази"
        ]
        if any(keyword in last_message_lower for keyword in img_keywords) and "код" not in last_message_lower:
            if "metadata" not in body:
                body["metadata"] = {}
            body["metadata"]["_routed_model"] = "image_gen_pipe.qwen-image"
            body["model"] = "image_gen_pipe.qwen-image"
            return body

        has_image = self._has_modality(
            messages, files, ["image"], (".png", ".jpg", ".jpeg", ".gif")
        )
        if has_image:
            if "metadata" not in body:
                body["metadata"] = {}
            body["metadata"]["_routed_model"] = "qwen2.5-vl-72b"
            body["model"] = "qwen2.5-vl-72b"
            return body

        has_audio = self._has_modality(
            messages, files, ["audio"], (".mp3", ".wav", ".ogg", ".m4a")
        )
        has_text_file = self._has_modality(
            messages,
            files,
            ["text", "pdf", "document"],
            (".txt", ".pdf", ".docx", ".csv"),
        )
        
        # Hardcode coding model routing (only if strongly indicated in the text)
        code_keywords = ["скрипт", "python", "javascript", "html", "css", "c++", "java ", "закодить", "напиши код", "ошибка в коде"]
        if any(keyword in last_message_lower for keyword in code_keywords):
            if "metadata" not in body:
                body["metadata"] = {}
            body["metadata"]["_routed_model"] = "qwen3-coder-480b-a35b"
            body["model"] = "qwen3-coder-480b-a35b"
            return body

        models_dict = __request__.app.state.MODELS
        available_models = []
        for model_id, model_data in models_dict.items():
            if (
                "pipeline" in model_data
                and model_data["pipeline"].get("type") == "filter"
            ):
                continue
            if model_id == "autorouting":
                continue

            desc = model_data.get("info", {}).get("meta", {}).get("description", "")
            capabilities = (
                model_data.get("info", {}).get("meta", {}).get("capabilities", {})
            )
            if capabilities.get("vision"):
                desc += " (Vision/Image capable VLM)"

            if not desc:
                # Fallback to name keywords if there's no description
                desc = (
                    "vision vlm image"
                    if any(
                        x in model_id.lower() or x in model_data.get("name", "").lower()
                        for x in ["vision", "vlm", "vl"]
                    )
                    else ""
                )

            available_models.append(
                {
                    "id": model_id,
                    "name": model_data.get("name", model_id),
                    "description": desc[:150],
                }
            )

        prompt = f"""You are an advanced AI routing system. DO NOT ANSWER the user's query. Your ONLY task is to select the most appropriate model ID from the Available Models list for the user's request.

Available Models:
{json.dumps(available_models, indent=2)}

Original Model Selected by User: {original_model}

Rules for Routing:
1. If the user explicitly asks to generate an image ("нарисуй", "сгенерируй", "сгенерировать", "draw", "create an image", "изобрази"), you MUST select an Image Generation model (e.g., ID containing 'image', 'lightning', 'qwen-image', 'dall-e').
2. If the user attached an image (has_image={has_image}), you MUST select a Vision Language Model (VLM) (e.g., ID containing 'vl', 'vision', 'cotype-pro-vl', 'qwen2.5-vl').
3. If the user attached audio (has_audio={has_audio}), you MUST select an Audio model (e.g., 'whisper', 'asr').
4. If the user explicitly asks to write, explain, review, or debug code, or mentions programming, you MUST select a Coding model (e.g., ID containing 'coder', 'qwen3-coder').
5. For ANY other standard text or reasoning questions: if the Original Model ({original_model}) is NOT a standard text model (e.g. if it's an image or audio model), you MUST select a good standard text model like 'deepseek-r1-distill-qwen-32b', 'llama-3.3-70b-instruct' or 'qwen3-32b'. If {original_model} IS already a standard text model, just return {original_model}.
6. DO NOT hallucinate. Only output exactly one Model ID from the Available Models list.

<user_query_to_analyze>
{last_message}
</user_query_to_analyze>

Provide your answer as a single string of the chosen model ID. NO EXCEPTIONS. JUST THE STRING ID.
"""
        task_model_id = self.valves.router_model
        if not task_model_id or task_model_id not in models_dict:
            task_model_id = original_model

        if not task_model_id:
            return body

        payload = {
            "model": task_model_id,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "metadata": {"task": "MODEL_AUTOROUTING", "bypass_filter": True},
        }

        try:
            response = await generate_chat_completion(
                __request__, form_data=payload, user=__user__, bypass_filter=True
            )
            if "choices" in response and len(response["choices"]) > 0:
                result_text = response["choices"][0]["message"]["content"].strip()

                # Clean up <think> blocks common in Deepseek R1
                result_text = re.sub(
                    r"<think>.*?</think>", "", result_text, flags=re.DOTALL
                ).strip()

                # Match the longest model ID present in the generated text
                sorted_models = sorted(
                    available_models, key=lambda x: len(x["id"]), reverse=True
                )

                routed_id = None
                for m in sorted_models:
                    if m["id"] in result_text:
                        routed_id = m["id"]
                        break

                if routed_id:
                    if routed_id in ["qwen-image", "qwen-image-lightning"]:
                        routed_id = f"image_gen_pipe.{routed_id}"
                        
                    if "metadata" not in body:
                        body["metadata"] = {}
                    body["metadata"]["_routed_model"] = routed_id
                    body["model"] = routed_id
                    return body

        except Exception as e:
            log.error(f"Autorouting LLM selection error: {e}")

        # Fallback if LLM fails or no match found
        if "metadata" not in body:
            body["metadata"] = {}
        body["metadata"]["_routed_model"] = original_model
        body["model"] = original_model

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