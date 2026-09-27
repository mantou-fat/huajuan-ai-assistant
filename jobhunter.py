# -*- coding: utf-8 -*-
"""应届生求职筛选助手 MVP v0.2
流程：填条件(城市/专业/薪资/应届) → 实时搜索 → qwen 筛选+结构化 → 输出清单。
提速：加载动画 + 减少输入输出 + 用 qwen-turbo（更快；要更准可换回 qwen-plus）。"""
import requests
from flask import Flask, request, render_template_string, jsonify
from llm import client, tavily_key

app = Flask(__name__)

def search(query, n=6):
    """Tavily 实时搜索，返回结构化结果列表 [{title,url,content}]"""
    try:
        r = requests.post(
            "https://api.tavily.com/search",
            headers={"Authorization": "Bearer " + (tavily_key or "missing-key")},
            json={"query": query, "max_results": n},
            timeout=20,
        )
        return r.json().get("results", [])
    except Exception as e:
        return [{"title": "搜索失败", "url": "", "content": str(e)}]

def filter_jobs(city, major, salary, fresh, raw_results):
    """把原始搜索结果塞给 qwen，筛出真实、对口、可投递的公司清单"""
    blob = "\n\n".join(
        "[%d] %s\n%s\n%s" % (i, item.get("title", ""), item.get("url", ""), (item.get("content") or "")[:400])
        for i, item in enumerate(raw_results, 1)
    )
    prompt = (
        "你是应届生求职筛选助手。用户条件：城市=%s，专业/方向=%s，期望薪资=%s，身份=%s。\n\n"
        "下面是联网搜到的原始结果。请从中筛出【真实、对口、可投递】的公司/岗位，"
        "剔除广告、培训贷、中介、无关内容和重复项。\n\n%s\n\n"
        "输出格式（每条一行，用 | 分隔）：公司名|岗位|官网或投递链接|匹配理由|薪资范围\n"
        "只输出清单本身，不要解释、不要标题，最多10条。若没有符合的，就输出：没找到符合的岗位。"
        % (city, major, salary, fresh, blob)
    )
    try:
        resp = client.chat.completions.create(
            model="qwen-turbo",   # 快；要更准可换 qwen-plus
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=900,
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        return "筛选失败：" + str(e)

HTML = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>求职筛选助手</title>
<style>
body{font-family:system-ui,-apple-system,"Microsoft YaHei",sans-serif;max-width:920px;margin:40px auto;padding:20px;color:#222;background:#fafafa}
.card{background:#fff;border-radius:12px;padding:24px;box-shadow:0 2px 8px rgba(0,0,0,.06)}
h1{color:#1a73e8;font-size:22px;margin-top:0}
label{display:block;margin:14px 0 4px;font-weight:600;font-size:14px}
input,select{width:100%;max-width:420px;padding:9px;font-size:15px;border:1px solid #ccc;border-radius:6px;box-sizing:border-box}
button{margin-top:20px;padding:10px 26px;font-size:16px;background:#1a73e8;color:#fff;border:none;border-radius:6px;cursor:pointer}
button:hover{background:#1557b0}
pre{white-space:pre-wrap;word-wrap:break-word;background:#f6f8fa;border:1px solid #e1e4e8;border-radius:8px;padding:16px;font-size:14px;line-height:1.6;font-family:inherit}
#loading{display:none;margin-top:16px;color:#1a73e8;font-size:14px}
</style></head>
<body>
<div class="card">
<h1>🎯 应届生求职筛选助手</h1>
<form id="f">
  <label>城市</label><input name="city" placeholder="如：南宁 / 深圳">
  <label>专业 / 方向</label><input name="major" placeholder="如：自动化 / Python / 嵌入式">
  <label>期望薪资</label><input name="salary" placeholder="如：6k-10k / 面议">
  <label>身份</label><select name="fresh"><option>应届</option><option>往届</option></select>
  <br><button type="submit">帮我筛</button>
</form>
<div id="loading">⏳ 正在搜索 + 筛选中，稍等几秒…</div>
<div id="result"></div>
</div>
<script>
function esc(s){return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}
document.getElementById('f').addEventListener('submit', function(e){
  e.preventDefault();
  const fd = new FormData(this);
  document.getElementById('loading').style.display='block';
  document.getElementById('result').innerHTML='';
  fetch('/search', {method:'POST', body:fd})
    .then(r=>r.json())
    .then(d=>{
      document.getElementById('loading').style.display='none';
      document.getElementById('result').innerHTML='<pre>'+esc(d.result)+'</pre>';
    })
    .catch(err=>{
      document.getElementById('loading').style.display='none';
      document.getElementById('result').innerHTML='<pre>出错了：'+err+'</pre>';
    });
});
</script>
</body></html>"""

@app.route("/")
def index():
    return render_template_string(HTML)

@app.route("/search", methods=["POST"])
def search_api():
    city = request.form.get("city", "").strip()
    major = request.form.get("major", "").strip()
    salary = request.form.get("salary", "").strip()
    fresh = request.form.get("fresh", "应届")
    if not city or not major:
        return jsonify({"result": "请填写城市和专业/方向"})
    raw = search("%s %s 应届生 校招 招聘" % (city, major), 6)
    result = filter_jobs(city, major, salary, fresh, raw)
    return jsonify({"result": result})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=False)
