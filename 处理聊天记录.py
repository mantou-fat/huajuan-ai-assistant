# -*- coding: utf-8 -*-
"""处理微信聊天记录：抽"胖馒头"的话 → 过滤有价值、能独立成句的 → 让花卷配回答 → 生成训练 JSONL。
只用了馒头自己的话，不含朋友的内容（隐私安全）。"""
import json
import re
from llm import client

def load_messages(path="聊天记录_原始.txt"):
    with open(path, encoding="utf-8") as f:
        raw = f.read()
    msgs = []
    for line in raw.split("\n"):
        for part in re.split(r"胖馒头[:：]", line):
            part = part.strip()
            if part:
                msgs.append(part)
    return msgs

def filter_worthy(msgs):
    """过滤掉太短/太依赖上下文的（OK、好吧、？这类单独拎出来没法当训练样本）"""
    skip = {"ok", "？", "?", "好吧", "行吧", "咋了", "那算了", "不知道", "好像是",
            "这个啊", "那没招了", "铁柱", "那真没招", "会的会有的", "让我看看"}
    out, seen = [], set()
    for m in msgs:
        m = m.strip()
        if not m or len(m) < 4:
            continue
        if m.lower() in skip:
            continue
        if m in seen:
            continue
        seen.add(m)
        out.append(m)
    return out

SYSTEM = "你叫花卷，是馒头的朋友、红颜知己。说话像微信聊天：短句、口语、有情绪、会调侃会关心，不装客服、不写长篇。"

def pair_with_huajuan(msgs, model="qwen-plus"):
    pairs = []
    for m in msgs:
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[{"role": "system", "content": SYSTEM},
                          {"role": "user", "content": "馒头给你发了一句：%s\n请用花卷的口吻回一句（1-2句，口语自然，可以调侃）。" % m}],
                temperature=0.8,
                max_tokens=80,
            )
            a = (resp.choices[0].message.content or "").strip()
            if a:
                pairs.append((m, a))
        except Exception:
            pass
    return pairs

def to_jsonl(pairs, out="微调数据_真实风格.jsonl"):
    with open(out, "w", encoding="utf-8") as f:
        for q, a in pairs:
            f.write(json.dumps({"messages": [
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": q},
                {"role": "assistant", "content": a},
            ]}, ensure_ascii=False) + "\n")
    print("生成 %d 条 -> %s" % (len(pairs), out))

if __name__ == "__main__":
    msgs = load_messages()
    good = filter_worthy(msgs)
    print("原始 %d 条 -> 有价值 %d 条" % (len(msgs), len(good)))
    pairs = pair_with_huajuan(good)
    to_jsonl(pairs)
    print("\n--- 前5条预览 ---")
    for q, a in pairs[:5]:
        print("馒头：%s\n花卷：%s\n" % (q, a))
