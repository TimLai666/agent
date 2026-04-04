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
        The waveform level is animated by the UI itself; on_level is no longer used
        to avoid opening a second audio stream which would crash PortAudio.
        Call cancel() to abort, submit_now() to stop recording and transcribe immediately."""
        self._cancel_flag.clear()
        self._audio_ready.clear()
        self._bg_audio = None

        def _audio_callback(recognizer, audio):
            # Called by speech_recognition when a phrase is detected
            if not self._cancel_flag.is_set():
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
            import time
            # Wait until audio arrives naturally OR user cancels/submits
            while not self._audio_ready.is_set() and not self._cancel_flag.is_set():
                time.sleep(0.05)

            # Stop the background listener before doing anything else
            if self._bg_stop_fn:
                try:
                    self._bg_stop_fn(wait_for_stop=False)
                except Exception:
                    pass
                self._bg_stop_fn = None

            if self._cancel_flag.is_set():
                on_result(None)
                return

            if self._bg_audio is None:
                on_result(None)
                return

            # Transcribe in the same worker thread (Whisper is CPU-bound)
            on_result(self._transcribe(self._bg_audio))

        threading.Thread(target=_worker, daemon=True).start()

    def submit_now(self) -> None:
        """Signal that the user wants to submit immediately — stops capturing."""
        self._audio_ready.set()

    def cancel(self) -> None:
        """Abort in-progress recognition without transcribing."""
        self._cancel_flag.set()
        self._audio_ready.set()  # unblock worker
        if self._bg_stop_fn:
            try:
                self._bg_stop_fn(wait_for_stop=False)
            except Exception:
                pass
            self._bg_stop_fn = None

    # ── Internal helpers ───────────────────────────────────────────────────

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
