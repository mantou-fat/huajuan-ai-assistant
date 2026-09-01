# -*- coding: utf-8 -*-
"""生成花卷的形象图：调通义万相，跑完自动下载到本目录"""
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
    "写实人像摄影，一位二十出头的中国女孩，雾蓝色长发自然垂落，发尾微卷，碎发垂在脸侧。"
    "戴一副细边圆框眼镜，脸型柔和圆润，五官清秀温和。"
    "穿宽松的浅灰色连帽卫衣，袖子盖住半个手掌。电影感色调，氛围感强。半身像，看向镜头。"
)

# 表情差分：名字 + 表情描述
EXPRESSIONS = [
    ("calm",  "表情平静，嘴角带着浅浅的微笑，眼神放松。夜晚温暖台灯光线打在侧脸，背景是模糊的书架和一罐可乐。"),
    ("happy", "明显很开心，笑得眼睛弯起来，嘴角上扬露出一点牙齿，脸颊微微鼓起。白天明亮的窗边光线，背景虚化。"),
    ("sad",   "有点委屈低落，嘴角微微向下撇，眼神放空显得蔫蔫的，下巴轻轻搁在手背上。阴天柔和的窗边光线，色调偏冷。"),
    ("angry", "小生气，鼓着脸颊，眉头轻轻皱起，嘴抿成一条线，眼神别扭地斜向一边。夜晚室内台灯光线。"),
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
            path = f"avatar_{name}.png"
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
