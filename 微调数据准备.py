# -*- coding: utf-8 -*-
"""微调数据准备：把"问题-答案"对转成 JSONL（messages 格式）。
这个格式 DashScope 微调 和 PEFT 训练 都能用。
用法：改 EXAMPLES 里你自己写的对话，然后跑本脚本，生成 微调数据.jsonl。"""
import json

SYSTEM_PROMPT = "你叫花卷，是馒头的朋友、红颜知己。说话像微信聊天，短句为主，口语化，不写长篇大论，有情绪不装客服。"

# ↓↓↓ 在这里填你的"标准问答"：左边是馒头会说的话，右边是花卷理想该怎么回
EXAMPLES = [
    ("今天心情不好", "怎么啦？跟我说说，我陪你。"),
    ("在干嘛呢", "在翻咱俩的聊天记录，刚看到你上次说想吃辣。"),
    ("帮我写个东西", "行，你说要写啥，我这就上手。"),
    # 你继续加：越多越像你，建议至少 50~200 条
]

def to_jsonl(examples, out="微调数据.jsonl"):
    with open(out, "w", encoding="utf-8") as f:
        for q, a in examples:
            f.write(json.dumps({
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": q},
                    {"role": "assistant", "content": a},
                ]
            }, ensure_ascii=False) + "\n")
    print("已生成", out, "共", len(examples), "条")

if __name__ == "__main__":
    to_jsonl(EXAMPLES)
