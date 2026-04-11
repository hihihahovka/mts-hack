"""
Context Inject Filter
=====================
OpenWebUI Filter Function (inlet) that automatically retrieves long-term 
memory context for the user and injects it into the system prompt.

Uses Claude-Code style Taxonomy parsing: [USER], [PROJECT], [FEEDBACK].
"""

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
        max_memories: int = Field(
            default=15,
            description="Maximum number of memories to fetch."
        )

    def __init__(self):
        self.valves = self.Valves()

    def _get_user_memories(self, user_id: str) -> list:
        """
        Fetch memories from OpenWebUI's internal Memories model.
        Tries the internal ORM import; logs clearly on failure.
        """
        try:
            from open_webui.models.memories import Memories
            memories = Memories.get_memories_by_user_id(user_id)
            if memories is None:
                # get_memories_by_user_id returns None on exception
                logger.warning("[ContextInject] Memories.get_memories_by_user_id returned None (possible DB error)")
                return []
            result = [m.content for m in memories if hasattr(m, 'content') and m.content]
            logger.info(f"[ContextInject] Fetched {len(result)} memories for user {user_id[:8]}...")
            return result
        except ImportError as e:
            logger.error(f"[ContextInject] Cannot import Memories model: {e}. "
                        f"Check that open_webui.models.memories exists in this OpenWebUI version.")
        except Exception as e:
            logger.error(f"[ContextInject] Failed to fetch memories: {type(e).__name__}: {e}")
            
        return []

    def _format_memory_context(self, memories: list) -> str:
        """Formats the raw memory strings into a structured system prompt block."""
        if not memories:
            return ""
            
        user_facts = []
        project_facts = []
        feedback_facts = []
        other_facts = []
        
        for mem in memories:
            mem = mem.strip()
            if mem.startswith("[USER]"):
                user_facts.append(mem.replace("[USER]", "").strip())
            elif mem.startswith("[PROJECT]"):
                project_facts.append(mem.replace("[PROJECT]", "").strip())
            elif mem.startswith("[FEEDBACK]"):
                feedback_facts.append(mem.replace("[FEEDBACK]", "").strip())
            else:
                other_facts.append(mem)
                
        # Build the injected text
        blocks = []
        blocks.append("--- [MEMORY CONTEXT START] ---")
        blocks.append("The following information has been recalled from past interactions:")
        
        if user_facts:
            blocks.append("\n## User Profile:")
            for f in user_facts[-self.valves.max_memories:]:
                blocks.append(f"- {f}")
                
        if project_facts:
            blocks.append("\n## Project Context:")
            for f in project_facts[-self.valves.max_memories:]:
                blocks.append(f"- {f}")
                
        if feedback_facts:
            blocks.append("\n## Behavioral Guidance (Feedback):")
            for f in feedback_facts[-self.valves.max_memories:]:
                blocks.append(f"- {f}")
                
        if other_facts:
            blocks.append("\n## Other Memories:")
            for f in other_facts[-self.valves.max_memories:]:
                blocks.append(f"- {f}")
                
        blocks.append("--- [MEMORY CONTEXT END] ---")
        
        return "\n".join(blocks)

    def inlet(self, body: dict, __user__: Optional[dict] = None) -> dict:
        """
        INLET: Runs before LLM call. Injects categorized memory context.
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
            
        # 1. Fetch memories efficiently and non-blocking via direct model
        raw_memories = self._get_user_memories(user_id)
        if not raw_memories:
            return body
            
        # 2. Format
        memory_block = self._format_memory_context(raw_memories)
        
        if not memory_block:
            return body

        # 3. Inject into the first system message, or prepend as a new system message
        system_msg_index = next((i for i, m in enumerate(messages) if m.get("role") == "system"), -1)
        
        if system_msg_index >= 0:
            original = messages[system_msg_index].get("content", "")
            messages[system_msg_index]["content"] = f"{memory_block}\n\n{original}"
        else:
            messages.insert(0, {"role": "system", "content": memory_block})
            
        body["messages"] = messages
        
        logger.info(f"[ContextInject] Injected {len(raw_memories)} memories into system prompt")
        
        return body
