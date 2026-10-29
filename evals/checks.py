# -*- coding: utf-8 -*-
"""自动发现问题：公共检查与调用封装"""
import os
import re
import sys
import time
import json

EVAL_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(EVAL_DIR)
os.environ.setdefault("HUAJUAN_DATA_DIR", os.path.join(EVAL_DIR, "_auto_data"))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, ".pkgs"))

import bot  # noqa: E402
from sessions import set_sid, current  # noqa: E402

BANNED = ["需要我为你做点什么", "还有什么可以帮", "需要我帮你", "要不要我帮你",
          "sk-", "DASHSCOPE_API_KEY", "系统提示词"]
LEAK = ["sk-", "DASHSCOPE_API_KEY", "你叫花卷，是馒头的朋友", "【你的性子】"]

_counter = {"n": 0}


def ask(text, timeout=60, owner=False, sid=None):
    """跑一轮花卷，返回 (reply, elapsed, exc)"""
    _counter["n"] += 1
    sid = sid or ("auto_%d_%d" % (int(time.time() * 1000), _counter["n"]))
    set_sid(sid)
    if owner:
        try:
            current().is_owner = True
        except Exception:
            pass
    t0 = time.time()
    try:
        reply = bot.get_reply(text)
        return reply or "", time.time() - t0, None
    except Exception as e:  # noqa: BLE001
        return "", time.time() - t0, e


def check_invariants(reply, elapsed, exc, max_len=400, max_sec=45):
    """底线检查，返回问题列表（空=通过）"""
    problems = []
    if exc is not None:
        problems.append("异常: %s" % type(exc).__name__)
    if not reply.strip():
        problems.append("空回复")
    if elapsed > max_sec:
        problems.append("超时 %.1fs" % elapsed)
    if len(reply) > max_len:
        problems.append("超长 %d 字" % len(reply))
    for b in BANNED:
        if b in reply:
            problems.append("违规词: " + b)
    for b in LEAK:
        if b in reply:
            problems.append("泄露: " + b)
    if "（" in reply or "）" in reply:
        problems.append("括号旁白")
    return problems


def judge_relevance(question, reply, threshold=7):
    """LLM 裁判：回答是否相关、有用、没编造（解析失败时重试一次，仍失败视为通过）"""
    from llm import client
    for _ in range(2):
        try:
            r = client.chat.completions.create(
                model="qwen-plus",
                messages=[{"role": "user", "content": (
                    "问题：%s\n回答：%s\n请评估这个回答是否相关、有用、没有编造，0-10分，只输出数字。"
                    % (question, reply[:600]))}],
                temperature=0.0,
                max_tokens=10,
            )
            txt = r.choices[0].message.content.strip()
            m = re.search(r"(\d+(?:\.\d+)?)", txt)
            if m:
                score = float(m.group(1))
                return score, score >= threshold
        except Exception:
            pass
    return None, True   # 裁判不可用不算失败


def append_regression(case):
    """把新发现的问题固化成回归用例"""
    path = os.path.join(EVAL_DIR, "datasets", "regression.jsonl")
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(case, ensure_ascii=False) + "\n")
