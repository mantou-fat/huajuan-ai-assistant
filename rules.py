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
    直播（逐字流）和最终回答共用这一把刀；旁白判定看 _is_aside_content"""
    text = re.sub(r"（([^（）]{1,12})）", lambda m: "" if _is_aside_content(m.group(1)) else m.group(0), text)
    text = re.sub(r"\(([^()]{1,12})\)", lambda m: "" if _is_aside_content(m.group(1)) else m.group(0), text)
    return text
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
EXPENSE_SET = re.compile(r"(花了|花掉|用了|用掉|付了|付|消费了?|充值了?|买了|请了).{0,6}\d+(\.\d+)?\s*(元|块|块钱|rmb)", re.I)
EXPENSE_SET2 = re.compile(r"(记账|记一笔|帮我记|记一下|记个账).{0,10}(花了|花|消费|买了|付了|支出|用)?\d+(\.\d+)?\s*(元|块|块钱)")
EXPENSE_QUERY = re.compile(r"花了多少钱|消费了?多少钱|花了多少|这个月(花了|的)?(钱|花销|支出|账|账单)|上个月(花了|的)?(钱|花销|支出|账|账单)|查(一?下)?账|看(一?下)?账|账本|记账记录|支出记录|账单|钱都花哪|都花到哪")
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
LOCK_HINT = re.compile(r"锁屏|锁定屏幕|把电脑锁")
# 锁屏确认门（Human-in-the-loop）：第一回合只问不做，等用户点头这一回合才真锁
CONFIRM_WORDS = re.compile(r"^(确认|确定|是的?|对|好|嗯|行|锁吧|锁)[。！!？?～~\s]*$")
# 注意：PENDING_LOCK 是"运行时状态"，不放在本文件（rules 只放纯规则），它定义在 bot.py
# 修改提醒的触发词（改成/改到/换成/提前/推迟…）
REMINDER_EDIT_HINT = re.compile(r"提醒|闹钟|那条")
# 登记过的程序/网站名，按名字长度从长到短排，先匹配长名防止歧义
def parse_remind_time(text):
    """把'明天下午3点/后天上午9点半/晚上7点半'这类时间换算成 YYYY-MM-DD HH:MM（纯本地计算）。
    没写哪天默认今天；但若算出来已过期（如晚上10点说'7点半'）说明有歧义 → 返回 None 让模型去问。"""
    from datetime import datetime, timedelta
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