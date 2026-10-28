# -*- coding: utf-8 -*-
"""用假事件 + 假 client 测试飞书 handler 全链路（不连飞书）"""
import sys, os, time, types
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".pkgs"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
os.environ["HUAJUAN_DATA_DIR"] = r"D:\python\_fsdata"

import feishu_bot as fb
import bot

sent = []

class FakeResponse:
    def success(self):
        return True

class FakeMessageAPI:
    def create(self, req):
        sent.append(req)
        return FakeResponse()

class FakeIM:
    def __init__(self):
        self.v1 = types.SimpleNamespace(message=FakeMessageAPI())

class FakeClient:
    def __init__(self):
        self.im = FakeIM()

fb.client = FakeClient()

# 假事件：群聊 @ 机器人
msg = types.SimpleNamespace(
    message_id="om_test_001", chat_id="oc_test_001", message_type="text",
    content='{"text": "@_user_1 你好呀"}', chat_type="group",
)
sender = types.SimpleNamespace(sender_id=types.SimpleNamespace(open_id="ou_test_abc"))
event = types.SimpleNamespace(message=msg, sender=sender)
data = types.SimpleNamespace(event=event)

fb.on_message(data)
time.sleep(8)  # 等后台线程调花卷

print("发送条数:", len(sent))
for req in sent:
    print("  content:", str(req.body.content)[:120])

# 重推同一 message_id → 应被去重
before = len(sent)
fb.on_message(data)
time.sleep(1)
print("重复消息后发送条数(应不变):", len(sent), "之前:", before)
