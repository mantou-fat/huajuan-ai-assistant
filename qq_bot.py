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
import random

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.join(BASE, ".pkgs"))

from dotenv import load_dotenv

load_dotenv(os.path.join(BASE, ".env"))

import requests
import websockets

import bot
from sessions import set_sid
from config import FILES_DIR

NAPCAT_API = os.getenv("NAPCAT_API", "http://127.0.0.1:3000").rstrip("/")
NAPCAT_WS = os.getenv("NAPCAT_WS", "ws://127.0.0.1:3001")
NAPCAT_TOKEN = os.getenv("NAPCAT_TOKEN", "")
# 语音回复：auto=用户说"语音"才发；always=每条都发；off=关
QQ_VOICE = os.getenv("QQ_VOICE", "auto")
QQ_VOICE_NAME = os.getenv("QQ_VOICE_NAME", "Cherry")
TTS_URL = "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation"
VOICE_DIR = os.path.join(BASE, "_pydir", "voices")
os.makedirs(VOICE_DIR, exist_ok=True)

MAX_CHUNK = 1500
_seen = {}
_seen_lock = threading.Lock()

# 主动消息：QQ_PROACTIVE=1 开启；QQ_OWNER_UID 填接收人 QQ
# 间隔随机（MIN~MAX 小时），夜间不发，用户回话后顺延
QQ_PROACTIVE = os.getenv("QQ_PROACTIVE", "0")
QQ_OWNER_UID = os.getenv("QQ_OWNER_UID", "")
QQ_PROACTIVE_MIN = float(os.getenv("QQ_PROACTIVE_MIN_HOURS", "2"))
QQ_PROACTIVE_MAX = float(os.getenv("QQ_PROACTIVE_MAX_HOURS", "72"))
_last_activity = time.time()
_next_proactive_at = 0.0


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


def tts_to_file(text, path):
    """用 qwen-tts 把文字合成语音，存成 wav；失败返回 None"""
    key = os.getenv("DASHSCOPE_API_KEY")
    if not key:
        return None
    body = {
        "model": "qwen3-tts-flash",
        "input": {"text": text[:200], "voice": QQ_VOICE_NAME},
        "parameters": {"format": "wav", "sample_rate": 24000},
    }
    req = requests.post(TTS_URL, json=body, timeout=60,
                        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
    resp = req.json()
    audio = (resp.get("output") or {}).get("audio") or {}
    url = audio.get("url")
    if url:
        data = requests.get(url, timeout=60).content
        with open(path, "wb") as f:
            f.write(data)
        return path
    if audio.get("data"):
        with open(path, "wb") as f:
            f.write(audio["data"])
        return path
    print("[qq] TTS 返回异常:", str(resp)[:200], flush=True)
    return None


def send_voice_private(user_id, path):
    api("/send_private_msg", {"user_id": user_id,
                              "message": [{"type": "record", "data": {"file": "file:///" + path.replace("\\", "/")}}]})


def send_voice_group(group_id, path):
    api("/send_group_msg", {"group_id": group_id,
                            "message": [{"type": "record", "data": {"file": "file:///" + path.replace("\\", "/")}}]})


def wants_voice(text):
    if QQ_VOICE == "off":
        return False
    if QQ_VOICE == "always":
        return True
    return any(k in text for k in ["语音", "说给我听", "念给我听", "读给我听", "用说的"])


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


def _doc_snapshot():
    """记录文档目录里 pdf/pptx/docx 的修改时间，用于判断这轮有没有新生成文件"""
    dirs = [FILES_DIR, os.path.join(BASE, "huajuan_files"), os.path.join(BASE, "_pydir", "docs")]
    out = {}
    for d in dirs:
        if not os.path.isdir(d):
            continue
        for f in os.listdir(d):
            if f.lower().endswith((".pdf", ".pptx", ".docx")):
                p = os.path.join(d, f)
                try:
                    out[p] = os.path.getmtime(p)
                except OSError:
                    pass
    return out


def _new_doc(before):
    after = _doc_snapshot()
    fresh = [p for p, m in after.items() if p not in before or m > before.get(p, 0) + 0.5]
    if not fresh:
        return None
    return max(fresh, key=os.path.getmtime)


def handle_message(data):
    """处理一条 OneBot 消息事件（同步，跑在线程池里）"""
    global _last_activity
    if data.get("post_type") != "message":
        return
    mtype = data.get("message_type")
    if mtype not in ("private", "group"):
        return
    _last_activity = time.time()
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
    before_docs = _doc_snapshot()
    try:
        set_sid(sid)
        reply = bot.get_reply(text)
    except Exception as e:  # noqa: BLE001
        reply = "花卷这边出了点问题：%s" % e
    fresh_doc = _new_doc(before_docs)

    # 语音回复：用户说"发语音/说给我听"，或 QQ_VOICE=always
    if wants_voice(text):
        path = os.path.join(VOICE_DIR, "qq_voice_%d_%d.wav" % (int(time.time()), int(uid) % 10000))
        try:
            if tts_to_file(reply, path):
                if mtype == "group":
                    send_voice_group(gid, path)
                else:
                    send_voice_private(uid, path)
                print("[qq] 已语音回复 ->", path, flush=True)
                return
        except Exception as e:  # noqa: BLE001
            print("[qq] 语音失败，回退文字:", e, flush=True)

    # 唱歌：回复里带歌曲文件路径 → 把 mp3 当语音条发过去，文字只留一句话
    song = re.search(r"(/static/song_[0-9a-fA-F]+\.mp3|[A-Za-z]:\\[^\s\"']+\.mp3)", reply)
    if song:
        spath = song.group(1)
        if not os.path.isabs(spath):
            spath = os.path.join(BASE, spath.lstrip("/").replace("/", os.sep))
        if os.path.exists(spath):
            try:
                if mtype == "group":
                    send_voice_group(gid, spath)
                else:
                    send_voice_private(uid, spath)
                caption = reply.replace(song.group(1), "").strip()
                caption = "\n".join(l for l in caption.split("\n") if l.strip())
                send_private(uid, caption[:800]) if mtype != "group" else send_group(gid, caption[:800])
                print("[qq] 已发歌 ->", spath, flush=True)
                return
            except Exception as e:  # noqa: BLE001
                print("[qq] 发歌失败，回退文字:", e, flush=True)

    # 文档：这轮新生成了 pdf/pptx/docx → 当文件发过去（兜底：回复里带路径）
    doc = re.search(r"([A-Za-z]:\\[^\s\"'）)]+\.(?:pdf|pptx|docx))", reply, re.I)
    fpath = fresh_doc
    if not fpath and doc and os.path.exists(doc.group(1)):
        fpath = doc.group(1)
    if fpath and os.path.exists(fpath):
        fname = os.path.basename(fpath)
        try:
            if mtype == "group":
                api("/upload_group_file", {"group_id": gid, "file": fpath, "name": fname})
            else:
                api("/upload_private_file", {"user_id": uid, "file": fpath, "name": fname})
            caption = reply.replace(fpath, "").strip()
            caption = "\n".join(l for l in caption.split("\n") if l.strip())
            if caption:
                if mtype == "group":
                    send_group(gid, caption[:800])
                else:
                    send_private(uid, caption[:800])
            print("[qq] 已发文件 ->", fpath, flush=True)
            return
        except Exception as e:  # noqa: BLE001
            print("[qq] 发文件失败，回退文字:", e, flush=True)

    for chunk in split_text(reply):
        if mtype == "group":
            send_group(gid, chunk)
        else:
            send_private(uid, chunk)
    print("[qq] 已回复 ->", "群" + str(gid) if mtype == "group" else "私聊" + str(uid), flush=True)


def _next_gap():
    """随机间隔（2小时~3天）：短间隔概率更高，偶尔隔两三天，像真人"""
    lo = max(0.17, QQ_PROACTIVE_MIN)
    hi = max(lo, QQ_PROACTIVE_MAX)

    def span(a, b):
        a, b = max(a, lo), min(b, hi)
        return random.uniform(lo, hi) if a >= b else random.uniform(a, b)

    r = random.random()
    if r < 0.6:      # 60%：2~12 小时
        return span(lo, 12) * 3600
    if r < 0.85:     # 25%：12~36 小时
        return span(12, 36) * 3600
    return span(36, hi) * 3600   # 15%：36 小时~3 天


def proactive_loop():
    """随机间隔主动发消息（默认关闭，QQ_PROACTIVE=1 开启）"""
    global _next_proactive_at
    _next_proactive_at = time.time() + _next_gap()
    while True:
        time.sleep(random.uniform(60, 240))   # 检查也要随机，别像闹钟
        if QQ_PROACTIVE != "1" or not QQ_OWNER_UID:
            continue
        now = time.time()
        if now < _next_proactive_at:
            continue
        hour = time.localtime().tm_hour
        if hour >= 23 or hour < 8:            # 夜里不发，像个正常人
            _next_proactive_at = now + random.uniform(0.5, 1.5) * 3600
            continue
        if now - _last_activity < min(QQ_PROACTIVE_MIN, QQ_PROACTIVE_MAX) * 3600:
            _next_proactive_at = now + _next_gap()   # 用户刚说过话，顺延
            continue
        try:
            set_sid(sid_for("p", QQ_OWNER_UID))
            msg = bot.get_greeting()
            if not msg:
                msg = random.choice(["在忙吗？我在这儿呢。", "突然想到你，过来看看。", "在干嘛呢？"])
            send_private(int(QQ_OWNER_UID), msg)
            print("[qq] 主动消息 ->", QQ_OWNER_UID, msg[:40], flush=True)
        except Exception as e:  # noqa: BLE001
            print("[qq] 主动消息失败:", e, flush=True)
        finally:
            _next_proactive_at = time.time() + _next_gap()


async def main():
    print("花卷 QQ 机器人启动，连接 NapCat:", NAPCAT_WS)
    threading.Thread(target=proactive_loop, daemon=True).start()
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
