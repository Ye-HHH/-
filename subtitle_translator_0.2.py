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

import nltk
from nltk.tokenize import sent_tokenize

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
            text = payload.get("result", "").strip()

            if not hasattr(self, "current_buffer"):
                self.current_buffer = ""

            # 拼接识别文本
            self.current_buffer += " " + text
            self.current_buffer = self.current_buffer.strip()

            # 使用 nltk 自动断句
            sentences = sent_tokenize(self.current_buffer)

            if len(sentences) >= 2:
                # ✅ 正常断句，处理前 N-1 句
                for s in sentences[:-1]:
                    SUBTITLE_QUEUE.put({
                        "text": f"原文: {s.strip()}",
                        "audio": "green",
                        "whisper": "green",
                        "translate": "red",
                        "need_translate": True
                    })
                self.current_buffer = sentences[-1].strip()

            elif len(sentences) == 1:
                # ✅ 如果只有一句，但太长，也强制断句
                if len(sentences[0]) >= 45:
                    sentence = self.current_buffer
                    self.current_buffer = ""

                    SUBTITLE_QUEUE.put({
                        "text": f"原文: {sentence}",
                        "audio": "green",
                        "whisper": "green",
                        "translate": "red",
                        "need_translate": True
                    })

            # ✅ 实时显示还没断完的部分
            if self.current_buffer:
                SUBTITLE_QUEUE.put({
                    "text": f"原文: {self.current_buffer}",
                    "audio": "green",
                    "whisper": "green",
                    "translate": "red",
                    "need_translate": False
                })

        except Exception as e:
            print("字幕断句失败:", e)

    def on_completed(self, message, *args):
        print("识别完成:", message)

    def on_error(self, message, *args):
        print("识别错误:", message)

    def on_close(self, *args):
        print("识别连接关闭")

API_KEY = ""
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
        root.attributes("-alpha", 0.92)
        root.configure(bg="black")
        screen_width = root.winfo_screenwidth()
        screen_height = root.winfo_screenheight()
        root.geometry(f"900x280+{(screen_width - 900) // 2}+{screen_height - 350}")

        # 状态灯区域
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

        # 历史字幕区（可滚动）
        history_frame = tk.Frame(root, bg="black")
        history_frame.pack(fill="both", expand=True, padx=10)

        scrollbar = tk.Scrollbar(history_frame)
        scrollbar.pack(side="right", fill="y")

        history_text = tk.Text(history_frame, wrap="word", yscrollcommand=scrollbar.set,
                               font=("Microsoft YaHei", 13), bg="black", fg="white", height=6)
        history_text.pack(side="left", fill="both", expand=True)
        history_text.config(state="disabled")
        scrollbar.config(command=history_text.yview)

        # 实时字幕区（固定两行：原文+译文）
        current_label = tk.Label(root, text="原文：", font=("Microsoft YaHei", 16),
                                 fg="#00ffcc", bg="black", anchor="w", wraplength=860, justify="left")
        current_label.pack(fill="x", padx=10)

        translate_label = tk.Label(root, text="译文：", font=("Microsoft YaHei", 16),
                                   fg="#ffff66", bg="black", anchor="w", wraplength=860, justify="left")
        translate_label.pack(fill="x", padx=10, pady=(0, 10))

        # 实时更新逻辑
        last_text = ""

        def update():
            nonlocal last_text
            try:
                while True:
                    item = SUBTITLE_QUEUE.get_nowait()
                    if isinstance(item, dict):
                        current_text = item.get("text", "")
                        audio_light.itemconfig("light_audio", fill=item.get("audio", "red"))
                        whisper_light.itemconfig("light_whisper", fill=item.get("whisper", "red"))
                        translate_light.itemconfig("light_translate", fill=item.get("translate", "red"))

                        if "原文:" in current_text:
                            parts = current_text.split("原文:")[1].split("\n翻译:")
                            original = parts[0].strip()
                            translated = parts[1].strip() if len(parts) > 1 else ""

                            # 更新底部实时字幕
                            current_label.config(text=f"原文：{original}")
                            translate_label.config(text=f"译文：{translated}")

                            # 判断是否是新句子，追加到历史
                            if translated and current_text != last_text:
                                last_text = current_text
                                history_text.config(state="normal")
                                history_text.insert("end", f"原文：{original}\n", "origin")
                                history_text.insert("end", f"译文：{translated}\n\n", "trans")
                                history_text.see("end")
                                history_text.config(state="disabled")
                                history_text.tag_config("origin", foreground="#ccccff")
                                history_text.tag_config("trans", foreground="#ffff99")
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

def translate(text, max_retries=3):
    url = "https://api.siliconflow.cn/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "Qwen/Qwen3-14B",
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
        "temperature": 0.7,
        "top_p": 0.7,
        "top_k": 50,
        "frequency_penalty": 0.5,
        "n": 1,
        "response_format": {"type": "text"},
        "tools": []
    }

    for attempt in range(max_retries):
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=10)
            if response.status_code == 200:
                return response.json()["choices"][0]["message"]["content"]
            else:
                logging.warning(f"翻译请求失败：{response.status_code} {response.text}")
        except requests.exceptions.RequestException as e:
            logging.error(f"[翻译重试] 第 {attempt+1} 次失败：{e}")
            time.sleep(1)

    # 若翻译失败则返回错误信息
    return "[翻译失败]"


def wrap_text(text, max_length=20):
    # 用于自动换行的函数
    wrapped_text = ""
    while len(text) > max_length:
        wrapped_text += text[:max_length] + "\n"
        text = text[max_length:]
    wrapped_text += text  # 最后一段不换行
    return wrapped_text


def main_loop():
    last_text = ""
    while True:
        item = SUBTITLE_QUEUE.get()
        text = item.get("text", "")

        if item.get("need_translate"):
            # 处理原文文本
            pure = text.split("原文:")[1].strip().split("\n")[0]
            if pure.strip() and pure != last_text:
                last_text = pure
                translation = translate(pure)

                # 即便翻译失败，也要保留原文
                item["text"] = f"原文: {pure}\n翻译: {translation if translation != '[翻译失败]' else '[翻译失败]'}"
                item["translate"] = "green" if translation.strip() and "失败" not in translation else "red"
                item["need_translate"] = False
                SUBTITLE_QUEUE.put(item)


start_gui()
start_ffmpeg()

print("🎧 正在使用阿里云实时语音识别...")

recognizer = AliyunLiveRecognizer(
    token="",        # ← 替换为你的实时 Token
    appkey=""                        # ← 替换为你的 AppKey
)

recognizer.start_stream()

main_loop()  # 翻译线程，主控字幕
