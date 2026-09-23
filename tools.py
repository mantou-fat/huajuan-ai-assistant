# -*- coding: utf-8 -*-
"""工具层：23 个工具 + TOOLS 登记表 + TOOL_FUNCS 派遣表 + 工具相关状态 + TTS。
依赖 config(配置) / llm(客户端) / rag(知识库检索)。工具只负责"干活"，编排逻辑在 bot.py。"""
import os
import json
import time
import base64
import hashlib
import requests
from concurrent.futures import ThreadPoolExecutor
from bs4 import BeautifulSoup
from config import (REMINDER_FILE, EXPENSE_FILE, HOME_FILE, FILES_DIR, READ_DIRS,
                    EXCLUDE_FILES, PROGRAM_LIST)
from llm import client, api_key, tavily_key, bjs_key, workspace_id
from rag import search_knowledge, get_embedding, cosine_similarity
PENDING_WRITES = {}              # 待确认写入（write_file 两步确认用）
PHONE_ACTIONS = {}               # 手机动作登记表：电脑上的工具只"开单子"，真动作由手机执行
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
            "description": r"列出文件盒（huajuan_files文件夹）里的所有文件名。用户提到文件盒/你有哪些文件时必须调用本工具获取实时清单，即使对话中出现过文件信息也不许凭记忆回答，记忆可能过期或错误,可以读文件盒和项目文件夹（D:\python）里的文件",
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
            "description": r"读取文件盒里某个文件的内容。用户想看某个文件写了什么时必须调用本工具读取实时内容，即使对话中见过该文件的内容也不许凭记忆背诵。只接受文件名如 心愿清单.txt，不接受带路径的写法,可以读文件盒和项目文件夹（D:\python）里的文件",
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
            "description": "打开电脑上的程序或网站（如微信、QQ、记事本、计算器、哔哩哔哩、抖音、知乎等，PROGRAM_LIST 里登记的都算）。调用前先向用户确认，用户同意后再调用",
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
            "description": "截取当前电脑屏幕并保存。调用前先向用户确认，用户同意后再调用",
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
            "description": "锁定电脑屏幕。调用前必须先向用户确认，用户明确同意后再调用",
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
{
    "type": "function",
    "function": {
        "name": "look_around",
        "description": "打开摄像头看一眼眼前的画面，报告看到的人和物品。当用户表达'看看我在干啥''看看我在做什么''看一眼我在干嘛''看看你面前有什么''你现在能看到什么''看一眼'等想看当前画面的意图时，**必须调用此工具**，不要说自己看不到。只能认出常见物体（人、杯子、手机等）",
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
        "name": "control_device",
        "description": "控制家里的智能设备（灯、空调），可以开、关、查状态。用户说'开灯''关空调''灯开着吗'时调用。device 用设备名如'客厅灯'",
        "parameters": {
            "type": "object",
            "properties": {
                "device": {"type": "string", "description": "设备名：客厅灯/卧室灯/空调"},
                "action": {"type": "string", "description": "动作：开/关/查询"}
            },
            "required": ["device", "action"]
        }
    }
},
{
    "type": "function",
    "function": {
        "name": "make_pdf",
        "description": "把 markdown 文本排成一份 PDF，保存到文件盒（huajuan_files/）。用户说'把…做成PDF/导出PDF/生成文档/排个版'时使用。",
        "parameters": {
            "type": "object",
            "properties": {
                "md": {"type": "string", "description": "要排版的 markdown 全文；如果内容是文件盒里的 .md 文件，先调 read_file 拿到内容再填这里"},
                "title": {"type": "string", "description": "文档标题，可留空（留空自动取正文第一个 # 标题）"},
                "filename": {"type": "string", "description": "输出 PDF 文件名，如 report.pdf"}
            },
            "required": ["md"]
        }
    }
},
{
    "type": "function",
    "function": {
        "name": "make_ppt",
        "description": "把 markdown 文本排成一份 PPT，保存到文件盒（huajuan_files/）。用户说'把…做成PPT/做份幻灯片/生成PPT'时使用。",
        "parameters": {
            "type": "object",
            "properties": {
                "md": {"type": "string", "description": "要排版的 markdown 全文；# 一级标题做封面/章节，## 二级标题做分节，- 列表做要点"},
                "title": {"type": "string", "description": "PPT 标题，可留空（留空自动取正文第一个 # 标题）"},
                "filename": {"type": "string", "description": "输出 PPT 文件名，如 demo.pptx"}
            },
            "required": ["md"]
        }
    }
},
]
def get_time():
    from datetime import datetime
    now = datetime.now()
    return now.strftime("%Y-%m-%d %H:%M") + " 周" + "一二三四五六日"[now.weekday()]
user_location = {"lat": None, "lon": None}
def get_weather(city=""):
    """city 可省略：没城市就看定位，再没有就引导用户说出城市（不许让模型编天气）"""
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
def make_pdf(md, title="", filename="huajuan_output.pdf"):
    """把 markdown 排成 PDF，输出到文件盒。返回结果字符串。"""
    if not filename.lower().endswith(".pdf"):
        filename += ".pdf"
    path = safe_write_path(filename)
    if path is None:
        return "输出名不合法，只能写到文件盒 huajuan_files 里"
    try:
        from gen_pdf import md_to_pdf
        if not title:
            title = "花卷文档"
            for line in md.splitlines():
                s = line.strip()
                if s.startswith("# "):
                    title = s[2:].strip(); break
        n = md_to_pdf(path, md.splitlines(), title=title)
        return "已生成 PDF「" + filename + "」到文件盒，共 " + str(n) + " 页"
    except Exception as e:
        return "生成 PDF 失败：" + str(e)
def make_ppt(md, title="", filename="huajuan_output.pptx"):
    """把 markdown 排成 PPTX，输出到文件盒。返回结果字符串。"""
    if not filename.lower().endswith(".pptx"):
        filename += ".pptx"
    path = safe_write_path(filename)
    if path is None:
        return "输出名不合法，只能写到文件盒 huajuan_files 里"
    try:
        from gen_ppt import md_to_ppt
        if not title:
            title = "花卷演示"
            for line in md.splitlines():
                s = line.strip()
                if s.startswith("# "):
                    title = s[2:].strip(); break
        n = md_to_ppt(path, md.splitlines(), title=title)
        return "已生成 PPT「" + filename + "」到文件盒，共 " + str(n) + " 页"
    except Exception as e:
        return "生成 PPT 失败：" + str(e)
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
    """打开程序/网站。安全靠两层：①ACCESS_TOKEN 门（外人进不来）②人设要求先问用户再调本工具。
    注：曾试过加 confirm 参数做代码级确认，但模型常漏传导致'用户已同意却仍被拦'，故去掉（2026-09-05）"""
    path = PROGRAM_LIST.get(program_name)
    if path is None:
        return f"找不到程序「{program_name}」，目前登记的有：{'、'.join(PROGRAM_LIST.keys())}"
    os.startfile(path)
    return f"已在电脑上打开 {program_name}。"
def take_screenshot():
    """截屏保存。安全同上：ACCESS_TOKEN 门 + 人设先确认。2026-09-05 去掉 confirm 参数"""
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
    """锁屏。安全同上：ACCESS_TOKEN 门 + 人设先确认。2026-09-05 去掉 confirm 参数"""
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
_yolo_model = None   # 全局缓存：模型只加载一次
def look_around():
    global _yolo_model
    if _yolo_model is None:
        from ultralytics import YOLO
        _yolo_model = YOLO("yolov8n.pt")
    import cv2
    cap = cv2.VideoCapture(0)
    ok, frame = cap.read()
    cap.release()
    if not ok:
        return "摄像头打开失败，可能被别的程序占用了"
    # ---- 第一双眼睛：YOLO 哨兵报点 ----
    r = _yolo_model.predict(frame, verbose=False, imgsz=320)[0]
    counts = {}
    for cls in r.boxes.cls:
        name = r.names[int(cls)]
        counts[name] = counts.get(name, 0) + 1
    if counts:
        yolo_report = "、".join(f"{n} {c}个" if c > 1 else n for n, c in counts.items())
    else:
        yolo_report = "没认出明确的物体"
    # ---- 第二双眼睛：qwen-vl 顾问细看 ----          
    ok2, buf = cv2.imencode(".jpg", frame)             
    if ok2:                                           
        b64 = base64.b64encode(buf).decode()           
        image_url = "data:image/jpeg;base64," + b64    
        try:                                           
            resp = client.chat.completions.create(    
                model="qwen-vl-max",
                messages=[{"role": "user", "content": [
                    {"type": "text", "text": "用一两句话描述这个画面的主要内容和人物动作。"},
                    {"type": "image_url", "image_url": {"url": image_url}}
                ]}],
                max_tokens=100                         
            )
            vl_report = resp.choices[0].message.content.strip()   
        except Exception:
            vl_report = "细看环节失败了"                
    else:
        vl_report = "照片打包失败"
    # ---- 合并汇报（开头黑体字是写给模型看的：这是真实画面，必须照实转述） ----
    return ("【系统：以下是你通过摄像头亲眼看到的真实画面，回答必须完全基于这两条内容，"
            "禁止说'我看不到''看不清''信号不好'等否认的话】\n"
            f"YOLO 检测到：{yolo_report}。\n画面细看：{vl_report}")
def control_device(device, action):
    # 防护：设备名必须是非空字符串，否则空串会命中"第一台设备"（"" 在任意名字里都成立）
    if not isinstance(device, str) or not device.strip():
        return "请说清楚要控制哪个设备，比如：客厅灯、卧室灯、空调"
    with open(HOME_FILE, "r", encoding="utf-8") as f:
        home = json.load(f)
    dev = None
    for d in home.values():
        if device in d["name"]:        # 模糊匹配：说"灯"也能命中"客厅灯"
            dev = d
            break
    if dev is None:
        return f"没找到设备：{device}。家里现在有：客厅灯、卧室灯、空调"
    if action == "开":
        dev["on"] = True
    elif action == "关":
        dev["on"] = False
    elif action == "查询":
        return f"{dev['name']}现在是{'开' if dev['on'] else '关'}的"
    else:
        return "动作只能是：开、关、查询"
    with open(HOME_FILE, "w", encoding="utf-8") as f:
        json.dump(home, f, ensure_ascii=False, indent=2)
    return f"{dev['name']}已{'打开' if dev['on'] else '关闭'}"
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
    "look_around": look_around,
    "control_device": control_device,
    "make_pdf": make_pdf,
    "make_ppt": make_ppt
}
def tts(text, filename="tts_latest.wav"):
    """文字转语音：长文本自动切成小段分别合成，再拼接成一个 wav"""
    import urllib.request
    import urllib.error
    import json as _json
    import wave
    # 缓存：用文字的 MD5 当文件名，同一段文字只合成一次
    filename = hashlib.md5(text.encode("utf-8")).hexdigest()[:16] + ".wav"
    save_path = os.path.join("static", filename)
    if os.path.exists(save_path) and os.path.getsize(save_path) > 0:
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
    with ThreadPoolExecutor(max_workers=4) as pool:
        part_paths = list(pool.map(synth_job, enumerate(parts)))
    # ---------- 第4步：wave 拼接 ----------
    with wave.open(save_path, "wb") as out_wav:
        first_params = None
        for pp in part_paths:
            with wave.open(pp, "rb") as w:
                fmt = (w.getnchannels(), w.getsampwidth(), w.getframerate())
                if first_params is None:          # 第一段：只记住格式三件套
                    first_params = fmt
                    out_wav.setnchannels(fmt[0])
                    out_wav.setsampwidth(fmt[1])
                    out_wav.setframerate(fmt[2])
                elif fmt != first_params:
                    continue                       # 格式不一致的段才跳过
                out_wav.writeframes(w.readframes(w.getnframes()))
    # 收尾：删掉临时小文件，别把 static 塞满
    for pp in part_paths:
        os.remove(pp)
    return "/static/" + filename
