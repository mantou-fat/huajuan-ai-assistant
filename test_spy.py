# -*- coding: utf-8 -*-
# 验证 get_reply 的工具循环是否真的执行了函数：用间谍函数包一层，记录调用
import bot

calls = []
orig_get_time = bot.get_time
orig_set_expense = bot.set_expense

def spy_get_time(*a, **k):
    calls.append("get_time 被真实调用，返回: " + str(orig_get_time(*a, **k)))
    return orig_get_time(*a, **k)

def spy_set_expense(*a, **k):
    calls.append("set_expense 被真实调用: " + str(a) + str(k))
    return orig_set_expense(*a, **k)

bot.TOOL_FUNCS["get_time"] = spy_get_time
bot.TOOL_FUNCS["set_expense"] = spy_set_expense

print("== 测试1：现在几点（问5遍，看模型调不调工具）==")
for i in range(5):
    r = bot.get_reply("现在几点了？")
    print(f"第{i+1}遍 花卷：", r.replace("\n", " ")[:60])

print("\n== 测试2：记账（逼模型必须走工具）==")
r = bot.get_reply("帮我记一笔账，今天买奶茶花了15块")
print("花卷：", r.replace("\n", " ")[:60])

print("\n== 间谍记录（工具真实执行过的证据）==")
for c in calls:
    print(c)
if not calls:
    print("（一次都没调用——模型全程在幻觉）")
