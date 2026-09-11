# -*- coding: utf-8 -*-
"""RAG 知识库：embedding 工具 + 知识入库/分块/检索。
状态说明：knowledge_base 是列表（共享对象）；_kb_embeddings 会被重新赋值，
所以它的 global 语句必须留在这个文件里。"""
import re
import numpy as np

from config import KNOWLEDGE_FILE
from llm import client


def split_long_text(text, max_len):
    """把长文切成每块不超过 max_len 字的列表。切法：先按换行断段，段内再按句末标点断句，
    句子比 max_len 还长就硬切——保证每块都是完整的语义单元，资料员才读得懂"""
    units = []                          # 第一步：磨成最小单元（句子）
    for para in text.split("\n"):
        para = para.strip()
        if not para:
            continue
        units.extend(re.split(r'(?<=[。！？!?])', para))
    blocks, cur = [], ""                # 第二步：句子攒成块，够一斗就封斗
    for u in units:
        u = u.strip()
        if not u:
            continue
        if len(u) > max_len:            # 碰到超长句，硬切
            if cur:
                blocks.append(cur)
                cur = ""
            for i in range(0, len(u), max_len):
                blocks.append(u[i:i + max_len])
        elif len(cur) + len(u) <= max_len:
            cur += u
        else:
            blocks.append(cur)
            cur = u
    if cur:
        blocks.append(cur)
    return blocks
def load_knowledge(file_path):
    with open(file_path, 'r', encoding='utf-8') as f:
        return [line.strip() for line in f if line.strip()]

def add_knowledge(text):
    """知识入库：短句直接进；长文自动按句切成 ≤80 字的分块再进（复用 split_long_text），
    防止一整行 3000 字把检索搞崩"""
    global _kb_embeddings
    text = (text or "").strip()
    if not text:
        return 0
    if len(text) <= 80:              # 本来就是规范条目，直接入库
        chunks = [text]
    else:                            # 长文：切成 ≤80 字的块
        chunks = [c for c in split_long_text(text, 80) if c.strip()]
    for c in chunks:
        knowledge_base.append(c)
        with open(KNOWLEDGE_FILE, "a", encoding="utf-8") as f:
            f.write(c + "\n")
    _kb_embeddings = None            # 知识库变了，向量缓存作废
    return len(chunks)

knowledge_base = load_knowledge(KNOWLEDGE_FILE)
_kb_embeddings = None  # 知识库向量缓存，避免每次检索都重新算全库向量


def get_embedding(texts):
    """获取文本的向量表示，自动分批（每批最多10条）"""
    batch_size = 10
    all_embeddings = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]
        response = client.embeddings.create(
            model="text-embedding-v3",
            input=batch
        )
        all_embeddings.extend([item.embedding for item in response.data])
    return all_embeddings

def get_kb_embeddings():
    global _kb_embeddings
    if _kb_embeddings is None:
        _kb_embeddings = get_embedding(knowledge_base) if knowledge_base else []
    return _kb_embeddings

def cosine_similarity(a, b):
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    if na == 0 or nb == 0:
        return 0.0
    return np.dot(a, b) / (na * nb)

def top_k_search(query, k=3, threshold=0.35):
    """相似度低于 threshold 的知识直接丢弃，返回可能为空列表"""
    if not knowledge_base:
        return []
    query_vec = get_embedding([query])[0]
    kb_vecs = get_kb_embeddings()
    sims = [(i, cosine_similarity(query_vec, v)) for i, v in enumerate(kb_vecs)]
    sims.sort(key=lambda x: x[1], reverse=True)

    results = []
    for i, score in sims:
        if score >= threshold and len(results) < k:
            results.append(knowledge_base[i])
    return results

def search_knowledge(query):
    """调用工具，查本地知识库"""
    results = top_k_search(query, k=3, threshold=0.35)
    if not results:
        return "知识库里没找到相关内容"
    return "\n\n".join(results)