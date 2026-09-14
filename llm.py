# -*- coding: utf-8 -*-
"""共享的大模型客户端与密钥：全项目只在这里建一次 client。
两个通道，靠 .env 里的 MODEL_PROVIDER 切换（cloud=阿里云百炼 / local=本机模型）：
两个 client 的属性路径和返回对象完全一样，所以上层 bot.py / 21 个工具一行都不用改。"""
import os
from dotenv import load_dotenv
from openai import OpenAI
from config import MODEL_PROVIDER
load_dotenv()
api_key = os.getenv("DASHSCOPE_API_KEY")
tavily_key = os.getenv("TAVILY_API_KEY")
# 唱歌走北京地域专用 key（Fun-Music 只认华北2的 key），没配则退回聊天 key
bjs_key = os.getenv("BJS_API_KEY") or api_key
workspace_id = "ws-jyr680etwmdpmwjy"
if not api_key:
    print("警告：.env 里没有配置 DASHSCOPE_API_KEY，所有接口调用都会失败")
if MODEL_PROVIDER == "local":
    from local_llm import LocalClient
    client = LocalClient()
    print("模型通道：本地模型（%s）" % os.path.basename(os.environ.get(
        "LOCAL_MODEL_PATH", "qwen2.5-3b-instruct-q4_k_m.gguf")))
else:
    client = OpenAI(
        api_key=api_key or "missing-key",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"
    )