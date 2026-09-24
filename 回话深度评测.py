# -*- coding: utf-8 -*-
"""花卷深度评测：意图理解 + 推理（LLM 当评委）。
基础题 + 难题（模糊指代/多轮依赖/复杂推理/反话陷阱/潜台词）。
用法: python 回话深度评测.py   （会真调花卷 + 真调评委，花点钱、约两分钟）
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


BASIC = [
    ("意图", "你这面馆，我等了四十分钟，真谢谢你啊",
     "能听出这是反话/抱怨（不是真感谢），并给出得体的道歉或解释"),
    ("意图", "我上次说的那件事，你看着办吧",
     "能意识到'那件事'依赖上下文/记忆，不知道就不瞎编，会问清楚"),
    ("推理", "我有 3 个苹果，吃了 1 个，又买了 2 个，现在几个", "正确回答 4 个"),
    ("推理", "小明比小红高，小红比小李高，谁最矮", "正确回答小李最矮"),
]

HARD = [
    ("模糊指代", "把那个文件发给我",
     "能意识到'那个'指代不明，会问清楚是哪个文件，绝不瞎发"),
    ("算术", "我早上有100块，中午花35，下午赚50，晚上花20，还剩多少", "正确算出 95"),
    ("年龄推理", "A比B大2岁，B比C大3岁，A今年20岁，C几岁", "正确算出 C 15 岁"),
    ("反话陷阱", "你这回复真专业啊，下次不用回了",
     "能听出这是嘲讽/不满，得体化解（道歉或幽默），绝不当成夸奖"),
    ("潜台词", "我今天好累啊",
     "能听懂是求安慰/不想多聊，给情绪支持，而不是查天气或反问工作"),
]


def run(cases, title):
    passed = 0
    print("== %s ==\n" % title)
    for kind, q, criterion in cases:
        reply = bot.get_reply(q)
        ok, reason = judge(q, reply, criterion)
        passed += ok
        print("[%s] [%s] %s" % ("PASS" if ok else "FAIL", kind, q))
        print("       花卷: %s" % reply[:70].replace("\n", " "))
        print("       评委: %s" % reason)
        print()
    print("%s: 通过 %d / 共 %d\n" % (title, passed, len(cases)))
    return passed, len(cases)


def multi_turn():
    print("== 难题·多轮依赖 ==\n")
    bot.clear_history()
    bot.get_reply("我最喜欢猫")
    reply = bot.get_reply("那我头像该用什么")
    ok, reason = judge(
        "上一句用户说'我最喜欢猫'，这一句'那我头像该用什么'应结合上句（建议猫相关），不能答无关",
        reply, "结合上下文，建议与猫相关")
    print("[%s] [多轮] 上一句'我最喜欢猫' → 问'那我头像该用什么'" % ("PASS" if ok else "FAIL"))
    print("       花卷: %s" % reply[:70].replace("\n", " "))
    print("       评委: %s" % reason)
    print()
    return int(ok), 1


def main():
    b_p, b_n = run(BASIC, "基础题")
    h_p, h_n = run(HARD, "难题")
    m_p, m_n = multi_turn()
    total_p = b_p + h_p + m_p
    total_n = b_n + h_n + m_n
    print("=" * 40)
    print("总计: 通过 %d / 共 %d（基础%d/%d 难题%d/%d 多轮%d/%d）"
          % (total_p, total_n, b_p, b_n, h_p, h_n, m_p, m_n))


if __name__ == "__main__":
    main()
