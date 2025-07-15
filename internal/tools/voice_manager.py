import speech_recognition as sr

# 語音輸入功能測試
class VoiceManager:
    def __init__(self):
        self.recognizer = sr.Recognizer()
        self.recognizer.pause_threshold = 2  # 語音靜音閾值，調整此值以適應環境噪音

    def recognize_speech(self):
        with sr.Microphone() as source:
            print("請開始說話:")
            self.recognizer.adjust_for_ambient_noise(source)
            audio = self.recognizer.listen(source)
        try:
            text = self.recognizer.recognize_google(audio, language="zh-TW")
        except sr.UnknownValueError:
            text = "無法翻譯"
        except sr.RequestError as e:
            text = f"無法翻譯: {e}"
        return text
