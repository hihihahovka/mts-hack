"""
Context Inject Filter (Hybrid Architecture)
=============================================
OpenWebUI Filter Function (inlet) that retrieves long-term memory context
and injects it into the system prompt.

ARCHITECTURE:
- [IDENTITY] + [USER] + [FEEDBACK] = SQL (always injected, global core memory)
- [PROJECT] = Vector DB semantic search (contextual, top-N relevant)
- Fallback: if Vector DB unavailable, [PROJECT] falls back to SQL recency

Uses Claude-Code style Taxonomy: [IDENTITY], [USER], [PROJECT], [FEEDBACK].
"""

import datetime
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

    def __init__(self):
        self.valves = self.Valves()

    def _get_user_memories(self, user_id: str) -> list:
        """
        Fetch memories from OpenWebUI's internal Memories model.
        Returns list of dicts with id and content.
        """
        try:
            from open_webui.models.memories import Memories
            memories = Memories.get_memories_by_user_id(user_id)
            if memories is None:
                logger.warning("[ContextInject] Memories.get_memories_by_user_id returned None (possible DB error)")
                return []
            result = [{"id": m.id, "content": m.content} for m in memories if hasattr(m, 'content') and m.content]
            logger.info(f"[ContextInject] Fetched {len(result)} total memories for user {user_id[:8]}...")
            return result
        except ImportError as e:
            logger.error(f"[ContextInject] Cannot import Memories model: {e}.")
        except Exception as e:
            logger.error(f"[ContextInject] Failed to fetch memories: {type(e).__name__}: {e}")

        return []

    async def _search_project_memories_vector(self, user_id: str, query_text: str, request, limit: int = 5) -> list:
        """
        Semantic search for [PROJECT] memories via Vector DB.
        Uses request.app.state.EMBEDDING_FUNCTION for embeddings.
        Returns list of document strings, or empty list on failure.
        """
        try:
            from open_webui.retrieval.vector.factory import VECTOR_DB_CLIENT

            embedding_function = request.app.state.EMBEDDING_FUNCTION
            if not embedding_function:
                logger.warning("[ContextInject] EMBEDDING_FUNCTION not configured, skipping vector search")
                return []

            # Generate embedding for query — this is async
            vector = await embedding_function(query_text)

            if not vector:
                logger.warning("[ContextInject] Embedding generation returned empty result")
                return []

            # Ensure vector is wrapped in list for search API
            search_vector = [vector] if not isinstance(vector[0], list) else vector

            collection_name = f"user-memory-{user_id}"

            # Check if collection exists before querying
            if not VECTOR_DB_CLIENT.has_collection(collection_name):
                logger.info(f"[ContextInject] No vector collection found for user, skipping semantic search")
                return []

            results = VECTOR_DB_CLIENT.search(
                collection_name=collection_name,
                vectors=search_vector,
                limit=limit,
            )

            if not results or not results.documents:
                return []

            # Collect documents with their creation timestamps for chronological sorting
            retrieved_items = []
            for i, doc_list in enumerate(results.documents):
                meta_list = results.metadatas[i] if results.metadatas and i < len(results.metadatas) else []
                for j, doc in enumerate(doc_list):
                    if doc and doc.startswith("[PROJECT]"):
                        meta = meta_list[j] if j < len(meta_list) and isinstance(meta_list[j], dict) else {}
                        created_at = meta.get("created_at", 0)
                        retrieved_items.append({
                            "content": doc.replace("[PROJECT]", "").strip(),
                            "timestamp": created_at
                        })

            # Sort chronologically (oldest → newest) to preserve project timeline
            retrieved_items.sort(key=lambda x: x["timestamp"])

            # Format with human-readable dates so AI understands timeline
            docs = []
            for item in retrieved_items:
                if item["timestamp"] > 0:
                    date_str = datetime.datetime.fromtimestamp(item["timestamp"]).strftime('%Y-%m-%d')
                    docs.append(f"[{date_str}] {item['content']}")
                else:
                    docs.append(item["content"])

            logger.info(f"[ContextInject] Vector search returned {len(docs)} chronologically sorted [PROJECT] memories")
            return docs

        except Exception as e:
            logger.warning(f"[ContextInject] Vector search failed (falling back to SQL): {type(e).__name__}: {e}")
            return []

    def _format_memory_context(self, identity_facts: list, user_facts: list, feedback_facts: list, project_facts: list) -> str:
        """Formats categorized memory lists into a structured system prompt block."""
        if not identity_facts and not user_facts and not feedback_facts and not project_facts:
            return ""

        blocks = []
        blocks.append("--- [MEMORY CONTEXT START] ---")
        blocks.append("The following information has been recalled from past interactions:")

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

        # Inject [USER] with cap — rolling preferences
        if user_facts:
            blocks.append("\n## User Preferences:")
            for f in user_facts[-self.valves.max_user_memories:]:
                blocks.append(f"- {f}")

        # Inject [PROJECT] — semantically relevant, chronologically sorted
        if project_facts:
            blocks.append("\n## Relevant Project Context (chronological):")
            for f in project_facts:
                blocks.append(f"- {f}")

        blocks.append("--- [MEMORY CONTEXT END] ---")

        return "\n".join(blocks)

    async def inlet(self, body: dict, __user__: Optional[dict] = None, __request__=None) -> dict:
        """
        INLET: Runs before LLM call.
        Injects global core memories ([USER]/[FEEDBACK]) from SQL
        and semantically relevant [PROJECT] memories from Vector DB.
        """
        if not self.valves.enable_context_injection or not __user__:
            return body

        user_id = __user__.get("id")
        if not user_id:
            logger.warning("[ContextInject] No user id found in __user__, memory injection skipped.")
            return body

        messages = body.get("messages", [])
        if not messages:
            return body

        # 1. Fetch ALL memories from SQL
        import asyncio
        raw_memories = await asyncio.to_thread(self._get_user_memories, user_id)
        if not raw_memories:
            return body

        # 2. Categorize — separate by priority tier
        identity_facts = []
        user_facts = []
        feedback_facts = []
        project_facts_sql = []

        for mem in raw_memories:
            content = mem["content"].strip()
            if content.startswith("[IDENTITY]"):
                identity_facts.append(content.replace("[IDENTITY]", "").strip())
            elif content.startswith("[USER]"):
                user_facts.append(content.replace("[USER]", "").strip())
            elif content.startswith("[FEEDBACK]"):
                feedback_facts.append(content.replace("[FEEDBACK]", "").strip())
            elif content.startswith("[PROJECT]"):
                project_facts_sql.append(content.replace("[PROJECT]", "").strip())
            # Skip uncategorized — they shouldn't exist in new system

        # 3. Get [PROJECT] facts — try Vector DB semantic search first, else SQL fallback
        project_facts = []
        vector_search_succeeded = False

        if project_facts_sql and __request__:
            # Find latest user message for semantic query
            latest_user_msg = ""
            for m in reversed(messages):
                if m.get("role") == "user" and isinstance(m.get("content"), str):
                    latest_user_msg = m["content"]
                    break

            if latest_user_msg:
                vector_results = await self._search_project_memories_vector(
                    user_id, latest_user_msg, __request__,
                    limit=self.valves.max_project_memories
                )
                if vector_results:
                    # Strip [PROJECT] prefix from vector results
                    project_facts = [doc.replace("[PROJECT]", "").strip() for doc in vector_results]
                    vector_search_succeeded = True

        if not vector_search_succeeded and project_facts_sql:
            # Fallback: most recent [PROJECT] facts from SQL
            project_facts = project_facts_sql[-self.valves.project_fallback_count:]
            logger.info(f"[ContextInject] Using SQL fallback for {len(project_facts)} [PROJECT] memories")

        # 4. Format and inject
        memory_block = self._format_memory_context(identity_facts, user_facts, feedback_facts, project_facts)

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

        global_count = len(identity_facts) + len(user_facts) + len(feedback_facts)
        logger.info(
            f"[ContextInject] Injected {global_count} global ({len(identity_facts)} identity) + {len(project_facts)} project "
            f"({'semantic' if vector_search_succeeded else 'recency'}) memories"
        )

        return body
