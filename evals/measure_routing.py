# -*- coding: utf-8 -*-
"""路由前后对比：延迟 + token 消耗（同一组问题跑两遍）"""
import os
import sys
import json
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("HUAJUAN_DATA_DIR", os.path.join(ROOT, "evals", "_data"))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, ".pkgs"))

import bot  # noqa: E402
from sessions import set_sid  # noqa: E402

PROMPTS = ["你好呀", "讲个短笑话", "我今天有点累", "晚安", "在干嘛",
           "夸夸我", "我有点烦", "陪我聊会儿", "现在几点了？", "北京天气怎么样？"]
LOG = os.path.join(ROOT, "logs", "model_usage.jsonl")


def read_usage():
    rows = []
    if os.path.exists(LOG):
        with open(LOG, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
    return rows


def run(mode):
    os.environ["MODEL_ROUTER"] = mode
    set_sid("perf_warmup_" + mode)          # 预热一次，避免首调冷启动干扰
    bot.get_reply("你好")
    start = len(read_usage())
    lat, models = [], []
    for i, p in enumerate(PROMPTS):
        set_sid("perf_route_%s_%d_%d" % (mode, int(time.time()), i))
        t0 = time.time()
        bot.get_reply(p)
        lat.append(time.time() - t0)
        models.append(bot.pick_model(p))
    rows = read_usage()[start:]
    tokens = sum((r.get("total_tokens") or 0) for r in rows)
    s = sorted(lat)
    median = s[len(s) // 2]
    return {"mode": mode, "latency": [round(x, 2) for x in lat],
            "avg": round(sum(lat) / len(lat), 2), "median": round(median, 2),
            "tokens": tokens, "models": models, "calls": len(rows)}


if __name__ == "__main__":
    off = run("0")
    on = run("1")
    print(json.dumps({"router_off": off, "router_on": on}, ensure_ascii=False, indent=2))
    with open(os.path.join(ROOT, "evals", "results", "routing.json"), "w", encoding="utf-8") as f:
        json.dump({"router_off": off, "router_on": on}, f, ensure_ascii=False, indent=2)
