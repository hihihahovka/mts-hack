"""
Memory Extract Filter (Hybrid Architecture)
=============================================
OpenWebUI Filter Function (outlet) that automatically extracts long-term context
about the user from the conversation and saves it into OpenWebUI's built-in memory.

ARCHITECTURE:
- [USER] + [FEEDBACK] = SQL only (global core memory, no embeddings)
- [PROJECT] = SQL + Vector DB (semantic episodic memory)
- Extraction LLM sees bounded context: all global facts + top-N relevant project facts
- Uses request.app.state.EMBEDDING_FUNCTION for proper async embedding generation

Uses Claude-Code style Taxonomy: [USER], [PROJECT], [FEEDBACK].

DEADLOCK AVOIDANCE:
- LLM extraction calls go DIRECTLY to MWS GPT API (not via OpenWebUI).
- Memory saves use the internal ORM directly (we're already inside OpenWebUI's process).
"""

import json
import logging
import os
import asyncio
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
        max_project_context: int = Field(
            default=10,
            description="Max [PROJECT] facts to include in extraction prompt (via vector search)."
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
                return [{"id": m.id, "content": m.content} for m in memories if hasattr(m, 'content') and m.content]
        except Exception as e:
            logger.warning(f"[MemoryExtract] Could not fetch existing memories: {e}")
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
        Uses normalized substring matching.
        """
        norm_new = self._normalize(new_content)
        if len(norm_new) < 5:
            return False

        for existing in existing_memories:
            norm_existing = self._normalize(existing["content"])
            if norm_new == norm_existing:
                return True
            if norm_new in norm_existing or norm_existing in norm_new:
                return True

        return False

    def _get_category(self, content: str) -> str:
        """Extract category tag from memory content."""
        for cat in ("[USER]", "[PROJECT]", "[FEEDBACK]"):
            if content.strip().startswith(cat):
                return cat
        return ""

    async def _vector_search_project(self, user_id: str, query_text: str, request, limit: int = 10) -> list:
        """
        Semantic search for relevant [PROJECT] memories via Vector DB.
        Returns list of memory dicts {id, content} or empty list.
        """
        try:
            from open_webui.retrieval.vector.factory import VECTOR_DB_CLIENT

            embedding_function = request.app.state.EMBEDDING_FUNCTION
            if not embedding_function:
                return []

            vector = await embedding_function(query_text)
            if not vector:
                return []

            search_vector = [vector] if not isinstance(vector[0], list) else vector
            collection_name = f"user-memory-{user_id}"

            if not VECTOR_DB_CLIENT.has_collection(collection_name):
                return []

            results = VECTOR_DB_CLIENT.search(
                collection_name=collection_name,
                vectors=search_vector,
                limit=limit,
            )

            if not results or not results.documents:
                return []

            # Rebuild memory dicts from vector results
            project_memories = []
            for i, doc_list in enumerate(results.documents):
                id_list = results.ids[i] if results.ids and i < len(results.ids) else []
                for j, doc in enumerate(doc_list):
                    if doc and doc.startswith("[PROJECT]"):
                        mem_id = id_list[j] if j < len(id_list) else "unknown"
                        project_memories.append({"id": mem_id, "content": doc})

            return project_memories

        except Exception as e:
            logger.warning(f"[MemoryExtract] Vector search for context failed: {e}")
            return []

    def _build_extraction_context(self, all_memories: list, relevant_project: list) -> list:
        """
        Build bounded extraction context:
        - ALL [USER] + [FEEDBACK] (global, always needed for dedup)
        - Top-N [PROJECT] from vector search (bounded, not all)
        Returns combined list of memory dicts.
        """
        global_memories = [m for m in all_memories if self._get_category(m["content"]) in ("[USER]", "[FEEDBACK]")]

        # Use vector results for PROJECT, deduplicated by ID
        seen_ids = {m["id"] for m in global_memories}
        project_memories = [m for m in relevant_project if m["id"] not in seen_ids]

        combined = global_memories + project_memories
        logger.info(
            f"[MemoryExtract] Extraction context: {len(global_memories)} global + "
            f"{len(project_memories)} project = {len(combined)} total"
        )
        return combined

    async def _extract_facts_via_llm(self, chat_history: str, existing_memories: list) -> list:
        """
        Calls the upstream LLM (MWS GPT) DIRECTLY to extract structured facts.
        Does NOT call OpenWebUI's own /api/chat/completions (that would deadlock).
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
            existing_block = f"""\n\nALREADY KNOWN FACTS (do NOT re-extract these or rephrasings of these):
{existing_lines}\n"""

        prompt = f"""You are a memory extraction agent. Analyze the chat history and extract persistent facts about the user.

CRITICAL RULES:
1. ONLY extract facts that the USER (human) has EXPLICITLY stated themselves in their own messages (lines starting with "USER:").
2. NEVER extract anything from ASSISTANT messages. The assistant may fabricate stories, roleplay, or make up details — these are NOT real facts about the user.
3. If the assistant says "I have a cat" or "my name is X" — that is the AI talking about itself, NOT a user fact. Ignore it completely.
4. Only extract information the user directly confirmed or volunteered about themselves.

Use the following strict taxonomy categories:
- [USER]: Facts about the user's role, preferences, skills, and background — ONLY if stated by the user.
- [PROJECT]: Facts about the project architecture, tech stack, and current state. Treat this as a living summary. If the user changes a previous technical decision (e.g., switching databases, changing frameworks), use UPDATE to overwrite the old fact rather than ADDing a conflicting new one.
- [FEEDBACK]: Explicit corrections or behavioral preferences the user has stated (e.g., "Don't write comments", "Always use pytest").

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

    async def _save_memory_internal(self, user_id: str, content: str, request=None):
        """
        Save memory to SQL. If [PROJECT], also upsert to Vector DB.
        """
        try:
            from open_webui.models.memories import Memories
            memory = await asyncio.to_thread(Memories.insert_new_memory, user_id, content)
            if not memory:
                logger.error(f"[MemoryExtract] SQL insert returned None for: {content[:60]}...")
                return None

            logger.info(f"[MemoryExtract] Saved memory to SQL: {content[:80]}...")

            # Only upsert [PROJECT] facts to Vector DB
            if self._get_category(content) == "[PROJECT]" and request:
                await self._vector_upsert(user_id, memory.id, content, memory.created_at, request)

            return memory
        except Exception as e:
            logger.error(f"[MemoryExtract] Memory save failed: {type(e).__name__}: {e}")
            return None

    async def _update_memory_internal(self, user_id: str, memory_id: str, content: str, request=None):
        """Update existing memory in SQL. If [PROJECT], also update Vector DB."""
        try:
            from open_webui.models.memories import Memories
            updated = await asyncio.to_thread(
                Memories.update_memory_by_id_and_user_id, memory_id, user_id, content
            )
            if not updated:
                logger.error(f"[MemoryExtract] SQL update failed for memory_id={memory_id}")
                return None

            logger.info(f"[MemoryExtract] Updated memory in SQL: {memory_id}")

            # Update vector if [PROJECT]
            if self._get_category(content) == "[PROJECT]" and request:
                await self._vector_upsert(user_id, memory_id, content, updated.created_at, request)

            return updated
        except Exception as e:
            logger.error(f"[MemoryExtract] Memory update failed: {e}")
            return None

    async def _delete_memory_internal(self, user_id: str, memory_id: str, old_content: str = ""):
        """Delete memory from SQL. If was [PROJECT], also delete from Vector DB."""
        try:
            from open_webui.models.memories import Memories
            success = await asyncio.to_thread(
                Memories.delete_memory_by_id_and_user_id, memory_id, user_id
            )
            if not success:
                logger.error(f"[MemoryExtract] SQL delete returned False for memory_id={memory_id}")
                return

            logger.info(f"[MemoryExtract] Deleted memory from SQL: {memory_id}")

            # Clean up vector if was [PROJECT]
            if self._get_category(old_content) == "[PROJECT]":
                try:
                    from open_webui.retrieval.vector.factory import VECTOR_DB_CLIENT
                    collection = f"user-memory-{user_id}"
                    if VECTOR_DB_CLIENT.has_collection(collection):
                        VECTOR_DB_CLIENT.delete(collection_name=collection, ids=[memory_id])
                        logger.info(f"[MemoryExtract] Deleted from Vector DB: {memory_id}")
                except Exception as e:
                    logger.warning(f"[MemoryExtract] Vector DB delete failed (non-fatal): {e}")

        except Exception as e:
            logger.error(f"[MemoryExtract] Memory delete failed: {e}")

    async def _vector_upsert(self, user_id: str, memory_id: str, content: str, created_at: int, request):
        """Upsert a single memory to Vector DB using EMBEDDING_FUNCTION."""
        try:
            from open_webui.retrieval.vector.factory import VECTOR_DB_CLIENT

            embedding_function = request.app.state.EMBEDDING_FUNCTION
            if not embedding_function:
                logger.warning("[MemoryExtract] EMBEDDING_FUNCTION not available, skipping vector upsert")
                return

            vector = await embedding_function(content)

            if not vector:
                logger.warning("[MemoryExtract] Embedding generation empty, skipping vector upsert")
                return

            vec = vector[0] if isinstance(vector, list) and isinstance(vector[0], list) else vector

            VECTOR_DB_CLIENT.upsert(
                collection_name=f"user-memory-{user_id}",
                items=[{
                    "id": memory_id,
                    "text": content,
                    "vector": vec,
                    "metadata": {"created_at": created_at},
                }],
            )
            logger.info(f"[MemoryExtract] Vector DB upsert OK: {memory_id}")

        except Exception as e:
            logger.warning(f"[MemoryExtract] Vector upsert failed (non-fatal): {type(e).__name__}: {e}")

    async def outlet(self, body: dict, __user__: Optional[dict] = None, __request__=None) -> dict:
        """
        OUTLET: Runs after AI responds. Analyzes history and extracts memories.
        Handles ADD, UPDATE, DELETE actions.
        Uses hybrid context: all global + top-N relevant project facts.
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

        # Fetch all memories from SQL
        existing_memories = await asyncio.to_thread(self._get_existing_memories, user_id)
        logger.info(f"[MemoryExtract] User has {len(existing_memories)} existing memories")

        # Build bounded extraction context:
        # All [USER]+[FEEDBACK] + top-N relevant [PROJECT] via vector search
        relevant_project = []
        if __request__:
            relevant_project = await self._vector_search_project(
                user_id, chat_history[:2000],  # cap query length
                __request__,
                limit=self.valves.max_project_context
            )

        if not relevant_project:
            # Fallback: use last N [PROJECT] from SQL
            all_project = [m for m in existing_memories if self._get_category(m["content"]) == "[PROJECT]"]
            relevant_project = all_project[-self.valves.max_project_context:]

        extraction_context = self._build_extraction_context(existing_memories, relevant_project)

        # Call extraction LLM with bounded context
        facts = await self._extract_facts_via_llm(chat_history, extraction_context)

        if not facts:
            return body

        saved_count = 0
        updated_count = 0
        deleted_count = 0
        skipped_count = 0

        # Build lookup for validation — need full existing_memories for ID checks
        valid_ids = {m["id"]: m["content"] for m in existing_memories}

        for item in facts:
            action = item.get("action", "ADD").upper()
            target_id = item.get("target_id", "")

            if action == "DELETE":
                if target_id and target_id in valid_ids:
                    old_content = valid_ids[target_id]
                    await self._delete_memory_internal(user_id, target_id, old_content)
                    del valid_ids[target_id]
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
                    await self._update_memory_internal(user_id, target_id, content, __request__)
                    valid_ids[target_id] = content
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

            result = await self._save_memory_internal(user_id, content, __request__)
            if result:
                existing_memories.append({"id": result.id, "content": content})
                valid_ids[result.id] = content
            saved_count += 1

        logger.info(
            f"[MemoryExtract] Summary: {saved_count} ADD, {updated_count} UPDATE, "
            f"{deleted_count} DELETE, {skipped_count} SKIPPED"
        )

        return body
