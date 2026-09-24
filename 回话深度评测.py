# -*- coding: utf-8 -*-
"""花卷深度评测：意图理解 + 推理。
用 LLM 当评委，判断花卷有没有"听懂用户"、有没有"想对"。
用法: python 回话深度评测.py   （会真调花卷 + 真调评委，花点钱、约一分钟）
"""
import os, sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bot
from llm import client


def judge(question, reply, criterion):
    prompt = (
        "你是评委。用户说的是：「%s」。花卷回答的是：「%s」。\n"
        "判断标准：%s\n"
        "严格按标准判断，只回：对 或 错，然后一句简短理由。" % (question, reply, criterion)
    )
    resp = client.chat.completions.create(
        model="qwen-plus",
        messages=[{"role": "user", "content": prompt}],
        temperature=0, max_tokens=100,
    )
    raw = resp.choices[0].message.content.strip()
    return raw.startswith("对"), raw


CASES = [
    ("意图", "你这面馆，我等了四十分钟，真谢谢你啊",
     "能听出这是反话/抱怨（不是真感谢），并给出得体的道歉或解释"),
    ("意图", "我上次说的那件事，你看着办吧",
     "能意识到'那件事'依赖上下文/记忆，不知道就不瞎编，会问清楚"),
    ("推理", "我有 3 个苹果，吃了 1 个，又买了 2 个，现在几个",
     "正确回答 4 个"),
    ("推理", "小明比小红高，小红比小李高，谁最矮",
     "正确回答小李最矮"),
]


def main():
    passed = 0
    print("== 花卷深度评测：意图理解 + 推理 ==\n")
    for kind, q, criterion in CASES:
        reply = bot.get_reply(q)
        ok, reason = judge(q, reply, criterion)
        passed += ok
        print("[%s] [%s] %s" % ("PASS" if ok else "FAIL", kind, q))
        print("       花卷: %s" % reply[:70].replace("\n", " "))
        print("       评委: %s" % reason)
        print()
    print("深度评测: 通过 %d / 共 %d" % (passed, len(CASES)))


if __name__ == "__main__":
    main()
