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
            default=True,
            description="Enable automatic neural network model routing"
        )
        show_routing_badge: bool = Field(
            default=True,
            description="Show routing badge in response"
        )
        router_model: str = Field(
            default="",
            description="The model to use for routing decisions. Leave blank to use system default TASK_MODEL."
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

    def _has_modality(self, messages: list, files: list, file_type_keywords: list, file_exts: tuple) -> bool:
        # Check files array
        for file_item in files:
            t = file_item.get("type", "")
            n = file_item.get("name", "").lower()
            if any(k in t for k in file_type_keywords) or n.endswith(file_exts):
                return True
        # Check messages for attachments
        for msg in messages:
            if msg.get("role") == "user":
                content = msg.get("content", "")
                if isinstance(content, list):
                    for part in content:
                        if part.get("type") == "image_url" and "image" in file_type_keywords:
                            return True
                for file_item in msg.get("files", []):
                    t = file_item.get("type", "")
                    n = file_item.get("name", "").lower()
                    if any(k in t for k in file_type_keywords) or n.endswith(file_exts):
                        return True
        return False

    async def inlet(self, body: dict, __user__: dict = None, __request__: Request = None) -> dict:
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

        has_image = self._has_modality(messages, files, ["image"], (".png", ".jpg", ".jpeg", ".gif"))
        has_audio = self._has_modality(messages, files, ["audio"], (".mp3", ".wav", ".ogg", ".m4a"))
        has_text_file = self._has_modality(messages, files, ["text", "pdf", "document"], (".txt", ".pdf", ".docx", ".csv"))

        models_dict = __request__.app.state.MODELS
        available_models = []
        for model_id, model_data in models_dict.items():
            if "pipeline" in model_data and model_data["pipeline"].get("type") == "filter":
                continue
            available_models.append({
                "id": model_id,
                "name": model_data.get("name", model_id)
            })

        prompt = f"""You are an advanced AI model router. Your job is to select the most appropriate model ID from the JSON list of available models below, based strictly on the user's latest request and contextual hints.

Rules to follow:
1. If the user attached an image ({has_image}), you MUST choose a VLM (Vision Language Model).
2. If the user attached audio ({has_audio}), you MUST choose an ASR (Speech-to-text/Audio) model.
3. If the user asks to "generate image", "draw", or similar, choose an Image Generation model.
4. If the user attached a document/text file ({has_text_file}), choose a model suited for RAG (e.g. rag_files).
5. Otherwise, choose a standard LLM for conversational text.

Available Models:
{json.dumps(available_models, indent=2)}

User's Latest Query:
{last_message}

IMPORTANT: Reply ONLY with a valid string containing the selected `id` from the Available Models list. Do not include quotes, JSON, or any other explanations. Just the ID string.
"""
        task_model_id = self.valves.router_model
        if not task_model_id:
            task_model_id = __request__.app.state.config.TASK_MODEL
        
        if not task_model_id or task_model_id not in models_dict:
            task_model_id = available_models[0]["id"] if available_models else None

        if not task_model_id:
            return body

        payload = {
            "model": task_model_id,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "metadata": {
                "task": "MODEL_AUTOROUTING",
                "bypass_filter": True
            }
        }

        try:
            response = await generate_chat_completion(__request__, form_data=payload, user=__user__, bypass_filter=True)
            if 'choices' in response and len(response['choices']) > 0:
                result_text = response['choices'][0]['message']['content'].strip()
                
                # Extract the ID
                match = re.search(r'[\w.-]+', result_text)
                if match:
                    selected_id = match.group(0)
                    if selected_id in models_dict:
                        self._routed_model = selected_id
                        body["model"] = selected_id
                        return body
                        
                for m in available_models:
                    if m["id"] == result_text:
                        self._routed_model = result_text
                        body["model"] = result_text
                        return body
                        
        except Exception as e:
            log.error(f"Autorouting LLM selection error: {e}")

        self._routed_model = original_model
        return body

    async def outlet(self, body: dict, __user__: dict = None, __event_emitter__=None) -> dict:
        """
        OUTLET: Injects a routing badge showing which model was used.
        """
        if not self.valves.show_routing_badge or not self._routed_model:
            return body

        messages = body.get("messages", [])
        if not messages:
            return body

        for msg in reversed(messages):
            if msg.get("role") == "assistant":
                content = msg.get("content", "")
                if isinstance(content, str) and content:
                    badge = f"\n\n---\n🤖 *{self._routed_model}* — {self._routing_reason}\n"
                    msg["content"] = content + badge
                break

        self._routed_model = ""
        return body