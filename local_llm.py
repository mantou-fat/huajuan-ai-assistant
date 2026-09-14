# -*- coding: utf-8 -*-
"""本地模型适配层：让花卷跑在本机模型上，而 bot.py / persona_state.py 一行都不用改。
为什么必须有这一层（面试也爱问"你的 skill 怎么跑起来的"）：
① 云端用的是 OpenAI SDK：client.chat.completions.create(...) → 返回 .choices[0].message。
   本地推理引擎（OpenVINO GenAI）的 API 形状完全不同，中间必须有人把两种格式翻译过来；
② 本地小模型（3B）不像云端那样稳定吐结构化 tool_calls，得由我们把它的
   <tool_call>{"name":...,"arguments":{...}}</tool_call> 解析成 OpenAI 形状，还要防它编工具名；
③ 它不认识图片、遇到没有的能力要优雅降级，而不是把整轮对话崩掉。
设计思路：LocalClient 伪装成 OpenAI 客户端——属性路径一样、返回对象一样，
于是 llm.py 只要换一个 client 变量，上层 21 个工具和整个工具循环全部零改动。
"""
import json
import os
import queue
import re
import threading
import time
from config import LOCAL_MODEL_PATH, LOCAL_DEVICE, LOCAL_MAX_NEW_TOKENS
# 工具调用标记：Qwen 系列的原生格式（Hermes 风格）
TOOL_CALL_RE = re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.S)
JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.S)


def _iter_json_objects(text):
    """扫出文本里所有"括号配平的 JSON 对象"：边扫边数字符串引号与转义，
    比正则靠谱（正则搞不定 "arguments": {"query": "RAG"} 这种嵌套花括号）。"""
    i, n = 0, len(text)
    while i < n:
        if text[i] != "{":
            i += 1
            continue
        depth, in_str, esc, j = 0, False, False, i
        while j < n:
            ch = text[j]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
            elif ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    yield text[i:j + 1]
                    break
            j += 1
        i = j + 1


class _Fn:
    def __init__(self, name, arguments):
        self.name = name
        self.arguments = arguments
    def __repr__(self):
        return "Fn(%s, %s)" % (self.name, self.arguments[:40])


class _ToolCall:
    def __init__(self, index, id_, name, arguments):
        self.index = index
        self.id = id_
        self.type = "function"
        self.function = _Fn(name, arguments)


class _Delta:
    def __init__(self, content=None, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls
        self.role = "assistant"


class _Choice:
    def __init__(self, delta=None, message=None, finish_reason=None):
        self.delta = delta
        self.message = message
        self.finish_reason = finish_reason
        self.index = 0


class _Chunk:
    def __init__(self, delta=None, finish_reason=None):
        # delta 绝不能是 None：上层 create_stream 会直接读 ch.delta.content，
        # 之前结束块给了 None，端到端就炸出 'NoneType' object has no attribute 'content'
        self.choices = [_Choice(delta=delta if delta is not None else _Delta(), finish_reason=finish_reason)]
        self.model = "local"


class _Message:
    def __init__(self, content, tool_calls=None):
        self.role = "assistant"
        self.content = content
        self.tool_calls = tool_calls or None


class _Response:
    def __init__(self, content, tool_calls=None, finish_reason="stop"):
        self.choices = [_Choice(message=_Message(content, tool_calls), finish_reason=finish_reason)]
        self.model = "local"


def parse_tool_calls(text, allowed_names=None):
    """把模型吐出来的文字解析成 OpenAI 形状的工具调用。
    三级兜底：① Qwen 原生 <tool_call>{...}</tool_call> ② ```json 代码块 ③ 裸 JSON。
    解析出来还会用 allowed_names 校验工具名——小模型最爱编不存在的工具，必须拦住。"""
    found = []
    for m in TOOL_CALL_RE.finditer(text or ""):
        found.append(m.group(1))
    if not found:
        for m in JSON_FENCE_RE.finditer(text or ""):
            found.append(m.group(1))
    if not found:
        found.extend(_iter_json_objects(text or ""))     # 裸 JSON：用括号配平扫描
    calls, seen = [], set()
    for raw in found:
        try:
            obj = json.loads(raw)
        except Exception:
            continue                      # 半个 JSON（模型被截断）直接丢掉，不猜
        if not isinstance(obj, dict):
            continue
        name = obj.get("name") or obj.get("tool") or obj.get("function")
        args = obj.get("arguments", obj.get("parameters", obj.get("args", {})))
        if isinstance(args, str):
            try:
                args = json.loads(args) if args.strip() else {}
            except Exception:
                args = {}
        if not isinstance(args, dict) or not name:
            continue
        if allowed_names is not None and name not in allowed_names:
            continue                      # 防编造：不在本轮工具表里的名字一律不认
        key = (name, json.dumps(args, sort_keys=True, ensure_ascii=False))
        if key in seen:
            continue                      # 同一个调用重复吐两遍，去重
        seen.add(key)
        calls.append(_ToolCall(len(calls), "call_%d" % len(calls), name,
                               json.dumps(args, ensure_ascii=False)))
    return calls


# 本地小模型的通病：明明在闲聊也乱调工具。实测 7 个用例里错了 2 个
# （"今天心情不错"→去调摄像头，"讲个笑话"→去联网搜索），云端模型不会这样。
# 所以在给它工具时，必须先立规矩——这条提示词就是"本地通道的兜底"。
TOOL_RULE = ("【工具使用规则】只有当用户明确要你做事（问时间、查天气、记一笔账、设提醒、"
             "开关程序/设备、查资料等）时才调用工具。闲聊、打招呼、表达心情、让你讲笑话或陪你说话时，"
             "绝对不要调用任何工具，直接用你自己的话回答。")


class _LocalPipeline:
    """模型本体：懒加载（第一次用时才加载，避免启动就吃几秒 + 几百 MB 内存）"""
    def __init__(self, model_path=None, device=None):
        self.model_path = model_path or LOCAL_MODEL_PATH
        self.device = device or LOCAL_DEVICE
        self._pipe = None
        self._lock = threading.Lock()
        # 本地引擎一次只能生成一个：云端是别人的服务器，能同时接几百个请求；
        # 本地就是你这一块 CPU/GPU，两个线程同时 generate 会被引擎直接拒绝
        # （实测报错：Generate cannot be called while ContinuousBatchingPipeline is already in running state）。
        # 所以并发请求必须在适配层排队——这也是本地部署和云端部署最大的区别之一。
        self._gen_lock = threading.Lock()
        self.waited = 0            # 有多少次请求因为排队等过
        self.load_seconds = None
        self.stats = {"生成次数": 0, "生成token数": 0, "总耗时秒": 0.0, "首字延迟秒": []}
    def pipe(self):
        with self._lock:
            if self._pipe is None:
                if not os.path.exists(self.model_path):
                    raise FileNotFoundError("本地模型文件不存在：%s" % self.model_path)
                os.environ.setdefault("OV_TELEMETRY_DISABLE", "1")   # 关掉遥测，别往外发东西
                import openvino_genai as ov
                t0 = time.time()
                # CACHE_DIR：把编译好的模型缓存在模型旁边，第二次启动能快很多
                cache = os.path.join(os.path.dirname(self.model_path), "ov_cache")
                cfg = {"CACHE_DIR": cache} if os.path.isdir(os.path.dirname(self.model_path)) else {}
                self._pipe = ov.LLMPipeline(self.model_path, self.device, cfg)
                self.load_seconds = time.time() - t0
            return self._pipe
    def build_prompt(self, messages, tools=None):
        """把 OpenAI 形状的 messages + tools 渲染成模型能吃的 prompt（用模型自带的对话模板）"""
        msgs = _normalize(messages)
        tok = self.pipe().get_tokenizer()
        try:
            return tok.apply_chat_template(msgs, True, "", tools or None, None)
        except Exception:
            return _manual_chatml(msgs, tools)      # 模板不支持就自己拼，兜底不崩
    def generate(self, prompt, temperature=0.8, max_tokens=None, top_p=0.9, streamer=None):
        import openvino_genai as ov
        cfg = ov.GenerationConfig()
        cfg.max_new_tokens = int(max_tokens or LOCAL_MAX_NEW_TOKENS)
        cfg.temperature = float(temperature if temperature else 0.8)
        cfg.top_p = float(top_p or 0.9)
        cfg.do_sample = True
        try:
            cfg.repetition_penalty = 1.1            # 小模型爱复读，给它上点惩罚
        except Exception:
            pass
        t0 = time.time()
        if not self._gen_lock.acquire(blocking=False):
            self.waited += 1                    # 有人正在生成，我们排队（记一笔，方便看本地到底堵不堵）
            self._gen_lock.acquire()            # 这里才真的阻塞等前一个生成完
        try:
            out = self.pipe().generate(prompt, cfg, streamer) if streamer else self.pipe().generate(prompt, cfg)
        finally:
            self._gen_lock.release()
        cost = time.time() - t0
        text = out if isinstance(out, str) else (out.texts[0] if getattr(out, "texts", None) else str(out))
        self.stats["生成次数"] += 1
        self.stats["总耗时秒"] += cost
        self.stats["生成字数"] = self.stats.get("生成字数", 0) + len(text)
        try:
            # 引擎自带性能指标。坑：MeanStdPair.mean 是"方法"不是属性，直接 round(x.mean) 会报错。
            # 另外流式调用返回的是字符串（没有 perf_metrics），必须先判断类型。
            pm = getattr(out, "perf_metrics", None)
            if pm is not None:
                n = _plain(pm.get_num_generated_tokens())
                self.stats["生成token数"] += int(n or 0)
                self.stats["首字延迟秒"].append(round(float(_plain(pm.get_ttft().mean)), 3))
        except Exception as e:
            self.stats["指标读取失败"] = "%s: %s" % (type(e).__name__, e)
        return text, cost
    def summary(self):
        s = dict(self.stats)
        n, sec = s["生成token数"], s["总耗时秒"]
        s["平均速度(token/s)"] = round(n / sec, 2) if sec > 0 else 0
        s["平均速度(字/s)"] = round(s.get("生成字数", 0) / sec, 2) if sec > 0 else 0
        ttfts = s.pop("首字延迟秒", [])
        s["平均首字延迟秒"] = round(sum(ttfts) / len(ttfts), 3) if ttfts else None
        s["模型"] = os.path.basename(self.model_path)
        s["设备"] = self.device
        s["加载耗时秒"] = round(self.load_seconds, 2) if self.load_seconds else None
        s["排队等待过的次数"] = self.waited
        return s


def _inject_system(messages, text):
    """把一句系统要求并进"第一条 system 消息"里。
    为什么不能简单 append 一条 system：Qwen 的对话模板只在开头渲染 system 块，
    末尾再挂一条 system 紧挨着 assistant，小模型会直接懵掉——
    实测强制作业的 prompt 让 3B 吐出 "Podesta，请稍等" 这种胡话。
    这里顺手做浅拷贝，绝不改动调用方（bot.py）手里的历史消息。"""
    msgs = [dict(m) for m in (messages or [])]
    for m in msgs:
        if m.get("role") == "system":
            m["content"] = ((m.get("content") or "") + "\n" + text).strip()
            return msgs
    msgs.insert(0, {"role": "system", "content": text})
    return msgs


def _plain(x):
    """MeanStdPair 这类包装：字段可能是方法也可能是属性，统一取出来"""
    return x() if callable(x) else x


def _normalize(messages):
    """把消息整理成模板能吃的样子：工具调用统一成 dict、参数统一成 JSON 字符串"""
    out = []
    for m in messages or []:
        if not isinstance(m, dict):
            continue
        role = m.get("role", "user")
        content = m.get("content")
        if isinstance(content, list):        # 多模态内容（图片）
            content = " ".join(p.get("text", "") if isinstance(p, dict) else str(p) for p in content)
        item = {"role": role, "content": content or ""}
        tcs = m.get("tool_calls")
        if tcs and role == "assistant":
            norm = []
            for tc in tcs:
                fn = tc.get("function") if isinstance(tc, dict) else getattr(tc, "function", None)
                if fn is None and isinstance(tc, dict):
                    fn = tc
                name = fn.get("name") if isinstance(fn, dict) else getattr(fn, "name", None)
                args = fn.get("arguments", "{}") if isinstance(fn, dict) else getattr(fn, "arguments", "{}")
                if not isinstance(args, str):
                    args = json.dumps(args, ensure_ascii=False)
                if name:
                    norm.append({"type": "function", "function": {"name": name, "arguments": args}})
            if norm:
                item["tool_calls"] = norm
        if m.get("tool_call_id"):
            item["tool_call_id"] = m["tool_call_id"]
        out.append(item)
    return out


def _manual_chatml(messages, tools=None):
    """模板不支持 tools 时的兜底：自己拼 ChatML，并把工具说明写进系统消息。
    小模型对"必须调工具"的服从度差，所以这里额外加一句硬要求。"""
    parts = []
    if tools:
        spec = json.dumps(tools, ensure_ascii=False)
        parts.append("<|im_start|>system\n你可以调用以下工具（JSON Schema）：\n" + spec +
                     "\n需要工具时，只输出 <tool_call>{\"name\": 工具名, \"arguments\": {...}}</tool_call>，"
                     "一次可以输出多个；不需要工具就直接回答。<|im_end|>\n")
    for m in messages:
        role = m.get("role", "user")
        if role == "system":
            parts.append("<|im_start|>system\n%s<|im_end|>\n" % m.get("content", ""))
        elif role == "tool":
            parts.append("<|im_start|>user\n<tool_response>\n%s\n</tool_response><|im_end|>\n" % m.get("content", ""))
        elif role == "assistant":
            body = m.get("content", "")
            for tc in m.get("tool_calls", []) or []:
                fn = tc.get("function", {})
                body += "\n<tool_call>{\"name\": \"%s\", \"arguments\": %s}</tool_call>" % (
                    fn.get("name", ""), fn.get("arguments", "{}"))
            parts.append("<|im_start|>assistant\n%s<|im_end|>\n" % body)
        else:
            parts.append("<|im_start|>user\n%s<|im_end|>\n" % m.get("content", ""))
    parts.append("<|im_start|>assistant\n")
    return "".join(parts)


class _Completions:
    def __init__(self, owner):
        self.owner = owner
    def create(self, model=None, messages=None, tools=None, tool_choice=None,
               stream=False, temperature=0.8, max_tokens=None, top_p=0.9, **kw):
        return self.owner._create(model, messages, tools, tool_choice, stream,
                                  temperature, max_tokens, top_p, **kw)


class _Chat:
    def __init__(self, owner):
        self.completions = _Completions(owner)


class LocalClient:
    """伪装成 OpenAI 客户端：用法一模一样（client.chat.completions.create(...)）"""
    def __init__(self, model_path=None, device=None):
        self.pipeline = _LocalPipeline(model_path, device)
        self.chat = _Chat(self)
        self.audit = []          # 每次调用的真相：有没有解析出工具、耗时多久
    def _prepare(self, messages, tools, tool_choice):
        """处理三个本地模型特有的问题：图片、强制调用、禁止调用"""
        if _has_image(messages):
            return None, None, ("本地模型看不了图片（它只会读文字）。"
                                "想要看图，把 .env 里的 MODEL_PROVIDER 切回 cloud 再跟我说一遍就行。")
        allowed = None
        if tools:
            allowed = {t["function"]["name"] for t in tools if "function" in t}
        if tool_choice == "none":
            tools = None                     # 本轮禁止调工具（收尾轮就是这么用的）
        elif isinstance(tool_choice, dict):
            name = (tool_choice.get("function") or {}).get("name")
            if name:
                tools = [t for t in tools if t["function"]["name"] == name] or tools
                messages = _inject_system(messages,
                    "【本轮硬性要求】必须调用工具 %s，不允许只说不做，也不允许编造它的返回结果。" % name)
        if tools:                             # 给工具就得同时立规矩，否则它逮着啥都调
            messages = _inject_system(messages, TOOL_RULE)
        return messages, tools, None
    def _create(self, model, messages, tools, tool_choice, stream,
                temperature, max_tokens, top_p, **kw):
        messages, tools, deny = self._prepare(messages, tools, tool_choice)
        if deny is not None:
            if stream:
                return iter([_Chunk(_Delta(content=deny)), _Chunk(finish_reason="stop")])
            return _Response(deny)
        allowed = {t["function"]["name"] for t in tools} if tools else None
        prompt = self.pipeline.build_prompt(messages, tools)
        if stream:
            return self._stream(prompt, allowed, temperature, max_tokens, top_p)
        text, cost = self.pipeline.generate(prompt, temperature, max_tokens, top_p)
        calls = parse_tool_calls(text, allowed)
        clean = TOOL_CALL_RE.sub("", text).strip() if calls else text
        self.audit.append({"工具调用": [c.function.name for c in calls], "耗时秒": round(cost, 2),
                           "流式": False, "输出字数": len(text)})
        return _Response(clean, calls, "tool_calls" if calls else "stop")
    def _stream(self, prompt, allowed, temperature, max_tokens, top_p):
        """引擎的流式是"回调式"，OpenAI 是"迭代器式"——用线程 + 队列把两者接起来。"""
        q = queue.Queue()
        def cb(text):
            q.put(("text", text))
            return False
        def worker():
            try:
                full, _ = self.pipeline.generate(prompt, temperature, max_tokens, top_p, streamer=cb)
                q.put(("done", full))
            except Exception as e:
                q.put(("err", e))
        threading.Thread(target=worker, daemon=True).start()
        buf = ""
        while True:
            kind, payload = q.get()
            if kind == "text":
                buf += payload
                yield _Chunk(_Delta(content=payload))
            elif kind == "err":
                raise payload
            else:
                text = payload if isinstance(payload, str) and payload else buf
                calls = parse_tool_calls(text, allowed)
                if calls:
                    yield _Chunk(_Delta(tool_calls=calls))       # 工具调用一次性给出（上层按 index 累加，形状一致）
                self.audit.append({"工具调用": [c.function.name for c in calls],
                                   "耗时秒": None, "流式": True, "输出字数": len(text)})
                yield _Chunk(finish_reason="tool_calls" if calls else "stop")
                return
    def stats(self):
        return self.pipeline.summary()


def _has_image(messages):
    for m in messages or []:
        c = m.get("content") if isinstance(m, dict) else None
        if isinstance(c, list):
            for part in c:
                if isinstance(part, dict) and part.get("type") == "image_url":
                    return True
    return False
