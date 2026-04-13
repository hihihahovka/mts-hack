/**
 * MTS AI Workspace — Model Category Tabs
 * Injects category tabs into the model selector dropdown.
 * Replaces the default "Все" / "Внешнее" tabs with categories.
 */
(function () {
  'use strict';

  // ─── Категории: keywords в нижнем регистре, order — тяжёлые первыми ──────────
  const CATEGORIES = [
    {
      id: 'text',
      label: '📝 Текст',
      keywords: ['glm-4', 'gpt-oss', 'llama', 'mistral', 'qwen2.5-72b', 'qwen3-32b'],
    },
    {
      id: 'reasoning',
      label: '🧠 Логика',
      keywords: ['qwq', 'deepseek-r1', 'deepseek-r', 'o1', 'o3'],
    },
    {
      id: 'code',
      label: '💻 Код',
      keywords: ['coder', 'codestral'],
    },
    {
      id: 'vision',
      label: '👁 Зрение',
      keywords: ['-vl', 'vision', 'cotype'],
    },
    {
      id: 'image',
      label: '🖼 Картинки',
      keywords: ['image', 'dall-e', 'flux', 'lightning'],
    },
    {
      id: 'audio',
      label: '🎤 Аудио',
      keywords: ['whisper', 'asr', 'speech'],
    },
  ];

  // ─── Стили ───────────────────────────────────────────────────────────────────
  const STYLE = `
    /* Скрываем оригинальные вкладки "Все" / "Внешнее" */
    .mts-hide-original-tabs { display: none !important; }

    #mts-cat-tabs {
      display: flex;
      flex-wrap: wrap;
      gap: 4px;
      padding: 6px 8px 4px;
      flex-shrink: 0;
    }
    .mts-cat-tab {
      padding: 3px 10px;
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
      line-height: 1.4;
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
  `;

  let activeCategory = 'all';
  let isFiltering = false; // Защита от рекурсии

  // ─── Ищем список моделей ─────────────────────────────────────────────────────
  // Open WebUI рендерит каждую модель как кнопку внутри прокручиваемого div.
  // Ищем контейнер по паттерну: div с overflow-y-auto внутри дропдауна.
  function getModelContainer() {
    // Ищем прокручиваемый контейнер списка моделей
    const scrollers = document.querySelectorAll('[data-state="open"] [class*="overflow-y-auto"], [class*="overflow-y-auto"]');
    for (const el of scrollers) {
      // Если внутри есть кнопки с именами моделей — это наш контейнер
      const buttons = el.querySelectorAll('button');
      if (buttons.length >= 2) return el;
    }
    return null;
  }

  function getModelItems(container) {
    if (!container) return [];
    // Берём прямых потомков type-button или div с кнопкой
    return [...container.querySelectorAll(':scope > *')].filter(el => {
      // Каждая модель — это строка (div/li) с кнопкой или сама кнопка
      return el.textContent.trim().length > 0 && !el.id.includes('mts');
    });
  }

  // ─── Фильтрация ─────────────────────────────────────────────────────────────
  function filterModels(catId) {
    if (isFiltering) return;
    isFiltering = true;

    try {
      const container = getModelContainer();
      if (!container) return;

      const items = getModelItems(container);
      if (!items.length) return;

      if (catId === 'all') {
        items.forEach(el => (el.style.display = ''));
        isFiltering = false;
        return;
      }

      const cat = CATEGORIES.find(c => c.id === catId);
      if (!cat) { isFiltering = false; return; }

      const matched = [];
      const unmatched = [];

      items.forEach(el => {
        const text = el.textContent.trim().toLowerCase();
        const matches = cat.keywords.some(kw => text.includes(kw.toLowerCase()));
        if (matches) {
          el.style.display = '';
          matched.push(el);
        } else {
          el.style.display = 'none';
          unmatched.push(el);
        }
      });

      // Перемещаем matched в начало (тяжёлые — по алфавиту/порядку появления, не меняем)
      matched.forEach(el => container.prepend(el));

    } finally {
      isFiltering = false;
    }
  }

  // ─── Инжектируем вкладки ─────────────────────────────────────────────────────
  function injectCategoryTabs() {
    // Уже инжектировано?
    if (document.getElementById('mts-cat-tabs')) return;

    // Находим таб-бар с "Все" / "Внешнее"
    const allButtons = [...document.querySelectorAll('button')];
    const tabAllBtn = allButtons.find(b => {
      const t = b.textContent.trim();
      return (t === 'Все' || t === 'All') && b.offsetParent !== null;
    });
    if (!tabAllBtn) return;

    const tabBar = tabAllBtn.parentElement;
    if (!tabBar) return;

    // Скрываем оригинальные вкладки
    [...tabBar.children].forEach(child => {
      child.classList.add('mts-hide-original-tabs');
    });

    // Создаём наш блок
    const catTabs = document.createElement('div');
    catTabs.id = 'mts-cat-tabs';

    // "Все" — первая
    catTabs.appendChild(makeTab('all', '✦ Все', true));
    CATEGORIES.forEach(cat => catTabs.appendChild(makeTab(cat.id, cat.label, false)));

    // Вставляем в тот же tabBar (вместо скрытых)
    tabBar.appendChild(catTabs);
  }

  function makeTab(id, label, active) {
    const btn = document.createElement('button');
    btn.className = 'mts-cat-tab' + (active ? ' active' : '');
    btn.dataset.catId = id;
    btn.textContent = label;
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      e.preventDefault();
      activeCategory = id;
      document.querySelectorAll('.mts-cat-tab').forEach(b =>
        b.classList.toggle('active', b.dataset.catId === id)
      );
      filterModels(id);
    });
    return btn;
  }

  // ─── Стили один раз ──────────────────────────────────────────────────────────
  function injectStyles() {
    if (document.getElementById('mts-cat-style')) return;
    const style = document.createElement('style');
    style.id = 'mts-cat-style';
    style.textContent = STYLE;
    document.head.appendChild(style);
  }

  // ─── MutationObserver — только следим за добавлением нот в DOM, не вмешиваемся ──
  const observer = new MutationObserver(() => {
    if (isFiltering) return; // не реагируем на наши собственные изменения
    injectCategoryTabs();
    // Применяем текущий фильтр если он не "all"
    if (activeCategory !== 'all') filterModels(activeCategory);
  });

  injectStyles();

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
      observer.observe(document.body, { childList: true, subtree: true });
    });
  } else {
    observer.observe(document.body, { childList: true, subtree: true });
  }

})();
