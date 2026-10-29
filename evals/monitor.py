# -*- coding: utf-8 -*-
"""日志监控：扫各会话 audit.log + 模型用量，出异常报告"""
import os
import sys
import json
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIRS = [os.path.join(ROOT, "evals", "_auto_data"), os.path.join(ROOT, "_qqdata"),
             os.path.join(ROOT, "data"), ROOT]
USAGE = os.path.join(ROOT, "logs", "model_usage.jsonl")


def scan_audit():
    rows = []
    for base in DATA_DIRS:
        if not os.path.isdir(base):
            continue
        for dirpath, _, files in os.walk(base):
            if "audit.log" not in files:
                continue
            p = os.path.join(dirpath, "audit.log")
            try:
                with open(p, encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            rows.append(json.loads(line))
            except Exception:
                continue
    return rows


def main():
    rows = scan_audit()
    errors = [r for r in rows if r.get("ok") is False]
    actions = {}
    for r in rows:
        actions[r.get("action", "?")] = actions.get(r.get("action", "?"), 0) + 1
    usage = []
    if os.path.exists(USAGE):
        with open(USAGE, encoding="utf-8") as f:
            usage = [json.loads(l) for l in f if l.strip()]
    tokens = sum((u.get("total_tokens") or 0) for u in usage)
    models = {}
    for u in usage:
        models[u.get("model", "?")] = models.get(u.get("model", "?"), 0) + 1

    lines = ["# 运行监控", "", "时间：%s" % time.strftime("%Y-%m-%d %H:%M"), "",
             "- 审计记录：%d 条" % len(rows),
             "- 失败操作：%d 条（%.2f%%）" % (len(errors), len(errors) / max(1, len(rows)) * 100),
             "- 模型调用：%d 次，总 token：%d" % (len(usage), tokens),
             "- 模型分布：%s" % json.dumps(models, ensure_ascii=False), "",
             "## 失败明细（最近 10 条）", ""]
    for e in errors[-10:]:
        lines.append("- %s | %s | %s" % (e.get("time"), e.get("action"), str(e.get("result"))[:80]))
    if not errors:
        lines.append("无")
    lines += ["", "## 操作分布", ""]
    for k, v in sorted(actions.items(), key=lambda x: -x[1])[:10]:
        lines.append("- %s：%d" % (k, v))
    report = os.path.join(ROOT, "evals", "report_monitor.md")
    with open(report, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
