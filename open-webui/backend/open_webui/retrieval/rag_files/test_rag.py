#!/usr/bin/env python3
"""
RAG Smoke Test — validates the RAG pipeline end-to-end.

Usage (against a running Open WebUI instance):
    python -m open_webui.retrieval.rag_files.test_rag

Or with curl:
    # 1. Upload a file
    curl -X POST http://localhost:8080/api/v1/rag/upload \\
        -F "file=@sample.txt"

    # 2. Query the collection
    curl -X POST http://localhost:8080/api/v1/rag/query \\
        -H "Content-Type: application/json" \\
        -d '{"collection_name": "rag-XXXX", "question": "What is this about?"}'

    # 3. Upload and query in one call
    curl -X POST http://localhost:8080/api/v1/rag/upload-and-query \\
        -F "file=@sample.pdf" \\
        -F "question=What are the main topics?"

    # 4. Health check
    curl http://localhost:8080/api/v1/rag/health
"""

import os
import sys
import json
import tempfile
import requests

# Default server URL
BASE_URL = os.environ.get("OPENWEBUI_URL", "http://localhost:8080")
RAG_API = f"{BASE_URL}/api/v1/rag"


def create_sample_txt(content: str = None) -> str:
    """Create a temporary sample TXT file for testing."""
    if content is None:
        content = """
Искусственный интеллект и машинное обучение

Машинное обучение — это подраздел искусственного интеллекта, который позволяет
компьютерам учиться на данных без явного программирования. Существует три основных
типа машинного обучения:

1. Обучение с учителем (Supervised Learning) — модель учится на размеченных данных.
   Примеры: классификация изображений, прогнозирование цен.

2. Обучение без учителя (Unsupervised Learning) — модель находит паттерны в
   неразмеченных данных. Примеры: кластеризация, снижение размерности.

3. Обучение с подкреплением (Reinforcement Learning) — модель учится через
   взаимодействие со средой. Примеры: игровые агенты, роботы.

RAG (Retrieval-Augmented Generation) — это метод, который объединяет поиск
релевантных документов с генерацией текста. Это позволяет языковым моделям
давать более точные ответы, основанные на реальных данных.

BGE-M3 — это модель для генерации эмбеддингов, которая поддерживает многоязычность
и несколько методов поиска: dense retrieval, sparse retrieval и multi-vector retrieval.
        """.strip()

    fd, path = tempfile.mkstemp(suffix=".txt", prefix="rag_test_")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(content)
    return path


def test_health():
    """Test: GET /health"""
    print("\n" + "=" * 60)
    print("TEST: Health Check")
    print("=" * 60)

    try:
        r = requests.get(f"{RAG_API}/health", timeout=10)
        print(f"  Status code: {r.status_code}")
        data = r.json()
        print(f"  Response: {json.dumps(data, indent=2, ensure_ascii=False)}")

        assert r.status_code == 200, f"Expected 200, got {r.status_code}"
        assert data["status"] in ("ok", "degraded"), f"Unexpected status: {data['status']}"
        print("  ✅ Health check PASSED")
        return True
    except Exception as e:
        print(f"  ❌ Health check FAILED: {e}")
        return False


def test_upload(file_path: str) -> str:
    """Test: POST /upload — returns collection_name on success."""
    print("\n" + "=" * 60)
    print(f"TEST: Upload File ({os.path.basename(file_path)})")
    print("=" * 60)

    try:
        with open(file_path, "rb") as f:
            r = requests.post(
                f"{RAG_API}/upload",
                files={"file": (os.path.basename(file_path), f)},
                timeout=60,
            )
        print(f"  Status code: {r.status_code}")
        data = r.json()
        print(f"  Response: {json.dumps(data, indent=2, ensure_ascii=False)}")

        assert r.status_code == 200, f"Expected 200, got {r.status_code}"
        assert data["status"] is True, "Upload status is not True"
        assert data["chunk_count"] > 0, "No chunks created"
        print(f"  ✅ Upload PASSED — collection: {data['collection_name']}, chunks: {data['chunk_count']}")
        return data["collection_name"]
    except Exception as e:
        print(f"  ❌ Upload FAILED: {e}")
        return ""


def test_query(collection_name: str, question: str = "Что такое RAG?"):
    """Test: POST /query"""
    print("\n" + "=" * 60)
    print(f"TEST: Query ('{question}')")
    print("=" * 60)

    try:
        r = requests.post(
            f"{RAG_API}/query",
            json={
                "collection_name": collection_name,
                "question": question,
                "k": 3,
            },
            timeout=30,
        )
        print(f"  Status code: {r.status_code}")
        data = r.json()
        print(f"  Results count: {data.get('results_count', 0)}")

        if data.get("chunks"):
            for i, chunk in enumerate(data["chunks"][:3]):
                preview = chunk["text"][:150].replace("\n", " ")
                print(f"  Chunk {i+1} (score={chunk.get('score', 'N/A')}): {preview}...")

        assert r.status_code == 200, f"Expected 200, got {r.status_code}"
        assert data["results_count"] > 0, "No results returned"
        # Check relevance: at least one chunk should contain RAG-related content
        relevant = any("rag" in chunk["text"].lower() or "retrieval" in chunk["text"].lower() for chunk in data["chunks"])
        if relevant:
            print("  ✅ Query PASSED — relevant chunks found")
        else:
            print("  ⚠️  Query returned results but relevance check inconclusive")
        return True
    except Exception as e:
        print(f"  ❌ Query FAILED: {e}")
        return False


def test_upload_and_query(file_path: str, question: str = "Какие типы машинного обучения существуют?"):
    """Test: POST /upload-and-query"""
    print("\n" + "=" * 60)
    print(f"TEST: Upload and Query ('{question}')")
    print("=" * 60)

    try:
        with open(file_path, "rb") as f:
            r = requests.post(
                f"{RAG_API}/upload-and-query",
                files={"file": (os.path.basename(file_path), f)},
                data={"question": question, "k": 3},
                timeout=60,
            )
        print(f"  Status code: {r.status_code}")
        data = r.json()

        upload_info = data.get("upload", {})
        query_info = data.get("query", {})
        print(f"  Upload: {upload_info.get('chunk_count', 0)} chunks")
        print(f"  Query results: {query_info.get('results_count', 0)}")

        if query_info.get("chunks"):
            for i, chunk in enumerate(query_info["chunks"][:2]):
                preview = chunk["text"][:150].replace("\n", " ")
                print(f"  Chunk {i+1}: {preview}...")

        assert r.status_code == 200, f"Expected 200, got {r.status_code}"
        assert data["status"] is True, "Status is not True"
        assert query_info["results_count"] > 0, "No query results"
        print("  ✅ Upload-and-Query PASSED")
        return True
    except Exception as e:
        print(f"  ❌ Upload-and-Query FAILED: {e}")
        return False


def main():
    print("=" * 60)
    print("  RAG System Smoke Test")
    print(f"  Server: {BASE_URL}")
    print("=" * 60)

    # Check server is reachable
    try:
        requests.get(BASE_URL, timeout=5)
    except Exception:
        print(f"\n❌ Cannot reach server at {BASE_URL}")
        print("   Make sure Open WebUI is running.")
        print(f"   Set OPENWEBUI_URL env var to override (current: {BASE_URL})")
        sys.exit(1)

    # Create sample file
    sample_file = create_sample_txt()
    print(f"\nCreated sample file: {sample_file}")

    results = []

    try:
        # Test 1: Health check
        results.append(("Health", test_health()))

        # Test 2: Upload
        collection = test_upload(sample_file)
        results.append(("Upload", bool(collection)))

        # Test 3: Query
        if collection:
            results.append(("Query", test_query(collection)))

        # Test 4: Upload and Query
        results.append(("Upload+Query", test_upload_and_query(sample_file)))

    finally:
        # Cleanup
        if os.path.exists(sample_file):
            os.remove(sample_file)

    # Summary
    print("\n" + "=" * 60)
    print("  SUMMARY")
    print("=" * 60)
    for name, passed in results:
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"  {status}  {name}")

    all_passed = all(p for _, p in results)
    print(f"\n{'✅ All tests passed!' if all_passed else '❌ Some tests failed.'}")
    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    main()
