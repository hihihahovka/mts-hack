"""
Context Inject Filter (Three-Scope Architecture)
===================================================
OpenWebUI Filter Function (inlet) that retrieves long-term memory context
and injects it into the system prompt.

THREE SCOPES:
  1. GLOBAL (chats without folder):
     [IDENTITY] + [USER] + [FEEDBACK] from SQL (always global, always injected)
     [PROJECT] from Vector DB semantic search (contextual, top-N)

  2. FOLDER (chats inside a folder — PROJECT isolated, core facts cascade):
     [IDENTITY] + [USER] + [FEEDBACK] = always global, cascade into all folders
     [PROJECT:folder:X] from Vector DB (collection: folder-{md5}, STRICTLY isolated)

  3. LOCAL (per-chat):
     [LOCAL:chat:X] from Vector DB (single collection: local-{md5(user_id)}, filtered by chat_id)
     + 5 most recent from SQL. Chat-specific decisions/solutions via RAG.

INJECTION FORMAT:
  System Prompt = [FEEDBACK] + [IDENTITY] + [USER] + [PROJECT](top-N) + [LOCAL](RAG)
"""

import datetime
import hashlib
import logging
from pydantic import BaseModel, Field
from typing import Optional

logger = logging.getLogger(__name__)


class Filter:
    class Valves(BaseModel):
        enable_context_injection: bool = Field(
            default=True,
            description="Enable automatic memory injection."
        )
        enable_global_memory: bool = Field(
            default=True,
            description="Enable global memory injection (for chats not in a folder)."
        )
        enable_local_memory: bool = Field(
            default=True,
            description="Enable per-chat local memory injection (decisions, solutions)."
        )
        max_user_memories: int = Field(
            default=20,
            description="Maximum number of [USER] memories to inject."
        )
        max_project_memories: int = Field(
            default=10,
            description="Maximum number of [PROJECT] memories to inject via semantic search."
        )
        project_fallback_count: int = Field(
            default=10,
            description="Number of recent [PROJECT] facts to inject when Vector DB is unavailable."
        )
        max_local_relevant: int = Field(
            default=10,
            description="Top-N semantically relevant [LOCAL] facts to inject per chat."
        )
        max_local_recent: int = Field(
            default=5,
            description="Most recent [LOCAL] facts to inject per chat (chronological context)."
        )

    def __init__(self):
        self.valves = self.Valves()

    # =========================================================================
    # Helpers
    # =========================================================================

    def _get_category(self, content: str) -> str:
        """Extract full category tag from memory content."""
        import re
        match = re.match(r'(\[(?:IDENTITY|USER|PROJECT|FEEDBACK|LOCAL)(?::[^\]]+)?\])', content.strip())
        if match:
            return match.group(1)
        return ""

    def _get_base_category(self, content: str) -> str:
        """Get base category. [PROJECT:folder:abc] -> [PROJECT], [LOCAL:chat:xyz] -> [LOCAL]."""
        import re
        match = re.match(r'(\[(?:IDENTITY|USER|PROJECT|FEEDBACK|LOCAL))', content.strip())
        if match:
            return match.group(1) + "]"
        return ""

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

    def _strip_tag(self, content: str) -> str:
        """Remove the category tag prefix from content."""
        import re
        return re.sub(r'^\[(?:IDENTITY|USER|PROJECT|FEEDBACK|LOCAL)(?::[^\]]+)?\]\s*', '', content.strip())

    # =========================================================================
    # Memory Retrieval
    # =========================================================================

    def _get_user_memories(self, user_id: str) -> list:
        """
        Fetch memories from OpenWebUI's internal Memories model.
        Returns list of dicts with id and content.
        """
        try:
            from open_webui.models.memories import Memories
            memories = Memories.get_memories_by_user_id(user_id)
            if memories is None:
                logger.warning("[ContextInject] Memories.get_memories_by_user_id returned None")
                return []
            result = [
                {"id": m.id, "content": m.content, "updated_at": getattr(m, 'updated_at', None)}
                for m in memories if hasattr(m, 'content') and m.content
            ]
            logger.info(f"[ContextInject] Fetched {len(result)} total memories for user {user_id[:8]}...")
            return result
        except ImportError as e:
            logger.error(f"[ContextInject] Cannot import Memories model: {e}.")
        except Exception as e:
            logger.error(f"[ContextInject] Failed to fetch memories: {type(e).__name__}: {e}")

        return []



    async def _search_local_memories_vector(self, user_id: str, chat_id: str, query_text: str, request,
                                             limit: int = 10) -> list:
        """
        Semantic search for [LOCAL] memories in the user's single local collection.
        Uses metadata filter to scope results to this chat_id.
        Returns list of document strings (stripped of tags), or empty list.
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

            docs = []
            for i, doc_list in enumerate(results.documents):
                for j, doc in enumerate(doc_list):
                    if doc and self._get_base_category(doc) == "[LOCAL]":
                        docs.append(self._strip_tag(doc))

            logger.info(f"[ContextInject] Vector search returned {len(docs)} [LOCAL] memories for chat {chat_id[:12]}...")
            return docs

        except Exception as e:
            logger.warning(f"[ContextInject] Local vector search failed: {type(e).__name__}: {e}")
            return []

    def _get_recent_local_memories_sql(self, all_memories: list, chat_id: str, limit: int = 5) -> list:
        """
        Get most recent [LOCAL:chat:X] memories from SQL for chronological context.
        Returns list of content strings (stripped of tags).
        """
        prefix = f"[LOCAL:chat:{chat_id}]"
        local_mems = [m for m in all_memories if m["content"].strip().startswith(prefix)]
        # SQL memories are ordered by insertion — take last N
        recent = local_mems[-limit:]
        return [self._strip_tag(m["content"]) for m in recent]

    # =========================================================================
    # Formatting
    # =========================================================================

    def _format_memory_context(self, identity_facts: list, user_facts: list,
                                feedback_facts: list, project_facts: list,
                                local_facts: list = None) -> str:
        """Formats categorized memory lists into a structured system prompt block."""
        if not identity_facts and not user_facts and not feedback_facts and not project_facts and not local_facts:
            return ""

        import datetime
        now = datetime.datetime.now()
        current_date = now.strftime("%Y-%m-%d %H:%M")

        blocks = []
        blocks.append("--- [MEMORY CONTEXT START] ---")
        blocks.append(f"Current date/time: {current_date}")
        blocks.append("The following information has been recalled from past interactions.")
        blocks.append("Each fact may include (saved: DATE) — use this to calculate relative time.")

        # ALWAYS inject all [FEEDBACK] — behavioral rules are sacred
        if feedback_facts:
            blocks.append("\n## Behavioral Guidelines (Always Active):")
            for f in feedback_facts:
                blocks.append(f"- {f}")

        # ALWAYS inject all [IDENTITY] — core facts never evicted
        if identity_facts:
            blocks.append("\n## User Identity:")
            for f in identity_facts:
                blocks.append(f"- {f}")

        # Inject [USER] with cap
        if user_facts:
            blocks.append("\n## User Preferences:")
            for f in user_facts[-self.valves.max_user_memories:]:
                blocks.append(f"- {f}")

        # Inject [PROJECT] — semantically relevant, chronologically sorted
        if project_facts:
            blocks.append("\n## Relevant Project Context (chronological):")
            for f in project_facts:
                blocks.append(f"- {f}")

        # Inject [LOCAL] — this chat's decisions and solutions
        if local_facts:
            blocks.append("\n## This Chat's Context (decisions & solutions made here):")
            for f in local_facts:
                blocks.append(f"- {f}")

        blocks.append("--- [MEMORY CONTEXT END] ---")

        return "\n".join(blocks)

    # =========================================================================
    # Main Inlet Pipeline
    # =========================================================================

    async def inlet(self, body: dict, __user__: Optional[dict] = None, __request__=None,
                    __chat_id__: str = None, __metadata__: dict = None) -> dict:
        """
        INLET: Runs before LLM call.
        Three-scope memory injection:
        1. Global OR Folder scope (mutually exclusive, based on folder_id)
        2. Local scope (per-chat, always if enabled)
        """
        if not self.valves.enable_context_injection or not __user__:
            return body

        user_id = __user__.get("id")
        if not user_id:
            logger.warning("[ContextInject] No user id found, memory injection skipped.")
            return body

        messages = body.get("messages", [])
        if not messages:
            return body

        # Determine scope
        chat_id = __chat_id__ or (__metadata__.get("chat_id") if __metadata__ else None)

        # Resolve folder_id from DB (OpenWebUI middleware does NOT propagate it to metadata)
        folder_id = None
        if chat_id and user_id:
            try:
                from open_webui.models.chats import Chats
                # Primary: lightweight column query
                folder_id = Chats.get_chat_folder_id(chat_id, user_id)
                logger.info(f"[ContextInject] DB folder_id lookup: chat={chat_id[:12]}... → folder_id={folder_id}")
            except AttributeError:
                # Fallback: get_chat_folder_id may not exist in this OpenWebUI version
                try:
                    from open_webui.models.chats import Chats
                    chat_obj = Chats.get_chat_by_id_and_user_id(chat_id, user_id)
                    if chat_obj:
                        folder_id = getattr(chat_obj, 'folder_id', None)
                        logger.info(f"[ContextInject] Fallback chat lookup: folder_id={folder_id}")
                except Exception as e2:
                    logger.warning(f"[ContextInject] Fallback chat lookup failed: {e2}")
            except Exception as e:
                logger.warning(f"[ContextInject] Could not resolve folder_id from DB: {type(e).__name__}: {e}")
        # Fallback: metadata (temporary chats / first message may have it)
        if not folder_id:
            folder_id = __metadata__.get("folder_id") if __metadata__ else None
            if folder_id:
                logger.info(f"[ContextInject] Using metadata folder_id={folder_id}")

        scope_label = f"folder={folder_id[:12]}" if folder_id else "global"
        chat_label = f"chat={chat_id[:12]}" if chat_id else "unknown"
        logger.info(f"[ContextInject] Scope: {scope_label}, {chat_label}")

        # 1. Fetch ALL memories from SQL
        import asyncio
        raw_memories = await asyncio.to_thread(self._get_user_memories, user_id)
        if not raw_memories and not (self.valves.enable_local_memory and chat_id):
            return body

        # 2. Categorize by scope — filter based on folder_id
        identity_facts = []
        user_facts = []
        feedback_facts = []
        project_facts_sql = []

        for mem in raw_memories:
            content = mem["content"].strip()
            base_cat = self._get_base_category(content)

            # Skip if doesn't match scope
            if not self._matches_scope(content, folder_id):
                continue

            # Skip LOCAL here — handled separately
            if base_cat == "[LOCAL]":
                continue

            stripped = self._strip_tag(content)

            # Append save date for temporal reasoning
            updated_at = mem.get("updated_at")
            if updated_at:
                import datetime
                if isinstance(updated_at, (int, float)):
                    dt = datetime.datetime.fromtimestamp(updated_at)
                elif isinstance(updated_at, datetime.datetime):
                    dt = updated_at
                else:
                    dt = None
                if dt:
                    stripped = f"{stripped} (saved: {dt.strftime('%Y-%m-%d')})"

            if base_cat == "[IDENTITY]":
                identity_facts.append(stripped)
            elif base_cat == "[USER]":
                user_facts.append(stripped)
            elif base_cat == "[FEEDBACK]":
                feedback_facts.append(stripped)
            elif base_cat == "[PROJECT]":
                project_facts_sql.append(stripped)

        # 3. Get [PROJECT] facts (Chronological SQL Only)
        project_facts = []
        if project_facts_sql:
            project_facts = project_facts_sql[-self.valves.project_fallback_count:]
            logger.info(f"[ContextInject] SQL fetching {len(project_facts)} [PROJECT] memories")

        # 4. Get [LOCAL] facts — semantic search + recent SQL, deduplicated
        local_facts = []
        if self.valves.enable_local_memory and chat_id:
            local_semantic = []
            if __request__:
                latest_user_msg = ""
                for m in reversed(messages):
                    if m.get("role") == "user" and isinstance(m.get("content"), str):
                        latest_user_msg = m["content"]
                        break

                if latest_user_msg:
                    local_semantic = await self._search_local_memories_vector(
                        user_id, chat_id, latest_user_msg, __request__,
                        limit=self.valves.max_local_relevant
                    )

            # Most recent from SQL
            local_recent = self._get_recent_local_memories_sql(
                raw_memories, chat_id,
                limit=self.valves.max_local_recent
            )

            # Deduplicate: union of semantic + recent, preserving order
            seen = set()
            for fact in local_semantic:
                normalized = fact.strip().lower()
                if normalized not in seen:
                    local_facts.append(fact)
                    seen.add(normalized)
            for fact in local_recent:
                normalized = fact.strip().lower()
                if normalized not in seen:
                    local_facts.append(fact)
                    seen.add(normalized)

            if local_facts:
                logger.info(
                    f"[ContextInject] Local memory: {len(local_semantic)} semantic + "
                    f"{len(local_recent)} recent = {len(local_facts)} deduplicated"
                )

        # 5. Format and inject
        memory_block = self._format_memory_context(
            identity_facts, user_facts, feedback_facts, project_facts, local_facts
        )

        if not memory_block:
            return body

        # Inject into first system message, or prepend as new system message
        system_msg_index = next((i for i, m in enumerate(messages) if m.get("role") == "system"), -1)

        if system_msg_index >= 0:
            original = messages[system_msg_index].get("content", "")
            messages[system_msg_index]["content"] = f"{memory_block}\n\n{original}"
        else:
            messages.insert(0, {"role": "system", "content": memory_block})

        body["messages"] = messages

        core_count = len(identity_facts) + len(user_facts) + len(feedback_facts)
        logger.info(
            f"[ContextInject] Injected {core_count} core ({len(identity_facts)} identity) + "
            f"{len(project_facts)} project (recency) + "
            f"{len(local_facts)} local memories | scope={scope_label}"
        )

        return body
