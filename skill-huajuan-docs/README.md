# 花卷文档生成 Skill

把 Markdown 或一句话主题，**一条命令**变成三份能直接交的成品：PDF、PPT、Word。

## 你拿到什么

- 三个排版引擎（`scripts/` 里的 gen_pdf / gen_ppt / gen_docx）
- 一个统一入口 `scripts/run.py`
- 一份示例（`example/`）
- 一份说明（`SKILL.md`，Claude Code 可直接加载为 Skill）

## 三步跑起来

```bash
# 1. 装依赖（就三个）
pip install -r requirements.txt

# 2. 生成
python scripts/run.py example/example.md
# 或：python scripts/run.py "我的实验报告"

# 3. 打开 output/ 看结果
```

## 它能排什么

- 标题/章节、项目符号/编号、真表格、代码块、加粗、行内代码、分页
- PDF 走精排版；PPT 是 16:9；Word 支持表格和代码块

## 适合谁

要交课程报告、实验报告、答辩 PPT、讲义、项目文档的学生和职场人——别再手搓排版了。
