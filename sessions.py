# -*- coding: utf-8 -*-
"""会话层：把"每个用户一份"的状态收进 Session 对象，多用户下互不串话。
设计要点（这三条决定了后面能不能"零行为变化"地接进去）：
① 单用户模式 = sid 为 "default" 的那一个 Session，它的数据文件路径和现在完全一样
   （history.json / memory.json ...，相对路径，一个字符都不差），所以老用户感觉不到任何变化；
② 多用户模式 = 数据落在 data/<sid>/ 下，一人一套文件，删号就是删目录；
③ 每个 Session 自带一把锁，A 的长对话不会把 B 的请求堵在门口（全局那把 chat_lock 的进阶版）。
为什么不做"if 多用户就走新代码，否则走老代码"：两条代码路径早晚会跑偏，
所以只保留一条路径——老用户就是 sid="default" 的那条路径。
共享的东西不放进 Session：知识库、规则表、工具表、配置常量全站一份（它们是"花卷的知识"，不是"某个用户的"）。
"""
import os
import re
import threading
import time

from config import (HISTORY_FILE, MEMORY_FILE, VEC_CACHE_FILE, STATUS_FILE, MOOD_FILE,
                    EXPENSE_FILE, REMINDER_FILE, HOME_FILE, SUMMARY_FILE, SEEN_FILE)

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
DATA_ROOT = os.path.join(PROJECT_ROOT, "data")   # 多用户的数据都放这儿，一个用户一个子目录
DEFAULT_SID = "default"                          # 单用户模式用的 sid（也是老文件的主人）
SID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,32}$")   # 只允许字母数字下划线连字符

# 文件名映射：值全部来自 config，避免"同一个文件名写两遍"（这项目吃过重复定义的亏）
FILE_MAP = {
    "history": HISTORY_FILE, "memory": MEMORY_FILE, "vec_cache": VEC_CACHE_FILE,
    "status": STATUS_FILE, "mood": MOOD_FILE, "expense": EXPENSE_FILE,
    "reminder": REMINDER_FILE, "home": HOME_FILE, "summary": SUMMARY_FILE,
    "seen": SEEN_FILE,
}


class Session:
    """一个用户的一整套状态：对话历史、记忆、心情近况、待确认队列、定位，外加一把自己的锁。"""
    def __init__(self, sid, legacy=False):
        if not SID_PATTERN.match(sid):
            # 防目录穿越：sid 会变成路径的一部分，绝不能让 "../.." 这种东西进来
            raise ValueError("非法的 sid：%r（只允许字母数字下划线连字符，长度 1-32）" % (sid,))
        self.sid = sid
        self.legacy = legacy          # True=老文件（项目根目录，相对路径），单用户模式专用
        self.dir = PROJECT_ROOT if legacy else os.path.join(DATA_ROOT, sid)
        # 文件路径：legacy 模式就是现在那几个相对路径（和 config 常量一模一样）
        self.files = {k: (v if legacy else os.path.join(self.dir, v)) for k, v in FILE_MAP.items()}
        self.lock = threading.RLock()          # 每个用户一把锁：A 聊天不堵 B
        # 时间戳用 monotonic：只算时间差、不受系统改时间影响。
        # 注意 Windows 上 time.time()/monotonic() 精度约 15ms——同一时间片内建的会话
        # 时间戳会完全相同，所以下面比较用 >= 而不是 >（这个坑是自测脚本逼出来的）。
        self.created = self.last_active = time.monotonic()
        # ↓↓↓ 以下原来都是各模块的模块级全局变量，多用户下会互相串，所以收进会话
        self.messages = []                     # 对话历史（原来是 bot.messages）
        self.mem = []                          # 长期记忆（原来是 memory.mem）
        self.mem_embeddings = None             # 记忆向量缓存（原来是 memory._mem_embeddings）
        self.last_merge_len = None             # 上次合并时的记忆条数（原来是 memory._last_merge_len）
        self.status = {}                       # 花卷的近况
        self.mood = {}                         # 花卷的心情
        self.seen = {}                         # 见面记录（上次聊天时间）
        self.pending_lock = [False]            # 锁屏确认门（原来是 bot.PENDING_LOCK）
        self.pending_writes = {}               # 待确认写入（原来是 tools.PENDING_WRITES）
        self.phone_actions = {}                # 手机动作开单（原来是 tools.PHONE_ACTIONS）
        self.location = {"lat": None, "lon": None}   # 定位（原来是 tools.user_location）

    def touch(self):
        self.last_active = time.monotonic()

    def file(self, name):
        """取数据文件路径：session.file("history") → 该用户的 history.json"""
        return self.files[name]

    def is_new(self):
        """这个用户是不是第一次来（没有任何历史）"""
        return not self.messages

    def __repr__(self):
        return "<Session %s%s 消息%d条 记忆%d条>" % (
            self.sid, "(老文件)" if self.legacy else "", len(self.messages), len(self.mem))


class SessionStore:
    """会话仓库：sid → Session。懒创建、能卸载空闲会话、线程安全。"""
    def __init__(self, max_sessions=200, idle_ttl=3600, min_idle_for_evict=60):
        self._sessions = {}
        self._store_lock = threading.Lock()
        self.max_sessions = max_sessions
        self.idle_ttl = idle_ttl                 # 多久没说话算"闲置"，sweep() 用它
        self.min_idle_for_evict = min_idle_for_evict   # 刚拿到的会话有这段保护期，不能被立刻卸掉
        self.hits = self.misses = self.evicted = 0

    def get(self, sid=DEFAULT_SID):
        sid = sid or DEFAULT_SID
        with self._store_lock:
            s = self._sessions.get(sid)
            if s is not None:
                self.hits += 1
                s.touch()
                return s
            self.misses += 1
            s = Session(sid, legacy=(sid == DEFAULT_SID))
            self._sessions[sid] = s
            self._evict_if_needed(keep=sid)
            return s

    def drop(self, sid):
        """卸载一个会话（只从内存里去掉，磁盘上的文件不动）"""
        with self._store_lock:
            return self._sessions.pop(sid, None) is not None

    def sids(self):
        with self._store_lock:
            return sorted(self._sessions)

    def stats(self):
        with self._store_lock:
            return {"在内存会话数": len(self._sessions), "命中": self.hits,
                    "新建": self.misses, "曾卸载": self.evicted}

    def _evict_if_needed(self, keep=None):
        """内存保护：会话数超上限就卸掉最久没动的。
        四条规矩：① default 永不卸载；② 锁被人持着的（正在用）不动；
        ③ keep 这个刚建好的绝不卸（否则刚发给调用方就没了）；
        ④ 刚创建的有一小段保护期——防"刚发出去就被别的线程卸掉"这种鬼问题。"""
        if len(self._sessions) <= self.max_sessions:
            return
        now = time.monotonic()
        idle = [(s.last_active, sid) for sid, s in self._sessions.items()
                if sid != DEFAULT_SID and sid != keep and not _in_use(s)
                and now - s.last_active >= self.min_idle_for_evict]
        idle.sort()
        for _, sid in idle[:len(self._sessions) - self.max_sessions]:
            self._sessions.pop(sid, None)
            self.evicted += 1

    def sweep(self):
        """定期清理：把闲置超过 idle_ttl 的会话从内存卸掉（数据都在磁盘上，不丢东西）"""
        now = time.monotonic()
        dropped = []
        with self._store_lock:
            for sid, s in list(self._sessions.items()):
                if sid == DEFAULT_SID or _in_use(s):
                    continue
                if now - s.last_active > self.idle_ttl:
                    self._sessions.pop(sid, None)
                    self.evicted += 1
                    dropped.append(sid)
        return dropped


store = SessionStore()          # 全局唯一的会话仓库（它自己线程安全，不是"用户状态"）


def current(sid=DEFAULT_SID):
    """取（必要时创建）某个用户的会话——上层最常用的入口"""
    return store.get(sid)


def _in_use(sess):
    """判断会话是不是正被别人用着（用来决定能不能从内存卸掉）。
    坑点：threading.RLock 没有 locked() 方法（只有普通 Lock 有），只能"试着获取一下"来探；
    而且 RLock 允许持有者自己递归获取，所以同一个线程里探自己的锁会误判成"没在用"。
    正因为有这点误差，Session 才需要 min_idle_for_evict 那段保护期兜底。
    就算偶尔误卸也没事：会话状态该落盘的都落盘了，下次 get() 会重新建一个。"""
    if sess.lock.acquire(blocking=False):
        sess.lock.release()
        return False
    return True
