# -*- coding: utf-8 -*-
"""从 results/*.json 汇总，更新基线并重生成 report.md（无需重跑评测）"""
import os
import json
import time

EVAL_DIR = os.path.dirname(os.path.abspath(__file__))
RESULTS = os.path.join(EVAL_DIR, "results")
BASELINE = os.path.join(EVAL_DIR, "baseline.json")
REPORT = os.path.join(EVAL_DIR, "report.md")

SUITES = ["tools", "agents", "rag", "persona", "safety", "memory", "perf", "multiuser"]

results = {}
for s in SUITES:
    p = os.path.join(RESULTS, s + ".json")
    if os.path.exists(p):
        results[s] = json.load(open(p, encoding="utf-8"))

base = {}
if os.path.exists(BASELINE):
    base = json.load(open(BASELINE, encoding="utf-8"))

merged = dict(base)
for s, r in results.items():
    merged[s] = r["rate"]
json.dump(merged, open(BASELINE, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

lines = ["# 花卷评测报告", "", "时间：%s" % time.strftime("%Y-%m-%d %H:%M"), "",
         "| 套件 | 通过/总数 | 通过率 | 基线 |", "|---|---|---|---|"]
for s in SUITES:
    if s not in results:
        continue
    r = results[s]
    lines.append("| %s | %d/%d | %.1f%% | %s |" % (
        s, r["pass"], r["total"], r["rate"] * 100,
        ("%.1f%%" % (base[s] * 100)) if s in base else "—"))
lines += ["", "门禁：任一指标低于基线 5 个百分点 → FAIL"]
open(REPORT, "w", encoding="utf-8").write("\n".join(lines) + "\n")
print("\n".join(lines))
