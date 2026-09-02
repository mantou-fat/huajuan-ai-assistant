# 花卷 Huajuan · 个人 AI 助理 Agent

一个能聊天、有记忆、会真动手干活的个人 AI 助理。
全部核心代码纯手写实现，未使用 LangChain 等封装框架，深入到了框架底层的原理。

## 功能亮点

- **电脑遥控（Computer Use）**：对话中说一句"打开抖音""截个屏""锁屏"，AI 真的执行；程序与网站白名单机制防误操作
- **Agent 工具调用**：16 个工具——天气、记账、定时提醒、文件读写、网页搜索、打开程序、截屏、锁屏……
- **长期记忆**：她会记住你告诉过她的事，跨会话不丢，还会在之后的对话里主动提起
- **语音闭环**：对着浏览器说话（语音识别），她开口回答（语音合成）
- **流式输出**：打字机效果，边生成边显示，与工具调用事件完全兼容

## 技术要点

### 自研 Function Calling 框架
工具登记表（TOOLS）+ 派遣表（TOOL_FUNCS）+ 通用参数解包循环，新增一个工具只需三处登记。
涉及真实系统动作（开程序 / 截屏 / 锁屏）的工具带"确认门"设计：先向用户确认，确认后才执行。

### RAG 长期记忆系统
对话中自动提取记忆 → embedding 向量化 → 余弦相似度去重（阈值经调参扫描得出）→ top-3 相似记忆召回注入上下文，实现跨会话记忆与主动回忆。

### 流式输出（SSE）
Flask SSE 接口 + 前端打字机渲染，流式过程与工具调用事件共存——边想、边干、边说。

### 语音闭环
阿里 CosyVoice TTS 语音合成 + 浏览器 Web Speech API 语音识别，说完即答。

### 模型幻觉治理
定位并解决"模型编造工具执行结果 → 谎话写入对话历史 → 后续轮次模仿撒谎"的链式幻觉污染问题，
沉淀出"停服务 → 清历史 → 收紧 prompt → 重启"的治理流程。

### 移动端桥接
Flask API + iOS 快捷指令实现 Siri 传声筒：语音 → HTTP → AI 回复 → 朗读。

## 快速开始

环境要求：Python 3.8+，Windows（电脑遥控功能依赖 Windows API）

安装依赖：

    pip install flask requests openai numpy beautifulsoup4 python-dotenv pillow

1. 在项目根目录创建 `.env` 文件，填入 API Key：

       DASHSCOPE_API_KEY=sk-xxxxxxxx
       # 可选：联网搜索
       TAVILY_API_KEY=tvly-xxxxxxxx

2. 启动服务：

       python app.py

3. 浏览器打开 http://127.0.0.1:5000 ，开始对话

## 项目结构

    bot.py        大脑：Agent 框架、16 个工具、RAG 记忆、心情系统
    app.py        网页服务：Flask、/chat 接口、SSE 流式、TTS
    persona.txt   AI 人设定义
    static/       前端：聊天界面、语音、PWA
