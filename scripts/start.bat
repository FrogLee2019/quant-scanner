@echo off
chcp 65001 >nul
echo ========================================
echo   🐸 量化信号扫描 - 自动更新启动器
echo ========================================
echo.

:: 进入项目目录
cd /d "%~dp0.."

:: 1. 拉取最新代码
echo [1/3] 正在从GitHub拉取最新代码...
git pull origin main
if %errorlevel% neq 0 (
    echo ⚠️ 拉取失败，使用本地版本继续运行
)
echo.

:: 2. 安装/更新依赖
echo [2/3] 检查依赖...
pip install -r cloud_deploy/requirements.txt -q
echo.

:: 3. 启动Streamlit
echo [3/3] 启动量化扫描工具...
echo.
echo ============================================
echo   浏览器会自动打开 http://localhost:8501
echo   关闭此窗口即可停止运行
echo ============================================
echo.

streamlit run cloud_deploy/app.py --server.port 8501 --server.headless true

pause
