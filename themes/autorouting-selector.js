/**
 * MTS AI Workspace — Autorouting Selector Widget
 * Injects a settings gear next to "Add Model" button which expands into autorouting toggles.
 */
(function () {
  'use strict';

  function injectWidget() {
    // Если уже добавлено, пропускаем
    if (document.getElementById('mts-autorouting-widget')) return;

    // Находим кнопку "Add Model" (или "Добавить модель"), чтобы прикрепиться к её контейнеру
    const addModelBtn = document.querySelector('button[aria-label="Add Model"]') || 
                        document.querySelector('button[aria-label="Добавить модель"]');
    if (!addModelBtn) return;

    // Нам нужен её родительский контейнер с классом flex, чтобы кнопка ровно встала в ряд
    let containerElement = addModelBtn.parentElement;
    if (containerElement && containerElement.parentElement && containerElement.parentElement.classList.contains('flex')) {
        containerElement = containerElement.parentElement;
    }

    if (!containerElement) return;
    
    // Создаем наш собственный DOM-элемент
    const widget = document.createElement('div');
    widget.id = 'mts-autorouting-widget';
    // Подгоняем стили так же, как у родных кнопок Svelte-шаблона
    widget.className = 'self-center mx-1 flex items-center group relative -translate-y-[0.5px]';

    // Инжектируем стили и HTML-структуру напрямую
    widget.innerHTML = `
      <style>
        .ar-settings-btn {
          color: #9ca3af;
          transition: color 0.2s;
          padding: 4px;
          cursor: pointer;
          background: transparent;
          border: none;
        }
        .ar-settings-btn:hover {
          color: #4b5563;
        }
        [data-theme='dark'] .ar-settings-btn:hover {
          color: #e5e7eb;
        }
        .ar-expand-area {
          display: flex;
          align-items: center;
          overflow: visible; /* changed from hidden so dropdown isn't clipped */
          transition: all 0.3s ease;
          width: 0;
          opacity: 0;
          pointer-events: none; /* disables clicking while hidden */
        }
        
        .ar-expand-area .ar-settings-btn {
           padding: 2px;
           margin-left: 2px;
        }

        .ar-settings-btn:hover {
           background-color: rgba(156, 163, 175, 0.1);
           border-radius: 0.5rem;
        }

        /* При наведении на всю группу открывается кнопка авторутинга */
        .ar-widget-group:hover .ar-expand-area {
          width: 24px;
          opacity: 1;
          pointer-events: auto;
        }

        .ar-dropdown {
          display: none;
          position: absolute;
          top: 100%;
          left: 0;
          margin-top: 4px;
          background: white;
          border: 1px solid #e5e7eb;
          border-radius: 0.75rem;
          box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.1);
          padding: 4px;
          z-index: 50;
          min-width: 180px;
          flex-direction: column;
          gap: 4px;
          font-family: inherit;
        }
        [data-theme='dark'] .ar-dropdown {
          background: #1f2937;
          border-color: #374151;
        }
        .ar-dropdown.open {
          display: flex;
        }
        .ar-dropdown-item {
          text-align: left;
          padding: 8px 12px;
          border-radius: 0.5rem;
          font-size: 0.875rem;
          color: #374151;
          cursor: pointer;
          border: none;
          background: transparent;
        }
        [data-theme='dark'] .ar-dropdown-item {
          color: #e5e7eb;
        }
        .ar-dropdown-item:hover {
          background: #f3f4f6;
        }
        [data-theme='dark'] .ar-dropdown-item:hover {
          background: #374151;
        }
      </style>

      <div class="ar-widget-group flex items-center" style="display:flex; align-items:center;">
          <!-- Иконка шестеренки (настройки) -->
          <button class="ar-settings-btn" aria-label="Настройки" title="Настройки">
            <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" width="14" height="14">
              <path stroke-linecap="round" stroke-linejoin="round" d="M9.594 3.94c.09-.542.56-.94 1.11-.94h2.593c.55 0 1.02.398 1.11.94l.213 1.281c.063.374.313.686.645.87.074.04.147.083.22.127.325.196.72.257 1.075.124l1.217-.456a1.125 1.125 0 0 1 1.37.49l1.296 2.247a1.125 1.125 0 0 1-.26 1.431l-1.003.827c-.293.241-.438.613-.43.992a7.723 7.723 0 0 1 0 .255c-.008.378.137.75.43.991l1.004.827c.424.35.534.955.26 1.43l-1.298 2.247a1.125 1.125 0 0 1-1.369.491l-1.217-.456c-.355-.133-.75-.072-1.076.124a6.47 6.47 0 0 1-.22.128c-.331.183-.581.495-.644.869l-.213 1.281c-.09.543-.56.94-1.11.94h-2.594c-.55 0-1.019-.398-1.11-.94l-.213-1.281c-.062-.374-.312-.686-.644-.87a6.52 6.52 0 0 1-.22-.127c-.325-.196-.72-.257-1.076-.124l-1.217.456a1.125 1.125 0 0 1-1.369-.49l-1.297-2.247a1.125 1.125 0 0 1 .26-1.431l1.004-.827c.292-.24.437-.613.43-.991a6.932 6.932 0 0 1 0-.255c.007-.38-.138-.751-.43-.992l-1.004-.827a1.125 1.125 0 0 1-.26-1.43l1.297-2.247a1.125 1.125 0 0 1 1.37-.491l1.216.456c.356.133.751.072 1.076-.124.072-.044.146-.086.22-.128.332-.183.582-.495.644-.869l.214-1.28Z" />
              <path stroke-linecap="round" stroke-linejoin="round" d="M15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z" />
            </svg>
          </button>

          <!-- Выплывающая кнопка -->
          <div class="ar-expand-area relative">
            <button class="ar-settings-btn" id="ar-trigger-btn" aria-label="Авторутинг" title="Авторутинг">
                <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" width="14" height="14">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M9.813 15.904 9 18.75l-.813-2.846a4.5 4.5 0 0 0-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 0 0 3.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 0 0 3.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 0 0-3.09 3.09ZM18.259 8.715 18 9.75l-.259-1.035a3.375 3.375 0 0 0-2.455-2.456L14.25 6l1.036-.259a3.375 3.375 0 0 0 2.455-2.456L18 2.25l.259 1.035a3.375 3.375 0 0 0 2.456 2.456L21.75 6l-1.035.259a3.375 3.375 0 0 0-2.456 2.456ZM16.894 20.567 16.5 21.75l-.394-1.183a2.25 2.25 0 0 0-1.423-1.423L13.5 18.75l1.183-.394a2.25 2.25 0 0 0 1.423-1.423l.394-1.183.394 1.183a2.25 2.25 0 0 0 1.423 1.423l1.183.394-1.183.394a2.25 2.25 0 0 0-1.423 1.423Z" />
                </svg>	
            </button>
            
            <div id="ar-dropdown-menu" class="ar-dropdown">
                <button class="ar-dropdown-item">Выключить настройки</button>
                <button class="ar-dropdown-item">Light версия</button>
                <button class="ar-dropdown-item">Pro версия</button>
            </div>
          </div>
      </div>
    `;

    containerElement.appendChild(widget);

    // Добавляем логику выпадающего списка
    const triggerBtn = widget.querySelector('#ar-trigger-btn');
    const dropdownMenu = widget.querySelector('#ar-dropdown-menu');
    
    triggerBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        dropdownMenu.classList.toggle('open');
    });

    document.addEventListener('click', (e) => {
        if (!dropdownMenu.contains(e.target) && e.target !== triggerBtn && !triggerBtn.contains(e.target)) {
            dropdownMenu.classList.remove('open');
        }
    });

    // Делаем кнопки нажимаемыми и закрываем менюшку
    const items = widget.querySelectorAll('.ar-dropdown-item');
    items.forEach(item => {
        item.addEventListener('click', (e) => {
            console.log('Выбрана опция:', e.target.textContent);
            dropdownMenu.classList.remove('open');
        });
    });
  }

  // Запускаем MutationObserver, потому что интерфейс (в том числе кнопка Add Model) 
  // может перерисовываться Svelte "на лету" 
  const observer = new MutationObserver((mutations, obs) => {
    // Если виджет уже есть, не делаем дубликатов
    if (document.getElementById('mts-autorouting-widget')) return;
    
    // Проверяем наличие кнопки Add Model
    const addModelBtn = document.querySelector('button[aria-label="Add Model"]') || 
                        document.querySelector('button[aria-label="Добавить модель"]');
    if (addModelBtn) {
        injectWidget();
    }
  });

  // Запускаем слежку за интерфейсом
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
      observer.observe(document.body, { childList: true, subtree: true });
    });
  } else {
    observer.observe(document.body, { childList: true, subtree: true });
    injectWidget(); // Пробуем сразу
  }

})();
