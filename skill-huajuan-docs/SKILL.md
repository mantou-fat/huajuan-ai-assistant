---
name: huajuan-docs
description: 把 Markdown 或一个主题，一键生成排版好的 PDF、PPT、Word 三件套。当用户要把文字变成文档/报告/幻灯片/讲义时使用。
---

# 花卷文档生成

把 Markdown 或一句话主题，变成能直接交的三份成品：**PDF（精排版）/ PPT（16:9 幻灯片）/ Word（含表格代码块）**。

## 用法

```bash
pip install -r requirements.txt
python scripts/run.py 你的输入.md        # 从 Markdown 文件
python scripts/run.py "我的报告主题"     # 从一句话主题（生成示例骨架）
```

生成结果在 `output/`：`doc.pdf`、`slides.pptx`、`doc.docx`。

## 输入约定（Markdown）

- `# ` 一级标题 → 封面/章节
- `## ` 二级标题 → 分节页（PPT）/ 章节（Word）
- `- ` / `1. ` → 要点/编号
- `| ` 表格 → 真表格（PDF/Word）
- ``` 代码块 ``` → 等宽代码（PDF/Word）
- `**加粗**` / `` `行内代码` `` → 行内样式

## 参考

- 示例：`example/example.md`
- 各脚本也可单独用：`python scripts/gen_pdf.py out.pdf in.md`
