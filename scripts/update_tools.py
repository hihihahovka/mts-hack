"""
Update Tools Script — Push updated tool code to running OpenWebUI via API
=========================================================================
Run this from the project root to update tools without rebuilding containers:

    python scripts/update_tools.py

Requires: pip install httpx
"""

import os
import sys
import httpx

# Adjust these if your setup differs
OPENWEBUI_URL = os.getenv("OPENWEBUI_URL", "http://localhost:8080")
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "admin@mts-ai.local")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "adminpassword123")

# Path relative to project root
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
TOOLS_DIR = os.path.join(PROJECT_ROOT, "tools")
FUNCTIONS_DIR = os.path.join(PROJECT_ROOT, "functions")

TOOLS = [
    {
        "id": "deep_research_tool",
        "name": "🔬 Deep Research",
        "description": "Глубокое исследование темы: декомпозиция запроса, поиск через SearXNG, парсинг через Jina Reader, синтез отчёта.",
        "filepath": os.path.join(TOOLS_DIR, "deep_research_tool.py"),
    },
    {
        "id": "web_scraper_tool",
        "name": "🌐 Web Scraper",
        "description": "Парсинг веб-страниц и извлечение контента в markdown.",
        "filepath": os.path.join(TOOLS_DIR, "web_scraper_tool.py"),
    },
]


def get_token() -> str:
    print(f"[update] Signing in as {ADMIN_EMAIL}...")
    resp = httpx.post(
        f"{OPENWEBUI_URL}/api/v1/auths/signin",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        timeout=10,
    )
    if resp.status_code != 200:
        print(f"[update] ❌ Auth failed: {resp.status_code} {resp.text}")
        sys.exit(1)
    token = resp.json().get("token")
    print("[update] ✅ Authenticated")
    return token


def update_tool(token: str, tool: dict) -> bool:
    filepath = tool["filepath"]
    if not os.path.exists(filepath):
        print(f"[update] ⚠️  File not found: {filepath}")
        return False

    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    payload = {
        "id": tool["id"],
        "name": tool["name"],
        "content": content,
        "meta": {"name": tool["name"], "description": tool["description"]},
    }
    headers = {"Authorization": f"Bearer {token}"}

    # Try update first, then create
    resp = httpx.post(
        f"{OPENWEBUI_URL}/api/v1/tools/id/{tool['id']}/update",
        json=payload,
        headers=headers,
        timeout=15,
    )
    if resp.status_code == 200:
        print(f"[update] 🔄 Tool '{tool['name']}' updated")
        return True

    resp = httpx.post(
        f"{OPENWEBUI_URL}/api/v1/tools/create",
        json=payload,
        headers=headers,
        timeout=15,
    )
    if resp.status_code == 200:
        print(f"[update] ✅ Tool '{tool['name']}' created")
        return True

    print(f"[update] ❌ Failed: {resp.status_code} {resp.text[:200]}")
    return False


def main():
    print("=" * 50)
    print("[update] OpenWebUI Tool Updater")
    print("=" * 50)

    token = get_token()

    for tool in TOOLS:
        update_tool(token, tool)

    print()
    print("[update] ✅ Done! Refresh the OpenWebUI page.")


if __name__ == "__main__":
    main()
