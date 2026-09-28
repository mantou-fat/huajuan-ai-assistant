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
    global _kb_embeddings, _kb_graph
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
    _kb_graph = None                 # 图谱也作废
    return len(chunks)
knowledge_base = load_knowledge(KNOWLEDGE_FILE)
_kb_embeddings = None  # 知识库向量缓存，避免每次检索都重新算全库向量
_kb_graph = None       # 知识图谱缓存：{节点索引: [邻居索引...]}
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

def debug_retrieval(query, k=5, alpha=0.65):
    """算法调试用：返回 top-k 的 (文本, 综合分, 向量分, 字面分)，方便看分数调参。
    alpha 是混合权重：越大越信语义(向量)，越小越信字面(关键词)"""
    if not knowledge_base:
        return []
    query_vec = get_embedding([query])[0]
    kb_vecs = get_kb_embeddings()
    rows = []
    for i, v in enumerate(kb_vecs):
        cos = cosine_similarity(query_vec, v)
        lex = lexical_score(query, knowledge_base[i])
        rows.append((knowledge_base[i], hybrid_score(query, knowledge_base[i], query_vec, v, alpha), cos, lex))
    rows.sort(key=lambda x: x[1], reverse=True)
    return rows[:k]

def hyde_query(query):
    """HyDE：让模型脑补一段"理想答案"，拿答案去检索（答案和知识库更像）。失败返回空串。"""
    try:
        resp = client.chat.completions.create(
            model="qwen-plus",
            messages=[{"role": "user", "content": (
                "针对下面的问题，写一段简短的参考答案（120字内，直接陈述答案本身，不要客套、不要重复问题）：\n" + query
            )}],
            temperature=0.3,
            max_tokens=200,
        )
        return resp.choices[0].message.content.strip()
    except Exception:
        return ""

def gen_query_variants(query):
    """把问题改写成3个不同问法（多路召回的第一路：改写）"""
    try:
        resp = client.chat.completions.create(
            model="qwen-plus",
            messages=[{"role": "user", "content": (
                "把下面的问题改写成3个不同的、更适合检索的问法，每行一个，只输出问法本身，不要编号、不要解释：\n" + query
            )}],
            temperature=0.4,
            max_tokens=150,
        )
        return [l.strip() for l in (resp.choices[0].message.content or "").split("\n") if l.strip()][:3]
    except Exception:
        return []

def multi_recall(query, k=3, min_score=0.25):
    """多路召回：原问题 + 改写 + HyDE 各搜一遍，按综合分合并去重取前k。"""
    variants = [query] + gen_query_variants(query)
    hyde = hyde_query(query)
    if hyde:
        variants.append(hyde)
    best = {}
    for v in variants:
        for text, hybrid, cos, lex in debug_retrieval(v, k=k):
            if hybrid >= min_score and (text not in best or hybrid > best[text]):
                best[text] = hybrid
    ranked = sorted(best.items(), key=lambda x: x[1], reverse=True)
    return [t for t, _ in ranked[:k]]

def search_knowledge_smart(query, k=3):
    """智能检索：先直接搜；搜不到再 HyDE 脑补答案补搜一次，合并去重。"""
    direct = top_k_search(query, k=k)
    if direct:
        return direct
    hyde = hyde_query(query)
    if not hyde:
        return direct
    via_hyde = top_k_search(hyde, k=k)
    merged = list(direct)
    for x in via_hyde:
        if x not in merged:
            merged.append(x)
    return merged[:k]

def build_graph(top_n=5, threshold=0.50):
    """把知识库建成轻量图谱：每条知识是节点，和它最相似的 top_n 条连边。"""
    global _kb_graph
    if _kb_graph is not None:
        return _kb_graph
    kb_vecs = get_kb_embeddings()
    graph = {}
    for i in range(len(knowledge_base)):
        sims = [(j, cosine_similarity(kb_vecs[i], kb_vecs[j]))
                for j in range(len(knowledge_base)) if j != i]
        sims.sort(key=lambda x: x[1], reverse=True)
        graph[i] = [j for j, s in sims[:top_n] if s > threshold]
    _kb_graph = graph
    return graph

def graph_search(query, k=3, hops=1):
    """图谱检索：向量找种子节点，再沿图多跳扩展邻居，返回种子+邻居（给模型更全的上下文）。"""
    qv = get_embedding([query])[0]
    kb_vecs = get_kb_embeddings()
    scored = sorted(
        [(i, hybrid_score(query, knowledge_base[i], qv, v)) for i, v in enumerate(kb_vecs)],
        key=lambda x: x[1], reverse=True,
    )
    seeds = [i for i, s in scored[:k] if s >= 0.25]
    if not seeds:
        return []
    graph = build_graph()
    picked = set(seeds)
    frontier = set(seeds)
    for _ in range(hops):
        nxt = set()
        for node in frontier:
            for nb in graph.get(node, []):
                if nb not in picked:
                    picked.add(nb)
                    nxt.add(nb)
        frontier = nxt
    ordered = [knowledge_base[i] for i in seeds] + [knowledge_base[i] for i in picked if i not in seeds]
    return ordered

def check_retrieval(query, results):
    """CRAG 自检：检索结果够不够回答？够返回空串，不够返回"缺什么"。失败静默当够用。"""
    try:
        resp = client.chat.completions.create(
            model="qwen-plus",
            messages=[{"role": "user", "content": (
                "严格判断：下面的知识【直接回答】了用户的问题吗？\n"
                "用户问题：" + query + "\n检索到的知识：\n" + "\n".join(results[:5]) + "\n"
                "只有真正给出了答案才算'够用'；如果只是相关、但没回答到点子上"
                "（比如问'移植步骤'却只有'这是什么'），必须判'不够'。\n"
                "足够只回复：够用；不够回复：不够：缺XXX（一句话说缺什么）。"
            )}],
            temperature=0,
            max_tokens=60,
        )
        v = (resp.choices[0].message.content or "").strip()
        if "不够" in v:
            return v          # 先判"不够"（防止"不够用"被当成"够用"）
        if "够用" in v:
            return ""
        return v              # 说不清，保守当不够
    except Exception:
        return ""

def search_knowledge(query):
    """调用工具，查本地知识库：关系类走图谱，否则直接搜/多路召回；最后自检（CRAG）。"""
    if re.search(r"关系|联系|区别|关联|怎么影响|什么相关|和.*有关", query):
        results = graph_search(query, k=3, hops=1)[:5]
    else:
        results = top_k_search(query, k=3)
        if not results:
            results = multi_recall(query, k=3)
    if not results:
        return "知识库里没找到相关内容（可改用联网搜索补充）"
    verdict = check_retrieval(query, results)
    if verdict:
        return "知识库查到这些：\n" + "\n\n".join(results) + "\n\n【自检提示】" + verdict + "（建议联网补充）"
    return "\n\n".join(results)