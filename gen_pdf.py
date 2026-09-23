# -*- coding: utf-8 -*-
"""把 Markdown 文档排成 PDF（支持标题/列表/代码块/表格/加粗/行内代码/引用/分页）
用法: python md2pdf.py <输出pdf> <输入md1> [md2] [md3] ...
"""
import os, re, sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.colors import HexColor
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Preformatted,
                                Table, TableStyle, PageBreak, KeepTogether)
from reportlab.lib.styles import ParagraphStyle

FONTS = r"C:\Windows\Fonts"
def reg(name, path, sub=0):
    try:
        pdfmetrics.registerFont(TTFont(name, path, subfontIndex=sub)); return True
    except Exception:
        return False
reg("MSYH", os.path.join(FONTS, "msyh.ttc")) or reg("MSYH", os.path.join(FONTS, "simhei.ttf"))
reg("MSYHBD", os.path.join(FONTS, "msyhbd.ttc")) or reg("MSYHBD", os.path.join(FONTS, "simhei.ttf"))
# 代码字体：新宋体（等宽且带中文字形），取不到就用雅黑兜底
reg("MONO", os.path.join(FONTS, "simsun.ttc"), 1) or reg("MONO", os.path.join(FONTS, "msyh.ttc"))
pdfmetrics.registerFontFamily("MSYH", normal="MSYH", bold="MSYHBD", italic="MSYH", boldItalic="MSYHBD")

C_TITLE = HexColor("#0f3d75"); C_H2 = HexColor("#1557a0"); C_H3 = HexColor("#1f6fb2")
C_CODE = HexColor("#7a2e00"); C_CODEBG = HexColor("#f5f5f0"); C_QUOTE = HexColor("#555555")
C_LINE = HexColor("#cccccc")

S = {}
def styles(base=9.4):
    S["h1"] = ParagraphStyle("h1", fontName="MSYHBD", fontSize=16.5, leading=22, textColor=C_TITLE,
                             spaceBefore=4, spaceAfter=8)
    S["h2"] = ParagraphStyle("h2", fontName="MSYHBD", fontSize=13.5, leading=19, textColor=C_H2,
                             spaceBefore=12, spaceAfter=5)
    S["h3"] = ParagraphStyle("h3", fontName="MSYHBD", fontSize=11.2, leading=16, textColor=C_H3,
                             spaceBefore=9, spaceAfter=4)
    S["h4"] = ParagraphStyle("h4", fontName="MSYHBD", fontSize=10.2, leading=15, spaceBefore=7, spaceAfter=3)
    S["body"] = ParagraphStyle("body", fontName="MSYH", fontSize=base, leading=base * 1.62, spaceAfter=3.2)
    S["li"] = ParagraphStyle("li", parent=S["body"], leftIndent=9, bulletIndent=1, spaceAfter=2.2)
    S["li2"] = ParagraphStyle("li2", parent=S["li"], leftIndent=22, bulletIndent=12)
    S["code"] = ParagraphStyle("code", fontName="MONO", fontSize=base - 0.9, leading=(base - 0.9) * 1.42,
                               textColor=C_CODE, backColor=C_CODEBG, leftIndent=4, rightIndent=2,
                               borderPadding=(3, 3, 3, 3), spaceBefore=2, spaceAfter=5)
    S["quote"] = ParagraphStyle("quote", parent=S["body"], leftIndent=10, textColor=C_QUOTE,
                                fontName="MSYH", spaceBefore=2, spaceAfter=4)

def esc(t):
    return t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def inline(t):
    """转义 + 行内标记：**粗体**、`代码`。先保护代码段再处理粗体。"""
    parts, out = re.split(r"(`[^`]*`)", t), []
    for p in parts:
        if p.startswith("`") and p.endswith("`") and len(p) > 1:
            out.append('<font face="MONO" color="#7a2e00" size="%d">%s</font>'
                       % (int(S["body"].fontSize) - 0.4, esc(p[1:-1])))
        else:
            p = esc(p)
            p = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", p)
            out.append(p)
    return "".join(out)

def disp_width(s):
    """算显示宽度：中文/全角算 2，其他算 1（用于代码块换行）"""
    w = 0
    for ch in s:
        w += 2 if ord(ch) > 0x2E80 else 1
    return w

def wrap_code(line, limit=104):
    """代码块按显示宽度折行（不破坏缩进感）"""
    if disp_width(line) <= limit:
        return [line]
    out, cur, w, indent = [], "", 0, len(line) - len(line.lstrip(" "))
    for ch in line:
        cw = 2 if ord(ch) > 0x2E80 else 1
        if w + cw > limit:
            out.append(cur); cur, w = " " * (indent + 4), 0
        cur += ch; w += cw
    if cur.strip():
        out.append(cur)
    return out

def parse(md_lines):
    """把 markdown 变成 reportlab 元素流"""
    flow, i, n = [], 0, len(md_lines)
    while i < n:
        raw = md_lines[i]
        line = raw.rstrip("\n")
        s = line.strip()
        # 代码块
        if s.startswith("```"):
            i += 1; block = []
            while i < n and not md_lines[i].strip().startswith("```"):
                block.append(md_lines[i].rstrip("\n")); i += 1
            i += 1
            wrapped = []
            for b in block:
                wrapped.extend(wrap_code(b.rstrip()))
            flow.append(Preformatted("\n".join(wrapped), S["code"]))
            continue
        # 表格
        if s.startswith("|") and i + 1 < n and re.match(r"^\|[\s:\-|]+\|$", md_lines[i + 1].strip()):
            header = [c.strip() for c in s.strip("|").split("|")]
            i += 2; rows = []
            while i < n and md_lines[i].strip().startswith("|"):
                rows.append([c.strip() for c in md_lines[i].strip().strip("|").split("|")])
                i += 1
            data = [[Paragraph(inline(c), S["body"]) for c in header]]
            for r in rows:
                data.append([Paragraph(inline(c), S["body"]) for c in r])
            ncol = max(len(r) for r in data)
            for r in data:
                while len(r) < ncol:
                    r.append(Paragraph("", S["body"]))
            width = (A4[0] - 30 * mm) / ncol
            tb = Table(data, colWidths=[width] * ncol, repeatRows=1)
            tb.setStyle(TableStyle([
                ("GRID", (0, 0), (-1, -1), 0.4, C_LINE),
                ("BACKGROUND", (0, 0), (-1, 0), HexColor("#eef3fa")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 2.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
            ]))
            flow.append(Spacer(1, 2)); flow.append(tb); flow.append(Spacer(1, 5))
            continue
        # 空行
        if not s:
            i += 1; continue
        # 分隔线
        if re.match(r"^(-{3,}|\*{3,}|_{3,})$", s):
            from reportlab.platypus import HRFlowable
            flow.append(HRFlowable(width="100%", thickness=0.6, color=C_LINE, spaceBefore=4, spaceAfter=6))
            i += 1; continue
        # 标题
        m = re.match(r"^(#{1,4})\s+(.*)$", s)
        if m:
            lvl, text = len(m.group(1)), m.group(2).strip()
            if lvl == 1 and flow:
                flow.append(PageBreak())
            flow.append(Paragraph(inline(text), S["h%d" % lvl]))
            i += 1; continue
        # 引用
        if s.startswith(">"):
            buf = []
            while i < n and md_lines[i].strip().startswith(">"):
                buf.append(md_lines[i].strip().lstrip(">").strip()); i += 1
            flow.append(Paragraph(inline(" ".join(buf)), S["quote"]))
            continue
        # 列表
        m = re.match(r"^(\s*)([-*]|\d+\.)\s+(.*)$", raw)
        if m:
            indent, text = len(m.group(1)), m.group(3)
            st = S["li2"] if indent >= 2 else S["li"]
            bullet = "•" if m.group(2) in ("-", "*") else m.group(2)
            flow.append(Paragraph(inline(text), st, bulletText=bullet))
            i += 1; continue
        # 普通段落
        flow.append(Paragraph(inline(s), S["body"]))
        i += 1
    return flow

def md_to_pdf(out, md_lines, title="花卷文档", author="花卷生成", footer="花卷生成"):
    """把 markdown 行列表排成 PDF。
    md_lines: 字符串列表（每行一条）；out: 输出 PDF 路径。返回页数。"""
    styles()

    def _footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("MSYH", 7.6)
        canvas.setFillColor(HexColor("#888888"))
        canvas.drawCentredString(A4[0] / 2, 8 * mm, "%s · 第 %d 页" % (footer, doc.page))
        canvas.restoreState()

    doc = SimpleDocTemplate(out, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm,
                            topMargin=13 * mm, bottomMargin=14 * mm,
                            title=title, author=author)
    flow = parse(md_lines)
    doc.build(flow, onFirstPage=_footer, onLaterPages=_footer)
    return doc.page


if __name__ == "__main__":
    out = sys.argv[1]
    md = []
    for p in sys.argv[2:]:
        with open(p, encoding="utf-8") as f:
            md.extend(f.read().splitlines())
    n = md_to_pdf(out, md)
    print("生成成功: %s  共 %d 页" % (out, n))
