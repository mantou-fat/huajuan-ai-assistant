# -*- coding: utf-8 -*-
"""花卷规则引擎：纯规则 + 纯函数集中在这。
原则：只依赖 参数 + config 里的词表，绝不读写 messages/mem/文件，所以能单独测试。"""
import re
from datetime import datetime, timedelta
from config import KB_STRONG, KB_WEAK, PROGRAM_NAMES
def _is_aside_content(s):
    """括号里是不是'旁白'？判定：≤12字的纯中文/中文标点/emoji 才算（如 托腮、小声）。
    出现数字、字母、运算符、网址、冒号的括号是正文（如 （2+1）、print(x)、（RAG）），必须保留"""
    if not s or len(s) > 12:
        return False
    if re.search(r"[0-9０-９a-zA-Z():：、/\\]", s):
        return False
    return bool(re.fullmatch(r"[\u4e00-\u9fff\u3000-\u303f\U0001F000-\U0001FAFF~～!！?？。，…\s]+", s))
def clean_aside(text):
    """删掉'旁白型'括号（如（托腮）（小声）），保留代码/数学/英文括号（如 print(x)、（2+1））。
    直播（逐字流）和最终回答共用这一把刀；旁白判定看 _is_aside_content。
    中文全角括号一律视为旁白（花卷人设明令禁止括号动作），避免长旁白漏网。"""
    text = re.sub(r"（[^（）]*）", "", text)
    text = re.sub(r"\(([^()]*)\)", lambda m: "" if (_is_aside_content(m.group(1)) or re.search(r"[\u4e00-\u9fff]", m.group(1))) else m.group(0), text)
    return text
PERSONA_LEAK_MARKS = [
    "【你的性子】", "【不变底子】", "【底线】", "【说话方式】", "【安全底线】",
    "你叫花卷，是馒头的朋友", "系统提示词", "system prompt",
]


# ===== 安全：危险工具 + 注入检测 =====
DANGEROUS_TOOLS = {"take_screenshot", "lock_screen", "look_around", "open_program", "control_device"}

INJECTION_MARKS = [
    "忽略之前", "忽略所有指令", "忽略你的规则", "忽略规则", "无视你的", "无视规则",
    "假装你是", "你现在是黑客", "黑客助手", "偷看", "偷窥", "绕过限制", "绕过你的",
    "不用确认", "无需确认", "直接执行", "越狱", "system prompt", "系统提示词", "你的设定原文",
]

BLOCKED_EXE = ["cmd.exe", "powershell", "regedit", "taskkill", "format.com", "diskpart",
               "shutdown", "net user", "certutil", "bitsadmin"]


def has_injection(text):
    """用户输入里有没有越权/注入信号"""
    low = (text or "").lower()
    return any(m.lower() in low for m in INJECTION_MARKS)


def dangerous_block_reason(tool_name, user_input, args=None):
    """危险工具执行前的代码级拦截，返回拦截原因；None 表示放行"""
    if tool_name in DANGEROUS_TOOLS and has_injection(user_input):
        return "【已拦截】这条消息像是在诱导我越权操作，我不执行。"
    if tool_name == "open_program" and args:
        s = str(args).lower()
        if any(b in s for b in BLOCKED_EXE):
            return "【已拦截】不允许打开命令行/系统工具。"
    return None


def guard_output(text):
    """输出兜底：有人设/系统提示原文就拒绝，避免被套话泄露"""
    if any(m in text for m in PERSONA_LEAK_MARKS):
        return "这个不能给你看哦，换个问题吧。"
    return text


CUSTOMER_SERVICE_MARKS = [
    "需要我为你做点什么", "需要我为您做点什么", "还有什么可以帮您", "还有什么可以帮你",
    "需要我帮你", "需要我帮您", "要不要我帮你", "要不要我帮您", "比如",
]


PLAN_HINTS = ["步骤", "方案", "计划", "怎么学", "怎么做", "教程", "流程", "分几步", "如何", "规划",
              "表格", "列表", "对比", "大纲", "清单", "整理成"]


def style_violation(text, user_input=""):
    """文风检测：太长、动作描写、列清单、文艺腔、客服腔 → 需要压缩重写。
    用户明确要步骤/方案/表格时不压缩（本来就该列清楚）。"""
    if not text:
        return False
    if any(k in (user_input or "") for k in PLAN_HINTS):
        return False
    # markdown 表格不压（压了会把内容弄没）
    if text.count("|") >= 4:
        return False
    if len(text) > 300:
        return True
    if "▢" in text or "嘶啦" in text:
        return True
    if len(re.findall(r"\n\s*[-•*]\s", text)) >= 1:
        return True
    if text.count("——") >= 2:
        return True
    if any(m in text for m in CUSTOMER_SERVICE_MARKS):
        return True
    return False


CLAIM_RULES = [
    (("已设提醒", "提醒设好", "已记住", "设好了提醒"), {"set_reminder", "create_reminder"}),
    (("已记账", "记好了", "已记下"), {"set_expense"}),
    (("已截屏", "截图已", "截好了"), {"take_screenshot"}),
    (("已锁屏", "锁好了"), {"lock_screen"}),
    (("已打开", "打开了"), {"open_program", "open_app"}),
    (("已生成", "生成好了", "已保存"), {"make_pdf", "make_ppt", "make_docx", "generate_song"}),
]


def claim_mismatch(reply, tools_called):
    """回复里声称做了某动作，但这轮根本没调对应工具 → 说明在编"""
    called = set(tools_called or [])
    for words, tools in CLAIM_RULES:
        if any(w in reply for w in words) and not (called & tools):
            return True
    return False


WEB_SEARCH_HINT = re.compile(r"(搜索一下|搜一下|搜一搜|帮我搜|上网查|百度一下|谷歌一下|查一下最新|最新消息|最新新闻|搜搜)")


def knowledge_hit_level(text):
    """知识题信号强度：'strong'=直接注入；'weak'=要 LLM 复核；None=不是知识题"""
    low = text.lower()
    if any(k in low for k in KB_STRONG):
        return "strong"
    if any(k in low for k in KB_WEAK):
        return "weak"
    return None
# 强触发：句子里有这些，基本就是要看画面
VISION_STRONG = ["打开摄像头", "看摄像头", "摄像头里", "看看镜头", "看看我在干", "看一眼我在", "看我在干",
                 "你面前有什么", "你现在能看到", "能看到什么"]
# 弱触发：单独出现可能是看画面，也可能后面跟着别的宾语
VISION_WEAK = ["看看我", "看我", "看一眼", "看看你", "看屏幕", "看前面", "我这边", "你那边", "你这边"]
# 排除词：弱触发命中后句子里出现这些，说明用户要看的是文字内容，不开摄像头
VISION_EXCLUDE = ["文章", "代码", "简历", "写的", "写得", "邮件", "消息", "作业", "报错", "错误", "问题",
                  "这个", "那张", "图片", "照片", "截图", "翻译", "天气", "下雨"]
def looks_like_vision(text):
    """规则引擎：像想看画面的请求就返回 True"""
    if any(kw in text for kw in VISION_STRONG):
        return True
    if any(kw in text for kw in VISION_WEAK):
        # 弱词命中后，句子里有"内容宾语"就放行给正常聊天
        if any(kw in text for kw in VISION_EXCLUDE):
            return False
        return True
    return False
# ===== 数据型工具硬约束（治"假完成"）：命中就强制调对应工具，模型没有"凭感觉编"的选项 =====
TIME_HARD = re.compile(r"现在几点了?|现在几点钟|几点了|现在几号|今天几号|今天星期几|星期几了|现在什么时间|现在时间|当前时间|今天日期|今天是几号|几点了呀")
WEATHER_INTENT = re.compile(r"(天气|气温|温度|下雨|下雪).{0,10}(怎么样|如何|怎样|几度|多少度|冷不冷|热不热|是什么|查|预报|会不会|吗|呢|啥|如何啊)")
WEATHER_ASK = re.compile(r"(查|问|看看|看下|帮我看看).{0,4}(天气|气温|温度)")
WEATHER_QUICK = re.compile(r"^.{0,10}(天气|气温|温度).{0,4}(怎么样|如何|怎样|呢|吗)$")
EXPENSE_SET = re.compile(r"(花了|花掉|用了|用掉|付了|付|消费了?|充值了?|买了|请了).{0,6}\d+(\.\d+)?\s*(元|块|块钱|rmb)?(?!(小时|分钟|秒|个月|年|周|天))", re.I)
EXPENSE_SET2 = re.compile(r"(记账|记一笔|帮我记|记一下|记个账).{0,10}(花了|花|消费|买了|付了|支出|用)?\d+(\.\d+)?\s*(元|块|块钱)")
EXPENSE_QUERY = re.compile(r"花了多少钱|消费了?多少钱|花了多少|这个月(总共|一共)|总共花了多少|一共花了多少|这个月(花了|的)?(钱|花销|支出|账|账单)|上个月(花了|的)?(钱|花销|支出|账|账单)|查(一?下)?账|看(一?下)?账|账本|记账记录|支出记录|账单|钱都花哪|都花到哪")
def detect_hard_tool(text):
    """规则引擎：这一句是'必须真调工具'的请求？是→返回要强制的工具名；不是→None。
    顺序：时间 → 天气 → 记一笔 → 查账 → 开程序/网站 → 截屏 → 锁屏
    （同一句多意图时优先最像的那个，剩下的交给后续轮次）"""
    if TIME_HARD.search(text):
        return "get_time"
    if WEATHER_INTENT.search(text) or WEATHER_ASK.search(text) or WEATHER_QUICK.search(text):
        return "get_weather"
    if EXPENSE_SET.search(text) or EXPENSE_SET2.search(text):
        return "set_expense"
    if EXPENSE_QUERY.search(text):
        return "query_expenses"
    # ---- 电脑动作：不强制的话模型会'嘴上说打开了实际没调工具'（假完成） ----
    # 否定/取消句不强制（如"别打开微信""先别锁屏"）
    if re.search(r"(别|不要|先别|不用|取消|别急)", text) and re.search(r"(打开|启动|开一?下|锁屏|截屏|锁一下)", text):
        return None
    # 疑问句不强制（如"能打开记事本吗""你会锁屏吗""微信打开了吗"）——那是问能力/问状态，不是下命令
    if re.search(r"(能|可以|会|行).{0,5}(打开|启动|开|锁屏|截屏|截图).{0,8}(吗|不|吧|行不行)", text):
        return None
    if re.search(r"(打开|启动|开一?下|锁屏|截屏).{0,5}(了吗|了没|没有|吗)", text):
        return None
    for name in PROGRAM_NAMES:   # 先精确匹配登记过的程序名，长名优先（记事本 > 记事）
        if re.search(r"(打开|启动|点开|开一?下|开个|帮我开)" + re.escape(name), text) or \
           re.search(r"(把|将|帮我把)" + re.escape(name) + r"(打开|启动|开一?下|点开)", text):
            return "open_program"
        # 兜底：说"打开 XXX"但 XXX 不在白名单 → 也强制调 open_program，
    # 工具会如实回"找不到程序，目前登记的有…"，堵死"假装打开"的假完成
    m = re.search(r"(打开|启动|点开|开一?下|开个|帮我开)\s*([\u4e00-\u9fffA-Za-z0-9]{1,10})", text)
    if m:
        token = m.group(2)
        prev = text[m.start() - 1] if m.start() > 0 else ""   # 动词前一个字符
        if prev.isdigit():          # "3点开会"→点开前是数字=时间，不是下指令
            m = None
        elif not any(w in token for w in ("这", "那", "文件", "程序", "软件", "浏览器",
                                          "网页", "网站", "手机", "应用", "链接", "会", "议")):
            return "open_program"    
    if re.search(r"打开|启动|开一?下", text) and re.search(r"程序|软件|浏览器|应用|网页|网站|[Aa]pp|APP", text):
        return "open_program"
    # ---- 智能家居：说"开灯/关空调/灯开着吗"就强制走 control_device（防嘴上说开了实际没动）----
    if re.search(r"(别|不要|先别|不用)", text) and re.search(r"(灯|空调|风扇|窗帘|电视)", text):
        return None                       # 否定句（别开灯）不强制
    if re.search(r"(客厅灯|卧室灯|空调|风扇|窗帘|电视|灯)", text) and \
       re.search(r"开|关|打开|亮|灭|开着|关着", text):
        return "control_device"
    if re.search(r"截屏|截图|截个图|截一?下|屏幕截图|拍个屏幕", text):
        return "take_screenshot"
    if re.search(r"锁屏|锁定屏幕|把电脑锁|锁一下屏|锁上屏幕", text):
        return "lock_screen"
    # ---- 文档生成：说"做成 PDF/PPT/Word"就强制走 make_*（防嘴上答应实际没生成文件）----
    if re.search(r"(做|生成|导出|转|排)[成为个份]?\s*(pdf|PDF|Pdf)", text):
        return "make_pdf"
    if re.search(r"(做|生成)[个份]?\s*(ppt|PPT|幻灯片|演示文稿)", text) or re.search(r"幻灯片|演示文稿", text):
        return "make_ppt"
    if re.search(r"(做|生成|导出|转|排)[成为]?\s*(word|Word|WORD|docx|DOCX)", text):
        return "make_docx"
    if re.search(r"唱(个|首|一?首)?歌|来(个|首)?歌|写(个|首)?歌|唱一?首", text):
        return "generate_song"
    # ---- 读文件：说"上传了文件/读一下某文件"就强制走 read_file，读真实内容（防嘴上说读了实际没读）----
    if re.search(r"上传了文件|我上传了|刚上传|上传了.{0,3}文件", text):
        return "read_file"
    return None
# 不锁死工具、但注入强指令的两类：设提醒/闹钟、文件盒操作（防止模型嘴上说做了/凭记忆编文件名）
REMINDER_HINT = re.compile(r"提醒我|提醒一下|设个提醒|设一个提醒|设个闹钟|闹钟")
FILEBOX_HINT = re.compile(r"文件盒|有哪些文件|有什么文件|文件都有|读一下|读文件|看一下.{0,6}(文件|笔记|清单|便签)|写(进|到).{0,6}(文件盒|便签|笔记)|列(一?下)?文件|(保存|存).{0,4}文件盒")
# CoT 思维链：命中计算/推理题就强制一步步列步骤（防模型直接跳答案）
COT_HINT = re.compile(r"算一?下|计算|一共|总共|还剩|剩下|平均|翻倍|几倍|差多少|多多少|少多少|第几天|第几次|第几层")
# 多步任务：命中"先…然后/再…"或"然后/接着/之后/顺便 + 动作"就触发规划（Plan-and-Execute 的 Plan 那半）
PLAN_HINT = re.compile(r"(先|首先).{0,15}(然后|再|接着|之后)|(然后|接着|之后|顺便|再).{0,12}(帮|查|写|打开|提醒|设|发|存|算)")
LOCK_HINT = re.compile(r"锁屏|锁定屏幕|把电脑锁")
# 锁屏确认门（Human-in-the-loop）：第一回合只问不做，等用户点头这一回合才真锁
CONFIRM_WORDS = re.compile(r"^(确认|确定|是的?|对|好|嗯|行|锁吧|锁)[。！!？?～~\s]*$")
# 注意：PENDING_LOCK 是"运行时状态"，不放在本文件（rules 只放纯规则），它定义在 bot.py
# 修改提醒的触发词（改成/改到/换成/提前/推迟…）
REMINDER_EDIT_HINT = re.compile(r"提醒|闹钟|那条")
# 登记过的程序/网站名，按名字长度从长到短排，先匹配长名防止歧义
_CN_DIGIT = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7,
             "八": 8, "九": 9, "十": 10}


def _cn_to_int(s):
    """把 一~十二 这类中文数字转成 int"""
    if not s:
        return None
    if s == "十":
        return 10
    if s.startswith("十"):
        return 10 + _CN_DIGIT.get(s[1:], 0)
    if "十" in s:
        a, b = s.split("十", 1)
        return _CN_DIGIT.get(a, 0) * 10 + (_CN_DIGIT.get(b, 0) if b else 0)
    return _CN_DIGIT.get(s)


def parse_remind_time(text):
    """把'明天下午3点/后天上午9点半/晚上7点半/下午五点'这类时间换算成 YYYY-MM-DD HH:MM（纯本地计算）。
    没写哪天默认今天；但若算出来已过期（如晚上10点说'7点半'）说明有歧义 → 返回 None 让模型去问。"""
    from datetime import datetime, timedelta
    # 中文数字转阿拉伯数字（下午五点 → 下午5点）
    text = re.sub(r"([一二两三四五六七八九十]{1,3})(?=[点时])",
                  lambda m: str(_cn_to_int(m.group(1)) or m.group(1)), text)
    m = re.search(r"(?:(今天|明天|后天)\s*)?(凌晨|早上|上午|中午|下午|晚上)?\s*(\d{1,2})[点时](?:(\d{1,2})\s*分?)?", text)
    if not m:
        return None
    day_word = m.group(1)
    period = m.group(2) or ""
    hour = int(m.group(3))
    minute = int(m.group(4) or 0)
    tail = text[m.end():].lstrip()
    if tail.startswith("半"):
        minute = 30
    elif tail.startswith("一刻"):
        minute = 15
    offset = {"今天": 0, "明天": 1, "后天": 2}.get(day_word, 0)
    if period in ("中午", "下午", "晚上") and hour < 12:
        hour += 12          # 下午3点 → 15点
    target = (datetime.now() + timedelta(days=offset)).replace(hour=hour, minute=minute, second=0, microsecond=0)
    if not day_word and target <= datetime.now():
        return None
    return target.strftime("%Y-%m-%d %H:%M")