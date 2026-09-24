import os
import json
import re
import time
import hashlib
import queue      
import threading 
from concurrent.futures import ThreadPoolExecutor  # 第3课：多手下并行干活靠它
from sessions import current
from lang_quality import check_typos, check_redline, check_typos_llm
import requests
import base64
from openai import OpenAI
import numpy as np
from bs4 import BeautifulSoup
# 配置搬家：纯配置统一从 config.py 读（重构第一步，只搬位置不改逻辑）
from config import (REMINDER_FILE, KNOWLEDGE_FILE, HISTORY_FILE, MEMORY_FILE, VEC_CACHE_FILE,
                    STATUS_FILE, MOOD_FILE, EXPENSE_FILE, SUMMARY_FILE, HOME_FILE, AUDIT_FILE,
                    RETRYABLE_TOOLS, VALIDATORS, FILES_DIR, READ_DIRS, PROGRAM_LIST,
                    PROGRAM_NAMES, EXCLUDE_FILES, MAX_MESSAGES, MEMORY_MERGE_EVERY,
                    KB_STRONG, KB_WEAK)
# 规则引擎搬家：纯规则函数从 rules.py 读（重构第二步，行为零变化）
from rules import (clean_aside, looks_like_vision, knowledge_hit_level, detect_hard_tool,
                   parse_remind_time, REMINDER_HINT, FILEBOX_HINT, LOCK_HINT,
                   CONFIRM_WORDS, REMINDER_EDIT_HINT)
from dotenv import load_dotenv
# 共享资源与 RAG 搬家（重构第三步，行为零变化）
from llm import client, api_key, tavily_key, bjs_key, workspace_id
from rag import (split_long_text, load_knowledge, add_knowledge, knowledge_base,
                 get_embedding, get_kb_embeddings, cosine_similarity,
                 top_k_search, search_knowledge)
# 记忆搬家（重构第四步，行为零变化）
from memory import (mem, load_memory, save_memory, delete_memory, retrieve_memory,
                    is_duplicate, judge_merge, merge_memory, maybe_merge_memory)
# ===== 重构第五、六步：人设/状态 → persona_state.py，工具层 → tools.py =====
# bot.py 现在只剩"编排层"：记忆/历史/流式调用/工具循环/审计。
from persona_state import (SYSTEM_PROMPT, IDENTITY, load_status, save_status, update_status,
                           load_mood, save_mood, update_mood, mood_shift,
                           load_seen, save_seen, get_greeting)
from tools import (TOOLS, TOOL_FUNCS, AGENTS, 
                   get_time, get_weather, set_reminder, set_expense, query_expenses,
                   load_expenses, save_expenses, expense_summary,
                   load_reminders, save_reminders, check_reminders,
                   read_webpage, read_webpage_browser, list_files, read_file, write_file,
                   safe_read_path, safe_write_path, web_search, generate_song,
                   set_timer, open_app, create_reminder, open_program, take_screenshot,
                   lock_screen, search_knowledge, dispatch_agent, look_around,
                   control_device, tts)
# ---- 运行时状态：只在本模块使用，不放 config（配置）也不放 rules（纯规则）----
_audit_lock = threading.Lock()   # 多线程并发写审计日志要加锁，防止两行搅在一起
       
chat_lock = threading.Lock()
# 第18个工具：子AI名册（给手下上编制）。每个成员的"专长"= 它的 system 人设
# ============ 第4课 map-reduce：大任务拆给手下分头干 ============
def map_phase(blocks):
    """map（拆分干活阶段）：每块派一个资料员并行提炼要点，谁都不等谁"""
    def work(i, block):
        resp = client.chat.completions.create(
            model="qwen-plus",
            messages=[
                {"role": "system", "content": AGENTS["资料员"]},
                {"role": "user", "content": "请提取下面这段文本的要点，只输出要点本身，不要复述原文：\n" + block},
            ],
            temperature=0.3,            # 总结类活温度要低，稳字当头
            max_tokens=1500,
        )
        return f"【第{i + 1}块】" + (resp.choices[0].message.content or "").strip()
    with ThreadPoolExecutor(max_workers=4) as pool:   # 线程池是第3课的地基，直接复用
        results = list(pool.map(work, range(len(blocks)), blocks))
    return "\n".join(r for r in results if r)
def auto_map_reduce(text):
    """第4课入口：长文(≥3000字)+总结意图 且 没点名派手下 → 拆块并行总结，返回注入素材；否则返回空串。
    reduce（合并阶段）交给主模型：它拿到各块摘要，去重整理成对用户的最终回答——老板干合并，手下干拆活。
    阈值 3000 是实测校准：qwen-plus 单次啃 1600 字也能 6/6 全覆盖（拆了白拆还烧钱），
    真到 3000+ 字注意力才开始衰减，那时候拆才划算"""
    if len(text) < 3000:
        return ""
    if not any(kw in text for kw in ("总结", "整理", "概括", "要点", "摘要", "归纳", "提炼")):
        return ""
    if re.search(r'(派|找|叫|请|让)(翻译官|文案师|资料员|代码员|个AI|手下)', text):
        return ""                       # 点名派手下走 dispatch_agent，两套机制不抢活
    blocks = split_long_text(text, 800)
    if len(blocks) < 2:
        return ""
    digest = map_phase(blocks)
    return ("\n\n【长文分块总结】原文太长，已拆成%d块让资料员们并行整理，各块摘要如下：\n%s\n"
            "（请基于以上分块摘要回答用户的问题：把重复的要点合并，按用户要求的格式输出最终答案，别逐字啃原文）"
            % (len(blocks), digest))
def create_stream(messages, tools=TOOLS,on_text=None,model="qwen-plus", tool_choice="auto"):
    stream = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=0.8,
        max_tokens=4000,
        top_p=0.9,
        tools=tools,
        tool_choice=tool_choice,
        stream=True
    )
    content = ""
    pieces = {}
    finish = None
    for chunk in stream:
        ch = chunk.choices[0]
        if ch.delta.content:
            content += ch.delta.content
            if on_text:
                on_text(clean_aside(ch.delta.content))
        if ch.delta.tool_calls:
            for tc in ch.delta.tool_calls:
                p = pieces.setdefault(tc.index, {"id": "", "name": "", "args": ""})
                if tc.id:
                    p["id"] = tc.id
                if tc.function.name:
                    p["name"] += tc.function.name
                if tc.function.arguments:
                    p["args"] += tc.function.arguments
        if ch.finish_reason:
            finish = ch.finish_reason
    tcs = [
        {
            "id": p["id"], "type": "function",
            "function": {"name": p["name"], "arguments": p["args"]}
        }
        for _, p in sorted(pieces.items())
    ]
    return {"content": content, "tool_calls": tcs, "finish_reason": finish}
def load_history():
    try:
        with open(current().file("history"), "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return [{"role": "system", "content": SYSTEM_PROMPT}]

def save_history(messages):
    with open(current().file("history"), "w", encoding="utf-8") as f:
        json.dump(messages, f, ensure_ascii=False, indent=2)

def clear_history():
    global messages
    with chat_lock:
        messages[:] = [{"role": "system", "content": SYSTEM_PROMPT}]
        # 清空对话后重新注入近况和记忆，否则花卷会"失忆"到下次重启
        s = load_status()
        if s.get("status"):
            messages.append({"role": "system", "content": "花卷的近况：" + s["status"]})
        n = load_mood()
        if n.get("mood"):
            messages.append({"role": "system", "content": "花卷的心情：" + n["mood"]})
        save_history(messages)
        print("对话历史已清空。")
def extract_memory(user_input, reply):
    """从这段记忆中提取长期记忆的事情，没有就返回空"""
    prompt = ("下面是用户和你的对话。请只提取'关于用户的、值得长期记住的事实'，"
        "比如喜好、生日、约定、经历。如果有，用一句话、第三人称说出来（如：馒头怕打雷）。"
        "没有就只回复两个字：无\n\n"
        f"用户：{user_input}\n花卷：{reply}"
    )
    resp = client.chat.completions.create(
        model="qwen-plus",
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
        max_tokens=100
    )
    facts = resp.choices[0].message.content.strip()
    if facts and facts != "无":
        return facts
    return ""
def load_summary():
    try:
        with open(current().file("summary"), "r", encoding="utf-8") as f:
            data = json.load(f)
            return {"summary": data.get("summary", ""), "pending": data.get("pending", [])}
    except (FileNotFoundError, json.JSONDecodeError):
        return {"summary": "", "pending": []}
def save_summary(text, pending):
    with open(SUMMARY_FILE, "w", encoding="utf-8") as f:
        json.dump({"summary": text, "pending": pending, "updated": time.strftime("%Y-%m-%d")}, f, ensure_ascii=False, indent=2)
def compress_history(dropped_msgs):
    """丢掉的旧对话先攒进 pending 待办本，攒够一批才压缩一次"""
    data = load_summary()
    pending = data["pending"] + [m["content"] for m in dropped_msgs if m["role"] in ("user", "assistant")]
    if len(pending) < 10:
        save_summary(data["summary"], pending)   # 没攒够：只记账，不调 LLM
        return
    transcript = "\n".join(pending)
    old = data["summary"]
    if old:
        text = "旧摘要：\n" + old + "\n\n新增对话：\n" + transcript
    else:
        text = transcript
    prompt = ("请把下面的内容整理成条目式摘要，每条一行、以-开头，保留：用户的重要信息（喜好/生日/约定/经历）、"
              "聊过的关键话题、没聊完的事。总长不超过400字。直接输出摘要正文，不要客套。\n\n" + text)
    resp = client.chat.completions.create(
        model="qwen-plus",
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
        max_tokens=600,
    )
    new = resp.choices[0].message.content.strip()
    if new:
        save_summary(new, [])
    return resp.choices[0].message.content.strip()
def is_knowledge_question(user_input):
    """判断用户是在闲聊还是在问知识库"""
    prompt = (
        "判断下面这句话的意图。如果是在查资料、问知识、问事实（比如'什么是RAG''python怎么读文件'），"
        "回复'查资料'。如果是闲聊、问候、情感交流、个人话题（比如'你好''你今天干嘛了''我不开心'），"
        "回复'闲聊'。注意：问时间、问天气、记账、设提醒这类你自己能查能办的事，也算'闲聊'，交给工具处理。只回复这三个字，不要多说。\n\n"
        f"用户：{user_input}"
    )
    resp = client.chat.completions.create(
        model="qwen-plus",
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
        max_tokens=10
    )
    result = resp.choices[0].message.content.strip()
    return "查资料" in result
def after_reply_jobs(user_input, full_reply):
    """幕后活：提取记忆 + 更新心情，丢给后台线程慢慢跑"""
    try:
        # 1. 提取记忆
        new = extract_memory(user_input, full_reply)
        if new and not is_duplicate(new, mem):
            mem.append(new)
            save_memory(mem)
            save_memory(mem)
            maybe_merge_memory()      # ← 加这行：新增记忆后检查是否该合并
        # 2. 心情会流动
        new_mood_raw = mood_shift(user_input, full_reply)
        new_mood = new_mood_raw.strip().rstrip("。.!！~～").strip()
        current_mood = (load_mood().get("mood", "") or "").strip().rstrip("。.!！~～").strip()
        if new_mood and new_mood != "无" and new_mood != current_mood:
            with chat_lock:  # 改共享的 messages，拿锁防冲突
                for m in messages:
                    if m["role"] == "system" and m["content"].startswith("花卷的心情："):
                        m["content"] = "花卷的心情：" + new_mood_raw
                        break
            data = load_mood()
            data["mood"] = new_mood_raw
            data["updated"] = time.strftime("%Y-%m-%d")
            save_mood(data)
    except Exception as e:
        print("幕后任务失败：", e)
# ===== 知识题硬性判断：规则引擎（关键词匹配，确定性，不会看走眼）=====
# 知识题关键词分两级：
#   STRONG = 术语类，命中基本就是查资料 → 直接注入（省一次 LLM）
#   WEAK   = 泛词，可能闲聊也可能真问 → 需要 LLM 复核一次
# ===== 知识题硬性判断：规则引擎（关键词匹配，确定性，不会看走眼）=====
# 关键词分两级：STRONG = 术语类命中基本就是查资料→直接注入；WEAK = 泛词可能闲聊→LLM 复核
def audit_log(action, args, result, ok=True):
    """把一次工具调用记进 audit.log：时间/动作/参数/结果/成败（一行一条 JSON）。
    模块级函数 + 写锁：run_one（多线程）里任何出口都能安全调用它"""
    try:
        with _audit_lock:
            with open(AUDIT_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps({
                    "time": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "action": action,
                    "args": args,
                    "result": str(result)[:200],   # 截断防日志无限大
                    "ok": ok,
                }, ensure_ascii=False) + "\n")
    except Exception:
        pass    # 审计失败绝不能影响主流程
def think_about(user_msg):
    """先想一步：一句话说清用户真实意图 + 回复要注意的点。失败静默返回空串。"""
    try:
        resp = client.chat.completions.create(
            model="qwen-plus",
            messages=[{"role": "user", "content": (
                "分析下面这句话：用户真正想要什么、有没有反话/潜台词/歧义、回复时要注意什么。"
                "用一句话总结，不超过40字，直接给结论，别客套。\n\n" + user_msg[:200]
            )}],
            temperature=0, max_tokens=60,
        )
        return resp.choices[0].message.content.strip()
    except Exception:
        return ""
def get_reply(user_input, print_stream=False, on_text=None, on_tool=None, image=None):
    """输入问题，返回回答。print_stream=True 时边生成边打印（命令行用）"""
    # 防御：接口传进来的不一定是字符串
    user_input = str(user_input) if user_input is not None else ""
    current().phone_actions.clear()
    with chat_lock:  # 防止多线程并发时 messages 串话
        user_msg = user_input
        # 错别字识别：先词典(免费快)再 LLM(认词典外的)，认出后按正字理解，回复自然（别当面挑用户错字）
        _typos = check_typos(user_msg)
        if not _typos:
            _typos = check_typos_llm(user_msg)
        if _typos:
            user_msg += "\n\n【用户错别字】" + "、".join(_typos) + "（按正字理解，回复自然即可）"
        # 知识题硬性兜底：命中关键词就强制检索并注入资料，模型没有"不查"的选项
                # 知识题两级路由：强词直接注入；弱词让 LLM 复核是不是真查资料（救活 is_knowledge_question）
        kb_level = knowledge_hit_level(user_msg)
        if kb_level == "strong":
            need_kb = True
        elif kb_level == "weak":
            try:
                need_kb = is_knowledge_question(user_msg)
            except Exception:
                need_kb = False        # 复核失败宁可不注入，别误伤闲聊
        else:
            need_kb = False
        if need_kb:
            try:
                kb = top_k_search(user_msg, k=2)     # 断网/DNS 失败时不能让整轮聊天崩
            except Exception as e:
                print("知识库检索失败(跳过注入,不影响聊天):", e)
                kb = []
            if kb:
                labeled = [f"#{knowledge_base.index(t) + 1} {t}" for t in kb]
                user_msg += "\n\n【知识库资料】\n" + "\n".join(labeled) + \
                    "\n（引用要求：答案若依据知识库，句末用（知识库#N）标出处，N 用上面出现的编号。示例：system消息用于设定对话角色和规则（知识库#11）。没有依据的内容不许标号、不许编编号。）"
        # 第4课 map-reduce 兜底：超长文本+总结意图 → 自动拆块并行派资料员，把各块摘要注入给主模型合并。
        # 同款思路：模型没有"硬啃长文"的选项——它拿到的已经是手下们嚼碎喂好的料
        mr_note = auto_map_reduce(user_msg)
        map_reduce_triggered = bool(mr_note)   # 新增：记录本轮是否走了 map-reduce
        if mr_note:
            user_msg += mr_note
    if image:
        messages.append({"role": "user", "content": "[图片] " + user_msg})
    else:
        messages.append({"role": "user", "content": user_msg})
    system_msg = [m for m in messages if m["role"] == "system"]
    summary = load_summary()
    if summary.get("summary"):
            system_msg = system_msg + [{"role": "system", "content": "更早对话的摘要：\n" + summary["summary"]}]
    # 先想一步：注入本轮意图分析，让主模型回复前先理解用户（像人一样思考）
    _think = think_about(user_msg)
    if _think:
        system_msg = system_msg + [{"role": "system", "content": "【先想一步】" + _think}]
    non_system = [m for m in messages if m["role"] != "system"]
                # RAG 记忆召回：每轮按当前问题现场检索，只带相关的，用完即扔不进 history
    # 召回失败（如接口临时出错）不能弄崩整轮聊天：降级成"没召回"继续聊
    try:
        recalled = retrieve_memory(user_input, k=3, threshold=0.55)
    except Exception:
        recalled = []
    if recalled:
            system_msg = system_msg + [{"role": "system", "content": "跟当前问题相关的记忆：\n" + "\n".join(recalled)}]
    # 点名派手下兜底：命中"派翻译官/找文案师/派个AI"等说法就注入本轮回合强指令。
    # 放 system 消息（模型对 system 的遵循优先级高于 user 正文里夹带），且只在本轮生效不污染 history
    # map-reduce 兜底：模型嘴硬/格式跑偏时，用 system 强制拉回来
    if map_reduce_triggered:
        system_msg = system_msg + [{"role": "system", "content": "【本轮回合强制指令】文章已触发 map-reduce：资料员已将长文分块并返回【第N块】摘要。你的任务：①将上述分块摘要整理成结构化的要点列表（用序号 1. 2. 3. 或 - 项目符号输出），禁止写成读后感或情绪回应；②若用户询问处理方式，必须如实回答'文章较长，我切成了N块让资料员分头总结，再合并给你'；③禁止编造'自己一页页读''没分块''没派手下'等说法。"}]
    if re.search(r'(派|找|叫|请|让)(翻译官|文案师|资料员|代码员|个AI|手下)', user_input):
        system_msg = system_msg + [{"role": "system", "content": "【本轮回合强制指令】馒头点名要派手下：你必须调用 dispatch_agent 工具，从名册里挑对的人（翻译官/文案师/资料员/代码员）。一次派多个手下时，必须为每个手下各发一次 dispatch_agent 调用，一个都不许漏。等所有子AI结果都回来后，按顺序逐条贴出每个结果的内容本体（译文念译文、文案贴文案、要点逐条列），每条前加【翻译官】【文案师】这类标签；有几个结果就贴几条，禁止漏贴、禁止只点评不转述、禁止说'都转给你了/收着啦'却没贴内容。禁止自己代劳翻译/写作/总结。"}]
    tail = non_system[-MAX_MESSAGES:]
    if image:
        tail[-1] = {"role": "user", "content": [
            {"type": "text", "text": user_msg},
            {"type": "image_url", "image_url": {"url": image}}
        ]}
    messages_to_send = system_msg + tail
    vision_hit = looks_like_vision(user_input)
    force_tool = "auto"
    if vision_hit:
        force_tool = {"type": "function", "function": {"name": "look_around"}}
        # 本回合强制指令：让她知道工具返回的就是亲眼所见，必须照实说
        system_msg = system_msg + [{"role": "system", "content": "【本回合强制指令】用户想让你看摄像头画面：你必须调用 look_around 工具；工具返回的内容就是你亲眼看到的真实画面，回答必须完全基于它，用你的口吻讲给馒头听。禁止说'我看不到''逗你的''信号不好'等否认的话，也不要干巴巴复读工具结果。"}]
    else:
        # 锁屏两段式：① 第一次要锁 → 禁止调工具，只问确认 ② 用户点头 → 这回合强制真锁
        # ③ 岔开话题 → 确认作废。顺序很关键：先看点头，再看要锁，最后才是普通硬路由
        if current().pending_lock[0] and CONFIRM_WORDS.match(user_input.strip()):
            current().pending_lock[0] = False
            force_tool = {"type": "function", "function": {"name": "lock_screen"}}
            system_msg = system_msg + [{"role": "system", "content": "【本回合强制指令】用户已确认锁屏：立即调用 lock_screen 工具，等工具真实返回结果后按结果回答。"}]
        elif LOCK_HINT.search(user_input):
            current().pending_lock[0] = True
            system_msg = system_msg + [{"role": "system", "content": "【本回合强制指令】用户想锁屏：本回合禁止调用任何工具，先用花卷的口吻问一句确认（比如桌上东西存好了没）。等用户下一回合明确说'确认/锁吧'后再执行。"}]
        else:
            current().pending_lock[0] = False
            hard_tool = detect_hard_tool(user_input)
            if hard_tool:
                force_tool = {"type": "function", "function": {"name": hard_tool}}
                # 数据型/动作型工具强指令：先调工具拿真实结果再回答，禁止凭空编
                system_msg = system_msg + [{"role": "system", "content": f"【本回合强制指令】你判断用户需要真实动作/数据：必须先把 {hard_tool} 工具调用起来，等工具真实返回结果后，再基于结果用花卷的口吻回答。禁止跳过工具凭空编造——时间、天气、金额、账目，以及'已打开/已截屏/已锁屏'这类执行结果，一律不许编。工具返回什么就如实说什么，执行失败就如实说失败。"}]
    # 设提醒/文件盒：不锁死工具名，但注入强指令，防止"嘴上说做了/凭记忆报文件名"
    if REMINDER_HINT.search(user_input):
        abs_time = parse_remind_time(user_input)   # 时间能算出来 → 硬路由，不许再问
        if abs_time:
            force_tool = {"type": "function", "function": {"name": "set_reminder"}}
            system_msg = system_msg + [{"role": "system", "content": f"【本回合强制指令】用户要设本地提醒，时间已由系统换算好：绝对时间 {abs_time}。立即调用 set_reminder 写入：remind_time 填 {abs_time}，content 从用户话里提炼要提醒的事（如'开会'）。禁止反问确认、禁止只调 get_time 不写入；工具返回成功后再用花卷口吻回复用户。"}]
        else:
            system_msg = system_msg + [{"role": "system", "content": "【本回合强指令】用户要设本地提醒(set_reminder)：先调 get_time 拿今天日期换算成 YYYY-MM-DD HH:MM，紧接着调 set_reminder 写入再回复；时间不完整（没说几点/哪天）就先问清楚。没真正写入成功不许说'已设好/已记住'。"}]
    if FILEBOX_HINT.search(user_input):
        system_msg = system_msg + [{"role": "system", "content": "【本回合强指令】用户涉及文件盒/项目文件：先调用 list_files / read_file / write_file 工具拿到真实清单或内容再回答，禁止凭记忆编造文件名或文件内容。read_file 只传文件名，不带路径。"}]
    if REMINDER_EDIT_HINT.search(user_input) and re.search(r"改成|改到|换成|改为|提前|推迟|调成|改一?下", user_input):
        system_msg = system_msg + [{"role":"system","content":"【本回合强指令】用户想【修改】已有提醒：目前没有直接修改的工具。你必须先如实说明'不能直接改，只能删掉旧的重新设一条'，并问用户要不要按新时间重设。禁止没调用工具就说'已改好/改到X点'。"}]
    messages_to_send = system_msg + tail
    failed = False
    turn_tools = []# 本轮依次调过的工具名（整轮审计用）
    steps = 0            # ← 新增：轮数计数提前到 try 外面（异常时也有定义）  
    try:
            base = len(messages)
            result = create_stream(messages_to_send, on_text=on_text,model="qwen-vl-max"if image else "qwen-plus", tool_choice=force_tool)
            steps = 0
            while (result["finish_reason"] == "tool_calls" or result["tool_calls"]) and steps < 5:
                steps += 1
                turn_tools.extend(tc["function"]["name"] for tc in result["tool_calls"])
                msg = {"role": "assistant", "content": "", "tool_calls": result["tool_calls"]}  # content 传空：防止模型把第一轮过渡话当成已回复，第二轮不转述工具结果
                messages.append(msg)
                # 现在线程池同时跑，谁都不等谁。on_tool 是 queue.Queue（线程安全）；
                # dispatch_agent 调子AI是网络IO，天然适合并行；pool.map 保持结果顺序，tool 消息不乱
                def run_one(tc):
                    """执行单个工具调用。参数解析失败/参数不对/工具不存在/执行出错，
                    全都转成文字喂回模型处理——绝不把异常抛出去弄崩整轮对话；
                    每个出口都写一条审计日志（audit_log），出事能还原现场"""
                    name = tc["function"]["name"]
                    raw = (tc["function"].get("arguments") or "").strip() or "{}"
                    try:
                        args = json.loads(raw)
                        if not isinstance(args, dict):
                            raise ValueError("参数必须是 JSON 对象")
                    except Exception:
                        if on_tool:
                            on_tool(name, {})
                        audit_log(name, raw, "参数解析失败", ok=False)   # 出口1
                        return tc["id"], f"{name} 的参数解析失败（拿到：{raw[:80]}）。请按工具定义用合法 JSON 重新调用，不要编结果"
                    if on_tool:
                        on_tool(name, args)
                    fn = TOOL_FUNCS.get(name)
                    if fn is None:
                        audit_log(name, raw, "没有这个工具", ok=False)   # 出口2
                        return tc["id"], f"没有这个工具：{name}"
                    try:
                        out = str(fn(**args))                            # 出口5（成功）——拆成两行才有地方记日志
                    except TypeError as e:
                        msg = f"{name} 参数不对：{e}。请按参数定义补齐或修正后重新调用，不要编造结果"
                        audit_log(name, args, msg, ok=False)             # 出口3
                        return tc["id"], msg
                    except Exception as e:
                        # 读类工具：网络/接口临时故障值得自动重试一次（幂等，重试无害）
                        if name in RETRYABLE_TOOLS:
                            time.sleep(0.5)              # 给临时故障喘口气
                            try:
                                out = str(fn(**args))    # 第二次尝试
                                audit_log(name, args, out + "（第1次失败，已自动重试成功）", ok=True)
                                return tc["id"], out
                            except Exception as e2:
                                msg = f"{name} 执行失败：{type(e2).__name__}: {e2}（已自动重试一次仍失败）。请如实告诉用户失败原因，别假装成功"
                                audit_log(name, args, msg, ok=False)             # 出口4
                                return tc["id"], msg
                        # 写类工具：不重试，直接把失败喂回模型（避免重复副作用）
                        msg = f"{name} 执行失败：{type(e).__name__}: {e}。请如实告诉用户失败原因，别假装成功"
                        audit_log(name, args, msg, ok=False)             # 出口4
                        return tc["id"], msg
                    # 结果校验：工具返回内容明显不像样时，给模型打标记，别让它把烂结果照念
                    try:
                        v = VALIDATORS.get(name)
                        if v and not v(out):
                            out = out + "\n【系统校验】这份返回内容异常（空/缺关键信息），请如实告诉用户没拿到结果，不要照念也不要编造。"
                    except Exception:
                        pass    # 校验器自己出错也不能影响主流程
                    audit_log(name, args, out, ok=True)                  # 出口5 成功记录
                    return tc["id"], out
                with ThreadPoolExecutor(max_workers=4) as pool:
                    executed = list(pool.map(run_one, result["tool_calls"]))
                for tc_id, content in executed:
                    messages.append({"role": "tool", "tool_call_id": tc_id, "content": content})
                result = create_stream(messages, on_text=on_text)
            # 工具轮数达到上限模型还想继续调：追加一轮"禁止再调工具"的收尾轮，
            # 让它基于已执行的 tool 结果把话说完，而不是甩一句"工具调太多次"就作废
            if result["tool_calls"] and steps >= 5:
                result = create_stream(
                    messages + [{"role": "system", "content": "【系统】工具调用已达本轮上限，禁止再调用任何工具。"
                                  "刚才已执行的工具结果都在上面的 tool 消息里，请直接据此给用户最终答复；"
                                  "没执行成功的工具请如实说明，不要假装成功。"}],
                    on_text=on_text, tool_choice="none")
            full_reply = result["content"] or "抱歉，我这边没组织好回答，你换个说法再问我一次？"
            del messages[base:]
            if print_stream:
                print("AI:", full_reply)
    except Exception as e:
            print(f"请求失败：{e}")
            full_reply = "抱歉，服务暂时不可用，请稍后再试"
            failed = True
        # 保险丝：把模型漏网的括号旁白删掉（规则和直播出口共用 clean_aside）
    full_reply = clean_aside(full_reply)
        # 删掉旁白后可能留下行首行尾多余空格和空行
    full_reply = "\n".join(line.strip() for line in full_reply.split("\n") if line.strip())
    messages.append({"role": "assistant", "content": full_reply})
        # 请求失败时不再白跑记忆/心情两次 API，直接存盘返回
    if not failed:
            threading.Thread(
                target=after_reply_jobs,
                args=(user_input, full_reply),
                daemon=True
            ).start()
        # 存盘前截断：只保留 system 消息 + 最近 MAX_MESSAGES 条对话，防止 history.json 无限膨胀
    system_msgs = [m for m in messages if m["role"] == "system"]
    non_system_msgs = [m for m in messages if m["role"] != "system"]
    if len(non_system_msgs) > MAX_MESSAGES:
        dropped = non_system_msgs[:-MAX_MESSAGES]
        compress_history(dropped)
    messages[:] = system_msgs + non_system_msgs[-MAX_MESSAGES:]
    save_history(messages)
    # 整轮审计：这次对话调过哪些工具、几轮、成败（_turn 条目）
    audit_log("_turn", {"input": user_input[:50], "tools": turn_tools, "rounds": steps},
              "ok" if not failed else "failed", ok=not failed)
    # 红线自检：回复不能带金额/联系方式/脏话，命中就记审计告警（下一步再接自动重写）
    _hits = check_redline(full_reply)
    if _hits:
        audit_log("红线", {"命中": _hits}, full_reply[:80], ok=False)
    return full_reply
print("ai智能机器人已启用（输入 exit 退出，输入 add 添加知识）\n")
messages = current().messages
messages[:] = load_history()
# 人设永远以 persona.txt 为准：history.json 里可能存着旧人设，直接覆盖成最新读到的，
# 否则改了 persona.txt 重启也看不到效果（这是"persona 新内容读不到"的根因）
if messages and messages[0].get("role") == "system":
    messages[0] = {"role": "system", "content": SYSTEM_PROMPT}
else:
    messages.insert(0, {"role": "system", "content": SYSTEM_PROMPT})
# 清掉上次运行时注入的近况/心情/记忆 system 消息，只保留第一条人设，
# 防止每重启一次程序就多攒一份，越积越多把对话撑爆
if len(messages) > 1:
    messages[:] = [messages[0]] + [m for m in messages[1:] if m["role"] != "system"]
# 近况/心情刷新放在 import 时会调网络 API——开机自启时网络可能还没就绪，
# 一旦抛异常整个服务就起不来。包上 try/except：失败就跳过，绝不挡启动
try:
    current_status = update_status()
    if current_status:
        messages.append({"role": "system", "content": "花卷的近况：" + current_status})
except Exception as e:
    print("启动时刷新近况失败(跳过,不影响启动):", e)
try:
    current_mood = update_mood()
    if current_mood:
        messages.append({"role": "system", "content": "花卷的心情：" + current_mood})
except Exception as e:
    print("启动时刷新心情失败(跳过,不影响启动):", e)
if __name__ == "__main__":
    while True:
        user_input = input('你：')
        if user_input == "exit":
            save_history(messages)
            print("再见！")
            break
        if user_input.lower() == "add":
            new_knowledge = input("请输入要添加的知识：")
            add_knowledge(new_knowledge)
            print("已添加到知识库！")
            continue
        get_reply(user_input, print_stream=True)
