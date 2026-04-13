"""
Memory Extract Filter (Three-Scope Architecture)
===================================================
OpenWebUI Filter Function (outlet) that automatically extracts long-term context
about the user from the conversation and saves it into OpenWebUI's built-in memory.

THREE SCOPES:
  1. GLOBAL (chats without folder):
     [IDENTITY], [USER], [FEEDBACK] = SQL only (always global)
     [PROJECT] = SQL + Vector DB (semantic episodic)

  2. FOLDER (chats inside a folder — PROJECT isolated, core facts cascade):
     [IDENTITY], [USER], [FEEDBACK] = always global, cascade into all folders
     [PROJECT:folder:XYZ] = SQL + Vector DB (collection: folder-{md5}, STRICTLY isolated)

  3. LOCAL (per-chat — decisions, solutions, architecture):
     [LOCAL:chat:ABC] = SQL + Vector DB (single collection: local-{md5(user_id)}, filtered by chat_id)
     Extracted from BOTH user + AI messages (only when user confirms AI's output)
     No compaction — grows unbounded, retrieved via semantic RAG

DEADLOCK AVOIDANCE:
- LLM extraction calls go DIRECTLY to MWS GPT API (not via OpenWebUI).
- Memory saves use the internal ORM directly (we're already inside OpenWebUI's process).
"""

import datetime
import hashlib
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
        enable_local_memory: bool = Field(
            default=True,
            description="Enable per-chat local memory extraction (decisions, solutions, architecture)."
        )
        extract_from_ai_responses: bool = Field(
            default=True,
            description="Extract local facts from AI responses when user confirms/accepts them."
        )
        max_project_context: int = Field(
            default=10,
            description="Max [PROJECT] facts to include in extraction prompt (via vector search)."
        )
        max_local_context: int = Field(
            default=10,
            description="Max [LOCAL] facts to include in local extraction prompt context (via vector search)."
        )
        max_deletes_per_cycle: int = Field(
            default=2,
            description="Maximum DELETE actions allowed per extraction cycle. Safety cap."
        )

    def __init__(self):
        self.valves = self.Valves()

    # =========================================================================
    # Helpers
    # =========================================================================

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
        text = re.sub(r'\[(?:identity|user|project|feedback|local)(?::[\w-]+)*\]\s*', '', text)
        text = re.sub(r'\s+', ' ', text)
        return text

    def _is_duplicate(self, new_content: str, existing_memories: list) -> bool:
        """Check if new_content is a duplicate of any existing memory."""
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
        """Extract category tag from memory content. Returns full tag like [PROJECT:folder:abc]."""
        import re
        # Match any tag pattern like [CATEGORY] or [CATEGORY:scope:id]
        match = re.match(r'(\[(?:IDENTITY|USER|PROJECT|FEEDBACK|LOCAL)(?::[^\]]+)?\])', content.strip())
        if match:
            return match.group(1)
        return ""

    def _get_base_category(self, content: str) -> str:
        """Get base category without scope suffix. [PROJECT:folder:abc] -> [PROJECT]."""
        cat = self._get_category(content)
        if not cat:
            return ""
        base = cat.split(":")[0]
        if not base.endswith("]"):
            base += "]"
        return base

    def _is_project_category(self, content: str) -> bool:
        """Check if memory is any variant of PROJECT."""
        return self._get_base_category(content) == "[PROJECT]"

    def _is_local_category(self, content: str) -> bool:
        """Check if memory is LOCAL."""
        return self._get_base_category(content) == "[LOCAL]"

    def _get_scope_prefix(self, folder_id: str = None) -> str:
        """Get the scope suffix for memory tags. Returns ':folder:XYZ' or ''."""
        if folder_id:
            return f":folder:{folder_id}"
        return ""

    def _tag_content(self, category: str, fact: str, folder_id: str = None) -> str:
        """Build tagged content like [PROJECT:folder:abc] fact text."""
        scope = self._get_scope_prefix(folder_id)
        return f"[{category}{scope}] {fact}"

    def _safe_collection_name(self, prefix: str, *ids: str) -> str:
        """Build a ChromaDB-safe collection name (max 63 chars) by hashing IDs."""
        raw = ":".join(ids)
        hashed = hashlib.md5(raw.encode()).hexdigest()
        return f"{prefix}-{hashed}"

    def _matches_scope(self, content: str, folder_id: str = None) -> bool:
        """Check if a memory matches the current scope.
        
        Core facts (IDENTITY/USER/FEEDBACK) are ALWAYS global — visible everywhere.
        
        PROJECT is STRICTLY isolated:
        - [PROJECT] only visible in global (no folder)
        - [PROJECT:folder:X] only visible in folder X
        """
        cat = self._get_category(content)
        if not cat:
            return False
        base_cat = self._get_base_category(content)

        # Core facts cascade: global ones always visible, folder overrides only in matching folder
        if base_cat in ("[IDENTITY]", "[USER]", "[FEEDBACK]"):
            if ":folder:" in cat:
                return f":folder:{folder_id}" in cat if folder_id else False
            return True  # Global core facts visible everywhere

        # PROJECT is strictly quarantined
        if folder_id:
            return f":folder:{folder_id}" in cat
        else:
            return ":folder:" not in cat and ":chat:" not in cat

    # =========================================================================
    # Vector DB Operations
    # =========================================================================

    async def _vector_search_project(self, user_id: str, query_text: str, request, limit: int = 10,
                                      folder_id: str = None) -> list:
        """
        Semantic search for relevant [PROJECT] memories via Vector DB.
        Scoped to folder if folder_id provided.
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

            if folder_id:
                collection_name = self._safe_collection_name("folder", user_id, folder_id)
            else:
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

            project_memories = []
            for i, doc_list in enumerate(results.documents):
                id_list = results.ids[i] if results.ids and i < len(results.ids) else []
                for j, doc in enumerate(doc_list):
                    if doc and self._is_project_category(doc):
                        mem_id = id_list[j] if j < len(id_list) else "unknown"
                        project_memories.append({"id": mem_id, "content": doc})

            return project_memories

        except Exception as e:
            logger.warning(f"[MemoryExtract] Vector search for project context failed: {e}")
            return []

    async def _vector_search_local(self, user_id: str, chat_id: str, query_text: str, request, limit: int = 10) -> list:
        """
        Semantic search for relevant [LOCAL] memories in the user's single local collection.
        Uses metadata filter to scope results to this chat_id.
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
            collection_name = self._safe_collection_name("local", user_id)

            if not VECTOR_DB_CLIENT.has_collection(collection_name):
                return []

            results = VECTOR_DB_CLIENT.search(
                collection_name=collection_name,
                vectors=search_vector,
                limit=limit,
                filter={"chat_id": chat_id},
            )

            if not results or not results.documents:
                return []

            local_memories = []
            for i, doc_list in enumerate(results.documents):
                id_list = results.ids[i] if results.ids and i < len(results.ids) else []
                for j, doc in enumerate(doc_list):
                    if doc and self._is_local_category(doc):
                        mem_id = id_list[j] if j < len(id_list) else "unknown"
                        local_memories.append({"id": mem_id, "content": doc})

            return local_memories

        except Exception as e:
            logger.warning(f"[MemoryExtract] Vector search for local context failed: {e}")
            return []

    async def _vector_upsert(self, collection_name: str, memory_id: str, content: str,
                              created_at: int, request, extra_metadata: dict = None):
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

            metadata = {"created_at": created_at}
            if extra_metadata:
                metadata.update(extra_metadata)

            VECTOR_DB_CLIENT.upsert(
                collection_name=collection_name,
                items=[{
                    "id": memory_id,
                    "text": content,
                    "vector": vec,
                    "metadata": metadata,
                }],
            )
            logger.info(f"[MemoryExtract] Vector DB upsert OK ({collection_name}): {memory_id}")

        except Exception as e:
            logger.warning(f"[MemoryExtract] Vector upsert failed (non-fatal): {type(e).__name__}: {e}")

    def _get_vector_collection_for_content(self, content: str, user_id: str, folder_id: str = None,
                                            chat_id: str = None) -> str:
        """Determine which vector collection a memory belongs to based on its tag.
        Uses hashed collection names to stay within ChromaDB's 63-char limit.
        LOCAL uses a single collection per user (filtered by chat_id metadata).
        """
        if self._is_local_category(content):
            # All LOCAL memories go into one collection per user
            return self._safe_collection_name("local", user_id)
        elif self._is_project_category(content):
            cat = self._get_category(content)
            if ":folder:" in cat:
                import re
                match = re.search(r':folder:([\w-]+)', cat)
                if match:
                    return self._safe_collection_name("folder", user_id, match.group(1))
            return f"user-memory-{user_id}"
        return ""

    # =========================================================================
    # Memory CRUD
    # =========================================================================

    async def _save_memory_internal(self, user_id: str, content: str, request=None,
                                     folder_id: str = None, chat_id: str = None):
        """
        Save memory to SQL. If [PROJECT] or [LOCAL], also upsert to Vector DB.
        """
        try:
            from open_webui.models.memories import Memories
            memory = await asyncio.to_thread(Memories.insert_new_memory, user_id, content)
            if not memory:
                logger.error(f"[MemoryExtract] SQL insert returned None for: {content[:60]}...")
                return None

            logger.info(f"[MemoryExtract] Saved memory to SQL: {content[:80]}...")

            # Upsert to Vector DB if PROJECT or LOCAL
            if request and (self._is_project_category(content) or self._is_local_category(content)):
                collection = self._get_vector_collection_for_content(content, user_id, folder_id, chat_id)
                if collection:
                    extra_meta = {"chat_id": chat_id} if chat_id and self._is_local_category(content) else None
                    await self._vector_upsert(collection, memory.id, content, memory.created_at, request, extra_meta)

            return memory
        except Exception as e:
            logger.error(f"[MemoryExtract] Memory save failed: {type(e).__name__}: {e}")
            return None

    async def _update_memory_internal(self, user_id: str, memory_id: str, content: str, request=None,
                                       folder_id: str = None, chat_id: str = None):
        """Update existing memory in SQL. If [PROJECT] or [LOCAL], also update Vector DB."""
        try:
            from open_webui.models.memories import Memories
            updated = await asyncio.to_thread(
                Memories.update_memory_by_id_and_user_id, memory_id, user_id, content
            )
            if not updated:
                logger.error(f"[MemoryExtract] SQL update failed for memory_id={memory_id}")
                return None

            logger.info(f"[MemoryExtract] Updated memory in SQL: {memory_id}")

            if request and (self._is_project_category(content) or self._is_local_category(content)):
                collection = self._get_vector_collection_for_content(content, user_id, folder_id, chat_id)
                if collection:
                    extra_meta = {"chat_id": chat_id} if chat_id and self._is_local_category(content) else None
                    await self._vector_upsert(collection, memory_id, content, updated.created_at, request, extra_meta)

            return updated
        except Exception as e:
            logger.error(f"[MemoryExtract] Memory update failed: {e}")
            return None

    async def _delete_memory_internal(self, user_id: str, memory_id: str, old_content: str = ""):
        """Delete memory from SQL. If was [PROJECT] or [LOCAL], also delete from Vector DB."""
        try:
            from open_webui.models.memories import Memories
            success = await asyncio.to_thread(
                Memories.delete_memory_by_id_and_user_id, memory_id, user_id
            )
            if not success:
                logger.error(f"[MemoryExtract] SQL delete returned False for memory_id={memory_id}")
                return

            logger.info(f"[MemoryExtract] Deleted memory from SQL: {memory_id}")

            # Clean up vector if was PROJECT or LOCAL
            if self._is_project_category(old_content) or self._is_local_category(old_content):
                try:
                    from open_webui.retrieval.vector.factory import VECTOR_DB_CLIENT
                    collection = self._get_vector_collection_for_content(old_content, user_id)
                    if collection and VECTOR_DB_CLIENT.has_collection(collection):
                        VECTOR_DB_CLIENT.delete(collection_name=collection, ids=[memory_id])
                        logger.info(f"[MemoryExtract] Deleted from Vector DB ({collection}): {memory_id}")
                except Exception as e:
                    logger.warning(f"[MemoryExtract] Vector DB delete failed (non-fatal): {e}")

        except Exception as e:
            logger.error(f"[MemoryExtract] Memory delete failed: {e}")

    # =========================================================================
    # Extraction Context Building
    # =========================================================================

    def _build_extraction_context(self, all_memories: list, relevant_project: list,
                                   folder_id: str = None) -> list:
        """
        Build bounded extraction context for global/folder extraction:
        - All scope-matching [IDENTITY] + [USER] + [FEEDBACK] (always needed for dedup)
        - Top-N [PROJECT] from vector search (bounded)
        Returns combined list of memory dicts.
        """
        global_memories = [m for m in all_memories
                           if self._matches_scope(m["content"], folder_id)
                           and self._get_base_category(m["content"]) in ("[IDENTITY]", "[USER]", "[FEEDBACK]")]

        # Use vector results for PROJECT, deduplicated by ID
        seen_ids = {m["id"] for m in global_memories}
        project_memories = [m for m in relevant_project if m["id"] not in seen_ids]

        combined = global_memories + project_memories
        logger.info(
            f"[MemoryExtract] Extraction context: {len(global_memories)} core + "
            f"{len(project_memories)} project = {len(combined)} total"
        )
        return combined

    def _build_local_extraction_context(self, all_memories: list, relevant_local: list,
                                         chat_id: str) -> list:
        """
        Build extraction context for local extraction:
        - Top-N [LOCAL] from vector search (for dedup)
        Returns list of memory dicts.
        """
        # Get existing local memories for this chat from SQL (for dedup)
        local_prefix = f"[LOCAL:chat:{chat_id}]"
        sql_local = [m for m in all_memories if m["content"].strip().startswith(local_prefix)]

        # Merge with vector results, dedup by ID
        seen_ids = {m["id"] for m in sql_local}
        extra = [m for m in relevant_local if m["id"] not in seen_ids]

        combined = sql_local + extra
        logger.info(f"[MemoryExtract] Local extraction context: {len(combined)} facts for chat {chat_id[:12]}...")
        return combined

    # =========================================================================
    # LLM Extraction Prompts
    # =========================================================================

    async def _extract_facts_via_llm(self, chat_history: str, existing_memories: list,
                                      folder_id: str = None) -> list:
        """
        Calls upstream LLM DIRECTLY to extract structured global/folder facts.
        Only extracts from USER messages.
        """
        import httpx

        api_key = self._get_mws_api_key()
        if not api_key:
            logger.error("[MemoryExtract] No MWS API key configured.")
            return []

        # Format existing memories for the prompt with IDs
        existing_block = ""
        if existing_memories:
            existing_lines = "\n".join(f"[ID: {m['id']}] {m['content']}" for m in existing_memories)
            existing_block = f"""\n\nALREADY KNOWN FACTS (do NOT re-extract these or rephrasings of these):
{existing_lines}\n"""

        current_date = datetime.datetime.now().strftime("%Y-%m-%d")
        # Pre-compute example dates for temporal grounding
        _now = datetime.datetime.now()
        _tomorrow = (_now + datetime.timedelta(days=1)).strftime("%Y-%m-%d")
        _next_week = (_now + datetime.timedelta(weeks=1)).strftime("%Y-%m-%d")
        _last_month = (_now.replace(day=1) - datetime.timedelta(days=1)).strftime("%Y-%m")

        scope_note = ""
        if folder_id:
            scope_note = f"""
FOLDER SCOPE: This chat is inside a folder (ID: {folder_id}).
IMPORTANT: Only [PROJECT] facts are scoped to this folder. Core identity facts are ALWAYS global.
- [IDENTITY] for identity facts (ALWAYS global, never folder-scoped)
- [USER] for preferences (ALWAYS global, never folder-scoped)
- [FEEDBACK] for behavioral rules (ALWAYS global, never folder-scoped)
- [PROJECT:folder:{folder_id}] for project facts (ONLY this is folder-scoped)
"""
        else:
            scope_note = """
GLOBAL SCOPE: This chat is not inside any folder. Facts will be stored globally.
Use standard categories: [IDENTITY], [USER], [PROJECT], [FEEDBACK].
"""

        prompt = f"""You are a memory extraction agent. Analyze the chat history and extract persistent facts about the user.

CRITICAL RULES:
1. ONLY extract facts that the USER (human) has EXPLICITLY stated themselves in their own messages (lines starting with "USER:").
2. NEVER extract anything from ASSISTANT messages. The assistant may fabricate stories, roleplay, or make up details — these are NOT real facts about the user.
3. If the assistant says "I have a cat" or "my name is X" — that is the AI talking about itself, NOT a user fact. Ignore it completely.
4. Only extract information the user directly confirmed or volunteered about themselves.

TEMPORAL GROUNDING (TODAY IS {current_date}):
CRITICAL: If the user mentions relative time, you MUST convert it to an absolute date in the fact.
Examples:
- User says "I have a meeting tomorrow" → fact: "Meeting on {_tomorrow}"
- User says "through a week I have a meeting" → fact: "Meeting on {_next_week}"
- User says "last month I started a new job" → fact: "Started a new job in {_last_month}"
NEVER store relative time like "tomorrow", "next week", "recently" — always convert to absolute dates.
{scope_note}
Use the following strict taxonomy categories:
- [IDENTITY]: Foundational facts about the user's life (Name, Profession, Location, Family, Spoken Languages). THESE CAN CHANGE — use UPDATE if corrected.
- [USER]: General preferences, tastes, or minor details (e.g., "Likes dark mode", "Prefers Python over JS").
- [PROJECT]: Facts about the project architecture, tech stack, and current state. Treat as a living summary. Use UPDATE to overwrite changed decisions.
- [FEEDBACK]: Explicit corrections or behavioral preferences (e.g., "Don't write comments", "Always use pytest").

ACTIONS:
- ADD: New fact not in known facts.
- UPDATE: User corrects a known fact. Provide exact `target_id`.
- DELETE: User EXPLICITLY denies or revokes a known fact. Provide exact `target_id`.

SAFETY:
- DELETE is EXTREMELY rare. Only when user explicitly says "That's wrong" or "Remove that memory".
- NEVER delete facts just because they weren't mentioned.
- NEVER delete more than 1 fact per response.
- When in doubt, do NOT delete. Return [] instead.
{existing_block}
Chat History:
{chat_history}

Output ONLY a valid JSON array. Each object MUST include a "reason" key explaining why. If nothing to extract, return [].
[
  {{"reason": "User stated their name", "action": "ADD", "category": "[IDENTITY]", "fact": "fact text"}},
  {{"reason": "User corrected DB choice", "action": "UPDATE", "target_id": "id", "category": "[PROJECT]", "fact": "updated text"}},
  {{"reason": "User said they no longer have a dog", "action": "DELETE", "target_id": "id"}}
]"""

        return await self._call_extraction_llm(prompt)

    async def _extract_local_facts_via_llm(self, chat_history: str, existing_local: list,
                                            chat_id: str) -> list:
        """
        Calls upstream LLM DIRECTLY to extract LOCAL (per-chat) facts.
        Extracts from BOTH user + AI messages, but ONLY when user confirms AI output.
        Focuses on: decisions, architecture, solutions, technical choices.
        """
        import httpx

        api_key = self._get_mws_api_key()
        if not api_key:
            logger.error("[MemoryExtract] No MWS API key configured.")
            return []

        existing_block = ""
        if existing_local:
            existing_lines = "\n".join(f"[ID: {m['id']}] {m['content']}" for m in existing_local)
            existing_block = f"""\n\nALREADY KNOWN LOCAL FACTS (do NOT re-extract these):
{existing_lines}\n"""

        current_date = datetime.datetime.now().strftime("%Y-%m-%d")

        prompt = f"""You are a local chat memory extraction agent. Extract technical decisions, architecture choices, and solutions from this conversation that should be remembered within this chat session.

CRITICAL RULES:
1. Extract DECISIONS, ARCHITECTURE, SOLUTIONS, and TECHNICAL CHOICES made in this conversation.
2. You may extract from BOTH USER and ASSISTANT messages, BUT with this strict condition:
   - ONLY extract from the Assistant's message IF the User's subsequent reply EXPLICITLY accepts, builds upon, or confirms it.
   - Acceptance signals: "great", "thanks", "that worked", "let's move on", "good", "perfect", user asking follow-up questions about the solution, user requesting next steps.
   - Rejection signals: "that's wrong", "error", "doesn't work", "try again", "no", user correcting the AI.
   - If the User rejects or corrects the AI, DO NOT extract the Assistant's proposed solution.
3. Focus on WHAT was decided/built, not HOW the conversation went.
4. Keep facts technical and specific — include exact names, paths, technologies, patterns.

BAD examples (too vague):
- "Worked on authentication" 
- "Discussed database design"

GOOD examples (specific and useful):
- "Implemented JWT auth via /api/v1/auth endpoint using MWS GPT API key"
- "Database schema: users table has id, email, name, is_active columns"
- "Architecture: three-filter pipeline auto_router → context_inject → memory_extract"
- "Deadlock fix: extraction LLM calls go directly to MWS API, not through OpenWebUI"

TEMPORAL GROUNDING (TODAY IS {current_date}):
CRITICAL: Convert ALL relative dates to absolute dates. Never store "tomorrow", "next week" etc.

All extracted facts will be tagged as [LOCAL:chat:{chat_id}].

ACTIONS:
- ADD: New fact/decision not yet recorded.
- UPDATE: A previous decision was changed. Provide exact `target_id`.
- DELETE: A decision was explicitly reverted. Provide exact `target_id`.
{existing_block}
Chat History:
{chat_history}

Output ONLY a valid JSON array. Each object MUST include a "reason" key. If nothing to extract, return [].
[
  {{"reason": "User confirmed the hybrid memory architecture", "action": "ADD", "fact": "Using hybrid memory: SQL for global facts, VectorDB for semantic project search"}},
  {{"reason": "Architecture decision was changed from X to Y", "action": "UPDATE", "target_id": "id", "fact": "updated decision"}}
]"""

        return await self._call_extraction_llm(prompt)

    async def _call_extraction_llm(self, prompt: str) -> list:
        """Common LLM call for extraction with retry on transfer errors."""
        import httpx

        api_key = self._get_mws_api_key()
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

        max_retries = 2
        for attempt in range(max_retries + 1):
            try:
                async with httpx.AsyncClient(
                    timeout=httpx.Timeout(60.0, connect=10.0)
                ) as client:
                    response = await client.post(
                        f"{self.valves.mws_api_base_url}/chat/completions",
                        json=payload,
                        headers=headers,
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
                    break  # Don't retry on HTTP errors (4xx/5xx)
            except (httpx.RemoteProtocolError, httpx.ReadError, httpx.ConnectError) as e:
                if attempt < max_retries:
                    logger.warning(f"[MemoryExtract] LLM call transfer error (attempt {attempt+1}), retrying: {e}")
                    await asyncio.sleep(1)
                    continue
                logger.error(f"[MemoryExtract] LLM call failed after {max_retries+1} attempts: {e}")
            except Exception as e:
                logger.error(f"[MemoryExtract] LLM call failed: {type(e).__name__}: {e}")
                break

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

    # =========================================================================
    # Main Outlet Pipeline
    # =========================================================================

    async def outlet(self, body: dict, __user__: Optional[dict] = None, __request__=None,
                     __chat_id__: str = None, __metadata__: dict = None) -> dict:
        """
        OUTLET: Runs after AI responds. Analyzes history and extracts memories.

        Three-scope extraction:
        1. Global/Folder facts (from user messages only)
        2. Local facts (from both user + AI, with confirmation detection)
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

        # Determine scope
        chat_id = __chat_id__ or (__metadata__.get("chat_id") if __metadata__ else None)

        # Resolve folder_id from DB (OpenWebUI middleware does NOT propagate it to metadata)
        folder_id = None
        if chat_id and user_id:
            try:
                from open_webui.models.chats import Chats
                folder_id = Chats.get_chat_folder_id(chat_id, user_id)
                logger.info(f"[MemoryExtract] DB folder_id lookup: chat={chat_id[:12]}... → folder_id={folder_id}")
            except AttributeError:
                try:
                    from open_webui.models.chats import Chats
                    chat_obj = Chats.get_chat_by_id_and_user_id(chat_id, user_id)
                    if chat_obj:
                        folder_id = getattr(chat_obj, 'folder_id', None)
                        logger.info(f"[MemoryExtract] Fallback chat lookup: folder_id={folder_id}")
                except Exception as e2:
                    logger.warning(f"[MemoryExtract] Fallback chat lookup failed: {e2}")
            except Exception as e:
                logger.warning(f"[MemoryExtract] Could not resolve folder_id from DB: {type(e).__name__}: {e}")
        if not folder_id:
            folder_id = __metadata__.get("folder_id") if __metadata__ else None
            if folder_id:
                logger.info(f"[MemoryExtract] Using metadata folder_id={folder_id}")

        folder_label = f"folder={folder_id[:12]}" if folder_id else "global"
        chat_label = f"chat={chat_id[:12]}" if chat_id else "unknown"
        logger.info(f"[MemoryExtract] Scope: {folder_label}, {chat_label}")

        # ── Build chat history window ──
        window_size = max(self.valves.extraction_interval * 2, 10)
        context_msgs = messages[-window_size:]

        # For global/folder: only USER messages
        global_chat_history = "\n".join([
            f"{m['role'].upper()}: {m['content']}"
            for m in context_msgs
            if m.get('role') == 'user' and isinstance(m.get('content'), str)
        ])

        # For local: BOTH user + AI messages (for confirmation detection)
        # EXCLUDE system messages — they contain injected memory context
        local_chat_history = "\n".join([
            f"{m['role'].upper()}: {m['content']}"
            for m in context_msgs
            if m.get('role') in ('user', 'assistant') and isinstance(m.get('content'), str)
        ])

        if not global_chat_history:
            return body

        # ── Fetch all memories from SQL ──
        existing_memories = await asyncio.to_thread(self._get_existing_memories, user_id)
        logger.info(f"[MemoryExtract] User has {len(existing_memories)} existing memories")

        # ══════════════════════════════════════════════════════════
        # PASS 1: Global/Folder fact extraction (user messages only)
        # ══════════════════════════════════════════════════════════

        # Get relevant PROJECT facts via vector search (scoped)
        relevant_project = []
        if __request__:
            relevant_project = await self._vector_search_project(
                user_id, global_chat_history[:2000],
                __request__,
                limit=self.valves.max_project_context,
                folder_id=folder_id
            )

        if not relevant_project:
            # Fallback: last N scope-matching [PROJECT] from SQL
            all_project = [m for m in existing_memories
                           if self._is_project_category(m["content"])
                           and self._matches_scope(m["content"], folder_id)]
            relevant_project = all_project[-self.valves.max_project_context:]

        extraction_context = self._build_extraction_context(existing_memories, relevant_project, folder_id)

        # Call global/folder extraction LLM
        global_facts = await self._extract_facts_via_llm(global_chat_history, extraction_context, folder_id)

        # Process global/folder facts
        await self._process_extracted_facts(
            global_facts, user_id, existing_memories, folder_id=folder_id,
            chat_id=chat_id, request=__request__, scope_label="global/folder"
        )

        # ══════════════════════════════════════════════════════════
        # PASS 2: Local fact extraction (both user + AI messages)
        # ══════════════════════════════════════════════════════════

        if self.valves.enable_local_memory and chat_id and local_chat_history:
            # Get relevant LOCAL facts via vector search
            relevant_local = []
            if __request__:
                relevant_local = await self._vector_search_local(
                    user_id, chat_id, local_chat_history[:2000],
                    __request__,
                    limit=self.valves.max_local_context
                )

            local_context = self._build_local_extraction_context(
                existing_memories, relevant_local, chat_id
            )

            # Call local extraction LLM
            local_facts = await self._extract_local_facts_via_llm(
                local_chat_history, local_context, chat_id
            )

            # Process local facts
            await self._process_extracted_facts(
                local_facts, user_id, existing_memories, folder_id=folder_id,
                chat_id=chat_id, request=__request__, scope_label="local",
                is_local=True
            )

        return body

    async def _process_extracted_facts(self, facts: list, user_id: str, existing_memories: list,
                                        folder_id: str = None, chat_id: str = None,
                                        request=None, scope_label: str = "", is_local: bool = False):
        """Process extracted facts: ADD, UPDATE, DELETE with safety checks."""
        if not facts:
            return

        saved_count = 0
        updated_count = 0
        deleted_count = 0
        skipped_count = 0

        valid_ids = {m["id"]: m["content"] for m in existing_memories}

        for item in facts:
            action = item.get("action", "ADD").upper()
            target_id = item.get("target_id", "")

            if action == "DELETE":
                if deleted_count >= self.valves.max_deletes_per_cycle:
                    logger.warning(
                        f"[MemoryExtract][{scope_label}] DELETE cap reached. "
                        f"Refusing further deletes. target_id={target_id[:12] if target_id else 'none'}..."
                    )
                    skipped_count += 1
                    continue

                if target_id and target_id in valid_ids:
                    old_content = valid_ids[target_id]
                    await self._delete_memory_internal(user_id, target_id, old_content)
                    del valid_ids[target_id]
                    deleted_count += 1
                elif target_id:
                    logger.warning(f"[MemoryExtract][{scope_label}] DELETE rejected — target_id not found")
                    skipped_count += 1
                continue

            fact = item.get("fact", "")
            if not fact:
                continue

            # Strip any tag prefix LLM may have included (prevents double-tagging)
            import re
            fact = re.sub(r'^\[(?:IDENTITY|USER|PROJECT|FEEDBACK|LOCAL)(?:[^\]]+)?\]\s*', '', fact.strip())
            if not fact:
                continue

            # Build tagged content
            if is_local:
                content = f"[LOCAL:chat:{chat_id}] {fact}"
            else:
                category_raw = item.get("category", "[PROJECT]")
                # Strip brackets and scope for clean category name
                cat_name = category_raw.replace("[", "").replace("]", "").split(":")[0]
                # Only PROJECT gets folder-scoped; core facts always global
                scope_id = folder_id if cat_name == "PROJECT" else None
                content = self._tag_content(cat_name, fact, scope_id)

            if action == "UPDATE":
                if target_id and target_id in valid_ids:
                    old_content = valid_ids[target_id]
                    old_collection = self._get_vector_collection_for_content(old_content, user_id)
                    new_collection = self._get_vector_collection_for_content(content, user_id, folder_id, chat_id)

                    # Clean up old vector entry if collection changed
                    if old_collection and old_collection != new_collection:
                        try:
                            from open_webui.retrieval.vector.factory import VECTOR_DB_CLIENT
                            if VECTOR_DB_CLIENT.has_collection(old_collection):
                                VECTOR_DB_CLIENT.delete(collection_name=old_collection, ids=[target_id])
                                logger.info(f"[MemoryExtract] Cleaned orphan vector for collection change")
                        except Exception as e:
                            logger.warning(f"[MemoryExtract] Vector cleanup failed: {e}")

                    await self._update_memory_internal(user_id, target_id, content, request, folder_id, chat_id)
                    valid_ids[target_id] = content
                    updated_count += 1
                elif target_id:
                    logger.warning(f"[MemoryExtract][{scope_label}] UPDATE rejected — target_id not found")
                    skipped_count += 1
                else:
                    logger.warning(f"[MemoryExtract][{scope_label}] UPDATE missing target_id")
                    skipped_count += 1
                continue

            # Default is ADD
            if self._is_duplicate(content, existing_memories):
                logger.info(f"[MemoryExtract][{scope_label}] Skipped duplicate: {content[:80]}...")
                skipped_count += 1
                continue

            result = await self._save_memory_internal(user_id, content, request, folder_id, chat_id)
            if result:
                existing_memories.append({"id": result.id, "content": content})
                valid_ids[result.id] = content
            saved_count += 1

        logger.info(
            f"[MemoryExtract][{scope_label}] Summary: {saved_count} ADD, {updated_count} UPDATE, "
            f"{deleted_count} DELETE, {skipped_count} SKIPPED"
        )
