"""
Voice Activity Detection (VAD)
==============================
Energy-based VAD for detecting speech start/end in audio streams.
Uses RMS energy levels with configurable thresholds and silence duration.
"""

import time
import numpy as np


class EnergyVAD:
    """
    Simple energy-based Voice Activity Detection.
    
    Detects speech by monitoring RMS energy levels:
    - Speech starts when energy exceeds SPEECH_THRESHOLD
    - Speech ends after SILENCE_DURATION_MS of silence (energy below SILENCE_THRESHOLD)
    - Minimum speech duration prevents false positives from noise bursts
    """

    def __init__(
        self,
        speech_threshold: float = 0.015,
        silence_threshold: float = 0.008,
        silence_duration_ms: int = 1500,
        min_speech_duration_ms: int = 300,
    ):
        self.speech_threshold = speech_threshold
        self.silence_threshold = silence_threshold
        self.silence_duration_ms = silence_duration_ms
        self.min_speech_duration_ms = min_speech_duration_ms

        self._is_speaking = False
        self._speech_start_time: float | None = None
        self._last_sound_time: float | None = None
        self._speech_ended = False

    def process_chunk(self, audio_int16: bytes) -> dict:
        """
        Process an audio chunk (Int16 PCM bytes) and return VAD state.
        
        Returns:
            dict with keys:
                - rms: float — current RMS energy level (0.0 - 1.0)
                - is_speaking: bool — whether speech is currently detected
                - speech_ended: bool — True once when speech-to-silence transition detected
        """
        # Convert Int16 PCM to float32 normalized
        audio = np.frombuffer(audio_int16, dtype=np.int16).astype(np.float32) / 32768.0

        # Calculate RMS energy
        rms = float(np.sqrt(np.mean(audio ** 2)))

        now = time.monotonic()
        self._speech_ended = False

        speech_started = False

        if rms > self.speech_threshold:
            # Sound detected
            if not self._is_speaking:
                self._is_speaking = True
                self._speech_start_time = now
                speech_started = True  # Signal: user just started speaking
            self._last_sound_time = now

        elif self._is_speaking and rms < self.silence_threshold:
            # Check if silence has lasted long enough
            if self._last_sound_time is not None:
                silence_ms = (now - self._last_sound_time) * 1000
                speech_ms = (now - (self._speech_start_time or now)) * 1000

                if silence_ms >= self.silence_duration_ms and speech_ms >= self.min_speech_duration_ms:
                    self._speech_ended = True
                    self._is_speaking = False
                    self._speech_start_time = None
                    self._last_sound_time = None

        return {
            "rms": rms,
            "is_speaking": self._is_speaking,
            "speech_started": speech_started,
            "speech_ended": self._speech_ended,
        }

    def reset(self):
        """Reset VAD state for a new utterance."""
        self._is_speaking = False
        self._speech_start_time = None
        self._last_sound_time = None
        self._speech_ended = False

    @property
    def is_speaking(self) -> bool:
        return self._is_speaking
