/**
 * MTS AI Workspace — Citation Pills v3
 * ======================================
 * Стилизует citation-ссылки как pill-бейджи.
 *
 * Шаг 1: Матчит <a href> с текстом "(N)" → pill-бейдж + запоминает N→URL
 * Шаг 2: Находит голые "(N)" в тексте и заменяет на <a>-ссылки из карты → pill
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
    `;
    document.head.appendChild(style);
  }

  // Карта: номер цитаты → URL  (заполняется при обработке <a> элементов)
  const urlMap = {};

  // Матчит текст вида: (2) OR (2) Some title text
  const CITE_RE = /^\((\d+)\)(?:\s+(.+))?$/;
  // Матчит голый (N) в тексте
  const BARE_RE = /\((\d+)\)/g;

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

  /** Шаг 1: Превращает <a href> с текстом "(N)" в pill и запоминает маппинг */
  function pillify(a) {
    if (a.dataset.mtsPill) return;

    const raw = (a.textContent || '').trim();
    const m = raw.match(CITE_RE);
    if (!m) return;

    const href = a.getAttribute('href') || '';
    if (!href.startsWith('http')) return;

    a.dataset.mtsPill = '1';

    const num = m[1];
    // Запоминаем маппинг для шага 2
    if (!urlMap[num]) urlMap[num] = href;

    let label = (m[2] || '').trim();
    if (!label) label = getDomain(href);
    if (label.length > 30) label = label.slice(0, 30).trimEnd();

    a.classList.add('mts-pill');
    a.setAttribute('target', '_blank');
    a.setAttribute('rel', 'noopener noreferrer');
    a.title = href;
    a.innerHTML = buildPillHTML(num, label);
  }

  /** Шаг 2: Заменяет голые (N) в текстовых узлах на pill-ссылки из urlMap */
  function replaceBareCitations(root) {
    if (!Object.keys(urlMap).length) return;

    const walker = document.createTreeWalker(
      root instanceof Document ? document.body : root,
      NodeFilter.SHOW_TEXT,
      {
        acceptNode(node) {
          // Пропускаем текст внутри <a>, <code>, <pre>, <script>
          const parent = node.parentElement;
          if (!parent) return NodeFilter.FILTER_REJECT;
          const tag = parent.tagName.toLowerCase();
          if (['a', 'code', 'pre', 'script', 'style'].includes(tag)) {
            return NodeFilter.FILTER_REJECT;
          }
          // Только если есть хотя бы один (N)
          if (!BARE_RE.test(node.textContent)) return NodeFilter.FILTER_REJECT;
          BARE_RE.lastIndex = 0;
          return NodeFilter.FILTER_ACCEPT;
        }
      }
    );

    const nodesToReplace = [];
    let node;
    while ((node = walker.nextNode())) nodesToReplace.push(node);

    for (const textNode of nodesToReplace) {
      const text = textNode.textContent;
      // Разбиваем на части по паттерну (N)
      const parts = text.split(/(\(\d+\))/);
      if (parts.length <= 1) continue;

      let changed = false;
      const fragment = document.createDocumentFragment();

      for (const part of parts) {
        const mPart = part.match(/^\((\d+)\)$/);
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

  /** Сканирует элемент: сначала <a> пиллы, потом голые (N) */
  function scan(root) {
    const el = root.querySelectorAll ? root : document;
    el.querySelectorAll('a[href]').forEach(a => {
      try { pillify(a); } catch (_) {}
    });
    // После сбора urlMap — заменяем голые (N)
    try { replaceBareCitations(el); } catch (_) {}
  }

  const obs = new MutationObserver(muts => {
    let needTextScan = false;
    for (const m of muts) {
      for (const n of m.addedNodes) {
        if (n.nodeType !== 1) continue;
        // Новые <a> → pillify и обновить карту
        n.querySelectorAll && n.querySelectorAll('a[href]').forEach(a => {
          try { pillify(a); } catch (_) {}
        });
        if (n.tagName === 'A') try { pillify(n); } catch (_) {}
        needTextScan = true;
      }
    }
    // Один проход по тексту после пачки мутаций
    if (needTextScan) {
      try { replaceBareCitations(document.body); } catch (_) {}
    }
  });

  function init() {
    scan(document);
    obs.observe(document.body, { childList: true, subtree: true });
    console.log('[MTS] Citation pills v3 ready (bare-citation patch enabled)');
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
