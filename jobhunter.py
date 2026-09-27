# -*- coding: utf-8 -*-
"""应届生求职筛选助手 MVP v0.3
流程：填条件 → 实时搜索 → qwen 筛出严格 JSON → 前端渲染成表格（链接可点）。"""
import json
import re
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

def search_multi(city, major):
    """多路搜索：用几个不同关键词各搜一遍，按 URL 去重合并，覆盖更全。"""
    queries = [
        "%s %s 应届生 校招 招聘" % (city, major),
        "%s %s 招聘 岗位 本科" % (city, major),
    ]
    seen = set()
    merged = []
    for q in queries:
        for item in search(q, 8):
            url = item.get("url", "")
            if url and url in seen:
                continue
            if url:
                seen.add(url)
            merged.append(item)
    return merged

def _parse_json(text):
    """从模型输出里抠出 JSON 数组：直接解析失败就截 [..] 再试。"""
    text = (text or "").strip()
    try:
        return json.loads(text)
    except Exception:
        pass
    m = re.search(r"\[[\s\S]*\]", text)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            pass
    return None

def filter_jobs(city, major, salary, fresh, raw_results):
    """把原始搜索结果塞给 qwen，筛出真实对口可投递的公司，输出严格 JSON 数组。
    返回解析后的 list[dict]；失败返回 None。"""
    blob = "\n\n".join(
        "[%d] %s\n%s\n%s" % (i, item.get("title", ""), item.get("url", ""), (item.get("content") or "")[:400])
        for i, item in enumerate(raw_results, 1)
    )
    prompt = (
        "你是应届生求职筛选助手。用户条件：城市=%s，专业/方向=%s，期望薪资=%s，身份=%s。\n\n"
        "下面是联网搜到的原始结果。请从中筛出【真实、对口、可投递】的公司/岗位，"
        "剔除广告、培训贷、中介、无关内容和重复项。\n\n%s\n\n"
        "输出严格的 JSON 数组，每个元素是对象，键为 company/job/url/reason/salary，例如：\n"
        '[{"company":"公司名","job":"岗位","url":"官网或投递链接","reason":"匹配理由","salary":"薪资范围"}]\n'
        "只输出这个 JSON 数组本身，不要任何其他文字、不要解释、不要 markdown 代码块。最多20条。"
        % (city, major, salary, fresh, blob)
    )
    try:
        resp = client.chat.completions.create(
            model="qwen-turbo",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=1400,
        )
        return _parse_json(resp.choices[0].message.content)
    except Exception:
        return None

HTML = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>求职筛选助手</title>
<style>
body{font-family:system-ui,-apple-system,"Microsoft YaHei",sans-serif;max-width:960px;margin:40px auto;padding:20px;color:#222;background:#fafafa}
.card{background:#fff;border-radius:12px;padding:24px;box-shadow:0 2px 8px rgba(0,0,0,.06)}
h1{color:#1a73e8;font-size:22px;margin-top:0}
label{display:block;margin:14px 0 4px;font-weight:600;font-size:14px}
input,select{width:100%;max-width:420px;padding:9px;font-size:15px;border:1px solid #ccc;border-radius:6px;box-sizing:border-box}
button{margin-top:20px;padding:10px 26px;font-size:16px;background:#1a73e8;color:#fff;border:none;border-radius:6px;cursor:pointer}
button:hover{background:#1557b0}
table{width:100%;border-collapse:collapse;margin-top:18px}
th,td{border:1px solid #e1e4e8;padding:8px 10px;text-align:left;font-size:14px;vertical-align:top}
th{background:#f5f5f5;white-space:nowrap}
a{color:#1a73e8}
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
function esc(s){return String(s==null?'':s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');}
document.getElementById('f').addEventListener('submit', function(e){
  e.preventDefault();
  const fd = new FormData(this);
  document.getElementById('loading').style.display='block';
  document.getElementById('result').innerHTML='';
  fetch('/search', {method:'POST', body:fd})
    .then(r=>r.json())
    .then(d=>{
      document.getElementById('loading').style.display='none';
      const box = document.getElementById('result');
      const items = d.items;
      if (Array.isArray(items) && items.length) {
        let html = '<table><tr><th>公司</th><th>岗位</th><th>投递</th><th>匹配理由</th><th>薪资</th></tr>';
        for (const it of items) {
          html += '<tr><td>'+esc(it.company)+'</td><td>'+esc(it.job)+'</td>'+
                  '<td><a href="'+esc(it.url)+'" target="_blank">打开链接</a></td>'+
                  '<td>'+esc(it.reason)+'</td><td>'+esc(it.salary)+'</td></tr>';
        }
        html += '</table>';
        box.innerHTML = html;
      } else {
        box.innerHTML = '<p style="color:#999;margin-top:16px">没解析出结果，稍后再试一次。</p>';
      }
    })
    .catch(err=>{
      document.getElementById('loading').style.display='none';
      document.getElementById('result').innerHTML='<p style="color:#c00">出错了：'+err+'</p>';
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
        return jsonify({"items": []})
    raw = search_multi(city, major)
    items = filter_jobs(city, major, salary, fresh, raw)
    return jsonify({"items": items or []})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=False)
