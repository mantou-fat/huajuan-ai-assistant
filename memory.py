# -*- coding: utf-8 -*-
"""记忆库：长期记忆的读写 / 召回 / 去重合并。
状态归属：mem 是列表（共享同一对象）；_mem_embeddings、_last_merge_len 会被重新赋值，
所以必须留在本文件里（global 才有意义）。"""
import json
from config import MEMORY_FILE, VEC_CACHE_FILE, MEMORY_MERGE_EVERY
from sessions import current
from llm import client
from rag import get_embedding, cosine_similarity, hybrid_score

def retrieve_memory(query, k=4, threshold=0.30):
    """记忆召回：混合检索(向量+字面) + 相对动态阈值，比纯余弦更稳"""
    mem = load_memory()
    if not mem:
        return []
    emb = current().mem_embeddings
    if emb is None:
        disk_cache = None
        try:
            with open(current().file("vec_cache"), "r", encoding="utf-8") as f:
                disk_cache = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            pass
        if disk_cache is not None and len(disk_cache) == len(mem):
            emb = disk_cache
        else:
            emb = get_embedding(mem)
            try:
                with open(current().file("vec_cache"), "w", encoding="utf-8") as f:
                    json.dump(emb, f)
            except OSError as e:
                print("向量缓存写盘失败（不影响功能）：", e)
        current().mem_embeddings = emb
    q = query[:2000]
    query_vec = get_embedding([q])[0]
    scored = [(i, hybrid_score(q, mem[i], query_vec, v)) for i, v in enumerate(emb)]
    scored.sort(key=lambda x: x[1], reverse=True)
    if not scored:
        return []
    floor = max(threshold, scored[0][1] * 0.45)
    results = []
    for i, score in scored:
        if score < floor or len(results) >= k:
            break
        results.append(mem[i])
    return results
def load_memory():
    try:
        with open(current().file("memory"), "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []

def save_memory(memory):
    current().mem_embeddings = None   # 记忆变了，向量缓存作废（原来是 global _mem_embeddings = None）
    with open(current().file("memory"), "w", encoding="utf-8") as f:
        json.dump(memory, f, ensure_ascii=False, indent=2)
def delete_memory(index):
    """删除指定索引的记忆。index 先强转整数（接口可能传来 0.5、"0" 这种），转不了就返回 None"""
    mem = current().mem
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
    cur_len = current().last_merge_len
    cur = len(load_memory())
    if cur_len is None:
        current().last_merge_len = cur
        return
    if cur - cur_len >= MEMORY_MERGE_EVERY:
        try:
            merge_memory()          # 内部会 save_memory + 清向量缓存
        except Exception as e:
            print("记忆合并失败(不影响功能):", e)
        mem = current().mem
        mem[:] = load_memory()      # 同步内存里的 mem，防止下次追加把合并结果覆盖回去
        current().last_merge_len = len(mem)
# 模块级状态：全体共享同一个列表对象（bot 里 mem.append(...) 也改的是这一份）
mem = current().mem
mem[:] = load_memory()
