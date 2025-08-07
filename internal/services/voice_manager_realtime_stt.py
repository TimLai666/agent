from RealtimeSTT import AudioToTextRecorder

def process_text(text):
    print(text)

class VoiceManagerRealtimeSTT:
    def __init__(self):
        self.recorder = AudioToTextRecorder()

    def start(self):
        print("Voice Manager Realtime STT started. Speak now...")

    def stop(self):
        print("Voice Manager Realtime STT stopped.")

if __name__ == '__main__':
    print("Wait until it says 'speak now'")
    recorder = AudioToTextRecorder()

    while True:
        recorder.text(process_text)