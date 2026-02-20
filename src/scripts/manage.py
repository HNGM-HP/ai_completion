import os
import os
import platform
import subprocess
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]

def get_python_exec():
    """优先返回虚拟环境的 python 路径，找不到则用系统 python。"""
    venv_names = ['venv', '.venv']
    
    is_windows = platform.system().lower() == 'windows'
    
    for vname in venv_names:
        vpath = ROOT_DIR / vname
        if vpath.is_dir():
            if is_windows:
                # Windows venv path
                py_path = vpath / 'Scripts' / 'python.exe'
            else:
                # Linux/Unix venv path
                py_path = vpath / 'bin' / 'python'
                
            if py_path.exists():
                return str(py_path)
    
    # 找不到虚拟环境则回退到当前解释器
    return sys.executable

PYTHON_EXEC = get_python_exec()

def run_cmd(cmd):
    """使用检测到的 Python 解释器执行命令。"""
    print(f"\n\033[96m>>> 正在执行: {cmd}\033[0m") # Cyan color
    try:
        # 如果命令以 python 开头，替换成虚拟环境的 python
        if cmd.strip().startswith("python"):
            cmd = f'"{PYTHON_EXEC}" {cmd.strip()[6:]}'
        
        # 将 src 加入 PYTHONPATH，确保导入正确
        env = os.environ.copy()
        src_dir = ROOT_DIR / 'src'
        
        if 'PYTHONPATH' in env:
            env['PYTHONPATH'] = f"{src_dir}{os.pathsep}{env['PYTHONPATH']}"
        else:
            env['PYTHONPATH'] = str(src_dir)
            
        subprocess.run(cmd, shell=True, check=False, env=env, cwd=str(ROOT_DIR))
    except Exception as e:
        print(f"\033[91m执行出错: {e}\033[0m") # Red color
    print("\n" + "-"*40 + "\n")

def menu():
    print(f"📦 当前使用 Python: {PYTHON_EXEC}")
    while True:
        print("\033[92m" + "="*40) # Green color
        print("   🤖 AI Briefing · 价值优先 - 管理菜单")
        print("="*40 + "\033[0m")
        print("1. [RSS-All] 抓取新闻 + 生成简报")
        print("2. [RSS-Col] 仅抓取 (不生成简报)")
        print("3. [RSS-Gen] 仅生成 (基于已有数据)")
        print("4. [GitHub]  抓取 Repo + 生成简报")
        print("5. [ALL]     执行全流程 (GitHub + RSS + Push)")
        print("6. [Push]    仅推送排队内容 (Feishu)")
        print("----------------------------------------")
        print("7. [Clear]   清空待推送队列 (慎用!)")
        print("8. [Regen]   强制重生成新闻 (清空近期历史)")
        print("9. [ALL-NP]  全流程但不推送 (用于测试)")
        print("10.[Dedup]  清理 24 小时内重复简报")
        print("----------------------------------------")
        print("0. 退出")
        print("\033[92m" + "="*40 + "\033[0m")
        
        choice = input("👉 请输入选项: ").strip()
        
        if choice == '1':
            run_cmd("python src/main.py --run-rss")
        elif choice == '2':
            run_cmd("python src/main.py --rss-collect-only")
        elif choice == '3':
            run_cmd("python src/main.py --rss-brief-only")
        elif choice == '4':
            run_cmd("python src/main.py --run-github")
        elif choice == '5':
            run_cmd("python src/main.py --run-all")
        elif choice == '6':
            run_cmd("python src/main.py --push-only")
        elif choice == '7':
            run_cmd("python src/scripts/clear_pending_briefs.py")
        elif choice == '8':
            run_cmd("python src/scripts/force_regenerate_news.py")
        elif choice == '9':
            run_cmd("python src/main.py --run-all --no-push")
        elif choice == '10':
            run_cmd("python src/scripts/clear_duplicate_briefs.py")
        elif choice == '0':
            print("Bye! 👋")
            break
        else:
            print("❌ 无效选项，请重试")

if __name__ == "__main__":
    # 确保从脚本所在目录运行
    os.chdir(str(ROOT_DIR))
    try:
        menu()
    except KeyboardInterrupt:
        print("\n\nUser interrupted. Exiting...")
