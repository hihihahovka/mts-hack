"""
Smoke Test — MTS AI Workspace
==============================
Автоматическая проверка работоспособности всех компонентов.
Читает порты из .env файла (или использует дефолты из docker-compose).
Запуск: python scripts/smoke_test.py  или  make test
"""

import sys
import json
import os
import urllib.request
import urllib.error
import time
from pathlib import Path


def load_dotenv():
    """Read .env file and return dict of key=value pairs."""
    env = {}
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if env_path.exists():
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, _, value = line.partition("=")
                    # Strip inline comments
                    value = value.split("#")[0].strip()
                    env[key.strip()] = value
    return env


# Load ports from .env (same defaults as docker-compose.yml)
_env = load_dotenv()
WEBUI_PORT = _env.get("WEBUI_PORT", "8080")
SEARXNG_PORT = _env.get("SEARXNG_PORT", "8888")
WHISPER_PORT = _env.get("WHISPER_PORT", "9000")

OPENWEBUI_URL = f"http://localhost:{WEBUI_PORT}"
SEARXNG_URL = f"http://localhost:{SEARXNG_PORT}"
WHISPER_URL = f"http://localhost:{WHISPER_PORT}"

# Учётные данные admin (создаются seed'ом)
ADMIN_EMAIL = "admin@mts-ai.local"
ADMIN_PASSWORD = "adminpassword123"

passed = 0
failed = 0
warnings = 0


def test(name, func):
    """Run a test and track results."""
    global passed, failed, warnings
    try:
        result = func()
        if result is True:
            print(f"  ✅ {name}")
            passed += 1
        elif result == "warn":
            print(f"  ⚠️  {name}")
            warnings += 1
        else:
            print(f"  ❌ {name}")
            failed += 1
    except Exception as e:
        print(f"  ❌ {name} — {e}")
        failed += 1


def http_get(url, headers=None, timeout=10):
    """Simple HTTP GET."""
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8"))


def http_post(url, data, headers=None, timeout=10):
    """Simple HTTP POST with JSON."""
    body = json.dumps(data).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers={**(headers or {}), "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8"))


def get_token():
    """Sign in as admin and get auth token."""
    try:
        status, data = http_post(
            f"{OPENWEBUI_URL}/api/v1/auths/signin",
            {"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        )
        if status == 200 and "token" in data:
            return data["token"]
    except Exception:
        pass
    return None


def main():
    global passed, failed, warnings

    print("=" * 56)
    print("  MTS AI Workspace — Smoke Test")
    print("=" * 56)
    print(f"  Порты: WebUI={WEBUI_PORT} SearXNG={SEARXNG_PORT} Whisper={WHISPER_PORT}")
    print()

    # ─────────────────────────────────────────
    # 1. Connectivity
    # ─────────────────────────────────────────
    print("📡 Базовая связность:")

    def check_openwebui():
        status, data = http_get(f"{OPENWEBUI_URL}/api/version")
        return status == 200

    def check_searxng():
        req = urllib.request.Request(SEARXNG_URL)
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status == 200

    def check_whisper():
        status, data = http_get(f"{WHISPER_URL}/health")
        return status == 200

    test(f"OpenWebUI отвечает (:{WEBUI_PORT})", check_openwebui)
    test(f"SearXNG отвечает (:{SEARXNG_PORT})", check_searxng)
    test(f"Whisper API отвечает (:{WHISPER_PORT})", check_whisper)

    # ─────────────────────────────────────────
    # 2. Auth
    # ─────────────────────────────────────────
    print("\n🔐 Авторизация:")
    token = get_token()

    def check_auth():
        return token is not None

    test("Admin аккаунт (admin@mts-ai.local)", check_auth)

    if not token:
        print("\n  ⛔ Не удалось авторизоваться. Остальные тесты пропущены.")
        print_summary()
        return

    auth_headers = {"Authorization": f"Bearer {token}"}

    # ─────────────────────────────────────────
    # 3. Models
    # ─────────────────────────────────────────
    print("\n🧠 Модели MWS GPT:")

    def check_models():
        status, data = http_get(
            f"{OPENWEBUI_URL}/api/models", headers=auth_headers
        )
        if status != 200:
            return False
        model_ids = []
        for m in data.get("data", []):
            mid = m.get("id", "")
            model_ids.append(mid)
        return model_ids

    model_ids = []
    try:
        model_ids = check_models()
    except Exception:
        pass

    test(f"Всего моделей в системе: {len(model_ids)}", lambda: len(model_ids) > 0)

    # Critical model — must exist
    def check_alpha():
        return any("mws-gpt-alpha" in mid for mid in model_ids)
    test("Модель 'mws-gpt-alpha' доступна", check_alpha)

    # Optional models — warn if missing (depends on API key)
    optional_models = ["kodify-2.0", "cotype-preview-32k"]
    for model in optional_models:
        def check_model(m=model):
            if any(m in mid for mid in model_ids):
                return True
            return "warn"  # Missing = warning, not error
        test(f"Модель '{model}' доступна (опционально)", check_model)

    # Check pipe models
    def check_pipe_model():
        return any("qwen-image" in mid for mid in model_ids)
    test("Pipe 'qwen-image' в списке моделей", check_pipe_model)

    # ─────────────────────────────────────────
    # 4. Tools
    # ─────────────────────────────────────────
    print("\n🔧 Tools:")

    def get_tools():
        status, data = http_get(
            f"{OPENWEBUI_URL}/api/v1/tools/", headers=auth_headers
        )
        if status == 200:
            return [t.get("id", "") for t in data]
        return []

    tool_ids = []
    try:
        tool_ids = get_tools()
    except Exception:
        pass

    expected_tools = [
        ("web_scraper_tool", "Web Scraper"),
        ("deep_research_tool", "Deep Research"),
    ]
    for tool_id, tool_name in expected_tools:
        def check_tool(tid=tool_id):
            return tid in tool_ids
        test(f"Tool '{tool_name}' загружен", check_tool)

    # Check that deprecated tool is NOT loaded
    def check_no_image_tool():
        return "image_gen_tool" not in tool_ids
    test("image_gen_tool НЕ загружен (deprecated)", check_no_image_tool)

    # ─────────────────────────────────────────
    # 5. Functions
    # ─────────────────────────────────────────
    print("\n⚡ Functions (Filters/Pipes):")

    def get_functions():
        status, data = http_get(
            f"{OPENWEBUI_URL}/api/v1/functions/", headers=auth_headers
        )
        if status == 200:
            return {f.get("id", ""): f for f in data}
        return {}

    func_map = {}
    try:
        func_map = get_functions()
    except Exception:
        pass

    expected_functions = [
        ("auto_router_filter", "Auto Router"),
        ("memory_extract_filter", "Memory Extractor"),
        ("context_inject_filter", "Context Injector"),
        ("image_gen_pipe", "Image Generation Pipe"),
    ]
    for func_id, func_name in expected_functions:
        def check_func(fid=func_id):
            return fid in func_map
        test(f"Function '{func_name}' загружена", check_func)

    # Check active + global status
    for func_id, func_name in expected_functions:
        func_data = func_map.get(func_id, {})
        is_active = func_data.get("is_active", False)
        is_global = func_data.get("is_global", False)

        def check_active(a=is_active, g=is_global, fid=func_id):
            if fid not in func_map:
                return False
            if a and g:
                return True
            return "warn"

        test(f"  ↳ '{func_name}' active={is_active} global={is_global}", check_active)

    # ─────────────────────────────────────────
    # 6. TTS Configuration
    # ─────────────────────────────────────────
    print("\n🔊 TTS:")

    def check_tts():
        status, data = http_get(
            f"{OPENWEBUI_URL}/api/v1/audio/config", headers=auth_headers
        )
        if status == 200:
            engine = data.get("tts", {}).get("ENGINE", "")
            if engine and engine != "":
                return True
        return False

    test("TTS Engine настроен", check_tts)

    # ─────────────────────────────────────────
    # 7. SearXNG Search
    # ─────────────────────────────────────────
    print("\n🔍 Web Search:")

    def check_search():
        try:
            req = urllib.request.Request(f"{SEARXNG_URL}/search?q=test&format=json")
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                results = data.get("results", [])
                return len(results) > 0
        except Exception:
            return "warn"

    test("SearXNG возвращает результаты", check_search)

    # ─────────────────────────────────────────
    # Summary
    # ─────────────────────────────────────────
    print_summary()


def print_summary():
    print()
    print("=" * 56)
    total = passed + failed + warnings
    print(f"  Результат: {passed}/{total} пройдено", end="")
    if warnings:
        print(f", {warnings} предупреждений", end="")
    if failed:
        print(f", {failed} ошибок", end="")
    print()

    if failed == 0:
        print("  🎉 Все проверки пройдены!")
    else:
        print("  ⚠️  Есть проблемы — проверьте логи: docker logs seed-local")

    print("=" * 56)
    sys.exit(1 if failed > 0 else 0)


if __name__ == "__main__":
    main()
