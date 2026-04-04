import threading
import types
from typing import Callable, cast

import numpy as np
import speech_recognition as sr
import whisper


class VoiceManager:
    def __init__(self, pause_threshold: int = 2, model_size: str = "base") -> None:
        self.recognizer: sr.Recognizer = sr.Recognizer()
        self.recognizer.pause_threshold = pause_threshold
        print(f"正在載入 Whisper 模型 ({model_size})...")
        self.model = whisper.load_model(model_size)
        self._cancel_flag = threading.Event()
        self._audio_ready = threading.Event()
        self._bg_stop_fn = None
        self._bg_audio = None

    # ── Async / cancellable interface ──────────────────────────────────────

    def start_listening(
        self,
        on_result: Callable[[str | None], None],
        on_level: Callable[[float], None] | None = None,
    ) -> None:
        """Start background listening. on_result called with transcribed text (or None).
        on_level(0.0‒1.0) called periodically with mic amplitude (for waveform UI).
        Call cancel() to abort early."""
        self._cancel_flag.clear()
        self._audio_ready.clear()
        self._bg_audio = None

        def _audio_callback(recognizer, audio):
            self._bg_audio = audio
            self._audio_ready.set()

        try:
            self._bg_stop_fn = self.recognizer.listen_in_background(
                sr.Microphone(), _audio_callback, phrase_time_limit=30
            )
        except Exception as e:
            print(f"Microphone init failed: {e}")
            on_result(None)
            return

        def _worker():
            # Poll level while waiting for audio
            import time
            while not self._audio_ready.is_set() and not self._cancel_flag.is_set():
                if on_level:
                    try:
                        level = self._sample_mic_level()
                        on_level(level)
                    except Exception:
                        pass
                time.sleep(0.08)

            # Stop background listener
            if self._bg_stop_fn:
                try:
                    self._bg_stop_fn(wait_for_stop=False)
                except Exception:
                    pass
                self._bg_stop_fn = None

            if self._cancel_flag.is_set() or self._bg_audio is None:
                on_result(None)
                return

            on_result(self._transcribe(self._bg_audio))

        threading.Thread(target=_worker, daemon=True).start()

    def submit_now(self) -> None:
        """Signal that the user wants to submit immediately — stops capturing."""
        self._audio_ready.set()

    def cancel(self) -> None:
        """Abort in-progress recognition without transcribing."""
        self._cancel_flag.set()
        self._audio_ready.set()
        if self._bg_stop_fn:
            try:
                self._bg_stop_fn(wait_for_stop=False)
            except Exception:
                pass
            self._bg_stop_fn = None

    # ── Internal helpers ───────────────────────────────────────────────────

    def _sample_mic_level(self) -> float:
        """Return a rough 0..1 RMS level from a tiny mic burst (non-blocking approx)."""
        try:
            with sr.Microphone() as src:
                raw = src.stream.read(1024)
            samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32)
            rms = float(np.sqrt(np.mean(samples ** 2))) / 32768.0
            return min(1.0, rms * 8)
        except Exception:
            return 0.1

    def _transcribe(self, audio) -> str | None:
        try:
            audio_data = audio
            if isinstance(audio, types.GeneratorType):
                try:
                    audio_data = next(audio)
                except StopIteration:
                    return None
            if not hasattr(audio_data, "get_raw_data"):
                return None
            audio_data = cast(sr.AudioData, audio_data)
            raw_data = audio_data.get_raw_data(convert_rate=16000, convert_width=2)
            audio_np = (
                np.frombuffer(raw_data, dtype=np.int16).astype(np.float32) / 32768.0
            )
            result = self.model.transcribe(audio_np, fp16=False)
            text_field = result.get("text")
            if isinstance(text_field, list):
                text = " ".join(str(t) for t in text_field).strip()
            else:
                text = str(text_field).strip() if text_field is not None else ""
            return text if text else None
        except Exception as e:
            print(f"Whisper 識別出錯: {e}")
            return None

    # ── Legacy synchronous interface (kept for CLI mode) ───────────────────

    def recognize_speech(self) -> str | None:
        with sr.Microphone() as source:
            print("請開始說話:")
            self.recognizer.adjust_for_ambient_noise(source)
            audio = self.recognizer.listen(source)
        return self._transcribe(audio)
