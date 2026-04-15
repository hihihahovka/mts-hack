/**
 * MTS AI Workspace — Citation Pills v2
 * ======================================
 * Стилизует citation-ссылки как pill-бейджи.
 *
 * Матчит ссылки с текстом: (N) или (N) Любой текст
 * Заголовок берёт из текста ссылки (если есть) или из домена href.
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
        background: rgba(255, 0, 50, 0.12) !important;
        color: #FF0032 !important;
        border: none !important;
      }
      .dark a.mts-pill {
        background: rgba(255, 0, 50, 0.2) !important;
        color: #FF0032 !important;
        border: none !important;
      }
      a.mts-pill:hover {
        background: rgba(255, 0, 50, 0.22) !important;
        box-shadow: none !important;
        transform: translateY(-1px) !important;
      }
      .dark a.mts-pill:hover {
        background: rgba(255, 0, 50, 0.3) !important;
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
        background: #FF0032 !important;
        color: #FFFFFF !important;
      }
      .dark a.mts-pill .mts-pill-num {
        background: #FF0032 !important;
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

  // Матчит텍스트вида: (2) OR (2) Some title text
  const CITE_RE = /^\((\d+)\)(?:\s+(.+))?$/;

  function getDomain(href) {
    try {
      const u = new URL(href);
      return u.hostname.replace(/^www\./, '');
    } catch (e) {
      return '';
    }
  }

  function pillify(a) {
    if (a.dataset.mtsPill) return;

    const raw = (a.textContent || '').trim();
    const m = raw.match(CITE_RE);
    if (!m) return;

    const href = a.getAttribute('href') || '';
    if (!href.startsWith('http')) return;

    a.dataset.mtsPill = '1';

    const num = m[1];
    // Заголовок: берём из текста ссылки, если есть, иначе домен
    let label = (m[2] || '').trim();
    if (!label) {
      label = getDomain(href);
    }
    // Ограничиваем длину
    if (label.length > 30) {
      label = label.slice(0, 30).trimEnd();
    }

    a.classList.add('mts-pill');
    a.setAttribute('target', '_blank');
    a.setAttribute('rel', 'noopener noreferrer');
    a.title = href;

    a.innerHTML =
      `<span class="mts-pill-num">${num}</span>` +
      (label ? `<span class="mts-pill-label">${esc(label)}</span>` : '');
  }

  function esc(s) {
    return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  function scan(root) {
    (root.querySelectorAll ? root : document).querySelectorAll('a[href]').forEach(a => {
      try { pillify(a); } catch (_) { }
    });
  }

  const obs = new MutationObserver(muts => {
    for (const m of muts) {
      for (const n of m.addedNodes) {
        if (n.nodeType !== 1) continue;
        scan(n);
        if (n.tagName === 'A') try { pillify(n); } catch (_) { }
      }
    }
  });

  function init() {
    scan(document);
    obs.observe(document.body, { childList: true, subtree: true });
    console.log('[MTS] Citation pills v2 ready');
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
