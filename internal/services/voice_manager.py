import speech_recognition as sr
from typing import Any, Generator
from speech_recognition import AudioData
import tempfile
import os
import time
import audioop

import pyaudio
import wave

import librosa
import numpy as np
import torch
from transformers import WhisperProcessor, WhisperForConditionalGeneration, AutomaticSpeechRecognitionPipeline

# 語音輸入功能測試


class VoiceManager:
    def __init__(self) -> None:
        self.chunk = 1024                     # 記錄聲音的樣本區塊大小
        self.sample_format = pyaudio.paInt16  # 樣本格式，可使用 paFloat32、paInt32、paInt24、paInt16、paInt8、paUInt8、paCustomFormat
        self.channels = 2                     # 聲道數量
        self.fs = 44100                       # 取樣頻率，常見值為 44100 ( CD )、48000 ( DVD )、22050、24000、12000 和 11025。
        
        # 語音活動檢測參數
        self.silence_threshold = 500          # 靜音門檻值（可調整）
        self.silence_duration = 5.0           # 靜音持續時間（秒）
        self.min_recording_time = 1.0         # 最小錄音時間（秒）
        self.max_recording_time = 30.0        # 最大錄音時間（秒）

        self.p = pyaudio.PyAudio()            # 建立 pyaudio 物件

    def is_silent(self, data) -> bool:
        """檢測音訊片段是否為靜音"""
        # 計算音量（RMS）
        rms = audioop.rms(data, 2)  # 2 是樣本寬度（16位 = 2字節）
        return rms < self.silence_threshold

    def record_audio_with_vad(self) -> str:
        """使用語音活動檢測的錄音功能"""
        # 創建臨時檔案
        temp_fd, temp_filename = tempfile.mkstemp(suffix='.wav')
        os.close(temp_fd)
        
        stream = self.p.open(format=self.sample_format,
                             channels=self.channels,
                             rate=self.fs,
                             frames_per_buffer=self.chunk,
                             input=True)

        print("開始錄音... 請說話")
        frames = []
        start_time = time.time()
        last_sound_time = start_time
        recording_started = False
        
        try:
            while True:
                data = stream.read(self.chunk)
                frames.append(data)
                
                current_time = time.time()
                elapsed_time = current_time - start_time
                
                # 檢測是否有聲音
                if not self.is_silent(data):
                    last_sound_time = current_time
                    if not recording_started:
                        recording_started = True
                        print("偵測到語音，開始錄音...")
                
                # 檢查停止條件
                silence_time = current_time - last_sound_time
                
                # 如果已經開始錄音且靜音超過設定時間，或超過最大錄音時間
                if ((recording_started and 
                     elapsed_time > self.min_recording_time and 
                     silence_time > self.silence_duration) or 
                    elapsed_time > self.max_recording_time):
                    
                    if silence_time > self.silence_duration:
                        print(f"偵測到 {silence_time:.1f} 秒靜音，結束錄音")
                    else:
                        print("達到最大錄音時間，結束錄音")
                    break
                    
                # 每秒顯示狀態
                if int(elapsed_time) > int(elapsed_time - 0.1):
                    if recording_started:
                        print(f"錄音中... {elapsed_time:.1f}s (靜音: {silence_time:.1f}s)")
                    else:
                        print(f"等待語音... {elapsed_time:.1f}s")
                        
        except KeyboardInterrupt:
            print("\n錄音被中斷")
        finally:
            stream.stop_stream()
            stream.close()

        # 如果沒有錄到任何語音
        if not recording_started:
            print("未偵測到語音")
            return temp_filename

        print("錄音結束，正在儲存...")
        
        # 儲存音訊檔案
        with wave.open(temp_filename, 'wb') as wf:
            wf.setnchannels(self.channels)
            wf.setsampwidth(self.p.get_sample_size(self.sample_format))
            wf.setframerate(self.fs)
            wf.writeframes(b''.join(frames))
            
        return temp_filename

    def record_audio(self) -> str:
        """錄製音訊並儲存為 WAV 檔案，返回臨時檔案路徑"""
        # 使用語音活動檢測版本
        return self.record_audio_with_vad()

    def cleanup_temp_file(self, temp_filename: str) -> None:
        """清理臨時檔案"""
        try:
            if os.path.exists(temp_filename):
                os.remove(temp_filename)
                print(f"已清理臨時檔案: {temp_filename}")
        except Exception as e:
            print(f"清理臨時檔案失敗: {e}")

    def close(self) -> None:
        """手動清理 PyAudio 資源"""
        if hasattr(self, 'p'):
            self.p.terminate()
            print("PyAudio 資源已釋放。")

    def __del__(self) -> None:
        """解構函式，清理 PyAudio 資源"""
        self.close()

    # 支援 context manager
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def speech_recognition(self, audio_path) -> str:
        # 使用 librosa 替代 torchaudio
        waveform, sample_rate = librosa.load(audio_path, sr=None)
        
        # 2. Preprocess
        if len(waveform.shape) > 1:
            waveform = np.mean(waveform, axis=0)
        
        if sample_rate != 16_000:
            waveform = librosa.resample(waveform, orig_sr=sample_rate, target_sr=16_000)
            sample_rate = 16_000
            
        # 3. Load Model
        processor = WhisperProcessor.from_pretrained("MediaTek-Research/Breeze-ASR-25")
        model = WhisperForConditionalGeneration.from_pretrained("MediaTek-Research/Breeze-ASR-25").to("cuda").eval()

        # 4. Build Pipeline
        asr_pipeline = AutomaticSpeechRecognitionPipeline(
            model=model,
            tokenizer=processor.tokenizer,
            feature_extractor=processor.feature_extractor,
            chunk_length_s=0
        )

        # 6. Inference
        output = asr_pipeline(waveform, return_timestamps=True)  
        return output['text']  # 返回識別結果文本
    
    def real_time_speech_recognition(self) -> str:
        recorded_audio = self.record_audio()
        response = self.speech_recognition(recorded_audio)
        self.cleanup_temp_file(recorded_audio)  # 清理臨時檔案
        return response