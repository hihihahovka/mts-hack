/**
 * MTS AI Workspace — Appearance Panel
 * ============================================================
 * Injects "Внешний вид" (Appearance) item into the user profile
 * dropdown menu. Opens a slide-over panel with:
 *   1. Theme mode selector (Light / Dark / System)
 *   2. Color accent selector (7 palettes + Reset)
 * Persists all choices in localStorage.
 * ============================================================
 */
(function () {
  'use strict';

  /* ── colour accents ── */
  const ACCENTS = [
    { id: 'indigo',   name: 'Indigo',   color: '#6366f1', emoji: '💎' },
    { id: 'emerald',  name: 'Emerald',  color: '#10b981', emoji: '🌿' },
    { id: 'amethyst', name: 'Amethyst', color: '#a855f7', emoji: '🔮' },
    { id: 'ruby',     name: 'Ruby',     color: '#f43f5e', emoji: '❤️‍🔥' },
    { id: 'amber',    name: 'Amber',    color: '#f59e0b', emoji: '🌅' },
    { id: 'graphite', name: 'Graphite', color: '#737373', emoji: '🌑' },
    { id: 'aurora',   name: 'Aurora',   color: '#06b6d4', emoji: '🌊' },
  ];

  const ACCENT_KEY = 'mts-theme';        // colour accent
  const MODE_KEY   = 'mts-theme-mode';   // light | dark | system

  /* ───────────────────────────────────
     Theme mode helpers
     ─────────────────────────────────── */
  function getSystemPrefersDark() {
    return window.matchMedia('(prefers-color-scheme: dark)').matches;
  }

  function applyMode(mode) {
    const html = document.documentElement;
    localStorage.setItem(MODE_KEY, mode);

    // OpenWebUI sets class "dark" on <html>
    if (mode === 'light') {
      html.classList.remove('dark');
      html.style.colorScheme = 'light';
    } else if (mode === 'dark') {
      html.classList.add('dark');
      html.style.colorScheme = 'dark';
    } else {
      // system
      if (getSystemPrefersDark()) {
        html.classList.add('dark');
        html.style.colorScheme = 'dark';
      } else {
        html.classList.remove('dark');
        html.style.colorScheme = 'light';
      }
    }
    // Also sync localStorage key that OpenWebUI's own code reads
    localStorage.setItem('theme', mode);
    updateModeButtons(mode);
  }

  function updateModeButtons(activeMode) {
    const btns = document.querySelectorAll('#mts-appearance-panel .mode-btn');
    btns.forEach(btn => {
      btn.classList.toggle('active', btn.dataset.mode === activeMode);
    });
  }

  /* ───────────────────────────────────
     Colour accent helpers
     ─────────────────────────────────── */
  function applyAccent(accentId) {
    const html = document.documentElement;
    if (accentId) {
      html.setAttribute('data-theme', accentId);
      localStorage.setItem(ACCENT_KEY, accentId);
    } else {
      html.removeAttribute('data-theme');
      localStorage.removeItem(ACCENT_KEY);
    }
    updateAccentButtons(accentId);
  }

  function updateAccentButtons(activeId) {
    const btns = document.querySelectorAll('#mts-appearance-panel .accent-btn');
    btns.forEach(btn => {
      btn.classList.toggle('active', btn.dataset.accent === (activeId || ''));
    });
  }

  /* ───────────────────────────────────
     Build the Appearance side-panel
     ─────────────────────────────────── */
  function buildPanel() {
    // Overlay backdrop
    const overlay = document.createElement('div');
    overlay.id = 'mts-appearance-overlay';
    overlay.addEventListener('click', () => closePanel());

    // Panel itself
    const panel = document.createElement('div');
    panel.id = 'mts-appearance-panel';

    // ── Header ──
    const header = document.createElement('div');
    header.className = 'panel-header';

    const title = document.createElement('h2');
    title.textContent = 'Внешний вид';

    const closeBtn = document.createElement('button');
    closeBtn.className = 'panel-close';
    closeBtn.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>`;
    closeBtn.addEventListener('click', () => closePanel());

    header.appendChild(title);
    header.appendChild(closeBtn);
    panel.appendChild(header);

    // ── Section: Theme Mode ──
    const modeSection = document.createElement('div');
    modeSection.className = 'panel-section';

    const modeLabel = document.createElement('div');
    modeLabel.className = 'section-label';
    modeLabel.textContent = 'Тема';
    modeSection.appendChild(modeLabel);

    const modeGroup = document.createElement('div');
    modeGroup.className = 'mode-group';

    const modes = [
      { id: 'light',  label: 'Светлая', icon: '☀️' },
      { id: 'dark',   label: 'Тёмная',  icon: '🌙' },
      { id: 'system', label: 'Система', icon: '💻' },
    ];

    modes.forEach(m => {
      const btn = document.createElement('button');
      btn.className = 'mode-btn';
      btn.dataset.mode = m.id;
      btn.innerHTML = `<span class="mode-icon">${m.icon}</span><span>${m.label}</span>`;
      btn.addEventListener('click', () => applyMode(m.id));
      modeGroup.appendChild(btn);
    });

    modeSection.appendChild(modeGroup);
    panel.appendChild(modeSection);

    // ── Section: Accent Colour ──
    const accentSection = document.createElement('div');
    accentSection.className = 'panel-section';

    const accentLabel = document.createElement('div');
    accentLabel.className = 'section-label';
    accentLabel.textContent = 'Цветовой акцент';
    accentSection.appendChild(accentLabel);

    const accentGrid = document.createElement('div');
    accentGrid.className = 'accent-grid';

    ACCENTS.forEach(a => {
      const btn = document.createElement('button');
      btn.className = 'accent-btn';
      btn.dataset.accent = a.id;
      btn.title = a.name;

      const swatch = document.createElement('span');
      swatch.className = 'accent-swatch';
      swatch.style.backgroundColor = a.color;

      const label = document.createElement('span');
      label.className = 'accent-label';
      label.textContent = `${a.emoji}  ${a.name}`;

      const check = document.createElement('span');
      check.className = 'accent-check';
      check.innerHTML = '✓';

      btn.appendChild(swatch);
      btn.appendChild(label);
      btn.appendChild(check);
      btn.addEventListener('click', () => applyAccent(a.id));
      accentGrid.appendChild(btn);
    });

    // Reset button
    const resetBtn = document.createElement('button');
    resetBtn.className = 'accent-btn';
    resetBtn.dataset.accent = '';
    resetBtn.title = 'Сбросить';

    const resetSwatch = document.createElement('span');
    resetSwatch.className = 'accent-swatch';
    resetSwatch.style.background = 'linear-gradient(135deg, #333 50%, #eee 50%)';

    const resetLabel = document.createElement('span');
    resetLabel.className = 'accent-label';
    resetLabel.textContent = '↩️  По умолчанию';

    const resetCheck = document.createElement('span');
    resetCheck.className = 'accent-check';
    resetCheck.innerHTML = '✓';

    resetBtn.appendChild(resetSwatch);
    resetBtn.appendChild(resetLabel);
    resetBtn.appendChild(resetCheck);
    resetBtn.addEventListener('click', () => applyAccent(null));
    accentGrid.appendChild(resetBtn);

    accentSection.appendChild(accentGrid);
    panel.appendChild(accentSection);

    // Escape key handler
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') closePanel();
    });

    document.body.appendChild(overlay);
    document.body.appendChild(panel);
  }

  /* ───────────────────────────────────
     Open / close panel
     ─────────────────────────────────── */
  function openPanel() {
    const overlay = document.getElementById('mts-appearance-overlay');
    const panel   = document.getElementById('mts-appearance-panel');
    if (!overlay || !panel) return;

    // Sync state before showing
    updateModeButtons(localStorage.getItem(MODE_KEY) || 'system');
    updateAccentButtons(localStorage.getItem(ACCENT_KEY) || '');

    overlay.classList.add('open');
    panel.classList.add('open');
  }

  function closePanel() {
    const overlay = document.getElementById('mts-appearance-overlay');
    const panel   = document.getElementById('mts-appearance-panel');
    if (overlay) overlay.classList.remove('open');
    if (panel)   panel.classList.remove('open');
  }

  /* ───────────────────────────────────
     Inject menu item into profile menu
     ─────────────────────────────────── */
  const APPEARANCE_SVG_PATHS = `<circle cx="12" cy="12" r="5"></circle><path stroke-linecap="round" stroke-linejoin="round" d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42"></path>`;

  function injectMenuItem() {
    const observer = new MutationObserver(() => {
      const menuButtons = document.querySelectorAll('button');

      let settingsBtn = null;
      menuButtons.forEach(btn => {
        if (btn.textContent.trim().startsWith('Настройки') && btn.classList.contains('rounded-xl')) {
          settingsBtn = btn;
        }
      });

      if (!settingsBtn) return;
      if (document.getElementById('mts-appearance-menu-item')) return;

      // Deep-clone the exact "Настройки" button
      const item = settingsBtn.cloneNode(true);
      item.id = 'mts-appearance-menu-item';

      // Replace SVG paths only — keeps original <svg> element with its exact classes/size
      const svg = item.querySelector('svg');
      if (svg) {
        svg.innerHTML = APPEARANCE_SVG_PATHS;
      }

      // Replace the label text
      const allEls = item.querySelectorAll('*');
      allEls.forEach(el => {
        // Only replace text nodes that exactly match
        for (let i = 0; i < el.childNodes.length; i++) {
          const node = el.childNodes[i];
          if (node.nodeType === 3 && node.textContent.trim() === 'Настройки') {
            node.textContent = 'Внешний вид';
          }
        }
      });

      // cloneNode strips event listeners, so attach fresh handler
      item.addEventListener('click', (e) => {
        e.stopPropagation();
        document.body.click();
        setTimeout(() => openPanel(), 120);
      });

      // Insert right after "Настройки"
      settingsBtn.parentElement.insertBefore(item, settingsBtn.nextSibling);
    });

    observer.observe(document.body, { childList: true, subtree: true });
  }

  /* ───────────────────────────────────
     Hide the built-in Theme row in Settings → General
     ─────────────────────────────────── */
  function hideBuiltInThemeSetting() {
    // OpenWebUI settings modal has a "Тема" label next to a <select>.
    // We'll observe for the settings modal and hide that row.
    const observer = new MutationObserver(() => {
      const selects = document.querySelectorAll('select');
      selects.forEach(sel => {
        // The theme selector typically has options like "System"/"Dark"/"Light"
        // and sits near text "Тема" or "Theme"
        const options = Array.from(sel.options).map(o => o.value);
        if (options.includes('system') && options.includes('dark') && options.includes('light')) {
          // Find the closest container row
          const row = sel.closest('.py-0\\.5') || sel.closest('div[class*="justify-between"]') || sel.parentElement?.parentElement;
          if (row) {
            row.style.display = 'none';
          }
        }
      });
    });
    observer.observe(document.body, { childList: true, subtree: true });
  }

  /* ───────────────────────────────────
     Init
     ─────────────────────────────────── */
  function init() {
    // Restore accent immediately (prevent FOUC)
    const savedAccent = localStorage.getItem(ACCENT_KEY);
    if (savedAccent) {
      document.documentElement.setAttribute('data-theme', savedAccent);
    }

    // Restore mode
    const savedMode = localStorage.getItem(MODE_KEY) || 'system';
    applyMode(savedMode);

    // System preference listener for "system" mode
    window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
      const currentMode = localStorage.getItem(MODE_KEY) || 'system';
      if (currentMode === 'system') applyMode('system');
    });

    // Wait for DOM
    const boot = () => {
      buildPanel();
      injectMenuItem();
      hideBuiltInThemeSetting();
    };

    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', boot);
    } else {
      boot();
    }
  }

  init();
})();
