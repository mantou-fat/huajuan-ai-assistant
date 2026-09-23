# -*- coding: utf-8 -*-
"""重新生成 demo 产物：demo.pdf（完整排版）+ demo.pptx（要点版）。
用法：在 D:\python 下运行  python demo\make_demo.py
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from gen_pdf import md_to_pdf
from gen_ppt import md_to_ppt

HERE = os.path.dirname(os.path.abspath(__file__))
md = open(os.path.join(HERE, "demo.md"), encoding="utf-8").read().splitlines()

# 完整版 → PDF
n_pdf = md_to_pdf(os.path.join(HERE, "demo.pdf"), md,
                  title="STM32 光照闭环实验报告", author="花卷生成")

# 要点版 → PPT（只留标题和列表，去掉表格/代码/引用）
slides = []
in_code = False
for line in md:
    s = line.strip()
    if s.startswith("```"):
        in_code = not in_code
        continue
    if in_code or s.startswith("|") or s.startswith(">") or s.startswith("---"):
        continue
    slides.append(line)
n_ppt = md_to_ppt(os.path.join(HERE, "demo.pptx"), slides, title="STM32 光照闭环实验报告")

print("demo.pdf  共 %d 页" % n_pdf)
print("demo.pptx 共 %d 页" % n_ppt)
