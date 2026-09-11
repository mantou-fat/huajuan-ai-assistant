# -*- coding: utf-8 -*-
"""花卷配置中心：所有"纯配置"集中在这（路径/常量/白名单/规则表）。
重构原则：这里只放不会变的数据，不放函数、不放运行时状态。"""
import os
# ---- 数据文件 ----
REMINDER_FILE = "reminders.json"
KNOWLEDGE_FILE = "knowledge_base.txt"
HISTORY_FILE = "history.json"
MEMORY_FILE = "memory.json"
VEC_CACHE_FILE = "memory_vecs.json"
STATUS_FILE = "status.json"
MOOD_FILE = "mood.json"
EXPENSE_FILE = "expenses.json"
SUMMARY_FILE = "summary.json"
HOME_FILE = "home.json"
AUDIT_FILE = "audit.log"
SEEN_FILE = "seen.json"
# ---- 目录与读写范围 ----
FILES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "huajuan_files")
READ_DIRS = [FILES_DIR, os.path.dirname(FILES_DIR)]
EXCLUDE_FILES = [".env"]
# ---- 对话参数 ----
MAX_MESSAGES = 20
MEMORY_MERGE_EVERY = 5
# ---- 幂等重试白名单（只放读类/无副作用工具）----
RETRYABLE_TOOLS = {"get_time", "get_weather", "query_expenses", "list_files", "read_file",
                   "read_webpage", "web_search", "search_knowledge", "look_around", "dispatch_agent"}
# ---- 结果校验器 ----
VALIDATORS = {
    "get_weather":    lambda r: ("℃" in r) or ("失败" in r) or ("没拿到" in r),
    "query_expenses": lambda r: ("笔" in r and "元" in r) or ("失败" in r),
    "web_search":     lambda r: len(r) > 5,
    "dispatch_agent": lambda r: len(r) > 5,
}
# ---- 程序/网站白名单 ----
PROGRAM_LIST = {
    "微信": r"C:\Program Files\Tencent\Weixin\Weixin.exe",
    "QQ": r"C:\Program Files\Tencent\QQNT\QQ.exe",
    "记事本": "notepad.exe",
    "计算器": "calc.exe",
    "哔哩哔哩": "https://www.bilibili.com",
    "抖音": "https://www.douyin.com",
    "知乎": "https://www.zhihu.com",
    "微博": "https://weibo.com",
    "百度": "https://www.baidu.com",
    "淘宝": "https://www.taobao.com",
    "京东": "https://www.jd.com",
    "拼多多": "https://www.pinduoduo.com",
    "网易云音乐": "https://music.163.com",
    "腾讯视频": "https://v.qq.com",
    "优酷": "https://www.youku.com",
    "GitHub": "https://github.com",
    "DeepSeek": "https://chat.deepseek.com",
}
PROGRAM_NAMES = sorted(PROGRAM_LIST.keys(), key=len, reverse=True)
# ---- 知识题路由词表 ----
KB_STRONG = ["rag", "embedding", "向量", "检索", "召回", "token", "flask", "api",
             "prompt", "流式", "sse", "函数调用", "工具调用", "agent", "智能体",
             "temperature", "top_p", "max_tokens", "上下文窗口", "system消息", "few-shot"]
KB_WEAK = ["什么是", "是什么", "怎么用", "如何", "原理", "区别", "对比"]