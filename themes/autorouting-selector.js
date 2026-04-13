/**
 * MTS AI Workspace — Chat Settings & Autorouting Panel
 * Injects a settings gear next to the Model Selector in the chat.
 */
(function () {
  'use strict';

  const LS_MODE_KEY = 'mts-autorouting-mode';

  function applyMode(mode) {
      localStorage.setItem(LS_MODE_KEY, mode);
      updateCheckmarks(mode);
  }
  
  function updateCheckmarks(activeMode) {
      const btns = document.querySelectorAll('.mts-ar-option');
      btns.forEach(btn => {
          const check = btn.querySelector('.check-icon');
          if(check) {
              check.style.opacity = (btn.dataset.mode === activeMode) ? '1' : '0';
          }
      });
  }

  function injectWidget() {
    if (document.getElementById('mts-chat-settings-widget')) return;

    // Находим кнопку "Add Model" (или "Добавить модель"), чтобы прикрепиться к её контейнеру в шапке чата
    const addModelBtn = document.querySelector('button[aria-label="Add Model"]') || 
                        document.querySelector('button[aria-label="Добавить модель"]');
    
    // В Open WebUI кнопка выбора модели и добавления новой находятся в одном flex-контейнере
    let containerElement = null;
    if (addModelBtn) {
        containerElement = addModelBtn.parentElement;
        if (containerElement && containerElement.parentElement && containerElement.parentElement.classList.contains('flex')) {
            containerElement = containerElement.parentElement;
        }
    } else {
        // Fallback: ищем элемент селектора моделей, если кнопки "Добавить модель" нет
        const modelSelectorArea = document.querySelector('div.flex-1.flex.items-center.min-w-0');
        if (modelSelectorArea) containerElement = modelSelectorArea;
    }

    if (!containerElement) return;

    // Снимаем класс overflow-hidden с контейнеров, чтобы наши dropdown меню не обрезались
    let parentNode = containerElement;
    for(let i=0; i<3; i++) {
        if(parentNode) {
            parentNode.style.overflow = 'visible';
            parentNode = parentNode.parentElement;
        }
    }

    // Создаем контейнер нашего виджета
    const widget = document.createElement('div');
    widget.id = 'mts-chat-settings-widget';
    // Добавляем margin-left для отступа от выбора модели
    widget.className = 'relative flex items-center ml-2 z-50'; 

    widget.innerHTML = `<style>
        .mts-chat-settings-btn {
            padding: 6px;
            border-radius: 0.75rem;
            color: #9ca3af;
            background: rgba(0,0,0,0);
            border: none;
            cursor: pointer;
            transition: all 0.2s;
            display: flex;
            align-items: center;
            justify-content: center;
        }
        .mts-chat-settings-btn:hover {
            color: #4b5563;
            background: rgba(0,0,0,0.05);
        }
        [data-theme='dark'] .mts-chat-settings-btn:hover, html.dark .mts-chat-settings-btn:hover {
            color: #e5e7eb;
            background: rgba(255,255,255,0.1);
        }
        
        @keyframes mtsSlideRight {
            from { opacity: 0; transform: translateX(-10px); }
            to { opacity: 1; transform: translateX(0); }
        }
        @keyframes mtsSlideDown {
            from { opacity: 0; transform: translateY(-10px); }
            to { opacity: 1; transform: translateY(0); }
        }

        .mts-popup-menu {
            position: absolute;
            width: 260px;
            background: white;
            border-radius: 0.75rem;
            box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.1), 0 4px 6px -2px rgba(0, 0, 0, 0.05);
            border: 1px solid #e5e7eb;
            display: none;
            flex-direction: column;
            z-index: 9999;
            padding: 6px;
            font-family: inherit;
        }
        [data-theme='dark'] .mts-popup-menu, html.dark .mts-popup-menu {
            background: #1f2937;
            border-color: #374151;
            color: #f3f4f6;
        }
        .mts-popup-menu.show {
            display: flex;
            animation: mtsSlideRight 0.2s ease forwards;
        }
        
        .mts-menu-item {
            display: flex;
            align-items: center;
            justify-content: space-between;
            width: 100%;
            padding: 10px 14px;
            font-size: 0.875rem;
            color: inherit;
            background: transparent;
            border: none;
            border-radius: 0.5rem;
            cursor: pointer;
            text-align: left;
            transition: background 0.1s;
        }
        .mts-menu-item:hover {
            background: rgba(0,0,0,0.05);
        }
        [data-theme='dark'] .mts-menu-item:hover, html.dark .mts-menu-item:hover {
            background: #374151;
        }

        .mts-submenu {
            display: none;
            position: absolute;
            width: 200px;
            background: white;
            border-radius: 0.75rem;
            box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.1);
            border: 1px solid #e5e7eb;
            flex-direction: column;
            padding: 6px;
            z-index: 10000;
        }
        [data-theme='dark'] .mts-submenu, html.dark .mts-submenu {
            background: #1f2937;
            border-color: #374151;
        }
        .mts-submenu.show {
            display: flex;
            animation: mtsSlideDown 0.2s ease forwards;
        }

        .mts-item-wrapper {
            position: relative;
        }
        
        .mts-arrow-icon {
            width: 16px;
            height: 16px;
            opacity: 0.5;
            transition: transform 0.2s;
        }
        .mts-item-wrapper.active .mts-arrow-icon {
            transform: rotate(-180deg);
        }
        
        .mts-ar-option {
            display: flex;
            align-items: center;
            gap: 8px;
            justify-content: flex-start;
        }
        .check-icon {
            opacity: 0;
            width: 14px;
            height: 14px;
            margin-left: auto;
            color: #3b82f6;
        }
        .menu-label-inner {
            display: flex;
            align-items: center;
            gap: 8px;
        }
    </style>`;

    // Кнопка-шестеренка (Settings button)
    const gearBtn = document.createElement('button');
    gearBtn.className = 'mts-chat-settings-btn';
    gearBtn.ariaLabel = "Настройки чата";
    gearBtn.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" width="20" height="20">
      <path stroke-linecap="round" stroke-linejoin="round" d="M9.594 3.94c.09-.542.56-.94 1.11-.94h2.593c.55 0 1.02.398 1.11.94l.213 1.281c.063.374.313.686.645.87.074.04.147.083.22.127.325.196.72.257 1.075.124l1.217-.456a1.125 1.125 0 0 1 1.37.49l1.296 2.247a1.125 1.125 0 0 1-.26 1.431l-1.003.827c-.293.241-.438.613-.43.992a7.723 7.723 0 0 1 0 .255c-.008.378.137.75.43.991l1.004.827c.424.35.534.955.26 1.43l-1.298 2.247a1.125 1.125 0 0 1-1.369.491l-1.217-.456c-.355-.133-.75-.072-1.076.124a6.47 6.47 0 0 1-.22.128c-.331.183-.581.495-.644.869l-.213 1.281c-.09.543-.56.94-1.11.94h-2.594c-.55 0-1.019-.398-1.11-.94l-.213-1.281c-.062-.374-.312-.686-.644-.87a6.52 6.52 0 0 1-.22-.127c-.325-.196-.72-.257-1.076-.124l-1.217.456a1.125 1.125 0 0 1-1.369-.49l-1.297-2.247a1.125 1.125 0 0 1 .26-1.431l1.004-.827c.292-.24.437-.613.43-.991a6.932 6.932 0 0 1 0-.255c.007-.38-.138-.751-.43-.992l-1.004-.827a1.125 1.125 0 0 1-.26-1.43l1.297-2.247a1.125 1.125 0 0 1 1.37-.491l1.216.456c.356.133.751.072 1.076-.124.072-.044.146-.086.22-.128.332-.183.582-.495.644-.869l.214-1.28Z" />
      <path stroke-linecap="round" stroke-linejoin="round" d="M15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z" />
    </svg>`;
    widget.appendChild(gearBtn);

    // Главное выпадающее меню настроек
    const mainMenu = document.createElement('div');
    mainMenu.className = 'mts-popup-menu';
    
    // Обертка для настройки "Автопереключение" (чтобы к ней привязать подменю)
    const arWrapper = document.createElement('div');
    arWrapper.className = 'mts-item-wrapper';

    // Кнопка Автопереключения в главном меню
    const arBtn = document.createElement('button');
    arBtn.className = 'mts-menu-item';
    arBtn.innerHTML = `
        <span class="menu-label-inner">
            <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" width="18" height="18">
                <path stroke-linecap="round" stroke-linejoin="round" d="M9.813 15.904 9 18.75l-.813-2.846a4.5 4.5 0 0 0-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 0 0 3.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 0 0 3.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 0 0-3.09 3.09ZM18.259 8.715 18 9.75l-.259-1.035a3.375 3.375 0 0 0-2.455-2.456L14.25 6l1.036-.259a3.375 3.375 0 0 0 2.455-2.456L18 2.25l.259 1.035a3.375 3.375 0 0 0 2.456 2.456L21.75 6l-1.035.259a3.375 3.375 0 0 0-2.456 2.456ZM16.894 20.567 16.5 21.75l-.394-1.183a2.25 2.25 0 0 0-1.423-1.423L13.5 18.75l1.183-.394a2.25 2.25 0 0 0 1.423-1.423l.394-1.183.394 1.183a2.25 2.25 0 0 0 1.423 1.423l1.183.394-1.183.394a2.25 2.25 0 0 0-1.423 1.423Z" />
            </svg>
            Автопереключение
        </span>
        <svg class="mts-arrow-icon" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
           <path stroke-linecap="round" stroke-linejoin="round" d="M9 5l7 7-7 7" />
        </svg>
    `;

    // Подменю (варианты автопереключения)
    const submenu = document.createElement('div');
    submenu.className = 'mts-submenu';

    const modes = [
        { id: 'off', label: 'Выключено', icon: '⛔' },
        { id: 'light', label: 'Light версия', icon: '⚡' },
        { id: 'pro', label: 'Pro версия', icon: '🔥' }
    ];

    modes.forEach(mode => {
        const btn = document.createElement('button');
        btn.className = 'mts-menu-item mts-ar-option';
        btn.dataset.mode = mode.id;
        btn.innerHTML = `
            <span class="menu-label-inner">${mode.icon} ${mode.label}</span>
            <svg class="check-icon" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2.5">
               <path stroke-linecap="round" stroke-linejoin="round" d="M5 13l4 4L19 7" />
            </svg>
        `;
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            applyMode(mode.id);
            // Закрываем меню после выбора
            submenu.classList.remove('show');
            mainMenu.classList.remove('show');
            arWrapper.classList.remove('active');
        });
        submenu.appendChild(btn);
    });

    // Не добавляем mainMenu и submenu внутрь widget, а добавляем в body,
    // чтобы избежать обрезания меню из-за родительских overflow:hidden.
    document.body.appendChild(mainMenu);
    document.body.appendChild(submenu);

    arWrapper.appendChild(arBtn);
    mainMenu.appendChild(arWrapper);
    
    // Добавляем саму кнопку-шестеренку в DOM
    containerElement.appendChild(widget);

    // Логика открытия/закрытия главного меню (нажатие на шестеренку)
    gearBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        
        const isShowing = mainMenu.classList.contains('show');
        
        if (!isShowing) {
            // Позиционируем меню ровно справа от кнопки шестеренки
            const rect = gearBtn.getBoundingClientRect();
            mainMenu.style.position = 'fixed';
            mainMenu.style.top = rect.top + 'px';
            mainMenu.style.left = (rect.right + 12) + 'px';
            mainMenu.classList.add('show');
        } else {
            mainMenu.classList.remove('show');
            submenu.classList.remove('show');
            arWrapper.classList.remove('active');
        }
    });

    // Логика открытия/закрытия подменю
    arBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        const isShowing = submenu.classList.contains('show');
        
        if (!isShowing) {
            // Позиционируем подменю ровно под кнопкой "Автопереключение"
            const rect = arBtn.getBoundingClientRect();
            submenu.style.position = 'fixed';
            submenu.style.top = (rect.bottom + 6) + 'px';
            
            // Если слишком близко к правому краю, сдвигаем левее
            if (rect.left + 200 > window.innerWidth) {
                submenu.style.left = (window.innerWidth - 210) + 'px';
            } else {
                submenu.style.left = rect.left + 'px';
            }
            submenu.classList.add('show');
            arWrapper.classList.add('active');
        } else {
            submenu.classList.remove('show');
            arWrapper.classList.remove('active');
        }
    });

    // Закрытие всех меню при клике в любое другое место
    document.addEventListener('click', (e) => {
        if (!mainMenu.contains(e.target) && !gearBtn.contains(e.target) && !submenu.contains(e.target)) {
            mainMenu.classList.remove('show');
            submenu.classList.remove('show');
            arWrapper.classList.remove('active');
        }
    });

    // Устанавливаем галочку в соответствии с сохраненным State
    const savedMode = localStorage.getItem(LS_MODE_KEY) || 'off';
    updateCheckmarks(savedMode);
  }

  // Запускаем `MutationObserver`, который реагирует на перерисовки Svelte и вмонтирует виджет
  const observer = new MutationObserver(() => {
    injectWidget();
  });

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
      observer.observe(document.body, { childList: true, subtree: true });
    });
  } else {
    observer.observe(document.body, { childList: true, subtree: true });
    injectWidget(); // Сразу инжектим, если страница уже загружена
  }

  // Перехватываем запросы к Chat Completions,
  // чтобы надежно прокинуть выбранный режим (off/light/pro) через само сообщение,
  // так как бэкенд (Pydantic) может обрезать кастомные поля вроде metadata.
  const originalFetch = window.fetch;
  window.fetch = async function(...args) {
      try {
          const urlStr = typeof args[0] === 'string' ? args[0] : (args[0] && args[0].url ? args[0].url : "");
          let options = args[1];
          if (options && options.body && typeof options.body === 'string') {
              const bodyObj = JSON.parse(options.body);
              if (bodyObj.messages && Array.isArray(bodyObj.messages)) {
                  const lastMsg = bodyObj.messages[bodyObj.messages.length - 1];
                  if (lastMsg && lastMsg.role === 'user' && typeof lastMsg.content === 'string') {
                      const mode = localStorage.getItem(LS_MODE_KEY) || 'off';
                      // Незаметно приклеиваем тег к сообщению
                      lastMsg.content += `\n\n[MTS_ROUTING_MODE=${mode}]`;
                      options.body = JSON.stringify(bodyObj);
                      args[1] = options;
                  }
              }
          }
      } catch(e) { } // Игнорируем ошибки сериализации, если это не наш запрос
      
      return originalFetch.apply(this, args);
  };

})();
