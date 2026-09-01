# -*- coding: utf-8 -*-
# create_stream 自检：纯聊天应返回 stop+文字；调工具应返回 tool_calls+完整工具单
import bot

print("== 测试1：你好（纯聊天）==")
r1 = bot.create_stream([{"role": "user", "content": "你好"}])
print(r1)

print("\n== 测试2：现在几点（调工具）==")
r2 = bot.create_stream([{"role": "user", "content": "现在几点"}])
print(r2)
