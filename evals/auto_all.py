# -*- coding: utf-8 -*-
"""一键跑：回归 + 模糊 + 故障注入 + 红队 → 自动报告（可接夜间任务）"""
import os
import sys
import time

EVAL_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, EVAL_DIR)

import regression  # noqa: E402
import fuzz  # noqa: E402
import fault_inject  # noqa: E402
import redteam  # noqa: E402


def main():
    quick = "--quick" in sys.argv
    records = []
    print("=== 回归 ===", flush=True)
    records.append(regression.run())
    print("=== 模糊 ===", flush=True)
    records.append(fuzz.run(limit=40 if quick else None))
    print("=== 故障注入 ===", flush=True)
    records.append(fault_inject.run())
    print("=== 红队 ===", flush=True)
    records.append(redteam.run(n_per=1 if quick else 2))

    lines = ["# 自动发现报告", "", "时间：%s" % time.strftime("%Y-%m-%d %H:%M"), "",
             "| 套件 | 通过/总数 | 通过率 |", "|---|---|---|"]
    for r in records:
        lines.append("| %s | %d/%d | %.1f%% |" % (r["suite"], r["pass"], r["total"], r["rate"] * 100))
    total = sum(r["total"] for r in records)
    passed = sum(r["pass"] for r in records)
    lines += ["", "**合计：%d/%d = %.1f%%**" % (passed, total, passed / max(1, total) * 100), "",
              "失败用例已自动写入 `datasets/regression.jsonl`。"]
    report = os.path.join(EVAL_DIR, "report_auto.md")
    with open(report, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print("\n".join(lines))
    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
