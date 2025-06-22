import nls
import time
import json

class ujykkl(nls.NlsSpeechTranscriber):
    def __init__(self):
        super().__init__(
            url="wss://nls-gateway-cn-shanghai.aliyuncs.com/ws/v1",
            token="",
            appkey="",
            on_result_changed=self.on_result_changed,
            on_completed=self.on_completed,
            on_error=self.on_error,
            on_close=self.on_close,
            callback_args=[1]
        )
        self.results = []

    def on_result_changed(self, message, *args):
        print("识别中:", message)
        try:
            msg = json.loads(message)
            payload = msg["payload"]
            index = payload.get("index")
            result = payload.get("result")

            # 更新或追加当前句子的内容（每个 index 只保留最后一个结果）
            if not hasattr(self, "result_map"):
                self.result_map = {}

            self.result_map[index] = result  # 每个 index 最终覆盖为最后一句

        except Exception as e:
            print("解析识别结果失败:", e, "\n原始内容:", message)

    def on_completed(self, message, *args):
        print("识别完成:", message)

    def on_error(self, message, *args):
        print("发生错误:", message)

    def on_close(self, *args):
        print("连接关闭")

if __name__ == '__main__':
    rs = ujykkl()
    rs.start(
        aformat='pcm',
        enable_intermediate_result=True,
        enable_punctuation_prediction=True,
        enable_inverse_text_normalization=True
    )

    with open("tests/test1.wav", "rb") as f:
        data = f.read()

    data = zip(*(iter(data),) * 640)

    for i in data:
        rs.send_audio(bytes(i))
        time.sleep(0.01)

    rs.ctrl(ex={"test": "tttt"})
    time.sleep(1)
    rs.stop()
    time.sleep(1)

    print("最终识别文本:", ''.join(rs.result_map.values()))