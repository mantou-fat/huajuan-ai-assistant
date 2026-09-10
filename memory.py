# -*- coding: utf-8 -*-
"""记忆库：长期记忆的读写 / 召回 / 去重合并。
状态归属：mem 是列表（共享同一对象）；_mem_embeddings、_last_merge_len 会被重新赋值，
所以必须留在本文件里（global 才有意义）。"""
import json
from config import MEMORY_FILE, VEC_CACHE_FILE, MEMORY_MERGE_EVERY
from rag import get_embedding, cosine_similarity
_mem_embeddings = None  # 记忆向量缓存，记忆变了才重算
_last_merge_len = None  # 上次合并时记忆库的长度（maybe_merge_memory 用它判断攒够没）
def retrieve_memory(query, k=4, threshold=0.35):
    """按相似度从记忆里召回最相关的几条，而不是全量塞给模型"""
    global _mem_embeddings
    mem = load_memory()
    if not mem:
        return []
    if _mem_embeddings is None:
        # 先看磁盘缓存：记忆条数没变就直接用，不用重新调接口算向量
        disk_cache = None
        try:
            with open(VEC_CACHE_FILE, "r", encoding="utf-8") as f:
                disk_cache = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            pass
        if disk_cache is not None and len(disk_cache) == len(mem):
            _mem_embeddings = disk_cache
        else:
            _mem_embeddings = get_embedding(mem)
            try:
                with open(VEC_CACHE_FILE, "w", encoding="utf-8") as f:
                    json.dump(_mem_embeddings, f)
            except OSError as e:
                print("向量缓存写盘失败（不影响功能）：", e)
    query_vec = get_embedding([query[:2000]])[0]   # 查询串太长会顶爆 embedding 接口，先截前2000字
    sims = [(i, cosine_similarity(query_vec, v)) for i, v in enumerate(_mem_embeddings)]
    sims.sort(key=lambda x: x[1], reverse=True)
    results = []
    for i, score in sims:
        if score >= threshold and len(results) < k:
            results.append(mem[i])
    return results
def load_memory():
    try:
        with open(MEMORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []
def save_memory(memory):
    global _mem_embeddings
    _mem_embeddings = None  # 记忆变了，向量缓存作废
    with open(MEMORY_FILE, "w", encoding="utf-8") as f:
        json.dump(memory, f, ensure_ascii=False, indent=2)
def delete_memory(index):
    """删除指定索引的记忆。index 先强转整数（接口可能传来 0.5、"0" 这种），转不了就返回 None"""
    global mem
    try:
        index = int(index)
    except (TypeError, ValueError):
        return None
    if 0 <= index < len(mem):
        removed = mem.pop(index)
        save_memory(mem)
        return removed
    return None
def is_duplicate(new_fact, existing_memories, threshold=0.75):
    """检查新提取的记忆是否已经存在于现有记忆中"""
    if not existing_memories:
        return False
    all_memories = existing_memories + [new_fact]
    embeddings = get_embedding(all_memories)
    new_vec = embeddings[-1]
    for vec in embeddings[:-1]:
        if cosine_similarity(new_vec, vec) >= threshold:
            return True
    return False
def judge_merge(fact_a, fact_b):
    """判断两条记忆是否记录同一件事。是→返回合并后的一句话；否→只返回"否" """
    prompt = ("下面是两条关于同一用户的长期记忆。请判断它们是否记录了同一件事。\n"
        "如果是同一件事（信息重叠），把它们合并成一句话，保留两边全部信息，用'馒头'开头。\n"
        "如果不是同一件事，只回复一个字：否\n\n"
        f"第一条：{fact_a}\n第二条：{fact_b}"
    )
    resp = client.chat.completions.create(
        model="qwen-plus",
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
        max_tokens=100
    )
last_merge_len = None      # 上次合并时记忆库的长度（记录用）
def merge_memory(threshold=0.70):
    """合并重复记忆：向量先粗筛出疑似对，再让模型精判是否同一件事"""
    mem = load_memory()
    if len(mem) < 2:
        return mem
    vecs = get_embedding(mem)
    to_remove = set()
    for i in range(len(mem)):
        if i in to_remove:
            continue
        for j in range(i + 1, len(mem)):
            if j in to_remove:
                continue
            if cosine_similarity(vecs[i], vecs[j]) < threshold:
                continue
            verdict = judge_merge(mem[i], mem[j])
            if verdict and verdict != "否":
                mem[i] = verdict
                to_remove.add(j)
    if to_remove:
        result = [m for idx, m in enumerate(mem) if idx not in to_remove]
        save_memory(result)
        return result
    return mem
def maybe_merge_memory():
    """记忆新增攒够 N 条就全库去重合并一次；失败静默，绝不打断对话"""
    global _last_merge_len
    cur = len(load_memory())
    if _last_merge_len is None:
        _last_merge_len = cur
        return
    if cur - _last_merge_len >= MEMORY_MERGE_EVERY:
        try:
            merge_memory()          # 内部会 save_memory + 清向量缓存
        except Exception as e:
            print("记忆合并失败(不影响功能):", e)
        global mem
        mem[:] = load_memory()      # 同步内存里的 mem，防止下次追加把合并结果覆盖回去
        _last_merge_len = len(mem)

# 模块级状态：全体共享同一个列表对象（bot 里 mem.append(...) 也改的是这一份）
mem = load_memory()
