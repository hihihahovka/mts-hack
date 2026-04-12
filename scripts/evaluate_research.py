#!/usr/bin/env python3
"""
Deep Research Quality Score (DRQS) — Evaluator
================================================
Оценивает качество вывода Deep Research Tool по 6 метрикам:

  1. Source Coverage    — кол-во уникальных источников (ссылок)
  2. Structure Quality  — наличие заголовков, списков, секций
  3. Citation Density   — % утверждений с подкреплением ссылкой
  4. Content Depth      — длина и информативность ответа
  5. Relevance (LLM)    — оценка релевантности судьёй-LLM
  6. Factual Grounding  — оценка фактической обоснованности судьёй-LLM

Использование:
  # Оценить один ответ (скопированный из UI):
  python scripts/evaluate_research.py --text "## Ответ ..."

  # Оценить из файла:
  python scripts/evaluate_research.py --file output.md

  # Запустить бенчмарк (все тестовые запросы через API):
  python scripts/evaluate_research.py --benchmark
"""

import argparse
import json
import os
import re
import sys
import time
from dataclasses import dataclass, field
from typing import List, Optional

# ═══════════════════════════════════════════════════════════
# МЕТРИКИ
# ═══════════════════════════════════════════════════════════

@dataclass
class DRQSScore:
    """Deep Research Quality Score — результат оценки."""
    query: str = ""
    # Структурные метрики (0-10)
    source_coverage: float = 0.0       # Кол-во уникальных источников
    structure_quality: float = 0.0     # Заголовки, списки, секции
    citation_density: float = 0.0      # Доля ссылок на факты
    content_depth: float = 0.0         # Глубина контента
    # LLM-judge метрики (0-10)
    relevance: float = 0.0            # Релевантность ответа
    factual_grounding: float = 0.0    # Фактическая обоснованность
    # Дополнительно
    response_time_s: float = 0.0      # Время ответа

    @property
    def composite(self) -> float:
        """Взвешенный итоговый балл DRQS (0-10)."""
        weights = {
            "source_coverage": 0.15,
            "structure_quality": 0.10,
            "citation_density": 0.20,
            "content_depth": 0.10,
            "relevance": 0.25,
            "factual_grounding": 0.20,
        }
        total = (
            self.source_coverage * weights["source_coverage"] +
            self.structure_quality * weights["structure_quality"] +
            self.citation_density * weights["citation_density"] +
            self.content_depth * weights["content_depth"] +
            self.relevance * weights["relevance"] +
            self.factual_grounding * weights["factual_grounding"]
        )
        return round(total, 2)

    def to_dict(self) -> dict:
        return {
            "query": self.query,
            "composite_drqs": self.composite,
            "source_coverage": self.source_coverage,
            "structure_quality": self.structure_quality,
            "citation_density": self.citation_density,
            "content_depth": self.content_depth,
            "relevance": self.relevance,
            "factual_grounding": self.factual_grounding,
            "response_time_s": self.response_time_s,
        }


# ═══════════════════════════════════════════════════════════
# СТРУКТУРНЫЕ МЕТРИКИ (без LLM, чистый парсинг)
# ═══════════════════════════════════════════════════════════

def count_unique_urls(text: str) -> int:
    """Считает уникальные URL в тексте."""
    urls = set(re.findall(r'https?://[^\s\)\]\"\'<>]+', text))
    return len(urls)


def evaluate_source_coverage(text: str) -> float:
    """
    Source Coverage: 0-10.
    0 ссылок = 0, 1 = 3, 2 = 5, 3 = 7, 4 = 8, 5+ = 10
    """
    n = count_unique_urls(text)
    scale = {0: 0, 1: 3, 2: 5, 3: 7, 4: 8}
    if n >= 5:
        return 10.0
    return float(scale.get(n, 5))


def evaluate_structure(text: str) -> float:
    """
    Structure Quality: оценивает наличие структурных элементов.
    Заголовки (##), буллеты (-/•), нумерованные списки, разделители.
    """
    score = 0.0
    # Заголовки
    headings = len(re.findall(r'^#{1,3}\s', text, re.MULTILINE))
    score += min(headings * 1.5, 4.0)

    # Списки
    bullets = len(re.findall(r'^\s*[-•*]\s', text, re.MULTILINE))
    numbered = len(re.findall(r'^\s*\d+\.\s', text, re.MULTILINE))
    score += min((bullets + numbered) * 0.5, 3.0)

    # Абзацы (>3 строки текста)
    paragraphs = len(re.findall(r'\n\n.{50,}', text))
    score += min(paragraphs * 0.5, 2.0)

    # Разделители (---)
    if re.search(r'^---', text, re.MULTILINE):
        score += 1.0

    return min(score, 10.0)


def evaluate_citation_density(text: str) -> float:
    """
    Citation Density: какой % утверждений сопровождается ссылкой.
    Проверяем: строки с фактами (длина > 30) и ссылки рядом.
    """
    lines = text.strip().split('\n')
    fact_lines = [l for l in lines if len(l.strip()) > 30 and not l.strip().startswith('#')]
    if not fact_lines:
        return 5.0

    cited_lines = 0
    for line in fact_lines:
        if re.search(r'https?://', line) or re.search(r'\[.*?\]\(.*?\)', line):
            cited_lines += 1

    ratio = cited_lines / len(fact_lines)

    # Секция "Источники" даёт бонус
    if re.search(r'##\s*(Источники|Sources|Ссылки)', text, re.IGNORECASE):
        ratio = min(ratio + 0.3, 1.0)

    return round(ratio * 10, 1)


def evaluate_content_depth(text: str) -> float:
    """
    Content Depth: оценивает информативность по длине.
    <200 символов = плохо, 200-500 = нормально, 500-2000 = хорошо, 2000+ = отлично.
    """
    length = len(text.strip())
    if length < 100:
        return 1.0
    elif length < 300:
        return 4.0
    elif length < 700:
        return 6.0
    elif length < 1500:
        return 8.0
    elif length < 3000:
        return 9.5
    else:
        return 10.0


# ═══════════════════════════════════════════════════════════
# LLM-AS-JUDGE (оценка через LLM)
# ═══════════════════════════════════════════════════════════

def llm_judge(query: str, text: str) -> dict:
    """
    Вызывает LLM для оценки Relevance и Factual Grounding.
    Возвращает {"relevance": float, "factual_grounding": float}.
    """
    try:
        import httpx
    except ImportError:
        print("⚠️  httpx не установлен, LLM-оценка пропущена")
        return {"relevance": 5.0, "factual_grounding": 5.0}

    api_key = os.environ.get("MWS_API_KEY") or os.environ.get("OPENAI_API_KEY", "")
    base_url = os.environ.get("LLM_BASE_URL", "https://api.gpt.mws.ru/v1")
    model = os.environ.get("LLM_MODEL", "mws-gpt-alpha")

    if not api_key:
        print("⚠️  MWS_API_KEY не задан, LLM-оценка пропущена")
        return {"relevance": 5.0, "factual_grounding": 5.0}

    system = """Ты — строгий оценщик качества ответов поисковой системы.
Тебе дан ЗАПРОС пользователя и ОТВЕТ системы.

Оцени ответ по двум критериям, каждый от 0 до 10:

1. **relevance** — насколько ответ релевантен запросу?
   - 0-3: ответ не по теме или мусор
   - 4-6: частично отвечает, но есть пробелы
   - 7-9: хорошо отвечает на вопрос
   - 10: идеально полный и точный ответ

2. **factual_grounding** — насколько утверждения подкреплены источниками?
   - 0-3: голословные утверждения без ссылок
   - 4-6: есть ссылки, но не все факты подкреплены
   - 7-9: большинство фактов имеют источники
   - 10: каждый факт подкреплён ссылкой

ВАЖНО: Верни ТОЛЬКО JSON, без пояснений.
Формат: {"relevance": 7.5, "factual_grounding": 6.0}"""

    prompt = f"ЗАПРОС: {query}\n\nОТВЕТ СИСТЕМЫ:\n{text[:3000]}"

    try:
        resp = httpx.post(
            f"{base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            },
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt}
                ]
            },
            timeout=30
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
        # Извлекаем JSON
        match = re.search(r'\{.*?\}', content.replace('\n', ' '), re.DOTALL)
        if match:
            scores = json.loads(match.group(0))
            return {
                "relevance": min(float(scores.get("relevance", 5)), 10),
                "factual_grounding": min(float(scores.get("factual_grounding", 5)), 10),
            }
    except Exception as e:
        print(f"⚠️  LLM judge error: {e}")

    return {"relevance": 5.0, "factual_grounding": 5.0}


# ═══════════════════════════════════════════════════════════
# ГЛАВНАЯ ФУНКЦИЯ ОЦЕНКИ
# ═══════════════════════════════════════════════════════════

def evaluate(query: str, text: str, response_time: float = 0.0, use_llm: bool = True) -> DRQSScore:
    """Полная оценка одного ответа Deep Research."""
    score = DRQSScore(query=query, response_time_s=response_time)

    # Структурные метрики
    score.source_coverage = evaluate_source_coverage(text)
    score.structure_quality = evaluate_structure(text)
    score.citation_density = evaluate_citation_density(text)
    score.content_depth = evaluate_content_depth(text)

    # LLM-judge
    if use_llm:
        llm_scores = llm_judge(query, text)
        score.relevance = llm_scores["relevance"]
        score.factual_grounding = llm_scores["factual_grounding"]
    else:
        score.relevance = 5.0
        score.factual_grounding = 5.0

    return score


def print_report(score: DRQSScore):
    """Красивый вывод результатов."""
    bar = lambda v: "█" * int(v) + "░" * (10 - int(v))

    print("\n" + "═" * 55)
    print("  📊 DEEP RESEARCH QUALITY SCORE (DRQS)")
    print("═" * 55)

    if score.query:
        print(f"  Запрос: {score.query[:60]}...")

    print(f"""
  📰 Source Coverage     {bar(score.source_coverage)}  {score.source_coverage:.1f}/10
  📐 Structure Quality   {bar(score.structure_quality)}  {score.structure_quality:.1f}/10
  🔗 Citation Density    {bar(score.citation_density)}  {score.citation_density:.1f}/10
  📚 Content Depth       {bar(score.content_depth)}  {score.content_depth:.1f}/10
  🎯 Relevance (LLM)     {bar(score.relevance)}  {score.relevance:.1f}/10
  ✅ Factual Ground (LLM) {bar(score.factual_grounding)}  {score.factual_grounding:.1f}/10
""")

    composite = score.composite
    grade = (
        "🏆 Отлично" if composite >= 8 else
        "✅ Хорошо" if composite >= 6 else
        "⚠️ Средне" if composite >= 4 else
        "❌ Плохо"
    )

    print(f"  ══════════════════════════════════════")
    print(f"  ИТОГО DRQS:  {composite:.1f}/10  {grade}")
    if score.response_time_s > 0:
        print(f"  ⏱ Время ответа: {score.response_time_s:.1f} сек")
    print(f"  ══════════════════════════════════════\n")


# ═══════════════════════════════════════════════════════════
# БЕНЧМАРК (автоматический прогон тестовых запросов)
# ═══════════════════════════════════════════════════════════

TEST_QUERIES = [
    "Что такое Gemini от Google и какие у него возможности?",
    "Топ 5 фреймворков для бэкенда на Python в 2025",
    "Сравнение React и Vue.js для нового проекта",
    "Как работает RAG (Retrieval-Augmented Generation)?",
    "Последние новости в сфере искусственного интеллекта",
]


def run_benchmark():
    """
    Прогоняет тестовые запросы через Deep Research Tool
    и считает средний DRQS.
    """
    try:
        import httpx
    except ImportError:
        print("❌ pip install httpx")
        return

    print("\n🚀 Запуск бенчмарка Deep Research Tool...")
    print(f"   Тестовых запросов: {len(TEST_QUERIES)}\n")

    openwebui_url = os.environ.get("OPENWEBUI_URL", "http://localhost:8080")
    api_key = os.environ.get("OPENWEBUI_API_KEY", "")

    scores = []

    for i, query in enumerate(TEST_QUERIES, 1):
        print(f"  [{i}/{len(TEST_QUERIES)}] {query[:50]}...")

        start = time.time()

        try:
            # Вызываем OpenWebUI API для chat completion
            resp = httpx.post(
                f"{openwebui_url}/api/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "mws-gpt-alpha",
                    "messages": [{"role": "user", "content": query}],
                },
                timeout=120,
            )
            resp.raise_for_status()
            text = resp.json()["choices"][0]["message"]["content"]
            elapsed = time.time() - start

            score = evaluate(query, text, response_time=elapsed, use_llm=True)
            scores.append(score)
            print(f"         DRQS: {score.composite:.1f}/10  ({elapsed:.1f}s)")

        except Exception as e:
            print(f"         ❌ Ошибка: {e}")
            continue

    if not scores:
        print("\n❌ Ни один запрос не выполнился.")
        return

    # Средние баллы
    avg = DRQSScore(query="СРЕДНЕЕ")
    for attr in ["source_coverage", "structure_quality", "citation_density",
                 "content_depth", "relevance", "factual_grounding", "response_time_s"]:
        setattr(avg, attr, sum(getattr(s, attr) for s in scores) / len(scores))

    print("\n" + "━" * 55)
    print("  📈 ИТОГОВЫЙ ОТЧЁТ БЕНЧМАРКА")
    print("━" * 55)
    print_report(avg)

    # JSON-отчёт
    report = {
        "benchmark_date": time.strftime("%Y-%m-%d %H:%M"),
        "total_queries": len(TEST_QUERIES),
        "successful": len(scores),
        "average_drqs": avg.composite,
        "average_response_time_s": round(avg.response_time_s, 1),
        "per_query": [s.to_dict() for s in scores],
    }

    report_path = "scripts/benchmark_results.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"  💾 Отчёт сохранён: {report_path}\n")


# ═══════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="DRQS — Deep Research Quality Score")
    parser.add_argument("--text", type=str, help="Текст ответа для оценки (в кавычках)")
    parser.add_argument("--file", type=str, help="Файл с ответом (.md/.txt)")
    parser.add_argument("--query", type=str, default="", help="Исходный запрос пользователя")
    parser.add_argument("--benchmark", action="store_true", help="Прогнать полный бенчмарк")
    parser.add_argument("--no-llm", action="store_true", help="Пропустить LLM-оценку")

    args = parser.parse_args()

    # Загрузить .env если есть
    env_path = os.path.join(os.path.dirname(__file__), '..', '.env')
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, _, val = line.partition('=')
                    os.environ.setdefault(key.strip(), val.strip())

    if args.benchmark:
        run_benchmark()
        return

    # Получаем текст
    text = ""
    if args.text:
        text = args.text
    elif args.file:
        with open(args.file, "r", encoding="utf-8") as f:
            text = f.read()
    else:
        # Читаем из stdin
        print("📋 Вставьте ответ Deep Research (Ctrl+D для завершения):")
        text = sys.stdin.read()

    if not text.strip():
        print("❌ Пустой текст. Укажите --text, --file или вставьте в stdin.")
        return

    query = args.query or "Не указан"
    score = evaluate(query, text, use_llm=not args.no_llm)
    print_report(score)


if __name__ == "__main__":
    main()
