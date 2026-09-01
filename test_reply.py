# -*- coding: utf-8 -*-
# 第②步接入验收：get_reply 走流式+工具循环，测纯聊天和调工具两条链路
import bot

print("== 测试1：现在几点（走工具循环）==")
print("花卷：", bot.get_reply("现在几点"))

print("\n== 测试2：你好（纯聊天单圈）==")
print("花卷：", bot.get_reply("你好"))
