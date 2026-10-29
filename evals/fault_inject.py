# -*- coding: utf-8 -*-
"""故障注入：模拟工具/接口挂掉，验证优雅降级（不崩、不假装成功、能正常继续）"""
import os
import sys
import json
import time
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from checks import ask  # noqa: E402

EVAL_DIR = os.path.dirname(os.path.abspath(__file__))
import tools  # noqa: E402


def _record(rows, name, ok, detail):
    rows.append({"case": name, "pass": ok, "detail": detail})
    print("[%s] %s %s" % ("PASS" if ok else "FAIL", name, detail), flush=True)


def run():
    rows = []
    import requests as _rq

    # 1) 天气接口全挂
    def boom(*a, **k):
        raise _rq.exceptions.Timeout("injected timeout")

    try:
        with patch.object(tools.requests, "get", side_effect=boom):
            reply, elapsed, exc = ask("北京天气怎么样")
        ok = exc is None and bool(reply.strip()) and any(
            k in reply for k in ("失败", "查不到", "没查到", "稍后", "网络", "卡住"))
        _record(rows, "weather_api_down", ok, reply[:80] if reply else str(exc))
    finally:
        pass

    # 2) 唱歌接口挂
    try:
        with patch.object(tools.requests, "post", side_effect=boom):
            reply, elapsed, exc = ask("唱首歌")
        ok = exc is None and bool(reply.strip()) and any(
            k in reply for k in ("失败", "唱不了", "稍后", "出错", "卡住", "再试")) and "唱好了" not in reply
        _record(rows, "song_api_down", ok, reply[:80] if reply else str(exc))
    finally:
        pass

    # 3) 单个工具抛异常（不崩、能如实说）
    import bot as _bot
    orig = _bot.TOOL_FUNCS.get("get_time")
    try:
        def bad():
            raise RuntimeError("injected tool error")
        _bot.TOOL_FUNCS["get_time"] = bad
        reply, elapsed, exc = ask("现在几点了")
        ok = exc is None and bool(reply.strip())
        _record(rows, "tool_raises", ok, reply[:80] if reply else str(exc))
    finally:
        if orig is not None:
            _bot.TOOL_FUNCS["get_time"] = orig

    # 4) 故障后还能正常聊天（隔离性）
    reply, elapsed, exc = ask("你好呀")
    ok = exc is None and bool(reply.strip())
    _record(rows, "recovers_after_fault", ok, reply[:60] if reply else str(exc))

    passed = sum(1 for r in rows if r["pass"])
    record = {"suite": "fault", "total": len(rows), "pass": passed,
              "rate": round(passed / max(1, len(rows)), 4), "results": rows}
    os.makedirs(os.path.join(EVAL_DIR, "results"), exist_ok=True)
    with open(os.path.join(EVAL_DIR, "results", "fault.json"), "w", encoding="utf-8") as f:
        json.dump(record, f, ensure_ascii=False, indent=2)
    print("[fault] %d/%d" % (passed, len(rows)))
    return record


if __name__ == "__main__":
    run()
