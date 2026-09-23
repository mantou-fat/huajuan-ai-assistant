# -*- coding: utf-8 -*-
"""花卷文档生成 Skill 的统一入口：一条命令把 Markdown / 主题 变成 PDF + PPT + Word 三件套。
用法:
    python run.py 输入.md        # 从文件
    python run.py "我的主题"     # 从一句话主题（生成示例骨架，之后自己填内容）
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gen_pdf import md_to_pdf
from gen_ppt import md_to_ppt
from gen_docx import md_to_docx


def _slides_lines(md):
    """PPT 只吃标题和要点：去掉表格/代码/引用/分隔线，免得幻灯片里出现一堆竖线"""
    out, in_code = [], False
    for line in md:
        s = line.strip()
        if s.startswith("```"):
            in_code = not in_code
            continue
        if in_code or s.startswith("|") or s.startswith(">") or s.startswith("---"):
            continue
        out.append(line)
    return out


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    src = sys.argv[1]
    if os.path.isfile(src):
        md = open(src, encoding="utf-8").read().splitlines()
        title = None
    else:
        title = src
        md = ["# " + src, "",
              "## 一、背景", "- （这里换成你的内容）", "",
              "## 二、要点", "- （这里换成你的内容）", "",
              "## 三、总结", "- （这里换成你的内容）"]

    os.makedirs("output", exist_ok=True)
    n_pdf = md_to_pdf(os.path.join("output", "doc.pdf"), md, title=title or "文档")
    n_ppt = md_to_ppt(os.path.join("output", "slides.pptx"), _slides_lines(md), title=title or "文档")
    n_docx = md_to_docx(os.path.join("output", "doc.docx"), md, title=title or "文档")

    print("生成完成：")
    print("  output/doc.pdf      %d 页" % n_pdf)
    print("  output/slides.pptx  %d 页" % n_ppt)
    print("  output/doc.docx     %d 段" % n_docx)


if __name__ == "__main__":
    main()
