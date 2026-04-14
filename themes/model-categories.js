/**
 * MTS AI Workspace — Model Category Tags
 * =======================================
 * Перехватывает /api/models и инжектирует категориальные теги в каждую модель.
 * Open WebUI сам рендерит теги как фильтр-кнопки через существующий Svelte-компонент.
 * Скрывает лишние нативные кнопки "Внешнее / Локальное / Прямое".
 */
(function () {
  'use strict';

  // Правила определения категории по ID модели (порядок важен — первое совпадение)
  const RULES = [
    { tag: 'Логика',   keywords: ['qwq', 'deepseek-r1', 'r1-distill', 'o1-', 'o3-'] },
    { tag: 'Код',      keywords: ['coder', 'codestral'] },
    { tag: 'Зрение',   keywords: ['-vl-', 'vl-72', '-vl', 'vision', 'cotype'] },
    { tag: 'Картинки', keywords: ['image', 'dall-e', 'flux', 'lightning'] },
    { tag: 'Аудио',    keywords: ['whisper', 'asr', 'stt', 'speech'] },
    { tag: 'Текст',    keywords: [] }, // catch-all — всё остальное
  ];

  function tagForModel(modelId) {
    const id = (modelId || '').toLowerCase();
    for (const rule of RULES) {
      if (rule.keywords.length === 0) return rule.tag; // catch-all
      if (rule.keywords.some(k => id.includes(k))) return rule.tag;
    }
    return 'Текст';
  }

  // ─── Перехват /api/models ────────────────────────────────────────────────────
  const _origFetch = window.fetch;

  window.fetch = async function (...args) {
    const response = await _origFetch.apply(this, args);

    try {
      const url = typeof args[0] === 'string' ? args[0]
        : args[0] instanceof Request ? args[0].url : '';

      // Только точный /api/models (без вложенных путей вроде /api/models/base)
      if (/\/api\/models\/?(\?[^]*)?$/.test(url)) {
        const clone = response.clone();
        let data;
        try { data = await clone.json(); } catch (_) { return response; }

        // Список может быть корневым массивом или в поле .data
        const list = Array.isArray(data) ? data
          : (Array.isArray(data?.data) ? data.data : null);

        if (!list) return response;

        // Добавляем тег категории каждой модели
        list.forEach(model => {
          const modelId = model.id || model.name || '';
          const catTag = tagForModel(modelId);

          if (!model.info) model.info = {};
          if (!model.info.meta) model.info.meta = {};
          const existing = Array.isArray(model.info.meta.tags) ? model.info.meta.tags : [];

          // Не дублируем тег
          if (!existing.some(t => t.name === catTag)) {
            model.info.meta.tags = [...existing, { name: catTag }];
          }
        });

        const newData = Array.isArray(data) ? list : { ...data, data: list };

        // Строим заголовки без content-length (тело изменилось — длина другая)
        const newHeaders = new Headers();
        response.headers.forEach((v, k) => {
          if (k.toLowerCase() !== 'content-length') newHeaders.set(k, v);
        });

        return new Response(JSON.stringify(newData), {
          status: response.status,
          statusText: response.statusText,
          headers: newHeaders,
        });
      }
    } catch (_) { /* при любой ошибке возвращаем оригинальный ответ */ }

    return response;
  };

  // ─── Скрываем нативные кнопки "Внешнее / Локальное / Прямое" ────────────────
  const HIDE_LABELS = new Set([
    'external', 'внешнее',
    'local', 'локальное',
    'direct', 'прямое',
  ]);

  const uiObserver = new MutationObserver(() => {
    document.querySelectorAll('button[aria-pressed]').forEach(btn => {
      const label = btn.textContent.trim().toLowerCase();
      if (HIDE_LABELS.has(label)) btn.style.display = 'none';
    });
  });

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
      uiObserver.observe(document.body, { childList: true, subtree: true });
    });
  } else {
    uiObserver.observe(document.body, { childList: true, subtree: true });
  }

})();
