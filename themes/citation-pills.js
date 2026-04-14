/**
 * MTS AI Workspace — Citation Pills v4
 * ======================================
 * Стилизует citation-ссылки как pill-бейджи.
 *
 * Шаг 1: Читает скрытую JSON-карту из HTML-комментария <!-- mts-cite-map:{...} -->
 *         Карта: { "N": "https://..." }
 * Шаг 2: Находит [N] в тексте и заменяет на кликабельный pill-бейдж
 */
(function () {
  'use strict';

  const STYLE_ID = 'mts-citation-pills-style';
  if (!document.getElementById(STYLE_ID)) {
    const style = document.createElement('style');
    style.id = STYLE_ID;
    style.textContent = `
      a.mts-pill {
        display: inline-flex !important;
        align-items: center !important;
        gap: 5px !important;
        margin: 0 2px !important;
        padding: 2px 9px 2px 5px !important;
        border-radius: 999px !important;
        font-size: 11.5px !important;
        font-weight: 500 !important;
        line-height: 1.5 !important;
        white-space: nowrap !important;
        max-width: 180px !important;
        overflow: hidden !important;
        text-decoration: none !important;
        cursor: pointer !important;
        vertical-align: middle !important;
        position: relative !important;
        top: -1px !important;
        font-family: 'MTS Text', -apple-system, BlinkMacSystemFont, sans-serif !important;
        transition: background 0.15s ease, box-shadow 0.15s ease, transform 0.1s ease !important;
        background: rgba(255, 0, 50, 0.10) !important;
        color: #FF0032 !important;
        border: 1px solid rgba(255, 0, 50, 0.25) !important;
      }
      .dark a.mts-pill {
        background: rgba(255, 0, 50, 0.12) !important;
        color: #FF3358 !important;
        border: 1px solid rgba(255, 0, 50, 0.28) !important;
      }
      a.mts-pill:hover {
        background: rgba(255, 0, 50, 0.20) !important;
        box-shadow: 0 1px 8px rgba(255, 0, 50, 0.30) !important;
        transform: translateY(-1px) !important;
      }
      a.mts-pill:active {
        transform: translateY(0) !important;
      }
      a.mts-pill .mts-pill-num {
        display: inline-flex !important;
        align-items: center !important;
        justify-content: center !important;
        min-width: 17px !important;
        height: 17px !important;
        border-radius: 50% !important;
        font-size: 10px !important;
        font-weight: 700 !important;
        flex-shrink: 0 !important;
        background: rgba(255, 0, 50, 0.20) !important;
        color: inherit !important;
      }
      .dark a.mts-pill .mts-pill-num {
        background: rgba(255, 0, 50, 0.28) !important;
      }
      a.mts-pill .mts-pill-label {
        overflow: hidden !important;
        text-overflow: ellipsis !important;
        white-space: nowrap !important;
        max-width: 130px !important;
      }
      /* Скрываем HTML-комментарий с JSON-картой */
      .mts-cite-map-node { display: none !important; }
    `;
    document.head.appendChild(style);
  }

  // Карта: N (строка) → URL
  const urlMap = {};

  // Регекс для поиска [N] в тексте, например [1] [12]
  const BRACKET_RE = /\[(\d+)\]/g;

  function getDomain(href) {
    try {
      const u = new URL(href);
      return u.hostname.replace(/^www\./, '');
    } catch (e) {
      return '';
    }
  }

  function esc(s) {
    return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  function buildPillHTML(num, label) {
    return (
      `<span class="mts-pill-num">${num}</span>` +
      (label ? `<span class="mts-pill-label">${esc(label)}</span>` : '')
    );
  }

  /**
   * Парсит HTML-комментарии вида <!-- mts-cite-map:{...} --> из DOM
   * и заполняет urlMap данными из JSON.
   */
  function extractCiteMap(root) {
    const walker = document.createTreeWalker(
      root instanceof Document ? document.body : root,
      NodeFilter.SHOW_COMMENT,
      null
    );
    let node;
    while ((node = walker.nextNode())) {
      const text = node.nodeValue || '';
      const match = text.match(/^\s*mts-cite-map:(\{[\s\S]*\})\s*$/);
      if (match) {
        try {
          const parsed = JSON.parse(match[1]);
          Object.assign(urlMap, parsed);
          // Скрываем родительский элемент комментария если возможно
          if (node.parentElement) {
            node.parentElement.classList.add('mts-cite-map-node');
          }
        } catch (e) {
          console.warn('[MTS] Failed to parse mts-cite-map JSON:', e);
        }
      }
    }
  }

  /** Заменяет [N] в текстовых узлах на pill-ссылки из urlMap */
  function replaceBracketCitations(root) {
    if (!Object.keys(urlMap).length) return;

    const walker = document.createTreeWalker(
      root instanceof Document ? document.body : root,
      NodeFilter.SHOW_TEXT,
      {
        acceptNode(node) {
          const parent = node.parentElement;
          if (!parent) return NodeFilter.FILTER_REJECT;
          const tag = parent.tagName.toLowerCase();
          // Пропускаем <a>, <code>, <pre>, <script>, <style>
          if (['a', 'code', 'pre', 'script', 'style'].includes(tag)) {
            return NodeFilter.FILTER_REJECT;
          }
          // Принимаем только если есть [N]
          BRACKET_RE.lastIndex = 0;
          if (!BRACKET_RE.test(node.textContent)) return NodeFilter.FILTER_REJECT;
          BRACKET_RE.lastIndex = 0;
          return NodeFilter.FILTER_ACCEPT;
        }
      }
    );

    const nodesToReplace = [];
    let node;
    while ((node = walker.nextNode())) nodesToReplace.push(node);

    for (const textNode of nodesToReplace) {
      const text = textNode.textContent;
      // Разбиваем на части по [N]
      const parts = text.split(/(\[\d+\])/);
      if (parts.length <= 1) continue;

      let changed = false;
      const fragment = document.createDocumentFragment();

      for (const part of parts) {
        BRACKET_RE.lastIndex = 0;
        const mPart = part.match(/^\[(\d+)\]$/);
        if (mPart && urlMap[mPart[1]]) {
          const num = mPart[1];
          const href = urlMap[num];
          const label = getDomain(href);
          const a = document.createElement('a');
          a.href = href;
          a.setAttribute('target', '_blank');
          a.setAttribute('rel', 'noopener noreferrer');
          a.setAttribute('title', href);
          a.setAttribute('data-mts-pill', '1');
          a.classList.add('mts-pill');
          a.innerHTML = buildPillHTML(num, label);
          fragment.appendChild(a);
          changed = true;
        } else {
          fragment.appendChild(document.createTextNode(part));
        }
      }

      if (changed && textNode.parentNode) {
        textNode.parentNode.replaceChild(fragment, textNode);
      }
    }
  }

  /** Полный проход: сначала читаем карту, потом заменяем [N] */
  function scan(root) {
    try { extractCiteMap(root); } catch (_) {}
    try { replaceBracketCitations(root); } catch (_) {}
  }

  const obs = new MutationObserver(muts => {
    let needScan = false;
    for (const m of muts) {
      for (const n of m.addedNodes) {
        if (n.nodeType === Node.COMMENT_NODE) {
          // Новый комментарий — возможно карта
          const text = n.nodeValue || '';
          if (text.includes('mts-cite-map:')) {
            try {
              const match = text.match(/mts-cite-map:(\{[\s\S]*\})/);
              if (match) Object.assign(urlMap, JSON.parse(match[1]));
            } catch (_) {}
            needScan = true;
          }
        } else if (n.nodeType === 1) {
          // Новый элемент — ищем комментарии внутри
          try { extractCiteMap(n); } catch (_) {}
          needScan = true;
        }
      }
    }
    if (needScan) {
      try { replaceBracketCitations(document.body); } catch (_) {}
    }
  });

  function init() {
    scan(document);
    obs.observe(document.body, { childList: true, subtree: true });
    console.log('[MTS] Citation pills v4 ready (square-bracket [N] mode)');
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
