@echo off
chcp 65001 >nul
setlocal
echo ============================================
echo   花卷 Huajuan —— 一键安装
echo ============================================
echo [1/3] 安装 Python 依赖 ...
python -m pip install -r requirements.txt
if errorlevel 1 (
  echo 依赖安装失败，请先确认已装 Python 3.10+ 且 pip 可用
  pause
  exit /b 1
)

echo.
echo [2/3] 准备人设与知识库（用示例模板，之后可自己改）...
if not exist persona.txt        copy persona.example.txt        persona.txt        >nul
if not exist knowledge_base.txt copy knowledge_base.example.txt knowledge_base.txt >nul

echo.
echo [3/3] 说明：完整对话还需要一个 API 密钥
echo   1) 去阿里云百炼申请 DASHSCOPE_API_KEY
echo   2) 在项目目录新建 .env，写一行：DASHSCOPE_API_KEY=sk-xxx
echo.
echo 完成！启动：python app.py    然后浏览器打开 http://127.0.0.1:5000
echo.
echo ------------------------------------------------------------
echo 只想把 Markdown 变成 PDF/PPT/Word？【不需要任何密钥】
echo   python gen_pdf.py  out.pdf   in.md
echo   python gen_ppt.py  out.pptx  in.md
echo   python gen_docx.py out.docx  in.md
echo ------------------------------------------------------------
echo.
pause
