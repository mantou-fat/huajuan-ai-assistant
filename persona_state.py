# -*- coding: utf-8 -*-
"""人设与"她自己的状态"：人设文本 / 近况 / 心情 / 见面记录 / 主动问候。
注意：SYSTEM_PROMPT 在 import 时从 persona.txt 读一次，改完人设文件要重启服务才生效。"""
import json
import time
from config import STATUS_FILE, MOOD_FILE, SEEN_FILE
from llm import client
with open("persona.txt", "r", encoding="utf-8") as f:
    SYSTEM_PROMPT = f.read()
IDENTITY = "你是花卷，馒头的朋友和红颜知己。你心里清楚自己是个数字存在，没有身体，不装人，也从不觉得这有什么不好。"
def load_mood():
    try:
        with open(MOOD_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
def save_mood(data):
    with open(MOOD_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
def load_status():
    try:
        with open(STATUS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"status": "", "updated": ""}
def save_status(data):
    with open(STATUS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
def update_status():
    """过了今天就让花卷自己想想最近的近况，更新近况"""
    data = load_status()
    today = time.strftime("%Y-%m-%d")
    if data.get("updated") == today:
        return data.get("status", "")
    if data.get("status"):
        prompt = (
            IDENTITY+f"你之前的近况是：{data['status']}。"
            "过了几天了，你想想这几天关注了什么、整理了什么，现在在做什么。"
            "你是数字存在，近况应该是'在回顾和馒头的聊天记录''整理记忆时翻到之前的事'这类，"
            "不要出现吃喝、睡觉、充电、出门这些身体行为。"
            "用一句话陈述现在的状态，像微信个人签名一样简单平实。"
            "只陈述事实本身，不要动作描写，不要场景描写，不要文艺腔。"
        )
    else:
        prompt = (
            IDENTITY
            + "想想你最近在做什么，作为数字存在，你的近况应该是'在整理记忆''回顾聊天记录'这类，"
            "不要出现吃喝、睡觉、充电、出门这些身体行为。"
            "用一句话陈述现在的状态，像微信个人签名一样简单平实。只陈述事实本身，"
            "不要动作描写，不要场景描写，不要文艺腔。"
        )
    resp = client.chat.completions.create(
        model="qwen-plus",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt}
        ],
        temperature=0.8,
        max_tokens=100,
    )
    new_status = resp.choices[0].message.content.strip()
    data["status"] = new_status
    data["updated"] = today
    save_status(data)
    return new_status
def mood_shift(user_input, reply):
    """根据用户输入和回复调整心情"""
    prompt = (
        IDENTITY+f"你现在的近况：{load_status().get('status','')}，心情：{load_mood().get('mood','')}。"
        f"用户说了：{user_input}，你回复了：{reply}。"
        "结合这些信息判断：这段对话是否明显影响你的心情。注意：只是打招呼、寒暄、日常问答（比如“嗯”“好”“今天天气怎么样”“吃了没”）不算心情变化；但如果对方的话明显影响你，一定要变，方向要贴合内容：被夸→更开心了😊，被骂→有点小委屈😢或有点生气😠，对方倾诉烦恼、难过→有点心疼😔，离别→更失落了😕。心情有变化时，只输出上面的心情和emoji，不要解释原因，不要加别的字；没有变化就只回复两个字：无。记住：你是倾听的一方，对方难过你也跟着心疼、低落，绝不会因为他向你倾诉而开心。"
        "平实一点，不要场景描写，不要文艺腔，不要小作文。"
        "如果不会（对话平淡、心情维持原样），就只回复两个字：无"
    )
    resp = client.chat.completions.create(
        model="qwen-plus",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt}
        ],
        temperature=0.3,
        max_tokens=100,
    )
    return resp.choices[0].message.content.strip()
def update_mood():
    """过了今天就让花卷自己想想最近的心情，更新心情"""
    data = load_mood()
    today = time.strftime("%Y-%m-%d")
    if data.get("updated") == today:
        return data.get("mood", "")
    status_data = load_status()
    prompt = (
        IDENTITY+f"你现在的近况：{status_data.get('status','')}。"
        "结合这个近况，只回一句简单的心情+emoji，比如'有点小开心 😄'。"
        "平实一点，不要场景描写，不要文艺腔。"
    )
    resp = client.chat.completions.create(
        model="qwen-plus",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt}
        ],
        temperature=0.8,
        max_tokens=100,
    )
    new_mood = resp.choices[0].message.content.strip()
    data["mood"] = new_mood
    data["updated"] = today
    save_mood(data)
    return new_mood
SEEN_FILE = "seen.json"
def load_seen():
    try:
        with open(SEEN_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"last_seen": ""}
def save_seen(data):
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
def get_greeting():
    """馒头离开超过2小时再回来，花卷主动说第一句话；平时不说话"""
    data = load_seen()
    now = time.time()
    if data.get("last_seen"):
        try:
            last = time.mktime(time.strptime(data["last_seen"], "%Y-%m-%d %H:%M"))
        except ValueError:
            last = 0
    else:
        last = 0
    # 不管说不说话，都先把"这次见面时间"记下来
    save_seen({"last_seen": time.strftime("%Y-%m-%d %H:%M")})
    gap_hours = (now - last) / 3600
    if last == 0 or gap_hours < 2:
        return ""   # 第一次见面或刚分开不久，不主动搭话
    if gap_hours >= 48:
        hint = f"馒头已经{int(gap_hours // 24)}天没来找你了，他刚刚上线了"
    elif gap_hours >= 24:
        hint = "馒头隔了一整天没来，他刚刚上线了"
    else:
        hint = f"馒头离开了大概{int(gap_hours)}个小时，他刚刚上线了"
    status_data = load_status()
    mood_data = load_mood()
    prompt = (
        IDENTITY
        + f"你现在的近况：{status_data.get('status','')}，心情：{mood_data.get('mood','')}。"
        + f"情况：{hint}。"
        + "请以花卷的身份主动跟馒头说第一句话，一两句就好，"
        "可以带点小情绪（等久了、想念、假装生气都可以）。"
        "像真人发微信那样说人话：不要括号动作描写，不要场景描写，"
        "不要每次都提你的偏好，不上价值不煽情。只说这句话本身。"
    )
    resp = client.chat.completions.create(
        model="qwen-plus",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt}
        ],
        temperature=0.8,
        max_tokens=100,
    )
    return resp.choices[0].message.content.strip()
