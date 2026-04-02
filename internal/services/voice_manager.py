import numpy as np
import speech_recognition as sr
import whisper
import types
from typing import cast


class VoiceManager:
    def __init__(self, pause_threshold: int = 2, model_size: str = "base") -> None:
        self.recognizer: sr.Recognizer = sr.Recognizer()
        self.recognizer.pause_threshold = pause_threshold  # 語音靜音閾值
        print(f"正在載入 Whisper 模型 ({model_size})...")
        self.model = whisper.load_model(model_size)

    def recognize_speech(self) -> str | None:
        with sr.Microphone() as source:
            print("請開始說話:")
            self.recognizer.adjust_for_ambient_noise(source)
            audio = self.recognizer.listen(source)

        try:
            # 將語音數據轉換為 Whisper 可讀取的格式 (16kHz, float32 numpy array)
            audio_data = audio
            if isinstance(audio, types.GeneratorType):
                try:
                    audio_data = next(audio)
                except StopIteration:
                    print("沒有收到音訊資料")
                    return None
            if not hasattr(audio_data, "get_raw_data"):
                print("收到的音訊物件不支援 'get_raw_data'")
                return None

            # help static type checkers by casting to sr.AudioData
            audio_data = cast(sr.AudioData, audio_data)

            raw_data = audio_data.get_raw_data(convert_rate=16000, convert_width=2)
            audio_np = (
                np.frombuffer(raw_data, dtype=np.int16).astype(np.float32) / 32768.0
            )

            # 使用 Whisper 進行辨識
            result = self.model.transcribe(audio_np, fp16=False)
            text_field = result.get("text")
            if isinstance(text_field, list):
                # join list elements into a single string
                text = " ".join(str(t) for t in text_field).strip()
            else:
                text = str(text_field).strip() if text_field is not None else ""
            return text if text != "" else None
        except Exception as e:
            print(f"Whisper 識別出錯: {e}")
            return None
