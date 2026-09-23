# -*- coding: utf-8 -*-
"""生成花卷文档生成 Skill 的介绍图（卖点卡），输出 assets/promo.png"""
import os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch

FONT = "C:/Windows/Fonts/msyh.ttc"
font_manager.fontManager.addfont(FONT)
NAME = font_manager.FontProperties(fname=FONT).get_name()
plt.rcParams["font.sans-serif"] = [NAME]
plt.rcParams["axes.unicode_minus"] = False

HERE = os.path.dirname(os.path.abspath(__file__))
fig = plt.figure(figsize=(10, 10), dpi=140)
ax = fig.add_axes([0, 0, 1, 1]); ax.set_xlim(0, 10); ax.set_ylim(0, 10); ax.axis("off")
fig.patch.set_facecolor("#f7fafc")

DARK = "#1a2b4a"; ACCENT = "#2b6cb0"; GRAY = "#4a5568"


def box(x0, y0, x1, y1, fc="#ffffff", ec="#cbd5e0", r=0.12):
    ax.add_patch(FancyBboxPatch((x0, y0), x1 - x0, y1 - y0,
                                boxstyle=f"round,pad=0.02,rounding_size={r}",
                                fc=fc, ec=ec, lw=1.2, zorder=2))


# 标题
ax.text(5, 9.3, "花卷文档生成", ha="center", fontsize=38, weight="bold", color=DARK, zorder=3)
ax.text(5, 8.55, "一条命令：Markdown → PDF · PPT · Word", ha="center", fontsize=16, color=GRAY, zorder=3)

# 左：输入
box(0.7, 3.0, 4.55, 8.15)
ax.text(2.62, 7.85, "输入  Markdown", ha="center", fontsize=13, weight="bold", color=ACCENT, zorder=3)
md_lines = [
    "# 实验报告",
    "## 一、目的",
    "- 搭建光照闭环",
    "- 误差 ≤ 2%",
    "## 二、元件清单",
    "| 元件 | 数量 |",
    "| LED | 6 |",
]
for i, t in enumerate(md_lines):
    ax.text(0.95, 7.35 - i * 0.52, t, fontsize=11.5, color=DARK, family=NAME, zorder=3, va="center")

# 箭头
ar = FancyArrowPatch((4.65, 5.6), (5.45, 5.6), arrowstyle="-|>", mutation_scale=22,
                     color=ACCENT, lw=2.5, zorder=3)
ax.add_patch(ar)

# 右：三个输出
box(5.55, 3.0, 9.3, 8.15)
ax.text(7.42, 7.85, "输出  三件套", ha="center", fontsize=13, weight="bold", color=ACCENT, zorder=3)
outs = [("PDF", "doc.pdf", "1 页 · 精排版"),
        ("PPT", "slides.pptx", "4 页 · 16:9 幻灯片"),
        ("DOC", "doc.docx", "19 段 · 含表格代码块")]
for i, (tag, fname, desc) in enumerate(outs):
    y = 6.9 - i * 1.28
    box(5.8, y - 0.5, 9.05, y + 0.5, fc="#f0f6ff", ec="#c7dcf5")
    ax.text(6.15, y, tag, fontsize=13, weight="bold", color=ACCENT, zorder=3, va="center")
    ax.text(7.25, y + 0.13, fname, fontsize=13, weight="bold", color=DARK, zorder=3, va="center")
    ax.text(7.25, y - 0.24, desc, fontsize=10, color=GRAY, zorder=3, va="center")

# 底部
ax.text(5, 2.35, "适合要交课程报告 / 实验报告 / 答辩 PPT 的你", ha="center", fontsize=14, color=DARK, zorder=3)
box(3.2, 1.15, 6.8, 1.95, fc=ACCENT, ec=ACCENT)
ax.text(5, 1.55, "评论区扣 1 · 或私信获取", ha="center", fontsize=15, weight="bold", color="#ffffff", zorder=3)

out = os.path.join(HERE, "promo.png")
fig.savefig(out, dpi=140, facecolor=fig.get_facecolor())
print("已生成:", out)
