import dashscope
from dashscope.audio.asr import TranslationRecognizerRealtime, TranslationRecognizerCallback
import pyaudio, threading, queue, os, ctypes, wx

# 1. 设置 API Key：推荐通过环境变量
dashscope.api_key = os.getenv("DASHSCOPE_API_KEY", "<your-api-key>")

# 2. 音频输入
pa = pyaudio.PyAudio()
stream = pa.open(format=pyaudio.paInt16, channels=1, rate=16000,
                 input=True, frames_per_buffer=3200)

# 3. 回调处理逻辑：打印识别与翻译文本
class MyCallback(TranslationRecognizerCallback):
    def on_open(self): print("连接已打开")
    def on_event(self, request_id, transcription_result, translation_result, usage):
        if transcription_result:
            print("[ASR] " + transcription_result.text)
        if translation_result:
            tr = translation_result.get_translation("zh")
            print("[TRANSLATION] " + tr.text)
    def on_error(self, err): print("出错:", err)
    def on_complete(self): print("处理完成")
    def on_close(self): print("连接已关闭")

# 4. 初始化并启动识别翻译器
recognizer = TranslationRecognizerRealtime(
    model="gummy-realtime-v1",
    format="pcm",
    sample_rate=16000,
    transcription_enabled=True,
    translation_enabled=True,
    translation_target_languages=["zh"],
    callback=MyCallback()
)
recognizer.start()

# 5. 音频循环推送
def feed_microphone():
    try:
        while True:
            data = stream.read(3200, exception_on_overflow=False)
            recognizer.send_audio_frame(data)
    except Exception:
        pass

threading.Thread(target=feed_microphone, daemon=True).start()

# 6. 示例：简单运行，没有 UI，Ctrl-C 停止
print("开始实时识别翻译，按 Ctrl-C 停止")
try:
    while True:
        pass
except KeyboardInterrupt:
    recognizer.stop()
    stream.stop_stream(); stream.close()
    pa.terminate()
    print("已停止")
