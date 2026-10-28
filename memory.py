# -*- coding: utf-8 -*-
"""记忆库：长期记忆的读写 / 召回 / 去重合并。
状态归属：mem 是列表（共享同一对象）；_mem_embeddings、_last_merge_len 会被重新赋值，
所以必须留在本文件里（global 才有意义）。"""
import json
import time
from config import MEMORY_FILE, VEC_CACHE_FILE, MEMORY_MERGE_EVERY, MEMORY_HALF_LIFE_DAYS, MEMORY_CONSOLIDATE_AT
from sessions import current
from llm import client
from rag import get_embedding, cosine_similarity, hybrid_score

def _now():
    return time.strftime("%Y-%m-%d %H:%M:%S")

def _decay(last_str):
    """遗忘曲线：距上次想起越久，权重越低。半衰期 MEMORY_HALF_LIFE_DAYS 天。"""
    if not last_str:
        return 1.0
    try:
        from datetime import datetime
        last = datetime.strptime(last_str, "%Y-%m-%d %H:%M:%S")
        days = (datetime.now() - last).total_seconds() / 86400.0
        if days < 0:
            days = 0
        return 0.5 ** (days / MEMORY_HALF_LIFE_DAYS)
    except Exception:
        return 1.0

def retrieve_memory(query, k=4, threshold=0.30):
    """记忆召回：混合检索 × 置信度 × 重要性 × 遗忘衰减。
    PreCoMem 式：只召回当前有效（to 为空）的记忆；置信度越低排得越后。"""
    mem = load_memory()
    if not mem:
        return []
    # 只取当前有效的信念（被 CORRECT 标记失效的历史事实不参与日常召回）
    active = [m for m in mem if not m.get("to")]
    if not active:
        return []
    texts = _mem_texts(active)
    emb = current().mem_embeddings
    if emb is None or len(emb) != len(texts):
        try:
            with open(current().file("vec_cache"), "r", encoding="utf-8") as f:
                disk_cache = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            disk_cache = None
        if disk_cache is not None and len(disk_cache) == len(texts):
            emb = disk_cache
        else:
            emb = get_embedding(texts)
            try:
                with open(current().file("vec_cache"), "w", encoding="utf-8") as f:
                    json.dump(emb, f)
            except OSError as e:
                print("向量缓存写盘失败（不影响功能）：", e)
        current().mem_embeddings = emb
    q = query[:2000]
    query_vec = get_embedding([q])[0]
    scored = []
    for i, v in enumerate(emb):
        m = active[i]
        base = hybrid_score(q, texts[i], query_vec, v)
        conf = float(m.get("conf", 0.7))
        imp = float(m.get("i", 0.5))
        decay = _decay(m.get("last", ""))
        # 置信度是主导（低置信度的假设自然排后），重要性/时间做微调
        scored.append((i, base * (0.25 + 0.75 * conf) * (0.5 + 0.5 * imp) * decay))
    scored.sort(key=lambda x: x[1], reverse=True)
    if not scored:
        return []
    floor = max(threshold, scored[0][1] * 0.45)
    results = []
    recalled_idx = []
    for i, score in scored:
        if score < floor or len(results) >= k:
            break
        results.append(texts[i])
        recalled_idx.append(i)
    # 召回即强化：被想起的记忆刷新"上次想起时间"
    if recalled_idx:
        now = _now()
        changed = False
        active_by_text = {m["t"]: m for m in active}
        for i in recalled_idx:
            m = active_by_text.get(texts[i])
            if m is not None and m.get("last") != now:
                m["last"] = now
                changed = True
        if changed:
            # 写回完整 mem（active 是 mem 里的同一批 dict 对象，引用保持一致）
            save_memory(mem)
    return results
def load_memory():
    try:
        with open(current().file("memory"), "r", encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []
    # 迁移：老格式是纯字符串，统一包成 {"t": 文本, "i": 重要性, "last": 上次想起时间}
    # 新版：再加 type(FACT/HYPOTHESIS) / conf(置信度) / hits / contra / from / to
    now = _now()
    out = []
    for m in data:
        if isinstance(m, dict) and "t" in m:
            out.append(_normalize(m, now))
        else:
            out.append(_normalize({"t": str(m)}, now))
    return out


def _normalize(m, now=None):
    """把任意版本的记忆条目补齐成新版字段（幂等）"""
    now = now or _now()
    d = {
        "t": str(m.get("t", "")),
        "type": m.get("type", "FACT"),
        "conf": float(m.get("conf", 0.7)),
        "i": float(m.get("i", 0.5)),
        "last": m.get("last", now),
        "hits": int(m.get("hits", 0)),
        "contra": int(m.get("contra", 0)),
        "from": m.get("from", now),
        "to": m.get("to"),
    }
    return d

def _mem_texts(mem):
    """从记忆列表里抽出纯文本（用于 embedding 和返回给模型）"""
    return [m["t"] if isinstance(m, dict) else str(m) for m in mem]

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
    new_text = new_fact["t"] if isinstance(new_fact, dict) else str(new_fact)
    texts = _mem_texts(existing_memories) + [new_text]
    embeddings = get_embedding(texts)
    new_vec = embeddings[-1]
    for vec in embeddings[:-1]:
        if cosine_similarity(new_vec, vec) >= threshold:
            return True
    return False


# ===== PreCoMem 式三态更新 =====
# MAINTAIN：新证据支持已有信念 → 抬置信度
# PROFILE：证据模糊 → 存成低置信度 HYPOTHESIS（等待室），攒够了才升级 FACT
# CORRECT：被可靠证据反驳 → 旧事实软衰减（降置信度 + 标记失效），不删除

CONF_INIT_FACT = 0.75       # 新事实初始置信度
CONF_INIT_HYPO = 0.35       # 新假设初始置信度
CONF_PROMOTE = 0.72         # HYPOTHESIS 升级成 FACT 的门槛
CONF_CORRECT_DECAY = 0.45   # 被反驳时旧事实的置信度乘数
SIM_SAME = 0.82             # 相似度 ≥ 此值：认为是同一件事
SIM_RELATED = 0.55          # 相似度在 [此值, SIM_SAME)：相关但可能矛盾


def _same_text(a, b):
    """去掉标点空白和数字差异后，判断两句是不是"同一句"。
    注意：只有内容和数字都一致才算 same；数字不同（如生日 3/5 vs 3/8）不算。"""
    import re as _re
    def norm(s):
        s = _re.sub(r"[\s，。！？、,.!?；;：:'\"“”‘’（）()\[\]【】]", "", str(s))
        return s
    return norm(a) == norm(b)


def apply_update(new_text, evidence, importance=0.5):
    """把一条新抽取的事实并入记忆库，返回 (action, 说明)。
    evidence: 0~1，模型给的"证据强度"（这句话有多确定）
    action: maintain / profile / correct / add_fact
    """
    mem = load_memory()
    mem = [_normalize(m) for m in mem]
    now = _now()

    if not mem:
        item = _normalize({"t": new_text, "type": "FACT" if evidence >= 0.6 else "HYPOTHESIS",
                           "conf": CONF_INIT_FACT if evidence >= 0.6 else CONF_INIT_HYPO,
                           "i": importance, "last": now, "hits": 1, "from": now})
        mem.append(item)
        save_memory(mem)
        return ("add_fact" if item["type"] == "FACT" else "profile", new_text)

    # 找最相似的已有记忆
    texts = _mem_texts(mem)
    vecs = get_embedding(texts + [new_text])
    new_vec = vecs[-1]
    sims = [cosine_similarity(new_vec, v) for v in vecs[:-1]]
    best_i = max(range(len(sims)), key=lambda i: sims[i]) if sims else -1
    best_sim = sims[best_i] if best_i >= 0 else 0.0

    # ① 高度相似 → 可能是同一件事，也可能是同一属性的不同值（矛盾）
    #    所以不能直接 MAINTAIN，要再判一次"文本是否真的一致"
    if best_i >= 0 and best_sim >= SIM_SAME:
        it = mem[best_i]
        # 文本几乎一致（去掉标点空白后相同）→ 才是真正的 MAINTAIN
        if _same_text(it["t"], new_text):
            it["hits"] += 1
            it["conf"] = min(1.0, it["conf"] + 0.12 * evidence)
            it["last"] = now
            it["i"] = max(it["i"], importance)
            if it["type"] == "HYPOTHESIS" and it["conf"] >= CONF_PROMOTE:
                it["type"] = "FACT"
            save_memory(mem)
            return ("maintain", it["t"])
        # 文本不同 → 让模型判断是补充还是矛盾
        verdict = _judge_relation(it["t"], new_text)
        if verdict == "conflict" and evidence >= 0.6:
            it["contra"] += 1
            it["conf"] = round(it["conf"] * CONF_CORRECT_DECAY, 3)
            it["to"] = now
            it["last"] = now
            new_item = _normalize({"t": new_text, "type": "FACT",
                                   "conf": CONF_INIT_FACT, "i": importance,
                                   "last": now, "hits": 1, "from": now})
            mem.append(new_item)
            save_memory(mem)
            return ("correct", it["t"])
        elif verdict == "support":
            it["hits"] += 1
            it["conf"] = min(1.0, it["conf"] + 0.08 * evidence)
            it["last"] = now
            save_memory(mem)
            return ("maintain", it["t"])

    # ② 中度相似 → 相关内容：判断是"补充"还是"矛盾"
    if best_i >= 0 and best_sim >= SIM_RELATED:
        it = mem[best_i]
        # 模型判断：这条新信息是在补充/细化旧事实，还是和它冲突
        verdict = _judge_relation(it["t"], new_text)
        if verdict == "conflict" and evidence >= 0.6:
            # CORRECT：旧事实软衰减 + 标记失效（不删除）
            it["contra"] += 1
            it["conf"] = round(it["conf"] * CONF_CORRECT_DECAY, 3)
            it["to"] = now
            it["last"] = now
            # 新事实作为新的当前事实加入
            new_item = _normalize({"t": new_text, "type": "FACT",
                                   "conf": CONF_INIT_FACT if evidence >= 0.6 else CONF_INIT_HYPO,
                                   "i": importance, "last": now, "hits": 1, "from": now})
            mem.append(new_item)
            save_memory(mem)
            return ("correct", it["t"])
        elif verdict == "support":
            it["hits"] += 1
            it["conf"] = min(1.0, it["conf"] + 0.08 * evidence)
            it["last"] = now
            save_memory(mem)
            return ("maintain", it["t"])

    # ③ 不相似 → 新信息：证据强走 FACT，证据弱进 PROFILE 等待室
    item = _normalize({
        "t": new_text,
        "type": "FACT" if evidence >= 0.6 else "HYPOTHESIS",
        "conf": CONF_INIT_FACT if evidence >= 0.6 else CONF_INIT_HYPO,
        "i": importance, "last": now, "hits": 1, "from": now,
    })
    mem.append(item)
    save_memory(mem)
    return ("add_fact" if item["type"] == "FACT" else "profile", new_text)


def _judge_relation(old_fact, new_fact):
    """判断新信息与旧事实的关系：support（补充/细化）/ conflict（矛盾）/ unrelated"""
    prompt = (
        "判断下面两句话的关系，只回复一个词：support、conflict 或 unrelated。\n"
        "support = 新信息与旧事实一致或补充细化它\n"
        "conflict = 新信息与旧事实互相矛盾（同一件事出现了不同答案）\n"
        "unrelated = 两句话讲的是不同的事\n"
        "不要解释，只输出一个词。\n\n"
        f"旧事实：{old_fact}\n新信息：{new_fact}"
    )
    try:
        resp = client.chat.completions.create(
            model="qwen-plus",
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=10,
        )
        v = (resp.choices[0].message.content or "").strip().lower()
        for k in ("conflict", "support", "unrelated"):
            if k in v:
                return k
    except Exception as e:
        print("关系判断失败（不影响功能）:", e)
    return "unrelated"
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
    texts = _mem_texts(mem)
    vecs = get_embedding(texts)
    to_remove = set()
    for i in range(len(mem)):
        if i in to_remove:
            continue
        for j in range(i + 1, len(mem)):
            if j in to_remove:
                continue
            if cosine_similarity(vecs[i], vecs[j]) < threshold:
                continue
            verdict = judge_merge(texts[i], texts[j])
            if verdict and verdict != "否":
                # 合并后保留两条里更高的重要性
                hi = max(mem[i].get("i", 0.5), mem[j].get("i", 0.5))
                mem[i] = {"t": verdict, "i": hi}
                to_remove.add(j)
    if to_remove:
        result = [m for idx, m in enumerate(mem) if idx not in to_remove]
        save_memory(result)
        return result
    return mem
def consolidate_memory():
    """记忆整理：记忆攒多了，让模型把相关的归纳成更高级结论，删重复和琐碎。
    少于 MEMORY_CONSOLIDATE_AT 条不动；失败静默返回原样，绝不崩主流程。"""
    mem = load_memory()
    if len(mem) < MEMORY_CONSOLIDATE_AT:
        return mem
    texts = _mem_texts(mem)
    prompt = ("下面是花卷记住的关于用户的事，共%d条。请把它们归纳整理：\n"
        "1. 把相关的合并成一条更高级的结论（例：'爱喝冰可乐'+'爱吃辣' → '口味偏重，爱碳酸饮料和辣食'）；\n"
        "2. 删掉重复的和鸡毛蒜皮的；\n"
        "3. 重要的具体信息（生日、约定、偏好）要保留。\n"
        "每条一行，格式：'事实|重要性'，重要性1~10（10=极其重要）。只输出整理后的清单，不要解释、不要编号。\n\n"
        % len(mem) + "\n".join(texts))
    resp = client.chat.completions.create(
        model="qwen-plus",
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
        max_tokens=600,
    )
    raw = (resp.choices[0].message.content or "").strip()
    if not raw:
        return mem
    now = _now()
    new_mem = []
    for line in raw.split("\n"):
        line = line.strip().lstrip("-•· ").strip()
        if not line:
            continue
        fact, imp = line, 0.5
        if "|" in line:
            left, _, right = line.partition("|")
            fact = left.strip()
            try:
                imp = max(0.0, min(1.0, float(right.strip()) / 10.0))
            except ValueError:
                imp = 0.5
        if fact:
            new_mem.append({"t": fact, "i": imp, "last": now})
    if new_mem:
        save_memory(new_mem)
        return new_mem
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
        try:
            consolidate_memory()    # 条数够多就归纳整理（内部有阈值，不够自动跳过）
        except Exception as e:
            print("记忆整理失败(不影响功能):", e)
        mem = current().mem
        mem[:] = load_memory()      # 同步内存里的 mem，防止下次追加把合并结果覆盖回去
        current().last_merge_len = len(mem)
# 模块级状态：全体共享同一个列表对象（bot 里 mem.append(...) 也改的是这一份）
mem = current().mem
mem[:] = load_memory()
