"""
🐸 量化信号扫描 - 自动更新监控
后台运行，每隔一段时间检查GitHub是否有更新，有则自动拉取并重启Streamlit

使用方法：
  python auto_update.py          # 前台运行
  python auto_update.py --daemon  # 后台守护进程模式（仅Linux/Mac）

更新逻辑：
  1. git fetch 检查远程是否有新commit
  2. 有更新 → git pull → 重启Streamlit
  3. 无更新 → 什么都不做
"""

import subprocess
import sys
import os
import time
import signal
import threading

CHECK_INTERVAL = 300  # 5分钟检查一次
REPO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BRANCH = "main"
streamlit_process = None


def run_cmd(cmd, cwd=None):
    """执行命令并返回输出"""
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True,
            cwd=cwd or REPO_DIR, timeout=30
        )
        return result.stdout.strip(), result.returncode
    except Exception as e:
        return str(e), 1


def check_and_update():
    """检查GitHub是否有更新，有则拉取"""
    # fetch远程最新
    out, code = run_cmd("git fetch origin")
    if code != 0:
        print(f"  [WARN] git fetch 失败: {out}")
        return False

    # 对比本地和远程
    out, code = run_cmd(f"git rev-parse HEAD")
    local_hash = out
    out, code = run_cmd(f"git rev-parse origin/{BRANCH}")
    remote_hash = out

    if local_hash == remote_hash:
        return False  # 无更新

    print(f"  📦 发现更新！")
    print(f"     本地: {local_hash[:8]}")
    print(f"     远程: {remote_hash[:8]}")

    # 拉取更新
    out, code = run_cmd(f"git pull origin {BRANCH}")
    if code != 0:
        print(f"  [ERROR] git pull 失败: {out}")
        return False

    # 更新依赖
    run_cmd("pip install -r cloud_deploy/requirements.txt -q")

    print(f"  ✅ 代码已更新到最新版本")
    return True


def start_streamlit():
    """启动Streamlit"""
    global streamlit_process
    if streamlit_process and streamlit_process.poll() is None:
        streamlit_process.terminate()
        streamlit_process.wait(timeout=10)

    print("  🚀 启动 Streamlit...")
    streamlit_process = subprocess.Popen(
        [sys.executable, "-m", "streamlit", "run",
         "cloud_deploy/app.py",
         "--server.port", "8501",
         "--server.headless", "true"],
        cwd=REPO_DIR,
    )
    print(f"  ✅ Streamlit 已启动 (PID: {streamlit_process.pid})")
    print(f"  🌐 打开浏览器访问: http://localhost:8501")


def stop_streamlit():
    """停止Streamlit"""
    global streamlit_process
    if streamlit_process and streamlit_process.poll() is None:
        print("  🛑 正在停止 Streamlit...")
        streamlit_process.terminate()
        try:
            streamlit_process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            streamlit_process.kill()
        print("  ✅ Streamlit 已停止")


def monitor_loop():
    """主监控循环"""
    print("=" * 50)
    print("  🐸 量化扫描 - 自动更新监控")
    print(f"  检查间隔: {CHECK_INTERVAL // 60} 分钟")
    print(f"  仓库目录: {REPO_DIR}")
    print("=" * 50)
    print()

    # 首次启动
    start_streamlit()

    while True:
        try:
            time.sleep(CHECK_INTERVAL)
            print(f"\n[{time.strftime('%H:%M:%S')}] 检查更新...")
            if check_and_update():
                stop_streamlit()
                time.sleep(2)
                start_streamlit()
            else:
                print("  无更新")
        except KeyboardInterrupt:
            print("\n\n正在退出...")
            stop_streamlit()
            break
        except Exception as e:
            print(f"  [ERROR] {e}")
            time.sleep(60)


if __name__ == "__main__":
    try:
        monitor_loop()
    except KeyboardInterrupt:
        stop_streamlit()
        print("\n👋 已退出")
