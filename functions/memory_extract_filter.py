"""
Memory Extract Filter
=====================
OpenWebUI Filter Function (outlet) that automatically extracts long-term context 
about the user from the conversation and saves it into OpenWebUI's built-in memory.

Uses Claude-Code style Taxonomy: [USER], [PROJECT], [FEEDBACK].

ARCHITECTURE NOTE:
- LLM extraction calls go DIRECTLY to MWS GPT API (not via OpenWebUI) to avoid deadlocks.
- Memory saves use the internal ORM directly (we're already inside OpenWebUI's process).
- Vector DB upsert is attempted for full memory system integration.
"""

import json
import logging
import os
from pydantic import BaseModel, Field
from typing import Optional

logger = logging.getLogger(__name__)


class Filter:
    class Valves(BaseModel):
        extraction_interval: int = Field(
            default=1,
            description="Extract memories every N user messages in a conversation."
        )
        extraction_model: str = Field(
            default="mws-gpt-alpha",
            description="Model used for fact extraction."
        )
        mws_api_base_url: str = Field(
            default="https://api.gpt.mws.ru/v1",
            description="Direct URL to the upstream LLM API (MWS GPT). NOT OpenWebUI's own URL."
        )
        mws_api_key: str = Field(
            default="",
            description="API key for the upstream LLM. Leave empty to read from MWS_API_KEY env var."
        )
        enable_memory_extraction: bool = Field(
            default=True,
            description="Enable automatic memory extraction."
        )

    def __init__(self):
        self.valves = self.Valves()

    def _get_mws_api_key(self) -> str:
        """Get MWS API key from valves or environment."""
        if self.valves.mws_api_key:
            return self.valves.mws_api_key
        key = os.environ.get("MWS_API_KEY", "") or os.environ.get("OPENAI_API_KEY", "")
        return key

    def _get_existing_memories(self, user_id: str) -> list:
        """Fetch all existing memories for the user from the internal ORM."""
        try:
            from open_webui.models.memories import Memories
            memories = Memories.get_memories_by_user_id(user_id)
            if memories:
                # Return dicts instead of strings so we have IDs for UPDATE/DELETE
                return [{"id": m.id, "content": m.content} for m in memories if hasattr(m, 'content') and m.content]
        except Exception as e:
            logger.warning(f"[MemoryExtract] Could not fetch existing memories for dedup: {e}")
        return []

    def _normalize(self, text: str) -> str:
        """Normalize text for comparison: lowercase, strip whitespace and category tags."""
        import re
        text = text.lower().strip()
        text = re.sub(r'\[(?:user|project|feedback)\]\s*', '', text)
        text = re.sub(r'\s+', ' ', text)
        return text

    def _is_duplicate(self, new_content: str, existing_memories: list) -> bool:
        """
        Check if new_content is a duplicate of any existing memory.
        Uses normalized substring matching — if the core fact is already
        contained in (or contains) an existing memory, it's a duplicate.
        """
        norm_new = self._normalize(new_content)
        if len(norm_new) < 5:
            return False

        for existing in existing_memories:
            norm_existing = self._normalize(existing["content"])
            # Exact match after normalization
            if norm_new == norm_existing:
                return True
            # Substring containment (either direction)
            if norm_new in norm_existing or norm_existing in norm_new:
                return True

        return False

    async def _extract_facts_via_llm(self, chat_history: str, existing_memories: list) -> list:
        """
        Calls the upstream LLM (MWS GPT) DIRECTLY to extract structured facts.
        Does NOT call OpenWebUI's own /api/chat/completions (that would deadlock).
        Passes existing memories to the LLM so it can update, delete, or add new facts.
        """
        import httpx

        api_key = self._get_mws_api_key()
        if not api_key:
            logger.error("[MemoryExtract] No MWS API key configured. Set mws_api_key valve or MWS_API_KEY env var.")
            return []

        # Format existing memories for the prompt with IDs
        existing_block = ""
        if existing_memories:
            existing_lines = "\n".join(f"[ID: {m['id']}] {m['content']}" for m in existing_memories)
            existing_block = f"""\n\nALREADY KNOWN FACTS(do NOT re-extract these or rephrasings of these):
{existing_lines}\n"""

        prompt = f"""You are a memory extraction agent. Analyze the chat history and extract persistent facts about the user.

CRITICAL RULES:
1. ONLY extract facts that the USER (human) has EXPLICITLY stated themselves in their own messages (lines starting with "USER:").
2. NEVER extract anything from ASSISTANT messages. The assistant may fabricate stories, roleplay, or make up details — these are NOT real facts about the user.
3. If the assistant says "I have a cat" or "my name is X" — that is the AI talking about itself, NOT a user fact. Ignore it completely.
4. Only extract information the user directly confirmed or volunteered about themselves.

Use the following strict taxonomy categories:
- [USER]: Facts about the user's role, preferences, skills, and background — ONLY if stated by the user.
- [PROJECT]: Facts about the current project architecture, ongoing tasks, tech stack, and constraints — ONLY if stated by the user.
- [FEEDBACK]: Explicit corrections or behavioral preferences the user has stated (e.g., "Don't write comments", "Always use pytest").

Examples of what to extract:
- USER says "меня зовут Макар" → {{"action": "ADD", "category": "[USER]", "fact": "Имя пользователя — Макар"}}
- USER says "у меня есть кот Бублик" → {{"action": "ADD", "category": "[USER]", "fact": "У пользователя есть кот по имени Бублик"}}
- USER says "я работаю в МТС" → {{"action": "ADD", "category": "[USER]", "fact": "Работает в МТС"}}

ACTIONS:
- ADD: New fact not in known facts.
- UPDATE: User corrects a known fact. Provide exact `target_id`.
- DELETE: User explicitly denies/revokes a known fact. Provide exact `target_id`.

SAFETY FOR UPDATE/DELETE:
- Only target facts DIRECTLY contradicted by the user. Never touch unrelated facts.
- One target per action. If user says "I lost my job" — only affect the job fact, not name or pets.
{existing_block}
Chat History:
{chat_history}

Output ONLY a valid JSON array. If nothing to extract, return [].
[
  {{"action": "ADD", "category": "[USER]", "fact": "fact text"}},
  {{"action": "UPDATE", "target_id": "id", "category": "[USER]", "fact": "updated text"}},
  {{"action": "DELETE", "target_id": "id"}}
]"""

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }

        payload = {
            "model": self.valves.extraction_model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "temperature": 0.1,
        }

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.valves.mws_api_base_url}/chat/completions",
                    json=payload,
                    headers=headers,
                    timeout=30.0
                )

            if response.status_code == 200:
                result = response.json()
                content = result["choices"][0]["message"]["content"]
                logger.info(f"[MemoryExtract] Raw LLM response: {content[:500]}")
                facts = self._parse_llm_json(content)
                logger.info(f"[MemoryExtract] Parsed {len(facts)} actions from LLM response")
                return facts
            else:
                logger.error(f"[MemoryExtract] LLM API returned {response.status_code}: {response.text[:200]}")
        except Exception as e:
            logger.error(f"[MemoryExtract] LLM call failed: {type(e).__name__}: {e}")

        return []

    def _parse_llm_json(self, content: str) -> list:
        """
        Robustly parse LLM response into a list of fact dicts.
        Handles: markdown fences, text before/after JSON, multiple objects, etc.
        """
        import re

        if not content or not content.strip():
            return []

        # Strip markdown code fences
        content = content.replace("```json", "").replace("```", "").strip()

        # Try direct parse first
        try:
            parsed = json.loads(content)
            if isinstance(parsed, list):
                return parsed
            if isinstance(parsed, dict):
                return [parsed]
        except json.JSONDecodeError:
            pass

        # Try to find JSON array in the text with regex
        array_match = re.search(r'\[.*\]', content, re.DOTALL)
        if array_match:
            try:
                parsed = json.loads(array_match.group())
                if isinstance(parsed, list):
                    return parsed
            except json.JSONDecodeError:
                pass

        # Try to find individual JSON objects and collect them
        obj_matches = re.findall(r'\{[^{}]*\}', content)
        if obj_matches:
            results = []
            for obj_str in obj_matches:
                try:
                    obj = json.loads(obj_str)
                    if isinstance(obj, dict) and ("action" in obj or "fact" in obj):
                        results.append(obj)
                except json.JSONDecodeError:
                    continue
            if results:
                return results

        # Nothing parseable
        logger.warning(f"[MemoryExtract] Could not parse LLM response as JSON: {content[:200]}")
        return []

    def _save_memory_internal(self, user_id: str, content: str):
        """Save memory directly via internal ORM + attempt vector DB upsert."""
        try:
            from open_webui.models.memories import Memories
            memory = Memories.insert_new_memory(user_id, content)
            if not memory:
                logger.error(f"[MemoryExtract] SQL insert returned None for: {content[:60]}...")
                return
            
            logger.info(f"[MemoryExtract] Saved memory to DB: {content[:80]}...")
            
            try:
                from open_webui.retrieval.vector.factory import VECTOR_DB_CLIENT
                try:
                    from open_webui.retrieval.utils import generate_embeddings
                    vector = generate_embeddings(content)
                    if vector and isinstance(vector, list) and len(vector) > 0:
                        vec = vector[0] if isinstance(vector[0], list) else vector
                        VECTOR_DB_CLIENT.upsert(
                            collection_name=f"user-memory-{user_id}",
                            items=[{
                                "id": memory.id,
                                "text": memory.content,
                                "vector": vec,
                                "metadata": {"created_at": memory.created_at},
                            }],
                        )
                    else:
                        logger.warning("[MemoryExtract] Embedding generation empty, skipping vector upsert.")
                except Exception as e:
                    logger.warning(f"[MemoryExtract] Vector upsert failed (non-fatal): {e}")
            except Exception as e:
                pass
        except Exception as e:
            logger.error(f"[MemoryExtract] Memory save failed: {type(e).__name__}: {e}")

    def _update_memory_internal(self, user_id: str, memory_id: str, content: str):
        """Update existing memory via ORM + vector DB."""
        try:
            from open_webui.models.memories import Memories
            updated_memory = Memories.update_memory_by_id_and_user_id(memory_id, user_id, content)
            if not updated_memory:
                logger.error(f"[MemoryExtract] SQL update failed for memory_id={memory_id}")
                return
            
            logger.info(f"[MemoryExtract] Updated memory in DB: {memory_id}")
            
            try:
                from open_webui.retrieval.vector.factory import VECTOR_DB_CLIENT
                try:
                    from open_webui.retrieval.utils import generate_embeddings
                    vector = generate_embeddings(content)
                    if vector and isinstance(vector, list) and len(vector) > 0:
                        vec = vector[0] if isinstance(vector[0], list) else vector
                        VECTOR_DB_CLIENT.upsert(
                            collection_name=f"user-memory-{user_id}",
                            items=[{
                                "id": memory_id,
                                "text": content,
                                "vector": vec,
                                "metadata": {"created_at": updated_memory.created_at},
                            }],
                        )
                except Exception as e:
                    logger.warning(f"[MemoryExtract] Vector DB update failed: {e}")
            except Exception as e:
                pass
        except Exception as e:
            logger.error(f"[MemoryExtract] Memory update failed: {e}")

    def _delete_memory_internal(self, user_id: str, memory_id: str):
        """Delete memory via ORM + vector DB."""
        try:
            from open_webui.models.memories import Memories
            success = Memories.delete_memory_by_id_and_user_id(memory_id, user_id)
            if not success:
                logger.error(f"[MemoryExtract] SQL delete returned False for memory_id={memory_id}")
                return
            
            logger.info(f"[MemoryExtract] Deleted memory DB: {memory_id}")
            
            try:
                from open_webui.retrieval.vector.factory import VECTOR_DB_CLIENT
                VECTOR_DB_CLIENT.delete(
                    collection_name=f"user-memory-{user_id}",
                    ids=[memory_id],
                )
            except Exception as e:
                logger.warning(f"[MemoryExtract] Vector DB delete failed: {e}")
        except Exception as e:
            logger.error(f"[MemoryExtract] Memory delete failed: {e}")

    async def outlet(self, body: dict, __user__: Optional[dict] = None) -> dict:
        """
        OUTLET: Runs after AI responds. Analyzes history and extracts memories.
        Handles ADD, UPDATE, DELETE actions.
        """
        if not self.valves.enable_memory_extraction or not __user__:
            return body

        user_id = __user__.get("id", "")
        if not user_id:
            logger.warning("[MemoryExtract] No user id found, skipping extraction.")
            return body

        messages = body.get("messages", [])
        user_msgs = [m for m in messages if m.get("role") == "user"]

        if not user_msgs:
            return body

        msg_count = len(user_msgs)
        if msg_count % self.valves.extraction_interval != 0:
            return body

        window_size = max(self.valves.extraction_interval * 2, 10)
        context_msgs = messages[-window_size:]
        chat_history = "\n".join([
            f"{m['role'].upper()}: {m['content']}"
            for m in context_msgs
            if isinstance(m.get('content'), str)
        ])

        if not chat_history:
            return body

        existing_memories = self._get_existing_memories(user_id)
        logger.info(f"[MemoryExtract] User has {len(existing_memories)} existing memories")

        facts = await self._extract_facts_via_llm(chat_history, existing_memories)

        if not facts:
            return body

        saved_count = 0
        updated_count = 0
        deleted_count = 0
        skipped_count = 0

        # Build set of valid memory IDs for validation
        valid_ids = {m["id"] for m in existing_memories}

        for item in facts:
            action = item.get("action", "ADD").upper()
            target_id = item.get("target_id", "")

            if action == "DELETE":
                if target_id and target_id in valid_ids:
                    self._delete_memory_internal(user_id, target_id)
                    valid_ids.discard(target_id)
                    deleted_count += 1
                elif target_id:
                    logger.warning(f"[MemoryExtract] DELETE rejected — target_id {target_id[:12]}... not in known memories")
                    skipped_count += 1
                continue

            category = item.get("category", "[PROJECT]")
            fact = item.get("fact", "")
            if not fact:
                continue

            content = f"{category} {fact}"

            if action == "UPDATE":
                if target_id and target_id in valid_ids:
                    self._update_memory_internal(user_id, target_id, content)
                    updated_count += 1
                elif target_id:
                    logger.warning(f"[MemoryExtract] UPDATE rejected — target_id {target_id[:12]}... not in known memories")
                    skipped_count += 1
                else:
                    logger.warning("[MemoryExtract] UPDATE missing target_id")
                    skipped_count += 1
                continue
            
            # Default is ADD
            if self._is_duplicate(content, existing_memories):
                logger.info(f"[MemoryExtract] Skipped duplicate: {content[:80]}...")
                skipped_count += 1
                continue

            self._save_memory_internal(user_id, content)
            existing_memories.append({"id": "tmp_new", "content": content})
            saved_count += 1

        logger.info(f"[MemoryExtract] Summary: {saved_count} ADD, {updated_count} UPDATE, {deleted_count} DELETE, {skipped_count} SKIPPED")

        return body
