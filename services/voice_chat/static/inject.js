/**
 * Voice Chat Injection Script — Inline Overlay
 * ==============================================
 * Injected into OpenWebUI to replace the native voice mode button behavior
 * with our custom real-time voice chat powered by WebSocket + Whisper + MWS GPT.
 *
 * Renders the voice chat UI as a fullscreen overlay INSIDE the current page.
 * No popups, no iframes — pure DOM injection.
 */
(function () {
    'use strict';

    const VOICE_HOST = window.location.hostname || 'localhost';
    const VOICE_PORT = '9001';
    const WS_URL = `ws://${VOICE_HOST}:${VOICE_PORT}/ws/voice`;

    let overlay = null;
    let ws = null;
    let audioCtx = null;
    let micStream = null;
    let scriptNode = null;
    let audioQueue = [];
    let isPlayingAudio = false;
    let currentAudioEl = null;
    let currentState = 'idle';

    // ── Create Overlay UI ──────────────────────────────────────
    function createOverlay() {
        if (overlay) return overlay;

        overlay = document.createElement('div');
        overlay.id = 'voice-chat-overlay';
        overlay.innerHTML = `
            <style>
                #voice-chat-overlay {
                    position: fixed; inset: 0; z-index: 999999;
                    background: rgba(0,0,0,0.95);
                    display: flex; flex-direction: column;
                    align-items: center; justify-content: center;
                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
                    color: #fff;
                    opacity: 0; transition: opacity 0.3s ease;
                }
                #voice-chat-overlay.visible { opacity: 1; }
                #vc-close-btn {
                    position: absolute; top: 20px; right: 24px;
                    background: rgba(255,255,255,0.1); border: none; color: #fff;
                    width: 44px; height: 44px; border-radius: 50%;
                    font-size: 22px; cursor: pointer; display: flex;
                    align-items: center; justify-content: center;
                    transition: background 0.2s;
                }
                #vc-close-btn:hover { background: rgba(255,255,255,0.25); }
                #vc-assistant-text {
                    position: absolute; top: 8%; left: 50%;
                    transform: translateX(-50%);
                    font-size: 18px; color: rgba(255,255,255,0.7);
                    text-align: center; max-width: 70%;
                    opacity: 0; transition: opacity 0.3s;
                    line-height: 1.5;
                }
                #vc-assistant-text.visible { opacity: 1; }
                #vc-orb {
                    width: 220px; height: 220px; border-radius: 50%;
                    background: radial-gradient(circle at 40% 40%, #6C8BFA, #3B5BDB 60%, #1a1a2e);
                    box-shadow: 0 0 60px rgba(99,130,255,0.4);
                    cursor: pointer;
                    transition: transform 0.15s ease, box-shadow 0.15s ease;
                }
                #vc-orb.speaking {
                    background: radial-gradient(circle at 40% 40%, #7C6BFA, #5B3BDB 60%, #2a1a3e);
                    box-shadow: 0 0 80px rgba(130,99,255,0.5);
                }
                #vc-orb.thinking {
                    background: radial-gradient(circle at 40% 40%, #FAC86C, #DB8B3B 60%, #2e1a1a);
                    box-shadow: 0 0 60px rgba(255,180,99,0.4);
                    animation: vc-pulse 1.5s ease-in-out infinite;
                }
                #vc-orb.error {
                    background: radial-gradient(circle at 40% 40%, #FA6C6C, #DB3B3B 60%, #2e1a1a);
                    box-shadow: 0 0 60px rgba(255,99,99,0.4);
                }
                @keyframes vc-pulse {
                    0%, 100% { transform: scale(1); }
                    50% { transform: scale(1.06); }
                }
                #vc-status {
                    margin-top: 28px; font-size: 16px;
                    color: #6C8BFA; letter-spacing: 1px;
                }
                #vc-user-text {
                    position: absolute; bottom: 12%; left: 50%;
                    transform: translateX(-50%);
                    font-size: 15px; color: rgba(255,255,255,0.5);
                    text-align: center; max-width: 70%;
                    opacity: 0; transition: opacity 0.3s;
                }
                #vc-user-text.visible { opacity: 1; }
            </style>
            <button id="vc-close-btn" title="Закрыть">✕</button>
            <div id="vc-assistant-text"></div>
            <div id="vc-orb"></div>
            <div id="vc-status">Подключение...</div>
            <div id="vc-user-text"></div>
        `;
        document.body.appendChild(overlay);
        requestAnimationFrame(() => overlay.classList.add('visible'));

        overlay.querySelector('#vc-close-btn').addEventListener('click', closeVoiceChat);
        overlay.querySelector('#vc-orb').addEventListener('click', () => {
            if (ws && ws.readyState === WebSocket.OPEN) {
                ws.send(JSON.stringify({ type: 'interrupt' }));
            }
        });

        return overlay;
    }

    // ── WebSocket ──────────────────────────────────────────────
    function connectWS() {
        ws = new WebSocket(WS_URL);

        ws.onopen = () => {
            console.log('[VoiceChat] WebSocket connected');
            setState('listening');
        };

        ws.onmessage = (event) => {
            try {
                const msg = JSON.parse(event.data);
                handleServerEvent(msg);
            } catch (e) { /* ignore */ }
        };

        ws.onclose = () => {
            console.log('[VoiceChat] WebSocket closed');
            setState('error');
        };

        ws.onerror = () => setState('error');
    }

    function handleServerEvent(msg) {
        switch (msg.type) {
            case 'status':
                setState(msg.state);
                break;
            case 'transcript':
                showUserText(msg.text);
                break;
            case 'assistant_text':
                if (msg.text) showAssistantText(msg.text);
                break;
            case 'assistant_audio':
                if (msg.audio) {
                    audioQueue.push(msg.audio);
                    playNextAudio();
                }
                break;
            case 'stop_audio':
                stopAllAudio();
                break;
            case 'rms':
                updateOrb(msg.level);
                break;
            case 'error':
                console.error('[VoiceChat]', msg.message);
                break;
        }
    }

    // ── State Management ──────────────────────────────────────
    function setState(state) {
        currentState = state;
        const orb = document.getElementById('vc-orb');
        const status = document.getElementById('vc-status');
        if (!orb || !status) return;

        orb.className = '';
        switch (state) {
            case 'listening':
                status.textContent = 'Слушаю...';
                status.style.color = '#6C8BFA';
                break;
            case 'thinking':
                orb.classList.add('thinking');
                status.textContent = 'Думаю...';
                status.style.color = '#FAC86C';
                break;
            case 'speaking':
                orb.classList.add('speaking');
                status.textContent = 'Говорю...';
                status.style.color = '#7C6BFA';
                break;
            case 'error':
                orb.classList.add('error');
                status.textContent = 'Ошибка подключения';
                status.style.color = '#FA6C6C';
                break;
        }
    }

    function showAssistantText(text) {
        const el = document.getElementById('vc-assistant-text');
        if (el) { el.textContent = text; el.classList.add('visible'); }
    }

    function showUserText(text) {
        const el = document.getElementById('vc-user-text');
        if (el) {
            el.textContent = `Вы: ${text}`;
            el.classList.add('visible');
            setTimeout(() => el.classList.remove('visible'), 5000);
        }
    }

    function updateOrb(rms) {
        const orb = document.getElementById('vc-orb');
        if (orb && currentState === 'listening') {
            const scale = 1 + Math.min(rms * 8, 0.3);
            orb.style.transform = `scale(${scale})`;
        }
    }

    // ── Microphone ────────────────────────────────────────────
    async function startMicrophone() {
        audioCtx = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 16000 });
        micStream = await navigator.mediaDevices.getUserMedia({
            audio: { sampleRate: 16000, channelCount: 1, echoCancellation: true, noiseSuppression: true }
        });

        const source = audioCtx.createMediaStreamSource(micStream);

        // Use ScriptProcessorNode (wider browser support)
        scriptNode = audioCtx.createScriptProcessor(4096, 1, 1);
        scriptNode.onaudioprocess = (e) => {
            if (!ws || ws.readyState !== WebSocket.OPEN) return;

            const float32 = e.inputBuffer.getChannelData(0);
            // Convert float32 → int16
            const int16 = new Int16Array(float32.length);
            for (let i = 0; i < float32.length; i++) {
                const s = Math.max(-1, Math.min(1, float32[i]));
                int16[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
            }

            // Base64 encode
            const bytes = new Uint8Array(int16.buffer);
            let binary = '';
            for (let i = 0; i < bytes.length; i++) {
                binary += String.fromCharCode(bytes[i]);
            }
            const b64 = btoa(binary);

            ws.send(JSON.stringify({ type: 'audio_chunk', data: b64 }));
        };

        source.connect(scriptNode);
        scriptNode.connect(audioCtx.destination);
    }

    // ── Audio Playback ────────────────────────────────────────
    async function playNextAudio() {
        if (isPlayingAudio || audioQueue.length === 0) return;
        isPlayingAudio = true;

        while (audioQueue.length > 0) {
            const b64 = audioQueue.shift();
            try { await playAudioChunk(b64); } catch (e) { /* skip */ }
        }
        isPlayingAudio = false;
    }

    function playAudioChunk(b64) {
        return new Promise((resolve, reject) => {
            const binary = atob(b64);
            const bytes = new Uint8Array(binary.length);
            for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);

            const blob = new Blob([bytes], { type: 'audio/mpeg' });
            const url = URL.createObjectURL(blob);
            const audio = new Audio(url);
            currentAudioEl = audio;

            audio.onended = () => { currentAudioEl = null; URL.revokeObjectURL(url); resolve(); };
            audio.onerror = (e) => { currentAudioEl = null; URL.revokeObjectURL(url); reject(e); };
            audio.play().catch(reject);
        });
    }

    function stopAllAudio() {
        audioQueue = [];
        isPlayingAudio = false;
        if (currentAudioEl) {
            currentAudioEl.pause();
            currentAudioEl.currentTime = 0;
            currentAudioEl = null;
        }
    }

    // ── Open / Close ──────────────────────────────────────────
    async function showVoiceChat() {
        createOverlay();
        try {
            await startMicrophone();
            connectWS();
        } catch (e) {
            console.error('[VoiceChat] Microphone error:', e);
            setState('error');
            const status = document.getElementById('vc-status');
            if (status) status.textContent = 'Нет доступа к микрофону';
        }
    }

    function closeVoiceChat() {
        // Stop audio
        stopAllAudio();

        // Close WebSocket
        if (ws) { ws.close(); ws = null; }

        // Stop microphone
        if (scriptNode) { scriptNode.disconnect(); scriptNode = null; }
        if (micStream) { micStream.getTracks().forEach(t => t.stop()); micStream = null; }
        if (audioCtx) { audioCtx.close(); audioCtx = null; }

        // Remove overlay
        if (overlay) {
            overlay.classList.remove('visible');
            setTimeout(() => { overlay.remove(); overlay = null; }, 300);
        }

        currentState = 'idle';
    }

    // ── Button Interception ───────────────────────────────────
    function patchVoiceButton(button) {
        if (button._voiceChatPatched) return;
        button._voiceChatPatched = true;

        button.addEventListener('click', (e) => {
            e.stopImmediatePropagation();
            e.preventDefault();
            showVoiceChat();
        }, true);

        console.log('[VoiceChat] Voice mode button patched ✓');
    }

    const observer = new MutationObserver(() => {
        const buttons = document.querySelectorAll('button[aria-label]');
        for (const btn of buttons) {
            const label = btn.getAttribute('aria-label')?.toLowerCase() || '';
            if (label.includes('voice mode') || label.includes('голос')) {
                patchVoiceButton(btn);
            }
        }
    });

    if (document.body) {
        observer.observe(document.body, { childList: true, subtree: true });
    } else {
        document.addEventListener('DOMContentLoaded', () => {
            observer.observe(document.body, { childList: true, subtree: true });
        });
    }

    let checkCount = 0;
    const checkInterval = setInterval(() => {
        const buttons = document.querySelectorAll('button[aria-label]');
        for (const btn of buttons) {
            const label = btn.getAttribute('aria-label')?.toLowerCase() || '';
            if (label.includes('voice mode') || label.includes('голос')) {
                patchVoiceButton(btn);
            }
        }
        if (++checkCount > 20) clearInterval(checkInterval);
    }, 1000);

    console.log('[VoiceChat] Injection script loaded — inline overlay mode');
})();