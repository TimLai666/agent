import speech_recognition as sr
from typing import Any, Generator
from speech_recognition import AudioData

# 語音輸入功能測試


class VoiceManager:
    def __init__(self, pause_threshold: int = 2) -> None:
        self.recognizer: sr.Recognizer = sr.Recognizer()
        self.recognizer.pause_threshold = pause_threshold  # 語音靜音閾值，靜音超過此時間則認為語音結束

    def recognize_speech(self) -> Any | str:
        with sr.Microphone() as source:
            print("請開始說話:")
            self.recognizer.adjust_for_ambient_noise(source)
            audio: sr.AudioData | Generator[AudioData,
                                            Any, None] = self.recognizer.listen(source)
        text: str | None = None
        try:
            text = self.recognizer.recognize_google(
                audio, language="zh-TW")
        except sr.UnknownValueError:
            text = None
            print("無法識別語音，請再試一次。")
        except sr.RequestError as e:
            text = None
            print(f"語音識別服務出錯: {e}")
        return text
