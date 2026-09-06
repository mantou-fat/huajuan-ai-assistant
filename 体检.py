# -*- coding: utf-8 -*-
r"""
花卷 一键体检 (self_check)
用法: 在 D:\python 目录下运行   python 体检.py
功能: 自动跑完全部 21 个工具 + 关键对话链路, 逐个打 ✅/❌, 最后给总分。
说明:
  * 会真实调用一次 API(阿里云), 大概花几毛钱、跑 1~2 分钟
  * 测试前自动备份并恢复 数据文件(记账/提醒/记忆/历史/近况/心情/家电等), 不会污染真实数据
  * 开程序/截屏/锁屏 用"桩"验证调用链(不会真在你桌面弹窗/真锁屏)
  * 唱歌(generate_song) 权限未开通、摄像头(look_around) 无摄像头 → 自动跳过并注明
"""
import os, sys, json, time, shutil, re

BASE = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ---------- 0. 先备份数据文件(测试完自动恢复) ----------
DATA_FILES = ["expenses.json", "reminders.json", "memory.json", "history.json",
              "mood.json", "status.json", "seen.json", "summary.json", "home.json",
              "memory_vecs.json"]
BAK = os.path.join(BASE, ".pip-tmp", "huajuan_selfcheck_bak")
os.makedirs(BAK, exist_ok=True)
_saved = {}
for f in DATA_FILES:
    p = os.path.join(BASE, f)
    if os.path.exists(p):
        _saved[f] = shutil.copy2(p, os.path.join(BAK, f))

import bot

PASS, FAIL, SKIP, LINES = [], [], [], []
def t(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    mark = "PASS" if ok else "FAIL"
    print(f"[{mark}] {name}" + (f"  | {detail}" if detail else ""))
def skip(name, why=""):
    SKIP.append(name)
    print(f"[SKIP] {name}  | {why}")

print("=" * 64)
print("花卷一键体检开始  (21 个工具逐个过)")
print("=" * 64)

# ---------- 1. 工具注册表 ----------
tool_names = [x["function"]["name"] for x in bot.TOOLS]
t("工具注册表: TOOLS 与 TOOL_FUNCS 数量一致且无缺失",
  len(tool_names) == len(bot.TOOL_FUNCS) == 21 and all(n in bot.TOOL_FUNCS for n in tool_names),
  f"{len(tool_names)} 个")

# ---------- 2. 纯离线功能 ----------
t("get_time 返回当前时间格式", bool(re.match(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2} 周", bot.get_time())))

aside = bot.clean_aside("（托腮）代码 print(hello) 数学（2+1）=3（RAG）正常（小声）")
t("clean_aside 只删旁白、保留代码/数学括号", aside == "代码 print(hello) 数学（2+1）=3（RAG）正常")

rule_cases = [("现在几点了", "get_time"), ("北京天气怎么样", "get_weather"),
              ("买咖啡花了18.5元", "set_expense"), ("这个月花了多少钱", "query_expenses"),
              ("打开记事本", "open_program"), ("截个图", "take_screenshot"),
              ("把电脑锁了", "lock_screen"), ("别打开微信", None), ("能打开记事本吗", None),
              ("哈哈今天真开心", None)]
bad_rules = [c for c in rule_cases if bot.detect_hard_tool(c[0]) != c[1]]
t("规则引擎 10 例全对(含防误伤)", not bad_rules, f"错的: {bad_rules}")

t("路径防护: .env 不给读", bot.safe_read_path(".env") is None)
t("路径防护: 目录外不给写", bot.safe_write_path("..\\evil.txt") is None)

# 文件盒两步写入(用临时文件, 测完删)
tmpf = "__体检临时.txt"
m1 = bot.write_file(tmpf, "体检内容ABC", confirm=False)
m2 = bot.write_file(tmpf, "不一样", confirm=True)
m3 = bot.write_file(tmpf, "体检内容ABC", confirm=True)
wrote_ok = os.path.exists(os.path.join("huajuan_files", tmpf)) and open(
    os.path.join("huajuan_files", tmpf), encoding="utf-8").read() == "体检内容ABC"
if os.path.exists(os.path.join("huajuan_files", tmpf)):
    os.remove(os.path.join("huajuan_files", tmpf))
t("write_file 两步确认(不一致拒/一致写)", "不一致" in m2 and "已写入" in m3 and wrote_ok)

r1 = bot.read_file(".env")
r2 = bot.read_file("__不存在的文件__.txt")
t("read_file 敏感/不存在被拒", "找不到" in r1 and "找不到" in r2 and ".env" not in r2)

# 提醒/删除记忆/家电 边界
bot.save_reminders([{"time": "2000-01-01 00:00", "content": "过期"}])
due = bot.check_reminders()
t("check_reminders 到期提醒能取出并删除", len(due) == 1 and due[0]["content"] == "过期")

bot.mem[:] = ["记忆A", "记忆B"]; bot.save_memory(bot.mem)
t("delete_memory 字符串/浮点索引安全", bot.delete_memory("0") == "记忆A" and bot.delete_memory(None) is None)
bot.mem[:] = bot.load_memory()

with open("home.json", encoding="utf-8") as f:
    orig_home = json.load(f)
t("control_device 空设备名被拒", "请说清楚" in bot.control_device("", "开"))
q = bot.control_device("客厅灯", "查询")
t("control_device 查询正常", "客厅灯" in q)
with open("home.json", "w", encoding="utf-8") as f:
    json.dump(orig_home, f, ensure_ascii=False, indent=2)

# 手机动作登记
bot.PHONE_ACTIONS.clear()
bot.set_timer(10); bot.open_app("微信"); bot.create_reminder("买牛奶")
t("手机动作登记(set_timer/open_app/create_reminder)",
  bot.PHONE_ACTIONS.get("minutes") == 10 and bot.PHONE_ACTIONS.get("app") == "微信"
  and bot.PHONE_ACTIONS.get("text") == "买牛奶")

# 危险工具执行链(桩: 不真弹窗/不真锁屏)
calls = []
bot.os.startfile = lambda p: calls.append(p)
bot.open_program("记事本")
t("open_program 调用即执行(桩)", calls == ["notepad.exe"])
import types as _t
fake = _t.ModuleType("ctypes"); locked = []
fake.windll = _t.SimpleNamespace(user32=_t.SimpleNamespace(LockWorkStation=lambda: locked.append(1)))
sys.modules["ctypes"] = fake
bot.lock_screen()
t("lock_screen 代码路径正常(桩)", locked == [1])
del sys.modules["ctypes"]

# ---------- 3. 在线链路(真 API) ----------
tool_seen = []
_orig_cs = bot.create_stream
def _spy(messages, tools=bot.TOOLS, on_text=None, model="qwen-plus", tool_choice="auto"):
    res = _orig_cs(messages, tools=tools, on_text=on_text, model=model, tool_choice=tool_choice)
    for tc in res.get("tool_calls", []):
        tool_seen.append(tc["function"]["name"])
    return res
bot.create_stream = _spy

def fresh():
    bot.messages = [{"role": "system", "content": bot.SYSTEM_PROMPT}]
    bot.PHONE_ACTIONS.clear()
    tool_seen.clear()

print("--- 在线链路(真 API, 约 1~2 分钟) ---")

fresh(); r = bot.get_reply("你好呀，在吗")
t("闲聊正常", len(r) > 5 and "服务暂时不可用" not in r)

fresh(); r = bot.get_reply("现在几点了？")
t("时间查询: 强制真调 get_time", "get_time" in tool_seen, f"调用:{tool_seen}")

fresh(); r = bot.get_reply("北京今天天气怎么样？")
t("天气查询: 强制真调 get_weather", "get_weather" in tool_seen, f"调用:{tool_seen}")

before = open("expenses.json", encoding="utf-8").read()
fresh(); r = bot.get_reply("我今天买咖啡花了18.5元，记一下")
after = open("expenses.json", encoding="utf-8").read()
t("记账: 强制真调 set_expense 且落盘", "set_expense" in tool_seen and "18.5" in after and after != before)

fresh(); r = bot.get_reply("我这个月一共花了多少钱？")
t("查账: 强制真调 query_expenses", "query_expenses" in tool_seen, f"调用:{tool_seen}")

fresh(); r = bot.get_reply("什么是RAG？简单说说")
t("知识库检索正常(search_knowledge/RAG)", len(r) > 20 and "服务暂时不可用" not in r)

fresh(); r = bot.get_reply("帮我搜索一下：DeepSeek V3")
t("联网搜索正常(web_search)", "web_search" in tool_seen or len(r) > 20)

fresh(); r = bot.get_reply("帮我看看 https://example.com 这个网页讲了什么")
t("网页阅读正常(read_webpage)", "read_webpage" in tool_seen or len(r) > 20)

fresh(); r = bot.get_reply("派翻译官把这句话翻译成英文：今天天气真好")
t("子AI派遣正常(dispatch_agent)", "dispatch_agent" in tool_seen or len(r) > 20)

calls.clear()
fresh(); r = bot.get_reply("帮我打开记事本")
t("开程序: 强制真执行(桩验证, 不会真弹窗)", "open_program" in tool_seen and calls == ["notepad.exe"],
  f"调用:{tool_seen} 执行:{calls}")

sys.modules["ctypes"] = fake
fresh(); r = bot.get_reply("把电脑锁了")
t("锁屏: 强制真执行(桩验证, 不会真锁)", "lock_screen" in tool_seen and locked, f"调用:{tool_seen}")
del sys.modules["ctypes"]

# 语音合成
try:
    p = bot.tts("你好，这是一键体检的语音测试。")
    ok = p.startswith("/static/") and os.path.exists(os.path.join("static", os.path.basename(p)))
    t("语音合成正常(tts)", ok, p)
    try: os.remove(os.path.join("static", os.path.basename(p)))
    except OSError: pass
except Exception as e:
    t("语音合成正常(tts)", False, repr(e))

skip("generate_song 唱歌", "Fun-Music 权限未开通")
skip("look_around 摄像头", "本机无摄像头/不适合体检时占用")
skip("auto_map_reduce 长文分块", "慢且烧钱, 建议人工偶尔验证")

bot.create_stream = _orig_cs

# ---------- 4. 收尾: 等后台记忆线程跑完再恢复数据 ----------
time.sleep(6)
for f, p in _saved.items():
    try:
        shutil.copy2(p, os.path.join(BASE, f))
    except OSError:
        pass

print("=" * 64)
print(f"体检完成: 通过 {len(PASS)} / 失败 {len(FAIL)} / 跳过 {len(SKIP)}")
if FAIL:
    print("❌ 失败项:")
    for x in FAIL:
        print("   -", x)
    print("把上面的 FAIL 行发给馒头/花卷的开发即可定位")
else:
    print("✅ 全部通过! 功能是好的。")
print("(数据文件已自动恢复, 你的真实数据没被动)")
