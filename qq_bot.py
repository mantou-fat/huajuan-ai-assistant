# -*- coding: utf-8 -*-
"""花卷 · QQ 机器人（OneBot 11 / NapCat 适配）

把花卷接到 QQ：私聊机器人，或在群里 @ 它。
- 协议端：NapCat（需要 NTQQ 客户端，扫码登录）
- 通信：NapCat 的 HTTP API + WebSocket 事件（本机回环，无需公网）
- 多用户：按 QQ 号映射会话（群聊按 群+人 隔离），每人独立记忆/历史
- 去重：按 message_id 去重（协议端可能重推）

运行前：
1. 安装 NapCat（https://napcat.napier.uk/），扫码登录一个 QQ 号（建议小号）
2. NapCat 配置里开启 HTTP 服务（默认 3000）和 WebSocket 服务（默认 3001）
3. .env 里配置（可选，默认值即可）：
   NAPCAT_API=http://127.0.0.1:3000
   NAPCAT_WS=ws://127.0.0.1:3001
   NAPCAT_TOKEN=   # 如果 NapCat 配了 token 才需要填
4. python qq_bot.py
"""
import os
import sys
import json
import re
import time
import hashlib
import asyncio
import threading

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

from dotenv import load_dotenv

load_dotenv(os.path.join(BASE, ".env"))

import requests
import websockets

import bot
from sessions import set_sid

NAPCAT_API = os.getenv("NAPCAT_API", "http://127.0.0.1:3000").rstrip("/")
NAPCAT_WS = os.getenv("NAPCAT_WS", "ws://127.0.0.1:3001")
NAPCAT_TOKEN = os.getenv("NAPCAT_TOKEN", "")

MAX_CHUNK = 1500
_seen = {}
_seen_lock = threading.Lock()


def dedupe(message_id):
    now = time.time()
    with _seen_lock:
        if message_id in _seen:
            return True
        _seen[message_id] = now
        if len(_seen) > 5000:
            for k in [k for k, t in _seen.items() if now - t > 600]:
                _seen.pop(k, None)
    return False


def sid_for(scope, uid):
    raw = "%s:%s" % (scope, uid)
    return "qq_" + hashlib.md5(raw.encode("utf-8")).hexdigest()[:24]


def api(path, payload):
    headers = {"Authorization": "Bearer " + NAPCAT_TOKEN} if NAPCAT_TOKEN else {}
    r = requests.post(NAPCAT_API + path, json=payload, headers=headers, timeout=15)
    try:
        data = r.json()
        if data.get("status") not in ("ok", "async"):
            print("[qq] API 返回异常:", path, data, flush=True)
        return data
    except Exception:
        print("[qq] API 解析失败:", r.status_code, r.text[:200], flush=True)
        return {}


def send_private(user_id, text):
    api("/send_private_msg", {"user_id": user_id, "message": text})


def send_group(group_id, text):
    api("/send_group_msg", {"group_id": group_id, "message": text})


def extract_text(message, self_id):
    """从 OneBot 消息里取出文本，并判断是否 @ 了机器人"""
    at_bot = False
    if isinstance(message, str):
        # 字符串格式（含 CQ 码）
        for m in re.finditer(r"\[CQ:at,qq=(\d+)\]", message):
            if m.group(1) == str(self_id):
                at_bot = True
        text = re.sub(r"\[CQ:[^\]]+\]", "", message)
        return text.strip(), at_bot
    if isinstance(message, list):
        texts = []
        for seg in message:
            if not isinstance(seg, dict):
                continue
            t = seg.get("type")
            d = seg.get("data") or {}
            if t == "text":
                texts.append(str(d.get("text", "")))
            elif t == "at":
                if str(d.get("qq")) == str(self_id):
                    at_bot = True
        return "".join(texts).strip(), at_bot
    return "", False


def split_text(text, n=MAX_CHUNK):
    return [text[i:i + n] for i in range(0, len(text), n)] or [""]


def handle_message(data):
    """处理一条 OneBot 消息事件（同步，跑在线程池里）"""
    if data.get("post_type") != "message":
        return
    mtype = data.get("message_type")
    if mtype not in ("private", "group"):
        return
    mid = data.get("message_id")
    if mid is None or dedupe(mid):
        return

    self_id = data.get("self_id")
    text, at_bot = extract_text(data.get("message"), self_id)
    if not text:
        return
    if mtype == "group" and not at_bot:
        return  # 群里没 @ 就不插话

    uid = data.get("user_id")
    gid = data.get("group_id")
    scope = ("g%d" % gid) if mtype == "group" else "p"
    sid = sid_for(scope, uid)

    print("[qq] 收到消息:", mid, "|", mtype, "| from:", uid, "|", text[:40], flush=True)
    try:
        set_sid(sid)
        reply = bot.get_reply(text)
    except Exception as e:  # noqa: BLE001
        reply = "花卷这边出了点问题：%s" % e

    for chunk in split_text(reply):
        if mtype == "group":
            send_group(gid, chunk)
        else:
            send_private(uid, chunk)
    print("[qq] 已回复 ->", "群" + str(gid) if mtype == "group" else "私聊" + str(uid), flush=True)


async def main():
    print("花卷 QQ 机器人启动，连接 NapCat:", NAPCAT_WS)
    loop = asyncio.get_running_loop()
    while True:
        try:
            async with websockets.connect(NAPCAT_WS, max_size=2 ** 24) as ws:
                print("已连接 NapCat，等待消息…", flush=True)
                async for raw in ws:
                    try:
                        data = json.loads(raw)
                    except Exception:
                        continue
                    if data.get("post_type") != "message":
                        continue
                    loop.run_in_executor(None, handle_message, data)
        except Exception as e:  # noqa: BLE001
            print("连接断开/失败，5 秒后重连:", e, flush=True)
            await asyncio.sleep(5)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("已退出")
