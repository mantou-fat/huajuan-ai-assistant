# -*- coding: utf-8 -*-
"""第1课·手工作业：改 alpha，看检索排名怎么变。

alpha 是"语义 vs 字面"的权重：
  大(0.9) = 更信向量(语义)    小(0.1) = 更信关键词(字面)

用法：改下面 ALPHA 的值，然后命令行跑：
    D:\minicoda\envs\ai_study\python.exe 学算法_第1课.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rag import debug_retrieval

ALPHA = 0.65   # ← 只改这一行：试 0.1 / 0.3 / 0.65 / 0.9

QUERIES = ["什么是RAG", "余弦相似度怎么算", "text-embedding-v3 怎么分批调用", "今天晚饭吃什么好"]

for q in QUERIES:
    print("=" * 60)
    print("查询：", q, "（alpha =", ALPHA, "）")
    for txt, hybrid, cos, lex in debug_retrieval(q, k=3, alpha=ALPHA):
        print("  综合%.3f = 向量%.3f + 字面%.3f ｜ %s" % (hybrid, cos, lex, txt[:38]))
    print()
