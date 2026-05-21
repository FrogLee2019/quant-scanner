"""
🐸 量化信号扫描 - 自动更新监控
后台运行，每隔5分钟检查GitHub是否有更新，有则自动拉取并重启Streamlit
"""

import subprocess
import sys
import os
import time

CHECK_INTERVAL = 300  # 5分钟检查一次

# 自动检测项目目录
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_DIR = os.path.normpath(os.path.join(SCRIPT_DIR, "..", ".."))
BRANCH = "main"
streamlit_process = None


def get_python():
    """获取Python路径（兼容便携版）"""
    # 便携版Python
    portable_python = os.path.normpath(os.path.join(REPO_DIR, "..", "python", "python.exe"))
    if os.path.exists(portable_python):
        return portable_python
    # 系统Python
    return sys.executable


def get_git():
    """获取Git路径（兼容便携版）"""
    portable_git = os.path.normpath(os.path.join(REPO_DIR, "..", "git", "bin", "git.exe"))
    if os.path.exists(portable_git):
        return portable_git
    return "git"


def run_cmd(cmd, cwd=None):
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True,
            cwd=cwd or REPO_DIR, timeout=30,
            env={**os.environ, "GIT_SSL_NO_VERIFY": "1"}
        )
        return result.stdout.strip(), result.returncode
    except Exception as e:
        return str(e), 1


def check_and_update():
    git = get_git()
    out, code = run_cmd(f'"{git}" fetch origin')
    if code != 0:
        print(f"  [WARN] git fetch 失败: {out}")
        return False

    out, _ = run_cmd(f'"{git}" rev-parse HEAD')
    local_hash = out
    out, _ = run_cmd(f'"{git}" rev-parse origin/{BRANCH}')
    remote_hash = out

    if local_hash == remote_hash:
        return False

    print(f"  📦 发现更新！")
    print(f"     本地: {local_hash[:8]}")
    print(f"     远程: {remote_hash[:8]}")

    out, code = run_cmd(f'"{git}" pull origin {BRANCH}')
    if code != 0:
        print(f"  [ERROR] git pull 失败: {out}")
        return False

    python = get_python()
    pip = os.path.join(os.path.dirname(python), "Scripts", "pip.exe")
    if not os.path.exists(pip):
        pip = os.path.join(os.path.dirname(python), "Scripts", "pip")
    run_cmd(f'"{pip}" install -r cloud_deploy/requirements.txt -q')

    print(f"  ✅ 代码已更新到最新版本")
    return True


def start_streamlit():
    global streamlit_process
    if streamlit_process and streamlit_process.poll() is None:
        streamlit_process.terminate()
        streamlit_process.wait(timeout=10)

    python = get_python()
    print("  🚀 启动 Streamlit...")
    streamlit_process = subprocess.Popen(
        [python, "-m", "streamlit", "run",
         "cloud_deploy/app.py",
         "--server.port", "8501",
         "--server.headless", "true"],
        cwd=REPO_DIR,
    )
    print(f"  ✅ Streamlit 已启动 (PID: {streamlit_process.pid})")
    print(f"  🌐 打开浏览器访问: http://localhost:8501")


def stop_streamlit():
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
    print("=" * 50)
    print("  🐸 量化扫描 - 自动更新监控")
    print(f"  检查间隔: {CHECK_INTERVAL // 60} 分钟")
    print(f"  项目目录: {REPO_DIR}")
    print("=" * 50)
    print()

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
