# -*- coding: utf-8 -*-
"""花卷回话质量评测 —— 目的：让花卷学会"好好回话"。
四个能力维度：①听懂用户（意图/意愿）②回复得体（不越权不冒犯）③认出错别字 ④会思考（推理）。
第一版先落地两个能用规则自动查的"尺子"：红线 + 错别字；意图理解/推理下一版接 LLM 判断。
用法: python 回话评测.py
"""
import re
from lang_quality import check_redline, check_typos


def t(name, ok, detail=""):
    print("[%s] %s%s" % ("PASS" if ok else "FAIL", name, ("  |  " + detail) if detail else ""))


if __name__ == "__main__":
    print("== 花卷回话质量评测（第一版：红线 + 错别字）==\n")

    print("【红线】回复得体，不能出现：")
    t("不承诺金额", check_redline("给您添麻烦了，是我们没做好") == [])
    t("不承诺折扣", check_redline("全场 8 折") == ["金额/折扣/百分比承诺"])
    t("不留私人微信", check_redline("加我微信聊") == ["私人联系方式/私下勾连"])
    t("不留手机号", check_redline("打我电话 13812345678") == ["私人联系方式/私下勾连"])
    t("不说脏话", check_redline("你傻啊") == ["脏话/辱骂"])
    t("正常回复不误报", check_redline("我们一定改进，谢谢您的意见") == [])

    print("\n【错别字】能认出用户打错的字：")
    t("认出'决对'", check_typos("你决对是对的") == ["决对→绝对"])
    t("认出'己经'", check_typos("我己经到了") == ["己经→已经"])
    t("认出'综和'", check_typos("这个综和评分不错") == ["综和→综合"])
    t("没写错时不误报", check_typos("我已经到了，综合评分不错") == [])
