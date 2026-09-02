import os
import json
import re
import time
import hashlib
import queue      
import threading 
from concurrent.futures import ThreadPoolExecutor  # 第3课：多手下并行干活靠它
import requests
from openai import OpenAI
import numpy as np
from bs4 import BeautifulSoup

from dotenv import load_dotenv
REMINDER_FILE = "reminders.json"
KNOWLEDGE_FILE = "knowledge_base.txt"
HISTORY_FILE = "history.json"
MEMORY_FILE = "memory.json"
VEC_CACHE_FILE = "memory_vecs.json"
STATUS_FILE = "status.json"
MOOD_FILE = "mood.json"
EXPENSE_FILE = "expenses.json"
SUMMARY_FILE = "summary.json"
FILES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "huajuan_files")
PENDING_WRITES = {}
PHONE_ACTIONS = {}  # 手机动作登记表：电脑上的工具只"开单子"，真动作由手机执行
READ_DIRS = [FILES_DIR, os.path.dirname(FILES_DIR)]
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

EXCLUDE_FILES = [".env"]

IDENTITY = "你是花卷，馒头的朋友和红颜知己。你心里清楚自己是个数字存在，没有身体，不装人，也从不觉得这有什么不好。"

def clean_aside(text):
    """删掉括号旁白（如"（托腮）""（小声）"），直播和最终回答共用这一把刀"""
    text = re.sub(r"（[^（）]*）", "", text)
    text = re.sub(r"\([^()]*\)", "", text)
    return text

def load_expenses():
    try:
        with open(EXPENSE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []

def save_expenses(items):
    with open(EXPENSE_FILE, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)

def query_expenses(month=None):
    items = load_expenses()
    if month:
        items = [x for x in items if x["date"].startswith(month)]
    total = sum(x["amount"] for x in items)
    lines = [f"{x['date']} {x['item']} {x['amount']}元" for x in items]
    return f"共{len(items)}笔，总支出{total}元：\n" + "\n".join(lines)

def expense_summary():
    month = time.strftime("%Y-%m")
    items = [x for x in load_expenses() if x["date"].startswith(month)]
    return {"month": month, "count": len(items), "total": sum(x["amount"] for x in items)}

def check_reminders():
    """找出所有到点的提醒，从文件里删掉，返回它们"""
    items = load_reminders()
    now = time.strftime("%Y-%m-%d %H:%M")
    due = [x for x in items if x["time"] <= now]
    if due:
        save_reminders([x for x in items if x["time"] > now])
    return due

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_time",
            "description": "查询现在的日期、时间和星期",
            "parameters": {"type": "object", "properties": {}}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "查询指定城市的当前天气，用户问到天气时调用",
            "parameters": {
                "type": "object",
                "properties": {
                    "city": {
                        "type": "string",
                        "description": "城市名。用户明确说了城市才填；没说就留空"
                    }
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "set_reminder",
            "description": "给用户设提醒。用户说'提醒我…'时使用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "remind_time": {
                        "type": "string",
                        "description": "提醒时间，格式 YYYY-MM-DD HH:MM。相对时间（如'一小时后'）必须先调 get_time 拿到当前时间再换算成绝对时间"
                    },
                    "content": {"type": "string", "description": "提醒内容"}
                },
                "required": ["remind_time", "content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "set_expense",
            "description": "记账。用户说'花了…钱/花了…块/消费了'时使用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "item": {"type": "string", "description": "买了什么"},
                    "amount": {"type": "number", "description": "金额，数字，如 4.5"}
                },
                "required": ["item", "amount"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "query_expenses",
            "description": "查询记账记录和总支出。用户问'花了多少钱/花销'时使用。",
            "parameters": {
                "type": "object",
                "properties": {"month":{"type":"string",
                         "description": "月份，格式 YYYY-MM，如 2026-08。用户明确说了'这个月/某月'才填，没说就留空"   
                         }
                        },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "read_webpage",
            "description": "阅读一个网页并返回主要内容。用户发来网址链接、或说'看看这个网页/这个链接讲了什么'时使用",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "完整网址，必须以 http:// 或 https:// 开头。用户没给网址就不要调用，先问用户要"
                    }
                },
                "required": ["url"]
            }
        }
    }
        ,{
        "type": "function",
        "function": {
            "name": "list_files",
            "description": "列出文件盒（huajuan_files文件夹）里的所有文件名。用户提到文件盒/你有哪些文件时必须调用本工具获取实时清单，即使对话中出现过文件信息也不许凭记忆回答，记忆可能过期或错误,可以读文件盒和项目文件夹（D:\python）里的文件",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "读取文件盒里某个文件的内容。用户想看某个文件写了什么时必须调用本工具读取实时内容，即使对话中见过该文件的内容也不许凭记忆背诵。只接受文件名如 心愿清单.txt，不接受带路径的写法,可以读文件盒和项目文件夹（D:\python）里的文件",
            "parameters": {
                "type": "object",
                "properties": {
                    "filename": {
                        "type": "string",
                        "description": "文件名，如 心愿清单.txt，不要带路径或斜杠"
                    }
                },
                "required": ["filename"]
            }
        }
    },
        {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "把内容写进文件盒里的文件。必须分两步：第一次调用不要传confirm（默认false），只登记不写入；等用户明确回复同意后，再次调用并传confirm=true才真正写入。禁止跳过确认直接传true。收到'尚未写入磁盘'的返回时，绝不允许对用户声称已写入，必须如实转告在等确认",
            "parameters": {
                "type": "object",
                "properties": {
                    "filename": {
                        "type": "string",
                        "description": "文件名，如 便签.txt，不带路径"
                    },
                    "content": {
                        "type": "string",
                        "description": "要写入的完整内容"
                    },
                    "confirm": {
                        "type": "boolean",
                        "description": "用户明确同意后才传true，其余情况一律不传或传false"
                    }
                },
                "required": ["filename", "content"]
            }
        }
    },
    {
    "type": "function",
    "function": {
        "name": "web_search",
        "description": "联网搜索外部信息。当被问到书籍、小说、新闻、人物、时事等你不知道的知识时调用。自己知识库里没有的内容优先搜索，而不是直接说不知道",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "搜索关键词，提炼自用户的问题，如'神秘复苏 小说 简介'"}
            },
            "required": ["query"]
        }
    }
},
    {
        "type": "function",
        "function": {
            "name": "generate_song",
            "description": "唱歌。当用户让你唱歌、唱首歌、写首歌、来一首时调用。花卷自己写词自己唱，主题从用户的话里提炼",
            "parameters": {
                "type": "object",
                "properties": {
                    "theme": {"type": "string", "description": "歌曲主题或情绪，提炼自用户的话，如'一首关于夏天的歌'、'哄我开心的歌'、'写给我妈妈的歌'"}
                },
                "required": ["theme"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "set_timer",
            "description": "让用户的手机设一个倒计时。用户说'设置X分钟倒计时/闹钟'时使用。登记后手机会响铃，使用前先向用户确认。",
            "parameters": {
                "type": "object",
                "properties": {
                    "minutes": {"type": "number", "description": "倒计时分钟数，如 10"}
                },
                "required": ["minutes"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "open_app",
            "description": "帮用户打开手机上的应用。用户说'打开微信/打开相机'时使用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "app_name": {"type": "string", "description": "应用名，如 微信、相机、音乐"}
                },
                "required": ["app_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "create_reminder",
            "description": "往用户手机添加一条提醒事项。用户说'提醒我明天…/记一下…'是手机事项时使用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "提醒的内容"}
                },
                "required": ["text"]
            }
        }
    },
{
    "type": "function",
    "function": {
            "name": "open_program",
            "description": "打开电脑上的程序或网站（如微信、QQ、记事本、计算器、哔哩哔哩、抖音、知乎等，PROGRAM_LIST 里登记的都算）。使用前先向用户确认。",
        "parameters": {
            "type": "object",
            "properties": {
                "program_name": {
                    "type": "string",
                    "description": "程序名字，如：微信"
                }
            },
            "required": ["program_name"]
        }
    }
},
    {
        "type": "function",
        "function": {
            "name": "take_screenshot",
            "description": "截取当前电脑屏幕并保存。用户说'截屏/截个图'时使用。使用前先向用户确认。",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "lock_screen",
            "description": "锁定电脑屏幕。用户说'锁屏/把电脑锁了'时使用。使用前必须先向用户确认。",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
{
    "type": "function",
    "function": {
        "name": "search_knowledge",
        "description": "查询本地知识库。用户问概念、知识、事实类问题（如'什么是RAG''embedding是什么'）时，先调用此工具查资料，再基于资料回答",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "检索关键词"}
            },
            "required": ["query"]
        }
    }
},
{
    "type": "function",
    "function": {
        "name": "dispatch_agent",
        "description": "从手下的子AI名册里挑一个干活：翻译找翻译官、写文案找文案师、整理长资料找资料员、写代码找代码员。判定规则：①用户明确说「派手下/找XX/让XX干/派个AI」时必须调用本工具，先调用再说话，不许只口头说'已派/派去啦'；②用户贴了大段文字要翻译/总结/整理时也应派出去；③随手的小翻译、两句话的文案直接自己干，不用派。用户一次要多个手下干活（如'同时派翻译官和文案师'）时，本回合可以连续发出多个 dispatch_agent 调用，一个手下一次调用。调用时把任务写成完整任务单交给它，等结果回来必须把每个手下给的结果内容完整转述（译文念译文、要点列要点、文案贴文案），不许只点评不转述、不许漏贴",
        "parameters": {
            "type": "object",
            "properties": {
                "agent": {"type": "string", "enum": ["翻译官", "文案师", "资料员", "代码员"], "description": "从名册里挑谁干"},
                "task": {"type": "string", "description": "交给子AI的完整任务描述，要说清要求"}
            },
            "required": ["agent", "task"]
        }
    }
},

]







MAX_MESSAGES = 20
# messages 是全局共享状态，Flask 多线程下可能串话，加把锁
chat_lock = threading.Lock()


load_dotenv()
api_key = os.getenv("DASHSCOPE_API_KEY")
tavily_key = os.getenv("TAVILY_API_KEY")
# 唱歌走北京地域专用 key（Fun-Music 只认华北2的 key），没配则退回聊天 key
bjs_key = os.getenv("BJS_API_KEY") or api_key
workspace_id = "ws-jyr680etwmdpmwjy"
if not api_key:
    print("警告：.env 里没有配置 DASHSCOPE_API_KEY，所有接口调用都会失败")
client = OpenAI(
    api_key=api_key or "missing-key",
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"
)

def get_time():
    from datetime import datetime
    now = datetime.now()
    return now.strftime("%Y-%m-%d %H:%M") + " 周" + "一二三四五六日"[now.weekday()]
user_location = {"lat": None, "lon": None}
def get_weather(city):
    try:
        if city:
            query = city
        elif user_location["lat"] is not None:
            query = str(user_location["lat"]) + "," + str(user_location["lon"])
        else:
            return "没拿到城市，也没定位信息，问一下用户想查哪里"
        r = requests.get("https://wttr.in/" + query, params={"format": "j1", "lang": "zh"}, timeout=8)
        cur = r.json()["current_condition"][0]
        return f"查询地({query})现在{cur['lang_zh'][0]['value']}，气温{cur['temp_C']}℃，体感{cur['FeelsLikeC']}℃，湿度{cur['humidity']}%"
    except Exception as e:
        return f"查天气失败了：{e}"

def load_reminders():
    try:
        with open(REMINDER_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []

def save_reminders(items):
    with open(REMINDER_FILE, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)
def read_webpage(url):
    try:
        r = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        r.encoding = r.apparent_encoding
        soup = BeautifulSoup(r.text, "html.parser")
        title = soup.title.string.strip() if soup.title and soup.title.string else ""
        for tag in soup(["script", "style"]):
            tag.decompose()
        text = soup.get_text(separator="\n")
        lines = [ln.strip() for ln in text.split("\n")]
        text = "\n".join(ln for ln in lines if ln)
        if len(text) > 3000:
            text = text[:3000] + "\n...（正文太长，只取了前3000字）"
        if len(text) < 200:
            more = read_webpage_browser(url)
            if len(more) > len(text):
                return more    
        if title:
            return "标题：" + title + "\n\n" + text
        return text
    except Exception as e:
        return "网页打开失败：" + str(e)
def web_search(query):
    """联网搜索：把关键词发给 Tavily，拿回几条网页摘要"""
    try:
        r = requests.post(
            "https://api.tavily.com/search",
            headers={"Authorization": "Bearer " + (tavily_key or "missing-key")},
            json={"query": query, "max_results": 3},
            timeout=15,
        )
        data = r.json()
        results = data.get("results", [])
        if not results:
            return "没搜到相关内容"
        parts = []
        for i, item in enumerate(results, 1):
            parts.append(f"{i}. {item.get('title', '')}\n   {item.get('url', '')}\n   {item.get('content', '')}")
        return "\n\n".join(parts)
    except Exception as e:
        return "搜索失败：" + str(e)
# 第18个工具：子AI名册（给手下上编制）。每个成员的"专长"= 它的 system 人设
AGENTS = {
    "翻译官": "你是翻译官，负责一切语言转换。收到任务直接给译文，保留原意和语气，不要解释过程。",
    "文案师": "你是文案师，负责写各种文案。写出的东西要有网感、抓人眼球，但别浮夸油腻。直接给成品。",
    "资料员": "你是资料员，负责把长资料整理清楚。输出结构清晰的要点或摘要，直接给结果。",
    "代码员": "你是代码员，负责写代码。直接给能跑的完整代码，需要时配一句简短说明，不要客套。",
}

def dispatch_agent(agent, task):
    """第18个工具：从名册挑一个子AI干活。子AI不带人设、不带记忆、只带一张任务单"""
    if agent not in AGENTS:
        return f"名册里没有「{agent}」，现在登记的有：{'、'.join(AGENTS.keys())}"
    resp = client.chat.completions.create(
        model="qwen-plus",
        messages=[
            {"role": "system", "content": AGENTS[agent]},
            {"role": "user", "content": str(task)},
        ],
        temperature=0.7,
        max_tokens=2000,
    )
    return resp.choices[0].message.content.strip() or "子AI没给出结果"

# ============ 第4课 map-reduce：大任务拆给手下分头干 ============
def split_long_text(text, max_len):
    """把长文切成每块不超过 max_len 字的列表。切法：先按换行断段，段内再按句末标点断句，
    句子比 max_len 还长就硬切——保证每块都是完整的语义单元，资料员才读得懂"""
    units = []                          # 第一步：磨成最小单元（句子）
    for para in text.split("\n"):
        para = para.strip()
        if not para:
            continue
        units.extend(re.split(r'(?<=[。！？!?])', para))
    blocks, cur = [], ""                # 第二步：句子攒成块，够一斗就封斗
    for u in units:
        u = u.strip()
        if not u:
            continue
        if len(u) > max_len:            # 碰到超长句，硬切
            if cur:
                blocks.append(cur)
                cur = ""
            for i in range(0, len(u), max_len):
                blocks.append(u[i:i + max_len])
        elif len(cur) + len(u) <= max_len:
            cur += u
        else:
            blocks.append(cur)
            cur = u
    if cur:
        blocks.append(cur)
    return blocks

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

def generate_song(theme):
    """花卷点歌：自己写词，Fun-Music 谱曲演唱，下载到本地返回播放地址"""
    try:
        # 第1步：花卷自己写歌词（带结构标签，控制在300字内）
        lyric_resp = client.chat.completions.create(
            model="qwen-plus",
            messages=[{"role": "user", "content": (
                "你是歌手花卷，根据下面的主题写一首中文歌词。"
                "要求：用[verse]标记主歌、[chorus]标记副歌、[bridge]标记桥段，"
                "全曲不超过300字，直接输出歌词，不要客套。\n\n主题：" + theme
            )}],
            temperature=0.8,
            max_tokens=800,
        )
        lyrics = lyric_resp.choices[0].message.content.strip()
        if not lyrics:
            return "歌词没写成，再说一次试试？"

        # 第2步：调 Fun-Music 生成歌曲（prompt 和 lyrics 同传只认 lyrics，所以只传歌词）
        r = requests.post(
            "https://" + workspace_id + ".cn-beijing.maas.aliyuncs.com/api/v1/services/audio/music/generation",
            headers={"Authorization": "Bearer " + bjs_key},
            json={
                "model": "fun-music-v1",
                "input": {"lyrics": lyrics, "gender": "female"},
            },
            timeout=120,   # 生成一首歌要几十秒到两分钟
        )
        data = r.json()
        audio_url = data["output"]["audio"]["url"]

        # 第3步：下载到本地（线上链接24小时就失效，必须存下来）
        song_resp = requests.get(audio_url, timeout=120)
        filename = "song_" + hashlib.md5(theme.encode()).hexdigest()[:8] + ".mp3"
        with open(os.path.join("static", filename), "wb") as f:
            f.write(song_resp.content)
        return "唱好了！播放地址：/static/" + filename
    except Exception as e:
        return "唱歌失败：" + str(e)
   
def read_webpage_browser(url):
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url, timeout=30000)
            page.wait_for_load_state("domcontentloaded")
            page.wait_for_timeout(3000)
            text = page.inner_text("body")
            title = page.title().strip()
            browser.close()
        lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
        text = "\n".join(lines)
        if len(text) > 3000:
            text = text[:3000] + "\n...（正文太长，只取了前3000字）"
        if title:
            return "标题：" + title + "\n\n" + text    
        return text
    except Exception as e:
        return "无头浏览器打开失败：" + str(e)
def safe_read_path(filename):
    """读权限：整个授权清单都能看，还要过敏感文件黑名单"""
    if os.path.basename(filename) in EXCLUDE_FILES:
        return None
    for d in READ_DIRS:
        path = os.path.abspath(os.path.join(d, filename))
        if path.startswith(d + os.sep) and os.path.exists(path):
            return path
    return None

def safe_write_path(filename):
    """写权限：只认文件盒，一个字都不许出去"""
    path = os.path.abspath(os.path.join(FILES_DIR, filename))
    if path.startswith(FILES_DIR + os.sep):
        return path
    return None


def list_files():
    try:
        lines = []
        for d in READ_DIRS:
            label = "文件盒" if d == FILES_DIR else "项目文件夹"
            names = [n for n in os.listdir(d)
                     if os.path.isfile(os.path.join(d, n))
                     and n not in EXCLUDE_FILES]
            lines.append("【" + label + "】" + (", ".join(names) if names else "空"))
        return "\n".join(lines)
    except Exception as e:
        return "列文件失败：" + str(e)


def read_file(filename):
    path = safe_read_path(filename)
    if path is None:
        return "找不到能读的「" + filename + "」。我只能读授权清单里的文件，敏感文件一律不给看"
    try:
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
        if len(text) > 3000:
            text = text[:3000] + "\n...（文件太长，只取了前3000字）"
        return text
    except FileNotFoundError:
        return "文件盒里没有叫「" + filename + "」的文件"
    except Exception as e:
        return "读文件失败：" + str(e)
def write_file(filename, content, confirm=False):
    path = safe_write_path(filename)
    if path is None:
        return "这个文件不在我的文件盒里，只能写 huajuan_files 文件夹里的文件"
    if confirm is not True:
        PENDING_WRITES[path] = content
        warn = ""
        if os.path.exists(path):
            warn = "（注意：文件已存在，写入会整份覆盖）"
        return "已登记待写入「" + filename + "」，共" + str(len(content)) + "字" + warn + "，尚未写入磁盘。请如实转告用户：内容还没写入，在等确认。用户明确同意后，再次调用write_file，filename和content必须与本次完全一致，并传confirm=true"
    old = PENDING_WRITES.get(path)
    if old != content:
        return "这次的内容和用户确认过的不一致，尚未写入磁盘。请如实转告用户并重新请求确认"
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        PENDING_WRITES.pop(path, None)
        return "已写入「" + filename + "」"
    except Exception as e:
        return "写文件失败：" + str(e)

def set_reminder(remind_time, content):
    try:
        from datetime import datetime
        datetime.strptime(remind_time, "%Y-%m-%d %H:%M")   # 校验格式，不对会抛异常
        items = load_reminders()
        items.append({"time": remind_time, "content": content})
        save_reminders(items)
        return f"已记住：{remind_time} 提醒你 {content}"
    except Exception as e:
        return f"设提醒失败：{e}"
    
def set_timer(minutes):
    """手机倒计时工具：只登记，不真的计时"""
    PHONE_ACTIONS["action"] = "set_timer"
    PHONE_ACTIONS["minutes"] = int(minutes)
    return f"手机倒计时已登记：{minutes} 分钟。请如实转告用户：手机会在 {minutes} 分钟后响铃，等他同意后再执行。"

def open_app(app_name):
    """打开手机应用工具：只登记，不真的打开"""
    PHONE_ACTIONS["action"] = "open_app"
    PHONE_ACTIONS["app"] = app_name
    return f"打开应用已登记：{app_name}。请如实转告用户：将为他打开 {app_name}，等他同意后再执行。"

def create_reminder(text):
    """手机提醒事项工具：只登记，不真的写入"""
    PHONE_ACTIONS["action"] = "create_reminder"
    PHONE_ACTIONS["text"] = text
    return f"提醒事项已登记：{text}。请如实转告用户：提醒已准备好，等他同意后再加到手机里。"

def open_program(program_name):
    path = PROGRAM_LIST.get(program_name)
    if path is None:
        return f"找不到程序「{program_name}」，目前登记的有：{'、'.join(PROGRAM_LIST.keys())}"
    os.startfile(path)
    return f"已在电脑上打开 {program_name}。"

def take_screenshot():
    from PIL import ImageGrab
    from datetime import datetime
    now = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"屏幕截图_{now}.png"
    path = os.path.join(r"D:\python\screenshots", filename)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    img = ImageGrab.grab()
    img.save(path)
    return f"已截屏，文件名 {filename}，存在 {path}"


def lock_screen():
    import ctypes
    ctypes.windll.user32.LockWorkStation()
    return "已锁屏。"

def set_expense(item, amount):
    try:
        date = time.strftime("%Y-%m-%d")
        items = load_expenses()
        items.append({"date": date, "item": item, "amount": amount})
        save_expenses(items)
        return f"已记：{date} 买{item}花了{amount}元"
    except Exception as e:
        return f"记账失败：{e}"

    
def create_stream(messages, tools=TOOLS,on_text=None):
    stream = client.chat.completions.create(
        model="qwen-plus",
        messages=messages,
        temperature=0.8,
        max_tokens=4000,
        top_p=0.9,
        tools=tools,
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

def load_knowledge(file_path):
    with open(file_path, 'r', encoding='utf-8') as f:
        return [line.strip() for line in f if line.strip()]

def add_knowledge(text):
    global _kb_embeddings
    knowledge_base.append(text)
    _kb_embeddings = None  # 知识库变了，向量缓存作废
    with open(KNOWLEDGE_FILE, 'a', encoding='utf-8') as f:
        f.write(text + '\n')

knowledge_base = load_knowledge(KNOWLEDGE_FILE)
_kb_embeddings = None  # 知识库向量缓存，避免每次检索都重新算全库向量
_mem_embeddings = None  # 记忆向量缓存，记忆变了才重算

def get_embedding(texts):
    """获取文本的向量表示，自动分批（每批最多10条）"""
    batch_size = 10
    all_embeddings = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]
        response = client.embeddings.create(
            model="text-embedding-v3",
            input=batch
        )
        all_embeddings.extend([item.embedding for item in response.data])
    return all_embeddings

def get_kb_embeddings():
    global _kb_embeddings
    if _kb_embeddings is None:
        _kb_embeddings = get_embedding(knowledge_base) if knowledge_base else []
    return _kb_embeddings

def cosine_similarity(a, b):
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    if na == 0 or nb == 0:
        return 0.0
    return np.dot(a, b) / (na * nb)

def top_k_search(query, k=3, threshold=0.35):
    """相似度低于 threshold 的知识直接丢弃，返回可能为空列表"""
    if not knowledge_base:
        return []
    query_vec = get_embedding([query])[0]
    kb_vecs = get_kb_embeddings()
    sims = [(i, cosine_similarity(query_vec, v)) for i, v in enumerate(kb_vecs)]
    sims.sort(key=lambda x: x[1], reverse=True)

    results = []
    for i, score in sims:
        if score >= threshold and len(results) < k:
            results.append(knowledge_base[i])
    return results

def search_knowledge(query):
    """调用工具，查本地知识库"""
    results = top_k_search(query, k=3, threshold=0.35)
    if not results:
        return "知识库里没找到相关内容"
    return "\n\n".join(results)

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
    query_vec = get_embedding([query])[0]
    sims = [(i, cosine_similarity(query_vec, v)) for i, v in enumerate(_mem_embeddings)]
    sims.sort(key=lambda x: x[1], reverse=True)
    results = []
    for i, score in sims:
        if score >= threshold and len(results) < k:
            results.append(mem[i])
    return results

with open("persona.txt", "r", encoding="utf-8") as f:
    SYSTEM_PROMPT = f.read()

def load_history():
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return [{"role": "system", "content": SYSTEM_PROMPT}]

def load_memory():
    try:
        with open(MEMORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []

def load_mood():
    try:
        with open(MOOD_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
def save_mood(data):
    with open(MOOD_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def save_history(messages):
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(messages, f, ensure_ascii=False, indent=2)

def save_memory(memory):
    global _mem_embeddings
    _mem_embeddings = None  # 记忆变了，向量缓存作废
    with open(MEMORY_FILE, "w", encoding="utf-8") as f:
        json.dump(memory, f, ensure_ascii=False, indent=2)

def delete_memory(index):
    """删除指定索引的记忆"""
    global mem 
    if 0 <= index < len(mem):
        removed = mem.pop(index)
        save_memory(mem)
        return removed
    return None

def load_status():
    try:
        with open(STATUS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"status": "", "updated": ""}

def save_status(data):
    with open(STATUS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def update_status():
    """过了今天就让花卷自己想想最近的近况，更新近况"""
    data = load_status()
    today = time.strftime("%Y-%m-%d")
    if data.get("updated") == today:
        return data.get("status", "")

    if data.get("status"):
        prompt = (
            IDENTITY+f"你之前的近况是：{data['status']}。"
            "过了几天了，你想想这几天关注了什么、整理了什么，现在在做什么。"
            "你是数字存在，近况应该是'在回顾和馒头的聊天记录''整理记忆时翻到之前的事'这类，"
            "不要出现吃喝、睡觉、充电、出门这些身体行为。"
            "用一句话陈述现在的状态，像微信个人签名一样简单平实。"
            "只陈述事实本身，不要动作描写，不要场景描写，不要文艺腔。"
        )
    else:
        prompt = (
            IDENTITY
            + "想想你最近在做什么，作为数字存在，你的近况应该是'在整理记忆''回顾聊天记录'这类，"
            "不要出现吃喝、睡觉、充电、出门这些身体行为。"
            "用一句话陈述现在的状态，像微信个人签名一样简单平实。只陈述事实本身，"
            "不要动作描写，不要场景描写，不要文艺腔。"
        )
    resp = client.chat.completions.create(
        model="qwen-plus",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt}
        ],
        temperature=0.8,
        max_tokens=100,
    )
    new_status = resp.choices[0].message.content.strip()
    data["status"] = new_status
    data["updated"] = today
    save_status(data)
    return new_status

def mood_shift(user_input, reply):
    """根据用户输入和回复调整心情"""
    prompt = (
        IDENTITY+f"你现在的近况：{load_status().get('status','')}，心情：{load_mood().get('mood','')}。"
        f"用户说了：{user_input}，你回复了：{reply}。"
        "结合这些信息判断：这段对话是否明显影响你的心情。注意：只是打招呼、寒暄、日常问答（比如“嗯”“好”“今天天气怎么样”“吃了没”）不算心情变化；但如果对方的话明显影响你，一定要变，方向要贴合内容：被夸→更开心了😊，被骂→有点小委屈😢或有点生气😠，对方倾诉烦恼、难过→有点心疼😔，离别→更失落了😕。心情有变化时，只输出上面的心情和emoji，不要解释原因，不要加别的字；没有变化就只回复两个字：无。记住：你是倾听的一方，对方难过你也跟着心疼、低落，绝不会因为他向你倾诉而开心。"
        "平实一点，不要场景描写，不要文艺腔，不要小作文。"
        "如果不会（对话平淡、心情维持原样），就只回复两个字：无"
    )
    resp = client.chat.completions.create(
        model="qwen-plus",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt}
        ],
        temperature=0.3,
        max_tokens=100,
    )
    return resp.choices[0].message.content.strip()

def update_mood():
    """过了今天就让花卷自己想想最近的心情，更新心情"""
    data = load_mood()
    today = time.strftime("%Y-%m-%d")
    if data.get("updated") == today:
        return data.get("mood", "")
    status_data = load_status()
    prompt = (
        IDENTITY+f"你现在的近况：{status_data.get('status','')}。"
        "结合这个近况，只回一句简单的心情+emoji，比如'有点小开心 😄'。"
        "平实一点，不要场景描写，不要文艺腔。"
    )
    resp = client.chat.completions.create(
        model="qwen-plus",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt}
        ],
        temperature=0.8,
        max_tokens=100,
    )
    new_mood = resp.choices[0].message.content.strip()
    data["mood"] = new_mood
    data["updated"] = today
    save_mood(data)
    return new_mood

SEEN_FILE = "seen.json"

def load_seen():
    try:
        with open(SEEN_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"last_seen": ""}

def save_seen(data):
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def get_greeting():
    """馒头离开超过2小时再回来，花卷主动说第一句话；平时不说话"""
    data = load_seen()
    now = time.time()
    if data.get("last_seen"):
        try:
            last = time.mktime(time.strptime(data["last_seen"], "%Y-%m-%d %H:%M"))
        except ValueError:
            last = 0
    else:
        last = 0

    # 不管说不说话，都先把"这次见面时间"记下来
    save_seen({"last_seen": time.strftime("%Y-%m-%d %H:%M")})

    gap_hours = (now - last) / 3600
    if last == 0 or gap_hours < 2:
        return ""   # 第一次见面或刚分开不久，不主动搭话

    if gap_hours >= 48:
        hint = f"馒头已经{int(gap_hours // 24)}天没来找你了，他刚刚上线了"
    elif gap_hours >= 24:
        hint = "馒头隔了一整天没来，他刚刚上线了"
    else:
        hint = f"馒头离开了大概{int(gap_hours)}个小时，他刚刚上线了"

    status_data = load_status()
    mood_data = load_mood()
    prompt = (
        IDENTITY
        + f"你现在的近况：{status_data.get('status','')}，心情：{mood_data.get('mood','')}。"
        + f"情况：{hint}。"
        + "请以花卷的身份主动跟馒头说第一句话，一两句就好，"
        "可以带点小情绪（等久了、想念、假装生气都可以）。"
        "像真人发微信那样说人话：不要括号动作描写，不要场景描写，"
        "不要每次都提你的偏好，不上价值不煽情。只说这句话本身。"
    )
    resp = client.chat.completions.create(
        model="qwen-plus",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt}
        ],
        temperature=0.8,
        max_tokens=100,
    )

    return resp.choices[0].message.content.strip()

def clear_history():
    global messages
    with chat_lock:
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
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
        with open(SUMMARY_FILE, "r", encoding="utf-8") as f:
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
    return resp.choices[0].message.content.strip()
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
TOOL_FUNCS = {
    "get_time": get_time,
    "get_weather": get_weather,
    "set_reminder": set_reminder,
    "set_expense": set_expense,
    "query_expenses": query_expenses,
    "read_webpage": read_webpage,
    "list_files": list_files,
    "read_file": read_file,
    "write_file": write_file,
    "web_search": web_search,
    "generate_song": generate_song,
    "set_timer": set_timer,
    "open_app": open_app,
    "create_reminder": create_reminder,
    "open_program": open_program,
    "take_screenshot": take_screenshot,
    "lock_screen": lock_screen,
    "search_knowledge": search_knowledge,
    "dispatch_agent": dispatch_agent,


}
# ===== 知识题硬性判断：规则引擎（关键词匹配，确定性，不会看走眼）=====
KNOWLEDGE_KEYWORDS = ["什么是", "是什么", "怎么用", "如何", "原理", "区别", "对比",
                      "rag", "embedding", "向量", "检索", "召回", "token", "flask",
                      "api", "prompt", "流式", "sse", "函数调用", "工具调用", "agent", "智能体"]

def looks_like_knowledge(text):
    """规则引擎：像知识题就返回 True"""
    low = text.lower()
    return any(kw in low for kw in KNOWLEDGE_KEYWORDS)

def get_reply(user_input, print_stream=False, on_text=None, on_tool=None):
    """输入问题，返回回答。print_stream=True 时边生成边打印（命令行用）"""
    # 防御：接口传进来的不一定是字符串
    user_input = str(user_input) if user_input is not None else ""
    PHONE_ACTIONS.clear()  # 每轮开头清空登记，防止上一轮的"单子"残留被下轮带走

    with chat_lock:  # 防止多线程并发时 messages 串话
        user_msg = user_input
        # 知识题硬性兜底：命中关键词就强制检索并注入资料，模型没有"不查"的选项
        if looks_like_knowledge(user_msg):
            kb = top_k_search(user_msg, k=2)
            if kb:
                user_msg += "\n\n【知识库资料】\n" + "\n".join(kb) + "\n（以上是知识库检索到的内容，请基于它回答；如与问题无关可忽略）"
        # 第4课 map-reduce 兜底：超长文本+总结意图 → 自动拆块并行派资料员，把各块摘要注入给主模型合并。
        # 同款思路：模型没有"硬啃长文"的选项——它拿到的已经是手下们嚼碎喂好的料
        mr_note = auto_map_reduce(user_msg)
        map_reduce_triggered = bool(mr_note)   # 新增：记录本轮是否走了 map-reduce
        if mr_note:
            user_msg += mr_note

    messages.append({"role": "user", "content": user_msg})

    system_msg = [m for m in messages if m["role"] == "system"]
    summary = load_summary()
    if summary.get("summary"):
            system_msg = system_msg + [{"role": "system", "content": "更早对话的摘要：\n" + summary["summary"]}]

    non_system = [m for m in messages if m["role"] != "system"]
                # RAG 记忆召回：每轮按当前问题现场检索，只带相关的，用完即扔不进 history
    # 包 try：召回失败（比如接口欠费/超时）只损失记忆，不拖垮整轮聊天
    try:
        recalled = retrieve_memory(user_input, k=3, threshold=0.55)
    except Exception as e:
        print("记忆召回失败（跳过，不影响聊天）：", e)
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
        
    messages_to_send = system_msg + non_system[-MAX_MESSAGES:]

    failed = False
       
    try:
            base = len(messages)
            result = create_stream(messages_to_send, on_text=on_text)
            steps = 0
            while result["finish_reason"] == "tool_calls" and steps < 5:
                steps += 1
                msg = {"role": "assistant", "content": "", "tool_calls": result["tool_calls"]}  # content 传空：防止模型把第一轮过渡话当成已回复，第二轮不转述工具结果
                messages.append(msg)
                # 第3课：多手下并行开工——原来 for 串行（翻译官干等文案师），
                # 现在线程池同时跑，谁都不等谁。on_tool 是 queue.Queue（线程安全）；
                # dispatch_agent 调子AI是网络IO，天然适合并行；pool.map 保持结果顺序，tool 消息不乱
                def run_one(tc):
                    if on_tool:
                        on_tool(tc["function"]["name"], json.loads(tc["function"]["arguments"]))
                    fn = TOOL_FUNCS[tc["function"]["name"]]
                    args = json.loads(tc["function"]["arguments"])
                    return tc["id"], str(fn(**args))
                with ThreadPoolExecutor(max_workers=4) as pool:
                    executed = list(pool.map(run_one, result["tool_calls"]))
                for tc_id, content in executed:
                    messages.append({"role": "tool", "tool_call_id": tc_id, "content": content})
                result = create_stream(messages, on_text=on_text)
            full_reply = result["content"]or "工具调太多次了，我先刹住了，换个说法再问我一次？"

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

    return full_reply


print("ai智能机器人已启用（输入 exit 退出，输入 add 添加知识）\n")
messages = load_history()
# 清掉上次运行时注入的近况/心情/记忆 system 消息，只保留人设，
# 防止每重启一次程序就多攒一份，越积越多把对话撑爆
if len(messages) > 1:
    messages = [messages[0]] + [m for m in messages[1:] if m["role"] != "system"]
mem = load_memory()
current_status = update_status()
if current_status:
    messages.append({"role": "system", "content": "花卷的近况：" + current_status})
current_mood = update_mood()
if current_mood:
    messages.append({"role": "system", "content": "花卷的心情：" + current_mood})


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

def tts(text, filename="tts_latest.wav"):
    """文字转语音：长文本自动切成小段分别合成，再拼接成一个 wav"""
    import urllib.request
    import urllib.error
    import json as _json
    import wave

    # 缓存：用文字的 MD5 当文件名，同一段文字只合成一次
    filename = hashlib.md5(text.encode("utf-8")).hexdigest()[:16] + ".wav"
    save_path = os.path.join("static", filename)
    if os.path.exists(save_path):
        return "/static/" + filename   # 已有现成音频，秒回

    # ---------- 第1步：切段 ----------
    # 思路和第4课 split_long_text 一样：优先按句子切，切不出就攒
    def split_sentences(long_text, max_len=300):
        parts = []                     # 切好的段都放这里
        current = ""                   # 正在攒的当前段
        for ch in long_text:
            current += ch
            # 碰到句末标点，且当前段已经攒够 100 字，就封一段
            # （"攒够100字"是防止全是短句时切得太碎，一段只有一句话）
            if ch in "。！？?!\n" and len(current) >= 100:
                parts.append(current)
                current = ""
        if current.strip():            # 最后剩下的尾巴不够 100 字也要
            parts.append(current)
        # 保险：极端情况一整段没有任何标点，按 max_len 硬切
        final = []
        for p in parts:
            while len(p) > max_len:
                final.append(p[:max_len])
                p = p[max_len:]
            if p.strip():
                final.append(p)
        return final

    # ---------- 第2步：单段合成（就是原来 tts 的主体，text 换成 piece） ----------
    def synth_one(piece, i):
        url = "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation"
        headers = {
            "Authorization": "Bearer " + api_key,
            "Content-Type": "application/json",
        }
        body = {
            "model": "qwen-tts",
            "input": {"text": piece},
            "voice": "longxiaochun_v2",
            "parameters": {"format": "wav", "sample_rate": 32000},
        }
        req = urllib.request.Request(url, data=_json.dumps(body).encode("utf-8"), headers=headers)
        with urllib.request.urlopen(req, timeout=60) as r:
            resp = _json.load(r)
        audio_url = resp["output"]["audio"].get("url")
        if not audio_url:
            raise Exception("语音接口没返回音频地址: " + _json.dumps(resp, ensure_ascii=False))
        # 下载成临时小文件，文件名带段号，防止几段互相覆盖
        part_path = os.path.join("static", "tts_part_" + str(i) + ".wav")
        urllib.request.urlretrieve(audio_url, part_path)
        return part_path

    # ---------- 第3步：并行合成（照第3课 run_one 描红） ----------
    parts = split_sentences(text)
    def synth_job(pair):              # pair 是 (段号, 段文字) 的打包件
        i, piece = pair               # 拆包：段号给 i，文字给 piece
        return synth_one(piece, i)
    part_paths = []
    try:
        with ThreadPoolExecutor(max_workers=4) as pool:
            part_paths = list(pool.map(synth_job, enumerate(parts)))

        # ---------- 第4步：wave 拼接 ----------
        with wave.open(save_path, "wb") as out_wav:
            first_fmt = None
            for pp in part_paths:
                with wave.open(pp, "rb") as w:
                    fmt = (w.getnchannels(), w.getsampwidth(), w.getframerate())
                    if first_fmt is None:          # 第一段：记住格式三件套并写入头部
                        first_fmt = fmt
                        out_wav.setnchannels(fmt[0])
                        out_wav.setsampwidth(fmt[1])
                        out_wav.setframerate(fmt[2])
                    elif fmt != first_fmt:
                        continue                       # 格式不一致的段才跳过
                    out_wav.writeframes(w.readframes(w.getnframes()))
    except Exception:
        # 拼接中途炸掉：把半成品删掉，防止坏文件被缓存系统当成"已合成"
        if os.path.exists(save_path):
            os.remove(save_path)
        raise
    finally:
        # 收尾：删掉临时小文件，别把 static 塞满（哪怕中途出错也要清场）
        for pp in part_paths:
            try:
                os.remove(pp)
            except OSError:
                pass

    return "/static/" + filename
