import tkinter as tk
import threading
import queue
import time
import os
import pyaudio
import dashscope
from dashscope.audio.asr import TranslationRecognizerRealtime, TranslationRecognizerCallback

SUBTITLE_QUEUE = queue.Queue()


def start_minimal_gui():
    selected_device = None
    try:
        root = tk._default_root
        selected_device = root.nametowidget(root.winfo_children()[0].winfo_name()).cget("textvariable")
        if isinstance(selected_device, tk.StringVar):
            selected_device = selected_device.get()
    except Exception as e:
        print("[警告] 无法获取音频源选择，使用默认设备。", e)

    def gui():
        # 初始化 PyAudio 设备列表
        pa = pyaudio.PyAudio()
        raw_device_names = []
        for i in range(pa.get_device_count()):
            info = pa.get_device_info_by_index(i)
            if info.get("maxInputChannels", 0) > 0:
                raw_device_names.append(info["name"])
        device_names = list(dict.fromkeys(raw_device_names))
        pa.terminate()
        root = tk.Tk()
        root.title("BabelStream")
        # 音频源下拉栏
        import json
        config_path = os.path.join(os.path.expanduser("~"), ".babelstream_gui_config.json")

        def load_config():
            if os.path.exists(config_path):
                with open(config_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            return {}

        def save_config(data):
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(data, f)

        config = load_config()
        default_index = 0
        try:
            import sounddevice as sd
            default_input = sd.query_devices(kind='input')['name']
            for i, name in enumerate(device_names):
                if default_input in name:
                    default_index = i
                    break
        except Exception as e:
            print("[提示] 无法获取系统默认设备，使用第一个音频源。", e)
        device_var = tk.StringVar(root, value=config.get("device_name", device_names[default_index]))

        if device_names:
            device_var.set(device_names[default_index])

        def on_device_change(*args):
            selected = device_var.get()
            print(f"[设备切换] 当前选择：{selected}")
            config["device_name"] = selected
            save_config(config)
            start_dashscope_stream(selected)

        device_var.trace_add("write", on_device_change)
        on_device_change()  # 启动时立即应用音频源
        # 底部设置栏容器
        settings_frame = tk.Frame(root, bg="black")
        settings_frame.place(relx=1.0, rely=1.0, anchor="se", x=-10, y=-10)

        # 音频源选择器
        def build_dropdown(label_text, variable, options):
            container = tk.Frame(settings_frame, bg="black")
            btn = tk.Menubutton(container, text=label_text, font=("Microsoft YaHei", 12), fg="white", bg="black",
                                relief="raised")
            menu = tk.Menu(btn, tearoff=0, font=("Microsoft YaHei", 12))

            def update_menu():
                menu.delete(0, 'end')
                for opt in options:
                    menu.add_radiobutton(label=opt, variable=variable, value=opt)

            update_menu()
            variable.trace_add("write", lambda *args: update_menu())
            btn.config(menu=menu, direction="flush")
            btn.pack(side="left")
            container.pack(side="right", padx=10)

        build_dropdown("音频源", device_var, device_names)

        # 字体大小选择器
        import json
        config_path = os.path.join(os.path.expanduser("~"), ".babelstream_gui_config.json")

        def load_config():
            if os.path.exists(config_path):
                with open(config_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            return {}

        def save_config(data):
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(data, f)

        config = load_config()
        font_var = tk.StringVar(value=config.get("font_size", "大号"))
        font_sizes = {
            "小号": (20, 16),
            "中号": (26, 20),
            "大号": (30, 24),
            "特大": (38, 30)
        }

        def on_font_change(*args):
            size = font_var.get()
            ch, en = font_sizes.get(size, (30, 24))
            try:
                translate_label.config(font=("Microsoft YaHei", ch))
                original_label.config(font=("Microsoft YaHei", en))
            except NameError:
                pass

        def save_font(*args):
            config["font_size"] = font_var.get()
            save_config(config)

        font_var.trace_add("write", on_font_change)
        font_var.trace_add("write", save_font)

        build_dropdown("字体大小", font_var, list(font_sizes.keys()))
        root.configure(bg="black")
        root.geometry("1600x200+160+800")
        root.attributes("-topmost", True)
        root.attributes("-alpha", 0.95)
        root.resizable(True, True)

        status_canvas = tk.Canvas(root, width=20, height=20, bg="black", highlightthickness=0, bd=0)
        status_dot = status_canvas.create_oval(4, 4, 16, 16, fill="green")
        status_canvas.place(relx=0.98, rely=0.02, anchor="ne")

        translate_label = tk.Label(root, text="", font=("Microsoft YaHei", 30), fg="white",
                                   bg="black", anchor="center")
        translate_label.pack(pady=(15, 5), fill="x")

        original_label = tk.Label(root, text="", font=("Microsoft YaHei", 24), fg="gray",
                                  bg="black", anchor="center")
        original_label.pack(pady=(0, 5), fill="x")
        on_font_change()  # 启动时立即应用字体大小（标签已创建）

        last_text = ""

        def fit_line_by_width(label, text):
            if not text:
                return ""
            label.update_idletasks()
            max_width = label.winfo_width()
            font = label.cget("font")

            test_label = tk.Label(label.master, font=font)
            result = ""
            for char in text[::-1]:  # 从末尾向前截取
                test_label.config(text=char + result)
                test_label.update_idletasks()
                if test_label.winfo_reqwidth() >= max_width:
                    break
                result = char + result
            test_label.destroy()
            return result.strip()

        def update():
            nonlocal last_text
            try:
                while True:
                    item = SUBTITLE_QUEUE.get_nowait()
                    if isinstance(item, dict):
                        text = item.get("transcription", "").strip()
                        translated = item.get("translation", "").strip()

                        # 伪分段显示（仅显示最后一段）
                        if text:
                            shown_text = fit_line_by_width(original_label, text)
                            if shown_text and text.endswith(shown_text):
                                original_label.config(text=shown_text)
                            else:
                                original_label.config(text=shown_text)
                            last_text = text

                        if translated:
                            shown_trans = fit_line_by_width(translate_label, translated)
                            if shown_trans and translated.endswith(shown_trans):
                                translate_label.config(text=shown_trans)
                            else:
                                translate_label.config(text=shown_trans)

                        status_canvas.itemconfig(status_dot, fill=item.get("asr", "green"))
            except queue.Empty:
                pass
            root.after(200, update)

        def quit_app(event=None):
            root.destroy()

        root.bind("<Control-q>", quit_app)
        update()
        root.protocol("WM_DELETE_WINDOW", lambda: os._exit(0))
        root.mainloop()

    threading.Thread(target=gui, daemon=True).start()


dashscope.api_key = os.getenv("DASHSCOPE_API_KEY", "<your-api-key>")


class GuiSubtitleCallback(TranslationRecognizerCallback):
    def on_open(self):
        print("[DashScope] 连接已打开")

    def on_event(self, request_id, transcription_result, translation_result, usage):
        text = transcription_result.text if transcription_result else ""
        trans = ""
        if translation_result:
            tr = translation_result.get_translation("zh")
            trans = tr.text if tr else ""

        if text.strip():
            SUBTITLE_QUEUE.put({
                "transcription": text,
                "translation": trans,
                "asr": "green",
                "trans": "green" if trans else "red"
            })

    def on_error(self, err):
        print("[DashScope] 出错:", err)

    def on_close(self):
        print("[DashScope] 连接已关闭")


recognizer_instance = None
stream_instance = None
pa_instance = None


def start_dashscope_stream(device_name=None):
    global recognizer_instance, stream_instance, pa_instance

    # 清理旧识别器和音频流
    if recognizer_instance:
        try:
            recognizer_instance.stop()
        except:
            pass
        recognizer_instance = None
    if stream_instance:
        try:
            stream_instance.stop_stream()
            stream_instance.close()
        except:
            pass
        stream_instance = None
    if pa_instance:
        try:
            pa_instance.terminate()
        except:
            pass
        pa_instance = None

    recognizer = TranslationRecognizerRealtime(
        model="gummy-realtime-v1",
        format="pcm",
        sample_rate=16000,
        transcription_enabled=True,
        translation_enabled=True,
        translation_target_languages=["zh"],
        callback=GuiSubtitleCallback()
    )
    recognizer.start()
    recognizer_instance = recognizer

    pa = pyaudio.PyAudio()
    pa_instance = pa
    device_index = None
    if device_name:
        for i in range(pa.get_device_count()):
            info = pa.get_device_info_by_index(i)
            if device_name in info["name"]:
                device_index = i
                break

    stream = pa.open(format=pyaudio.paInt16, channels=1, rate=16000,
                     input=True, frames_per_buffer=3200,
                     input_device_index=device_index)
    stream_instance = stream

    def feed():
        try:
            while True:
                data = stream.read(3200, exception_on_overflow=False)
                recognizer.send_audio_frame(data)
                time.sleep(0.01)
        except Exception as e:
            print("[DashScope] 音频读取异常：", e)

    threading.Thread(target=feed, daemon=True).start()


if __name__ == '__main__':
    start_minimal_gui()
    # 初始启动时使用默认设备
    # 初始启动由 GUI 完成
    pass
    print("[系统] 实时识别中，关闭窗口或 Ctrl+C 停止。")
    while True:
        time.sleep(1)
