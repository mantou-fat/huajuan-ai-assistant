# -*- coding: utf-8 -*-
"""把 Markdown 排成 Word（.docx）。
#/##/### → 标题；- → 项目符号；1. → 编号；``` → 代码块；| → 表格；**加粗**、`行内代码`、> 引用。
用法: python gen_docx.py <输出docx> <输入md1> [md2] ...
"""
import os, re, sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from docx import Document
from docx.shared import Pt, RGBColor
from docx.oxml.ns import qn

MONO_COLOR = RGBColor(0x7a, 0x2e, 0x00)   # 代码/行内代码 深棕


def _add_runs(par, text):
    """把一段文字写进段落，处理 **加粗** 和 `行内代码`。"""
    for seg in re.split(r"(`[^`]*`)", text):
        if seg.startswith("`") and seg.endswith("`") and len(seg) > 1:
            r = par.add_run(seg[1:-1]); r.font.name = "Consolas"; r.font.color.rgb = MONO_COLOR
        else:
            for sub in re.split(r"(\*\*[^*]+\*\*)", seg):
                if sub.startswith("**") and sub.endswith("**") and len(sub) > 4:
                    r = par.add_run(sub[2:-2]); r.bold = True
                elif sub:
                    par.add_run(sub)


def md_to_docx(out, md_lines, title=None):
    """把 markdown 行列表排成 Word，返回段落数。"""
    doc = Document()
    doc.styles["Normal"].font.name = "Microsoft YaHei"
    doc.styles["Normal"].font.size = Pt(11)
    doc.styles["Normal"].element.rPr.rFonts.set(qn("w:eastAsia"), "微软雅黑")
    if title:
        doc.add_heading(title, level=0)

    i, n, in_code, code_buf = 0, len(md_lines), False, []
    while i < n:
        s = md_lines[i].strip()
        # 代码块
        if s.startswith("```"):
            if in_code:
                p = doc.add_paragraph(); r = p.add_run("\n".join(code_buf))
                r.font.name = "Consolas"; r.font.size = Pt(9)
                code_buf = []
            in_code = not in_code; i += 1; continue
        if in_code:
            code_buf.append(md_lines[i].rstrip("\n")); i += 1; continue
        # 表格
        if s.startswith("|") and i + 1 < n and re.match(r"^\|[\s:\-|]+\|$", md_lines[i + 1].strip()):
            header = [c.strip() for c in s.strip("|").split("|")]
            i += 2; rows = []
            while i < n and md_lines[i].strip().startswith("|"):
                rows.append([c.strip() for c in md_lines[i].strip().strip("|").split("|")]); i += 1
            ncol = max(len(header), max((len(r) for r in rows), default=0))
            table = doc.add_table(rows=1 + len(rows), cols=ncol); table.style = "Table Grid"
            for j, h in enumerate(header):
                cell = table.cell(0, j); cell.text = h
                for para in cell.paragraphs:
                    for r in para.runs: r.bold = True
            for ri, row in enumerate(rows):
                for j in range(ncol):
                    table.cell(ri + 1, j).text = row[j] if j < len(row) else ""
            doc.add_paragraph(); continue
        # 标题
        m = re.match(r"^(#{1,4})\s+(.*)$", s)
        if m:
            doc.add_heading(m.group(2).strip(), level=len(m.group(1))); i += 1; continue
        # 项目符号 / 编号
        m = re.match(r"^([-*•])\s+(.*)$", s)
        if m:
            _add_runs(doc.add_paragraph(style="List Bullet"), m.group(2)); i += 1; continue
        m = re.match(r"^\d+[.、]\s+(.*)$", s)
        if m:
            _add_runs(doc.add_paragraph(style="List Number"), m.group(1)); i += 1; continue
        # 引用
        if s.startswith(">"):
            p = doc.add_paragraph(); p.paragraph_format.left_indent = Pt(18)
            r = p.add_run(s.lstrip(">").strip()); r.italic = True; i += 1; continue
        # 分隔线 / 空行
        if not s or re.match(r"^(-{3,}|\*{3,})$", s):
            i += 1; continue
        # 普通段落
        _add_runs(doc.add_paragraph(), s); i += 1

    doc.save(out)
    return len(doc.paragraphs)


if __name__ == "__main__":
    out = sys.argv[1]
    md = []
    for p in sys.argv[2:]:
        with open(p, encoding="utf-8") as f:
            md.extend(f.read().splitlines())
    n = md_to_docx(out, md)
    print("生成成功: %s  共 %d 段" % (out, n))
