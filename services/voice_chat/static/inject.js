/**
 * Voice Chat Injection Script
 * ============================
 * Injected into OpenWebUI to replace the native voice mode button behavior
 * with our custom real-time voice chat powered by WebSocket + Whisper + MWS GPT.
 *
 * Opens the voice chat as a fullscreen popup window (avoids CSP/iframe issues).
 */
(function () {
    'use strict';

    // Voice chat service URL — auto-detect from current hostname
    const VOICE_CHAT_HOST = window.location.hostname || 'localhost';
    const VOICE_CHAT_PORT = '9001';
    const VOICE_CHAT_URL = `${window.location.protocol}//${VOICE_CHAT_HOST}:${VOICE_CHAT_PORT}/`;

    let popupWindow = null;

    /**
     * Open voice chat in a fullscreen popup window
     */
    function showVoiceChat() {
        // If popup already open, focus it
        if (popupWindow && !popupWindow.closed) {
            popupWindow.focus();
            return;
        }

        // Open fullscreen popup
        const w = window.screen.width;
        const h = window.screen.height;
        popupWindow = window.open(
            VOICE_CHAT_URL,
            'VoiceChat',
            `width=${w},height=${h},left=0,top=0,menubar=no,toolbar=no,location=no,status=no,scrollbars=no`
        );

        // If popup was blocked, fallback to new tab
        if (!popupWindow) {
            window.open(VOICE_CHAT_URL, '_blank');
        }
    }

    /**
     * Watch for the voice mode button and intercept its click
     */
    function patchVoiceButton(button) {
        if (button._voiceChatPatched) return;
        button._voiceChatPatched = true;

        // Add click handler in capture phase (fires before Svelte's handler)
        button.addEventListener('click', (e) => {
            e.stopImmediatePropagation();
            e.preventDefault();
            showVoiceChat();
        }, true);

        console.log('[VoiceChat] Voice mode button patched ✓');
    }

    /**
     * MutationObserver to watch for the voice mode button
     * The button may be added/removed as Svelte re-renders
     */
    const observer = new MutationObserver(() => {
        const buttons = document.querySelectorAll('button[aria-label]');
        for (const btn of buttons) {
            const label = btn.getAttribute('aria-label')?.toLowerCase() || '';
            if (label.includes('voice mode') || label.includes('голос')) {
                patchVoiceButton(btn);
            }
        }
    });

    // Start observing once DOM is ready
    if (document.body) {
        observer.observe(document.body, { childList: true, subtree: true });
    } else {
        document.addEventListener('DOMContentLoaded', () => {
            observer.observe(document.body, { childList: true, subtree: true });
        });
    }

    // Also check periodically for the first few seconds
    let checkCount = 0;
    const checkInterval = setInterval(() => {
        const buttons = document.querySelectorAll('button[aria-label]');
        for (const btn of buttons) {
            const label = btn.getAttribute('aria-label')?.toLowerCase() || '';
            if (label.includes('voice mode') || label.includes('голос')) {
                patchVoiceButton(btn);
            }
        }
        checkCount++;
        if (checkCount > 20) clearInterval(checkInterval);
    }, 1000);

    console.log('[VoiceChat] Injection script loaded — waiting for voice mode button');
})();
