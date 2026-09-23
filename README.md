# 花卷 Huajuan · 个人 AI 助理 Agent

一个能聊天、有长期记忆、会指挥多个子 AI、能真实执行任务的个人 AI 助理。
核心代码（Function Calling、Agent 编排、RAG 记忆）全部手写实现，**未使用 LangChain 等封装框架**。

> **3 秒看懂**：① 说"查天气/记账/开程序"，它**真的调工具执行**，不是嘴上答应；
> ② 有**长期记忆**（对话自动入库、每轮现场召回）；③ 能**指挥 4 个子 AI 并行干活**；
> ④ 自带 **56 项自动化回归**，改一行都知道有没有弄坏。→ 30 秒跑起来见下方「快速开始」。

> ⚠️ 仓库里的 `persona.txt`（个人人设）与 `knowledge_base.txt`（个人知识库）是隐私文件，已被 .gitignore 排除。
> 克隆后请先执行：
> ```
> copy persona.example.txt persona.txt
> copy knowledge_base.example.txt knowledge_base.txt
> ```

## 30 秒看效果

花卷的 `make_pdf` / `make_ppt` 工具能把同一篇 Markdown 变成排版好的 PDF 和 PPT，输入见 [`demo/demo.md`](demo/demo.md)：

- 📄 生成的 PDF：**[demo/demo.pdf](demo/demo.pdf)**（GitHub 上可直接预览第一页）
- 📊 生成的 PPT：**[demo/demo.pptx](demo/demo.pptx)**
- 📝 生成的 Word：**[demo/demo.docx](demo/demo.docx)**

同一套生成器，可复现：

```
python demo\make_demo.py
```

## 功能特性

- **24 个 Agent 工具**：查时间/天气、记账查账、定时提醒、文件盒读写、网页阅读、联网搜索、知识库检索、
  子 AI 派遣、智能家居控制、电脑遥控（开程序/截屏/锁屏）等；**新增一个工具只需三处登记**
- **多 Agent 派遣**：主 AI 当老板，通过 `dispatch_agent` 把任务派给 4 个子 AI
  （翻译官 / 文案师 / 资料员 / 代码员），线程池并行执行、结果保序回收
- **长文自动 Map-Reduce**：3000 字以上 + 总结意图 → 自动分块并行摘要 → 主模型合并（实测 1.1 万字约 26s 输出要点）
- **RAG 长期记忆**：对话自动提取记忆 → embedding 向量化 → 余弦去重 → 每轮现场检索 top-3 注入
- **幻觉治理**：规则引擎硬路由（正则意图识别 + tool_choice 强制调用），时间/天气/记账/开程序等指令
  经自动化断言验证**必走真实工具**，杜绝"嘴上说做了、实际没调工具"
- **多模态 + 语音闭环**：qwen-vl 图片问答 + YOLOv8 摄像头实时检测；SSE 打字机流式；
  TTS 长文切段并行合成（1000 字 81s → 25s）；浏览器语音识别
- **安全**：ACCESS_TOKEN 访问门（HttpOnly Cookie + 恒定时间比较）、XSS 转义、请求体上限、
  高影响电脑动作先经用户确认
- **自动化回归**：`体检.py` 一键体检，56 项检查（≈70 个场景）+ 真 API 链路自动全量验证
  （数据自动备份恢复）；另含"重名定义/漏 import"静态自检，专抓静默失效

## 技术要点

- **自研 Function Calling 框架**：`TOOLS`（JSON Schema 登记）+ `TOOL_FUNCS`（执行表）+
  通用参数解包循环；工具执行全兜底（参数错误/未知工具不崩对话，错误喂回模型重试）
- **Agent 编排**：ThreadPoolExecutor 并行派遣 + pool.map 保序回收；map-reduce 自动分块
- **RAG 记忆**：对话后自动提取 → 向量化 → 余弦去重（阈值经调参扫描）→ 现场召回注入；失败自动降级
- **工程可靠性**：多线程服务避免 SSE 长聊天冻结其他请求（并发排队 92s → 0s）；
  独立排查过"模型编造工具结果污染历史"等真实问题

## 项目结构

```
bot.py          编排层：记忆/历史、SSE 流式调用、工具循环、审计日志
tools.py        工具层：24 个工具 + TOOLS 登记表 + TOOL_FUNCS 执行表 + TTS
persona_state.py 人设与状态：人设文本、近况、心情、见面记录、主动问候
rules.py        规则引擎：意图硬路由、旁白清洗、时间解析（纯函数，可单测）
rag.py          知识库：embedding、分块入库、余弦检索
memory.py       长期记忆：召回、去重合并
config.py       配置：路径、白名单、阈值、可重试工具表
llm.py          模型客户端与密钥
app.py          Flask 网页端：SSE 流式、TTS、登录门卫
体检.py         一键自动化回归脚本（python 体检.py）
persona.txt     人设（个人隐私，不入库；用 persona.example.txt 代替）
knowledge_base.txt  本地知识库（个人隐私，不入库；用 knowledge_base.example.txt 代替）
static/         前端资源（聊天页、PWA、语音）
huajuan_files/  文件盒：Agent 可读写的文件目录
```

> 分层原则：配置只放配置；会被重新赋值的全局状态留在它自己的文件里（`global` 才有意义）；
> 列表这类共享对象可跨模块引用。`bot.py` 只负责编排，工具只负责干活。

## 快速开始

环境：Python 3.10+（Windows），依赖：

```
pip install -r requirements.txt
```

> 可选依赖（本地小模型 / YOLO 摄像头 / 浏览器自动化）在 `requirements.txt` 里以注释标出，用到再装。

1. 准备 `persona.txt` 与 `knowledge_base.txt`（见开头说明）
2. 创建 `.env`：

```
DASHSCOPE_API_KEY=sk-xxx          # 阿里云百炼，聊天/工具/embedding 必需
TAVILY_API_KEY=tvly-xxx           # 可选：联网搜索
ACCESS_TOKEN=随便设一串长密码      # Web 访问钥匙（可选但强烈建议）
BJS_API_KEY=sk-xxx                # 可选：Fun-Music 唱歌（需单独开通权限）
```

3. 启动：

```
python app.py
```

4. 浏览器打开 `http://127.0.0.1:5000`（配了 ACCESS_TOKEN 则先进登录页输钥匙）

### 局域网/手机访问

- 默认监听 `0.0.0.0:5000`，同一 WiFi 下手机可用 `http://电脑IP:5000` 访问
- 配了 ACCESS_TOKEN 后，任何设备都要先登录
- ⚠️ 注意：**PWA 安装、语音识别、浏览器定位在 http 局域网下会被浏览器禁用**（安全上下文限制），
  如需完整手机体验，请配置 HTTPS（自签证书或 Tailscale/Caddy）
- 生产部署建议用多线程 WSGI（如 waitress）替代 Flask 开发服务器

### 自动化测试

```
python 体检.py
```

## 示例玩法

- "现在几点了？" / "北京今天天气怎么样？" —— 必走真实工具查询
- "我今天买咖啡花了 18.5 元，记一下" —— 真实记账落盘
- "派翻译官把这句话翻译成英文：今天天气真好" —— 多 Agent 派遣
- "帮我打开记事本" —— 真实打开本机程序（会先跟你确认）
- 粘贴一篇 3000 字长文 + "总结要点" —— 自动 map-reduce 分块总结
- "读一下文件盒里的 心愿清单.txt" —— 文件盒读写

## License

MIT
