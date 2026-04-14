/**
 * MTS AI Workspace — Citation Pills
 * ==================================
 * Transforms inline citation links [(N) Title](url) into
 * styled pill/badge elements that open in a new tab.
 *
 * Pattern matched: <a href="..."> starting with "(N) "
 * e.g. "(1) Влияние Авито на" → pill with that text
 */
(function () {
  'use strict';

  // ── Styles injected once ─────────────────────────────────────────
  const STYLE_ID = 'mts-citation-pills-style';
  if (!document.getElementById(STYLE_ID)) {
    const style = document.createElement('style');
    style.id = STYLE_ID;
    style.textContent = `
      .mts-citation-pill {
        display: inline-flex;
        align-items: center;
        gap: 4px;
        margin: 0 2px;
        padding: 1px 8px 1px 6px;
        border-radius: 999px;
        font-size: 11px;
        font-weight: 500;
        line-height: 1.6;
        white-space: nowrap;
        max-width: 160px;
        overflow: hidden;
        text-decoration: none !important;
        cursor: pointer;
        transition: background 0.15s, box-shadow 0.15s, transform 0.1s;
        vertical-align: middle;
        position: relative;
        top: -1px;

        /* Light mode */
        background: rgba(100, 160, 255, 0.12);
        color: #3b6fd4;
        border: 1px solid rgba(100, 160, 255, 0.3);
      }

      /* Dark mode */
      :root[data-theme="dark"] .mts-citation-pill,
      .dark .mts-citation-pill {
        background: rgba(120, 170, 255, 0.15);
        color: #90b8ff;
        border: 1px solid rgba(120, 170, 255, 0.25);
      }

      .mts-citation-pill:hover {
        background: rgba(100, 160, 255, 0.22);
        box-shadow: 0 1px 6px rgba(100, 160, 255, 0.25);
        transform: translateY(-1px);
        text-decoration: none !important;
      }

      .mts-citation-pill:active {
        transform: translateY(0);
      }

      .mts-citation-pill__num {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        min-width: 16px;
        height: 16px;
        border-radius: 50%;
        font-size: 10px;
        font-weight: 700;
        flex-shrink: 0;
        background: rgba(100, 160, 255, 0.25);
        color: inherit;
      }

      :root[data-theme="dark"] .mts-citation-pill__num,
      .dark .mts-citation-pill__num {
        background: rgba(120, 170, 255, 0.25);
      }

      .mts-citation-pill__label {
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
        max-width: 120px;
      }
    `;
    document.head.appendChild(style);
  }

  // ── Citation link pattern: text starts with "(N) " ───────────────
  // Matches: (1) Some Title, (12) Another Source, etc.
  const CITATION_RE = /^\((\d+)\)\s+(.+)/;

  /**
   * Check if an <a> element is a citation pill candidate.
   * Returns { num, label } or null.
   */
  function parseCitationLink(anchor) {
    const text = (anchor.textContent || '').trim();
    const match = text.match(CITATION_RE);
    if (!match) return null;
    const href = anchor.getAttribute('href') || '';
    if (!href.startsWith('http')) return null;
    return { num: match[1], label: match[2] };
  }

  /**
   * Convert a plain citation <a> into a pill element.
   */
  function pillify(anchor) {
    if (anchor.dataset.mtsPill) return; // already processed
    const parsed = parseCitationLink(anchor);
    if (!parsed) return;

    anchor.dataset.mtsPill = '1';

    // Remove default link styling (markdown adds underline etc.)
    anchor.classList.add('mts-citation-pill');
    anchor.setAttribute('target', '_blank');
    anchor.setAttribute('rel', 'noopener noreferrer');
    anchor.title = anchor.href; // show full URL on hover

    // Replace text content with structured spans
    anchor.innerHTML = `
      <span class="mts-citation-pill__num">${parsed.num}</span>
      <span class="mts-citation-pill__label">${escapeHtml(parsed.label)}</span>
    `;
  }

  function escapeHtml(str) {
    return str
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  /**
   * Scan all anchor tags in a container and pillify citation ones.
   */
  function scanContainer(root) {
    root.querySelectorAll('a[href]').forEach(anchor => {
      try { pillify(anchor); } catch (e) {}
    });
  }

  // ── MutationObserver: watch for new rendered markdown ────────────
  const observer = new MutationObserver(mutations => {
    for (const mutation of mutations) {
      for (const node of mutation.addedNodes) {
        if (node.nodeType !== 1) continue; // only elements
        // Scan newly added subtrees
        scanContainer(node);
        // Also check if the node itself is an anchor
        if (node.tagName === 'A') {
          try { pillify(node); } catch (e) {}
        }
      }
    }
  });

  function init() {
    // Initial scan of existing content
    scanContainer(document);

    // Watch for future DOM changes (new messages rendered)
    observer.observe(document.body, {
      childList: true,
      subtree: true,
    });

    console.log('[MTS] Citation pills initialized');
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

})();
