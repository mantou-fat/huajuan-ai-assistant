
from flask import Flask, request, jsonify, send_file, Response, json

from bot import get_reply, clear_history, load_memory, load_status, get_greeting, delete_memory, load_mood,tts,user_location,check_reminders,expense_summary,PHONE_ACTIONS,control_device
import queue
import threading

app = Flask(__name__)

HTML = """
<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>花卷</title>
<link rel="manifest" href="/static/manifest.json">
<style>
  .app {
  display: flex;            /* 开启 flex 布局 */
  flex-direction: column;   /* 子元素竖着排 */
  height: 100vh;            /* 占满整个屏幕高度 */
  background-image: url('bg.jpg');   /* 图片文件名 */
  background-size: cover;            /* 铺满整个区域不变形 */
  background-position: center;       /* 居中显示 */
}
.header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  background-color: #4CAF50;
  color: white;
  padding: 10px;
  font-size: 20px;
}

.home-bar { padding: 8px 14px; font-size: 13px; background: rgba(255,255,255,0.06); border-bottom: 1px solid rgba(255,255,255,0.08); }
.dev-btn { margin: 2px 6px; padding: 3px 10px; border: none; border-radius: 12px; cursor: pointer; font-size: 12px; background: rgba(255,255,255,0.12); color: #eee; }

.header-btns button {
  background: rgba(255,255,255,0.25);
  color: white;
  border: none;
  border-radius: 8px;
  padding: 5px 12px;
  font-size: 14px;
  margin-left: 8px;
  cursor: pointer;
}
.input-bar input {
  flex: 1;                    /* 输入框吃掉剩余宽度 */
  height: 44px;
  font-size: 16px;
  border: 1px solid #ccc;
  border-radius: 10px;
  padding: 0 12px;
}
.input-bar button {
  height: 44px;
  min-width: 44px;
  font-size: 16px;
  border: none;
  border-radius: 10px;
  background: #4CAF50;
  color: white;
  margin-left: 6px;
  padding: 0 12px;
  cursor: pointer;
}

#chat {
  flex: 1;                  /* 消息区吃掉所有剩余空间 */
  overflow-y: auto;         /* 消息多了能滚动 */
  display: flex;            /* 新加：变 flex 容器 */
  flex-direction: column;   /* 新加：消息竖着排 */
  padding: 15px;            /* 新加：内容别贴边 */
}

.input-bar {
  display: flex;            /* 输入框和按钮横着排 */
  padding: 10px;            /* 内边距，别贴边 */
}

#previewArea {
  padding: 6px 12px;
  margin: 0 10px 6px 10px;
  background: rgba(255,255,255,0.9);
  border: 2px dashed #4CAF50;
  border-radius: 10px;
  text-align: center;
  display: none;
}
#previewArea img {
  max-height: 90px;
  max-width: 180px;
  border-radius: 8px;
  display: inline-block;
}

.user {
  max-width: 70%;               /* 最宽占七成，不会横贯全屏 */
  padding: 10px 14px;           /* 内边距：文字离泡边远一点 */
  border-radius: 12px;          /* 圆角，泡的感觉 */
  background-color: #2f6feb;    /* 深蓝底，配合白色文字可读性好 */
  color: white;                 /* 白字，深底 */
  margin-bottom: 10px;          /* 和下一条消息隔开 */
}

.ai {
  max-width: 70%;
  padding: 10px 14px;
  border-radius: 12px;
  background-color: white;          /* 白色或浅色，不透明的 */
  color: black;                     /* 深色字 */
  margin-bottom: 10px;
}
.row-user { display: flex; justify-content: flex-end; }  /* 整行靠右 */
.row-ai { display: flex; justify-content: flex-start; }   /* 整行靠左 */

.avatar {
  width: 56px; height: 56px;      /* 圆形头像大小 */
  border-radius: 50%;             /* 一半就是正圆 */
  color: yellow;                    /* 文字颜色 */
  font-size: 16px;                /* 字号 */
  display: flex;
  align-items: center;  /* 文字垂直居中 */
  justify-content: center;  /* 文字水平居中 */
  margin: 0 8px;    /* 上下空0，左右各空8像素 */
}
.avatar img {
  width: 100%;
  height: 100%;
  border-radius: 50%;
  object-fit: cover;
  object-position: top center;
}
.play-btn {
  background: rgba(255,255,255,0.85);
  border: none;
  border-radius: 50%;
  width: 28px; height: 28px;
  cursor: pointer;
  font-size: 14px;
  margin: 0 4px;
  flex-shrink: 0;
}
.typing { padding: 10px 14px; }
.typing span {
  display: inline-block;
  width: 6px; height: 6px;
  border-radius: 50%;
  background: gray;
  animation: blink 1s infinite;
}
.typing span:nth-child(2) { animation-delay: 0.2s; }
.typing span:nth-child(3) { animation-delay: 0.4s; }

@keyframes blink {
  0%, 100% { opacity: 0.3; }
  50% { opacity: 1; }
}
.status-bar {
  background: rgba(255,255,255,0.85);
  padding: 6px 14px;
  font-size: 13px;
  color: #555;
  border-bottom: 1px solid #eee;
}
.status-bar span { color: #4CAF50; font-weight: bold; }
.mood-bar,.expense-bar{
  background: rgba(255,255,255,0.85);
  padding: 6px 14px;
  font-size: 13px;
  color: #555;
  border-bottom: 1px solid #eee;
}
.mood-bar span, .expense-bar span { color: #e67e22; font-weight: bold; }
.mem-panel {
  display: none;
  position: fixed; top: 0; right: 0;
  width: 280px; height: 100vh;
  background: rgba(255,255,255,0.95);
  box-shadow: -2px 0 8px rgba(0,0,0,0.15);
  padding: 16px; overflow-y: auto;
  z-index: 100;
}
.mem-panel h3 { font-size: 16px; color: #333; margin-bottom: 12px; }
.mem-panel .item {
  font-size: 13px; color: #555; line-height: 1.6;
  padding: 8px 0; border-bottom: 1px solid #eee;
}
.mem-panel .close-btn {
  position: absolute; top: 12px; right: 14px;
  cursor: pointer; font-size: 20px; color: #999;
}

</style>
</head>
<body>
  <div class = "app">
  <div class = "header">
    <span>🥐 花卷</span>
    <span class="header-btns">
      <button onclick="clearChat()">清空</button>
      <button onclick="showMemory()">记忆</button>
    </span>
  </div>
   <div class="status-bar" id="statusBar" onclick="loadStatus()" title="点击重新加载">__STATUS__</div>
   <div class="mood-bar" id="moodBar" onclick="loadMood()" title="点击重新加载">__MOOD__</div>
   <div class="expense-bar" id="expenseBar" onclick="loadStatus()">本月账本：加载中...</div>
   <div class="home-bar" id="homeBar">我的家：加载中...</div>
   <div id="chat"></div>
   <div id="previewArea" style="display:none"><img id="imgPreview" alt="待发送图片"></div>
   <div class = "input-bar">
  <input id="msg" placeholder="跟花卷说点什么..." onkeydown="if(event.key==='Enter')send()">
  <button onclick="send()">发送</button>
  <button onclick="document.getElementById('imgInput').click()">📷</button>
  <input type="file" id="imgInput" accept="image/*" style="display:none" onchange="pickImg(event)">
  <button id="micBtn" onclick="toggleMic()">🎤</button>

    <button id="voiceBtn" onclick="toggleVoice()">🔈</button>

    </div>
  </div>

  <script>
    if (navigator.geolocation) {
        navigator.geolocation.getCurrentPosition(
            function(pos) {
                fetch('/location', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({lat: pos.coords.latitude, lon: pos.coords.longitude})
                });
            },
            function(err) {
                console.log('定位失败：' + err.message);
            }
        );
    }
  let selectedImg = null;   // 记住当前选的图，没选就是 null

  function pickImg(event) {
    const file = event.target.files[0];
    if (!file) return;
    const reader = new FileReader();              // 浏览器自带的"读文件"工具
    reader.onload = function(e) {
      selectedImg = e.target.result;              // 结果自带 data:image/...;base64, 前缀
      addImgPreview(selectedImg);                 // 输入框上方亮出缩略图
    };
    reader.readAsDataURL(file);                   // 按"文本快递包装"格式读
    event.target.value = '';                      // 清掉选择记录，允许下次选同一张
  }
  function addImgPreview(src) {
    const area = document.getElementById('previewArea');
    document.getElementById('imgPreview').src = src;
    area.style.display = 'block';   // 恢复显示（发送后曾被隐藏，不恢复就"第二次失效"）
  }

  async function send() {
  const input = document.getElementById('msg');
  const msg = input.value.trim();
  if (!msg) return;
  input.value = '';
  const imgToSend = selectedImg;                 // 先把图接住，再清状态
  selectedImg = null;
  document.getElementById('previewArea').style.display = 'none';
  addMsg(msg, 'user');
  const typing = addMsg('●●●', 'ai');          // 占位气泡（先保持打点动画）
  const typingBubble = typing.querySelector('.ai');
  typingBubble.className = 'typing';
  typingBubble.innerHTML = '<span></span><span></span><span></span>';
  let full = '';                                // 攒她的完整回答，TTS 要用
  let started = false;                          // 第一片来了没有
  try {
    const res = await fetch('/chat_stream', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({message: msg, image: imgToSend})
    });
    const reader = res.body.getReader();        // 拧开水龙头
    const decoder = new TextDecoder('utf-8');   // 字节翻译官
    let buf = '';                               // 攒消息的碗
    while (true) {
      const r = await reader.read();            // 接一截
      if (r.done) break;                        // 水管关了 = 流结束
      buf += decoder.decode(r.value, {stream: true});
      const parts = buf.split('\\n\\n');        // 按"消息结束记号"切
      buf = parts.pop();                        // 最后一段可能不完整，留碗里
      for (const line of parts) {
        if (!line.startsWith('data: ')) continue;   // 不是 SSE 格式就跳过
        const d = JSON.parse(line.slice(6));        // 剥掉前缀，剩的是 JSON
        if (d.tool) {
            typingBubble.className = 'ai';
            typingBubble.textContent = '正在调工具：' + d.tool + ' ...';
        }
        if (d.delta) {
          if (!started) {                       // 第一片：占位气泡变身真气泡
            started = true;
            typingBubble.className = 'ai';
            typingBubble.textContent = '';
          }
          typingBubble.textContent += d.delta;  // 打字机逐字追加
          full += d.delta;
        }
        if (d.final) {                          // 定稿版（洗过旁白的全文）
          full = d.final;
        }
        if (d.end) {                            // 收工：气泡换成定稿
          if (full) {
            typingBubble.className = 'ai';
            typingBubble.textContent = full;
          }
        }
      }
    }
        const ttsPromise = fetch('/tts', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({text: full})
    }).then(function(r) { return r.json(); })
      .catch(function() { return null; });
    if (autoPlay) {
      const ttsData = await ttsPromise;
      if (ttsData && ttsData.audio_url) {
        const audio = new Audio(ttsData.audio_url);
        audio.play().catch(function(err) {
          console.log('TTS 播放失败:', err);
        });
      }
    }

  } catch (e) {
    typing.remove();
    addMsg('（网络开小差了，再说一次？）', 'ai');
  }
  loadMood();
}

    function addMsg(text, cls) {
      const chat = document.getElementById('chat');
      const row = document.createElement('div');      // 行容器
      row.className = 'row-' + cls;
      const avatar = document.createElement('div');   // 头像
      avatar.className = 'avatar';
      if (cls === 'user') {
        avatar.textContent = '🙂';
        } else {
        const img = document.createElement('img');
        img.src = avatarFor(currentMood);
        avatar.appendChild(img);
    
    
    }

      const bubble = document.createElement('div');   // 气泡
      bubble.className = cls;
      bubble.textContent = text;
        // 拼装：用户行是 气泡+头像，AI行是 头像+气泡（注意顺序）
      if (cls === 'user') {
        row.appendChild(bubble);
        row.appendChild(avatar);
        }
        else {
        row.appendChild(avatar);
        row.appendChild(bubble);
        const playBtn = document.createElement('button');
        playBtn.className = 'play-btn';
        playBtn.textContent = '🔊';
        playBtn.title = '播放花卷的声音';
        row.appendChild(playBtn);
        }
     chat.appendChild(row);
     chat.scrollTop = chat.scrollHeight;
     return row;  // 返回气泡元素，方便后续修改内容
    }

  </script>
  <script>
    async function clearChat() {
      const chat = document.getElementById('chat');
      chat.innerHTML = '';
      try {
        await fetch('/clear', { method: 'POST' });
      } catch (e) {}
      addMsg('对话已清空。', 'ai');
    }
    let autoPlay = localStorage.getItem('autoplay') === '1';
    updateVoiceBtn();

    function toggleVoice() {
    autoPlay = !autoPlay;
    localStorage.setItem('autoplay', autoPlay ? '1' : '0');
    updateVoiceBtn();
    }

    function updateVoiceBtn() {
    const btn = document.getElementById('voiceBtn');
    btn.textContent = autoPlay ? '🔈' : '🔇';
    btn.title = autoPlay ? '自动朗读：开' : '自动朗读：关';
    }

    async function loadHome() {
      const bar = document.getElementById('homeBar');
      try {
        const res = await fetch('/home');
        const home = await res.json();
        let html = '<span>我的家：</span>';
        for (const key in home) {
          const d = home[key];
          const btn = d.on ? '💡 开' : '🌑 关';
          html += '<button class="dev-btn" onclick="toggleDevice(\'' + d.name + '\')">' + d.name + ' ' + btn + '</button>';
        }
        bar.innerHTML = html;
      } catch (e) {
        bar.innerHTML = '<span>我的家：</span>加载失败';
      }
    }

    async function toggleDevice(name) {
      const res = await fetch('/home/control', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({device: name, action: '查询'})
      });
      const data = await res.json();
      const isOn = data.result.includes('开的');
      await fetch('/home/control', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({device: name, action: isOn ? '关' : '开'})
      });
      loadHome();
    }

    async function loadStatus() {
      
      const bar = document.getElementById('statusBar');
      try {
        const res = await fetch('/status');
        const data = await res.json();
        if (data.reminders && data.reminders.length > 0) {
                  data.reminders.forEach(r => addMsg('🔔 ' + r.content, 'ai'));  
              }  
        if (data.status) {
          bar.innerHTML = '<span>花卷的近况：</span>' + data.status;
        } else {
          bar.innerHTML = '<span>花卷的近况：</span>还没想起来...';
        }
        const ebar = document.getElementById('expenseBar');
        if (ebar && data.expense) {
            ebar.innerHTML = '<span>本月账本：</span>' + data.expense.count + ' 笔 · ' + data.expense.total + ' 元';
        }
      } catch (e) {
        bar.innerHTML = '<span>花卷的近况：</span>加载失败了，刷新页面试试';
      }
    }

    async function showMemory() {
      const old = document.getElementById('memPanel');
        if (old) old.remove();   // 先关掉旧面板再开新的
      const res = await fetch('/memory');
      const mems = await res.json();
      let html = '<div class="mem-panel" id="memPanel" style="display:block">';
      html += '<span class="close-btn" onclick="closeMem()">×</span>';
      html += '<h3>花卷记住的事</h3>';
      if (mems.length === 0) {
        html += '<div class="item">还没记住什么，多跟她聊聊吧～</div>';
      } else {
        mems.forEach(function(m, i) {
        html += '<div class="item">' + m + ' <span style="color:#e74c3c;cursor:pointer" onclick="delMem(' + i + ')">✕</span></div>';
});

      }
      html += '</div>';
      document.body.insertAdjacentHTML('beforeend', html);
    }
    const recognition = new (window.SpeechRecognition || window.webkitSpeechRecognition)();
    recognition.lang = 'zh-CN';
    recognition.interimResults = true;
    recognition.continuous = false;

    let listening = false;

    function toggleMic() {
    if (listening) {
        recognition.stop();
    } else {
        recognition.start();
        listening = true;
        micBtn.textContent = '🎙️';
    }
    }

    recognition.onresult = function (e) {
    let text = '';
    for (let i = 0; i < e.results.length; i++) {
        text += e.results[i][0].transcript;
    }
    document.getElementById('msg').value = text;
    };

    recognition.onend = function () {
    listening = false;
    micBtn.textContent = '🎤';
    };
    let currentMood = '';   // 花卷当前的心情文字

    function avatarFor(mood) {
    if (!mood) return '/static/avatar.png';
    if (mood.includes('😊') || mood.includes('😄') || mood.includes('😆')) return '/static/avatar_happy.png';
    if (mood.includes('😢') || mood.includes('😔') || mood.includes('😕')) return '/static/avatar_sad.png';
    if (mood.includes('😠') || mood.includes('😡')) return '/static/avatar_angry.png';
    if (mood.includes('😐') || mood.includes('😌')) return '/static/avatar_calm.png';
    return '/static/avatar.png';
    }


    async function loadMood() {
      const bar = document.getElementById('moodBar');
      try {
        const res = await fetch('/mood');
        const data = await res.json();
        if (data.mood) {
          currentMood = data.mood;
          bar.innerHTML = '<span>花卷的心情：</span>' + data.mood;
        } else {
          bar.innerHTML = '<span>花卷的心情：</span>心情还没想起来...';
        }
      } catch (e) {
        bar.innerHTML = '<span>花卷的心情：</span>加载失败了，刷新页面试试';
      }
    }

    loadStatus();               // 页面打开时加载近况
    loadHome();                 // 页面打开时加载家里设备状态
    setInterval(loadStatus, 10000); // 10秒后再试一次，防止偶发失败

    async function delMem(i) {
      await fetch('/memory/delete', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({index: i})
      });
      showMemory();  // 重新拉一遍记忆刷新面板
    }

    function closeMem() {   // 关闭记忆面板
      const p = document.getElementById('memPanel');
      if (p) p.remove();
    }

    async function greet() {    // 页面打开时，看花卷有没有话想主动说
      try {
        const res = await fetch('/greet');
        const data = await res.json();
        if (data.greeting) {
          addMsg(data.greeting, 'ai');
        }
      } catch (e) {}
    }
    greet();
        // 播放语音：点 🔊 按钮，把这条回复的文字拿去合成声音播放
    document.getElementById('chat').addEventListener('click', async function(e) {
      const btn = e.target.closest('.play-btn');
      if (!btn) return;
      const row = btn.closest('.row-ai');
      const bubble = row.querySelector('.ai');
      const text = bubble.textContent.trim();
      if (!text) return;
      btn.textContent = '⏳';  // 生成中
      try {
        const res = await fetch('/tts', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({text: text})
        });
        const data = await res.json();
        if (data.audio_url) {
          const audio = new Audio(data.audio_url);
          audio.play();
          btn.textContent = '🔊';
        } else {
          btn.textContent = '❌';
          setTimeout(function(){ btn.textContent = '🔊'; }, 2000);
        }
      } catch (err) {
        btn.textContent = '❌';
        setTimeout(function(){ btn.textContent = '🔊'; }, 2000);
      }
    });
        if ('serviceWorker' in navigator) {
      navigator.serviceWorker.register('/static/sw.js');
    }

  </script>

</body>
</html>
"""

@app.route("/")
def index():
    # 直接在服务器端把近况写进页面（不靠JS加载），刷新页面必然显示
    data = load_status()
    mood_data = load_mood()
    mood = mood_data.get("mood") or "心情还没想起来..."
    initial = data.get("status") or "还没想起来..."
    page = HTML.replace("__STATUS__", "<span>花卷的近况：</span>" + initial)
    page = page.replace("__MOOD__", "<span>花卷的心情：</span>" + mood)
    # no-store: 告诉浏览器别缓存这个页面，每次都拿最新的
    return page, 200, {"Cache-Control": "no-store"}

@app.route("/location", methods=["POST"])
def receive_location():
    data = request.get_json()
    user_location["lat"] = data.get("lat")
    user_location["lon"] = data.get("lon")
    print("收到定位：", user_location)
    return jsonify({"ok": True})
@app.route("/chat", methods=["POST"])
def chat_api():
    data = request.get_json()
    reply = get_reply(data.get("message", ""))
    return jsonify({"reply": reply, "action": PHONE_ACTIONS or None})

@app.route("/clear", methods=["POST"])
def clear_api():
    clear_history()
    return jsonify({"ok": True})

@app.route("/bg.jpg")
def bg():
    return send_file("bg.jpg")

@app.route("/status")
def status_api():
    data = load_status()
    data["expense"] = expense_summary()
    data["reminders"] = check_reminders()
    return jsonify(data)

@app.route("/mood")
def mood_api():
    return jsonify(load_mood())

@app.route("/memory")
def memory_api():
    return jsonify(load_memory())

@app.route("/memory/delete", methods=["POST"])
def memory_delete_api():
    data = request.get_json()
    delete_memory(data.get("index", -1))
    return jsonify({"ok": True})

@app.route("/greet")
def greet_api():
    return jsonify({"greeting": get_greeting()})
@app.route("/tts", methods=["POST"])
def tts_api():
    data = request.get_json()
    text = data.get("text", "")
    if not text:
        return jsonify({"error": "没有文字"}), 400
    try:
        audio_path = tts(text)   # 生成声音，得到 /static/tts_latest.wav
        return jsonify({"audio_url": audio_path})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
@app.route("/home")
def home_api():
    with open("home.json", "r", encoding="utf-8") as f:
        return jsonify(json.load(f))

@app.route("/home/control", methods=["POST"])
def home_control_api():
    data = request.get_json()
    result = control_device(data.get("device", ""), data.get("action", ""))
    with open("home.json", "r", encoding="utf-8") as f:
        return jsonify({"result": result, "home": json.load(f)})
    
@app.route("/chat_stream", methods=["POST"])
def chat_stream_api():
    data = request.get_json()
    msg = data.get("message", "")
    img = data.get("image")

    def generate():
        q = queue.Queue()

        def push(text):
            q.put(text)                      # 碎片扔上传送带
        def tool_push(name,args):
            q.put(("tool",name))
        def worker():
            reply = ""
            try:
                reply = get_reply(msg, on_text=push, on_tool=tool_push, image=img)
            finally:
                q.put(("final", reply))          # 定稿全文（已洗过旁白）
                q.put(None)                      # 哨兵：干完活的信号

        threading.Thread(target=worker).start()

        while True:
            piece = q.get()                  # 阻塞等，来一个发一个
            if piece is None:                # 收到哨兵
                yield "data: " + json.dumps({"end": True}) + "\n\n"
                break
            if isinstance(piece, tuple):        # 元组 = 打了标签的包裹
                if piece[0] == "final":         # ("final", 定稿全文)
                    yield "data: " + json.dumps({"final": piece[1]}, ensure_ascii=False) + "\n\n"
                    continue
                yield "data: " + json.dumps({"tool": piece[1]}) + "\n\n"
                continue
            yield "data: " + json.dumps({"delta": piece}, ensure_ascii=False) + "\n\n"

    return Response(generate(), mimetype="text/event-stream")    
if __name__ == "__main__":
    # 0.0.0.0 = 监听所有网卡：同一 WiFi 下手机也能通过电脑的局域网 IP 访问
    app.run(host="0.0.0.0", port=5000, debug=True)

