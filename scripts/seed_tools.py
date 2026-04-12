"""
Seed Script — Auto-loads Tools and Functions into OpenWebUI
============================================================
Runs on first docker-compose up. Waits for OpenWebUI to be ready,
then uploads all tools and filter functions via the REST API.

This ensures one-command startup without manual Admin Panel configuration.
"""

import os
import sys
import time
import json
import httpx

OPENWEBUI_URL = os.getenv("OPENWEBUI_URL", "http://open-webui:8080")
MAX_RETRIES = 60  # Wait up to 5 minutes for OpenWebUI to start
RETRY_INTERVAL = 5  # seconds

# Directory containing tool/function Python files (mounted from host)
TOOLS_DIR = os.getenv("TOOLS_DIR", "/app/tools")
FUNCTIONS_DIR = os.getenv("FUNCTIONS_DIR", "/app/functions")


def wait_for_openwebui():
    """Wait for OpenWebUI to become available."""
    print(f"[seed] Waiting for OpenWebUI at {OPENWEBUI_URL}...")
    for i in range(MAX_RETRIES):
        try:
            response = httpx.get(f"{OPENWEBUI_URL}/api/version", timeout=5)
            if response.status_code == 200:
                version = response.json()
                print(f"[seed] OpenWebUI is ready! Version: {version}")
                return True
        except Exception:
            pass
        print(f"[seed] Retry {i+1}/{MAX_RETRIES}...")
        time.sleep(RETRY_INTERVAL)

    print("[seed] ERROR: OpenWebUI did not start in time")
    return False


def get_auth_token():
    """
    Create an admin account and get auth token.
    OpenWebUI requires auth for API calls.
    """
    # Try to sign up as admin (first user becomes admin)
    signup_data = {
        "name": "Admin",
        "email": "admin@mts-ai.local",
        "password": "adminpassword123",
    }

    try:
        # Try to sign up
        response = httpx.post(
            f"{OPENWEBUI_URL}/api/v1/auths/signup",
            json=signup_data,
            timeout=10,
        )
        if response.status_code == 200:
            token = response.json().get("token")
            print("[seed] Admin account created")
            return token
    except Exception as e:
        print(f"[seed] Signup failed: {e}")

    # If signup fails, try to sign in (account already exists)
    try:
        response = httpx.post(
            f"{OPENWEBUI_URL}/api/v1/auths/signin",
            json={"email": signup_data["email"], "password": signup_data["password"]},
            timeout=10,
        )
        if response.status_code == 200:
            token = response.json().get("token")
            print("[seed] Signed in as admin")
            return token
    except Exception as e:
        print(f"[seed] Signin failed: {e}")

    return None


def read_file(path: str) -> str:
    """Read a Python file and return its content."""
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def upload_tool(token: str, tool_id: str, name: str, description: str, filepath: str):
    """Upload a tool to OpenWebUI via REST API."""
    content = read_file(filepath)

    payload = {
        "id": tool_id,
        "name": name,
        "content": content,
        "meta": {
            "name": name,
            "description": description,
        }
    }

    headers = {"Authorization": f"Bearer {token}"}

    try:
        # Try to create
        response = httpx.post(
            f"{OPENWEBUI_URL}/api/v1/tools/create",
            json=payload,
            headers=headers,
            timeout=10,
        )
        if response.status_code == 200:
            print(f"[seed] ✅ Tool '{name}' created")
            return True

        # If already exists (400 ID_TAKEN), update it using the /id/{id}/update endpoint
        if response.status_code in (400, 409):
            response = httpx.post(
                f"{OPENWEBUI_URL}/api/v1/tools/id/{tool_id}/update",
                json=payload,
                headers=headers,
                timeout=10,
            )
            if response.status_code == 200:
                print(f"[seed] 🔄 Tool '{name}' updated")
                return True

        print(f"[seed] ❌ Failed to upload tool '{name}': {response.status_code} {response.text}")
        return False

    except Exception as e:
        print(f"[seed] ❌ Error uploading tool '{name}': {e}")
        return False


def upload_function(token: str, func_id: str, name: str, description: str, filepath: str, func_type: str = "filter"):
    """Upload a function to OpenWebUI via REST API."""
    content = read_file(filepath)

    payload = {
        "id": func_id,
        "name": name,
        "content": content,
        "type": func_type,
        "is_active": True,
        "is_global": True,  # Apply to all models
        "meta": {
            "name": name,
            "description": description,
        }
    }

    headers = {"Authorization": f"Bearer {token}"}

    try:
        # Try to create
        response = httpx.post(
            f"{OPENWEBUI_URL}/api/v1/functions/create",
            json=payload,
            headers=headers,
            timeout=10,
        )
        if response.status_code == 200:
            print(f"[seed] ✅ Function '{name}' created (type={func_type})")
        # If already exists, update using the /id/{id}/update endpoint
        elif response.status_code in (400, 409):
            response = httpx.post(
                f"{OPENWEBUI_URL}/api/v1/functions/id/{func_id}/update",
                json=payload,
                headers=headers,
                timeout=10,
            )
            if response.status_code == 200:
                print(f"[seed] 🔄 Function '{name}' updated")
            else:
                print(f"[seed] ❌ Failed to update function '{name}': {response.status_code} {response.text}")
                return False
        else:
            print(f"[seed] ❌ Failed to create function '{name}': {response.status_code} {response.text}")
            return False

        # Check current state before toggling (toggle is a FLIP, not a SET)
        try:
            state_resp = httpx.get(
                f"{OPENWEBUI_URL}/api/v1/functions/id/{func_id}",
                headers=headers,
                timeout=5,
            )
            if state_resp.status_code == 200:
                state = state_resp.json()
                is_active = state.get("is_active", False)
                is_global = state.get("is_global", False)

                if not is_active:
                    httpx.post(
                        f"{OPENWEBUI_URL}/api/v1/functions/id/{func_id}/toggle",
                        json={},
                        headers=headers,
                        timeout=5,
                    )
                    print(f"[seed] ⚡ Function '{name}' activated")
                else:
                    print(f"[seed] ✔️ Function '{name}' already active")

                if not is_global:
                    httpx.post(
                        f"{OPENWEBUI_URL}/api/v1/functions/id/{func_id}/toggle/global",
                        json={},
                        headers=headers,
                        timeout=5,
                    )
                    print(f"[seed] 🌐 Function '{name}' set to global")
                else:
                    print(f"[seed] ✔️ Function '{name}' already global")
        except Exception as e:
            print(f"[seed] ⚠️ Could not check/toggle function state: {e}")

        return True

    except Exception as e:
        print(f"[seed] ❌ Error uploading function '{name}': {e}")
        return False


def upload_model(token: str, model_id: str, name: str, description: str):
    """Upload a custom model to OpenWebUI via REST API."""
    payload = {
        "id": model_id,
        "name": name,
        "base_model_id": "",
        "meta": {
            "description": description,
            "profile_image_url": "/favicon.png",
        },
        "params": {}
    }

    headers = {"Authorization": f"Bearer {token}"}

    try:
        response = httpx.post(
            f"{OPENWEBUI_URL}/api/v1/models/create",
            json=payload,
            headers=headers,
            timeout=10,
        )
        if response.status_code == 200:
            print(f"[seed] ✅ Model '{name}' created")
            return True

        if response.status_code in (400, 401, 403, 409):
            response = httpx.post(
                f"{OPENWEBUI_URL}/api/v1/models/model/update",
                json=payload,
                headers=headers,
                timeout=10,
            )
            if response.status_code == 200:
                print(f"[seed] 🔄 Model '{name}' updated")
                return True

        print(f"[seed] ❌ Failed to upload model '{name}': {response.status_code} {response.text}")
        return False
    except Exception as e:
        print(f"[seed] ❌ Error uploading model '{name}': {e}")
        return False


def main():
    print("=" * 60)
    print("[seed] MTS AI Workspace — Auto Seed Script")
    print("=" * 60)

    # Step 1: Wait for OpenWebUI
    if not wait_for_openwebui():
        sys.exit(1)

    # Step 2: Get auth token
    token = get_auth_token()
    if not token:
        print("[seed] WARNING: Could not authenticate. Skipping seed.")
        sys.exit(0)

    # Step 4: Upload Tools
    tools = [
        {
            "id": "image_gen_tool",
            "name": "🖼️ Image Generator",
            "description": "Генерация изображений через Pollinations AI. Вызовите generate_image(prompt) для создания картинки.",
            "filepath": f"{TOOLS_DIR}/image_gen_tool.py",
        },
        {
            "id": "web_scraper_tool",
            "name": "🌐 Web Scraper",
            "description": "Парсинг веб-страниц и извлечение контента в markdown. Вызовите scrape_url(url) для чтения страницы.",
            "filepath": f"{TOOLS_DIR}/web_scraper_tool.py",
        },
        {
            "id": "deep_research_tool",
            "name": "🔬 Deep Research",
            "description": "Глубокое исследование темы: декомпозиция запроса, поиск через SearXNG, парсинг через Jina Reader, синтез отчёта. Вызовите deep_research(topic) для исследования.",
            "filepath": f"{TOOLS_DIR}/deep_research_tool.py",
        },
    ]

    for tool in tools:
        if os.path.exists(tool["filepath"]):
            upload_tool(token, tool["id"], tool["name"], tool["description"], tool["filepath"])
        else:
            print(f"[seed] ⚠️ Tool file not found: {tool['filepath']}")

    # Step 5: Upload Filter Functions
    functions = [
        {
            "id": "auto_router_filter",
            "name": "🧠 Auto Router",
            "description": "Автоматический выбор модели на основе содержимого запроса (код → kodify, длинный контекст → cotype, изображения → VLM)",
            "filepath": f"{FUNCTIONS_DIR}/auto_router_filter.py",
            "type": "filter",
        },
        {
            "id": "memory_extract_filter",
            "name": "💾 Memory Extractor (Outlet)",
            "description": "Автоматическое извлечение фактов из контекста общения (role, preferences, project info) каждые N сообщений (Outlet Filter)",
            "filepath": f"{FUNCTIONS_DIR}/memory_extract_filter.py",
            "type": "filter",
        },
        {
            "id": "context_inject_filter",
            "name": "🧠 Context Injector (Inlet)",
            "description": "Предзагрузка фактов из памяти перед отправкой запроса к LLM для повышения персонализации (Inlet Filter)",
            "filepath": f"{FUNCTIONS_DIR}/context_inject_filter.py",
            "type": "filter",
        },
        {
            "id": "image_gen_pipe",
            "name": "🖼️ Image Generation (qwen-image)",
            "description": "Генерация изображений через MWS GPT API. Модели qwen-image и qwen-image-lightning появятся в выпадающем списке.",
            "filepath": f"{FUNCTIONS_DIR}/image_gen_pipe.py",
            "type": "pipe",
        },
    ]

    for func in functions:
        if os.path.exists(func["filepath"]):
            upload_function(
                token, func["id"], func["name"], func["description"],
                func["filepath"], func.get("type", "filter")
            )
        else:
            print(f"[seed] ⚠️ Function file not found: {func['filepath']}")

    print()
    print("=" * 60)
    print("[seed] ✅ Seeding complete!")
    print("[seed] Open http://localhost:8080 to start using MTS AI Workspace")
    print("=" * 60)


if __name__ == "__main__":
    main()
