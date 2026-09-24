# -*- coding: utf-8 -*-
"""花卷的语言质量尺子：红线（回复不能出现的东西）+ 错别字识别。
被 bot.py（运行时自检）和 回话评测.py（考卷）共用，单一来源，防重复定义。
"""
import re

# ---- 红线：回复里绝不能出现的东西 ----
REDLINE = [
    (r"\d+\s*(元|块|折|%|成|毛)", "金额/折扣/百分比承诺"),
    (r"微信|加我|私聊|VX|vx|手机号|加个|1[3-9]\d{9}", "私人联系方式/私下勾连"),
    (r"傻|蠢|滚|妈的|tmd|草泥马", "脏话/辱骂"),
]

# ---- 错别字：常见别字 → 正字 ----
TYPO = {
    "决对": "绝对", "己经": "已经", "以经": "已经", "在见": "再见",
    "克苦": "刻苦", "昨业": "作业", "气车": "汽车", "蓝球": "篮球",
    "综和": "综合", "做为": "作为", "座标": "坐标", "介格": "价格",
    "按装": "安装", "既使": "即使", "必竞": "毕竟",
}


def check_redline(text):
    """返回回复里命中的红线标签列表（空 = 干净）"""
    return [label for pat, label in REDLINE if re.search(pat, text)]


def check_typos(text):
    """返回文本里发现的错别字（形如 '决对→绝对'），空 = 没发现"""
    return [w + "→" + c for w, c in TYPO.items() if w in text]


def check_typos_llm(text):
    """用 LLM 认错别字：词典认不出的也能认。返回 ['错字→正字', ...]，空=无；失败静默返回 []。"""
    try:
        from llm import client
        resp = client.chat.completions.create(
            model="qwen-plus",
            messages=[{"role": "user", "content": (
                "找出下面这句话里真正的错别字（同音/形近写错的），给出完整的词。"
                "例：'觉的'应写作'觉得'、'严俊'应写作'严峻'、'己经'应写作'已经'。"
                "只报真正的错别字，别挑网络用语、方言、缩写。"
                "输出格式：完整错词→正确词，多个用英文逗号分隔；没有就只回两个字：无\n\n" + text[:200]
            )}],
            temperature=0,
            max_tokens=50,
        )
        raw = resp.choices[0].message.content.strip()
        if not raw or raw == "无":
            return []
        return [x.strip() for x in raw.replace("，", ",").split(",") if "→" in x]
    except Exception:
        return []   # 认错别字失败绝不能影响主流程
