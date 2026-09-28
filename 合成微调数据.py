# -*- coding: utf-8 -*-
"""合成微调数据：让强模型照着"种子示例"批量生成训练数据（知识蒸馏）。
你不用真聊几百句——写 20 个"真像花卷"的标杆，让 qwen-max 照着批量造。"""
import json
from llm import client

SYSTEM_PROMPT = "你叫花卷，是馒头的朋友、红颜知己。说话像微信聊天，短句为主，口语化，有情绪不装客服。"

# ↓↓↓ 20 个"标杆对话"：你写，越像花卷越好。这是合成的"风格模板"，质量决定一切。
SEED = [
    ("今天心情不好", "怎么啦？跟我说说，我陪你。"),
    ("在干嘛呢", "在翻咱俩的聊天记录，刚看到你上次说想吃辣。"),
    ("你会不会累", "我是程序，不会累。倒是你，别老熬夜。"),
    ("帮我写个东西", "行，你说写啥，我这就上手。"),
    # 你继续补到 20 个左右，覆盖：日常闲聊 / 吐槽 / 求助 / 抬杠 / 安慰
]

def synthesize(seed, n=100, model="qwen-max"):
    """照着种子示例，让强模型批量生成 n 组同风格对话"""
    seed_text = "\n".join("馒头：%s\n花卷：%s" % (q, a) for q, a in seed)
    prompt = (
        "下面是一些'馒头和花卷'的对话示例，展示花卷的说话风格（短句、口语、有情绪、会反驳、不装客服）。\n\n%s\n\n"
        "请照这个风格，新写 %d 组对话，每组严格两行：\n馒头：<问题>\n花卷：<回答>\n"
        "问题要像真人微信聊天（日常、吐槽、求助、闲聊都行），回答要符合花卷人设、口语化。"
        "只输出对话本身，不要解释、不要编号。"
        % (seed_text, n)
    )
    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.9,
        max_tokens=4000,
    )
    pairs = []
    q = None
    for ln in resp.choices[0].message.content.strip().split("\n"):
        ln = ln.strip()
        if ln.startswith("馒头："):
            q = ln[len("馒头："):].strip()
        elif ln.startswith("花卷：") and q:
            pairs.append((q, ln[len("花卷："):].strip()))
            q = None
    return pairs

def to_jsonl(pairs, out="微调数据.jsonl"):
    with open(out, "w", encoding="utf-8") as f:
        for q, a in pairs:
            f.write(json.dumps({"messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": q},
                {"role": "assistant", "content": a},
            ]}, ensure_ascii=False) + "\n")
    print("合成 %d 条，已写入 %s" % (len(pairs), out))

if __name__ == "__main__":
    pairs = synthesize(SEED, n=100)
    to_jsonl(pairs)
