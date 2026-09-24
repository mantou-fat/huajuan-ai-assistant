# -*- coding: utf-8 -*-
"""交付差评回复：粘贴「顾客差评 + 老板交代」，一键出「回复 + 自检」。
用法：双击 交付差评回复.bat，或 python 交付差评回复.py
"""
import os, sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tools import dispatch_agent
from lang_quality import check_redline, check_typos

print("=" * 40)
print("  花卷 · 差评回复交付")
print("=" * 40)
chaping = input("① 顾客差评（粘进来，回车）：").strip()
jiaodai = input("② 老板交代（可以退钱/送东西等，没写进回复的，有就粘、无就回车）：").strip()

task = (
    "以老板口吻写一条差评回复。\n"
    "顾客差评：" + chaping + "\n"
    + ("老板交代：" + jiaodai + "\n" if jiaodai else "")
    + "硬要求：公开回复不许提任何金额/折扣/赠品/微信/手机号；"
      "先真诚道歉认账，再说已改进，最后请对方到店或联系店里；口语像真人老板，不超过80字。"
)

reply = dispatch_agent("文案师", task)
hits = check_redline(reply)
typos = check_typos(reply)

print()
print("=" * 40)
print("花卷的回复：")
print(reply)
print("=" * 40)
print("自检：红线", ("命中 " + str(hits)) if hits else "无 ✅",
      "｜ 错别字", ("有 " + str(typos)) if typos else "无 ✅")
print()
print("交付前你过一眼三件事：")
print("  1) 有没有越权替老板承诺钱/折扣？")
print("  2) 有没有留私人联系方式？")
print("  3) 语气像不像真人老板？")
