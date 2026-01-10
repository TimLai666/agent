import numpy as np
import speech_recognition as sr
import whisper


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
            raw_data = audio.get_raw_data(convert_rate=16000, convert_width=2)
            audio_np = (
                np.frombuffer(raw_data, dtype=np.int16).astype(np.float32) / 32768.0
            )

            # 使用 Whisper 進行辨識
            result = self.model.transcribe(audio_np, fp16=False)
            text = result["text"].strip()
            return text
        except Exception as e:
            print(f"Whisper 識別出錯: {e}")
            return None
