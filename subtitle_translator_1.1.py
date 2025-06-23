import subprocess
import threading
import queue
import requests
import tempfile
import logging
import tkinter as tk
import json
import time
import webrtcvad

import nls
import json
import time
import threading

class AliyunLiveRecognizer(nls.NlsSpeechTranscriber):
    def __init__(self, token, appkey):
        super().__init__(
            url="wss://nls-gateway-cn-shanghai.aliyuncs.com/ws/v1",
            token=token,
            appkey=appkey,
            on_result_changed=self.on_result_changed,
            on_completed=self.on_completed,
            on_error=self.on_error,
            on_close=self.on_close
        )
        self.running = False
        self.result_map = {}
        self.lock = threading.Lock()
        self.last_index = -1

    def start_stream(self):
        self.result_map = {}
        self.running = True
        threading.Thread(target=self._feed_audio, daemon=True).start()

        self.start(
            aformat='pcm',
            enable_intermediate_result=True,
            enable_punctuation_prediction=True,
            enable_inverse_text_normalization=True
        )

    def _feed_audio(self):
        while self.running:
            try:
                chunk = AUDIO_QUEUE.get()
                for i in range(0, len(chunk), 640):
                    frame = chunk[i:i+640]
                    if len(frame) == 640:
                        self.send_audio(frame)
                        time.sleep(0.01)
            except Exception:
                break

    def stop_stream(self):
        self.running = False
        try:
            self.stop()
        except Exception:
            pass

    def on_result_changed(self, message, *args):
        try:
            msg = json.loads(message)
            payload = msg.get("payload", {})
            index = payload.get("index")
            text = payload.get("result", "")

            with self.lock:
                self.result_map[index] = text
                self.last_index = index

            # 推送到字幕显示（翻译异步做）
            SUBTITLE_QUEUE.put({
                "text": f"原文: {''.join(self.result_map.values())}",
                "audio": "green",
                "whisper": "green",
                "translate": "red"  # 先占位，翻译后替换
            })

        except Exception as e:
            print("实时识别解析失败:", e)

    def on_completed(self, message, *args):
        print("识别完成:", message)

    def on_error(self, message, *args):
        print("识别错误:", message)

    def on_close(self, *args):
        print("识别连接关闭")

API_KEY = "这里填入硅基流动的API"
AUDIO_QUEUE = queue.Queue()
SUBTITLE_QUEUE = queue.Queue()

FRAME_DURATION = 30  # ms
FRAME_SIZE = int(16000 * 2 * FRAME_DURATION / 1000)
SILENCE_LIMIT_FRAMES = int(500 / FRAME_DURATION)

vad = webrtcvad.Vad(2)

class SpeechDetector:
    def __init__(self):
        self.buffer = bytearray()
        self.silence_counter = 0

    def process_frame(self, frame):
        if vad.is_speech(frame, 16000):
            self.buffer.extend(frame)
            self.silence_counter = 0
            return None
        else:
            if self.buffer:
                self.silence_counter += 1
                if self.silence_counter >= SILENCE_LIMIT_FRAMES:
                    result = bytes(self.buffer)
                    self.buffer.clear()
                    return result
        return None

def start_gui():
    def gui():
        root = tk.Tk()
        root.title("实时字幕")
        root.attributes("-topmost", True)
        root.attributes("-alpha", 0.85)
        root.configure(bg="black")
        screen_width = root.winfo_screenwidth()
        screen_height = root.winfo_screenheight()
        root.geometry(f"800x140+{(screen_width - 800) // 2}+{screen_height - 200}")

        status_frame = tk.Frame(root, bg="black")
        status_frame.pack(anchor="nw", padx=10, pady=5)

        audio_light = tk.Canvas(status_frame, width=20, height=20, bg="black", highlightthickness=0)
        audio_light.create_oval(2, 2, 18, 18, fill="red", tags="light_audio")
        audio_light.pack(side="left", padx=5)

        whisper_light = tk.Canvas(status_frame, width=20, height=20, bg="black", highlightthickness=0)
        whisper_light.create_oval(2, 2, 18, 18, fill="red", tags="light_whisper")
        whisper_light.pack(side="left", padx=5)

        translate_light = tk.Canvas(status_frame, width=20, height=20, bg="black", highlightthickness=0)
        translate_light.create_oval(2, 2, 18, 18, fill="red", tags="light_translate")
        translate_light.pack(side="left", padx=5)

        label = tk.Label(root, text="等待识别...", font=("Microsoft YaHei", 18), fg="white", bg="black", wraplength=780)
        label.pack(expand=True, fill="both")

        def update():
            try:
                while True:
                    item = SUBTITLE_QUEUE.get_nowait()
                    if isinstance(item, dict):
                        label.config(text=item.get("text", ""))
                        audio_light.itemconfig("light_audio", fill=item.get("audio", "red"))
                        whisper_light.itemconfig("light_whisper", fill=item.get("whisper", "red"))
                        translate_light.itemconfig("light_translate", fill=item.get("translate", "red"))
            except queue.Empty:
                pass
            root.after(200, update)

        update()
        root.mainloop()

    threading.Thread(target=gui, daemon=True).start()

def start_ffmpeg():
    device_names = [
        'audio=CABLE Output (VB-Audio Virtual Cable)'
    ]
    for device in device_names:
        try:
            command = [
                'ffmpeg',
                '-f', 'dshow',
                '-i', device,
                '-ac', '1',
                '-ar', '16000',
                '-f', 'wav',
                'pipe:1'
            ]
            proc = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)

            def reader():
                while True:
                    header = proc.stdout.read(44)
                    data = proc.stdout.read(FRAME_SIZE * 10)
                    if not data:
                        break
                    AUDIO_QUEUE.put(data)

            threading.Thread(target=reader, daemon=True).start()
            print(f"🎧 使用音频输入设备: {device}")
            return
        except Exception as e:
            logging.warning(f"设备初始化失败: {device} -> {e}")
            continue

    print("❌ 未能成功初始化任何音频设备")

def translate(text):
    try:
        url = "https://api.siliconflow.cn/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": "Qwen/Qwen3-30B-A3B",
            "messages": [
                {
                    "role": "user",
                    "content": f"请将以下文本准确翻译为中文：{text}"
                }
            ],
            "stream": False,
            "max_tokens": 512,
            "enable_thinking": False,
            "thinking_budget": 4096,
            "min_p": 0.05,
            "stop": None,
            "temperature": 0.7,
            "top_p": 0.7,
            "top_k": 50,
            "frequency_penalty": 0.5,
            "n": 1,
            "response_format": {"type": "text"},
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "description": "<string>",
                        "name": "<string>",
                        "parameters": {},
                        "strict": False
                    }
                }
            ]
        }
        response = requests.post(url, headers=headers, json=payload)
        if response.status_code == 200:
            data = response.json()
            return data["choices"][0]["message"]["content"]
    except Exception:
        logging.exception("翻译失败")
    return ""

def main_loop():
    last_text = ""
    while True:
        item = SUBTITLE_QUEUE.get()
        text = item.get("text", "")
        # 提取纯文本（可自行改为正则）
        if "原文:" in text:
            pure = text.split("原文:")[1].split("\n")[0]
            if pure.strip() and pure != last_text:
                last_text = pure
                translation = translate(pure)
                item["text"] = f"原文: {pure}\n翻译: {translation}"
                item["translate"] = "green" if translation.strip() else "red"
                SUBTITLE_QUEUE.put(item)


start_gui()
start_ffmpeg()

print("🎧 正在使用阿里云实时语音识别...")

recognizer = AliyunLiveRecognizer(
    token="填阿里的",        # ← 替换为你的实时 Token
    appkey="填阿里的"                        # ← 替换为你的 AppKey
)

recognizer.start_stream()

main_loop()  # 翻译线程，主控字幕
