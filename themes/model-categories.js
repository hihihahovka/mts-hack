/**
 * MTS AI Workspace — Model Category Tabs
 * Injects category tabs into the model selector dropdown.
 * Categories: Текст, Логика, Код, Зрение, Картинки, Аудио
 * Within each category: heavy models first, light models last.
 */
(function () {
  'use strict';

  // ─── Категории и модели (от тяжёлых к лёгким) ───────────────────────────────
  const CATEGORIES = [
    {
      id: 'text',
      label: '📝 Текст',
      keywords: ['glm-4', 'gpt-oss', 'llama', 'qwen3-32b', 'qwen2.5-72b', 'mistral'],
      // Порядок: тяжёлые сначала
      order: ['glm-4.6-357b', 'gpt-oss-20b', 'llama-3.1-8b-instruct'],
    },
    {
      id: 'reasoning',
      label: '🧠 Логика',
      keywords: ['qwq', 'deepseek-r1', 'deepseek-r', 'o1', 'o3'],
      order: ['qwq-32b', 'QwQ-32B', 'deepseek-r1-distill-qwen-32b'],
    },
    {
      id: 'code',
      label: '💻 Код',
      keywords: ['coder', 'code', 'codestral'],
      order: ['qwen3-coder-480b-a35b'],
    },
    {
      id: 'vision',
      label: '👁 Зрение',
      keywords: ['vl', 'vision', 'cotype'],
      order: ['qwen2.5-vl-72b', 'cotype-pro-vl-32b', 'qwen2.5-vl'],
    },
    {
      id: 'image',
      label: '🖼 Картинки',
      keywords: ['image', 'dall-e', 'stable-diff', 'flux'],
      order: ['qwen-image', 'qwen-image-lightning'],
    },
    {
      id: 'audio',
      label: '🎤 Аудио',
      keywords: ['whisper', 'asr', 'speech', 'stt'],
      order: [],
    },
  ];

  // ─── Стили ───────────────────────────────────────────────────────────────────
  const STYLE = `
    #mts-cat-tabs {
      display: flex;
      flex-wrap: wrap;
      gap: 4px;
      padding: 6px 8px 4px;
      border-bottom: 1px solid #e5e7eb;
      background: transparent;
    }
    html.dark #mts-cat-tabs {
      border-color: #374151;
    }
    .mts-cat-tab {
      padding: 3px 8px;
      border-radius: 999px;
      font-size: 0.72rem;
      font-weight: 500;
      border: 1px solid transparent;
      cursor: pointer;
      background: transparent;
      color: #6b7280;
      white-space: nowrap;
      transition: all 0.15s;
      font-family: inherit;
    }
    .mts-cat-tab:hover {
      background: #f3f4f6;
      color: #111827;
    }
    html.dark .mts-cat-tab:hover {
      background: #374151;
      color: #f9fafb;
    }
    .mts-cat-tab.active {
      background: #e0e7ff;
      color: #4338ca;
      border-color: #c7d2fe;
    }
    html.dark .mts-cat-tab.active {
      background: #312e81;
      color: #a5b4fc;
      border-color: #4338ca;
    }
    .mts-cat-hidden {
      display: none !important;
    }
  `;

  // ─── Определяем категорию модели по ID/name ──────────────────────────────────
  function getCategoryForModel(modelId) {
    const id = (modelId || '').toLowerCase();
    for (const cat of CATEGORIES) {
      if (cat.keywords.some(kw => id.includes(kw.toLowerCase()))) {
        return cat.id;
      }
    }
    return 'text'; // fallback — в «Текст»
  }

  // ─── Инжектируем вкладки ─────────────────────────────────────────────────────
  let activeCategory = 'all';
  let injected = false;

  function injectCategoryTabs() {
    // Ищем таб-бар с кнопками "Все" / "Внешнее"
    const existingTabs = [...document.querySelectorAll('button')].filter(b => {
      const t = b.textContent.trim();
      return (t === 'Все' || t === 'All') && b.parentElement;
    });

    if (!existingTabs.length) return;

    const tabBar = existingTabs[0].parentElement;

    // Не добавляем если уже есть
    if (tabBar.querySelector('#mts-cat-tabs') || document.getElementById('mts-cat-tabs')) return;
    injected = true;

    // Стили
    if (!document.getElementById('mts-cat-style')) {
      const styleEl = document.createElement('style');
      styleEl.id = 'mts-cat-style';
      styleEl.textContent = STYLE;
      document.head.appendChild(styleEl);
    }

    // Контейнер вкладок категорий
    const catTabsEl = document.createElement('div');
    catTabsEl.id = 'mts-cat-tabs';

    // Кнопка "Все" в наших вкладках
    const allTab = makeTab('all', '✦ Все');
    allTab.classList.add('active');
    catTabsEl.appendChild(allTab);

    // Кнопки категорий
    CATEGORIES.forEach(cat => {
      catTabsEl.appendChild(makeTab(cat.id, cat.label));
    });

    // Вставляем ПОСЛЕ существующего таб-бара
    tabBar.insertAdjacentElement('afterend', catTabsEl);
  }

  function makeTab(id, label) {
    const btn = document.createElement('button');
    btn.className = 'mts-cat-tab';
    btn.dataset.catId = id;
    btn.textContent = label;
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      selectCategory(id);
    });
    return btn;
  }

  function selectCategory(catId) {
    activeCategory = catId;

    // Обновляем active-класс
    document.querySelectorAll('.mts-cat-tab').forEach(b => {
      b.classList.toggle('active', b.dataset.catId === catId);
    });

    filterAndSortModels(catId);
  }

  // ─── Фильтрация и сортировка ─────────────────────────────────────────────────
  function filterAndSortModels(catId) {
    // Ищем контейнер со списком моделей
    // Open WebUI рендерит их как кнопки с data-value или aria-label, или просто текстом
    const allItems = getModelListItems();
    if (!allItems.length) return;

    const parent = allItems[0].parentElement;

    if (catId === 'all') {
      // Показываем всё, убираем нашу сортировку
      allItems.forEach(el => el.classList.remove('mts-cat-hidden'));
      return;
    }

    const cat = CATEGORIES.find(c => c.id === catId);
    if (!cat) return;

    // Разбиваем на matching и non-matching
    const matching = [];
    const nonMatching = [];

    allItems.forEach(el => {
      const modelText = (el.textContent || '').toLowerCase();
      const matches = cat.keywords.some(kw => modelText.includes(kw.toLowerCase()));
      if (matches) {
        matching.push(el);
        el.classList.remove('mts-cat-hidden');
      } else {
        nonMatching.push(el);
        el.classList.add('mts-cat-hidden');
      }
    });

    // Сортируем matching по order (тяжёлые сначала)
    if (cat.order.length > 0) {
      matching.sort((a, b) => {
        const aText = a.textContent.trim().toLowerCase();
        const bText = b.textContent.trim().toLowerCase();
        const aIdx = cat.order.findIndex(m => aText.includes(m.toLowerCase()));
        const bIdx = cat.order.findIndex(m => bText.includes(m.toLowerCase()));
        const ai = aIdx === -1 ? 999 : aIdx;
        const bi = bIdx === -1 ? 999 : bIdx;
        return ai - bi;
      });
      // Переставляем в DOM
      matching.forEach(el => parent.appendChild(el));
    }
  }

  function getModelListItems() {
    // Open WebUI рендерит каждую модель как button или div с ролью option
    // в одном прокручиваемом контейнере внутри model selector
    const candidates = [];
    // Ищем кнопки в model dropdown, у которых нет наших классов
    document.querySelectorAll('[role="option"], [role="listitem"]').forEach(el => {
      if (!el.classList.contains('mts-cat-tab')) candidates.push(el);
    });
    if (candidates.length > 0) return candidates;

    // Fallback: ищем элементы списка внутри popover/dropdown, которые не являются нашими
    const dropdowns = document.querySelectorAll('[data-radix-popper-content-wrapper], .model-selector, [role="listbox"]');
    dropdowns.forEach(dd => {
      dd.querySelectorAll('button').forEach(btn => {
        if (!btn.classList.contains('mts-cat-tab') && btn.textContent.trim().length > 0) {
          candidates.push(btn);
        }
      });
    });
    return candidates;
  }

  // ─── MutationObserver ────────────────────────────────────────────────────────
  const observer = new MutationObserver(() => {
    injectCategoryTabs();

    // Если вкладки уже инжектированы — поддерживаем фильтр при обновлении списка
    if (injected && activeCategory !== 'all') {
      filterAndSortModels(activeCategory);
    }

    // Сброс при закрытии dropdown
    const catTabs = document.getElementById('mts-cat-tabs');
    if (catTabs && !document.body.contains(catTabs)) {
      injected = false;
      activeCategory = 'all';
    }
  });

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
      observer.observe(document.body, { childList: true, subtree: true });
    });
  } else {
    observer.observe(document.body, { childList: true, subtree: true });
  }

})();
