# -*- coding: utf-8 -*-
"""生成花卷的国风形象图：调通义万相，跑完自动下载到 static/ 供前端使用。
设计：国风少女 + 花卷元素（螺旋纹蒸包造型的发髻、汉服、花卷纹样）。"""
import os
import json
import time
import urllib.request
from dotenv import load_dotenv

load_dotenv()
KEY = os.getenv("DASHSCOPE_API_KEY")

API_CREATE = "https://dashscope.aliyuncs.com/api/v1/services/aigc/text2image/image-synthesis"
API_TASK = "https://dashscope.aliyuncs.com/api/v1/tasks/"

# 想改样子就改这里的提示词，然后重新运行本脚本
# 人物基础特征（四个表情共用，保证是同一个人）
BASE = (
    "国风二次元插画，一位温婉软萌的中国少女。"
    "头顶两个大大的蒸花卷造型发髻——白乎乎、软糯糯的奶白色蒸花卷，"
    "螺旋花纹清晰可见，像刚出笼的蒸花卷一样蓬松柔软，还冒着热气。"
    "发髻是视觉重点，一眼就能认出是'花卷'面点。"
    "穿淡青色与米白色相间的汉服，衣襟和袖口绣着花卷螺旋纹样。"
    "脸型柔和圆润，眉眼温柔清秀，皮肤白皙。半身像，看向镜头。"
    "暖色调，光影柔和，带一点蒸笼热气的氤氲氛围。"
)

# 表情差分：名字 + 表情描述
EXPRESSIONS = [
    ("calm",  "表情平静，嘴角带浅浅微笑，眼神温和，双手轻轻交叠在身前。"),
    ("happy", "开心地笑，眼睛弯成月牙，脸颊微微泛红，头微微一侧。"),
    ("sad",   "有点委屈低落，嘴角微微向下撇，眼神放空蔫蔫的，轻轻低着头。"),
    ("angry", "小生气，鼓着腮帮子，眉头轻轻皱起，嘴抿成一条线，眼神别扭地斜向一边。"),
]


def build_prompt(expr_desc):
    return BASE + expr_desc


def post_json(url, body, headers):
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), headers=headers)
    with urllib.request.urlopen(req) as r:
        return json.load(r)


def gen_one(prompt, name):
    headers = {
        "Authorization": "Bearer " + KEY,
        "Content-Type": "application/json",
        "X-DashScope-Async": "enable",
    }
    body = {
        "model": "wanx2.1-t2i-turbo",
        "input": {"prompt": prompt},
        "parameters": {"size": "1024*1024", "n": 1},
    }
    resp = post_json(API_CREATE, body, headers)
    task_id = resp["output"]["task_id"]
    print(f"[{name}] 提交成功，任务号 {task_id}，等待生成...")

    for _ in range(60):  # 最多等5分钟
        time.sleep(5)
        with urllib.request.urlopen(urllib.request.Request(
            API_TASK + task_id, headers={"Authorization": "Bearer " + KEY}
        )) as r:
            result = json.load(r)
        status = result["output"]["task_status"]
        if status == "SUCCEEDED":
            url = result["output"]["results"][0]["url"]
            os.makedirs("static", exist_ok=True)
            path = os.path.join("static", f"avatar_{name}.png")
            urllib.request.urlretrieve(url, path)
            print(f"[{name}] 完成，已保存到 {path}")
            return path
        if status == "FAILED":
            print(f"[{name}] 生成失败：{result['output']}")
            return None
        print(f"[{name}] 状态：{status}，继续等...")
    return None


if __name__ == "__main__":
    for name, desc in EXPRESSIONS:
        gen_one(build_prompt(desc), name)
    print("全部完成")
