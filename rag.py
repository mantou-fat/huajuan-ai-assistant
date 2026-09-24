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

def _char_bigrams(text):
    """中文按字符二元组、英文按字母二元组切，纯本地零成本的字面信号"""
    text = re.sub(r"[^\u4e00-\u9fa5A-Za-z0-9]", "", str(text).lower())
    return {text[i:i + 2] for i in range(len(text) - 1)}

def _tokens(text):
    """抽出长度>=2的字母数字词（英文术语/缩写/代码标识符），用于精确命中"""
    return {t for t in re.findall(r"[A-Za-z0-9]{2,}", str(text).lower())}

def lexical_score(query, doc):
    """字面重叠分（0~1）：字符 bigram 的 F1 + 精确词命中的加成。纯本地，零 API 成本"""
    qb, db = _char_bigrams(query), _char_bigrams(doc)
    if not qb or not db:
        base = 0.0
    else:
        inter = len(qb & db)
        recall = inter / len(qb)
        precision = inter / len(db)
        base = (2 * recall * precision / (recall + precision)) if (recall + precision) else 0.0
    qt, dt = _tokens(query), _tokens(doc)
    if qt and dt:
        hit = len(qt & dt) / len(qt)
        base = base + (1 - base) * hit * 0.5
    return min(base, 1.0)

def hybrid_score(query, doc, q_vec, d_vec, alpha=0.65):
    """语义(向量) + 字面(关键词) 加权融合。alpha 越大越偏语义，默认 0.65"""
    return alpha * cosine_similarity(q_vec, d_vec) + (1 - alpha) * lexical_score(query, doc)

def top_k_search(query, k=3, threshold=0.30, alpha=0.65, diversity=0.88):
    """混合检索：向量+字面加权 → 相对动态阈值 → MMR 去重。
    相对阈值 floor = max(绝对下限 threshold, 最高分*0.45)，比写死一个数更稳
    （不同问题的分数分布不一样）；MMR 把跟已选结果太像的跳过，保证结果多样不重复。"""
    if not knowledge_base:
        return []
    query_vec = get_embedding([query])[0]
    kb_vecs = get_kb_embeddings()
    scored = [(i, hybrid_score(query, knowledge_base[i], query_vec, v, alpha))
              for i, v in enumerate(kb_vecs)]
    scored.sort(key=lambda x: x[1], reverse=True)
    if not scored:
        return []
    floor = max(threshold, scored[0][1] * 0.45)
    picked = []
    for i, score in scored:
        if score < floor or len(picked) >= k:
            break
        if any(cosine_similarity(kb_vecs[i], kb_vecs[j]) > diversity for j, _ in picked):
            continue
        picked.append((i, score))
    return [knowledge_base[i] for i, _ in picked]

def debug_retrieval(query, k=5):
    """算法调试用：返回 top-k 的 (文本, 综合分, 向量分, 字面分)，方便看分数调参"""
    if not knowledge_base:
        return []
    query_vec = get_embedding([query])[0]
    kb_vecs = get_kb_embeddings()
    rows = []
    for i, v in enumerate(kb_vecs):
        cos = cosine_similarity(query_vec, v)
        lex = lexical_score(query, knowledge_base[i])
        rows.append((knowledge_base[i], hybrid_score(query, knowledge_base[i], query_vec, v), cos, lex))
    rows.sort(key=lambda x: x[1], reverse=True)
    return rows[:k]

def search_knowledge(query):
    """调用工具，查本地知识库"""
    results = top_k_search(query, k=3)
    if not results:
        return "知识库里没找到相关内容"
    return "\n\n".join(results)