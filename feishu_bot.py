# -*- coding: utf-8 -*-
"""花卷 · 飞书机器人（长连接模式）

把花卷接入飞书：私聊 / 群里 @ 机器人 即可对话。
- 无需公网 IP：飞书「长连接」模式由飞书主动连本机
- 多用户隔离：每个飞书用户（open_id）对应花卷里的一个独立会话，记忆/历史互不串
- 消息去重：飞书会重推事件，按 message_id 去重

运行前：
1. 飞书开放平台创建「企业自建应用」→ 开启机器人
2. 事件订阅选「长连接」，订阅 im.message.receive_v1
3. 权限：im:message（读取消息）、im:message:send_as_bot（发消息）
4. .env 里填 FEISHU_APP_ID / FEISHU_APP_SECRET
5. python feishu_bot.py
"""
import os
import sys
import json
import re
import time
import hashlib
import threading

BASE = os.path.dirname(os.path.abspath(__file__))
# 本地依赖目录（lark-oapi 装在工作区的 .pkgs 里，避免污染全局环境）
sys.path.insert(0, os.path.join(BASE, ".pkgs"))

from dotenv import load_dotenv

load_dotenv(os.path.join(BASE, ".env"))

import lark_oapi as lark
from lark_oapi.api.im.v1 import (
    CreateMessageRequest,
    CreateMessageRequestBody,
    P2ImMessageReceiveV1,
)
from lark_oapi.ws import Client as WsClient

import bot
from sessions import set_sid

APP_ID = os.getenv("FEISHU_APP_ID", "")
APP_SECRET = os.getenv("FEISHU_APP_SECRET", "")

# 全局 lark 客户端（有凭据时初始化，send_text 会用到）
client = None
if APP_ID and APP_SECRET:
    client = lark.Client.builder().app_id(APP_ID).app_secret(APP_SECRET).build()

MAX_CHUNK = 1500          # 飞书单条文本不宜过长，按段切
_seen = {}                # message_id -> 时间戳（去重）
_seen_lock = threading.Lock()


def dedupe(message_id):
    """飞书在未及时 ack 时会重推事件，这里按 message_id 去重"""
    now = time.time()
    with _seen_lock:
        if message_id in _seen:
            return True
        _seen[message_id] = now
        # 只保留最近 10 分钟的记录
        if len(_seen) > 5000:
            for k in [k for k, t in _seen.items() if now - t > 600]:
                _seen.pop(k, None)
    return False


def strip_mention(text):
    """去掉群聊 @ 留下的占位符，例如 @_user_1"""
    return re.sub(r"@_user_\d+", "", text or "").strip()


def sid_for(open_id):
    """飞书 open_id 映射成花卷的会话 id（只允许字母数字下划线，1-32 位）"""
    return "fs_" + hashlib.md5((open_id or "").encode("utf-8")).hexdigest()[:24]


def send_text(chat_id, text):
    """给会话发文本（长文本自动切段）"""
    text = (text or "").strip()
    if not text:
        text = "（花卷这次没说出话，再试一次？）"
    for i in range(0, len(text), MAX_CHUNK):
        chunk = text[i:i + MAX_CHUNK]
        body = (
            CreateMessageRequestBody.builder()
            .receive_id(chat_id)
            .msg_type("text")
            .content(json.dumps({"text": chunk}, ensure_ascii=False))
            .build()
        )
        req = (
            CreateMessageRequest.builder()
            .receive_id_type("chat_id")
            .request_body(body)
            .build()
        )
        resp = client.im.v1.message.create(req)
        if not resp.success():
            print("[feishu] 发送失败:", resp.code, resp.msg)


def on_message(data: P2ImMessageReceiveV1) -> None:
    """收到飞书消息：去重 → 提取文本 → 交给花卷 → 回复"""
    try:
        event = data.event
        msg = event.message
        if not msg or not msg.message_id:
            return
        if dedupe(msg.message_id):
            return

        if msg.message_type != "text":
            send_text(msg.chat_id, "我先只听得懂文字消息哦～")
            return

        content = json.loads(msg.content or "{}")
        text = strip_mention(content.get("text", ""))
        if not text:
            return

        open_id = event.sender.sender_id.open_id or ""
        sid = sid_for(open_id)

        # 花卷回复可能较慢，放后台线程，避免阻塞飞书事件回调
        def work():
            try:
                set_sid(sid)          # 每个飞书用户独立会话
                reply = bot.get_reply(text)
            except Exception as e:  # noqa: BLE001
                reply = "花卷这边出了点问题：%s" % e
            try:
                send_text(msg.chat_id, reply)
            except Exception as e:  # noqa: BLE001
                print("[feishu] 回复失败:", e)

        threading.Thread(target=work, daemon=True).start()
    except Exception as e:  # noqa: BLE001
        print("[feishu] 事件处理异常:", e)


def main():
    if not APP_ID or not APP_SECRET:
        print("请先在 .env 里配置 FEISHU_APP_ID 和 FEISHU_APP_SECRET")
        return

    handler = (
        lark.EventDispatcherHandler.builder("", "")
        .register_p2_im_message_receive_v1(on_message)
        .build()
    )
    ws = WsClient(APP_ID, APP_SECRET, handler, log_level=lark.LogLevel.INFO)
    print("花卷飞书机器人已启动（长连接）。在飞书里私聊或 @ 它试试～")
    ws.start()


if __name__ == "__main__":
    main()
