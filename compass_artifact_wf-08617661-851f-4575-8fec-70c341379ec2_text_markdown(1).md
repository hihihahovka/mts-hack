# Building a low-latency Russian voice chat assistant with custom LLMs

Your existing pipeline — Browser → energy-based VAD → faster-whisper → LLM streaming → edge-tts → Browser — can be improved from a typical **1.1–3 seconds** end-to-end latency down to **400–700ms** with targeted optimizations, or below **300ms** by switching to self-hosted TTS. The highest-impact changes are replacing energy-based VAD with **Silero VAD**, implementing **sentence-level chunked TTS** to overlap LLM and TTS stages, switching faster-whisper to the **large-v3-turbo** model with greedy decoding, and adopting a framework like **Pipecat** or **LiveKit Agents** that handles streaming, barge-in, and pipeline orchestration out of the box. Both frameworks support custom OpenAI-compatible APIs via a simple `base_url` parameter, making them directly compatible with MWS GPT. For Russian TTS, **Silero TTS** offers the best combination of quality (CER 0.7, matching edge-tts), speed (<20ms on CPU), and self-hosting simplicity, while **XTTS v2** adds voice cloning with streaming at ~200ms latency on GPU.

---

## Your latency budget hides 60% of wasted time in sequential processing

The typical latency breakdown for a voice assistant pipeline reveals where time is lost:

| Stage | Naive (sequential) | Optimized (streaming) |
|-------|-------------------|-----------------------|
| Transport in | 20–50ms | 20–30ms |
| VAD + STT | 100–350ms | 50–100ms |
| LLM time-to-first-token | 200–600ms | 100–200ms |
| TTS time-to-first-byte | 100–500ms | 50–100ms |
| Transport out | 20–50ms | 20ms |
| **Total** | **1.1–3+ seconds** | **300–600ms** |

The critical insight is **streaming concurrency** — stages should overlap, not run sequentially. Start TTS synthesis on the first sentence while the LLM generates the rest. Start audio playback before TTS finishes the complete response. This alone can cut latency by 40–60%.

**Sentence-boundary splitting** between LLM and TTS is the single most impactful architectural change. The `stream2sentence` library by KoljaB extracts sentences from streaming text in real-time, enabling chunked TTS synthesis. Set `quick_yield_single_sentence_fragment=True` to yield the first fragment as fast as possible:

```python
import re, asyncio, edge_tts

async def stream_llm_to_tts(llm_stream, voice="ru-RU-DmitryNeural"):
    sentence_buffer = ""
    for token in llm_stream:
        sentence_buffer += token
        if re.search(r'[.!?]\s*$', sentence_buffer):
            communicate = edge_tts.Communicate(sentence_buffer, voice)
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    yield chunk["data"]
            sentence_buffer = ""
    if sentence_buffer.strip():
        communicate = edge_tts.Communicate(sentence_buffer, voice)
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                yield chunk["data"]
```

The async pipeline architecture uses `asyncio.Queue` between stages — STT produces transcripts, LLM consumes transcripts and produces sentences, TTS consumes sentences and produces audio chunks, and the playback stage streams audio to the browser. All four stages run concurrently via `asyncio.gather()`.

---

## Silero VAD eliminates the biggest weakness in your current pipeline

Energy-based VAD is your pipeline's weakest link. Research published in January 2026 (arXiv 2601.17270) found that at 100ms windows, energy-based VAD **"has a relatively narrow sweet spot and underperforms random guessing for most of its range."** Silero VAD dramatically outperforms both energy-based and WebRTC VAD across all conditions.

| Feature | Energy/RMS | WebRTC VAD | Silero VAD |
|---------|-----------|------------|------------|
| Approach | Signal level threshold | GMM-based | DNN (attention) |
| Accuracy | Poor | Moderate | **High** |
| Noise robustness | Very poor | Poor–moderate | **Excellent** |
| Latency per chunk | <1ms | <1ms | ~1ms (ONNX) |
| Size | Trivial | 158KB | ~1MB |

Integration is straightforward — load via `torch.hub.load('snakers4/silero-vad', 'silero_vad', onnx=True)` and call `model(audio_tensor, sample_rate)` to get speech probability per chunk. Use ONNX mode for 2–3x faster inference.

**Pre-speech buffering is essential.** Always maintain a rolling buffer of **200–300ms** of audio before speech detection triggers. Without this, the first syllable of every utterance gets clipped. A `collections.deque(maxlen=10)` holding 30ms chunks provides 300ms of lookback that gets prepended to the speech audio when VAD fires.

For **endpointing** (detecting when the user finishes speaking), a 300ms silence timeout works for responsive interaction but causes false triggers during thinking pauses. The state of the art combines Silero VAD with **semantic turn detection** — LiveKit's 3M-parameter transformer model analyzes the partial transcript to predict turn completeness in under 75ms, reducing false interruptions by **45%** versus VAD alone.

---

## faster-whisper gets 3–6x faster with the right settings for Russian

The `large-v3-turbo` model is the optimal choice for real-time Russian STT. It delivers **6x faster** inference than large-v3 with only 1–2% accuracy degradation. Combine it with greedy decoding and quantization:

```python
from faster_whisper import WhisperModel

model = WhisperModel(
    "large-v3-turbo",
    device="cuda",
    compute_type="int8_float16",   # 30-40% faster than float32
)

segments, info = model.transcribe(
    audio_data,
    language="ru",                  # Skip language detection (~30ms saved)
    beam_size=1,                    # Greedy decoding: 2-3x faster than default 5
    vad_filter=True,                # Built-in Silero VAD to skip silence
    vad_parameters=dict(min_silence_duration_ms=300, speech_pad_ms=200),
    condition_on_previous_text=False,  # Faster for short chunks
    word_timestamps=False,          # Skip word timestamps for speed
)
```

For Russian accuracy, Whisper large-v3 achieves **WER ~9.84%** on Common Voice Russian out of the box, improving to **6.39%** with the fine-tuned `antony66/whisper-large-v3-russian` model. The turbo variant sits between these numbers while being dramatically faster. Smaller models (tiny, base, small) are **not recommended for Russian** — accuracy drops sharply for non-English languages below the medium model size.

**Distil-whisper** offers 6x speedup over large-v3, but it is **English-only** and cannot be used for Russian. For Russian, large-v3-turbo is the correct choice.

If cloud STT is acceptable, **Yandex SpeechKit** delivers the best Russian accuracy at **95–97%** on clean audio, followed by Deepgram Nova-3 (which supports Russian among 45+ languages at $4.30/1000 minutes). For fully self-hosted Russian STT, NVIDIA NeMo provides dedicated Russian FastConformer models trained on 1,840 hours of Russian data with punctuation and capitalization support.

---

## Pipecat and LiveKit Agents both integrate directly with MWS GPT

Two frameworks stand out for building production voice assistants with custom OpenAI-compatible LLM APIs. Both are actively maintained, well-documented, and fully self-hostable.

**Pipecat** (BSD-2-Clause, ~10k GitHub stars) provides maximum flexibility with **80+ service integrations** including local STT (Whisper), local TTS (Piper, XTTS, Kokoro), and transport-agnostic deployment via WebSocket, WebRTC, or local audio. Connecting to MWS GPT requires only setting `base_url`:

```python
from pipecat.services.openai import OpenAILLMService

llm = OpenAILLMService(
    api_key="your-mws-api-key",
    base_url="https://your-mws-gpt-endpoint.mws.ru/v1",
    settings=OpenAILLMService.Settings(model="your-model-name"),
)
```

Its frame-based pipeline architecture handles streaming, barge-in, and interruption automatically. When VAD detects a `UserStartedSpeakingFrame`, a `StartInterruptionFrame` propagates through the entire pipeline, canceling LLM generation and flushing TTS buffers in **under 100ms**. Pipecat's `SmallWebRTCTransport` enables fully self-hosted WebRTC without any cloud dependency.

**LiveKit Agents** (Apache-2.0, ~9.2k stars) takes a WebRTC-first approach where the AI agent joins a LiveKit room as a participant. Its key differentiator is the **semantic turn detector** — a custom transformer model that determines end-of-turn with sub-75ms latency. LiveKit Server (the open-source SFU) is one of the most widely deployed WebRTC media servers and handles NAT traversal, echo cancellation, and multi-participant scenarios natively.

**Vocode** (MIT, ~3.7k stars) should be avoided for new projects — the last commit was November 2024, the team has shifted to a closed-source hosted platform, and the README actively seeks community maintainers. **Bolna** (MIT, ~2k stars) is telephony-first and uses LiteLLM for broad LLM compatibility, but its STT/TTS options are narrower than Pipecat or LiveKit.

| Feature | Pipecat | LiveKit Agents |
|---------|---------|----------------|
| MWS GPT integration | `base_url` parameter | `base_url` parameter |
| Self-hosted transport | WebSocket + SmallWebRTC | LiveKit Server (OSS) |
| Local STT | Whisper, Piper | Via plugins |
| Local TTS | Piper, XTTS, Kokoro, Silero | Via plugins |
| Barge-in | Frame-based, <100ms | AgentSession, configurable |
| Turn detection | VAD + endpointing | VAD + semantic transformer |
| Best for | Max flexibility, provider choice | WebRTC production, scale |

---

## Speech-to-speech models cannot replace your custom LLM pipeline — yet

Speech-to-speech (S2S) models eliminate the STT bottleneck by processing audio directly, achieving dramatically lower latency. However, they are **tightly integrated** — you cannot swap in an external LLM API like MWS GPT. This makes them fundamentally incompatible with the user's requirement for a custom OpenAI-compatible backend.

**Moshi** (Kyutai, MIT license) achieves ~**200ms** practical latency on an L4 GPU with true full-duplex conversation, but supports only English and French — **no Russian**. Its 7B-parameter Helium backbone, Mimi audio codec, and multi-stream decoder are inseparable components.

**GPT-4o Realtime API** delivers sub-200ms latency with the best quality and Russian support, but it is cloud-only, API-only ($0.06/min input, $0.24/min output), and cannot be self-hosted or connected to custom LLMs.

**Qwen3-Omni** (30B-A3B MoE, Alibaba) is the most promising open-source option for Russian — it supports Russian for both speech input AND output among 19 input and 10 output languages. It leads on 32/36 open-source audio benchmarks. However, it requires **24–40GB VRAM** and replaces the LLM entirely rather than integrating with MWS GPT.

**Ultravox** (Fixie AI, MIT) takes a unique approach — a Whisper encoder feeds directly into an LLM backbone (Llama, Gemma, or Qwen variants), eliminating STT latency. It supports **42 languages including Russian** (since v0.5). The LLM backbone can be swapped, but only through retraining, not runtime API configuration. It currently outputs text only, still requiring external TTS. With **~150ms TTFT** on A100, it could serve as a faster STT replacement within a traditional pipeline if the right backbone is trained.

The fundamental tradeoff: S2S models deliver **160–500ms** end-to-end latency versus **800–1,500ms** for cascaded pipelines, but sacrifice LLM flexibility, TTS voice selection, and (for most models) Russian language support. **For the user's setup with MWS GPT, the traditional STT→LLM→TTS pipeline remains the only viable architecture.**

---

## Russian TTS: Silero for speed, XTTS for quality, Fish Audio for state-of-the-art

Edge-tts works well (CER 0.7, UTMOS 3.565 for Russian — competitive with Yandex SpeechKit), but it is an **unofficial reverse-engineered API** with recent rate limiting, 10-minute audio caps, and no reliability guarantees. Microsoft could block it at any time.

The alphacephei benchmark data provides the clearest Russian TTS quality comparison:

| Engine | CER (lower=better) | UTMOS (higher=better) | Latency | Self-hosted | GPU |
|--------|----|----|---------|------------|-----|
| **Yandex SpeechKit** | 0.6 | 3.48 | Low (cloud) | Enterprise only | N/A |
| **Silero V5** | 0.7 | 2.54–2.98 | **<20ms** | ✅ CPU only | No |
| **edge-tts** | 0.7 | 3.57 | 100–200ms | ❌ Cloud | N/A |
| **Piper (Irina)** | 1.4 | **3.67** | <50ms CPU | ✅ | No |
| **XTTS v2** | 2.7 | 3.04 | <200ms | ✅ | Yes (4–6GB) |
| **Bark** | 10.3 | 2.55 | 1–5s | ✅ | Yes (8–12GB) |

**Silero TTS V5** is the strongest self-hosted option for Russian — it matches edge-tts clarity (CER 0.7), runs on **CPU in under 20ms**, requires zero GPU resources, and integrates with one line of Python via PyTorch Hub. It provides 6 Russian speakers with SSML support. The main limitation is limited expressiveness — clear but somewhat flat intonation. License is CC-NC-BY for main models (non-commercial), with MIT-licensed CIS base models available.

**Piper TTS (Irina voice)** achieves the highest UTMOS score (3.67) among all tested open-source Russian models — better than edge-tts — while running on CPU at xRT 0.045. The quality depends heavily on training data; Irina was trained on just 1 hour of high-quality recordings. Four Russian voices are available (Denis, Dmitri, Irina, Ruslan). The limitation is no streaming output and no voice cloning.

**XTTS v2** (maintained by Idiap Research Institute after Coqui's shutdown) adds **zero-shot voice cloning** from a 6-second sample and native streaming support at <200ms latency on GPU. Russian quality (CER 2.7) is acceptable but noticeably worse than Silero or edge-tts. Docker images are available (`ghcr.io/idiap/coqui-tts-cpu`).

**Fish Audio S2 Pro** represents the state of the art — it passed the Audio Turing Test (48.5% correct identification) and supports 80+ languages with Russian as Tier 2. Self-hosted latency is ~100ms on H200 GPU via SGLang. However, it requires heavy GPU resources and a commercial license for production use.

**Kokoro TTS** deserves watching — at only 82M parameters it synthesizes sentences in **40–70ms on GPU** and runs on CPU, with an Apache 2.0 license. Russian support is currently experimental via community training (kokoro-ruslan project), but if quality improves it could become the ideal choice.

**Recommendation:** Replace edge-tts with Silero V5 for an immediate, zero-cost improvement in reliability and latency. If voice quality or cloning matters more, deploy XTTS v2 on GPU. Use the `RealtimeTTS` library by KoljaB to wrap either engine in a unified streaming interface compatible with your pipeline.

---

## Barge-in, echo cancellation, and browser audio require careful engineering

**Barge-in handling** is essential for natural conversation. When VAD detects user speech during assistant playback, the system must immediately: (1) stop TTS synthesis, (2) cancel in-flight LLM generation, (3) discard queued audio, and (4) notify the browser to clear its playback buffer. Add a **500–1,000ms no-interrupt window** after the assistant starts speaking to prevent false triggers from echo or background noise. Pipecat handles this automatically with `PipelineParams(allow_interruptions=True)`.

**Echo cancellation** — preventing the assistant's audio from triggering its own VAD — is handled primarily by the browser's built-in AEC. Enable it via `getUserMedia`:

```javascript
const stream = await navigator.mediaDevices.getUserMedia({
    audio: {
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
        sampleRate: 16000,
        channelCount: 1
    }
});
```

Browser AEC needs **2–5 seconds to adapt** to room acoustics. During this period, echo leaks through. The solution: delay transmitting mic audio briefly after `getUserMedia` to let AEC stabilize. AEC works when TTS audio plays through the same browser tab via Web Audio API, even with WebSocket transport.

**Browser audio capture and playback** should use AudioWorklet exclusively — ScriptProcessorNode is deprecated and runs on the main thread, causing jitter. The capture worklet converts float32 samples to PCM16 and posts them as binary ArrayBuffers to the main thread, which sends them as **binary WebSocket frames** (33% less bandwidth than base64). The playback worklet uses a **pre-allocated ring buffer** — never allocate memory inside `process()` as garbage collection causes audible glitches. Support a `clearBuffer` command for barge-in:

```javascript
// In playback AudioWorklet processor
this.port.onmessage = (event) => {
    if (event.data.command === 'clearBuffer') {
        this.readIndex = this.writeIndex;  // Instant clear for barge-in
        return;
    }
    // Write incoming PCM samples to ring buffer...
};
```

**WebRTC vs WebSocket:** Your WebSocket setup is viable for prototyping and single-user scenarios. WebRTC adds ~50ms lower latency via UDP transport, eliminates TCP head-of-line blocking, and provides built-in AEC/AGC/noise suppression. LiveKit's argument: "TCP head-of-line blocking is devastating for audio — if a packet is lost, TCP pauses the entire stream." When ready for production, migrate to WebRTC via LiveKit Server or Pipecat's SmallWebRTCTransport, both fully self-hostable.

---

## Practical Docker architecture for your optimized pipeline

A production-ready Docker Compose setup separates concerns while keeping all components self-hosted:

```yaml
version: "3.8"
services:
  voice-server:
    build: ./server
    ports: ["8000:8000"]
    environment:
      - MWS_API_KEY=${MWS_API_KEY}
      - MWS_BASE_URL=https://your-mws-endpoint.mws.ru/v1
      - REDIS_URL=redis://redis:6379
    depends_on: [redis]
    deploy:
      resources:
        reservations:
          devices:
            - capabilities: [gpu]

  redis:
    image: redis:7-alpine
    ports: ["6379:6379"]
    volumes: [redis_data:/data]

volumes:
  redis_data:
```

The voice server loads faster-whisper (large-v3-turbo) and Silero TTS directly — no need for separate STT/TTS services if running on a single GPU server. Use Redis for session state to keep the compute layer stateless. Each WebSocket connection gets its own pipeline instance with `asyncio.Queue` between stages for backpressure control.

For **conversation state management**, maintain a structured JSON state alongside the message history. Trim context by summarizing older messages when approaching the LLM's context window. A typical minute of transcribed speech produces ~150 tokens — a 30-minute conversation generates ~4,500 tokens. Use a sliding window with summary buffer: keep the last 20 messages raw, summarize earlier ones into 1–3 sentences of key facts.

---

## Conclusion

The fastest path to a dramatically improved voice assistant starts with three changes that require no architectural overhaul: swap energy-based VAD for **Silero VAD** (accuracy improvement from "worse than random" to excellent, ~1ms overhead), switch to **large-v3-turbo with beam_size=1** (3–6x faster STT with minimal quality loss for Russian), and implement **sentence-level chunked TTS** to overlap LLM generation and synthesis. These changes alone should reduce end-to-end latency from 1.5–3 seconds to **600–900ms**.

The next level of improvement comes from replacing edge-tts with **Silero TTS** (eliminating network latency to Azure, gaining <20ms local synthesis) and adopting **Pipecat** as the pipeline orchestration framework (gaining automatic barge-in handling, streaming at every stage, and trivial MWS GPT integration via `base_url`). This combination targets **400–600ms** end-to-end latency with fully self-hosted infrastructure.

Speech-to-speech models like Qwen3-Omni represent the future — they deliver 160–500ms latency by eliminating the STT intermediary — but they cannot integrate with custom LLM APIs today. The traditional pipeline remains necessary for MWS GPT compatibility. The most interesting emerging option is **Ultravox**, which could serve as a faster STT replacement (audio → LLM embeddings directly) if trained on a compatible backbone, while still allowing separate TTS. Watch this space as the gap between S2S and pipeline approaches continues to narrow.