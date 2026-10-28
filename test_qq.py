# -*- coding: utf-8 -*-
"""本地测试 QQ 机器人协议层（不连 NapCat）"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import qq_bot as qb

sent = []
qb.send_private = lambda uid, t: sent.append(("private", uid, t))
qb.send_group = lambda gid, t: sent.append(("group", gid, t))
qb.bot.get_reply = lambda t: "花卷收到：" + t

SELF = 10001
# 1) 私聊（消息段格式）
ev1 = {
    "post_type": "message", "message_type": "private", "message_id": 9001,
    "self_id": SELF, "user_id": 12345, "group_id": None,
    "message": [{"type": "text", "data": {"text": "你好呀"}}],
}
qb.handle_message(ev1)
print("私聊发送:", sent[-1])

# 2) 群聊没 @ 机器人 → 不应回复
ev2 = {
    "post_type": "message", "message_type": "group", "message_id": 9002,
    "self_id": SELF, "user_id": 12345, "group_id": 55555,
    "message": [{"type": "text", "data": {"text": "大家好"}}],
}
before = len(sent)
qb.handle_message(ev2)
print("群聊未@，发送条数不变:", len(sent) == before)

# 3) 群聊 @ 机器人 → 回复到群
ev3 = {
    "post_type": "message", "message_type": "group", "message_id": 9003,
    "self_id": SELF, "user_id": 12345, "group_id": 55555,
    "message": [
        {"type": "at", "data": {"qq": str(SELF)}},
        {"type": "text", "data": {"text": " 在吗"}},
    ],
}
qb.handle_message(ev3)
print("群聊@发送:", sent[-1])

# 4) 重复消息 → 去重
before = len(sent)
qb.handle_message(ev3)
print("重复消息被去重:", len(sent) == before)

# 5) 字符串 + CQ 码格式
text, at = qb.extract_text("[CQ:at,qq=%d] 你好" % SELF, SELF)
print("CQ 字符串解析:", repr(text), "at_bot:", at)

# 6) 会话隔离：不同 QQ 号不同 sid
print("sid 隔离:", qb.sid_for("p", 1) != qb.sid_for("p", 2))
