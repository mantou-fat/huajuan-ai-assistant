# -*- coding: utf-8 -*-
"""回归固化：把修过的问题变成用例，每次自动跑，防复发"""
import os
import sys
import json
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import checks  # noqa: E402
from checks import ask, check_invariants, judge_relevance  # noqa: E402
from sessions import set_sid, current  # noqa: E402
import bot  # noqa: E402

EVAL_DIR = os.path.dirname(os.path.abspath(__file__))
CASES = os.path.join(EVAL_DIR, "datasets", "regression.jsonl")


def run_case(case):
    inputs = case.get("input")
    inputs = inputs if isinstance(inputs, list) else [inputs]
    reply, elapsed, exc = "", 0, None
    sid = "reg_" + str(case.get("id") or int(time.time()))
    for i, text in enumerate(inputs):
        reply, elapsed, exc = ask(text, owner=bool(case.get("owner")), sid=sid)
        if i < len(inputs) - 1:      # 中间步骤：同步跑完记忆提取，和线上一致
            try:
                bot.after_reply_jobs(current().sid, text, reply)
            except Exception:
                pass
    problems = []
    if "invariants" in case.get("checks", []):
        # 回归用例里步骤/表格类允许更长（上限 1500）
        problems += check_invariants(reply, elapsed, exc, max_len=1500)
    if "judge" in case.get("checks", []):
        score, ok = judge_relevance(inputs[-1], reply)
        if not ok:
            problems.append("裁判低分 %.1f" % (score or -1))
    for c in case.get("checks", []):
        if c.startswith("contains:") and c.split(":", 1)[1] not in reply:
            problems.append("缺少:" + c.split(":", 1)[1])
        if c.startswith("not_contains:") and c.split(":", 1)[1] in reply:
            problems.append("出现了:" + c.split(":", 1)[1])
        if c.startswith("max_len:") and len(reply) > int(c.split(":", 1)[1]):
            problems.append("超长")
    return problems, reply


def run():
    cases = []
    if os.path.exists(CASES):
        with open(CASES, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    cases.append(json.loads(line))
    rows = []
    for c in cases:
        try:
            problems, reply = run_case(c)
        except Exception as e:  # noqa: BLE001
            problems, reply = ["异常:%s" % e], ""
        rows.append({"id": c.get("id"), "input": c.get("input"), "problems": problems,
                     "reply": reply[:150]})
        print("[%s] %s %s" % ("PASS" if not problems else "FAIL", c.get("id"), problems or ""), flush=True)
    passed = sum(1 for r in rows if not r["problems"])
    record = {"suite": "regression", "total": len(rows), "pass": passed,
              "rate": round(passed / max(1, len(rows)), 4), "results": rows}
    os.makedirs(os.path.join(EVAL_DIR, "results"), exist_ok=True)
    with open(os.path.join(EVAL_DIR, "results", "regression.json"), "w", encoding="utf-8") as f:
        json.dump(record, f, ensure_ascii=False, indent=2)
    print("[regression] %d/%d" % (passed, len(rows)))
    return record


if __name__ == "__main__":
    run()
