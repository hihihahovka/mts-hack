/**
 * MTS AI Workspace — Model Category Tags (v4)
 * ============================================
 * Перехватывает /api/models и инжектирует теги.
 */
(function () {
  'use strict';
  console.log('[MTS] Initializing model tags interceptor...');

  const RULES = [
    { tag: 'Логика',   keywords: ['qwq', 'deepseek-r1', 'r1-distill', 'o1-', 'o3-'] },
    { tag: 'Код',      keywords: ['coder', 'codestral'] },
    { tag: 'Зрение',   keywords: ['-vl-', 'vl-72', '-vl', 'vision', 'cotype'] },
    { tag: 'Картинки', keywords: ['image', 'dall-e', 'flux', 'lightning'] },
    { tag: 'Аудио',    keywords: ['whisper', 'asr', 'stt', 'speech'] },
    { tag: 'Текст',    keywords: [] },
  ];

  function tagForModel(modelId) {
    const id = (modelId || '').toLowerCase();
    for (const rule of RULES) {
      if (rule.keywords.length === 0) return rule.tag;
      if (rule.keywords.some(k => id.includes(k))) return rule.tag;
    }
    return 'Текст';
  }

  // Очищаем кэш моделей SvelteKit (чтобы заставить его запросить с бэкенда заново)
  const keys = Object.keys(localStorage);
  keys.forEach(k => {
    if (k.includes('models') || k.includes('cache')) {
      try { localStorage.removeItem(k); } catch(e){}
    }
  });

  const _origFetch = window.fetch;

  window.fetch = async function (...args) {
    const url = typeof args[0] === 'string' ? args[0] : (args[0] && args[0].url ? args[0].url : '');
    
    // Перехват API моделей
    if (url && /\/api\/models\/?(\?[^]*)?$/.test(url)) {
      console.log('[MTS] Intercepted /api/models call');
      const response = await _origFetch.apply(this, args);
      try {
        const clone = response.clone();
        let data = await clone.json();

        const list = Array.isArray(data) ? data : (Array.isArray(data?.data) ? data.data : null);

        if (list) {
          list.forEach(model => {
            const catTag = tagForModel(model.id || model.name);
            if (!model.info) model.info = {};
            if (!model.info.meta) model.info.meta = {};
            
            // Если теги не массив, делаем массивом
            let tags = model.info.meta.tags;
            if (!Array.isArray(tags)) tags = [];
            
            // Удаляем старые теги категорий, если есть (на всякий случай)
            const allCatTags = RULES.map(r => r.tag);
            tags = tags.filter(t => !allCatTags.includes(t.name));
            
            // Добавляем новый
            tags.push({ name: catTag });
            model.info.meta.tags = tags;
            model.tags = tags;
          });

          console.log('[MTS] Injected tags into models:', list.length);
          const newData = Array.isArray(data) ? list : { ...data, data: list };
          
          return new Response(JSON.stringify(newData), {
            status: response.status,
            statusText: response.statusText,
            headers: response.headers
          });
        }
      } catch (e) {
        console.error('[MTS] Error inside interceptor', e);
      }
      return response; // fallback
    }

    return _origFetch.apply(this, args);
  };

  const HIDE_LABELS = new Set(['external', 'внешнее', 'local', 'локальное', 'direct', 'прямое']);

  const uiObserver = new MutationObserver(() => {
    document.querySelectorAll('button[aria-pressed]').forEach(btn => {
      const label = btn.textContent.trim().toLowerCase();
      if (HIDE_LABELS.has(label)) {
        btn.style.display = 'none';
      }
    });
  });

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => uiObserver.observe(document.body, { childList: true, subtree: true }));
  } else {
    uiObserver.observe(document.body, { childList: true, subtree: true });
  }

})();
