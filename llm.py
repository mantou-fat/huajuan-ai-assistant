# -*- coding: utf-8 -*-
"""共享的大模型客户端与密钥：全项目只在这里建一次 client。"""
import os
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()
api_key = os.getenv("DASHSCOPE_API_KEY")
tavily_key = os.getenv("TAVILY_API_KEY")
# 唱歌走北京地域专用 key（Fun-Music 只认华北2的 key），没配则退回聊天 key
bjs_key = os.getenv("BJS_API_KEY") or api_key
workspace_id = "ws-jyr680etwmdpmwjy"
if not api_key:
    print("警告：.env 里没有配置 DASHSCOPE_API_KEY，所有接口调用都会失败")
client = OpenAI(
    api_key=api_key or "missing-key",
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"
)