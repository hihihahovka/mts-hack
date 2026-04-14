"""
title: Presentation Tool
author: Developer
version: 4.0
requirements: python-pptx, httpx
"""

import httpx
import json
import logging
import os
import asyncio
import re
import uuid
from io import BytesIO
from typing import Optional, List, Dict, Tuple, Any
from dataclasses import dataclass
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ════════════════════════════════════════════════════════════════════════
# THEME ENGINE
# ════════════════════════════════════════════════════════════════════════

@dataclass
class ThemeConfig:
    """Visual theme configuration for presentations."""
    name: str
    bg: Tuple[int, int, int]
    title: Tuple[int, int, int]
    body: Tuple[int, int, int]
    accent: Tuple[int, int, int]
    accent2: Tuple[int, int, int]
    muted: Tuple[int, int, int]
    section_bg: Tuple[int, int, int]
    section_text: Tuple[int, int, int]
    title_font: str
    body_font: str
    title_size: int
    body_size: int
    subtitle_size: int


THEMES: Dict[str, ThemeConfig] = {
    "dark": ThemeConfig(
        name="Dark",
        bg=(30, 30, 46), title=(205, 214, 244), body=(186, 194, 222),
        accent=(137, 180, 250), accent2=(245, 194, 231), muted=(108, 112, 134),
        section_bg=(49, 50, 68), section_text=(205, 214, 244),
        title_font="Segoe UI", body_font="Segoe UI",
        title_size=32, body_size=16, subtitle_size=20,
    ),
    "corporate": ThemeConfig(
        name="Corporate",
        bg=(255, 255, 255), title=(27, 42, 74), body=(51, 60, 78),
        accent=(0, 120, 212), accent2=(0, 178, 148), muted=(153, 153, 153),
        section_bg=(27, 42, 74), section_text=(255, 255, 255),
        title_font="Calibri", body_font="Calibri",
        title_size=32, body_size=16, subtitle_size=20,
    ),
    "academic": ThemeConfig(
        name="Academic",
        bg=(250, 248, 240), title=(44, 30, 16), body=(62, 48, 32),
        accent=(139, 0, 0), accent2=(212, 165, 55), muted=(153, 136, 119),
        section_bg=(44, 30, 16), section_text=(250, 248, 240),
        title_font="Georgia", body_font="Palatino Linotype",
        title_size=30, body_size=15, subtitle_size=18,
    ),
    "creative": ThemeConfig(
        name="Creative",
        bg=(15, 10, 26), title=(232, 222, 255), body=(196, 181, 224),
        accent=(189, 92, 255), accent2=(255, 107, 157), muted=(108, 91, 138),
        section_bg=(45, 27, 78), section_text=(232, 222, 255),
        title_font="Segoe UI", body_font="Segoe UI",
        title_size=34, body_size=16, subtitle_size=20,
    ),
    "minimal": ThemeConfig(
        name="Minimal",
        bg=(255, 255, 255), title=(17, 17, 17), body=(68, 68, 68),
        accent=(17, 17, 17), accent2=(238, 85, 51), muted=(187, 187, 187),
        section_bg=(245, 245, 245), section_text=(17, 17, 17),
        title_font="Arial", body_font="Arial",
        title_size=30, body_size=15, subtitle_size=18,
    ),
}


# ════════════════════════════════════════════════════════════════════════
# SLIDE SCHEMA (Pydantic Validation)
# ════════════════════════════════════════════════════════════════════════

VALID_LAYOUTS = [
    "title_slide", "bullets_only", "title_and_image", "two_columns",
    "quote", "section_divider", "full_image", "stats",
    "comparison", "closing", "title_only",
]


class SlideSchema(BaseModel):
    layout: str = "bullets_only"
    title: str = ""
    subtitle: str = ""
    bullets: List[str] = Field(default_factory=list)
    speaker_notes: str = ""
    image_prompt: str = ""
    stat_number: str = ""
    stat_label: str = ""


class PresentationSchema(BaseModel):
    slides: List[SlideSchema]


# ════════════════════════════════════════════════════════════════════════
# CONSTANTS
# ════════════════════════════════════════════════════════════════════════

MAX_RETRIES = 3
RETRY_BASE_DELAY_S = 1.5
IMAGE_CONCURRENCY = 3
RESEARCH_TIMEOUT_S = 180.0
GENERATION_TIMEOUT_S = 180.0
CRITIC_TIMEOUT_S = 120.0
IMAGE_TIMEOUT_S = 60.0

# Slide dimensions (16:9 widescreen)
SLD_W = 13.333
SLD_H = 7.5

# Standard positions (inches)
TITLE_L, TITLE_T, TITLE_W, TITLE_H = 0.7, 0.4, 11.9, 1.1
BODY_L, BODY_T, BODY_W, BODY_H = 0.7, 1.85, 11.9, 5.1
BODY_IMG_W = 5.5
IMG_L, IMG_T, IMG_W, IMG_H = 6.8, 1.85, 5.8, 5.0
ACCENT_BAR_T = 1.6
ACCENT_BAR_W, ACCENT_BAR_H = 3.5, 0.05
SNUM_L, SNUM_T, SNUM_W, SNUM_H = 12.3, 7.0, 0.7, 0.35
COMPARISON_HEADER_MAX_CHARS = 35


# ════════════════════════════════════════════════════════════════════════
# TOOL CLASS
# ════════════════════════════════════════════════════════════════════════

class Tools:
    class Valves(BaseModel):
        """Configurable parameters for Presentation Tool v4."""
        llm_base_url: str = Field(
            default="https://api.gpt.mws.ru/v1",
            description="MWS GPT API base URL"
        )
        llm_api_key: str = Field(
            default="",
            description="MWS API Key. If empty, falls back to MWS_API_KEY or OPENAI_API_KEY env."
        )
        llm_model: str = Field(
            default="qwen2.5-72b-instruct",
            description="Model for generating content. Recommended: qwen2.5-72b-instruct"
        )
        image_model: str = Field(
            default="qwen-image",
            description="Model for generating images"
        )
        default_theme: str = Field(
            default="dark",
            description="Default visual theme: dark, corporate, academic, creative, minimal"
        )
        enable_critic: bool = Field(
            default=True,
            description="Enable critic agent for quality review (adds ~20s but improves quality)"
        )
        max_critic_iterations: int = Field(
            default=2,
            description="Maximum critic review iterations"
        )
        enable_web_research: bool = Field(
            default=True,
            description="Enable web search via SearXNG + Jina for real data"
        )
        searxng_base_url: str = Field(
            default="http://searxng:8080/search",
            description="SearXNG API base URL for web search"
        )
        jina_base_url: str = Field(
            default="https://r.jina.ai",
            description="Jina Reader API base URL for web scraping"
        )
        max_search_results: int = Field(
            default=4,
            description="Max URLs to scrape per search query"
        )
        max_scrape_chars: int = Field(
            default=8000,
            description="Max characters per scraped page"
        )

    def __init__(self):
        self.valves = self.Valves()

    # ────────────────────────────────────────────────────────────────
    # Utility Methods
    # ────────────────────────────────────────────────────────────────

    async def emit_status(self, __event_emitter__, description: str, done: bool = False):
        """Send status update to OpenWebUI chat."""
        if __event_emitter__:
            await __event_emitter__({
                "type": "status",
                "data": {"description": description, "done": done}
            })

    def _get_api_key(self) -> str:
        """Get API key from valves or environment."""
        if self.valves.llm_api_key:
            return self.valves.llm_api_key
        return os.environ.get("MWS_API_KEY") or os.environ.get("OPENAI_API_KEY", "")

    @staticmethod
    def _rgb(t: Tuple[int, int, int]):
        """Convert RGB tuple to pptx RGBColor."""
        from pptx.dml.color import RGBColor
        return RGBColor(t[0], t[1], t[2])

    # ────────────────────────────────────────────────────────────────
    # HTTP with Retry (Exponential Backoff)
    # ────────────────────────────────────────────────────────────────

    async def _llm_call(
        self,
        messages: List[Dict],
        timeout: float = GENERATION_TIMEOUT_S,
        json_mode: bool = False,
        max_tokens: Optional[int] = None,
    ) -> str:
        """Make an LLM API call with retry logic and exponential backoff."""
        api_key = self._get_api_key()
        if not api_key:
            raise ValueError("API key is not configured. Set it in Valves or MWS_API_KEY env var.")

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        payload: Dict[str, Any] = {
            "model": self.valves.llm_model,
            "messages": messages,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        if max_tokens:
            payload["max_tokens"] = max_tokens

        last_error: Optional[Exception] = None
        for attempt in range(MAX_RETRIES):
            try:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    response = await client.post(
                        f"{self.valves.llm_base_url}/chat/completions",
                        headers=headers,
                        json=payload,
                    )
                    response.raise_for_status()
                    return response.json()["choices"][0]["message"]["content"]
            except (httpx.HTTPStatusError, httpx.TimeoutException, httpx.ConnectError) as e:
                last_error = e
                if attempt < MAX_RETRIES - 1:
                    delay = RETRY_BASE_DELAY_S * (2 ** attempt)
                    logger.warning(f"LLM call attempt {attempt + 1} failed: {e}. Retrying in {delay:.1f}s...")
                    await asyncio.sleep(delay)
                else:
                    logger.error(f"LLM call failed after {MAX_RETRIES} attempts: {e}")
        raise last_error

    # ────────────────────────────────────────────────────────────────
    # Web Search & Scraping (SearXNG + Jina Reader)
    # ────────────────────────────────────────────────────────────────

    async def _search_web(self, query: str) -> List[Dict[str, str]]:
        """Search via SearXNG and return list of {url, title, snippet}."""
        try:
            params = {"q": query, "format": "json"}
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(self.valves.searxng_base_url, params=params)
                resp.raise_for_status()
                results = resp.json().get("results", [])
                parsed = []
                for res in results:
                    parsed.append({
                        "url": res.get("url", ""),
                        "title": res.get("title", ""),
                        "snippet": res.get("content", "")[:500],
                    })
                    if len(parsed) >= self.valves.max_search_results:
                        break
                return parsed
        except Exception as e:
            logger.warning(f"SearXNG search failed for '{query}': {e}")
            return []

    async def _scrape_url(self, url: str) -> str:
        """Scrape URL via Jina Reader, fallback to direct scrape."""
        # Attempt 1: Jina Reader
        try:
            jina_url = f"{self.valves.jina_base_url}/{url}"
            async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
                resp = await client.get(
                    jina_url,
                    headers={"Accept": "text/markdown", "X-Return-Format": "markdown"},
                )
                resp.raise_for_status()
                content = resp.text
                if len(content) > self.valves.max_scrape_chars:
                    content = content[: self.valves.max_scrape_chars]
                return content
        except Exception as e:
            logger.warning(f"Jina failed for '{url}': {e}, trying direct scrape")

        # Attempt 2: Direct scrape with HTML cleanup
        try:
            async with httpx.AsyncClient(
                timeout=15,
                follow_redirects=True,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    "Accept": "text/html",
                },
            ) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                html = resp.text
            for tag in ["script", "style", "nav", "footer", "header", "aside", "noscript"]:
                html = re.sub(rf"<{tag}[^>]*>.*?</{tag}>", "", html, flags=re.DOTALL | re.IGNORECASE)
            text = re.sub(r"<[^>]+>", " ", html)
            text = re.sub(r"[ \t]+", " ", text)
            text = re.sub(r"\n\s*\n", "\n\n", text).strip()
            if len(text) > self.valves.max_scrape_chars:
                text = text[: self.valves.max_scrape_chars]
            return text
        except Exception as e2:
            logger.error(f"Direct scrape also failed for '{url}': {e2}")
            return ""

    async def _web_research(self, topic: str, __event_emitter__) -> str:
        """Perform web research: decompose query → search → scrape → compile."""
        await self.emit_status(__event_emitter__, "🌐 Generating search queries...", False)

        # Step 1: Decompose topic into search queries
        decompose_messages = [
            {
                "role": "system",
                "content": (
                    "You are a search query optimizer. Given a presentation topic, generate 3 focused "
                    "search queries to find factual data, statistics, and expert insights.\n"
                    "Return ONLY a JSON array of strings, no explanation.\n"
                    "Example: [\"query 1\", \"query 2\", \"query 3\"]"
                ),
            },
            {"role": "user", "content": f"Generate search queries for a presentation about: {topic}"},
        ]
        try:
            raw = await self._llm_call(decompose_messages, timeout=30, max_tokens=300)
            match = re.search(r"\[.*?\]", raw.replace("\n", " "), re.DOTALL)
            queries = json.loads(match.group(0)) if match else [topic]
            if not isinstance(queries, list) or not queries:
                queries = [topic]
        except Exception:
            queries = [topic]

        queries_preview = ", ".join(f'"{q}"' for q in queries[:3])
        await self.emit_status(__event_emitter__, f"🔍 Searching: {queries_preview}", False)

        # Step 2: Parallel search
        sem = asyncio.Semaphore(2)

        async def bounded_search(q):
            async with sem:
                return await self._search_web(q)

        search_results = await asyncio.gather(*[bounded_search(q) for q in queries], return_exceptions=True)
        search_results = [r for r in search_results if isinstance(r, list)]

        # Deduplicate URLs
        seen_urls: set = set()
        all_results: List[Dict] = []
        for results in search_results:
            for res in results:
                if res["url"] not in seen_urls:
                    seen_urls.add(res["url"])
                    all_results.append(res)

        if not all_results:
            logger.warning("Web search returned no results, falling back to LLM-only research")
            return ""

        await self.emit_status(
            __event_emitter__,
            f"📖 Reading {len(all_results)} sources...",
            False,
        )

        # Step 3: Parallel scrape
        sem_read = asyncio.Semaphore(3)

        async def bounded_read(url: str):
            async with sem_read:
                return await self._scrape_url(url)

        scraped = await asyncio.gather(
            *[bounded_read(r["url"]) for r in all_results], return_exceptions=True
        )
        scraped = [s for s in scraped if isinstance(s, str) and len(s) > 100]

        if not scraped:
            return ""

        # Compile with source attribution
        compiled = "## Web Research Results\n\n"
        for i, (content, result) in enumerate(zip(scraped, all_results)):
            if content:
                title = result.get("title", result["url"])
                compiled += f"### Source {i + 1}: {title}\n{content}\n\n---\n\n"

        # Cap total length
        if len(compiled) > 30000:
            compiled = compiled[:30000] + "\n\n...[truncated]"

        return compiled

    # ────────────────────────────────────────────────────────────────
    # Agent 1: Deep Research
    # ────────────────────────────────────────────────────────────────

    async def _perform_deep_research(
        self, topic: str, audience: str, web_context: str, __event_emitter__
    ) -> str:
        """Agentic research: combines web data with LLM knowledge into presentation-ready material."""
        logger.info(f"--- AGENT 1: DEEP RESEARCH | Topic: {topic} ---")

        audience_guidance = {
            "executives": "Focus on strategic impact, ROI, market positioning, and high-level metrics. Avoid technical jargon.",
            "technical": "Include technical details, architecture, implementation specifics, and code-level considerations.",
            "students": "Use clear explanations, educational examples, and build concepts progressively from basics.",
            "general": "Balance depth with accessibility. Use relatable analogies and avoid assuming prior knowledge.",
        }.get(audience, "Balance depth with accessibility.")

        web_section = ""
        if web_context:
            web_section = (
                "\n\nYou have been provided with REAL WEB RESEARCH DATA below. "
                "Use this data as your PRIMARY source of facts, statistics, and evidence. "
                "Cite specific numbers and findings from the web research. "
                "Supplement with your own knowledge only where the web data has gaps.\n\n"
                f"--- WEB RESEARCH DATA ---\n{web_context}\n--- END WEB DATA ---\n"
            )

        system_prompt = (
            "You are a world-class research analyst and presentation strategist. "
            "Your task is to conduct exhaustive research on the given topic and prepare a rich factual foundation for a professional presentation.\n\n"
            "⚠️ CRITICAL: Carefully examine ALL aspects of the requested topic. If the topic mentions multiple subjects, "
            "you MUST cover ALL of them equally — do not omit anything!\n\n"
            f"Target audience: {audience_guidance}\n"
            f"{web_section}\n"
            "Generate a comprehensive research document (minimum 800 words, 8-12 semantic blocks) including:\n"
            "1. **Narrative Arc**: The logical storytelling flow from opening hook to conclusion.\n"
            "2. **Key Facts & Statistics**: Concrete data points, numbers, and evidence (prefer web research data if available).\n"
            "3. **Detailed Speaker Notes**: Rich explanatory text for each semantic block (the presenter's script).\n"
            "4. **Visual Ideas**: Suggestions for images, charts, or diagrams per section.\n"
            "5. **Comparative Analysis**: Where applicable, compare/contrast ideas or approaches.\n"
            "6. **Actionable Takeaways**: What the audience should remember or do after the presentation.\n\n"
            "⚠️ CRITICAL: The output MUST be in the EXACT SAME language as the requested topic!\n"
            "Focus on depth, academic rigor, and concrete specifics — not vague generalities."
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Conduct deep research for a presentation on the topic: {topic}"},
        ]

        return await self._llm_call(messages, timeout=RESEARCH_TIMEOUT_S, max_tokens=4000)

    # ────────────────────────────────────────────────────────────────
    # Agent 2: Outline Planning
    # ────────────────────────────────────────────────────────────────

    async def _plan_outline(
        self, topic: str, research: str, num_slides: int, __event_emitter__
    ) -> str:
        """Create a structured slide outline based on research material."""
        logger.info(f"--- AGENT 2: OUTLINE PLANNING | Slides: {num_slides} ---")

        system_prompt = (
            "You are a presentation architect. Given research material, create a structured outline.\n\n"
            f"Create exactly {num_slides} slides. For each slide, specify:\n"
            "- Slide number\n"
            "- Recommended layout (pick from: title_slide, bullets_only, title_and_image, two_columns, "
            "quote, section_divider, full_image, stats, comparison, closing)\n"
            "- Title\n"
            "- Key points to cover (3-5 bullet ideas)\n"
            "- Whether it needs an image\n\n"
            "Layout usage rules:\n"
            "- Slide 1 MUST be 'title_slide'\n"
            "- The last slide MUST be 'closing'\n"
            "- Use at least 1-2 'section_divider' slides to break the presentation into logical parts\n"
            "- Use 'title_and_image' for at least 30% of content slides to keep the deck visual\n"
            "- Use 'stats' layout when there are key numbers, percentages, or metrics to highlight\n"
            "- Use 'quote' for impactful statements or key takeaways\n"
            "- Use 'comparison' when contrasting two approaches, products, or ideas\n"
            "- Ensure a coherent narrative arc: hook → context → deep dive → insights → conclusion\n\n"
            "⚠️ CRITICAL: Cover ALL topics mentioned in the original request. Do not omit anything!\n"
            "⚠️ Output in the SAME language as the research material."
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Topic: {topic}\n\nResearch material:\n{research[:6000]}"},
        ]

        return await self._llm_call(messages, timeout=GENERATION_TIMEOUT_S, max_tokens=2000)

    # ────────────────────────────────────────────────────────────────
    # Agent 3: Slide JSON Generation
    # ────────────────────────────────────────────────────────────────

    async def _generate_slides_json(
        self,
        research: str,
        outline: str,
        num_slides: int,
        __event_emitter__,
    ) -> PresentationSchema:
        """Generate validated JSON slide structure from research and outline."""
        logger.info("--- AGENT 3: SLIDE JSON GENERATION ---")

        system_prompt = (
            "You are an elite presentation content designer. Convert the research and outline "
            "into a strict JSON structure for generating a professional presentation.\n\n"
            "CORE PRINCIPLE: Slides must be information-dense and visually planned. No empty or sparse slides!\n\n"
            "CRITICAL RULES:\n"
            f"1. Generate exactly {num_slides} slides.\n"
            "2. The `speaker_notes` field is MANDATORY for EVERY slide — never leave it empty! (3-6 detailed sentences)\n"
            "3. Each bullet point must be 15-40 words of substantive content.\n"
            "4. Follow the outline's layout recommendations strictly.\n\n"
            "AVAILABLE LAYOUTS & THEIR JSON FIELDS:\n"
            "• 'title_slide' — Opening slide. Use: title, subtitle, speaker_notes\n"
            "• 'bullets_only' — Standard content. Use: title, bullets (3-6 items), speaker_notes\n"
            "• 'title_and_image' — Content + visual. Use: title, bullets (3-5 items), image_prompt (ENGLISH!), speaker_notes\n"
            "• 'two_columns' — Split content. Use: title, bullets (4-6 items, split into left/right halves), speaker_notes\n"
            "• 'comparison' — Side-by-side contrast. Use: title, bullets (4-6, first half=left, second half=right), speaker_notes\n"
            "• 'quote' — Impactful statement. Use: title (the quote text), subtitle (attribution), speaker_notes\n"
            "• 'section_divider' — Section break. Use: title, subtitle, speaker_notes\n"
            "• 'full_image' — Full background image. Use: title, image_prompt (ENGLISH!), speaker_notes\n"
            "• 'stats' — Key metric highlight. Use: title, stat_number (e.g. '93%'), stat_label (explanation), bullets (2-3 supporting), speaker_notes\n"
            "• 'closing' — Final slide. Use: title, subtitle, bullets (optional, e.g. contact), speaker_notes\n"
            "• 'title_only' — Simple title. Use: title, speaker_notes\n\n"
            "JSON FORMAT:\n"
            '{"slides": [{"layout": "title_slide", "title": "...", "subtitle": "...", '
            '"bullets": [], "speaker_notes": "...", "image_prompt": "", '
            '"stat_number": "", "stat_label": ""}]}\n\n'
            "⚠️ ALL text (title, bullets, speaker_notes, subtitle, stat_label) must be in the SAME language as the research.\n"
            "⚠️ ONLY image_prompt must be in English.\n"
            "⚠️ Every slide object must have ALL 8 fields (use empty string/array for unused ones).\n"
            "⚠️ LANGUAGE CONSISTENCY IS CRITICAL: Do NOT mix languages! If the research is in Russian, ALL titles and bullets MUST be in Russian. "
            "Do NOT use English words or phrases in titles/bullets unless they are proper nouns or widely-used technical terms (e.g. 'AI', 'Python'). "
            "Translate everything else to the research language."
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": f"Research:\n{research[:6000]}\n\nOutline:\n{outline}\n\nGenerate the strict JSON slide structure.",
            },
        ]

        raw = await self._llm_call(
            messages, timeout=GENERATION_TIMEOUT_S, json_mode=True, max_tokens=6000
        )

        # Parse JSON (extract from possible markdown wrapping)
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            raw = match.group(0)
        parsed = json.loads(raw)

        # Validate with Pydantic schema, with recovery
        try:
            validated = PresentationSchema(**parsed)
        except Exception as e:
            logger.warning(f"Schema validation failed, attempting recovery: {e}")
            if "slides" not in parsed and isinstance(parsed, list):
                parsed = {"slides": parsed}
            slides = []
            for s in parsed.get("slides", []):
                try:
                    slide = SlideSchema(**s)
                    # Fix invalid layout
                    if slide.layout not in VALID_LAYOUTS:
                        slide.layout = "bullets_only"
                    slides.append(slide)
                except Exception:
                    slides.append(
                        SlideSchema(
                            layout="bullets_only",
                            title=s.get("title", "Untitled") if isinstance(s, dict) else "Untitled",
                            bullets=s.get("bullets", []) if isinstance(s, dict) else [],
                            speaker_notes=s.get("speaker_notes", "") if isinstance(s, dict) else "",
                        )
                    )
            validated = PresentationSchema(slides=slides)

        # Post-validation: ensure all layouts are valid
        for slide in validated.slides:
            if slide.layout not in VALID_LAYOUTS:
                slide.layout = "bullets_only"

        return validated

    # ────────────────────────────────────────────────────────────────
    # Agent 4: Critic Review
    # ────────────────────────────────────────────────────────────────

    async def _critic_review(
        self, topic: str, presentation: PresentationSchema, __event_emitter__
    ) -> Tuple[bool, str]:
        """Review slides for quality and completeness. Returns (approved, feedback)."""
        logger.info("--- AGENT 4: CRITIC REVIEW ---")

        slides_summary = json.dumps(
            [s.dict() if hasattr(s, 'dict') else s.model_dump() for s in presentation.slides],
            ensure_ascii=False,
            indent=2,
        )

        system_prompt = (
            "You are a strict presentation quality reviewer. Evaluate the slide JSON and decide "
            "if it meets professional standards.\n\n"
            "CHECK THESE CRITERIA:\n"
            "1. Topic Coverage: Do the slides cover ALL aspects of the original topic? Nothing omitted?\n"
            "2. Speaker Notes: Does EVERY slide have substantial speaker notes (not just 1 sentence)?\n"
            "3. Content Density: Are bullets detailed (15+ words each)? No sparse or empty slides?\n"
            "4. Narrative Flow: Is there logical progression from intro → body → conclusion?\n"
            "5. Layout Variety: Are multiple layout types used appropriately?\n"
            "6. Opening & Closing: Does it start with title_slide and end with closing?\n\n"
            "RESPOND IN THIS EXACT FORMAT:\n"
            "VERDICT: APPROVED\n"
            "(or)\n"
            "VERDICT: NEEDS_REVISION\n"
            "FEEDBACK: <specific issues to fix, one per line>"
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Original topic: {topic}\n\nSlides JSON:\n{slides_summary[:8000]}"},
        ]

        response = await self._llm_call(messages, timeout=CRITIC_TIMEOUT_S, max_tokens=1000)

        if "APPROVED" in response.upper():
            return True, ""
        else:
            feedback = response.split("FEEDBACK:")[-1].strip() if "FEEDBACK:" in response else response
            return False, feedback

    # ────────────────────────────────────────────────────────────────
    # PPTX Theme & Shape Helpers
    # ────────────────────────────────────────────────────────────────

    def _set_slide_bg(self, slide, theme: ThemeConfig):
        """Set solid background color for a slide."""
        bg = slide.background
        fill = bg.fill
        fill.solid()
        fill.fore_color.rgb = self._rgb(theme.bg)

    def _add_accent_bar(self, slide, theme: ThemeConfig, left: float = 0.7, width: float = ACCENT_BAR_W):
        """Add thin colored accent bar under the title area."""
        from pptx.util import Inches
        from pptx.enum.shapes import MSO_SHAPE

        bar = slide.shapes.add_shape(
            MSO_SHAPE.RECTANGLE,
            Inches(left), Inches(ACCENT_BAR_T),
            Inches(width), Inches(ACCENT_BAR_H),
        )
        bar.fill.solid()
        bar.fill.fore_color.rgb = self._rgb(theme.accent)
        bar.line.fill.background()

    def _add_slide_number(self, slide, num: int, total: int, theme: ThemeConfig):
        """Add slide number indicator at bottom-right."""
        from pptx.util import Inches, Pt
        from pptx.enum.text import PP_ALIGN

        txbox = slide.shapes.add_textbox(
            Inches(SNUM_L), Inches(SNUM_T), Inches(SNUM_W), Inches(SNUM_H)
        )
        tf = txbox.text_frame
        p = tf.paragraphs[0]
        p.text = f"{num}/{total}"
        p.font.size = Pt(10)
        p.font.color.rgb = self._rgb(theme.muted)
        p.font.name = theme.body_font
        p.alignment = PP_ALIGN.RIGHT

    def _make_title_frame(
        self, slide, text: str, theme: ThemeConfig,
        left: float = TITLE_L, top: float = TITLE_T,
        width: float = TITLE_W, height: float = TITLE_H,
        size: Optional[int] = None, bold: bool = True, alignment=None,
        color_override: Optional[Tuple[int, int, int]] = None,
    ):
        """Create a styled title textbox and return the shape."""
        from pptx.util import Inches, Pt
        from pptx.enum.text import MSO_AUTO_SIZE

        txbox = slide.shapes.add_textbox(
            Inches(left), Inches(top), Inches(width), Inches(height)
        )
        tf = txbox.text_frame
        tf.word_wrap = True
        tf.auto_size = MSO_AUTO_SIZE.TEXT_TO_FIT_SHAPE
        p = tf.paragraphs[0]
        p.text = text
        p.font.size = Pt(size or theme.title_size)
        p.font.color.rgb = self._rgb(color_override or theme.title)
        p.font.name = theme.title_font
        p.font.bold = bold
        if alignment:
            p.alignment = alignment
        return txbox

    def _make_body_frame(
        self, slide, bullets: List[str], theme: ThemeConfig,
        left: float = BODY_L, top: float = BODY_T,
        width: float = BODY_W, height: float = BODY_H,
        size: Optional[int] = None,
    ):
        """Create a styled bullet-point textbox and return the shape."""
        from pptx.util import Inches, Pt
        from pptx.enum.text import MSO_AUTO_SIZE

        if not bullets:
            return None
        txbox = slide.shapes.add_textbox(
            Inches(left), Inches(top), Inches(width), Inches(height)
        )
        tf = txbox.text_frame
        tf.word_wrap = True
        tf.auto_size = MSO_AUTO_SIZE.TEXT_TO_FIT_SHAPE
        for i, bullet in enumerate(bullets):
            p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
            p.text = f"•  {bullet}"
            p.font.size = Pt(size or theme.body_size)
            p.font.color.rgb = self._rgb(theme.body)
            p.font.name = theme.body_font
            p.space_before = Pt(4)
            p.space_after = Pt(10)
            p.line_spacing = Pt(22)
        return txbox

    def _add_image_to_slide(
        self, slide, img_bytes: Optional[bytes],
        left: float = IMG_L, top: float = IMG_T,
        width: float = IMG_W, height: float = IMG_H,
        theme: Optional[ThemeConfig] = None,
    ) -> bool:
        """Add image to slide or a styled placeholder if image is missing."""
        from pptx.util import Inches, Pt
        from pptx.enum.text import PP_ALIGN
        from pptx.enum.shapes import MSO_SHAPE

        if img_bytes:
            try:
                img_io = BytesIO(img_bytes)
                slide.shapes.add_picture(
                    img_io, Inches(left), Inches(top),
                    width=Inches(width), height=Inches(height),
                )
                return True
            except Exception as e:
                logger.warning(f"Failed to add picture: {e}")

        # Placeholder for missing images
        if theme:
            rect = slide.shapes.add_shape(
                MSO_SHAPE.ROUNDED_RECTANGLE,
                Inches(left), Inches(top), Inches(width), Inches(height),
            )
            rect.fill.solid()
            rect.fill.fore_color.rgb = self._rgb(theme.section_bg)
            rect.line.fill.background()
            tf = rect.text_frame
            tf.word_wrap = True
            p = tf.paragraphs[0]
            p.text = "🖼️"
            p.font.size = Pt(48)
            p.alignment = PP_ALIGN.CENTER
            p.font.color.rgb = self._rgb(theme.muted)
            p.space_before = Pt(60)
        return False

    # ────────────────────────────────────────────────────────────────
    # Layout Renderers (one per layout type)
    # ────────────────────────────────────────────────────────────────

    def _render_title_slide(self, slide, data: SlideSchema, theme: ThemeConfig):
        from pptx.util import Inches
        from pptx.enum.text import PP_ALIGN
        from pptx.enum.shapes import MSO_SHAPE

        # Top accent stripe
        bar = slide.shapes.add_shape(
            MSO_SHAPE.RECTANGLE, Inches(0), Inches(0), Inches(SLD_W), Inches(0.08)
        )
        bar.fill.solid()
        bar.fill.fore_color.rgb = self._rgb(theme.accent)
        bar.line.fill.background()

        # Title
        self._make_title_frame(
            slide, data.title, theme,
            left=1.0, top=2.2, width=11.3, height=2.0,
            size=44, alignment=PP_ALIGN.CENTER,
        )

        # Subtitle
        if data.subtitle:
            from pptx.util import Pt
            sub = slide.shapes.add_textbox(
                Inches(2.0), Inches(4.3), Inches(9.3), Inches(1.0)
            )
            tf = sub.text_frame
            tf.word_wrap = True
            p = tf.paragraphs[0]
            p.text = data.subtitle
            p.font.size = Pt(theme.subtitle_size)
            p.font.color.rgb = self._rgb(theme.muted)
            p.font.name = theme.body_font
            p.alignment = PP_ALIGN.CENTER

        # Bottom decorative line
        bar2 = slide.shapes.add_shape(
            MSO_SHAPE.RECTANGLE,
            Inches(4.0), Inches(5.5), Inches(5.3), Inches(0.04),
        )
        bar2.fill.solid()
        bar2.fill.fore_color.rgb = self._rgb(theme.accent2)
        bar2.line.fill.background()

    def _render_bullets_only(self, slide, data: SlideSchema, theme: ThemeConfig):
        self._make_title_frame(slide, data.title, theme)
        self._add_accent_bar(slide, theme)
        self._make_body_frame(slide, data.bullets, theme)

    def _render_title_and_image(
        self, slide, data: SlideSchema, theme: ThemeConfig, img_bytes: Optional[bytes]
    ):
        self._make_title_frame(slide, data.title, theme)
        self._add_accent_bar(slide, theme)
        self._make_body_frame(slide, data.bullets, theme, width=BODY_IMG_W)
        self._add_image_to_slide(slide, img_bytes, theme=theme)

    def _render_two_columns(self, slide, data: SlideSchema, theme: ThemeConfig):
        self._make_title_frame(slide, data.title, theme)
        self._add_accent_bar(slide, theme)
        mid = (len(data.bullets) + 1) // 2
        self._make_body_frame(slide, data.bullets[:mid], theme, width=5.5)
        self._make_body_frame(slide, data.bullets[mid:], theme, left=6.8, width=5.5)

    def _render_comparison(self, slide, data: SlideSchema, theme: ThemeConfig):
        from pptx.util import Inches, Pt
        from pptx.enum.shapes import MSO_SHAPE
        from pptx.enum.text import PP_ALIGN

        self._make_title_frame(slide, data.title, theme)
        self._add_accent_bar(slide, theme)

        mid = (len(data.bullets) + 1) // 2
        left_b = data.bullets[:mid]
        right_b = data.bullets[mid:]

        # Column header bars with labels
        for col_left, items, color in [
            (0.7, left_b, theme.accent),
            (6.8, right_b, theme.accent2),
        ]:
            header = slide.shapes.add_shape(
                MSO_SHAPE.RECTANGLE,
                Inches(col_left), Inches(1.85), Inches(5.5), Inches(0.5),
            )
            header.fill.solid()
            header.fill.fore_color.rgb = self._rgb(color)
            header.line.fill.background()
            # Header label — truncated to fit the bar
            tf = header.text_frame
            tf.word_wrap = True
            p = tf.paragraphs[0]
            label = items[0].split(":")[0].split("—")[0].split(".")[0].strip() if items else ""
            if len(label) > COMPARISON_HEADER_MAX_CHARS:
                label = label[:COMPARISON_HEADER_MAX_CHARS].rsplit(" ", 1)[0] + "…"
            p.text = label
            p.font.size = Pt(13)
            p.font.bold = True
            p.font.color.rgb = self._rgb((255, 255, 255))
            p.font.name = theme.title_font
            p.alignment = PP_ALIGN.CENTER

        # Column content
        self._make_body_frame(slide, left_b, theme, top=2.5, width=5.5, height=4.4)
        self._make_body_frame(slide, right_b, theme, left=6.8, top=2.5, width=5.5, height=4.4)

        # Vertical divider
        div = slide.shapes.add_shape(
            MSO_SHAPE.RECTANGLE,
            Inches(6.5), Inches(1.85), Inches(0.03), Inches(5.0),
        )
        div.fill.solid()
        div.fill.fore_color.rgb = self._rgb(theme.muted)
        div.line.fill.background()

    def _render_quote(self, slide, data: SlideSchema, theme: ThemeConfig):
        from pptx.util import Inches, Pt
        from pptx.enum.text import PP_ALIGN

        # Large decorative quote mark
        qm = slide.shapes.add_textbox(Inches(1.0), Inches(1.0), Inches(2.0), Inches(2.0))
        p = qm.text_frame.paragraphs[0]
        p.text = "\u201C"
        p.font.size = Pt(120)
        p.font.color.rgb = self._rgb(theme.accent)
        p.font.name = theme.title_font
        p.font.bold = True

        # Quote text
        quote_text = data.title if data.title else " ".join(data.bullets)
        txbox = slide.shapes.add_textbox(Inches(2.0), Inches(2.5), Inches(9.3), Inches(3.0))
        tf = txbox.text_frame
        tf.word_wrap = True
        p = tf.paragraphs[0]
        p.text = quote_text
        p.font.size = Pt(28)
        p.font.italic = True
        p.font.color.rgb = self._rgb(theme.title)
        p.font.name = theme.title_font
        p.alignment = PP_ALIGN.CENTER

        # Attribution
        if data.subtitle:
            attr = slide.shapes.add_textbox(Inches(2.0), Inches(5.5), Inches(9.3), Inches(0.6))
            p = attr.text_frame.paragraphs[0]
            p.text = f"— {data.subtitle}"
            p.font.size = Pt(16)
            p.font.color.rgb = self._rgb(theme.muted)
            p.font.name = theme.body_font
            p.alignment = PP_ALIGN.RIGHT

    def _render_section_divider(self, slide, data: SlideSchema, theme: ThemeConfig):
        from pptx.util import Inches, Pt
        from pptx.enum.text import PP_ALIGN
        from pptx.enum.shapes import MSO_SHAPE

        # Override background to section color
        bg = slide.background.fill
        bg.solid()
        bg.fore_color.rgb = self._rgb(theme.section_bg)

        # Centered accent bar
        bar = slide.shapes.add_shape(
            MSO_SHAPE.RECTANGLE,
            Inches(4.5), Inches(3.0), Inches(4.3), Inches(0.06),
        )
        bar.fill.solid()
        bar.fill.fore_color.rgb = self._rgb(theme.accent)
        bar.line.fill.background()

        # Section title
        self._make_title_frame(
            slide, data.title, theme,
            left=1.0, top=3.3, width=11.3, height=1.5,
            size=40, alignment=PP_ALIGN.CENTER,
            color_override=theme.section_text,
        )

        # Subtitle
        if data.subtitle:
            sub = slide.shapes.add_textbox(Inches(2.0), Inches(4.9), Inches(9.3), Inches(0.8))
            p = sub.text_frame.paragraphs[0]
            p.text = data.subtitle
            p.font.size = Pt(theme.subtitle_size)
            p.font.color.rgb = self._rgb(theme.muted)
            p.font.name = theme.body_font
            p.alignment = PP_ALIGN.CENTER

    def _render_full_image(
        self, slide, data: SlideSchema, theme: ThemeConfig, img_bytes: Optional[bytes]
    ):
        from pptx.util import Inches, Pt
        from pptx.enum.text import PP_ALIGN
        from pptx.enum.shapes import MSO_SHAPE

        # Full-bleed image
        if img_bytes:
            try:
                img_io = BytesIO(img_bytes)
                slide.shapes.add_picture(
                    img_io, Inches(0), Inches(0),
                    width=Inches(SLD_W), height=Inches(SLD_H),
                )
            except Exception as e:
                logger.warning(f"Full image failed: {e}")

        # Caption bar at bottom
        caption_bar = slide.shapes.add_shape(
            MSO_SHAPE.RECTANGLE,
            Inches(0), Inches(5.5), Inches(SLD_W), Inches(2.0),
        )
        caption_bar.fill.solid()
        caption_bar.fill.fore_color.rgb = self._rgb((0, 0, 0))
        caption_bar.line.fill.background()

        # Title on caption bar
        txbox = slide.shapes.add_textbox(Inches(1.0), Inches(5.8), Inches(11.3), Inches(1.2))
        tf = txbox.text_frame
        tf.word_wrap = True
        p = tf.paragraphs[0]
        p.text = data.title
        p.font.size = Pt(30)
        p.font.color.rgb = self._rgb((255, 255, 255))
        p.font.name = theme.title_font
        p.font.bold = True
        p.alignment = PP_ALIGN.LEFT

    def _render_stats(self, slide, data: SlideSchema, theme: ThemeConfig):
        from pptx.util import Inches, Pt
        from pptx.enum.text import PP_ALIGN

        self._make_title_frame(slide, data.title, theme)
        self._add_accent_bar(slide, theme)

        # Big stat number
        stat_box = slide.shapes.add_textbox(Inches(1.0), Inches(2.2), Inches(11.3), Inches(2.0))
        p = stat_box.text_frame.paragraphs[0]
        p.text = data.stat_number or "—"
        p.font.size = Pt(72)
        p.font.color.rgb = self._rgb(theme.accent)
        p.font.name = theme.title_font
        p.font.bold = True
        p.alignment = PP_ALIGN.CENTER

        # Stat label
        label_box = slide.shapes.add_textbox(Inches(2.0), Inches(4.0), Inches(9.3), Inches(0.8))
        p = label_box.text_frame.paragraphs[0]
        p.text = data.stat_label or ""
        p.font.size = Pt(22)
        p.font.color.rgb = self._rgb(theme.body)
        p.font.name = theme.body_font
        p.alignment = PP_ALIGN.CENTER

        # Supporting bullets
        if data.bullets:
            self._make_body_frame(slide, data.bullets, theme, top=5.0, height=2.0, size=14)

    def _render_closing(self, slide, data: SlideSchema, theme: ThemeConfig):
        from pptx.util import Inches, Pt
        from pptx.enum.text import PP_ALIGN
        from pptx.enum.shapes import MSO_SHAPE

        # Top accent stripe
        bar = slide.shapes.add_shape(
            MSO_SHAPE.RECTANGLE, Inches(0), Inches(0), Inches(SLD_W), Inches(0.08)
        )
        bar.fill.solid()
        bar.fill.fore_color.rgb = self._rgb(theme.accent)
        bar.line.fill.background()

        # Main closing text
        self._make_title_frame(
            slide, data.title or "Thank You", theme,
            left=1.0, top=2.5, width=11.3, height=1.5,
            size=44, alignment=PP_ALIGN.CENTER,
        )

        # Decorative line
        line = slide.shapes.add_shape(
            MSO_SHAPE.RECTANGLE,
            Inches(5.0), Inches(4.2), Inches(3.3), Inches(0.04),
        )
        line.fill.solid()
        line.fill.fore_color.rgb = self._rgb(theme.accent2)
        line.line.fill.background()

        # Subtitle (constrained width to prevent overflow)
        if data.subtitle:
            sub = slide.shapes.add_textbox(Inches(2.5), Inches(4.6), Inches(8.3), Inches(1.0))
            sub.text_frame.word_wrap = True
            p = sub.text_frame.paragraphs[0]
            p.text = data.subtitle
            p.font.size = Pt(theme.subtitle_size - 2)
            p.font.color.rgb = self._rgb(theme.muted)
            p.font.name = theme.body_font
            p.alignment = PP_ALIGN.CENTER

        # Optional bullets (contact info, etc.)
        if data.bullets:
            body = self._make_body_frame(slide, data.bullets, theme, top=5.5, height=1.5, size=14)
            if body:
                for p in body.text_frame.paragraphs:
                    p.alignment = PP_ALIGN.CENTER

    def _render_title_only(self, slide, data: SlideSchema, theme: ThemeConfig):
        self._make_title_frame(slide, data.title, theme)
        self._add_accent_bar(slide, theme)

    # ────────────────────────────────────────────────────────────────
    # PPTX Assembly
    # ────────────────────────────────────────────────────────────────

    def _assemble_pptx(
        self,
        presentation: PresentationSchema,
        images_bytes: List[Optional[bytes]],
        theme_name: str,
    ) -> BytesIO:
        """Assemble the final PPTX with themed styling and all layout types."""
        import pptx
        from pptx.util import Inches

        theme = THEMES.get(theme_name, THEMES["dark"])

        prs = pptx.Presentation()
        prs.slide_width = Inches(SLD_W)
        prs.slide_height = Inches(SLD_H)

        # Use blank layout for full visual control
        blank_layout_idx = min(6, len(prs.slide_layouts) - 1)
        blank_layout = prs.slide_layouts[blank_layout_idx]

        slides_data = presentation.slides
        total = len(slides_data)

        for idx, data in enumerate(slides_data):
            slide = prs.slides.add_slide(blank_layout)

            # Set background (section_divider and full_image handle their own)
            if data.layout not in ("section_divider",):
                self._set_slide_bg(slide, theme)

            img = images_bytes[idx] if idx < len(images_bytes) else None

            # Dispatch to layout renderer
            layout = data.layout
            if layout == "title_slide":
                self._render_title_slide(slide, data, theme)
            elif layout == "title_and_image":
                self._render_title_and_image(slide, data, theme, img)
            elif layout == "two_columns":
                self._render_two_columns(slide, data, theme)
            elif layout == "comparison":
                self._render_comparison(slide, data, theme)
            elif layout == "quote":
                self._render_quote(slide, data, theme)
            elif layout == "section_divider":
                self._render_section_divider(slide, data, theme)
            elif layout == "full_image":
                self._render_full_image(slide, data, theme, img)
            elif layout == "stats":
                self._render_stats(slide, data, theme)
            elif layout == "closing":
                self._render_closing(slide, data, theme)
            elif layout == "title_only":
                self._render_title_only(slide, data, theme)
            else:
                self._render_bullets_only(slide, data, theme)

            # Add slide number (skip for special layouts)
            if layout not in ("title_slide", "section_divider", "closing", "full_image"):
                self._add_slide_number(slide, idx + 1, total, theme)

            # Speaker notes
            if data.speaker_notes:
                notes = slide.notes_slide
                notes.notes_text_frame.text = data.speaker_notes

        bytes_io = BytesIO()
        prs.save(bytes_io)
        bytes_io.seek(0)
        return bytes_io

    # ────────────────────────────────────────────────────────────────
    # File Saving (OpenWebUI Integration)
    # ────────────────────────────────────────────────────────────────

    def _save_and_get_link(self, bytes_io: BytesIO, base_filename: str, user_id: str) -> str:
        """Save PPTX to OpenWebUI uploads and register in DB."""
        from open_webui.models.files import Files, FileForm

        save_dir = "/app/backend/data/uploads"
        os.makedirs(save_dir, exist_ok=True)
        unique_id = str(uuid.uuid4())
        safe_filename = f"{unique_id}_{base_filename}.pptx"
        file_path = os.path.join(save_dir, safe_filename)

        with open(file_path, "wb") as f:
            f.write(bytes_io.getvalue())

        try:
            form_data = FileForm(
                id=unique_id,
                filename=f"{base_filename}.pptx",
                path=file_path,
                meta={
                    "name": f"{base_filename}.pptx",
                    "content_type": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
                    "size": len(bytes_io.getvalue()),
                    "source": "presentation_tool_v4",
                },
            )
            Files.insert_new_file(user_id=user_id, form_data=form_data)
        except Exception as e:
            logger.warning(f"Failed to inject file into OpenWebUI DB: {e}")

        return f"/api/v1/files/{unique_id}/content/{safe_filename}"

    # ────────────────────────────────────────────────────────────────
    # Presentation Coach
    # ────────────────────────────────────────────────────────────────

    @staticmethod
    def _generate_coach_tips(slides: List[SlideSchema]) -> str:
        """Generate post-presentation coaching analysis."""
        total_words = sum(len(s.speaker_notes.split()) for s in slides)
        est_minutes = max(1, round(total_words / 140))  # ~140 wpm speaking pace

        bullet_count = sum(len(s.bullets) for s in slides)
        image_count = sum(1 for s in slides if s.image_prompt)
        layout_types = set(s.layout for s in slides)
        notes_thin = sum(1 for s in slides if len(s.speaker_notes.split()) < 20)

        tips = [
            f"⏱️ Estimated speaking time: **{est_minutes} min** ({total_words} words in speaker notes)",
            f"📊 {len(slides)} slides, {bullet_count} bullet points, {image_count} images",
            f"🎨 Layout variety: **{len(layout_types)} types** ({', '.join(sorted(layout_types))})",
        ]

        if est_minutes > 20:
            tips.append("⚠️ Consider trimming — presentations over 20 min tend to lose audience attention")
        if image_count < len(slides) * 0.2:
            tips.append("💡 Consider adding more visuals — aim for images on 25%+ of slides")
        if notes_thin > 2:
            tips.append(f"💡 {notes_thin} slides have thin speaker notes — expand for confident delivery")
        if len(layout_types) <= 3:
            tips.append("💡 Low layout variety — try using stats, quote, or comparison slides for visual interest")

        return "\n".join(f"- {t}" for t in tips)

    # ────────────────────────────────────────────────────────────────
    # Image Generation
    # ────────────────────────────────────────────────────────────────

    async def _fetch_image(self, prompt: str, api_key: str, client: httpx.AsyncClient) -> bytes:
        """Fetch a single image from the image generation API."""
        payload = {"model": self.valves.image_model, "prompt": prompt}
        headers = {"Authorization": f"Bearer {api_key}"}

        response = await client.post(
            f"{self.valves.llm_base_url}/images/generations",
            json=payload,
            headers=headers,
        )
        response.raise_for_status()
        url = response.json()["data"][0]["url"]

        img_resp = await client.get(url)
        img_resp.raise_for_status()
        return img_resp.content

    async def _generate_all_images(
        self, image_prompts: List[str], api_key: str, __event_emitter__
    ) -> Tuple[List[Optional[bytes]], List[str]]:
        """Concurrently fetch images. Returns (images_list, failed_prompts)."""
        sem = asyncio.Semaphore(IMAGE_CONCURRENCY)
        failed_prompts: List[str] = []
        generated_count = 0
        total_to_generate = sum(1 for p in image_prompts if p and p.strip().lower() not in ("none", "null", ""))

        async def _fetch_with_sem(prompt: str, idx: int, client: httpx.AsyncClient) -> Optional[bytes]:
            nonlocal generated_count
            if not prompt or prompt.strip().lower() in ("none", "null", ""):
                return None
            try:
                async with sem:
                    generated_count += 1
                    await self.emit_status(
                        __event_emitter__,
                        f"🎨 Image {generated_count}/{total_to_generate}: {prompt[:50]}...",
                        False,
                    )
                    return await self._fetch_image(prompt, api_key, client)
            except Exception as e:
                logger.error(f"Image generation failed for prompt '{prompt[:60]}': {e}")
                failed_prompts.append(prompt[:60])
                return None

        async with httpx.AsyncClient(timeout=IMAGE_TIMEOUT_S) as client:
            tasks = [_fetch_with_sem(p, i, client) for i, p in enumerate(image_prompts)]
            results = await asyncio.gather(*tasks, return_exceptions=True)

        final = [r if not isinstance(r, Exception) else None for r in results]
        return final, failed_prompts

    # ────────────────────────────────────────────────────────────────
    # Theme Auto-Selection
    # ────────────────────────────────────────────────────────────────

    async def _suggest_themes(self, topic: str) -> List[str]:
        """Use LLM to pick the 3 best themes for a topic. Returns list of theme keys."""
        theme_descriptions = {
            "dark": "Dark (Тёмная) — Deep navy/charcoal background with soft blue accents. Modern, sleek, universal. Best for: tech, science, general topics.",
            "corporate": "Corporate (Корпоративная) — Clean white background with navy headers and blue accents. Professional and trustworthy. Best for: business, finance, strategy.",
            "academic": "Academic (Академическая) — Warm cream background with serif fonts and burgundy accents. Scholarly and refined. Best for: education, research, history, literature.",
            "creative": "Creative (Креативная) — Deep purple/black background with vibrant purple and pink accents. Bold and expressive. Best for: art, design, marketing, entertainment.",
            "minimal": "Minimal (Минималистичная) — Pure white with thin black typography and orange accents. Clean and focused. Best for: startups, product demos, philosophy.",
        }

        system_prompt = (
            "You are a presentation design advisor. Given a topic, pick the 3 most suitable visual themes "
            "from the available options. Return ONLY a JSON array of 3 theme keys, ordered by best fit.\n"
            "Available themes: dark, corporate, academic, creative, minimal\n"
            "Example: [\"academic\", \"dark\", \"corporate\"]\n"
            "Return ONLY the JSON array, no explanation."
        )

        try:
            raw = await self._llm_call(
                [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"Topic: {topic}"},
                ],
                timeout=30,
                max_tokens=100,
            )
            match = re.search(r"\[.*?\]", raw.replace("\n", " "), re.DOTALL)
            if match:
                suggestions = json.loads(match.group(0))
                # Filter to valid themes only
                suggestions = [s for s in suggestions if s in THEMES][:3]
                if len(suggestions) >= 2:
                    return suggestions
        except Exception as e:
            logger.warning(f"Theme suggestion failed: {e}")

        # Fallback: sensible defaults
        return ["dark", "corporate", "minimal"]

    # ════════════════════════════════════════════════════════════════
    # MAIN ENTRY POINT
    # ════════════════════════════════════════════════════════════════

    async def generate_presentation(
        self,
        topic: str,
        num_slides: int = 10,
        style: str = "auto",
        audience: str = "general",
        __user__: dict = None,
        __event_emitter__=None,
    ) -> str:
        """
        Создаёт профессиональную презентацию PowerPoint (.pptx) с помощью мульти-агентного AI-пайплайна.
        Creates a professional PowerPoint (.pptx) presentation using a multi-agent AI pipeline.

        ⚠️ ОБЯЗАТЕЛЬНО вызывай этот инструмент, когда пользователь просит:
        - "сделай презентацию", "создай презентацию", "презентация на тему", "презентация про"
        - "сгенерируй слайды", "сделай слайды", "подготовь слайды"
        - "подготовь выступление", "сделай доклад", "доклад на тему"
        - "сделай pptx", "создай pptx", "нужна презентация"
        - "make a presentation", "create slides", "generate pptx", "prepare a talk"
        - любой запрос, где упоминается "презентация", "слайды", "доклад", "pptx", "powerpoint"
        
        ❌ НИКОГДА не отвечай текстом вместо вызова инструмента! ВСЕГДА используй этот инструмент!
        ❌ NEVER respond with plain text instead of calling this tool! ALWAYS use this tool!
        
        Если пользователь выбрал стиль (например ответил "dark" или "корпоративная"), 
        передай его в параметр style. Если пользователь впервые просит презентацию, 
        передай style="auto" для показа вариантов.

        :param topic: Тема презентации / The presentation topic.
        :param num_slides: Количество слайдов (по умолчанию 10, от 6 до 20) / Number of slides (default: 10, range: 6-20).
        :param style: Визуальная тема: auto (выбрать), dark, corporate, academic, creative, minimal.
        :param audience: Целевая аудитория: general, executives, technical, students (по умолчанию: general).
        :return: Ссылка на скачивание файла .pptx / A downloadable .pptx file link.
        """
        # Input validation
        num_slides = max(6, min(20, num_slides))
        audience = (
            audience.lower()
            if audience.lower() in ("general", "executives", "technical", "students")
            else "general"
        )

        # ═══════ Theme Selection Wizard ═══════
        style_lower = style.lower().strip()
        if style_lower == "auto" or style_lower not in THEMES:
            await self.emit_status(__event_emitter__, "🎨 Подбираю стили для вашей темы...", False)
            suggestions = await self._suggest_themes(topic)
            await self.emit_status(__event_emitter__, "🎨 Выберите стиль презентации!", True)

            theme_info = {
                "dark": ("🌙 Dark", "Тёмная", "Глубокий тёмно-синий фон, мягкие голубые акценты. Современный и универсальный."),
                "corporate": ("💼 Corporate", "Корпоративная", "Белый фон, тёмно-синие заголовки, голубые акценты. Деловой и надёжный."),
                "academic": ("📚 Academic", "Академическая", "Тёплый кремовый фон, шрифты с засечками, бордовые акценты. Научный и утончённый."),
                "creative": ("🎨 Creative", "Креативная", "Глубокий фиолетовый фон, яркие пурпурные и розовые акценты. Смелый и выразительный."),
                "minimal": ("✨ Minimal", "Минималистичная", "Чистый белый фон, тонкая чёрная типографика, оранжевые акценты. Лаконичный и фокусированный."),
            }

            options_md = ""
            for i, key in enumerate(suggestions):
                emoji, ru_name, desc = theme_info.get(key, ("📄", key, ""))
                marker = " ⭐ *рекомендуется*" if i == 0 else ""
                options_md += f"**{i + 1}. {emoji} — {ru_name}**{marker}\n{desc}\n\n"

            return f"""## 🎨 Выберите стиль презентации

**Тема:** {topic}

На основе вашей темы, я подобрал 3 лучших стиля:

{options_md}---

💬 **Ответьте номером (1, 2, 3) или названием стиля** (например: `dark`, `corporate`, `academic`, `creative`, `minimal`), и я сгенерирую вашу презентацию!"""

        style = style_lower

        try:
            # ═══════ Phase 0: Web Research (optional) ═══════
            web_context = ""
            if self.valves.enable_web_research:
                try:
                    await self.emit_status(
                        __event_emitter__,
                        "🌐 Phase 0/5: Searching the web for real data and statistics...",
                        False,
                    )
                    web_context = await self._web_research(topic, __event_emitter__)
                    if web_context:
                        logger.info(f"--- WEB RESEARCH COMPLETE ({len(web_context)} chars) ---")
                    else:
                        logger.info("--- WEB RESEARCH: no results, using LLM knowledge only ---")
                except Exception as e:
                    logger.warning(f"Web research failed (non-fatal): {e}")
                    web_context = ""

            # ═══════ Phase 1: Deep Research ═══════
            await self.emit_status(
                __event_emitter__,
                "🔬 Phase 1/5: Deep research — analyzing topic and gathering facts...",
                False,
            )
            research_data = await self._perform_deep_research(
                topic, audience, web_context, __event_emitter__
            )
            logger.info(f"--- RESEARCH COMPLETE ({len(research_data)} chars) ---")

            # ═══════ Phase 2: Outline Planning ═══════
            await self.emit_status(
                __event_emitter__,
                "📐 Phase 2/5: Architecting slide structure and narrative flow...",
                False,
            )
            outline = await self._plan_outline(topic, research_data, num_slides, __event_emitter__)
            logger.info(f"--- OUTLINE COMPLETE ({len(outline)} chars) ---")

            # ═══════ Phase 3: Slide JSON Generation ═══════
            await self.emit_status(
                __event_emitter__,
                "✍️ Phase 3/5: Generating detailed slide content and speaker notes...",
                False,
            )
            presentation = await self._generate_slides_json(
                research_data, outline, num_slides, __event_emitter__
            )
            logger.info(f"--- JSON GENERATION COMPLETE ({len(presentation.slides)} slides) ---")

            if not presentation.slides:
                return "❌ Failed to generate presentation content. Please try again."

            # ═══════ Phase 3.5: Critic Review Loop ═══════
            if self.valves.enable_critic:
                for iteration in range(self.valves.max_critic_iterations):
                    await self.emit_status(
                        __event_emitter__,
                        f"🔍 Quality review (pass {iteration + 1}/{self.valves.max_critic_iterations})...",
                        False,
                    )
                    approved, feedback = await self._critic_review(
                        topic, presentation, __event_emitter__
                    )

                    if approved:
                        logger.info(f"--- CRITIC APPROVED (pass {iteration + 1}) ---")
                        break
                    else:
                        logger.info(f"--- CRITIC REJECTED (pass {iteration + 1}): {feedback[:200]} ---")
                        if iteration < self.valves.max_critic_iterations - 1:
                            await self.emit_status(
                                __event_emitter__,
                                f"🔄 Critic found issues — regenerating (attempt {iteration + 2})...",
                                False,
                            )
                            presentation = await self._generate_slides_json(
                                research_data,
                                outline + f"\n\nCRITIC FEEDBACK (fix these issues):\n{feedback}",
                                num_slides,
                                __event_emitter__,
                            )

            # ═══════ Phase 4: Parallel Image Generation ═══════
            image_prompts: List[str] = []
            for s in presentation.slides:
                if s.layout in ("title_and_image", "full_image") and s.image_prompt:
                    image_prompts.append(s.image_prompt)
                else:
                    image_prompts.append("")

            num_images = sum(1 for p in image_prompts if p)
            failed_images: List[str] = []

            if num_images > 0:
                await self.emit_status(
                    __event_emitter__,
                    f"🎨 Phase 4/5: Generating {num_images} images in parallel...",
                    False,
                )
                images_bytes, failed_images = await self._generate_all_images(
                    image_prompts, self._get_api_key(), __event_emitter__
                )
            else:
                images_bytes = [None] * len(presentation.slides)

            # ═══════ Phase 5: Assembly & Export ═══════
            await self.emit_status(
                __event_emitter__,
                f"🏗️ Phase 5/5: Assembling {style.title()} themed PowerPoint...",
                False,
            )

            first_title = presentation.slides[0].title if presentation.slides else "Presentation"
            safe_title = re.sub(r"[^\w\s-]", "", first_title[:30]).strip().replace(" ", "_")
            if not safe_title:
                safe_title = "Presentation"

            pptx_bytes_io = self._assemble_pptx(presentation, images_bytes, style)

            # Save and get download link
            native_link = self._save_and_get_link(
                pptx_bytes_io, safe_title, __user__.get("id") if __user__ else "system"
            )

            await self.emit_status(__event_emitter__, "✅ Presentation ready!", True)

            # ═══════ Build Response ═══════
            # Slide structure summary
            layout_emoji = {
                "title_slide": "🎬", "bullets_only": "📝", "title_and_image": "🖼️",
                "two_columns": "📊", "comparison": "⚖️", "quote": "💬",
                "section_divider": "📌", "full_image": "🌅", "stats": "📈",
                "closing": "🎯", "title_only": "📋",
            }
            plan_md = ""
            for i, s in enumerate(presentation.slides):
                emoji = layout_emoji.get(s.layout, "📄")
                plan_md += f"{emoji} **Slide {i + 1}:** {s.title} `{s.layout}`\n"

            # Coach tips
            coach_tips = self._generate_coach_tips(presentation.slides)

            # Image failure warning
            img_warning = ""
            if failed_images:
                img_warning = (
                    f"\n\n> ⚠️ **{len(failed_images)} image(s) failed to generate** "
                    "and were replaced with placeholders."
                )

            # Web research note
            web_note = ""
            if web_context:
                web_note = "\n> 🌐 **Web-enhanced**: This presentation includes real data sourced from the internet.\n"

            return f"""## 📊 Your PowerPoint Presentation is Ready!

**Topic:** {first_title}
**Theme:** {style.title()} | **Slides:** {len(presentation.slides)} | **Audience:** {audience.title()}
{web_note}
### [⬇️ Download {safe_title}.pptx]({native_link})

---
### 📋 Slide Structure:
{plan_md}
---
### 🎤 Presentation Coach:
{coach_tips}{img_warning}

> 💡 **Совет:** Откройте **Заметки докладчика** в PowerPoint (Вид → Заметки) — ИИ сгенерировал полный текст выступления к каждому слайду!
"""

            # Emit directly into chat so the download link is ALWAYS visible
            # (not hidden behind the small "source" button)
            if __event_emitter__:
                await __event_emitter__({
                    "type": "message",
                    "data": {"content": response}
                })

            # Return empty string since content is already emitted to chat
            return ""

        except Exception as e:
            logger.error(f"Presentation generation failed: {e}", exc_info=True)
            await self.emit_status(__event_emitter__, f"❌ Error: {e}", True)
            return f"❌ Presentation generation failed: {str(e)}"
