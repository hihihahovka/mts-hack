/**
 * MTS AI Workspace — Theme Selector Widget
 * ============================================================
 * Floating button with dropdown to switch between 7 custom themes.
 * Persists selection in localStorage. Applies data-theme on <html>.
 * ============================================================
 */
(function () {
  'use strict';

  const THEMES = [
    { id: 'indigo',   name: 'Indigo',   color: '#6366f1', emoji: '💎' },
    { id: 'emerald',  name: 'Emerald',  color: '#10b981', emoji: '🌿' },
    { id: 'amethyst', name: 'Amethyst', color: '#a855f7', emoji: '🔮' },
    { id: 'ruby',     name: 'Ruby',     color: '#f43f5e', emoji: '❤️‍🔥' },
    { id: 'amber',    name: 'Amber',    color: '#f59e0b', emoji: '🌅' },
    { id: 'graphite', name: 'Graphite', color: '#737373', emoji: '🌑' },
    { id: 'aurora',   name: 'Aurora',   color: '#06b6d4', emoji: '🌊' },
  ];

  const STORAGE_KEY = 'mts-theme';

  /** Apply theme to <html> element */
  function applyTheme(themeId) {
    const html = document.documentElement;
    if (themeId) {
      html.setAttribute('data-theme', themeId);
      localStorage.setItem(STORAGE_KEY, themeId);
    } else {
      html.removeAttribute('data-theme');
      localStorage.removeItem(STORAGE_KEY);
    }
    updateActiveState(themeId);
  }

  /** Highlight active theme in the menu */
  function updateActiveState(activeId) {
    const buttons = document.querySelectorAll('#mts-theme-menu button.theme-option');
    buttons.forEach(btn => {
      btn.classList.toggle('active', btn.dataset.theme === (activeId || ''));
    });
  }

  /** Build and inject the widget DOM */
  function createWidget() {
    // Container
    const container = document.createElement('div');
    container.id = 'mts-theme-selector';

    // Toggle button
    const toggle = document.createElement('button');
    toggle.id = 'mts-theme-toggle';
    toggle.innerHTML = '🎨';
    toggle.title = 'Выберите тему';
    toggle.setAttribute('aria-label', 'Переключатель тем');

    // Dropdown menu
    const menu = document.createElement('div');
    menu.id = 'mts-theme-menu';

    // Header
    const header = document.createElement('div');
    header.className = 'menu-header';
    header.textContent = 'Тема оформления';
    menu.appendChild(header);

    // Theme buttons
    THEMES.forEach(theme => {
      const btn = document.createElement('button');
      btn.className = 'theme-option';
      btn.dataset.theme = theme.id;

      const swatch = document.createElement('span');
      swatch.className = 'swatch';
      swatch.style.backgroundColor = theme.color;

      const label = document.createElement('span');
      label.textContent = `${theme.emoji} ${theme.name}`;

      btn.appendChild(swatch);
      btn.appendChild(label);

      btn.addEventListener('click', () => {
        applyTheme(theme.id);
        menu.classList.remove('open');
      });

      menu.appendChild(btn);
    });

    // Divider
    const divider = document.createElement('div');
    divider.className = 'divider';
    menu.appendChild(divider);

    // Reset button
    const resetBtn = document.createElement('button');
    resetBtn.className = 'theme-option';
    resetBtn.dataset.theme = '';

    const resetSwatch = document.createElement('span');
    resetSwatch.className = 'swatch';
    resetSwatch.style.background = 'linear-gradient(135deg, #333 50%, #eee 50%)';

    const resetLabel = document.createElement('span');
    resetLabel.textContent = '↩️ Сбросить';

    resetBtn.appendChild(resetSwatch);
    resetBtn.appendChild(resetLabel);

    resetBtn.addEventListener('click', () => {
      applyTheme(null);
      menu.classList.remove('open');
    });
    menu.appendChild(resetBtn);

    // Assemble
    container.appendChild(menu);
    container.appendChild(toggle);

    // Toggle dropdown
    toggle.addEventListener('click', (e) => {
      e.stopPropagation();
      menu.classList.toggle('open');
    });

    // Close on outside click
    document.addEventListener('click', (e) => {
      if (!container.contains(e.target)) {
        menu.classList.remove('open');
      }
    });

    // Close on Escape
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') {
        menu.classList.remove('open');
      }
    });

    document.body.appendChild(container);
  }

  /** Initialize: restore saved theme and create widget */
  function init() {
    // Restore saved theme immediately
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved) {
      document.documentElement.setAttribute('data-theme', saved);
    }

    // Wait for DOM to be ready, then inject widget
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', () => {
        createWidget();
        updateActiveState(saved);
      });
    } else {
      createWidget();
      updateActiveState(saved);
    }
  }

  init();
})();
