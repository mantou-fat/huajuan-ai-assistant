# 临时测试脚本 v2：绕过DNS解析直接连IP，验证唱歌代码本身是否正确，测完即删
import os
import socket
import requests
from dotenv import load_dotenv

# 给域名手动指路（等价 curl --resolve）：系统解析不了这个域名，我们直接把域名指向真实IP
_orig_getaddrinfo = socket.getaddrinfo
def _patched_getaddrinfo(host, *args, **kwargs):
    if host == "ws-jyr680etwmdpmwjy.cn-beijing.maas.aliyuncs.com":
        host = "47.94.20.201"
    return _orig_getaddrinfo(host, *args, **kwargs)
socket.getaddrinfo = _patched_getaddrinfo

load_dotenv()
api_key = os.getenv("BJS_API_KEY") or os.getenv("DASHSCOPE_API_KEY")
workspace_id = "ws-jyr680etwmdpmwjy"

url = "https://" + workspace_id + ".cn-beijing.maas.aliyuncs.com/api/v1/services/audio/music/generation"
payload = {
    "model": "fun-music-v1",
    "input": {
        "lyrics": "[verse]小小花卷转呀转\n[chorus]馒头馒头我们去远方",
        "gender": "female",
    },
}
print("请求地址:", url)
r = requests.post(url, headers={"Authorization": "Bearer " + api_key}, json=payload, timeout=180)
print("状态码:", r.status_code)
print("响应:", r.text[:600])
