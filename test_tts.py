# -*- coding: utf-8 -*-
"""测试 TTS：把一句话变成音频

注意：本账号（DASHSCOPE_API_KEY）下可用的语音模型是 qwen-tts，
cosyvoice-v2 会报 "url error, please check url"（模型不被识别）。
接口：DashScope 原生多模态生成接口（compatible-mode 没有 /audio/speech）。
"""
import os
import json
import urllib.request
import urllib.error
from dotenv import load_dotenv

load_dotenv()
KEY = os.getenv("DASHSCOPE_API_KEY")
if not KEY:
    print("请先在 .env 里配置 DASHSCOPE_API_KEY")
    exit(1)

# 原生 TTS 接口（同步返回）
URL = "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation"
headers = {
    "Authorization": "Bearer " + KEY,
    "Content-Type": "application/json",
}
body = {
    "model": "qwen-tts",
    "input": {"text": "刚灌完半瓶冰可乐，透心凉。你想聊啥都行，我听着。"},
    "voice": "longxiaochun_v2",
    "parameters": {"format": "wav", "sample_rate": 32000},
}


def post_json(url, data, hdrs):
    req = urllib.request.Request(url, data=json.dumps(data).encode("utf-8"), headers=hdrs)
    with urllib.request.urlopen(req) as r:
        return json.load(r)


try:
    resp = post_json(URL, body, headers)
except urllib.error.HTTPError as e:
    # 关键：把错误响应体打出来，不然 400/404 都看不到原因
    print(f"HTTP {e.code} 错误，响应体：")
    print(e.read().decode("utf-8", errors="replace"))
    exit(1)
except Exception as e:
    print(f"请求失败：{e}")
    exit(1)

output = resp.get("output", {})
audio = output.get("audio", {})
url = audio.get("url") if isinstance(audio, dict) else None
if url:
    urllib.request.urlretrieve(url, "test_voice.wav")
    print(f"生成完毕：test_voice.wav（{audio.get('expires_at')} 前有效）")
elif isinstance(audio, dict) and audio.get("data"):
    with open("test_voice.wav", "wb") as f:
        f.write(audio["data"])
    print("生成完毕：test_voice.wav（base64）")
else:
    print("未识别的返回格式：", json.dumps(resp, ensure_ascii=False, indent=2))

