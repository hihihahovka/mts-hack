/**
 * MTS AI Workspace — Citation Pills v4
 * ======================================
 * Стилизует citation-ссылки как pill-бейджи.
 *
 * Шаг 1: Читает скрытый <span id="mts-cite-map" data-map='{"1":"url",...}'>
 *         который бэкенд вставляет в конец отчёта.
 * Шаг 2: Находит [N] в тексте и заменяет на кликабельный pill-бейдж.
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
      /* Скрываем встроенные серые плашки цитат от Open WebUI для Deep Research */
      button[data-source-title*="deep_research"],
      button[data-source-title*="undefined"] {
        display: none !important;
      }
    `;
    document.head.appendChild(style);
  }

  // Глобальный реестр уникальных URL для присвоения номеров
  const uniqueUrls = [];

  function getCiteNumForUrl(href) {
    if (!href) return '?';
    // Нормализуем URL (убираем концевые слэши)
    const norm = href.replace(/\/$/, '');
    let idx = uniqueUrls.findIndex(u => u.replace(/\/$/, '') === norm);
    if (idx === -1) {
      uniqueUrls.push(href);
      idx = uniqueUrls.length - 1;
    }
    return idx + 1;
  }

  function getDomain(href) {
    try {
      return new URL(href).hostname.replace(/^www\./, '');
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
   * Превращает существующий <a> тег в pill-бейдж, если это похоже на цитату.
   */
  function processAnchorTags(root) {
    const searchRoot = root instanceof Document ? document.body : root;
    if (!searchRoot) return;

    const anchors = searchRoot.querySelectorAll('a:not(.mts-pill)');
    anchors.forEach(a => {
      // Игнорируем если уже обработан или внутри каких-то спец блоков
      if (a.hasAttribute('data-mts-pill')) return;
      if (a.closest('code, pre, .mts-pill')) return;

      const text = a.textContent.trim();
      const href = a.href;
      if (!href || !href.startsWith('http')) return;

      // Если текст ссылки это просто цифра (рендер от [1](url))
      // Или если текст начинается с http (рендер от авто-ссылок)
      // Или если текст пустой
      const isNum = /^\d+$/.test(text);
      const isUrl = text.startsWith('http');
      
      if (isNum || isUrl || text === '') {
        const num = getCiteNumForUrl(href);
        const label = getDomain(href);
        
        a.setAttribute('target', '_blank');
        a.setAttribute('rel', 'noopener noreferrer');
        a.setAttribute('title', href);
        a.setAttribute('data-mts-pill', '1');
        a.classList.add('mts-pill');
        a.innerHTML = buildPillHTML(num, label);

        // Удаляем скобки вокруг ссылки: "( " перед ссылкой и " )." после, если они есть
        if (a.previousSibling && a.previousSibling.nodeType === 3) {
            a.previousSibling.textContent = a.previousSibling.textContent.replace(/[\(\[]\s*$/, '');
        }
        if (a.nextSibling && a.nextSibling.nodeType === 3) {
            a.nextSibling.textContent = a.nextSibling.textContent.replace(/^\s*[\)\]]/, '');
        }
      }
    });
  }

  // Регекс: ищет URL в скобках (https://...) или [https://...]
  const RAW_URL_RE = /[\(\[]\s*(https?:\/\/[^\s\)\]]+)\s*[\)\]]/g;

  /** Заменяет (url) и [url] в текстовых узлах на pill-ссылки */
  function replaceTextNodeCitations(root) {
    const searchRoot = root instanceof Document ? document.body : root;
    if (!searchRoot) return;

    const walker = document.createTreeWalker(
      searchRoot,
      NodeFilter.SHOW_TEXT,
      {
        acceptNode(node) {
          const parent = node.parentElement;
          if (!parent) return NodeFilter.FILTER_REJECT;
          const tag = parent.tagName.toLowerCase();
          // Пропускаем теги, в которых замена не нужна
          if (['a', 'code', 'pre', 'script', 'style'].includes(tag)) {
            return NodeFilter.FILTER_REJECT;
          }
          // Принимаем только если есть URL в скобках
          RAW_URL_RE.lastIndex = 0;
          if (!RAW_URL_RE.test(node.textContent)) return NodeFilter.FILTER_REJECT;
          RAW_URL_RE.lastIndex = 0;
          return NodeFilter.FILTER_ACCEPT;
        }
      }
    );

    const nodesToReplace = [];
    let node;
    while ((node = walker.nextNode())) nodesToReplace.push(node);

    for (const textNode of nodesToReplace) {
      const text = textNode.textContent;
      
      // Разбиваем текст по сырым URL в скобках
      const parts = text.split(/([\(\[]\s*https?:\/\/[^\s\)\]]+\s*[\)\]])/i);
      if (parts.length <= 1) continue;

      let changed = false;
      const fragment = document.createDocumentFragment();

      for (const part of parts) {
        const mPart = part.match(/^[\(\[]\s*(https?:\/\/[^\s\)\]]+)\s*[\)\]]$/i);
        if (mPart) {
          let href = mPart[1];
          // Убираем возможные знаки пунктуации в конце URL
          href = href.replace(/[.,;:!?]+$/, '');

          const num = getCiteNumForUrl(href);
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

  /** Полный проход */
  function scan(root) {
    try { processAnchorTags(root); } catch (e) { console.error(e); }
    try { replaceTextNodeCitations(root); } catch (e) { console.error(e); }
  }

  const obs = new MutationObserver(muts => {
    let needScan = false;

    for (const m of muts) {
      for (const n of m.addedNodes) {
        if (n.nodeType === 1) { // Element
          needScan = true;
        } else if (n.nodeType === 3) { // Text Node
          needScan = true;
        }
      }
    }

    if (needScan) {
      // Ищем ближайший родительский контейнер сообщений или body, чтобы сузить область
      try { processAnchorTags(document.body); } catch (_) {}
      try { replaceTextNodeCitations(document.body); } catch (_) {}
    }
  });

  function init() {
    scan(document);
    obs.observe(document.body, { childList: true, subtree: true, characterData: true });
    console.log('[MTS] Citation pills v5 ready (Dynamic URL mode)');
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
