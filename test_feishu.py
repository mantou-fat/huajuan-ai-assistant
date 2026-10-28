# -*- coding: utf-8 -*-
"""验证飞书接入的本地链路（不连飞书，只验证解析/去重/花卷调用）"""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".pkgs"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import feishu_bot as fb
from sessions import set_sid
import bot

print("1) strip_mention:", repr(fb.strip_mention("@_user_1 你好呀")))
print("2) dedupe 第一次:", fb.dedupe("m1"))
print("3) dedupe 第二次:", fb.dedupe("m1"))

t0 = time.time()
set_sid("feishu:test")
reply = bot.get_reply("你好，简单介绍一下你自己")
print("4) 花卷回复(%.1fs):" % (time.time() - t0), reply[:200])
